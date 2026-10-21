"""The manual emergency close never removes the stop of an open position (Phase 20, plan 20-11).

D-09, RISK-03, EXEC-06 and EXECUTION_SPEC section 11: "cancelling a protective stop is never
part of any control above". Before this plan `emergency_manual_close` cancelled the entry and then
ALL protective legs with no position read. Now the protective legs are cancelled only after two
independent fresh position reads are both zero AND the entry is verified terminal; otherwise
nothing protective is cancelled and `PROTECTIVES_KEPT` is journaled with a reason code. After the
legs are cancelled each one is queried again; a leg that is not proven gone journals
`MANUAL_CLOSE_ORPHAN_UNVERIFIED` and SAFE_MODE stays.

Evidence label: executed tests with the Binance-semantics fake; no network, no Binance. What
Binance does with a closePosition leg when the position is closed outside the system (G4-035) is
[NOT_TESTED] and owned by Phase 25.
"""

from __future__ import annotations

import ast
import inspect
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.execution.order_ids import derive_algo_client_id, derive_client_order_id
from src.execution.protection import ProtectionState

from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.protection_doubles import TEST_ONLY_PLAN_HASH as RIG_PLAN_HASH
from tests.support.protection_doubles import ProtectionRig, make_rig
from tests.support.reconcile_doubles import RaisingJournal, RecordingJournal

NOW_UTC = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
PLAN_HASH = "6" * 64
SYMBOL = "BTCUSDT"
ENTRY_ID = derive_client_order_id(plan_hash=PLAN_HASH, role="ENTRY")
SL_ID = derive_algo_client_id(plan_hash=PLAN_HASH, role="STOP_LOSS")
TP1_ID = derive_algo_client_id(plan_hash=PLAN_HASH, role="TAKE_PROFIT_1")
TP2_ID = derive_algo_client_id(plan_hash=PLAN_HASH, role="TAKE_PROFIT_2")
LEG_IDS = (SL_ID, TP1_ID, TP2_ID)
QUANTITY = Decimal("0.004")
PRICE = Decimal("60000")
MANAGER = Path(__file__).parent.parent / "src" / "execution" / "manager.py"


class ScriptedFake(BinanceSemanticsFakeAdapter):
    """The Binance-semantics fake plus scripted position reads and misbehaving legs.

    `position_script`: one item per `snapshot_positions` call, consumed in order; a Decimal sets
    the symbol's position before the read, an exception is raised by that read. When the script
    is empty the real position book answers.
    `unreadable_algo_ids`: a query of these algo ids raises. `sticky_algo_ids`: a cancel of these
    algo ids is accepted but does not take effect (the leg keeps resting).
    """

    def __init__(self) -> None:
        super().__init__()
        self.position_script: list[Decimal | BaseException] = []
        self.unreadable_algo_ids: set[str] = set()
        self.sticky_algo_ids: set[str] = set()

    async def snapshot_positions(self, **kwargs: Any) -> Any:
        if self.position_script:
            item = self.position_script.pop(0)
            if isinstance(item, BaseException):
                self.fail_next("snapshot_positions", item)
            else:
                self.positions[SYMBOL] = item
        return await super().snapshot_positions(**kwargs)

    async def query_algo_order_by_client(self, **kwargs: Any) -> Any:
        if kwargs["client_algo_id"] in self.unreadable_algo_ids:
            self.fail_next("query_algo_order_by_client", RuntimeError("scripted read failure"))
        return await super().query_algo_order_by_client(**kwargs)

    async def cancel_algo_order(self, **kwargs: Any) -> Any:
        if kwargs["client_algo_id"] in self.sticky_algo_ids:
            self._bind_real("cancel_algo_order", kwargs)
            self._record_call("cancel_algo_order", kwargs)
            return None
        return await super().cancel_algo_order(**kwargs)


class RecordingEnablement:
    def __init__(self, order: list[str]) -> None:
        self._order = order
        self.disabled = False

    def disable(self, *, operator_id: str, now_utc: datetime) -> None:
        self._order.append("disable")
        self.disabled = True


class RecordingSafeMode:
    """Records SAFE_MODE entries; any exit is a test failure (the control never exits it)."""

    def __init__(self, order: list[str]) -> None:
        self._order = order
        self.reasons: list[str] = []
        self.exits = 0

    def enter_safe_mode(self, *, reason: str, now_utc: Any = None) -> None:
        self._order.append("safe_mode")
        self.reasons.append(reason)

    def exit_safe_mode(self, **_kwargs: Any) -> None:
        self.exits += 1
        raise AssertionError("emergency_manual_close must never exit SAFE_MODE")


async def _open_position(fake: ScriptedFake, *, with_legs: bool = True) -> None:
    """The entry filled in full (+0.004) and the three protective legs rest."""
    await fake.place_entry(
        symbol=SYMBOL,
        side="BUY",
        position_side="BOTH",
        time_in_force="GTC",
        quantity=QUANTITY,
        price=PRICE,
        new_client_order_id=ENTRY_ID,
    )
    fake.fill(ENTRY_ID)
    if with_legs:
        await _place_legs(fake)


async def _resting_entry_with_legs(fake: ScriptedFake) -> None:
    """The entry never filled (still resting) and the legs rest: nothing is exposed."""
    await fake.place_entry(
        symbol=SYMBOL,
        side="BUY",
        position_side="BOTH",
        time_in_force="GTC",
        quantity=QUANTITY,
        price=PRICE,
        new_client_order_id=ENTRY_ID,
    )
    await _place_legs(fake)


async def _place_legs(fake: ScriptedFake) -> None:
    for client_algo_id in LEG_IDS:
        stop = client_algo_id == SL_ID
        await fake.place_algo_protective(
            symbol=SYMBOL,
            side="SELL",
            algo_type="CONDITIONAL",
            type="STOP_MARKET" if stop else "TAKE_PROFIT_MARKET",
            position_side="BOTH",
            trigger_price=Decimal("59000") if stop else Decimal("61000"),
            close_position=stop,
            quantity=None if stop else QUANTITY / 2,
            working_type="MARK_PRICE",
            client_algo_id=client_algo_id,
            reduce_only=None if stop else True,
        )
    fake.calls.clear()


async def _close(
    fake: ScriptedFake,
    journal: Any,
    *,
    order: list[str] | None = None,
    safe_mode: RecordingSafeMode | None = None,
    spill: Any = None,
) -> tuple[RecordingEnablement, RecordingSafeMode]:
    from src.execution.manager import emergency_manual_close

    order = order if order is not None else []
    enablement = RecordingEnablement(order)
    safe_mode = safe_mode or RecordingSafeMode(order)
    await emergency_manual_close(
        plan_hash=PLAN_HASH,
        symbol=SYMBOL,
        adapter=fake,  # type: ignore[arg-type]
        journal=journal,
        enablement=enablement,
        safe_mode_controller=safe_mode,
        operator_id="operator_alpha",
        now_utc=NOW_UTC,
        spill=spill,
    )
    return enablement, safe_mode


def _leaf_types(error: BaseException) -> list[type[BaseException]]:
    """The exception classes at the leaves of (nested) exception groups."""
    if isinstance(error, BaseExceptionGroup):
        return [t for inner in error.exceptions for t in _leaf_types(inner)]
    return [type(error)]


def _methods(fake: ScriptedFake) -> list[str]:
    return [c["method"] for c in fake.calls]


def _events(journal: RecordingJournal, event_type: str) -> list[dict[str, Any]]:
    return [json.loads(e.payload_json) for e in journal.events if e.event_type == event_type]


