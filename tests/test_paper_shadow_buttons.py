"""SHADOW decision paths: SKIP, expiry, replay, send failure, restart, 429 (plan 16-04, Task 2).

Every non-happy path of the SHADOW approval front half is journaled and fails closed: a send
failure never approves, an APPROVE after the TradePlan expiry is APPROVAL_EXPIRED and never
revives the signal (REV-12), a restart expires pending approvals because the raw tokens do not
survive it (Pitfall P13), a Telegram 429 is honoured inside the existing retry budget, and every
reply text carries the SHADOW label, the mode and both time zones (D-12, D-35). Telegram errors
are classified once, in the adapter, so no python-telegram-bot class reaches `src/paper`.
No network, no real Telegram.
"""

from __future__ import annotations

import ast
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from src.adapters.telegram_callbacks import (
    CallbackKind,
    DispatchResult,
    on_callback,
    parse_callback_data,
)
from src.adapters.telegram_notify import (
    TelegramFailureKind,
    TelegramSendError,
    classify_telegram_error,
    edit_text,
    send_text,
)
from src.domain.enums import ApprovalAction, ApprovalResult, RejectionReason
from src.paper.notify import NOTIFY_MAX_ATTEMPTS, NOTIFY_MAX_DELAY_SECONDS
from src.paper.shadow import (
    Mode,
    ModeNotConstructible,
    ShadowApprovalBook,
    ShadowDecisionOutcome,
    ShadowSendOutcome,
    invalidate_pending_on_restart,
    make_shadow_reply_fn,
    send_shadow_alert,
)
from telegram import error as tg_error

from tests.shadow_fakes import (
    CHAT_ID,
    OTHER_CHAT_ID,
    T0,
    FakeBot,
    InMemoryShadowStores,
    RecordingSleep,
    assert_shadow_text,
    keyboard_buttons,
    make_callback_update,
    make_shadow_plan,
    make_shadow_signal,
)

T_PRESS = T0 + timedelta(minutes=7)


class Harness:
    """Stores, bot, a movable clock and a book, plus helpers to send alerts and press buttons."""

    def __init__(self) -> None:
        self.trace: list[str] = []
        self.stores = InMemoryShadowStores(self.trace)
        self.bot = FakeBot(self.trace)
        self.now = T_PRESS
        self.book = ShadowApprovalBook(self.stores, clock=lambda: self.now)
        self.sleep = RecordingSleep()

    async def alert(self, n: int = 1) -> tuple[ShadowSendOutcome, str, Any]:
        signal = make_shadow_signal(n)
        plan = make_shadow_plan(signal)
        outcome = await send_shadow_alert(
            stores=self.stores,
            book=self.book,
            bot=self.bot,
            chat_id=CHAT_ID,
            mode=Mode.SHADOW,
            signal=signal,
            plan=plan,
            exposure_quote=Decimal("0"),
            reason_codes=["SETUP_DETECTED"],
            now_utc=T0,
            sleep=self.sleep,
        )
        return outcome, signal.signal_id, plan

    def press(self, data: str, *, query: str, chat_id: int = CHAT_ID) -> DispatchResult:
        parsed = parse_callback_data(data)
        return self.book.dispatch(
            parsed,
            callback_chat_id=chat_id,
            authorized_chat_id=CHAT_ID,
            callback_at_utc=self.now,
            raw_token="",
            correlation_id=f"cbq:{query}",
            binding_context=self.book.resolve(parsed.short_id),
        )

    def buttons(self, index: int = -1) -> tuple[str, str]:
        (_, apr), (_, skp) = keyboard_buttons(self.bot.sent[index].reply_markup)
        return apr, skp


# --------------------------------------------------------------------------- #
# Test 1: SKIP.
# --------------------------------------------------------------------------- #


async def test_skp_callback_skips_with_action_and_timestamp() -> None:
    h = Harness()
    await h.alert()
    _, skp = h.buttons()

    result = h.press(skp, query="skip-1")

    assert result.ok is True
    assert result.kind is CallbackKind.SKIP
    assert result.approval is not None
    assert result.approval.status == ApprovalResult.SKIPPED
    assert result.approval.action == ApprovalAction.SKIP_USER
    assert result.approval.acted_at_utc == T_PRESS
    assert result.approval.actor_id == str(CHAT_ID)
    decision = h.book.take_last_decision()
    assert decision is not None and decision.outcome is ShadowDecisionOutcome.SKIPPED


