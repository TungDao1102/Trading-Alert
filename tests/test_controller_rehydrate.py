"""Controller state snapshots and rehydrate constructors (17-13, D-22, F-606, research C14).

Pins:

  - `SafeModeController.state_snapshot()` and `LiveEnablementController.state_snapshot()` return the
    state-dict formats the system-state store persists, and `rehydrate(...)` rebuilds a controller
    from such a plain mapping (no `src.persistence` import in either module);
  - `state=None` rehydrates to the controller defaults (SAFE_MODE off, live orders disabled), and a
    malformed mapping (missing or unknown key, wrong type, naive or non-UTC datetime, an entered
    SAFE_MODE without its entry time or reason, an enabled state without operator or time) raises
    `ValueError` instead of defaulting;
  - rehydrating writes nothing to the journal and leaves the constructors' signatures alone;
  - on PostgreSQL, state written through one engine is read back through a fresh engine and stores,
    and the rehydrated controllers block new entries / placement exactly as before the restart.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from src.domain.enums import KillGateState, RejectionReason, SystemStateKey
from src.execution.enablement import LiveEnablementController
from src.persistence.engine import make_sync_engine
from src.persistence.journal import PgJournalStore
from src.persistence.system_state import PgSystemStateStore
from src.persistence.uow import OperationalDatabase
from src.reconcile.safe_mode import SafeModeController

T0 = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
T1 = T0 + timedelta(minutes=5)
REPO_ROOT = Path(__file__).resolve().parents[1]


class FakeJournal:
    """In-memory journal that records every event."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def record(self, event: Any) -> None:
        self.events.append(event)


class _NoAdapter:
    """Never called by the rehydrate paths under test."""

    async def snapshot_open_normal_orders(self, *, symbol: str | None = None) -> list[Any]:
        return []

    async def snapshot_open_algo_orders(self, *, symbol: str | None = None) -> list[Any]:
        return []

    async def snapshot_positions(self, *, symbol: str | None = None) -> list[Any]:
        return []


def _clean_compare(**_kwargs: Any) -> Any:
    return SimpleNamespace(agreement=True)


def _passing_health_verdict() -> Any:
    from src.ops.health import ALL_CHECK_NAMES, HealthCheckResult, run_health_checks

    return run_health_checks(
        results=[
            HealthCheckResult(check_name=name, status="PASS", detail="ok", observed_at_utc=T0)
            for name in ALL_CHECK_NAMES
        ]
    )


def _safe_mode(journal: Any = None) -> SafeModeController:
    return SafeModeController(
        adapter=_NoAdapter(),
        journal=journal if journal is not None else FakeJournal(),
        compare_fn=_clean_compare,
    )


def _rehydrate_safe_mode(
    state: Mapping[str, Any] | None, journal: Any = None
) -> SafeModeController:
    return SafeModeController.rehydrate(
        adapter=_NoAdapter(),
        journal=journal if journal is not None else FakeJournal(),
        compare_fn=_clean_compare,
        state=state,
    )


SAFE_ON: dict[str, Any] = {
    "in_safe_mode": True,
    "entered_at_utc": T0.isoformat(),
    "entered_reason": "UNSYNCED_POSITION",
}
SAFE_OFF: dict[str, Any] = {
    "in_safe_mode": False,
    "entered_at_utc": None,
    "entered_reason": None,
}
ENABLED: dict[str, Any] = {
    "disabled": False,
    "enabled_at_utc": T0.isoformat(),
    "operator_id": "operator-1",
}
DISABLED: dict[str, Any] = {"disabled": True, "enabled_at_utc": None, "operator_id": None}


# --------------------------------------------------------------------------- #
# SafeModeController
# --------------------------------------------------------------------------- #


def test_safe_mode_default_snapshot_is_off() -> None:
    assert _safe_mode().state_snapshot() == SAFE_OFF


