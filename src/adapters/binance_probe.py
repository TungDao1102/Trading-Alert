"""The Demo-probe adapter: exchange answers as data, never as exceptions (plan 18-12).

Used only by `scripts/demo_probe.py` (plans 18-17 and 18-23). D-15 and D-16 ask the probe to
record "the exact (class, code, message)" of each case; `BinanceUsdmAdapter` maps not-found to
`found=False` and hides the code, and D055 and G2-029 need order shapes the production adapter
never sends. Every operation here therefore returns a frozen `ProbeObservation`: an exchange
error becomes an `ErrorObservation` with the SDK class, the int Binance code, the Retry-After
seconds, the taxonomy category (`error_facts_from_exception` plus `classify`) and the exchange
message passed through the shared redactor and capped at `ERROR_MESSAGE_MAX_CHARS`. The message
is evidence only: no branch of this module reads it. A non-SDK exception records its type
name only.

No environment selection: the adapter receives an SDK client built by `build_sdk_client`; the
probe script asserts the host before each call (plan 18-17). Nothing here builds a client,
reads the environment, reads a clock or opens a connection.

Rate limits (user record `decisions/18-DEC-O-18-01.md` and its amendment of 2026-10-16): the
adapter holds the one process-wide `RestRateLimitGate` of plan 18-10. A 418 or a 429 it meets
is recorded in the gate, so every other REST holder of the probe process is banned or paused
too, and it sets the adapter's own ban flag: every later operation raises `ProbeBanned`
without an SDK call, so a probe run cannot extend a ban. A ban or pause recorded by another
holder refuses every operation the same way. No operation is ever retried: a retry would
defeat the point of recording the first answer.

Every signed call passes `recv_window` from the required `SignedCallPolicy`. Prices and
quantities cross the SDK boundary as exact fixed-point strings (`_decimal_to_wire`); no money
value passes through float. The SDK is called duck-typed through `sdk_client.rest_api`; the
installed SDK is imported only for the request enums, as `binance_usdm.py` does.

SDK methods (installed `binance-sdk-derivatives-trading-usds-futures` 17.4.0, bound offline by
`tests/test_binance_probe_contract.py`): see `SDK_REST_METHODS`.

Quick task 261021-sj0 adds nine owner-run evidence-capture operations (`account_information`,
`account_balance_all`, `account_config`, `symbol_config`, `leverage_brackets`, `income_history`,
`query_algo_order_by_algo_id`, `new_gtd_limit_order`, `live_mark_price`). Each makes one SDK
call and is never retried. The five account reads use `_flat_summary`, which deliberately
extends T-18-34 (the named-field rule) to these read-only account answers: they carry no
credential field, and every value still goes through the shared redactor and the length cap.

Quick task 261022-sj1 adds two unsigned public reads through the gated reader: `server_time`
(the exchange clock, for the goodTillDate boundary case) and `order_book` (the top
`ORDER_BOOK_LIMIT` levels, for the partial-fill and cancel-race cases).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any

from binance_sdk_derivatives_trading_usds_futures.rest_api.models.enums import (
    NewAlgoOrderAlgoTypeEnum,
    NewAlgoOrderClosePositionEnum,
    NewAlgoOrderReduceOnlyEnum,
    NewAlgoOrderSideEnum,
    NewAlgoOrderTimeInForceEnum,
    NewAlgoOrderTypeEnum,
    NewAlgoOrderWorkingTypeEnum,
    NewOrderReduceOnlyEnum,
    NewOrderSideEnum,
    NewOrderTimeInForceEnum,
    NewOrderTypeEnum,
)
from src.adapters.binance_errors import error_facts_from_exception
from src.adapters.binance_limits import SignedCallPolicy
from src.adapters.binance_public import (
    BinancePublicMarketData,
    MarkKline,
    OrderBookReading,
    SymbolFilters,
)
from src.adapters.binance_ratelimit_gate import (
    IP_BAN_418,
    RATE_LIMIT_PAUSE_429,
    RestGateRefusal,
    RestRateLimitGate,
)
from src.adapters.binance_usdm import (
    OpenAlgoOrderSnapshot,
    OpenOrderSnapshot,
    PositionSnapshot,
    _decimal_to_wire,
    _row_to_open_algo_order_snapshot,
    _row_to_open_order_snapshot,
    _row_to_position_snapshot,
)
from src.domain.exchange_errors import (
    CallKind,
    ErrorFacts,
    ExchangeErrorCategory,
    HttpClass,
    classify,
)
from src.ops.redaction import scrub

# The cap on the recorded exchange message (plan 18-12): evidence text, never a decision input.
ERROR_MESSAGE_MAX_CHARS: int = 200

# Every installed SDK REST method this adapter calls; each is a signed (USER_DATA or TRADE)
# endpoint that takes `recv_window`.
SDK_REST_METHODS: frozenset[str] = frozenset(
    {
        "query_order",
        "query_algo_order",
        "new_order",
        "new_algo_order",
        "cancel_order",
        "cancel_algo_order",
        "cancel_all_open_orders",
        "cancel_all_algo_open_orders",
        "current_all_open_orders",
        "current_all_algo_open_orders",
        "position_information_v3",
        "account_trade_list",
        "futures_account_balance_v3",
        # quick task 261021-sj0
        "account_information_v3",
        "futures_account_configuration",
        "symbol_configuration",
        "notional_and_leverage_brackets",
        "get_income_history",
    }
)

# `order_book` reads this many levels per side (a depth limit the exchange accepts).
ORDER_BOOK_LIMIT: int = 20
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# `mark_price` reads the latest mark-price kline of this interval (one row: the latest).
MARK_PRICE_INTERVAL: str = "1m"
_LATEST_ROW_ONLY: int = 1

# The order types `new_conditional_order` accepts: the CONDITIONAL algo types the probe cases
# use (D055, G2-029). TRAILING_STOP_MARKET is left out because it needs a callback rate this
# adapter does not send; LIMIT and MARKET are normal-order types.
CONDITIONAL_ORDER_TYPES: frozenset[str] = frozenset(
    {"STOP_MARKET", "TAKE_PROFIT_MARKET", "STOP", "TAKE_PROFIT"}
)

_RATE_LIMIT_REASONS: Mapping[ExchangeErrorCategory, str] = MappingProxyType(
    {
        ExchangeErrorCategory.IP_BANNED: IP_BAN_418,
        ExchangeErrorCategory.RATE_LIMITED: RATE_LIMIT_PAUSE_429,
    }
)

# The response fields recorded per answer, by name (threat T-18-34: nothing else is copied).
_ORDER_FIELDS: tuple[str, ...] = (
    "order_id",
    "client_order_id",
    "symbol",
    "status",
    "side",
    "position_side",
    "type",
    "orig_type",
    "time_in_force",
    "orig_qty",
    "executed_qty",
    "avg_price",
    "price",
    "stop_price",
    "working_type",
    "reduce_only",
    "close_position",
    "good_till_date",
)
_ALGO_ORDER_FIELDS: tuple[str, ...] = (
    "algo_id",
    "client_algo_id",
    "symbol",
    "algo_status",
    "algo_type",
    "order_type",
    "side",
    "position_side",
    "time_in_force",
    "quantity",
    "price",
    "trigger_price",
    "working_type",
    "reduce_only",
    "close_position",
    "actual_order_id",
)
_CANCEL_ALGO_FIELDS: tuple[str, ...] = ("algo_id", "client_algo_id", "code", "msg")
_CANCEL_ALL_FIELDS: tuple[str, ...] = ("code", "msg")
# Per-row fields of the three snapshots, named after the production dataclass fields.
_OPEN_ORDER_ROW_FIELDS: tuple[str, ...] = (
    "symbol",
    "client_order_id",
    "exchange_order_id",
    "status",
    "side",
    "position_side",
    "order_type",
    "time_in_force",
    "quantity",
    "price",
    "stop_price",
    "working_type",
    "reduce_only",
    "close_position",
)
_OPEN_ALGO_ROW_FIELDS: tuple[str, ...] = (
    "symbol",
    "client_algo_id",
    "algo_id",
    "algo_status",
    "algo_type",
    "order_type",
    "side",
    "position_side",
    "time_in_force",
    "quantity",
    "price",
    "trigger_price",
    "working_type",
    "reduce_only",
    "close_position",
)
_POSITION_ROW_FIELDS: tuple[str, ...] = (
    "symbol",
    "position_side",
    "position_amt",
    "entry_price",
    "break_even_price",
    "mark_price",
    "unrealized_profit",
    "liquidation_price",
    "notional",
    "margin_asset",
)
# (summary name, SDK field) of one user trade: `trade_id` is the SDK `id`, the key space of the
# stream's `t` (to be confirmed by the probe, research Open Question 8).
_TRADE_ROW_FIELDS: tuple[tuple[str, str], ...] = (
    ("trade_id", "id"),
    ("order_id", "order_id"),
    ("price", "price"),
    ("qty", "qty"),
    ("commission", "commission"),
    ("commission_asset", "commission_asset"),
    ("maker", "maker"),
    ("time_ms", "time"),
    # quick task 261021-sj0 (additive): realized PnL and the fill's identity
    ("realized_pnl", "realized_pnl"),
    ("side", "side"),
    ("position_side", "position_side"),
    ("buyer", "buyer"),
    ("quote_qty", "quote_qty"),
    ("margin_asset", "margin_asset"),
)
# (summary name, SDK field) of one income row (quick task 261021-sj0); `info` is free text.
_INCOME_ROW_FIELDS: tuple[tuple[str, str], ...] = (
    ("symbol", "symbol"),
    ("income_type", "income_type"),
    ("income", "income"),
    ("asset", "asset"),
    ("info", "info"),
    ("time_ms", "time"),
    ("tran_id", "tran_id"),
    ("trade_id", "trade_id"),
)
_BALANCE_ROW_FIELDS: tuple[str, ...] = ("asset", "balance", "available_balance")
_ZERO = Decimal(0)
# Free-text response fields: passed through the shared redactor and capped like an error
# message (threat T-18-34).
_FREE_TEXT_FIELDS: frozenset[str] = frozenset({"msg"})

# `_flat_summary` stops after this many data keys and adds `truncated` = `true` (quick task
# 261021-sj0). The account answer lists one row per asset and per position.
FLAT_SUMMARY_MAX_KEYS: int = 2000
_FLAT_MAX_DEPTH: int = 8


def _is_strict_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# --------------------------------------------------------------------------- #
# Argument validation (before any SDK call).
# --------------------------------------------------------------------------- #


def _money(name: str, value: object) -> Any:
    """A positive, finite `Decimal` as its exact fixed-point wire text; anything else refused.

    A float, an int, a bool or text raises TypeError; zero, a negative or a non-finite value
    raises ValueError. The wire text comes from the shared `_decimal_to_wire`.
    """
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return _decimal_to_wire(value)


def _member[E: Enum](enum_cls: type[E], name: str, value: object) -> E:
    """The installed SDK enum member whose value is exactly `value`; unknown text refused."""
    if not isinstance(value, str):
        raise TypeError(f"{name} must be text, got {type(value).__name__}")
    try:
        return enum_cls(value)
    except ValueError:
        raise ValueError(f"unknown {name}: {value!r}") from None


def _flag(name: str, value: object) -> bool | None:
    if value is not None and not isinstance(value, bool):
        raise TypeError(f"{name} must be a bool or None, got {type(value).__name__}")
    return value


# --------------------------------------------------------------------------- #
# Value types.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ErrorObservation:
    """One exchange error as data: the class, the int code, the category, the scrubbed text.

    `http_class` is an `HttpClass` value and `category` an `ExchangeErrorCategory` value,
    stored as plain text for the evidence file. `message` is at most
    `ERROR_MESSAGE_MAX_CHARS` characters and is never an input to a decision.
    """

    http_class: str
    code: int | None
    retry_after_seconds: int | None
    category: str
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.http_class, str):
            raise TypeError("http_class must be text")
        if not isinstance(self.category, str):
            raise TypeError("category must be text")
        object.__setattr__(self, "http_class", HttpClass(self.http_class).value)
        object.__setattr__(self, "category", ExchangeErrorCategory(self.category).value)
        if self.code is not None and not _is_strict_int(self.code):
            raise TypeError("code must be an int (not a bool) or None")
        if self.retry_after_seconds is not None:
            if not _is_strict_int(self.retry_after_seconds):
                raise TypeError("retry_after_seconds must be an int (not a bool) or None")
            if self.retry_after_seconds < 0:
                raise ValueError("retry_after_seconds must not be negative")
        if not isinstance(self.message, str):
            raise TypeError("message must be text")
        if len(self.message) > ERROR_MESSAGE_MAX_CHARS:
            raise ValueError("message exceeds ERROR_MESSAGE_MAX_CHARS")


@dataclass(frozen=True, slots=True)
class ProbeObservation:
    """The result of one probe operation: `ok` with a text summary, or an `ErrorObservation`.

    `summary` maps text keys to text values only (a read-only copy of the mapping given);
    `ok` is True exactly when `error` is None.
    """

    operation: str
    ok: bool
    summary: Mapping[str, str]
    error: ErrorObservation | None

    def __post_init__(self) -> None:
        if not isinstance(self.operation, str) or not self.operation:
            raise ValueError("operation must be non-empty text")
        if not isinstance(self.ok, bool):
            raise TypeError("ok must be a bool")
        if not isinstance(self.summary, Mapping):
            raise TypeError("summary must be a mapping")
        copied: dict[str, str] = {}
        for key, value in self.summary.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise TypeError("summary keys and values must be text")
            copied[key] = value
        object.__setattr__(self, "summary", MappingProxyType(copied))
        if self.error is not None and not isinstance(self.error, ErrorObservation):
            raise TypeError("error must be an ErrorObservation or None")
        if self.ok != (self.error is None):
            raise ValueError("ok must be True exactly when error is None")


class ProbeBanned(Exception):  # noqa: N818 - a refusal, named by plan 18-12
    """Refused before sending: a 418 or 429 was met, or the shared gate is restricted.

    `reason` is `IP_BAN_418` or `RATE_LIMIT_PAUSE_429`; `retry_after_seconds` is the gate's
    remaining whole seconds when the gate is restricted, else None. No URL, key or SDK text.
    """

    def __init__(self, reason: str, retry_after_seconds: int | None) -> None:
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"probe call refused before sending: {reason}; "
            f"retry_after_seconds={retry_after_seconds}"
        )


# --------------------------------------------------------------------------- #
# Summaries.
# --------------------------------------------------------------------------- #


def _text(value: object) -> str:
    """The evidence text of one field: `str()`, booleans as `true` / `false`, a `Decimal` in
    exact fixed-point form (`_decimal_to_wire`), a datetime in ISO 8601."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return str(_decimal_to_wire(value))
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _fields_summary(raw: Any, names: Sequence[str]) -> dict[str, str]:
    """The named response fields that are present, as text."""
    if raw is None:
        return {}
    out: dict[str, str] = {}
    for name in names:
        value = getattr(raw, name, None)
        if value is None:
            continue
        text = _text(value)
        if name in _FREE_TEXT_FIELDS:
            text = scrub(text)[:ERROR_MESSAGE_MAX_CHARS]
        out[name] = text
    return out


