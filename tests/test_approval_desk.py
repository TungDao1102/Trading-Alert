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
    format_presentation_time,
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
ACTED = "2026-10-09 10:05:00 +07 (2026-10-09 03:05:00 UTC)"


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
    assert keyboard_buttons(message.reply_markup) == [
        ("APPROVE", f"APR:{short}"),
        ("SKIP", f"SKP:{short}"),
    ]
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


# --------------------------------------------------------------------------- #
# Task 2: send failures, stale taps, G4-032, fail-closed APPROVE, expiry, strangers.
# --------------------------------------------------------------------------- #


async def test_retry_after_is_honoured_then_the_request_goes_out() -> None:
    rig = Rig()
    issued = rig.issue()
    rig.bot.queue_error(RetryAfter(2))

    outcome = await rig.desk.send(rig.bot, chat_id=CHAT_ID, issued=issued, sleep=rig.sleep)

    assert outcome.sent and outcome.attempts == 2
    assert rig.sleep.calls == [2]


async def test_a_forbidden_send_is_journaled_and_leaves_both_approvals_pending() -> None:
    rig = Rig()
    issued = rig.issue()
    rig.bot.queue_error(Forbidden("blocked by the user"))

    outcome = await rig.desk.send(rig.bot, chat_id=CHAT_ID, issued=issued, sleep=rig.sleep)

    assert not outcome.sent and outcome.message_id is None
    assert outcome.failure is not None and outcome.failure.kind.value == "REJECTED"
    (failed,) = rig.stores.journal_of_type("DEMO_APPROVAL_REQUEST_SEND_FAILED")
    payload = json.loads(failed.payload_json)
    assert payload["kind"] == "REJECTED" and payload["error_class"] == "Forbidden"
    assert "blocked" not in failed.payload_json
    assert all(a.status is ApprovalResult.PENDING for a in rig.stores.approvals.values())
    assert not rig.stores.journal_of_type("DEMO_APPROVAL_REQUEST_SENT")


def test_issue_refuses_missing_or_mismatching_money_before_any_write() -> None:
    rig = Rig()
    with pytest.raises(MoneyAtStakeUnavailable) as missing:
        rig.issue(money=None)
    assert missing.value.reason_code == MONEY_AT_STAKE_MISSING
    different = make_desk_money(
        sized=SizedResult(
            is_no_trade=False,
            quantity=D("0.09"),
            quantity_before_rounding=D("0.09"),
            quantity_after_rounding=D("0.09"),
            quantization_decision="ACCEPTED",
            realized_risk=D("60"),
            modeled_costs_per_unit=D("20"),
            sizing_entry_price=D("50100"),
        )
    )
    with pytest.raises(ValueError, match="quantity"):
        rig.issue(money=different)
    one_leg = make_desk_money(take_profits=[(D("51000"), D("1"))])
    with pytest.raises(MoneyAtStakeUnavailable, match="take_profits"):
        rig.issue(money=one_leg)
    assert rig.stores.trace == []
    assert rig.stores.approvals == {} and rig.stores.journal == []


@pytest.mark.parametrize(
    "rule",
    [
        '{"basis":"CANDLE_CLOSE"}',
        '{"level":"49500"}',
        '{"basis":"CANDLE_CLOSE","level":null}',
        '{"basis":"","level":"49500"}',
        '{"basis":"CANDLE_CLOSE","level":49500}',
    ],
)
def test_issue_refuses_an_invalidation_rule_without_a_text_basis_and_level(rule: str) -> None:
    """WR-10: never send an APPROVE request that says 'Invalidation: None at None'."""
    rig = Rig()
    rig.plan = make_shadow_plan(rig.signal, invalidation_rule_json=rule)
    with pytest.raises(ValueError, match="invalidation_rule_json"):
        rig.issue()
    assert rig.stores.approvals == {} and rig.stores.journal == []


def test_the_second_issue_for_one_signal_is_refused_before_any_write() -> None:
    rig = Rig()
    rig.issue()
    trace = list(rig.stores.trace)
    with pytest.raises(ValueError, match="already issued"):
        rig.issue()
    assert rig.stores.trace == trace


def test_only_demo_and_live_profiles_are_accepted() -> None:
    stores = InMemoryShadowStores()
    for profile in (DEMO_CONFIRM_PROFILE, LIVE_CONFIRM_PROFILE):
        ApprovalDesk(stores, profile=profile, clock=lambda: T0, intent_reader=lambda _id: None)
    with pytest.raises(ValueError):
        ApprovalDesk(
            stores, profile=SHADOW_CONFIRM_PROFILE, clock=lambda: T0, intent_reader=lambda _id: None
        )


