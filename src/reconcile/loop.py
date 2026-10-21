"""The reconcile loop as a tested library (Phase 20, plan 20-12; EXEC-02, D-01, D-02, D-07, D-18).

`ReconcileLoop.tick(now_utc=...)` is step-driven like the protection coordinator: no sleep, no
clock read (the caller injects `now_utc`), no process. Phase 24 composes it into a running
process; here it is driven by tests with fakes. One tick:

  1. asks the REST gate whether a restriction is known (including GATE_NOT_RESTORED and
     GATE_STATE_UNKNOWN after a restart, plan 20-07). If so it reads nothing, journals
     RECONCILE_SKIPPED_GATE and stops: a pause is never bypassed (D-18). The coordinator's own
     clock-driven deadlines keep running in its step, not here.
     The gate's `recovery_status()` (plan 20-07), when it has one, is copied into the tick rows
     and the report, so LEGACY_IN_MEMORY (no persistence wired) is visible.
  2. stops with RECONCILE_SKIPPED_RESTORE_PENDING while the coordinator's tracked plans are not
     rebuilt (`restore_complete`), so a half-restored view is never read as "no plans".
  3. lets the optional `UnknownEntryResolver` step (D-11, D-12: every UNKNOWN exit goes through it
     with REST_RECONCILE evidence; the loop writes no Order or Position row).
  4. reads the three Binance truth snapshots, then the local side (coordinator views plus
     unresolved intent rows, see `local_intent`), runs compare v2 and classifies each divergence
     with the pure table of `classify`.
  5. enters SAFE_MODE once per distinct reason, delegates stop-related exposure to the
     coordinator (`notify_divergence`, one decision path), alerts, and finally sweeps ORPHAN
     protectives only; it journals one RECONCILE_TICK row.

Fail closed: a failed truth read, a failed local read or a compare error is never agreement. The
tick enters SAFE_MODE (API_DEGRADATION for the exchange reads and compare, DB_FAILURE for the
local source) and compares nothing. A divergence is never explained away.

Staleness of the local side: it is read inside the tick, with no cache, by two synchronous calls
that follow one another with no await between them; a None, a non-sequence or an exception from
either is a failed local read. The truth snapshots are read first, so a coordinator step that
runs between the reads can only make the tick report a divergence (SAFE_MODE, fail closed), never
hide one. Only the operator exits SAFE_MODE (D-15); this module never calls an exit and never
calls a placement method. A foreign or untracked order is alert-only (D-02). A divergence that
cannot be tied to exactly one tracked plan is alerted, never delegated to a guessed owner
(D-01a).

Exception TEXT is never read to decide anything (D-10) and never journaled: payloads carry ids,
kinds, symbols, counts and exception class names.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from src.domain.journal import JournalEvent, content_hash_event_id
from src.execution.execution_limits import (
    ExecutionLimits,
    ExecutionLimitsNotConfigured,
    check_reconcile_cadence,
)
from src.execution.order_ids import plan_hash_prefix_of
from src.reconcile.classify import ALERT_STALE_DATA, DivergenceAction, classify
from src.reconcile.compare import CompareDiff, Divergence, compare
from src.reconcile.feed_freshness import FeedReading, FeedVerdict, assess_feeds
from src.reconcile.local_intent import INACTIVE_STATE_NAMES, derive_local_intent

# --------------------------------------------------------------------------- #
# Journal event types and tick outcomes.
# --------------------------------------------------------------------------- #

RECONCILE_TICK: str = "RECONCILE_TICK"
RECONCILE_SKIPPED_GATE: str = "RECONCILE_SKIPPED_GATE"
RECONCILE_SKIPPED_RESTORE_PENDING: str = "RECONCILE_SKIPPED_RESTORE_PENDING"
RECONCILE_READ_FAILED: str = "RECONCILE_READ_FAILED"
ALERT_SINK_FAILED: str = "ALERT_SINK_FAILED"
#: A step after a successful read failed (SAFE_MODE entry, delegation, sweep, UNKNOWN step).
RECONCILE_ACTION_FAILED: str = "RECONCILE_ACTION_FAILED"

TICK_COMPARED: str = "COMPARED"
TICK_SKIPPED_GATE: str = "SKIPPED_GATE"
TICK_SKIPPED_RESTORE_PENDING: str = "SKIPPED_RESTORE_PENDING"
TICK_READ_FAILED: str = "READ_FAILED"
TICK_SKIPPED_OVERLAP: str = "SKIPPED_OVERLAP"

#: Existing SAFE_MODE reasons (GLOSSARY 9.4) for the failed reads.
SAFE_MODE_API_DEGRADATION: str = "API_DEGRADATION"
SAFE_MODE_DB_FAILURE: str = "DB_FAILURE"
#: SAFE_MODE reason of a stale mark price or a silent user-data feed (GLOSSARY 9.4, D-25).
SAFE_MODE_STALE_FEED: str = "STALE_FEED"

#: Alert reasons and the alert subject of the user-data feed (plan 20-16).
ALERT_REASON_MARK_PRICE_STALE: str = "MARK_PRICE_STALE"
ALERT_REASON_USER_DATA_SILENT: str = "USER_DATA_SILENT"
ALERT_SUBJECT_USER_DATA: str = "USER_DATA"

_ENTITY_TYPE = "ReconcileLoop"
_ENTITY_ID = "reconcile_loop"
_CORRELATION_ID = "reconcile_loop"
_UNKNOWN_REASON = "UNKNOWN"

#: How urgent the owner of a divergence is; SAFE_MODE reasons are entered in ascending order.
_ACTION_URGENCY: dict[DivergenceAction, int] = {
    DivergenceAction.ALERT_ONLY: 0,
    DivergenceAction.SWEEP_ORPHAN: 1,
    DivergenceAction.DELEGATE_TO_COORDINATOR: 2,
}


# --------------------------------------------------------------------------- #
# Protocols: everything is injected, nothing is imported from an adapter or a store.
# --------------------------------------------------------------------------- #


class ReconcileAdapter(Protocol):
    """The three read-only snapshots a tick makes (the real adapter and the fake have them)."""

    async def snapshot_open_normal_orders(self, *, symbol: str | None = None) -> list[Any]: ...

    async def snapshot_open_algo_orders(self, *, symbol: str | None = None) -> list[Any]: ...

    async def snapshot_positions(self, *, symbol: str | None = None) -> list[Any]: ...


class GateRestrictionSource(Protocol):
    """`RestRateLimitGate.restriction()`: None, or an object with a `reason` text."""

    def restriction(self) -> Any | None: ...


class ProtectionView(Protocol):
    """The reconcile hooks of the protection coordinator (plan 20-09)."""

    def protections(self) -> Sequence[Any]: ...

    def notify_divergence(self, plan_hash: str, kind: str) -> bool: ...

    @property
    def restore_complete(self) -> bool: ...


class ReconcileAlertSink(Protocol):
    """Where an operator alert goes (plan 20-13's `JournalFirstAlertSink` satisfies this)."""

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


class SafeModeGate(Protocol):
    """What the loop uses of `SafeModeController`: durable state and entering. Never an exit."""

    @property
    def is_durable(self) -> bool: ...

    @property
    def in_safe_mode(self) -> bool: ...

    def enter_safe_mode(self, *, reason: str, now_utc: datetime | None = None) -> None: ...


class UnresolvedIntentSource(Protocol):
    """`ExecutionIntentStore.list_unresolved_intents()`, the only store call of the loop."""

    def list_unresolved_intents(self) -> Sequence[Any]: ...


class OrphanSweeperLike(Protocol):
    """`OrphanSweeper.sweep`: the cancel-only path for ORPHAN_PROTECTIVE divergences."""

    async def sweep(self, diff: Any, *, position_verifier: Any, now_utc: datetime) -> Any: ...


class JournalSink(Protocol):
    """The journal surface: `record(event)`."""

    def record(self, event: Any) -> None: ...


class UnknownEntryStepper(Protocol):
    """`UnknownEntryResolver.step`: the only way an UNKNOWN intent leaves UNKNOWN (D-11)."""

    async def step(self, *, now_utc: datetime) -> Any: ...


class FeedSource(Protocol):
    """The latest feed times (plan 20-16); Phase 24 binds it to the supervisor and mark prices."""

    def read_feed(self) -> FeedReading: ...


class _UnusableRows(Exception):
    """A snapshot answered with something that is not a list of rows."""


# --------------------------------------------------------------------------- #
# The report of one tick.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TickReport:
    """What one tick saw and did.

    `agreement` is None when no compare ran. `stale_symbols` and `user_data_silent` are the feed
    verdict of the tick (plan 20-16; empty / False without a feed source). `delegated` holds
    `(plan_hash, kind)` pairs the coordinator accepted; `undelegated` holds `(symbol, kind)`
    pairs of stop-related divergences that reached no coordinator plan (several or no candidate,
    or an untracked plan): they were alerted only. `swept` and `sweep_skipped` echo the sweeper
    outcome. `action_failures` names the steps that failed after a read succeeded;
    `failed_source` names the read that failed.
    """

    outcome: str
    now_utc: datetime
    agreement: bool | None = None
    divergences: tuple[Divergence, ...] = ()
    safe_mode_reasons: tuple[str, ...] = ()
    delegated: tuple[tuple[str, str], ...] = ()
    undelegated: tuple[tuple[str, str], ...] = ()
    alerts_sent: int = 0
    alerts_failed: int = 0
    swept: tuple[tuple[str, str], ...] = ()
    sweep_skipped: tuple[tuple[str, str], ...] = ()
    gate_reason: str | None = None
    gate_recovery_status: str | None = None
    failed_source: str | None = None
    action_failures: tuple[str, ...] = ()
    unknown_entries: Any = None
    stale_symbols: tuple[str, ...] = ()
    user_data_silent: bool = False


# --------------------------------------------------------------------------- #
# The loop.
# --------------------------------------------------------------------------- #


class ReconcileLoop:
    """One reconcile tick per call (see the module docstring).

    Args:
        adapter: the three read-only snapshots.
        gate: the REST rate-limit gate (`restriction()`).
        safe_mode: a DURABLE controller; the constructor refuses one with `is_durable` False.
        intent_store: the unresolved-intent source.
        protection: the coordinator's reconcile hooks.
        sweeper: the cancel-only orphan sweeper.
        alerts: the alert sink.
        journal: the journal for the loop's own rows (best effort, never blocks an action).
        limits: the execution limits; `require_live_ready` must pass and the tick interval must
            be strictly below `max_unprotected_ms` (D-25).
        unknown_entries: optional `UnknownEntryResolver`, stepped once per tick (D-11).
        feeds: optional `FeedSource`; when set, every tick judges the mark price of each tracked
            symbol and the user-data feed (plan 20-16, D-25). None means no feed is judged.

    Raises:
        ValueError: `safe_mode` is not durable.
        ExecutionLimitsNotConfigured: any limit is unset (names the keys, never a value).
        ExecutionLimitsInvalid: the tick interval is not below `max_unprotected_ms`.
    """

    def __init__(
        self,
        *,
        adapter: ReconcileAdapter,
        gate: GateRestrictionSource,
        safe_mode: SafeModeGate,
        intent_store: UnresolvedIntentSource,
        protection: ProtectionView,
        sweeper: OrphanSweeperLike,
        alerts: ReconcileAlertSink,
        journal: JournalSink,
        limits: ExecutionLimits,
        unknown_entries: UnknownEntryStepper | None = None,
        feeds: FeedSource | None = None,
    ) -> None:
        if not safe_mode.is_durable:
            raise ValueError(
                "the reconcile loop needs a durable SafeModeController (is_durable is False): "
                "a restart must never read SAFE_MODE as off"
            )
        limits.require_live_ready()
        check_reconcile_cadence(limits)
        tick_interval_ms = limits.reconcile_tick_interval_ms
        if tick_interval_ms is None:
            raise ExecutionLimitsNotConfigured(("reconcile.tick_interval_ms",))
        self._adapter = adapter
        self._gate = gate
        self._safe_mode = safe_mode
        self._intent_store = intent_store
        self._protection = protection
        self._sweeper = sweeper
        self._alerts = alerts
        self._journal = journal
        self._unknown_entries = unknown_entries
        self._feeds = feeds
        self._limits = limits
        self._tick_interval_ms = tick_interval_ms
        self._lock = asyncio.Lock()
        self._journal_failures = 0

    @property
    def tick_interval_ms(self) -> int:
        """The configured cadence in milliseconds (`reconcile.tick_interval_ms`)."""
        return self._tick_interval_ms

    @property
    def journal_failures(self) -> int:
        """How many of the loop's own journal rows could not be written (best effort)."""
        return self._journal_failures

    async def tick(self, *, now_utc: datetime) -> TickReport:
        """Run one reconcile tick; an overlapping call returns TICK_SKIPPED_OVERLAP at once.

        Raises:
            ValueError: `now_utc` is naive or not UTC (a caller bug).
        """
        _require_utc(now_utc)
        if self._lock.locked():
            return TickReport(outcome=TICK_SKIPPED_OVERLAP, now_utc=now_utc)
        async with self._lock:
            gate_status = self._gate_recovery_status()
            report = await self._run(now_utc, gate_status)
            return dataclasses.replace(report, gate_recovery_status=gate_status)

    # ------------------------------------------------------------------ #
    # Steps.
    # ------------------------------------------------------------------ #

    async def _run(self, now_utc: datetime, gate_status: str | None) -> TickReport:
        gate_report = self._check_gate(now_utc, gate_status)
        if gate_report is not None:
            return gate_report
        if not self._restore_complete():
            self._journal_row(RECONCILE_SKIPPED_RESTORE_PENDING, {}, now_utc)
            return TickReport(outcome=TICK_SKIPPED_RESTORE_PENDING, now_utc=now_utc)

        action_failures: list[str] = []
        pre = self._check_feeds(now_utc, action_failures)
        report = await self._read_and_act(now_utc, gate_status, pre, action_failures)
        return _with_pre(report, pre)

    async def _read_and_act(
        self, now_utc: datetime, gate_status: str | None, pre: _Pre, action_failures: list[str]
    ) -> TickReport:
        unknown_report = await self._step_unknown_entries(now_utc, action_failures)

        truth: dict[str, tuple[Any, ...]] = {}
        readers = (
            ("open_normal_orders", self._adapter.snapshot_open_normal_orders),
            ("open_algo_orders", self._adapter.snapshot_open_algo_orders),
            ("positions", self._adapter.snapshot_positions),
        )
        for source, reader in readers:
            try:
                rows = await reader()
                if not isinstance(rows, (list, tuple)):
                    raise _UnusableRows
                truth[source] = tuple(rows)
            except Exception as exc:
                return self._read_failed(
                    now_utc, source, exc, SAFE_MODE_API_DEGRADATION, action_failures
                )

        try:
            plans = tuple(self._protection.protections())
            unresolved = tuple(self._intent_store.list_unresolved_intents())
            local = derive_local_intent(plans, unresolved)
        except Exception as exc:
            return self._read_failed(
                now_utc, "local_intent", exc, SAFE_MODE_DB_FAILURE, action_failures
            )

        try:
            diff = compare(
                **local.compare_kwargs(),
                truth_normal_orders=truth["open_normal_orders"],
                truth_algo_orders=truth["open_algo_orders"],
                truth_positions=truth["positions"],
            )
        except Exception as exc:
            return self._read_failed(
                now_utc, "compare", exc, SAFE_MODE_API_DEGRADATION, action_failures
            )

        return await self._act(
            now_utc, diff, plans, unknown_report, action_failures, gate_status, pre
        )

    def _gate_recovery_status(self) -> str | None:
        """The gate's restart-recovery verdict (plan 20-07), when the gate exposes one.

        LEGACY_IN_MEMORY means no persistence is wired (plan 20-25 must not accept it); None means
        the gate offers no verdict (or it could not be read), and the field is left out.
        """
        reader = getattr(self._gate, "recovery_status", None)
        if not callable(reader):
            return None
        try:
            status = reader()
        except Exception:
            return None
        value = getattr(status, "value", status)
        return value if isinstance(value, str) and value != "" else None

    def _check_gate(self, now_utc: datetime, gate_status: str | None) -> TickReport | None:
        try:
            restriction = self._gate.restriction()
        except Exception as exc:
            return self._read_failed(now_utc, "gate", exc, SAFE_MODE_API_DEGRADATION, [])
        if restriction is None:
            return None
        reason = getattr(restriction, "reason", None)
        reason_text = reason if isinstance(reason, str) and reason != "" else _UNKNOWN_REASON
        payload: dict[str, Any] = {"reason": reason_text}
        if gate_status is not None:
            payload["gate_recovery_status"] = gate_status
        remaining = getattr(restriction, "remaining_seconds", None)
        if isinstance(remaining, int) and not isinstance(remaining, bool):
            payload["remaining_seconds"] = remaining
        self._journal_row(RECONCILE_SKIPPED_GATE, payload, now_utc)
        return TickReport(outcome=TICK_SKIPPED_GATE, now_utc=now_utc, gate_reason=reason_text)

    def _restore_complete(self) -> bool:
        try:
            return bool(self._protection.restore_complete)
        except Exception:
            return False

    async def _step_unknown_entries(self, now_utc: datetime, failures: list[str]) -> Any:
        if self._unknown_entries is None:
            return None
        try:
            return await self._unknown_entries.step(now_utc=now_utc)
        except Exception as exc:
            failures.append("unknown_entry_step")
            self._journal_row(
                RECONCILE_ACTION_FAILED,
                {"action": "unknown_entry_step", "error_type": type(exc).__name__},
                now_utc,
            )
            self._enter_safe_mode(SAFE_MODE_API_DEGRADATION, now_utc, failures)
            return None

    def _read_failed(
        self,
        now_utc: datetime,
        source: str,
        exc: BaseException,
        reason: str,
        failures: list[str],
    ) -> TickReport:
        """Fail closed: journal source and exception class, enter SAFE_MODE, compare nothing."""
        self._journal_row(
            RECONCILE_READ_FAILED, {"source": source, "error_type": type(exc).__name__}, now_utc
        )
        self._enter_safe_mode(reason, now_utc, failures)
        return TickReport(
            outcome=TICK_READ_FAILED,
            now_utc=now_utc,
            safe_mode_reasons=(reason,),
            failed_source=source,
            action_failures=tuple(failures),
        )

    async def _act(
        self,
        now_utc: datetime,
        diff: CompareDiff,
        plans: tuple[Any, ...],
        unknown_report: Any,
        failures: list[str],
        gate_status: str | None,
        pre: _Pre,
    ) -> TickReport:
        # One entry per distinct reason, least urgent first: the controller keeps the LAST reason,
        # so the persisted reason is the most urgent one (stop-related exposure), and every
        # reason is still in the journal.
        ranked: dict[str, int] = {}
        for divergence in diff.divergences:
            policy = classify(divergence.kind)
            ranked.setdefault(policy.safe_mode_reason, _ACTION_URGENCY[policy.action])
        reasons = sorted(ranked, key=lambda reason: ranked[reason])
        for reason in reasons:
            self._enter_safe_mode(reason, now_utc, failures)

        delegated: list[tuple[str, str]] = []
        undelegated: list[tuple[str, str]] = []
        alerts_sent = 0
        alerts_failed = 0
        for divergence in diff.divergences:
            policy = classify(divergence.kind)
            owner: str | None = None
            if policy.action is DivergenceAction.DELEGATE_TO_COORDINATOR:
                owner = _owner_of(divergence, plans)
                if owner is not None and self._notify(owner, divergence.kind, now_utc, failures):
                    delegated.append((owner, divergence.kind))
                else:
                    undelegated.append((divergence.symbol, divergence.kind))
            if self._send_alert(policy.alert_event, divergence, owner, now_utc):
                alerts_sent += 1
            else:
                alerts_failed += 1

        swept: tuple[tuple[str, str], ...] = ()
        sweep_skipped: tuple[tuple[str, str], ...] = ()
        if diff.orphan_protectives:
            swept, sweep_skipped = await self._sweep(diff, now_utc, failures)

        counts: dict[str, int] = {}
        for divergence in pre.divergences + diff.divergences:
            counts[divergence.kind] = counts.get(divergence.kind, 0) + 1
        tick_payload: dict[str, Any] = {
            "outcome": TICK_COMPARED,
            "divergence_count": len(pre.divergences) + len(diff.divergences),
            "counts": counts,
            "safe_mode_reasons": list(_merge_reasons(pre.safe_mode_reasons, reasons)),
            "delegated": len(delegated),
            "undelegated": len(undelegated),
            "alerts_sent": alerts_sent + pre.alerts_sent,
            "alerts_failed": alerts_failed + pre.alerts_failed,
            "swept": len(swept),
            "sweep_skipped": len(sweep_skipped),
            "action_failures": list(failures),
        }
        if pre.stale_symbols:
            tick_payload["stale_feed_symbols"] = list(pre.stale_symbols)
        if pre.user_data_silent:
            tick_payload["user_data_silent"] = True
        if gate_status is not None:
            tick_payload["gate_recovery_status"] = gate_status
        self._journal_row(RECONCILE_TICK, tick_payload, now_utc)
        return TickReport(
            outcome=TICK_COMPARED,
            now_utc=now_utc,
            agreement=diff.agreement,
            divergences=diff.divergences,
            safe_mode_reasons=tuple(reasons),
            delegated=tuple(delegated),
            undelegated=tuple(undelegated),
            alerts_sent=alerts_sent,
            alerts_failed=alerts_failed,
            swept=swept,
            sweep_skipped=sweep_skipped,
            action_failures=tuple(failures),
            unknown_entries=unknown_report,
        )

    def _tracked_symbols(self) -> tuple[str, ...]:
        """The symbols of the coordinator plans that are not FLAT / ENTRY_ENDED_NO_FILL.

        A failed read gives no symbols: the local read of the same tick then fails too and enters
        SAFE_MODE DB_FAILURE (fail closed); only the user-data feed is judged on its own.
        """
        try:
            plans = tuple(self._protection.protections())
        except Exception:
            return ()
        symbols = {
            symbol
            for plan in plans
            if _state_name(plan) not in INACTIVE_STATE_NAMES
            for symbol in (getattr(plan, "symbol", None),)
            if isinstance(symbol, str) and symbol != ""
        }
        return tuple(sorted(symbols))

    def _check_feeds(self, now_utc: datetime, failures: list[str]) -> _Pre:
        """Judge the feeds (D-25): SAFE_MODE STALE_FEED and a STALE_DATA alert per stale feed.

        Never an exit: a later fresh reading changes nothing in SAFE_MODE (D-15). A source that
        raises, or a reading `assess_feeds` refuses, counts as stale for every tracked symbol and
        for the user-data feed (fail closed); only the exception class name is journaled.
        """
        if self._feeds is None:
            return _NO_PRE
        tracked = self._tracked_symbols()
        try:
            verdict = assess_feeds(
                self._feeds.read_feed(), symbols=tracked, now_utc=now_utc, limits=self._limits
            )
        except Exception as exc:
            failures.append("feed_read")
            self._journal_row(
                RECONCILE_ACTION_FAILED,
                {"action": "feed_read", "error_type": type(exc).__name__},
                now_utc,
            )
            verdict = FeedVerdict(stale_symbols=tracked, user_data_silent=True)
        if not verdict.any_stale:
            return _NO_PRE
        self._enter_safe_mode(SAFE_MODE_STALE_FEED, now_utc, failures)
        sent = 0
        failed = 0
        alerts: list[tuple[str, str, str | None]] = [
            (symbol, ALERT_REASON_MARK_PRICE_STALE, symbol) for symbol in verdict.stale_symbols
        ]
        if verdict.user_data_silent:
            alerts.append((ALERT_SUBJECT_USER_DATA, ALERT_REASON_USER_DATA_SILENT, None))
        for subject, reason, symbol in alerts:
            delivered = self._alert(
                event=ALERT_STALE_DATA,
                subject=subject,
                reason=reason,
                symbol=symbol,
                plan_hash=None,
                now_utc=now_utc,
            )
            sent, failed = (sent + 1, failed) if delivered else (sent, failed + 1)
        return _Pre(
            safe_mode_reasons=(SAFE_MODE_STALE_FEED,),
            alerts_sent=sent,
            alerts_failed=failed,
            stale_symbols=verdict.stale_symbols,
            user_data_silent=verdict.user_data_silent,
        )

    def _enter_safe_mode(self, reason: str, now_utc: datetime, failures: list[str]) -> None:
        try:
            self._safe_mode.enter_safe_mode(reason=reason, now_utc=now_utc)
        except Exception as exc:
            # The controller flips its flag first: entries stay blocked even when saving failed.
            failures.append("safe_mode_enter")
            self._journal_row(
                RECONCILE_ACTION_FAILED,
                {"action": "safe_mode_enter", "reason": reason, "error_type": type(exc).__name__},
                now_utc,
            )

    def _notify(self, plan_hash: str, kind: str, now_utc: datetime, failures: list[str]) -> bool:
        try:
            return bool(self._protection.notify_divergence(plan_hash, kind))
        except Exception as exc:
            failures.append("notify_divergence")
            self._journal_row(
                RECONCILE_ACTION_FAILED,
                {"action": "notify_divergence", "kind": kind, "error_type": type(exc).__name__},
                now_utc,
            )
            return False

    def _send_alert(
        self, event: str, divergence: Divergence, plan_hash: str | None, now_utc: datetime
    ) -> bool:
        return self._alert(
            event=event,
            subject=divergence.symbol,
            reason=divergence.kind,
            symbol=divergence.symbol,
            plan_hash=plan_hash,
            now_utc=now_utc,
        )

    def _alert(
        self,
        *,
        event: str,
        subject: str,
        reason: str,
        symbol: str | None,
        plan_hash: str | None,
        now_utc: datetime,
    ) -> bool:
        """One alert; a raising sink is journaled by exception class name, never re-raised."""
        try:
            self._alerts.alert(
                event=event,
                subject=subject,
                reason=reason,
                now_utc=now_utc,
                plan_hash=plan_hash,
                symbol=symbol,
            )
        except Exception as exc:
            self._journal_row(
                ALERT_SINK_FAILED,
                {
                    "event": event,
                    "kind": reason,
                    "symbol": symbol,
                    "error_type": type(exc).__name__,
                },
                now_utc,
            )
            return False
        return True

    async def _sweep(
        self, diff: CompareDiff, now_utc: datetime, failures: list[str]
    ) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]:
        try:
            outcome = await self._sweeper.sweep(
                diff, position_verifier=self._position_amount, now_utc=now_utc
            )
        except Exception as exc:
            failures.append("sweep")
            self._journal_row(
                RECONCILE_ACTION_FAILED,
                {"action": "sweep", "error_type": type(exc).__name__},
                now_utc,
            )
            return (), ()
        cancelled = tuple((str(s), str(c)) for s, c in getattr(outcome, "cancelled", ()))
        skipped = tuple(
            (str(getattr(s, "symbol", "")), str(getattr(s, "client_algo_id", "")))
            for s in getattr(outcome, "skipped", ())
        )
        return cancelled, skipped

    async def _position_amount(self, *, symbol: str) -> Decimal:
        """One fresh position read for the sweeper's two-zero-reads rule: the sum of abs amounts.

        A row that is not a Decimal raises, so an unreadable position never reads as zero.
        """
        rows = await self._adapter.snapshot_positions(symbol=symbol)
        total = Decimal(0)
        for row in rows:
            amount = getattr(row, "position_amt", None)
            if not isinstance(amount, Decimal):
                raise TypeError("position_amt must be a Decimal")
            total += abs(amount)
        return total

    def _journal_row(self, event_type: str, payload: dict[str, Any], now_utc: datetime) -> None:
        """Best effort: the journal is an audit trail here, never a precondition of an action."""
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        try:
            self._journal.record(
                JournalEvent(
                    journal_event_id=content_hash_event_id(
                        prefix="reconcile",
                        event_type=event_type,
                        entity_id=_ENTITY_ID,
                        occurred_at_utc=now_utc,
                        payload_json=payload_json,
                    ),
                    occurred_at_utc=now_utc,
                    event_type=event_type,
                    entity_type=_ENTITY_TYPE,
                    entity_id=_ENTITY_ID,
                    correlation_id=_CORRELATION_ID,
                    payload_json=payload_json,
                )
            )
        except Exception:
            self._journal_failures += 1


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Pre:
    """What the steps before the truth reads did in one tick (feeds, plan 20-16).

    They run before the reads so that a failed read cannot hide them; `_with_pre` folds them into
    the final report whatever the outcome.
    """

    divergences: tuple[Divergence, ...] = ()
    safe_mode_reasons: tuple[str, ...] = ()
    alerts_sent: int = 0
    alerts_failed: int = 0
    stale_symbols: tuple[str, ...] = ()
    user_data_silent: bool = False


