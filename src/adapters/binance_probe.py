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
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
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
from src.adapters.binance_ratelimit_gate import (
    IP_BAN_418,
    RATE_LIMIT_PAUSE_429,
    RestRateLimitGate,
)
from src.adapters.binance_usdm import _decimal_to_wire
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
    }
)

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
# Free-text response fields: passed through the shared redactor and capped like an error
# message (threat T-18-34).
_FREE_TEXT_FIELDS: frozenset[str] = frozenset({"msg"})


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
    """The evidence text of one response field: `str()`, booleans as `true` / `false`."""
    if isinstance(value, bool):
        return "true" if value else "false"
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
    gate, whose policy must equal `policy.rate_limit`.
    """

    def __init__(
        self,
        sdk_client: Any,
        *,
        policy: SignedCallPolicy,
        rest_gate: RestRateLimitGate,
    ) -> None:
        if not isinstance(policy, SignedCallPolicy):
            raise TypeError("policy must be a SignedCallPolicy")
        if not isinstance(rest_gate, RestRateLimitGate):
            raise TypeError("rest_gate must be the process-wide RestRateLimitGate")
        if rest_gate.policy != policy.rate_limit:
            raise ValueError("rest_gate.policy must equal policy.rate_limit")
        self._sdk = sdk_client
        self._policy = policy
        self._rest_gate = rest_gate
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


__all__ = [
    "CONDITIONAL_ORDER_TYPES",
    "ERROR_MESSAGE_MAX_CHARS",
    "SDK_REST_METHODS",
    "BinanceProbeAdapter",
    "ErrorObservation",
    "ProbeBanned",
    "ProbeObservation",
]
