"""Experiment registry — six-field identity + typed record + reproduce + baselines.

Phase 6 (plan 06-02), per D-03 + BACKTEST_SPEC §11 + RESEARCH_PROTOCOL §5: every
experiment record carries the canonical six-field identity tuple
(`experimentId`, `strategyVersion`, `parameterSetHash` + runtime
`parameterSetId` alongside, `dataSnapshotId`, `codeVersion`,
`costModelHash`) plus dataset range, symbol universe, timeframe, full
parameters, cost assumptions, results, and notes. A record missing any
field fails the acceptance gate.

Phase 14 (plan 14-15, D-22, F-118, BKTS-04) adds typed, validated record fields
instead of free-form summary JSON: NO_TRADE counts by reason, the intrabar
tie-break, timeframes, full parameter and cost values, the simulator semantics
version, a verifiable code version (git commit and dirty flag), the fallback and
END_OF_DATA counts, the window sizes, the allowed gaps used, and the split role and
boundaries. `__post_init__` raises `IncompleteExperimentRecord` for any invalid
value, so an invalid record cannot be constructed. The semantics version, the split
role and the split boundaries join `experiment_id` (D-02), so a record produced by
the old simulator can never share an identity with a new one. Holdout-once
enforcement is NOT here (Phase 26, F-960). `result_summary_json` survives only as
the carrier of the optional stored `trades_digest`.

Reproduction = re-running the recorded tuple yields byte-identical trade lists and
a run summary that agrees with the typed fields. Baselines (no-trade + simple-trend)
run through the identical simulator with degenerated parameter sets.

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 / Phase-5 D-05 purity precedent. The git commit and
dirty flag are read by `src/adapters/code_version.py`, never here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.core.types import _require_utc_aware
from src.domain.canonical import canonical_decimal_text, sha256_hex
from src.domain.registry import load_parameter_set

from .binding import assert_cost_model_binds_registry
from .costs import COST_KEYS, OPTIONAL_COST_KEYS, CostModel, build_cost_model
from .semantics import (
    FUNDING_CONVENTION,
    PLAN_SOURCE_STRATEGY,
    SIMULATOR_SEMANTICS_VERSION,
    TIE_BREAK,
)
from .simulator import TradeRecord
from .simulator import run as simulator_run
from .validator import validate_trade_record

# --------------------------------------------------------------------------- #
# Exceptions.
# --------------------------------------------------------------------------- #


class IncompleteExperimentRecord(Exception):
    """Raised when an ExperimentRecord is missing any identity field or holds an invalid value.

    Per D-03: a record missing any field fails the acceptance gate. Per D-22 the typed
    fields are validated at construction, so every invalid value raises this too.
    """


class ExperimentReproducibilityBroken(Exception):
    """Raised when reproduce byte-check fails (engine drift detected).

    Per D-03: reproduction = re-running the recorded six-field tuple
    yields byte-identical trade lists. Drift raises this exception.
    """


# --------------------------------------------------------------------------- #
# Allowed run_type and split_role values.
# --------------------------------------------------------------------------- #


_RUN_TYPES: frozenset[str] = frozenset({"CANDIDATE", "BASELINE_NO_TRADE", "BASELINE_SIMPLE_TREND"})

# RESEARCH_PROTOCOL section 1: Development 40%, Validation 40%, Final holdout 20% (D-22).
SPLIT_ROLES: tuple[str, ...] = ("DEVELOPMENT", "VALIDATION", "HOLDOUT")

_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
_DIRTY_SUFFIX = "-dirty"


# --------------------------------------------------------------------------- #
# Validation helpers — _require_utc_aware delegated to src/core/types.py
# (shared helper, D-12 fail-closed). The other two are experiment-specific.
# --------------------------------------------------------------------------- #


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


def _incomplete_if_not_utc(value: object, field_name: str) -> None:
    """Typed-field datetime check that reports as `IncompleteExperimentRecord`."""
    if not isinstance(value, datetime):
        raise IncompleteExperimentRecord(f"{field_name} must be a datetime")
    try:
        _require_utc_aware(value, field_name)
    except ValueError as exc:
        raise IncompleteExperimentRecord(str(exc)) from None


def _require_count(value: object, field_name: str, *, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise IncompleteExperimentRecord(f"{field_name} must be an int")
    if value < minimum:
        raise IncompleteExperimentRecord(f"{field_name} must be >= {minimum}, got {value}")


def _require_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or value == "":
        raise IncompleteExperimentRecord(f"{field_name} must be a non-empty string")


def _require_pairs(value: object, field_name: str) -> tuple[tuple[str, Any], ...]:
    """A tuple of `(key, value)` pairs with non-empty str keys, sorted and unique."""
    if not isinstance(value, tuple):
        raise IncompleteExperimentRecord(f"{field_name} must be a tuple of (key, value) pairs")
    previous: str | None = None
    for item in value:
        if not (
            isinstance(item, tuple)
            and len(item) == 2
            and isinstance(item[0], str)
            and item[0] != ""
        ):
            raise IncompleteExperimentRecord(
                f"{field_name} entries must be (non-empty str key, value) pairs"
            )
        if previous is not None and not previous < item[0]:
            raise IncompleteExperimentRecord(f"{field_name} keys must be sorted and unique")
        previous = item[0]
    return value


# --------------------------------------------------------------------------- #
# CodeVersion — the verifiable git commit and dirty flag (D-22).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CodeVersion:
    """The code a run was produced by: a 40-hex git commit and a dirty flag.

    `text` is the commit, with `-dirty` appended for a working tree that differed from it;
    it is what `ExperimentRecord.code_version` must equal. `src/adapters/code_version.py`
    reads the pair from git (this package may not run subprocesses).
    """

    commit: str
    dirty: bool

    def __post_init__(self) -> None:
        if not isinstance(self.commit, str) or _COMMIT_PATTERN.fullmatch(self.commit) is None:
            raise IncompleteExperimentRecord("code_commit must be 40 lowercase hex characters")
        if not isinstance(self.dirty, bool):
            raise IncompleteExperimentRecord("code_dirty must be a bool")

    @property
    def text(self) -> str:
        return f"{self.commit}{_DIRTY_SUFFIX}" if self.dirty else self.commit


# --------------------------------------------------------------------------- #
# RecordedGap — an acknowledged data gap the run carried (BACKTEST_SPEC §11, D-36).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RecordedGap:
    """One acknowledged data gap of a run (WR-05).

    A funding gap is recorded when it covered a hole during the run; a gap of any other
    series (bars, 1m trade or mark minutes, open interest) is recorded whenever the case
    acknowledged it, because the run then simulated over data that is missing those rows.
    """

    series: str
    symbol: str
    start_utc: datetime
    end_utc: datetime

    def __post_init__(self) -> None:
        _require_text(self.series, "allowed_gaps series")
        _require_text(self.symbol, "allowed_gaps symbol")
        _incomplete_if_not_utc(self.start_utc, "allowed_gaps start_utc")
        _incomplete_if_not_utc(self.end_utc, "allowed_gaps end_utc")
        if self.end_utc < self.start_utc:
            raise IncompleteExperimentRecord("allowed_gaps end_utc must be >= start_utc")

    def sort_key(self) -> tuple[str, datetime, datetime, str]:
        return (self.symbol, self.start_utc, self.end_utc, self.series)

    def to_dict(self) -> dict[str, str]:
        return {
            "series": self.series,
            "symbol": self.symbol,
            "start_utc": self.start_utc.isoformat(),
            "end_utc": self.end_utc.isoformat(),
        }


# --------------------------------------------------------------------------- #
# ExperimentRecord — frozen value object with six-field identity and typed fields.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ExperimentRecord:
    """A versioned experiment record (D-03, D-22).

    The six identity fields are:
      - `experiment_id` (64-hex SHA256 over the identity payload)
      - `strategy_version` (string)
      - `parameter_set_hash` (64-hex SHA256 from registry)
      - `data_snapshot_id` (64-hex SHA256 of the dataset version)
      - `code_version` (string: the git commit, plus `-dirty` for a dirty tree)
      - `cost_model_hash` (64-hex SHA256 from CostModel)

    `parameter_set_id` lives alongside `parameter_set_hash` (not inside
    the hash payload) per `docs/configuration/CONFIGURATION.md:100-113`.

    The typed fields (Phase 14, D-22) come after `notes`; none has a default, so a record
    without them cannot be built:
      - `no_trade_counts`: sorted `(reason, count)` pairs
      - `intrabar_tie_break`, `simulator_semantics_version`: must equal the code constants
      - `timeframe`, `context_timeframe`: the strategy and context bar intervals
      - `parameter_values`, `cost_values`: sorted `(key, canonical text)` pairs; the cost
        values must carry `funding_convention` and must hash to `cost_model_hash`
      - `code_commit`, `code_dirty`: `code_version` must equal the commit, plus `-dirty`
      - `fallback_count`, `end_of_data_count`, `strategy_window_bars`, `context_window_bars`
      - `allowed_gaps`: the `RecordedGap`s the run used, sorted by symbol and time
      - `split_role`, `split_start_utc`, `split_end_utc`: the protocol split and its
        boundaries, which must contain the record's time range

    `__post_init__` raises `IncompleteExperimentRecord` on any missing or invalid value.
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
    # --- typed fields (Phase 14, plan 14-15, D-22) ---
    no_trade_counts: tuple[tuple[str, int], ...]
    intrabar_tie_break: str
    timeframe: str
    context_timeframe: str
    parameter_values: tuple[tuple[str, str], ...]
    cost_values: tuple[tuple[str, str], ...]
    simulator_semantics_version: str
    code_commit: str
    code_dirty: bool
    fallback_count: int
    end_of_data_count: int
    strategy_window_bars: int
    context_window_bars: int
    allowed_gaps: tuple[RecordedGap, ...]
    split_role: str
    split_start_utc: datetime
    split_end_utc: datetime

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
                raise IncompleteExperimentRecord(f"{fname} must be a non-empty string")
            _require_64_hex(value, fname)
        for fname in ("strategy_version", "code_version"):
            value = getattr(self, fname)
            if not isinstance(value, str) or value == "":
                raise IncompleteExperimentRecord(f"{fname} must be a non-empty string")
        _require_non_empty_str(self.parameter_set_id, "parameter_set_id")
        if self.run_type not in _RUN_TYPES:
            raise IncompleteExperimentRecord(
                f"run_type must be one of {sorted(_RUN_TYPES)}, got {self.run_type!r}"
            )
        _require_utc_aware(self.time_range_start_utc, "time_range_start_utc")
        _require_utc_aware(self.time_range_end_utc, "time_range_end_utc")
        if self.time_range_end_utc <= self.time_range_start_utc:
            raise IncompleteExperimentRecord("time_range_end_utc must be > time_range_start_utc")
        self._validate_semantics()
        self._validate_code_version()
        self._validate_counts()
        self._validate_values()
        self._validate_split()

    def _validate_semantics(self) -> None:
        if self.simulator_semantics_version != SIMULATOR_SEMANTICS_VERSION:
            raise IncompleteExperimentRecord(
                f"simulator_semantics_version must be {SIMULATOR_SEMANTICS_VERSION!r}, "
                f"got {self.simulator_semantics_version!r}"
            )
        if self.intrabar_tie_break != TIE_BREAK:
            raise IncompleteExperimentRecord(
                f"intrabar_tie_break must be {TIE_BREAK!r}, got {self.intrabar_tie_break!r}"
            )
        _require_text(self.timeframe, "timeframe")
        _require_text(self.context_timeframe, "context_timeframe")

    def _validate_code_version(self) -> None:
        if (
            not isinstance(self.code_commit, str)
            or _COMMIT_PATTERN.fullmatch(self.code_commit) is None
        ):
            raise IncompleteExperimentRecord("code_commit must be 40 lowercase hex characters")
        if not isinstance(self.code_dirty, bool):
            raise IncompleteExperimentRecord("code_dirty must be a bool")
        expected = CodeVersion(commit=self.code_commit, dirty=self.code_dirty).text
        if self.code_version != expected:
            raise IncompleteExperimentRecord(
                f"code_version must equal the commit (plus {_DIRTY_SUFFIX!r} when dirty): "
                f"expected {expected!r}, got {self.code_version!r}"
            )

    def _validate_counts(self) -> None:
        for reason, count in _require_pairs(self.no_trade_counts, "no_trade_counts"):
            _require_count(count, f"no_trade_counts[{reason}]", minimum=0)
        _require_count(self.fallback_count, "fallback_count", minimum=0)
        _require_count(self.end_of_data_count, "end_of_data_count", minimum=0)
        _require_count(self.strategy_window_bars, "strategy_window_bars", minimum=1)
        _require_count(self.context_window_bars, "context_window_bars", minimum=1)
        if not isinstance(self.allowed_gaps, tuple) or not all(
            isinstance(gap, RecordedGap) for gap in self.allowed_gaps
        ):
            raise IncompleteExperimentRecord("allowed_gaps must be a tuple of RecordedGap")
        keys = [gap.sort_key() for gap in self.allowed_gaps]
        if any(not earlier < later for earlier, later in zip(keys, keys[1:], strict=False)):
            raise IncompleteExperimentRecord("allowed_gaps must be sorted and unique")

    def _validate_values(self) -> None:
        parameters = _require_pairs(self.parameter_values, "parameter_values")
        if not parameters:
            raise IncompleteExperimentRecord("parameter_values must not be empty")
        for key, text in parameters:
            _require_text(text, f"parameter_values[{key}]")
        costs = _require_pairs(self.cost_values, "cost_values")
        for key, text in costs:
            _require_text(text, f"cost_values[{key}]")
        cost_map = dict(costs)
        allowed = {*COST_KEYS, *OPTIONAL_COST_KEYS}
        unknown = sorted(set(cost_map) - allowed)
        if unknown:
            raise IncompleteExperimentRecord(f"cost_values has unknown keys {unknown}")
        missing = sorted({*COST_KEYS, "funding_convention"} - set(cost_map))
        if missing:
            raise IncompleteExperimentRecord(f"cost_values lacks the keys {missing}")
        if cost_map["funding_convention"] != FUNDING_CONVENTION:
            raise IncompleteExperimentRecord(
                f"cost_values funding_convention must be {FUNDING_CONVENTION!r}"
            )
        try:
            rebuilt = build_cost_model(cost_map)
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise IncompleteExperimentRecord(
                f"cost_values do not build a cost model ({type(exc).__name__})"
            ) from None
        if rebuilt.cost_model_hash != self.cost_model_hash:
            raise IncompleteExperimentRecord(
                f"cost_values hash to {rebuilt.cost_model_hash!r}, not the recorded "
                f"cost_model_hash {self.cost_model_hash!r}"
            )

    def _validate_split(self) -> None:
        if self.split_role not in SPLIT_ROLES:
            raise IncompleteExperimentRecord(
                f"split_role must be one of {list(SPLIT_ROLES)}, got {self.split_role!r}"
            )
        _incomplete_if_not_utc(self.split_start_utc, "split_start_utc")
        _incomplete_if_not_utc(self.split_end_utc, "split_end_utc")
        if self.split_start_utc > self.time_range_start_utc:
            raise IncompleteExperimentRecord(
                "split_start_utc must be <= time_range_start_utc (the split contains the range)"
            )
        if self.split_end_utc < self.time_range_end_utc:
            raise IncompleteExperimentRecord(
                "split_end_utc must be >= time_range_end_utc (the split contains the range)"
            )

    def to_dict(self) -> dict[str, Any]:
        """Project to a JSON-native dict (the evidence-file shape of `analytics-evidence/2`).

        Counts and values serialize as objects, gaps as a list of objects; no key is named
        `parameters` or `parameters_json` (research-gate tripwire).
        """
        return {
            "experiment_id": self.experiment_id,
            "strategy_version": self.strategy_version,
            "parameter_set_id": self.parameter_set_id,
            "parameter_set_hash": self.parameter_set_hash,
            "data_snapshot_id": self.data_snapshot_id,
            "code_version": self.code_version,
            "cost_model_hash": self.cost_model_hash,
            "time_range_start_utc": self.time_range_start_utc.isoformat(),
            "time_range_end_utc": self.time_range_end_utc.isoformat(),
            "universe_hash": self.universe_hash,
            "run_type": self.run_type,
            "result_summary_json": self.result_summary_json,
            "notes": self.notes,
            "no_trade_counts": dict(self.no_trade_counts),
            "intrabar_tie_break": self.intrabar_tie_break,
            "timeframe": self.timeframe,
            "context_timeframe": self.context_timeframe,
            "parameter_values": dict(self.parameter_values),
            "cost_values": dict(self.cost_values),
            "simulator_semantics_version": self.simulator_semantics_version,
            "code_commit": self.code_commit,
            "code_dirty": self.code_dirty,
            "fallback_count": self.fallback_count,
            "end_of_data_count": self.end_of_data_count,
            "strategy_window_bars": self.strategy_window_bars,
            "context_window_bars": self.context_window_bars,
            "allowed_gaps": [gap.to_dict() for gap in self.allowed_gaps],
            "split_role": self.split_role,
            "split_start_utc": self.split_start_utc.isoformat(),
            "split_end_utc": self.split_end_utc.isoformat(),
        }


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
# Typed values from the registry, the cost model and the engine run summary.
# --------------------------------------------------------------------------- #


