"""`ConfirmFlow(run_sync=...)`: `handle_confirm` runs on the store writer thread (plan 24-17).

R-2 / P-1 / D-25: a CONFIRM press does journal writes and takes a reservation lock; on the bot loop
they would delay a CANCEL or a replay. With the optional `run_sync` seam (`StoreExecutor.write` in
the live process) the core's synchronous `handle_confirm` is awaited on the writer thread; without
it every existing test and the SHADOW confirm keep the inline call. Assumption A6: the core makes
no loop-bound call on that thread, so the injected `on_confirmed` is the only hop back to the loop.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest
from src.domain.approval import Approval
from src.domain.enums import ApprovalAction
from src.domain.trade_plan import TradePlan
from src.ops.store_executor import WRITER_THREAD_PREFIX, StoreExecutor

from tests.test_confirm_flow import Rig

MAIN = threading.main_thread().name


@pytest.fixture
def executor() -> Iterator[StoreExecutor]:
    store_executor = StoreExecutor()
    yield store_executor
    store_executor.close()


class ThreadSpy:
    """Records the thread names of the loop-bound asyncio entry points called off the loop."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.main = threading.current_thread()
        self.off_loop_calls: list[tuple[str, str]] = []
        for name in ("get_running_loop", "get_event_loop", "create_task", "ensure_future"):
            self._wrap(monkeypatch, name)

    def _wrap(self, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
        original = getattr(asyncio, name)

        def spy(*args: Any, **kwargs: Any) -> Any:
            thread = threading.current_thread()
            if thread is not self.main:
                self.off_loop_calls.append((name, thread.name))
            return original(*args, **kwargs)

        monkeypatch.setattr(asyncio, name, spy)


def _recorder(rig: Rig, seen: dict[str, Any]) -> None:
    """Replace the rig's `on_confirmed` effect with a recorder of the thread it runs on."""
    original = rig.on_confirmed
    loop = asyncio.get_running_loop()

    def on_confirmed(approval: Approval, plan: TradePlan, confirmed_at: datetime) -> None:
        seen["hook_thread"] = threading.current_thread().name
        original(approval, plan, confirmed_at)
        # The same hop ExecutionService makes: schedule on the loop thread, never await here.
        loop.call_soon_threadsafe(lambda: seen.setdefault("scheduled_on", []).append(approval))

    rig.on_confirmed = on_confirmed  # type: ignore[method-assign]


async def _approve_and_confirm(rig: Rig, flow: Any) -> None:
    issued = await rig.issue_and_send()
    short = issued.mapping.short_id
    approve = await rig.tap("APR", short, query_id="q-apr", flow=flow)
    assert approve.ok
    confirm = await rig.tap("CNF", short, query_id="q-cnf", flow=flow)
    assert confirm.ok


async def test_handle_confirm_and_the_hook_run_on_the_writer_thread_and_place_once(
    executor: StoreExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig()
    seen: dict[str, Any] = {}
    _recorder(rig, seen)
    flow = rig.make_flow(run_sync=executor.write)
    core_threads: list[str] = []
    real_handle_confirm = flow.book.handle_confirm

    def handle_confirm(**kwargs: Any) -> Any:
        core_threads.append(threading.current_thread().name)
        return real_handle_confirm(**kwargs)

    monkeypatch.setattr(flow.book, "handle_confirm", handle_confirm)

    await _approve_and_confirm(rig, flow)
    await asyncio.sleep(0)  # let the call_soon_threadsafe hop run

    assert len(core_threads) == 1
    assert core_threads[0].startswith(WRITER_THREAD_PREFIX)
    assert seen["hook_thread"].startswith(WRITER_THREAD_PREFIX)
    assert len(rig.confirmed) == 1, "exactly one hand-off to placement"
    assert len(seen["scheduled_on"]) == 1, "the hop to the loop scheduled placement exactly once"
    assert rig.row(ApprovalAction.APPROVE).approval_id == rig.confirmed[0][0].approval_id


async def test_no_loop_bound_call_is_made_on_the_worker_thread(
    executor: StoreExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Assumption A6: handle_confirm touches no loop on the writer thread."""
    rig = Rig()
    seen: dict[str, Any] = {}
    loop = asyncio.get_running_loop()

    def on_confirmed(approval: Approval, plan: TradePlan, confirmed_at: datetime) -> None:
        rig.confirmed.append((approval, plan, confirmed_at))
        loop.call_soon_threadsafe(lambda: seen.setdefault("n", []).append(1))

    rig.on_confirmed = on_confirmed  # type: ignore[method-assign]
    flow = rig.make_flow(run_sync=executor.write)
    spy = ThreadSpy(monkeypatch)

    await _approve_and_confirm(rig, flow)
    await asyncio.sleep(0)

    assert len(rig.confirmed) == 1
    assert spy.off_loop_calls == [], f"loop-bound calls off the loop: {spy.off_loop_calls}"
    assert seen["n"] == [1]


async def test_without_the_seam_handle_confirm_stays_inline() -> None:
    rig = Rig()
    seen: dict[str, Any] = {}
    _recorder(rig, seen)
    flow = rig.make_flow()
    assert "run_sync" not in flow.callback_kwargs(
        authorized_chat_id=4242, authorized_user_ids=frozenset({1})
    )

    await _approve_and_confirm(rig, flow)

    assert seen["hook_thread"] == MAIN
    assert len(rig.confirmed) == 1


async def test_the_seam_is_carried_into_the_callback_keywords(executor: StoreExecutor) -> None:
    rig = Rig()
    flow = rig.make_flow(run_sync=executor.write)
    kwargs = flow.callback_kwargs(authorized_chat_id=4242, authorized_user_ids=frozenset({1}))
    assert kwargs["run_sync"] == executor.write


async def test_a_refused_confirm_off_the_loop_places_nothing(executor: StoreExecutor) -> None:
    """The seam does not weaken the core: a CONFIRM without a prior APPROVE hands nothing over."""
    rig = Rig()
    flow = rig.make_flow(run_sync=executor.write)
    issued = await rig.issue_and_send()

    result = await rig.tap("CNF", issued.mapping.short_id, query_id="q-cnf", flow=flow)

    assert not result.ok
    assert rig.confirmed == []
