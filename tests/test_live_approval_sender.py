"""The DEMO approval request sender and its signal source (Phase 24, plan 24-14; D-18, OQ-2).

Fakes only for the sender flow (D-17): the real `ApprovalDesk`, the in-memory stores of the
SHADOW chain scoped to DEMO, a fake bot and fake readers. The D028 chain is proven twice: against
a fake approval store that models the PostgreSQL transaction (decide, hook, rollback on error) for
the ordering and rollback rules, and against PostgreSQL in the `*_pg` section at the end (skips
without TEST_DATABASE_URL; `TRADING_CI_STRICT=1` turns the skip into a failure).
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from src.adapters.binance_public import SymbolFilters
from src.adapters.binance_usdm import CommissionRates
from src.adapters.telegram_callbacks import DispatchResult, on_callback
from src.approval.confirm_core import DEMO_CONFIRM_PROFILE
from src.approval.mapping import ShortIdMapping
from src.approval.replay import ApprovalAlreadyDecided
from src.backtest.semantics import NO_TRADE_CONFLICT
from src.domain.approval import Approval
from src.domain.enums import (
    ApprovalAction,
    ApprovalResult,
    ExecutionIntentStatus,
    RejectionReason,
    SignalStatus,
    TradePlanStatus,
)
from src.domain.ids import make_signal_id
from src.domain.registry import load_parameter_set
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.domain.transitions import IllegalTransition, TransitionKind, assert_transition
from src.execution.approval_desk import ApprovalDesk
from src.execution.protection import PlanProtection, ProtectionState
from src.live.approval_sender import (
    CONFLICT_SOURCES,
    EVENT_REQUEST_NOT_ISSUED,
    EVENT_REQUEST_REFUSED,
    EVENT_SIGNAL_NOTIFY_FAILED,
    REASON_CONFLICT,
    REASON_UNCERTAIN,
    ApprovalRequestSender,
    DemoDeskStores,
    OpenApproval,
    SendStatus,
    apply_d028_chain,
    make_demo_save_atomic,
    make_open_demo_approvals_reader,
)
from src.live.signal_source import (
    DEMO_SMOKE_SETUP,
    DemoSmokeSignalSource,
    SignalDerivationError,
    SignalRequest,
    SignalSource,
    build_request_money,
)
from src.persistence.approvals import PgApprovalStore
from src.persistence.day_risk import PgDayRiskStore
from src.persistence.engine import make_sync_engine
from src.persistence.entities import PgTradingEntityStore
from src.persistence.risk_reservations import PgRiskReservationStore, ReservationRefused
from src.persistence.shadow_stores import approval_mode_event
from src.persistence.uow import OperationalDatabase
from src.risk.daily_loss import DayRiskState
from src.risk.money_at_stake import MoneyAtStake, money_canonical_json
from src.risk.reservations import ReleaseReason, ReservationRequest, ReservationStatus
from telegram.error import Forbidden

from tests.shadow_fakes import (
    AUTHORIZED_USER_IDS,
    CHAT_ID,
    USER_ID,
    FakeBot,
    InMemoryShadowStores,
    RecordingSleep,
    make_callback_update,
)
from tests.support.intent_store_fakes import InMemoryExecutionIntentStore
from tests.support.pg_rows import (
    hexid,
    insert_and_commit,
    make_approval,
    make_plan,
    make_signal,
)

D = Decimal
ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
BAR_CLOSE = datetime(2026, 10, 5, 11, 0, 0, tzinfo=UTC)
MARK = D("60000.0")
PARAMETER_SET = load_parameter_set("trend-pullback", "baseline-v5")
COMMISSION = CommissionRates(symbol="BTCUSDT", maker_rate=D("0.0002"), taker_rate=D("0.0004"))


def btc_filters(**overrides: Any) -> SymbolFilters:
    fields: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "contract_type": "PERPETUAL",
        "status": "TRADING",
        "onboard_time_utc": None,
        "price_tick_size": D("0.1"),
        "quantity_step_size": D("0.001"),
        "min_quantity": D("0.001"),
        "max_quantity": D("1000"),
        "min_notional": D("100"),
        "base_asset": "BTC",
        "quote_asset": "USDT",
        "margin_asset": "USDT",
        "notional_constraints_json": "{}",
        "order_capabilities_json": "{}",
        "position_mode_snapshot_json": "{}",
        "percent_price_multiplier_up": D("1.05"),
        "percent_price_multiplier_down": D("0.95"),
        "percent_price_multiplier_decimals": 4,
        "market_lot_min_quantity": D("0.001"),
        "market_lot_max_quantity": D("120"),
        "market_lot_step_size": D("0.001"),
    }
    fields.update(overrides)
    return SymbolFilters(**fields)


def new_source(run_id: str = "run-1") -> DemoSmokeSignalSource:
    return DemoSmokeSignalSource(run_id=run_id, parameter_set=PARAMETER_SET)


def derive(source: DemoSmokeSignalSource, scenario: str = "far", **overrides: Any) -> SignalRequest:
    values: dict[str, Any] = {
        "scenario": scenario,
        "filters": btc_filters(),
        "mark_price": MARK,
        "commission": COMMISSION,
        "observed_at": NOW,
        "latest_closed_bar_close": BAR_CLOSE,
    }
    values.update(overrides)
    return source.derive_request(**values)


# --------------------------------------------------------------------------- #
# Fakes.
# --------------------------------------------------------------------------- #


class DemoStores(InMemoryShadowStores):
    """The DEMO view of the shared stores: it writes the plan 24-08 mode marker like Pg does."""

    def insert_pending(self, approval: Approval) -> None:
        super().insert_pending(approval)
        if self.confirm_mode is not None:
            self.record_journal(approval_mode_event(approval, self.confirm_mode))

    def get_signal(self, signal_id: str) -> Signal | None:
        return self.signals.get(signal_id)

    def get_trade_plan(self, trade_plan_id: str) -> TradePlan | None:
        return self.plans.get(trade_plan_id)


class FakeEntities:
    """`transition_signal` / `transition_trade_plan` over the stores' dicts, DOMN-04 enforced."""

    def __init__(self, stores: InMemoryShadowStores, trace: list[str]) -> None:
        self._stores = stores
        self.trace = trace
        self.fail_on: set[str] = set()

    def transition_signal(
        self, signal_id: str, new_status: SignalStatus, *, now_utc: datetime, tx: Any = None
    ) -> Signal:
        self.trace.append(f"signal:{new_status.value}")
        if "signal" in self.fail_on:
            raise RuntimeError("signal transition failed")
        current = self._stores.signals[signal_id]
        if current.status is not new_status:
            assert_transition(TransitionKind.SIGNAL, current.status, new_status)
            current = Signal(**{**current.__dict__, "status": new_status})
            self._stores.signals[signal_id] = current
        return current

    def transition_trade_plan(
        self, trade_plan_id: str, new_status: TradePlanStatus, *, now_utc: datetime, tx: Any = None
    ) -> TradePlan:
        self.trace.append(f"plan:{new_status.value}")
        if "plan" in self.fail_on:
            raise RuntimeError("plan transition failed")
        current = self._stores.plans[trade_plan_id]
        if current.status is not new_status:
            assert_transition(TransitionKind.TRADE_PLAN, current.status, new_status)
            current = TradePlan(**{**current.__dict__, "status": new_status})
            self._stores.plans[trade_plan_id] = current
        return current


