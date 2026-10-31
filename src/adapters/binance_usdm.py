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
  | __init__(sdk_client, *, rest_gate, sleep) | (no SDK call) | plan 18-10: `rest_gate` is the process-wide RestRateLimitGate (checked before every REST call, records a 418 or 429; also handed to the inner BinancePublicMarketData); `sleep` serves only the waits of the STATUS_UNKNOWN cancel retry.  # noqa: E501
  | __init__(..., signed_call_policy, drift_guard, clock, on_clock_skew) | (no SDK call) | plan 18-13: every signed method in this table passes `recv_window=signed_call_policy.recv_window_ms` explicitly through the one helper `_sdk_call` (all twenty SDK methods have a `recv_window` parameter in 17.4.0, pinned offline by tests/test_binance_usdm_signed_calls.py); no policy -> SignedCallPolicyMissing before any SDK call; a configured drift guard blocks `place_entry` only (EntriesBlocked); -1021 calls `on_clock_skew` once and is never retried.  # noqa: E501
  | user_commission_rate       | user_commission_rate(symbol, recv_window) | 17.4.0: `symbol` required (passed by keyword), `recv_window` explicit (plan 18-13); returns UserCommissionRateResponse with Optional str fields (symbol, makerCommissionRate, takerCommissionRate, rpiCommissionRate); strict parse, unknown raises, never zero (Phase 12, D-11).  # noqa: E501
  | account_information_snapshot | account_information_v3(recv_window) | plan 21-03: GET /fapi/v3/account; every field Optional[str] in the model, parsed strictly to Decimal (a missing or non-finite field raises, never a zero); `totalMarginBalance` is the equity field (D-02), `availableBalance` is not read.  # noqa: E501
  | account_balances_snapshot   | futures_account_balance_v3(recv_window) | plan 21-03: GET /fapi/v3/balance; reads asset, balance, crossUnPnl only; the account alias attribute is never read (D-21).  # noqa: E501
  | user_trades_in_window       | account_trade_list(symbol, start_time, end_time, from_id, recv_window) | plan 21-08: GET /fapi/v1/userTrades; page 1 sends start_time and end_time, later pages send `from_id` = last trade id + 1 and no time bounds (the endpoint refuses `fromId` with a time bound); trade ids must strictly increase, else ValueError; no `limit` is sent.  # noqa: E501
  | income_in_window            | get_income_history(income_type, start_time, end_time, page, recv_window) | plan 21-08: GET /fapi/v1/income; pages 1, 2, ... until an empty page; the free-text `info` field is never read; the funding source is unverified on Demo (0 rows in the recorded reads).  # noqa: E501
  | symbol_config_snapshot      | symbol_configuration(symbol, recv_window) | plan 22-01: GET /fapi/v1/symbolConfig (weight 5); `symbol`, `recv_window` Optional; one row for the symbol with `marginType` text, `leverage` StrictInt, `isAutoAddMargin` StrictBool and `maxNotionalValue` text; each parsed strictly (a missing or mistyped field raises, never a default).  # noqa: E501
  | leverage_brackets_snapshot   | notional_and_leverage_brackets(symbol, recv_window) | plan 22-01: GET /fapi/v1/leverageBracket; the answer is a oneOf wrapper (`actual_instance`: a list of entries or one entry), both unwrapped; `maintMarginRatio` and `cum` are SDK floats, converted with Decimal(repr(value)) (the object shape declares `cum` StrictInt only: SDK quirk); no bracket value is a constant of this project.  # noqa: E501
  | change_margin_type          | change_margin_type(symbol, margin_type, recv_window) | plan 22-06: POST /fapi/v1/marginType (weight 1); `margin_type` is `ChangeMarginTypeMarginTypeEnum` (ISOLATED, CROSSED) converted after a membership check; call kind PLACEMENT (mutating, never retried, never slept on); the answer body is not read; the same-type request is an exchange error (-4046), decided by a symbol_config_snapshot read.  # noqa: E501
  | change_initial_leverage     | change_initial_leverage(symbol, leverage, recv_window) | plan 22-06: POST /fapi/v1/leverage (weight 1); `leverage` a positive int (not a bool), no cap in the adapter (the guard owns it, D-02); call kind PLACEMENT (never retried); the answer body is not read.  # noqa: E501
  | account_config_snapshot     | futures_account_configuration(recv_window) | plan 21-03: GET /fapi/v1/accountConfig; reads multiAssetsMargin and dualSidePosition as strict bools, nothing else (OPS-02 is an owner attestation).  # noqa: E501

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
import math
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    GetIncomeHistoryIncomeTypeEnum,
)
from src.adapters.binance_clock import ClockDriftGuard, DriftBlockReason
from src.adapters.binance_errors import error_facts_from_exception
from src.adapters.binance_limits import SignedCallPolicy
from src.adapters.binance_public import (
    BinancePublicMarketData,
    _ms_to_utc,
)
from src.adapters.binance_public import FundingTick as FundingTick
from src.adapters.binance_public import Kline as Kline
from src.adapters.binance_public import LastPriceReading as LastPriceReading
from src.adapters.binance_public import MarkKline as MarkKline
from src.adapters.binance_public import MarkPriceReading as MarkPriceReading
from src.adapters.binance_public import OiSnapshot as OiSnapshot
from src.adapters.binance_public import SymbolFilters as SymbolFilters
from src.adapters.binance_public import _row_to_kline as _row_to_kline
from src.adapters.binance_public import _row_to_mark_kline as _row_to_mark_kline
from src.adapters.binance_ratelimit_gate import RestGateRefusal, RestRateLimitGate
from src.domain.exchange_errors import (
    CallKind,
    ErrorFacts,
    ExchangeErrorCategory,
    PreSendRefusal,
    classify,
    retry_eligible,
)
from src.domain.lot_filters import LotFilters

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
#
# Plan 18-10: they bound the STATUS_UNKNOWN cancel retry only (5xx, 408,
# network errors, -1006, -1007). A 429, a 418, a definitive rejection, an
# auth error or an unknown error is never retried (user record
# 18-DEC-O-18-01.md, amendment 2026-10-16: a cancel that meets a 429 fails
# at once and is left to reconciliation).
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


# --------------------------------------------------------------------------- #
# Signed calls (plan 18-13, D-14, F-505).
#
# Every signed SDK call goes through `BinanceUsdmAdapter._sdk_call`, which
# forwards the ratified `SignedCallPolicy.recv_window_ms` explicitly (no
# exchange default decides the replay window), runs the shared REST gate check
# first, records a 418 or 429 in the gate and notifies the optional -1021 hook.
# It never retries and never sleeps for any category.
#
# A -1008 (SYSTEM_THROTTLED, quick task 261020-g1a) is NOT recorded: it is the node's
# overload protection, not counted toward rate limits, and reduce-only / close-position
# orders are exempt from it. Recording it as a 429 paused every REST call of the process
# and refused the protective stop, the entry cancel and the emergency close. The call that
# got it is re-raised unchanged and never retried (a placement is never re-sent).
# --------------------------------------------------------------------------- #

# The categories recorded in the process-wide gate: a 418 (ban) and a 429 (pause) only.
_RATE_LIMIT_CATEGORIES: frozenset[ExchangeErrorCategory] = frozenset(
    {ExchangeErrorCategory.IP_BANNED, ExchangeErrorCategory.RATE_LIMITED}
)


class SignedCallPolicyMissing(PreSendRefusal):  # noqa: N818 - a refusal, not an error of the caller
    """A signed call refused before the gate and the SDK: no `SignedCallPolicy` is configured.

    Fail closed (D-14): without the ratified recvWindow a signed request would silently use
    the exchange default, a replay window nobody chose.
    """

    def __init__(self) -> None:
        super().__init__(
            "signed call refused before sending: no SignedCallPolicy configured "
            "(the recvWindow must be explicit)"
        )


class EntriesBlocked(PreSendRefusal):  # noqa: N818 - a refusal, not an error of the caller
    """A new entry refused before sending because the clock-drift guard blocks entries.

    `reason` is the guard's `DriftBlockReason` (never measured, measurement failed, out of
    limits, stale). Protective orders, cancels, queries and snapshots are never blocked by
    the drift guard.
    """

    def __init__(self, reason: DriftBlockReason) -> None:
        self.reason = reason
        super().__init__(f"new entry refused before sending: clock drift guard {reason}")


