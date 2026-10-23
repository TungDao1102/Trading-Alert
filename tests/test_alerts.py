"""Operational alerts (Phase 20, plan 20-13; D-22, D-23, T-G, OPS-05).

Evidence label: executed tests with a fake bot. No Telegram call is made and nothing here is
`[DEMO]`. Telegram rate-limit behaviour is [ASSUMED] (research A3).

Task 1 (tracer): a critical alert is journaled first, then delivered.
Task 2: bounded retry, send failure, dedupe, the no-secret rule, journal outage.
Task 3: restart re-queue and the daily-state test trigger.
"""

from __future__ import annotations

import ast
import json
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol

import pytest
from src.domain.enums import DailyState
from src.domain.journal import JournalEvent
from src.execution.execution_limits import ExecutionLimitsNotConfigured
from src.execution.protection import CriticalAlertSink
from src.ops import alerts as alerts_module
from src.ops.alerts import (
    ALERT_EVENTS,
    INVALID_REASON,
    AlertSeverity,
    JournalFirstAlertSink,
    OperationalAlert,
    TelegramAlertSender,
    render_alert_text,
)
from src.ops.risk_first import AuditRecordLost
from src.ops.spill import LocalSpill
from src.paper.notify import NOTIFY_MAX_ATTEMPTS
from telegram import error as tg_error

from tests.support.ast_guards import forbidden_imports, module_imports, wall_clock_calls
from tests.support.execution_limits import test_only_execution_limits as make_test_limits
from tests.support.reconcile_doubles import RaisingJournal, RecordingJournal

NOW = datetime(2026, 9, 19, 0, 0, 0, tzinfo=UTC)
PLAN_HASH = "a" * 64
ALERTS_SOURCE = Path(__file__).resolve().parents[1] / "src" / "ops" / "alerts.py"
CHAT_ID = 4242


class TraceJournal(RecordingJournal):
    """A recording journal that appends `journal:<event_type>` to a shared trace."""

    def __init__(self, trace: list[str]) -> None:
        super().__init__()
        self.trace = trace

    def record(self, event: Any) -> None:
        super().record(event)
        self.trace.append(f"journal:{event.event_type}")


class FakeAlertBot:
    """Only `send_message` exists: any other method call is an AttributeError.

    It raises the queued exceptions in order (real `telegram.error` classes), then succeeds.
    """

    def __init__(self, trace: list[str] | None = None) -> None:
        self.trace: list[str] = trace if trace is not None else []
        self.sent: list[SimpleNamespace] = []
        self.attempts = 0
        self.errors: list[BaseException] = []

    async def send_message(self, *, chat_id: int | str, text: str, reply_markup: Any = None) -> Any:
        self.attempts += 1
        self.trace.append("send")
        if self.errors:
            raise self.errors.pop(0)
        sent = SimpleNamespace(chat_id=chat_id, text=text, reply_markup=reply_markup)
        self.sent.append(sent)
        return SimpleNamespace(message_id=len(self.sent))


class RecordingSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class Harness:
    """A sink and a sender sharing one queue, one journal and one trace."""

    def __init__(self) -> None:
        self.trace: list[str] = []
        self.journal = TraceJournal(self.trace)
        self.bot = FakeAlertBot(self.trace)
        self.sleep = RecordingSleep()
        self.queue: deque[OperationalAlert] = deque()
        self.sink = JournalFirstAlertSink(
            journal=self.journal,
            spill=None,
            limits=make_test_limits(),
            queue=self.queue,
        )
        self.sender = TelegramAlertSender(
            bot=self.bot,
            chat_id=CHAT_ID,
            journal=self.journal,
            spill=None,
            sleep=self.sleep,
            queue=self.queue,
        )

    def rows(self, event_type: str) -> list[Any]:
        return [e for e in self.journal.events if e.event_type == event_type]


def _close_required(sink: JournalFirstAlertSink, *, now: datetime = NOW) -> None:
    sink.critical(
        event="CLOSE_REQUIRED",
        plan_hash=PLAN_HASH,
        symbol="BTCUSDT",
        reason="B2_STOP_UNCONFIRMED",
        now_utc=now,
    )