def _order_summary(raw: Any) -> dict[str, str]:
    return _fields_summary(raw, _ORDER_FIELDS)


def _algo_order_summary(raw: Any) -> dict[str, str]:
    return _fields_summary(raw, _ALGO_ORDER_FIELDS)


def _cancel_algo_summary(raw: Any) -> dict[str, str]:
    return _fields_summary(raw, _CANCEL_ALGO_FIELDS)


def _cancel_all_summary(raw: Any) -> dict[str, str]:
    return _fields_summary(raw, _CANCEL_ALL_FIELDS)


def _rows(raw: Any) -> list[Any]:
    """A list-shaped SDK answer as a list (a single object becomes one row, None none)."""
    if raw is None:
        return []
    return list(raw) if isinstance(raw, list) else [raw]


def _same_names(names: Sequence[str]) -> tuple[tuple[str, str], ...]:
    return tuple((name, name) for name in names)


def _rows_summary(rows: Sequence[object], fields: Sequence[tuple[str, str]]) -> dict[str, str]:
    """`count` plus `row_<index>_<name>` text for every present field of every row."""
    out: dict[str, str] = {"count": str(len(rows))}
    for index, row in enumerate(rows):
        for name, attribute in fields:
            value = getattr(row, attribute, None)
            if value is not None:
                out[f"row_{index}_{name}"] = _text(value)
    return out