_MARKET_CLOSE_SIDES: frozenset[str] = frozenset({"BUY", "SELL"})
_MARKET_CLOSE_POSITION_SIDES: frozenset[str] = frozenset({"BOTH", "LONG", "SHORT"})
_MAX_CLIENT_ORDER_ID_LEN = 36


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
    """True only for a STATUS_UNKNOWN cancel failure (`retry_eligible(category, CANCEL)`).

    A refusal of the shared REST gate (a ban or a pause set meanwhile by any holder) is
    never retried; neither is a 429, a 418, ORDER_ABSENT, a definitive rejection, an auth
    error, an unknown code or a non-SDK exception (programming errors included).
    """
    if isinstance(exc, RestGateRefusal):
        return False
    category = classify(error_facts_from_exception(exc), CallKind.CANCEL)
    return retry_eligible(category, CallKind.CANCEL)


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
    # Plan 24-21 (D-34): True when the row carried `entry_price` as a float instead of the
    # exchange's own string. The value is then exact text of that float, never rounded, but it may
    # hold float noise (84816.40000000001); readers that need the exact price check this flag.
    entry_price_from_float: bool = False


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
class MarketCloseResult:
    """Result of `place_market_close` (new_order MARKET, risk-reducing, plan 19-08, D-15).

    `executed_quantity` and `average_price` are the fields the new-order response reported;
    None means the response did not carry the field (unknown, never zero). A MARKET order
    is normally acknowledged before it fills, so the caller confirms the real closed
    quantity by a position query, not by this result.
    """

    symbol: str
    client_order_id: str
    exchange_order_id: str
    side: str
    position_side: str
    status: str
    executed_quantity: Decimal | None
    average_price: Decimal | None
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
    # Plan 19-05 (research F8, D-10 REST fill source): what the exchange reports as executed.
    # None means the exchange omitted the field (unknown); it is never defaulted to zero.
    executed_quantity: Decimal | None = None
    average_price: Decimal | None = None


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


@dataclass(frozen=True)
class AccountAssetRow:
    """One row of the `assets` list of `account_information_v3` (plan 21-03).

    All four amounts are Decimal, parsed from the exchange text. The USDT row is the
    cross-check of the account equity: `margin_balance` equals the account-level
    `total_margin_balance` in single-asset mode (demo-observed, not mainnet). Other
    assets (USDC, BTC on the Demo account) are kept as their own rows; the account totals
    exclude them. `available_balance` (plan 22-10) is the free margin of the asset: the
    cross-check of the account-level `available_balance`, never an equity.
    """

    asset: str
    wallet_balance: Decimal
    unrealized_profit: Decimal
    margin_balance: Decimal
    available_balance: Decimal


@dataclass(frozen=True)
class AccountInformationSnapshot:
    """Result of `account_information_snapshot` (GET /fapi/v3/account, plan 21-03, D-02).

    The equity field is `total_margin_balance` ("USDT only in single-asset mode" in the SDK
    17.4.0 model; on Demo equal to `total_wallet_balance + total_unrealized_profit` and to
    the USDT row's `margin_balance`, all 4999.09343961, demo-observed, not mainnet). The
    choice and the identity checks belong to the pure resolver of plan 21-04; this value
    only carries the parsed numbers. Since Phase 22 (plan 22-10) the same answer also carries
    `available_balance` and `total_open_order_initial_margin` (the free-margin figures of the
    margin check, D-13): they share the equity's stamp and are never used as the equity.
    `assets` keeps the response order.
    """

    total_margin_balance: Decimal
    total_wallet_balance: Decimal
    total_unrealized_profit: Decimal
    available_balance: Decimal
    total_open_order_initial_margin: Decimal
    assets: tuple[AccountAssetRow, ...]


@dataclass(frozen=True)
class AccountBalanceRow:
    """One row of `account_balances_snapshot` (GET /fapi/v3/balance, plan 21-03, D-02).

    `balance` is the wallet balance of `asset`; `cross_unrealized_pnl` its cross unrealized
    PnL. Only these three fields are read. The account alias field of the endpoint is
    deliberately never read, stored or logged (D-21), so this dataclass has no field for it.
    """

    asset: str
    balance: Decimal
    cross_unrealized_pnl: Decimal


@dataclass(frozen=True)
class AccountConfigSnapshot:
    """Result of `account_config_snapshot` (GET /fapi/v1/accountConfig, plan 21-03).

    Both flags are detected, never assumed: a missing or non-bool value raises. The other
    fields of the response (canWithdraw, canTrade, feeTier, ...) are not read: the
    no-withdraw check is an owner attestation (OPS-02, D-21), not an adapter read.
    """

    multi_assets_margin: bool
    dual_side_position: bool


@dataclass(frozen=True)
class SymbolConfigSnapshot:
    """Result of `symbol_config_snapshot` (GET /fapi/v1/symbolConfig, weight 5, plan 22-01).

    The only read that returns the margin type, the leverage, `isAutoAddMargin` and
    `maxNotionalValue` of one symbol (the `positionRisk` answer of the current API has no
    leverage field, 22-RESEARCH 2.3). `margin_type` is kept as the exchange text: the CROSSED
    casing is demo-observed, not mainnet; the ISOLATED casing is ASSUMED until the owner-run
    case records it (22-RESEARCH A5, D-18). Choosing a target and comparing it with this
    snapshot belong to the guard of plan 22-11, not to the adapter.
    """

    symbol: str
    margin_type: str
    leverage: int
    is_auto_add_margin: bool
    max_notional_value: Decimal


@dataclass(frozen=True)
class LeverageBracketRow:
    """One bracket of `leverage_brackets_snapshot` (plan 22-01, D-08).

    `maint_margin_ratio` and `cum` (the cumulative maintenance amount) are the exchange numbers
    as exact Decimals. The SDK 17.4.0 models carry them as floats; the adapter converts them with
    `Decimal(repr(value))`, never `Decimal(float)` (22-RESEARCH Pitfall 4).
    """

    bracket: int
    initial_leverage: int
    notional_floor: Decimal
    notional_cap: Decimal
    maint_margin_ratio: Decimal
    cum: Decimal


@dataclass(frozen=True)
class SymbolLeverageBrackets:
    """Result of `leverage_brackets_snapshot` (GET /fapi/v1/leverageBracket, plan 22-01).

    The bracket numbers are INPUTS read from the exchange, never defaults: no bracket value,
    maintenance ratio or leverage may become a constant of `src/` or a parameter (D-08). The
    recorded Demo table differs from the mainnet figure (Demo first bracket 125x, the mainnet
    figure of the official change-log is 150x; demo-observed, not mainnet, 22-RESEARCH 2.4).
    `notional_coef` is carried as read (None when absent) and is not interpreted here: the guard
    refuses a value other than 1. `brackets` keeps the response order.
    """

    symbol: str
    notional_coef: Decimal | None
    brackets: tuple[LeverageBracketRow, ...]


# The exchange window rule for userTrades (SDK 17.4.0 docstring): startTime to endTime may not
# be longer than seven days.
_MAX_WINDOW = timedelta(days=7)
_EPOCH_UTC = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class UserTradeRow:
    """One fill of `user_trades_in_window` (GET /fapi/v1/userTrades, plan 21-08).

    `realized_pnl` and `commission` are strict Decimals of the exchange text (USDT for the
    USDT-margined symbols); `trade_id` is the key space of the user-data stream's `t` field.
    """

    symbol: str
    order_id: int
    trade_id: int
    realized_pnl: Decimal
    commission: Decimal
    commission_asset: str
    margin_asset: str
    time_utc: datetime


