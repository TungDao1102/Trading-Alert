"""SHADOW CONFIRM step of D041 (Phase 16, plan 16-11, Tasks 1 and 2, D-16, L-13, REV-12).

APPROVE never confirms anything: it edits the alert into a SHADOW confirmation card with CONFIRM
and CANCEL buttons. The confirm token is separate from the approval token, single use, bound to
the approving Telegram user id and the plan hash, and expires after a TTL (60 s by default). The
only side effect of a successful CONFIRM is the injected `on_confirmed` callback; nothing here
can place an order. Every text of the chain comes from the one composer of plan 16-04. No network,
no real Telegram.
"""

from __future__ import annotations

import ast
import inspect
import json
from collections.abc import Callable
from datetime import datetime, timedelta
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
from src.domain.approval import Approval
from src.domain.enums import ApprovalResult, RejectionReason
from src.domain.trade_plan import TradePlan
from src.paper.shadow import (
    SHADOW_LABEL,
    ConfirmCardFields,
    ConfirmOutcome,
    Mode,
    ShadowApprovalBook,
    ShadowMessageKind,
    format_time_pair,
    make_shadow_reply_fn,
    render_shadow_message,
    send_shadow_alert,
)
from src.paper.shadow_confirm import (
    CONFIRM_TTL_SECONDS_DEFAULT,
    EVENT_SHADOW_CONFIRM_CANCELLED,
    EVENT_SHADOW_CONFIRM_EXPIRED,
    EVENT_SHADOW_CONFIRM_ISSUED,
    EVENT_SHADOW_CONFIRM_REJECTED,
    EVENT_SHADOW_CONFIRMED,
    ConfirmBook,
    make_confirm_callbacks,
    render_confirm_card,
)

