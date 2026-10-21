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

from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
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
