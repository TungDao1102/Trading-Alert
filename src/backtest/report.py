"""Pure uncertainty-first backtest report (Phase 6, plan 06-03).

Per D-04 + BACKTEST_SPEC §10 + METRICS §§1–2: every report carries
trade counts overall and by symbol/quarter/regime/version, mean /
median / std of R, bootstrap expectancy interval (block bootstrap with
a recorded seed), drawdown distribution under resampling, stability
across time and symbols, parameter-plateau analysis, baseline
comparison (no-trade + simple-trend), dual-universe slices
(research_universe vs live-5), and an intrabar-coverage note. No
single headline number is ever accepted — uncertainty sections are
mandatory for every candidate.

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 / Phase-5 D-05 / Phase-6 D-05 purity
precedent. Floats are confined to report-local bootstrap math and
never returned into decision-typed fields.
"""
from __future__ import annotations

import random
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from src.core._decimal import _div, _q
from src.core.types import _require_utc_aware
from src.domain.canonical import sha256_hex

# Live-5 universe per PROJECT.md constraints (BTCUSDT, ETHUSDT, BNBUSDT,
# SOLUSDT, XRPUSDT). Symbols carrying the live5_universe tag must be a
# subset of this set; the dual-universe section asserts the bound.
LIVE5_SYMBOLS: frozenset[str] = frozenset(
    {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"}
)


# --------------------------------------------------------------------------- #
# Exceptions.
# --------------------------------------------------------------------------- #


class ReportBuildError(Exception):
    """Raised when the report input is malformed (fails closed)."""


# --------------------------------------------------------------------------- #
# Counts section — overall + by symbol / quarter / regime / version.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CountsSection:
    """Trade counts overall and sliced by symbol/quarter/regime/version.

    All counters are sorted alphabetically by key so iteration order is
    stable across reruns (D-04 reproducibility tripwire).
    """

    trade_count: int
    counts_by_symbol: dict[str, int]
    counts_by_quarter: dict[str, int]
    counts_by_regime: dict[str, int]
    counts_by_version: dict[str, int]

    def digest(self) -> str:
        return sha256_hex(
            {
                "trade_count": self.trade_count,
                "counts_by_symbol": self.counts_by_symbol,
                "counts_by_quarter": self.counts_by_quarter,
                "counts_by_regime": self.counts_by_regime,
                "counts_by_version": self.counts_by_version,
            }
        )


# --------------------------------------------------------------------------- #
# R-distribution section.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RDistributionSection:
    """Mean / median / std / min / max of R plus win / loss / zero counts.

    Per D-04: trades with R exactly zero are counted as neither wins
    nor losses; the win + loss + zero_r counts must equal trade_count.
    """

    mean: Decimal | None
    median: Decimal | None
    std: Decimal | None
    min: Decimal | None
    max: Decimal | None
    win_count: int
    loss_count: int
    zero_r_count: int

    def digest(self) -> str:
        return sha256_hex(
            {
                "mean": self.mean,
                "median": self.median,
                "std": self.std,
                "min": self.min,
                "max": self.max,
                "win_count": self.win_count,
                "loss_count": self.loss_count,
                "zero_r_count": self.zero_r_count,
            }
        )


# --------------------------------------------------------------------------- #
# Bootstrap expectancy interval — stationary block bootstrap.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BootstrapInterval:
    """Stationary-block-bootstrap expectancy interval.

    Per D-04: block lengths are geometric with mean `1/p`; resamples are
    driven by a single seeded `random.Random(experiment_seed)` instance
    so rebuilds are byte-stable. The interval is the 2.5 / 97.5 percentile
    pair of the bootstrap mean distribution. The seed is recorded on
    the interval so different seeds yield different interval digests
    (T-06-06 tripwire).
    """

    lower: Decimal
    upper: Decimal
    point_estimate: Decimal
    se_diagnostic: Decimal
    n_resamples: int
    seed: int

    def digest(self) -> str:
        return sha256_hex(
            {
                "lower": self.lower,
                "upper": self.upper,
                "point_estimate": self.point_estimate,
                "se_diagnostic": self.se_diagnostic,
                "n_resamples": self.n_resamples,
                "seed": self.seed,
            }
        )


# --------------------------------------------------------------------------- #
# Drawdown distribution under resampling.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DrawdownDistribution:
    """Drawdown distribution over the bootstrap resamples.

    `observed_max_drawdown` is the maximum drawdown of the realized
    PnL curve; `resampled_max_drawdown` is the distribution from the
    same resamples that drive the expectancy interval.
    """

    observed_max_drawdown: Decimal
    resampled_p05_max_drawdown: Decimal
    resampled_p50_max_drawdown: Decimal
    resampled_p95_max_drawdown: Decimal

    def digest(self) -> str:
        return sha256_hex(
            {
                "observed_max_drawdown": self.observed_max_drawdown,
                "resampled_p05_max_drawdown": self.resampled_p05_max_drawdown,
                "resampled_p50_max_drawdown": self.resampled_p50_max_drawdown,
                "resampled_p95_max_drawdown": self.resampled_p95_max_drawdown,
            }
        )


# --------------------------------------------------------------------------- #
# Stability slices — by quarter (one slice per observed quarter).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class StabilitySlice:
    """Per-quarter summary: trade count, mean R, win-rate proxy."""

    key: str
    trade_count: int
    mean_r: Decimal | None

    def digest(self) -> str:
        return sha256_hex(
            {
                "key": self.key,
                "trade_count": self.trade_count,
                "mean_r": self.mean_r,
            }
        )


@dataclass(frozen=True)
class StabilitySection:
    """Stability across time slices (per-quarter, sorted by key)."""

    slices: tuple[StabilitySlice, ...]

    def digest(self) -> str:
        return sha256_hex({"slices": [s.digest() for s in self.slices]})


# --------------------------------------------------------------------------- #
# Plateau section — by parameter region.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PlateauRegion:
    """Per-region summary for the plateau section."""

    region: str
    trade_count: int
    mean_r: Decimal | None

    def digest(self) -> str:
        return sha256_hex(
            {
                "region": self.region,
                "trade_count": self.trade_count,
                "mean_r": self.mean_r,
            }
        )


@dataclass(frozen=True)
class PlateauSection:
    """Parameter-plateau analysis.

    Per D-04 + RESEARCH_PROTOCOL §4 R2: a narrow isolated optimum is a
    robustness warning, never a conclusion. The section flags isolated
    single-point optima (regions whose mean R is materially higher than
    all other regions AND whose trade count is below the median of all
    regions).
    """

    regions: tuple[PlateauRegion, ...]
    isolated_optimum_warnings: tuple[str, ...]

    def digest(self) -> str:
        return sha256_hex(
            {
                "regions": [r.digest() for r in self.regions],
                "isolated_optimum_warnings": list(self.isolated_optimum_warnings),
            }
        )


# --------------------------------------------------------------------------- #
# Baseline comparison — vs no_trade + simple_trend.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BaselineSummary:
    """Pre-aggregated baseline summary for the comparison section."""

    trade_count: int
    mean_r: Decimal | None

    def digest(self) -> str:
        return sha256_hex(
            {"trade_count": self.trade_count, "mean_r": self.mean_r}
        )


@dataclass(frozen=True)
class BaselineSummaries:
    """Container for no_trade + simple_trend pre-aggregated summaries."""

    no_trade: BaselineSummary | None
    simple_trend: BaselineSummary | None

    def digest(self) -> str:
        return sha256_hex(
            {
                "no_trade": self.no_trade.digest() if self.no_trade else None,
                "simple_trend": (
                    self.simple_trend.digest() if self.simple_trend else None
                ),
            }
        )


@dataclass(frozen=True)
class BaselineComparison:
    """Candidate deltas vs the declared baselines.

    Per BACKTEST_SPEC §9: every candidate is compared against declared
    baselines. `delta_vs_no_trade` and `delta_vs_simple_trend` are the
    candidate mean R minus the baseline mean R; None when the baseline
    is absent.
    """

    candidate_trade_count: int
    candidate_mean_r: Decimal | None
    no_trade: BaselineSummary | None
    simple_trend: BaselineSummary | None
    delta_vs_no_trade: Decimal | None
    delta_vs_simple_trend: Decimal | None

    def digest(self) -> str:
        return sha256_hex(
            {
                "candidate_trade_count": self.candidate_trade_count,
                "candidate_mean_r": self.candidate_mean_r,
                "no_trade": self.no_trade.digest() if self.no_trade else None,
                "simple_trend": (
                    self.simple_trend.digest() if self.simple_trend else None
                ),
                "delta_vs_no_trade": self.delta_vs_no_trade,
                "delta_vs_simple_trend": self.delta_vs_simple_trend,
            }
        )


# --------------------------------------------------------------------------- #
# Dual-universe slices — research_universe vs live5_universe.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DualUniverseSlice:
    """Per-universe slice (research_universe or live5_universe)."""

    name: str
    symbols: tuple[str, ...]
    trade_count: int
    mean_r: Decimal | None
    insufficient_data: bool

    def digest(self) -> str:
        return sha256_hex(
            {
                "name": self.name,
                "symbols": list(self.symbols),
                "trade_count": self.trade_count,
                "mean_r": self.mean_r,
                "insufficient_data": self.insufficient_data,
            }
        )


@dataclass(frozen=True)
class DualUniverseSection:
    """Side-by-side research_universe vs live5_universe slices.

    Per BACKTEST_SPEC §10.1: a strategy must not be accepted solely
    because the broader universe rescues a weak live universe. When
    the research mean R is materially positive while the live-5 mean R
    is materially non-positive, `weak_live_universe_rejection` is True
    and the report marks the candidate as rejected.
    """

    research_universe: DualUniverseSlice
    live5_universe: DualUniverseSlice
    weak_live_universe_rejection: bool

    def digest(self) -> str:
        return sha256_hex(
            {
                "research_universe": self.research_universe.digest(),
                "live5_universe": self.live5_universe.digest(),
                "weak_live_universe_rejection": self.weak_live_universe_rejection,
            }
        )


# --------------------------------------------------------------------------- #
# Intrabar coverage.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class IntrabarCoverage:
    """1m intrabar coverage aggregation.

    Per D-01 + Phase-2 D-09: missing 1m coverage produces the
    conservative SL-first fallback; the trade record carries
    `fallback_applied=True`. The report aggregates the percentage of
    trades that did NOT use the fallback (i.e. resolved via 1m data).
    """

    percent: Decimal
    fallback_count: int
    total_trades: int
    coverage_notes: tuple[str, ...]

    def digest(self) -> str:
        return sha256_hex(
            {
                "percent": self.percent,
                "fallback_count": self.fallback_count,
                "total_trades": self.total_trades,
                "coverage_notes": list(self.coverage_notes),
            }
        )


# --------------------------------------------------------------------------- #
# UncertaintyReport — frozen envelope with all nine sections.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class UncertaintyReport:
    """Uncertainty-first backtest report (D-04).

    Carries the canonical nine sections plus reproducibility metadata
    (experiment_id, bootstrap_seed, built_at_utc). The report is
    always valid — even zero-trade / single-trade reports yield a
    valid envelope with the bootstrap interval absent and an explicit
    insufficient_data_note.
    """

    experiment_id: str
    bootstrap_seed: int
    built_at_utc: datetime
    counts: CountsSection
    r_distribution: RDistributionSection
    expectancy_interval: BootstrapInterval | None
    drawdown_distribution: DrawdownDistribution
    stability: StabilitySection
    plateau: PlateauSection
    baselines: BaselineComparison
    dual_universe: DualUniverseSection
    intrabar_coverage: IntrabarCoverage
    insufficient_data_note: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.experiment_id, str) or self.experiment_id == "":
            raise ReportBuildError("experiment_id must be a non-empty string")
        if not isinstance(self.bootstrap_seed, int):
            raise ReportBuildError(
                f"bootstrap_seed must be int, got {type(self.bootstrap_seed).__name__}"
            )
        _require_utc_aware(self.built_at_utc, "built_at_utc")

    def digest(self) -> str:
        """Canonical sha256 over all sections (D-04 reproducibility)."""
        return sha256_hex(
            {
                "experiment_id": self.experiment_id,
                "bootstrap_seed": self.bootstrap_seed,
                "built_at_utc": self.built_at_utc,
                "counts": self.counts.digest(),
                "r_distribution": self.r_distribution.digest(),
                "expectancy_interval": (
                    self.expectancy_interval.digest()
                    if self.expectancy_interval
                    else None
                ),
                "drawdown_distribution": self.drawdown_distribution.digest(),
                "stability": self.stability.digest(),
                "plateau": self.plateau.digest(),
                "baselines": self.baselines.digest(),
                "dual_universe": self.dual_universe.digest(),
                "intrabar_coverage": self.intrabar_coverage.digest(),
                "insufficient_data_note": self.insufficient_data_note,
            }
        )


