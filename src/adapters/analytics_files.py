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
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.analytics.family import (
    FamilyEvidence,
    FamilyStatus,
    is_baseline_parameter_set_id,
)
from src.analytics.gates import FamilyGateFacts
from src.analytics.killgate import ResetRecord
from src.backtest.experiment import ExperimentRecord
from src.domain.registry import REGISTRY_ROOT, load_parameter_set

__all__ = [
    "REPORTS_ROOT",
    "DecisionsFile",
    "DecisionsFileError",
    "EvidenceFileError",
    "ExperimentFlags",
    "FamilyDecision",
    "FamilyScan",
    "PathConfinementError",
    "RecordedTerminal",
    "read_protocol_text",
    "scan_family_facts",
]

REPORTS_ROOT = Path("data") / "reports"

_PROTOCOL_RELATIVE = Path("docs") / "research" / "RESEARCH_PROTOCOL.md"
_SLOT_HEADING = re.compile(r"^## ([1-7])\.", re.MULTILINE)
_CANDIDATE_RUN_TYPE = "CANDIDATE"


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
    """The committed mirror of a recorded INSUFFICIENT_EDGE outcome (D-03 tripwire input)."""

    state: str
    decision_ref: str
    recorded_at_utc: str
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
    """(sha256 hex of the sheet bytes, sorted unique 7-slot heading numbers)."""
    sheet = sheets_root / f"{family_id}.md"
    if not sheet.is_file():
        return None, ()
    raw = sheet.read_bytes()
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
    """
    decision_by_family = {decision.family_id: decision for decision in decisions.families}
    candidate_hashes = {family_id: _candidate_hashes(family_id) for family_id in _family_ids()}
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
                    baseline_compared=any(
                        flag.baseline_summaries_present for flag in family_flags
                    ),
                    tested=evidence.status is not FamilyStatus.NOT_TESTED,
                ),
            )
        )

    return FamilyScan(
        families=tuple(families),
        gate_facts=tuple(facts),
        unknown_experiment_ids=tuple(sorted(unknown)),
    )
