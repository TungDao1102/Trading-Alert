"""The mode-independent CONFIRM core (Phase 23, plan 23-06, D-09, D-10, D-16, P16R-02).

`src/approval/confirm_core.py` holds the state machine SHADOW has run since Phase 16, parametrized
by a `ConfirmProfile`. These tests prove, at core level and without Telegram:

- the core imports nothing from `src.execution`, `src.paper`, `src.adapters` or `telegram`;
- the SHADOW profile equals the literals the SHADOW evidence is written with;
- a DEMO or LIVE profile journals DEMO_* / LIVE_* events with its own mode label (Task 1);
- every CONFIRM adopted in one sweep reaches `on_confirmed` once, in order (Task 2, P16R-02);
- the D-10 refusal matrix: nothing but one valid CONFIRM reaches `on_confirmed` (Task 3).
"""

from __future__ import annotations

import ast
import hashlib
import json
import threading
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from src.approval import confirm_core
from src.approval.confirm_core import (
    DEMO_CONFIRM_PROFILE,
    LIVE_CONFIRM_PROFILE,
    SHADOW_CONFIRM_PROFILE,
    ConfirmBook,
    ConfirmEntry,
    ConfirmOutcome,
    ConfirmProfile,
    ConfirmRecord,
    ConfirmResult,
    ConfirmState,
)
from src.domain.approval import Approval
from src.domain.enums import ApprovalAction, ApprovalResult, RejectionReason
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.paper import shadow, shadow_confirm

from tests.shadow_fakes import (
    CHAT_ID,
    OTHER_USER_ID,
    T0,
    USER_ID,
    InMemoryShadowStores,
    make_shadow_plan,
    make_shadow_signal,
)

CORE_SOURCE = Path(__file__).resolve().parents[1] / "src" / "approval" / "confirm_core.py"
BANNED_PREFIXES = ("src.execution", "src.paper", "src.adapters", "telegram")

T_ISSUE = T0 + timedelta(minutes=7)
TTL = 60


