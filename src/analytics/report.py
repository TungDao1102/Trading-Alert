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

import dataclasses
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType

from src.analytics.approval_delay import ApprovalDelaySection, build_approval_delay
from src.analytics.clock import ClockStart
from src.analytics.core_metrics import CoreMetrics, compute_core_metrics
from src.analytics.excursion import ExcursionSection, build_excursion_section
from src.analytics.family import FamilyEvidence
from src.analytics.gates import FamilyGateFacts, GateCell, derive_gate_cells, gate_cells_digest
from src.analytics.killgate import KillGateVerdict, PriorEvaluation, ResetRecord, evaluate
from src.analytics.latency import ExecutionQualitySection, build_execution_quality
from src.analytics.lifecycle import LifecycleRecord
from src.analytics.no_trade import NoTradeSection, count_no_trades
from src.analytics.provenance import ProvenanceBlock, build_provenance
from src.analytics.slices import SlicesSection, build_slices
from src.analytics.types import (
    ANALYTICS_SCHEMA_VERSION,
    AnalyticsInputError,
    EvidenceKind,
    IncompleteReason,
    NoTradeRecord,
    TradeOutcome,
    _require_count,
    _require_utc,
)
from src.analytics.universe import DualUniverseView, build_dual_universe
from src.backtest.experiment import ExperimentRecord
from src.backtest.report import LIVE5_SYMBOLS
from src.core.types import Candle
from src.domain.canonical import sha256_hex
from src.domain.journal import JournalEvent

__all__ = [
    "EVIDENCE_ORDER",
    "FIXED_FAMILY_ORDER",
    "LIVE_ORDERS_DISABLED_EVENT",
    "LIVE_ORDERS_ENABLED_EVENT",
    "LIVE_POSTURE_UNKNOWN",
    "EvidenceBlock",
    "EvidenceInputs",
    "FamilyGateRow",
    "IncompleteEntry",
    "InputNote",
    "JournalDepthReport",
    "KillGateSection",
    "ReportInputs",
    "build_evidence_block",
    "build_incomplete_ledger",
    "build_journal_depth_report",
    "build_kill_gate_section",
    "live_posture_from_events",
]

# The fixed, never-pooled evidence order every report carries.
EVIDENCE_ORDER: tuple[EvidenceKind, ...] = (
    EvidenceKind.BACKTEST,
    EvidenceKind.PAPER,
    EvidenceKind.LIVE,
)

# Journal vocabulary of the live-orders posture (string literals on purpose: the posture
# helper reads events only and must never import or call enablement code).
LIVE_ORDERS_ENABLED_EVENT = "LIVE_ORDERS_ENABLED"
LIVE_ORDERS_DISABLED_EVENT = "LIVE_ORDERS_DISABLED"
LIVE_POSTURE_UNKNOWN = "UNKNOWN"

# The three families the kill gate names first; any other family follows alphabetically.
FIXED_FAMILY_ORDER: tuple[str, ...] = ("trend-pullback", "breakout-retest", "range-mr")

# Ledger reasons: every IncompleteReason value plus two fixed literals - never free text.
_LEDGER_REASONS: frozenset[str] = frozenset(
    {reason.value for reason in IncompleteReason} | {"ZERO_RISK", "NOT_R_VALUED"}
)
_LEDGER_NAME = re.compile(r"^[A-Za-z0-9_.:>-]+$")


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
class InputNote:
    """A caller-supplied count for the INCOMPLETE ledger (rejected rows, unmatched joins).

    Only a structured identifier, a fixed reason and a count are accepted - never free
    text - so the ledger (and the report) cannot carry exception messages or payloads.
    """

    input_name: str
    reason: str
    count: int

    def __post_init__(self) -> None:
        if not isinstance(self.input_name, str) or _LEDGER_NAME.match(self.input_name) is None:
            raise AnalyticsInputError(
                f"input_name must be a structured identifier: {self.input_name!r}"
            )
        if self.reason not in _LEDGER_REASONS:
            raise AnalyticsInputError(f"note reason {self.reason!r} is not a ledger reason")
        _require_count(self.count, "count")


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
    notes: tuple[InputNote, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EvidenceKind):
            raise AnalyticsInputError("kind must be an EvidenceKind")
        object.__setattr__(self, "notes", tuple(self.notes))
        for note in self.notes:
            if not isinstance(note, InputNote):
                raise AnalyticsInputError("notes entries must be InputNote instances")
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

    @property
    def has_data(self) -> bool:
        """True iff any of outcomes, lifecycle or no_trades is non-empty."""
        return bool(self.outcomes or self.lifecycle or self.no_trades)


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
class IncompleteEntry:
    """One ledger line: how many items of `input_name` are INCOMPLETE for `reason`."""

    evidence: EvidenceKind
    input_name: str
    reason: str
    count: int

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, EvidenceKind):
            raise AnalyticsInputError("evidence must be an EvidenceKind")
        if _LEDGER_NAME.match(self.input_name) is None:
            raise AnalyticsInputError(
                f"input_name must be a structured identifier: {self.input_name!r}"
            )
        if self.reason not in _LEDGER_REASONS:
            raise AnalyticsInputError(f"ledger reason {self.reason!r} is not in the vocabulary")
        _require_count(self.count, "count")

    def digest(self) -> str:
        return sha256_hex(
            {
                "evidence": self.evidence,
                "input_name": self.input_name,
                "reason": self.reason,
                "count": self.count,
            }
        )


