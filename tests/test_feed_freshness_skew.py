"""A feed time ahead of now is bounded by the ratified drift, else stale (plan 20-30, WR-B6).

`assess_feeds` used to read `now - seen > limit` only, so a time in the future (a unit bug, a wrong
time zone, a clock that jumped) was fresh without bound and stale-feed detection was off for good.
Now a time ahead of `now_utc` by more than `max_clock_skew` is unreadable, hence stale. The bound
is the already ratified drift (`config/binance/binance-limits-v1.toml [drift]`, the same margin
the pre-placement check uses); no number is added. No bound given means no allowance at all.

Evidence label: executed unit tests with fakes; nothing is a Demo observation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from src.reconcile.feed_freshness import FeedReading, FeedVerdict, assess_feeds
from src.reconcile.loop import TICK_COMPARED

from tests.support.execution_limits import test_only_execution_limits as make_test_limits
from tests.support.reconcile_rig import NOW, FakeFeedSource, build_rig
from tests.test_feed_freshness import protected_btc_rig_kwargs

LIMITS_FILE = Path(__file__).parent.parent / "config" / "binance" / "binance-limits-v1.toml"
SKEW = timedelta(seconds=1)
EPS = timedelta(microseconds=1)
FAR_FUTURE = datetime(2100, 1, 1, tzinfo=UTC)


def reading(*, btc: datetime | None, user: datetime | None) -> FeedReading:
    return FeedReading(mark_price_at_utc={"BTCUSDT": btc}, user_data_last_event_at_utc=user)


def assess(feed: FeedReading, **kwargs: Any) -> FeedVerdict:
    return assess_feeds(
        feed, symbols=("BTCUSDT",), now_utc=NOW, limits=make_test_limits(), **kwargs
    )


def test_a_time_ahead_by_exactly_the_bound_is_fresh() -> None:
    ahead = NOW + SKEW
    verdict = assess(reading(btc=ahead, user=ahead), max_clock_skew=SKEW)
    assert verdict == FeedVerdict(stale_symbols=(), user_data_silent=False)


def test_a_mark_time_ahead_by_more_than_the_bound_is_stale() -> None:
    verdict = assess(reading(btc=NOW + SKEW + EPS, user=NOW), max_clock_skew=SKEW)
    assert verdict.stale_symbols == ("BTCUSDT",)
    assert verdict.user_data_silent is False


def test_a_user_data_time_ahead_by_more_than_the_bound_is_silent() -> None:
    verdict = assess(reading(btc=NOW, user=NOW + SKEW + EPS), max_clock_skew=SKEW)
    assert verdict.stale_symbols == ()
    assert verdict.user_data_silent is True


def test_the_year_2100_case_of_the_review_is_stale_not_fresh() -> None:
    verdict = assess(reading(btc=FAR_FUTURE, user=FAR_FUTURE), max_clock_skew=SKEW)
    assert verdict == FeedVerdict(stale_symbols=("BTCUSDT",), user_data_silent=True)


def test_no_bound_means_no_allowance_a_time_ahead_by_one_microsecond_is_stale() -> None:
    ahead = NOW + EPS
    verdict = assess(reading(btc=ahead, user=ahead))
    assert verdict == FeedVerdict(stale_symbols=("BTCUSDT",), user_data_silent=True)
    explicit_none = assess(reading(btc=ahead, user=ahead), max_clock_skew=None)
    assert explicit_none == verdict


def test_a_time_equal_to_now_is_fresh_with_or_without_a_bound() -> None:
    fresh = FeedVerdict(stale_symbols=(), user_data_silent=False)
    assert assess(reading(btc=NOW, user=NOW)) == fresh
    assert assess(reading(btc=NOW, user=NOW), max_clock_skew=SKEW) == fresh


def test_the_bound_never_loosens_the_age_rule() -> None:
    # 3579 ms is the TEST_ONLY mark limit; older than that is stale whatever the skew bound is.
    old = NOW - timedelta(milliseconds=3579 + 1)
    assert assess(reading(btc=old, user=NOW), max_clock_skew=SKEW).stale_symbols == ("BTCUSDT",)


@pytest.mark.parametrize("bad", [-1, 1.0, True, "1s", timedelta(seconds=-1)])
def test_a_bound_that_is_not_a_non_negative_timedelta_is_refused(bad: object) -> None:
    with pytest.raises(ValueError, match="max_clock_skew"):
        assess(reading(btc=NOW, user=NOW), max_clock_skew=bad)


def test_the_helper_turns_the_ratified_drift_limits_into_the_bound() -> None:
    from src.adapters.binance_limits import load_binance_limits
    from src.reconcile.feed_freshness import clock_skew_from_drift

    drift = load_binance_limits(LIMITS_FILE).drift
    assert clock_skew_from_drift(drift) == timedelta(
        milliseconds=max(drift.ahead_limit_ms, drift.behind_limit_ms)
    )
    assert clock_skew_from_drift(drift) > timedelta(0)


# --------------------------------------------------------------------------- #
# The loop: a future feed time enters SAFE_MODE STALE_FEED (fail closed).
# --------------------------------------------------------------------------- #


async def test_the_loop_treats_a_far_future_user_data_time_as_silent() -> None:
    feed = FakeFeedSource(reading(btc=NOW, user=FAR_FUTURE))
    rig = build_rig(feed=feed, feed_clock_skew=SKEW, **protected_btc_rig_kwargs())

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_COMPARED
    assert report.user_data_silent is True
    assert rig.safe_mode.in_safe_mode is True
    assert rig.safe_mode.entered_reason == "STALE_FEED"
    assert [(a.event, a.reason) for a in rig.alerts.alerts] == [("STALE_DATA", "USER_DATA_SILENT")]


async def test_the_loop_without_a_bound_treats_any_future_mark_time_as_stale() -> None:
    feed = FakeFeedSource(reading(btc=NOW + EPS, user=NOW))
    rig = build_rig(feed=feed, **protected_btc_rig_kwargs())

    report = await rig.loop.tick(now_utc=NOW)

    assert report.stale_symbols == ("BTCUSDT",)
    assert rig.safe_mode.entered_reason == "STALE_FEED"


async def test_the_loop_with_a_bound_accepts_a_time_within_it() -> None:
    ahead = NOW + SKEW
    feed = FakeFeedSource(reading(btc=ahead, user=ahead))
    rig = build_rig(feed=feed, feed_clock_skew=SKEW, **protected_btc_rig_kwargs())

    report = await rig.loop.tick(now_utc=NOW)

    assert report.stale_symbols == ()
    assert report.user_data_silent is False
    assert rig.safe_mode.in_safe_mode is False
    assert rig.alerts.alerts == []


@pytest.mark.parametrize("bad", [-1, True, timedelta(seconds=-1)])
def test_the_loop_refuses_a_bound_that_is_not_a_non_negative_timedelta(bad: object) -> None:
    with pytest.raises(ValueError, match="feed_clock_skew"):
        build_rig(feed=FakeFeedSource(reading(btc=NOW, user=NOW)), feed_clock_skew=bad)
