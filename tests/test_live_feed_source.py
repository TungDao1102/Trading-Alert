"""Feed sources of the live reconcile loop (plan 24-19, D-14, 20-DEFERRED feed-liveness row).

Pins `LiveFeedSource` (a quiet account is not stale, a dead connection is), `refresh_marks`
(one call per symbol, never raises, an old reading ages), and `StreamDivergenceQueue` (arrival
order, drained once, halt reason, bounded, and a rejected triggered stop reaches SAFE_MODE through
a real router and a real `ReconcileLoop` tick).

Evidence label: executed unit tests with fakes. Every frame is SYNTHETIC (tests/support/
userdata_frames.py), written from the SDK model and never captured from Binance. Nothing here
touches Binance, Telegram or a database. Times are TEST_ONLY.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from src.adapters.binance_public import MarkPriceReading
from src.adapters.binance_userdata_events import parse_stream_message
from src.adapters.binance_userdata_router import (
    KnownOrder,
    StreamDivergence,
    StreamDivergenceKind,
)
from src.adapters.binance_userdata_supervisor import LivenessSnapshot, StreamState
from src.domain.enums import OrderRole, OrderStatus
from src.live.feeds import (
    ESCALATED_REASON,
    REASON_DIVERGENCE_QUEUE_OVERFLOW,
    LiveFeedSource,
    MarkBook,
    StreamDivergenceQueue,
    refresh_marks,
)
from src.reconcile.feed_freshness import assess_feeds

from tests.support.execution_limits import test_only_execution_limits as make_test_limits
from tests.support.reconcile_rig import NOW, build_rig
from tests.support.stream_sinks import (
    FakeOrderLookup,
    RecordingJournal,
    RecordingSinks,
    make_router,
)
from tests.support.userdata_frames import conditional_order_trigger_reject_frame

LIMITS = make_test_limits()
SILENCE = timedelta(milliseconds=LIMITS.stale_feed_max_user_data_silence_ms or 0)
MARK_AGE = timedelta(milliseconds=LIMITS.stale_feed_max_mark_price_age_ms or 0)
SKEW = timedelta(milliseconds=500)
SYMBOLS = ("BTCUSDT", "ETHUSDT")
LONG_AGO = NOW - timedelta(hours=1)


def snapshot(
    *,
    state: StreamState = StreamState.LIVE,
    since: datetime = LONG_AGO,
    event: datetime | None = None,
    ping: datetime | None = None,
    pong: datetime | None = None,
) -> LivenessSnapshot:
    return LivenessSnapshot(
        state=state,
        state_since_utc=since,
        epoch=1,
        last_event_at_utc=event,
        last_ping_at_utc=ping,
        last_pong_at_utc=pong,
        last_keepalive_ok_at_utc=None,
        consecutive_keepalive_failures=0,
    )


class FakeSupervisor:
    def __init__(self, snap: LivenessSnapshot) -> None:
        self.snap = snap

    def liveness(self) -> LivenessSnapshot:
        return self.snap


def mark(symbol: str, at: datetime) -> MarkPriceReading:
    return MarkPriceReading(symbol=symbol, mark_price=Decimal("60000"), exchange_time_utc=at)


class FakeReader:
    def __init__(self, at: datetime, *, failing: set[str] | None = None) -> None:
        self.at = at
        self.failing = failing or set()
        self.calls: list[str] = []

    async def mark_price(self, symbol: str) -> MarkPriceReading:
        self.calls.append(symbol)
        if symbol in self.failing:
            raise TimeoutError("TEST_ONLY failure")
        return mark(symbol, self.at)


def source(snap: LivenessSnapshot, book: MarkBook) -> LiveFeedSource:
    return LiveFeedSource(
        supervisor=FakeSupervisor(snap), marks=book, clock=lambda: NOW, symbols=SYMBOLS
    )


def judge(src: LiveFeedSource, now: datetime = NOW):  # type: ignore[no-untyped-def]
    return assess_feeds(
        src.read_feed(), symbols=SYMBOLS, now_utc=now, limits=LIMITS, max_clock_skew=SKEW
    )


def fresh_book(at: datetime = NOW) -> MarkBook:
    book = MarkBook()
    for symbol in SYMBOLS:
        book.store(mark(symbol, at))
    return book


# --------------------------------------------------------------------------- #
# User-data liveness.
# --------------------------------------------------------------------------- #


def test_a_quiet_account_with_recent_pongs_is_not_stale() -> None:
    snap = snapshot(event=NOW - timedelta(hours=1), pong=NOW - SILENCE / 2, since=LONG_AGO)
    verdict = judge(source(snap, fresh_book()))
    assert verdict.user_data_silent is False
    assert verdict.any_stale is False


def test_the_newest_of_event_ping_and_pong_is_the_liveness_time() -> None:
    snap = snapshot(
        event=NOW - timedelta(minutes=30),
        ping=NOW - timedelta(seconds=1),
        pong=NOW - timedelta(minutes=5),
    )
    assert source(snap, fresh_book()).user_data_liveness() == NOW - timedelta(seconds=1)


def test_silence_beyond_the_limit_is_stale_even_when_the_stream_says_live() -> None:
    old = NOW - SILENCE - timedelta(seconds=1)
    snap = snapshot(event=old, ping=old, pong=old, since=old)
    verdict = judge(source(snap, fresh_book()))
    assert verdict.user_data_silent is True
    assert verdict.any_stale is True


def test_no_signal_at_all_is_stale_and_a_fresh_live_entry_is_not() -> None:
    not_live = snapshot(state=StreamState.UNKNOWN, since=NOW)
    assert source(not_live, fresh_book()).user_data_liveness() is None
    assert judge(source(not_live, fresh_book())).user_data_silent is True
    just_live = snapshot(state=StreamState.LIVE, since=NOW - timedelta(seconds=2))
    assert judge(source(just_live, fresh_book())).user_data_silent is False


def test_a_liveness_time_in_the_future_beyond_the_skew_is_stale() -> None:
    snap = snapshot(pong=NOW + SKEW + timedelta(seconds=30))
    assert judge(source(snap, fresh_book())).user_data_silent is True


# --------------------------------------------------------------------------- #
# Mark readings.
# --------------------------------------------------------------------------- #


async def test_refresh_makes_one_call_per_symbol_and_marks_are_fresh() -> None:
    book = MarkBook()
    reader = FakeReader(NOW)
    stored = await refresh_marks(reader=reader, marks=book, symbols=[*SYMBOLS, "BTCUSDT"])
    assert stored == 2
    assert reader.calls == list(SYMBOLS)
    assert judge(source(snapshot(pong=NOW), book)).stale_symbols == ()


async def test_a_refresh_failing_longer_than_the_limit_makes_the_mark_stale_but_never_raises() -> (
    None
):
    book = fresh_book(NOW - timedelta(seconds=1))
    reader = FakeReader(NOW, failing={"ETHUSDT"})
    later = NOW + MARK_AGE
    stored = await refresh_marks(reader=reader, marks=book, symbols=SYMBOLS)
    assert stored == 1
    assert book.last_failure("ETHUSDT") == "TimeoutError"
    src = source(snapshot(pong=later), book)
    assert judge(src, later).stale_symbols == ("ETHUSDT",)
    # a good refresh later clears the failure
    await refresh_marks(reader=FakeReader(later), marks=book, symbols=SYMBOLS)
    assert book.last_failure("ETHUSDT") is None
    assert judge(src, later).stale_symbols == ()


async def test_a_mark_that_was_never_read_is_stale() -> None:
    book = MarkBook()
    assert judge(source(snapshot(pong=NOW), book)).stale_symbols == SYMBOLS


def test_a_mark_time_in_the_future_beyond_the_skew_is_stale() -> None:
    book = fresh_book(NOW + SKEW + timedelta(seconds=30))
    assert judge(source(snapshot(pong=NOW), book)).stale_symbols == SYMBOLS


async def test_cancellation_is_not_swallowed() -> None:
    import asyncio

    class Cancelling:
        async def mark_price(self, symbol: str) -> MarkPriceReading:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await refresh_marks(reader=Cancelling(), marks=MarkBook(), symbols=SYMBOLS)


# --------------------------------------------------------------------------- #
# Stream divergence queue.
# --------------------------------------------------------------------------- #


def divergence(
    *, kind: StreamDivergenceKind = StreamDivergenceKind.STREAM_ANOMALY, anomaly: str | None = None
) -> StreamDivergence:
    return StreamDivergence(
        kind=kind,
        symbol="BTCUSDT",
        client_order_id=None,
        client_algo_id=None,
        reason="fixed project text",
        anomaly_kind=anomaly,
        payload_sha256=None,
        after_gap=False,
    )


def test_items_drain_once_in_arrival_order() -> None:
    queue = StreamDivergenceQueue(max_items=10)
    first = divergence(anomaly="UNKNOWN_EVENT_TYPE")
    second = divergence(kind=StreamDivergenceKind.UNKNOWN_STREAM_ORDER)
    queue.sink(first)
    queue.sink(second)
    assert len(queue) == 2
    assert list(queue.drain()) == [first, second]
    assert queue.drain() == ()


def test_the_halt_reason_follows_the_supervisor_callbacks() -> None:
    queue = StreamDivergenceQueue(max_items=10)
    assert queue.halted_reason() is None
    queue.note_failure("TASK_DIED")
    queue.note_state(StreamState.UNKNOWN, "TASK_DIED")
    assert queue.halted_reason() == "TASK_DIED"
    queue.note_state(StreamState.LIVE, "SNAPSHOT_OK")
    assert queue.halted_reason() is None


def test_an_overflow_is_reported_once_and_halts_for_good() -> None:
    calls: list[int] = []
    queue = StreamDivergenceQueue(max_items=1, on_overflow=lambda: calls.append(1))
    queue.sink(divergence())
    queue.sink(divergence())
    queue.sink(divergence())
    assert calls == [1]
    assert len(queue) == 1
    assert queue.halted_reason() == REASON_DIVERGENCE_QUEUE_OVERFLOW
    queue.drain()
    queue.note_state(StreamState.LIVE, "SNAPSHOT_OK")
    assert queue.halted_reason() == REASON_DIVERGENCE_QUEUE_OVERFLOW


def test_a_failing_overflow_callback_does_not_hide_the_halt() -> None:
    def boom() -> None:
        raise RuntimeError("TEST_ONLY")

    queue = StreamDivergenceQueue(max_items=1, on_overflow=boom)
    queue.sink(divergence())
    queue.sink(divergence())
    assert queue.halted_reason() == REASON_DIVERGENCE_QUEUE_OVERFLOW


@pytest.mark.parametrize("bad", [0, -1, True, 1.5])
def test_max_items_must_be_a_positive_int(bad: object) -> None:
    with pytest.raises(ValueError):
        StreamDivergenceQueue(max_items=bad)  # type: ignore[arg-type]


async def test_synthetic_trigger_reject_reaches_safe_mode_through_the_loop() -> None:
    """SYNTHETIC CONDITIONAL_ORDER_TRIGGER_REJECT -> real router -> queue -> loop tick."""
    queue = StreamDivergenceQueue(max_items=10)
    sinks = RecordingSinks()
    router = make_router(
        lookup=FakeOrderLookup.of(
            orders=[
                KnownOrder(
                    local_order_id="x",
                    client_id="x",
                    symbol="BTCUSDT",
                    role=OrderRole.ENTRY,
                    local_status=OrderStatus.NEW,
                )
            ]
        ),
        journal=RecordingJournal(),
        sinks=sinks,
        clock=lambda: NOW,
        overrides={"divergence_sink": queue.sink},
    )
    outcome = parse_stream_message(conditional_order_trigger_reject_frame(), observed_at_utc=NOW)

    class Item:
        def __init__(self) -> None:
            self.outcome = outcome
            self.received_at_utc = NOW
            self.after_gap = False

    result = router.route(Item())
    assert result.divergences == 1
    assert len(queue) == 1
    assert queue.escalated == 1

    rig = build_rig(stream=queue)
    report = await rig.loop.tick(now_utc=NOW)

    assert [d.kind for d in report.divergences] == ["STREAM_SINK_FAILURE"]
    assert rig.safe_mode.enter_calls == ["STREAM_SINK_FAILURE"]
    assert queue.drain() == ()


def test_a_plain_anomaly_is_queued_unchanged_and_a_rejected_stop_is_relabelled() -> None:
    queue = StreamDivergenceQueue(max_items=10)
    plain = divergence(anomaly="UNKNOWN_EVENT_TYPE")
    rejected = divergence(anomaly="DEPRECATED_EVENT")
    queue.sink(plain)
    queue.sink(rejected)
    first, second = queue.drain()
    assert first == plain
    assert second.kind is StreamDivergenceKind.SINK_FAILURE
    assert second.reason == ESCALATED_REASON
    assert second.anomaly_kind == "DEPRECATED_EVENT"
    assert second.symbol == "BTCUSDT"
    assert queue.escalated == 1


async def test_a_halted_queue_enters_safe_mode_through_the_loop() -> None:
    queue = StreamDivergenceQueue(max_items=10)
    queue.note_failure("TASK_DIED")
    rig = build_rig(stream=queue)
    report = await rig.loop.tick(now_utc=NOW)
    assert [d.kind for d in report.divergences] == ["STREAM_TASK_DIED"]
    assert rig.safe_mode.enter_calls == ["USER_DATA_STREAM_HALTED"]


async def test_the_loop_judges_a_dead_feed_through_the_live_feed_source() -> None:
    """The existing `assess_feeds` path: a dead connection enters SAFE_MODE STALE_FEED."""
    old = NOW - SILENCE - timedelta(seconds=5)
    src = source(snapshot(event=old, ping=old, pong=old, since=old), fresh_book(NOW))
    rig = build_rig(feed=src)  # type: ignore[arg-type]
    report = await rig.loop.tick(now_utc=NOW)
    assert report.user_data_silent is True
    assert rig.safe_mode.enter_calls == ["STALE_FEED"]
