"""Contract tests for the shared trade-record validator (Phase 14, plan 14-01, D-23).

`validate_trade_record` raises `TradeRecordInvariantError` on every violation, never
warns, and skips the data-window check when no window is given (normalizer boundary).
"""

from __future__ import annotations

import warnings
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from src.backtest.validator import TradeRecordInvariantError, validate_trade_record

from tests.backtest_plan_helpers import SIGNAL_CLOSE, make_record

ENTRY = datetime(2026, 1, 5, 10, 1, 59, 999000, tzinfo=UTC)
EXIT = datetime(2026, 1, 5, 10, 30, 59, 999000, tzinfo=UTC)


def test_valid_filled_record_passes_and_never_warns() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert validate_trade_record(make_record()) is None


def test_entry_at_or_before_signal_close_raises_naming_entry_time() -> None:
    with pytest.raises(TradeRecordInvariantError, match="entry_time"):
        validate_trade_record(make_record(entry_time_utc=SIGNAL_CLOSE))
    earlier = datetime(2026, 1, 5, 9, 59, 59, tzinfo=UTC)
    with pytest.raises(TradeRecordInvariantError, match="entry_time"):
        validate_trade_record(make_record(entry_time_utc=earlier, exit_time_utc=EXIT))


def test_filled_record_without_signal_close_raises() -> None:
    with pytest.raises(TradeRecordInvariantError, match="signal_close"):
        validate_trade_record(make_record(signal_close_utc=None))


def test_exit_before_entry_raises_and_exit_equal_entry_passes() -> None:
    before = datetime(2026, 1, 5, 10, 1, 58, tzinfo=UTC)
    with pytest.raises(TradeRecordInvariantError, match="exit_time"):
        validate_trade_record(make_record(exit_time_utc=before))
    validate_trade_record(make_record(exit_time_utc=ENTRY, resolved_at_utc=ENTRY))


def test_tp1_time_outside_the_holding_window_raises() -> None:
    inside = datetime(2026, 1, 5, 10, 10, 59, 999000, tzinfo=UTC)
    validate_trade_record(make_record(tp1_time_utc=inside, tp1_quantity="0.25", tp1_price="104.00"))
    early = datetime(2026, 1, 5, 10, 0, 59, 999000, tzinfo=UTC)
    with pytest.raises(TradeRecordInvariantError, match="tp1_time"):
        validate_trade_record(make_record(tp1_time_utc=early, tp1_quantity="0.25"))
    late = datetime(2026, 1, 5, 11, 0, 59, 999000, tzinfo=UTC)
    with pytest.raises(TradeRecordInvariantError, match="tp1_time"):
        validate_trade_record(make_record(tp1_time_utc=late, tp1_quantity="0.25"))


def test_tp1_quantity_not_below_the_total_quantity_raises() -> None:
    with pytest.raises(TradeRecordInvariantError, match="tp1_quantity"):
        validate_trade_record(make_record(tp1_quantity="0.5"))
    with pytest.raises(TradeRecordInvariantError, match="tp1_quantity"):
        validate_trade_record(make_record(tp1_quantity="0.6"))


def test_exit_outside_the_data_window_raises_when_a_window_is_given() -> None:
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    end = datetime(2026, 1, 6, 0, 0, tzinfo=UTC)
    validate_trade_record(make_record(), data_start_utc=start, data_end_utc=end)
    validate_trade_record(make_record(), data_start_utc=start, data_end_utc=EXIT)  # inclusive end
    with pytest.raises(TradeRecordInvariantError, match="exit_time"):
        validate_trade_record(make_record(), data_start_utc=start, data_end_utc=ENTRY)
    with pytest.raises(TradeRecordInvariantError, match="exit_time"):
        validate_trade_record(make_record(), data_start_utc=end, data_end_utc=None)


def test_window_check_is_skipped_when_no_window_is_given() -> None:
    far_future = datetime(2099, 1, 1, tzinfo=UTC)
    validate_trade_record(make_record(exit_time_utc=far_future, resolved_at_utc=far_future))


def test_filled_quantity_above_planned_raises() -> None:
    with pytest.raises(TradeRecordInvariantError, match="quantity"):
        validate_trade_record(make_record(quantity="0.6", planned_quantity="0.5"))
    validate_trade_record(make_record(quantity="0.4", planned_quantity="0.5"))


