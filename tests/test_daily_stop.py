"""DAILY_STOP actions and the daily-loss alert producers (Phase 21, plan 21-10; D-12, D-13, D033).

Evidence label: executed tests with the Binance-semantics fake exchange [DESIGN]; no [DEMO]
claim. The producer is not wired in a running process until Phase 24.

Task 1 (tracer): a latched DAILY_STOP cancels the resting entry through `expire_pending_entry`,
keeps the stop of the open position and journals the CRITICAL alert after the cancel.
Task 2: gate refusals, a fill racing the cancel, unknown system entries, the idempotent second
call, WARNING, a missing day state and a failing alert sink.
"""

from __future__ import annotations

import ast
import json
from collections import deque
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_ratelimit_gate import RateLimitPauseActive
from src.domain.enums import DailyState, RejectionReason
from src.execution.daily_stop import (
    ALERT_DAILY_LOSS_WARNING,
    ALERT_DAILY_STOP,
    ALERT_REASON_ENTRY_CANCEL_INCOMPLETE,
    ALERT_REASON_UNMATCHED_ENTRY_ORDER,
    DAILY_STOP_TRIGGER,
    DailyStopOutcome,
    PlacedPlanRef,
    day_alert_subject,
    enforce_daily_state,
)
from src.execution.manager import expire_pending_entry
from src.execution.order_ids import derive_algo_client_id, derive_client_order_id
from src.ops.alerts import JournalFirstAlertSink, OperationalAlert
from src.ops.risk_first import AuditRecordLost
from src.risk.daily_loss import (
    BLOCKED_DAILY_LOSS_UNKNOWN,
    BLOCKED_DAY_BASE_UNAVAILABLE,
    BLOCKED_DAY_STATE_MISSING,
    BLOCKED_DAY_STATE_UNREADABLE,
    BLOCKED_DAY_THRESHOLDS_INVALID,
    DayStateVerdict,
    blocked_verdict,
)

from tests.support.ast_guards import float_constructor_calls, wall_clock_calls
from tests.support.execution_limits import test_only_execution_limits as make_test_limits
from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.reconcile_doubles import RecordingAlertSink, RecordingJournal

NOW_UTC = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
DAY = date(2026, 10, 23)
SUBJECT = "utc-day-2026-10-23"
HASH_P = "a" * 64
HASH_Q = "b" * 64
HASH_R = "c" * 64
PLAN_P = "plan-p"
PLAN_Q = "plan-q"
PLAN_R = "plan-r"
QUANTITY = Decimal("0.004")
PRICE = Decimal("60000")
SRC = Path(__file__).resolve().parents[1] / "src" / "execution" / "daily_stop.py"


def _verdict(
    state: DailyState | None = DailyState.DAILY_STOP,
    *,
    latch_now: bool = True,
    alerts_due: tuple[DailyState, ...] | None = None,
) -> DayStateVerdict:
    if alerts_due is None:
        alerts_due = (state,) if state is not None else ()  # type: ignore[assignment]
    return DayStateVerdict(
        utc_day=DAY,
        state=state,
        reason_code=(
            RejectionReason.DAILY_STOP_BLOCK.value if state is DailyState.DAILY_STOP else "OK"
        ),
        blocked_reason=None,
        loss_quote=Decimal("10"),
        latch_now=latch_now,
        alerts_due=alerts_due,
    )


async def _rest_entry(
    fake: BinanceSemanticsFakeAdapter, plan_hash: str, symbol: str = "BTCUSDT"
) -> str:
    client_id = derive_client_order_id(plan_hash=plan_hash, role="ENTRY")
    await fake.place_entry(
        symbol=symbol,
        side="BUY",
        position_side="BOTH",
        time_in_force="GTC",
        quantity=QUANTITY,
        price=PRICE,
        new_client_order_id=client_id,
    )
    return client_id


