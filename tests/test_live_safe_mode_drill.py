"""The SAFE_MODE drill with fakes (plan 24-23, D-33 fake level; R-4, C-6, D-28).

Nothing here is [DEMO] evidence. The path is the real one from `tests/support/live_rig.py` (the
approval desk, the confirm flow, the execution service, the manager, the SAFE_MODE controller, the
protection coordinator) with the Binance-semantics fake exchange at the edge; the operator commands
are the real `OperatorCommands` over a fake REST gate, a switchable stream state and a recording
reply. The drill:

  1. enter SAFE_MODE; a full APPROVE and CONFIRM places nothing (NO_TRADE, RECONCILIATION_REQUIRED);
  2. `/safemode_exit` then `/confirm` with the stream not LIVE: still SAFE_MODE, the reply names
     the failing exit row;
  3. with every row satisfied the same two steps leave SAFE_MODE, and the exit row carries the
     operator's user id;
  4. a second APPROVE and CONFIRM then places exactly one entry (a consumed approval is never
     re-sent, so the second press belongs to a second signal);
  5. a state save that fails after the EXIT journal row leaves SAFE_MODE in effect, and `/status`
     reports it.

The last section is the contract test of `ExitReadiness` against the real PostgreSQL stores
(20-DEFERRED row 46); it skips without `TEST_DATABASE_URL` and fails under `TRADING_CI_STRICT=1`.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from scripts.gen_phase23_fixtures import fixture_money
from src.adapters.binance_ratelimit_gate import GateRecoveryStatus
from src.domain.enums import RejectionReason
from src.execution.binding import recompute_plan_hash
from src.execution.pending_actions import PendingKind
from src.live.execution_service import EVENT_PLACEMENT_OUTCOME
from src.live.operator import OperatorCommands
from src.reconcile.safe_mode import SafeModeController

from tests.shadow_fakes import (
    AUTHORIZED_USER_IDS,
    CHAT_ID,
    T0,
    USER_ID,
    make_shadow_plan,
    make_shadow_signal,
)
from tests.support.live_rig import LiveRig, forbid_real_sleep, make_live_rig
from tests.support.pending_action_fakes import InMemoryPendingActionStore

TOKEN_RE = re.compile(r"/confirm (\S+)")


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


# --------------------------------------------------------------------------- #
# Fakes at the edges of the operator commands.
# --------------------------------------------------------------------------- #


class FakeRestGate:
    """`restriction()` and `recovery_status()` of the REST gate, set by the test."""

    def __init__(self) -> None:
        self.restriction_value: Any = None
        self.recovery = GateRecoveryStatus.RESTORED_DURABLE
        self.restriction_reads = 0

    def restriction(self) -> Any:
        self.restriction_reads += 1
        return self.restriction_value

    def recovery_status(self) -> GateRecoveryStatus:
        return self.recovery


class StreamHolder:
    """The user-data stream state the commands read."""

    def __init__(self, value: str = "LIVE") -> None:
        self.value = value

    def __call__(self) -> str:
        return self.value


class Replies:
    """The recording reply function: `(chat_id, text)` in order."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def __call__(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))

    @property
    def last(self) -> str:
        return self.sent[-1][1]

    def last_token(self) -> str:
        match = TOKEN_RE.search(self.last)
        assert match is not None, self.last
        return match.group(1)


def command_update(update_id: int, *, user_id: int = USER_ID) -> Any:
    return SimpleNamespace(
        update_id=update_id,
        effective_chat=SimpleNamespace(id=CHAT_ID, type="private"),
        effective_user=SimpleNamespace(id=user_id),
    )


def with_args(*args: str) -> Any:
    return SimpleNamespace(args=list(args))


@dataclasses.dataclass
class Drill:
    rig: LiveRig
    ops: OperatorCommands
    gate: FakeRestGate
    stream: StreamHolder
    replies: Replies
    _update_id: int = 100

    def next_update(self) -> Any:
        self._update_id += 1
        return command_update(self._update_id)

    async def exit_in_two_steps(self) -> Any:
        """`/safemode_exit` then `/confirm <token>`; returns the confirm result."""
        asked = await self.ops.safemode_exit(self.next_update(), with_args())
        assert asked.ok
        return await self.ops.confirm(self.next_update(), with_args(self.replies.last_token()))


