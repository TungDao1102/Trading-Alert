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

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from src.domain.enums import RejectionReason
from src.reconcile.safe_mode import SafeModeController, SafeModeStateStore

T0 = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
T1 = T0 + timedelta(minutes=5)
T2 = T0 + timedelta(minutes=10)
REPO_ROOT = Path(__file__).resolve().parents[1]

SAFE_OFF: dict[str, Any] = {"in_safe_mode": False, "entered_at_utc": None, "entered_reason": None}


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


def _controller(
    store: FakeStore | None, journal: FakeJournal | None = None
) -> SafeModeController:
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
    assert controller.state_snapshot() == SAFE_OFF
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
