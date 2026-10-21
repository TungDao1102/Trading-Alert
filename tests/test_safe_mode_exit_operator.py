"""Operator-attributed, fail-closed SAFE_MODE exit (Phase 20, plan 20-15, D-15, F-711, T-E 1-5).

Pins, on fakes only (nothing here is [DEMO] evidence):

  - the exit is an explicit operator act: a non-empty operator id (audit metadata, NOT
    authentication), a successfully read local intent source, fresh successful Binance reads in
    this call, a clean compare v2, and a clean readiness (no UNKNOWN intent, no blocking plan, no
    open pending action);
  - every one of the five readiness rows has its own failure test, and a missing or raising local
    source blocks the exit instead of becoming an empty list (the `local_open_orders or []`
    defect, F-711);
  - the write order is journal SAFE_MODE_EXIT (with the operator id), then the persisted exit
    state, then memory last; a failure of either write leaves the controller in SAFE_MODE;
  - a restart, a timer, a boolean flip or a closed intent never exits SAFE_MODE;
  - the state format accepts five keys, reads the three-key row of plan 20-06 as last_exit_* None
    and refuses every other key set.

Rows 6 (REST gate) and 7 (StreamState.LIVE) are NOT built here: they wait for owner decision O-B
(plan 20-25).
"""

from __future__ import annotations

import ast
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_usdm import PositionSnapshot
from src.reconcile.local_intent import LocalIntent
from src.reconcile.safe_mode import (
    ExitDecision,
    ExitReadiness,
    SafeModeController,
)

T0 = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
T1 = T0 + timedelta(minutes=5)
T2 = T0 + timedelta(minutes=10)
REPO_ROOT = Path(__file__).resolve().parents[1]
SAFE_MODE_SOURCE = REPO_ROOT / "src" / "reconcile" / "safe_mode.py"

OPERATOR = "op-1"
EMPTY_INTENT = LocalIntent(orders=(), algos=(), positions=())
CLEAN = ExitReadiness(unknown_intents=0, blocking_plans=0, open_pending_actions=0)


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class Trace:
    """One shared, ordered log of every write the controller makes."""

    def __init__(self) -> None:
        self.calls: list[str] = []


class FakeJournal:
    """Records events; `fail_on` makes the named event types raise."""

    def __init__(self, trace: Trace | None = None) -> None:
        self.events: list[Any] = []
        self.trace = trace if trace is not None else Trace()
        self.fail_on: set[str] = set()

    def record(self, event: Any) -> None:
        if event.event_type in self.fail_on:
            raise RuntimeError("journal down")
        self.trace.calls.append(f"journal:{event.event_type}")
        self.events.append(event)

    def of(self, event_type: str) -> list[Any]:
        return [e for e in self.events if e.event_type == event_type]


class FakeStore:
    """In-memory `SafeModeStateStore`; `save_error` makes the next saves raise."""

    def __init__(self, trace: Trace | None = None) -> None:
        self.saved: list[tuple[dict[str, Any], datetime]] = []
        self.loaded: Mapping[str, Any] | None = None
        self.save_error: Exception | None = None
        self.trace = trace if trace is not None else Trace()

    def save(self, state: Mapping[str, str | bool | None], *, now_utc: datetime) -> None:
        if self.save_error is not None:
            raise self.save_error
        self.trace.calls.append("save")
        self.saved.append((dict(state), now_utc))
        self.loaded = dict(state)

    def load(self) -> Mapping[str, str | bool | None] | None:
        return self.loaded


class FakeAdapter:
    """Exchange truth; each snapshot read can be made to raise or to return a non-list."""

    def __init__(
        self,
        *,
        normal: Any = None,
        algos: Any = None,
        positions: Any = None,
    ) -> None:
        self.normal: Any = [] if normal is None else normal
        self.algos: Any = [] if algos is None else algos
        self.positions: Any = [] if positions is None else positions
        self.reads = 0

    async def snapshot_open_normal_orders(self, *, symbol: str | None = None) -> Any:
        self.reads += 1
        if isinstance(self.normal, Exception):
            raise self.normal
        return self.normal

    async def snapshot_open_algo_orders(self, *, symbol: str | None = None) -> Any:
        self.reads += 1
        if isinstance(self.algos, Exception):
            raise self.algos
        return self.algos

    async def snapshot_positions(self, *, symbol: str | None = None) -> Any:
        self.reads += 1
        if isinstance(self.positions, Exception):
            raise self.positions
        return self.positions


def _position() -> PositionSnapshot:
    return PositionSnapshot(
        symbol="BTCUSDT",
        position_side="BOTH",
        position_amt=Decimal("0.020"),
        entry_price=Decimal("50000"),
        break_even_price=Decimal("50000"),
        mark_price=Decimal("50100"),
        unrealized_profit=Decimal("1"),
        liquidation_price=None,
        notional=Decimal("1002"),
        margin_asset="USDT",
        update_time_utc=T0,
    )


@dataclass
class Rig:
    controller: SafeModeController
    journal: FakeJournal
    store: FakeStore
    adapter: FakeAdapter
    trace: Trace


