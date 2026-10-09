"""Live 1m trade and mark minutes from the public REST adapter (Phase 16, plan 16-19, D-14).

`LiveMinuteSource` is an append-only in-memory `MinuteSource` validated by
`validate_minute_series`; `LiveMinutePoller` fills it from `klines` and `mark_klines` of the
public adapter. The poll cadence and the minute close lag are timing numbers owned by the user
(O-07) and are required inputs with no default. The adapter is a fake: no network is touched and
no wall clock is read (the poller takes `now_utc` and, for `run`, a clock callable).
"""

from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_public import Kline, MarkKline
from src.backtest.case import parse_case_input
from src.backtest.engine import simulate
from src.backtest.series import MinuteSeriesError, parse_minute_row
from src.core.types import Candle
from src.paper.live_minutes import (
    LiveMinutePoller,
    LiveMinutePollError,
    LiveMinuteSource,
    PollResult,
)

from tests.backtest_case_helpers import DATA_END, SIGNAL_CLOSE, fixed_risk_fn
from tests.backtest_case_helpers import at as case_at
from tests.test_backtest_engine import tracer_case
from tests.test_paper_shadow_fill import (
    QUANTITY,
    REALIZED_RISK,
    _driver,
    _funding,
    _outcome,
)

LIVE_MINUTES_PATH = Path(__file__).resolve().parent.parent / "src" / "paper" / "live_minutes.py"
SYMBOL = "BTCUSDT"
MINUTE = timedelta(minutes=1)
LAG = 5
FIRST_OPEN = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 1, 5, hour, minute, second, tzinfo=UTC)


def close_of(opened: datetime) -> datetime:
    return opened + timedelta(seconds=59, milliseconds=999)


def candle(
    opened: datetime, *, kind: str = "trade", price: str = "100", symbol: str = SYMBOL
) -> Candle:
    value = Decimal(price)
    return Candle(
        symbol=symbol,
        interval="1m",
        open_time_utc=opened,
        close_time_utc=close_of(opened),
        open=value,
        high=value + Decimal("1"),
        low=value - Decimal("1"),
        close=value,
        volume=Decimal("1") if kind == "trade" else Decimal("0"),
    )


def ms(value: datetime) -> int:
    return (value - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(milliseconds=1)


# --------------------------------------------------------------------------- #
# LiveMinuteSource
# --------------------------------------------------------------------------- #


def test_minutes_are_selected_by_close_time_in_the_half_open_window() -> None:
    source = LiveMinuteSource()
    minutes = [candle(at(10, m)) for m in range(5)]
    source.append(SYMBOL, "trade", minutes, closed_through_utc=at(10, 5))
    source.append(
        SYMBOL,
        "mark",
        [candle(at(10, m), kind="mark") for m in range(5)],
        closed_through_utc=at(10, 5),
    )

    # (10:01:00, 10:03:59.999] contains the minutes opening 10:01, 10:02 and 10:03 only.
    window = source.trade_minutes(SYMBOL, at(10, 1), close_of(at(10, 3)))
    assert [c.open_time_utc for c in window] == [at(10, 1), at(10, 2), at(10, 3)]
    window = source.mark_minutes(SYMBOL, close_of(at(10, 1)), close_of(at(10, 3)))
    assert [c.open_time_utc for c in window] == [at(10, 2), at(10, 3)]


def test_a_symbol_without_a_series_is_a_data_error_not_an_empty_window() -> None:
    source = LiveMinuteSource()
    with pytest.raises(MinuteSeriesError):
        source.trade_minutes(SYMBOL, at(10), at(11))
    with pytest.raises(MinuteSeriesError):
        source.mark_minutes(SYMBOL, at(10), at(11))


def test_a_forming_minute_is_rejected() -> None:
    source = LiveMinuteSource()
    forming = candle(at(10, 3))
    with pytest.raises(MinuteSeriesError, match="forming|closed"):
        source.append(SYMBOL, "trade", [forming], closed_through_utc=at(10, 3, 30))
    # Nothing was stored.
    assert source.last_open_utc(SYMBOL, "trade") is None


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param([candle(at(10, 1)), candle(at(10, 1))], id="duplicate-open"),
        pytest.param([candle(at(10, 2)), candle(at(10, 1))], id="decreasing"),
        pytest.param([candle(at(10, 1, 30))], id="misaligned"),
        pytest.param([candle(at(10, 1), symbol="ETHUSDT")], id="wrong-symbol"),
    ],
)
def test_every_batch_is_validated_with_the_minute_series_rules(bad: list[Candle]) -> None:
    source = LiveMinuteSource()
    with pytest.raises(MinuteSeriesError):
        source.append(SYMBOL, "trade", bad, closed_through_utc=at(11))
    assert source.last_open_utc(SYMBOL, "trade") is None


