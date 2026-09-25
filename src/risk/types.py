"""Pure-risk frozen dataclasses (Phase 5, plans 05-01 + 05-02).

Per D-05/D-12: frozen pure-Python dataclasses with Decimal money/qty/
price fields and timezone-aware UTC datetime fields. Construction-time
guards mirror the Phase-4 domain pattern (`src/core/types.py`,
`src/domain/trade_plan.py`).

These types are the value objects flowing between the sizing, quantize,
portfolio, and gating services. All four live in this package and share
the same purity contract (stdlib + Decimal + `src/core/_decimal.py` only).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from src.domain.enums import DailyState


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
# ConstraintSnapshot — frozen adapter-edge mirror of SymbolFilters fields
# actually consumed by the risk pipeline (D-05 adapter-boundary isolation).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ConstraintSnapshot:
    """ExchangeInfo-derived constraints consumed by risk math.

    Mirrors the fields the pure risk pipeline reads from the adapter's
    SymbolFilters — never imports the SDK. `metadata_observed_at_utc`
    drives the TTL freshness gate (D-04); step/min/notional drive
    quantization (D-02).
    """

    symbol: str
    price_tick_size: Decimal
    quantity_step_size: Decimal
    min_quantity: Decimal
    min_notional: Decimal
    metadata_observed_at_utc: datetime

    def __post_init__(self) -> None:
        _require_non_empty(self.symbol, "symbol")
        for fname in (
            "price_tick_size",
            "quantity_step_size",
            "min_quantity",
            "min_notional",
        ):
            _require_decimal(getattr(self, fname), fname)
        _require_positive(self.price_tick_size, "price_tick_size")
        _require_positive(self.quantity_step_size, "quantity_step_size")
        _require_positive(self.min_quantity, "min_quantity")
        _require_positive(self.min_notional, "min_notional")
        _require_utc_aware(self.metadata_observed_at_utc, "metadata_observed_at_utc")


# --------------------------------------------------------------------------- #
# SizedResult — discriminated ACCEPTED-or-REJECT envelope emitted by sizing
# + quantization. Mirrors the PlanResult discipline from src/core/types.py.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SizedResult:
    """Sized (or rejected) plan fields emitted by the risk pipeline.

    `is_no_trade=True` carries a canonical RejectionReason value in
    `reason_code`; `quantity` is None in that case (never a stale value
    riding along on a reject — WR-09 mirror for risk output).
    `quantity_before_rounding` and `quantity_after_rounding` are always
    populated; `realized_risk` is the canonical "actual dollars at risk
    after rounding" value used by the utilization gate and logged per
    RISK_MANAGEMENT §11 rule 5.
    """

    is_no_trade: bool
    quantity: Decimal | None
    quantity_before_rounding: Decimal
    quantity_after_rounding: Decimal
    quantization_decision: str
    realized_risk: Decimal
    reason_code: str = "OK"

    def __post_init__(self) -> None:
        _require_non_empty(self.quantization_decision, "quantization_decision")
        _require_non_empty(self.reason_code, "reason_code")
        for fname in (
            "quantity_before_rounding",
            "quantity_after_rounding",
            "realized_risk",
        ):
            _require_decimal(getattr(self, fname), fname)
        if self.is_no_trade:
            if self.quantity is not None:
                raise ValueError("SizedResult: is_no_trade=True requires quantity=None")
        else:
            if self.quantity is None:
                raise ValueError("SizedResult: is_no_trade=False requires quantity to be Decimal")
            _require_decimal(self.quantity, "quantity")
            if self.quantity <= Decimal("0"):
                raise ValueError(f"SizedResult: quantity {self.quantity} must be > 0 when sized")


# --------------------------------------------------------------------------- #
# OpenPosition — frozen caller-supplied snapshot of one open position (D-03).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class OpenPosition:
    """One open position in the reconciled portfolio snapshot (D-03).

    `open_risk` is the precomputed realized risk in quote currency
    (caller-supplied — risk does not value positions from mark prices).
    `daily_pnl_contribution` is reserved for Phase-7+ journaling (zero
    in V1).
    """

    symbol: str
    position_side: str
    open_risk: Decimal
    daily_pnl_contribution: Decimal

    def __post_init__(self) -> None:
        _require_non_empty(self.symbol, "symbol")
        _require_non_empty(self.position_side, "position_side")
        _require_decimal(self.open_risk, "open_risk")
        _require_decimal(self.daily_pnl_contribution, "daily_pnl_contribution")
        if self.open_risk < Decimal("0"):
            raise ValueError(f"open_risk {self.open_risk} must be >= 0")


# --------------------------------------------------------------------------- #
# PortfolioVerdict — discriminated PASS-or-NO_TRADE envelope (D-03/D-04).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PortfolioVerdict:
    """Discriminated PASS-or-NO_TRADE envelope emitted by `check_portfolio`.

    `is_no_trade=True` carries a canonical RejectionReason value in
    `reason_code` (CLUSTER_CAP_REJECT, AGGREGATE_CAP_REJECT,
    MAX_POSITIONS_REJECT, DAILY_STOP_BLOCK, STALE_CONSTRAINTS,
    UNCERTAIN_ACCOUNT_STATE) and `sized=None`.
    `is_no_trade=False` carries the input SizedResult plus the derived
    `daily_state` (NORMAL / WARNING / DAILY_STOP) for downstream
    consumers (Phase-8 SAFE_MODE interplay).
    """

    is_no_trade: bool
    sized: SizedResult | None
    reason_code: str
    daily_state: DailyState

    def __post_init__(self) -> None:
        _require_non_empty(self.reason_code, "reason_code")
        if not isinstance(self.daily_state, DailyState):
            raise TypeError(
                f"daily_state must be DailyState, got {type(self.daily_state).__name__}"
            )
        if self.is_no_trade:
            if self.sized is not None:
                raise ValueError(
                    "PortfolioVerdict: is_no_trade=True requires sized=None"
                )
        else:
            if self.sized is None:
                raise ValueError(
                    "PortfolioVerdict: is_no_trade=False requires sized"
                )


__all__ = [
    "ConstraintSnapshot",
    "OpenPosition",
    "PortfolioVerdict",
    "SizedResult",
]
