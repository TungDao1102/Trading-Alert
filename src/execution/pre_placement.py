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

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

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

# Binance New Order (page read 2026-10-19, research B6): `goodTillDate` must be greater than
# now + 600 seconds, with second precision, and is mandatory for timeInForce GTD. This is a
# STRUCTURAL exchange constant, not an owner limit: the owner's own minimum remaining validity is
# a separate, NOT_CONFIGURED value (`min_remaining_validity_seconds`). Assumption A1: the page's
# "current time" is Binance server time, which `gtd_clock_margin` covers (research P7).
GTD_MIN_AHEAD_SECONDS: int = 600

_LONG = "LONG"
_SHORT = "SHORT"
_CANDLE_CLOSE = "CANDLE_CLOSE"
# Same strings as `src.execution.manager.POSITION_MODE_*` (pinned by a test, no import here).
_POSITION_MODE_HEDGE = "HEDGE"
_POSITION_MODE_ONE_WAY = "ONE_WAY"
_MILLISECOND = timedelta(milliseconds=1)
_SECOND = timedelta(seconds=1)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_DENIED_STATUSES = frozenset(
    {TradePlanStatus.EXPIRED, TradePlanStatus.INVALIDATED, TradePlanStatus.SUPERSEDED}
)


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
    `mark_time_utc`, `mark_checked_at_utc`) and on an owner limit
    (`min_remaining_validity_seconds`, `max_mark_price_age_ms`) means "not available" and refuses
    (D-06, D-07).

    `mark_checked_at_utc` is the injected clock read AFTER the mark-price read: the mark age is
    measured against it, never against `now_utc`, which the manager takes before the read
    (19-REVIEW CR-01). `gtd_clock_margin` (the ratified drift bound) is also the most the reading
    may be stamped ahead of `mark_checked_at_utc` before it counts as future-dated.
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
    mark_checked_at_utc: datetime | None
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
        if self.mark_checked_at_utc is not None:
            _require_utc(self.mark_checked_at_utc, "mark_checked_at_utc")
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


def check_plan_status(plan_status: TradePlanStatus) -> str | None:
    """Deny-list on the plan status (D-09).

    EXPIRED, INVALIDATED and SUPERSEDED refuse; READY, APPROVAL_PENDING and APPROVED pass. A
    require-APPROVED rule would be wrong: no production code sets APPROVED yet (research F5) and
    an executed plan stays APPROVED (D051 item i), so it must never be contradicted here.
    """
    if plan_status in _DENIED_STATUSES:
        return PLAN_STATUS_INVALID
    return None


def plan_invalidation_level(trade_plan: TradePlan) -> Decimal:
    """Parse the plan's CANDLE_CLOSE invalidation level (mirror of the backtest rule, D-35).

    Fails closed with `ValueError` on an unparseable rule, a basis other than CANDLE_CLOSE or a
    missing, non-string or non-finite level.
    """
    try:
        rule = json.loads(trade_plan.invalidation_rule_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalidation_rule_json is not valid JSON: {exc}") from exc
    if not isinstance(rule, dict):
        raise ValueError("invalidation_rule_json must be a JSON object")
    basis = rule.get("basis")
    if basis != _CANDLE_CLOSE:
        raise ValueError(f"invalidation basis must be CANDLE_CLOSE, got {basis!r}")
    raw = rule.get("level")
    if not isinstance(raw, str):
        raise ValueError(f"invalidation level must be a decimal string, got {raw!r}")
    try:
        level = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"invalidation level is not a decimal: {raw!r}") from exc
    if not level.is_finite():
        raise ValueError(f"invalidation level must be finite, got {raw!r}")
    return level


def bar_close_invalidates(*, bar_close_price: Decimal, level: Decimal, side: str) -> bool:
    """True when a strategy-bar close is strictly beyond the level (LONG below, SHORT above)."""
    _require_side(side)
    if side == _LONG:
        return bar_close_price < level
    return bar_close_price > level


