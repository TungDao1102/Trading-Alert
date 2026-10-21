"""Phase 8 Nyquist audit — behavioral proof for the 34 review fixes.

Each test below targets one finding from
`.planning/phases/08-approval-reconciliation-hardening/08-REVIEW.md`
(CR-01..CR-03, WR-01..WR-31) as fixed in `08-REVIEW-FIX.md`.

Stance: every fix is assumed uncovered until a passing test proves the
fixed behavior holds. Tests exercise observable behavior (transitions,
verdicts, divergences, sweeps, journal rows, rejections) — never
implementation structure.
"""

from __future__ import annotations

import inspect
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from src.adapters.telegram_callbacks import (
    EVENT_TYPE_CALLBACK_RECEIVED,
    EVENT_TYPE_CALLBACK_REJECTED,
    EVENT_TYPE_CALLBACK_RESOLVED,
    CallbackKind,
    DispatchResult,
    ParsedCallback,
    dispatch_callback,
    on_callback,
)
from src.approval.binding import ApprovalRejected, Callback
from src.approval.mapping import derive_short_id
from src.approval.replay import resolve_callback
from src.approval.tokens import issue_one_time_token, token_hash_of
from src.domain.approval import Approval
from src.domain.enums import (
    ApprovalAction,
    ApprovalResult,
    OrderRole,
    OrderStatus,
    RejectionReason,
)
from src.execution.order_ids import derive_algo_client_id, derive_client_order_id
from src.ops.drills import (
    DrillDeclaration,
    DrillLog,
    make_api_down_drill,
    make_db_failure_drill,
    make_manual_close_drill,
    make_restore_drill,
    run_drill,
)
from src.reconcile.compare import (
    DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE,
    DIVERGENCE_KIND_ORPHAN_PROTECTIVE,
    DIVERGENCE_KIND_UNSYNCED_ALGO,
    DIVERGENCE_KIND_UNSYNCED_NORMAL,
    CompareDiff,
    OrphanProtective,
    compare,
)
from src.reconcile.safe_mode import ExitReadiness, SafeModeController, SafeModeVerdict
from src.reconcile.sweeper import OrphanSweeper

# --------------------------------------------------------------------------- #
# Shared fixtures / helpers.
# --------------------------------------------------------------------------- #

NOW = datetime(2026, 9, 19, 13, 0, tzinfo=UTC)
EXPIRY = datetime(2026, 9, 19, 14, 0, tzinfo=UTC)
PLAN_HASH = "0" * 64
PARAM_HASH = "1" * 64
CHAT_ID = 123


def _make_pending_approval(
    *,
    action: ApprovalAction = ApprovalAction.APPROVE,
    raw_token: str,
    plan_hash: str = PLAN_HASH,
) -> Approval:
    return Approval(
        approval_id="appr_audit_0000000000000000000000000000000000000000",
        trade_plan_id="tp_audit_0000000000000000000000000000000000000000",
        signal_id="sig_audit_00000000000000000000000000000000000000000",
        action=action,
        result=ApprovalResult.PENDING,
        status=ApprovalResult.PENDING,
        approval_token_hash=token_hash_of(raw_token),
        requested_at_utc=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
        acted_at_utc=None,
        actor_id="",
        telegram_message_id=None,
        request_hash=plan_hash,
    )


def _binding_context(*, plan_hash: str = PLAN_HASH, expiry: datetime = EXPIRY) -> dict[str, Any]:
    return {
        "plan_hash": plan_hash,
        "strategy_version": "v1.0.0",
        "parameter_set_id": "ps-1",
        "parameter_set_hash": PARAM_HASH,
        "expiry_utc": expiry,
    }


def _callback(raw_token: str, *, action: ApprovalAction | None = None) -> Callback:
    return Callback(
        raw_token=raw_token,
        chat_id=CHAT_ID,
        plan_hash=PLAN_HASH,
        strategy_version="v1.0.0",
        parameter_set_id="ps-1",
        parameter_set_hash=PARAM_HASH,
        callback_at_utc=NOW,
        action=action,
    )


def _replay_kwargs(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "authorized_chat_id": CHAT_ID,
        "expiry_utc": EXPIRY,
        "approval_strategy_version": "v1.0.0",
        "approval_parameter_set_id": "ps-1",
        "approval_parameter_set_hash": PARAM_HASH,
        "now_utc": NOW,
    }
    base.update(over)
    return base


class _Store:
    """In-memory token-hash -> Approval store with a call-counted save."""

    def __init__(self, approval: Approval, token_hash: str) -> None:
        self._lock = threading.Lock()
        self._rows = {token_hash: approval}
        self.save_calls = 0

    def lookup(self, token_hash: str) -> Approval | None:
        with self._lock:
            return self._rows.get(token_hash)

    def save(self, approval: Approval) -> None:
        with self._lock:
            self.save_calls += 1
            self._rows[approval.approval_token_hash] = approval


class _FakeJournal:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def record(self, event: Any) -> None:
        self.events.append(event)


def _event_types(journal: _FakeJournal) -> list[str]:
    return [e.event_type for e in journal.events]


class _FakeSafeAdapter:
    def __init__(
        self,
        *,
        normal: tuple = (),
        algos: tuple = (),
        positions: tuple = (),
    ) -> None:
        self.normal = list(normal)
        self.algos = list(algos)
        self.positions = list(positions)

    async def snapshot_open_normal_orders(self, *, symbol: str | None = None) -> list[Any]:
        return list(self.normal)

    async def snapshot_open_algo_orders(self, *, symbol: str | None = None) -> list[Any]:
        return list(self.algos)

    async def snapshot_positions(self, *, symbol: str | None = None) -> list[Any]:
        return list(self.positions)


class _FakeSweepAdapter:
    def __init__(self, *, found: bool = True, cancel_exc: BaseException | None = None) -> None:
        self.found = found
        self.cancel_exc = cancel_exc
        self.cancels: list[tuple[str, str]] = []
        self._queries: dict[str, int] = {}

    async def query_algo_order_by_client(self, *, client_algo_id: str) -> Any:
        # Plan 20-11 (D-17): the sweeper queries once before the cancel (the orphan is still
        # there) and once after it (the cancel is verified). The first answer is the old
        # fixture value; every later one shows the order canceled, as a healthy exchange does.
        n = self._queries.get(client_algo_id, 0) + 1
        self._queries[client_algo_id] = n
        status = "WORKING" if n == 1 else "CANCELED"
        return SimpleNamespace(found=self.found, algo_status=status, update_time_utc=NOW)

    async def cancel_algo_order(self, *, symbol: str, client_algo_id: str) -> None:
        self.cancels.append((symbol, client_algo_id))
        if self.cancel_exc is not None:
            raise self.cancel_exc


def _orphan_diff(symbol: str = "BTCUSDT", algo_id: str = "algo-orphan-1") -> CompareDiff:
    return CompareDiff(
        agreement=False,
        divergences=(),
        orphan_protectives=(
            OrphanProtective(
                symbol=symbol,
                client_algo_id=algo_id,
                order_role=OrderRole.STOP_LOSS.value,
            ),
        ),
    )


