"""The composed live process on in-memory stores, for the end-to-end tracer (plan 24-27B).

TEST_ONLY: every number is a made-up value (the BTCUSDT filters, the prices, the commission, the
equity of the recorded Demo account answers); none is a Binance fact or a chosen threshold. No
production module imports this file (tests/test_no_unratified_defaults.py enforces it).

Everything the live process builds is REAL: `build_wiring` constructs the stores' consumers, the
REST gate and drift guard, the signed adapter (over a recorded-Demo SDK stand-in for the account,
configuration and bracket reads), the commission cache, equity, bracket and day-risk services, the
desk, the sender, the runner, the confirm flow, the execution service, the producer, the
coordinator, the closer, the reconcile loop, the stream router and the fill fan-out, the health
producer and the scheduler. The edges that are fakes:

* the database: `tests/support/live_store_set.py` (in-memory doubles of the Pg stores);
* the exchange orders, prices and snapshots: the Binance-semantics fake adapter, reached through
  `ComposedExchangeEdge` (the signed adapter's place_entry, place_algo_protective, queries, cancels
  and snapshots; every other read stays on the real adapter);
* the PTB bot, the clock and the sleep.

`make_composed_rig(tmp_path)` returns a `ComposedRig`; `await rig.prepare()` completes the assembly
the way start step 4 does (a durable in-memory SAFE_MODE store, a DISABLED enablement controller),
enables entries and primes the readings the placement needs.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import sqlalchemy
from src.adapters.binance_client import Environment
from src.adapters.binance_public import MarkPriceReading
from src.adapters.binance_ratelimit_gate import GateRecoveryStatus
from src.adapters.binance_usdm import CommissionRates
from src.adapters.binance_userdata_events import parse_stream_message
from src.adapters.binance_userdata_supervisor import TrustedEvent
from src.adapters.telegram_callbacks import DispatchResult
from src.domain.enums import KillGateState, OrderRole
from src.domain.registry import load_parameter_set
from src.execution.enablement import LiveEnablementController
from src.execution.order_ids import derive_client_order_id
from src.live.exchange import ExchangeBundle
from src.live.risk_inputs import backfill_day_risk
from src.live.signal_source import (
    SCENARIO_FILL,
    DemoSmokeSignalSource,
    SignalRequest,
)
from src.live.wiring import CompleteLiveWiring, LiveAssembly, LiveStoreSet, build_wiring
from src.live.wiring_parts import LiveBotProxy
from src.ops.health import ALL_CHECK_NAMES, HealthCheckResult, run_health_checks
from src.reconcile.safe_mode import SafeModeController

from tests.shadow_fakes import (
    AUTHORIZED_USER_IDS,
    CHAT_ID,
    T0,
    USER_ID,
    FakeBot,
    assert_live_text,
    make_callback_update,
)
from tests.support.day_risk_fakes import ScriptedDayRiskReader
from tests.support.execution_limits import test_only_execution_limits
from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.fault_edge import FaultEdge
from tests.support.limits import test_only_binance_limits
from tests.support.live_risk_rig import btc_filters
from tests.support.live_store_set import MemoryStoreHandles, build_memory_stores
from tests.support.live_wiring_rig import (
    TEST_ONLY_SYMBOLS,
    make_config,
)
from tests.support.margin_guard_fakes import CompositeRest
from tests.support.protection_doubles import lot_filters_for_tests
from tests.support.userdata_frames import order_trade_update_frame
from tests.support.virtual_time import VirtualTime

D = Decimal
TEST_ONLY_OPERATOR = "operator_alpha"
TEST_ONLY_SYMBOL = "BTCUSDT"
TEST_ONLY_MARK = D("50000")
TEST_ONLY_STREAM_ORDER_ID = 8_000_000_778
TEST_ONLY_MAKER = D("0.0002")
TEST_ONLY_TAKER = D("0.0004")

# The signed-adapter names served by the Binance-semantics fake (orders, prices, snapshots).
_FAKE_SERVED = frozenset(
    {
        "place_entry",
        "place_algo_protective",
        "place_market_close",
        "query_order_by_client",
        "query_algo_order_by_client",
        "cancel_normal_order",
        "cancel_algo_order",
        "snapshot_open_normal_orders",
        "snapshot_open_algo_orders",
        "snapshot_positions",
        "get_mark_price",
        "get_last_price",
        "get_position_mode",
        "symbol_lot_filters",
        "error_facts",
    }
)


class ComposedExchangeEdge:
    """The signed adapter of the tracer (see the module docstring).

    The gate and the drift guard attributes are the REAL adapter's, so `check_wiring` sees the
    production links; calls are routed by name.
    """

    def __init__(
        self,
        *,
        real: Any,
        fake: BinanceSemanticsFakeAdapter,
        day_reader: ScriptedDayRiskReader,
    ) -> None:
        self._real = real
        self._fake = fake
        self._day_reader = day_reader
        self._rest_gate = real._rest_gate
        self._drift_guard = real._drift_guard
        self.commission_calls = 0

    async def exchange_info(self, symbols: Any = None) -> list[Any]:
        return [btc_filters()]

    async def user_commission_rate(self, symbol: str) -> CommissionRates:
        self.commission_calls += 1
        return CommissionRates(
            symbol=symbol, maker_rate=TEST_ONLY_MAKER, taker_rate=TEST_ONLY_TAKER
        )

    async def user_trades_in_window(self, **kwargs: Any) -> Any:
        return await self._day_reader.user_trades_in_window(**kwargs)

    async def income_in_window(self, **kwargs: Any) -> Any:
        return await self._day_reader.income_in_window(**kwargs)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        if name in _FAKE_SERVED:
            return getattr(self._fake, name)
        return getattr(self._real, name)


class StartableFakeApplication:
    """A PTB application stand-in the runner can start and stop (plan 24-29: the start sequence).

    It registers handlers, polls nothing and carries the rig's FakeBot as its bot.
    """

    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self.handlers: list[Any] = []
        self.error_handlers: list[Any] = []
        self.started = False
        self.updater = SimpleNamespace(start_polling=self._start_polling, stop=self._stop_polling)

    def add_handler(self, handler: Any) -> None:
        self.handlers.append(handler)

    def add_error_handler(self, handler: Any) -> None:
        self.error_handlers.append(handler)

    async def initialize(self) -> None:
        return None

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False

    async def shutdown(self) -> None:
        return None

    async def _start_polling(self, **_kwargs: Any) -> None:
        return None

    async def _stop_polling(self) -> None:
        return None


class FakePublic:
    """The public market-data reader (`mark_price`, `last_price`, `exchange_info`)."""

    def __init__(self, fake: BinanceSemanticsFakeAdapter, rest_gate: Any) -> None:
        self._fake = fake
        self._rest_gate = rest_gate

    async def mark_price(self, symbol: str) -> MarkPriceReading:
        return await self._fake.get_mark_price(symbol=symbol)

    async def exchange_info(self, symbols: Any = None) -> list[Any]:
        return [btc_filters()]

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)


@dataclass
class ComposedRig:
    """Everything one tracer test touches."""

    assembly: LiveAssembly
    clock: VirtualTime
    bot: FakeBot
    fake: BinanceSemanticsFakeAdapter
    stores: LiveStoreSet
    memory: MemoryStoreHandles
    edge: ComposedExchangeEdge
    day_reader: ScriptedDayRiskReader
    source: DemoSmokeSignalSource
    wiring: CompleteLiveWiring | None = None
    enablement: LiveEnablementController | None = None
    safe_mode: SafeModeController | None = None
    # Plan 25-02: the test-only fault objects installed at the three production seams (or None).
    faults: FaultEdge | None = None
    sdk_faults: Any = None
    store_faults: Any = None

    # ---- bring-up -------------------------------------------------------------------------- #

    def set_prices(self, mark: Decimal = TEST_ONLY_MARK) -> None:
        now = self.clock.now()
        self.fake.now_utc = now
        self.fake.set_mark_price(TEST_ONLY_SYMBOL, mark, now - timedelta(seconds=1))
        self.fake.set_last_price(TEST_ONLY_SYMBOL, mark, now - timedelta(seconds=1))

    async def prepare(self) -> CompleteLiveWiring:
        """Complete the assembly, enable entries and prime the readings placement needs."""
        assembly = self.assembly
        # Start step 2: the first-install initialization of the gate state file, then the restore.
        assembly.exchange.gate_store.initialize(now_utc=T0, operator_id=TEST_ONLY_OPERATOR)
        assert assembly.exchange.gate.restore() is GateRecoveryStatus.RESTORED_DURABLE
        controller = SafeModeController(
            adapter=assembly.exchange.adapter,  # type: ignore[arg-type]
            journal=assembly.stores.journal,
            state_store=assembly.stores.safe_mode_state,
            on_enter=assembly.alerts.safe_mode_observer,
        )
        enablement = LiveEnablementController(journal=assembly.stores.journal)
        enablement.enable(
            operator_id=TEST_ONLY_OPERATOR,
            now_utc=T0,
            health_verdict=run_health_checks(
                results=[
                    HealthCheckResult(check_name=n, status="PASS", detail="ok", observed_at_utc=T0)
                    for n in ALL_CHECK_NAMES
                ]
            ),
            kill_gate_state=KillGateState.WITHIN_BUDGET,
        )
        self.safe_mode, self.enablement = controller, enablement
        wiring = assembly.complete(safe_mode=controller, enablement=enablement)
        self.wiring = wiring
        # The start sequence's recovery step restores the (empty) set of plans; until then the
        # coordinator blocks every new entry (restore_required=True).
        wiring.coordinator.restore([], now_utc=self.clock.now())
        self.set_prices()
        await wiring.commission.refresh_due()
        await backfill_day_risk(wiring.day_risk, self.clock.now())
        await wiring.day_risk.evaluate(now_utc=self.clock.now(), exposure=False)
        return wiring

    # ---- driving --------------------------------------------------------------------------- #

    async def derive_request(self, scenario: str = SCENARIO_FILL) -> SignalRequest:
        """One Demo smoke request from the primed readings, queued on the source.

        Sized from the LIVE account equity (the same equity the producer sizes from at placement),
        so the approved quantity is the one the placement returns.
        """
        assert self.wiring is not None
        await self.wiring.equity.refresh()
        now = self.clock.now()
        resolved = self.wiring.equity.resolve(
            risk_rate=self.assembly.params["risk_rate"], now_utc=now
        )
        assert resolved.equity is not None
        return self.source.submit(
            scenario=scenario,
            filters=btc_filters(),
            mark_price=TEST_ONLY_MARK,
            commission=CommissionRates(
                symbol=TEST_ONLY_SYMBOL, maker_rate=TEST_ONLY_MAKER, taker_rate=TEST_ONLY_TAKER
            ),
            observed_at=now,
            latest_closed_bar_close=now.replace(minute=0, second=0, microsecond=0),
            account_equity=resolved.equity,
        )

    async def press(self, prefix: str, short_id: str, *, query_id: str) -> DispatchResult:
        """One authorized button press through the runner's one `on_callback` handler."""
        assert self.wiring is not None
        update = make_callback_update(
            data=f"{prefix}:{short_id}",
            chat_id=CHAT_ID,
            query_id=query_id,
            message_chat_id=CHAT_ID,
            from_user_id=USER_ID,
            message_id=1,
            chat_type="private",
        )
        return cast(DispatchResult, await self.wiring.runner.handler(update, None))

    def entry_id(self, request: SignalRequest) -> str:
        return derive_client_order_id(plan_hash=request.plan.plan_hash, role=OrderRole.ENTRY.value)

    def route(self, frame: dict[str, Any]) -> Any:
        """Parse and route one SYNTHETIC frame through the composed stream's real router."""
        assert self.wiring is not None
        received = self.clock.now()
        outcome = parse_stream_message(frame, observed_at_utc=received)
        return self.wiring.stream.router.route(
            TrustedEvent(
                outcome=outcome,
                received_at_utc=received,
                connection_epoch=1,
                after_gap=False,
            )
        )

    def trade_frame(self, request: SignalRequest, quantity: str) -> dict[str, Any]:
        return order_trade_update_frame(
            c=self.entry_id(request), i=TEST_ONLY_STREAM_ORDER_ID, t=902, l=quantity, z=quantity
        )