def test_non_positive_filled_quantity_raises() -> None:
    with pytest.raises(TradeRecordInvariantError, match="quantity"):
        validate_trade_record(make_record(quantity="0"))
    with pytest.raises(TradeRecordInvariantError, match="quantity"):
        validate_trade_record(make_record(quantity=Decimal("-0.1")))


def test_non_filled_record_with_exit_fields_raises() -> None:
    unfilled = {
        "entry_kind": "EXPIRED",
        "entry_price": None,
        "entry_time_utc": None,
        "quantity": None,
    }
    with pytest.raises(TradeRecordInvariantError, match="exit"):
        validate_trade_record(make_record(**unfilled))  # exit fields still set
    clean = {"exit_kind": None, "exit_price": None, "exit_time_utc": None}
    validate_trade_record(make_record(**unfilled, **clean))


def test_reject_record_passes_with_all_trade_fields_none() -> None:
    validate_trade_record(
        make_record(
            entry_kind="REJECT",
            entry_price=None,
            entry_time_utc=None,
            quantity=None,
            exit_kind=None,
            exit_price=None,
            exit_time_utc=None,
            realized_pnl=None,
            realized_risk=None,
            gross_pnl=None,
            entry_fee=None,
            exit_fee=None,
            funding_amount=None,
            slippage_amount=None,
            signal_close_utc=None,
            planned_quantity=None,
            resolved_at_utc=None,
            outcome_kind="REJECT",
            reason_code="MIN_QTY_REJECT",
        )
    )


def test_entry_kind_outside_the_vocabulary_raises() -> None:
    with pytest.raises(TradeRecordInvariantError, match="entry_kind"):
        validate_trade_record(make_record(entry_kind="TOUCH_NO_FILL"))


def test_exit_kind_outside_the_vocabulary_raises() -> None:
    with pytest.raises(TradeRecordInvariantError, match="exit_kind"):
        validate_trade_record(make_record(exit_kind="EOD"))
    for kind in ("SL", "TP2", "END_OF_DATA"):
        validate_trade_record(make_record(exit_kind=kind))


def test_filled_record_without_planned_quantity_raises() -> None:
    with pytest.raises(TradeRecordInvariantError, match="planned_quantity"):
        validate_trade_record(make_record(planned_quantity=None))


# ----- strict mode (WR-01): the cross-field shape of an engine record ---------------


def test_strict_accepts_a_valid_closed_record() -> None:
    validate_trade_record(make_record(), strict=True)


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"entry_kind": "EXPIRED"}, "entry_kind"),
        ({"entry_kind": "PARTIAL_FILL"}, "PARTIAL_FILL"),  # quantity == planned_quantity
        ({"quantity": "0.4", "planned_quantity": "0.5"}, "PARTIAL_FILL"),  # ENTRY_FILLED
        ({"entry_price": None}, "entry_price"),
        ({"exit_kind": None, "exit_price": None, "exit_time_utc": None}, "exit_kind"),
        ({"realized_pnl": None}, "realized_pnl"),
        ({"realized_risk": None}, "realized_risk"),
    ],
)
def test_strict_refuses_an_inconsistent_filled_record(overrides: dict, match: str) -> None:
    record = make_record(**overrides)
    with pytest.raises(TradeRecordInvariantError, match=match):
        validate_trade_record(record, strict=True)


def test_strict_refuses_an_unfilled_record_with_fill_fields() -> None:
    unfilled = {
        "entry_kind": "EXPIRED",
        "entry_price": None,
        "entry_time_utc": None,
        "quantity": None,
        "exit_kind": None,
        "exit_price": None,
        "exit_time_utc": None,
    }
    with pytest.raises(TradeRecordInvariantError, match="realized_pnl"):
        validate_trade_record(make_record(**unfilled), strict=True)  # still carries PnL
    clean = {
        name: None
        for name in (
            "realized_pnl",
            "realized_risk",
            "gross_pnl",
            "entry_fee",
            "exit_fee",
            "funding_amount",
            "slippage_amount",
            "tp1_quantity",
            "tp1_price",
            "tp1_time_utc",
        )
    }
    validate_trade_record(make_record(**unfilled, **clean), strict=True)
    filled_kind = make_record(**{**unfilled, **clean, "entry_kind": "ENTRY_FILLED"})
    with pytest.raises(TradeRecordInvariantError, match="needs a fill"):
        validate_trade_record(filled_kind, strict=True)
