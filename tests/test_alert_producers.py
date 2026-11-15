"""OPS-05 alert producers on the plan 20-13 sink (Phase 20, plan 20-22; D-23, D-24, T-G).

Evidence label: executed tests with fakes (a fake exchange adapter, an in-memory journal and the
real `JournalFirstAlertSink`). No Telegram call is made and nothing here is `[DEMO]`.

Task 1 (tracer): the entry path's SAFE_MODE reasons reach the sink through the controller's
`on_enter` observer.
Task 2: PROTECTIVE_REJECTED, DUPLICATE_EXECUTION_ATTEMPT and MANUAL_CLOSE_ORPHAN_UNVERIFIED.
"""

from __future__ import annotations

import ast
import json
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from src.ops.alerts import (
    DEDICATED_PRODUCER_REASONS,
    JournalFirstAlertSink,
    OperationalAlert,
    SafeModeAlertObserver,
)
from src.reconcile.safe_mode import SafeModeController

from tests.support.execution_limits import test_only_execution_limits as make_test_limits
from tests.support.reconcile_doubles import RecordingJournal

NOW = datetime(2026, 9, 19, 0, 0, 0, tzinfo=UTC)
SAFE_MODE_SOURCE = Path(__file__).resolve().parents[1] / "src" / "reconcile" / "safe_mode.py"


class _NoAdapter:
    """The controller never reads the exchange on an entry; any call is a failure."""


class Rig:
    """A real sink on a recording journal, and a real controller observed by it."""

    def __init__(self) -> None:
        self.journal = RecordingJournal()
        self.queue: deque[OperationalAlert] = deque()
        self.sink = JournalFirstAlertSink(
            journal=self.journal, spill=None, limits=make_test_limits(), queue=self.queue
        )
        self.safe_mode_journal = RecordingJournal()
        self.controller = SafeModeController(
            adapter=_NoAdapter(),  # type: ignore[arg-type]
            journal=self.safe_mode_journal,
            on_enter=SafeModeAlertObserver(self.sink),
        )

    def alert_rows(self) -> list[dict[str, Any]]:
        return [
            json.loads(e.payload_json)
            for e in self.journal.events
            if e.event_type == "OPERATIONAL_ALERT"
        ]

    def queued(self) -> list[tuple[str, str]]:
        return [(a.event, a.reason) for a in self.queue]


# --------------------------------------------------------------------------- #
# Task 1 (tracer): ENTRY_STATE_UNKNOWN from the entry path reaches the sink.
# --------------------------------------------------------------------------- #


async def test_entry_state_unknown_alerts_once() -> None:
    from tests.test_execution_manager import (
        FakeExecutionAdapter,
        InMemoryExecutionIntentStore,
        _probe,
        _run_plan,
        _status_unknown,
    )

    rig = Rig()
    adapter = FakeExecutionAdapter()
    adapter.entry_exceptions.append(_status_unknown())
    adapter.query_responses.append(_probe(found=False))

    outcome = await _run_plan(
        adapter,
        safe_mode_controller=rig.controller,
        intent_store=InMemoryExecutionIntentStore(),
    )

    assert (outcome.is_no_trade, outcome.reason_code) == (True, "RECONCILIATION_REQUIRED")
    assert rig.controller.entered_reason == "ENTRY_STATE_UNKNOWN"
    # One alert: journaled (OPERATIONAL_ALERT row) and queued, severity CRITICAL, fixed reason.
    rows = rig.alert_rows()
    assert [(r["event"], r["severity"], r["reason"]) for r in rows] == [
        ("ENTRY_STATE_UNKNOWN", "CRITICAL", "ENTRY_STATE_UNKNOWN")
    ]
    assert rows[0]["subject"] == "SYSTEM"
    assert rig.queued() == [("ENTRY_STATE_UNKNOWN", "ENTRY_STATE_UNKNOWN")]
    # The entry was sent once and never again (Q5): the alert changed nothing in the flow.
    assert [c["method"] for c in adapter.calls].count("place_entry") == 1


