"""DAILY_STOP actions and the daily-loss alert producers (Phase 21, plan 21-10; D-12, D-13, D033).

Given the day verdict of `src/risk/daily_loss.py` (plan 21-05), `enforce_daily_state` does what
D033 says for a latched DAILY_STOP: it cancels every resting ENTRY of a placed plan and keeps
the protective stops of the open positions; then it alerts.

- **Cancel first, alert after (WR-C8).** Every cancel goes through `expire_pending_entry` with
  the trigger `daily_stop` (act first, verify with a query, audit). The alert is produced after
  all cancels, so a journal outage on the alert path never delays a risk-reducing cancel.
- **Never a protective cancel.** Only ENTRY-role ids of known placed plans are cancelled. This
  module calls no `cancel_algo_order`, no `cancel_untriggered_protectives` and no protective-leg
  helper, and it opens nothing (D-12, F-013, F-963).
- **Not SAFE_MODE (Pitfall 7).** DAILY_STOP is a daily latch that ends at the next UTC day;
  SAFE_MODE exit needs a clean reconcile and an operator. This module touches neither.
- **The latch is held elsewhere (D-14).** The service of plan 21-13 persists the latch from
  `verdict.latch_now` and decides `verdict.alerts_due`; this module reads both and persists
  nothing. A later call while the latch holds is the retry of a cancel that did not finish:
  nothing is retried inside one call, and a placement is never re-sent (D080).
- **Gate.** The cancels use the adapter, whose REST gate refuses during a 429/418 pause; a
  refusal is recorded for that plan and the remaining entries are still cancelled. Nothing
  bypasses the gate (D081).
- **Missing day state.** A missing or unreadable persisted day state while exposure exists
  produces the existing `DB_FAILURE` alert with the reason `DAY_STATE_MISSING` or
  `DAY_STATE_UNREADABLE` and cancels nothing (D-07). The other blocked reasons are NO_TRADE only.
- **A fill is not ours.** A FILLED_OR_PARTIAL verdict is left to the protection coordinator. An
  open system ENTRY order that matches no placed plan is reported in `unmatched_entry_orders`,
  never guessed at or cancelled (D082, alert-only spirit).
- **Alert fields.** Subject `utc-day-YYYY-MM-DD`, an upper-case reason, no amount, no equity.
- **An incomplete cancel is alerted (review WR-07).** The `DAILY_STOP` alert is due once, on the
  call that latches. A refused or unverified cancel (`not_cancelled`, `unverified`) and an open
  system ENTRY order with no placed plan (`unmatched_entry_orders`) are alerted on EVERY call
  that finds them, under the same event with the reasons `ENTRY_CANCEL_INCOMPLETE` and
  `UNMATCHED_ENTRY_ORDER`: the sink dedupes by (event, subject, reason), so the stop alert does
  not swallow them and a repeat inside the dedupe window is only counted.
- **A failed alert is reported (review WR-07).** An exception from the sink is never raised, but
  its event and class name go to `DailyStopOutcome.alerts_failed`. A sink that queued the alert
  and then raised `AuditRecordLost` is listed there too (queued, audit row lost); one that raised
  before queuing lost the alert, and the caller keeps retrying the next call (the incomplete-cancel
  alerts repeat; the one-shot stop alert does not, so the caller should log `alerts_failed`).

Plain data in, plain data out: the caller (Phase 24 composition, fed by the service of plan
21-13) passes the verdict and the placed plans read from the reservation rows of plan 21-12.
Pure of wall clock: `now_utc` is injected.

This producer is NOT wired in a running process until Phase 24; OPS-05 stays incomplete
end-to-end until then. Evidence label: executed tests with the Binance-semantics fake [DESIGN].
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from src.domain.enums import DailyState, OrderRole
from src.execution.cancel_verification import CancelVerdict
from src.execution.manager import ExecutionAdapter, expire_pending_entry
from src.execution.order_ids import derive_client_order_id, role_of_client_id
from src.ops.spill import LocalSpill
from src.risk.daily_loss import (
    BLOCKED_DAY_STATE_MISSING,
    BLOCKED_DAY_STATE_UNREADABLE,
    DayStateVerdict,
)

DAILY_STOP_TRIGGER = "daily_stop"
ALERT_DAILY_STOP = "DAILY_STOP"
ALERT_DAILY_LOSS_WARNING = "DAILY_LOSS_WARNING"
ALERT_DB_FAILURE = "DB_FAILURE"
# Reasons of the extra DAILY_STOP alerts (WR-07): the same event, so the OPS-05 matrix is unchanged.
ALERT_REASON_ENTRY_CANCEL_INCOMPLETE = "ENTRY_CANCEL_INCOMPLETE"
ALERT_REASON_UNMATCHED_ENTRY_ORDER = "UNMATCHED_ENTRY_ORDER"

_ALERT_BY_STATE: dict[DailyState, str] = {
    DailyState.DAILY_STOP: ALERT_DAILY_STOP,
    DailyState.WARNING: ALERT_DAILY_LOSS_WARNING,
}
_DB_FAILURE_REASONS = frozenset({BLOCKED_DAY_STATE_MISSING, BLOCKED_DAY_STATE_UNREADABLE})


class _AlertEmitter(Protocol):
    def alert(
        self,
        *,
        event: str,
        subject: str,
        reason: str,
        now_utc: datetime,
        plan_hash: str | None = None,
        symbol: str | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class PlacedPlanRef:
    """A plan whose entry was placed: its id, its 64-char plan hash and its symbol."""

    trade_plan_id: str
    plan_hash: str
    symbol: str

    def __post_init__(self) -> None:
        if not isinstance(self.trade_plan_id, str) or self.trade_plan_id == "":
            raise ValueError("trade_plan_id must be a non-empty string")
        if not isinstance(self.symbol, str) or self.symbol == "":
            raise ValueError("symbol must be a non-empty string")
        # Raises TypeError / ValueError for a plan hash that is not a 64-char lowercase hex.
        derive_client_order_id(plan_hash=self.plan_hash, role=OrderRole.ENTRY.value)

    @property
    def entry_client_order_id(self) -> str:
        return derive_client_order_id(plan_hash=self.plan_hash, role=OrderRole.ENTRY.value)


@dataclass(frozen=True)
class DailyStopOutcome:
    """What one `enforce_daily_state` call did. Every tuple is sorted.

    `cancelled`: trade plan ids whose entry cancel is verified CANCELED.
    `unverified`: `(trade_plan_id, verdict name)` for FILLED_OR_PARTIAL, STILL_OPEN,
    GONE_NOT_CANCELED and UNKNOWN.
    `not_cancelled`: `(trade_plan_id, exception type name)` for a refused or failing read/cancel.
    `unmatched_entry_orders`: client order ids of open system ENTRY orders with no placed plan.
    `alerts_emitted`: the alert events the sink took without raising (an event repeats when it
    was emitted with two reasons).
    `alerts_failed`: `(event, exception class name)` for each alert whose sink call raised, in
    emission order; never a message (WR-07).
    """

    cancelled: tuple[str, ...]
    unverified: tuple[tuple[str, str], ...]
    not_cancelled: tuple[tuple[str, str], ...]
    unmatched_entry_orders: tuple[str, ...]
    alerts_emitted: tuple[str, ...]
    alerts_failed: tuple[tuple[str, str], ...] = ()


def day_alert_subject(utc_day: date) -> str:
    """The fixed alert subject of a UTC day: `utc-day-YYYY-MM-DD`."""
    return f"utc-day-{utc_day.isoformat()}"


async def _cancel_entries(
    *,
    placed_plans: Iterable[PlacedPlanRef],
    adapter: ExecutionAdapter,
    journal: Any,
    now_utc: datetime,
    spill: LocalSpill | None,
) -> tuple[
    list[str],
    list[tuple[str, str]],
    list[tuple[str, str]],
    list[str],
]:
    cancelled: list[str] = []
    unverified: list[tuple[str, str]] = []
    not_cancelled: list[tuple[str, str]] = []
    unmatched: list[str] = []

    by_symbol: dict[str, dict[str, PlacedPlanRef]] = {}
    for ref in placed_plans:
        by_symbol.setdefault(ref.symbol, {})[ref.entry_client_order_id] = ref

    for symbol in sorted(by_symbol):
        expected = by_symbol[symbol]
        try:
            open_orders = await adapter.snapshot_open_normal_orders(symbol=symbol)
        except Exception as exc:  # noqa: BLE001 - only the type name is kept
            not_cancelled.extend(
                (planned.trade_plan_id, type(exc).__name__) for planned in expected.values()
            )
            continue
        for order in open_orders:
            client_id = order.client_order_id
            if role_of_client_id(client_id) != OrderRole.ENTRY.value:
                continue  # a foreign order, a stop or a take-profit: never ours to cancel here
            match = expected.get(client_id)
            if match is None:
                unmatched.append(client_id)
                continue
            try:
                verdict = await expire_pending_entry(
                    plan_hash=match.plan_hash,
                    symbol=match.symbol,
                    adapter=adapter,
                    journal=journal,
                    now_utc=now_utc,
                    trigger_reason=DAILY_STOP_TRIGGER,
                    spill=spill,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - only the type name is kept
                not_cancelled.append((match.trade_plan_id, type(exc).__name__))
                continue
            if verdict is CancelVerdict.CANCELED:
                cancelled.append(match.trade_plan_id)
            else:
                unverified.append((match.trade_plan_id, verdict.name))
    return cancelled, unverified, not_cancelled, unmatched


def _emit(
    alert_sink: _AlertEmitter,
    *,
    event: str,
    verdict: DayStateVerdict,
    reason: str,
    now_utc: datetime,
    emitted: list[str],
    failed: list[tuple[str, str]],
) -> None:
    try:
        alert_sink.alert(
            event=event,
            subject=day_alert_subject(verdict.utc_day),
            reason=reason,
            now_utc=now_utc,
        )
    except Exception as exc:  # noqa: BLE001 - the latch is the durable record (WR-C6)
        failed.append((event, type(exc).__name__))  # the class name only, never a message
        return
    emitted.append(event)


async def enforce_daily_state(
    *,
    verdict: DayStateVerdict,
    placed_plans: Iterable[PlacedPlanRef],
    adapter: ExecutionAdapter,
    journal: Any,
    alert_sink: _AlertEmitter,
    now_utc: datetime,
    spill: LocalSpill | None = None,
) -> DailyStopOutcome:
    """Act on a day verdict: cancel resting entries at DAILY_STOP, then alert (D-12, D-13).

    Never raises for a per-plan or per-alert failure (`asyncio.CancelledError` passes through);
    the failures are reported in the outcome. Stops and take-profits are never touched.
    """
    cancelled: list[str] = []
    unverified: list[tuple[str, str]] = []
    not_cancelled: list[tuple[str, str]] = []
    unmatched: list[str] = []
    emitted: list[str] = []
    failed: list[tuple[str, str]] = []

    if verdict.state is DailyState.DAILY_STOP:
        cancelled, unverified, not_cancelled, unmatched = await _cancel_entries(
            placed_plans=placed_plans,
            adapter=adapter,
            journal=journal,
            now_utc=now_utc,
            spill=spill,
        )

    if verdict.state is None:
        if verdict.blocked_reason in _DB_FAILURE_REASONS:
            _emit(
                alert_sink,
                event=ALERT_DB_FAILURE,
                verdict=verdict,
                reason=str(verdict.blocked_reason),
                now_utc=now_utc,
                emitted=emitted,
                failed=failed,
            )
    else:
        for state in verdict.alerts_due:
            event = _ALERT_BY_STATE.get(state)
            if event is None:
                continue
            _emit(
                alert_sink,
                event=event,
                verdict=verdict,
                reason=state.value,
                now_utc=now_utc,
                emitted=emitted,
                failed=failed,
            )

    if verdict.state is DailyState.DAILY_STOP:
        # WR-07: the stop alert is one-shot; what the cancels did not finish is alerted on
        # every call that finds it (after the cancels, so a journal outage never delays them).
        for reason, found in (
            (ALERT_REASON_ENTRY_CANCEL_INCOMPLETE, bool(not_cancelled or unverified)),
            (ALERT_REASON_UNMATCHED_ENTRY_ORDER, bool(unmatched)),
        ):
            if found:
                _emit(
                    alert_sink,
                    event=ALERT_DAILY_STOP,
                    verdict=verdict,
                    reason=reason,
                    now_utc=now_utc,
                    emitted=emitted,
                    failed=failed,
                )

    return DailyStopOutcome(
        cancelled=tuple(sorted(cancelled)),
        unverified=tuple(sorted(unverified)),
        not_cancelled=tuple(sorted(not_cancelled)),
        unmatched_entry_orders=tuple(sorted(unmatched)),
        alerts_emitted=tuple(emitted),
        alerts_failed=tuple(failed),
    )


__all__ = [
    "ALERT_DAILY_LOSS_WARNING",
    "ALERT_DAILY_STOP",
    "ALERT_DB_FAILURE",
    "ALERT_REASON_ENTRY_CANCEL_INCOMPLETE",
    "ALERT_REASON_UNMATCHED_ENTRY_ORDER",
    "DAILY_STOP_TRIGGER",
    "DailyStopOutcome",
    "PlacedPlanRef",
    "day_alert_subject",
    "enforce_daily_state",
]
