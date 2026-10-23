"""OPS-05 acceptance matrix (Phase 20, plan 20-22; T-G, D-23, D-24).

Evidence label: executed tests with a fake journal and the real `JournalFirstAlertSink`, plus
AST scans of the producer modules. No Telegram call is made and nothing here is `[DEMO]`.

One parametrized case per OPS-05 alert listed in REQUIREMENTS.md plus the D-24 entry-path rows.
DAILY_STOP and DAILY_LOSS_WARNING have a contract and a test trigger only (the producer is
Phase 21): a test trigger is not end-to-end coverage, and OPS-05 is NOT complete end-to-end here.
"""

from __future__ import annotations

import ast
import inspect
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from src.domain.enums import DailyState
from src.execution.protection import CriticalAlertSink
from src.ops.alerts import (
    ALERT_EVENTS,
    OPS05_MATRIX,
    JournalFirstAlertSink,
    Ops05Row,
    emit_daily_state_alert,
)
from src.reconcile.loop import ReconcileAlertSink

from tests.support.execution_limits import test_only_execution_limits as make_test_limits
from tests.support.reconcile_doubles import RecordingJournal

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 19, 0, 0, 0, tzinfo=UTC)
SINK_BEHAVIOR = "dedupe window + bounded message retry; orders never retried"

# The alerts REQUIREMENTS.md OPS-05 names, as the events that carry them.
OPS05_REQUIREMENT_EVENTS: dict[str, tuple[str, ...]] = {
    "an unprotected position": ("UNPROTECTED_POSITION", "CLOSE_REQUIRED"),
    "local versus exchange divergence": ("DIVERGENCE",),
    "an unknown or foreign order": ("UNKNOWN_ORDER", "FOREIGN_ORDER"),
    "a duplicate execution attempt": ("DUPLICATE_EXECUTION_ATTEMPT",),
    "stale data": ("STALE_DATA",),
    "a rejected protective action": ("PROTECTIVE_REJECTED",),
    "an authentication failure": ("AUTH_FAILURE",),
    "daily-loss WARNING": ("DAILY_LOSS_WARNING",),
    "DAILY_STOP": ("DAILY_STOP",),
}
D24_EVENTS = ("ENTRY_STATE_UNKNOWN", "PROTECTION_HANDOFF_FAILED", "DB_FAILURE")
# Plan 20-28 (owner request 2026-10-23): the stale resting entry alert is not an OPS-05 phrase and
# not a D-24 entry-path reason; it is its own row with its own requirement source.
STALE_ENTRY_EVENTS = ("STALE_ENTRY_ORDER",)
STALE_ENTRY_SOURCE = "owner request 2026-10-23 (stale entry)"
ALL_ROW_EVENTS = (
    [e for events in OPS05_REQUIREMENT_EVENTS.values() for e in events]
    + list(D24_EVENTS)
    + list(STALE_ENTRY_EVENTS)
)


def _row(alert: str) -> Ops05Row:
    rows = [r for r in OPS05_MATRIX if r.alert == alert]
    assert len(rows) == 1, alert
    return rows[0]


