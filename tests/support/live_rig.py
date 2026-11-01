"""The Phase 24 composition harness over `VirtualTime` (plan 24-04): used by every live test.

TEST_ONLY: every number here (the BTCUSDT filters, the cost rates, the risk thresholds, the equity,
the fake exchange prices) is a made-up value that only makes a consistent shadow-plan placement
pass the real gates. None is a Binance fact and none is a chosen threshold; no production module
imports this file (tests/test_no_unratified_defaults.py enforces it).

`make_live_rig(**overrides)` builds the path through `src.live.wiring.build_execution_path`
with fakes ONLY at the edges: the Binance-semantics fake exchange (`enforce_flat_stop_rejection`),
the PTB bot, the clock and the margin guard. Everything else is the real object: the approval desk,
the confirm flow and core, the execution service, the manager, the protection coordinator, the
emergency closer, the SAFE_MODE controller, the enablement controller and the user-data router
whose `OrderLookup` is the live client-id index. Presses go through `on_callback` with the flow's
own callback keywords (D-17). `forbid_real_sleep` makes a real `asyncio.sleep` fail the test
(the pattern of tests/test_protection_router_rig.py).

Overrides (all optional): `token_for`, `limits`, `margin_verdict`, `inputs`.
"""

from __future__ import annotations

import asyncio
import dataclasses
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from functools import partial
from typing import Any, cast

import pytest
from scripts.gen_phase23_fixtures import fixture_money
from src.adapters.binance_userdata_events import parse_stream_message
from src.adapters.binance_userdata_router import UserDataRouter
from src.adapters.binance_userdata_supervisor import TrustedEvent
from src.adapters.telegram_callbacks import DispatchResult, on_callback
from src.approval.confirm_core import DEMO_CONFIRM_PROFILE
from src.core.types import AccountState
from src.domain.approval import Approval
from src.domain.enums import (
    ApprovalAction,
    KillGateState,
    OrderRole,
    SignalStatus,
    TradePlanStatus,
)
from src.domain.trade_plan import TradePlan
from src.execution.binding import recompute_plan_hash
from src.execution.confirm_recheck import (
    ConfirmInputs,
    PrefetchedConfirmInputs,
    make_confirm_recheck,
    prefetched_provider,
)
from src.execution.constraint_snapshot import ExchangeFilterExtras, build_plan_constraint_snapshot
from src.execution.enablement import LiveEnablementController
from src.execution.execution_limits import ExecutionLimits
from src.execution.live_context import LivePlacementContext
from src.execution.order_ids import derive_client_order_id
from src.execution.pre_placement import PrePlacementInputs, check_remaining_validity
from src.live.execution_service import PlacementInputs, PlacementInputsSource, PlacementRefusal
from src.live.wiring import LiveWiring, build_execution_path
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
from tests.support.execution_limits import test_only_execution_limits
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
TEST_ONLY_SYMBOL = "BTCUSDT"
# TEST_ONLY: the sizing equity; the fake margin guard reports a larger live equity (gate 5f3).
TEST_ONLY_SIZING_EQUITY = D("9600")
TEST_ONLY_GUARD_EQUITY = D("10000")
OVERRIDE_NAMES = frozenset({"token_for", "limits", "margin_verdict", "inputs"})


