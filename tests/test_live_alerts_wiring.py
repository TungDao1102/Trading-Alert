"""The operator alert path of the live process (plan 24-13; D-07, T-05, W8 of 20-VERIFICATION).

Evidence label: executed tests with a fake Telegram bot and in-memory journals. No Telegram call is
made and nothing here is `[DEMO]`. The three T-05 alerts are produced by their PRODUCTION producers
(the manager through `LivePlacementContext.alert_sink`, the protection coordinator, the daily-state
enforcement), all holding the sink of the bundle `build_alerts` returned; no alert text is typed
here except the header lines the Phase 20 template defines.

Task 1 (tracer): a SAFE_MODE entry of the composed controller reaches the bot through the real
sink, sender and drain, journal first.
Task 2: the T-05 producers, the gate alert (and its `until_utc`) and the start re-queue.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from src.domain.enums import DailyState, RejectionReason
from src.domain.journal import content_hash_event_id
from src.execution.daily_stop import enforce_daily_state
from src.execution.execution_limits import ExecutionLimits, ExecutionLimitsNotConfigured
from src.live.alerts import (
    AlertBundle,
    AlertsAlreadyRequeued,
    build_alerts,
    drain_once,
    requeue_at_start,
)
from src.live.exchange import GateAlert, gate_alert_adapter
from src.live.execution_service import PlacementInputs
from src.ops.alerts import (
    ALERT_EVENTS,
    OperationalAlert,
    render_alert_text,
)
from src.reconcile.safe_mode import SafeModeController
from src.risk.daily_loss import DayStateVerdict
from telegram import error as tg_error

from tests.support.execution_limits import test_only_execution_limits as make_test_limits
from tests.support.live_rig import LiveRig, forbid_real_sleep, make_live_rig
from tests.support.reconcile_doubles import RecordingJournal

D = Decimal
ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "fixtures" / "phase23" / "alerts"
LIVE_ALERTS_SOURCE = ROOT / "src" / "live" / "alerts.py"
CHAT_ID = 4242
# The fixed time of the Phase 23 golden texts (scripts/gen_phase23_fixtures.py FIXED_AT_UTC).
GOLDEN_AT = datetime(2026, 10, 9, 3, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


class FakeBot:
    """Only `send_message` exists. It raises the queued errors in order, then succeeds."""

    def __init__(self, trace: list[str] | None = None) -> None:
        self.trace = trace if trace is not None else []
        self.sent: list[SimpleNamespace] = []
        self.errors: list[BaseException] = []

    async def send_message(self, *, chat_id: int | str, text: str, reply_markup: Any = None) -> Any:
        self.trace.append("send")
        if self.errors:
            raise self.errors.pop(0)
        self.sent.append(SimpleNamespace(chat_id=chat_id, text=text))
        return SimpleNamespace(message_id=len(self.sent))


class NoSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class TraceJournal(RecordingJournal):
    def __init__(self, trace: list[str]) -> None:
        super().__init__()
        self.trace = trace

    def record(self, event: Any) -> None:
        super().record(event)
        self.trace.append(f"journal:{event.event_type}")


@dataclasses.dataclass
class Parts:
    bundle: AlertBundle
    journal: RecordingJournal
    bot: FakeBot
    trace: list[str]


def _parts(
    *,
    clock: Callable[[], datetime] = lambda: GOLDEN_AT,
    limits: ExecutionLimits | None = None,
    journal: RecordingJournal | None = None,
) -> Parts:
    trace: list[str] = []
    the_journal = journal if journal is not None else TraceJournal(trace)
    bot = FakeBot(trace)
    bundle = build_alerts(
        journal=the_journal,
        spill=None,
        limits=limits if limits is not None else make_test_limits(),
        bot=bot,
        chat_id=CHAT_ID,
        sleep=NoSleep(),
        clock=clock,
    )
    return Parts(bundle=bundle, journal=the_journal, bot=bot, trace=trace)


def _golden(name: str) -> str:
    return (GOLDEN / f"{name}.txt").read_text(encoding="utf-8").replace("\r\n", "\n").rstrip("\n")


def _rows(journal: RecordingJournal, event_type: str) -> list[Any]:
    return [e for e in journal.events if e.event_type == event_type]


def _header(alert: OperationalAlert) -> str:
    """The Phase 20 header, typed from the alert fields (not from the renderer under test)."""
    at = alert.occurred_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f"[{alert.severity.value}] {alert.event}\n"
        f"subject: {alert.subject}\n"
        f"reason: {alert.reason}\n"
        f"at: {at}"
    )


# --------------------------------------------------------------------------- #
# Task 1: the tracer - a SAFE_MODE entry reaches the operator's chat.
# --------------------------------------------------------------------------- #


async def test_a_safe_mode_entry_of_the_composed_controller_reaches_the_bot_journal_first() -> None:
    p = _parts()
    controller = SafeModeController(
        adapter=SimpleNamespace(),  # type: ignore[arg-type]
        journal=RecordingJournal(),
        on_enter=p.bundle.safe_mode_observer,
    )

    controller.enter_safe_mode(reason="DB_FAILURE", now_utc=GOLDEN_AT)

    # Journal first: the alert row exists, nothing was sent, one alert waits in the queue.
    assert p.trace == ["journal:OPERATIONAL_ALERT"]
    assert p.bot.sent == []
    assert [a.event for a in p.bundle.queue] == ["DB_FAILURE"]

    report = await drain_once(p.bundle)

    assert (report.delivered, report.failed) == (1, 0)
    assert p.trace == ["journal:OPERATIONAL_ALERT", "send", "journal:ALERT_DELIVERED"]
    (sent,) = p.bot.sent
    assert sent.chat_id == CHAT_ID
    assert sent.text == _golden("DB_FAILURE")  # the Phase 23 wording, byte for byte


async def test_a_second_identical_entry_inside_the_dedupe_window_sends_nothing_more() -> None:
    p = _parts()
    observer = p.bundle.safe_mode_observer

    observer("DB_FAILURE", GOLDEN_AT)
    await drain_once(p.bundle)
    observer("DB_FAILURE", GOLDEN_AT + timedelta(seconds=1))
    report = await drain_once(p.bundle)

    assert report.delivered == 0
    assert len(p.bot.sent) == 1
    assert len(_rows(p.journal, "ALERT_SUPPRESSED")) == 1


def test_an_unset_dedupe_window_refuses_the_build_naming_the_key() -> None:
    limits = dataclasses.replace(make_test_limits(), alerts_dedupe_window_ms=None)

    with pytest.raises(ExecutionLimitsNotConfigured) as caught:
        _parts(limits=limits)

    assert caught.value.keys == ("alerts.dedupe_window_ms",)


async def test_a_bot_that_raises_is_journaled_and_drain_does_not_raise() -> None:
    p = _parts()
    p.bot.errors = [tg_error.BadRequest("chat not found token=abc123")]
    p.bundle.safe_mode_observer("DB_FAILURE", GOLDEN_AT)

    report = await drain_once(p.bundle)

    assert (report.delivered, report.failed) == (0, 1)
    (failed,) = _rows(p.journal, "ALERT_SEND_FAILED")
    assert "abc123" not in failed.payload_json  # the class name only, never the message
    assert p.bundle.queue == type(p.bundle.queue)()  # WR-C6: not queued again in the process


def test_the_build_needs_a_callable_clock() -> None:
    with pytest.raises(TypeError, match="clock"):
        build_alerts(
            journal=RecordingJournal(),
            spill=None,
            limits=make_test_limits(),
            bot=FakeBot(),
            chat_id=CHAT_ID,
            sleep=NoSleep(),
            clock=None,  # type: ignore[arg-type]
        )


# --------------------------------------------------------------------------- #
# Task 2: the T-05 alerts from their production producers.
# --------------------------------------------------------------------------- #


def _sink_into_placement_context(rig: LiveRig, bundle: AlertBundle) -> None:
    """Give the rig's placement inputs the bundle's sink as `LivePlacementContext.alert_sink`."""
    original = rig.inputs.for_plan

    async def with_sink(*args: Any) -> Any:
        result = await original(*args)
        if isinstance(result, PlacementInputs):
            context = dataclasses.replace(result.live_context, alert_sink=bundle.sink)
            return dataclasses.replace(result, live_context=context)
        return result

    rig.inputs.for_plan = with_sink


async def test_a_replayed_execution_of_a_consumed_approval_alerts_once_and_is_delivered() -> None:
    rig = await make_live_rig()
    p = _parts(clock=rig.clock.now)
    _sink_into_placement_context(rig, p.bundle)
    service = rig.wiring.service
    await rig.approve_and_confirm()
    await service.drain()
    assert list(p.bundle.queue) == [], "the first execution alerts nothing"
    approval = rig.approve_row()

    service.on_confirmed(approval, rig.plan, rig.clock.now())  # the same approval again
    await service.drain()

    (alert,) = p.bundle.queue
    assert alert.event == "DUPLICATE_EXECUTION_ATTEMPT"
    assert alert.plan_hash == rig.plan.plan_hash
    assert len(rig.fake.calls_to("place_entry")) == 1, "a placement is never re-sent"
    report = await drain_once(p.bundle)
    assert report.delivered == 1
    (sent,) = p.bot.sent
    assert sent.text.startswith(_header(alert))
    assert [e.event_type for e in p.journal.events][:1] == ["OPERATIONAL_ALERT"]


async def test_a_rejected_stop_after_a_fill_delivers_protective_rejected() -> None:
    rig = await make_live_rig()
    p = _parts(clock=rig.clock.now)
    # The coordinator and the emergency closer hold `rig.alerts`; point it at the bundle's sink.
    rig.alerts.critical = p.bundle.sink.critical  # type: ignore[method-assign]
    await rig.approve_and_confirm()
    await rig.wiring.service.drain()
    rig.fake.fill(rig.entry_id, quantity=D("0.004"))
    rig.route(rig.trade_frame())
    rig.fake.reject_next_algo(-2021)

    await rig.wiring.coordinator.step()

    events = [a.event for a in p.bundle.queue]
    assert events.count("PROTECTIVE_REJECTED") == 1
    assert "CLOSE_REQUIRED" in events
    report = await drain_once(p.bundle)
    assert report.failed == 0 and report.delivered == len(events)
    texts = [s.text for s in p.bot.sent]
    (text,) = [t for t in texts if t.startswith("[CRITICAL] PROTECTIVE_REJECTED")]
    assert "reason: B5_STOP_REJECTED" in text
    assert "subject: BTCUSDT" in text


def _verdict(state: DailyState) -> DayStateVerdict:
    return DayStateVerdict(
        utc_day=date(2026, 10, 31),
        state=state,
        reason_code=(
            RejectionReason.DAILY_STOP_BLOCK.value if state is DailyState.DAILY_STOP else "OK"
        ),
        blocked_reason=None,
        loss_quote=D("10"),
        latch_now=state is DailyState.DAILY_STOP,
        alerts_due=(state,),
    )


@pytest.mark.parametrize(
    ("state", "event", "severity"),
    [
        (DailyState.WARNING, "DAILY_LOSS_WARNING", "WARNING"),
        (DailyState.DAILY_STOP, "DAILY_STOP", "CRITICAL"),
    ],
)
async def test_the_daily_state_producer_delivers_its_alert(
    state: DailyState, event: str, severity: str
) -> None:
    rig = await make_live_rig()
    p = _parts(clock=rig.clock.now)

    outcome = await enforce_daily_state(
        verdict=_verdict(state),
        placed_plans=[],
        adapter=rig.fake,  # type: ignore[arg-type]
        journal=rig.journal,
        alert_sink=p.bundle.sink,
        now_utc=rig.clock.now(),
    )

    assert outcome.alerts_emitted == (event,) and outcome.alerts_failed == ()
    report = await drain_once(p.bundle)
    assert report.delivered == 1
    (sent,) = p.bot.sent
    assert sent.text.startswith(f"[{severity}] {event}\nsubject: utc-day-2026-10-31\n")
    assert f"reason: {state.value}\n" in sent.text
    assert [e.event_type for e in p.journal.events][0] == "OPERATIONAL_ALERT"


# --------------------------------------------------------------------------- #
# The gate alert.
# --------------------------------------------------------------------------- #


async def test_a_gate_ban_names_the_deadline_and_carries_no_exchange_text() -> None:
    p = _parts()
    until = GOLDEN_AT + timedelta(minutes=15)

    p.bundle.gate_alert(GateAlert(event="REST_GATE_BAN_ENTERED", until_utc=until))
    await drain_once(p.bundle)

    (sent,) = p.bot.sent
    assert sent.text == _golden("REST_GATE_BAN_ENTERED")
    assert "until: 2026-10-09T03:15:00Z" in sent.text
    (row,) = _rows(p.journal, "OPERATIONAL_ALERT")
    assert json.loads(row.payload_json)["until_utc"] == "2026-10-09T03:15:00Z"


async def test_the_real_gate_hook_string_becomes_a_structured_alert_rounded_up() -> None:
    p = _parts()
    hook = gate_alert_adapter(p.bundle.gate_alert)

    hook("REST_GATE_BAN_ENTERED until_utc=2026-10-09T03:15:00.250000+00:00")
    await drain_once(p.bundle)

    (sent,) = p.bot.sent
    assert "until: 2026-10-09T03:15:01Z" in sent.text, "never an end earlier than the gate's"


async def test_a_gate_recovery_alert_has_no_deadline_and_the_golden_text() -> None:
    p = _parts()
    gate_alert_adapter(p.bundle.gate_alert)("REST_GATE_RECOVERY_REQUIRED")

    await drain_once(p.bundle)

    (sent,) = p.bot.sent
    assert sent.text == _golden("REST_GATE_RECOVERY_REQUIRED")
    assert "until:" not in sent.text


async def test_a_ban_without_a_parsable_deadline_still_alerts() -> None:
    p = _parts()
    gate_alert_adapter(p.bundle.gate_alert)("REST_GATE_BAN_ENTERED until_utc=not-a-time")

    await drain_once(p.bundle)

    (sent,) = p.bot.sent
    assert sent.text.startswith("[HIGH] REST_GATE_BAN_ENTERED\n")
    assert "until:" not in sent.text.split("What happened:")[0]


def test_an_event_that_is_not_a_gate_event_is_refused_by_the_sink() -> None:
    p = _parts()

    with pytest.raises(ValueError, match="REST gate event"):
        p.bundle.sink.gate_alert(
            SimpleNamespace(event="DB_FAILURE", until_utc=None), now_utc=GOLDEN_AT
        )
    assert list(p.bundle.queue) == []


# --------------------------------------------------------------------------- #
# `until_utc` on the alert (the ops-level contract of this plan).
# --------------------------------------------------------------------------- #


def test_the_alert_id_and_text_of_an_alert_without_a_deadline_are_what_they_always_were() -> None:
    alert = OperationalAlert.create(
        event="DB_FAILURE", subject="SYSTEM", reason="DB_FAILURE", occurred_at_utc=GOLDEN_AT
    )

    assert alert.until_utc is None
    assert alert.alert_id == content_hash_event_id(
        prefix="alert",
        event_type="OPERATIONAL_ALERT",
        entity_id="SYSTEM",
        occurred_at_utc=GOLDEN_AT,
        payload_json=json.dumps({"event": "DB_FAILURE", "reason": "DB_FAILURE"}, sort_keys=True),
    )
    assert render_alert_text(alert) == (
        "[HIGH] DB_FAILURE\nsubject: SYSTEM\nreason: DB_FAILURE\nat: 2026-10-09T03:00:00Z"
    )


def test_only_the_ban_event_may_carry_a_deadline_and_it_must_be_utc() -> None:
    with pytest.raises(ValueError, match="only carried by REST_GATE_BAN_ENTERED"):
        OperationalAlert.create(
            event="DB_FAILURE",
            subject="SYSTEM",
            reason="DB_FAILURE",
            occurred_at_utc=GOLDEN_AT,
            until_utc=GOLDEN_AT,
        )
    with pytest.raises(ValueError, match="until_utc"):
        OperationalAlert.create(
            event="REST_GATE_BAN_ENTERED",
            subject="SYSTEM",
            reason="IP_BAN_418",
            occurred_at_utc=GOLDEN_AT,
            until_utc=datetime(2026, 10, 9, 4, 0, 0),  # noqa: DTZ001 - the naive case under test
        )


def test_the_gate_events_are_in_the_closed_contract_with_their_severities() -> None:
    assert ALERT_EVENTS["REST_GATE_BAN_ENTERED"].value == "HIGH"
    assert ALERT_EVENTS["REST_GATE_RECOVERY_REQUIRED"].value == "CRITICAL"


def test_a_ban_alert_keeps_its_deadline_through_the_journal_row() -> None:
    first = _parts()
    first.bundle.gate_alert(
        GateAlert(event="REST_GATE_BAN_ENTERED", until_utc=GOLDEN_AT + timedelta(hours=1))
    )
    restarted = _parts(clock=lambda: GOLDEN_AT + timedelta(seconds=5))

    report = requeue_at_start(restarted.bundle, first.journal.events)

    assert len(report.requeued) == 1 and report.invalid == ()
    (again,) = restarted.bundle.queue
    assert again.until_utc == GOLDEN_AT + timedelta(hours=1)
    assert render_alert_text(again) == render_alert_text(first.bundle.queue[0])


# --------------------------------------------------------------------------- #
# The start re-queue.
# --------------------------------------------------------------------------- #


async def test_requeue_at_start_queues_only_undelivered_alerts_and_only_once() -> None:
    journal = RecordingJournal()
    first = _parts(journal=journal)
    for subject in ("AAA", "BBB", "CCC"):
        first.bundle.sink.alert(
            event="DIVERGENCE", subject=subject, reason="UNSYNCED_NORMAL", now_utc=GOLDEN_AT
        )
    # Only the first alert is sent; the other two are lost with the process.
    first.bundle.queue.pop()
    first.bundle.queue.pop()
    assert (await drain_once(first.bundle)).delivered == 1

    restarted = _parts(journal=journal)
    report = requeue_at_start(restarted.bundle, list(journal.events))

    assert len(report.requeued) == 2 and report.invalid == ()
    assert sorted(a.subject for a in restarted.bundle.queue) == ["BBB", "CCC"]
    assert (await drain_once(restarted.bundle)).delivered == 2
    assert sorted(
        line.split(": ", 1)[1]
        for s in restarted.bot.sent
        for line in s.text.splitlines()
        if line.startswith("subject: ")
    ) == ["BBB", "CCC"]
    with pytest.raises(AlertsAlreadyRequeued):
        requeue_at_start(restarted.bundle, list(journal.events))


# --------------------------------------------------------------------------- #
# Guards of the module itself.
# --------------------------------------------------------------------------- #


def test_the_live_alert_module_never_names_the_rehearsal_sink_or_a_wall_clock() -> None:
    source = LIVE_ALERTS_SOURCE.read_text(encoding="utf-8")

    assert "RehearsalAlertSink" not in source
    assert "datetime.now" not in source and "time.time" not in source