def _valid_approve_kwargs() -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "setup": "BREAKOUT_RETEST",
        "entry_min": Decimal("60000"),
        "entry_max": Decimal("60500"),
        "stop_loss": Decimal("59000"),
        "take_profits": [(Decimal("62000"), Decimal("0.5"))],
        "rr": Decimal("2"),
        "risk_pct": Decimal("1"),
        "expiry_utc": EXPIRY,
        "invalidation": "Close below 59000 invalidates",
        "exposure_quote": Decimal("100"),
        "reason_codes": ["RSI_DIV"],
        "signal_id": "sig_audit",
        "detected_at_utc": datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
        "approved_quantity": Decimal("0.01"),
    }


# --------------------------------------------------------------------------- #
# CR-01: the pressed button determines the outcome.
# --------------------------------------------------------------------------- #


def test_cr01_replay_skip_button_on_approve_plan_fails_closed() -> None:
    """A SKIP press on an APPROVE-action plan must NOT approve it."""
    raw = issue_one_time_token()
    token_hash = token_hash_of(raw)
    store = _Store(_make_pending_approval(raw_token=raw), token_hash)

    with pytest.raises(ApprovalRejected) as exc_info:
        resolve_callback(
            _callback(raw, action=ApprovalAction.SKIP_USER),
            store.lookup,
            store.save,
            **_replay_kwargs(),
        )
    assert exc_info.value.reason_code == RejectionReason.INVALIDATED
    assert store.save_calls == 0
    row = store.lookup(token_hash)
    assert row is not None
    assert row.status == ApprovalResult.PENDING


def test_cr01_replay_matching_skip_action_transitions_to_skipped() -> None:
    """A SKIP press on a SKIP-action plan transitions to SKIPPED."""
    raw = issue_one_time_token()
    token_hash = token_hash_of(raw)
    store = _Store(
        _make_pending_approval(action=ApprovalAction.SKIP_USER, raw_token=raw),
        token_hash,
    )

    result = resolve_callback(
        _callback(raw, action=ApprovalAction.SKIP_USER),
        store.lookup,
        store.save,
        **_replay_kwargs(),
    )
    assert result.status == ApprovalResult.SKIPPED
    assert result.result == ApprovalResult.SKIPPED
    assert result.acted_at_utc is not None
    assert store.save_calls == 1


def test_cr01_dispatch_skip_press_does_not_approve() -> None:
    """End-to-end: SKP callback against an APPROVE plan is INVALIDATED."""
    raw = issue_one_time_token()
    token_hash = token_hash_of(raw)
    store = _Store(_make_pending_approval(raw_token=raw), token_hash)
    signal_id = "sig_cr01_" + "0" * 55
    short_id = derive_short_id(signal_id)
    journal = _FakeJournal()
    saved: list[Any] = []

    result = dispatch_callback(
        ParsedCallback(raw="SKP:" + short_id, kind=CallbackKind.SKIP, short_id=short_id),
        callback_chat_id=CHAT_ID,
        authorized_chat_id=CHAT_ID,
        callback_at_utc=NOW,
        raw_token=raw,
        correlation_id="cb:cr01",
        journal_receipt=journal.record,
        lookup_by_short_id=lambda sid: (signal_id, "tp_cr01"),
        lookup_by_token_hash=store.lookup,
        save_atomic=lambda approval, mapping: saved.append(approval),
        now_utc=NOW,
        binding_context=_binding_context(),
    )
    # The mapping short-id check fires first here (signal differs), but the
    # outcome must still be a fail-closed INVALIDATED with no state change.
    assert result.ok is False
    assert result.reason_code == RejectionReason.INVALIDATED
    assert saved == []
    row = store.lookup(token_hash)
    assert row is not None
    assert row.status == ApprovalResult.PENDING


# --------------------------------------------------------------------------- #
# CR-02: guard_new_entries PASS path.
# --------------------------------------------------------------------------- #


def test_cr02_guard_outside_safe_mode_passes_without_raise() -> None:
    """The guard on the normal-operation path returns a PASS verdict."""
    controller = SafeModeController(adapter=_FakeSafeAdapter(), journal=_FakeJournal())
    assert controller.in_safe_mode is False
    verdict = controller.guard_new_entries(trade_plan=None)
    assert verdict.is_no_trade is False
    assert verdict.reason_code is None


def test_cr02_verdict_pass_shape_cannot_be_confused_with_reject() -> None:
    """PASS carries no reason; a block carries RECONCILIATION_REQUIRED."""
    assert SafeModeVerdict(is_no_trade=False, reason_code=None).is_no_trade is False
    controller = SafeModeController(adapter=_FakeSafeAdapter(), journal=_FakeJournal())
    controller.enter_safe_mode(reason="DIVERGENCE", now_utc=NOW)
    blocked = controller.guard_new_entries(trade_plan=None)
    assert blocked.is_no_trade is True
    assert blocked.reason_code == RejectionReason.RECONCILIATION_REQUIRED.value


# --------------------------------------------------------------------------- #
# CR-03: naked local position diverges.
# --------------------------------------------------------------------------- #


def test_cr03_naked_local_position_diverges() -> None:
    """A filled ENTRY leaves a bare position: must NOT read as clean."""
    local_positions = [
        {
            "symbol": "BTCUSDT",
            "position_side": "LONG",
            "position_amt": Decimal("0.5"),
        }
    ]
    truth_positions = [
        SimpleNamespace(
            symbol="BTCUSDT",
            position_side="LONG",
            position_amt=Decimal("0.5"),
        )
    ]
    diff = compare(
        local_open_orders=[],
        local_open_algos=[],
        local_open_positions=local_positions,
        truth_normal_orders=[],
        truth_algo_orders=[],
        truth_positions=truth_positions,
    )
    assert diff.agreement is False
    kinds = {d.kind for d in diff.divergences}
    assert DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE in kinds


def test_cr03_flat_local_position_stays_clean() -> None:
    """A zero-amount local position is flat — no false divergence."""
    local_positions = [
        {
            "symbol": "BTCUSDT",
            "position_side": "LONG",
            "position_amt": Decimal("0"),
        }
    ]
    diff = compare(
        local_open_orders=[],
        local_open_algos=[],
        local_open_positions=local_positions,
        truth_normal_orders=[],
        truth_algo_orders=[],
        truth_positions=[],
    )
    assert diff.agreement is True


# --------------------------------------------------------------------------- #
# WR-01: on_callback gates chat before the resolver read.
# --------------------------------------------------------------------------- #


class _FakeQuery:
    def __init__(self, data: str, chat_id: int, query_id: str = "q-default") -> None:
        # Telegram's callback_query.id: stable across redelivery, the source
        # of the callback correlation id (17-04, D-10).
        self.id = query_id
        self.data = data
        self.message = SimpleNamespace(chat_id=chat_id)
        self.answered = False

    async def answer(self) -> None:
        self.answered = True


class _FakeUpdate:
    def __init__(self, query: _FakeQuery, chat_id: int) -> None:
        self.callback_query = query
        self.effective_chat = SimpleNamespace(id=chat_id)


async def test_wr01_on_callback_gates_chat_before_resolver() -> None:
    """An unauthorized chat must never trigger a DB read by short id."""
    short_id = "a" * 32
    query = _FakeQuery("APR:" + short_id, chat_id=999)
    update = _FakeUpdate(query, chat_id=999)
    resolver_calls: list[str] = []

    def fake_dispatch(parsed: ParsedCallback, **kwargs: Any) -> DispatchResult:
        return DispatchResult(
            ok=False,
            kind=parsed.kind,
            reason_code=RejectionReason.INVALIDATED,
        )

    result = await on_callback(
        update,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        authorized_chat_id=CHAT_ID,
        binding_context_resolver=lambda sid: resolver_calls.append(sid),
        dispatch=fake_dispatch,
        reply_text_fn=None,
    )
    assert query.answered is True
    assert resolver_calls == []
    assert result.ok is False
    assert result.reason_code == RejectionReason.INVALIDATED


