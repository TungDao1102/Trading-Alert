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
"""

from __future__ import annotations

import inspect
import itertools
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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

STATUS_NEW = "NEW"
STATUS_FILLED = "FILLED"
STATUS_CANCELED = "CANCELED"


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

    @property
    def update_time_utc(self) -> datetime:
        """The `updateTime` an exchange query reports: the last change, else the creation."""
        return self.updated_at_utc if self.updated_at_utc is not None else self.created_at_utc


class BinanceSemanticsFakeAdapter:
    """In-memory adapter implementing the seven `ExecutionAdapter` methods."""

    def __init__(
        self,
        *,
        position_mode: str = "ONE_WAY",
        now_utc: datetime | None = None,
    ) -> None:
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

    def fill(self, client_id: str) -> None:
        """The order fills: it leaves the open book and frees its client id."""
        record = self.open_orders.pop(client_id)
        record.status = STATUS_FILLED
        record.had_fill = True
        record.updated_at_utc = self.now_utc
        self.history[client_id] = record

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
    # ExecutionAdapter surface.
    # ------------------------------------------------------------------ #

    async def place_entry(self, **kwargs: Any) -> Any:
        self._bind_real("place_entry", kwargs)
        self._record_call("place_entry", kwargs)
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

    async def place_algo_protective(self, **kwargs: Any) -> Any:
        self._bind_real("place_algo_protective", kwargs)
        self._record_call("place_algo_protective", kwargs)
        client_algo_id = kwargs["client_algo_id"]
        if client_algo_id in self.open_algos:
            # The docs name no error code for a duplicate algo id (research A8); the Demo probe
            # observed -4116 "ClientOrderId is duplicated." (check file line 33).
            raise BadRequestError(
                error_message=DUPLICATE_ALGO_MESSAGE, status_code=DUPLICATE_CLIENT_ID_CODE
            )
        record = ExchangeOrderRecord(
            client_id=client_algo_id,
            symbol=kwargs["symbol"],
            status=STATUS_NEW,
            created_at_utc=self.now_utc,
            exchange_id=f"algo-{next(self._ids)}",
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

    async def query_order_by_client(self, **kwargs: Any) -> Any:
        from src.adapters.binance_usdm import OrderProbe

        self._bind_real("query_order_by_client", kwargs)
        self._record_call("query_order_by_client", kwargs)
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
        )

    async def query_algo_order_by_client(self, **kwargs: Any) -> Any:
        from src.adapters.binance_usdm import AlgoOrderProbe

        self._bind_real("query_algo_order_by_client", kwargs)
        self._record_call("query_algo_order_by_client", kwargs)
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

    async def get_position_mode(self) -> Any:
        from src.adapters.binance_usdm import PositionModeResult

        self._record_call("get_position_mode", {})
        if self.position_mode not in ("ONE_WAY", "HEDGE"):
            raise RuntimeError("position mode unavailable")
        return PositionModeResult(dual_side_position=self.position_mode == "HEDGE")

    async def cancel_normal_order(self, **kwargs: Any) -> Any:
        self._bind_real("cancel_normal_order", kwargs)
        self._record_call("cancel_normal_order", kwargs)
        client_id = kwargs["orig_client_order_id"]
        if client_id in self.open_orders:
            self.cancel(client_id)
        return None

    async def cancel_algo_order(self, **kwargs: Any) -> Any:
        self._bind_real("cancel_algo_order", kwargs)
        self._record_call("cancel_algo_order", kwargs)
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
