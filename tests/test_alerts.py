"""Operational alerts (Phase 20, plan 20-13; D-22, D-23, T-G, OPS-05).

Evidence label: executed tests with a fake bot. No Telegram call is made and nothing here is
`[DEMO]`. Telegram rate-limit behaviour is [ASSUMED] (research A3).

Task 1 (tracer): a critical alert is journaled first, then delivered.
"""

from __future__ import annotations

import json
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol

import pytest

from src.execution.protection import CriticalAlertSink
from src.ops.alerts import (
    ALERT_EVENTS,
    AlertSeverity,
    JournalFirstAlertSink,
    OperationalAlert,
    TelegramAlertSender,
    render_alert_text,
)
from tests.support.ast_guards import forbidden_imports, module_imports, wall_clock_calls
from tests.support.execution_limits import test_only_execution_limits
from tests.support.reconcile_doubles import RecordingJournal

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
            limits=test_only_execution_limits(),
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
    }
    assert all(isinstance(s, AlertSeverity) for s in ALERT_EVENTS.values())
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