def make_composed_rig(
    tmp_path: Path,
    *,
    stores: tuple[LiveStoreSet, MemoryStoreHandles] | None = None,
    clock: VirtualTime | None = None,
    fake: BinanceSemanticsFakeAdapter | None = None,
    session_id: str = "composed-rig",
    faults: FaultEdge | None = None,
    sdk_faults: Any = None,
    store_faults: Any = None,
) -> ComposedRig:
    """One composed process; a restart passes the SAME `stores`, `clock` and `fake` (plan 24-29).

    Plan 25-02 (test-only, D-08): `faults` is installed inside `edge()` around the composed edge and
    FakePublic (the `exchange_edge` seam), `sdk_faults` wraps the rig's own `sdk_factory` (the
    `sdk_factory` seam) and `store_faults` wraps the store set before `build_wiring(stores=...)`
    (the `stores` seam). Every default keeps the existing callers unchanged.
    """
    clock = clock if clock is not None else VirtualTime(T0)
    if fake is None:
        fake = BinanceSemanticsFakeAdapter(now_utc=clock.now(), enforce_flat_stop_rejection=True)
        fake.set_lot_filters(TEST_ONLY_SYMBOL, lot_filters_for_tests())
    day_reader = ScriptedDayRiskReader()
    rest = CompositeRest(clock=None)
    store_set, memory = stores if stores is not None else build_memory_stores()
    holder: dict[str, ComposedExchangeEdge] = {}

    def sdk_factory(**kwargs: Any) -> Any:
        return SimpleNamespace(
            environment=kwargs["environment"],
            surfaces=kwargs["surfaces"],
            client=SimpleNamespace(rest_api=rest),
        )

    def edge(bundle: ExchangeBundle) -> ExchangeBundle:
        composed = ComposedExchangeEdge(real=bundle.adapter, fake=fake, day_reader=day_reader)
        holder["edge"] = composed
        composed_bundle = dataclasses.replace(
            bundle,
            adapter=composed,  # type: ignore[arg-type]
            public=FakePublic(fake, bundle.gate),  # type: ignore[arg-type]
        )
        if faults is not None:
            return cast(ExchangeBundle, faults.install(composed_bundle))
        return composed_bundle

    config = make_config(tmp_path, mode=Environment.DEMO)
    # The loss bound is raised for the rig only: the rig's presses take 30 virtual seconds.
    config = dataclasses.replace(
        config, limits=test_only_execution_limits(account_max_daily_loss_age_ms=120_000)
    )

    def check_text(text: str) -> None:
        # Cards and confirm prompts (they name the symbol) carry the DEMO mode and the +07/UTC
        # time pairs; the short operator replies of the commands do not.
        if "BTCUSDT" in text:
            assert_live_text(text, "DEMO")

    bot = FakeBot(text_check=check_text)
    parameter_set = load_parameter_set("trend-pullback", "baseline-v5")
    source = DemoSmokeSignalSource(run_id=session_id, parameter_set=parameter_set)
    assembly = build_wiring(
        config=config,
        execution_limits=config.limits,
        binance_limits=test_only_binance_limits(),
        parameter_set=parameter_set,
        clock=clock,
        sleep=clock.sleep,
        sdk_factory=sdk_factory,
        application_factory=lambda: StartableFakeApplication(bot),
        bot=LiveBotProxy(bot),
        engine=sqlalchemy.create_engine("postgresql+psycopg://rig:rig@127.0.0.1:1/rig"),
        repo_root=Path(__file__).resolve().parents[2],
        symbols=TEST_ONLY_SYMBOLS,
        session_id=session_id,
        stores=store_set,
        signal_source=source,
        exchange_edge=edge,
    )
    return ComposedRig(
        assembly=assembly,
        clock=clock,
        bot=bot,
        fake=fake,
        stores=store_set,
        memory=memory,
        edge=holder["edge"],
        day_reader=day_reader,
        source=source,
        faults=faults,
        sdk_faults=sdk_faults,
        store_faults=store_faults,
    )


__all__ = [
    "AUTHORIZED_USER_IDS",
    "TEST_ONLY_MARK",
    "TEST_ONLY_SYMBOL",
    "ComposedExchangeEdge",
    "ComposedRig",
    "FakePublic",
    "StartableFakeApplication",
    "make_composed_rig",
]
