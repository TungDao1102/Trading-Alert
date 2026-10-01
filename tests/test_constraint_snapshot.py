"""Pure per-plan constraint snapshot (Phase 17 plan 06, EXEC-04, D-18, D-19, D-21).

The snapshot module is stdlib + Decimal + src.domain + src.risk.types only. Tests do
the SymbolFilters -> primitive mapping explicitly so the module never imports the
adapter.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import re
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    ExchangeInformationResponse,
)
from src.adapters.binance_usdm import BinanceUsdmAdapter, SymbolFilters
from src.domain.enums import LiveInputsStatus
from src.domain.registry import ParameterSet
from src.execution.constraint_snapshot import (
    UNKNOWN,
    ExchangeFilterExtras,
    PlanConstraintSnapshot,
    build_plan_constraint_snapshot,
    canonical_json,
    parse_snapshot_json,
    snapshot_is_valid_for_live,
    snapshot_sha256,
    ttl_from_parameter_set,
)
from src.risk.types import ConstraintSnapshot

_FIXTURE = Path(__file__).parent / "fixtures" / "exchange_info_sample.json"
_SRC = Path(__file__).resolve().parents[1] / "src" / "execution" / "constraint_snapshot.py"

OBSERVED = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)
CAPTURED = datetime(2026, 9, 30, 12, 0, 5, tzinfo=UTC)
TTL = timedelta(seconds=3600)


def _constraints(symbol: str = "BTCUSDT") -> ConstraintSnapshot:
    return ConstraintSnapshot(
        symbol=symbol,
        price_tick_size=Decimal("0.10"),
        quantity_step_size=Decimal("0.001"),
        min_quantity=Decimal("0.001"),
        min_notional=Decimal("50"),
        metadata_observed_at_utc=OBSERVED,
    )


def _extras(**overrides: Any) -> ExchangeFilterExtras:
    base: dict[str, Any] = {
        "market_lot_min_quantity": Decimal("0.001"),
        "market_lot_max_quantity": Decimal("120"),
        "market_lot_step_size": Decimal("0.001"),
        "percent_price_multiplier_up": Decimal("1.0500"),
        "percent_price_multiplier_down": Decimal("0.9500"),
        "percent_price_multiplier_decimals": 4,
    }
    base.update(overrides)
    return ExchangeFilterExtras(**base)


def _complete(**overrides: Any) -> PlanConstraintSnapshot:
    kwargs: dict[str, Any] = {
        "max_quantity": Decimal("1000"),
        "working_type": "MARK_PRICE",
        "margin_type": "ISOLATED",
        "leverage": 5,
        "equity_used": Decimal("1000.50"),
        "captured_at_utc": CAPTURED,
    }
    kwargs.update(overrides)
    return build_plan_constraint_snapshot("plan-1", _constraints(), _extras(), **kwargs)


def _incomplete(**overrides: Any) -> PlanConstraintSnapshot:
    kwargs: dict[str, Any] = {
        "max_quantity": Decimal("1000"),
        "working_type": "MARK_PRICE",
        "captured_at_utc": CAPTURED,
    }
    kwargs.update(overrides)
    return build_plan_constraint_snapshot("plan-1", _constraints(), _extras(), **kwargs)


# --------------------------------------------------------------------------- #
# Build + completeness
# --------------------------------------------------------------------------- #


def test_build_returns_frozen_snapshot_with_all_fields() -> None:
    snap = _complete()
    assert snap.trade_plan_id == "plan-1"
    assert snap.symbol == "BTCUSDT"
    assert snap.price_tick_size == Decimal("0.10")
    assert snap.quantity_step_size == Decimal("0.001")
    assert snap.min_quantity == Decimal("0.001")
    assert snap.max_quantity == Decimal("1000")
    assert snap.min_notional == Decimal("50")
    assert snap.market_lot_max_quantity == Decimal("120")
    assert snap.percent_price_multiplier_decimals == 4
    assert snap.working_type == "MARK_PRICE"
    assert snap.margin_type == "ISOLATED"
    assert snap.leverage == 5
    assert snap.equity_used == Decimal("1000.50")
    assert snap.constraints_observed_at_utc == OBSERVED
    assert snap.captured_at_utc == CAPTURED
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.symbol = "ETHUSDT"  # type: ignore[misc]


def test_complete_when_all_live_inputs_and_filters_known() -> None:
    assert _complete().live_inputs_status is LiveInputsStatus.COMPLETE


def test_unknown_live_inputs_make_the_snapshot_incomplete_with_sentinel_json() -> None:
    snap = _incomplete()
    assert snap.margin_type is None
    assert snap.leverage is None
    assert snap.equity_used is None
    assert snap.live_inputs_status is LiveInputsStatus.INCOMPLETE
    doc = json.loads(canonical_json(snap))
    assert doc["margin_type"] == UNKNOWN == "UNKNOWN"
    assert doc["leverage"] == "UNKNOWN"
    assert doc["equity_used"] == "UNKNOWN"


@pytest.mark.parametrize("missing", ["margin_type", "leverage", "equity_used"])
def test_each_missing_live_input_alone_is_incomplete(missing: str) -> None:
    full: dict[str, Any] = {"margin_type": "ISOLATED", "leverage": 3, "equity_used": Decimal("10")}
    full[missing] = None
    snap = _incomplete(**full)
    assert snap.live_inputs_status is LiveInputsStatus.INCOMPLETE


@pytest.mark.parametrize(
    "field",
    [
        "market_lot_min_quantity",
        "market_lot_max_quantity",
        "market_lot_step_size",
        "percent_price_multiplier_up",
        "percent_price_multiplier_down",
        "percent_price_multiplier_decimals",
    ],
)
def test_absent_filter_value_is_unknown_and_incomplete(field: str) -> None:
    snap = build_plan_constraint_snapshot(
        "plan-1",
        _constraints(),
        _extras(**{field: None}),
        max_quantity=Decimal("1000"),
        working_type="MARK_PRICE",
        margin_type="ISOLATED",
        leverage=5,
        equity_used=Decimal("100"),
        captured_at_utc=CAPTURED,
    )
    assert snap.live_inputs_status is LiveInputsStatus.INCOMPLETE
    assert json.loads(canonical_json(snap))[field] == UNKNOWN


def test_absent_max_quantity_is_unknown_and_incomplete() -> None:
    snap = _complete(max_quantity=None)
    assert snap.max_quantity is None
    assert snap.live_inputs_status is LiveInputsStatus.INCOMPLETE
    assert json.loads(canonical_json(snap))["max_quantity"] == UNKNOWN


# --------------------------------------------------------------------------- #
# Canonical JSON, hash, round trip
# --------------------------------------------------------------------------- #


def test_canonical_json_is_byte_identical_sorted_text_decimals_and_float_free() -> None:
    a, b = _complete(), _complete()
    assert a == b
    text_a, text_b = canonical_json(a), canonical_json(b)
    assert text_a == text_b
    assert isinstance(text_a, str)
    doc = json.loads(text_a)
    assert list(doc) == sorted(doc)
    # Decimals are text with their exchange spelling preserved, never JSON numbers.
    assert doc["price_tick_size"] == "0.10"
    assert doc["percent_price_multiplier_up"] == "1.0500"
    assert doc["equity_used"] == "1000.50"
    assert isinstance(doc["leverage"], int)
    assert isinstance(doc["percent_price_multiplier_decimals"], int)
    # No JSON number with a fraction or exponent anywhere in the document text.
    assert re.search(r"(?<![\"\w.])-?\d+\.\d+(?![\"\w.])", text_a) is None
    assert doc["constraints_observed_at_utc"] == "2026-09-30T12:00:00+00:00"
    assert doc["captured_at_utc"] == "2026-09-30T12:00:05+00:00"
    assert doc["trade_plan_id"] == "plan-1"
    assert doc["working_type"] == "MARK_PRICE"


def test_sha256_is_hex_of_the_canonical_bytes() -> None:
    import hashlib

    snap = _complete()
    expected = hashlib.sha256(canonical_json(snap).encode("utf-8")).hexdigest()
    assert snapshot_sha256(snap) == expected
    assert re.fullmatch(r"[0-9a-f]{64}", snapshot_sha256(snap))


def test_sha256_changes_when_any_value_changes() -> None:
    base = snapshot_sha256(_complete())
    assert snapshot_sha256(_complete(leverage=6)) != base
    assert snapshot_sha256(_complete(equity_used=Decimal("1000.51"))) != base
    assert snapshot_sha256(_complete(captured_at_utc=CAPTURED + timedelta(seconds=1))) != base


@pytest.mark.parametrize("factory", [_complete, _incomplete])
def test_round_trip_through_text(factory: Any) -> None:
    snap = factory()
    text = canonical_json(snap)
    parsed = parse_snapshot_json(text)
    assert parsed == snap
    assert canonical_json(parsed) == text
    assert snapshot_sha256(parsed) == snapshot_sha256(snap)
    assert parsed.live_inputs_status is snap.live_inputs_status


def test_parse_rejects_unknown_missing_and_float_values() -> None:
    doc = json.loads(canonical_json(_complete()))
    with pytest.raises(ValueError):
        parse_snapshot_json(json.dumps({**doc, "surprise": "x"}))
    missing = dict(doc)
    del missing["min_notional"]
    with pytest.raises(ValueError):
        parse_snapshot_json(json.dumps(missing))
    # A JSON number where a Decimal text is required is a float in disguise.
    with pytest.raises(ValueError):
        parse_snapshot_json(json.dumps({**doc, "price_tick_size": 0.1}))
    with pytest.raises(ValueError):
        parse_snapshot_json(json.dumps({**doc, "leverage": 5.0}))
    with pytest.raises(ValueError):
        parse_snapshot_json(json.dumps({**doc, "snapshot_schema_version": 999}))
    with pytest.raises(ValueError):
        parse_snapshot_json("not json")
    with pytest.raises(ValueError):
        parse_snapshot_json("[]")


def test_parse_rejects_non_utc_or_naive_datetimes_and_bad_decimal_text() -> None:
    doc = json.loads(canonical_json(_complete()))
    with pytest.raises(ValueError):
        parse_snapshot_json(json.dumps({**doc, "captured_at_utc": "2026-09-30T12:00:05"}))
    with pytest.raises(ValueError):
        parse_snapshot_json(json.dumps({**doc, "captured_at_utc": "2026-09-30T19:00:05+07:00"}))
    with pytest.raises(ValueError):
        parse_snapshot_json(json.dumps({**doc, "price_tick_size": "abc"}))


# --------------------------------------------------------------------------- #
# Input validation
# --------------------------------------------------------------------------- #


def test_working_type_other_than_mark_price_is_rejected() -> None:
    with pytest.raises(ValueError):
        _complete(working_type="CONTRACT_PRICE")
    with pytest.raises(ValueError):
        _complete(working_type="")


def test_float_numeric_inputs_raise_type_error() -> None:
    with pytest.raises(TypeError):
        _complete(max_quantity=1000.0)
    with pytest.raises(TypeError):
        _complete(equity_used=100.5)
    with pytest.raises(TypeError):
        _complete(leverage=5.0)
    with pytest.raises(TypeError):
        build_plan_constraint_snapshot(
            "plan-1",
            _constraints(),
            _extras(market_lot_step_size=0.001),
            max_quantity=Decimal("1000"),
            working_type="MARK_PRICE",
            captured_at_utc=CAPTURED,
        )
    with pytest.raises(TypeError):
        build_plan_constraint_snapshot(
            "plan-1",
            _constraints(),
            _extras(percent_price_multiplier_decimals=4.0),
            max_quantity=Decimal("1000"),
            working_type="MARK_PRICE",
            captured_at_utc=CAPTURED,
        )


def test_bool_is_not_an_int_for_leverage() -> None:
    with pytest.raises(TypeError):
        _complete(leverage=True)


@pytest.mark.parametrize("bad", [0, -1])
def test_leverage_must_be_positive(bad: int) -> None:
    with pytest.raises(ValueError):
        _complete(leverage=bad)


@pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-5"), Decimal("NaN"), Decimal("Infinity")])
def test_equity_used_must_be_positive_finite_decimal(bad: Decimal) -> None:
    with pytest.raises(ValueError):
        _complete(equity_used=bad)


def test_naive_or_non_utc_datetimes_are_rejected() -> None:
    with pytest.raises(ValueError):
        _complete(captured_at_utc=datetime(2026, 9, 30, 12, 0, 5))
    with pytest.raises(ValueError):
        _complete(
            captured_at_utc=datetime(2026, 9, 30, 19, 0, 5, tzinfo=timezone(timedelta(hours=7)))
        )


def test_margin_type_unknown_literal_and_empty_are_rejected() -> None:
    with pytest.raises(ValueError):
        _complete(margin_type="UNKNOWN")
    with pytest.raises(ValueError):
        _complete(margin_type="")


def test_negative_percent_price_decimals_rejected() -> None:
    with pytest.raises(ValueError):
        build_plan_constraint_snapshot(
            "plan-1",
            _constraints(),
            _extras(percent_price_multiplier_decimals=-1),
            max_quantity=Decimal("1000"),
            working_type="MARK_PRICE",
            captured_at_utc=CAPTURED,
        )


def test_direct_construction_validates_too() -> None:
    snap = _complete()
    with pytest.raises(ValueError):
        dataclasses.replace(snap, price_tick_size=Decimal("0"))
    with pytest.raises(ValueError):
        dataclasses.replace(snap, trade_plan_id="")
    with pytest.raises(TypeError):
        dataclasses.replace(snap, min_notional=50.0)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Live validity (mirrors the placement gate's stale predicate)
# --------------------------------------------------------------------------- #


def test_incomplete_snapshot_is_never_valid_for_live() -> None:
    assert snapshot_is_valid_for_live(_incomplete(), now_utc=OBSERVED, ttl=TTL) is False


def test_fresh_complete_snapshot_is_valid_for_live() -> None:
    assert snapshot_is_valid_for_live(
        _complete(), now_utc=OBSERVED + timedelta(seconds=10), ttl=TTL
    )


def test_age_exactly_ttl_is_valid_and_one_microsecond_over_is_stale() -> None:
    snap = _complete()
    assert snapshot_is_valid_for_live(snap, now_utc=OBSERVED + TTL, ttl=TTL) is True
    over = OBSERVED + TTL + timedelta(microseconds=1)
    assert snapshot_is_valid_for_live(snap, now_utc=over, ttl=TTL) is False


def test_future_dated_capture_is_invalid() -> None:
    snap = _complete()
    assert (
        snapshot_is_valid_for_live(snap, now_utc=OBSERVED - timedelta(seconds=1), ttl=TTL) is False
    )


def test_age_is_measured_from_the_exchange_capture_not_captured_at() -> None:
    snap = _complete()
    # captured_at is 5s after observed; now is exactly observed + ttl: still valid.
    assert snapshot_is_valid_for_live(snap, now_utc=OBSERVED + TTL, ttl=TTL) is True
    assert snap.constraints_observed_at_utc == OBSERVED


def test_validity_rejects_naive_now_and_bad_ttl() -> None:
    snap = _complete()
    with pytest.raises(ValueError):
        snapshot_is_valid_for_live(snap, now_utc=datetime(2026, 9, 30, 12, 0, 0), ttl=TTL)
    with pytest.raises(ValueError):
        snapshot_is_valid_for_live(snap, now_utc=OBSERVED, ttl=timedelta(seconds=-1))
    with pytest.raises(TypeError):
        snapshot_is_valid_for_live(snap, now_utc=OBSERVED, ttl=3600)  # type: ignore[arg-type]


def _param_set(params: dict[str, Any]) -> ParameterSet:
    return ParameterSet(
        strategy_id="breakout-retest",
        strategy_version="v1",
        parameter_set_id="test",
        parameter_set_hash="0" * 64,
        params=params,
    )


def test_ttl_comes_from_the_parameter_set() -> None:
    assert ttl_from_parameter_set(_param_set({"constraint_snapshot_ttl_seconds": 900})) == (
        timedelta(seconds=900)
    )


def test_ttl_reads_a_real_registered_parameter_set() -> None:
    from src.domain.registry import load_parameter_set

    loaded = load_parameter_set("breakout-retest", "baseline-v4")
    assert ttl_from_parameter_set(loaded) == timedelta(
        seconds=int(loaded.params["constraint_snapshot_ttl_seconds"])
    )


@pytest.mark.parametrize("bad", [None, True, 0, -5, 1.5, "3600"])
def test_ttl_missing_or_malformed_fails_closed(bad: Any) -> None:
    with pytest.raises(ValueError):
        ttl_from_parameter_set(_param_set({"constraint_snapshot_ttl_seconds": bad}))
    with pytest.raises(ValueError):
        ttl_from_parameter_set(_param_set({}))


# --------------------------------------------------------------------------- #
# Built from the parsed exchangeInfo sample for all five symbols
# --------------------------------------------------------------------------- #


def _parsed_sample() -> list[SymbolFilters]:
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    info = ExchangeInformationResponse.from_dict(raw)

    class _Rest:
        def exchange_information(self) -> Any:
            class _R:
                def data(self_inner) -> Any:  # noqa: N805
                    return info

            return _R()

    class _Sdk:
        rest_api = _Rest()

    return asyncio.run(BinanceUsdmAdapter(sdk_client=_Sdk()).exchange_info())  # type: ignore[arg-type]


def _map(filters: SymbolFilters) -> tuple[ConstraintSnapshot, ExchangeFilterExtras]:
    constraints = ConstraintSnapshot(
        symbol=filters.symbol,
        price_tick_size=filters.price_tick_size,
        quantity_step_size=filters.quantity_step_size,
        min_quantity=filters.min_quantity,
        min_notional=filters.min_notional,
        metadata_observed_at_utc=OBSERVED,
    )
    extras = ExchangeFilterExtras(
        market_lot_min_quantity=filters.market_lot_min_quantity,
        market_lot_max_quantity=filters.market_lot_max_quantity,
        market_lot_step_size=filters.market_lot_step_size,
        percent_price_multiplier_up=filters.percent_price_multiplier_up,
        percent_price_multiplier_down=filters.percent_price_multiplier_down,
        percent_price_multiplier_decimals=filters.percent_price_multiplier_decimals,
    )
    return constraints, extras


def test_snapshots_from_the_five_symbol_sample_list_both_filters() -> None:
    parsed = _parsed_sample()
    assert {f.symbol for f in parsed} == {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"}
    hashes = set()
    for filters in parsed:
        constraints, extras = _map(filters)
        snap = build_plan_constraint_snapshot(
            f"plan-{filters.symbol}",
            constraints,
            extras,
            max_quantity=filters.max_quantity,
            working_type="MARK_PRICE",
            captured_at_utc=CAPTURED,
        )
        doc = json.loads(canonical_json(snap))
        assert doc["symbol"] == filters.symbol
        assert doc["market_lot_max_quantity"] == str(filters.market_lot_max_quantity)
        assert doc["market_lot_step_size"] == str(filters.market_lot_step_size)
        assert doc["market_lot_min_quantity"] == str(filters.market_lot_min_quantity)
        assert doc["percent_price_multiplier_up"] == str(filters.percent_price_multiplier_up)
        assert doc["percent_price_multiplier_down"] == str(filters.percent_price_multiplier_down)
        assert doc["percent_price_multiplier_decimals"] == 4
        assert UNKNOWN not in (
            doc["market_lot_max_quantity"],
            doc["percent_price_multiplier_up"],
            doc["max_quantity"],
        )
        # Margin type, leverage and equity are not known until Phases 21-22 (D-19).
        assert snap.live_inputs_status is LiveInputsStatus.INCOMPLETE
        assert parse_snapshot_json(canonical_json(snap)) == snap
        hashes.add(snapshot_sha256(snap))
    assert len(hashes) == 5


# --------------------------------------------------------------------------- #
# Import boundary and float purity
# --------------------------------------------------------------------------- #


def test_module_does_not_import_the_sdk_or_adapters() -> None:
    source = _SRC.read_text(encoding="utf-8")
    assert re.search(r"^\s*(from|import)\s+(src\.adapters|binance)", source, re.M) is None


def test_module_has_no_float_usage() -> None:
    source = _SRC.read_text(encoding="utf-8")
    assert re.search(r"\bfloat\(", source) is None
    assert re.search(r":\s*float\b", source) is None