async def test_wr02_unauthorized_chat_gets_generic_rejection() -> None:
    """No reason code, kind, or status may leak to the attacker's chat."""
    short_id = "b" * 32
    query = _FakeQuery("APR:" + short_id, chat_id=999)
    update = _FakeUpdate(query, chat_id=999)
    replies: list[tuple[int, str]] = []

    async def fake_reply(chat_id: int, text: str) -> None:
        replies.append((chat_id, text))

    def fake_dispatch(parsed: ParsedCallback, **kwargs: Any) -> DispatchResult:
        return DispatchResult(
            ok=False,
            kind=parsed.kind,
            reason_code=RejectionReason.INVALIDATED,
        )

    await on_callback(
        update,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        authorized_chat_id=CHAT_ID,
        binding_context_resolver=lambda sid: None,
        dispatch=fake_dispatch,
        reply_text_fn=fake_reply,
    )
    assert len(replies) == 1
    assert replies[0][1] == "Rejected"


async def test_wr17_rapid_callbacks_get_distinct_correlations() -> None:
    """Distinct Telegram queries (double-taps) must not collide on receipt IDs.

    Correlation derives from `callback_query.id` (17-04): distinct presses carry
    distinct query ids, so they get distinct correlations even within one second.
    """
    short_id = "c" * 32
    seen: list[str] = []

    def fake_dispatch(parsed: ParsedCallback, **kwargs: Any) -> DispatchResult:
        seen.append(kwargs["correlation_id"])
        return DispatchResult(ok=True, kind=parsed.kind)

    for index in range(3):
        query = _FakeQuery("APR:" + short_id, chat_id=CHAT_ID, query_id=f"q-{index}")
        update = _FakeUpdate(query, chat_id=CHAT_ID)
        await on_callback(
            update,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            authorized_chat_id=CHAT_ID,
            binding_context_resolver=lambda sid: None,
            dispatch=fake_dispatch,
            reply_text_fn=None,
        )
    assert len(set(seen)) == 3


# --------------------------------------------------------------------------- #
# WR-03: stale/unknown short ids map to INVALIDATED, never a crash.
# --------------------------------------------------------------------------- #


def test_wr03_unknown_short_id_returns_invalidated() -> None:
    """A stale button (unknown short id) is a graceful INVALIDATED."""
    short_id = "d" * 32
    journal = _FakeJournal()
    result = dispatch_callback(
        ParsedCallback(raw="APR:" + short_id, kind=CallbackKind.APPROVE, short_id=short_id),
        callback_chat_id=CHAT_ID,
        authorized_chat_id=CHAT_ID,
        callback_at_utc=NOW,
        raw_token="sometoken",
        correlation_id="cb:wr03",
        journal_receipt=journal.record,
        lookup_by_short_id=lambda sid: None,
        lookup_by_token_hash=lambda th: None,
        save_atomic=lambda approval, mapping: None,
        now_utc=NOW,
        binding_context=_binding_context(),
    )
    assert result.ok is False
    assert result.reason_code == RejectionReason.INVALIDATED


def test_wr03_missing_binding_context_returns_invalidated() -> None:
    """A resolver hit with no binding context is INVALIDATED, not KeyError."""
    short_id = "e" * 32
    journal = _FakeJournal()
    result = dispatch_callback(
        ParsedCallback(raw="APR:" + short_id, kind=CallbackKind.APPROVE, short_id=short_id),
        callback_chat_id=CHAT_ID,
        authorized_chat_id=CHAT_ID,
        callback_at_utc=NOW,
        raw_token="sometoken",
        correlation_id="cb:wr03b",
        journal_receipt=journal.record,
        lookup_by_short_id=lambda sid: ("sig_x", "tp_x"),
        lookup_by_token_hash=lambda th: None,
        save_atomic=lambda approval, mapping: None,
        now_utc=NOW,
        binding_context=None,
    )
    assert result.ok is False
    assert result.reason_code == RejectionReason.INVALIDATED


# --------------------------------------------------------------------------- #
# WR-04: outcome events are journaled on every dispatch path.
# --------------------------------------------------------------------------- #


def test_wr04_success_path_journals_received_and_resolved() -> None:
    """A fresh APPROVE journals CALLBACK_RECEIVED then CALLBACK_RESOLVED."""
    raw = issue_one_time_token()
    token_hash = token_hash_of(raw)
    store = _Store(_make_pending_approval(raw_token=raw), token_hash)
    signal_id = "sig_wr04_" + "0" * 55
    short_id = derive_short_id(signal_id)
    journal = _FakeJournal()

    result = dispatch_callback(
        ParsedCallback(raw="APR:" + short_id, kind=CallbackKind.APPROVE, short_id=short_id),
        callback_chat_id=CHAT_ID,
        authorized_chat_id=CHAT_ID,
        callback_at_utc=NOW,
        raw_token=raw,
        correlation_id="cb:wr04",
        journal_receipt=journal.record,
        lookup_by_short_id=lambda sid: (signal_id, "tp_wr04"),
        lookup_by_token_hash=store.lookup,
        save_atomic=lambda approval, mapping: None,
        now_utc=NOW,
        binding_context=_binding_context(),
    )
    assert result.ok is True
    types = _event_types(journal)
    assert EVENT_TYPE_CALLBACK_RECEIVED in types
    assert EVENT_TYPE_CALLBACK_RESOLVED in types


def test_wr04_reject_path_journals_received_and_rejected() -> None:
    """A binding-gate failure journals CALLBACK_RECEIVED + CALLBACK_REJECTED."""
    short_id = "f" * 32
    journal = _FakeJournal()
    result = dispatch_callback(
        ParsedCallback(raw="APR:" + short_id, kind=CallbackKind.APPROVE, short_id=short_id),
        callback_chat_id=CHAT_ID,
        authorized_chat_id=CHAT_ID,
        callback_at_utc=NOW,
        raw_token="wrongtoken",
        correlation_id="cb:wr04b",
        journal_receipt=journal.record,
        lookup_by_short_id=lambda sid: None,
        lookup_by_token_hash=lambda th: None,
        save_atomic=lambda approval, mapping: None,
        now_utc=NOW,
        binding_context=_binding_context(),
    )
    assert result.ok is False
    types = _event_types(journal)
    assert EVENT_TYPE_CALLBACK_RECEIVED in types
    assert EVENT_TYPE_CALLBACK_REJECTED in types


# --------------------------------------------------------------------------- #
# WR-05: short-id consistency between callback and mapping row.
# --------------------------------------------------------------------------- #


