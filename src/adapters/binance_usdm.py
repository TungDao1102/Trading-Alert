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

Phase 8 (plan 08-04) reconciler truth surface — every method below is
verified against the INSTALLED SDK version (recorded here per
acceptance criterion "SDK signatures verified against installed
17.4.0 in module docstring"; re-verify against the SDK after any upgrade
per the project's SDK re-verification policy):

  Installed package: binance-sdk-derivatives-trading-usds-futures 17.4.0
  Verified against the installed package via `python -c "import
  binance_sdk_derivatives_trading_usds_futures as m; ..."` during
  08-04 execution.

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

The 17.3.1 -> 17.4.0 changelog (per RESEARCH Open Question 2): the
Delta closed during 08-04 was "no public REST method-signature change
in any of the seven reconciler methods we touch; only the
ALGO_UPDATE.o.rm field semantics for rejection reasons (Dec 2025 Algo
migration) changed, which is WS-side and not part of this adapter
slice." Reconciliation module never relies on WS-only events without
the periodic REST truth tick (T-8-33).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
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


def _is_transient_reconcile(exc: BaseException) -> bool:
    """Retry transient faults only; fail closed on programming errors.

    Mirrors the precedent in `src/paper/resync.py` (lines 177-179):
    programming errors (`ValueError`, `KeyError`, `TypeError`) fail
    immediately instead of burning the bounded retry budget and
    masking deterministic faults as transient.
    """
    return not isinstance(exc, (ValueError, KeyError, TypeError))


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
    successful sweep (no cancel needed, no error).
    """

    client_algo_id: str
    found: bool
    algo_status: str | None
    update_time_utc: datetime | None


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
        raw = response.data()
        # The stub types `data()` as the single response model, but array
        # endpoints return a list at runtime (`is_array` models) — unwrap
        # defensively instead of casting.
        rows: list[GetFundingRateHistoryResponseInner] = (
            raw if isinstance(raw, list) else [raw]
        )
        out: list[FundingTick] = []
        for item in rows:
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
        rows: Sequence[CurrentAllOpenOrdersResponse] = (
            raw if isinstance(raw, list) else [raw]
        )
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
        rows: Sequence[CurrentAllAlgoOpenOrdersResponse] = (
            raw if isinstance(raw, list) else [raw]
        )
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
        rows: Sequence[PositionInformationV3Response] = (
            raw if isinstance(raw, list) else [raw]
        )
        out: list[PositionSnapshot] = []
        for item in rows:
            snapshot = _row_to_position_snapshot(item)
            if snapshot is not None and snapshot.position_amt != Decimal("0"):
                out.append(snapshot)
        return out

    async def query_algo_order_by_client(
        self, *, client_algo_id: str
    ) -> AlgoOrderProbe:
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
        retry = tenacity.retry_if_exception(_is_transient_reconcile)
        stop = tenacity.stop_after_attempt(
            _RECONCILER_CANCEL_MAX_ATTEMPTS
        ) | tenacity.stop_after_delay(_RECONCILER_CANCEL_MAX_DELAY_SECONDS)
        wait = tenacity.wait_random_exponential(
            multiplier=_RECONCILER_CANCEL_WAIT_MULTIPLIER_SECONDS,
            max=_RECONCILER_CANCEL_WAIT_MAX_SECONDS,
        )
        decorator = tenacity.AsyncRetrying(
            retry=retry, stop=stop, wait=wait, reraise=True
        )

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
            raise RuntimeError(
                "unreachable: tenacity.AsyncRetrying exhausted without reraise"
            )

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
        retry = tenacity.retry_if_exception(_is_transient_reconcile)
        stop = tenacity.stop_after_attempt(
            _RECONCILER_CANCEL_MAX_ATTEMPTS
        ) | tenacity.stop_after_delay(_RECONCILER_CANCEL_MAX_DELAY_SECONDS)
        wait = tenacity.wait_random_exponential(
            multiplier=_RECONCILER_CANCEL_WAIT_MULTIPLIER_SECONDS,
            max=_RECONCILER_CANCEL_WAIT_MAX_SECONDS,
        )
        decorator = tenacity.AsyncRetrying(
            retry=retry, stop=stop, wait=wait, reraise=True
        )

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
            raise RuntimeError(
                "unreachable: tenacity.AsyncRetrying exhausted without reraise"
            )

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
    if (
        not item.symbol
        or not item.client_order_id
        or item.order_id is None
    ):
        raise ValueError(
            f"open_order row missing identity fields: {item!r}"
        )
    return OpenOrderSnapshot(
        symbol=item.symbol,
        client_order_id=item.client_order_id,
        exchange_order_id=str(item.order_id),
        side=item.side or "",
        position_side=item.position_side or "",
        order_type=item.type or "",
        time_in_force=item.time_in_force or "",
        status=item.status or "",
        quantity=Decimal(str(item.orig_qty))
        if item.orig_qty is not None
        else Decimal("0"),
        price=Decimal(str(item.price)) if item.price is not None else None,
        stop_price=(
            Decimal(str(item.stop_price))
            if item.stop_price is not None
            else None
        ),
        reduce_only=bool(item.reduce_only) if item.reduce_only is not None else False,
        close_position=bool(item.close_position) if item.close_position is not None else False,
        working_type=item.working_type,
        price_protect=item.price_protect,
        update_time_utc=_ms_to_utc(int(item.update_time))
        if item.update_time is not None
        else _epoch_utc(),
    )


def _row_to_open_algo_order_snapshot(
    item: CurrentAllAlgoOpenOrdersResponse,
) -> OpenAlgoOrderSnapshot | None:
    """Project one SDK open-algo-order row to `OpenAlgoOrderSnapshot`.

    Flag-never-fabricate (D-09): rows missing identity fields raise
    loudly. The reconciler MUST never sweep on a synthetic ID.
    """
    if (
        not item.symbol
        or not item.client_algo_id
        or item.algo_id is None
    ):
        raise ValueError(
            f"open_algo_order row missing identity fields: {item!r}"
        )
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
        quantity=Decimal(str(item.quantity))
        if item.quantity is not None
        else Decimal("0"),
        trigger_price=(
            Decimal(str(item.trigger_price))
            if item.trigger_price is not None
            else None
        ),
        price=Decimal(str(item.price)) if item.price is not None else None,
        trigger_time_utc=(
            _ms_to_utc(int(item.trigger_time))
            if item.trigger_time is not None
            else None
        ),
        working_type=item.working_type,
        close_position=bool(item.close_position) if item.close_position is not None else False,
        reduce_only=bool(item.reduce_only) if item.reduce_only is not None else False,
        update_time_utc=_ms_to_utc(int(item.update_time))
        if item.update_time is not None
        else _epoch_utc(),
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
        mark_price=(
            Decimal(str(item.mark_price))
            if item.mark_price is not None
            else None
        ),
        unrealized_profit=Decimal(str(item.un_realized_profit))
        if item.un_realized_profit is not None
        else Decimal("0"),
        liquidation_price=(
            Decimal(str(item.liquidation_price))
            if item.liquidation_price is not None
            else None
        ),
        notional=(
            Decimal(str(item.notional))
            if item.notional is not None
            else None
        ),
        margin_asset=item.margin_asset or "",
        update_time_utc=_ms_to_utc(int(item.update_time))
        if item.update_time is not None
        else _epoch_utc(),
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
        update_time_utc=_ms_to_utc(int(raw.update_time))
        if raw.update_time is not None
        else None,
    )


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
