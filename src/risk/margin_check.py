"""Pure available-margin predicate (Phase 22, plan 22-04; D-13, criterion 3, F-966).

Question answered: does the exchange's free margin cover the new order plus every other claim on
margin? The answer is a `MarginVerdict`, never an exception, so a refused plan is a NO_TRADE
with a reason code and not a crash.

Formulas. One-way mode, a flat symbol, one limit entry:

    initial margin = quantity x limit price / leverage       [CITED: FAQ-margin]
    fees           = notional x (fee_rate_entry + fee_rate_exit)   taker on both legs (D036)
    open loss      = BUY  max(0, (limit price - mark price) x quantity)
                     SELL max(0, (mark price - limit price) x quantity)      [ASSUMED]
    need           = initial margin + fees + open loss + margin of the other claims
    required       = need + need x headroom_bps / 10000
    pass           = free margin >= required      (equality passes)

The open-loss term covers a limit that is already marketable (it fills at once at a price worse
than the mark); a resting limit on the right side of the mark has none. It is an assumption of
the research, not an exchange-documented figure, and the headroom covers the difference. The
initial-margin shape is the FAQ formula; the owner-run Demo case records the exchange's own
figure. Exact Decimal arithmetic with the default context; no rounding mode is chosen, because
the headroom covers any exchange rounding.

Every number is an input. The leverage, the fee rates and the headroom are keyword-only
parameters with no default and no constant here: the leverage is the one the caller verified on
the exchange, the rates are the verified taker rates the manager already holds, and the headroom
is the owner's number in basis points of the margin needed (D-13, O-3, amendment A4). The only
numeric literals of this module are 0, 1 and the basis-point denominator 10000.

Fail closed. A claim with an unknown margin makes the sum unknown and the verdict NO_TRADE
`UNCERTAIN_ACCOUNT_STATE`; a shortfall is NO_TRADE `INSUFFICIENT_MARGIN` (the existing enum
value, amendment A3: `RejectionReason` is not touched). Anything that is not a finite Decimal,
or a leverage or headroom that is not a plain positive int, raises.

Two open facts live behind named seams so the owner-run Demo case changes one line (amendment
A1): the basis of the free margin is `free_margin_basis` alone, and whether `availableBalance`
already nets the margin of resting orders is `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED`
alone.

Purity (Phase 5 D-05): stdlib, Decimal, `src.domain.enums` and `src.risk.reservations` only; no
clock, no SDK, no adapters, no store, no floats, no quote-asset name. Sizing and quantization are
untouched (RISK-01): this module judges the notional of the already-sized quantity at the
already-snapped limit price.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from src.domain.enums import Direction, RejectionReason

_OK = "OK"
_REASON_CODES = frozenset({r.value for r in RejectionReason})
_INSUFFICIENT = RejectionReason.INSUFFICIENT_MARGIN.value
_UNCERTAIN = RejectionReason.UNCERTAIN_ACCOUNT_STATE.value
_SIDES = frozenset({d.value for d in Direction})

# The headroom is basis points of the margin needed.
BASIS_POINT_DENOMINATOR: Final[int] = 10000


def _require_amount(value: object, field_name: str) -> Decimal:
    """Reject non-Decimal (float, int, bool, str) and non-finite amounts."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite, got {value}")
    return value


def _require_positive(value: object, field_name: str) -> Decimal:
    amount = _require_amount(value, field_name)
    if amount <= 0:
        raise ValueError(f"{field_name} must be positive, got {amount}")
    return amount


def _require_non_negative(value: object, field_name: str) -> Decimal:
    amount = _require_amount(value, field_name)
    if amount < 0:
        raise ValueError(f"{field_name} must not be negative, got {amount}")
    return amount


