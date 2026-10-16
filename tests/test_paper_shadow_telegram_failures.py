"""Telegram failures in the APPROVE then CONFIRM chain (Phase 16, plan 16-11, Task 4, T-16-112).

A failure after APPROVE must never leave an approved plan with no confirm card AND no journaled
outcome: a failed edit into the card is followed by exactly one fallback send of the same card;
if that fails too the confirm is journaled EXPIRED with reason CARD_DELIVERY_FAILED and no
CONFIRM can follow; "message is not modified" on a replayed callback is success; a 429 is
honoured inside the remaining confirm TTL; every callback is answered once without text and a
failed `answerCallbackQuery` never aborts the processing. A decided approval is never reverted.

The fake bot raises real `telegram.error` classes and asserts label, mode and both time zones on
every text it is asked to send. No network, no real Telegram.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any, cast

import pytest
from src.adapters.telegram_callbacks import on_callback, parse_callback_data
from src.domain.enums import ApprovalResult
from src.domain.journal import JournalEvent
from src.paper.shadow import Mode
from src.paper.shadow_confirm import (
    EVENT_SHADOW_CONFIRM_EXPIRED,
    EVENT_SHADOW_CONFIRM_ISSUED,
    EVENT_SHADOW_CONFIRM_NOTICE_FAILED,
    EVENT_SHADOW_CONFIRM_REJECTED,
    EVENT_SHADOW_CONFIRMED,
    ConfirmState,
    StrandedApprovals,
    assert_no_stranded_approvals,
    make_confirm_callbacks,
)
from telegram import error as tg_error

from tests.shadow_fakes import (
    CHAT_ID,
    OTHER_CHAT_ID,
    USER_ID,
    keyboard_buttons,
    make_callback_update,
)
from tests.test_paper_shadow_confirm import T_PRESS, Harness, payload

LATE = T_PRESS + timedelta(hours=1)


class ClockSleep:
    """An injectable sleep that records the wait and moves the harness clock by it."""

    def __init__(self, harness: Harness) -> None:
        self.harness = harness
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        self.harness.now += timedelta(seconds=seconds)


def harness(*, ttl: int | None = None) -> tuple[Harness, ClockSleep]:
    h = Harness(ttl=ttl)
    sleep = ClockSleep(h)
    h.sleep = sleep  # type: ignore[assignment]
    h.callbacks = make_confirm_callbacks(
        approvals=h.book, confirm=h.confirm, bot=h.bot, mode=Mode.SHADOW, sleep=sleep
    )
    return h, sleep


async def approve_with(h: Harness, *errors: BaseException, message_id: int | None = 1) -> str:
    """Send the alert, queue the Telegram errors the next calls raise, then press APPROVE."""
    await h.alert()
    for error in errors:
        h.bot.queue_error(error)
    apr, _ = h.alert_buttons()
    await h.tap(apr, "q-apr", message_id=message_id)
    return apr.removeprefix("APR:")


def approved_ids(h: Harness) -> list[str]:
    return [
        a.approval_id for a in h.stores.approvals.values() if a.status == ApprovalResult.APPROVED
    ]


def assert_nothing_stranded(h: Harness) -> None:
    assert len(approved_ids(h)) == 1
    assert_no_stranded_approvals(h.stores, LATE)


def only(h: Harness, event_type: str) -> dict[str, Any]:
    events = h.events(event_type)
    assert len(events) == 1, [e.event_type for e in h.stores.journal]
    return payload(events[0])


# --------------------------------------------------------------------------- #
# Test 1: the edit fails after APPROVE, one fallback send of the same card.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "error",
    [tg_error.BadRequest("Message to edit not found"), tg_error.NetworkError("connection reset")],
    ids=["bad_request", "network_error"],
)
async def test_a_failed_edit_is_followed_by_exactly_one_fallback_send_of_the_same_card(
    error: BaseException,
) -> None:
    h, _ = harness()

    short_id = await approve_with(h, error)

    assert h.trace.count("edit") == 1
    assert h.trace.count("send") == 2  # the alert and the one fallback send
    assert h.bot.edited == []
    fallback = h.bot.sent[1]
    entry = h.confirm.get(short_id)
    assert entry is not None and entry.state is ConfirmState.PENDING and entry.delivered
    assert fallback.text == entry.card_text  # same card, same issue time
    assert [d for _, d in keyboard_buttons(fallback.reply_markup)] == [
        f"CNF:{short_id}",
        f"CXL:{short_id}",
    ]
    issued = only(h, EVENT_SHADOW_CONFIRM_ISSUED)
    assert issued["delivery"] == "fallback_send"
    assert issued["message_id"] == str(fallback.message_id)
    assert issued["edit_failure_kind"] in ("REJECTED", "TRANSIENT")
    assert h.events(EVENT_SHADOW_CONFIRM_EXPIRED) == []
    # A CONFIRM on the NEW message within the TTL is confirmed normally.
    h.now = T_PRESS + timedelta(seconds=20)
    result = await h.tap(f"CNF:{short_id}", "q-cnf", message_id=fallback.message_id)
    assert result.ok is True
    assert len(h.confirmed) == 1
    assert_nothing_stranded(h)


async def test_without_a_message_id_the_card_goes_out_as_the_one_fallback_send() -> None:
    h, _ = harness()

    short_id = await approve_with(h, message_id=None)

    assert h.trace.count("edit") == 0
    assert h.bot.sent[1].text == h.confirm.get(short_id).card_text  # type: ignore[union-attr]
    assert only(h, EVENT_SHADOW_CONFIRM_ISSUED)["delivery"] == "fallback_send"
    # Nobody pressed: the periodic sweep expires the token at its TTL, then nothing is stranded.
    assert h.confirm.expire_due(LATE) == approved_ids(h)
    assert_nothing_stranded(h)


# --------------------------------------------------------------------------- #
# Test 2: both fail - fail closed, nothing stranded.
# --------------------------------------------------------------------------- #


async def test_when_the_fallback_fails_too_the_confirm_expires_with_card_delivery_failed() -> None:
    h, _ = harness()

    short_id = await approve_with(
        h, tg_error.BadRequest("Message to edit not found"), tg_error.NetworkError("down")
    )

    expired = only(h, EVENT_SHADOW_CONFIRM_EXPIRED)
    assert expired["reason"] == "CARD_DELIVERY_FAILED"
    assert expired["failure_kind"] == "TRANSIENT"  # the kind of the LAST failure
    assert expired["failure_notice"] == "sent"
    assert h.events(EVENT_SHADOW_CONFIRM_ISSUED) == []
    entry = h.confirm.get(short_id)
    assert entry is not None and entry.state is ConfirmState.EXPIRED
    # The approval stays APPROVED: a decided approval is never reverted.
    assert len(approved_ids(h)) == 1
    # One best-effort notice, built by the composer.
    notice = h.bot.sent[-1].text
    assert "Confirmation card not delivered: TRANSIENT" in notice
    assert h.trace.count("send") == 3  # alert, fallback, notice
    # The token is dead: a later CONFIRM is rejected, journaled, and simulates nothing.
    h.now = T_PRESS + timedelta(seconds=5)
    late = await h.tap(f"CNF:{short_id}", "q-late")
    assert late.ok is False
    assert h.confirmed == []
    assert h.events(EVENT_SHADOW_CONFIRMED) == []
    rejected = h.events(EVENT_SHADOW_CONFIRM_REJECTED)
    assert len(rejected) == 1
    assert payload(rejected[0])["reason"] == "CONFIRM_ALREADY_EXPIRED"
    assert_nothing_stranded(h)


async def test_a_failing_notice_is_journaled_and_changes_nothing() -> None:
    h, _ = harness()

    short_id = await approve_with(
        h,
        tg_error.BadRequest("Message to edit not found"),
        tg_error.NetworkError("down"),
        tg_error.NetworkError("still down"),
    )

    assert only(h, EVENT_SHADOW_CONFIRM_EXPIRED)["reason"] == "CARD_DELIVERY_FAILED"
    failed = only(h, EVENT_SHADOW_CONFIRM_NOTICE_FAILED)
    assert failed["failure_kind"] == "TRANSIENT"
    assert failed["error_class"] == "NetworkError"
    entry = h.confirm.get(short_id)
    assert entry is not None and entry.state is ConfirmState.EXPIRED
    assert len(approved_ids(h)) == 1
    assert h.trace.count("send") == 3  # exactly one notice attempt
    assert_nothing_stranded(h)


# --------------------------------------------------------------------------- #
# Test 3: the repair sweep and the no-stranded-approval invariant.
# --------------------------------------------------------------------------- #


def approve_then_crash(h: Harness, apr: str) -> str:
    """APPROVED is written, then the process dies before any card is delivered."""
    parsed = parse_callback_data(apr)
    result = h.book.dispatch(
        parsed,
        callback_chat_id=CHAT_ID,
        authorized_chat_id=CHAT_ID,
        callback_at_utc=h.now,
        raw_token="",
        correlation_id="cbq:crash",
        binding_context=h.book.resolve(parsed.short_id),
    )
    assert result.ok is True
    return parsed.short_id


async def test_a_crash_between_approved_and_the_card_is_repaired_by_the_sweep() -> None:
    h, _ = harness()
    await h.alert()
    apr, _skp = h.alert_buttons()
    approve_then_crash(h, apr)
    assert not [e for e in h.stores.journal if e.event_type.startswith("SHADOW_CONFIRM")]
    # Inside the TTL there is still time to deliver, so the invariant holds.
    assert_no_stranded_approvals(h.stores, T_PRESS + timedelta(seconds=30))
    assert h.confirm.expire_due(T_PRESS + timedelta(seconds=30)) == []

    with pytest.raises(StrandedApprovals):
        assert_no_stranded_approvals(h.stores, T_PRESS + timedelta(seconds=61))

    swept = h.confirm.expire_due(T_PRESS + timedelta(seconds=61))
    assert swept == approved_ids(h)
    assert only(h, EVENT_SHADOW_CONFIRM_EXPIRED)["reason"] == "CARD_DELIVERY_FAILED"
    assert_no_stranded_approvals(h.stores, T_PRESS + timedelta(seconds=61))
    journal_size = len(h.stores.journal)
    assert h.confirm.expire_due(T_PRESS + timedelta(seconds=120)) == []
    assert len(h.stores.journal) == journal_size  # a second sweep writes nothing


async def test_the_invariant_also_flags_a_plan_with_two_terminal_events() -> None:
    """Negative control: exactly ONE terminal event is required, not at least one."""
    h, _ = harness()
    short_id = await approve_with(h)
    await h.tap(f"CNF:{short_id}", "q-cnf")
    assert_no_stranded_approvals(h.stores, LATE)
    approval = h.stores.list_approved_approvals()[0]
    extra = JournalEvent(
        journal_event_id="shadow-cnf_extra-terminal",
        occurred_at_utc=LATE,
        event_type=EVENT_SHADOW_CONFIRM_EXPIRED,
        entity_type="ShadowConfirm",
        entity_id=approval.approval_id,
        correlation_id=f"shadow-confirm:{approval.approval_id}",
        approval_id=approval.approval_id,
        payload_json="{}",
    )
    h.stores.record_journal(extra)

    with pytest.raises(StrandedApprovals):
        assert_no_stranded_approvals(h.stores, LATE)


# --------------------------------------------------------------------------- #
# Test 4: "message is not modified" on a replayed APPROVE is success.
# --------------------------------------------------------------------------- #


async def test_not_modified_on_a_replayed_approve_is_success_and_issues_nothing_new() -> None:
    h, _ = harness()
    short_id = await approve_with(h)
    entry = h.confirm.get(short_id)
    assert entry is not None
    token_hash = entry.token_hash
    journal_before = len(h.stores.journal)
    h.bot.queue_error(tg_error.BadRequest("Message is not modified"))
    apr = f"APR:{short_id}"

    await h.tap(apr, "q-apr-2")  # the replayed press edits the message again

    assert h.trace.count("edit") == 2
    assert h.confirm.get(short_id) is entry and entry.token_hash == token_hash
    assert len(h.events(EVENT_SHADOW_CONFIRM_ISSUED)) == 1
    assert h.events(EVENT_SHADOW_CONFIRM_EXPIRED) == []
    assert len(h.bot.sent) == 1, "no fallback send and no extra reply"
    new_rows = h.stores.journal[journal_before:]
    assert {e.event_type for e in new_rows} <= {"CALLBACK_RECEIVED", "CALLBACK_RESOLVED"}
    # The existing confirm still works.
    h.now = T_PRESS + timedelta(seconds=9)
    assert (await h.tap(f"CNF:{short_id}", "q-cnf")).ok is True
    assert len(h.confirmed) == 1
    assert_nothing_stranded(h)


async def test_a_replayed_approve_whose_edit_fails_otherwise_changes_nothing() -> None:
    h, _ = harness()
    short_id = await approve_with(h)
    h.bot.queue_error(tg_error.NetworkError("down"))

    await h.tap(f"APR:{short_id}", "q-apr-2")

    assert h.trace.count("send") == 1, "a replay never sends a second card"
    entry = h.confirm.get(short_id)
    assert entry is not None and entry.state is ConfirmState.PENDING
    assert len(h.events(EVENT_SHADOW_CONFIRM_ISSUED)) == 1
    assert h.events(EVENT_SHADOW_CONFIRM_EXPIRED) == []


async def test_a_replayed_approve_after_the_outcome_replays_the_decision_only() -> None:
    h, _ = harness()
    short_id = await approve_with(h)
    await h.tap(f"CNF:{short_id}", "q-cnf")
    edits = h.trace.count("edit")

    await h.tap(f"APR:{short_id}", "q-apr-2")

    assert h.trace.count("edit") == edits, "no card is put back after the outcome"
    assert "Decision: REPLAYED" in h.bot.sent[-1].text
    assert len(h.confirmed) == 1


# --------------------------------------------------------------------------- #
# Test 5: a 429 on the card edit is honoured inside the remaining TTL.
# --------------------------------------------------------------------------- #


async def test_a_rate_limited_edit_waits_retry_after_inside_the_window_and_succeeds() -> None:
    h, sleep = harness()

    short_id = await approve_with(h, tg_error.RetryAfter(5))

    assert sleep.calls == [5.0]
    entry = h.confirm.get(short_id)
    assert entry is not None and entry.state is ConfirmState.PENDING
    issued = only(h, EVENT_SHADOW_CONFIRM_ISSUED)
    assert issued["delivery"] == "edit"
    assert issued["attempts"] == 2
    assert issued["issued_at_utc"] == T_PRESS.isoformat()  # the TTL anchor is the issue time
    assert h.bot.edited[0].text == entry.card_text
    # 5 s of the 60 s window are gone: 54 s later the confirm still works, 56 s later it is late.
    h.now = T_PRESS + timedelta(seconds=59)
    assert (await h.tap(f"CNF:{short_id}", "q-cnf")).ok is True
    assert_nothing_stranded(h)


async def test_retry_after_beyond_the_remaining_window_does_not_sleep_and_fails_closed() -> None:
    h, sleep = harness()

    short_id = await approve_with(h, tg_error.RetryAfter(120))

    assert sleep.calls == []
    assert h.bot.send_attempts == 1, "no fallback send while Telegram says to wait"
    expired = only(h, EVENT_SHADOW_CONFIRM_EXPIRED)
    assert expired["reason"] == "CARD_DELIVERY_FAILED"
    assert expired["failure_kind"] == "RATE_LIMITED"
    assert expired["retry_after_seconds"] == 120
    assert expired["failure_notice"] == "skipped_rate_limited"
    entry = h.confirm.get(short_id)
    assert entry is not None and entry.state is ConfirmState.EXPIRED
    assert len(approved_ids(h)) == 1
    assert_nothing_stranded(h)


async def test_a_card_delivered_after_the_ttl_ran_out_is_expired_at_once() -> None:
    h, sleep = harness()

    short_id = await approve_with(h, tg_error.RetryAfter(60))  # exactly the whole window

    assert sleep.calls == [60.0]
    expired = only(h, EVENT_SHADOW_CONFIRM_EXPIRED)
    assert expired["reason"] == "CONFIRM_TTL_ELAPSED"
    assert expired["delivered_late"] is True
    assert h.events(EVENT_SHADOW_CONFIRM_ISSUED) == []
    result = await h.tap(f"CNF:{short_id}", "q-late")
    assert result.ok is False
    assert h.confirmed == []
    assert_nothing_stranded(h)


# --------------------------------------------------------------------------- #
# Test 6: answerCallbackQuery.
# --------------------------------------------------------------------------- #


class AnswerRecorder:
    """A `query.answer` that records its arguments and the journal size when it was called."""

    def __init__(self, h: Harness, error: BaseException | None = None) -> None:
        self.h = h
        self.error = error
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.journal_sizes: list[int] = []

    async def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))
        self.journal_sizes.append(len(self.h.stores.journal))
        if self.error is not None:
            raise self.error


async def press(h: Harness, data: str, query: str, answer: Any, *, chat_id: int = CHAT_ID) -> Any:
    update = make_callback_update(
        data=data, chat_id=chat_id, query_id=query, from_user_id=USER_ID, answer=answer
    )
    return await on_callback(
        update,
        cast(Any, None),
        authorized_chat_id=CHAT_ID,
        binding_context_resolver=h.book.resolve,
        dispatch=h.book.dispatch,
        reply_text_fn=h.reply,
        confirm_handler=h.callbacks.confirm_handler,
        approved_handler=h.callbacks.approved_handler,
        clock=lambda: h.now,
    )


async def test_every_callback_is_answered_once_without_text_before_any_state_change() -> None:
    h, _ = harness()
    await h.alert()
    apr, _skp = h.alert_buttons()
    answer = AnswerRecorder(h)
    size_before = len(h.stores.journal)

    result = await press(h, apr, "q1", answer)

    assert result.ok is True
    assert answer.calls == [((), {})], "answered exactly once, without text"
    assert answer.journal_sizes == [size_before], "before any journal write or state change"
    assert len(approved_ids(h)) == 1


@pytest.mark.parametrize(
    "error",
    [
        tg_error.BadRequest("Query is too old and response timeout expired or query id is invalid"),
        tg_error.NetworkError("connection reset"),
        tg_error.RetryAfter(3),
    ],
    ids=["too_old", "network", "rate_limited"],
)
async def test_a_failed_answer_never_stops_the_press_from_going_through_the_gates(
    error: BaseException, caplog: pytest.LogCaptureFixture
) -> None:
    h, _ = harness()
    await h.alert()
    apr, _skp = h.alert_buttons()
    short_id = apr.removeprefix("APR:")
    answer = AnswerRecorder(h, error)

    with caplog.at_level(logging.WARNING):
        valid = await press(h, apr, "q1", answer)
        rejected = await press(h, apr, "q2", answer, chat_id=OTHER_CHAT_ID)
        confirm = await press(h, f"CNF:{short_id}", "q3", answer)

    assert valid.ok is True, "a valid APR: still reaches APPROVED"
    assert len(approved_ids(h)) == 1
    assert rejected.ok is False, "an invalid press is still rejected by the gates"
    assert confirm.ok is True, "a CNF: still reaches the confirm layer"
    assert len(answer.calls) == 3, "answered once per press and never retried"
    logged = caplog.text
    assert type(error).__name__ in logged
    assert str(error) not in logged, "only the exception class is logged"


# --------------------------------------------------------------------------- #
# The invariant after every failure sequence above is checked inline; one more mix.
# --------------------------------------------------------------------------- #


async def test_after_a_mixed_failure_sequence_no_approval_is_stranded() -> None:
    h, _ = harness()
    await approve_with(
        h,
        tg_error.RetryAfter(2),
        tg_error.BadRequest("Message to edit not found"),
        tg_error.NetworkError("down"),
    )
    assert_nothing_stranded(h)
    assert only(h, EVENT_SHADOW_CONFIRM_EXPIRED)["reason"] == "CARD_DELIVERY_FAILED"
    body = json.loads(h.events(EVENT_SHADOW_CONFIRM_EXPIRED)[0].payload_json)
    assert body["mode"] == "SHADOW"


# --------------------------------------------------------------------------- #
# Plan 16-58, B2-WR-08: an infrastructure error in dispatch is diagnosable and still fails closed.
# --------------------------------------------------------------------------- #

from src.domain.enums import RejectionReason  # noqa: E402

from tests.shadow_fakes import InMemoryShadowStores  # noqa: E402


class DatabaseDown(Exception):
    """Stands for an OperationalError of the real store."""


class FailingSaveStores(InMemoryShadowStores):
    def save_atomic(self, approval: Any, mapping: Any) -> None:
        raise DatabaseDown("connection to host=db password=hunter2 refused")


async def test_an_infrastructure_error_in_dispatch_is_logged_by_class_and_fails_closed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    h = Harness(stores=FailingSaveStores())
    await h.alert()
    apr, _skp = h.alert_buttons()

    with caplog.at_level(logging.ERROR):
        result = await h.tap(apr, "q-db")

    assert result.ok is False and result.reason_code is RejectionReason.INVALIDATED
    assert all(a.status is not ApprovalResult.APPROVED for a in h.stores.approvals.values())
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    logged = errors[0].getMessage()
    assert "DatabaseDown" in logged and "cbq:q-db" in logged
    assert "hunter2" not in caplog.text and "password" not in caplog.text, "no message text"
    assert apr not in caplog.text, "no callback data or token"

    # A domain rejection (another chat) is unchanged: refused without an error line.
    before = len(caplog.records)
    with caplog.at_level(logging.ERROR):
        refused = await h.tap(apr, "q-other", chat_id=OTHER_CHAT_ID)
    assert refused.ok is False
    assert [r for r in caplog.records[before:] if r.levelno >= logging.ERROR] == []