class FakePositions:
    def __init__(self) -> None:
        self.quantity = D("0")
        self.entry_orders = 0
        self.raise_on: set[str] = set()

    async def open_position_quantity(self, symbol: str) -> Decimal:
        if "position" in self.raise_on:
            raise TimeoutError("REST position read timed out")
        return self.quantity

    async def open_entry_order_count(self, symbol: str) -> int:
        if "orders" in self.raise_on:
            raise TimeoutError("REST open orders read timed out")
        return self.entry_orders


class FakeDb:
    """The state one fake transaction can roll back: approvals, signals, plans, reservations."""

    def __init__(self, stores: InMemoryShadowStores) -> None:
        self.stores = stores
        self.reservations: dict[str, str] = {}

    def snapshot(self) -> tuple[Any, ...]:
        return (
            dict(self.stores.approvals),
            dict(self.stores.signals),
            dict(self.stores.plans),
            dict(self.stores.mappings),
            dict(self.reservations),
        )

    def restore(self, snapshot: tuple[Any, ...]) -> None:
        self.stores.approvals = snapshot[0]
        self.stores.signals = snapshot[1]
        self.stores.plans = snapshot[2]
        self.stores.mappings = snapshot[3]
        self.reservations = snapshot[4]


class FakeTxApprovals:
    """`PgApprovalStore.save_atomic` as a transaction: decide, hook, roll back on any error."""

    def __init__(self, db: FakeDb) -> None:
        self._db = db

    def save_atomic(
        self, approval: Approval, mapping: ShortIdMapping | None, *, after_decide: Any = None
    ) -> None:
        stores = self._db.stores
        current = stores.approvals[approval.approval_id]
        if current.status is not ApprovalResult.PENDING:
            raise ApprovalAlreadyDecided(current)
        snapshot = self._db.snapshot()
        stores.approvals[approval.approval_id] = approval
        try:
            if after_decide is not None:
                after_decide(object(), approval)
            if mapping is not None:
                stores._put_mapping(mapping)
        except BaseException:
            self._db.restore(snapshot)
            raise


class FakeReservations:
    """The two reservation methods the Phase 21 hook calls, tracing their order."""

    def __init__(self, db: FakeDb, trace: list[str]) -> None:
        self._db = db
        self._trace = trace
        self.refuse = False

    def register(self, trade_plan_id: str) -> None:
        self._db.reservations[trade_plan_id] = "REQUESTED"

    def reserve_in(self, session: Any, *, approval: Approval, **_: Any) -> None:
        self._trace.append("reserve:APPROVED")
        rows = self._db.reservations
        if self.refuse or rows.get(approval.trade_plan_id) != "REQUESTED":
            raise ReservationRefused(RejectionReason.UNCERTAIN_ACCOUNT_STATE)
        rows[approval.trade_plan_id] = "RESERVED"

    def release_requested_in(
        self, session: Any, *, trade_plan_id: str, reason: ReleaseReason, now_utc: datetime
    ) -> None:
        self._trace.append(f"release:{reason.value}")
        if self._db.reservations.get(trade_plan_id) == "REQUESTED":
            self._db.reservations[trade_plan_id] = "RELEASED"


def protection(symbol: str, state: ProtectionState) -> PlanProtection:
    return PlanProtection(
        plan_hash="c" * 64,
        symbol=symbol,
        state=state,
        first_fill_at_utc=None,
        stop_confirmed_at_utc=None,
        entry_terminal_at_utc=None,
        last_reason=None,
    )


@dataclass
class Rig:
    stores: DemoStores = field(default_factory=lambda: DemoStores(confirm_mode="DEMO"))
    intents: InMemoryExecutionIntentStore = field(default_factory=InMemoryExecutionIntentStore)
    positions: FakePositions = field(default_factory=FakePositions)
    sleep: RecordingSleep = field(default_factory=RecordingSleep)
    now: datetime = NOW
    tracked: list[PlanProtection] = field(default_factory=list)
    extra_approvals: list[OpenApproval] = field(default_factory=list)
    journal_events: list[Any] = field(default_factory=list)
    reservations: list[tuple[str, str]] = field(default_factory=list)
    # True: the desk's stores are `DemoDeskStores` over `make_demo_save_atomic` (the D028 chain).
    with_chain: bool = False

    def __post_init__(self) -> None:
        self.trace: list[str] = []
        self.bot = FakeBot.for_mode("DEMO")
        self.entities = FakeEntities(self.stores, self.trace)
        self.db = FakeDb(self.stores)
        self.reservation_store = FakeReservations(self.db, self.trace)
        desk_stores: Any = self.stores
        if self.with_chain:
            save = make_demo_save_atomic(
                approvals=cast(Any, FakeTxApprovals(self.db)),
                reservations=cast(Any, self.reservation_store),
                entities=self.entities,
                parameter_set={},
                daily_loss_quote=lambda day: D("0"),
            )
            desk_stores = DemoDeskStores(self.stores, save)
        self.desk_stores = desk_stores
        self.desk = ApprovalDesk(
            desk_stores,
            profile=DEMO_CONFIRM_PROFILE,
            clock=lambda: self.now,
            intent_reader=lambda approval_id: self.intents.get_entry(approval_id=approval_id),
        )
        store_reader = make_open_demo_approvals_reader(self.stores)
        self.money_for: Callable[[SignalRequest], MoneyAtStake | None] = build_request_money
        self.sender = ApprovalRequestSender(
            desk=self.desk,
            bot=self.bot,
            chat_id=CHAT_ID,
            entities=self.entities,
            intents=self.intents,
            protections=lambda: tuple(self.tracked),
            positions_reader=self.positions,
            approvals_reader=lambda: [*store_reader(), *self.extra_approvals],
            money_for=lambda request: self.money_for(request),
            clock=lambda: self.now,
            sleep=self.sleep,
            journal=self._journal,
            register_reservation=self._register,
        )

    def _register(self, request: SignalRequest, money: MoneyAtStake, now: datetime) -> None:
        self.reservations.append((request.plan.trade_plan_id, money.side))
        self.reservation_store.register(request.plan.trade_plan_id)

    async def tap(self, prefix: str, short_id: str, *, query_id: str) -> DispatchResult:
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
            authorized_chat_id=CHAT_ID,
            authorized_user_ids=AUTHORIZED_USER_IDS,
            binding_context_resolver=self.desk.resolve,
            dispatch=self.desk.dispatch,
            reply_text_fn=self.desk.reply_fn(self.bot, sleep=self.sleep),
            finalize_message=self.desk.finalize_hook(self.bot, sleep=self.sleep),
            clock=lambda: self.now,
        )

    def _journal(self, event: Any) -> None:
        self.journal_events.append(event)
        # Like the real sink, the store refuses an event that points at a missing row.
        self.stores.record_journal(event)

    def approvals(self) -> list[Approval]:
        return list(self.stores.approvals.values())


