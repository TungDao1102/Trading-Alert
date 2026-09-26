"""Tests for the Phase 6 experiment registry (plan 06-02).

Per D-03 + BACKTEST_SPEC §11 + RESEARCH_PROTOCOL §5: every experiment
record carries the canonical six-field identity tuple
(`experimentId`, `strategyVersion`, `parameterSetHash` + runtime
`parameterSetId` alongside, `dataSnapshotId`, `codeVersion`,
`costModelHash`) plus dataset range, symbol universe, timeframe, full
parameters, cost assumptions, results, and notes. A record missing any
field fails the acceptance gate.

TDD discipline: RED → GREEN. These tests are the RED phase — they MUST
fail until `src/backtest/experiment.py` is implemented.
"""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from src.domain.canonical import sha256_hex
from src.domain.registry import UnregisteredParameterSet

PHASE6_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase6"


# --------------------------------------------------------------------------- #
# Helpers — load input/expected pair from a phase6 case directory.
# --------------------------------------------------------------------------- #


def _load_input(case_dir: Path) -> dict:
    return json.loads((case_dir / "input.json").read_text(encoding="utf-8"))


def _load_expected(case_dir: Path) -> dict:
    return json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))


def _build_cost_model(cost_dict: dict):
    """Build a CostModel from a dict (delegates to costs.build_cost_model)."""
    from src.backtest.costs import build_cost_model

    return build_cost_model(cost_dict)


# --------------------------------------------------------------------------- #
# Test 1 — assemble with complete inputs returns stable 64-hex identity.
# --------------------------------------------------------------------------- #


def test_experiment_assemble_stable_64_hex_identity() -> None:
    """Beh. 1: assemble with complete inputs returns ExperimentRecord with
    six 64-hex identity fields and a stable experiment_id across reruns.

    Per D-03: every experiment record carries the canonical six-field
    identity tuple. All hash fields must be 64-hex strings; the
    experiment_id must be stable across reruns.
    """
    from src.backtest.experiment import assemble

    case_dir = PHASE6_FIXTURES_DIR / "registry_identity"
    case_input = _load_input(case_dir)
    cost_model = _build_cost_model(case_input["cost_model"])

    record_a = assemble(
        parameter_set_id=case_input["parameter_set_id"],
        strategy_id=case_input["strategy_id"],
        strategy_version=case_input["strategy_version"],
        data_snapshot_id=case_input["data_snapshot_id"],
        code_version=case_input["code_version"],
        cost_model=cost_model,
        time_range_start_utc=datetime.fromisoformat(
            case_input["time_range_start_utc"]
        ),
        time_range_end_utc=datetime.fromisoformat(case_input["time_range_end_utc"]),
        universe=case_input["universe"],
        run_type=case_input["run_type"],
        notes=case_input["notes"],
    )
    record_b = assemble(
        parameter_set_id=case_input["parameter_set_id"],
        strategy_id=case_input["strategy_id"],
        strategy_version=case_input["strategy_version"],
        data_snapshot_id=case_input["data_snapshot_id"],
        code_version=case_input["code_version"],
        cost_model=cost_model,
        time_range_start_utc=datetime.fromisoformat(
            case_input["time_range_start_utc"]
        ),
        time_range_end_utc=datetime.fromisoformat(case_input["time_range_end_utc"]),
        universe=case_input["universe"],
        run_type=case_input["run_type"],
        notes=case_input["notes"],
    )

    # All six identity fields must be 64-hex strings.
    for field in (
        "experiment_id",
        "parameter_set_hash",
        "data_snapshot_id",
        "cost_model_hash",
    ):
        value = getattr(record_a, field)
        assert isinstance(value, str), f"{field} must be str, got {type(value).__name__}"
        assert len(value) == 64, f"{field} must be 64-hex, got len={len(value)}"
        assert all(c in "0123456789abcdef" for c in value), (
            f"{field} must be lowercase hex, got {value!r}"
        )

    # experiment_id must be stable across reruns.
    assert record_a.experiment_id == record_b.experiment_id, (
        "experiment_id must be stable across reruns"
    )


# --------------------------------------------------------------------------- #
# Test 2 — assemble with missing identity field raises IncompleteExperimentRecord.
# --------------------------------------------------------------------------- #


