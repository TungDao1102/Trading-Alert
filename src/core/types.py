"""Pure-core frozen dataclasses (Phase 4, plan 04-01).

Per D-01/D-02/D-10: frozen pure-Python dataclasses with Decimal money/price
fields and timezone-aware UTC datetime fields. Construction-time guards
mirror the Phase-3 domain pattern (`src/domain/signal.py`,
`src/domain/trade_plan.py`). No third-party imports.

These types are the value objects flowing between the feature engine,
strategy function, and planner — all three live in this package and share
the same purity contract.

Reason-code vocabulary travels as plain strings on `FeatureOutput.reason_code`
per RESEARCH.md Pattern 1 — see canonical `RejectionReason` values in
`src/domain/enums.py` for the cross-module vocabulary the strategy uses
when emitting NO_TRADE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from src.domain.enums import RejectionReason

# --------------------------------------------------------------------------- #
# Validation helpers — copied from the Phase-3 signal.py / trade_plan.py
# pattern (no shared module; each Phase layer keeps its own guards).
# --------------------------------------------------------------------------- #


def _require_non_empty(value: str, field_name: str) -> None:
    """Reject empty strings for validated non-empty fields."""
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_utc_aware(value: datetime, field_name: str) -> None:
    """Reject naive and non-UTC datetimes (D-12)."""
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")


def _require_decimal(value: object, field_name: str) -> None:
    """Reject non-Decimal values for money/qty/price fields (D-12)."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal, got {type(value).__name__}")


def _require_positive(value: Decimal, field_name: str) -> None:
    """Reject non-positive Decimals (D-04 fail-closed)."""
    if value <= Decimal("0"):
        raise ValueError(f"{field_name} must be > 0, got {value}")


# --------------------------------------------------------------------------- #
# Candle — one closed bar; OHLCV validated at construction (D-04).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Candle:
    """One closed candle (D-02: closed-only, never resampled/forward-filled).

    `open_time_utc` < `close_time_utc` and OHLC ordering validated
    construction-time so malformed bars fail before features compute.
    `volume` is informational (volume features deferred to v2 per
    RESEARCH.md REFN-02/03).
    """

    symbol: str
    interval: str
    open_time_utc: datetime
    close_time_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self) -> None:
        _require_non_empty(self.symbol, "symbol")
        _require_non_empty(self.interval, "interval")
        _require_utc_aware(self.open_time_utc, "open_time_utc")
        _require_utc_aware(self.close_time_utc, "close_time_utc")
        for fname in ("open", "high", "low", "close", "volume"):
            _require_decimal(getattr(self, fname), fname)
        if self.open_time_utc >= self.close_time_utc:
            raise ValueError(
                f"open_time_utc {self.open_time_utc} must be < close_time_utc {self.close_time_utc}"
            )
        if self.high < self.low:
            raise ValueError(f"high {self.high} must be >= low {self.low}")
        if not (self.low <= self.open <= self.high):
            raise ValueError(f"open {self.open} must be within [low={self.low}, high={self.high}]")
        if not (self.low <= self.close <= self.high):
            raise ValueError(
                f"close {self.close} must be within [low={self.low}, high={self.high}]"
            )
        if self.volume < Decimal("0"):
            raise ValueError(f"volume {self.volume} must be >= 0")


# --------------------------------------------------------------------------- #
# FeatureOutput — one indicator value with validity gate (D-03).
# --------------------------------------------------------------------------- #


# Reason-code vocabulary (project-defined; no upstream library). Canonical
# reasons are drawn from RejectionReason where they apply. New additive
# reasons stay here as strings (RESEARCH.md Pattern 1).
REASON_OK = "OK"
REASON_WARMUP_INSUFFICIENT = "WARMUP_INSUFFICIENT"
REASON_GAP_IN_SOURCE = "GAP_IN_SOURCE"
REASON_INVALID_INPUT = "INVALID_INPUT"


