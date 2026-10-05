"""Strategy front-end tests for the v2 engine (Phase 14, plan 14-08, Task 3).

The engine evaluates a trailing window of `STRATEGY_WINDOW_BARS` 1h bars and
`CONTEXT_WINDOW_BARS` 4h bars per symbol (selected with bisect, never a full-prefix slice),
with context bars closed at or before the strategy bar close (D-31). The phase 6 trigger-bar
fixture (250 setup bars, inside the window) is the real-strategy oracle: the engine must
find the same signal at the trigger close as `strategy.evaluate` on the full prefix.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from src.backtest import engine
from src.backtest.engine import simulate
from src.backtest.entry import snapped_limit_price
from src.backtest.exits import sl_trigger_price
from src.core.planner import plan
from src.core.strategy import evaluate
from src.core.types import AccountState, Candle, MarketSnapshot, SetupResult
from src.domain.enums import DailyState
from src.domain.registry import load_parameter_set
from src.risk.gating import evaluate_risk
from src.risk.types import PortfolioVerdict

from tests.backtest_case_helpers import (
    SYMBOL,
    bar_row,
    flat_minutes,
    make_case,
    minute_row,
    phase6_strategy_rows,
    scripted_plan,
)

TICK = Decimal("0.10")
TRIGGER_FIXTURE = "intrabar_both_touched"


def candle_of(row: dict[str, Any]) -> Candle:
    return Candle(
        symbol=row["symbol"],
        interval=row["interval"],
        open_time_utc=datetime.fromisoformat(row["open_time_utc"]),
        close_time_utc=datetime.fromisoformat(row["close_time_utc"]),
        open=Decimal(row["open"]),
        high=Decimal(row["high"]),
        low=Decimal(row["low"]),
        close=Decimal(row["close"]),
        volume=Decimal(row["volume"]),
    )


def trigger_case() -> tuple[dict[str, Any], Any, Any]:
    """The trigger-bar case, its full-prefix signal and its full-prefix plan.

    Minutes follow the trigger close: a trade minute that trades through the limit by two
    ticks 10 minutes after it, flat marks in between and a mark minute through the stop.
    """
    strategy_rows, context_rows = phase6_strategy_rows(TRIGGER_FIXTURE)
    setup = [candle_of(r) for r in strategy_rows]
    context = [candle_of(r) for r in context_rows]
    parameter_set = load_parameter_set("trend-pullback", "baseline-v5")
    account = AccountState(equity=Decimal("10000"), risk_rate=Decimal("0.005"))
    snapshot = MarketSnapshot(
        symbol=SYMBOL,
        setup_candles=setup,
        context_candles=[c for c in context if c.close_time_utc <= setup[-1].close_time_utc],
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=account,
        strategy_version="v4.0.0",
        parameter_set=parameter_set,
    )
    assert result.signal is not None, "the phase 6 trigger-bar fixture must produce a setup"
    planned = plan(
        signal=result.signal,
        setup_candles=setup,
        parameter_set=parameter_set,
        account_state=account,
        created_at_utc=setup[-1].close_time_utc,
    )
    assert planned.trade_plan is not None
    trade_plan = planned.trade_plan
    direction = result.signal.direction
    limit = snapped_limit_price(plan=trade_plan, direction=direction, price_tick_size=TICK)
    stop = sl_trigger_price(plan=trade_plan, direction=direction, price_tick_size=TICK)
    long_side = direction == "LONG"
    start = setup[-1].close_time_utc.replace(second=0, microsecond=0) + timedelta(minutes=1)
    # The fill minute trades through the limit by two ticks; the stop minute passes the
    # stop by one tick without opening beyond it (no gap).
    if long_side:
        fill_high, fill_low = limit + TICK, limit - TICK * 2
        stop_high, stop_low = limit, stop - TICK
    else:
        fill_high, fill_low = limit + TICK * 2, limit - TICK
        stop_high, stop_low = stop + TICK, limit
    trade_row = minute_row(
        SYMBOL,
        start + timedelta(minutes=10),
        str(limit),
        str(fill_high),
        str(fill_low),
        str(limit),
        kind="trade",
    )
    flat = flat_minutes(SYMBOL, start, 30, str(limit), kind="mark", half_range="0.1")
    stop_row = minute_row(
        SYMBOL,
        start + timedelta(minutes=30),
        str(limit),
        str(stop_high),
        str(stop_low),
        str(limit),
        kind="mark",
    )
    case = make_case(
        strategy_bars=strategy_rows,
        context_bars=context_rows,
        trade_minutes=[trade_row],
        mark_minutes=[*flat, stop_row],
        data_start=setup[0].open_time_utc,
        data_end=setup[-1].close_time_utc + timedelta(hours=3),
        funding=[
            {
                "symbol": SYMBOL,
                "funding_time_utc": when.isoformat(),
                "funding_rate": "0",
                "mark_price": "100",
            }
            for when in (
                setup[0].open_time_utc,
                setup[-1].close_time_utc - timedelta(hours=4),
                setup[-1].close_time_utc + timedelta(hours=3),
            )
        ],
    )
    return case, result.signal, trade_plan


def test_the_engine_finds_the_full_prefix_signal_at_the_trigger_close() -> None:
    case, signal, trade_plan = trigger_case()
    output = simulate(case, risk_fn=evaluate_risk)

    assert len(output["trades"]) == 1
    trade = output["trades"][0]
    assert trade["signal_id"] == signal.signal_id
    assert trade["trade_plan_id"] == trade_plan.trade_plan_id
    assert trade["direction"] == signal.direction
    # The plan rests from the minute after the trigger close and fills 11 minutes later.
    assert trade["signal_close_utc"] == trade_plan.created_at_utc.isoformat()
    assert datetime.fromisoformat(trade["entry_time_utc"]) > trade_plan.created_at_utc
    assert trade["exit_kind"] == "SL"
    assert output["run_summary"]["plan_source"] == "STRATEGY"


def test_earlier_bars_are_counted_by_reason_and_produce_no_record() -> None:
    case, _, _ = trigger_case()
    output = simulate(case, risk_fn=evaluate_risk)

    counts = output["run_summary"]["no_trade_counts"]
    # Every one of the 249 bars before the trigger bar was a NO_TRADE evaluation.
    assert sum(counts.values()) == len(case["strategy_bars"]) - 1
    assert "CONFLICT_WITH_OPEN_POSITION" not in counts
    assert len(output["trades"]) == 1


def test_the_window_is_a_trailing_slice_and_context_bars_never_run_ahead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine, "STRATEGY_WINDOW_BARS", 5)
    monkeypatch.setattr(engine, "CONTEXT_WINDOW_BARS", 3)
    seen: list[tuple[list[Candle], list[Candle]]] = []

    def spy(**kwargs: Any) -> SetupResult:
        snapshot = kwargs["snapshot"]
        seen.append((list(snapshot.setup_candles), list(snapshot.context_candles)))
        return SetupResult(is_no_trade=True, reason_code="NO_TRADE_REGIME")

    monkeypatch.setattr(engine, "evaluate", spy)
    day = datetime(2026, 1, 5, tzinfo=UTC)
    strategy_rows = [
        bar_row(SYMBOL, day + timedelta(hours=i), "100", "101", "99", "100") for i in range(12)
    ]
    context_rows = [
        bar_row(SYMBOL, day + timedelta(hours=4 * i), "100", "101", "99", "100", interval="4h")
        for i in range(3)
    ]
    case = make_case(strategy_bars=strategy_rows, context_bars=context_rows)
    output = simulate(case, risk_fn=evaluate_risk)

    bars = [candle_of(r) for r in strategy_rows]
    contexts = [candle_of(r) for r in context_rows]
    assert len(seen) == 12
    for index, (setup, context) in enumerate(seen):
        assert setup == bars[max(0, index - 4) : index + 1]  # at most STRATEGY_WINDOW_BARS
        close = bars[index].close_time_utc
        assert context == [c for c in contexts if c.close_time_utc <= close][-3:]
        assert all(c.close_time_utc <= close for c in context)
    # The 4h bar opening 04:00 closes 07:59:59.999: not visible to the 07:00 bar's close
    # (07:59:59.999 is its own close, so it IS visible there), and never to the 06:00 bar.
    assert contexts[1] not in seen[6][1]
    assert contexts[1] in seen[7][1]
    assert output["run_summary"]["no_trade_counts"] == {"NO_TRADE_REGIME": 12}
    assert output["trades"] == []


def test_the_default_window_sizes_cover_the_phase_6_fixture() -> None:
    # 250 setup bars and 250 context bars are inside the 1000/300 windows, so the windowed
    # evaluation equals the full-prefix one for the trigger-bar oracle above.
    assert engine.STRATEGY_WINDOW_BARS == 1000
    assert engine.CONTEXT_WINDOW_BARS == 300
    strategy_rows, context_rows = phase6_strategy_rows(TRIGGER_FIXTURE)
    assert len(strategy_rows) <= engine.STRATEGY_WINDOW_BARS
    assert len(context_rows) <= engine.CONTEXT_WINDOW_BARS


def test_a_close_of_a_strategy_bar_outside_the_data_window_is_not_evaluated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[datetime] = []

    def spy(**kwargs: Any) -> SetupResult:
        calls.append(kwargs["snapshot"].setup_candles[-1].close_time_utc)
        return SetupResult(is_no_trade=True, reason_code="NO_TRADE_REGIME")

    monkeypatch.setattr(engine, "evaluate", spy)
    day = datetime(2026, 1, 5, tzinfo=UTC)
    rows = [bar_row(SYMBOL, day + timedelta(hours=i), "100", "101", "99", "100") for i in range(6)]
    # Window 02:00 to 04:00: the first two closes are warm-up, the last two are past the end.
    case = make_case(
        strategy_bars=rows,
        data_start=day + timedelta(hours=2),
        data_end=day + timedelta(hours=4),
    )
    simulate(case, risk_fn=evaluate_risk)

    assert calls == [
        day + timedelta(hours=3) - timedelta(milliseconds=1),
        day + timedelta(hours=4) - timedelta(milliseconds=1),
    ]


# --------------------------------------------------------------------------- #
# Regime flows from strategy.evaluate through SetupResult onto every record (D-21, D-38).
# --------------------------------------------------------------------------- #

REGIMES = {"BULLISH", "BEARISH", "NEUTRAL"}


def trigger_setup_result() -> SetupResult:
    """`strategy.evaluate` on the full phase 6 prefix: the trigger-bar SetupResult."""
    strategy_rows, context_rows = phase6_strategy_rows(TRIGGER_FIXTURE)
    setup = [candle_of(r) for r in strategy_rows]
    context = [candle_of(r) for r in context_rows]
    snapshot = MarketSnapshot(
        symbol=SYMBOL,
        setup_candles=setup,
        context_candles=[c for c in context if c.close_time_utc <= setup[-1].close_time_utc],
        source_timeframe="1h",
    )
    return evaluate(
        snapshot=snapshot,
        account_state=AccountState(equity=Decimal("10000"), risk_rate=Decimal("0.005")),
        strategy_version="v4.0.0",
        parameter_set=load_parameter_set("trend-pullback", "baseline-v5"),
    )


def test_the_trigger_bar_setup_result_carries_the_resolved_regime() -> None:
    result = trigger_setup_result()

    assert result.signal is not None
    assert result.regime in REGIMES


def test_the_emitted_trade_record_carries_the_setup_regime() -> None:
    case, _, _ = trigger_case()
    output = simulate(case, risk_fn=evaluate_risk)

    assert [t["regime"] for t in output["trades"]] == [trigger_setup_result().regime]


def test_a_reject_record_carries_the_signal_regime() -> None:
    def rejecting(**_: Any) -> PortfolioVerdict:
        return PortfolioVerdict(
            is_no_trade=True,
            sized=None,
            reason_code="CLUSTER_CAP_REJECT",
            daily_state=DailyState.NORMAL,
        )

    case, signal, _ = trigger_case()
    output = simulate(case, risk_fn=rejecting)

    assert len(output["trades"]) == 1
    record = output["trades"][0]
    assert record["entry_kind"] == "REJECT"
    assert record["signal_id"] == signal.signal_id
    assert record["regime"] == trigger_setup_result().regime


def test_a_scripted_plan_record_carries_its_own_regime_or_none() -> None:
    from tests.backtest_case_helpers import SIGNAL_CLOSE, fixed_risk_fn, minute_close

    def run(regime: str | None) -> dict[str, Any]:
        row = scripted_plan(SYMBOL, SIGNAL_CLOSE, "sig-regime", regime=regime)
        marks = flat_minutes(
            SYMBOL,
            minute_close(SIGNAL_CLOSE).replace(second=0, microsecond=0),
            30,
            "100",
            kind="mark",
        )
        trades = flat_minutes(
            SYMBOL,
            minute_close(SIGNAL_CLOSE).replace(second=0, microsecond=0),
            30,
            "100",
            kind="trade",
            half_range="1.5",
        )
        case = make_case(scripted=[row], trade_minutes=trades, mark_minutes=marks)
        return simulate(case, risk_fn=fixed_risk_fn("1.000", "3.0"))

    assert [t["regime"] for t in run("BULLISH")["trades"]] == ["BULLISH"]
    assert [t["regime"] for t in run(None)["trades"]] == [None]


def test_a_no_trade_setup_result_without_a_regime_still_constructs() -> None:
    result = SetupResult(is_no_trade=True, reason_code="NO_TRADE_REGIME")

    assert result.regime is None
    with pytest.raises(ValueError):
        SetupResult(is_no_trade=True, reason_code="NO_TRADE_REGIME", regime="")


def test_a_no_trade_result_past_the_regime_gate_names_the_regime() -> None:
    strategy_rows, context_rows = phase6_strategy_rows(TRIGGER_FIXTURE)
    setup = [candle_of(r) for r in strategy_rows]
    context = [candle_of(r) for r in context_rows]
    parameter_set = load_parameter_set("trend-pullback", "baseline-v5")
    account = AccountState(equity=Decimal("10000"), risk_rate=Decimal("0.005"))
    named = 0
    for end in range(210, len(setup)):
        prefix = setup[:end]
        result = evaluate(
            snapshot=MarketSnapshot(
                symbol=SYMBOL,
                setup_candles=prefix,
                context_candles=[
                    c for c in context if c.close_time_utc <= prefix[-1].close_time_utc
                ],
                source_timeframe="1h",
            ),
            account_state=account,
            strategy_version="v4.0.0",
            parameter_set=parameter_set,
        )
        assert result.regime is None or result.regime in REGIMES
        if result.is_no_trade and result.regime is not None:
            named += 1
    assert named > 0