async def test_skip_after_approve_cannot_flip_the_decision() -> None:
    h = Harness()
    await h.alert()
    apr, skp = h.buttons()
    assert h.press(apr, query="a").ok is True

    result = h.press(skp, query="b")

    assert result.ok is False
    assert result.reason_code is RejectionReason.INVALIDATED
    decided = [a for a in h.stores.approvals.values() if a.status != ApprovalResult.PENDING]
    assert [a.status for a in decided] == [ApprovalResult.APPROVED]


# --------------------------------------------------------------------------- #
# Test 2: expiry (REV-12).
# --------------------------------------------------------------------------- #


async def test_approve_at_or_after_the_plan_expiry_is_journaled_and_never_revives() -> None:
    h = Harness()
    _, _, plan = await h.alert()
    apr, _ = h.buttons()
    h.now = plan.expiry_utc  # boundary inclusive: now >= expiry is expired

    result = h.press(apr, query="late-1")

    assert result.ok is False
    assert result.reason_code is RejectionReason.APPROVAL_EXPIRED
    assert h.stores.journal_of_type("APPROVAL_EXPIRED")
    payloads = [json.loads(e.payload_json) for e in h.stores.journal_of_type("CALLBACK_REJECTED")]
    assert any(p["reason_code"] == "APPROVAL_EXPIRED" for p in payloads)
    expired_event = h.stores.journal_of_type("APPROVAL_EXPIRED")[0]
    assert json.loads(expired_event.payload_json)["reason_code"] == "APPROVAL_EXPIRED"

    # Never revives: a later press, even a new one, is still rejected and nothing is approved.
    h.now = plan.expiry_utc + timedelta(hours=1)
    again = h.press(apr, query="late-2")
    assert again.ok is False
    assert again.reason_code is RejectionReason.APPROVAL_EXPIRED
    assert all(a.status == ApprovalResult.PENDING for a in h.stores.approvals.values())
    assert not any(a.status == ApprovalResult.APPROVED for a in h.stores.approvals.values())


async def test_one_second_before_expiry_is_still_approvable() -> None:
    h = Harness()
    _, _, plan = await h.alert()
    apr, _ = h.buttons()
    h.now = plan.expiry_utc - timedelta(seconds=1)

    assert h.press(apr, query="edge").ok is True


# --------------------------------------------------------------------------- #
# Test 3: replay.
# --------------------------------------------------------------------------- #


async def test_replayed_approve_returns_the_existing_decision_without_a_second_write() -> None:
    h = Harness()
    await h.alert()
    apr, _ = h.buttons()
    first = h.press(apr, query="r-1")
    assert h.book.take_last_decision() is not None

    second = h.press(apr, query="r-2")

    assert second.ok is True
    assert second.approval == first.approval
    assert h.trace.count("save_atomic") == 1
    decision = h.book.take_last_decision()
    assert decision is not None and decision.outcome is ShadowDecisionOutcome.REPLAYED


# --------------------------------------------------------------------------- #
# Test 4: a send failure approves nothing.
# --------------------------------------------------------------------------- #


async def test_send_failure_after_bounded_retries_leaves_pending_and_is_journaled() -> None:
    h = Harness()
    for _ in range(NOTIFY_MAX_ATTEMPTS):
        h.bot.queue_error(tg_error.NetworkError("boom"))

    outcome, _, _ = await h.alert()

    assert outcome.sent is False
    assert outcome.attempts == NOTIFY_MAX_ATTEMPTS
    assert h.bot.send_attempts == NOTIFY_MAX_ATTEMPTS
    assert outcome.failure is not None
    assert outcome.failure.kind is TelegramFailureKind.TRANSIENT
    assert all(a.status == ApprovalResult.PENDING for a in h.stores.approvals.values())
    assert h.trace[-1] == "journal:SHADOW_ALERT_FAILED"
    assert h.stores.journal_of_type("SHADOW_ALERT_SENT") == []
    # Backoff sleeps happen between attempts only.
    assert len(h.sleep.calls) == NOTIFY_MAX_ATTEMPTS - 1


async def test_a_non_telegram_send_exception_is_retried_then_journaled_as_unknown() -> None:
    h = Harness()
    for _ in range(NOTIFY_MAX_ATTEMPTS):
        h.bot.queue_error(RuntimeError("secret detail"))

    outcome, _, _ = await h.alert()

    assert outcome.sent is False
    assert outcome.failure is not None
    assert outcome.failure.kind is TelegramFailureKind.UNKNOWN
    assert outcome.failure.detail == "RuntimeError"
    payload = h.stores.journal_of_type("SHADOW_ALERT_FAILED")[0].payload_json
    assert "secret detail" not in payload


