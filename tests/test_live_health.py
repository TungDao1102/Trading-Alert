"""The live health producer: ten results per tick, the D056 modes, the D058 mark gate (plan 24-22).

Evidence label: executed unit tests with fakes. Nothing here touches Binance, Telegram or a
database. Every time and threshold is TEST_ONLY (the owner has set no value for the REST error
rate or the database write age, so the producer takes them as required arguments).

Pinned (24-01 Q5, research C-3):

* `market_feed_freshness` = age of the REST mark price of the tracked symbols (the OLDEST one);
* `ws_connection_state` and `user_data_stream_state` = the user-data stream state;
* `last_closed_candle_time` = DEGRADED "not applicable" (the live process has no candle feed);
* the other six come from the composed objects; each result is journaled as `HEALTH_CHECK` with
  the mode, the Python version and the application revision.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_client import Environment
from src.adapters.binance_public import MarkPriceReading
from src.adapters.binance_userdata_supervisor import LivenessSnapshot, StreamState
from src.domain.journal import JournalEvent
from src.live.feeds import MarkBook
from src.live.health import (
    DbWriteTracker,
    LiveHealthProducer,
    LiveHealthThresholds,
    ReconcileObserver,
    RestErrorCounter,
    TelegramDeliveryObserver,
    health_tick_once,
)
from src.ops.alerts import SendReport
from src.ops.health import (
    ALL_CHECK_NAMES,
    CHECK_LAST_CLOSED_CANDLE_TIME,
    CHECK_MARKET_FEED_FRESHNESS,
    HealthCheckResult,
    HealthRuntimeMode,
)
from src.reconcile.compare import Divergence
from src.reconcile.loop import TICK_COMPARED, TICK_READ_FAILED, TICK_SKIPPED_GATE, TickReport

NOW = datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC)
SYMBOLS = ("BTCUSDT", "ETHUSDT")
DIAGNOSTICS = {"python_version": "3.13.TEST", "app_revision": "a" * 40}


class FakeSupervisor:
    def __init__(self, state: StreamState = StreamState.LIVE) -> None:
        self.state = state

    def liveness(self) -> LivenessSnapshot:
        return LivenessSnapshot(
            state=self.state,
            state_since_utc=NOW - timedelta(hours=1),
            epoch=1,
            last_event_at_utc=None,
            last_ping_at_utc=None,
            last_pong_at_utc=None,
            last_keepalive_ok_at_utc=None,
            consecutive_keepalive_failures=0,
        )


class Parts:
    """The objects a producer is built over; tests change them, then call `produce`."""

    def __init__(self) -> None:
        self.marks = MarkBook()
        for symbol in SYMBOLS:
            self.mark(symbol, age_seconds=5)
        self.supervisor = FakeSupervisor()
        self.halt: str | None = None
        self.rest = RestErrorCounter()
        self.reconcile = ReconcileObserver()
        self.reconcile.note(TickReport(outcome=TICK_COMPARED, now_utc=NOW, agreement=True))
        self.db = DbWriteTracker(clock=lambda: NOW)
        self.db.note_ok()
        self.telegram = TelegramDeliveryObserver()
        self.telegram.note(ok=True)
        self.thresholds = LiveHealthThresholds(
            mark_price_max_age=timedelta(seconds=60),
            mark_clock_skew=timedelta(milliseconds=500),
            rest_max_error_rate=Decimal("0.05"),
            db_write_max_age=timedelta(minutes=5),
        )

    def mark(self, symbol: str, *, age_seconds: float) -> None:
        self.marks.store(
            MarkPriceReading(
                symbol=symbol,
                mark_price=Decimal("50000"),
                exchange_time_utc=NOW - timedelta(seconds=age_seconds),
            )
        )

    def producer(
        self,
        *,
        mode: Environment = Environment.DEMO,
        demo_degraded_allowed: bool = True,
        symbols: tuple[str, ...] = SYMBOLS,
    ) -> LiveHealthProducer:
        return LiveHealthProducer(
            mode=mode,
            demo_degraded_allowed=demo_degraded_allowed,
            symbols=symbols,
            marks=self.marks,
            stream=self.supervisor,
            stream_halted_reason=lambda: self.halt,
            rest_errors=self.rest,
            reconcile=self.reconcile,
            db_writes=self.db,
            telegram=self.telegram,
            thresholds=self.thresholds,
        )


def by_name(results: list[HealthCheckResult]) -> dict[str, HealthCheckResult]:
    return {r.check_name: r for r in results}


# --------------------------------------------------------------------------- #
# Tracer - ten results, the D056 modes.
# --------------------------------------------------------------------------- #


def test_the_producer_emits_exactly_the_ten_names_in_order() -> None:
    results = Parts().producer().produce(now_utc=NOW)
    assert [r.check_name for r in results] == list(ALL_CHECK_NAMES)
    assert all(r.observed_at_utc == NOW for r in results)


def test_demo_with_the_flag_is_ok_with_exactly_the_candle_check_degraded() -> None:
    producer = Parts().producer(demo_degraded_allowed=True)
    results = producer.produce(now_utc=NOW)
    statuses = {r.check_name: r.status for r in results}
    assert statuses.pop(CHECK_LAST_CLOSED_CANDLE_TIME) == "DEGRADED"
    assert set(statuses.values()) == {"PASS"}
    assert "not applicable" in by_name(results)[CHECK_LAST_CLOSED_CANDLE_TIME].detail
    verdict = producer.verdict(results)
    assert verdict.is_no_trade is False
    assert verdict.mode is HealthRuntimeMode.DEMO
    assert verdict.demo_degraded_allowed is True
    assert verdict.degraded_names == (CHECK_LAST_CLOSED_CANDLE_TIME,)


def test_demo_without_the_flag_is_not_ok() -> None:
    producer = Parts().producer(demo_degraded_allowed=False)
    verdict = producer.verdict(producer.produce(now_utc=NOW))
    assert verdict.is_no_trade is True
    assert verdict.reason_code == "HEALTH_CHECK_FAILED"


def test_live_with_a_degraded_result_is_not_ok() -> None:
    producer = Parts().producer(mode=Environment.LIVE, demo_degraded_allowed=False)
    verdict = producer.verdict(producer.produce(now_utc=NOW))
    assert verdict.is_no_trade is True
    assert verdict.mode is HealthRuntimeMode.LIVE


def test_the_demo_flag_cannot_be_given_to_a_live_producer() -> None:
    with pytest.raises(ValueError, match="demo_degraded_allowed"):
        Parts().producer(mode=Environment.LIVE, demo_degraded_allowed=True)


def test_testnet_has_no_health_row() -> None:
    with pytest.raises(ValueError):
        Parts().producer(mode=Environment.TESTNET)


def test_a_fail_anywhere_is_not_ok_even_in_demo_with_the_flag() -> None:
    parts = Parts()
    parts.telegram.note(ok=False)
    producer = parts.producer()
    verdict = producer.verdict(producer.produce(now_utc=NOW))
    assert verdict.is_no_trade is True
    assert by_name(list(verdict.results))["telegram_delivery"].status == "FAIL"


def test_the_producer_never_runs_a_probe_that_messages_the_owner() -> None:
    """A tick reads recorded outcomes; the only sends are real alerts and the startup probe."""
    source = (Path(__file__).resolve().parents[1] / "src" / "live" / "health.py").read_text(
        encoding="utf-8"
    )
    # The one call sits in `TelegramDeliveryObserver.probe` (the startup probe), never in a tick.
    assert source.count("await check_telegram_delivery(") == 1
    assert "check_telegram_delivery(" not in source.split("def produce")[1].split("def verdict")[0]


# --------------------------------------------------------------------------- #
# D058 - the mark price gate.
# --------------------------------------------------------------------------- #


def test_a_stale_mark_price_fails_market_feed_freshness() -> None:
    parts = Parts()
    parts.mark("BTCUSDT", age_seconds=61)
    producer = parts.producer()
    results = by_name(producer.produce(now_utc=NOW))
    assert results[CHECK_MARKET_FEED_FRESHNESS].status == "FAIL"
    assert producer.verdict(list(results.values())).is_no_trade is True


def test_the_oldest_symbol_decides_and_a_boundary_age_passes() -> None:
    parts = Parts()
    parts.mark("ETHUSDT", age_seconds=60)
    assert by_name(parts.producer().produce(now_utc=NOW))[CHECK_MARKET_FEED_FRESHNESS].status == (
        "PASS"
    )
    parts.mark("ETHUSDT", age_seconds=60.001)
    assert by_name(parts.producer().produce(now_utc=NOW))[CHECK_MARKET_FEED_FRESHNESS].status == (
        "FAIL"
    )


def test_a_missing_mark_price_fails_and_so_do_no_tracked_symbols() -> None:
    parts = Parts()
    missing = parts.producer(symbols=("BTCUSDT", "SOLUSDT"))
    assert by_name(missing.produce(now_utc=NOW))[CHECK_MARKET_FEED_FRESHNESS].status == "FAIL"
    empty = parts.producer(symbols=())
    assert by_name(empty.produce(now_utc=NOW))[CHECK_MARKET_FEED_FRESHNESS].status == "FAIL"


def test_a_mark_ahead_of_now_passes_within_the_skew_and_fails_beyond_it() -> None:
    parts = Parts()
    parts.mark("BTCUSDT", age_seconds=-0.4)
    assert by_name(parts.producer().produce(now_utc=NOW))[CHECK_MARKET_FEED_FRESHNESS].status == (
        "PASS"
    )
    parts.mark("BTCUSDT", age_seconds=-0.6)
    assert by_name(parts.producer().produce(now_utc=NOW))[CHECK_MARKET_FEED_FRESHNESS].status == (
        "FAIL"
    )


# --------------------------------------------------------------------------- #
# The stream.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("state", [s for s in StreamState if s is not StreamState.LIVE])
def test_a_stream_that_is_not_live_fails_both_stream_checks(state: StreamState) -> None:
    parts = Parts()
    parts.supervisor.state = state
    results = by_name(parts.producer().produce(now_utc=NOW))
    assert results["ws_connection_state"].status == "FAIL"
    assert results["user_data_stream_state"].status == "FAIL"


def test_a_halted_stream_fails_the_user_data_check() -> None:
    parts = Parts()
    parts.halt = "DIVERGENCE_QUEUE_OVERFLOW"
    results = by_name(parts.producer().produce(now_utc=NOW))
    assert results["ws_connection_state"].status == "PASS"
    assert results["user_data_stream_state"].status == "FAIL"
    assert "DIVERGENCE_QUEUE_OVERFLOW" not in results["user_data_stream_state"].detail


# --------------------------------------------------------------------------- #
# REST error rate.
# --------------------------------------------------------------------------- #


def test_the_rest_counter_counts_calls_and_errors_per_window() -> None:
    counter = RestErrorCounter()
    counter.record_ok()
    counter.record_ok()
    counter.record_error()
    assert counter.take_window() == (1, 3)
    assert counter.take_window() == (0, 0)


async def test_wrap_counts_a_raising_call_and_reraises() -> None:
    counter = RestErrorCounter()

    async def good(x: int) -> int:
        return x

    async def bad() -> None:
        raise RuntimeError("boom")

    assert await counter.wrap(good)(3) == 3
    with pytest.raises(RuntimeError):
        await counter.wrap(bad)()
    assert counter.take_window() == (1, 2)


def test_a_rest_error_rate_above_the_maximum_fails_and_the_window_resets() -> None:
    parts = Parts()
    for _ in range(9):
        parts.rest.record_ok()
    parts.rest.record_error()
    producer = parts.producer()
    assert by_name(producer.produce(now_utc=NOW))["rest_error_rate"].status == "FAIL"
    assert by_name(producer.produce(now_utc=NOW))["rest_error_rate"].status == "PASS"


def test_a_rest_error_rate_at_the_maximum_passes() -> None:
    parts = Parts()
    for _ in range(19):
        parts.rest.record_ok()
    parts.rest.record_error()
    assert by_name(parts.producer().produce(now_utc=NOW))["rest_error_rate"].status == "PASS"


# --------------------------------------------------------------------------- #
# Reconciliation, unprotected positions, orphaned orders.
# --------------------------------------------------------------------------- #


def divergence(kind: str) -> Divergence:
    return Divergence(
        kind=kind,
        symbol="BTCUSDT",
        order_role="ENTRY",
        client_order_id="c1",
        client_algo_id=None,
        reason="test",
    )


def test_no_reconcile_tick_yet_fails_the_drift_check() -> None:
    parts = Parts()
    parts.reconcile = ReconcileObserver()
    assert by_name(parts.producer().produce(now_utc=NOW))["reconciliation_drift"].status == "FAIL"


@pytest.mark.parametrize("outcome", [TICK_READ_FAILED, TICK_SKIPPED_GATE])
def test_a_latest_tick_that_did_not_compare_fails_the_drift_check(outcome: str) -> None:
    parts = Parts()
    parts.reconcile.note(TickReport(outcome=outcome, now_utc=NOW))
    assert by_name(parts.producer().produce(now_utc=NOW))["reconciliation_drift"].status == "FAIL"


def test_a_compared_tick_with_a_disagreement_fails_the_drift_check() -> None:
    parts = Parts()
    parts.reconcile.note(TickReport(outcome=TICK_COMPARED, now_utc=NOW, agreement=False))
    assert by_name(parts.producer().produce(now_utc=NOW))["reconciliation_drift"].status == "FAIL"


def test_divergences_of_the_last_compared_tick_fail_the_matching_checks() -> None:
    parts = Parts()
    parts.reconcile.note(
        TickReport(
            outcome=TICK_COMPARED,
            now_utc=NOW,
            agreement=False,
            divergences=(
                divergence("ENTRY_WITHOUT_PROTECTIVE"),
                divergence("ORPHAN_PROTECTIVE"),
            ),
        )
    )
    # A later tick that could not compare keeps the last known divergences.
    parts.reconcile.note(TickReport(outcome=TICK_READ_FAILED, now_utc=NOW))
    results = by_name(parts.producer().produce(now_utc=NOW))
    assert results["unprotected_positions"].status == "FAIL"
    assert results["orphaned_orders"].status == "FAIL"
    assert results["reconciliation_drift"].status == "FAIL"


def test_a_clean_compared_tick_clears_the_divergences() -> None:
    parts = Parts()
    parts.reconcile.note(
        TickReport(
            outcome=TICK_COMPARED,
            now_utc=NOW,
            agreement=False,
            divergences=(divergence("ORPHAN_PROTECTIVE"),),
        )
    )
    parts.reconcile.note(TickReport(outcome=TICK_COMPARED, now_utc=NOW, agreement=True))
    results = by_name(parts.producer().produce(now_utc=NOW))
    assert results["orphaned_orders"].status == "PASS"
    assert results["reconciliation_drift"].status == "PASS"


# --------------------------------------------------------------------------- #
# Database writes.
# --------------------------------------------------------------------------- #


def test_no_database_write_yet_fails_the_check() -> None:
    parts = Parts()
    parts.db = DbWriteTracker(clock=lambda: NOW)
    assert by_name(parts.producer().produce(now_utc=NOW))["db_writes"].status == "FAIL"


def test_a_database_write_older_than_the_maximum_fails() -> None:
    parts = Parts()
    later = NOW + timedelta(minutes=5, seconds=1)
    assert by_name(parts.producer().produce(now_utc=later))["db_writes"].status == "FAIL"


async def test_tracked_writes_record_success_and_a_failure_clears_the_stamp() -> None:
    parts = Parts()
    parts.db = DbWriteTracker(clock=lambda: NOW)
    calls: list[int] = []

    async def write(value: int) -> int:
        if value < 0:
            raise OSError("db down")
        calls.append(value)
        return value

    tracked = parts.db.track(write)
    assert await tracked(1) == 1
    assert by_name(parts.producer().produce(now_utc=NOW))["db_writes"].status == "PASS"
    with pytest.raises(OSError):
        await tracked(-1)
    assert by_name(parts.producer().produce(now_utc=NOW))["db_writes"].status == "FAIL"
    assert await tracked(2) == 2
    assert by_name(parts.producer().produce(now_utc=NOW))["db_writes"].status == "PASS"


# --------------------------------------------------------------------------- #
# Telegram delivery.
# --------------------------------------------------------------------------- #


def test_no_telegram_delivery_observed_fails_closed() -> None:
    parts = Parts()
    parts.telegram = TelegramDeliveryObserver()
    assert by_name(parts.producer().produce(now_utc=NOW))["telegram_delivery"].status == "FAIL"


def test_a_send_report_updates_the_observed_outcome() -> None:
    observer = TelegramDeliveryObserver()
    observer.note_send_report(SendReport(delivered=2, failed=0, audit_lost=0))
    assert observer.last_ok is True
    observer.note_send_report(SendReport(delivered=0, failed=0, audit_lost=0))
    assert observer.last_ok is True  # nothing was sent: nothing learned
    observer.note_send_report(SendReport(delivered=1, failed=1, audit_lost=0))
    assert observer.last_ok is False


class FakeNotifier:
    def __init__(self, *, raises: bool = False) -> None:
        self.raises = raises
        self.sent: list[str] = []

    async def send_message(self, *, chat_id: Any, text: str, reply_markup: Any = None) -> Any:
        if self.raises:
            raise OSError("net")
        self.sent.append(text)
        return {"message_id": 1}


async def test_the_startup_probe_sends_once_and_records_the_outcome() -> None:
    observer = TelegramDeliveryObserver()
    sink: list[JournalEvent] = []

    class Journal:
        def record(self, event: Any) -> None:
            sink.append(event)

    notifier = FakeNotifier()
    result = await observer.probe(
        notifier=notifier,
        chat_id=1,
        probe_text="live process started",
        now_utc=NOW,
        journal=Journal(),
    )
    assert result.status == "PASS"
    assert observer.last_ok is True
    assert notifier.sent == ["live process started"]
    failing = FakeNotifier(raises=True)
    result = await observer.probe(
        notifier=failing, chat_id=1, probe_text="x", now_utc=NOW, journal=Journal()
    )
    assert result.status == "FAIL"
    assert observer.last_ok is False


# --------------------------------------------------------------------------- #
# The tick body: journaling.
# --------------------------------------------------------------------------- #


class Recorder:
    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[JournalEvent] = []
        self.fail = fail

    async def __call__(self, event: JournalEvent) -> None:
        if self.fail:
            raise OSError("journal down")
        self.events.append(event)


async def test_a_tick_journals_ten_health_checks_with_diagnostics_and_one_verdict() -> None:
    producer = Parts().producer()
    recorder = Recorder()
    verdict = await health_tick_once(
        producer, now_utc=NOW, record=recorder, diagnostics=lambda: DIAGNOSTICS
    )
    assert verdict.is_no_trade is False
    checks = [e for e in recorder.events if e.event_type == "HEALTH_CHECK"]
    assert [e.entity_id for e in checks] == list(ALL_CHECK_NAMES)
    for event in checks:
        payload = json.loads(event.payload_json)
        assert payload["python_version"] == "3.13.TEST"
        assert payload["app_revision"] == "a" * 40
        assert payload["mode"] == "DEMO"
        assert payload["demo_degraded_allowed"] is True
        assert event.correlation_id == "execution_health"
    verdicts = [e for e in recorder.events if e.event_type == "HEALTH_VERDICT"]
    assert len(verdicts) == 1
    document = json.loads(verdicts[0].payload_json)
    assert document["is_no_trade"] is False
    assert document["mode"] == "DEMO"
    assert document["demo_degraded_allowed"] is True
    assert document["degraded"] == [CHECK_LAST_CLOSED_CANDLE_TIME]
    assert document["failing"] == []
    assert document["python_version"] == "3.13.TEST"
    assert producer.latest_verdict is verdict


async def test_the_verdict_event_names_the_failing_checks() -> None:
    parts = Parts()
    parts.mark("BTCUSDT", age_seconds=300)
    recorder = Recorder()
    verdict = await health_tick_once(
        parts.producer(), now_utc=NOW, record=recorder, diagnostics=lambda: DIAGNOSTICS
    )
    assert verdict.is_no_trade is True
    document = json.loads(
        next(e for e in recorder.events if e.event_type == "HEALTH_VERDICT").payload_json
    )
    assert document["is_no_trade"] is True
    assert document["failing"] == [CHECK_MARKET_FEED_FRESHNESS]


async def test_the_default_diagnostics_are_the_runtime_payload() -> None:
    recorder = Recorder()
    await health_tick_once(Parts().producer(), now_utc=NOW, record=recorder)
    payload = json.loads(recorder.events[0].payload_json)
    assert payload["python_version"] == sys.version
    assert "app_revision" in payload


async def test_a_journal_failure_propagates_but_the_verdict_was_kept() -> None:
    producer = Parts().producer()
    with pytest.raises(OSError):
        await health_tick_once(
            producer, now_utc=NOW, record=Recorder(fail=True), diagnostics=lambda: DIAGNOSTICS
        )
    assert producer.latest_verdict is not None


def test_no_verdict_before_the_first_tick() -> None:
    assert Parts().producer().latest_verdict is None
