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

Rows 6 (REST gate open and restored) and 7 (StreamState.LIVE) were accepted by owner decision O-B
"accept-both" (plan 20-25, 2026-10-21); their failure tests are in the last section of this file.
Every other test here uses healthy fakes for them.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from src.adapters.binance_usdm import PositionSnapshot
from src.reconcile.local_intent import LocalIntent
from src.reconcile.safe_mode import (
    ExitDecision,
    ExitReadiness,
    SafeModeController,
    build_exit_readiness,
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


def _gate_healthy() -> tuple[str | None, str]:
    """Row 6 healthy fake: no restriction and a durably restored gate (owner decision O-B)."""
    return (None, "RESTORED_DURABLE")


def _stream_live() -> str:
    """Row 7 healthy fake: the user-data stream is LIVE (owner decision O-B)."""
    return "LIVE"


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
        gate_status=_gate_healthy,
        stream_state=_stream_live,
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
    assert names == [
        "operator_id",
        "local_intent_fn",
        "readiness",
        "gate_status",
        "stream_state",
        "now_utc",
    ]
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


# --------------------------------------------------------------------------- #
# Task 2 - one failure test per readiness row 1-5
# --------------------------------------------------------------------------- #


def _assert_still_in_safe_mode(rig: Rig, *, saves: int = 1) -> None:
    """A refused or failed exit changed nothing: memory, journal and store."""
    assert rig.controller.in_safe_mode is True
    assert rig.controller.entered_reason == "DB_FAILURE"
    assert rig.journal.of("SAFE_MODE_EXIT") == []
    assert len(rig.store.saved) == saves
    assert rig.controller.guard_new_entries(trade_plan=None).is_no_trade is True


@pytest.mark.parametrize("operator_id", ["", "   ", "\t\n", None, 7, b"op"])
async def test_row1_a_missing_operator_id_refuses(operator_id: Any) -> None:
    rig = _rig()

    decision = await _exit(rig, operator_id=operator_id)

    assert decision == ExitDecision(exited=False, refusals=("OPERATOR_ID_MISSING",))
    _assert_still_in_safe_mode(rig)


async def test_row1_the_operator_id_is_audit_metadata_not_authentication() -> None:
    """Any non-blank text is accepted: there is no allow-list yet (Phase 23/24, T-20-38)."""
    rig = _rig()

    decision = await _exit(rig, operator_id="anyone-at-all")

    assert decision.exited is True
    payload = json.loads(rig.journal.of("SAFE_MODE_EXIT")[0].payload_json)
    assert payload["operator_id"] == "anyone-at-all"


async def test_row2_a_raising_source_never_becomes_an_empty_list() -> None:
    """The F-711 case: truth is empty, so an empty list would have agreed. It must not."""
    rig = _rig(adapter=FakeAdapter())

    decision = await _exit(rig, local_intent_fn=_raises(RuntimeError("password=hunter2")))

    assert decision.refusals == ("LOCAL_SOURCE_UNREADABLE",)
    _assert_still_in_safe_mode(rig)
    payloads = [e.payload_json for e in rig.journal.events]
    assert not any("hunter2" in payload for payload in payloads)


@pytest.mark.parametrize("which", ["normal", "algos", "positions"])
@pytest.mark.parametrize("failure", ["raises", "none"])
async def test_row3_each_binance_read_failing_refuses(which: str, failure: str) -> None:
    adapter = FakeAdapter()
    # Set after construction: the constructor maps None to an empty list.
    setattr(adapter, which, RuntimeError("binance down") if failure == "raises" else None)
    rig = _rig(adapter=adapter)

    decision = await _exit(rig)

    assert decision == ExitDecision(exited=False, refusals=("BINANCE_READ_FAILED",))
    _assert_still_in_safe_mode(rig)


async def test_row3_the_reads_happen_inside_the_exit_call() -> None:
    rig = _rig()
    reads_before = rig.adapter.reads

    await _exit(rig)

    assert rig.adapter.reads == reads_before + 3


async def test_row3_an_unreadable_binance_side_skips_the_compare() -> None:
    calls: list[Any] = []

    def compare_fn(**kwargs: Any) -> Any:
        calls.append(kwargs)
        raise AssertionError("compare must not run on unreadable inputs")

    adapter = FakeAdapter(positions=RuntimeError("down"))
    controller = SafeModeController(
        adapter=adapter, journal=FakeJournal(), compare_fn=compare_fn, state_store=FakeStore()
    )
    controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T0)

    decision = await controller.exit_safe_mode(
        operator_id=OPERATOR,
        local_intent_fn=_local,
        readiness=_readiness,
        gate_status=_gate_healthy,
        stream_state=_stream_live,
        now_utc=T1,
    )

    assert decision.refusals == ("BINANCE_READ_FAILED",)
    assert calls == []


