"""Operational alerts: a journal-first sink and a Telegram sender with a bounded message retry.

Phase 20, plan 20-13 (D-22, D-23, T-G, OPS-05). This replaces the rehearsal-only alert sink
with the real infrastructure; plan 20-22 wires the producers and publishes `OPS05_MATRIX`.

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
- `emit_daily_state_alert` stays a TEST TRIGGER for the daily states: no production module
  calls it. The Phase 21 producer is `src/execution/daily_stop.py` (`enforce_daily_state`),
  which calls the sink directly after it cancelled the resting entries (D-13).

`OPS05_MATRIX` states, per OPS-05 alert, the producer and what Phase 20 delivers.
OPS-05 is NOT complete end-to-end: DAILY_STOP and DAILY_LOSS_WARNING have a producer since
Phase 21, but no producer is wired in a running process until Phase 24, and a test trigger is
not end-to-end coverage (D-23).

The module reads no clock: every time comes from the caller.
"""

from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
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
from src.domain.enums import DailyState
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
        # Plan 20-22 (D-24): the catch-all for a SAFE_MODE entry with no event of its own.
        "SAFE_MODE_ENTERED": AlertSeverity.HIGH,
        # Plan 20-28 (owner request 2026-10-23): a resting entry still NEW past goodTillDate plus
        # the owner grace. Alert only: no SAFE_MODE, no cancel.
        "STALE_ENTRY_ORDER": AlertSeverity.HIGH,
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


@dataclass(frozen=True)
class RequeueReport:
    """What `requeue_undelivered` did: alert ids queued, and ids of rows it could not read."""

    requeued: tuple[str, ...]
    invalid: tuple[str, ...]


def _alert_of_row(row: JournalEvent) -> OperationalAlert:
    """Rebuild an alert from its journal row; any malformed field raises."""
    payload = json.loads(row.payload_json)
    if not isinstance(payload, dict):
        raise TypeError("alert payload is not an object")
    return OperationalAlert(
        event=payload["event"],
        severity=AlertSeverity(payload["severity"]),
        subject=payload["subject"],
        reason=payload["reason"],
        occurred_at_utc=row.occurred_at_utc,
        plan_hash=payload.get("plan_hash"),
        symbol=payload.get("symbol"),
        alert_id=row.entity_id,
    )


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

    def requeue_undelivered(self, journal_rows: Iterable[JournalEvent]) -> RequeueReport:
        """Queue again every journaled alert that has no `ALERT_DELIVERED` row (restart).

        The caller reads the rows (correlation `operational_alerts`; the read itself belongs to
        the composition, Phase 24). Rows of another correlation are ignored; a row that cannot
        be rebuilt is reported in `invalid` and never queued. An alert already in the queue is
        not queued twice. The dedupe episodes are rebuilt from the same rows, so a repeat of a
        journaled alert inside its window stays suppressed after the restart. The delivery is
        at least once: an alert whose `ALERT_DELIVERED` row was lost is sent again.
        """
        rows = sorted(
            (r for r in journal_rows if r.correlation_id == ALERT_CORRELATION_ID),
            key=lambda r: (r.occurred_at_utc, r.journal_event_id),
        )
        delivered = {r.entity_id for r in rows if r.event_type == EVENT_ALERT_DELIVERED}
        queued_ids = {a.alert_id for a in self.queue}
        requeued: list[str] = []
        invalid: list[str] = []
        episodes_by_id: dict[str, _Episode] = {}
        for row in rows:
            if row.event_type != EVENT_OPERATIONAL_ALERT:
                continue
            try:
                alert = _alert_of_row(row)
            except (ValueError, KeyError, TypeError):
                invalid.append(row.journal_event_id)
                continue
            key = (alert.event, alert.subject, alert.reason)
            known = self._episodes.get(key)
            if known is None or known.started_at_utc < alert.occurred_at_utc:
                known = _Episode(alert.alert_id, alert.occurred_at_utc, 0)
                self._episodes[key] = known
            episodes_by_id[known.alert_id] = known
            if alert.alert_id not in delivered and alert.alert_id not in queued_ids:
                self.queue.append(alert)
                queued_ids.add(alert.alert_id)
                requeued.append(alert.alert_id)
        for row in rows:
            if row.event_type != EVENT_ALERT_SUPPRESSED:
                continue
            episode = episodes_by_id.get(row.entity_id)
            if episode is None:
                continue
            try:
                count = int(json.loads(row.payload_json)["count"])
            except (ValueError, KeyError, TypeError):
                continue
            episode.suppressed = max(episode.suppressed, count)
        return RequeueReport(requeued=tuple(requeued), invalid=tuple(invalid))


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
    """Transient faults only: programming errors and refusals fail at once.

    WR-C5: tenacity's attempt manager stores any ``BaseException``, so a cancellation would be
    retried (and could be swallowed by a later success). Only an ``Exception`` is retryable; a
    ``CancelledError``, ``KeyboardInterrupt`` or ``SystemExit`` is re-raised at once.
    """
    if not isinstance(exc, Exception):
        return False
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