def test_the_desk_is_proven_against_the_narrow_stores_port() -> None:
    stores: DeskStores = InMemoryShadowStores()
    assert stores is not None


async def test_three_skip_taps_give_one_transition_and_one_final_edit() -> None:
    rig = Rig()
    issued = await rig.issue_and_send()
    short = issued.mapping.short_id

    await rig.tap("SKP", short, query_id="q1")
    await rig.tap("SKP", short, query_id="q2")
    await rig.tap("SKP", short, query_id="q3")

    saves = [t for t in rig.stores.trace if t == "save_atomic"]
    assert len(saves) == 1
    assert rig.row(ApprovalAction.SKIP_USER).status is ApprovalResult.SKIPPED
    expected = "Mode: DEMO\nAlready decided: SKIPPED. Nothing changed. [ALREADY_DECIDED]"
    assert texts(rig.bot)[1:] == [expected, expected]
    assert len(rig.bot.edited) == 1, "the final text is edited once"


async def test_approve_after_skip_changes_nothing_and_says_already_decided() -> None:
    rig = Rig()
    issued = await rig.issue_and_send()
    short = issued.mapping.short_id
    await rig.tap("SKP", short, query_id="q1")

    result = await rig.tap("APR", short, query_id="q2")

    assert not result.ok
    assert rig.row(ApprovalAction.APPROVE).status is ApprovalResult.PENDING
    assert rig.row(ApprovalAction.SKIP_USER).status is ApprovalResult.SKIPPED
    assert texts(rig.bot)[-1] == (
        "Mode: DEMO\nAlready decided: SKIPPED. Nothing changed. [ALREADY_DECIDED]"
    )
    assert "Decision: SKIPPED" in rig.bot.edited[-1].text


async def test_a_fresh_approve_without_a_card_handler_is_recorded_and_places_nothing() -> None:
    rig = Rig()
    issued = await rig.issue_and_send()

    result = await rig.tap("APR", issued.mapping.short_id, query_id="q-apr")

    assert result.ok
    approve = rig.row(ApprovalAction.APPROVE)
    assert approve.status is ApprovalResult.APPROVED and approve.actor_id == "777001"
    assert texts(rig.bot)[-1] == f"Mode: DEMO\n{NO_HANDLER_REPLY}"
    (edit,) = rig.bot.edited
    assert "No confirmation card handler is attached, so nothing can be confirmed" in edit.text
    assert f"Decision: APPROVED by user 777001 at {ACTED}" in edit.text
    assert edit.reply_markup.inline_keyboard == ()
    assert rig.intents.get_entry(approval_id=approve.approval_id) is None, "nothing was placed"


async def test_a_confirmation_attached_desk_does_not_claim_a_missing_handler() -> None:
    rig = Rig()
    rig.desk.confirmation_attached = True
    issued = await rig.issue_and_send()

    await rig.tap("APR", issued.mapping.short_id, query_id="q-apr")

    assert "no confirmation card handler" not in texts(rig.bot)[-1]
    assert "no confirmation card handler" not in rig.bot.edited[-1].text
    assert "Nothing was placed." in rig.bot.edited[-1].text


@pytest.mark.parametrize(
    ("status", "needle"),
    [
        (ExecutionIntentStatus.ACKED, "already placed (acknowledged by the exchange"),
        (ExecutionIntentStatus.UNKNOWN, "needs reconciliation"),
        (ExecutionIntentStatus.SENT, "needs reconciliation"),
        (ExecutionIntentStatus.INTENDED, "needs reconciliation"),
        (ExecutionIntentStatus.REJECTED, "rejected"),
    ],
)
async def test_a_redelivered_approve_after_expiry_is_answered_from_the_stored_intent(
    status: ExecutionIntentStatus, needle: str
) -> None:
    rig = Rig()
    issued = await rig.issue_and_send()
    short = issued.mapping.short_id
    await rig.tap("APR", short, query_id="q-apr")
    rig.record_entry_intent(status)
    approved = rig.row(ApprovalAction.APPROVE)
    rig.now = rig.plan.expiry_utc + timedelta(seconds=1)

    result = await rig.tap("APR", short, query_id="q-redelivered")

    assert not result.ok
    reply = texts(rig.bot)[-1]
    assert needle in reply and "APPROVAL_EXPIRED" not in reply.split("\n", 1)[1][:0]
    assert reply.startswith("Mode: DEMO\n")
    if needle == "needs reconciliation":
        assert reconciliation_required_text() in reply
    else:
        assert reconciliation_required_text() not in reply
    assert rig.row(ApprovalAction.APPROVE) == approved, "no state change"