async def _open_position_with_stop(fake: BinanceSemanticsFakeAdapter, plan_hash: str) -> str:
    entry_id = await _rest_entry(fake, plan_hash, "ETHUSDT")
    fake.fill(entry_id)
    stop_id = derive_algo_client_id(plan_hash=plan_hash, role="STOP_LOSS")
    await fake.place_algo_protective(
        symbol="ETHUSDT",
        side="SELL",
        algo_type="CONDITIONAL",
        type="STOP_MARKET",
        position_side="BOTH",
        trigger_price=Decimal("59000"),
        close_position=True,
        quantity=None,
        working_type="MARK_PRICE",
        client_algo_id=stop_id,
        reduce_only=None,
    )
    return stop_id


class TraceJournal(RecordingJournal):
    """A recording journal that keeps the order of the event types."""

    def __init__(self) -> None:
        super().__init__()
        self.order: list[str] = []

    def record(self, event: Any) -> None:
        super().record(event)
        self.order.append(event.event_type)


def _sink(journal: Any) -> JournalFirstAlertSink:
    return JournalFirstAlertSink(
        journal=journal, spill=None, limits=make_test_limits(), queue=deque()
    )


async def _enforce(
    fake: BinanceSemanticsFakeAdapter,
    verdict: DayStateVerdict,
    plans: list[PlacedPlanRef],
    journal: Any,
    sink: Any,
) -> DailyStopOutcome:
    return await enforce_daily_state(
        verdict=verdict,
        placed_plans=plans,
        adapter=fake,  # type: ignore[arg-type]
        journal=journal,
        alert_sink=sink,
        now_utc=NOW_UTC,
    )


# --------------------------------------------------------------------------- #
# Task 1 (tracer).
# --------------------------------------------------------------------------- #


async def test_latched_daily_stop_cancels_the_entry_keeps_the_stop_and_alerts_after() -> None:
    fake = BinanceSemanticsFakeAdapter()
    entry_p = await _rest_entry(fake, HASH_P)
    stop_q = await _open_position_with_stop(fake, HASH_Q)
    position_q = fake.positions["ETHUSDT"]
    journal = TraceJournal()
    sink = _sink(journal)

    outcome = await _enforce(
        fake, _verdict(), [PlacedPlanRef(PLAN_P, HASH_P, "BTCUSDT")], journal, sink
    )

    assert outcome.cancelled == (PLAN_P,)
    assert outcome.unverified == () and outcome.not_cancelled == ()
    assert outcome.alerts_emitted == (ALERT_DAILY_STOP,)
    cancels = fake.calls_to("cancel_normal_order")
    assert [c["kwargs"]["orig_client_order_id"] for c in cancels] == [entry_p]
    assert len(fake.calls_to("cancel_algo_order")) == 0
    assert stop_q in [o.client_algo_id for o in await fake.snapshot_open_algo_orders(symbol=None)]
    assert fake.positions["ETHUSDT"] == position_q
    assert entry_p not in fake.open_orders

    alert_rows = [e for e in journal.events if e.event_type == "OPERATIONAL_ALERT"]
    assert len(alert_rows) == 1
    payload = json.loads(alert_rows[0].payload_json)
    assert payload["event"] == "DAILY_STOP"
    assert payload["subject"] == SUBJECT
    assert payload["reason"] == "DAILY_STOP"
    assert payload["severity"] == "CRITICAL"
    assert [a.event for a in sink.queue] == ["DAILY_STOP"]
    # The cancel rows come before the alert row.
    assert journal.order.index("OPERATIONAL_ALERT") > max(
        i for i, t in enumerate(journal.order) if t == "ENTRY_EXPIRY"
    )
    cancel_payload = json.loads(
        next(e for e in journal.events if e.event_type == "ENTRY_EXPIRY").payload_json
    )
    assert cancel_payload["trigger_reason"] == DAILY_STOP_TRIGGER


