"""Thin public wrappers over the Phase-6 Decimal statistics and bootstrap (plan 10-01).

The Phase-6 helpers (`_r_multiple`, `_has_zero_risk`, `_decimal_mean`,
`_decimal_median`, `_quantile`, `_stationary_block_bootstrap_means`,
`_max_drawdown`) are private names in `src.backtest.report`. The coupling is
INTENTIONAL (RESEARCH P7: reuse, do not re-derive) and is guarded by the golden
fixture digests - a change in their behavior changes the pinned section digests
and fails the fixture tests. Nothing here reads a clock, uses built-in `hash()`,
touches module-level randomness, or calls `timedelta.total_seconds()` (which
returns a binary float).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.analytics.types import (
    BOOTSTRAP_BLOCK_P,
    LOW_N_THRESHOLD,
    MIN_RESAMPLES,
    AnalyticsInputError,
    DistStat,
    Estimate,
    TradeOutcome,
)
from src.backtest.report import (  # noqa: F401 - _max_drawdown re-exposed for later plans
    _decimal_mean,
    _decimal_median,
    _has_zero_risk,
    _max_drawdown,
    _quantile,
    _r_multiple,
    _stationary_block_bootstrap_means,
)
from src.core._decimal import _div, _mul, _q

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_MICROSECOND = timedelta(microseconds=1)
_MICROS_PER_SECOND = Decimal(1000000)
_HUNDRED = Decimal(100)
_LO_Q = Decimal("0.025")
_HI_Q = Decimal("0.975")
_P90_Q = Decimal("0.9")


def r_value(realized_pnl: Decimal | None, realized_risk: Decimal | None) -> Decimal | None:
    """R-multiple = realized_pnl / realized_risk via the Phase-6 `_r_multiple`."""
    return _r_multiple({"realized_pnl": realized_pnl, "realized_risk": realized_risk})


def is_zero_risk(realized_risk: Decimal | None) -> bool:
    """True only for an explicit realized_risk of zero (absent risk is not zero-risk)."""
    return _has_zero_risk({"realized_risk": realized_risk})


def seed_for(base_seed: int, ordinal: int) -> int:
    """Deterministic per-statistic seed: base_seed + ordinal (ints only, never hash())."""
    for name, value in (("base_seed", base_seed), ("ordinal", ordinal)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise AnalyticsInputError(f"{name} must be an int, got {value!r}")
    if ordinal < 0:
        raise AnalyticsInputError(f"ordinal must be >= 0, got {ordinal}")
    return base_seed + ordinal


def micros_since_epoch(value: datetime) -> int:
    """Exact integer microseconds since the Unix epoch for a UTC-aware datetime."""
    return (value - _EPOCH) // _ONE_MICROSECOND


def seconds_between(start: datetime, end: datetime) -> Decimal:
    """Exact Decimal seconds from start to end (integer-microsecond arithmetic)."""
    micros = (end - start) // _ONE_MICROSECOND
    return _div(Decimal(micros), _MICROS_PER_SECOND)


def percent(numerator: int | Decimal, denominator: int | Decimal) -> Decimal | None:
    """Percentage 0-100 as Decimal, or None when the denominator is zero."""
    den = _q(denominator)
    if den == Decimal(0):
        return None
    return _div(_mul(_q(numerator), _HUNDRED), den)


def is_low_n(n: int) -> bool:
    """Display flag only: n below LOW_N_THRESHOLD (never an acceptance threshold)."""
    return n < LOW_N_THRESHOLD


def _check_resamples(resamples: int) -> None:
    if not isinstance(resamples, int) or isinstance(resamples, bool) or resamples < MIN_RESAMPLES:
        raise AnalyticsInputError(f"resamples must be int >= {MIN_RESAMPLES}, got {resamples!r}")


def _check_values(values: Sequence[Decimal]) -> None:
    for value in values:
        if not isinstance(value, Decimal):
            raise AnalyticsInputError(f"values must be Decimal, got {type(value).__name__}")


def estimate_mean(
    values: Sequence[Decimal],
    *,
    seed: int,
    resamples: int,
    n: int | None = None,
) -> Estimate:
    """Mean with n and a seeded stationary-block-bootstrap interval when n_valued >= 2.

    `values` MUST be passed in stable time order (the block bootstrap preserves
    adjacency). `n` is the population size the estimate speaks about (defaults to
    the number of values). Fewer than two valued observations -> explicit
    `interval_absent` marker, never a bare number.
    """
    _check_resamples(resamples)
    _check_values(values)
    n_valued = len(values)
    population = n_valued if n is None else n
    if population < n_valued:
        raise AnalyticsInputError(f"n {population} is smaller than n_valued {n_valued}")
    if n_valued == 0:
        return Estimate(
            value=None, lo=None, hi=None, n=population, n_valued=0, interval_absent=True
        )
    if n_valued == 1:
        return Estimate(
            value=values[0],
            lo=None,
            hi=None,
            n=population,
            n_valued=1,
            interval_absent=True,
        )
    means = _stationary_block_bootstrap_means(
        values, seed=seed, n_resamples=resamples, p=BOOTSTRAP_BLOCK_P
    )
    return Estimate(
        value=_decimal_mean(values),
        lo=_quantile(means, _LO_Q),
        hi=_quantile(means, _HI_Q),
        n=population,
        n_valued=n_valued,
        interval_absent=False,
        n_resamples=resamples,
        seed=seed,
    )


def percentile(values: Sequence[Decimal], q: Decimal) -> Decimal | None:
    """Linear-interpolated quantile in [0, 1]; None for an empty sequence."""
    _check_values(values)
    if not values:
        return None
    return _quantile(values, q)


def dist_stat(
    values: Sequence[Decimal],
    *,
    seed: int,
    resamples: int,
    n: int | None = None,
) -> DistStat:
    """Descriptive distribution: mean estimate, median, p90, min, max (no thresholds)."""
    mean = estimate_mean(values, seed=seed, resamples=resamples, n=n)
    if not values:
        return DistStat(n=mean.n, mean=mean, median=None, p90=None, minimum=None, maximum=None)
    return DistStat(
        n=mean.n,
        mean=mean,
        median=_decimal_median(values),
        p90=_quantile(values, _P90_Q),
        minimum=min(values),
        maximum=max(values),
    )


def ordered_r_values(outcomes: Sequence[TradeOutcome]) -> list[Decimal]:
    """R values ordered by (exit_time_utc, trade_id) for outcomes with a defined R."""
    keyed: list[tuple[int, str, Decimal]] = []
    for outcome in outcomes:
        r = r_value(outcome.realized_pnl, outcome.realized_risk)
        if r is None or outcome.exit_time_utc is None:
            continue
        keyed.append((micros_since_epoch(outcome.exit_time_utc), outcome.trade_id, r))
    keyed.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in keyed]