async def test_row4_an_exchange_position_with_an_empty_successful_local_read_refuses() -> None:
    """The vacuous exit of F-711: the local read worked and is empty, Binance holds a position."""
    rig = _rig(adapter=FakeAdapter(positions=[_position()]))

    decision = await _exit(rig, local_intent_fn=lambda: EMPTY_INTENT)

    assert decision == ExitDecision(exited=False, refusals=("COMPARE_NOT_CLEAN",))
    _assert_still_in_safe_mode(rig)


async def test_row4_a_compare_that_raises_is_never_clean() -> None:
    def compare_fn(**_kwargs: Any) -> Any:
        raise TypeError("a source was None")

    controller = SafeModeController(
        adapter=FakeAdapter(), journal=FakeJournal(), compare_fn=compare_fn
    )
    controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T0)

    decision = await controller.exit_safe_mode(
        operator_id=OPERATOR,
        local_intent_fn=_local,
        readiness=_readiness,
        gate_status=_gate_healthy,
        stream_state=_stream_live,
        now_utc=T1,
    )

    assert decision.refusals == ("COMPARE_NOT_CLEAN",)
    assert controller.in_safe_mode is True


async def test_row4_a_compare_result_without_agreement_is_never_clean() -> None:
    controller = SafeModeController(
        adapter=FakeAdapter(), journal=FakeJournal(), compare_fn=lambda **_k: object()
    )
    controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T0)

    decision = await controller.exit_safe_mode(
        operator_id=OPERATOR,
        local_intent_fn=_local,
        readiness=_readiness,
        gate_status=_gate_healthy,
        stream_state=_stream_live,
        now_utc=T1,
    )

    assert decision.refusals == ("COMPARE_NOT_CLEAN",)


def _not_a_count() -> Any:
    return ExitReadiness(True, 0, 0)  # type: ignore[arg-type]  # a bool is not a count


ROW5: list[Any] = [
    pytest.param(ExitReadiness(1, 0, 0), ("UNKNOWN_INTENT_PRESENT",), id="unknown-intent"),
    pytest.param(ExitReadiness(0, 1, 0), ("BLOCKING_PROTECTION_STATE",), id="blocking-plan"),
    pytest.param(ExitReadiness(0, 0, 1), ("PENDING_ACTION_PRESENT",), id="pending-action"),
    pytest.param(ExitReadiness(None, 0, 0), ("READINESS_UNREADABLE",), id="intents-unread"),
    pytest.param(ExitReadiness(0, None, 0), ("READINESS_UNREADABLE",), id="plans-unread"),
    pytest.param(ExitReadiness(0, 0, None), ("READINESS_UNREADABLE",), id="pending-unread"),
    pytest.param(ExitReadiness(-1, 0, 0), ("READINESS_UNREADABLE",), id="negative-count"),
    pytest.param(_not_a_count(), ("READINESS_UNREADABLE",), id="bool-is-not-a-count"),
    pytest.param(
        ExitReadiness(None, 2, 3),
        ("READINESS_UNREADABLE", "BLOCKING_PROTECTION_STATE", "PENDING_ACTION_PRESENT"),
        id="partly-unread-and-blocking",
    ),
]


@pytest.mark.parametrize(("counts", "expected"), ROW5)
async def test_row5_a_dirty_or_unreadable_readiness_refuses(
    counts: ExitReadiness, expected: tuple[str, ...]
) -> None:
    rig = _rig()

    decision = await _exit(rig, readiness=lambda: counts)

    assert decision == ExitDecision(exited=False, refusals=expected)
    _assert_still_in_safe_mode(rig)


async def test_row5_a_raising_readiness_refuses() -> None:
    rig = _rig()

    decision = await _exit(rig, readiness=_raises(RuntimeError("db down")))

    assert decision == ExitDecision(exited=False, refusals=("READINESS_UNREADABLE",))
    _assert_still_in_safe_mode(rig)


async def test_row5_a_readiness_without_the_fields_refuses() -> None:
    rig = _rig()

    decision = await _exit(rig, readiness=lambda: object())  # type: ignore[arg-type,return-value]

    assert decision.refusals == ("READINESS_UNREADABLE",)


