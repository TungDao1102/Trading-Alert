"""Phase 23, plan 23-01: only a listed user in a private chat can decide (F-508, F-707).

The tracer slice: a press by a user who is not on the allow-list (or from a group, or without a
user) is refused BEFORE any short-id or token lookup, changes no approval, and is journaled with
only the pressing actor's id. An allowed press is decided with the presser recorded as actor.

No PTB Application is built and nothing touches the network: `on_callback` runs against
SimpleNamespace updates and the real `dispatch_callback` runs over recording callables.
"""

from __future__ import annotations

import inspect
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from src.adapters.telegram_callbacks import (
    EVENT_TYPE_CALLBACK_RECEIVED,
    EVENT_TYPE_CALLBACK_REJECTED,
    CallbackKind,
    DispatchResult,
    ParsedCallback,
    _build_chat_reject_receipt,
    _build_user_reject_receipt,
    authorized_user_gate,
    build_application,
    dispatch_callback,
    on_callback,
)
from src.approval.binding import Callback
from src.approval.mapping import derive_short_id
from src.approval.reason_codes import (
    ALREADY_DECIDED,
    APPROVAL_STORE_FAILURE,
    CALLBACK_HANDLER_ERROR,
    CHAT_NOT_PRIVATE,
    PHASE23_EDGE_CODES,
    USER_ID_UNAVAILABLE,
    USER_NOT_AUTHORIZED,
)
from src.approval.replay import resolve_callback
from src.approval.tokens import issue_one_time_token, token_hash_of
from src.domain.approval import Approval
from src.domain.enums import ApprovalAction, ApprovalResult, RejectionReason

from tests.shadow_fakes import (
    AUTHORIZED_USER_IDS,
    CHAT_ID,
    OTHER_USER_ID,
    STRANGER_USER_ID,
    USER_ID,
    make_callback_update,
)
from tests.support.press_identity import OWNER_PRESS

NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
EXPIRY = NOW + timedelta(hours=1)
PLAN_HASH = "0" * 64
PARAM_HASH = "1" * 64
SIGNAL_ID = "sig_auth_" + "0" * 55
SHORT_ID = derive_short_id(SIGNAL_ID)
ALLOW = frozenset({USER_ID})


# --------------------------------------------------------------------------- #
# Pure gate table.
# --------------------------------------------------------------------------- #


def test_gate_passes_the_listed_user_in_a_private_chat() -> None:
    assert (
        authorized_user_gate(
            from_user_id=USER_ID, chat_type="private", authorized_user_ids=frozenset({USER_ID})
        )
        is None
    )


@pytest.mark.parametrize("bad", [None, True, False, "777001", 1.5])
def test_gate_refuses_a_missing_or_non_integer_user_id(bad: object) -> None:
    assert (
        authorized_user_gate(from_user_id=bad, chat_type="private", authorized_user_ids=ALLOW)
        == USER_ID_UNAVAILABLE
    )


@pytest.mark.parametrize("chat_type", ["group", "supergroup", "channel", None, "", "Private"])
def test_gate_refuses_every_chat_type_but_private(chat_type: object) -> None:
    assert (
        authorized_user_gate(from_user_id=USER_ID, chat_type=chat_type, authorized_user_ids=ALLOW)
        == CHAT_NOT_PRIVATE
    )


def test_gate_refuses_a_user_that_is_not_listed() -> None:
    assert (
        authorized_user_gate(
            from_user_id=STRANGER_USER_ID, chat_type="private", authorized_user_ids=ALLOW
        )
        == USER_NOT_AUTHORIZED
    )


def test_gate_order_is_user_id_then_chat_type_then_membership() -> None:
    assert (
        authorized_user_gate(from_user_id=None, chat_type="group", authorized_user_ids=ALLOW)
        == USER_ID_UNAVAILABLE
    )
    assert (
        authorized_user_gate(
            from_user_id=STRANGER_USER_ID, chat_type="group", authorized_user_ids=ALLOW
        )
        == CHAT_NOT_PRIVATE
    )


@pytest.mark.parametrize(
    "bad_set",
    [frozenset(), {USER_ID}, frozenset({True}), frozenset({"1"}), frozenset({USER_ID, "1"})],
)
def test_gate_rejects_a_bad_allow_list_as_a_programming_error(bad_set: Any) -> None:
    with pytest.raises(ValueError):
        authorized_user_gate(from_user_id=USER_ID, chat_type="private", authorized_user_ids=bad_set)


# --------------------------------------------------------------------------- #
# End to end through on_callback and the real dispatch_callback.
# --------------------------------------------------------------------------- #


