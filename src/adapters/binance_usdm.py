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

Phase 8 (plan 08-04) reconciler truth surface + Phase 9 (plan 09-01)
placement surface — every method below is verified against the
INSTALLED SDK version (recorded here per acceptance criterion "SDK
signatures verified against installed 17.4.0 in module docstring";
re-verify against the SDK after any upgrade per the project's SDK
re-verification policy):

  Installed package: binance-sdk-derivatives-trading-usds-futures 17.4.0
  Verified against the installed package via `python -c "import
  binance_sdk_derivatives_trading_usds_futures as m; ..."` during
  08-04 and 09-01 execution.

  | Adapter method              | SDK method                      | Notes
  | --------------------------- | ------------------------------- | -----
  | snapshot_open_normal_orders | current_all_open_orders(symbol) | 17.3.1 -> 17.4.0: no signature
    change in the installed package; symbol parameter Optional[str]
    unchanged; returns ApiResponse[CurrentAllOpenOrdersResponse] (list
    shape at runtime).
  | snapshot_open_algo_orders   | current_all_algo_open_orders    | 17.3.1 -> 17.4.0: no signature
    change; `algo_type`, `symbol`, `algo_id`, `recv_window` Optional,
    return list at runtime.
  | snapshot_positions          | position_information_v3         | 17.3.1 -> 17.4.0: no signature
    change; `symbol`, `recv_window` Optional; return list at runtime
    (one row per symbol/position_side).
  | query_algo_order_by_client  | query_algo_order(client_algo_id)| 17.3.1 -> 17.4.0: no signature
    change; `algo_id`, `client_algo_id`, `recv_window` Optional —
    populate `client_algo_id` (T-8-32 query-by-ID first, never blind
    retry per EXECUTION_SPEC 10).
  | cancel_normal_order         | cancel_order(symbol, orig_client_order_id) | 17.3.1 -> 17.4.0: no
    signature change; `symbol` required, `order_id` / `orig_client_order_id`
    optional — populate `orig_client_order_id` to keep the cancel
    idempotent on retries.
  | cancel_algo_order           | cancel_algo_order(client_algo_id) | 17.3.1 -> 17.4.0: no
    signature change; same query-by-ID posture as the normal cancel.
  | place_entry                 | new_order(symbol, side, type, position_side, time_in_force, quantity, price, new_client_order_id) | 17.4.0: no signature change; LIMIT requires timeInForce+quantity+price; position_side "BOTH" one-way / "LONG"/"SHORT" hedge (mandatory in hedge); quantity/price are float at SDK boundary (converted via string-mediated Decimal-to-edge per RESEARCH Pattern 1).  # noqa: E501
  | place_algo_protective       | new_algo_order(algo_type, symbol, side, type, position_side, trigger_price, close_position, working_type, client_algo_id) | 17.4.0: no signature change; algoType=CONDITIONAL required; closePosition=true mutually exclusive with quantity/reduceOnly; working_type MARK_PRICE for SL/TP triggers.  # noqa: E501
  | query_order_by_client       | query_order(symbol, orig_client_order_id) | 17.4.0: no signature change; `symbol` required, `order_id` / `orig_client_order_id` optional — populate `orig_client_order_id` for no-blind-recovery probe (EXECUTION_SPEC §10).  # noqa: E501
  | get_position_mode           | get_current_position_mode(recv_window) | 17.4.0: no signature change; returns dual_side_position bool (True=hedge, False=one-way); re-checked at placement time per D-02.  # noqa: E501
  | user_commission_rate       | user_commission_rate(symbol, recv_window) | 17.4.0: `symbol` required, `recv_window` Optional (left to the SDK default); returns UserCommissionRateResponse with Optional str fields (symbol, makerCommissionRate, takerCommissionRate, rpiCommissionRate); strict parse, unknown raises, never zero (Phase 12, D-11).  # noqa: E501

The 17.3.1 -> 17.4.0 changelog (per RESEARCH Open Question 2): the
Delta closed during 08-04 was "no public REST method-signature change
in any of the seven reconciler methods we touch; only the
ALGO_UPDATE.o.rm field semantics for rejection reasons (Dec 2025 Algo
migration) changed, which is WS-side and not part of this adapter
slice." Reconciliation module never relies on WS-only events without
the periodic REST truth tick (T-8-33). The 09-01 placement methods
follow the same posture: no signature change in the four new methods.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

import structlog
import tenacity
from binance_sdk_derivatives_trading_usds_futures import (
    DerivativesTradingUsdsFutures,
    RateLimitBanError,
    TooManyRequestsError,
)

log = structlog.get_logger()

if TYPE_CHECKING:
    from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
        CancelAlgoOrderResponse,
        CancelOrderResponse,
        CurrentAllAlgoOpenOrdersResponse,
        CurrentAllOpenOrdersResponse,
        ExchangeInformationResponse,
        ExchangeInformationResponseSymbolsInnerFiltersInner,
        GetFundingRateHistoryResponseInner,
        OpenInterestResponse,
        PositionInformationV3Response,
        QueryAlgoOrderResponse,
    )


# --------------------------------------------------------------------------- #
# Reconciler cancel ceilings (mirror of notify/resync precedent).
#
# The reconciler is the LAST line of defense against stale protective
# orders. Its cancel calls must be bounded — a runaway retry loop can
# turn an orphan protective into a flood of duplicate exchange
# requests. The ceilings below are module-level named constants so the
# operator can audit them before live enablement, never mid-run.
# --------------------------------------------------------------------------- #

_RECONCILER_CANCEL_MAX_ATTEMPTS: int = 3
_RECONCILER_CANCEL_MAX_DELAY_SECONDS: int = 30
_RECONCILER_CANCEL_WAIT_MULTIPLIER_SECONDS: int = 1
_RECONCILER_CANCEL_WAIT_MAX_SECONDS: int = 10