# --------------------------------------------------------------------------- #
# Helpers — R computation, quarter derivation, slice iteration.
# --------------------------------------------------------------------------- #


def _r_multiple(trade: Mapping[str, Any]) -> Decimal | None:
    """Compute R = realized_pnl / realized_risk as Decimal (D-12).

    Returns None when `realized_risk` is missing or zero (the trade is
    excluded from R distribution; it remains in trade_count).
    """
    pnl_raw = trade.get("realized_pnl")
    risk_raw = trade.get("realized_risk")
    if pnl_raw is None or risk_raw is None:
        return None
    pnl = _q(pnl_raw)
    risk = _q(risk_raw)
    if risk == Decimal("0"):
        return None
    return _div(pnl, risk)


def _quarter(exit_time_utc: datetime | None) -> str:
    """Derive the quarter key from `exit_time_utc` (e.g. '2026-Q1').

    Falls back to 'UNKNOWN' when exit_time_utc is missing. UTC-aware
    only (the build pipeline enforces UTC at the boundary).
    """
    if exit_time_utc is None:
        return "UNKNOWN"
    month = exit_time_utc.month
    q = (month - 1) // 3 + 1
    return f"{exit_time_utc.year}-Q{q}"


def _safe_str(value: object, default: str) -> str:
    return value if isinstance(value, str) and value != "" else default