async def test_a_rejected_send_is_not_retried() -> None:
    h = Harness()
    h.bot.queue_error(tg_error.Forbidden("bot was blocked"))

    outcome, _, _ = await h.alert()

    assert outcome.sent is False
    assert outcome.attempts == 1
    assert h.bot.send_attempts == 1
    assert outcome.failure is not None
    assert outcome.failure.kind is TelegramFailureKind.REJECTED


# --------------------------------------------------------------------------- #
# Test 5: restart (Pitfall P13).
# --------------------------------------------------------------------------- #


async def test_restart_expires_pending_approvals_and_later_callbacks_are_rejected() -> None:
    h = Harness()
    await h.alert(1)
    await h.alert(2)
    apr1, _ = h.buttons(0)
    apr2, _ = h.buttons(1)
    plan_ids = {a.trade_plan_id for a in h.stores.approvals.values()}
    assert len(plan_ids) == 2
    restart_at = T0 + timedelta(minutes=30)

    report = invalidate_pending_on_restart(h.stores, restart_at)

    # One decision per plan is all PostgreSQL allows; the rest of the pair can no longer be
    # decided by anyone (its raw token died with the process).
    assert len(report.expired) == 2
    for approval in report.expired:
        stored = h.stores.approvals[approval.approval_id]
        assert stored.status == ApprovalResult.EXPIRED
        assert stored.acted_at_utc == restart_at
    events = h.stores.journal_of_type("SHADOW_PENDING_INVALIDATED")
    assert {json.loads(e.payload_json)["reason_code"] for e in events} == {"RUNTIME_RESTART"}
    assert {e.approval_id for e in events} >= {a.approval_id for a in report.expired}
    for plan_id in plan_ids:
        assert [
            a.status
            for a in h.stores.approvals.values()
            if a.trade_plan_id == plan_id and a.status != ApprovalResult.PENDING
        ] == [ApprovalResult.EXPIRED]

    # A new process has an empty book: the callback finds no binding context and is rejected.
    h.book = ShadowApprovalBook(h.stores, clock=lambda: restart_at)
    h.now = restart_at
    for data in (apr1, apr2):
        result = h.press(data, query=f"after-restart-{data[-4:]}")
        assert result.ok is False
        assert result.reason_code is RejectionReason.INVALIDATED
    assert not any(a.status == ApprovalResult.APPROVED for a in h.stores.approvals.values())

    # Idempotent: a second sweep decides nothing more.
    again = invalidate_pending_on_restart(h.stores, restart_at)
    assert again.expired == []


# --------------------------------------------------------------------------- #
# Test 6: only SHADOW.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("mode", [Mode.DEMO, Mode.LIVE])
async def test_demo_and_live_cannot_reach_the_alert_path(mode: Mode) -> None:
    h = Harness()
    signal = make_shadow_signal()

    with pytest.raises(ModeNotConstructible):
        await send_shadow_alert(
            stores=h.stores,
            book=h.book,
            bot=h.bot,
            chat_id=CHAT_ID,
            mode=mode,
            signal=signal,
            plan=make_shadow_plan(signal),
            exposure_quote=Decimal("0"),
            reason_codes=["SETUP_DETECTED"],
            now_utc=T0,
            sleep=h.sleep,
        )

    assert h.trace == []
    assert h.bot.send_attempts == 0
    with pytest.raises(ModeNotConstructible):
        make_shadow_reply_fn(h.bot, mode=mode, clock=lambda: T0)


# --------------------------------------------------------------------------- #
# Test 7: outcome replies through the real on_callback entry.
# --------------------------------------------------------------------------- #


