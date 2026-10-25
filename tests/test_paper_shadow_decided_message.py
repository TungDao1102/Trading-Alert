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
from datetime import datetime
from typing import Any, cast

from src.adapters.telegram_callbacks import DispatchResult, on_callback
from src.domain.enums import ApprovalResult
from telegram import error as tg_error

from tests.shadow_fakes import (
    CHAT_ID,
    OTHER_CHAT_ID,
    STRANGER_USER_ID,
    FakeBot,
    keyboard_buttons,
    make_callback_update,
)
from tests.test_paper_shadow_runtime import T_APPROVE, Rig

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
