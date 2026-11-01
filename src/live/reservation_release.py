"""Release of risk reservations that are over (plan 24-37, findings F4 and F5; D095).

Before this module nothing in `src` released a reservation: the reservation of an approved plan
whose placement was refused or whose plan simply expired stayed RESERVED, and so did the
reservation of a plan whose position had closed. A RESERVED row is counted against the caps and
the margin claims, so the next entry on the cluster was refused (`CLUSTER_CAP_REJECT`). Two
callers, both built on the pure mappings of `src.execution.live_risk_inputs`:

* `ReservationReleaser.sweep_once` is the body of the scheduler task `reservation_release_sweep`.
  For every REQUESTED, RESERVED, PLACED or OPEN row it reads the plan and decides:

  - NO entry intent row (the approval was never consumed): `release_reason_for_plan` (EXPIRED,
    INVALIDATED and SUPERSEDED plans at once, an approved plan whose expiry passed as
    PLAN_EXPIRED); a plan that is still open maps to None and is untouched.
  - An entry intent row exists (the entry may be live or filled): only the OUTCOME releases it.
    A REJECTED entry intent releases as ENTRY_REJECTED (`release_reason_for_entry_intent`); a
    plan whose journal holds a `PROTECTION_TRANSITION` into FLAT or ENTRY_ENDED_NO_FILL
    releases as POSITION_CLOSED or ENTRY_ENDED_NO_FILL (`release_reason_for_protection_state`),
    after the row was advanced RESERVED to PLACED (the store permits both reasons only from
    PLACED or OPEN; the PLACED instant is the sweep's, later than the acknowledgement, which only
    over-counts the margin claim for the moment between the two writes, 22-REVIEW WR-06). SENT,
    UNKNOWN and ACKED entries with a live protection state stay counted. The journal is the
    source (not the coordinator), so a plan that ended before a restart is released too.

* `ReservationReleaser.release_refused` is the `on_refused` hook of the execution service: when a
  CONFIRM is refused before the approval was consumed, `release_reason_for_placement_refusal`
  releases the row at once for a FINAL refusal (PLAN_STATUS_INVALID,
  PLAN_INVALIDATED_BEFORE_PLACEMENT, VALIDITY_TOO_SHORT). Every other refusal (SAFE_MODE, a
  limit, a price) is not final: its reservation stays counted until the sweep finds the plan
  expired. That is the documented, conservative rule of the mapping; this module does not widen it.

Safety rules, each tested:

* An executed plan stays APPROVED (D051 item i), so `release_reason_for_plan` alone would release
  the reservation of a live position at the plan expiry: a row whose entry intent exists never
  takes the plan path.
* The store enforces `RELEASE_SOURCE_STATUSES`: a row in another status raises `RowConflict`, which
  is counted as a skip, never forced.
* A read that fails leaves the row counted (fail closed). One failing row does not stop the others;
  the sweep raises after the pass so the scheduler marks the task unhealthy.
* The journal rows carry fixed codes and the plan id only.

No wall clock is read here: every instant is passed in.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import structlog

from src.domain.journal import JournalEvent, content_hash_event_id
from src.execution.live_risk_inputs import (
    release_reason_for_entry_intent,
    release_reason_for_placement_refusal,
    release_reason_for_plan,
    release_reason_for_protection_state,
)
from src.execution.protection import EVENT_PROTECTION_TRANSITION, ProtectionState
from src.live.startup import protection_correlation
from src.persistence.errors import RowConflict
from src.risk.reservations import ReleaseReason, ReservationStatus

log = structlog.get_logger(__name__)

EVENT_RESERVATION_RELEASED: Final = "LIVE_RESERVATION_RELEASED"
SOURCE_SWEEP: Final = "SWEEP"
SOURCE_SWEEP_EXECUTED: Final = "SWEEP_EXECUTED"
SOURCE_REFUSAL: Final = "REFUSAL"
_ENDED_STATES: Final = frozenset(
    {ProtectionState.FLAT.value, ProtectionState.ENTRY_ENDED_NO_FILL.value}
)
_NEEDS_PLACED: Final = frozenset({ReleaseReason.POSITION_CLOSED, ReleaseReason.ENTRY_ENDED_NO_FILL})
_ENTITY_TYPE: Final = "RiskReservation"
_CORRELATION: Final = "live_reservation_release"

Record = Callable[[JournalEvent], Awaitable[None]]


class ReservationSweepIncomplete(RuntimeError):  # noqa: N818 - a task failure, not a family
    """At least one row could not be read or released in this pass (the others were handled)."""


@dataclass(frozen=True)
class SweepReport:
    """What one sweep did: counts only."""

    examined: int
    released: int
    consumed_skipped: int
    conflicts: int
    failures: int
    released_executed: int = 0


class ReservationReleaser:
    """The two release paths over the reservation, plan and intent stores (see the module doc)."""

    def __init__(
        self,
        *,
        reservations: Any,
        entities: Any,
        intents: Any,
        events_for_correlation: Callable[[str], Any],
        executor: Any,
        record: Record,
    ) -> None:
        self._reservations = reservations
        self._entities = entities
        self._intents = intents
        self._events_for = events_for_correlation
        self._executor = executor
        self._record = record

    # ---- the sweep ------------------------------------------------------------------------ #

    async def sweep_once(self, now_utc: datetime) -> SweepReport:
        """Release every reservation that is over; raise if any row failed (see the module doc)."""
        rows = await self._executor.read(self._reservations.list_unreleased)
        released = executed = consumed = conflicts = failures = 0
        for row in rows:
            try:
                plan = await self._executor.read(self._entities.get_trade_plan, row.trade_plan_id)
                if plan is None:
                    failures += 1  # a reservation without its plan: leave it counted, say so
                    continue
                entry = await self._entry_of(row.approval_id)
                if entry is None:
                    reason = release_reason_for_plan(
                        status=plan.status, expiry_utc=plan.expiry_utc, now_utc=now_utc
                    )
                    source = SOURCE_SWEEP
                else:
                    consumed += 1
                    reason = await self._executed_reason(plan.plan_hash, entry)
                    source = SOURCE_SWEEP_EXECUTED
                if reason is None:
                    continue
                if reason in _NEEDS_PLACED and row.status is ReservationStatus.RESERVED:
                    await self._executor.write(
                        self._reservations.mark_placed, row.trade_plan_id, now_utc=now_utc
                    )
                if await self._release(row.trade_plan_id, reason, now_utc, source):
                    released += 1
                    executed += source == SOURCE_SWEEP_EXECUTED
                else:
                    conflicts += 1
            except RowConflict:
                conflicts += 1
            except Exception as exc:  # noqa: BLE001 - class name only; the other rows go on
                failures += 1
                log.warning("live.reservation_sweep.row_failed", error_class=type(exc).__name__)
        report = SweepReport(
            examined=len(rows),
            released=released,
            consumed_skipped=consumed - executed,
            conflicts=conflicts,
            failures=failures,
            released_executed=executed,
        )
        if failures:
            raise ReservationSweepIncomplete(f"{failures} reservation(s) could not be handled")
        return report

    async def _executed_reason(self, plan_hash: str, entry: Any) -> ReleaseReason | None:
        """The outcome that releases a consumed plan's reservation, or None while it is live."""
        reason = release_reason_for_entry_intent(entry.intent_status)
        if reason is not None:
            return reason
        events = await self._executor.read(self._events_for, protection_correlation(plan_hash))
        for event in events:
            if event.event_type != EVENT_PROTECTION_TRANSITION:
                continue
            try:
                target = json.loads(event.payload_json).get("to")
            except (ValueError, AttributeError):
                continue
            if target in _ENDED_STATES:
                return release_reason_for_protection_state(ProtectionState(target))
        return None

    # ---- the refusal hook ----------------------------------------------------------------- #

    async def release_refused(
        self, approval_id: str, trade_plan_id: str, reason_code: str, now_utc: datetime
    ) -> bool:
        """Release the reservation of a plan whose CONFIRM was refused FINALLY; True when released.

        A non-final refusal (None from `release_reason_for_placement_refusal`) and a plan that was
        consumed release nothing.
        """
        reason = release_reason_for_placement_refusal(reason_code)
        if reason is None:
            return False
        if await self._entry_of(approval_id) is not None:
            return False
        return await self._release(trade_plan_id, reason, now_utc, SOURCE_REFUSAL)

    # ---- shared --------------------------------------------------------------------------- #

    async def _entry_of(self, approval_id: str | None) -> Any:
        """The ENTRY intent row of the approval, or None (a REQUESTED row has no approval yet)."""
        if approval_id is None:
            return None
        return await self._executor.read(self._intents.get_entry, approval_id=approval_id)

    async def _release(
        self, trade_plan_id: str, reason: ReleaseReason, now_utc: datetime, source: str
    ) -> bool:
        try:
            await self._executor.write(
                self._reservations.release, trade_plan_id, reason=reason, now_utc=now_utc
            )
        except RowConflict:
            return False
        await self._journal(trade_plan_id, reason, source, now_utc)
        return True

    async def _journal(
        self, trade_plan_id: str, reason: ReleaseReason, source: str, now_utc: datetime
    ) -> None:
        payload = json.dumps(
            {"reason": reason.value, "source": source},
            sort_keys=True,
            separators=(",", ":"),
        )
        event = JournalEvent(
            journal_event_id=content_hash_event_id(
                prefix="live_reservation",
                event_type=EVENT_RESERVATION_RELEASED,
                entity_id=trade_plan_id,
                occurred_at_utc=now_utc,
                payload_json=payload,
            ),
            occurred_at_utc=now_utc,
            event_type=EVENT_RESERVATION_RELEASED,
            entity_type=_ENTITY_TYPE,
            entity_id=trade_plan_id,
            correlation_id=_CORRELATION,
            trade_plan_id=trade_plan_id,
            payload_json=payload,
        )
        try:
            await self._record(event)
        except Exception as exc:  # noqa: BLE001 - the release is durable; an audit row may fail
            log.warning("live.reservation_release.journal_failed", error_class=type(exc).__name__)


__all__ = [
    "EVENT_RESERVATION_RELEASED",
    "SOURCE_REFUSAL",
    "SOURCE_SWEEP",
    "SOURCE_SWEEP_EXECUTED",
    "ReservationReleaser",
    "ReservationSweepIncomplete",
    "SweepReport",
]