def _open_orders_summary(raw: Any) -> dict[str, str]:
    """Rows through the production converter (`_row_to_open_order_snapshot`)."""
    snapshots: list[OpenOrderSnapshot] = []
    for row in _rows(raw):
        snapshot = _row_to_open_order_snapshot(row)
        if snapshot is not None:
            snapshots.append(snapshot)
    return _rows_summary(snapshots, _same_names(_OPEN_ORDER_ROW_FIELDS))


def _open_algo_orders_summary(raw: Any) -> dict[str, str]:
    """Rows through the production converter (`_row_to_open_algo_order_snapshot`)."""
    snapshots: list[OpenAlgoOrderSnapshot] = []
    for row in _rows(raw):
        snapshot = _row_to_open_algo_order_snapshot(row)
        if snapshot is not None:
            snapshots.append(snapshot)
    return _rows_summary(snapshots, _same_names(_OPEN_ALGO_ROW_FIELDS))


def _positions_summary(raw: Any) -> dict[str, str]:
    """Rows through `_row_to_position_snapshot`; zero-amount rows dropped as in production."""
    snapshots: list[PositionSnapshot] = []
    for row in _rows(raw):
        snapshot = _row_to_position_snapshot(row)
        if snapshot is not None and snapshot.position_amt != _ZERO:
            snapshots.append(snapshot)
    return _rows_summary(snapshots, _same_names(_POSITION_ROW_FIELDS))