def test_safe_mode_snapshot_after_entry_uses_the_documented_format() -> None:
    controller = _safe_mode()
    controller.enter_safe_mode(reason="UNSYNCED_POSITION", now_utc=T0)

    assert controller.state_snapshot() == SAFE_ON


def test_safe_mode_snapshot_after_exit_is_off() -> None:
    import asyncio

    controller = _safe_mode()
    controller.enter_safe_mode(reason="UNSYNCED_POSITION", now_utc=T0)
    assert asyncio.run(controller.exit_safe_mode(now_utc=T1)) is True

    assert controller.state_snapshot() == SAFE_OFF


def test_safe_mode_rehydrate_restores_the_entered_state_and_blocks_entries() -> None:
    source = _safe_mode()
    source.enter_safe_mode(reason="UNSYNCED_POSITION", now_utc=T0)

    restored = _rehydrate_safe_mode(source.state_snapshot())

    assert restored.in_safe_mode is True
    assert restored.entered_at_utc == T0
    assert restored.entered_reason == "UNSYNCED_POSITION"
    verdict = restored.guard_new_entries(trade_plan=None)
    assert verdict.is_no_trade is True
    assert verdict.reason_code == RejectionReason.RECONCILIATION_REQUIRED.value
    assert restored.state_snapshot() == source.state_snapshot()


def test_safe_mode_rehydrate_of_none_is_the_default_controller() -> None:
    restored = _rehydrate_safe_mode(None)

    assert restored.in_safe_mode is False
    assert restored.entered_at_utc is None
    assert restored.entered_reason is None
    assert restored.guard_new_entries(trade_plan=None).is_no_trade is False


def test_safe_mode_rehydrate_of_an_off_state_is_not_in_safe_mode() -> None:
    restored = _rehydrate_safe_mode(SAFE_OFF)
    assert restored.in_safe_mode is False


def test_safe_mode_rehydrate_writes_nothing_to_the_journal() -> None:
    journal = FakeJournal()
    _rehydrate_safe_mode(SAFE_ON, journal)
    assert journal.events == []


def test_a_rehydrated_safe_mode_exits_only_through_the_normal_journaled_path() -> None:
    import asyncio

    journal = FakeJournal()
    restored = _rehydrate_safe_mode(SAFE_ON, journal)

    assert asyncio.run(restored.exit_safe_mode(now_utc=T1)) is True

    assert [event.event_type for event in journal.events] == ["SAFE_MODE_EXIT"]
    assert restored.in_safe_mode is False


def _without(state: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: value for name, value in state.items() if name != key}


MALFORMED_SAFE_MODE: list[Any] = [
    pytest.param(_without(SAFE_ON, "in_safe_mode"), id="missing-in_safe_mode"),
    pytest.param(_without(SAFE_ON, "entered_at_utc"), id="missing-entered_at"),
    pytest.param(_without(SAFE_ON, "entered_reason"), id="missing-entered_reason"),
    pytest.param({**SAFE_ON, "extra": "x"}, id="unknown-key"),
    pytest.param({**SAFE_ON, "in_safe_mode": "true"}, id="in_safe_mode-text"),
    pytest.param({**SAFE_ON, "in_safe_mode": 1}, id="in_safe_mode-int"),
    pytest.param({**SAFE_ON, "in_safe_mode": None}, id="in_safe_mode-none"),
    pytest.param({**SAFE_ON, "entered_at_utc": "2026-09-19T12:00:00"}, id="naive-datetime"),
    pytest.param({**SAFE_ON, "entered_at_utc": "2026-09-19T12:00:00+07:00"}, id="non-utc-datetime"),
    pytest.param({**SAFE_ON, "entered_at_utc": "not a date"}, id="bad-iso"),
    pytest.param({**SAFE_ON, "entered_at_utc": 5}, id="datetime-int"),
    pytest.param({**SAFE_ON, "entered_at_utc": None}, id="entered-without-time"),
    pytest.param({**SAFE_ON, "entered_reason": None}, id="entered-without-reason"),
    pytest.param({**SAFE_ON, "entered_reason": 5}, id="reason-int"),
    pytest.param({**SAFE_OFF, "entered_at_utc": T0.isoformat()}, id="off-with-time"),
    pytest.param({**SAFE_OFF, "entered_reason": "X"}, id="off-with-reason"),
    pytest.param([("in_safe_mode", True)], id="not-a-mapping"),
    pytest.param("in_safe_mode", id="string"),
    pytest.param({}, id="empty-mapping"),
]


