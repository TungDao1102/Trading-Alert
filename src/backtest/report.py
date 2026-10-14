"""Pure uncertainty-first backtest report (Phase 6, plan 06-03).

Per D-04 + BACKTEST_SPEC §10 + METRICS §§1–2: every report carries
trade counts overall and by symbol/quarter/regime/version, mean /
median / std of R, bootstrap expectancy interval (block bootstrap with
a recorded seed), drawdown distribution under resampling, stability
across time and symbols, a parameter-plateau section, baseline
comparison (no-trade + simple-trend), dual-universe slices
(research_universe vs live-5), and an intrabar-coverage note. No
single headline number is ever accepted — uncertainty sections are
mandatory for every candidate.

Plan 14-11 (D-34, D-37, D-21): only CLOSED FILLED trades (outcome OK, a filled entry,
exit_kind SL or TP2) are trades. They alone feed trade_count, the R distribution, the
bootstrap, drawdown, stability, baselines and the dual-universe slices, so a plan that
never filled can never inflate the trade floor. Positions the data end closed
(END_OF_DATA) and positions the terminal settlement closed (SETTLEMENT, quick 261014-nnl) are
each counted apart and kept out of the pooled R; non-fill plan outcomes (SETTLEMENT_CANCEL
among them) are counted by entry_kind. The plateau section is a fixed NOT_COMPUTED structure until
BKTS-03 exists: the report neither states nor implies plateau evidence.

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 / Phase-5 D-05 / Phase-6 D-05 purity
precedent. No float call, literal, or numpy float attr appears in
this file (no-float AST guard, D-12).
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.core._decimal import _add, _div, _mul, _q, _sub
from src.core.types import _require_utc_aware
from src.domain.canonical import sha256_hex

from .semantics import (
    ENTRY_FILLED,
    EXIT_END_OF_DATA,
    EXIT_SETTLEMENT,
    EXIT_SL,
    EXIT_TP2,
    PARTIAL_FILL,
)

LIVE5_SYMBOLS: frozenset[str] = frozenset({"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"})

_MAX_BLOCK_LENGTH = 10000
_FILLED_ENTRY_KINDS = frozenset({ENTRY_FILLED, PARTIAL_FILL})
_CLOSED_EXIT_KINDS = frozenset({EXIT_SL, EXIT_TP2})
PLATEAU_STATUS_NOT_COMPUTED = "NOT_COMPUTED"
PLATEAU_NOTE = "not computed (BKTS-03 pending)"
_RANDOM_BIT_WIDTH = 64


class ReportBuildError(Exception):
    """Raised when the report input is malformed (fails closed)."""


@dataclass(frozen=True)
class CountsSection:
    """Closed-trade counts overall and sliced by symbol/quarter/regime/version.

    `trade_count` and every slice cover closed filled trades only (D-37).
    `end_of_data_count` counts positions the data end closed; `settlement_count` counts
    positions the terminal settlement closed (never a closed trade; it joins the digest payload
    only when non-zero, so every settlement-free digest is unchanged); `plan_outcome_counts`
    counts plans that never filled, keyed by `entry_kind` (sorted).
    """

    trade_count: int
    counts_by_symbol: dict[str, int]
    counts_by_quarter: dict[str, int]
    counts_by_regime: dict[str, int]
    counts_by_version: dict[str, int]
    end_of_data_count: int
    plan_outcome_counts: dict[str, int]
    settlement_count: int = 0

    def digest(self) -> str:
        payload: dict[str, Any] = {
            "trade_count": self.trade_count,
            "end_of_data_count": self.end_of_data_count,
            "plan_outcome_counts": self.plan_outcome_counts,
            "counts_by_symbol": self.counts_by_symbol,
            "counts_by_quarter": self.counts_by_quarter,
            "counts_by_regime": self.counts_by_regime,
            "counts_by_version": self.counts_by_version,
        }
        if self.settlement_count:
            payload["settlement_count"] = self.settlement_count
        return sha256_hex(payload)


@dataclass(frozen=True)
class RDistributionSection:
    """Mean / median / std / min / max of R plus win / loss / zero counts."""

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


@dataclass(frozen=True)
class BootstrapInterval:
    """Stationary-block-bootstrap expectancy interval (D-04).

    Block lengths are geometric with mean `1/p`; resamples are driven
    by a single seeded `random.Random(experiment_seed)` instance so
    rebuilds are byte-stable. The interval is the 2.5 / 97.5
    percentile pair of the bootstrap mean distribution. The seed is
    recorded on the interval so different seeds yield different
    interval digests (T-06-06 tripwire).
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


