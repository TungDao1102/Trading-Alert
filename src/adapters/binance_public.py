"""Binance USD-M public market data (no orders, no account, no credentials).

Public market data only; constructs no order adapter and holds no credentials (SC6, D-13,
D040). The SHADOW runtime imports this module instead of `src.adapters.binance_usdm`, so a
process that must never place an order never loads the order adapter (phase 16, plan 16-03).

This module is, with `src/adapters/binance_usdm.py`, one of the project modules allowed to
import the `binance-sdk-derivatives-trading-usds-futures` package. SDK response models never
leave it: callers receive the frozen dataclasses below.

Dataclass conventions (unchanged from the order adapter this surface was split from):
  - Prices and quantities are `Decimal` (no float for exchange-sensitive values).
  - Timestamps are `datetime` with `tzinfo=UTC` (D-06).
  - Every dataclass is `frozen=True`.

When no `sdk_client` is passed, the SDK REST client is built from an explicit configuration
with no API key and no API secret. Nothing here reads the process environment. The public
endpoints are unsigned, so a signed request cannot originate from this class.

Optional REST rate-limit gate (plan 18-10): `BinancePublicMarketData(..., rest_gate=gate)`
runs `gate.check()` before each of its delegated REST calls (so a 418 ban or a 429
pause of the process refuses them without sending) and records a 418 or 429 it meets in the
gate, then re-raises the original exception; nothing is retried. `BinanceUsdmAdapter` passes
its own gate, so its public delegations, including `server_time` (the drift guard's time
source), are refused too. With the default `rest_gate=None` the behavior is unchanged (the
data jobs, the paper runtime and the Phase 16 scripts stay ungated in Phase 18, a known gap).

Project transport errors (plan 16-56, B1-WR-06, D-13 boundary): with
`project_transport_errors=True` (the paper runtime's composition root sets it) the REST calls of
the paper path (`klines`, `mark_klines` and the call behind `exchange_info`) turn an SDK server
or network error into `TransientMarketDataError` and an SDK rate-limit (429) or ban (418) error
into `MarketDataRateLimited` (`MarketDataRateLimitBan` for a ban), which is NOT transient: a
caller must never retry it at once. Each carries the SDK class name only, never a response body
or a URL, so `src/paper` never names an SDK type. The gate (above) still sees the SDK exception
first. Any other SDK error (an unknown symbol, for example) passes through unchanged. The default
(False) keeps the SDK types for the order adapter, the probe and the data jobs, whose error
taxonomy (`src/adapters/binance_errors.py`) classifies the SDK classes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

import structlog
from binance_common.configuration import ConfigurationRestAPI
from binance_common.errors import (
    NetworkError,
    RateLimitBanError,
    ServerError,
    TooManyRequestsError,
)
from binance_sdk_derivatives_trading_usds_futures import DerivativesTradingUsdsFutures
from src.adapters.binance_errors import error_facts_from_exception
from src.adapters.binance_ratelimit_gate import RestRateLimitGate
from src.domain.exchange_errors import CallKind, ExchangeErrorCategory, classify

log = structlog.get_logger()

if TYPE_CHECKING:
    from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
        ExchangeInformationResponse,
        ExchangeInformationResponseSymbolsInnerFiltersInner,
        GetFundingRateHistoryResponseInner,
        OpenInterestResponse,
    )

# --------------------------------------------------------------------------- #
# Frozen domain dataclasses — the public contract of this adapter.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Kline:
    """One kline row, normalized to project types.

    `close_time_utc <= now_utc` is the invariant callers MUST enforce before
    accepting a kline (RESEARCH §Pitfall 1 — never include the forming candle).
    """

    symbol: str
    interval: str
    open_time_utc: datetime
    close_time_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal
    trade_count: int


@dataclass(frozen=True)
class MarkKline:
    """One mark-price kline row (`GET /fapi/v1/markPriceKlines`), normalized.

    The exchange row carries volume and quote volume fields that are always
    "0" and a field 8 that is the number of mark-price UPDATES in the bar, not
    a trade count. Neither is a trade statistic, so this type has no volume or
    trade_count field and the update count is named `price_tick_count`
    (D-11, D-29). Same closed-candle invariant as `Kline`.
    """

    symbol: str
    interval: str
    open_time_utc: datetime
    close_time_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    price_tick_count: int


@dataclass(frozen=True)
class OiSnapshot:
    """One open-interest observation for a symbol.

    `source` distinguishes canonical day-one polling snapshots from
    opportunistic historical harvests (D-08). Allowed values:
      - "canonical"  — produced by the live 5-minute poll loop
      - "research"   — produced by the opportunistic openInterestHist
                       harvest at bootstrap; never relied upon as the
                       forward source
    """

    symbol: str
    observed_at_utc: datetime
    open_interest: Decimal
    source: str = "canonical"


@dataclass(frozen=True)
class MarkPriceReading:
    """One live mark price of one symbol (`GET /fapi/v1/premiumIndex`, plan 19-05, D-06).

    `exchange_time_utc` is the `time` field of the response (Binance's clock). The adapter
    takes no clock: the caller measures the age of the reading with its own injected clock.
    """

    symbol: str
    mark_price: Decimal
    exchange_time_utc: datetime


@dataclass(frozen=True)
class OrderBookReading:
    """The top of one symbol's order book (`GET /fapi/v1/depth`, quick task 261022-sj1).

    `bids` and `asks` are (price, quantity) pairs as the exchange lists them (best first),
    every value a positive finite `Decimal`. Used only by the Demo probe to read how much
    quantity the book holds; no decision path reads it.
    """

    symbol: str
    last_update_id: int
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]


@dataclass(frozen=True)
class LastPriceReading:
    """The latest traded price of one symbol (`GET /fapi/v1/ticker/price`, quick task 261020-l4p).

    "Symbol Price Ticker" answers `{symbol, price, time}` for one symbol. `last_price` is its
    `price` field and `exchange_time_utc` its `time` field (Binance's clock, the time of the last
    trade). The adapter takes no clock: the caller measures the age with its own injected clock.
    """

    symbol: str
    last_price: Decimal
    exchange_time_utc: datetime


@dataclass(frozen=True)
class FundingTick:
    """One funding-rate observation."""

    symbol: str
    funding_time_utc: datetime
    funding_rate: Decimal
    mark_price: Decimal | None = None


@dataclass(frozen=True)
class SymbolFilters:
    """Snapshot of the exchangeInfo filters for one symbol.

    Decimals for all numeric filter fields (Pitfall 4 — no float). The
    raw filter list and full symbol record are retained as JSON blobs so
    later plans (position-mode, leverage brackets) can pull additional
    fields without re-querying.
    """

    symbol: str
    contract_type: str
    status: str
    onboard_time_utc: datetime | None
    price_tick_size: Decimal
    quantity_step_size: Decimal
    min_quantity: Decimal
    max_quantity: Decimal | None
    min_notional: Decimal
    base_asset: str
    quote_asset: str
    margin_asset: str
    notional_constraints_json: str
    order_capabilities_json: str
    position_mode_snapshot_json: str
    # exchangeInfo `deliveryDate` (ms epoch). Perpetuals in TRADING carry the
    # far-future sentinel 4133404800000, passed through unchanged; consumers
    # decide what is "past". Optional trailing field: no PostgreSQL migration and
    # no symbol_metadata column (D-26).
    delivery_date_ms: int | None = None
    # MARKET_LOT_SIZE and PERCENT_PRICE (Phase 17, EXEC-04 / D-18). Optional trailing
    # fields: no PostgreSQL migration and no symbol_metadata column (research C10).
    # None means the exchange did not publish the filter (never a fabricated default);
    # the per-plan constraint snapshot renders None as the UNKNOWN sentinel.
    market_lot_min_quantity: Decimal | None = None
    market_lot_max_quantity: Decimal | None = None
    market_lot_step_size: Decimal | None = None
    percent_price_multiplier_up: Decimal | None = None
    percent_price_multiplier_down: Decimal | None = None
    percent_price_multiplier_decimals: int | None = None


# --------------------------------------------------------------------------- #
# Helper conversions.
# --------------------------------------------------------------------------- #


def _ms_to_utc(ms: int) -> datetime:
    """Convert a millisecond Unix epoch to a tz-aware UTC datetime."""
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def _row_to_kline(symbol: str, interval: str, row: Sequence[Any]) -> Kline:
    """Map one raw kline list (12-field tuple) to a `Kline`.

    Per Binance docs the order is:
        0  open_time                int ms
        1  open                     str Decimal
        2  high                     str Decimal
        3  low                      str Decimal
        4  close                    str Decimal
        5  volume                   str Decimal
        6  close_time               int ms
        7  quote_asset_volume       str Decimal
        8  number_of_trades         int
        9  taker_buy_base_volume    str Decimal
        10 taker_buy_quote_volume   str Decimal
        11 ignore                   str
    """
    if len(row) < 9:
        raise ValueError(f"kline row too short ({len(row)} cols): {row!r}")
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time_utc=_ms_to_utc(int(row[0])),
        close_time_utc=_ms_to_utc(int(row[6])),
        open=Decimal(str(row[1])),
        high=Decimal(str(row[2])),
        low=Decimal(str(row[3])),
        close=Decimal(str(row[4])),
        volume=Decimal(str(row[5])),
        quote_volume=Decimal(str(row[7])),
        trade_count=int(row[8]),
    )


def _row_to_mark_kline(symbol: str, interval: str, row: Sequence[Any]) -> MarkKline:
    """Map one raw markPriceKlines list (12-field row) to a `MarkKline`.

    Same 12-field layout as a trade kline, but fields 5 and 7 (volume, quote
    volume) are always "0" and field 8 is a mark-price update count. Only
    fields 0-4, 6 and 8 are read; 5 and 7 are ignored by design (D-29).
    """
    if len(row) < 9:
        raise ValueError(f"mark kline row too short ({len(row)} cols): {row!r}")
    return MarkKline(
        symbol=symbol,
        interval=interval,
        open_time_utc=_ms_to_utc(int(row[0])),
        close_time_utc=_ms_to_utc(int(row[6])),
        open=Decimal(str(row[1])),
        high=Decimal(str(row[2])),
        low=Decimal(str(row[3])),
        close=Decimal(str(row[4])),
        price_tick_count=int(row[8]),
    )


# --------------------------------------------------------------------------- #
# REST rate-limit gate plumbing (plan 18-10), shared with the order adapter.
# --------------------------------------------------------------------------- #

_RATE_LIMIT_CATEGORIES: frozenset[ExchangeErrorCategory] = frozenset(
    {ExchangeErrorCategory.IP_BANNED, ExchangeErrorCategory.RATE_LIMITED}
)


def _record_rate_limit(
    gate: RestRateLimitGate | None, exc: BaseException, call_kind: CallKind
) -> None:
    """Record a 418 or 429 met by a REST call in the shared gate; any other error is left alone.

    The decision uses the SDK class, the int code and the Retry-After seconds only (never
    message text). The caller re-raises the original exception: nothing is retried.
    """
    if gate is None:
        return
    facts = error_facts_from_exception(exc)
    category = classify(facts, call_kind)
    if category in _RATE_LIMIT_CATEGORIES:
        gate.record(
            category,
            facts.retry_after_seconds,
            ban_until_epoch_ms=facts.ban_until_epoch_ms,
        )


def _book_levels(raw: object, side: str, symbol: str) -> tuple[tuple[Decimal, Decimal], ...]:
    """The (price, quantity) levels of one depth side; any malformed level raises ValueError."""
    if not isinstance(raw, list):
        raise ValueError(f"depth {side} missing for {symbol}")
    levels: list[tuple[Decimal, Decimal]] = []
    for level in raw:
        if not isinstance(level, list) or len(level) < 2:
            raise ValueError(f"depth {side} level malformed for {symbol}")
        try:
            price, quantity = Decimal(level[0]), Decimal(level[1])
        except (InvalidOperation, TypeError):
            raise ValueError(f"depth {side} level is not a decimal pair for {symbol}") from None
        if not (price.is_finite() and quantity.is_finite()) or price <= 0 or quantity <= 0:
            raise ValueError(f"depth {side} level is not positive and finite for {symbol}")
        levels.append((price, quantity))
    return tuple(levels)


async def _gated_rest_call[**P, R](
    gate: RestRateLimitGate | None,
    call_kind: CallKind,
    func: Callable[P, R],
    *args: P.args,
    **kwargs: P.kwargs,
) -> R:
    """One REST call in a worker thread: gate check first, gate record of a 418 or 429.

    Without a gate this is exactly `asyncio.to_thread(func, *args, **kwargs)`.
    """
    if gate is not None:
        gate.check()
    try:
        return await asyncio.to_thread(func, *args, **kwargs)
    except Exception as exc:
        _record_rate_limit(gate, exc, call_kind)
        raise


# --------------------------------------------------------------------------- #
# Project error types for the SDK's transport errors (plan 16-56, B1-WR-06).
# --------------------------------------------------------------------------- #


class TransientMarketDataError(Exception):
    """A Binance server (5xx) or network error of a public call: one immediate retry is allowed.

    The message is the SDK class name only (never a response body or a URL).
    """


class MarketDataRateLimited(Exception):
    """A Binance rate-limit answer (429): NOT transient, never retried at once.

    The message is the SDK class name only; `retry_after` is the `Retry-After` header in whole
    seconds when Binance sent one.
    """

    def __init__(self, sdk_error_name: str, retry_after: int | None = None) -> None:
        super().__init__(sdk_error_name)
        self.retry_after = retry_after


class MarketDataRateLimitBan(MarketDataRateLimited):
    """A Binance IP ban (418): requests sent while banned extend the ban, so a caller stops."""


def _project_transport_error(exc: Exception) -> Exception | None:
    """The project error for an SDK transport error, or None to re-raise `exc` unchanged."""
    name = type(exc).__name__
    if isinstance(exc, ServerError | NetworkError):
        return TransientMarketDataError(name)
    if isinstance(exc, RateLimitBanError):
        return MarketDataRateLimitBan(name, exc.retry_after)
    if isinstance(exc, TooManyRequestsError):
        return MarketDataRateLimited(name, exc.retry_after)
    return None


# --------------------------------------------------------------------------- #
# Adapter — public market data only.
# --------------------------------------------------------------------------- #


def _credential_free_client() -> DerivativesTradingUsdsFutures:
    """SDK client whose REST configuration carries no API key and no API secret."""
    return DerivativesTradingUsdsFutures(
        config_rest_api=ConfigurationRestAPI(api_key=None, api_secret=None)
    )


class BinancePublicMarketData:
    """Public Binance USD-M market data behind project-owned types.

    Tests inject a fake `sdk_client` (any object exposing `rest_api.kline_candlestick_data`
    etc.) so unit tests never touch the network. The order adapter passes its own client in,
    so one client serves both surfaces there; the SHADOW runtime passes nothing and gets a
    credential-free client.

    `rest_gate` (optional, keyword only) is the process-wide `RestRateLimitGate`: when set,
    every delegated REST call is refused during a 418 ban or a 429 pause and a 418 or 429 it
    meets is recorded in the gate. None (the default) leaves the reader ungated.

    `project_transport_errors` (optional, keyword only, plan 16-56): when True, `klines`,
    `mark_klines` and `exchange_info` raise the project errors of this module instead of the
    SDK's server, network, rate-limit and ban errors (see the module docstring).
    """

    def __init__(
        self,
        sdk_client: DerivativesTradingUsdsFutures | None = None,
        *,
        rest_gate: RestRateLimitGate | None = None,
        project_transport_errors: bool = False,
    ) -> None:
        self._sdk: DerivativesTradingUsdsFutures = (
            sdk_client if sdk_client is not None else _credential_free_client()
        )
        self._rest_gate = rest_gate
        self._project_errors = project_transport_errors

    async def _paper_path_call[**P, R](
        self, func: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs
    ) -> R:
        """One gated QUERY call of the paper path, with the opt-in project transport errors."""
        try:
            return await _gated_rest_call(self._rest_gate, CallKind.QUERY, func, *args, **kwargs)
        except Exception as exc:
            mapped = _project_transport_error(exc) if self._project_errors else None
            if mapped is None:
                raise
            raise mapped from None

    # ----- klines ---------------------------------------------------------- #

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]:
        """Fetch one page of klines. Always returns the raw list shape
        (a list of 12-field lists) projected to `Kline` instances.

        `start_ms` / `end_ms` are inclusive open-time bounds per Binance
        docs (verified at implementation time against installed SDK).

        The underlying SDK call is synchronous (returns `ApiResponse`
        directly); we run it in a worker thread so the async paginator
        can interleave multiple pages across symbols without blocking.
        """
        response = await self._paper_path_call(
            self._sdk.rest_api.kline_candlestick_data,
            symbol=symbol,
            interval=interval,  # type: ignore[arg-type]
            start_time=start_ms,
            end_time=end_ms,
            limit=limit,
        )
        # `data()` is a list[list[Any]] — see exchange_info_sample pattern.
        raw = response.data()
        return [_row_to_kline(symbol, interval, row) for row in raw]

    async def mark_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[MarkKline]:
        """Fetch one page of mark-price klines (`GET /fapi/v1/markPriceKlines`).

        Facts re-verified 2026-09-30 (see 13-04-SUMMARY): limit default 500,
        max 1500; weight 1 / 2 / 5 / 10 for limit <1-99 / 100-499 / 500-1000 /
        >1000; rows are 12-field lists with volume "0" (D-29). Runs in a worker
        thread like `klines`; SDK types never leave this module.
        """
        response = await self._paper_path_call(
            self._sdk.rest_api.mark_price_kline_candlestick_data,
            symbol=symbol,
            interval=interval,  # type: ignore[arg-type]
            start_time=start_ms,
            end_time=end_ms,
            limit=limit,
        )
        raw = response.data()
        return [_row_to_mark_kline(symbol, interval, row) for row in raw]

    # ----- live mark price ------------------------------------------------- #

    async def order_book(self, symbol: str, limit: int) -> OrderBookReading:
        """The top `limit` levels of one symbol's book (`GET /fapi/v1/depth`, unsigned).

        Flag-never-fabricate (D-06): an empty answer, a missing side or update id, or a level
        that is not a (positive finite price, positive finite quantity) pair raises
        `ValueError`. No retry; an SDK exception propagates unchanged. Messages name the field
        and the symbol only (never the payload).
        """
        response = await _gated_rest_call(
            self._rest_gate,
            CallKind.QUERY,
            self._sdk.rest_api.order_book,
            symbol=symbol,
            limit=limit,
        )
        raw = response.data()
        if raw is None:
            raise ValueError(f"depth response empty for {symbol}: refusing to fabricate")
        update_id = raw.last_update_id
        if isinstance(update_id, bool) or not isinstance(update_id, int):
            raise ValueError(f"depth lastUpdateId missing for {symbol}")
        return OrderBookReading(
            symbol=symbol,
            last_update_id=update_id,
            bids=_book_levels(raw.bids, "bids", symbol),
            asks=_book_levels(raw.asks, "asks", symbol),
        )

    async def mark_price(self, symbol: str) -> MarkPriceReading:
        """The live mark price of one symbol (`GET /fapi/v1/premiumIndex`).

        Flag-never-fabricate (D-06): an empty response, a list instead of one symbol, a
        missing or non-finite or non-positive `markPrice`, a missing `time` or another symbol
        raises `ValueError`. No retry, no fallback value; an SDK exception propagates
        unchanged. Messages name the field and the symbol only (never the payload).
        """
        response = await _gated_rest_call(
            self._rest_gate, CallKind.QUERY, self._sdk.rest_api.mark_price, symbol=symbol
        )
        wrapper = response.data()
        if wrapper is None:
            raise ValueError(f"premiumIndex response empty for {symbol}: refusing to fabricate")
        raw = getattr(wrapper, "actual_instance", None)
        if raw is None or isinstance(raw, list):
            raise ValueError(
                f"premiumIndex response for {symbol} is not a single-symbol answer: "
                "refusing to fabricate a mark price"
            )
        if raw.symbol is None or raw.symbol != symbol:
            raise ValueError(
                f"premiumIndex response symbol does not match requested {symbol}: "
                "refusing to use another symbol's mark price"
            )
        text = raw.mark_price
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"premiumIndex markPrice missing for {symbol}")
        try:
            price = Decimal(text)
        except InvalidOperation:
            raise ValueError(f"premiumIndex markPrice is not a decimal for {symbol}") from None
        if not price.is_finite() or price <= 0:
            raise ValueError(f"premiumIndex markPrice is not a positive finite price for {symbol}")
        time_ms = raw.time
        if isinstance(time_ms, bool) or not isinstance(time_ms, int):
            raise ValueError(f"premiumIndex time missing for {symbol}")
        seconds, millis = divmod(time_ms, 1000)
        observed = datetime.fromtimestamp(seconds, tz=UTC) + timedelta(milliseconds=millis)
        return MarkPriceReading(symbol=symbol, mark_price=price, exchange_time_utc=observed)

    # ----- live last price (quick task 261020-l4p) -------------------------- #

    async def last_price(self, symbol: str) -> LastPriceReading:
        """The latest traded price of one symbol (`GET /fapi/v1/ticker/price`, weight 1).

        The SDK method is `symbol_price_ticker` (Symbol Price Ticker); it is always called WITH
        the symbol, so the answer is one `{symbol, price, time}` object, never the all-symbols
        list. Flag-never-fabricate, like `mark_price`: an empty response, a list, a missing or
        non-finite or non-positive `price`, a missing `time` or another symbol raises
        `ValueError`. No retry, no fallback value (the mark price is never substituted); an SDK
        exception propagates unchanged. Messages name the field and the symbol only.
        """
        response = await _gated_rest_call(
            self._rest_gate, CallKind.QUERY, self._sdk.rest_api.symbol_price_ticker, symbol=symbol
        )
        wrapper = response.data()
        if wrapper is None:
            raise ValueError(f"ticker/price response empty for {symbol}: refusing to fabricate")
        raw = getattr(wrapper, "actual_instance", None)
        if raw is None or isinstance(raw, list):
            raise ValueError(
                f"ticker/price response for {symbol} is not a single-symbol answer: "
                "refusing to fabricate a last price"
            )
        if raw.symbol is None or raw.symbol != symbol:
            raise ValueError(
                f"ticker/price response symbol does not match requested {symbol}: "
                "refusing to use another symbol's last price"
            )
        text = raw.price
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"ticker/price price missing for {symbol}")
        try:
            price = Decimal(text)
        except InvalidOperation:
            raise ValueError(f"ticker/price price is not a decimal for {symbol}") from None
        if not price.is_finite() or price <= 0:
            raise ValueError(f"ticker/price price is not a positive finite price for {symbol}")
        time_ms = raw.time
        if isinstance(time_ms, bool) or not isinstance(time_ms, int):
            raise ValueError(f"ticker/price time missing for {symbol}")
        seconds, millis = divmod(time_ms, 1000)
        observed = datetime.fromtimestamp(seconds, tz=UTC) + timedelta(milliseconds=millis)
        return LastPriceReading(symbol=symbol, last_price=price, exchange_time_utc=observed)

    # ----- open interest --------------------------------------------------- #

    async def open_interest(self, symbol: str) -> OiSnapshot:
        response = await _gated_rest_call(
            self._rest_gate, CallKind.QUERY, self._sdk.rest_api.open_interest, symbol=symbol
        )
        oi: OpenInterestResponse = response.data()
        # Flag-never-fabricate (D-09): a missing timestamp or measurement
        # must surface loudly, never become epoch-0 or a plausible zero.
        if oi.time is None or oi.open_interest is None:
            raise ValueError(f"open_interest response missing fields: {oi!r}")
        return OiSnapshot(
            symbol=oi.symbol or symbol,
            observed_at_utc=_ms_to_utc(int(oi.time)),
            open_interest=Decimal(str(oi.open_interest)),
        )

    async def open_interest_statistics(
        self,
        symbol: str,
        period: str,
        limit: int = 30,
    ) -> list[OiSnapshot]:
        """Opportunistic historical OI harvest (D-08).

        Per Binance docs the response is a list of `{symbol, sum_open_interest,
        sum_open_interest_value, cmc_circulating_supply, timestamp}` rows.
        Only the latest ~30 days are available — this is NOT the forward
        source. Each returned `OiSnapshot` carries `source="research"` so
        downstream consumers can distinguish from canonical day-one
        snapshots.
        """
        response = await _gated_rest_call(
            self._rest_gate,
            CallKind.QUERY,
            self._sdk.rest_api.open_interest_statistics,
            symbol=symbol,
            period=period,  # type: ignore[arg-type]
            limit=limit,
        )
        raw = response.data()
        out: list[OiSnapshot] = []
        for item in raw or []:
            ts = getattr(item, "timestamp", None)
            oi = getattr(item, "sum_open_interest", None)
            # Same strictness as open_interest/funding_rate: a malformed
            # harvest row raises loudly, never drops silently (D-09).
            if ts is None or oi is None:
                raise ValueError(f"open_interest_statistics row missing fields: {item!r}")
            out.append(
                OiSnapshot(
                    symbol=getattr(item, "symbol", None) or symbol,
                    observed_at_utc=_ms_to_utc(int(ts)),
                    open_interest=Decimal(str(oi)),
                    source="research",
                )
            )
        return out

    # ----- funding rate ---------------------------------------------------- #

    async def funding_rate(
        self,
        symbol: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1000,
    ) -> list[FundingTick]:
        response = await _gated_rest_call(
            self._rest_gate,
            CallKind.QUERY,
            self._sdk.rest_api.get_funding_rate_history,
            symbol=symbol,
            start_time=start_ms,
            end_time=end_ms,
            limit=limit,
        )
        raw = response.data()
        # The stub types `data()` as the single response model, but array
        # endpoints return a list at runtime (`is_array` models) — unwrap
        # defensively instead of casting.
        rows: list[GetFundingRateHistoryResponseInner] = raw if isinstance(raw, list) else [raw]
        out: list[FundingTick] = []
        for item in rows:
            # Same strictness as open_interest: skip-and-raise, never
            # default a missing timestamp/rate to epoch-0 or zero.
            if item.funding_time is None or item.funding_rate is None:
                raise ValueError(f"funding_rate row missing fields: {item!r}")
            resolved_symbol = item.symbol or symbol
            if not resolved_symbol:
                raise ValueError(f"funding_rate row missing symbol: {item!r}")
            out.append(
                FundingTick(
                    symbol=resolved_symbol,
                    funding_time_utc=_ms_to_utc(int(item.funding_time)),
                    funding_rate=Decimal(str(item.funding_rate)),
                    # Historical funding rows can carry markPrice "" (Pitfall 9).
                    # Only the empty string maps to None; any other malformed
                    # value still raises in Decimal() -- never fabricated as 0.
                    mark_price=(
                        Decimal(str(item.mark_price))
                        if item.mark_price is not None and item.mark_price != ""
                        else None
                    ),
                )
            )
        return out

    # ----- server time ----------------------------------------------------- #

    async def server_time(self) -> datetime:
        """Binance server time (`GET /fapi/v1/time`) as a UTC datetime (D-25).

        Lets the CLI bound a run by the exchange clock instead of the host's.
        A missing value raises: an unknown time is never defaulted.
        """
        response = await _gated_rest_call(
            self._rest_gate, CallKind.TIME, self._sdk.rest_api.check_server_time
        )
        payload = response.data()
        if payload is None or payload.server_time is None:
            raise ValueError(f"check_server_time response missing server_time: {payload!r}")
        return _ms_to_utc(int(payload.server_time))

    # ----- exchange info --------------------------------------------------- #

    async def exchange_info(self, symbols: Sequence[str] | None = None) -> list[SymbolFilters]:
        """The exchange constraints of the listed contracts (`GET /fapi/v1/exchangeInfo`).

        Without `symbols` (the collector, the backfill CLI, the universe freeze and the order
        adapter) every listed contract is validated strictly: any drift fails the whole call.
        With `symbols` (the paper runtime's `ConstraintProvider`, plan 16-56, B1-WR-12) only the
        requested symbols are validated strictly and returned; a contract the caller did not ask
        for is never projected, so its drift cannot stop the refresh. Drift of an unrequested
        contract is logged as one warning naming the symbols only.
        """
        response = await self._paper_path_call(self._sdk.rest_api.exchange_information)
        info: ExchangeInformationResponse = response.data()
        listed = list(info.symbols or [])
        if symbols is not None:
            requested = frozenset(symbols)
            ignored_drift = sorted(
                str(sym.symbol) for sym in listed if sym.symbol not in requested and _has_drift(sym)
            )
            if ignored_drift:
                log.warning("adapter.exchange_info.unrequested_drift", symbols=ignored_drift)
            listed = [sym for sym in listed if sym.symbol in requested]
        out: list[SymbolFilters] = []
        drifted: list[str] = []
        for sym in listed:
            f_price = _find_filter(sym.filters, "PRICE_FILTER")
            f_lot = _find_filter(sym.filters, "LOT_SIZE")
            f_min_notional = _find_filter(sym.filters, "MIN_NOTIONAL")
            if f_price is None or f_lot is None or f_min_notional is None:
                # A missing required filter is contract drift (delist /
                # spec change): log loudly and fail the refresh rather
                # than silently shrinking the universe.
                missing = ",".join(
                    name
                    for name, f in (
                        ("PRICE_FILTER", f_price),
                        ("LOT_SIZE", f_lot),
                        ("MIN_NOTIONAL", f_min_notional),
                    )
                    if f is None
                )
                log.error(
                    "adapter.exchange_info.filter_drift",
                    symbol=sym.symbol,
                    missing_filters=missing,
                )
                drifted.append(f"{sym.symbol} lacks {missing}")
                continue
            # Flag-never-fabricate (D-09): a missing numeric filter field
            # must raise loudly, never become a plausible zero that poisons
            # downstream quantization (zero tick_size floors everything to
            # zero wearing the clothes of real data).
            if (
                f_price.tick_size is None
                or f_lot.step_size is None
                or f_lot.min_qty is None
                or f_min_notional.notional is None
            ):
                raise ValueError(
                    f"exchangeInfo filter missing numeric field for {sym.symbol!r}: {sym.filters!r}"
                )
            # Identity fields are the partition keys downstream (symbol
            # partitions, metadata PK): an empty-string symbol is a corrupt
            # partition, so a missing one joins the drift failure, never
            # an empty default.
            if (
                not sym.symbol
                or not sym.contract_type
                or not sym.status
                or not sym.base_asset
                or not sym.quote_asset
                or not sym.margin_asset
            ):
                log.error(
                    "adapter.exchange_info.symbol_drift",
                    symbol=sym.symbol,
                )
                drifted.append(f"symbol record missing identity fields: {sym!r}")
                continue
            tick = Decimal(str(f_price.tick_size))
            step = Decimal(str(f_lot.step_size))
            min_qty = Decimal(str(f_lot.min_qty))
            max_qty = Decimal(str(f_lot.max_qty)) if f_lot.max_qty is not None else None
            min_notional = Decimal(str(f_min_notional.notional))
            notional_blob = _filter_blob(f_min_notional)
            capabilities_blob = _order_capabilities_blob(sym.order_types or [])
            position_mode_blob = _position_mode_blob(sym)
            onboard = _ms_to_utc(int(sym.onboard_date)) if sym.onboard_date is not None else None
            market_lot = _parse_market_lot_size(
                sym.symbol, _find_filter(sym.filters, "MARKET_LOT_SIZE")
            )
            percent_price = _parse_percent_price(
                sym.symbol, _find_filter(sym.filters, "PERCENT_PRICE")
            )
            out.append(
                SymbolFilters(
                    symbol=sym.symbol,
                    contract_type=sym.contract_type,
                    status=sym.status,
                    onboard_time_utc=onboard,
                    price_tick_size=tick,
                    quantity_step_size=step,
                    min_quantity=min_qty,
                    max_quantity=max_qty,
                    min_notional=min_notional,
                    base_asset=sym.base_asset,
                    quote_asset=sym.quote_asset,
                    margin_asset=sym.margin_asset,
                    notional_constraints_json=notional_blob,
                    order_capabilities_json=capabilities_blob,
                    position_mode_snapshot_json=position_mode_blob,
                    delivery_date_ms=(
                        int(sym.delivery_date) if sym.delivery_date is not None else None
                    ),
                    market_lot_min_quantity=market_lot[0],
                    market_lot_max_quantity=market_lot[1],
                    market_lot_step_size=market_lot[2],
                    percent_price_multiplier_up=percent_price[0],
                    percent_price_multiplier_down=percent_price[1],
                    percent_price_multiplier_decimals=percent_price[2],
                )
            )
        if drifted:
            raise ValueError(
                "exchangeInfo contract drift — symbols with missing "
                f"required filters: {'; '.join(drifted)}"
            )
        return out


# --------------------------------------------------------------------------- #
# Internal helpers for exchange-info projection.
# --------------------------------------------------------------------------- #


def _has_drift(sym: Any) -> bool:
    """True when a contract lacks a required filter, a numeric filter field or an identity field.

    Only used to name unrequested contracts in a warning; the strict path raises on its own.
    """
    f_price = _find_filter(sym.filters, "PRICE_FILTER")
    f_lot = _find_filter(sym.filters, "LOT_SIZE")
    f_min_notional = _find_filter(sym.filters, "MIN_NOTIONAL")
    if f_price is None or f_lot is None or f_min_notional is None:
        return True
    if (
        f_price.tick_size is None
        or f_lot.step_size is None
        or f_lot.min_qty is None
        or f_min_notional.notional is None
    ):
        return True
    identity = (
        sym.symbol,
        sym.contract_type,
        sym.status,
        sym.base_asset,
        sym.quote_asset,
        sym.margin_asset,
    )
    return not all(identity)


def _find_filter(
    filters: list[ExchangeInformationResponseSymbolsInnerFiltersInner] | None,
    filter_type: str,
) -> ExchangeInformationResponseSymbolsInnerFiltersInner | None:
    if not filters:
        return None
    for f in filters:
        if f.filter_type == filter_type:
            return f
    return None


def _filter_decimal(symbol: str | None, filter_type: str, field: str, raw: str | None) -> Decimal:
    """Parse one numeric field of a PRESENT filter, failing closed (EXEC-04, D-09).

    A missing, empty, non-numeric or non-finite value raises ValueError: a present
    filter with a bad field is exchange contract drift, never a silent None.
    """
    if raw is None or raw == "":
        raise ValueError(f"exchangeInfo {filter_type} for {symbol!r} is missing {field}")
    try:
        value = Decimal(str(raw))
    except InvalidOperation as exc:
        raise ValueError(
            f"exchangeInfo {filter_type}.{field} for {symbol!r} is not numeric: {raw!r}"
        ) from exc
    if not value.is_finite():
        raise ValueError(
            f"exchangeInfo {filter_type}.{field} for {symbol!r} is not finite: {raw!r}"
        )
    return value


def _parse_market_lot_size(
    symbol: str | None,
    f: ExchangeInformationResponseSymbolsInnerFiltersInner | None,
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """MARKET_LOT_SIZE as (min_qty, max_qty, step_size); all None when the filter is absent."""
    if f is None:
        return (None, None, None)
    return (
        _filter_decimal(symbol, "MARKET_LOT_SIZE", "minQty", f.min_qty),
        _filter_decimal(symbol, "MARKET_LOT_SIZE", "maxQty", f.max_qty),
        _filter_decimal(symbol, "MARKET_LOT_SIZE", "stepSize", f.step_size),
    )


def _parse_percent_price(
    symbol: str | None,
    f: ExchangeInformationResponseSymbolsInnerFiltersInner | None,
) -> tuple[Decimal | None, Decimal | None, int | None]:
    """PERCENT_PRICE as (multiplierUp, multiplierDown, multiplierDecimal as int).

    All None when the filter is absent; a present filter missing or mangling any field
    raises ValueError.
    """
    if f is None:
        return (None, None, None)
    up = _filter_decimal(symbol, "PERCENT_PRICE", "multiplierUp", f.multiplier_up)
    down = _filter_decimal(symbol, "PERCENT_PRICE", "multiplierDown", f.multiplier_down)
    raw_decimals = f.multiplier_decimal
    if raw_decimals is None or raw_decimals == "":
        raise ValueError(f"exchangeInfo PERCENT_PRICE for {symbol!r} is missing multiplierDecimal")
    try:
        decimals = int(str(raw_decimals))
    except ValueError as exc:
        raise ValueError(
            f"exchangeInfo PERCENT_PRICE.multiplierDecimal for {symbol!r} is not an integer: "
            f"{raw_decimals!r}"
        ) from exc
    if decimals < 0:
        raise ValueError(
            f"exchangeInfo PERCENT_PRICE.multiplierDecimal for {symbol!r} must be >= 0: {decimals}"
        )
    return (up, down, decimals)


def _filter_blob(f: ExchangeInformationResponseSymbolsInnerFiltersInner) -> str:
    """Compact JSON blob of the MIN_NOTIONAL filter for downstream consumers.

    Pydantic's `model_dump_json()` is the canonical serialization (the SDK
    already builds the model via pydantic v2). Kept tiny — single filter
    object — so the column stays portable across PG versions (per DATA_MODEL
    §5 JSON-as-TEXT rule).
    """
    return f.model_dump_json()


def _order_capabilities_blob(order_types: list[str]) -> str:
    import json

    return json.dumps({"order_types": list(order_types)}, separators=(",", ":"))


def _position_mode_blob(sym: Any) -> str:
    """Snapshot of fields the executor/collector care about for position-mode.

    Kept as a JSON blob (DATA_MODEL §2.11): `positionSide` semantics differ
    between one-way and hedge mode and the precise field set is TBD by the
    Phase-3 parameter-registry work. We capture the union of fields that
    later consumers may need.
    """
    import json

    payload = {
        "pricePrecision": getattr(sym, "price_precision", None),
        "quantityPrecision": getattr(sym, "quantity_precision", None),
        "quotePrecision": getattr(sym, "quote_precision", None),
        "timeInForce": getattr(sym, "time_in_force", None),
        "triggerProtect": getattr(sym, "trigger_protect", None),
        "marketTakeBound": getattr(sym, "market_take_bound", None),
    }
    return json.dumps(payload, separators=(",", ":"), default=str)