@dataclass(frozen=True)
class IncomeRow:
    """One row of `income_in_window` (GET /fapi/v1/income, plan 21-08).

    The free-text `info` field of the response has no counterpart here: it is never read.
    `symbol` is None for an account-level row, `trade_id` None when the exchange sent none.
    """

    symbol: str | None
    income_type: str
    income: Decimal
    asset: str
    tran_id: int
    trade_id: str | None
    time_utc: datetime


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

    `rest_gate` (keyword only) is the process-wide `RestRateLimitGate` (plan
    18-10): every call that reaches `self._sdk.rest_api` runs `rest_gate.check()`
    first (also before every attempt of the STATUS_UNKNOWN cancel retry) and a
    418 or 429 it meets is recorded in the gate, then the original exception is
    re-raised; nothing is retried because of a 418 or a 429. The inner
    `BinancePublicMarketData` gets the same gate, so the public delegations
    (`server_time` included) are refused during a ban or a pause too. Without a
    gate the public delegations are neither refused nor recorded and a 418 or
    429 raises after one call; the signed methods cannot run without a gate
    (plan 18-13: a signed policy requires it). No wait exists in this module (the ban and pause lengths are the user's,
    held by the gate's `RateLimitPolicy`).

    `sleep` (keyword only, default `asyncio.sleep`) serves only the waits of
    the STATUS_UNKNOWN cancel retry, so tests inject a recording sleep.

    `signed_call_policy` (keyword only, plan 18-13) is the ratified
    `SignedCallPolicy` loaded from the limits file: every signed SDK call
    carries `recv_window=signed_call_policy.recv_window_ms`. Without it every
    signed method raises `SignedCallPolicyMissing` before the gate check and
    before the SDK is touched (fail closed); the public-data delegations carry
    no recvWindow and are unaffected. A policy requires `rest_gate`, and the
    gate's policy must equal `signed_call_policy.rate_limit` (ValueError).

    `drift_guard` and `clock` (keyword only): when a `ClockDriftGuard` is
    given, `place_entry` raises `EntriesBlocked` before any SDK call while
    `drift_guard.entries_allowed(clock())` is False. Protective placement,
    cancels, queries and snapshots never consult the guard. A guard requires
    a clock (ValueError).

    `on_clock_skew` (keyword only): called once when a signed call answers
    -1021 (CLOCK_SKEW), e.g. `ClockDriftGuard.note_clock_skew_error`; the
    original exception is re-raised and the call is never retried (D-14).
    """

    def __init__(
        self,
        sdk_client: DerivativesTradingUsdsFutures | None = None,
        *,
        rest_gate: RestRateLimitGate | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        signed_call_policy: SignedCallPolicy | None = None,
        drift_guard: ClockDriftGuard | None = None,
        clock: Callable[[], datetime] | None = None,
        on_clock_skew: Callable[[], None] | None = None,
    ) -> None:
        if signed_call_policy is not None:
            if not isinstance(signed_call_policy, SignedCallPolicy):
                raise TypeError("signed_call_policy must be a SignedCallPolicy")
            if rest_gate is None:
                raise ValueError(
                    "signed_call_policy requires rest_gate: signed calls use the one "
                    "process-wide RestRateLimitGate"
                )
            if rest_gate.policy != signed_call_policy.rate_limit:
                raise ValueError(
                    "rest_gate.policy must equal signed_call_policy.rate_limit "
                    "(one ratified rate-limit policy per process)"
                )
        if drift_guard is not None:
            if not isinstance(drift_guard, ClockDriftGuard):
                raise TypeError("drift_guard must be a ClockDriftGuard")
            if clock is None:
                raise ValueError("drift_guard requires clock (an aware-UTC clock callable)")
        if on_clock_skew is not None and not callable(on_clock_skew):
            raise TypeError("on_clock_skew must be callable")
        self._sdk: DerivativesTradingUsdsFutures = sdk_client or DerivativesTradingUsdsFutures()
        self._rest_gate = rest_gate
        self._sleep: Callable[[float], Awaitable[None]] = (
            sleep if sleep is not None else asyncio.sleep
        )
        self._signed_call_policy = signed_call_policy
        self._drift_guard = drift_guard
        self._clock = clock
        self._on_clock_skew = on_clock_skew
        self._public = BinancePublicMarketData(sdk_client=self._sdk, rest_gate=rest_gate)

    @staticmethod
    def error_facts(exc: BaseException) -> ErrorFacts:
        """The Phase 18 `ErrorFacts` (class, int code, Retry-After) of `exc` (plan 19-08, D-21).

        Lets the SDK-free execution core call `classify` without importing the SDK
        normalizer. Facts only: no exception message text is read, and the taxonomy and
        `classify` are unchanged. A `PreSendRefusal` is not an SDK error and yields NON_SDK
        facts; the caller tests `isinstance(exc, PreSendRefusal)` first.
        """
        return error_facts_from_exception(exc)

    def _require_signed_policy(self) -> tuple[SignedCallPolicy, RestRateLimitGate]:
        """The policy and the shared gate of a signed call, or `SignedCallPolicyMissing`."""
        policy = self._signed_call_policy
        gate = self._rest_gate
        if policy is None or gate is None:
            raise SignedCallPolicyMissing()
        return policy, gate

    def _require_entries_allowed(self) -> None:
        """Raise `EntriesBlocked` while the configured drift guard blocks new entries."""
        guard = self._drift_guard
        if guard is None:
            return
        if self._clock is None:  # pragma: no cover - the constructor refuses it
            raise ValueError("drift_guard requires clock")
        now = self._clock()
        if guard.entries_allowed(now):
            return
        reason = guard.blocked_reason(now)
        if reason is None:  # pragma: no cover - entries_allowed means blocked_reason is None
            raise RuntimeError("drift guard disagreed with itself")
        raise EntriesBlocked(reason)

    async def _sdk_call[R](self, call_kind: CallKind, method: Callable[..., R], **kwargs: Any) -> R:
        """The one path of every signed SDK call (plan 18-13).

        In order: refuse without a policy (`SignedCallPolicyMissing`, nothing checked or
        sent); run the shared gate check (a ban or a pause refuses unchanged, nothing sent);
        run `method(recv_window=<policy value>, **kwargs)` in a worker thread. On an
        exception: classify it with `call_kind`; record a 418 or 429 in the gate (never a
        -1008 SYSTEM_THROTTLED, which pauses nothing); call the
        -1021 hook once for CLOCK_SKEW (a hook failure is logged by type name only); then
        re-raise the ORIGINAL exception object. Never retries, never sleeps.
        """
        policy, gate = self._require_signed_policy()
        gate.check()
        try:
            return await asyncio.to_thread(method, recv_window=policy.recv_window_ms, **kwargs)
        except Exception as exc:
            facts = error_facts_from_exception(exc)
            category = classify(facts, call_kind)
            if category in _RATE_LIMIT_CATEGORIES:
                gate.record(
                    category,
                    facts.retry_after_seconds,
                    ban_until_epoch_ms=facts.ban_until_epoch_ms,
                )
            elif category is ExchangeErrorCategory.CLOCK_SKEW and self._on_clock_skew is not None:
                try:
                    self._on_clock_skew()
                except Exception as hook_exc:  # noqa: BLE001 - never replaces the original
                    log.error(
                        "adapter.signed_call.on_clock_skew_failed",
                        call_kind=call_kind.value,
                        error_class=type(hook_exc).__name__,
                    )
            raise

    def _cancel_retrying(self) -> tenacity.AsyncRetrying:
        """The bounded STATUS_UNKNOWN cancel retry (the four `_RECONCILER_CANCEL_*` ceilings)."""
        return tenacity.AsyncRetrying(
            retry=tenacity.retry_if_exception(_cancel_retry_predicate),
            stop=tenacity.stop_after_attempt(_RECONCILER_CANCEL_MAX_ATTEMPTS)
            | tenacity.stop_after_delay(_RECONCILER_CANCEL_MAX_DELAY_SECONDS),
            wait=tenacity.wait_random_exponential(
                multiplier=_RECONCILER_CANCEL_WAIT_MULTIPLIER_SECONDS,
                max=_RECONCILER_CANCEL_WAIT_MAX_SECONDS,
            ),
            sleep=self._sleep,
            reraise=True,
        )

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

    # ----- live mark price (plan 19-05, D-06) ------------------------------- #

    async def get_mark_price(self, *, symbol: str) -> MarkPriceReading:
        """The live mark price of `symbol`; delegates to the public reader (shared REST gate).

        The adapter takes no clock: the execution manager measures the age of the reading
        with its injected clock, read after this call (19-REVIEW CR-01).
        """
        return await self._public.mark_price(symbol)

    # ----- live last price (quick task 261020-l4p, 19-REVIEW WR-06 work item) - #

    async def get_last_price(self, *, symbol: str) -> LastPriceReading:
        """The latest traded price of `symbol`; delegates to the public reader (shared REST gate).

        `GET /fapi/v1/ticker/price` for one symbol. Like `get_mark_price` the adapter takes no
        clock: the execution manager measures the age with its injected clock after the reads.
        """
        return await self._public.last_price(symbol)

    # ----- exchange info --------------------------------------------------- #

    async def exchange_info(self, symbols: Sequence[str] | None = None) -> list[SymbolFilters]:
        """The exchange constraints; `symbols` limits the strict validation (plan 19-08)."""
        return await self._public.exchange_info(symbols)

    async def symbol_lot_filters(self, *, symbol: str) -> LotFilters:
        """The live `LotFilters` of `symbol` from exchangeInfo (plan 19-08, D-16, D-19).

        LOT_SIZE, MARKET_LOT_SIZE, tick and min notional are read at call time, never taken
        from a default. A symbol that exchangeInfo does not list, a missing LOT_SIZE max or a
        missing MARKET_LOT_SIZE field raises `ValueError` naming the field and the symbol; a
        gate refusal or an SDK error of the read propagates unchanged. Whether a failed read
        during an emergency close may fall back to the plan-time snapshot is owner-open
        (Q3): this method only reads live and raises.
        """
        rows = [f for f in await self.exchange_info([symbol]) if f.symbol == symbol]
        if not rows:
            raise ValueError(f"exchangeInfo does not list symbol {symbol!r}")
        info = rows[0]
        for name in (
            "max_quantity",
            "market_lot_min_quantity",
            "market_lot_max_quantity",
            "market_lot_step_size",
        ):
            if getattr(info, name) is None:
                raise ValueError(f"exchangeInfo {name} is missing for symbol {symbol!r}")
        assert info.max_quantity is not None
        assert info.market_lot_min_quantity is not None
        assert info.market_lot_max_quantity is not None
        assert info.market_lot_step_size is not None
        return LotFilters(
            symbol=symbol,
            price_tick_size=info.price_tick_size,
            lot_min_quantity=info.min_quantity,
            lot_max_quantity=info.max_quantity,
            lot_step_size=info.quantity_step_size,
            market_lot_min_quantity=info.market_lot_min_quantity,
            market_lot_max_quantity=info.market_lot_max_quantity,
            market_lot_step_size=info.market_lot_step_size,
            min_notional=info.min_notional,
        )

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
        response = await self._sdk_call(
            CallKind.QUERY,
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
        response = await self._sdk_call(
            CallKind.QUERY,
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
        response = await self._sdk_call(
            CallKind.QUERY,
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
            response = await self._sdk_call(
                CallKind.QUERY,
                self._sdk.rest_api.query_algo_order,
                client_algo_id=client_algo_id,
            )
        except Exception as exc:  # noqa: BLE001 - SDK wraps unknown codes
            # Only ORDER_ABSENT of a QUERY (-2013, observed on Demo, or -2011
            # as the int code of an SDK 400/404) is "not found"; everything
            # else, a gate refusal included, raises (fail closed).
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
        sweeper does the probe before calling cancel). Only a
        STATUS_UNKNOWN failure is retried, within the four
        `_RECONCILER_CANCEL_*` ceilings; every attempt passes the shared
        REST gate first. The cancel is idempotent on retries because
        `orig_client_order_id` is the deterministic 36-char ID from
        `derive_client_order_id`.

        ORDER_ABSENT of a CANCEL (-2011 or -2013 as the int code of an SDK
        400/404) is success: the post-condition the caller wanted holds.

        Args:
            symbol: The trading pair (Binance requires it).
            orig_client_order_id: The deterministic client_order_id
                minted by `derive_client_order_id`.

        Raises:
            A 429, a 418, a gate refusal, a definitive rejection, an auth
            error or an unknown error after one SDK call; a STATUS_UNKNOWN
            error after the bounded retries are exhausted.
        """

        async def _do_cancel() -> CancelOrderResponse:
            response = await self._sdk_call(
                CallKind.CANCEL,
                self._sdk.rest_api.cancel_order,
                symbol=symbol,
                orig_client_order_id=orig_client_order_id,
            )
            return response.data()

        async def _do_cancel_with_retry() -> CancelOrderResponse:
            async for attempt in self._cancel_retrying():
                with attempt:
                    return await _do_cancel()
            raise RuntimeError("unreachable: tenacity.AsyncRetrying exhausted without reraise")

        try:
            await _do_cancel_with_retry()
        except Exception as exc:  # noqa: BLE001 - SDK wraps unknown codes
            if _is_order_absent(exc, CallKind.CANCEL):
                log.info(
                    "adapter.cancel_normal_order.already_canceled",
                    symbol=symbol,
                    orig_client_order_id=orig_client_order_id,
                    error_class=type(exc).__name__,
                    code=error_facts_from_exception(exc).code,
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

        Per T-8-32 + EXECUTION_SPEC 10: query-by-ID-first posture,
        idempotent on retries. Only a STATUS_UNKNOWN failure is retried,
        within the four `_RECONCILER_CANCEL_*` ceilings, every attempt
        passing the shared REST gate first. ORDER_ABSENT of a CANCEL is
        success.

        Args:
            symbol: The trading pair (Binance requires it).
            client_algo_id: The deterministic algo_client_id minted by
                `derive_algo_client_id`.

        Raises:
            A 429, a 418, a gate refusal, a definitive rejection, an auth
            error or an unknown error after one SDK call; a STATUS_UNKNOWN
            error after the bounded retries are exhausted.
        """

        async def _do_cancel() -> CancelAlgoOrderResponse:
            response = await self._sdk_call(
                CallKind.CANCEL,
                self._sdk.rest_api.cancel_algo_order,
                client_algo_id=client_algo_id,
            )
            return response.data()

        async def _do_cancel_with_retry() -> CancelAlgoOrderResponse:
            async for attempt in self._cancel_retrying():
                with attempt:
                    return await _do_cancel()
            raise RuntimeError("unreachable: tenacity.AsyncRetrying exhausted without reraise")

        try:
            await _do_cancel_with_retry()
        except Exception as exc:  # noqa: BLE001 - SDK wraps unknown codes
            if _is_order_absent(exc, CallKind.CANCEL):
                log.info(
                    "adapter.cancel_algo_order.already_canceled",
                    symbol=symbol,
                    client_algo_id=client_algo_id,
                    error_class=type(exc).__name__,
                    code=error_facts_from_exception(exc).code,
                )
                return
            raise

    # ----- placement surface (Phase 9, plan 09-01) ----------------------- #
    # These methods are the FIRST line of defense — they place new orders
    # on the exchange. Each makes exactly one SDK call for every error
    # class (never retried, 09-REVIEW CR-09, D-11), passes the shared REST
    # gate first (refused without sending during a 418 ban or a 429 pause)
    # and uses the string-mediated Decimal-to-edge conversion (RESEARCH
    # Pattern 1). The execution core never imports the SDK; only this
    # adapter does.

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
        good_till_date: int | None = None,
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
            time_in_force: "GTC" for LIMIT entries, or "GTD" (exchange-side expiry
                backstop, plan 19-05) which requires `good_till_date`.
            quantity: The quantized quantity (Decimal).
            price: The zone-mid limit price (Decimal).
            new_client_order_id: The deterministic 36-char client_order_id
                from `derive_client_order_id`.
            good_till_date: The expiry in epoch milliseconds, an `int`; required with GTD and
                refused with any other time in force. None (the only default) means "not
                GTD". The adapter does not compute or range-check it (the pure core does and
                Binance validates server-side).

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
        # Plan 19-05: argument validation first (programming errors, nothing sent).
        if good_till_date is not None and (
            isinstance(good_till_date, bool) or not isinstance(good_till_date, int)
        ):
            raise TypeError("good_till_date must be an int (epoch milliseconds)")
        if time_in_force == "GTD" and good_till_date is None:
            raise ValueError("time_in_force GTD requires good_till_date")
        if good_till_date is not None and time_in_force != "GTD":
            raise ValueError("good_till_date is only valid with time_in_force GTD")

        # Plan 18-13: no policy refuses first; then a configured drift guard refuses a NEW
        # entry while it does not allow entries (never measured, failed, out of limits,
        # stale), before the gate check and before any SDK call.
        self._require_signed_policy()
        self._require_entries_allowed()

        from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
            NewOrderResponse,
        )
        from binance_sdk_derivatives_trading_usds_futures.rest_api.models.enums import (
            NewOrderSideEnum,
            NewOrderTimeInForceEnum,
            NewOrderTypeEnum,
        )

        # goodTillDate is sent only for GTD, so the GTC wire is byte-identical to before.
        gtd_kwargs: dict[str, Any] = {}
        if good_till_date is not None:
            gtd_kwargs["good_till_date"] = good_till_date
        response = await self._sdk_call(
            CallKind.PLACEMENT,
            self._sdk.rest_api.new_order,
            symbol=symbol,
            side=NewOrderSideEnum(side),
            type=NewOrderTypeEnum.LIMIT,
            position_side=position_side,
            time_in_force=NewOrderTimeInForceEnum(time_in_force),
            quantity=_decimal_to_wire(quantity),
            price=_decimal_to_wire(price),
            new_client_order_id=new_client_order_id,
            **gtd_kwargs,
        )
        result: NewOrderResponse = response.data()
        return _new_order_to_entry_result(result)

    async def place_market_close(
        self,
        *,
        symbol: str,
        side: str,
        position_side: str,
        quantity: Decimal,
        new_client_order_id: str,
    ) -> MarketCloseResult:
        """Send ONE MARKET order that only reduces the position (plan 19-08, D-15, D034).

        D034 approves a reduce-only close when the stop is rejected or unconfirmed. Payload
        (19-NOTES "Emergency close"): One-way (`position_side` BOTH) sends
        `reduceOnly=true` with the closing side; Hedge (LONG or SHORT) sends an explicit
        `positionSide` and no `reduceOnly` (Binance refuses it in Hedge Mode); the side must
        close the leg (SELL closes LONG, BUY closes SHORT), otherwise the order would add
        exposure and `ValueError` is raised before anything is sent. Hedge is not verified
        against the exchange (V1 must not enable it).

        Exactly one SDK call through the shared gate path: never retried and never blocked
        by the clock-drift guard, which blocks NEW entries only (a risk-reducing call must
        not wait for a clock measurement). A gate pause or ban still refuses it with nothing
        sent (owner-open Q4 / Phase 18 src/WR-12: whether risk-reducing calls get an exemption
        is the owner's decision; none is added here). On an ambiguous failure the caller
        queries by the deterministic `new_client_order_id` before any resend.

        Args:
            symbol: The trading pair.
            side: The closing side, "BUY" or "SELL".
            position_side: "BOTH" (One-way) or "LONG"/"SHORT" (Hedge).
            quantity: A positive finite Decimal, already valid under the live lot filters.
            new_client_order_id: The caller's deterministic id, 1..36 characters.

        Raises:
            ValueError / TypeError: invalid arguments (nothing sent), or a response without
                identity or update time (flag, never fabricate).
            Any SDK or gate error of the single attempt, unchanged.
        """
        if side not in _MARKET_CLOSE_SIDES:
            raise ValueError(f"side must be BUY or SELL, got {side!r}")
        if position_side not in _MARKET_CLOSE_POSITION_SIDES:
            raise ValueError(f"position_side must be BOTH, LONG or SHORT, got {position_side!r}")
        if (position_side == "LONG" and side != "SELL") or (
            position_side == "SHORT" and side != "BUY"
        ):
            raise ValueError(
                f"a {side} order on position_side {position_side} would add exposure; "
                "a close must be SELL on LONG or BUY on SHORT"
            )
        if not isinstance(quantity, Decimal):
            raise TypeError(f"quantity must be Decimal, got {type(quantity).__name__}")
        if not quantity.is_finite() or quantity <= 0:
            raise ValueError("quantity must be a finite Decimal > 0")
        if (
            not isinstance(new_client_order_id, str)
            or new_client_order_id == ""
            or len(new_client_order_id) > _MAX_CLIENT_ORDER_ID_LEN
        ):
            raise ValueError(
                f"new_client_order_id must be 1..{_MAX_CLIENT_ORDER_ID_LEN} characters"
            )

        from binance_sdk_derivatives_trading_usds_futures.rest_api.models.enums import (
            NewOrderReduceOnlyEnum,
            NewOrderSideEnum,
            NewOrderTypeEnum,
        )

        # One-way only: reduceOnly. Hedge omits the parameter (the consistency check above
        # already guarantees the Hedge order cannot add exposure).
        reduce_only_kwargs: dict[str, Any] = {}
        if position_side == "BOTH":
            reduce_only_kwargs["reduce_only"] = NewOrderReduceOnlyEnum.TRUE
        response = await self._sdk_call(
            CallKind.PLACEMENT,
            self._sdk.rest_api.new_order,
            symbol=symbol,
            side=NewOrderSideEnum(side),
            type=NewOrderTypeEnum.MARKET,
            position_side=position_side,
            quantity=_decimal_to_wire(quantity),
            new_client_order_id=new_client_order_id,
            **reduce_only_kwargs,
        )
        return _new_order_to_market_close_result(response.data())

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
        response = await self._sdk_call(
            CallKind.PLACEMENT,
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
            response = await self._sdk_call(
                CallKind.QUERY,
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

        response = await self._sdk_call(
            CallKind.QUERY, self._sdk.rest_api.get_current_position_mode
        )
        raw: GetCurrentPositionModeResponse = response.data()
        # Detected, never assumed: a dropped/renamed field must not read as one-way.
        if not isinstance(raw.dual_side_position, bool):
            raise ValueError("dualSidePosition missing or not a bool")
        return PositionModeResult(dual_side_position=raw.dual_side_position)

    async def user_commission_rate(self, symbol: str) -> CommissionRates:
        """Read the account's maker/taker commission rate for one symbol.

        GET /fapi/v1/commissionRate (USER_DATA, IP weight 20) through the
        official SDK `rest_api.user_commission_rate(symbol, recv_window)`;
        `symbol` is passed by keyword and `recv_window` is the ratified
        `SignedCallPolicy` value (plan 18-13). The `rpiCommissionRate`
        field is ignored.

        Flag-never-fabricate (D-09, D-11): a missing, non-decimal,
        non-finite, negative, above-0.01 or wrong-symbol field raises
        `ValueError` — the adapter never returns a zero to mean unknown.
        A symbol that is empty, not a str, padded or not upper-case raises `ValueError`
        before any request (the call costs weight 20). A negative maker rate stays a refusal
        (owner decision D-22, Phase 12 review IN-01).
        There is no retry and no fallback value; an SDK exception
        propagates unchanged. The adapter takes no clock: the caller stamps
        `observed_at_utc` when it builds the risk-layer `AccountCommission`,
        and runtime wiring (refresh loop, TTL) is Phase 24.

        Returns:
            A frozen `CommissionRates` for the requested symbol.
        """
        # IN-01 (plan 24-15): a malformed symbol must not spend the weight-20 call.
        if (
            not isinstance(symbol, str)
            or symbol == ""
            or symbol != symbol.strip()
            or symbol != symbol.upper()
        ):
            raise ValueError("symbol must be a non-empty upper-case string")
        from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
            UserCommissionRateResponse,
        )

        response = await self._sdk_call(
            CallKind.QUERY, self._sdk.rest_api.user_commission_rate, symbol=symbol
        )
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

    async def account_information_snapshot(self) -> AccountInformationSnapshot:
        """Read the account equity and free-margin figures (GET /fapi/v3/account, plan 21-03).

        Phase 22 (plan 22-10) reads `availableBalance` and `totalOpenOrderInitialMargin` from the
        same answer for the margin check; they are never the equity.

        Through the official SDK `rest_api.account_information_v3(recv_window)` and the one
        signed helper `_sdk_call` (policy, shared REST gate, never retried; an SDK exception
        propagates unchanged). Every amount is parsed as a Decimal from the exchange text;
        a missing, empty, non-decimal or non-finite field raises `ValueError` naming the
        field only, never a zero (D-04). The adapter takes no clock (the caller stamps the
        reading time before the call) and logs nothing about the response.
        """
        response = await self._sdk_call(CallKind.QUERY, self._sdk.rest_api.account_information_v3)
        raw = response.data()
        if raw is None:
            raise ValueError("account information response empty: refusing to fabricate")
        raw_assets = raw.assets
        if raw_assets is None:
            raise ValueError("account field assets missing: refusing to fabricate")
        assets = tuple(_row_to_account_asset(item) for item in raw_assets)
        return AccountInformationSnapshot(
            total_margin_balance=_require_exchange_decimal(
                raw.total_margin_balance, "totalMarginBalance"
            ),
            total_wallet_balance=_require_exchange_decimal(
                raw.total_wallet_balance, "totalWalletBalance"
            ),
            total_unrealized_profit=_require_exchange_decimal(
                raw.total_unrealized_profit, "totalUnrealizedProfit"
            ),
            available_balance=_require_exchange_decimal(raw.available_balance, "availableBalance"),
            total_open_order_initial_margin=_require_exchange_decimal(
                raw.total_open_order_initial_margin, "totalOpenOrderInitialMargin"
            ),
            assets=assets,
        )

    async def account_balances_snapshot(self) -> tuple[AccountBalanceRow, ...]:
        """Read the per-asset balances (GET /fapi/v3/balance, USER_DATA, plan 21-03).

        Through the official SDK `rest_api.futures_account_balance_v3(recv_window)` and the
        one signed helper `_sdk_call` (shared REST gate, never retried). Only `asset`,
        `balance` and `crossUnPnl` of each row are read; the account alias attribute is
        never touched (D-21). Strict Decimal parse as `account_information_snapshot` (D-04).
        """
        response = await self._sdk_call(
            CallKind.QUERY, self._sdk.rest_api.futures_account_balance_v3
        )
        raw = response.data()
        if raw is None:
            raise ValueError("account balance response empty: refusing to fabricate")
        rows = raw if isinstance(raw, list) else [raw]
        out: list[AccountBalanceRow] = []
        for item in rows:
            asset = item.asset
            if not isinstance(asset, str) or asset.strip() == "":
                raise ValueError("account field asset missing or empty: refusing to fabricate")
            out.append(
                AccountBalanceRow(
                    asset=asset,
                    balance=_require_exchange_decimal(item.balance, "balance"),
                    cross_unrealized_pnl=_require_exchange_decimal(item.cross_un_pnl, "crossUnPnl"),
                )
            )
        return tuple(out)

    async def account_config_snapshot(self) -> AccountConfigSnapshot:
        """Read the account mode flags (GET /fapi/v1/accountConfig, USER_DATA, plan 21-03).

        Through the official SDK `rest_api.futures_account_configuration(recv_window)` and
        `_sdk_call` (shared REST gate, never retried). `multiAssetsMargin` and
        `dualSidePosition` must be real bools, like `get_position_mode`: a dropped or
        renamed field must not read as a default. No other field is read (OPS-02 is an owner
        attestation, D-21).
        """
        response = await self._sdk_call(
            CallKind.QUERY, self._sdk.rest_api.futures_account_configuration
        )
        raw = response.data()
        if raw is None:
            raise ValueError("account config response empty: refusing to fabricate")
        if not isinstance(raw.multi_assets_margin, bool):
            raise ValueError("multiAssetsMargin missing or not a bool")
        if not isinstance(raw.dual_side_position, bool):
            raise ValueError("dualSidePosition missing or not a bool")
        return AccountConfigSnapshot(
            multi_assets_margin=raw.multi_assets_margin,
            dual_side_position=raw.dual_side_position,
        )

    async def symbol_config_snapshot(self, *, symbol: str) -> SymbolConfigSnapshot:
        """Read the margin type and leverage of one symbol (GET /fapi/v1/symbolConfig, plan 22-01).

        USER_DATA, IP weight 5, through the official SDK `rest_api.symbol_configuration(symbol,
        recv_window)` and `_sdk_call` (policy, shared REST gate, never retried). Exactly one row
        for the requested symbol is required; an empty answer, two rows or a row for another
        symbol raises. `marginType` must be non-empty text, `leverage` an int (not a bool) of at
        least 1, `isAutoAddMargin` a real bool and `maxNotionalValue` a finite decimal text: a
        dropped or renamed field must not read as a default. Every `ValueError` names the field
        only, never the value, and nothing about the response is logged. The adapter takes no
        clock.
        """
        response = await self._sdk_call(
            CallKind.QUERY, self._sdk.rest_api.symbol_configuration, symbol=symbol
        )
        raw = response.data()
        if raw is None:
            raise ValueError("symbol config response empty: refusing to fabricate")
        rows = raw if isinstance(raw, list) else [raw]
        if len(rows) != 1:
            raise ValueError("symbol config answer must hold exactly one row for the symbol")
        row = rows[0]
        if row.symbol != symbol:
            raise ValueError("symbol config row is for another symbol: refusing to use it")
        margin_type = row.margin_type
        if not isinstance(margin_type, str) or margin_type.strip() == "":
            raise ValueError("marginType missing or not text: refusing to fabricate")
        leverage = row.leverage
        if isinstance(leverage, bool) or not isinstance(leverage, int) or leverage < 1:
            raise ValueError("leverage missing or not a positive int: refusing to fabricate")
        if not isinstance(row.is_auto_add_margin, bool):
            raise ValueError("isAutoAddMargin missing or not a bool")
        return SymbolConfigSnapshot(
            symbol=symbol,
            margin_type=margin_type,
            leverage=leverage,
            is_auto_add_margin=row.is_auto_add_margin,
            max_notional_value=_require_exchange_decimal(
                row.max_notional_value, "maxNotionalValue"
            ),
        )

    async def leverage_brackets_snapshot(self, *, symbol: str) -> SymbolLeverageBrackets:
        """Read the exchange leverage brackets of one symbol (GET /fapi/v1/leverageBracket, 22-01).

        USER_DATA, through the official SDK `rest_api.notional_and_leverage_brackets(symbol,
        recv_window)` and `_sdk_call` (policy, shared REST gate, never retried). The SDK answer is
        a oneOf wrapper (`actual_instance`: a list of entries, or one entry); both shapes are
        unwrapped and exactly one entry for the requested symbol is required. The floats the SDK
        models carry (`maintMarginRatio`, `cum`, `notionalCoef`) become Decimal through
        `Decimal(repr(value))`; None, bool and non-finite values are refused. Every `ValueError`
        names the field only, never the value; nothing about the response is logged.
        """
        response = await self._sdk_call(
            CallKind.QUERY, self._sdk.rest_api.notional_and_leverage_brackets, symbol=symbol
        )
        # The oneOf wrapper holds the answer in `actual_instance`; a plain list or entry passes.
        data: Any = response.data()
        raw: Any = getattr(data, "actual_instance", data)
        if raw is None:
            raise ValueError("leverage bracket response empty: refusing to fabricate")
        entries = raw if isinstance(raw, list) else [raw]
        if len(entries) != 1:
            raise ValueError("leverage bracket answer must hold exactly one entry for the symbol")
        entry = entries[0]
        if entry.symbol != symbol:
            raise ValueError("leverage bracket entry is for another symbol: refusing to use it")
        raw_brackets = entry.brackets
        if not isinstance(raw_brackets, list) or len(raw_brackets) == 0:
            raise ValueError("brackets missing or empty: refusing to fabricate")
        coef = entry.notional_coef
        return SymbolLeverageBrackets(
            symbol=symbol,
            notional_coef=None
            if coef is None
            else _exchange_number_to_decimal(coef, "notionalCoef"),
            brackets=tuple(_row_to_leverage_bracket(item) for item in raw_brackets),
        )

    async def change_margin_type(self, *, symbol: str, margin_type: str) -> None:
        """Change the margin type of one symbol (POST /fapi/v1/marginType, plan 22-06).

        TRADE, IP weight 1, through the official SDK `rest_api.change_margin_type(symbol,
        margin_type, recv_window)` and `_sdk_call`. This call MUTATES the account
        configuration, so the call kind is PLACEMENT: it is never retried and never slept on
        (`CallKind` has no separate configuration kind, 22-RESEARCH Open Question 5), it
        uses the shared REST gate and the signed-call policy recv window, and the original
        exception propagates unchanged. Requesting the type the symbol already has is an
        exchange ERROR (-4046), a change with open orders or a position is -4047 / -4048: the
        caller must not read a failure as "not ISOLATED" and decides only by a
        `symbol_config_snapshot` read. The answer body is not trusted and is not read; nothing
        about it is logged. `margin_type` must be exactly "ISOLATED" or "CROSSED" and is
        converted with the SDK enum; `symbol` must be a non-empty text. The adapter holds no
        target: what to send is the guard's decision (D-01).
        """
        if not isinstance(symbol, str) or symbol == "":
            raise ValueError("symbol must be non-empty text")
        if not isinstance(margin_type, str) or margin_type not in ("ISOLATED", "CROSSED"):
            raise ValueError("margin_type must be ISOLATED or CROSSED")
        from binance_sdk_derivatives_trading_usds_futures.rest_api.models.enums import (
            ChangeMarginTypeMarginTypeEnum,
        )

        await self._sdk_call(
            CallKind.PLACEMENT,
            self._sdk.rest_api.change_margin_type,
            symbol=symbol,
            margin_type=ChangeMarginTypeMarginTypeEnum(margin_type),
        )

    async def change_initial_leverage(self, *, symbol: str, leverage: int) -> None:
        """Change the initial leverage of one symbol (POST /fapi/v1/leverage, plan 22-06).

        TRADE, IP weight 1, through the official SDK `rest_api.change_initial_leverage(symbol,
        leverage, recv_window)` and `_sdk_call`. Like `change_margin_type` this MUTATES the
        account configuration: the call kind is PLACEMENT (never retried, never slept on), the
        shared REST gate and the policy recv window apply, and the original exception
        propagates unchanged. The answer body is not trusted and is not read; the caller
        decides by a `symbol_config_snapshot` read. The maximum leverage is symbol-specific (the
        `initialLeverage` of bracket 1 of the leverage-bracket read, not a constant: the
        2026-10-09 change-log correction); the adapter enforces NO cap, the guard compares with
        the D035 cap and the bracket (D-02). A leverage reduction in isolated mode with a
        position is refused by the exchange (-4161, 22-RESEARCH 2.2). `leverage` must be an
        int (not a bool) of at least 1; `symbol` a non-empty text.
        """
        if not isinstance(symbol, str) or symbol == "":
            raise ValueError("symbol must be non-empty text")
        if isinstance(leverage, bool) or not isinstance(leverage, int):
            raise TypeError("leverage must be an int")
        if leverage < 1:
            raise ValueError("leverage must be at least 1")
        await self._sdk_call(
            CallKind.PLACEMENT,
            self._sdk.rest_api.change_initial_leverage,
            symbol=symbol,
            leverage=leverage,
        )

    async def user_trades_in_window(
        self, *, symbol: str, start_utc: datetime, end_utc: datetime
    ) -> tuple[UserTradeRow, ...]:
        """Read every fill of `symbol` inside a UTC window (GET /fapi/v1/userTrades, plan 21-08).

        The REST trade list is the arbiter of the realized PnL and commission of a UTC day
        (D-09): the stream feeds fills of known orders only and drops frames sent during a
        gap. Through the official SDK `rest_api.account_trade_list` and `_sdk_call` (policy,
        shared REST gate, never retried; an SDK exception propagates unchanged). Page 1 sends
        `start_time` and `end_time`; every later page sends `from_id` = last trade id + 1 and
        no time bound (the endpoint refuses `fromId` with a time bound). The loop ends on an
        empty page or on a page holding only trades after `end_utc`; rows after `end_utc` are
        dropped. Trade ids must strictly increase, within a page and across pages, else
        `ValueError` (the order the exchange pages in is not documented in the SDK; this check
        fails closed either way and also bounds the loop). No `limit` is sent, no clock is
        read, nothing about the response is logged. A malformed row, a row of another symbol
        or a bad window raises `ValueError` naming the field only: the caller then treats the
        loss as unknown (D-04, D-20).
        """
        start_ms, end_ms = _window_ms(start_utc, end_utc)
        found: list[UserTradeRow] = []
        last_id: int | None = None
        while True:
            if last_id is None:
                response = await self._sdk_call(
                    CallKind.QUERY,
                    self._sdk.rest_api.account_trade_list,
                    symbol=symbol,
                    start_time=start_ms,
                    end_time=end_ms,
                )
            else:
                response = await self._sdk_call(
                    CallKind.QUERY,
                    self._sdk.rest_api.account_trade_list,
                    symbol=symbol,
                    from_id=last_id + 1,
                )
            page = response.data()
            if not isinstance(page, list):
                raise ValueError("trade list page is not a list: refusing to fabricate")
            if not page:
                break
            in_window = False
            for item in page:
                trade_id = _require_exchange_int(getattr(item, "id", None), "id")
                if last_id is not None and trade_id <= last_id:
                    raise ValueError("trade ids must strictly increase: refusing a partial read")
                last_id = trade_id
                row, row_ms = _row_to_user_trade(item, symbol, trade_id)
                if row_ms <= end_ms:
                    in_window = True
                    found.append(row)
            if not in_window:
                break
        return tuple(found)

    async def income_in_window(
        self, *, income_type: str, start_utc: datetime, end_utc: datetime
    ) -> tuple[IncomeRow, ...]:
        """Read every income row of one type inside a UTC window (GET /fapi/v1/income).

        Plan 21-08. Through the official SDK `rest_api.get_income_history` and `_sdk_call`
        (policy, shared REST gate, never retried). `income_type` must be a member of the SDK
        income enum, else `ValueError` before any call. Pages 1, 2, ... are read until an empty
        page; `tranId` is unique within one income type, so a repeated one raises (the page
        parameter is the documented way to page; a server that ignored it could otherwise loop).
        Funding is read as `income_type="FUNDING_FEE"`; that source is UNVERIFIED on Demo (0 rows
        in four recorded tries, demo-observed, not mainnet). The free-text `info` field is never
        read and nothing about the response is logged (D-21 secret-free logging; OPS-02 itself
        is an owner attestation this method does not claim). Rows are returned ordered by
        `(time_utc, tran_id)`.
        """
        try:
            income_enum = GetIncomeHistoryIncomeTypeEnum(income_type)
        except ValueError:
            raise ValueError("income_type is not a member of the SDK income enum") from None
        start_ms, end_ms = _window_ms(start_utc, end_utc)
        found: list[IncomeRow] = []
        seen: set[int] = set()
        page_number = 1
        while True:
            response = await self._sdk_call(
                CallKind.QUERY,
                self._sdk.rest_api.get_income_history,
                income_type=income_enum,
                start_time=start_ms,
                end_time=end_ms,
                page=page_number,
            )
            page = response.data()
            if not isinstance(page, list):
                raise ValueError("income page is not a list: refusing to fabricate")
            if not page:
                break
            for item in page:
                row = _row_to_income(item, income_type)
                if row.tran_id in seen:
                    raise ValueError("income tranId repeated across pages: refusing a bad read")
                seen.add(row.tran_id)
                found.append(row)
            page_number += 1
        return tuple(sorted(found, key=lambda row: (row.time_utc, row.tran_id)))


# --------------------------------------------------------------------------- #
# Internal helpers for reconciler snapshot projection.
# --------------------------------------------------------------------------- #


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
    # A missing amount must never read as a flat position: `snapshot_positions`
    # drops zero-amount rows, and the orphan sweeper's position-zero check
    # (T-8-30) would then be satisfied by a fabricated zero (fail closed).
    if item.position_amt is None:
        raise ValueError("position row missing positionAmt: refusing to fabricate a flat position")
    position_amt = Decimal(str(item.position_amt))
    if not position_amt.is_finite():
        raise ValueError("position row positionAmt is not finite")
    entry_price, entry_price_from_float = _entry_price_decimal(item.entry_price)
    return PositionSnapshot(
        symbol=item.symbol,
        position_side=item.position_side or "",
        position_amt=position_amt,
        entry_price=entry_price,
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
        entry_price_from_float=entry_price_from_float,
    )


def _entry_price_decimal(value: object) -> tuple[Decimal, bool]:
    """The position `entry_price` as a Decimal, and whether it came from a float (D-34).

    The installed SDK model types `entryPrice` as a string, so the exchange's own text reaches
    here and `Decimal(text)` is exact (84816.4 stays 84816.4). A float can only arrive through a
    row built without validation or from another SDK version: it is converted through its
    shortest text (never rounded or quantized) and flagged, because float noise such as
    84816.40000000001 cannot be repaired from the float alone. A missing value is zero, as before.
    """
    if value is None:
        return Decimal("0"), False
    if isinstance(value, float):
        converted = Decimal(repr(value))
        if not converted.is_finite():
            raise ValueError("position row entryPrice is not finite")
        return converted, True
    return Decimal(str(value)), False


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


def _new_order_to_market_close_result(raw: Any) -> MarketCloseResult:
    """Project a MARKET `new_order` response into a `MarketCloseResult` (plan 19-08).

    Flag-never-fabricate (D-09): a response without identity fields or update time raises.
    `executed_qty` and `avg_price` are read as optional (the SDK 17.4.0 response model does
    not declare `avg_price`): absent is None, never zero.
    """
    if not raw.symbol or not raw.client_order_id or raw.order_id is None:
        raise ValueError(f"new_order response missing identity fields: {raw!r}")
    return MarketCloseResult(
        symbol=raw.symbol,
        client_order_id=raw.client_order_id,
        exchange_order_id=str(raw.order_id),
        side=raw.side or "",
        position_side=raw.position_side or "",
        status=raw.status or "",
        executed_quantity=_optional_probe_decimal(
            getattr(raw, "executed_qty", None), "executed_qty"
        ),
        average_price=_optional_probe_decimal(getattr(raw, "avg_price", None), "avg_price"),
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
        executed_quantity=_optional_probe_decimal(
            getattr(raw, "executed_qty", None), "executed_qty"
        ),
        average_price=_optional_probe_decimal(getattr(raw, "avg_price", None), "avg_price"),
    )


def _optional_probe_decimal(value: Any, field_name: str) -> Decimal | None:
    """Strict Decimal of an optional query_order field: None stays None, junk raises.

    String-mediated (no float). An absent field is unknown (None), never zero; a present
    but non-decimal, non-finite or negative value raises, naming the field only.
    """
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"query_order {field_name} is not a decimal") from None
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"query_order {field_name} is not a finite non-negative decimal")
    return parsed


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


def _require_exchange_decimal(value: Any, field_name: str) -> Decimal:
    """Parse one exchange amount strictly: a finite Decimal from non-empty text (plan 21-03).

    A missing (None), empty, non-text, non-decimal or non-finite value raises `ValueError`
    naming the field only; the offending text is never put in the message. No float is built
    and a failure is never turned into a zero (D-04).
    """
    message = f"account field {field_name} missing or not a finite decimal: refusing to fabricate"
    if not isinstance(value, str) or value.strip() != value or value == "" or "_" in value:
        raise ValueError(message)
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise ValueError(message) from None
    if not parsed.is_finite():
        raise ValueError(message)
    return parsed


def _window_ms(start_utc: datetime, end_utc: datetime) -> tuple[int, int]:
    """Epoch milliseconds of a UTC window; anything but a valid window raises (plan 21-08).

    Both bounds must be timezone-aware UTC datetimes, `start_utc <= end_utc`, and the span at
    most seven days (the exchange window rule). Integer arithmetic only.
    """
    for bound in (start_utc, end_utc):
        if (
            not isinstance(bound, datetime)
            or bound.tzinfo is None
            or bound.utcoffset() != timedelta(0)
        ):
            raise ValueError("window bounds must be timezone-aware UTC datetimes")
    if start_utc > end_utc:
        raise ValueError("window start is after its end")
    if end_utc - start_utc > _MAX_WINDOW:
        raise ValueError("window is longer than seven days")
    one_ms = timedelta(milliseconds=1)
    return (start_utc - _EPOCH_UTC) // one_ms, (end_utc - _EPOCH_UTC) // one_ms


def _require_exchange_int(value: Any, field_name: str) -> int:
    """A real integer (not a bool) from the exchange; anything else raises, naming the field."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"exchange field {field_name} missing or not an integer")
    return value


def _exchange_number_to_decimal(value: Any, field_name: str) -> Decimal:
    """A non-negative finite exchange number (SDK float or int) as an exact Decimal (22-01).

    The SDK models carry the bracket ratios as `StrictFloat | StrictInt`. A float becomes
    `Decimal(repr(value))`, the shortest text that round-trips (`0.004` -> `Decimal("0.004")`),
    never `Decimal(value)`, which would expose the binary expansion (22-RESEARCH Pitfall 4).
    None, bool, text, non-finite and negative values raise `ValueError` naming the field only.
    """
    message = f"exchange field {field_name} missing or not a finite non-negative number"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(message)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(message)
    if value < 0:
        raise ValueError(message)
    return Decimal(repr(value)) if isinstance(value, float) else Decimal(value)


def _row_to_leverage_bracket(item: Any) -> LeverageBracketRow:
    """Project one SDK bracket into `LeverageBracketRow`; a bad field raises, naming it (22-01)."""
    initial_leverage = _require_exchange_int(item.initial_leverage, "initialLeverage")
    if initial_leverage < 1:
        raise ValueError("exchange field initialLeverage below 1")
    notional_floor = _require_exchange_int(item.notional_floor, "notionalFloor")
    notional_cap = _require_exchange_int(item.notional_cap, "notionalCap")
    if notional_floor < 0 or notional_cap < 0:
        raise ValueError("exchange field notionalFloor or notionalCap negative")
    return LeverageBracketRow(
        bracket=_require_exchange_int(item.bracket, "bracket"),
        initial_leverage=initial_leverage,
        notional_floor=Decimal(notional_floor),
        notional_cap=Decimal(notional_cap),
        maint_margin_ratio=_exchange_number_to_decimal(item.maint_margin_ratio, "maintMarginRatio"),
        cum=_exchange_number_to_decimal(item.cum, "cum"),
    )


def _require_exchange_text(value: Any, field_name: str) -> str:
    """Non-empty exchange text; anything else raises, naming the field only."""
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(f"exchange field {field_name} missing or empty")
    return value


def _utc_from_ms(ms: int) -> datetime:
    """Exact UTC datetime of an epoch millisecond count (no float)."""
    return _EPOCH_UTC + timedelta(milliseconds=ms)


def _row_to_user_trade(item: Any, symbol: str, trade_id: int) -> tuple[UserTradeRow, int]:
    """Project one `userTrades` row; the second value is its epoch milliseconds (plan 21-08)."""
    row_symbol = _require_exchange_text(getattr(item, "symbol", None), "symbol")
    if row_symbol != symbol:
        raise ValueError("trade row symbol differs from the requested symbol")
    time_ms = _require_exchange_int(getattr(item, "time", None), "time")
    row = UserTradeRow(
        symbol=row_symbol,
        order_id=_require_exchange_int(getattr(item, "order_id", None), "orderId"),
        trade_id=trade_id,
        realized_pnl=_require_exchange_decimal(getattr(item, "realized_pnl", None), "realizedPnl"),
        commission=_require_exchange_decimal(getattr(item, "commission", None), "commission"),
        commission_asset=_require_exchange_text(
            getattr(item, "commission_asset", None), "commissionAsset"
        ),
        margin_asset=_require_exchange_text(getattr(item, "margin_asset", None), "marginAsset"),
        time_utc=_utc_from_ms(time_ms),
    )
    return row, time_ms


def _row_to_income(item: Any, income_type: str) -> IncomeRow:
    """Project one income row; `info` is deliberately never touched (plan 21-08, D-21)."""
    row_type = _require_exchange_text(getattr(item, "income_type", None), "incomeType")
    if row_type != income_type:
        raise ValueError("income row incomeType differs from the requested type")
    raw_symbol = getattr(item, "symbol", None)
    if raw_symbol is not None and not isinstance(raw_symbol, str):
        raise ValueError("exchange field symbol is not text")
    raw_trade_id = getattr(item, "trade_id", None)
    if raw_trade_id is not None and not isinstance(raw_trade_id, str):
        raise ValueError("exchange field tradeId is not text")
    return IncomeRow(
        symbol=raw_symbol if raw_symbol else None,
        income_type=row_type,
        income=_require_exchange_decimal(getattr(item, "income", None), "income"),
        asset=_require_exchange_text(getattr(item, "asset", None), "asset"),
        tran_id=_require_exchange_int(getattr(item, "tran_id", None), "tranId"),
        trade_id=raw_trade_id if raw_trade_id else None,
        time_utc=_utc_from_ms(_require_exchange_int(getattr(item, "time", None), "time")),
    )


def _row_to_account_asset(item: Any) -> AccountAssetRow:
    """Project one `assets` row of `account_information_v3` into the frozen dataclass."""
    asset = item.asset
    if not isinstance(asset, str) or asset.strip() == "":
        raise ValueError("account field asset missing or empty: refusing to fabricate")
    return AccountAssetRow(
        asset=asset,
        wallet_balance=_require_exchange_decimal(item.wallet_balance, "walletBalance"),
        unrealized_profit=_require_exchange_decimal(item.unrealized_profit, "unrealizedProfit"),
        margin_balance=_require_exchange_decimal(item.margin_balance, "marginBalance"),
        available_balance=_require_exchange_decimal(item.available_balance, "availableBalance"),
    )


def _require_update_time_utc(value: Any) -> datetime:
    if value is None:
        raise ValueError("snapshot row missing update_time: refusing to fabricate epoch-0")
    return _ms_to_utc(int(value))
