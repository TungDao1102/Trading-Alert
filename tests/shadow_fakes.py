"""In-memory fakes for the SHADOW approval front half (Phase 16, plan 16-04, D-12, D-16, D-35).

Reused by plans 16-11, 16-31, 16-35, 16-38 and 16-39. No network is touched and no real
Telegram bot is constructed.

`InMemoryShadowStores` implements the `ShadowStores` port with the behaviour of the Phase 17
PostgreSQL stores that matters to the SHADOW layer: parents must exist before children
(`ParentRowMissing`), a decision is conditional on PENDING and only ONE approval of a plan may be
decided (`uq_approvals_one_decided_per_plan`, `ApprovalAlreadyDecided`), and the short-id mapping
refuses to rebind.

`FakeBot` records `send_message` / `edit_message_text` calls and runs `assert_shadow_text` on every
text BEFORE recording it (and before raising a queued error), so any SHADOW text that leaves
without the exact label, the mode or both time zones fails the test that sent it. The label
literal is deliberately repeated here instead of imported: the check must not move with the
constant it guards.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from src.approval.mapping import ShortIdMapping
from src.approval.replay import ApprovalAlreadyDecided
from src.domain.approval import Approval
from src.domain.enums import ApprovalAction, ApprovalResult, SignalStatus, TradePlanStatus
from src.domain.journal import JournalEvent
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.persistence.errors import ParentRowMissing, RowConflict

EXPECTED_LABEL = "SHADOW — no real order"

T0 = datetime(2026, 10, 9, 3, 0, 0, tzinfo=UTC)
CHAT_ID = 4242
OTHER_CHAT_ID = 9999

_STAMP = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
_PAIR = re.compile(rf"({_STAMP}) UTC \(({_STAMP}) Asia/Ho_Chi_Minh\)")
_UTC_STAMP = re.compile(rf"{_STAMP} UTC")
_FORMAT = "%Y-%m-%d %H:%M:%S"


def assert_shadow_text(text: str) -> None:
    """Fail unless `text` carries the label, the mode and every time in both zones."""
    assert EXPECTED_LABEL in text, f"SHADOW label missing: {text!r}"
    assert "Mode: SHADOW" in text, f"mode missing: {text!r}"
    pairs = _PAIR.findall(text)
    assert pairs, f"no UTC + Asia/Ho_Chi_Minh time pair: {text!r}"
    assert len(_UTC_STAMP.findall(text)) == len(pairs), f"a UTC time without its pair: {text!r}"
    assert text.count("Asia/Ho_Chi_Minh") == len(pairs), f"a lone Ho Chi Minh time: {text!r}"
    for utc_text, local_text in pairs:
        utc = datetime.strptime(utc_text, _FORMAT)
        local = datetime.strptime(local_text, _FORMAT)
        assert local - utc == timedelta(hours=7), f"not UTC+7: {utc_text} / {local_text}"


# --------------------------------------------------------------------------- #
# Domain fixtures.
# --------------------------------------------------------------------------- #


def make_shadow_signal(n: int = 1, **overrides: Any) -> Signal:
    values: dict[str, Any] = {
        "signal_id": f"{0xA000 + n:x}".rjust(64, "0"),
        "strategy_id": "trend-pullback",
        "strategy_version": "v1.0.0",
        "parameter_set_id": "baseline-v1",
        "parameter_set_hash": "b" * 64,
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "setup_type": "TREND_PULLBACK_LONG",
        "source_timeframe": "1h",
        "source_candle_close_utc": T0 - timedelta(minutes=1),
        "detected_at_utc": T0,
        "status": SignalStatus.DETECTED,
        "expires_at_utc": T0 + timedelta(hours=4),
    }
    values.update(overrides)
    return Signal(**values)


def make_shadow_plan(signal: Signal, **overrides: Any) -> TradePlan:
    values: dict[str, Any] = {
        "trade_plan_id": f"{int(signal.signal_id, 16) + 0x1000:x}".rjust(64, "0"),
        "signal_id": signal.signal_id,
        "trade_plan_version": "v1.0.0",
        "entry_model": "LIMIT_ZONE",
        "entry_min_price": Decimal("50000"),
        "entry_max_price": Decimal("50100"),
        "stop_loss_price": Decimal("49500"),
        "take_profit_json": (
            '{"tp1":"51000","tp1_role":"TAKE_PROFIT_1","tp2":"52000","tp2_role":"TAKE_PROFIT_2"}'
        ),
        "invalidation_rule_json": (
            '{"basis":"CANDLE_CLOSE","break_distance_atr":"10","level":"49500"}'
        ),
        "expiry_utc": T0 + timedelta(hours=4),
        "expected_rr_json": '{"tp1_rr":"2","tp2_rr":"4"}',
        "risk_rate": Decimal("0.005"),
        "risk_budget": Decimal("4"),
        "suggested_quantity": Decimal("0.08"),
        "quantity_before_rounding": Decimal("0.08"),
        "quantity_after_rounding": Decimal("0.08"),
        "quantization_decision": "ACCEPTED",
        "plan_hash": "d" * 64,
        "status": TradePlanStatus.READY,
        "created_at_utc": T0,
    }
    values.update(overrides)
    return TradePlan(**values)


# --------------------------------------------------------------------------- #
# Stores.
# --------------------------------------------------------------------------- #


class InMemoryShadowStores:
    """The `ShadowStores` port over dicts, with PostgreSQL's parent and decision rules."""

    def __init__(self, trace: list[str] | None = None) -> None:
        self.trace: list[str] = trace if trace is not None else []
        self.signals: dict[str, Signal] = {}
        self.plans: dict[str, TradePlan] = {}
        self.approvals: dict[str, Approval] = {}
        self.mappings: dict[str, ShortIdMapping] = {}
        self.journal: list[JournalEvent] = []

    # ---- writers ------------------------------------------------------- #

    def insert_signal(self, signal: Signal) -> None:
        self.trace.append("insert_signal")
        self.signals.setdefault(signal.signal_id, signal)

    def insert_trade_plan(self, plan: TradePlan) -> None:
        self.trace.append("insert_trade_plan")
        if plan.signal_id not in self.signals:
            raise ParentRowMissing(f"trade plan {plan.trade_plan_id}: signal missing")
        self.plans.setdefault(plan.trade_plan_id, plan)

    def insert_pending(self, approval: Approval) -> None:
        self.trace.append("insert_pending")
        if approval.status != ApprovalResult.PENDING:
            raise ValueError("insert_pending requires a PENDING approval")
        if approval.signal_id not in self.signals or approval.trade_plan_id not in self.plans:
            raise ParentRowMissing(f"approval {approval.approval_id}: parent row missing")
        self.approvals.setdefault(approval.approval_id, approval)

    def record_short_id_mapping(self, mapping: ShortIdMapping) -> None:
        self.trace.append("record_short_id_mapping")
        if mapping.trade_plan_id not in self.plans:
            raise ParentRowMissing(f"mapping {mapping.short_id}: trade plan missing")
        self._put_mapping(mapping)

    def save_atomic(self, approval: Approval, mapping: ShortIdMapping | None) -> None:
        self.trace.append("save_atomic")
        if approval.status == ApprovalResult.PENDING:
            raise ValueError("save_atomic requires a decided approval")
        current = self.approvals.get(approval.approval_id)
        if current is None:
            raise RowConflict(f"approval {approval.approval_id}: row does not exist")
        if current.status != ApprovalResult.PENDING:
            raise ApprovalAlreadyDecided(current)
        for other in self.approvals.values():
            if other.trade_plan_id == approval.trade_plan_id and (
                other.status != ApprovalResult.PENDING
            ):
                raise ApprovalAlreadyDecided(other)
        self.approvals[approval.approval_id] = approval
        if mapping is not None:
            self._put_mapping(mapping)

    def record_journal(self, event: JournalEvent) -> None:
        self.trace.append(f"journal:{event.event_type}")
        if event.signal_id is not None and event.signal_id not in self.signals:
            raise ParentRowMissing(f"journal {event.journal_event_id}: signal missing")
        if event.trade_plan_id is not None and event.trade_plan_id not in self.plans:
            raise ParentRowMissing(f"journal {event.journal_event_id}: trade plan missing")
        if event.approval_id is not None and event.approval_id not in self.approvals:
            raise ParentRowMissing(f"journal {event.journal_event_id}: approval missing")
        for stored in self.journal:
            if stored.journal_event_id == event.journal_event_id:
                return
        self.journal.append(event)

    # ---- readers ------------------------------------------------------- #

    def lookup_by_token_hash(self, token_hash: str) -> Approval | None:
        for approval in self.approvals.values():
            if approval.approval_token_hash == token_hash:
                return approval
        return None

    def lookup_by_short_id(self, short_id: str) -> tuple[str, str] | None:
        mapping = self.mappings.get(short_id)
        return None if mapping is None else (mapping.signal_id, mapping.trade_plan_id)

    def list_pending_approvals(self) -> list[Approval]:
        return [a for a in self.approvals.values() if a.status == ApprovalResult.PENDING]

    def list_approved_approvals(self) -> list[Approval]:
        """APPROVE-action approvals that reached APPROVED (the confirm layer's sweep input)."""
        return [
            a
            for a in self.approvals.values()
            if a.status == ApprovalResult.APPROVED and a.action == ApprovalAction.APPROVE
        ]

    def journal_for_correlation(self, correlation_id: str) -> list[JournalEvent]:
        return [event for event in self.journal if event.correlation_id == correlation_id]

    # ---- helpers ------------------------------------------------------- #

    def _put_mapping(self, mapping: ShortIdMapping) -> None:
        stored = self.mappings.get(mapping.short_id)
        if stored is None:
            self.mappings[mapping.short_id] = mapping
            return
        if (stored.signal_id, stored.trade_plan_id) != (mapping.signal_id, mapping.trade_plan_id):
            raise RowConflict(f"short id {mapping.short_id} would be rebound")

    def journal_payloads(self) -> list[str]:
        return [event.payload_json for event in self.journal]

    def journal_of_type(self, event_type: str) -> list[JournalEvent]:
        return [event for event in self.journal if event.event_type == event_type]