@pytest.mark.parametrize("state", MALFORMED_SAFE_MODE)
def test_safe_mode_rehydrate_fails_closed_on_malformed_state(state: Any) -> None:
    with pytest.raises(ValueError):
        _rehydrate_safe_mode(state)


# --------------------------------------------------------------------------- #
# LiveEnablementController
# --------------------------------------------------------------------------- #


def test_enablement_default_snapshot_is_disabled() -> None:
    assert LiveEnablementController(journal=FakeJournal()).state_snapshot() == DISABLED


def test_enablement_snapshot_after_enable_and_disable() -> None:
    controller = LiveEnablementController(journal=FakeJournal())
    controller.enable(
        operator_id="operator-1",
        now_utc=T0,
        health_verdict=_passing_health_verdict(),
        kill_gate_state=KillGateState.WITHIN_BUDGET,
    )
    assert controller.state_snapshot() == ENABLED

    controller.disable(operator_id="operator-1", now_utc=T1)
    assert controller.state_snapshot() == DISABLED


def test_enablement_rehydrate_restores_an_enabled_controller() -> None:
    restored = LiveEnablementController.rehydrate(journal=FakeJournal(), state=ENABLED)

    assert restored.is_disabled is False
    assert restored.enabled_at_utc == T0
    assert restored.operator_id == "operator-1"
    assert restored.guard_placement(plan_hash="h").is_no_trade is False
    assert restored.state_snapshot() == ENABLED


def test_enablement_rehydrate_restores_a_disabled_controller() -> None:
    restored = LiveEnablementController.rehydrate(journal=FakeJournal(), state=DISABLED)

    assert restored.is_disabled is True
    assert restored.guard_placement(plan_hash="h").reason_code == "DISABLED"


def test_enablement_rehydrate_of_none_is_the_default_disabled_controller() -> None:
    restored = LiveEnablementController.rehydrate(journal=FakeJournal(), state=None)

    assert restored.is_disabled is True
    assert restored.enabled_at_utc is None
    assert restored.operator_id is None
    assert restored.guard_placement(plan_hash="h").is_no_trade is True


def test_enablement_rehydrate_writes_nothing_and_disable_still_journals_first() -> None:
    journal = FakeJournal()
    restored = LiveEnablementController.rehydrate(journal=journal, state=ENABLED)
    assert journal.events == []

    restored.disable(operator_id="operator-2", now_utc=T1)

    assert [event.event_type for event in journal.events] == ["LIVE_ORDERS_DISABLED"]
    assert restored.is_disabled is True


MALFORMED_ENABLEMENT: list[Any] = [
    pytest.param(_without(ENABLED, "disabled"), id="missing-disabled"),
    pytest.param(_without(ENABLED, "enabled_at_utc"), id="missing-enabled_at"),
    pytest.param(_without(ENABLED, "operator_id"), id="missing-operator_id"),
    pytest.param({**ENABLED, "extra": 1}, id="unknown-key"),
    pytest.param({**ENABLED, "disabled": "false"}, id="disabled-text"),
    pytest.param({**ENABLED, "disabled": 0}, id="disabled-int"),
    pytest.param({**ENABLED, "disabled": None}, id="disabled-none"),
    pytest.param({**ENABLED, "enabled_at_utc": "2026-09-19T12:00:00"}, id="naive-datetime"),
    pytest.param({**ENABLED, "enabled_at_utc": "2026-09-19T12:00:00+07:00"}, id="non-utc-datetime"),
    pytest.param({**ENABLED, "enabled_at_utc": "nope"}, id="bad-iso"),
    pytest.param({**ENABLED, "enabled_at_utc": None}, id="enabled-without-time"),
    pytest.param({**ENABLED, "operator_id": None}, id="enabled-without-operator"),
    pytest.param({**ENABLED, "operator_id": ""}, id="enabled-with-empty-operator"),
    pytest.param({**ENABLED, "operator_id": 7}, id="operator-int"),
    pytest.param({**DISABLED, "operator_id": "operator-1"}, id="disabled-with-operator"),
    pytest.param({**DISABLED, "enabled_at_utc": T0.isoformat()}, id="disabled-with-time"),
    pytest.param(["disabled"], id="not-a-mapping"),
    pytest.param({}, id="empty-mapping"),
]


