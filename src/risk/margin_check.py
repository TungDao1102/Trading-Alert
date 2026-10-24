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

The reading (plan 22-10). `check_available_margin` is the one pure judgement of the fresh
account reading for the margin guard. The reading carries, under the equity's single stamp, the
exchange's `availableBalance`, the open-order margin total, the quote-asset row's
`availableBalance` and the account's position and margin mode (all from the answers the equity
read already makes; no extra call). The order of the refusals is fixed and tested:

    1. unusable: no reading, a reading older than `max_age` or future-dated (the mode flags of a
       stale reading are not trusted, so staleness is reported before the mode);
    2. hedge mode (`dual_side_position`): the guard must neither size nor mutate a hedge account;
    3. multi-assets mode: the margin would mix assets;
    4. unusable: an equity identity of `check_equity_reading` fails (unchanged Phase 21 rules),
       the quote-asset row's `availableBalance` is missing, or it differs from the top-level
       `availableBalance` (exact equality, no tolerance).

The two mode refusals come BEFORE the equity identities and are reported with their own
`blocked` value, so the guard can give a plain reason before it mutates anything (criterion 4).
Every non-OK outcome has `reason_code` `UNCERTAIN_ACCOUNT_STATE` (the existing enum value,
amendment A3) and a `blocked` value: the three `BLOCKED_*` constants are plain strings, not
`RejectionReason` members. Otherwise the available margin is `free_margin_basis(...)` and the
equity is the equity of `check_equity_reading` (never `availableBalance`).

Purity (Phase 5 D-05): stdlib, Decimal, `src.domain.enums`, `src.risk.reservations` and
`src.risk.live_equity` only; no clock, no SDK, no adapters, no store, no floats, no quote-asset
name. Sizing and quantization are
untouched (RISK-01): this module judges the notional of the already-sized quantity at the
already-snapped limit price.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from src.domain.enums import Direction, RejectionReason
from src.risk.live_equity import AccountEquityReading, check_equity_reading
from src.risk.reservations import ReservationStatus

_OK = "OK"
_REASON_CODES = frozenset({r.value for r in RejectionReason})
_INSUFFICIENT = RejectionReason.INSUFFICIENT_MARGIN.value
_UNCERTAIN = RejectionReason.UNCERTAIN_ACCOUNT_STATE.value
_SIDES = frozenset({d.value for d in Direction})
_CLAIM_STATUSES = frozenset({ReservationStatus.RESERVED, ReservationStatus.PLACED})

# The headroom is basis points of the margin needed.
BASIS_POINT_DENOMINATOR: Final[int] = 10000

# Why `check_available_margin` refused (plain strings; the guard maps them to its own codes).
BLOCKED_READING_UNUSABLE: Final[str] = "READING_UNUSABLE"
BLOCKED_HEDGE_MODE: Final[str] = "HEDGE_MODE"
BLOCKED_MULTI_ASSETS_MODE: Final[str] = "MULTI_ASSETS_MODE"
_BLOCKED_VALUES = frozenset(
    {BLOCKED_READING_UNUSABLE, BLOCKED_HEDGE_MODE, BLOCKED_MULTI_ASSETS_MODE}
)


def _require_utc_aware(value: object, field_name: str) -> None:
    """Reject non-datetime, naive and non-UTC values."""
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")


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


# --- claims on margin and the two seams ---------------------------------------------------------

# Amendment A1. The API reference does not say whether `availableBalance` already nets the
# initial margin of resting orders; the support-center article says it does. The owner-run Demo
# case `available_balance_with_resting_order` (plan 22-09, 22-DEMO-RESULTS.md R-4 and R-5, two
# samples, CROSSED and ISOLATED, demo-observed, not mainnet) showed it does, and the owner flipped
# this to True on 2026-10-24 (DECISIONS D085, O-3). With True a PLACED claim whose `placed_at_utc`
# is at or before the reading is not counted again (the exchange already nets it); a PLACED claim
# placed AFTER the reading still counts, and a RESERVED claim always counts. A mainnet sample at the
# Phase 26 canary re-checks it; a wrong True can only let the exchange reject with -2019 at
# placement. It changes only with an owner DECISIONS row, never by a code edit alone.
AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED: Final[bool] = True


