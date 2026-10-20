"""Stateful Binance-semantics fake adapter (Phase 17, D-25, F-603; corrected in Phase 18-21).

Models the one exchange rule the audit finding F-126 turns on: Binance's
`newClientOrderId` / `clientAlgoId` are "a unique id among OPEN orders"
(New Order / New Algo Order docs). A FILLED or CANCELED order frees its
client id, so the exchange itself can NOT stop a replayed APPROVE from
placing a second entry once the first one is no longer open. The durable
local intent row is the only line of defense; this fake lets a test prove
that by actually accepting a reused id after `fill()` / `cancel()`.

Errors are SDK-shaped (plan 18-21): a duplicate id raises the SDK's
`BadRequestError` with the int code -4116, the same class and code the real
adapter's error path (`error_facts_from_exception`, then `classify`) sees.

Evidence status of the three assumptions. The source is the Demo probe check file
`.planning/phases/18-user-data-stream-error-taxonomy/evidence/18-probe-check.txt`
(second run 2026-10-16T17:36:12Z; lines 66 to 69, with the first run's lines 33 to 36
and 50 to 53). It is Demo evidence, not mainnet:

1. A client id is unique among OPEN orders, so a duplicate while the first is
   open is rejected: agrees with the probe for clientAlgoId (-4116) ("1 a client
   id is unique among OPEN orders: agrees with the probe for clientAlgoId (-4116
   while the first is open); not observed for a normal order", check file line
   67). For a normal order this is NOT validated against Demo: not observed.
2. A CANCELED order frees its client id (a reused id is accepted): agrees with
   the probe, normal and algo order (check file lines 34, 35 and 68).
3. A FILLED order frees its client id: agrees with the probe, normal order (the
   reused id was accepted after FILLED; check file lines 64 and 69). The first
   probe run could not observe it (the entry was rejected with -4016 before any
   fill, line 53); the second run did.

The duplicate clientAlgoId code is -4116 with the text "ClientOrderId is
duplicated." (check file line 33); before the probe the fake raised an
undocumented-code error (research A8). That is a correction, not a confirmation.

Retention of the order-by-client lookup follows the documented Query Order
rule: a CANCELED/EXPIRED order with no fills older than 3 days is no longer
found (`HISTORY_RETENTION`), so "not found" is a definitive absence only
for young intents. NOT validated against Demo: it is a documentation rule the
probe does not test (check file line 54).

The kwargs of every call are bound against the REAL `BinanceUsdmAdapter`
method signature (09-REVIEW WR-12) so this fake can never drift from the
production surface.

Phase 19 additions (plan 19-10). Every rule below carries a provenance label; the fake is an
offline test double, NOT evidence of mainnet behavior, and a green test against it proves
only that the code under test agrees with the label, not that the exchange does:

* [DEMO] A `closePosition` STOP_MARKET placed while the position is flat is rejected with
  -4509 ("Time in Force (TIF) GTE can only be used with open positions. ..."; probe check
  file line 38). An explicit-quantity reduce-only stop placed while flat is ACCEPTED on Demo
  (check file line 37), so the fake accepts it too. The -4509 rule is opt-in through
  `enforce_flat_stop_rejection=True` because the pre-Phase-19 manager places its
  closePosition stop right after the entry ack (no fill yet) and the legacy tests that use
  this fake would fail; Phase 19 flow tests construct the fake with the flag.
* [DOC] `closePosition` cannot be combined with a quantity or `reduceOnly` (New Algo Order,
  -4137/-4138); the real adapter enforces it, the fake only binds the signature.
* [ASSUMED, research A5] Partial fills: Demo may never produce one. The fake lets a test
  script `fill(client_id, quantity=...)`, which keeps the order open as PARTIALLY_FILLED
  with `executed_quantity` and a volume-weighted `average_price` on the probe.
* [ASSUMED, research A4/A8] `place_market_close` reduces the position. A close on a flat
  position raises -2022 and a close above the position raises -2024. The repo taxonomy has
  both rows, but the 2026-10-19 doc pass found -2022 documented only as a conflict with open
  orders and -2024 as "Position is not sufficient"; which code a flat-position reduce-only
  MARKET really gets is UNPROVEN. The fake's choice of -2022 for the flat case is a TEST
  CONVENTION, and callers must treat -2022 and -2024 identically (requery the position).
  The fake fills a MARKET close at once and in full; the real response is normally an
  acknowledgment, so production code must confirm the closed quantity by a position query
  (`market_close_ack_only=True` makes the fake answer like an acknowledgment).
* [ASSUMED] `trigger_stop` consumes the position of a closePosition stop in full and leaves
  the algo FINISHED; the position book is one signed Decimal per symbol (One-way only, Hedge
  position books are not modeled).
* Mark price, lot filters, open-order and algo snapshots are served from state the test
  sets (`set_mark_price`, `set_lot_filters`); an unset value raises, never defaults.
* Scripted completion gates (`hold`/`release`, `fail_next`, `reject_next_algo`) make every
  D-12 stop/cancel race a deterministic test; none of them sleeps. A D-12 branch test
  combines them: hold the cancel, run stop and cancel concurrently, assert the stop
  completed first through `completed`, release, and drive a late `fill` or `trigger_stop`
  to reach the B4 branch (a fill after the stop triggered).
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import itertools
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from binance_sdk_derivatives_trading_usds_futures import BadRequestError

# Binance Query Order: a canceled/expired order with no filled trade older
# than 3 days is not returned (docs, Query Order "orders not found" rules).
HISTORY_RETENTION = timedelta(days=3)

# Binance -4116 (duplicated client order id): documented for a normal order, observed on Demo for
# a duplicate clientAlgoId (probe check file line 33), with the Demo text below.
DUPLICATE_CLIENT_ID_CODE = -4116
DUPLICATE_ORDER_MESSAGE = "clientOrderId is duplicated"  # the page text; not observed on Demo
DUPLICATE_ALGO_MESSAGE = "ClientOrderId is duplicated."  # the Demo text (check file line 33)

# Binance -4509: closePosition stop with no open position (Demo-observed only, probe line 38).
FLAT_CLOSE_POSITION_CODE = -4509
FLAT_CLOSE_POSITION_MESSAGE = (
    "Time in Force (TIF) GTE can only be used with open positions. "
    "Please ensure that positions are available."
)
# TEST CONVENTION (research A4/A8): the code a reduce-only MARKET close gets on a flat position
# is unproven; -2022 and -2024 must be handled identically by callers.
REDUCE_ONLY_REJECT_CODE = -2022
POSITION_NOT_SUFFICIENT_CODE = -2024

STATUS_NEW = "NEW"
STATUS_PARTIALLY_FILLED = "PARTIALLY_FILLED"
STATUS_FILLED = "FILLED"
STATUS_CANCELED = "CANCELED"
STATUS_FINISHED = "FINISHED"

ZERO = Decimal("0")


def _dec(value: Any) -> Decimal | None:
    """Decimal of a quantity or price a caller passed (legacy tests pass strings); None stays."""
    return None if value is None else Decimal(str(value))


@dataclass
class ExchangeOrderRecord:
    """One order (normal or algo) the fake exchange has seen."""

    client_id: str
    symbol: str
    status: str
    created_at_utc: datetime
    exchange_id: str
    had_fill: bool = False
    # Moves on every state change (fill, cancel); None until the first one.
    updated_at_utc: datetime | None = None
    # Phase 19 trailing fields (safe defaults so every older construction keeps working).
    quantity: Decimal | None = None
    executed_quantity: Decimal = ZERO
    average_price: Decimal | None = None
    side: str = ""
    position_side: str = "BOTH"
    order_type: str = "LIMIT"
    time_in_force: str = "GTC"
    price: Decimal | None = None
    trigger_price: Decimal | None = None
    close_position: bool = False
    reduce_only: bool = False
    working_type: str | None = None
    algo_type: str = ""

    @property
    def update_time_utc(self) -> datetime:
        """The `updateTime` an exchange query reports: the last change, else the creation."""
        return self.updated_at_utc if self.updated_at_utc is not None else self.created_at_utc


def _exchange_call(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Wrap an adapter method: bind the kwargs to the REAL signature, record the call, pass the
    scripted gates (`hold`, `fail_next`), run the body, then log the completion.

    The call is recorded before any gate, so a held or failing call is visible in `calls`; only
    a call that returns (does not raise) is appended to `completed`.
    """

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        async def wrapper(self: BinanceSemanticsFakeAdapter, **kwargs: Any) -> Any:
            self._bind_real(name, kwargs)
            self._record_call(name, kwargs)
            await self._pass_gates(name)
            result = await fn(self, **kwargs)
            self.completed.append(name)
            return result

        return wrapper

    return decorate


