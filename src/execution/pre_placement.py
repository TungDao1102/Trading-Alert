"""Pure pre-placement refusals (Phase 19, plan 19-03; D-05..D-09, D-14, RISK-04).

Every check is a pure function of injected values and returns a reason code or `None`.
`evaluate_pre_placement` runs them first-failure-wins in a fixed order (status, invalidation,
remaining validity, symbol free, mark price). The execution manager (plan 19-13) performs the
adapter reads and passes the values in; every refusal happens before the approval is consumed.

The module imports only stdlib, `decimal` and `src.domain`: no clock, no float, no SDK, no
`src.backtest` (the backtest imports `src.execution.placement`, so the invalidation rule is
re-implemented here and pinned against the backtest in the tests).

Recorded, not decided:

- Q2: only the mark price is read; the stop triggers on MARK_PRICE (D037), so a last-price read is
  deliberately not added.
- Q6: the latest closed strategy-bar close is a required injected value; its producer is Phase 24.
- Q7: the exchange open-order snapshot is the authority for "another order on the symbol"; an
  intent-store cross-check needs a new store query and is not built here.

RISK-04: no input describes prior losses, a target or a running PnL, so a size can never grow
because of earlier results.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from src.domain.enums import TradePlanStatus
from src.domain.trade_plan import TradePlan

# Reason codes. PLAN_INVALIDATED_BEFORE_PLACEMENT is deliberately distinct from the enum
# `RejectionReason.INVALIDATED` (D-08): the new code never renames or aliases it.
PLAN_STATUS_INVALID = "PLAN_STATUS_INVALID"
PLAN_INVALIDATED_BEFORE_PLACEMENT = "PLAN_INVALIDATED_BEFORE_PLACEMENT"
INVALIDATION_INPUT_UNAVAILABLE = "INVALIDATION_INPUT_UNAVAILABLE"
VALIDITY_TOO_SHORT = "VALIDITY_TOO_SHORT"
LIMITS_NOT_CONFIGURED = "LIMITS_NOT_CONFIGURED"
SYMBOL_HAS_POSITION = "SYMBOL_HAS_POSITION"
SYMBOL_HAS_OPEN_ORDER = "SYMBOL_HAS_OPEN_ORDER"
UNPROTECTED_POSITION_EXISTS = "UNPROTECTED_POSITION_EXISTS"
SYMBOL_STATE_UNAVAILABLE = "SYMBOL_STATE_UNAVAILABLE"
MARK_PRICE_UNAVAILABLE = "MARK_PRICE_UNAVAILABLE"
MARK_PRICE_CROSSED_STOP = "MARK_PRICE_CROSSED_STOP"
MARK_PRICE_OUTSIDE_ZONE = "MARK_PRICE_OUTSIDE_ZONE"
HEDGE_MODE_UNSUPPORTED = "HEDGE_MODE_UNSUPPORTED"

_LONG = "LONG"
_SHORT = "SHORT"
_MILLISECOND = timedelta(milliseconds=1)


def _require_side(side: str) -> None:
    if side not in (_LONG, _SHORT):
        raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def _require_utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be a UTC-aware datetime")


def _require_decimal(value: object, name: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal, got {type(value).__name__}")


def _require_optional_int(value: object, name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be int or None, got {type(value).__name__}")


@dataclass(frozen=True, kw_only=True)
class PrePlacementInputs:
    """Every value `evaluate_pre_placement` reads; all fields are required (no defaults).

    `None` on a live reading (`latest_closed_bar_close`, `open_order_symbols`, `mark_price`,
    `mark_time_utc`) and on an owner limit (`min_remaining_validity_seconds`,
    `max_mark_price_age_ms`) means "not available" and refuses (D-06, D-07).
    """

    side: str
    plan_status: TradePlanStatus
    signal_invalidated: bool
    trade_plan: TradePlan
    latest_closed_bar_close: Decimal | None
    expiry_utc: datetime
    now_utc: datetime
    min_remaining_validity_seconds: int | None
    gtd_clock_margin: timedelta
    position_symbols: frozenset[str]
    open_order_symbols: frozenset[str] | None
    any_unprotected: bool
    symbol: str
    mark_price: Decimal | None
    mark_time_utc: datetime | None
    max_mark_price_age_ms: int | None
    sl_trigger_price: Decimal
    entry_min_price: Decimal
    entry_max_price: Decimal

    def __post_init__(self) -> None:
        _require_side(self.side)
        if not isinstance(self.plan_status, TradePlanStatus):
            raise TypeError("plan_status must be a TradePlanStatus")
        _require_utc(self.expiry_utc, "expiry_utc")
        _require_utc(self.now_utc, "now_utc")
        if self.mark_time_utc is not None:
            _require_utc(self.mark_time_utc, "mark_time_utc")
        for name in ("sl_trigger_price", "entry_min_price", "entry_max_price"):
            _require_decimal(getattr(self, name), name)
        for name in ("latest_closed_bar_close", "mark_price"):
            value = getattr(self, name)
            if value is not None:
                _require_decimal(value, name)
        _require_optional_int(self.min_remaining_validity_seconds, "min_remaining_validity_seconds")
        _require_optional_int(self.max_mark_price_age_ms, "max_mark_price_age_ms")
        if not isinstance(self.gtd_clock_margin, timedelta):
            raise TypeError("gtd_clock_margin must be a timedelta")
        if not self.symbol:
            raise ValueError("symbol must be non-empty")


def check_mark_price(
    *,
    side: str,
    mark_price: Decimal | None,
    mark_time_utc: datetime | None,
    now_utc: datetime,
    max_mark_price_age_ms: int | None,
    sl_trigger_price: Decimal,
    entry_min_price: Decimal,
    entry_max_price: Decimal,
) -> str | None:
    """Refuse when the live mark price is unusable, crossed the stop, or left the zone.

    A missing price or time, an unset age bound, a future-dated reading (negative age) and an
    older-than-bound reading all give MARK_PRICE_UNAVAILABLE (D-06 fail closed). A LONG whose mark
    is at or below the stop trigger (SHORT: at or above) gives MARK_PRICE_CROSSED_STOP; a mark
    outside the inclusive entry zone gives MARK_PRICE_OUTSIDE_ZONE. The stop convention matches
    `src.backtest.exits.is_sl_touched` (LONG low <= trigger, SHORT high >= trigger).
    """
    _require_side(side)
    _require_utc(now_utc, "now_utc")
    if mark_price is None or mark_time_utc is None or max_mark_price_age_ms is None:
        return MARK_PRICE_UNAVAILABLE
    _require_utc(mark_time_utc, "mark_time_utc")
    age = now_utc - mark_time_utc
    if age < timedelta(0):
        return MARK_PRICE_UNAVAILABLE
    if age // _MILLISECOND > max_mark_price_age_ms:
        return MARK_PRICE_UNAVAILABLE
    if side == _LONG:
        crossed = mark_price <= sl_trigger_price
    else:
        crossed = mark_price >= sl_trigger_price
    if crossed:
        return MARK_PRICE_CROSSED_STOP
    if mark_price < entry_min_price or mark_price > entry_max_price:
        return MARK_PRICE_OUTSIDE_ZONE
    return None


def evaluate_pre_placement(inputs: PrePlacementInputs) -> str | None:
    """First failing reason in the fixed order, or `None` when placement may proceed.

    Order: status, invalidation, remaining validity, symbol free, mark price (the later checks are
    added by the following tasks of plan 19-03).
    """
    return check_mark_price(
        side=inputs.side,
        mark_price=inputs.mark_price,
        mark_time_utc=inputs.mark_time_utc,
        now_utc=inputs.now_utc,
        max_mark_price_age_ms=inputs.max_mark_price_age_ms,
        sl_trigger_price=inputs.sl_trigger_price,
        entry_min_price=inputs.entry_min_price,
        entry_max_price=inputs.entry_max_price,
    )