# --------------------------------------------------------------------------- #
# Task 1: the tracer.
# --------------------------------------------------------------------------- #


async def test_close_required_is_journaled_before_it_is_sent() -> None:
    h = Harness()

    _close_required(h.sink)

    assert h.trace == ["journal:OPERATIONAL_ALERT"]  # journaled, nothing sent yet
    assert h.bot.attempts == 0

    report = await h.sender.drain()

    assert h.trace == ["journal:OPERATIONAL_ALERT", "send", "journal:ALERT_DELIVERED"]
    assert h.bot.attempts == 1
    text = h.bot.sent[0].text
    assert "CLOSE_REQUIRED" in text
    assert "BTCUSDT" in text
    assert "B2_STOP_UNCONFIRMED" in text
    assert h.bot.sent[0].chat_id == CHAT_ID
    assert h.bot.sent[0].reply_markup is None
    assert (report.delivered, report.failed) == (1, 0)
    delivered = h.rows("ALERT_DELIVERED")[0]
    assert delivered.entity_id == h.rows("OPERATIONAL_ALERT")[0].entity_id


async def test_the_journaled_alert_row_carries_the_contract_fields() -> None:
    h = Harness()
    _close_required(h.sink)

    row = h.rows("OPERATIONAL_ALERT")[0]
    payload = json.loads(row.payload_json)

    assert row.journal_event_id == row.entity_id
    assert row.entity_type == "OperationalAlert"
    assert row.correlation_id == "operational_alerts"
    assert row.occurred_at_utc == NOW
    assert payload == {
        "event": "CLOSE_REQUIRED",
        "plan_hash": PLAN_HASH,
        "reason": "B2_STOP_UNCONFIRMED",
        "severity": "CRITICAL",
        "subject": "BTCUSDT",
        "symbol": "BTCUSDT",
    }


def test_sink_satisfies_the_critical_alert_sink_and_the_reconcile_alert_sink_shapes() -> None:
    class ReconcileAlertSink(Protocol):
        """The shape plan 20-12 fixes for the loop (not imported: it may not exist yet)."""

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

    h = Harness()
    as_critical: CriticalAlertSink = h.sink  # checked by mypy
    as_reconcile: ReconcileAlertSink = h.sink  # checked by mypy

    as_critical.critical(
        event="UNPROTECTED_POSITION",
        plan_hash=PLAN_HASH,
        symbol="ETHUSDT",
        reason="STOP_LOST",
        now_utc=NOW,
    )
    as_reconcile.alert(
        event="DIVERGENCE", subject="SYSTEM", reason="POSITION_MISMATCH", now_utc=NOW
    )

    assert [r.event_type for r in h.journal.events] == ["OPERATIONAL_ALERT"] * 2
    assert len(h.queue) == 2


def test_the_alert_id_is_deterministic_for_the_same_event_subject_reason_and_time() -> None:
    first = OperationalAlert.create(
        event="CLOSE_REQUIRED", subject="BTCUSDT", reason="B2_STOP_UNCONFIRMED", occurred_at_utc=NOW
    )
    again = OperationalAlert.create(
        event="CLOSE_REQUIRED",
        subject="BTCUSDT",
        reason="B2_STOP_UNCONFIRMED",
        occurred_at_utc=NOW,
        plan_hash=PLAN_HASH,  # not part of the id
    )
    other_reason = OperationalAlert.create(
        event="CLOSE_REQUIRED", subject="BTCUSDT", reason="B3_STOP_ABSENT", occurred_at_utc=NOW
    )

    assert first.alert_id == again.alert_id
    assert first.alert_id != other_reason.alert_id
    assert len(first.alert_id) <= 128


