"""Account commission cache for the live process (plan 24-15; D-22, G3-008).

``CommissionCache`` is the one object that turns the adapter's ``user_commission_rate`` (GET
/fapi/v1/commissionRate, USER_DATA, weight 20, through the shared REST gate) into the
``AccountCommission`` readings that ``src.risk.live_commission.resolve_live_cost_rates`` needs.
Without a fresh reading every live plan is NO_TRADE ``UNCERTAIN_ACCOUNT_STATE``; with a stale one
the cost guard would size on the wrong fee. Phase 12 built the resolver and the adapter read and
left the runtime wiring (the refresh and the TTL) to this module.

* Cadence. The TTL is the registry key ``commission_rate_ttl_seconds`` (a ``timedelta`` handed in
  by the composition root). ``refresh_due`` is called on a periodic task (the reconcile tick) and
  reads a symbol only when it has no reading or its reading is at least ``ttl - refresh_margin``
  old (the margin is one reconcile tick, so a reading is replaced before it expires). A margin at
  or above the TTL means "due on every call". Nothing else spends the weight-20 call.
* One call per symbol per due refresh; no retry, no loop, no sleep. A symbol whose read failed is
  next tried by the next ``refresh_due`` call, not inside the same one.
* Freshness. ``observed_at_utc`` is stamped with the injected clock BEFORE the request, so the age
  is only over-estimated. ``account_commission_for`` returns a reading only while its age is
  within ``[0, ttl]`` (the rule of ``resolve_live_cost_rates``: above the TTL or negative is
  stale); a symbol that is not tracked or was never read gives None.
* Failure. A failed read (any ``Exception``) keeps that symbol's PREVIOUS reading, but only until
  that reading's own TTL ends (the age rule above); other symbols are unaffected. A response the
  project refuses as invalid (``ValueError`` or ``TypeError``: a negative or out-of-range rate, a
  rate for another symbol, a missing field) is not a transport failure but a value that must not
  be trusted, and it also drops the previous reading (fail closed, T-24-41). Only the exception
  CLASS NAME is kept (``last_error_types``) and journaled (``CommissionRefreshEvent``): a message
  can carry a value. A ``BaseException`` propagates. The injected ``record`` is awaited on a change
  of outcome only (the first failure, a failure of another class, the recovery); one that raises
  is swallowed, because the journal must not stop the refresh.
* Negative maker rate. The adapter refuses it (``ValueError``) and so does ``AccountCommission``;
  that is the owner's decision D-22 (Phase 12 review IN-01): a negative maker rate is a
  fail-closed refusal, not a rebate to model.
* Consumers. ``cost_rates_for`` calls ``resolve_live_cost_rates`` with the cache's own clock and
  TTL (the sizing path). ``entry_fee_rate`` is the ``EntryFeeRateSource`` port of
  ``src.execution.liquidation_watch.LiquidationWatch`` (plan 24-16): the account TAKER rate, since
  the entry is a taker-priced fill in the liquidation estimate, or None when unknown or stale.
  Both read the same readings.

Purity: no wall clock (the clock is injected), no SDK, no sqlalchemy, no float, no logging of a
value.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol

from src.risk.cost_rates import CostRates
from src.risk.live_commission import (
    AccountCommission,
    LiveCostRatesResult,
    resolve_live_cost_rates,
)

RefreshEventKind = Literal["failure", "recovery"]
_ZERO = timedelta(0)


class CommissionPort(Protocol):
    """The one adapter read the cache calls (async, REST, USER_DATA, weight 20)."""

    async def user_commission_rate(self, symbol: str) -> Any: ...


@dataclass(frozen=True)
class CommissionRefreshEvent:
    """One journaled outcome change of a symbol's refresh (a class name, never a message)."""

    symbol: str
    error_class: str | None
    at_utc: datetime
    kind: RefreshEventKind = "failure"

    def __post_init__(self) -> None:
        if self.kind == "failure" and not self.error_class:
            raise ValueError("a failure event needs an error class")
        if self.kind == "recovery" and self.error_class is not None:
            raise ValueError("a recovery event carries no error class")


Record = Callable[[CommissionRefreshEvent], Awaitable[None]]


def _require_symbol(symbol: object) -> str:
    if (
        not isinstance(symbol, str)
        or symbol == ""
        or symbol != symbol.strip()
        or symbol != symbol.upper()
    ):
        raise ValueError("symbol must be a non-empty upper-case string")
    return symbol


