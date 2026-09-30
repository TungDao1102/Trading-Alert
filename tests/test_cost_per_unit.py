"""Tests for the price-aware per-unit round-trip cost producer (Phase 12, plan 12-03).

Wave 0 file. The producer returns QUOTE CURRENCY PER UNIT OF BASE:

    entry_price * (fee_rate_entry + entry_slippage_rate)
      + stop_price * (fee_rate_exit + exit_slippage_rate)

Oracles are hand-derived literals (independent Decimal script at planning
time); no expectation here is computed by the code under test.

Rates: fee_rate_entry 0.0005, entry_slippage_rate 0.0001,
       fee_rate_exit 0.0005, exit_slippage_rate 0.0003.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from src.risk.cost_rates import (
    FEE_SOURCE_ACCOUNT_MAX,
    FEE_SOURCE_PARAMETER,
    FEE_SOURCES,
    MAX_RATE,
    CostRates,
    per_unit_round_trip_cost,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _rates(**overrides: object) -> CostRates:
    kwargs: dict[str, object] = {
        "fee_rate_entry": Decimal("0.0005"),
        "entry_slippage_rate": Decimal("0.0001"),
        "fee_rate_exit": Decimal("0.0005"),
        "exit_slippage_rate": Decimal("0.0003"),
        "fee_source": FEE_SOURCE_PARAMETER,
    }
    kwargs.update(overrides)
    return CostRates(**kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Hand-derived oracles (BTC LONG/SHORT, XRP, 0.5 percent stop).
# --------------------------------------------------------------------------- #


def test_btc_long_oracle() -> None:
    got = per_unit_round_trip_cost(
        side="LONG",
        entry_price=Decimal("60100"),
        stop_price=Decimal("58780"),
        rates=_rates(),
    )
    assert got == Decimal("83.0840")


def test_btc_short_oracle() -> None:
    got = per_unit_round_trip_cost(
        side="SHORT",
        entry_price=Decimal("59900"),
        stop_price=Decimal("61300"),
        rates=_rates(),
    )
    assert got == Decimal("84.9800")


def test_xrp_long_oracle() -> None:
    got = per_unit_round_trip_cost(
        side="LONG",
        entry_price=Decimal("0.5010"),
        stop_price=Decimal("0.4930"),
        rates=_rates(),
    )
    assert got == Decimal("0.000695")


def test_btc_half_percent_stop_oracle() -> None:
    got = per_unit_round_trip_cost(
        side="LONG",
        entry_price=Decimal("60100"),
        stop_price=Decimal("59800"),
        rates=_rates(),
    )
    assert got == Decimal("83.9000")


def test_result_is_decimal_never_float() -> None:
    got = per_unit_round_trip_cost(
        side="LONG",
        entry_price=Decimal("60100"),
        stop_price=Decimal("58780"),
        rates=_rates(),
    )
    assert isinstance(got, Decimal)


# --------------------------------------------------------------------------- #
# Linear scaling (the F-001 / F-801 regression: the cost is price-denominated).
# --------------------------------------------------------------------------- #


def test_doubling_prices_doubles_cost() -> None:
    got = per_unit_round_trip_cost(
        side="LONG",
        entry_price=Decimal("120200"),
        stop_price=Decimal("117560"),
        rates=_rates(),
    )
    assert got == Decimal("166.1680")


def test_halving_prices_halves_cost() -> None:
    got = per_unit_round_trip_cost(
        side="LONG",
        entry_price=Decimal("30050"),
        stop_price=Decimal("29390"),
        rates=_rates(),
    )
    assert got == Decimal("41.5420")


def test_rate_change_scales_affected_leg_only() -> None:
    # Only the exit slippage doubles (0.0003 -> 0.0006): the stop leg grows by
    # stop_price * 0.0003 = 58780 * 0.0003 = 17.634; the entry leg is unchanged.
    got = per_unit_round_trip_cost(
        side="LONG",
        entry_price=Decimal("60100"),
        stop_price=Decimal("58780"),
        rates=_rates(exit_slippage_rate=Decimal("0.0006")),
    )
    assert got == Decimal("83.0840") + Decimal("17.6340")


# --------------------------------------------------------------------------- #
# Input validation.
# --------------------------------------------------------------------------- #


def test_bad_side_raises_value_error() -> None:
    with pytest.raises(ValueError, match="side"):
        per_unit_round_trip_cost(
            side="FLAT",
            entry_price=Decimal("1"),
            stop_price=Decimal("1"),
            rates=_rates(),
        )


@pytest.mark.parametrize("bad", [1.5, 1, "1", True])
def test_non_decimal_price_raises_type_error(bad: object) -> None:
    with pytest.raises(TypeError):
        per_unit_round_trip_cost(
            side="LONG",
            entry_price=bad,  # type: ignore[arg-type]
            stop_price=Decimal("1"),
            rates=_rates(),
        )
    with pytest.raises(TypeError):
        per_unit_round_trip_cost(
            side="LONG",
            entry_price=Decimal("1"),
            stop_price=bad,  # type: ignore[arg-type]
            rates=_rates(),
        )


@pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-1")])
def test_non_positive_price_raises_value_error(bad: Decimal) -> None:
    with pytest.raises(ValueError):
        per_unit_round_trip_cost(
            side="LONG", entry_price=bad, stop_price=Decimal("1"), rates=_rates()
        )
    with pytest.raises(ValueError):
        per_unit_round_trip_cost(
            side="LONG", entry_price=Decimal("1"), stop_price=bad, rates=_rates()
        )


# --------------------------------------------------------------------------- #
# CostRates value object.
# --------------------------------------------------------------------------- #


def test_fee_sources_exactly_two() -> None:
    assert FEE_SOURCES == frozenset({"PARAMETER", "ACCOUNT_MAX"})
    assert FEE_SOURCE_PARAMETER == "PARAMETER"
    assert FEE_SOURCE_ACCOUNT_MAX == "ACCOUNT_MAX"
    assert Decimal("0.01") == MAX_RATE


@pytest.mark.parametrize("bad", [0.0005, 1, True, "0.0005"])
@pytest.mark.parametrize(
    "field",
    ["fee_rate_entry", "entry_slippage_rate", "fee_rate_exit", "exit_slippage_rate"],
)
def test_cost_rates_rejects_non_decimal(field: str, bad: object) -> None:
    with pytest.raises(TypeError):
        _rates(**{field: bad})


@pytest.mark.parametrize("bad", [Decimal("-0.0001"), Decimal("0.0100001"), Decimal("2")])
@pytest.mark.parametrize(
    "field",
    ["fee_rate_entry", "entry_slippage_rate", "fee_rate_exit", "exit_slippage_rate"],
)
def test_cost_rates_range_error_names_field(field: str, bad: Decimal) -> None:
    with pytest.raises(ValueError, match=field):
        _rates(**{field: bad})


def test_cost_rates_accepts_boundaries() -> None:
    r = _rates(fee_rate_entry=Decimal("0"), exit_slippage_rate=Decimal("0.01"))
    assert r.fee_rate_entry == Decimal("0")
    assert r.exit_slippage_rate == Decimal("0.01")


def test_cost_rates_rejects_unknown_fee_source() -> None:
    with pytest.raises(ValueError, match="fee_source"):
        _rates(fee_source="MAKER")


def test_cost_rates_is_frozen() -> None:
    r = _rates()
    with pytest.raises(AttributeError):
        r.fee_rate_entry = Decimal("0.001")  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Purity: risk imports nothing from backtest; no float arithmetic.
# --------------------------------------------------------------------------- #


def test_cost_rates_module_does_not_import_backtest() -> None:
    code = (
        "import sys\n"
        "import src.risk.cost_rates\n"
        "bad = sorted(\n"
        "    m for m in sys.modules\n"
        "    if m == 'src.backtest' or m.startswith('src.backtest.')\n"
        ")\n"
        "print(','.join(bad))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    )
    assert out.stdout.strip() == ""


def test_cost_rates_module_has_no_float_call() -> None:
    source = (REPO_ROOT / "src" / "risk" / "cost_rates.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "float"
        if isinstance(node, ast.Constant):
            assert not isinstance(node.value, float)


# --------------------------------------------------------------------------- #
# CostModel carries exit_slippage_rate; legacy models refused for sizing.
# --------------------------------------------------------------------------- #

_SEVEN = {
    "fee_rate_entry": "0.0005",
    "fee_rate_exit": "0.0005",
    "funding_treatment": "ADDITIVE",
    "expected_slippage": "0.0001",
    "slippage_model": "FIXED_BPS",
    "spread_fill_assumptions": "FULL_FILL",
    "partial_fill_fraction": "1",
}


def test_cost_model_exposes_exit_slippage_rate() -> None:
    from src.backtest.costs import build_cost_model

    model = build_cost_model({**_SEVEN, "exit_slippage_rate": "0.0003"})
    assert model.exit_slippage_rate == Decimal("0.0003")


def test_cost_model_without_key_is_legacy() -> None:
    from src.backtest.costs import build_cost_model

    model = build_cost_model(dict(_SEVEN))
    assert model.exit_slippage_rate is None
    assert len(model.cost_model_hash) == 64


def test_exit_slippage_presence_changes_hash() -> None:
    from src.backtest.costs import build_cost_model

    legacy = build_cost_model(dict(_SEVEN))
    eight = build_cost_model({**_SEVEN, "exit_slippage_rate": "0.0003"})
    assert legacy.cost_model_hash != eight.cost_model_hash


def test_exit_slippage_value_changes_hash() -> None:
    from src.backtest.costs import build_cost_model

    a = build_cost_model({**_SEVEN, "exit_slippage_rate": "0.0003"})
    b = build_cost_model({**_SEVEN, "exit_slippage_rate": "0.0004"})
    assert a.cost_model_hash != b.cost_model_hash


def test_legacy_registry_hash_unchanged_by_optional_field() -> None:
    from src.backtest.costs import build_cost_model

    model = build_cost_model(dict(_SEVEN))
    assert (
        model.cost_model_hash
        == "e18ce00931314a670dab22a4f0bd704c75d36c5d736c0c8ca04713050bb704d8"
    )


@pytest.mark.parametrize(
    "field", ["fee_rate_entry", "fee_rate_exit", "expected_slippage", "exit_slippage_rate"]
)
def test_cost_model_rejects_rate_above_ceiling(field: str) -> None:
    from src.backtest.costs import build_cost_model

    with pytest.raises(ValueError, match=field):
        build_cost_model({**_SEVEN, "exit_slippage_rate": "0.0003", field: "0.011"})


def test_cost_rates_from_model_maps_fields() -> None:
    from src.backtest.costs import build_cost_model, cost_rates_from_model

    model = build_cost_model({**_SEVEN, "exit_slippage_rate": "0.0003"})
    rates = cost_rates_from_model(model)
    assert rates == CostRates(
        fee_rate_entry=Decimal("0.0005"),
        entry_slippage_rate=Decimal("0.0001"),
        fee_rate_exit=Decimal("0.0005"),
        exit_slippage_rate=Decimal("0.0003"),
        fee_source=FEE_SOURCE_PARAMETER,
    )


def test_cost_rates_from_legacy_model_refused() -> None:
    from src.backtest.costs import build_cost_model, cost_rates_from_model

    model = build_cost_model(dict(_SEVEN))
    with pytest.raises(ValueError, match="exit_slippage_rate") as info:
        cost_rates_from_model(model)
    assert "legacy" in str(info.value)


def test_end_to_end_model_to_cost() -> None:
    from src.backtest.costs import build_cost_model, cost_rates_from_model

    model = build_cost_model({**_SEVEN, "exit_slippage_rate": "0.0003"})
    got = per_unit_round_trip_cost(
        side="LONG",
        entry_price=Decimal("60100"),
        stop_price=Decimal("58780"),
        rates=cost_rates_from_model(model),
    )
    assert got == Decimal("83.0840")


def test_old_two_argument_modeled_costs_per_unit_call_is_removed() -> None:
    """The rate-sum call form (cost_model, side) is gone: prices are required (D-01, D-18)."""
    from src.backtest.costs import build_cost_model, modeled_costs_per_unit

    model = build_cost_model(dict(_SEVEN))
    with pytest.raises(TypeError):
        modeled_costs_per_unit(cost_model=model, side="LONG")  # type: ignore[call-arg]


# --------------------------------------------------------------------------- #
# Task 2 - canonical cost-hash text (D-15), cost_slice, binding and freeze.
# --------------------------------------------------------------------------- #

# cost_model_hash of every existing registry set over its seven-key slice.
# Literal constants (never recomputed from the code under test): none of these
# may move when the canonical text rule lands.
LEGACY_COST_HASHES = {
    ("trend-pullback", "baseline-v3"): (
        "12c05d5f406196af7a53ebeb76b865bfc14dd955c0527629511404eaf631d9f2"
    ),
    ("trend-pullback", "baseline-v4"): (
        "e18ce00931314a670dab22a4f0bd704c75d36c5d736c0c8ca04713050bb704d8"
    ),
    ("breakout-retest", "baseline-v4"): (
        "e18ce00931314a670dab22a4f0bd704c75d36c5d736c0c8ca04713050bb704d8"
    ),
    ("range-mr", "baseline-v4"): (
        "e18ce00931314a670dab22a4f0bd704c75d36c5d736c0c8ca04713050bb704d8"
    ),
    ("trend-pullback", "baseline-no-trade-v2"): (
        "e18ce00931314a670dab22a4f0bd704c75d36c5d736c0c8ca04713050bb704d8"
    ),
    ("trend-pullback", "baseline-simple-trend-v2"): (
        "e18ce00931314a670dab22a4f0bd704c75d36c5d736c0c8ca04713050bb704d8"
    ),
    ("trend-pullback", "baseline-no-trade-v1"): (
        "98d177271d961ad6c15d26523866de60e771d0dccf45f1cfdfe92ed17deca80e"
    ),
    ("trend-pullback", "baseline-simple-trend-v1"): (
        "98d177271d961ad6c15d26523866de60e771d0dccf45f1cfdfe92ed17deca80e"
    ),
}

V5_SETS = (
    ("trend-pullback", "baseline-v5"),
    ("breakout-retest", "baseline-v5"),
    ("range-mr", "baseline-v5"),
    ("trend-pullback", "baseline-no-trade-v3"),
    ("trend-pullback", "baseline-simple-trend-v3"),
)


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (Decimal("0"), "0"),
        (Decimal("0.0"), "0"),
        (Decimal("0.000"), "0"),
        (Decimal("-0"), "0"),
        (Decimal("-0.00"), "0"),
        (Decimal("1"), "1"),
        (Decimal("1.0"), "1"),
        (Decimal("1.00"), "1"),
        (Decimal("0.00020"), "0.0002"),
        (Decimal("0.0002"), "0.0002"),
        (Decimal("100"), "100"),
        (Decimal("1E+2"), "100"),
        (Decimal("1.5E-3"), "0.0015"),
        (Decimal("0.5"), "0.5"),
    ],
)
def test_canonical_decimal_text(value: Decimal, text: str) -> None:
    from src.backtest.costs import _canonical_decimal_text

    assert _canonical_decimal_text(value) == text


def _cost(**overrides: object) -> dict[str, object]:
    return {**_SEVEN, **overrides}


def test_fee_spellings_hash_equal() -> None:
    from src.backtest.costs import build_cost_model

    spellings = ("0.0005", "0.00050", Decimal("0.00050"), Decimal("0.0005"))
    hashes = {
        build_cost_model(_cost(fee_rate_entry=s)).cost_model_hash for s in spellings
    }
    assert len(hashes) == 1


def test_partial_fill_fraction_one_spellings_hash_equal() -> None:
    from src.backtest.costs import build_cost_model

    hashes = {
        build_cost_model(_cost(partial_fill_fraction=s)).cost_model_hash
        for s in ("1", "1.0", 1, Decimal("1.00"), Decimal("1"))
    }
    assert len(hashes) == 1


def test_zero_spellings_hash_equal() -> None:
    from src.backtest.costs import build_cost_model

    hashes = {
        build_cost_model(_cost(fee_rate_exit=s)).cost_model_hash
        for s in ("0", "0.0", 0, Decimal("0"), Decimal("0.000"))
    }
    assert len(hashes) == 1


def test_genuine_change_still_changes_hash() -> None:
    from src.backtest.costs import build_cost_model

    base = build_cost_model(_cost()).cost_model_hash
    assert build_cost_model(_cost(fee_rate_entry="0.0006")).cost_model_hash != base
    assert build_cost_model(_cost(funding_treatment="PRO_RATA")).cost_model_hash != base
    assert build_cost_model(_cost(partial_fill_fraction="0.5")).cost_model_hash != base


def test_exit_slippage_spellings_hash_equal() -> None:
    from src.backtest.costs import build_cost_model

    a = build_cost_model(_cost(exit_slippage_rate="0.0003")).cost_model_hash
    b = build_cost_model(_cost(exit_slippage_rate="0.00030")).cost_model_hash
    c = build_cost_model(_cost(exit_slippage_rate=Decimal("0.00030"))).cost_model_hash
    assert a == b == c


@pytest.mark.parametrize(("strategy_id", "set_id"), sorted(LEGACY_COST_HASHES))
def test_legacy_registry_cost_hashes_do_not_move(strategy_id: str, set_id: str) -> None:
    from src.backtest.costs import build_cost_model, cost_slice
    from src.domain.registry import load_parameter_set

    params = load_parameter_set(strategy_id, set_id).params
    model = build_cost_model(cost_slice(params))
    assert model.exit_slippage_rate is None
    assert model.cost_model_hash == LEGACY_COST_HASHES[(strategy_id, set_id)]


def test_supplied_hash_verified_against_canonical_hash() -> None:
    from src.backtest.costs import CostModel, build_cost_model

    good7 = build_cost_model(_cost())
    good8 = build_cost_model(_cost(exit_slippage_rate="0.0003"))
    for good in (good7, good8):
        kwargs: dict[str, object] = {
            "fee_rate_entry": good.fee_rate_entry,
            "fee_rate_exit": good.fee_rate_exit,
            "funding_treatment": good.funding_treatment,
            "expected_slippage": good.expected_slippage,
            "slippage_model": good.slippage_model,
            "spread_fill_assumptions": good.spread_fill_assumptions,
            "partial_fill_fraction": good.partial_fill_fraction,
            "exit_slippage_rate": good.exit_slippage_rate,
        }
        with pytest.raises(ValueError, match="mismatch"):
            CostModel(cost_model_hash="f" * 64, **kwargs)  # type: ignore[arg-type]
        ok = CostModel(cost_model_hash=good.cost_model_hash, **kwargs)  # type: ignore[arg-type]
        assert ok.cost_model_hash == good.cost_model_hash


def test_cost_slice_legacy_set_is_seven_keys() -> None:
    from src.backtest.costs import COST_KEYS, cost_slice
    from src.domain.registry import load_parameter_set

    params = load_parameter_set("trend-pullback", "baseline-v4").params
    assert tuple(sorted(cost_slice(params))) == tuple(sorted(COST_KEYS))


def test_cost_slice_v5_set_adds_exit_slippage() -> None:
    from src.backtest.costs import COST_KEYS, cost_slice
    from src.domain.registry import load_parameter_set

    params = load_parameter_set("trend-pullback", "baseline-v5").params
    sliced = cost_slice(params)
    assert set(sliced) == {*COST_KEYS, "exit_slippage_rate"}
    assert Decimal(str(sliced["exit_slippage_rate"])) == Decimal("0.0003")


def test_cost_slice_missing_required_key_raises_bare_key_error() -> None:
    from src.backtest.costs import cost_slice
    from src.domain.registry import load_parameter_set

    params = load_parameter_set("trend-pullback", "baseline-v2").params
    with pytest.raises(KeyError):
        cost_slice(params)


def test_cost_keys_tuple_unchanged() -> None:
    from src.backtest.costs import COST_KEYS

    assert len(COST_KEYS) == 7
    assert "exit_slippage_rate" not in COST_KEYS


@pytest.mark.parametrize(("strategy_id", "set_id"), V5_SETS)
def test_v5_slice_hashes_over_eight_keys(strategy_id: str, set_id: str) -> None:
    from src.backtest.costs import build_cost_model, cost_slice
    from src.domain.registry import load_parameter_set

    params = load_parameter_set(strategy_id, set_id).params
    model = build_cost_model(cost_slice(params))
    assert model.exit_slippage_rate == Decimal("0.0003")
    legacy_hash = LEGACY_COST_HASHES[("trend-pullback", "baseline-v4")]
    assert model.cost_model_hash != legacy_hash


def test_v5_sets_share_one_cost_hash() -> None:
    from src.backtest.costs import build_cost_model, cost_slice
    from src.domain.registry import load_parameter_set

    hashes = {
        build_cost_model(cost_slice(load_parameter_set(s, p).params)).cost_model_hash
        for s, p in V5_SETS
    }
    assert len(hashes) == 1


def _v5_cost_dict() -> dict[str, object]:
    from src.backtest.costs import cost_slice
    from src.domain.registry import load_parameter_set

    return dict(cost_slice(load_parameter_set("trend-pullback", "baseline-v5").params))


def _assemble_v5(cost_model: object) -> object:
    from datetime import UTC, datetime

    from src.backtest.experiment import assemble

    return assemble(
        parameter_set_id="baseline-v5",
        strategy_id="trend-pullback",
        strategy_version="v4.0.0",
        data_snapshot_id="1" * 64,
        code_version="12-03",
        cost_model=cost_model,  # type: ignore[arg-type]
        time_range_start_utc=datetime(2026, 9, 1, tzinfo=UTC),
        time_range_end_utc=datetime(2026, 9, 11, tzinfo=UTC),
        universe=["BTCUSDT"],
        run_type="CANDIDATE",
        notes="12-03 v5 binding",
    )


def test_binding_v5_set_accepts_matching_eight_key_model() -> None:
    from src.backtest.costs import build_cost_model

    record = _assemble_v5(build_cost_model(_v5_cost_dict()))
    assert len(record.cost_model_hash) == 64  # type: ignore[attr-defined]


def test_binding_v5_set_refuses_seven_key_model() -> None:
    from src.backtest.binding import CostModelBindingMismatch
    from src.backtest.costs import build_cost_model

    seven = {k: v for k, v in _v5_cost_dict().items() if k != "exit_slippage_rate"}
    with pytest.raises(CostModelBindingMismatch):
        _assemble_v5(build_cost_model(seven))


def test_binding_v5_set_refuses_disagreeing_exit_slippage() -> None:
    from src.backtest.binding import CostModelBindingMismatch
    from src.backtest.costs import build_cost_model

    other = {**_v5_cost_dict(), "exit_slippage_rate": "0.0004"}
    with pytest.raises(CostModelBindingMismatch):
        _assemble_v5(build_cost_model(other))


def test_binding_legacy_set_with_seven_key_model_unchanged() -> None:
    from datetime import UTC, datetime

    from src.backtest.costs import build_cost_model, cost_slice
    from src.backtest.experiment import assemble
    from src.domain.registry import load_parameter_set

    params = load_parameter_set("trend-pullback", "baseline-v4").params
    record = assemble(
        parameter_set_id="baseline-v4",
        strategy_id="trend-pullback",
        strategy_version="v3.0.0",
        data_snapshot_id="1" * 64,
        code_version="12-03",
        cost_model=build_cost_model(cost_slice(params)),
        time_range_start_utc=datetime(2026, 9, 1, tzinfo=UTC),
        time_range_end_utc=datetime(2026, 9, 11, tzinfo=UTC),
        universe=["BTCUSDT"],
        run_type="CANDIDATE",
        notes="12-03 legacy binding",
    )
    assert record.cost_model_hash == LEGACY_COST_HASHES[("trend-pullback", "baseline-v4")]


def test_freeze_v5_set_pins_and_refuses_seven_key_model() -> None:
    from datetime import UTC, datetime

    from src.backtest.binding import CostModelBindingMismatch
    from src.backtest.costs import build_cost_model
    from src.paper.freeze import pin_stream_epoch

    opened = datetime(2026, 9, 19, 10, 0, tzinfo=UTC)
    epoch = pin_stream_epoch(
        strategy_id="trend-pullback",
        parameter_set_id="baseline-v5",
        opened_at_utc=opened,
        cost_model=build_cost_model(_v5_cost_dict()),
    )
    assert epoch.parameter_set_id == "baseline-v5"

    seven = {k: v for k, v in _v5_cost_dict().items() if k != "exit_slippage_rate"}
    with pytest.raises(CostModelBindingMismatch):
        pin_stream_epoch(
            strategy_id="trend-pullback",
            parameter_set_id="baseline-v5",
            opened_at_utc=opened,
            cost_model=build_cost_model(seven),
        )