def _string_constants(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
    return names


def _sink() -> tuple[JournalFirstAlertSink, RecordingJournal, deque[Any]]:
    journal = RecordingJournal()
    queue: deque[Any] = deque()
    sink = JournalFirstAlertSink(
        journal=journal, spill=None, limits=make_test_limits(), queue=queue
    )
    return sink, journal, queue


# --------------------------------------------------------------------------- #
# The matrix itself.
# --------------------------------------------------------------------------- #


def test_the_matrix_has_exactly_one_row_per_ops05_alert_and_per_d24_entry_path_reason() -> None:
    assert sorted(r.alert for r in OPS05_MATRIX) == sorted(ALL_ROW_EVENTS)


def test_every_requirement_phrase_is_still_in_requirements_md_ops05() -> None:
    text = (ROOT / ".planning" / "REQUIREMENTS.md").read_text(encoding="utf-8")
    line = next(
        entry for entry in text.splitlines() if entry.startswith("- [") and "**OPS-05**" in entry
    )
    for phrase in OPS05_REQUIREMENT_EVENTS:
        assert phrase in line, phrase


@pytest.mark.parametrize("alert", ALL_ROW_EVENTS)
def test_each_row_is_in_the_event_contract_and_states_its_sink_behavior(alert: str) -> None:
    row = _row(alert)

    assert alert in ALERT_EVENTS
    assert row.journal_first is True
    assert row.dedupe_and_retry == SINK_BEHAVIOR
    assert row.requirement_source in ("OPS-05", "D-24 (entry path)", STALE_ENTRY_SOURCE)
    assert row.phase20_delivers.strip() != ""
    assert row.producer.strip() != ""


@pytest.mark.parametrize("alert", ALL_ROW_EVENTS)
def test_each_row_is_journaled_before_it_is_queued_and_a_repeat_is_deduped(alert: str) -> None:
    sink, journal, queue = _sink()
    order: list[str] = []
    original_record = journal.record

    def _record(event: Any) -> None:
        original_record(event)
        order.append(f"journal:{event.event_type}:{len(queue)}")

    journal.record = _record  # type: ignore[method-assign]

    sink.alert(event=alert, subject="SYSTEM", reason="TEST_REASON", now_utc=NOW)
    sink.alert(
        event=alert, subject="SYSTEM", reason="TEST_REASON", now_utc=NOW + timedelta(seconds=1)
    )

    # The OPERATIONAL_ALERT row was written while the queue was still empty (journal first).
    assert order[0] == "journal:OPERATIONAL_ALERT:0"
    assert [e.event_type for e in journal.events] == ["OPERATIONAL_ALERT", "ALERT_SUPPRESSED"]
    assert [a.event for a in queue] == [alert]


@pytest.mark.parametrize(
    "alert", [e for e in ALL_ROW_EVENTS if _row(e).producer.startswith("src/")]
)
def test_each_named_producer_module_really_emits_the_event(alert: str) -> None:
    row = _row(alert)
    path = ROOT / row.producer

    assert path.is_file(), row.producer
    constants = _string_constants(path)
    imported = _imported_names(path)
    # Either the module owns the event name or it imports the `ALERT_<EVENT>` constant it sends.
    assert alert in constants or f"ALERT_{alert}" in imported, (alert, row.producer)


def test_the_stale_entry_row_is_alert_only_and_produced_by_the_reconcile_loop() -> None:
    row = _row("STALE_ENTRY_ORDER")

    assert row.requirement_source == STALE_ENTRY_SOURCE
    assert row.producer == "src/reconcile/loop.py"
    assert "alert only" in row.phase20_delivers
    assert "nothing is cancelled" in row.phase20_delivers
    assert "NOT_CONFIGURED" in row.phase20_delivers


def test_the_entry_path_reasons_reach_the_sink_through_the_observer_in_alerts_py() -> None:
    constants = _string_constants(ROOT / "src" / "ops" / "alerts.py")

    for reason in D24_EVENTS:
        assert reason in constants
        assert reason in ALERT_EVENTS


# --------------------------------------------------------------------------- #
# Phase 21 parts and the authentication scope.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("alert", ["DAILY_STOP", "DAILY_LOSS_WARNING"])
def test_daily_state_rows_list_only_the_test_trigger_with_phase_21_as_producer(alert: str) -> None:
    row = _row(alert)

    assert row.producer == "Phase 21"
    assert row.phase20_delivers.startswith("contract and test trigger only")
    assert "not end-to-end" in row.phase20_delivers


@pytest.mark.parametrize(
    ("state", "alert"),
    [(DailyState.DAILY_STOP, "DAILY_STOP"), (DailyState.WARNING, "DAILY_LOSS_WARNING")],
)
def test_the_daily_state_test_trigger_pushes_the_alert_through_the_sink(
    state: DailyState, alert: str
) -> None:
    sink, journal, queue = _sink()

    emit_daily_state_alert(sink, state=state, subject="SYSTEM", now_utc=NOW)

    assert [a.event for a in queue] == [alert]
    assert [e.event_type for e in journal.events] == ["OPERATIONAL_ALERT"]


def test_no_production_module_other_than_alerts_py_calls_the_daily_state_trigger() -> None:
    offenders = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "src").rglob("*.py")
        if path.name != "alerts.py" and "emit_daily_state_alert" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_authentication_failure_is_produced_only_by_the_reconcile_tick() -> None:
    row = _row("AUTH_FAILURE")

    assert row.producer == "src/reconcile/loop.py"
    assert "only by the reconcile tick" in row.phase20_delivers
    # The coordinator, the closer and the manager never name the alert event.
    for name in ("protection.py", "emergency_close.py", "manager.py"):
        text = (ROOT / "src" / "execution" / name).read_text(encoding="utf-8")
        assert "AUTH_FAILURE" not in text, name
        assert "ALERT_AUTH_FAILURE" not in text, name


def test_the_module_states_that_ops05_is_not_complete_end_to_end() -> None:
    doc = inspect.getmodule(OPS05_MATRIX[0])
    assert doc is not None and doc.__doc__ is not None
    assert "OPS-05 is NOT complete end-to-end" in doc.__doc__


# --------------------------------------------------------------------------- #
# The duck-typed sink pair (plans 20-12 and 20-13 ran in the same wave).
# --------------------------------------------------------------------------- #


def _shape(function: Any) -> list[tuple[str, Any, Any]]:
    """Parameter name, kind and default of a method, without `self` and annotations."""
    parameters = [p for p in inspect.signature(function).parameters.values() if p.name != "self"]
    return [(p.name, p.kind, p.default) for p in parameters]


def test_journal_first_sink_matches_the_loop_and_coordinator_protocols() -> None:
    assert _shape(JournalFirstAlertSink.alert) == _shape(ReconcileAlertSink.alert)
    assert _shape(JournalFirstAlertSink.critical) == _shape(CriticalAlertSink.critical)
    # The sink also satisfies both protocols structurally at runtime.
    sink, _, queue = _sink()
    reconcile_sink: ReconcileAlertSink = sink
    critical_sink: CriticalAlertSink = sink
    reconcile_sink.alert(
        event="DIVERGENCE", subject="BTCUSDT", reason="UNSYNCED_NORMAL", now_utc=NOW
    )
    critical_sink.critical(
        event="CLOSE_REQUIRED",
        plan_hash="a" * 64,
        symbol="BTCUSDT",
        reason="B2_STOP_UNCONFIRMED",
        now_utc=NOW,
    )
    assert [a.event for a in queue] == ["DIVERGENCE", "CLOSE_REQUIRED"]
