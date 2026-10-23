"""Feed freshness tests (Phase 20, plan 20-16, EXEC-02, OPS-05, D-25, D058).

`assess_feeds` is a pure predicate over an injected reading and an injected `now_utc`; the loop
turns a stale verdict into SAFE_MODE STALE_FEED plus a STALE_DATA alert. A feed that recovers
never leaves SAFE_MODE (only the operator does, D-15), and Phase 24 owns the LIVE gate.

Evidence label: executed unit tests with fakes. The feed source is an injected double, NOT wired
to a running supervisor or mark-price reader (Phase 24); nothing is a Demo observation.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from src.domain.enums import OrderRole
from src.execution.order_ids import derive_algo_client_id
from src.reconcile.feed_freshness import FeedReading, FeedVerdict, assess_feeds
from src.reconcile.loop import (
    RECONCILE_ACTION_FAILED,
    RECONCILE_SKIPPED_GATE,
    RECONCILE_SKIPPED_RESTORE_PENDING,
    RECONCILE_TICK,
    TICK_COMPARED,
    TICK_SKIPPED_GATE,
)

from tests.support.ast_guards import (
    float_constructor_calls,
    forbidden_imports,
    module_imports,
    wall_clock_calls,
)
from tests.support.execution_limits import test_only_execution_limits as make_test_limits
from tests.support.reconcile_doubles import (
    FakeGate,
    FakeProtectionView,
    make_algo_order,
    make_plan_protection,
    make_position,
)
from tests.support.reconcile_rig import NOW, FakeFeedSource, build_rig

SRC_RECONCILE = Path(__file__).parent.parent / "src" / "reconcile"
FEED_MODULE = SRC_RECONCILE / "feed_freshness.py"
H1 = "1" * 64

# The TEST_ONLY thresholds of plan 20-01 (tests/support/execution_limits.py).
MARK_LIMIT_MS = 3579
SILENCE_LIMIT_MS = 5791


def ago(milliseconds: int) -> datetime:
    return NOW - timedelta(milliseconds=milliseconds)


def reading(
    *, btc: datetime | None, user: datetime | None, **others: datetime | None
) -> FeedReading:
    return FeedReading(
        mark_price_at_utc={"BTCUSDT": btc, **others}, user_data_last_event_at_utc=user
    )


def fresh_reading() -> FeedReading:
    return reading(btc=ago(10), user=ago(10))


# --------------------------------------------------------------------------- #
# assess_feeds: pure predicates.
# --------------------------------------------------------------------------- #


def assess(
    feed: FeedReading, *, symbols: tuple[str, ...] = ("BTCUSDT",), **overrides: int | None
) -> FeedVerdict:
    return assess_feeds(feed, symbols=symbols, now_utc=NOW, limits=make_test_limits(**overrides))


def test_a_mark_price_older_than_the_limit_is_stale() -> None:
    verdict = assess(reading(btc=ago(MARK_LIMIT_MS + 1), user=ago(1)))
    assert verdict.stale_symbols == ("BTCUSDT",)
    assert verdict.user_data_silent is False


def test_a_mark_price_exactly_at_the_limit_is_fresh() -> None:
    verdict = assess(reading(btc=ago(MARK_LIMIT_MS), user=ago(1)))
    assert verdict == FeedVerdict(stale_symbols=(), user_data_silent=False)


def test_a_mark_price_older_by_a_sub_millisecond_is_stale() -> None:
    older = NOW - timedelta(milliseconds=MARK_LIMIT_MS, microseconds=1)
    assert assess(reading(btc=older, user=ago(1))).stale_symbols == ("BTCUSDT",)


def test_a_missing_mark_time_is_stale_fail_closed() -> None:
    assert assess(reading(btc=None, user=ago(1))).stale_symbols == ("BTCUSDT",)


def test_a_symbol_absent_from_the_reading_is_stale() -> None:
    verdict = assess(reading(btc=ago(1), user=ago(1)), symbols=("BTCUSDT", "ETHUSDT"))
    assert verdict.stale_symbols == ("ETHUSDT",)


def test_only_the_asked_symbols_are_judged() -> None:
    stale_eth = reading(btc=ago(1), user=ago(1), ETHUSDT=ago(MARK_LIMIT_MS + 5000))
    assert assess(stale_eth, symbols=("BTCUSDT",)).stale_symbols == ()


def test_the_stale_symbols_are_sorted_and_unique() -> None:
    feed = reading(btc=None, user=ago(1), ETHUSDT=None)
    verdict = assess(feed, symbols=("ETHUSDT", "BTCUSDT", "ETHUSDT"))
    assert verdict.stale_symbols == ("BTCUSDT", "ETHUSDT")


def test_a_mark_time_ahead_of_now_is_stale_unless_a_skew_bound_allows_it() -> None:
    # Plan 20-30 (WR-B6): ahead of now is unreadable unless within the ratified drift bound given
    # as `max_clock_skew`; no bound means no allowance. More cases: test_feed_freshness_skew.py.
    ahead = NOW + timedelta(seconds=1)
    assert assess(reading(btc=ahead, user=ahead)).stale_symbols == ("BTCUSDT",)


def test_user_data_silence_past_the_limit_is_silent() -> None:
    assert assess(reading(btc=ago(1), user=ago(SILENCE_LIMIT_MS + 1))).user_data_silent is True


def test_user_data_exactly_at_the_limit_is_not_silent() -> None:
    assert assess(reading(btc=ago(1), user=ago(SILENCE_LIMIT_MS))).user_data_silent is False


def test_no_user_data_event_at_all_is_silent() -> None:
    assert assess(reading(btc=ago(1), user=None)).user_data_silent is True


def test_no_symbols_still_judges_the_user_data_feed() -> None:
    verdict = assess(reading(btc=None, user=None), symbols=())
    assert verdict == FeedVerdict(stale_symbols=(), user_data_silent=True)


@pytest.mark.parametrize("naive_field", ["now", "mark", "user"])
def test_a_naive_datetime_is_refused(naive_field: str) -> None:
    naive = datetime(2026, 9, 19, 0, 0)  # noqa: DTZ001 - the point of the test
    feed = reading(
        btc=naive if naive_field == "mark" else ago(1),
        user=naive if naive_field == "user" else ago(1),
    )
    now = naive if naive_field == "now" else NOW
    with pytest.raises(ValueError, match="timezone-aware"):
        assess_feeds(feed, symbols=("BTCUSDT",), now_utc=now, limits=make_test_limits())


def test_the_mark_threshold_comes_only_from_the_stale_feed_mark_field() -> None:
    feed = reading(btc=ago(2000), user=ago(1))
    assert assess(feed).stale_symbols == ()
    assert assess(feed, stale_feed_max_mark_price_age_ms=1999).stale_symbols == ("BTCUSDT",)
    # The pre-placement bound (4321 ms) is a different key and does not move this verdict.
    assert assess(feed, max_mark_price_age_ms=1).stale_symbols == ()


def test_the_silence_threshold_comes_only_from_the_stale_feed_silence_field() -> None:
    feed = reading(btc=ago(1), user=ago(3000))
    assert assess(feed).user_data_silent is False
    assert assess(feed, stale_feed_max_user_data_silence_ms=2999).user_data_silent is True


@pytest.mark.parametrize(
    "unset",
    ["stale_feed_max_mark_price_age_ms", "stale_feed_max_user_data_silence_ms"],
)
def test_an_unset_threshold_is_refused_and_never_defaulted(unset: str) -> None:
    with pytest.raises(ValueError, match="NOT_CONFIGURED"):
        assess(fresh_reading(), **{unset: None})


def test_feed_freshness_is_pure_stdlib_and_domain_only() -> None:
    imports = module_imports(FEED_MODULE)
    outside = [
        name
        for name in imports
        if name.split(".")[0] not in sys.stdlib_module_names
        and not (name == "src.domain" or name.startswith("src.domain."))
    ]
    assert outside == []
    assert forbidden_imports(FEED_MODULE, ["src.paper", "src.adapters", "src.execution"]) == []
    assert wall_clock_calls(FEED_MODULE) == []
    assert float_constructor_calls(FEED_MODULE) == []


def test_the_reconcile_package_does_not_import_the_paper_coverage_module() -> None:
    for module in SRC_RECONCILE.glob("*.py"):
        assert forbidden_imports(module, ["src.paper", "src.adapters"]) == [], module.name


# --------------------------------------------------------------------------- #
# The loop: a stale feed enters SAFE_MODE STALE_FEED and alerts STALE_DATA (tracer).
# --------------------------------------------------------------------------- #


def protected_btc_rig_kwargs() -> dict[str, Any]:
    """BTCUSDT is tracked (PROTECTED) and the exchange agrees with the coordinator."""
    return {
        "plans": (make_plan_protection(H1, symbol="BTCUSDT", state="PROTECTED"),),
        "algo": (
            make_algo_order(
                derive_algo_client_id(plan_hash=H1, role=OrderRole.STOP_LOSS.value), "BTCUSDT"
            ),
        ),
        "positions": (make_position("BTCUSDT", "0.004"),),
    }


async def test_a_stale_mark_price_for_a_tracked_symbol_enters_safe_mode_and_alerts() -> None:
    feed = FakeFeedSource(reading(btc=ago(MARK_LIMIT_MS + 1), user=ago(1)))
    rig = build_rig(feed=feed, **protected_btc_rig_kwargs())

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_COMPARED
    assert report.agreement is True
    assert report.stale_symbols == ("BTCUSDT",)
    assert report.user_data_silent is False
    assert rig.safe_mode.in_safe_mode is True
    assert rig.safe_mode.entered_reason == "STALE_FEED"
    assert [(a.event, a.subject, a.reason, a.symbol) for a in rig.alerts.alerts] == [
        ("STALE_DATA", "BTCUSDT", "MARK_PRICE_STALE", "BTCUSDT")
    ]
    assert feed.calls == 1
    # Reconciliation still ran in the same tick.
    for name in (
        "snapshot_open_normal_orders",
        "snapshot_open_algo_orders",
        "snapshot_positions",
    ):
        assert rig.adapter.count(name) == 1, name
    assert RECONCILE_TICK in rig.event_types()
    tick_payload = json.loads(rig.journal.events[-1].payload_json)
    assert tick_payload["stale_feed_symbols"] == ["BTCUSDT"]
    assert tick_payload["alerts_sent"] == 1


async def test_a_later_tick_with_fresh_feeds_does_not_exit_safe_mode() -> None:
    feed = FakeFeedSource(reading(btc=None, user=ago(1)))
    rig = build_rig(feed=feed, **protected_btc_rig_kwargs())
    await rig.loop.tick(now_utc=NOW)
    assert rig.safe_mode.in_safe_mode is True

    feed.reading = fresh_reading()
    later = await rig.loop.tick(now_utc=NOW)

    # SpyingSafeMode.exit_safe_mode raises if it is ever called.
    assert later.stale_symbols == ()
    assert rig.safe_mode.in_safe_mode is True
    assert rig.safe_mode.entered_reason == "STALE_FEED"
    assert len(rig.alerts.alerts) == 1


async def test_fresh_feeds_alone_enter_nothing_and_alert_nothing() -> None:
    rig = build_rig(feed=FakeFeedSource(fresh_reading()), **protected_btc_rig_kwargs())

    report = await rig.loop.tick(now_utc=NOW)

    assert report.stale_symbols == ()
    assert report.user_data_silent is False
    assert rig.safe_mode.enter_calls == []
    assert rig.alerts.alerts == []


async def test_user_data_silence_enters_safe_mode_and_alerts_once_for_user_data() -> None:
    feed = FakeFeedSource(reading(btc=ago(1), user=ago(SILENCE_LIMIT_MS + 1)))
    rig = build_rig(feed=feed, **protected_btc_rig_kwargs())

    report = await rig.loop.tick(now_utc=NOW)

    assert report.user_data_silent is True
    assert report.stale_symbols == ()
    assert rig.safe_mode.entered_reason == "STALE_FEED"
    assert [(a.event, a.subject, a.reason) for a in rig.alerts.alerts] == [
        ("STALE_DATA", "USER_DATA", "USER_DATA_SILENT")
    ]
    assert rig.adapter.count("snapshot_positions") == 1


async def test_only_symbols_with_a_tracked_plan_are_judged() -> None:
    flat = make_plan_protection(
        "2" * 64, symbol="ETHUSDT", state="FLAT", first_fill=True, stop_confirmed=False
    )
    kwargs = protected_btc_rig_kwargs()
    kwargs["plans"] = (*kwargs["plans"], flat)
    feed = FakeFeedSource(reading(btc=ago(1), user=ago(1), ETHUSDT=None))
    rig = build_rig(feed=feed, **kwargs)

    report = await rig.loop.tick(now_utc=NOW)

    assert report.stale_symbols == ()
    assert rig.alerts.alerts == []


async def test_a_raising_feed_source_counts_as_stale_for_every_tracked_symbol() -> None:
    secret = "token=hunter2-do-not-journal"
    feed = FakeFeedSource(fresh_reading(), raises=RuntimeError(secret))
    rig = build_rig(feed=feed, **protected_btc_rig_kwargs())

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_COMPARED
    assert report.stale_symbols == ("BTCUSDT",)
    assert report.user_data_silent is True
    assert rig.safe_mode.entered_reason == "STALE_FEED"
    assert {a.subject for a in rig.alerts.alerts} == {"BTCUSDT", "USER_DATA"}
    failed = [e for e in rig.journal.events if e.event_type == RECONCILE_ACTION_FAILED]
    assert [json.loads(e.payload_json)["action"] for e in failed] == ["feed_read"]
    assert json.loads(failed[0].payload_json)["error_type"] == "RuntimeError"
    assert all(secret not in e.payload_json for e in rig.journal.events)


async def test_a_loop_without_a_feed_source_judges_no_feed() -> None:
    rig = build_rig(feed=None, **protected_btc_rig_kwargs())

    report = await rig.loop.tick(now_utc=NOW)

    assert report.stale_symbols == ()
    assert report.user_data_silent is False
    assert rig.safe_mode.enter_calls == []


async def test_a_gate_restricted_tick_reads_no_feed() -> None:
    class Restriction:
        reason = "IP_BAN_418"
        remaining_seconds = 5

    feed = FakeFeedSource(reading(btc=None, user=None))
    rig = build_rig(feed=feed, gate=FakeGate(Restriction()), **protected_btc_rig_kwargs())

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_SKIPPED_GATE
    assert feed.calls == 0
    assert rig.event_types() == [RECONCILE_SKIPPED_GATE]


async def test_a_restore_pending_tick_reads_no_feed() -> None:
    feed = FakeFeedSource(reading(btc=None, user=None))
    rig = build_rig(feed=feed, **protected_btc_rig_kwargs())
    rig.protection.restore_complete = False

    await rig.loop.tick(now_utc=NOW)

    assert feed.calls == 0
    assert rig.event_types() == [RECONCILE_SKIPPED_RESTORE_PENDING]


async def test_a_failed_read_of_the_plans_still_judges_user_data_and_fails_closed() -> None:
    feed = FakeFeedSource(reading(btc=ago(1), user=None))
    rig = build_rig(
        feed=feed,
        protection=FakeProtectionView((), protections_raises=RuntimeError("db down")),
        **protected_btc_rig_kwargs(),
    )

    report = await rig.loop.tick(now_utc=NOW)

    assert report.user_data_silent is True
    assert "STALE_FEED" in rig.safe_mode.enter_calls
