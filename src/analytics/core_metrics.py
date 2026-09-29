"""Core metric block (Phase 10, plan 10-04, M-1 / METRICS section 2).

One reusable, pure projection of a set of `TradeOutcome`s: counts, R statistics
with the Phase-6 uncertainty presentation, win rate, expectancy, max drawdown
(R) and longest loss streak. Every slice, universe and section view is a
`CoreMetrics` projection, so a slice row can never disagree with the full report.

Plan decisions (documented, D-02):
  * An outcome is R-valued only when R is defined AND it has an exit time (the
    R series is ordered by (exit_time_utc, trade_id) via `stats.ordered_r_values`);
    every other outcome that is not an explicit zero-risk exclusion is counted
    as `incomplete`, never imputed.
  * `expectancy_r` equals the mean R by definition: realized R is already net of
    the modeled costs.
  * `low_n` refers to the estimate's sample size (`n_r_valued`) and is a display
    flag only - never an acceptance threshold.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from src.analytics import stats
from src.analytics.types import Estimate, TradeOutcome
from src.backtest.report import _decimal_median, _max_drawdown
from src.core._decimal import _div
from src.domain.canonical import sha256_hex

_ZERO = Decimal(0)


@dataclass(frozen=True)
class CoreMetrics:
    """The M-1 metric block for one set of outcomes (single evidence kind)."""

    n: int
    n_r_valued: int
    zero_risk_excluded: int
    incomplete: int
    mean_r: Estimate
    median_r: Decimal | None
    win_rate: Decimal | None
    expectancy_r: Decimal | None
    max_drawdown_r: Decimal | None
    loss_streak_max: int | None
    low_n: bool

    def digest(self) -> str:
        return sha256_hex(
            {
                "n": self.n,
                "n_r_valued": self.n_r_valued,
                "zero_risk_excluded": self.zero_risk_excluded,
                "incomplete": self.incomplete,
                "mean_r": self.mean_r.digest(),
                "median_r": self.median_r,
                "win_rate": self.win_rate,
                "expectancy_r": self.expectancy_r,
                "max_drawdown_r": self.max_drawdown_r,
                "loss_streak_max": self.loss_streak_max,
                "low_n": self.low_n,
            }
        )


def _longest_loss_streak(r_values: Sequence[Decimal]) -> int:
    longest = 0
    current = 0
    for r in r_values:
        if r < _ZERO:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def compute_core_metrics(
    outcomes: Sequence[TradeOutcome],
    *,
    base_seed: int,
    resamples: int,
    ordinal: int = 0,
) -> CoreMetrics:
    """Compute the M-1 block; the bootstrap seed is `base_seed + ordinal`."""
    n = len(outcomes)
    zero_risk = sum(1 for outcome in outcomes if stats.is_zero_risk(outcome.realized_risk))
    r_values = stats.ordered_r_values(outcomes)
    n_r_valued = len(r_values)
    incomplete = n - n_r_valued - zero_risk
    mean_r = stats.estimate_mean(
        r_values, seed=stats.seed_for(base_seed, ordinal), resamples=resamples
    )
    if n_r_valued == 0:
        return CoreMetrics(
            n=n,
            n_r_valued=0,
            zero_risk_excluded=zero_risk,
            incomplete=incomplete,
            mean_r=mean_r,
            median_r=None,
            win_rate=None,
            expectancy_r=None,
            max_drawdown_r=None,
            loss_streak_max=None,
            low_n=stats.is_low_n(0),
        )
    wins = sum(1 for r in r_values if r > _ZERO)
    return CoreMetrics(
        n=n,
        n_r_valued=n_r_valued,
        zero_risk_excluded=zero_risk,
        incomplete=incomplete,
        mean_r=mean_r,
        median_r=_decimal_median(r_values),
        win_rate=_div(Decimal(wins), Decimal(n_r_valued)),
        expectancy_r=mean_r.value,
        max_drawdown_r=_max_drawdown(r_values),
        loss_streak_max=_longest_loss_streak(r_values),
        low_n=stats.is_low_n(n_r_valued),
    )