@pytest.mark.parametrize("state", MALFORMED_ENABLEMENT)
def test_enablement_rehydrate_fails_closed_on_malformed_state(state: Any) -> None:
    with pytest.raises(ValueError):
        LiveEnablementController.rehydrate(journal=FakeJournal(), state=state)


# --------------------------------------------------------------------------- #
# Contracts: constructors unchanged, no persistence import
# --------------------------------------------------------------------------- #


def test_constructor_signatures_are_unchanged() -> None:
    safe = inspect.signature(SafeModeController.__init__)
    # Plan 20-06 (D-14) adds the optional `state_store` keyword; the others keep their order.
    assert list(safe.parameters) == ["self", "adapter", "journal", "compare_fn", "state_store"]
    assert safe.parameters["state_store"].default is None
    enable = inspect.signature(LiveEnablementController.__init__)
    assert list(enable.parameters) == ["self", "journal"]


@pytest.mark.parametrize("module", ["reconcile/safe_mode.py", "execution/enablement.py"])
def test_controllers_do_not_import_the_persistence_layer(module: str) -> None:
    source = (REPO_ROOT / "src" / module).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+src\.persistence", source, flags=re.MULTILINE)


# --------------------------------------------------------------------------- #
# Restart across a fresh engine (PostgreSQL)
# --------------------------------------------------------------------------- #


def _open_stores(url: str) -> tuple[Callable[[], None], PgJournalStore, PgSystemStateStore]:
    engine = make_sync_engine(url)
    db = OperationalDatabase(engine)
    journal = PgJournalStore(db)
    return engine.dispose, journal, PgSystemStateStore(db, journal)


def test_safe_mode_survives_a_restart_on_a_fresh_engine(pg_db: str) -> None:
    dispose, journal, state_store = _open_stores(pg_db)
    try:
        controller = _safe_mode(journal)
        controller.enter_safe_mode(reason="UNSYNCED_POSITION", now_utc=T0)
        state_store.append(SystemStateKey.SAFE_MODE, controller.state_snapshot(), now_utc=T0)
    finally:
        dispose()

    dispose_b, journal_b, state_store_b = _open_stores(pg_db)
    try:
        record = state_store_b.latest(SystemStateKey.SAFE_MODE)
        assert record is not None
        restored = _rehydrate_safe_mode(record.state, journal_b)

        assert restored.in_safe_mode is True
        assert restored.entered_at_utc == T0
        assert restored.entered_reason == "UNSYNCED_POSITION"
        verdict = restored.guard_new_entries(trade_plan=None)
        assert verdict.is_no_trade is True
        assert verdict.reason_code == RejectionReason.RECONCILIATION_REQUIRED.value
        # The audit trail holds both the controller's own event and the state-change event.
        types = {
            event.event_type
            for event in journal_b.list_by_correlation("reconcile_safe_mode")
            + journal_b.list_by_correlation("system_state:SAFE_MODE")
        }
        assert types == {"SAFE_MODE_ENTER", "SYSTEM_STATE_CHANGED"}
    finally:
        dispose_b()