@dataclass(frozen=True)
class FeatureOutput:
    """One feature value with a validity gate (D-03).

    `value` is None when `valid` is False (never NaN/partial
    propagation). `reason_code` is one of the REASON_* constants above
    or a domain RejectionReason value used by the strategy gate.
    """

    value: Decimal | None
    valid: bool
    reason_code: str

    def __post_init__(self) -> None:
        _require_non_empty(self.reason_code, "reason_code")
        if self.valid:
            if self.value is None:
                raise ValueError("FeatureOutput: valid=True requires value to be Decimal")
        else:
            # WR-09: a stale value must never ride along on invalid —
            # the AND-gate's chokepoint type enforces "no value without
            # validity" so `.value`-without-`.valid` misuse fails here,
            # not downstream. Adapters needing last-known values carry
            # them in their own local type.
            if self.value is not None:
                raise ValueError("FeatureOutput: valid=False requires value=None")


def _ok(value: Decimal) -> FeatureOutput:
    """Build an OK FeatureOutput from a Decimal value."""
    return FeatureOutput(value=value, valid=True, reason_code=REASON_OK)


def _invalid(reason: str) -> FeatureOutput:
    """Build an invalid FeatureOutput with the given reason."""
    return FeatureOutput(value=None, valid=False, reason_code=reason)


# --------------------------------------------------------------------------- #
# FeatureFrame — whole-bar feature summary (D-03).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FeatureFrame:
    """Whole-bar feature summary (D-03): EMA(20/50/200), ATR(14), swing H/L, zone.

    `features_valid` is the AND of all required-feature validity flags; the
    strategy treats `features_valid=False` as NO_TRADE (fail closed, never
    NaN/partial propagation).
    """

    symbol: str
    interval: str
    bar_index: int  # 0-based index of the bar these features describe
    bar_close_utc: datetime  # aware UTC
    features_valid: bool
    ema_20: FeatureOutput
    ema_50: FeatureOutput
    ema_200: FeatureOutput
    atr_14: FeatureOutput
    swing_high: FeatureOutput
    swing_low: FeatureOutput
    zone_upper: FeatureOutput
    zone_lower: FeatureOutput

    def __post_init__(self) -> None:
        _require_non_empty(self.symbol, "symbol")
        _require_non_empty(self.interval, "interval")
        if self.bar_index < 0:
            raise ValueError(f"bar_index {self.bar_index} must be >= 0")
        _require_utc_aware(self.bar_close_utc, "bar_close_utc")
        if self.features_valid:
            for f in (
                self.ema_20,
                self.ema_50,
                self.ema_200,
                self.atr_14,
                self.swing_high,
                self.swing_low,
                self.zone_upper,
                self.zone_lower,
            ):
                if not f.valid:
                    raise ValueError(
                        f"FeatureFrame: features_valid=True but {f.reason_code!r} invalid"
                    )


# SetupResult reason vocabulary (WR-06): the canonical RejectionReason
# values plus the additive feature-layer codes the strategy gate
# propagates verbatim (pinned by the boundary + determinism suites).
# Anything else is a programming error that fails here instead of
# throwing in a strict-enum downstream consumer.
_SETUP_REASONS = frozenset(
    {r.value for r in RejectionReason}
    | {
        REASON_OK,
        REASON_WARMUP_INSUFFICIENT,
        REASON_GAP_IN_SOURCE,
        REASON_INVALID_INPUT,
    }
)


# --------------------------------------------------------------------------- #
# SetupResult — discriminated NO_TRADE | SETUP envelope (D-07).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SetupResult:
    """Discriminated NO_TRADE-or-SETUP envelope emitted by `strategy.evaluate`.

    Per D-07: pure function — zero I/O, zero clock reads, zero randomness.
    A `signal` is set only when the strategy detected a setup; otherwise
    `reason_code` carries the rejection reason (canonical RejectionReason
    value or an additive warm-up/gap code).

    `regime` is the 4H regime verdict ("BULLISH" / "BEARISH" / "NEUTRAL") the
    strategy resolved while evaluating, or None when the evaluation stopped
    before the regime was known. It is report metadata only (Phase 14, D-21,
    D-38): it is NOT part of the persisted Signal and enters no signal id,
    fingerprint or plan hash.
    """

    is_no_trade: bool
    signal: Signal | None = field(default=None)
    reason_code: str = "OK"
    regime: str | None = field(default=None)

    def __post_init__(self) -> None:
        _require_non_empty(self.reason_code, "reason_code")
        if self.regime is not None:
            _require_non_empty(self.regime, "regime")
        if self.reason_code not in _SETUP_REASONS:
            raise ValueError(f"SetupResult: unknown reason_code {self.reason_code!r}")
        if self.is_no_trade:
            if self.signal is not None:
                raise ValueError("SetupResult: is_no_trade=True requires signal=None")
        else:
            if self.signal is None:
                raise ValueError("SetupResult: is_no_trade=False requires a Signal")


