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


def _v3_case_input(case_dir: Path) -> dict:
    """Load a phase6 fixture and rebind it to the v3 registry set.

    Per Phase 7.1 D-05: phase6 fixtures stay byte-identical (NOT
    regenerated), but tests that call assemble() must migrate to a
    7-key registry set. baseline-v3 ships all 7 COST_KEYS; baseline-v2
    only has 3 and now raises KeyError at the gate (correct behavior).
    The cost_model dict is also rebinding partial_fill_fraction from
    "1.0" (phase6 spelling) to "0.5" (v3 TOML spelling) so the
    registry slice and the fixture dict hash identically.
    """
    case: dict = _load_input(case_dir)
    case["parameter_set_id"] = "baseline-v3"
    cost_model: dict = dict(case["cost_model"])
    cost_model["partial_fill_fraction"] = "0.5"
    case["cost_model"] = cost_model
    return case


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
    case_input = _v3_case_input(case_dir)
    cost_model = _build_cost_model(case_input["cost_model"])

    record_a = assemble(
        parameter_set_id=case_input["parameter_set_id"],
        strategy_id=case_input["strategy_id"],
        strategy_version=case_input["strategy_version"],
        data_snapshot_id=case_input["data_snapshot_id"],
        code_version=case_input["code_version"],
        cost_model=cost_model,
        time_range_start_utc=datetime.fromisoformat(case_input["time_range_start_utc"]),
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
        time_range_start_utc=datetime.fromisoformat(case_input["time_range_start_utc"]),
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
    case_input = _v3_case_input(case_dir)
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
            time_range_start_utc=datetime.fromisoformat(case_input["time_range_start_utc"]),
            time_range_end_utc=datetime.fromisoformat(case_input["time_range_end_utc"]),
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
    case_input = _v3_case_input(case_dir)
    cost_model = _build_cost_model(case_input["cost_model"])

    record = assemble(
        parameter_set_id=case_input["parameter_set_id"],
        strategy_id=case_input["strategy_id"],
        strategy_version=case_input["strategy_version"],
        data_snapshot_id=case_input["data_snapshot_id"],
        code_version=case_input["code_version"],
        cost_model=cost_model,
        time_range_start_utc=datetime.fromisoformat(case_input["time_range_start_utc"]),
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
    assert digest_a == digest_b, f"reproduce digests differ: {digest_a} != {digest_b}"


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
            time_range_start_utc=datetime.fromisoformat(case_input["time_range_start_utc"]),
            time_range_end_utc=datetime.fromisoformat(case_input["time_range_end_utc"]),
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
# Test 7 — costModelHash is spelling-independent, value-sensitive (D-15).
# --------------------------------------------------------------------------- #


def test_cost_model_hash_precision_discipline() -> None:
    """Beh. 7: costModelHash is identical for equivalent spellings
    (fee_rate_entry 0.00020 vs 0.0002) and differs for a genuine value
    change (D-15 canonical numeric text).

    Supersedes the Phase 6 D-12 trailing-precision rule: cost identity is
    the VALUE, not its spelling, so a fixture spelling can never make a
    correct registry binding fail (F-608). Registry parameter_set_hash keeps
    trailing precision; only the cost hash canonicalizes.
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
    assert cost_a.cost_model_hash == cost_b.cost_model_hash, (
        "costModelHash must be equal for equivalent spellings 0.00020 vs 0.0002"
    )
    cost_c = build_cost_model(
        {
            "fee_rate_entry": "0.0003",
            "fee_rate_exit": "0.0005",
            "funding_treatment": "ADDITIVE",
            "expected_slippage": "0.0001",
            "slippage_model": "FIXED_BPS",
            "spread_fill_assumptions": "FULL_FILL",
            "partial_fill_fraction": "1.0",
        }
    )
    assert cost_a.cost_model_hash != cost_c.cost_model_hash, (
        "costModelHash must differ for a genuine value change"
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
    case_input = _v3_case_input(case_dir)
    cost_model = _build_cost_model(case_input["cost_model"])

    record = assemble(
        parameter_set_id=case_input["parameter_set_id"],
        strategy_id=case_input["strategy_id"],
        strategy_version=case_input["strategy_version"],
        data_snapshot_id=case_input["data_snapshot_id"],
        code_version=case_input["code_version"],
        cost_model=cost_model,
        time_range_start_utc=datetime.fromisoformat(case_input["time_range_start_utc"]),
        time_range_end_utc=datetime.fromisoformat(case_input["time_range_end_utc"]),
        universe=case_input["universe"],
        run_type=case_input["run_type"],
        notes=case_input["notes"],
    )

    # verify_experiment must return None when reproducible.
    result = verify_experiment(record, simulator_inputs={})
    assert result is None, f"verify_experiment must return None when reproducible, got {result!r}"


# --------------------------------------------------------------------------- #
# Test 9 — empty-input handling: zero strategy bars yields a valid record.
# --------------------------------------------------------------------------- #


def test_empty_input_yields_valid_record_with_zero_trades() -> None:
    """Beh. 9: zero strategy bars yields a valid ExperimentRecord with
    trade_count zero plus an empty trade list (REFACTOR task).

    Per D-03: the experiment record is valid even when the simulator
    produces no trades. The empty-input case must not raise.
    """
    from src.backtest.experiment import assemble, reproduce

    case_dir = PHASE6_FIXTURES_DIR / "registry_identity"
    case_input = _v3_case_input(case_dir)
    cost_model = _build_cost_model(case_input["cost_model"])

    record = assemble(
        parameter_set_id=case_input["parameter_set_id"],
        strategy_id=case_input["strategy_id"],
        strategy_version=case_input["strategy_version"],
        data_snapshot_id=case_input["data_snapshot_id"],
        code_version=case_input["code_version"],
        cost_model=cost_model,
        time_range_start_utc=datetime.fromisoformat(case_input["time_range_start_utc"]),
        time_range_end_utc=datetime.fromisoformat(case_input["time_range_end_utc"]),
        universe=case_input["universe"],
        run_type=case_input["run_type"],
        notes=case_input["notes"],
    )

    # Empty simulator_inputs (no candles) → empty trade list, no exception.
    trades = reproduce(record, simulator_inputs={})
    assert trades == [], f"empty input must yield empty trade list, got {len(trades)} trades"


# --------------------------------------------------------------------------- #
# Test 10 — run-twice record-stability: identical experiment_id across reruns.
# --------------------------------------------------------------------------- #


def test_run_twice_record_stability() -> None:
    """Beh. 10: two assemble() calls with the same inputs produce
    identical experiment_id (REFACTOR task).

    Per D-03: experiment_id is stable across reruns. The canonicalizer
    sorts dict keys before hashing, so the order in which inputs are
    provided does not affect the digest.
    """
    from src.backtest.experiment import assemble

    case_dir = PHASE6_FIXTURES_DIR / "registry_identity"
    case_input = _v3_case_input(case_dir)
    cost_model = _build_cost_model(case_input["cost_model"])

    record_a = assemble(
        parameter_set_id=case_input["parameter_set_id"],
        strategy_id=case_input["strategy_id"],
        strategy_version=case_input["strategy_version"],
        data_snapshot_id=case_input["data_snapshot_id"],
        code_version=case_input["code_version"],
        cost_model=cost_model,
        time_range_start_utc=datetime.fromisoformat(case_input["time_range_start_utc"]),
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
        time_range_start_utc=datetime.fromisoformat(case_input["time_range_start_utc"]),
        time_range_end_utc=datetime.fromisoformat(case_input["time_range_end_utc"]),
        universe=case_input["universe"],
        run_type=case_input["run_type"],
        notes=case_input["notes"],
    )
    assert record_a.experiment_id == record_b.experiment_id, (
        "experiment_id must be stable across reruns"
    )


# --------------------------------------------------------------------------- #
# Test 11 — universe-order stability: input order cannot change identity.
# --------------------------------------------------------------------------- #


def test_universe_order_stability() -> None:
    """Beh. 11: universe_hash sorts the symbol list before hashing so
    input order cannot change identity (REFACTOR task).

    Per D-03: the universe hash must be stable across input orderings.
    Symbols are sorted alphabetically before hashing.
    """
    from src.backtest.experiment import assemble

    case_dir = PHASE6_FIXTURES_DIR / "registry_identity"
    case_input = _v3_case_input(case_dir)
    cost_model = _build_cost_model(case_input["cost_model"])

    # Same universe in different orders.
    universe_a = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    universe_b = ["SOLUSDT", "BTCUSDT", "ETHUSDT"]
    universe_c = ["ETHUSDT", "SOLUSDT", "BTCUSDT"]

    record_a = assemble(
        parameter_set_id=case_input["parameter_set_id"],
        strategy_id=case_input["strategy_id"],
        strategy_version=case_input["strategy_version"],
        data_snapshot_id=case_input["data_snapshot_id"],
        code_version=case_input["code_version"],
        cost_model=cost_model,
        time_range_start_utc=datetime.fromisoformat(case_input["time_range_start_utc"]),
        time_range_end_utc=datetime.fromisoformat(case_input["time_range_end_utc"]),
        universe=universe_a,
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
        time_range_start_utc=datetime.fromisoformat(case_input["time_range_start_utc"]),
        time_range_end_utc=datetime.fromisoformat(case_input["time_range_end_utc"]),
        universe=universe_b,
        run_type=case_input["run_type"],
        notes=case_input["notes"],
    )
    record_c = assemble(
        parameter_set_id=case_input["parameter_set_id"],
        strategy_id=case_input["strategy_id"],
        strategy_version=case_input["strategy_version"],
        data_snapshot_id=case_input["data_snapshot_id"],
        code_version=case_input["code_version"],
        cost_model=cost_model,
        time_range_start_utc=datetime.fromisoformat(case_input["time_range_start_utc"]),
        time_range_end_utc=datetime.fromisoformat(case_input["time_range_end_utc"]),
        universe=universe_c,
        run_type=case_input["run_type"],
        notes=case_input["notes"],
    )
    assert record_a.experiment_id == record_b.experiment_id == record_c.experiment_id, (
        "experiment_id must be stable across universe orderings"
    )


# --------------------------------------------------------------------------- #
# Nyquist gap-fill (review-fix iteration 1): CR-03a/b/c, CR-05..CR-11.
# --------------------------------------------------------------------------- #


def _assemble_gap_record(
    *,
    cost_dict: dict,
    run_type: str = "CANDIDATE",
    strategy_id: str = "trend-pullback",
    parameter_set_id: str = "baseline-v3",
    result_summary_json: str = "{}",
):
    """Assemble a record bound to registry params + the given cost dict.

    Per Phase 7.1 D-05: assemble() now requires a 7-key registry set.
    baseline-v3 ships all 7 keys; baseline-v2 only has 3 and now raises
    KeyError at the gate (correct behavior — see fixture audit table).
    Phase6 fixtures themselves remain grandfathered (NOT regenerated).
    """
    from src.backtest.experiment import assemble

    return assemble(
        parameter_set_id=parameter_set_id,
        strategy_id=strategy_id,
        strategy_version="v2.0.0",
        data_snapshot_id="1" * 64,
        code_version="gap-test",
        cost_model=_build_cost_model(cost_dict),
        time_range_start_utc=datetime.fromisoformat("2026-09-01T00:00:00+00:00"),
        time_range_end_utc=datetime.fromisoformat("2026-09-11T10:00:00+00:00"),
        universe=["BTCUSDT"],
        run_type=run_type,
        notes="nyquist gap test",
        result_summary_json=result_summary_json,
    )


def _gap_cost_dict() -> dict:
    return {
        "fee_rate_entry": "0.0002",
        "fee_rate_exit": "0.0005",
        "funding_treatment": "ADDITIVE",
        "expected_slippage": "0.0001",
        "slippage_model": "FIXED_BPS",
        "spread_fill_assumptions": "FULL_FILL",
        "partial_fill_fraction": "0.5",
    }


def _gap_simulator_inputs(cost_dict: dict) -> dict:
    return {
        "strategy_id": "trend-pullback",
        "parameter_set_id": "baseline-v3",
        "strategy_version": "v2.0.0",
        "cost_model": dict(cost_dict),
    }


def test_cr03a_reproduce_rejects_mismatched_simulator_inputs() -> None:
    """CR-03a: reproduce() rejects inputs mismatched to the record."""
    from src.backtest.experiment import (
        ExperimentReproducibilityBroken,
        reproduce,
    )

    cost = _gap_cost_dict()
    record = _assemble_gap_record(cost_dict=cost)
    good = _gap_simulator_inputs(cost)

    bad_set = dict(good, parameter_set_id="baseline-no-trade-v1")
    with pytest.raises(ExperimentReproducibilityBroken):
        reproduce(record, simulator_inputs=bad_set)

    bad_version = dict(good, strategy_version="v9.9.9")
    with pytest.raises(ExperimentReproducibilityBroken):
        reproduce(record, simulator_inputs=bad_version)

    bad_cost = dict(good, cost_model=dict(cost, fee_rate_entry="0.0099"))
    with pytest.raises(ExperimentReproducibilityBroken):
        reproduce(record, simulator_inputs=bad_cost)


def test_cr03b_reproduced_trades_carry_typed_decimal_datetime_fields() -> None:
    """CR-03b: reproduced TradeRecords hold typed Decimal/datetime fields."""
    from src.backtest.experiment import assemble, reproduce

    # Phase 12 (D048): the regenerated baseline fixture names its own v3
    # baseline set and carries the matching 8-key cost dict, so assemble()
    # binds it directly - no rebinding to baseline-v3 and no respelling.
    case = dict(_load_input(PHASE6_FIXTURES_DIR / "baselines" / "simple_trend"))
    assert case["parameter_set_id"] == "baseline-simple-trend-v3"
    cost_model_dict: dict = dict(case["cost_model"])
    record = assemble(
        parameter_set_id=case["parameter_set_id"],
        strategy_id=case["strategy_id"],
        strategy_version=case["strategy_version"],
        data_snapshot_id="2" * 64,
        code_version="gap-test-cr03b",
        cost_model=_build_cost_model(cost_model_dict),
        time_range_start_utc=datetime.fromisoformat("2026-09-01T00:00:00+00:00"),
        time_range_end_utc=datetime.fromisoformat("2026-09-11T10:00:00+00:00"),
        universe=["BTCUSDT"],
        run_type="BASELINE_SIMPLE_TREND",
        notes="nyquist cr03b",
    )
    sim_inputs = dict(case, cost_model=cost_model_dict)
    trades = reproduce(record, simulator_inputs=sim_inputs)
    assert len(trades) >= 1, "simple-trend baseline must yield filled trades"
    decimal_fields = (
        "entry_price",
        "quantity",
        "exit_price",
        "realized_pnl",
        "realized_risk",
        "gross_pnl",
        "entry_fee",
        "exit_fee",
        "funding_amount",
        "slippage_amount",
        "modeled_costs_per_unit",
    )
    for trade in trades:
        for fname in decimal_fields:
            value = getattr(trade, fname)
            assert value is None or isinstance(value, Decimal), (
                f"{fname} must be Decimal|None, got {type(value).__name__} "
                f"({value!r}) — stringified rebuild corrupts types"
            )
        for fname in ("entry_time_utc", "exit_time_utc"):
            value = getattr(trade, fname)
            assert value is None or isinstance(value, datetime), (
                f"{fname} must be datetime|None, got {type(value).__name__}"
            )
        assert not isinstance(trade.entry_price, str)
        assert not isinstance(trade.exit_time_utc, str)


def test_cr03c_verify_experiment_detects_engine_drift_vs_stored_digest() -> None:
    """CR-03c: verify_experiment detects drift vs the stored result digest."""
    import json

    from src.backtest.experiment import (
        ExperimentReproducibilityBroken,
        verify_experiment,
    )

    cost = _gap_cost_dict()
    # No stored digest: empty-input determinism check passes.
    record = _assemble_gap_record(cost_dict=cost)
    assert verify_experiment(record, simulator_inputs={}) is None

    # Forged stored digest: drift detected.
    forged = _assemble_gap_record(
        cost_dict=cost,
        result_summary_json=json.dumps({"trades_digest": "f" * 64}),
    )
    with pytest.raises(ExperimentReproducibilityBroken):
        verify_experiment(forged, simulator_inputs={})

    # Matching stored digest: accepted.
    matching_digest = sha256_hex({"trades": []})
    matching = _assemble_gap_record(
        cost_dict=cost,
        result_summary_json=json.dumps({"trades_digest": matching_digest}),
    )
    assert verify_experiment(matching, simulator_inputs={}) is None


def test_cr05_decimal_inputs_hash_identically_to_string_inputs() -> None:
    """CR-05: Decimal cost inputs hash identically to their string spellings."""
    from src.backtest.costs import build_cost_model

    string_cost = _gap_cost_dict()
    decimal_cost = {
        key: (
            Decimal(value)
            if key
            not in {
                "funding_treatment",
                "slippage_model",
                "spread_fill_assumptions",
            }
            else value
        )
        for key, value in string_cost.items()
    }
    assert build_cost_model(decimal_cost).cost_model_hash == (
        build_cost_model(string_cost).cost_model_hash
    ), "Decimal inputs must never round-trip through str() before hashing"

    # Equivalent spellings hash equally (D-15); a genuine change still differs.
    trailing = dict(string_cost, fee_rate_entry="0.00020")
    trimmed = dict(string_cost, fee_rate_entry="0.0002")
    assert build_cost_model(trailing).cost_model_hash == (build_cost_model(trimmed).cost_model_hash)
    assert (
        build_cost_model(dict(decimal_cost, fee_rate_entry=Decimal("0.00020"))).cost_model_hash
        == build_cost_model(trailing).cost_model_hash
    )
    changed = dict(string_cost, fee_rate_entry="0.0003")
    assert build_cost_model(changed).cost_model_hash != (build_cost_model(trimmed).cost_model_hash)


def test_cr06_experiment_id_differs_across_run_type_and_strategy_id() -> None:
    """CR-06: experiment_id binds run_type and strategy_id (no collisions)."""
    cost = _gap_cost_dict()
    candidate = _assemble_gap_record(cost_dict=cost, run_type="CANDIDATE")
    baseline = _assemble_gap_record(cost_dict=cost, run_type="BASELINE_NO_TRADE")
    assert candidate.experiment_id != baseline.experiment_id, (
        "CANDIDATE vs BASELINE_NO_TRADE over identical inputs must differ"
    )

    trend = _assemble_gap_record(cost_dict=cost, strategy_id="trend-pullback")
    breakout = _assemble_gap_record(
        cost_dict=cost,
        strategy_id="breakout-retest",
        parameter_set_id="baseline-v3",
    )
    assert trend.experiment_id != breakout.experiment_id, (
        "two strategies sharing a version string must never share experiment_id"
    )


def test_cr07_baselines_enforce_degenerated_minimum_rr() -> None:
    """CR-07: baseline runners fail closed on non-degenerated candidate params."""
    from src.backtest.experiment import baseline_no_trade, baseline_simple_trend

    candidate = _load_input(PHASE6_FIXTURES_DIR / "intrabar_both_touched")
    with pytest.raises(ValueError, match="minimum_rr"):
        baseline_no_trade(candidate)

    no_trade_case = _load_input(PHASE6_FIXTURES_DIR / "baselines" / "no_trade")
    with pytest.raises(ValueError, match="minimum_rr"):
        baseline_simple_trend(no_trade_case)


def test_cr09_forged_cost_model_hash_rejected_at_assembly() -> None:
    """CR-09: a forged cost_model_hash inconsistent with params is rejected."""
    from src.backtest.costs import CostModel, build_cost_model

    good = build_cost_model(_gap_cost_dict())
    with pytest.raises(ValueError, match="mismatch"):
        CostModel(
            fee_rate_entry=good.fee_rate_entry,
            fee_rate_exit=good.fee_rate_exit,
            funding_treatment=good.funding_treatment,
            expected_slippage=good.expected_slippage,
            slippage_model=good.slippage_model,
            spread_fill_assumptions=good.spread_fill_assumptions,
            partial_fill_fraction=good.partial_fill_fraction,
            cost_model_hash="f" * 64,
        )
    # The verified hash round-trips cleanly and binds the experiment record.
    verified = CostModel(
        fee_rate_entry=good.fee_rate_entry,
        fee_rate_exit=good.fee_rate_exit,
        funding_treatment=good.funding_treatment,
        expected_slippage=good.expected_slippage,
        slippage_model=good.slippage_model,
        spread_fill_assumptions=good.spread_fill_assumptions,
        partial_fill_fraction=good.partial_fill_fraction,
        cost_model_hash=good.cost_model_hash,
    )
    record = _assemble_gap_record(cost_dict=_gap_cost_dict())
    assert record.cost_model_hash == verified.cost_model_hash


def test_cr11_baseline_tomls_carry_detector_and_cost_keys() -> None:
    """CR-11: baseline TOMLs carry atr_period + 4 cost keys from COST_MODEL."""
    import ast
    from pathlib import Path

    from src.domain.registry import load_parameter_set

    repo_root = Path(__file__).resolve().parents[1]
    tree = ast.parse((repo_root / "scripts" / "gen_phase6_fixtures.py").read_text(encoding="utf-8"))
    canonical: dict | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", "") == "COST_MODEL" for target in node.targets
        ):
            canonical = ast.literal_eval(node.value)
    assert canonical is not None, "COST_MODEL canonical source must exist"
    # Phase 14 (D-16): the generator literal must equal the code constant.
    from src.backtest.semantics import FUNDING_CONVENTION

    assert canonical["funding_convention"] == FUNDING_CONVENTION

    for parameter_set_id in (
        "baseline-no-trade-v1",
        "baseline-simple-trend-v1",
        "baseline-no-trade-v3",
        "baseline-simple-trend-v3",
    ):
        parameter_set = load_parameter_set("trend-pullback", parameter_set_id)
        assert parameter_set.params["atr_period"] == 14, (
            f"{parameter_set_id}: atr_period must match sibling baseline-v2 sets"
        )
        for key in (
            "funding_treatment",
            "slippage_model",
            "spread_fill_assumptions",
        ):
            assert str(parameter_set.params[key]) == str(canonical[key]), (
                f"{parameter_set_id}: {key}={parameter_set.params[key]!r} != "
                f"COST_MODEL canonical {canonical[key]!r}"
            )
        # partial_fill_fraction: TOML whole-number rule normalizes 1.0 to
        # int 1 while the fixture spells "1.0" — value equality binds them.
        assert Decimal(str(parameter_set.params["partial_fill_fraction"])) == (
            Decimal(str(canonical["partial_fill_fraction"]))
        ), (
            f"{parameter_set_id}: partial_fill_fraction="
            f"{parameter_set.params['partial_fill_fraction']!r} != "
            f"COST_MODEL canonical {canonical['partial_fill_fraction']!r}"
        )
        # Phase 12: the v3 baselines carry the rate keys and the stop-exit
        # slippage rate; compare by value against the generator literal.
        if parameter_set_id.endswith("-v3"):
            for key in (
                "fee_rate_entry",
                "fee_rate_exit",
                "expected_slippage",
                "exit_slippage_rate",
            ):
                assert Decimal(str(parameter_set.params[key])) == Decimal(str(canonical[key])), (
                    f"{parameter_set_id}: {key}={parameter_set.params[key]!r} != "
                    f"COST_MODEL canonical {canonical[key]!r}"
                )
