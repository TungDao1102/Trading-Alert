"""Test-only fault injection for the Demo campaign (plan 25-02, D-05, D-08).

TEST_ONLY: nothing under `src` imports this file (`git grep fault_edge -- src` is empty). It
exists because Demo cannot produce a stop rejection, a lost ACK, a 418/429, a DB outage or a stale
feed on demand. The trigger is injected at a seam production already has, so the composed process
keeps ONE code path with live and its REACTION to the failure stays real (D-08):

* `FaultEdge` and `FaultPublic` go through `build_wiring(exchange_edge=...)`. The edge may replace
  the signed adapter and the public reader, never the REST gate; `FaultEdge.install` replaces
  exactly those two fields and forwards every other name (the gate and drift-guard attributes
  that `check_wiring` reads included) to the object it wraps.
* `SdkFaults` goes through `build_wiring(sdk_factory=...)`: the SDK client's `rest_api` raises
  BEFORE the call is delegated, so the real adapter's `_sdk_call` classifies the error and the real
  REST gate records a 418 or 429. A real 418 is never provoked (owner decision 2026-10-22): the
  error is raised by this proxy and nothing is sent.
* `StoreFaults` goes through `build_wiring(stores=...)`: a store method raises `StoreUnavailable`.

Every injection is recorded (method, mode, sequence number). Labelling a scenario step
DEMO_FAULT_INJECTED, and never as exchange behaviour, is the scenario's job (plan 25-08); this
module only keeps the evidence that it was an injection. No wall clock is read and no sleep is
awaited here; prices stay `Decimal` and times stay UTC-aware.
"""

from __future__ import annotations

import asyncio
import dataclasses
import functools
import inspect
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

MODE_RAISE_BEFORE_SEND = "raise_before_send"
MODE_MUTATE_PAYLOAD = "mutate_payload"
MODE_DROP_RESPONSE = "drop_response_after_send"
MODE_HOLD = "hold"
MODE_OVERRIDE = "override"
MODE_STALE_MARK = "stale_mark"
MODE_MOVED_MARK = "moved_mark"
MODE_SDK_ERROR = "sdk_error"
MODE_STORE_UNAVAILABLE = "store_unavailable"


@dataclass(frozen=True)
class Injection:
    """One applied fault: which method, by which mode, and its 1-based order among injections."""

    method: str
    mode: str
    sequence: int


@dataclass
class _Fault:
    mode: str
    times: int | None  # None: until `clear`
    exc: BaseException | None = None
    fn: Callable[..., Any] | None = None
    value: Any = None  # a mark's age (timedelta) or price (Decimal)