async def test_a_redelivered_approve_after_expiry_without_an_intent_is_plainly_refused() -> None:
    rig = Rig()
    issued = await rig.issue_and_send()
    short = issued.mapping.short_id
    await rig.tap("APR", short, query_id="q-apr")
    rig.now = rig.plan.expiry_utc + timedelta(seconds=1)

    await rig.tap("APR", short, query_id="q-redelivered")

    assert texts(rig.bot)[-1] == "Mode: DEMO\nRefused: APPROVAL_EXPIRED. Nothing changed."


async def test_the_intent_reader_is_not_called_for_a_pending_approval() -> None:
    rig = Rig()
    calls: list[str] = []
    rig.desk = ApprovalDesk(
        rig.stores,
        profile=DEMO_CONFIRM_PROFILE,
        clock=lambda: rig.now,
        intent_reader=lambda approval_id: calls.append(approval_id),  # type: ignore[func-returns-value]
    )
    issued = await rig.issue_and_send()
    rig.now = rig.plan.expiry_utc + timedelta(seconds=1)

    await rig.tap("APR", issued.mapping.short_id, query_id="q-late")

    assert calls == []
    assert rig.row(ApprovalAction.APPROVE).status is ApprovalResult.PENDING


async def test_an_unreadable_intent_is_never_described_as_expired_or_rejected() -> None:
    rig = Rig()

    def broken(approval_id: str) -> IntentRecord | None:
        raise RuntimeError("store down")

    rig.desk = ApprovalDesk(
        rig.stores, profile=DEMO_CONFIRM_PROFILE, clock=lambda: rig.now, intent_reader=broken
    )
    issued = await rig.issue_and_send()
    short = issued.mapping.short_id
    await rig.tap("APR", short, query_id="q-apr")
    rig.now = rig.plan.expiry_utc + timedelta(seconds=1)

    await rig.tap("APR", short, query_id="q-redelivered")

    assert "needs reconciliation" in texts(rig.bot)[-1]


async def test_a_tap_after_expiry_on_a_pending_request_finalizes_it_as_expired() -> None:
    rig = Rig()
    issued = await rig.issue_and_send()
    rig.now = rig.plan.expiry_utc + timedelta(seconds=1)

    await rig.tap("APR", issued.mapping.short_id, query_id="q-late")

    assert texts(rig.bot)[-1] == "Mode: DEMO\nRefused: APPROVAL_EXPIRED. Nothing changed."
    (edit,) = rig.bot.edited
    expiry = format_presentation_time(rig.plan.expiry_utc)
    assert edit.text == (
        f"{issued.text}\nEXPIRED: the plan expired at {expiry}; no decision was taken."
    )
    assert edit.reply_markup.inline_keyboard == ()
    assert all(a.status is ApprovalResult.PENDING for a in rig.stores.approvals.values())


async def test_a_store_failure_keeps_the_keyboard() -> None:
    rig = Rig()
    issued = await rig.issue_and_send()

    def boom(approval: Any, mapping: Any) -> None:
        raise ConnectionError("db down")

    rig.stores.save_atomic = boom  # type: ignore[method-assign]
    result = await rig.tap("SKP", issued.mapping.short_id, query_id="q-fail")

    assert not result.ok and result.reason_code == "APPROVAL_STORE_FAILURE"
    assert texts(rig.bot)[-1] == "Mode: DEMO\nRefused: APPROVAL_STORE_FAILURE. Nothing changed."
    assert rig.bot.edited == [] and rig.bot.markup_edits == []


async def test_the_expiry_sweep_finalizes_untapped_requests_once_and_writes_no_row() -> None:
    rig = Rig()
    issued = await rig.issue_and_send()
    rows_before = dict(rig.stores.approvals)

    assert (
        await rig.desk.finalize_expired_requests(
            rig.bot, now_utc=rig.plan.expiry_utc - timedelta(seconds=1), sleep=rig.sleep
        )
        == []
    )
    done = await rig.desk.finalize_expired_requests(
        rig.bot, now_utc=rig.plan.expiry_utc, sleep=rig.sleep
    )
    again = await rig.desk.finalize_expired_requests(
        rig.bot, now_utc=rig.plan.expiry_utc + timedelta(minutes=1), sleep=rig.sleep
    )

    assert done == [issued.mapping.short_id] and again == []
    (edit,) = rig.bot.edited
    assert edit.text.endswith(
        "EXPIRED: the plan expired at "
        f"{format_presentation_time(rig.plan.expiry_utc)}; no decision was taken."
    )
    assert edit.reply_markup.inline_keyboard == ()
    assert rig.stores.approvals == rows_before