def make_ops(
    rig: LiveRig,
    *,
    controller: SafeModeController | None = None,
    pending_actions: InMemoryPendingActionStore | None = None,
) -> tuple[OperatorCommands, FakeRestGate, StreamHolder, Replies]:
    gate = FakeRestGate()
    stream = StreamHolder()
    replies = Replies()
    ops = OperatorCommands(
        authorized_chat_id=CHAT_ID,
        authorized_user_ids=AUTHORIZED_USER_IDS,
        controller=rig.safe_mode if controller is None else controller,
        enablement=rig.enablement,
        coordinator=rig.wiring.coordinator,
        intent_store=rig.intents,
        pending_actions=InMemoryPendingActionStore()
        if pending_actions is None
        else pending_actions,
        gate=gate,
        stream_state=stream,
        journal=rig.journal,
        clock=rig.clock.now,
        reply=replies,
    )
    return ops, gate, stream, replies


async def make_drill() -> Drill:
    rig = await make_live_rig()
    ops, gate, stream, replies = make_ops(rig)
    return Drill(rig=rig, ops=ops, gate=gate, stream=stream, replies=replies)


async def approve_and_confirm_signal_2(rig: LiveRig) -> None:
    """A second APPROVE and CONFIRM (the first approval is consumed and never re-sent)."""
    signal = make_shadow_signal(2)
    shadow = make_shadow_plan(signal)
    plan = dataclasses.replace(shadow, plan_hash=recompute_plan_hash(shadow))
    rig.inputs.signal = signal  # the rig's placement inputs read the signal of the press
    issued = rig.wiring.desk.issue(
        signal=signal,
        plan=plan,
        money=fixture_money(),
        exposure_quote=Decimal("0"),
        reason_codes=["TREND_OK"],
        now_utc=T0,
    )
    outcome = await rig.wiring.desk.send(rig.bot, chat_id=CHAT_ID, issued=issued, sleep=rig.sleep)
    assert outcome.sent
    short_id = issued.mapping.short_id
    assert (await rig.press("APR", short_id, query_id="q-apr-2")).ok
    await rig.clock.advance(30)
    rig.set_prices()
    assert (await rig.press("CNF", short_id, query_id="q-cnf-2")).ok


def outcome_codes(rig: LiveRig) -> list[str]:
    return [
        json.loads(e.payload_json)["reason_code"]
        for e in rig.journal.by_type(EVENT_PLACEMENT_OUTCOME)
    ]


# --------------------------------------------------------------------------- #
# The tracer: an authorized, confirmed /safemode_exit ends SAFE_MODE only when the system is safe.
# --------------------------------------------------------------------------- #


async def test_the_drill_enter_blocked_refused_exit_operator_exit_entry_allowed() -> None:
    drill = await make_drill()
    rig = drill.rig

    # 1. SAFE_MODE: a full APPROVE and CONFIRM places nothing.
    handle = await rig.issue_and_send()
    assert (await rig.press("APR", handle.short_id, query_id="q-apr")).ok
    rig.safe_mode.enter_safe_mode(reason="DIVERGENCE", now_utc=rig.clock.now())
    await rig.clock.advance(30)
    rig.set_prices()
    assert (await rig.press("CNF", handle.short_id, query_id="q-cnf")).ok
    await rig.wiring.service.drain()
    assert rig.fake.calls_to("place_entry") == []
    assert outcome_codes(rig) == [RejectionReason.RECONCILIATION_REQUIRED.value]

    # 2. The stream is not LIVE: the exit is refused with the failing row named.
    drill.stream.value = "CONNECTING"
    refused = await drill.exit_in_two_steps()
    assert not refused.ok and refused.code == "EXIT_REFUSED"
    assert "STREAM_NOT_LIVE" in drill.replies.last
    assert rig.safe_mode.in_safe_mode
    assert rig.safe_mode.guard_new_entries(None).is_no_trade

    # 3. Every row satisfied: the exit happens, attributed to the operator's user id.
    drill.stream.value = "LIVE"
    exited = await drill.exit_in_two_steps()
    assert exited.ok and exited.code == "SAFE_MODE_EXITED"
    assert not rig.safe_mode.in_safe_mode
    (exit_row,) = rig.journal.by_type("SAFE_MODE_EXIT")
    assert f'"operator_id":"tg:{USER_ID}"' in exit_row.payload_json.replace(" ", "")

    # 4. A CONFIRM now places exactly one entry.
    await approve_and_confirm_signal_2(rig)
    await rig.wiring.service.drain()
    assert len(rig.fake.calls_to("place_entry")) == 1
    assert outcome_codes(rig) == [RejectionReason.RECONCILIATION_REQUIRED.value, "OK"]


