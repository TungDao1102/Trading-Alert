"""The DEMO/LIVE two-step confirm flow (Phase 23, plan 23-12; D041, D-06, D-09 to D-13).

The flow is driven through the real `on_callback` entry point with the flow's own callback keyword
set (the desk's resolver and dispatcher, the flow's reply, approved, confirm and finalize hooks), so
the wiring is under test and not only the methods. No network, no real Telegram, no placement:
`on_confirmed` is a recording stub, the only seam to placement (Phase 24 connects it).
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from functools import partial
from typing import Any, cast

import pytest
from scripts.gen_phase23_fixtures import fixture_money
from src.adapters.telegram_callbacks import DispatchResult, on_callback
from src.approval.confirm_core import (
    DEMO_CONFIRM_PROFILE,
    LIVE_CONFIRM_PROFILE,
    ConfirmProfile,
)
from src.domain.approval import Approval
from src.domain.enums import (
    ApprovalAction,
    ApprovalResult,
    ExecutionIntentStatus,
    OrderRole,
    TradePlanStatus,
)
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.execution.approval_desk import ApprovalDesk, IssuedRequest
from src.execution.confirm_flow import ConfirmFlow, make_confirm_flow
from src.execution.confirm_recheck import (
    ConfirmInputs,
    PrefetchedConfirmInputs,
    make_confirm_recheck,
    prefetched_provider,
)
from src.execution.intent_store import IntentRecord
from src.execution.pre_placement import PrePlacementInputs, check_remaining_validity
from src.ops.alert_wording import reconciliation_required_text

from tests.shadow_fakes import (
    AUTHORIZED_USER_IDS,
    CHAT_ID,
    T0,
    USER_ID,
    FakeBot,
    InMemoryShadowStores,
    RecordingSleep,
    keyboard_buttons,
    make_callback_update,
    make_shadow_plan,
    make_shadow_signal,
)
from tests.support.intent_store_fakes import InMemoryExecutionIntentStore

D = Decimal
PLAN_EXPIRY_TEXT = "2026-10-09 07:00:00 UTC"

# The card of the 23-02 LONG fixture, issued at T0 with a mark of 50050 and a 600 s minimum. Every
# amount is the stored value; the golden file of the generator carries the same text (Task 3).
DEMO_CARD = "\n".join(
    [
        "CONFIRM BTCUSDT LONG",
        "Mode: DEMO",
        "Quantity: 0.08",
        "Notional: 4008.00 USDT",
        "Loss at SL: 48.00 USDT gross, 53.5776 USDT net of modeled costs",
        "Mark price: 50050 (entry 50100, SL 49500)",
        f"Remaining validity: 14400 s to the plan expiry {PLAN_EXPIRY_TEXT}; "
        "placement check: passes",
        "Confirm until 2026-10-09 03:01:00 UTC (60 s window)",
    ]
)


@dataclass
class Rig:
    mode: str = "DEMO"
    min_validity: int | None = 600
    mark: Decimal | None = D("50050")
    prefetch_mark: Decimal | None = D("50050")
    prefetch_error: Exception | None = None
    plan_overrides: dict[str, Any] = field(default_factory=dict)
    now: datetime = T0
    stores: InMemoryShadowStores = field(default_factory=InMemoryShadowStores)
    intents: InMemoryExecutionIntentStore = field(default_factory=InMemoryExecutionIntentStore)
    sleep: RecordingSleep = field(default_factory=RecordingSleep)
    holder: PrefetchedConfirmInputs = field(default_factory=PrefetchedConfirmInputs)
    confirmed: list[tuple[Approval, TradePlan, datetime]] = field(default_factory=list)
    intent_on_confirm: ExecutionIntentStatus | None = None
    prefetch_calls: int = 0

    def __post_init__(self) -> None:
        self.bot = FakeBot.for_mode(self.mode)
        self.profile: ConfirmProfile = (
            DEMO_CONFIRM_PROFILE if self.mode == "DEMO" else LIVE_CONFIRM_PROFILE
        )
        self.desk = ApprovalDesk(
            self.stores,
            profile=self.profile,
            clock=lambda: self.now,
            intent_reader=lambda approval_id: self.intents.get_entry(approval_id=approval_id),
        )
        self.signal = make_shadow_signal()
        self.plan = make_shadow_plan(self.signal, **self.plan_overrides)
        self.flow = self.make_flow()

    # ---- the seams ------------------------------------------------------------------- #

    def on_confirmed(self, approval: Approval, plan: TradePlan, confirmed_at: datetime) -> None:
        self.confirmed.append((approval, plan, confirmed_at))
        if self.intent_on_confirm is not None:
            self.set_entry_intent(approval.approval_id, self.intent_on_confirm)

    async def prefetch(self, signal: Signal, plan: TradePlan) -> None:
        self.prefetch_calls += 1
        if self.prefetch_error is not None:
            raise self.prefetch_error
        if self.prefetch_mark is None:
            return
        self.holder.put(
            plan.trade_plan_id,
            ConfirmInputs(pre_placement=self.inputs(signal, plan), position_mode="ONE_WAY"),
        )

    def inputs(self, signal: Signal, plan: TradePlan) -> PrePlacementInputs:
        assert self.prefetch_mark is not None
        return PrePlacementInputs(
            side=signal.direction,
            plan_status=TradePlanStatus.APPROVED,
            signal_invalidated=False,
            trade_plan=plan,
            latest_closed_bar_close=D("50050"),
            expiry_utc=plan.expiry_utc,
            now_utc=self.now,
            min_remaining_validity_seconds=600,
            gtd_clock_margin=timedelta(seconds=2),
            position_symbols=frozenset(),
            open_order_symbols=frozenset(),
            any_unprotected=False,
            symbol=signal.symbol,
            mark_price=self.prefetch_mark,
            mark_time_utc=self.now - timedelta(seconds=1),
            mark_checked_at_utc=self.now,
            max_mark_price_age_ms=5000,
            last_price=self.prefetch_mark,
            last_time_utc=self.now - timedelta(seconds=1),
            last_checked_at_utc=self.now,
            max_last_price_age_ms=3000,
            sl_trigger_price=plan.stop_loss_price,
            entry_min_price=plan.entry_min_price,
            entry_max_price=plan.entry_max_price,
        )

    def make_flow(self, **overrides: Any) -> ConfirmFlow:
        values: dict[str, Any] = {
            "desk": self.desk,
            "profile": self.profile,
            "stores": self.stores,
            "clock": lambda: self.now,
            "bot": self.bot,
            "sleep": self.sleep,
            "mark_price": lambda symbol: self.mark,
            "validity_rule": partial(
                check_remaining_validity,
                min_remaining_validity_seconds=self.min_validity,
                gtd_clock_margin=timedelta(seconds=2),
            ),
            "recheck": make_confirm_recheck(prefetched_provider(self.holder)),
            "on_confirmed": self.on_confirmed,
            "prefetch": self.prefetch,
        }
        values.update(overrides)
        return make_confirm_flow(**values)

    # ---- driving ----------------------------------------------------------------------- #

    def issue(self) -> IssuedRequest:
        return self.desk.issue(
            signal=self.signal,
            plan=self.plan,
            money=fixture_money(),
            exposure_quote=D("0"),
            reason_codes=["TREND_OK"],
            now_utc=T0,
        )

    async def issue_and_send(self) -> IssuedRequest:
        issued = self.issue()
        outcome = await self.desk.send(self.bot, chat_id=CHAT_ID, issued=issued, sleep=self.sleep)
        assert outcome.sent
        return issued

    async def tap(
        self,
        prefix: str,
        short_id: str,
        *,
        query_id: str,
        user_id: int | None = USER_ID,
        chat_id: int = CHAT_ID,
        chat_type: str | None = "private",
        message_id: int | None = 1,
        flow: ConfirmFlow | None = None,
    ) -> DispatchResult:
        update = make_callback_update(
            data=f"{prefix}:{short_id}",
            chat_id=chat_id,
            query_id=query_id,
            message_chat_id=chat_id,
            from_user_id=user_id,
            message_id=message_id,
            chat_type=chat_type,
        )
        active = self.flow if flow is None else flow
        return await on_callback(
            update,
            cast(Any, None),
            **active.callback_kwargs(
                authorized_chat_id=CHAT_ID,
                authorized_user_ids=AUTHORIZED_USER_IDS,
                error_journal=self.stores.record_journal,
            ),
        )

    async def approve(self, short_id: str, *, query_id: str = "q-apr") -> DispatchResult:
        return await self.tap("APR", short_id, query_id=query_id)

    def row(self, action: ApprovalAction) -> Approval:
        (found,) = [a for a in self.stores.approvals.values() if a.action is action]
        return found

    def set_entry_intent(self, approval_id: str, status: ExecutionIntentStatus) -> None:
        ok = self.intents.consume_and_record_entry_intent(
            approval_id=approval_id,
            trade_plan_id=self.plan.trade_plan_id,
            plan_hash=self.plan.plan_hash,
            client_order_id="cid-1",
            symbol="BTCUSDT",
            side="BUY",
            intended_quantity=D("0.08"),
            intended_price=D("50050"),
            approved_quantity=D("0.08"),
            now_utc=self.now,
        )
        assert ok
        stored = self.intents.get_entry(approval_id=approval_id)
        assert stored is not None
        if status is not ExecutionIntentStatus.INTENDED:
            self.intents._rows[(approval_id, OrderRole.ENTRY.value)] = IntentRecord(
                **{**stored.__dict__, "intent_status": status}
            )

    def journal_types(self) -> list[str]:
        return [event.event_type for event in self.stores.journal]


def buttons_of(message: Any) -> list[tuple[str, str]]:
    return keyboard_buttons(message.reply_markup)


# --------------------------------------------------------------------------- #
# Task 1 (tracer): APPROVE edits the request into the card; one CONFIRM reaches on_confirmed.
# --------------------------------------------------------------------------- #


def test_make_confirm_flow_needs_on_confirmed_and_serves_demo_or_live_only() -> None:
    signature = inspect.signature(make_confirm_flow)
    assert signature.parameters["on_confirmed"].default is inspect.Parameter.empty
    assert signature.parameters["on_confirmed"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["prefetch"].default is None
    assert signature.parameters["ttl_seconds"].default == 60
    rig = Rig()
    with pytest.raises(ValueError):
        rig.make_flow(profile=LIVE_CONFIRM_PROFILE)  # the desk serves DEMO


async def test_approve_edits_the_request_into_the_confirmation_card() -> None:
    rig = Rig()
    issued = await rig.issue_and_send()
    short = issued.mapping.short_id

    result = await rig.approve(short)

    assert result.ok
    approve = rig.row(ApprovalAction.APPROVE)
    assert approve.status is ApprovalResult.APPROVED
    assert approve.actor_id == str(USER_ID) == "777001"
    (edit,) = rig.bot.edited
    assert edit.message_id == 1
    assert edit.text == DEMO_CARD
    assert buttons_of(edit) == [("CONFIRM", f"CNF:{short}"), ("CANCEL", f"CXL:{short}")]
    assert len(rig.bot.sent) == 1, "the card replaces the request, no extra message"
    assert rig.journal_types().count("DEMO_CONFIRM_ISSUED") == 1
    (issued_event,) = rig.stores.journal_of_type("DEMO_CONFIRM_ISSUED")
    payload = json.loads(issued_event.payload_json)
    assert payload["delivery"] == "edit" and payload["message_id"] == "1"
    assert "DEMO_CONFIRMED" not in rig.journal_types()
    assert rig.confirmed == [], "APPROVE alone never reaches the placement seam"
    assert rig.prefetch_calls == 0


async def test_confirm_by_the_approving_user_reaches_on_confirmed_once_and_finalizes() -> None:
    rig = Rig()
    issued = await rig.issue_and_send()
    short = issued.mapping.short_id
    await rig.approve(short)
    rig.now = T0 + timedelta(seconds=30)

    result = await rig.tap("CNF", short, query_id="q-cnf")

    assert result.ok
    assert rig.prefetch_calls == 1
    (confirmed_event,) = rig.stores.journal_of_type("DEMO_CONFIRMED")
    assert json.loads(confirmed_event.payload_json)["approving_user_id"] == "777001"
    ((approval, plan, confirmed_at),) = rig.confirmed
    assert approval.approval_id == rig.row(ApprovalAction.APPROVE).approval_id
    assert plan.plan_hash == rig.plan.plan_hash
    assert confirmed_at == T0 + timedelta(seconds=30)
    assert len(rig.bot.edited) == 2
    final = rig.bot.edited[-1]
    assert final.message_id == 1
    assert final.reply_markup.inline_keyboard == ()
    assert final.text.splitlines()[:5] == DEMO_CARD.splitlines()[:5]
    assert "CONFIRMED by user 777001 at 2026-10-09 03:00:30 UTC" in final.text
    assert "Placement: handed to the execution step; no entry recorded yet" in final.text
    assert len(rig.bot.sent) == 1, "a fresh CONFIRM sends no extra message"


@pytest.mark.parametrize(
    ("status", "label"),
    [
        (ExecutionIntentStatus.ACKED, "already executed"),
        (ExecutionIntentStatus.UNKNOWN, "needs reconciliation"),
        (ExecutionIntentStatus.SENT, "needs reconciliation"),
        (ExecutionIntentStatus.INTENDED, "needs reconciliation"),
        (ExecutionIntentStatus.REJECTED, "rejected"),
    ],
)
async def test_the_confirmed_card_shows_the_stored_entry_outcome(
    status: ExecutionIntentStatus, label: str
) -> None:
    rig = Rig()
    rig.intent_on_confirm = status
    issued = await rig.issue_and_send()
    await rig.approve(issued.mapping.short_id)

    await rig.tap("CNF", issued.mapping.short_id, query_id="q-cnf")

    final = rig.bot.edited[-1].text
    assert f"Placement: {label}" in final
    if label == "needs reconciliation":
        assert reconciliation_required_text() in final
        assert "rejected" not in final.lower()
    assert len(rig.confirmed) == 1
