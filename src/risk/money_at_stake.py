"""Money at stake: one frozen value built once from the risk pipeline output (Phase 23, D-13).

The operator decides on amounts: notional, initial margin, the loss at the stop-loss (gross and
net of the modeled costs), the profit at each take-profit (gross and net), and the equity those
amounts are measured against. Those numbers are produced HERE, once, at plan-issue time, from
one `SizedResult` plus the plan's stop and take-profits, the cost rates, the verified leverage
and the equity reading. The result is stored with the pending approval (`approvals.money_json`)
and only FORMATTED by the Telegram code; the message layer never recomputes a figure (F-015).

Contract:

* The net loss at the stop is `SizedResult.realized_risk` itself (read, not recomputed); the
  gross loss is `quantity x |entry - stop|`. Margin is `required_initial_margin` and a cost is
  `per_unit_round_trip_cost` (one definition each). A division result is truncated toward zero
  at 18 fractional digits, never rounded up.
* Any missing input raises `MoneyAtStakeUnavailable` (reason `MONEY_AT_STAKE_MISSING`, the
  missing field named): nothing partial is ever built, so nothing can render or be sent.
* The stored form is `money_canonical_json` / `parse_money_json`: sorted keys, compact, every
  Decimal as fixed-point text, the time as ISO UTC text, no float anywhere. A change of the
  shape is a new `MONEY_SCHEMA_TAG`, never a silent reinterpretation.
* No leverage, equity, fee or slippage value is a constant here; only the source labels and the
  quote-asset name are (Phase 27 makes the asset configurable).

Purity: stdlib, Decimal, `src.domain.enums` and the sibling risk modules only. No clock, no
float, no import of the execution, paper or adapter layers.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal, InvalidOperation, localcontext
from typing import Any, Final

from src.domain.enums import Direction
from src.risk.cost_rates import CostRates, per_unit_round_trip_cost
from src.risk.margin_check import required_initial_margin
from src.risk.types import SizedResult

#: The settlement asset of the USD-M futures this system trades (Phase 27 makes it configurable).
QUOTE_ASSET_USDT: Final = "USDT"

#: Reason code of every refusal in this module.
MONEY_AT_STAKE_MISSING: Final = "MONEY_AT_STAKE_MISSING"

#: Schema tag of the stored form; a different shape needs a different tag.
MONEY_SCHEMA_TAG: Final = "money-at-stake/1"

#: Equity read from the live account (D086 basis: the smaller of wallet and margin balance).
EQUITY_SOURCE_ACCOUNT_LIVE: Final = "ACCOUNT_LIVE:min(totalWalletBalance,totalMarginBalance)"
#: Equity of the paper configuration.
EQUITY_SOURCE_PAPER_CONFIG: Final = "PAPER_CONFIG:initial_equity"
#: Leverage verified on the account and frozen in the plan constraint snapshot (Phase 22).
LEVERAGE_SOURCE_CONSTRAINT_SNAPSHOT: Final = "PLAN_CONSTRAINT_SNAPSHOT:verified_leverage"
#: Leverage of the paper configuration (its value is Phase 22 owner item O-1, never set here).
LEVERAGE_SOURCE_PAPER_CONFIG: Final = "PAPER_CONFIG:target_leverage"

EQUITY_SOURCES: Final[frozenset[str]] = frozenset(
    {EQUITY_SOURCE_ACCOUNT_LIVE, EQUITY_SOURCE_PAPER_CONFIG}
)
LEVERAGE_SOURCES: Final[frozenset[str]] = frozenset(
    {LEVERAGE_SOURCE_CONSTRAINT_SNAPSHOT, LEVERAGE_SOURCE_PAPER_CONFIG}
)

_SIDES: Final[frozenset[str]] = frozenset({"LONG", "SHORT"})
_PRECISION: Final = 38
_FRACTION_DIGITS: Final = 18
_ONE: Final = Decimal("1")
_ZERO: Final = Decimal("0")


class MoneyAtStakeUnavailable(ValueError):
    """An input the money block needs is missing or unusable; nothing was built."""

    def __init__(self, field: str, detail: str = "") -> None:
        self.reason_code = MONEY_AT_STAKE_MISSING
        self.field = field
        text = f"{MONEY_AT_STAKE_MISSING}: {field}"
        super().__init__(f"{text} ({detail})" if detail else text)


def _decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite, got {value}")
    return value


def _positive(value: object, name: str) -> Decimal:
    amount = _decimal(value, name)
    if amount <= _ZERO:
        raise ValueError(f"{name} must be above zero, got {amount}")
    return amount


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _utc(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC-aware")
    return value


def _truncate(value: Decimal) -> Decimal:
    """Truncate toward zero at 18 fractional digits, only when there are more of them."""
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -_FRACTION_DIGITS:
        with localcontext() as ctx:
            ctx.prec = _PRECISION
            ctx.rounding = ROUND_DOWN
            return value.quantize(Decimal(1).scaleb(-_FRACTION_DIGITS), rounding=ROUND_DOWN)
    return value


def _check_side_prices(side: str, entry: Decimal, stop: Decimal, tps: Sequence[Decimal]) -> None:
    """The stop is on the losing side of the entry and every take-profit on the winning side."""
    if side == "LONG":
        if stop >= entry:
            raise ValueError("a LONG stop-loss must be below the entry")
        if any(tp <= entry for tp in tps):
            raise ValueError("a LONG take-profit must be above the entry")
    else:
        if stop <= entry:
            raise ValueError("a SHORT stop-loss must be above the entry")
        if any(tp >= entry for tp in tps):
            raise ValueError("a SHORT take-profit must be below the entry")


@dataclass(frozen=True)
class TakeProfitAtStake:
    """Profit estimate of one take-profit leg (leg quantity = quantity x the plan's fraction)."""

    label: str
    price: Decimal
    fraction: Decimal
    leg_quantity: Decimal
    profit_gross: Decimal
    profit_net: Decimal

    def __post_init__(self) -> None:
        _text(self.label, "label")
        _positive(self.price, "price")
        fraction = _positive(self.fraction, "fraction")
        if fraction > _ONE:
            raise ValueError(f"fraction must be at most 1, got {fraction}")
        _positive(self.leg_quantity, "leg_quantity")
        _positive(self.profit_gross, "profit_gross")
        _decimal(self.profit_net, "profit_net")


@dataclass(frozen=True)
class MoneyAtStake:
    """Every amount the operator decides on, computed once from the risk pipeline output."""

    schema: str
    quote_asset: str
    side: str
    quantity: Decimal
    entry_price: Decimal
    stop_loss_price: Decimal
    notional: Decimal
    leverage: int
    leverage_source: str
    initial_margin: Decimal
    loss_at_stop_gross: Decimal
    loss_at_stop_net: Decimal
    take_profits: tuple[TakeProfitAtStake, ...]
    equity: Decimal
    equity_source: str
    equity_observed_at_utc: datetime

    def __post_init__(self) -> None:
        if self.schema != MONEY_SCHEMA_TAG:
            raise ValueError(f"schema must be {MONEY_SCHEMA_TAG!r}, got {self.schema!r}")
        asset = _text(self.quote_asset, "quote_asset")
        if not (asset.isascii() and asset.isalnum() and asset == asset.upper()):
            raise ValueError("quote_asset must be an upper-case ASCII name")
        if self.side not in _SIDES:
            raise ValueError(f"side must be LONG or SHORT, got {self.side!r}")
        for name in (
            "quantity",
            "entry_price",
            "stop_loss_price",
            "notional",
            "initial_margin",
            "loss_at_stop_gross",
            "loss_at_stop_net",
            "equity",
        ):
            _positive(getattr(self, name), name)
        if self.loss_at_stop_net < self.loss_at_stop_gross:
            raise ValueError("loss_at_stop_net must not be below loss_at_stop_gross")
        if isinstance(self.leverage, bool) or not isinstance(self.leverage, int):
            raise TypeError(f"leverage must be int, got {type(self.leverage).__name__}")
        if self.leverage < 1:
            raise ValueError(f"leverage must be at least 1, got {self.leverage}")
        if self.leverage_source not in LEVERAGE_SOURCES:
            raise ValueError(f"unknown leverage_source {self.leverage_source!r}")
        if self.equity_source not in EQUITY_SOURCES:
            raise ValueError(f"unknown equity_source {self.equity_source!r}")
        _utc(self.equity_observed_at_utc, "equity_observed_at_utc")
        if not isinstance(self.take_profits, tuple) or not self.take_profits:
            raise ValueError("take_profits must be a non-empty tuple")
        for leg in self.take_profits:
            if not isinstance(leg, TakeProfitAtStake):
                raise TypeError(f"take_profits holds {type(leg).__name__}")
        if sum((leg.fraction for leg in self.take_profits), _ZERO) != _ONE:
            raise ValueError("take-profit fractions must sum to 1")
        _check_side_prices(
            self.side,
            self.entry_price,
            self.stop_loss_price,
            [leg.price for leg in self.take_profits],
        )
        # Review WR-04: the amounts agree with each other, so a stored block cannot show a
        # notional or leg quantities that the quantity and entry price do not produce. Same
        # context as `build_money_at_stake` (38 digits, truncating).
        with localcontext() as ctx:
            ctx.prec = _PRECISION
            ctx.rounding = ROUND_DOWN
            if self.notional != self.quantity * self.entry_price:
                raise ValueError("notional must equal quantity x entry_price")
            if sum((leg.leg_quantity for leg in self.take_profits), _ZERO) != self.quantity:
                raise ValueError("take-profit leg quantities must sum to the quantity")


def _side_text(side: object) -> str:
    text = side.value if isinstance(side, Direction) else side
    if not isinstance(text, str) or text not in _SIDES:
        raise ValueError(f"side must be LONG or SHORT, got {side!r}")
    return text


def _take_profit_pairs(raw: object) -> list[tuple[Decimal, Decimal]]:
    if raw is None or not isinstance(raw, Sequence) or len(raw) == 0:
        raise MoneyAtStakeUnavailable("take_profits", "no take-profit")
    pairs: list[tuple[Decimal, Decimal]] = []
    for item in raw:
        if not isinstance(item, tuple) or len(item) != 2:
            raise TypeError("each take-profit must be a (price, fraction) pair")
        pairs.append((_positive(item[0], "take_profit_price"), _positive(item[1], "fraction")))
    return pairs


def build_money_at_stake(
    *,
    side: Direction | str,
    sized: SizedResult,
    stop_loss_price: Decimal | None,
    take_profits: Sequence[tuple[Decimal, Decimal]] | None,
    cost_rates: CostRates,
    leverage: int | None,
    leverage_source: str,
    equity: Decimal | None,
    equity_source: str,
    equity_observed_at_utc: datetime | None,
    quote_asset: str = QUOTE_ASSET_USDT,
) -> MoneyAtStake:
    """Turn one risk-pipeline output into the money block; refuse when any input is missing.

    `take_profits` is a sequence of `(price, fraction_of_quantity)` pairs in plan order, labelled
    TP1, TP2, ... A profit is an ESTIMATE: the live TP1 leg is floored to the step size.

    Raises:
        MoneyAtStakeUnavailable: a needed input is missing or unusable (`.field` names it).
        TypeError / ValueError: an argument has the wrong type or a malformed value.
    """
    side_text = _side_text(side)
    if not isinstance(sized, SizedResult):
        raise TypeError(f"sized must be SizedResult, got {type(sized).__name__}")
    if sized.is_no_trade or sized.quantity is None:
        raise MoneyAtStakeUnavailable("sized", "NO_TRADE result carries no quantity")
    if sized.sizing_entry_price is None:
        raise MoneyAtStakeUnavailable("sizing_entry_price")
    if sized.modeled_costs_per_unit is None:
        raise MoneyAtStakeUnavailable("modeled_costs_per_unit")
    if stop_loss_price is None:
        raise MoneyAtStakeUnavailable("stop_loss_price")
    if leverage is None:
        raise MoneyAtStakeUnavailable("leverage")
    if equity is None:
        raise MoneyAtStakeUnavailable("equity")
    if equity_observed_at_utc is None:
        raise MoneyAtStakeUnavailable("equity_observed_at_utc")
    pairs = _take_profit_pairs(take_profits)

    quantity = _positive(sized.quantity, "quantity")
    entry = _positive(sized.sizing_entry_price, "sizing_entry_price")
    stop = _positive(stop_loss_price, "stop_loss_price")
    if sum((fraction for _, fraction in pairs), _ZERO) != _ONE:
        raise MoneyAtStakeUnavailable("take_profits", "fractions do not sum to 1")
    try:
        _check_side_prices(side_text, entry, stop, [price for price, _ in pairs])
    except ValueError as exc:
        field = "stop_loss_price" if "stop-loss" in str(exc) else "take_profits"
        raise MoneyAtStakeUnavailable(field, str(exc)) from exc

    with localcontext() as ctx:
        ctx.prec = _PRECISION
        ctx.rounding = ROUND_DOWN
        loss_gross = quantity * abs(entry - stop)
        if sized.realized_risk < loss_gross:
            raise MoneyAtStakeUnavailable("realized_risk", "below the gross loss at the stop")
        notional = quantity * entry
        margin = _truncate(
            required_initial_margin(quantity=quantity, price=entry, leverage=leverage)
        )
        legs: list[TakeProfitAtStake] = []
        for index, (tp_price, fraction) in enumerate(pairs, start=1):
            leg_quantity = quantity * fraction
            gross = leg_quantity * abs(tp_price - entry)
            cost = per_unit_round_trip_cost(
                side=side_text, entry_price=entry, stop_price=tp_price, rates=cost_rates
            )
            legs.append(
                TakeProfitAtStake(
                    label=f"TP{index}",
                    price=tp_price,
                    fraction=fraction,
                    leg_quantity=leg_quantity,
                    profit_gross=gross,
                    profit_net=gross - leg_quantity * cost,
                )
            )

    return MoneyAtStake(
        schema=MONEY_SCHEMA_TAG,
        quote_asset=quote_asset,
        side=side_text,
        quantity=quantity,
        entry_price=entry,
        stop_loss_price=stop,
        notional=notional,
        leverage=leverage,
        leverage_source=leverage_source,
        initial_margin=margin,
        loss_at_stop_gross=loss_gross,
        loss_at_stop_net=sized.realized_risk,
        take_profits=tuple(legs),
        equity=equity,
        equity_source=equity_source,
        equity_observed_at_utc=equity_observed_at_utc,
    )


# --------------------------------------------------------------------------- #
# Stored form
# --------------------------------------------------------------------------- #

_TOP_KEYS: Final = tuple(f.name for f in fields(MoneyAtStake))
_LEG_KEYS: Final = tuple(f.name for f in fields(TakeProfitAtStake))
_TOP_DECIMALS: Final = (
    "quantity",
    "entry_price",
    "stop_loss_price",
    "notional",
    "initial_margin",
    "loss_at_stop_gross",
    "loss_at_stop_net",
    "equity",
)
_LEG_DECIMALS: Final = ("price", "fraction", "leg_quantity", "profit_gross", "profit_net")


def _leg_payload(leg: TakeProfitAtStake) -> dict[str, Any]:
    doc: dict[str, Any] = {"label": leg.label}
    for name in _LEG_DECIMALS:
        doc[name] = format(getattr(leg, name), "f")
    return doc


def money_canonical_json(money: MoneyAtStake) -> str:
    """Canonical JSON text: sorted keys, compact, Decimal as fixed-point text, no float."""
    doc: dict[str, Any] = {
        "schema": money.schema,
        "quote_asset": money.quote_asset,
        "side": money.side,
        "leverage": money.leverage,
        "leverage_source": money.leverage_source,
        "equity_source": money.equity_source,
        "equity_observed_at_utc": money.equity_observed_at_utc.isoformat(),
        "take_profits": [_leg_payload(leg) for leg in money.take_profits],
    }
    for name in _TOP_DECIMALS:
        doc[name] = format(getattr(money, name), "f")
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _reject_float(literal: str) -> Any:
    raise ValueError(f"float literal {literal!r} in money JSON (Decimal text required)")


def _reject_constant(literal: str) -> Any:
    raise ValueError(f"non-finite constant {literal!r} in money JSON")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    doc = dict(pairs)
    if len(doc) != len(pairs):
        raise ValueError("duplicate key in money JSON")
    return doc


def _decode_decimal(name: str, raw: object) -> Decimal:
    if not isinstance(raw, str):
        raise ValueError(f"{name} must be Decimal text, got {type(raw).__name__}")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"{name} is not Decimal text: {raw!r}") from exc
    if not value.is_finite() or format(value, "f") != raw:
        raise ValueError(f"{name} is not canonical fixed-point Decimal text: {raw!r}")
    return value