_NO_PRE = _Pre()


def _merge_reasons(first: Sequence[str], second: Sequence[str]) -> tuple[str, ...]:
    """The reasons of both steps in entry order, each once."""
    return tuple(dict.fromkeys((*first, *second)))


def _with_pre(report: TickReport, pre: _Pre) -> TickReport:
    return dataclasses.replace(
        report,
        divergences=pre.divergences + report.divergences,
        safe_mode_reasons=_merge_reasons(pre.safe_mode_reasons, report.safe_mode_reasons),
        alerts_sent=report.alerts_sent + pre.alerts_sent,
        alerts_failed=report.alerts_failed + pre.alerts_failed,
        stale_symbols=pre.stale_symbols,
        user_data_silent=pre.user_data_silent,
    )


def _require_utc(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now_utc must be a timezone-aware UTC datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError("now_utc must be UTC, not an offset time")


def _state_name(plan: Any) -> str:
    state = getattr(plan, "state", None)
    raw = getattr(state, "value", state)
    return raw if isinstance(raw, str) else ""


def _owner_of(divergence: Divergence, plans: Sequence[Any]) -> str | None:
    """The one tracked plan a stop-related divergence belongs to, else None (never guess).

    An order id on the divergence ties it to a plan by the 29-character plan-hash prefix. Without
    an id (exposure rows) the symbol must match exactly one plan that is not FLAT or
    ENTRY_ENDED_NO_FILL.
    """
    order_id = divergence.client_algo_id or divergence.client_order_id
    if order_id is not None:
        prefix = plan_hash_prefix_of(order_id)
        if prefix is None:
            return None
        matches = [p for p in plans if str(getattr(p, "plan_hash", ""))[:29] == prefix]
    else:
        matches = [
            p
            for p in plans
            if getattr(p, "symbol", None) == divergence.symbol
            and _state_name(p) not in INACTIVE_STATE_NAMES
        ]
    if len(matches) != 1:
        return None
    plan_hash = getattr(matches[0], "plan_hash", None)
    return plan_hash if isinstance(plan_hash, str) and plan_hash != "" else None


__all__ = [
    "ALERT_SINK_FAILED",
    "RECONCILE_ACTION_FAILED",
    "RECONCILE_READ_FAILED",
    "RECONCILE_SKIPPED_GATE",
    "RECONCILE_SKIPPED_RESTORE_PENDING",
    "RECONCILE_TICK",
    "SAFE_MODE_API_DEGRADATION",
    "SAFE_MODE_DB_FAILURE",
    "SAFE_MODE_STALE_FEED",
    "TICK_COMPARED",
    "TICK_READ_FAILED",
    "TICK_SKIPPED_GATE",
    "TICK_SKIPPED_OVERLAP",
    "TICK_SKIPPED_RESTORE_PENDING",
    "FeedSource",
    "GateRestrictionSource",
    "JournalSink",
    "OrphanSweeperLike",
    "ProtectionView",
    "ReconcileAdapter",
    "ReconcileAlertSink",
    "ReconcileLoop",
    "SafeModeGate",
    "TickReport",
    "UnknownEntryStepper",
    "UnresolvedIntentSource",
]