def _value_text(value: object, field_name: str) -> str:
    """Canonical text of one registry or cost value (Decimal via D047, never a float)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return canonical_decimal_text(value)
    if isinstance(value, (int, str)):
        return str(value)
    raise IncompleteExperimentRecord(
        f"{field_name} has a value of unsupported type {type(value).__name__}"
    )


def parameter_value_pairs(params: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """The full registry parameters as sorted `(key, canonical text)` pairs."""
    return tuple((key, _value_text(params[key], f"parameter {key}")) for key in sorted(params))


def cost_value_pairs(cost_model: CostModel) -> tuple[tuple[str, str], ...]:
    """The cost model's keys as sorted `(key, canonical text)` pairs.

    The seven `COST_KEYS` always appear; each optional key (`exit_slippage_rate`,
    `funding_convention`) appears when the model carries it, exactly the key set its hash covers.
    """
    keys = (*COST_KEYS, *(k for k in OPTIONAL_COST_KEYS if getattr(cost_model, k) is not None))
    return tuple(
        (key, _value_text(getattr(cost_model, key), f"cost {key}")) for key in sorted(keys)
    )


def _summary_value(run_summary: Mapping[str, Any], key: str) -> Any:
    if key not in run_summary:
        raise IncompleteExperimentRecord(f"run_summary is missing the key {key!r}")
    return run_summary[key]


def _parse_summary_utc(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise IncompleteExperimentRecord(f"run_summary {name} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise IncompleteExperimentRecord(f"run_summary {name} is not a valid datetime") from None
    _incomplete_if_not_utc(parsed, f"run_summary {name}")
    return parsed


def _summary_gaps(run_summary: Mapping[str, Any]) -> tuple[RecordedGap, ...]:
    raw = _summary_value(run_summary, "allowed_gaps_used")
    if not isinstance(raw, list):
        raise IncompleteExperimentRecord("run_summary allowed_gaps_used must be a list")
    gaps: list[RecordedGap] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise IncompleteExperimentRecord(f"allowed_gaps_used[{index}] must be an object")
        label = f"allowed_gaps_used[{index}]"
        gaps.append(
            RecordedGap(
                series=_summary_value(item, "series"),
                symbol=_summary_value(item, "symbol"),
                start_utc=_parse_summary_utc(_summary_value(item, "start_utc"), label),
                end_utc=_parse_summary_utc(_summary_value(item, "end_utc"), label),
            )
        )
    return tuple(sorted(gaps, key=RecordedGap.sort_key))


def _summary_no_trade_counts(run_summary: Mapping[str, Any]) -> tuple[tuple[str, int], ...]:
    raw = _summary_value(run_summary, "no_trade_counts")
    if not isinstance(raw, Mapping) or not all(isinstance(key, str) for key in raw):
        raise IncompleteExperimentRecord("run_summary no_trade_counts must map reason to count")
    return tuple(sorted(raw.items()))


def _typed_fields_from_summary(run_summary: Mapping[str, Any]) -> dict[str, Any]:
    """The record fields an engine `run_summary` determines (counts, windows, tie-break, gaps)."""
    return {
        "no_trade_counts": _summary_no_trade_counts(run_summary),
        "intrabar_tie_break": _summary_value(run_summary, "intrabar_tie_break"),
        "timeframe": _summary_value(run_summary, "timeframe"),
        "context_timeframe": _summary_value(run_summary, "context_timeframe"),
        "simulator_semantics_version": _summary_value(run_summary, "simulator_semantics_version"),
        "fallback_count": _summary_value(run_summary, "fallback_count"),
        "end_of_data_count": _summary_value(run_summary, "end_of_data_count"),
        "strategy_window_bars": _summary_value(run_summary, "strategy_window_bars"),
        "context_window_bars": _summary_value(run_summary, "context_window_bars"),
        "allowed_gaps": _summary_gaps(run_summary),
    }


def _summary_window(run_summary: Mapping[str, Any]) -> tuple[datetime, datetime]:
    window = _summary_value(run_summary, "data_window")
    if not isinstance(window, Mapping):
        raise IncompleteExperimentRecord("run_summary data_window must be an object")
    return (
        _parse_summary_utc(_summary_value(window, "start_utc"), "data_window start_utc"),
        _parse_summary_utc(_summary_value(window, "end_utc"), "data_window end_utc"),
    )


# --------------------------------------------------------------------------- #
# assemble — build an ExperimentRecord from identity inputs and an engine run.
# --------------------------------------------------------------------------- #


def _check_run_identity(
    run_identity: Mapping[str, Any],
    *,
    strategy_version: str,
    parameter_set: Any,
    cost_model: CostModel,
    universe: Sequence[str],
) -> None:
    """Refuse an engine run that is not the one the record's identity inputs describe (CR-02)."""
    if parameter_set.strategy_version != strategy_version:
        raise IncompleteExperimentRecord(
            f"strategy_version {strategy_version!r} is not the parameter set's "
            f"strategy_version {parameter_set.strategy_version!r}"
        )
    if not isinstance(run_identity, Mapping):
        raise IncompleteExperimentRecord("run_identity must be the engine output mapping")
    expected: tuple[tuple[str, Any], ...] = (
        ("strategy_version", strategy_version),
        ("parameter_set_hash", parameter_set.parameter_set_hash),
        ("cost_model_hash", cost_model.cost_model_hash),
    )
    for key, value in expected:
        if key not in run_identity:
            raise IncompleteExperimentRecord(f"run_identity is missing {key!r}")
        if run_identity[key] != value:
            raise IncompleteExperimentRecord(
                f"run_identity {key} {run_identity[key]!r} is not the record's {value!r}: "
                "the run is not the one this record attests"
            )
    symbols = run_identity.get("symbols")
    if not isinstance(symbols, (list, tuple)) or any(not isinstance(s, str) for s in symbols):
        raise IncompleteExperimentRecord("run_identity symbols must be a list of symbol strings")
    if sorted(symbols) != sorted(universe):
        raise IncompleteExperimentRecord(
            f"run_identity symbols {sorted(symbols)!r} are not the record universe "
            f"{sorted(universe)!r}"
        )


