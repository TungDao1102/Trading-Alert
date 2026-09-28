"""Pure placement math helpers (Phase 9, plan 09-01).

Per D-05: the execution core is dependency-free (stdlib + Decimal +
`src/core/_decimal.py` only). All placement math — limit-price
derivation, SL-trigger derivation — runs in Decimal with pinned
precision. The adapter converts to the SDK's native numeric type at
the SDK boundary via string-mediated Decimal-to-edge conversion
(RESEARCH Pattern 1).

The module is dependency-free: stdlib + `src/core/_decimal.py` only.
No Binance SDK, no SQLAlchemy, no Pydantic, no Polars.
"""

from __future__ import annotations

from decimal import Decimal

from src.core._decimal import _add, _div


def derive_limit_price(
    *,
    entry_min_price: Decimal,
    entry_max_price: Decimal,
) -> Decimal:
    """Return the zone-mid limit price for a LIMIT_ZONE entry.

    Per D-02 (Phase 5): zone-mid entry_ref = (entry_min + entry_max) / 2.
    Pinned prec-28 so ambient context mutations cannot change the value.

    Args:
        entry_min_price: The lower bound of the entry zone.
        entry_max_price: The upper bound of the entry zone.

    Returns:
        The zone-mid Decimal limit price.
    """
    return _div(_add(entry_min_price, entry_max_price), Decimal("2"))


def derive_sl_trigger_price(*, stop_loss_price: Decimal) -> Decimal:
    """Return the SL trigger price for a CONDITIONAL STOP_MARKET leg.

    For a one-way LONG entry, the SL trigger equals the plan's
    stop_loss_price directly. For a one-way SHORT entry, the SL
    trigger also equals the plan's stop_loss_price (the exchange
    interprets the side to determine trigger direction).

    Args:
        stop_loss_price: The plan's stop_loss_price.

    Returns:
        The SL trigger Decimal price.
    """
    return stop_loss_price


__all__ = ["derive_limit_price", "derive_sl_trigger_price"]
