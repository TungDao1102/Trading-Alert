"""The live Telegram runner (plan 24-17, D-17, P23-R1, T-24-47/48/49/50).

The runner registers exactly one callback handler, `on_callback` with the flow's keyword set (a
non-empty `authorized_user_ids`), and uses the manual PTB lifecycle of `ShadowRuntime`. The
application is a recording fake: `build_application` is never called here and no network is used.
Through the live rig (tests/support/live_rig.py) an authorized APPROVE then CONFIRM press reaches
the registered handler and leads to exactly one `place_entry`; a stranger's press leads to none.
"""

from __future__ import annotations

import ast
import functools
import threading
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any

import pytest
import structlog
from src.adapters.telegram_callbacks import on_callback
from src.approval.confirm_core import DEMO_CONFIRM_PROFILE
from src.domain.enums import ApprovalResult
from src.domain.trade_plan import TradePlan
from src.execution.confirm_recheck import make_confirm_recheck, prefetched_provider
from src.execution.pre_placement import check_remaining_validity
from src.live.telegram_runner import BOT_TOKEN_RULE, LiveTelegramRunner
from src.ops.store_executor import WRITER_THREAD_PREFIX, StoreExecutor

from tests.shadow_fakes import (
    AUTHORIZED_USER_IDS,
    CHAT_ID,
    STRANGER_USER_ID,
    USER_ID,
    make_callback_update,
)
from tests.support.live_rig import LiveRig, forbid_real_sleep, make_live_rig, prefetch_inputs

D = Decimal
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


@pytest.fixture
def executor() -> Iterator[StoreExecutor]:
    store_executor = StoreExecutor()
    yield store_executor
    store_executor.close()


# --------------------------------------------------------------------------- #
# A recording fake of the PTB application (no network, no build_application).
# --------------------------------------------------------------------------- #


class FakeUpdater:
    def __init__(self, calls: list[str], fail_polling: bool) -> None:
        self.calls = calls
        self.fail_polling = fail_polling
        self.polling_kwargs: dict[str, Any] = {}

    async def start_polling(self, **kwargs: Any) -> None:
        self.calls.append("updater.start_polling")
        self.polling_kwargs = kwargs
        if self.fail_polling:
            raise RuntimeError("polling failed")

    async def stop(self) -> None:
        self.calls.append("updater.stop")


class FakeApplication:
    def __init__(self, *, fail_polling: bool = False) -> None:
        self.calls: list[str] = []
        self.handlers: list[Any] = []
        self.error_handlers: list[Any] = []
        self.bot = object()
        self.updater = FakeUpdater(self.calls, fail_polling)

    def add_handler(self, handler: Any) -> None:
        self.calls.append("add_handler")
        self.handlers.append(handler)

    def add_error_handler(self, callback: Any) -> None:
        self.calls.append("add_error_handler")
        self.error_handlers.append(callback)

    async def initialize(self) -> None:
        self.calls.append("initialize")

    async def start(self) -> None:
        self.calls.append("start")

    async def stop(self) -> None:
        self.calls.append("stop")

    async def shutdown(self) -> None:
        self.calls.append("shutdown")


def make_runner(
    rig: LiveRig,
    executor: StoreExecutor,
    application: FakeApplication,
    **overrides: Any,
) -> LiveTelegramRunner:
    async def prefetch(signal: Any, plan: TradePlan) -> None:
        await prefetch_inputs(
            clock=rig.clock, holder=rig.holder, limits=rig.limits, signal=signal, plan=plan
        )

    values: dict[str, Any] = {
        "application_factory": lambda: application,
        "desk": rig.wiring.desk,
        "stores": rig.stores,
        "profile": DEMO_CONFIRM_PROFILE,
        "clock": rig.clock,
        "bot": rig.bot,
        "sleep": rig.sleep,
        "service": rig.wiring.service,
        "executor": executor,
        "authorized_chat_id": CHAT_ID,
        "authorized_user_ids": AUTHORIZED_USER_IDS,
        "error_journal": rig.stores.record_journal,
        "mark_price": lambda symbol: D("50050"),
        "validity_rule": partial(
            check_remaining_validity,
            min_remaining_validity_seconds=rig.limits.min_remaining_validity_seconds,
            gtd_clock_margin=timedelta(seconds=2),
        ),
        "recheck": make_confirm_recheck(prefetched_provider(rig.holder)),
        "prefetch": prefetch,
    }
    values.update(overrides)
    return LiveTelegramRunner(**values)


