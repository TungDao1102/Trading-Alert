"""The Phase 24 tracer: CONFIRM, one place_entry, a fill frame, a REST-confirmed stop (24-04).

Everything is real except the edges: the Binance-semantics fake exchange, the PTB bot, the clock
and the TEST_ONLY margin guard. An authorized APPROVE press then a CONFIRM press go through
`on_callback`; the sync `on_confirmed` hook of the confirm core reaches `ExecutionService`, which
schedules ONE `execute_approved_plan` on the event loop; the fake records exactly one `place_entry`
(a GTD LIMIT with no entry-time stop, D079). A SYNTHETIC ORDER_TRADE_UPDATE frame (never captured
Binance data) is routed by the real `UserDataRouter` whose `OrderLookup` is the live client-id
index and whose fill sink is the coordinator's; the coordinator places and confirms the stop with
no manual call in between. Time is virtual and `asyncio.sleep` fails the test.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import threading
from datetime import datetime, timedelta
from decimal import Decimal
from functools import partial
from typing import Any, cast

import pytest
from scripts.gen_phase23_fixtures import fixture_money
from src.adapters.binance_userdata_events import parse_stream_message
from src.adapters.binance_userdata_router import UserDataRouter
from src.adapters.binance_userdata_supervisor import TrustedEvent
from src.adapters.telegram_callbacks import on_callback
from src.approval.confirm_core import DEMO_CONFIRM_PROFILE
from src.core.types import AccountState
from src.domain.approval import Approval
from src.domain.enums import (
    ApprovalAction,
    ApprovalResult,
    ExecutionIntentStatus,
    KillGateState,
    OrderRole,
    SignalStatus,
    TradePlanStatus,
)
from src.domain.trade_plan import TradePlan
from src.execution.approval_desk import ApprovalDesk
from src.execution.confirm_flow import ConfirmFlow, make_confirm_flow
from src.execution.confirm_recheck import (
    ConfirmInputs,
    PrefetchedConfirmInputs,
    make_confirm_recheck,
    prefetched_provider,
)
from src.execution.constraint_snapshot import ExchangeFilterExtras, build_plan_constraint_snapshot
from src.execution.emergency_close import MarketEmergencyCloser
from src.execution.enablement import LiveEnablementController
from src.execution.live_context import LivePlacementContext
from src.execution.order_ids import derive_algo_client_id, derive_client_order_id
from src.execution.pre_placement import PrePlacementInputs, check_remaining_validity
from src.execution.protection import ProtectionCoordinator, ProtectionState
from src.live.execution_service import (
    EVENT_PLACEMENT_OUTCOME,
    EVENT_PLACEMENT_REFUSED,
    EVENT_PLACEMENT_TASK_FAILED,
    REFUSAL_TOKEN_UNAVAILABLE,
    ExecutionService,
    PlacementInputs,
    PlacementRefusal,
)
from src.live.order_index import ClientIdIndex
from src.ops.health import ALL_CHECK_NAMES, HealthCheckResult, run_health_checks
from src.reconcile.safe_mode import SafeModeController
from src.risk.cost_rates import FEE_SOURCE_ACCOUNT_MAX, CostRates
from src.risk.types import ConstraintSnapshot

from tests.shadow_fakes import (
    AUTHORIZED_USER_IDS,
    CHAT_ID,
    T0,
    USER_ID,
    FakeBot,
    InMemoryShadowStores,
    RecordingSleep,
    make_callback_update,
    make_shadow_plan,
    make_shadow_signal,
)
from tests.support.execution_limits import test_only_execution_limits as limits_for_tests
from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.intent_store_fakes import InMemoryExecutionIntentStore
from tests.support.margin_guard_stub import StubMarginGuard, passing_verdict
from tests.support.protection_doubles import RecordingAlerts, lot_filters_for_tests
from tests.support.stream_sinks import RecordingJournal, RecordingSinks, make_router
from tests.support.userdata_frames import order_trade_update_frame
from tests.support.virtual_time import VirtualTime

D = Decimal
TEST_ONLY_STREAM_ORDER_ID = 8_000_000_777
TEST_ONLY_OPERATOR = "operator_alpha"


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    calls: list[float] = []

    async def _forbidden(delay: float, result: Any = None) -> Any:
        calls.append(delay)
        raise AssertionError("asyncio.sleep called: the rig must use the injected clock")

    monkeypatch.setattr(asyncio, "sleep", _forbidden)
    return calls


class PlacementInputsStub:
    """The `PlacementInputsSource` of the tracer: TEST_ONLY risk values for the shadow plan."""

    def __init__(self, rig: Rig) -> None:
        self.rig = rig
        self.calls = 0

    async def for_plan(
        self, approval: Approval, plan: TradePlan, confirmed_at_utc: datetime
    ) -> PlacementInputs | PlacementRefusal:
        self.calls += 1
        rig = self.rig
        now = confirmed_at_utc
        approved_plan = dataclasses.replace(plan, status=TradePlanStatus.APPROVED)
        constraints = ConstraintSnapshot(
            symbol="BTCUSDT",
            price_tick_size=D("0.01"),
            quantity_step_size=D("0.001"),
            min_quantity=D("0.001"),
            min_notional=D("100"),
            metadata_observed_at_utc=now - timedelta(seconds=30),
        )
        snapshot = build_plan_constraint_snapshot(
            plan.trade_plan_id,
            constraints,
            ExchangeFilterExtras(
                market_lot_min_quantity=D("0.001"),
                market_lot_max_quantity=D("120"),
                market_lot_step_size=D("0.001"),
                percent_price_multiplier_up=D("1.05"),
                percent_price_multiplier_down=D("0.95"),
                percent_price_multiplier_decimals=4,
            ),
            D("1000"),
            "MARK_PRICE",
            captured_at_utc=now,
        )
        observed = now - timedelta(seconds=60)
        rates = CostRates(
            fee_rate_entry=D("0.0005"),
            entry_slippage_rate=D("0.0001"),
            fee_rate_exit=D("0.0005"),
            exit_slippage_rate=D("0.0003"),
            fee_source=FEE_SOURCE_ACCOUNT_MAX,
            account_symbol="BTCUSDT",
            commission_observed_at_utc=observed,
            commission_expires_at_utc=observed + timedelta(seconds=3600),
        )
        risk_kwargs: dict[str, Any] = {
            "trade_plan": approved_plan,
            "candidate_position_side": "LONG",
            "account_state": AccountState(equity=D("9600"), risk_rate=D("0.005")),
            "constraint_snapshot": constraints,
            "open_positions": [],
            "daily_loss_quote": D("0"),
            "now_utc": now,
            "ttl": timedelta(seconds=3600),
            "cost_rates": rates,
            "min_stop_distance_rate": D("0.003"),
            "max_cost_to_risk": D("0.15"),
            "minimum_risk_utilization_after_rounding": D("0.60"),
            "parameter_set": {
                "cluster_cap": D("1000"),
                "max_aggregate_open_risk": D("2000"),
                "max_open_positions": 3,
                "daily_loss_warning_threshold": D("100"),
                "daily_loss_stop_threshold": D("200"),
            },
        }
        live_context = LivePlacementContext(
            signal=dataclasses.replace(rig.signal, status=SignalStatus.APPROVED),
            plan_constraint_snapshot=snapshot,
            execution_limits=rig.limits,
            protection_registry=rig.coordinator,
            latest_closed_bar_close=D("50050"),
            gtd_clock_margin=timedelta(seconds=2),
            tp1_quantity_fraction=D("0.5"),
            clock=rig.clock,
            margin_guard=StubMarginGuard(verdict=passing_verdict(equity_used=D("10000"))),
        )
        return PlacementInputs(
            now_utc=now,
            expiry_utc=plan.expiry_utc,
            approval_strategy_version=rig.signal.strategy_version,
            approval_parameter_set_id=rig.signal.parameter_set_id,
            approval_parameter_set_hash=rig.signal.parameter_set_hash,
            risk_kwargs=risk_kwargs,
            gate_kwargs={
                "open_algo_count": 0,
                "planned_leg_count": 3,
                "positions_reconciled": True,
            },
            live_context=live_context,
        )


class Rig:
    """The composition of the tracer (inline in Task 1; moved to tests/support in Task 2)."""

    def __init__(self, *, with_token: bool = True) -> None:
        self.loop = asyncio.get_running_loop()
        self.clock = VirtualTime(T0)
        self.fake = BinanceSemanticsFakeAdapter(
            now_utc=self.clock.now(), enforce_flat_stop_rejection=True
        )
        self.fake.set_lot_filters("BTCUSDT", lot_filters_for_tests())
        self.stores = InMemoryShadowStores()
        self.intents = InMemoryExecutionIntentStore()
        self.journal = RecordingJournal()
        self.limits = limits_for_tests()
        self.sleep = RecordingSleep()
        self.bot = FakeBot.for_mode("DEMO")
        self.alerts = RecordingAlerts()
        self.safe_mode = SafeModeController(adapter=self.fake, journal=self.journal)  # type: ignore[arg-type]
        self.enablement = LiveEnablementController(journal=self.journal)
        self.enablement.enable(
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
        closer = MarketEmergencyCloser(
            adapter=self.fake,
            journal=self.journal,
            safe_mode_controller=self.safe_mode,
            alert_sink=self.alerts,
            clock=self.clock,
            limits=self.limits,
        )
        self.coordinator = ProtectionCoordinator(
            adapter=self.fake,
            intent_store=self.intents,
            journal=self.journal,
            safe_mode_controller=self.safe_mode,
            alert_sink=self.alerts,
            emergency_closer=closer,
            limits=self.limits,
            clock=self.clock,
        )
        self.signal = make_shadow_signal()
        plan = make_shadow_plan(self.signal)
        from src.execution.binding import recompute_plan_hash

        self.plan = dataclasses.replace(plan, plan_hash=recompute_plan_hash(plan))
        self.desk = ApprovalDesk(
            self.stores,
            profile=DEMO_CONFIRM_PROFILE,
            clock=self.clock,
            intent_reader=lambda approval_id: self.intents.get_entry(approval_id=approval_id),
        )
        self.index = ClientIdIndex()
        self.inputs = PlacementInputsStub(self)
        self.service = ExecutionService(
            loop=self.loop,
            token_for=self.desk.approve_token_for if with_token else (lambda _id: None),
            inputs=self.inputs,
            adapter=self.fake,  # type: ignore[arg-type]
            safe_mode_controller=self.safe_mode,
            journal=self.journal,
            enablement=self.enablement,
            intent_store=self.intents,
            index=self.index,
            clock=self.clock,
            authorized_chat_id=CHAT_ID,
        )
        self.holder = PrefetchedConfirmInputs()
        self.flow: ConfirmFlow = make_confirm_flow(
            desk=self.desk,
            profile=DEMO_CONFIRM_PROFILE,
            stores=self.stores,
            clock=self.clock,
            bot=self.bot,
            sleep=self.sleep,
            mark_price=lambda symbol: D("50050"),
            validity_rule=partial(
                check_remaining_validity,
                min_remaining_validity_seconds=self.limits.min_remaining_validity_seconds,
                gtd_clock_margin=timedelta(seconds=2),
            ),
            recheck=make_confirm_recheck(prefetched_provider(self.holder)),
            on_confirmed=self.service.on_confirmed,
            prefetch=self.prefetch,
        )
        self.sinks = RecordingSinks()
        self.router: UserDataRouter = make_router(
            lookup=self.index,  # type: ignore[arg-type]
            journal=self.journal,
            sinks=self.sinks,
            clock=self.clock,
            overrides={"fill_sink": self.coordinator.fill_sink},
        )

    # ---- readings ------------------------------------------------------------------------ #

    def set_prices(self) -> None:
        now = self.clock.now()
        self.fake.now_utc = now
        self.fake.set_mark_price("BTCUSDT", D("50050"), now - timedelta(seconds=1))
        self.fake.set_last_price("BTCUSDT", D("50050"), now - timedelta(seconds=1))

    async def prefetch(self, signal: Any, plan: TradePlan) -> None:
        now = self.clock.now()
        self.holder.put(
            plan.trade_plan_id,
            ConfirmInputs(
                pre_placement=PrePlacementInputs(
                    side=signal.direction,
                    plan_status=TradePlanStatus.APPROVED,
                    signal_invalidated=False,
                    trade_plan=plan,
                    latest_closed_bar_close=D("50050"),
                    expiry_utc=plan.expiry_utc,
                    now_utc=now,
                    min_remaining_validity_seconds=self.limits.min_remaining_validity_seconds,
                    gtd_clock_margin=timedelta(seconds=2),
                    position_symbols=frozenset(),
                    open_order_symbols=frozenset(),
                    any_unprotected=False,
                    symbol=signal.symbol,
                    mark_price=D("50050"),
                    mark_time_utc=now - timedelta(seconds=1),
                    mark_checked_at_utc=now,
                    max_mark_price_age_ms=self.limits.max_mark_price_age_ms,
                    last_price=D("50050"),
                    last_time_utc=now - timedelta(seconds=1),
                    last_checked_at_utc=now,
                    max_last_price_age_ms=self.limits.max_last_price_age_ms,
                    sl_trigger_price=plan.stop_loss_price,
                    entry_min_price=plan.entry_min_price,
                    entry_max_price=plan.entry_max_price,
                ),
                position_mode="ONE_WAY",
            ),
        )

    # ---- driving ------------------------------------------------------------------------- #

    async def issue_and_send(self) -> str:
        issued = self.desk.issue(
            signal=self.signal,
            plan=self.plan,
            money=fixture_money(),
            exposure_quote=D("0"),
            reason_codes=["TREND_OK"],
            now_utc=T0,
        )
        outcome = await self.desk.send(self.bot, chat_id=CHAT_ID, issued=issued, sleep=self.sleep)
        assert outcome.sent
        self.approve_id = issued.approve.approval_id
        return issued.mapping.short_id

    async def press(self, prefix: str, short_id: str, *, query_id: str) -> Any:
        update = make_callback_update(
            data=f"{prefix}:{short_id}",
            chat_id=CHAT_ID,
            query_id=query_id,
            message_chat_id=CHAT_ID,
            from_user_id=USER_ID,
            message_id=1,
            chat_type="private",
        )
        return await on_callback(
            update,
            cast(Any, None),
            **self.flow.callback_kwargs(
                authorized_chat_id=CHAT_ID,
                authorized_user_ids=AUTHORIZED_USER_IDS,
                error_journal=self.stores.record_journal,
            ),
        )

    async def approve_and_confirm(self) -> str:
        short_id = await self.issue_and_send()
        assert (await self.press("APR", short_id, query_id="q-apr")).ok
        await self.clock.advance(30)
        self.set_prices()
        assert (await self.press("CNF", short_id, query_id="q-cnf")).ok
        return short_id

    @property
    def entry_id(self) -> str:
        return derive_client_order_id(plan_hash=self.plan.plan_hash, role=OrderRole.ENTRY.value)

    def trade_frame(self, quantity: str = "0.004") -> dict[str, Any]:
        return order_trade_update_frame(
            c=self.entry_id, i=TEST_ONLY_STREAM_ORDER_ID, t=901, l=quantity, z=quantity
        )

    def route(self, frame: dict[str, Any]) -> Any:
        received = self.clock.now()
        outcome = parse_stream_message(frame, observed_at_utc=received)
        return self.router.route(
            TrustedEvent(
                outcome=outcome, received_at_utc=received, connection_epoch=1, after_gap=False
            )
        )


# --------------------------------------------------------------------------- #
# The tracer.
# --------------------------------------------------------------------------- #


async def test_confirm_places_one_entry_and_its_fill_ends_in_a_rest_confirmed_stop() -> None:
    rig = Rig()
    seen_in_hook: dict[str, Any] = {}

    def at_place_entry(kwargs: dict[str, Any]) -> None:
        # P-4: the id is in the index and the ENTRY intent row is written before the send.
        client_id = kwargs["new_client_order_id"]
        seen_in_hook["index"] = rig.index.known_order(client_id)
        seen_in_hook["intent"] = rig.intents.get_entry(approval_id=rig.approve_id)

    rig.fake.on_place_entry = at_place_entry

    await rig.approve_and_confirm()
    assert rig.service.outstanding == 1, "the hook only scheduled the placement"
    assert rig.fake.calls_to("place_entry") == [], "nothing is placed before the loop runs"
    await rig.service.drain()

    (placement,) = rig.fake.calls_to("place_entry")
    kwargs = placement["kwargs"]
    assert (kwargs["symbol"], kwargs["side"], kwargs["time_in_force"]) == (
        "BTCUSDT",
        "BUY",
        "GTD",
    )
    assert kwargs["new_client_order_id"] == rig.entry_id
    assert rig.fake.calls_to("place_algo_protective") == [], "no entry-time stop (D079)"
    assert rig.fake.open_algos == {}
    known = seen_in_hook["index"]
    assert known is not None and known.client_id == rig.entry_id
    assert seen_in_hook["intent"] is not None
    (outcome,) = rig.journal.by_type(EVENT_PLACEMENT_OUTCOME)
    assert json.loads(outcome.payload_json) == {"is_no_trade": False, "reason_code": "OK"}
    protection = rig.coordinator.protection_of(rig.plan.plan_hash)
    assert protection is not None and protection.state is ProtectionState.AWAITING_FILL

    # The exchange fills part of the entry and the stream says so; nobody calls the coordinator.
    rig.fake.fill(rig.entry_id, quantity=D("0.004"))
    routed = rig.route(rig.trade_frame())
    assert routed.fills == 1
    assert rig.sinks.fills == [], "the coordinator's sink replaced the recording one"
    unknown_stream_orders = [e for e in rig.journal.calls if "UNKNOWN" in e.event_type]
    assert unknown_stream_orders == [], "the index knew the entry id"

    await rig.coordinator.step()
    await rig.clock.advance(1)
    await rig.coordinator.step()

    protection = rig.coordinator.protection_of(rig.plan.plan_hash)
    assert protection is not None and protection.state is ProtectionState.PROTECTED
    (stop,) = rig.fake.calls_to("place_algo_protective")
    assert stop["kwargs"]["close_position"] is True
    assert stop["kwargs"]["client_algo_id"] == derive_algo_client_id(
        plan_hash=rig.plan.plan_hash, role=OrderRole.STOP_LOSS.value
    )
    assert len(rig.fake.calls_to("place_entry")) == 1, "a placement is never re-sent"
    entry = rig.intents.get_entry(approval_id=rig.approve_id)
    assert entry is not None and entry.intent_status is ExecutionIntentStatus.ACKED


# --------------------------------------------------------------------------- #
# The hook, the token accessor, the failure paths.
# --------------------------------------------------------------------------- #


async def test_on_confirmed_returns_none_at_once_and_never_awaits() -> None:
    rig = Rig()
    short_id = await rig.issue_and_send()
    await rig.press("APR", short_id, query_id="q-apr")
    approval = next(a for a in rig.stores.approvals.values() if a.action is ApprovalAction.APPROVE)
    assert approval.result is ApprovalResult.APPROVED

    result = rig.service.on_confirmed(approval, rig.plan, rig.clock.now())

    assert result is None
    assert rig.inputs.calls == 0, "the hook did not run the placement inline"
    assert rig.service.outstanding == 1
    await rig.service.drain()
    assert rig.service.outstanding == 0


async def test_on_confirmed_from_a_worker_thread_schedules_through_the_loop() -> None:
    rig = Rig()
    short_id = await rig.issue_and_send()
    await rig.press("APR", short_id, query_id="q-apr")
    approval = next(a for a in rig.stores.approvals.values() if a.action is ApprovalAction.APPROVE)
    scheduled_from: list[bool] = []
    original = rig.service._schedule

    def spy(*args: Any) -> None:
        scheduled_from.append(threading.current_thread() is threading.main_thread())
        original(*args)

    rig.service._schedule = spy  # type: ignore[method-assign]

    worker = threading.Thread(
        target=rig.service.on_confirmed, args=(approval, rig.plan, rig.clock.now())
    )
    worker.start()
    worker.join()
    assert scheduled_from == [], "nothing ran on the worker thread itself"
    await rig.clock.settle()  # the loop picks the scheduled call up
    assert scheduled_from == [True], "the schedule ran on the loop thread"
    await rig.service.drain()
    assert rig.inputs.calls == 1


async def test_a_placement_task_that_raises_is_journaled_by_class_name_only() -> None:
    rig = Rig()
    short_id = await rig.issue_and_send()
    await rig.press("APR", short_id, query_id="q-apr")
    approval = next(a for a in rig.stores.approvals.values() if a.action is ApprovalAction.APPROVE)

    async def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("secret-detail-do-not-journal")

    rig.inputs.for_plan = boom  # type: ignore[method-assign]

    rig.service.on_confirmed(approval, rig.plan, rig.clock.now())  # the caller is unaffected
    await rig.service.drain()

    (failed,) = rig.journal.by_type(EVENT_PLACEMENT_TASK_FAILED)
    assert json.loads(failed.payload_json) == {"error_class": "RuntimeError"}
    assert "secret-detail" not in failed.payload_json
    assert rig.fake.calls_to("place_entry") == []


def test_approve_token_for_an_unknown_id_is_none() -> None:
    desk = ApprovalDesk(
        InMemoryShadowStores(),
        profile=DEMO_CONFIRM_PROFILE,
        clock=lambda: T0,
        intent_reader=lambda approval_id: None,
    )
    assert desk.approve_token_for("apv-unknown") is None


async def test_approve_token_for_gives_the_issued_token_and_not_the_skip_one() -> None:
    rig = Rig()
    short_id = await rig.issue_and_send()
    token = rig.desk.approve_token_for(rig.approve_id)
    assert token is not None and token != ""
    context = rig.desk.resolve(short_id)
    assert context is not None and context["raw_token"] == token
    skip_id = next(
        a.approval_id for a in rig.stores.approvals.values() if a.action is ApprovalAction.SKIP_USER
    )
    assert rig.desk.approve_token_for(skip_id) is None


async def test_without_a_token_the_service_journals_a_refusal_and_calls_nothing() -> None:
    rig = Rig(with_token=False)  # a restart: the desk memory (and the token) is gone
    await rig.approve_and_confirm()
    await rig.service.drain()

    (refusal,) = rig.journal.by_type(EVENT_PLACEMENT_REFUSED)
    assert json.loads(refusal.payload_json) == {"reason": REFUSAL_TOKEN_UNAVAILABLE}
    assert rig.inputs.calls == 0
    assert rig.fake.calls == []
    assert rig.intents.get_entry(approval_id=rig.approve_id) is None