# --------------------------------------------------------------------------- #
# SAFE_MODE entries (plan 20-22, D-23, D-24).
# --------------------------------------------------------------------------- #

# SAFE_MODE reasons that the entry path alerts under an event of the same name.
_ENTRY_PATH_EVENTS = frozenset({"ENTRY_STATE_UNKNOWN", "PROTECTION_HANDOFF_FAILED", "DB_FAILURE"})

# SAFE_MODE reasons whose own producer already alerts (the coordinator, the closer, the reconcile
# tick), so the observer stays silent for them and an operator never gets the same event twice.
# `src.reconcile` may not be imported here: a parity test pins the divergence reasons against
# `src.reconcile.classify.POLICY_BY_KIND`.
DEDICATED_PRODUCER_REASONS: frozenset[str] = frozenset(
    {
        "CLOSE_REQUIRED",
        "EMERGENCY_CLOSE_FAILED",
        "ENTRY_WITHOUT_PROTECTIVE",
        "ORPHAN_PROTECTIVE",
        "POSITION_WITHOUT_STOP",
        "TP_ONLY_POSITION",
        "SIGN_FLIPPED_POSITION",
        "DOUBLED_POSITION",
        "FOREIGN_ORDER",
        "UNTRACKED_SYSTEM_ORDER",
        "UNSYNCED_NORMAL",
        "UNSYNCED_ALGO",
        "UNSYNCED_POSITION",
        "DUPLICATE_EXCHANGE_ID",
        "UNSUPPORTED_POSITION_SIDE",
        "STREAM_SINK_FAILURE",
        "SYMBOL_OWNERSHIP_CONFLICT",
        "USER_DATA_STREAM_HALTED",
        "STALE_FEED",
        "AUTH_FAILURE",
        "API_DEGRADATION",
    }
)

SAFE_MODE_ALERT_SUBJECT = "SYSTEM"


class SafeModeAlertObserver:
    """The `on_enter` callable of `SafeModeController`: SAFE_MODE entries become alerts.

    ENTRY_STATE_UNKNOWN, PROTECTION_HANDOFF_FAILED and DB_FAILURE alert under their own event;
    a reason in `DEDICATED_PRODUCER_REASONS` alerts nothing here; every other reason alerts
    `SAFE_MODE_ENTERED`, so no SAFE_MODE entry is silent. The subject is `SYSTEM` (the controller
    knows no plan), the reason is the SAFE_MODE reason code, and the repeats of one reason go
    through the sink's dedupe window. A reason that is not a code is replaced by the sink.
    The controller swallows an exception from this callable.
    """

    def __init__(self, sink: _AlertEmitter) -> None:
        self._sink = sink

    def __call__(self, reason: str, now_utc: datetime) -> None:
        if reason in DEDICATED_PRODUCER_REASONS:
            return
        event = reason if reason in _ENTRY_PATH_EVENTS else "SAFE_MODE_ENTERED"
        self._sink.alert(
            event=event, subject=SAFE_MODE_ALERT_SUBJECT, reason=reason, now_utc=now_utc
        )