# --------------------------------------------------------------------------- #
# Bot.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SentMessage:
    chat_id: int | str
    text: str
    reply_markup: Any
    message_id: int | None = None


_LIVE_MODES = frozenset({"DEMO", "LIVE"})


def assert_live_text(text: str, mode: str) -> None:
    """Fail unless a DEMO or LIVE `text` names its mode and shows every time as UTC only.

    The Phase 23 DEMO/LIVE messages (plans 23-11, 23-12) carry `Mode: <mode>`, never the SHADOW
    label, and show times in UTC with no Asia/Ho_Chi_Minh display pair (D-18).
    """
    assert mode in _LIVE_MODES, f"unknown live mode: {mode!r}"
    assert f"Mode: {mode}" in text, f"mode missing: {text!r}"
    assert "Asia/Ho_Chi_Minh" not in text, f"a Ho Chi Minh time in a {mode} text: {text!r}"
    for match in re.finditer(_STAMP, text):
        assert text[match.end() : match.end() + 4] == " UTC", f"a time without UTC: {text!r}"


class FakeBot:
    """Records sends and edits; raises queued exceptions (real `telegram.error` ones).

    `text_check` runs on every text BEFORE it is recorded (and before a queued error is raised);
    the default is the SHADOW check. `FakeBot.for_mode("DEMO")` checks the DEMO/LIVE rules.
    `edit_message_reply_markup` records into `markup_edits` only (not `trace`, not `edited`) and
    has its own error queue, so a SHADOW test sees the same recording as before.
    """

    def __init__(
        self,
        trace: list[str] | None = None,
        *,
        text_check: Callable[[str], None] = assert_shadow_text,
    ) -> None:
        self.trace: list[str] = trace if trace is not None else []
        self.sent: list[SentMessage] = []
        self.edited: list[SentMessage] = []
        self.markup_edits: list[SentMessage] = []
        self.send_attempts = 0
        self._errors: list[BaseException] = []
        self._markup_errors: list[BaseException] = []
        self._text_check = text_check

    @classmethod
    def for_mode(cls, mode: str, trace: list[str] | None = None) -> FakeBot:
        """A bot that checks texts with `assert_live_text` for DEMO or LIVE."""
        return cls(trace, text_check=lambda text: assert_live_text(text, mode))

    def queue_error(self, exc: BaseException) -> None:
        self._errors.append(exc)

    def queue_markup_error(self, exc: BaseException) -> None:
        self._markup_errors.append(exc)

    async def edit_message_reply_markup(
        self, *, chat_id: int | str, message_id: int, reply_markup: Any = None
    ) -> object:
        if self._markup_errors:
            raise self._markup_errors.pop(0)
        self.markup_edits.append(SentMessage(chat_id, "", reply_markup, message_id))
        return SimpleNamespace(message_id=message_id)

    async def send_message(
        self, *, chat_id: int | str, text: str, reply_markup: Any = None
    ) -> object:
        self._text_check(text)
        self.send_attempts += 1
        self.trace.append("send")
        if self._errors:
            raise self._errors.pop(0)
        message_id = len(self.sent) + 1
        self.sent.append(SentMessage(chat_id, text, reply_markup, message_id))
        return SimpleNamespace(message_id=message_id)

    async def edit_message_text(
        self, *, chat_id: int | str, message_id: int, text: str, reply_markup: Any = None
    ) -> object:
        self._text_check(text)
        self.trace.append("edit")
        if self._errors:
            raise self._errors.pop(0)
        self.edited.append(SentMessage(chat_id, text, reply_markup, message_id))
        return SimpleNamespace(message_id=message_id)


