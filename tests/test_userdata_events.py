"""ORDER_TRADE_UPDATE tracer tests (Phase 18, plan 18-03 Task 1).

A synthetic ORDER_TRADE_UPDATE TRADE frame (FRAME_LABEL
SYNTHETIC_FROM_SDK_MODEL, never captured Binance data) becomes a frozen
`OrderUpdateEvent`, then a `FillEvent`, then a `FoldedPositionView` through
the unchanged idempotent `fold_fills`, with commission, commission asset,
realized PnL and the maker flag carried (D-06, G3-009). Anything that does not
validate is a `StreamAnomaly`, never coerced (D-05, research P17).

No network: every frame comes from `tests/support/userdata_frames.py`.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from src.adapters.binance_userdata_events import (
    OrderUpdateEvent,
    StreamAnomaly,
    StreamAnomalyKind,
    normalize_event_name,
    parse_order_trade_update,
    parse_stream_message,
    to_fill_event,
    unwrap_message,
)
from src.execution.fill_monitor import CurrentPositionView, FillEvent, fold_fills

from tests.support.userdata_frames import (
    FRAME_LABEL,
    OMIT,
    SYNTHETIC_EVENT_TIME_MS,
    SYNTHETIC_TRADE_TIME_MS,
    SYNTHETIC_TRANSACTION_TIME_MS,
    order_trade_update_frame,
)

OBSERVED_AT = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _parse(frame: Any) -> OrderUpdateEvent | StreamAnomaly:
    return parse_stream_message(frame, observed_at_utc=OBSERVED_AT)


def _event(frame: Any) -> OrderUpdateEvent:
    outcome = _parse(frame)
    assert isinstance(outcome, OrderUpdateEvent), outcome
    return outcome


def _anomaly(frame: Any) -> StreamAnomaly:
    outcome = _parse(frame)
    assert isinstance(outcome, StreamAnomaly), outcome
    return outcome


def _flat_view() -> CurrentPositionView:
    return CurrentPositionView(symbol="BTCUSDT", position_side="BOTH", position_amt=Decimal("0"))


# --------------------------------------------------------------------------- #
# Provenance of the frames.
# --------------------------------------------------------------------------- #


def test_frames_are_labelled_synthetic_from_the_sdk_model() -> None:
    assert FRAME_LABEL == "SYNTHETIC_FROM_SDK_MODEL"


# --------------------------------------------------------------------------- #
# The tracer: frame -> OrderUpdateEvent -> FillEvent -> FoldedPositionView.
# --------------------------------------------------------------------------- #


def test_trade_frame_parses_to_a_typed_order_update_event() -> None:
    event = _event(order_trade_update_frame())

    assert event.symbol == "BTCUSDT"
    assert event.client_order_id == "synthetic-entry-0001"
    assert event.side == "BUY"
    assert event.order_type == "LIMIT"
    assert event.original_order_type == "LIMIT"
    assert event.time_in_force == "GTC"
    assert event.position_side == "BOTH"
    assert event.execution_type == "TRADE"
    assert event.order_status == "PARTIALLY_FILLED"
    # The int `i` and `t` become text; nothing is synthesized.
    assert event.exchange_order_id == "8000000001"
    assert event.trade_id == "900000001"
    # Money, quantity and price fields are Decimal built from the wire string.
    assert event.original_quantity == Decimal("0.010")
    assert event.original_price == Decimal("60000.00")
    assert event.average_price == Decimal("60000.00")
    assert event.stop_price == Decimal("0")
    assert event.last_filled_quantity == Decimal("0.004")
    assert event.accumulated_filled_quantity == Decimal("0.004")
    assert event.last_filled_price == Decimal("60000.00")
    assert event.commission == Decimal("0.09600000")
    assert event.commission_asset == "USDT"
    assert event.realized_profit == Decimal("0")
    assert event.is_maker is False
    assert event.reduce_only is False
    assert event.working_type == "CONTRACT_PRICE"
    assert event.stp_mode == "EXPIRE_TAKER"
    assert event.price_match == "NONE"
    assert event.modify_id is None
    assert event.expire_reason is None
    # Millisecond times convert exactly to UTC-aware datetimes.
    assert event.event_time_utc == _EPOCH + timedelta(milliseconds=SYNTHETIC_EVENT_TIME_MS)
    assert event.transaction_time_utc == _EPOCH + timedelta(
        milliseconds=SYNTHETIC_TRANSACTION_TIME_MS
    )
    assert event.trade_time_utc == _EPOCH + timedelta(milliseconds=SYNTHETIC_TRADE_TIME_MS)
    assert event.trade_time_utc.utcoffset() == timedelta(0)
    for value in dataclasses.astuple(event):
        assert not isinstance(value, float)


def test_order_update_event_is_frozen() -> None:
    event = _event(order_trade_update_frame())
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.symbol = "ETHUSDT"  # type: ignore[misc]


def test_to_fill_event_maps_the_trade_and_carries_commission() -> None:
    event = _event(order_trade_update_frame(m=True, rp="-1.25000000"))
    fill = to_fill_event(event)

    assert fill is not None
    assert fill.order_id == "8000000001"
    assert fill.exchange_trade_id == "900000001"
    assert fill.symbol == "BTCUSDT"
    assert fill.side == "BUY"
    assert fill.position_side == "BOTH"
    assert fill.fill_price == Decimal("60000.00")
    assert fill.fill_quantity == Decimal("0.004")
    assert fill.fill_time_utc == event.trade_time_utc
    assert fill.commission == Decimal("0.09600000")
    assert fill.commission_asset == "USDT"
    assert fill.realized_pnl == Decimal("-1.25000000")
    assert fill.is_maker is True


@pytest.mark.parametrize(
    ("execution_type", "order_status"),
    [
        ("NEW", "NEW"),
        ("CANCELED", "CANCELED"),
        ("EXPIRED", "EXPIRED"),
    ],
)
def test_to_fill_event_returns_none_for_non_trade_execution_types(
    execution_type: str, order_status: str
) -> None:
    frame = order_trade_update_frame(x=execution_type, X=order_status, l="0", z="0", L="0")
    event = _event(frame)
    # The wire carries `t`, but a non-TRADE event never gets a trade id.
    assert event.trade_id is None
    assert to_fill_event(event) is None


def test_non_trade_event_needs_no_fill_fields() -> None:
    frame = order_trade_update_frame(x="NEW", X="NEW", l=OMIT, z=OMIT, L=OMIT, t=OMIT, n=OMIT)
    event = _event(frame)
    assert event.trade_id is None
    assert event.last_filled_quantity is None
    assert to_fill_event(event) is None


def test_to_fill_event_returns_none_for_a_trade_without_positive_quantity() -> None:
    event = _event(order_trade_update_frame(l="0"))
    assert event.execution_type == "TRADE"
    assert to_fill_event(event) is None


def test_replayed_frame_folds_to_one_unique_fill_with_commission_keys() -> None:
    frame = order_trade_update_frame()
    fills = [to_fill_event(_event(frame)), to_fill_event(_event(dict(frame)))]
    assert all(fill is not None for fill in fills)

    view = fold_fills(fill_events=fills, current_position_view=_flat_view())

    assert view.fill_count == 1
    assert view.filled_quantity == Decimal("0.004")
    assert view.position_amt == Decimal("0.004")
    folded = view.fills[0]
    assert folded["order_id"] == "8000000001"
    assert folded["exchange_trade_id"] == "900000001"
    assert folded["commission"] == Decimal("0.09600000")
    assert folded["commission_asset"] == "USDT"
    assert folded["realized_pnl"] == Decimal("0")
    assert folded["is_maker"] is False


def test_two_trades_of_one_order_fold_to_two_fills() -> None:
    first = to_fill_event(_event(order_trade_update_frame()))
    second = to_fill_event(
        _event(order_trade_update_frame(t=900_000_002, l="0.006", z="0.010", X="FILLED"))
    )
    view = fold_fills(fill_events=[second, first], current_position_view=_flat_view())
    assert view.fill_count == 2
    assert view.filled_quantity == Decimal("0.010")
    assert [f["exchange_trade_id"] for f in view.fills] == ["900000001", "900000002"]


# --------------------------------------------------------------------------- #
# Strictness: numeric money and missing fields are anomalies, never coerced.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("field", ["q", "p", "ap", "sp", "l", "z", "L", "n", "rp"])
@pytest.mark.parametrize("number", [1, 0.004, Decimal("0.004")])
def test_money_field_given_as_a_number_is_a_field_validation_anomaly(
    field: str, number: object
) -> None:
    anomaly = _anomaly(order_trade_update_frame(**{field: number}))
    assert anomaly.kind is StreamAnomalyKind.FIELD_VALIDATION
    assert anomaly.field == f"o.{field}"
    assert anomaly.event_name == "ORDER_TRADE_UPDATE"


@pytest.mark.parametrize("bad", ["", "abc", "NaN", "Infinity", "1_000", " 1", "1e", True, None])
def test_malformed_quantity_text_is_rejected(bad: object) -> None:
    anomaly = _anomaly(order_trade_update_frame(q=bad))
    expected = (
        StreamAnomalyKind.MALFORMED_PAYLOAD if bad is None else StreamAnomalyKind.FIELD_VALIDATION
    )
    assert anomaly.kind is expected
    assert anomaly.field == "o.q"


def test_negative_quantity_is_rejected_but_signed_commission_is_kept() -> None:
    assert _anomaly(order_trade_update_frame(l="-0.004")).kind is (
        StreamAnomalyKind.FIELD_VALIDATION
    )
    event = _event(order_trade_update_frame(n="-0.01000000", rp="-3.5"))
    assert event.commission == Decimal("-0.01000000")
    assert event.realized_profit == Decimal("-3.5")


@pytest.mark.parametrize(
    ("field", "value"),
    [("i", "8000000001"), ("i", True), ("t", "900000001"), ("T", 1.5), ("m", "false")],
)
def test_wrong_wire_type_for_ids_times_and_flags_is_rejected(field: str, value: object) -> None:
    anomaly = _anomaly(order_trade_update_frame(**{field: value}))
    assert anomaly.kind is StreamAnomalyKind.FIELD_VALIDATION
    assert anomaly.field == f"o.{field}"


@pytest.mark.parametrize("field", ["s", "c", "S", "o", "f", "q", "x", "X", "i", "T", "ps"])
def test_missing_required_order_field_is_a_malformed_payload_anomaly(field: str) -> None:
    anomaly = _anomaly(order_trade_update_frame(**{field: OMIT}))
    assert anomaly.kind is StreamAnomalyKind.MALFORMED_PAYLOAD
    assert anomaly.field == f"o.{field}"


@pytest.mark.parametrize("field", ["E", "T", "o"])
def test_missing_required_event_field_is_a_malformed_payload_anomaly(field: str) -> None:
    anomaly = _anomaly(order_trade_update_frame(event_overrides={field: OMIT}))
    assert anomaly.kind is StreamAnomalyKind.MALFORMED_PAYLOAD
    assert anomaly.field == field


@pytest.mark.parametrize("field", ["l", "L", "z", "t"])
def test_trade_without_its_fill_fields_is_a_malformed_payload_anomaly(field: str) -> None:
    anomaly = _anomaly(order_trade_update_frame(**{field: OMIT}))
    assert anomaly.kind is StreamAnomalyKind.MALFORMED_PAYLOAD
    assert anomaly.field == f"o.{field}"


def test_unknown_side_is_a_field_validation_anomaly() -> None:
    anomaly = _anomaly(order_trade_update_frame(S="HOLD"))
    assert anomaly.kind is StreamAnomalyKind.FIELD_VALIDATION
    assert anomaly.field == "o.S"


def test_anomaly_detail_carries_no_raw_value_and_the_hash_is_deterministic() -> None:
    frame = order_trade_update_frame(q=12345.678)
    first = _anomaly(frame)
    second = _anomaly(json.loads(json.dumps(frame)))

    assert "12345" not in first.detail
    assert "synthetic-entry-0001" not in first.detail
    assert len(first.detail) <= 200
    assert first.payload_sha256 == second.payload_sha256
    canonical = json.dumps(frame, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert first.payload_sha256 == hashlib.sha256(canonical.encode("ascii")).hexdigest()
    assert first.observed_at_utc == OBSERVED_AT


def test_parse_order_trade_update_takes_the_payload_dict_directly() -> None:
    outcome = parse_order_trade_update(order_trade_update_frame(), observed_at_utc=OBSERVED_AT)
    assert isinstance(outcome, OrderUpdateEvent)


def test_observed_at_must_be_utc_aware() -> None:
    with pytest.raises(ValueError, match="observed_at_utc"):
        parse_stream_message(order_trade_update_frame(), observed_at_utc=datetime(2026, 10, 16))


# --------------------------------------------------------------------------- #
# Envelope: the two shapes the SDK hands to a callback, duck-typed.
# --------------------------------------------------------------------------- #


class OrderTradeUpdate:  # named like the SDK model class: the event name is the class name
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def to_dict(self) -> dict[str, Any]:
        return dict(self._payload)


class _Wrapper:
    def __init__(self, actual_instance: object) -> None:
        self.actual_instance = actual_instance


def test_normalize_event_name_meets_wire_and_model_names() -> None:
    assert normalize_event_name("ORDER_TRADE_UPDATE") == "ordertradeupdate"
    assert normalize_event_name("OrderTradeUpdate") == "ordertradeupdate"
    assert normalize_event_name("listen-Key_Expired") == "listenkeyexpired"


def test_unwrap_message_handles_dict_wrapped_dict_and_model() -> None:
    frame = order_trade_update_frame()
    assert unwrap_message(frame) == ("ORDER_TRADE_UPDATE", frame)
    assert unwrap_message(_Wrapper(frame)) == ("ORDER_TRADE_UPDATE", frame)

    model_payload = {key: value for key, value in frame.items() if key != "e"}
    name, payload = unwrap_message(_Wrapper(OrderTradeUpdate(model_payload)))
    assert name == "OrderTradeUpdate"
    assert payload == model_payload

    assert unwrap_message(_Wrapper(None)) == (None, None)
    assert unwrap_message(object()) == (None, None)


def test_model_shaped_message_parses_to_the_same_event_as_the_dict() -> None:
    frame = order_trade_update_frame()
    model_payload = {key: value for key, value in frame.items() if key != "e"}
    assert _event(_Wrapper(OrderTradeUpdate(model_payload))) == _event(frame)


def test_synthetic_frame_validates_against_the_installed_sdk_model() -> None:
    """The builder's frame passes the SDK's strict model (no network: models only), and the
    SDK callback shape (`UserDataStreamEventsResponse` around the model) parses to the same
    event as the plain dict."""
    from binance_sdk_derivatives_trading_usds_futures.websocket_streams.models.order_trade_update import (  # noqa: E501
        OrderTradeUpdate as SdkOrderTradeUpdate,
    )
    from binance_sdk_derivatives_trading_usds_futures.websocket_streams.models.user_data_stream_events_response import (  # noqa: E501
        UserDataStreamEventsResponse,
    )

    frame = order_trade_update_frame()
    model = SdkOrderTradeUpdate.from_dict(frame)
    assert model is not None
    assert model.to_dict()["o"] == frame["o"]
    assert _event(UserDataStreamEventsResponse(model)) == _event(frame)


def test_unrecognized_envelope_and_unknown_event_are_anomalies() -> None:
    assert _anomaly(object()).kind is StreamAnomalyKind.UNRECOGNIZED_ENVELOPE
    assert _anomaly({"E": 1}).kind is StreamAnomalyKind.UNRECOGNIZED_ENVELOPE
    unknown = _anomaly({"e": "SOMETHING_NEW", "E": 1})
    assert unknown.kind is StreamAnomalyKind.UNKNOWN_EVENT_TYPE
    assert unknown.event_name == "SOMETHING_NEW"


# --------------------------------------------------------------------------- #
# FillEvent extension (G3-009): additive, defaulted, validated when given.
# --------------------------------------------------------------------------- #


def _fill_kwargs() -> dict[str, Any]:
    return {
        "order_id": "ord_001",
        "exchange_trade_id": "trade_001",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "position_side": "BOTH",
        "fill_price": Decimal("100.00"),
        "fill_quantity": Decimal("0.100"),
        "fill_time_utc": datetime(2026, 9, 19, 10, 30, tzinfo=UTC),
    }


def test_fill_event_with_the_previous_eight_arguments_still_validates() -> None:
    fill = FillEvent(**_fill_kwargs())
    assert fill.commission is None
    assert fill.commission_asset is None
    assert fill.realized_pnl is None
    assert fill.is_maker is None
    view = fold_fills(fill_events=[fill], current_position_view=_flat_view())
    folded = view.fills[0]
    for key in ("commission", "commission_asset", "realized_pnl", "is_maker"):
        assert key in folded
        assert folded[key] is None


def test_dict_style_fill_without_the_new_keys_still_folds() -> None:
    raw = dict(_fill_kwargs())
    view = fold_fills(fill_events=[raw], current_position_view=_flat_view())
    assert view.fills[0]["commission"] is None


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"commission": "0.1"}, TypeError),
        ({"commission": 0.1}, TypeError),
        ({"realized_pnl": 1}, TypeError),
        ({"commission_asset": ""}, ValueError),
        ({"commission_asset": 5}, ValueError),
        ({"is_maker": 1}, TypeError),
        ({"is_maker": "true"}, TypeError),
    ],
)
def test_fill_event_rejects_invalid_optional_fields(
    overrides: dict[str, Any], error: type[Exception]
) -> None:
    with pytest.raises(error):
        FillEvent(**{**_fill_kwargs(), **overrides})


def test_fill_event_accepts_valid_optional_fields() -> None:
    fill = FillEvent(
        **_fill_kwargs(),
        commission=Decimal("-0.01"),
        commission_asset="BNB",
        realized_pnl=Decimal("2.5"),
        is_maker=True,
    )
    assert fill.commission == Decimal("-0.01")
    assert fill.is_maker is True
