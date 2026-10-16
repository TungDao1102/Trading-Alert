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

_DIVERGENCE_KINDS: frozenset[str] = frozenset({DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE})


# --------------------------------------------------------------------------- #
# Validation helpers — D-12 boundary discipline.
# --------------------------------------------------------------------------- #


def _require_decimal(value: object, field_name: str) -> None:
    """Reject non-Decimal values for money/qty/price fields (D-12)."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal, got {type(value).__name__}")


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


# --------------------------------------------------------------------------- #
# Frozen dataclasses — the public fill-monitor contract.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FillEvent:
    """One fill event from the user-data WS or REST tick.

    Duck-typed: the fold_fills function accepts both attribute-style
    objects (this dataclass) and dict-style payloads (test fixture
    format). The unique key is `(order_id, exchange_trade_id)`.

    The four optional fields (Phase 18, G3-009) carry the trade's
    commission, commission asset, realized PnL and maker flag from the
    user-data stream; they default to None so every earlier caller is
    unchanged, and they are validated when given.
    """

    order_id: str
    exchange_trade_id: str
    symbol: str
    side: str
    position_side: str
    fill_price: Decimal
    fill_quantity: Decimal
    fill_time_utc: datetime
    commission: Decimal | None = None
    commission_asset: str | None = None
    realized_pnl: Decimal | None = None
    is_maker: bool | None = None

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
        for fname in ("commission", "realized_pnl"):
            if getattr(self, fname) is not None:
                _require_decimal(getattr(self, fname), fname)
        if self.commission_asset is not None:
            _require_non_empty(self.commission_asset, "commission_asset")
        if self.is_maker is not None and not isinstance(self.is_maker, bool):
            raise TypeError(f"is_maker must be bool, got {type(self.is_maker).__name__}")


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
            raise ValueError(f"fill_count {self.fill_count} != len(fills) {len(self.fills)}")


# --------------------------------------------------------------------------- #
# Public entry point.
# --------------------------------------------------------------------------- #


_SIDE_SIGN: dict[str, Decimal] = {"BUY": Decimal("1"), "SELL": Decimal("-1")}


def fold_fills(
    *,
    fill_events: Sequence[Any],
    current_position_view: CurrentPositionView,
    has_protective: bool = True,
    expected_symbol: str | None = None,
    expected_side: str | None = None,
    expected_order_id: str | None = None,
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
        expected_symbol: When given, every event must be for this symbol.
        expected_side: When given ("BUY"/"SELL"), every event must be on
            this side — an exit fill (e.g. a TP1 SELL against a LONG
            entry) can never inflate the entry's filled quantity.
        expected_order_id: When given, every event must belong to this
            order id.

    Returns:
        A `FoldedPositionView` with the folded position, sorted fills,
        and any divergences.

    Raises:
        ValueError: an event is missing its identity (`order_id` /
            `exchange_trade_id`), carries an unknown side, or does not
            match an `expected_*` filter (09-REVIEW WR-04 — flag, never
            fabricate: a malformed or foreign fill is never silently
            skipped or summed).
        TypeError: an event's `fill_quantity` is not a `Decimal` (e.g. a
            raw WS string) — never silently dropped from the sum.
    """
    # Index fills by (order_id, exchange_trade_id) for idempotent dedup.
    unique_fills: dict[tuple[str, str], dict[str, Any]] = {}

    for event in fill_events:
        order_id = _get_field(event, "order_id")
        exchange_trade_id = _get_field(event, "exchange_trade_id")
        if not isinstance(order_id, str) or order_id == "":
            raise ValueError(f"fold_fills: fill event missing order_id: {event!r}")
        if not isinstance(exchange_trade_id, str) or exchange_trade_id == "":
            raise ValueError(f"fold_fills: fill event missing exchange_trade_id: {event!r}")
        symbol = _get_field(event, "symbol")
        side = _get_field(event, "side")
        fill_quantity = _get_field(event, "fill_quantity")
        if not isinstance(fill_quantity, Decimal):
            raise TypeError(
                f"fold_fills: fill_quantity must be Decimal, got "
                f"{type(fill_quantity).__name__} ({order_id}/{exchange_trade_id})"
            )
        if side not in _SIDE_SIGN:
            raise ValueError(f"fold_fills: unknown fill side {side!r} ({order_id})")
        if expected_symbol is not None and symbol != expected_symbol:
            raise ValueError(f"fold_fills: fill symbol {symbol!r} != expected {expected_symbol!r}")
        if expected_side is not None and side != expected_side:
            raise ValueError(f"fold_fills: fill side {side!r} != expected {expected_side!r}")
        if expected_order_id is not None and order_id != expected_order_id:
            raise ValueError(
                f"fold_fills: fill order_id {order_id!r} != expected {expected_order_id!r}"
            )
        key = (order_id, exchange_trade_id)
        if key in unique_fills:
            # Replayed event — skip (idempotent).
            continue
        unique_fills[key] = {
            "order_id": order_id,
            "exchange_trade_id": exchange_trade_id,
            "symbol": symbol or "",
            "side": side,
            "position_side": _get_field(event, "position_side") or "",
            "fill_price": _get_field(event, "fill_price"),
            "fill_quantity": fill_quantity,
            "fill_time_utc": _get_field(event, "fill_time_utc"),
            "commission": _get_field(event, "commission"),
            "commission_asset": _get_field(event, "commission_asset"),
            "realized_pnl": _get_field(event, "realized_pnl"),
            "is_maker": _get_field(event, "is_maker"),
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

    # `filled_quantity` is the unsigned sum of all unique fill quantities;
    # the position amount moves by the SIGNED quantity (Binance position
    # amounts are negative for SHORT — a SELL fill decreases it).
    filled_quantity = Decimal("0")
    signed_delta = Decimal("0")
    for f in sorted_fills:
        qty = f["fill_quantity"]
        filled_quantity = filled_quantity + qty
        signed_delta = signed_delta + _SIDE_SIGN[f["side"]] * qty

    new_position_amt = current_position_view.position_amt + signed_delta

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