def free_margin_basis(
    *,
    available_balance: Decimal,
    total_open_order_initial_margin: Decimal,
) -> Decimal:
    """The free margin the check judges: ONE function, so the owner-run case changes one line.

    Today it is `availableBalance` as the exchange reports it (the documented seam: if the
    owner-run case shows that `availableBalance` does not net the margin of resting orders,
    this becomes `available_balance - total_open_order_initial_margin`). Both arguments must be
    finite Decimals; the result is returned as is, even when negative.
    """
    available = _require_amount(available_balance, "available_balance")
    _require_amount(total_open_order_initial_margin, "total_open_order_initial_margin")
    return available


@dataclass(frozen=True)
class MarginClaim:
    """One stored claim on margin: a RESERVED or PLACED reservation row of another plan.

    `required_margin` is the initial margin the plan was judged to need, None when unknown (the
    sum is then unknown and the verdict fails closed). `placed_at_utc` is when the entry was sent;
    a PLACED claim requires it, a RESERVED claim may carry None.
    """

    trade_plan_id: str
    status: ReservationStatus
    required_margin: Decimal | None
    placed_at_utc: datetime | None

    def __post_init__(self) -> None:
        if not isinstance(self.trade_plan_id, str) or not self.trade_plan_id:
            raise ValueError("trade_plan_id must be a non-empty string")
        if self.status not in _CLAIM_STATUSES:
            raise ValueError(f"a margin claim is RESERVED or PLACED, got {self.status!r}")
        if self.required_margin is not None:
            _require_positive(self.required_margin, "required_margin")
        if self.status is ReservationStatus.PLACED:
            if self.placed_at_utc is None:
                raise ValueError("a PLACED claim requires placed_at_utc")
            _require_utc_aware(self.placed_at_utc, "placed_at_utc")
        elif self.placed_at_utc is not None:
            _require_utc_aware(self.placed_at_utc, "placed_at_utc")


def other_claims_margin(
    *,
    claims: Sequence[MarginClaim],
    exclude_trade_plan_id: str,
    reading_observed_at_utc: datetime,
    resting_orders_netted: bool,
) -> Decimal | None:
    """Sum of the margin of every other claim, or None when a counted claim's margin is unknown.

    A RESERVED claim always counts. A PLACED claim counts unless the exchange already nets it:
    with `resting_orders_netted` False it always counts; with True it counts only when
    `placed_at_utc` is strictly after `reading_observed_at_utc` (the reading cannot show it
    yet). The candidate's own row (`exclude_trade_plan_id`) is never counted, whatever its
    status. A RELEASED or OPEN row is never a claim (an OPEN position is in `availableBalance`
    as position margin).

    Pitfall 5: a PLACED entry must be subtracted in exactly one place, by the exchange inside
    `availableBalance` or by this sum. Counting it in both over-refuses, in neither over-admits.
    With the netting flag False (the state before D085) the sum counts it, which can only
    over-refuse.
    """
    _require_utc_aware(reading_observed_at_utc, "reading_observed_at_utc")
    if not isinstance(resting_orders_netted, bool):
        raise TypeError(
            f"resting_orders_netted must be bool, got {type(resting_orders_netted).__name__}"
        )
    total = Decimal(0)
    for claim in claims:
        if claim.trade_plan_id == exclude_trade_plan_id:
            continue
        if claim.status is ReservationStatus.PLACED and resting_orders_netted:
            placed_at = claim.placed_at_utc
            if placed_at is None or placed_at <= reading_observed_at_utc:
                continue
        if claim.required_margin is None:
            return None
        total += claim.required_margin
    return total