async def test_every_refusal_found_in_one_pass_is_reported_and_journaled_once() -> None:
    rig = _rig(adapter=FakeAdapter(positions=[_position()]))

    decision = await _exit(rig, operator_id="", readiness=lambda: ExitReadiness(1, 1, 1))

    assert decision.refusals == (
        "OPERATOR_ID_MISSING",
        "COMPARE_NOT_CLEAN",
        "UNKNOWN_INTENT_PRESENT",
        "BLOCKING_PROTECTION_STATE",
        "PENDING_ACTION_PRESENT",
    )
    refused = rig.journal.of("SAFE_MODE_EXIT_REFUSED")
    assert len(refused) == 1
    assert json.loads(refused[0].payload_json)["refusals"] == list(decision.refusals)
    _assert_still_in_safe_mode(rig)


async def test_a_failing_refusal_journal_does_not_change_the_decision() -> None:
    rig = _rig()
    rig.journal.fail_on.add("SAFE_MODE_EXIT_REFUSED")

    decision = await _exit(rig, operator_id="")

    assert decision.refusals == ("OPERATOR_ID_MISSING",)
    assert rig.controller.in_safe_mode is True


async def test_an_exit_of_a_controller_that_is_not_in_safe_mode_is_a_noop() -> None:
    rig = _rig(enter=False)

    decision = await _exit(rig, operator_id="")

    assert decision == ExitDecision(exited=True, refusals=())
    assert rig.journal.events == []
    assert rig.store.saved == []
    assert rig.adapter.reads == 0


async def test_a_naive_now_is_a_caller_bug() -> None:
    rig = _rig()

    with pytest.raises(ValueError, match="UTC"):
        await _exit(rig, now_utc=datetime(2026, 9, 19, 12, 0))

    assert rig.controller.in_safe_mode is True


# --------------------------------------------------------------------------- #
# Write order: journal first, store second, memory last
# --------------------------------------------------------------------------- #


async def test_a_failing_exit_journal_keeps_safe_mode_and_a_retry_can_exit() -> None:
    rig = _rig()
    rig.journal.fail_on.add("SAFE_MODE_EXIT")

    with pytest.raises(RuntimeError, match="journal down"):
        await _exit(rig)

    _assert_still_in_safe_mode(rig)  # the store was never written either
    rig.journal.fail_on.clear()
    assert (await _exit(rig, now_utc=T2)).exited is True
    assert rig.controller.in_safe_mode is False


async def test_a_failing_state_save_keeps_safe_mode_and_a_retry_can_exit() -> None:
    rig = _rig()
    rig.trace.calls.clear()
    rig.store.save_error = RuntimeError("store down")

    with pytest.raises(RuntimeError, match="store down"):
        await _exit(rig)

    # The journal row was written first; memory was not flipped and the store kept SAFE_MODE.
    assert rig.trace.calls == ["journal:SAFE_MODE_EXIT"]
    assert rig.controller.in_safe_mode is True
    assert rig.controller.entered_reason == "DB_FAILURE"
    assert rig.controller.guard_new_entries(trade_plan=None).is_no_trade is True
    assert rig.controller.state_snapshot()["last_exit_operator_id"] is None
    assert rig.store.loaded is not None and rig.store.loaded["in_safe_mode"] is True

    rig.store.save_error = None
    assert (await _exit(rig, now_utc=T2)).exited is True
    assert rig.controller.in_safe_mode is False
    assert rig.store.loaded is not None and rig.store.loaded["in_safe_mode"] is False
    assert rig.store.loaded["last_exit_at_utc"] == T2.isoformat()


async def test_the_exit_state_is_saved_before_memory_flips() -> None:
    """The store sees the exit while the controller still reports SAFE_MODE."""
    observed: list[bool] = []
    rig = _rig()
    original_save = rig.store.save

    def spying_save(state: Mapping[str, str | bool | None], *, now_utc: datetime) -> None:
        observed.append(rig.controller.in_safe_mode)
        original_save(state, now_utc=now_utc)

    rig.store.save = spying_save  # type: ignore[method-assign]

    await _exit(rig)

    assert observed == [True]
    assert rig.controller.in_safe_mode is False


async def test_an_exit_without_a_store_still_journals_and_flips() -> None:
    journal = FakeJournal()
    controller = SafeModeController(adapter=FakeAdapter(), journal=journal)
    controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T0)

    decision = await controller.exit_safe_mode(
        operator_id=OPERATOR,
        local_intent_fn=_local,
        readiness=_readiness,
        gate_status=_gate_healthy,
        stream_state=_stream_live,
        now_utc=T1,
    )

    assert decision.exited is True
    assert controller.state_snapshot()["last_exit_operator_id"] == OPERATOR
    assert len(journal.of("SAFE_MODE_EXIT")) == 1


# --------------------------------------------------------------------------- #
# Nothing but the operator call exits
# --------------------------------------------------------------------------- #