# --------------------------------------------------------------------------- #
# Placement is NEVER retried inside the adapter (09-REVIEW CR-09).
#
# Placement calls are the FIRST line of defense. Binance dedups
# `newClientOrderId` / `clientAlgoId` only among OPEN orders, so an
# adapter-level retry after an ambiguous failure (timeout, 5xx
# "execution status unknown") can duplicate an order whose first attempt
# was accepted and filled, and non-transient 4xx rejections would be
# re-sent for nothing. `place_entry` / `place_algo_protective` make one
# attempt and surface every failure; the execution manager probes by the
# deterministic client id (EXECUTION_SPEC §10) and decides.
# --------------------------------------------------------------------------- #


def _is_transient_reconcile(exc: BaseException) -> bool:
    """Retry transient faults only; fail closed on programming errors.

    Mirrors the precedent in `src/paper/resync.py` (lines 177-179):
    programming errors (`ValueError`, `KeyError`, `TypeError`) fail
    immediately instead of burning the bounded retry budget and
    masking deterministic faults as transient.
    """
    return not isinstance(exc, (ValueError, KeyError, TypeError))


def _cancel_retry_predicate(exc: BaseException) -> bool:
    if _is_already_canceled_message(str(exc)):
        return False
    return _is_transient_reconcile(exc)


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
# Reconciler truth snapshots (Phase 8, plan 08-04).
#
# These are the SDK-free value objects the reconciler compares against
# local intent. Every field is Decimal/UTC-aware/non-empty-string per
# the project's D-12 boundary discipline. The reconciler never sees an
# SDK response model — only these frozen dataclasses.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class OpenOrderSnapshot:
    """One open normal order from `current_all_open_orders`.

    `client_order_id` is the deterministic ID minted by
    `src/execution/order_ids.py:derive_client_order_id`; the sweeper
    uses it to address the cancel call (T-8-32 query-by-ID first,
    never blind retry per EXECUTION_SPEC 10).
    """

    symbol: str
    client_order_id: str
    exchange_order_id: str
    side: str
    position_side: str
    order_type: str
    time_in_force: str
    status: str
    quantity: Decimal
    price: Decimal | None
    stop_price: Decimal | None
    reduce_only: bool
    close_position: bool
    working_type: str | None
    price_protect: bool | None
    update_time_utc: datetime


@dataclass(frozen=True)
class OpenAlgoOrderSnapshot:
    """One open algo order from `current_all_algo_open_orders`.

    `client_algo_id` is the deterministic ID minted by
    `src/execution/order_ids.py:derive_algo_client_id`; the sweeper
    uses it to address the cancel call. `algo_type` is the
    CONDITIONAL type (STOP_MARKET / TAKE_PROFIT_MARKET / STOP /
    TAKE_PROFIT / TRAILING_STOP_MARKET) per the Dec 2025 Algo
    migration.
    """

    symbol: str
    client_algo_id: str
    algo_id: str
    algo_type: str
    order_type: str
    side: str
    position_side: str
    time_in_force: str
    algo_status: str
    quantity: Decimal
    trigger_price: Decimal | None
    price: Decimal | None
    trigger_time_utc: datetime | None
    working_type: str | None
    close_position: bool
    reduce_only: bool
    update_time_utc: datetime


@dataclass(frozen=True)
class PositionSnapshot:
    """One position row from `position_information_v3`.

    `position_amt` is signed (positive for LONG, negative for SHORT).
    `position_side` is the Binance-reported side (LONG / SHORT /
    BOTH). The reconciler treats `position_amt == 0` as "no position"
    regardless of `position_side`.
    """

    symbol: str
    position_side: str
    position_amt: Decimal
    entry_price: Decimal
    break_even_price: Decimal
    mark_price: Decimal | None
    unrealized_profit: Decimal
    liquidation_price: Decimal | None
    notional: Decimal | None
    margin_asset: str
    update_time_utc: datetime


@dataclass(frozen=True)
class AlgoOrderProbe:
    """Result of `query_algo_order(client_algo_id=...)`.

    Used by the sweeper to verify the algo order still exists before
    issuing a cancel (T-8-32 query-by-ID first). `found=False` means
    the algo order is already gone — the sweeper treats that as a
    successful prior sweep (no cancel needed, no error).
    """

    client_algo_id: str
    found: bool
    algo_status: str | None
    update_time_utc: datetime | None


# --------------------------------------------------------------------------- #
# Placement result dataclasses (Phase 9, plan 09-01).
#
# These are the SDK-free value objects the execution manager receives
# from the adapter. Every field is Decimal/UTC-aware/non-empty-string
# per the project's D-12 boundary discipline. The execution core never
# sees an SDK response model — only these frozen dataclasses.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EntryPlacementResult:
    """Result of `place_entry` (new_order LIMIT).

    `client_order_id` is the deterministic ID minted by
    `src/execution/order_ids.py:derive_client_order_id`; the manager
    uses it for the no-blind-recovery probe. `exchange_order_id` is
    the exchange-assigned numeric ID (None if the response was
    ambiguous — the manager probes by client_order_id in that case).
    """

    symbol: str
    client_order_id: str
    exchange_order_id: str | None
    side: str
    position_side: str
    order_type: str
    time_in_force: str
    status: str
    quantity: Decimal
    price: Decimal
    update_time_utc: datetime


@dataclass(frozen=True)
class AlgoPlacementResult:
    """Result of `place_algo_protective` (new_algo_order CONDITIONAL).

    `client_algo_id` is the deterministic ID minted by
    `src/execution/order_ids.py:derive_algo_client_id`. `algo_id` is
    the exchange-assigned numeric ID (None if the response was
    ambiguous).
    """

    symbol: str
    client_algo_id: str
    algo_id: str | None
    algo_type: str
    order_type: str
    side: str
    position_side: str
    algo_status: str
    trigger_price: Decimal
    close_position: bool
    working_type: str
    update_time_utc: datetime