def entry_intent(rig: Rig, request: SignalRequest, status: ExecutionIntentStatus) -> None:
    ok = rig.intents.consume_and_record_entry_intent(
        approval_id="apv-other",
        trade_plan_id=request.plan.trade_plan_id,
        plan_hash=request.plan.plan_hash,
        client_order_id="cid-1",
        symbol=request.signal.symbol,
        side="BUY",
        intended_quantity=D("0.004"),
        intended_price=D("58500.0"),
        approved_quantity=D("0.004"),
        now_utc=NOW,
    )
    assert ok
    row = rig.intents.get_entry(approval_id="apv-other")
    assert row is not None
    rig.intents._rows[("apv-other", "ENTRY")] = type(row)(
        **{**row.__dict__, "intent_status": status}
    )


# --------------------------------------------------------------------------- #
# Task 1: the signal source and the tracer.
# --------------------------------------------------------------------------- #


def test_the_demo_smoke_source_satisfies_the_protocol_and_ships_alone() -> None:
    source: SignalSource = new_source()
    assert isinstance(source, DemoSmokeSignalSource)
    modules = sorted(p.stem for p in (ROOT / "src" / "live").glob("*signal*.py"))
    assert modules == ["signal_source"]


async def test_next_request_is_fifo_and_none_when_empty() -> None:
    source = new_source()
    assert await source.next_request() is None
    first = source.submit(
        scenario="far",
        filters=btc_filters(),
        mark_price=MARK,
        commission=COMMISSION,
        observed_at=NOW,
        latest_closed_bar_close=BAR_CLOSE,
    )
    second = source.submit(
        scenario="far",
        filters=btc_filters(),
        mark_price=MARK,
        commission=COMMISSION,
        observed_at=NOW,
        latest_closed_bar_close=BAR_CLOSE,
    )
    assert source.pending == 2
    assert await source.next_request() is first
    assert await source.next_request() is second
    assert await source.next_request() is None
    assert first.signal.signal_id != second.signal.signal_id


def test_the_smoke_ids_are_never_a_shadow_id() -> None:
    request = derive(new_source())
    signal = request.signal
    shadow_id = make_signal_id(
        strategy_id=signal.strategy_id,
        strategy_version=signal.strategy_version,
        parameter_set_id=signal.parameter_set_id,
        symbol=signal.symbol,
        source_timeframe=signal.source_timeframe,
        source_candle_close_utc=signal.source_candle_close_utc,
        setup_fingerprint="{}",
    )
    assert signal.signal_id != shadow_id
    assert request.plan.signal_id == signal.signal_id
    assert request.plan.trade_plan_id != signal.signal_id
    # a different run id gives different ids; the same inputs under one source give distinct ones
    assert derive(new_source("run-2")).signal.signal_id != signal.signal_id


def test_the_derived_plan_is_decimal_and_the_unmodified_pipeline_sizes_it() -> None:
    request = derive(new_source())
    plan = request.plan
    # entry 60000 * (1 - 0.05 * 0.5) = 58500.0; entry_max 60000 * 1.005 = 60300.0; the mirror
    # entry_min is 56700.0; stop 56700.0 * 0.985 = 55849.5 (the rehearsal's own arithmetic).
    assert plan.entry_min_price == D("56700.0")
    assert plan.entry_max_price == D("60300.0")
    assert plan.stop_loss_price == D("55849.5")
    assert plan.quantity_after_rounding == D("0.004")
    assert plan.status is TradePlanStatus.APPROVAL_PENDING
    assert request.signal.status is SignalStatus.DETECTED
    assert request.signal.setup_type == DEMO_SMOKE_SETUP
    assert request.money_inputs.sized.quantity == D("0.004")
    assert request.money_inputs.equity == D("3625.09")
    assert request.latest_closed_bar_close == BAR_CLOSE
    assert request.signal.source_candle_close_utc == BAR_CLOSE
    assert plan.expiry_utc == NOW + timedelta(seconds=300) + timedelta(minutes=10)


def test_the_fill_scenario_places_the_zone_around_the_mark() -> None:
    request = derive(new_source(), "fill")
    plan = request.plan
    assert plan.entry_min_price < MARK < plan.entry_max_price