def test_a_never_written_safe_mode_rehydrates_to_off_on_a_fresh_engine(pg_db: str) -> None:
    dispose, _journal, state_store = _open_stores(pg_db)
    try:
        record = state_store.latest(SystemStateKey.SAFE_MODE)
        restored = _rehydrate_safe_mode(None if record is None else record.state)
        assert record is None
        assert restored.in_safe_mode is False
    finally:
        dispose()


def test_enablement_survives_a_restart_on_a_fresh_engine(pg_db: str) -> None:
    dispose, journal, state_store = _open_stores(pg_db)
    try:
        controller = LiveEnablementController(journal=journal)
        controller.enable(
            operator_id="operator-1",
            now_utc=T0,
            health_verdict=_passing_health_verdict(),
            kill_gate_state=KillGateState.WITHIN_BUDGET,
        )
        state_store.append(SystemStateKey.LIVE_ENABLEMENT, controller.state_snapshot(), now_utc=T0)
        controller.disable(operator_id="operator-1", now_utc=T1)
        state_store.append(SystemStateKey.LIVE_ENABLEMENT, controller.state_snapshot(), now_utc=T1)
        # Enable again so the latest persisted version is the enabled state.
        controller.enable(
            operator_id="operator-2",
            now_utc=T1 + timedelta(minutes=1),
            health_verdict=_passing_health_verdict(),
            kill_gate_state=KillGateState.PASSING_CANDIDATE,
        )
        state_store.append(
            SystemStateKey.LIVE_ENABLEMENT,
            controller.state_snapshot(),
            now_utc=T1 + timedelta(minutes=1),
        )
    finally:
        dispose()

    dispose_b, journal_b, state_store_b = _open_stores(pg_db)
    try:
        record = state_store_b.latest(SystemStateKey.LIVE_ENABLEMENT)
        assert record is not None
        assert record.version == 3
        restored = LiveEnablementController.rehydrate(journal=journal_b, state=record.state)

        assert restored.is_disabled is False
        assert restored.operator_id == "operator-2"
        assert restored.enabled_at_utc == T1 + timedelta(minutes=1)
        assert restored.guard_placement(plan_hash="h").is_no_trade is False
    finally:
        dispose_b()


def test_a_disabled_enablement_survives_a_restart_as_disabled(pg_db: str) -> None:
    dispose, _journal, state_store = _open_stores(pg_db)
    try:
        controller = LiveEnablementController(journal=FakeJournal())
        state_store.append(SystemStateKey.LIVE_ENABLEMENT, controller.state_snapshot(), now_utc=T0)
    finally:
        dispose()

    dispose_b, journal_b, state_store_b = _open_stores(pg_db)
    try:
        record = state_store_b.latest(SystemStateKey.LIVE_ENABLEMENT)
        assert record is not None
        restored = LiveEnablementController.rehydrate(journal=journal_b, state=record.state)
        assert restored.guard_placement(plan_hash="h").reason_code == "DISABLED"
    finally:
        dispose_b()


@pytest.mark.parametrize("state", list(KillGateState))
def test_kill_gate_state_survives_a_restart_on_a_fresh_engine(
    pg_db: str, state: KillGateState
) -> None:
    dispose, _journal, state_store = _open_stores(pg_db)
    try:
        state_store.append(SystemStateKey.KILL_GATE, {"kill_gate_state": state.value}, now_utc=T0)
    finally:
        dispose()

    dispose_b, _journal_b, state_store_b = _open_stores(pg_db)
    try:
        assert state_store_b.latest_kill_gate_state() is state
    finally:
        dispose_b()


def test_a_restored_naive_or_foreign_offset_time_cannot_reach_the_controller() -> None:
    odd = timezone(timedelta(hours=7))
    with pytest.raises(ValueError):
        _rehydrate_safe_mode(
            {**SAFE_ON, "entered_at_utc": datetime(2026, 9, 19, 19, 0, tzinfo=odd).isoformat()}
        )
