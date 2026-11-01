"""The adapters of the composition root (plan 24-27) and the hand-offs they close.

Covers D092 (the DEMO-only kill-gate rule, journaled on every enable, never in another mode),
D091 (the two health bounds), the lazy startup ports, the signal context book, the positions
reader, the reservation registrar, the SQL of the new `PgExecutionStateStore` reads and the runner
command registration. Everything runs without a database (a socket/connect guard is active).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql
from src.adapters.binance_client import Environment
from src.domain.enums import KillGateState
from src.live.health import LiveHealthThresholds
from src.live.scheduler import TaskEvent
from src.live.wiring import (
    DB_WRITE_MAX_AGE,
    REST_MAX_ERROR_RATE,
    CompleteLiveWiring,
    WiringIncomplete,
)
from src.live.wiring_parts import (
    DEMO_KILL_GATE_RULE_CODE,
    EVENT_DEMO_KILL_GATE_RULE,
    AdapterPositionsReader,
    BotNotBound,
    LateBound,
    LiveBotProxy,
    SignalContextBook,
    make_kill_gate_sources,
    make_reservation_registrar,
    task_event_journal,
)
from src.persistence.execution_state import PgExecutionStateStore

from tests.shadow_fakes import T0
from tests.support.live_wiring_rig import (
    complete_assembly,
    forbid_connections,
    make_assembly,
)


@pytest.fixture(autouse=True)
def _no_connections(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    return forbid_connections(monkeypatch)


class _Executor:
    def __init__(self, value: Any = None) -> None:
        self.value = value
        self.reads = 0

    async def read(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        self.reads += 1
        return fn(*args, **kwargs)


class _SystemState:
    def __init__(self, state: KillGateState | None) -> None:
        self._state = state

    def latest_kill_gate_state(self) -> KillGateState | None:
        return self._state


# --------------------------------------------------------------------------- #
# D092: the kill-gate state source.
# --------------------------------------------------------------------------- #


async def test_demo_treats_the_kill_gate_as_within_budget_and_journals_every_enable() -> None:
    rows: list[Any] = []

    async def record(event: Any) -> None:
        rows.append(event)

    sources = make_kill_gate_sources(
        mode=Environment.DEMO,
        system_state=_SystemState(None),  # type: ignore[arg-type]
        executor=_Executor(),  # type: ignore[arg-type]
        record=record,
        clock=lambda: T0,
    )
    assert await sources.for_enable() is KillGateState.WITHIN_BUDGET
    assert await sources.for_enable() is KillGateState.WITHIN_BUDGET
    assert [r.event_type for r in rows] == [EVENT_DEMO_KILL_GATE_RULE] * 2, "every enable"
    assert DEMO_KILL_GATE_RULE_CODE in rows[0].payload_json
    assert "WITHIN_BUDGET" in rows[0].payload_json


async def test_the_demo_task_source_never_journals_and_never_disables() -> None:
    rows: list[Any] = []

    async def record(event: Any) -> None:
        rows.append(event)

    sources = make_kill_gate_sources(
        mode=Environment.DEMO,
        system_state=_SystemState(None),  # type: ignore[arg-type]
        executor=_Executor(),  # type: ignore[arg-type]
        record=record,
        clock=lambda: T0,
    )
    assert await sources.for_task() is KillGateState.WITHIN_BUDGET
    assert rows == []


@pytest.mark.parametrize("mode", [Environment.LIVE, Environment.TESTNET])
async def test_negative_control_other_modes_never_apply_the_demo_rule(mode: Environment) -> None:
    rows: list[Any] = []

    async def record(event: Any) -> None:
        rows.append(event)

    unevaluated = make_kill_gate_sources(
        mode=mode,
        system_state=_SystemState(None),  # type: ignore[arg-type]
        executor=_Executor(),  # type: ignore[arg-type]
        record=record,
        clock=lambda: T0,
    )
    assert await unevaluated.for_enable() is None, "a start without an evaluated state is refused"
    assert await unevaluated.for_task() is None
    assert rows == []

    evaluated = make_kill_gate_sources(
        mode=mode,
        system_state=_SystemState(KillGateState.INSUFFICIENT_EDGE),  # type: ignore[arg-type]
        executor=_Executor(),  # type: ignore[arg-type]
        record=record,
        clock=lambda: T0,
    )
    assert await evaluated.for_enable() is KillGateState.INSUFFICIENT_EDGE
    assert rows == []


async def test_the_demo_start_enable_reads_the_rule_through_the_startup_port(
    tmp_path: Path,
) -> None:
    handles = make_assembly(tmp_path)
    ports = handles.assembly.startup_ports()
    # Replace only the journal edge (the PostgreSQL write) to observe the rule's row.
    rows: list[Any] = []

    async def record(event: Any) -> None:
        rows.append(event)

    handles.assembly.kill_gate = make_kill_gate_sources(
        mode=Environment.DEMO,
        system_state=handles.assembly.stores.system_state,
        executor=handles.assembly.executor,
        record=record,
        clock=handles.clock,
    )
    assert await ports.kill_gate_state() is KillGateState.WITHIN_BUDGET
    assert [r.event_type for r in rows] == [EVENT_DEMO_KILL_GATE_RULE]


# --------------------------------------------------------------------------- #
# D091: the health bounds.
# --------------------------------------------------------------------------- #


async def test_the_health_thresholds_are_the_d091_bounds(tmp_path: Path) -> None:
    assert REST_MAX_ERROR_RATE == Decimal("3") / Decimal("10")
    assert DB_WRITE_MAX_AGE == timedelta(seconds=60)
    handles = make_assembly(tmp_path)
    wiring = await complete_assembly(handles)
    thresholds: LiveHealthThresholds = wiring.health._thresholds
    assert thresholds.rest_max_error_rate == REST_MAX_ERROR_RATE
    assert thresholds.db_write_max_age == DB_WRITE_MAX_AGE
    assert thresholds.mark_price_max_age == timedelta(
        milliseconds=handles.assembly.limits.stale_feed_max_mark_price_age_ms or 0
    )


async def test_the_observers_are_the_ones_the_scheduler_and_the_health_producer_share(
    tmp_path: Path,
) -> None:
    handles = make_assembly(tmp_path)
    wiring = await complete_assembly(handles)
    assert wiring.health._rest is wiring.rest_errors
    assert wiring.health._db is wiring.db_writes
    assert wiring.health._reconcile is wiring.reconcile_observer
    assert wiring.health._telegram is wiring.telegram_observer
    assert wiring.health._marks is wiring.marks


# --------------------------------------------------------------------------- #
# The startup ports are lazy until the SAFE_MODE controller is loaded.
# --------------------------------------------------------------------------- #


async def test_the_recovery_ports_forward_to_the_completed_wiring(tmp_path: Path) -> None:
    handles = make_assembly(tmp_path)
    ports = handles.assembly.startup_ports(initialize_gate_state=True, operator_id="op")
    assert ports.initialize_gate_state is True and ports.operator_id == "op"
    with pytest.raises(WiringIncomplete):
        _ = ports.recovery.coordinator.restore_complete
    wiring = await complete_assembly(handles)
    assert ports.recovery.coordinator.restore_complete is False, "restore_required=True"
    assert ports.recovery.closer._clock is wiring.closer._clock


async def test_the_startup_ports_are_bound_to_the_composed_objects(tmp_path: Path) -> None:
    handles = make_assembly(tmp_path)
    assembly = handles.assembly
    ports = assembly.startup_ports()
    assert ports.mode is Environment.DEMO
    assert ports.gate is assembly.exchange.gate
    assert ports.gate_store is assembly.exchange.gate_store
    assert ports.recovery.pending_store is assembly.stores.pending_actions
    assert ports.recovery.intent_store is assembly.stores.execution_state
    assert ports.recovery.probe_adapter is assembly.exchange.adapter
    assert ports.spill_directory == assembly.config.spill_dir
    wiring = await complete_assembly(handles)
    assert callable(ports.expire_confirms) and callable(ports.requeue_alerts)
    assert wiring.runner is assembly.wiring.runner


# --------------------------------------------------------------------------- #
# The small adapters.
# --------------------------------------------------------------------------- #


def test_the_signal_context_book_keeps_the_signal_and_the_bar_close_price() -> None:
    book = SignalContextBook()
    plan = SimpleNamespace(trade_plan_id="plan-1")
    signal = SimpleNamespace(signal_id="s-1")
    request = SimpleNamespace(plan=plan, signal=signal, bar_close_price=Decimal("60000"))
    assert book.lookup(plan) is None  # type: ignore[arg-type]
    book.put(request)  # type: ignore[arg-type]
    context = book.lookup(plan)  # type: ignore[arg-type]
    assert context is not None
    assert context.signal is signal
    assert context.latest_closed_bar_close == Decimal("60000")
    assert len(book) == 1


async def test_the_positions_reader_sums_the_absolute_amount_and_counts_orders() -> None:
    class Adapter:
        async def snapshot_positions(self) -> list[Any]:
            return [
                SimpleNamespace(symbol="BTCUSDT", position_amt=Decimal("-0.5")),
                SimpleNamespace(symbol="BTCUSDT", position_amt=Decimal("0.25")),
                SimpleNamespace(symbol="ETHUSDT", position_amt=Decimal("3")),
            ]

        async def snapshot_open_normal_orders(self) -> list[Any]:
            return [SimpleNamespace(symbol="BTCUSDT"), SimpleNamespace(symbol="ETHUSDT")]

    reader = AdapterPositionsReader(Adapter())
    assert await reader.open_position_quantity("BTCUSDT") == Decimal("0.75")
    assert await reader.open_position_quantity("SOLUSDT") == Decimal("0")
    assert await reader.open_entry_order_count("BTCUSDT") == 1


async def test_the_positions_reader_raises_on_an_unusable_snapshot() -> None:
    class Adapter:
        async def snapshot_positions(self) -> Any:
            return None

        async def snapshot_open_normal_orders(self) -> Any:
            return "bad"

    reader = AdapterPositionsReader(Adapter())
    with pytest.raises(ValueError):
        await reader.open_position_quantity("BTCUSDT")
    with pytest.raises(ValueError):
        await reader.open_entry_order_count("BTCUSDT")


def test_the_reservation_registrar_writes_the_margin_trio_from_the_money_block() -> None:
    captured: list[Any] = []

    class Store:
        def register_request(self, request: Any, *, now_utc: Any) -> None:
            captured.append((request, now_utc))

    request = SimpleNamespace(
        plan=SimpleNamespace(trade_plan_id="plan-1", plan_hash="a" * 64),
        signal=SimpleNamespace(symbol="BTCUSDT"),
        money_inputs=SimpleNamespace(sized=SimpleNamespace(realized_risk=Decimal("4"))),
    )
    money = SimpleNamespace(
        side="LONG", quantity=Decimal("0.01"), entry_price=Decimal("60000"), leverage=5
    )
    make_reservation_registrar(Store())(request, money, T0)  # type: ignore[arg-type]
    reservation, when = captured[0]
    assert when == T0
    assert reservation.symbol == "BTCUSDT" and reservation.position_side == "LONG"
    assert reservation.quantity == Decimal("0.01")
    assert reservation.realized_risk == Decimal("4")
    assert reservation.required_margin == Decimal("120")  # 0.01 x 60000 / 5
    assert reservation.margin_entry_price == Decimal("60000")
    assert reservation.margin_leverage == 5


def test_late_bound_forwards_every_attribute_to_the_resolved_object() -> None:
    target = SimpleNamespace(value=3)
    proxy = LateBound(lambda: target)
    assert proxy.value == 3
    target.value = 4
    assert proxy.value == 4


async def test_the_live_bot_proxy_refuses_a_send_before_it_is_bound() -> None:
    proxy = LiveBotProxy()
    assert proxy.is_bound is False
    with pytest.raises(BotNotBound):
        await proxy.send_message(chat_id=1, text="x")
    sent: list[str] = []

    class Bot:
        async def send_message(self, *, chat_id: int, text: str, reply_markup: Any = None) -> str:
            sent.append(text)
            return "ok"

    proxy.bind(Bot())
    assert proxy.is_bound is True
    assert await proxy.send_message(chat_id=1, text="x") == "ok"
    assert sent == ["x"]


def test_a_scheduler_event_journals_the_task_kind_and_class_name_only() -> None:
    event = task_event_journal(
        TaskEvent(task="reconcile_tick", kind="failure", at_utc=T0, error_class="ValueError")
    )
    assert event.event_type == "LIVE_TASK_EVENT"
    assert event.entity_id == "reconcile_tick"
    assert '"error_class":"ValueError"' in event.payload_json
    assert dataclasses.is_dataclass(event)


# --------------------------------------------------------------------------- #
# The new PostgreSQL reads: the statements build and compile for the PostgreSQL dialect.
# --------------------------------------------------------------------------- #


class _CapturingDb:
    """Records the statement of each read; answers with an empty result."""

    def __init__(self) -> None:
        self.statements: list[Any] = []

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        outer = self

        class Result:
            def scalars(self) -> list[Any]:
                return []

            def scalar_one_or_none(self) -> None:
                return None

        class Session:
            def execute(self, statement: Any) -> Result:
                outer.statements.append(statement)
                return Result()

        yield Session()


def _sql(statement: Any) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def test_get_intent_selects_one_row_by_approval_and_role() -> None:
    db = _CapturingDb()
    store = PgExecutionStateStore(db)  # type: ignore[arg-type]
    assert store.get_intent(approval_id="a", role="STOP_LOSS") is None
    sql = _sql(db.statements[0])
    assert "execution_intents.approval_id =" in sql and "execution_intents.role =" in sql


def test_restorable_entries_selects_entry_rows_in_sent_unknown_and_acked() -> None:
    db = _CapturingDb()
    store = PgExecutionStateStore(db)  # type: ignore[arg-type]
    assert store.restorable_entries() == ()
    statement = db.statements[0]
    sql = _sql(statement)
    assert "execution_intents.role =" in sql and "execution_intents.intent_status IN" in sql
    compiled = statement.compile(dialect=postgresql.dialect())
    values = {
        v for p in compiled.params.values() for v in (p if isinstance(p, list | tuple) else [p])
    }
    assert {"SENT", "UNKNOWN", "ACKED", "ENTRY"} <= values
    assert "INTENDED" not in values and "REJECTED" not in values
    assert "ORDER BY" in sql


def test_intent_for_client_id_matches_the_entry_id_or_the_algo_id() -> None:
    db = _CapturingDb()
    store = PgExecutionStateStore(db)  # type: ignore[arg-type]
    assert store.intent_for_client_id("x-abc") is None
    sql = _sql(db.statements[0])
    assert "execution_intents.client_order_id =" in sql
    assert "execution_intents.algo_client_id =" in sql and " OR " in sql


# --------------------------------------------------------------------------- #
# The runner registers the operator commands and polls messages.
# --------------------------------------------------------------------------- #


async def test_the_completed_wiring_registers_the_commands_on_the_application(
    tmp_path: Path,
) -> None:
    handles = make_assembly(tmp_path)
    wiring: CompleteLiveWiring = await complete_assembly(handles)

    class Updater:
        def __init__(self) -> None:
            self.kwargs: dict[str, Any] = {}

        async def start_polling(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        async def stop(self) -> None: ...

    class Application:
        def __init__(self) -> None:
            self.bot = SimpleNamespace()
            self.handlers: list[Any] = []
            self.updater = Updater()

        def add_handler(self, handler: Any) -> None:
            self.handlers.append(handler)

        def add_error_handler(self, _handler: Any) -> None: ...

        async def initialize(self) -> None: ...

        async def start(self) -> None: ...

        async def stop(self) -> None: ...

        async def shutdown(self) -> None: ...

    application = Application()
    runner = wiring.runner
    runner._application_factory = lambda: application
    await runner.start()
    try:
        from telegram.ext import CallbackQueryHandler, CommandHandler

        commands = [h for h in application.handlers if isinstance(h, CommandHandler)]
        callbacks = [h for h in application.handlers if isinstance(h, CallbackQueryHandler)]
        assert len(callbacks) == 1, "one on_callback handler only (T-24-47)"
        assert {next(iter(h.commands)) for h in commands} == set(wiring.operator.handlers())
        assert "message" in application.updater.kwargs["allowed_updates"]
        assert "callback_query" in application.updater.kwargs["allowed_updates"]
    finally:
        await runner.stop()