def test_a_batch_that_overlaps_the_stored_series_is_rejected_unless_it_replays_it_exactly() -> None:
    source = LiveMinuteSource()
    first = [candle(at(10, 0)), candle(at(10, 1))]
    source.append(SYMBOL, "trade", first, closed_through_utc=at(10, 5))
    # An identical re-delivery is a no-op.
    source.append(SYMBOL, "trade", first, closed_through_utc=at(10, 5))
    assert [c.open_time_utc for c in source.trade_minutes(SYMBOL, at(9), at(11))] == [
        at(10, 0),
        at(10, 1),
    ]
    # The same minute with other prices is evidence tampering: refused, stored value kept.
    with pytest.raises(MinuteSeriesError, match="differs"):
        source.append(
            SYMBOL, "trade", [candle(at(10, 1), price="105")], closed_through_utc=at(10, 5)
        )
    assert source.trade_minutes(SYMBOL, at(10, 0), at(11))[-1].close == Decimal("100")


def test_a_missing_minute_stays_a_hole() -> None:
    source = LiveMinuteSource()
    source.append(
        SYMBOL, "trade", [candle(at(10, 0)), candle(at(10, 2))], closed_through_utc=at(10, 5)
    )
    opens = [c.open_time_utc for c in source.trade_minutes(SYMBOL, at(9), at(11))]
    assert opens == [at(10, 0), at(10, 2)]  # no 10:01 padded in


def test_a_mark_hole_inside_a_position_is_annotated_by_the_lifecycle() -> None:
    """The source does not fill the hole; the Phase 14 lifecycle annotates it in coverage_note."""
    case = tracer_case()
    parsed = parse_case_input(case)
    expected = simulate(case, risk_fn=fixed_risk_fn(QUANTITY, REALIZED_RISK))
    trade = [parse_minute_row(r, kind="trade") for r in case["trade_bars_1m"]]
    mark = [
        parse_minute_row(r, kind="mark")
        for r in case["mark_bars_1m"]
        if parse_minute_row(r, kind="mark").open_time_utc != case_at(10, 10)
    ]
    source = LiveMinuteSource()
    source.append(SYMBOL, "trade", trade, closed_through_utc=DATA_END)
    source.append(SYMBOL, "mark", mark, closed_through_utc=DATA_END)

    driver = _driver(parsed, expected)
    driver.open(_outcome(parsed), eligibility_start_utc=SIGNAL_CLOSE)
    driver.advance_to(DATA_END, source, funding=_funding(parsed))

    note = driver.trade_record().coverage_note
    assert note is not None and "10:10" in note


# --------------------------------------------------------------------------- #
# LiveMinutePoller
# --------------------------------------------------------------------------- #


class FakeFeed:
    """A public-adapter stand-in: serves prepared minutes, records every request."""

    def __init__(self, *, first: datetime = FIRST_OPEN, count: int = 20) -> None:
        self.trade_rows = [
            Kline(
                symbol=SYMBOL,
                interval="1m",
                open_time_utc=first + MINUTE * i,
                close_time_utc=close_of(first + MINUTE * i),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
                volume=Decimal("1"),
                quote_volume=Decimal("100"),
                trade_count=3,
            )
            for i in range(count)
        ]
        self.mark_rows = [
            MarkKline(
                symbol=SYMBOL,
                interval="1m",
                open_time_utc=first + MINUTE * i,
                close_time_utc=close_of(first + MINUTE * i),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
                price_tick_count=5,
            )
            for i in range(count)
        ]
        self.calls: list[tuple[str, str, int | None, int | None, int]] = []
        self.fail_next: list[BaseException] = []

    def _page(
        self, rows: list[Any], start_ms: int | None, end_ms: int | None, limit: int
    ) -> list[Any]:
        picked = [
            r
            for r in rows
            if (start_ms is None or ms(r.open_time_utc) >= start_ms)
            and (end_ms is None or ms(r.open_time_utc) <= end_ms)
        ]
        return picked[:limit]

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]:
        self.calls.append(("klines", interval, start_ms, end_ms, limit))
        if self.fail_next:
            raise self.fail_next.pop(0)
        return self._page(self.trade_rows, start_ms, end_ms, limit)

    async def mark_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[MarkKline]:
        self.calls.append(("mark_klines", interval, start_ms, end_ms, limit))
        return self._page(self.mark_rows, start_ms, end_ms, limit)


