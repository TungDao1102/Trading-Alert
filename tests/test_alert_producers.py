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
