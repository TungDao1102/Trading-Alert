"""A decided SHADOW message loses its keyboard (Phase 23, plan 23-10, D-06, D-08).

SHADOW texts are pinned by many tests and by the Phase 16 soak evidence, so SHADOW removes the
keyboard with a KEYBOARD-ONLY edit (`finalize_decided_message(..., text=None)`) and keeps sending
its decision replies as separate messages. The tests drive the real coordinator through
`on_callback(**coordinator.callback_kwargs())`, so the wiring (finalize hook and error journal) is
under test, not only the hook. `FakeBot` records keyboard-only edits in `markup_edits`, outside
`sent`, `edited` and `trace`. No network, no real Telegram.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, cast

import pytest
from src.adapters.telegram_callbacks import DispatchResult, on_callback
from src.approval.confirm_core import ConfirmState
from src.domain.enums import ApprovalResult, RejectionReason
from src.paper.shadow_runtime import ShadowCoordinator
from telegram import error as tg_error

from tests.shadow_fakes import (
    CHAT_ID,
    OTHER_CHAT_ID,
    OTHER_USER_ID,
    STRANGER_USER_ID,
    T0,
    FakeBot,
    keyboard_buttons,
    make_callback_update,
)
from tests.test_paper_shadow_runtime import T_APPROVE, T_CONFIRM, Rig

EVENT_FAILED = "SHADOW_KEYBOARD_REMOVAL_FAILED"
BAD_REQUEST = "Bad Request: message can't be edited"


async def _alerted(rig: Rig) -> str:
    """Send the alert and return its short id."""
    await rig.alert()
    return rig.buttons()[0][1].removeprefix("APR:")


async def _tap_without_hook(
    rig: Rig, data: str, query: str, *, at: datetime, message_id: int | None = 1
) -> DispatchResult:
    """The same press with the Phase 23 finalize hook and error journal left out (the baseline)."""
    rig.now = at
    kwargs = dict(rig.coordinator.callback_kwargs())
    kwargs.pop("finalize_message")
    kwargs.pop("error_journal")
    update = make_callback_update(data=data, chat_id=CHAT_ID, query_id=query, message_id=message_id)
    return await on_callback(update, cast(Any, None), **kwargs)


def _is_empty_keyboard(markup: Any) -> bool:
    return keyboard_buttons(markup) == []


def _texts(bot: FakeBot) -> list[tuple[str, int | None, str]]:
    return [(m.text, m.message_id, repr(m.reply_markup)) for m in [*bot.sent, *bot.edited]]


# --------------------------------------------------------------------------- #
# Task 1 (tracer): a SKP tap through coordinator.callback_kwargs.
# --------------------------------------------------------------------------- #


async def test_a_skip_removes_the_alert_keyboard_with_a_keyboard_only_edit() -> None:
    rig = Rig()
    short = await _alerted(rig)

    result = await rig.tap(f"SKP:{short}", "q-skp", at=T_APPROVE)

    assert result.ok is True
    assert [a.status for a in rig.stores.approvals.values()].count(ApprovalResult.SKIPPED) == 1
    (edit,) = rig.bot.markup_edits
    assert (edit.chat_id, edit.message_id) == (CHAT_ID, 1)
    assert _is_empty_keyboard(edit.reply_markup)
    assert rig.bot.edited == [], "the text of the alert is not touched"


async def test_the_skip_reply_text_equals_the_text_sent_without_the_hook() -> None:
    hooked = Rig()
    short = await _alerted(hooked)
    await hooked.tap(f"SKP:{short}", "q-skp", at=T_APPROVE)

    plain = Rig()
    short_plain = await _alerted(plain)
    assert short_plain == short
    await _tap_without_hook(plain, f"SKP:{short}", "q-skp", at=T_APPROVE)

    assert len(hooked.bot.markup_edits) == 1 and plain.bot.markup_edits == []
    assert _texts(hooked.bot) == _texts(plain.bot)
    assert len(hooked.bot.sent) == 2, "the alert and one decision reply, exactly as before"


async def test_a_press_refused_by_the_user_or_chat_gate_touches_no_message() -> None:
    rig = Rig()
    short = await _alerted(rig)

    await rig.tap(f"SKP:{short}", "q-stranger", user=STRANGER_USER_ID, at=T_APPROVE)
    await rig.tap(f"SKP:{short}", "q-chat", chat_id=OTHER_CHAT_ID, at=T_APPROVE)
    await rig.tap(f"APR:{short}", "q-nouser", user=None, at=T_APPROVE)

    assert rig.bot.markup_edits == []
    assert all(a.status is ApprovalResult.PENDING for a in rig.stores.approvals.values())


async def test_a_refused_keyboard_removal_is_journaled_and_the_skip_stands() -> None:
    rig = Rig()
    short = await _alerted(rig)
    rig.bot.queue_markup_error(tg_error.BadRequest(BAD_REQUEST))

    result = await rig.tap(f"SKP:{short}", "q-skp", at=T_APPROVE)

    assert result.ok is True, "no exception reaches on_callback and the decision stands"
    assert [a.status for a in rig.stores.approvals.values()].count(ApprovalResult.SKIPPED) == 1
    (row,) = rig.stores.journal_of_type(EVENT_FAILED)
    body = json.loads(row.payload_json)
    assert body["failure_kind"] == "REJECTED"
    assert body["trigger"] == "press" and body["mode"] == "SHADOW"
    assert body["short_id"] == short and body["message_id"] == 1 and body["attempts"] == 1
    assert row.journal_event_id.startswith("shadow-kbd_")
    assert BAD_REQUEST not in row.payload_json, "only the classified kind, never the text"


async def test_the_coordinator_wires_the_finalize_hook_and_the_error_journal() -> None:
    rig = Rig()
    kwargs = rig.coordinator.callback_kwargs()

    assert callable(kwargs["finalize_message"])
    assert callable(kwargs["error_journal"])


async def test_a_handler_exception_is_journaled_with_its_correlation_id() -> None:
    rig = Rig()
    short = await _alerted(rig)
    kwargs = dict(rig.coordinator.callback_kwargs())

    def broken_resolver(short_id: str) -> dict[str, Any] | None:
        raise RuntimeError("boom with a secret")

    kwargs["binding_context_resolver"] = broken_resolver
    update = make_callback_update(data=f"SKP:{short}", chat_id=CHAT_ID, query_id="q-boom")

    result = await on_callback(update, cast(Any, None), **kwargs)

    assert result.ok is False and result.reason_code == "CALLBACK_HANDLER_ERROR"
    (row,) = rig.stores.journal_of_type("CALLBACK_HANDLER_FAILED")
    assert row.correlation_id == "cbq:q-boom"
    assert "secret" not in row.payload_json
    assert rig.bot.markup_edits == [], "a failed press leaves the keyboard where it is"


# --------------------------------------------------------------------------- #
# Task 2: the card, the refusals, the TTL sweep and the cases that keep the keyboard.
# --------------------------------------------------------------------------- #

CARD_MESSAGE_ID = 1  # the alert is edited into the card: same message id


async def _approved(rig: Rig) -> str:
    """Alert and APPROVE: the alert became the confirmation card. Returns the short id."""
    short = await _alerted(rig)
    await rig.tap(f"APR:{short}", "q-apr", at=T_APPROVE)
    return short


async def test_an_approve_that_delivers_the_card_keeps_the_keyboard() -> None:
    rig = Rig()
    short = await _approved(rig)

    (card,) = rig.bot.edited
    assert [data for _label, data in keyboard_buttons(card.reply_markup)] == [
        f"CNF:{short}",
        f"CXL:{short}",
    ]
    assert rig.bot.markup_edits == []


async def test_confirm_removes_the_keyboard_of_the_card() -> None:
    rig = Rig()
    short = await _approved(rig)

    result = await rig.tap(f"CNF:{short}", "q-cnf", at=T_CONFIRM)

    assert result.ok is True
    (edit,) = rig.bot.markup_edits
    assert edit.message_id == CARD_MESSAGE_ID and _is_empty_keyboard(edit.reply_markup)
    assert len(rig.bot.edited) == 1, "only the card edit, never a text edit by the hook"


async def test_cancel_removes_the_keyboard_of_the_card() -> None:
    rig = Rig()
    short = await _approved(rig)

    result = await rig.tap(f"CXL:{short}", "q-cxl", at=T_CONFIRM)

    assert result.ok is True
    (edit,) = rig.bot.markup_edits
    assert edit.message_id == CARD_MESSAGE_ID and _is_empty_keyboard(edit.reply_markup)


async def test_a_confirm_by_another_user_keeps_the_keyboard_for_the_approver() -> None:
    rig = Rig()
    short = await _approved(rig)

    refused = await rig.tap(f"CNF:{short}", "q-other", user=OTHER_USER_ID, at=T_CONFIRM)

    assert refused.ok is False
    assert rig.bot.markup_edits == [], "REJECTED_USER_MISMATCH is not terminal"
    confirmed = await rig.tap(f"CNF:{short}", "q-own", at=T_CONFIRM)
    assert confirmed.ok is True
    assert len(rig.bot.markup_edits) == 1


async def test_a_confirm_after_the_plan_expiry_removes_the_keyboard() -> None:
    rig = Rig(confirm_ttl_seconds=8 * 3600)  # the plan expiry (4 h) is what ends it
    short = await _approved(rig)

    result = await rig.tap(f"CNF:{short}", "q-late", at=T0 + timedelta(hours=4))

    assert result.ok is False
    assert "REJECTED_PLAN_EXPIRED" in rig.bot.sent[-1].text
    assert len(rig.bot.markup_edits) == 1


async def test_a_confirm_refused_by_the_recheck_removes_the_keyboard() -> None:
    rig = Rig()
    rig.coordinator.confirm_book._recheck = lambda signal, plan, now: "INVALIDATED"  # type: ignore[attr-defined]
    short = await _approved(rig)

    result = await rig.tap(f"CNF:{short}", "q-rc", at=T_CONFIRM)

    assert result.ok is False
    assert len(rig.bot.markup_edits) == 1


async def test_an_approve_whose_card_could_not_be_delivered_removes_the_alert_keyboard() -> None:
    rig = Rig()
    short = await _alerted(rig)
    rig.bot.queue_error(tg_error.BadRequest("Message to edit not found"))
    rig.bot.queue_error(tg_error.NetworkError("fallback send failed"))

    await rig.tap(f"APR:{short}", "q-apr", at=T_APPROVE)

    (edit,) = rig.bot.markup_edits
    assert edit.message_id == 1 and _is_empty_keyboard(edit.reply_markup)
    assert [e.event_type for e in rig.stores.journal if "EXPIRED" in e.event_type]


async def test_a_stale_approve_after_a_skip_removes_the_keyboard_again() -> None:
    rig = Rig()
    short = await _alerted(rig)
    await rig.tap(f"SKP:{short}", "q-skp", at=T_APPROVE)

    stale = await rig.tap(f"APR:{short}", "q-stale", at=T_APPROVE + timedelta(seconds=2))

    assert stale.ok is False
    assert len(rig.bot.markup_edits) == 2
    assert [a.status for a in rig.stores.approvals.values()].count(ApprovalResult.SKIPPED) == 1


async def test_a_tap_after_the_plan_expiry_removes_the_keyboard() -> None:
    rig = Rig()
    short = await _alerted(rig)

    result = await rig.tap(f"APR:{short}", "q-late", at=T0 + timedelta(hours=4, seconds=1))

    assert result.ok is False and result.reason_code is RejectionReason.APPROVAL_EXPIRED
    assert len(rig.bot.markup_edits) == 1


async def test_a_store_failure_in_the_tap_keeps_the_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Rig()
    short = await _alerted(rig)

    def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("database down")

    monkeypatch.setattr(rig.stores, "save_atomic", broken)

    result = await rig.tap(f"APR:{short}", "q-apr", at=T_APPROVE)

    assert result.ok is False and result.reason_code == "APPROVAL_STORE_FAILURE"
    assert rig.bot.markup_edits == [], "a transient failure leaves the decision open"


async def test_the_ttl_sweep_removes_the_keyboard_of_an_expired_card_once() -> None:
    rig = Rig()
    await _approved(rig)

    await rig.coordinator.poll_once()  # inside the TTL: nothing expires
    assert rig.bot.markup_edits == []

    rig.now = T_APPROVE + timedelta(seconds=61)
    await rig.coordinator.poll_once()
    (edit,) = rig.bot.markup_edits
    assert edit.message_id == CARD_MESSAGE_ID and _is_empty_keyboard(edit.reply_markup)

    rig.now = T_APPROVE + timedelta(seconds=120)
    await rig.coordinator.poll_once()
    assert len(rig.bot.markup_edits) == 1, "a second tick does nothing"


async def test_the_ttl_sweep_skips_an_entry_without_a_message_id() -> None:
    rig = Rig()
    short = await _approved(rig)
    entry = rig.coordinator.confirm_book.get(short)
    assert entry is not None
    entry.message_id = None

    rig.now = T_APPROVE + timedelta(seconds=61)
    await rig.coordinator.poll_once()

    assert rig.bot.markup_edits == []
    assert entry.state is ConfirmState.EXPIRED


async def test_a_failed_removal_in_the_ttl_sweep_is_journaled() -> None:
    rig = Rig()
    await _approved(rig)
    rig.bot.queue_markup_error(tg_error.BadRequest(BAD_REQUEST))

    rig.now = T_APPROVE + timedelta(seconds=61)
    await rig.coordinator.poll_once()

    (row,) = rig.stores.journal_of_type(EVENT_FAILED)
    body = json.loads(row.payload_json)
    assert body["trigger"] == "ttl_expiry" and body["failure_kind"] == "REJECTED"
    assert row.correlation_id.startswith("shadow-confirm:")


async def _flow_skip(rig: Rig) -> None:
    short = await _alerted(rig)
    await rig.tap(f"SKP:{short}", "q-skp", at=T_APPROVE)


async def _flow_confirm(rig: Rig) -> None:
    short = await _approved(rig)
    await rig.tap(f"CNF:{short}", "q-cnf", at=T_CONFIRM)


async def _flow_cancel(rig: Rig) -> None:
    short = await _approved(rig)
    await rig.tap(f"CXL:{short}", "q-cxl", at=T_CONFIRM)


async def _flow_other_user_then_owner(rig: Rig) -> None:
    short = await _approved(rig)
    await rig.tap(f"CNF:{short}", "q-other", user=OTHER_USER_ID, at=T_CONFIRM)
    await rig.tap(f"CNF:{short}", "q-own", at=T_CONFIRM)


async def _flow_stale_approve(rig: Rig) -> None:
    short = await _alerted(rig)
    await rig.tap(f"SKP:{short}", "q-skp", at=T_APPROVE)
    await rig.tap(f"APR:{short}", "q-stale", at=T_APPROVE + timedelta(seconds=2))


async def _flow_card_not_delivered(rig: Rig) -> None:
    short = await _alerted(rig)
    rig.bot.queue_error(tg_error.BadRequest("Message to edit not found"))
    rig.bot.queue_error(tg_error.NetworkError("fallback send failed"))
    await rig.tap(f"APR:{short}", "q-apr", at=T_APPROVE)


async def _flow_ttl_sweep(rig: Rig) -> None:
    await _approved(rig)
    rig.now = T_APPROVE + timedelta(seconds=61)
    await rig.coordinator.poll_once()


FLOWS = [
    _flow_skip,
    _flow_confirm,
    _flow_cancel,
    _flow_other_user_then_owner,
    _flow_stale_approve,
    _flow_card_not_delivered,
    _flow_ttl_sweep,
]


@pytest.mark.parametrize("flow", FLOWS, ids=lambda f: f.__name__)
async def test_every_shadow_text_equals_the_text_sent_before_the_hook(
    flow: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    hooked = Rig()
    await flow(hooked)

    original = ShadowCoordinator.callback_kwargs

    def plain(self: ShadowCoordinator) -> dict[str, Any]:
        kwargs = original(self)
        kwargs.pop("finalize_message")
        kwargs.pop("error_journal")
        return kwargs

    monkeypatch.setattr(ShadowCoordinator, "callback_kwargs", plain)
    baseline = Rig()
    await flow(baseline)

    assert _texts(hooked.bot) == _texts(baseline.bot)
    assert len(hooked.bot.markup_edits) >= 1
