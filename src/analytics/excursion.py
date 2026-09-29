"""1m-candle MFE/MAE excursion engine (Phase 10, plan 10-01, D-01/D-02).

Window convention (RESEARCH Metric Definitions 3 / A6): 1m candles whose open
time lies in [minute containing entry_time, minute containing exit_time],
inclusive; exactly one candle per minute is required. Trades without a fill,
without 1m coverage, or with a fallback simulation land in an explicit INCOMPLETE
bucket - nothing is imputed. Excursions are descriptive measurements only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from src.analytics.stats import (
    dist_stat,
    is_zero_risk,
    micros_since_epoch,
    r_value,
    seconds_between,
    seed_for,
)
from src.analytics.types import (
    DEFAULT_BASE_SEED,
    DEFAULT_RESAMPLES,
    AnalyticsInputError,
    DistStat,
    EvidenceKind,
    IncompleteReason,
    TradeOutcome,
)
from src.core._decimal import _div, _mul, _sub
from src.core.types import Candle
from src.domain.canonical import sha256_hex

EXCURSION_WINDOW_CONVENTION = (
    "Window: entry minute through exit minute, inclusive, 1m high/low. "
    "Trades without 1m coverage are counted as INCOMPLETE."
)
EXCURSION_MEASURES: tuple[str, ...] = (
    "mfe_price",
    "mae_price",
    "mfe_r",
    "mae_r",
    "time_to_mfe",
    "time_to_mae",
    "holding",
)

_ZERO = Decimal(0)
_ONE_MINUTE = timedelta(minutes=1)


@dataclass(frozen=True)
class TradeExcursion:
    """Excursion measurements for one trade (all numerics None when INCOMPLETE)."""

    trade_id: str
    evidence: EvidenceKind
    symbol: str
    direction: str
    mfe_price: Decimal | None
    mae_price: Decimal | None
    mfe_r: Decimal | None
    mae_r: Decimal | None
    time_to_mfe_s: Decimal | None
    time_to_mae_s: Decimal | None
    holding_s: Decimal | None
    exit_kind: str | None
    realized_r: Decimal | None
    r_excluded_zero_risk: bool
    incomplete_reason: IncompleteReason | None

    def digest(self) -> str:
        return sha256_hex(
            {
                "trade_id": self.trade_id,
                "evidence": self.evidence,
                "symbol": self.symbol,
                "direction": self.direction,
                "mfe_price": self.mfe_price,
                "mae_price": self.mae_price,
                "mfe_r": self.mfe_r,
                "mae_r": self.mae_r,
                "time_to_mfe_s": self.time_to_mfe_s,
                "time_to_mae_s": self.time_to_mae_s,
                "holding_s": self.holding_s,
                "exit_kind": self.exit_kind,
                "realized_r": self.realized_r,
                "r_excluded_zero_risk": self.r_excluded_zero_risk,
                "incomplete_reason": self.incomplete_reason,
            }
        )


@dataclass(frozen=True)
class ExcursionSection:
    """Digest-stamped excursion section for exactly one EvidenceKind."""

    evidence: EvidenceKind
    n_outcomes: int
    n_measured: int
    incomplete: tuple[tuple[str, int], ...]
    n_zero_risk_excluded: int
    measure_stats: tuple[DistStat, ...]  # EXCURSION_MEASURES order
    # METRICS section 6 diagnostic questions, descriptive distributions only. The
    # fourth question (holding duration) is the `holding` measure above.
    mfe_r_of_sl_exits: DistStat
    mae_r_of_tp_exits: DistStat
    give_back: DistStat
    window_convention: str
    base_seed: int
    resamples: int
    per_trade: tuple[TradeExcursion, ...]

    def stat(self, measure: str) -> DistStat:
        """The DistStat for one named measure in EXCURSION_MEASURES."""
        return self.measure_stats[EXCURSION_MEASURES.index(measure)]

    def digest(self) -> str:
        return sha256_hex(
            {
                "evidence": self.evidence,
                "base_seed": self.base_seed,
                "resamples": self.resamples,
                "window_convention": self.window_convention,
                "n_outcomes": self.n_outcomes,
                "n_measured": self.n_measured,
                "incomplete": [[reason, count] for reason, count in self.incomplete],
                "n_zero_risk_excluded": self.n_zero_risk_excluded,
                "measures": {
                    name: stat.digest()
                    for name, stat in zip(EXCURSION_MEASURES, self.measure_stats, strict=True)
                },
                "diagnostics": {
                    "mfe_r_of_sl_exits": self.mfe_r_of_sl_exits.digest(),
                    "mae_r_of_tp_exits": self.mae_r_of_tp_exits.digest(),
                    "give_back": self.give_back.digest(),
                },
                "per_trade": [trade.digest() for trade in self.per_trade],
            }
        )


def _floor_minute(value: datetime) -> datetime:
    return value.replace(second=0, microsecond=0)


def _incomplete(outcome: TradeOutcome, reason: IncompleteReason) -> TradeExcursion:
    return TradeExcursion(
        trade_id=outcome.trade_id,
        evidence=outcome.evidence,
        symbol=outcome.symbol,
        direction=outcome.direction,
        mfe_price=None,
        mae_price=None,
        mfe_r=None,
        mae_r=None,
        time_to_mfe_s=None,
        time_to_mae_s=None,
        holding_s=None,
        exit_kind=outcome.exit_kind,
        realized_r=None,
        r_excluded_zero_risk=False,
        incomplete_reason=reason,
    )


def _r_form(
    excursion_price: Decimal, quantity: Decimal, realized_risk: Decimal | None
) -> Decimal | None:
    """excursion_price * quantity / realized_risk (same denominator as _r_multiple)."""
    if realized_risk is None or realized_risk == _ZERO:
        return None
    return _div(_mul(excursion_price, quantity), realized_risk)


def _time_to(entry_time: datetime, candle: Candle) -> Decimal:
    """Seconds from entry to the extreme candle's open, clamped at 0."""
    seconds = seconds_between(entry_time, candle.open_time_utc)
    return seconds if seconds > _ZERO else _ZERO