async def test_daily_stop_is_an_accepted_trigger_and_an_unknown_one_still_raises() -> None:
    fake = BinanceSemanticsFakeAdapter()
    await _rest_entry(fake, HASH_P)
    journal = RecordingJournal()

    await expire_pending_entry(
        plan_hash=HASH_P,
        symbol="BTCUSDT",
        adapter=fake,  # type: ignore[arg-type]
        journal=journal,
        now_utc=NOW_UTC,
        trigger_reason="daily_stop",
    )
    with pytest.raises(ValueError, match="unknown trigger_reason"):
        await expire_pending_entry(
            plan_hash=HASH_P,
            symbol="BTCUSDT",
            adapter=fake,  # type: ignore[arg-type]
            journal=journal,
            now_utc=NOW_UTC,
            trigger_reason="daily_halt",
        )


def test_day_alert_subject_is_fixed_and_valid() -> None:
    assert day_alert_subject(DAY) == SUBJECT
    OperationalAlert.create(
        event="DAILY_STOP",
        subject=day_alert_subject(DAY),
        reason="DAILY_STOP",
        occurred_at_utc=NOW_UTC,
        plan_hash=None,
        symbol=None,
    )


# --------------------------------------------------------------------------- #
# Task 2.
# --------------------------------------------------------------------------- #


async def test_a_gate_refusal_on_one_cancel_does_not_stop_the_others_and_the_alert_follows() -> (
    None
):
    fake = BinanceSemanticsFakeAdapter()
    await _rest_entry(fake, HASH_P, "BTCUSDT")
    await _rest_entry(fake, HASH_Q, "ETHUSDT")
    fake.fail_next("cancel_normal_order", RateLimitPauseActive(30))
    journal = RecordingJournal()
    sink = RecordingAlertSink()
    plans = [PlacedPlanRef(PLAN_P, HASH_P, "BTCUSDT"), PlacedPlanRef(PLAN_Q, HASH_Q, "ETHUSDT")]

    outcome = await _enforce(fake, _verdict(), plans, journal, sink)

    # Symbols are visited in sorted order: BTCUSDT (plan P) is refused first.
    assert outcome.not_cancelled == ((PLAN_P, "RateLimitPauseActive"),)
    assert outcome.cancelled == (PLAN_Q,)
    # The stop alert, then (WR-07) the incomplete cancel under its own reason.
    assert [(a.event, a.reason) for a in sink.alerts] == [
        (ALERT_DAILY_STOP, "DAILY_STOP"),
        (ALERT_DAILY_STOP, ALERT_REASON_ENTRY_CANCEL_INCOMPLETE),
    ]
    assert len(fake.calls_to("cancel_algo_order")) == 0
    assert len(fake.calls_to("cancel_normal_order")) == 2  # no retry inside one call


async def test_a_failing_open_order_read_marks_every_plan_of_that_symbol_not_cancelled() -> None:
    fake = BinanceSemanticsFakeAdapter()
    await _rest_entry(fake, HASH_P)
    fake.fail_next("snapshot_open_normal_orders", RateLimitPauseActive(5))
    sink = RecordingAlertSink()

    outcome = await _enforce(
        fake, _verdict(), [PlacedPlanRef(PLAN_P, HASH_P, "BTCUSDT")], RecordingJournal(), sink
    )

    assert outcome.not_cancelled == ((PLAN_P, "RateLimitPauseActive"),)
    assert fake.calls_to("cancel_normal_order") == []
    assert [(a.event, a.reason) for a in sink.alerts] == [
        (ALERT_DAILY_STOP, "DAILY_STOP"),
        (ALERT_DAILY_STOP, ALERT_REASON_ENTRY_CANCEL_INCOMPLETE),
    ]


class _FillsOnCancel(BinanceSemanticsFakeAdapter):
    """The entry fills just before the cancel arrives: the cancel answers absent."""

    async def cancel_normal_order(self, **kwargs: Any) -> Any:
        self.fill(kwargs["orig_client_order_id"])
        return await super().cancel_normal_order(**kwargs)