@dataclass(frozen=True)
class OrderProbe:
    """Result of `query_order_by_client` (query_order by orig_client_order_id).

    Used by the execution manager for the no-blind-recovery probe
    (EXECUTION_SPEC §10). `found=False` means the order is already
    gone — the manager treats that as a successful prior placement
    (no retry needed).
    """

    client_order_id: str
    found: bool
    order_id: str | None
    status: str | None
    update_time_utc: datetime | None


@dataclass(frozen=True)
class PositionModeResult:
    """Result of `get_position_mode` (get_current_position_mode).

    `dual_side_position=True` means hedge mode (positionSide LONG/SHORT
    mandatory); `False` means one-way mode (positionSide BOTH).
    """

    dual_side_position: bool


@dataclass(frozen=True)
class CommissionRates:
    """Result of `user_commission_rate` (GET /fapi/v1/commissionRate).

    Both rates are Decimal fractions in [0, 0.01] (0.0004 is 0.04 percent).
    A real rate of 0 is legitimate; an unknown rate is never represented as
    0 (the adapter raises instead). The adapter takes no clock: the caller
    stamps `observed_at_utc` when it builds the risk-layer
    `AccountCommission`. Runtime wiring is Phase 24.
    """

    symbol: str
    maker_rate: Decimal
    taker_rate: Decimal


# --------------------------------------------------------------------------- #
# Helper conversions.
# --------------------------------------------------------------------------- #


