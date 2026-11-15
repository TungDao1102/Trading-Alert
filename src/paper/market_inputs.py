"""Market inputs of the live paper loop (Phase 16, plan 16-26; D-35, Q-G folded into O-07).

What the per-bar tick needs from outside the candle stream, and where each value comes from:

- exchange constraints (tick, step, minimum quantity, minimum notional): only from the public
  `exchangeInfo`, never hard-coded (AGENTS.md exchange authority);
- the refresh cadence and the time-to-live of a constraint snapshot: only from the ratified
  runtime configuration;
- the account inputs: the risk rate from the ratified configuration; the equity to size with and
  the absolute portfolio thresholds from the required `RiskInputsProvider` port, i.e. the SHADOW
  ledger as of the bar close (16-DEC-EQUITY-BASE; the configured initial equity only starts the
  ledger, in `build_coordinator`);
- open positions and the daily loss: through the same port. This module holds NO default
  implementation of the port; plan 16-31 binds it to the SHADOW ledger.

The module never reads the wall clock: every time arrives through the injected clock.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

import structlog

from src.adapters.binance_public import Kline as RestKline
from src.adapters.binance_public import SymbolFilters
from src.backtest.costs import build_cost_model, cost_slice
from src.core.types import AccountState, Candle
from src.domain.registry import ParameterSet
from src.paper.loop import BarContext
from src.paper.runtime_config import AccountConfig
from src.paper.vocabulary import INTERVAL_MS, SourceTag, TaggedBar
from src.risk.types import ConstraintSnapshot, OpenPosition

log = structlog.get_logger()

_UNIX_ORIGIN = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_MS = timedelta(milliseconds=1)

SIBLING_INTERVAL = "4h"

# Constraint snapshots kept per symbol, newest last. An implementation value, NOT a threshold:
# it only bounds memory. A bar older than every retained snapshot is judged with the earliest
# retained one, which is observed after the bar closed and therefore fails closed as stale.
_SNAPSHOTS_PER_SYMBOL = 64


class PublicDataLike(Protocol):
    """The credential-free public adapter surface the loop uses (`BinancePublicMarketData`)."""

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[RestKline]: ...

    async def server_time(self) -> datetime: ...

    async def exchange_info(self, symbols: Sequence[str] | None = None) -> list[SymbolFilters]: ...


class RiskInputsProvider(Protocol):
    """Portfolio state at an instant (required port; D-17, plan 16-31, 16-DEC-EQUITY-BASE).

    There is deliberately NO implementation in src: plan 16-31 binds this port to the SHADOW
    ledger, and a stub here would let a run decide with invented portfolio state.
    """

    def open_positions(self, at_utc: datetime) -> Sequence[OpenPosition]: ...

    def daily_loss_quote(self, at_utc: datetime) -> Decimal | None: ...

    def equity_and_thresholds(self, at_utc: datetime) -> tuple[Decimal, dict[str, Any]]:
        """The equity to size with and the absolute portfolio thresholds, both from the SHADOW
        ledger as of `at_utc` (the thresholds resolved against the UTC day-start equity)."""
        ...


class ConstraintsUnavailable(Exception):
    """No usable exchange constraint snapshot exists (never replaced by an invented one)."""


class ConstraintProvider:
    """Exchange constraints per configured symbol, from the public `exchangeInfo` only.

    `refresh` is all-or-nothing: if any configured symbol is missing from the exchange answer, no
    snapshot is stored and the error propagates, so a half-updated universe never exists. Each
    stored snapshot is stamped with the injected clock read BEFORE the request (an age can then
    only be over-, never under-estimated). `snapshot_for` is point-in-time like the backtest: the
    snapshot a bar is judged with is the latest one observed at or before the bar's close. The
    time-to-live is not applied here: it travels in the `BarContext` and `evaluate_risk` turns an
    old (or future-dated) snapshot into the existing STALE_CONSTRAINTS verdict.

    Thread-safety: `refresh` runs on the event loop, `snapshot_for` in the tick's worker thread.
    """

    def __init__(
        self,
        *,
        public: PublicDataLike,
        symbols: Sequence[str],
        clock: Callable[[], datetime],
    ) -> None:
        self._public = public
        self._symbols = tuple(symbols)
        self._clock = clock
        self._lock = threading.Lock()
        self._history: dict[str, list[ConstraintSnapshot]] = {s: [] for s in self._symbols}

    async def refresh(self) -> None:
        observed_at = self._clock()
        # Only the configured symbols are validated strictly (B1-WR-12): drift of a contract the
        # runtime does not trade cannot stop the refresh, a bad configured one still fails it.
        rows = {row.symbol: row for row in await self._public.exchange_info(self._symbols)}
        built: dict[str, ConstraintSnapshot] = {}
        for symbol in self._symbols:
            row = rows.get(symbol)
            if row is None:
                raise ConstraintsUnavailable(f"exchangeInfo does not list {symbol}")
            built[symbol] = ConstraintSnapshot(
                symbol=symbol,
                price_tick_size=row.price_tick_size,
                quantity_step_size=row.quantity_step_size,
                min_quantity=row.min_quantity,
                min_notional=row.min_notional,
                metadata_observed_at_utc=observed_at,
            )
        with self._lock:
            for symbol, snapshot in built.items():
                history = self._history[symbol]
                history.append(snapshot)
                del history[:-_SNAPSHOTS_PER_SYMBOL]

    def snapshot_for(self, symbol: str, at_utc: datetime) -> ConstraintSnapshot:
        with self._lock:
            history = list(self._history.get(symbol, ()))
        if not history:
            raise ConstraintsUnavailable(f"no exchange constraint snapshot exists for {symbol}")
        for snapshot in reversed(history):
            if snapshot.metadata_observed_at_utc <= at_utc:
                return snapshot
        return history[0]


async def refresh_forever(
    provider: ConstraintProvider,
    *,
    every: timedelta,
    sleep: Callable[[timedelta], Awaitable[None]],
) -> None:
    """Refresh the constraints every `every` until cancelled; a failure keeps the old snapshot.

    A failed refresh is logged and retried at the next period. Nothing is substituted: the old
    snapshot simply ages, and once it is older than the time-to-live the tick rejects with
    STALE_CONSTRAINTS.
    """
    while True:
        await sleep(every)
        try:
            await provider.refresh()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("paper.market_inputs.refresh_failed", error=type(exc).__name__)


def make_context_factory(
    *,
    parameter_set: ParameterSet,
    constraints: ConstraintProvider,
    risk_inputs: RiskInputsProvider,
    account: AccountConfig,
    ttl_seconds: int,
) -> Callable[[Candle], BarContext]:
    """The `context_factory` of the bar pipeline (plan 16-24): one `BarContext` per 1h bar.

    The cost model is the registry slice of the pinned parameter set (the same source
    `run_paper_tick` binds). The risk rate comes from the ratified configuration (never defaulted
    here). The equity to size with and the absolute portfolio thresholds, the open positions and
    the daily loss come from the required `risk_inputs` port, asked at the bar close: the SHADOW
    ledger as the backtest engine reads it (16-DEC-EQUITY-BASE), so sizing, the signal-time gates
    and the CONFIRM-time gates judge the same numbers.
    """
    cost_model = build_cost_model(cost_slice(parameter_set.params))
    ttl = timedelta(seconds=ttl_seconds)

    def factory(candle: Candle) -> BarContext:
        close = candle.close_time_utc
        equity, thresholds = risk_inputs.equity_and_thresholds(close)
        account_state = AccountState(equity=equity, risk_rate=account.risk_rate)
        return BarContext(
            symbol=candle.symbol,
            strategy_version=parameter_set.strategy_version,
            parameter_set=parameter_set,
            account_state=account_state,
            constraint_snapshot=constraints.snapshot_for(candle.symbol, close),
            cost_model=cost_model,
            open_positions=tuple(risk_inputs.open_positions(close)),
            daily_loss_quote=risk_inputs.daily_loss_quote(close),
            ttl=ttl,
            absolute_thresholds=thresholds,
        )

    return factory


async def measure_clock_skew(public: PublicDataLike, clock: Callable[[], datetime]) -> int:
    """Host clock minus Binance server time, in whole milliseconds (D-35: logged, no threshold).

    The host time is the midpoint of two injected-clock readings around the single server-time
    request, so the request latency does not masquerade as skew. Positive: the host runs ahead.
    A host running behind (negative) is what drops closed bars as FUTURE_CLOSE (research P20).
    """
    before = clock()
    server = await public.server_time()
    after = clock()
    midpoint = before + (after - before) // 2
    return (midpoint - server) // _ONE_MS


def _to_ms(moment: datetime) -> int:
    """Whole milliseconds since the Unix epoch (exact integer arithmetic)."""
    return (moment.astimezone(UTC) - _UNIX_ORIGIN) // _ONE_MS


def make_sibling_fetcher(
    public: PublicDataLike, loop: asyncio.AbstractEventLoop
) -> Callable[[str, datetime], TaggedBar | None]:
    """The synchronous `fetch_4h_bar(symbol, close)` the bar pipeline needs (plan 16-24).

    The pipeline runs in a worker thread (`asyncio.to_thread`), so the fetch hands the async REST
    call to the event loop and waits for it; the loop thread is never blocked by it. It returns
    the closed 4h bar ending exactly at `close_time_utc`, or None when the exchange has no such
    closed candle (flag-never-fabricate: nothing is invented).
    """
    step = timedelta(milliseconds=INTERVAL_MS[SIBLING_INTERVAL])

    def fetch(symbol: str, close_time_utc: datetime) -> TaggedBar | None:
        open_time = close_time_utc + _ONE_MS - step
        rows = asyncio.run_coroutine_threadsafe(
            public.klines(
                symbol,
                SIBLING_INTERVAL,
                start_ms=_to_ms(open_time),
                end_ms=_to_ms(close_time_utc),
                limit=2,
            ),
            loop,
        ).result()
        for row in rows:
            if row.open_time_utc == open_time and row.close_time_utc == close_time_utc:
                return TaggedBar(
                    symbol=symbol,
                    interval=SIBLING_INTERVAL,
                    open_time_utc=row.open_time_utc,
                    close_time_utc=row.close_time_utc,
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    volume=row.volume,
                    source=SourceTag.REST_BACKFILL,
                )
        return None

    return fetch


__all__ = [
    "ConstraintProvider",
    "ConstraintsUnavailable",
    "PublicDataLike",
    "RiskInputsProvider",
    "make_context_factory",
    "make_sibling_fetcher",
    "measure_clock_skew",
    "refresh_forever",
]