def _poller(feed: FakeFeed, source: LiveMinuteSource, **overrides: Any) -> LiveMinutePoller:
    arguments: dict[str, Any] = {
        "feed": feed,
        "source": source,
        "poll_interval_seconds": 30,
        "close_lag_seconds": LAG,
    }
    arguments.update(overrides)
    return LiveMinutePoller(**arguments)


def test_the_cadence_and_the_close_lag_are_required_with_no_default() -> None:
    feed, source = FakeFeed(), LiveMinuteSource()
    with pytest.raises(TypeError):
        LiveMinutePoller(feed=feed, source=source, close_lag_seconds=LAG)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        LiveMinutePoller(feed=feed, source=source, poll_interval_seconds=30)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        LiveMinutePoller(feed=feed, source=source)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        LiveMinutePoller(feed, source, 30, LAG)  # type: ignore[misc]


@pytest.mark.parametrize("bad", [0, -1])
def test_a_non_positive_cadence_or_lag_is_refused(bad: int) -> None:
    feed, source = FakeFeed(), LiveMinuteSource()
    with pytest.raises(ValueError, match="poll_interval_seconds"):
        _poller(feed, source, poll_interval_seconds=bad)
    with pytest.raises(ValueError, match="close_lag_seconds"):
        _poller(feed, source, close_lag_seconds=bad)


def test_only_minutes_closed_before_now_minus_the_lag_are_stored() -> None:
    async def scenario() -> None:
        feed, source = FakeFeed(), LiveMinuteSource()
        poller = _poller(feed, source)
        # now - lag is exactly the close of the 10:04 minute, so that minute is the last stored.
        now = close_of(at(10, 4)) + timedelta(seconds=LAG)
        result = await poller.poll_once(SYMBOL, now_utc=now, since_utc=at(10, 0))

        assert result.settled_through_utc == close_of(at(10, 4))
        trade_opens = [c.open_time_utc for c in source.trade_minutes(SYMBOL, at(9), at(11))]
        mark_opens = [c.open_time_utc for c in source.mark_minutes(SYMBOL, at(9), at(11))]
        assert trade_opens == [at(10, m) for m in range(5)]
        assert mark_opens == trade_opens
        assert (result.trade_minutes_added, result.mark_minutes_added) == (5, 5)
        assert at(10, 5) not in trade_opens

    asyncio.run(scenario())


def test_a_forming_minute_served_by_the_feed_is_dropped_not_stored() -> None:
    async def scenario() -> None:
        feed, source = FakeFeed(), LiveMinuteSource()
        # The horizon falls inside the 10:05 minute, so the feed (which bounds by OPEN time)
        # serves the forming 10:05 minute too; it must not be stored.
        now = at(10, 5, 30) + timedelta(seconds=LAG)
        result = await _poller(feed, source).poll_once(SYMBOL, now_utc=now, since_utc=at(10, 0))

        assert any(end >= ms(at(10, 5)) for _n, _i, _s, end, _l in feed.calls if end is not None)
        assert source.last_open_utc(SYMBOL, "trade") == at(10, 4)
        assert source.last_open_utc(SYMBOL, "mark") == at(10, 4)
        assert result.settled_through_utc == at(10, 5, 30)

    asyncio.run(scenario())


def test_the_next_poll_starts_after_the_last_stored_minute_and_adds_only_new_minutes() -> None:
    async def scenario() -> None:
        feed, source = FakeFeed(), LiveMinuteSource()
        poller = _poller(feed, source)
        first_now = close_of(at(10, 4)) + timedelta(seconds=LAG)
        await poller.poll_once(SYMBOL, now_utc=first_now, since_utc=at(10, 0))
        feed.calls.clear()
        second_now = close_of(at(10, 7)) + timedelta(seconds=LAG)
        result = await poller.poll_once(SYMBOL, now_utc=second_now, since_utc=at(10, 0))

        starts = {name: start for name, _i, start, _e, _l in feed.calls}
        assert starts["klines"] == ms(at(10, 5))
        assert starts["mark_klines"] == ms(at(10, 5))
        assert (result.trade_minutes_added, result.mark_minutes_added) == (3, 3)
        assert [c.open_time_utc for c in source.trade_minutes(SYMBOL, at(9), at(11))] == [
            at(10, m) for m in range(8)
        ]
        # Same instant again: nothing new, the settled watermark is unchanged.
        again = await poller.poll_once(SYMBOL, now_utc=second_now, since_utc=at(10, 0))
        assert (again.trade_minutes_added, again.mark_minutes_added) == (0, 0)
        assert again.settled_through_utc == result.settled_through_utc

    asyncio.run(scenario())