def _decimal_to_wire(value: Decimal) -> Any:
    """Convert an exchange-sensitive Decimal to its exact wire string.

    09-REVIEW WR-11 / IN-02: the SDK annotates prices/quantities as
    `float`, but serializes every non-float value with `str()` into the
    signed query string. Passing a raw `Decimal` breaks mypy strict and
    can emit exponent notation (`str(Decimal("1E-8"))` → "1E-8",
    `str(Decimal("1E+1"))` → "1E+1"), which Binance rejects. Fixed-point
    formatting (`format(value, "f")`) is the exact, float-free wire form.

    Typed `Any` (not `str`) on purpose: the one place the project's
    Decimal crosses the SDK's float-annotated boundary, without a
    `type: ignore` at every call site.
    """
    if not isinstance(value, Decimal):
        raise TypeError(f"_decimal_to_wire expects Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"_decimal_to_wire: non-finite value {value!r}")
    return format(value, "f")


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
        response = await asyncio.to_thread(self._sdk.rest_api.open_interest, symbol=symbol)
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
        response = await asyncio.to_thread(
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
                    mark_price=(
                        Decimal(str(item.mark_price)) if item.mark_price is not None else None
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

    # ----- reconciler truth surface (Phase 8, plan 08-04) ---------------- #
    # These methods are QUERY-AND-CANCEL ONLY. The reconciler must never
    # place a new order under any input (Pitfall 1 — D-03 reconciliation
    # is the safety net, never the initiator). A place-order path here
    # is a Phase-9 escalation, not a Phase-8 addition.

    async def snapshot_open_normal_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> list[OpenOrderSnapshot]:
        """Return the project's frozen-dataclass view of open normal orders.

        Wraps `current_all_open_orders` (verified against installed SDK
        17.4.0 per module docstring). Each SDK response row is projected
        to `OpenOrderSnapshot`; SDK response models never leak out of
        this module.

        Args:
            symbol: When provided, fetches only that symbol's open
                orders. When None, fetches all symbols (Binance
                recommends the symbol-scoped call to avoid heavy
                responses on busy accounts).
        """
        response = await asyncio.to_thread(
            self._sdk.rest_api.current_all_open_orders,
            symbol=symbol,
        )
        raw = response.data()
        rows: Sequence[CurrentAllOpenOrdersResponse] = raw if isinstance(raw, list) else [raw]
        out: list[OpenOrderSnapshot] = []
        for item in rows:
            snapshot = _row_to_open_order_snapshot(item)
            if snapshot is not None:
                out.append(snapshot)
        return out

    async def snapshot_open_algo_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> list[OpenAlgoOrderSnapshot]:
        """Return the project's frozen-dataclass view of open algo orders.

        Wraps `current_all_algo_open_orders` (verified against installed
        SDK 17.4.0). Each SDK row is projected to `OpenAlgoOrderSnapshot`
        with the canonical `client_algo_id` preserved for the sweeper's
        query-by-ID cancel posture.
        """
        response = await asyncio.to_thread(
            self._sdk.rest_api.current_all_algo_open_orders,
            symbol=symbol,
        )
        raw = response.data()
        rows: Sequence[CurrentAllAlgoOpenOrdersResponse] = raw if isinstance(raw, list) else [raw]
        out: list[OpenAlgoOrderSnapshot] = []
        for item in rows:
            snapshot = _row_to_open_algo_order_snapshot(item)
            if snapshot is not None:
                out.append(snapshot)
        return out

    async def snapshot_positions(
        self,
        *,
        symbol: str | None = None,
    ) -> list[PositionSnapshot]:
        """Return the project's frozen-dataclass view of open positions.

        Wraps `position_information_v3` (verified against installed SDK
        17.4.0). Rows with `position_amt == 0` are filtered out — a
        zero-amount position is "no position" per Binance semantics,
        and including it would poison the three-source compare with a
        phantom truth row that has no matching local intent.
        """
        response = await asyncio.to_thread(
            self._sdk.rest_api.position_information_v3,
            symbol=symbol,
        )
        raw = response.data()
        rows: Sequence[PositionInformationV3Response] = raw if isinstance(raw, list) else [raw]
        out: list[PositionSnapshot] = []
        for item in rows:
            snapshot = _row_to_position_snapshot(item)
            if snapshot is not None and snapshot.position_amt != Decimal("0"):
                out.append(snapshot)
        return out

    async def query_algo_order_by_client(self, *, client_algo_id: str) -> AlgoOrderProbe:
        """Look up one algo order by its deterministic client_algo_id.

        Returns `AlgoOrderProbe(found=False, ...)` when the SDK raises
        a not-found error (the SDK normalizes not-found as a generic
        API error with code -2011). The sweeper treats `found=False`
        as a successful prior sweep — no cancel call needed.

        Per T-8-32 (no-blind-retry, query-by-ID-first) and EXECUTION_SPEC
        10, the sweeper MUST verify the algo order exists before
        issuing a cancel; this probe is the verification path.
        """
        # SDK signatures accept Optional for both algo_id and
        # client_algo_id — we always populate the client side because
        # the deterministic-ID derivation guarantees uniqueness.
        try:
            response = await asyncio.to_thread(
                self._sdk.rest_api.query_algo_order,
                client_algo_id=client_algo_id,
            )
        except Exception as exc:  # noqa: BLE001 - SDK wraps unknown codes
            # Binance returns -2011 (UNKNOWN_ORDER) for missing algo
            # orders. Match by message code rather than importing the
            # SDK error class hierarchy, since the SDK does not expose
            # the per-code exception types.
            if "UNKNOWN_ORDER" in str(exc) or "-2011" in str(exc):
                return AlgoOrderProbe(
                    client_algo_id=client_algo_id,
                    found=False,
                    algo_status=None,
                    update_time_utc=None,
                )
            raise
        raw: QueryAlgoOrderResponse = response.data()
        return _algo_order_to_probe(client_algo_id, raw)

    async def cancel_normal_order(
        self,
        *,
        symbol: str,
        orig_client_order_id: str,
    ) -> None:
        """Cancel one open normal order by its deterministic client_order_id.

        Per T-8-32 + EXECUTION_SPEC 10: query-by-ID-first posture (the
        sweeper does the probe before calling cancel), bounded-batch
        retry mirroring the notify precedent. The cancel is idempotent
        on retries because `orig_client_order_id` is the deterministic
        36-char ID from `derive_client_order_id`.

        Never raises on "already canceled" — the SDK normalizes that
        as a generic API error with code -2011, which we treat as
        success (the post-condition the caller wanted is satisfied).

        Args:
            symbol: The trading pair (Binance requires it).
            orig_client_order_id: The deterministic client_order_id
                minted by `derive_client_order_id`.

        Raises:
            Any non-canceled-already SDK error after bounded retries
            are exhausted.
        """
        retry = tenacity.retry_if_exception(_cancel_retry_predicate)
        stop = tenacity.stop_after_attempt(
            _RECONCILER_CANCEL_MAX_ATTEMPTS
        ) | tenacity.stop_after_delay(_RECONCILER_CANCEL_MAX_DELAY_SECONDS)
        wait = tenacity.wait_random_exponential(
            multiplier=_RECONCILER_CANCEL_WAIT_MULTIPLIER_SECONDS,
            max=_RECONCILER_CANCEL_WAIT_MAX_SECONDS,
        )
        decorator = tenacity.AsyncRetrying(retry=retry, stop=stop, wait=wait, reraise=True)

        async def _do_cancel() -> CancelOrderResponse:
            response = await asyncio.to_thread(
                self._sdk.rest_api.cancel_order,
                symbol=symbol,
                orig_client_order_id=orig_client_order_id,
            )
            return response.data()

        async def _do_cancel_with_retry() -> CancelOrderResponse:
            async for attempt in decorator:
                with attempt:
                    result = await _do_cancel()
                    if _is_already_canceled_response(result):
                        return result
                    return result
            raise RuntimeError("unreachable: tenacity.AsyncRetrying exhausted without reraise")

        try:
            await _do_cancel_with_retry()
        except Exception as exc:  # noqa: BLE001 - SDK wraps unknown codes
            if _is_already_canceled_message(str(exc)):
                log.info(
                    "adapter.cancel_normal_order.already_canceled",
                    symbol=symbol,
                    orig_client_order_id=orig_client_order_id,
                )
                return
            raise

    async def cancel_algo_order(
        self,
        *,
        symbol: str,
        client_algo_id: str,
    ) -> None:
        """Cancel one open algo order by its deterministic client_algo_id.

        Per T-8-32 + EXECUTION_SPEC 10: query-by-ID-first posture, bounded
        retry, idempotent on retries. Treats already-canceled as success.

        Args:
            symbol: The trading pair (Binance requires it).
            client_algo_id: The deterministic algo_client_id minted by
                `derive_algo_client_id`.

        Raises:
            Any non-canceled-already SDK error after bounded retries
            are exhausted.
        """
        retry = tenacity.retry_if_exception(_cancel_retry_predicate)
        stop = tenacity.stop_after_attempt(
            _RECONCILER_CANCEL_MAX_ATTEMPTS
        ) | tenacity.stop_after_delay(_RECONCILER_CANCEL_MAX_DELAY_SECONDS)
        wait = tenacity.wait_random_exponential(
            multiplier=_RECONCILER_CANCEL_WAIT_MULTIPLIER_SECONDS,
            max=_RECONCILER_CANCEL_WAIT_MAX_SECONDS,
        )
        decorator = tenacity.AsyncRetrying(retry=retry, stop=stop, wait=wait, reraise=True)

        async def _do_cancel() -> CancelAlgoOrderResponse:
            response = await asyncio.to_thread(
                self._sdk.rest_api.cancel_algo_order,
                client_algo_id=client_algo_id,
            )
            return response.data()

        async def _do_cancel_with_retry() -> CancelAlgoOrderResponse:
            async for attempt in decorator:
                with attempt:
                    result = await _do_cancel()
                    if _is_already_canceled_response(result):
                        return result
                    return result
            raise RuntimeError("unreachable: tenacity.AsyncRetrying exhausted without reraise")

        try:
            await _do_cancel_with_retry()
        except Exception as exc:  # noqa: BLE001 - SDK wraps unknown codes
            if _is_already_canceled_message(str(exc)):
                log.info(
                    "adapter.cancel_algo_order.already_canceled",
                    symbol=symbol,
                    client_algo_id=client_algo_id,
                )
                return
            raise

    # ----- placement surface (Phase 9, plan 09-01) ----------------------- #
    # These methods are the FIRST line of defense — they place new orders
    # on the exchange. Every call is bounded by the PLACEMENT-prefixed
    # tenacity ceilings and uses the string-mediated Decimal-to-edge
    # conversion (RESEARCH Pattern 1). The execution core never imports
    # the SDK; only this adapter does.

    async def place_entry(
        self,
        *,
        symbol: str,
        side: str,
        position_side: str,
        time_in_force: str,
        quantity: Decimal,
        price: Decimal,
        new_client_order_id: str,
    ) -> EntryPlacementResult:
        """Place a LIMIT entry order via `new_order`.

        Per D-01: entry is a LIMIT-zone order on the normal order
        endpoint. The SDK 17.4.0 signature annotates `quantity` and
        `price` as `Optional[float]`, but the implementation just
        forwards the value through `urlencode` — Decimal is accepted
        and serialized with full precision (no float roundoff). We
        pass the Decimal through directly so the execution core never
        sees float (D-05 purity).

        Args:
            symbol: The trading pair (e.g. "BTCUSDT").
            side: "BUY" or "SELL".
            position_side: "BOTH" (one-way) or "LONG"/"SHORT" (hedge).
            time_in_force: "GTC" for LIMIT entries.
            quantity: The quantized quantity (Decimal).
            price: The zone-mid limit price (Decimal).
            new_client_order_id: The deterministic 36-char client_order_id
                from `derive_client_order_id`.

        Returns:
            An `EntryPlacementResult` with the exchange-assigned order_id
            and the projected response fields.

        Raises:
            Any SDK error from the SINGLE attempt. Placement is never
            retried here (EXECUTION_SPEC §10, 09-REVIEW CR-09): Binance
            dedups `newClientOrderId` only among OPEN orders, so a blind
            retry after an ambiguous failure (timeout / 5xx "execution
            status unknown") can double a position whose first attempt
            was accepted and filled. The execution manager probes by the
            deterministic client id and decides.
        """
        from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
            NewOrderResponse,
        )
        from binance_sdk_derivatives_trading_usds_futures.rest_api.models.enums import (
            NewOrderSideEnum,
            NewOrderTimeInForceEnum,
            NewOrderTypeEnum,
        )

        response = await asyncio.to_thread(
            self._sdk.rest_api.new_order,
            symbol=symbol,
            side=NewOrderSideEnum(side),
            type=NewOrderTypeEnum.LIMIT,
            position_side=position_side,
            time_in_force=NewOrderTimeInForceEnum(time_in_force),
            quantity=_decimal_to_wire(quantity),
            price=_decimal_to_wire(price),
            new_client_order_id=new_client_order_id,
        )
        result: NewOrderResponse = response.data()
        return _new_order_to_entry_result(result)

    async def place_algo_protective(
        self,
        *,
        symbol: str,
        side: str,
        algo_type: str,
        type: str,
        position_side: str,
        trigger_price: Decimal,
        close_position: bool,
        quantity: Decimal | None,
        working_type: str,
        client_algo_id: str,
        reduce_only: bool | None = None,
    ) -> AlgoPlacementResult:
        """Place a CONDITIONAL algo protective order via `new_algo_order`.

        Per D-01: protective exits go through `POST /fapi/v1/algoOrder`
        with `algoType=CONDITIONAL`. The adapter asserts that
        `close_position=True` is mutually exclusive with `quantity` and
        `reduce_only` (Pitfall 2 — Binance rejects the combination), and
        that a non-close leg carries an explicit quantity.

        `reduce_only=True` is forwarded to the SDK as
        `NewAlgoOrderReduceOnlyEnum.TRUE` (one-way partial-TP legs, so a
        late TP1 trigger can never open a reverse position). `None` /
        `False` omit the parameter (hedge mode — reduceOnly is omitted
        everywhere per EXECUTION_SPEC §5).

        Args:
            symbol: The trading pair.
            side: "BUY" or "SELL".
            algo_type: "CONDITIONAL" (the only supported type).
            type: "STOP_MARKET" or "TAKE_PROFIT_MARKET".
            position_side: "BOTH" (one-way) or "LONG"/"SHORT" (hedge).
            trigger_price: The trigger price (Decimal).
            close_position: True for close-all legs (SL/TP2 one-way).
            quantity: Explicit quantity (None for close-all legs).
            working_type: "MARK_PRICE" or "CONTRACT_PRICE".
            client_algo_id: The deterministic 36-char algo_client_id
                from `derive_algo_client_id`.
            reduce_only: True to send `reduceOnly=true` (one-way
                explicit-quantity legs); None/False omits the parameter.

        Returns:
            An `AlgoPlacementResult` with the exchange-assigned algo_id
            and the projected response fields.

        Raises:
            ValueError: close_position=True with quantity/reduce_only, or
                close_position=False without a quantity.
            Any SDK error from the single (never retried) attempt.
        """
        from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
            NewAlgoOrderResponse,
        )
        from binance_sdk_derivatives_trading_usds_futures.rest_api.models.enums import (
            NewAlgoOrderAlgoTypeEnum,
            NewAlgoOrderClosePositionEnum,
            NewAlgoOrderReduceOnlyEnum,
            NewAlgoOrderSideEnum,
            NewAlgoOrderTypeEnum,
            NewAlgoOrderWorkingTypeEnum,
        )

        # Pitfall 2: closePosition=true is mutually exclusive with
        # quantity and reduceOnly.
        if close_position and (quantity is not None or reduce_only):
            raise ValueError(
                "place_algo_protective: close_position=True is mutually "
                "exclusive with quantity/reduce_only (Binance rejects the combination)"
            )
        if not close_position and quantity is None:
            raise ValueError(
                "place_algo_protective: close_position=False requires an explicit quantity"
            )
        reduce_only_param = NewAlgoOrderReduceOnlyEnum.TRUE if reduce_only else None

        # Single attempt — never retried here (EXECUTION_SPEC §10,
        # 09-REVIEW CR-09): clientAlgoId is unique only among OPEN algo
        # orders, so a blind retry is either rejected as a duplicate (the
        # first attempt exists) or silently duplicates a leg (the first
        # attempt already triggered). The manager probes by id instead.
        response = await asyncio.to_thread(
            self._sdk.rest_api.new_algo_order,
            algo_type=NewAlgoOrderAlgoTypeEnum(algo_type),
            symbol=symbol,
            side=NewAlgoOrderSideEnum(side),
            type=NewAlgoOrderTypeEnum(type),
            position_side=position_side,
            trigger_price=_decimal_to_wire(trigger_price),
            close_position=NewAlgoOrderClosePositionEnum.TRUE
            if close_position
            else NewAlgoOrderClosePositionEnum.FALSE,
            quantity=_decimal_to_wire(quantity) if quantity is not None else None,
            working_type=NewAlgoOrderWorkingTypeEnum(working_type),
            reduce_only=reduce_only_param,
            client_algo_id=client_algo_id,
        )
        result: NewAlgoOrderResponse = response.data()
        return _new_algo_order_to_algo_result(result)

    async def query_order_by_client(
        self,
        *,
        symbol: str,
        orig_client_order_id: str,
    ) -> OrderProbe:
        """Look up one normal order by its deterministic client_order_id.

        Per T-8-32 + EXECUTION_SPEC §10: the execution manager probes
        by deterministic client_order_id before any retry (no-blind-
        recovery). Returns `OrderProbe(found=False, ...)` when the SDK
        raises a not-found error (code -2011 UNKNOWN_ORDER).

        Args:
            symbol: The trading pair (Binance requires it).
            orig_client_order_id: The deterministic client_order_id
                minted by `derive_client_order_id`.

        Returns:
            An `OrderProbe` with `found` flag and projected fields.
        """
        from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
            QueryOrderResponse,
        )

        try:
            response = await asyncio.to_thread(
                self._sdk.rest_api.query_order,
                symbol=symbol,
                orig_client_order_id=orig_client_order_id,
            )
        except Exception as exc:  # noqa: BLE001 - SDK wraps unknown codes
            # Only the already-mapped -2011 / UNKNOWN_ORDER form is treated
            # as a definitive "not found". Any other error (including a
            # query-order not-found code such as -2013 NO_SUCH_ORDER, which
            # must be re-verified against the current Binance error-code
            # docs before it is mapped here) RAISES, and the execution
            # manager treats a raising probe as UNKNOWN -> SAFE_MODE (fail
            # closed, 09-REVIEW CR-09). Mapping a code to not-found enables
            # a retry, so a wrong mapping would risk a duplicate order.
            if "UNKNOWN_ORDER" in str(exc) or "-2011" in str(exc):
                return OrderProbe(
                    client_order_id=orig_client_order_id,
                    found=False,
                    order_id=None,
                    status=None,
                    update_time_utc=None,
                )
            raise
        raw: QueryOrderResponse = response.data()
        return _query_order_to_probe(orig_client_order_id, raw)

    async def get_position_mode(self) -> PositionModeResult:
        """Detect the account's position mode (one-way vs hedge).

        Per D-02: position mode is detected dynamically at startup and
        re-checked at placement time — never assumed, never hard-coded.
        `dual_side_position=True` means hedge mode (positionSide
        LONG/SHORT mandatory); `False` means one-way mode (positionSide
        BOTH).

        Returns:
            A `PositionModeResult` with the `dual_side_position` flag.
        """
        from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
            GetCurrentPositionModeResponse,
        )

        response = await asyncio.to_thread(self._sdk.rest_api.get_current_position_mode)
        raw: GetCurrentPositionModeResponse = response.data()
        return PositionModeResult(dual_side_position=bool(raw.dual_side_position))

    async def user_commission_rate(self, symbol: str) -> CommissionRates:
        """Read the account's maker/taker commission rate for one symbol.

        GET /fapi/v1/commissionRate (USER_DATA, IP weight 20) through the
        official SDK `rest_api.user_commission_rate(symbol, recv_window)`;
        `recv_window` is left to the SDK default. The `rpiCommissionRate`
        field is ignored.

        Flag-never-fabricate (D-09, D-11): a missing, non-decimal,
        non-finite, negative, above-0.01 or wrong-symbol field raises
        `ValueError` — the adapter never returns a zero to mean unknown.
        There is no retry and no fallback value; an SDK exception
        propagates unchanged. The adapter takes no clock: the caller stamps
        `observed_at_utc` when it builds the risk-layer `AccountCommission`,
        and runtime wiring (refresh loop, TTL) is Phase 24.

        Returns:
            A frozen `CommissionRates` for the requested symbol.
        """
        from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
            UserCommissionRateResponse,
        )

        response = await asyncio.to_thread(self._sdk.rest_api.user_commission_rate, symbol)
        raw: UserCommissionRateResponse | None = response.data()
        if raw is None:
            raise ValueError(
                f"commissionRate response empty for {symbol}: refusing to fabricate a rate"
            )
        if raw.symbol is None or raw.symbol != symbol:
            raise ValueError(
                f"commissionRate response symbol {raw.symbol!r} does not match "
                f"requested {symbol}: refusing to use another symbol's rate"
            )
        maker = _require_commission_rate(raw.maker_commission_rate, "makerCommissionRate", symbol)
        taker = _require_commission_rate(raw.taker_commission_rate, "takerCommissionRate", symbol)
        return CommissionRates(symbol=symbol, maker_rate=maker, taker_rate=taker)


