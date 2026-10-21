"""Operational alerts: a journal-first sink and a Telegram sender with a bounded message retry.

Phase 20, plan 20-13 (D-22, D-23, T-G, OPS-05). This replaces the rehearsal-only alert sink
with the real infrastructure; the producers are wired by plan 20-22.

- `JournalFirstAlertSink` writes every alert to the journal BEFORE anything is sent (the spill
  takes the record when the journal is down, `record_after`, D-16) and then queues it. It
  satisfies the `CriticalAlertSink` protocol of the protection coordinator and the closer
  (`critical(...)`) and the alert shape of the reconcile loop (`alert(...)`).
- `TelegramAlertSender` drains that queue. A MESSAGE may be retried inside a bounded budget
  (the `NOTIFY_*` constants); a send that still fails is journaled `ALERT_SEND_FAILED` with the
  exception class name only. Nothing in this module can place, cancel or re-send an ORDER
  (Q5): the only exchange-side surface it touches is `bot.send_message`.
- The alert text is a fixed template plus enum-like fields. A reason that is not an upper-case
  code or an exception class name becomes `INVALID_REASON`, a malformed subject, symbol or plan
  hash is replaced the same way, and no exception text is ever copied into a message
  (redaction is not relied on).
- On a restart the caller passes the journaled rows to `requeue_undelivered`: every
  `OPERATIONAL_ALERT` without an `ALERT_DELIVERED` row is queued again (at least once).
- `emit_daily_state_alert` is a TEST TRIGGER for the Phase 21 daily states: no production
  module calls it until Phase 21 provides a producer.

The module reads no clock: every time comes from the caller.
"""

from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Any, Protocol, cast

from tenacity import AsyncRetrying, RetryCallState, RetryError, wait_random_exponential

from src.adapters.telegram_notify import (
    TelegramFailure,
    TelegramFailureKind,
    TelegramSendError,
    TelegramTextBot,
    send_text,
)
from src.domain.journal import JournalEvent, content_hash_event_id
from src.execution.execution_limits import ExecutionLimits, ExecutionLimitsNotConfigured
from src.ops.risk_first import AuditRecordLost, record_after
from src.ops.spill import LocalSpill
from src.paper.notify import (
    NOTIFY_MAX_ATTEMPTS,
    NOTIFY_MAX_DELAY_SECONDS,
    NOTIFY_WAIT_MAX_SECONDS,
    NOTIFY_WAIT_MULTIPLIER_SECONDS,
)

# --------------------------------------------------------------------------- #
# The event contract (T-G).
# --------------------------------------------------------------------------- #

EVENT_OPERATIONAL_ALERT = "OPERATIONAL_ALERT"
EVENT_ALERT_SUPPRESSED = "ALERT_SUPPRESSED"
EVENT_ALERT_DELIVERED = "ALERT_DELIVERED"
EVENT_ALERT_SEND_FAILED = "ALERT_SEND_FAILED"

ALERT_CORRELATION_ID = "operational_alerts"
_ENTITY_TYPE = "OperationalAlert"

INVALID_REASON = "INVALID_REASON"
INVALID_SUBJECT = "INVALID_SUBJECT"
INVALID_SYMBOL = "INVALID_SYMBOL"
INVALID_PLAN_HASH = "INVALID_PLAN_HASH"

_DEDUPE_KEY = "alerts.dedupe_window_ms"