@dataclass(frozen=True)
class DrawdownDistribution:
    """Drawdown distribution over the bootstrap resamples."""

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


@dataclass(frozen=True)
class StabilitySlice:
    """Per-quarter summary: trade count and mean R."""

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


@dataclass(frozen=True)
class PlateauSection:
    """Parameter-plateau section: always NOT_COMPUTED until BKTS-03 (D-21, D-37).

    A fixed structure with no regions and no warnings, whatever the trades are: a
    plateau needs a parameter sweep that does not exist yet, and an empty or
    single-region "analysis" would read as evidence.
    """

    status: str = PLATEAU_STATUS_NOT_COMPUTED
    note: str = PLATEAU_NOTE

    def digest(self) -> str:
        return sha256_hex({"status": self.status, "note": self.note})


@dataclass(frozen=True)
class BaselineSummary:
    """Pre-aggregated baseline summary for the comparison section."""

    trade_count: int
    mean_r: Decimal | None

    def digest(self) -> str:
        return sha256_hex({"trade_count": self.trade_count, "mean_r": self.mean_r})


@dataclass(frozen=True)
class BaselineSummaries:
    """Container for no_trade + simple_trend pre-aggregated summaries."""

    no_trade: BaselineSummary | None
    simple_trend: BaselineSummary | None

    def digest(self) -> str:
        return sha256_hex(
            {
                "no_trade": self.no_trade.digest() if self.no_trade else None,
                "simple_trend": (self.simple_trend.digest() if self.simple_trend else None),
            }
        )


@dataclass(frozen=True)
class BaselineComparison:
    """Candidate deltas vs the declared baselines (BACKTEST_SPEC §9)."""

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
                "simple_trend": (self.simple_trend.digest() if self.simple_trend else None),
                "delta_vs_no_trade": self.delta_vs_no_trade,
                "delta_vs_simple_trend": self.delta_vs_simple_trend,
            }
        )


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
    because the broader universe rescues a weak live universe.
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


