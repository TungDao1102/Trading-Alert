"""Bounded-age cache of the exchange leverage brackets (Phase 22, plan 22-12; D-11, criterion 2).

``BracketCache`` is the one object that turns the adapter's ``leverage_brackets_snapshot`` into a
``BracketReading`` (pure ``Bracket`` objects plus the time they were read) for the liquidation
guard, and keeps it only while it is younger than the owner's bound (``margin.max_bracket_age_ms``,
D-11, OWNER-OPEN O-3). Brackets change per account and over time (22-RESEARCH Pitfall 11), so a
bracket set that is stale or was never read is never used.

* Freshness contract. ``get`` stamps ``observed_at_utc`` with the injected clock BEFORE the
  request, so the age is only over-estimated. It reuses a cached reading only while
  ``src.risk.liquidation.brackets_are_fresh`` says so (an age greater than the bound, or
  negative, is stale; equal passes), and it reads the injected clock again AFTER the await: a
  reading that is no longer fresh at return time is dropped and ``get`` returns None.
* The bound comes from the REQUIRED limit ``margin.max_bracket_age_ms`` of the execution limits.
  Construction raises ``ExecutionLimitsNotConfigured`` while it is unset (the same pattern as
  ``LiveEquitySource``); the cache holds no bound and no bracket value of its own.
* Fail closed, no stale fallback. A failed read (any ``Exception`` from the port, a table for
  another symbol, an empty table, a row the ``Bracket`` validation refuses, a naive clock value)
  drops the cached reading of that symbol, records only the exception CLASS NAME in
  ``last_error_type`` and returns None. The read is never retried and never slept on. A reading
  that is no longer fresh when the read returns is dropped too and recorded as
  ``"StaleBracketReading"`` (a label, not an exception class). A ``BaseException`` propagates.
* Notional coefficient (assumption A8, 22-RESEARCH 2.4). ``notionalCoef`` is the account
  adjustment of the table. None (absent) and exactly 1 are accepted; any other value makes the
  set unusable (a failed read, ``ValueError``) until the owner decides what it means.
* ``invalidate`` drops one symbol (or all). An ``invalidate`` that arrives while a read of the
  affected symbol is in flight discards that read's result (the generation rule of
  ``LiveEquitySource.refresh``); the read itself is not an error, so ``get`` returns None and
  ``last_error_type`` is None. There is no single-flight lock: two concurrent first ``get`` calls
  for one symbol may each read once.
* Purity. The module imports no adapter, store, SDK or sqlalchemy module (it talks to the
  adapter through ``BracketPort`` and converts rows by attribute access), reads no wall clock
  (only the injected one) and logs nothing: no bracket value and no exception message is kept.

Not wired in a running process until plan 22-14. Figures quoted in tests are demo-observed, not
mainnet.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from src.execution.execution_limits import ExecutionLimits, ExecutionLimitsNotConfigured
from src.risk.liquidation import Bracket, brackets_are_fresh

_AGE_KEY = "margin.max_bracket_age_ms"
_ONE_MS = timedelta(milliseconds=1)
_STALE_LABEL = "StaleBracketReading"
_UNIT_COEFFICIENT = Decimal(1)


class BracketPort(Protocol):
    """The one adapter read the cache calls (async, REST, read-only, weight 1)."""

    async def leverage_brackets_snapshot(self, *, symbol: str) -> Any: ...


@dataclass(frozen=True)
class BracketReading:
    """The brackets of one symbol and the injected-clock time the read started."""

    symbol: str
    brackets: tuple[Bracket, ...]
    observed_at_utc: datetime


def _require_symbol(symbol: object) -> str:
    if not isinstance(symbol, str) or symbol.strip() == "":
        raise ValueError("symbol must be a non-empty string")
    return symbol


def _reading_from_table(table: Any, symbol: str, observed_at_utc: datetime) -> BracketReading:
    """Map the adapter's table to a reading; any refusal raises (a failed read for the cache)."""
    if table.symbol != symbol:
        raise ValueError("bracket table is for another symbol")
    coef = table.notional_coef
    if coef is not None:
        if isinstance(coef, bool) or not isinstance(coef, Decimal):
            raise TypeError("notional_coef must be Decimal or None")
        if coef != _UNIT_COEFFICIENT:
            raise ValueError("notional_coef other than 1 is not supported")
    rows = tuple(table.brackets)
    if len(rows) == 0:
        raise ValueError("bracket table is empty")
    brackets = tuple(
        Bracket(
            bracket=row.bracket,
            initial_leverage=row.initial_leverage,
            notional_floor=row.notional_floor,
            notional_cap=row.notional_cap,
            maint_margin_ratio=row.maint_margin_ratio,
            cum=row.cum,
        )
        for row in rows
    )
    return BracketReading(symbol=symbol, brackets=brackets, observed_at_utc=observed_at_utc)