def _require_positive_int(value: object, field_name: str) -> int:
    """A plain int of at least 1: bool, Decimal, float and str are refused."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be int, got {type(value).__name__}")
    if value < 1:
        raise ValueError(f"{field_name} must be at least 1, got {value}")
    return value


def _require_side(value: object) -> str:
    text = value.value if isinstance(value, Direction) else value
    if not isinstance(text, str) or text not in _SIDES:
        raise ValueError(f"side must be LONG or SHORT, got {value!r}")
    return text


def required_initial_margin(*, quantity: Decimal, price: Decimal, leverage: int) -> Decimal:
    """Initial margin of one order: quantity x price / leverage [CITED: FAQ-margin].

    `leverage` is the caller's verified leverage; it has no default and no constant here.
    """
    qty = _require_positive(quantity, "quantity")
    px = _require_positive(price, "price")
    lev = _require_positive_int(leverage, "leverage")
    return qty * px / Decimal(lev)


def estimated_fees(
    *,
    quantity: Decimal,
    price: Decimal,
    fee_rate_entry: Decimal,
    fee_rate_exit: Decimal,
) -> Decimal:
    """Round-trip fees: notional x (fee_rate_entry + fee_rate_exit), taker on both (D036)."""
    qty = _require_positive(quantity, "quantity")
    px = _require_positive(price, "price")
    entry = _require_non_negative(fee_rate_entry, "fee_rate_entry")
    exit_ = _require_non_negative(fee_rate_exit, "fee_rate_exit")
    return qty * px * (entry + exit_)


def estimated_open_loss(
    *,
    quantity: Decimal,
    limit_price: Decimal,
    mark_price: Decimal,
    side: Direction | str,
) -> Decimal:
    """Loss a limit that is already marketable takes at the fill [ASSUMED]; 0 when it rests.

    A BUY limit above the mark, or a SELL limit below it, fills at once at a price worse than
    the mark; the difference times the quantity is an unrealized loss that eats free margin.
    """
    qty = _require_positive(quantity, "quantity")
    limit = _require_positive(limit_price, "limit_price")
    mark = _require_positive(mark_price, "mark_price")
    position_side = _require_side(side)
    gap = limit - mark if position_side == Direction.LONG.value else mark - limit
    if gap <= 0:
        return Decimal(0)
    return gap * qty


@dataclass(frozen=True)
class MarginVerdict:
    """Outcome of the margin check: `ok` with reason `OK`, or a NO_TRADE `RejectionReason`.

    `required` is the need plus its headroom; it is None only when the verdict is
    `UNCERTAIN_ACCOUNT_STATE` because a claim's margin is unknown. `available` is the free
    margin the caller judged (it may be negative).
    """

    ok: bool
    reason_code: str
    required: Decimal | None
    available: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.ok, bool):
            raise TypeError(f"ok must be bool, got {type(self.ok).__name__}")
        if self.ok:
            if self.reason_code != _OK:
                raise ValueError(f"an ok verdict requires reason_code OK, got {self.reason_code!r}")
        elif self.reason_code == _OK or self.reason_code not in _REASON_CODES:
            raise ValueError(
                f"a refusal needs a non-OK RejectionReason code, got {self.reason_code!r}"
            )
        if self.required is not None:
            _require_amount(self.required, "required")
        elif self.ok:
            raise ValueError("an ok verdict requires the required margin")
        _require_amount(self.available, "available")


def margin_verdict(
    *,
    available_balance: Decimal,
    quantity: Decimal,
    limit_price: Decimal,
    mark_price: Decimal,
    side: Direction | str,
    leverage: int,
    fee_rate_entry: Decimal,
    fee_rate_exit: Decimal,
    others_margin: Decimal | None,
    headroom_bps: int,
) -> MarginVerdict:
    """Pass only when the free margin covers the order, its costs, the other claims and headroom.

    `available_balance` is the free margin already passed through `free_margin_basis`.
    `others_margin` is the Decimal summed by `other_claims_margin`, or None when a claim's
    margin is unknown (then the verdict is NO_TRADE `UNCERTAIN_ACCOUNT_STATE`). `headroom_bps`
    is the owner's number: basis points of the margin needed, a positive int.
    """
    available = _require_amount(available_balance, "available_balance")
    margin = required_initial_margin(quantity=quantity, price=limit_price, leverage=leverage)
    fees = estimated_fees(
        quantity=quantity,
        price=limit_price,
        fee_rate_entry=fee_rate_entry,
        fee_rate_exit=fee_rate_exit,
    )
    open_loss = estimated_open_loss(
        quantity=quantity, limit_price=limit_price, mark_price=mark_price, side=side
    )
    bps = _require_positive_int(headroom_bps, "headroom_bps")
    if others_margin is None:
        return MarginVerdict(ok=False, reason_code=_UNCERTAIN, required=None, available=available)
    others = _require_non_negative(others_margin, "others_margin")
    need = margin + fees + open_loss + others
    required = need + need * Decimal(bps) / Decimal(BASIS_POINT_DENOMINATOR)
    if available >= required:
        return MarginVerdict(ok=True, reason_code=_OK, required=required, available=available)
    return MarginVerdict(
        ok=False, reason_code=_INSUFFICIENT, required=required, available=available
    )
