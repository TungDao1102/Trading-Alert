"""Parity-fixture tests for the Phase-5 risk pipeline (plan 05-01).

Per D-02: identical inputs run through `size_position` then `quantize`
produce byte-identical SizedResult outputs (including reason codes).
The CI-blocking parity fixture pins the byte-identical guarantee so
backtest, paper, and live modes share identical math.

TDD discipline: RED → GREEN. These tests are the RED phase — they MUST
fail until `src/risk/sizing.py` and `src/risk/quantization.py` are
implemented.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from src.core.types import AccountState
from src.domain.canonical import sha256_hex
from src.domain.enums import TradePlanStatus
from src.domain.trade_plan import TradePlan
from src.risk.quantization import quantize
from src.risk.sizing import size_position
from src.risk.types import ConstraintSnapshot, SizedResult

PHASE5_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase5"


# --------------------------------------------------------------------------- #
# Helpers — load input/expected pair from a phase5 case directory.
# --------------------------------------------------------------------------- #


def _load_input(case_dir: Path) -> dict:
    return json.loads((case_dir / "input.json").read_text(encoding="utf-8"))


def _load_expected(case_dir: Path) -> dict:
    return json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))


def _build_trade_plan(tp_dict: dict) -> TradePlan:
    """Build a TradePlan from a JSON-decoded dict."""
    return TradePlan(
        trade_plan_id=tp_dict["trade_plan_id"],
        signal_id=tp_dict["signal_id"],
        trade_plan_version=tp_dict["trade_plan_version"],
        entry_model=tp_dict["entry_model"],
        entry_min_price=Decimal(tp_dict["entry_min_price"]),
        entry_max_price=Decimal(tp_dict["entry_max_price"]),
        stop_loss_price=Decimal(tp_dict["stop_loss_price"]),
        take_profit_json=tp_dict["take_profit_json"],
        invalidation_rule_json=tp_dict["invalidation_rule_json"],
        expiry_utc=datetime.fromisoformat(tp_dict["expiry_utc"]),
        expected_rr_json=tp_dict["expected_rr_json"],
        risk_rate=Decimal(tp_dict["risk_rate"]),
        risk_budget=Decimal(tp_dict["risk_budget"]),
        suggested_quantity=Decimal(tp_dict["suggested_quantity"]),
        quantity_before_rounding=Decimal(tp_dict["quantity_before_rounding"]),
        quantity_after_rounding=Decimal(tp_dict["quantity_after_rounding"]),
        quantization_decision=tp_dict["quantization_decision"],
        plan_hash=tp_dict["plan_hash"],
        status=TradePlanStatus(tp_dict["status"]),
        created_at_utc=datetime.fromisoformat(tp_dict["created_at_utc"]),
    )


def _build_account_state(as_dict: dict) -> AccountState:
    return AccountState(
        equity=Decimal(as_dict["equity"]),
        risk_rate=Decimal(as_dict["risk_rate"]),
    )


def _build_constraints(cs_dict: dict) -> ConstraintSnapshot:
    return ConstraintSnapshot(
        symbol=cs_dict["symbol"],
        price_tick_size=Decimal(cs_dict["price_tick_size"]),
        quantity_step_size=Decimal(cs_dict["quantity_step_size"]),
        min_quantity=Decimal(cs_dict["min_quantity"]),
        min_notional=Decimal(cs_dict["min_notional"]),
        metadata_observed_at_utc=datetime.fromisoformat(cs_dict["metadata_observed_at_utc"]),
    )


def _run_pipeline(case_input: dict) -> SizedResult:
    """Run size_position + quantize on a phase5 case input."""
    trade_plan = _build_trade_plan(case_input["trade_plan"])
    account = _build_account_state(case_input["account_state"])
    constraints = _build_constraints(case_input["constraint_snapshot"])

    # Zone-mid entry_ref = (entry_min + entry_max) / 2
    entry_ref = (trade_plan.entry_min_price + trade_plan.entry_max_price) / Decimal("2")
    modeled_costs = Decimal(str(case_input["modeled_costs_per_unit"]))

    sized = size_position(
        trade_plan=trade_plan,
        account_state=account,
        entry_ref=entry_ref,
        modeled_costs_per_unit=modeled_costs,
    )

    allowed_risk = account.equity * account.risk_rate
    sl_distance = abs(entry_ref - trade_plan.stop_loss_price)
    risk_per_unit = sl_distance + modeled_costs

    return quantize(
        sized=sized,
        constraint_snapshot=constraints,
        allowed_risk=allowed_risk,
        risk_per_unit=risk_per_unit,
        minimum_risk_utilization_after_rounding=Decimal("0.6"),
        reference_price=entry_ref,
    )


def _to_parity_dict(result: SizedResult) -> dict:
    """Project SizedResult to a parity-fixture-shaped dict (canonical-JSON-safe)."""
    return {
        "is_no_trade": result.is_no_trade,
        "quantity": None if result.quantity is None else str(result.quantity),
        "quantity_before_rounding": str(result.quantity_before_rounding),
        "quantity_after_rounding": str(result.quantity_after_rounding),
        "quantization_decision": result.quantization_decision,
        "realized_risk": str(result.realized_risk),
        "reason_code": result.reason_code,
    }


# --------------------------------------------------------------------------- #
# Test 1 — same input run twice yields canonical-JSON-identical output dict.
# --------------------------------------------------------------------------- #


def test_risk_pipeline_byte_identical_across_runs() -> None:
    """Beh. 2: identical input → byte-identical SizedResult (incl. reason code)."""
    case_dir = PHASE5_FIXTURES_DIR / "happy_path_long"
    case_input = _load_input(case_dir)

    a = _run_pipeline(case_input)
    b = _run_pipeline(case_input)

    # Same fields ⇒ same canonical-JSON hash.
    assert sha256_hex(_to_parity_dict(a)) == sha256_hex(_to_parity_dict(b))
    # Reason code parity too.
    assert a.reason_code == b.reason_code
    assert a.is_no_trade == b.is_no_trade


# --------------------------------------------------------------------------- #
# Test 2 — every phase5 case directory has matching input/expected files.
# --------------------------------------------------------------------------- #


def test_phase5_fixtures_exist() -> None:
    """Beh. 3: each case directory under phase5/ contains input.json + expected.json."""
    assert PHASE5_FIXTURES_DIR.is_dir(), f"missing phase5 fixtures dir: {PHASE5_FIXTURES_DIR}"
    expected_cases = {
        "happy_path_long",
        "happy_path_short",
        "utilization_reject_edge",
        "min_qty_reject",
        "notional_reject",
    }
    actual_cases = {p.name for p in PHASE5_FIXTURES_DIR.iterdir() if p.is_dir()}
    assert expected_cases.issubset(actual_cases), (
        f"missing phase5 cases: {expected_cases - actual_cases}"
    )


# --------------------------------------------------------------------------- #
# Test 3 — parametrize over all phase5 cases; pipeline output matches expected.
# --------------------------------------------------------------------------- #


_PHASE5_CASES = (
    "happy_path_long",
    "happy_path_short",
    "utilization_reject_edge",
    "min_qty_reject",
    "notional_reject",
)


@pytest.mark.parametrize("case_name", _PHASE5_CASES)
def test_phase5_pipeline_matches_expected(case_name: str) -> None:
    """Beh. 4: pipeline output dict matches expected.json canonical-JSON-exactly."""
    case_dir = PHASE5_FIXTURES_DIR / case_name
    case_input = _load_input(case_dir)
    case_expected = _load_expected(case_dir)

    result = _run_pipeline(case_input)
    actual = _to_parity_dict(result)
    assert sha256_hex(actual) == sha256_hex(case_expected), (
        f"parity mismatch in {case_name}: actual={actual}, expected={case_expected}"
    )
