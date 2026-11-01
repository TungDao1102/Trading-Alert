"""The owner-triggered Demo smoke injection: `/demo_signal [far|fill]` (plan 24-27B).

The live process had a queue-based `DemoSmokeSignalSource` and a pump that hands each queued
request to the approval sender, but nothing could put a request on that queue inside the running
process (`scripts/demo_rehearsal.py` builds its own objects). This module is that path.

**Which route, and why.** A Telegram operator command, on the same two gates as every other
operator command (the authorized chat first, then private chat type and a user id in the
allow-list), registered next to them on the live bot. Alternatives that were not taken: a watched
file (a second trust boundary on the state volume, polling, a format to validate) and a network
listener (a new open port and authentication surface: it needs a DECISIONS row first, and there is
none). The command adds no channel: the owner is already authenticated to this process through the
bot, and the approval card that follows is the existing APPROVE / CONFIRM flow, so a command alone
never places anything.

**DEMO only.** `build_demo_signal_command` returns None for any mode but DEMO, the constructor
refuses one, and `check_wiring` fails when a non-DEMO wiring registers the command. Nothing here is
reachable in LIVE or TESTNET.

**What it does.** For one scenario (`far`, the default, never fills; or `fill`) it reads the live
Demo inputs through the signed adapter (exchange filters, the mark price, the account commission
rate, the account equity), derives the request with `DemoSmokeSignalSource.derive_request` sized
from the LIVE account equity (so the quantity the producer sizes at placement equals the approved
one; the binding never clips), and queues it. One request may wait at a time. Every outcome is
journaled with a fixed code (never the message text, never a price or a quantity) and answered
with a short fixed text.

No wall clock is read here: the clock, the readers and the reply are injected.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

import structlog

from src.adapters.binance_client import Environment
from src.adapters.telegram_callbacks import (
    _validate_authorized_user_ids,
    authorized_chat_gate,
    authorized_user_gate,
)
from src.domain.journal import JournalEvent, correlated_event_id
from src.live.signal_source import SCENARIO_FAR, SCENARIOS, DemoSmokeSignalSource

log = structlog.get_logger(__name__)

COMMAND_DEMO_SIGNAL: Final = "demo_signal"

EVENT_DEMO_SIGNAL: Final = "DEMO_SIGNAL_COMMAND"
EVENT_DEMO_SIGNAL_REJECTED: Final = "DEMO_SIGNAL_COMMAND_REJECTED"

CODE_QUEUED: Final = "QUEUED"
CODE_ALREADY_QUEUED: Final = "ALREADY_QUEUED"
CODE_BAD_USAGE: Final = "BAD_USAGE"
CODE_FILTERS_UNAVAILABLE: Final = "FILTERS_UNAVAILABLE"
CODE_EQUITY_UNAVAILABLE: Final = "EQUITY_UNAVAILABLE"
CODE_DERIVATION_FAILED: Final = "DERIVATION_FAILED"
CODE_CHAT_NOT_AUTHORIZED: Final = "CHAT_NOT_AUTHORIZED"
CODE_CHAT_UNAVAILABLE: Final = "CHAT_UNAVAILABLE"

_REJECTED: Final = "REJECTED"
_REJECTED_TEXT: Final = "Rejected"
_ENTITY_TYPE: Final = "DemoSignalCommand"
_JOURNAL_PREFIX: Final = "demosig"

ReplyFn = Callable[[int, str], Awaitable[None]]
Record = Callable[[JournalEvent], Awaitable[None]]


class DemoSignalCommand:
    """The `/demo_signal` handler (see the module docstring)."""

    def __init__(
        self,
        *,
        mode: Environment,
        authorized_chat_id: int,
        authorized_user_ids: frozenset[int],
        source: DemoSmokeSignalSource,
        adapter: Any,
        equity: Any,
        risk_rate: Decimal,
        symbol: str,
        record: Record,
        clock: Callable[[], datetime],
        reply: ReplyFn,
    ) -> None:
        if mode is not Environment.DEMO:
            raise ValueError("the Demo signal command exists in DEMO mode only")
        _validate_authorized_user_ids(authorized_user_ids)
        if isinstance(authorized_chat_id, bool) or not isinstance(authorized_chat_id, int):
            raise ValueError("authorized_chat_id must be an int")
        if not isinstance(source, DemoSmokeSignalSource):
            raise TypeError("source must be the DemoSmokeSignalSource")
        self._chat_id = authorized_chat_id
        self._user_ids = authorized_user_ids
        self._source = source
        self._adapter = adapter
        self._equity = equity
        self._risk_rate = risk_rate
        self._symbol = symbol
        self._record = record
        self._clock = clock
        self._reply = reply
        self._seq = 0

    @property
    def source(self) -> DemoSmokeSignalSource:
        """The queue the command feeds (the D-05 gate compares it with the pump's source)."""
        return self._source

    async def handle(self, update: Any, context: Any = None) -> bool:
        """`/demo_signal [far|fill]`. True only when a request was queued."""
        chat_id = await self._authorize(update)
        if chat_id is None:
            return False
        args = [a for a in (getattr(context, "args", None) or ()) if isinstance(a, str)]
        scenario = args[0].lower() if args else SCENARIO_FAR
        if len(args) > 1 or scenario not in SCENARIOS:
            return await self._finish(
                update, chat_id, CODE_BAD_USAGE, "Usage: /demo_signal [far|fill]"
            )
        if self._source.pending > 0:
            return await self._finish(
                update, chat_id, CODE_ALREADY_QUEUED, "A request is already waiting."
            )
        try:
            listed = await self._adapter.exchange_info([self._symbol])
            filters = next((row for row in listed if row.symbol == self._symbol), None)
            mark = (await self._adapter.get_mark_price(symbol=self._symbol)).mark_price
            commission = await self._adapter.user_commission_rate(self._symbol)
        except Exception as exc:  # noqa: BLE001 - class name only
            return await self._finish(
                update,
                chat_id,
                CODE_FILTERS_UNAVAILABLE,
                "The Demo readings are unavailable.",
                error_class=type(exc).__name__,
            )
        if filters is None:
            return await self._finish(
                update, chat_id, CODE_FILTERS_UNAVAILABLE, "The Demo readings are unavailable."
            )
        try:
            await self._equity.refresh()
            now = self._clock()
            resolved = self._equity.resolve(risk_rate=self._risk_rate, now_utc=now)
        except Exception as exc:  # noqa: BLE001 - class name only
            return await self._finish(
                update,
                chat_id,
                CODE_EQUITY_UNAVAILABLE,
                "The account equity is unavailable.",
                error_class=type(exc).__name__,
            )
        if resolved.equity is None:
            return await self._finish(
                update, chat_id, CODE_EQUITY_UNAVAILABLE, "The account equity is unavailable."
            )
        try:
            request = self._source.submit(
                scenario=scenario,
                filters=filters,
                mark_price=mark,
                commission=commission,
                observed_at=now,
                latest_closed_bar_close=now.replace(minute=0, second=0, microsecond=0),
                account_equity=resolved.equity,
            )
        except Exception as exc:  # noqa: BLE001 - class name only
            return await self._finish(
                update,
                chat_id,
                CODE_DERIVATION_FAILED,
                "No request could be derived.",
                error_class=type(exc).__name__,
            )
        return await self._finish(
            update,
            chat_id,
            CODE_QUEUED,
            f"Queued a {scenario} request; the approval card follows.",
            scenario=scenario,
            signal_id=request.signal.signal_id,
            ok=True,
        )

    # ---- authentication, journal, reply ---------------------------------------------------- #

    async def _authorize(self, update: Any) -> int | None:
        chat = getattr(update, "effective_chat", None)
        user = getattr(update, "effective_user", None)
        raw_chat_id = getattr(chat, "id", None)
        chat_id = raw_chat_id if _is_int(raw_chat_id) else None
        raw_user_id = getattr(user, "id", None)
        reason: str | None
        if chat_id is None:
            reason = CODE_CHAT_UNAVAILABLE
        elif not authorized_chat_gate(callback_chat_id=chat_id, authorized_chat_id=self._chat_id):
            reason = CODE_CHAT_NOT_AUTHORIZED
        else:
            reason = authorized_user_gate(
                from_user_id=raw_user_id,
                chat_type=getattr(chat, "type", None),
                authorized_user_ids=self._user_ids,
            )
        if reason is None and chat_id is not None:
            return int(chat_id)
        await self._journal(
            update,
            EVENT_DEMO_SIGNAL_REJECTED,
            {
                "reason_code": reason or CODE_CHAT_UNAVAILABLE,
                "user_id": raw_user_id if _is_int(raw_user_id) else None,
                "chat_id": chat_id,
            },
        )
        if chat_id is not None:
            await self._send(chat_id, _REJECTED_TEXT)
        return None

    async def _finish(
        self,
        update: Any,
        chat_id: int,
        code: str,
        text: str,
        *,
        error_class: str | None = None,
        scenario: str | None = None,
        signal_id: str | None = None,
        ok: bool = False,
    ) -> bool:
        payload: dict[str, Any] = {"code": code, "chat_id": chat_id}
        if error_class is not None:
            payload["error_class"] = error_class
        if scenario is not None:
            payload["scenario"] = scenario
        if signal_id is not None:
            payload["signal_id"] = signal_id
        await self._journal(update, EVENT_DEMO_SIGNAL, payload)
        await self._send(chat_id, text)
        return ok

    async def _journal(self, update: Any, event_type: str, payload: dict[str, Any]) -> None:
        update_id = getattr(update, "update_id", None)
        if _is_int(update_id):
            correlation = f"upd:{update_id}"
        else:
            self._seq += 1
            correlation = f"local:{self._seq}"
        try:
            await self._record(
                JournalEvent(
                    journal_event_id=correlated_event_id(
                        prefix=_JOURNAL_PREFIX,
                        correlation_id=correlation,
                        event_type=event_type,
                        entity_id=COMMAND_DEMO_SIGNAL,
                        step=str(payload.get("code") or payload.get("reason_code")),
                    ),
                    occurred_at_utc=self._clock(),
                    event_type=event_type,
                    entity_type=_ENTITY_TYPE,
                    entity_id=COMMAND_DEMO_SIGNAL,
                    correlation_id=correlation,
                    payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
                )
            )
        except Exception as exc:  # noqa: BLE001 - an audit row must not break the command
            log.warning("live.smoke_injection.journal_failed", error_class=type(exc).__name__)

    async def _send(self, chat_id: int, text: str) -> None:
        try:
            await self._reply(chat_id, text)
        except Exception as exc:  # noqa: BLE001 - a lost reply changes nothing
            log.warning("live.smoke_injection.reply_failed", error_class=type(exc).__name__)


def build_demo_signal_command(
    *,
    mode: Environment,
    source: object,
    **kwargs: Any,
) -> DemoSignalCommand | None:
    """The command for a DEMO process whose source is the Demo smoke source; None otherwise.

    LIVE and TESTNET never get the command, and a process with a strategy-driven source (a later
    phase) has no queue to feed.
    """
    if mode is not Environment.DEMO or not isinstance(source, DemoSmokeSignalSource):
        return None
    return DemoSignalCommand(mode=mode, source=source, **kwargs)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


__all__ = [
    "CODE_ALREADY_QUEUED",
    "CODE_BAD_USAGE",
    "CODE_DERIVATION_FAILED",
    "CODE_EQUITY_UNAVAILABLE",
    "CODE_FILTERS_UNAVAILABLE",
    "CODE_QUEUED",
    "COMMAND_DEMO_SIGNAL",
    "EVENT_DEMO_SIGNAL",
    "EVENT_DEMO_SIGNAL_REJECTED",
    "DemoSignalCommand",
    "build_demo_signal_command",
]
