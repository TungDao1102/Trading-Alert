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
        "bad = sorted(m for m in sys.modules if m == 'src.backtest' or m.startswith('src.backtest.'))\n"
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


def test_old_modeled_costs_per_unit_untouched() -> None:
    from src.backtest.costs import build_cost_model, modeled_costs_per_unit

    model = build_cost_model(dict(_SEVEN))
    assert modeled_costs_per_unit(cost_model=model, side="LONG") == Decimal("0.0011")