async def test_every_outcome_reply_is_one_labelled_shadow_message() -> None:
    h = Harness()
    await h.alert(1)
    await h.alert(2)
    _, _, plan3 = await h.alert(3)
    apr1, skp1 = h.buttons(0)
    _, skp2 = h.buttons(1)
    apr3, _ = h.buttons(2)
    reply = make_shadow_reply_fn(h.bot, mode=Mode.SHADOW, clock=lambda: h.now, book=h.book)

    async def tap(data: str, query: str, chat_id: int = CHAT_ID) -> str:
        before = len(h.bot.sent)
        update = make_callback_update(data=data, chat_id=chat_id, query_id=query)
        await on_callback(
            update,
            cast(Any, None),
            authorized_chat_id=CHAT_ID,
            binding_context_resolver=h.book.resolve,
            dispatch=h.book.dispatch,
            reply_text_fn=reply,
        )
        assert len(h.bot.sent) == before + 1, "exactly one reply per press"
        text = h.bot.sent[-1].text
        assert_shadow_text(text)
        return text

    approved = await tap(apr1, "q1")
    skipped = await tap(skp2, "q2")
    replayed = await tap(apr1, "q3")
    unauthorized = await tap(apr1, "q4", chat_id=OTHER_CHAT_ID)
    h.now = plan3.expiry_utc + timedelta(minutes=1)
    expired = await tap(apr3, "q5")

    assert "Decision: APPROVED" in approved
    assert "Decision: SKIPPED" in skipped
    assert "Decision: REPLAYED" in replayed
    assert "Decision: REJECTED_OTHER" in unauthorized
    assert "Decision: REJECTED_APPROVAL_EXPIRED" in expired
    assert "Plan expiry: 2026-10-09 07:00:00 UTC" in expired
    # The adapter's own text is only the detail; it never goes out on its own.
    assert "Detail: OK: APPROVED" in approved
    assert "Detail: Rejected" in unauthorized
    assert skp1 != apr1
    assert not [m for m in h.bot.sent if m.text in ("Rejected", "OK: APPROVED")]


async def test_a_failed_reply_never_raises_into_the_handler() -> None:
    h = Harness()
    await h.alert()
    apr, _ = h.buttons()
    h.bot.queue_error(tg_error.NetworkError("down"))
    reply = make_shadow_reply_fn(h.bot, mode=Mode.SHADOW, clock=lambda: h.now, book=h.book)
    update = make_callback_update(data=apr, chat_id=CHAT_ID, query_id="q-fail")

    result = await on_callback(
        update,
        cast(Any, None),
        authorized_chat_id=CHAT_ID,
        binding_context_resolver=h.book.resolve,
        dispatch=h.book.dispatch,
        reply_text_fn=reply,
    )

    assert result.ok is True
    assert result.approval is not None and result.approval.status == ApprovalResult.APPROVED


# --------------------------------------------------------------------------- #
# Tests 8 and 9: 429 is honoured inside the existing budget.
# --------------------------------------------------------------------------- #


async def test_retry_after_is_honoured_with_exactly_one_retry() -> None:
    h = Harness()
    h.bot.queue_error(tg_error.RetryAfter(5))

    outcome, _, _ = await h.alert()

    assert outcome.sent is True
    assert outcome.attempts == 2
    assert h.bot.send_attempts == 2
    assert len(h.sleep.calls) == 1
    assert 5 <= h.sleep.calls[0] <= NOTIFY_MAX_DELAY_SECONDS
    assert len(h.stores.approvals) == 2  # the rows were written once, not per attempt
    assert h.trace.count("insert_signal") == 1
    assert h.stores.journal_of_type("SHADOW_ALERT_SENT")


async def test_retry_after_is_honoured_when_it_fits_the_budget() -> None:
    h = Harness()
    h.bot.queue_error(tg_error.RetryAfter(NOTIFY_MAX_DELAY_SECONDS - 5))

    outcome, _, _ = await h.alert()

    assert outcome.sent is True
    assert NOTIFY_MAX_DELAY_SECONDS - 5 <= h.sleep.calls[0] <= NOTIFY_MAX_DELAY_SECONDS


async def test_retry_after_beyond_the_budget_stops_at_once_and_approves_nothing() -> None:
    h = Harness()
    h.bot.queue_error(tg_error.RetryAfter(NOTIFY_MAX_DELAY_SECONDS + 30))

    outcome, signal_id, _ = await h.alert()

    assert outcome.sent is False
    assert outcome.attempts == 1
    assert h.bot.send_attempts == 1  # no other text is sent
    assert h.sleep.calls == []  # no sleep past the budget
    assert outcome.failure is not None
    assert outcome.failure.kind is TelegramFailureKind.RATE_LIMITED
    assert outcome.failure.retry_after_seconds == NOTIFY_MAX_DELAY_SECONDS + 30
    assert all(a.status == ApprovalResult.PENDING for a in h.stores.approvals.values())
    failed = h.stores.journal_of_type("SHADOW_ALERT_FAILED")[0]
    payload = json.loads(failed.payload_json)
    assert payload["kind"] == "RATE_LIMITED"
    assert payload["retry_after_seconds"] == NOTIFY_MAX_DELAY_SECONDS + 30
    assert_shadow_text(payload["notice_text"])
    assert signal_id in payload["notice_text"]
    assert outcome.notice_text == payload["notice_text"]