# --------------------------------------------------------------------------- #
# The OPS-05 acceptance matrix (plan 20-22, T-G, D-23, D-24).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Ops05Row:
    """One alert of OPS-05: its event, where it comes from and what Phase 20 delivers.

    `alert` is the event name in `ALERT_EVENTS` (the event contract: name, severity and fixed
    template). `requirement_source` says where the alert is required (`OPS-05` or a Phase 20
    decision). `producer` is the module that raises it (a producer exists for every row since
    Phase 21; none is wired in a running process before Phase 24); `phase20_delivers` is the
    honest scope. `journal_first` and `dedupe_and_retry` describe
    the shared sink: the alert is journaled before it is queued, a repeat inside the dedupe
    window is suppressed, and only the MESSAGE is retried (an order never is, Q5).
    """

    alert: str
    requirement_source: str
    phase20_delivers: str
    producer: str
    journal_first: bool
    dedupe_and_retry: str


_SINK_BEHAVIOR = "dedupe window + bounded message retry; orders never retried"
_SOURCE_OPS05 = "OPS-05"
_SOURCE_D24 = "D-24 (entry path)"
_SOURCE_STALE_ENTRY = "owner request 2026-10-23 (stale entry)"
_PRODUCER_DAILY_STOP = "src/execution/daily_stop.py"
_DAILY_PRODUCER_TEXT = (
    "Phase 21 producer (enforce_daily_state): cancels the resting entries through "
    "expire_pending_entry('daily_stop') before it alerts; not wired in a running process "
    "until Phase 24"
)

