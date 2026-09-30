"""Pure cost model — frozen dataclass + hash + per-unit formula (Phase 6, plan 06-01).

Per D-02: costs apply from run #1 before any selection decision. The
`CostModel` is a frozen dataclass built from registry cost keys, with
`cost_model_hash` computed via `sha256_hex` over the sorted seven-key
snapshot (eight keys when the model carries `exit_slippage_rate`, Phase 12),
with numeric values hashed as canonical text so equivalent spellings agree
(D-15). `modeled_costs_per_unit` is price-aware (quote currency per unit of
base) and delegates to `src/risk/cost_rates.per_unit_round_trip_cost`, the one
producer `evaluate_risk` also uses — never re-derived inside the simulator
body. `guard_rates_from_params` reads the two cost-guard rates from the
pinned registry set for both the simulator and the paper loop.

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 / Phase-5 D-05 purity precedent.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.domain.canonical import sha256_hex
from src.risk.cost_guards import validate_guard_rates
from src.risk.cost_rates import (
    FEE_SOURCE_PARAMETER,
    MAX_RATE,
    CostRates,
    per_unit_round_trip_cost,
)

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

# Optional cost keys participate in cost identity by PRESENCE (D-14 option B):
# a set that carries one hashes over the seven required keys plus this one; a
# set that does not (every legacy set) keeps its byte-locked seven-key hash.
OPTIONAL_COST_KEYS: tuple[str, ...] = ("exit_slippage_rate",)


# Numeric cost fields hashed as canonical text (D-15); the rest are strings.
_NUMERIC_HASH_KEYS: frozenset[str] = frozenset(
    {
        "fee_rate_entry",
        "fee_rate_exit",
        "expected_slippage",
        "partial_fill_fraction",
        "exit_slippage_rate",
    }
)


def _canonical_decimal_text(value: Decimal) -> str:
    """Render a Decimal as one plain (non-exponent) text form (D-15).

    Zero, in any spelling including negative zero, renders as "0". Every
    other value renders as its plain positional text with trailing zeros
    removed, so 1, 1.0 and Decimal("1.00") all render "1", 0.00020 renders
    "0.0002", and 100 stays "100" (never "1E+2"). Built from the digit tuple
    so it does not depend on the ambient Decimal context precision.
    """
    if not value.is_finite():
        raise ValueError(f"cost value must be finite, got {value}")
    if value == 0:
        return "0"
    sign, digits, exponent = value.as_tuple()
    assert isinstance(exponent, int)  # finite Decimal
    mantissa = list(digits)
    while len(mantissa) > 1 and mantissa[-1] == 0:
        mantissa.pop()
        exponent += 1
    return format(Decimal((sign, tuple(mantissa), exponent)), "f")


def _cost_hash_payload(model: CostModel) -> dict[str, str]:
    """Build the hash payload: canonical text for numerics, strings as-is.

    The seven `COST_KEYS` always participate; `exit_slippage_rate`
    participates only when the model carries it (presence-driven, D-14
    option B), so every legacy seven-key model keeps its byte-locked hash.
    """
    keys = (
        (*COST_KEYS, *OPTIONAL_COST_KEYS)
        if model.exit_slippage_rate is not None
        else COST_KEYS
    )
    payload: dict[str, str] = {}
    for key in keys:
        value = getattr(model, key)
        payload[key] = (
            _canonical_decimal_text(value) if key in _NUMERIC_HASH_KEYS else value
        )
    return payload


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


def _require_cost_str(value: object, field_name: str) -> str:
    """Require a non-empty string for string-valued cost keys (WR-02).

    Fail-closed at the boundary: mistyped fixture/caller values such as
    ``None`` or ``123`` raise ``TypeError`` here instead of being silently
    coerced via ``str(...)`` into ``"None"``/``"123"`` and surfacing
    downstream as a hash mismatch.
    """
    if not isinstance(value, str) or value == "":
        raise TypeError(f"{field_name} must be a non-empty string, got {value!r}")
    return value


# --------------------------------------------------------------------------- #
# CostModel — frozen value object with computed cost_model_hash.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CostModel:
    """Registry-parameterized cost model (D-02).

    `cost_model_hash` is SHA256 over the canonical JSON of the sorted
    seven-key snapshot, plus `exit_slippage_rate` when present. Numeric
    values enter the hash as canonical text (equivalent spellings agree,
    D-15). Once referenced by an experiment, the hash is permanent (D-03).
    """

    fee_rate_entry: Decimal
    fee_rate_exit: Decimal
    funding_treatment: str
    expected_slippage: Decimal
    slippage_model: str
    spread_fill_assumptions: str
    partial_fill_fraction: Decimal
    cost_model_hash: str
    # Optional stop-exit slippage rate (Phase 12, D-14 option B). Trailing and
    # defaulted so existing keyword and positional construction keeps working.
    # None marks a legacy 7-key model: constructible and hashable, but refused
    # by `cost_rates_from_model` (it cannot size).
    exit_slippage_rate: Decimal | None = None

    def __post_init__(self) -> None:
        for fname in (
            "fee_rate_entry",
            "fee_rate_exit",
            "expected_slippage",
            "partial_fill_fraction",
        ):
            object.__setattr__(self, fname, _coerce_decimal(getattr(self, fname), fname))
        if self.exit_slippage_rate is not None:
            object.__setattr__(
                self,
                "exit_slippage_rate",
                _coerce_decimal(self.exit_slippage_rate, "exit_slippage_rate"),
            )
        for fname in (
            "fee_rate_entry",
            "fee_rate_exit",
            "expected_slippage",
        ):
            _require_non_negative(Decimal(getattr(self, fname)), fname)
            _require_in_range(Decimal(getattr(self, fname)), fname, Decimal("0"), MAX_RATE)
        if self.exit_slippage_rate is not None:
            _require_non_negative(self.exit_slippage_rate, "exit_slippage_rate")
            _require_in_range(
                self.exit_slippage_rate, "exit_slippage_rate", Decimal("0"), MAX_RATE
            )
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
        expected_hash = sha256_hex(_cost_hash_payload(self))
        if self.cost_model_hash == "":
            object.__setattr__(self, "cost_model_hash", expected_hash)
        elif self.cost_model_hash != expected_hash:
            raise ValueError(
                f"cost_model_hash mismatch: {self.cost_model_hash!r} != {expected_hash!r}"
            )


# --------------------------------------------------------------------------- #
# build_cost_model — read cost keys from a dict (fixture or ParameterSet).
# --------------------------------------------------------------------------- #


def cost_slice(params: Mapping[str, Any]) -> dict[str, Any]:
    """Slice the cost keys out of a registry parameter mapping.

    Returns the seven required `COST_KEYS` plus `exit_slippage_rate` when the
    set carries it (Phase 12 sets do; every legacy set does not). A set
    missing a required key raises a bare `KeyError` (fail closed, never
    defaulted): baseline-v1 and baseline-v2 take that path. This is the one
    slice builder shared by the binding gate and the paper freeze so the
    registry side of the cost binding is built in exactly one place.
    """
    sliced: dict[str, Any] = {k: params[k] for k in COST_KEYS}
    for key in OPTIONAL_COST_KEYS:
        if key in params:
            sliced[key] = params[key]
    return sliced


def build_cost_model(cost_dict: dict[str, Any]) -> CostModel:
    """Build a CostModel from a dict of cost keys.

    Absent keys raise KeyError (fail closed, never silent defaults).
    The dict may come from a loaded ParameterSet.params or directly
    from a fixture's `cost_model` field.
    """
    exit_slippage_rate = (
        _coerce_decimal(cost_dict["exit_slippage_rate"], "exit_slippage_rate")
        if "exit_slippage_rate" in cost_dict
        else None
    )
    return CostModel(
        fee_rate_entry=_coerce_decimal(cost_dict["fee_rate_entry"], "fee_rate_entry"),
        fee_rate_exit=_coerce_decimal(cost_dict["fee_rate_exit"], "fee_rate_exit"),
        funding_treatment=_require_cost_str(
            cost_dict["funding_treatment"], "funding_treatment"
        ),
        expected_slippage=_coerce_decimal(
            cost_dict["expected_slippage"], "expected_slippage"
        ),
        slippage_model=_require_cost_str(
            cost_dict["slippage_model"], "slippage_model"
        ),
        spread_fill_assumptions=_require_cost_str(
            cost_dict["spread_fill_assumptions"], "spread_fill_assumptions"
        ),
        partial_fill_fraction=_coerce_decimal(
            cost_dict["partial_fill_fraction"], "partial_fill_fraction"
        ),
        cost_model_hash="",
        exit_slippage_rate=exit_slippage_rate,
    )


def cost_rates_from_model(cost_model: CostModel) -> CostRates:
    """Map a CostModel to the four-rate `CostRates` the cost producer consumes.

    `entry_slippage_rate` is the model's `expected_slippage`. A model without
    `exit_slippage_rate` is a legacy 7-key model: refused (fail closed) and
    never defaulted to `expected_slippage`, because sizing on a silently
    assumed stop-exit slippage would under- or over-state the risk (T-12-07).
    """
    if cost_model.exit_slippage_rate is None:
        raise ValueError(
            "exit_slippage_rate is missing: legacy 7-key cost models cannot size; "
            "use a registry set that carries exit_slippage_rate (baseline-v5 or later)"
        )
    return CostRates(
        fee_rate_entry=cost_model.fee_rate_entry,
        entry_slippage_rate=cost_model.expected_slippage,
        fee_rate_exit=cost_model.fee_rate_exit,
        exit_slippage_rate=cost_model.exit_slippage_rate,
        fee_source=FEE_SOURCE_PARAMETER,
    )


GUARD_RATE_KEYS: tuple[str, str] = ("min_stop_distance_rate", "max_cost_to_risk")


def guard_rates_from_params(params: Mapping[str, Any]) -> tuple[Decimal, Decimal]:
    """Read the two cost-guard rates from a registry parameter mapping.

    Returns `(min_stop_distance_rate, max_cost_to_risk)` as Decimals, in the
    order `evaluate_risk` takes them. The simulator and the paper loop both
    call this one helper so the guard values reach the risk pipeline from the
    pinned registry set identically (D-19). A legacy set that predates the
    guards (baseline-v4 and earlier) raises `ValueError` naming the missing
    key; the guards are never defaulted (fail closed, T-12-19).

    Each value must be a `Decimal` or `int` (never bool, float or str, 12-REVIEW
    WR-05) and the pair is range-checked through `validate_guard_rates`, so a
    bad value fails here with `TypeError` / `ValueError` rather than deep in
    the risk gate.
    """
    values: list[Decimal] = []
    for key in GUARD_RATE_KEYS:
        if key not in params:
            raise ValueError(
                f"{key} is missing from the parameter set: legacy sets cannot "
                "size without the cost guards; use a registry set that carries "
                "them (baseline-v5 or later)"
            )
        raw = params[key]
        if isinstance(raw, bool) or not isinstance(raw, (Decimal, int)):
            raise TypeError(f"{key} must be Decimal or int, got {type(raw).__name__}")
        values.append(Decimal(raw))
    min_stop_distance_rate, max_cost_to_risk = values[0], values[1]
    validate_guard_rates(
        min_stop_distance_rate=min_stop_distance_rate,
        max_cost_to_risk=max_cost_to_risk,
    )
    return min_stop_distance_rate, max_cost_to_risk


# --------------------------------------------------------------------------- #
# modeled_costs_per_unit — per-unit cost formula consumed by sizing.
# --------------------------------------------------------------------------- #


def modeled_costs_per_unit(
    *,
    cost_model: CostModel,
    side: str,
    entry_price: Decimal,
    stop_price: Decimal,
) -> Decimal:
    """Return the modeled round-trip cost in QUOTE CURRENCY PER ONE UNIT of base.

    Formula: `entry_price * (fee_rate_entry + expected_slippage)
    + stop_price * (fee_rate_exit + exit_slippage_rate)`. This is the same
    function `evaluate_risk` uses internally (`per_unit_round_trip_cost` over
    `cost_rates_from_model(cost_model)`); the simulator record's
    `modeled_costs_per_unit` is the value sizing produced, and this helper
    reproduces it from explicit prices. The old form returned the dimensionless
    rate sum, which is not a quote amount (F-001, F-801).

    Args:
        cost_model: an 8-key model carrying `exit_slippage_rate`.
        side: "LONG" or "SHORT".
        entry_price: the sizing entry price (the adverse zone edge), > 0.
        stop_price: the stop trigger price, > 0.

    Raises:
        ValueError: `side` is not LONG/SHORT, a price is <= 0, or the model is
            a legacy 7-key model without `exit_slippage_rate`.
    """
    if side not in {"LONG", "SHORT"}:
        raise ValueError(f"side must be LONG or SHORT, got {side!r}")
    return per_unit_round_trip_cost(
        side=side,
        entry_price=entry_price,
        stop_price=stop_price,
        rates=cost_rates_from_model(cost_model),
    )


__all__ = [
    "COST_KEYS",
    "OPTIONAL_COST_KEYS",
    "CostModel",
    "build_cost_model",
    "cost_rates_from_model",
    "cost_slice",
    "guard_rates_from_params",
    "modeled_costs_per_unit",
]
