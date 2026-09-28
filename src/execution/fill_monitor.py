"""Fill monitor — idempotent fill-event folding (Phase 9, plan 09-02).

Per D-02: fill events arriving out of order or replayed reconcile to a
single position view. Entry-without-protective is a divergence that
forces SAFE_MODE via the Phase-8 reconciler (sweeper never places
rescue protection).

The module is dependency-free: stdlib + `src/domain/enums.py` only.
No Binance SDK, no SQLAlchemy, no Pydantic, no Polars.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

# --------------------------------------------------------------------------- #
# Divergence-kind vocabulary.
#
# The fill monitor surfaces ENTRY_WITHOUT_PROTECTIVE for the Phase-8
# reconciler SAFE_MODE composition. The monitor never places rescue
# protection per D-02 — the divergence is a signal, not an action.
# --------------------------------------------------------------------------- #

DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE: str = "ENTRY_WITHOUT_PROTECTIVE"

_DIVERGENCE_KINDS: frozenset[str] = frozenset(
    {DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE}
)


# --------------------------------------------------------------------------- #
# Validation helpers — D-12 boundary discipline.
# --------------------------------------------------------------------------- #


def _require_decimal(value: object, field_name: str) -> None:
    """Reject non-Decimal values for money/qty/price fields (D-12)."""
    if not isinstance(value, Decimal):
        raise TypeError(
            f"{field_name} must be Decimal, got {type(value).__name__}"
        )


def _require_non_empty(value: str, field_name: str) -> None:
    """Reject empty strings for validated non-empty fields."""
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_utc_aware(value: datetime, field_name: str) -> None:
    """Reject naive and non-UTC datetimes (D-12)."""
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(
            f"{field_name} must be UTC, got offset {value.utcoffset()}"
        )


# --------------------------------------------------------------------------- #
# Frozen dataclasses — the public fill-monitor contract.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FillEvent:
    """One fill event from the user-data WS or REST tick.

    Duck-typed: the fold_fills function accepts both attribute-style
    objects (this dataclass) and dict-style payloads (test fixture
    format). The unique key is `(order_id, exchange_trade_id)`.
    """

    order_id: str
    exchange_trade_id: str
    symbol: str
    side: str
    position_side: str
    fill_price: Decimal
    fill_quantity: Decimal
    fill_time_utc: datetime

    def __post_init__(self) -> None:
        for fname in (
            "order_id",
            "exchange_trade_id",
            "symbol",
            "side",
            "position_side",
        ):
            _require_non_empty(getattr(self, fname), fname)
        for fname in ("fill_price", "fill_quantity"):
            _require_decimal(getattr(self, fname), fname)
        _require_utc_aware(self.fill_time_utc, "fill_time_utc")


@dataclass(frozen=True)
class CurrentPositionView:
    """The current position view from the reconciler.

    `position_amt` is the current position amount (positive for LONG,
    negative for SHORT, zero for flat).
    """

    symbol: str
    position_side: str
    position_amt: Decimal

    def __post_init__(self) -> None:
        _require_non_empty(self.symbol, "symbol")
        _require_non_empty(self.position_side, "position_side")
        _require_decimal(self.position_amt, "position_amt")


@dataclass(frozen=True)
class FoldedPositionView:
    """The result of `fold_fills`.

    `filled_quantity` is the sum of all unique fill quantities.
    `fill_count` is the number of unique fills (after dedup).
    `fills` is the sorted list of unique fill dicts.
    `divergences` is the list of typed divergences for the reconciler.
    """

    symbol: str
    position_side: str
    position_amt: Decimal
    filled_quantity: Decimal
    fill_count: int
    fills: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    divergences: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_non_empty(self.symbol, "symbol")
        _require_non_empty(self.position_side, "position_side")
        _require_decimal(self.position_amt, "position_amt")
        _require_decimal(self.filled_quantity, "filled_quantity")
        if self.fill_count < 0:
            raise ValueError(f"fill_count must be >= 0, got {self.fill_count}")
        if self.fill_count != len(self.fills):
            raise ValueError(
                f"fill_count {self.fill_count} != len(fills) {len(self.fills)}"
            )


# --------------------------------------------------------------------------- #
# Public entry point.
# --------------------------------------------------------------------------- #


def fold_fills(
    *,
    fill_events: Sequence[Any],
    current_position_view: CurrentPositionView,
    has_protective: bool = True,
) -> FoldedPositionView:
    """Fold fill events idempotently to a single position view.

    Per D-02: fill events arriving out of order or replayed reconcile
    to a single position view. The unique key is `(order_id,
    exchange_trade_id)` — mirroring the `FillRow` unique constraint
    precedent (STATE.md 03-04 decision).

    Entry-without-protective surfaces as divergence kind
    ENTRY_WITHOUT_PROTECTIVE for the Phase-8 reconciler SAFE_MODE
    composition. The monitor never places rescue protection per D-02.

    Args:
        fill_events: Sequence of `FillEvent` (or duck-typed equivalents
            with `order_id`, `exchange_trade_id`, `symbol`, `side`,
            `position_side`, `fill_price`, `fill_quantity`,
            `fill_time_utc` attributes/keys).
        current_position_view: The current position view from the
            reconciler.
        has_protective: Whether a protective is attached to the entry.
            If False, the monitor surfaces ENTRY_WITHOUT_PROTECTIVE
            divergence. Default True (protective attached).

    Returns:
        A `FoldedPositionView` with the folded position, sorted fills,
        and any divergences.
    """
    # Index fills by (order_id, exchange_trade_id) for idempotent dedup.
    unique_fills: dict[tuple[str, str], dict[str, Any]] = {}

    for event in fill_events:
        order_id = _get_field(event, "order_id")
        exchange_trade_id = _get_field(event, "exchange_trade_id")
        if not isinstance(order_id, str) or order_id == "":
            continue
        if not isinstance(exchange_trade_id, str) or exchange_trade_id == "":
            continue
        key = (order_id, exchange_trade_id)
        if key in unique_fills:
            # Replayed event — skip (idempotent).
            continue
        unique_fills[key] = {
            "order_id": order_id,
            "exchange_trade_id": exchange_trade_id,
            "symbol": _get_field(event, "symbol") or "",
            "side": _get_field(event, "side") or "",
            "position_side": _get_field(event, "position_side") or "",
            "fill_price": _get_field(event, "fill_price"),
            "fill_quantity": _get_field(event, "fill_quantity"),
            "fill_time_utc": _get_field(event, "fill_time_utc"),
        }

    # Sort deterministically by (symbol, order_id, exchange_trade_id).
    sorted_fills = sorted(
        unique_fills.values(),
        key=lambda f: (
            f["symbol"],
            f["order_id"],
            f["exchange_trade_id"],
        ),
    )

    # Compute filled_quantity as the sum of all unique fill quantities.
    filled_quantity = Decimal("0")
    for f in sorted_fills:
        qty = f["fill_quantity"]
        if isinstance(qty, Decimal):
            filled_quantity = filled_quantity + qty

    new_position_amt = current_position_view.position_amt + filled_quantity

    divergences: list[dict[str, Any]] = []
    if not has_protective and len(sorted_fills) > 0:
        divergences.append(
            {
                "kind": DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE,
                "symbol": current_position_view.symbol,
                "order_role": current_position_view.position_side,
                "client_order_id": None,
                "client_algo_id": None,
                "reason": (
                    "entry fills with no protective attached — "
                    "forces SAFE_MODE via Phase-8 reconciler"
                ),
            }
        )

    return FoldedPositionView(
        symbol=current_position_view.symbol,
        position_side=current_position_view.position_side,
        position_amt=new_position_amt,
        filled_quantity=filled_quantity,
        fill_count=len(sorted_fills),
        fills=tuple(sorted_fills),
        divergences=tuple(divergences),
    )


# --------------------------------------------------------------------------- #
# Internal helpers.
# --------------------------------------------------------------------------- #


def _get_field(entry: Any, field_name: str) -> Any:
    """Read a field from either an object (attribute) or a dict (key).

    Mirrors `src/reconcile/compare.py:_get_field` — the duck-typed
    lookup is intentional so the fill monitor accepts both attribute-
    style objects (the canonical `FillEvent` dataclass) and dict-style
    payloads (the test fixture format).
    """
    if isinstance(entry, dict):
        return entry.get(field_name)
    return getattr(entry, field_name, None)


__all__ = [
    "fold_fills",
    "FillEvent",
    "CurrentPositionView",
    "FoldedPositionView",
    "DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE",
]
