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

from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest
from src.backtest.engine import EngineRun, simulate_detailed
from src.backtest.ledger import open_positions_for_risk
from src.backtest.records import BOOKING_CANCEL, BOOKING_EXIT
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
