"""Flow tests for the Binance Demo Trading rehearsal runner (quick task 261005-tx9).

Everything here is offline. `FakeDemoAdapter` binds every call against the real
`BinanceUsdmAdapter` signature and simulates just enough Binance state; `FakeApprovalChannel`
"taps" by running the production `on_callback` / `parse_callback_data` / `dispatch_callback`
code, so the approval logic under test is the production logic. No test opens a socket, builds
a python-telegram-bot Application or places an order.
"""

from __future__ import annotations

import ast
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import demo_rehearsal as dr
from src.adapters.binance_public import MarkPriceReading
from src.adapters.binance_usdm import (
    AlgoOrderProbe,
    AlgoPlacementResult,
    BinanceUsdmAdapter,
    CommissionRates,
    EntryPlacementResult,
    Kline,
    MarketCloseResult,
    MarkKline,
    OpenAlgoOrderSnapshot,
    OpenOrderSnapshot,
    OrderProbe,
    PositionModeResult,
    PositionSnapshot,
    SymbolFilters,
)
from src.adapters.telegram_callbacks import on_callback
from src.approval.mapping import derive_short_id
from src.backtest.semantics import TP1_QUANTITY_FRACTION
from src.domain.enums import ApprovalResult
from src.domain.lot_filters import LotFilters
from src.execution.enablement import LiveEnablementController
from src.execution.execution_limits import ExecutionLimits
from src.ops.health import ALL_CHECK_NAMES

from tests.support import execution_limits as test_limits

SERVER_NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
FAKE_KEY = "FAKEKEY0123456789ABCDEF"
FAKE_SECRET = "FAKESECRET0123456789GHIJKL"
FAKE_TOKEN = "123456789:FAKETELEGRAMTOKENFAKETELEGRAMTOKEN12"
AUTH_CHAT = 424242
OTHER_CHAT = 777000
MARK = Decimal("60000.0")

MUTATING = (
    "place_entry",
    "place_algo_protective",
    "cancel_normal_order",
    "cancel_algo_order",
    "place_market_close",
)


def environ() -> dict[str, str]:
    return {
        "BINANCE_DEMO_API_KEY": FAKE_KEY,
        "BINANCE_DEMO_API_SECRET": FAKE_SECRET,
        "TELEGRAM_BOT_TOKEN": FAKE_TOKEN,
        "TELEGRAM_AUTHORIZED_CHAT_ID": str(AUTH_CHAT),
    }


def fixed_clock() -> datetime:
    return SERVER_NOW


async def no_sleep(_seconds: int) -> None:
    return None


def btc_filters(**overrides: Any) -> SymbolFilters:
    fields: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "contract_type": "PERPETUAL",
        "status": "TRADING",
        "onboard_time_utc": None,
        "price_tick_size": Decimal("0.1"),
        "quantity_step_size": Decimal("0.001"),
        "min_quantity": Decimal("0.001"),
        "max_quantity": Decimal("1000"),
        "min_notional": Decimal("100"),
        "base_asset": "BTC",
        "quote_asset": "USDT",
        "margin_asset": "USDT",
        "notional_constraints_json": "{}",
        "order_capabilities_json": "{}",
        "position_mode_snapshot_json": "{}",
        "percent_price_multiplier_up": Decimal("1.05"),
        "percent_price_multiplier_down": Decimal("0.95"),
        "percent_price_multiplier_decimals": 4,
        # Plan 19-16: the exchange always publishes MARKET_LOT_SIZE; with it known, the only
        # unknowns of the plan snapshot are margin type, leverage and equity (Phases 21-22).
        "market_lot_min_quantity": Decimal("0.001"),
        "market_lot_max_quantity": Decimal("120"),
        "market_lot_step_size": Decimal("0.001"),
    }
    fields.update(overrides)
    return SymbolFilters(**fields)


def _kline(interval: str, open_time: datetime, close_time: datetime) -> Kline:
    return Kline(
        symbol="BTCUSDT",
        interval=interval,
        open_time_utc=open_time,
        close_time_utc=close_time,
        open=MARK,
        high=MARK,
        low=MARK,
        close=MARK,
        volume=Decimal("1"),
        quote_volume=Decimal("1"),
        trade_count=1,
    )


# --------------------------------------------------------------------------- #
# Fake Demo exchange.
# --------------------------------------------------------------------------- #