def test_the_event_contract_is_closed_and_maps_every_event_to_a_severity() -> None:
    assert set(ALERT_EVENTS) == {
        "UNPROTECTED_POSITION",
        "CLOSE_REQUIRED",
        "TP_UNAVAILABLE",
        "EMERGENCY_CLOSE_FAILED",
        "EMERGENCY_CLOSE_NOT_SENT",
        "PROTECTIVE_REJECTED",
        "DIVERGENCE",
        "FOREIGN_ORDER",
        "UNKNOWN_ORDER",
        "STALE_DATA",
        "AUTH_FAILURE",
        "DUPLICATE_EXECUTION_ATTEMPT",
        "ENTRY_STATE_UNKNOWN",
        "PROTECTION_HANDOFF_FAILED",
        "DB_FAILURE",
        "MANUAL_CLOSE_ORPHAN_UNVERIFIED",
        "DAILY_STOP",
        "DAILY_LOSS_WARNING",
        "SAFE_MODE_ENTERED",
        "STALE_ENTRY_ORDER",
    }
    assert all(isinstance(s, AlertSeverity) for s in ALERT_EVENTS.values())
    assert ALERT_EVENTS["STALE_ENTRY_ORDER"] is AlertSeverity.HIGH
    assert ALERT_EVENTS["DAILY_STOP"] is AlertSeverity.CRITICAL
    assert ALERT_EVENTS["DAILY_LOSS_WARNING"] is AlertSeverity.WARNING


def test_an_unknown_event_raises_value_error_and_journals_nothing() -> None:
    h = Harness()

    with pytest.raises(ValueError, match="event"):
        h.sink.alert(event="SOMETHING_ELSE", subject="SYSTEM", reason="X_Y", now_utc=NOW)

    assert h.journal.events == []
    assert len(h.queue) == 0


def test_a_naive_time_is_refused() -> None:
    h = Harness()

    with pytest.raises(ValueError, match="UTC"):
        h.sink.alert(
            event="DIVERGENCE", subject="SYSTEM", reason="X_Y", now_utc=datetime(2026, 1, 1)
        )


def test_alert_text_is_a_fixed_template() -> None:
    alert = OperationalAlert.create(
        event="CLOSE_REQUIRED",
        subject="BTCUSDT",
        reason="B2_STOP_UNCONFIRMED",
        occurred_at_utc=NOW,
        plan_hash=PLAN_HASH,
        symbol="BTCUSDT",
    )

    text = render_alert_text(alert)

    assert text == (
        "[CRITICAL] CLOSE_REQUIRED\n"
        "subject: BTCUSDT\n"
        "reason: B2_STOP_UNCONFIRMED\n"
        "at: 2026-09-19T00:00:00Z"
    )
    assert PLAN_HASH not in text  # the plan hash stays in the journal, not in the message


def test_the_alerts_module_reads_no_wall_clock_and_imports_no_placement_path() -> None:
    assert wall_clock_calls(ALERTS_SOURCE) == []
    assert (
        forbidden_imports(
            ALERTS_SOURCE,
            (
                "src.execution.manager",
                "src.execution.protection",
                "src.execution.emergency_close",
                "src.execution.live_context",
                "src.execution.intent_store",
                "src.execution.enablement",
                "src.adapters.binance*",
                "src.reconcile",
            ),
        )
        == []
    )
    imports = module_imports(ALERTS_SOURCE)
    assert [m for m in imports if m.startswith("src.execution")] == [
        "src.execution.execution_limits"
    ]
    assert [m for m in imports if m.startswith("src.adapters")] == ["src.adapters.telegram_notify"]


async def test_the_sender_only_ever_calls_send_message() -> None:
    h = Harness()
    _close_required(h.sink)
    await h.sender.drain()

    public = sorted(n for n in vars(type(h.bot)) if not n.startswith("_"))
    assert public == ["send_message"]
    assert h.bot.attempts == 1


# --------------------------------------------------------------------------- #
# Task 2: bounded retry, send failure, dedupe, no secret material.
# --------------------------------------------------------------------------- #