class _Ledger:
    """The recorded calls and injections shared by one fault object (and its public wrapper)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.injections: list[Injection] = []

    def start(self, method: str, kwargs: Mapping[str, Any]) -> dict[str, Any]:
        record: dict[str, Any] = {
            "method": method,
            "kwargs": dict(kwargs),
            "injected": False,
            "mode": None,
            "sequence": None,
        }
        self.calls.append(record)
        return record

    def mark(self, record: dict[str, Any], mode: str) -> None:
        injection = Injection(method=record["method"], mode=mode, sequence=len(self.injections) + 1)
        self.injections.append(injection)
        record["injected"] = True
        record["mode"] = mode
        record["sequence"] = injection.sequence

    def calls_to(self, method: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["method"] == method]


def _take(queues: dict[str, deque[_Fault]], key: str) -> _Fault | None:
    """The head fault of `key`, consumed by one use; faults apply in registration order."""
    queue = queues.get(key)
    if not queue:
        return None
    fault = queue[0]
    if fault.times is not None:
        fault.times -= 1
        if fault.times <= 0:
            queue.popleft()
    return fault


class FaultEdge:
    """The signed adapter of the composed process with faults injected by method name.

    Build one, hand it to `make_composed_rig(faults=...)` (or call `install(bundle)` yourself), then
    arm faults. A call to a coroutine method is recorded; a pending fault for that method is applied
    before (or around) delegating to the bound inner object. Plain attributes and synchronous
    methods (`_rest_gate`, `_drift_guard`, `error_facts`, ...) pass through unchanged.
    """

    def __init__(self) -> None:
        self._inner: Any = None
        self._ledger = _Ledger()
        self._faults: dict[str, deque[_Fault]] = {}
        self._hold_pending: dict[str, deque[asyncio.Event]] = {}
        self._hold_waiting: dict[str, deque[asyncio.Event]] = {}
        self._wrappers: dict[str, Callable[..., Any]] = {}
        self.public = FaultPublic(self._ledger)

    # ---- wiring ---------------------------------------------------------------------------- #

    def bind(self, inner: Any) -> FaultEdge:
        """Bind the adapter this edge wraps (a restart binds the next process's adapter)."""
        self._inner = inner
        self._wrappers.clear()
        return self

    def install(self, bundle: Any) -> Any:
        """The `exchange_edge` seam: replace adapter and public reader, never the gate."""
        self.bind(bundle.adapter)
        self.public.bind(bundle.public)
        return dataclasses.replace(bundle, adapter=self, public=self.public)

    @property
    def inner(self) -> Any:
        return self._inner

    # ---- the record ------------------------------------------------------------------------ #

    @property
    def injections(self) -> list[Injection]:
        return self._ledger.injections

    def calls_to(self, method: str) -> list[dict[str, Any]]:
        """Every call of `method` that went through this edge, injected or not."""
        return self._ledger.calls_to(method)

    # ---- arming ---------------------------------------------------------------------------- #

    def raise_before_send(self, method: str, exc: BaseException, *, times: int = 1) -> None:
        """The next `times` calls of `method` raise `exc`; the inner object is never reached."""
        self._arm(method, _Fault(MODE_RAISE_BEFORE_SEND, times, exc=exc))

    def mutate_payload(
        self,
        method: str,
        fn: Callable[[dict[str, Any]], dict[str, Any]],
        times: int = 1,
    ) -> None:
        """The inner call receives `fn(kwargs)`; the record keeps `kwargs` and `mutated_kwargs`."""
        self._arm(method, _Fault(MODE_MUTATE_PAYLOAD, times, fn=fn))

    def drop_response_after_send(self, method: str, exc: BaseException, times: int = 1) -> None:
        """A lost ACK: the inner call runs (its state changes), then `exc` is raised."""
        self._arm(method, _Fault(MODE_DROP_RESPONSE, times, exc=exc))

    def override(
        self,
        method: str,
        coro_fn: Callable[..., Awaitable[Any]],
        times: int | None = None,
    ) -> None:
        """`await coro_fn(**kwargs)` is the answer; the inner object is not called.

        `times=None` keeps the override until `clear(method)` (for example scripted day-risk rows).
        """
        self._arm(method, _Fault(MODE_OVERRIDE, times, fn=coro_fn))

    def hold(self, method: str) -> None:
        """The next call of `method` waits (recorded, inner not called) until `release(method)`."""
        self._hold_pending.setdefault(method, deque()).append(asyncio.Event())

    def release(self, method: str) -> None:
        """Let the oldest held call continue, or pre-release the next hold."""
        waiting = [e for e in self._hold_waiting.get(method, ()) if not e.is_set()]
        pending = [e for e in self._hold_pending.get(method, ()) if not e.is_set()]
        if waiting:
            waiting[0].set()
        elif pending:
            pending[0].set()
        else:
            raise ValueError(f"nothing is held for {method}")

    def held(self, method: str) -> bool:
        """True while a call of `method` waits for its release."""
        return any(not e.is_set() for e in self._hold_waiting.get(method, ()))

    def clear(self, method: str) -> None:
        """Drop every armed fault and unconsumed hold of `method` (held calls keep waiting)."""
        self._faults.pop(method, None)
        self._hold_pending.pop(method, None)

    def stale_mark(self, symbol: str, age: timedelta, *, times: int | None = None) -> None:
        """Delegates to `FaultPublic.stale_mark` (the reading's own time moves back by `age`)."""
        self.public.stale_mark(symbol, age, times=times)

    def moved_mark(self, symbol: str, price: Decimal, *, times: int | None = None) -> None:
        """Delegates to `FaultPublic.moved_mark` (the reading carries the given price)."""
        self.public.moved_mark(symbol, price, times=times)

    def _arm(self, method: str, fault: _Fault) -> None:
        self._faults.setdefault(method, deque()).append(fault)

    # ---- forwarding ------------------------------------------------------------------------ #

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") or name == "_inner":
            raise AttributeError(name)
        if self._inner is None:
            raise AttributeError(name)
        cached = self._wrappers.get(name)
        if cached is not None:
            return cached
        attr = getattr(self._inner, name)
        if not inspect.iscoroutinefunction(attr):
            return attr
        wrapper = self._wrap(name, attr)
        self._wrappers[name] = wrapper
        return wrapper

    def _wrap(self, name: str, attr: Callable[..., Awaitable[Any]]) -> Callable[..., Any]:
        @functools.wraps(attr)
        async def call(*args: Any, **kwargs: Any) -> Any:
            record = self._ledger.start(name, kwargs)
            await self._pass_hold(name, record)
            fault = _take(self._faults, name)
            target = getattr(self._inner, name)
            if fault is None:
                return await target(*args, **kwargs)
            self._ledger.mark(record, fault.mode)
            if fault.mode == MODE_RAISE_BEFORE_SEND:
                assert fault.exc is not None
                raise fault.exc
            if fault.mode == MODE_MUTATE_PAYLOAD:
                assert fault.fn is not None
                mutated = fault.fn(dict(kwargs))
                record["mutated_kwargs"] = dict(mutated)
                return await target(*args, **mutated)
            if fault.mode == MODE_DROP_RESPONSE:
                assert fault.exc is not None
                await target(*args, **kwargs)
                raise fault.exc
            if fault.mode == MODE_OVERRIDE:
                assert fault.fn is not None
                return await fault.fn(**kwargs)
            raise AssertionError(f"unknown fault mode {fault.mode!r}")  # pragma: no cover

        return call

    async def _pass_hold(self, name: str, record: dict[str, Any]) -> None:
        pending = self._hold_pending.get(name)
        if not pending:
            return
        event = pending.popleft()
        waiting = self._hold_waiting.setdefault(name, deque())
        waiting.append(event)
        self._ledger.mark(record, MODE_HOLD)
        try:
            await event.wait()
        finally:
            waiting.remove(event)


class FaultPublic:
    """The public market-data reader of the composed process, with stale and moved marks.

    `stale_mark` and `moved_mark` ARM a transformation of `mark_price(symbol)` for that symbol
    only; every other symbol and every other method passes through to the bound reader. The age
    is applied to the reading's own `exchange_time_utc` (no clock is read), the price stays
    `Decimal`.
    """

    def __init__(self, ledger: _Ledger | None = None) -> None:
        self._inner: Any = None
        self._ledger = ledger if ledger is not None else _Ledger()
        self._marks: dict[str, deque[_Fault]] = {}

    def bind(self, inner: Any) -> FaultPublic:
        self._inner = inner
        return self

    def stale_mark(self, symbol: str, age: timedelta, *, times: int | None = None) -> None:
        """`mark_price(symbol)` answers a reading observed `age` earlier (None: until cleared)."""
        if not isinstance(age, timedelta) or age < timedelta(0):
            raise ValueError("the stale mark age must be a non-negative timedelta")
        self._marks.setdefault(symbol, deque()).append(_Fault(MODE_STALE_MARK, times, value=age))

    def moved_mark(self, symbol: str, price: Decimal, *, times: int | None = None) -> None:
        """`mark_price(symbol)` answers a reading at `price` (None: until cleared)."""
        if not isinstance(price, Decimal) or not price.is_finite() or price <= 0:
            raise TypeError("the moved mark price must be a positive finite Decimal")
        self._marks.setdefault(symbol, deque()).append(_Fault(MODE_MOVED_MARK, times, value=price))

    def clear_marks(self, symbol: str | None = None) -> None:
        """Drop the armed marks of `symbol` (all symbols when None)."""
        if symbol is None:
            self._marks.clear()
        else:
            self._marks.pop(symbol, None)

    async def mark_price(self, symbol: str) -> Any:
        record = self._ledger.start("mark_price", {"symbol": symbol})
        reading = await self._inner.mark_price(symbol)
        fault = _take(self._marks, symbol)
        if fault is None:
            return reading
        self._ledger.mark(record, fault.mode)
        if fault.mode == MODE_STALE_MARK:
            return dataclasses.replace(
                reading, exchange_time_utc=reading.exchange_time_utc - fault.value
            )
        return dataclasses.replace(reading, mark_price=fault.value)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") or name in ("_inner", "_ledger", "_marks"):
            raise AttributeError(name)
        if self._inner is None:
            raise AttributeError(name)
        return getattr(self._inner, name)


__all__ = [
    "MODE_DROP_RESPONSE",
    "MODE_HOLD",
    "MODE_MOVED_MARK",
    "MODE_MUTATE_PAYLOAD",
    "MODE_OVERRIDE",
    "MODE_RAISE_BEFORE_SEND",
    "MODE_SDK_ERROR",
    "MODE_STALE_MARK",
    "MODE_STORE_UNAVAILABLE",
    "FaultEdge",
    "FaultPublic",
    "Injection",
]
