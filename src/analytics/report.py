"""Composed journal-depth report model (Phase 10, plan 10-08, D-01, D-04, D-05).

`build_journal_depth_report` is one pure function of frozen inputs. It composes exactly
three `EvidenceBlock`s - BACKTEST, PAPER, LIVE, always in that order, an empty kind
rendering as a valid no-data block - and stamps the whole tree with one digest. Evidence
kinds are never pooled: each block is built only from its own kind's inputs, a
cross-kind element fails closed, and the report has no aggregate field across kinds.

No wall clock (`as_of_utc` is injected), no float, no dict/set iteration order in
outputs, no database/adapter/file access. Mapping-typed inputs are frozen read-only and
always iterated through sorted keys.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType

from src.analytics.approval_delay import ApprovalDelaySection, build_approval_delay
from src.analytics.clock import ClockStart
from src.analytics.core_metrics import CoreMetrics, compute_core_metrics
from src.analytics.excursion import ExcursionSection, build_excursion_section
from src.analytics.family import FamilyEvidence
from src.analytics.gates import FamilyGateFacts
from src.analytics.killgate import PriorEvaluation, ResetRecord
from src.analytics.latency import ExecutionQualitySection, build_execution_quality
from src.analytics.lifecycle import LifecycleRecord
from src.analytics.no_trade import NoTradeSection, count_no_trades
from src.analytics.slices import SlicesSection, build_slices
from src.analytics.types import (
    ANALYTICS_SCHEMA_VERSION,
    AnalyticsInputError,
    EvidenceKind,
    NoTradeRecord,
    TradeOutcome,
    _require_utc,
)
from src.analytics.universe import DualUniverseView, build_dual_universe
from src.backtest.experiment import ExperimentRecord
from src.core.types import Candle
from src.domain.canonical import sha256_hex
from src.domain.journal import JournalEvent

__all__ = [
    "EVIDENCE_ORDER",
    "EvidenceBlock",
    "EvidenceInputs",
    "JournalDepthReport",
    "ReportInputs",
    "build_evidence_block",
    "build_journal_depth_report",
]

# The fixed, never-pooled evidence order every report carries.
EVIDENCE_ORDER: tuple[EvidenceKind, ...] = (
    EvidenceKind.BACKTEST,
    EvidenceKind.PAPER,
    EvidenceKind.LIVE,
)


def _freeze_r_mapping(mapping: Mapping[str, Decimal], name: str) -> Mapping[str, Decimal]:
    """Read-only copy with sorted keys; every key/value validated (fail closed)."""
    frozen: dict[str, Decimal] = {}
    for key in sorted(mapping):
        value = mapping[key]
        if not isinstance(key, str) or key == "":
            raise AnalyticsInputError(f"{name} keys must be non-empty str, got {key!r}")
        if not isinstance(value, Decimal) or not value.is_finite():
            raise AnalyticsInputError(f"{name}[{key!r}] must be a finite Decimal")
        frozen[key] = value
    return MappingProxyType(frozen)


def _freeze_candles(
    mapping: Mapping[str, Sequence[Candle]],
) -> Mapping[str, tuple[Candle, ...]]:
    frozen: dict[str, tuple[Candle, ...]] = {}
    for key in sorted(mapping):
        if not isinstance(key, str) or key == "":
            raise AnalyticsInputError(f"candles_by_symbol keys must be non-empty str, got {key!r}")
        frozen[key] = tuple(mapping[key])
    return MappingProxyType(frozen)


@dataclass(frozen=True)
class EvidenceInputs:
    """Everything one evidence kind contributes; an all-empty instance is valid.

    Sequences are frozen to tuples and mappings to read-only sorted-key copies at
    construction. `notes` (Task 2 ledger inputs) and `experiments`/`paper_epoch_ids`
    feed provenance only; they never change a statistic.
    """

    kind: EvidenceKind
    outcomes: tuple[TradeOutcome, ...] = ()
    lifecycle: tuple[LifecycleRecord, ...] = ()
    no_trades: tuple[NoTradeRecord, ...] = ()
    candles_by_symbol: Mapping[str, Sequence[Candle]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    realized_r_by_signal: Mapping[str, Decimal] = field(
        default_factory=lambda: MappingProxyType({})
    )
    hypothetical_r_by_signal: Mapping[str, Decimal] = field(
        default_factory=lambda: MappingProxyType({})
    )
    experiments: tuple[ExperimentRecord, ...] = ()
    paper_epoch_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EvidenceKind):
            raise AnalyticsInputError("kind must be an EvidenceKind")
        object.__setattr__(self, "outcomes", tuple(self.outcomes))
        object.__setattr__(self, "lifecycle", tuple(self.lifecycle))
        object.__setattr__(self, "no_trades", tuple(self.no_trades))
        object.__setattr__(self, "experiments", tuple(self.experiments))
        object.__setattr__(self, "paper_epoch_ids", tuple(self.paper_epoch_ids))
        object.__setattr__(self, "candles_by_symbol", _freeze_candles(self.candles_by_symbol))
        object.__setattr__(
            self,
            "realized_r_by_signal",
            _freeze_r_mapping(self.realized_r_by_signal, "realized_r_by_signal"),
        )
        object.__setattr__(
            self,
            "hypothetical_r_by_signal",
            _freeze_r_mapping(self.hypothetical_r_by_signal, "hypothetical_r_by_signal"),
        )
        for epoch_id in self.paper_epoch_ids:
            if not isinstance(epoch_id, str) or epoch_id == "":
                raise AnalyticsInputError("paper_epoch_ids entries must be non-empty str")


@dataclass(frozen=True)
class ReportInputs:
    """All frozen inputs of one report; `as_of_utc` is the single injected time."""

    as_of_utc: datetime
    backtest: EvidenceInputs
    paper: EvidenceInputs
    live: EvidenceInputs
    clock: ClockStart
    research_symbols: tuple[str, ...] = ()
    expected_universe_hash: str | None = None
    journal_events: tuple[JournalEvent, ...] = ()
    families: tuple[FamilyEvidence, ...] = ()
    family_gate_facts: Mapping[str, FamilyGateFacts] = field(
        default_factory=lambda: MappingProxyType({})
    )
    prior_evaluations: tuple[PriorEvaluation, ...] = ()
    resets: tuple[ResetRecord, ...] = ()

    def __post_init__(self) -> None:
        _require_utc(self.as_of_utc, "as_of_utc")
        for expected, slot in zip(
            EVIDENCE_ORDER, (self.backtest, self.paper, self.live), strict=True
        ):
            if not isinstance(slot, EvidenceInputs) or slot.kind is not expected:
                raise AnalyticsInputError(
                    f"the {expected.value} slot must hold {expected.value} evidence inputs"
                )
        if not isinstance(self.clock, ClockStart):
            raise AnalyticsInputError("clock must be a ClockStart")
        for symbol in self.research_symbols:
            if not isinstance(symbol, str) or symbol == "":
                raise AnalyticsInputError(f"research symbol must be a non-empty str: {symbol!r}")
        object.__setattr__(self, "research_symbols", tuple(sorted(set(self.research_symbols))))
        object.__setattr__(self, "journal_events", tuple(self.journal_events))
        object.__setattr__(self, "families", tuple(self.families))
        object.__setattr__(self, "prior_evaluations", tuple(self.prior_evaluations))
        object.__setattr__(self, "resets", tuple(self.resets))
        object.__setattr__(
            self,
            "family_gate_facts",
            MappingProxyType(
                {key: self.family_gate_facts[key] for key in sorted(self.family_gate_facts)}
            ),
        )

    def evidence_inputs(self) -> tuple[EvidenceInputs, ...]:
        """The three per-kind inputs in the fixed BACKTEST, PAPER, LIVE order."""
        return (self.backtest, self.paper, self.live)


@dataclass(frozen=True)
class EvidenceBlock:
    """Every analytics section for exactly one evidence kind (never pooled)."""

    kind: EvidenceKind
    has_data: bool
    core: CoreMetrics
    excursion: ExcursionSection
    execution_quality: ExecutionQualitySection
    approval_delay: ApprovalDelaySection
    slices: SlicesSection
    dual_universe: DualUniverseView
    no_trade: NoTradeSection

    def digest(self) -> str:
        return sha256_hex(
            {
                "kind": self.kind,
                "has_data": self.has_data,
                "core": self.core.digest(),
                "excursion": self.excursion.digest(),
                "execution_quality": self.execution_quality.digest(),
                "approval_delay": self.approval_delay.digest(),
                "slices": self.slices.digest(),
                "dual_universe": self.dual_universe.digest(),
                "no_trade": self.no_trade.digest(),
            }
        )


@dataclass(frozen=True)
class JournalDepthReport:
    """The composed dashboard model: three unpooled evidence blocks plus one digest."""

    schema_version: str
    as_of_utc: datetime
    base_seed: int
    resamples: int
    evidence: tuple[EvidenceBlock, ...]

    def digest(self) -> str:
        return sha256_hex(
            {
                "schema_version": self.schema_version,
                "as_of_utc": self.as_of_utc,
                "base_seed": self.base_seed,
                "resamples": self.resamples,
                "evidence": [block.digest() for block in self.evidence],
            }
        )


def _require_own_kind(items: Sequence[object], kind: EvidenceKind, label: str) -> None:
    for item in items:
        item_kind = getattr(item, "evidence", None)
        if item_kind is not kind:
            shown = getattr(item_kind, "value", item_kind)
            raise AnalyticsInputError(
                f"{label} element has evidence {shown!r}, block is {kind.value} "
                "(evidence kinds are never pooled)"
            )


def build_evidence_block(
    inputs: EvidenceInputs,
    *,
    research_symbols: Sequence[str],
    expected_universe_hash: str | None,
    base_seed: int,
    resamples: int,
) -> EvidenceBlock:
    """Compose one section of each analytics module for `inputs.kind` only."""
    kind = inputs.kind
    _require_own_kind(inputs.outcomes, kind, "outcome")
    _require_own_kind(inputs.lifecycle, kind, "lifecycle")
    _require_own_kind(inputs.no_trades, kind, "no_trade")
    outcomes = sorted(inputs.outcomes, key=lambda outcome: outcome.trade_id)
    lifecycle = sorted(inputs.lifecycle, key=lambda record: record.source_id)
    no_trades = sorted(inputs.no_trades, key=lambda record: record.source_id)
    return EvidenceBlock(
        kind=kind,
        has_data=bool(outcomes or lifecycle or no_trades),
        core=compute_core_metrics(outcomes, base_seed=base_seed, resamples=resamples),
        excursion=build_excursion_section(
            outcomes,
            inputs.candles_by_symbol,
            evidence=kind,
            base_seed=base_seed,
            resamples=resamples,
        ),
        execution_quality=build_execution_quality(
            lifecycle, evidence=kind, base_seed=base_seed, resamples=resamples
        ),
        approval_delay=build_approval_delay(
            lifecycle,
            evidence=kind,
            realized_r_by_signal=inputs.realized_r_by_signal,
            hypothetical_r_by_signal=inputs.hypothetical_r_by_signal,
            base_seed=base_seed,
            resamples=resamples,
        ),
        slices=build_slices(outcomes, evidence=kind, base_seed=base_seed, resamples=resamples),
        dual_universe=build_dual_universe(
            outcomes,
            evidence=kind,
            research_symbols=research_symbols,
            expected_universe_hash=expected_universe_hash,
            base_seed=base_seed,
            resamples=resamples,
        ),
        no_trade=count_no_trades(no_trades, evidence=kind, research_symbols=research_symbols),
    )


def build_journal_depth_report(
    inputs: ReportInputs, *, base_seed: int, resamples: int
) -> JournalDepthReport:
    """Build the composed report; `as_of_utc` comes only from `inputs`."""
    blocks = tuple(
        build_evidence_block(
            evidence_inputs,
            research_symbols=inputs.research_symbols,
            expected_universe_hash=inputs.expected_universe_hash,
            base_seed=base_seed,
            resamples=resamples,
        )
        for evidence_inputs in inputs.evidence_inputs()
    )
    return JournalDepthReport(
        schema_version=ANALYTICS_SCHEMA_VERSION,
        as_of_utc=inputs.as_of_utc,
        base_seed=base_seed,
        resamples=resamples,
        evidence=blocks,
    )