def check_invalidation(
    *,
    trade_plan: TradePlan,
    side: str,
    signal_invalidated: bool,
    latest_closed_bar_close: Decimal | None,
) -> str | None:
    """Refuse when the signal or the plan's CANDLE_CLOSE rule says the setup is invalid (D-08).

    A signal with `invalidated_at_utc` set, or a latest closed bar close beyond the level, gives
    PLAN_INVALIDATED_BEFORE_PLACEMENT (distinct from the enum `RejectionReason.INVALIDATED`). A
    missing bar close or an unparseable rule gives INVALIDATION_INPUT_UNAVAILABLE (fail closed).
    """
    _require_side(side)
    if signal_invalidated:
        return PLAN_INVALIDATED_BEFORE_PLACEMENT
    if latest_closed_bar_close is None:
        return INVALIDATION_INPUT_UNAVAILABLE
    try:
        level = plan_invalidation_level(trade_plan)
    except ValueError:
        return INVALIDATION_INPUT_UNAVAILABLE
    if bar_close_invalidates(bar_close_price=latest_closed_bar_close, level=level, side=side):
        return PLAN_INVALIDATED_BEFORE_PLACEMENT
    return None


def good_till_date_ms(expiry_utc: datetime) -> int:
    """The `goodTillDate` value: the expiry floored to whole seconds, as epoch milliseconds."""
    _require_utc(expiry_utc, "expiry_utc")
    return ((expiry_utc - _EPOCH) // _SECOND) * 1000


def check_remaining_validity(
    *,
    expiry_utc: datetime,
    now_utc: datetime,
    min_remaining_validity_seconds: int | None,
    gtd_clock_margin: timedelta,
) -> str | None:
    """Refuse when too little validity remains for the owner's minimum or the GTD floor.

    The remaining time is measured to the floored `goodTillDate` second. It must exceed both the
    owner's `min_remaining_validity_seconds` and `GTD_MIN_AHEAD_SECONDS` plus the clock margin
    (research B6, P7). An unset owner minimum is LIMITS_NOT_CONFIGURED (D-07).
    """
    _require_utc(now_utc, "now_utc")
    if min_remaining_validity_seconds is None:
        return LIMITS_NOT_CONFIGURED
    gtd_instant = _EPOCH + timedelta(milliseconds=good_till_date_ms(expiry_utc))
    remaining = gtd_instant - now_utc
    if remaining <= timedelta(seconds=min_remaining_validity_seconds):
        return VALIDITY_TOO_SHORT
    if remaining <= timedelta(seconds=GTD_MIN_AHEAD_SECONDS) + gtd_clock_margin:
        return VALIDITY_TOO_SHORT
    return None


def check_mark_price(
    *,
    side: str,
    mark_price: Decimal | None,
    mark_time_utc: datetime | None,
    now_utc: datetime | None,
    max_mark_price_age_ms: int | None,
    max_clock_skew: timedelta,
    sl_trigger_price: Decimal,
    entry_min_price: Decimal,
    entry_max_price: Decimal,
) -> str | None:
    """Refuse when the live mark price is unusable, crossed the stop, or left the zone.

    `now_utc` is the instant the age is measured at: it must be a clock reading taken AFTER the
    mark-price read (19-REVIEW CR-01), so a fresh reading has a small non-negative age. Binance's
    clock may run ahead of the local one by up to `max_clock_skew` (the ratified drift bound), so a
    reading stamped at most that far in the future is treated as age zero.

    A missing price, time or check instant, an unset age bound, a reading stamped more than
    `max_clock_skew` in the future and an older-than-bound reading all give MARK_PRICE_UNAVAILABLE
    (D-06 fail closed). A LONG whose mark is at or below the stop trigger (SHORT: at or above)
    gives MARK_PRICE_CROSSED_STOP; a mark outside the inclusive entry zone gives
    MARK_PRICE_OUTSIDE_ZONE. The stop convention matches `src.backtest.exits.is_sl_touched`
    (LONG low <= trigger, SHORT high >= trigger).
    """
    _require_side(side)
    if not isinstance(max_clock_skew, timedelta) or max_clock_skew < timedelta(0):
        raise ValueError("max_clock_skew must be a non-negative timedelta")
    if (
        mark_price is None
        or mark_time_utc is None
        or now_utc is None
        or max_mark_price_age_ms is None
    ):
        return MARK_PRICE_UNAVAILABLE
    _require_utc(now_utc, "now_utc")
    _require_utc(mark_time_utc, "mark_time_utc")
    age = now_utc - mark_time_utc
    if age < -max_clock_skew:
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


def check_symbol_free(
    *,
    symbol: str,
    position_symbols: frozenset[str],
    open_order_symbols: frozenset[str] | None,
    any_unprotected: bool,
) -> str | None:
    """Refuse a second plan or any exposure on the symbol, or any unprotected position (RISK-04).

    `any_unprotected` is account-wide (D-11) and is checked first. `open_order_symbols` holds the
    symbols with an open normal or algo order; `None` means the order state could not be read and
    refuses (SYMBOL_STATE_UNAVAILABLE, fail closed). Other symbols never block.
    """
    if any_unprotected:
        return UNPROTECTED_POSITION_EXISTS
    if symbol in position_symbols:
        return SYMBOL_HAS_POSITION
    if open_order_symbols is None:
        return SYMBOL_STATE_UNAVAILABLE
    if symbol in open_order_symbols:
        return SYMBOL_HAS_OPEN_ORDER
    return None


def check_position_mode(position_mode: str) -> str | None:
    """Refuse hedge mode (D-14); one-way passes; any other value is a caller bug.

    The manager calls this after the position-mode read, right before consuming the approval.
    """
    if position_mode == _POSITION_MODE_HEDGE:
        return HEDGE_MODE_UNSUPPORTED
    if position_mode == _POSITION_MODE_ONE_WAY:
        return None
    raise ValueError(f"unknown position mode {position_mode!r}")


def evaluate_pre_placement(inputs: PrePlacementInputs) -> str | None:
    """First failing reason in the fixed order, or `None` when placement may proceed.

    Order: status, invalidation, remaining validity, symbol free, mark price. The position-mode
    check is separate (`check_position_mode`) because it needs the mode read.
    """
    reason = check_plan_status(inputs.plan_status)
    if reason is not None:
        return reason
    reason = check_invalidation(
        trade_plan=inputs.trade_plan,
        side=inputs.side,
        signal_invalidated=inputs.signal_invalidated,
        latest_closed_bar_close=inputs.latest_closed_bar_close,
    )
    if reason is not None:
        return reason
    reason = check_remaining_validity(
        expiry_utc=inputs.expiry_utc,
        now_utc=inputs.now_utc,
        min_remaining_validity_seconds=inputs.min_remaining_validity_seconds,
        gtd_clock_margin=inputs.gtd_clock_margin,
    )
    if reason is not None:
        return reason
    reason = check_symbol_free(
        symbol=inputs.symbol,
        position_symbols=inputs.position_symbols,
        open_order_symbols=inputs.open_order_symbols,
        any_unprotected=inputs.any_unprotected,
    )
    if reason is not None:
        return reason
    return check_mark_price(
        side=inputs.side,
        mark_price=inputs.mark_price,
        mark_time_utc=inputs.mark_time_utc,
        now_utc=inputs.mark_checked_at_utc,
        max_mark_price_age_ms=inputs.max_mark_price_age_ms,
        max_clock_skew=inputs.gtd_clock_margin,
        sl_trigger_price=inputs.sl_trigger_price,
        entry_min_price=inputs.entry_min_price,
        entry_max_price=inputs.entry_max_price,
    )
