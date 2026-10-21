"""Risk-reducing controls act first and journal afterwards (Phase 20, plan 20-08, D-16, F-702).

A journal or database that always raises must never stop a risk-reducing control: the
action runs, the audit record waits in a local durable spill (one file per record), and
`replay_spill` moves it into the journal later. The spill is supplementary evidence of what
this process did; it is never a substitute for Binance truth (D-30).

Evidence label: executed tests with fakes only. No database, no network, no Binance.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from src.domain.enums import KillGateState
from src.domain.journal import JournalEvent
from src.execution.enablement import LiveEnablementController

from tests.support.ast_guards import float_constructor_calls, wall_clock_calls
from tests.support.reconcile_doubles import FlakyJournal, RaisingJournal, RecordingJournal

NOW_UTC = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
SRC_ROOT = Path(__file__).parent.parent / "src"


def _event(
    *, suffix: str = "a", payload: dict[str, Any] | None = None, at: datetime = NOW_UTC
) -> JournalEvent:
    return JournalEvent(
        journal_event_id=f"unit_test_{suffix}",
        occurred_at_utc=at,
        event_type="UNIT_TEST_EVENT",
        entity_type="UnitTest",
        entity_id=f"entity-{suffix}",
        correlation_id="unit_test_correlation",
        payload_json=json.dumps(payload or {"k": suffix}, separators=(",", ":")),
    )


def _passing_health_verdict() -> Any:
    from src.ops.health import ALL_CHECK_NAMES, HealthCheckResult, run_health_checks

    return run_health_checks(
        results=[
            HealthCheckResult(check_name=name, status="PASS", detail="ok", observed_at_utc=NOW_UTC)
            for name in ALL_CHECK_NAMES
        ]
    )


def _enabled_controller(journal: Any, spill: Any = None) -> LiveEnablementController:
    controller = LiveEnablementController(journal=journal, spill=spill)
    controller.enable(
        operator_id="op-1",
        now_utc=NOW_UTC,
        health_verdict=_passing_health_verdict(),
        kill_gate_state=KillGateState.WITHIN_BUDGET,
    )
    assert controller.is_disabled is False
    return controller


def _spill_files(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.suffix == ".json")


# --------------------------------------------------------------------------- #
# Task 1 (tracer): disable() with a journal that always raises.
# --------------------------------------------------------------------------- #


def test_disable_flips_with_journal_always_raising(tmp_path: Path) -> None:
    """F-702: the flag flips even though the journal is down; the record waits in the spill."""
    from src.ops.spill import LocalSpill

    spill = LocalSpill(tmp_path / "spill")
    good = RecordingJournal()
    controller = _enabled_controller(good, spill)
    # The enable event reached the healthy journal; from here on the journal is down.
    controller._journal = RaisingJournal()  # noqa: SLF001 — swap the journal to simulate an outage

    controller.disable(operator_id="op-1", now_utc=NOW_UTC)

    assert controller.is_disabled is True
    assert controller.guard_placement(plan_hash="x" * 64).is_no_trade is True
    files = _spill_files(tmp_path / "spill")
    assert len(files) == 1
    assert files[0].endswith(".json")
    assert not any(p.name.endswith(".tmp") for p in (tmp_path / "spill").iterdir())
    (record,) = spill.pending()
    assert record.event.event_type == "LIVE_ORDERS_DISABLED"
    assert files[0] == f"{record.event.journal_event_id}.json"


def test_replay_spill_records_the_event_once_and_a_second_replay_is_a_noop(
    tmp_path: Path,
) -> None:
    from src.ops.spill import LocalSpill, replay_spill

    spill = LocalSpill(tmp_path / "spill")
    controller = _enabled_controller(RecordingJournal(), spill)
    controller._journal = RaisingJournal()  # noqa: SLF001
    controller.disable(operator_id="op-1", now_utc=NOW_UTC)

    journal = RecordingJournal()
    first = replay_spill(spill, journal)
    second = replay_spill(spill, journal)

    assert [e.event_type for e in journal.events] == ["LIVE_ORDERS_DISABLED"]
    assert len(first.replayed) == 1
    assert first.conflicts == () and first.corrupt == ()
    assert second.replayed == () and second.already_present == ()
    assert _spill_files(tmp_path / "spill") == []
    assert journal.attempts == 1


def test_disable_without_a_spill_flips_then_raises_audit_record_lost_naming_the_class() -> None:
    from src.ops.risk_first import AuditRecordLost

    controller = _enabled_controller(RecordingJournal())
    controller._journal = RaisingJournal()  # noqa: SLF001

    with pytest.raises(AuditRecordLost) as excinfo:
        controller.disable(operator_id="op-1", now_utc=NOW_UTC)

    assert controller.is_disabled is True
    text = str(excinfo.value)
    assert "StoreUnavailable" in text
    # Class names only: the underlying message text is never copied.
    assert "PostgreSQL unavailable" not in text


def test_disable_with_a_healthy_journal_records_the_same_event_and_leaves_no_spill(
    tmp_path: Path,
) -> None:
    from src.ops.spill import LocalSpill

    spill = LocalSpill(tmp_path / "spill")
    journal = RecordingJournal()
    controller = _enabled_controller(journal, spill)

    controller.disable(operator_id="op-1", now_utc=NOW_UTC)

    assert controller.is_disabled is True
    assert [e.event_type for e in journal.events] == [
        "LIVE_ORDERS_ENABLED",
        "LIVE_ORDERS_DISABLED",
    ]
    payload = json.loads(journal.events[-1].payload_json)
    assert set(payload) == {"operator_id", "live_orders_disabled", "live_orders_disabled_before"}
    assert payload["live_orders_disabled"] is True
    assert payload["live_orders_disabled_before"] is False
    assert _spill_files(tmp_path / "spill") == []


# --------------------------------------------------------------------------- #
# risk_first primitives.
# --------------------------------------------------------------------------- #


def test_record_after_with_a_healthy_journal_writes_no_spill(tmp_path: Path) -> None:
    from src.ops.risk_first import record_after
    from src.ops.spill import LocalSpill

    spill = LocalSpill(tmp_path / "spill")
    journal = RecordingJournal()

    record_after(spill=spill, journal=journal, event=_event())

    assert len(journal.events) == 1
    assert _spill_files(tmp_path / "spill") == []


def test_record_after_spills_when_the_journal_is_down(tmp_path: Path) -> None:
    from src.ops.risk_first import record_after
    from src.ops.spill import LocalSpill

    spill = LocalSpill(tmp_path / "spill")

    record_after(spill=spill, journal=RaisingJournal(), event=_event())

    assert _spill_files(tmp_path / "spill") == ["unit_test_a.json"]


async def test_act_then_record_writes_the_spill_before_the_action_and_clears_it_after(
    tmp_path: Path,
) -> None:
    from src.ops.risk_first import act_then_record
    from src.ops.spill import LocalSpill

    spill = LocalSpill(tmp_path / "spill")
    journal = RecordingJournal()
    seen_during_action: list[list[str]] = []

    async def action() -> str:
        seen_during_action.append(_spill_files(tmp_path / "spill"))
        assert journal.events == []  # nothing waited for the journal before the action
        return "done"

    result = await act_then_record(spill=spill, journal=journal, event=_event(), action=action)

    assert result == "done"
    assert seen_during_action == [["unit_test_a.json"]]
    assert len(journal.events) == 1
    assert _spill_files(tmp_path / "spill") == []


async def test_act_then_record_keeps_the_spill_when_the_journal_is_down(tmp_path: Path) -> None:
    from src.ops.risk_first import act_then_record
    from src.ops.spill import LocalSpill

    spill = LocalSpill(tmp_path / "spill")
    calls: list[str] = []

    async def action() -> None:
        calls.append("ran")

    await act_then_record(spill=spill, journal=RaisingJournal(), event=_event(), action=action)

    assert calls == ["ran"]
    assert _spill_files(tmp_path / "spill") == ["unit_test_a.json"]


async def test_act_then_record_preserves_an_action_exception_and_still_records(
    tmp_path: Path,
) -> None:
    from src.ops.risk_first import act_then_record
    from src.ops.spill import LocalSpill

    spill = LocalSpill(tmp_path / "spill")
    journal = RecordingJournal()

    async def action() -> None:
        raise RuntimeError("exchange said no")

    with pytest.raises(RuntimeError, match="exchange said no"):
        await act_then_record(spill=spill, journal=journal, event=_event(), action=action)

    assert len(journal.events) == 1
    assert _spill_files(tmp_path / "spill") == []


async def test_act_then_record_raises_audit_record_lost_only_after_the_action_succeeded(
    tmp_path: Path,
) -> None:
    from src.ops.risk_first import AuditRecordLost, act_then_record

    calls: list[str] = []

    async def action() -> None:
        calls.append("ran")

    with pytest.raises(AuditRecordLost):
        await act_then_record(spill=None, journal=RaisingJournal(), event=_event(), action=action)
    assert calls == ["ran"]

    # When the action itself failed, its exception wins over the lost audit record.
    async def failing() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await act_then_record(spill=None, journal=RaisingJournal(), event=_event(), action=failing)


async def test_act_then_record_survives_a_spill_that_cannot_be_written(tmp_path: Path) -> None:
    """A spill failure is remembered, never raised: the action still runs."""
    from src.ops.risk_first import act_then_record
    from src.ops.spill import LocalSpill

    blocker = tmp_path / "not-a-directory"
    blocker.write_text("file in the way", encoding="utf-8")
    spill = LocalSpill.__new__(LocalSpill)
    spill._directory = blocker  # noqa: SLF001 — a directory path that is really a file
    calls: list[str] = []
    journal = RecordingJournal()

    async def action() -> None:
        calls.append("ran")

    await act_then_record(spill=spill, journal=journal, event=_event(), action=action)

    assert calls == ["ran"]
    assert len(journal.events) == 1


def test_flaky_journal_record_after_spills_then_replay_completes(tmp_path: Path) -> None:
    from src.ops.risk_first import record_after
    from src.ops.spill import LocalSpill, replay_spill

    spill = LocalSpill(tmp_path / "spill")
    journal = FlakyJournal(fail_times=1)

    record_after(spill=spill, journal=journal, event=_event())
    assert _spill_files(tmp_path / "spill") == ["unit_test_a.json"]

    report = replay_spill(spill, journal)

    assert report.replayed == ("unit_test_a",)
    assert [e.journal_event_id for e in journal.events] == ["unit_test_a"]
    assert _spill_files(tmp_path / "spill") == []


# --------------------------------------------------------------------------- #
# Purity (machine-enforced invariants).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("module", ["spill.py", "risk_first.py"])
def test_new_modules_read_no_wall_clock_and_build_no_float(module: str) -> None:
    path = SRC_ROOT / "ops" / module
    assert wall_clock_calls(path) == []
    assert float_constructor_calls(path) == []