@pytest.mark.parametrize(
    "overrides",
    [
        {"scenario": "sideways"},
        {"mark_price": D("0")},
        {"filters": btc_filters(percent_price_multiplier_down=None)},
        {"filters": btc_filters(max_quantity=D("0.002"))},
        {"filters": btc_filters(symbol="ETHUSDT")},
    ],
    ids=["scenario", "mark", "band", "max_quantity", "symbol"],
)
def test_a_plan_that_cannot_be_derived_raises_instead_of_producing_a_request(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(SignalDerivationError):
        derive(new_source(), **overrides)


def test_the_source_refuses_a_symbol_outside_the_live_five() -> None:
    with pytest.raises(SignalDerivationError):
        DemoSmokeSignalSource(run_id="r", parameter_set=PARAMETER_SET, symbol="DOGEUSDT")


async def test_a_demo_request_becomes_one_card_with_its_money_sent_once() -> None:
    rig = Rig()
    request = derive(new_source())

    outcome = await rig.sender.send_request(request)

    assert outcome.status is SendStatus.SENT
    assert outcome.notified is True
    # rows persisted under the request's own ids
    assert rig.stores.signals[request.signal.signal_id].status is SignalStatus.NOTIFIED
    assert request.plan.trade_plan_id in rig.stores.plans
    # one DEMO approval pair, PENDING, money stored identically on both rows
    approvals = rig.approvals()
    assert sorted(a.action.value for a in approvals) == ["APPROVE", "SKIP_USER"]
    assert {a.status for a in approvals} == {ApprovalResult.PENDING}
    expected_money = money_canonical_json(build_request_money(request))
    assert {a.money_json for a in approvals} == {expected_money}
    assert {a.approved_quantity for a in approvals} == {D("0.004")}
    assert {rig.stores.approval_modes[a.approval_id] for a in approvals} == {"DEMO"}
    # the reservation request was registered once for the plan, after the rows existed
    assert rig.reservations == [(request.plan.trade_plan_id, "LONG")]
    # ONE card, with the APRV-01 fields and the money rows
    assert len(rig.bot.sent) == 1
    text = rig.bot.sent[0].text
    for fragment in (
        "Mode: DEMO",
        "BTCUSDT",
        "LONG",
        DEMO_SMOKE_SETUP,
        "56700.0",
        "60300.0",
        "55849.5",
        "61800.0",
        "63600.0",
        "0.004",
        request.signal.signal_id,
        "CANDLE_CLOSE at 55849.5",
        "DEMO_ONLY",
    ):
        assert fragment in text, fragment
    money = build_request_money(request)
    assert f"Loss at SL: {money.loss_at_stop_gross} USDT gross, {money.loss_at_stop_net}" in text
    assert f"Notional: {money.notional:.4f} USDT" in text
    assert "Equity used: 3625.09 USDT" in text
    assert outcome.short_id is not None
    # a second send of the same request is refused: its approvals are PENDING
    again = await rig.sender.send_request(request)
    assert again.status is SendStatus.REFUSED
    assert len(rig.bot.sent) == 1


async def test_the_tracer_card_can_only_be_approved_by_a_press() -> None:
    rig = Rig()
    outcome = await rig.sender.send_request(derive(new_source()))
    assert outcome.status is SendStatus.SENT
    assert all(a.status is ApprovalResult.PENDING for a in rig.approvals())
    assert not any(a.status is ApprovalResult.APPROVED for a in rig.approvals())
    assert not any("save_atomic" in entry for entry in rig.stores.trace)
    assert rig.trace == ["signal:NOTIFIED"]  # nothing but the notification moved


async def test_a_send_failure_leaves_both_approvals_pending_and_is_journaled() -> None:
    rig = Rig()
    rig.bot.queue_error(Forbidden("bot was blocked"))
    request = derive(new_source())

    outcome = await rig.sender.send_request(request)

    assert outcome.status is SendStatus.SEND_FAILED
    assert outcome.notified is False
    assert {a.status for a in rig.approvals()} == {ApprovalResult.PENDING}
    assert len(rig.approvals()) == 2
    assert rig.stores.signals[request.signal.signal_id].status is SignalStatus.DETECTED
    failed = rig.stores.journal_of_type("DEMO_APPROVAL_REQUEST_SEND_FAILED")
    assert len(failed) == 1
    assert "bot was blocked" not in failed[0].payload_json  # class name only
    assert rig.trace == []


async def test_a_notify_transition_failure_is_journaled_and_the_card_stays_pending() -> None:
    rig = Rig()
    rig.entities.fail_on.add("signal")
    request = derive(new_source())

    outcome = await rig.sender.send_request(request)

    assert outcome.status is SendStatus.SENT
    assert outcome.notified is False
    assert {a.status for a in rig.approvals()} == {ApprovalResult.PENDING}
    (event,) = rig.stores.journal_of_type(EVENT_SIGNAL_NOTIFY_FAILED)
    assert "RuntimeError" in event.payload_json


async def test_missing_money_issues_nothing() -> None:
    rig = Rig()
    rig.money_for = lambda request: None
    outcome = await rig.sender.send_request(derive(new_source()))
    assert outcome.status is SendStatus.NOT_ISSUED
    assert rig.approvals() == []
    assert rig.bot.sent == []
    assert rig.journal_events[-1].event_type == EVENT_REQUEST_NOT_ISSUED
    assert rig.journal_events[-1].signal_id is None  # no row exists to point at


async def test_a_money_builder_that_raises_issues_nothing() -> None:
    rig = Rig()

    def boom(request: SignalRequest) -> MoneyAtStake:
        raise ValueError("secret detail")

    rig.money_for = boom
    outcome = await rig.sender.send_request(derive(new_source()))
    assert outcome.status is SendStatus.NOT_ISSUED
    assert outcome.reason == "ValueError"
    assert rig.approvals() == []
    assert "secret detail" not in rig.journal_events[-1].payload_json


async def test_a_reservation_registration_failure_sends_no_card() -> None:
    rig = Rig()

    def fail(request: SignalRequest, money: MoneyAtStake, now: datetime) -> None:
        raise RuntimeError("db down")

    rig.sender._register_reservation = fail
    outcome = await rig.sender.send_request(derive(new_source()))
    assert outcome.status is SendStatus.NOT_ISSUED
    assert outcome.reason is not None and "RuntimeError" in outcome.reason
    assert rig.bot.sent == []
    assert {a.status for a in rig.approvals()} == {ApprovalResult.PENDING}


@pytest.mark.parametrize("field_name", ["signal_status", "plan_status", "expired"])
async def test_a_request_that_is_not_a_fresh_pending_one_is_refused(field_name: str) -> None:
    rig = Rig()
    request = derive(new_source())
    if field_name == "signal_status":
        signal = Signal(**{**request.signal.__dict__, "status": SignalStatus.NOTIFIED})
        request = SignalRequest(**{**request.__dict__, "signal": signal})
    elif field_name == "plan_status":
        plan = TradePlan(**{**request.plan.__dict__, "status": TradePlanStatus.READY})
        request = SignalRequest(**{**request.__dict__, "plan": plan})
    else:
        rig.now = request.plan.expiry_utc
    outcome = await rig.sender.send_request(request)
    assert outcome.status is SendStatus.REFUSED
    assert rig.approvals() == []
    assert rig.bot.sent == []


# --------------------------------------------------------------------------- #
# Task 2: the second-plan-per-symbol refusal.
# --------------------------------------------------------------------------- #


async def _first_card(rig: Rig) -> SignalRequest:
    request = derive(new_source("first"))
    outcome = await rig.sender.send_request(request)
    assert outcome.status is SendStatus.SENT
    return request


def _arm(rig: Rig, source_name: str) -> None:
    other = derive(new_source("other"))
    if source_name == "active_plan":
        rig.tracked.append(protection("BTCUSDT", ProtectionState.PROTECTED))
    elif source_name == "entry_intent":
        entry_intent(rig, other, ExecutionIntentStatus.SENT)
    elif source_name == "resting_entry":
        rig.positions.entry_orders = 1
    elif source_name == "open_position":
        rig.positions.quantity = D("0.004")
    elif source_name == "open_approval":
        rig.extra_approvals.append(OpenApproval("apv-x", "BTCUSDT", NOW + timedelta(minutes=5)))
    else:
        raise AssertionError(source_name)


@pytest.mark.parametrize(
    ("source_name", "label"),
    [
        ("active_plan", "ACTIVE_PLAN"),
        ("entry_intent", "UNRESOLVED_ENTRY_INTENT"),
        ("resting_entry", "RESTING_ENTRY_ORDER"),
        ("open_position", "OPEN_POSITION"),
        ("open_approval", "PENDING_OR_APPROVED_APPROVAL"),
    ],
)
async def test_a_second_plan_on_a_busy_symbol_is_refused_with_no_write(
    source_name: str, label: str
) -> None:
    rig = Rig()
    _arm(rig, source_name)
    request = derive(new_source())

    outcome = await rig.sender.send_request(request)

    assert outcome.status is SendStatus.REFUSED
    assert outcome.reason == REASON_CONFLICT == "CONFLICT_WITH_OPEN_POSITION" == NO_TRADE_CONFLICT
    assert outcome.sources == (label,)
    assert label in CONFLICT_SOURCES
    # nothing written, nothing sent
    assert rig.stores.signals == {}
    assert rig.stores.plans == {}
    assert rig.approvals() == []
    assert rig.bot.sent == []
    assert rig.reservations == []
    (event,) = [e for e in rig.journal_events if e.event_type == EVENT_REQUEST_REFUSED]
    assert event.signal_id is None and event.trade_plan_id is None
    assert label in event.payload_json and REASON_CONFLICT in event.payload_json


def test_the_refusal_covers_five_conflict_sources() -> None:
    assert len(CONFLICT_SOURCES) == 5
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith(
            "test_a_second_plan_on_a_busy_symbol"
        ):
            (mark,) = node.decorator_list
            assert isinstance(mark, ast.Call)
            cases = mark.args[1]
            assert isinstance(cases, ast.List)
            assert len(cases.elts) == 5
            return
    raise AssertionError("the refusal test is missing")


async def test_a_pending_card_blocks_a_second_one_through_the_real_store_reader() -> None:
    rig = Rig()
    await _first_card(rig)
    second = derive(new_source("second"))
    outcome = await rig.sender.send_request(second)
    assert outcome.status is SendStatus.REFUSED
    assert outcome.sources == ("PENDING_OR_APPROVED_APPROVAL",)
    assert len(rig.bot.sent) == 1


async def test_an_expired_open_approval_no_longer_blocks_the_symbol() -> None:
    rig = Rig()
    first = await _first_card(rig)
    rig.now = first.plan.expiry_utc + timedelta(seconds=1)
    later = derive(new_source("later"), observed_at=rig.now, latest_closed_bar_close=BAR_CLOSE)
    outcome = await rig.sender.send_request(later)
    assert outcome.status is SendStatus.SENT


@pytest.mark.parametrize("state", [ProtectionState.FLAT, ProtectionState.ENTRY_ENDED_NO_FILL])
async def test_a_finished_tracked_plan_does_not_block(state: ProtectionState) -> None:
    rig = Rig()
    rig.tracked.append(protection("BTCUSDT", state))
    outcome = await rig.sender.send_request(derive(new_source()))
    assert outcome.status is SendStatus.SENT


async def test_an_active_plan_on_another_symbol_does_not_block() -> None:
    rig = Rig()
    rig.tracked.append(protection("ETHUSDT", ProtectionState.PROTECTED))
    rig.extra_approvals.append(OpenApproval("apv-e", "ETHUSDT", NOW + timedelta(minutes=5)))
    outcome = await rig.sender.send_request(derive(new_source()))
    assert outcome.status is SendStatus.SENT


@pytest.mark.parametrize("which", ["position", "orders", "protections", "intents", "approvals"])
async def test_an_unreadable_source_refuses_fail_closed_with_the_class_name(which: str) -> None:
    rig = Rig()
    if which in ("position", "orders"):
        rig.positions.raise_on.add(which)
    elif which == "protections":

        def boom() -> tuple[PlanProtection, ...]:
            raise ConnectionError("db secret")

        rig.sender._protections = boom
    elif which == "intents":

        class BadIntents:
            def list_unresolved_intents(self) -> tuple[Any, ...]:
                raise ConnectionError("db secret")

        rig.sender._intents = BadIntents()
    else:

        def bad_reader() -> list[OpenApproval]:
            raise ConnectionError("db secret")

        rig.sender._approvals = bad_reader
    outcome = await rig.sender.send_request(derive(new_source()))

    assert outcome.status is SendStatus.REFUSED
    assert outcome.reason == REASON_UNCERTAIN
    assert len(outcome.sources) == 1
    assert "READ_FAILED" in outcome.sources[0]
    assert "TimeoutError" in outcome.sources[0] or "ConnectionError" in outcome.sources[0]
    assert rig.approvals() == [] and rig.bot.sent == []
    event = rig.journal_events[-1]
    assert event.event_type == EVENT_REQUEST_REFUSED
    assert "db secret" not in event.payload_json


async def test_a_conflict_wins_over_a_read_failure_and_lists_both() -> None:
    rig = Rig()
    rig.positions.quantity = D("1")
    rig.positions.raise_on.add("orders")
    outcome = await rig.sender.send_request(derive(new_source()))
    assert outcome.reason == REASON_CONFLICT
    assert outcome.sources[0] == "OPEN_POSITION"
    assert any("READ_FAILED" in s for s in outcome.sources)


async def test_two_concurrent_requests_for_one_symbol_send_only_one_card() -> None:
    import asyncio

    rig = Rig()
    first = derive(new_source("a"))
    second = derive(new_source("b"))
    outcomes = await asyncio.gather(rig.sender.send_request(first), rig.sender.send_request(second))
    assert sorted(o.status.value for o in outcomes) == ["REFUSED", "SENT"]
    assert len(rig.bot.sent) == 1


def test_the_open_approvals_reader_needs_demo_scoped_stores() -> None:
    with pytest.raises(ValueError):
        make_open_demo_approvals_reader(DemoStores(confirm_mode="SHADOW"))
    with pytest.raises(ValueError):
        make_open_demo_approvals_reader(DemoStores(confirm_mode=None))


def test_an_approval_of_a_closed_plan_does_not_count_as_open_until_its_expiry() -> None:
    """A plan moved to EXPIRED can never be confirmed, so it must not block the symbol for the rest
    of its lifetime (first Demo rehearsals: 26 minutes of waiting after a refused placement)."""
    stores = DemoStores(confirm_mode="DEMO")
    request = derive(new_source("closed"))
    stores.insert_signal(request.signal)
    stores.insert_trade_plan(request.plan)
    stores.insert_pending(
        Approval(
            approval_id="apv-closed",
            trade_plan_id=request.plan.trade_plan_id,
            signal_id=request.signal.signal_id,
            action=ApprovalAction.APPROVE,
            result=ApprovalResult.PENDING,
            status=ApprovalResult.PENDING,
            approval_token_hash="e" * 64,
            requested_at_utc=NOW,
            request_hash=request.plan.plan_hash,
        )
    )
    reader = make_open_demo_approvals_reader(stores)
    assert [a.approval_id for a in reader()] == ["apv-closed"]

    FakeEntities(stores, []).transition_trade_plan(
        request.plan.trade_plan_id, TradePlanStatus.EXPIRED, now_utc=NOW
    )

    assert reader() == []


async def test_a_shadow_pending_approval_does_not_block_a_demo_request() -> None:
    shared = DemoStores(confirm_mode="SHADOW")
    rig = Rig(stores=shared.scoped("DEMO"))  # type: ignore[arg-type]
    # a SHADOW card for BTCUSDT in the same database (its approval carries the SHADOW marker)
    shadow_request = derive(new_source("shadow"))
    shared.insert_signal(shadow_request.signal)
    shared.insert_trade_plan(shadow_request.plan)
    approval = Approval(
        approval_id="apv-shadow",
        trade_plan_id=shadow_request.plan.trade_plan_id,
        signal_id=shadow_request.signal.signal_id,
        action=ApprovalAction.APPROVE,
        result=ApprovalResult.PENDING,
        status=ApprovalResult.PENDING,
        approval_token_hash="f" * 64,
        requested_at_utc=NOW,
        request_hash=shadow_request.plan.plan_hash,
    )
    shared.insert_pending(approval)
    assert shared.approval_modes["apv-shadow"] == "SHADOW"
    outcome = await rig.sender.send_request(derive(new_source("demo")))
    assert outcome.status is SendStatus.SENT


# --------------------------------------------------------------------------- #
# Task 3: the D028 chain in the approval transaction, with the Phase 21 reservation.
# --------------------------------------------------------------------------- #

ACTED = NOW + timedelta(minutes=1)
GLOSSARY = (ROOT / "docs" / "GLOSSARY.md").read_text(encoding="utf-8")
DATA_MODEL = (ROOT / "docs" / "data" / "DATA_MODEL.md").read_text(encoding="utf-8")


def decided(
    approval: Approval, status: ApprovalResult, *, action: ApprovalAction | None = None
) -> Approval:
    return Approval(
        **{
            **approval.__dict__,
            "result": status,
            "status": status,
            "action": approval.action if action is None else action,
            "acted_at_utc": ACTED,
            "actor_id": "777001",
        }
    )


def row(rig: Rig, action: ApprovalAction) -> Approval:
    (found,) = [a for a in rig.stores.approvals.values() if a.action is action]
    return found


async def sent_chain_rig() -> tuple[Rig, SignalRequest]:
    rig = Rig(with_chain=True)
    request = derive(new_source())
    outcome = await rig.sender.send_request(request)
    assert outcome.status is SendStatus.SENT
    rig.trace.clear()
    return rig, request


async def test_approve_decides_reserves_then_moves_signal_then_plan() -> None:
    rig, request = await sent_chain_rig()
    approve = row(rig, ApprovalAction.APPROVE)

    rig.desk_stores.save_atomic(decided(approve, ApprovalResult.APPROVED), None)

    # D028 (GLOSSARY 2.1): Signal APPROVED -> TradePlan APPROVED; the reservation comes first
    assert rig.trace == ["reserve:APPROVED", "signal:APPROVED", "plan:APPROVED"]
    assert rig.stores.approvals[approve.approval_id].status is ApprovalResult.APPROVED
    assert rig.stores.signals[request.signal.signal_id].status is SignalStatus.APPROVED
    assert rig.stores.plans[request.plan.trade_plan_id].status is TradePlanStatus.APPROVED
    assert rig.db.reservations[request.plan.trade_plan_id] == "RESERVED"


@pytest.mark.parametrize(
    ("action", "signal_status"),
    [
        (ApprovalAction.SKIP_USER, SignalStatus.SKIPPED_USER),
        (ApprovalAction.CANCEL, SignalStatus.SKIPPED_USER),
        (ApprovalAction.SKIP_BUSY, SignalStatus.SKIPPED_BUSY),
    ],
)
async def test_skip_releases_the_reservation_and_skips_the_signal(
    action: ApprovalAction, signal_status: SignalStatus
) -> None:
    rig, request = await sent_chain_rig()
    skip = row(rig, ApprovalAction.SKIP_USER)

    rig.desk_stores.save_atomic(decided(skip, ApprovalResult.SKIPPED, action=action), None)

    assert rig.trace == ["release:APPROVAL_SKIPPED", f"signal:{signal_status.value}"]
    assert rig.stores.signals[request.signal.signal_id].status is signal_status
    assert rig.db.reservations[request.plan.trade_plan_id] == "RELEASED"
    # No plan state is named for a skip: the plan keeps APPROVAL_PENDING (it cannot be placed).
    assert rig.stores.plans[request.plan.trade_plan_id].status is TradePlanStatus.APPROVAL_PENDING


def test_the_skip_and_expiry_targets_are_the_ones_the_documents_name() -> None:
    # GLOSSARY 11.1: a NOTIFIED signal can go to SKIPPED_USER, SKIPPED_BUSY and EXPIRED.
    assert "NOTIFIED -> VIEWED, APPROVED, SKIPPED_USER, SKIPPED_BUSY, EXPIRED, INVALIDATED" in (
        GLOSSARY
    )
    assert "SKIPPED_USER -> (terminal)" in GLOSSARY
    # GLOSSARY 11.2: an APPROVAL_PENDING plan can go to APPROVED and EXPIRED; there is no skipped
    # plan state, and SUPERSEDED means replaced before the human decided.
    assert "APPROVAL_PENDING -> APPROVED, EXPIRED, INVALIDATED, SUPERSEDED" in GLOSSARY
    assert "`SUPERSEDED` means a plan replaced before the human decided" in GLOSSARY
    # GLOSSARY 2.1 and DATA_MODEL section 3 (D028): the approval order.
    assert "Signal APPROVED → TradePlan APPROVED → Order PLANNED" in GLOSSARY
    assert "`TradePlanStatus.APPROVED` authorizes execution handoff" in DATA_MODEL


async def test_expiry_releases_the_reservation_and_expires_signal_and_plan() -> None:
    rig, request = await sent_chain_rig()
    approve = row(rig, ApprovalAction.APPROVE)
    skip = row(rig, ApprovalAction.SKIP_USER)

    rig.desk_stores.save_atomic(decided(approve, ApprovalResult.EXPIRED), None)
    rig.desk_stores.save_atomic(decided(skip, ApprovalResult.EXPIRED), None)  # the sibling too

    assert rig.trace == [
        "release:APPROVAL_EXPIRED",
        "signal:EXPIRED",
        "plan:EXPIRED",
        "release:APPROVAL_EXPIRED",
        "signal:EXPIRED",
        "plan:EXPIRED",
    ]
    assert rig.stores.signals[request.signal.signal_id].status is SignalStatus.EXPIRED
    assert rig.stores.plans[request.plan.trade_plan_id].status is TradePlanStatus.EXPIRED
    assert rig.db.reservations[request.plan.trade_plan_id] == "RELEASED"


@pytest.mark.parametrize("failing", ["plan", "signal"])
async def test_a_transition_failure_rolls_decision_reservation_and_transitions_back(
    failing: str,
) -> None:
    rig, request = await sent_chain_rig()
    approve = row(rig, ApprovalAction.APPROVE)
    rig.entities.fail_on.add(failing)

    with pytest.raises(RuntimeError):
        rig.desk_stores.save_atomic(decided(approve, ApprovalResult.APPROVED), None)

    assert rig.stores.approvals[approve.approval_id].status is ApprovalResult.PENDING
    assert rig.db.reservations[request.plan.trade_plan_id] == "REQUESTED"
    assert rig.stores.signals[request.signal.signal_id].status is SignalStatus.NOTIFIED
    assert rig.stores.plans[request.plan.trade_plan_id].status is TradePlanStatus.APPROVAL_PENDING
    if failing == "plan":
        # the signal move happened inside the transaction and was undone with it
        assert rig.trace == ["reserve:APPROVED", "signal:APPROVED", "plan:APPROVED"]


async def test_a_refused_reservation_stops_the_chain_before_any_transition() -> None:
    rig, request = await sent_chain_rig()
    approve = row(rig, ApprovalAction.APPROVE)
    rig.reservation_store.refuse = True

    with pytest.raises(ReservationRefused):
        rig.desk_stores.save_atomic(decided(approve, ApprovalResult.APPROVED), None)

    assert rig.trace == ["reserve:APPROVED"]
    assert rig.stores.approvals[approve.approval_id].status is ApprovalResult.PENDING
    assert rig.stores.signals[request.signal.signal_id].status is SignalStatus.NOTIFIED


async def test_a_signal_that_was_never_notified_cannot_be_approved() -> None:
    rig = Rig(with_chain=True)
    rig.entities.fail_on.add("signal")  # the NOTIFIED move fails after the send
    request = derive(new_source())
    outcome = await rig.sender.send_request(request)
    assert outcome.status is SendStatus.SENT and outcome.notified is False
    rig.entities.fail_on.clear()
    rig.trace.clear()
    approve = row(rig, ApprovalAction.APPROVE)

    with pytest.raises(Exception, match="illegal SIGNAL transition: DETECTED -> APPROVED"):
        rig.desk_stores.save_atomic(decided(approve, ApprovalResult.APPROVED), None)

    assert rig.stores.approvals[approve.approval_id].status is ApprovalResult.PENDING
    assert rig.db.reservations[request.plan.trade_plan_id] == "REQUESTED"
    assert rig.stores.signals[request.signal.signal_id].status is SignalStatus.DETECTED


def test_the_chain_refuses_an_undecided_or_unstamped_approval() -> None:
    stores = DemoStores(confirm_mode="DEMO")
    entities = FakeEntities(stores, [])
    request = derive(new_source())
    pending = Approval(
        approval_id="a" * 32,
        trade_plan_id=request.plan.trade_plan_id,
        signal_id=request.signal.signal_id,
        action=ApprovalAction.APPROVE,
        result=ApprovalResult.PENDING,
        status=ApprovalResult.PENDING,
        approval_token_hash="f" * 64,
        requested_at_utc=NOW,
        request_hash=request.plan.plan_hash,
    )
    # The domain object refuses these states itself; the chain re-checks them defensively.
    unstamped = decided(pending, ApprovalResult.APPROVED)
    object.__setattr__(unstamped, "acted_at_utc", None)
    with pytest.raises(ValueError, match="acted_at_utc"):
        apply_d028_chain(entities, cast(Any, object()), unstamped)
    undecided = decided(pending, ApprovalResult.APPROVED)
    object.__setattr__(undecided, "status", ApprovalResult.PENDING)
    with pytest.raises(ValueError, match="decided approval"):
        apply_d028_chain(entities, cast(Any, object()), undecided)
    skip_as_approval = decided(pending, ApprovalResult.APPROVED, action=ApprovalAction.SKIP_USER)
    with pytest.raises(ValueError, match="APPROVE action"):
        apply_d028_chain(entities, cast(Any, object()), skip_as_approval)


async def test_a_press_runs_the_chain_and_a_failed_chain_approves_nothing() -> None:
    rig = Rig(with_chain=True)
    request = derive(new_source())
    outcome = await rig.sender.send_request(request)
    assert outcome.short_id is not None
    rig.now = ACTED
    rig.entities.fail_on.add("plan")

    failed = await rig.tap("APR", outcome.short_id, query_id="q-fail")

    assert isinstance(failed, DispatchResult)
    assert all(a.status is ApprovalResult.PENDING for a in rig.approvals())
    assert rig.stores.signals[request.signal.signal_id].status is SignalStatus.NOTIFIED

    rig.entities.fail_on.clear()
    await rig.tap("APR", outcome.short_id, query_id="q-ok")

    approve = row(rig, ApprovalAction.APPROVE)
    assert approve.status is ApprovalResult.APPROVED
    assert rig.stores.signals[request.signal.signal_id].status is SignalStatus.APPROVED
    assert rig.stores.plans[request.plan.trade_plan_id].status is TradePlanStatus.APPROVED
    assert rig.db.reservations[request.plan.trade_plan_id] == "RESERVED"


# --------------------------------------------------------------------------- #
# Structure guards.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("module", ["signal_source", "approval_sender"])
def test_the_modules_import_no_paper_pipeline_and_never_place(module: str) -> None:
    source = (ROOT / "src" / "live" / f"{module}.py").read_text(encoding="utf-8")
    assert "src.paper" not in source
    tree = ast.parse(source)
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {
        n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
    }
    assert not names & {
        "execute_approved_plan",
        "place_entry",
        "place_algo_protective",
        "place_market_close",
    }


def test_no_float_constructor_in_the_new_modules() -> None:
    for module in ("signal_source", "approval_sender"):
        tree = ast.parse((ROOT / "src" / "live" / f"{module}.py").read_text(encoding="utf-8"))
        floats = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "float"
        ]
        assert floats == []


