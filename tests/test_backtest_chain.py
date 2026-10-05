"""Evidence chain: simulator -> normalizer -> excursion on v2 records (Phase 14, plan 14-11).

The v2 engine emits TradeRecord dicts; the analytics layer normalizes TradeRecord objects.
These tests drive the whole chain with a scripted multi-plan case, prove that the shared
temporal validator runs again at the normalizer boundary (D-23, F-804) and that the
analytics vocabulary accepts the v2 entry and exit kinds (D-34, D-11).

Plan 14-15 adds the shared dict -> TradeRecord converter; until then a local one is used.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from src.analytics.excursion import build_excursion_section, compute_trade_excursion
from src.analytics.inputs import normalize_backtest
from src.analytics.lifecycle import normalize_backtest_lifecycle
from src.analytics.types import (
    AnalyticsInputError,
    EvidenceKind,
    IncompleteReason,
    NoTradeRecord,
    TradeOutcome,
)
from src.backtest.engine import simulate
from src.backtest.records import TradeRecord
from src.backtest.validator import TradeRecordInvariantError
from src.core.types import Candle
from src.domain.enums import DailyState
from src.risk.types import PortfolioVerdict

from tests.backtest_case_helpers import (
    SIGNAL_CLOSE,
    at,
    fixed_risk_fn,
    flat_minutes,
    make_case,
    minute_row,
    scripted_plan,
)
from tests.phase10_helpers import make_candle, make_outcome, parse_utc

SYMBOLS = ("ADAUSDT", "BTCUSDT", "ETHUSDT", "LTCUSDT", "SOLUSDT")

_DECIMAL_FIELDS = frozenset(
    {
        "entry_price",
        "quantity",
        "exit_price",
        "realized_pnl",
        "realized_risk",
        "gross_pnl",
        "entry_fee",
        "exit_fee",
        "funding_amount",
        "slippage_amount",
        "modeled_costs_per_unit",
        "planned_quantity",
        "tp1_quantity",
        "tp1_price",
    }
)
_DATETIME_FIELDS = frozenset(
    {"entry_time_utc", "exit_time_utc", "signal_close_utc", "tp1_time_utc", "resolved_at_utc"}
)


def record_from_dict(row: dict[str, Any]) -> TradeRecord:
    """Rebuild a TradeRecord from an engine output dict (Decimal and datetime fields parsed)."""
    fields: dict[str, Any] = {}
    for name, value in row.items():
        if value is not None and name in _DECIMAL_FIELDS:
            fields[name] = Decimal(value)
        elif value is not None and name in _DATETIME_FIELDS:
            fields[name] = datetime.fromisoformat(value)
        else:
            fields[name] = value
    return TradeRecord(**fields)


def go_through(symbol: str, when: datetime) -> dict[str, str]:
    """A trade minute that trades through a 100.00 LONG limit."""
    return minute_row(symbol, when, "100.20", "100.30", "99.80", "100.00", kind="trade")


def mark_minute(
    symbol: str, when: datetime, open_: str, high: str, low: str, close: str
) -> dict[str, str]:
    return minute_row(symbol, when, open_, high, low, close, kind="mark")


def chain_case() -> dict[str, Any]:
    """BTC stops out, ETH takes TP1 then TP2, ADA expires, SOL is closed at data end, LTC rejects.

    Zone 99-101 gives limit 100.00, stop 98.00, TP1 104.00, TP2 108.00. Every symbol except
    ADA fills on the 10:01 trade minute; ADA's trade minutes stay above the limit.
    """
    trades: list[dict[str, str]] = []
    marks: list[dict[str, str]] = []
    for symbol in SYMBOLS:
        trades += flat_minutes(symbol, at(10, 0), 1, "105.00", kind="trade")
        trades.append(
            go_through(symbol, at(10, 1))
            if symbol != "ADAUSDT"
            else flat_minutes(symbol, at(10, 1), 1, "105.00", kind="trade")[0]
        )
        trades += flat_minutes(symbol, at(10, 2), 118, "105.00", kind="trade")
    for symbol in ("ADAUSDT", "LTCUSDT", "SOLUSDT"):
        marks += flat_minutes(symbol, at(10, 0), 120, "100.00", kind="mark")
    marks += [
        *flat_minutes("BTCUSDT", at(10, 0), 40, "100.00", kind="mark"),
        mark_minute("BTCUSDT", at(10, 40), "98.50", "98.60", "97.90", "98.20"),
        *flat_minutes("BTCUSDT", at(10, 41), 79, "98.00", kind="mark"),
    ]
    marks += [
        *flat_minutes("ETHUSDT", at(10, 0), 30, "100.00", kind="mark"),
        mark_minute("ETHUSDT", at(10, 30), "100.00", "104.20", "99.90", "103.00"),
        mark_minute("ETHUSDT", at(10, 31), "103.00", "108.40", "103.00", "108.00"),
        *flat_minutes("ETHUSDT", at(10, 32), 88, "108.00", kind="mark"),
    ]
    plans = [
        scripted_plan("BTCUSDT", SIGNAL_CLOSE, "sig-btc"),
        scripted_plan("ETHUSDT", SIGNAL_CLOSE, "sig-eth", regime="BULLISH"),
        scripted_plan("ADAUSDT", SIGNAL_CLOSE, "sig-ada", expiry_hours=1),
        scripted_plan("SOLUSDT", SIGNAL_CLOSE, "sig-sol"),
        scripted_plan("LTCUSDT", SIGNAL_CLOSE, "sig-ltc"),
    ]
    return make_case(
        symbols=SYMBOLS,
        scripted=plans,
        trade_minutes=trades,
        mark_minutes=marks,
    )


def rejecting_risk_fn() -> Any:
    """Reject `sig-ltc` with a risk reason, size everything else at a hand quantity."""
    sizer = fixed_risk_fn("0.5", "1.50")

    def risk_fn(**kwargs: Any) -> PortfolioVerdict:
        if kwargs["trade_plan"].signal_id == "sig-ltc":
            return PortfolioVerdict(
                is_no_trade=True,
                sized=None,
                reason_code="CLUSTER_CAP_REJECT",
                daily_state=DailyState.NORMAL,
            )
        return sizer(**kwargs)

    return risk_fn


def candles_from_marks(case: dict[str, Any]) -> dict[str, list[Candle]]:
    """Mark minutes of the case as 1m Candles per symbol (the excursion window source)."""
    by_symbol: dict[str, list[Candle]] = {}
    for row in case["mark_bars_1m"]:
        by_symbol.setdefault(row["symbol"], []).append(
            Candle(
                symbol=row["symbol"],
                interval="1m",
                open_time_utc=datetime.fromisoformat(row["open_time_utc"]),
                close_time_utc=datetime.fromisoformat(row["close_time_utc"]),
                open=Decimal(row["open"]),
                high=Decimal(row["high"]),
                low=Decimal(row["low"]),
                close=Decimal(row["close"]),
                volume=Decimal("1"),
            )
        )
    return by_symbol


@pytest.fixture(scope="module")
def chain() -> tuple[dict[str, Any], list[TradeRecord]]:
    case = chain_case()
    output = simulate(case, risk_fn=rejecting_risk_fn())
    return case, [record_from_dict(row) for row in output["trades"]]


def test_the_scripted_case_yields_one_record_of_every_v2_kind(
    chain: tuple[dict[str, Any], list[TradeRecord]],
) -> None:
    _, records = chain
    by_signal = {record.signal_id: record for record in records}
    assert by_signal["sig-btc"].exit_kind == "SL"
    assert by_signal["sig-eth"].exit_kind == "TP2"
    assert by_signal["sig-eth"].tp1_time_utc is not None
    assert by_signal["sig-ada"].entry_kind == "EXPIRED"
    assert by_signal["sig-sol"].exit_kind == "END_OF_DATA"
    assert by_signal["sig-ltc"].outcome_kind == "REJECT"


def test_engine_output_flows_through_normalizer_into_excursion_without_negative_interval(
    chain: tuple[dict[str, Any], list[TradeRecord]],
) -> None:
    case, records = chain
    normalized = normalize_backtest(records)

    assert [reject.symbol for reject in normalized.rejects] == ["LTCUSDT"]
    assert isinstance(normalized.rejects[0], NoTradeRecord)
    assert len(normalized.outcomes) == 4
    assert all(isinstance(outcome, TradeOutcome) for outcome in normalized.outcomes)

    candles = candles_from_marks(case)
    filled = [outcome for outcome in normalized.outcomes if outcome.entry_price is not None]
    assert {outcome.symbol for outcome in filled} == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    for outcome in filled:
        excursion = compute_trade_excursion(outcome, candles[outcome.symbol])
        assert excursion.incomplete_reason is not IncompleteReason.NEGATIVE_INTERVAL
        assert excursion.incomplete_reason is None, (outcome.symbol, excursion.incomplete_reason)

    section = build_excursion_section(
        normalized.outcomes, candles, evidence=EvidenceKind.BACKTEST, resamples=100
    )
    reasons = dict(section.incomplete)
    assert IncompleteReason.NEGATIVE_INTERVAL.value not in reasons
    assert section.n_measured == 3
    # ETH took its profit: the TP2 exit feeds the take-profit diagnostic.
    assert section.mae_r_of_tp_exits.n == 1


def test_a_record_entering_at_its_signal_close_is_refused_at_the_normalizer_boundary(
    chain: tuple[dict[str, Any], list[TradeRecord]],
) -> None:
    _, records = chain
    filled = next(record for record in records if record.exit_kind == "SL")
    assert filled.entry_time_utc is not None
    broken = dataclasses.replace(filled, signal_close_utc=filled.entry_time_utc)

    with pytest.raises(AnalyticsInputError) as caught:
        normalize_backtest([broken])
    assert isinstance(caught.value.__cause__, TradeRecordInvariantError)
    assert filled.trade_id in str(caught.value)


def test_a_record_whose_exit_precedes_its_entry_is_refused_at_the_normalizer_boundary(
    chain: tuple[dict[str, Any], list[TradeRecord]],
) -> None:
    _, records = chain
    filled = next(record for record in records if record.exit_kind == "SL")
    assert filled.entry_time_utc is not None
    broken = dataclasses.replace(filled, exit_time_utc=filled.entry_time_utc - timedelta(seconds=1))

    with pytest.raises(AnalyticsInputError) as caught:
        normalize_backtest([broken])
    assert isinstance(caught.value.__cause__, TradeRecordInvariantError)


@pytest.mark.parametrize(
    ("kind", "filled"),
    [
        ("ENTRY_FILLED", True),
        ("PARTIAL_FILL", True),
        ("EXPIRED", False),
        ("INVALIDATION_CANCEL", False),
        ("DAILY_STOP_CANCEL", False),
        ("PENDING_AT_DATA_END", False),
        ("TOUCH_NO_FILL", False),
    ],
)
def test_lifecycle_normalization_accepts_the_v2_entry_kinds(kind: str, filled: bool) -> None:
    (record,) = normalize_backtest_lifecycle([make_outcome(trade_id="A", entry_kind=kind)])
    assert record.entry_filled is filled


def test_lifecycle_normalization_still_refuses_an_unknown_entry_kind() -> None:
    with pytest.raises(AnalyticsInputError):
        normalize_backtest_lifecycle([make_outcome(trade_id="A", entry_kind="MYSTERY")])


def test_the_excursion_take_profit_group_holds_tp1_and_tp2_exits() -> None:
    entry = "2026-01-05T10:00:30+00:00"
    exit_time = "2026-01-05T10:02:30+00:00"
    outcomes = [
        make_outcome(
            trade_id=f"T-{kind}",
            entry_price="100",
            entry_time_utc=entry,
            exit_kind=kind,
            exit_price="104",
            exit_time_utc=exit_time,
            quantity="1",
            realized_pnl="4",
            realized_risk="2",
        )
        for kind in ("TP1", "TP2", "SL")
    ]
    candles = [
        make_candle("BTCUSDT", parse_utc(f"2026-01-05T10:0{minute}:00+00:00"), "103", "99")
        for minute in range(3)
    ]
    section = build_excursion_section(
        outcomes, {"BTCUSDT": candles}, evidence=EvidenceKind.BACKTEST, resamples=100
    )
    assert section.n_measured == 3
    assert section.mae_r_of_tp_exits.n == 2
    assert section.mfe_r_of_sl_exits.n == 1
