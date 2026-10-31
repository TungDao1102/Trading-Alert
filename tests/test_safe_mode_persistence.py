"""SAFE_MODE persistence through the SafeModeStateStore seam (Phase 20, plan 20-06, D-14, F-127).

Pins, on in-memory fakes (the PostgreSQL adapter is covered by `test_safe_mode_persistence_pg.py`):

  - `enter_safe_mode` flips the in-memory flag first, journals, then saves `state_snapshot()` to
    the injected store; `SafeModeController.load` on the same store restores SAFE_MODE;
  - `is_durable` is True only with a store attached; constructing without a store still works;
  - a failing save keeps the controller in SAFE_MODE and propagates the error; the next
    `enter_safe_mode` call (even with the same reason) retries the save;
  - `load` fails closed: a store whose `load` raises, or a malformed row, starts the controller IN
    SAFE_MODE with reason `SAFE_MODE_STATE_UNREADABLE`; only the exception TYPE name is journaled;
  - a restart never exits SAFE_MODE; an empty reason is refused (08-REVIEW IN-13).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from src.domain.enums import RejectionReason
from src.reconcile.safe_mode import (
    SAFE_MODE_STATE_UNREADABLE,
    SafeModeController,
    SafeModeStateStore,
)

T0 = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
T1 = T0 + timedelta(minutes=5)
T2 = T0 + timedelta(minutes=10)
REPO_ROOT = Path(__file__).resolve().parents[1]

SAFE_OFF: dict[str, Any] = {"in_safe_mode": False, "entered_at_utc": None, "entered_reason": None}
# The snapshot is the five-key format since plan 20-15 (D-15); SAFE_OFF above is the three-key row
# of plan 20-06, which must still load.
SNAP_OFF: dict[str, Any] = {
    **SAFE_OFF,
    "last_exit_operator_id": None,
    "last_exit_at_utc": None,
}


class FakeJournal:
    """In-memory journal that records every event (optionally failing)."""

    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[Any] = []
        self.fail = fail

    def record(self, event: Any) -> None:
        if self.fail:
            raise RuntimeError("journal down")
        self.events.append(event)


class _NoAdapter:
    """Never called by the persistence paths under test."""

    async def snapshot_open_normal_orders(self, *, symbol: str | None = None) -> list[Any]:
        return []

    async def snapshot_open_algo_orders(self, *, symbol: str | None = None) -> list[Any]:
        return []

    async def snapshot_positions(self, *, symbol: str | None = None) -> list[Any]:
        return []


class FakeStore:
    """In-memory `SafeModeStateStore`; `save_error` / `load_error` make it fail on demand."""

    def __init__(self, *, loaded: Mapping[str, Any] | None = None) -> None:
        self.saved: list[tuple[dict[str, Any], datetime]] = []
        self.loaded: Mapping[str, Any] | None = loaded
        self.save_error: Exception | None = None
        self.load_error: Exception | None = None

    def save(self, state: Mapping[str, str | bool | None], *, now_utc: datetime) -> None:
        if self.save_error is not None:
            raise self.save_error
        self.saved.append((dict(state), now_utc))
        self.loaded = dict(state)

    def load(self) -> Mapping[str, str | bool | None] | None:
        if self.load_error is not None:
            raise self.load_error
        return self.loaded


def _clean_compare(**_kwargs: Any) -> Any:
    return SimpleNamespace(agreement=True)


def _controller(store: FakeStore | None, journal: FakeJournal | None = None) -> SafeModeController:
    return SafeModeController(
        adapter=_NoAdapter(),
        journal=journal if journal is not None else FakeJournal(),
        compare_fn=_clean_compare,
        state_store=store,
    )


def _load(
    store: SafeModeStateStore, journal: FakeJournal | None = None, now_utc: datetime = T2
) -> SafeModeController:
    return SafeModeController.load(
        adapter=_NoAdapter(),
        journal=journal if journal is not None else FakeJournal(),
        state_store=store,
        now_utc=now_utc,
        compare_fn=_clean_compare,
    )


# --------------------------------------------------------------------------- #
# Task 1 - tracer: enter persists, a controller loaded from the same store is in SAFE_MODE
# --------------------------------------------------------------------------- #


def test_enter_saves_exactly_the_state_snapshot() -> None:
    store = FakeStore()
    controller = _controller(store)

    controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T0)

    assert store.saved == [
        (
            {
                "in_safe_mode": True,
                "entered_at_utc": T0.isoformat(),
                "entered_reason": "DB_FAILURE",
                "last_exit_operator_id": None,
                "last_exit_at_utc": None,
            },
            T0,
        )
    ]
    assert store.saved[0][0] == controller.state_snapshot()


def test_a_controller_loaded_from_the_same_store_is_in_safe_mode() -> None:
    store = FakeStore()
    _controller(store).enter_safe_mode(reason="DB_FAILURE", now_utc=T0)

    restored = _load(store, now_utc=T2)

    assert restored.in_safe_mode is True
    assert restored.entered_reason == "DB_FAILURE"
    assert restored.entered_at_utc == T0
    verdict = restored.guard_new_entries(trade_plan=None)
    assert verdict.is_no_trade is True
    assert verdict.reason_code == RejectionReason.RECONCILIATION_REQUIRED.value


def test_load_of_a_store_that_never_persisted_is_the_default_controller() -> None:
    store = FakeStore(loaded=None)

    controller = _load(store)

    assert controller.in_safe_mode is False
    assert controller.state_snapshot() == SNAP_OFF
    assert store.saved == []


def test_load_of_a_persisted_off_state_is_not_in_safe_mode() -> None:
    controller = _load(FakeStore(loaded=SAFE_OFF))

    assert controller.in_safe_mode is False


def test_is_durable_is_true_only_with_a_store() -> None:
    assert _controller(FakeStore()).is_durable is True
    assert _controller(None).is_durable is False
    assert _load(FakeStore()).is_durable is True


def test_a_controller_without_a_store_keeps_working_and_saves_nothing() -> None:
    journal = FakeJournal()
    controller = SafeModeController(adapter=_NoAdapter(), journal=journal)

    controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T0)

    assert controller.in_safe_mode is True
    assert [event.event_type for event in journal.events] == ["SAFE_MODE_ENTER"]


def test_a_reentry_with_a_new_reason_saves_the_new_snapshot() -> None:
    store = FakeStore()
    controller = _controller(store)
    controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T0)

    controller.enter_safe_mode(reason="UNSYNCED_POSITION", now_utc=T1)

    assert [saved[0]["entered_reason"] for saved in store.saved] == [
        "DB_FAILURE",
        "UNSYNCED_POSITION",
    ]
    assert store.saved[1][0]["entered_at_utc"] == T0.isoformat()
    assert store.saved[1][1] == T1


def test_a_same_reason_reentry_after_a_successful_save_does_not_save_again() -> None:
    store = FakeStore()
    controller = _controller(store)
    controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T0)

    controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T1)

    assert len(store.saved) == 1


def test_load_rejects_a_naive_or_non_utc_now() -> None:
    store = FakeStore()
    with pytest.raises(ValueError, match="UTC"):
        _load(store, now_utc=datetime(2026, 9, 19, 12, 0))
    with pytest.raises(ValueError, match="UTC"):
        _load(store, now_utc=datetime(2026, 9, 19, 12, 0, tzinfo=timezone(timedelta(hours=2))))


def test_safe_mode_module_imports_nothing_from_the_persistence_layer() -> None:
    source = (REPO_ROOT / "src" / "reconcile" / "safe_mode.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+src\.persistence", source, flags=re.MULTILINE)


# --------------------------------------------------------------------------- #
# Task 2 - fail closed: save failure and retry, unreadable or malformed store, empty reason
# --------------------------------------------------------------------------- #


def test_a_failing_save_propagates_but_the_controller_stays_in_safe_mode() -> None:
    store = FakeStore()
    store.save_error = ConnectionError("db down")
    journal = FakeJournal()
    controller = _controller(store, journal)

    with pytest.raises(ConnectionError, match="db down"):
        controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T0)

    assert controller.in_safe_mode is True
    assert controller.entered_reason == "DB_FAILURE"
    assert [event.event_type for event in journal.events] == ["SAFE_MODE_ENTER"]
    assert store.saved == []


def test_the_next_same_reason_enter_retries_the_save_until_the_store_recovers() -> None:
    store = FakeStore()
    store.save_error = ConnectionError("db down")
    journal = FakeJournal()
    controller = _controller(store, journal)
    with pytest.raises(ConnectionError):
        controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T0)

    with pytest.raises(ConnectionError):
        controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T1)  # still down: retried, raises
    store.save_error = None
    controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T2)

    assert len(store.saved) == 1
    assert store.saved[0][0] == controller.state_snapshot()
    # Only the first entry journals; the retries are not new transitions.
    assert [event.event_type for event in journal.events] == ["SAFE_MODE_ENTER"]
    # And once persisted, a further same-reason call is a no-op again.
    controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T2)
    assert len(store.saved) == 1


def test_a_failed_save_on_a_reentry_is_retried_by_the_next_same_reason_call() -> None:
    store = FakeStore()
    controller = _controller(store)
    controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T0)
    store.save_error = TimeoutError("slow")
    with pytest.raises(TimeoutError):
        controller.enter_safe_mode(reason="UNSYNCED_POSITION", now_utc=T1)
    store.save_error = None

    controller.enter_safe_mode(reason="UNSYNCED_POSITION", now_utc=T2)

    assert store.saved[-1][0]["entered_reason"] == "UNSYNCED_POSITION"


def test_a_journal_failure_on_entry_leaves_the_controller_in_safe_mode_and_save_retries() -> None:
    store = FakeStore()
    journal = FakeJournal(fail=True)
    controller = _controller(store, journal)
    with pytest.raises(RuntimeError, match="journal down"):
        controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T0)
    assert controller.in_safe_mode is True
    assert store.saved == []

    controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T1)

    assert len(store.saved) == 1


def test_a_store_whose_load_raises_starts_the_controller_in_safe_mode_unreadable() -> None:
    store = FakeStore()
    store.load_error = ConnectionError("db down")
    journal = FakeJournal()

    controller = _load(store, journal, now_utc=T2)

    assert controller.in_safe_mode is True
    assert controller.entered_reason == SAFE_MODE_STATE_UNREADABLE
    assert SAFE_MODE_STATE_UNREADABLE == "SAFE_MODE_STATE_UNREADABLE"
    assert controller.entered_at_utc == T2
    assert controller.is_durable is True
    assert controller.guard_new_entries(trade_plan=None).is_no_trade is True
    (event,) = journal.events
    assert event.event_type == "SAFE_MODE_STATE_UNREADABLE"
    assert json.loads(event.payload_json) == {"error_type": "ConnectionError"}


@pytest.mark.parametrize(
    "state",
    [
        {"in_safe_mode": True},
        {"in_safe_mode": "yes", "entered_at_utc": None, "entered_reason": None},
        {"in_safe_mode": True, "entered_at_utc": None, "entered_reason": "X"},
        {"in_safe_mode": True, "entered_at_utc": "2026-09-19T12:00:00", "entered_reason": "X"},
        {"in_safe_mode": False, "entered_at_utc": T0.isoformat(), "entered_reason": None},
        {"in_safe_mode": True, "entered_at_utc": T0.isoformat(), "entered_reason": "X", "x": 1},
    ],
)
def test_a_malformed_stored_state_starts_the_controller_in_safe_mode_unreadable(
    state: dict[str, Any],
) -> None:
    journal = FakeJournal()

    controller = _load(FakeStore(loaded=state), journal, now_utc=T2)

    assert controller.in_safe_mode is True
    assert controller.entered_reason == SAFE_MODE_STATE_UNREADABLE
    assert controller.entered_at_utc == T2
    (event,) = journal.events
    assert json.loads(event.payload_json) == {"error_type": "ValueError"}


def test_a_journal_failure_while_reporting_an_unreadable_store_is_swallowed() -> None:
    store = FakeStore()
    store.load_error = RuntimeError("boom")

    controller = _load(store, FakeJournal(fail=True))

    assert controller.in_safe_mode is True
    assert controller.entered_reason == SAFE_MODE_STATE_UNREADABLE


def test_an_error_message_is_never_journaled_on_an_unreadable_store() -> None:
    store = FakeStore()
    store.load_error = RuntimeError("password=hunter2")
    journal = FakeJournal()

    controller = _load(store, journal)

    assert controller.in_safe_mode is True
    assert journal.events
    for event in journal.events:
        assert "hunter2" not in event.payload_json
        assert "hunter2" not in repr(event)
    assert "hunter2" not in repr(controller.state_snapshot())


@pytest.mark.parametrize("reason", ["", None, 7])
def test_enter_refuses_an_empty_or_non_string_reason_and_changes_nothing(reason: Any) -> None:
    store = FakeStore()
    journal = FakeJournal()
    controller = _controller(store, journal)

    with pytest.raises(ValueError, match="reason"):
        controller.enter_safe_mode(reason=reason, now_utc=T0)

    assert controller.in_safe_mode is False
    assert controller.state_snapshot() == SNAP_OFF
    assert journal.events == []
    assert store.saved == []


def test_a_restart_never_exits_safe_mode() -> None:
    store = FakeStore()
    _controller(store).enter_safe_mode(reason="DB_FAILURE", now_utc=T0)

    first = _load(store, now_utc=T1)
    second = _load(store, now_utc=T2)

    assert first.in_safe_mode is True
    assert second.in_safe_mode is True
    assert second.entered_at_utc == T0


# --------------------------------------------------------------------------- #
# Plan 24-20 (20-DEFERRED row 41): a journal failure while entering leaves a spill record
# --------------------------------------------------------------------------- #


class RecordingSpill:
    """The one method a `SafeModeController` calls on a spill: `write(event)`."""

    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[Any] = []
        self.fail = fail

    def write(self, event: Any) -> object:
        if self.fail:
            raise OSError("spill volume down")
        self.events.append(event)
        return object()


def _spilling(
    journal: FakeJournal, spill: RecordingSpill | None, store: FakeStore | None = None
) -> SafeModeController:
    return SafeModeController(
        adapter=_NoAdapter(),
        journal=journal,
        compare_fn=_clean_compare,
        state_store=store if store is not None else FakeStore(),
        spill=spill,
    )


def test_a_journal_failure_on_entry_leaves_one_spill_record_and_still_raises() -> None:
    spill = RecordingSpill()
    controller = _spilling(FakeJournal(fail=True), spill)

    with pytest.raises(RuntimeError, match="journal down"):
        controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T0)

    assert controller.in_safe_mode is True, "the flag is set first (fail closed)"
    (event,) = spill.events
    assert event.event_type == "SAFE_MODE_ENTER"
    assert event.occurred_at_utc == T0
    assert json.loads(event.payload_json)["reason"] == "DB_FAILURE"


def test_a_journal_failure_on_reentry_with_a_new_reason_is_spilled_too() -> None:
    spill = RecordingSpill()
    journal = FakeJournal()
    controller = _spilling(journal, spill)
    controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T0)
    journal.fail = True

    with pytest.raises(RuntimeError, match="journal down"):
        controller.enter_safe_mode(reason="API_DEGRADATION", now_utc=T1)

    (event,) = spill.events
    assert event.event_type == "SAFE_MODE_REENTER"
    assert json.loads(event.payload_json)["reason"] == "API_DEGRADATION"


def test_a_working_journal_writes_nothing_to_the_spill() -> None:
    spill = RecordingSpill()
    controller = _spilling(FakeJournal(), spill)

    controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T0)

    assert spill.events == []


def test_a_failing_spill_does_not_hide_the_journal_error() -> None:
    controller = _spilling(FakeJournal(fail=True), RecordingSpill(fail=True))

    with pytest.raises(RuntimeError, match="journal down"):
        controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T0)

    assert controller.in_safe_mode is True


def test_without_a_spill_the_journal_error_propagates_as_before() -> None:
    controller = _spilling(FakeJournal(fail=True), None)

    with pytest.raises(RuntimeError, match="journal down"):
        controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T0)

    assert controller.in_safe_mode is True


def test_load_passes_the_spill_to_the_controller() -> None:
    spill = RecordingSpill()
    journal = FakeJournal(fail=True)
    controller = SafeModeController.load(
        adapter=_NoAdapter(),
        journal=journal,
        state_store=FakeStore(),
        now_utc=T0,
        compare_fn=_clean_compare,
        spill=spill,
    )
    assert controller.in_safe_mode is False

    with pytest.raises(RuntimeError, match="journal down"):
        controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T1)

    assert len(spill.events) == 1


def test_an_unreadable_start_with_a_failing_journal_leaves_a_spill_record() -> None:
    store = FakeStore()
    store.load_error = RuntimeError("db down")
    spill = RecordingSpill()

    controller = SafeModeController.load(
        adapter=_NoAdapter(),
        journal=FakeJournal(fail=True),
        state_store=store,
        now_utc=T2,
        compare_fn=_clean_compare,
        spill=spill,
    )

    assert controller.in_safe_mode is True
    (event,) = spill.events
    assert event.event_type == SAFE_MODE_STATE_UNREADABLE