async def test_the_expiry_sweep_leaves_a_tapped_request_alone() -> None:
    rig = Rig()
    issued = await rig.issue_and_send()
    await rig.tap("SKP", issued.mapping.short_id, query_id="q1")
    edits = len(rig.bot.edited)

    done = await rig.desk.finalize_expired_requests(
        rig.bot, now_utc=rig.plan.expiry_utc + timedelta(hours=1), sleep=rig.sleep
    )

    assert done == [] and len(rig.bot.edited) == edits


async def test_a_failed_final_edit_is_journaled_and_changes_no_decision() -> None:
    rig = Rig()
    issued = await rig.issue_and_send()
    rig.bot.queue_error(Forbidden("cannot edit"))
    rig.bot.queue_markup_error(Forbidden("cannot edit"))

    result = await rig.tap("SKP", issued.mapping.short_id, query_id="q1")

    assert result.ok
    assert rig.row(ApprovalAction.SKIP_USER).status is ApprovalResult.SKIPPED
    (failed,) = rig.stores.journal_of_type("DEMO_DECIDED_MESSAGE_EDIT_FAILED")
    payload = json.loads(failed.payload_json)
    assert payload["trigger"] == "SKIP" and payload["error_class"] == "Forbidden"
    assert "cannot edit" not in failed.payload_json


async def test_a_stranger_or_a_wrong_chat_touches_nothing_and_gets_a_plain_refusal() -> None:
    rig = Rig()
    issued = await rig.issue_and_send()
    short = issued.mapping.short_id

    await rig.tap("SKP", short, query_id="q-stranger", user_id=STRANGER_USER_ID)
    await rig.tap("APR", short, query_id="q-group", chat_type="group")
    await rig.tap("APR", short, query_id="q-chat", chat_id=OTHER_CHAT_ID)

    assert rig.bot.edited == [] and rig.bot.markup_edits == []
    assert texts(rig.bot)[1:] == ["Mode: DEMO\nRefused. Nothing changed."] * 3
    assert all(a.status is ApprovalResult.PENDING for a in rig.stores.approvals.values())
    assert rig.desk._decisions == {}, "gate refusals leave no record behind"


async def test_a_short_id_lost_in_a_restart_loses_its_keyboard_only() -> None:
    first = Rig()
    issued = await first.issue_and_send()
    second = Rig(stores=first.stores)

    await second.tap("APR", issued.mapping.short_id, query_id="q-after-restart")

    assert texts(second.bot) == ["Mode: DEMO\nRefused: INVALIDATED. Nothing changed."]
    assert second.bot.edited == []
    (markup,) = second.bot.markup_edits
    assert markup.message_id == 1
    assert all(a.status is ApprovalResult.PENDING for a in second.stores.approvals.values())


async def test_the_live_desk_labels_every_text_live() -> None:
    rig = Rig(mode="LIVE")
    issued = await rig.issue_and_send()
    assert "Mode: LIVE" in issued.text

    await rig.tap("APR", issued.mapping.short_id, query_id="q-apr")
    await rig.tap("APR", issued.mapping.short_id, query_id="q-again")

    assert rig.stores.journal_of_type("LIVE_APPROVAL_REQUEST_ISSUED")
    assert rig.stores.journal_of_type("LIVE_APPROVAL_REQUEST_SENT")
    assert all("Mode: LIVE" in t for t in texts(rig.bot))


def test_money_for_reads_the_stored_money_by_short_id_or_plan_id() -> None:
    rig = Rig()
    money = make_desk_money()
    issued = rig.issue(money=money)

    assert rig.desk.money_for(issued.mapping.short_id) == money
    assert rig.desk.money_for(rig.plan.trade_plan_id) == money
    assert rig.desk.money_for("unknown") is None
    assert rig.desk.plan_context(issued.mapping.short_id) == (rig.signal, rig.plan)
    assert rig.desk.plan_context("unknown") is None