def test_a_reentry_with_a_new_reason_alerts_and_the_same_reason_again_does_not() -> None:
    rig = Rig()
    rig.controller.enter_safe_mode(reason="ENTRY_STATE_UNKNOWN", now_utc=NOW)
    rig.controller.enter_safe_mode(reason="DB_FAILURE", now_utc=NOW + timedelta(seconds=1))
    rig.controller.enter_safe_mode(reason="DB_FAILURE", now_utc=NOW + timedelta(seconds=2))

    assert rig.queued() == [
        ("ENTRY_STATE_UNKNOWN", "ENTRY_STATE_UNKNOWN"),
        ("DB_FAILURE", "DB_FAILURE"),
    ]


def test_protection_handoff_failed_alerts_as_its_own_event() -> None:
    rig = Rig()
    rig.controller.enter_safe_mode(reason="PROTECTION_HANDOFF_FAILED", now_utc=NOW)

    assert rig.queued() == [("PROTECTION_HANDOFF_FAILED", "PROTECTION_HANDOFF_FAILED")]


def test_a_dedicated_producer_reason_fires_no_observer_alert() -> None:
    rig = Rig()
    rig.controller.enter_safe_mode(reason="CLOSE_REQUIRED", now_utc=NOW)

    assert rig.controller.in_safe_mode is True
    assert rig.queued() == []
    assert rig.alert_rows() == []


@pytest.mark.parametrize(
    "reason",
    ["RESTORE_INCONSISTENT", "SAFE_MODE_STATE_UNREADABLE", "PROTECTION_STATE_INVALID"],
)
def test_a_reason_without_a_dedicated_producer_alerts_safe_mode_entered(reason: str) -> None:
    rig = Rig()
    rig.controller.enter_safe_mode(reason=reason, now_utc=NOW)

    assert rig.queued() == [("SAFE_MODE_ENTERED", reason)]
    assert rig.alert_rows()[0]["severity"] == "HIGH"


def test_the_fallback_alert_repeats_once_per_episode() -> None:
    rig = Rig()
    rig.controller.enter_safe_mode(reason="RESTORE_INCONSISTENT", now_utc=NOW)
    rig.controller.enter_safe_mode(reason="RESTORE_INCONSISTENT", now_utc=NOW)

    assert rig.queued() == [("SAFE_MODE_ENTERED", "RESTORE_INCONSISTENT")]


def test_a_reason_that_is_not_a_code_never_carries_text_into_the_alert() -> None:
    rig = Rig()
    rig.controller.enter_safe_mode(reason="postgres://user:secret@host/db", now_utc=NOW)

    assert rig.queued() == [("SAFE_MODE_ENTERED", "INVALID_REASON")]


def test_an_unreadable_state_store_at_start_alerts_safe_mode_entered_once() -> None:
    class _UnreadableStore:
        def save(self, state: Any, *, now_utc: datetime) -> None:  # pragma: no cover - unused
            raise AssertionError("not called")

        def load(self) -> Any:
            raise RuntimeError("postgres://user:secret@host/db")

    sink_rig = Rig()
    controller = SafeModeController.load(
        adapter=_NoAdapter(),  # type: ignore[arg-type]
        journal=RecordingJournal(),
        state_store=_UnreadableStore(),
        now_utc=NOW,
        on_enter=SafeModeAlertObserver(sink_rig.sink),
    )

    assert controller.entered_reason == "SAFE_MODE_STATE_UNREADABLE"
    assert sink_rig.queued() == [("SAFE_MODE_ENTERED", "SAFE_MODE_STATE_UNREADABLE")]
    assert "secret" not in json.dumps(sink_rig.alert_rows())


def test_a_raising_observer_does_not_undo_the_flip_the_journal_row_or_the_save() -> None:
    class _Store:
        def __init__(self) -> None:
            self.saved: list[dict[str, Any]] = []

        def save(self, state: Any, *, now_utc: datetime) -> None:
            self.saved.append(dict(state))

        def load(self) -> Any:
            return None

    calls: list[str] = []

    def _boom(reason: str, now_utc: datetime) -> None:
        calls.append(reason)
        raise RuntimeError("observer down")

    journal = RecordingJournal()
    store = _Store()
    controller = SafeModeController(
        adapter=_NoAdapter(),  # type: ignore[arg-type]
        journal=journal,
        state_store=store,
        on_enter=_boom,
    )

    controller.enter_safe_mode(reason="ENTRY_STATE_UNKNOWN", now_utc=NOW)

    assert calls == ["ENTRY_STATE_UNKNOWN"]
    assert controller.in_safe_mode is True
    assert [e.event_type for e in journal.events] == ["SAFE_MODE_ENTER"]
    assert [s["entered_reason"] for s in store.saved] == ["ENTRY_STATE_UNKNOWN"]