def keyboard_buttons(markup: Any) -> list[tuple[str, str]]:
    """Flatten an inline keyboard to `(label, callback_data)` pairs."""
    return [(button.text, button.callback_data) for row in markup.inline_keyboard for button in row]


class RecordingSleep:
    """An injectable sleep that records the requested seconds and never waits."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


USER_ID = 777001
OTHER_USER_ID = 777002
STRANGER_USER_ID = 777003
# The test allow-list of `on_callback`. OTHER_USER_ID is a second allowed operator, so the confirm
# layer's "another user" tests keep their meaning (the confirm stays bound to the approving user).
# The refusal of an unlisted user is tested with STRANGER_USER_ID (Phase 23, D-02).
AUTHORIZED_USER_IDS: frozenset[int] = frozenset({USER_ID, OTHER_USER_ID})


def make_callback_update(
    *,
    data: str,
    chat_id: int,
    query_id: str,
    message_chat_id: int = CHAT_ID,
    from_user_id: int | None = USER_ID,
    message_id: int | None = 1,
    answer: Any = None,
    chat_type: str | None = "private",
) -> Any:
    """A PTB-shaped update for `on_callback`: a callback query with an awaitable `answer`.

    `answer` replaces the default no-op `query.answer` (a test passes a recording or failing
    coroutine function). `from_user_id=None` models a press without a user. `chat_type` is the
    Telegram chat type of `effective_chat` (`"private"`, `"group"`, ...).
    """

    async def _answer(*args: Any, **kwargs: Any) -> None:
        return None

    query = SimpleNamespace(
        id=query_id,
        data=data,
        answer=_answer if answer is None else answer,
        message=SimpleNamespace(chat_id=message_chat_id, message_id=message_id),
        from_user=None if from_user_id is None else SimpleNamespace(id=from_user_id),
    )
    return SimpleNamespace(
        callback_query=query, effective_chat=SimpleNamespace(id=chat_id, type=chat_type)
    )