# --------------------------------------------------------------------------- #
# Task 3 on PostgreSQL: the composed save_atomic against the real stores. Needs TEST_DATABASE_URL
# (skips without it; TRADING_CI_STRICT=1 turns the skip into a failure). Not run on the dev
# machine of plan 24-14 (no PostgreSQL there): run it before the phase gate.
# --------------------------------------------------------------------------- #
PG_NOW = datetime(2026, 10, 23, 10, 0, tzinfo=UTC)
PG_ACTED = datetime(2026, 10, 23, 10, 30, tzinfo=UTC)
PG_PLAN = hexid(0x1001)
PG_SIGNAL = hexid(1)
PG_APPROVE = hexid(0x2001)
PG_SKIP = hexid(0x2002)
PG_RATES: dict[str, Any] = {
    "max_open_positions": 2,
    "max_aggregate_open_risk": D("0.01"),
    "cluster_cap": D("0.006"),
    "daily_loss_warning_threshold": D("0.005"),
    "daily_loss_stop_threshold": D("0.01"),
}


@dataclass
class PgRig:
    engine: Engine
    db: OperationalDatabase
    approvals: PgApprovalStore
    reservations: PgRiskReservationStore
    entities: PgTradingEntityStore

    def save_atomic(self) -> Any:
        return make_demo_save_atomic(
            approvals=self.approvals,
            reservations=self.reservations,
            entities=self.entities,
            parameter_set=PG_RATES,
            daily_loss_quote=lambda _day: D("0"),
        )

    def decision(
        self, approval_id: str, action: ApprovalAction, status: ApprovalResult
    ) -> Approval:
        return Approval(
            approval_id=approval_id,
            trade_plan_id=PG_PLAN,
            signal_id=PG_SIGNAL,
            action=action,
            result=status,
            status=status,
            approval_token_hash=hexid(0x3001 if approval_id == PG_APPROVE else 0x3002),
            requested_at_utc=PG_NOW,
            acted_at_utc=PG_ACTED,
            actor_id="operator",
            request_hash="e" * 64,
        )


