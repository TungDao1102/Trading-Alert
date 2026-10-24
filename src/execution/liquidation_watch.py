"""Post-fill liquidation watch (Phase 22, plan 22-13; D-12, amendment A10, owner item O-4, F-964).

Question answered: now that a position exists, is the exchange's own ``liquidationPrice`` of that
position beyond the stop-loss by the owner's buffer, and does it agree with the price the
pre-entry guard computed locally? The coordinator in ``src.execution.protection`` asks this once
per plan, after the first fill and once the stop is REST-confirmed. The answer is a
``LiquidationWatchVerdict``; the coordinator, not this module, closes the position.

The three inputs of the judgement:

1. The exchange value (``exchange_liquidation_price``), from the REST position row. It decides.
2. The strict predicate of ``src.risk.liquidation.liquidation_beyond_stop`` (LONG
   ``LP < stop - buffer``, SHORT ``LP > stop + buffer``, buffer = entry x
   ``margin.liquidation_buffer_bps`` / 10000) measured from the ACTUAL fill price of the
   position, not from the limit price the pre-entry guard used.
3. The optional local comparison: ``liquidation_price`` of the same module computed from the
   exchange's leverage brackets (a ``BracketSource``) and the entry fee rate (an
   ``EntryFeeRateSource``). It never decides: a bracket source or a fee source that returns None
   or raises only skips the comparison (``local_price`` None), so an unavailable bracket set can
   never turn a passing exchange value into a failure.

The unknown rule (Pitfall 7, amendment A10, D-12). An exchange value of None, zero, negative or
not finite is UNKNOWN and fails closed. Zero is the cross-margin sentinel on every recorded Demo
row (22-DEMO-RESULTS; Demo-observed, not mainnet) and must never be read as "far away". So is an
input needed to judge it that is unknown: a leverage below one, or inverted stop geometry (a LONG
stop not below the entry, a SHORT stop not above it). A leverage of None (a plan restored after a
restart: the persisted snapshot holds UNKNOWN) is NOT unknown for the decision, which does not use
it; it only skips the local comparison (WR-03).

The policy (OWNER-OPEN O-4). Whether a failed check closes the position or only alerts is the
owner's open decision. ``LiquidationFailurePolicy`` has both members built: ``CLOSE_POSITION`` (the
D-12 default the composition is expected to pass) and ``ALERT_ONLY``. It is a REQUIRED keyword
argument with no default, like ``FundingPolicy`` in Phase 21: this module decides neither for the
owner. A failed check is ``CLOSE`` under the first and ``ALERT_ONLY_FAILED`` under the second.

"Differs" means unequal at the exchange value's own decimal places: the exchange string fixes the
quantum, the local value is rounded half-up to it, and no tolerance number exists or is invented
here. A difference is expected (funding, the exit fee and the isolated-wallet assumption are not in
the local price; 22-RESEARCH 2.5) and is the point of the comparison: ``OK_DIFFERS`` is calibration
only, both exact prices are on the verdict for the journal, and no amount belongs in any alert.

Purity: stdlib, Decimal, ``src.execution.execution_limits`` and ``src.risk.liquidation`` only. No
adapter, store, SDK or sqlalchemy import, no wall clock (the bracket source owns its injected
clock), no quote-asset name, and no numeric literal except 0 and 1. The limit and every price are
inputs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import Enum
from typing import Final, Protocol

from src.execution.execution_limits import ExecutionLimits, ExecutionLimitsNotConfigured
from src.risk.liquidation import (
    LIQUIDATION_OK,
    Bracket,
    liquidation_beyond_stop,
    liquidation_price,
)

LIQUIDATION_UNKNOWN_AFTER_FILL: Final[str] = "LIQUIDATION_UNKNOWN_AFTER_FILL"
LIQUIDATION_TOO_CLOSE_AFTER_FILL: Final[str] = "LIQUIDATION_TOO_CLOSE_AFTER_FILL"
LIQUIDATION_PRICE_DIFFERS: Final[str] = "LIQUIDATION_PRICE_DIFFERS"

_BUFFER_KEY: Final[str] = "margin.liquidation_buffer_bps"
_SIDES: Final[frozenset[str]] = frozenset({"LONG", "SHORT"})
_LONG: Final[str] = "LONG"


class LiquidationFailurePolicy(str, Enum):
    """What a failed post-fill check means (OWNER-OPEN O-4). Both are built; neither is chosen."""

    CLOSE_POSITION = "CLOSE_POSITION"
    ALERT_ONLY = "ALERT_ONLY"


class LiquidationWatchAction(str, Enum):
    """The four answers of ``LiquidationWatch.check``."""

    OK = "OK"
    OK_DIFFERS = "OK_DIFFERS"
    CLOSE = "CLOSE"
    ALERT_ONLY_FAILED = "ALERT_ONLY_FAILED"


def _require_decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal, got {type(value).__name__}")
    return value


def _require_positive(value: object, name: str) -> Decimal:
    amount = _require_decimal(value, name)
    if not amount.is_finite() or amount <= 0:
        raise ValueError(f"{name} must be a positive finite Decimal")
    return amount


@dataclass(frozen=True)
class LiquidationWatchInput:
    """One position as the coordinator read it from REST, plus the plan's stop and leverage.

    ``entry_price`` is the position's actual average entry price. ``leverage`` is the leverage the
    pre-entry guard verified (None when unknown, as on a restored plan; the decision does not use
    it, only the optional local comparison). ``exchange_liquidation_price`` is None or any
    Decimal as read: zero, negative and non-finite values are judged UNKNOWN by the watch.
    """

    symbol: str
    side: str
    stop_price: Decimal
    leverage: int | None
    quantity: Decimal
    entry_price: Decimal
    exchange_liquidation_price: Decimal | None

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or self.symbol.strip() == "":
            raise ValueError("symbol must be a non-empty string")
        if not isinstance(self.side, str) or self.side not in _SIDES:
            raise ValueError("side must be LONG or SHORT")
        _require_positive(self.stop_price, "stop_price")
        _require_positive(self.quantity, "quantity")
        _require_positive(self.entry_price, "entry_price")
        if self.leverage is not None and (
            isinstance(self.leverage, bool) or not isinstance(self.leverage, int)
        ):
            raise TypeError("leverage must be int or None")
        if self.exchange_liquidation_price is not None:
            _require_decimal(self.exchange_liquidation_price, "exchange_liquidation_price")


@dataclass(frozen=True)
class LiquidationWatchVerdict:
    """The judgement. ``reason`` is a fixed upper-case code (``LIQUIDATION_OK`` for a pass).

    ``exchange_price`` and ``local_price`` are exact and informational: the coordinator journals
    them as calibration data; they never go into an alert.
    """

    action: LiquidationWatchAction
    reason: str
    exchange_price: Decimal | None
    local_price: Decimal | None

    def __post_init__(self) -> None:
        if not isinstance(self.action, LiquidationWatchAction):
            raise TypeError("action must be a LiquidationWatchAction")
        if not isinstance(self.reason, str) or self.reason == "":
            raise ValueError("reason must be a non-empty string")
        for name in ("exchange_price", "local_price"):
            value = getattr(self, name)
            if value is not None:
                _require_decimal(value, name)


class BracketReadingView(Protocol):
    """The part of ``BracketCache``'s reading this module reads."""

    @property
    def brackets(self) -> Sequence[Bracket]: ...


