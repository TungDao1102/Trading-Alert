"""Core analytics types, enums, and constants (Phase 10, plan 10-01, D-01/D-02/D-05).

stdlib + Decimal + in-repo pure modules only. Every dataclass is frozen and
validated at construction (fail closed with `AnalyticsInputError`). Evidence
kinds are never pooled: every `TradeOutcome` carries its `EvidenceKind` plus
strategy_version + parameter_set_hash so evidence stays traceable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum

from src.domain.canonical import sha256_hex

ANALYTICS_SCHEMA_VERSION = "analytics-schema/1"
# Display flag only (RESEARCH A2) - never an acceptance threshold.
LOW_N_THRESHOLD = 30
DEFAULT_RESAMPLES = 1000
MIN_RESAMPLES = 100
BOOTSTRAP_BLOCK_P = Decimal("0.1")
DEFAULT_BASE_SEED = 20260929


class AnalyticsInputError(Exception):
    """Raised when analytics input is malformed (fails closed, never imputed)."""


class EvidenceKind(str, Enum):
    """Which evidence stream a row/section belongs to (never pooled, D-05)."""

    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE = "LIVE"


class IncompleteReason(str, Enum):
    """Why a measurement is INCOMPLETE (counted, never imputed, D-02)."""

    NO_1M_COVERAGE = "NO_1M_COVERAGE"
    NO_FILL_EVENT = "NO_FILL_EVENT"
    NO_SEEN_TIMESTAMP = "NO_SEEN_TIMESTAMP"
    FALLBACK_APPLIED = "FALLBACK_APPLIED"
    NO_RISK_VALUE = "NO_RISK_VALUE"
    NO_INTENDED_PRICE = "NO_INTENDED_PRICE"
    NO_HYPOTHETICAL_OUTCOME = "NO_HYPOTHETICAL_OUTCOME"
    NOT_MEASURED_FOR_EVIDENCE = "NOT_MEASURED_FOR_EVIDENCE"
    NEGATIVE_INTERVAL = "NEGATIVE_INTERVAL"
    MALFORMED_ROW = "MALFORMED_ROW"
    UNMATCHED_JOIN = "UNMATCHED_JOIN"
    OPEN_POSITION = "OPEN_POSITION"
    COMMISSION_ASSET_NOT_QUOTE = "COMMISSION_ASSET_NOT_QUOTE"
    UNVERIFIED_EXCHANGE_SEMANTICS = "UNVERIFIED_EXCHANGE_SEMANTICS"
    NO_APPROVAL = "NO_APPROVAL"
    NO_ORDER = "NO_ORDER"
    NO_PAPER_OUTCOME = "NO_PAPER_OUTCOME"


_DIRECTIONS = frozenset({"LONG", "SHORT"})


def _require_utc(value: object, name: str) -> None:
    if not isinstance(value, datetime):
        raise AnalyticsInputError(f"{name} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        raise AnalyticsInputError(f"{name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise AnalyticsInputError(f"{name} must be UTC, got offset {value.utcoffset()}")


def _require_decimal(value: object, name: str) -> None:
    if not isinstance(value, Decimal):
        raise AnalyticsInputError(f"{name} must be Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise AnalyticsInputError(f"{name} must be finite, got {value}")


def _optional_decimal(value: object, name: str) -> None:
    if value is not None:
        _require_decimal(value, name)


def _optional_utc(value: object, name: str) -> None:
    if value is not None:
        _require_utc(value, name)


def _require_non_empty(value: object, name: str) -> None:
    if not isinstance(value, str) or value == "":
        raise AnalyticsInputError(f"{name} must be a non-empty str")


def _require_count(value: object, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AnalyticsInputError(f"{name} must be an int >= 0, got {value!r}")


@dataclass(frozen=True)
class TradeOutcome:
    """One normalized trade outcome; every downstream metric consumes only this."""

    evidence: EvidenceKind
    trade_id: str
    signal_id: str | None
    strategy_version: str
    parameter_set_hash: str
    symbol: str
    direction: str
    entry_kind: str | None
    entry_price: Decimal | None
    entry_time_utc: datetime | None
    exit_kind: str | None
    exit_price: Decimal | None
    exit_time_utc: datetime | None
    quantity: Decimal | None
    realized_pnl: Decimal | None
    realized_risk: Decimal | None
    fallback_applied: bool
    intended_entry_price: Decimal | None = None
    regime: str | None = None
    vol_regime: str | None = None
    coverage_note: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, EvidenceKind):
            raise AnalyticsInputError("evidence must be an EvidenceKind")
        _require_non_empty(self.trade_id, "trade_id")
        _require_non_empty(self.strategy_version, "strategy_version")
        _require_non_empty(self.parameter_set_hash, "parameter_set_hash")
        _require_non_empty(self.symbol, "symbol")
        if self.direction not in _DIRECTIONS:
            raise AnalyticsInputError(f"direction must be LONG or SHORT, got {self.direction!r}")
        _optional_decimal(self.entry_price, "entry_price")
        _optional_decimal(self.exit_price, "exit_price")
        _optional_decimal(self.quantity, "quantity")
        _optional_decimal(self.realized_pnl, "realized_pnl")
        _optional_decimal(self.realized_risk, "realized_risk")
        # WR-15: risk is a magnitude. A negative value would flip the sign of R in the core
        # metrics (a loss would count as a win) while the excursion engine calls the same
        # row MALFORMED_ROW, so it is refused outright (fail closed, never repaired).
        if self.realized_risk is not None and self.realized_risk < 0:
            raise AnalyticsInputError("realized_risk must not be negative")
        _optional_decimal(self.intended_entry_price, "intended_entry_price")
        _optional_utc(self.entry_time_utc, "entry_time_utc")
        _optional_utc(self.exit_time_utc, "exit_time_utc")
        if not isinstance(self.fallback_applied, bool):
            raise AnalyticsInputError("fallback_applied must be a bool")


@dataclass(frozen=True)
class OutcomeContext:
    """Optional caller-supplied descriptive tags for one trade (never feed back)."""

    intended_entry_price: Decimal | None = None
    regime: str | None = None
    vol_regime: str | None = None

    def __post_init__(self) -> None:
        _optional_decimal(self.intended_entry_price, "intended_entry_price")


@dataclass(frozen=True)
class NoTradeRecord:
    """A risk-rejected plan: a NO_TRADE record, never a TradeOutcome."""

    evidence: EvidenceKind
    symbol: str
    reason_code: str
    source_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, EvidenceKind):
            raise AnalyticsInputError("evidence must be an EvidenceKind")
        _require_non_empty(self.symbol, "symbol")
        _require_non_empty(self.reason_code, "reason_code")
        _require_non_empty(self.source_id, "source_id")


@dataclass(frozen=True)
class BacktestNormalization:
    """Result of normalizing backtest TradeRecords: outcomes + NO_TRADE rejects."""

    outcomes: tuple[TradeOutcome, ...]
    rejects: tuple[NoTradeRecord, ...]


@dataclass(frozen=True)
class Estimate:
    """A point estimate that always carries n and an interval or its absence.

    `n` is the population size the estimate speaks about; `n_valued` is how many
    observations had a defined value. With fewer than two valued observations the
    interval is explicitly absent (`interval_absent`), never a bare number.
    """

    value: Decimal | None
    lo: Decimal | None
    hi: Decimal | None
    n: int
    n_valued: int
    interval_absent: bool
    n_resamples: int | None = None
    seed: int | None = None

    def __post_init__(self) -> None:
        _optional_decimal(self.value, "value")
        _optional_decimal(self.lo, "lo")
        _optional_decimal(self.hi, "hi")
        _require_count(self.n, "n")
        _require_count(self.n_valued, "n_valued")
        if self.n_valued > self.n:
            raise AnalyticsInputError(f"n_valued {self.n_valued} exceeds n {self.n}")
        if self.interval_absent != (self.lo is None or self.hi is None):
            raise AnalyticsInputError("interval_absent must match lo/hi presence")

    def digest(self) -> str:
        return sha256_hex(
            {
                "value": self.value,
                "lo": self.lo,
                "hi": self.hi,
                "n": self.n,
                "n_valued": self.n_valued,
                "interval_absent": self.interval_absent,
                "n_resamples": self.n_resamples,
                "seed": self.seed,
            }
        )


@dataclass(frozen=True)
class DistStat:
    """A descriptive distribution: mean (with uncertainty), median, p90, min, max."""

    n: int
    mean: Estimate
    median: Decimal | None
    p90: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None

    def __post_init__(self) -> None:
        _require_count(self.n, "n")
        _optional_decimal(self.median, "median")
        _optional_decimal(self.p90, "p90")
        _optional_decimal(self.minimum, "minimum")
        _optional_decimal(self.maximum, "maximum")

    def digest(self) -> str:
        return sha256_hex(
            {
                "n": self.n,
                "mean": self.mean.digest(),
                "median": self.median,
                "p90": self.p90,
                "minimum": self.minimum,
                "maximum": self.maximum,
            }
        )