async def test_a_rate_limited_send_is_retried_honouring_retry_after_then_delivered() -> None:
    h = Harness()
    h.bot.errors = [tg_error.RetryAfter(2), tg_error.RetryAfter(3)]
    _close_required(h.sink)

    report = await h.sender.drain()

    assert h.bot.attempts == 3
    assert len(h.sleep.calls) == 2
    assert h.sleep.calls[0] >= 2
    assert h.sleep.calls[1] >= 3
    assert (report.delivered, report.failed) == (1, 0)
    assert len(h.rows("ALERT_DELIVERED")) == 1
    assert json.loads(h.rows("ALERT_DELIVERED")[0].payload_json) == {"attempts": 3}
    assert h.rows("ALERT_SEND_FAILED") == []


async def test_a_rejected_send_is_tried_once_and_journaled_with_the_class_name_only() -> None:
    h = Harness()
    h.bot.errors = [tg_error.BadRequest("chat not found token=abc123")]
    _close_required(h.sink)

    report = await h.sender.drain()

    assert h.bot.attempts == 1
    assert h.sleep.calls == []
    assert (report.delivered, report.failed) == (0, 1)
    failed = h.rows("ALERT_SEND_FAILED")
    assert len(failed) == 1
    assert json.loads(failed[0].payload_json) == {
        "attempts": 1,
        "error_class": "BadRequest",
        "kind": "REJECTED",
        "retry_after_seconds": None,
    }
    assert "abc123" not in failed[0].payload_json
    assert h.rows("ALERT_DELIVERED") == []


async def test_transient_errors_stop_at_the_attempt_budget_and_drain_returns_normally() -> None:
    h = Harness()
    h.bot.errors = [tg_error.NetworkError("down") for _ in range(NOTIFY_MAX_ATTEMPTS + 2)]
    _close_required(h.sink)

    report = await h.sender.drain()

    assert h.bot.attempts == NOTIFY_MAX_ATTEMPTS
    assert (report.delivered, report.failed) == (0, 1)
    failed = h.rows("ALERT_SEND_FAILED")
    assert json.loads(failed[0].payload_json)["attempts"] == NOTIFY_MAX_ATTEMPTS
    assert json.loads(failed[0].payload_json)["error_class"] == "NetworkError"
    assert len(h.queue) == 0


def _emergency_close_failed(sink: JournalFirstAlertSink, *, at: datetime) -> None:
    sink.alert(
        event="EMERGENCY_CLOSE_FAILED",
        subject="BTCUSDT",
        reason="CLOSE_FAILED",
        now_utc=at,
        plan_hash=PLAN_HASH,
        symbol="BTCUSDT",
    )


async def test_repeats_inside_the_dedupe_window_are_suppressed_and_counted() -> None:
    h = Harness()  # TEST_ONLY alerts.dedupe_window_ms = 6543
    _emergency_close_failed(h.sink, at=NOW)
    _emergency_close_failed(h.sink, at=NOW + timedelta(milliseconds=1000))
    _emergency_close_failed(h.sink, at=NOW + timedelta(milliseconds=2000))

    report = await h.sender.drain()

    assert len(h.rows("OPERATIONAL_ALERT")) == 1
    assert h.bot.attempts == 1
    assert report.delivered == 1
    suppressed = h.rows("ALERT_SUPPRESSED")
    counts = [json.loads(r.payload_json)["count"] for r in suppressed]
    assert counts == [1, 2]
    assert {r.entity_id for r in suppressed} == {h.rows("OPERATIONAL_ALERT")[0].entity_id}

    # A fourth one after the window (measured from the first alert) is a new alert.
    _emergency_close_failed(h.sink, at=NOW + timedelta(milliseconds=6543))
    await h.sender.drain()

    assert len(h.rows("OPERATIONAL_ALERT")) == 2
    assert h.bot.attempts == 2


def test_the_window_edge_is_exclusive() -> None:
    h = Harness()
    _emergency_close_failed(h.sink, at=NOW)
    _emergency_close_failed(h.sink, at=NOW + timedelta(milliseconds=6542))
    assert len(h.rows("OPERATIONAL_ALERT")) == 1
    _emergency_close_failed(h.sink, at=NOW + timedelta(milliseconds=6543))
    assert len(h.rows("OPERATIONAL_ALERT")) == 2