async def press(handler: Any, prefix: str, short_id: str, *, query_id: str, user_id: int) -> Any:
    update = make_callback_update(
        data=f"{prefix}:{short_id}",
        chat_id=CHAT_ID,
        query_id=query_id,
        message_chat_id=CHAT_ID,
        from_user_id=user_id,
        message_id=1,
        chat_type="private",
    )
    return await handler.callback(update, None)


# --------------------------------------------------------------------------- #
# The wiring: one handler, on_callback, the user ids.
# --------------------------------------------------------------------------- #


async def test_exactly_one_handler_and_it_is_on_callback_with_the_user_ids(
    executor: StoreExecutor,
) -> None:
    rig = await make_live_rig()
    application = FakeApplication()
    runner = make_runner(rig, executor, application)

    await runner.start()

    (handler,) = application.handlers
    assert isinstance(handler.callback, functools.partial)
    assert handler.callback.func is on_callback
    keywords = handler.callback.keywords
    assert keywords["authorized_user_ids"] == AUTHORIZED_USER_IDS
    assert keywords["authorized_user_ids"], "never empty"
    assert keywords["authorized_chat_id"] == CHAT_ID
    assert keywords["run_sync"] == executor.write
    assert keywords["confirm_handler"] == runner.flow.confirm_handler
    assert keywords["approved_handler"] == runner.flow.approved_handler
    assert len(application.error_handlers) == 1
    await runner.stop()


@pytest.mark.parametrize("bad", [frozenset(), {USER_ID}, frozenset({True}), frozenset({"7"})])
async def test_an_empty_or_malformed_allow_list_is_refused_at_construction(
    executor: StoreExecutor, bad: Any
) -> None:
    rig = await make_live_rig()
    with pytest.raises(ValueError):
        make_runner(rig, executor, FakeApplication(), authorized_user_ids=bad)


def test_the_runner_source_never_calls_dispatch_callback_and_builds_no_application() -> None:
    source = (ROOT / "src" / "live" / "telegram_runner.py").read_text(encoding="utf-8")
    names = {
        node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
    }
    assert "dispatch_callback" not in names
    assert "build_application" not in names
    assert source.count("CallbackQueryHandler(") == 1


# --------------------------------------------------------------------------- #
# The lifecycle.
# --------------------------------------------------------------------------- #


async def test_start_and_stop_follow_the_manual_lifecycle_and_keep_pending_updates(
    executor: StoreExecutor,
) -> None:
    rig = await make_live_rig()
    application = FakeApplication()
    runner = make_runner(rig, executor, application)

    with structlog.testing.capture_logs() as logs:
        await runner.start()

    assert application.calls == [
        "add_handler",
        "add_error_handler",
        "initialize",
        "start",
        "updater.start_polling",
    ]
    polling = application.updater.polling_kwargs
    assert "callback_query" in polling["allowed_updates"]
    assert polling["drop_pending_updates"] is False, "a replay after a restart is the safety net"
    assert callable(polling["error_callback"])
    assert any(
        log.get("event") == "live.telegram.bot_token_rule" and log.get("rule") == BOT_TOKEN_RULE
        for log in logs
    )

    application.calls.clear()
    await runner.stop()
    assert application.calls == ["updater.stop", "stop", "shutdown"]
    application.calls.clear()
    await runner.stop()
    assert application.calls == [], "stop is idempotent"


async def test_start_twice_is_refused_and_a_polling_failure_shuts_the_application_down(
    executor: StoreExecutor,
) -> None:
    rig = await make_live_rig()
    application = FakeApplication()
    runner = make_runner(rig, executor, application)
    await runner.start()
    with pytest.raises(RuntimeError):
        await runner.start()
    await runner.stop()

    broken = FakeApplication(fail_polling=True)
    failing = make_runner(rig, executor, broken)
    with pytest.raises(RuntimeError):
        await failing.start()
    assert broken.calls[-1] == "shutdown"
    assert not failing.running


async def test_errors_are_counted_by_class_name_and_change_nothing(
    executor: StoreExecutor,
) -> None:
    rig = await make_live_rig()
    application = FakeApplication()
    runner = make_runner(rig, executor, application)
    await runner.start()

    class Conflict(Exception):
        pass

    context = type("Context", (), {"error": Conflict("secret-token-text")})()
    await application.error_handlers[0](None, context)
    application.updater.polling_kwargs["error_callback"](Conflict("x"))

    assert runner.telegram_error_counts == {"Conflict": 2}
    await runner.stop()


# --------------------------------------------------------------------------- #
# Through the rig: APPROVE then CONFIRM reach one placement; a stranger reaches none.
# --------------------------------------------------------------------------- #


