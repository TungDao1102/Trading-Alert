"""SHADOW alert and message catalogue tests (Phase 16, plan 16-04, Task 1, D-12, D-16, D-35, SC5).

A SHADOW alert is labelled, backed by PENDING approval rows and live APR:/SKP: buttons, and an
APPROVE tap moves the approval to APPROVED through the existing `dispatch_callback`. Every text
the SHADOW layer builds goes through `render_shadow_message`, so each one carries the exact label,
the mode and every time in UTC and Asia/Ho_Chi_Minh. No network, no real Telegram.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from src.adapters.telegram_callbacks import dispatch_callback, parse_callback_data
from src.approval.tokens import token_hash_of
from src.domain.enums import ApprovalAction, ApprovalResult
from src.paper.shadow import (
    SHADOW_LABEL,
    Mode,
    ShadowApprovalBook,
    ShadowDecisionOutcome,
    ShadowMessageKind,
    format_shadow_alert,
    format_time_pair,
    render_shadow_message,
    require_shadow,
    send_shadow_alert,
)

from tests.shadow_fakes import (
    CHAT_ID,
    T0,
    FakeBot,
    InMemoryShadowStores,
    RecordingSleep,
    assert_shadow_text,
    keyboard_buttons,
    make_shadow_plan,
    make_shadow_signal,
)

REASONS = ["SETUP_DETECTED"]
T_CALLBACK = T0 + timedelta(minutes=7)


def _alert_kwargs() -> dict[str, Any]:
    return {"exposure_quote": Decimal("0"), "reason_codes": REASONS}


async def _send(
    stores: InMemoryShadowStores,
    bot: FakeBot,
    book: ShadowApprovalBook,
    *,
    n: int = 1,
) -> Any:
    signal = make_shadow_signal(n)
    plan = make_shadow_plan(signal)
    outcome = await send_shadow_alert(
        stores=stores,
        book=book,
        bot=bot,
        chat_id=CHAT_ID,
        mode=Mode.SHADOW,
        signal=signal,
        plan=plan,
        now_utc=T0,
        sleep=RecordingSleep(),
        **_alert_kwargs(),
    )
    return signal, plan, outcome


# --------------------------------------------------------------------------- #
# Test 1: the formatter.
# --------------------------------------------------------------------------- #


def test_alert_text_carries_label_mode_and_both_time_zones() -> None:
    signal = make_shadow_signal()
    plan = make_shadow_plan(signal)

    text = format_shadow_alert(
        signal=signal, plan=plan, mode=Mode.SHADOW, now_utc=T0, **_alert_kwargs()
    )

    assert "SHADOW — no real order" in text
    assert SHADOW_LABEL == "SHADOW — no real order"
    assert "Mode: SHADOW" in text
    assert "2026-10-09 07:00:00 UTC (2026-10-09 14:00:00 Asia/Ho_Chi_Minh)" in text  # expiry
    assert "2026-10-09 03:00:00 UTC (2026-10-09 10:00:00 Asia/Ho_Chi_Minh)" in text  # now
    assert_shadow_text(text)
    # The 12 APRV-01 fields are still there.
    for needle in ("BTCUSDT", "LONG", "TREND_PULLBACK_LONG", "SL: 49500", "TP1: 51000", "R:R: 2"):
        assert needle in text


# --------------------------------------------------------------------------- #
# Test 2: parents first, journal first, then one send with two live buttons.
# --------------------------------------------------------------------------- #


async def test_send_shadow_alert_writes_parents_journal_then_sends_two_live_buttons() -> None:
    trace: list[str] = []
    stores = InMemoryShadowStores(trace)
    bot = FakeBot(trace)
    book = ShadowApprovalBook(stores, clock=lambda: T0)

    signal, plan, outcome = await _send(stores, bot, book)

    assert trace == [
        "insert_signal",
        "insert_trade_plan",
        "insert_pending",
        "insert_pending",
        "record_short_id_mapping",
        "journal:SHADOW_ALERT_PENDING",
        "send",
        "journal:SHADOW_ALERT_SENT",
    ]
    assert outcome.sent is True
    assert len(bot.sent) == 1
    sent = bot.sent[0]
    assert sent.chat_id == CHAT_ID
    assert_shadow_text(sent.text)

    buttons = keyboard_buttons(sent.reply_markup)
    assert [label for label, _ in buttons] == ["APPROVE", "SKIP"]
    apr, skp = (data for _, data in buttons)
    assert apr.startswith("APR:") and skp.startswith("SKP:")
    short = apr[len("APR:") :]
    assert len(short) == 32 and skp == f"SKP:{short}"
    assert not any(data.startswith(("SIM:", "SKIP:")) for _, data in buttons)

    approvals = {a.action: a for a in stores.approvals.values()}
    assert set(approvals) == {ApprovalAction.APPROVE, ApprovalAction.SKIP_USER}
    for approval in approvals.values():
        assert approval.status == ApprovalResult.PENDING
        assert approval.requested_at_utc == T0
        assert approval.acted_at_utc is None
        assert approval.request_hash == plan.plan_hash
        assert approval.signal_id == signal.signal_id
    assert stores.lookup_by_short_id(short) == (signal.signal_id, plan.trade_plan_id)

    # The raw tokens live in memory only (T-16-10).
    context = book.resolve(short)
    assert context is not None
    stored_text = repr(list(stores.approvals.values())) + "".join(stores.journal_payloads())
    stored_text += "".join(event.journal_event_id for event in stores.journal)
    for raw in (context["raw_token"], context["skip_raw_token"]):
        assert raw not in stored_text
        assert raw not in sent.text
        assert token_hash_of(raw) in {a.approval_token_hash for a in approvals.values()}
    assert approvals[ApprovalAction.APPROVE].approval_token_hash != (
        approvals[ApprovalAction.SKIP_USER].approval_token_hash
    )


# --------------------------------------------------------------------------- #
# Test 3: an APPROVE tap reaches APPROVED through dispatch_callback.
# --------------------------------------------------------------------------- #


async def test_approve_callback_moves_approval_to_approved_with_timestamps() -> None:
    stores = InMemoryShadowStores()
    bot = FakeBot()
    book = ShadowApprovalBook(stores, clock=lambda: T_CALLBACK)
    _, _, _ = await _send(stores, bot, book)
    apr = keyboard_buttons(bot.sent[0].reply_markup)[0][1]
    parsed = parse_callback_data(apr)
    context = book.resolve(parsed.short_id)
    assert context is not None

    result = book.dispatch(
        parsed,
        callback_chat_id=CHAT_ID,
        authorized_chat_id=CHAT_ID,
        callback_at_utc=T_CALLBACK,
        raw_token=context["raw_token"],
        correlation_id="cbq:approve-1",
        binding_context=context,
    )

    assert result.ok is True
    assert result.approval is not None
    assert result.approval.status == ApprovalResult.APPROVED
    assert result.approval.requested_at_utc == T0
    assert result.approval.acted_at_utc == T_CALLBACK
    assert result.approval.actor_id == str(CHAT_ID)
    stored = stores.lookup_by_token_hash(token_hash_of(context["raw_token"]))
    assert stored == result.approval


async def test_the_resolve_context_works_with_the_stock_dispatch_callback() -> None:
    stores = InMemoryShadowStores()
    bot = FakeBot()
    book = ShadowApprovalBook(stores, clock=lambda: T_CALLBACK)
    await _send(stores, bot, book)
    parsed = parse_callback_data(keyboard_buttons(bot.sent[0].reply_markup)[0][1])
    context = book.resolve(parsed.short_id)
    assert context is not None
    journal_events: list[Any] = []

    result = dispatch_callback(
        parsed,
        callback_chat_id=CHAT_ID,
        authorized_chat_id=CHAT_ID,
        callback_at_utc=T_CALLBACK,
        raw_token=context["raw_token"],
        correlation_id="cbq:stock-1",
        journal_receipt=journal_events.append,
        lookup_by_short_id=stores.lookup_by_short_id,
        lookup_by_token_hash=stores.lookup_by_token_hash,
        save_atomic=stores.save_atomic,
        now_utc=T_CALLBACK,
        binding_context=context,
    )

    assert result.ok is True
    assert result.approval is not None
    assert result.approval.status == ApprovalResult.APPROVED
    assert result.approval.acted_at_utc == T_CALLBACK


def test_resolve_returns_none_for_an_unknown_short_id() -> None:
    book = ShadowApprovalBook(InMemoryShadowStores(), clock=lambda: T0)

    assert book.resolve("0" * 32) is None


# --------------------------------------------------------------------------- #
# Test 4: the message catalogue (D-12, D-35).
# --------------------------------------------------------------------------- #

EXPIRY = T0 + timedelta(hours=4)

CATALOGUE: list[tuple[ShadowMessageKind, dict[str, Any]]] = [
    (
        ShadowMessageKind.ALERT,
        {"body": "APPROVE BTCUSDT LONG X\nSL: 1", "detected_at_utc": T0, "expiry_utc": EXPIRY},
    ),
    *[
        (
            ShadowMessageKind.DECISION_RESULT,
            {"outcome": outcome, "detail": "OK: something", "expiry_utc": EXPIRY},
        )
        for outcome in ShadowDecisionOutcome
    ],
    (
        ShadowMessageKind.SEND_FAILURE_NOTICE,
        {"failure_kind": "RATE_LIMITED", "retry_after_seconds": 5, "signal_id": "sig-1"},
    ),
]


def test_the_catalogue_names_every_message_kind_and_every_outcome() -> None:
    assert {kind for kind, _ in CATALOGUE} == set(ShadowMessageKind)
    outcomes = {
        fields["outcome"] for kind, fields in CATALOGUE if kind is ShadowMessageKind.DECISION_RESULT
    }
    assert outcomes == set(ShadowDecisionOutcome)
    assert {o.value for o in ShadowDecisionOutcome} == {
        "APPROVED",
        "SKIPPED",
        "REPLAYED",
        "REJECTED_APPROVAL_EXPIRED",
        "REJECTED_OTHER",
    }


@pytest.mark.parametrize(("kind", "fields"), CATALOGUE)
def test_every_message_kind_carries_label_mode_and_both_time_zones(
    kind: ShadowMessageKind, fields: dict[str, Any]
) -> None:
    text = render_shadow_message(kind, mode=Mode.SHADOW, now_utc=T0, **fields)

    assert "SHADOW — no real order" in text
    assert "Mode: SHADOW" in text
    assert "2026-10-09 03:00:00 UTC (2026-10-09 10:00:00 Asia/Ho_Chi_Minh)" in text
    if "expiry_utc" in fields:
        assert "2026-10-09 07:00:00 UTC (2026-10-09 14:00:00 Asia/Ho_Chi_Minh)" in text
    assert_shadow_text(text)


@pytest.mark.parametrize("mode", [Mode.DEMO, Mode.LIVE])
def test_only_shadow_mode_is_constructible(mode: Mode) -> None:
    with pytest.raises(ValueError, match="SHADOW"):
        require_shadow(mode)
    with pytest.raises(ValueError, match="SHADOW"):
        render_shadow_message(
            ShadowMessageKind.SEND_FAILURE_NOTICE, mode=mode, now_utc=T0, failure_kind="X"
        )
    require_shadow(Mode.SHADOW)


def test_time_pair_is_utc_and_ho_chi_minh() -> None:
    assert format_time_pair(T0) == "2026-10-09 03:00:00 UTC (2026-10-09 10:00:00 Asia/Ho_Chi_Minh)"
    with pytest.raises(ValueError, match="UTC-aware"):
        format_time_pair(T0.replace(tzinfo=None))
