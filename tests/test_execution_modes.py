"""Mode-branch protective sizing tests (Phase 9, plan 09-02).

Per D-02: protective parameters are mode-correct per EXECUTION_SPEC §5.
The one-way pattern (SL `closePosition=true`, TP1 `reduceOnly` + explicit
quantity, TP2 `closePosition=true`) is one branch; hedge mode carries
explicit `positionSide` with its own parameter constraints. Partial fills
are first-class: protective exits are sized against the actual filled
quantity (never the planned quantity).

The four behaviors pinned here:

  1. One-way full fill yields SL close-all, TP1 explicit qty with
     reduceOnly, TP2 close-all.
  2. One-way partial fill yields all legs sized to filled qty only.
  3. Hedge full fill yields all legs with positionSide and no reduceOnly.
  4. Sub-minimum filled qty returns a fail-closed protective-sizing
     rejection, never a rounded-up leg.

The tests load the golden fixture pairs
(`tests/fixtures/phase9/mode_branches/{one_way,hedge}/{input,expected}.json`)
and assert the protective leg parameters match the expected matrix
byte-for-byte.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

PHASE9_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase9"
MODE_BRANCHES_DIR = PHASE9_FIXTURES_DIR / "mode_branches"


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _load_input(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "input.json").read_text(encoding="utf-8"))


def _load_expected(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))


def _coerce_decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        return Decimal(value)
    if isinstance(value, int):
        return Decimal(value)
    raise TypeError(f"{field_name} must be Decimal/str/int, got {type(value).__name__}")


def _build_constraint_snapshot(case_input: dict[str, Any]) -> Any:
    from src.risk.types import ConstraintSnapshot

    cs = case_input["constraint_snapshot"]
    from datetime import datetime

    return ConstraintSnapshot(
        symbol=cs["symbol"],
        price_tick_size=_coerce_decimal(cs["price_tick_size"], "price_tick_size"),
        quantity_step_size=_coerce_decimal(cs["quantity_step_size"], "quantity_step_size"),
        min_quantity=_coerce_decimal(cs["min_quantity"], "min_quantity"),
        min_notional=_coerce_decimal(cs["min_notional"], "min_notional"),
        metadata_observed_at_utc=datetime.fromisoformat(cs["metadata_observed_at_utc"]),
    )


def _build_protective_template(case_input: dict[str, Any]) -> Any:
    from src.execution.placement import ProtectiveTemplate

    pt = case_input["protective_template"]
    return ProtectiveTemplate(
        stop_loss_trigger_price=_coerce_decimal(pt["stop_loss_trigger_price"], "stop_loss_trigger_price"),
        tp1_trigger_price=_coerce_decimal(pt["tp1_trigger_price"], "tp1_trigger_price"),
        tp2_trigger_price=_coerce_decimal(pt["tp2_trigger_price"], "tp2_trigger_price"),
        tp1_quantity_fraction=_coerce_decimal(pt["tp1_quantity_fraction"], "tp1_quantity_fraction"),
    )


# --------------------------------------------------------------------------- #
# Beh. 1 — one-way full fill: SL close-all, TP1 qty+reduceOnly, TP2 close-all.
# --------------------------------------------------------------------------- #


def test_one_way_full_fill_yields_close_all_sl_tp1_qty_reduce_only_tp2_close_all() -> None:
    """Beh. 1: a one-way full fill yields SL close-all, TP1 explicit qty
    with reduceOnly, TP2 close-all.
    """
    from src.execution.placement import size_protectives_to_filled_qty

    case_dir = MODE_BRANCHES_DIR / "one_way"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    filled_qty = _coerce_decimal(case_input["filled_quantity"], "filled_quantity")
    template = _build_protective_template(case_input)
    constraint = _build_constraint_snapshot(case_input)

    result = size_protectives_to_filled_qty(
        filled_quantity=filled_qty,
        protective_template=template,
        constraint_snapshot=constraint,
        position_mode=case_input["position_mode"],
        candidate_position_side=case_input["candidate_position_side"],
    )

    assert result.is_no_trade is False, f"expected PASS, got NO_TRADE: {result.reason_code}"
    assert result.reason_code == expected["reason_code"]

    # SL leg: close-all, no quantity, no reduceOnly.
    sl = result.sl_leg
    assert sl["side"] == expected["sl_leg"]["side"]
    assert sl["position_side"] == expected["sl_leg"]["position_side"]
    assert sl["algo_type"] == expected["sl_leg"]["algo_type"]
    assert sl["type"] == expected["sl_leg"]["type"]
    assert sl["trigger_price"] == _coerce_decimal(
        expected["sl_leg"]["trigger_price"], "sl_trigger_price"
    )
    assert sl["close_position"] is True
    assert sl["quantity"] is None
    assert sl["reduce_only"] is None

    # TP1 leg: explicit qty, reduceOnly True.
    tp1 = result.tp1_leg
    assert tp1["side"] == expected["tp1_leg"]["side"]
    assert tp1["position_side"] == expected["tp1_leg"]["position_side"]
    assert tp1["algo_type"] == expected["tp1_leg"]["algo_type"]
    assert tp1["type"] == expected["tp1_leg"]["type"]
    assert tp1["trigger_price"] == _coerce_decimal(
        expected["tp1_leg"]["trigger_price"], "tp1_trigger_price"
    )
    assert tp1["close_position"] is False
    assert tp1["quantity"] == _coerce_decimal(
        expected["tp1_leg"]["quantity"], "tp1_quantity"
    )
    assert tp1["reduce_only"] is True

    # TP2 leg: close-all, no quantity, no reduceOnly.
    tp2 = result.tp2_leg
    assert tp2["side"] == expected["tp2_leg"]["side"]
    assert tp2["position_side"] == expected["tp2_leg"]["position_side"]
    assert tp2["algo_type"] == expected["tp2_leg"]["algo_type"]
    assert tp2["type"] == expected["tp2_leg"]["type"]
    assert tp2["trigger_price"] == _coerce_decimal(
        expected["tp2_leg"]["trigger_price"], "tp2_trigger_price"
    )
    assert tp2["close_position"] is True
    assert tp2["quantity"] is None
    assert tp2["reduce_only"] is None


# --------------------------------------------------------------------------- #
# Beh. 2 — one-way partial fill: all legs sized to filled qty only.
# --------------------------------------------------------------------------- #


def test_one_way_partial_fill_sizes_all_legs_to_filled_qty() -> None:
    """Beh. 2: a one-way partial fill yields all legs sized to filled
    qty only (TP1 qty = filled_qty * tp1_fraction, remainder cancellable).
    """
    from src.execution.placement import size_protectives_to_filled_qty

    case_dir = MODE_BRANCHES_DIR / "one_way"
    case_input = _load_input(case_dir)
    template = _build_protective_template(case_input)
    constraint = _build_constraint_snapshot(case_input)

    # Use a partial fill: 0.300 instead of 0.500.
    partial_filled_qty = Decimal("0.300")

    result = size_protectives_to_filled_qty(
        filled_quantity=partial_filled_qty,
        protective_template=template,
        constraint_snapshot=constraint,
        position_mode="ONE_WAY",
        candidate_position_side="LONG",
    )

    assert result.is_no_trade is False, f"expected PASS, got NO_TRADE: {result.reason_code}"

    # TP1 qty = 0.300 * 0.5 = 0.150 (floored to stepSize 0.001).
    assert result.tp1_leg["quantity"] == Decimal("0.150")
    # SL and TP2 are close-all (no quantity).
    assert result.sl_leg["quantity"] is None
    assert result.tp2_leg["quantity"] is None
    # TP1 still has reduceOnly in one-way.
    assert result.tp1_leg["reduce_only"] is True


# --------------------------------------------------------------------------- #
# Beh. 3 — hedge full fill: positionSide, no reduceOnly, close-all forbidden.
# --------------------------------------------------------------------------- #


def test_hedge_full_fill_yields_position_side_no_reduce_only() -> None:
    """Beh. 3: a hedge full fill yields all legs with explicit
    positionSide and no reduceOnly. close-all legs carry quantity None.
    """
    from src.execution.placement import size_protectives_to_filled_qty

    case_dir = MODE_BRANCHES_DIR / "hedge"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    filled_qty = _coerce_decimal(case_input["filled_quantity"], "filled_quantity")
    template = _build_protective_template(case_input)
    constraint = _build_constraint_snapshot(case_input)

    result = size_protectives_to_filled_qty(
        filled_quantity=filled_qty,
        protective_template=template,
        constraint_snapshot=constraint,
        position_mode=case_input["position_mode"],
        candidate_position_side=case_input["candidate_position_side"],
    )

    assert result.is_no_trade is False, f"expected PASS, got NO_TRADE: {result.reason_code}"
    assert result.reason_code == expected["reason_code"]

    # SL leg: positionSide LONG, no reduceOnly, close-all.
    sl = result.sl_leg
    assert sl["position_side"] == expected["sl_leg"]["position_side"]
    assert sl["close_position"] is True
    assert sl["quantity"] is None
    assert sl["reduce_only"] is None

    # TP1 leg: positionSide LONG, no reduceOnly, explicit qty.
    tp1 = result.tp1_leg
    assert tp1["position_side"] == expected["tp1_leg"]["position_side"]
    assert tp1["close_position"] is False
    assert tp1["quantity"] == _coerce_decimal(
        expected["tp1_leg"]["quantity"], "tp1_quantity"
    )
    assert tp1["reduce_only"] is None  # NEVER reduceOnly in hedge.

    # TP2 leg: positionSide LONG, no reduceOnly, close-all.
    tp2 = result.tp2_leg
    assert tp2["position_side"] == expected["tp2_leg"]["position_side"]
    assert tp2["close_position"] is True
    assert tp2["quantity"] is None
    assert tp2["reduce_only"] is None


# --------------------------------------------------------------------------- #
# Beh. 4 — sub-minimum filled qty: fail-closed rejection, never rounded up.
# --------------------------------------------------------------------------- #


def test_sub_minimum_filled_qty_returns_fail_closed_rejection() -> None:
    """Beh. 4: a sub-minimum filled qty returns a fail-closed
    protective-sizing rejection, never a rounded-up leg.
    """
    from src.execution.placement import size_protectives_to_filled_qty

    case_dir = MODE_BRANCHES_DIR / "one_way"
    case_input = _load_input(case_dir)
    template = _build_protective_template(case_input)
    constraint = _build_constraint_snapshot(case_input)

    # Sub-minimum: 0.0005 < min_quantity 0.001.
    sub_min_qty = Decimal("0.0005")

    result = size_protectives_to_filled_qty(
        filled_quantity=sub_min_qty,
        protective_template=template,
        constraint_snapshot=constraint,
        position_mode="ONE_WAY",
        candidate_position_side="LONG",
    )

    assert result.is_no_trade is True
    assert result.reason_code == "MIN_QTY_REJECT"
    # No legs should be populated on a reject.
    assert result.sl_leg is None
    assert result.tp1_leg is None
    assert result.tp2_leg is None


# --------------------------------------------------------------------------- #
# Beh. 5 — purity: no float() in placement math.
# --------------------------------------------------------------------------- #


def test_placement_module_has_no_float_in_math() -> None:
    """Beh. 5: src/execution/placement.py does not use float() for
    placement math. Decimal-only per D-05.
    """
    import re
    from pathlib import Path

    module_path = Path("src/execution/placement.py")
    source = module_path.read_text(encoding="utf-8")
    match = re.search(r"\bfloat\s*\(", source)
    assert match is None, f"float() found in {module_path}: {match.group(0)!r}"


# --------------------------------------------------------------------------- #
# Beh. 6 — purity: no Binance SDK imports in placement module.
# --------------------------------------------------------------------------- #


def test_placement_module_does_not_import_binance_sdk() -> None:
    """Beh. 6: src/execution/placement.py does not import the Binance SDK."""
    import re
    from pathlib import Path

    module_path = Path("src/execution/placement.py")
    source = module_path.read_text(encoding="utf-8")
    forbidden_patterns = [
        r"\bimport\s+binance_sdk\b",
        r"\bfrom\s+binance_sdk\b",
    ]
    for pattern in forbidden_patterns:
        match = re.search(pattern, source)
        assert match is None, (
            f"forbidden import in {module_path}: pattern={pattern!r}, match={match.group(0)!r}"
        )
