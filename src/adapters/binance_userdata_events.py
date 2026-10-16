"""Typed, SDK-free events of the Binance USD-M user-data stream (Phase 18, plan 18-03).

The stream is a hint plus evidence; REST stays the authority (D-05). This
module turns one message handed to an SDK stream callback into either a
frozen event dataclass or a `StreamAnomaly`. It never coerces: a field of the
wrong wire type, a missing required field or an unparseable value becomes an
anomaly with a deterministic payload hash, and nothing is defaulted to zero
(D-05, research P4 and P17).

SDK-free by construction: the only imports are the standard library,
`src.execution.fill_monitor.FillEvent` and `src.domain.algo_status`. The SDK
message is read by duck typing
(`actual_instance`, `to_dict`) in `unwrap_message`; no SDK, requests,
aiohttp, SQLAlchemy, Pydantic or Polars import appears here. No wall clock
is read: `observed_at_utc` is always an argument.

Wire field names and Python types follow the installed SDK models
(`binance_sdk_derivatives_trading_usds_futures` 17.4.0,
`websocket_streams/models/*.py`, read as files): strings carry money,
quantities and prices; ints carry ids and millisecond times; bools carry
flags. The event field tables of the Binance pages could not be read; only
the value lists (order `x` and `X`, algo `X`, account `m`) and the event
names were read, as WebFetch summaries that are not verified live
(docs/SOURCES.md, "Facts read for Phase 18"). The event shapes were reviewed
by the user at the plan 18-03 design gate
(`decisions/18-DEC-D01-event-types.md`, option amend).

Routing (`parse_stream_message`): ORDER_TRADE_UPDATE, ALGO_UPDATE,
ACCOUNT_UPDATE, listenKeyExpired and ACCOUNT_CONFIG_UPDATE become typed
events; TRADE_LITE, STRATEGY_UPDATE and GRID_UPDATE become `IgnoredEvent`;
MARGIN_CALL is an UNHANDLED_EVENT anomaly, CONDITIONAL_ORDER_TRIGGER_REJECT a
DEPRECATED_EVENT anomaly and any other name an UNKNOWN_EVENT_TYPE anomaly.
Exchange-supplied free text (`rm`, reasons) is data: nothing here parses it
for a decision.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Protocol

from src.domain.algo_status import is_known_algo_status
from src.execution.fill_monitor import FillEvent

# --------------------------------------------------------------------------- #
# Anomaly vocabulary.
# --------------------------------------------------------------------------- #


class StreamAnomalyKind(str, Enum):
    """Why a stream message did not become a typed event (D-05).

    Every kind is journaled and surfaced as a divergence by the router
    (plan 18-15); none is ever dropped or coerced into an event.
    """

    UNRECOGNIZED_ENVELOPE = "UNRECOGNIZED_ENVELOPE"
    MALFORMED_PAYLOAD = "MALFORMED_PAYLOAD"
    FIELD_VALIDATION = "FIELD_VALIDATION"
    UNKNOWN_EVENT_TYPE = "UNKNOWN_EVENT_TYPE"
    UNKNOWN_EXECUTION_TYPE = "UNKNOWN_EXECUTION_TYPE"
    UNKNOWN_ORDER_STATUS = "UNKNOWN_ORDER_STATUS"
    UNKNOWN_ALGO_STATUS = "UNKNOWN_ALGO_STATUS"
    FORCED_CLOSE_ORDER = "FORCED_CLOSE_ORDER"
    AMENDMENT_EVENT = "AMENDMENT_EVENT"
    LIQUIDATION_EVENT = "LIQUIDATION_EVENT"
    DEPRECATED_EVENT = "DEPRECATED_EVENT"
    UNHANDLED_EVENT = "UNHANDLED_EVENT"
    FILL_TOTAL_MISMATCH = "FILL_TOTAL_MISMATCH"
    UNKNOWN_ORDER = "UNKNOWN_ORDER"
    QUEUE_OVERFLOW = "QUEUE_OVERFLOW"


DETAIL_MAX_CHARS = 200
EVENT_NAME_MAX_CHARS = 64
FIELD_PATH_MAX_CHARS = 64

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# Plain ASCII decimal text only: no whitespace, no underscores, no NaN or
# Infinity, no non-ASCII digits (all of which `Decimal()` would accept).
_DECIMAL_TEXT = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", re.ASCII)
_SIDES: frozenset[str] = frozenset({"BUY", "SELL"})
_EXECUTION_TYPE_TRADE = "TRADE"
_EXECUTION_TYPE_AMENDMENT = "AMENDMENT"
_EXECUTION_TYPE_CALCULATED = "CALCULATED"

# Wire event names (the `e` value). The SDK model class names
# (`OrderTradeUpdate`, ...) meet them through `normalize_event_name`.
ORDER_TRADE_UPDATE_EVENT = "ORDER_TRADE_UPDATE"
ALGO_UPDATE_EVENT = "ALGO_UPDATE"
ACCOUNT_UPDATE_EVENT = "ACCOUNT_UPDATE"
LISTEN_KEY_EXPIRED_EVENT = "listenKeyExpired"
ACCOUNT_CONFIG_UPDATE_EVENT = "ACCOUNT_CONFIG_UPDATE"

# Order Update value lists as read on 2026-10-16 (WebFetch summary, not
# character-exact, not verified live; docs/SOURCES.md "Facts read for
# Phase 18"). A value outside them is an UNKNOWN_* anomaly, never coerced.
ORDER_EXECUTION_TYPE_VOCABULARY: frozenset[str] = frozenset(
    {"NEW", "CANCELED", "CALCULATED", "EXPIRED", "TRADE", "AMENDMENT"}
)
ORDER_STATUS_VOCABULARY: frozenset[str] = frozenset(
    {"NEW", "PARTIALLY_FILLED", "FILLED", "CANCELED", "EXPIRED", "EXPIRED_IN_MATCH"}
)
# AMENDMENT (the project never amends orders) and CALCULATED (liquidation)
# are anomalies, so an OrderUpdateEvent never carries them.
_EVENT_EXECUTION_TYPES: frozenset[str] = ORDER_EXECUTION_TYPE_VOCABULARY - {
    _EXECUTION_TYPE_AMENDMENT,
    _EXECUTION_TYPE_CALCULATED,
}
# Client order ids of orders the exchange placed (liquidation, ADL,
# settlement): never the project's orders. `settlement_autoclose-` comes from
# the research baseline B5b and is absent from the page read on 2026-10-16;
# it is kept because an extra forced-close prefix only adds an anomaly.
FORCED_CLOSE_CLIENT_ID_PREFIXES: tuple[str, ...] = (
    "autoclose-",
    "adl_autoclose",
    "settlement_autoclose-",
)

REJECT_REASON_MAX_CHARS = 200
IGNORED_REASON_MAX_CHARS = 200
FUNDING_FEE_REASON = "FUNDING_FEE"

# The wire keys each parser reads (plan 18-11 pins them against the SDK
# model aliases). Keys of the `o` object of ORDER_TRADE_UPDATE; `b`, `a`,
# `si` and `ss` are not read.
ORDER_UPDATE_WIRE_FIELDS: frozenset[str] = frozenset(
    {
        "s",
        "c",
        "S",
        "o",
        "f",
        "q",
        "p",
        "ap",
        "sp",
        "x",
        "X",
        "i",
        "l",
        "z",
        "L",
        "N",
        "n",
        "T",
        "t",
        "m",
        "R",
        "wt",
        "ot",
        "ps",
        "rp",
        "M",
        "er",
        "V",
        "pm",
        "cp",
        "pP",
        "AP",
        "cr",
        "gtd",
    }
)
# Keys of the `o` object of ALGO_UPDATE (all 26 keys of the SDK model).
ALGO_UPDATE_WIRE_FIELDS: frozenset[str] = frozenset(
    {
        "caid",
        "aid",
        "at",
        "o",
        "s",
        "S",
        "ps",
        "f",
        "q",
        "X",
        "ai",
        "ap",
        "aq",
        "act",
        "tp",
        "p",
        "V",
        "wt",
        "pm",
        "cp",
        "pP",
        "R",
        "tt",
        "gtd",
        "rm",
        "ia",
    }
)
# Keys of the `a` object of ACCOUNT_UPDATE, and of its `B` and `P` rows.
ACCOUNT_UPDATE_WIRE_FIELDS: frozenset[str] = frozenset({"m", "B", "P", "S"})
ACCOUNT_BALANCE_WIRE_FIELDS: frozenset[str] = frozenset({"a", "wb", "cw", "bc"})
ACCOUNT_POSITION_WIRE_FIELDS: frozenset[str] = frozenset(
    {"s", "pa", "ep", "bep", "cr", "up", "mt", "iw", "ps"}
)


# --------------------------------------------------------------------------- #
# Dataclass validation helpers (raise TypeError / ValueError; messages carry
# field names and type names only, never a value).
# --------------------------------------------------------------------------- #


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{name} must be a non-empty string")


def _optional_text(value: object, name: str) -> None:
    if value is not None:
        _require_text(value, name)


def _require_decimal(value: object, name: str, *, non_negative: bool) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if non_negative and value < 0:
        raise ValueError(f"{name} must be non-negative")


def _optional_decimal(value: object, name: str, *, non_negative: bool) -> None:
    if value is not None:
        _require_decimal(value, name, non_negative=non_negative)


def _require_utc(value: object, name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be a UTC-aware datetime")


def _optional_bool(value: object, name: str) -> None:
    if value is not None and not isinstance(value, bool):
        raise TypeError(f"{name} must be bool, got {type(value).__name__}")


def _optional_non_negative_int(value: object, name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


# --------------------------------------------------------------------------- #
# StreamAnomaly.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class StreamAnomaly:
    """A stream message that did not become a typed event (D-05).

    `detail` is built from field names and type names only (never a raw
    payload value) and is at most 200 characters. `payload_sha256` is the
    sha256 of the canonical JSON (sorted keys, compact separators, ASCII) of
    the offending payload, so the same payload always gives the same hash.
    `event_name` and `field` may be None (an unrecognized envelope has
    neither).
    """

    kind: StreamAnomalyKind
    event_name: str | None
    field: str | None
    detail: str
    payload_sha256: str
    observed_at_utc: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.kind, StreamAnomalyKind):
            raise TypeError(f"kind must be StreamAnomalyKind, got {type(self.kind).__name__}")
        _optional_text(self.event_name, "event_name")
        if self.event_name is not None and len(self.event_name) > EVENT_NAME_MAX_CHARS:
            raise ValueError(f"event_name must be at most {EVENT_NAME_MAX_CHARS} characters")
        _optional_text(self.field, "field")
        if self.field is not None and len(self.field) > FIELD_PATH_MAX_CHARS:
            raise ValueError(f"field must be at most {FIELD_PATH_MAX_CHARS} characters")
        _require_text(self.detail, "detail")
        if len(self.detail) > DETAIL_MAX_CHARS:
            raise ValueError(f"detail must be at most {DETAIL_MAX_CHARS} characters")
        if not isinstance(self.payload_sha256, str) or not _SHA256_HEX.fullmatch(
            self.payload_sha256
        ):
            raise ValueError("payload_sha256 must be 64 lowercase hex characters")
        _require_utc(self.observed_at_utc, "observed_at_utc")


def _canonical_default(obj: object) -> object:
    """JSON fallback for values a decoded frame never holds (deterministic, no addresses)."""
    if isinstance(obj, Decimal):
        return {"__decimal__": str(obj)}
    return {"__type__": type(obj).__name__}


def canonical_payload_sha256(payload: object) -> str:
    """sha256 of the canonical JSON of `payload` (sorted keys, compact, ASCII)."""
    try:
        text = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=_canonical_default,
        )
    except (TypeError, ValueError):
        # Non-string keys or a reference cycle: hash a deterministic marker.
        text = json.dumps({"__unserializable__": type(payload).__name__}, sort_keys=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def make_stream_anomaly(
    kind: StreamAnomalyKind,
    *,
    event_name: str | None,
    field: str | None,
    detail: str,
    payload: object,
    observed_at_utc: datetime,
) -> StreamAnomaly:
    """Build a `StreamAnomaly`, bounding the free-text attributes.

    `detail` must already be free of payload values; this function only caps
    its length. `event_name` is capped to 64 characters.
    """
    name = None if event_name in (None, "") else str(event_name)[:EVENT_NAME_MAX_CHARS]
    return StreamAnomaly(
        kind=kind,
        event_name=name,
        field=None if field is None else field[:FIELD_PATH_MAX_CHARS],
        detail=detail[:DETAIL_MAX_CHARS],
        payload_sha256=canonical_payload_sha256(payload),
        observed_at_utc=observed_at_utc,
    )


# --------------------------------------------------------------------------- #
# OrderUpdateEvent (ORDER_TRADE_UPDATE).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class OrderUpdateEvent:
    """One ORDER_TRADE_UPDATE frame, typed (wire field in brackets).

    Required on the wire for every frame: `E`, `T`, and in `o`: `s`, `c`,
    `S`, `o`, `f`, `ps`, `q`, `x`, `X`, `i`, `T`; additionally for `x` TRADE:
    `l`, `L`, `z`, `t`. `exchange_order_id` is the int `i` as text;
    `trade_id` is the int `t` as text, set only for TRADE and otherwise None
    whatever the wire carries (never synthesized). Quantities and prices are
    non-negative Decimals; `commission` and `realized_profit` may be signed.

    The design gate (decisions/18-DEC-D01-event-types.md) added five optional
    fields: `close_position` (`o.cp`) and `price_protect` (`o.pP`) as strict
    bools, `activation_price` (`o.AP`) and `callback_rate` (`o.cr`) as
    non-negative Decimals (pushed for trailing stops only), and
    `good_till_date_ms` (`o.gtd`) as the raw non-negative integer: no
    timestamp meaning is inferred from it without verified documentation.
    """

    event_time_utc: datetime  # E
    transaction_time_utc: datetime  # T
    symbol: str  # o.s
    client_order_id: str  # o.c
    side: str  # o.S
    order_type: str  # o.o
    original_order_type: str | None = None  # o.ot
    time_in_force: str  # o.f
    position_side: str  # o.ps
    original_quantity: Decimal  # o.q
    original_price: Decimal | None = None  # o.p
    average_price: Decimal | None = None  # o.ap
    stop_price: Decimal | None = None  # o.sp
    execution_type: str  # o.x
    order_status: str  # o.X
    exchange_order_id: str  # o.i
    last_filled_quantity: Decimal | None = None  # o.l
    accumulated_filled_quantity: Decimal | None = None  # o.z
    last_filled_price: Decimal | None = None  # o.L
    commission: Decimal | None = None  # o.n
    commission_asset: str | None = None  # o.N
    trade_time_utc: datetime  # o.T
    trade_id: str | None = None  # o.t
    is_maker: bool | None = None  # o.m
    reduce_only: bool | None = None  # o.R
    working_type: str | None = None  # o.wt
    realized_profit: Decimal | None = None  # o.rp
    modify_id: str | None = None  # o.M
    expire_reason: str | None = None  # o.er
    stp_mode: str | None = None  # o.V
    price_match: str | None = None  # o.pm
    # Added by the design gate (decisions/18-DEC-D01-event-types.md, option amend).
    close_position: bool | None = None  # o.cp
    price_protect: bool | None = None  # o.pP
    activation_price: Decimal | None = None  # o.AP (trailing stop only)
    callback_rate: Decimal | None = None  # o.cr (trailing stop only)
    good_till_date_ms: int | None = None  # o.gtd: the raw integer, no meaning inferred

    def __post_init__(self) -> None:
        for name in (
            "symbol",
            "client_order_id",
            "side",
            "order_type",
            "time_in_force",
            "position_side",
            "execution_type",
            "order_status",
            "exchange_order_id",
        ):
            _require_text(getattr(self, name), name)
        for name in (
            "original_order_type",
            "commission_asset",
            "trade_id",
            "working_type",
            "modify_id",
            "expire_reason",
            "stp_mode",
            "price_match",
        ):
            _optional_text(getattr(self, name), name)
        if self.side not in _SIDES:
            raise ValueError("side must be BUY or SELL")
        if self.execution_type not in _EVENT_EXECUTION_TYPES:
            raise ValueError("execution_type is outside the parsed execution types")
        if self.order_status not in ORDER_STATUS_VOCABULARY:
            raise ValueError("order_status is outside the documented order statuses")
        _require_decimal(self.original_quantity, "original_quantity", non_negative=True)
        for name in (
            "original_price",
            "average_price",
            "stop_price",
            "last_filled_quantity",
            "accumulated_filled_quantity",
            "last_filled_price",
            "activation_price",
            "callback_rate",
        ):
            _optional_decimal(getattr(self, name), name, non_negative=True)
        for name in ("commission", "realized_profit"):
            _optional_decimal(getattr(self, name), name, non_negative=False)
        for name in ("event_time_utc", "transaction_time_utc", "trade_time_utc"):
            _require_utc(getattr(self, name), name)
        for name in ("is_maker", "reduce_only", "close_position", "price_protect"):
            _optional_bool(getattr(self, name), name)
        _optional_non_negative_int(self.good_till_date_ms, "good_till_date_ms")
        if self.trade_id is not None and self.execution_type != _EXECUTION_TYPE_TRADE:
            raise ValueError("trade_id is set only for execution_type TRADE")


# --------------------------------------------------------------------------- #
# AlgoUpdateEvent (ALGO_UPDATE).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class AlgoUpdateEvent:
    """One ALGO_UPDATE frame, typed (wire field in brackets).

    Required on the wire: `E`, `T`, and in `o`: `caid`, `aid`, `at`, `o`,
    `s`, `S`, `ps`, `f`, `q`, `X`, `tp`; every other key is optional.
    `algo_status` is the raw `X` string and must be in
    `ALGO_STATUS_VOCABULARY` (otherwise the parser yields an
    UNKNOWN_ALGO_STATUS anomaly); classifying it is plan 18-06.
    `actual_order_id` is the matching-engine order id once triggered (`ai`,
    text per the SDK) and None while `ai` is the empty string or absent.
    `average_price`, `executed_quantity` and `actual_order_type` are shown by
    Binance only once triggered (SDK description). `reject_reason` is the
    free text `rm`, verbatim and bounded to 200 characters: a diagnostic only,
    never a decision input (P23). `trigger_time_utc` is `tt` converted
    exactly (a 0 becomes the epoch; nothing is inferred from it).
    `good_till_date_ms` is the raw `gtd` integer. A trailing-stop update may
    arrive twice (`ia` false, then true): both parse, de-duplication is the
    router's (plan 18-15).
    """

    event_time_utc: datetime  # E
    transaction_time_utc: datetime  # T
    client_algo_id: str  # o.caid
    algo_id: str  # o.aid (int on the wire, kept as text)
    algo_type: str  # o.at
    order_type: str  # o.o
    symbol: str  # o.s
    side: str  # o.S
    position_side: str  # o.ps
    time_in_force: str  # o.f
    quantity: Decimal  # o.q
    algo_status: str  # o.X
    actual_order_id: str | None = None  # o.ai
    average_price: Decimal | None = None  # o.ap
    executed_quantity: Decimal | None = None  # o.aq
    actual_order_type: str | None = None  # o.act
    trigger_price: Decimal  # o.tp
    price: Decimal | None = None  # o.p
    working_type: str | None = None  # o.wt
    reduce_only: bool | None = None  # o.R
    close_position: bool | None = None  # o.cp
    price_protect: bool | None = None  # o.pP
    trigger_time_utc: datetime | None = None  # o.tt
    reject_reason: str | None = None  # o.rm
    is_activated: bool | None = None  # o.ia
    # Added by the design gate (decisions/18-DEC-D01-event-types.md, Q6).
    stp_mode: str | None = None  # o.V
    price_match: str | None = None  # o.pm
    good_till_date_ms: int | None = None  # o.gtd

    def __post_init__(self) -> None:
        for name in (
            "client_algo_id",
            "algo_id",
            "algo_type",
            "order_type",
            "symbol",
            "side",
            "position_side",
            "time_in_force",
            "algo_status",
        ):
            _require_text(getattr(self, name), name)
        for name in (
            "actual_order_id",
            "actual_order_type",
            "working_type",
            "reject_reason",
            "stp_mode",
            "price_match",
        ):
            _optional_text(getattr(self, name), name)
        if self.side not in _SIDES:
            raise ValueError("side must be BUY or SELL")
        if not is_known_algo_status(self.algo_status):
            raise ValueError("algo_status is outside the algo status vocabulary")
        if self.reject_reason is not None and len(self.reject_reason) > REJECT_REASON_MAX_CHARS:
            raise ValueError(f"reject_reason must be at most {REJECT_REASON_MAX_CHARS} characters")
        _require_decimal(self.quantity, "quantity", non_negative=True)
        _require_decimal(self.trigger_price, "trigger_price", non_negative=True)
        for name in ("average_price", "executed_quantity", "price"):
            _optional_decimal(getattr(self, name), name, non_negative=True)
        for name in ("event_time_utc", "transaction_time_utc"):
            _require_utc(getattr(self, name), name)
        if self.trigger_time_utc is not None:
            _require_utc(self.trigger_time_utc, "trigger_time_utc")
        for name in ("reduce_only", "close_position", "price_protect", "is_activated"):
            _optional_bool(getattr(self, name), name)
        _optional_non_negative_int(self.good_till_date_ms, "good_till_date_ms")


# --------------------------------------------------------------------------- #
# AccountUpdateEvent (ACCOUNT_UPDATE): deltas only (D-08).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class BalanceDelta:
    """One `a.B` row of ACCOUNT_UPDATE, as pushed (all money signed Decimals)."""

    asset: str  # a
    wallet_balance: Decimal  # wb
    cross_wallet_balance: Decimal  # cw
    balance_change: Decimal  # bc (balance change except PnL and commission)

    def __post_init__(self) -> None:
        _require_text(self.asset, "asset")
        for name in ("wallet_balance", "cross_wallet_balance", "balance_change"):
            _require_decimal(getattr(self, name), name, non_negative=False)


@dataclass(frozen=True, kw_only=True)
class PositionDelta:
    """One `a.P` row of ACCOUNT_UPDATE, as pushed.

    `position_amount` is signed (negative is short in one-way mode). Prices
    are non-negative; realized, unrealized and the isolated wallet are signed.
    Required on the wire: `s`, `pa`, `ep`, `up`, `mt`, `ps`; `bep`, `cr`,
    `iw` are optional.
    """

    symbol: str  # s
    position_amount: Decimal  # pa
    entry_price: Decimal  # ep
    breakeven_price: Decimal | None = None  # bep
    accumulated_realized: Decimal | None = None  # cr
    unrealized_pnl: Decimal  # up
    margin_type: str  # mt
    isolated_wallet: Decimal | None = None  # iw
    position_side: str  # ps

    def __post_init__(self) -> None:
        for name in ("symbol", "margin_type", "position_side"):
            _require_text(getattr(self, name), name)
        _require_decimal(self.position_amount, "position_amount", non_negative=False)
        _require_decimal(self.entry_price, "entry_price", non_negative=True)
        _optional_decimal(self.breakeven_price, "breakeven_price", non_negative=True)
        _require_decimal(self.unrealized_pnl, "unrealized_pnl", non_negative=False)
        for name in ("accumulated_realized", "isolated_wallet"):
            _optional_decimal(getattr(self, name), name, non_negative=False)


@dataclass(frozen=True, kw_only=True)
class AccountUpdateEvent:
    """One ACCOUNT_UPDATE frame: balance and position DELTAS only (D-08).

    Nothing here (or anywhere in this module) computes equity, margin or a
    position view from these rows; REST stays the authority (D-05). `reason`
    is `a.m` carried verbatim: an unknown reason is not an anomaly (the
    reason list is documentation vocabulary, not a decision input).
    `funding_symbol` is `a.S`, accepted only when the reason is FUNDING_FEE.
    An absent `B` or `P` list is an empty tuple.
    """

    event_time_utc: datetime  # E
    transaction_time_utc: datetime  # T
    reason: str  # a.m
    balances: tuple[BalanceDelta, ...] = ()  # a.B
    positions: tuple[PositionDelta, ...] = ()  # a.P
    funding_symbol: str | None = None  # a.S

    def __post_init__(self) -> None:
        for name in ("event_time_utc", "transaction_time_utc"):
            _require_utc(getattr(self, name), name)
        _require_text(self.reason, "reason")
        if not isinstance(self.balances, tuple) or not all(
            isinstance(row, BalanceDelta) for row in self.balances
        ):
            raise TypeError("balances must be a tuple of BalanceDelta")
        if not isinstance(self.positions, tuple) or not all(
            isinstance(row, PositionDelta) for row in self.positions
        ):
            raise TypeError("positions must be a tuple of PositionDelta")
        _optional_text(self.funding_symbol, "funding_symbol")
        if self.funding_symbol is not None and self.reason != FUNDING_FEE_REASON:
            raise ValueError("funding_symbol is accepted only for reason FUNDING_FEE")


# --------------------------------------------------------------------------- #
# ListenKeyExpiredEvent, AccountConfigUpdateEvent, IgnoredEvent.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class ListenKeyExpiredEvent:
    """The listenKey of the connection expired (`listenKeyExpired`).

    Carries only the event time. The listenKey is a credential: it is never
    read into this type, an anomaly detail or a repr.
    """

    event_time_utc: datetime  # E

    def __post_init__(self) -> None:
        _require_utc(self.event_time_utc, "event_time_utc")


@dataclass(frozen=True, kw_only=True)
class AccountConfigUpdateEvent:
    """One ACCOUNT_CONFIG_UPDATE frame: a leverage change or a Multi-Assets mode change.

    `symbol` and `leverage` come from `ac` (`s` text, `l` int >= 1, both or
    neither); `multi_assets` from `ai.j` (bool). At least one of the two
    parts is present. A hint only: REST stays the authority.
    """

    event_time_utc: datetime  # E
    transaction_time_utc: datetime  # T
    symbol: str | None = None  # ac.s
    leverage: int | None = None  # ac.l
    multi_assets: bool | None = None  # ai.j

    def __post_init__(self) -> None:
        for name in ("event_time_utc", "transaction_time_utc"):
            _require_utc(getattr(self, name), name)
        _optional_text(self.symbol, "symbol")
        if self.leverage is not None:
            if isinstance(self.leverage, bool) or not isinstance(self.leverage, int):
                raise TypeError(f"leverage must be int, got {type(self.leverage).__name__}")
            if self.leverage < 1:
                raise ValueError("leverage must be at least 1")
        if (self.symbol is None) != (self.leverage is None):
            raise ValueError("symbol and leverage are given together or not at all")
        _optional_bool(self.multi_assets, "multi_assets")
        if self.leverage is None and self.multi_assets is None:
            raise ValueError("an account config update carries leverage or multi_assets")


@dataclass(frozen=True, kw_only=True)
class IgnoredEvent:
    """A recognized event the project does not use (TRADE_LITE, STRATEGY_UPDATE, GRID_UPDATE).

    Counted by the router, not journaled as an anomaly. `event_name` is the
    name as received (at most 64 characters); `reason` is fixed project text.
    """

    event_name: str
    reason: str

    def __post_init__(self) -> None:
        _require_text(self.event_name, "event_name")
        if len(self.event_name) > EVENT_NAME_MAX_CHARS:
            raise ValueError(f"event_name must be at most {EVENT_NAME_MAX_CHARS} characters")
        _require_text(self.reason, "reason")
        if len(self.reason) > IGNORED_REASON_MAX_CHARS:
            raise ValueError(f"reason must be at most {IGNORED_REASON_MAX_CHARS} characters")


StreamOutcome = (
    OrderUpdateEvent
    | AlgoUpdateEvent
    | AccountUpdateEvent
    | ListenKeyExpiredEvent
    | AccountConfigUpdateEvent
    | IgnoredEvent
    | StreamAnomaly
)


# --------------------------------------------------------------------------- #
# Strict wire-field readers. A failure raises `_ParseError`, which the parser
# turns into a `StreamAnomaly`; details name the field path and type only.
# --------------------------------------------------------------------------- #


class _ParseError(Exception):
    def __init__(self, kind: StreamAnomalyKind, field: str, detail: str) -> None:
        super().__init__(detail)
        self.kind = kind
        self.field = field
        self.detail = detail


def _path(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def _required(obj: Mapping[str, Any], key: str, prefix: str) -> Any:
    value = obj.get(key)
    if value is None:
        path = _path(prefix, key)
        raise _ParseError(
            StreamAnomalyKind.MALFORMED_PAYLOAD, path, f"required field {path} is missing"
        )
    return value


def _invalid(path: str, expected: str, value: object) -> _ParseError:
    return _ParseError(
        StreamAnomalyKind.FIELD_VALIDATION,
        path,
        f"field {path} must be {expected}, got {type(value).__name__}",
    )


def _decimal_value(value: object, path: str, *, non_negative: bool) -> Decimal:
    if not isinstance(value, str):
        raise _invalid(path, "a decimal string", value)
    if _DECIMAL_TEXT.fullmatch(value) is None:
        raise _ParseError(
            StreamAnomalyKind.FIELD_VALIDATION, path, f"field {path} is not plain decimal text"
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise _ParseError(
            StreamAnomalyKind.FIELD_VALIDATION, path, f"field {path} is not plain decimal text"
        ) from None
    if not parsed.is_finite():
        raise _ParseError(StreamAnomalyKind.FIELD_VALIDATION, path, f"field {path} is not finite")
    if non_negative and parsed < 0:
        raise _ParseError(
            StreamAnomalyKind.FIELD_VALIDATION, path, f"field {path} must be non-negative"
        )
    return parsed


def _money(obj: Mapping[str, Any], key: str, prefix: str, *, non_negative: bool) -> Decimal:
    return _decimal_value(
        _required(obj, key, prefix), _path(prefix, key), non_negative=non_negative
    )


def _money_opt(
    obj: Mapping[str, Any], key: str, prefix: str, *, non_negative: bool
) -> Decimal | None:
    value = obj.get(key)
    if value is None:
        return None
    return _decimal_value(value, _path(prefix, key), non_negative=non_negative)


def _text_value(value: object, path: str) -> str:
    if not isinstance(value, str) or value == "":
        raise _invalid(path, "a non-empty string", value)
    return value


def _text(obj: Mapping[str, Any], key: str, prefix: str) -> str:
    return _text_value(_required(obj, key, prefix), _path(prefix, key))


def _text_opt(obj: Mapping[str, Any], key: str, prefix: str) -> str | None:
    value = obj.get(key)
    return None if value is None else _text_value(value, _path(prefix, key))


def _int_value(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _invalid(path, "a non-negative integer", value)
    return value


def _int_id(obj: Mapping[str, Any], key: str, prefix: str) -> int:
    return _int_value(_required(obj, key, prefix), _path(prefix, key))


def _int_id_opt(obj: Mapping[str, Any], key: str, prefix: str) -> int | None:
    value = obj.get(key)
    return None if value is None else _int_value(value, _path(prefix, key))


def _ms_to_utc(ms: int, path: str) -> datetime:
    """Exact millisecond epoch to UTC (timedelta arithmetic, no float division)."""
    try:
        return _EPOCH + timedelta(milliseconds=ms)
    except OverflowError:
        raise _ParseError(
            StreamAnomalyKind.FIELD_VALIDATION, path, f"field {path} is out of the datetime range"
        ) from None


def _time(obj: Mapping[str, Any], key: str, prefix: str) -> datetime:
    return _ms_to_utc(_int_id(obj, key, prefix), _path(prefix, key))


def _flag_opt(obj: Mapping[str, Any], key: str, prefix: str) -> bool | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise _invalid(_path(prefix, key), "a bool", value)
    return value


def _object_value(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(k, str) for k in value):
        raise _invalid(path, "an object", value)
    return value


def _object(obj: Mapping[str, Any], key: str, prefix: str) -> Mapping[str, Any]:
    return _object_value(_required(obj, key, prefix), _path(prefix, key))


def _object_opt(obj: Mapping[str, Any], key: str, prefix: str) -> Mapping[str, Any] | None:
    value = obj.get(key)
    return None if value is None else _object_value(value, _path(prefix, key))


def _rows(obj: Mapping[str, Any], key: str, prefix: str) -> list[tuple[str, Mapping[str, Any]]]:
    """(row path, row object) of an optional list of objects; absent is empty."""
    value = obj.get(key)
    path = _path(prefix, key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise _invalid(path, "a list", value)
    rows: list[tuple[str, Mapping[str, Any]]] = []
    for index, row in enumerate(value):
        row_path = f"{path}[{index}]"
        rows.append((row_path, _object_value(row, row_path)))
    return rows


def _vocabulary_text(obj: Mapping[str, Any], key: str, prefix: str) -> str:
    """A required string field whose vocabulary is checked by the caller.

    A non-string is FIELD_VALIDATION; any string (also the empty one) is
    returned, so an unseen value becomes the caller's UNKNOWN_* anomaly.
    """
    value = _required(obj, key, prefix)
    if not isinstance(value, str):
        raise _invalid(_path(prefix, key), "a string", value)
    return value


def _positive_int(obj: Mapping[str, Any], key: str, prefix: str) -> int:
    path = _path(prefix, key)
    value = _required(obj, key, prefix)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(path, "a positive integer", value)
    return value


def _flag(obj: Mapping[str, Any], key: str, prefix: str) -> bool:
    value = _required(obj, key, prefix)
    if not isinstance(value, bool):
        raise _invalid(_path(prefix, key), "a bool", value)
    return value


def _side(obj: Mapping[str, Any], key: str, prefix: str) -> str:
    side = _text(obj, key, prefix)
    if side not in _SIDES:
        path = _path(prefix, key)
        raise _ParseError(
            StreamAnomalyKind.FIELD_VALIDATION, path, f"field {path} is not BUY or SELL"
        )
    return side


def _require_observed(observed_at_utc: datetime) -> None:
    if (
        not isinstance(observed_at_utc, datetime)
        or observed_at_utc.tzinfo is None
        or observed_at_utc.utcoffset() != timedelta(0)
    ):
        raise ValueError("observed_at_utc must be a UTC-aware datetime")


# --------------------------------------------------------------------------- #
# Parsers.
# --------------------------------------------------------------------------- #


def _classify_order_update(order: Mapping[str, Any], p: str) -> tuple[str, str, str]:
    """Read `c`, `x`, `X` and raise the order-level anomalies of research P22.

    Precedence (first match wins): an unseen `x` (UNKNOWN_EXECUTION_TYPE),
    `x` AMENDMENT (AMENDMENT_EVENT), `x` CALCULATED (LIQUIDATION_EVENT), a
    forced-close client order id (FORCED_CLOSE_ORDER), an unseen `X`
    (UNKNOWN_ORDER_STATUS). These run before the remaining fields are read,
    so such a frame is reported by what it is, not by a later field error.
    """
    client_order_id = _text(order, "c", p)
    execution_type = _vocabulary_text(order, "x", p)
    order_status = _vocabulary_text(order, "X", p)
    if execution_type not in ORDER_EXECUTION_TYPE_VOCABULARY:
        raise _ParseError(
            StreamAnomalyKind.UNKNOWN_EXECUTION_TYPE,
            "o.x",
            "field o.x is outside the documented execution types",
        )
    if execution_type == _EXECUTION_TYPE_AMENDMENT:
        raise _ParseError(
            StreamAnomalyKind.AMENDMENT_EVENT,
            "o.x",
            "field o.x reports an order amendment; the project never amends orders",
        )
    if execution_type == _EXECUTION_TYPE_CALCULATED:
        raise _ParseError(
            StreamAnomalyKind.LIQUIDATION_EVENT,
            "o.x",
            "field o.x reports a liquidation execution",
        )
    if client_order_id.startswith(FORCED_CLOSE_CLIENT_ID_PREFIXES):
        raise _ParseError(
            StreamAnomalyKind.FORCED_CLOSE_ORDER,
            "o.c",
            "field o.c carries a forced-close client order id prefix",
        )
    if order_status not in ORDER_STATUS_VOCABULARY:
        raise _ParseError(
            StreamAnomalyKind.UNKNOWN_ORDER_STATUS,
            "o.X",
            "field o.X is outside the documented order statuses",
        )
    return client_order_id, execution_type, order_status


def _build_order_update(payload: Mapping[str, Any]) -> OrderUpdateEvent:
    event_time = _time(payload, "E", "")
    transaction_time = _time(payload, "T", "")
    order = _object(payload, "o", "")
    p = "o"

    client_order_id, execution_type, order_status = _classify_order_update(order, p)
    side = _side(order, "S", p)
    is_trade = execution_type == _EXECUTION_TYPE_TRADE
    if is_trade:
        last_qty: Decimal | None = _money(order, "l", p, non_negative=True)
        last_price: Decimal | None = _money(order, "L", p, non_negative=True)
        accumulated: Decimal | None = _money(order, "z", p, non_negative=True)
        trade_id: str | None = str(_int_id(order, "t", p))
    else:
        last_qty = _money_opt(order, "l", p, non_negative=True)
        last_price = _money_opt(order, "L", p, non_negative=True)
        accumulated = _money_opt(order, "z", p, non_negative=True)
        _int_id_opt(order, "t", p)  # type-checked, then discarded: no trade id without TRADE
        trade_id = None

    return OrderUpdateEvent(
        event_time_utc=event_time,
        transaction_time_utc=transaction_time,
        symbol=_text(order, "s", p),
        client_order_id=client_order_id,
        side=side,
        order_type=_text(order, "o", p),
        original_order_type=_text_opt(order, "ot", p),
        time_in_force=_text(order, "f", p),
        position_side=_text(order, "ps", p),
        original_quantity=_money(order, "q", p, non_negative=True),
        original_price=_money_opt(order, "p", p, non_negative=True),
        average_price=_money_opt(order, "ap", p, non_negative=True),
        stop_price=_money_opt(order, "sp", p, non_negative=True),
        execution_type=execution_type,
        order_status=order_status,
        exchange_order_id=str(_int_id(order, "i", p)),
        last_filled_quantity=last_qty,
        accumulated_filled_quantity=accumulated,
        last_filled_price=last_price,
        commission=_money_opt(order, "n", p, non_negative=False),
        commission_asset=_text_opt(order, "N", p),
        trade_time_utc=_time(order, "T", p),
        trade_id=trade_id,
        is_maker=_flag_opt(order, "m", p),
        reduce_only=_flag_opt(order, "R", p),
        working_type=_text_opt(order, "wt", p),
        realized_profit=_money_opt(order, "rp", p, non_negative=False),
        modify_id=_text_opt(order, "M", p),
        expire_reason=_text_opt(order, "er", p),
        stp_mode=_text_opt(order, "V", p),
        price_match=_text_opt(order, "pm", p),
        close_position=_flag_opt(order, "cp", p),
        price_protect=_flag_opt(order, "pP", p),
        activation_price=_money_opt(order, "AP", p, non_negative=True),
        callback_rate=_money_opt(order, "cr", p, non_negative=True),
        good_till_date_ms=_int_id_opt(order, "gtd", p),
    )


def _build_algo_update(payload: Mapping[str, Any]) -> AlgoUpdateEvent:
    event_time = _time(payload, "E", "")
    transaction_time = _time(payload, "T", "")
    algo = _object(payload, "o", "")
    p = "o"

    algo_status = _vocabulary_text(algo, "X", p)
    if not is_known_algo_status(algo_status):
        raise _ParseError(
            StreamAnomalyKind.UNKNOWN_ALGO_STATUS,
            "o.X",
            "field o.X is outside the algo status vocabulary",
        )
    # `ai` is the matching-engine order id (text per the SDK); the empty
    # string means "not triggered yet" and is read as None (plan 18-03 Task 3).
    raw_actual_order_id = algo.get("ai")
    actual_order_id = (
        None
        if raw_actual_order_id is None or raw_actual_order_id == ""
        else _text_value(raw_actual_order_id, "o.ai")
    )
    reject_reason = _text_opt(algo, "rm", p)
    if reject_reason is not None:
        reject_reason = reject_reason[:REJECT_REASON_MAX_CHARS]
    trigger_time_ms = _int_id_opt(algo, "tt", p)

    return AlgoUpdateEvent(
        event_time_utc=event_time,
        transaction_time_utc=transaction_time,
        client_algo_id=_text(algo, "caid", p),
        algo_id=str(_int_id(algo, "aid", p)),
        algo_type=_text(algo, "at", p),
        order_type=_text(algo, "o", p),
        symbol=_text(algo, "s", p),
        side=_side(algo, "S", p),
        position_side=_text(algo, "ps", p),
        time_in_force=_text(algo, "f", p),
        quantity=_money(algo, "q", p, non_negative=True),
        algo_status=algo_status,
        actual_order_id=actual_order_id,
        average_price=_money_opt(algo, "ap", p, non_negative=True),
        executed_quantity=_money_opt(algo, "aq", p, non_negative=True),
        actual_order_type=_text_opt(algo, "act", p),
        trigger_price=_money(algo, "tp", p, non_negative=True),
        price=_money_opt(algo, "p", p, non_negative=True),
        working_type=_text_opt(algo, "wt", p),
        reduce_only=_flag_opt(algo, "R", p),
        close_position=_flag_opt(algo, "cp", p),
        price_protect=_flag_opt(algo, "pP", p),
        trigger_time_utc=(None if trigger_time_ms is None else _ms_to_utc(trigger_time_ms, "o.tt")),
        reject_reason=reject_reason,
        is_activated=_flag_opt(algo, "ia", p),
        stp_mode=_text_opt(algo, "V", p),
        price_match=_text_opt(algo, "pm", p),
        good_till_date_ms=_int_id_opt(algo, "gtd", p),
    )


def _build_balance_delta(row: Mapping[str, Any], path: str) -> BalanceDelta:
    return BalanceDelta(
        asset=_text(row, "a", path),
        wallet_balance=_money(row, "wb", path, non_negative=False),
        cross_wallet_balance=_money(row, "cw", path, non_negative=False),
        balance_change=_money(row, "bc", path, non_negative=False),
    )


def _build_position_delta(row: Mapping[str, Any], path: str) -> PositionDelta:
    return PositionDelta(
        symbol=_text(row, "s", path),
        position_amount=_money(row, "pa", path, non_negative=False),
        entry_price=_money(row, "ep", path, non_negative=True),
        breakeven_price=_money_opt(row, "bep", path, non_negative=True),
        accumulated_realized=_money_opt(row, "cr", path, non_negative=False),
        unrealized_pnl=_money(row, "up", path, non_negative=False),
        margin_type=_text(row, "mt", path),
        isolated_wallet=_money_opt(row, "iw", path, non_negative=False),
        position_side=_text(row, "ps", path),
    )


def _build_account_update(payload: Mapping[str, Any]) -> AccountUpdateEvent:
    event_time = _time(payload, "E", "")
    transaction_time = _time(payload, "T", "")
    account = _object(payload, "a", "")
    p = "a"

    reason = _text(account, "m", p)
    balances = tuple(_build_balance_delta(row, path) for path, row in _rows(account, "B", p))
    positions = tuple(_build_position_delta(row, path) for path, row in _rows(account, "P", p))
    funding_symbol = _text_opt(account, "S", p)
    if funding_symbol is not None and reason != FUNDING_FEE_REASON:
        raise _ParseError(
            StreamAnomalyKind.FIELD_VALIDATION,
            "a.S",
            "field a.S is accepted only for reason FUNDING_FEE",
        )
    return AccountUpdateEvent(
        event_time_utc=event_time,
        transaction_time_utc=transaction_time,
        reason=reason,
        balances=balances,
        positions=positions,
        funding_symbol=funding_symbol,
    )


def _build_listen_key_expired(payload: Mapping[str, Any]) -> ListenKeyExpiredEvent:
    # Only `E` is read: the listenKey is a credential and never leaves the payload.
    return ListenKeyExpiredEvent(event_time_utc=_time(payload, "E", ""))


def _build_account_config_update(payload: Mapping[str, Any]) -> AccountConfigUpdateEvent:
    event_time = _time(payload, "E", "")
    transaction_time = _time(payload, "T", "")
    leverage_part = _object_opt(payload, "ac", "")
    assets_part = _object_opt(payload, "ai", "")
    if leverage_part is None and assets_part is None:
        raise _ParseError(
            StreamAnomalyKind.MALFORMED_PAYLOAD,
            "ac",
            "required field ac or ai is missing",
        )
    symbol: str | None = None
    leverage: int | None = None
    multi_assets: bool | None = None
    if leverage_part is not None:
        symbol = _text(leverage_part, "s", "ac")
        leverage = _positive_int(leverage_part, "l", "ac")
    if assets_part is not None:
        multi_assets = _flag(assets_part, "j", "ai")
    return AccountConfigUpdateEvent(
        event_time_utc=event_time,
        transaction_time_utc=transaction_time,
        symbol=symbol,
        leverage=leverage,
        multi_assets=multi_assets,
    )


def _run_parser[EventT](
    build: Callable[[Mapping[str, Any]], EventT],
    payload: Mapping[str, Any],
    *,
    observed_at_utc: datetime,
    event_name: str,
) -> EventT | StreamAnomaly:
    """Run a strict builder; every failure becomes a `StreamAnomaly` (never coerced)."""
    _require_observed(observed_at_utc)
    try:
        return build(payload)
    except _ParseError as exc:
        return make_stream_anomaly(
            exc.kind,
            event_name=event_name,
            field=exc.field,
            detail=exc.detail,
            payload=payload,
            observed_at_utc=observed_at_utc,
        )
    except (TypeError, ValueError) as exc:
        # The dataclass rejected a combination the readers let through.
        return make_stream_anomaly(
            StreamAnomalyKind.FIELD_VALIDATION,
            event_name=event_name,
            field=None,
            detail=f"event validation failed ({type(exc).__name__})",
            payload=payload,
            observed_at_utc=observed_at_utc,
        )


def parse_order_trade_update(
    payload: Mapping[str, Any],
    *,
    observed_at_utc: datetime,
    event_name: str = ORDER_TRADE_UPDATE_EVENT,
) -> OrderUpdateEvent | StreamAnomaly:
    """Parse one ORDER_TRADE_UPDATE payload dict strictly; never coerce."""
    return _run_parser(
        _build_order_update, payload, observed_at_utc=observed_at_utc, event_name=event_name
    )


def parse_algo_update(
    payload: Mapping[str, Any],
    *,
    observed_at_utc: datetime,
    event_name: str = ALGO_UPDATE_EVENT,
) -> AlgoUpdateEvent | StreamAnomaly:
    """Parse one ALGO_UPDATE payload dict strictly; an unseen `X` is UNKNOWN_ALGO_STATUS."""
    return _run_parser(
        _build_algo_update, payload, observed_at_utc=observed_at_utc, event_name=event_name
    )


def parse_account_update(
    payload: Mapping[str, Any],
    *,
    observed_at_utc: datetime,
    event_name: str = ACCOUNT_UPDATE_EVENT,
) -> AccountUpdateEvent | StreamAnomaly:
    """Parse one ACCOUNT_UPDATE payload dict into balance and position deltas (D-08)."""
    return _run_parser(
        _build_account_update, payload, observed_at_utc=observed_at_utc, event_name=event_name
    )


def parse_listen_key_expired(
    payload: Mapping[str, Any],
    *,
    observed_at_utc: datetime,
    event_name: str = LISTEN_KEY_EXPIRED_EVENT,
) -> ListenKeyExpiredEvent | StreamAnomaly:
    """Parse one listenKeyExpired payload dict; the listenKey is never read."""
    return _run_parser(
        _build_listen_key_expired, payload, observed_at_utc=observed_at_utc, event_name=event_name
    )


def parse_account_config_update(
    payload: Mapping[str, Any],
    *,
    observed_at_utc: datetime,
    event_name: str = ACCOUNT_CONFIG_UPDATE_EVENT,
) -> AccountConfigUpdateEvent | StreamAnomaly:
    """Parse one ACCOUNT_CONFIG_UPDATE payload dict (leverage or Multi-Assets change)."""
    return _run_parser(
        _build_account_config_update,
        payload,
        observed_at_utc=observed_at_utc,
        event_name=event_name,
    )


# --------------------------------------------------------------------------- #
# Envelope and routing.
# --------------------------------------------------------------------------- #


def normalize_event_name(name: str) -> str:
    """Lower-case, underscores and hyphens removed: `ORDER_TRADE_UPDATE` == `OrderTradeUpdate`."""
    return name.lower().replace("_", "").replace("-", "")


def _unwrap_dict(candidate: dict[Any, Any]) -> tuple[str | None, dict[str, Any] | None]:
    if not all(isinstance(key, str) for key in candidate):
        return None, None
    wire_name = candidate.get("e")
    name = wire_name if isinstance(wire_name, str) and wire_name != "" else None
    return name, candidate


def unwrap_message(message: object) -> tuple[str | None, dict[str, Any] | None]:
    """(event name, payload dict) of what the SDK hands to a stream callback.

    Two shapes, read by duck typing with no SDK import: an object whose
    `actual_instance` is either a plain dict (the SDK's raw-dict fallback,
    research P4) or a model exposing `to_dict` (alias keys; the event name is
    the model class name, e.g. `OrderTradeUpdate`); or a plain dict whose
    `e` carries the wire event name. Anything else is `(None, None)`.
    """
    if isinstance(message, dict):
        return _unwrap_dict(message)
    instance = getattr(message, "actual_instance", None)
    if instance is None:
        return None, None
    if isinstance(instance, dict):
        return _unwrap_dict(instance)
    to_dict = getattr(instance, "to_dict", None)
    if not callable(to_dict):
        return None, None
    try:
        payload = to_dict()
    except Exception:  # an envelope that cannot be read is an anomaly, not a crash
        return None, None
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        return None, None
    return type(instance).__name__, payload


def parse_stream_message(message: object, *, observed_at_utc: datetime) -> StreamOutcome:
    """Unwrap, route on the normalized event name, parse strictly.

    Typed events: ORDER_TRADE_UPDATE, ALGO_UPDATE, ACCOUNT_UPDATE,
    listenKeyExpired, ACCOUNT_CONFIG_UPDATE. `IgnoredEvent`: TRADE_LITE,
    STRATEGY_UPDATE, GRID_UPDATE. Anomalies: MARGIN_CALL (UNHANDLED_EVENT),
    CONDITIONAL_ORDER_TRIGGER_REJECT (DEPRECATED_EVENT), any other name
    (UNKNOWN_EVENT_TYPE). Nothing is dropped.
    """
    _require_observed(observed_at_utc)
    event_name, payload = unwrap_message(message)
    if event_name is None or payload is None:
        return make_stream_anomaly(
            StreamAnomalyKind.UNRECOGNIZED_ENVELOPE,
            event_name=None,
            field=None,
            detail=f"message of type {type(message).__name__} carries no recognizable event",
            payload=payload,
            observed_at_utc=observed_at_utc,
        )
    route = normalize_event_name(event_name)
    wire_name = payload.get("e")
    if wire_name is not None and (
        not isinstance(wire_name, str) or normalize_event_name(wire_name) != route
    ):
        return make_stream_anomaly(
            StreamAnomalyKind.UNRECOGNIZED_ENVELOPE,
            event_name=event_name,
            field="e",
            detail="wire event name disagrees with the envelope event name",
            payload=payload,
            observed_at_utc=observed_at_utc,
        )
    parser = _TYPED_ROUTES.get(route)
    if parser is not None:
        return parser(payload, observed_at_utc=observed_at_utc, event_name=event_name)
    ignored_reason = _IGNORED_ROUTES.get(route)
    if ignored_reason is not None:
        return IgnoredEvent(event_name=event_name[:EVENT_NAME_MAX_CHARS], reason=ignored_reason)
    anomaly_route = _ANOMALY_ROUTES.get(route)
    kind, detail = (
        anomaly_route
        if anomaly_route is not None
        else (StreamAnomalyKind.UNKNOWN_EVENT_TYPE, "event type is not routed by this parser")
    )
    return make_stream_anomaly(
        kind,
        event_name=event_name,
        field=None,
        detail=detail,
        payload=payload,
        observed_at_utc=observed_at_utc,
    )


class _EventParser(Protocol):
    def __call__(
        self, payload: Mapping[str, Any], *, observed_at_utc: datetime, event_name: str
    ) -> StreamOutcome: ...


# Normalized event name -> parser / ignore reason / anomaly (kind, detail).
_TYPED_ROUTES: dict[str, _EventParser] = {
    "ordertradeupdate": parse_order_trade_update,
    "algoupdate": parse_algo_update,
    "accountupdate": parse_account_update,
    "listenkeyexpired": parse_listen_key_expired,
    "accountconfigupdate": parse_account_config_update,
}
_IGNORED_ROUTES: dict[str, str] = {
    "tradelite": "not used: fills come from ORDER_TRADE_UPDATE only (single fill source)",
    "strategyupdate": "not used: the project runs no Binance strategy orders",
    "gridupdate": "not used: the project runs no Binance grid strategy",
}
_ANOMALY_ROUTES: dict[str, tuple[StreamAnomalyKind, str]] = {
    "margincall": (
        StreamAnomalyKind.UNHANDLED_EVENT,
        "margin call event is recognized but not handled by this parser",
    ),
    "conditionalordertriggerreject": (
        StreamAnomalyKind.DEPRECATED_EVENT,
        "deprecated event type; conditional order rejections arrive in ALGO_UPDATE",
    ),
}


# --------------------------------------------------------------------------- #
# Bridge to the fill monitor.
# --------------------------------------------------------------------------- #


def to_fill_event(event: OrderUpdateEvent) -> FillEvent | None:
    """The `FillEvent` of a TRADE with a positive last filled quantity, else None.

    Keyed `(exchange_order_id, trade_id)` for the idempotent `fold_fills`;
    commission, commission asset, realized PnL and the maker flag are
    carried (G3-009).
    """
    if event.execution_type != _EXECUTION_TYPE_TRADE:
        return None
    quantity = event.last_filled_quantity
    price = event.last_filled_price
    trade_id = event.trade_id
    if quantity is None or price is None or trade_id is None or quantity <= 0:
        return None
    return FillEvent(
        order_id=event.exchange_order_id,
        exchange_trade_id=trade_id,
        symbol=event.symbol,
        side=event.side,
        position_side=event.position_side,
        fill_price=price,
        fill_quantity=quantity,
        fill_time_utc=event.trade_time_utc,
        commission=event.commission,
        commission_asset=event.commission_asset,
        realized_pnl=event.realized_profit,
        is_maker=event.is_maker,
    )


__all__ = [
    "ACCOUNT_BALANCE_WIRE_FIELDS",
    "ACCOUNT_CONFIG_UPDATE_EVENT",
    "ACCOUNT_POSITION_WIRE_FIELDS",
    "ACCOUNT_UPDATE_EVENT",
    "ACCOUNT_UPDATE_WIRE_FIELDS",
    "ALGO_UPDATE_EVENT",
    "ALGO_UPDATE_WIRE_FIELDS",
    "DETAIL_MAX_CHARS",
    "EVENT_NAME_MAX_CHARS",
    "FIELD_PATH_MAX_CHARS",
    "FORCED_CLOSE_CLIENT_ID_PREFIXES",
    "FUNDING_FEE_REASON",
    "IGNORED_REASON_MAX_CHARS",
    "LISTEN_KEY_EXPIRED_EVENT",
    "ORDER_EXECUTION_TYPE_VOCABULARY",
    "ORDER_STATUS_VOCABULARY",
    "ORDER_TRADE_UPDATE_EVENT",
    "ORDER_UPDATE_WIRE_FIELDS",
    "REJECT_REASON_MAX_CHARS",
    "AccountConfigUpdateEvent",
    "AccountUpdateEvent",
    "AlgoUpdateEvent",
    "BalanceDelta",
    "IgnoredEvent",
    "ListenKeyExpiredEvent",
    "OrderUpdateEvent",
    "PositionDelta",
    "StreamAnomaly",
    "StreamAnomalyKind",
    "StreamOutcome",
    "canonical_payload_sha256",
    "make_stream_anomaly",
    "normalize_event_name",
    "parse_account_config_update",
    "parse_account_update",
    "parse_algo_update",
    "parse_listen_key_expired",
    "parse_order_trade_update",
    "parse_stream_message",
    "to_fill_event",
    "unwrap_message",
]