def test_wr05_divergent_mapping_short_id_is_rejected() -> None:
    """A re-plan that changed the plan for the same signal fails closed."""
    raw = issue_one_time_token()
    token_hash = token_hash_of(raw)
    store = _Store(_make_pending_approval(raw_token=raw), token_hash)
    # Parsed short belongs to signal A; the mapping resolves to signal B.
    parsed_short = "1" * 32
    other_signal = "sig_other_" + "0" * 53
    assert derive_short_id(other_signal) != parsed_short
    journal = _FakeJournal()

    result = dispatch_callback(
        ParsedCallback(
            raw="APR:" + parsed_short,
            kind=CallbackKind.APPROVE,
            short_id=parsed_short,
        ),
        callback_chat_id=CHAT_ID,
        authorized_chat_id=CHAT_ID,
        callback_at_utc=NOW,
        raw_token=raw,
        correlation_id="cb:wr05",
        journal_receipt=journal.record,
        lookup_by_short_id=lambda sid: (other_signal, "tp_wr05"),
        lookup_by_token_hash=store.lookup,
        save_atomic=lambda approval, mapping: None,
        now_utc=NOW,
        binding_context=_binding_context(),
    )
    assert result.ok is False
    assert result.reason_code == RejectionReason.INVALIDATED
    row = store.lookup(token_hash)
    assert row is not None
    assert row.status == ApprovalResult.PENDING


# --------------------------------------------------------------------------- #
# WR-06: server time — never the callback's own timestamp — gates expiry.
# --------------------------------------------------------------------------- #


def test_wr06_stale_callback_judged_by_server_time() -> None:
    """A callback stamped before expiry but arriving after it is expired."""
    raw = issue_one_time_token()
    token_hash = token_hash_of(raw)
    store = _Store(_make_pending_approval(raw_token=raw), token_hash)
    callback_at = datetime(2026, 9, 19, 13, 0, tzinfo=UTC)
    server_now = datetime(2026, 9, 19, 15, 0, tzinfo=UTC)  # past EXPIRY

    with pytest.raises(ApprovalRejected) as exc_info:
        resolve_callback(
            Callback(
                raw_token=raw,
                chat_id=CHAT_ID,
                plan_hash=PLAN_HASH,
                strategy_version="v1.0.0",
                parameter_set_id="ps-1",
                parameter_set_hash=PARAM_HASH,
                callback_at_utc=callback_at,
            ),
            store.lookup,
            store.save,
            **_replay_kwargs(now_utc=server_now),
        )
    assert exc_info.value.reason_code == RejectionReason.APPROVAL_EXPIRED
    assert store.save_calls == 0


def test_wr06_dispatch_defaults_to_server_time() -> None:
    """dispatch_callback with now_utc=None resolves against wall-clock."""
    raw = issue_one_time_token()
    token_hash = token_hash_of(raw)
    store = _Store(_make_pending_approval(raw_token=raw), token_hash)
    signal_id = "sig_wr06_" + "0" * 55
    short_id = derive_short_id(signal_id)
    journal = _FakeJournal()
    # Far-future expiry so wall-clock server time still approves.
    far_expiry = datetime.now(UTC) + timedelta(days=30)

    result = dispatch_callback(
        ParsedCallback(raw="APR:" + short_id, kind=CallbackKind.APPROVE, short_id=short_id),
        callback_chat_id=CHAT_ID,
        authorized_chat_id=CHAT_ID,
        callback_at_utc=datetime(2026, 9, 19, 13, 0, tzinfo=UTC),
        raw_token=raw,
        correlation_id="cb:wr06",
        journal_receipt=journal.record,
        lookup_by_short_id=lambda sid: (signal_id, "tp_wr06"),
        lookup_by_token_hash=store.lookup,
        save_atomic=lambda approval, mapping: None,
        now_utc=None,
        binding_context=_binding_context(expiry=far_expiry),
    )
    assert result.ok is True


# --------------------------------------------------------------------------- #
# WR-07 / WR-08 / WR-09: sweeper failure isolation, already-gone, timestamps.
# --------------------------------------------------------------------------- #


async def test_wr07_sweeper_continues_after_single_cancel_failure() -> None:
    """One failing cancel must not abort the remaining orphans."""
    adapter = _FakeSweepAdapter(found=True, cancel_exc=RuntimeError("transient boom"))
    journal = _FakeJournal()
    sweeper = OrphanSweeper(adapter=adapter, journal=journal)
    diff = CompareDiff(
        agreement=False,
        divergences=(),
        orphan_protectives=(
            OrphanProtective(
                symbol="BTCUSDT",
                client_algo_id="algo-1",
                order_role=OrderRole.STOP_LOSS.value,
            ),
            OrphanProtective(
                symbol="BTCUSDT",
                client_algo_id="algo-2",
                order_role=OrderRole.TAKE_PROFIT_1.value,
            ),
        ),
    )
    # First cancel raises; flip to success for the second orphan.
    calls = {"n": 0}

    async def flaky_cancel(*, symbol: str, client_algo_id: str) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient boom")

    adapter.cancel_algo_order = flaky_cancel  # type: ignore[method-assign]
    outcome = await sweeper.sweep(
        diff,
        position_verifier=lambda symbol: Decimal("0"),
        now_utc=NOW,
    )
    assert outcome.swept_count == 1
    assert outcome.cancelled == (("BTCUSDT", "algo-2"),)
    assert len(outcome.skipped) == 1
    assert "cancel_failed" in outcome.skipped[0].reason


async def test_wr08_already_gone_not_counted_as_swept() -> None:
    """A not-found probe lands in already_gone with a journal trail."""
    adapter = _FakeSweepAdapter(found=False)
    journal = _FakeJournal()
    sweeper = OrphanSweeper(adapter=adapter, journal=journal)
    outcome = await sweeper.sweep(
        _orphan_diff(),
        position_verifier=lambda symbol: Decimal("0"),
        now_utc=NOW,
    )
    assert outcome.swept_count == 0
    assert outcome.cancelled == ()
    assert outcome.already_gone == (("BTCUSDT", "algo-orphan-1"),)
    assert adapter.cancels == []
    payloads = [e.payload_json for e in journal.events]
    assert any("already_gone" in p for p in payloads)


async def test_wr09_per_sweep_timestamp_used_not_pinned() -> None:
    """Two sweeps from one long-lived sweeper carry distinct journal IDs."""
    adapter = _FakeSweepAdapter(found=True)
    journal = _FakeJournal()
    sweeper = OrphanSweeper(adapter=adapter, journal=journal)
    t1 = datetime(2026, 9, 19, 13, 0, tzinfo=UTC)
    t2 = datetime(2026, 9, 19, 14, 0, tzinfo=UTC)
    verifier = lambda symbol: Decimal("0")  # noqa: E731
    await sweeper.sweep(_orphan_diff(), position_verifier=verifier, now_utc=t1)
    await sweeper.sweep(_orphan_diff(), position_verifier=verifier, now_utc=t2)
    ids = [e.journal_event_id for e in journal.events]
    assert len(set(ids)) == len(ids)


# --------------------------------------------------------------------------- #
# WR-10: concurrent same-token deliveries serialize to one transition.
# --------------------------------------------------------------------------- #


def test_wr10_concurrent_same_token_single_transition() -> None:
    """Racing threads on one token produce exactly one save."""
    raw = issue_one_time_token()
    token_hash = token_hash_of(raw)
    store = _Store(_make_pending_approval(raw_token=raw), token_hash)
    callback = _callback(raw)
    kwargs = _replay_kwargs()
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            resolve_callback(callback, store.lookup, store.save, **kwargs)
        except ApprovalRejected as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert store.save_calls == 1
    row = store.lookup(token_hash)
    assert row is not None
    assert row.status == ApprovalResult.APPROVED