OPS05_MATRIX: tuple[Ops05Row, ...] = (
    Ops05Row(
        "ENTRY_STATE_UNKNOWN",
        _SOURCE_D24,
        "SAFE_MODE entry of the entry path alerts through the on_enter observer",
        "src/execution/manager.py",
        True,
        _SINK_BEHAVIOR,
    ),
    Ops05Row(
        "PROTECTION_HANDOFF_FAILED",
        _SOURCE_D24,
        "SAFE_MODE entry of the entry path alerts through the on_enter observer",
        "src/execution/manager.py",
        True,
        _SINK_BEHAVIOR,
    ),
    Ops05Row(
        "DB_FAILURE",
        _SOURCE_D24,
        "SAFE_MODE entry after a store failure alerts through the on_enter observer; since "
        "Phase 21 src/execution/daily_stop.py also alerts it with the reasons DAY_STATE_MISSING "
        "and DAY_STATE_UNREADABLE (a missing or unreadable persisted day state, nothing is "
        "cancelled)",
        "src/execution/manager.py",
        True,
        _SINK_BEHAVIOR,
    ),
    Ops05Row(
        "PROTECTIVE_REJECTED",
        _SOURCE_OPS05,
        "definitive stop rejection after a fill (B5) alerts with CLOSE_REQUIRED",
        "src/execution/protection.py",
        True,
        _SINK_BEHAVIOR,
    ),
    Ops05Row(
        "UNPROTECTED_POSITION",
        _SOURCE_OPS05,
        "reconcile tick alerts a position without stop, a TP-only position, an entry without "
        "protective",
        "src/reconcile/classify.py",
        True,
        _SINK_BEHAVIOR,
    ),
    Ops05Row(
        "CLOSE_REQUIRED",
        _SOURCE_OPS05,
        "the protection coordinator alerts once per plan when the position must be closed",
        "src/execution/protection.py",
        True,
        _SINK_BEHAVIOR,
    ),
    Ops05Row(
        "DIVERGENCE",
        _SOURCE_OPS05,
        "reconcile tick alerts a local versus exchange divergence",
        "src/reconcile/classify.py",
        True,
        _SINK_BEHAVIOR,
    ),
    Ops05Row(
        "UNKNOWN_ORDER",
        _SOURCE_OPS05,
        "reconcile tick alerts an untracked system order",
        "src/reconcile/classify.py",
        True,
        _SINK_BEHAVIOR,
    ),
    Ops05Row(
        "FOREIGN_ORDER",
        _SOURCE_OPS05,
        "reconcile tick alerts a foreign order",
        "src/reconcile/classify.py",
        True,
        _SINK_BEHAVIOR,
    ),
    Ops05Row(
        "STALE_DATA",
        _SOURCE_OPS05,
        "reconcile tick alerts a stale mark price, a silent user-data stream or a halted stream",
        "src/reconcile/loop.py",
        True,
        _SINK_BEHAVIOR,
    ),
    Ops05Row(
        "AUTH_FAILURE",
        _SOURCE_OPS05,
        "produced only by the reconcile tick REST reads (plan 20-16); the coordinator, the "
        "closer and the manager journal the error class and do not alert it in Phase 20",
        "src/reconcile/loop.py",
        True,
        _SINK_BEHAVIOR,
    ),
    Ops05Row(
        "DUPLICATE_EXECUTION_ATTEMPT",
        _SOURCE_OPS05,
        "an already consumed approval (stored outcome or lost consume race) alerts through the "
        "optional LivePlacementContext.alert_sink; nothing is re-sent",
        "src/execution/manager.py",
        True,
        _SINK_BEHAVIOR,
    ),
    Ops05Row(
        "STALE_ENTRY_ORDER",
        _SOURCE_STALE_ENTRY,
        "reconcile tick alerts a resting entry that is still NEW more than the owner grace "
        "(reconcile.entry_stale_grace_ms, NOT_CONFIGURED: the check is skipped and says so) past "
        "its goodTillDate; alert only, nothing is cancelled and SAFE_MODE is not entered",
        "src/reconcile/loop.py",
        True,
        _SINK_BEHAVIOR,
    ),
    Ops05Row(
        "DAILY_STOP",
        _SOURCE_OPS05,
        _DAILY_PRODUCER_TEXT,
        _PRODUCER_DAILY_STOP,
        True,
        _SINK_BEHAVIOR,
    ),
    Ops05Row(
        "DAILY_LOSS_WARNING",
        _SOURCE_OPS05,
        _DAILY_PRODUCER_TEXT,
        _PRODUCER_DAILY_STOP,
        True,
        _SINK_BEHAVIOR,
    ),
)


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


_DAILY_STATE_EVENTS = MappingProxyType(
    {
        DailyState.DAILY_STOP: "DAILY_STOP",
        DailyState.WARNING: "DAILY_LOSS_WARNING",
    }
)


def emit_daily_state_alert(
    sink: _AlertEmitter, *, state: DailyState, subject: str, now_utc: datetime
) -> None:
    """TEST TRIGGER for the daily states. It has no production caller.

    DAILY_STOP emits `DAILY_STOP` (CRITICAL) and WARNING emits `DAILY_LOSS_WARNING` (WARNING).
    The production producer is `src/execution/daily_stop.py` (`enforce_daily_state`, Phase 21),
    which calls the sink directly; this function stays the contract plus a way for a test to
    push the alert through the sink. A test that calls it is NOT evidence of end-to-end
    coverage (D-23, OPS-05 scope split), and `tests/test_alerts.py` scans `src` to prove no
    module other than this one uses it.

    Raises:
        ValueError: `state` is not DAILY_STOP or WARNING.
    """
    event = _DAILY_STATE_EVENTS.get(state)
    if event is None:
        raise ValueError("state must be DailyState.DAILY_STOP or DailyState.WARNING")
    sink.alert(event=event, subject=subject, reason=state.value, now_utc=now_utc)


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
    "DEDICATED_PRODUCER_REASONS",
    "JournalFirstAlertSink",
    "OPS05_MATRIX",
    "RequeueReport",
    "OperationalAlert",
    "Ops05Row",
    "SafeModeAlertObserver",
    "SendReport",
    "TelegramAlertSender",
    "emit_daily_state_alert",
    "render_alert_text",
]