# --------------------------------------------------------------------------- #
# Internal helpers for reconciler snapshot projection.
# --------------------------------------------------------------------------- #


def _is_already_canceled_message(message: str) -> bool:
    """True when an SDK error message indicates the order is gone.

    Binance uses error code -2011 (UNKNOWN_ORDER) for cancels that
    target a non-existent order. We match by message code rather than
    importing the SDK error class hierarchy, since the SDK does not
    expose typed per-code exceptions.
    """
    return "UNKNOWN_ORDER" in message or "-2011" in message


def _is_already_canceled_response(result: Any) -> bool:
    """True when a successful cancel response already reflects the post-state."""
    # The Binance cancel responses carry a `status` field that
    # normalizes to "CANCELED" or "EXPIRED" on success; we don't
    # special-case them because the function returns None either way.
    # This helper exists so the caller has a single decision point if
    # a future Binance change introduces a "noop" status.
    return False


def _row_to_open_order_snapshot(
    item: CurrentAllOpenOrdersResponse,
) -> OpenOrderSnapshot | None:
    """Project one SDK open-order row to `OpenOrderSnapshot`.

    Flag-never-fabricate (D-09): rows missing the identity fields
    (symbol, client_order_id, exchange_order_id) raise loudly — a
    silent default would poison the three-source compare with a row
    that has no canonical ID to match against local intent.
    """
    if not item.symbol or not item.client_order_id or item.order_id is None:
        raise ValueError(f"open_order row missing identity fields: {item!r}")
    return OpenOrderSnapshot(
        symbol=item.symbol,
        client_order_id=item.client_order_id,
        exchange_order_id=str(item.order_id),
        side=item.side or "",
        position_side=item.position_side or "",
        order_type=item.type or "",
        time_in_force=item.time_in_force or "",
        status=item.status or "",
        quantity=_require_quantity(item.orig_qty, "orig_qty"),
        price=Decimal(str(item.price)) if item.price is not None else None,
        stop_price=(Decimal(str(item.stop_price)) if item.stop_price is not None else None),
        reduce_only=bool(item.reduce_only) if item.reduce_only is not None else False,
        close_position=bool(item.close_position) if item.close_position is not None else False,
        working_type=item.working_type,
        price_protect=item.price_protect,
        update_time_utc=_require_update_time_utc(item.update_time),
    )