class BinanceSemanticsFakeAdapter:
    """In-memory adapter implementing the `ExecutionAdapter` methods and the Phase 19 reads."""

    def __init__(
        self,
        *,
        position_mode: str = "ONE_WAY",
        now_utc: datetime | None = None,
        enforce_flat_stop_rejection: bool = False,
    ) -> None:
        self.enforce_flat_stop_rejection = enforce_flat_stop_rejection
        self.calls: list[dict[str, Any]] = []
        # Injected, settable clock (tests move it to exercise the retention rule).
        self.now_utc: datetime = now_utc or datetime(2026, 9, 19, 10, 30, tzinfo=UTC)
        self.position_mode = position_mode
        self.open_orders: dict[str, ExchangeOrderRecord] = {}
        self.history: dict[str, ExchangeOrderRecord] = {}
        self.open_algos: dict[str, ExchangeOrderRecord] = {}
        self.algo_history: dict[str, ExchangeOrderRecord] = {}
        # Runs before the duplicate check on every place_entry (the tracer
        # test reads the write-ahead intent row from a second connection).
        self.on_place_entry: Callable[[dict[str, Any]], None] | None = None
        self._ids = itertools.count(1)
        self._trade_ids = itertools.count(1)
        # Signed position per symbol (One-way) and its volume-weighted entry price.
        self.positions: dict[str, Decimal] = {}
        self._entry_prices: dict[str, Decimal] = {}
        # One FillEvent per scripted `fill` (what the user-data stream would deliver).
        self.fill_events: list[Any] = []
        # State the test sets; an unset value raises, it is never defaulted.
        self._mark_prices: dict[str, Any] = {}
        self._mark_price_error: BaseException | None = None
        self._lot_filters: dict[str, Any] = {}
        # True: a MARKET close answers like an acknowledgment (NEW, executed unknown).
        self.market_close_ack_only = False
        # Scripted completion gates. `completed` lists the methods that returned, in order.
        self.completed: list[str] = []
        self._hold_pending: dict[str, deque[asyncio.Event]] = {}
        self._hold_waiting: dict[str, deque[asyncio.Event]] = {}
        self._failures: dict[str, deque[BaseException]] = {}

    # ------------------------------------------------------------------ #
    # Contract guard (same check as the existing FakeExecutionAdapter).
    # ------------------------------------------------------------------ #

    @staticmethod
    def _bind_real(method_name: str, kwargs: dict[str, Any]) -> None:
        from src.adapters.binance_usdm import BinanceUsdmAdapter

        inspect.signature(getattr(BinanceUsdmAdapter, method_name)).bind(None, **kwargs)

    def _record_call(self, method: str, kwargs: dict[str, Any]) -> None:
        self.calls.append({"method": method, "kwargs": dict(kwargs)})

    def calls_to(self, method: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["method"] == method]

    # ------------------------------------------------------------------ #
    # Test-side state transitions (what the exchange does on its own).
    # ------------------------------------------------------------------ #

    def fill(
        self,
        client_id: str,
        quantity: Decimal | None = None,
        price: Decimal | None = None,
    ) -> None:
        """The order fills, fully (`quantity=None`, the old behavior) or partially.

        A partial fill keeps the order open as PARTIALLY_FILLED (its client id stays taken); the
        final fill moves it to the history as FILLED and frees the id. Every fill moves the
        position and appends a `FillEvent` with a trade id of its own to `fill_events`.
        """
        from src.execution.fill_monitor import FillEvent

        record = self.open_orders[client_id]
        assert record.quantity is not None, "fill() needs an order placed through place_entry"
        remaining = record.quantity - record.executed_quantity
        fill_quantity = remaining if quantity is None else quantity
        if fill_quantity <= ZERO:
            raise ValueError("fill quantity must be > 0")
        if fill_quantity > remaining:
            raise ValueError(
                f"fill quantity {fill_quantity} exceeds the remaining quantity {remaining}"
            )
        fill_price = price if price is not None else record.price
        assert fill_price is not None, "fill() needs a price (the order has none)"
        previous_value = record.executed_quantity * (record.average_price or ZERO)
        record.executed_quantity += fill_quantity
        record.average_price = (previous_value + fill_quantity * fill_price) / (
            record.executed_quantity
        )
        record.had_fill = True
        record.updated_at_utc = self.now_utc
        if record.executed_quantity == record.quantity:
            self.open_orders.pop(client_id)
            record.status = STATUS_FILLED
            self.history[client_id] = record
        else:
            record.status = STATUS_PARTIALLY_FILLED
        signed = fill_quantity if record.side == "BUY" else -fill_quantity
        self._apply_position_delta(record.symbol, signed, fill_price)
        self.fill_events.append(
            FillEvent(
                order_id=record.exchange_id,
                exchange_trade_id=f"fake-trade-{next(self._trade_ids)}",
                symbol=record.symbol,
                side=record.side,
                position_side=record.position_side,
                fill_price=fill_price,
                fill_quantity=fill_quantity,
                fill_time_utc=self.now_utc,
            )
        )

    def _apply_position_delta(self, symbol: str, delta: Decimal, price: Decimal) -> None:
        """Move the signed position; the entry price is volume-weighted while it grows."""
        old = self.positions.get(symbol, ZERO)
        new = old + delta
        old_price = self._entry_prices.get(symbol, ZERO)
        if new == ZERO:
            entry = ZERO
        elif old == ZERO or (old > ZERO) == (delta > ZERO):
            entry = (abs(old) * old_price + abs(delta) * price) / abs(new)
        elif (new > ZERO) == (old > ZERO):
            entry = old_price  # reduced, not flipped
        else:
            entry = price  # flipped through zero: the new side opens at this price
        self.positions[symbol] = new
        self._entry_prices[symbol] = entry

    def cancel(self, client_id: str) -> None:
        """The order is canceled: it leaves the open book and frees its client id."""
        record = self.open_orders.pop(client_id)
        record.status = STATUS_CANCELED
        record.updated_at_utc = self.now_utc
        self.history[client_id] = record

    def cancel_algo(self, client_algo_id: str) -> None:
        """An algo order is canceled: it leaves the open book and frees its id."""
        record = self.open_algos.pop(client_algo_id)
        record.status = STATUS_CANCELED
        record.updated_at_utc = self.now_utc
        self.algo_history[client_algo_id] = record

    # ------------------------------------------------------------------ #
    # Scripted completion gates (D-12 races): deterministic, no sleeping.
    # ------------------------------------------------------------------ #

    def hold(self, method_name: str) -> None:
        """The next call of `method_name` records itself, then waits until `release`.

        The body of the call (the state change) runs only after the release, so a test decides
        which of two concurrent calls the exchange completes first. A hold applies to one call.
        """
        self._hold_pending.setdefault(method_name, deque()).append(asyncio.Event())

    def release(self, method_name: str) -> None:
        """Let the oldest held call of `method_name` continue (or pre-release the next hold)."""
        waiting = [e for e in self._hold_waiting.get(method_name, ()) if not e.is_set()]
        pending = [e for e in self._hold_pending.get(method_name, ()) if not e.is_set()]
        if waiting:
            waiting[0].set()
        elif pending:
            pending[0].set()
        else:
            raise ValueError(f"nothing is held for {method_name}")

    def held(self) -> list[str]:
        """The methods with a call that is waiting for its release, one entry per waiting call."""
        return [
            name
            for name, events in self._hold_waiting.items()
            for event in events
            if not event.is_set()
        ]

    def fail_next(self, method_name: str, exc: BaseException) -> None:
        """The next call of `method_name` raises `exc` (after it is recorded), once.

        Several scripted failures for one method are consumed in order. The exchange state is
        untouched by a failed call; to model an AMBIGUOUS failure (the order reached the
        exchange but the answer was lost), perform the state change yourself (`fill`, `cancel`)
        and script the failure.
        """
        self._failures.setdefault(method_name, deque()).append(exc)

    def reject_next(self, method_name: str, code: int, message: str = "scripted rejection") -> None:
        """The next call of `method_name` raises the SDK `BadRequestError` with `code`."""
        self.fail_next(method_name, BadRequestError(error_message=message, status_code=code))

    def reject_next_algo(self, code: int, message: str = "scripted rejection") -> None:
        """The next `place_algo_protective` is rejected with `code` (for example -2021)."""
        self.reject_next("place_algo_protective", code, message)

    async def _pass_gates(self, method_name: str) -> None:
        pending = self._hold_pending.get(method_name)
        if pending:
            event = pending.popleft()
            waiting = self._hold_waiting.setdefault(method_name, deque())
            waiting.append(event)
            try:
                await event.wait()
            finally:
                waiting.remove(event)
        failures = self._failures.get(method_name)
        if failures:
            raise failures.popleft()

    def trigger_stop(self, client_algo_id: str) -> None:
        """The exchange triggers an open algo: it leaves the open book as FINISHED [ASSUMED].

        A closePosition algo consumes the whole position of its symbol; an explicit-quantity
        algo reduces it by its quantity, capped at the position. A still-open entry that fills
        later opens a NEW position (the D-12 B4 race). The trigger price is not compared with
        the mark price: the test decides when the exchange triggers.
        """
        record = self.open_algos.pop(client_algo_id)
        position = self.positions.get(record.symbol, ZERO)
        if position != ZERO:
            if record.close_position or record.quantity is None:
                closed = abs(position)
            else:
                closed = min(record.quantity, abs(position))
            delta = -closed if position > ZERO else closed
            self._apply_position_delta(
                record.symbol, delta, record.trigger_price or self._entry_prices[record.symbol]
            )
        record.status = STATUS_FINISHED
        record.updated_at_utc = self.now_utc
        self.algo_history[client_algo_id] = record

    def set_mark_price(self, symbol: str, price: Decimal, time_utc: datetime | None = None) -> None:
        """Set the mark price `get_mark_price` serves for `symbol` (exchange time: `time_utc`)."""
        from src.adapters.binance_public import MarkPriceReading

        self._mark_prices[symbol] = MarkPriceReading(
            symbol=symbol, mark_price=price, exchange_time_utc=time_utc or self.now_utc
        )

    def set_mark_price_error(self, exc: BaseException | None) -> None:
        """The exception `get_mark_price` raises for a symbol with no price set (None: clear)."""
        self._mark_price_error = exc

    def set_lot_filters(self, symbol: str, filters: Any) -> None:
        """Set the `LotFilters` `symbol_lot_filters` serves for `symbol`."""
        self._lot_filters[symbol] = filters

    # ------------------------------------------------------------------ #
    # ExecutionAdapter surface.
    # ------------------------------------------------------------------ #

    @_exchange_call("place_entry")
    async def place_entry(self, **kwargs: Any) -> Any:
        if self.on_place_entry is not None:
            self.on_place_entry(dict(kwargs))
        client_id = kwargs["new_client_order_id"]
        if client_id in self.open_orders:
            # Binance error -4116 DUPLICATED_CLIENT_ORDER_ID, only among OPEN orders. The
            # code is documented; for a normal order it was not observed on Demo (assumption 1).
            raise BadRequestError(
                error_message=DUPLICATE_ORDER_MESSAGE, status_code=DUPLICATE_CLIENT_ID_CODE
            )
        record = ExchangeOrderRecord(
            client_id=client_id,
            symbol=kwargs["symbol"],
            status=STATUS_NEW,
            created_at_utc=self.now_utc,
            exchange_id=f"ex-{next(self._ids)}",
            quantity=_dec(kwargs["quantity"]),
            side=kwargs["side"],
            position_side=kwargs["position_side"],
            order_type="LIMIT",
            time_in_force=kwargs["time_in_force"],
            price=_dec(kwargs["price"]),
        )
        self.open_orders[client_id] = record
        from src.adapters.binance_usdm import EntryPlacementResult

        # The same result type the real adapter returns (the manager reads its attributes).
        return EntryPlacementResult(
            symbol=kwargs["symbol"],
            client_order_id=client_id,
            exchange_order_id=record.exchange_id,
            side=kwargs["side"],
            position_side=kwargs["position_side"],
            order_type="LIMIT",
            time_in_force=kwargs["time_in_force"],
            status=STATUS_NEW,
            quantity=kwargs["quantity"],
            price=kwargs["price"],
            update_time_utc=record.update_time_utc,
        )

    @_exchange_call("place_algo_protective")
    async def place_algo_protective(self, **kwargs: Any) -> Any:
        client_algo_id = kwargs["client_algo_id"]
        if client_algo_id in self.open_algos:
            # The docs name no error code for a duplicate algo id (research A8); the Demo probe
            # observed -4116 "ClientOrderId is duplicated." (check file line 33).
            raise BadRequestError(
                error_message=DUPLICATE_ALGO_MESSAGE, status_code=DUPLICATE_CLIENT_ID_CODE
            )
        if (
            self.enforce_flat_stop_rejection
            and kwargs["close_position"]
            and self.positions.get(kwargs["symbol"], ZERO) == ZERO
        ):
            # [DEMO] probe check file line 38: closePosition while flat answers -4509.
            raise BadRequestError(
                error_message=FLAT_CLOSE_POSITION_MESSAGE, status_code=FLAT_CLOSE_POSITION_CODE
            )
        record = ExchangeOrderRecord(
            client_id=client_algo_id,
            symbol=kwargs["symbol"],
            status=STATUS_NEW,
            created_at_utc=self.now_utc,
            exchange_id=f"algo-{next(self._ids)}",
            quantity=_dec(kwargs["quantity"]),
            side=kwargs["side"],
            position_side=kwargs["position_side"],
            order_type=kwargs["type"],
            trigger_price=_dec(kwargs["trigger_price"]),
            close_position=kwargs["close_position"],
            reduce_only=bool(kwargs.get("reduce_only") or False),
            working_type=kwargs["working_type"],
            algo_type=kwargs["algo_type"],
        )
        self.open_algos[client_algo_id] = record
        from src.adapters.binance_usdm import AlgoPlacementResult

        return AlgoPlacementResult(
            symbol=kwargs["symbol"],
            client_algo_id=client_algo_id,
            algo_id=record.exchange_id,
            algo_type=kwargs["algo_type"],
            order_type=kwargs["type"],
            side=kwargs["side"],
            position_side=kwargs["position_side"],
            algo_status=STATUS_NEW,
            trigger_price=kwargs["trigger_price"],
            close_position=kwargs["close_position"],
            working_type=kwargs["working_type"],
            update_time_utc=record.update_time_utc,
        )

    @_exchange_call("query_order_by_client")
    async def query_order_by_client(self, **kwargs: Any) -> Any:
        from src.adapters.binance_usdm import OrderProbe

        client_id = kwargs["orig_client_order_id"]
        record = self.open_orders.get(client_id) or self._visible_history(self.history, client_id)
        if record is None:
            return OrderProbe(
                client_order_id=client_id,
                found=False,
                order_id=None,
                status=None,
                update_time_utc=None,
            )
        return OrderProbe(
            client_order_id=client_id,
            found=True,
            order_id=record.exchange_id,
            status=record.status,
            update_time_utc=record.update_time_utc,
            executed_quantity=record.executed_quantity,
            average_price=record.average_price,
        )

    @_exchange_call("query_algo_order_by_client")
    async def query_algo_order_by_client(self, **kwargs: Any) -> Any:
        from src.adapters.binance_usdm import AlgoOrderProbe

        client_algo_id = kwargs["client_algo_id"]
        record = self.open_algos.get(client_algo_id) or self._visible_history(
            self.algo_history, client_algo_id
        )
        if record is None:
            return AlgoOrderProbe(
                client_algo_id=client_algo_id,
                found=False,
                algo_status=None,
                update_time_utc=None,
            )
        return AlgoOrderProbe(
            client_algo_id=client_algo_id,
            found=True,
            algo_status=record.status,
            update_time_utc=record.update_time_utc,
        )

    @_exchange_call("get_mark_price")
    async def get_mark_price(self, **kwargs: Any) -> Any:
        symbol = kwargs["symbol"]
        reading = self._mark_prices.get(symbol)
        if reading is None:
            if self._mark_price_error is not None:
                raise self._mark_price_error
            raise RuntimeError(f"no mark price set for {symbol}")
        return reading

    @_exchange_call("symbol_lot_filters")
    async def symbol_lot_filters(self, **kwargs: Any) -> Any:
        symbol = kwargs["symbol"]
        filters = self._lot_filters.get(symbol)
        if filters is None:
            raise ValueError(f"no lot filters set for {symbol}")
        return filters

    @staticmethod
    def error_facts(exc: BaseException) -> Any:
        """Same facts as the real adapter (a static, SDK-free classification helper)."""
        from src.adapters.binance_errors import error_facts_from_exception
        from src.adapters.binance_usdm import BinanceUsdmAdapter

        inspect.signature(BinanceUsdmAdapter.error_facts).bind(exc)
        return error_facts_from_exception(exc)

    @_exchange_call("snapshot_open_normal_orders")
    async def snapshot_open_normal_orders(self, **kwargs: Any) -> Any:
        from src.adapters.binance_usdm import OpenOrderSnapshot

        symbol = kwargs.get("symbol")
        return [
            OpenOrderSnapshot(
                symbol=record.symbol,
                client_order_id=record.client_id,
                exchange_order_id=record.exchange_id,
                side=record.side,
                position_side=record.position_side,
                order_type=record.order_type,
                time_in_force=record.time_in_force,
                status=record.status,
                quantity=record.quantity if record.quantity is not None else ZERO,
                price=record.price,
                stop_price=None,
                reduce_only=record.reduce_only,
                close_position=record.close_position,
                working_type=None,
                price_protect=None,
                update_time_utc=record.update_time_utc,
            )
            for record in self.open_orders.values()
            if symbol is None or record.symbol == symbol
        ]

    @_exchange_call("snapshot_open_algo_orders")
    async def snapshot_open_algo_orders(self, **kwargs: Any) -> Any:
        from src.adapters.binance_usdm import OpenAlgoOrderSnapshot

        symbol = kwargs.get("symbol")
        return [
            OpenAlgoOrderSnapshot(
                symbol=record.symbol,
                client_algo_id=record.client_id,
                algo_id=record.exchange_id,
                algo_type=record.algo_type,
                order_type=record.order_type,
                side=record.side,
                position_side=record.position_side,
                time_in_force=record.time_in_force,
                algo_status=record.status,
                quantity=record.quantity if record.quantity is not None else ZERO,
                trigger_price=record.trigger_price,
                price=None,
                trigger_time_utc=None,
                working_type=record.working_type,
                close_position=record.close_position,
                reduce_only=record.reduce_only,
                update_time_utc=record.update_time_utc,
            )
            for record in self.open_algos.values()
            if symbol is None or record.symbol == symbol
        ]

    @_exchange_call("place_market_close")
    async def place_market_close(self, **kwargs: Any) -> Any:
        """A reduce-only MARKET close; the rejection codes are TEST CONVENTIONS (A4/A8)."""
        from src.adapters.binance_usdm import MarketCloseResult

        symbol = kwargs["symbol"]
        side = kwargs["side"]
        quantity = _dec(kwargs["quantity"])
        assert quantity is not None
        position = self.positions.get(symbol, ZERO)
        closes_the_position = (side == "SELL" and position > ZERO) or (
            side == "BUY" and position < ZERO
        )
        if position == ZERO or not closes_the_position:
            # UNPROVEN code (research A4/A8): the fake uses -2022 for a flat position and for a
            # reduce-only order that would add exposure. Callers treat -2022 and -2024 alike.
            raise BadRequestError(
                error_message="ReduceOnly Order is rejected.",
                status_code=REDUCE_ONLY_REJECT_CODE,
            )
        if quantity > abs(position):
            raise BadRequestError(
                error_message="Position is not sufficient.",
                status_code=POSITION_NOT_SUFFICIENT_CODE,
            )
        mark = self._mark_prices.get(symbol)
        fill_price = mark.mark_price if mark is not None else self._entry_prices[symbol]
        self._apply_position_delta(symbol, -quantity if position > ZERO else quantity, fill_price)
        client_id = kwargs["new_client_order_id"]
        record = ExchangeOrderRecord(
            client_id=client_id,
            symbol=symbol,
            status=STATUS_FILLED,
            created_at_utc=self.now_utc,
            exchange_id=f"ex-{next(self._ids)}",
            had_fill=True,
            updated_at_utc=self.now_utc,
            quantity=quantity,
            executed_quantity=quantity,
            average_price=fill_price,
            side=side,
            position_side=kwargs["position_side"],
            order_type="MARKET",
            reduce_only=kwargs["position_side"] == "BOTH",
        )
        self.history[client_id] = record
        return MarketCloseResult(
            symbol=symbol,
            client_order_id=client_id,
            exchange_order_id=record.exchange_id,
            side=side,
            position_side=kwargs["position_side"],
            status=STATUS_NEW if self.market_close_ack_only else STATUS_FILLED,
            executed_quantity=None if self.market_close_ack_only else quantity,
            average_price=None if self.market_close_ack_only else fill_price,
            update_time_utc=record.update_time_utc,
        )

    @_exchange_call("snapshot_positions")
    async def snapshot_positions(self, **kwargs: Any) -> Any:
        from src.adapters.binance_usdm import PositionSnapshot

        symbol = kwargs.get("symbol")
        rows = []
        for sym, amount in sorted(self.positions.items()):
            if amount == ZERO or (symbol is not None and sym != symbol):
                continue
            entry = self._entry_prices.get(sym, ZERO)
            rows.append(
                PositionSnapshot(
                    symbol=sym,
                    position_side="BOTH",
                    position_amt=amount,
                    entry_price=entry,
                    break_even_price=entry,
                    mark_price=self._mark_prices[sym].mark_price
                    if sym in self._mark_prices
                    else None,
                    unrealized_profit=ZERO,
                    liquidation_price=None,
                    notional=None,
                    margin_asset="USDT",
                    update_time_utc=self.now_utc,
                )
            )
        return rows

    @_exchange_call("get_position_mode")
    async def get_position_mode(self) -> Any:
        from src.adapters.binance_usdm import PositionModeResult

        if self.position_mode not in ("ONE_WAY", "HEDGE"):
            raise RuntimeError("position mode unavailable")
        return PositionModeResult(dual_side_position=self.position_mode == "HEDGE")

    @_exchange_call("cancel_normal_order")
    async def cancel_normal_order(self, **kwargs: Any) -> Any:
        client_id = kwargs["orig_client_order_id"]
        if client_id in self.open_orders:
            # A PARTIALLY_FILLED entry ends CANCELED with its executed quantity kept (the
            # position it opened stays); a FILLED entry is no longer open: a no-op (ORDER_ABSENT
            # semantics, research P5).
            self.cancel(client_id)
        return None

    @_exchange_call("cancel_algo_order")
    async def cancel_algo_order(self, **kwargs: Any) -> Any:
        client_algo_id = kwargs["client_algo_id"]
        if client_algo_id in self.open_algos:
            self.cancel_algo(client_algo_id)
        return None

    # ------------------------------------------------------------------ #
    # Retention rule (research Pitfall 11).
    # ------------------------------------------------------------------ #

    def _visible_history(
        self, book: dict[str, ExchangeOrderRecord], client_id: str
    ) -> ExchangeOrderRecord | None:
        record = book.get(client_id)
        if record is None:
            return None
        too_old = self.now_utc - record.created_at_utc > HISTORY_RETENTION
        if too_old and not record.had_fill and record.status == STATUS_CANCELED:
            return None
        return record