@dataclass(frozen=True)
class AvailableMarginCheck:
    """The judged free margin of one reading, or the plain reason it cannot be trusted.

    OK: `available`, `equity` and `observed_at_utc` are set, `reason_code` is `OK` and `blocked`
    is None. Otherwise all three figures are None, `reason_code` is `UNCERTAIN_ACCOUNT_STATE` and
    `blocked` is one of the three `BLOCKED_*` constants.
    """

    available: Decimal | None
    equity: Decimal | None
    observed_at_utc: datetime | None
    reason_code: str
    blocked: str | None

    def __post_init__(self) -> None:
        if self.reason_code not in _REASON_CODES and self.reason_code != _OK:
            raise ValueError(f"unknown reason_code {self.reason_code!r}")
        if self.available is not None:
            _require_amount(self.available, "available")
        if self.equity is not None:
            _require_amount(self.equity, "equity")
        if self.observed_at_utc is not None:
            _require_utc_aware(self.observed_at_utc, "observed_at_utc")
        usable = (
            self.available is not None
            and self.equity is not None
            and self.observed_at_utc is not None
        )
        if self.reason_code == _OK:
            if not usable or self.blocked is not None:
                raise ValueError("an OK check needs its figures and no blocked value")
            return
        if self.reason_code != _UNCERTAIN:
            raise ValueError("a refused check carries UNCERTAIN_ACCOUNT_STATE")
        if (
            self.available is not None
            or self.equity is not None
            or self.observed_at_utc is not None
        ):
            raise ValueError("a refused check carries no figures")
        if self.blocked not in _BLOCKED_VALUES:
            raise ValueError("a refused check needs a known blocked value")


def _refused(blocked: str) -> AvailableMarginCheck:
    return AvailableMarginCheck(
        available=None,
        equity=None,
        observed_at_utc=None,
        reason_code=_UNCERTAIN,
        blocked=blocked,
    )


def check_available_margin(
    *,
    reading: AccountEquityReading | None,
    now_utc: datetime,
    max_age: timedelta,
) -> AvailableMarginCheck:
    """Judge the one fresh account reading for the margin guard (D-07, D-13, criterion 4).

    The order is unusable (no reading, older than `max_age`, future-dated), hedge mode,
    multi-assets mode, then the equity identities and the `availableBalance` cross-check (see the
    module docstring). An age equal to `max_age` passes.

    Raises:
        ValueError: `now_utc` is naive or non-UTC, or `max_age` is not positive (programming
            errors, not market states).
    """
    _require_utc_aware(now_utc, "now_utc")
    if max_age <= timedelta(0):
        raise ValueError(f"max_age must be positive, got {max_age}")
    if reading is None:
        return _refused(BLOCKED_READING_UNUSABLE)
    age = now_utc - reading.observed_at_utc
    if age > max_age or age < timedelta(0):
        return _refused(BLOCKED_READING_UNUSABLE)
    if reading.dual_side_position:
        return _refused(BLOCKED_HEDGE_MODE)
    if reading.multi_assets_margin:
        return _refused(BLOCKED_MULTI_ASSETS_MODE)
    equity_check = check_equity_reading(reading=reading, now_utc=now_utc, max_age=max_age)
    if equity_check.equity is None or equity_check.observed_at_utc is None:
        return _refused(BLOCKED_READING_UNUSABLE)
    quote_available = reading.quote_asset_available_balance
    if quote_available is None or quote_available != reading.available_balance:
        return _refused(BLOCKED_READING_UNUSABLE)
    available = free_margin_basis(
        available_balance=reading.available_balance,
        total_open_order_initial_margin=reading.total_open_order_initial_margin,
    )
    return AvailableMarginCheck(
        available=available,
        equity=equity_check.equity,
        observed_at_utc=equity_check.observed_at_utc,
        reason_code=_OK,
        blocked=None,
    )
