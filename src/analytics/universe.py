"""Dual-universe view (Phase 10, plan 10-04, D-04, D-05).

Live-5 and the research universe sit side by side for ONE evidence kind (kinds are
never pooled). The live-5 set is imported from `src.backtest.report` (single
source - no third copy lives here) and the research symbols are always evidence
INPUT, never a list held by this module. An empty slice is an explicit no-data
`CoreMetrics` (n 0, every estimate None) - never hidden, never imputed. The
research-universe hash is verified against the recorded `ExperimentRecord`
universe hash or labelled `UNVERIFIED_UNIVERSE`.

The two views overlap by design (live-5 symbols may also be in the research set):
they are side-by-side views, not additive partitions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from src.analytics.core_metrics import CoreMetrics, compute_core_metrics
from src.analytics.types import AnalyticsInputError, EvidenceKind, TradeOutcome
from src.backtest.experiment import _universe_hash
from src.backtest.report import LIVE5_SYMBOLS
from src.domain.canonical import sha256_hex

VERIFIED = "VERIFIED"
UNVERIFIED_UNIVERSE = "UNVERIFIED_UNIVERSE"
NOT_APPLICABLE = "NOT_APPLICABLE"

_ZERO = Decimal(0)
_LIVE5_ORDINAL = 0
_RESEARCH_ORDINAL = 1


@dataclass(frozen=True)
class DualUniverseView:
    """Live-5 vs research-universe CoreMetrics for one evidence kind."""

    evidence: EvidenceKind
    live5_symbols: tuple[str, ...]
    research_symbols: tuple[str, ...]
    universe_hash: str
    universe_status: str
    live5: CoreMetrics
    research: CoreMetrics
    live5_empty: bool
    weak_live_universe_rejection: bool

    def digest(self) -> str:
        return sha256_hex(
            {
                "evidence": self.evidence.value,
                "live5_symbols": list(self.live5_symbols),
                "research_symbols": list(self.research_symbols),
                "universe_hash": self.universe_hash,
                "universe_status": self.universe_status,
                "live5": self.live5.digest(),
                "research": self.research.digest(),
                "live5_empty": self.live5_empty,
                "weak_live_universe_rejection": self.weak_live_universe_rejection,
            }
        )


def _normalize_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
    for symbol in symbols:
        if not isinstance(symbol, str) or symbol == "":
            raise AnalyticsInputError(f"research symbol must be a non-empty str, got {symbol!r}")
    return tuple(sorted(set(symbols)))


def verify_research_universe(symbols: Sequence[str], expected_hash: str | None) -> str:
    """VERIFIED on a hash match, UNVERIFIED_UNIVERSE on mismatch, NOT_APPLICABLE without one.

    The hash is the Phase-6 `_universe_hash` over the sorted, de-duplicated symbols,
    compared with the recorded `ExperimentRecord.universe_hash`.
    """
    if expected_hash is None:
        return NOT_APPLICABLE
    if _universe_hash(_normalize_symbols(symbols)) == expected_hash:
        return VERIFIED
    return UNVERIFIED_UNIVERSE


def build_dual_universe(
    outcomes: Sequence[TradeOutcome],
    *,
    evidence: EvidenceKind,
    research_symbols: Sequence[str],
    expected_universe_hash: str | None = None,
    base_seed: int,
    resamples: int,
) -> DualUniverseView:
    """Build the side-by-side view; another evidence kind fails closed."""
    for outcome in outcomes:
        if outcome.evidence is not evidence:
            raise AnalyticsInputError(
                f"outcome {outcome.trade_id!r} has evidence {outcome.evidence.value}, "
                f"expected {evidence.value} (evidence kinds are never pooled)"
            )
    research = _normalize_symbols(research_symbols)
    research_set = frozenset(research)
    live5_outcomes = [o for o in outcomes if o.symbol in LIVE5_SYMBOLS]
    research_outcomes = [o for o in outcomes if o.symbol in research_set]
    live5_metrics = compute_core_metrics(
        live5_outcomes, base_seed=base_seed, resamples=resamples, ordinal=_LIVE5_ORDINAL
    )
    research_metrics = compute_core_metrics(
        research_outcomes, base_seed=base_seed, resamples=resamples, ordinal=_RESEARCH_ORDINAL
    )
    live5_mean = live5_metrics.mean_r.value
    research_mean = research_metrics.mean_r.value
    weak = (
        research_mean is not None
        and live5_mean is not None
        and research_mean > _ZERO
        and live5_mean <= _ZERO
    )
    return DualUniverseView(
        evidence=evidence,
        live5_symbols=tuple(sorted(LIVE5_SYMBOLS)),
        research_symbols=research,
        universe_hash=_universe_hash(research),
        universe_status=verify_research_universe(research, expected_universe_hash),
        live5=live5_metrics,
        research=research_metrics,
        live5_empty=len(live5_outcomes) == 0,
        weak_live_universe_rejection=weak,
    )
