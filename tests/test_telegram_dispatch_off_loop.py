"""`on_callback(run_sync=...)`: the desk's dispatch runs on the store writer thread (plan 24-17).

R-2 / P-1 / D-25: `ApprovalDesk.dispatch` journals the decision and takes the FOR UPDATE
reservation; on the bot loop that would hold up a CANCEL or a replay. With the optional `run_sync`
seam it is awaited on the writer thread. The chat and user gates stay on the loop and run first;
without the seam nothing changes (the Phase 23 authorization tests stay green).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Any, cast

import pytest
from src.adapters import telegram_callbacks
from src.adapters.telegram_callbacks import DispatchResult, on_callback
from src.domain.enums import ApprovalResult
from src.ops.store_executor import WRITER_THREAD_PREFIX, StoreExecutor

from tests.shadow_fakes import (
    AUTHORIZED_USER_IDS,
    CHAT_ID,
    STRANGER_USER_ID,
    USER_ID,
    make_callback_update,
)
from tests.test_confirm_flow import Rig

MAIN = threading.main_thread().name


@pytest.fixture
def executor() -> Iterator[StoreExecutor]:
    store_executor = StoreExecutor()
    yield store_executor
    store_executor.close()


async def _press(
    rig: Rig, short_id: str, *, run_sync: Any, dispatch: Any, user_id: int, query_id: str
) -> DispatchResult:
    update = make_callback_update(
        data=f"APR:{short_id}",
        chat_id=CHAT_ID,
        query_id=query_id,
        message_chat_id=CHAT_ID,
        from_user_id=user_id,
        message_id=1,
        chat_type="private",
    )
    kwargs = rig.flow.callback_kwargs(
        authorized_chat_id=CHAT_ID,
        authorized_user_ids=AUTHORIZED_USER_IDS,
        error_journal=rig.stores.record_journal,
    )
    kwargs["dispatch"] = dispatch
    return await on_callback(update, cast(Any, None), **kwargs, run_sync=run_sync)


def _spying_dispatch(rig: Rig, threads: list[str]) -> Any:
    real = rig.desk.dispatch

    def dispatch(parsed: Any, **kwargs: Any) -> DispatchResult:
        threads.append(threading.current_thread().name)
        return real(parsed, **kwargs)

    return dispatch


async def test_dispatch_runs_on_the_writer_thread_when_the_seam_is_given(
    executor: StoreExecutor,
) -> None:
    rig = Rig()
    issued = await rig.issue_and_send()
    threads: list[str] = []

    result = await _press(
        rig,
        issued.mapping.short_id,
        run_sync=executor.write,
        dispatch=_spying_dispatch(rig, threads),
        user_id=USER_ID,
        query_id="q-apr",
    )

    assert result.ok
    assert len(threads) == 1 and threads[0].startswith(WRITER_THREAD_PREFIX)
    assert any(a.status is ApprovalResult.APPROVED for a in rig.stores.approvals.values())


async def test_dispatch_stays_inline_without_the_seam() -> None:
    rig = Rig()
    issued = await rig.issue_and_send()
    threads: list[str] = []

    result = await _press(
        rig,
        issued.mapping.short_id,
        run_sync=None,
        dispatch=_spying_dispatch(rig, threads),
        user_id=USER_ID,
        query_id="q-apr",
    )

    assert result.ok
    assert threads == [MAIN]


async def test_an_unauthorized_user_is_refused_on_the_loop_and_approves_nothing(
    executor: StoreExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig()
    issued = await rig.issue_and_send()
    threads: list[str] = []
    gate_threads: list[str] = []
    real_gate = telegram_callbacks.authorized_user_gate

    def gate(**kwargs: Any) -> str | None:
        gate_threads.append(threading.current_thread().name)
        return real_gate(**kwargs)

    monkeypatch.setattr(telegram_callbacks, "authorized_user_gate", gate)

    result = await _press(
        rig,
        issued.mapping.short_id,
        run_sync=executor.write,
        dispatch=_spying_dispatch(rig, threads),
        user_id=STRANGER_USER_ID,
        query_id="q-bad",
    )

    assert not result.ok
    assert result.reason_code == "USER_NOT_AUTHORIZED"
    # The first evaluation is the one in on_callback, on the loop; the dispatcher re-checks it.
    assert gate_threads[0] == MAIN, "the user gate runs first, on the loop"
    # The refusal is journaled by the dispatcher (on the writer thread); no approval is decided.
    assert all(t.startswith(WRITER_THREAD_PREFIX) for t in threads)
    assert not any(a.status is ApprovalResult.APPROVED for a in rig.stores.approvals.values())
    assert rig.confirmed == []


async def test_an_async_dispatcher_is_still_awaited_through_the_seam(
    executor: StoreExecutor,
) -> None:
    rig = Rig()
    issued = await rig.issue_and_send()
    real = rig.desk.dispatch
    awaited: list[str] = []

    async def inner(parsed: Any, kwargs: dict[str, Any]) -> DispatchResult:
        awaited.append(threading.current_thread().name)
        return real(parsed, **kwargs)

    def dispatch(parsed: Any, **kwargs: Any) -> Any:
        return inner(parsed, kwargs)

    result = await _press(
        rig,
        issued.mapping.short_id,
        run_sync=executor.write,
        dispatch=dispatch,
        user_id=USER_ID,
        query_id="q-apr",
    )

    assert result.ok
    assert awaited == [MAIN], "an awaitable result is awaited on the loop, not lost in the worker"
