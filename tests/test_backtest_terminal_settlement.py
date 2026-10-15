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

SHORT (same quantity, settled at 110.5): gross -105, exit fee 110.5 x 10 x 0.0005 = 0.5525,
funding +0.1, realized_pnl = -105 - 0.5 - 0.5525 - 0.1 + 0.1 = -106.0525.

TP1 case (LONG, TP1 5 at 104 at 03:00, remainder 5 settled at 90.5):

    gross  = (104 - 100) x 5 + (90.5 - 100) x 5 = -27.5
    fees   = 0.5 + 104 x 5 x 0.0005 + 90.5 x 5 x 0.0005 = 0.5 + 0.26 + 0.22625
    slip   = 0.1 + 104 x 5 x 0.0001 + 0 = 0.152
    fund   = -(5 x 100 x 0.0001) = -0.05 (the remainder only)
    pnl    = -27.5 - 0.98625 - 0.152 - 0.05 = -28.68825
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from src.backtest import semantics
from src.backtest.case import parse_case_input
from src.backtest.engine import EngineRun, simulate_detailed
from src.backtest.lifecycle import (
    EVENT_CANCEL,
    PHASE_CLOSED,
    PHASE_RESTING,
    PlanState,
    new_plan_state,
    settle_at_terminal,
)
from src.backtest.records import BOOKING_EXIT, BOOKING_FILL, BOOKING_FUNDING, BOOKING_TP1
from src.backtest.semantics import (
    EXIT_KINDS,
    EXIT_SETTLEMENT,
    SETTLEMENT_CANCEL,
    SETTLEMENT_NOTE_PREFIX,
    TERMINAL_EVALUATION_UNION_ADVERSE_BOUND,
    TERMINAL_KIND_BOUNDED_BY_INDEX_KLINES,
)
from src.research.report import MARK_HOLE_MARKER, count_mark_hole_trades