class Harness:
    """Recording lookups and journal around the real `dispatch_callback`."""

    def __init__(self, *, approval: Approval | None = None, raw: str = "") -> None:
        self.raw = raw
        self.approvals: dict[str, Approval] = {}
        if approval is not None:
            self.approvals[approval.approval_token_hash] = approval
        self.short_lookups: list[str] = []
        self.hash_lookups: list[str] = []
        self.saved: list[Approval] = []
        self.journal: list[Any] = []
        self.replies: list[tuple[int, str]] = []

    def lookup_by_short_id(self, short_id: str) -> tuple[str, str] | None:
        self.short_lookups.append(short_id)
        return (SIGNAL_ID, "tp_auth")

    def lookup_by_token_hash(self, token_hash: str) -> Approval | None:
        self.hash_lookups.append(token_hash)
        return self.approvals.get(token_hash)

    def save_atomic(self, approval: Approval, mapping: Any) -> None:
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
        from_user_id: int | None,
        chat_type: str | None = "private",
        chat_id: int = CHAT_ID,
        query_id: str = "q-auth-1",
        allow: frozenset[int] = ALLOW,
    ) -> DispatchResult:
        update = make_callback_update(
            data="APR:" + SHORT_ID,
            chat_id=chat_id,
            query_id=query_id,
            message_chat_id=chat_id,
            from_user_id=from_user_id,
            chat_type=chat_type,
        )
        return await on_callback(
            update,
            None,  # type: ignore[arg-type]
            authorized_chat_id=CHAT_ID,
            authorized_user_ids=allow,
            binding_context_resolver=self.binding,
            dispatch=self.dispatch,
            reply_text_fn=self.reply,
            clock=lambda: NOW,
        )

    def payloads(self, event_type: str) -> list[dict[str, Any]]:
        return [json.loads(e.payload_json) for e in self.journal if e.event_type == event_type]