class BracketCache:
    """Fresh exchange brackets or None; see the module docstring for the contract."""

    def __init__(
        self,
        *,
        adapter: BracketPort,
        clock: Callable[[], datetime],
        limits: ExecutionLimits,
    ) -> None:
        if not isinstance(limits, ExecutionLimits):
            raise TypeError("limits must be ExecutionLimits")
        age_ms = limits.margin_max_bracket_age_ms
        if age_ms is None:
            raise ExecutionLimitsNotConfigured((_AGE_KEY,))
        if isinstance(age_ms, bool) or not isinstance(age_ms, int) or age_ms <= 0:
            raise ValueError(f"{_AGE_KEY} must be a positive int")
        if not callable(clock):
            raise TypeError("clock must be callable")
        if not callable(getattr(adapter, "leverage_brackets_snapshot", None)):
            raise TypeError("adapter must offer leverage_brackets_snapshot")
        self._adapter = adapter
        self._clock = clock
        self._max_age = age_ms * _ONE_MS
        self._readings: dict[str, BracketReading] = {}
        self._epoch = 0
        self._symbol_epochs: dict[str, int] = {}
        self._last_error_type: str | None = None

    @property
    def last_error_type(self) -> str | None:
        """Type name of the last failed get; None after a success. Never a message."""
        return self._last_error_type

    def _token(self, symbol: str) -> tuple[int, int]:
        return (self._epoch, self._symbol_epochs.get(symbol, 0))

    async def get(self, *, symbol: str) -> BracketReading | None:
        """The fresh brackets of ``symbol``: cached, or read once from the exchange; else None.

        A cached reading is returned only while it is fresh under the owner's bound. Otherwise
        the adapter is read exactly once (never retried), the reading is stamped with the clock
        value taken before the request and checked again against the clock after the await.
        Every failure drops the cached reading of the symbol and returns None (no stale fallback).
        """
        _require_symbol(symbol)
        try:
            cached = self._readings.get(symbol)
            if cached is not None:
                if brackets_are_fresh(
                    observed_at_utc=cached.observed_at_utc,
                    now_utc=self._clock(),
                    max_age=self._max_age,
                ):
                    return cached
                self._readings.pop(symbol, None)
            token = self._token(symbol)
            observed = self._clock()
            table = await self._adapter.leverage_brackets_snapshot(symbol=symbol)
            reading = _reading_from_table(table, symbol, observed)
            if not brackets_are_fresh(
                observed_at_utc=observed, now_utc=self._clock(), max_age=self._max_age
            ):
                self._readings.pop(symbol, None)
                self._last_error_type = _STALE_LABEL
                return None
        except Exception as exc:  # noqa: BLE001 - any failed read is "no brackets", fail closed
            self._readings.pop(symbol, None)
            self._last_error_type = type(exc).__name__
            return None
        self._last_error_type = None
        if token != self._token(symbol):
            return None
        self._readings[symbol] = reading
        return reading

    def invalidate(self, *, symbol: str | None = None) -> None:
        """Drop the reading of ``symbol`` (or all readings when None).

        A read of the affected symbol that is in flight is discarded when it returns: it may
        predate the change that caused the invalidation.
        """
        if symbol is None:
            self._epoch += 1
            self._readings.clear()
            return
        name = _require_symbol(symbol)
        self._symbol_epochs[name] = self._symbol_epochs.get(name, 0) + 1
        self._readings.pop(name, None)


__all__ = ["BracketCache", "BracketPort", "BracketReading"]
