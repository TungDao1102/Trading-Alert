"""Pre-entry margin guard (Phase 22, plan 22-14; D-05, D-07, D-13, D-15, criteria 1 to 4).

``MarginGuard.evaluate(request)`` is the one call the execution manager makes (plan 22-15) before
an entry may reach the exchange. It composes the four checks of Phase 22 in ONE fixed order and
the FIRST refusal wins, each with its own plain reason code (amendment A7):

0. The ACCOUNT MODE comes first. One fresh account reading is taken and judged: an unusable
   reading is ``UNCERTAIN_ACCOUNT_STATE``, a hedge account is ``HEDGE_MODE_UNSUPPORTED`` and a
   multi-asset account is ``MARGIN_MODE_UNSUPPORTED``. Nothing is mutated on an account the system
   does not support or cannot read (criterion 4, T-22-48).
1. The SYMBOL CONFIGURATION second: ISOLATED margin and the target leverage are set and VERIFIED by
   a read (plan 22-11, criterion 1). It is second because the leverage every later number needs is
   the one the exchange confirmed, not the one the system asked for.
2. The LIQUIDATION check third (criterion 2): exchange brackets from the bounded-age cache, the
   notional within the symbol's ``maxNotionalValue``, and the strict buffer beyond the stop, all at
   the verified leverage and with the entry fee of the request (``fee_rate_entry``, Demo-observed to
   reduce the isolated wallet, plan 22-07 amendment of 2026-10-24).
3. The AVAILABLE MARGIN last (criterion 3): the fresh ``availableBalance`` must cover the initial
   margin at the verified leverage, the fees, the open loss of an already marketable limit, the
   margin of the other claims and the owner's headroom.

Fail closed. Any exception from any port (account refresh, configuration guard, bracket cache,
claims reader) is NO_TRADE ``UNCERTAIN_ACCOUNT_STATE`` and only a verdict with a plain code is ever
produced: no exception message is kept, logged or returned. A claim of unknown margin, a reading
that is stale or future-dated and a malformed answer of a port are refused the same way. A
``BaseException`` such as a cancellation propagates.

Freshness contract (D-03, Pitfall 6). The account is refreshed once at the start; ``now`` is read
from the injected clock AFTER the refresh and the reading is judged; the reading is judged AGAIN
with a clock read taken after the last await (the bracket read and the claims read take time),
immediately before the margin check, so the figure that decides is never older than the owner's
bound. The bracket reading is re-checked against the owner's bracket bound as well.

Reason codes are plain strings or existing enum values; ``RejectionReason`` is not changed
(amendment A3): ``UNCERTAIN_ACCOUNT_STATE`` and ``INSUFFICIENT_MARGIN`` from the enum,
``HEDGE_MODE_UNSUPPORTED`` imported from ``pre_placement``, ``MARGIN_MODE_UNSUPPORTED`` defined
here, the three configuration codes from ``symbol_config_guard`` and the four liquidation codes from
``src.risk.liquidation``. The ``MARGIN_CONFIG_UNVERIFIED`` outcome (and only it) carries the alert
reason of the same name for the manager's DIVERGENCE alert (amendment A9); ordinary refusals carry
none.

On success the verdict carries exactly what the exchange verified: the margin type, the leverage and
the equity of the same fresh reading, for the plan constraint snapshot (D-05, plan 22-15), plus
``config_changed`` (a configuration POST was SENT in this run) and the previous configuration as
EVIDENCE. The previous configuration is never restored (Pitfall 9, OWNER-OPEN O-1). A refusal
carries the same evidence whenever a POST was sent, so the manager can journal a mutation even when
the plan is refused.

What is deliberately not here. The guard changes nothing in the sizing or the quantization
(RISK-01): it judges the already-sized quantity at the already-snapped limit price. The netting
constant ``AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED`` of plan 22-04 (True since DECISIONS
D085, 2026-10-24; it was False until that owner row) is passed through to the claims sum. The
liquidation buffer, the bracket age and the headroom are the owner's REQUIRED numbers (O-2, O-3;
set by DECISIONS D085, 300 bps, 60000 ms and 1000 bps, in the execution-limits file): construction
refuses with ``ExecutionLimitsNotConfigured`` while any is unset and nothing here chooses one. The
module holds no bracket value, no rate and no leverage default (the target comes from the
configuration guard).
Backtest parity (D-15): the backtest has no margin or liquidation model, so these are live-only
gates like the Phase 21 equity age.

Purity: the module imports no adapter, store, SDK or sqlalchemy (it talks to its collaborators
through the ports below), reads no wall clock (only the injected one), logs nothing and holds no
quote-asset literal. It is a library: nothing composes it into a running process before plan 22-15
and Phase 24, and live placement stays disabled.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Protocol

from src.domain.enums import Direction, RejectionReason
from src.execution.bracket_cache import BracketReading
from src.execution.execution_limits import ExecutionLimits, ExecutionLimitsNotConfigured
from src.execution.pre_placement import HEDGE_MODE_UNSUPPORTED
from src.execution.symbol_config_guard import TARGET_MARGIN_TYPE, ConfigGuardResult
from src.risk.liquidation import (
    LIQUIDATION_INPUT_UNAVAILABLE,
    NOTIONAL_ABOVE_MAX,
    brackets_are_fresh,
    liquidation_verdict,
)
from src.risk.margin_check import (
    AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED,
    BLOCKED_HEDGE_MODE,
    BLOCKED_MULTI_ASSETS_MODE,
    AvailableMarginCheck,
    MarginClaim,
    margin_verdict,
    other_claims_margin,
)

# Defined here (a multi-asset account); the other plain codes are imported from their modules.
MARGIN_MODE_UNSUPPORTED: Final[str] = "MARGIN_MODE_UNSUPPORTED"

_OK: Final[str] = "OK"
_UNCERTAIN: Final[str] = RejectionReason.UNCERTAIN_ACCOUNT_STATE.value
_SIDES: Final[frozenset[str]] = frozenset({d.value for d in Direction})
_BUFFER_KEY: Final[str] = "margin.liquidation_buffer_bps"
_AGE_KEY: Final[str] = "margin.max_bracket_age_ms"
_HEADROOM_KEY: Final[str] = "margin.headroom_bps"


# --------------------------------------------------------------------------- request and verdict


def _require_decimal(value: object, name: str, *, allow_zero: bool) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    if value == 0 and not allow_zero:
        raise ValueError(f"{name} must be positive")
    return value


@dataclass(frozen=True)
class MarginGuardRequest:
    """What will be placed: the sized quantity at the snapped limit price and stop (RISK-01).

    ``fee_rate_entry`` and ``fee_rate_exit`` are the verified taker rates the manager already
    holds (a rate may be zero); ``symbol_is_flat`` is the caller's fact: no position, no open
    order and no open algo order on the symbol.
    """

    trade_plan_id: str
    symbol: str
    side: Direction | str
    quantity: Decimal
    limit_price: Decimal
    stop_price: Decimal
    mark_price: Decimal
    fee_rate_entry: Decimal
    fee_rate_exit: Decimal
    symbol_is_flat: bool

    def __post_init__(self) -> None:
        for name in ("trade_plan_id", "symbol"):
            value = getattr(self, name)
            if not isinstance(value, str) or value.strip() == "":
                raise ValueError(f"{name} must be a non-empty string")
        side = self.side.value if isinstance(self.side, Direction) else self.side
        if not isinstance(side, str) or side not in _SIDES:
            raise ValueError("side must be LONG or SHORT")
        for name in ("quantity", "limit_price", "stop_price", "mark_price"):
            _require_decimal(getattr(self, name), name, allow_zero=False)
        for name in ("fee_rate_entry", "fee_rate_exit"):
            _require_decimal(getattr(self, name), name, allow_zero=True)
        if not isinstance(self.symbol_is_flat, bool):
            raise TypeError("symbol_is_flat must be a bool")


@dataclass(frozen=True)
class MarginGuardVerdict:
    """The outcome: a pass with the verified values, or a NO_TRADE with one plain reason code.

    A pass has reason ``OK`` and carries the margin type, the leverage and the equity the exchange
    verified. A refusal carries none of the three (``is_no_trade``); ``config_changed`` and the
    previous configuration may be present on either as evidence that a configuration POST was sent.
    ``alert_reason`` is set only for the unverified-configuration outcome.
    """

    is_no_trade: bool
    reason_code: str
    alert_reason: str | None
    margin_type: str | None
    leverage: int | None
    equity_used: Decimal | None
    config_changed: bool
    previous_margin_type: str | None
    previous_leverage: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.is_no_trade, bool):
            raise TypeError("is_no_trade must be a bool")
        if not isinstance(self.reason_code, str) or self.reason_code == "":
            raise ValueError("reason_code must be a non-empty string")
        if not isinstance(self.config_changed, bool):
            raise TypeError("config_changed must be a bool")
        if self.alert_reason is not None and not isinstance(self.alert_reason, str):
            raise TypeError("alert_reason must be text or None")
        if self.previous_margin_type is not None and not isinstance(self.previous_margin_type, str):
            raise TypeError("previous_margin_type must be text or None")
        if self.previous_leverage is not None and type(self.previous_leverage) is not int:
            raise TypeError("previous_leverage must be an int or None")
        if self.is_no_trade:
            if self.reason_code == _OK:
                raise ValueError("a NO_TRADE verdict needs a non-OK reason code")
            if (
                self.margin_type is not None
                or self.leverage is not None
                or self.equity_used is not None
            ):
                raise ValueError("a NO_TRADE verdict carries no verified margin type or figure")
            return
        if self.reason_code != _OK:
            raise ValueError("a pass needs the reason code OK")
        if self.alert_reason is not None:
            raise ValueError("a pass carries no alert reason")
        if not isinstance(self.margin_type, str) or self.margin_type == "":
            raise ValueError("a pass needs the verified margin type")
        if type(self.leverage) is not int or self.leverage < 1:
            raise ValueError("a pass needs the verified leverage")
        if not isinstance(self.equity_used, Decimal) or not self.equity_used.is_finite():
            raise ValueError("a pass needs the equity used")


# --------------------------------------------------------------------------------------- ports


class MarginGuardPort(Protocol):
    """What the execution manager needs: one async evaluation per entry (plan 22-15)."""

    async def evaluate(self, request: MarginGuardRequest) -> MarginGuardVerdict: ...


class MarginAccountPort(Protocol):
    """The account source: one REST refresh, then judgements of the reading it kept."""

    async def refresh(self) -> None: ...

    def check_margin(self, *, now_utc: datetime) -> AvailableMarginCheck: ...


class ClaimsPort(Protocol):
    """The stored RESERVED and PLACED claims on margin (a plain call; an awaitable is accepted)."""

    def list_margin_claims(self) -> Any: ...


class ConfigGuardPort(Protocol):
    """The symbol configuration guard of plan 22-11."""

    async def ensure(self, *, symbol: str, symbol_is_flat: bool) -> ConfigGuardResult: ...


class BracketPort(Protocol):
    """The bounded-age bracket cache of plan 22-12."""

    async def get(self, *, symbol: str) -> BracketReading | None: ...


# ------------------------------------------------------------------------------------ the guard


def _is_plain_int(value: object) -> bool:
    return type(value) is int


class MarginGuard:
    """Account mode, configuration, liquidation, margin: one fixed order, first refusal wins."""

    def __init__(
        self,
        *,
        config_guard: ConfigGuardPort,
        brackets: BracketPort,
        account: MarginAccountPort,
        claims: ClaimsPort,
        clock: Callable[[], datetime],
        limits: ExecutionLimits,
    ) -> None:
        if not isinstance(limits, ExecutionLimits):
            raise TypeError("limits must be ExecutionLimits")
        unset = tuple(
            key
            for key, value in (
                (_BUFFER_KEY, limits.margin_liquidation_buffer_bps),
                (_AGE_KEY, limits.margin_max_bracket_age_ms),
                (_HEADROOM_KEY, limits.margin_headroom_bps),
            )
            if value is None
        )
        if unset:
            raise ExecutionLimitsNotConfigured(unset)
        buffer_bps = limits.margin_liquidation_buffer_bps
        age_ms = limits.margin_max_bracket_age_ms
        headroom_bps = limits.margin_headroom_bps
        for key, value in (
            (_BUFFER_KEY, buffer_bps),
            (_AGE_KEY, age_ms),
            (_HEADROOM_KEY, headroom_bps),
        ):
            if not _is_plain_int(value) or value is None or value < 1:
                raise ValueError(f"{key} must be a positive int")
        if not callable(clock):
            raise TypeError("clock must be callable")
        for port, names in (
            (config_guard, ("ensure",)),
            (brackets, ("get",)),
            (account, ("refresh", "check_margin")),
            (claims, ("list_margin_claims",)),
        ):
            for name in names:
                if not callable(getattr(port, name, None)):
                    raise TypeError(f"port must offer {name}")
        assert buffer_bps is not None and age_ms is not None and headroom_bps is not None
        self._config_guard = config_guard
        self._brackets = brackets
        self._account = account
        self._claims = claims
        self._clock = clock
        self._buffer_bps: int = buffer_bps
        self._bracket_max_age = timedelta(milliseconds=age_ms)
        self._headroom_bps: int = headroom_bps

    async def evaluate(self, request: MarginGuardRequest) -> MarginGuardVerdict:
        """Run the four checks in the fixed order; the first refusal is the verdict."""
        if not isinstance(request, MarginGuardRequest):
            raise TypeError("request must be a MarginGuardRequest")

        # 0. Account mode: one refresh, one clock read after it, one judgement.
        try:
            await self._account.refresh()
            first = self._account.check_margin(now_utc=self._clock())
        except Exception:  # noqa: BLE001 - an unreadable account is NO_TRADE, class name only
            return _refusal(_UNCERTAIN)
        mode_code = _account_refusal(first)
        if mode_code is not None:
            return _refusal(mode_code)

        # 1. Symbol configuration: set and verified, or refused.
        try:
            cfg = await self._config_guard.ensure(
                symbol=request.symbol, symbol_is_flat=request.symbol_is_flat
            )
        except Exception:  # noqa: BLE001 - nothing is known about what was sent, fail closed
            return _refusal(_UNCERTAIN)
        if not isinstance(cfg, ConfigGuardResult):
            return _refusal(_UNCERTAIN)
        if not cfg.ok:
            code = cfg.reason_code
            if not isinstance(code, str) or code in ("", _OK):
                return _refusal(_UNCERTAIN, cfg=cfg)
            alert = cfg.alert_reason if isinstance(cfg.alert_reason, str) else None
            return _refusal(code, alert=alert, cfg=cfg)
        verified = _verified_configuration(cfg)
        if verified is None:
            return _refusal(_UNCERTAIN, cfg=cfg)
        leverage, max_notional = verified

        # 2. Liquidation: notional within the symbol maximum, then the buffer beyond the stop.
        try:
            reading = await self._brackets.get(symbol=request.symbol)
        except Exception:  # noqa: BLE001 - a failing bracket source is NO_TRADE, class name only
            return _refusal(_UNCERTAIN, cfg=cfg)
        if reading is None:
            return _refusal(LIQUIDATION_INPUT_UNAVAILABLE, cfg=cfg)
        try:
            usable = (
                isinstance(reading, BracketReading)
                and reading.symbol == request.symbol
                and len(reading.brackets) > 0
                and brackets_are_fresh(
                    observed_at_utc=reading.observed_at_utc,
                    now_utc=self._clock(),
                    max_age=self._bracket_max_age,
                )
            )
            if not usable:
                return _refusal(LIQUIDATION_INPUT_UNAVAILABLE, cfg=cfg)
            if request.limit_price * request.quantity > max_notional:
                return _refusal(NOTIONAL_ABOVE_MAX, cfg=cfg)
            liquidation = liquidation_verdict(
                side=request.side,
                entry_price=request.limit_price,
                quantity=request.quantity,
                leverage=leverage,
                brackets=reading.brackets,
                stop_price=request.stop_price,
                buffer_bps=self._buffer_bps,
                entry_fee_rate=request.fee_rate_entry,
            )
        except Exception:  # noqa: BLE001 - an unjudgeable liquidation is NO_TRADE
            return _refusal(_UNCERTAIN, cfg=cfg)
        if not liquidation.ok:
            return _refusal(liquidation.reason_code, cfg=cfg)

        # 3. Available margin: the claims, a clock read after the last await, the reading re-judged.
        try:
            claims = await self._claims_snapshot()
            second = self._account.check_margin(now_utc=self._clock())
        except Exception:  # noqa: BLE001 - unreadable claims or reading is NO_TRADE
            return _refusal(_UNCERTAIN, cfg=cfg)
        again = _account_refusal(second)
        if again is not None:
            return _refusal(again, cfg=cfg)
        if second.available is None or second.equity is None or second.observed_at_utc is None:
            return _refusal(_UNCERTAIN, cfg=cfg)
        try:
            others = other_claims_margin(
                claims=claims,
                exclude_trade_plan_id=request.trade_plan_id,
                reading_observed_at_utc=second.observed_at_utc,
                resting_orders_netted=AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED,
            )
            margin = margin_verdict(
                available_balance=second.available,
                quantity=request.quantity,
                limit_price=request.limit_price,
                mark_price=request.mark_price,
                side=request.side,
                leverage=leverage,
                fee_rate_entry=request.fee_rate_entry,
                fee_rate_exit=request.fee_rate_exit,
                others_margin=others,
                headroom_bps=self._headroom_bps,
            )
        except Exception:  # noqa: BLE001 - an unjudgeable margin is NO_TRADE
            return _refusal(_UNCERTAIN, cfg=cfg)
        if not margin.ok:
            return _refusal(margin.reason_code, cfg=cfg)

        sent, previous_type, previous_leverage = _evidence(cfg, always=True)
        return MarginGuardVerdict(
            is_no_trade=False,
            reason_code=_OK,
            alert_reason=None,
            margin_type=str(cfg.margin_type),
            leverage=leverage,
            equity_used=second.equity,
            config_changed=sent,
            previous_margin_type=previous_type,
            previous_leverage=previous_leverage,
        )

    async def _claims_snapshot(self) -> tuple[MarginClaim, ...]:
        found = self._claims.list_margin_claims()
        if inspect.isawaitable(found):
            found = await found
        return tuple(found)


# --------------------------------------------------------------------------------------- helpers


def _account_refusal(check: object) -> str | None:
    """The plain code for a refused account judgement, or None when it is usable."""
    if not isinstance(check, AvailableMarginCheck):
        return _UNCERTAIN
    if check.blocked is None:
        return None if check.reason_code == _OK else _UNCERTAIN
    if check.blocked == BLOCKED_HEDGE_MODE:
        return HEDGE_MODE_UNSUPPORTED
    if check.blocked == BLOCKED_MULTI_ASSETS_MODE:
        return MARGIN_MODE_UNSUPPORTED
    return _UNCERTAIN


def _verified_configuration(cfg: ConfigGuardResult) -> tuple[int, Decimal] | None:
    """The verified leverage and ``maxNotionalValue``, or None when the result is not usable."""
    leverage = cfg.leverage
    max_notional = cfg.max_notional_value
    if cfg.margin_type != TARGET_MARGIN_TYPE:
        return None
    if type(leverage) is not int or leverage < 1:
        return None
    if not isinstance(max_notional, Decimal) or not max_notional.is_finite() or max_notional <= 0:
        return None
    return leverage, max_notional


def _evidence(cfg: ConfigGuardResult, *, always: bool) -> tuple[bool, str | None, int | None]:
    """(config_changed, previous margin type, previous leverage) from the configuration result.

    ``config_changed`` is True when at least one configuration POST was sent. The previous
    configuration is carried on a pass always, on a refusal only when a POST was sent.
    """
    posts = cfg.posts_sent
    sent = type(posts) is int and posts > 0
    if not (sent or always):
        return False, None, None
    previous_type = cfg.previous_margin_type
    previous_leverage = cfg.previous_leverage
    return (
        sent,
        previous_type if isinstance(previous_type, str) else None,
        previous_leverage if type(previous_leverage) is int else None,
    )


def _refusal(
    code: str, *, alert: str | None = None, cfg: ConfigGuardResult | None = None
) -> MarginGuardVerdict:
    """A NO_TRADE verdict; the configuration evidence rides along when a POST was sent."""
    sent, previous_type, previous_leverage = (
        (False, None, None) if cfg is None else _evidence(cfg, always=False)
    )
    return MarginGuardVerdict(
        is_no_trade=True,
        reason_code=code,
        alert_reason=alert,
        margin_type=None,
        leverage=None,
        equity_used=None,
        config_changed=sent,
        previous_margin_type=previous_type,
        previous_leverage=previous_leverage,
    )


__all__ = [
    "MARGIN_MODE_UNSUPPORTED",
    "BracketPort",
    "ClaimsPort",
    "ConfigGuardPort",
    "MarginAccountPort",
    "MarginGuard",
    "MarginGuardPort",
    "MarginGuardRequest",
    "MarginGuardVerdict",
]