def assemble(
    *,
    parameter_set_id: str,
    strategy_id: str,
    strategy_version: str,
    data_snapshot_id: str,
    code_version: CodeVersion,
    cost_model: CostModel,
    time_range_start_utc: datetime,
    time_range_end_utc: datetime,
    universe: Sequence[str],
    run_type: str,
    run_summary: Mapping[str, Any],
    run_identity: Mapping[str, Any],
    split_role: str,
    split_start_utc: datetime,
    split_end_utc: datetime,
    notes: str = "",
    result_summary_json: str = "{}",
) -> ExperimentRecord:
    """Assemble a typed ExperimentRecord from the identity inputs and an engine run summary.

    Per D-03: the parameter set is loaded from the registry (fail closed
    on `UnregisteredParameterSet`). The `experiment_id` is SHA256 over
    the canonical payload of the six identity fields plus time range,
    universe hash, `simulator_semantics_version`, `split_role` and the split boundaries
    (D-02, D-22).

    `run_summary` is the `run_summary` of an engine output. A run is refused (with
    `IncompleteExperimentRecord` naming the cause) when its `plan_source` is not
    STRATEGY (a scripted run is never evidence), when its semantics version or tie-break
    differ from the code constants, when its `data_window` is not the record's time
    range, when its `dataset_id` is absent or is not `data_snapshot_id`, or when the cost
    model lacks the funding convention. Holdout-once enforcement is Phase 26 (F-960).

    `run_identity` is the engine output (or any mapping with its `strategy_version`,
    `parameter_set_hash`, `cost_model_hash` and `symbols` keys). The record attests those
    identity inputs, so each is compared with the record's own (CR-02): the registry set's
    strategy version must be `strategy_version`, the run's parameter-set and cost-model
    hashes must be the record's, and the run's symbols must be the record's `universe`.

    Raises:
        UnregisteredParameterSet: parameter_set_id not in registry.
        IncompleteExperimentRecord: any identity or typed field missing, malformed or refused.
        CostModelBindingMismatch: caller-supplied cost_model hash differs
            from the registry-derived slice (assembly refusal, D-03).
        KeyError: registry set lacks one of the seven COST_KEYS
            (pre-7-key sets such as baseline-v2; fail closed, never
            translated — D-02/D-05).
    """
    # Load the parameter set from the registry (fail closed).
    parameter_set = load_parameter_set(strategy_id, parameter_set_id)

    # D-01 gate: registry cost slice is the authority (D-02). Sits
    # strictly before identity_payload so no record exists on the
    # mismatch path; never appears in the payload (D-04 byte-stability).
    assert_cost_model_binds_registry(parameter_set, cost_model)

    if not isinstance(code_version, CodeVersion):
        raise IncompleteExperimentRecord("code_version must be a CodeVersion (commit and dirty)")
    if cost_model.funding_convention != FUNDING_CONVENTION:
        raise IncompleteExperimentRecord(
            f"the cost model lacks funding_convention {FUNDING_CONVENTION!r}: a record over a "
            f"model that predates it would hide the funding sign convention "
            f"(got {cost_model.funding_convention!r})"
        )
    plan_source = _summary_value(run_summary, "plan_source")
    if plan_source != PLAN_SOURCE_STRATEGY:
        raise IncompleteExperimentRecord(
            f"run_summary plan_source must be {PLAN_SOURCE_STRATEGY!r}, got {plan_source!r}: "
            "a scripted run is not experiment evidence"
        )
    typed = _typed_fields_from_summary(run_summary)
    for key, constant in (
        ("simulator_semantics_version", SIMULATOR_SEMANTICS_VERSION),
        ("intrabar_tie_break", TIE_BREAK),
    ):
        if typed[key] != constant:
            raise IncompleteExperimentRecord(
                f"run_summary {key} {typed[key]!r} differs from the code constant {constant!r}"
            )
    if _summary_window(run_summary) != (time_range_start_utc, time_range_end_utc):
        raise IncompleteExperimentRecord(
            "run_summary data_window is not the record time range "
            f"({time_range_start_utc.isoformat()} to {time_range_end_utc.isoformat()})"
        )
    dataset_id = _summary_value(run_summary, "dataset_id")
    if dataset_id is None:
        raise IncompleteExperimentRecord(
            "run_summary dataset_id is missing: a run over data that carries no dataset id "
            "cannot be bound to data_snapshot_id (WR-03)"
        )
    if dataset_id != data_snapshot_id:
        raise IncompleteExperimentRecord(
            f"run_summary dataset_id {dataset_id!r} is not data_snapshot_id {data_snapshot_id!r}"
        )

    _check_run_identity(
        run_identity,
        strategy_version=strategy_version,
        parameter_set=parameter_set,
        cost_model=cost_model,
        universe=universe,
    )

    # Build the universe hash (sorted for order-stability).
    universe_hash = _universe_hash(universe)

    # Build the experiment_id via sha256_hex over the identity payload.
    # CR-06: run_type and strategy_id are identity — a CANDIDATE and a
    # BASELINE_NO_TRADE over identical inputs (or two strategies sharing
    # a version string) must never share an experiment_id.
    # D-02/D-22: the semantics version and the split are identity too, so a record
    # produced by the v1 simulator, or on another split, can never compare equal.
    identity_payload = {
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "parameter_set_hash": parameter_set.parameter_set_hash,
        "data_snapshot_id": data_snapshot_id,
        "code_version": code_version.text,
        "cost_model_hash": cost_model.cost_model_hash,
        "run_type": run_type,
        "time_range_start_utc": time_range_start_utc,
        "time_range_end_utc": time_range_end_utc,
        "universe_hash": universe_hash,
        "simulator_semantics_version": SIMULATOR_SEMANTICS_VERSION,
        "split_role": split_role,
        "split_start_utc": split_start_utc,
        "split_end_utc": split_end_utc,
    }
    experiment_id = sha256_hex(identity_payload)

    return ExperimentRecord(
        experiment_id=experiment_id,
        strategy_version=strategy_version,
        parameter_set_id=parameter_set_id,
        parameter_set_hash=parameter_set.parameter_set_hash,
        data_snapshot_id=data_snapshot_id,
        code_version=code_version.text,
        cost_model_hash=cost_model.cost_model_hash,
        time_range_start_utc=time_range_start_utc,
        time_range_end_utc=time_range_end_utc,
        universe_hash=universe_hash,
        run_type=run_type,
        result_summary_json=result_summary_json,
        notes=notes,
        parameter_values=parameter_value_pairs(parameter_set.params),
        cost_values=cost_value_pairs(cost_model),
        code_commit=code_version.commit,
        code_dirty=code_version.dirty,
        split_role=split_role,
        split_start_utc=split_start_utc,
        split_end_utc=split_end_utc,
        **typed,
    )


