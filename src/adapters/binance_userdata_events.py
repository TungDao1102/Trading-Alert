"""Typed, SDK-free events of the Binance USD-M user-data stream (Phase 18, plan 18-03).

The stream is a hint plus evidence; REST stays the authority (D-05). This
module turns one message handed to an SDK stream callback into either a
frozen event dataclass or a `StreamAnomaly`. It never coerces: a field of the
wrong wire type, a missing required field or an unparseable value becomes an
anomaly with a deterministic payload hash, and nothing is defaulted to zero
(D-05, research P4 and P17).

SDK-free by construction: the only imports are the standard library,
`src.execution.fill_monitor.FillEvent` and (from Task 3 of the plan)
`src.domain.algo_status`. The SDK message is read by duck typing
(`actual_instance`, `to_dict`) in `unwrap_message`; no SDK, requests,
aiohttp, SQLAlchemy, Pydantic or Polars import appears here. No wall clock
is read: `observed_at_utc` is always an argument.

Wire field names and Python types follow the installed SDK models
(`binance_sdk_derivatives_trading_usds_futures` 17.4.0,
`websocket_streams/models/order_trade_update.py` and
`order_trade_update_o.py`, read as files): strings carry money, quantities
and prices; ints carry ids and millisecond times; bools carry flags. The
Binance event pages themselves are UNVERIFIED for Phase 18 (docs/SOURCES.md,
"Facts read for Phase 18").
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

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
ORDER_TRADE_UPDATE_EVENT = "ORDER_TRADE_UPDATE"


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


StreamOutcome = OrderUpdateEvent | StreamAnomaly


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


def _object(obj: Mapping[str, Any], key: str, prefix: str) -> Mapping[str, Any]:
    value = _required(obj, key, prefix)
    if not isinstance(value, Mapping) or not all(isinstance(k, str) for k in value):
        raise _invalid(_path(prefix, key), "an object", value)
    return value


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


def _build_order_update(payload: Mapping[str, Any]) -> OrderUpdateEvent:
    event_time = _time(payload, "E", "")
    transaction_time = _time(payload, "T", "")
    order = _object(payload, "o", "")
    p = "o"

    side = _text(order, "S", p)
    if side not in _SIDES:
        raise _ParseError(StreamAnomalyKind.FIELD_VALIDATION, "o.S", "field o.S is not BUY or SELL")
    execution_type = _text(order, "x", p)
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
        client_order_id=_text(order, "c", p),
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
        order_status=_text(order, "X", p),
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


def parse_order_trade_update(
    payload: Mapping[str, Any],
    *,
    observed_at_utc: datetime,
    event_name: str = ORDER_TRADE_UPDATE_EVENT,
) -> OrderUpdateEvent | StreamAnomaly:
    """Parse one ORDER_TRADE_UPDATE payload dict strictly; never coerce."""
    _require_observed(observed_at_utc)
    try:
        return _build_order_update(payload)
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

    This revision routes ORDER_TRADE_UPDATE only; every other event name is
    an UNKNOWN_EVENT_TYPE anomaly until the remaining parsers are added
    (plan 18-03 Task 3, after the design review of the event types).
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
    if route == "ordertradeupdate":
        return parse_order_trade_update(
            payload, observed_at_utc=observed_at_utc, event_name=event_name
        )
    return make_stream_anomaly(
        StreamAnomalyKind.UNKNOWN_EVENT_TYPE,
        event_name=event_name,
        field=None,
        detail="event type is not routed by this parser",
        payload=payload,
        observed_at_utc=observed_at_utc,
    )


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
    "DETAIL_MAX_CHARS",
    "EVENT_NAME_MAX_CHARS",
    "FIELD_PATH_MAX_CHARS",
    "ORDER_TRADE_UPDATE_EVENT",
    "OrderUpdateEvent",
    "StreamAnomaly",
    "StreamAnomalyKind",
    "StreamOutcome",
    "canonical_payload_sha256",
    "make_stream_anomaly",
    "normalize_event_name",
    "parse_order_trade_update",
    "parse_stream_message",
    "to_fill_event",
    "unwrap_message",
]