def test_another_reason_or_subject_is_not_suppressed() -> None:
    h = Harness()
    _emergency_close_failed(h.sink, at=NOW)
    h.sink.alert(
        event="EMERGENCY_CLOSE_FAILED", subject="BTCUSDT", reason="OTHER_CODE", now_utc=NOW
    )
    h.sink.alert(
        event="EMERGENCY_CLOSE_FAILED", subject="ETHUSDT", reason="CLOSE_FAILED", now_utc=NOW
    )

    assert len(h.rows("OPERATIONAL_ALERT")) == 3
    assert h.rows("ALERT_SUPPRESSED") == []


def test_an_unset_dedupe_window_refuses_construction_and_names_the_key() -> None:
    journal = RecordingJournal()

    with pytest.raises(ExecutionLimitsNotConfigured) as caught:
        JournalFirstAlertSink(
            journal=journal,
            spill=None,
            limits=make_test_limits(alerts_dedupe_window_ms=None),
        )

    assert caught.value.keys == ("alerts.dedupe_window_ms",)
    assert journal.events == []


class _LeakyError(Exception):
    pass


async def test_alert_text_never_contains_secret_material() -> None:
    secret_message = "token=abc123 postgresql://u:p@h/db 429 Too Many Requests: https://x/y"
    exc = _LeakyError(secret_message)
    h = Harness()

    # An exception MESSAGE used as a reason becomes INVALID_REASON.
    h.sink.alert(event="DB_FAILURE", subject="SYSTEM", reason=str(exc), now_utc=NOW)
    # A leading underscore is not a class-name shape either.
    h.sink.alert(
        event="DB_FAILURE",
        subject="SYSTEM",
        reason=type(exc).__name__,
        now_utc=NOW + timedelta(days=1),
    )
    # A poisoned subject, symbol and plan hash are replaced too.
    h.sink.alert(
        event="DIVERGENCE",
        subject="postgresql://u:p@h/db",
        reason="POSITION_MISMATCH",
        now_utc=NOW,
        plan_hash="token=abc123",
        symbol="x y",
    )
    await h.sender.drain()

    texts = [m.text for m in h.bot.sent]
    journaled = [e.payload_json for e in h.journal.events]
    assert len(texts) == 3
    for blob in (*texts, *journaled):
        assert "abc123" not in blob
        assert "postgresql" not in blob
        assert "u:p@h" not in blob
        assert "https://" not in blob
        assert "429" not in blob
    assert f"reason: {INVALID_REASON}" in texts[0]
    assert "_LeakyError" not in texts[1]
    assert "subject: INVALID_SUBJECT" in texts[2]
    assert json.loads(h.rows("OPERATIONAL_ALERT")[2].payload_json)["plan_hash"] == (
        "INVALID_PLAN_HASH"
    )


async def test_a_class_name_reason_is_kept() -> None:
    h = Harness()
    h.sink.alert(event="DB_FAILURE", subject="SYSTEM", reason="StoreUnavailable", now_utc=NOW)
    await h.sender.drain()

    assert "reason: StoreUnavailable" in h.bot.sent[0].text


def test_a_journal_outage_is_absorbed_by_the_spill_and_the_alert_is_still_queued(
    tmp_path: Path,
) -> None:
    spill = LocalSpill(tmp_path / "spill")
    sink = JournalFirstAlertSink(
        journal=RaisingJournal(), spill=spill, limits=make_test_limits(), queue=deque()
    )

    _close_required(sink)  # does not raise: the spill took the record

    assert len(sink.queue) == 1
    assert len(spill.pending()) == 1


def test_when_the_journal_and_the_spill_both_fail_the_alert_is_queued_and_the_loss_raised() -> None:
    sink = JournalFirstAlertSink(
        journal=RaisingJournal(), spill=None, limits=make_test_limits(), queue=deque()
    )

    with pytest.raises(AuditRecordLost):
        _close_required(sink)

    assert len(sink.queue) == 1  # the operator is still told