def forbid_real_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Make a call of `asyncio.sleep` fail the test; returns the (empty) list of attempts."""
    calls: list[float] = []

    async def _forbidden(delay: float, result: Any = None) -> Any:
        calls.append(delay)
        raise AssertionError("asyncio.sleep called: the rig must use the injected clock")

    monkeypatch.setattr(asyncio, "sleep", _forbidden)
    return calls


class RigPlacementInputs:
    """A `PlacementInputsSource` with TEST_ONLY risk values for the shadow plan.

    The live producer (plan 24-16) implements the same port; this one only makes a consistent
    BTCUSDT LONG placement pass the real gates. The coordinator is read lazily because it is
    built by `build_execution_path`, after this source exists.
    """

    def __init__(
        self,
        *,
        signal: Any,
        limits: ExecutionLimits,
        clock: VirtualTime,
        margin_verdict: Any,
    ) -> None:
        self.signal = signal
        self.limits = limits
        self.clock = clock
        self.margin_verdict = margin_verdict
        self.wiring: LiveWiring | None = None
        self.calls = 0
        # TEST_ONLY: the snapshots the manager made durable (plan 24-37, F3), in order.
        self.recorded_snapshots: list[Any] = []

    async def for_plan(
        self, approval: Approval, plan: TradePlan, confirmed_at_utc: datetime
    ) -> PlacementInputs | PlacementRefusal:
        self.calls += 1
        if self.wiring is None:
            return PlacementRefusal(reason="WIRING_NOT_BUILT")
        now = confirmed_at_utc
        constraints = ConstraintSnapshot(
            symbol=TEST_ONLY_SYMBOL,
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
            account_symbol=TEST_ONLY_SYMBOL,
            commission_observed_at_utc=observed,
            commission_expires_at_utc=observed + timedelta(seconds=3600),
        )
        risk_kwargs: dict[str, Any] = {
            "trade_plan": dataclasses.replace(plan, status=TradePlanStatus.APPROVED),
            "candidate_position_side": "LONG",
            "account_state": AccountState(equity=TEST_ONLY_SIZING_EQUITY, risk_rate=D("0.005")),
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
            signal=dataclasses.replace(self.signal, status=SignalStatus.APPROVED),
            plan_constraint_snapshot=snapshot,
            execution_limits=self.limits,
            protection_registry=self.wiring.coordinator,
            latest_closed_bar_close=D("50050"),
            gtd_clock_margin=timedelta(seconds=2),
            tp1_quantity_fraction=D("0.5"),
            clock=self.clock,
            margin_guard=StubMarginGuard(verdict=self.margin_verdict),
            snapshot_recorder=self.recorded_snapshots.append,
        )
        return PlacementInputs(
            now_utc=now,
            expiry_utc=plan.expiry_utc,
            approval_strategy_version=self.signal.strategy_version,
            approval_parameter_set_id=self.signal.parameter_set_id,
            approval_parameter_set_hash=self.signal.parameter_set_hash,
            risk_kwargs=risk_kwargs,
            gate_kwargs={
                "open_algo_count": 0,
                "planned_leg_count": 3,
                "positions_reconciled": True,
            },
            live_context=live_context,
        )


async def prefetch_inputs(
    *,
    clock: VirtualTime,
    holder: PrefetchedConfirmInputs,
    limits: ExecutionLimits,
    signal: Any,
    plan: TradePlan,
) -> None:
    """The confirm flow's prefetch: put fresh readings where the re-check reads them."""
    now = clock.now()
    holder.put(
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
                min_remaining_validity_seconds=limits.min_remaining_validity_seconds,
                gtd_clock_margin=timedelta(seconds=2),
                position_symbols=frozenset(),
                open_order_symbols=frozenset(),
                any_unprotected=False,
                symbol=signal.symbol,
                mark_price=D("50050"),
                mark_time_utc=now - timedelta(seconds=1),
                mark_checked_at_utc=now,
                max_mark_price_age_ms=limits.max_mark_price_age_ms,
                last_price=D("50050"),
                last_time_utc=now - timedelta(seconds=1),
                last_checked_at_utc=now,
                max_last_price_age_ms=limits.max_last_price_age_ms,
                sl_trigger_price=plan.stop_loss_price,
                entry_min_price=plan.entry_min_price,
                entry_max_price=plan.entry_max_price,
            ),
            position_mode="ONE_WAY",
        ),
    )


@dataclass(frozen=True)
class IssuedHandle:
    """What `LiveRig.issue_and_send` returns: the short id of the buttons and the APPROVE id."""

    short_id: str
    approve_id: str