async def test_a_fill_racing_the_cancel_is_unverified_and_left_to_the_coordinator() -> None:
    fake = _FillsOnCancel()
    await _rest_entry(fake, HASH_P)
    sink = RecordingAlertSink()

    outcome = await _enforce(
        fake, _verdict(), [PlacedPlanRef(PLAN_P, HASH_P, "BTCUSDT")], RecordingJournal(), sink
    )

    assert outcome.cancelled == ()
    assert outcome.unverified == ((PLAN_P, "FILLED_OR_PARTIAL"),)
    assert fake.calls_to("place_market_close") == []
    assert fake.calls_to("place_algo_protective") == []
    assert fake.calls_to("cancel_algo_order") == []
    assert [(a.event, a.reason) for a in sink.alerts] == [
        (ALERT_DAILY_STOP, "DAILY_STOP"),
        (ALERT_DAILY_STOP, ALERT_REASON_ENTRY_CANCEL_INCOMPLETE),
    ]


async def test_a_clean_cancel_alerts_the_stop_once_and_nothing_about_the_cancel() -> None:
    fake = BinanceSemanticsFakeAdapter()
    await _rest_entry(fake, HASH_P)
    sink = RecordingAlertSink()

    outcome = await _enforce(
        fake, _verdict(), [PlacedPlanRef(PLAN_P, HASH_P, "BTCUSDT")], RecordingJournal(), sink
    )

    assert outcome.cancelled == (PLAN_P,)
    assert [(a.event, a.reason) for a in sink.alerts] == [(ALERT_DAILY_STOP, "DAILY_STOP")]


async def test_an_incomplete_cancel_is_alerted_again_on_every_call_while_the_latch_holds() -> None:
    # WR-07: the DAILY_STOP alert itself is due once (alerts_due), a later call is the retry of
    # the cancel; if that retry also fails the operator must hear it, not only the first time.
    fake = BinanceSemanticsFakeAdapter()
    await _rest_entry(fake, HASH_P)
    fake.fail_next("cancel_normal_order", RateLimitPauseActive(30))
    sink = RecordingAlertSink()
    held = _verdict(latch_now=False, alerts_due=())

    outcome = await _enforce(
        fake, held, [PlacedPlanRef(PLAN_P, HASH_P, "BTCUSDT")], RecordingJournal(), sink
    )

    assert outcome.not_cancelled == ((PLAN_P, "RateLimitPauseActive"),)
    assert [(a.event, a.reason) for a in sink.alerts] == [
        (ALERT_DAILY_STOP, ALERT_REASON_ENTRY_CANCEL_INCOMPLETE)
    ]


async def test_an_unmatched_system_entry_on_a_stopped_day_is_alerted() -> None:
    fake = BinanceSemanticsFakeAdapter()
    await _rest_entry(fake, HASH_P)
    stray_id = await _rest_entry(fake, HASH_R)
    sink = RecordingAlertSink()

    outcome = await _enforce(
        fake, _verdict(), [PlacedPlanRef(PLAN_P, HASH_P, "BTCUSDT")], RecordingJournal(), sink
    )

    assert outcome.unmatched_entry_orders == (stray_id,)
    assert stray_id in fake.open_orders  # alert only, never cancelled
    assert [(a.event, a.reason) for a in sink.alerts] == [
        (ALERT_DAILY_STOP, "DAILY_STOP"),
        (ALERT_DAILY_STOP, ALERT_REASON_UNMATCHED_ENTRY_ORDER),
    ]
    assert all(a.subject == SUBJECT for a in sink.alerts)


async def test_the_real_sink_does_not_dedupe_the_incomplete_cancel_into_the_stop_alert() -> None:
    fake = BinanceSemanticsFakeAdapter()
    await _rest_entry(fake, HASH_P)
    fake.fail_next("cancel_normal_order", RateLimitPauseActive(30))
    journal = TraceJournal()
    sink = _sink(journal)

    await _enforce(fake, _verdict(), [PlacedPlanRef(PLAN_P, HASH_P, "BTCUSDT")], journal, sink)

    assert [(a.event, a.reason) for a in sink.queue] == [
        ("DAILY_STOP", "DAILY_STOP"),
        ("DAILY_STOP", ALERT_REASON_ENTRY_CANCEL_INCOMPLETE),
    ]


