"""Terminal-settlement tracer and OPEN-side semantics (quick 261014-nnl, plan 03).

Design 16-DRAFT-S-B-interval-design.md rev3 section 3 items 1-3 and 7-9 (decided per
16-DEC-S-B-interval item 3). A case may carry the optional backtest-case/2 key
`terminal_settlements`; an OPEN position of a declared symbol closes at exactly the terminal
instant T at the adverse bound of the recorded interval (LONG at `price_lower`, SHORT at
`price_upper`), exit kind SETTLEMENT, exit fee at the exit fee rate, slippage zero.

Hand oracle of the tracer case (LONG, zone 99.00-101.00 -> limit 100.00, quantity 10 from the
stand-in risk function, baseline-v5 costs: fee 0.0005 both ways, entry slippage 0.0001, the
SETTLEMENT leg slippage 0, interval [90.5, 110.5], funding row 08:00 rate 0.0001 mark 100):

    gross_pnl     = (90.5 - 100) x 10 = -95
    entry fee     = 100 x 10 x 0.0005 = 0.5     entry slippage = 100 x 10 x 0.0001 = 0.1
    exit fee      = 90.5 x 10 x 0.0005 = 0.4525 exit slippage  = 0
    funding       = -(+1) x 10 x 100 x 0.0001 = -0.1 (LONG pays)
    realized_pnl  = -95 - 0.5 - 0.4525 - 0.1 - 0.1 = -96.1525
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.backtest import semantics
from src.backtest.case import parse_case_input
from src.backtest.engine import EngineRun, simulate_detailed
from src.backtest.records import BOOKING_EXIT
from src.backtest.semantics import (
    EXIT_KINDS,
    EXIT_SETTLEMENT,
    SETTLEMENT_NOTE_PREFIX,
    TERMINAL_EVALUATION_UNION_ADVERSE_BOUND,
    TERMINAL_KIND_BOUNDED_BY_INDEX_KLINES,
)

from tests.backtest_case_helpers import (
    at,
    bar_row,
    constraint_row,
    fixed_risk_fn,
    flat_minutes,
    funding_row,
    make_case,
    minute_close,
    minute_row,
    scripted_plan,
)

REEF = "REEFUSDT"
TERMINAL = at(9, 0)
PRICE_LOWER = "90.5"
PRICE_UPPER = "110.5"
SIGNAL = datetime(2026, 1, 5, 1, 59, 59, 999000, tzinfo=UTC)

LONG_NOTE = (
    "terminal_settlement SETTLEMENT side=LONG bound=price_lower price=90.5 "
    "interval=[90.5, 110.5] kind=BOUNDED_BY_INDEX_KLINES evaluation=UNION_ADVERSE_BOUND "
    "(settlement price unknown; the bound is an unverified assumption)"
)
SHORT_NOTE = (
    "terminal_settlement SETTLEMENT side=SHORT bound=price_upper price=110.5 "
    "interval=[90.5, 110.5] kind=BOUNDED_BY_INDEX_KLINES evaluation=UNION_ADVERSE_BOUND "
    "(settlement price unknown; the bound is an unverified assumption)"
)


def settlement_row(
    symbol: str = REEF,
    terminal: datetime = TERMINAL,
    lower: str = PRICE_LOWER,
    upper: str = PRICE_UPPER,
) -> dict[str, str]:
    """One `terminal_settlements` row (all strings, the shape plan 02 emits)."""
    return {
        "symbol": symbol,
        "terminal_at_utc": terminal.isoformat(),
        "price_lower": lower,
        "price_upper": upper,
        "kind": TERMINAL_KIND_BOUNDED_BY_INDEX_KLINES,
        "recorded_evaluation": TERMINAL_EVALUATION_UNION_ADVERSE_BOUND,
    }


def settled_case(
    *,
    direction: str = "LONG",
    declare: bool = True,
    rows: list[dict[str, str]] | None = None,
    mark_minutes: list[dict[str, str]] | None = None,
    funding: list[dict[str, Any]] | None = None,
    plan: dict[str, Any] | None = None,
    extra_trade_minutes: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """REEF-geometry case: a scripted plan filled at 02:01 and never stopped, T = 09:00.

    The last declared 1h bar (08:00) closes 1 ms before T, mark minutes run to the minute
    closing 1 ms before T, and the only funding rows lie before T.
    """
    trade = [
        minute_row(REEF, at(2, 0), "100.60", "100.70", "100.40", "100.60", kind="trade"),
        minute_row(REEF, at(2, 1), "100.20", "100.30", "99.80", "100.00", kind="trade"),
    ]
    if direction == "SHORT":
        trade = [
            minute_row(REEF, at(2, 0), "99.40", "99.60", "99.30", "99.40", kind="trade"),
            minute_row(REEF, at(2, 1), "99.80", "100.20", "99.70", "100.00", kind="trade"),
        ]
    trade.extend(extra_trade_minutes or [])
    marks = (
        mark_minutes
        if mark_minutes is not None
        else flat_minutes(REEF, at(2, 0), 420, "100.00", kind="mark")
    )
    rate_rows = funding or [
        funding_row(REEF, datetime(2026, 1, 4, 16, 0, tzinfo=UTC), "0", "100"),
        funding_row(REEF, at(0, 0), "0", "100"),
        funding_row(REEF, at(8, 0), "0.0001", "100"),
    ]
    scripted = plan or (
        scripted_plan(REEF, SIGNAL, "sig-reef", direction)
        if direction == "LONG"
        else scripted_plan(
            REEF,
            SIGNAL,
            "sig-reef",
            "SHORT",
            entry_min="99.00",
            entry_max="101.00",
            stop="102.00",
            tp1="96.00",
            tp2="92.00",
        )
    )
    case = make_case(
        symbols=(REEF,),
        scripted=[scripted],
        strategy_bars=[bar_row(REEF, at(8, 0), "100", "100.2", "99.8", "100")],
        trade_minutes=trade,
        mark_minutes=marks,
        funding=rate_rows,
        constraints=[constraint_row(REEF)],
    )
    if declare:
        case["terminal_settlements"] = rows if rows is not None else [settlement_row()]
    return case


def run_settled(case: dict[str, Any]) -> EngineRun:
    return simulate_detailed(case, risk_fn=fixed_risk_fn("10", "50"))


def test_vocabulary_constants_are_pinned() -> None:
    assert semantics.EXIT_SETTLEMENT == "SETTLEMENT"
    assert semantics.SETTLEMENT_CANCEL == "SETTLEMENT_CANCEL"
    assert semantics.NO_TRADE_TERMINAL == "TERMINAL_BEFORE_ACTIVATION"
    assert semantics.TERMINAL_KIND_BOUNDED_BY_INDEX_KLINES == "BOUNDED_BY_INDEX_KLINES"
    assert semantics.TERMINAL_EVALUATION_UNION_ADVERSE_BOUND == "UNION_ADVERSE_BOUND"
    assert semantics.SETTLEMENT_NOTE_PREFIX == "terminal_settlement"
    assert EXIT_SETTLEMENT in EXIT_KINDS
    assert semantics.SETTLEMENT_CANCEL in semantics.ENTRY_KINDS
    assert semantics.SIMULATOR_SEMANTICS_VERSION == "2.0.0"


def test_tracer_open_long_settles_at_price_lower_at_the_terminal_instant() -> None:
    run = run_settled(settled_case())

    assert len(run.output["trades"]) == 1
    trade = run.output["trades"][0]
    assert trade["exit_kind"] == "SETTLEMENT"
    assert Decimal(trade["exit_price"]) == Decimal(PRICE_LOWER)
    assert trade["exit_time_utc"] == TERMINAL.isoformat()
    assert trade["exit_time_utc"] > minute_close(at(8, 59)).isoformat()
    assert Decimal(trade["entry_price"]) == Decimal("100.00")
    assert Decimal(trade["quantity"]) == Decimal("10")
    # Slippage of the entry only: the SETTLEMENT leg carries none.
    assert Decimal(trade["slippage_amount"]) == Decimal("0.1")
    assert trade["coverage_note"] == LONG_NOTE
    assert trade["coverage_note"].startswith(SETTLEMENT_NOTE_PREFIX)

    exits = [b for b in run.bookings if b.kind == BOOKING_EXIT]
    assert len(exits) == 1
    assert exits[0].time_utc == TERMINAL
    assert exits[0].symbol == REEF


def test_case_without_terminal_settlements_parses_to_an_empty_tuple() -> None:
    parsed = parse_case_input(settled_case(declare=False))

    assert parsed.terminal_settlements == ()