def compute_trade_excursion(outcome: TradeOutcome, candles: Sequence[Candle]) -> TradeExcursion:
    """MFE/MAE in price and R plus time-to-extreme for one trade over 1m candles."""
    entry_price = outcome.entry_price
    entry_time = outcome.entry_time_utc
    if entry_price is None or entry_time is None:
        return _incomplete(outcome, IncompleteReason.NO_FILL_EVENT)
    exit_time = outcome.exit_time_utc
    if outcome.fallback_applied or exit_time is None:
        return _incomplete(outcome, IncompleteReason.FALLBACK_APPLIED)
    if exit_time < entry_time:
        return _incomplete(outcome, IncompleteReason.NEGATIVE_INTERVAL)
    quantity = outcome.quantity
    risk = outcome.realized_risk
    if quantity is None or (risk is not None and risk < _ZERO):
        return _incomplete(outcome, IncompleteReason.MALFORMED_ROW)

    first_minute = _floor_minute(entry_time)
    last_minute = _floor_minute(exit_time)
    n_minutes = (last_minute - first_minute) // _ONE_MINUTE + 1
    expected_opens = [first_minute + _ONE_MINUTE * i for i in range(n_minutes)]
    window = sorted(
        (
            candle
            for candle in candles
            if candle.symbol == outcome.symbol
            and candle.interval == "1m"
            and first_minute <= candle.open_time_utc <= last_minute
        ),
        key=lambda candle: candle.open_time_utc,
    )
    if [candle.open_time_utc for candle in window] != expected_opens:
        return _incomplete(outcome, IncompleteReason.NO_1M_COVERAGE)

    max_high = max(candle.high for candle in window)
    min_low = min(candle.low for candle in window)
    high_candle = next(candle for candle in window if candle.high == max_high)
    low_candle = next(candle for candle in window if candle.low == min_low)
    if outcome.direction == "LONG":
        mfe_price = max(_ZERO, _sub(max_high, entry_price))
        mae_price = max(_ZERO, _sub(entry_price, min_low))
        mfe_candle, mae_candle = high_candle, low_candle
    else:
        mfe_price = max(_ZERO, _sub(entry_price, min_low))
        mae_price = max(_ZERO, _sub(max_high, entry_price))
        mfe_candle, mae_candle = low_candle, high_candle

    return TradeExcursion(
        trade_id=outcome.trade_id,
        evidence=outcome.evidence,
        symbol=outcome.symbol,
        direction=outcome.direction,
        mfe_price=mfe_price,
        mae_price=mae_price,
        mfe_r=_r_form(mfe_price, quantity, risk),
        mae_r=_r_form(mae_price, quantity, risk),
        time_to_mfe_s=_time_to(entry_time, mfe_candle) if mfe_price > _ZERO else None,
        time_to_mae_s=_time_to(entry_time, mae_candle) if mae_price > _ZERO else None,
        holding_s=seconds_between(entry_time, exit_time),
        exit_kind=outcome.exit_kind,
        realized_r=r_value(outcome.realized_pnl, risk),
        r_excluded_zero_risk=is_zero_risk(risk),
        incomplete_reason=None,
    )


