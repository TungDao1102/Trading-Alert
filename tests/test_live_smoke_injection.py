"""`/demo_signal`: the owner-triggered, DEMO-only injection into the running process (plan 24-27B).

The command is exercised on the composed rig (tests/support/live_composed_rig.py): the signed
adapter's readings come from the rig's edge, the request lands on the process's own
`DemoSmokeSignalSource`, and the composed pump then sends the approval card. A request made by the
command is then placed through the same CONFIRM path as the tracer.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from src.adapters.binance_client import Environment
from src.live.signal_source import DemoSmokeSignalSource
from src.live.smoke_injection import (
    CODE_ALREADY_QUEUED,
    CODE_BAD_USAGE,
    CODE_FILTERS_UNAVAILABLE,
    CODE_QUEUED,
    EVENT_DEMO_SIGNAL,
    EVENT_DEMO_SIGNAL_REJECTED,
    DemoSignalCommand,
    build_demo_signal_command,
)
from src.live.wiring import TASK_SIGNAL_PUMP

from tests.shadow_fakes import CHAT_ID, OTHER_USER_ID, USER_ID
from tests.support.live_composed_rig import ComposedRig, make_composed_rig
from tests.support.live_rig import forbid_real_sleep


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def update(*, chat_id: int = CHAT_ID, user_id: int = USER_ID, chat_type: str = "private") -> Any:
    return SimpleNamespace(
        update_id=11,
        effective_chat=SimpleNamespace(id=chat_id, type=chat_type),
        effective_user=SimpleNamespace(id=user_id),
    )


def args(*values: str) -> Any:
    return SimpleNamespace(args=list(values))


async def prepared(tmp_path: Path) -> tuple[ComposedRig, DemoSignalCommand]:
    rig = make_composed_rig(tmp_path)
    wiring = await rig.prepare()
    assert wiring.demo_signal is not None
    return rig, wiring.demo_signal


def codes(rig: ComposedRig) -> list[str]:
    out = []
    for event in rig.memory.journal.events:
        if event.event_type in (EVENT_DEMO_SIGNAL, EVENT_DEMO_SIGNAL_REJECTED):
            payload = json.loads(event.payload_json)
            out.append(payload.get("code") or payload.get("reason_code"))
    return out


async def test_the_command_queues_one_request_on_the_process_source(tmp_path: Path) -> None:
    rig, command = await prepared(tmp_path)
    assert command.source is rig.source
    assert await command.handle(update(), args("fill")) is True
    assert rig.source.pending == 1
    assert codes(rig) == [CODE_QUEUED]
    # No order, no card: the command never places and never sends a card by itself.
    assert rig.fake.calls_to("place_entry") == []
    assert rig.bot.sent[-1].text == "Queued a fill request; the approval card follows."


async def test_the_default_scenario_is_far(tmp_path: Path) -> None:
    rig, command = await prepared(tmp_path)
    assert await command.handle(update(), args()) is True
    request = await rig.source.next_request()
    assert request is not None
    entry = (request.plan.entry_min_price + request.plan.entry_max_price) / 2
    assert request.bar_close_price is not None
    assert entry < request.bar_close_price  # far: the entry rests below the mark


async def test_a_second_command_while_one_waits_is_refused(tmp_path: Path) -> None:
    rig, command = await prepared(tmp_path)
    assert await command.handle(update(), args("far"))
    assert await command.handle(update(), args("far")) is False
    assert rig.source.pending == 1
    assert codes(rig) == [CODE_QUEUED, CODE_ALREADY_QUEUED]


@pytest.mark.parametrize("bad", [("nonsense",), ("far", "fill")])
async def test_a_bad_usage_changes_nothing(tmp_path: Path, bad: tuple[str, ...]) -> None:
    rig, command = await prepared(tmp_path)
    assert await command.handle(update(), args(*bad)) is False
    assert rig.source.pending == 0
    assert codes(rig) == [CODE_BAD_USAGE]


@pytest.mark.parametrize(
    "caller",
    [
        {"chat_id": CHAT_ID + 1},
        {"user_id": 5},
        {"chat_type": "group"},
    ],
)
async def test_an_unauthorized_caller_changes_nothing_and_is_journaled(
    tmp_path: Path, caller: dict[str, Any]
) -> None:
    rig, command = await prepared(tmp_path)
    assert await command.handle(update(**caller), args("far")) is False
    assert rig.source.pending == 0
    assert len(codes(rig)) == 1
    assert rig.memory.journal.by_type(EVENT_DEMO_SIGNAL_REJECTED)
    assert rig.bot.sent[-1].text == "Rejected"


async def test_the_other_allow_listed_user_may_command(tmp_path: Path) -> None:
    rig, command = await prepared(tmp_path)
    assert await command.handle(update(user_id=OTHER_USER_ID), args("far")) is True


async def test_an_unreadable_demo_state_queues_nothing(tmp_path: Path) -> None:
    rig, command = await prepared(tmp_path)

    async def boom(*_a: Any, **_k: Any) -> Any:
        raise OSError("TEST_ONLY readings down")

    command._adapter = SimpleNamespace(exchange_info=boom)
    assert await command.handle(update(), args("far")) is False
    assert rig.source.pending == 0
    (journaled,) = [
        json.loads(e.payload_json) for e in rig.memory.journal.by_type(EVENT_DEMO_SIGNAL)
    ]
    assert journaled["code"] == CODE_FILTERS_UNAVAILABLE
    assert journaled["error_class"] == "OSError"
    assert "TEST_ONLY" not in json.dumps(journaled), "never the message text"


async def test_a_request_made_by_the_command_is_placed_by_confirm_exactly_once(
    tmp_path: Path,
) -> None:
    rig, command = await prepared(tmp_path)
    wiring = rig.wiring
    assert wiring is not None
    assert await command.handle(update(), args("fill"))
    (spec,) = [s for s in wiring.specs if s.name == TASK_SIGNAL_PUMP]
    await spec.run()
    short_id = next(iter(rig.memory.shadow.mappings))
    assert (await rig.press("APR", short_id, query_id="q-apr")).ok
    await rig.clock.advance(30)
    rig.set_prices()
    assert (await rig.press("CNF", short_id, query_id="q-cnf")).ok
    await wiring.service.drain()
    assert len(rig.fake.calls_to("place_entry")) == 1


def test_the_command_is_built_for_demo_with_the_smoke_source_only() -> None:
    parameter_set = None
    source = SimpleNamespace()
    assert (
        build_demo_signal_command(mode=Environment.LIVE, source=source, parameter_set=parameter_set)
        is None
    )
    assert build_demo_signal_command(mode=Environment.DEMO, source=source) is None
    with pytest.raises(ValueError):
        DemoSignalCommand(
            mode=Environment.LIVE,
            authorized_chat_id=1,
            authorized_user_ids=frozenset({1}),
            source=DemoSmokeSignalSource.__new__(DemoSmokeSignalSource),
            adapter=None,
            equity=None,
            risk_rate=None,  # type: ignore[arg-type]
            symbol="BTCUSDT",
            record=None,  # type: ignore[arg-type]
            clock=None,  # type: ignore[arg-type]
            reply=None,  # type: ignore[arg-type]
        )