# --------------------------------------------------------------------------- #
# WR-11 / WR-12 / WR-13 / WR-14: compare classification fixes.
# --------------------------------------------------------------------------- #


def test_wr11_side_mismatch_does_not_satisfy_protective() -> None:
    """A SHORT-side algo does not protect a LONG position."""
    local_positions = [{"symbol": "BTCUSDT", "position_side": "LONG", "position_amt": Decimal("1")}]
    local_algos = [
        {
            "client_algo_id": "sl-short",
            "symbol": "BTCUSDT",
            "order_role": OrderRole.STOP_LOSS.value,
            "status": OrderStatus.NEW.value,
            "position_side": "SHORT",
        }
    ]
    truth_algos = [SimpleNamespace(client_algo_id="sl-short", symbol="BTCUSDT")]
    diff = compare(
        local_open_orders=[],
        local_open_algos=local_algos,
        local_open_positions=local_positions,
        truth_normal_orders=[],
        truth_algo_orders=truth_algos,
        truth_positions=[],
    )
    kinds = {d.kind for d in diff.divergences}
    assert DIVERGENCE_KIND_ORPHAN_PROTECTIVE in kinds
    assert DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE in kinds


def test_wr11_zero_amount_local_position_ignored() -> None:
    """A flat local row must not suppress an orphan protective."""
    local_positions = [{"symbol": "BTCUSDT", "position_side": "LONG", "position_amt": Decimal("0")}]
    local_algos = [
        {
            "client_algo_id": "sl-1",
            "symbol": "BTCUSDT",
            "order_role": OrderRole.STOP_LOSS.value,
            "status": OrderStatus.NEW.value,
        }
    ]
    truth_algos = [SimpleNamespace(client_algo_id="sl-1", symbol="BTCUSDT")]
    diff = compare(
        local_open_orders=[],
        local_open_algos=local_algos,
        local_open_positions=local_positions,
        truth_normal_orders=[],
        truth_algo_orders=truth_algos,
        truth_positions=[],
    )
    kinds = {d.kind for d in diff.divergences}
    assert DIVERGENCE_KIND_ORPHAN_PROTECTIVE in kinds


def test_wr12_exchange_missing_protective_is_unsynced_not_orphan() -> None:
    """A protective the exchange never had is UNSYNCED_ALGO, not orphan."""
    local_algos = [
        {
            "client_algo_id": "sl-ghost",
            "symbol": "BTCUSDT",
            "order_role": OrderRole.STOP_LOSS.value,
            "status": OrderStatus.NEW.value,
        }
    ]
    diff = compare(
        local_open_orders=[],
        local_open_algos=local_algos,
        local_open_positions=[],
        truth_normal_orders=[],
        truth_algo_orders=[],
        truth_positions=[],
    )
    kinds = {d.kind for d in diff.divergences}
    assert DIVERGENCE_KIND_UNSYNCED_ALGO in kinds
    assert DIVERGENCE_KIND_ORPHAN_PROTECTIVE not in kinds
    assert diff.orphan_protectives == ()


def test_wr13_entry_guarded_only_by_ghost_algo_still_diverges() -> None:
    """An ENTRY whose only 'protection' has no exchange row diverges."""
    local_orders = [
        {
            "client_order_id": "entry-1",
            "symbol": "BTCUSDT",
            "order_role": OrderRole.ENTRY.value,
            "status": OrderStatus.NEW.value,
        }
    ]
    local_algos = [
        {
            "client_algo_id": "sl-ghost",
            "symbol": "BTCUSDT",
            "order_role": OrderRole.STOP_LOSS.value,
            "status": OrderStatus.NEW.value,
        }
    ]
    truth_normal = [SimpleNamespace(client_order_id="entry-1", symbol="BTCUSDT")]
    diff = compare(
        local_open_orders=local_orders,
        local_open_algos=local_algos,
        local_open_positions=[],
        truth_normal_orders=truth_normal,
        truth_algo_orders=[],
        truth_positions=[],
    )
    kinds = {d.kind for d in diff.divergences}
    assert DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE in kinds


def test_wr13_missing_entry_without_protection_yields_both() -> None:
    """A missing ENTRY with no protection yields both divergence kinds."""
    local_orders = [
        {
            "client_order_id": "entry-gone",
            "symbol": "BTCUSDT",
            "order_role": OrderRole.ENTRY.value,
            "status": OrderStatus.NEW.value,
        }
    ]
    diff = compare(
        local_open_orders=local_orders,
        local_open_algos=[],
        local_open_positions=[],
        truth_normal_orders=[],
        truth_algo_orders=[],
        truth_positions=[],
    )
    kinds = {d.kind for d in diff.divergences}
    assert DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE in kinds
    assert DIVERGENCE_KIND_UNSYNCED_NORMAL in kinds


def test_wr14_malformed_rows_diverge_not_raise() -> None:
    """Status-less / identity-less rows become divergences, never a tick abort."""
    local_orders = [{"symbol": "BTCUSDT", "order_role": OrderRole.ENTRY.value}]
    diff = compare(
        local_open_orders=local_orders,
        local_open_algos=[{"symbol": "BTCUSDT"}],
        local_open_positions=[],
        truth_normal_orders=[],
        truth_algo_orders=[],
        truth_positions=[],
    )
    assert diff.agreement is False
    assert len(diff.divergences) >= 1


# --------------------------------------------------------------------------- #
# WR-15: async position verifier supported.
# --------------------------------------------------------------------------- #


async def test_wr15_async_position_verifier_supported() -> None:
    """An async production-style verifier must not wedge the sweep."""

    async def async_verifier(*, symbol: str) -> Decimal:
        return Decimal("0")

    adapter = _FakeSweepAdapter(found=True)
    journal = _FakeJournal()
    sweeper = OrphanSweeper(adapter=adapter, journal=journal)
    outcome = await sweeper.sweep(_orphan_diff(), position_verifier=async_verifier, now_utc=NOW)
    assert outcome.swept_count == 1
    assert outcome.cancelled == (("BTCUSDT", "algo-orphan-1"),)


# --------------------------------------------------------------------------- #
# WR-16: exit_safe_mode honors a fresh intent supplier.
# --------------------------------------------------------------------------- #


class _LocalIntentStub:
    """Duck-typed local intent: the compare accepts plain dict rows (WR-14)."""

    def __init__(self, orders: list[Any], algos: list[Any], positions: list[Any]) -> None:
        self.orders = orders
        self.algos = algos
        self.positions = positions


async def test_wr16_exit_prefers_fresh_intent_fn_over_stale_lists() -> None:
    """A stale caller snapshot cannot force the exit decision."""
    journal = _FakeJournal()
    controller = SafeModeController(adapter=_FakeSafeAdapter(), journal=journal)
    controller.enter_safe_mode(reason="DIVERGENCE", now_utc=NOW)
    stale_orders = [
        {
            "client_order_id": "stale-1",
            "symbol": "BTCUSDT",
            "order_role": OrderRole.ENTRY.value,
            "status": OrderStatus.NEW.value,
        }
    ]
    # Fresh supplier matches the empty truth: exit must succeed. Since plan 20-15 there is no
    # list argument at all, so a stale caller snapshot cannot exist (`stale_orders` documents the
    # shape the old signature accepted).
    assert stale_orders
    decision = await controller.exit_safe_mode(
        operator_id="operator-1",
        local_intent_fn=lambda: _LocalIntentStub([], [], []),
        readiness=lambda: ExitReadiness(0, 0, 0),
        gate_status=lambda: (None, "RESTORED_DURABLE"),
        stream_state=lambda: "LIVE",
        now_utc=NOW,
    )
    assert decision.exited is True
    assert controller.in_safe_mode is False


