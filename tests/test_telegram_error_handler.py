"""Phase 23, plan 23-07: Telegram error handling at the edge (D-08, F-512).

The live test of 2026-10-04 found no application error handler: callbacks queued during downtime
raised `BadRequest: Query is too old` at `query.answer()`. This file pins the three parts:

* `make_application_error_handler` logs only the exception class and the callback correlation id;
* `on_callback` journals an exception raised after the gates (CALLBACK_HANDLER_FAILED) and answers
  the authorized chat neutrally; nothing propagates (but `CancelledError` does);
* an expired query at `query.answer()` is logged at debug level and the press is still processed.

`build_application` is never called from a test (existing rule): a static AST check finds the
`add_error_handler(make_application_error_handler())` call instead.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
import src.adapters.telegram_callbacks as callbacks_module
from src.adapters.telegram_callbacks import (
    EVENT_TYPE_CALLBACK_HANDLER_FAILED,
    CallbackPress,
    DispatchResult,
    ParsedCallback,
    dispatch_callback,
    make_application_error_handler,
    on_callback,
)
from src.approval.mapping import derive_short_id
from src.approval.reason_codes import CALLBACK_HANDLER_ERROR
from src.approval.tokens import issue_one_time_token, token_hash_of
from src.domain.approval import Approval
from src.domain.enums import ApprovalAction, ApprovalResult
from src.domain.journal import JournalEvent
from telegram import error as tg_error

from tests.shadow_fakes import CHAT_ID, USER_ID, make_callback_update

NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
EXPIRY = NOW + timedelta(hours=1)
PLAN_HASH = "0" * 64
PARAM_HASH = "1" * 64
SIGNAL_ID = "sig_err_" + "0" * 56
SHORT_ID = derive_short_id(SIGNAL_ID)
ALLOW = frozenset({USER_ID})
SECRET = "secret-ish text 123456:ABCdef"


# --------------------------------------------------------------------------- #
# The application error handler.
# --------------------------------------------------------------------------- #


async def test_the_error_handler_logs_the_class_and_the_correlation_id_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    handler = make_application_error_handler()
    update = SimpleNamespace(callback_query=SimpleNamespace(id="q1", data="APR:" + SHORT_ID))
    context = SimpleNamespace(error=RuntimeError(SECRET))

    with caplog.at_level(logging.ERROR, logger="src.adapters.telegram_callbacks"):
        await handler(update, context)

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    text = caplog.text
    assert "RuntimeError" in text
    assert "cbq:q1" in text
    assert "secret-ish" not in text
    assert "ABCdef" not in text
    assert SHORT_ID not in text


async def test_the_error_handler_logs_the_class_only_without_an_update(
    caplog: pytest.LogCaptureFixture,
) -> None:
    handler = make_application_error_handler()
    with caplog.at_level(logging.ERROR, logger="src.adapters.telegram_callbacks"):
        await handler(None, SimpleNamespace(error=tg_error.NetworkError(SECRET)))
    assert "NetworkError" in caplog.text
    assert "cbq:" not in caplog.text
    assert "secret-ish" not in caplog.text


@pytest.mark.parametrize(
    "update, context",
    [
        (object(), SimpleNamespace(error=None)),
        (SimpleNamespace(callback_query=None), SimpleNamespace()),
        (SimpleNamespace(callback_query=SimpleNamespace(id=5)), SimpleNamespace(error=KeyError())),
        (None, None),
    ],
)
async def test_the_error_handler_never_raises(update: Any, context: Any) -> None:
    await make_application_error_handler()(update, context)


def test_build_application_registers_the_error_handler() -> None:
    tree = ast.parse(inspect.getsource(callbacks_module.build_application).replace("\r", ""))
    found = False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_error_handler"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Call)
            and isinstance(node.args[0].func, ast.Name)
            and node.args[0].func.id == "make_application_error_handler"
        ):
            found = True
    assert found, "build_application must call add_error_handler(make_application_error_handler())"


# --------------------------------------------------------------------------- #
# on_callback: an exception after the gates.
# --------------------------------------------------------------------------- #


class Harness:
    def __init__(self, raw: str) -> None:
        self.raw = raw
        approval = Approval(
            approval_id="appr_err_00000000000000000000000000000000000000000",
            trade_plan_id="tp_err",
            signal_id=SIGNAL_ID,
            action=ApprovalAction.APPROVE,
            result=ApprovalResult.PENDING,
            status=ApprovalResult.PENDING,
            approval_token_hash=token_hash_of(raw),
            requested_at_utc=NOW - timedelta(minutes=5),
            acted_at_utc=None,
            actor_id="",
            telegram_message_id=None,
            request_hash=PLAN_HASH,
        )
        self.approvals: dict[str, Approval] = {approval.approval_token_hash: approval}
        self.journal: list[JournalEvent] = []
        self.error_events: list[JournalEvent] = []
        self.replies: list[tuple[int, str]] = []
        self.answered = 0
        self.saved: list[Approval] = []

    def dispatch(self, parsed: ParsedCallback, **kwargs: Any) -> DispatchResult:
        return dispatch_callback(
            parsed,
            journal_receipt=self.journal.append,
            lookup_by_short_id=lambda short_id: (SIGNAL_ID, "tp_err"),
            lookup_by_token_hash=self.approvals.get,
            save_atomic=self._save,
            now_utc=NOW,
            **kwargs,
        )

    def _save(self, approval: Approval, mapping: Any) -> None:
        self.saved.append(approval)
        self.approvals[approval.approval_token_hash] = approval

    async def reply(self, chat_id: int, text: str) -> None:
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

    async def press(
        self,
        *,
        approved_handler: Any = None,
        error_journal: Any = None,
        answer: Any = None,
        query_id: str = "q-err-1",
        chat_id: int = CHAT_ID,
        reply: bool = True,
    ) -> DispatchResult:
        update = make_callback_update(
            data="APR:" + SHORT_ID,
            chat_id=chat_id,
            query_id=query_id,
            message_chat_id=chat_id,
            answer=answer,
        )
        return await on_callback(
            update,
            None,  # type: ignore[arg-type]
            authorized_chat_id=CHAT_ID,
            authorized_user_ids=ALLOW,
            binding_context_resolver=self.binding,
            dispatch=self.dispatch,
            reply_text_fn=self.reply if reply else None,
            approved_handler=approved_handler,
            error_journal=error_journal,
            clock=lambda: NOW,
        )


async def _raises_key_error(press: CallbackPress, result: DispatchResult) -> bool:
    raise KeyError(SECRET)


async def test_a_handler_exception_is_journaled_and_answered_neutrally(
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = Harness(issue_one_time_token())

    with caplog.at_level(logging.ERROR, logger="src.adapters.telegram_callbacks"):
        result = await harness.press(
            approved_handler=_raises_key_error, error_journal=harness.error_events.append
        )

    assert result.ok is False
    assert result.reason_code == CALLBACK_HANDLER_ERROR
    assert len(harness.error_events) == 1
    event = harness.error_events[0]
    assert event.event_type == EVENT_TYPE_CALLBACK_HANDLER_FAILED == "CALLBACK_HANDLER_FAILED"
    assert event.correlation_id == "cbq:q-err-1"
    payload = json.loads(event.payload_json)
    assert payload["error_class"] == "KeyError"
    assert payload["short_id"] == SHORT_ID
    assert payload["kind"] == "APPROVE"
    assert payload["correlation_id"] == "cbq:q-err-1"
    for needle in ("secret-ish", "ABCdef"):
        assert needle not in event.payload_json
        assert needle not in caplog.text
    assert "KeyError" in caplog.text
    assert "cbq:q-err-1" in caplog.text
    # The only reply is the neutral text, in the authorized chat.
    assert len(harness.replies) == 1
    chat_id, text = harness.replies[0]
    assert chat_id == CHAT_ID
    assert "cbq:q-err-1" in text
    assert "Do not tap again" in text
    assert "secret-ish" not in text


async def test_the_same_happens_without_an_error_journal() -> None:
    harness = Harness(issue_one_time_token())
    result = await harness.press(approved_handler=_raises_key_error)
    assert result.ok is False and result.reason_code == CALLBACK_HANDLER_ERROR
    assert len(harness.replies) == 1
    assert harness.error_events == []


async def test_a_failing_error_journal_is_logged_and_swallowed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = Harness(issue_one_time_token())

    def broken_journal(event: JournalEvent) -> None:
        raise OSError(SECRET)

    with caplog.at_level(logging.ERROR, logger="src.adapters.telegram_callbacks"):
        result = await harness.press(
            approved_handler=_raises_key_error, error_journal=broken_journal
        )

    assert result.ok is False and result.reason_code == CALLBACK_HANDLER_ERROR
    assert "OSError" in caplog.text
    assert "secret-ish" not in caplog.text
    # The neutral answer still goes out.
    assert len(harness.replies) == 1


async def test_a_failing_neutral_reply_is_logged_and_swallowed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = Harness(issue_one_time_token())

    async def broken_reply(chat_id: int, text: str) -> None:
        raise tg_error.NetworkError(SECRET)

    harness.reply = broken_reply  # type: ignore[method-assign]
    with caplog.at_level(logging.ERROR, logger="src.adapters.telegram_callbacks"):
        result = await harness.press(approved_handler=_raises_key_error)
    assert result.ok is False and result.reason_code == CALLBACK_HANDLER_ERROR
    assert "secret-ish" not in caplog.text


async def test_cancellation_still_propagates() -> None:
    harness = Harness(issue_one_time_token())

    async def cancelled(press: CallbackPress, result: DispatchResult) -> bool:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await harness.press(approved_handler=cancelled, error_journal=harness.error_events.append)
    assert harness.error_events == []


async def test_no_neutral_reply_without_a_reply_function() -> None:
    harness = Harness(issue_one_time_token())
    result = await harness.press(approved_handler=_raises_key_error, reply=False)
    assert result.reason_code == CALLBACK_HANDLER_ERROR
    assert harness.replies == []


async def test_a_good_press_journals_no_handler_failure() -> None:
    harness = Harness(issue_one_time_token())
    result = await harness.press(error_journal=harness.error_events.append)
    assert result.ok is True
    assert harness.error_events == []


@pytest.mark.parametrize(
    "bad_update",
    [
        SimpleNamespace(callback_query=None),
        SimpleNamespace(
            callback_query=SimpleNamespace(id="q", data=None, message=SimpleNamespace(chat_id=1)),
            effective_chat=SimpleNamespace(id=CHAT_ID, type="private"),
        ),
        SimpleNamespace(
            callback_query=SimpleNamespace(
                id="q", data="APR:" + SHORT_ID, message=None, answer=lambda: None
            ),
            effective_chat=SimpleNamespace(id=CHAT_ID, type="private"),
        ),
    ],
)
async def test_a_malformed_update_still_raises_value_error(bad_update: Any) -> None:
    harness = Harness(issue_one_time_token())
    with pytest.raises((ValueError, TypeError)):
        await on_callback(
            bad_update,
            None,  # type: ignore[arg-type]
            authorized_chat_id=CHAT_ID,
            authorized_user_ids=ALLOW,
            binding_context_resolver=harness.binding,
            dispatch=harness.dispatch,
            error_journal=harness.error_events.append,
            clock=lambda: NOW,
        )
    assert harness.error_events == []


# --------------------------------------------------------------------------- #
# answer_callback_safely: an expired query.
# --------------------------------------------------------------------------- #


async def test_query_is_too_old_is_a_debug_log_and_the_press_is_still_processed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = Harness(issue_one_time_token())

    async def expired(*args: Any, **kwargs: Any) -> None:
        raise tg_error.BadRequest(
            "Query is too old and response timeout expired or query id is invalid"
        )

    with caplog.at_level(logging.DEBUG, logger="src.adapters.telegram_callbacks"):
        result = await harness.press(answer=expired)

    assert result.ok is True
    assert len(harness.saved) == 1
    answered = [r for r in caplog.records if "telegram.callback.answer_expired" in r.getMessage()]
    assert len(answered) == 1
    assert answered[0].levelno == logging.DEBUG
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


async def test_any_other_answer_failure_keeps_the_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = Harness(issue_one_time_token())

    async def failing(*args: Any, **kwargs: Any) -> None:
        raise tg_error.BadRequest("Bad Request: some other refusal")

    with caplog.at_level(logging.DEBUG, logger="src.adapters.telegram_callbacks"):
        result = await harness.press(answer=failing)

    assert result.ok is True
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "telegram.callback.answer_failed" in warnings[0].getMessage()
    assert "BadRequest" in warnings[0].getMessage()
    assert "some other refusal" not in caplog.text