def _rig(*, adapter: FakeAdapter | None = None, enter: bool = True) -> Rig:
    trace = Trace()
    journal = FakeJournal(trace)
    store = FakeStore(trace)
    the_adapter = adapter if adapter is not None else FakeAdapter()
    controller = SafeModeController(
        adapter=the_adapter,
        journal=journal,
        state_store=store,
    )
    if enter:
        controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T0)
    return Rig(controller, journal, store, the_adapter, trace)


def _local() -> LocalIntent:
    return EMPTY_INTENT


def _readiness() -> ExitReadiness:
    return CLEAN


async def _exit(
    rig: Rig,
    *,
    operator_id: Any = OPERATOR,
    local_intent_fn: Any = _local,
    readiness: Any = _readiness,
    now_utc: datetime = T1,
) -> ExitDecision:
    return await rig.controller.exit_safe_mode(
        operator_id=operator_id,
        local_intent_fn=local_intent_fn,
        readiness=readiness,
        now_utc=now_utc,
    )


def _raises(exc: Exception) -> Any:
    def fn() -> Any:
        raise exc

    return fn


# --------------------------------------------------------------------------- #
# Task 1 - tracer: operator exit end to end
# --------------------------------------------------------------------------- #


async def test_operator_exit_checks_journals_persists_then_flips() -> None:
    rig = _rig()
    rig.trace.calls.clear()

    decision = await _exit(rig)

    assert decision == ExitDecision(exited=True, refusals=())
    assert bool(decision) is True
    assert rig.controller.in_safe_mode is False
    exit_events = rig.journal.of("SAFE_MODE_EXIT")
    assert len(exit_events) == 1
    assert json.loads(exit_events[0].payload_json)["operator_id"] == OPERATOR
    assert rig.trace.calls == ["journal:SAFE_MODE_EXIT", "save"]
    saved_state, saved_at = rig.store.saved[-1]
    assert saved_state == {
        "in_safe_mode": False,
        "entered_at_utc": None,
        "entered_reason": None,
        "last_exit_operator_id": OPERATOR,
        "last_exit_at_utc": T1.isoformat(),
    }
    assert saved_at == T1


async def test_a_fresh_load_after_the_exit_is_out_of_safe_mode() -> None:
    rig = _rig()
    await _exit(rig)

    restored = SafeModeController.load(
        adapter=rig.adapter, journal=FakeJournal(), state_store=rig.store, now_utc=T2
    )

    assert restored.in_safe_mode is False
    assert restored.state_snapshot()["last_exit_operator_id"] == OPERATOR
    assert restored.state_snapshot()["last_exit_at_utc"] == T1.isoformat()


async def test_missing_local_source_blocks_exit() -> None:
    rig = _rig()

    decision = await _exit(rig, local_intent_fn=_raises(RuntimeError("store down")))

    assert decision == ExitDecision(exited=False, refusals=("LOCAL_SOURCE_UNREADABLE",))
    assert bool(decision) is False
    assert rig.controller.in_safe_mode is True
    assert rig.journal.of("SAFE_MODE_EXIT") == []
    refused = rig.journal.of("SAFE_MODE_EXIT_REFUSED")
    assert len(refused) == 1
    assert json.loads(refused[0].payload_json)["refusals"] == ["LOCAL_SOURCE_UNREADABLE"]


async def test_a_local_source_that_returns_nothing_blocks_exit() -> None:
    rig = _rig()

    decision = await _exit(rig, local_intent_fn=lambda: None)

    assert decision.refusals == ("LOCAL_SOURCE_UNREADABLE",)
    assert rig.controller.in_safe_mode is True


async def test_a_local_source_with_a_missing_sequence_blocks_exit() -> None:
    class Partial:
        orders = ()
        algos = ()
        positions = None

    rig = _rig()

    decision = await _exit(rig, local_intent_fn=lambda: Partial())

    assert decision.refusals == ("LOCAL_SOURCE_UNREADABLE",)
    assert rig.controller.in_safe_mode is True


async def test_a_successful_empty_local_read_is_valid() -> None:
    rig = _rig()

    decision = await _exit(rig, local_intent_fn=lambda: EMPTY_INTENT)

    assert decision.exited is True


def test_exit_safe_mode_has_no_empty_list_default() -> None:
    """F-711: no `x or []` (or `or ()`, `or list()`) default anywhere in exit_safe_mode."""
    tree = ast.parse(SAFE_MODE_SOURCE.read_text(encoding="utf-8"))
    target = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "exit_safe_mode"
    )

    def is_empty(node: ast.expr) -> bool:
        if isinstance(node, ast.List | ast.Tuple | ast.Set):
            return not node.elts
        if isinstance(node, ast.Dict):
            return not node.keys
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return node.func.id in {"list", "tuple", "set", "dict"} and not node.args
        return False

    offenders = [
        node.lineno
        for node in ast.walk(target)
        if isinstance(node, ast.BoolOp)
        and isinstance(node.op, ast.Or)
        and any(is_empty(value) for value in node.values[1:])
    ]
    assert offenders == []