from tests.shadow_fakes import (
    CHAT_ID,
    OTHER_CHAT_ID,
    OTHER_USER_ID,
    T0,
    USER_ID,
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
MARK = Decimal("50050")
Recheck = Callable[[Any, TradePlan, datetime], RejectionReason | None]


class Harness:
    """Stores, bot, a movable clock, both books and the callbacks wired into `on_callback`."""

    def __init__(
        self,
        *,
        ttl: int | None = None,
        mark: Decimal | None = MARK,
        recheck: Recheck | None = None,
    ) -> None:
        self.trace: list[str] = []
        self.stores = InMemoryShadowStores(self.trace)
        self.bot = FakeBot(self.trace)
        self.now = T_PRESS
        self.mark = mark
        self.sleep = RecordingSleep()
        self.confirmed: list[tuple[Approval, TradePlan, datetime]] = []
        self.book = ShadowApprovalBook(self.stores, clock=lambda: self.now)
        kwargs: dict[str, Any] = {} if ttl is None else {"ttl_seconds": ttl}
        self.confirm = ConfirmBook(
            self.stores,
            clock=lambda: self.now,
            mark_price=lambda symbol: self.mark,
            recheck=recheck,
            on_confirmed=lambda a, p, t: self.confirmed.append((a, p, t)),
            **kwargs,
        )
        self.callbacks = make_confirm_callbacks(
            approvals=self.book,
            confirm=self.confirm,
            bot=self.bot,
            mode=Mode.SHADOW,
            sleep=self.sleep,
        )
        self.reply = make_shadow_reply_fn(
            self.bot,
            mode=Mode.SHADOW,
            clock=lambda: self.now,
            book=self.book,
            confirm_book=self.confirm,
        )
        self.signal = make_shadow_signal(1)
        self.plan = make_shadow_plan(self.signal)

    async def alert(self) -> None:
        await send_shadow_alert(
            stores=self.stores,
            book=self.book,
            bot=self.bot,
            chat_id=CHAT_ID,
            mode=Mode.SHADOW,
            signal=self.signal,
            plan=self.plan,
            exposure_quote=Decimal("0"),
            reason_codes=["SETUP_DETECTED"],
            now_utc=T0,
            sleep=self.sleep,
        )

    def alert_buttons(self) -> tuple[str, str]:
        (_, apr), (_, skp) = keyboard_buttons(self.bot.sent[0].reply_markup)
        return apr, skp

    async def tap(
        self,
        data: str,
        query: str,
        *,
        chat_id: int = CHAT_ID,
        user: int | None = USER_ID,
        message_id: int = 1,
    ) -> DispatchResult:
        update = make_callback_update(
            data=data,
            chat_id=chat_id,
            query_id=query,
            from_user_id=user,
            message_id=message_id,
        )
        return await on_callback(
            update,
            cast(Any, None),
            authorized_chat_id=CHAT_ID,
            binding_context_resolver=self.book.resolve,
            dispatch=self.book.dispatch,
            reply_text_fn=self.reply,
            confirm_handler=self.callbacks.confirm_handler,
            approved_handler=self.callbacks.approved_handler,
            clock=lambda: self.now,
        )

    async def approve(self, query: str = "q-apr", *, user: int | None = USER_ID) -> str:
        """Press APPROVE and return the confirm short id taken from the card keyboard."""
        await self.alert()
        apr, _ = self.alert_buttons()
        await self.tap(apr, query, user=user)
        return apr.removeprefix("APR:")

    def events(self, event_type: str) -> list[Any]:
        return self.stores.journal_of_type(event_type)

    def terminal_events(self) -> list[Any]:
        return [
            e
            for e in self.stores.journal
            if e.event_type
            in (
                EVENT_SHADOW_CONFIRMED,
                EVENT_SHADOW_CONFIRM_CANCELLED,
                EVENT_SHADOW_CONFIRM_EXPIRED,
            )
        ]


def payload(event: Any) -> dict[str, Any]:
    loaded = json.loads(event.payload_json)
    assert isinstance(loaded, dict)
    return loaded


# --------------------------------------------------------------------------- #
# Task 1, test 1: APPROVE edits the alert into the confirmation card.
# --------------------------------------------------------------------------- #


async def test_approve_edits_the_alert_into_a_shadow_confirmation_card() -> None:
    h = Harness()

    short_id = await h.approve()

    assert len(h.bot.edited) == 1
    assert len(h.bot.sent) == 1, "the card replaces the alert; nothing else is sent"
    edit = h.bot.edited[0]
    assert (edit.chat_id, edit.message_id) == (CHAT_ID, 1)
    text = edit.text
    assert_shadow_text(text)
    assert SHADOW_LABEL in text
    assert "Mode: SHADOW" in text
    assert "Symbol: BTCUSDT" in text
    assert "Side: LONG" in text
    assert "Quantity: 0.08" in text
    assert "Notional: 4008 quote" in text  # 0.08 * 50100, the adverse edge of the entry zone
    assert "Estimated loss at SL: 48 quote" in text  # 0.08 * (50100 - 49500)
    assert "Mark price: 50050" in text
    assert "Entry (adverse edge): 50100" in text
    assert "Stop loss: 49500" in text
    # Remaining validity: the plan expiry as a UTC and a Ho Chi Minh time, plus the seconds.
    assert f"Plan expiry: {format_time_pair(h.plan.expiry_utc)} (remaining 13980 s)" in text
    assert "Confirm within 60 s" in text
    assert format_time_pair(T_PRESS + timedelta(seconds=60)) in text
    # The text is exactly the composer's output (D-12, D-35).
    assert text == render_confirm_card(
        h.signal, h.plan, mode=Mode.SHADOW, mark_price=MARK, now_utc=T_PRESS, ttl_seconds=60
    )
    assert [data for _, data in keyboard_buttons(edit.reply_markup)] == [
        f"CNF:{short_id}",
        f"CXL:{short_id}",
    ]
    assert [label for label, _ in keyboard_buttons(edit.reply_markup)] == ["CONFIRM", "CANCEL"]
    # APPROVE confirmed nothing.
    assert h.confirmed == []
    assert h.events(EVENT_SHADOW_CONFIRMED) == []
    issued = h.events(EVENT_SHADOW_CONFIRM_ISSUED)
    assert len(issued) == 1
    assert payload(issued[0])["delivery"] == "edit"
    approved = [a for a in h.stores.approvals.values() if a.status == ApprovalResult.APPROVED]
    assert len(approved) == 1


async def test_the_card_says_when_the_mark_price_is_unavailable() -> None:
    h = Harness(mark=None)

    await h.approve()

    assert "Mark price: mark price unavailable" in h.bot.edited[0].text
    assert_shadow_text(h.bot.edited[0].text)


def test_the_default_confirm_ttl_is_sixty_seconds_and_configurable() -> None:
    assert CONFIRM_TTL_SECONDS_DEFAULT == 60


# --------------------------------------------------------------------------- #
# Task 1, test 2: CNF: and CXL: parsing.
# --------------------------------------------------------------------------- #

SHORT = "0123456789abcdef0123456789abcdef"


def test_parse_accepts_confirm_and_cancel_payloads() -> None:
    confirm = parse_callback_data(f"CNF:{SHORT}")
    cancel = parse_callback_data(f"CXL:{SHORT}")

    assert (confirm.kind, confirm.short_id) == (CallbackKind.CONFIRM, SHORT)
    assert (cancel.kind, cancel.short_id) == (CallbackKind.CANCEL, SHORT)


@pytest.mark.parametrize(
    "raw",
    [
        f"CNF:{SHORT[:-1]}",  # 31 hex
        f"CXL:{SHORT}0",  # 33 hex
        f"CNF:{SHORT.upper()}",  # uppercase hex
        f"CNF:{'g' * 32}",  # not hex
        f"CFM:{SHORT}",  # unknown prefix
        f"CNF {SHORT}",
        "CNF:",
        "",
        f"CNF:{SHORT}" + "x" * 40,  # over the 64-byte ceiling
    ],
)
def test_parse_still_rejects_other_shapes(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_callback_data(raw)


@pytest.mark.parametrize(
    ("prefix", "kind"),
    [
        ("APR:", CallbackKind.APPROVE),
        ("SKP:", CallbackKind.SKIP),
        ("SIM:", CallbackKind.SIMULATE_RECORDED),
        ("SKIP:", CallbackKind.SIMULATE_RECORDED),
    ],
)
def test_existing_prefixes_parse_unchanged(prefix: str, kind: CallbackKind) -> None:
    assert parse_callback_data(f"{prefix}{SHORT}").kind is kind


# --------------------------------------------------------------------------- #
# Task 1, test 3: CNF within the TTL journals CONFIRMED and calls only on_confirmed.
# --------------------------------------------------------------------------- #


async def test_confirm_within_the_ttl_journals_confirmed_with_both_timestamps() -> None:
    h = Harness()
    short_id = await h.approve()
    h.now = T_PRESS + timedelta(seconds=10)

    result = await h.tap(f"CNF:{short_id}", "q-cnf")

    assert result.ok is True
    assert result.kind is CallbackKind.CONFIRM
    confirmed = h.events(EVENT_SHADOW_CONFIRMED)
    assert len(confirmed) == 1
    body = payload(confirmed[0])
    assert body["confirm_requested_at_utc"] == T_PRESS.isoformat()
    assert body["confirmed_at_utc"] == (T_PRESS + timedelta(seconds=10)).isoformat()
    assert body["mode"] == "SHADOW"
    assert body["approving_user_id"] == str(USER_ID)
    assert len(h.confirmed) == 1
    approval, plan, confirmed_at = h.confirmed[0]
    assert approval.status == ApprovalResult.APPROVED
    assert plan.trade_plan_id == h.plan.trade_plan_id
    assert confirmed_at == T_PRESS + timedelta(seconds=10)
    # One labelled reply for the press, rendered by the composer.
    reply = h.bot.sent[-1].text
    assert_shadow_text(reply)
    assert "Confirm: CONFIRMED" in reply


def test_the_confirm_path_receives_no_exchange_object() -> None:
    forbidden = ("adapter", "exchange", "binance", "client", "order")
    for func in (ConfirmBook.handle_confirm, ConfirmBook.handle_cancel):
        names = list(inspect.signature(func).parameters)
        assert not [n for n in names if any(word in n for word in forbidden)], names
    callbacks_names = list(inspect.signature(make_confirm_callbacks).parameters)
    assert not [n for n in callbacks_names if any(w in n for w in ("adapter", "exchange"))]


# --------------------------------------------------------------------------- #
# Task 2, test 1: single use.
# --------------------------------------------------------------------------- #


async def test_a_second_confirm_replays_the_existing_outcome() -> None:
    h = Harness()
    short_id = await h.approve()
    h.now = T_PRESS + timedelta(seconds=10)
    await h.tap(f"CNF:{short_id}", "q1")

    h.now = T_PRESS + timedelta(seconds=11)
    replay = await h.tap(f"CNF:{short_id}", "q2")

    assert replay.ok is True
    assert len(h.confirmed) == 1, "on_confirmed is called once: never a second position"
    assert len(h.events(EVENT_SHADOW_CONFIRMED)) == 1
    assert len(h.terminal_events()) == 1
    assert "Confirm: CONFIRMED" in h.bot.sent[-1].text
    assert "REPLAYED" in h.bot.sent[-1].text


async def test_the_same_delivery_twice_writes_the_same_journal_ids() -> None:
    h = Harness()
    short_id = await h.approve()
    h.now = T_PRESS + timedelta(seconds=10)
    await h.tap(f"CNF:{short_id}", "q1")
    before = [e.journal_event_id for e in h.stores.journal]

    await h.tap(f"CNF:{short_id}", "q1")  # Telegram redelivery of the same callback query

    assert [e.journal_event_id for e in h.stores.journal] == before
    assert len(h.confirmed) == 1


# --------------------------------------------------------------------------- #
# Task 2, test 2: bound to the approving user.
# --------------------------------------------------------------------------- #


async def test_a_confirm_from_another_user_is_rejected_and_journaled() -> None:
    h = Harness()
    short_id = await h.approve()
    h.now = T_PRESS + timedelta(seconds=5)

    result = await h.tap(f"CNF:{short_id}", "q-other", user=OTHER_USER_ID)

    assert result.ok is False
    assert h.confirmed == []
    rejected = h.events(EVENT_SHADOW_CONFIRM_REJECTED)
    assert len(rejected) == 1
    body = payload(rejected[0])
    assert body["reason"] == "USER_MISMATCH"
    assert body["presented_user_id"] == str(OTHER_USER_ID)
    assert h.terminal_events() == []
    assert "REJECTED_USER_MISMATCH" in h.bot.sent[-1].text
    # The token stays usable by the approving user until expiry.
    h.now = T_PRESS + timedelta(seconds=20)
    ok = await h.tap(f"CNF:{short_id}", "q-user")
    assert ok.ok is True
    assert len(h.confirmed) == 1


async def test_a_confirm_without_a_user_id_is_rejected() -> None:
    h = Harness()
    short_id = await h.approve()

    result = await h.tap(f"CNF:{short_id}", "q-nouser", user=None)

    assert result.ok is False
    assert h.confirmed == []
    assert h.terminal_events() == []


async def test_a_confirm_from_the_wrong_chat_never_reaches_the_confirm_layer() -> None:
    h = Harness()
    short_id = await h.approve()

    result = await h.tap(f"CNF:{short_id}", "q-chat", chat_id=OTHER_CHAT_ID)

    assert result.ok is False
    assert h.confirmed == []
    assert h.events(EVENT_SHADOW_CONFIRM_REJECTED) == []  # the chat gate ran first
    assert h.terminal_events() == []


# --------------------------------------------------------------------------- #
# Task 2, test 3: TTL.
# --------------------------------------------------------------------------- #


async def test_a_confirm_at_the_ttl_boundary_is_expired_and_nothing_is_simulated() -> None:
    h = Harness()
    short_id = await h.approve()
    h.now = T_PRESS + timedelta(seconds=60)  # boundary inclusive, as binding.py

    result = await h.tap(f"CNF:{short_id}", "q-late")

    assert result.ok is False
    assert h.confirmed == []
    expired = h.events(EVENT_SHADOW_CONFIRM_EXPIRED)
    assert len(expired) == 1
    assert payload(expired[0])["reason"] == "CONFIRM_TTL_ELAPSED"
    assert "EXPIRED_TTL" in h.bot.sent[-1].text
    # The token is dead for good.
    h.now = T_PRESS + timedelta(seconds=61)
    again = await h.tap(f"CNF:{short_id}", "q-later")
    assert again.ok is False
    assert h.confirmed == []
    assert len(h.terminal_events()) == 1


async def test_one_second_before_the_ttl_still_confirms() -> None:
    h = Harness()
    short_id = await h.approve()
    h.now = T_PRESS + timedelta(seconds=59)

    assert (await h.tap(f"CNF:{short_id}", "q")).ok is True
    assert len(h.confirmed) == 1


async def test_expire_due_expires_every_outstanding_token_past_the_ttl() -> None:
    h = Harness()
    await h.approve()
    assert h.confirm.expire_due(T_PRESS + timedelta(seconds=59)) == []
    assert h.terminal_events() == []

    expired = h.confirm.expire_due(T_PRESS + timedelta(seconds=60))

    assert len(expired) == 1
    assert len(h.events(EVENT_SHADOW_CONFIRM_EXPIRED)) == 1
    assert payload(h.events(EVENT_SHADOW_CONFIRM_EXPIRED)[0])["reason"] == "CONFIRM_TTL_ELAPSED"
    assert h.confirm.expire_due(T_PRESS + timedelta(seconds=120)) == []
    assert len(h.terminal_events()) == 1
    assert h.confirmed == []


# --------------------------------------------------------------------------- #
# Task 2, test 4: CANCEL.
# --------------------------------------------------------------------------- #


async def test_cancel_is_journaled_and_nothing_is_simulated() -> None:
    h = Harness()
    short_id = await h.approve()
    h.now = T_PRESS + timedelta(seconds=8)

    result = await h.tap(f"CXL:{short_id}", "q-cxl")

    assert result.ok is True
    assert result.kind is CallbackKind.CANCEL
    cancelled = h.events(EVENT_SHADOW_CONFIRM_CANCELLED)
    assert len(cancelled) == 1
    body = payload(cancelled[0])
    assert body["confirm_requested_at_utc"] == T_PRESS.isoformat()
    assert body["cancelled_at_utc"] == (T_PRESS + timedelta(seconds=8)).isoformat()
    assert h.confirmed == []
    assert "Confirm: CANCELLED" in h.bot.sent[-1].text
    # A CONFIRM after the cancel replays the cancel; it never confirms.
    h.now = T_PRESS + timedelta(seconds=9)
    late = await h.tap(f"CNF:{short_id}", "q-after")
    assert late.ok is False
    assert h.confirmed == []
    assert "CANCELLED" in h.bot.sent[-1].text
    assert len(h.terminal_events()) == 1


async def test_a_cancel_after_confirm_cannot_flip_the_outcome() -> None:
    h = Harness()
    short_id = await h.approve()
    await h.tap(f"CNF:{short_id}", "q-cnf")

    await h.tap(f"CXL:{short_id}", "q-cxl")

    assert len(h.confirmed) == 1
    assert h.events(EVENT_SHADOW_CONFIRM_CANCELLED) == []
    assert "CONFIRMED" in h.bot.sent[-1].text


# --------------------------------------------------------------------------- #
# Task 2, test 5: re-checks at confirm time.
# --------------------------------------------------------------------------- #


async def test_a_plan_past_its_expiry_is_rejected_at_confirm() -> None:
    # The confirm TTL (a generous 8 h here) outlives the plan expiry (4 h): REV-12 still wins.
    h = Harness(ttl=8 * 3600)
    short_id = await h.approve()
    h.now = h.plan.expiry_utc  # boundary inclusive

    result = await h.tap(f"CNF:{short_id}", "q-exp")

    assert result.ok is False
    assert h.confirmed == []
    expired = h.events(EVENT_SHADOW_CONFIRM_EXPIRED)
    assert len(expired) == 1
    assert payload(expired[0])["reason"] == RejectionReason.APPROVAL_EXPIRED.value
    assert "REJECTED_PLAN_EXPIRED" in h.bot.sent[-1].text


async def test_an_injected_recheck_can_reject_the_confirm_and_its_reason_is_journaled() -> None:
    seen: list[tuple[str, datetime]] = []

    def recheck(signal: Any, plan: TradePlan, now_utc: datetime) -> RejectionReason | None:
        seen.append((plan.trade_plan_id, now_utc))
        return RejectionReason.INVALIDATED

    h = Harness(recheck=recheck)
    short_id = await h.approve()
    h.now = T_PRESS + timedelta(seconds=3)

    result = await h.tap(f"CNF:{short_id}", "q-rc")

    assert result.ok is False
    assert h.confirmed == []
    assert seen == [(h.plan.trade_plan_id, T_PRESS + timedelta(seconds=3))]
    expired = h.events(EVENT_SHADOW_CONFIRM_EXPIRED)
    assert len(expired) == 1
    assert payload(expired[0])["reason"] == RejectionReason.INVALIDATED.value
    assert "REJECTED_OTHER" in h.bot.sent[-1].text


async def test_a_recheck_that_passes_lets_the_confirm_through() -> None:
    h = Harness(recheck=lambda signal, plan, now_utc: None)
    short_id = await h.approve()

    assert (await h.tap(f"CNF:{short_id}", "q")).ok is True
    assert len(h.confirmed) == 1


# --------------------------------------------------------------------------- #
# Task 2, test 6: the TTL is configurable.
# --------------------------------------------------------------------------- #


async def test_the_ttl_is_configurable_through_the_constructor() -> None:
    h = Harness(ttl=15)
    short_id = await h.approve()
    assert "Confirm within 15 s" in h.bot.edited[0].text
    h.now = T_PRESS + timedelta(seconds=15)

    assert (await h.tap(f"CNF:{short_id}", "q")).ok is False
    assert h.confirmed == []


@pytest.mark.parametrize("ttl", [0, -1, -60])
def test_a_non_positive_ttl_raises(ttl: int) -> None:
    with pytest.raises(ValueError, match="ttl"):
        ConfirmBook(InMemoryShadowStores(), clock=lambda: T0, ttl_seconds=ttl)


# --------------------------------------------------------------------------- #
# Restart: raw confirm tokens do not survive it.
# --------------------------------------------------------------------------- #


async def test_a_restart_expires_outstanding_confirms_and_rejects_a_later_press() -> None:
    h = Harness()
    short_id = await h.approve()
    # A new process: the stores survive, the raw confirm tokens do not.
    fresh = ConfirmBook(h.stores, clock=lambda: h.now, on_confirmed=lambda a, p, t: None)

    expired = fresh.expire_on_restart(T_PRESS + timedelta(seconds=5))

    assert len(expired) == 1
    rows = h.events(EVENT_SHADOW_CONFIRM_EXPIRED)
    assert len(rows) == 1
    assert payload(rows[0])["reason"] == "RUNTIME_RESTART"
    assert fresh.expire_on_restart(T_PRESS + timedelta(seconds=6)) == []
    assert len(h.terminal_events()) == 1
    h.confirm = fresh
    h.callbacks = make_confirm_callbacks(
        approvals=h.book, confirm=fresh, bot=h.bot, mode=Mode.SHADOW, sleep=h.sleep
    )
    h.reply = make_shadow_reply_fn(
        h.bot, mode=Mode.SHADOW, clock=lambda: h.now, book=h.book, confirm_book=fresh
    )

    result = await h.tap(f"CNF:{short_id}", "q-after-restart")

    assert result.ok is False
    assert h.confirmed == []


# --------------------------------------------------------------------------- #
# Task 2, test 7: the message catalogue of the confirm chain (D-12, D-35).
# --------------------------------------------------------------------------- #

EXPIRY = T0 + timedelta(hours=4)
CARD = ConfirmCardFields(
    symbol="BTCUSDT",
    side="LONG",
    quantity=Decimal("0.08"),
    entry_ref=Decimal("50100"),
    stop_loss=Decimal("49500"),
    notional=Decimal("4008"),
    estimated_loss=Decimal("48"),
    mark_price=Decimal("50050"),
    plan_expiry_utc=EXPIRY,
    plan_remaining_seconds=int((EXPIRY - T0).total_seconds()),
    confirm_ttl_seconds=60,
    confirm_until_utc=T0 + timedelta(seconds=60),
)

CONFIRM_CATALOGUE: list[tuple[ShadowMessageKind, dict[str, Any]]] = [
    (ShadowMessageKind.CONFIRM_CARD, {"card": CARD}),
    *[
        (
            ShadowMessageKind.CONFIRM_RESULT,
            {
                "confirm_outcome": outcome,
                "confirm_requested_at_utc": T0 - timedelta(seconds=10),
                "expiry_utc": EXPIRY,
                "detail": "reason",
            },
        )
        for outcome in ConfirmOutcome
    ],
    (
        ShadowMessageKind.CARD_DELIVERY_FAILED,
        {"failure_kind": "TRANSIENT", "signal_id": "sig-1", "expiry_utc": EXPIRY},
    ),
]


def test_the_catalogue_covers_every_confirm_message_kind_and_outcome() -> None:
    confirm_kinds = {
        ShadowMessageKind.CONFIRM_CARD,
        ShadowMessageKind.CONFIRM_RESULT,
        ShadowMessageKind.CARD_DELIVERY_FAILED,
    }
    assert {kind for kind, _ in CONFIRM_CATALOGUE} == confirm_kinds
    outcomes = {
        fields["confirm_outcome"]
        for kind, fields in CONFIRM_CATALOGUE
        if kind is ShadowMessageKind.CONFIRM_RESULT
    }
    assert outcomes == set(ConfirmOutcome)
    assert {o.value for o in ConfirmOutcome} == {
        "CONFIRMED",
        "CANCELLED",
        "EXPIRED_TTL",
        "REJECTED_PLAN_EXPIRED",
        "REJECTED_USER_MISMATCH",
        "REJECTED_OTHER",
    }
    # Plan 16-04's catalogue and this one together name every ShadowMessageKind.
    from tests.test_paper_shadow_messages import CATALOGUE

    named = {kind for kind, _ in CATALOGUE} | {kind for kind, _ in CONFIRM_CATALOGUE}
    assert named == set(ShadowMessageKind)


@pytest.mark.parametrize(("kind", "fields"), CONFIRM_CATALOGUE)
def test_every_confirm_message_carries_label_mode_and_both_time_zones(
    kind: ShadowMessageKind, fields: dict[str, Any]
) -> None:
    text = render_shadow_message(kind, mode=Mode.SHADOW, now_utc=T0, **fields)

    assert "SHADOW — no real order" in text
    assert "Mode: SHADOW" in text
    assert "2026-10-09 03:00:00 UTC (2026-10-09 10:00:00 Asia/Ho_Chi_Minh)" in text
    assert "2026-10-09 07:00:00 UTC (2026-10-09 14:00:00 Asia/Ho_Chi_Minh)" in text  # plan expiry
    assert_shadow_text(text)
    if kind is ShadowMessageKind.CONFIRM_CARD:
        assert "(remaining 14400 s)" in text


async def test_every_reply_of_the_confirm_chain_passes_the_fake_bot_guard() -> None:
    """The fake bot asserts label, mode and both zones on every call; any miss fails here."""
    h = Harness()
    short_id = await h.approve("a1")
    h.now = T_PRESS + timedelta(seconds=5)
    await h.tap(f"CNF:{short_id}", "c1", user=OTHER_USER_ID)  # REJECTED_USER_MISMATCH
    await h.tap(f"CNF:{short_id}", "c2")  # CONFIRMED
    await h.tap(f"CNF:{short_id}", "c3")  # replay
    await h.tap(f"CXL:{short_id}", "c4")  # replay of the confirm

    texts = [m.text for m in h.bot.sent] + [m.text for m in h.bot.edited]
    assert len(texts) >= 5
    for text in texts:
        assert_shadow_text(text)


def test_a_non_shadow_mode_cannot_render_a_confirm_message() -> None:
    for kind, fields in CONFIRM_CATALOGUE:
        with pytest.raises(ValueError, match="SHADOW"):
            render_shadow_message(kind, mode=Mode.LIVE, now_utc=T0, **fields)


# --------------------------------------------------------------------------- #
# The module never reaches an exchange (T-16-28).
# --------------------------------------------------------------------------- #

FORBIDDEN_IMPORT_PREFIXES = (
    "src.execution",
    "src.adapters.binance_usdm",
    "src.adapters.binance_public",
    "binance",
    "telegram",
)


def test_the_confirm_module_imports_no_exchange_adapter_and_no_execution() -> None:
    source = Path(inspect.getsourcefile(ConfirmBook) or "").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)
    assert imported, "the module should import something"
    bad = [m for m in imported if m.startswith(FORBIDDEN_IMPORT_PREFIXES)]
    assert bad == [], f"forbidden imports in shadow_confirm.py: {bad}"