def _imported_modules(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names.add(module)
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return names


def _is_banned(name: str) -> bool:
    return any(name == p or name.startswith(p + ".") for p in BANNED_PREFIXES)


# --------------------------------------------------------------------------- #
# The core's rig: stores, a movable clock, a recording hook and the DEMO or LIVE profile.
# --------------------------------------------------------------------------- #


def _card(
    profile: ConfirmProfile,
) -> Any:
    def render(signal: Signal, plan: TradePlan, mark: Any, now_utc: Any, ttl: int) -> str:
        return f"{profile.mode_label} card {signal.symbol} {plan.plan_hash[:4]} ttl={ttl}"

    return render


class CoreRig:
    """A core `ConfirmBook` over in-memory stores, with approved plans on demand."""

    def __init__(
        self,
        profile: ConfirmProfile = DEMO_CONFIRM_PROFILE,
        *,
        ttl: int = TTL,
        recheck: Any = None,
        on_confirmed: Any = None,
        stores: InMemoryShadowStores | None = None,
    ) -> None:
        self.profile = profile
        self.stores = InMemoryShadowStores() if stores is None else stores
        self.now = T_ISSUE
        self.hook_calls: list[tuple[Approval, TradePlan, Any]] = []
        self.recheck_calls = 0
        self._recheck = recheck
        self._on_confirmed = on_confirmed
        self.book = ConfirmBook(
            self.stores,
            profile=profile,
            clock=lambda: self.now,
            card_renderer=_card(profile),
            ttl_seconds=ttl,
            recheck=self._recheck_fn,
            on_confirmed=self._hook,
        )

    def _recheck_fn(self, signal: Signal, plan: TradePlan, now_utc: Any) -> Any:
        self.recheck_calls += 1
        if self._recheck is None:
            return None
        return self._recheck(signal, plan, now_utc)

    def _hook(self, approval: Approval, plan: TradePlan, at: Any) -> None:
        self.hook_calls.append((approval, plan, at))
        if self._on_confirmed is not None:
            self._on_confirmed(approval, plan, at)

    def approved(
        self, n: int = 1, *, request_hash: str | None = None, **plan_overrides: Any
    ) -> tuple[Signal, TradePlan, Approval]:
        """An APPROVED approval of plan n in the stores (the state after the APPROVE press)."""
        signal = make_shadow_signal(n)
        plan = make_shadow_plan(signal, plan_hash=f"{n:x}".rjust(64, "d"), **plan_overrides)
        self.stores.insert_signal(signal)
        self.stores.insert_trade_plan(plan)
        token_hash = hashlib.sha256(f"approval-token-{n}".encode()).hexdigest()
        base = {
            "approval_id": f"apr-{n}",
            "trade_plan_id": plan.trade_plan_id,
            "signal_id": signal.signal_id,
            "action": ApprovalAction.APPROVE,
            "approval_token_hash": token_hash,
            "requested_at_utc": T0,
            "request_hash": plan.plan_hash if request_hash is None else request_hash,
        }
        pending = Approval(
            **base, result=ApprovalResult.PENDING, status=ApprovalResult.PENDING, actor_id=""
        )
        self.stores.insert_pending(pending)
        approved = Approval(
            **base,
            result=ApprovalResult.APPROVED,
            status=ApprovalResult.APPROVED,
            acted_at_utc=T_ISSUE,
            actor_id=str(USER_ID),
        )
        self.stores.save_atomic(approved, None)
        return signal, plan, approved

    def issue(
        self,
        n: int = 1,
        *,
        user: int | None = USER_ID,
        request_hash: str | None = None,
        **plan_overrides: Any,
    ) -> ConfirmEntry:
        """Approve plan n and issue its confirm card (delivered through the edit path)."""
        signal, plan, approval = self.approved(n, request_hash=request_hash, **plan_overrides)
        entry = self.book.issue(
            short_id=f"s{n:03d}",
            approval=approval,
            signal=signal,
            plan=plan,
            approving_user_id=user,
            now_utc=self.now,
        )
        if entry.state is ConfirmState.PENDING:
            self.book.record_issued(
                entry,
                delivery="edit",
                message_id=1,
                attempts=1,
                edit_failure=None,
                now_utc=self.now,
            )
        return entry

    def confirm(
        self,
        entry: ConfirmEntry,
        *,
        user: int | None = USER_ID,
        at: Any = None,
        correlation: str = "cbq:c1",
        chat_id: int = CHAT_ID,
    ) -> ConfirmResult:
        return self.book.handle_confirm(
            short_id=entry.short_id,
            chat_id=chat_id,
            authorized_chat_id=CHAT_ID,
            from_user_id=user,
            now_utc=self.now if at is None else at,
            correlation_id=correlation,
        )

    def cancel(
        self, entry: ConfirmEntry, *, user: int | None = USER_ID, correlation: str = "cbq:x1"
    ) -> ConfirmResult:
        return self.book.handle_cancel(
            short_id=entry.short_id,
            chat_id=CHAT_ID,
            authorized_chat_id=CHAT_ID,
            from_user_id=user,
            now_utc=self.now,
            correlation_id=correlation,
        )

    def journal(self, event_type: str) -> list[Any]:
        return self.stores.journal_of_type(event_type)


def _payload(event: Any) -> dict[str, Any]:
    loaded = json.loads(event.payload_json)
    assert isinstance(loaded, dict)
    return loaded


# --------------------------------------------------------------------------- #
# Task 1: the tracer - the core, the SHADOW profile and the profile contract.
# --------------------------------------------------------------------------- #


def test_the_core_imports_nothing_order_capable_or_telegram_facing() -> None:
    imported = _imported_modules(CORE_SOURCE.read_text(encoding="utf-8"))
    assert imported, "the scan found no import at all (vacuous)"
    assert [name for name in sorted(imported) if _is_banned(name)] == []


def test_the_import_ban_scan_can_fail() -> None:
    seeded = (
        "import telegram\nfrom src.paper.shadow import Mode\nfrom src.execution import manager\n"
    )
    banned = [name for name in _imported_modules(seeded) if _is_banned(name)]
    assert {"telegram", "src.paper.shadow", "src.execution"} <= set(banned)


def test_the_core_has_no_shadow_gate_and_no_message_text() -> None:
    source = CORE_SOURCE.read_text(encoding="utf-8")
    assert "require_shadow" not in source
    assert "render_shadow_message" not in source


def test_the_shadow_profile_holds_the_literals_the_shadow_evidence_is_written_with() -> None:
    p = SHADOW_CONFIRM_PROFILE
    assert p.event_issued == "SHADOW_CONFIRM_ISSUED"
    assert p.event_confirmed == "SHADOW_CONFIRMED"
    assert p.event_cancelled == "SHADOW_CONFIRM_CANCELLED"
    assert p.event_expired == "SHADOW_CONFIRM_EXPIRED"
    assert p.event_rejected == "SHADOW_CONFIRM_REJECTED"
    assert p.event_notice_failed == "SHADOW_CONFIRM_NOTICE_FAILED"
    assert p.entity_type == "ShadowConfirm"
    assert p.correlation_prefix == "shadow-confirm:"
    assert p.journal_prefix == "shadow-cnf"
    assert p.mode_label == "SHADOW"
    assert p.log_namespace == "paper.shadow_confirm"
    assert p.terminal_events == (
        "SHADOW_CONFIRMED",
        "SHADOW_CONFIRM_CANCELLED",
        "SHADOW_CONFIRM_EXPIRED",
    )


def test_the_shadow_module_names_are_the_profile_values() -> None:
    p = SHADOW_CONFIRM_PROFILE
    assert shadow_confirm.EVENT_SHADOW_CONFIRMED is p.event_confirmed
    assert shadow_confirm.EVENT_SHADOW_CONFIRM_ISSUED == p.event_issued
    assert shadow_confirm.EVENT_SHADOW_CONFIRM_CANCELLED == p.event_cancelled
    assert shadow_confirm.EVENT_SHADOW_CONFIRM_EXPIRED == p.event_expired
    assert shadow_confirm.EVENT_SHADOW_CONFIRM_REJECTED == p.event_rejected
    assert shadow_confirm.EVENT_SHADOW_CONFIRM_NOTICE_FAILED == p.event_notice_failed
    assert shadow_confirm.TERMINAL_CONFIRM_EVENTS == p.terminal_events
    assert shadow_confirm._correlation("x") == "shadow-confirm:x"
    assert shadow_confirm.CONFIRM_TTL_SECONDS_DEFAULT == confirm_core.CONFIRM_TTL_SECONDS_DEFAULT


def test_the_moved_enum_and_record_are_the_same_objects_in_shadow() -> None:
    assert shadow.ConfirmOutcome is ConfirmOutcome
    assert shadow.ConfirmRecord is ConfirmRecord
    assert shadow_confirm.ConfirmOutcome is ConfirmOutcome
    assert issubclass(shadow_confirm.ConfirmBook, ConfirmBook)


def test_every_former_shadow_confirm_name_is_still_importable() -> None:
    for name in shadow_confirm.__all__:
        assert hasattr(shadow_confirm, name), name
    for name in (
        "ConfirmEntry",
        "ConfirmResult",
        "ConfirmState",
        "ConfirmStores",
        "ReservationPort",
        "ReserveOutcome",
        "StrandedApprovals",
        "REASON_CARD_DELIVERY_FAILED",
        "REASON_CHAT_MISMATCH",
        "REASON_CONFIRM_ALREADY_EXPIRED",
        "REASON_CONFIRM_TTL_ELAPSED",
        "REASON_NO_CONFIRM_CONTEXT",
        "REASON_RECHECK_ERROR",
        "REASON_RUNTIME_RESTART",
        "REASON_USER_ID_UNAVAILABLE",
        "REASON_USER_MISMATCH",
    ):
        assert hasattr(shadow_confirm, name), name


def test_the_user_id_reason_has_one_definition() -> None:
    from src.approval import reason_codes

    assert confirm_core.REASON_USER_ID_UNAVAILABLE is reason_codes.USER_ID_UNAVAILABLE


def test_a_demo_book_constructs_without_the_shadow_gate_and_journals_demo_names() -> None:
    rig = CoreRig(DEMO_CONFIRM_PROFILE)
    entry = rig.issue()
    assert entry.card_text.startswith("DEMO card")  # the injected renderer, no text of its own
    (issued,) = rig.journal("DEMO_CONFIRM_ISSUED")
    assert issued.entity_type == "DemoConfirm"
    assert issued.correlation_id == "demo-confirm:apr-1"
    assert issued.journal_event_id.startswith("demo-cnf_")
    assert _payload(issued)["mode"] == "DEMO"
    assert rig.journal("SHADOW_CONFIRM_ISSUED") == []


def test_a_live_book_journals_live_names() -> None:
    rig = CoreRig(LIVE_CONFIRM_PROFILE)
    rig.issue()
    (issued,) = rig.journal("LIVE_CONFIRM_ISSUED")
    assert issued.entity_type == "LiveConfirm"
    assert issued.correlation_id == "live-confirm:apr-1"
    assert issued.journal_event_id.startswith("live-cnf_")
    assert _payload(issued)["mode"] == "LIVE"


def test_the_three_profiles_share_no_journal_name() -> None:
    names: list[str] = []
    for profile in (SHADOW_CONFIRM_PROFILE, DEMO_CONFIRM_PROFILE, LIVE_CONFIRM_PROFILE):
        names += [
            profile.event_issued,
            profile.event_confirmed,
            profile.event_cancelled,
            profile.event_expired,
            profile.event_rejected,
            profile.event_notice_failed,
        ]
    assert len(names) == len(set(names)) == 18


def test_a_valid_confirm_in_the_core_reaches_the_hook_once() -> None:
    rig = CoreRig(DEMO_CONFIRM_PROFILE)
    entry = rig.issue()
    result = rig.confirm(entry)
    assert result.outcome is ConfirmOutcome.CONFIRMED and not result.replayed
    assert len(rig.hook_calls) == 1


# --------------------------------------------------------------------------- #
# Task 2: P16R-02 - every CONFIRM adopted in one sweep reaches on_confirmed once, in order.
# --------------------------------------------------------------------------- #


class UnreadableJournalStores(InMemoryShadowStores):
    """A CONFIRM append that commits and then raises, and a journal read that can be broken.

    The press cannot settle the unknown append (the read raises), so the entry keeps
    `confirm_append_unknown` and a later sweep adopts the committed CONFIRM.
    """

    def __init__(self) -> None:
        super().__init__()
        self.raise_after_confirm_write = True
        self.unreadable = True

    def record_journal(self, event: Any) -> None:
        super().record_journal(event)
        if self.raise_after_confirm_write and event.event_type.endswith("_CONFIRMED"):
            raise ConnectionError("commit acknowledgement lost")

    def journal_for_correlation(self, correlation_id: str) -> list[Any]:
        if self.unreadable:
            raise ConnectionError("journal unreadable")
        return super().journal_for_correlation(correlation_id)


def _two_unknown_confirms(rig: CoreRig, stores: UnreadableJournalStores) -> tuple[Any, Any]:
    """Two entries whose CONFIRM append committed but is unknown; returns their two entries."""
    entries = (rig.issue(1), rig.issue(2))
    for n, entry in enumerate(entries, start=1):
        with pytest.raises(ConnectionError):
            rig.confirm(entry, correlation=f"cbq:c{n}")
        assert entry.confirm_append_unknown and entry.state is ConfirmState.PENDING
    assert rig.hook_calls == []
    stores.raise_after_confirm_write = False
    stores.unreadable = False
    return entries


def _lock_is_free(rig: CoreRig) -> bool:
    """True when another thread can take the book lock (the hook runs outside it, B2-CR-01)."""
    got: list[bool] = []

    def probe() -> None:
        acquired = rig.book._lock.acquire(blocking=False)  # type: ignore[attr-defined]
        got.append(acquired)
        if acquired:
            rig.book._lock.release()  # type: ignore[attr-defined]

    thread = threading.Thread(target=probe)
    thread.start()
    thread.join()
    return got == [True]


def test_two_adoptions_in_one_sweep_reach_the_hook_once_each_in_order() -> None:
    stores = UnreadableJournalStores()
    lock_free: list[bool] = []
    rig = CoreRig(DEMO_CONFIRM_PROFILE, stores=stores, on_confirmed=lambda a, p, t: None)
    rig._on_confirmed = lambda a, p, t: lock_free.append(_lock_is_free(rig))
    a, b = _two_unknown_confirms(rig, stores)
    confirmed_at = T_ISSUE

    rig.now = T_ISSUE + timedelta(seconds=TTL + 1)
    expired = rig.book.expire_due(rig.now)

    assert expired == []  # both were adopted as CONFIRMED, neither expired
    assert [call[0].approval_id for call in rig.hook_calls] == ["apr-1", "apr-2"]
    assert [call[1].trade_plan_id for call in rig.hook_calls] == [
        a.plan.trade_plan_id,
        b.plan.trade_plan_id,
    ]
    assert [call[2] for call in rig.hook_calls] == [confirmed_at, confirmed_at]
    assert lock_free == [True, True], "the hook ran while the book lock was held"
    assert a.state is b.state is ConfirmState.CONFIRMED
    # A second sweep adopts nothing and calls nothing.
    assert rig.book.expire_due(rig.now + timedelta(seconds=5)) == []
    assert len(rig.hook_calls) == 2


def test_a_hook_that_raises_on_the_first_adoption_still_receives_the_second() -> None:
    stores = UnreadableJournalStores()

    def boom_on_first(approval: Approval, plan: TradePlan, at: Any) -> None:
        if approval.approval_id == "apr-1":
            raise RuntimeError("hook failed for apr-1")

    rig = CoreRig(DEMO_CONFIRM_PROFILE, stores=stores, on_confirmed=boom_on_first)
    _two_unknown_confirms(rig, stores)

    rig.now = T_ISSUE + timedelta(seconds=TTL + 1)
    with pytest.raises(RuntimeError, match="apr-1"):
        rig.book.expire_due(rig.now)

    assert [call[0].approval_id for call in rig.hook_calls] == ["apr-1", "apr-2"]
    assert _lock_is_free(rig)


def test_the_first_of_several_hook_errors_is_the_one_re_raised() -> None:
    stores = UnreadableJournalStores()

    def boom(approval: Approval, plan: TradePlan, at: Any) -> None:
        raise RuntimeError(f"hook failed for {approval.approval_id}")

    rig = CoreRig(DEMO_CONFIRM_PROFILE, stores=stores, on_confirmed=boom)
    _two_unknown_confirms(rig, stores)

    rig.now = T_ISSUE + timedelta(seconds=TTL + 1)
    with pytest.raises(RuntimeError, match="apr-1"):
        rig.book.expire_due(rig.now)
    assert len(rig.hook_calls) == 2


def test_a_press_that_confirms_one_entry_calls_the_hook_exactly_once() -> None:
    rig = CoreRig(DEMO_CONFIRM_PROFILE)
    entry = rig.issue()
    assert rig.confirm(entry).outcome is ConfirmOutcome.CONFIRMED
    assert len(rig.hook_calls) == 1
    rig.now = T_ISSUE + timedelta(seconds=TTL + 1)
    rig.book.expire_due(rig.now)  # nothing left to adopt or expire
    assert len(rig.hook_calls) == 1


def test_the_deferred_confirmations_are_a_list_not_the_last_one_only() -> None:
    source = CORE_SOURCE.read_text(encoding="utf-8")
    assert "_deferred_confirmed: list[" in source


class PerCorrelationUnreadableStores(UnreadableJournalStores):
    """Like `UnreadableJournalStores`, but only the listed correlations are unreadable."""

    def __init__(self) -> None:
        super().__init__()
        self.unreadable_ids: set[str] = set()

    def journal_for_correlation(self, correlation_id: str) -> list[Any]:
        if self.unreadable or correlation_id in self.unreadable_ids:
            raise ConnectionError("journal unreadable for " + correlation_id)
        return InMemoryShadowStores.journal_for_correlation(self, correlation_id)


def test_an_adoption_is_not_lost_when_a_later_entry_of_the_same_sweep_raises() -> None:
    stores = PerCorrelationUnreadableStores()
    rig = CoreRig(DEMO_CONFIRM_PROFILE, stores=stores)
    entries = (rig.issue(1), rig.issue(2))
    # Both CONFIRM appends commit and raise; neither press can read the journal back.
    stores.unreadable = True
    for n, entry in enumerate(entries, start=1):
        with pytest.raises(ConnectionError):
            rig.confirm(entry, correlation=f"cbq:c{n}")
    stores.raise_after_confirm_write = False
    stores.unreadable = False
    stores.unreadable_ids = {DEMO_CONFIRM_PROFILE.correlation("apr-2")}  # only the second

    rig.now = T_ISSUE + timedelta(seconds=TTL + 1)
    with pytest.raises(ConnectionError, match="apr-2"):
        rig.book.expire_due(rig.now)
    # apr-1 was adopted before apr-2 raised: its CONFIRM still reached the hook, once.
    assert [call[0].approval_id for call in rig.hook_calls] == ["apr-1"]

    stores.unreadable_ids = set()
    rig.book.expire_due(rig.now + timedelta(seconds=1))
    assert [call[0].approval_id for call in rig.hook_calls] == ["apr-1", "apr-2"]


# --------------------------------------------------------------------------- #
# Task 3: the D-10 refusal matrix at core level. Nothing reaches on_confirmed except one valid
# CONFIRM by the approving user, inside the TTL and the plan expiry, after the re-check.
# --------------------------------------------------------------------------- #


def _terminal_events(rig: CoreRig) -> list[Any]:
    terminal = set(rig.profile.terminal_events)
    return [e for e in rig.stores.journal if e.event_type in terminal]


def test_matrix_a_valid_confirm_is_confirmed_once_with_the_confirm_actor_journaled() -> None:
    rig = CoreRig(DEMO_CONFIRM_PROFILE)
    entry = rig.issue()
    rig.now = T_ISSUE + timedelta(seconds=10)
    result = rig.confirm(entry)

    assert result.outcome is ConfirmOutcome.CONFIRMED and not result.replayed
    assert len(rig.hook_calls) == 1
    approval, plan, at = rig.hook_calls[0]
    assert (approval.approval_id, plan.trade_plan_id, at) == (
        "apr-1",
        entry.plan.trade_plan_id,
        rig.now,
    )
    (confirmed,) = rig.journal("DEMO_CONFIRMED")
    body = _payload(confirmed)
    assert body["approving_user_id"] == str(USER_ID)  # the CONFIRM actor (D-03)
    assert body["mode"] == "DEMO"
    assert body["plan_hash"] == entry.plan.plan_hash
    assert rig.recheck_calls == 1
    assert [e.event_type for e in _terminal_events(rig)] == ["DEMO_CONFIRMED"]


def test_matrix_a_double_tap_replays_the_outcome_and_never_calls_the_hook_twice() -> None:
    rig = CoreRig(DEMO_CONFIRM_PROFILE)
    entry = rig.issue()
    first = rig.confirm(entry, correlation="cbq:tap-1")
    second = rig.confirm(entry, correlation="cbq:tap-2")  # a new press, same user

    assert first.outcome is ConfirmOutcome.CONFIRMED and not first.replayed
    assert second.outcome is ConfirmOutcome.CONFIRMED and second.replayed
    assert len(rig.hook_calls) == 1
    assert len(rig.journal("DEMO_CONFIRMED")) == 1


def test_matrix_a_replayed_confirm_with_the_same_correlation_writes_nothing_more() -> None:
    rig = CoreRig(DEMO_CONFIRM_PROFILE)
    entry = rig.issue()
    rig.confirm(entry, correlation="cbq:same")
    rows_before = list(rig.stores.journal)
    again = rig.confirm(entry, correlation="cbq:same")

    assert again.outcome is ConfirmOutcome.CONFIRMED and again.replayed
    assert rig.stores.journal == rows_before
    assert len(rig.hook_calls) == 1


def test_matrix_a_confirm_after_the_ttl_is_expired_and_never_reaches_the_hook() -> None:
    rig = CoreRig(DEMO_CONFIRM_PROFILE)
    entry = rig.issue()
    # The boundary is inclusive: at issued_at + 60 s the token is already dead.
    result = rig.confirm(entry, at=T_ISSUE + timedelta(seconds=TTL))

    assert result.outcome is ConfirmOutcome.EXPIRED_TTL
    assert result.reason == "CONFIRM_TTL_ELAPSED"
    assert rig.hook_calls == []
    (expired,) = rig.journal("DEMO_CONFIRM_EXPIRED")
    assert _payload(expired)["reason"] == "CONFIRM_TTL_ELAPSED"
    # A later press hits the dead token: journaled, replayed, still no hook.
    later = rig.confirm(entry, at=T_ISSUE + timedelta(seconds=TTL + 5), correlation="cbq:late")
    assert later.replayed and later.outcome is ConfirmOutcome.EXPIRED_TTL
    assert rig.hook_calls == []


def test_matrix_the_last_second_inside_the_ttl_still_confirms() -> None:
    rig = CoreRig(DEMO_CONFIRM_PROFILE)
    entry = rig.issue()
    result = rig.confirm(entry, at=T_ISSUE + timedelta(seconds=TTL - 1))
    assert result.outcome is ConfirmOutcome.CONFIRMED
    assert len(rig.hook_calls) == 1


def test_matrix_a_confirm_by_another_user_is_rejected_and_the_owner_can_still_confirm() -> None:
    rig = CoreRig(DEMO_CONFIRM_PROFILE)
    entry = rig.issue()
    refused = rig.confirm(entry, user=OTHER_USER_ID, correlation="cbq:other")

    assert refused.outcome is ConfirmOutcome.REJECTED_USER_MISMATCH
    assert rig.hook_calls == []
    (rejected,) = rig.journal("DEMO_CONFIRM_REJECTED")
    body = _payload(rejected)
    assert body["reason"] == "USER_MISMATCH"
    assert body["presented_user_id"] == str(OTHER_USER_ID)
    assert _terminal_events(rig) == []  # not terminal: the token is still usable by its owner
    assert entry.state is ConfirmState.PENDING

    ok = rig.confirm(entry, correlation="cbq:owner")
    assert ok.outcome is ConfirmOutcome.CONFIRMED
    assert len(rig.hook_calls) == 1


def test_matrix_a_press_without_a_user_id_is_a_user_mismatch() -> None:
    rig = CoreRig(DEMO_CONFIRM_PROFILE)
    result = rig.confirm(rig.issue(), user=None)
    assert result.outcome is ConfirmOutcome.REJECTED_USER_MISMATCH
    assert rig.hook_calls == []


def test_matrix_a_confirm_from_another_chat_is_rejected() -> None:
    rig = CoreRig(DEMO_CONFIRM_PROFILE)
    result = rig.confirm(rig.issue(), chat_id=CHAT_ID + 1)
    assert result.outcome is ConfirmOutcome.REJECTED_OTHER
    assert result.reason == "CHAT_MISMATCH"
    assert rig.hook_calls == []


def test_matrix_a_confirm_at_or_after_the_plan_expiry_is_refused_and_terminal() -> None:
    rig = CoreRig(DEMO_CONFIRM_PROFILE)
    entry = rig.issue(expiry_utc=T_ISSUE + timedelta(seconds=30))  # inside the 60 s TTL
    result = rig.confirm(entry, at=T_ISSUE + timedelta(seconds=30))  # inclusive boundary

    assert result.outcome is ConfirmOutcome.REJECTED_PLAN_EXPIRED
    assert rig.hook_calls == []
    assert entry.state is ConfirmState.EXPIRED
    (expired,) = rig.journal("DEMO_CONFIRM_EXPIRED")
    assert _payload(expired)["reason"] == RejectionReason.APPROVAL_EXPIRED.value
    assert rig.recheck_calls == 0  # the binding gate refuses before the re-check runs


def test_matrix_a_recheck_refusal_is_terminal_and_never_reaches_the_hook() -> None:
    rig = CoreRig(DEMO_CONFIRM_PROFILE, recheck=lambda s, p, n: "MARK_PRICE_CROSSED_STOP")
    entry = rig.issue()
    result = rig.confirm(entry)

    assert result.outcome is ConfirmOutcome.REJECTED_OTHER
    assert result.reason == "MARK_PRICE_CROSSED_STOP"
    assert rig.hook_calls == []
    assert entry.state is ConfirmState.EXPIRED
    (expired,) = rig.journal("DEMO_CONFIRM_EXPIRED")
    body = _payload(expired)
    assert body["reason"] == "MARK_PRICE_CROSSED_STOP"
    assert body["rejected_at_confirm"] is True
    # The refusal is final: a second press replays it.
    again = rig.confirm(entry, correlation="cbq:again")
    assert again.replayed and again.outcome is ConfirmOutcome.REJECTED_OTHER
    assert rig.hook_calls == []


def test_matrix_a_recheck_that_raises_fails_closed_as_recheck_error() -> None:
    def broken(signal: Signal, plan: TradePlan, now_utc: Any) -> str | None:
        raise RuntimeError("price feed down")

    rig = CoreRig(DEMO_CONFIRM_PROFILE, recheck=broken)
    result = rig.confirm(rig.issue())
    assert result.outcome is ConfirmOutcome.REJECTED_OTHER
    assert result.reason == "RECHECK_ERROR"
    assert rig.hook_calls == []


def test_matrix_a_stale_plan_hash_is_refused_by_the_binding_gate() -> None:
    rig = CoreRig(DEMO_CONFIRM_PROFILE)
    entry = rig.issue(request_hash="e" * 64)  # the approval was granted for another plan hash
    result = rig.confirm(entry)
    assert result.outcome is ConfirmOutcome.REJECTED_OTHER
    assert result.reason == RejectionReason.STALE_SETUP.value
    assert rig.hook_calls == []


def test_matrix_cancel_is_journaled_by_the_approving_user_and_never_reaches_the_hook() -> None:
    rig = CoreRig(DEMO_CONFIRM_PROFILE)
    entry = rig.issue()
    result = rig.cancel(entry)

    assert result.outcome is ConfirmOutcome.CANCELLED
    (cancelled,) = rig.journal("DEMO_CONFIRM_CANCELLED")
    assert _payload(cancelled)["approving_user_id"] == str(USER_ID)
    assert _payload(cancelled)["mode"] == "DEMO"
    assert rig.hook_calls == []
    # A CONFIRM after the CANCEL cannot flip it.
    after = rig.confirm(entry, correlation="cbq:after-cancel")
    assert after.outcome is ConfirmOutcome.CANCELLED and after.replayed
    assert rig.hook_calls == []


def test_matrix_a_cancel_by_another_user_is_rejected() -> None:
    rig = CoreRig(DEMO_CONFIRM_PROFILE)
    entry = rig.issue()
    result = rig.cancel(entry, user=OTHER_USER_ID)
    assert result.outcome is ConfirmOutcome.REJECTED_USER_MISMATCH
    assert rig.journal("DEMO_CONFIRM_CANCELLED") == []
    assert entry.state is ConfirmState.PENDING


def test_matrix_a_restart_expires_every_outstanding_confirm_with_runtime_restart() -> None:
    rig = CoreRig(DEMO_CONFIRM_PROFILE)
    rig.issue()  # ISSUED is journaled; the raw token lives in this process only
    fresh = ConfirmBook(
        rig.stores,
        profile=DEMO_CONFIRM_PROFILE,
        clock=lambda: rig.now,
        card_renderer=_card(DEMO_CONFIRM_PROFILE),
        on_confirmed=rig._hook,
    )
    swept = fresh.expire_on_restart(T_ISSUE + timedelta(seconds=5))

    assert swept == ["apr-1"]
    (expired,) = rig.journal("DEMO_CONFIRM_EXPIRED")
    body = _payload(expired)
    assert body["reason"] == "RUNTIME_RESTART" and body["swept"] is True
    assert body["mode"] == "DEMO"
    assert rig.hook_calls == []
    assert fresh.expire_on_restart(T_ISSUE + timedelta(seconds=6)) == []  # idempotent
    confirm_core.assert_no_stranded_approvals(
        rig.stores, T_ISSUE + timedelta(seconds=TTL + 1), profile=DEMO_CONFIRM_PROFILE
    )


def test_matrix_a_stranded_approval_is_detected_per_profile() -> None:
    rig = CoreRig(DEMO_CONFIRM_PROFILE)
    rig.approved(1)  # APPROVED, no card, no outcome
    late = T_ISSUE + timedelta(seconds=TTL + 1)
    with pytest.raises(confirm_core.StrandedApprovals):
        confirm_core.assert_no_stranded_approvals(rig.stores, late, profile=DEMO_CONFIRM_PROFILE)
    # The SHADOW names are not the DEMO names: a SHADOW-profile check sees the same gap too.
    with pytest.raises(confirm_core.StrandedApprovals):
        confirm_core.assert_no_stranded_approvals(rig.stores, late, profile=SHADOW_CONFIRM_PROFILE)


def test_matrix_a_missing_user_id_expires_the_confirm_at_once() -> None:
    rig = CoreRig(DEMO_CONFIRM_PROFILE)
    entry = rig.issue(user=None)
    assert entry.state is ConfirmState.EXPIRED
    assert entry.reason == "USER_ID_UNAVAILABLE"
    # Nobody can confirm: the bound id (-1) matches no Telegram user.
    assert rig.confirm(entry).outcome is ConfirmOutcome.REJECTED_USER_MISMATCH
    assert rig.hook_calls == []


def test_the_live_profile_confirms_through_the_same_path_with_live_names() -> None:
    rig = CoreRig(LIVE_CONFIRM_PROFILE)
    entry = rig.issue()
    result = rig.confirm(entry)

    assert result.outcome is ConfirmOutcome.CONFIRMED
    assert len(rig.hook_calls) == 1
    (confirmed,) = rig.journal("LIVE_CONFIRMED")
    assert _payload(confirmed)["mode"] == "LIVE"
    assert confirmed.entity_type == "LiveConfirm"
    assert rig.journal("DEMO_CONFIRMED") == [] and rig.journal("SHADOW_CONFIRMED") == []


def test_the_hook_is_the_only_seam_a_book_without_a_hook_confirms_and_places_nothing() -> None:
    rig = CoreRig(LIVE_CONFIRM_PROFILE)
    rig.book._on_confirmed = None  # type: ignore[attr-defined]
    result = rig.confirm(rig.issue())
    assert result.outcome is ConfirmOutcome.CONFIRMED
    assert rig.hook_calls == []