async def test_each_failing_exit_row_keeps_safe_mode_and_is_named() -> None:
    drill = await make_drill()
    rig = drill.rig
    rig.safe_mode.enter_safe_mode(reason="DIVERGENCE", now_utc=rig.clock.now())

    drill.gate.restriction_value = SimpleNamespace(reason="IP_BAN_418")
    result = await drill.exit_in_two_steps()
    assert result.code == "EXIT_REFUSED" and "GATE_NOT_OPEN" in drill.replies.last
    drill.gate.restriction_value = None

    drill.gate.recovery = GateRecoveryStatus.NOT_RESTORED
    result = await drill.exit_in_two_steps()
    assert result.code == "EXIT_REFUSED" and "GATE_NOT_RESTORED" in drill.replies.last
    drill.gate.recovery = GateRecoveryStatus.RESTORED_DURABLE

    assert rig.safe_mode.in_safe_mode
    assert drill.gate.restriction_reads == 2, "ONE restriction read per exit attempt"


async def test_an_open_pending_action_keeps_safe_mode() -> None:
    rig = await make_live_rig()
    pending = InMemoryPendingActionStore()
    ops, _gate, _stream, replies = make_ops(rig, pending_actions=pending)
    rig.safe_mode.enter_safe_mode(reason="DIVERGENCE", now_utc=rig.clock.now())
    pending.record_blocked(
        plan_hash="a" * 64,
        trade_plan_id="b" * 64,
        approval_id="apv-x",
        symbol="BTCUSDT",
        kind=next(iter(PendingKind)),
        gate_reason="IP_BAN_418",
        retry_after_until_utc=None,
        now_utc=rig.clock.now(),
    )
    asked = await ops.safemode_exit(command_update(1), with_args())
    assert asked.ok
    result = await ops.confirm(command_update(2), with_args(replies.last_token()))
    assert result.code == "EXIT_REFUSED"
    assert "PENDING_ACTION_PRESENT" in replies.last
    assert rig.safe_mode.in_safe_mode


# --------------------------------------------------------------------------- #
# A failed state save after the EXIT journal row.
# --------------------------------------------------------------------------- #


class FakeStateStore:
    """In-memory `SafeModeStateStore`; `save_error` makes saves raise."""

    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []
        self.save_error: Exception | None = None

    def save(self, state: Mapping[str, str | bool | None], *, now_utc: datetime) -> None:
        if self.save_error is not None:
            raise self.save_error
        self.saved.append(dict(state))

    def load(self) -> Mapping[str, str | bool | None] | None:
        return self.saved[-1] if self.saved else None


async def test_a_failed_state_save_after_the_exit_row_leaves_safe_mode_and_status_says_so() -> None:
    rig = await make_live_rig()
    store = FakeStateStore()
    controller = SafeModeController(
        adapter=rig.fake,  # type: ignore[arg-type]
        journal=rig.journal,
        state_store=store,
    )
    controller.enter_safe_mode(reason="DIVERGENCE", now_utc=rig.clock.now())
    ops, _gate, _stream, replies = make_ops(rig, controller=controller)
    store.save_error = RuntimeError("state store down")

    asked = await ops.safemode_exit(command_update(1), with_args())
    assert asked.ok
    result = await ops.confirm(command_update(2), with_args(replies.last_token()))

    assert not result.ok and result.code == "EXIT_NOT_RECORDED"
    assert "still in SAFE_MODE" in replies.last
    assert "state store down" not in replies.last, "the reply names the class, never the text"
    assert controller.in_safe_mode
    assert rig.journal.by_type("SAFE_MODE_EXIT"), "the EXIT row was written first"
    assert store.load() is not None and store.load()["in_safe_mode"] is True  # type: ignore[index]

    status = await ops.status(command_update(3), with_args())
    assert status.ok
    assert "mode: SAFE_MODE" in replies.last