def _phases(journal: RecordingJournal, identifier: str) -> list[str]:
    return [
        json.loads(e.payload_json)["phase"] for e in journal.events if e.entity_id == identifier
    ]


# --------------------------------------------------------------------------- #
# An open position keeps its stop.
# --------------------------------------------------------------------------- #


async def test_manual_close_never_cancels_an_open_positions_stop() -> None:
    """D-09, EXECUTION_SPEC section 11, RISK-03: +0.004 open and an ACTIVE SL: the SL stays.

    Before plan 20-11 this control cancelled SL, TP1 and TP2 unconditionally.
    """
    fake = ScriptedFake()
    await _open_position(fake)
    journal = RecordingJournal()

    enablement, safe_mode = await _close(fake, journal)

    assert set(fake.open_algos) == set(LEG_IDS)  # nothing protective was cancelled
    assert "cancel_algo_order" not in _methods(fake)
    assert fake.positions[SYMBOL] == QUANTITY
    (kept,) = _events(journal, "PROTECTIVES_KEPT")
    assert kept["reason_code"] == "FIRST_READ_NONZERO"
    assert kept["symbol"] == SYMBOL
    assert enablement.disabled is True
    assert safe_mode.reasons == ["MANUAL_CLOSE"]
    assert safe_mode.exits == 0
    # The entry cancel was verified: it filled, so it is not "canceled".
    assert fake.calls_to("query_order_by_client")
    assert _phases(journal, ENTRY_ID) == ["pre_cancel", "cancel_unverified"]
    assert _events(journal, "MANUAL_CLOSE_ORPHAN_UNVERIFIED") == []


async def test_manual_close_keeps_the_stop_of_a_partly_filled_entry_whose_cancel_verified() -> None:
    fake = ScriptedFake()
    await fake.place_entry(
        symbol=SYMBOL,
        side="BUY",
        position_side="BOTH",
        time_in_force="GTC",
        quantity=QUANTITY,
        price=PRICE,
        new_client_order_id=ENTRY_ID,
    )
    fake.fill(ENTRY_ID, quantity=Decimal("0.001"))
    await _place_legs(fake)
    journal = RecordingJournal()

    await _close(fake, journal)

    assert _phases(journal, ENTRY_ID) == ["pre_cancel", "post_cancel"]  # CANCELED, verified
    assert set(fake.open_algos) == set(LEG_IDS)
    (kept,) = _events(journal, "PROTECTIVES_KEPT")
    assert kept["reason_code"] == "FIRST_READ_NONZERO"
    assert kept["entry_verdict"] == "CANCELED"


# --------------------------------------------------------------------------- #
# Flat twice and the entry terminal: the legs are cancelled, each verified.
# --------------------------------------------------------------------------- #


async def test_manual_close_cancels_the_legs_after_two_flat_reads_and_a_canceled_entry() -> None:
    fake = ScriptedFake()
    await _resting_entry_with_legs(fake)
    journal = RecordingJournal()
    order: list[str] = []

    enablement, safe_mode = await _close(fake, journal, order=order)

    assert order == ["disable", "safe_mode"]
    assert fake.open_algos == {}
    assert fake.open_orders == {}
    for client_algo_id in LEG_IDS:
        assert _phases(journal, client_algo_id) == ["pre_cancel", "post_cancel"]  # CANCELED
    assert _events(journal, "PROTECTIVES_KEPT") == []
    assert _events(journal, "MANUAL_CLOSE_ORPHAN_UNVERIFIED") == []
    assert safe_mode.exits == 0
    # Order of the exchange conversation: entry cancel + its check, two reads, then the legs.
    methods = _methods(fake)
    assert methods[:4] == [
        "cancel_normal_order",
        "query_order_by_client",
        "snapshot_positions",
        "snapshot_positions",
    ]
    assert methods.count("snapshot_positions") == 2
    assert all(c["kwargs"] == {"symbol": SYMBOL} for c in fake.calls_to("snapshot_positions"))
    assert methods.count("cancel_algo_order") == 3


# --------------------------------------------------------------------------- #
# Each way the evidence can fall short keeps every leg.
# --------------------------------------------------------------------------- #


async def test_flat_first_read_and_nonzero_second_read_cancels_no_leg() -> None:
    fake = ScriptedFake()
    await _resting_entry_with_legs(fake)
    fake.position_script = [Decimal("0"), Decimal("0.004")]
    journal = RecordingJournal()

    await _close(fake, journal)

    assert set(fake.open_algos) == set(LEG_IDS)
    assert "cancel_algo_order" not in _methods(fake)
    (kept,) = _events(journal, "PROTECTIVES_KEPT")
    assert kept["reason_code"] == "SECOND_READ_NONZERO"
    assert _methods(fake).count("snapshot_positions") == 2


async def test_flat_first_read_and_failing_second_read_cancels_no_leg() -> None:
    fake = ScriptedFake()
    await _resting_entry_with_legs(fake)
    fake.position_script = [Decimal("0"), RuntimeError("signature=SECRET-TOKEN-9")]
    journal = RecordingJournal()

    await _close(fake, journal)

    assert set(fake.open_algos) == set(LEG_IDS)
    (kept,) = _events(journal, "PROTECTIVES_KEPT")
    assert kept["reason_code"] == "READ_FAILED"
    assert "SECRET-TOKEN-9" not in json.dumps([e.payload_json for e in journal.events])


async def test_failing_first_read_cancels_no_leg_and_asks_once() -> None:
    fake = ScriptedFake()
    await _resting_entry_with_legs(fake)
    fake.position_script = [RuntimeError("down")]
    journal = RecordingJournal()

    await _close(fake, journal)

    assert set(fake.open_algos) == set(LEG_IDS)
    (kept,) = _events(journal, "PROTECTIVES_KEPT")
    assert kept["reason_code"] == "READ_FAILED"
    assert _methods(fake).count("snapshot_positions") == 1


async def test_a_nonzero_first_read_asks_once() -> None:
    fake = ScriptedFake()
    await _resting_entry_with_legs(fake)
    fake.position_script = [Decimal("-0.002")]  # a short position is exposure too
    journal = RecordingJournal()

    await _close(fake, journal)

    (kept,) = _events(journal, "PROTECTIVES_KEPT")
    assert kept["reason_code"] == "FIRST_READ_NONZERO"
    assert _methods(fake).count("snapshot_positions") == 1


async def test_a_filled_entry_with_a_flat_position_keeps_the_legs() -> None:
    """The entry verdict is FILLED_OR_PARTIAL: the cancel alone does not prove it terminal."""
    fake = ScriptedFake()
    await _open_position(fake)
    fake.positions[SYMBOL] = Decimal("0")  # closed on the exchange by hand
    journal = RecordingJournal()

    await _close(fake, journal)

    assert set(fake.open_algos) == set(LEG_IDS)
    assert "cancel_algo_order" not in _methods(fake)
    (kept,) = _events(journal, "PROTECTIVES_KEPT")
    assert kept["reason_code"] == "ENTRY_NOT_TERMINAL"
    assert kept["entry_verdict"] == "FILLED_OR_PARTIAL"


async def test_a_failing_entry_cancel_keeps_the_legs_and_still_raises_the_group() -> None:
    fake = ScriptedFake()
    await _resting_entry_with_legs(fake)
    fake.fail_next("cancel_normal_order", RuntimeError("network"))
    journal = RecordingJournal()

    with pytest.raises(ExceptionGroup) as excinfo:
        await _close(fake, journal)

    assert [type(e) for e in excinfo.value.exceptions] == [RuntimeError]
    assert set(fake.open_algos) == set(LEG_IDS)
    (kept,) = _events(journal, "PROTECTIVES_KEPT")
    assert kept["reason_code"] == "ENTRY_NOT_TERMINAL"
    assert kept["entry_verdict"] == "NONE"