def _trades_summary(raw: Any) -> dict[str, str]:
    return _rows_summary(_rows(raw), _TRADE_ROW_FIELDS)


def _balance_summary(raw: Any) -> dict[str, str]:
    """Assets with a non-zero balance only (the balance text read exactly as a Decimal)."""
    kept = [
        row
        for row in _rows(raw)
        if getattr(row, "balance", None) is not None and Decimal(str(row.balance)) != _ZERO
    ]
    return _rows_summary(kept, _same_names(_BALANCE_ROW_FIELDS))


def _income_summary(raw: Any) -> dict[str, str]:
    """Income rows as text; the free-text `info` goes through the redactor and the cap."""
    out = _rows_summary(_rows(raw), _INCOME_ROW_FIELDS)
    for key in [name for name in out if name.endswith("_info")]:
        out[key] = scrub(out[key])[:ERROR_MESSAGE_MAX_CHARS]
    return out


def _flat_summary(raw: Any) -> dict[str, str]:
    """Every present field of an account answer as `<path>` -> text (quick task 261021-sj0).

    The path joins the wire (alias) names with dots and list positions as numbers, for example
    ``assets.0.walletBalance``. SDK models are read through ``to_dict()`` (wire names, extra
    fields kept), a oneOf wrapper through its ``actual_instance``; None is dropped. Every
    value is the evidence text of the field, passed through the shared redactor and capped at
    `ERROR_MESSAGE_MAX_CHARS`. After `FLAT_SUMMARY_MAX_KEYS` data keys it stops and adds
    ``truncated`` = ``true``.

    This deliberately extends T-18-34 (named response fields only) to the five read-only
    account answers of the capture task: they carry no credential field, and the owner wants
    every field the exchange returns (for example the equity field names).
    """
    out: dict[str, str] = {}
    full = False

    def clip(text: str) -> str:
        return scrub(text)[:ERROR_MESSAGE_MAX_CHARS]

    def walk(value: object, path: str, depth: int) -> None:
        nonlocal full
        if full or value is None:
            return
        inner = getattr(value, "actual_instance", None)
        if inner is not None:
            walk(inner, path, depth)
            return
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict) and not isinstance(value, Mapping):
            walk(to_dict(), path, depth)
            return
        children: list[tuple[str, object]] | None = None
        if depth < _FLAT_MAX_DEPTH:
            if isinstance(value, Mapping):
                children = [(clip(str(key)), item) for key, item in value.items()]
            elif isinstance(value, list | tuple):
                children = [(str(index), item) for index, item in enumerate(value)]
        if children is not None:
            for name, item in children:
                walk(item, f"{path}.{name}" if path else name, depth + 1)
            return
        if len(out) >= FLAT_SUMMARY_MAX_KEYS:
            full = True
            return
        out[path or "value"] = clip(_text(value))

    walk(raw, "", 0)
    if full:
        out["truncated"] = "true"
    return out


def _mark_price_summary(symbol: str, klines: Sequence[MarkKline]) -> dict[str, str]:
    out = {"symbol": symbol, "interval": MARK_PRICE_INTERVAL, "count": str(len(klines))}
    if klines:
        latest = klines[-1]
        out["close"] = _text(latest.close)
        out["open_time_utc"] = _text(latest.open_time_utc)
        out["close_time_utc"] = _text(latest.close_time_utc)
    return out


def _server_time_summary(moment: datetime) -> dict[str, str]:
    """The exchange clock as whole epoch milliseconds (integer arithmetic) and UTC text."""
    millis = (moment - _EPOCH + timedelta(microseconds=500)) // timedelta(milliseconds=1)
    return {"server_time_ms": str(millis), "server_time_utc": _text(moment)}


def _order_book_summary(book: OrderBookReading) -> dict[str, str]:
    out = {
        "symbol": book.symbol,
        "last_update_id": str(book.last_update_id),
        "bid_count": str(len(book.bids)),
        "ask_count": str(len(book.asks)),
    }
    for side, levels in (("bid", book.bids), ("ask", book.asks)):
        for index, (price, quantity) in enumerate(levels):
            out[f"{side}_{index}_price"] = _text(price)
            out[f"{side}_{index}_quantity"] = _text(quantity)
    return out


# (summary name, SymbolFilters field) of `symbol_filters`.
_FILTER_FIELDS: tuple[tuple[str, str], ...] = (
    ("status", "status"),
    ("tick_size", "price_tick_size"),
    ("step_size", "quantity_step_size"),
    ("min_quantity", "min_quantity"),
    ("max_quantity", "max_quantity"),
    ("min_notional", "min_notional"),
    ("market_lot_min_quantity", "market_lot_min_quantity"),
    ("market_lot_max_quantity", "market_lot_max_quantity"),
    ("market_lot_step_size", "market_lot_step_size"),
    ("percent_price_multiplier_up", "percent_price_multiplier_up"),
    ("percent_price_multiplier_down", "percent_price_multiplier_down"),
    ("percent_price_multiplier_decimals", "percent_price_multiplier_decimals"),
)


