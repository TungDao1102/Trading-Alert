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
from src.domain.enums import ApprovalAction, ApprovalResult
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.paper import shadow, shadow_confirm

from tests.shadow_fakes import (
    CHAT_ID,
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

    def approved(self, n: int = 1, **plan_overrides: Any) -> tuple[Signal, TradePlan, Approval]:
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
            "request_hash": plan.plan_hash,
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

    def issue(self, n: int = 1, *, user: int | None = USER_ID) -> ConfirmEntry:
        """Approve plan n and issue its confirm card (delivered through the edit path)."""
        signal, plan, approval = self.approved(n)
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