async def test_an_entry_that_expired_on_its_own_counts_as_terminal() -> None:
    from src.execution.cancel_verification import CancelVerdict

    class ExpiredEntryFake(ScriptedFake):
        async def query_order_by_client(self, **kwargs: Any) -> Any:
            probe = await super().query_order_by_client(**kwargs)
            from dataclasses import replace

            return replace(probe, found=True, status="EXPIRED")

    fake = ExpiredEntryFake()
    await _resting_entry_with_legs(fake)
    journal = RecordingJournal()

    await _close(fake, journal)

    assert fake.open_algos == {}  # EXPIRED is GONE_NOT_CANCELED: terminal
    assert CancelVerdict.GONE_NOT_CANCELED.value in json.dumps(
        [e.payload_json for e in journal.events]
    )


# --------------------------------------------------------------------------- #
# Legs that do not verify gone keep SAFE_MODE and are reported.
# --------------------------------------------------------------------------- #


async def test_a_leg_that_cannot_be_read_after_its_cancel_journals_orphan_unverified() -> None:
    fake = ScriptedFake()
    await _resting_entry_with_legs(fake)
    fake.unreadable_algo_ids = {SL_ID}
    journal = RecordingJournal()

    enablement, safe_mode = await _close(fake, journal)

    (orphan,) = _events(journal, "MANUAL_CLOSE_ORPHAN_UNVERIFIED")
    assert orphan["symbol"] == SYMBOL
    assert orphan["legs"]["STOP_LOSS"] == "UNKNOWN"
    assert orphan["legs"]["TAKE_PROFIT_1"] == "CANCELED"
    assert safe_mode.reasons == ["MANUAL_CLOSE"]
    assert safe_mode.exits == 0  # SAFE_MODE is kept, never exited
    assert enablement.disabled is True


async def test_a_leg_that_keeps_resting_after_its_cancel_journals_orphan_unverified() -> None:
    fake = ScriptedFake()
    await _resting_entry_with_legs(fake)
    fake.sticky_algo_ids = {TP2_ID}
    journal = RecordingJournal()

    await _close(fake, journal)

    (orphan,) = _events(journal, "MANUAL_CLOSE_ORPHAN_UNVERIFIED")
    assert orphan["legs"]["TAKE_PROFIT_2"] == "STILL_OPEN"
    assert orphan["legs"]["STOP_LOSS"] == "CANCELED"
    assert _phases(journal, TP2_ID) == ["pre_cancel", "cancel_unverified"]


async def test_a_leg_that_is_already_gone_is_proven_gone_and_not_an_orphan() -> None:
    fake = ScriptedFake()
    await _resting_entry_with_legs(fake)
    fake.cancel_algo(TP2_ID)
    fake.algo_history.pop(TP2_ID)  # retention: a canceled leg with no fill is no longer found
    journal = RecordingJournal()

    await _close(fake, journal)

    assert _events(journal, "MANUAL_CLOSE_ORPHAN_UNVERIFIED") == []
    assert fake.open_algos == {}


# --------------------------------------------------------------------------- #
# The control stays risk-first and never touches the plan status.
# --------------------------------------------------------------------------- #


async def test_a_journal_outage_changes_nothing_about_which_legs_are_cancelled() -> None:
    """D-16 still holds: the verdicts come from the exchange, not from the journal."""
    fake = ScriptedFake()
    await _resting_entry_with_legs(fake)

    with pytest.raises(ExceptionGroup) as excinfo:
        await _close(fake, RaisingJournal())

    from src.ops.risk_first import AuditRecordLost

    assert set(_leaf_types(excinfo.value)) == {AuditRecordLost}
    assert fake.open_algos == {}
    assert fake.open_orders == {}


async def test_an_unreadable_journal_still_keeps_the_stop_of_an_open_position() -> None:
    fake = ScriptedFake()
    await _open_position(fake)

    with pytest.raises(ExceptionGroup):
        await _close(fake, RaisingJournal())

    assert set(fake.open_algos) == set(LEG_IDS)