def _pg_rig(pg_db: str, *, signal_status: str) -> Iterator[PgRig]:
    engine = make_sync_engine(pg_db)
    try:
        insert_and_commit(
            engine,
            make_signal(1, status=signal_status),
            make_plan(1, 1, status="APPROVAL_PENDING", plan_hash="a" * 64),
            make_approval(1, 1, 1),
            make_approval(2, 1, 1, action="SKIP_USER"),
        )
        db = OperationalDatabase(engine)
        PgDayRiskStore(db).open_day(
            DayRiskState(
                utc_day=PG_NOW.date(),
                equity_at_day_start=D("1000"),
                base_observed_at_utc=datetime(2026, 10, 23, 0, 5, tzinfo=UTC),
            )
        )
        reservations = PgRiskReservationStore(db)
        reservations.register_request(
            ReservationRequest(
                trade_plan_id=PG_PLAN,
                plan_hash="a" * 64,
                symbol="BTCUSDT",
                position_side="LONG",
                quantity=D("0.001"),
                realized_risk=D("4"),
            ),
            now_utc=PG_NOW,
        )
        yield PgRig(engine, db, PgApprovalStore(db), reservations, PgTradingEntityStore(db))
    finally:
        engine.dispose()


@pytest.fixture
def pg_notified(pg_db: str) -> Iterator[PgRig]:
    yield from _pg_rig(pg_db, signal_status="NOTIFIED")


