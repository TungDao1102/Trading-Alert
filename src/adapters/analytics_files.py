"""Edge adapter: repo/file inputs for the Phase 10 analytics core (plan 10-09, D-01, D-03).

All filesystem access for the analytics phase lives here so the pure `src/analytics`
modules stay free of I/O. The family registry facts are derived from the real repo (the
`params/<family>/` directories, the registry loader and the 7-slot family sheets), never
from a free-text flag: independence is decided later by `independent_family_ids` over the
facts this module extracts. Human decision records and evidence files are loaded
fail-closed with typed errors that name the offending key and never echo file contents.

No network, no exchange access, no database, no float.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from src.analytics.family import (
    FamilyEvidence,
    FamilyStatus,
    is_baseline_parameter_set_id,
)
from src.analytics.gates import FamilyGateFacts
from src.analytics.killgate import ResetRecord
from src.analytics.killgate_guard import EvidenceClass
from src.analytics.types import OutcomeContext
from src.backtest.experiment import (
    ExperimentRecord,
    RecordedGap,
    _trade_from_dict,
    stored_trades_digest,
    trades_digest,
)
from src.backtest.simulator import TradeRecord
from src.domain.registry import REGISTRY_ROOT, load_parameter_set
from src.paper.attribution import AttributionKind
from src.paper.journal import PaperRecord

__all__ = [
    "REPORTS_ROOT",
    "BacktestEvidence",
    "DecisionsFile",
    "DecisionsFileError",
    "EvidenceFile",
    "EvidenceFileError",
    "ExperimentFlags",
    "FamilyDecision",
    "FamilyScan",
    "PathConfinementError",
    "RecordedTerminal",
    "confine_output_dir",
    "load_decisions_file",
    "load_evidence_file",
    "load_universe_file",
    "read_protocol_text",
    "scan_family_facts",
]

REPORTS_ROOT = Path("data") / "reports"

_PROTOCOL_RELATIVE = Path("docs") / "research" / "RESEARCH_PROTOCOL.md"
_SLOT_HEADING = re.compile(r"^## ([1-7])\.", re.MULTILINE)
_CANDIDATE_RUN_TYPE = "CANDIDATE"

EVIDENCE_SCHEMA = "analytics-evidence/2"
DECISIONS_SCHEMA = "kill-gate-decisions/1"
_SYMBOL = re.compile(r"[A-Z0-9]{5,20}")
_TRADE_DECIMAL_FIELDS = (
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
_TRADE_DATETIME_FIELDS = (
    "entry_time_utc",
    "exit_time_utc",
    "signal_close_utc",
    "tp1_time_utc",
    "resolved_at_utc",
)
# The `experiment` object of an `analytics-evidence/2` file: a closed key set. The plain
# identity fields come first, then the typed fields of plan 14-15 (D-22).
_EXPERIMENT_PLAIN_KEYS = (
    "experiment_id",
    "strategy_version",
    "parameter_set_id",
    "parameter_set_hash",
    "data_snapshot_id",
    "code_version",
    "cost_model_hash",
    "universe_hash",
    "run_type",
    "result_summary_json",
    "notes",
    "intrabar_tie_break",
    "timeframe",
    "context_timeframe",
    "simulator_semantics_version",
    "code_commit",
    "code_dirty",
    "fallback_count",
    "end_of_data_count",
    "strategy_window_bars",
    "context_window_bars",
    "split_role",
)
_EXPERIMENT_DATETIME_KEYS = (
    "time_range_start_utc",
    "time_range_end_utc",
    "split_start_utc",
    "split_end_utc",
)
_EXPERIMENT_MAPPING_KEYS = ("no_trade_counts", "parameter_values", "cost_values")
_EXPERIMENT_KEYS = (
    *_EXPERIMENT_PLAIN_KEYS,
    *_EXPERIMENT_DATETIME_KEYS,
    *_EXPERIMENT_MAPPING_KEYS,
    "allowed_gaps",
)
_GAP_KEYS = ("series", "symbol", "start_utc", "end_utc")
_PAPER_DATETIME_FIELDS = (
    "signal_detected_at_utc",
    "approval_acted_at_utc",
    "order_submitted_at_utc",
    "fill_time_utc",
)
# Plan 16-35 (D-15): optional SHADOW keys of a paper record. Absent means None / False, so an
# evidence file written before Phase 16 loads exactly as before; any other unknown key is still
# refused by `PaperRecord(**fields)`.
_PAPER_OPTIONAL_DATETIME_FIELDS = (
    "approval_requested_at_utc",
    "confirm_requested_at_utc",
    "confirmed_at_utc",
)
_FAMILY_DECISION_KEYS = (
    "family_id",
    "status",
    "decision_ref",
    "decided_at_utc",
    "development_experiment_ids",
    "validation_experiment_ids",
)
_TERMINAL_KEYS = ("state", "decision_ref", "recorded_at_utc", "families_at_record")


class EvidenceFileError(ValueError):
    """An evidence / universe input file is malformed (fail closed, names the key only)."""


class DecisionsFileError(ValueError):
    """The human decision record is malformed (fail closed, names the key only)."""


class PathConfinementError(ValueError):
    """A requested output directory resolves outside the reports root."""


@dataclass(frozen=True)
class FamilyDecision:
    """One recorded human family decision (status is never derived from data)."""

    family_id: str
    status: FamilyStatus
    decision_ref: str | None
    decided_at_utc: datetime | None
    development_experiment_ids: tuple[str, ...]
    validation_experiment_ids: tuple[str, ...]


@dataclass(frozen=True)
class RecordedTerminal:
    """The committed mirror of a recorded INSUFFICIENT_EDGE outcome (D-03).

    It feeds the CI registration tripwire and, as a prior terminal evaluation at
    `recorded_at_utc`, the sticky kill-gate state of every report run, so a run without a
    database (or with a journal that lost the event) still cannot clear the terminal.
    """

    state: str
    decision_ref: str
    recorded_at_utc: datetime
    families_at_record: tuple[str, ...]


@dataclass(frozen=True)
class DecisionsFile:
    """Typed view of `docs/research/kill_gate_decisions.json` (schema kill-gate-decisions/1)."""

    families: tuple[FamilyDecision, ...]
    resets: tuple[ResetRecord, ...]
    recorded_terminal: RecordedTerminal | None


@dataclass(frozen=True)
class ExperimentFlags:
    """Recorded per-experiment facts that machine-derivable gates may read."""

    reproducibility_verified: bool | None
    has_uncertainty_report: bool
    baseline_summaries_present: bool


@dataclass(frozen=True)
class FamilyScan:
    """Result of scanning the real registry, family sheets, decisions and experiments."""

    families: tuple[FamilyEvidence, ...]
    gate_facts: tuple[tuple[str, FamilyGateFacts], ...]
    unknown_experiment_ids: tuple[str, ...]


def read_protocol_text(repo_root: Path) -> str:
    """Read the frozen research protocol as UTF-8 text (fixed path, no caller segments)."""
    return (repo_root / _PROTOCOL_RELATIVE).read_bytes().decode("utf-8")


def _family_ids() -> tuple[str, ...]:
    return tuple(
        sorted(
            child.name
            for child in REGISTRY_ROOT.iterdir()
            if child.is_dir() and not child.name.startswith((".", "_"))
        )
    )


def _candidate_hashes(family_id: str) -> tuple[str, ...]:
    """Sorted parameter-set hashes of every non-baseline set registered for the family."""
    stems = sorted(path.stem for path in (REGISTRY_ROOT / family_id).glob("*.toml"))
    hashes = [
        load_parameter_set(family_id, stem).parameter_set_hash
        for stem in stems
        if not is_baseline_parameter_set_id(stem)
    ]
    return tuple(sorted(hashes))


def _sheet_facts(sheets_root: Path, family_id: str) -> tuple[str | None, tuple[int, ...]]:
    """(sha256 hex of the sheet content, sorted unique 7-slot heading numbers).

    Line endings are normalized (CRLF to LF) before hashing so the digest equals the
    committed blob content on every checkout (git autocrlf on Windows rewrites the working
    copy); otherwise the sheet hash, and every evidence digest built on it, would differ
    across machines.
    """
    sheet = sheets_root / f"{family_id}.md"
    if not sheet.is_file():
        return None, ()
    raw = sheet.read_bytes().replace(b"\r\n", b"\n")
    text = raw.decode("utf-8", errors="replace")
    slots = sorted({int(match) for match in _SLOT_HEADING.findall(text)})
    return hashlib.sha256(raw).hexdigest(), tuple(slots)


def _combine_reproducibility(values: Sequence[bool | None]) -> bool | None:
    """None without any recorded verdict; False if any is False; True only if all True."""
    if not values:
        return None
    if any(value is False for value in values):
        return False
    if any(value is None for value in values):
        return None
    return True


def scan_family_facts(
    *,
    sheets_root: Path,
    decisions: DecisionsFile,
    experiments: Sequence[ExperimentRecord],
    flags_by_experiment: Mapping[str, ExperimentFlags],
) -> FamilyScan:
    """Derive per-family kill-gate facts from the real repo (D-03, T-10-32).

    Families are the directory names under the registry root. Only CANDIDATE experiments
    whose parameter_set_hash equals one of a family's candidate hashes are mapped to that
    family; a CANDIDATE with any other hash is reported in `unknown_experiment_ids` and is
    never guessed onto a family. Baseline-run experiments are excluded without being listed.
    A recorded decision whose family_id matches no registry directory raises
    `DecisionsFileError` (fail closed: a human decision input is never dropped).
    """
    decision_by_family = {decision.family_id: decision for decision in decisions.families}
    candidate_hashes = {family_id: _candidate_hashes(family_id) for family_id in _family_ids()}
    # A recorded human decision whose family_id matches no registry directory (typo, rename)
    # must never vanish silently: that would hide a recorded pass or a recorded fail.
    unknown_decisions = sorted(set(decision_by_family) - set(candidate_hashes))
    if unknown_decisions:
        raise DecisionsFileError(
            f"families: decisions for unregistered family ids {unknown_decisions}"
        )
    hash_to_family: dict[str, str] = {}
    for family_id, hashes in candidate_hashes.items():
        for param_hash in hashes:
            hash_to_family.setdefault(param_hash, family_id)

    mapped: dict[str, list[ExperimentRecord]] = {family_id: [] for family_id in candidate_hashes}
    unknown: list[str] = []
    for experiment in sorted(experiments, key=lambda record: record.experiment_id):
        if experiment.run_type != _CANDIDATE_RUN_TYPE:
            continue
        owner = hash_to_family.get(experiment.parameter_set_hash)
        if owner is None:
            unknown.append(experiment.experiment_id)
        else:
            mapped[owner].append(experiment)

    families: list[FamilyEvidence] = []
    facts: list[tuple[str, FamilyGateFacts]] = []
    for family_id in sorted(candidate_hashes):
        sheet_sha256, slots = _sheet_facts(sheets_root, family_id)
        records = mapped[family_id]
        experiment_ids = tuple(sorted(record.experiment_id for record in records))
        decision = decision_by_family.get(family_id)
        if decision is None:
            evidence = FamilyEvidence(
                family_id=family_id,
                sheet_sha256=sheet_sha256,
                sheet_slots_present=slots,
                candidate_param_set_hashes=candidate_hashes[family_id],
                experiment_ids=experiment_ids,
                status=FamilyStatus.NOT_TESTED,
                decision_ref=None,
                decided_at_utc=None,
                development_experiment_ids=(),
                validation_experiment_ids=(),
            )
        else:
            evidence = FamilyEvidence(
                family_id=family_id,
                sheet_sha256=sheet_sha256,
                sheet_slots_present=slots,
                candidate_param_set_hashes=candidate_hashes[family_id],
                experiment_ids=experiment_ids,
                status=decision.status,
                decision_ref=decision.decision_ref,
                decided_at_utc=decision.decided_at_utc,
                development_experiment_ids=tuple(sorted(decision.development_experiment_ids)),
                validation_experiment_ids=tuple(sorted(decision.validation_experiment_ids)),
            )
        families.append(evidence)

        family_flags = [
            flags_by_experiment[record.experiment_id]
            for record in records
            if record.experiment_id in flags_by_experiment
        ]
        facts.append(
            (
                family_id,
                FamilyGateFacts(
                    cost_model_hash_present=any(
                        record.cost_model_hash.strip() != "" for record in records
                    ),
                    reproducibility_verified=_combine_reproducibility(
                        [flag.reproducibility_verified for flag in family_flags]
                    ),
                    uncertainty_report_present=any(
                        flag.has_uncertainty_report for flag in family_flags
                    ),
                    baseline_compared=any(flag.baseline_summaries_present for flag in family_flags),
                    tested=evidence.status is not FamilyStatus.NOT_TESTED,
                ),
            )
        )

    return FamilyScan(
        families=tuple(families),
        gate_facts=tuple(facts),
        unknown_experiment_ids=tuple(sorted(unknown)),
    )


# --------------------------------------------------------------------------- #
# Evidence file (schema analytics-evidence/2)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BacktestEvidence:
    """One backtest experiment with its trades, descriptive contexts and recorded flags."""

    experiment: ExperimentRecord
    trades: tuple[TradeRecord, ...]
    contexts: Mapping[str, OutcomeContext]
    flags: ExperimentFlags


@dataclass(frozen=True)
class EvidenceFile:
    """Typed view of an analytics evidence file."""

    backtest: tuple[BacktestEvidence, ...]
    paper: tuple[PaperRecord, ...]
    research_universe: tuple[str, ...]
    evidence_class: EvidenceClass = EvidenceClass.REAL


def _reject_constant(_name: str) -> Any:
    raise ValueError("non-finite JSON constant")


def _read_json(path: Path, error: type[ValueError], label: str) -> Any:
    """Load JSON from a file; unreadable or malformed input fails closed (no contents echoed)."""
    try:
        return json.loads(Path(path).read_bytes().decode("utf-8"), parse_constant=_reject_constant)
    except (OSError, ValueError):
        raise error(f"{label} file is unreadable or not valid JSON") from None


def _read_json_object(path: Path, error: type[ValueError], label: str) -> dict[str, Any]:
    loaded = _read_json(path, error, label)
    if not isinstance(loaded, dict):
        raise error(f"{label} file must contain a JSON object")
    return loaded


def _require_key(doc: Mapping[str, Any], key: str, error: type[ValueError], where: str) -> Any:
    if key not in doc:
        raise error(f"{where}: missing required key {key!r}")
    return doc[key]


def _require_str(value: Any, key: str, error: type[ValueError], where: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise error(f"{where}: {key!r} must be a non-empty string")
    return value


def _parse_utc(value: Any, key: str, error: type[ValueError], where: str) -> datetime:
    if not isinstance(value, str):
        raise error(f"{where}: {key!r} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise error(f"{where}: {key!r} is not a valid ISO-8601 datetime") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise error(f"{where}: {key!r} must be a UTC-aware datetime")
    return parsed


def _parse_decimal(value: Any, key: str, error: type[ValueError], where: str) -> Decimal:
    if not isinstance(value, str):
        raise error(f"{where}: {key!r} must be a decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise error(f"{where}: {key!r} is not a valid decimal") from None
    if not parsed.is_finite():
        raise error(f"{where}: {key!r} must be finite")
    return parsed


def _parse_symbols(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise EvidenceFileError(f"{where}: 'research_universe' must be a list of symbols")
    symbols: set[str] = set()
    for symbol in value:
        if not isinstance(symbol, str) or _SYMBOL.fullmatch(symbol) is None:
            raise EvidenceFileError(f"{where}: invalid symbol entry (expected [A-Z0-9]{{5,20}})")
        symbols.add(symbol)
    return tuple(sorted(symbols))


def _check_trade_fields(trade: Mapping[str, Any], where: str) -> None:
    """Validate every money / timestamp field before the shared trade parser runs."""
    for name in _TRADE_DECIMAL_FIELDS:
        raw = trade.get(name)
        if raw is not None:
            value = _parse_decimal(raw, name, EvidenceFileError, where)
            if name == "realized_risk" and value < 0:
                raise EvidenceFileError(f"{where}: 'realized_risk' must not be negative")
    for name in _TRADE_DATETIME_FIELDS:
        raw = trade.get(name)
        if raw is not None:
            _parse_utc(raw, name, EvidenceFileError, where)


def _load_trades(raw_trades: Any, where: str) -> tuple[TradeRecord, ...]:
    if not isinstance(raw_trades, list):
        raise EvidenceFileError(f"{where}: 'trades' must be a list")
    trades: list[TradeRecord] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_trades):
        item = f"{where}.trades[{index}]"
        if not isinstance(raw, dict):
            raise EvidenceFileError(f"{item}: must be an object")
        _check_trade_fields(raw, item)
        try:
            trade = _trade_from_dict(raw)
        except Exception as exc:  # foreign constructor: wrap, never echo values
            raise EvidenceFileError(
                f"{item}: invalid trade record ({type(exc).__name__})"
            ) from None
        if trade.trade_id in seen:
            raise EvidenceFileError(f"{where}: duplicate trade_id within one backtest entry")
        seen.add(trade.trade_id)
        trades.append(trade)
    return tuple(trades)


def _load_contexts(raw: Any, where: str) -> dict[str, OutcomeContext]:
    if not isinstance(raw, dict):
        raise EvidenceFileError(f"{where}: 'contexts' must be an object")
    contexts: dict[str, OutcomeContext] = {}
    for trade_id in sorted(raw):
        entry = raw[trade_id]
        item = f"{where}.contexts[{trade_id!r}]"
        if not isinstance(entry, dict):
            raise EvidenceFileError(f"{item}: must be an object")
        price = entry.get("intended_entry_price")
        for name in ("regime", "vol_regime"):
            if entry.get(name) is not None and not isinstance(entry[name], str):
                raise EvidenceFileError(f"{item}: {name!r} must be a string or null")
        contexts[trade_id] = OutcomeContext(
            intended_entry_price=(
                None
                if price is None
                else _parse_decimal(price, "intended_entry_price", EvidenceFileError, item)
            ),
            regime=entry.get("regime"),
            vol_regime=entry.get("vol_regime"),
        )
    return contexts


def _load_flags(raw: Any, where: str) -> ExperimentFlags:
    if not isinstance(raw, dict):
        raise EvidenceFileError(f"{where}: 'flags' must be an object")
    repro = raw.get("reproducibility_verified")
    if repro is not None and not isinstance(repro, bool):
        raise EvidenceFileError(f"{where}: 'reproducibility_verified' must be a bool or null")
    for name in ("has_uncertainty_report", "baseline_summaries_present"):
        if not isinstance(raw.get(name), bool):
            raise EvidenceFileError(f"{where}: {name!r} must be a bool")
    return ExperimentFlags(
        reproducibility_verified=repro,
        has_uncertainty_report=raw["has_uncertainty_report"],
        baseline_summaries_present=raw["baseline_summaries_present"],
    )


def _mapping_pairs(
    raw: Any, key: str, where: str, *, value_type: type
) -> tuple[tuple[str, Any], ...]:
    """A JSON object of `str -> value_type` as the sorted pair tuple the record stores."""
    if not isinstance(raw, dict):
        raise EvidenceFileError(f"{where}: {key!r} must be an object")
    for name, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, value_type):
            raise EvidenceFileError(f"{where}: {key!r} values must be {value_type.__name__}")
        if name == "":
            raise EvidenceFileError(f"{where}: {key!r} keys must be non-empty")
    return tuple(sorted(raw.items()))


def _load_gaps(raw: Any, where: str) -> tuple[RecordedGap, ...]:
    if not isinstance(raw, list):
        raise EvidenceFileError(f"{where}: 'allowed_gaps' must be a list")
    gaps: list[RecordedGap] = []
    for index, item in enumerate(raw):
        label = f"{where}.allowed_gaps[{index}]"
        if not isinstance(item, dict):
            raise EvidenceFileError(f"{label}: must be an object")
        for name in _GAP_KEYS:
            _require_key(item, name, EvidenceFileError, label)
        extra = sorted(set(item) - set(_GAP_KEYS))
        if extra:
            raise EvidenceFileError(f"{label}: unexpected key {extra[0]!r}")
        try:
            gaps.append(
                RecordedGap(
                    series=item["series"],
                    symbol=item["symbol"],
                    start_utc=_parse_utc(item["start_utc"], "start_utc", EvidenceFileError, label),
                    end_utc=_parse_utc(item["end_utc"], "end_utc", EvidenceFileError, label),
                )
            )
        except EvidenceFileError:
            raise
        except Exception as exc:  # IncompleteExperimentRecord: wrap, never echo values
            raise EvidenceFileError(f"{label}: invalid gap ({type(exc).__name__})") from None
    return tuple(sorted(gaps, key=RecordedGap.sort_key))


def _load_experiment(raw: Any, where: str) -> ExperimentRecord:
    """Build the typed `ExperimentRecord` of an `analytics-evidence/2` experiment object.

    Every key of the closed set must be present and no other key may appear; mappings
    become the sorted pair tuples the record stores, datetimes must be UTC-aware. The
    record validates the rest in `__post_init__` (D-22), and any failure is re-raised as
    `EvidenceFileError` without echoing values.
    """
    if not isinstance(raw, dict):
        raise EvidenceFileError(f"{where}: 'experiment' must be an object")
    label = f"{where}.experiment"
    for name in _EXPERIMENT_KEYS:
        _require_key(raw, name, EvidenceFileError, label)
    extra = sorted(set(raw) - set(_EXPERIMENT_KEYS))
    if extra:
        raise EvidenceFileError(f"{label}: unexpected key {extra[0]!r}")
    fields: dict[str, Any] = {name: raw[name] for name in _EXPERIMENT_PLAIN_KEYS}
    for name in _EXPERIMENT_DATETIME_KEYS:
        fields[name] = _parse_utc(raw[name], name, EvidenceFileError, label)
    fields["no_trade_counts"] = _mapping_pairs(
        raw["no_trade_counts"], "no_trade_counts", label, value_type=int
    )
    fields["parameter_values"] = _mapping_pairs(
        raw["parameter_values"], "parameter_values", label, value_type=str
    )
    fields["cost_values"] = _mapping_pairs(raw["cost_values"], "cost_values", label, value_type=str)
    fields["allowed_gaps"] = _load_gaps(raw["allowed_gaps"], label)
    try:
        return ExperimentRecord(**fields)
    except Exception as exc:  # IncompleteExperimentRecord / TypeError / ValueError
        raise EvidenceFileError(
            f"{where}: invalid experiment record ({type(exc).__name__})"
        ) from None


def _check_trades_belong_to_experiment(
    experiment: ExperimentRecord, trades: tuple[TradeRecord, ...], where: str
) -> None:
    """Refuse trades that are not the output of the experiment they are filed under (WR-02).

    Trades from another run could otherwise be paired with a candidate experiment and feed
    the kill gate: every trade must carry the experiment's strategy version and parameter
    set hash, sit inside its time range, and agree with its typed fallback / END_OF_DATA
    counts and (when stored) its `trades_digest`.
    """
    start = experiment.time_range_start_utc
    end = experiment.time_range_end_utc
    for trade in trades:
        label = f"{where}.trades[{trade.trade_id!r}]"
        if trade.strategy_version != experiment.strategy_version:
            raise EvidenceFileError(f"{label}: strategy_version is not the experiment's")
        if trade.parameter_set_hash != experiment.parameter_set_hash:
            raise EvidenceFileError(f"{label}: parameter_set_hash is not the experiment's")
        for name in ("signal_close_utc", "entry_time_utc", "exit_time_utc"):
            moment = getattr(trade, name)
            if moment is not None and not start <= moment <= end:
                raise EvidenceFileError(f"{label}: {name!r} lies outside the experiment time range")
    fallback = sum(trade.fallback_applied for trade in trades)
    if fallback != experiment.fallback_count:
        raise EvidenceFileError(
            f"{where}: {fallback} fallback trades but the experiment records "
            f"{experiment.fallback_count}"
        )
    end_of_data = sum(trade.exit_kind == "END_OF_DATA" for trade in trades)
    if end_of_data != experiment.end_of_data_count:
        raise EvidenceFileError(
            f"{where}: {end_of_data} END_OF_DATA trades but the experiment records "
            f"{experiment.end_of_data_count}"
        )
    stored = stored_trades_digest(experiment)
    if stored is not None:
        ordered = sorted(trades, key=lambda t: (t.signal_close_utc or start, t.symbol, t.trade_id))
        if trades_digest(ordered) != stored:
            raise EvidenceFileError(f"{where}: trades do not match the experiment trades_digest")


def _load_backtest_entry(raw: Any, index: int) -> BacktestEvidence:
    where = f"backtest[{index}]"
    if not isinstance(raw, dict):
        raise EvidenceFileError(f"{where}: must be an object")
    experiment = _load_experiment(_require_key(raw, "experiment", EvidenceFileError, where), where)
    trades = _load_trades(_require_key(raw, "trades", EvidenceFileError, where), where)
    _check_trades_belong_to_experiment(experiment, trades, where)
    return BacktestEvidence(
        experiment=experiment,
        trades=trades,
        contexts=_load_contexts(_require_key(raw, "contexts", EvidenceFileError, where), where),
        flags=_load_flags(_require_key(raw, "flags", EvidenceFileError, where), where),
    )


def _load_paper_record(raw: Any, index: int) -> PaperRecord:
    where = f"paper[{index}]"
    if not isinstance(raw, dict):
        raise EvidenceFileError(f"{where}: must be an object")
    fields = dict(raw)
    attribution = _require_key(raw, "attribution", EvidenceFileError, where)
    try:
        fields["attribution"] = AttributionKind(attribution)
    except ValueError:
        raise EvidenceFileError(f"{where}: unknown 'attribution' value") from None
    for name in _PAPER_DATETIME_FIELDS:
        value = _require_key(raw, name, EvidenceFileError, where)
        fields[name] = None if value is None else _parse_utc(value, name, EvidenceFileError, where)
    for name in _PAPER_OPTIONAL_DATETIME_FIELDS:
        if name in raw:
            value = raw[name]
            fields[name] = (
                None if value is None else _parse_utc(value, name, EvidenceFileError, where)
            )
    try:
        return PaperRecord(**fields)
    except Exception as exc:  # missing/extra field or identity validation failure
        raise EvidenceFileError(f"{where}: invalid paper record ({type(exc).__name__})") from None


def _load_evidence_class(doc: Mapping[str, Any]) -> EvidenceClass:
    """Default-deny fixture marker (REV-11, T-16-11): absent means REAL.

    The only accepted explicit value is the literal "fixture"; anything else is refused, so a
    typo or a "real" spelling can never be mistaken for a downgrade.
    """
    if "evidence_class" not in doc:
        return EvidenceClass.REAL
    if doc["evidence_class"] != EvidenceClass.FIXTURE.value:
        raise EvidenceFileError("evidence: 'evidence_class' must be absent or the string 'fixture'")
    return EvidenceClass.FIXTURE


def load_evidence_file(path: Path) -> EvidenceFile:
    """Load an `analytics-evidence/2` file fail-closed into typed objects (T-10-30/31, T-14-29).

    A file of any other schema (the void pre-Phase-14 `analytics-evidence/1`) is refused.
    An optional top-level `evidence_class: "fixture"` marks test evidence (REV-11); a file
    without it is real evidence.
    """
    doc = _read_json_object(path, EvidenceFileError, "evidence")
    if doc.get("schema") != EVIDENCE_SCHEMA:
        raise EvidenceFileError(f"schema must be {EVIDENCE_SCHEMA!r}")
    where = "evidence"
    raw_backtest = _require_key(doc, "backtest", EvidenceFileError, where)
    raw_paper = _require_key(doc, "paper", EvidenceFileError, where)
    raw_universe = _require_key(doc, "research_universe", EvidenceFileError, where)
    if not isinstance(raw_backtest, list):
        raise EvidenceFileError("evidence: 'backtest' must be a list")
    if not isinstance(raw_paper, list):
        raise EvidenceFileError("evidence: 'paper' must be a list")
    evidence_class = _load_evidence_class(doc)
    research_universe = _parse_symbols(raw_universe, where)
    backtest = tuple(_load_backtest_entry(raw, i) for i, raw in enumerate(raw_backtest))
    for index, entry in enumerate(backtest):
        for trade in entry.trades:
            if trade.symbol not in research_universe:
                raise EvidenceFileError(
                    f"backtest[{index}].trades[{trade.trade_id!r}]: symbol is outside the "
                    "research universe"
                )
    return EvidenceFile(
        backtest=backtest,
        paper=tuple(_load_paper_record(raw, i) for i, raw in enumerate(raw_paper)),
        research_universe=research_universe,
        evidence_class=evidence_class,
    )


def load_universe_file(path: Path) -> tuple[str, ...]:
    """Load a research-universe file (array or {"research_universe": [...]}), sorted unique."""
    loaded = _read_json(path, EvidenceFileError, "universe")
    if isinstance(loaded, dict):
        if "research_universe" not in loaded:
            raise EvidenceFileError("universe: missing required key 'research_universe'")
        loaded = loaded["research_universe"]
    return _parse_symbols(loaded, "universe")


# --------------------------------------------------------------------------- #
# Decisions file (schema kill-gate-decisions/1)
# --------------------------------------------------------------------------- #


def _id_list(raw: Any, key: str, where: str, *, required: bool) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise DecisionsFileError(f"{where}: {key!r} must be a list")
    if required and not raw:
        raise DecisionsFileError(f"{where}: {key!r} must be non-empty for a TESTED_* status")
    for item in raw:
        _require_str(item, key, DecisionsFileError, where)
    return tuple(raw)


def _load_family_decision(raw: Any, index: int) -> FamilyDecision:
    where = f"families[{index}]"
    if not isinstance(raw, dict):
        raise DecisionsFileError(f"{where}: must be an object")
    for key in _FAMILY_DECISION_KEYS:
        _require_key(raw, key, DecisionsFileError, where)
    family_id = _require_str(raw["family_id"], "family_id", DecisionsFileError, where)
    try:
        status = FamilyStatus(raw["status"])
    except ValueError:
        raise DecisionsFileError(f"{where}: 'status' is not a recognized status") from None
    tested = status is not FamilyStatus.NOT_TESTED
    decision_ref = raw["decision_ref"]
    if tested or decision_ref is not None:
        decision_ref = _require_str(decision_ref, "decision_ref", DecisionsFileError, where)
    decided_raw = raw["decided_at_utc"]
    decided_at = (
        None
        if decided_raw is None and not tested
        else _parse_utc(decided_raw, "decided_at_utc", DecisionsFileError, where)
    )
    return FamilyDecision(
        family_id=family_id,
        status=status,
        decision_ref=decision_ref,
        decided_at_utc=decided_at,
        development_experiment_ids=_id_list(
            raw["development_experiment_ids"], "development_experiment_ids", where, required=tested
        ),
        validation_experiment_ids=_id_list(
            raw["validation_experiment_ids"], "validation_experiment_ids", where, required=tested
        ),
    )


def _load_reset(raw: Any, index: int) -> ResetRecord:
    where = f"resets[{index}]"
    if not isinstance(raw, dict):
        raise DecisionsFileError(f"{where}: must be an object")
    operator_id = _require_key(raw, "operator_id", DecisionsFileError, where)
    decision_ref = _require_key(raw, "decision_ref", DecisionsFileError, where)
    occurred = _require_key(raw, "occurred_at_utc", DecisionsFileError, where)
    return ResetRecord(
        operator_id=_require_str(operator_id, "operator_id", DecisionsFileError, where),
        decision_ref=_require_str(decision_ref, "decision_ref", DecisionsFileError, where),
        occurred_at_utc=_parse_utc(occurred, "occurred_at_utc", DecisionsFileError, where),
    )


def _load_terminal(raw: Any) -> RecordedTerminal | None:
    if raw is None:
        return None
    where = "recorded_terminal"
    if not isinstance(raw, dict):
        raise DecisionsFileError(f"{where}: must be an object or null")
    for key in _TERMINAL_KEYS:
        _require_key(raw, key, DecisionsFileError, where)
    if raw["state"] != "INSUFFICIENT_EDGE":
        raise DecisionsFileError(f"{where}: 'state' must be INSUFFICIENT_EDGE")
    families = raw["families_at_record"]
    if not isinstance(families, list) or any(not isinstance(item, str) for item in families):
        raise DecisionsFileError(f"{where}: 'families_at_record' must be a list of strings")
    return RecordedTerminal(
        state="INSUFFICIENT_EDGE",
        decision_ref=_require_str(raw["decision_ref"], "decision_ref", DecisionsFileError, where),
        recorded_at_utc=_parse_utc(
            raw["recorded_at_utc"], "recorded_at_utc", DecisionsFileError, where
        ),
        families_at_record=tuple(families),
    )


def load_decisions_file(path: Path) -> DecisionsFile:
    """Load a `kill-gate-decisions/1` record fail-closed (D-03: pass/fail is a human input)."""
    doc = _read_json_object(path, DecisionsFileError, "decisions")
    if doc.get("schema") != DECISIONS_SCHEMA:
        raise DecisionsFileError(f"schema must be {DECISIONS_SCHEMA!r}")
    raw_families = _require_key(doc, "families", DecisionsFileError, "decisions")
    raw_resets = _require_key(doc, "resets", DecisionsFileError, "decisions")
    raw_terminal = _require_key(doc, "recorded_terminal", DecisionsFileError, "decisions")
    if not isinstance(raw_families, list):
        raise DecisionsFileError("decisions: 'families' must be a list")
    if not isinstance(raw_resets, list):
        raise DecisionsFileError("decisions: 'resets' must be a list")
    families = sorted(
        (_load_family_decision(raw, i) for i, raw in enumerate(raw_families)),
        key=lambda decision: decision.family_id,
    )
    if len({decision.family_id for decision in families}) != len(families):
        raise DecisionsFileError("families: duplicate 'family_id'")
    resets = sorted(
        (_load_reset(raw, i) for i, raw in enumerate(raw_resets)),
        key=lambda reset: (reset.occurred_at_utc, reset.decision_ref),
    )
    return DecisionsFile(
        families=tuple(families),
        resets=tuple(resets),
        recorded_terminal=_load_terminal(raw_terminal),
    )


# --------------------------------------------------------------------------- #
# Output confinement
# --------------------------------------------------------------------------- #


def confine_output_dir(requested: Path | None, reports_root: Path = REPORTS_ROOT) -> Path:
    """Return `requested` resolved, only if it equals or lies inside `reports_root`.

    `..` segments, absolute escapes and symlink escapes all resolve outside the root and are
    refused (T-10-29). The default (`requested is None`) is the reports root itself; the
    caller creates directories lazily after this check.
    """
    if requested is None:
        return reports_root
    root = reports_root.resolve()
    target = Path(requested).resolve()
    if target != root and not target.is_relative_to(root):
        raise PathConfinementError("output directory resolves outside the reports root")
    return target