def test_a_failing_save_propagates_and_the_operator_is_still_told() -> None:
    class _BadStore:
        def save(self, state: Any, *, now_utc: datetime) -> None:
            raise RuntimeError("db down")

        def load(self) -> Any:
            return None

    calls: list[str] = []
    controller = SafeModeController(
        adapter=_NoAdapter(),  # type: ignore[arg-type]
        journal=RecordingJournal(),
        state_store=_BadStore(),
        on_enter=lambda reason, now: calls.append(reason),
    )

    with pytest.raises(RuntimeError):
        controller.enter_safe_mode(reason="ENTRY_STATE_UNKNOWN", now_utc=NOW)

    # The flag is set (fail closed) and the operator hears about it even though the store is down.
    assert controller.in_safe_mode is True
    assert calls == ["ENTRY_STATE_UNKNOWN"]


def test_the_dedicated_producer_set_covers_every_divergence_safe_mode_reason() -> None:
    from src.reconcile.classify import POLICY_BY_KIND

    for policy in POLICY_BY_KIND.values():
        assert policy.safe_mode_reason in DEDICATED_PRODUCER_REASONS
    for reason in (
        "CLOSE_REQUIRED",
        "EMERGENCY_CLOSE_FAILED",
        "ENTRY_WITHOUT_PROTECTIVE",
        "STALE_FEED",
        "AUTH_FAILURE",
        "USER_DATA_STREAM_HALTED",
        "API_DEGRADATION",
        "SYMBOL_OWNERSHIP_CONFLICT",
    ):
        assert reason in DEDICATED_PRODUCER_REASONS
    # The three entry-path reasons have their own events, so they are not "dedicated" here.
    for reason in ("ENTRY_STATE_UNKNOWN", "PROTECTION_HANDOFF_FAILED", "DB_FAILURE"):
        assert reason not in DEDICATED_PRODUCER_REASONS