class FakeDemoAdapter:
    """Binds every call to the real adapter signature and simulates Demo state."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.kwargs_log: list[tuple[str, dict[str, Any]]] = []
        self.orders: dict[str, dict[str, Any]] = {}
        self.algos: dict[str, dict[str, Any]] = {}
        self.position_amt = Decimal("0")
        self.entry_price = Decimal("0")
        self.fill_on_place = False
        self.flip_to_filled_after_place = False
        self.stale_hourly = False
        self.stale_minute = False
        self.preexisting_open_order = False
        self.raise_on: dict[str, BaseException] = {}
        self.raise_when_symbol_none: BaseException | None = None
        self.info_calls = 0
        self.drift_after_info_calls: int | None = None
        # Plan 19-13: the mark price `get_mark_price` reports; `None` reports MARK, the same
        # mark the plan is derived from (19-REVIEW CR-02: the derived zone must contain it, so
        # no flow test moves the gate mark onto the entry any more). A test that wants the
        # mark to have left the zone sets it explicitly.
        self.gate_mark_price: Decimal | None = None
        self._next_id = 1

    @staticmethod
    def _bind(name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        inspect.signature(getattr(BinanceUsdmAdapter, name)).bind(None, *args, **kwargs)

    def _enter(self, name: str, *args: Any, **kwargs: Any) -> None:
        self._bind(name, args, kwargs)
        self.calls.append(name)
        self.kwargs_log.append((name, dict(kwargs)))
        if name in self.raise_on:
            raise self.raise_on[name]

    def _new_id(self) -> str:
        value = f"ORD-{self._next_id}"
        self._next_id += 1
        return value

    # ----- reads ------------------------------------------------------------- #

    async def server_time(self) -> datetime:
        self._enter("server_time")
        return SERVER_NOW

    async def exchange_info(self) -> list[SymbolFilters]:
        self._enter("exchange_info")
        self.info_calls += 1
        if (
            self.drift_after_info_calls is not None
            and self.info_calls > self.drift_after_info_calls
        ):
            return [btc_filters(price_tick_size=Decimal("0.5"))]
        return [btc_filters()]

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]:
        self._enter("klines", symbol, interval, start_ms, end_ms, limit)
        if interval == "1m":
            age = timedelta(minutes=30) if self.stale_minute else timedelta(seconds=20)
            opened = SERVER_NOW - age
            return [_kline("1m", opened, opened + timedelta(seconds=59))]
        closed_ago = timedelta(hours=3) if self.stale_hourly else timedelta(minutes=10)
        closed = SERVER_NOW - closed_ago
        return [
            _kline("1h", closed - timedelta(hours=1), closed),
            _kline("1h", closed, closed + timedelta(hours=1)),
        ]

    async def mark_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[MarkKline]:
        self._enter("mark_klines", symbol, interval, start_ms, end_ms, limit)
        return [
            MarkKline(
                symbol="BTCUSDT",
                interval=interval,
                open_time_utc=SERVER_NOW - timedelta(seconds=20),
                close_time_utc=SERVER_NOW + timedelta(seconds=39),
                open=MARK,
                high=MARK,
                low=MARK,
                close=MARK,
                price_tick_count=10,
            )
        ]

    async def user_commission_rate(self, symbol: str) -> CommissionRates:
        self._enter("user_commission_rate", symbol)
        return CommissionRates(
            symbol=symbol, maker_rate=Decimal("0.0002"), taker_rate=Decimal("0.0004")
        )

    async def get_mark_price(self, *, symbol: str) -> MarkPriceReading:
        self._enter("get_mark_price", symbol=symbol)
        price = self.gate_mark_price if self.gate_mark_price is not None else MARK
        return MarkPriceReading(symbol=symbol, mark_price=price, exchange_time_utc=SERVER_NOW)

    async def get_position_mode(self) -> PositionModeResult:
        self._enter("get_position_mode")
        return PositionModeResult(dual_side_position=False)

    async def snapshot_open_normal_orders(
        self, *, symbol: str | None = None
    ) -> list[OpenOrderSnapshot]:
        self._enter("snapshot_open_normal_orders", symbol=symbol)
        rows = [
            OpenOrderSnapshot(
                symbol="BTCUSDT",
                client_order_id=cid,
                exchange_order_id=row["order_id"],
                side="BUY",
                position_side="BOTH",
                order_type="LIMIT",
                time_in_force="GTC",
                status=row["status"],
                quantity=row["qty"],
                price=row["price"],
                stop_price=None,
                reduce_only=False,
                close_position=False,
                working_type=None,
                price_protect=None,
                update_time_utc=SERVER_NOW,
            )
            for cid, row in self.orders.items()
            if row["status"] == "NEW"
        ]
        if self.preexisting_open_order:
            rows.append(
                OpenOrderSnapshot(
                    symbol="BTCUSDT",
                    client_order_id="stray",
                    exchange_order_id="1",
                    side="BUY",
                    position_side="BOTH",
                    order_type="LIMIT",
                    time_in_force="GTC",
                    status="NEW",
                    quantity=Decimal("0.001"),
                    price=Decimal("1"),
                    stop_price=None,
                    reduce_only=False,
                    close_position=False,
                    working_type=None,
                    price_protect=None,
                    update_time_utc=SERVER_NOW,
                )
            )
        return rows

    async def snapshot_open_algo_orders(
        self, *, symbol: str | None = None
    ) -> list[OpenAlgoOrderSnapshot]:
        self._enter("snapshot_open_algo_orders", symbol=symbol)
        if symbol is None and self.raise_when_symbol_none is not None:
            raise self.raise_when_symbol_none
        return [
            OpenAlgoOrderSnapshot(
                symbol="BTCUSDT",
                client_algo_id=cid,
                algo_id=row["algo_id"],
                algo_type="CONDITIONAL",
                order_type=row["type"],
                side=row["side"],
                position_side="BOTH",
                time_in_force="GTC",
                algo_status=row["status"],
                quantity=row["quantity"] or Decimal("0"),
                trigger_price=row["trigger"],
                price=None,
                trigger_time_utc=None,
                working_type="MARK_PRICE",
                close_position=row["close_position"],
                reduce_only=bool(row["reduce_only"]),
                update_time_utc=SERVER_NOW,
            )
            for cid, row in self.algos.items()
            if row["status"] == "NEW"
        ]

    async def snapshot_positions(self, *, symbol: str | None = None) -> list[PositionSnapshot]:
        self._enter("snapshot_positions", symbol=symbol)
        if self.position_amt == 0:
            return []
        return [
            PositionSnapshot(
                symbol="BTCUSDT",
                position_side="BOTH",
                position_amt=self.position_amt,
                entry_price=self.entry_price,
                break_even_price=self.entry_price,
                mark_price=MARK,
                unrealized_profit=Decimal("0"),
                liquidation_price=None,
                notional=None,
                margin_asset="USDT",
                update_time_utc=SERVER_NOW,
            )
        ]

    async def query_order_by_client(self, *, symbol: str, orig_client_order_id: str) -> OrderProbe:
        self._enter(
            "query_order_by_client", symbol=symbol, orig_client_order_id=orig_client_order_id
        )
        row = self.orders.get(orig_client_order_id)
        if row is None:
            return OrderProbe(
                client_order_id=orig_client_order_id,
                found=False,
                order_id=None,
                status=None,
                update_time_utc=None,
            )
        return OrderProbe(
            client_order_id=orig_client_order_id,
            found=True,
            order_id=row["order_id"],
            status=row["status"],
            update_time_utc=SERVER_NOW,
        )

    async def query_algo_order_by_client(self, *, client_algo_id: str) -> AlgoOrderProbe:
        self._enter("query_algo_order_by_client", client_algo_id=client_algo_id)
        row = self.algos.get(client_algo_id)
        return AlgoOrderProbe(
            client_algo_id=client_algo_id,
            found=row is not None,
            algo_status=None if row is None else row["status"],
            update_time_utc=None if row is None else SERVER_NOW,
        )

    # ----- mutating ---------------------------------------------------------- #

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
        self._enter(
            "place_entry",
            symbol=symbol,
            side=side,
            position_side=position_side,
            time_in_force=time_in_force,
            quantity=quantity,
            price=price,
            new_client_order_id=new_client_order_id,
            good_till_date=good_till_date,
        )
        order_id = self._new_id()
        status = "FILLED" if (self.fill_on_place or self.flip_to_filled_after_place) else "NEW"
        self.orders[new_client_order_id] = {
            "order_id": order_id,
            "status": status,
            "qty": quantity,
            "price": price,
        }
        if status == "FILLED":
            self.position_amt = quantity
            self.entry_price = MARK
        return EntryPlacementResult(
            symbol=symbol,
            client_order_id=new_client_order_id,
            exchange_order_id=order_id,
            side=side,
            position_side=position_side,
            order_type="LIMIT",
            time_in_force=time_in_force,
            status="NEW",
            quantity=quantity,
            price=price,
            update_time_utc=SERVER_NOW,
        )

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
        self._enter(
            "place_algo_protective",
            symbol=symbol,
            side=side,
            algo_type=algo_type,
            type=type,
            position_side=position_side,
            trigger_price=trigger_price,
            close_position=close_position,
            quantity=quantity,
            working_type=working_type,
            client_algo_id=client_algo_id,
            reduce_only=reduce_only,
        )
        algo_id = self._new_id()
        self.algos[client_algo_id] = {
            "algo_id": algo_id,
            "status": "NEW",
            "type": type,
            "side": side,
            "trigger": trigger_price,
            "quantity": quantity,
            "close_position": close_position,
            "reduce_only": reduce_only,
        }
        return AlgoPlacementResult(
            symbol=symbol,
            client_algo_id=client_algo_id,
            algo_id=algo_id,
            algo_type=algo_type,
            order_type=type,
            side=side,
            position_side=position_side,
            algo_status="NEW",
            trigger_price=trigger_price,
            close_position=close_position,
            working_type=working_type,
            update_time_utc=SERVER_NOW,
        )

    async def cancel_normal_order(self, *, symbol: str, orig_client_order_id: str) -> None:
        self._enter("cancel_normal_order", symbol=symbol, orig_client_order_id=orig_client_order_id)
        row = self.orders.get(orig_client_order_id)
        if row is not None and row["status"] == "NEW":  # a FILLED order is not cancelled
            row["status"] = "CANCELED"

    async def symbol_lot_filters(self, *, symbol: str) -> LotFilters:
        self._enter("symbol_lot_filters", symbol=symbol)
        return LotFilters(
            symbol=symbol,
            price_tick_size=Decimal("0.1"),
            lot_min_quantity=Decimal("0.001"),
            lot_max_quantity=Decimal("1000"),
            lot_step_size=Decimal("0.001"),
            market_lot_min_quantity=Decimal("0.001"),
            market_lot_max_quantity=Decimal("120"),
            market_lot_step_size=Decimal("0.001"),
            min_notional=Decimal("100"),
        )

    async def place_market_close(
        self,
        *,
        symbol: str,
        side: str,
        position_side: str,
        quantity: Decimal,
        new_client_order_id: str,
    ) -> MarketCloseResult:
        self._enter(
            "place_market_close",
            symbol=symbol,
            side=side,
            position_side=position_side,
            quantity=quantity,
            new_client_order_id=new_client_order_id,
        )
        order_id = self._new_id()
        self.position_amt = max(self.position_amt - quantity, Decimal("0"))
        self.orders[new_client_order_id] = {
            "order_id": order_id,
            "status": "FILLED",
            "qty": quantity,
            "price": MARK,
        }
        return MarketCloseResult(
            symbol=symbol,
            client_order_id=new_client_order_id,
            exchange_order_id=order_id,
            side=side,
            position_side=position_side,
            status="FILLED",
            executed_quantity=quantity,
            average_price=MARK,
            update_time_utc=SERVER_NOW,
        )

    async def cancel_algo_order(self, *, symbol: str, client_algo_id: str) -> None:
        self._enter("cancel_algo_order", symbol=symbol, client_algo_id=client_algo_id)
        row = self.algos.get(client_algo_id)
        if row is None:
            raise RuntimeError("-2011 Unknown order sent")
        row["status"] = "CANCELED"

    def mutating_calls(self) -> list[str]:
        return [name for name in self.calls if name in MUTATING]


# --------------------------------------------------------------------------- #
# Fake approval channel: taps run the production on_callback / dispatch code.
# --------------------------------------------------------------------------- #


@dataclass
class ScriptedTap:
    prefix: str  # "APR:" or "SKP:"
    chat: str = "authorized"  # or "other"
    which: int = -1  # index among the messages sent to that chat


@dataclass
class SentMessage:
    chat_id: int
    text: str
    signal_id: str
    kind: str


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[Any, str]] = []
        self.raise_on_send: BaseException | None = None

    async def send_message(self, *, chat_id: Any, text: str, reply_markup: Any = None) -> Any:
        if self.raise_on_send is not None:
            raise self.raise_on_send
        self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=len(self.sent))


@dataclass
class FakeApprovalChannel:
    script: list[ScriptedTap | None] = field(default_factory=list)
    other_chat_id: int | None = OTHER_CHAT
    send_error: BaseException | None = None

    def __post_init__(self) -> None:
        self.notifier = FakeNotifier()
        self.sent: list[SentMessage] = []
        self.results: list[Any] = []
        self.opened = False
        self.closed = False
        self._deps: Any = None
        self._tap_no = 0

    async def open(self, deps: Any) -> None:
        self.opened = True
        self._deps = deps

    async def close(self) -> None:
        self.closed = True

    async def send_approval(self, *, chat_id: int, text: str, signal_id: str, kind: str) -> None:
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(SentMessage(chat_id, text, signal_id, kind))

    async def discover_other_chat(self, *, timeout_seconds: int) -> int | None:
        return self.other_chat_id

    async def next_result(self, *, timeout_seconds: int) -> Any:
        if not self.script:
            return None
        tap = self.script.pop(0)
        if tap is None:
            return None
        chat_id = AUTH_CHAT if tap.chat == "authorized" else (self.other_chat_id or 0)
        candidates = [m for m in self.sent if m.chat_id == chat_id]
        target = candidates[tap.which]
        self._tap_no += 1
        data = f"{tap.prefix}{derive_short_id(target.signal_id)}"
        answered: list[bool] = []

        async def _answer() -> None:
            answered.append(True)

        query = SimpleNamespace(
            data=data,
            id=f"q{self._tap_no}",
            message=SimpleNamespace(chat_id=chat_id),
            answer=_answer,
        )
        update = SimpleNamespace(callback_query=query, effective_chat=SimpleNamespace(id=chat_id))
        result = await on_callback(
            update,
            None,  # type: ignore[arg-type]
            authorized_chat_id=self._deps.authorized_chat_id,
            binding_context_resolver=self._deps.binding_context_resolver,
            dispatch=self._deps.dispatch,
            reply_text_fn=None,
        )
        self.results.append(result)
        return result


def counter_tokens() -> Callable[[], str]:
    state = {"n": 0}

    def factory() -> str:
        state["n"] += 1
        return f"fixed-test-token-{state['n']:04d}-abcdefghijklmnop"

    return factory


# --------------------------------------------------------------------------- #
# Harness.
# --------------------------------------------------------------------------- #


def approve_script() -> list[ScriptedTap | None]:
    return [ScriptedTap("APR:")]


def taps_script() -> list[ScriptedTap | None]:
    return [
        ScriptedTap("SKP:", "authorized"),
        ScriptedTap("APR:", "authorized"),
        ScriptedTap("APR:", "other", which=0),
    ]


def run_flow(
    tmp_path: Path,
    *,
    scenario: str,
    adapter: FakeDemoAdapter | None = None,
    channel: FakeApprovalChannel | None = None,
    execute: bool = False,
    dry_script: bool = True,
    execution_limits: ExecutionLimits | None = None,
    committed_limits: bool = False,
    snapshot_live_inputs: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any], FakeDemoAdapter, FakeApprovalChannel]:
    exchange = adapter if adapter is not None else FakeDemoAdapter()
    # TEST_ONLY limits by default; `committed_limits=True` loads config/execution instead,
    # where every value is NOT_CONFIGURED (plan 19-13).
    limits = (
        None
        if committed_limits
        else (
            execution_limits
            if execution_limits is not None
            else test_limits.test_only_execution_limits()
        )
    )
    chan = (
        channel
        if channel is not None
        else FakeApprovalChannel(script=taps_script() if scenario == "taps" else approve_script())
    )
    argv = ["--scenario", scenario, "--approval-timeout-seconds", "300"]
    confirmation = None
    if execute:
        argv.append("--execute")
        confirmation = lambda _p: dr.required_phrase(scenario)  # noqa: E731
    code = dr.main(
        argv,
        environ=environ(),
        adapter_factory=lambda creds: dr.AdapterBundle(
            inner=exchange,  # type: ignore[arg-type]
            guard=lambda: None,
        ),
        clock=fixed_clock,
        is_tty=lambda: execute,
        read_confirmation=confirmation,
        evidence_dir=tmp_path,
        channel_factory=lambda creds: chan,
        sleep=no_sleep,
        token_factory=counter_tokens(),
        execution_limits=limits,
        snapshot_live_inputs=snapshot_live_inputs,
    )
    files = sorted(tmp_path.glob("*.json"))
    data: dict[str, Any] = json.loads(files[-1].read_text(encoding="utf-8")) if files else {}
    return code, data, exchange, chan


def step(data: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [s for s in data["steps"] if s["name"] == name]
    assert matches, f"no step {name}: {[s['name'] for s in data['steps']]}"
    return matches[-1]


def make_ctx(
    adapter: FakeDemoAdapter,
    channel: FakeApprovalChannel,
    *,
    mode: dr.RunMode = dr.RunMode.DRY_RUN,
    scenario: str = "far",
    execution_limits: ExecutionLimits | None = None,
) -> dr.RunContext:
    recorder = dr.EvidenceRecorder(
        mode=mode,
        scenario=scenario,
        symbol="BTCUSDT",
        base_url=dr.DEMO_BASE_URL,
        environ=environ(),
        clock=fixed_clock,
    )
    guarded = dr.GuardedAdapter(
        adapter,  # type: ignore[arg-type]
        guard=lambda: None,
        mode=mode,
        clock=fixed_clock,
        recorder=recorder,
    )
    return dr.build_context(
        guarded=guarded,
        recorder=recorder,
        channel=channel,
        credentials=dr.load_credentials(environ()),
        scenario=scenario,
        mode=mode,
        clock=fixed_clock,
        sleep=no_sleep,
        approval_timeout_seconds=300,
        discovery_timeout_seconds=120,
        token_factory=counter_tokens(),
        execution_limits=(
            execution_limits
            if execution_limits is not None
            else test_limits.test_only_execution_limits()
        ),
    )


# --------------------------------------------------------------------------- #
# Health preflight (SR-6).
# --------------------------------------------------------------------------- #


async def test_health_preflight_runs_all_ten_probes_with_honest_degraded() -> None:
    ctx = make_ctx(FakeDemoAdapter(), FakeApprovalChannel())
    verdict = await dr.run_health_preflight(ctx)
    assert [r.check_name for r in verdict.results] == list(ALL_CHECK_NAMES)
    by_name = {r.check_name: r for r in verdict.results}
    for name in ("ws_connection_state", "user_data_stream_state", "db_writes"):
        assert by_name[name].status == "DEGRADED"
    assert "no WebSocket" in by_name["ws_connection_state"].detail
    assert "no user-data stream" in by_name["user_data_stream_state"].detail
    assert "no PostgreSQL" in by_name["db_writes"].detail
    passed = [r for r in verdict.results if r.status == "PASS"]
    assert len(passed) == 7
    assert verdict.is_no_trade is False
    assert len(ctx.journal.events) >= 10
    assert ctx.recorder.details["health"][2]["status"] == "DEGRADED"


@pytest.mark.parametrize(
    "mutate",
    [
        "open_order",
        "open_position",
        "stale_hourly",
        "stale_minute",
        "telegram_send",
        "read_failure",
    ],
)
def test_any_health_fail_aborts_before_any_mutation(tmp_path: Path, mutate: str) -> None:
    adapter = FakeDemoAdapter()
    channel = FakeApprovalChannel(script=approve_script())
    if mutate == "open_order":
        adapter.preexisting_open_order = True
    elif mutate == "open_position":
        adapter.position_amt = Decimal("0.01")
        adapter.entry_price = MARK
    elif mutate == "stale_hourly":
        adapter.stale_hourly = True
    elif mutate == "stale_minute":
        adapter.stale_minute = True
    elif mutate == "telegram_send":
        channel.notifier.raise_on_send = RuntimeError("telegram down")
    elif mutate == "read_failure":
        adapter.raise_on["mark_klines"] = RuntimeError("boom")
    code, data, _, _ = run_flow(tmp_path, scenario="far", adapter=adapter, channel=channel)
    if mutate == "read_failure":
        # the failing read itself is an exception, so the run fails before any order
        assert code in (dr.EXIT_ABORTED, dr.EXIT_FAILED)
    else:
        assert code == dr.EXIT_ABORTED
        assert step(data, "health_preflight")["status"] == "FAILED"
    assert adapter.mutating_calls() == []
    assert data["exchange_orders"] == []
    assert data["outcome"] in ("ABORTED_NO_ORDER", "FAILED")


async def test_rest_error_rate_above_limit_fails_the_probe() -> None:
    adapter = FakeDemoAdapter()
    ctx = make_ctx(adapter, FakeApprovalChannel())
    adapter.raise_on["exchange_info"] = RuntimeError("boom")
    for _ in range(6):
        with pytest.raises(RuntimeError):
            await ctx.guarded.exchange_info()
    del adapter.raise_on["exchange_info"]
    verdict = await dr.run_health_preflight(ctx)
    by_name = {r.check_name: r for r in verdict.results}
    assert by_name["rest_error_rate"].status == "FAIL"
    assert verdict.is_no_trade is True


# --------------------------------------------------------------------------- #
# Plan derivation (SR-4).
# --------------------------------------------------------------------------- #


def _derive(scenario: str, **filter_overrides: Any) -> dr.DerivedPlan:
    from src.domain.registry import load_parameter_set

    return dr.derive_plan(
        scenario=scenario,
        filters=btc_filters(**filter_overrides),
        mark_price=MARK,
        parameter_set=load_parameter_set("trend-pullback", "baseline-v5"),
        commission=CommissionRates(
            symbol="BTCUSDT", maker_rate=Decimal("0.0002"), taker_rate=Decimal("0.0004")
        ),
        observed_at=SERVER_NOW,
        run_id=f"{scenario}-test",
        approval_timeout_seconds=300,
    )


def test_plan_derivation_is_decimal_and_hits_the_smallest_passing_quantity() -> None:
    plan = _derive("far")
    # entry 60000 * (1 - 0.05 * 0.5) = 58500.0 (the zone mid, the placed price). 19-REVIEW
    # CR-02: entry_max = 60000 * 1.005 = 60300.0 (the cushion past the mark), entry_min is the
    # mirror 2 * 58500.0 - 60300.0 = 56700.0, stop = 56700.0 * 0.985 = 55849.5 (below the zone).
    assert plan.entry_price == Decimal("58500.0")
    assert plan.trade_plan.entry_min_price == Decimal("56700.0")
    assert plan.trade_plan.entry_max_price == Decimal("60300.0")
    assert plan.stop_loss == Decimal("55849.5")
    assert plan.tp1_trigger == Decimal("61800.0")
    assert plan.tp2_trigger == Decimal("63600.0")
    # 0.002 and 0.003 fail the TP1 notional gate (0.001 * 61800 < 100); 0.004 is the first pass.
    assert plan.quantity == Decimal("0.004")
    assert plan.tp1_quantity == Decimal("0.002")
    # Back-solved at the adverse edge entry_max: 0.004 * (60300.0 - 55849.5 + 80.8596) / 0.005
    # = 3625.08768, rounded up to the cent.
    assert plan.equity == Decimal("3625.09")
    assert plan.trade_plan.status.value == "APPROVAL_PENDING"
    for value in (
        plan.entry_price,
        plan.stop_loss,
        plan.tp1_trigger,
        plan.tp2_trigger,
        plan.quantity,
        plan.tp1_quantity,
        plan.equity,
        plan.trade_plan.entry_min_price,
        plan.trade_plan.entry_max_price,
        plan.trade_plan.stop_loss_price,
        plan.trade_plan.suggested_quantity,
    ):
        assert isinstance(value, Decimal)
    assert plan.trade_plan.expiry_utc == SERVER_NOW + timedelta(seconds=300) + dr.PLAN_EXPIRY_MARGIN

    tree = ast.parse(Path(dr.__file__).read_text(encoding="utf-8"))
    float_calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "float"
    ]
    assert float_calls == []


def test_far_entry_price_is_inside_the_percent_price_band_and_fill_price_crosses() -> None:
    far = _derive("far")
    assert far.entry_price < MARK
    assert far.entry_price >= MARK * Decimal("0.95")
    assert far.entry_price % Decimal("0.1") == 0
    fill = _derive("fill")
    assert fill.entry_price == Decimal("61500.0")
    assert fill.entry_price > MARK
    assert fill.entry_price <= MARK * Decimal("1.05")
    # the stop sits below the mark so it cannot trigger on placement
    assert fill.stop_loss < MARK
    assert fill.tp1_trigger > MARK
    with pytest.raises(dr.RehearsalAbort):
        _derive("far", percent_price_multiplier_down=None)
    with pytest.raises(dr.RehearsalAbort):
        _derive("fill", percent_price_multiplier_up=None)


def test_derived_zone_contains_the_mark_and_its_mid_is_the_entry() -> None:
    """19-REVIEW CR-02: the far/fill plans pass the production gate 5e checks unchanged.

    The old one-price zone [entry, entry] excluded the mark (far sits below it, fill above it),
    so `check_mark_price` refused both scenarios with MARK_PRICE_OUTSIDE_ZONE on the exchange.
    """
    from src.execution.binding import check_snapped_geometry
    from src.execution.placement import derive_limit_price
    from src.execution.pre_placement import check_mark_price

    for scenario in ("far", "fill"):
        plan = _derive(scenario)
        trade_plan = plan.trade_plan
        assert trade_plan.entry_min_price < MARK < trade_plan.entry_max_price, scenario
        mid = derive_limit_price(
            entry_min_price=trade_plan.entry_min_price,
            entry_max_price=trade_plan.entry_max_price,
        )
        assert mid == plan.entry_price, scenario  # the manager places exactly the entry
        assert (
            check_mark_price(
                side="LONG",
                mark_price=MARK,
                mark_time_utc=SERVER_NOW,
                now_utc=SERVER_NOW,
                max_mark_price_age_ms=0,
                max_clock_skew=timedelta(0),
                sl_trigger_price=plan.stop_loss,
                entry_min_price=trade_plan.entry_min_price,
                entry_max_price=trade_plan.entry_max_price,
            )
            is None
        ), scenario
        assert (
            check_snapped_geometry(
                side="LONG",
                limit_price=plan.entry_price,
                sl_trigger_price=plan.stop_loss,
                entry_min_price=trade_plan.entry_min_price,
                entry_max_price=trade_plan.entry_max_price,
            )
            is None
        ), scenario
    fill = _derive("fill").trade_plan
    # fill: entry_min = 60000 * 0.995 = 59700.0, entry_max = 2 * 61500.0 - 59700.0 = 63300.0.
    assert (fill.entry_min_price, fill.entry_max_price) == (Decimal("59700.0"), Decimal("63300.0"))


@pytest.mark.parametrize("scenario", ["far", "fill"])
def test_order_scenarios_reach_the_entry_against_the_fakes_own_mark(
    tmp_path: Path, scenario: str
) -> None:
    """19-REVIEW CR-02: no gate-mark override; the fake reports the mark the plan came from."""
    adapter = FakeDemoAdapter()
    assert adapter.gate_mark_price is None
    _, data, _, _ = run_flow(tmp_path, scenario=scenario, adapter=adapter, execute=True)
    assert "MARK_PRICE_OUTSIDE_ZONE" not in json.dumps(data)
    entry_kwargs = next(kw for name, kw in adapter.kwargs_log if name == "place_entry")
    assert entry_kwargs["price"] == _derive(scenario).entry_price
    assert step(data, "place_entry")["status"] == "PASSED"


@pytest.mark.parametrize("scenario", ["far", "fill"])
def test_a_mark_past_the_zone_cushion_is_still_refused(tmp_path: Path, scenario: str) -> None:
    """The production zone check is not weakened: a LONG mark one tick below entry_min refuses.

    19-REVIEW WR-06 (owner): only the adverse side refuses, which for the rehearsal's LONG plan
    is a mark below entry_min. (Before WR-06 this test moved the mark one tick ABOVE entry_max;
    that is now the favorable resting-limit side and is allowed, see the next test.)
    """
    adapter = FakeDemoAdapter()
    adapter.gate_mark_price = _derive(scenario).trade_plan.entry_min_price - Decimal("0.1")
    code, data, _, _ = run_flow(tmp_path, scenario=scenario, adapter=adapter, execute=True)
    assert code == dr.EXIT_ABORTED
    assert adapter.mutating_calls() == []
    assert "MARK_PRICE_OUTSIDE_ZONE" in json.dumps(data)


def test_a_far_mark_above_the_zone_is_the_favorable_side_and_reaches_the_entry(
    tmp_path: Path,
) -> None:
    """19-REVIEW WR-06: a LONG mark one tick above entry_max no longer refuses at gate 5e."""
    adapter = FakeDemoAdapter()
    adapter.gate_mark_price = _derive("far").trade_plan.entry_max_price + Decimal("0.1")
    _, data, _, _ = run_flow(tmp_path, scenario="far", adapter=adapter, execute=True)
    assert "MARK_PRICE_OUTSIDE_ZONE" not in json.dumps(data)
    entry_kwargs = next(kw for name, kw in adapter.kwargs_log if name == "place_entry")
    assert entry_kwargs["price"] == _derive("far").entry_price


def test_tp1_quantity_fraction_is_the_backtest_constant() -> None:
    assert dr.TP1_QUANTITY_FRACTION is TP1_QUANTITY_FRACTION
    assert TP1_QUANTITY_FRACTION == Decimal("0.5")


# --------------------------------------------------------------------------- #
# Approval taps (SR-7, SR-11).
# --------------------------------------------------------------------------- #


def test_constraint_drift_between_plan_and_execution_aborts(tmp_path: Path) -> None:
    adapter = FakeDemoAdapter()
    adapter.drift_after_info_calls = 1
    code, data, _, _ = run_flow(tmp_path, scenario="far", adapter=adapter, execute=True)
    assert code == dr.EXIT_ABORTED
    assert adapter.mutating_calls() == []
    assert data["outcome"] == "ABORTED_NO_ORDER"
    assert "price_tick_size" in step(data, "constraint_recheck")["detail"]


@pytest.mark.parametrize("failure", ["timeout", "send_failure"])
def test_approval_timeout_and_send_failure_place_nothing(tmp_path: Path, failure: str) -> None:
    channel = FakeApprovalChannel(script=[None] if failure == "timeout" else [])
    if failure == "send_failure":
        channel.send_error = RuntimeError("telegram down " + FAKE_TOKEN)
    adapter = FakeDemoAdapter()
    code, data, _, chan = run_flow(
        tmp_path, scenario="far", adapter=adapter, channel=channel, execute=True
    )
    assert code == dr.EXIT_ABORTED
    assert adapter.mutating_calls() == []
    assert data["exchange_orders"] == []
    assert data["outcome"] == "ABORTED_NO_ORDER"
    assert chan.results == [] or all(not r.ok for r in chan.results)
    assert FAKE_TOKEN not in json.dumps(data)


def test_r3b_each_demo_approval_message_shows_the_quantity_stored_on_its_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issued_all: list[dr.IssuedApproval] = []
    original = dr.issue_approval

    def recording(*args: Any, **kwargs: Any) -> dr.IssuedApproval:
        issued = original(*args, **kwargs)
        issued_all.append(issued)
        return issued

    monkeypatch.setattr(dr, "issue_approval", recording)
    code, _data, _adapter, chan = run_flow(tmp_path, scenario="taps")
    assert code == dr.EXIT_OK
    assert len(chan.sent) >= 2
    for message in chan.sent:
        matching = [i for i in issued_all if i.signal_id == message.signal_id]
        assert len(matching) == 1
        stored = matching[0].approval.approved_quantity
        assert stored is not None
        lines = [x for x in message.text.split("\n") if x.startswith("Quantity: ")]
        assert lines == ["Quantity: " + format(stored, "f")]


def test_r3b_a_demo_approval_without_a_stored_quantity_is_never_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = dr.issue_approval

    def without_quantity(*args: Any, **kwargs: Any) -> dr.IssuedApproval:
        issued = original(*args, **kwargs)
        return dr.IssuedApproval(
            approval=replace(issued.approval, approved_quantity=None),
            raw_token=issued.raw_token,
            signal_id=issued.signal_id,
        )

    monkeypatch.setattr(dr, "issue_approval", without_quantity)
    adapter = FakeDemoAdapter()
    channel = FakeApprovalChannel(script=approve_script())
    code, data, _, chan = run_flow(
        tmp_path, scenario="far", adapter=adapter, channel=channel, execute=True
    )
    assert code == dr.EXIT_ABORTED
    assert data["outcome"] == "ABORTED_NO_ORDER"
    assert chan.sent == []
    assert adapter.mutating_calls() == []
    assert all(failure["step"] != "telegram_send" for failure in data["failures"])
    assert any(
        s["status"] == "FAILED" and s["detail"] == "approval carries no approved quantity"
        for s in data["steps"]
    )


def test_skip_tap_records_skipped_and_places_nothing(tmp_path: Path) -> None:
    code, data, adapter, chan = run_flow(tmp_path, scenario="taps")
    assert code == dr.EXIT_OK
    assert adapter.mutating_calls() == []
    assert step(data, "skip_tap")["status"] == "PASSED"
    first = chan.results[0]
    assert first.ok is True
    assert first.approval is not None
    assert first.approval.status is ApprovalResult.SKIPPED


def test_skp_tap_against_the_approve_approval_is_rejected(tmp_path: Path) -> None:
    channel = FakeApprovalChannel(script=[ScriptedTap("SKP:", "authorized")])
    adapter = FakeDemoAdapter()
    code, data, _, chan = run_flow(
        tmp_path, scenario="far", adapter=adapter, channel=channel, execute=True
    )
    assert code == dr.EXIT_ABORTED
    result = chan.results[0]
    assert result.ok is False
    assert result.reason_code is not None and result.reason_code.value == "INVALIDATED"
    assert adapter.mutating_calls() == []


def test_unknown_chat_tap_is_rejected_journaled_and_row_untouched(tmp_path: Path) -> None:
    code, data, adapter, chan = run_flow(tmp_path, scenario="taps")
    assert code == dr.EXIT_OK
    result = chan.results[2]
    assert result.ok is False
    assert result.reason_code is not None and result.reason_code.value == "INVALIDATED"
    info = data["details"]["unknown_chat"]
    assert info["callback_received_chat_gate_rejected"] is True
    assert info["callback_rejected"] is True
    assert info["approval_row_unchanged"] is True
    assert info["chat_sha256_prefix"] and str(OTHER_CHAT) not in json.dumps(data)
    assert step(data, "unknown_chat_tap")["status"] == "PASSED"
    # both keyboards were posted to the discovered chat
    to_other = [m for m in chan.sent if m.chat_id == OTHER_CHAT]
    assert sorted(m.kind for m in to_other) == ["APPROVE", "SKIP"]


def test_no_second_chat_is_recorded_not_rehearsed(tmp_path: Path) -> None:
    channel = FakeApprovalChannel(script=taps_script()[:2], other_chat_id=None)
    code, data, adapter, _ = run_flow(tmp_path, scenario="taps", channel=channel)
    assert code == dr.EXIT_OK
    assert step(data, "unknown_chat_tap")["status"] == "NOT_REHEARSED"
    assert data["outcome"] == "COMPLETE_WITH_GAPS"
    assert "unknown_chat" not in data["details"] or not data["details"]["unknown_chat"]
    assert adapter.mutating_calls() == []


def test_approvals_are_only_ever_created_pending() -> None:
    tree = ast.parse(Path(dr.__file__).read_text(encoding="utf-8"))
    constructions = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "Approval"
    ]
    assert constructions, "the runner must construct approvals"
    for call in constructions:
        keywords = {k.arg: k.value for k in call.keywords}
        for name in ("status", "result"):
            value = keywords[name]
            assert isinstance(value, ast.Attribute)
            assert value.attr == "PENDING"
    source = Path(dr.__file__).read_text(encoding="utf-8")
    assert "status=ApprovalResult.APPROVED" not in source
    assert "result=ApprovalResult.APPROVED" not in source


# --------------------------------------------------------------------------- #
# Scenarios (SR-3, SR-5).
# --------------------------------------------------------------------------- #


def test_far_scenario_sequence_and_cleanup(tmp_path: Path) -> None:
    """Plan 19-15 (D-10): the manager places only the GTD entry; the far scenario then cancels
    the entry by id. There is no stop at entry time, so no algo order is placed, probed or
    cancelled."""
    code, data, adapter, chan = run_flow(tmp_path, scenario="far", execute=True)
    assert code == dr.EXIT_OK
    assert adapter.mutating_calls() == ["place_entry", "cancel_normal_order"]
    assert adapter.calls.index("get_position_mode") < adapter.calls.index("place_entry")
    assert "place_algo_protective" not in adapter.calls
    assert "query_algo_order_by_client" not in adapter.calls
    assert "cancel_algo_order" not in adapter.calls
    entry_kwargs = next(kw for name, kw in adapter.kwargs_log if name == "place_entry")
    assert entry_kwargs["quantity"] == Decimal("0.004")
    assert entry_kwargs["price"] == Decimal("58500.0")
    assert entry_kwargs["side"] == "BUY" and entry_kwargs["position_side"] == "BOTH"
    assert entry_kwargs["time_in_force"] == "GTD"
    assert isinstance(entry_kwargs["good_till_date"], int)
    assert entry_kwargs["good_till_date"] % 1000 == 0  # whole seconds, in epoch milliseconds
    kinds = [o["type"] for o in data["exchange_orders"]]
    assert kinds == ["EntryPlacementResult"]
    assert data["exchange_orders"][0]["exchange_order_id"].startswith("ORD-")
    assert step(data, "place_entry")["status"] == "PASSED"
    assert "place_entry_and_stop" not in [s["name"] for s in data["steps"]]
    readback = step(data, "readback")
    assert readback["status"] == "PASSED"
    assert "no stop at entry time (D-10)" in readback["detail"]
    assert "'NEW'" in readback["detail"]
    assert "no protective leg exists" in step(data, "cleanup")["detail"]
    assert step(data, "account_clean")["status"] == "PASSED"
    assert data["details"]["enablement"]["enabled_in_run"] is True
    assert data["details"]["enablement"]["disabled_after_run"] is True
    assert chan.closed is True


def test_far_scenario_entry_no_longer_new_leaves_the_position_for_the_operator(
    tmp_path: Path,
) -> None:
    adapter = FakeDemoAdapter()
    adapter.flip_to_filled_after_place = True
    code, data, _, _ = run_flow(tmp_path, scenario="far", adapter=adapter, execute=True)
    assert code == dr.EXIT_FAILED
    assert "cancel_algo_order" not in adapter.calls
    assert "cancel_normal_order" not in adapter.calls
    assert "place_algo_protective" not in adapter.calls  # no stop exists to leave in place
    assert step(data, "cleanup")["status"] == "FAILED"
    assert "nothing was cancelled" in step(data, "cleanup")["detail"]
    assert any(
        "close the Demo position" in text for text in data["details"]["operator_instructions"]
    )
    assert data["outcome"] == "FAILED"


# Plan 19-16: TEST_ONLY live inputs that make the plan snapshot COMPLETE. The real rehearsal has no
# source for margin type, leverage and equity until Phases 21-22, so its snapshot stays INCOMPLETE.
COMPLETE_SNAPSHOT_INPUTS: dict[str, Any] = {
    "margin_type": "ISOLATED",
    "leverage": 3,
    "equity_used": Decimal("1000"),
}


def _to_states(data: dict[str, Any]) -> list[str]:
    return [t["to"] for t in data["details"]["protection_flow"]["transitions"]]


def test_fill_scenario_completes_through_the_coordinator_with_a_complete_snapshot(
    tmp_path: Path,
) -> None:
    """The fill scenario no longer builds a FillEvent from a position view: the coordinator
    detects the fill by REST, places the stop after it, confirms it, then adds TP1 and TP2."""
    adapter = FakeDemoAdapter()
    adapter.fill_on_place = True
    code, data, _, _ = run_flow(
        tmp_path,
        scenario="fill",
        adapter=adapter,
        execute=True,
        snapshot_live_inputs=COMPLETE_SNAPSHOT_INPUTS,
    )
    assert code == dr.EXIT_OK
    placed = [kw for name, kw in adapter.kwargs_log if name == "place_algo_protective"]
    by_type = {(kw["type"], kw["close_position"]): kw for kw in placed}
    sl = by_type[("STOP_MARKET", True)]
    tp1 = by_type[("TAKE_PROFIT_MARKET", False)]
    tp2 = by_type[("TAKE_PROFIT_MARKET", True)]
    assert sl["quantity"] is None
    assert tp1["reduce_only"] is True
    assert tp1["quantity"] == Decimal("0.002")  # floor(0.004 * 0.5 / 0.001) * 0.001
    assert tp2["quantity"] is None and tp2["reduce_only"] in (None, False)
    assert len(placed) == 3  # SL, TP1, TP2 once each, all placed after the fill (D-10)
    assert adapter.calls.index("place_entry") < adapter.calls.index("place_algo_protective")
    assert [kw["type"] for kw in placed][0] == "STOP_MARKET", "the stop comes first"
    assert "cancel_algo_order" not in adapter.calls
    assert "place_market_close" not in adapter.calls
    echoes = data["details"]["leg_echoes"]
    assert sorted(e["order_type"] for e in echoes) == [
        "STOP_MARKET",
        "TAKE_PROFIT_MARKET",
        "TAKE_PROFIT_MARKET",
    ]
    assert any("close the Demo position" in t for t in data["details"]["operator_instructions"])
    assert step(data, "fill_wait")["status"] == "PASSED"
    assert step(data, "protection_stop")["status"] == "PASSED"
    assert step(data, "attach_protectives")["status"] == "PASSED"
    assert data["details"]["protection_flow"]["final_state"] == "COMPLETE"
    assert _to_states(data) == ["AWAITING_FILL", "UNPROTECTED", "PROTECTED", "COMPLETE"]
    assert data["details"]["live_context"]["plan_snapshot_status"] == "COMPLETE"
    assert "position-view:" not in json.dumps(data)  # no REST-synthetic trade id any more
    assert "fill_event" not in data["details"]
    assert data["outcome"] == "COMPLETE"
    assert data["attestation_map"]["1"]["status"] == "OBSERVED"
    assert data["attestation_map"]["2"]["status"] == "OBSERVED_ACCEPTANCE_ONLY"


def test_fill_scenario_with_the_incomplete_snapshot_is_tp_unavailable_a_known_gap(
    tmp_path: Path,
) -> None:
    """With real data the snapshot is INCOMPLETE (margin type, leverage and equity unknown), so
    the stop is placed and kept and no take profit is placed: recorded as a gap, never a pass."""
    adapter = FakeDemoAdapter()
    adapter.fill_on_place = True
    code, data, _, _ = run_flow(tmp_path, scenario="fill", adapter=adapter, execute=True)
    assert code == dr.EXIT_OK
    placed = [kw for name, kw in adapter.kwargs_log if name == "place_algo_protective"]
    assert [(kw["type"], kw["close_position"]) for kw in placed] == [("STOP_MARKET", True)]
    assert "place_market_close" not in adapter.calls
    assert "cancel_algo_order" not in adapter.calls
    assert step(data, "fill_wait")["status"] == "PASSED"
    assert step(data, "protection_stop")["status"] == "PASSED"
    attach = step(data, "attach_protectives")
    assert attach["status"] == "NOT_REHEARSED"
    assert "known gap" in attach["detail"] and "INCOMPLETE" in attach["detail"]
    assert data["details"]["protection_flow"]["final_state"] == "TP_UNAVAILABLE"
    assert _to_states(data) == ["AWAITING_FILL", "UNPROTECTED", "PROTECTED", "TP_UNAVAILABLE"]
    assert data["details"]["live_context"]["plan_snapshot_status"] == "INCOMPLETE"
    alerts = data["details"]["critical_alerts"]
    assert [a["event"] for a in alerts] == ["TP_UNAVAILABLE"]
    assert any("close the Demo position" in t for t in data["details"]["operator_instructions"])
    assert data["outcome"] == "COMPLETE_WITH_GAPS"
    assert data["attestation_map"]["1"]["status"] == "NOT_OBSERVED"


def test_fill_scenario_unfilled_entry_ends_no_fill_after_the_cancel(tmp_path: Path) -> None:
    adapter = FakeDemoAdapter()
    code, data, _, _ = run_flow(tmp_path, scenario="fill", adapter=adapter, execute=True)
    assert code == dr.EXIT_OK
    assert "cancel_normal_order" in adapter.calls
    assert "place_algo_protective" not in adapter.calls  # nothing is placed before a fill
    assert "cancel_algo_order" not in adapter.calls
    assert step(data, "fill_wait")["status"] == "NOT_REHEARSED"
    assert step(data, "attach_protectives")["status"] == "NOT_REHEARSED"
    assert data["details"]["protection_flow"]["final_state"] == "ENTRY_ENDED_NO_FILL"
    assert _to_states(data) == ["AWAITING_FILL", "ENTRY_ENDED_NO_FILL"]
    assert step(data, "account_clean")["status"] == "PASSED"
    assert data["outcome"] == "COMPLETE_WITH_GAPS"
    assert data["attestation_map"]["1"]["status"] == "NOT_OBSERVED"


def test_fill_scenario_with_a_rejected_stop_closes_by_market_and_fails(tmp_path: Path) -> None:
    """B5: a definitively rejected stop after a fill is never resent; the coordinator closes the
    position through the guarded adapter (a mutating method) and the run is FAILED."""
    from binance_sdk_derivatives_trading_usds_futures import BadRequestError

    adapter = FakeDemoAdapter()
    adapter.fill_on_place = True
    adapter.raise_on["place_algo_protective"] = BadRequestError(
        error_message="Order would immediately trigger.", status_code=-2021
    )
    code, data, _, _ = run_flow(
        tmp_path,
        scenario="fill",
        adapter=adapter,
        execute=True,
        snapshot_live_inputs=COMPLETE_SNAPSHOT_INPUTS,
    )
    assert code == dr.EXIT_FAILED
    assert data["outcome"] == "FAILED"
    assert adapter.calls.count("place_algo_protective") == 1, "a rejected stop is never resent"
    assert "place_market_close" in adapter.calls
    assert adapter.position_amt == Decimal("0")
    assert step(data, "protection_stop")["status"] == "FAILED"
    assert step(data, "attach_protectives")["status"] == "NOT_REHEARSED"
    assert data["details"]["protection_flow"]["final_state"] == "FLAT"
    assert "CLOSE_REQUIRED" in _to_states(data)
    assert [a["event"] for a in data["details"]["critical_alerts"]] == ["CLOSE_REQUIRED"]
    assert [o["type"] for o in data["exchange_orders"]] == [
        "EntryPlacementResult",
        "MarketCloseResult",
    ]


def test_the_dry_run_fill_scenario_attaches_nothing(tmp_path: Path) -> None:
    code, data, adapter, _ = run_flow(tmp_path, scenario="fill")
    assert code == dr.EXIT_OK
    assert adapter.mutating_calls() == []
    assert step(data, "fill_wait")["status"] == "SKIPPED_DRY_RUN"
    assert step(data, "attach_protectives")["status"] == "NOT_REHEARSED"
    assert "dry run" in step(data, "attach_protectives")["detail"]
    assert "protection_flow" not in data["details"]
    assert data["exchange_orders"] == []
    assert "place_market_close" not in [p["method"] for p in data["planned_requests"]]


def test_exchange_failure_is_recorded_honestly(tmp_path: Path) -> None:
    adapter = FakeDemoAdapter()
    adapter.raise_on["place_entry"] = ValueError("secret " + FAKE_SECRET)
    code, data, _, _ = run_flow(tmp_path, scenario="far", adapter=adapter, execute=True)
    assert code == dr.EXIT_FAILED
    assert data["outcome"] == "FAILED"
    assert data["exchange_orders"] == []
    types = {(f["step"], f["exception_type"]) for f in data["failures"]}
    assert ("place_entry", "ValueError") in types
    text = json.dumps(data)
    assert FAKE_SECRET not in text and "secret " not in text


def test_sdk_error_code_and_text_are_recorded_but_other_errors_stay_type_only(
    tmp_path: Path,
) -> None:
    """A Binance 400 records its code and public text; a plain error records no detail."""
    from binance_sdk_derivatives_trading_usds_futures import BadRequestError

    adapter = FakeDemoAdapter()
    adapter.raise_on["place_entry"] = BadRequestError(
        error_message="Order would immediately trigger.", status_code=-2021
    )
    _, data, _, _ = run_flow(tmp_path, scenario="far", adapter=adapter, execute=True)
    entry = next(f for f in data["failures"] if f["step"] == "place_entry")
    assert entry["exception_type"] == "BadRequestError"
    assert entry["message"] == "binance code -2021: Order would immediately trigger."

    (tmp_path / "plain").mkdir()
    adapter = FakeDemoAdapter()
    adapter.raise_on["place_entry"] = ValueError("secret " + FAKE_SECRET)
    _, data, _, _ = run_flow(tmp_path / "plain", scenario="far", adapter=adapter, execute=True)
    entry = next(f for f in data["failures"] if f["step"] == "place_entry")
    assert "message" not in entry


async def test_enablement_is_in_process_only() -> None:
    adapter = FakeDemoAdapter()
    adapter.raise_when_symbol_none = RuntimeError("account-wide read failed")
    channel = FakeApprovalChannel(script=approve_script())
    ctx = make_ctx(adapter, channel, mode=dr.RunMode.EXECUTE)
    with pytest.raises(RuntimeError):
        await dr.run_rehearsal(ctx)
    assert ctx.controller is not None
    assert ctx.controller.is_disabled
    types = [e.event_type for e in ctx.journal.events]
    assert types.count("LIVE_ORDERS_ENABLED") == 1
    assert types.count("LIVE_ORDERS_DISABLED") == 1
    assert LiveEnablementController(journal=ctx.journal).is_disabled
    assert adapter.mutating_calls() == []


# --------------------------------------------------------------------------- #
# Attestation map and evidence determinism (SR-8).
# --------------------------------------------------------------------------- #


def test_attestation_map_covers_six_items(tmp_path: Path) -> None:
    code, data, _, _ = run_flow(tmp_path, scenario="taps")
    assert code == dr.EXIT_OK
    attest = data["attestation_map"]
    assert sorted(attest) == ["1", "2", "3", "4", "5", "6"]
    assert attest["1"]["status"] == "NOT_OBSERVED"
    assert attest["2"]["status"] == "NOT_OBSERVED"
    assert attest["3"]["status"] == "NOT_OBSERVED"
    assert "Phase 18" in attest["3"]["detail"]
    assert attest["4"]["status"] == "HUMAN_ONLY"
    assert attest["5"]["status"] == "OBSERVED"
    assert attest["6"]["status"] == "OBSERVED_WITH_DEGRADED"
    assert "ws_connection_state" in attest["6"]["detail"]
    assert "db_writes" in attest["6"]["detail"]


def test_evidence_is_deterministic(tmp_path: Path) -> None:
    runs = []
    for name in ("a", "b"):
        folder = tmp_path / name
        folder.mkdir()
        code, _, _, _ = run_flow(folder, scenario="far")
        assert code == dr.EXIT_OK
        files = list(folder.glob("*.json"))
        assert len(files) == 1
        runs.append((files[0].name, files[0].read_bytes()))
    assert runs[0] == runs[1]
    data = json.loads(runs[0][1].decode("utf-8"))
    assert data["mode"] == "DRY_RUN"
    assert data["exchange_orders"] == []
    assert [p["method"] for p in data["planned_requests"]][:2] == [
        "place_entry",
        "cancel_normal_order",
    ]
    assert "place_algo_protective" not in [p["method"] for p in data["planned_requests"]]
    planned_entry = data["planned_requests"][0]["request"]
    assert planned_entry["time_in_force"] == "GTD"
    assert isinstance(planned_entry["good_till_date"], int)
    assert step(data, "place_entry")["status"] == "SKIPPED_DRY_RUN"


# --------------------------------------------------------------------------- #
# Plan 19-13: the live placement context and the NOT_CONFIGURED abort.
# --------------------------------------------------------------------------- #


def test_derived_plan_hash_is_the_planners_hash_and_the_quantity_fields_agree() -> None:
    from src.core.planner import plan_hash_from_fields
    from src.execution.binding import recompute_plan_hash

    for scenario in ("far", "fill"):
        plan = _derive(scenario)
        trade_plan = plan.trade_plan
        assert trade_plan.plan_hash == recompute_plan_hash(trade_plan)
        assert trade_plan.plan_hash == plan_hash_from_fields(
            signal_id=trade_plan.signal_id,
            entry_min_price=trade_plan.entry_min_price,
            entry_max_price=trade_plan.entry_max_price,
            stop_loss_price=trade_plan.stop_loss_price,
            take_profit_json=trade_plan.take_profit_json,
            invalidation_rule_json=trade_plan.invalidation_rule_json,
            expiry_utc=trade_plan.expiry_utc,
        )
        assert (
            trade_plan.suggested_quantity
            == trade_plan.quantity_before_rounding
            == trade_plan.quantity_after_rounding
            == plan.quantity
        )
        assert json.loads(trade_plan.invalidation_rule_json) == {
            "basis": "CANDLE_CLOSE",
            "level": str(plan.stop_loss),
        }


async def test_build_live_context_binds_to_the_derived_plan() -> None:
    from src.execution.binding import bind_plan
    from src.execution.live_context import LivePlacementContext
    from src.execution.protection import ProtectionCoordinator
    from src.reconcile.safe_mode import SafeModeController
    from src.risk.types import ConstraintSnapshot

    from tests.support.intent_store_fakes import InMemoryExecutionIntentStore

    adapter = FakeDemoAdapter()
    ctx = make_ctx(adapter, FakeApprovalChannel())
    plan = _derive("far")
    filters = btc_filters()
    constraints = ConstraintSnapshot(
        symbol="BTCUSDT",
        price_tick_size=filters.price_tick_size,
        quantity_step_size=filters.quantity_step_size,
        min_quantity=filters.min_quantity,
        min_notional=filters.min_notional,
        metadata_observed_at_utc=SERVER_NOW,
    )
    live = await dr.build_live_context(
        ctx,
        plan,
        filters,
        constraints,
        SERVER_NOW,
        safe_mode=SafeModeController(adapter=ctx.guarded, journal=ctx.journal),
        intent_store=InMemoryExecutionIntentStore(),
    )
    assert isinstance(live, LivePlacementContext)
    assert live.signal.signal_id == plan.signal_id
    assert (live.signal.symbol, live.signal.direction) == ("BTCUSDT", "LONG")
    assert live.signal.strategy_version == plan.parameter_set.strategy_version
    assert live.signal.parameter_set_hash == plan.parameter_set.parameter_set_hash
    assert live.plan_constraint_snapshot.working_type == "MARK_PRICE"
    assert live.plan_constraint_snapshot.trade_plan_id == plan.trade_plan.trade_plan_id
    assert live.execution_limits == test_limits.test_only_execution_limits()
    assert isinstance(live.protection_registry, ProtectionCoordinator)
    assert live.protection_registry.blocks_new_entries() is False
    assert live.tp1_quantity_fraction == TP1_QUANTITY_FRACTION
    # the latest CLOSED 1h bar (the forming one is skipped), read through the guarded adapter
    assert live.latest_closed_bar_close == MARK
    assert "klines" in adapter.calls
    # the margin is the larger of the ratified drift limits
    drift = dr.load_drift_limits(dr.DEFAULT_LIMITS_FILE)
    assert live.gtd_clock_margin == timedelta(
        milliseconds=max(drift.ahead_limit_ms, drift.behind_limit_ms)
    )
    # the plan is bound: hash, signal, symbol and side all agree
    params = plan.parameter_set
    verdict = bind_plan(
        trade_plan=plan.trade_plan,
        signal=live.signal,
        callback_plan_hash=plan.trade_plan.plan_hash,
        approval_request_hash=plan.trade_plan.plan_hash,
        approval_strategy_version=params.strategy_version,
        approval_parameter_set_id=params.parameter_set_id,
        approval_parameter_set_hash=params.parameter_set_hash,
        plan_snapshot_symbol=live.plan_constraint_snapshot.symbol,
        plan_snapshot_trade_plan_id=live.plan_constraint_snapshot.trade_plan_id,
        caller_symbol="BTCUSDT",
        caller_side="LONG",
        approval_quantity=plan.trade_plan.quantity_after_rounding,
    )
    assert verdict.ok is True
    assert adapter.mutating_calls() == []


async def test_a_bar_close_that_cannot_be_read_is_none_not_a_guess() -> None:
    adapter = FakeDemoAdapter()
    ctx = make_ctx(adapter, FakeApprovalChannel())
    adapter.raise_on["klines"] = RuntimeError("boom")
    assert await dr._latest_closed_bar_close(ctx, SERVER_NOW) is None


def test_the_alert_sink_records_the_alert_and_an_operator_instruction() -> None:
    ctx = make_ctx(FakeDemoAdapter(), FakeApprovalChannel())
    dr.RehearsalAlertSink(ctx).critical(
        event="UNPROTECTED_POSITION",
        plan_hash="h" * 64,
        symbol="BTCUSDT",
        reason="STOP_NOT_CONFIRMED",
        now_utc=SERVER_NOW,
    )
    alerts = ctx.recorder.details["critical_alerts"]
    assert alerts[0]["event"] == "UNPROTECTED_POSITION"
    assert alerts[0]["symbol"] == "BTCUSDT"
    assert any("UNPROTECTED_POSITION" in t for t in ctx.recorder.details["operator_instructions"])


def test_the_read_passthroughs_are_allowed_in_dry_run_and_bind_the_real_signature() -> None:
    adapter = FakeDemoAdapter()
    ctx = make_ctx(adapter, FakeApprovalChannel(), mode=dr.RunMode.DRY_RUN)
    import asyncio

    reading = asyncio.run(ctx.guarded.get_mark_price(symbol="BTCUSDT"))
    assert reading.mark_price == MARK
    assert adapter.calls == ["get_mark_price"]
    assert ctx.guarded.mutating_attempts == 0


async def test_committed_not_configured_limits_abort_before_any_mutation() -> None:
    """D-07 / D-13 / T-19-34: the committed file has no value, so the run stops honestly."""
    adapter = FakeDemoAdapter()
    channel = FakeApprovalChannel(script=approve_script())
    ctx = make_ctx(adapter, channel, mode=dr.RunMode.EXECUTE, scenario="far")
    ctx.execution_limits = None  # the default: load the committed config/execution file
    with pytest.raises(dr.RehearsalAbort, match="LIMITS_NOT_CONFIGURED"):
        await dr.run_rehearsal(ctx)
    assert ctx.guarded.mutating_attempts == 0
    assert adapter.mutating_calls() == []
    failed = [s for s in ctx.recorder.steps if s["name"] == "execution_limits"]
    assert failed and failed[-1]["status"] == dr.STEP_FAILED
    assert "LIMITS_NOT_CONFIGURED" in failed[-1]["detail"]
    for key in (
        "protection.max_unprotected_ms",
        "protection.entry_terminal_timeout_ms",
        "protection.entry_unknown_grace_ms",
        "protection.emergency_close_poll_timeout_ms",
        "pre_placement.min_remaining_validity_seconds",
        "pre_placement.max_mark_price_age_ms",
    ):
        assert key in failed[-1]["detail"]
    # nothing else ran: no approval was requested, no channel opened
    assert channel.opened is False
    assert channel.sent == []


@pytest.mark.parametrize("scenario", ["far", "fill"])
def test_committed_limits_end_the_main_run_as_aborted_no_order(
    tmp_path: Path, scenario: str
) -> None:
    code, data, adapter, chan = run_flow(
        tmp_path, scenario=scenario, execute=True, committed_limits=True
    )
    assert code == dr.EXIT_ABORTED
    assert data["outcome"] == "ABORTED_NO_ORDER"
    assert adapter.mutating_calls() == []
    assert data["exchange_orders"] == []
    assert chan.sent == []
    status = step(data, "execution_limits")
    assert status["status"] == "FAILED"
    assert "LIMITS_NOT_CONFIGURED" in status["detail"]


def test_one_unset_limit_names_only_that_key(tmp_path: Path) -> None:
    code, data, adapter, _ = run_flow(
        tmp_path,
        scenario="far",
        execute=True,
        execution_limits=test_limits.test_only_execution_limits(max_mark_price_age_ms=None),
    )
    assert code == dr.EXIT_ABORTED
    detail = step(data, "execution_limits")["detail"]
    assert "pre_placement.max_mark_price_age_ms" in detail
    assert "protection.max_unprotected_ms" not in detail
    assert adapter.mutating_calls() == []


def test_the_taps_scenario_needs_no_execution_limits(tmp_path: Path) -> None:
    code, data, adapter, _ = run_flow(tmp_path, scenario="taps", committed_limits=True)
    assert code == dr.EXIT_OK
    assert adapter.mutating_calls() == []
    assert not [s for s in data["steps"] if s["name"] == "execution_limits"]


def test_the_dry_run_far_scenario_reads_the_mark_price_and_still_sends_nothing(
    tmp_path: Path,
) -> None:
    code, data, adapter, _ = run_flow(tmp_path, scenario="far")
    assert code == dr.EXIT_OK
    assert "get_mark_price" in adapter.calls
    assert adapter.mutating_calls() == []
    assert data["exchange_orders"] == []
    assert step(data, "execution_limits")["status"] == "PASSED"
    assert data["details"]["live_context"]["working_type"] == "MARK_PRICE"


def test_wr01_issue_approval_stores_the_plan_quantity_on_both_roles() -> None:
    """D078: every PENDING approval of the rehearsal carries the issued plan's quantity."""
    from src.domain.enums import ApprovalAction

    plan = _derive("far")
    for role, action in (("approve", ApprovalAction.APPROVE), ("skip", ApprovalAction.SKIP_USER)):
        ctx = make_ctx(FakeDemoAdapter(), FakeApprovalChannel())
        issued = dr.issue_approval(ctx, plan, role=role, action=action)
        assert issued.approval.approved_quantity == plan.trade_plan.quantity_after_rounding, role
        assert issued.approval.approved_quantity is not None