async def test_an_unmatched_system_entry_is_reported_never_cancelled_and_foreign_is_ignored() -> (
    None
):
    fake = BinanceSemanticsFakeAdapter()
    await _rest_entry(fake, HASH_P)
    stray_id = await _rest_entry(fake, HASH_R)  # a system entry of a plan nobody told us about
    await fake.place_entry(
        symbol="BTCUSDT",
        side="BUY",
        position_side="BOTH",
        time_in_force="GTC",
        quantity=QUANTITY,
        price=PRICE,
        new_client_order_id="manual-order-1",
    )

    outcome = await _enforce(
        fake,
        _verdict(),
        [PlacedPlanRef(PLAN_P, HASH_P, "BTCUSDT")],
        RecordingJournal(),
        RecordingAlertSink(),
    )

    assert outcome.cancelled == (PLAN_P,)
    assert outcome.unmatched_entry_orders == (stray_id,)
    assert stray_id in fake.open_orders
    assert "manual-order-1" in fake.open_orders
    cancels = fake.calls_to("cancel_normal_order")
    assert [c["kwargs"]["orig_client_order_id"] for c in cancels] == [
        derive_client_order_id(plan_hash=HASH_P, role="ENTRY")
    ]


async def test_a_placed_plan_whose_entry_no_longer_rests_is_not_cancelled_and_not_an_error() -> (
    None
):
    fake = BinanceSemanticsFakeAdapter()
    outcome = await _enforce(
        fake,
        _verdict(),
        [PlacedPlanRef(PLAN_P, HASH_P, "BTCUSDT")],
        RecordingJournal(),
        RecordingAlertSink(),
    )

    assert outcome == DailyStopOutcome((), (), (), (), (ALERT_DAILY_STOP,))
    assert fake.calls_to("cancel_normal_order") == []


async def test_a_second_call_with_the_latch_already_held_is_idempotent() -> None:
    fake = BinanceSemanticsFakeAdapter()
    await _rest_entry(fake, HASH_P)
    plans = [PlacedPlanRef(PLAN_P, HASH_P, "BTCUSDT")]
    journal = RecordingJournal()
    sink = RecordingAlertSink()

    first = await _enforce(fake, _verdict(), plans, journal, sink)
    second = await _enforce(fake, _verdict(latch_now=False, alerts_due=()), plans, journal, sink)

    assert first.cancelled == (PLAN_P,)
    assert second == DailyStopOutcome((), (), (), (), ())
    assert len(fake.calls_to("cancel_normal_order")) == 1
    assert [a.event for a in sink.alerts] == [ALERT_DAILY_STOP]


async def test_a_warning_alerts_without_any_adapter_call() -> None:
    fake = BinanceSemanticsFakeAdapter()
    await _rest_entry(fake, HASH_P)
    calls_before = len(fake.calls)
    sink = RecordingAlertSink()

    outcome = await _enforce(
        fake,
        _verdict(DailyState.WARNING, latch_now=False),
        [PlacedPlanRef(PLAN_P, HASH_P, "BTCUSDT")],
        RecordingJournal(),
        sink,
    )

    assert outcome.alerts_emitted == (ALERT_DAILY_LOSS_WARNING,)
    assert [(a.event, a.subject, a.reason) for a in sink.alerts] == [
        (ALERT_DAILY_LOSS_WARNING, SUBJECT, "WARNING")
    ]
    assert len(fake.calls) == calls_before


async def test_a_normal_verdict_does_nothing() -> None:
    fake = BinanceSemanticsFakeAdapter()
    sink = RecordingAlertSink()

    outcome = await _enforce(
        fake,
        _verdict(DailyState.NORMAL, latch_now=False, alerts_due=()),
        [PlacedPlanRef(PLAN_P, HASH_P, "BTCUSDT")],
        RecordingJournal(),
        sink,
    )

    assert outcome == DailyStopOutcome((), (), (), (), ())
    assert fake.calls == [] and sink.alerts == []