def test_safe_mode_py_imports_nothing_from_src_ops() -> None:
    tree = ast.parse(SAFE_MODE_SOURCE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    assert [m for m in imported if m.startswith("src.ops")] == []


# --------------------------------------------------------------------------- #
# Task 2: PROTECTIVE_REJECTED, DUPLICATE_EXECUTION_ATTEMPT, MANUAL_CLOSE_ORPHAN_UNVERIFIED.
# --------------------------------------------------------------------------- #


async def test_a_definitively_rejected_stop_alerts_close_required_then_protective_rejected() -> (
    None
):
    from decimal import Decimal

    from tests.support.protection_doubles import TEST_ONLY_PLAN_HASH, make_rig

    rig = await make_rig(real_closer=True)
    rig.fake.reject_next_algo(-2021)
    rig.coordinator.fill_sink(rig.stream_fill(Decimal("0.004")))

    await rig.coordinator.step()
    await rig.coordinator.step()
    await rig.coordinator.step()

    # In this order, once per plan; the handoff alert is a different event and is not raised.
    assert [(a.event, a.reason, a.plan_hash) for a in rig.alerts.alerts] == [
        ("CLOSE_REQUIRED", "B5_STOP_REJECTED", TEST_ONLY_PLAN_HASH),
        ("PROTECTIVE_REJECTED", "B5_STOP_REJECTED", TEST_ONLY_PLAN_HASH),
    ]
    assert rig.safe_mode.entered_reasons == ["CLOSE_REQUIRED"]
    # The close flow ran: exactly one reduce-only MARKET close went out and the stop is not re-sent.
    assert len(rig.fake.calls_to("place_market_close")) == 1
    assert len(rig.fake.calls_to("place_algo_protective")) == 1


async def test_a_failing_protective_rejected_alert_does_not_stop_the_close() -> None:
    from decimal import Decimal

    from tests.support.protection_doubles import make_rig

    rig = await make_rig(real_closer=True)
    original = rig.alerts.critical

    def _critical(**kwargs: Any) -> None:
        original(**kwargs)
        if kwargs["event"] == "PROTECTIVE_REJECTED":
            raise RuntimeError("sink down")

    rig.alerts.critical = _critical  # type: ignore[method-assign]
    rig.fake.reject_next_algo(-2021)
    rig.coordinator.fill_sink(rig.stream_fill(Decimal("0.004")))

    await rig.coordinator.step()

    assert len(rig.fake.calls_to("place_market_close")) == 1


async def test_another_close_required_branch_does_not_alert_protective_rejected() -> None:
    from decimal import Decimal

    from tests.support.protection_doubles import TEST_ONLY_PLAN_HASH, make_rig

    # The operator close enters CLOSE_REQUIRED through its own branch (OPERATOR_CLOSE): the
    # PROTECTIVE_REJECTED alert belongs to the B5 branch only.
    rig = await make_rig(closer_results=[False])
    rig.coordinator.fill_sink(rig.stream_fill(Decimal("0.004")))
    await rig.coordinator.step()

    await rig.coordinator.operator_close(
        plan_hash=TEST_ONLY_PLAN_HASH, operator_id="operator_alpha"
    )

    events = [a.event for a in rig.alerts.alerts]
    assert "CLOSE_REQUIRED" in events
    assert "PROTECTIVE_REJECTED" not in events


class _AlertCalls:
    """A duck-typed `.alert(...)` sink that records the calls (replay and manual-close paths)."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail = fail

    def alert(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        if self._fail:
            raise RuntimeError("sink down")


async def test_a_second_call_for_an_executed_approval_alerts_a_duplicate_and_sends_nothing() -> (
    None
):
    from tests.test_execution_manager import (
        FakeExecutionAdapter,
        InMemoryExecutionIntentStore,
        _build_live_context,
        _load_input,
        _run_plan,
    )

    case = _load_input()
    store = InMemoryExecutionIntentStore()
    sink = _AlertCalls()
    first = await _run_plan(
        FakeExecutionAdapter(),
        intent_store=store,
        live_context=_build_live_context(case, alert_sink=sink),
    )
    assert first.is_no_trade is False
    assert sink.calls == []  # a first execution is not a duplicate

    replay_adapter = FakeExecutionAdapter()
    replay = await _run_plan(
        replay_adapter,
        intent_store=store,
        live_context=_build_live_context(case, alert_sink=sink),
    )

    assert replay == first
    assert replay_adapter.calls == []
    (call,) = sink.calls
    assert call["event"] == "DUPLICATE_EXECUTION_ATTEMPT"
    assert call["reason"] == "STORED_OUTCOME_REPLAY"
    assert call["subject"] == call["plan_hash"]
    assert len(call["plan_hash"]) == 64


async def test_a_redelivered_callback_is_deduped_by_the_alert_window() -> None:
    from tests.test_execution_manager import (
        FakeExecutionAdapter,
        InMemoryExecutionIntentStore,
        _build_live_context,
        _load_input,
        _run_plan,
    )

    case = _load_input()
    store = InMemoryExecutionIntentStore()
    real = JournalFirstAlertSink(
        journal=RecordingJournal(), spill=None, limits=make_test_limits(), queue=deque()
    )
    await _run_plan(FakeExecutionAdapter(), intent_store=store)
    for _ in range(3):
        adapter = FakeExecutionAdapter()
        await _run_plan(
            adapter,
            intent_store=store,
            live_context=_build_live_context(case, alert_sink=real),
        )
        assert adapter.calls == []

    assert [(a.event, a.reason) for a in real.queue] == [
        ("DUPLICATE_EXECUTION_ATTEMPT", "STORED_OUTCOME_REPLAY")
    ]


async def test_losing_the_consume_race_alerts_a_duplicate_too() -> None:
    from tests.test_execution_manager import (
        FakeExecutionAdapter,
        InMemoryExecutionIntentStore,
        _build_live_context,
        _load_input,
        _run_plan,
    )

    case = _load_input()
    real_store = InMemoryExecutionIntentStore()
    await _run_plan(FakeExecutionAdapter(), intent_store=real_store)

    class _RaceLostStore:
        """The first lookup finds nothing; the consume loses; the second lookup finds the row."""

        def __init__(self) -> None:
            self.lookups = 0

        def __getattr__(self, name: str) -> Any:
            return getattr(real_store, name)

        def get_entry(self, *, approval_id: str) -> Any:
            self.lookups += 1
            return None if self.lookups == 1 else real_store.get_entry(approval_id=approval_id)

        def consume_and_record_entry_intent(self, **kwargs: Any) -> bool:
            return False

    sink = _AlertCalls()
    adapter = FakeExecutionAdapter()
    outcome = await _run_plan(
        adapter,
        intent_store=_RaceLostStore(),
        live_context=_build_live_context(case, alert_sink=sink),
    )

    assert outcome.is_no_trade is False  # the stored outcome of the winner
    assert "place_entry" not in [c["method"] for c in adapter.calls]
    (call,) = sink.calls
    assert (call["event"], call["reason"]) == ("DUPLICATE_EXECUTION_ATTEMPT", "CONSUME_RACE_LOST")


async def test_without_an_alert_sink_or_with_a_failing_one_the_replay_outcome_is_unchanged() -> (
    None
):
    from tests.test_execution_manager import (
        FakeExecutionAdapter,
        InMemoryExecutionIntentStore,
        _build_live_context,
        _load_input,
        _run_plan,
    )

    case = _load_input()
    store = InMemoryExecutionIntentStore()
    first = await _run_plan(FakeExecutionAdapter(), intent_store=store)
    quiet = await _run_plan(FakeExecutionAdapter(), intent_store=store)
    failing = _AlertCalls(fail=True)
    loud = await _run_plan(
        FakeExecutionAdapter(),
        intent_store=store,
        live_context=_build_live_context(case, alert_sink=failing),
    )

    assert quiet == first == loud
    assert len(failing.calls) == 1


def test_live_context_alert_sink_defaults_to_none_and_must_offer_alert() -> None:
    from tests.test_execution_manager import _build_live_context, _load_input

    case = _load_input()
    assert _build_live_context(case).alert_sink is None
    with pytest.raises(TypeError):
        _build_live_context(case, alert_sink=object())


async def test_a_manual_close_with_an_unverifiable_leg_alerts_the_orphan() -> None:
    from tests.test_manual_controls import (
        PLAN_HASH,
        SL_ID,
        SYMBOL,
        ScriptedFake,
        _close,
        _resting_entry_with_legs,
    )

    fake = ScriptedFake()
    await _resting_entry_with_legs(fake)
    fake.unreadable_algo_ids = {SL_ID}
    sink = _AlertCalls()

    await _close(fake, RecordingJournal(), alert_sink=sink)

    (call,) = sink.calls
    assert call["event"] == "MANUAL_CLOSE_ORPHAN_UNVERIFIED"
    assert call["subject"] == SYMBOL
    assert call["plan_hash"] == PLAN_HASH
    assert call["reason"] == "LEGS_NOT_PROVEN_GONE"


async def test_a_manual_close_that_proves_the_legs_gone_alerts_nothing() -> None:
    from tests.test_manual_controls import ScriptedFake, _close, _resting_entry_with_legs

    fake = ScriptedFake()
    await _resting_entry_with_legs(fake)
    sink = _AlertCalls()

    await _close(fake, RecordingJournal(), alert_sink=sink)

    assert sink.calls == []


async def test_a_failing_orphan_alert_does_not_change_the_manual_close() -> None:
    from tests.test_manual_controls import SL_ID, ScriptedFake, _close, _resting_entry_with_legs

    fake = ScriptedFake()
    await _resting_entry_with_legs(fake)
    fake.unreadable_algo_ids = {SL_ID}
    journal = RecordingJournal()
    sink = _AlertCalls(fail=True)

    enablement, safe_mode = await _close(fake, journal, alert_sink=sink)

    assert len(sink.calls) == 1
    assert enablement.disabled is True
    assert safe_mode.reasons == ["MANUAL_CLOSE"]
    assert [e.event_type for e in journal.events].count("MANUAL_CLOSE_ORPHAN_UNVERIFIED") == 1
