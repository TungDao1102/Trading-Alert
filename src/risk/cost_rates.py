"""Price-aware round-trip cost producer (Phase 12, plan 12-03, D-01).

One pure producer, `per_unit_round_trip_cost`, returns the modeled round
trip cost in QUOTE CURRENCY PER ONE UNIT OF BASE:

    entry_price * (fee_rate_entry + entry_slippage_rate)
      + stop_price * (fee_rate_exit + exit_slippage_rate)

The old rate-sum (`fee_in + fee_out + slippage`, a dimensionless rate)
was added to a price distance (quote per unit); the units differ by the
price, so the cost was under-counted by orders of magnitude on high-priced
symbols (F-001, F-801). This producer takes the two prices explicitly so
the result is linear in price and the units are right by construction.

The function takes `side` although the formula is side-symmetric today so a
later funding-sign term needs no signature change. `entry_price` is the
sizing entry; `stop_price` is the stop trigger price (the exit leg of the
worst-case loss the sizing risk budget is measured against).

Purity (Phase 5 D-05): stdlib, Decimal and `src/core/_decimal.py` only.
This module imports NOTHING from `src/backtest` (backtest imports risk,
never the reverse) and performs no float arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.core._decimal import _add, _mul

FEE_SOURCE_PARAMETER = "PARAMETER"
FEE_SOURCE_ACCOUNT_MAX = "ACCOUNT_MAX"
FEE_SOURCES: frozenset[str] = frozenset({FEE_SOURCE_PARAMETER, FEE_SOURCE_ACCOUNT_MAX})

# Unit guard (D-04): a fee or slippage RATE above 1 percent is a unit error
# (percent typed where a fraction was meant), never a real Binance rate.
MAX_RATE = Decimal("0.01")

_RATE_FIELDS: tuple[str, ...] = (
    "fee_rate_entry",
    "entry_slippage_rate",
    "fee_rate_exit",
    "exit_slippage_rate",
)


def _require_decimal(value: object, field_name: str) -> Decimal:
    """Reject non-Decimal values (bool, int, float and str included)."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal, got {type(value).__name__}")
    return value


@dataclass(frozen=True)
class CostRates:
    """The four rates the cost producer needs plus where the fee came from.

    Every rate is a Decimal fraction in [0, MAX_RATE]. `fee_source` records
    whether the fee rates are registry parameters (`PARAMETER`) or the
    account-derived maximum (`ACCOUNT_MAX`).
    """

    fee_rate_entry: Decimal
    entry_slippage_rate: Decimal
    fee_rate_exit: Decimal
    exit_slippage_rate: Decimal
    fee_source: str

    def __post_init__(self) -> None:
        for fname in _RATE_FIELDS:
            value = _require_decimal(getattr(self, fname), fname)
            if not value.is_finite() or value < Decimal("0") or value > MAX_RATE:
                raise ValueError(f"{fname} must be in [0, {MAX_RATE}], got {value}")
        if self.fee_source not in FEE_SOURCES:
            raise ValueError(
                f"fee_source must be one of {sorted(FEE_SOURCES)}, got {self.fee_source!r}"
            )


def _require_price(value: object, field_name: str) -> Decimal:
    price = _require_decimal(value, field_name)
    if not price.is_finite() or price <= Decimal("0"):
        raise ValueError(f"{field_name} must be > 0, got {price}")
    return price


def per_unit_round_trip_cost(
    *,
    side: str,
    entry_price: Decimal,
    stop_price: Decimal,
    rates: CostRates,
) -> Decimal:
    """Return the modeled round-trip cost, quote currency per one unit of base.

    Formula: `entry_price * (fee_rate_entry + entry_slippage_rate)
    + stop_price * (fee_rate_exit + exit_slippage_rate)`.

    Args:
        side: "LONG" or "SHORT". Side-symmetric today; taken now so a later
            funding-sign term needs no signature change.
        entry_price: the sizing entry price (Decimal, > 0).
        stop_price: the stop trigger price (Decimal, > 0).
        rates: the four cost rates.

    Raises:
        ValueError: side is neither LONG nor SHORT, or a price is <= 0.
        TypeError: a price is not a Decimal.
    """
    if side not in {"LONG", "SHORT"}:
        raise ValueError(f"side must be LONG or SHORT, got {side!r}")
    entry = _require_price(entry_price, "entry_price")
    stop = _require_price(stop_price, "stop_price")
    entry_leg = _mul(entry, _add(rates.fee_rate_entry, rates.entry_slippage_rate))
    exit_leg = _mul(stop, _add(rates.fee_rate_exit, rates.exit_slippage_rate))
    return _add(entry_leg, exit_leg)


__all__ = [
    "FEE_SOURCES",
    "FEE_SOURCE_ACCOUNT_MAX",
    "FEE_SOURCE_PARAMETER",
    "MAX_RATE",
    "CostRates",
    "per_unit_round_trip_cost",
]
