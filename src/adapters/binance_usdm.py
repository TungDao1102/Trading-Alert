"""Binance USDⓈ-M Futures adapter.

This is the ONLY module in the project allowed to import the
`binance-sdk-derivatives-trading-usds-futures` package (RESEARCH §Pattern 1,
BINANCE.md §2, DATA_PIPELINE.md §14). Every downstream module receives
frozen dataclass instances — SDK response models never leak into the
domain/strategy layer.

Dataclass conventions:
  - Prices / quantities / notional values are `Decimal` (no float for
    exchange-sensitive values per ENGINEERING_PRINCIPLES).
  - Timestamps are `datetime` with `tzinfo=UTC` (D-06).
  - All fields are `frozen=True` so an immutable value flows through the
    pipeline and cannot be accidentally mutated.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import structlog
from binance_sdk_derivatives_trading_usds_futures import (
    DerivativesTradingUsdsFutures,
    RateLimitBanError,
    TooManyRequestsError,
)

log = structlog.get_logger()

if TYPE_CHECKING:
    from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
        ExchangeInformationResponse,
        ExchangeInformationResponseSymbolsInnerFiltersInner,
        GetFundingRateHistoryResponseInner,
        OpenInterestResponse,
    )


# --------------------------------------------------------------------------- #
# Frozen domain dataclasses — the public contract of the adapter.
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


# --------------------------------------------------------------------------- #
# Helper conversions.
# --------------------------------------------------------------------------- #


def _ms_to_utc(ms: int) -> datetime:
    """Convert a millisecond Unix epoch to a tz-aware UTC datetime."""
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


# The installed SDK's canonical rate-limit errors. `is_rate_limit_error`
# matches `isinstance` against these real classes (not name substrings),
# pinned by `test_rate_limit_predicate_pins_canonical_sdk_error_names` —
# an SDK rename fails loudly at import/test time instead of silently
# disabling bootstrap retry.
_RATE_LIMIT_ERRORS: tuple[type[BaseException], ...] = (
    TooManyRequestsError,
    RateLimitBanError,
)


def is_rate_limit_error(exc: BaseException) -> bool:
    """True when `exc` is one of the installed SDK's rate-limit errors.

    Primary check is `isinstance` against the real SDK classes; the
    class-name sniff survives only as a fallback for wrapped/proxied
    errors whose type identity is lost. Lives here (not in the
    paginator) because this module is the only one allowed to import
    the SDK.
    """
    if isinstance(exc, _RATE_LIMIT_ERRORS):
        return True
    cls_name = type(exc).__name__
    return "TooManyRequests" in cls_name or "RateLimit" in cls_name


def _row_to_kline(symbol: str, interval: str, row: list[Any]) -> Kline:
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


# --------------------------------------------------------------------------- #
# Adapter — single owner of SDK imports.
# --------------------------------------------------------------------------- #


class BinanceUsdmAdapter:
    """Project-owned wrapper around `DerivativesTradingUsdsFutures`.

    Constructed without arguments → uses the default `prod` REST host.
    Tests inject a fake `sdk_client` (any object exposing
    `rest_api.kline_candlestick_data` etc.) so unit tests never touch the
    network.
    """

    def __init__(self, sdk_client: DerivativesTradingUsdsFutures | None = None) -> None:
        self._sdk: DerivativesTradingUsdsFutures = sdk_client or DerivativesTradingUsdsFutures()

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
        response = await asyncio.to_thread(
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

    # ----- open interest --------------------------------------------------- #

    async def open_interest(self, symbol: str) -> OiSnapshot:
        response = await asyncio.to_thread(
            self._sdk.rest_api.open_interest, symbol=symbol
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
        response = await asyncio.to_thread(
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
                raise ValueError(
                    f"open_interest_statistics row missing fields: {item!r}"
                )
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
        response = await asyncio.to_thread(
            self._sdk.rest_api.get_funding_rate_history,
            symbol=symbol,
            start_time=start_ms,
            end_time=end_ms,
            limit=limit,
        )
        items: list[GetFundingRateHistoryResponseInner] = response.data()
        out: list[FundingTick] = []
        for item in items:
            # Same strictness as open_interest: skip-and-raise, never
            # default a missing timestamp/rate to epoch-0 or zero.
            if item.funding_time is None or item.funding_rate is None:
                raise ValueError(f"funding_rate row missing fields: {item!r}")
            resolved_symbol = item.symbol or symbol
            if not resolved_symbol:
                raise ValueError(
                    f"funding_rate row missing symbol: {item!r}"
                )
            out.append(
                FundingTick(
                    symbol=resolved_symbol,
                    funding_time_utc=_ms_to_utc(int(item.funding_time)),
                    funding_rate=Decimal(str(item.funding_rate)),
                    mark_price=(
                        Decimal(str(item.mark_price))
                        if item.mark_price is not None
                        else None
                    ),
                )
            )
        return out

    # ----- exchange info --------------------------------------------------- #

    async def exchange_info(self) -> list[SymbolFilters]:
        response = await asyncio.to_thread(self._sdk.rest_api.exchange_information)
        info: ExchangeInformationResponse = response.data()
        out: list[SymbolFilters] = []
        drifted: list[str] = []
        for sym in info.symbols or []:
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
                    "exchangeInfo filter missing numeric field "
                    f"for {sym.symbol!r}: {sym.filters!r}"
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
            max_qty = (
                Decimal(str(f_lot.max_qty)) if f_lot.max_qty is not None else None
            )
            min_notional = Decimal(str(f_min_notional.notional))
            notional_blob = _filter_blob(f_min_notional)
            capabilities_blob = _order_capabilities_blob(sym.order_types or [])
            position_mode_blob = _position_mode_blob(sym)
            onboard = (
                _ms_to_utc(int(sym.onboard_date))
                if sym.onboard_date is not None
                else None
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