from tests.backtest_case_helpers import (
    DATA_END,
    DATA_START,
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
from tests.backtest_plan_helpers import make_trade_plan

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
RESTING_NOTE = (
    "terminal_settlement SETTLEMENT_CANCEL resting entry cancelled at the terminal instant "
    "(unverified assumption)"
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
    rows: list[dict[str, Any]] | None = None,
    mark_minutes: list[dict[str, str]] | None = None,
    funding: list[dict[str, Any]] | None = None,
    with_last_bar: bool = True,
) -> dict[str, Any]:
    """REEF-geometry case: a scripted plan filled at 02:01 and never stopped, T = 09:00.

    The last declared 1h bar (08:00) closes 1 ms before T, mark minutes run to the minute
    closing 1 ms before T, and the only funding rows lie before T (the last one at 08:00, so
    the case stays covered without the funding clip of Task 3).
    """
    if direction == "LONG":
        trade = [
            minute_row(REEF, at(2, 0), "100.60", "100.70", "100.40", "100.60", kind="trade"),
            minute_row(REEF, at(2, 1), "100.20", "100.30", "99.80", "100.00", kind="trade"),
        ]
        scripted = scripted_plan(REEF, SIGNAL, "sig-reef", "LONG")
    else:
        trade = [
            minute_row(REEF, at(2, 0), "99.40", "99.60", "99.30", "99.40", kind="trade"),
            minute_row(REEF, at(2, 1), "99.80", "100.20", "99.70", "100.00", kind="trade"),
        ]
        scripted = scripted_plan(
            REEF, SIGNAL, "sig-reef", "SHORT", stop="102.00", tp1="96.00", tp2="92.00"
        )
    marks = (
        mark_minutes
        if mark_minutes is not None
        else flat_minutes(REEF, at(2, 0), 420, "100.00", kind="mark")
    )
    rate_rows = (
        funding
        if funding is not None
        else [
            funding_row(REEF, datetime(2026, 1, 4, 16, 0, tzinfo=UTC), "0", "100"),
            funding_row(REEF, at(0, 0), "0", "100"),
            funding_row(REEF, at(8, 0), "0.0001", "100"),
        ]
    )
    bars = [bar_row(REEF, at(8, 0), "100", "100.2", "99.8", "100")] if with_last_bar else []
    case = make_case(
        symbols=(REEF,),
        scripted=[scripted],
        strategy_bars=bars,
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


def booking_total(run: EngineRun) -> Decimal:
    return sum((b.amount for b in run.bookings), Decimal("0"))


def tp1_marks() -> list[dict[str, str]]:
    """Mark minutes 02:00-08:59 with TP1 (104) touched at 03:00, flat at 104 afterwards."""
    return [
        *flat_minutes(REEF, at(2, 0), 60, "100.00", kind="mark"),
        minute_row(REEF, at(3, 0), "100.50", "104.50", "100.40", "104.00", kind="mark"),
        *flat_minutes(REEF, at(3, 1), 359, "104.00", kind="mark"),
    ]


def test_vocabulary_constants_are_pinned() -> None:
    assert semantics.EXIT_SETTLEMENT == "SETTLEMENT"
    assert semantics.SETTLEMENT_CANCEL == "SETTLEMENT_CANCEL"
    assert semantics.NO_TRADE_TERMINAL == "TERMINAL_BEFORE_ACTIVATION"
    assert semantics.TERMINAL_KIND_BOUNDED_BY_INDEX_KLINES == "BOUNDED_BY_INDEX_KLINES"
    assert semantics.TERMINAL_EVALUATION_UNION_ADVERSE_BOUND == "UNION_ADVERSE_BOUND"
    assert semantics.SETTLEMENT_NOTE_PREFIX == "terminal_settlement"
    assert EXIT_SETTLEMENT in EXIT_KINDS
    assert semantics.SETTLEMENT_CANCEL in semantics.ENTRY_KINDS
    assert semantics.SIMULATOR_SEMANTICS_VERSION == "2.1.0"


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


def test_open_short_settles_at_price_upper() -> None:
    run = run_settled(settled_case(direction="SHORT"))

    trade = run.output["trades"][0]
    assert trade["direction"] == "SHORT"
    assert trade["exit_kind"] == "SETTLEMENT"
    assert Decimal(trade["exit_price"]) == Decimal(PRICE_UPPER)
    assert trade["exit_time_utc"] == TERMINAL.isoformat()
    assert trade["coverage_note"] == SHORT_NOTE
    # gross (100 - 110.5) x 10 = -105; exit fee 110.5 x 10 x 0.0005 = 0.5525; the SHORT
    # receives the 08:00 funding: +10 x 100 x 0.0001 = +0.1.
    assert Decimal(trade["gross_pnl"]) == Decimal("-105")
    assert Decimal(trade["exit_fee"]) == Decimal("0.5525")
    assert Decimal(trade["funding_amount"]) == Decimal("0.1")
    assert Decimal(trade["realized_pnl"]) == Decimal("-106.0525")


def test_tp1_remainder_settles_at_the_adverse_bound() -> None:
    run = run_settled(settled_case(mark_minutes=tp1_marks()))

    trade = run.output["trades"][0]
    assert Decimal(trade["tp1_quantity"]) == Decimal("5")
    assert Decimal(trade["tp1_price"]) == Decimal("104")
    assert trade["exit_kind"] == "SETTLEMENT"
    assert Decimal(trade["exit_price"]) == Decimal(PRICE_LOWER)
    assert trade["exit_time_utc"] == TERMINAL.isoformat()
    # The SETTLEMENT leg closes only the remainder: 5 of the 10 filled.
    assert Decimal(trade["quantity"]) == Decimal("10")
    assert Decimal(trade["gross_pnl"]) == Decimal("-27.5")
    assert Decimal(trade["exit_fee"]) == Decimal("0.48625")
    assert Decimal(trade["slippage_amount"]) == Decimal("0.152")
    assert Decimal(trade["funding_amount"]) == Decimal("-0.05")
    assert Decimal(trade["realized_pnl"]) == Decimal("-28.68825")
    kinds = [b.kind for b in run.bookings]
    assert kinds.count(BOOKING_TP1) == 1
    assert kinds.count(BOOKING_EXIT) == 1


def test_settlement_fee_is_exit_fee_rate_times_quantity_times_price_and_slippage_zero() -> None:
    run = run_settled(settled_case())

    trade = run.output["trades"][0]
    assert Decimal(trade["gross_pnl"]) == Decimal("-95")
    assert Decimal(trade["entry_fee"]) == Decimal("0.5")
    assert Decimal(trade["exit_fee"]) == Decimal("0.4525")  # 90.5 x 10 x 0.0005
    assert Decimal(trade["slippage_amount"]) == Decimal("0.1")  # entry only
    assert Decimal(trade["funding_amount"]) == Decimal("-0.1")
    assert Decimal(trade["realized_pnl"]) == Decimal("-96.1525")
    exit_booking = next(b for b in run.bookings if b.kind == BOOKING_EXIT)
    assert exit_booking.amount == Decimal("-95.4525")  # gross - exit fee, slippage 0


@pytest.mark.parametrize(
    ("direction", "marks"),
    [("LONG", None), ("SHORT", None), ("LONG", "tp1")],
    ids=["long", "short", "long-after-tp1"],
)
def test_ledger_bookings_sum_to_record_realized_pnl(direction: str, marks: str | None) -> None:
    case = settled_case(direction=direction, mark_minutes=tp1_marks() if marks else None)
    run = run_settled(case)

    trade = run.output["trades"][0]
    kinds = {b.kind for b in run.bookings}
    assert {BOOKING_FILL, BOOKING_EXIT, BOOKING_FUNDING} <= kinds
    assert booking_total(run) == Decimal(trade["realized_pnl"])


@pytest.mark.parametrize(("direction", "note"), [("LONG", LONG_NOTE), ("SHORT", SHORT_NOTE)])
def test_settlement_coverage_note_has_the_fixed_text(direction: str, note: str) -> None:
    run = run_settled(settled_case(direction=direction))

    assert run.output["trades"][0]["coverage_note"] == note


def test_no_mark_hole_marker_between_last_mark_minute_and_terminal() -> None:
    # Mark minutes end at 08:38 (the minute closing 20+ minutes before T) and no bar closes in
    # the stretch up to T: the delisting gap must not read as a mark-price hole (design 3.7).
    marks = flat_minutes(REEF, at(2, 0), 399, "100.00", kind="mark")
    assert marks[-1]["open_time_utc"] == at(8, 38).isoformat()
    run = run_settled(settled_case(mark_minutes=marks, with_last_bar=False))

    trade = run.output["trades"][0]
    assert trade["exit_kind"] == "SETTLEMENT"
    assert trade["exit_time_utc"] == TERMINAL.isoformat()
    assert trade["coverage_note"] == LONG_NOTE
    assert MARK_HOLE_MARKER not in trade["coverage_note"]
    assert count_mark_hole_trades([trade]) == 0


@pytest.mark.parametrize("with_last_bar", [True, False], ids=["bar-window", "single-window"])
def test_stop_on_the_last_minute_before_the_terminal_books_sl_not_settlement(
    with_last_bar: bool,
) -> None:
    marks = [
        *flat_minutes(REEF, at(2, 0), 419, "100.00", kind="mark"),
        minute_row(REEF, at(8, 59), "98.50", "98.60", "97.90", "98.20", kind="mark"),
    ]
    run = run_settled(settled_case(mark_minutes=marks, with_last_bar=with_last_bar))

    assert len(run.output["trades"]) == 1
    trade = run.output["trades"][0]
    assert trade["exit_kind"] == "SL"
    assert trade["exit_time_utc"] == minute_close(at(8, 59)).isoformat()
    assert Decimal(trade["exit_price"]) == Decimal("98.00")
    assert SETTLEMENT_NOTE_PREFIX not in (trade["coverage_note"] or "")
    exits = [b for b in run.bookings if b.kind == BOOKING_EXIT]
    assert [b.time_utc for b in exits] == [minute_close(at(8, 59))]


def _resting_state() -> PlanState:
    return new_plan_state(
        plan=make_trade_plan("LONG"),
        symbol="BTCUSDT",
        direction="LONG",
        signal_close_utc=SIGNAL,
        price_tick_size=Decimal("0.10"),
        planned_quantity=Decimal("0.5"),
        sized_realized_risk=Decimal("1.50"),
    )


def _settle(state: PlanState, **overrides: Any) -> Any:
    arguments: dict[str, Any] = {
        "terminal_at_utc": TERMINAL,
        "price_lower": Decimal(PRICE_LOWER),
        "price_upper": Decimal(PRICE_UPPER),
        "kind": TERMINAL_KIND_BOUNDED_BY_INDEX_KLINES,
        "recorded_evaluation": TERMINAL_EVALUATION_UNION_ADVERSE_BOUND,
    }
    arguments.update(overrides)
    return settle_at_terminal(state, **arguments)


def test_settle_at_terminal_cancels_a_resting_plan_with_settlement_cancel() -> None:
    state = _resting_state()
    assert state.phase == PHASE_RESTING

    closed, events = _settle(state)

    assert closed.phase == PHASE_CLOSED
    assert closed.entry_kind == SETTLEMENT_CANCEL
    assert closed.resolved_at_utc == TERMINAL
    assert closed.coverage_note == RESTING_NOTE
    assert len(events) == 1
    assert events[0].kind == EVENT_CANCEL
    assert events[0].time_utc == TERMINAL
    assert events[0].entry_kind == SETTLEMENT_CANCEL
    assert events[0].price is None
    assert events[0].quantity is None


def test_settle_at_terminal_leaves_a_closed_plan_unchanged() -> None:
    closed_state = dataclasses.replace(_resting_state(), phase=PHASE_CLOSED, entry_kind="EXPIRED")

    state, events = _settle(closed_state)

    assert state is closed_state
    assert events == ()


@pytest.mark.parametrize(
    "overrides",
    [
        {"terminal_at_utc": datetime(2026, 1, 5, 9, 0)},
        {"terminal_at_utc": datetime(2026, 1, 5, 9, 0, 30, tzinfo=UTC)},
        {"terminal_at_utc": datetime(2026, 1, 5, 9, 0, 0, 1, tzinfo=UTC)},
        {"price_lower": Decimal("110.5")},
        {"price_lower": Decimal("120")},
        {"price_lower": Decimal("0")},
        {"kind": "OTHER"},
        {"recorded_evaluation": "OTHER"},
    ],
    ids=[
        "naive",
        "seconds",
        "microseconds",
        "lower-equals-upper",
        "lower-above-upper",
        "non-positive",
        "kind",
        "evaluation",
    ],
)
def test_settle_at_terminal_refuses_malformed_arguments(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _settle(_resting_state(), **overrides)


def _bad(key: str, value: Any) -> list[dict[str, Any]]:
    return [{**settlement_row(), key: value}]


def _without(key: str) -> list[dict[str, Any]]:
    row: dict[str, Any] = dict(settlement_row())
    del row[key]
    return [row]


REFUSALS: list[tuple[str, list[dict[str, Any]], str]] = [
    ("empty-list", [], "must not be empty"),
    ("unknown-key", [{**settlement_row(), "extra": "x"}], "unknown keys"),
    ("missing-key", _without("price_lower"), "missing keys"),
    ("float-price", _bad("price_lower", 90.5), "float"),
    ("int-price", _bad("price_lower", 90), "must be a string"),
    ("null-kind", _bad("kind", None), "must be a string"),
    ("symbol-not-declared", _bad("symbol", "BTCUSDT"), "not in symbols"),
    ("duplicate-symbol", [settlement_row(), settlement_row()], "two rows"),
    ("naive-time", _bad("terminal_at_utc", "2026-01-05T09:00:00"), "UTC-aware"),
    ("non-utc-time", _bad("terminal_at_utc", "2026-01-05T09:00:00+02:00"), "must be UTC"),
    ("seconds", _bad("terminal_at_utc", "2026-01-05T09:00:30+00:00"), "minute-aligned"),
    ("microseconds", _bad("terminal_at_utc", "2026-01-05T09:00:00.000001+00:00"), "minute-aligned"),
    ("at-window-start", _bad("terminal_at_utc", DATA_START.isoformat()), "strictly inside"),
    ("at-window-end", _bad("terminal_at_utc", DATA_END.isoformat()), "strictly inside"),
    ("after-window", _bad("terminal_at_utc", "2026-01-06T09:00:00+00:00"), "strictly inside"),
    ("non-canonical-price", _bad("price_lower", "90.50"), "canonical decimal text"),
    ("exponent-price", _bad("price_upper", "1.1E+2"), "canonical decimal text"),
    ("lower-equals-upper", _bad("price_lower", PRICE_UPPER), "price_lower"),
    ("lower-above-upper", _bad("price_lower", "120"), "price_lower"),
    ("zero-price", _bad("price_lower", "0"), "must be > 0"),
    ("negative-price", _bad("price_lower", "-1"), "must be > 0"),
    ("unknown-kind", _bad("kind", "OTHER"), "kind must be"),
    ("unknown-evaluation", _bad("recorded_evaluation", "OTHER"), "recorded_evaluation must be"),
]


@pytest.mark.parametrize(
    ("rows", "message"), [(r, m) for _, r, m in REFUSALS], ids=[i for i, _, _ in REFUSALS]
)
def test_case_refuses_malformed_terminal_rows(rows: list[dict[str, Any]], message: str) -> None:
    with pytest.raises((ValueError, TypeError), match=message):
        parse_case_input(settled_case(rows=rows))


def test_case_parses_a_valid_row_into_decimals() -> None:
    parsed = parse_case_input(settled_case())

    assert len(parsed.terminal_settlements) == 1
    row = parsed.terminal_settlements[0]
    assert row.symbol == REEF
    assert row.terminal_at_utc == TERMINAL
    assert row.price_lower == Decimal(PRICE_LOWER)
    assert row.price_upper == Decimal(PRICE_UPPER)
    assert row.kind == TERMINAL_KIND_BOUNDED_BY_INDEX_KLINES
    assert row.recorded_evaluation == TERMINAL_EVALUATION_UNION_ADVERSE_BOUND
