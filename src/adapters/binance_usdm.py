"""Binance USDⓈ-M Futures adapter.

This is the ONLY module in the project allowed to import the
`binance-sdk-derivatives-trading-usds-futures` package (RESEARCH §Pattern 1,
BINANCE.md §2, DATA_PIPELINE.md §14). Every downstream module receives
frozen dataclass instances — SDK response models never leak into the
domain/strategy layer.

Public market data (klines, mark klines, open interest, funding, server time, exchangeInfo)
lives in `src/adapters/binance_public.py` (plan 16-03). `BinanceUsdmAdapter` holds a
`BinancePublicMarketData` on its own SDK client and delegates those methods to it; the public
value types are re-exported here so every existing importer is unchanged. Only the order,
cancel, query, snapshot, position-mode and commission methods are implemented in this module.

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
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

import structlog
import tenacity
from binance_sdk_derivatives_trading_usds_futures import (
    BadRequestError,
    DerivativesTradingUsdsFutures,
    RateLimitBanError,
    TooManyRequestsError,
)
from src.adapters.binance_errors import error_facts_from_exception
from src.adapters.binance_public import (
    BinancePublicMarketData,
    _ms_to_utc,
)
from src.adapters.binance_public import FundingTick as FundingTick
from src.adapters.binance_public import Kline as Kline
from src.adapters.binance_public import MarkKline as MarkKline
from src.adapters.binance_public import OiSnapshot as OiSnapshot
from src.adapters.binance_public import SymbolFilters as SymbolFilters
from src.adapters.binance_public import _row_to_kline as _row_to_kline
from src.adapters.binance_public import _row_to_mark_kline as _row_to_mark_kline
from src.domain.exchange_errors import CallKind, ExchangeErrorCategory, classify

log = structlog.get_logger()

if TYPE_CHECKING:
    from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
        CancelAlgoOrderResponse,
        CancelOrderResponse,
        CurrentAllAlgoOpenOrdersResponse,
        CurrentAllOpenOrdersResponse,
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


def _is_order_absent(exc: BaseException, call_kind: CallKind) -> bool:
    """True only for the taxonomy category ORDER_ABSENT of `call_kind` (D-10).

    The decision uses the SDK class, the int Binance code and the call kind only
    (`src/domain/exchange_errors.py`): -2013 NO_SUCH_ORDER (Demo-observed for GET
    /fapi/v1/algoOrder) and -2011 on a QUERY or a CANCEL. Exception message text is never
    read, so a non-SDK exception, a missing or unlisted code, a 5xx or a network error is
    never "absent" (08-REVIEW IN-10): a wrong "absent" enables a duplicate order.
    """
    category = classify(error_facts_from_exception(exc), call_kind)
    return category is ExchangeErrorCategory.ORDER_ABSENT


def _is_order_not_found_error(exc: BaseException) -> bool:
    """True only for ORDER_ABSENT of a QUERY call; every other error must raise."""
    return _is_order_absent(exc, CallKind.QUERY)


def _cancel_retry_predicate(exc: BaseException) -> bool:
    if _is_already_canceled_message(str(exc)):
        return False
    return _is_transient_reconcile(exc)


# --------------------------------------------------------------------------- #
# Frozen domain dataclasses — the public contract of the adapter.
# --------------------------------------------------------------------------- #


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


def is_rate_limit_ban_error(exc: BaseException) -> bool:
    """True when `exc` is an IP ban (HTTP 418), not a plain 429.

    Binance documents that requests sent while banned extend the ban, so a
    caller must stop instead of retrying (WR-01).
    """
    return isinstance(exc, RateLimitBanError) or "RateLimitBan" in type(exc).__name__


def rate_limit_retry_after_seconds(exc: BaseException) -> int | None:
    """Whole seconds from the `Retry-After` header carried by a 429 or a 418, else None.

    Delegates to the shared SDK normalizer (`src/adapters/binance_errors.py`) so both agree:
    a bool, a negative or a non-int value, and any exception that is not the SDK's 418 or
    429 class, give None.
    """
    return error_facts_from_exception(exc).retry_after_seconds


# Binance error code for an unknown symbol (`-1121 Invalid symbol.`). The SDK
# raises `BadRequestError` for HTTP 400 with the Binance code in `status_code`.
# The freeze CLI and backfill treat it as "no data for this symbol" and fall
# back to the archive instead of failing the run (D-08).
INVALID_SYMBOL_CODE: int = -1121


def is_invalid_symbol_error(exc: BaseException) -> bool:
    """True when `exc` is the SDK's 400 carrying Binance code -1121 (invalid symbol).

    Lives here because this module is the only one allowed to import the SDK.
    Any other 400 code, non-SDK error or rate-limit error is False.
    """
    return isinstance(exc, BadRequestError) and exc.status_code == INVALID_SYMBOL_CODE


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
        self._public = BinancePublicMarketData(sdk_client=self._sdk)

    # ----- klines ---------------------------------------------------------- #

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]:
        """Fetch one page of klines; delegates to `BinancePublicMarketData` (plan 16-03)."""
        return await self._public.klines(symbol, interval, start_ms, end_ms, limit)

    async def mark_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[MarkKline]:
        """Fetch one page of mark-price klines; delegates to `BinancePublicMarketData`."""
        return await self._public.mark_klines(symbol, interval, start_ms, end_ms, limit)

    # ----- open interest --------------------------------------------------- #

    async def open_interest(self, symbol: str) -> OiSnapshot:
        return await self._public.open_interest(symbol)

    async def open_interest_statistics(
        self,
        symbol: str,
        period: str,
        limit: int = 30,
    ) -> list[OiSnapshot]:
        """Opportunistic historical OI harvest (D-08); delegates to the public adapter."""
        return await self._public.open_interest_statistics(symbol, period, limit)

    # ----- funding rate ---------------------------------------------------- #

    async def funding_rate(
        self,
        symbol: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1000,
    ) -> list[FundingTick]:
        return await self._public.funding_rate(symbol, start_ms, end_ms, limit)

    # ----- server time ----------------------------------------------------- #

    async def server_time(self) -> datetime:
        """Binance server time as a UTC datetime (D-25); delegates to the public adapter."""
        return await self._public.server_time()

    # ----- exchange info --------------------------------------------------- #

    async def exchange_info(self) -> list[SymbolFilters]:
        return await self._public.exchange_info()

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
        a not-found error (Demo: BadRequestError code -2013 "Order
        does not exist."). The sweeper treats `found=False`
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
            # Demo answers a missing algo order with -2013 "Order does not
            # exist." (observed); -2011 is kept for the cancel-path form.
            if _is_order_not_found_error(exc):
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
                    return await _do_cancel()
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
                    return await _do_cancel()
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
        raises a not-found error (-2013 NO_SUCH_ORDER or -2011).

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
            # Only a definitive not-found code (-2013 NO_SUCH_ORDER, -2011) is
            # "not found". Any other error RAISES and the execution manager
            # treats a raising probe as UNKNOWN -> SAFE_MODE (fail closed,
            # 09-REVIEW CR-09): a wrong mapping would enable a duplicate order.
            if _is_order_not_found_error(exc):
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