def _row_to_open_algo_order_snapshot(
    item: CurrentAllAlgoOpenOrdersResponse,
) -> OpenAlgoOrderSnapshot | None:
    """Project one SDK open-algo-order row to `OpenAlgoOrderSnapshot`.

    Flag-never-fabricate (D-09): rows missing identity fields raise
    loudly. The reconciler MUST never sweep on a synthetic ID.
    """
    if not item.symbol or not item.client_algo_id or item.algo_id is None:
        raise ValueError(f"open_algo_order row missing identity fields: {item!r}")
    return OpenAlgoOrderSnapshot(
        symbol=item.symbol,
        client_algo_id=item.client_algo_id,
        algo_id=str(item.algo_id),
        algo_type=item.algo_type or "",
        order_type=item.order_type or "",
        side=item.side or "",
        position_side=item.position_side or "",
        time_in_force=item.time_in_force or "",
        algo_status=item.algo_status or "",
        quantity=_require_quantity(item.quantity, "quantity"),
        trigger_price=(
            Decimal(str(item.trigger_price)) if item.trigger_price is not None else None
        ),
        price=Decimal(str(item.price)) if item.price is not None else None,
        trigger_time_utc=(
            _ms_to_utc(int(item.trigger_time)) if item.trigger_time is not None else None
        ),
        working_type=item.working_type,
        close_position=bool(item.close_position) if item.close_position is not None else False,
        reduce_only=bool(item.reduce_only) if item.reduce_only is not None else False,
        update_time_utc=_require_update_time_utc(item.update_time),
    )


