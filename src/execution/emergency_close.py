"""Automatic reduce-only MARKET emergency close (Phase 19, plan 19-12; D034, D-15, D-16, D-17).

The last line of defense when a protective stop is missing: the protection coordinator
(plan 19-14) calls ``close_position`` from its failure branches. The closer

* re-reads the position over REST (the exchange is canonical, never a running total),
* builds ONE valid MARKET part from the live exchangeInfo lot filters (``next_close_part``),
* sends it reduce-only under a deterministic client order id per attempt
  (``derive_close_order_id``),
* re-reads the position after the part and answers True only when REST shows it flat.

Anything it cannot prove ends in SAFE_MODE (``EMERGENCY_CLOSE_FAILED``), a critical alert and a
journal row, and returns False; a failed emergency close never declares the position safe
(D-16, D-15).

Decisions and open items:

* D034 approves the reduce-only close principle; D-15 and D-16 set the parameters; D-17: the
  automatic close is a separate path and ``emergency_manual_close`` (the operator path in
  ``src/execution/manager.py``) is unchanged.
* D-14: Hedge Mode is not supported in V1; a Hedge entry is refused with ``ValueError``.
* Q3 (owner-open): a failed live exchangeInfo read during the close is treated as "no valid
  part can be built", the D-16 SAFE_MODE branch. The plan-time snapshot is NOT used as a
  fallback until the owner decides.
* Q4 / Phase 18 src/WR-12 (owner-open): a 418/429 pause refuses the close too (the adapter
  raises ``PreSendRefusal`` with nothing sent). No exemption is added; the deadline keeps running
  in the coordinator and no claim of safety is made.
* A4 / A8 (assumptions): a reduce-only MARKET on a flat or smaller position answers -2022 or
  -2024, from the repo taxonomy and not verified on the live page. The closer treats both the
  same: it re-reads the position and never branches on the difference, never resends blindly.

Purity: stdlib, Decimal, ``src.domain`` and ``src.execution``. No SDK, no ``src.adapters``, no
float, no sleep, and no clock other than the injected one. An exception's message text is never
read (D-21): only its type name and the facts the adapter extracts.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from src.domain.exchange_errors import (
    CallKind,
    ExchangeErrorCategory,
    PreSendRefusal,
    classify,
)
from src.domain.journal import JournalEvent, content_hash_event_id
from src.domain.lot_filters import LotFilters
from src.execution.lot_split import next_close_part, plan_close_parts
from src.execution.order_ids import derive_close_order_id
from src.execution.protection import (
    POSITION_MODE_HEDGE,
    SAFE_MODE_DB_FAILURE,
    CriticalAlertSink,
    EmergencyCloser,
    RestingEntry,
)

EVENT_EMERGENCY_CLOSE = "EMERGENCY_CLOSE"
SAFE_MODE_EMERGENCY_CLOSE_FAILED = "EMERGENCY_CLOSE_FAILED"
ALERT_EMERGENCY_CLOSE_FAILED = "EMERGENCY_CLOSE_FAILED"
ALERT_EMERGENCY_CLOSE_NOT_SENT = "EMERGENCY_CLOSE_NOT_SENT"

PHASE_PRE_SEND = "pre_send"
PHASE_POST_SEND = "post_send"
PHASE_ALREADY_FLAT = "already_flat"
PHASE_FAILED = "failed"
PHASE_NOT_SENT = "not_sent"
PHASE_REJECTED = "rejected"
PHASE_AMBIGUOUS = "ambiguous"
PHASE_ABSENT = "absent"
PHASE_ENDED_UNFILLED = "ended_unfilled"

_ZERO = Decimal("0")
_POSITION_SIDE_ONE_WAY = "BOTH"
_CORRELATION_PREFIX = "emergency_close_"
_EVENT_ID_PREFIX = "ecl"
_STATUS_FILLED = "FILLED"
_REASON_PRE_SEND_REFUSED = "PRE_SEND_REFUSED"
# Order statuses that end a MARKET close without closing anything by themselves; the position
# read decides what is left (no assumption about a partial execution).
_TERMINAL_NOT_FILLED: frozenset[str] = frozenset(
    {"CANCELED", "EXPIRED", "EXPIRED_IN_MATCH", "REJECTED"}
)
_DEFINITIVE_REJECTIONS: frozenset[ExchangeErrorCategory] = frozenset(
    {
        ExchangeErrorCategory.REJECTED_DEFINITIVE,
        ExchangeErrorCategory.PRECONDITION_NO_POSITION,
    }
)


class EmergencyCloseStatus(StrEnum):
    """How one ``close_position`` call ended."""

    FLAT = "FLAT"
    CLOSE_FAILED = "CLOSE_FAILED"
    NOT_SENT = "NOT_SENT"
    PENDING_UNKNOWN = "PENDING_UNKNOWN"


@dataclass(frozen=True)
class EmergencyCloseResult:
    """The outcome of the last ``close_position`` call (fixed project text only)."""

    status: EmergencyCloseStatus
    parts_sent: int
    reason: str


class _Kind(StrEnum):
    """What one part attempt turned out to be."""

    CLOSED = "CLOSED"  # accepted by the exchange (or found FILLED by id)
    NO_EFFECT = "NO_EFFECT"  # proven absent, or found ended without filling
    REJECTED = "REJECTED"  # definitive rejection (-2022, -2024, ...)
    NOT_SENT = "NOT_SENT"  # PreSendRefusal: nothing left the process
    UNKNOWN = "UNKNOWN"  # cannot tell whether the attempt exists or what it did


@dataclass(frozen=True)
class _Outcome:
    kind: _Kind
    code: str = ""
    error_type: str | None = None


class CloseAdapter(Protocol):
    """The adapter methods the closer calls (the real adapter and the fake have them)."""

    async def snapshot_positions(self, *, symbol: str | None = None) -> Any: ...

    async def symbol_lot_filters(self, *, symbol: str) -> Any: ...

    async def place_market_close(
        self,
        *,
        symbol: str,
        side: str,
        position_side: str,
        quantity: Decimal,
        new_client_order_id: str,
    ) -> Any: ...

    async def query_order_by_client(self, *, symbol: str, orig_client_order_id: str) -> Any: ...

    def error_facts(self, exc: BaseException) -> Any: ...


def _attr(obj: Any, name: str) -> Any:
    """Read ``name`` from a dataclass-style object or a dict-style payload."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


