"""`entry_price` float noise never becomes a noisy Decimal at the SDK boundary (plan 24-21; D-34).

Demo finding (2026-10-04): `snapshot_positions` returned `entry_price` `84816.40000000001`. The
chosen path, pinned here:

1. The installed SDK model (`PositionInformationV3ResponseInner`, SDK 17.4.0) types `entryPrice`
   as a strict STRING, so the exchange's own text reaches the adapter and `Decimal(text)` is exact:
   "84816.4" stays `Decimal("84816.4")`, with no float anywhere. A JSON number is refused by the
   model's validation (the SDK then hands back raw dicts, which the adapter refuses loudly).
2. Defence in depth: a row object that still carries a float (a model built without validation, a
   different SDK version) is converted through its shortest text, never rounded or quantized, and
   the snapshot says so with `entry_price_from_float=True`, which the reconcile bound check and the
   liquidation estimate can read. The noise itself cannot be repaired from a float; that residual is
   carried to Phase 25.

Evidence label: executed tests on fake SDK rows; no network.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    PositionInformationV3Response,
    PositionInformationV3ResponseInner,
)
from src.adapters.binance_usdm import PositionSnapshot, _row_to_position_snapshot

FIELDS: dict[str, Any] = {
    "symbol": "BTCUSDT",
    "position_side": "BOTH",
    "position_amt": "0.001",
    "entry_price": "84816.4",
    "break_even_price": "84850.0",
    "mark_price": "84800.0",
    "un_realized_profit": "-0.0165",
    "liquidation_price": "0",
    "notional": "84.8",
    "margin_asset": "USDT",
    "update_time": 1790770020000,
}


def _row(**overrides: Any) -> PositionInformationV3ResponseInner:
    return PositionInformationV3ResponseInner(**{**FIELDS, **overrides})


def test_the_exchange_string_is_carried_exactly() -> None:
    snapshot = _row_to_position_snapshot(_row())

    assert snapshot is not None
    assert snapshot.entry_price == Decimal("84816.4")
    assert str(snapshot.entry_price) == "84816.4"
    assert snapshot.entry_price_from_float is False


def test_a_long_exchange_string_is_not_shortened_or_rounded() -> None:
    snapshot = _row_to_position_snapshot(_row(entry_price="84816.40000000001"))

    assert snapshot is not None
    assert snapshot.entry_price == Decimal("84816.40000000001")
    assert snapshot.entry_price_from_float is False, "a string is the exchange's own text"


def test_a_row_parsed_from_the_raw_json_keeps_the_string_the_exchange_sent() -> None:
    text = json.dumps(
        [{"symbol": "BTCUSDT", "positionAmt": "0.001", "entryPrice": "84816.4", "updateTime": 1}]
    )

    rows = PositionInformationV3Response.from_dict(json.loads(text))

    assert rows is not None
    assert type(rows[0].entry_price) is str and rows[0].entry_price == "84816.4"


def test_the_sdk_model_refuses_a_json_number_for_the_entry_price() -> None:
    """A float cannot enter through the validated model, so no noise appears on that path."""
    with pytest.raises(ValueError):
        PositionInformationV3Response.from_dict(
            [{"symbol": "BTCUSDT", "positionAmt": "0.001", "entryPrice": 84816.40000000001}]
        )


def test_a_float_that_reaches_the_boundary_is_converted_by_text_and_flagged() -> None:
    row = PositionInformationV3ResponseInner.model_construct(
        **{**FIELDS, "entry_price": 84816.40000000001}
    )

    snapshot = _row_to_position_snapshot(row)

    assert snapshot is not None
    assert snapshot.entry_price == Decimal("84816.40000000001"), "never rounded or quantized"
    assert snapshot.entry_price_from_float is True
    assert not isinstance(snapshot.entry_price, float)


def test_a_float_without_noise_is_still_flagged_because_the_source_is_not_the_exchange_text() -> (
    None
):
    row = PositionInformationV3ResponseInner.model_construct(**{**FIELDS, "entry_price": 84816.4})

    snapshot = _row_to_position_snapshot(row)

    assert snapshot is not None
    assert snapshot.entry_price == Decimal("84816.4")
    assert snapshot.entry_price_from_float is True


def test_a_non_finite_float_is_refused() -> None:
    row = PositionInformationV3ResponseInner.model_construct(
        **{**FIELDS, "entry_price": float("nan")}
    )

    with pytest.raises(ValueError, match="entryPrice"):
        _row_to_position_snapshot(row)


def test_a_missing_entry_price_stays_zero_and_unflagged() -> None:
    snapshot = _row_to_position_snapshot(_row(entry_price=None))

    assert snapshot is not None
    assert snapshot.entry_price == Decimal("0") and snapshot.entry_price_from_float is False


def test_a_raw_dict_row_from_a_failed_model_parse_is_refused_loudly() -> None:
    """When the SDK cannot validate a body it hands back raw dicts; they never become a snapshot."""
    raw: Any = {"symbol": "BTCUSDT", "positionAmt": "0.001", "entryPrice": 84816.40000000001}

    with pytest.raises(AttributeError):
        _row_to_position_snapshot(raw)


def test_the_snapshot_flag_defaults_to_false_for_every_older_construction() -> None:
    snapshot = PositionSnapshot(
        symbol="BTCUSDT",
        position_side="BOTH",
        position_amt=Decimal("1"),
        entry_price=Decimal("1"),
        break_even_price=Decimal("1"),
        mark_price=None,
        unrealized_profit=Decimal("0"),
        liquidation_price=None,
        notional=None,
        margin_asset="USDT",
        update_time_utc=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert snapshot.entry_price_from_float is False