def _row_to_position_snapshot(
    item: PositionInformationV3Response,
) -> PositionSnapshot | None:
    """Project one SDK position row to `PositionSnapshot`.

    Flag-never-fabricate (D-09): rows missing identity fields raise
    loudly. The position-amount is signed (positive for LONG, negative
    for SHORT per Binance); the compare module checks `position_amt
    == 0` to filter phantom rows.
    """
    if not item.symbol:
        raise ValueError(f"position row missing symbol: {item!r}")
    return PositionSnapshot(
        symbol=item.symbol,
        position_side=item.position_side or "",
        position_amt=Decimal(str(item.position_amt))
        if item.position_amt is not None
        else Decimal("0"),
        entry_price=Decimal(str(item.entry_price))
        if item.entry_price is not None
        else Decimal("0"),
        break_even_price=Decimal(str(item.break_even_price))
        if item.break_even_price is not None
        else Decimal("0"),
        mark_price=(Decimal(str(item.mark_price)) if item.mark_price is not None else None),
        unrealized_profit=Decimal(str(item.un_realized_profit))
        if item.un_realized_profit is not None
        else Decimal("0"),
        liquidation_price=(
            Decimal(str(item.liquidation_price)) if item.liquidation_price is not None else None
        ),
        notional=(Decimal(str(item.notional)) if item.notional is not None else None),
        margin_asset=item.margin_asset or "",
        update_time_utc=_require_update_time_utc(item.update_time),
    )