# --------------------------------------------------------------------------- #
# reproduce — re-run simulator.run with the recorded tuple.
# --------------------------------------------------------------------------- #

_DECIMAL_TRADE_FIELDS: tuple[str, ...] = (
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
    "planned_quantity",
    "tp1_quantity",
    "tp1_price",
)

_DATETIME_TRADE_FIELDS: tuple[str, ...] = (
    "entry_time_utc",
    "exit_time_utc",
    "signal_close_utc",
    "tp1_time_utc",
    "resolved_at_utc",
)

_INT_TRADE_FIELDS: tuple[str, ...] = ("touch_no_fill_count", "funding_event_count")

_BOOL_TRADE_FIELDS: tuple[str, ...] = (
    "fallback_applied",
    "gap_through_stop",
    "constraints_extrapolated",
)

_OPTIONAL_STR_TRADE_FIELDS: tuple[str, ...] = ("coverage_note", "regime")


def _coerce_trade_decimal(value: object, field_name: str) -> Decimal | None:
    """Parse a trade-dict money field back to Decimal (fail-closed)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ExperimentReproducibilityBroken(
            f"trade field {field_name!r} must be Decimal/str/int/None, got bool"
        )
    if isinstance(value, (str, int)):
        return Decimal(str(value))
    if isinstance(value, float):
        # Shortest-repr round-trip keeps "1.1" exact; raw binary noise
        # never enters (matches the simulator WR-14 boundary rule).
        return Decimal(str(value))
    raise ExperimentReproducibilityBroken(
        f"trade field {field_name!r} has unparseable type {type(value).__name__}"
    )


def _coerce_trade_datetime(value: object, field_name: str) -> datetime | None:
    """Parse a trade-dict timestamp back to UTC-aware datetime (fail-closed)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        _require_utc_aware(value, field_name)
        return value
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        _require_utc_aware(parsed, field_name)
        return parsed
    raise ExperimentReproducibilityBroken(
        f"trade field {field_name!r} has unparseable type {type(value).__name__}"
    )