def test_a_restart_never_exits_safe_mode() -> None:
    rig = _rig()

    restored = SafeModeController.load(
        adapter=FakeAdapter(), journal=FakeJournal(), state_store=rig.store, now_utc=T2
    )

    assert restored.in_safe_mode is True
    assert restored.entered_reason == "DB_FAILURE"
    assert restored.guard_new_entries(trade_plan=None).is_no_trade is True


def test_time_passing_and_a_reentry_never_exit_safe_mode() -> None:
    rig = _rig()
    for hours in (1, 24, 24 * 30):
        rig.controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T0 + timedelta(hours=hours))
        assert rig.controller.in_safe_mode is True
    assert rig.controller.entered_at_utc == T0
    assert rig.journal.of("SAFE_MODE_EXIT") == []


def test_the_public_api_has_no_way_to_flip_the_flag() -> None:
    rig = _rig()

    with pytest.raises(AttributeError):
        rig.controller.in_safe_mode = False  # type: ignore[misc]
    public = {name for name in dir(SafeModeController) if not name.startswith("_")}
    assert "exit_safe_mode" in public
    assert not {"set_safe_mode", "clear_safe_mode", "reset", "force_exit"} & public
    assert rig.controller.in_safe_mode is True


def test_a_state_row_that_says_off_does_not_change_a_live_controller() -> None:
    """A row written by someone else is only read at the next load, never by the live object."""
    rig = _rig()
    rig.store.loaded = dict(FIVE_KEY_OFF)

    assert rig.controller.in_safe_mode is True


# --------------------------------------------------------------------------- #
# The restore drill is a caller of the operator exit
# --------------------------------------------------------------------------- #


def test_the_restore_drill_exits_with_an_operator_id() -> None:
    from src.ops.drills import DRILL_OPERATOR_ID, DrillLog, make_restore_drill, run_drill

    rig = _rig(enter=False)
    drill = make_restore_drill(safe_mode_controller=rig.controller, now_utc=T0)

    outcome = run_drill(drill, journal=DrillLog(), now_utc=T0)

    assert outcome.outcome == "restore_clean_exit"
    assert rig.controller.in_safe_mode is False
    payload = json.loads(rig.journal.of("SAFE_MODE_EXIT")[0].payload_json)
    assert payload["operator_id"] == DRILL_OPERATOR_ID == "drill-operator"


def test_the_restore_drill_fails_when_the_local_source_is_unreadable() -> None:
    from src.ops.drills import DrillLog, make_restore_drill, run_drill

    rig = _rig(enter=False)
    drill = make_restore_drill(
        safe_mode_controller=rig.controller,
        now_utc=T0,
        local_intent_fn=_raises(RuntimeError("down")),
    )

    with pytest.raises(AssertionError, match="LOCAL_SOURCE_UNREADABLE"):
        run_drill(drill, journal=DrillLog(), now_utc=T0)

    assert rig.controller.in_safe_mode is True


# --------------------------------------------------------------------------- #
# Task 3 - build_exit_readiness (row 5) and the no-exit guarantees outside the controller
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Plan:
    state: Any


class _State(StrEnum):
    UNPROTECTED = "UNPROTECTED"
    CLOSE_REQUIRED = "CLOSE_REQUIRED"
    CLOSE_FAILED = "CLOSE_FAILED"
    PROTECTED = "PROTECTED"
    FLAT = "FLAT"
    AWAITING_FILL = "AWAITING_FILL"


def _readiness_of(
    *,
    intents: Any = lambda: [],  # noqa: B006 - lambdas are fresh per call
    plans: Any = lambda: [],
    pending: Any = lambda: [],
) -> ExitReadiness:
    return build_exit_readiness(
        unresolved_intents_fn=intents, protections_fn=plans, open_pending_fn=pending
    )


def test_a_clean_composition_reads_all_zero() -> None:
    plans = [_Plan(_State.PROTECTED), _Plan("FLAT"), _Plan(_State.AWAITING_FILL)]

    assert _readiness_of(plans=lambda: plans) == ExitReadiness(0, 0, 0)


@pytest.mark.parametrize("status", ["INTENDED", "SENT", "UNKNOWN"])
def test_an_unresolved_intent_of_any_status_counts(status: str) -> None:
    rows = [SimpleNamespace(intent_status=status), SimpleNamespace(intent_status=status)]

    assert _readiness_of(intents=lambda: rows).unknown_intents == 2