class CommissionCache:
    """Fresh per-symbol account commission or None; see the module docstring for the contract."""

    def __init__(
        self,
        *,
        adapter: CommissionPort,
        clock: Callable[[], datetime],
        symbols: tuple[str, ...],
        ttl: timedelta,
        refresh_margin: timedelta,
        record: Record | None = None,
    ) -> None:
        if not callable(clock):
            raise TypeError("clock must be callable")
        if not callable(getattr(adapter, "user_commission_rate", None)):
            raise TypeError("adapter must offer user_commission_rate")
        if not isinstance(ttl, timedelta) or ttl <= _ZERO:
            raise ValueError("ttl must be a positive timedelta")
        if not isinstance(refresh_margin, timedelta) or refresh_margin < _ZERO:
            raise ValueError("refresh_margin must be a non-negative timedelta")
        names = tuple(_require_symbol(symbol) for symbol in symbols)
        if not names:
            raise ValueError("a CommissionCache needs at least one symbol")
        if len(set(names)) != len(names):
            raise ValueError("duplicate symbol")
        self._adapter = adapter
        self._clock = clock
        self._symbols = names
        self._ttl = ttl
        self._due_age = max(ttl - refresh_margin, _ZERO)
        self._record = record
        self._readings: dict[str, AccountCommission] = {}
        self._errors: dict[str, str] = {}

    @property
    def symbols(self) -> tuple[str, ...]:
        return self._symbols

    @property
    def ttl(self) -> timedelta:
        return self._ttl

    @property
    def last_error_types(self) -> dict[str, str]:
        """Exception class name of each symbol whose latest refresh failed. Never a message."""
        return dict(self._errors)

    # ---- refresh ------------------------------------------------------------------------ #

    def _is_due(self, symbol: str, now: datetime) -> bool:
        reading = self._readings.get(symbol)
        if reading is None:
            return True
        age = now - reading.observed_at_utc
        return age < _ZERO or age >= self._due_age

    async def refresh_due(self) -> tuple[str, ...]:
        """Read every tracked symbol that is due, once each; return the symbols read OK.

        Never raises for a failed read (see the module docstring); a ``BaseException`` does.
        """
        refreshed: list[str] = []
        for symbol in self._symbols:
            if not self._is_due(symbol, self._clock()):
                continue
            if await self._refresh_one(symbol):
                refreshed.append(symbol)
        return tuple(refreshed)

    async def _refresh_one(self, symbol: str) -> bool:
        observed = self._clock()
        try:
            raw = await self._adapter.user_commission_rate(symbol)
            if raw.symbol != symbol:
                raise ValueError("commission response is for another symbol")
            reading = AccountCommission(
                symbol=symbol,
                maker_rate=raw.maker_rate,
                taker_rate=raw.taker_rate,
                observed_at_utc=observed,
            )
        except (ValueError, TypeError, AttributeError) as exc:
            # An untrustworthy value: the previous reading goes too (fail closed).
            self._readings.pop(symbol, None)
            await self._note_failure(symbol, type(exc).__name__)
            return False
        except Exception as exc:  # noqa: BLE001 - a failed read keeps the previous reading to TTL
            await self._note_failure(symbol, type(exc).__name__)
            return False
        self._readings[symbol] = reading
        if self._errors.pop(symbol, None) is not None:
            await self._emit(
                CommissionRefreshEvent(
                    symbol=symbol, error_class=None, at_utc=self._clock(), kind="recovery"
                )
            )
        return True

    async def _note_failure(self, symbol: str, error_class: str) -> None:
        previous = self._errors.get(symbol)
        self._errors[symbol] = error_class
        if previous != error_class:
            await self._emit(
                CommissionRefreshEvent(symbol=symbol, error_class=error_class, at_utc=self._clock())
            )

    async def _emit(self, event: CommissionRefreshEvent) -> None:
        if self._record is None:
            return
        try:
            await self._record(event)
        except Exception:  # noqa: BLE001 - the journal must not stop the refresh
            return

    # ---- readings ----------------------------------------------------------------------- #

    def account_commission_for(self, symbol: str) -> AccountCommission | None:
        """The reading of ``symbol`` while its age is within [0, ttl]; else None."""
        reading = self._readings.get(symbol)
        if reading is None:
            return None
        age = self._clock() - reading.observed_at_utc
        if age < _ZERO or age > self._ttl:
            return None
        return reading

    def cost_rates_for(self, *, parameter_rates: CostRates, symbol: str) -> LiveCostRatesResult:
        """``resolve_live_cost_rates`` over this cache's reading, clock and TTL (the sizing path).

        Returns NO_TRADE ``UNCERTAIN_ACCOUNT_STATE`` with no rates when the reading is missing,
        stale or for another symbol.
        """
        return resolve_live_cost_rates(
            parameter_rates=parameter_rates,
            account_commission=self.account_commission_for(symbol),
            candidate_symbol=symbol,
            now_utc=self._clock(),
            ttl=self._ttl,
        )

    async def entry_fee_rate(self, *, symbol: str) -> Decimal | None:
        """The account taker rate (zero allowed) for the liquidation watch, or None if unknown."""
        reading = self.account_commission_for(symbol)
        return None if reading is None else reading.taker_rate


__all__ = [
    "CommissionCache",
    "CommissionPort",
    "CommissionRefreshEvent",
    "RefreshEventKind",
]