async def test_wr16_divergent_intent_fn_blocks_exit() -> None:
    """A divergent fresh supplier blocks exit even with clean list args."""
    journal = _FakeJournal()
    controller = SafeModeController(adapter=_FakeSafeAdapter(), journal=journal)
    controller.enter_safe_mode(reason="DIVERGENCE", now_utc=NOW)
    divergent = [
        {
            "client_order_id": "fresh-ghost",
            "symbol": "BTCUSDT",
            "order_role": OrderRole.ENTRY.value,
            "status": OrderStatus.NEW.value,
        }
    ]
    decision = await controller.exit_safe_mode(
        operator_id="operator-1",
        local_intent_fn=lambda: _LocalIntentStub(divergent, [], []),
        readiness=lambda: ExitReadiness(0, 0, 0),
        gate_status=lambda: (None, "RESTORED_DURABLE"),
        stream_state=lambda: "LIVE",
        now_utc=NOW,
    )
    assert decision.exited is False
    assert decision.refusals == ("COMPARE_NOT_CLEAN",)
    assert controller.in_safe_mode is True


# --------------------------------------------------------------------------- #
# WR-18: plan-hash 64-hex enforcement.
# --------------------------------------------------------------------------- #


def test_wr18_short_plan_hash_rejected() -> None:
    """Prefix-only identities must never mint exchange-dedupe IDs."""
    with pytest.raises(ValueError):
        derive_client_order_id(plan_hash="abc", role=OrderRole.ENTRY.value)
    with pytest.raises(ValueError):
        derive_algo_client_id(plan_hash="abc", role=OrderRole.ENTRY.value)


def test_wr18_non_hex_plan_hash_rejected() -> None:
    """Uppercase / non-hex 64-char strings are not SHA-256 identities."""
    with pytest.raises(ValueError):
        derive_client_order_id(plan_hash="F" * 64, role=OrderRole.ENTRY.value)
    with pytest.raises(ValueError):
        derive_client_order_id(plan_hash="z" * 64, role=OrderRole.ENTRY.value)


def test_wr18_canonical_hash_still_derives() -> None:
    """A real 64-char lowercase hex hash derives 36-char IDs."""
    plan_hash = "ab" * 32
    client_id = derive_client_order_id(plan_hash=plan_hash, role=OrderRole.ENTRY.value)
    algo_id = derive_algo_client_id(plan_hash=plan_hash, role=OrderRole.STOP_LOSS.value)
    assert len(client_id) == 36
    assert len(algo_id) == 36


# --------------------------------------------------------------------------- #
# WR-19: snapshot projection refuses to fabricate quantity / timestamps.
# --------------------------------------------------------------------------- #


def test_wr19_missing_quantity_raises() -> None:
    """A row without orig_qty/quantity raises instead of becoming zero."""
    from src.adapters.binance_usdm import (
        _require_quantity,
        _require_update_time_utc,
    )

    with pytest.raises(ValueError, match="refusing to fabricate zero"):
        _require_quantity(None, "orig_qty")
    with pytest.raises(ValueError, match="refusing to fabricate epoch"):
        _require_update_time_utc(None)


def test_wr19_projectors_route_through_require_helpers() -> None:
    """All three projectors must call the loud require helpers."""
    import src.adapters.binance_usdm as adapter_mod

    for projector in (
        "_row_to_open_order_snapshot",
        "_row_to_open_algo_order_snapshot",
        "_row_to_position_snapshot",
    ):
        source = inspect.getsource(getattr(adapter_mod, projector))
        assert "_require_quantity" in source or projector.endswith("position_snapshot"), projector
        assert "_require_update_time_utc" in source, projector


# --------------------------------------------------------------------------- #
# WR-20: already-canceled errors skip the retry budget.
# --------------------------------------------------------------------------- #


def test_wr20_already_canceled_skips_retry() -> None:
    """A gone order succeeds immediately — no 3-attempt / 30s burn."""
    from binance_common.errors import BadRequestError
    from src.adapters.binance_usdm import _cancel_retry_predicate

    assert _cancel_retry_predicate(BadRequestError("Unknown order sent.", -2011)) is False
    # Plan 18-10 (D-10): message text no longer decides; a non-SDK error is never retried.
    gone = RuntimeError("APIError(code=-2011): UNKNOWN_ORDER ...")
    assert _cancel_retry_predicate(gone) is False


def test_wr20_transient_still_retries_programming_errors_do_not() -> None:
    """Status-unknown faults retry; deterministic and unknown faults fail closed at once.

    Plan 18-10 routes the predicate through the taxonomy: only STATUS_UNKNOWN (5xx, 408,
    network errors, -1006, -1007) is retried; a non-SDK exception such as RuntimeError is
    UNKNOWN_EXCHANGE_ERROR and is no longer retried.
    """
    from binance_common.errors import NetworkError, ServerError
    from src.adapters.binance_usdm import _cancel_retry_predicate

    assert _cancel_retry_predicate(ServerError("unavailable", 503)) is True
    assert _cancel_retry_predicate(NetworkError("timeout")) is True
    assert _cancel_retry_predicate(RuntimeError("timeout")) is False
    assert _cancel_retry_predicate(ValueError("bad wiring")) is False
    assert _cancel_retry_predicate(TypeError("bad type")) is False


# --------------------------------------------------------------------------- #
# WR-21: 64-byte ceiling raises ValueError (never bare assert).
# --------------------------------------------------------------------------- #


def test_wr21_simulate_keyboard_uses_value_error_not_assert() -> None:
    """The hard Telegram ceiling must survive `python -O`."""
    from src.adapters import telegram_notify as notify_mod

    source = inspect.getsource(notify_mod.build_simulate_keyboard)
    assert "raise ValueError" in source
    for line in source.splitlines():
        assert not line.lstrip().startswith("assert "), line


def test_wr21_keyboard_payloads_stay_within_64_bytes() -> None:
    """Built keyboards respect the Telegram ceiling behaviorally."""
    from src.adapters.telegram_notify import build_simulate_keyboard

    keyboard = build_simulate_keyboard("sig_wr21_" + "x" * 40)
    for row in keyboard.inline_keyboard:
        for button in row:
            data = button.callback_data
            assert isinstance(data, str)
            assert len(data.encode("utf-8")) <= 64


# --------------------------------------------------------------------------- #
# WR-22: format_approve fail-closed validation per field.
# --------------------------------------------------------------------------- #


def test_wr22_format_approve_rejects_negative_stop_loss() -> None:
    """A non-positive stop loss must never render into an alert."""
    from src.adapters.telegram_notify import format_approve

    kwargs = _valid_approve_kwargs()
    kwargs["stop_loss"] = Decimal("-1")
    with pytest.raises(ValueError):
        format_approve(**kwargs)