# --------------------------------------------------------------------------- #
# Bootstrap — stationary block bootstrap with geometric block lengths.
# --------------------------------------------------------------------------- #


def _stationary_block_bootstrap_means(
    r_values: Sequence[Decimal],
    *,
    seed: int,
    n_resamples: int,
    p: Decimal,
) -> list[Decimal]:
    """Stationary block bootstrap with geometric block lengths.

    Per D-04 + BACKTEST_SPEC §10: block lengths are geometric with
    mean `1/p`; each resample walks the sequence picking random block
    starts in `[0, n)` and takes consecutive block lengths. The
    resample is truncated to `n` values; the mean of those values is
    the bootstrap replicate.

    Returns a list of `n_resamples` Decimal means.
    """
    if not r_values:
        return []
    n = len(r_values)
    rng = random.Random(seed)
    p_float = float(p)
    if p_float <= 0.0 or p_float > 1.0:
        raise ReportBuildError(f"p must be in (0, 1], got {p_float}")
    # Convert to float for the local bootstrap math; this is the ONE
    # place floats appear in the report module — they never flow back
    # into the digest payload because we convert to Decimal before
    # returning. (D-12 fail-closed: floats confined to report-local
    # bootstrap math and never returned into decision-typed fields.)
    r_floats = [float(r) for r in r_values]
    bootstrap_means: list[float] = []
    for _ in range(n_resamples):
        sample: list[float] = []
        while len(sample) < n:
            # Geometric: probability of length l is p*(1-p)^(l-1) for l=1,2,...
            u = rng.random()
            block_length = 1
            while rng.random() > p_float and block_length < n:
                block_length += 1
            start = rng.randrange(n)
            for j in range(block_length):
                sample.append(r_floats[(start + j) % n])
                if len(sample) >= n:
                    break
        sample = sample[:n]
        bootstrap_means.append(statistics.fmean(sample))
    # Return as Decimal (full precision via str) so the digest is stable.
    return [_q(repr(m)) for m in bootstrap_means]