async def discover_next_attempt_no(*, adapter: CloseAdapter, symbol: str, plan_hash: str) -> int:
    """The first attempt number whose id the exchange does not know (definitively absent).

    Probes ``xc-...0001``, ``0002``, ... over REST (there is no attempt table, plan 19-06), so
    a close started again after a crash never reuses an attempt id. A probe that fails or
    answers something other than a plain found flag raises: the caller treats the history as
    unknown and sends nothing. Raises ``ValueError`` when all 9999 numbers are taken.
    """
    attempt_no = 1
    while True:
        client_order_id = derive_close_order_id(plan_hash=plan_hash, attempt_no=attempt_no)
        probe = await adapter.query_order_by_client(
            symbol=symbol, orig_client_order_id=client_order_id
        )
        found = _attr(probe, "found")
        if found is False:
            return attempt_no
        if found is not True:
            raise ValueError("the attempt probe did not answer found or absent")
        attempt_no += 1


class MarketEmergencyCloser(EmergencyCloser):
    """Closes a position by reduce-only MARKET parts; see the module docstring.

    Every argument is keyword-only and injected. ``close_position`` answers True only when REST
    shows the position flat; ``last_result`` describes how the last call ended.
    """

    def __init__(
        self,
        *,
        adapter: CloseAdapter,
        journal: Any,
        safe_mode_controller: Any,
        alert_sink: CriticalAlertSink,
        clock: Callable[[], datetime],
    ) -> None:
        self._adapter = adapter
        self._journal = journal
        self._safe_mode = safe_mode_controller
        self._alerts = alert_sink
        self._clock = clock
        self._last_result: EmergencyCloseResult | None = None
        self._journal_failed = False

    @property
    def last_result(self) -> EmergencyCloseResult | None:
        return self._last_result

    # ------------------------------------------------------------------ #
    # The close.
    # ------------------------------------------------------------------ #

    async def close_position(self, *, entry: RestingEntry, reason: str) -> bool:
        """True only when REST shows the position of ``entry.symbol`` flat."""
        if entry.position_mode == POSITION_MODE_HEDGE:
            raise ValueError("the automatic close does not support HEDGE position mode (D-14)")
        self._last_result = None
        symbol = entry.symbol

        try:
            position = await self._read_position(symbol)
        except Exception as exc:  # noqa: BLE001 - an unreadable position proves nothing
            return self._fail(entry, reason, "POSITION_READ_FAILED", 0, type(exc).__name__)
        if position == _ZERO:
            self._journal_note(entry, PHASE_ALREADY_FLAT, reason)
            self._last_result = EmergencyCloseResult(EmergencyCloseStatus.FLAT, 0, reason)
            return True

        try:
            filters = await self._adapter.symbol_lot_filters(symbol=symbol)
        except Exception as exc:  # noqa: BLE001 - Q3: no live filters means no valid part
            return self._fail(entry, reason, "LOT_FILTERS_UNAVAILABLE", 0, type(exc).__name__)
        if not isinstance(filters, LotFilters):
            return self._fail(entry, reason, "LOT_FILTERS_UNAVAILABLE", 0, "InvalidFilters")

        # An attempt number is never reused, also across restarts: continue after the last
        # attempt the exchange knows about (a probe failure means the history is unknown).
        try:
            attempt_no = await discover_next_attempt_no(
                adapter=self._adapter, symbol=symbol, plan_hash=entry.plan_hash
            )
        except Exception as exc:  # noqa: BLE001 - an unknown attempt history stops the close
            return self._fail(
                entry,
                reason,
                "ATTEMPT_DISCOVERY_FAILED",
                0,
                type(exc).__name__,
                status=EmergencyCloseStatus.PENDING_UNKNOWN,
            )

        # Never more sends than the parts planned from the first REST position (D-15): a part
        # that does not move the position must not turn into an endless loop. Attempts proven to
        # have had no effect are bounded by the same number.
        parts_planned = max(len(plan_close_parts(position=abs(position), filters=filters).parts), 1)
        parts_sent = 0
        no_effect_attempts = 0
        while parts_sent < parts_planned:
            # Each part is sized from the REST position, never from a running total.
            quantity = next_close_part(remaining=abs(position), filters=filters)
            if quantity is None:
                return self._fail(entry, reason, "NO_VALID_PART", parts_sent, None)
            side = "SELL" if position > _ZERO else "BUY"
            try:
                client_order_id = derive_close_order_id(
                    plan_hash=entry.plan_hash, attempt_no=attempt_no
                )
            except ValueError:
                return self._fail(entry, reason, "ATTEMPT_NUMBERS_EXHAUSTED", parts_sent, None)
            outcome = await self._send_part(
                entry, reason, attempt_no, client_order_id, side, quantity
            )
            attempt_no += 1  # whatever happened, this id is spent
            if outcome.kind is _Kind.NOT_SENT:
                return self._not_sent(entry, reason, parts_sent, outcome.error_type)
            if outcome.kind is _Kind.UNKNOWN:
                return self._fail(
                    entry,
                    reason,
                    outcome.code,
                    parts_sent,
                    outcome.error_type,
                    status=EmergencyCloseStatus.PENDING_UNKNOWN,
                )
            if outcome.kind is _Kind.CLOSED:
                parts_sent += 1
            elif outcome.kind is _Kind.NO_EFFECT:
                no_effect_attempts += 1
                if no_effect_attempts > parts_planned:
                    return self._fail(entry, reason, "SEND_NOT_CONFIRMED", parts_sent, None)
            try:
                position = await self._read_position(symbol)
            except Exception as exc:  # noqa: BLE001 - flat is proven by REST or not at all
                return self._fail(
                    entry, reason, "POSITION_READ_FAILED", parts_sent, type(exc).__name__
                )
            if position == _ZERO:
                self._last_result = EmergencyCloseResult(
                    EmergencyCloseStatus.FLAT, parts_sent, reason
                )
                return True
            if outcome.kind is _Kind.REJECTED:
                # The exchange refused the part and the position is still open: -2022 and
                # -2024 (and every other definitive rejection) end here the same way. The
                # close is never resent blindly.
                return self._fail(
                    entry, reason, "REJECTED_NOT_FLAT", parts_sent, outcome.error_type
                )
        return self._fail(entry, reason, "PARTS_EXHAUSTED", parts_sent, None)

    # ------------------------------------------------------------------ #
    # One part: journal-first send, ambiguity resolved by a query, never a blind resend.
    # ------------------------------------------------------------------ #

    async def _send_part(
        self,
        entry: RestingEntry,
        close_reason: str,
        attempt_no: int,
        client_order_id: str,
        side: str,
        quantity: Decimal,
    ) -> _Outcome:
        def journal(phase: str, error_type: str | None = None) -> None:
            self._journal_attempt(
                entry,
                phase,
                close_reason,
                attempt_no,
                client_order_id,
                side,
                quantity,
                error_type=error_type,
            )

        journal(PHASE_PRE_SEND)
        try:
            answer = await self._adapter.place_market_close(
                symbol=entry.symbol,
                side=side,
                position_side=_POSITION_SIDE_ONE_WAY,
                quantity=quantity,
                new_client_order_id=client_order_id,
            )
        except PreSendRefusal as exc:
            # Nothing reached the exchange (rate-limit gate, policy missing): no probe, no
            # resend. The coordinator's deadline keeps running (Q4 is owner-open).
            journal(PHASE_NOT_SENT, type(exc).__name__)
            return _Outcome(_Kind.NOT_SENT, error_type=type(exc).__name__)
        except Exception as exc:  # noqa: BLE001 - classified below; ambiguity is probed
            error_type = type(exc).__name__
            if self._is_definitive_rejection(exc):
                journal(PHASE_REJECTED, error_type)
                return _Outcome(_Kind.REJECTED, error_type=error_type)
            journal(PHASE_AMBIGUOUS, error_type)
            return await self._resolve_ambiguity(entry, client_order_id, journal)
        if answer is None:
            journal(PHASE_AMBIGUOUS)
            return await self._resolve_ambiguity(entry, client_order_id, journal)
        journal(PHASE_POST_SEND)
        return _Outcome(_Kind.CLOSED)

    def _is_definitive_rejection(self, exc: Exception) -> bool:
        """True when the exchange definitively refused the order (nothing was placed).

        Decided from the facts the adapter extracts (class and int code), never from message
        text (D-21). -2022 and -2024 are both REJECTED_DEFINITIVE and are not told apart.
        """
        try:
            category = classify(self._adapter.error_facts(exc), CallKind.PLACEMENT)
        except Exception:  # noqa: BLE001 - an unclassifiable failure is ambiguous
            return False
        return category in _DEFINITIVE_REJECTIONS

    async def _resolve_ambiguity(
        self,
        entry: RestingEntry,
        client_order_id: str,
        journal: Callable[[str], None],
    ) -> _Outcome:
        """Query the attempt id; an attempt is never sent twice (T-19-29)."""
        try:
            probe = await self._adapter.query_order_by_client(
                symbol=entry.symbol, orig_client_order_id=client_order_id
            )
        except Exception as exc:  # noqa: BLE001 - existence unknown: stop, no resend
            return _Outcome(_Kind.UNKNOWN, "PROBE_FAILED", type(exc).__name__)
        found = _attr(probe, "found")
        if found is False:
            journal(PHASE_ABSENT)
            return _Outcome(_Kind.NO_EFFECT)
        if found is not True:
            return _Outcome(_Kind.UNKNOWN, "PROBE_INDETERMINATE")
        status = _attr(probe, "status")
        if status == _STATUS_FILLED:
            journal(PHASE_POST_SEND)
            return _Outcome(_Kind.CLOSED)
        if status in _TERMINAL_NOT_FILLED:
            journal(PHASE_ENDED_UNFILLED)
            return _Outcome(_Kind.NO_EFFECT)
        return _Outcome(_Kind.UNKNOWN, "ATTEMPT_NOT_TERMINAL")

    # ------------------------------------------------------------------ #
    # REST reads.
    # ------------------------------------------------------------------ #

    async def _read_position(self, symbol: str) -> Decimal:
        """The signed One-way position of ``symbol`` from REST; raises when it cannot be read."""
        rows = await self._adapter.snapshot_positions(symbol=symbol)
        total = _ZERO
        for row in rows:
            if _attr(row, "symbol") != symbol:
                continue
            if _attr(row, "position_side") != _POSITION_SIDE_ONE_WAY:
                raise ValueError("a non-BOTH position row contradicts the ONE_WAY position mode")
            amount = _attr(row, "position_amt")
            if not isinstance(amount, Decimal) or not amount.is_finite():
                raise ValueError("position_amt is not a finite Decimal")
            total += amount
        return total

    # ------------------------------------------------------------------ #
    # Failure path: SAFE_MODE, critical alert, journal, False.
    # ------------------------------------------------------------------ #

    def _fail(
        self,
        entry: RestingEntry,
        close_reason: str,
        code: str,
        parts_sent: int,
        error_type: str | None,
        *,
        status: EmergencyCloseStatus = EmergencyCloseStatus.CLOSE_FAILED,
    ) -> bool:
        now = self._clock()
        self._journal_note(
            entry,
            PHASE_FAILED,
            close_reason,
            parts_sent=parts_sent,
            code=code,
            error_type=error_type,
        )
        try:
            self._safe_mode.enter_safe_mode(reason=SAFE_MODE_EMERGENCY_CLOSE_FAILED, now_utc=now)
        except Exception:  # noqa: BLE001, S110 - the alert below still goes out
            pass
        try:
            self._alerts.critical(
                event=ALERT_EMERGENCY_CLOSE_FAILED,
                plan_hash=entry.plan_hash,
                symbol=entry.symbol,
                reason=code,
                now_utc=now,
            )
        except Exception:  # noqa: BLE001, S110 - SAFE_MODE and the journal row already exist
            pass
        self._last_result = EmergencyCloseResult(status, parts_sent, code)
        return False

    def _not_sent(
        self, entry: RestingEntry, close_reason: str, parts_sent: int, error_type: str | None
    ) -> bool:
        """A pre-send refusal: critical alert, no claim of safety, no SAFE_MODE from here.

        The coordinator's unprotected deadline keeps running and decides (Q4 is owner-open).
        The refusal itself was journaled as ``not_sent`` before this call.
        """
        try:
            self._alerts.critical(
                event=ALERT_EMERGENCY_CLOSE_NOT_SENT,
                plan_hash=entry.plan_hash,
                symbol=entry.symbol,
                reason=_REASON_PRE_SEND_REFUSED,
                now_utc=self._clock(),
            )
        except Exception:  # noqa: BLE001, S110 - the journal row already exists
            pass
        self._last_result = EmergencyCloseResult(
            EmergencyCloseStatus.NOT_SENT, parts_sent, _REASON_PRE_SEND_REFUSED
        )
        return False

    # ------------------------------------------------------------------ #
    # Journal (scalar payload fields only; exception TYPE names, never messages).
    # ------------------------------------------------------------------ #

    def _journal_attempt(
        self,
        entry: RestingEntry,
        phase: str,
        close_reason: str,
        attempt_no: int,
        client_order_id: str,
        side: str,
        quantity: Decimal,
        *,
        error_type: str | None = None,
    ) -> None:
        payload: dict[str, str | int | None] = {
            "phase": phase,
            "plan_hash": entry.plan_hash,
            "symbol": entry.symbol,
            "reason": close_reason,
            "attempt_no": attempt_no,
            "client_order_id": client_order_id,
            "side": side,
            "quantity": str(quantity),
        }
        if error_type is not None:
            payload["error_type"] = error_type
        self._record(entry, client_order_id, payload)

    def _journal_note(
        self,
        entry: RestingEntry,
        phase: str,
        close_reason: str,
        *,
        parts_sent: int | None = None,
        code: str | None = None,
        error_type: str | None = None,
    ) -> None:
        payload: dict[str, str | int | None] = {
            "phase": phase,
            "plan_hash": entry.plan_hash,
            "symbol": entry.symbol,
            "reason": close_reason,
        }
        if parts_sent is not None:
            payload["parts_sent"] = parts_sent
        if code is not None:
            payload["code"] = code
        if error_type is not None:
            payload["error_type"] = error_type
        self._record(entry, entry.plan_hash, payload)

    def _record(
        self, entry: RestingEntry, entity_id: str, payload: dict[str, str | int | None]
    ) -> None:
        """Journal one event; a failing journal loses only the audit row (D034)."""
        now = self._clock()
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        event = JournalEvent(
            journal_event_id=content_hash_event_id(
                prefix=_EVENT_ID_PREFIX,
                event_type=EVENT_EMERGENCY_CLOSE,
                entity_id=entity_id,
                occurred_at_utc=now,
                payload_json=body,
            ),
            occurred_at_utc=now,
            event_type=EVENT_EMERGENCY_CLOSE,
            entity_type="Order" if entity_id != entry.plan_hash else "EmergencyClose",
            entity_id=entity_id,
            correlation_id=f"{_CORRELATION_PREFIX}{entry.plan_hash}",
            trade_plan_id=entry.trade_plan_id,
            approval_id=entry.approval_id,
            payload_json=body,
        )
        try:
            self._journal.record(event)
        except Exception:  # noqa: BLE001 - protection outranks the audit row
            self._journal_failure(now)

    def _journal_failure(self, now: datetime) -> None:
        if self._journal_failed:
            return
        self._journal_failed = True
        try:
            self._safe_mode.enter_safe_mode(reason=SAFE_MODE_DB_FAILURE, now_utc=now)
        except Exception:  # noqa: BLE001, S110 - the flag is set first
            pass


__all__ = [
    "ALERT_EMERGENCY_CLOSE_FAILED",
    "ALERT_EMERGENCY_CLOSE_NOT_SENT",
    "EVENT_EMERGENCY_CLOSE",
    "SAFE_MODE_EMERGENCY_CLOSE_FAILED",
    "CloseAdapter",
    "EmergencyCloseResult",
    "EmergencyCloseStatus",
    "MarketEmergencyCloser",
    "discover_next_attempt_no",
]
