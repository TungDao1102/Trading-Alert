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

from src.domain.journal import JournalEvent, content_hash_event_id
from src.domain.lot_filters import LotFilters
from src.execution.lot_split import next_close_part
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

_ZERO = Decimal("0")
_POSITION_SIDE_ONE_WAY = "BOTH"
_CORRELATION_PREFIX = "emergency_close_"
_EVENT_ID_PREFIX = "ecl"


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

        quantity = next_close_part(remaining=abs(position), filters=filters)
        if quantity is None:
            return self._fail(entry, reason, "NO_VALID_PART", 0, None)

        side = "SELL" if position > _ZERO else "BUY"
        client_order_id = derive_close_order_id(plan_hash=entry.plan_hash, attempt_no=1)
        self._journal_attempt(entry, PHASE_PRE_SEND, reason, 1, client_order_id, side, quantity)
        await self._adapter.place_market_close(
            symbol=symbol,
            side=side,
            position_side=_POSITION_SIDE_ONE_WAY,
            quantity=quantity,
            new_client_order_id=client_order_id,
        )
        self._journal_attempt(entry, PHASE_POST_SEND, reason, 1, client_order_id, side, quantity)

        try:
            position = await self._read_position(symbol)
        except Exception as exc:  # noqa: BLE001 - flat is proven by REST or not at all
            return self._fail(entry, reason, "POSITION_READ_FAILED", 1, type(exc).__name__)
        if position != _ZERO:
            return self._fail(entry, reason, "NOT_FLAT_AFTER_PART", 1, None)
        self._last_result = EmergencyCloseResult(EmergencyCloseStatus.FLAT, 1, reason)
        return True

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
        self._last_result = EmergencyCloseResult(
            EmergencyCloseStatus.CLOSE_FAILED, parts_sent, code
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
]
