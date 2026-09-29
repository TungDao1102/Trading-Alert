"""Evidence provenance block (Phase 10, plan 10-08, D-05).

Every report carries full provenance so any headline number traces back to registered
experiments and journal rows: strategy versions, parameter-set ids/hashes, the
experiment identity fields (experiment_id, strategy_version, parameter_set_id,
parameter_set_hash, data_snapshot_id, code_version, cost_model_hash, plus the universe
hash and run type), data snapshot ids, paper epoch ids and the fixed vocabulary
constants. BACKTEST, PAPER and LIVE identity is listed separately (`by_evidence`) and the
flat union fields state which evidence kinds are present.

Pure: derived from frozen `ReportInputs`; no file access, no clock, no float. Every
sequence is a sorted tuple. The research-universe hash is the Phase-6 universe hash and
its status comes from the shared `verify_research_universe` (never re-implemented).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.analytics.live_outcomes import LIVE_NET_PNL_SEMANTICS_VERIFIED
from src.analytics.slices import SESSION_BANDS, SLICE_VOCABULARY_VERSION
from src.analytics.types import (
    ANALYTICS_SCHEMA_VERSION,
    LOW_N_THRESHOLD,
    EvidenceKind,
)
from src.analytics.universe import verify_research_universe
from src.backtest.experiment import ExperimentRecord, _universe_hash
from src.domain.canonical import sha256_hex
from src.paper.attribution import APPROVAL_DELAY_LAG_SECONDS

if TYPE_CHECKING:
    from src.analytics.report import EvidenceInputs, ReportInputs

__all__ = [
    "LIVE_R_EXCLUDES",
    "ExperimentIdentity",
    "KindProvenance",
    "ProvenanceBlock",
    "build_provenance",
]

# Live R is net of fees but excludes funding (stated so R is never over-read).
LIVE_R_EXCLUDES: tuple[str, ...] = ("funding",)

_KIND_ORDER: tuple[EvidenceKind, ...] = (
    EvidenceKind.BACKTEST,
    EvidenceKind.PAPER,
    EvidenceKind.LIVE,
)


@dataclass(frozen=True)
class ExperimentIdentity:
    """The registered-experiment identity fields, tagged with their evidence kind."""

    experiment_id: str
    strategy_version: str
    parameter_set_id: str
    parameter_set_hash: str
    data_snapshot_id: str
    code_version: str
    cost_model_hash: str
    universe_hash: str
    run_type: str
    evidence: EvidenceKind = EvidenceKind.BACKTEST

    @classmethod
    def from_record(cls, record: ExperimentRecord, evidence: EvidenceKind) -> ExperimentIdentity:
        return cls(
            experiment_id=record.experiment_id,
            strategy_version=record.strategy_version,
            parameter_set_id=record.parameter_set_id,
            parameter_set_hash=record.parameter_set_hash,
            data_snapshot_id=record.data_snapshot_id,
            code_version=record.code_version,
            cost_model_hash=record.cost_model_hash,
            universe_hash=record.universe_hash,
            run_type=record.run_type,
            evidence=evidence,
        )

    def digest(self) -> str:
        return sha256_hex(
            {
                "evidence": self.evidence,
                "experiment_id": self.experiment_id,
                "strategy_version": self.strategy_version,
                "parameter_set_id": self.parameter_set_id,
                "parameter_set_hash": self.parameter_set_hash,
                "data_snapshot_id": self.data_snapshot_id,
                "code_version": self.code_version,
                "cost_model_hash": self.cost_model_hash,
                "universe_hash": self.universe_hash,
                "run_type": self.run_type,
            }
        )


@dataclass(frozen=True)
class KindProvenance:
    """The identity behind exactly one evidence kind (never merged across kinds)."""

    kind: EvidenceKind
    has_data: bool
    strategy_versions: tuple[str, ...]
    parameter_set_ids: tuple[str, ...]
    parameter_set_hashes: tuple[str, ...]
    data_snapshot_ids: tuple[str, ...]
    paper_epoch_ids: tuple[str, ...]

    def digest(self) -> str:
        return sha256_hex(
            {
                "kind": self.kind,
                "has_data": self.has_data,
                "strategy_versions": list(self.strategy_versions),
                "parameter_set_ids": list(self.parameter_set_ids),
                "parameter_set_hashes": list(self.parameter_set_hashes),
                "data_snapshot_ids": list(self.data_snapshot_ids),
                "paper_epoch_ids": list(self.paper_epoch_ids),
            }
        )


@dataclass(frozen=True)
class ProvenanceBlock:
    """Report-wide provenance: identity, universe verification and vocabulary constants."""

    schema_version: str
    strategy_versions: tuple[str, ...]
    parameter_set_ids: tuple[str, ...]
    parameter_set_hashes: tuple[str, ...]
    experiments: tuple[ExperimentIdentity, ...]
    research_universe_hash: str
    research_universe_status: str
    data_snapshot_ids: tuple[str, ...]
    paper_epoch_ids: tuple[str, ...]
    approval_delay_lag_seconds: int
    low_n_threshold: int
    resamples: int
    base_seed: int
    slice_vocabulary_version: str
    session_bands: tuple[tuple[str, int, int], ...]
    evidence_kinds_present: tuple[str, ...]
    live_net_pnl_semantics_verified: bool
    live_r_excludes: tuple[str, ...]
    by_evidence: tuple[KindProvenance, ...]

    def digest(self) -> str:
        return sha256_hex(
            {
                "schema_version": self.schema_version,
                "strategy_versions": list(self.strategy_versions),
                "parameter_set_ids": list(self.parameter_set_ids),
                "parameter_set_hashes": list(self.parameter_set_hashes),
                "experiments": [item.digest() for item in self.experiments],
                "research_universe_hash": self.research_universe_hash,
                "research_universe_status": self.research_universe_status,
                "data_snapshot_ids": list(self.data_snapshot_ids),
                "paper_epoch_ids": list(self.paper_epoch_ids),
                "approval_delay_lag_seconds": self.approval_delay_lag_seconds,
                "low_n_threshold": self.low_n_threshold,
                "resamples": self.resamples,
                "base_seed": self.base_seed,
                "slice_vocabulary_version": self.slice_vocabulary_version,
                "session_bands": [list(band) for band in self.session_bands],
                "evidence_kinds_present": list(self.evidence_kinds_present),
                "live_net_pnl_semantics_verified": self.live_net_pnl_semantics_verified,
                "live_r_excludes": list(self.live_r_excludes),
                "by_evidence": [item.digest() for item in self.by_evidence],
            }
        )


def _sorted_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def _kind_provenance(inputs: EvidenceInputs) -> KindProvenance:
    epoch_ids = set(inputs.paper_epoch_ids)
    epoch_ids.update(record.epoch_id for record in inputs.lifecycle if record.epoch_id is not None)
    return KindProvenance(
        kind=inputs.kind,
        has_data=inputs.has_data,
        strategy_versions=_sorted_unique(
            [outcome.strategy_version for outcome in inputs.outcomes]
            + [record.strategy_version for record in inputs.lifecycle]
            + [experiment.strategy_version for experiment in inputs.experiments]
        ),
        parameter_set_ids=_sorted_unique(
            experiment.parameter_set_id for experiment in inputs.experiments
        ),
        parameter_set_hashes=_sorted_unique(
            [outcome.parameter_set_hash for outcome in inputs.outcomes]
            + [experiment.parameter_set_hash for experiment in inputs.experiments]
        ),
        data_snapshot_ids=_sorted_unique(
            experiment.data_snapshot_id for experiment in inputs.experiments
        ),
        paper_epoch_ids=tuple(sorted(epoch_ids)),
    )


def build_provenance(inputs: ReportInputs, *, base_seed: int, resamples: int) -> ProvenanceBlock:
    """Derive the provenance block from frozen inputs (no file access)."""
    per_kind = tuple(_kind_provenance(item) for item in inputs.evidence_inputs())
    experiments = tuple(
        sorted(
            (
                ExperimentIdentity.from_record(record, item.kind)
                for item in inputs.evidence_inputs()
                for record in item.experiments
            ),
            key=lambda identity: (_KIND_ORDER.index(identity.evidence), identity.experiment_id),
        )
    )
    return ProvenanceBlock(
        schema_version=ANALYTICS_SCHEMA_VERSION,
        strategy_versions=_sorted_unique(v for kind in per_kind for v in kind.strategy_versions),
        parameter_set_ids=_sorted_unique(v for kind in per_kind for v in kind.parameter_set_ids),
        parameter_set_hashes=_sorted_unique(
            v for kind in per_kind for v in kind.parameter_set_hashes
        ),
        experiments=experiments,
        research_universe_hash=_universe_hash(inputs.research_symbols),
        research_universe_status=verify_research_universe(
            inputs.research_symbols, inputs.expected_universe_hash
        ),
        data_snapshot_ids=_sorted_unique(v for kind in per_kind for v in kind.data_snapshot_ids),
        paper_epoch_ids=_sorted_unique(v for kind in per_kind for v in kind.paper_epoch_ids),
        approval_delay_lag_seconds=APPROVAL_DELAY_LAG_SECONDS,
        low_n_threshold=LOW_N_THRESHOLD,
        resamples=resamples,
        base_seed=base_seed,
        slice_vocabulary_version=SLICE_VOCABULARY_VERSION,
        session_bands=SESSION_BANDS,
        evidence_kinds_present=tuple(kind.kind.value for kind in per_kind if kind.has_data),
        live_net_pnl_semantics_verified=LIVE_NET_PNL_SEMANTICS_VERIFIED,
        live_r_excludes=LIVE_R_EXCLUDES,
        by_evidence=per_kind,
    )