def _coerce_trade_int(value: object, field_name: str) -> int:
    """A counter field must already be an int (never a bool, never text)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExperimentReproducibilityBroken(
            f"trade field {field_name!r} must be an int, got {type(value).__name__}"
        )
    return value


def _coerce_trade_bool(value: object, field_name: str) -> bool:
    """A flag field must already be a bool (never 0/1, never text)."""
    if not isinstance(value, bool):
        raise ExperimentReproducibilityBroken(
            f"trade field {field_name!r} must be a bool, got {type(value).__name__}"
        )
    return value


def _coerce_trade_optional_str(value: object, field_name: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ExperimentReproducibilityBroken(
            f"trade field {field_name!r} must be a string or null, got {type(value).__name__}"
        )
    return value


def _trade_from_dict(t: dict[str, Any]) -> TradeRecord:
    """Rebuild a TradeRecord from `to_dict()` output with typed fields, then validate it.

    CR-03: `TradeRecord(**t)` left Decimals stringified and datetimes
    as ISO strings, corrupting the typed record. Every money/timestamp
    field is parsed back before construction, including the v2 trailing fields
    (`signal_close_utc`, `planned_quantity`, the TP1 leg, `resolved_at_utc`); counters
    and flags are checked strictly. The rebuilt record goes through
    `validate_trade_record` (D-23), so a v1-shaped dict (an unknown `entry_kind`, a fill
    without its signal close) raises `TradeRecordInvariantError` instead of loading.
    """
    data = dict(t)
    for fname in _DECIMAL_TRADE_FIELDS:
        data[fname] = _coerce_trade_decimal(data.get(fname), fname)
    for fname in _DATETIME_TRADE_FIELDS:
        data[fname] = _coerce_trade_datetime(data.get(fname), fname)
    for fname in _INT_TRADE_FIELDS:
        if fname in data:
            data[fname] = _coerce_trade_int(data[fname], fname)
    for fname in _BOOL_TRADE_FIELDS:
        if fname in data:
            data[fname] = _coerce_trade_bool(data[fname], fname)
    for fname in _OPTIONAL_STR_TRADE_FIELDS:
        if fname in data:
            data[fname] = _coerce_trade_optional_str(data[fname], fname)
    trade = TradeRecord(**data)
    validate_trade_record(trade, strict=True)
    return trade


def _check_inputs_bind_record(record: ExperimentRecord, simulator_inputs: dict[str, Any]) -> None:
    """Fail closed unless the inputs reproduce the record's identity.

    CR-03: reproduce must run the RECORDED tuple, not whatever dict it
    is handed. The registry parameter set (hash), the fixture
    strategy_version, the cost model hash and the data window (D-22: the
    record's time range) must all match the record; otherwise raise
    ExperimentReproducibilityBroken.
    """
    mismatches: list[str] = []
    if simulator_inputs.get("parameter_set_id") != record.parameter_set_id:
        mismatches.append(
            f"parameter_set_id {simulator_inputs.get('parameter_set_id')!r} "
            f"!= recorded {record.parameter_set_id!r}"
        )
    if simulator_inputs.get("strategy_version") != record.strategy_version:
        mismatches.append(
            f"strategy_version {simulator_inputs.get('strategy_version')!r} "
            f"!= recorded {record.strategy_version!r}"
        )
    missing = [
        key
        for key in ("strategy_id", "parameter_set_id", "cost_model", "symbols")
        if key not in simulator_inputs
    ]
    if missing:
        raise ExperimentReproducibilityBroken(
            "simulator_inputs are missing " + ", ".join(repr(key) for key in missing)
        )
    parameter_set = load_parameter_set(
        simulator_inputs["strategy_id"], simulator_inputs["parameter_set_id"]
    )
    if parameter_set.parameter_set_hash != record.parameter_set_hash:
        mismatches.append("parameter_set_hash != recorded parameter_set_hash")
    cost_model = build_cost_model(simulator_inputs["cost_model"])
    if cost_model.cost_model_hash != record.cost_model_hash:
        mismatches.append("cost_model_hash != recorded cost_model_hash")
    symbols = simulator_inputs["symbols"]
    if (
        not isinstance(symbols, (list, tuple))
        or not all(isinstance(symbol, str) for symbol in symbols)
        or _universe_hash(symbols) != record.universe_hash
    ):
        mismatches.append("symbols != recorded universe_hash")
    window = simulator_inputs.get("data_window")
    if not isinstance(window, Mapping):
        mismatches.append("data_window is missing from the simulator inputs")
    else:
        try:
            bounds = (
                datetime.fromisoformat(str(window.get("start_utc"))),
                datetime.fromisoformat(str(window.get("end_utc"))),
            )
        except ValueError:
            bounds = None
        if bounds != (record.time_range_start_utc, record.time_range_end_utc):
            mismatches.append("data_window != recorded time range")
    if mismatches:
        raise ExperimentReproducibilityBroken(
            "simulator_inputs do not bind to the recorded experiment: " + "; ".join(mismatches)
        )


def _check_run_binds_record(record: ExperimentRecord, run_summary: Mapping[str, Any]) -> None:
    """Fail closed unless the re-run's summary agrees with every typed field of the record.

    The semantics version, tie-break, counts, windows, timeframes and allowed gaps the
    engine reports now must equal what the record carries; a drifted engine, a changed
    data set or a scripted run raises `ExperimentReproducibilityBroken` (D-22, D-02).
    """
    mismatches: list[str] = []
    try:
        typed = _typed_fields_from_summary(run_summary)
        window = _summary_window(run_summary)
        plan_source = _summary_value(run_summary, "plan_source")
        dataset_id = _summary_value(run_summary, "dataset_id")
    except IncompleteExperimentRecord as exc:
        raise ExperimentReproducibilityBroken(f"re-run summary is unusable: {exc}") from None
    if plan_source != PLAN_SOURCE_STRATEGY:
        mismatches.append(f"plan_source {plan_source!r} is not {PLAN_SOURCE_STRATEGY!r}")
    for name, value in typed.items():
        recorded = getattr(record, name)
        if value != recorded:
            mismatches.append(f"{name} {value!r} != recorded {recorded!r}")
    if window != (record.time_range_start_utc, record.time_range_end_utc):
        mismatches.append("data_window != recorded time range")
    if dataset_id is None or dataset_id != record.data_snapshot_id:
        mismatches.append(
            f"dataset_id {dataset_id!r} != recorded data_snapshot_id "
            "(a run without a dataset id is not bound to the recorded data)"
        )
    if mismatches:
        raise ExperimentReproducibilityBroken(
            "the re-run does not match the recorded experiment: " + "; ".join(mismatches)
        )


def reproduce(
    record: ExperimentRecord,
    *,
    simulator_inputs: dict[str, Any],
) -> list[TradeRecord]:
    """Re-run the simulator with the recorded tuple.

    Per D-03: reproduction = re-running the recorded tuple
    yields byte-identical trade lists. Inputs are checked against the
    record's identity first (fail closed on mismatch), and the re-run's summary must
    agree with the record's typed fields; rebuilt trades carry typed Decimal/datetime
    fields and are validated (D-23). Empty `simulator_inputs` raise
    `ExperimentReproducibilityBroken`: there is nothing to replay, so reporting the
    experiment as reproducible would check nothing (WR-03).
    """
    if not simulator_inputs:
        raise ExperimentReproducibilityBroken(
            "simulator_inputs are empty: nothing can be reproduced against the record"
        )
    _check_inputs_bind_record(record, simulator_inputs)
    result = simulator_run(simulator_inputs)
    _check_run_binds_record(record, result["run_summary"])
    return [_trade_from_dict(t) for t in result["trades"]]


# --------------------------------------------------------------------------- #
# verify_experiment — runtime tripwire for reproducibility.
# --------------------------------------------------------------------------- #


def trades_digest(trades: Sequence[Any]) -> str:
    """The digest `verify_experiment` compares: SHA256 over the trades in the given order.

    Engine order is `(signal_close_utc or data start, symbol, trade_id)`; a caller holding
    the trades in another order sorts them that way before digesting.
    """
    return sha256_hex({"trades": [t.to_dict() for t in trades]})


def stored_trades_digest(record: ExperimentRecord) -> str | None:
    """The persisted `trades_digest` of `record`, or None when it carries none."""
    return _stored_trades_digest(record)


def _stored_trades_digest(record: ExperimentRecord) -> str | None:
    """Return the persisted trades digest, if the record carries one.

    `assemble()` cannot know the trade list (it never runs the
    simulator), so the digest is optional: callers that persist
    `result_summary_json={"trades_digest": ...}` after a run get
    cross-version drift detection in `verify_experiment`.
    """
    import json

    try:
        summary = json.loads(record.result_summary_json)
    except (ValueError, TypeError):
        return None
    digest = summary.get("trades_digest") if isinstance(summary, dict) else None
    return digest if isinstance(digest, str) and digest != "" else None


def verify_experiment(
    record: ExperimentRecord,
    *,
    simulator_inputs: dict[str, Any],
) -> None:
    """Return None when reproducible; raise ExperimentReproducibilityBroken on drift.

    Per D-03: verify_experiment is the runtime tripwire for
    reproducibility. Inputs are bound to the record (fail closed on
    mismatch, including the data window and the semantics version of the re-run); the
    reproduce digest is compared against the record's stored `trades_digest` when
    present (cross-version drift), and two reproduce() runs must always agree
    (determinism).
    """
    trades_a = reproduce(record, simulator_inputs=simulator_inputs)
    digest_a = trades_digest(trades_a)
    stored = _stored_trades_digest(record)
    if stored is not None and digest_a != stored:
        raise ExperimentReproducibilityBroken(
            f"reproduce digest {digest_a} != recorded trades_digest {stored}"
        )
    trades_b = reproduce(record, simulator_inputs=simulator_inputs)
    digest_b = trades_digest(trades_b)
    if digest_a != digest_b:
        raise ExperimentReproducibilityBroken(f"reproduce digests differ: {digest_a} != {digest_b}")
    return None


# --------------------------------------------------------------------------- #
# Baseline runners — same engine, degenerated parameter sets.
# --------------------------------------------------------------------------- #


def _require_baseline_params(
    case_input: dict[str, Any],
    *,
    kind: str,
) -> None:
    """Fail closed unless the case references a degenerated baseline set.

    CR-07: the baseline docstrings promise degenerated parameters, but
    the bodies never checked. Passing candidate params to
    `baseline_no_trade` would return filled trades mislabeled as a
    baseline. The registry set behind the case must satisfy the
    kind-specific bound: no-trade needs `minimum_rr >= 100` (every plan
    fails the RR gate); simple-trend needs `minimum_rr < 2` (looser
    than the candidate gate).
    """
    parameter_set = load_parameter_set(case_input["strategy_id"], case_input["parameter_set_id"])
    minimum_rr = Decimal(str(parameter_set.params["minimum_rr"]))
    if kind == "no_trade":
        if minimum_rr < Decimal("100"):
            raise ValueError(
                f"baseline_no_trade requires minimum_rr >= 100, got {minimum_rr} "
                f"for {parameter_set.strategy_id}/{parameter_set.parameter_set_id}"
            )
    elif kind == "simple_trend":
        if minimum_rr >= Decimal("2"):
            raise ValueError(
                f"baseline_simple_trend requires minimum_rr < 2, got {minimum_rr} "
                f"for {parameter_set.strategy_id}/{parameter_set.parameter_set_id}"
            )
    else:  # pragma: no cover — internal misuse, never user input.
        raise ValueError(f"unknown baseline kind {kind!r}")


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
    _require_baseline_params(case_input, kind="no_trade")
    result = simulator_run(case_input)
    trades = [_trade_from_dict(t) for t in result["trades"]]
    return _filled_trades(trades)


def baseline_simple_trend(case_input: dict[str, Any]) -> list[TradeRecord]:
    """Run the simple-trend baseline (looser minimum_rr + single-condition trend filter).

    Per BACKTEST_SPEC §9: the simple-trend baseline uses a looser
    `minimum_rr` and a single-condition trend filter so the simulator
    emits a deterministic single-direction trade list.

    The case_input must reference `parameter_set_id="baseline-simple-trend-v1"`
    (or equivalent with looser config).
    """
    _require_baseline_params(case_input, kind="simple_trend")
    result = simulator_run(case_input)
    trades = [_trade_from_dict(t) for t in result["trades"]]
    return _filled_trades(trades)


__all__ = [
    "SPLIT_ROLES",
    "CodeVersion",
    "ExperimentRecord",
    "ExperimentReproducibilityBroken",
    "IncompleteExperimentRecord",
    "RecordedGap",
    "assemble",
    "baseline_no_trade",
    "baseline_simple_trend",
    "cost_value_pairs",
    "parameter_value_pairs",
    "reproduce",
    "stored_trades_digest",
    "trades_digest",
    "verify_experiment",
]