# --------------------------------------------------------------------------- #
# Test 10: classification lives in the adapter only.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("exc", "kind", "retry_after"),
    [
        (tg_error.RetryAfter(5), TelegramFailureKind.RATE_LIMITED, 5),
        (tg_error.RetryAfter(timedelta(seconds=4.2)), TelegramFailureKind.RATE_LIMITED, 5),
        (tg_error.RetryAfter(timedelta(seconds=7)), TelegramFailureKind.RATE_LIMITED, 7),
        (
            tg_error.BadRequest("Bad Request: Message is Not Modified: same text"),
            TelegramFailureKind.MESSAGE_NOT_MODIFIED,
            None,
        ),
        (tg_error.BadRequest("Chat not found"), TelegramFailureKind.REJECTED, None),
        (tg_error.Forbidden("bot was blocked"), TelegramFailureKind.REJECTED, None),
        (tg_error.InvalidToken("secret-token-123"), TelegramFailureKind.REJECTED, None),
        (tg_error.ChatMigrated(77), TelegramFailureKind.REJECTED, None),
        (tg_error.NetworkError("down"), TelegramFailureKind.TRANSIENT, None),
        (tg_error.TimedOut(), TelegramFailureKind.TRANSIENT, None),
        (tg_error.TelegramError("other"), TelegramFailureKind.UNKNOWN, None),
        (RuntimeError("nope"), TelegramFailureKind.UNKNOWN, None),
    ],
)
def test_classification_table(
    exc: BaseException, kind: TelegramFailureKind, retry_after: int | None
) -> None:
    failure = classify_telegram_error(exc)

    assert failure.kind is kind
    assert failure.retry_after_seconds == retry_after
    assert failure.detail == type(exc).__name__  # the class name only
    assert "secret-token-123" not in failure.detail


async def test_send_and_edit_wrappers_convert_telegram_errors() -> None:
    bot = FakeBot()
    bot.queue_error(tg_error.RetryAfter(3))
    with pytest.raises(TelegramSendError) as sent:
        await send_text(bot, CHAT_ID, _label("x"))
    assert sent.value.failure.kind is TelegramFailureKind.RATE_LIMITED
    assert sent.value.failure.retry_after_seconds == 3
    assert "secret" not in str(sent.value)

    bot.queue_error(tg_error.BadRequest("message is not modified"))
    with pytest.raises(TelegramSendError) as edited:
        await edit_text(bot, CHAT_ID, 5, _label("y"))
    assert edited.value.failure.kind is TelegramFailureKind.MESSAGE_NOT_MODIFIED

    # Programming errors are not Telegram failures and pass through unconverted.
    bot.queue_error(ValueError("bug"))
    with pytest.raises(ValueError, match="bug"):
        await send_text(bot, CHAT_ID, _label("z"))

    await send_text(bot, CHAT_ID, _label("ok"))
    await edit_text(bot, CHAT_ID, 5, _label("ok2"))
    assert len(bot.sent) == 1 and len(bot.edited) == 1


def _label(word: str) -> str:
    from src.paper.shadow import ShadowMessageKind, render_shadow_message

    return render_shadow_message(
        ShadowMessageKind.SEND_FAILURE_NOTICE, mode=Mode.SHADOW, now_utc=T0, failure_kind=word
    )


# --------------------------------------------------------------------------- #
# Boundaries: no PTB class and no order path in src/paper/shadow.py.
# --------------------------------------------------------------------------- #


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.add(node.module)
    return found


def test_shadow_module_imports_no_telegram_and_no_execution() -> None:
    path = Path(__file__).resolve().parent.parent / "src" / "paper" / "shadow.py"
    modules = _imported_modules(path)

    assert not [m for m in modules if m == "telegram" or m.startswith("telegram.")]
    assert not [m for m in modules if m == "src.execution" or m.startswith("src.execution.")]
    # The checker is not vacuous: it does see the imports that are there.
    assert "src.adapters.telegram_notify" in modules
