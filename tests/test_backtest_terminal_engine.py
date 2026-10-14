"""Engine interplay of the terminal settlement (quick 261014-nnl, plan 04).

Design 16-DRAFT-S-B-interval-design.md rev3 section 3 items 2 (dropped), 4 (RESTING at T),
5 (no-plan rule with a pinned label position), 6 (inputs after T raise) and section 4
(`settlement_count` apart). Plan 03 built the hook; these tests pin what happens around it:

- a symbol whose plan was settled or cancelled at T joins `window.dropped`, so a DAILY_STOP from
  another symbol later in the same window never cancels or books it a second time;
- a declared symbol gets no plan when `signal_close + 1 minute > T` (label
  `TERMINAL_BEFORE_ACTIVATION`, counted after the equity check and the conflict check);
- a declared symbol with a bar, minute or funding row beyond T raises before the simulation.

Geometry mirrors REEF: T = 09:00 UTC, the last declared 1h bar closes 1 ms before T. Sizes come
from a per-symbol stand-in risk function: qty 10 / risk 50 for the symbol under test (its
settlement loss, about -96, stays under the 100.00 daily stop of 10000 equity) and qty 50 /
risk 100 for the "other" symbol (a stop-out there is a -106.92 day loss and trips DAILY_STOP).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from src.backtest import engine
from src.backtest.case import parse_case_input
from src.backtest.engine import EngineRun, _Engine, _Entity, simulate_detailed
from src.backtest.ledger import open_positions_for_risk
from src.backtest.lifecycle import new_plan_state
from src.backtest.records import BOOKING_CANCEL, BOOKING_EXIT
from src.core.types import SetupResult
from src.domain.registry import load_parameter_set
from src.risk.types import PortfolioVerdict

from tests.backtest_case_helpers import (
    at,
    bar_row,
    constraint_row,
    default_funding,
    fixed_risk_fn,
    flat_minutes,
    funding_row,
    make_case,
    minute_close,
    minute_row,
    scripted_plan,
)
from tests.backtest_plan_helpers import make_trade_plan
from tests.test_backtest_terminal_settlement import (
    LONG_NOTE,
    RESTING_NOTE,
    SIGNAL,
    TERMINAL,
    settlement_row,
)

REEF = "REEFUSDT"
BTC = "BTCUSDT"
SOL = "SOLUSDT"
SMALL = ("10", "50")
BIG = ("50", "100")


def sized_risk_fn(sizes: dict[str, tuple[str, str]]) -> Callable[..., PortfolioVerdict]:
    """A stand-in risk function with one hand size per symbol."""
    inner = {symbol: fixed_risk_fn(*size) for symbol, size in sizes.items()}

    def risk_fn(**kwargs: Any) -> PortfolioVerdict:
        return inner[kwargs["constraint_snapshot"].symbol](**kwargs)

    return risk_fn


def _go_through(symbol: str, open_time: datetime) -> dict[str, str]:
    """A trade minute that trades through the 100.00 LONG limit."""
    return minute_row(symbol, open_time, "100.20", "100.30", "99.80", "100.00", kind="trade")


def _stop_out(symbol: str, open_time: datetime) -> dict[str, str]:
    """A mark minute that reaches the 98.00 LONG stop and opens above it (no gap)."""
    return minute_row(symbol, open_time, "98.50", "98.60", "97.90", "98.20", kind="mark")


def symbol_rows(
    symbol: str, mode: str, stop_at: datetime | None = None
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Trade and mark minute rows of one symbol for a scripted LONG plan signalled at 01:59:59.999.

    `rest`: the plan never reaches the limit (trade stays at 105.00) and rests until T.
    `open`: it fills at 02:00 and is never stopped (marks flat at 100.00 until 08:59).
    `loser`: it fills at 02:00 and the mark minute opening at `stop_at` reaches the stop.
    """
    if mode == "rest":
        return (
            flat_minutes(symbol, at(2, 0), 420, "105.00", kind="trade"),
            flat_minutes(symbol, at(2, 0), 420, "100.00", kind="mark"),
        )
    if mode == "open":
        return (
            [_go_through(symbol, at(2, 0))],
            flat_minutes(symbol, at(2, 0), 420, "100.00", kind="mark"),
        )
    if mode == "loser" and stop_at is not None:
        before = int((stop_at - at(2, 0)).total_seconds() // 60)
        return (
            [_go_through(symbol, at(2, 0))],
            [
                *flat_minutes(symbol, at(2, 0), before, "100.00", kind="mark"),
                _stop_out(symbol, stop_at),
            ],
        )
    raise ValueError(f"unknown mode {mode!r}")


def build_case(
    modes: dict[str, str],
    *,
    terminals: dict[str, datetime],
    stops: dict[str, datetime] | None = None,
    with_last_bar: bool = True,
) -> dict[str, Any]:
    """A scripted multi-symbol case; `terminals` lists the declared symbols and their T.

    Declared symbols get funding rows only before T (a row at or after T is refused); the
    others get the default rows. `with_last_bar` adds the 08:00 1h bar of the first declared
    symbol, so a window ends at 08:59:59.999, 1 ms before T.
    """
    symbols = tuple(sorted(modes))
    trade: list[dict[str, str]] = []
    mark: list[dict[str, str]] = []
    funding: list[dict[str, Any]] = []
    for symbol in symbols:
        rows = symbol_rows(symbol, modes[symbol], (stops or {}).get(symbol))
        trade.extend(rows[0])
        mark.extend(rows[1])
        if symbol in terminals:
            funding.extend(
                [
                    funding_row(symbol, datetime(2026, 1, 4, 16, 0, tzinfo=TERMINAL.tzinfo), "0"),
                    funding_row(symbol, at(0, 0), "0"),
                    funding_row(symbol, at(8, 0), "0"),
                ]
            )
        else:
            funding.extend(default_funding([symbol]))
    bars = []
    if with_last_bar:
        bars = [bar_row(sorted(terminals)[0], at(8, 0), "100", "100.2", "99.8", "100")]
    case = make_case(
        symbols=symbols,
        scripted=[
            scripted_plan(s, SIGNAL, f"sig-{s[:3].lower()}", expiry_hours=12) for s in symbols
        ],
        strategy_bars=bars,
        trade_minutes=trade,
        mark_minutes=mark,
        funding=funding,
        constraints=[constraint_row(s) for s in symbols],
    )
    case["terminal_settlements"] = [
        settlement_row(symbol=s, terminal=t) for s, t in terminals.items()
    ]
    return case


def run(case: dict[str, Any], sizes: dict[str, tuple[str, str]]) -> EngineRun:
    return simulate_detailed(case, risk_fn=sized_risk_fn(sizes))


def records_of(result: EngineRun, symbol: str) -> list[dict[str, Any]]:
    return [t for t in result.output["trades"] if t["symbol"] == symbol]


def bookings_of(result: EngineRun, symbol: str, kind: str) -> list[Any]:
    return [b for b in result.bookings if b.symbol == symbol and b.kind == kind]


# --------------------------------------------------------------------------- #
# Task 1: RESTING at T, window.dropped and DAILY_STOP (design tests 6 and 11).
# --------------------------------------------------------------------------- #


def test_resting_plan_at_terminal_is_cancelled_settlement_cancel_and_exposure_removed() -> None:
    result = run(build_case({REEF: "rest"}, terminals={REEF: TERMINAL}), {REEF: SMALL})

    (record,) = records_of(result, REEF)
    assert record["entry_kind"] == "SETTLEMENT_CANCEL"
    assert record["resolved_at_utc"] == TERMINAL.isoformat()
    assert record["coverage_note"] == RESTING_NOTE
    for name in (
        "entry_time_utc",
        "entry_price",
        "exit_kind",
        "exit_price",
        "exit_time_utc",
        "realized_pnl",
    ):
        assert record[name] is None, name
    cancels = bookings_of(result, REEF, BOOKING_CANCEL)
    assert [(b.time_utc, b.amount) for b in cancels] == [(TERMINAL, 0)]
    assert [p for p in open_positions_for_risk(result.ledger) if p.symbol == REEF] == []


def test_daily_stop_after_terminal_from_another_symbol_does_not_rebook_the_cancelled_plan() -> None:
    stop = at(10, 15)
    case = build_case({REEF: "rest", SOL: "loser"}, terminals={REEF: TERMINAL}, stops={SOL: stop})
    result = run(case, {REEF: SMALL, SOL: BIG})

    # The loss really tripped DAILY_STOP after T, inside the same window as the cancel.
    (sol,) = records_of(result, SOL)
    assert sol["exit_kind"] == "SL"
    assert sol["exit_time_utc"] == minute_close(stop).isoformat()
    (reef,) = records_of(result, REEF)
    assert reef["entry_kind"] == "SETTLEMENT_CANCEL"
    assert reef["resolved_at_utc"] == TERMINAL.isoformat()
    cancels = bookings_of(result, REEF, BOOKING_CANCEL)
    assert [b.time_utc for b in cancels] == [TERMINAL]


def test_daily_stop_after_terminal_does_not_rebook_the_settled_position() -> None:
    stop = at(10, 15)
    case = build_case({REEF: "open", SOL: "loser"}, terminals={REEF: TERMINAL}, stops={SOL: stop})
    result = run(case, {REEF: SMALL, SOL: BIG})

    (sol,) = records_of(result, SOL)
    assert sol["exit_time_utc"] == minute_close(stop).isoformat()
    (reef,) = records_of(result, REEF)
    assert reef["exit_kind"] == "SETTLEMENT"
    assert reef["exit_time_utc"] == TERMINAL.isoformat()
    exits = bookings_of(result, REEF, BOOKING_EXIT)
    assert [b.time_utc for b in exits] == [TERMINAL]
    assert bookings_of(result, REEF, BOOKING_CANCEL) == []


@pytest.mark.parametrize("with_last_bar", [True, False], ids=["bar-window", "single-window"])
def test_daily_stop_before_terminal_cancels_the_resting_plan_daily_stop_cancel(
    with_last_bar: bool,
) -> None:
    stop = at(5, 0)
    case = build_case(
        {REEF: "rest", SOL: "loser"},
        terminals={REEF: TERMINAL},
        stops={SOL: stop},
        with_last_bar=with_last_bar,
    )
    result = run(case, {REEF: SMALL, SOL: BIG})

    (reef,) = records_of(result, REEF)
    assert reef["entry_kind"] == "DAILY_STOP_CANCEL"
    assert reef["resolved_at_utc"] == minute_close(stop).isoformat()
    cancels = bookings_of(result, REEF, BOOKING_CANCEL)
    assert [b.time_utc for b in cancels] == [minute_close(stop)]
    assert all(t["entry_kind"] != "SETTLEMENT_CANCEL" for t in result.output["trades"])


def test_daily_stop_at_the_terminal_instant_follows_symbol_order() -> None:
    declared = {BTC: TERMINAL, REEF: TERMINAL}
    # BTCUSDT sorts before REEFUSDT: its settlement loss at exactly T (-3.00 entry, -477.26
    # exit) trips DAILY_STOP first, so the resting REEF plan ends DAILY_STOP_CANCEL at T.
    before = run(
        build_case({BTC: "open", REEF: "rest"}, terminals=declared), {BTC: BIG, REEF: SMALL}
    )
    (btc,) = records_of(before, BTC)
    assert btc["exit_kind"] == "SETTLEMENT"
    (reef,) = records_of(before, REEF)
    assert reef["entry_kind"] == "DAILY_STOP_CANCEL"
    assert reef["resolved_at_utc"] == TERMINAL.isoformat()
    assert [b.time_utc for b in bookings_of(before, REEF, BOOKING_CANCEL)] == [TERMINAL]

    # SOLUSDT sorts after REEFUSDT: REEF is cancelled first (SETTLEMENT_CANCEL), is dropped,
    # and the later DAILY_STOP of SOL's settlement loss cannot touch it.
    declared = {REEF: TERMINAL, SOL: TERMINAL}
    after = run(
        build_case({REEF: "rest", SOL: "open"}, terminals=declared), {REEF: SMALL, SOL: BIG}
    )
    (sol,) = records_of(after, SOL)
    assert sol["exit_kind"] == "SETTLEMENT"
    (reef,) = records_of(after, REEF)
    assert reef["entry_kind"] == "SETTLEMENT_CANCEL"
    assert reef["resolved_at_utc"] == TERMINAL.isoformat()
    assert [b.time_utc for b in bookings_of(after, REEF, BOOKING_CANCEL)] == [TERMINAL]


@pytest.mark.parametrize("with_last_bar", [True, False], ids=["bar-window", "single-window"])
def test_open_position_keeps_its_stop_through_a_daily_stop_before_terminal_and_settles_at_t(
    with_last_bar: bool,
) -> None:
    stop = at(5, 0)
    case = build_case(
        {REEF: "open", SOL: "loser"},
        terminals={REEF: TERMINAL},
        stops={SOL: stop},
        with_last_bar=with_last_bar,
    )
    result = run(case, {REEF: SMALL, SOL: BIG})

    (sol,) = records_of(result, SOL)
    assert sol["exit_time_utc"] == minute_close(stop).isoformat()
    (reef,) = records_of(result, REEF)
    assert reef["entry_kind"] == "ENTRY_FILLED"
    assert reef["exit_kind"] == "SETTLEMENT"
    assert reef["exit_time_utc"] == TERMINAL.isoformat()
    assert reef["coverage_note"] == LONG_NOTE
    assert bookings_of(result, REEF, BOOKING_CANCEL) == []


# --------------------------------------------------------------------------- #
# Task 2: no-plan rule with the pinned label position; inputs after T raise.
# --------------------------------------------------------------------------- #

LATE_CLOSE = minute_close(at(8, 59))  # 08:59:59.999: the last 1h bar close before T
EARLY_CLOSE = minute_close(at(7, 59))  # 07:59:59.999: one hour earlier
TERMINAL_LABEL = "TERMINAL_BEFORE_ACTIVATION"
TERMINAL_TEXT = r"2026-01-05T09:00:00\+00:00"
PRE_T_FUNDING = [
    funding_row(REEF, datetime(2026, 1, 4, 16, 0, tzinfo=UTC), "0"),
    funding_row(REEF, at(0, 0), "0"),
    funding_row(REEF, at(8, 0), "0"),
]


def terminal_case(
    *,
    scripted_closes: Sequence[datetime] | None = (SIGNAL,),
    bars: Sequence[dict[str, str]] | None = None,
    context: Sequence[dict[str, str]] = (),
    trade_extra: Sequence[dict[str, str]] = (),
    mark_extra: Sequence[dict[str, str]] = (),
    funding: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A one-symbol REEF case with T = 09:00; `scripted_closes=None` selects the strategy front-end.

    The plan (when scripted) never reaches its limit and rests until T. Everything else is
    inside the declared range unless an `*_extra` argument adds data beyond T.
    """
    case = make_case(
        symbols=(REEF,),
        scripted=(
            None
            if scripted_closes is None
            else [
                scripted_plan(REEF, close, f"sig-{index}", expiry_hours=12)
                for index, close in enumerate(scripted_closes)
            ]
        ),
        strategy_bars=(
            [bar_row(REEF, at(8, 0), "100", "100.2", "99.8", "100")] if bars is None else bars
        ),
        context_bars=context,
        trade_minutes=[
            *flat_minutes(REEF, at(2, 0), 420, "105.00", kind="trade"),
            *trade_extra,
        ],
        mark_minutes=[*flat_minutes(REEF, at(2, 0), 420, "100.00", kind="mark"), *mark_extra],
        funding=PRE_T_FUNDING if funding is None else funding,
        constraints=[constraint_row(REEF)],
    )
    case["terminal_settlements"] = [settlement_row()]
    return case


def make_engine(case: dict[str, Any]) -> _Engine:
    parsed = parse_case_input(case)
    parameter_set = load_parameter_set(parsed.strategy_id, parsed.parameter_set_id)
    assert parsed.minute_source is not None
    return _Engine(parsed, parameter_set, parsed.minute_source, fixed_risk_fn("10", "50"))


def resting_entity(close: datetime) -> _Entity:
    state = new_plan_state(
        plan=make_trade_plan("LONG"),
        symbol=REEF,
        direction="LONG",
        signal_close_utc=close,
        price_tick_size=Decimal("0.10"),
        planned_quantity=Decimal("0.5"),
        sized_realized_risk=Decimal("1.50"),
    )
    return _Entity(state=state, advanced_to=close, extrapolated=False)


def test_signal_closing_1ms_before_terminal_creates_no_plan_and_no_exposure() -> None:
    calls: list[dict[str, Any]] = []
    case = terminal_case(scripted_closes=(LATE_CLOSE,))
    result = simulate_detailed(case, risk_fn=fixed_risk_fn("10", "50", calls=calls))

    assert result.output["trades"] == []
    assert result.output["run_summary"]["no_trade_counts"] == {TERMINAL_LABEL: 1}
    assert calls == []  # the risk gate was never asked: no sizing, no exposure
    assert open_positions_for_risk(result.ledger) == []
    assert result.ledger.exposures == ()
    assert result.bookings == ()


def test_signal_one_hour_earlier_still_creates_a_plan() -> None:
    case = terminal_case(scripted_closes=(EARLY_CLOSE,))
    result = simulate_detailed(case, risk_fn=fixed_risk_fn("10", "50"))

    (record,) = result.output["trades"]
    assert record["entry_kind"] == "SETTLEMENT_CANCEL"
    assert record["signal_close_utc"] == EARLY_CLOSE.isoformat()
    assert result.output["run_summary"]["no_trade_counts"] == {}


def test_terminal_block_boundary_is_one_minute_after_the_signal_close() -> None:
    built = make_engine(terminal_case())
    one_minute_before_t = TERMINAL - timedelta(minutes=1)

    assert built._terminal_blocks(REEF, one_minute_before_t) is False
    assert built._terminal_blocks(REEF, one_minute_before_t + timedelta(milliseconds=1)) is True
    assert built._terminal_blocks(REEF, LATE_CLOSE) is True
    assert built._terminal_blocks(BTC, LATE_CLOSE) is False  # undeclared: never blocked


def _spy_evaluate(monkeypatch: pytest.MonkeyPatch, result: object) -> list[tuple[Any, ...]]:
    """Replace the strategy by a fixed answer and forbid the planner; return the call log."""
    calls: list[tuple[Any, ...]] = []

    def spy(**kwargs: Any) -> object:
        calls.append(tuple(sorted(kwargs)))
        return result

    def no_plan(**kwargs: Any) -> object:
        raise AssertionError("a terminal-blocked signal must not reach the planner")

    monkeypatch.setattr(engine, "evaluate", spy)
    monkeypatch.setattr(engine, "build_trade_plan", no_plan)
    return calls


SIGNALLED = SimpleNamespace(
    is_no_trade=False,
    signal=SimpleNamespace(direction="LONG", signal_id="sig-strategy"),
    reason_code="OK",
    regime=None,
)


def test_terminal_label_is_counted_after_equity_and_conflict_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # --- scripted front-end: equity check, then conflict check, then the terminal check ---
    exhausted = make_engine(terminal_case(scripted_closes=(LATE_CLOSE,)))
    exhausted.ledger = dataclasses.replace(exhausted.ledger, equity=Decimal("0"))
    exhausted._evaluate_signal(REEF, LATE_CLOSE)
    assert exhausted.no_trade_counts == {"UNCERTAIN_ACCOUNT_STATE": 1}

    busy = make_engine(terminal_case(scripted_closes=(SIGNAL, LATE_CLOSE)))
    busy._evaluate_signal(REEF, SIGNAL)  # the first plan rests
    assert REEF in busy.active
    busy._evaluate_signal(REEF, LATE_CLOSE)
    assert busy.no_trade_counts == {"CONFLICT_WITH_OPEN_POSITION": 1}

    fresh = make_engine(terminal_case(scripted_closes=(LATE_CLOSE,)))
    fresh._evaluate_signal(REEF, LATE_CLOSE)
    assert fresh.no_trade_counts == {TERMINAL_LABEL: 1}
    assert fresh.active == {}

    # --- strategy front-end: equity, strategy evaluate, conflict, terminal, plan ---
    strategy_case = terminal_case(scripted_closes=None)
    calls = _spy_evaluate(monkeypatch, SIGNALLED)

    exhausted_s = make_engine(strategy_case)
    exhausted_s.ledger = dataclasses.replace(exhausted_s.ledger, equity=Decimal("0"))
    exhausted_s._evaluate_signal(REEF, LATE_CLOSE)
    assert exhausted_s.no_trade_counts == {"UNCERTAIN_ACCOUNT_STATE": 1}
    assert calls == []  # equity is checked before the strategy is asked

    busy_s = make_engine(strategy_case)
    busy_s.active[REEF] = resting_entity(SIGNAL)
    busy_s._evaluate_signal(REEF, LATE_CLOSE)
    assert busy_s.no_trade_counts == {"CONFLICT_WITH_OPEN_POSITION": 1}
    assert len(calls) == 1

    fresh_s = make_engine(strategy_case)
    fresh_s._evaluate_signal(REEF, LATE_CLOSE)
    assert fresh_s.no_trade_counts == {TERMINAL_LABEL: 1}
    assert fresh_s.records == []
    assert fresh_s.active == {}
    assert fresh_s.ledger.exposures == ()
    assert len(calls) == 2


def test_strategy_no_signal_reason_is_counted_as_before_even_after_the_terminal_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _spy_evaluate(monkeypatch, SetupResult(is_no_trade=True, reason_code="NO_TRADE_REGIME"))
    built = make_engine(terminal_case(scripted_closes=None))

    built._evaluate_signal(REEF, LATE_CLOSE)

    assert built.no_trade_counts == {"NO_TRADE_REGIME": 1}


def test_declared_symbol_with_a_strategy_bar_closing_after_terminal_raises() -> None:
    late_bar = bar_row(REEF, at(9, 0), "100", "100.2", "99.8", "100")
    bars = [bar_row(REEF, at(8, 0), "100", "100.2", "99.8", "100"), late_bar]

    with pytest.raises(ValueError, match=rf"REEFUSDT.*strategy bar.*{TERMINAL_TEXT}"):
        simulate_detailed(terminal_case(bars=bars), risk_fn=fixed_risk_fn("10", "50"))


@pytest.mark.parametrize("kind", ["trade", "mark"])
def test_declared_symbol_with_a_trade_or_mark_minute_closing_after_terminal_raises(
    kind: str,
) -> None:
    minute = minute_row(REEF, at(9, 0), "105.00", "105.05", "104.95", "105.00", kind=kind)
    extra = {"trade_extra": [minute]} if kind == "trade" else {"mark_extra": [minute]}

    with pytest.raises(ValueError, match=rf"REEFUSDT.*{kind} minute.*{TERMINAL_TEXT}"):
        simulate_detailed(terminal_case(**extra), risk_fn=fixed_risk_fn("10", "50"))


@pytest.mark.parametrize("opened", [at(9, 0), at(10, 0)], ids=["at-terminal", "after-terminal"])
def test_declared_symbol_with_a_context_bar_opening_at_or_after_terminal_raises(
    opened: datetime,
) -> None:
    context = [bar_row(REEF, opened, "100", "100.2", "99.8", "100", interval="4h")]

    with pytest.raises(ValueError, match=rf"REEFUSDT.*context bar.*{TERMINAL_TEXT}"):
        simulate_detailed(terminal_case(context=context), risk_fn=fixed_risk_fn("10", "50"))


def test_context_bar_opening_before_terminal_is_allowed() -> None:
    # The 08:00 4h bar closes 11:59:59.999, after T, but opens before it: allowed (design 3.6).
    context = [bar_row(REEF, at(8, 0), "100", "100.2", "99.8", "100", interval="4h")]

    result = simulate_detailed(terminal_case(context=context), risk_fn=fixed_risk_fn("10", "50"))

    (record,) = result.output["trades"]
    assert record["entry_kind"] == "SETTLEMENT_CANCEL"


@pytest.mark.parametrize(
    "when",
    [at(9, 0), datetime(2026, 1, 5, 16, 0, tzinfo=UTC)],
    ids=["at-terminal", "after-terminal"],
)
def test_funding_row_at_terminal_raises(when: datetime) -> None:
    funding = [*PRE_T_FUNDING, funding_row(REEF, when, "0")]

    with pytest.raises(ValueError, match=rf"REEFUSDT.*funding row.*{TERMINAL_TEXT}"):
        simulate_detailed(terminal_case(funding=funding), risk_fn=fixed_risk_fn("10", "50"))


def test_undeclared_symbol_with_data_after_another_symbols_terminal_is_unaffected() -> None:
    # BTCUSDT is not declared: its 1h bar, 4h bar, minutes and funding after 09:00 are legal.
    btc_trade = flat_minutes(BTC, at(2, 0), 600, "105.00", kind="trade")
    btc_mark = flat_minutes(BTC, at(2, 0), 600, "100.00", kind="mark")
    case = make_case(
        symbols=(BTC, REEF),
        scripted=[
            scripted_plan(BTC, SIGNAL, "sig-btc", expiry_hours=12),
            scripted_plan(REEF, SIGNAL, "sig-reef", expiry_hours=12),
        ],
        strategy_bars=[
            bar_row(REEF, at(8, 0), "100", "100.2", "99.8", "100"),
            bar_row(BTC, at(9, 0), "100", "100.2", "99.8", "100"),
        ],
        context_bars=[bar_row(BTC, at(9, 0), "100", "100.2", "99.8", "100", interval="4h")],
        trade_minutes=[*btc_trade, *flat_minutes(REEF, at(2, 0), 420, "105.00", kind="trade")],
        mark_minutes=[*btc_mark, *flat_minutes(REEF, at(2, 0), 420, "100.00", kind="mark")],
        funding=[*default_funding([BTC]), *PRE_T_FUNDING],
        constraints=[constraint_row(BTC), constraint_row(REEF)],
    )
    case["terminal_settlements"] = [settlement_row()]

    result = simulate_detailed(case, risk_fn=fixed_risk_fn("10", "50"))

    assert [t["entry_kind"] for t in records_of(result, BTC)] == ["PENDING_AT_DATA_END"]
    assert [t["entry_kind"] for t in records_of(result, REEF)] == ["SETTLEMENT_CANCEL"]


# --------------------------------------------------------------------------- #
# Task 3: settlement_count in run_summary, only when the case declares a settlement.
# --------------------------------------------------------------------------- #

SUMMARY_KEYS = frozenset(
    {
        "allowed_gaps_used",
        "constraints_extrapolated_count",
        "context_timeframe",
        "context_window_bars",
        "data_window",
        "dataset_id",
        "end_of_data_count",
        "fallback_count",
        "gap_through_stop_count",
        "intrabar_tie_break",
        "no_trade_counts",
        "pending_at_data_end_count",
        "plan_source",
        "simulator_semantics_version",
        "strategy_window_bars",
        "tie_order_note",
        "timeframe",
        "touch_no_fill_total",
    }
)


def test_run_summary_carries_settlement_count_only_when_the_case_declares_a_settlement() -> None:
    undeclared = terminal_case()
    del undeclared["terminal_settlements"]
    plain = simulate_detailed(undeclared, risk_fn=fixed_risk_fn("10", "50"))
    declared = simulate_detailed(terminal_case(), risk_fn=fixed_risk_fn("10", "50"))

    assert len(SUMMARY_KEYS) == 18
    assert set(plain.output["run_summary"]) == SUMMARY_KEYS
    assert set(declared.output["run_summary"]) == SUMMARY_KEYS | {"settlement_count"}
    assert declared.output["run_summary"]["settlement_count"] == 0  # only a cancel happened
    # Every key the undeclared run has keeps its value in the declared run, apart from the
    # outcome of the plan itself (cancelled at T instead of pending at the data end).
    assert plain.output["run_summary"]["pending_at_data_end_count"] == 1
    assert declared.output["run_summary"]["pending_at_data_end_count"] == 0


def test_settlement_count_counts_settlement_exits_not_cancels() -> None:
    # REEFUSDT is settled (open), BTCUSDT is cancelled (resting), SOLUSDT is undeclared and
    # still open when its marks end, so it closes END_OF_DATA.
    case = build_case(
        {REEF: "open", BTC: "rest", SOL: "open"}, terminals={REEF: TERMINAL, BTC: TERMINAL}
    )
    result = run(case, {REEF: SMALL, BTC: SMALL, SOL: SMALL})

    summary = result.output["run_summary"]
    assert [t["exit_kind"] for t in records_of(result, REEF)] == ["SETTLEMENT"]
    assert [t["entry_kind"] for t in records_of(result, BTC)] == ["SETTLEMENT_CANCEL"]
    assert [t["exit_kind"] for t in records_of(result, SOL)] == ["END_OF_DATA"]
    assert summary["settlement_count"] == 1
    assert summary["end_of_data_count"] == 1
    assert summary["pending_at_data_end_count"] == 0
