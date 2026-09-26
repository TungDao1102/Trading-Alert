"""Experiment registry — six-field identity + reproduce + baselines (Phase 6, plan 06-02).

Per D-03 + BACKTEST_SPEC §11 + RESEARCH_PROTOCOL §5: every experiment
record carries the canonical six-field identity tuple
(`experimentId`, `strategyVersion`, `parameterSetHash` + runtime
`parameterSetId` alongside, `dataSnapshotId`, `codeVersion`,
`costModelHash`) plus dataset range, symbol universe, timeframe, full
parameters, cost assumptions, results, and notes. A record missing any
field fails the acceptance gate.

Reproduction = re-running the recorded six-field tuple yields
byte-identical trade lists. Baselines (no-trade + simple-trend) run
through the identical simulator with degenerated parameter sets.

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 / Phase-5 D-05 purity precedent.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.domain.canonical import sha256_hex
from src.domain.registry import load_parameter_set

from .costs import CostModel
from .simulator import TradeRecord, run as simulator_run


# --------------------------------------------------------------------------- #
# Exceptions.
# --------------------------------------------------------------------------- #


class IncompleteExperimentRecord(Exception):
    """Raised when an ExperimentRecord is missing any identity field.

    Per D-03: a record missing any field fails the acceptance gate.
    """


class ExperimentReproducibilityBroken(Exception):
    """Raised when reproduce byte-check fails (engine drift detected).

    Per D-03: reproduction = re-running the recorded six-field tuple
    yields byte-identical trade lists. Drift raises this exception.
    """


# --------------------------------------------------------------------------- #
# Allowed run_type values.
# --------------------------------------------------------------------------- #


_RUN_TYPES: frozenset[str] = frozenset(
    {"CANDIDATE", "BASELINE_NO_TRADE", "BASELINE_SIMPLE_TREND"}
)


# --------------------------------------------------------------------------- #
# Validation helpers — local copies (D-12 fail-closed).
# --------------------------------------------------------------------------- #


def _require_utc_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(
            f"{field_name} must be UTC, got offset {value.utcoffset()}"
        )


def _require_non_empty_str(value: str, field_name: str) -> None:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_64_hex(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be str, got {type(value).__name__}")
    if len(value) != 64:
        raise ValueError(f"{field_name} must be 64-hex, got len={len(value)}")
    if not all(c in "0123456789abcdef" for c in value):
        raise ValueError(f"{field_name} must be lowercase hex, got {value!r}")


# --------------------------------------------------------------------------- #
# ExperimentRecord — frozen value object with six-field identity.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ExperimentRecord:
    """A versioned experiment record (D-03).

    The six identity fields are:
      - `experiment_id` (64-hex SHA256 over the identity payload)
      - `strategy_version` (string)
      - `parameter_set_hash` (64-hex SHA256 from registry)
      - `data_snapshot_id` (64-hex SHA256 of the dataset version)
      - `code_version` (string — engine commit/tag)
      - `cost_model_hash` (64-hex SHA256 from CostModel)

    `parameter_set_id` lives alongside `parameter_set_hash` (not inside
    the hash payload) per `docs/configuration/CONFIGURATION.md:100-113`.

    `__post_init__` raises `IncompleteExperimentRecord` on any missing
    identity field and validates 64-hex shape on hash fields.
    """

    experiment_id: str
    strategy_version: str
    parameter_set_id: str
    parameter_set_hash: str
    data_snapshot_id: str
    code_version: str
    cost_model_hash: str
    time_range_start_utc: datetime
    time_range_end_utc: datetime
    universe_hash: str
    run_type: str
    result_summary_json: str
    notes: str

    def __post_init__(self) -> None:
        # Validate all identity fields are present and well-formed.
        for fname in (
            "experiment_id",
            "parameter_set_hash",
            "data_snapshot_id",
            "cost_model_hash",
            "universe_hash",
        ):
            value = getattr(self, fname)
            if not isinstance(value, str) or value == "":
                raise IncompleteExperimentRecord(
                    f"{fname} must be a non-empty string"
                )
            _require_64_hex(value, fname)
        for fname in ("strategy_version", "code_version"):
            value = getattr(self, fname)
            if not isinstance(value, str) or value == "":
                raise IncompleteExperimentRecord(
                    f"{fname} must be a non-empty string"
                )
        _require_non_empty_str(self.parameter_set_id, "parameter_set_id")
        if self.run_type not in _RUN_TYPES:
            raise IncompleteExperimentRecord(
                f"run_type must be one of {sorted(_RUN_TYPES)}, "
                f"got {self.run_type!r}"
            )
        _require_utc_aware(self.time_range_start_utc, "time_range_start_utc")
        _require_utc_aware(self.time_range_end_utc, "time_range_end_utc")
        if self.time_range_end_utc <= self.time_range_start_utc:
            raise IncompleteExperimentRecord(
                "time_range_end_utc must be > time_range_start_utc"
            )


# --------------------------------------------------------------------------- #
# Universe hash — sort symbols before hashing (D-03 + REFACTOR task).
# --------------------------------------------------------------------------- #


def _universe_hash(universe: Sequence[str]) -> str:
    """Return the SHA256 hex digest of the sorted symbol universe.

    Per D-03: the universe hash must be stable across input orderings.
    Symbols are sorted alphabetically before hashing.
    """
    return sha256_hex({"universe": sorted(universe)})


# --------------------------------------------------------------------------- #
# assemble — build an ExperimentRecord from identity inputs.
# --------------------------------------------------------------------------- #


def assemble(
    *,
    parameter_set_id: str,
    strategy_id: str,
    strategy_version: str,
    data_snapshot_id: str,
    code_version: str,
    cost_model: CostModel,
    time_range_start_utc: datetime,
    time_range_end_utc: datetime,
    universe: Sequence[str],
    run_type: str,
    notes: str = "",
    result_summary_json: str = "{}",
) -> ExperimentRecord:
    """Assemble an ExperimentRecord from the six-field identity tuple.

    Per D-03: the parameter set is loaded from the registry (fail closed
    on `UnregisteredParameterSet`). The `experiment_id` is SHA256 over
    the canonical payload of the six identity fields plus time range
    and universe hash.

    Raises:
        UnregisteredParameterSet: parameter_set_id not in registry.
        IncompleteExperimentRecord: any identity field missing or
            malformed.
    """
    # Load the parameter set from the registry (fail closed).
    parameter_set = load_parameter_set(strategy_id, parameter_set_id)

    # Build the universe hash (sorted for order-stability).
    universe_hash = _universe_hash(universe)

    # Build the experiment_id via sha256_hex over the identity payload.
    identity_payload = {
        "strategy_version": strategy_version,
        "parameter_set_hash": parameter_set.parameter_set_hash,
        "data_snapshot_id": data_snapshot_id,
        "code_version": code_version,
        "cost_model_hash": cost_model.cost_model_hash,
        "time_range_start_utc": time_range_start_utc,
        "time_range_end_utc": time_range_end_utc,
        "universe_hash": universe_hash,
    }
    experiment_id = sha256_hex(identity_payload)

    return ExperimentRecord(
        experiment_id=experiment_id,
        strategy_version=strategy_version,
        parameter_set_id=parameter_set_id,
        parameter_set_hash=parameter_set.parameter_set_hash,
        data_snapshot_id=data_snapshot_id,
        code_version=code_version,
        cost_model_hash=cost_model.cost_model_hash,
        time_range_start_utc=time_range_start_utc,
        time_range_end_utc=time_range_end_utc,
        universe_hash=universe_hash,
        run_type=run_type,
        result_summary_json=result_summary_json,
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# reproduce — re-run simulator.run with the recorded tuple.
# --------------------------------------------------------------------------- #


def reproduce(
    record: ExperimentRecord,
    *,
    simulator_inputs: dict[str, Any],
) -> list[TradeRecord]:
    """Re-run the simulator with the recorded tuple.

    Per D-03: reproduction = re-running the recorded six-field tuple
    yields byte-identical trade lists. With empty `simulator_inputs`,
    returns an empty list (deterministic, no candles to replay).
    """
    if not simulator_inputs:
        return []
    result = simulator_run(simulator_inputs)
    return [TradeRecord(**t) for t in result["trades"]]


# --------------------------------------------------------------------------- #
# verify_experiment — runtime tripwire for reproducibility.
# --------------------------------------------------------------------------- #


def verify_experiment(
    record: ExperimentRecord,
    *,
    simulator_inputs: dict[str, Any],
) -> None:
    """Return None when reproducible; raise ExperimentReproducibilityBroken on drift.

    Per D-03: verify_experiment is the runtime tripwire for
    reproducibility. Two reproduce() calls with the same inputs must
    yield byte-identical trade lists.
    """
    trades_a = reproduce(record, simulator_inputs=simulator_inputs)
    trades_b = reproduce(record, simulator_inputs=simulator_inputs)
    digest_a = sha256_hex({"trades": [t.to_dict() for t in trades_a]})
    digest_b = sha256_hex({"trades": [t.to_dict() for t in trades_b]})
    if digest_a != digest_b:
        raise ExperimentReproducibilityBroken(
            f"reproduce digests differ: {digest_a} != {digest_b}"
        )
    return None


# --------------------------------------------------------------------------- #
# Baseline runners — same engine, degenerated parameter sets.
# --------------------------------------------------------------------------- #


def _filled_trades(trades: list[TradeRecord]) -> list[TradeRecord]:
    """Filter to filled trades only (ENTRY_FILLED + PARTIAL_FILL).

    REJECT records are risk-rejection outcomes, not filled trades.
    Baselines return only filled trades so the "empty trade list"
    semantics hold when no plan passes the gates.
    """
    return [t for t in trades if t.entry_kind in {"ENTRY_FILLED", "PARTIAL_FILL"}]


def baseline_no_trade(case_input: dict[str, Any]) -> list[TradeRecord]:
    """Run the no-trade baseline (minimum_rr=100).

    Per BACKTEST_SPEC §9: every candidate is compared against declared
    baselines. The no-trade baseline degenerates `minimum_rr` to 100 so
    every plan fails the RR gate; the simulator emits no filled trades.

    The case_input must reference `parameter_set_id="baseline-no-trade-v1"`
    (or equivalent with minimum_rr=100).
    """
    result = simulator_run(case_input)
    trades = [TradeRecord(**t) for t in result["trades"]]
    return _filled_trades(trades)


def baseline_simple_trend(case_input: dict[str, Any]) -> list[TradeRecord]:
    """Run the simple-trend baseline (looser minimum_rr + single-condition trend).

    Per BACKTEST_SPEC §9: the simple-trend baseline uses a looser
    `minimum_rr` and a single-condition trend filter so the simulator
    emits a deterministic single-direction trade list.

    The case_input must reference `parameter_set_id="baseline-simple-trend-v1"`
    (or equivalent with looser config).
    """
    result = simulator_run(case_input)
    trades = [TradeRecord(**t) for t in result["trades"]]
    return _filled_trades(trades)


__all__ = [
    "ExperimentRecord",
    "ExperimentReproducibilityBroken",
    "IncompleteExperimentRecord",
    "assemble",
    "baseline_no_trade",
    "baseline_simple_trend",
    "reproduce",
    "verify_experiment",
]