def _decode_time(name: str, raw: object) -> datetime:
    if not isinstance(raw, str):
        raise ValueError(f"{name} must be ISO-8601 text, got {type(raw).__name__}")
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{name} is not an ISO-8601 datetime: {raw!r}") from exc
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC-aware")
    if value.isoformat() != raw:
        raise ValueError(f"{name} is not canonical ISO UTC text: {raw!r}")
    return value


def _require_keys(doc: object, expected: tuple[str, ...], where: str) -> dict[str, Any]:
    if not isinstance(doc, dict):
        raise ValueError(f"{where} must be an object, got {type(doc).__name__}")
    if set(doc) != set(expected):
        extra = sorted(set(doc) - set(expected))
        missing = sorted(set(expected) - set(doc))
        raise ValueError(f"{where} keys differ: unknown={extra} missing={missing}")
    return doc


def _decode_leg(raw: object) -> TakeProfitAtStake:
    doc = _require_keys(raw, _LEG_KEYS, "take-profit")
    label = doc["label"]
    if not isinstance(label, str):
        raise ValueError("take-profit label must be text")
    values = {name: _decode_decimal(name, doc[name]) for name in _LEG_DECIMALS}
    return TakeProfitAtStake(label=label, **values)


def parse_money_json(text: str) -> MoneyAtStake:
    """Rebuild a MoneyAtStake from its canonical JSON; strict, ValueError on anything else.

    Rejected: float literals, NaN / Infinity, duplicate, unknown or missing keys at either level,
    a foreign schema tag, non-canonical Decimal or time text, a naive time, a non-int leverage.
    """
    try:
        doc = json.loads(
            text,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
            object_pairs_hook=_no_duplicate_keys,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"money JSON is not valid JSON: {exc}") from exc
    doc = _require_keys(doc, _TOP_KEYS, "money JSON")
    if doc["schema"] != MONEY_SCHEMA_TAG:
        raise ValueError(f"unsupported money schema {doc['schema']!r}")
    leverage = doc["leverage"]
    if isinstance(leverage, bool) or not isinstance(leverage, int):
        raise ValueError(f"leverage must be an integer, got {type(leverage).__name__}")
    legs = doc["take_profits"]
    if not isinstance(legs, list) or not legs:
        raise ValueError("take_profits must be a non-empty list")
    for name in ("schema", "quote_asset", "side", "leverage_source", "equity_source"):
        if not isinstance(doc[name], str):
            raise ValueError(f"{name} must be text")
    try:
        return MoneyAtStake(
            schema=doc["schema"],
            quote_asset=doc["quote_asset"],
            side=doc["side"],
            leverage=leverage,
            leverage_source=doc["leverage_source"],
            equity_source=doc["equity_source"],
            equity_observed_at_utc=_decode_time(
                "equity_observed_at_utc", doc["equity_observed_at_utc"]
            ),
            take_profits=tuple(_decode_leg(leg) for leg in legs),
            **{name: _decode_decimal(name, doc[name]) for name in _TOP_DECIMALS},
        )
    except TypeError as exc:
        raise ValueError(f"money JSON field has the wrong type: {exc}") from exc


__all__ = [
    "EQUITY_SOURCES",
    "EQUITY_SOURCE_ACCOUNT_LIVE",
    "EQUITY_SOURCE_PAPER_CONFIG",
    "LEVERAGE_SOURCES",
    "LEVERAGE_SOURCE_CONSTRAINT_SNAPSHOT",
    "LEVERAGE_SOURCE_PAPER_CONFIG",
    "MONEY_AT_STAKE_MISSING",
    "MONEY_SCHEMA_TAG",
    "QUOTE_ASSET_USDT",
    "MoneyAtStake",
    "MoneyAtStakeUnavailable",
    "TakeProfitAtStake",
    "build_money_at_stake",
    "money_canonical_json",
    "parse_money_json",
]