async def test_a_lost_outcome_row_is_counted_not_raised() -> None:
    h = Harness()
    _close_required(h.sink)
    sender = TelegramAlertSender(
        bot=h.bot,
        chat_id=CHAT_ID,
        journal=RaisingJournal(),
        spill=None,
        sleep=h.sleep,
        queue=h.queue,
    )

    report = await sender.drain()

    assert (report.delivered, report.failed, report.audit_lost) == (1, 0, 1)


# --------------------------------------------------------------------------- #
# Task 3: restart re-queue and the daily-state test trigger.
# --------------------------------------------------------------------------- #


def _alert_at(sink: JournalFirstAlertSink, *, subject: str, at: datetime) -> None:
    sink.alert(event="STALE_DATA", subject=subject, reason="MARK_PRICE_STALE", now_utc=at)


async def _journal_with_one_delivered_and_one_undelivered() -> tuple[list[Any], str, str]:
    """Rows of alert a1 (delivered) and a2 (never drained); returns (rows, a1 id, a2 id)."""
    h = Harness()
    _alert_at(h.sink, subject="BTCUSDT", at=NOW)
    await h.sender.drain()
    _alert_at(h.sink, subject="ETHUSDT", at=NOW + timedelta(seconds=1))
    first, second = (e.entity_id for e in h.rows("OPERATIONAL_ALERT"))
    assert [e.event_type for e in h.journal.events] == [
        "OPERATIONAL_ALERT",
        "ALERT_DELIVERED",
        "OPERATIONAL_ALERT",
    ]
    return list(h.journal.events), first, second


async def test_requeue_undelivered_queues_only_the_alert_without_a_delivered_row() -> None:
    rows, first, second = await _journal_with_one_delivered_and_one_undelivered()
    restarted = Harness()

    report = restarted.sink.requeue_undelivered(rows)
    await restarted.sender.drain()

    assert report.requeued == (second,)
    assert report.invalid == ()
    assert len(restarted.bot.sent) == 1
    assert "ETHUSDT" in restarted.bot.sent[0].text
    assert "BTCUSDT" not in restarted.bot.sent[0].text  # a1 was delivered, it is not re-sent
    assert first not in {a.alert_id for a in restarted.queue}


async def test_requeue_does_not_depend_on_the_order_of_the_rows() -> None:
    rows, _, second = await _journal_with_one_delivered_and_one_undelivered()
    restarted = Harness()

    report = restarted.sink.requeue_undelivered(list(reversed(rows)))

    assert report.requeued == (second,)


async def test_a_send_failed_alert_without_a_delivered_row_is_requeued() -> None:
    h = Harness()
    h.bot.errors = [tg_error.BadRequest("nope")]
    _close_required(h.sink)
    await h.sender.drain()
    assert len(h.rows("ALERT_SEND_FAILED")) == 1
    restarted = Harness()

    report = restarted.sink.requeue_undelivered(h.journal.events)
    await restarted.sender.drain()

    assert len(report.requeued) == 1
    assert len(restarted.bot.sent) == 1
    assert "CLOSE_REQUIRED" in restarted.bot.sent[0].text


async def test_requeue_twice_does_not_queue_an_alert_twice() -> None:
    rows, _, second = await _journal_with_one_delivered_and_one_undelivered()
    restarted = Harness()

    restarted.sink.requeue_undelivered(rows)
    again = restarted.sink.requeue_undelivered(rows)

    assert again.requeued == ()
    assert [a.alert_id for a in restarted.queue] == [second]


