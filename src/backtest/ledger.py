"""Pure simulated ledger for the causal backtest (Phase 14, plan 14-05, D-18, D-32).

The ledger starts from the account equity and changes only through dated `Booking`s
(entry fee and slippage at the fill, exit legs net of fee and slippage at the exit,
funding at its fundingTime). Equity is realized-only (D-18): there is no mark-to-market.
The simulation engine (plan 14-08) feeds `evaluate_risk` from `ledger.equity`,
`daily_loss_quote`, `open_positions_for_risk` and `ledger.thresholds`, so the backtest
runs the same gates as paper and live.

The daily-loss day is the UTC day (D033). Absolute thresholds are re-resolved against the
equity at each UTC day start (`resolve_absolute_thresholds`), never per booking, and the
NORMAL/WARNING/DAILY_STOP state always comes from `derive_daily_state`, never a copy of
its rule. When the state is DAILY_STOP, `cancel_resting_required` tells the engine to
cancel resting entries while open positions keep their stop (D033, D-32).

Every function takes a `Ledger` and returns a new one; a `Ledger` is never mutated. The
module imports NOTHING from Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic and reads
no clock: stdlib + Decimal + `src/core/_decimal.py` + the pure `src.risk` functions only.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.core._decimal import _add, _sub
from src.domain.enums import DailyState
from src.risk.portfolio import (
    RATE_THRESHOLD_KEYS,
    derive_daily_state,
    resolve_absolute_thresholds,
)

from .records import Booking

_ZERO = Decimal("0")


@dataclass(frozen=True)
class Ledger:
    """Simulated account state at one instant (immutable value object).

    `parameter_set_params` is the raw registry mapping (equity-fraction rates);
    `thresholds` is the same mapping with the rate keys resolved to absolute quote
    amounts against `equity_at_day_start`, ready for `evaluate_risk(parameter_set=...)`.
    `day_start_utc` is the 00:00:00 UTC of the current day, `day_pnl` the sum of the
    bookings dated in that day and `last_booking_time_utc` the latest applied booking
    (the order guard). Neither dict may be mutated by callers.
    """

    initial_equity: Decimal
    equity: Decimal
    parameter_set_params: dict[str, Any]
    thresholds: dict[str, Any]
    day_start_utc: datetime
    equity_at_day_start: Decimal
    day_pnl: Decimal
    last_booking_time_utc: datetime | None

    @classmethod
    def start(
        cls,
        *,
        equity: Decimal,
        parameter_set_params: dict[str, Any],
        at_utc: datetime,
    ) -> Ledger:
        """Open a ledger with `equity` at `at_utc`; the UTC day of `at_utc` is day 1.

        Raises:
            TypeError: `equity` is not a Decimal.
            ValueError: `equity` is not positive, or `at_utc` is not UTC-aware.
        """
        if not isinstance(equity, Decimal):
            raise TypeError(f"equity must be Decimal, got {type(equity).__name__}")
        _require_utc(at_utc, "at_utc")
        params = dict(parameter_set_params)
        return cls(
            initial_equity=equity,
            equity=equity,
            parameter_set_params=params,
            thresholds=_resolve_thresholds(params, equity),
            day_start_utc=_utc_day_start(at_utc),
            equity_at_day_start=equity,
            day_pnl=_ZERO,
            last_booking_time_utc=None,
        )


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")


def _utc_day_start(at_utc: datetime) -> datetime:
    """00:00:00.000 UTC of the UTC day containing `at_utc` (midnight belongs to the new day)."""
    return at_utc.replace(hour=0, minute=0, second=0, microsecond=0)


def _resolve_thresholds(params: dict[str, Any], equity: Decimal) -> dict[str, Any]:
    """Absolute thresholds against `equity`; exhausted equity fails closed to zero.

    `resolve_absolute_thresholds` refuses non-positive equity. A ledger can legitimately
    reach that state, so the rate keys then resolve to 0: every loss (even 0) is
    `>= stop`, which derives DAILY_STOP, and every cap rejects. The engine additionally
    stops opening trades through `equity_positive`.
    """
    if equity > _ZERO:
        return resolve_absolute_thresholds(parameter_set=params, equity=equity)
    resolved = dict(params)
    for key in RATE_THRESHOLD_KEYS:
        resolved[key] = _ZERO
    return resolved


def _roll(ledger: Ledger, at_utc: datetime) -> Ledger:
    """Advance to the UTC day of `at_utc`: reset the day PnL and re-resolve thresholds."""
    _require_utc(at_utc, "at_utc")
    new_day_start = _utc_day_start(at_utc)
    if new_day_start < ledger.day_start_utc:
        raise ValueError(
            f"cannot roll the ledger backwards: {at_utc.isoformat()} is before the "
            f"current day start {ledger.day_start_utc.isoformat()}"
        )
    if new_day_start == ledger.day_start_utc:
        return ledger
    return replace(
        ledger,
        day_start_utc=new_day_start,
        equity_at_day_start=ledger.equity,
        day_pnl=_ZERO,
        thresholds=_resolve_thresholds(ledger.parameter_set_params, ledger.equity),
    )


def apply_booking(ledger: Ledger, booking: Booking) -> Ledger:
    """Book one dated amount: roll the UTC day if needed, then add it to equity and day PnL.

    Bookings must arrive in non-decreasing time order (the engine sorts by time, then
    symbol); an earlier booking raises `ValueError`. A booking exactly at 00:00:00.000 UTC
    belongs to the new day.

    Raises:
        TypeError: the amount is not a Decimal.
        ValueError: the booking time is naive/non-UTC or earlier than the last booking.
    """
    if not isinstance(booking.amount, Decimal):
        raise TypeError(f"booking amount must be Decimal, got {type(booking.amount).__name__}")
    _require_utc(booking.time_utc, "booking.time_utc")
    last = ledger.last_booking_time_utc
    if last is not None and booking.time_utc < last:
        raise ValueError(
            "bookings must be applied in non-decreasing time order: "
            f"{booking.time_utc.isoformat()} is before {last.isoformat()}"
        )
    rolled = _roll(ledger, booking.time_utc)
    return replace(
        rolled,
        equity=_add(rolled.equity, booking.amount),
        day_pnl=_add(rolled.day_pnl, booking.amount),
        last_booking_time_utc=booking.time_utc,
    )


def daily_loss_quote(ledger: Ledger) -> Decimal:
    """Loss of the current UTC day in quote currency: `max(0, -day_pnl)`."""
    loss = _sub(_ZERO, ledger.day_pnl)
    return loss if loss > _ZERO else _ZERO


def daily_state(ledger: Ledger) -> DailyState:
    """NORMAL / WARNING / DAILY_STOP from the shared `derive_daily_state` rule."""
    return derive_daily_state(
        daily_loss_quote=daily_loss_quote(ledger),
        parameter_set=ledger.thresholds,
    )


def cancel_resting_required(ledger: Ledger) -> bool:
    """True when resting entries must be cancelled (DAILY_STOP, D033); open stops stay."""
    return daily_state(ledger) is DailyState.DAILY_STOP


__all__ = [
    "Ledger",
    "apply_booking",
    "cancel_resting_required",
    "daily_loss_quote",
    "daily_state",
]