@dataclass(frozen=True)
class LiveRig:
    """Everything one live test touches (see `make_live_rig`)."""

    clock: VirtualTime
    fake: BinanceSemanticsFakeAdapter
    stores: InMemoryShadowStores
    intents: InMemoryExecutionIntentStore
    journal: RecordingJournal
    limits: ExecutionLimits
    bot: FakeBot
    alerts: RecordingAlerts
    safe_mode: SafeModeController
    enablement: LiveEnablementController
    wiring: LiveWiring
    inputs: Any
    sleep: RecordingSleep
    holder: PrefetchedConfirmInputs
    sinks: RecordingSinks
    router: UserDataRouter
    signal: Any
    plan: TradePlan

    # ---- readings ------------------------------------------------------------------------ #

    def set_prices(self) -> None:
        """Move the fake exchange to the virtual now with a fresh mark and last price."""
        now = self.clock.now()
        self.fake.now_utc = now
        self.fake.set_mark_price(TEST_ONLY_SYMBOL, D("50050"), now - timedelta(seconds=1))
        self.fake.set_last_price(TEST_ONLY_SYMBOL, D("50050"), now - timedelta(seconds=1))

    # ---- driving ------------------------------------------------------------------------- #

    async def issue_and_send(self) -> IssuedHandle:
        """Issue the request through the real desk and send it through the fake bot."""
        desk = self.wiring.desk
        issued = desk.issue(
            signal=self.signal,
            plan=self.plan,
            money=fixture_money(),
            exposure_quote=D("0"),
            reason_codes=["TREND_OK"],
            now_utc=T0,
        )
        outcome = await desk.send(self.bot, chat_id=CHAT_ID, issued=issued, sleep=self.sleep)
        assert outcome.sent
        return IssuedHandle(short_id=issued.mapping.short_id, approve_id=issued.approve.approval_id)

    async def press(self, prefix: str, short_id: str, *, query_id: str) -> DispatchResult:
        """One authorized button press through `on_callback` with the flow's callback keywords."""
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
            **self.wiring.confirm_flow.callback_kwargs(
                authorized_chat_id=CHAT_ID,
                authorized_user_ids=AUTHORIZED_USER_IDS,
                error_journal=self.stores.record_journal,
            ),
        )

    async def approve_and_confirm(self) -> IssuedHandle:
        """APPROVE, 30 virtual seconds, then CONFIRM (both presses must be accepted)."""
        handle = await self.issue_and_send()
        assert (await self.press("APR", handle.short_id, query_id="q-apr")).ok
        await self.clock.advance(30)
        self.set_prices()
        assert (await self.press("CNF", handle.short_id, query_id="q-cnf")).ok
        return handle

    def approve_row(self) -> Approval:
        return next(a for a in self.stores.approvals.values() if a.action is ApprovalAction.APPROVE)

    # ---- the stream ---------------------------------------------------------------------- #

    @property
    def entry_id(self) -> str:
        return derive_client_order_id(plan_hash=self.plan.plan_hash, role=OrderRole.ENTRY.value)

    def trade_frame(self, quantity: str = "0.004") -> dict[str, Any]:
        """A SYNTHETIC ORDER_TRADE_UPDATE TRADE frame of the entry (never captured data)."""
        return order_trade_update_frame(
            c=self.entry_id, i=TEST_ONLY_STREAM_ORDER_ID, t=901, l=quantity, z=quantity
        )

    def route(self, frame: dict[str, Any], *, after_gap: bool = False) -> Any:
        """Parse and route one frame through the real router."""
        received = self.clock.now()
        outcome = parse_stream_message(frame, observed_at_utc=received)
        return self.router.route(
            TrustedEvent(
                outcome=outcome,
                received_at_utc=received,
                connection_epoch=1,
                after_gap=after_gap,
            )
        )