@pytest.mark.parametrize("reason", [BLOCKED_DAY_STATE_MISSING, BLOCKED_DAY_STATE_UNREADABLE])
async def test_a_missing_or_unreadable_day_state_alerts_db_failure_and_cancels_nothing(
    reason: str,
) -> None:
    fake = BinanceSemanticsFakeAdapter()
    await _rest_entry(fake, HASH_P)
    calls_before = len(fake.calls)
    sink = RecordingAlertSink()

    outcome = await _enforce(
        fake,
        blocked_verdict(utc_day=DAY, blocked_reason=reason),
        [PlacedPlanRef(PLAN_P, HASH_P, "BTCUSDT")],
        RecordingJournal(),
        sink,
    )

    assert outcome.alerts_emitted == ("DB_FAILURE",)
    assert [(a.event, a.subject, a.reason) for a in sink.alerts] == [
        ("DB_FAILURE", SUBJECT, reason)
    ]
    assert len(fake.calls) == calls_before


@pytest.mark.parametrize(
    "reason",
    [BLOCKED_DAILY_LOSS_UNKNOWN, BLOCKED_DAY_BASE_UNAVAILABLE, BLOCKED_DAY_THRESHOLDS_INVALID],
)
async def test_the_other_blocked_reasons_emit_nothing(reason: str) -> None:
    fake = BinanceSemanticsFakeAdapter()
    sink = RecordingAlertSink()

    outcome = await _enforce(
        fake,
        blocked_verdict(utc_day=DAY, blocked_reason=reason),
        [PlacedPlanRef(PLAN_P, HASH_P, "BTCUSDT")],
        RecordingJournal(),
        sink,
    )

    assert outcome == DailyStopOutcome((), (), (), (), ())
    assert sink.alerts == [] and fake.calls == []


@pytest.mark.parametrize(
    "exc",
    [
        AuditRecordLost(
            journal_event_id="e1", journal_error="StoreUnavailable", spill_error="OSError"
        ),
        RuntimeError("boom"),
    ],
)
async def test_a_failing_alert_sink_does_not_undo_the_cancels(exc: BaseException) -> None:
    fake = BinanceSemanticsFakeAdapter()
    entry_id = await _rest_entry(fake, HASH_P)
    sink = RecordingAlertSink(fail_with=exc)

    outcome = await _enforce(
        fake, _verdict(), [PlacedPlanRef(PLAN_P, HASH_P, "BTCUSDT")], RecordingJournal(), sink
    )

    assert outcome.cancelled == (PLAN_P,)
    assert outcome.alerts_emitted == ()
    # WR-07: the failure is reported with its class name only, never silently dropped.
    assert outcome.alerts_failed == ((ALERT_DAILY_STOP, type(exc).__name__),)
    assert sink.attempts == 1
    assert entry_id not in fake.open_orders


async def test_outcome_tuples_are_sorted_by_trade_plan_id() -> None:
    fake = BinanceSemanticsFakeAdapter()
    await _rest_entry(fake, HASH_P, "BTCUSDT")
    await _rest_entry(fake, HASH_Q, "ETHUSDT")
    plans = [PlacedPlanRef("z-plan", HASH_P, "BTCUSDT"), PlacedPlanRef("a-plan", HASH_Q, "ETHUSDT")]

    outcome = await _enforce(fake, _verdict(), plans, RecordingJournal(), RecordingAlertSink())

    assert outcome.cancelled == ("a-plan", "z-plan")


def test_placed_plan_ref_rejects_a_bad_plan_hash_and_empty_fields() -> None:
    with pytest.raises(ValueError):
        PlacedPlanRef(PLAN_P, "short", "BTCUSDT")
    with pytest.raises(ValueError):
        PlacedPlanRef("", HASH_P, "BTCUSDT")
    with pytest.raises(ValueError):
        PlacedPlanRef(PLAN_P, HASH_P, "")


def test_the_module_has_no_wall_clock_no_float_and_no_protective_cancel() -> None:
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    assert wall_clock_calls(SRC) == []
    assert float_constructor_calls(SRC) == []
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert not called & {
        "cancel_algo_order",
        "cancel_untriggered_protectives",
        "place_entry",
        "place_market_close",
        "place_algo_protective",
    }