@pytest.fixture
def pg_detected(pg_db: str) -> Iterator[PgRig]:
    yield from _pg_rig(pg_db, signal_status="DETECTED")


def _status(engine: Engine, table: str, column: str, key: str) -> str:
    with engine.connect() as conn:
        return str(
            conn.execute(
                text(f"SELECT status FROM {table} WHERE {column} = :k"),  # noqa: S608 - constants
                {"k": key},
            ).scalar_one()
        )


def test_pg_approve_reserves_and_moves_signal_then_plan_in_one_transaction(
    pg_notified: PgRig,
) -> None:
    rig = pg_notified
    approve = rig.decision(PG_APPROVE, ApprovalAction.APPROVE, ApprovalResult.APPROVED)

    rig.save_atomic()(approve, None)

    assert _status(rig.engine, "approvals", "approval_id", PG_APPROVE) == "APPROVED"
    assert _status(rig.engine, "signals", "signal_id", PG_SIGNAL) == "APPROVED"
    assert _status(rig.engine, "trade_plans", "trade_plan_id", PG_PLAN) == "APPROVED"
    record = rig.reservations.get(PG_PLAN)
    assert record is not None and record.status is ReservationStatus.RESERVED
    assert record.approval_id == PG_APPROVE


def test_pg_skip_releases_the_reservation_and_skips_the_signal(pg_notified: PgRig) -> None:
    rig = pg_notified
    skip = rig.decision(PG_SKIP, ApprovalAction.SKIP_USER, ApprovalResult.SKIPPED)

    rig.save_atomic()(skip, None)

    assert _status(rig.engine, "approvals", "approval_id", PG_SKIP) == "SKIPPED"
    assert _status(rig.engine, "signals", "signal_id", PG_SIGNAL) == "SKIPPED_USER"
    assert _status(rig.engine, "trade_plans", "trade_plan_id", PG_PLAN) == "APPROVAL_PENDING"
    record = rig.reservations.get(PG_PLAN)
    assert record is not None and record.status is ReservationStatus.RELEASED
    assert record.release_reason is ReleaseReason.APPROVAL_SKIPPED