async def make_live_rig(**overrides: Any) -> LiveRig:
    """Build the tracer composition through `build_execution_path` (fakes only at the edges)."""
    unknown = set(overrides) - OVERRIDE_NAMES
    if unknown:
        raise TypeError(f"unknown live rig override: {sorted(unknown)}")
    loop = asyncio.get_running_loop()
    clock = VirtualTime(T0)
    fake = BinanceSemanticsFakeAdapter(now_utc=clock.now(), enforce_flat_stop_rejection=True)
    fake.set_lot_filters(TEST_ONLY_SYMBOL, lot_filters_for_tests())
    stores = InMemoryShadowStores()
    intents = InMemoryExecutionIntentStore()
    journal = RecordingJournal()
    limits: ExecutionLimits = overrides.get("limits") or test_only_execution_limits()
    sleep = RecordingSleep()
    bot = FakeBot.for_mode("DEMO")
    alerts = RecordingAlerts()
    safe_mode = SafeModeController(adapter=fake, journal=journal)  # type: ignore[arg-type]
    enablement = LiveEnablementController(journal=journal)
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
    signal = make_shadow_signal()
    shadow_plan = make_shadow_plan(signal)
    # The binding re-derives the plan hash, so the shadow plan's placeholder hash is replaced.
    plan = dataclasses.replace(shadow_plan, plan_hash=recompute_plan_hash(shadow_plan))
    margin_verdict = overrides.get("margin_verdict") or passing_verdict(
        equity_used=TEST_ONLY_GUARD_EQUITY
    )
    inputs: PlacementInputsSource = overrides.get("inputs") or RigPlacementInputs(
        signal=signal, limits=limits, clock=clock, margin_verdict=margin_verdict
    )
    holder = PrefetchedConfirmInputs()

    async def prefetch(sig: Any, pln: TradePlan) -> None:
        await prefetch_inputs(clock=clock, holder=holder, limits=limits, signal=sig, plan=pln)

    wiring = build_execution_path(
        loop=loop,
        clock=clock,
        adapter=fake,  # type: ignore[arg-type]
        stores=stores,
        intent_store=intents,
        journal=journal,
        safe_mode_controller=safe_mode,
        enablement=enablement,
        alert_sink=alerts,
        limits=limits,
        inputs=inputs,
        profile=DEMO_CONFIRM_PROFILE,
        authorized_chat_id=CHAT_ID,
        bot=bot,
        sleep=sleep,
        mark_price=lambda symbol: D("50050"),
        validity_rule=partial(
            check_remaining_validity,
            min_remaining_validity_seconds=limits.min_remaining_validity_seconds,
            gtd_clock_margin=timedelta(seconds=2),
        ),
        recheck=make_confirm_recheck(prefetched_provider(holder)),
        prefetch=prefetch,
        token_for=overrides.get("token_for"),
    )
    if isinstance(inputs, RigPlacementInputs):
        inputs.wiring = wiring
    sinks = RecordingSinks()
    router = make_router(
        lookup=wiring.index,  # type: ignore[arg-type]
        journal=journal,
        sinks=sinks,
        clock=clock,
        overrides={"fill_sink": wiring.coordinator.fill_sink},
    )
    rig = LiveRig(
        clock=clock,
        fake=fake,
        stores=stores,
        intents=intents,
        journal=journal,
        limits=limits,
        bot=bot,
        alerts=alerts,
        safe_mode=safe_mode,
        enablement=enablement,
        wiring=wiring,
        inputs=inputs,
        sleep=sleep,
        holder=holder,
        sinks=sinks,
        router=router,
        signal=signal,
        plan=plan,
    )
    return rig


__all__ = [
    "OVERRIDE_NAMES",
    "TEST_ONLY_OPERATOR",
    "TEST_ONLY_SYMBOL",
    "IssuedHandle",
    "LiveRig",
    "RigPlacementInputs",
    "forbid_real_sleep",
    "make_live_rig",
    "prefetch_inputs",
]
