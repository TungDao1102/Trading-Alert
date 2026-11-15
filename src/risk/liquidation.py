"""Pure isolated liquidation guard (Phase 22, plan 22-07; D-08, D-09, D-10, criterion 2, F-964).

Question answered: where would the liquidation price of an isolated, one-way position that does
not exist yet be, and does it lie beyond the stop-loss by the buffer? The answer is a
`LiquidationVerdict`, never an exception, so a refused plan is a NO_TRADE with a plain code and
not a crash. The pre-entry guard, the post-fill watch and the tests all call this one module.

Formulas. Symbol `Q` (quantity), `EP` (entry price), `L` (the verified leverage), `f` (the entry
fee rate, a caller input), `m` and `cum` (maintenance margin ratio and maintenance amount of one
leverage bracket). The isolated wallet is `WB = Q x EP / L - f x Q x EP`, and `w = WB / (Q x EP)
= 1/L - f`:

    LONG   LP = (EP x (1 - w) - cum/Q) / (1 - m)
    SHORT  LP = (EP x (1 + w) + cum/Q) / (1 + m)

With `f = 0` these are the formulas of plan 22-07 as first written (`w = 1/L`).

Source label. The variables, the isolated rule (TMM = UPNL = 0, the wallet is the isolated
wallet) and the tier-change rule are [CITED: FAQ-liq]. The general formula is an image on that
page, so the closed form above is a reconstruction from the stated liquidation condition (margin
balance equals maintenance margin); it reproduces both worked examples of the page to the cent
(22-RESEARCH 2.5, MEDIUM confidence).

Demo observation (amendment 2026-10-24). The owner-run Demo case
`isolated_position_liquidation_price` (evidence file `demo-probe-EVIDENCE-20261024T043134Z.json`,
Demo-observed, NOT mainnet) recorded, for a BTC perpetual LONG with entry 80845.8, quantity 0.0014,
leverage 5 and tier 1 (m 0.004, cum 0), a `liquidationPrice` of 64968.85373637 and an
`isolatedWallet` of 22.59155035. That wallet is the initial margin 22.636824 minus the entry fee
(0.0004 x Q x EP = 0.04527365), so the entry fee DOES reduce the isolated wallet on Demo. With the
fee the closed form gives 64968.853735 (about 1.4e-6 away: the exchange rounds the wallet to eight
decimals); without it 64936.3855, about 32 on the non-conservative side for a long (for a short the
omitted fee likewise moves the price toward the entry). The fee rate is therefore a REQUIRED input
(`entry_fee_rate`, 0 allowed): the Demo taker rate was observed, no rate is a constant here. One
Demo record at one tier is not a proof for every tier or for mainnet.

Tier rule. `m` and `cum` are those of the bracket that contains `Q x LP`, the notional at the
liquidation price, NOT of the bracket that contains `Q x EP`. The page says the rate and amount
must be taken "on the level of position notional" and that another level applies when the notional
implied at the liquidation price lies in it. For a long near a bracket edge the entry tier
overstates the liquidation price toward the entry, which is the non-conservative direction
(22-RESEARCH Pitfall 1, golden G3). Every candidate bracket is solved and kept only when its own
`Q x LP` falls inside its own [floor, cap] (inclusive). At an exact edge two candidates coincide
when `notional x rate - cum` is continuous there (true of every recorded edge, a property of the
Demo table and not a rule of this module); if a table were not continuous the conservative one is
returned, the larger LP for a LONG and the smaller for a SHORT.

Entry-price assumption. The position is taken to fill at `EP` (the limit price is the worst case
in both directions), the isolated wallet is the initial margin `Q x EP / L` less the entry fee
`f x Q x EP` (Demo-observed, see above), no funding is paid and no exit fee is reserved. The
funding and exit-fee parts are [ASSUMED]; the page is silent. They are therefore not in the number:
the buffer and the post-fill comparison with the exchange value are the real margin of error. A
wallet of zero or less (a fee rate of at least `1/L`) is NO_TRADE (LIQUIDATION_INPUT_UNAVAILABLE).

Buffer predicate (D-09, D-10). `buffer = EP x buffer_bps / 10000`. LONG passes only when
`LP < stop - buffer`; SHORT only when `LP > stop + buffer`. Strict: equality fails. `buffer_bps`
is the owner's number and has no default.

Exact arithmetic. Every tier test and every comparison uses `fractions.Fraction` built from the
Decimal inputs, so a notional that lands exactly on a bracket edge selects a tier without rounding
error. The Decimal returned is the exact value divided at the active context precision; no
decision depends on that rounding.

Every number is an input. The leverage, the buffer, the entry fee rate and every bracket value are
arguments with no default and no constant here; the only numeric literals of this module are 0, 1
and the basis-point denominator 10000.

Fail closed. A bracket list that is empty, not contiguous, malformed or stale, a notional above
the top bracket cap, a leverage above the initial leverage of the entry bracket, a non-positive
liquidation price or inverted stop geometry is NO_TRADE with its own plain code and never a pass.
Anything that is not a finite Decimal (a fee rate must also be non-negative), or a leverage or
buffer that is not a plain positive int, raises (a programming error). The four codes are plain
strings of this module (amendment A3: the `RejectionReason` enum is not touched); GLOSSARY 9.3
lists them.

Purity (Phase 5 D-05): stdlib, Decimal, Fraction and `src.domain.enums` only; no clock, no SDK, no
adapters, no store, no floats, no quote-asset name.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Final

from src.domain.enums import Direction

LIQUIDATION_OK: Final[str] = "OK"
LIQUIDATION_TOO_CLOSE: Final[str] = "LIQUIDATION_TOO_CLOSE"
LIQUIDATION_INPUT_UNAVAILABLE: Final[str] = "LIQUIDATION_INPUT_UNAVAILABLE"
LEVERAGE_ABOVE_BRACKET: Final[str] = "LEVERAGE_ABOVE_BRACKET"
NOTIONAL_ABOVE_MAX: Final[str] = "NOTIONAL_ABOVE_MAX"

# The buffer is basis points of the entry price.
BASIS_POINT_DENOMINATOR: Final[int] = 10000

_LONG = Direction.LONG.value
_SIDES = frozenset({d.value for d in Direction})


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


def _require_utc_aware(value: object, field_name: str) -> datetime:
    """Reject non-datetime, naive and non-UTC values."""
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")
    return value


def _require_side(value: object) -> str:
    text = value.value if isinstance(value, Direction) else value
    if not isinstance(text, str) or text not in _SIDES:
        raise ValueError(f"side must be LONG or SHORT, got {value!r}")
    return text


@dataclass(frozen=True)
class Bracket:
    """One leverage bracket as the exchange reports it (every field is an input, never a constant).

    `notional_floor` and `notional_cap` bound the position notional of the bracket,
    `maint_margin_ratio` is its maintenance margin ratio `m`, `cum` its maintenance amount.
    """

    bracket: int
    initial_leverage: int
    notional_floor: Decimal
    notional_cap: Decimal
    maint_margin_ratio: Decimal
    cum: Decimal

    def __post_init__(self) -> None:
        _require_positive_int(self.bracket, "bracket")
        _require_positive_int(self.initial_leverage, "initial_leverage")
        floor = _require_non_negative(self.notional_floor, "notional_floor")
        cap = _require_amount(self.notional_cap, "notional_cap")
        if cap <= floor:
            raise ValueError(f"notional_cap {cap} must exceed notional_floor {floor}")
        ratio = _require_non_negative(self.maint_margin_ratio, "maint_margin_ratio")
        if ratio >= 1:
            raise ValueError(f"maint_margin_ratio must be below 1, got {ratio}")
        _require_non_negative(self.cum, "cum")


@dataclass(frozen=True)
class LiquidationVerdict:
    """Result of the guard. `liquidation_price` is informational (decisions use exact values)."""

    ok: bool
    reason_code: str
    liquidation_price: Decimal | None

    def __post_init__(self) -> None:
        if not isinstance(self.ok, bool):
            raise TypeError(f"ok must be bool, got {type(self.ok).__name__}")
        if not isinstance(self.reason_code, str) or not self.reason_code:
            raise ValueError("reason_code must be a non-empty string")
        if self.ok != (self.reason_code == LIQUIDATION_OK):
            raise ValueError(f"ok={self.ok} contradicts reason_code={self.reason_code}")
        if self.liquidation_price is not None:
            _require_positive(self.liquidation_price, "liquidation_price")
        if self.ok and self.liquidation_price is None:
            raise ValueError("an ok verdict must carry the liquidation price")


def _to_decimal(value: Fraction) -> Decimal:
    """The exact value divided at the active context precision (informational only)."""
    return Decimal(value.numerator) / Decimal(value.denominator)


def _candidate(
    *, side: str, entry: Fraction, quantity: Fraction, wallet_share: Fraction, tier: Bracket
) -> Fraction:
    """The liquidation price if `tier` were the active bracket (exact).

    `wallet_share` is the isolated wallet over the entry notional, `1/L - f`.
    """
    ratio = Fraction(tier.maint_margin_ratio)
    cum = Fraction(tier.cum)
    if side == _LONG:
        return (entry * (1 - wallet_share) - cum / quantity) / (1 - ratio)
    return (entry * (1 + wallet_share) + cum / quantity) / (1 + ratio)


def _shape_is_usable(brackets: Sequence[Bracket]) -> bool:
    """True when the list is non-empty, sorted by bracket number and contiguous from zero.

    Contiguous means the first floor is zero and every floor equals the previous cap. A list that
    fails this (empty, unsorted, duplicate number, gap or overlap) is bracket data the guard must
    not use. A non-`Bracket` element is a programming error.
    """
    if not brackets:
        return False
    for item in brackets:
        if not isinstance(item, Bracket):
            raise TypeError(f"brackets must hold Bracket objects, got {type(item).__name__}")
    if brackets[0].notional_floor != 0:
        return False
    for previous, current in zip(brackets, brackets[1:], strict=False):
        if current.bracket <= previous.bracket:
            return False
        if current.notional_floor != previous.notional_cap:
            return False
    return True


def _solve(
    *,
    side: str,
    entry_price: Decimal,
    quantity: Decimal,
    leverage: int,
    brackets: Sequence[Bracket],
    entry_fee_rate: Decimal,
) -> tuple[str, Fraction | None]:
    """The reason code and the exact liquidation price (None unless the reason is OK)."""
    if not _shape_is_usable(brackets):
        return LIQUIDATION_INPUT_UNAVAILABLE, None
    entry = Fraction(entry_price)
    qty = Fraction(quantity)
    entry_notional = entry * qty
    if entry_notional > Fraction(brackets[-1].notional_cap):
        return NOTIONAL_ABOVE_MAX, None
    # The bracket(s) containing the entry notional (two at an exact edge: the smaller maximum
    # leverage binds, fail closed).
    allowed = min(
        t.initial_leverage
        for t in brackets
        if Fraction(t.notional_floor) <= entry_notional <= Fraction(t.notional_cap)
    )
    if leverage > allowed:
        return LEVERAGE_ABOVE_BRACKET, None
    # Isolated wallet over the entry notional: (Q x EP / L - f x Q x EP) / (Q x EP) = 1/L - f.
    wallet_share = Fraction(1, leverage) - Fraction(entry_fee_rate)
    if wallet_share <= 0:
        return LIQUIDATION_INPUT_UNAVAILABLE, None
    candidates = [
        (
            t,
            _candidate(side=side, entry=entry, quantity=qty, wallet_share=wallet_share, tier=t),
        )
        for t in brackets
    ]
    consistent = [
        lp
        for t, lp in candidates
        if Fraction(t.notional_floor) <= qty * lp <= Fraction(t.notional_cap)
    ]
    if not consistent:
        if all(lp <= 0 for _, lp in candidates):
            return LIQUIDATION_INPUT_UNAVAILABLE, None
        return NOTIONAL_ABOVE_MAX, None
    best = max(consistent) if side == _LONG else min(consistent)
    if best <= 0:
        return LIQUIDATION_INPUT_UNAVAILABLE, None
    return LIQUIDATION_OK, best


def liquidation_price(
    *,
    side: object,
    entry_price: Decimal,
    quantity: Decimal,
    leverage: int,
    brackets: Sequence[Bracket],
    entry_fee_rate: Decimal,
) -> Decimal | None:
    """Isolated, one-way liquidation price; None = unknown (fail closed).

    The entry fee `entry_fee_rate x Q x EP` reduces the isolated wallet (Demo-observed); no funding.
    CITED: FAQ-liq for the variables; the closed form is a reconstruction. The rate is the caller's.
    """
    side_text = _require_side(side)
    _require_positive(entry_price, "entry_price")
    _require_positive(quantity, "quantity")
    _require_positive_int(leverage, "leverage")
    _require_non_negative(entry_fee_rate, "entry_fee_rate")
    reason, exact = _solve(
        side=side_text,
        entry_price=entry_price,
        quantity=quantity,
        leverage=leverage,
        brackets=brackets,
        entry_fee_rate=entry_fee_rate,
    )
    if reason != LIQUIDATION_OK or exact is None:
        return None
    return _to_decimal(exact)


def _beyond_stop(
    *,
    side: str,
    liquidation: Fraction,
    stop_price: Decimal,
    entry_price: Decimal,
    buffer_bps: int,
) -> bool:
    buffer = Fraction(entry_price) * buffer_bps / BASIS_POINT_DENOMINATOR
    stop = Fraction(stop_price)
    if side == _LONG:
        return liquidation < stop - buffer
    return liquidation > stop + buffer


def liquidation_beyond_stop(
    *,
    side: object,
    liquidation_price: Decimal,
    stop_price: Decimal,
    entry_price: Decimal,
    buffer_bps: int,
) -> bool:
    """Strict buffer predicate (D-09): LONG `LP < stop - buffer`, SHORT `LP > stop + buffer`.

    `buffer = entry_price x buffer_bps / 10000`; equality is False.
    """
    side_text = _require_side(side)
    _require_positive(liquidation_price, "liquidation_price")
    _require_positive(stop_price, "stop_price")
    _require_positive(entry_price, "entry_price")
    _require_positive_int(buffer_bps, "buffer_bps")
    return _beyond_stop(
        side=side_text,
        liquidation=Fraction(liquidation_price),
        stop_price=stop_price,
        entry_price=entry_price,
        buffer_bps=buffer_bps,
    )


def liquidation_verdict(
    *,
    side: object,
    entry_price: Decimal,
    quantity: Decimal,
    leverage: int,
    brackets: Sequence[Bracket],
    stop_price: Decimal,
    buffer_bps: int,
    entry_fee_rate: Decimal,
) -> LiquidationVerdict:
    """Compose the price and the buffer predicate into one fail-closed verdict."""
    side_text = _require_side(side)
    entry = _require_positive(entry_price, "entry_price")
    _require_positive(quantity, "quantity")
    _require_positive_int(leverage, "leverage")
    stop = _require_positive(stop_price, "stop_price")
    _require_positive_int(buffer_bps, "buffer_bps")
    _require_non_negative(entry_fee_rate, "entry_fee_rate")
    inverted = stop >= entry if side_text == _LONG else stop <= entry
    if inverted:
        return LiquidationVerdict(False, LIQUIDATION_INPUT_UNAVAILABLE, None)
    reason, exact = _solve(
        side=side_text,
        entry_price=entry_price,
        quantity=quantity,
        leverage=leverage,
        brackets=brackets,
        entry_fee_rate=entry_fee_rate,
    )
    if reason != LIQUIDATION_OK or exact is None:
        return LiquidationVerdict(False, reason, None)
    if not _beyond_stop(
        side=side_text,
        liquidation=exact,
        stop_price=stop,
        entry_price=entry,
        buffer_bps=buffer_bps,
    ):
        return LiquidationVerdict(False, LIQUIDATION_TOO_CLOSE, _to_decimal(exact))
    return LiquidationVerdict(True, LIQUIDATION_OK, _to_decimal(exact))


def brackets_are_fresh(*, observed_at_utc: datetime, now_utc: datetime, max_age: timedelta) -> bool:
    """The project's stale rule for the bracket table (D-11).

    Age greater than `max_age`, or negative (an observation from the future), is stale; an age
    exactly equal to `max_age` passes. The caller supplies both instants and the limit: this module
    reads no clock.

    Raises:
        TypeError: an instant is not a datetime, or `max_age` is not a timedelta.
        ValueError: an instant is naive or non-UTC, or `max_age` is not positive.
    """
    observed = _require_utc_aware(observed_at_utc, "observed_at_utc")
    now = _require_utc_aware(now_utc, "now_utc")
    if not isinstance(max_age, timedelta):
        raise TypeError(f"max_age must be timedelta, got {type(max_age).__name__}")
    if max_age <= timedelta(0):
        raise ValueError(f"max_age must be positive, got {max_age}")
    age = now - observed
    return timedelta(0) <= age <= max_age