def _values(items: Sequence[Decimal | None]) -> list[Decimal]:
    return [item for item in items if item is not None]


def build_excursion_section(
    outcomes: Sequence[TradeOutcome],
    candles_by_symbol: Mapping[str, Sequence[Candle]],
    *,
    evidence: EvidenceKind,
    base_seed: int = DEFAULT_BASE_SEED,
    resamples: int = DEFAULT_RESAMPLES,
) -> ExcursionSection:
    """Build the digest-stamped excursion section for exactly one EvidenceKind."""
    for outcome in outcomes:
        if outcome.evidence is not evidence:
            raise AnalyticsInputError(
                f"outcome {outcome.trade_id!r} has evidence {outcome.evidence.value}, "
                f"section is {evidence.value} (evidence kinds are never pooled)"
            )
    ordered = sorted(outcomes, key=lambda outcome: outcome.trade_id)
    pairs = [
        (outcome, compute_trade_excursion(outcome, candles_by_symbol.get(outcome.symbol, ())))
        for outcome in ordered
    ]
    per_trade = tuple(excursion for _, excursion in pairs)

    counts: dict[str, int] = {}
    for excursion in per_trade:
        if excursion.incomplete_reason is not None:
            key = excursion.incomplete_reason.value
            counts[key] = counts.get(key, 0) + 1
    incomplete = tuple(sorted(counts.items()))

    # Stable time order (exit time, trade_id) for the block bootstrap.
    measured = sorted(
        (
            (outcome, excursion)
            for outcome, excursion in pairs
            if excursion.incomplete_reason is None and outcome.exit_time_utc is not None
        ),
        key=lambda pair: (
            micros_since_epoch(pair[0].exit_time_utc) if pair[0].exit_time_utc else 0,
            pair[0].trade_id,
        ),
    )
    excursions = [excursion for _, excursion in measured]
    n_measured = len(excursions)
    series: dict[str, list[Decimal]] = {
        "mfe_price": _values([e.mfe_price for e in excursions]),
        "mae_price": _values([e.mae_price for e in excursions]),
        "mfe_r": _values([e.mfe_r for e in excursions]),
        "mae_r": _values([e.mae_r for e in excursions]),
        "time_to_mfe": _values([e.time_to_mfe_s for e in excursions]),
        "time_to_mae": _values([e.time_to_mae_s for e in excursions]),
        "holding": _values([e.holding_s for e in excursions]),
    }
    measure_stats = tuple(
        dist_stat(
            series[name],
            seed=seed_for(base_seed, ordinal),
            resamples=resamples,
            n=n_measured,
        )
        for ordinal, name in enumerate(EXCURSION_MEASURES)
    )
    # Diagnostics get distinct deterministic seeds after the measure ordinals.
    diag_base = len(EXCURSION_MEASURES)
    sl_excursions = [e for e in excursions if e.exit_kind == "SL"]
    tp_excursions = [e for e in excursions if e.exit_kind == "TP1"]
    give_back_values = [
        _sub(e.mfe_r, e.realized_r)
        for e in excursions
        if e.mfe_r is not None and e.realized_r is not None
    ]
    mfe_r_of_sl_exits = dist_stat(
        _values([e.mfe_r for e in sl_excursions]),
        seed=seed_for(base_seed, diag_base),
        resamples=resamples,
        n=len(sl_excursions),
    )
    mae_r_of_tp_exits = dist_stat(
        _values([e.mae_r for e in tp_excursions]),
        seed=seed_for(base_seed, diag_base + 1),
        resamples=resamples,
        n=len(tp_excursions),
    )
    give_back = dist_stat(
        give_back_values,
        seed=seed_for(base_seed, diag_base + 2),
        resamples=resamples,
        n=n_measured,
    )
    return ExcursionSection(
        evidence=evidence,
        n_outcomes=len(ordered),
        n_measured=n_measured,
        incomplete=incomplete,
        n_zero_risk_excluded=sum(1 for e in excursions if e.r_excluded_zero_risk),
        measure_stats=measure_stats,
        mfe_r_of_sl_exits=mfe_r_of_sl_exits,
        mae_r_of_tp_exits=mae_r_of_tp_exits,
        give_back=give_back,
        window_convention=EXCURSION_WINDOW_CONVENTION,
        base_seed=base_seed,
        resamples=resamples,
        per_trade=per_trade,
    )
