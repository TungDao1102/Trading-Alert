"""Pure cost model — frozen dataclass + hash + per-unit formula (Phase 6, plan 06-01).

Per D-02: costs apply from run #1 before any selection decision. The
`CostModel` is a frozen dataclass built from registry cost keys, with
`cost_model_hash` computed via `sha256_hex` over the sorted seven-key
snapshot. `modeled_costs_per_unit` delegates to the same per-unit
formula `src/risk/sizing.py` consumes — never re-derived inside the
simulator body.

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 / Phase-5 D-05 purity precedent.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.core._decimal import _add
from src.domain.canonical import sha256_hex

# Canonical cost-key vocabulary (D-02 + Pitfall 7). These keys are
# read from the loaded ParameterSet.params dict; absent keys raise
# KeyError (fail closed, never silent defaults).
COST_KEYS: tuple[str, ...] = (
    "fee_rate_entry",
    "fee_rate_exit",
    "funding_treatment",
    "expected_slippage",
    "slippage_model",
    "spread_fill_assumptions",
    "partial_fill_fraction",
)


def _coerce_decimal(value: object, field_name: str) -> Decimal:
    """Coerce a money/rate field to Decimal without losing precision (D-12).

    A `Decimal` input is returned AS-IS — never round-tripped through
    `str()`, which would drop trailing precision (`Decimal("0.00020")`
    → `"0.0002"` → a different `cost_model_hash`). String inputs keep
    their exact spelling (`Decimal("0.00020")` stays `"0.00020"`).
    Plain ints are exact. Bools and floats are rejected fail-closed:
    bool is not a rate, and float carries binary noise.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be Decimal/str/int, got bool")
    if isinstance(value, str):
        return Decimal(value)
    if isinstance(value, int):
        return Decimal(value)
    raise TypeError(
        f"{field_name} must be Decimal/str/int, got {type(value).__name__}"
    )


def _require_non_negative(value: Decimal, field_name: str) -> None:
    """Reject negative Decimals for rate fields."""
    if value < Decimal("0"):
        raise ValueError(f"{field_name} must be >= 0, got {value}")


def _require_in_range(value: Decimal, field_name: str, lo: Decimal, hi: Decimal) -> None:
    """Reject Decimals outside [lo, hi]."""
    if value < lo or value > hi:
        raise ValueError(f"{field_name} must be in [{lo}, {hi}], got {value}")


# --------------------------------------------------------------------------- #
# CostModel — frozen value object with computed cost_model_hash.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CostModel:
    """Registry-parameterized cost model (D-02).

    `cost_model_hash` is SHA256 over the canonical JSON of the sorted
    seven-key snapshot. Once referenced by an experiment, the hash is
    permanent (D-03).
    """

    fee_rate_entry: Decimal
    fee_rate_exit: Decimal
    funding_treatment: str
    expected_slippage: Decimal
    slippage_model: str
    spread_fill_assumptions: str
    partial_fill_fraction: Decimal
    cost_model_hash: str

    def __post_init__(self) -> None:
        for fname in (
            "fee_rate_entry",
            "fee_rate_exit",
            "expected_slippage",
            "partial_fill_fraction",
        ):
            _coerce_decimal(getattr(self, fname), fname)
        for fname in (
            "fee_rate_entry",
            "fee_rate_exit",
            "expected_slippage",
        ):
            _require_non_negative(Decimal(getattr(self, fname)), fname)
        _require_in_range(
            self.partial_fill_fraction,
            "partial_fill_fraction",
            Decimal("0"),
            Decimal("1"),
        )
        for fname in ("funding_treatment", "slippage_model", "spread_fill_assumptions"):
            value = getattr(self, fname)
            if not isinstance(value, str) or value == "":
                raise ValueError(f"{fname} must be a non-empty string")
        # Compute cost_model_hash if not provided; VERIFY it if provided
        # (CR-09): a non-empty hash copied from different cost assumptions
        # must fail closed, never silently poison experiment identity.
        expected_hash = sha256_hex({k: getattr(self, k) for k in COST_KEYS})
        if self.cost_model_hash == "":
            object.__setattr__(self, "cost_model_hash", expected_hash)
        elif self.cost_model_hash != expected_hash:
            raise ValueError(
                f"cost_model_hash mismatch: {self.cost_model_hash!r} != {expected_hash!r}"
            )


# --------------------------------------------------------------------------- #
# build_cost_model — read cost keys from a dict (fixture or ParameterSet).
# --------------------------------------------------------------------------- #


def build_cost_model(cost_dict: dict[str, Any]) -> CostModel:
    """Build a CostModel from a dict of cost keys.

    Absent keys raise KeyError (fail closed, never silent defaults).
    The dict may come from a loaded ParameterSet.params or directly
    from a fixture's `cost_model` field.
    """
    return CostModel(
        fee_rate_entry=_coerce_decimal(cost_dict["fee_rate_entry"], "fee_rate_entry"),
        fee_rate_exit=_coerce_decimal(cost_dict["fee_rate_exit"], "fee_rate_exit"),
        funding_treatment=str(cost_dict["funding_treatment"]),
        expected_slippage=_coerce_decimal(
            cost_dict["expected_slippage"], "expected_slippage"
        ),
        slippage_model=str(cost_dict["slippage_model"]),
        spread_fill_assumptions=str(cost_dict["spread_fill_assumptions"]),
        partial_fill_fraction=_coerce_decimal(
            cost_dict["partial_fill_fraction"], "partial_fill_fraction"
        ),
        cost_model_hash="",
    )


# --------------------------------------------------------------------------- #
# modeled_costs_per_unit — per-unit cost formula consumed by sizing.
# --------------------------------------------------------------------------- #


def modeled_costs_per_unit(
    *,
    cost_model: CostModel,
    side: str,
) -> Decimal:
    """Return the per-unit cost in quote currency.

    Per D-02: this is the same formula `src/risk/sizing.py` consumes
    via the `modeled_costs_per_unit` parameter. The simulator calls
    this function identically — never re-derives the math.

    Formula: `fee_rate_entry + fee_rate_exit + expected_slippage`
    (simplified for the tracer slice; funding treatment is ADDITIVE
    so it folds into the per-unit cost).
    """
    if side not in {"LONG", "SHORT"}:
        raise ValueError(f"side must be LONG or SHORT, got {side!r}")
    return _add(
        _add(cost_model.fee_rate_entry, cost_model.fee_rate_exit),
        cost_model.expected_slippage,
    )


__all__ = [
    "COST_KEYS",
    "CostModel",
    "build_cost_model",
    "modeled_costs_per_unit",
]