class BracketSource(Protocol):
    """``BracketCache.get``: fresh brackets of one symbol, or None."""

    async def get(self, *, symbol: str) -> BracketReadingView | None: ...


class EntryFeeRateSource(Protocol):
    """The entry fee rate for one symbol (a Decimal, zero allowed), or None when unknown."""

    async def entry_fee_rate(self, *, symbol: str) -> Decimal | None: ...


class LiquidationWatchPort(Protocol):
    """What the protection coordinator calls, once per plan."""

    async def check(self, inputs: LiquidationWatchInput) -> LiquidationWatchVerdict: ...


def _is_unknown_exchange_value(value: Decimal | None) -> bool:
    return value is None or not value.is_finite() or value <= 0


def _equal_at_exchange_places(exchange: Decimal, local: Decimal) -> bool:
    """Equality after rounding ``local`` to the decimal places of the exchange's own string."""
    exponent = exchange.as_tuple().exponent
    if not isinstance(exponent, int):
        return False
    try:
        rounded = local.quantize(Decimal(1).scaleb(exponent), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return False
    return rounded == exchange


class LiquidationWatch:
    """The post-fill judgement; see the module docstring for the contract."""

    def __init__(
        self,
        *,
        brackets: BracketSource,
        fee_rates: EntryFeeRateSource,
        limits: ExecutionLimits,
        policy: LiquidationFailurePolicy,
    ) -> None:
        if not isinstance(policy, LiquidationFailurePolicy):
            raise TypeError("policy must be a LiquidationFailurePolicy member (OWNER-OPEN O-4)")
        buffer_bps = limits.margin_liquidation_buffer_bps
        if buffer_bps is None:
            raise ExecutionLimitsNotConfigured((_BUFFER_KEY,))
        self._brackets = brackets
        self._fee_rates = fee_rates
        self._buffer_bps = buffer_bps
        self._policy = policy

    @property
    def policy(self) -> LiquidationFailurePolicy:
        return self._policy

    def _failed(self) -> LiquidationWatchAction:
        if self._policy is LiquidationFailurePolicy.CLOSE_POSITION:
            return LiquidationWatchAction.CLOSE
        return LiquidationWatchAction.ALERT_ONLY_FAILED

    async def _local_price(self, inputs: LiquidationWatchInput) -> Decimal | None:
        """The local reconstruction, or None when any part of it is unavailable (never raises)."""
        leverage = inputs.leverage
        if leverage is None:
            return None
        try:
            reading = await self._brackets.get(symbol=inputs.symbol)
            if reading is None:
                return None
            fee_rate = await self._fee_rates.entry_fee_rate(symbol=inputs.symbol)
            if fee_rate is None:
                return None
            return liquidation_price(
                side=inputs.side,
                entry_price=inputs.entry_price,
                quantity=inputs.quantity,
                leverage=leverage,
                brackets=list(reading.brackets),
                entry_fee_rate=fee_rate,
            )
        except Exception:  # noqa: BLE001 - the local value only calibrates; it never decides
            return None

    async def check(self, inputs: LiquidationWatchInput) -> LiquidationWatchVerdict:
        """OK, OK_DIFFERS, or the policy's failure action (CLOSE / ALERT_ONLY_FAILED)."""
        exchange = inputs.exchange_liquidation_price
        leverage = inputs.leverage
        inverted = (
            inputs.stop_price >= inputs.entry_price
            if inputs.side == _LONG
            else inputs.stop_price <= inputs.entry_price
        )
        # The leverage is NOT an input of the decision (WR-03): the strict predicate needs the
        # exchange value, the stop, the fill price and the buffer only. A plan restored after a
        # restart has no leverage (the persisted snapshot is write-once and holds UNKNOWN), and a
        # healthy position with a REST-confirmed stop must not be closed for that; the leverage only
        # feeds the local comparison, which is skipped when it is None. A leverage that IS given but
        # below one is malformed input and stays unknown.
        if (
            _is_unknown_exchange_value(exchange)
            or (leverage is not None and leverage < 1)
            or inverted
            or exchange is None
        ):
            return LiquidationWatchVerdict(
                self._failed(), LIQUIDATION_UNKNOWN_AFTER_FILL, exchange, None
            )
        local = await self._local_price(inputs)
        if not liquidation_beyond_stop(
            side=inputs.side,
            liquidation_price=exchange,
            stop_price=inputs.stop_price,
            entry_price=inputs.entry_price,
            buffer_bps=self._buffer_bps,
        ):
            return LiquidationWatchVerdict(
                self._failed(), LIQUIDATION_TOO_CLOSE_AFTER_FILL, exchange, local
            )
        if local is not None and not _equal_at_exchange_places(exchange, local):
            return LiquidationWatchVerdict(
                LiquidationWatchAction.OK_DIFFERS, LIQUIDATION_PRICE_DIFFERS, exchange, local
            )
        return LiquidationWatchVerdict(LiquidationWatchAction.OK, LIQUIDATION_OK, exchange, local)


__all__ = [
    "LIQUIDATION_PRICE_DIFFERS",
    "LIQUIDATION_TOO_CLOSE_AFTER_FILL",
    "LIQUIDATION_UNKNOWN_AFTER_FILL",
    "BracketReadingView",
    "BracketSource",
    "EntryFeeRateSource",
    "LiquidationFailurePolicy",
    "LiquidationWatch",
    "LiquidationWatchAction",
    "LiquidationWatchInput",
    "LiquidationWatchPort",
    "LiquidationWatchVerdict",
]
