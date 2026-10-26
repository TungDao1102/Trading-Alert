"""The DEMO/LIVE approval desk (Phase 23, plan 23-11): one request, SKIP recorded, final messages.

The desk is driven through the real `on_callback` entry point with the desk's own resolver,
dispatcher, reply function and finalize hook, so the wiring is under test, not only the methods.
No network, no real Telegram, no placement: fakes only (D-17).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from src.adapters.telegram_callbacks import DispatchResult, on_callback
from src.adapters.telegram_notify import (
    build_decision_keyboard,
    format_approval_request,
    format_utc,
)
from src.approval.confirm_core import (
    DEMO_CONFIRM_PROFILE,
    LIVE_CONFIRM_PROFILE,
    SHADOW_CONFIRM_PROFILE,
)
from src.backtest.semantics import TP1_QUANTITY_FRACTION
from src.domain.enums import (
    ApprovalAction,
    ApprovalResult,
    ExecutionIntentStatus,
    OrderRole,
)
from src.execution.approval_desk import (
    NO_HANDLER_REPLY,
    ApprovalDesk,
    DeskStores,
    IssuedRequest,
)
from src.execution.intent_store import IntentRecord
from src.ops.alert_wording import reconciliation_required_text
from src.risk.cost_rates import FEE_SOURCE_PARAMETER, CostRates
from src.risk.money_at_stake import (
    EQUITY_SOURCE_PAPER_CONFIG,
    LEVERAGE_SOURCE_PAPER_CONFIG,
    MONEY_AT_STAKE_MISSING,
    MoneyAtStake,
    MoneyAtStakeUnavailable,
    build_money_at_stake,
    money_canonical_json,
)
from src.risk.types import SizedResult
from telegram.error import Forbidden, RetryAfter

from tests.shadow_fakes import (
    AUTHORIZED_USER_IDS,
    CHAT_ID,
    OTHER_CHAT_ID,
    STRANGER_USER_ID,
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
PRESS_AT = T0 + timedelta(minutes=5)
ACTED = "2026-10-09 03:05:00 UTC"


def make_desk_money(**overrides: Any) -> MoneyAtStake:
    """The money block of the shadow-fakes LONG plan: quantity 0.08, stop 49500, TP 51000/52000."""
    sized = SizedResult(
        is_no_trade=False,
        quantity=D("0.08"),
        quantity_before_rounding=D("0.08"),
        quantity_after_rounding=D("0.08"),
        quantization_decision="ACCEPTED",
        realized_risk=D("50"),
        modeled_costs_per_unit=D("20"),
        sizing_entry_price=D("50100"),
    )
    values: dict[str, Any] = {
        "side": "LONG",
        "sized": sized,
        "stop_loss_price": D("49500"),
        "take_profits": [
            (D("51000"), TP1_QUANTITY_FRACTION),
            (D("52000"), D(1) - TP1_QUANTITY_FRACTION),
        ],
        "cost_rates": CostRates(
            fee_rate_entry=D("0.0005"),
            entry_slippage_rate=D("0.0002"),
            fee_rate_exit=D("0.0005"),
            exit_slippage_rate=D("0.0002"),
            fee_source=FEE_SOURCE_PARAMETER,
        ),
        "leverage": 5,
        "leverage_source": LEVERAGE_SOURCE_PAPER_CONFIG,
        "equity": D("1000"),
        "equity_source": EQUITY_SOURCE_PAPER_CONFIG,
        "equity_observed_at_utc": T0,
    }
    values.update(overrides)
    return build_money_at_stake(**values)


@dataclass
class Rig:
    mode: str = "DEMO"
    stores: InMemoryShadowStores = field(default_factory=InMemoryShadowStores)
    intents: InMemoryExecutionIntentStore = field(default_factory=InMemoryExecutionIntentStore)
    sleep: RecordingSleep = field(default_factory=RecordingSleep)
    now: datetime = PRESS_AT

    def __post_init__(self) -> None:
        self.bot = FakeBot.for_mode(self.mode)
        profile = DEMO_CONFIRM_PROFILE if self.mode == "DEMO" else LIVE_CONFIRM_PROFILE
        self.desk = ApprovalDesk(
            self.stores,
            profile=profile,
            clock=lambda: self.now,
            intent_reader=lambda approval_id: self.intents.get_entry(approval_id=approval_id),
        )
        self.signal = make_shadow_signal()
        self.plan = make_shadow_plan(self.signal)

    def issue(self, **overrides: Any) -> IssuedRequest:
        values: dict[str, Any] = {
            "signal": self.signal,
            "plan": self.plan,
            "money": make_desk_money(),
            "exposure_quote": D("0"),
            "reason_codes": ["TREND_OK"],
            "now_utc": T0,
        }
        values.update(overrides)
        return self.desk.issue(**values)

    async def issue_and_send(self) -> IssuedRequest:
        issued = self.issue()
        outcome = await self.desk.send(
            self.bot, chat_id=CHAT_ID, issued=issued, sleep=self.sleep
        )
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

    def row(self, action: ApprovalAction) -> Any:
        (found,) = [a for a in self.stores.approvals.values() if a.action is action]
        return found

    def record_entry_intent(self, status: ExecutionIntentStatus) -> None:
        approve = self.row(ApprovalAction.APPROVE)
        ok = self.intents.consume_and_record_entry_intent(
            approval_id=approve.approval_id,
            trade_plan_id=self.plan.trade_plan_id,
            plan_hash=self.plan.plan_hash,
            client_order_id="cid-1",
            symbol="BTCUSDT",
            side="BUY",
            intended_quantity=D("0.08"),
            intended_price=D("50050"),
            approved_quantity=D("0.08"),
            now_utc=T0,
        )
        assert ok
        stored = self.intents.get_entry(approval_id=approve.approval_id)
        assert stored is not None
        if status is not ExecutionIntentStatus.INTENDED:
            self.intents._rows[(approve.approval_id, OrderRole.ENTRY.value)] = IntentRecord(
                **{**stored.__dict__, "intent_status": status}
            )


def texts(bot: FakeBot) -> list[str]:
    return [m.text for m in bot.sent]


# --------------------------------------------------------------------------- #
# Task 1 (tracer): issue, send as one message, SKIP through on_callback.
# --------------------------------------------------------------------------- #


def test_issue_writes_parents_first_two_pending_rows_and_the_issue_journal() -> None:
    rig = Rig()
    money = make_desk_money()

    issued = rig.issue(money=money)

    assert rig.stores.trace == [
        "insert_signal",
        "insert_trade_plan",
        "insert_pending",
        "insert_pending",
        "record_short_id_mapping",
        "journal:DEMO_APPROVAL_REQUEST_ISSUED",
    ]
    assert issued.approve.action is ApprovalAction.APPROVE
    assert issued.skip.action is ApprovalAction.SKIP_USER
    for row in (issued.approve, issued.skip):
        assert row.status is ApprovalResult.PENDING
        assert row.approved_quantity == D("0.08")
        assert row.money_json == money_canonical_json(money)
    assert issued.text == format_approval_request(
        mode_label="DEMO",
        symbol="BTCUSDT",
        direction="LONG",
        setup="TREND_PULLBACK_LONG",
        entry_min=D("50000"),
        entry_max=D("50100"),
        stop_loss=D("49500"),
        take_profits=[(D("51000"), TP1_QUANTITY_FRACTION), (D("52000"), D("0.5"))],
        rr=D("2"),
        risk_pct=D("0.005"),
        expiry_utc=rig.plan.expiry_utc,
        invalidation="CANDLE_CLOSE at 49500",
        exposure_quote=D("0"),
        reason_codes=["TREND_OK"],
        signal_id=rig.signal.signal_id,
        detected_at_utc=rig.signal.detected_at_utc,
        approved_quantity=D("0.08"),
        money=money,
    )
    (journal,) = rig.stores.journal_of_type("DEMO_APPROVAL_REQUEST_ISSUED")
    assert journal.correlation_id == f"demo-request:{rig.signal.signal_id}"
    payload = json.loads(journal.payload_json)
    assert payload["short_id"] == issued.mapping.short_id
    assert payload["approved_quantity"] == "0.08"
    # No raw token anywhere: the payload holds ids and the plan hash only.
    assert "token" not in journal.payload_json


async def test_send_is_one_message_with_approve_and_skip_and_journals_the_message_id() -> None:
    rig = Rig()
    issued = rig.issue()

    outcome = await rig.desk.send(rig.bot, chat_id=CHAT_ID, issued=issued, sleep=rig.sleep)

    assert outcome.sent and outcome.message_id == 1 and outcome.attempts == 1
    (message,) = rig.bot.sent
    assert message.text == issued.text
    short = issued.mapping.short_id
    assert keyboard_buttons(message.reply_markup) == [("APPROVE", f"APR:{short}"), ("SKIP", f"SKP:{short}")]
    assert message.reply_markup == build_decision_keyboard(rig.signal.signal_id)
    (sent,) = rig.stores.journal_of_type("DEMO_APPROVAL_REQUEST_SENT")
    assert json.loads(sent.payload_json)["message_id"] == 1
    assert rig.stores.trace[-1] == "journal:DEMO_APPROVAL_REQUEST_SENT"
    assert rig.desk.message_id(short) == 1 and rig.desk.request_text(short) == issued.text


async def test_a_skip_tap_records_skipped_with_the_actor_and_makes_the_message_final() -> None:
    rig = Rig()
    issued = await rig.issue_and_send()
    short = issued.mapping.short_id

    result = await rig.tap("SKP", short, query_id="q-skip")

    assert result.ok
    skip = rig.row(ApprovalAction.SKIP_USER)
    assert skip.status is ApprovalResult.SKIPPED
    assert skip.action is ApprovalAction.SKIP_USER, "never SIMULATE_RECORDED"
    assert skip.actor_id == str(USER_ID) == "777001"
    assert rig.row(ApprovalAction.APPROVE).status is ApprovalResult.PENDING
    (edit,) = rig.bot.edited
    assert edit.message_id == 1
    assert edit.text == f"{issued.text}\nDecision: SKIPPED by user 777001 at {ACTED}"
    assert edit.reply_markup.inline_keyboard == ()
    assert len(rig.bot.sent) == 1, "a fresh SKIP sends no extra message"