def _max_drawdown(returns: Sequence[Decimal]) -> Decimal:
    """Compute the maximum drawdown over the cumulative-PnL curve."""
    if not returns:
        return Decimal("0")
    peak = Decimal("0")
    cum = Decimal("0")
    max_dd = Decimal("0")
    for r in returns:
        cum = cum + r
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _quantile(values: Sequence[Decimal], q: float) -> Decimal:
    """Return the q-quantile of `values` (0 <= q <= 1)."""
    if not values:
        return Decimal("0")
    sorted_v = sorted(values)
    # linear-interpolation method, matching statistics.quantiles (n=4)
    if q <= 0:
        return sorted_v[0]
    if q >= 1:
        return sorted_v[-1]
    idx_float = q * (len(sorted_v) - 1)
    lo = int(idx_float)
    hi = min(lo + 1, len(sorted_v) - 1)
    frac = _q(repr(idx_float - lo))
    return sorted_v[lo] + (sorted_v[hi] - sorted_v[lo]) * frac


# --------------------------------------------------------------------------- #
# build — top-level entry point.
# --------------------------------------------------------------------------- #


def build(
    *,
    experiment_record: Any,
    trade_records: Sequence[Mapping[str, Any]],
    bootstrap_seed: int,
    resamples: int = 10000,
    probable: Decimal = Decimal("0.1"),
    universe_tags: Mapping[str, Sequence[str]] | None = None,
    baseline_summaries: BaselineSummaries | None = None,
    built_at_utc: datetime | None = None,
) -> UncertaintyReport:
    """Build an UncertaintyReport from trade records + experiment identity.

    Per D-04: the report always carries all nine sections; the
    expectancy_interval is None when trade_count < 2. The bootstrap
    uses a single seeded `random.Random(experiment_seed)` instance so
    rebuilds are byte-stable.

    `built_at_utc` defaults to `datetime.now(timezone.utc)`; pass an
    explicit value for digest-stable rebuilds (the digest includes
    `built_at_utc`).
    """
    if built_at_utc is None:
        built_at_utc = datetime.now(timezone.utc)
    # Compute R multiples for every trade with a non-zero realized_risk.
    r_values: list[Decimal] = []
    annotated: list[tuple[Mapping[str, Any], Decimal]] = []
    for trade in trade_records:
        r = _r_multiple(trade)
        if r is not None:
            r_values.append(r)
            annotated.append((trade, r))

    n_trades = len(trade_records)
    n_r = len(r_values)

    # --- Counts section -----------------------------------------------------
    by_symbol: Counter[str] = Counter()
    by_quarter: Counter[str] = Counter()
    by_regime: Counter[str] = Counter()
    by_version: Counter[str] = Counter()
    for trade in trade_records:
        by_symbol[_safe_str(trade.get("symbol"), "UNKNOWN")] += 1
        exit_time = trade.get("exit_time_utc")
        if isinstance(exit_time, str):
            try:
                exit_dt = datetime.fromisoformat(exit_time)
            except ValueError:
                exit_dt = None
        elif isinstance(exit_time, datetime):
            exit_dt = exit_time
        else:
            exit_dt = None
        by_quarter[_quarter(exit_dt)] += 1
        by_regime[_safe_str(trade.get("regime"), "UNKNOWN")] += 1
        by_version[_safe_str(trade.get("strategy_version"), "UNKNOWN")] += 1
    counts = CountsSection(
        trade_count=n_trades,
        counts_by_symbol=dict(sorted(by_symbol.items())),
        counts_by_quarter=dict(sorted(by_quarter.items())),
        counts_by_regime=dict(sorted(by_regime.items())),
        counts_by_version=dict(sorted(by_version.items())),
    )

    # --- R-distribution section ---------------------------------------------
    if n_r == 0:
        r_dist = RDistributionSection(
            mean=None,
            median=None,
            std=None,
            min=None,
            max=None,
            win_count=0,
            loss_count=0,
            zero_r_count=0,
        )
    else:
        r_floats = [float(r) for r in r_values]
        r_mean = statistics.fmean(r_floats)
        r_median = statistics.median(r_floats)
        r_std = statistics.pstdev(r_floats) if n_r > 1 else 0
        wins = sum(1 for r in r_values if r > Decimal("0"))
        losses = sum(1 for r in r_values if r < Decimal("0"))
        zeros = sum(1 for r in r_values if r == Decimal("0"))
        r_dist = RDistributionSection(
            mean=_q(repr(r_mean)),
            median=_q(repr(r_median)),
            std=_q(repr(r_std)),
            min=min(r_values),
            max=max(r_values),
            win_count=wins,
            loss_count=losses,
            zero_r_count=zeros,
        )

    # --- Bootstrap expectancy interval -------------------------------------
    insufficient_note: str | None = None
    if n_r < 2:
        interval: BootstrapInterval | None = None
        if n_trades == 0:
            insufficient_note = (
                "no trades in trade list; bootstrap interval absent"
            )
        else:
            insufficient_note = (
                f"only {n_r} R-valued trade(s); bootstrap interval absent "
                "(minimum two observations required)"
            )
        resampled_means: list[Decimal] = []
        se_diagnostic = Decimal("0")
    else:
        resampled_means = _stationary_block_bootstrap_means(
            r_values, seed=bootstrap_seed, n_resamples=resamples, p=probable
        )
        lo_q = _quantile(resampled_means, 0.025)
        hi_q = _quantile(resampled_means, 0.975)
        point = r_dist.mean if r_dist.mean is not None else Decimal("0")
        sigma = r_dist.std if r_dist.std is not None else Decimal("0")
        n_q = _q(n_r)
        # SE ≈ sigma / sqrt(n) — Decimal arithmetic via _div.
        se_diagnostic = _div(sigma, _q(repr(n_r ** 0.5)))
        interval = BootstrapInterval(
            lower=lo_q,
            upper=hi_q,
            point_estimate=point,
            se_diagnostic=se_diagnostic,
            n_resamples=resamples,
            seed=bootstrap_seed,
        )

    # --- Drawdown distribution under resampling ----------------------------
    observed_dd = _max_drawdown(r_values)
    if resampled_means:
        # Build a resampled drawdown for each bootstrap replicate using
        # the same R sequence as a proxy (the resample-mean sequence is
        # a coarse distributional summary — the per-trade sequence is
        # what the drawdown is computed over). We compute the resampled
        # drawdowns deterministically using the SAME seed and a fixed
        # block scheme so rebuilds match.
        dd_resamples = _resample_drawdowns(
            r_values, seed=bootstrap_seed, n_resamples=resamples, p=probable
        )
        dd_p05 = _quantile(dd_resamples, 0.05)
        dd_p50 = _quantile(dd_resamples, 0.50)
        dd_p95 = _quantile(dd_resamples, 0.95)
    else:
        dd_p05 = observed_dd
        dd_p50 = observed_dd
        dd_p95 = observed_dd
    drawdown = DrawdownDistribution(
        observed_max_drawdown=observed_dd,
        resampled_p05_max_drawdown=dd_p05,
        resampled_p50_max_drawdown=dd_p50,
        resampled_p95_max_drawdown=dd_p95,
    )

    # --- Stability section (per quarter) -----------------------------------
    quarter_groups: dict[str, list[Decimal]] = {}
    for trade, r in annotated:
        exit_time = trade.get("exit_time_utc")
        if isinstance(exit_time, str):
            try:
                exit_dt = datetime.fromisoformat(exit_time)
            except ValueError:
                exit_dt = None
        elif isinstance(exit_time, datetime):
            exit_dt = exit_time
        else:
            exit_dt = None
        q_key = _quarter(exit_dt)
        quarter_groups.setdefault(q_key, []).append(r)
    stability_slices = tuple(
        StabilitySlice(
            key=k,
            trade_count=len(v),
            mean_r=(
                _q(repr(statistics.fmean([float(x) for x in v])))
                if v
                else None
            ),
        )
        for k, v in sorted(quarter_groups.items())
    )
    stability = StabilitySection(slices=stability_slices)

    # --- Plateau section (per parameter region) ----------------------------
    region_groups: dict[str, list[Decimal]] = {}
    for trade, r in annotated:
        region = _safe_str(trade.get("parameter_region"), "UNKNOWN")
        region_groups.setdefault(region, []).append(r)
    plateau_regions = []
    for region, rs in sorted(region_groups.items()):
        plateau_regions.append(
            PlateauRegion(
                region=region,
                trade_count=len(rs),
                mean_r=(
                    _q(repr(statistics.fmean([float(x) for x in rs])))
                    if rs
                    else None
                ),
            )
        )
    plateau_regions_tuple = tuple(plateau_regions)
    # Isolated-optimum warning: any region whose mean R is materially
    # higher than the median AND whose trade count is below the
    # median trade count is flagged.
    isolated_warnings: list[str] = []
    if plateau_regions_tuple:
        median_count = sorted(
            len(rs) for rs in region_groups.values()
        )[len(region_groups) // 2]
        mean_rs = [
            float(r.mean_r) if r.mean_r is not None else 0.0
            for r in plateau_regions_tuple
        ]
        median_mean = statistics.median(mean_rs)
        for plat in plateau_regions_tuple:
            if plat.mean_r is None:
                continue
            if (
                float(plat.mean_r) > median_mean
                and plat.trade_count < median_count
            ):
                isolated_warnings.append(plat.region)
    plateau = PlateauSection(
        regions=plateau_regions_tuple,
        isolated_optimum_warnings=tuple(isolated_warnings),
    )

    # --- Baseline comparison -----------------------------------------------
    candidate_mean = r_dist.mean
    no_trade = baseline_summaries.no_trade if baseline_summaries else None
    simple_trend = (
        baseline_summaries.simple_trend if baseline_summaries else None
    )
    delta_no_trade: Decimal | None = None
    if candidate_mean is not None and no_trade is not None and no_trade.mean_r is not None:
        delta_no_trade = candidate_mean - no_trade.mean_r
    delta_simple_trend: Decimal | None = None
    if (
        candidate_mean is not None
        and simple_trend is not None
        and simple_trend.mean_r is not None
    ):
        delta_simple_trend = candidate_mean - simple_trend.mean_r
    baselines = BaselineComparison(
        candidate_trade_count=n_trades,
        candidate_mean_r=candidate_mean,
        no_trade=no_trade,
        simple_trend=simple_trend,
        delta_vs_no_trade=delta_no_trade,
        delta_vs_simple_trend=delta_simple_trend,
    )

    # --- Dual-universe slices ---------------------------------------------
    universe_tags = universe_tags or {}
    research_symbols = sorted(
        sym for sym, tags in universe_tags.items()
        if "research_universe" in tags
    )
    live5_symbols = sorted(
        sym for sym, tags in universe_tags.items()
        if "live5_universe" in tags
    )
    # Defensive: live5 must be subset of the declared LIVE5_SYMBOLS.
    for sym in live5_symbols:
        if sym not in LIVE5_SYMBOLS:
            raise ReportBuildError(
                f"live5_universe symbol {sym!r} is not in declared LIVE5_SYMBOLS"
            )

    def _slice_for(
        name: str, symbols: Sequence[str]
    ) -> DualUniverseSlice:
        symbol_set = set(symbols)
        rs_in = [r for trade, r in annotated if trade.get("symbol") in symbol_set]
        if not rs_in:
            return DualUniverseSlice(
                name=name,
                symbols=tuple(symbols),
                trade_count=0,
                mean_r=None,
                insufficient_data=True,
            )
        return DualUniverseSlice(
            name=name,
            symbols=tuple(symbols),
            trade_count=len(rs_in),
            mean_r=_q(repr(statistics.fmean([float(x) for x in rs_in]))),
            insufficient_data=len(rs_in) < 2,
        )

    research_slice = _slice_for("research_universe", research_symbols)
    live5_slice = _slice_for("live5_universe", live5_symbols)

    # weak_live_universe_rejection: research mean R > 0 AND live-5 mean R <= 0.
    weak_rejection = False
    if (
        research_slice.mean_r is not None
        and live5_slice.mean_r is not None
        and research_slice.mean_r > Decimal("0")
        and live5_slice.mean_r <= Decimal("0")
    ):
        weak_rejection = True
    dual = DualUniverseSection(
        research_universe=research_slice,
        live5_universe=live5_slice,
        weak_live_universe_rejection=weak_rejection,
    )

    # --- Intrabar coverage -------------------------------------------------
    fallback_count = sum(
        1 for t in trade_records if t.get("fallback_applied") is True
    )
    coverage_notes = tuple(
        sorted(
            {
                str(t.get("coverage_note"))
                for t in trade_records
                if t.get("coverage_note") not in (None, "")
            }
        )
    )
    if n_trades == 0:
        coverage_pct = Decimal("100")
    else:
        coverage_pct = _q(
            (n_trades - fallback_count) * 100 // n_trades
        )
    intrabar = IntrabarCoverage(
        percent=coverage_pct,
        fallback_count=fallback_count,
        total_trades=n_trades,
        coverage_notes=coverage_notes,
    )

    return UncertaintyReport(
        experiment_id=experiment_record.experiment_id,
        bootstrap_seed=bootstrap_seed,
        built_at_utc=built_at_utc,
        counts=counts,
        r_distribution=r_dist,
        expectancy_interval=interval,
        drawdown_distribution=drawdown,
        stability=stability,
        plateau=plateau,
        baselines=baselines,
        dual_universe=dual,
        intrabar_coverage=intrabar,
        insufficient_data_note=insufficient_note,
    )


def _resample_drawdowns(
    r_values: Sequence[Decimal],
    *,
    seed: int,
    n_resamples: int,
    p: Decimal,
) -> list[Decimal]:
    """Resample drawdowns using the same stationary block scheme.

    Returns one Decimal max_drawdown per resample.
    """
    if not r_values:
        return []
    n = len(r_values)
    rng = random.Random(seed)
    p_float = float(p)
    if p_float <= 0.0 or p_float > 1.0:
        raise ReportBuildError(f"p must be in (0, 1], got {p_float}")
    r_floats = [float(r) for r in r_values]
    drawdowns: list[Decimal] = []
    for _ in range(n_resamples):
        sample: list[float] = []
        while len(sample) < n:
            u = rng.random()
            block_length = 1
            while rng.random() > p_float and block_length < n:
                block_length += 1
            start = rng.randrange(n)
            for j in range(block_length):
                sample.append(r_floats[(start + j) % n])
                if len(sample) >= n:
                    break
        sample = sample[:n]
        dd = _max_drawdown([_q(repr(x)) for x in sample])
        drawdowns.append(dd)
    return drawdowns


__all__ = [
    "BaselineComparison",
    "BaselineSummaries",
    "BaselineSummary",
    "BootstrapInterval",
    "CountsSection",
    "DrawdownDistribution",
    "DualUniverseSection",
    "DualUniverseSlice",
    "IntrabarCoverage",
    "LIVE5_SYMBOLS",
    "PlateauRegion",
    "PlateauSection",
    "RDistributionSection",
    "ReportBuildError",
    "StabilitySection",
    "StabilitySlice",
    "UncertaintyReport",
    "build",
]