def _algo_order_to_probe(
    client_algo_id: str,
    raw: QueryAlgoOrderResponse,
) -> AlgoOrderProbe:
    """Project a `query_algo_order` response into an `AlgoOrderProbe`."""
    return AlgoOrderProbe(
        client_algo_id=client_algo_id,
        found=True,
        algo_status=raw.algo_status,
        update_time_utc=_ms_to_utc(int(raw.update_time)) if raw.update_time is not None else None,
    )


# --------------------------------------------------------------------------- #
# Internal helpers for placement result projection (Phase 9, plan 09-01).
# --------------------------------------------------------------------------- #


def _new_order_to_entry_result(raw: Any) -> EntryPlacementResult:
    """Project a `new_order` response into an `EntryPlacementResult`.

    Flag-never-fabricate (D-09): rows missing identity fields raise
    loudly. The execution manager must never place on a synthetic ID.
    """
    if not raw.symbol or not raw.client_order_id or raw.order_id is None:
        raise ValueError(f"new_order response missing identity fields: {raw!r}")
    return EntryPlacementResult(
        symbol=raw.symbol,
        client_order_id=raw.client_order_id,
        exchange_order_id=str(raw.order_id),
        side=raw.side or "",
        position_side=raw.position_side or "",
        order_type=raw.type or "",
        time_in_force=raw.time_in_force or "",
        status=raw.status or "",
        quantity=_require_quantity(raw.orig_qty, "orig_qty"),
        price=Decimal(str(raw.price)) if raw.price is not None else Decimal("0"),
        update_time_utc=_require_update_time_utc(raw.update_time),
    )


def _new_algo_order_to_algo_result(raw: Any) -> AlgoPlacementResult:
    """Project a `new_algo_order` response into an `AlgoPlacementResult`.

    Flag-never-fabricate (D-09): rows missing identity fields raise
    loudly. The execution manager must never attach a protective on a
    synthetic ID.
    """
    if not raw.symbol or not raw.client_algo_id or raw.algo_id is None:
        raise ValueError(f"new_algo_order response missing identity fields: {raw!r}")
    return AlgoPlacementResult(
        symbol=raw.symbol,
        client_algo_id=raw.client_algo_id,
        algo_id=str(raw.algo_id),
        algo_type=raw.algo_type or "",
        order_type=raw.order_type or "",
        side=raw.side or "",
        position_side=raw.position_side or "",
        algo_status=raw.algo_status or "",
        trigger_price=(
            Decimal(str(raw.trigger_price)) if raw.trigger_price is not None else Decimal("0")
        ),
        close_position=bool(raw.close_position) if raw.close_position is not None else False,
        working_type=raw.working_type or "",
        update_time_utc=_require_update_time_utc(raw.update_time),
    )


def _query_order_to_probe(
    client_order_id: str,
    raw: Any,
) -> OrderProbe:
    """Project a `query_order` response into an `OrderProbe`."""
    return OrderProbe(
        client_order_id=client_order_id,
        found=True,
        order_id=str(raw.order_id) if raw.order_id is not None else None,
        status=raw.status,
        update_time_utc=_ms_to_utc(int(raw.update_time)) if raw.update_time is not None else None,
    )


def _require_quantity(value: Any, field_name: str) -> Decimal:
    if value is None:
        raise ValueError(f"snapshot row missing {field_name}: refusing to fabricate zero")
    return Decimal(str(value))


# A commission RATE above 1 percent is a unit error, never a real Binance
# rate (mirrors `src.risk.cost_rates.MAX_RATE`; the adapter imports nothing
# from the risk package).
_MAX_COMMISSION_RATE = Decimal("0.01")


def _require_commission_rate(value: Any, field_name: str, symbol: str) -> Decimal:
    """Parse one commissionRate string strictly; never fabricate a rate.

    Messages carry the symbol and field name only — no request URL,
    signature or key material.
    """
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(
            f"commissionRate {field_name} missing or not a string for {symbol}: "
            "refusing to fabricate a rate"
        )
    try:
        rate = Decimal(value)
    except InvalidOperation:
        raise ValueError(
            f"commissionRate {field_name} is not a decimal for {symbol}: "
            "refusing to fabricate a rate"
        ) from None
    if not rate.is_finite():
        raise ValueError(f"commissionRate {field_name} is not finite for {symbol}")
    if rate < Decimal("0"):
        raise ValueError(f"commissionRate {field_name} is negative for {symbol}")
    if rate > _MAX_COMMISSION_RATE:
        raise ValueError(
            f"commissionRate {field_name} exceeds {_MAX_COMMISSION_RATE} for {symbol}: "
            "likely a unit error"
        )
    return rate


def _require_update_time_utc(value: Any) -> datetime:
    if value is None:
        raise ValueError("snapshot row missing update_time: refusing to fabricate epoch-0")
    return _ms_to_utc(int(value))


def _epoch_utc() -> datetime:
    """UTC epoch — used as a defensive default when update_time is missing.

    `flag-never-fabricate` says a missing timestamp must surface
    loudly, but the snapshot projection runs on rows that already
    passed identity validation. The defensive epoch is here so a
    downstream consumer that requires a tz-aware datetime never sees
    a naive value; the row's identity still carries the truth.
    """
    return datetime(1970, 1, 1, tzinfo=UTC)


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