def test_wr22_format_approve_rejects_bad_tp_fraction() -> None:
    """A TP fraction outside (0, 1] must fail loudly."""
    from src.adapters.telegram_notify import format_approve

    kwargs = _valid_approve_kwargs()
    kwargs["take_profits"] = [(Decimal("62000"), Decimal("1.5"))]
    with pytest.raises(ValueError):
        format_approve(**kwargs)


def test_wr22_format_approve_rejects_empty_invalidation() -> None:
    """A blank invalidation field must fail loudly."""
    from src.adapters.telegram_notify import format_approve

    kwargs = _valid_approve_kwargs()
    kwargs["invalidation"] = ""
    with pytest.raises(ValueError):
        format_approve(**kwargs)


def test_wr22_format_approve_rejects_newline_reason_code() -> None:
    """Reason codes with embedded newlines allow message-shape spoofing."""
    from src.adapters.telegram_notify import format_approve

    kwargs = _valid_approve_kwargs()
    kwargs["reason_codes"] = ["OK\nFAKE: second message"]
    with pytest.raises(ValueError):
        format_approve(**kwargs)


def test_wr22_format_approve_renders_valid_message() -> None:
    """A fully valid payload still renders with all core fields."""
    from src.adapters.telegram_notify import format_approve

    text = format_approve(**_valid_approve_kwargs())
    assert "BTCUSDT" in text
    assert "59000" in text


# --------------------------------------------------------------------------- #
# WR-23: pure surfaces import without python-telegram-bot.
# --------------------------------------------------------------------------- #