def test_the_first_poll_starts_at_since_floored_to_the_minute() -> None:
    async def scenario() -> None:
        feed, source = FakeFeed(), LiveMinuteSource()
        poller = _poller(feed, source)
        now = close_of(at(10, 4)) + timedelta(seconds=LAG)
        await poller.poll_once(SYMBOL, now_utc=now, since_utc=at(10, 2, 30))
        assert {start for _n, _i, start, _e, _l in feed.calls} == {ms(at(10, 2))}
        assert all(interval == "1m" for _n, interval, _s, _e, _l in feed.calls)

    asyncio.run(scenario())


def test_one_transient_error_is_retried_once_and_the_second_failure_propagates() -> None:
    async def scenario() -> None:
        feed, source = FakeFeed(), LiveMinuteSource()
        poller = _poller(feed, source)
        now = close_of(at(10, 4)) + timedelta(seconds=LAG)

        feed.fail_next = [TimeoutError("slow")]
        result = await poller.poll_once(SYMBOL, now_utc=now, since_utc=at(10, 0))
        assert result.trade_minutes_added == 5
        assert [name for name, *_ in feed.calls].count("klines") == 2  # failed once, retried once

        feed2, source2 = FakeFeed(), LiveMinuteSource()
        feed2.fail_next = [ConnectionError("a"), ConnectionError("b")]
        with pytest.raises(ConnectionError):
            await _poller(feed2, source2).poll_once(SYMBOL, now_utc=now, since_utc=at(10, 0))
        assert [name for name, *_ in feed2.calls].count("klines") == 2  # never a third attempt
        assert source2.last_open_utc(SYMBOL, "trade") is None

    asyncio.run(scenario())


def test_an_error_that_is_not_transient_is_not_retried() -> None:
    async def scenario() -> None:
        feed, source = FakeFeed(), LiveMinuteSource()
        feed.fail_next = [ValueError("malformed row")]
        now = close_of(at(10, 4)) + timedelta(seconds=LAG)
        with pytest.raises(ValueError, match="malformed row"):
            await _poller(feed, source).poll_once(SYMBOL, now_utc=now, since_utc=at(10, 0))
        assert [name for name, *_ in feed.calls].count("klines") == 1

    asyncio.run(scenario())


def test_a_feed_that_never_ends_a_page_fails_closed() -> None:
    async def scenario() -> None:
        feed, source = FakeFeed(count=40), LiveMinuteSource()
        poller = _poller(feed, source, page_limit=2, max_pages=3)
        now = close_of(at(10, 30)) + timedelta(seconds=LAG)
        with pytest.raises(LiveMinutePollError):
            await poller.poll_once(SYMBOL, now_utc=now, since_utc=at(10, 0))

    asyncio.run(scenario())


def test_run_polls_at_the_cadence_until_stopped_and_reports_each_settled_watermark() -> None:
    async def scenario() -> None:
        feed, source = FakeFeed(), LiveMinuteSource()
        poller = _poller(feed, source, poll_interval_seconds=1)
        stop = asyncio.Event()
        instants = iter(
            [
                close_of(at(10, 4)) + timedelta(seconds=LAG),
                close_of(at(10, 6)) + timedelta(seconds=LAG),
            ]
        )
        seen: list[PollResult] = []

        async def on_settled(result: PollResult) -> None:
            seen.append(result)
            if len(seen) == 2:
                stop.set()

        await asyncio.wait_for(
            poller.run(
                SYMBOL,
                since_utc=at(10, 0),
                clock=lambda: next(instants),
                stop=stop,
                on_settled=on_settled,
            ),
            timeout=10,
        )
        assert [r.settled_through_utc for r in seen] == [close_of(at(10, 4)), close_of(at(10, 6))]

    asyncio.run(scenario())


def test_the_module_reads_no_clock_and_has_no_float() -> None:
    tree = ast.parse(LIVE_MINUTES_PATH.read_text(encoding="utf-8"))
    called = {
        n.func.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert called.isdisjoint({"now", "utcnow", "today", "time", "monotonic", "timestamp"}), called
    assert not any(
        isinstance(n, ast.Constant) and isinstance(n.value, float) for n in ast.walk(tree)
    )
    imported = {
        alias.name.split(".")[0]
        for n in ast.walk(tree)
        if isinstance(n, ast.Import)
        for alias in n.names
    } | {
        n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module
    }
    assert (
        "binance_common" not in imported
        and "binance_sdk_derivatives_trading_usds_futures" not in imported
    )
    assert "time" not in imported