@pytest.mark.parametrize(
    ("state", "blocks"),
    [
        (_State.UNPROTECTED, True),
        ("UNPROTECTED", True),
        (_State.CLOSE_REQUIRED, True),
        ("CLOSE_REQUIRED", True),
        (_State.CLOSE_FAILED, True),
        ("CLOSE_FAILED", True),
        (_State.PROTECTED, False),
        (_State.FLAT, False),
        (_State.AWAITING_FILL, False),
        ("ENTRY_UNRESOLVED", False),
    ],
)
def test_only_unprotected_close_required_and_close_failed_block(state: Any, blocks: bool) -> None:
    result = _readiness_of(plans=lambda: [_Plan(state)])

    assert result.blocking_plans == (1 if blocks else 0)


def test_open_pending_actions_are_counted() -> None:
    assert _readiness_of(pending=lambda: [object(), object(), object()]).open_pending_actions == 3


def test_each_provider_is_independent() -> None:
    result = _readiness_of(
        intents=lambda: [object()],
        plans=lambda: [_Plan("UNPROTECTED"), _Plan("CLOSE_FAILED")],
        pending=lambda: [object(), object(), object()],
    )

    assert result == ExitReadiness(unknown_intents=1, blocking_plans=2, open_pending_actions=3)


@pytest.mark.parametrize("field", ["intents", "plans", "pending"])
@pytest.mark.parametrize("failure", ["raises", "none", "not-iterable"])
def test_a_provider_that_cannot_read_gives_none_in_its_field_only(field: str, failure: str) -> None:
    def bad() -> Any:
        if failure == "raises":
            raise RuntimeError("db down")
        return None if failure == "none" else 5

    result = _readiness_of(**{field: bad})

    expected = {
        "intents": "unknown_intents",
        "plans": "blocking_plans",
        "pending": "open_pending_actions",
    }
    for name in ("unknown_intents", "blocking_plans", "open_pending_actions"):
        assert getattr(result, name) == (None if name == expected[field] else 0)


def test_a_plan_view_without_a_state_makes_the_plans_field_unreadable() -> None:
    assert _readiness_of(plans=lambda: [object()]).blocking_plans is None


async def test_an_unreadable_provider_refuses_the_exit_as_readiness_unreadable() -> None:
    rig = _rig()

    def down() -> Any:
        raise RuntimeError("db down")

    decision = await _exit(rig, readiness=lambda: _readiness_of(pending=down))

    assert decision.refusals == ("READINESS_UNREADABLE",)
    assert rig.controller.in_safe_mode is True


async def test_the_composed_readiness_gates_the_exit() -> None:
    rig = _rig()

    refused = await _exit(
        rig, readiness=lambda: _readiness_of(plans=lambda: [_Plan("UNPROTECTED")])
    )
    assert refused.refusals == ("BLOCKING_PROTECTION_STATE",)

    allowed = await _exit(rig, readiness=lambda: _readiness_of(plans=lambda: [_Plan("PROTECTED")]))
    assert allowed.exited is True


def _calls_of_exit_safe_mode(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name == "exit_safe_mode":
                lines.append(node.lineno)
    return lines


@pytest.mark.parametrize(
    "relative",
    ["src/reconcile/loop.py", "src/execution/intent_recovery.py", "src/ops/alerts.py"],
)
def test_tick_recovery_and_alerts_never_call_exit_safe_mode(relative: str) -> None:
    """D-15: a tick, an intent closure and an alert never exit SAFE_MODE."""
    assert _calls_of_exit_safe_mode(REPO_ROOT / relative) == []


def test_only_the_operator_path_calls_exit() -> None:
    """Across all of src, the only caller of exit_safe_mode is the restore drill."""
    callers = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "src").rglob("*.py")
        if _calls_of_exit_safe_mode(path)
    }
    assert callers == {"src/ops/drills.py"}