# --------------------------------------------------------------------------- #
# MarketSnapshot — what evaluate() sees.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MarketSnapshot:
    """The market view the strategy sees (D-02: closed-candle sequences only).

    `setup_candles` is the bar stream the strategy evaluates setups on
    (e.g. 1H for trend-pullback). `context_candles` is the higher-timeframe
    context stream (e.g. 4H). Both are independently ordered closed
    sequences — the core NEVER interpolates across timeframes.
    """

    symbol: str
    setup_candles: list[Candle]
    context_candles: list[Candle]
    source_timeframe: str

    def __post_init__(self) -> None:
        _require_non_empty(self.symbol, "symbol")
        _require_non_empty(self.source_timeframe, "source_timeframe")
        if not isinstance(self.setup_candles, list):
            raise TypeError("setup_candles must be a list[Candle]")
        if not isinstance(self.context_candles, list):
            raise TypeError("context_candles must be a list[Candle]")


# --------------------------------------------------------------------------- #
# AccountState — what evaluate() needs from the account (Phase 5 expands).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AccountState:
    """Minimal account view the pure core needs (D-07/Phase 5 expands).

    `equity` is the current account equity in quote currency. `risk_rate`
    is the per-trade equity fraction. Both are Decimal; all strategy
    arithmetic stays in Decimal.
    """

    equity: Decimal
    risk_rate: Decimal

    def __post_init__(self) -> None:
        _require_decimal(self.equity, "equity")
        _require_decimal(self.risk_rate, "risk_rate")
        _require_positive(self.equity, "equity")
        if not (Decimal("0") < self.risk_rate <= Decimal("1")):
            raise ValueError(f"risk_rate {self.risk_rate} must be in (0, 1]")


# Local re-export to keep `types` self-contained for the discriminator
# check above (avoids a circular import on this module's public surface).
from src.domain.signal import Signal  # noqa: E402
from src.domain.trade_plan import TradePlan  # noqa: E402

# --------------------------------------------------------------------------- #
# PlanResult — discriminated NO_TRADE-or-TradePlan envelope (D-08).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PlanResult:
    """Discriminated NO_TRADE-or-TradePlan envelope emitted by `planner.plan`.

    Per D-08: RR below minimum_rr returns NO_TRADE with RR_TOO_LOW,
    never a downgraded plan. The planner is the second line of defense
    (the strategy gate should have caught this earlier).

    `is_no_trade=True` carries a canonical `RejectionReason` value in
    `reason_code`; `is_no_trade=False` carries a fully populated TradePlan.
    """

    is_no_trade: bool
    trade_plan: TradePlan | None = None
    reason_code: str = "OK"

    def __post_init__(self) -> None:
        _require_non_empty(self.reason_code, "reason_code")
        if self.is_no_trade:
            if self.trade_plan is not None:
                raise ValueError("PlanResult: is_no_trade=True requires trade_plan=None")
        else:
            if self.trade_plan is None:
                raise ValueError("PlanResult: is_no_trade=False requires a TradePlan")


__all__ = [
    "REASON_OK",
    "REASON_WARMUP_INSUFFICIENT",
    "REASON_GAP_IN_SOURCE",
    "REASON_INVALID_INPUT",
    "Candle",
    "FeatureOutput",
    "FeatureFrame",
    "SetupResult",
    "MarketSnapshot",
    "AccountState",
    "PlanResult",
]