def test_pg_expiry_releases_the_reservation_and_expires_signal_and_plan(
    pg_notified: PgRig,
) -> None:
    rig = pg_notified
    expired = rig.decision(PG_APPROVE, ApprovalAction.APPROVE, ApprovalResult.EXPIRED)

    rig.save_atomic()(expired, None)

    assert _status(rig.engine, "approvals", "approval_id", PG_APPROVE) == "EXPIRED"
    assert _status(rig.engine, "signals", "signal_id", PG_SIGNAL) == "EXPIRED"
    assert _status(rig.engine, "trade_plans", "trade_plan_id", PG_PLAN) == "EXPIRED"
    record = rig.reservations.get(PG_PLAN)
    assert record is not None and record.status is ReservationStatus.RELEASED


def test_pg_a_transition_failure_rolls_the_decision_and_the_reservation_back(
    pg_detected: PgRig,
) -> None:
    rig = pg_detected  # a DETECTED signal cannot become APPROVED: the chain raises
    approve = rig.decision(PG_APPROVE, ApprovalAction.APPROVE, ApprovalResult.APPROVED)

    with pytest.raises(IllegalTransition):
        rig.save_atomic()(approve, None)

    assert _status(rig.engine, "approvals", "approval_id", PG_APPROVE) == "PENDING"
    assert _status(rig.engine, "signals", "signal_id", PG_SIGNAL) == "DETECTED"
    assert _status(rig.engine, "trade_plans", "trade_plan_id", PG_PLAN) == "APPROVAL_PENDING"
    record = rig.reservations.get(PG_PLAN)
    assert record is not None and record.status is ReservationStatus.REQUESTED