async def test_an_authorized_approve_then_confirm_press_places_exactly_once(
    executor: StoreExecutor,
) -> None:
    rig = await make_live_rig()
    application = FakeApplication()
    runner = make_runner(rig, executor, application)
    await runner.start()
    (handler,) = application.handlers
    service = rig.wiring.service

    issued = await rig.issue_and_send()
    approve = await press(handler, "APR", issued.short_id, query_id="q-apr", user_id=USER_ID)
    assert approve.ok
    await rig.clock.advance(30)
    rig.set_prices()
    confirm = await press(handler, "CNF", issued.short_id, query_id="q-cnf", user_id=USER_ID)
    assert confirm.ok
    # The hook ran on the writer thread and only scheduled the placement on the loop.
    await service.drain()
    assert len(rig.fake.calls_to("place_entry")) == 1

    # A redelivery of the same CONFIRM (same callback query id) never places a second time.
    await press(handler, "CNF", issued.short_id, query_id="q-cnf", user_id=USER_ID)
    await service.drain()
    assert len(rig.fake.calls_to("place_entry")) == 1
    await runner.stop()


async def test_a_press_from_a_user_not_on_the_list_places_nothing_and_is_journaled(
    executor: StoreExecutor,
) -> None:
    rig = await make_live_rig()
    application = FakeApplication()
    runner = make_runner(rig, executor, application)
    await runner.start()
    (handler,) = application.handlers

    issued = await rig.issue_and_send()
    refused = await press(
        handler, "APR", issued.short_id, query_id="q-bad", user_id=STRANGER_USER_ID
    )

    assert not refused.ok
    assert refused.reason_code == "USER_NOT_AUTHORIZED"
    assert not any(a.status is ApprovalResult.APPROVED for a in rig.stores.approvals.values())
    assert rig.stores.journal, "the refusal is journaled"
    await rig.clock.advance(30)
    rig.set_prices()
    confirm = await press(
        handler, "CNF", issued.short_id, query_id="q-cnf", user_id=STRANGER_USER_ID
    )
    assert not confirm.ok
    assert rig.wiring.service.outstanding == 0
    assert rig.fake.calls_to("place_entry") == []
    await runner.stop()


async def test_the_dispatch_of_a_press_runs_on_the_writer_thread(
    executor: StoreExecutor,
) -> None:
    rig = await make_live_rig()
    application = FakeApplication()
    runner = make_runner(rig, executor, application)
    await runner.start()
    (handler,) = application.handlers
    threads: list[str] = []
    real_record = rig.stores.record_journal

    def record(event: Any) -> None:
        threads.append(threading.current_thread().name)
        real_record(event)

    rig.stores.record_journal = record  # type: ignore[method-assign]

    issued = await rig.issue_and_send()
    threads.clear()
    assert (await press(handler, "APR", issued.short_id, query_id="q-apr", user_id=USER_ID)).ok

    assert threads, "the decision was journaled"
    # The decision rows (dispatch) are written on the writer thread. The later card issue
    # (`record_issued` in the approved handler) is still inline: a known gap, see the SUMMARY.
    decision_rows = threads[:2]
    assert all(name.startswith(WRITER_THREAD_PREFIX) for name in decision_rows), threads
    await runner.stop()


# --------------------------------------------------------------------------- #
# The startup hooks.
# --------------------------------------------------------------------------- #


async def test_expire_on_restart_expires_the_outstanding_confirm_once(
    executor: StoreExecutor,
) -> None:
    rig = await make_live_rig()
    first = FakeApplication()
    old_process = make_runner(rig, executor, first)
    await old_process.start()
    (handler,) = first.handlers
    issued = await rig.issue_and_send()
    assert (await press(handler, "APR", issued.short_id, query_id="q-apr", user_id=USER_ID)).ok
    await old_process.stop()

    new_process = make_runner(rig, executor, FakeApplication())
    expired = new_process.expire_on_restart(rig.clock.now())

    assert expired == [rig.approve_row().approval_id]
    assert new_process.expire_on_restart(rig.clock.now()) == []
    types = [event.event_type for event in rig.stores.journal]
    assert "DEMO_CONFIRM_EXPIRED" in types


async def test_finalize_expired_once_edits_an_expired_card_once(
    executor: StoreExecutor,
) -> None:
    rig = await make_live_rig()
    application = FakeApplication()
    runner = make_runner(rig, executor, application)
    await runner.start()
    (handler,) = application.handlers
    issued = await rig.issue_and_send()
    assert (await press(handler, "APR", issued.short_id, query_id="q-apr", user_id=USER_ID)).ok
    await rig.clock.advance(61)

    finalized = await runner.finalize_expired_once(rig.clock.now())

    assert finalized == [issued.short_id]
    assert await runner.finalize_expired_once(rig.clock.now()) == []
    await runner.stop()