def test_no_manual_control_moves_a_trade_plan_to_expired() -> None:
    """D-09, G4-036: an executed plan stays APPROVED. The three controls have no plan store and
    never name a TradePlan status or a status writer."""
    from src.execution import manager

    forbidden = {"TradePlanStatus", "EXPIRED", "update_status", "set_status", "mark_expired"}
    tree = ast.parse(MANAGER.read_text(encoding="utf-8"))
    controls = {"emergency_manual_close", "expire_pending_entry", "cancel_untriggered_protectives"}
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name in controls:
            seen.add(node.name)
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            names |= {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
            constants = {
                n.value
                for n in ast.walk(node)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
            }
            assert not (names | constants) & forbidden, node.name
            params = set(inspect.signature(getattr(manager, node.name)).parameters)
            assert not any("plan_store" in p or "status" in p for p in params), node.name
    assert seen == controls


# --------------------------------------------------------------------------- #
# Plan 20-17, Task 1 (D-26, D-06, D-09, D034): operator_close_position flattens through the
# coordinator's own close flow. Evidence label: executed tests with the Binance-semantics fake and
# the real MarketEmergencyCloser; reduce-only MARKET behavior on Binance is [NOT_TESTED].
# --------------------------------------------------------------------------- #

RIG_SL_ID = derive_algo_client_id(plan_hash=RIG_PLAN_HASH, role="STOP_LOSS")
RIG_TP1_ID = derive_algo_client_id(plan_hash=RIG_PLAN_HASH, role="TAKE_PROFIT_1")
RIG_TP2_ID = derive_algo_client_id(plan_hash=RIG_PLAN_HASH, role="TAKE_PROFIT_2")


def _state(rig: ProtectionRig) -> str:
    view = rig.coordinator.protection_of(RIG_PLAN_HASH)
    assert view is not None
    return view.state.value


def _last_reason(rig: ProtectionRig) -> str | None:
    view = rig.coordinator.protection_of(RIG_PLAN_HASH)
    assert view is not None
    return view.last_reason


def _rig_events(rig: ProtectionRig, event_type: str) -> list[dict[str, Any]]:
    return [json.loads(e.payload_json) for e in rig.journal.calls if e.event_type == event_type]


async def _protected_rig(**overrides: Any) -> ProtectionRig:
    """A +0.004 LONG position, the stop confirmed ACTIVE, the entry remainder cancelled."""
    rig = await make_rig(real_closer=True, **overrides)
    rig.coordinator.fill_sink(rig.stream_fill(QUANTITY))
    await rig.coordinator.step()
    await rig.coordinator.step()
    assert _state(rig) == "PROTECTED"
    return rig


async def test_operator_close_flattens_through_the_coordinator() -> None:
    rig = await _protected_rig()
    assert rig.fake.calls_to("cancel_algo_order") == []

    result = await rig.coordinator.operator_close(plan_hash=RIG_PLAN_HASH, operator_id="op-1")

    assert (result.accepted, result.code) == (True, "CLOSE_REQUESTED")
    assert _state(rig) == "CLOSE_REQUIRED"
    assert _last_reason(rig) == "OPERATOR_CLOSE"
    closes = rig.fake.calls_to("place_market_close")
    assert len(closes) == 1
    assert (closes[0]["kwargs"]["side"], closes[0]["kwargs"]["quantity"]) == ("SELL", QUANTITY)
    # The stop is kept until the plan is FLAT (D-09): nothing protective is cancelled yet.
    assert rig.fake.calls_to("cancel_algo_order") == []
    assert RIG_SL_ID in rig.fake.open_algos
    assert rig.safe_mode.entered_reasons == ["CLOSE_REQUIRED"]
    assert [(a.event, a.reason) for a in rig.alerts.alerts] == [
        ("CLOSE_REQUIRED", "OPERATOR_CLOSE")
    ]

    await rig.coordinator.step()  # two zero reads, the entry is terminal: FLAT, then the sweep

    assert _state(rig) == "FLAT"
    swept = [c["kwargs"]["client_algo_id"] for c in rig.fake.calls_to("cancel_algo_order")]
    assert swept == [RIG_SL_ID, RIG_TP1_ID, RIG_TP2_ID]
    assert len(rig.fake.calls_to("place_market_close")) == 1, "no second close"
    requested = _rig_events(rig, "OPERATOR_CLOSE_REQUESTED")
    assert len(requested) == 1
    assert requested[0]["operator_id"] == "op-1"
    assert requested[0]["state_before"] == "PROTECTED"


async def test_operator_close_of_a_resting_entry_cancels_it_and_ends_flat() -> None:
    rig = await make_rig(real_closer=True)
    assert _state(rig) == "AWAITING_FILL"

    result = await rig.coordinator.operator_close(plan_hash=RIG_PLAN_HASH, operator_id="op-1")

    assert (result.accepted, result.code) == (True, "CLOSE_REQUESTED")
    assert _state(rig) == "CLOSE_REQUIRED"
    assert rig.fake.calls_to("place_market_close") == [], "no position, so no close order"
    for _ in range(3):
        await rig.coordinator.step()
    assert _state(rig) == "FLAT"
    assert rig.entry.entry_client_order_id not in rig.fake.open_orders


async def test_operator_close_refuses_without_an_operator_id_and_sends_nothing() -> None:
    rig = await _protected_rig()
    calls_before = len(rig.fake.calls)
    rows_before = len(rig.journal.calls)

    result = await rig.coordinator.operator_close(plan_hash=RIG_PLAN_HASH, operator_id="")

    assert (result.accepted, result.code) == (False, "OPERATOR_ID_MISSING")
    assert _state(rig) == "PROTECTED"
    assert len(rig.fake.calls) == calls_before
    assert len(rig.journal.calls) == rows_before


async def test_operator_close_refuses_an_unknown_plan() -> None:
    rig = await _protected_rig()

    result = await rig.coordinator.operator_close(plan_hash="f" * 64, operator_id="op-1")

    assert (result.accepted, result.code) == (False, "UNKNOWN_PLAN")
    assert rig.fake.calls_to("place_market_close") == []


async def test_operator_close_has_nothing_to_close_for_a_flat_or_unfilled_ended_plan() -> None:
    flat = await _protected_rig()
    await flat.coordinator.operator_close(plan_hash=RIG_PLAN_HASH, operator_id="op-1")
    await flat.coordinator.step()
    assert _state(flat) == "FLAT"
    closes = len(flat.fake.calls_to("place_market_close"))
    again = await flat.coordinator.operator_close(plan_hash=RIG_PLAN_HASH, operator_id="op-1")
    assert (again.accepted, again.code) == (False, "NOTHING_TO_CLOSE")
    assert len(flat.fake.calls_to("place_market_close")) == closes

    ended = await make_rig(real_closer=True)
    ended.fake.cancel(ended.entry.entry_client_order_id)
    await ended.coordinator.step()
    assert _state(ended) == "ENTRY_ENDED_NO_FILL"
    result = await ended.coordinator.operator_close(plan_hash=RIG_PLAN_HASH, operator_id="op-1")
    assert (result.accepted, result.code) == (False, "NOTHING_TO_CLOSE")


async def test_operator_close_while_a_close_is_already_required_starts_nothing_new() -> None:
    rig = await _protected_rig()
    first = await rig.coordinator.operator_close(plan_hash=RIG_PLAN_HASH, operator_id="op-1")
    assert first.accepted is True
    alerts = len(rig.alerts.alerts)

    second = await rig.coordinator.operator_close(plan_hash=RIG_PLAN_HASH, operator_id="op-2")

    assert (second.accepted, second.code) == (False, "CLOSE_ALREADY_REQUIRED")
    assert len(rig.alerts.alerts) == alerts
    assert len(_rig_events(rig, "OPERATOR_CLOSE_REQUESTED")) == 1


async def test_operator_close_never_sends_a_guessed_quantity_when_the_position_is_unreadable() -> (
    None
):
    rig = await _protected_rig()
    for _ in range(50):
        rig.fake.fail_next("snapshot_positions", RuntimeError("scripted read failure"))

    result = await rig.coordinator.operator_close(plan_hash=RIG_PLAN_HASH, operator_id="op-1")

    assert result.accepted is True, "the request is accepted; the close itself fails closed"
    assert rig.fake.calls_to("place_market_close") == []
    assert _state(rig) == "CLOSE_FAILED"
    assert RIG_SL_ID in rig.fake.open_algos


async def test_manager_operator_close_position_is_a_thin_wrapper() -> None:
    from src.execution.manager import operator_close_position

    rig = await _protected_rig()

    result = await operator_close_position(
        coordinator=rig.coordinator, plan_hash=RIG_PLAN_HASH, operator_id="op-1"
    )

    assert (result.accepted, result.code) == (True, "CLOSE_REQUESTED")
    assert _state(rig) == "CLOSE_REQUIRED"
    tree = ast.parse(MANAGER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "operator_close_position":
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            attrs = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
            assert "adapter" not in names | attrs
            assert attrs == {"operator_close"}
            break
    else:
        raise AssertionError("operator_close_position not found")


# --------------------------------------------------------------------------- #
# Plan 20-17, Task 2 (D-26, D-06, D077, RISK-03; owner direction 1 on the D-26/D077 conflict):
# operator_protect_position has NO placement of its own. In the never-confirmed branch it runs the
# coordinator's own per-plan step once; in a confirmed state it only adopts an ACTIVE stop; after a
# confirmed stop was lost, in CLOSE_REQUIRED / CLOSE_FAILED and on an unknown stop history it
# refuses with nothing sent. Evidence label: executed tests with the Binance-semantics fake; nothing
# is [DEMO].
# --------------------------------------------------------------------------- #

RIG_ENTRY_STOP_PRICE = Decimal("59000.00")
MAX_UNPROTECTED_MS = 7777
ENTRY_TERMINAL_TIMEOUT_MS = 13333
PROTECT_REFUSED = "OPERATOR_PROTECT_REFUSED"
PROTECT_STEPPED = "OPERATOR_PROTECT_STEPPED"
STOP_ADOPTED = "OPERATOR_STOP_ADOPTED"


class PlacementSpy:
    """Records every STOP_LOSS placement and flags any price other than entry.sl_trigger_price."""

    def __init__(self, rig: ProtectionRig) -> None:
        self.prices: list[Decimal] = []
        self.violations: list[Decimal] = []
        original = rig.fake.place_algo_protective

        async def spy(**kwargs: Any) -> Any:
            price = kwargs.get("trigger_price")
            self.prices.append(price)
            if price != RIG_ENTRY_STOP_PRICE:
                self.violations.append(price)
            return await original(**kwargs)

        rig.fake.place_algo_protective = spy  # type: ignore[method-assign]


def _tracked(rig: ProtectionRig) -> Any:
    return rig.coordinator._tracked[RIG_PLAN_HASH]


def _snapshot(rig: ProtectionRig) -> tuple[Any, ...]:
    tracked = _tracked(rig)
    return (tracked.state, tracked.seq, tracked.stop_lost_at, tracked.close_branch)


def _methods_since(rig: ProtectionRig, count: int) -> list[str]:
    return [c["method"] for c in rig.fake.calls[count:]]


async def _unprotected_never_confirmed(**overrides: Any) -> ProtectionRig:
    """First fill 0.004, the stop placement failed ambiguously: UNPROTECTED, never confirmed."""
    rig = await make_rig(real_closer=True, **overrides)
    rig.fake.fail_next("place_algo_protective", RuntimeError("scripted ambiguous failure"))
    rig.coordinator.fill_sink(rig.stream_fill(QUANTITY))
    await rig.coordinator.step()
    assert _state(rig) == "UNPROTECTED"
    assert _tracked(rig).stop_confirmed_at is None
    return rig


async def _protected_entry_open(**overrides: Any) -> ProtectionRig:
    """The stop is confirmed ACTIVE by REST and the entry remainder is still open."""
    rig = await make_rig(real_closer=True, **overrides)
    for _ in range(2):
        rig.fake.fail_next("cancel_normal_order", RuntimeError("scripted ambiguous failure"))
    rig.coordinator.fill_sink(rig.stream_fill(QUANTITY))
    await rig.coordinator.step()
    await rig.coordinator.step()
    assert _state(rig) == "PROTECTED_ENTRY_OPEN"
    return rig


async def _stop_lost_unprotected(**overrides: Any) -> ProtectionRig:
    """A confirmed stop that was lost while the position cannot be read: UNPROTECTED, STOP_LOST."""
    rig = await _protected_entry_open(**overrides)
    await rig.clock.advance(1.0)
    rig.fake.trigger_stop(rig.stop_id)
    for _ in range(500):
        rig.fake.fail_next("snapshot_positions", RuntimeError("scripted read failure"))
    await rig.coordinator.step()
    assert _state(rig) == "UNPROTECTED"
    assert _last_reason(rig) == "STOP_LOST"
    assert _tracked(rig).stop_lost_at is not None
    return rig


async def _assert_refused(
    rig: ProtectionRig, code: str, *, operator_id: str = "op-9", allowed: tuple[str, ...] = ()
) -> None:
    """The operator_protect call is refused with `code`, sends nothing and changes nothing."""
    calls = len(rig.fake.calls)
    snapshot = _snapshot(rig)
    rows = len(_rig_events(rig, PROTECT_REFUSED))
    result = await rig.coordinator.operator_protect(
        plan_hash=RIG_PLAN_HASH, operator_id=operator_id
    )
    assert (result.accepted, result.code) == (False, code)
    assert set(_methods_since(rig, calls)) <= set(allowed)
    assert _snapshot(rig) == snapshot
    refused = _rig_events(rig, PROTECT_REFUSED)
    assert len(refused) == rows + 1
    assert refused[-1]["code"] == code
    assert refused[-1]["operator_id"] == operator_id


async def test_operator_protect_never_places_after_a_confirmed_stop_was_lost() -> None:
    """UNPROTECTED STOP_LOST: zero adapter calls; the D077 deadline still escalates."""
    rig = await _stop_lost_unprotected()
    spy = PlacementSpy(rig)
    lost_at = _tracked(rig).stop_lost_at

    await _assert_refused(rig, "REPLACEMENT_FORBIDDEN_STOP_LOST")

    assert spy.prices == []
    assert _tracked(rig).stop_lost_at == lost_at
    # The coordinator's own supervision is untouched: it escalates at stop_lost_at + the limit.
    await rig.clock.advance((MAX_UNPROTECTED_MS - 1) / 1000)
    await rig.coordinator.step()
    assert _state(rig) == "UNPROTECTED"
    await rig.clock.advance(0.001)
    await rig.coordinator.step()
    assert _state(rig) in ("CLOSE_REQUIRED", "CLOSE_FAILED")
    assert _last_reason(rig) in ("B4_STOP_LOST_UNRESOLVED", "CLOSE_FAILED", "CLOSE_NOT_SENT")
    assert spy.prices == []


async def test_operator_protect_never_places_after_a_stop_lost_in_close_required() -> None:
    """CLOSE_REQUIRED / CLOSE_FAILED from both B4 branches: refused, zero adapter calls."""
    # B4_FILL_AFTER_STOP: the confirmed stop triggers, the still-open entry fills again.
    fill_after = await _protected_entry_open()
    spy = PlacementSpy(fill_after)
    fill_after.fake.trigger_stop(fill_after.stop_id)
    fill_after.fake.fill(fill_after.entry_id, quantity=Decimal("0.002"))
    await fill_after.coordinator.step()
    assert _state(fill_after) in ("CLOSE_REQUIRED", "CLOSE_FAILED")
    assert _tracked(fill_after).close_branch == "B4_FILL_AFTER_STOP"
    await _assert_refused(fill_after, "REPLACEMENT_FORBIDDEN_STOP_LOST")
    assert spy.prices == []

    # B4_STOP_LOST_UNRESOLVED: the loss was never resolved within the deadline.
    unresolved = await _stop_lost_unprotected()
    spy2 = PlacementSpy(unresolved)
    await unresolved.clock.advance(MAX_UNPROTECTED_MS / 1000)
    await unresolved.coordinator.step()
    assert _state(unresolved) in ("CLOSE_REQUIRED", "CLOSE_FAILED")
    assert _tracked(unresolved).close_branch == "B4_STOP_LOST_UNRESOLVED"
    await _assert_refused(unresolved, "REPLACEMENT_FORBIDDEN_STOP_LOST")
    assert spy2.prices == []


async def test_operator_protect_refuses_every_other_close_required_branch() -> None:
    """No stop is restored as a workaround for the D077 close (CLOSE_REQUIRED refusal)."""
    code = "REPLACEMENT_FORBIDDEN_CLOSE_REQUIRED"

    # B5: the stop was rejected definitively.
    b5 = await make_rig(real_closer=True)
    b5.fake.reject_next_algo(-2021)
    b5.coordinator.fill_sink(b5.stream_fill(QUANTITY))
    await b5.coordinator.step()
    assert _tracked(b5).close_branch == "B5_STOP_REJECTED"
    await _assert_refused(b5, code)

    # B2: the stop stayed unconfirmed to the deadline (a status that is not ACTIVE).
    b2 = await make_rig(real_closer=True)
    b2.coordinator.fill_sink(b2.stream_fill(QUANTITY))
    await b2.coordinator.step()
    b2.fake.open_algos[b2.stop_id].status = "TRIGGERING"
    await b2.clock.advance(MAX_UNPROTECTED_MS / 1000)
    await b2.coordinator.step()
    assert _tracked(b2).close_branch == "B2_STOP_UNCONFIRMED"
    await _assert_refused(b2, code)

    # B1: the stop is good but the entry stayed open past its own deadline.
    b1 = await _protected_entry_open()
    for _ in range(5):
        b1.fake.fail_next("cancel_normal_order", RuntimeError("scripted ambiguous failure"))
    await b1.clock.advance(ENTRY_TERMINAL_TIMEOUT_MS / 1000)
    await b1.coordinator.step()
    assert _tracked(b1).close_branch == "B1_ENTRY_NOT_TERMINAL"
    await _assert_refused(b1, code)

    # OPERATOR_CLOSE: the operator's own close is not undone by a stop.
    own = await _protected_rig()
    await own.coordinator.operator_close(plan_hash=RIG_PLAN_HASH, operator_id="op-1")
    await _assert_refused(own, code)

    # The remaining branch codes, set on a plan that is in CLOSE_REQUIRED.
    for branch in ("B3_BOTH_AMBIGUOUS", "NO_POSITION_ON_STOP_BUT_EXPOSED"):
        rig = await _protected_rig()
        await rig.coordinator.operator_close(plan_hash=RIG_PLAN_HASH, operator_id="op-1")
        _tracked(rig).close_branch = branch
        await _assert_refused(rig, code)


async def test_operator_protect_refuses_unknown_stop_history() -> None:
    """stop_history_known False, or fields that contradict each other: fail closed, no guess."""
    rig = await _unprotected_never_confirmed()
    spy = PlacementSpy(rig)
    _tracked(rig).stop_history_known = False
    await _assert_refused(rig, "STOP_HISTORY_UNKNOWN")

    inconsistent = await _unprotected_never_confirmed()
    _tracked(inconsistent).stop_lost_at = inconsistent.clock.now()  # lost, yet never confirmed
    await _assert_refused(inconsistent, "STOP_HISTORY_UNKNOWN")

    confirmed = await _protected_rig()
    _tracked(confirmed).stop_history_known = False
    await _assert_refused(confirmed, "STOP_HISTORY_UNKNOWN")
    assert spy.prices == []


async def test_operator_protect_delegates_to_the_coordinator_step() -> None:
    """Never-confirmed UNPROTECTED: one fresh position read, then the coordinator's own step."""
    rig = await _unprotected_never_confirmed()
    spy = PlacementSpy(rig)
    assert len(rig.fake.calls_to("place_algo_protective")) == 1
    calls = len(rig.fake.calls)

    result = await rig.coordinator.operator_protect(plan_hash=RIG_PLAN_HASH, operator_id="op-3")

    assert (result.accepted, result.code) == (True, "COORDINATOR_STEPPED")
    methods = _methods_since(rig, calls)
    assert methods[0] == "snapshot_positions", "the position is read fresh first"
    # The coordinator's B2/B3 rule: the stop is queried by its id, found absent, placed again
    # under the SAME id at the plan stop price, and nothing else is sent.
    assert len(rig.fake.calls_to("place_algo_protective")) == 2
    placed = rig.fake.calls_to("place_algo_protective")[-1]["kwargs"]
    assert placed["client_algo_id"] == rig.stop_id
    assert placed["trigger_price"] == RIG_ENTRY_STOP_PRICE
    assert spy.prices == [RIG_ENTRY_STOP_PRICE]
    assert "place_market_close" not in methods
    assert "cancel_algo_order" not in methods
    assert _state(rig) == "UNPROTECTED", "a placement is never protection; only REST ACTIVE is"
    row = _rig_events(rig, PROTECT_STEPPED)[-1]
    assert row["operator_id"] == "op-3"
    assert (row["state_before"], row["state_after"]) == ("UNPROTECTED", "UNPROTECTED")

    # A second call: the stop now rests ACTIVE; nothing is placed and REST confirms it.
    again = await rig.coordinator.operator_protect(plan_hash=RIG_PLAN_HASH, operator_id="op-3")
    assert (again.accepted, again.code) == (True, "COORDINATOR_STEPPED")
    assert len(rig.fake.calls_to("place_algo_protective")) == 2
    assert _state(rig) in ("PROTECTED", "PROTECTED_ENTRY_OPEN")
    assert _tracked(rig).stop_confirmed_at is not None
    assert spy.violations == []


async def test_operator_protect_never_widens_the_stop() -> None:
    """RISK-03: every placement any path can cause is at entry.sl_trigger_price."""
    rig = await _unprotected_never_confirmed()
    spy = PlacementSpy(rig)
    # The mark moved far from the plan; the plan stop is still the only price ever used.
    rig.fake.set_mark_price(SYMBOL, Decimal("50000"), rig.clock.now())

    await rig.coordinator.operator_protect(plan_hash=RIG_PLAN_HASH, operator_id="op-3")
    await rig.coordinator.operator_protect(plan_hash=RIG_PLAN_HASH, operator_id="op-3")

    assert spy.prices == [RIG_ENTRY_STOP_PRICE]
    assert spy.violations == []


async def test_operator_protect_cannot_extend_max_unprotected_ms() -> None:
    """Past the deadline the delegated step escalates and places nothing (a status not ACTIVE)."""
    rig = await make_rig(real_closer=True)
    rig.coordinator.fill_sink(rig.stream_fill(QUANTITY))
    await rig.coordinator.step()
    rig.fake.open_algos[rig.stop_id].status = "TRIGGERING"
    spy = PlacementSpy(rig)
    placements = len(rig.fake.calls_to("place_algo_protective"))

    await rig.clock.advance((MAX_UNPROTECTED_MS - 1) / 1000)
    early = await rig.coordinator.operator_protect(plan_hash=RIG_PLAN_HASH, operator_id="op-3")
    assert (early.accepted, early.code) == (True, "COORDINATOR_STEPPED")
    assert _state(rig) == "UNPROTECTED"

    await rig.clock.advance(0.001)
    late = await rig.coordinator.operator_protect(plan_hash=RIG_PLAN_HASH, operator_id="op-3")

    assert (late.accepted, late.code) == (True, "COORDINATOR_STEPPED")
    assert _state(rig) == "CLOSE_REQUIRED"
    assert _last_reason(rig) == "B2_STOP_UNCONFIRMED"
    assert len(rig.fake.calls_to("place_algo_protective")) == placements
    assert spy.prices == []
    row = _rig_events(rig, PROTECT_STEPPED)[-1]
    assert (row["state_before"], row["state_after"]) == ("UNPROTECTED", "CLOSE_REQUIRED")


async def test_operator_protect_position_problems_send_nothing() -> None:
    """Unreadable -> POSITION_UNREADABLE, zero -> NO_EXPOSURE, wrong sign -> WRONG_SIDE."""
    reads_only = ("snapshot_positions",)

    unreadable = await _unprotected_never_confirmed()
    unreadable.fake.fail_next("snapshot_positions", RuntimeError("scripted read failure"))
    await _assert_refused(unreadable, "POSITION_UNREADABLE", allowed=reads_only)

    zero = await _unprotected_never_confirmed()
    zero.fake.positions[SYMBOL] = Decimal("0")
    await _assert_refused(zero, "NO_EXPOSURE", allowed=reads_only)

    wrong = await _unprotected_never_confirmed()
    wrong.fake.positions[SYMBOL] = Decimal("-0.004")  # contradicts the LONG plan
    await _assert_refused(wrong, "WRONG_SIDE", allowed=reads_only)

    for rig in (unreadable, zero, wrong):
        assert len(rig.fake.calls_to("place_algo_protective")) == 1
        assert rig.fake.calls_to("place_market_close") == []


async def test_operator_protect_adopts_an_active_stop_in_every_confirmed_state() -> None:
    """PROTECTED_ENTRY_OPEN, PROTECTED, COMPLETE: STOP_ADOPTED, nothing placed, state unchanged."""
    entry_open = await _protected_entry_open()
    protected = await _protected_rig()
    complete = await _protected_rig()
    await complete.coordinator.step()  # PROTECTED -> COMPLETE (the take profits attach)
    assert _state(complete) == "COMPLETE"

    for rig, state in (
        (entry_open, "PROTECTED_ENTRY_OPEN"),
        (protected, "PROTECTED"),
        (complete, "COMPLETE"),
    ):
        placements = len(rig.fake.calls_to("place_algo_protective"))
        snapshot = _snapshot(rig)
        calls = len(rig.fake.calls)

        result = await rig.coordinator.operator_protect(plan_hash=RIG_PLAN_HASH, operator_id="op-4")

        assert (result.accepted, result.code) == (True, "STOP_ADOPTED"), state
        assert _snapshot(rig) == snapshot
        assert len(rig.fake.calls_to("place_algo_protective")) == placements
        assert set(_methods_since(rig, calls)) <= {
            "snapshot_positions",
            "query_algo_order_by_client",
        }
        adopted = _rig_events(rig, STOP_ADOPTED)[-1]
        assert (adopted["operator_id"], adopted["code"], adopted["state"]) == (
            "op-4",
            "STOP_ADOPTED",
            state,
        )


async def test_operator_protect_refuses_a_confirmed_stop_that_is_no_longer_active() -> None:
    """A confirmed stop that reads ABSENT or NOT_ACTIVE is lost: refused, left to D077."""
    gone = await _protected_rig()
    spy = PlacementSpy(gone)
    del gone.fake.open_algos[gone.stop_id]  # the stop vanished from the book and the history
    await _assert_refused(
        gone,
        "REPLACEMENT_FORBIDDEN_STOP_LOST",
        allowed=("snapshot_positions", "query_algo_order_by_client"),
    )

    not_active = await _protected_rig()
    not_active.fake.open_algos[not_active.stop_id].status = "TRIGGERING"
    await _assert_refused(
        not_active,
        "REPLACEMENT_FORBIDDEN_STOP_LOST",
        allowed=("snapshot_positions", "query_algo_order_by_client"),
    )
    assert spy.prices == []
    # The state is untouched by the control; the coordinator's own step then applies D077.
    await not_active.coordinator.step()
    assert _state(not_active) == "CLOSE_REQUIRED"
    assert _last_reason(not_active) == "B4_FILL_AFTER_STOP"


async def test_operator_protect_stop_query_failing_is_stop_unreadable() -> None:
    rig = await _protected_rig()
    rig.fake.fail_next("query_algo_order_by_client", RuntimeError("scripted read failure"))

    await _assert_refused(
        rig, "STOP_UNREADABLE", allowed=("snapshot_positions", "query_algo_order_by_client")
    )

    assert len(rig.fake.calls_to("place_algo_protective")) == 1


async def test_operator_protect_has_nothing_to_protect_without_a_filled_position() -> None:
    awaiting = await make_rig(real_closer=True)
    await _assert_refused(awaiting, "NOTHING_TO_PROTECT")

    ended = await make_rig(real_closer=True)
    ended.fake.cancel(ended.entry.entry_client_order_id)
    await ended.coordinator.step()
    assert _state(ended) == "ENTRY_ENDED_NO_FILL"
    await _assert_refused(ended, "NOTHING_TO_PROTECT")

    flat = await _protected_rig()
    await flat.coordinator.operator_close(plan_hash=RIG_PLAN_HASH, operator_id="op-1")
    await flat.coordinator.step()
    assert _state(flat) == "FLAT"
    await _assert_refused(flat, "NOTHING_TO_PROTECT")

    unresolved = await make_rig(real_closer=True)
    _tracked(unresolved).state = ProtectionState.ENTRY_UNRESOLVED
    await _assert_refused(unresolved, "NOTHING_TO_PROTECT")


async def test_operator_protect_refuses_an_empty_operator_id_and_an_unknown_plan() -> None:
    rig = await _unprotected_never_confirmed()
    calls = len(rig.fake.calls)
    rows = len(rig.journal.calls)

    missing = await rig.coordinator.operator_protect(plan_hash=RIG_PLAN_HASH, operator_id="")
    unknown = await rig.coordinator.operator_protect(plan_hash="f" * 64, operator_id="op-1")

    assert (missing.accepted, missing.code) == (False, "OPERATOR_ID_MISSING")
    assert (unknown.accepted, unknown.code) == (False, "UNKNOWN_PLAN")
    assert len(rig.fake.calls) == calls
    assert len(rig.journal.calls) == rows


async def test_operator_protect_gate_refusal_in_the_delegated_step_is_the_coordinators_own() -> (
    None
):
    """RestGateRefusal inside the step: journaled as not sent, PENDING row, no retry, no bypass."""
    from src.adapters.binance_ratelimit_gate import RestGateRefusal

    from tests.support.pending_action_fakes import InMemoryPendingActionStore

    store = InMemoryPendingActionStore()
    rig = await _unprotected_never_confirmed(pending_actions=store)
    placements = len(rig.fake.calls_to("place_algo_protective"))
    rig.fake.fail_next("place_algo_protective", RestGateRefusal("RATE_LIMIT_PAUSE_429", 60))

    result = await rig.coordinator.operator_protect(plan_hash=RIG_PLAN_HASH, operator_id="op-5")

    assert (result.accepted, result.code) == (True, "COORDINATOR_STEPPED")
    assert len(rig.fake.calls_to("place_algo_protective")) == placements + 1, "one try, no retry"
    assert len(rig.journal.by_type("STOP_NOT_SENT")) == 1
    assert [row.kind.value for row in store.list_open()] == ["STOP_NOT_SENT"]
    assert _state(rig) == "UNPROTECTED"


def test_operator_protect_has_no_placement_and_no_transition_of_its_own() -> None:
    """operator_protect and its helpers never place, close, cancel or move a plan's state.

    The only thing that can place is the coordinator's own per-plan step that
    `_operator_protect_step` runs; none of these bodies names a placement, close, cancel or
    `_transition` call.
    """
    path = Path(__file__).parent.parent / "src" / "execution" / "protection.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = {
        "place_algo_protective",
        "_place_stop",
        "_transition",
        "_enter_close_required",
        "_attempt_close",
        "place_market_close",
        "cancel_algo_order",
        "cancel_normal_order",
        "close_position",
    }
    own = {
        "operator_protect",
        "_operator_protect_precheck",
        "_operator_protect_position_refusal",
        "_operator_protect_step",
        "_operator_protect_stop_refusal",
    }
    seen: set[str] = set()
    called_by: dict[str, set[str]] = {}
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name == "ProtectionCoordinator":
            for node in cls.body:
                if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name in own:
                    seen.add(node.name)
                    called_by[node.name] = {
                        n.func.attr
                        if isinstance(n.func, ast.Attribute)
                        else getattr(n.func, "id", "")
                        for n in ast.walk(node)
                        if isinstance(n, ast.Call)
                    }
                    assert not called_by[node.name] & forbidden, node.name
    assert seen == own
    assert "_step_plan" in called_by["_operator_protect_step"]
    assert "_operator_protect_step" in called_by["operator_protect"]


async def test_manager_operator_protect_position_is_a_thin_wrapper() -> None:
    from src.execution.manager import operator_protect_position

    rig = await _protected_rig()

    result = await operator_protect_position(
        coordinator=rig.coordinator, plan_hash=RIG_PLAN_HASH, operator_id="op-6"
    )

    assert (result.accepted, result.code) == (True, "STOP_ADOPTED")
    tree = ast.parse(MANAGER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "operator_protect_position":
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            attrs = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
            assert "adapter" not in names | attrs
            assert attrs == {"operator_protect"}
            break
    else:
        raise AssertionError("operator_protect_position not found")


# --------------------------------------------------------------------------- #
# Plan 20-17, Task 3 (D-26, EXEC-06, D-16): the five controls exist, are listed in one place, and
# act during a journal outage. Evidence label: executed tests with fakes; nothing is [DEMO].
# --------------------------------------------------------------------------- #

EXEC06_NAMES = {
    "cancel_pending_strategy_orders",
    "disable_new_entries",
    "close_strategy_positions",
    "replace_protection",
    "enter_safe_mode",
}


def _resolve(dotted: str) -> Any:
    import importlib

    parts = dotted.split(".")
    for split in range(len(parts) - 1, 0, -1):
        try:
            target: Any = importlib.import_module(".".join(parts[:split]))
        except ModuleNotFoundError:
            continue
        for name in parts[split:]:
            target = getattr(target, name)
        return target
    raise AssertionError(f"cannot resolve {dotted}")


def test_exec06_five_controls_exist() -> None:
    from src.execution import manager

    controls = manager.EXEC06_CONTROLS
    assert set(controls) == EXEC06_NAMES
    for name, dotted in controls.items():
        assert callable(_resolve(dotted)), (name, dotted)
    assert controls["close_strategy_positions"] == "src.execution.manager.operator_close_position"
    assert controls["replace_protection"] == "src.execution.manager.operator_protect_position"
    assert "EXEC06_CONTROLS" in manager.__all__


def test_exec06_controls_that_take_an_operator_id_refuse_an_empty_one() -> None:
    from src.execution.enablement import LiveEnablementController

    controller = LiveEnablementController(journal=RecordingJournal())
    with pytest.raises(ValueError):
        controller.disable(operator_id="", now_utc=NOW_UTC)


async def test_exec06_cancel_pending_orders_acts_during_a_journal_outage(tmp_path: Path) -> None:
    from src.execution.manager import expire_pending_entry
    from src.ops.spill import LocalSpill

    fake = ScriptedFake()
    await _resting_entry_with_legs(fake)
    spill = LocalSpill(tmp_path / "spill")

    await expire_pending_entry(
        plan_hash=PLAN_HASH,
        symbol=SYMBOL,
        adapter=fake,  # type: ignore[arg-type]
        journal=RaisingJournal(),
        now_utc=NOW_UTC,
        trigger_reason="operator_close",
        spill=spill,
    )

    assert ENTRY_ID not in fake.open_orders
    assert {r.event.event_type for r in spill.pending()} == {"ENTRY_EXPIRY"}


def test_exec06_disable_acts_during_a_journal_outage(tmp_path: Path) -> None:
    from src.execution.enablement import LiveEnablementController
    from src.ops.spill import LocalSpill

    spill = LocalSpill(tmp_path / "spill")
    controller = LiveEnablementController(journal=RaisingJournal(), spill=spill)
    controller._disabled = False  # noqa: SLF001 - the state a prior enable leaves behind

    controller.disable(operator_id="op-1", now_utc=NOW_UTC)

    assert controller.is_disabled is True
    assert [r.event.event_type for r in spill.pending()] == ["LIVE_ORDERS_DISABLED"]


def test_exec06_safe_mode_is_entered_during_a_journal_outage() -> None:
    """The flag flips before the journal is touched. This control has no spill (finding): the
    journal error propagates to the caller, who must treat it as an audit gap, not as "not in
    SAFE_MODE"."""
    from src.execution.manager import safe_mode_freeze
    from src.reconcile.safe_mode import SafeModeController

    controller = SafeModeController(adapter=ScriptedFake(), journal=RaisingJournal())  # type: ignore[arg-type]

    with pytest.raises(Exception, match="PostgreSQL unavailable"):
        safe_mode_freeze(safe_mode_controller=controller, reason="MANUAL_CLOSE", now_utc=NOW_UTC)

    assert controller.in_safe_mode is True


async def test_exec06_operator_close_acts_during_a_journal_outage(tmp_path: Path) -> None:
    from src.ops.spill import LocalSpill

    spill = LocalSpill(tmp_path / "spill")
    rig = await _protected_rig(spill=spill)
    rig.coordinator._journal = RaisingJournal()  # noqa: SLF001 - the database goes down now

    result = await rig.coordinator.operator_close(plan_hash=RIG_PLAN_HASH, operator_id="op-7")

    assert (result.accepted, result.code) == (True, "CLOSE_REQUESTED")
    assert len(rig.fake.calls_to("place_market_close")) == 1, "the close is not held for the audit"
    assert _state(rig) == "CLOSE_REQUIRED"
    (record,) = [r for r in spill.pending() if r.event.event_type == "OPERATOR_CLOSE_REQUESTED"]
    assert json.loads(record.event.payload_json)["operator_id"] == "op-7"


async def test_exec06_operator_close_without_a_spill_still_acts_and_enters_db_failure() -> None:
    rig = await _protected_rig()
    rig.coordinator._journal = RaisingJournal()  # noqa: SLF001

    result = await rig.coordinator.operator_close(plan_hash=RIG_PLAN_HASH, operator_id="op-7")

    assert result.accepted is True
    assert len(rig.fake.calls_to("place_market_close")) == 1
    assert "DB_FAILURE" in rig.safe_mode.entered_reasons


async def test_exec06_operator_protect_acts_during_a_journal_outage(tmp_path: Path) -> None:
    from src.ops.spill import LocalSpill

    # The never-confirmed branch: the delegated coordinator step still runs.
    spill = LocalSpill(tmp_path / "spill_step")
    stepped = await _unprotected_never_confirmed(spill=spill)
    stepped.coordinator._journal = RaisingJournal()  # noqa: SLF001
    placements = len(stepped.fake.calls_to("place_algo_protective"))

    result = await stepped.coordinator.operator_protect(plan_hash=RIG_PLAN_HASH, operator_id="op-8")

    assert (result.accepted, result.code) == (True, "COORDINATOR_STEPPED")
    assert len(stepped.fake.calls_to("place_algo_protective")) == placements + 1
    (row,) = [r for r in spill.pending() if r.event.event_type == "OPERATOR_PROTECT_STEPPED"]
    assert json.loads(row.event.payload_json)["operator_id"] == "op-8"

    # A refusal: nothing is sent and the refusal row reaches the spill.
    refusal_spill = LocalSpill(tmp_path / "spill_refusal")
    lost = await _stop_lost_unprotected(spill=refusal_spill)
    lost.coordinator._journal = RaisingJournal()  # noqa: SLF001
    calls = len(lost.fake.calls)

    refused = await lost.coordinator.operator_protect(plan_hash=RIG_PLAN_HASH, operator_id="op-8")

    assert (refused.accepted, refused.code) == (False, "REPLACEMENT_FORBIDDEN_STOP_LOST")
    assert len(lost.fake.calls) == calls
    refusals = [r for r in refusal_spill.pending() if r.event.event_type == PROTECT_REFUSED]
    assert len(refusals) == 1
    assert json.loads(refusals[0].event.payload_json)["code"] == "REPLACEMENT_FORBIDDEN_STOP_LOST"


def test_execute_approved_plan_is_untouched_by_the_operator_controls() -> None:
    """The EXEC-06 additions sit after the manual-control block; the placement path is unchanged."""
    tree = ast.parse(MANAGER.read_text(encoding="utf-8"))
    names = {n.name for n in tree.body if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef)}
    assert {"operator_close_position", "operator_protect_position"} <= names
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "execute_approved_plan":
            called = {
                n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
                for n in ast.walk(node)
                if isinstance(n, ast.Call)
            }
            assert not called & {"operator_close", "operator_protect", "operator_close_position"}
