"""NO_TRADE counts by reason category (Phase 10, plan 10-04, GOV-01, D-04, D-05).

NO_TRADE is a first-class outcome (RESEARCH_PROTOCOL "NO_TRADE as a valid outcome"):
counted by the five protocol reason categories plus an UNMAPPED bucket that is
counted, never dropped, split into live-5 / research / all counts. The mapping from
canonical reason codes to categories is a documented plan assumption; GLOSSARY
section 9 gains no new codes. The live-5 set is imported (single source) and the
research symbols are evidence input, never a list held here. One evidence kind per
call - kinds are never pooled.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from src.analytics.types import AnalyticsInputError, EvidenceKind, NoTradeRecord
from src.backtest.report import LIVE5_SYMBOLS
from src.domain.canonical import sha256_hex
from src.paper.attribution import AttributionKind
from src.paper.journal import PaperRecord


class NoTradeCategory(str, Enum):
    """The five RESEARCH_PROTOCOL NO_TRADE categories plus the UNMAPPED catch-all."""

    REGIME_FILTER = "REGIME_FILTER"
    RR_FLOOR = "RR_FLOOR"
    OPEN_POSITION_CONFLICT = "OPEN_POSITION_CONFLICT"
    DATA_UNAVAILABILITY = "DATA_UNAVAILABILITY"
    KILL_GATE_TRIP = "KILL_GATE_TRIP"
    UNMAPPED = "UNMAPPED"


# Plan assumptions (documented): reason code -> protocol category.
NO_TRADE_CATEGORY_BY_REASON: MappingProxyType[str, NoTradeCategory] = MappingProxyType(
    {
        "NO_TRADE_REGIME": NoTradeCategory.REGIME_FILTER,
        "RR_TOO_LOW": NoTradeCategory.RR_FLOOR,
        "MAX_POSITIONS_REJECT": NoTradeCategory.OPEN_POSITION_CONFLICT,
        "SKIPPED_BUSY": NoTradeCategory.OPEN_POSITION_CONFLICT,
        "DATA_STALE": NoTradeCategory.DATA_UNAVAILABILITY,
        "STALE_CONSTRAINTS": NoTradeCategory.DATA_UNAVAILABILITY,
        "UNCERTAIN_ACCOUNT_STATE": NoTradeCategory.DATA_UNAVAILABILITY,
        "RECONCILIATION_REQUIRED": NoTradeCategory.DATA_UNAVAILABILITY,
        "INSUFFICIENT_EDGE": NoTradeCategory.KILL_GATE_TRIP,
    }
)


@dataclass(frozen=True)
class NoTradeRow:
    """Counts for one category, split live-5 / research / all.

    `category` is None only on the Total row of a `NoTradeSection`.
    """

    category: NoTradeCategory | None
    live5_n: int
    research_n: int
    all_n: int

    def digest(self) -> str:
        return sha256_hex(
            {
                "category": None if self.category is None else self.category.value,
                "live5_n": self.live5_n,
                "research_n": self.research_n,
                "all_n": self.all_n,
            }
        )


@dataclass(frozen=True)
class NoTradeSection:
    """NO_TRADE counts for one evidence kind: six fixed-order rows plus Total."""

    evidence: EvidenceKind
    rows: tuple[NoTradeRow, ...]
    total: NoTradeRow
    research_symbols: tuple[str, ...]

    def digest(self) -> str:
        return sha256_hex(
            {
                "evidence": self.evidence.value,
                "rows": [row.digest() for row in self.rows],
                "total": self.total.digest(),
                "research_symbols": list(self.research_symbols),
            }
        )


def category_for(reason_code: str) -> NoTradeCategory:
    """Map a reason code to its category; anything unrecognized is UNMAPPED (counted)."""
    return NO_TRADE_CATEGORY_BY_REASON.get(reason_code, NoTradeCategory.UNMAPPED)


def no_trade_from_paper(records: Sequence[PaperRecord]) -> list[NoTradeRecord]:
    """NO_TRADE records from paper rows: attribution SYSTEM with no signal only.

    Opportunity rows (skipped/expired signals) and rows that carry a signal are
    signal-chain outcomes, not NO_TRADE. Input order is preserved.
    """
    found: list[NoTradeRecord] = []
    for record in records:
        if record.attribution is not AttributionKind.SYSTEM or record.signal_id is not None:
            continue
        detected = record.signal_detected_at_utc
        stamp = "-" if detected is None else detected.isoformat()
        found.append(
            NoTradeRecord(
                evidence=EvidenceKind.PAPER,
                symbol=record.symbol,
                reason_code=record.reason_code,
                source_id=f"{record.epoch_id}:{record.symbol}:{record.reason_code}:{stamp}",
            )
        )
    return found


def count_no_trades(
    records: Sequence[NoTradeRecord],
    *,
    evidence: EvidenceKind,
    research_symbols: Sequence[str],
) -> NoTradeSection:
    """Count NO_TRADE records by category; mixed evidence fails closed."""
    for record in records:
        if record.evidence is not evidence:
            raise AnalyticsInputError(
                f"NO_TRADE record {record.source_id!r} has evidence {record.evidence.value}, "
                f"expected {evidence.value} (evidence kinds are never pooled)"
            )
    research = tuple(sorted(set(research_symbols)))
    research_set = frozenset(research)
    counts: dict[NoTradeCategory, list[int]] = {cat: [0, 0, 0] for cat in NoTradeCategory}
    for record in records:
        bucket = counts[category_for(record.reason_code)]
        if record.symbol in LIVE5_SYMBOLS:
            bucket[0] += 1
        if record.symbol in research_set:
            bucket[1] += 1
        bucket[2] += 1
    rows = tuple(
        NoTradeRow(
            category=cat, live5_n=counts[cat][0], research_n=counts[cat][1], all_n=counts[cat][2]
        )
        for cat in NoTradeCategory
    )
    total = NoTradeRow(
        category=None,
        live5_n=sum(row.live5_n for row in rows),
        research_n=sum(row.research_n for row in rows),
        all_n=sum(row.all_n for row in rows),
    )
    return NoTradeSection(evidence=evidence, rows=rows, total=total, research_symbols=research)
