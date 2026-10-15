"""Tracer tests for the causal backtest lifecycle (Phase 14, plan 14-01, Task 1).

One hand-built LONG plan is created at the close of strategy bar N (signal close
09:59:59.999). It rests from bar N+1, fills on a one-tick trade-through of the
tick-snapped limit on a trade-price 1m minute, exits at the stop on a mark-price
1m minute, and becomes a validated v2 TradeRecord whose realized_risk comes from
the single R-denominator function.

Every expected number below is hand-derived in the comments (standalone
arithmetic, never read from the code under test).

Hand oracle (LONG):
    entry zone 99.00 - 101.00 -> mid 100.00; tick 0.10 -> snapped limit 100.00
    stop 98.00; planned == filled quantity 0.5; sized realized risk 1.50
    trade minute 10:00 low 100.00 -> touch only (needs low <= 99.90)
    trade minute 10:01 low  99.90 -> fill at 100.00, entry_time 10:01:59.999
    mark  minute 10:01 low  97.90 -> stop on the fill minute, exit 98.00 at 10:01:59.999
    gross_pnl = (98.00 - 100.00) * 0.5 = -1.00
    entry fee      = 100.00 * 0.5 * 0.0004 = 0.0200
    exit fee       =  98.00 * 0.5 * 0.0004 = 0.0196
    entry slippage = 100.00 * 0.5 * 0.0002 = 0.0100
    exit slippage  =  98.00 * 0.5 * 0.0005 = 0.0245   (stop exit uses exit_slippage_rate)
    realized_pnl   = -1.00 - 0.0200 - 0.0196 - (0.0100 + 0.0245) + 0 = -1.0741
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from src.backtest.costs import CostModel
from src.backtest.lifecycle import PlanState, advance, new_plan_state
from src.backtest.records import build_trade_record
from src.backtest.semantics import (
    POSITION_MODE,
    SIMULATOR_SEMANTICS_VERSION,
    TP1_QUANTITY_FRACTION,
)
from src.backtest.series import ListMinuteSource
from src.backtest.validator import TradeRecordInvariantError, validate_trade_record
from src.core.types import Candle
from src.domain.trade_plan import TradePlan

from tests.backtest_plan_helpers import make_minute, make_trade_plan

SYMBOL = "BTCUSDT"
SIGNAL_CLOSE = datetime(2026, 1, 5, 9, 59, 59, 999000, tzinfo=UTC)  # same as the helper default
TICK = Decimal("0.10")


def D(text: str) -> Decimal:  # noqa: N802 - terse fixture helper
    return Decimal(text)


def _plan(direction: str) -> TradePlan:
    """Hand-built plan: zone 99-101 (mid 100.00); LONG stop 98.00, SHORT stop 102.00."""
    stop = "98.00" if direction == "LONG" else "102.00"
    return make_trade_plan(
        direction,
        entry_min="99.00",
        entry_max="101.00",
        stop_loss=stop,
        signal_close_utc=SIGNAL_CLOSE,
        trade_plan_id="tp-tracer",
        signal_id="sig-tracer",
    )


def _minute(
    open_hm: tuple[int, int],
    *,
    o: str,
    h: str,
    low: str,
    c: str,
    kind: str = "trade",
) -> Candle:
    return make_minute(
        SYMBOL, datetime(2026, 1, 5, open_hm[0], open_hm[1], tzinfo=UTC), o, h, low, c, kind
    )


def _long_trade_minutes(*, with_signal_bar: bool) -> list[Candle]:
    rows: list[Candle] = []
    if with_signal_bar:
        # Inside the signal bar: far below the limit AND the stop. Must never be read.
        rows.append(_minute((9, 30), o="95.00", h="100.00", low="90.00", c="95.00"))
        rows.append(_minute((9, 59), o="95.00", h="100.00", low="90.00", c="95.00"))
    rows.extend(
        [
            _minute((10, 0), o="100.50", h="100.80", low="100.00", c="100.40"),
            _minute((10, 1), o="100.40", h="100.50", low="99.90", c="100.20"),
            _minute((10, 2), o="101.00", h="101.50", low="100.90", c="101.20"),
        ]
    )
    return rows


def _long_mark_minutes(*, with_signal_bar: bool) -> list[Candle]:
    rows: list[Candle] = []
    if with_signal_bar:
        rows.append(_minute((9, 30), o="95.00", h="100.00", low="90.00", c="95.00", kind="mark"))
        rows.append(_minute((9, 59), o="95.00", h="100.00", low="90.00", c="95.00", kind="mark"))
    rows.extend(
        [
            _minute((10, 0), o="100.50", h="100.80", low="99.00", c="100.40", kind="mark"),
            _minute((10, 1), o="100.10", h="100.30", low="97.90", c="98.50", kind="mark"),
            _minute((10, 2), o="98.50", h="99.00", low="97.00", c="97.50", kind="mark"),
        ]
    )
    return rows


def _source(*, with_signal_bar: bool) -> ListMinuteSource:
    return ListMinuteSource(
        trade={SYMBOL: _long_trade_minutes(with_signal_bar=with_signal_bar)},
        mark={SYMBOL: _long_mark_minutes(with_signal_bar=with_signal_bar)},
    )


def _long_state() -> PlanState:
    return new_plan_state(
        plan=_plan("LONG"),
        symbol=SYMBOL,
        direction="LONG",
        signal_close_utc=SIGNAL_CLOSE,
        price_tick_size=TICK,
        planned_quantity=D("0.5"),
        sized_realized_risk=D("1.50"),
    )


WINDOW_END = datetime(2026, 1, 5, 10, 5, 59, 999000, tzinfo=UTC)


def _cost_model() -> CostModel:
    return CostModel(
        fee_rate_entry=D("0.0004"),
        fee_rate_exit=D("0.0004"),
        funding_treatment="ADDITIVE",
        expected_slippage=D("0.0002"),
        slippage_model="FIXED_RATE",
        spread_fill_assumptions="TAKER",
        partial_fill_fraction=D("1"),
        cost_model_hash="",
        exit_slippage_rate=D("0.0005"),
    )


def test_phase_constants_pin_the_user_resolved_tp1_policy() -> None:
    assert Decimal("0.5") == TP1_QUANTITY_FRACTION
    assert SIMULATOR_SEMANTICS_VERSION == "2.1.0"
    assert POSITION_MODE == "ONE_WAY"


def test_tracer_touch_then_trade_through_fill_then_mark_stop_on_fill_minute() -> None:
    state, events = advance(
        _long_state(),
        source=_source(with_signal_bar=False),
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=WINDOW_END,
        bar=None,
    )

    assert state.limit_price == D("100.00")
    assert state.touch_no_fill_count == 1  # 10:00 low 100.00 touched but did not trade through
    assert state.entry_price == D("100.00")
    assert state.entry_time_utc == datetime(2026, 1, 5, 10, 1, 59, 999000, tzinfo=UTC)
    assert state.phase == "CLOSED"
    assert state.exit_kind == "SL"
    assert state.exit_price == D("98.00")
    assert state.exit_time_utc == state.entry_time_utc  # fill minute: only the stop may trigger
    assert [e.kind for e in events] == ["FILL", "EXIT"]
    assert events[0].price == D("100.00")
    assert events[0].entry_kind == "ENTRY_FILLED"
    assert events[1].exit_kind == "SL"


def test_touch_only_minute_does_not_fill() -> None:
    only_touch = ListMinuteSource(
        trade={SYMBOL: [_minute((10, 0), o="100.50", h="100.80", low="100.00", c="100.40")]},
        mark={
            SYMBOL: [_minute((10, 0), o="100.50", h="100.80", low="99.00", c="100.40", kind="mark")]
        },
    )
    state, events = advance(
        _long_state(),
        source=only_touch,
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=WINDOW_END,
        bar=None,
    )
    assert state.phase == "RESTING"
    assert state.touch_no_fill_count == 1
    assert state.entry_price is None
    assert events == ()


def test_minutes_at_or_before_the_signal_close_are_never_examined() -> None:
    """Signal-bar minutes (low 90 << limit and stop) must not change the result."""
    with_bar, events_with = advance(
        _long_state(),
        source=_source(with_signal_bar=True),
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=WINDOW_END,
        bar=None,
    )
    without_bar, events_without = advance(
        _long_state(),
        source=_source(with_signal_bar=False),
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=WINDOW_END,
        bar=None,
    )
    assert with_bar == without_bar
    assert events_with == events_without

    # A caller that passes a start BEFORE the signal close is clamped to the signal close.
    clamped, events_clamped = advance(
        _long_state(),
        source=_source(with_signal_bar=True),
        start_exclusive=SIGNAL_CLOSE - timedelta(hours=1),
        end_inclusive=WINDOW_END,
        bar=None,
    )
    assert clamped == without_bar
    assert events_clamped == events_without
    assert clamped.entry_time_utc is not None and clamped.entry_time_utc > SIGNAL_CLOSE


def test_advance_is_pure_same_input_same_output() -> None:
    first = advance(
        _long_state(),
        source=_source(with_signal_bar=False),
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=WINDOW_END,
        bar=None,
    )
    second = advance(
        _long_state(),
        source=_source(with_signal_bar=False),
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=WINDOW_END,
        bar=None,
    )
    assert first == second


def test_short_mirror_fills_on_high_trade_through_and_stops_on_mark_high() -> None:
    # SHORT: mid 100.00, entry rounding UP keeps 100.00; fill needs high >= 100.10;
    # stop 102.00 is touched by a mark high >= 102.00.
    source = ListMinuteSource(
        trade={
            SYMBOL: [
                _minute((10, 0), o="99.50", h="100.00", low="99.40", c="99.80"),
                _minute((10, 1), o="99.80", h="100.10", low="99.70", c="100.00"),
            ]
        },
        mark={
            SYMBOL: [
                _minute((10, 0), o="99.50", h="100.00", low="99.40", c="99.80", kind="mark"),
                _minute((10, 1), o="99.80", h="102.10", low="99.70", c="101.00", kind="mark"),
            ]
        },
    )
    state = new_plan_state(
        plan=_plan("SHORT"),
        symbol=SYMBOL,
        direction="SHORT",
        signal_close_utc=SIGNAL_CLOSE,
        price_tick_size=TICK,
        planned_quantity=D("0.5"),
        sized_realized_risk=D("1.50"),
    )
    final, events = advance(
        state,
        source=source,
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=WINDOW_END,
        bar=None,
    )
    assert final.touch_no_fill_count == 1  # 10:00 high 100.00 touches the limit, no trade-through
    assert final.entry_price == D("100.00")
    assert final.exit_kind == "SL"
    assert final.exit_price == D("102.00")
    assert [e.kind for e in events] == ["FILL", "EXIT"]


def test_tracer_state_becomes_a_validated_v2_trade_record() -> None:
    state, _ = advance(
        _long_state(),
        source=_source(with_signal_bar=False),
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=WINDOW_END,
        bar=None,
    )
    record = build_trade_record(
        state=state,
        strategy_version="v1",
        parameter_set_hash="b" * 64,
        cost_model=_cost_model(),
        funding_amount=D("0"),
        funding_event_count=0,
        regime=None,
        constraints_extrapolated=False,
    )
    assert record.signal_close_utc == SIGNAL_CLOSE
    assert record.entry_time_utc is not None and record.entry_time_utc > SIGNAL_CLOSE
    assert record.exit_time_utc is not None and record.exit_time_utc >= record.entry_time_utc
    assert record.quantity == D("0.5")
    assert record.planned_quantity == D("0.5")
    assert record.realized_risk == D("1.50")  # filled == planned -> sized figure unchanged
    assert record.gross_pnl == D("-1.00")
    assert record.entry_fee == D("0.0200")
    assert record.exit_fee == D("0.0196")
    assert record.slippage_amount == D("0.0345")
    assert record.realized_pnl == D("-1.0741")
    assert record.touch_no_fill_count == 1
    validate_trade_record(record)  # raises on violation, returns None otherwise

    again = build_trade_record(
        state=state,
        strategy_version="v1",
        parameter_set_hash="b" * 64,
        cost_model=_cost_model(),
        funding_amount=D("0"),
        funding_event_count=0,
        regime=None,
        constraints_extrapolated=False,
    )
    assert again.trade_id == record.trade_id
    assert again.to_dict() == record.to_dict()


def test_record_with_entry_at_signal_close_is_refused_by_the_validator() -> None:
    state, _ = advance(
        _long_state(),
        source=_source(with_signal_bar=False),
        start_exclusive=SIGNAL_CLOSE,
        end_inclusive=WINDOW_END,
        bar=None,
    )
    record = build_trade_record(
        state=state,
        strategy_version="v1",
        parameter_set_hash="b" * 64,
        cost_model=_cost_model(),
        funding_amount=D("0"),
        funding_event_count=0,
        regime=None,
        constraints_extrapolated=False,
    )
    bad = dataclasses.replace(record, entry_time_utc=SIGNAL_CLOSE)
    with pytest.raises(TradeRecordInvariantError, match="entry_time"):
        validate_trade_record(bad)


def test_trade_record_is_shared_with_the_v1_simulator_module() -> None:
    from src.backtest.records import TradeRecord as MovedRecord
    from src.backtest.simulator import TradeRecord

    assert TradeRecord is MovedRecord