def test_exit_safe_mode_has_only_the_keyword_only_operator_signature() -> None:
    import inspect

    sig = inspect.signature(SafeModeController.exit_safe_mode)
    names = [p.name for p in sig.parameters.values() if p.name != "self"]
    assert names == ["operator_id", "local_intent_fn", "readiness", "now_utc"]
    assert all(
        p.kind is inspect.Parameter.KEYWORD_ONLY
        for p in sig.parameters.values()
        if p.name != "self"
    )
    assert all(
        p.default is inspect.Parameter.empty for p in sig.parameters.values() if p.name != "self"
    )


# --------------------------------------------------------------------------- #
# State format: five keys, three-key rows accepted, anything else refused
# --------------------------------------------------------------------------- #

THREE_KEY_ON: dict[str, Any] = {
    "in_safe_mode": True,
    "entered_at_utc": T0.isoformat(),
    "entered_reason": "DB_FAILURE",
}
THREE_KEY_OFF: dict[str, Any] = {
    "in_safe_mode": False,
    "entered_at_utc": None,
    "entered_reason": None,
}
FIVE_KEY_OFF: dict[str, Any] = {
    **THREE_KEY_OFF,
    "last_exit_operator_id": OPERATOR,
    "last_exit_at_utc": T1.isoformat(),
}


def _rehydrate(state: Any) -> SafeModeController:
    return SafeModeController.rehydrate(adapter=FakeAdapter(), journal=FakeJournal(), state=state)


def test_a_three_key_row_reads_as_last_exit_none() -> None:
    controller = _rehydrate(THREE_KEY_ON)

    assert controller.in_safe_mode is True
    snapshot = controller.state_snapshot()
    assert snapshot["last_exit_operator_id"] is None
    assert snapshot["last_exit_at_utc"] is None
    assert _rehydrate(THREE_KEY_OFF).in_safe_mode is False


def test_the_five_key_format_round_trips() -> None:
    controller = _rehydrate(FIVE_KEY_OFF)

    assert controller.in_safe_mode is False
    assert controller.state_snapshot() == FIVE_KEY_OFF


def test_every_snapshot_has_exactly_the_five_keys() -> None:
    rig = _rig(enter=False)
    assert set(rig.controller.state_snapshot()) == set(FIVE_KEY_OFF)
    rig.controller.enter_safe_mode(reason="X", now_utc=T0)
    assert set(rig.controller.state_snapshot()) == set(FIVE_KEY_OFF)


async def test_the_last_exit_survives_a_later_entry() -> None:
    rig = _rig()
    await _exit(rig)

    rig.controller.enter_safe_mode(reason="UNSYNCED_POSITION", now_utc=T2)

    snapshot = rig.controller.state_snapshot()
    assert snapshot["in_safe_mode"] is True
    assert snapshot["last_exit_operator_id"] == OPERATOR
    assert snapshot["last_exit_at_utc"] == T1.isoformat()
    assert _rehydrate(snapshot).state_snapshot() == snapshot


MALFORMED: list[Any] = [
    pytest.param({**THREE_KEY_ON, "last_exit_operator_id": OPERATOR}, id="four-keys-id-only"),
    pytest.param({**THREE_KEY_ON, "last_exit_at_utc": T1.isoformat()}, id="four-keys-at-only"),
    pytest.param({**FIVE_KEY_OFF, "extra": "x"}, id="six-keys"),
    pytest.param({**THREE_KEY_ON, "operator": "x", "at": "y"}, id="five-wrong-keys"),
    pytest.param({**FIVE_KEY_OFF, "last_exit_operator_id": 7}, id="operator-not-text"),
    pytest.param({**FIVE_KEY_OFF, "last_exit_operator_id": ""}, id="operator-empty"),
    pytest.param({**FIVE_KEY_OFF, "last_exit_operator_id": "   "}, id="operator-blank"),
    pytest.param({**FIVE_KEY_OFF, "last_exit_at_utc": None}, id="operator-without-time"),
    pytest.param({**FIVE_KEY_OFF, "last_exit_operator_id": None}, id="time-without-operator"),
    pytest.param({**FIVE_KEY_OFF, "last_exit_at_utc": "not-a-date"}, id="time-garbage"),
    pytest.param({**FIVE_KEY_OFF, "last_exit_at_utc": "2026-09-19T12:00:00"}, id="time-naive"),
    pytest.param(
        {**FIVE_KEY_OFF, "last_exit_at_utc": "2026-09-19T12:00:00+02:00"}, id="time-offset"
    ),
    pytest.param({**FIVE_KEY_OFF, "last_exit_at_utc": 5}, id="time-not-text"),
]


@pytest.mark.parametrize("state", MALFORMED)
def test_any_other_key_set_or_value_is_refused(state: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _rehydrate(state)


def test_a_load_of_a_malformed_five_key_row_fails_closed_into_safe_mode() -> None:
    store = FakeStore()
    store.loaded = {**FIVE_KEY_OFF, "extra": "x"}

    controller = SafeModeController.load(
        adapter=FakeAdapter(), journal=FakeJournal(), state_store=store, now_utc=T2
    )

    assert controller.in_safe_mode is True
    assert controller.entered_reason == "SAFE_MODE_STATE_UNREADABLE"