def test_experiment_assemble_missing_field_raises() -> None:
    """Beh. 2: assemble with any missing identity field raises
    IncompleteExperimentRecord (D-03 acceptance gate).

    Per D-03: a record missing any field fails the acceptance gate.
    """
    from src.backtest.experiment import IncompleteExperimentRecord, assemble

    case_dir = PHASE6_FIXTURES_DIR / "registry_identity"
    case_input = _load_input(case_dir)
    cost_model = _build_cost_model(case_input["cost_model"])

    # Missing data_snapshot_id.
    with pytest.raises(IncompleteExperimentRecord):
        assemble(
            parameter_set_id=case_input["parameter_set_id"],
            strategy_id=case_input["strategy_id"],
            strategy_version=case_input["strategy_version"],
            data_snapshot_id="",
            code_version=case_input["code_version"],
            cost_model=cost_model,
            time_range_start_utc=datetime.fromisoformat(
                case_input["time_range_start_utc"]
            ),
            time_range_end_utc=datetime.fromisoformat(
                case_input["time_range_end_utc"]
            ),
            universe=case_input["universe"],
            run_type=case_input["run_type"],
            notes=case_input["notes"],
        )


# --------------------------------------------------------------------------- #
# Test 3 — reproduce with the recorded tuple returns byte-identical trades.
# --------------------------------------------------------------------------- #


def test_experiment_reproduce_byte_identical() -> None:
    """Beh. 3: reproduce with the recorded tuple returns byte-identical
    trade lists via canonical sha256 comparison (D-03 reproducibility).

    Per D-03: reproduction = re-running the recorded six-field tuple
    yields byte-identical trade lists.
    """
    from src.backtest.experiment import assemble, reproduce

    case_dir = PHASE6_FIXTURES_DIR / "registry_identity"
    case_input = _load_input(case_dir)
    cost_model = _build_cost_model(case_input["cost_model"])

    record = assemble(
        parameter_set_id=case_input["parameter_set_id"],
        strategy_id=case_input["strategy_id"],
        strategy_version=case_input["strategy_version"],
        data_snapshot_id=case_input["data_snapshot_id"],
        code_version=case_input["code_version"],
        cost_model=cost_model,
        time_range_start_utc=datetime.fromisoformat(
            case_input["time_range_start_utc"]
        ),
        time_range_end_utc=datetime.fromisoformat(case_input["time_range_end_utc"]),
        universe=case_input["universe"],
        run_type=case_input["run_type"],
        notes=case_input["notes"],
    )

    # Reproduce twice — both runs must yield byte-identical trade lists.
    trades_a = reproduce(record, simulator_inputs={})
    trades_b = reproduce(record, simulator_inputs={})
    digest_a = sha256_hex({"trades": [t.to_dict() for t in trades_a]})
    digest_b = sha256_hex({"trades": [t.to_dict() for t in trades_b]})
    assert digest_a == digest_b, (
        f"reproduce digests differ: {digest_a} != {digest_b}"
    )


# --------------------------------------------------------------------------- #
# Test 4 — unregistered parameterSetId raises UnregisteredParameterSet.
# --------------------------------------------------------------------------- #


def test_experiment_unregistered_set_fails_closed() -> None:
    """Beh. 4: assemble with an unregistered parameterSetId raises
    UnregisteredParameterSet (Phase-1 D-07, Phase-3 D-05).

    Per D-03: any run without a registered parameterSetId + matching
    hash fails closed.
    """
    from src.backtest.experiment import assemble

    case_dir = PHASE6_FIXTURES_DIR / "registry_identity"
    case_input = _load_input(case_dir)
    cost_model = _build_cost_model(case_input["cost_model"])

    with pytest.raises(UnregisteredParameterSet):
        assemble(
            parameter_set_id="does-not-exist",
            strategy_id=case_input["strategy_id"],
            strategy_version=case_input["strategy_version"],
            data_snapshot_id=case_input["data_snapshot_id"],
            code_version=case_input["code_version"],
            cost_model=cost_model,
            time_range_start_utc=datetime.fromisoformat(
                case_input["time_range_start_utc"]
            ),
            time_range_end_utc=datetime.fromisoformat(
                case_input["time_range_end_utc"]
            ),
            universe=case_input["universe"],
            run_type=case_input["run_type"],
            notes=case_input["notes"],
        )


# --------------------------------------------------------------------------- #
# Test 5 — baseline_no_trade returns an empty trade list.
# --------------------------------------------------------------------------- #


def test_baseline_no_trade_returns_empty_trades() -> None:
    """Beh. 5: baseline_no_trade over the fixture returns an empty
    trade list (minimum_rr=100 forces every plan to fail the RR gate).

    Per BACKTEST_SPEC §9: every candidate is compared against declared
    baselines (no-trade + simple-trend at minimum). The no-trade
    baseline degenerates minimum_rr so no filled trades occur.
    """
    from src.backtest.experiment import baseline_no_trade

    case_dir = PHASE6_FIXTURES_DIR / "baselines" / "no_trade"
    case_input = _load_input(case_dir)
    trades = baseline_no_trade(case_input)
    assert len(trades) == 0, (
        f"baseline_no_trade must return empty trade list, got {len(trades)} trades"
    )


