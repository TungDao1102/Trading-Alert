"""Phase 23, plan 23-07: a decided Telegram message is made final (D-06, D-07; F-509, F-510).

The tracer slice: a SKP press through `on_callback` with a finalize hook built on
`finalize_decided_message` edits the message to its final text AND removes the keyboard in ONE
`editMessageText` call; RetryAfter is honoured inside a bound that restates the existing
`src.paper.notify` bound. Nothing touches the network: a `FakeBot` records the calls, and the
`telegram.error` classes are the real ones.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from src.adapters.telegram_callbacks import (
    CallbackKind,
    CallbackPress,
    DispatchResult,
    ParsedCallback,
    dispatch_callback,
    on_callback,
)
from src.adapters.telegram_notify import (
    EDIT_MAX_ATTEMPTS,
    RETRY_AFTER_CAP_SECONDS,
    BoundedOutcome,
    FinalizeOutcome,
    TelegramFailureKind,
    TelegramSendError,
    build_removed_keyboard,
    call_bounded,
    finalize_decided_message,
    send_text_bounded,
)
from src.approval.binding import ApprovalRejected
from src.approval.mapping import derive_short_id
from src.approval.replay import ApprovalAlreadyDecided, ApprovalDecidedDifferently
from src.approval.tokens import issue_one_time_token, token_hash_of
from src.domain.approval import Approval
from src.domain.enums import ApprovalAction, ApprovalResult, RejectionReason
from src.paper.notify import NOTIFY_MAX_ATTEMPTS, NOTIFY_MAX_DELAY_SECONDS
from telegram import error as tg_error

from tests.shadow_fakes import (
    CHAT_ID,
    OTHER_CHAT_ID,
    STRANGER_USER_ID,
    USER_ID,
    FakeBot,
    RecordingSleep,
    make_callback_update,
)

NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
EXPIRY = NOW + timedelta(hours=1)
PLAN_HASH = "0" * 64
PARAM_HASH = "1" * 64
SIGNAL_ID = "sig_dec_" + "0" * 56
SHORT_ID = derive_short_id(SIGNAL_ID)
ALLOW = frozenset({USER_ID})
FINAL_TEXT = "FINAL\nMode: DEMO\nDecided at 2026-10-25 09:00:00 UTC"
MESSAGE_ID = 7


# --------------------------------------------------------------------------- #
# The bound restates the existing message-retry bound (no new number).
# --------------------------------------------------------------------------- #


def test_the_bound_equals_the_paper_notify_bound() -> None:
    assert RETRY_AFTER_CAP_SECONDS == NOTIFY_MAX_DELAY_SECONDS
    assert EDIT_MAX_ATTEMPTS == NOTIFY_MAX_ATTEMPTS


def test_the_telegram_adapters_import_nothing_from_execution() -> None:
    import inspect

    import src.adapters.telegram_callbacks as callbacks
    import src.adapters.telegram_notify as notify

    for module in (callbacks, notify):
        source = inspect.getsource(module)
        assert "src.execution" not in source


def test_the_removed_keyboard_is_an_empty_inline_keyboard() -> None:
    from telegram import InlineKeyboardMarkup

    markup = build_removed_keyboard()
    assert isinstance(markup, InlineKeyboardMarkup)
    assert markup.inline_keyboard == ()


# --------------------------------------------------------------------------- #
# call_bounded.
# --------------------------------------------------------------------------- #


class Script:
    """An async op that raises the queued exceptions in order, then returns 'ok'."""

    def __init__(self, *errors: BaseException) -> None:
        self.errors = list(errors)
        self.calls = 0

    async def __call__(self) -> object:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


async def test_retry_after_is_slept_then_the_call_succeeds() -> None:
    sleep = RecordingSleep()
    script = Script(tg_error.RetryAfter(2))
    outcome = await call_bounded(script, sleep=sleep)
    assert isinstance(outcome, BoundedOutcome)
    assert sleep.calls == [2]
    assert outcome.attempts == 2
    assert outcome.failure is None
    assert outcome.result == "ok"


async def test_a_retry_after_over_the_cap_stops_without_sleeping() -> None:
    sleep = RecordingSleep()
    script = Script(tg_error.RetryAfter(RETRY_AFTER_CAP_SECONDS + 1))
    outcome = await call_bounded(script, sleep=sleep)
    assert sleep.calls == []
    assert outcome.attempts == 1
    assert outcome.failure is not None
    assert outcome.failure.kind is TelegramFailureKind.RATE_LIMITED
    assert script.calls == 1


async def test_a_retry_after_beyond_the_remaining_window_stops_without_sleeping() -> None:
    sleep = RecordingSleep()
    script = Script(tg_error.RetryAfter(5))
    outcome = await call_bounded(script, sleep=sleep, window_seconds=4)
    assert sleep.calls == []
    assert outcome.failure is not None
    assert outcome.failure.kind is TelegramFailureKind.RATE_LIMITED


async def test_the_window_is_consumed_by_the_sleeps() -> None:
    sleep = RecordingSleep()
    script = Script(tg_error.RetryAfter(3), tg_error.RetryAfter(3))
    outcome = await call_bounded(script, sleep=sleep, window_seconds=5)
    assert sleep.calls == [3]
    assert outcome.attempts == 2
    assert outcome.failure is not None


async def test_three_retry_afters_stop_at_the_attempt_bound() -> None:
    sleep = RecordingSleep()
    script = Script(tg_error.RetryAfter(1), tg_error.RetryAfter(1), tg_error.RetryAfter(1))
    outcome = await call_bounded(script, sleep=sleep)
    assert outcome.attempts == EDIT_MAX_ATTEMPTS == 3
    assert script.calls == 3
    # No sleep after the last attempt: it would only delay the report.
    assert sleep.calls == [1, 1]
    assert outcome.failure is not None
    assert outcome.failure.kind is TelegramFailureKind.RATE_LIMITED


async def test_a_network_error_is_retried_without_a_sleep() -> None:
    sleep = RecordingSleep()
    script = Script(tg_error.NetworkError("boom"))
    outcome = await call_bounded(script, sleep=sleep)
    assert outcome.attempts == 2
    assert sleep.calls == []
    assert outcome.failure is None


async def test_message_is_not_modified_counts_as_success() -> None:
    sleep = RecordingSleep()
    script = Script(tg_error.BadRequest("Bad Request: message is not modified"))
    outcome = await call_bounded(script, sleep=sleep)
    assert outcome.attempts == 1
    assert outcome.failure is None


async def test_a_refusal_is_never_retried() -> None:
    sleep = RecordingSleep()
    script = Script(tg_error.Forbidden("bot was blocked by the user"))
    outcome = await call_bounded(script, sleep=sleep)
    assert outcome.attempts == 1
    assert script.calls == 1
    assert outcome.failure is not None
    assert outcome.failure.kind is TelegramFailureKind.REJECTED


async def test_an_already_classified_send_error_is_read_not_reclassified() -> None:
    from src.adapters.telegram_notify import TelegramFailure

    failure = TelegramFailure(TelegramFailureKind.REJECTED, None, "BadRequest")
    outcome = await call_bounded(Script(TelegramSendError(failure)), sleep=RecordingSleep())
    assert outcome.failure == failure
    assert outcome.attempts == 1


async def test_a_programming_error_propagates() -> None:
    with pytest.raises(ValueError):
        await call_bounded(Script(ValueError("bug")), sleep=RecordingSleep())


async def test_an_unknown_exception_stops_and_is_reported_by_class() -> None:
    outcome = await call_bounded(Script(RuntimeError("secret-ish")), sleep=RecordingSleep())
    assert outcome.attempts == 1
    assert outcome.failure is not None
    assert outcome.failure.kind is TelegramFailureKind.UNKNOWN
    assert outcome.failure.detail == "RuntimeError"


async def test_send_text_bounded_honours_retry_after() -> None:
    bot = FakeBot.for_mode("DEMO")
    bot.queue_error(tg_error.RetryAfter(2))
    sleep = RecordingSleep()
    outcome = await send_text_bounded(bot, CHAT_ID, FINAL_TEXT, None, sleep=sleep)
    assert sleep.calls == [2]
    assert outcome.failure is None
    assert len(bot.sent) == 1


# --------------------------------------------------------------------------- #
# finalize_decided_message.
# --------------------------------------------------------------------------- #


async def test_finalize_edits_the_text_and_removes_the_keyboard_in_one_call() -> None:
    bot = FakeBot.for_mode("DEMO")
    outcome = await finalize_decided_message(
        bot, chat_id=CHAT_ID, message_id=MESSAGE_ID, text=FINAL_TEXT, sleep=RecordingSleep()
    )
    assert isinstance(outcome, FinalizeOutcome)
    assert outcome.done is True
    assert outcome.method == "edit_text"
    assert outcome.failure is None
    assert len(bot.edited) == 1
    assert bot.edited[0].text == FINAL_TEXT
    assert bot.edited[0].message_id == MESSAGE_ID
    assert bot.edited[0].reply_markup is not None
    assert bot.edited[0].reply_markup.inline_keyboard == ()
    assert bot.markup_edits == []


async def test_finalize_without_text_removes_the_keyboard_only() -> None:
    bot = FakeBot.for_mode("DEMO")
    outcome = await finalize_decided_message(
        bot, chat_id=CHAT_ID, message_id=MESSAGE_ID, text=None, sleep=RecordingSleep()
    )
    assert outcome.done is True
    assert outcome.method == "edit_reply_markup"
    assert bot.edited == []
    assert len(bot.markup_edits) == 1
    assert bot.markup_edits[0].reply_markup.inline_keyboard == ()


async def test_a_refused_text_edit_falls_back_once_to_a_keyboard_only_edit() -> None:
    bot = FakeBot.for_mode("DEMO")
    bot.queue_error(tg_error.BadRequest("Bad Request: some refusal"))
    outcome = await finalize_decided_message(
        bot, chat_id=CHAT_ID, message_id=MESSAGE_ID, text=FINAL_TEXT, sleep=RecordingSleep()
    )
    assert outcome.done is True
    assert outcome.method == "edit_reply_markup"
    assert bot.edited == []
    assert len(bot.markup_edits) == 1


async def test_two_refusals_report_done_false_and_never_raise() -> None:
    bot = FakeBot.for_mode("DEMO")
    bot.queue_error(tg_error.BadRequest("Bad Request: some refusal"))
    bot.queue_markup_error(tg_error.BadRequest("Bad Request: another refusal"))
    outcome = await finalize_decided_message(
        bot, chat_id=CHAT_ID, message_id=MESSAGE_ID, text=FINAL_TEXT, sleep=RecordingSleep()
    )
    assert outcome.done is False
    assert outcome.failure is not None
    assert outcome.failure.kind is TelegramFailureKind.REJECTED
    assert bot.edited == [] and bot.markup_edits == []


async def test_finalize_honours_retry_after_on_the_text_edit() -> None:
    bot = FakeBot.for_mode("DEMO")
    bot.queue_error(tg_error.RetryAfter(1))
    sleep = RecordingSleep()
    outcome = await finalize_decided_message(
        bot, chat_id=CHAT_ID, message_id=MESSAGE_ID, text=FINAL_TEXT, sleep=sleep
    )
    assert outcome.done is True
    assert outcome.attempts == 2
    assert sleep.calls == [1]
    assert len(bot.edited) == 1


async def test_finalize_message_is_not_modified_is_done() -> None:
    bot = FakeBot.for_mode("DEMO")
    bot.queue_error(tg_error.BadRequest("Bad Request: message is not modified"))
    outcome = await finalize_decided_message(
        bot, chat_id=CHAT_ID, message_id=MESSAGE_ID, text=FINAL_TEXT, sleep=RecordingSleep()
    )
    assert outcome.done is True
    assert outcome.failure is None


# --------------------------------------------------------------------------- #
# FakeBot extension keeps the SHADOW recording unchanged.
# --------------------------------------------------------------------------- #


async def test_the_default_fake_bot_still_enforces_the_shadow_text_rules() -> None:
    bot = FakeBot()
    with pytest.raises(AssertionError):
        await bot.send_message(chat_id=CHAT_ID, text="no label here")
    with pytest.raises(AssertionError):
        await bot.edit_message_text(chat_id=CHAT_ID, message_id=1, text="no label here")


async def test_the_live_fake_bot_refuses_a_shadow_pair_and_a_missing_mode() -> None:
    bot = FakeBot.for_mode("DEMO")
    with pytest.raises(AssertionError):
        await bot.send_message(chat_id=CHAT_ID, text="Mode: LIVE\n2026-10-25 09:00:00 UTC")
    with pytest.raises(AssertionError):
        await bot.send_message(
            chat_id=CHAT_ID,
            text="Mode: DEMO\n2026-10-25 09:00:00 UTC (2026-10-25 16:00:00 Asia/Ho_Chi_Minh)",
        )
    with pytest.raises(AssertionError):
        await bot.send_message(chat_id=CHAT_ID, text="Mode: DEMO\n2026-10-25 09:00:00")


async def test_a_markup_edit_is_not_a_text_edit_and_not_traced() -> None:
    bot = FakeBot()
    await bot.edit_message_reply_markup(chat_id=CHAT_ID, message_id=3, reply_markup=None)
    assert len(bot.markup_edits) == 1
    assert bot.edited == [] and bot.sent == [] and bot.trace == []


# --------------------------------------------------------------------------- #
# on_callback: the finalize hook (tracer path).
# --------------------------------------------------------------------------- #


class Harness:
    """Recording lookups and journal around the real `dispatch_callback`."""

    def __init__(self, approval: Approval, raw: str) -> None:
        self.raw = raw
        self.approvals: dict[str, Approval] = {approval.approval_token_hash: approval}
        self.saved: list[Approval] = []
        self.journal: list[Any] = []
        self.replies: list[tuple[int, str]] = []
        self.order: list[str] = []
        self.save_error: BaseException | None = None

    def lookup_by_short_id(self, short_id: str) -> tuple[str, str] | None:
        return (SIGNAL_ID, "tp_dec")

    def lookup_by_token_hash(self, token_hash: str) -> Approval | None:
        return self.approvals.get(token_hash)

    def save_atomic(self, approval: Approval, mapping: Any) -> None:
        if self.save_error is not None:
            raise self.save_error
        self.saved.append(approval)
        self.approvals[approval.approval_token_hash] = approval

    def dispatch(self, parsed: ParsedCallback, **kwargs: Any) -> DispatchResult:
        return dispatch_callback(
            parsed,
            journal_receipt=self.journal.append,
            lookup_by_short_id=self.lookup_by_short_id,
            lookup_by_token_hash=self.lookup_by_token_hash,
            save_atomic=self.save_atomic,
            now_utc=NOW,
            **kwargs,
        )

    async def reply(self, chat_id: int, text: str) -> None:
        self.order.append("reply")
        self.replies.append((chat_id, text))

    def binding(self, short_id: str) -> dict[str, Any]:
        return {
            "raw_token": self.raw,
            "plan_hash": PLAN_HASH,
            "strategy_version": "v1.0.0",
            "parameter_set_id": "ps-1",
            "parameter_set_hash": PARAM_HASH,
            "expiry_utc": EXPIRY,
        }


def _pending(raw: str, action: ApprovalAction = ApprovalAction.SKIP_USER) -> Approval:
    return Approval(
        approval_id="appr_dec_00000000000000000000000000000000000000000",
        trade_plan_id="tp_dec",
        signal_id=SIGNAL_ID,
        action=action,
        result=ApprovalResult.PENDING,
        status=ApprovalResult.PENDING,
        approval_token_hash=token_hash_of(raw),
        requested_at_utc=NOW - timedelta(minutes=5),
        acted_at_utc=None,
        actor_id="",
        telegram_message_id=None,
        request_hash=PLAN_HASH,
    )


class HookRecorder:
    def __init__(self, harness: Harness, *, error: BaseException | None = None) -> None:
        self.harness = harness
        self.error = error
        self.calls: list[tuple[CallbackPress, DispatchResult]] = []

    async def __call__(self, press: CallbackPress, result: DispatchResult) -> None:
        self.harness.order.append("hook")
        self.calls.append((press, result))
        if self.error is not None:
            raise self.error


async def _press(
    harness: Harness,
    *,
    prefix: str = "SKP:",
    finalize: Any = None,
    from_user_id: int | None = USER_ID,
    chat_id: int = CHAT_ID,
    query_id: str = "q-dec-1",
    confirm_handler: Any = None,
) -> DispatchResult:
    update = make_callback_update(
        data=prefix + SHORT_ID,
        chat_id=chat_id,
        query_id=query_id,
        message_chat_id=chat_id,
        from_user_id=from_user_id,
        message_id=MESSAGE_ID,
    )
    return await on_callback(
        update,
        None,  # type: ignore[arg-type]
        authorized_chat_id=CHAT_ID,
        authorized_user_ids=ALLOW,
        binding_context_resolver=harness.binding,
        dispatch=harness.dispatch,
        reply_text_fn=harness.reply,
        confirm_handler=confirm_handler,
        finalize_message=finalize,
        clock=lambda: NOW,
    )


async def test_tracer_a_skip_press_finalizes_the_message_with_an_empty_keyboard() -> None:
    raw = issue_one_time_token()
    harness = Harness(_pending(raw), raw)
    bot = FakeBot.for_mode("DEMO")
    sleep = RecordingSleep()
    bot.queue_error(tg_error.RetryAfter(2))

    async def hook(press: CallbackPress, result: DispatchResult) -> None:
        assert press.message_id is not None
        await finalize_decided_message(
            bot,
            chat_id=press.chat_id,
            message_id=press.message_id,
            text=FINAL_TEXT,
            sleep=sleep,
        )

    result = await _press(harness, finalize=hook)

    assert result.ok is True
    assert result.approval is not None
    assert result.approval.status == ApprovalResult.SKIPPED
    assert len(harness.saved) == 1
    assert len(bot.edited) == 1
    assert bot.edited[0].text == FINAL_TEXT
    assert bot.edited[0].message_id == MESSAGE_ID
    assert bot.edited[0].reply_markup.inline_keyboard == ()
    assert sleep.calls == [2]


async def test_the_hook_runs_once_after_the_reply_with_the_press_and_the_result() -> None:
    raw = issue_one_time_token()
    harness = Harness(_pending(raw), raw)
    hook = HookRecorder(harness)

    result = await _press(harness, finalize=hook)

    assert harness.order == ["reply", "hook"]
    assert len(hook.calls) == 1
    press, hooked = hook.calls[0]
    assert hooked is result
    assert press.parsed.kind is CallbackKind.SKIP
    assert press.message_id == MESSAGE_ID
    assert press.chat_id == CHAT_ID
    assert press.correlation_id == "cbq:q-dec-1"


async def test_the_hook_runs_for_an_approve_press_too() -> None:
    raw = issue_one_time_token()
    harness = Harness(_pending(raw, ApprovalAction.APPROVE), raw)
    hook = HookRecorder(harness)
    result = await _press(harness, prefix="APR:", finalize=hook)
    assert result.ok is True
    assert len(hook.calls) == 1


async def test_the_hook_runs_for_a_confirm_press() -> None:
    raw = issue_one_time_token()
    harness = Harness(_pending(raw), raw)
    hook = HookRecorder(harness)

    async def confirm(press: CallbackPress) -> Any:
        from src.adapters.telegram_callbacks import ConfirmReply

        return ConfirmReply(ok=True, text="confirmed")

    result = await _press(harness, prefix="CNF:", finalize=hook, confirm_handler=confirm)
    assert result.ok is True
    assert harness.order == ["reply", "hook"]
    assert hook.calls[0][0].parsed.kind is CallbackKind.CONFIRM


async def test_the_hook_does_not_run_for_a_chat_gate_refusal() -> None:
    raw = issue_one_time_token()
    harness = Harness(_pending(raw), raw)
    hook = HookRecorder(harness)
    result = await _press(harness, finalize=hook, chat_id=OTHER_CHAT_ID)
    assert result.ok is False
    assert hook.calls == []


async def test_the_hook_does_not_run_for_a_user_gate_refusal() -> None:
    raw = issue_one_time_token()
    harness = Harness(_pending(raw), raw)
    hook = HookRecorder(harness)
    result = await _press(harness, finalize=hook, from_user_id=STRANGER_USER_ID)
    assert result.ok is False
    assert hook.calls == []
    assert harness.saved == []


async def test_a_hook_error_is_logged_by_class_and_changes_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw = issue_one_time_token()
    harness = Harness(_pending(raw), raw)
    hook = HookRecorder(harness, error=RuntimeError("secret-ish text"))

    with caplog.at_level(logging.ERROR, logger="src.adapters.telegram_callbacks"):
        result = await _press(harness, finalize=hook)

    assert result.ok is True
    assert result.approval is not None
    assert result.approval.status == ApprovalResult.SKIPPED
    assert len(harness.saved) == 1
    text = caplog.text
    assert "telegram.callback.finalize_failed" in text
    assert "RuntimeError" in text
    assert "cbq:q-dec-1" in text
    assert "secret-ish" not in text


async def test_without_a_hook_nothing_changes() -> None:
    raw = issue_one_time_token()
    harness = Harness(_pending(raw), raw)
    result = await _press(harness)
    assert result.ok is True
    assert harness.order == ["reply"]


# --------------------------------------------------------------------------- #
# Task 2: the state-based "already decided" flag (D-06, D-09; research Pitfall 7).
# --------------------------------------------------------------------------- #


def _decided(approval: Approval, result: ApprovalResult) -> Approval:
    return replace(approval, result=result, status=result, acted_at_utc=NOW, actor_id="777001")


def test_decided_differently_is_an_approval_rejected_that_carries_the_stored_row() -> None:
    stored = _decided(_pending("x", ApprovalAction.APPROVE), ApprovalResult.APPROVED)
    exc = ApprovalDecidedDifferently(
        reason_code=RejectionReason.INVALIDATED,
        message="approval already decided with a different outcome",
        existing=stored,
    )
    assert isinstance(exc, ApprovalRejected)
    assert exc.existing is stored
    assert exc.reason_code is RejectionReason.INVALIDATED
    assert "different outcome" in str(exc)


async def test_a_fresh_approve_is_not_already_decided_and_a_replay_is() -> None:
    raw = issue_one_time_token()
    harness = Harness(_pending(raw, ApprovalAction.APPROVE), raw)

    first = await _press(harness, prefix="APR:")
    assert first.ok is True
    assert first.already_decided is False
    assert len(harness.saved) == 1

    second = await _press(harness, prefix="APR:", query_id="q-dec-2")
    third = await _press(harness, prefix="APR:", query_id="q-dec-3")
    for replay in (second, third):
        assert replay.ok is True
        assert replay.already_decided is True
        assert replay.approval is not None
        assert replay.approval.status == ApprovalResult.APPROVED
    # Three presses, one transition: state is unchanged by the replays.
    assert len(harness.saved) == 1


async def test_a_tap_on_the_sibling_button_of_a_decided_plan_is_flagged() -> None:
    raw = issue_one_time_token()
    harness = Harness(_pending(raw, ApprovalAction.SKIP_USER), raw)
    approved = _decided(_pending("sibling", ApprovalAction.APPROVE), ApprovalResult.APPROVED)
    harness.save_error = ApprovalAlreadyDecided(approved)

    result = await _press(harness, prefix="SKP:")

    assert result.ok is False
    assert result.reason_code is RejectionReason.INVALIDATED
    assert result.approval is approved
    assert result.already_decided is True
    assert harness.saved == []
    # The journal is exactly what it was before this flag: one rejected outcome, INVALIDATED.
    rejected = [e for e in harness.journal if e.event_type == "CALLBACK_REJECTED"]
    assert len(rejected) == 1
    assert '"reason_code":"INVALIDATED"' in rejected[0].payload_json


async def test_a_lost_cross_process_race_to_the_same_decision_is_flagged() -> None:
    raw = issue_one_time_token()
    harness = Harness(_pending(raw, ApprovalAction.APPROVE), raw)
    stored = _decided(_pending(raw, ApprovalAction.APPROVE), ApprovalResult.APPROVED)
    harness.save_error = ApprovalAlreadyDecided(stored)

    result = await _press(harness, prefix="APR:")

    assert result.ok is True
    assert result.already_decided is True
    assert result.approval is stored


async def test_a_rejection_that_is_not_a_decision_is_not_flagged() -> None:
    raw = issue_one_time_token()
    harness = Harness(_pending(raw, ApprovalAction.APPROVE), raw)
    result = await _press(harness, prefix="APR:", chat_id=OTHER_CHAT_ID)
    assert result.ok is False
    assert result.already_decided is False
