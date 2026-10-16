"""Strict parsers for the remaining user-data events (Phase 18, plan 18-03 Task 3).

ALGO_UPDATE, ACCOUNT_UPDATE, listenKeyExpired, ACCOUNT_CONFIG_UPDATE, the
ignored and unhandled event kinds and the ORDER_TRADE_UPDATE anomaly paths
(D-05, D-07, D-08, research P22 and P23), with the shapes reviewed at the
design gate (decisions/18-DEC-D01-event-types.md, option amend).

Every frame is SYNTHETIC (FRAME_LABEL SYNTHETIC_FROM_SDK_MODEL), built from the
installed SDK models; none is captured Binance data, and passing these tests is
not evidence of live Binance frame behaviour. No network.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_userdata_events import (
    ACCOUNT_BALANCE_WIRE_FIELDS,
    ACCOUNT_POSITION_WIRE_FIELDS,
    ACCOUNT_UPDATE_WIRE_FIELDS,
    ALGO_UPDATE_WIRE_FIELDS,
    DETAIL_MAX_CHARS,
    FORCED_CLOSE_CLIENT_ID_PREFIXES,
    ORDER_EXECUTION_TYPE_VOCABULARY,
    ORDER_STATUS_VOCABULARY,
    ORDER_UPDATE_WIRE_FIELDS,
    AccountConfigUpdateEvent,
    AccountUpdateEvent,
    AlgoUpdateEvent,
    BalanceDelta,
    IgnoredEvent,
    ListenKeyExpiredEvent,
    OrderUpdateEvent,
    PositionDelta,
    StreamAnomaly,
    StreamAnomalyKind,
    parse_account_config_update,
    parse_account_update,
    parse_algo_update,
    parse_listen_key_expired,
    parse_order_trade_update,
    parse_stream_message,
)
from src.domain.algo_status import ALGO_STATUS_VOCABULARY, is_known_algo_status

from tests.support.ast_guards import (
    float_constructor_calls,
    forbidden_imports,
    module_imports,
    wall_clock_calls,
)
from tests.support.userdata_frames import (
    FRAME_LABEL,
    OMIT,
    SYNTHETIC_EVENT_TIME_MS,
    SYNTHETIC_LISTEN_KEY,
    SYNTHETIC_TRANSACTION_TIME_MS,
    account_config_update_frame,
    account_update_frame,
    algo_update_frame,
    balance_row,
    conditional_order_trigger_reject_frame,
    grid_update_frame,
    listen_key_expired_frame,
    margin_call_frame,
    order_trade_update_frame,
    position_row,
    strategy_update_frame,
    trade_lite_frame,
)

OBSERVED_AT = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_REPO_ROOT = Path(__file__).resolve().parents[1]
EVENTS_MODULE = _REPO_ROOT / "src" / "adapters" / "binance_userdata_events.py"
ALGO_STATUS_MODULE = _REPO_ROOT / "src" / "domain" / "algo_status.py"
FORBIDDEN_PREFIXES = (
    "binance*",
    "binance_common",
    "requests",
    "aiohttp",
    "sqlalchemy",
    "pydantic*",
    "polars",
)
_SDK_MODELS = "binance_sdk_derivatives_trading_usds_futures.websocket_streams.models"


def _parse(frame: Any) -> Any:
    return parse_stream_message(frame, observed_at_utc=OBSERVED_AT)


def _anomaly(frame: Any) -> StreamAnomaly:
    outcome = _parse(frame)
    assert isinstance(outcome, StreamAnomaly), outcome
    return outcome


def _algo(frame: Any) -> AlgoUpdateEvent:
    outcome = _parse(frame)
    assert isinstance(outcome, AlgoUpdateEvent), outcome
    return outcome


def _account(frame: Any) -> AccountUpdateEvent:
    outcome = _parse(frame)
    assert isinstance(outcome, AccountUpdateEvent), outcome
    return outcome


def _order(frame: Any) -> OrderUpdateEvent:
    outcome = _parse(frame)
    assert isinstance(outcome, OrderUpdateEvent), outcome
    return outcome


def _ms(ms: int) -> datetime:
    return _EPOCH + timedelta(milliseconds=ms)


# --------------------------------------------------------------------------- #
# Algo status vocabulary (src/domain/algo_status.py).
# --------------------------------------------------------------------------- #


def test_algo_status_vocabulary_is_the_seven_documented_values() -> None:
    assert ALGO_STATUS_VOCABULARY == frozenset(
        {"NEW", "TRIGGERING", "TRIGGERED", "FINISHED", "CANCELED", "REJECTED", "EXPIRED"}
    )
    assert isinstance(ALGO_STATUS_VOCABULARY, frozenset)


@pytest.mark.parametrize("value", sorted(ALGO_STATUS_VOCABULARY))
def test_is_known_algo_status_accepts_each_documented_value(value: str) -> None:
    assert is_known_algo_status(value) is True


@pytest.mark.parametrize(
    "value", [None, "", "new", "Canceled", "CANCELLED", " NEW", "NEW ", "UNKNOWN", 1, b"NEW", True]
)
def test_is_known_algo_status_rejects_everything_else(value: object) -> None:
    assert is_known_algo_status(value) is False


# --------------------------------------------------------------------------- #
# ALGO_UPDATE.
# --------------------------------------------------------------------------- #


def test_algo_update_frame_parses_to_a_typed_event() -> None:
    event = _algo(algo_update_frame())

    assert event.event_time_utc == _ms(SYNTHETIC_EVENT_TIME_MS)
    assert event.transaction_time_utc == _ms(SYNTHETIC_TRANSACTION_TIME_MS)
    assert event.client_algo_id == "synthetic-sl-0001"
    assert event.algo_id == "7000000001"  # the int `aid` as text
    assert event.algo_type == "CONDITIONAL"
    assert event.order_type == "STOP_MARKET"
    assert event.symbol == "BTCUSDT"
    assert event.side == "SELL"
    assert event.position_side == "BOTH"
    assert event.time_in_force == "GTC"
    assert event.quantity == Decimal("0.010")
    assert event.algo_status == "NEW"  # the raw string; classification is plan 18-06
    assert event.actual_order_id is None  # `ai` is "" before the trigger
    assert event.average_price is None
    assert event.executed_quantity is None
    assert event.actual_order_type is None
    assert event.trigger_price == Decimal("58000.00")
    assert event.price == Decimal("0")
    assert event.working_type == "MARK_PRICE"
    assert event.reduce_only is True
    assert event.close_position is False
    assert event.price_protect is False
    # `tt` 0 converts exactly to the epoch; nothing is inferred from it.
    assert event.trigger_time_utc == _EPOCH
    assert event.reject_reason is None
    assert event.is_activated is False
    # Added by the design gate (18-DEC-D01 Q6).
    assert event.stp_mode == "EXPIRE_MAKER"
    assert event.price_match == "NONE"
    assert event.good_till_date_ms == 0
    for value in dataclasses.astuple(event):
        assert not isinstance(value, float)


def test_triggered_algo_update_carries_the_matching_engine_fields() -> None:
    frame = algo_update_frame(
        X="TRIGGERED",
        ai="8000000099",
        ap="57990.10",
        aq="0.010",
        act="MARKET",
        tt=SYNTHETIC_TRANSACTION_TIME_MS,
    )
    event = _algo(frame)
    assert event.algo_status == "TRIGGERED"
    assert event.actual_order_id == "8000000099"
    assert event.average_price == Decimal("57990.10")
    assert event.executed_quantity == Decimal("0.010")
    assert event.actual_order_type == "MARKET"
    assert event.trigger_time_utc == _ms(SYNTHETIC_TRANSACTION_TIME_MS)


@pytest.mark.parametrize("status", sorted(ALGO_STATUS_VOCABULARY))
def test_every_documented_algo_status_parses(status: str) -> None:
    assert _algo(algo_update_frame(X=status)).algo_status == status


@pytest.mark.parametrize("status", ["", "new", "PENDING", "CANCELLED", "TRIGGERED "])
def test_algo_status_outside_the_vocabulary_is_an_unknown_algo_status_anomaly(
    status: str,
) -> None:
    anomaly = _anomaly(algo_update_frame(X=status))
    assert anomaly.kind is StreamAnomalyKind.UNKNOWN_ALGO_STATUS
    assert anomaly.field == "o.X"
    assert anomaly.event_name == "ALGO_UPDATE"


def test_rejected_algo_update_keeps_rm_as_a_diagnostic_only() -> None:
    event = _algo(algo_update_frame(X="REJECTED", rm="Reduce Only reject"))
    assert event.algo_status == "REJECTED"
    assert event.reject_reason == "Reduce Only reject"


def test_reject_reason_is_verbatim_and_bounded_to_200_characters() -> None:
    long_reason = "Margin is insufficient; " * 20
    event = _algo(algo_update_frame(X="REJECTED", rm=long_reason))
    assert event.reject_reason == long_reason[:200]
    assert len(event.reject_reason or "") == 200


def test_trailing_stop_algo_update_arriving_twice_parses_both_times() -> None:
    """Change log 2026-08-21 (WebFetch summary, not verified live): a trailing-stop
    ALGO_UPDATE may arrive twice, `ia` false then true. Both parse; neither is an
    anomaly; de-duplication belongs to the router (plan 18-15)."""
    base = {"o": "TRAILING_STOP_MARKET", "X": "NEW", "R": True}
    first = _algo(algo_update_frame(**base, ia=False))
    second = _algo(algo_update_frame(**base, ia=True))
    assert first.is_activated is False
    assert second.is_activated is True
    assert first.algo_id == second.algo_id


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("aid", "7000000001"),
        ("aid", True),
        ("aid", -1),
        ("q", 0.01),
        ("q", "-0.010"),
        ("tp", 58000),
        ("p", ""),
        ("ap", 57990.1),
        ("aq", "abc"),
        ("ai", 8000000099),
        ("act", ""),
        ("cp", "false"),
        ("pP", 0),
        ("R", "true"),
        ("ia", 1),
        ("tt", "0"),
        ("tt", -5),
        ("gtd", "0"),
        ("gtd", True),
        ("V", ""),
        ("pm", 0),
        ("wt", ""),
        ("rm", 5),
        ("rm", ""),
        ("S", "HOLD"),
        ("X", 1),
        ("caid", ""),
    ],
)
def test_algo_field_of_the_wrong_wire_type_is_a_field_validation_anomaly(
    field: str, value: object
) -> None:
    anomaly = _anomaly(algo_update_frame(**{field: value}))
    assert anomaly.kind is StreamAnomalyKind.FIELD_VALIDATION
    assert anomaly.field == f"o.{field}"


@pytest.mark.parametrize("field", ["caid", "aid", "at", "o", "s", "S", "ps", "f", "q", "X", "tp"])
def test_missing_required_algo_field_is_a_malformed_payload_anomaly(field: str) -> None:
    anomaly = _anomaly(algo_update_frame(**{field: OMIT}))
    assert anomaly.kind is StreamAnomalyKind.MALFORMED_PAYLOAD
    assert anomaly.field == f"o.{field}"


@pytest.mark.parametrize("field", ["E", "T", "o"])
def test_missing_required_algo_event_field_is_a_malformed_payload_anomaly(field: str) -> None:
    anomaly = _anomaly(algo_update_frame(event_overrides={field: OMIT}))
    assert anomaly.kind is StreamAnomalyKind.MALFORMED_PAYLOAD
    assert anomaly.field == field


@pytest.mark.parametrize(
    "field",
    ["ai", "ap", "aq", "act", "p", "V", "wt", "pm", "cp", "pP", "R", "tt", "gtd", "rm", "ia"],
)
def test_optional_algo_fields_may_be_absent(field: str) -> None:
    assert isinstance(_parse(algo_update_frame(**{field: OMIT})), AlgoUpdateEvent)


def test_algo_update_event_rejects_an_unknown_status_at_construction() -> None:
    event = _algo(algo_update_frame())
    with pytest.raises(ValueError, match="algo_status"):
        dataclasses.replace(event, algo_status="PENDING")
    with pytest.raises(ValueError):
        dataclasses.replace(event, reject_reason="x" * 201)
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.algo_status = "CANCELED"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# ACCOUNT_UPDATE (D-08: deltas only).
# --------------------------------------------------------------------------- #


def test_account_update_parses_to_balance_and_position_deltas() -> None:
    event = _account(account_update_frame())

    assert event.event_time_utc == _ms(SYNTHETIC_EVENT_TIME_MS)
    assert event.transaction_time_utc == _ms(SYNTHETIC_TRANSACTION_TIME_MS)
    assert event.reason == "ORDER"
    assert event.funding_symbol is None
    assert event.balances == (
        BalanceDelta(
            asset="USDT",
            wallet_balance=Decimal("1000.12345678"),
            cross_wallet_balance=Decimal("1000.12345678"),
            balance_change=Decimal("0"),
        ),
    )
    (position,) = event.positions
    assert position == PositionDelta(
        symbol="BTCUSDT",
        position_amount=Decimal("-0.010"),  # signed: a short position
        entry_price=Decimal("60000.00"),
        breakeven_price=Decimal("60024.00"),
        accumulated_realized=Decimal("0"),
        unrealized_pnl=Decimal("1.20000000"),
        margin_type="cross",
        isolated_wallet=Decimal("0"),
        position_side="BOTH",
    )
    assert isinstance(event.balances, tuple)
    assert isinstance(event.positions, tuple)


def test_account_update_carries_only_deltas_no_derived_state() -> None:
    names = {field.name for field in dataclasses.fields(AccountUpdateEvent)}
    assert names == {
        "event_time_utc",
        "transaction_time_utc",
        "reason",
        "balances",
        "positions",
        "funding_symbol",
    }
    for forbidden in ("equity", "margin", "available", "position_view", "total"):
        assert not any(forbidden in name for name in names)


def test_account_update_with_several_rows_keeps_their_order() -> None:
    frame = account_update_frame(
        B=[balance_row(), balance_row(a="BNB", wb="0.5", cw="0.5", bc="-0.1")],
        P=[position_row(ps="LONG", pa="0.020"), position_row(ps="SHORT", pa="-0.010")],
    )
    event = _account(frame)
    assert [b.asset for b in event.balances] == ["USDT", "BNB"]
    assert event.balances[1].balance_change == Decimal("-0.1")
    assert [p.position_side for p in event.positions] == ["LONG", "SHORT"]


def test_unknown_account_update_reason_is_carried_verbatim() -> None:
    event = _account(account_update_frame(m="SOME_FUTURE_REASON"))
    assert event.reason == "SOME_FUTURE_REASON"


def test_funding_symbol_is_accepted_for_funding_fee_only() -> None:
    funding = _account(account_update_frame(m="FUNDING_FEE", S="BTCUSDT", P=OMIT))
    assert funding.funding_symbol == "BTCUSDT"
    assert funding.positions == ()

    anomaly = _anomaly(account_update_frame(m="ORDER", S="BTCUSDT"))
    assert anomaly.kind is StreamAnomalyKind.FIELD_VALIDATION
    assert anomaly.field == "a.S"


def test_funding_fee_without_s_parses() -> None:
    assert _account(account_update_frame(m="FUNDING_FEE")).funding_symbol is None


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"B": [balance_row(wb=1000)]}, "a.B[0].wb"),
        ({"B": [balance_row(cw="NaN")]}, "a.B[0].cw"),
        ({"B": [balance_row(a="")]}, "a.B[0].a"),
        ({"P": [position_row(pa=-0.01)]}, "a.P[0].pa"),
        ({"P": [position_row(ep="-1")]}, "a.P[0].ep"),
        ({"P": [position_row(), position_row(up=1.2)]}, "a.P[1].up"),
        ({"P": [position_row(iw="")]}, "a.P[0].iw"),
        ({"B": {"a": "USDT"}}, "a.B"),
        ({"B": ["USDT"]}, "a.B[0]"),
        ({"P": "none"}, "a.P"),
        ({"m": ""}, "a.m"),
        ({"m": 1}, "a.m"),
        ({"S": 5, "m": "FUNDING_FEE"}, "a.S"),
    ],
)
def test_account_update_field_of_the_wrong_wire_type_is_a_field_validation_anomaly(
    overrides: dict[str, Any], field: str
) -> None:
    anomaly = _anomaly(account_update_frame(**overrides))
    assert anomaly.kind is StreamAnomalyKind.FIELD_VALIDATION
    assert anomaly.field == field


@pytest.mark.parametrize(
    ("overrides", "event_overrides", "field"),
    [
        ({"m": OMIT}, {}, "a.m"),
        ({"B": [balance_row(wb=OMIT)]}, {}, "a.B[0].wb"),
        ({"P": [position_row(pa=OMIT)]}, {}, "a.P[0].pa"),
        ({"P": [position_row(s=OMIT)]}, {}, "a.P[0].s"),
        ({}, {"a": OMIT}, "a"),
        ({}, {"E": OMIT}, "E"),
        ({}, {"T": OMIT}, "T"),
    ],
)
def test_missing_required_account_field_is_a_malformed_payload_anomaly(
    overrides: dict[str, Any], event_overrides: dict[str, Any], field: str
) -> None:
    anomaly = _anomaly(account_update_frame(event_overrides=event_overrides, **overrides))
    assert anomaly.kind is StreamAnomalyKind.MALFORMED_PAYLOAD
    assert anomaly.field == field


def test_account_update_without_b_or_p_has_empty_delta_tuples() -> None:
    event = _account(account_update_frame(B=OMIT, P=OMIT))
    assert event.balances == ()
    assert event.positions == ()


# --------------------------------------------------------------------------- #
# listenKeyExpired: the key is a credential and is never stored.
# --------------------------------------------------------------------------- #


def test_listen_key_expired_carries_only_the_event_time() -> None:
    outcome = _parse(listen_key_expired_frame())
    assert outcome == ListenKeyExpiredEvent(event_time_utc=_ms(SYNTHETIC_EVENT_TIME_MS))
    assert [field.name for field in dataclasses.fields(ListenKeyExpiredEvent)] == ["event_time_utc"]


def _listen_key_outcomes() -> list[object]:
    from binance_sdk_derivatives_trading_usds_futures.websocket_streams.models.listen_key_expired import (  # noqa: E501
        ListenKeyExpired as SdkListenKeyExpired,
    )
    from binance_sdk_derivatives_trading_usds_futures.websocket_streams.models.user_data_stream_events_response import (  # noqa: E501
        UserDataStreamEventsResponse,
    )

    frame = listen_key_expired_frame()
    model = SdkListenKeyExpired.from_dict(frame)
    return [
        _parse(frame),
        _parse(UserDataStreamEventsResponse(model)),
        parse_listen_key_expired(frame, observed_at_utc=OBSERVED_AT),
        _parse(listen_key_expired_frame(E=OMIT)),
        _parse(listen_key_expired_frame(E="1760000000123")),
        _parse(listen_key_expired_frame(e="listenKeyExpiredX")),
        _parse(listen_key_expired_frame(e=7)),
        _parse({"listenKey": SYNTHETIC_LISTEN_KEY}),
    ]


def test_listen_key_never_reaches_an_event_an_anomaly_or_a_repr() -> None:
    outcomes = _listen_key_outcomes()
    assert isinstance(outcomes[0], ListenKeyExpiredEvent)
    assert isinstance(outcomes[1], ListenKeyExpiredEvent)
    assert outcomes[0] == outcomes[1] == outcomes[2]
    for outcome in outcomes:
        assert SYNTHETIC_LISTEN_KEY not in repr(outcome)
        assert SYNTHETIC_LISTEN_KEY not in str(outcome)
        for value in vars(outcome).values() if hasattr(outcome, "__dict__") else ():
            assert SYNTHETIC_LISTEN_KEY not in str(value)
        if dataclasses.is_dataclass(outcome):
            for value in dataclasses.astuple(outcome):  # type: ignore[arg-type]
                assert SYNTHETIC_LISTEN_KEY not in str(value)


def test_listen_key_frame_anomalies_have_the_expected_kinds() -> None:
    outcomes = _listen_key_outcomes()
    kinds = [o.kind for o in outcomes[3:] if isinstance(o, StreamAnomaly)]
    assert kinds == [
        StreamAnomalyKind.MALFORMED_PAYLOAD,
        StreamAnomalyKind.FIELD_VALIDATION,
        StreamAnomalyKind.UNKNOWN_EVENT_TYPE,
        StreamAnomalyKind.UNRECOGNIZED_ENVELOPE,
        StreamAnomalyKind.UNRECOGNIZED_ENVELOPE,
    ]


# --------------------------------------------------------------------------- #
# ACCOUNT_CONFIG_UPDATE.
# --------------------------------------------------------------------------- #


def test_account_config_update_leverage_change_parses() -> None:
    outcome = _parse(account_config_update_frame())
    assert outcome == AccountConfigUpdateEvent(
        event_time_utc=_ms(SYNTHETIC_EVENT_TIME_MS),
        transaction_time_utc=_ms(SYNTHETIC_TRANSACTION_TIME_MS),
        symbol="BTCUSDT",
        leverage=5,
        multi_assets=None,
    )
    assert isinstance(outcome, AccountConfigUpdateEvent)
    assert type(outcome.leverage) is int


def test_account_config_update_multi_assets_change_parses() -> None:
    outcome = _parse(account_config_update_frame(ac=OMIT, ai={"j": True}))
    assert isinstance(outcome, AccountConfigUpdateEvent)
    assert outcome.multi_assets is True
    assert outcome.symbol is None
    assert outcome.leverage is None


@pytest.mark.parametrize(
    ("overrides", "kind", "field"),
    [
        ({"ac": {"s": "BTCUSDT", "l": "5"}}, StreamAnomalyKind.FIELD_VALIDATION, "ac.l"),
        ({"ac": {"s": "BTCUSDT", "l": 5.0}}, StreamAnomalyKind.FIELD_VALIDATION, "ac.l"),
        ({"ac": {"s": "BTCUSDT", "l": True}}, StreamAnomalyKind.FIELD_VALIDATION, "ac.l"),
        ({"ac": {"s": "BTCUSDT", "l": 0}}, StreamAnomalyKind.FIELD_VALIDATION, "ac.l"),
        ({"ac": {"s": "", "l": 5}}, StreamAnomalyKind.FIELD_VALIDATION, "ac.s"),
        ({"ac": {"l": 5}}, StreamAnomalyKind.MALFORMED_PAYLOAD, "ac.s"),
        ({"ac": {"s": "BTCUSDT"}}, StreamAnomalyKind.MALFORMED_PAYLOAD, "ac.l"),
        ({"ac": OMIT, "ai": {"j": "true"}}, StreamAnomalyKind.FIELD_VALIDATION, "ai.j"),
        ({"ac": OMIT, "ai": {}}, StreamAnomalyKind.MALFORMED_PAYLOAD, "ai.j"),
        ({"ac": OMIT}, StreamAnomalyKind.MALFORMED_PAYLOAD, "ac"),
        ({"ac": [5]}, StreamAnomalyKind.FIELD_VALIDATION, "ac"),
        ({"E": OMIT}, StreamAnomalyKind.MALFORMED_PAYLOAD, "E"),
        ({"T": OMIT}, StreamAnomalyKind.MALFORMED_PAYLOAD, "T"),
    ],
)
def test_account_config_update_anomalies(
    overrides: dict[str, Any], kind: StreamAnomalyKind, field: str
) -> None:
    anomaly = _anomaly(account_config_update_frame(**overrides))
    assert anomaly.kind is kind
    assert anomaly.field == field


# --------------------------------------------------------------------------- #
# Ignored, unhandled, deprecated and unknown event kinds.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("builder", "name"),
    [
        (trade_lite_frame, "TRADE_LITE"),
        (strategy_update_frame, "STRATEGY_UPDATE"),
        (grid_update_frame, "GRID_UPDATE"),
    ],
)
def test_events_the_project_does_not_use_are_ignored_events(
    builder: Callable[..., dict[str, Any]], name: str
) -> None:
    outcome = _parse(builder())
    assert isinstance(outcome, IgnoredEvent)
    assert outcome.event_name == name
    assert outcome.reason != ""


def test_margin_call_is_an_unhandled_event_anomaly() -> None:
    anomaly = _anomaly(margin_call_frame())
    assert anomaly.kind is StreamAnomalyKind.UNHANDLED_EVENT
    assert anomaly.event_name == "MARGIN_CALL"


def test_conditional_order_trigger_reject_is_a_deprecated_event_anomaly() -> None:
    anomaly = _anomaly(conditional_order_trigger_reject_frame())
    assert anomaly.kind is StreamAnomalyKind.DEPRECATED_EVENT
    assert anomaly.event_name == "CONDITIONAL_ORDER_TRIGGER_REJECT"
    assert "Synthetic reject reason" not in anomaly.detail


def test_unknown_event_name_is_an_unknown_event_type_anomaly() -> None:
    anomaly = _anomaly({"e": "BRAND_NEW_EVENT", "E": SYNTHETIC_EVENT_TIME_MS})
    assert anomaly.kind is StreamAnomalyKind.UNKNOWN_EVENT_TYPE
    assert anomaly.event_name == "BRAND_NEW_EVENT"


# --------------------------------------------------------------------------- #
# ORDER_TRADE_UPDATE anomaly paths (research P22).
# --------------------------------------------------------------------------- #


def test_order_vocabularies_are_the_documented_lists() -> None:
    assert ORDER_EXECUTION_TYPE_VOCABULARY == frozenset(
        {"NEW", "CANCELED", "CALCULATED", "EXPIRED", "TRADE", "AMENDMENT"}
    )
    assert ORDER_STATUS_VOCABULARY == frozenset(
        {"NEW", "PARTIALLY_FILLED", "FILLED", "CANCELED", "EXPIRED", "EXPIRED_IN_MATCH"}
    )
    assert FORCED_CLOSE_CLIENT_ID_PREFIXES == (
        "autoclose-",
        "adl_autoclose",
        "settlement_autoclose-",
    )


def test_amendment_is_an_amendment_event_anomaly() -> None:
    anomaly = _anomaly(order_trade_update_frame(x="AMENDMENT", X="NEW", M="1"))
    assert anomaly.kind is StreamAnomalyKind.AMENDMENT_EVENT
    assert anomaly.field == "o.x"


def test_calculated_is_a_liquidation_event_anomaly() -> None:
    anomaly = _anomaly(order_trade_update_frame(x="CALCULATED", X="FILLED"))
    assert anomaly.kind is StreamAnomalyKind.LIQUIDATION_EVENT
    assert anomaly.field == "o.x"


def test_liquidation_with_a_forced_close_id_reports_the_liquidation() -> None:
    anomaly = _anomaly(
        order_trade_update_frame(x="CALCULATED", X="FILLED", c="autoclose-1760000000")
    )
    assert anomaly.kind is StreamAnomalyKind.LIQUIDATION_EVENT


@pytest.mark.parametrize(
    "client_order_id",
    ["autoclose-1760000000123", "adl_autoclose", "adl_autoclose-77", "settlement_autoclose-BTC"],
)
@pytest.mark.parametrize(("execution_type", "status"), [("NEW", "NEW"), ("TRADE", "FILLED")])
def test_forced_close_client_order_id_is_a_forced_close_anomaly(
    client_order_id: str, execution_type: str, status: str
) -> None:
    anomaly = _anomaly(order_trade_update_frame(c=client_order_id, x=execution_type, X=status))
    assert anomaly.kind is StreamAnomalyKind.FORCED_CLOSE_ORDER
    assert anomaly.field == "o.c"
    assert client_order_id not in anomaly.detail


@pytest.mark.parametrize("client_order_id", ["myautoclose-1", "x-autoclose-", "AUTOCLOSE-1"])
def test_client_ids_that_only_contain_the_word_are_not_forced_close(client_order_id: str) -> None:
    assert _order(order_trade_update_frame(c=client_order_id)).client_order_id == client_order_id


def test_expired_in_match_parses_as_a_terminal_unfilled_order_update() -> None:
    event = _order(
        order_trade_update_frame(x="EXPIRED", X="EXPIRED_IN_MATCH", l="0", z="0", L="0", er="1")
    )
    assert event.order_status == "EXPIRED_IN_MATCH"
    assert event.trade_id is None


@pytest.mark.parametrize("execution_type", ["", "REPLACED", "trade", "LIQUIDATION"])
def test_unseen_execution_type_is_an_unknown_execution_type_anomaly(execution_type: str) -> None:
    anomaly = _anomaly(order_trade_update_frame(x=execution_type))
    assert anomaly.kind is StreamAnomalyKind.UNKNOWN_EXECUTION_TYPE
    assert anomaly.field == "o.x"


@pytest.mark.parametrize("status", ["", "PENDING_NEW", "filled", "REJECTED"])
def test_unseen_order_status_is_an_unknown_order_status_anomaly(status: str) -> None:
    anomaly = _anomaly(order_trade_update_frame(X=status))
    assert anomaly.kind is StreamAnomalyKind.UNKNOWN_ORDER_STATUS
    assert anomaly.field == "o.X"


@pytest.mark.parametrize("execution_type", sorted({"NEW", "CANCELED", "EXPIRED", "TRADE"}))
@pytest.mark.parametrize("status", sorted(ORDER_STATUS_VOCABULARY))
def test_every_documented_event_combination_parses(execution_type: str, status: str) -> None:
    event = _order(order_trade_update_frame(x=execution_type, X=status))
    assert event.execution_type == execution_type
    assert event.order_status == status


def test_order_update_event_rejects_vocabulary_outside_the_parsed_set() -> None:
    event = _order(order_trade_update_frame())
    for overrides in (
        {"execution_type": "AMENDMENT", "trade_id": None},
        {"execution_type": "CALCULATED", "trade_id": None},
        {"execution_type": "REPLACED", "trade_id": None},
        {"order_status": "PENDING"},
    ):
        with pytest.raises(ValueError):
            dataclasses.replace(event, **overrides)


# --------------------------------------------------------------------------- #
# Anomaly determinism and detail hygiene.
# --------------------------------------------------------------------------- #

_DISTINCT_VALUE = "ZZDISTINCT9917"


@pytest.mark.parametrize(
    "frame",
    [
        algo_update_frame(X=_DISTINCT_VALUE),
        algo_update_frame(q=_DISTINCT_VALUE),
        algo_update_frame(caid=_DISTINCT_VALUE, S=_DISTINCT_VALUE),
        account_update_frame(B=[balance_row(wb=_DISTINCT_VALUE)]),
        account_update_frame(m=_DISTINCT_VALUE, S=_DISTINCT_VALUE),
        account_config_update_frame(ac={"s": _DISTINCT_VALUE, "l": _DISTINCT_VALUE}),
        order_trade_update_frame(x=_DISTINCT_VALUE),
        order_trade_update_frame(X=_DISTINCT_VALUE),
        order_trade_update_frame(c="autoclose-" + _DISTINCT_VALUE),
        order_trade_update_frame(x="AMENDMENT", M=_DISTINCT_VALUE),
        margin_call_frame(cw=_DISTINCT_VALUE),
        conditional_order_trigger_reject_frame(T=_DISTINCT_VALUE),
    ],
)
def test_anomaly_detail_never_carries_a_raw_value_and_the_hash_is_deterministic(
    frame: dict[str, Any],
) -> None:
    first = _anomaly(frame)
    second = _anomaly(json.loads(json.dumps(frame)))
    assert _DISTINCT_VALUE not in first.detail
    assert _DISTINCT_VALUE not in (first.field or "")
    assert len(first.detail) <= DETAIL_MAX_CHARS
    assert first == second
    assert first.payload_sha256 == second.payload_sha256


def test_different_payloads_give_different_hashes() -> None:
    a = _anomaly(algo_update_frame(X="PENDING"))
    b = _anomaly(algo_update_frame(X="PENDING", caid="synthetic-sl-0002"))
    assert a.payload_sha256 != b.payload_sha256


# --------------------------------------------------------------------------- #
# Builders: every synthetic frame is accepted by its parser and by the SDK model.
# --------------------------------------------------------------------------- #


def test_frames_are_labelled_synthetic_from_the_sdk_model() -> None:
    assert FRAME_LABEL == "SYNTHETIC_FROM_SDK_MODEL"


_BUILDER_OUTCOMES: list[tuple[Callable[..., dict[str, Any]], str, type]] = [
    (order_trade_update_frame, "order_trade_update.OrderTradeUpdate", OrderUpdateEvent),
    (algo_update_frame, "algo_update.AlgoUpdate", AlgoUpdateEvent),
    (account_update_frame, "account_update.AccountUpdate", AccountUpdateEvent),
    (listen_key_expired_frame, "listen_key_expired.ListenKeyExpired", ListenKeyExpiredEvent),
    (
        account_config_update_frame,
        "account_config_update.AccountConfigUpdate",
        AccountConfigUpdateEvent,
    ),
    (trade_lite_frame, "trade_lite.TradeLite", IgnoredEvent),
    (strategy_update_frame, "strategy_update.StrategyUpdate", IgnoredEvent),
    (grid_update_frame, "grid_update.GridUpdate", IgnoredEvent),
    (margin_call_frame, "margin_call.MarginCall", StreamAnomaly),
    (
        conditional_order_trigger_reject_frame,
        "conditional_order_trigger_reject.ConditionalOrderTriggerReject",
        StreamAnomaly,
    ),
]


@pytest.mark.parametrize(("builder", "model_path", "expected"), _BUILDER_OUTCOMES)
def test_every_builder_is_accepted_by_its_parser_and_the_sdk_model(
    builder: Callable[..., dict[str, Any]], model_path: str, expected: type
) -> None:
    import importlib

    from binance_sdk_derivatives_trading_usds_futures.websocket_streams.models.user_data_stream_events_response import (  # noqa: E501
        UserDataStreamEventsResponse,
    )

    module_name, class_name = model_path.rsplit(".", 1)
    model_class = getattr(importlib.import_module(f"{_SDK_MODELS}.{module_name}"), class_name)
    frame = builder()
    model = model_class.from_dict(frame)
    assert model is not None
    # Every key survives the strict SDK model (the frame uses the SDK's aliases and types).
    assert model.to_dict() == frame

    from_dict = _parse(frame)
    from_model = _parse(UserDataStreamEventsResponse(model))
    assert isinstance(from_dict, expected)
    assert isinstance(from_model, expected)
    if not isinstance(from_dict, StreamAnomaly | IgnoredEvent):
        assert from_dict == from_model


def test_direct_parsers_accept_the_payload_dict() -> None:
    assert isinstance(
        parse_algo_update(algo_update_frame(), observed_at_utc=OBSERVED_AT), AlgoUpdateEvent
    )
    assert isinstance(
        parse_account_update(account_update_frame(), observed_at_utc=OBSERVED_AT),
        AccountUpdateEvent,
    )
    assert isinstance(
        parse_account_config_update(account_config_update_frame(), observed_at_utc=OBSERVED_AT),
        AccountConfigUpdateEvent,
    )
    assert isinstance(
        parse_order_trade_update(order_trade_update_frame(), observed_at_utc=OBSERVED_AT),
        OrderUpdateEvent,
    )


# --------------------------------------------------------------------------- #
# Wire-field frozensets: exactly the keys the parsers read, all SDK aliases.
# --------------------------------------------------------------------------- #


class _RecordingDict(dict[str, Any]):
    """A dict that records every key a parser reads."""

    def __init__(self, data: dict[str, Any], seen: set[str]) -> None:
        super().__init__(data)
        self._seen = seen

    def get(self, key: str, default: Any = None) -> Any:
        self._seen.add(key)
        return super().get(key, default)

    def __getitem__(self, key: str) -> Any:
        self._seen.add(key)
        return super().__getitem__(key)


def test_order_update_wire_fields_are_the_keys_the_parser_reads() -> None:
    seen: set[str] = set()
    frame = order_trade_update_frame(AP="61000.10", cr="1.5", M="1", er="0")
    frame["o"] = _RecordingDict(frame["o"], seen)
    assert isinstance(
        parse_order_trade_update(frame, observed_at_utc=OBSERVED_AT), OrderUpdateEvent
    )
    assert seen == ORDER_UPDATE_WIRE_FIELDS
    assert {"b", "a", "si", "ss"}.isdisjoint(ORDER_UPDATE_WIRE_FIELDS)


def test_algo_update_wire_fields_are_the_keys_the_parser_reads() -> None:
    seen: set[str] = set()
    frame = algo_update_frame(X="REJECTED", rm="Reduce Only reject", ap="0", aq="0", act="MARKET")
    frame["o"] = _RecordingDict(frame["o"], seen)
    assert isinstance(parse_algo_update(frame, observed_at_utc=OBSERVED_AT), AlgoUpdateEvent)
    assert seen == ALGO_UPDATE_WIRE_FIELDS


def test_account_update_wire_fields_are_the_keys_the_parser_reads() -> None:
    seen_a: set[str] = set()
    seen_b: set[str] = set()
    seen_p: set[str] = set()
    frame = account_update_frame(m="FUNDING_FEE", S="BTCUSDT")
    account = frame["a"]
    account["B"] = [_RecordingDict(row, seen_b) for row in account["B"]]
    account["P"] = [_RecordingDict(row, seen_p) for row in account["P"]]
    frame["a"] = _RecordingDict(account, seen_a)
    assert isinstance(parse_account_update(frame, observed_at_utc=OBSERVED_AT), AccountUpdateEvent)
    assert seen_a == ACCOUNT_UPDATE_WIRE_FIELDS
    assert seen_b == ACCOUNT_BALANCE_WIRE_FIELDS
    assert seen_p == ACCOUNT_POSITION_WIRE_FIELDS


def _sdk_aliases(module_name: str, class_name: str) -> set[str]:
    import importlib

    model = getattr(importlib.import_module(f"{_SDK_MODELS}.{module_name}"), class_name)
    return {
        info.alias or name
        for name, info in model.model_fields.items()
        if name != "additional_properties"  # the SDK's catch-all, not a wire key
    }


@pytest.mark.parametrize(
    ("fields", "module_name", "class_name"),
    [
        (ORDER_UPDATE_WIRE_FIELDS, "order_trade_update_o", "OrderTradeUpdateO"),
        (ALGO_UPDATE_WIRE_FIELDS, "algo_update_o", "AlgoUpdateO"),
        (ACCOUNT_UPDATE_WIRE_FIELDS, "account_update_a", "AccountUpdateA"),
        (ACCOUNT_BALANCE_WIRE_FIELDS, "account_update_ab_inner", "AccountUpdateABInner"),
        (ACCOUNT_POSITION_WIRE_FIELDS, "account_update_ap_inner", "AccountUpdateAPInner"),
    ],
)
def test_wire_fields_are_aliases_of_the_installed_sdk_model(
    fields: frozenset[str], module_name: str, class_name: str
) -> None:
    assert isinstance(fields, frozenset)
    assert fields <= _sdk_aliases(module_name, class_name)


def test_algo_wire_fields_cover_the_whole_sdk_model() -> None:
    assert ALGO_UPDATE_WIRE_FIELDS == _sdk_aliases("algo_update_o", "AlgoUpdateO")


# --------------------------------------------------------------------------- #
# AST guards: SDK-free, float-free, clock-free.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", [EVENTS_MODULE, ALGO_STATUS_MODULE], ids=["events", "algo_status"])
def test_pure_modules_have_no_forbidden_import_float_or_clock(path: Path) -> None:
    assert forbidden_imports(path, FORBIDDEN_PREFIXES) == []
    assert float_constructor_calls(path) == []
    assert wall_clock_calls(path) == []


def test_events_module_imports_only_stdlib_and_the_two_project_modules() -> None:
    allowed_project = {"src.execution.fill_monitor", "src.domain.algo_status"}
    for name in module_imports(EVENTS_MODULE):
        top = name.split(".")[0]
        assert name in allowed_project or top in sys.stdlib_module_names, name
    assert "src.domain.algo_status" in module_imports(EVENTS_MODULE)


def test_algo_status_module_imports_only_stdlib() -> None:
    for name in module_imports(ALGO_STATUS_MODULE):
        assert name.split(".")[0] in sys.stdlib_module_names, name


def test_ast_guards_detect_what_they_look_for(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import time\n"
        "import binance_common.utils\n"
        "from datetime import datetime\n"
        "from time import monotonic as mono\n"
        "from pydantic import BaseModel\n"
        "x = float('1')\n"
        "y = datetime.now()\n"
        "z = time.time()\n"
        "w = mono()\n",
        encoding="utf-8",
    )
    assert module_imports(sample) == [
        "time",
        "binance_common.utils",
        "datetime",
        "time",
        "pydantic",
    ]
    assert forbidden_imports(sample, FORBIDDEN_PREFIXES) == ["binance_common.utils", "pydantic"]
    assert float_constructor_calls(sample) == [6]
    assert wall_clock_calls(sample) == [
        (7, "datetime.now"),
        (8, "time.time"),
        (9, "time.monotonic"),
    ]