class AlertSeverity(str, Enum):
    """How loud an alert is. CRITICAL means the operator must look now."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    WARNING = "WARNING"


# The OPS-05 matrix (20-REVIEW-RESOLUTIONS T-G). An event outside this map is a programming
# error and raises ValueError: the contract is closed.
ALERT_EVENTS = MappingProxyType(
    {
        "UNPROTECTED_POSITION": AlertSeverity.CRITICAL,
        "CLOSE_REQUIRED": AlertSeverity.CRITICAL,
        "TP_UNAVAILABLE": AlertSeverity.HIGH,
        "EMERGENCY_CLOSE_FAILED": AlertSeverity.CRITICAL,
        "EMERGENCY_CLOSE_NOT_SENT": AlertSeverity.CRITICAL,
        "PROTECTIVE_REJECTED": AlertSeverity.CRITICAL,
        "DIVERGENCE": AlertSeverity.HIGH,
        "FOREIGN_ORDER": AlertSeverity.HIGH,
        "UNKNOWN_ORDER": AlertSeverity.HIGH,
        "STALE_DATA": AlertSeverity.HIGH,
        "AUTH_FAILURE": AlertSeverity.HIGH,
        "DUPLICATE_EXECUTION_ATTEMPT": AlertSeverity.HIGH,
        "ENTRY_STATE_UNKNOWN": AlertSeverity.CRITICAL,
        "PROTECTION_HANDOFF_FAILED": AlertSeverity.CRITICAL,
        "DB_FAILURE": AlertSeverity.HIGH,
        "MANUAL_CLOSE_ORPHAN_UNVERIFIED": AlertSeverity.HIGH,
        "DAILY_STOP": AlertSeverity.CRITICAL,
        "DAILY_LOSS_WARNING": AlertSeverity.WARNING,
    }
)

# A reason is an upper-case code (B2_STOP_UNCONFIRMED) or an exception class name
# (StoreUnavailable). Anything else (spaces, `=`, `/`, `:`, `@`) cannot be one.
_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_CLASS_NAME_RE = re.compile(r"[A-Z][A-Za-z0-9]{0,63}")
_SUBJECT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
_SYMBOL_RE = re.compile(r"[A-Z0-9_]{1,32}")
_PLAN_HASH_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")


def _is_reason(value: str) -> bool:
    return bool(_CODE_RE.fullmatch(value) or _CLASS_NAME_RE.fullmatch(value))


def _require_utc(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be a UTC-aware datetime")


def _alert_id_of(*, event: str, subject: str, reason: str, occurred_at_utc: datetime) -> str:
    return content_hash_event_id(
        prefix="alert",
        event_type=EVENT_OPERATIONAL_ALERT,
        entity_id=subject,
        occurred_at_utc=occurred_at_utc,
        payload_json=json.dumps({"event": event, "reason": reason}, sort_keys=True),
    )


@dataclass(frozen=True)
class OperationalAlert:
    """One operator alert. Build it with `create`, which sanitises the free fields.

    Direct construction validates strictly and raises `ValueError`; `alert_id` is a pure
    function of `(event, subject, reason, occurred_at_utc)`.
    """

    event: str
    severity: AlertSeverity
    subject: str
    reason: str
    occurred_at_utc: datetime
    plan_hash: str | None
    symbol: str | None
    alert_id: str

    def __post_init__(self) -> None:
        if self.event not in ALERT_EVENTS:
            raise ValueError("event is not in ALERT_EVENTS")
        if self.severity is not ALERT_EVENTS[self.event]:
            raise ValueError("severity does not match the event contract")
        if not _SUBJECT_RE.fullmatch(self.subject):
            raise ValueError("subject must be non-empty and enum-like")
        if not _is_reason(self.reason) and self.reason != INVALID_REASON:
            raise ValueError("reason must be an upper-case code or an exception class name")
        if self.plan_hash is not None and not _PLAN_HASH_RE.fullmatch(self.plan_hash):
            raise ValueError("plan_hash is malformed")
        if self.symbol is not None and not _SYMBOL_RE.fullmatch(self.symbol):
            raise ValueError("symbol is malformed")
        _require_utc(self.occurred_at_utc, "occurred_at_utc")
        expected = _alert_id_of(
            event=self.event,
            subject=self.subject,
            reason=self.reason,
            occurred_at_utc=self.occurred_at_utc,
        )
        if self.alert_id != expected:
            raise ValueError("alert_id does not match the alert content")

    @classmethod
    def create(
        cls,
        *,
        event: str,
        subject: str,
        reason: str,
        occurred_at_utc: datetime,
        plan_hash: str | None = None,
        symbol: str | None = None,
    ) -> OperationalAlert:
        """Validate the event and the time, replace any free field that is not enum-like."""
        if event not in ALERT_EVENTS:
            raise ValueError("event is not in ALERT_EVENTS")
        _require_utc(occurred_at_utc, "occurred_at_utc")
        safe_subject = subject if _SUBJECT_RE.fullmatch(subject) else INVALID_SUBJECT
        safe_reason = reason if _is_reason(reason) else INVALID_REASON
        safe_plan_hash = (
            None
            if plan_hash is None
            else plan_hash
            if _PLAN_HASH_RE.fullmatch(plan_hash)
            else INVALID_PLAN_HASH
        )
        safe_symbol = (
            None if symbol is None else symbol if _SYMBOL_RE.fullmatch(symbol) else INVALID_SYMBOL
        )
        return cls(
            event=event,
            severity=ALERT_EVENTS[event],
            subject=safe_subject,
            reason=safe_reason,
            occurred_at_utc=occurred_at_utc,
            plan_hash=safe_plan_hash,
            symbol=safe_symbol,
            alert_id=_alert_id_of(
                event=event,
                subject=safe_subject,
                reason=safe_reason,
                occurred_at_utc=occurred_at_utc,
            ),
        )


def render_alert_text(alert: OperationalAlert) -> str:
    """The fixed message template: severity, event, subject, reason, UTC time. Nothing else."""
    at = alert.occurred_at_utc.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f"[{alert.severity.value}] {alert.event}\n"
        f"subject: {alert.subject}\n"
        f"reason: {alert.reason}\n"
        f"at: {at}"
    )


# --------------------------------------------------------------------------- #
# Journal rows.
# --------------------------------------------------------------------------- #


def _alert_event(alert: OperationalAlert) -> JournalEvent:
    payload_json = json.dumps(
        {
            "event": alert.event,
            "severity": alert.severity.value,
            "subject": alert.subject,
            "reason": alert.reason,
            "plan_hash": alert.plan_hash,
            "symbol": alert.symbol,
        },
        sort_keys=True,
    )
    return JournalEvent(
        journal_event_id=alert.alert_id,
        occurred_at_utc=alert.occurred_at_utc,
        event_type=EVENT_OPERATIONAL_ALERT,
        entity_type=_ENTITY_TYPE,
        entity_id=alert.alert_id,
        correlation_id=ALERT_CORRELATION_ID,
        payload_json=payload_json,
    )


def _outcome_event(
    *,
    prefix: str,
    event_type: str,
    entity_id: str,
    occurred_at_utc: datetime,
    payload: dict[str, Any],
) -> JournalEvent:
    """A follow-up row of an alert: its id is a content hash, so a replay is a no-op."""
    payload_json = json.dumps(payload, sort_keys=True)
    return JournalEvent(
        journal_event_id=content_hash_event_id(
            prefix=prefix,
            event_type=event_type,
            entity_id=entity_id,
            occurred_at_utc=occurred_at_utc,
            payload_json=payload_json,
        ),
        occurred_at_utc=occurred_at_utc,
        event_type=event_type,
        entity_type=_ENTITY_TYPE,
        entity_id=entity_id,
        correlation_id=ALERT_CORRELATION_ID,
        payload_json=payload_json,
    )


# --------------------------------------------------------------------------- #
# The sink.
# --------------------------------------------------------------------------- #


@dataclass
class _Episode:
    """One dedupe episode: the first alert of a (event, subject, reason) key and its repeats."""

    alert_id: str
    started_at_utc: datetime
    suppressed: int


class JournalFirstAlertSink:
    """Journal the alert (spill fallback), then queue it for the sender.

    Dedupe (D-23): one alert per (event, subject, reason) episode. An episode starts with the
    first alert and lasts `alerts.dedupe_window_ms` measured from that first alert; a repeat
    inside it is not queued, and each one writes an `ALERT_SUPPRESSED` row carrying the running
    count (1, 2, ...). The comparison uses the `occurred_at_utc` values the caller passes; the
    sink reads no clock. An unset window refuses construction (no default).

    `critical(...)` adapts the `CriticalAlertSink` call of the coordinator and the closer;
    `alert(...)` is the shape the reconcile loop calls. Both are synchronous.

    If neither the journal nor the spill takes the record, the alert is still queued (the
    operator should hear about it) and `AuditRecordLost` is raised; the existing callers
    already swallow sink errors.
    """

    def __init__(
        self,
        *,
        journal: Any,
        spill: LocalSpill | None,
        limits: ExecutionLimits,
        queue: deque[OperationalAlert] | None = None,
    ) -> None:
        self._journal = journal
        self._spill = spill
        window_ms = limits.alerts_dedupe_window_ms
        if window_ms is None:
            raise ExecutionLimitsNotConfigured((_DEDUPE_KEY,))
        self._window = timedelta(milliseconds=window_ms)
        self._episodes: dict[tuple[str, str, str], _Episode] = {}
        self.queue: deque[OperationalAlert] = deque() if queue is None else queue

    def alert(
        self,
        *,
        event: str,
        subject: str,
        reason: str,
        now_utc: datetime,
        plan_hash: str | None = None,
        symbol: str | None = None,
    ) -> None:
        alert = OperationalAlert.create(
            event=event,
            subject=subject,
            reason=reason,
            occurred_at_utc=now_utc,
            plan_hash=plan_hash,
            symbol=symbol,
        )
        key = (alert.event, alert.subject, alert.reason)
        episode = self._episodes.get(key)
        if episode is not None and alert.occurred_at_utc - episode.started_at_utc < self._window:
            episode.suppressed += 1
            record_after(
                spill=self._spill,
                journal=self._journal,
                event=_outcome_event(
                    prefix="alertsup",
                    event_type=EVENT_ALERT_SUPPRESSED,
                    entity_id=episode.alert_id,
                    occurred_at_utc=alert.occurred_at_utc,
                    payload={
                        "count": episode.suppressed,
                        "event": alert.event,
                        "reason": alert.reason,
                        "subject": alert.subject,
                    },
                ),
            )
            return
        self._episodes[key] = _Episode(alert.alert_id, alert.occurred_at_utc, 0)
        try:
            record_after(spill=self._spill, journal=self._journal, event=_alert_event(alert))
        finally:
            self.queue.append(alert)

    def critical(
        self, *, event: str, plan_hash: str, symbol: str, reason: str, now_utc: datetime
    ) -> None:
        """The `CriticalAlertSink` call: the symbol is the subject."""
        self.alert(
            event=event,
            subject=symbol,
            reason=reason,
            now_utc=now_utc,
            plan_hash=plan_hash,
            symbol=symbol,
        )


# --------------------------------------------------------------------------- #
# The sender: a bounded MESSAGE retry (never an order retry, Q5).
# --------------------------------------------------------------------------- #
# The predicates below are small copies of `src.paper.shadow` (`_is_retryable`, `_stop`, `_wait`,
# `_send_bounded`): that module's helpers are private and shadow-specific, so they are copied
# rather than imported. The budget constants are the shared `NOTIFY_*` ones.


def _failure_of(exc: BaseException | None) -> TelegramFailure:
    if isinstance(exc, TelegramSendError):
        return exc.failure
    name = "UnknownError" if exc is None else type(exc).__name__
    return TelegramFailure(TelegramFailureKind.UNKNOWN, None, name)


def _failure_of_state(retry_state: RetryCallState) -> TelegramFailure:
    outcome = retry_state.outcome
    return _failure_of(None if outcome is None else outcome.exception())


def _is_retryable(exc: BaseException) -> bool:
    """Transient faults only: programming errors and refusals fail at once."""
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return False
    if isinstance(exc, TelegramSendError):
        return exc.failure.kind in (
            TelegramFailureKind.RATE_LIMITED,
            TelegramFailureKind.TRANSIENT,
            TelegramFailureKind.UNKNOWN,
        )
    return True


def _retryable_state(retry_state: RetryCallState) -> bool:
    outcome = retry_state.outcome
    if outcome is None or not outcome.failed:
        return False
    exc = outcome.exception()
    return exc is not None and _is_retryable(exc)


def _remaining_budget(retry_state: RetryCallState) -> float:
    return NOTIFY_MAX_DELAY_SECONDS - (retry_state.seconds_since_start or 0.0)


def _stop(retry_state: RetryCallState) -> bool:
    """Stop at the attempt cap, at the delay budget, or when retry_after would pass it."""
    if retry_state.attempt_number >= NOTIFY_MAX_ATTEMPTS:
        return True
    remaining = _remaining_budget(retry_state)
    if remaining <= 0:
        return True
    retry_after = _failure_of_state(retry_state).retry_after_seconds
    return retry_after is not None and retry_after > remaining


_BACKOFF = wait_random_exponential(
    multiplier=NOTIFY_WAIT_MULTIPLIER_SECONDS, max=NOTIFY_WAIT_MAX_SECONDS
)


def _wait(retry_state: RetryCallState) -> float:
    """The larger of the jittered backoff and retry_after, never past the remaining budget."""
    retry_after = _failure_of_state(retry_state).retry_after_seconds or 0
    wanted = max(float(_BACKOFF(retry_state)), float(retry_after))
    return max(0.0, min(wanted, _remaining_budget(retry_state)))


async def _send_bounded(
    bot: AlertTextBot,
    chat_id: int | str,
    text: str,
    sleep: Callable[[float], Awaitable[None]],
) -> tuple[int, TelegramFailure | None]:
    """Send with the retry budget. Returns `(attempts, failure or None)`; never raises."""
    attempts = 0
    try:
        async for attempt in AsyncRetrying(
            stop=_stop,
            wait=_wait,
            retry=_retryable_state,
            reraise=True,
            sleep=sleep,
        ):
            with attempt:
                attempts += 1
                await send_text(cast(TelegramTextBot, bot), chat_id, text, None)
    except RetryError as exc:  # pragma: no cover - reraise=True re-raises the cause instead
        attempt_exc = exc.last_attempt.exception() if exc.last_attempt else None
        return attempts, _failure_of(attempt_exc)
    except Exception as exc:  # noqa: BLE001 - classified and journaled, never raised
        return attempts, _failure_of(exc)
    return attempts, None


class AlertTextBot(Protocol):
    """The one bot method the sender may call: no edit, no keyboard, nothing else."""

    async def send_message(
        self, *, chat_id: str | int, text: str, reply_markup: None = None
    ) -> object: ...


@dataclass(frozen=True)
class SendReport:
    """What one `drain` did: counts only."""

    delivered: int
    failed: int
    audit_lost: int


class TelegramAlertSender:
    """Send the queued alerts through the bot, one bounded attempt series each.

    `drain` never raises for a send failure (it is journaled `ALERT_SEND_FAILED`, class name
    only) and never raises for a lost outcome row (counted in `audit_lost`; a restart
    re-queues an alert without an `ALERT_DELIVERED` row, so the message is at-least-once).
    """

    def __init__(
        self,
        *,
        bot: AlertTextBot,
        chat_id: int | str,
        journal: Any,
        spill: LocalSpill | None,
        sleep: Callable[[float], Awaitable[None]],
        queue: deque[OperationalAlert],
    ) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._journal = journal
        self._spill = spill
        self._sleep = sleep
        self._queue = queue

    async def drain(self) -> SendReport:
        delivered = failed = audit_lost = 0
        while self._queue:
            alert = self._queue.popleft()
            try:
                attempts, failure = await _send_bounded(
                    self._bot, self._chat_id, render_alert_text(alert), self._sleep
                )
            except BaseException:
                self._queue.appendleft(alert)  # cancelled mid-send: nothing is lost
                raise
            if failure is None:
                delivered += 1
                outcome = _outcome_event(
                    prefix="alertdlv",
                    event_type=EVENT_ALERT_DELIVERED,
                    entity_id=alert.alert_id,
                    occurred_at_utc=alert.occurred_at_utc,
                    payload={"attempts": attempts},
                )
            else:
                failed += 1
                outcome = _outcome_event(
                    prefix="alertfail",
                    event_type=EVENT_ALERT_SEND_FAILED,
                    entity_id=alert.alert_id,
                    occurred_at_utc=alert.occurred_at_utc,
                    payload={
                        "attempts": attempts,
                        "kind": failure.kind.value,
                        "retry_after_seconds": failure.retry_after_seconds,
                        "error_class": failure.detail,
                    },
                )
            try:
                record_after(spill=self._spill, journal=self._journal, event=outcome)
            except AuditRecordLost:
                audit_lost += 1
        return SendReport(delivered=delivered, failed=failed, audit_lost=audit_lost)


__all__ = [
    "ALERT_CORRELATION_ID",
    "ALERT_EVENTS",
    "EVENT_ALERT_DELIVERED",
    "EVENT_ALERT_SEND_FAILED",
    "EVENT_ALERT_SUPPRESSED",
    "EVENT_OPERATIONAL_ALERT",
    "INVALID_REASON",
    "AlertSeverity",
    "AlertTextBot",
    "JournalFirstAlertSink",
    "OperationalAlert",
    "SendReport",
    "TelegramAlertSender",
    "render_alert_text",
]
