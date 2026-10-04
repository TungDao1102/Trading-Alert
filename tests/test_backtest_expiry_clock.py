"""G3 proof: entry expiry follows the simulated minute clock (Phase 14, plan 14-02, Task 1).

Phase 6 gap G3: the v1 simulator judged expiry against one fixture `now_utc`, so a plan
whose limit was first reached long after `signal_expiry_hours` could still fill. The
lifecycle driver has no clock parameter; expiry is a function of the plan and of the
minute being examined only (D-04, D-33).

Hand oracle (LONG; zone 99.00-101.00 -> mid 100.00; tick 0.10 -> limit 100.00; a minute
fills only when its trade low is <= 99.90):
    signal close   2026-01-05T09:59:59.999Z   (end of strategy bar N, the 09:00 1h bar)
    signal_expiry_hours = 4 -> expiry_utc 13:59:59.999
    bar N+1 = 10:00-10:59, N+2 = 11:00-11:59, ..., N+4 = 13:00-13:59, N+5 = 14:00-14:59

    Plan A: first trade-through on the 11:20 minute (bar N+2, before expiry)
            -> FILL, entry_time 11:20:59.999
    Plan B: first trade-through on the 14:05 minute (bar N+5, after expiry)
            -> EXPIRED at 13:59:59.999, entry_time None, no FILL event
    Boundary: the 13:59 minute closes exactly at 13:59:59.999 -> still eligible, fills;
              the 14:00 minute closes at 14:00:59.999 -> not eligible, EXPIRED.
    Second-resolution fixtures (closes at :59 s): signal close 09:59:59, expiry 13:59:59;
              the 13:59 minute closes 13:59:59 (fills), the 14:00 minute does not.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import src.backtest.lifecycle as lifecycle
from src.backtest.lifecycle import PlanState, advance, new_plan_state
from src.backtest.series import ListMinuteSource
from src.core.types import Candle

from tests.backtest_plan_helpers import make_minute, make_trade_plan

SYMBOL = "BTCUSDT"
TICK = Decimal("0.10")
SIGNAL_CLOSE = datetime(2026, 1, 5, 9, 59, 59, 999000, tzinfo=UTC)
EXPIRY = datetime(2026, 1, 5, 13, 59, 59, 999000, tzinfo=UTC)
SIGNAL_CLOSE_S = datetime(2026, 1, 5, 9, 59, 59, tzinfo=UTC)
EXPIRY_S = datetime(2026, 1, 5, 13, 59, 59, tzinfo=UTC)


def _at(hour: int, minute: int) -> datetime:
    return datetime(2026, 1, 5, hour, minute, tzinfo=UTC)


def _flat(hour: int, minute: int, *, ms: bool = True, kind: str = "trade") -> Candle:
    """A minute that never reaches the limit 100.00 (low 100.50) nor the stop (mark low 99.00)."""
    low = "100.50" if kind == "trade" else "99.00"
    return make_minute(
        SYMBOL, _at(hour, minute), "101.00", "101.50", low, "101.00", kind, millisecond_close=ms
    )


def _through(hour: int, minute: int, *, ms: bool = True) -> Candle:
    """A trade minute with low 99.90: a one-tick trade-through of the LONG limit 100.00."""
    return make_minute(
        SYMBOL,
        _at(hour, minute),
        "100.40",
        "100.50",
        "99.90",
        "100.20",
        "trade",
        millisecond_close=ms,
    )


def _source(
    trade: list[Candle], mark_minutes: list[tuple[int, int]], *, ms: bool = True
) -> ListMinuteSource:
    return ListMinuteSource(
        trade={SYMBOL: trade},
        mark={SYMBOL: [_flat(h, m, ms=ms, kind="mark") for h, m in mark_minutes]},
    )


def _state(*, signal_close: datetime = SIGNAL_CLOSE) -> PlanState:
    plan = make_trade_plan(
        "LONG",
        entry_min="99.00",
        entry_max="101.00",
        stop_loss="98.00",
        signal_close_utc=signal_close,
        expiry_hours=4,
    )
    return new_plan_state(
        plan=plan,
        symbol=SYMBOL,
        direction="LONG",
        signal_close_utc=signal_close,
        price_tick_size=TICK,
        planned_quantity=Decimal("0.5"),
        sized_realized_risk=Decimal("1.50"),
    )


def _plan_a_source() -> ListMinuteSource:
    trade = [_flat(10, 0), _flat(11, 19), _through(11, 20), _flat(12, 0)]
    return _source(trade, [(10, 0), (11, 19), (11, 20), (12, 0)])


def _plan_b_source() -> ListMinuteSource:
    trade = [_flat(10, 0), _flat(13, 59), _flat(14, 0), _through(14, 5)]
    return _source(trade, [(10, 0), (13, 59), (14, 0), (14, 5)])


_WIDE_END = datetime(2026, 1, 5, 16, 0, 0, tzinfo=UTC)


def test_plan_a_fills_on_bar_n_plus_2_before_expiry() -> None:
    state, events = advance(
        _state(),
        source=_plan_a_source(),
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=_WIDE_END,
        bar=None,
    )
    assert state.phase == "OPEN"
    assert state.entry_price == Decimal("100.00")
    assert state.entry_time_utc == datetime(2026, 1, 5, 11, 20, 59, 999000, tzinfo=UTC)
    assert state.entry_kind == "ENTRY_FILLED"
    assert [e.kind for e in events] == ["FILL"]


def test_plan_b_expires_when_the_limit_is_first_reached_after_expiry() -> None:
    state, events = advance(
        _state(),
        source=_plan_b_source(),
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=_WIDE_END,
        bar=None,
    )
    assert state.phase == "CLOSED"
    assert state.entry_kind == "EXPIRED"
    assert state.entry_time_utc is None
    assert state.entry_price is None
    assert state.resolved_at_utc == EXPIRY  # 13:59:59.999, not the 14:05 minute, not the window end
    assert [e.kind for e in events] == ["CANCEL"]
    assert events[0].time_utc == EXPIRY
    assert events[0].entry_kind == "EXPIRED"
    assert all(e.kind != "FILL" for e in events)


def test_expiry_boundary_minute_fills_and_the_next_minute_cannot() -> None:
    # 13:59 closes exactly at expiry (13:59:59.999) -> eligible; 14:00 closes 14:00:59.999 -> not.
    last_eligible = _source([_through(13, 59)], [(13, 59)])
    filled, filled_events = advance(
        _state(),
        source=last_eligible,
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=_WIDE_END,
        bar=None,
    )
    assert filled.entry_kind == "ENTRY_FILLED"
    assert filled.entry_time_utc == EXPIRY
    assert [e.kind for e in filled_events] == ["FILL"]

    first_late = _source([_flat(13, 59), _through(14, 0)], [(13, 59), (14, 0)])
    expired, expired_events = advance(
        _state(),
        source=first_late,
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=_WIDE_END,
        bar=None,
    )
    assert expired.entry_kind == "EXPIRED"
    assert expired.entry_time_utc is None
    assert expired.resolved_at_utc == EXPIRY
    assert [e.kind for e in expired_events] == ["CANCEL"]


def test_is_minute_eligible_uses_the_minute_close_against_expiry() -> None:
    from src.backtest.entry import is_minute_eligible

    assert is_minute_eligible(minute=_flat(13, 59), expiry_utc=EXPIRY) is True
    assert is_minute_eligible(minute=_flat(14, 0), expiry_utc=EXPIRY) is False
    assert is_minute_eligible(minute=_flat(13, 58), expiry_utc=EXPIRY) is True


def test_second_resolution_closes_give_the_same_eligibility_result() -> None:
    # Phase 6 style fixtures: minutes close at :59 s. Signal close 09:59:59, expiry 13:59:59.
    fills = _source([_through(13, 59, ms=False)], [(13, 59)], ms=False)
    state, events = advance(
        _state(signal_close=SIGNAL_CLOSE_S),
        source=fills,
        start_exclusive=SIGNAL_CLOSE_S,
        end_inclusive=_WIDE_END,
        bar=None,
    )
    assert state.entry_kind == "ENTRY_FILLED"
    assert state.entry_time_utc == EXPIRY_S
    assert [e.kind for e in events] == ["FILL"]

    late = _source(
        [_flat(13, 59, ms=False), _through(14, 0, ms=False)], [(13, 59), (14, 0)], ms=False
    )
    expired, expired_events = advance(
        _state(signal_close=SIGNAL_CLOSE_S),
        source=late,
        start_exclusive=SIGNAL_CLOSE_S,
        end_inclusive=_WIDE_END,
        bar=None,
    )
    assert expired.entry_kind == "EXPIRED"
    assert expired.resolved_at_utc == EXPIRY_S
    assert [e.kind for e in expired_events] == ["CANCEL"]


def _bar_by_bar(source: ListMinuteSource, hours: list[int]) -> tuple[PlanState, tuple[object, ...]]:
    """Advance over consecutive 1h windows closing at HH:59:59.999."""
    state = _state()
    collected: list[object] = []
    previous_end = SIGNAL_CLOSE
    for hour in hours:
        window_end = datetime(2026, 1, 5, hour, 59, 59, 999000, tzinfo=UTC)
        state, events = advance(
            state,
            source=source,
            start_exclusive=previous_end,
            end_inclusive=window_end,
            bar=None,
        )
        collected.extend(events)
        previous_end = window_end
    return state, tuple(collected)


def test_advancing_bar_by_bar_equals_one_advance_over_the_whole_span_for_a_fill() -> None:
    source = _plan_a_source()
    split_state, split_events = _bar_by_bar(source, [10, 11, 12, 13])
    whole_state, whole_events = advance(
        _state(),
        source=source,
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=datetime(2026, 1, 5, 13, 59, 59, 999000, tzinfo=UTC),
        bar=None,
    )
    assert split_state == whole_state
    assert split_events == whole_events
    assert split_state.entry_kind == "ENTRY_FILLED"


def test_advancing_bar_by_bar_equals_one_advance_over_the_whole_span_for_an_expiry() -> None:
    source = _plan_b_source()
    split_state, split_events = _bar_by_bar(source, [10, 11, 12, 13, 14, 15])
    whole_state, whole_events = advance(
        _state(),
        source=source,
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=datetime(2026, 1, 5, 15, 59, 59, 999000, tzinfo=UTC),
        bar=None,
    )
    assert split_state == whole_state
    assert split_events == whole_events
    assert split_state.entry_kind == "EXPIRED"
    assert [e.kind for e in split_events] == ["CANCEL"]  # type: ignore[attr-defined]


def test_expiry_resolves_inside_the_window_that_ends_at_expiry() -> None:
    """The 13:00-13:59 window ends exactly at expiry: the plan is already EXPIRED there."""
    state, events = _bar_by_bar(_plan_b_source(), [10, 11, 12, 13])
    assert state.entry_kind == "EXPIRED"
    assert state.resolved_at_utc == EXPIRY
    assert len(events) == 1


def test_a_window_that_starts_after_expiry_cannot_fill_a_resting_plan() -> None:
    state, events = advance(
        _state(),
        source=_plan_b_source(),
        start_exclusive=EXPIRY,
        end_inclusive=_WIDE_END,
        bar=None,
    )
    assert state.entry_kind == "EXPIRED"
    assert state.entry_time_utc is None
    assert state.resolved_at_utc == EXPIRY
    assert [e.kind for e in events] == ["CANCEL"]


def test_advance_has_no_clock_parameter() -> None:
    parameters = inspect.signature(lifecycle.advance).parameters
    assert "now_utc" not in parameters
    assert not any("now" in name or "clock" in name for name in parameters)
    assert timedelta(hours=4) == EXPIRY - SIGNAL_CLOSE  # fixture sanity: signal_expiry_hours = 4