# --------------------------------------------------------------------------- #
# Test 6 — baseline_simple_trend returns a single-direction trade list.
# --------------------------------------------------------------------------- #


def test_baseline_simple_trend_returns_single_direction() -> None:
    """Beh. 6: baseline_simple_trend over the fixture returns a
    deterministic single-direction trade list (looser minimum_rr +
    single-condition trend filter).

    Per BACKTEST_SPEC §9: the simple-trend baseline uses a single-
    condition trend filter so the simulator emits a deterministic
    single-direction trade list.
    """
    from src.backtest.experiment import baseline_simple_trend

    case_dir = PHASE6_FIXTURES_DIR / "baselines" / "simple_trend"
    case_input = _load_input(case_dir)
    trades = baseline_simple_trend(case_input)
    assert len(trades) >= 1, (
        f"baseline_simple_trend must return at least 1 trade, got {len(trades)}"
    )
    # All trades must be the same direction (single-direction).
    directions = {t.direction for t in trades}
    assert len(directions) == 1, (
        f"baseline_simple_trend must be single-direction, got directions={directions}"
    )


# --------------------------------------------------------------------------- #
# Test 7 — costModelHash differs between fee_rate_entry 0.00020 vs 0.0002.
# --------------------------------------------------------------------------- #


def test_cost_model_hash_precision_discipline() -> None:
    """Beh. 7: costModelHash differs between fee_rate_entry 0.00020 vs
    0.0002 (trailing-precision discipline, D-12).

    Per D-12: Decimal → str() preserving full precision. Decimal("0.00020")
    stays "0.00020", never "0.0002". This is documented design — trailing
    precision is semantically meaningful for exchange-sensitive values.
    """
    from src.backtest.costs import build_cost_model

    cost_a = build_cost_model(
        {
            "fee_rate_entry": "0.00020",
            "fee_rate_exit": "0.0005",
            "funding_treatment": "ADDITIVE",
            "expected_slippage": "0.0001",
            "slippage_model": "FIXED_BPS",
            "spread_fill_assumptions": "FULL_FILL",
            "partial_fill_fraction": "1.0",
        }
    )
    cost_b = build_cost_model(
        {
            "fee_rate_entry": "0.0002",
            "fee_rate_exit": "0.0005",
            "funding_treatment": "ADDITIVE",
            "expected_slippage": "0.0001",
            "slippage_model": "FIXED_BPS",
            "spread_fill_assumptions": "FULL_FILL",
            "partial_fill_fraction": "1.0",
        }
    )
    assert cost_a.cost_model_hash != cost_b.cost_model_hash, (
        "costModelHash must differ between fee_rate_entry 0.00020 vs 0.0002"
    )


# --------------------------------------------------------------------------- #
# Test 8 — verify_experiment returns None when reproducible.
# --------------------------------------------------------------------------- #


def test_verify_experiment_returns_none_when_reproducible() -> None:
    """Beh. 8: verify_experiment returns None when the recorded tuple
    reproduces byte-identically; raises ExperimentReproducibilityBroken
    on drift.

    Per D-03: verify_experiment is the runtime tripwire for
    reproducibility.
    """
    from src.backtest.experiment import assemble, verify_experiment

    case_dir = PHASE6_FIXTURES_DIR / "registry_identity"
    case_input = _load_input(case_dir)
    cost_model = _build_cost_model(case_input["cost_model"])

    record = assemble(
        parameter_set_id=case_input["parameter_set_id"],
        strategy_id=case_input["strategy_id"],
        strategy_version=case_input["strategy_version"],
        data_snapshot_id=case_input["data_snapshot_id"],
        code_version=case_input["code_version"],
        cost_model=cost_model,
        time_range_start_utc=datetime.fromisoformat(
            case_input["time_range_start_utc"]
        ),
        time_range_end_utc=datetime.fromisoformat(case_input["time_range_end_utc"]),
        universe=case_input["universe"],
        run_type=case_input["run_type"],
        notes=case_input["notes"],
    )

    # verify_experiment must return None when reproducible.
    result = verify_experiment(record, simulator_inputs={})
    assert result is None, (
        f"verify_experiment must return None when reproducible, got {result!r}"
    )
