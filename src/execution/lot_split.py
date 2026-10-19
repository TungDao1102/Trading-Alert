"""Pure lot arithmetic for the emergency close and the TP legs (Phase 19, plan 19-04).

A MARKET exit must satisfy LOT_SIZE and MARKET_LOT_SIZE at once (research A7). Every
quantity is checked in exact Decimal: `min <= q <= max` and `(q - min)` a whole multiple
of `step`. All arithmetic runs on exact integers (the Decimals scaled to a common power
of ten), so no float and no context rounding is involved.

The set of valid MARKET quantities is the intersection of two arithmetic progressions, which
is itself one progression `q = r (mod m)` bounded by `[lo, hi]`; it is computed in closed form
(Chinese remainder), never by search. A close that cannot be built is reported as `None` or
`complete=False`, never rounded up (D-16): the caller turns it into SAFE_MODE, a critical
alert and manual intervention. The emergency close re-reads the position from the exchange
after each part, so the running total here is never trusted by the coordinator.

Purity: stdlib, Decimal, `src.domain` and `src.execution.constraint_snapshot`. No clock, no
float, no SDK.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import gcd

from src.domain.lot_filters import LotFilters

# --------------------------------------------------------------------------- #
# Exact integer scaling
# --------------------------------------------------------------------------- #


def _decimal_places(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    assert isinstance(exponent, int)  # finite Decimals only
    return max(0, -exponent)


def _to_units(value: Decimal, places: int) -> int:
    """`value * 10**places` as an exact int (`places` covers every digit of `value`)."""
    sign, digits, exponent = value.as_tuple()
    assert isinstance(exponent, int)
    scale: int = 10 ** (exponent + places)
    magnitude = int("".join(str(d) for d in digits) or "0") * scale
    return -magnitude if sign else magnitude


def _from_units(units: int, places: int) -> Decimal:
    return Decimal(f"{units}E-{places}")


@dataclass(frozen=True)
class _Grid:
    """Valid quantities `q = residue (mod modulus)` with `lo <= q <= hi`, in integer units."""

    places: int
    residue: int
    modulus: int
    lo: int
    hi: int

    def floor(self, limit: int) -> int | None:
        """Largest valid quantity at or below `limit`, or None."""
        top = min(limit, self.hi)
        candidate = top - ((top - self.residue) % self.modulus)
        return candidate if self.lo <= candidate <= self.hi else None


def _grid(filters: LotFilters, *, market_exit: bool, extra: Decimal | None = None) -> _Grid:
    """The valid-quantity grid: LOT_SIZE alone, or its intersection with MARKET_LOT_SIZE.

    `extra` is a further Decimal (a remaining quantity) whose digits the common scale must
    cover.
    """
    values = [
        filters.lot_min_quantity,
        filters.lot_max_quantity,
        filters.lot_step_size,
        filters.market_lot_min_quantity,
        filters.market_lot_max_quantity,
        filters.market_lot_step_size,
    ]
    if extra is not None:
        values.append(extra)
    places = max(_decimal_places(v) for v in values)
    lot_min = _to_units(filters.lot_min_quantity, places)
    lot_max = _to_units(filters.lot_max_quantity, places)
    lot_step = _to_units(filters.lot_step_size, places)
    if not market_exit:
        return _Grid(places, lot_min % lot_step, lot_step, lot_min, lot_max)
    mkt_min = _to_units(filters.market_lot_min_quantity, places)
    mkt_max = _to_units(filters.market_lot_max_quantity, places)
    mkt_step = _to_units(filters.market_lot_step_size, places)
    # Solve lot_min + a * lot_step == mkt_min (mod mkt_step) for the common residue.
    g = gcd(lot_step, mkt_step)
    diff = mkt_min - lot_min
    if diff % g != 0:
        # The two progressions never meet: no quantity is valid under both filters.
        return _Grid(places, 0, 1, 1, 0)
    modulus = lot_step // g * mkt_step
    reduced = mkt_step // g
    a = (diff // g) * pow(lot_step // g, -1, reduced) % reduced if reduced > 1 else 0
    residue = (lot_min + a * lot_step) % modulus
    return _Grid(places, residue, modulus, max(lot_min, mkt_min), min(lot_max, mkt_max))


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def is_valid_market_part(quantity: Decimal, filters: LotFilters) -> bool:
    """True when `quantity` satisfies LOT_SIZE and MARKET_LOT_SIZE, exactly."""
    if not isinstance(quantity, Decimal) or not quantity.is_finite() or quantity <= 0:
        return False
    for lo, hi, step in (
        (filters.lot_min_quantity, filters.lot_max_quantity, filters.lot_step_size),
        (
            filters.market_lot_min_quantity,
            filters.market_lot_max_quantity,
            filters.market_lot_step_size,
        ),
    ):
        if quantity < lo or quantity > hi or (quantity - lo) % step != 0:
            return False
    return True


def next_close_part(*, remaining: Decimal, filters: LotFilters) -> Decimal | None:
    """One MARKET close quantity valid under LOT_SIZE and MARKET_LOT_SIZE, or None.

    The part never exceeds `remaining`. None means no valid part exists (the caller enters
    SAFE_MODE and needs manual intervention); nothing is rounded up.
    """
    if not isinstance(remaining, Decimal) or not remaining.is_finite() or remaining <= 0:
        return None
    grid = _grid(filters, market_exit=True, extra=remaining)
    part = grid.floor(_to_units(remaining, grid.places))
    return None if part is None else _from_units(part, grid.places)
