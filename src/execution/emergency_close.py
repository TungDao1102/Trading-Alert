"""Automatic reduce-only MARKET emergency close (Phase 19, plan 19-12; D034, D-15, D-16, D-17).

The last line of defense when a protective stop is missing: the protection coordinator
(plan 19-14) calls ``close_position`` from its failure branches. The closer

* re-reads the position over REST (the exchange is canonical, never a running total),
* builds ONE valid MARKET part from the live exchangeInfo lot filters (``next_close_part``),
* sends it reduce-only under a deterministic client order id per attempt
  (``derive_close_order_id``),
* confirms that attempt by querying its id (``query_order_by_client``) until it is FILLED or
  another terminal status, and only then
* re-reads the position and answers True only when REST shows it flat on two consecutive reads
  (T-8-30, the rule of ``src/reconcile/sweeper.py``; 19-REVIEW CR-03). A zero read followed by a
  non-zero one fails closed (``TRANSIENT_POSITION_GAP``) and sends nothing more in that call.

Q5 applied to the close (19-REVIEW WR-03, owner decision 2026-10-20): a second close order is
never sent while the result of the previous one is not determined.

* An ACK of the MARKET close (typically NEW with nothing executed) is PENDING, never CLOSED. The
  attempt is remembered per plan (``_PendingAttempt``, in process) and every later call queries
  that same id first; nothing else is sent until it is terminal.
* ``found=False`` right after an ambiguous send (an error with an unknown outcome, or no answer)
  is UNKNOWN, not absence: no new attempt is created. ``found=False`` for an attempt that was
  acknowledged or once found is UNKNOWN too.
* ``discover_next_attempt_no`` hands out no new number while an earlier attempt is found and not
  terminal (``CloseAttemptNotTerminal``); the closer then adopts that attempt as pending and
  sends nothing.
* Only after the attempt is confirmed terminal is the position re-read; exposure that remains
  gets a next attempt under a NEW id, sized from that fresh REST position.
* An attempt still not terminal ``protection.emergency_close_poll_timeout_ms`` after it was sent
  (injected clock; an owner number of its own, never ``max_unprotected_ms``) is held UNKNOWN:
  SAFE_MODE, ONE critical alert per pending attempt (the episode), no overlapping close, and the
  next calls keep querying it. The owner accepts that the position may stay open longer, even
  without a stop.

So the duplicate bound no longer rests on assumption A4 (reduce-only rejected on a flat or
smaller position). The pending attempt is in-process state: after a restart only
``discover_next_attempt_no`` protects the history, and an ambiguous attempt the exchange does
not show is NOT remembered (rebuilding state after a restart is Phase 20/24).

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
  Since WR-03 no send relies on A4 to avoid a duplicate close.

Purity: stdlib, Decimal, ``src.domain`` and ``src.execution``. No SDK, no ``src.adapters``, no
float, no sleep, and no clock other than the injected one. An exception's message text is never
read (D-21): only its type name and the facts the adapter extracts.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
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
from src.execution.execution_limits import ExecutionLimits, ExecutionLimitsNotConfigured
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
PHASE_ENDED_UNFILLED = "ended_unfilled"
# A query of the attempt id proved it FILLED (19-REVIEW WR-03: an ACK alone is not a fill).
PHASE_FILLED = "filled"

# The failure code of a zero position read that a second, fresh read did not confirm (T-8-30
# two consecutive zero reads, the rule of src/reconcile/sweeper.py; 19-REVIEW CR-03).
CODE_TRANSIENT_POSITION_GAP = "TRANSIENT_POSITION_GAP"
# 19-REVIEW WR-03: why a sent attempt is still pending, or why it is held UNKNOWN.
CODE_ATTEMPT_NOT_TERMINAL = "ATTEMPT_NOT_TERMINAL"
CODE_ABSENT_AFTER_AMBIGUOUS_SEND = "ABSENT_AFTER_AMBIGUOUS_SEND"
CODE_NOT_FOUND_AFTER_ACK = "ATTEMPT_NOT_FOUND_AFTER_ACK"
CODE_PROBE_FAILED = "PROBE_FAILED"
CODE_PROBE_INDETERMINATE = "PROBE_INDETERMINATE"
CODE_STATUS_UNREADABLE = "ATTEMPT_STATUS_UNREADABLE"
CODE_HISTORY_NOT_TERMINAL = "ATTEMPT_HISTORY_NOT_TERMINAL"
CODE_POLL_DEADLINE_PASSED = "CLOSE_POLL_DEADLINE_PASSED"

_ZERO = Decimal("0")
_ONE_MS = timedelta(milliseconds=1)
_POSITION_SIDE_ONE_WAY = "BOTH"
_CORRELATION_PREFIX = "emergency_close_"
_EVENT_ID_PREFIX = "ecl"
_STATUS_FILLED = "FILLED"
_REASON_PRE_SEND_REFUSED = "PRE_SEND_REFUSED"
_POLL_TIMEOUT_KEY = "protection.emergency_close_poll_timeout_ms"
# Order statuses that end a MARKET close without closing anything by themselves; the position
# read decides what is left (no assumption about a partial execution).
_TERMINAL_NOT_FILLED: frozenset[str] = frozenset(
    {"CANCELED", "EXPIRED", "EXPIRED_IN_MATCH", "REJECTED"}
)
_TERMINAL_STATUSES: frozenset[str] = _TERMINAL_NOT_FILLED | {_STATUS_FILLED}
# The order statuses that are known and not terminal: the attempt may still execute.
_ACTIVE_STATUSES: frozenset[str] = frozenset({"NEW", "PARTIALLY_FILLED"})
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
    # A sent attempt is not terminal yet and is polled by its id; nothing else is sent (WR-03).
    PENDING = "PENDING"
    PENDING_UNKNOWN = "PENDING_UNKNOWN"


@dataclass(frozen=True)
class EmergencyCloseResult:
    """The outcome of the last ``close_position`` call (fixed project text only)."""

    status: EmergencyCloseStatus
    parts_sent: int
    reason: str


class _Kind(StrEnum):
    """What one part attempt turned out to be."""

    CLOSED = "CLOSED"  # a query of its id found it FILLED (an ACK alone is never CLOSED)
    NO_EFFECT = "NO_EFFECT"  # a query of its id found it ended without filling
    REJECTED = "REJECTED"  # definitive rejection (-2022, -2024, ...): nothing was placed
    NOT_SENT = "NOT_SENT"  # PreSendRefusal: nothing left the process
    PENDING = "PENDING"  # may exist and is not proven terminal: poll it, send nothing else


@dataclass(frozen=True)
class _Outcome:
    kind: _Kind
    error_type: str | None = None


@dataclass
class _PendingAttempt:
    """A close attempt whose end is not proven yet (in-process, one per plan; WR-03).

    ``seen`` is True once an answer proved that the attempt exists (an ACK or a query that found
    it). ``unknown_code`` is set once its state became unknown and stays set until a query proves
    it terminal. ``alerted`` is True once the episode's one critical alert went out.
    """

    attempt_no: int
    client_order_id: str
    side: str | None
    quantity: Decimal | None
    sent_at: datetime
    seen: bool
    unknown_code: str | None = None
    error_type: str | None = None
    alerted: bool = False

    def mark_unknown(self, code: str, error_type: str | None = None) -> None:
        if self.unknown_code is None:
            self.unknown_code = code
            self.error_type = error_type


class CloseAttemptNotTerminal(ValueError):
    """An earlier close attempt is found and not terminal: no new attempt number (WR-03)."""

    def __init__(self, *, attempt_no: int, client_order_id: str) -> None:
        self.attempt_no = attempt_no
        self.client_order_id = client_order_id
        super().__init__(f"close attempt {attempt_no} is not terminal")


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
    unknown and sends nothing. A found attempt that is not terminal (FILLED, CANCELED, EXPIRED,
    EXPIRED_IN_MATCH, REJECTED) may still execute, so no new number is handed out: it raises
    ``CloseAttemptNotTerminal`` naming that attempt (19-REVIEW WR-03). Raises ``ValueError`` when
    all 9999 numbers are taken.
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
        if _attr(probe, "status") not in _TERMINAL_STATUSES:
            raise CloseAttemptNotTerminal(attempt_no=attempt_no, client_order_id=client_order_id)
        attempt_no += 1


class MarketEmergencyCloser(EmergencyCloser):
    """Closes a position by reduce-only MARKET parts; see the module docstring.

    Every argument is keyword-only and injected. ``close_position`` answers True only when REST
    shows the position flat; ``last_result`` describes how the last call ended. The constructor
    refuses while any execution limit is NOT_CONFIGURED (``limits.require_live_ready()``, as the
    coordinator does); the poll deadline is ``protection.emergency_close_poll_timeout_ms``.
    """

    def __init__(
        self,
        *,
        adapter: CloseAdapter,
        journal: Any,
        safe_mode_controller: Any,
        alert_sink: CriticalAlertSink,
        clock: Callable[[], datetime],
        limits: ExecutionLimits,
    ) -> None:
        limits.require_live_ready()
        poll_timeout_ms = limits.emergency_close_poll_timeout_ms
        if poll_timeout_ms is None:
            raise ExecutionLimitsNotConfigured((_POLL_TIMEOUT_KEY,))
        self._poll_timeout_ms = poll_timeout_ms
        self._adapter = adapter
        self._journal = journal
        self._safe_mode = safe_mode_controller
        self._alerts = alert_sink
        self._clock = clock
        self._last_result: EmergencyCloseResult | None = None
        self._journal_failed = False
        # 19-REVIEW WR-03: the attempt of each plan whose end is not proven yet.
        self._pending: dict[str, _PendingAttempt] = {}

    @property
    def last_result(self) -> EmergencyCloseResult | None:
        return self._last_result

    # ------------------------------------------------------------------ #
    # The close.
    # ------------------------------------------------------------------ #

    async def close_position(self, *, entry: RestingEntry, reason: str) -> bool:
        """True only when REST shows the position of ``entry.symbol`` flat.

        A pending attempt of this plan is queried first; while it is not terminal nothing is
        sent and the call answers False (``PENDING``, or ``PENDING_UNKNOWN`` once its state is
        unknown or the poll deadline has passed).
        """
        if entry.position_mode == POSITION_MODE_HEDGE:
            raise ValueError("the automatic close does not support HEDGE position mode (D-14)")
        self._last_result = None
        symbol = entry.symbol
        parts_sent = 0

        pending = self._pending.get(entry.plan_hash)
        if pending is not None:
            kind = await self._poll(entry, reason, pending)
            if kind is _Kind.PENDING:
                return self._hold(entry, reason, pending, parts_sent)
            del self._pending[entry.plan_hash]
            if kind is _Kind.CLOSED:
                parts_sent += 1

        try:
            position = await self._read_position(symbol)
        except Exception as exc:  # noqa: BLE001 - an unreadable position proves nothing
            return self._fail(entry, reason, "POSITION_READ_FAILED", parts_sent, type(exc).__name__)
        if position == _ZERO:
            refused = await self._refuse_unconfirmed_flat(entry, reason, parts_sent)
            if refused is not None:
                return refused
            if parts_sent == 0:
                self._journal_note(entry, PHASE_ALREADY_FLAT, reason)
            self._last_result = EmergencyCloseResult(EmergencyCloseStatus.FLAT, parts_sent, reason)
            return True

        try:
            filters = await self._adapter.symbol_lot_filters(symbol=symbol)
        except Exception as exc:  # noqa: BLE001 - Q3: no live filters means no valid part
            return self._fail(
                entry, reason, "LOT_FILTERS_UNAVAILABLE", parts_sent, type(exc).__name__
            )
        if not isinstance(filters, LotFilters):
            return self._fail(
                entry, reason, "LOT_FILTERS_UNAVAILABLE", parts_sent, "InvalidFilters"
            )

        # An attempt number is never reused, also across restarts: continue after the last
        # attempt the exchange knows about (a probe failure means the history is unknown). An
        # earlier attempt that is found and not terminal is adopted as the pending attempt and
        # nothing is sent (WR-03).
        try:
            attempt_no = await discover_next_attempt_no(
                adapter=self._adapter, symbol=symbol, plan_hash=entry.plan_hash
            )
        except CloseAttemptNotTerminal as exc:
            adopted = _PendingAttempt(
                attempt_no=exc.attempt_no,
                client_order_id=exc.client_order_id,
                side=None,
                quantity=None,
                sent_at=self._clock(),
                seen=True,
            )
            adopted.mark_unknown(CODE_HISTORY_NOT_TERMINAL)
            self._pending[entry.plan_hash] = adopted
            return self._hold(entry, reason, adopted, parts_sent)
        except Exception as exc:  # noqa: BLE001 - an unknown attempt history stops the close
            return self._fail(
                entry,
                reason,
                "ATTEMPT_DISCOVERY_FAILED",
                parts_sent,
                type(exc).__name__,
                status=EmergencyCloseStatus.PENDING_UNKNOWN,
            )

        # Never more confirmed parts in one call than the parts planned from the REST position
        # read above (D-15): a part that does not move the position must not turn into an
        # endless loop. Attempts proven to have had no effect are bounded by the same number.
        parts_planned = max(len(plan_close_parts(position=abs(position), filters=filters).parts), 1)
        send_limit = parts_sent + parts_planned
        no_effect_attempts = 0
        while parts_sent < send_limit:
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
            if outcome.kind is _Kind.PENDING:
                # The attempt is not proven terminal: nothing else is sent (WR-03, Q5).
                return self._hold(entry, reason, self._pending[entry.plan_hash], parts_sent)
            if outcome.kind is _Kind.CLOSED:
                parts_sent += 1
            elif outcome.kind is _Kind.NO_EFFECT:
                no_effect_attempts += 1
                if no_effect_attempts > parts_planned:
                    return self._fail(entry, reason, "SEND_NOT_CONFIRMED", parts_sent, None)
            # The attempt is terminal (or was rejected): only now is the position re-read.
            try:
                position = await self._read_position(symbol)
            except Exception as exc:  # noqa: BLE001 - flat is proven by REST or not at all
                return self._fail(
                    entry, reason, "POSITION_READ_FAILED", parts_sent, type(exc).__name__
                )
            if position == _ZERO:
                refused = await self._refuse_unconfirmed_flat(entry, reason, parts_sent)
                if refused is not None:
                    return refused
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
    # One part: journal-first send, then a query of its id; never a second send while the
    # attempt is not proven terminal (Q5 applied to the close, 19-REVIEW WR-03).
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
        # Remembered BEFORE the send, so an interrupted call cannot forget an attempt that may
        # have reached the exchange; dropped only when nothing was placed.
        pending = _PendingAttempt(
            attempt_no=attempt_no,
            client_order_id=client_order_id,
            side=side,
            quantity=quantity,
            sent_at=self._clock(),
            seen=False,
        )
        self._pending[entry.plan_hash] = pending
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
            del self._pending[entry.plan_hash]
            journal(PHASE_NOT_SENT, type(exc).__name__)
            return _Outcome(_Kind.NOT_SENT, error_type=type(exc).__name__)
        except Exception as exc:  # noqa: BLE001 - classified below; ambiguity is probed
            error_type = type(exc).__name__
            if self._is_definitive_rejection(exc):
                del self._pending[entry.plan_hash]
                journal(PHASE_REJECTED, error_type)
                return _Outcome(_Kind.REJECTED, error_type=error_type)
            journal(PHASE_AMBIGUOUS, error_type)
        else:
            if answer is None:
                journal(PHASE_AMBIGUOUS)
            else:
                # An ACK proves the attempt exists, not that it filled: it stays pending until
                # a query of its id shows a terminal status.
                pending.seen = True
                journal(PHASE_POST_SEND)
        kind = await self._poll(entry, close_reason, pending)
        if kind is not _Kind.PENDING:
            del self._pending[entry.plan_hash]
        return _Outcome(kind)

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

    async def _poll(
        self, entry: RestingEntry, close_reason: str, pending: _PendingAttempt
    ) -> _Kind:
        """Query the pending attempt by its id: CLOSED, NO_EFFECT, or still PENDING (T-19-29).

        ``found=False`` is never read as absence for an attempt that was sent: right after an
        ambiguous send, or after an ACK or an earlier find, it marks the attempt UNKNOWN (Q5). A
        failed or indeterminate query of an attempt never seen marks it UNKNOWN too; of an
        attempt known to exist it only waits. A status that is neither known-active nor
        terminal marks it UNKNOWN. Every PENDING answer keeps the attempt; nothing is resent.
        """

        def journal(phase: str) -> None:
            self._journal_attempt(
                entry,
                phase,
                close_reason,
                pending.attempt_no,
                pending.client_order_id,
                pending.side,
                pending.quantity,
            )

        try:
            probe = await self._adapter.query_order_by_client(
                symbol=entry.symbol, orig_client_order_id=pending.client_order_id
            )
        except Exception as exc:  # noqa: BLE001 - existence or end unknown: wait, never resend
            if not pending.seen:
                pending.mark_unknown(CODE_PROBE_FAILED, type(exc).__name__)
            return _Kind.PENDING
        found = _attr(probe, "found")
        if found is False:
            pending.mark_unknown(
                CODE_NOT_FOUND_AFTER_ACK if pending.seen else CODE_ABSENT_AFTER_AMBIGUOUS_SEND
            )
            return _Kind.PENDING
        if found is not True:
            if not pending.seen:
                pending.mark_unknown(CODE_PROBE_INDETERMINATE)
            return _Kind.PENDING
        pending.seen = True
        status = _attr(probe, "status")
        if status == _STATUS_FILLED:
            journal(PHASE_FILLED)
            return _Kind.CLOSED
        if status in _TERMINAL_NOT_FILLED:
            journal(PHASE_ENDED_UNFILLED)
            return _Kind.NO_EFFECT
        if status not in _ACTIVE_STATUSES:
            pending.mark_unknown(CODE_STATUS_UNREADABLE)
        return _Kind.PENDING

    def _hold(
        self,
        entry: RestingEntry,
        close_reason: str,
        pending: _PendingAttempt,
        parts_sent: int,
    ) -> bool:
        """Answer False for a pending attempt; nothing is sent while it is not terminal.

        Before the poll deadline (measured from the send on the injected clock, whole
        milliseconds) a known, active attempt is ``PENDING``. An UNKNOWN attempt, or one still
        not terminal at ``protection.emergency_close_poll_timeout_ms``, is ``PENDING_UNKNOWN``:
        the first time, SAFE_MODE, ONE critical alert and a ``failed`` journal row (the
        episode); afterwards only the result is reported. The attempt stays pending, so the next
        call queries it again.
        """
        elapsed_ms = (self._clock() - pending.sent_at) // _ONE_MS
        if pending.unknown_code is None and elapsed_ms >= self._poll_timeout_ms:
            pending.mark_unknown(CODE_POLL_DEADLINE_PASSED)
        code = pending.unknown_code
        if code is None:
            self._last_result = EmergencyCloseResult(
                EmergencyCloseStatus.PENDING, parts_sent, CODE_ATTEMPT_NOT_TERMINAL
            )
            return False
        if not pending.alerted:
            pending.alerted = True
            return self._fail(
                entry,
                close_reason,
                code,
                parts_sent,
                pending.error_type,
                status=EmergencyCloseStatus.PENDING_UNKNOWN,
            )
        self._last_result = EmergencyCloseResult(
            EmergencyCloseStatus.PENDING_UNKNOWN, parts_sent, code
        )
        return False

    # ------------------------------------------------------------------ #
    # REST reads.
    # ------------------------------------------------------------------ #

    async def _refuse_unconfirmed_flat(
        self, entry: RestingEntry, close_reason: str, parts_sent: int
    ) -> bool | None:
        """T-8-30 (19-REVIEW CR-03): confirm a zero read with a second, fresh REST read.

        Called right after a read showed the position flat and before the closer answers True
        (which makes the coordinator go FLAT and sweep every protective leg). ``None`` means the
        second read is flat too. A second read that is not flat (a transient position gap) or
        that fails is never flat: the close fails closed (SAFE_MODE, critical alert, False)
        WITHOUT sending another part in this call; the coordinator's next step calls the closer
        again, which starts over from fresh reads.
        """
        try:
            confirmed = await self._read_position(entry.symbol)
        except Exception as exc:  # noqa: BLE001 - an unreadable position proves nothing
            return self._fail(
                entry, close_reason, "POSITION_READ_FAILED", parts_sent, type(exc).__name__
            )
        if confirmed != _ZERO:
            return self._fail(entry, close_reason, CODE_TRANSIENT_POSITION_GAP, parts_sent, None)
        return None

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
        side: str | None,
        quantity: Decimal | None,
        *,
        error_type: str | None = None,
    ) -> None:
        """One attempt row; ``side`` and ``quantity`` are omitted for an attempt adopted from
        the exchange history, whose order this process did not send (WR-03)."""
        payload: dict[str, str | int | None] = {
            "phase": phase,
            "plan_hash": entry.plan_hash,
            "symbol": entry.symbol,
            "reason": close_reason,
            "attempt_no": attempt_no,
            "client_order_id": client_order_id,
        }
        if side is not None:
            payload["side"] = side
        if quantity is not None:
            payload["quantity"] = str(quantity)
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
    "CODE_ABSENT_AFTER_AMBIGUOUS_SEND",
    "CODE_ATTEMPT_NOT_TERMINAL",
    "CODE_HISTORY_NOT_TERMINAL",
    "CODE_NOT_FOUND_AFTER_ACK",
    "CODE_POLL_DEADLINE_PASSED",
    "CODE_PROBE_FAILED",
    "CODE_PROBE_INDETERMINATE",
    "CODE_STATUS_UNREADABLE",
    "CODE_TRANSIENT_POSITION_GAP",
    "EVENT_EMERGENCY_CLOSE",
    "SAFE_MODE_EMERGENCY_CLOSE_FAILED",
    "CloseAdapter",
    "CloseAttemptNotTerminal",
    "EmergencyCloseResult",
    "EmergencyCloseStatus",
    "MarketEmergencyCloser",
    "discover_next_attempt_no",
]
