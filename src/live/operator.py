"""The operator commands of the live process, over Telegram (plan 24-23; R-4, OQ-5, 24-01 Q7).

The owner answered Q7 with this set and nothing else:

  * `/status`            read only: mode, SAFE_MODE and its reason, entry enablement, REST gate,
                         user-data stream, protections.
  * `/disable_entries`   risk reducing, no confirm: entries are disabled with the user id journaled.
  * `/safemode_exit`     two steps: a prompt carrying a one-time token, then `/confirm <token>`.
                         The exit goes through `SafeModeController.exit_safe_mode` in process, so
                         every one of its exit rows decides (gate, stream, restore, compare,
                         readiness); a refusal is answered with the controller's own codes.
  * `/close SYMBOL`      two steps, as above; after the confirm the position is closed through the
                         protection coordinator's own close flow (reduce-only MARKET by the
                         emergency closer, which reads the quantity itself).
  * `/confirm <token>`   the second step of the two commands above.

No command opens an entry, raises a position or touches leverage or margin type (D085 stays
deferred); clearing the REST gate stays an ssh command (the gate state file is process state of a
restart, not of a running gate).

Authentication (D-28, 20-DEFERRED D-15) is the Phase 23 allow-list and the same two gates as
`on_callback`: the authorized chat first, then user id present, chat type "private", user id in
`TELEGRAM_AUTHORIZED_USER_IDS`. A refused command changes nothing, is journaled with the presser's
user id, the chat id and a fixed reason code (never the message text), and is answered with the
neutral text "Rejected".

The confirm token is `issue_one_time_token()`: single use, bound to the user that asked, and valid
for `CONFIRM_TTL_SECONDS_DEFAULT` seconds. Only its SHA-256 is kept in memory. An expired, replayed,
unknown or other-user token changes nothing. A pending confirmation is memory only: a restart
forgets it, which is the safe direction.

The handlers are `async (update, context)` callables so plan 24-27 can register them as
`CommandHandler` callbacks; they read only `update.update_id`, `update.effective_chat` and
`update.effective_user` and `context.args`. All time comes from the injected clock.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

import structlog

from src.adapters.telegram_callbacks import (
    _validate_authorized_user_ids,
    authorized_chat_gate,
    authorized_user_gate,
)
from src.approval.confirm_core import CONFIRM_TTL_SECONDS_DEFAULT
from src.approval.tokens import issue_one_time_token, token_hash_of, verify_token_hash
from src.domain.journal import JournalEvent, correlated_event_id
from src.execution.manager import operator_close_position
from src.execution.protection import PlanProtection, ProtectionState
from src.live.execution_service import JournalWriter
from src.reconcile.local_intent import derive_local_intent
from src.reconcile.safe_mode import ExitReadiness, build_exit_readiness

log = structlog.get_logger(__name__)

#: The Telegram command names (without the slash) and the handler each one is registered with.
COMMAND_STATUS: Final = "status"
COMMAND_DISABLE_ENTRIES: Final = "disable_entries"
COMMAND_SAFEMODE_EXIT: Final = "safemode_exit"
COMMAND_CLOSE: Final = "close"
COMMAND_CONFIRM: Final = "confirm"

EVENT_COMMAND: Final = "OPERATOR_COMMAND"
EVENT_COMMAND_REJECTED: Final = "OPERATOR_COMMAND_REJECTED"

#: Result codes of a handler (also the `code` of the journal row).
CODE_STATUS: Final = "STATUS"
CODE_ENTRIES_DISABLED: Final = "ENTRIES_DISABLED"
CODE_ALREADY_DISABLED: Final = "ALREADY_DISABLED"
CODE_CONFIRM_REQUIRED: Final = "CONFIRM_REQUIRED"
CODE_NOT_IN_SAFE_MODE: Final = "NOT_IN_SAFE_MODE"
CODE_SAFE_MODE_EXITED: Final = "SAFE_MODE_EXITED"
CODE_EXIT_REFUSED: Final = "EXIT_REFUSED"
CODE_EXIT_NOT_RECORDED: Final = "EXIT_NOT_RECORDED"
CODE_BAD_USAGE: Final = "BAD_USAGE"
CODE_UNKNOWN_SYMBOL: Final = "UNKNOWN_SYMBOL"
CODE_NOTHING_TO_CLOSE: Final = "NOTHING_TO_CLOSE"
CODE_AMBIGUOUS_SYMBOL: Final = "AMBIGUOUS_SYMBOL"
CODE_TOKEN_UNKNOWN: Final = "TOKEN_UNKNOWN"
CODE_TOKEN_EXPIRED: Final = "TOKEN_EXPIRED"
CODE_TOKEN_OTHER_USER: Final = "TOKEN_OTHER_USER"
CODE_CHAT_NOT_AUTHORIZED: Final = "CHAT_NOT_AUTHORIZED"
CODE_CHAT_UNAVAILABLE: Final = "CHAT_UNAVAILABLE"

_ACTION_SAFEMODE_EXIT: Final = "safemode_exit"
_ACTION_CLOSE: Final = "close"
_ENTITY_TYPE: Final = "OperatorCommand"
_JOURNAL_PREFIX: Final = "opcmd"
_REJECTED_TEXT: Final = "Rejected"
#: Code of a refused command in `OperatorResult` (the precise reason is in the journal row).
_REJECTED: Final = "REJECTED"
_NOT_CONFIRMED_TEXT: Final = "Not confirmed: the token is unknown, used, expired or not yours."
#: A symbol is a short run of upper-case letters and digits (Binance USD-M symbols).
_SYMBOL_MAX_LENGTH: Final = 20
#: At most this many confirmations wait at once; the oldest is dropped first.
_MAX_PENDING: Final = 8
#: Plan states that hold nothing to close (the coordinator refuses them too).
_FINISHED_STATES: Final = frozenset({ProtectionState.FLAT, ProtectionState.ENTRY_ENDED_NO_FILL})

ReplyFn = Callable[[int, str], Awaitable[None]]


@dataclass(frozen=True)
class OperatorResult:
    """What a handler did: `ok` is True only when the command was accepted; `code` is fixed text."""

    ok: bool
    code: str


@dataclass(frozen=True)
class _Pending:
    """One confirmation waiting for its `/confirm` (memory only)."""

    action: str
    user_id: int
    expires_at_utc: datetime
    symbol: str | None = None
    plan_hash: str | None = None


@dataclass(frozen=True)
class _Caller:
    chat_id: int
    user_id: int


class OperatorCommands:
    """The authenticated operator command set of the live process (see the module docstring).

    Args:
        authorized_chat_id: The one chat the commands are accepted from.
        authorized_user_ids: Non-empty frozenset of Telegram user ids that may command.
        controller: The durable `SafeModeController`.
        enablement: The `LiveEnablementController` (only `is_disabled` and `disable` are used).
        coordinator: The `ProtectionCoordinator` (protections, restore flag, close flow).
        intent_store: The execution intent store (`list_unresolved_intents`).
        pending_actions: The pending protective action store (`list_open`), a SAFE_MODE exit input.
        gate: The REST gate (`restriction()` and `recovery_status()`).
        stream_state: Zero-argument callable returning the user-data stream state (str or enum).
        journal: Where command rows go.
        clock: UTC-aware "now"; the only time source.
        reply: `async (chat_id, text)`; a failing reply is logged and changes nothing.
        ttl_seconds: How long a confirm token stays valid.
    """

    def __init__(
        self,
        *,
        authorized_chat_id: int,
        authorized_user_ids: frozenset[int],
        controller: Any,
        enablement: Any,
        coordinator: Any,
        intent_store: Any,
        pending_actions: Any,
        gate: Any,
        stream_state: Callable[[], Any],
        journal: JournalWriter,
        clock: Callable[[], datetime],
        reply: ReplyFn,
        ttl_seconds: int = CONFIRM_TTL_SECONDS_DEFAULT,
    ) -> None:
        _validate_authorized_user_ids(authorized_user_ids)
        if isinstance(authorized_chat_id, bool) or not isinstance(authorized_chat_id, int):
            raise ValueError("authorized_chat_id must be an int")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be a positive int")
        self._chat_id = authorized_chat_id
        self._user_ids = authorized_user_ids
        self._controller = controller
        self._enablement = enablement
        self._coordinator = coordinator
        self._intents = intent_store
        self._pending_actions = pending_actions
        self._gate = gate
        self._stream_state = stream_state
        self._journal = journal
        self._clock = clock
        self._reply = reply
        self._ttl = timedelta(seconds=ttl_seconds)
        self._pending: OrderedDict[str, _Pending] = OrderedDict()
        self._seq = 0

    # ----- registration ---------------------------------------------------------------------- #

    def handlers(self) -> dict[str, Callable[[Any, Any], Awaitable[OperatorResult]]]:
        """Command name (no slash) -> handler, for plan 24-27's `CommandHandler` registration."""
        return {
            COMMAND_STATUS: self.status,
            COMMAND_DISABLE_ENTRIES: self.disable_entries,
            COMMAND_SAFEMODE_EXIT: self.safemode_exit,
            COMMAND_CLOSE: self.close,
            COMMAND_CONFIRM: self.confirm,
        }

    # ----- the commands ---------------------------------------------------------------------- #

    async def status(self, update: Any, context: Any = None) -> OperatorResult:
        """Read only: report the system state. Changes nothing."""
        caller = await self._authorize(update, COMMAND_STATUS)
        if caller is None:
            return OperatorResult(False, _REJECTED)
        lines = self._status_lines()
        await self._send(caller.chat_id, "\n".join(lines))
        self._audit(update, COMMAND_STATUS, caller, CODE_STATUS)
        return OperatorResult(True, CODE_STATUS)

    async def disable_entries(self, update: Any, context: Any = None) -> OperatorResult:
        """Disable new entries now (risk reducing, so no confirm); idempotent."""
        caller = await self._authorize(update, COMMAND_DISABLE_ENTRIES)
        if caller is None:
            return OperatorResult(False, _REJECTED)
        if self._enablement.is_disabled:
            await self._send(caller.chat_id, "Entries are already disabled.")
            self._audit(update, COMMAND_DISABLE_ENTRIES, caller, CODE_ALREADY_DISABLED)
            return OperatorResult(True, CODE_ALREADY_DISABLED)
        try:
            self._enablement.disable(operator_id=_operator_id(caller), now_utc=self._clock())
        except Exception as exc:  # noqa: BLE001 - the flag flips first; report what is true
            log.error("live.operator.disable_audit_failed", error_class=type(exc).__name__)
        text = (
            "Entries are disabled."
            if self._enablement.is_disabled
            else "Entries could NOT be disabled."
        )
        await self._send(caller.chat_id, text)
        self._audit(update, COMMAND_DISABLE_ENTRIES, caller, CODE_ENTRIES_DISABLED)
        return OperatorResult(self._enablement.is_disabled, CODE_ENTRIES_DISABLED)

    async def safemode_exit(self, update: Any, context: Any = None) -> OperatorResult:
        """Step one of leaving SAFE_MODE: issue a confirm token. Nothing changes yet."""
        caller = await self._authorize(update, COMMAND_SAFEMODE_EXIT)
        if caller is None:
            return OperatorResult(False, _REJECTED)
        if not self._controller.in_safe_mode:
            await self._send(caller.chat_id, "Not in SAFE_MODE; nothing to exit.")
            self._audit(update, COMMAND_SAFEMODE_EXIT, caller, CODE_NOT_IN_SAFE_MODE)
            return OperatorResult(False, CODE_NOT_IN_SAFE_MODE)
        token = self._issue(_Pending(_ACTION_SAFEMODE_EXIT, caller.user_id, self._expiry()))
        await self._send(
            caller.chat_id,
            "Leave SAFE_MODE? The system checks every exit row first. "
            f"Within {self._ttl_seconds()} s send: /confirm {token}",
        )
        self._audit(update, COMMAND_SAFEMODE_EXIT, caller, CODE_CONFIRM_REQUIRED)
        return OperatorResult(True, CODE_CONFIRM_REQUIRED)

    async def close(self, update: Any, context: Any = None) -> OperatorResult:
        """Step one of closing a strategy position: check the symbol, issue a confirm token."""
        caller = await self._authorize(update, COMMAND_CLOSE)
        if caller is None:
            return OperatorResult(False, _REJECTED)
        args = _args_of(context)
        symbol = args[0] if len(args) == 1 else None
        if symbol is None or not _is_symbol(symbol):
            await self._send(caller.chat_id, "Usage: /close SYMBOL (for example /close BTCUSDT)")
            self._audit(update, COMMAND_CLOSE, caller, CODE_BAD_USAGE)
            return OperatorResult(False, CODE_BAD_USAGE)
        plan_or_code = self._closable_plan(symbol)
        if isinstance(plan_or_code, str):
            await self._send(caller.chat_id, f"Nothing to close for {symbol}: {plan_or_code}")
            self._audit(update, COMMAND_CLOSE, caller, plan_or_code, symbol=symbol)
            return OperatorResult(False, plan_or_code)
        token = self._issue(
            _Pending(
                _ACTION_CLOSE,
                caller.user_id,
                self._expiry(),
                symbol=symbol,
                plan_hash=plan_or_code.plan_hash,
            )
        )
        await self._send(
            caller.chat_id,
            f"Close the {symbol} position (plan state {plan_or_code.state.value})? "
            f"Within {self._ttl_seconds()} s send: /confirm {token}",
        )
        self._audit(update, COMMAND_CLOSE, caller, CODE_CONFIRM_REQUIRED, symbol=symbol)
        return OperatorResult(True, CODE_CONFIRM_REQUIRED)

    async def confirm(self, update: Any, context: Any = None) -> OperatorResult:
        """Step two: run the action behind a valid, unused, unexpired token of the same user."""
        caller = await self._authorize(update, COMMAND_CONFIRM)
        if caller is None:
            return OperatorResult(False, _REJECTED)
        args = _args_of(context)
        token = args[0] if len(args) == 1 else ""
        pending, code = self._take(token, caller.user_id)
        if pending is None:
            await self._send(caller.chat_id, _NOT_CONFIRMED_TEXT)
            self._audit(update, COMMAND_CONFIRM, caller, code)
            return OperatorResult(False, code)
        if pending.action == _ACTION_SAFEMODE_EXIT:
            result = await self._run_safemode_exit(caller)
        else:
            result = await self._run_close(caller, pending)
        self._audit(update, COMMAND_CONFIRM, caller, result.code, symbol=pending.symbol)
        return result

    # ----- the confirmed actions ------------------------------------------------------------- #

    async def _run_safemode_exit(self, caller: _Caller) -> OperatorResult:
        if not self._controller.in_safe_mode:
            await self._send(caller.chat_id, "Not in SAFE_MODE; nothing to exit.")
            return OperatorResult(False, CODE_NOT_IN_SAFE_MODE)
        try:
            decision = await self._controller.exit_safe_mode(
                operator_id=_operator_id(caller),
                local_intent_fn=self._local_intent,
                readiness=self._readiness,
                gate_status=self._gate_status,
                stream_state=self._stream_value,
                now_utc=self._clock(),
            )
        except Exception as exc:  # noqa: BLE001 - the controller is still in SAFE_MODE
            log.error("live.operator.exit_failed", error_class=type(exc).__name__)
            await self._send(
                caller.chat_id,
                f"SAFE_MODE exit was not recorded ({type(exc).__name__}); still in SAFE_MODE.",
            )
            return OperatorResult(False, CODE_EXIT_NOT_RECORDED)
        if decision.exited:
            await self._send(caller.chat_id, "SAFE_MODE left.")
            return OperatorResult(True, CODE_SAFE_MODE_EXITED)
        rows = ", ".join(decision.refusals)
        await self._send(caller.chat_id, f"Still in SAFE_MODE. Exit refused: {rows}")
        return OperatorResult(False, CODE_EXIT_REFUSED)

    async def _run_close(self, caller: _Caller, pending: _Pending) -> OperatorResult:
        plan_hash = pending.plan_hash or ""
        symbol = pending.symbol or ""
        view = self._coordinator.protection_of(plan_hash)
        if view is None or view.symbol != symbol:
            await self._send(
                caller.chat_id, f"Nothing to close for {symbol}: {CODE_UNKNOWN_SYMBOL}"
            )
            return OperatorResult(False, CODE_UNKNOWN_SYMBOL)
        try:
            outcome = await operator_close_position(
                coordinator=self._coordinator,
                plan_hash=plan_hash,
                operator_id=_operator_id(caller),
            )
        except Exception as exc:  # noqa: BLE001 - reported by class name, never by text
            log.error("live.operator.close_failed", error_class=type(exc).__name__)
            await self._send(caller.chat_id, f"Close of {symbol} failed ({type(exc).__name__}).")
            return OperatorResult(False, "CLOSE_FAILED")
        await self._send(caller.chat_id, f"Close {symbol}: {outcome.code}")
        return OperatorResult(outcome.accepted, outcome.code)

    # ----- providers for the SAFE_MODE exit -------------------------------------------------- #

    def _local_intent(self) -> Any:
        return derive_local_intent(
            self._coordinator.protections(), self._intents.list_unresolved_intents()
        )

    def _readiness(self) -> ExitReadiness:
        return build_exit_readiness(
            unresolved_intents_fn=self._intents.list_unresolved_intents,
            protections_fn=self._coordinator.protections,
            open_pending_fn=self._pending_actions.list_open,
            restore_complete_fn=lambda: self._coordinator.restore_complete,
        )

    def _gate_status(self) -> tuple[str | None, str]:
        restriction = self._gate.restriction()
        recovery = self._gate.recovery_status()
        return (
            None if restriction is None else str(restriction.reason),
            str(getattr(recovery, "value", recovery)),
        )

    def _stream_value(self) -> str:
        state = self._stream_state()
        return str(getattr(state, "value", state))

    # ----- status ---------------------------------------------------------------------------- #

    def _status_lines(self) -> list[str]:
        controller = self._controller
        if controller.in_safe_mode:
            mode = f"SAFE_MODE (reason {controller.entered_reason})"
        else:
            mode = "NORMAL"
        lines = [
            f"mode: {mode}",
            f"entries: {'DISABLED' if self._enablement.is_disabled else 'ENABLED'}",
        ]
        try:
            restriction = self._gate.restriction()
            recovery = self._gate.recovery_status()
            gate = "OPEN" if restriction is None else str(restriction.reason)
            lines.append(f"rest gate: {gate}, recovery {getattr(recovery, 'value', recovery)}")
        except Exception as exc:  # noqa: BLE001 - a status read must not raise
            lines.append(f"rest gate: unreadable ({type(exc).__name__})")
        try:
            lines.append(f"stream: {self._stream_value()}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"stream: unreadable ({type(exc).__name__})")
        try:
            plans = self._coordinator.protections()
            open_plans = [p for p in plans if p.state not in _FINISHED_STATES]
            lines.append(f"protections: {len(open_plans)} open of {len(plans)} tracked")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"protections: unreadable ({type(exc).__name__})")
        return lines

    # ----- close helper ---------------------------------------------------------------------- #

    def _closable_plan(self, symbol: str) -> PlanProtection | str:
        """The one plan to close for `symbol`, or the fixed reason code why there is none."""
        try:
            plans: list[PlanProtection] = [
                p for p in self._coordinator.protections() if p.symbol == symbol
            ]
        except Exception as exc:  # noqa: BLE001 - fail closed
            log.error("live.operator.protections_unreadable", error_class=type(exc).__name__)
            return CODE_UNKNOWN_SYMBOL
        if not plans:
            return CODE_UNKNOWN_SYMBOL
        open_plans = [p for p in plans if p.state not in _FINISHED_STATES]
        if not open_plans:
            return CODE_NOTHING_TO_CLOSE
        if len(open_plans) > 1:
            return CODE_AMBIGUOUS_SYMBOL
        return open_plans[0]

    # ----- the gate -------------------------------------------------------------------------- #

    async def _authorize(self, update: Any, command: str) -> _Caller | None:
        """Both `on_callback` gates for a command; None after a journaled, neutral refusal."""
        chat = getattr(update, "effective_chat", None)
        user = getattr(update, "effective_user", None)
        raw_chat_id = getattr(chat, "id", None)
        chat_id = raw_chat_id if _is_int(raw_chat_id) else None
        raw_user_id = getattr(user, "id", None)
        user_id = raw_user_id if _is_int(raw_user_id) else None
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
        if reason is None and chat_id is not None and user_id is not None:
            return _Caller(chat_id=chat_id, user_id=user_id)
        reason = reason or CODE_CHAT_UNAVAILABLE
        self._journal_row(
            update,
            EVENT_COMMAND_REJECTED,
            command,
            {"command": command, "reason_code": reason, "user_id": user_id, "chat_id": chat_id},
        )
        if chat_id is not None:
            await self._send(chat_id, _REJECTED_TEXT)
        return None

    # ----- confirm tokens -------------------------------------------------------------------- #

    def _issue(self, pending: _Pending) -> str:
        """Store `pending` under the hash of a fresh token and return the raw token."""
        self._purge_expired()
        # A user asking for the same thing again replaces the earlier token.
        for key in [k for k, v in self._pending.items() if _same_ask(v, pending)]:
            del self._pending[key]
        while len(self._pending) >= _MAX_PENDING:
            self._pending.popitem(last=False)
        token = issue_one_time_token()
        self._pending[token_hash_of(token)] = pending
        return token

    def _take(self, token: str, user_id: int) -> tuple[_Pending | None, str]:
        """Consume the token's pending ask, or `(None, code)`; nothing changes on a refusal."""
        if not token:
            return None, CODE_TOKEN_UNKNOWN
        digest = token_hash_of(token)
        pending = self._pending.get(digest)
        if pending is None or not verify_token_hash(token, digest):
            return None, CODE_TOKEN_UNKNOWN
        if pending.user_id != user_id:
            return None, CODE_TOKEN_OTHER_USER
        if self._clock() >= pending.expires_at_utc:
            del self._pending[digest]
            return None, CODE_TOKEN_EXPIRED
        # Single use: this token and every other waiting ask of the same kind go.
        for key in [k for k, v in self._pending.items() if _same_ask(v, pending)]:
            del self._pending[key]
        return pending, "OK"

    def _purge_expired(self) -> None:
        now = self._clock()
        for key in [k for k, v in self._pending.items() if now >= v.expires_at_utc]:
            del self._pending[key]

    def _expiry(self) -> datetime:
        return self._clock() + self._ttl

    def _ttl_seconds(self) -> int:
        return int(self._ttl.total_seconds())

    # ----- audit and reply ------------------------------------------------------------------- #

    def _audit(
        self,
        update: Any,
        command: str,
        caller: _Caller,
        code: str,
        *,
        symbol: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "command": command,
            "code": code,
            "user_id": caller.user_id,
            "chat_id": caller.chat_id,
        }
        if symbol is not None:
            payload["symbol"] = symbol
        self._journal_row(update, EVENT_COMMAND, command, payload)

    def _journal_row(
        self, update: Any, event_type: str, command: str, payload: dict[str, Any]
    ) -> None:
        """Append one row; a failing journal is logged by class name and never undoes a command.

        The state changes themselves carry the operator id in the controllers' own rows, and a
        risk-reducing action never waits for the journal (D-16).
        """
        update_id = getattr(update, "update_id", None)
        if _is_int(update_id):
            correlation = f"upd:{update_id}"
        else:
            self._seq += 1
            correlation = f"local:{self._seq}"
        try:
            self._journal.record(
                JournalEvent(
                    journal_event_id=correlated_event_id(
                        prefix=_JOURNAL_PREFIX,
                        correlation_id=correlation,
                        event_type=event_type,
                        entity_id=command,
                        step=str(payload.get("code") or payload.get("reason_code")),
                    ),
                    occurred_at_utc=self._clock(),
                    event_type=event_type,
                    entity_type=_ENTITY_TYPE,
                    entity_id=command,
                    correlation_id=correlation,
                    payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
                )
            )
        except Exception as exc:  # noqa: BLE001 - an audit row must not break the command
            log.warning("live.operator.journal_failed", error_class=type(exc).__name__)

    async def _send(self, chat_id: int, text: str) -> None:
        try:
            await self._reply(chat_id, text)
        except Exception as exc:  # noqa: BLE001 - a lost reply changes nothing
            log.warning("live.operator.reply_failed", error_class=type(exc).__name__)


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _operator_id(caller: _Caller) -> str:
    """The audit id every controller row carries: the Telegram user id."""
    return f"tg:{caller.user_id}"


def _args_of(context: Any) -> list[str]:
    args = getattr(context, "args", None)
    if not isinstance(args, list | tuple):
        return []
    return [a for a in args if isinstance(a, str)]


def _is_symbol(text: str) -> bool:
    return (
        0 < len(text) <= _SYMBOL_MAX_LENGTH
        and text.isascii()
        and text.isalnum()
        and text == text.upper()
    )


def _same_ask(a: _Pending, b: _Pending) -> bool:
    return (a.action, a.user_id, a.plan_hash) == (b.action, b.user_id, b.plan_hash)


__all__ = [
    "COMMAND_CLOSE",
    "COMMAND_CONFIRM",
    "COMMAND_DISABLE_ENTRIES",
    "COMMAND_SAFEMODE_EXIT",
    "COMMAND_STATUS",
    "EVENT_COMMAND",
    "EVENT_COMMAND_REJECTED",
    "OperatorCommands",
    "OperatorResult",
]