async def test_a_corrupt_alert_row_is_reported_and_the_others_are_still_queued() -> None:
    rows, _, second = await _journal_with_one_delivered_and_one_undelivered()
    broken = JournalEvent(
        journal_event_id="alert_broken",
        occurred_at_utc=NOW,
        event_type="OPERATIONAL_ALERT",
        entity_type="OperationalAlert",
        entity_id="alert_broken",
        correlation_id="operational_alerts",
        payload_json='{"event": "NOT_AN_EVENT"}',
    )
    restarted = Harness()

    report = restarted.sink.requeue_undelivered([broken, *rows])

    assert report.invalid == ("alert_broken",)
    assert report.requeued == (second,)


async def test_rows_of_other_correlations_and_event_types_are_ignored() -> None:
    rows, _, _ = await _journal_with_one_delivered_and_one_undelivered()
    foreign = JournalEvent(
        journal_event_id="x1",
        occurred_at_utc=NOW,
        event_type="OPERATIONAL_ALERT",
        entity_type="Other",
        entity_id="x1",
        correlation_id="some_other_stream",
        payload_json="{}",
    )
    restarted = Harness()

    report = restarted.sink.requeue_undelivered([foreign, *rows])

    assert report.invalid == ()
    assert len(report.requeued) == 1


async def test_after_a_restart_a_repeat_inside_the_window_is_still_suppressed() -> None:
    h = Harness()
    _alert_at(h.sink, subject="BTCUSDT", at=NOW)
    _alert_at(h.sink, subject="BTCUSDT", at=NOW + timedelta(milliseconds=500))  # suppressed, 1
    restarted = Harness()
    restarted.sink.requeue_undelivered(h.journal.events)
    restarted.queue.clear()

    _alert_at(restarted.sink, subject="BTCUSDT", at=NOW + timedelta(milliseconds=900))

    assert len(restarted.queue) == 0  # the same episode, not a new alert
    counts = [json.loads(r.payload_json)["count"] for r in restarted.rows("ALERT_SUPPRESSED")]
    assert counts == [2]  # the count continues from the journaled one


def test_daily_stop_test_trigger_emits_a_critical_daily_stop() -> None:
    h = Harness()

    alerts_module.emit_daily_state_alert(
        h.sink, state=DailyState.DAILY_STOP, subject="SYSTEM", now_utc=NOW
    )

    alert = h.queue[0]
    assert (alert.event, alert.severity, alert.subject) == (
        "DAILY_STOP",
        AlertSeverity.CRITICAL,
        "SYSTEM",
    )


def test_daily_loss_warning_test_trigger_emits_a_warning() -> None:
    h = Harness()

    alerts_module.emit_daily_state_alert(
        h.sink, state=DailyState.WARNING, subject="SYSTEM", now_utc=NOW
    )

    alert = h.queue[0]
    assert (alert.event, alert.severity) == ("DAILY_LOSS_WARNING", AlertSeverity.WARNING)


def test_the_daily_state_trigger_refuses_any_other_state() -> None:
    h = Harness()

    with pytest.raises(ValueError, match="state"):
        alerts_module.emit_daily_state_alert(
            h.sink, state=DailyState.NORMAL, subject="SYSTEM", now_utc=NOW
        )

    assert h.journal.events == []


def test_daily_state_trigger_has_no_production_caller() -> None:
    """`emit_daily_state_alert` is a TEST TRIGGER: no module under src may use it (Phase 21).

    This keeps the OPS-05 matrix of plan 20-22 truthful: DAILY_STOP and the daily-loss WARNING
    are "contract and test trigger only" until Phase 21 adds a real producer.
    """
    src_root = ALERTS_SOURCE.parents[1]
    offenders: list[str] = []
    for path in sorted(src_root.rglob("*.py")):
        if path == ALERTS_SOURCE:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            named = (
                (isinstance(node, ast.Name) and node.id == "emit_daily_state_alert")
                or (isinstance(node, ast.Attribute) and node.attr == "emit_daily_state_alert")
                or (
                    isinstance(node, ast.ImportFrom)
                    and any(a.name == "emit_daily_state_alert" for a in node.names)
                )
            )
            if named:
                offenders.append(f"{path.relative_to(src_root)}:{node.lineno}")  # type: ignore[attr-defined]
    assert offenders == []