@dataclass(frozen=True)
class IntrabarCoverage:
    """1m intrabar coverage aggregation (D-01 + Phase-2 D-09).

    Fallback can occur on a closed trade, on an END_OF_DATA trade or on a SETTLEMENT trade,
    so the population is all three; `closed_trades`, `end_of_data_trades` and
    `settlement_trades` state the three totals and `total_trades` is their sum.
    `settlement_trades` joins the digest payload only when non-zero (settlement-free digests
    are unchanged).
    """

    percent: Decimal
    fallback_count: int
    total_trades: int
    closed_trades: int
    end_of_data_trades: int
    coverage_notes: tuple[str, ...]
    settlement_trades: int = 0

    def digest(self) -> str:
        payload: dict[str, Any] = {
            "percent": self.percent,
            "fallback_count": self.fallback_count,
            "total_trades": self.total_trades,
            "closed_trades": self.closed_trades,
            "end_of_data_trades": self.end_of_data_trades,
            "coverage_notes": list(self.coverage_notes),
        }
        if self.settlement_trades:
            payload["settlement_trades"] = self.settlement_trades
        return sha256_hex(payload)


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
        return sha256_hex(
            {
                "experiment_id": self.experiment_id,
                "bootstrap_seed": self.bootstrap_seed,
                "built_at_utc": self.built_at_utc,
                "counts": self.counts.digest(),
                "r_distribution": self.r_distribution.digest(),
                "expectancy_interval": (
                    self.expectancy_interval.digest() if self.expectancy_interval else None
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


def _decimal_mean(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    total = Decimal("0")
    for v in values:
        total = _add(total, _q(v))
    return _div(total, _q(len(values)))


def _decimal_median(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    sorted_v = sorted(values)
    n = len(sorted_v)
    if n % 2 == 1:
        return sorted_v[n // 2]
    mid_lo = sorted_v[n // 2 - 1]
    mid_hi = sorted_v[n // 2]
    return _div(_add(mid_lo, mid_hi), Decimal("2"))


def _decimal_pstdev(values: Sequence[Decimal]) -> Decimal:
    if len(values) < 2:
        return Decimal("0")
    mean = _decimal_mean(values)
    sq_diffs = [_mul(_sub(_q(v), mean), _sub(_q(v), mean)) for v in values]
    total_sq = Decimal("0")
    for sq in sq_diffs:
        total_sq = _add(total_sq, sq)
    variance = _div(total_sq, _q(len(values)))
    return variance.sqrt()


def _r_multiple(trade: Mapping[str, Any]) -> Decimal | None:
    pnl_raw = trade.get("realized_pnl")
    risk_raw = trade.get("realized_risk")
    if pnl_raw is None or risk_raw is None:
        return None
    pnl = _q(pnl_raw)
    risk = _q(risk_raw)
    if risk == Decimal("0"):
        return None
    return _div(pnl, risk)


def _has_zero_risk(trade: Mapping[str, Any]) -> bool:
    """True when the trade carries an explicit realized_risk of zero.

    WR-10: `_r_multiple` drops these from the R distribution while
    `counts.trade_count` keeps them — the exclusion must be counted
    and surfaced, never silent.
    """
    risk_raw = trade.get("realized_risk")
    if risk_raw is None:
        return False
    try:
        return _q(risk_raw) == Decimal("0")
    except (TypeError, ValueError, ArithmeticError):
        return False


def _quarter(exit_time_utc: datetime | None) -> str:
    if exit_time_utc is None:
        return "UNKNOWN"
    month = exit_time_utc.month
    q = (month - 1) // 3 + 1
    return f"{exit_time_utc.year}-Q{q}"


def _safe_str(value: object, default: str) -> str:
    return value if isinstance(value, str) and value != "" else default


def _parse_exit_dt(trade: Mapping[str, Any]) -> datetime | None:
    exit_time = trade.get("exit_time_utc")
    if isinstance(exit_time, str):
        try:
            return datetime.fromisoformat(exit_time)
        except ValueError:
            return None
    if isinstance(exit_time, datetime):
        return exit_time
    return None


_EARLIEST = datetime.min.replace(tzinfo=UTC)


def _realized_order_key(trade: Mapping[str, Any]) -> tuple[datetime, str]:
    """Order key of a closed trade by realized time: `(exit_time_utc, trade_id)`."""
    exit_dt = _parse_exit_dt(trade)
    return (exit_dt if exit_dt is not None else _EARLIEST, str(trade.get("trade_id")))


def _sample_block_length(rng: random.Random, p: Decimal) -> int:
    if p <= Decimal("0") or p > Decimal("1"):
        raise ReportBuildError(f"p must be in (0, 1], got {p}")
    q = _sub(Decimal("1"), p)
    k = rng.getrandbits(_RANDOM_BIT_WIDTH)
    threshold = _div(Decimal(k), Decimal(2**_RANDOM_BIT_WIDTH))
    length = 1
    while length < _MAX_BLOCK_LENGTH:
        # `**` has no pinned helper; the base/subtrahend still route
        # through _sub so only the power itself is ambient-context.
        cdf_l = _sub(Decimal("1"), q**length)
        if threshold <= cdf_l:
            return length
        length += 1
    return _MAX_BLOCK_LENGTH


def _stationary_block_bootstrap_means(
    r_values: Sequence[Decimal],
    *,
    seed: int,
    n_resamples: int,
    p: Decimal,
) -> list[Decimal]:
    if not r_values:
        return []
    n = len(r_values)
    rng = random.Random(seed)
    bootstrap_means: list[Decimal] = []
    for _ in range(n_resamples):
        sample: list[Decimal] = []
        while len(sample) < n:
            block_length = _sample_block_length(rng, p)
            start = rng.randrange(n)
            for j in range(block_length):
                sample.append(r_values[(start + j) % n])
                if len(sample) >= n:
                    break
        bootstrap_means.append(_decimal_mean(sample))
    return bootstrap_means


def _max_drawdown(returns: Sequence[Decimal]) -> Decimal:
    if not returns:
        return Decimal("0")
    peak = Decimal("0")
    cum = Decimal("0")
    max_dd = Decimal("0")
    for r in returns:
        cum = _add(cum, _q(r))
        if cum > peak:
            peak = cum
        dd = _sub(peak, cum)
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _resample_drawdowns(
    r_values: Sequence[Decimal],
    *,
    seed: int,
    n_resamples: int,
    p: Decimal,
) -> list[Decimal]:
    if not r_values:
        return []
    n = len(r_values)
    rng = random.Random(seed)
    drawdowns: list[Decimal] = []
    for _ in range(n_resamples):
        sample: list[Decimal] = []
        while len(sample) < n:
            block_length = _sample_block_length(rng, p)
            start = rng.randrange(n)
            for j in range(block_length):
                sample.append(r_values[(start + j) % n])
                if len(sample) >= n:
                    break
        drawdowns.append(_max_drawdown(sample))
    return drawdowns


def _quantile(values: Sequence[Decimal], q: Decimal) -> Decimal:
    if not values:
        return Decimal("0")
    sorted_v = sorted(values)
    if q <= Decimal("0"):
        return sorted_v[0]
    if q >= Decimal("1"):
        return sorted_v[-1]
    last_idx = len(sorted_v) - 1
    idx_float = _mul(q, _q(last_idx))
    idx_int = int(idx_float)
    frac = _sub(idx_float, _q(idx_int))
    lo_idx = max(0, min(idx_int, last_idx))
    hi_idx = max(0, min(idx_int + 1, last_idx))
    return _add(sorted_v[lo_idx], _mul(_sub(sorted_v[hi_idx], sorted_v[lo_idx]), frac))


_TradeGroup = list[Mapping[str, Any]]


def _classify(
    trade_records: Sequence[Mapping[str, Any]],
) -> tuple[_TradeGroup, _TradeGroup, _TradeGroup, Counter[str]]:
    """Split records into closed, END_OF_DATA and SETTLEMENT trades and plan outcomes (D-34).

    A record that filled (outcome OK, entry ENTRY_FILLED or PARTIAL_FILL) must leave with
    SL, TP2, END_OF_DATA or SETTLEMENT; any other exit (a v1 TP1 or EOD, a missing or unknown
    kind) is refused, never counted as a trade of unknown meaning. Everything else is a plan
    outcome, counted by `entry_kind`.
    """
    closed: list[Mapping[str, Any]] = []
    end_of_data: list[Mapping[str, Any]] = []
    settlement: list[Mapping[str, Any]] = []
    plan_outcomes: Counter[str] = Counter()
    for trade in trade_records:
        entry_kind = trade.get("entry_kind")
        filled = trade.get("outcome_kind") == "OK" and entry_kind in _FILLED_ENTRY_KINDS
        if not filled:
            plan_outcomes[_safe_str(entry_kind, "UNKNOWN")] += 1
            continue
        exit_kind = trade.get("exit_kind")
        if exit_kind in _CLOSED_EXIT_KINDS:
            closed.append(trade)
        elif exit_kind == EXIT_END_OF_DATA:
            end_of_data.append(trade)
        elif exit_kind == EXIT_SETTLEMENT:
            settlement.append(trade)
        else:
            raise ReportBuildError(
                f"filled trade {trade.get('trade_id')!r} has exit_kind {exit_kind!r}: "
                f"expected one of "
                f"{sorted(_CLOSED_EXIT_KINDS | {EXIT_END_OF_DATA, EXIT_SETTLEMENT})}"
            )
    return closed, end_of_data, settlement, plan_outcomes


def build(
    *,
    experiment_record: Any,
    trade_records: Sequence[Mapping[str, Any]],
    bootstrap_seed: int,
    built_at_utc: datetime,
    resamples: int = 10000,
    probable: Decimal = Decimal("0.1"),
    universe_tags: Mapping[str, Sequence[str]] | None = None,
    baseline_summaries: BaselineSummaries | None = None,
) -> UncertaintyReport:
    """Build the uncertainty-first report (fail-closed on bad inputs).

    CR-08: `built_at_utc` is a REQUIRED explicit input — it enters the
    report digest, so a wall-clock default would make rebuilds
    non-reproducible. Callers pass a pinned timestamp (tests) or the
    experiment's recorded build time. `resamples`/`probable` are
    validated upfront (CR-12): a zero-resample "interval" would be a
    confident-looking [0, 0] lie over real data.
    """
    _require_utc_aware(built_at_utc, "built_at_utc")
    if not isinstance(resamples, int) or isinstance(resamples, bool) or resamples < 100:
        raise ReportBuildError(f"resamples must be int >= 100, got {resamples!r}")
    if not isinstance(probable, Decimal):
        raise ReportBuildError(f"probable must be Decimal in (0, 1], got {type(probable).__name__}")
    if not (Decimal("0") < probable <= Decimal("1")):
        raise ReportBuildError(f"probable must be in (0, 1], got {probable}")

    closed_trades, end_of_data_trades, settlement_trades, plan_outcomes = _classify(trade_records)
    # WR-06: the engine orders trades by signal close, but results are realized at exit, and
    # holding periods overlap. Drawdown, block bootstrap and stability walk the equity path,
    # so the closed trades are ordered by realized time (exit time, then trade id).
    closed_trades = sorted(closed_trades, key=_realized_order_key)

    r_values: list[Decimal] = []
    annotated: list[tuple[Mapping[str, Any], Decimal]] = []
    risk_zero_excluded = 0
    for trade in closed_trades:
        r = _r_multiple(trade)
        if r is not None:
            r_values.append(r)
            annotated.append((trade, r))
        elif _has_zero_risk(trade):
            risk_zero_excluded += 1

    n_trades = len(closed_trades)
    n_r = len(r_values)

    by_symbol: Counter[str] = Counter()
    by_quarter: Counter[str] = Counter()
    by_regime: Counter[str] = Counter()
    by_version: Counter[str] = Counter()
    for trade in closed_trades:
        by_symbol[_safe_str(trade.get("symbol"), "UNKNOWN")] += 1
        by_quarter[_quarter(_parse_exit_dt(trade))] += 1
        by_regime[_safe_str(trade.get("regime"), "UNKNOWN")] += 1
        by_version[_safe_str(trade.get("strategy_version"), "UNKNOWN")] += 1
    counts = CountsSection(
        trade_count=n_trades,
        counts_by_symbol=dict(sorted(by_symbol.items())),
        counts_by_quarter=dict(sorted(by_quarter.items())),
        counts_by_regime=dict(sorted(by_regime.items())),
        counts_by_version=dict(sorted(by_version.items())),
        end_of_data_count=len(end_of_data_trades),
        plan_outcome_counts=dict(sorted(plan_outcomes.items())),
        settlement_count=len(settlement_trades),
    )

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
        r_mean = _decimal_mean(r_values)
        r_median = _decimal_median(r_values)
        r_std = _decimal_pstdev(r_values)
        wins = sum(1 for r in r_values if r > Decimal("0"))
        losses = sum(1 for r in r_values if r < Decimal("0"))
        zeros = sum(1 for r in r_values if r == Decimal("0"))
        r_dist = RDistributionSection(
            mean=r_mean,
            median=r_median,
            std=r_std,
            min=min(r_values),
            max=max(r_values),
            win_count=wins,
            loss_count=losses,
            zero_r_count=zeros,
        )

    insufficient_note: str | None = None
    resampled_means: list[Decimal] = []
    if n_r < 2:
        interval: BootstrapInterval | None = None
        if n_trades == 0:
            insufficient_note = "no closed trades in trade list; bootstrap interval absent"
        else:
            insufficient_note = (
                f"only {n_r} R-valued trade(s); bootstrap interval absent "
                "(minimum two observations required)"
            )
        se_diagnostic = Decimal("0")
    else:
        resampled_means = _stationary_block_bootstrap_means(
            r_values, seed=bootstrap_seed, n_resamples=resamples, p=probable
        )
        lo_q = _quantile(resampled_means, Decimal("0.025"))
        hi_q = _quantile(resampled_means, Decimal("0.975"))
        point = r_dist.mean if r_dist.mean is not None else Decimal("0")
        sigma = r_dist.std if r_dist.std is not None else Decimal("0")
        se_diagnostic = _div(sigma, _q(n_r).sqrt())
        interval = BootstrapInterval(
            lower=lo_q,
            upper=hi_q,
            point_estimate=point,
            se_diagnostic=se_diagnostic,
            n_resamples=resamples,
            seed=bootstrap_seed,
        )

    # WR-10: risk-zero trades are counted in trade_count but excluded
    # from the R distribution — say so on the report, never silently.
    if risk_zero_excluded:
        zero_note = (
            f"{risk_zero_excluded} trade(s) excluded from the R distribution (realized_risk=0)"
        )
        insufficient_note = f"{insufficient_note}; {zero_note}" if insufficient_note else zero_note

    observed_dd = _max_drawdown(r_values)
    if resampled_means:
        # WR-06: the drawdown stage runs on seed + 1, not the same seed
        # as the expectancy bootstrap — sharing one stream couples the
        # drawdown distribution to the mean resample deterministically.
        dd_resamples = _resample_drawdowns(
            r_values, seed=bootstrap_seed + 1, n_resamples=resamples, p=probable
        )
        dd_p05 = _quantile(dd_resamples, Decimal("0.05"))
        dd_p50 = _quantile(dd_resamples, Decimal("0.50"))
        dd_p95 = _quantile(dd_resamples, Decimal("0.95"))
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

    quarter_groups: dict[str, list[Decimal]] = {}
    for trade, r in annotated:
        q_key = _quarter(_parse_exit_dt(trade))
        quarter_groups.setdefault(q_key, []).append(r)
    stability_slices = tuple(
        StabilitySlice(
            key=k,
            trade_count=len(v),
            mean_r=_decimal_mean(v) if v else None,
        )
        for k, v in sorted(quarter_groups.items())
    )
    stability = StabilitySection(slices=stability_slices)

    plateau = PlateauSection()

    candidate_mean = r_dist.mean
    no_trade = baseline_summaries.no_trade if baseline_summaries else None
    simple_trend = baseline_summaries.simple_trend if baseline_summaries else None
    delta_no_trade: Decimal | None = None
    if candidate_mean is not None and no_trade is not None and no_trade.mean_r is not None:
        delta_no_trade = _sub(candidate_mean, no_trade.mean_r)
    delta_simple_trend: Decimal | None = None
    if candidate_mean is not None and simple_trend is not None and simple_trend.mean_r is not None:
        delta_simple_trend = _sub(candidate_mean, simple_trend.mean_r)
    baselines = BaselineComparison(
        candidate_trade_count=n_trades,
        candidate_mean_r=candidate_mean,
        no_trade=no_trade,
        simple_trend=simple_trend,
        delta_vs_no_trade=delta_no_trade,
        delta_vs_simple_trend=delta_simple_trend,
    )

    universe_tags = universe_tags or {}
    research_symbols = sorted(
        sym for sym, tags in universe_tags.items() if "research_universe" in tags
    )
    live5_symbols = sorted(sym for sym, tags in universe_tags.items() if "live5_universe" in tags)
    for sym in live5_symbols:
        if sym not in LIVE5_SYMBOLS:
            raise ReportBuildError(
                f"live5_universe symbol {sym!r} is not in declared LIVE5_SYMBOLS"
            )

    def _slice_for(name: str, symbols: Sequence[str]) -> DualUniverseSlice:
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
            mean_r=_decimal_mean(rs_in),
            insufficient_data=len(rs_in) < 2,
        )

    research_slice = _slice_for("research_universe", research_symbols)
    live5_slice = _slice_for("live5_universe", live5_symbols)

    # WR-08: a live-5 universe with no R-valued trades has not shown a positive expectancy
    # either, so a positive research universe must not rescue it (BACKTEST_SPEC section 10.1).
    weak_rejection = (
        research_slice.mean_r is not None
        and research_slice.mean_r > Decimal("0")
        and (live5_slice.mean_r is None or live5_slice.mean_r <= Decimal("0"))
    )
    dual = DualUniverseSection(
        research_universe=research_slice,
        live5_universe=live5_slice,
        weak_live_universe_rejection=weak_rejection,
    )

    # Fallback can occur on a closed trade, an END_OF_DATA trade or a SETTLEMENT trade: all
    # three are filled (a settlement is a filled trade, so its fixed coverage note surfaces).
    filled_trades = [*closed_trades, *end_of_data_trades, *settlement_trades]
    n_filled = len(filled_trades)
    fallback_count = sum(1 for t in filled_trades if t.get("fallback_applied") is True)
    coverage_notes = tuple(
        sorted(
            {
                str(t.get("coverage_note"))
                for t in filled_trades
                if t.get("coverage_note") not in (None, "")
            }
        )
    )
    if n_filled == 0:
        coverage_pct = Decimal("100")
    else:
        # WR-05: exact Decimal division under the pinned context — the
        # old integer `//` floored e.g. 2/3 coverage to 66.
        coverage_pct = _div(_q((n_filled - fallback_count) * 100), _q(n_filled))
    intrabar = IntrabarCoverage(
        percent=coverage_pct,
        fallback_count=fallback_count,
        total_trades=n_filled,
        closed_trades=n_trades,
        end_of_data_trades=len(end_of_data_trades),
        coverage_notes=coverage_notes,
        settlement_trades=len(settlement_trades),
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
    "PlateauSection",
    "RDistributionSection",
    "ReportBuildError",
    "StabilitySection",
    "StabilitySlice",
    "UncertaintyReport",
    "build",
]