def _pending(raw: str) -> Approval:
    return Approval(
        approval_id="appr_auth_0000000000000000000000000000000000000000",
        trade_plan_id="tp_auth",
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


async def test_a_stranger_is_refused_before_any_lookup_and_journaled_with_only_his_id() -> None:
    raw = issue_one_time_token()
    harness = Harness(approval=_pending(raw), raw=raw)

    result = await harness.press(from_user_id=STRANGER_USER_ID, allow=frozenset({USER_ID, 777009}))

    assert harness.short_lookups == []
    assert harness.hash_lookups == []
    assert harness.saved == []
    assert result.ok is False
    assert result.reason_code == USER_NOT_AUTHORIZED
    received = harness.payloads(EVENT_TYPE_CALLBACK_RECEIVED)
    assert len(received) == 1
    assert received[0]["user_gate_rejected"] is True
    assert received[0]["reason"] == USER_NOT_AUTHORIZED
    assert received[0]["from_user_id"] == STRANGER_USER_ID
    assert received[0]["chat_type"] == "private"
    rejected = harness.payloads(EVENT_TYPE_CALLBACK_REJECTED)
    assert len(rejected) == 1
    assert rejected[0]["reason_code"] == "USER_NOT_AUTHORIZED"
    # The allow-list never reaches the journal: only the presser's id does.
    for event in harness.journal:
        assert "777009" not in event.payload_json
        assert str(USER_ID) not in event.payload_json
    assert harness.replies == [(CHAT_ID, "Rejected")]
    stored = harness.approvals[token_hash_of(raw)]
    assert stored.status == ApprovalResult.PENDING


async def test_a_group_with_the_authorized_chat_id_is_refused_before_any_lookup() -> None:
    harness = Harness()
    result = await harness.press(from_user_id=USER_ID, chat_type="supergroup")

    assert harness.short_lookups == [] and harness.hash_lookups == [] and harness.saved == []
    assert result.ok is False and result.reason_code == CHAT_NOT_PRIVATE
    received = harness.payloads(EVENT_TYPE_CALLBACK_RECEIVED)
    assert received[0]["reason"] == CHAT_NOT_PRIVATE
    assert received[0]["chat_type"] == "supergroup"
    assert harness.replies == [(CHAT_ID, "Rejected")]


async def test_a_press_without_a_user_is_refused_before_any_lookup() -> None:
    harness = Harness()
    result = await harness.press(from_user_id=None)

    assert harness.short_lookups == [] and harness.hash_lookups == [] and harness.saved == []
    assert result.ok is False and result.reason_code == USER_ID_UNAVAILABLE
    received = harness.payloads(EVENT_TYPE_CALLBACK_RECEIVED)
    assert received[0]["from_user_id"] is None
    assert harness.replies == [(CHAT_ID, "Rejected")]


async def test_a_press_without_a_chat_type_is_refused() -> None:
    harness = Harness()
    result = await harness.press(from_user_id=USER_ID, chat_type=None)
    assert result.reason_code == CHAT_NOT_PRIVATE
    assert harness.short_lookups == []


async def test_the_gate_holds_even_when_the_dispatcher_ignores_the_new_keywords() -> None:
    seen: list[dict[str, Any]] = []

    def lax_dispatch(parsed: ParsedCallback, **kwargs: Any) -> DispatchResult:
        seen.append(kwargs)
        return DispatchResult(ok=True, kind=parsed.kind)

    update = make_callback_update(
        data="APR:" + SHORT_ID, chat_id=CHAT_ID, query_id="q-lax", from_user_id=STRANGER_USER_ID
    )
    result = await on_callback(
        update,
        None,  # type: ignore[arg-type]
        authorized_chat_id=CHAT_ID,
        authorized_user_ids=ALLOW,
        binding_context_resolver=lambda sid: {"raw_token": "x"},
        dispatch=lax_dispatch,
        clock=lambda: NOW,
    )
    assert result.ok is False
    assert result.reason_code == USER_NOT_AUTHORIZED
    assert all(kw.get("binding_context") is None and kw.get("raw_token") == "" for kw in seen)


async def test_an_allowed_press_is_decided_with_the_presser_as_actor_and_replay_keeps_it() -> None:
    raw = issue_one_time_token()
    harness = Harness(approval=_pending(raw), raw=raw)

    first = await harness.press(from_user_id=USER_ID, allow=AUTHORIZED_USER_IDS)
    assert first.ok is True
    assert first.approval is not None
    assert first.approval.status == ApprovalResult.APPROVED
    assert first.approval.actor_id == str(USER_ID)
    assert len(harness.saved) == 1
    assert harness.saved[0].actor_id == "777001"

    # A second press by another listed user replays the stored row and keeps the first actor.
    second = await harness.press(
        from_user_id=OTHER_USER_ID, query_id="q-auth-2", allow=AUTHORIZED_USER_IDS
    )
    assert second.ok is True
    assert second.approval is not None
    assert second.approval.actor_id == "777001"
    assert len(harness.saved) == 1


# --------------------------------------------------------------------------- #
# dispatch_callback directly, resolve_callback, receipts.
# --------------------------------------------------------------------------- #


def _direct_dispatch(journal: list[Any], **gate: Any) -> DispatchResult:
    return dispatch_callback(
        ParsedCallback(raw="APR:" + SHORT_ID, kind=CallbackKind.APPROVE, short_id=SHORT_ID),
        callback_chat_id=CHAT_ID,
        authorized_chat_id=CHAT_ID,
        callback_at_utc=NOW,
        raw_token="t",
        correlation_id="cbq:direct",
        journal_receipt=journal.append,
        lookup_by_short_id=lambda sid: None,
        lookup_by_token_hash=lambda th: None,
        save_atomic=lambda approval, mapping: None,
        now_utc=NOW,
        binding_context=None,
        **gate,
    )


def test_dispatch_has_no_way_to_skip_the_user_gate() -> None:
    """WR-01: the three user-gate keywords are required, an allow-list is never optional."""
    journal: list[Any] = []
    with pytest.raises(TypeError):
        _direct_dispatch(journal)
    with pytest.raises(ValueError, match="authorized_user_ids"):
        _direct_dispatch(
            journal, from_user_id=USER_ID, chat_type="private", authorized_user_ids=None
        )
    with pytest.raises(ValueError, match="authorized_user_ids"):
        _direct_dispatch(
            journal, from_user_id=USER_ID, chat_type="private", authorized_user_ids=frozenset()
        )
    assert journal == []


def test_dispatch_with_an_allow_list_still_runs_the_gate_and_the_lookup() -> None:
    journal: list[Any] = []
    result = _direct_dispatch(journal, **OWNER_PRESS)
    assert result.reason_code == RejectionReason.INVALIDATED
    refused = _direct_dispatch(
        journal, from_user_id=USER_ID + 1, chat_type="private", authorized_user_ids=ALLOW
    )
    assert refused.reason_code == USER_NOT_AUTHORIZED


def test_a_store_failure_is_reported_with_its_own_code() -> None:
    raw = issue_one_time_token()
    approval = _pending(raw)
    journal: list[Any] = []

    def failing_save(a: Approval, mapping: Any) -> None:
        raise ConnectionError("db down")

    result = dispatch_callback(
        ParsedCallback(raw="APR:" + SHORT_ID, kind=CallbackKind.APPROVE, short_id=SHORT_ID),
        callback_chat_id=CHAT_ID,
        authorized_chat_id=CHAT_ID,
        callback_at_utc=NOW,
        raw_token=raw,
        correlation_id="cbq:store",
        journal_receipt=journal.append,
        lookup_by_short_id=lambda sid: (SIGNAL_ID, "tp_auth"),
        lookup_by_token_hash=lambda th: approval,
        save_atomic=failing_save,
        now_utc=NOW,
        binding_context={
            "plan_hash": PLAN_HASH,
            "strategy_version": "v1.0.0",
            "parameter_set_id": "ps-1",
            "parameter_set_hash": PARAM_HASH,
            "expiry_utc": EXPIRY,
        },
        from_user_id=USER_ID,
        chat_type="private",
        authorized_user_ids=ALLOW,
    )
    assert result.ok is False
    assert result.reason_code == APPROVAL_STORE_FAILURE
    rejected = [json.loads(e.payload_json) for e in journal if e.event_type == "CALLBACK_REJECTED"]
    assert rejected[0]["reason_code"] == "APPROVAL_STORE_FAILURE"


def test_resolve_callback_sets_the_actor_and_rejects_an_overlong_one() -> None:
    raw = issue_one_time_token()
    approval = _pending(raw)
    saved: list[Approval] = []
    callback = Callback(
        raw_token=raw,
        chat_id=CHAT_ID,
        plan_hash=PLAN_HASH,
        strategy_version="v1.0.0",
        parameter_set_id="ps-1",
        parameter_set_hash=PARAM_HASH,
        callback_at_utc=NOW,
        action=ApprovalAction.APPROVE,
    )
    kwargs: dict[str, Any] = {
        "authorized_chat_id": CHAT_ID,
        "expiry_utc": EXPIRY,
        "approval_strategy_version": "v1.0.0",
        "approval_parameter_set_id": "ps-1",
        "approval_parameter_set_hash": PARAM_HASH,
        "now_utc": NOW,
    }
    with pytest.raises(ValueError):
        resolve_callback(callback, lambda th: approval, saved.append, actor_id="9" * 65, **kwargs)
    assert saved == []
    decided = resolve_callback(callback, lambda th: approval, saved.append, actor_id="42", **kwargs)
    assert decided.actor_id == "42"
    assert saved[0].actor_id == "42"
    # Without an actor the stored one (here empty) is kept.
    keep = resolve_callback(
        callback, lambda th: replace(approval, actor_id="pre"), saved.append, **kwargs
    )
    assert keep.actor_id == "pre"


def test_user_reject_and_chat_reject_receipts_have_distinct_event_ids() -> None:
    parsed = ParsedCallback(raw="APR:" + SHORT_ID, kind=CallbackKind.APPROVE, short_id=SHORT_ID)
    user_receipt = _build_user_reject_receipt(
        parsed=parsed,
        callback_chat_id=CHAT_ID,
        from_user_id=STRANGER_USER_ID,
        chat_type="private",
        reason=USER_NOT_AUTHORIZED,
        callback_at_utc=NOW,
        correlation_id="cbq:same",
    )
    chat_receipt = _build_chat_reject_receipt(
        parsed=parsed, callback_chat_id=CHAT_ID, callback_at_utc=NOW, correlation_id="cbq:same"
    )
    assert user_receipt.journal_event_id != chat_receipt.journal_event_id


# --------------------------------------------------------------------------- #
# Signature pins and reason codes.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("function", [on_callback, build_application])
def test_authorized_user_ids_is_required_keyword_only(function: Any) -> None:
    parameter = inspect.signature(function).parameters["authorized_user_ids"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


async def test_on_callback_rejects_a_bad_allow_list_at_the_entry() -> None:
    update = make_callback_update(data="APR:" + SHORT_ID, chat_id=CHAT_ID, query_id="q-bad")
    for bad in (frozenset(), frozenset({True})):
        with pytest.raises(ValueError):
            await on_callback(
                update,
                None,  # type: ignore[arg-type]
                authorized_chat_id=CHAT_ID,
                authorized_user_ids=bad,
                binding_context_resolver=lambda sid: None,
                dispatch=lambda parsed, **kw: DispatchResult(ok=True, kind=parsed.kind),
            )


def test_build_application_rejects_a_bad_allow_list_before_building_anything() -> None:
    with pytest.raises(ValueError):
        build_application(
            token="123:abc",
            authorized_chat_id=CHAT_ID,
            authorized_user_ids=frozenset(),
            binding_context_resolver=lambda sid: None,
            dispatch=lambda parsed, **kw: DispatchResult(ok=True, kind=parsed.kind),
        )


def test_the_new_codes_are_plain_strings_and_the_enum_is_untouched() -> None:
    assert len(PHASE23_EDGE_CODES) == 6
    for code in PHASE23_EDGE_CODES:
        assert type(code) is str
        assert not isinstance(code, RejectionReason)
    assert {
        USER_ID_UNAVAILABLE,
        CHAT_NOT_PRIVATE,
        USER_NOT_AUTHORIZED,
        APPROVAL_STORE_FAILURE,
        ALREADY_DECIDED,
        CALLBACK_HANDLER_ERROR,
    } == set(PHASE23_EDGE_CODES)
    assert len(RejectionReason) == 21