def test_safe_mode_module_imports_nothing_from_persistence_or_execution() -> None:
    tree = ast.parse(SAFE_MODE_SOURCE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    assert [m for m in imported if m.startswith(("src.persistence", "src.execution"))] == []


# --------------------------------------------------------------------------- #
# A divergence found while the exit awaits Binance must not be lost
# --------------------------------------------------------------------------- #


async def test_an_entry_during_the_exit_reads_refuses_the_exit() -> None:
    """The reconcile loop shares the event loop: it may re-enter SAFE_MODE while the exit awaits
    its Binance reads. Exiting on the older, clean-looking reads would erase that divergence."""
    rig = _rig()

    class EnteringAdapter(FakeAdapter):
        async def snapshot_positions(self, *, symbol: str | None = None) -> Any:
            rig.controller.enter_safe_mode(reason="DB_FAILURE", now_utc=T1)  # same reason
            return await super().snapshot_positions(symbol=symbol)

    rig.controller._adapter = EnteringAdapter()  # type: ignore[attr-defined]

    decision = await _exit(rig, now_utc=T2)

    assert decision == ExitDecision(exited=False, refusals=("COMPARE_NOT_CLEAN",))
    _assert_still_in_safe_mode(rig)


# --------------------------------------------------------------------------- #
# Owner decision O-B (plan 20-25, T-E rows 6 and 7): REST gate restored and open, stream LIVE
# --------------------------------------------------------------------------- #


def _gate_of(status: tuple[str | None, str] | Any) -> Any:
    return lambda: status


def _stream_of(state: Any) -> Any:
    return lambda: state


async def _exit_rows(
    rig: Rig,
    *,
    gate_status: Any = _gate_healthy,
    stream_state: Any = _stream_live,
) -> ExitDecision:
    return await rig.controller.exit_safe_mode(
        operator_id=OPERATOR,
        local_intent_fn=_local,
        readiness=_readiness,
        gate_status=gate_status,
        stream_state=stream_state,
        now_utc=T1,
    )


async def test_rows_6_and_7_healthy_gate_and_live_stream_exit() -> None:
    rig = _rig()

    decision = await _exit_rows(rig)

    assert decision == ExitDecision(exited=True, refusals=())
    assert rig.controller.in_safe_mode is False


@pytest.mark.parametrize("reason", ["RATE_LIMIT_PAUSE_429", "IP_BAN_418", "GATE_NOT_RESTORED"])
async def test_row6_a_restricted_gate_refuses_gate_not_open(reason: str) -> None:
    rig = _rig()

    decision = await _exit_rows(rig, gate_status=_gate_of((reason, "RESTORED_DURABLE")))

    assert decision == ExitDecision(exited=False, refusals=("GATE_NOT_OPEN",))
    _assert_still_in_safe_mode(rig)


@pytest.mark.parametrize(
    "status",
    ["LEGACY_IN_MEMORY", "NOT_RESTORED", "RESTORED_UNKNOWN_STATE", "PERSISTENCE_FAILED"],
)
async def test_row6_an_open_gate_that_is_not_restored_refuses_gate_not_restored(
    status: str,
) -> None:
    rig = _rig()

    decision = await _exit_rows(rig, gate_status=_gate_of((None, status)))

    assert decision == ExitDecision(exited=False, refusals=("GATE_NOT_RESTORED",))
    _assert_still_in_safe_mode(rig)


@pytest.mark.parametrize("status", ["RESTORED_DURABLE", "RESTORED_BARRIER"])
async def test_row6_a_restored_status_with_no_restriction_passes(status: str) -> None:
    rig = _rig()

    decision = await _exit_rows(rig, gate_status=_gate_of((None, status)))

    assert decision.exited is True


async def test_row6_a_restricted_and_unrestored_gate_reports_both_codes() -> None:
    rig = _rig()

    decision = await _exit_rows(rig, gate_status=_gate_of(("GATE_STATE_UNKNOWN", "NOT_RESTORED")))

    assert decision.refusals == ("GATE_NOT_OPEN", "GATE_NOT_RESTORED")


async def test_row6_a_gate_status_that_raises_refuses_gate_not_restored() -> None:
    rig = _rig()

    decision = await _exit_rows(rig, gate_status=_raises(RuntimeError("gate lock broken")))

    assert decision == ExitDecision(exited=False, refusals=("GATE_NOT_RESTORED",))
    _assert_still_in_safe_mode(rig)


@pytest.mark.parametrize(
    "malformed",
    [
        None,
        "RESTORED_DURABLE",
        (None,),
        (None, "RESTORED_DURABLE", "extra"),
        (None, None),
        (None, 3),
        (None, "SOMETHING_NEW"),
        (None, "restored_durable"),
    ],
    ids=[
        "none",
        "bare-string",
        "one-item",
        "three-items",
        "status-none",
        "status-int",
        "unknown-status",
        "lowercase-status",
    ],
)
async def test_row6_a_malformed_or_unrecognised_gate_status_refuses_gate_not_restored(
    malformed: Any,
) -> None:
    rig = _rig()

    decision = await _exit_rows(rig, gate_status=_gate_of(malformed))

    assert decision.exited is False
    assert "GATE_NOT_RESTORED" in decision.refusals
    _assert_still_in_safe_mode(rig)


async def test_row6_a_missing_gate_status_is_a_type_error_at_call() -> None:
    rig = _rig()

    with pytest.raises(TypeError):
        await rig.controller.exit_safe_mode(  # type: ignore[call-arg]
            operator_id=OPERATOR,
            local_intent_fn=_local,
            readiness=_readiness,
            stream_state=_stream_live,
            now_utc=T1,
        )

    _assert_still_in_safe_mode(rig)


async def test_row6_never_replaces_the_fresh_binance_reads_of_row_3() -> None:
    """An open, restored gate says only "no restriction known": a failed read still refuses."""
    rig = _rig(adapter=FakeAdapter(positions=RuntimeError("down")))

    decision = await _exit_rows(rig, gate_status=_gate_of((None, "RESTORED_DURABLE")))

    assert decision == ExitDecision(exited=False, refusals=("BINANCE_READ_FAILED",))
    _assert_still_in_safe_mode(rig)


@pytest.mark.parametrize("state", ["CONNECTING", "SYNCING", "UNKNOWN", "STOPPED"])
async def test_row7_a_stream_that_is_not_live_refuses_stream_not_live(state: str) -> None:
    rig = _rig()

    decision = await _exit_rows(rig, stream_state=_stream_of(state))

    assert decision == ExitDecision(exited=False, refusals=("STREAM_NOT_LIVE",))
    _assert_still_in_safe_mode(rig)


async def test_row7_a_stream_state_provider_that_raises_refuses_stream_not_live() -> None:
    rig = _rig()

    decision = await _exit_rows(rig, stream_state=_raises(RuntimeError("supervisor gone")))

    assert decision == ExitDecision(exited=False, refusals=("STREAM_NOT_LIVE",))
    _assert_still_in_safe_mode(rig)


@pytest.mark.parametrize("state", [None, 1, True, b"LIVE", "live", " LIVE", ""])
async def test_row7_anything_but_the_exact_live_string_refuses(state: Any) -> None:
    rig = _rig()

    decision = await _exit_rows(rig, stream_state=_stream_of(state))

    assert decision == ExitDecision(exited=False, refusals=("STREAM_NOT_LIVE",))


async def test_row7_a_missing_stream_state_is_a_type_error_at_call() -> None:
    rig = _rig()

    with pytest.raises(TypeError):
        await rig.controller.exit_safe_mode(  # type: ignore[call-arg]
            operator_id=OPERATOR,
            local_intent_fn=_local,
            readiness=_readiness,
            gate_status=_gate_healthy,
            now_utc=T1,
        )

    _assert_still_in_safe_mode(rig)


async def test_rows_6_and_7_refusals_are_collected_in_one_pass_and_journaled() -> None:
    rig = _rig()

    decision = await _exit_rows(
        rig,
        gate_status=_gate_of(("IP_BAN_418", "RESTORED_DURABLE")),
        stream_state=_stream_of("UNKNOWN"),
    )

    assert decision.refusals == ("GATE_NOT_OPEN", "STREAM_NOT_LIVE")
    refused = rig.journal.of("SAFE_MODE_EXIT_REFUSED")
    assert len(refused) == 1
    assert json.loads(refused[0].payload_json)["refusals"] == ["GATE_NOT_OPEN", "STREAM_NOT_LIVE"]
    _assert_still_in_safe_mode(rig)


async def test_rows_6_and_7_come_after_the_five_d15_rows() -> None:
    rig = _rig(adapter=FakeAdapter(positions=RuntimeError("down")))

    decision = await _exit_rows(
        rig,
        gate_status=_gate_of(("IP_BAN_418", "RESTORED_DURABLE")),
        stream_state=_stream_of("STOPPED"),
    )

    assert decision.refusals == ("BINANCE_READ_FAILED", "GATE_NOT_OPEN", "STREAM_NOT_LIVE")


def test_the_strings_used_equal_the_adapter_enum_values() -> None:
    """safe_mode.py imports nothing from src.adapters; this parity test pins the strings."""
    from src.adapters.binance_ratelimit_gate import GateRecoveryStatus
    from src.adapters.binance_userdata_supervisor import StreamState
    from src.reconcile.safe_mode import ACCEPTED_GATE_RECOVERY_STATES, STREAM_LIVE_STATE

    assert {status.value for status in GateRecoveryStatus} >= ACCEPTED_GATE_RECOVERY_STATES
    assert ACCEPTED_GATE_RECOVERY_STATES == frozenset({"RESTORED_DURABLE", "RESTORED_BARRIER"})
    assert StreamState.LIVE.value == STREAM_LIVE_STATE == "LIVE"


async def test_every_adapter_recovery_status_and_stream_state_is_judged_as_decided() -> None:
    from src.adapters.binance_ratelimit_gate import GateRecoveryStatus
    from src.adapters.binance_userdata_supervisor import StreamState

    for status in GateRecoveryStatus:
        decision = await _exit_rows(_rig(), gate_status=_gate_of((None, status.value)))
        accepted = status in (
            GateRecoveryStatus.RESTORED_DURABLE,
            GateRecoveryStatus.RESTORED_BARRIER,
        )
        assert decision.exited is accepted, status
    for state in StreamState:
        decision = await _exit_rows(_rig(), stream_state=_stream_of(state))  # a StrEnum member
        assert decision.exited is (state is StreamState.LIVE), state


def test_safe_mode_module_imports_nothing_from_adapters() -> None:
    tree = ast.parse(SAFE_MODE_SOURCE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    assert [m for m in imported if m.startswith("src.adapters")] == []


# -- the real gate as the row 6 provider: check() and restriction() semantics, tested --------- #


class _GateClock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def _real_gate(
    tmp_path: Path, clock: _GateClock, *, restore: bool = True, store: bool = True
) -> Any:
    from src.adapters.binance_limits import RateLimitPolicy
    from src.adapters.binance_ratelimit_gate import RestRateLimitGate
    from src.ops.rest_gate_state import FileGateStateStore

    policy = RateLimitPolicy(
        no_retry_after_wait_418_seconds=3600,
        no_retry_after_wait_429_seconds=60,
        retry_after_cap_seconds=7200,
    )
    state_store = None
    if store:
        tmp_path.mkdir(parents=True, exist_ok=True)
        state_store = FileGateStateStore(tmp_path / "gate.json", clock=clock)
        state_store.initialize(now_utc=clock(), operator_id="op-1")
    gate = RestRateLimitGate(policy=policy, clock=clock, state_store=state_store)
    if restore:
        gate.restore()
    return gate


def _status_of(gate: Any) -> Any:
    def provider() -> tuple[str | None, str]:
        restriction = gate.restriction()
        return (None if restriction is None else restriction.reason, gate.recovery_status().value)

    return provider


async def test_the_real_gate_restored_and_open_lets_the_exit_pass(tmp_path: Path) -> None:
    gate = _real_gate(tmp_path, _GateClock())

    decision = await _exit_rows(_rig(), gate_status=_status_of(gate))

    assert decision.exited is True


async def test_the_real_gate_before_restore_refuses_not_open_and_not_restored(
    tmp_path: Path,
) -> None:
    gate = _real_gate(tmp_path, _GateClock(), restore=False)

    decision = await _exit_rows(_rig(), gate_status=_status_of(gate))

    assert decision.refusals == ("GATE_NOT_OPEN", "GATE_NOT_RESTORED")


async def test_the_real_gate_without_a_state_store_is_legacy_and_refuses(tmp_path: Path) -> None:
    gate = _real_gate(tmp_path, _GateClock(), store=False)
    assert gate.restriction() is None  # None is not proof that REST is healthy

    decision = await _exit_rows(_rig(), gate_status=_status_of(gate))

    assert decision.refusals == ("GATE_NOT_RESTORED",)


async def test_the_real_gate_with_a_known_pause_refuses_until_it_passes(tmp_path: Path) -> None:
    from src.domain.exchange_errors import ExchangeErrorCategory

    clock = _GateClock()
    gate = _real_gate(tmp_path, clock)
    gate.record(ExchangeErrorCategory.RATE_LIMITED, 50)

    refused = await _exit_rows(_rig(), gate_status=_status_of(gate))
    assert refused.refusals == ("GATE_NOT_OPEN",)

    clock.now = T0 + timedelta(seconds=51)
    allowed = await _exit_rows(_rig(), gate_status=_status_of(gate))
    assert allowed.exited is True


async def test_the_real_gate_restriction_is_none_exactly_when_check_would_not_refuse(
    tmp_path: Path,
) -> None:
    """The predicate row 6 uses (restriction) agrees with the call that refuses REST (check)."""
    from src.adapters.binance_ratelimit_gate import RestGateRefusal
    from src.domain.exchange_errors import ExchangeErrorCategory

    def check_refuses(gate: Any) -> bool:
        try:
            gate.check()
        except RestGateRefusal:
            return True
        return False

    clock = _GateClock()
    unrestored = _real_gate(tmp_path / "a", clock, restore=False)
    restored = _real_gate(tmp_path / "b", clock)
    paused = _real_gate(tmp_path / "c", clock)
    paused.record(ExchangeErrorCategory.RATE_LIMITED, 50)
    banned = _real_gate(tmp_path / "d", clock)
    banned.record(ExchangeErrorCategory.IP_BANNED, 120)

    for gate, refuses in ((unrestored, True), (restored, False), (paused, True), (banned, True)):
        assert check_refuses(gate) is refuses
        assert (gate.restriction() is not None) is refuses