def _symbol_filters_summary(symbol: str, filters: Sequence[SymbolFilters]) -> dict[str, str]:
    match = next((item for item in filters if item.symbol == symbol), None)
    if match is None:
        return {"symbol": symbol, "found": "false"}
    out = {"symbol": symbol, "found": "true"}
    for name, attribute in _FILTER_FIELDS:
        value = getattr(match, attribute)
        if value is not None:
            out[name] = _text(value)
    return out


def _error_message(exc: Exception, facts: ErrorFacts) -> str:
    """The scrubbed, capped exchange message; the type name for a non-SDK exception."""
    if facts.http_class is HttpClass.NON_SDK:
        return type(exc).__name__
    text = getattr(exc, "error_message", None)
    if not isinstance(text, str):
        return type(exc).__name__
    return scrub(text)[:ERROR_MESSAGE_MAX_CHARS]


# --------------------------------------------------------------------------- #
# The adapter.
# --------------------------------------------------------------------------- #


class BinanceProbeAdapter:
    """The probe's exchange operations behind project-owned, data-returning methods.

    `sdk_client` is an SDK client built by `build_sdk_client` (or an SDK-shaped fake);
    `policy` supplies `recv_window` for every signed call; `rest_gate` is the process-wide
    gate, whose policy must equal `policy.rate_limit`; `public` is the public market-data
    reader of `mark_price` and `symbol_filters`, which must hold the same gate so these two
    reads are refused during a ban or a pause too (the probe composition of plan 18-17).
    """

    def __init__(
        self,
        sdk_client: Any,
        *,
        policy: SignedCallPolicy,
        rest_gate: RestRateLimitGate,
        public: BinancePublicMarketData,
    ) -> None:
        if not isinstance(policy, SignedCallPolicy):
            raise TypeError("policy must be a SignedCallPolicy")
        if not isinstance(rest_gate, RestRateLimitGate):
            raise TypeError("rest_gate must be the process-wide RestRateLimitGate")
        if not isinstance(public, BinancePublicMarketData):
            raise TypeError("public must be a BinancePublicMarketData")
        if rest_gate.policy != policy.rate_limit:
            raise ValueError("rest_gate.policy must equal policy.rate_limit")
        # The reader keeps its gate private; reading it here is the only way to prove the
        # composition handed it the same instance (an ungated reader could extend a ban).
        if getattr(public, "_rest_gate", None) is not rest_gate:
            raise ValueError("public must hold the same RestRateLimitGate instance")
        self._sdk = sdk_client
        self._policy = policy
        self._rest_gate = rest_gate
        self._public = public
        self._banned_reason: str | None = None

    @property
    def banned(self) -> bool:
        """True once this adapter met a 418 or a 429 (it then refuses every operation)."""
        return self._banned_reason is not None

    def _refuse_if_banned(self) -> None:
        restriction = self._rest_gate.restriction()
        if restriction is not None:
            raise ProbeBanned(restriction.reason, restriction.remaining_seconds)
        if self._banned_reason is not None:
            raise ProbeBanned(self._banned_reason, None)

    def _note_rate_limit(self, category: ExchangeErrorCategory) -> None:
        reason = _RATE_LIMIT_REASONS.get(category)
        if reason is None:
            return
        if self._banned_reason != IP_BAN_418:
            self._banned_reason = reason

    def _failure(
        self, operation: str, exc: Exception, call_kind: CallKind, *, record_in_gate: bool
    ) -> ProbeObservation:
        facts = error_facts_from_exception(exc)
        category = classify(facts, call_kind)
        self._note_rate_limit(category)
        if record_in_gate and category in _RATE_LIMIT_REASONS:
            self._rest_gate.record(category, facts.retry_after_seconds)
        return ProbeObservation(
            operation=operation,
            ok=False,
            summary={},
            error=ErrorObservation(
                http_class=facts.http_class.value,
                code=facts.code,
                retry_after_seconds=facts.retry_after_seconds,
                category=category.value,
                message=_error_message(exc, facts),
            ),
        )

    async def _call(
        self,
        operation: str,
        *,
        sdk_method_name: str,
        call_kind: CallKind,
        kwargs: Mapping[str, Any],
        summarize: Callable[[Any], Mapping[str, str]],
    ) -> ProbeObservation:
        """One signed SDK call in a worker thread; its answer or its error as an observation.

        Refused with `ProbeBanned` (no SDK call) while the adapter's ban flag is set or the
        shared gate is restricted. Only `Exception` becomes data; a `BaseException` propagates.
        """
        if sdk_method_name not in SDK_REST_METHODS:
            raise ValueError(f"undeclared SDK method: {sdk_method_name}")
        self._refuse_if_banned()
        method = getattr(self._sdk.rest_api, sdk_method_name)
        request = {**kwargs, "recv_window": self._policy.recv_window_ms}
        try:
            response = await asyncio.to_thread(method, **request)
        except Exception as exc:  # noqa: BLE001 - every exchange error is recorded as data
            return self._failure(operation, exc, call_kind, record_in_gate=True)
        return ProbeObservation(
            operation=operation, ok=True, summary=summarize(response.data()), error=None
        )

    async def _public_read[T](
        self,
        operation: str,
        read: Callable[[], Awaitable[T]],
        summarize: Callable[[T], Mapping[str, str]],
    ) -> ProbeObservation:
        """One public read through the gated reader; its error as an observation.

        The reader holds the same gate: it records a 418 or 429 itself (so it is not recorded
        twice here), and its refusal (a restriction set by another holder in between) becomes
        `ProbeBanned`.
        """
        self._refuse_if_banned()
        try:
            value = await read()
        except RestGateRefusal as refusal:
            raise ProbeBanned(refusal.reason, refusal.retry_after_seconds) from None
        except Exception as exc:  # noqa: BLE001 - every exchange error is recorded as data
            return self._failure(operation, exc, CallKind.QUERY, record_in_gate=False)
        return ProbeObservation(operation=operation, ok=True, summary=summarize(value), error=None)

    # ----- raw queries ----------------------------------------------------- #

    async def query_order(self, *, symbol: str, client_order_id: str) -> ProbeObservation:
        """GET /fapi/v1/order by client id; a missing order is recorded with its exact code."""
        return await self._call(
            "query_order",
            sdk_method_name="query_order",
            call_kind=CallKind.QUERY,
            kwargs={"symbol": symbol, "orig_client_order_id": client_order_id},
            summarize=_order_summary,
        )

    async def query_algo_order(self, *, client_algo_id: str) -> ProbeObservation:
        """GET /fapi/v1/algoOrder by client algo id (-2013 on Demo for a missing one)."""
        return await self._call(
            "query_algo_order",
            sdk_method_name="query_algo_order",
            call_kind=CallKind.QUERY,
            kwargs={"client_algo_id": client_algo_id},
            summarize=_algo_order_summary,
        )

    # ----- placements (each sent once, never retried) ---------------------- #

    async def new_limit_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        client_order_id: str,
        position_side: str,
        time_in_force: str,
        reduce_only: bool | None,
    ) -> ProbeObservation:
        """POST /fapi/v1/order LIMIT. `reduce_only` None omits the parameter (hedge mode)."""
        kwargs: dict[str, Any] = {
            "symbol": symbol,
            "side": _member(NewOrderSideEnum, "side", side),
            "type": NewOrderTypeEnum.LIMIT,
            "position_side": position_side,
            "time_in_force": _member(NewOrderTimeInForceEnum, "time_in_force", time_in_force),
            "quantity": _money("quantity", quantity),
            "price": _money("price", price),
            "new_client_order_id": client_order_id,
        }
        flag = _flag("reduce_only", reduce_only)
        if flag is not None:
            kwargs["reduce_only"] = (
                NewOrderReduceOnlyEnum.TRUE if flag else NewOrderReduceOnlyEnum.FALSE
            )
        return await self._call(
            "new_limit_order",
            sdk_method_name="new_order",
            call_kind=CallKind.PLACEMENT,
            kwargs=kwargs,
            summarize=_order_summary,
        )

    async def new_market_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: Decimal,
        client_order_id: str,
        position_side: str,
        reduce_only: bool | None,
    ) -> ProbeObservation:
        """POST /fapi/v1/order MARKET (also the reduce-only close of a residual position)."""
        kwargs: dict[str, Any] = {
            "symbol": symbol,
            "side": _member(NewOrderSideEnum, "side", side),
            "type": NewOrderTypeEnum.MARKET,
            "position_side": position_side,
            "quantity": _money("quantity", quantity),
            "new_client_order_id": client_order_id,
        }
        flag = _flag("reduce_only", reduce_only)
        if flag is not None:
            kwargs["reduce_only"] = (
                NewOrderReduceOnlyEnum.TRUE if flag else NewOrderReduceOnlyEnum.FALSE
            )
        return await self._call(
            "new_market_order",
            sdk_method_name="new_order",
            call_kind=CallKind.PLACEMENT,
            kwargs=kwargs,
            summarize=_order_summary,
        )

    async def new_conditional_order(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        client_algo_id: str,
        position_side: str,
        trigger_price: Decimal,
        working_type: str,
        quantity: Decimal | None = None,
        reduce_only: bool | None = None,
        close_position: bool | None = None,
        price: Decimal | None = None,
        time_in_force: str | None = None,
    ) -> ProbeObservation:
        """POST /fapi/v1/algoOrder with algoType CONDITIONAL.

        Only the optional parameters that are not None are sent. A combination Binance
        documents as invalid (close_position with quantity or reduce_only) is passed through
        unchanged so the probe records the exchange's answer. `working_type` has no default
        (the probe passes MARK_PRICE); hedge mode is not detected here (the caller passes
        `position_side`).
        """
        if not isinstance(order_type, str):
            raise TypeError("order_type must be text")
        if order_type not in CONDITIONAL_ORDER_TYPES:
            raise ValueError(f"unknown conditional order_type: {order_type!r}")
        kwargs: dict[str, Any] = {
            "algo_type": NewAlgoOrderAlgoTypeEnum.CONDITIONAL,
            "symbol": symbol,
            "side": _member(NewAlgoOrderSideEnum, "side", side),
            "type": _member(NewAlgoOrderTypeEnum, "order_type", order_type),
            "position_side": position_side,
            "trigger_price": _money("trigger_price", trigger_price),
            "working_type": _member(NewAlgoOrderWorkingTypeEnum, "working_type", working_type),
            "client_algo_id": client_algo_id,
        }
        if quantity is not None:
            kwargs["quantity"] = _money("quantity", quantity)
        if price is not None:
            kwargs["price"] = _money("price", price)
        if time_in_force is not None:
            kwargs["time_in_force"] = _member(
                NewAlgoOrderTimeInForceEnum, "time_in_force", time_in_force
            )
        reduce_flag = _flag("reduce_only", reduce_only)
        if reduce_flag is not None:
            kwargs["reduce_only"] = (
                NewAlgoOrderReduceOnlyEnum.TRUE if reduce_flag else NewAlgoOrderReduceOnlyEnum.FALSE
            )
        close_flag = _flag("close_position", close_position)
        if close_flag is not None:
            kwargs["close_position"] = (
                NewAlgoOrderClosePositionEnum.TRUE
                if close_flag
                else NewAlgoOrderClosePositionEnum.FALSE
            )
        return await self._call(
            "new_conditional_order",
            sdk_method_name="new_algo_order",
            call_kind=CallKind.PLACEMENT,
            kwargs=kwargs,
            summarize=_algo_order_summary,
        )

    # ----- cancels (each sent once, never retried) ------------------------- #

    async def cancel_order(self, *, symbol: str, client_order_id: str) -> ProbeObservation:
        """DELETE /fapi/v1/order by client id; not-found is recorded as ORDER_ABSENT."""
        return await self._call(
            "cancel_order",
            sdk_method_name="cancel_order",
            call_kind=CallKind.CANCEL,
            kwargs={"symbol": symbol, "orig_client_order_id": client_order_id},
            summarize=_order_summary,
        )

    async def cancel_algo_order(self, *, client_algo_id: str) -> ProbeObservation:
        """DELETE /fapi/v1/algoOrder by client algo id; not-found is recorded as ORDER_ABSENT."""
        return await self._call(
            "cancel_algo_order",
            sdk_method_name="cancel_algo_order",
            call_kind=CallKind.CANCEL,
            kwargs={"client_algo_id": client_algo_id},
            summarize=_cancel_algo_summary,
        )

    async def cancel_all_open_orders(self, *, symbol: str) -> ProbeObservation:
        """DELETE /fapi/v1/allOpenOrders for one symbol (cleanup toolbox)."""
        return await self._call(
            "cancel_all_open_orders",
            sdk_method_name="cancel_all_open_orders",
            call_kind=CallKind.CANCEL,
            kwargs={"symbol": symbol},
            summarize=_cancel_all_summary,
        )

    async def cancel_all_algo_open_orders(self, *, symbol: str) -> ProbeObservation:
        """DELETE /fapi/v1/algoOpenOrders for one symbol (cleanup toolbox)."""
        return await self._call(
            "cancel_all_algo_open_orders",
            sdk_method_name="cancel_all_algo_open_orders",
            call_kind=CallKind.CANCEL,
            kwargs={"symbol": symbol},
            summarize=_cancel_all_summary,
        )

    # ----- state capture (before and after every case) --------------------- #

    async def open_orders(self, *, symbol: str) -> ProbeObservation:
        """GET /fapi/v1/openOrders: `count` and `row_<i>_<field>` text per open order."""
        return await self._call(
            "open_orders",
            sdk_method_name="current_all_open_orders",
            call_kind=CallKind.QUERY,
            kwargs={"symbol": symbol},
            summarize=_open_orders_summary,
        )

    async def open_algo_orders(self, *, symbol: str) -> ProbeObservation:
        """GET /fapi/v1/openAlgoOrders: `count` and `row_<i>_<field>` text per algo order."""
        return await self._call(
            "open_algo_orders",
            sdk_method_name="current_all_algo_open_orders",
            call_kind=CallKind.QUERY,
            kwargs={"symbol": symbol},
            summarize=_open_algo_orders_summary,
        )

    async def positions(self, *, symbol: str) -> ProbeObservation:
        """GET /fapi/v3/positionRisk: non-zero positions only, as text rows."""
        return await self._call(
            "positions",
            sdk_method_name="position_information_v3",
            call_kind=CallKind.QUERY,
            kwargs={"symbol": symbol},
            summarize=_positions_summary,
        )

    async def user_trades(self, *, symbol: str, order_id: int | None = None) -> ProbeObservation:
        """GET /fapi/v1/userTrades: one text row per fill, `trade_id` being the SDK `id`.

        `trade_id` is the key space of the user-data stream's `t` field; the probe confirms
        that (research Open Question 8, P13: two fill key spaces).
        """
        if order_id is not None and not _is_strict_int(order_id):
            raise TypeError("order_id must be an int (not a bool) or None")
        kwargs: dict[str, Any] = {"symbol": symbol}
        if order_id is not None:
            kwargs["order_id"] = order_id
        return await self._call(
            "user_trades",
            sdk_method_name="account_trade_list",
            call_kind=CallKind.QUERY,
            kwargs=kwargs,
            summarize=_trades_summary,
        )

    async def account_balance(self) -> ProbeObservation:
        """GET /fapi/v3/balance: assets with a non-zero balance, as text rows."""
        return await self._call(
            "account_balance",
            sdk_method_name="futures_account_balance_v3",
            call_kind=CallKind.QUERY,
            kwargs={},
            summarize=_balance_summary,
        )

    async def mark_price(self, *, symbol: str) -> ProbeObservation:
        """The latest `MARK_PRICE_INTERVAL` mark-price kline close, through the public reader."""

        async def read() -> list[MarkKline]:
            return await self._public.mark_klines(
                symbol, MARK_PRICE_INTERVAL, limit=_LATEST_ROW_ONLY
            )

        return await self._public_read(
            "mark_price", read, lambda klines: _mark_price_summary(symbol, klines)
        )

    async def symbol_filters(self, *, symbol: str) -> ProbeObservation:
        """Tick, step, minimum quantity, minimum notional and PERCENT_PRICE of one symbol."""
        return await self._public_read(
            "symbol_filters",
            self._public.exchange_info,
            lambda filters: _symbol_filters_summary(symbol, filters),
        )

    # ----- capture operations (quick task 261021-sj0; each sent once, never retried) -- #

    async def account_information(self) -> ProbeObservation:
        """GET /fapi/v3/account: every present field, flattened (equity field names)."""
        return await self._call(
            "account_information",
            sdk_method_name="account_information_v3",
            call_kind=CallKind.QUERY,
            kwargs={},
            summarize=_flat_summary,
        )

    async def account_balance_all(self) -> ProbeObservation:
        """GET /fapi/v3/balance: every asset and every field (unlike `account_balance`)."""
        return await self._call(
            "account_balance_all",
            sdk_method_name="futures_account_balance_v3",
            call_kind=CallKind.QUERY,
            kwargs={},
            summarize=_flat_summary,
        )

    async def account_config(self) -> ProbeObservation:
        """GET /fapi/v1/accountConfig: dualSidePosition, multiAssetsMargin, fee tier."""
        return await self._call(
            "account_config",
            sdk_method_name="futures_account_configuration",
            call_kind=CallKind.QUERY,
            kwargs={},
            summarize=_flat_summary,
        )

    async def symbol_config(self, *, symbol: str) -> ProbeObservation:
        """GET /fapi/v1/symbolConfig for one symbol: margin type and leverage."""
        return await self._call(
            "symbol_config",
            sdk_method_name="symbol_configuration",
            call_kind=CallKind.QUERY,
            kwargs={"symbol": symbol},
            summarize=_flat_summary,
        )

    async def leverage_brackets(self, *, symbol: str) -> ProbeObservation:
        """GET /fapi/v1/leverageBracket for one symbol (the oneOf answer is unwrapped)."""
        return await self._call(
            "leverage_brackets",
            sdk_method_name="notional_and_leverage_brackets",
            call_kind=CallKind.QUERY,
            kwargs={"symbol": symbol},
            summarize=_flat_summary,
        )

    async def income_history(self, *, symbol: str, start_time_ms: int) -> ProbeObservation:
        """GET /fapi/v1/income from `start_time_ms`: no type filter, no limit (exchange default)."""
        if not _is_strict_int(start_time_ms):
            raise TypeError("start_time_ms must be an int (not a bool)")
        if start_time_ms <= 0:
            raise ValueError("start_time_ms must be positive")
        return await self._call(
            "income_history",
            sdk_method_name="get_income_history",
            call_kind=CallKind.QUERY,
            kwargs={"symbol": symbol, "start_time": start_time_ms},
            summarize=_income_summary,
        )

    async def query_algo_order_by_algo_id(self, *, algo_id: int) -> ProbeObservation:
        """GET /fapi/v1/algoOrder by the exchange's algo id (the id of the placement answer)."""
        if not _is_strict_int(algo_id):
            raise TypeError("algo_id must be an int (not a bool)")
        if algo_id <= 0:
            raise ValueError("algo_id must be positive")
        return await self._call(
            "query_algo_order_by_algo_id",
            sdk_method_name="query_algo_order",
            call_kind=CallKind.QUERY,
            kwargs={"algo_id": algo_id},
            summarize=_algo_order_summary,
        )

    async def new_gtd_limit_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        client_order_id: str,
        position_side: str,
        good_till_date_ms: int,
    ) -> ProbeObservation:
        """POST /fapi/v1/order LIMIT with timeInForce GTD and goodTillDate (epoch ms, an int).

        No reduce-only parameter. Whether the exchange accepts a goodTillDate below its own
        floor is itself evidence, so the value is checked for type and sign only.
        """
        if not _is_strict_int(good_till_date_ms):
            raise TypeError("good_till_date_ms must be an int (not a bool)")
        if good_till_date_ms <= 0:
            raise ValueError("good_till_date_ms must be positive")
        kwargs: dict[str, Any] = {
            "symbol": symbol,
            "side": _member(NewOrderSideEnum, "side", side),
            "type": NewOrderTypeEnum.LIMIT,
            "position_side": position_side,
            "time_in_force": NewOrderTimeInForceEnum.GTD,
            "quantity": _money("quantity", quantity),
            "price": _money("price", price),
            "new_client_order_id": client_order_id,
            "good_till_date": good_till_date_ms,
        }
        return await self._call(
            "new_gtd_limit_order",
            sdk_method_name="new_order",
            call_kind=CallKind.PLACEMENT,
            kwargs=kwargs,
            summarize=_order_summary,
        )

    async def server_time(self) -> ProbeObservation:
        """GET /fapi/v1/time through the public reader: the exchange clock (261022-sj1)."""

        async def read() -> datetime:
            return await self._public.server_time()

        return await self._public_read("server_time", read, _server_time_summary)

    async def order_book(self, *, symbol: str) -> ProbeObservation:
        """GET /fapi/v1/depth, the top `ORDER_BOOK_LIMIT` levels per side (public, unsigned)."""

        async def read() -> OrderBookReading:
            return await self._public.order_book(symbol, ORDER_BOOK_LIMIT)

        return await self._public_read("order_book", read, _order_book_summary)

    async def live_mark_price(self, *, symbol: str) -> ProbeObservation:
        """The live premiumIndex mark price and the exchange time, through the public reader.

        Unlike `mark_price` (the last one-minute mark-kline close, which stayed unchanged for
        seconds on Demo), this is the current mark the trigger cases price against.
        """

        async def read() -> Any:
            return await self._public.mark_price(symbol)

        return await self._public_read(
            "live_mark_price",
            read,
            lambda reading: {
                "symbol": reading.symbol,
                "mark_price": _text(reading.mark_price),
                "exchange_time_utc": _text(reading.exchange_time_utc),
            },
        )


__all__ = [
    "MARK_PRICE_INTERVAL",
    "CONDITIONAL_ORDER_TYPES",
    "ERROR_MESSAGE_MAX_CHARS",
    "FLAT_SUMMARY_MAX_KEYS",
    "ORDER_BOOK_LIMIT",
    "SDK_REST_METHODS",
    "BinanceProbeAdapter",
    "ErrorObservation",
    "ProbeBanned",
    "ProbeObservation",
]