def test_wr23_pure_surfaces_import_without_telegram() -> None:
    """parse/format/dispatch must work with the telegram package blocked."""
    repo_root = Path(__file__).resolve().parent.parent
    script = (
        "import sys; "
        "sys.modules['telegram'] = None; "
        "sys.modules['telegram.ext'] = None; "
        "from src.adapters.telegram_callbacks import parse_callback_data; "
        "from src.adapters.telegram_notify import format_approve; "
        "from decimal import Decimal; "
        "from datetime import datetime, UTC; "
        "p = parse_callback_data('APR:' + 'ab' * 16); "
        "assert p.short_id == 'ab' * 16; "
        "t = format_approve(symbol='BTCUSDT', direction='LONG', setup='S', "
        "entry_min=Decimal('1'), entry_max=Decimal('2'), "
        "stop_loss=Decimal('0.5'), "
        "take_profits=[(Decimal('3'), Decimal('0.5'))], rr=Decimal('2'), "
        "risk_pct=Decimal('1'), "
        "expiry_utc=datetime(2026, 9, 19, 14, 0, tzinfo=UTC), "
        "invalidation='x', exposure_quote=Decimal('10'), "
        "reason_codes=['R'], signal_id='s', "
        "detected_at_utc=datetime(2026, 9, 19, 12, 0, tzinfo=UTC), "
        "approved_quantity=Decimal('0.5')); "
        "assert 'BTCUSDT' in t; "
        "print('pure-ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "pure-ok" in result.stdout, result.stderr


# --------------------------------------------------------------------------- #
# WR-24 / WR-25: the vacuous-test fixes are armed.
# --------------------------------------------------------------------------- #


def test_wr24_synonym_guard_test_is_armed() -> None:
    """The canonical-vocabulary guard must actually collect suspects."""
    path = (Path(__file__).resolve().parent / "test_approval_replay.py").read_text(encoding="utf-8")
    assert "suspicious.append" in path


def test_wr25_drill_invariant_test_asserts() -> None:
    """The no-place-order drill test must assert on every fake adapter."""
    path = Path(__file__).resolve().parent / "test_drills.py"
    text = path.read_text(encoding="utf-8")
    assert "place_order_calls == 0" in text
    assert "BUILT_DRILL_ADAPTERS" in text


# --------------------------------------------------------------------------- #
# WR-26: drills propagate programming errors.
# --------------------------------------------------------------------------- #


def _drill_controller() -> SafeModeController:
    return SafeModeController(adapter=_FakeSafeAdapter(), journal=_FakeJournal())


def test_wr26_api_down_propagates_programming_errors() -> None:
    """A TypeError in harness wiring must not pass as 'degradation'."""
    declaration = make_api_down_drill(
        safe_mode_controller=_drill_controller(),
        api_call=lambda: (_ for _ in ()).throw(TypeError("harness wiring boom")),
    )
    with pytest.raises(TypeError):
        run_drill(declaration, journal=DrillLog(), now_utc=NOW)


def test_wr26_db_failure_propagates_programming_errors() -> None:
    """A TypeError in harness wiring must not pass as 'DB degradation'."""
    declaration = make_db_failure_drill(
        safe_mode_controller=_drill_controller(),
        db_write=lambda: (_ for _ in ()).throw(AttributeError("harness wiring boom")),
    )
    with pytest.raises(AttributeError):
        run_drill(declaration, journal=DrillLog(), now_utc=NOW)


def test_wr26_transient_runtime_error_still_counts_as_degradation() -> None:
    """The injected RuntimeError transient still rehearses SAFE_MODE."""
    declaration = make_api_down_drill(
        safe_mode_controller=_drill_controller(),
        api_call=lambda: (_ for _ in ()).throw(RuntimeError("transient 503")),
    )
    outcome = run_drill(declaration, journal=DrillLog(), now_utc=NOW)
    assert outcome.outcome == "safe_mode_entered"


# --------------------------------------------------------------------------- #
# WR-27: restore drill requires caller-supplied time.
# --------------------------------------------------------------------------- #


def test_wr27_restore_drill_requires_now_utc() -> None:
    """No wall-clock fallback: now_utc is a required keyword."""
    with pytest.raises(TypeError):
        make_restore_drill(safe_mode_controller=_drill_controller())  # type: ignore[call-arg]


def test_wr27_restore_drill_signature_has_no_default() -> None:
    """The now_utc parameter must have no default value."""
    sig = inspect.signature(make_restore_drill)
    param = sig.parameters["now_utc"]
    assert param.default is inspect.Parameter.empty


# --------------------------------------------------------------------------- #
# WR-28: manual-close drill honors the injected compare.
# --------------------------------------------------------------------------- #


def test_wr28_manual_close_uses_injected_compare() -> None:
    """A sentinel compare must observe the drill's invocation."""
    from src.reconcile.compare import compare as real_compare

    calls: list[dict[str, Any]] = []

    def sentinel(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return real_compare(**kwargs)

    adapter = _FakeSweepAdapter(found=True)
    journal = _FakeJournal()
    sweeper = OrphanSweeper(adapter=adapter, journal=journal)
    algo_id = "xa-" + "0" * 31 + "SL"
    local_intent = {
        "open_orders": [],
        "open_algos": [
            {
                "client_algo_id": algo_id,
                "symbol": "BTCUSDT",
                "order_role": OrderRole.STOP_LOSS.value,
                "status": OrderStatus.NEW.value,
            }
        ],
        "open_positions": [],
    }
    truth = {
        "normal_orders": [],
        "algo_orders": [SimpleNamespace(client_algo_id=algo_id, symbol="BTCUSDT")],
        "positions": [],
    }
    declaration = make_manual_close_drill(
        sweeper=sweeper,
        safe_mode_controller=_drill_controller(),
        local_intent=local_intent,
        truth=truth,
        position_verifier=lambda symbol: Decimal("0"),
        compare_fn=sentinel,
    )
    outcome = run_drill(declaration, journal=DrillLog(), now_utc=NOW)
    assert outcome.outcome == "orphan_swept"
    assert len(calls) == 1


# --------------------------------------------------------------------------- #
# WR-29: DrillLog concurrency control.
# --------------------------------------------------------------------------- #


def test_wr29_concurrent_drill_records_all_survive() -> None:
    """Concurrent run_drill calls must neither lose nor corrupt rows."""
    log = DrillLog()

    def make_decl() -> DrillDeclaration:
        return DrillDeclaration(
            name="unprotected",
            runbook_section="audit",
            inject=lambda: "fault",
            assert_outcome=lambda journal, ctx: "safe_mode_entered",
        )

    def worker() -> None:
        run_drill(make_decl(), journal=log, now_utc=NOW)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(log.events) == 20
    assert log._sequence == 20


def test_wr29_drill_log_has_lock_and_sequence() -> None:
    """The log guards record/reset with a lock and a monotonic sequence."""
    log = DrillLog()
    assert hasattr(log, "_lock")
    assert hasattr(log, "_sequence")
    run_drill(
        DrillDeclaration(
            name="unprotected",
            runbook_section="audit",
            inject=lambda: "fault",
            assert_outcome=lambda journal, ctx: "safe_mode_entered",
        ),
        journal=log,
        now_utc=NOW,
    )
    assert log._sequence == 1


# --------------------------------------------------------------------------- #
# WR-30: mapping-table retention contract + uniqueness guard.
# --------------------------------------------------------------------------- #


def test_wr30_migration_documents_retention_and_unique_guard() -> None:
    """The mapping table must pin its lifecycle and reject divergent rebinds."""
    path = (
        Path(__file__).resolve().parent.parent / "src/db/alembic/versions/0003_callback_mapping.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "purge" in text.lower()
    assert "uq_short_id_mapping_signal_trade_plan" in text
    assert "unique=True" in text


# --------------------------------------------------------------------------- #
# WR-31: SIMULATE never transitions approval state.
# --------------------------------------------------------------------------- #


def test_wr31_stored_simulate_action_rejected_explicitly() -> None:
    """A SIMULATE-action approval reaching replay is INVALIDATED, not ValueError."""
    raw = issue_one_time_token()
    token_hash = token_hash_of(raw)
    store = _Store(
        _make_pending_approval(action=ApprovalAction.SIMULATE, raw_token=raw),
        token_hash,
    )
    with pytest.raises(ApprovalRejected) as exc_info:
        resolve_callback(
            _callback(raw),
            store.lookup,
            store.save,
            **_replay_kwargs(),
        )
    assert exc_info.value.reason_code == RejectionReason.INVALIDATED
    assert "SIMULATE" in str(exc_info.value)
    assert store.save_calls == 0


def test_wr31_callback_simulate_action_rejected() -> None:
    """A SIMULATE callback action never transitions, even on APPROVE plans."""
    raw = issue_one_time_token()
    token_hash = token_hash_of(raw)
    store = _Store(_make_pending_approval(raw_token=raw), token_hash)
    with pytest.raises(ApprovalRejected) as exc_info:
        resolve_callback(
            _callback(raw, action=ApprovalAction.SIMULATE),
            store.lookup,
            store.save,
            **_replay_kwargs(),
        )
    assert exc_info.value.reason_code == RejectionReason.INVALIDATED
    assert store.save_calls == 0


# --------------------------------------------------------------------------- #
# Phase 18 review WR-07: sweeper journals no exception text and isolates journal failures.
# --------------------------------------------------------------------------- #

_SIGNED_URL_TEXT = "Network error: GET https://x.test/fapi?signature=" + "ab" * 32 + "&timestamp=1"


class _PostImageFailingJournal(_FakeJournal):
    def record(self, event: Any) -> None:
        if '"phase":"post_cancel"' in event.payload_json.replace(" ", ""):
            raise RuntimeError("journal down")
        super().record(event)


class _FailureEventFailingJournal(_FakeJournal):
    def record(self, event: Any) -> None:
        if "sweep_failed" in event.payload_json:
            raise RuntimeError("journal down")
        super().record(event)


async def test_review_wr07_failure_events_carry_the_exception_type_only() -> None:
    adapter = _FakeSweepAdapter(found=True, cancel_exc=RuntimeError(_SIGNED_URL_TEXT))
    journal = _FakeJournal()
    sweeper = OrphanSweeper(adapter=adapter, journal=journal)
    outcome = await sweeper.sweep(
        _orphan_diff(), position_verifier=lambda symbol: Decimal("0"), now_utc=NOW
    )
    assert outcome.skipped[0].reason == "cancel_failed: RuntimeError"
    assert journal.events
    assert all("signature" not in e.payload_json for e in journal.events)
    assert any("cancel_failed: RuntimeError" in e.payload_json for e in journal.events)


async def test_review_wr07_probe_failure_event_carries_the_exception_type_only() -> None:
    adapter = _FakeSweepAdapter(found=True)

    async def broken_probe(*, client_algo_id: str) -> Any:
        raise RuntimeError(_SIGNED_URL_TEXT)

    adapter.query_algo_order_by_client = broken_probe  # type: ignore[method-assign]
    journal = _FakeJournal()
    sweeper = OrphanSweeper(adapter=adapter, journal=journal)
    outcome = await sweeper.sweep(
        _orphan_diff(), position_verifier=lambda symbol: Decimal("0"), now_utc=NOW
    )
    assert outcome.skipped[0].reason == "probe_failed: RuntimeError"
    assert all("signature" not in e.payload_json for e in journal.events)


async def test_review_wr07_a_post_image_failure_still_counts_the_cancel() -> None:
    adapter = _FakeSweepAdapter(found=True)
    journal = _PostImageFailingJournal()
    sweeper = OrphanSweeper(adapter=adapter, journal=journal)
    outcome = await sweeper.sweep(
        _orphan_diff(), position_verifier=lambda symbol: Decimal("0"), now_utc=NOW
    )
    assert adapter.cancels == [("BTCUSDT", "algo-orphan-1")]
    assert outcome.cancelled == (("BTCUSDT", "algo-orphan-1"),)
    assert outcome.skipped == ()
    assert any("post_image_failed: RuntimeError" in e.payload_json for e in journal.events)


async def test_review_wr07_a_failing_failure_event_does_not_end_the_sweep() -> None:
    adapter = _FakeSweepAdapter(found=True)
    calls = {"n": 0}

    async def flaky_cancel(*, symbol: str, client_algo_id: str) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")

    adapter.cancel_algo_order = flaky_cancel  # type: ignore[method-assign]
    journal = _FailureEventFailingJournal()
    sweeper = OrphanSweeper(adapter=adapter, journal=journal)
    diff = CompareDiff(
        agreement=False,
        divergences=(),
        orphan_protectives=(
            OrphanProtective(
                symbol="BTCUSDT", client_algo_id="algo-1", order_role=OrderRole.STOP_LOSS.value
            ),
            OrphanProtective(
                symbol="BTCUSDT",
                client_algo_id="algo-2",
                order_role=OrderRole.TAKE_PROFIT_1.value,
            ),
        ),
    )
    outcome = await sweeper.sweep(diff, position_verifier=lambda symbol: Decimal("0"), now_utc=NOW)
    assert outcome.cancelled == (("BTCUSDT", "algo-2"),)
    assert [s.client_algo_id for s in outcome.skipped] == ["algo-1"]