@dataclass(frozen=True)
class FamilyGateRow:
    """One family's line in the kill-gate section (facts, gate cells, dual-universe counts)."""

    family_id: str
    independent: bool
    sheet_sha256: str | None
    param_set_count: int
    experiment_count: int
    status: str
    decision_ref: str | None
    live5_n: int
    research_n: int
    cells: tuple[tuple[str, GateCell], ...]

    def digest(self) -> str:
        return sha256_hex(
            {
                "family_id": self.family_id,
                "independent": self.independent,
                "sheet_sha256": self.sheet_sha256,
                "param_set_count": self.param_set_count,
                "experiment_count": self.experiment_count,
                "status": self.status,
                "decision_ref": self.decision_ref,
                "live5_n": self.live5_n,
                "research_n": self.research_n,
                "cells": gate_cells_digest(self.cells),
            }
        )


@dataclass(frozen=True)
class KillGateSection:
    """Kill-gate verdict, per-family gate matrix, decision refs and NO_TRADE counts."""

    verdict: KillGateVerdict
    families: tuple[FamilyGateRow, ...]
    decision_refs: tuple[str, ...]
    no_trade: tuple[NoTradeSection, ...]

    def digest(self) -> str:
        return sha256_hex(
            {
                "verdict": self.verdict.digest(),
                "families": [row.digest() for row in self.families],
                "decision_refs": list(self.decision_refs),
                "no_trade": [section.digest() for section in self.no_trade],
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
    live_posture: str
    kill_gate: KillGateSection
    incomplete_ledger: tuple[IncompleteEntry, ...]
    provenance: ProvenanceBlock

    def digest(self) -> str:
        return sha256_hex(
            {
                "schema_version": self.schema_version,
                "as_of_utc": self.as_of_utc,
                "base_seed": self.base_seed,
                "resamples": self.resamples,
                "evidence": [block.digest() for block in self.evidence],
                "live_posture": self.live_posture,
                "kill_gate": self.kill_gate.digest(),
                "incomplete_ledger": [entry.digest() for entry in self.incomplete_ledger],
                "provenance": self.provenance.digest(),
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
        has_data=inputs.has_data,
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


def live_posture_from_events(events: Iterable[JournalEvent]) -> str:
    """Latest LIVE_ORDERS_ENABLED / LIVE_ORDERS_DISABLED event type, or UNKNOWN.

    Display-only and read-only: it never changes enablement. Events are ordered by the
    total key (occurred_at_utc, event_type, entity_id, journal_event_id), so the answer
    does not depend on the input order.
    """
    posture_events = sorted(
        (
            event
            for event in events
            if event.event_type in (LIVE_ORDERS_ENABLED_EVENT, LIVE_ORDERS_DISABLED_EVENT)
        ),
        key=lambda event: (
            event.occurred_at_utc,
            event.event_type,
            event.entity_id,
            event.journal_event_id,
        ),
    )
    return posture_events[-1].event_type if posture_events else LIVE_POSTURE_UNKNOWN


def _family_order_key(family_id: str) -> tuple[int, str]:
    if family_id in FIXED_FAMILY_ORDER:
        return (FIXED_FAMILY_ORDER.index(family_id), family_id)
    return (len(FIXED_FAMILY_ORDER), family_id)


def build_kill_gate_section(
    verdict: KillGateVerdict,
    families: Iterable[FamilyEvidence],
    family_gate_facts: Mapping[str, FamilyGateFacts],
    no_trade_sections: Iterable[NoTradeSection],
    backtest_outcomes: Iterable[TradeOutcome],
    research_symbols: Iterable[str],
) -> KillGateSection:
    """Wrap the verdict with per-family gate cells and dual-universe counts.

    Gate cells come only from `derive_gate_cells`; a family without recorded facts gets
    the all-False facts (never a fabricated pass). `tested` follows the recorded status.
    """
    family_list = sorted(families, key=lambda family: _family_order_key(family.family_id))
    known = {family.family_id for family in family_list}
    unknown_facts = sorted(set(family_gate_facts) - known)
    if unknown_facts:
        raise AnalyticsInputError(f"gate facts for unknown families: {unknown_facts}")
    outcomes = list(backtest_outcomes)
    _require_own_kind(outcomes, EvidenceKind.BACKTEST, "kill-gate outcome")
    research_set = frozenset(research_symbols)
    rows_by_id = {row.family_id: row for row in verdict.families}
    rows: list[FamilyGateRow] = []
    for family in family_list:
        verdict_row = rows_by_id.get(family.family_id)
        if verdict_row is None:
            raise AnalyticsInputError(f"verdict has no row for family {family.family_id!r}")
        tested = verdict_row.status in ("TESTED_FAIL", "TESTED_PASS")
        facts = family_gate_facts.get(family.family_id)
        if facts is None:
            facts = FamilyGateFacts(
                cost_model_hash_present=False,
                reproducibility_verified=None,
                uncertainty_report_present=False,
                baseline_compared=False,
                tested=tested,
            )
        else:
            facts = dataclasses.replace(facts, tested=tested)
        candidate_hashes = frozenset(family.candidate_param_set_hashes)
        matching = [o for o in outcomes if o.parameter_set_hash in candidate_hashes]
        rows.append(
            FamilyGateRow(
                family_id=verdict_row.family_id,
                independent=verdict_row.independent,
                sheet_sha256=verdict_row.sheet_sha256,
                param_set_count=verdict_row.param_set_count,
                experiment_count=verdict_row.experiment_count,
                status=verdict_row.status,
                decision_ref=verdict_row.decision_ref,
                live5_n=sum(1 for o in matching if o.symbol in LIVE5_SYMBOLS),
                research_n=sum(1 for o in matching if o.symbol in research_set),
                cells=derive_gate_cells(facts),
            )
        )
    sections = sorted(no_trade_sections, key=lambda section: EVIDENCE_ORDER.index(section.evidence))
    if len({section.evidence for section in sections}) != len(sections):
        raise AnalyticsInputError("no_trade_sections must hold at most one section per kind")
    decision_refs = tuple(
        sorted(
            {
                row.decision_ref
                for row in verdict.families
                if row.status in ("TESTED_FAIL", "TESTED_PASS") and row.decision_ref is not None
            }
        )
    )
    return KillGateSection(
        verdict=verdict,
        families=tuple(rows),
        decision_refs=decision_refs,
        no_trade=tuple(sections),
    )


def _block_ledger_counts(block: EvidenceBlock) -> Iterable[tuple[str, str, int]]:
    """(input_name, reason, count) triples re-labelled from one block's own counters."""
    yield ("core_metrics", "ZERO_RISK", block.core.zero_risk_excluded)
    yield ("core_metrics", "NOT_R_VALUED", block.core.incomplete)
    for reason, count in block.excursion.incomplete:
        yield ("excursion", reason, count)
    yield ("excursion", "ZERO_RISK", block.excursion.n_zero_risk_excluded)
    for leg in block.execution_quality.legs:
        for reason, count in leg.incomplete:
            yield (f"execution_quality.{leg.leg.value}", reason, count)
    for reason, count in block.execution_quality.deviation.incomplete:
        yield ("execution_quality.deviation", reason, count)
    delay = block.approval_delay
    for report_block in (delay.system, delay.user_execution, delay.opportunity):
        for reason, count in report_block.incomplete:
            yield (f"approval_delay.{report_block.label.value}", reason, count)
    for reason, count in delay.delay_incomplete:
        yield ("approval_delay.delay", reason, count)


def build_incomplete_ledger(
    blocks: Sequence[EvidenceBlock], inputs: ReportInputs
) -> tuple[IncompleteEntry, ...]:
    """One sorted ledger of every INCOMPLETE bucket, exclusion and note (count 0 omitted)."""
    totals: dict[tuple[int, str, str], int] = {}

    def add(kind: EvidenceKind, name: str, reason: str, count: int) -> None:
        if count > 0:
            key = (EVIDENCE_ORDER.index(kind), name, reason)
            totals[key] = totals.get(key, 0) + count

    for block in blocks:
        for name, reason, count in _block_ledger_counts(block):
            add(block.kind, name, reason, count)
    for evidence_inputs in inputs.evidence_inputs():
        for note in evidence_inputs.notes:
            add(evidence_inputs.kind, note.input_name, note.reason, note.count)
    return tuple(
        IncompleteEntry(
            evidence=EVIDENCE_ORDER[kind_index], input_name=name, reason=reason, count=count
        )
        for (kind_index, name, reason), count in sorted(totals.items())
    )


def build_journal_depth_report(
    inputs: ReportInputs, *, base_seed: int, resamples: int
) -> JournalDepthReport:
    """Build the composed report; `as_of_utc` comes only from `inputs`.

    The kill-gate verdict is evaluated here (read-only, at the injected `as_of_utc`); the
    report never writes an event or records the evaluation.
    """
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
    verdict = evaluate(
        families=inputs.families,
        clock=inputs.clock,
        evaluated_at_utc=inputs.as_of_utc,
        prior_evaluations=inputs.prior_evaluations,
        resets=inputs.resets,
    )
    kill_gate = build_kill_gate_section(
        verdict,
        inputs.families,
        inputs.family_gate_facts,
        [block.no_trade for block in blocks],
        inputs.backtest.outcomes,
        inputs.research_symbols,
    )
    return JournalDepthReport(
        schema_version=ANALYTICS_SCHEMA_VERSION,
        as_of_utc=inputs.as_of_utc,
        base_seed=base_seed,
        resamples=resamples,
        evidence=blocks,
        live_posture=live_posture_from_events(inputs.journal_events),
        kill_gate=kill_gate,
        incomplete_ledger=build_incomplete_ledger(blocks, inputs),
        provenance=build_provenance(inputs, base_seed=base_seed, resamples=resamples),
    )
