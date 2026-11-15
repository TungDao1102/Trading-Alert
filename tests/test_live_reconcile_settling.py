"""The scheduled reconcile leaves a placement alone while it runs and for one tick after.

First Demo run (2026-11-01), twice: the tick ran two seconds after CONFIRM, when the entry had
filled on the exchange and the local rows and the protection coordinator had not caught up, so a
healthy placement was judged UNSYNCED_NORMAL and POSITION_WITHOUT_STOP and entered SAFE_MODE.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from src.live.wiring import CompleteLiveWiring

from tests.support.live_wiring_rig import (
    WiringHandles,
    complete_assembly,
    forbid_connections,
    make_assembly,
)


@pytest.fixture(autouse=True)
def _no_connections(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    return forbid_connections(monkeypatch)


@pytest.fixture
def handles(tmp_path: Path) -> WiringHandles:
    return make_assembly(tmp_path)


@pytest.fixture
async def complete(handles: WiringHandles) -> CompleteLiveWiring:
    return await complete_assembly(handles)


def _record_ticks(handles: WiringHandles) -> list[bool]:
    ran: list[bool] = []

    async def record(now_utc: Any) -> None:
        ran.append(True)

    handles.assembly._reconcile_tick = record  # type: ignore[method-assign]
    return ran


def _reconcile(complete: CompleteLiveWiring) -> Any:
    return next(spec for spec in complete.specs if spec.name == "reconcile_tick")


async def test_a_tick_runs_when_no_placement_is_outstanding(
    complete: CompleteLiveWiring, handles: WiringHandles
) -> None:
    ran = _record_ticks(handles)
    await _reconcile(complete).run()
    assert ran == [True]


async def test_a_tick_is_skipped_while_a_placement_is_outstanding(
    complete: CompleteLiveWiring, handles: WiringHandles
) -> None:
    ran = _record_ticks(handles)
    complete.service._tasks.add(object())  # type: ignore[arg-type]
    try:
        await _reconcile(complete).run()
    finally:
        complete.service._tasks.clear()
    assert ran == []


async def test_one_tick_is_skipped_after_a_placement_ends_and_the_next_one_runs(
    complete: CompleteLiveWiring, handles: WiringHandles
) -> None:
    ran = _record_ticks(handles)
    complete.service._settling = True  # a placement has just ended

    await _reconcile(complete).run()
    assert ran == []
    await _reconcile(complete).run()
    assert ran == [True]


async def test_take_settling_is_true_once_per_ended_placement(
    complete: CompleteLiveWiring,
) -> None:
    service = complete.service
    assert service.take_settling() is False
    service._settling = True
    assert service.take_settling() is True
    assert service.take_settling() is False
