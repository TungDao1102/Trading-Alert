"""The take-profit step of the single protection model (Phase 19, plan 19-16).

`attach_protectives_to_fill(entry=..., position_quantity=..., live_lot_filters=..., adapter=...,
intent_store=..., now_utc=..., safe_mode_controller=...)` runs after the entry is terminal and the
stop is confirmed (D-10, D-18):

* it is bound to the `RestingEntry` built from the bound plan (D-01): no symbol, side or plan-hash
  argument of its own, and an entry whose snapshot, filters or trade plan id disagree is refused
  before any adapter call (PLAN_SYMBOL_MISMATCH);
* it never places or cancels a stop (D-11, D-17, T-19-42): the stop must be ACTIVE by a REST query;
  anything else holds ENTRY_WITHOUT_PROTECTIVE with SAFE_MODE and places no take profit;
* TP1 and TP2 are sized by `size_take_profits` from the REST position quantity, written ahead
  (INTENDED then SENT, TP1 with its quantity) before each placement, placed query-first by their
  deterministic id and confirmed by a REST query (D-18, D-19, D-20);
* the plan snapshot must be valid for live; a stale but COMPLETE one is re-sized with the live
  exchangeInfo filters, an INCOMPLETE one or a stale one without live filters is refused (D-20).

Every scenario goes through `run_attach`, which asserts that attach made no `place_algo_protective`
call with the STOP_LOSS id and no cancel of any order.

All numbers are TEST_ONLY (`tests/support/protection_doubles.py`); the fake exchange is an offline
test double, so a green test proves agreement with the fake, not with Binance.

Legacy inventory (research P12): the plan 09-04 tests that fed fill events, a protective template
and a candidate position side into attach (and the golden fixture pair under
`tests/fixtures/phase9/attach`) are replaced as listed in the plan 19-16 SUMMARY.
"""

from __future__ import annotations

import dataclasses
import inspect
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_usdm import AlgoOrderProbe, AlgoPlacementResult
from src.domain.algo_status import is_protection_confirmed
from src.domain.enums import ExecutionIntentStatus
from src.domain.lot_filters import LotFilters
from src.execution.manager import AttachOutcome, attach_protectives_to_fill
from src.execution.order_ids import derive_algo_client_id
from src.persistence.errors import StoreUnavailable

from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.intent_store_fakes import FailingIntentStore
from tests.support.protection_doubles import (
    TEST_ONLY_PLAN_HASH,
    TEST_ONLY_REGISTERED_AT,
    TEST_ONLY_SNAPSHOT_TTL,
    TEST_ONLY_SYMBOL,
    LoggingStore,
    ProtectionRig,
    complete_constraint_snapshot,
    lot_filters_for_tests,
    make_rig,
    resting_entry_for_tests,
)

STOP_ID = derive_algo_client_id(plan_hash=TEST_ONLY_PLAN_HASH, role="STOP_LOSS")
TP1_ID = derive_algo_client_id(plan_hash=TEST_ONLY_PLAN_HASH, role="TAKE_PROFIT_1")
TP2_ID = derive_algo_client_id(plan_hash=TEST_ONLY_PLAN_HASH, role="TAKE_PROFIT_2")
ALL_THREE = ("STOP_LOSS", "TAKE_PROFIT_1", "TAKE_PROFIT_2")
HOLD = "ENTRY_WITHOUT_PROTECTIVE"
# One minute after the TEST_ONLY snapshot capture: well inside the TEST_ONLY TTL.
FRESH_NOW = TEST_ONLY_REGISTERED_AT + timedelta(minutes=1)
STALE_NOW = TEST_ONLY_REGISTERED_AT + TEST_ONLY_SNAPSHOT_TTL + timedelta(minutes=1)


# --------------------------------------------------------------------------- #
# Helpers shared with the other plan 19-16 test files.
# --------------------------------------------------------------------------- #


async def protected_rig(
    *, filled: Decimal = Decimal("0.010"), stop: bool = True, **entry_overrides: Any
) -> ProtectionRig:
    """A rig whose entry is terminal (filled, or partially filled then cancelled), with the
    REST position `filled` and, when `stop`, an ACTIVE closePosition stop under its id.

    The call log and the fake's call list are cleared afterwards so a test sees only attach.
    """
    rig = await make_rig(register=False, **entry_overrides)
    rig.fake.fill(rig.entry_id, quantity=filled)
    if filled < rig.entry.entry_quantity:
        rig.fake.cancel(rig.entry_id)
    if stop:
        await rig.fake.place_algo_protective(
            symbol=rig.entry.symbol,
            side=rig.entry.exit_side,
            algo_type="CONDITIONAL",
            type="STOP_MARKET",
            position_side="BOTH",
            trigger_price=rig.entry.sl_trigger_price,
            close_position=True,
            quantity=None,
            working_type=rig.entry.working_type,
            client_algo_id=STOP_ID,
        )
    rig.log.clear()
    rig.fake.calls.clear()
    return rig


def script_algo_status(fake: BinanceSemanticsFakeAdapter, client_algo_id: str, status: Any) -> None:
    """The REST query of one algo id answers `status` (found), whatever the fake holds."""
    original = fake.query_algo_order_by_client

    async def query(**kwargs: Any) -> Any:
        if kwargs["client_algo_id"] == client_algo_id:
            return AlgoOrderProbe(
                client_algo_id=client_algo_id,
                found=True,
                algo_status=status,
                update_time_utc=None,
            )
        return await original(**kwargs)

    fake.query_algo_order_by_client = query  # type: ignore[method-assign]


async def run_attach(
    rig: ProtectionRig,
    *,
    entry: Any = None,
    position_quantity: Decimal = Decimal("0.010"),
    live_lot_filters: LotFilters | None = None,
    now_utc: Any = FRESH_NOW,
    store: Any = None,
    adapter: Any = None,
    safe_mode: Any = "rig",
) -> AttachOutcome:
    """Call attach; every scenario also proves attach never touches the stop (T-19-42)."""
    outcome = await attach_protectives_to_fill(
        entry=rig.entry if entry is None else entry,
        position_quantity=position_quantity,
        live_lot_filters=live_lot_filters,
        adapter=rig.fake if adapter is None else adapter,
        intent_store=LoggingStore(rig.inner_store, rig.log) if store is None else store,
        now_utc=now_utc,
        safe_mode_controller=rig.safe_mode if safe_mode == "rig" else safe_mode,
    )
    assert_stop_untouched(rig)
    return outcome


def assert_stop_untouched(rig: ProtectionRig) -> None:
    placed_ids = [c["kwargs"]["client_algo_id"] for c in rig.fake.calls_to("place_algo_protective")]
    assert STOP_ID not in placed_ids, "attach placed a stop"
    assert rig.fake.calls_to("cancel_algo_order") == [], "attach cancelled an algo order"
    assert rig.fake.calls_to("cancel_normal_order") == [], "attach cancelled an order"


def placed_ids(rig: ProtectionRig) -> list[str]:
    return [c["kwargs"]["client_algo_id"] for c in rig.fake.calls_to("place_algo_protective")]


def row(rig: ProtectionRig, role: str) -> Any:
    return rig.inner_store.get_intent(approval_id=rig.entry.approval_id, role=role)


def assert_held(rig: ProtectionRig, outcome: AttachOutcome) -> None:
    """The ENTRY_WITHOUT_PROTECTIVE hold: NO_TRADE reason and SAFE_MODE entered exactly once."""
    assert outcome.is_no_trade is True
    assert outcome.reason_code == HOLD
    assert rig.safe_mode.entered_reasons == [HOLD]


# --------------------------------------------------------------------------- #
# Tracer: attach adopts the REST-confirmed stop and places TP1 and TP2 from the real position.
# --------------------------------------------------------------------------- #


async def test_tracer_attach_adopts_the_confirmed_stop_and_places_tp1_and_tp2() -> None:
    rig = await protected_rig()
    statuses_at_placement: list[tuple[str, ExecutionIntentStatus | None]] = []
    wrapped = rig.fake.place_algo_protective

    async def spy(**kwargs: Any) -> Any:
        role = "TAKE_PROFIT_1" if kwargs["client_algo_id"] == TP1_ID else "TAKE_PROFIT_2"
        stored = row(rig, role)
        statuses_at_placement.append((role, None if stored is None else stored.intent_status))
        return await wrapped(**kwargs)

    rig.fake.place_algo_protective = spy  # type: ignore[method-assign]

    outcome = await run_attach(rig)

    assert (outcome.is_no_trade, outcome.reason_code) == (False, "OK")
    assert outcome.placed_legs == ALL_THREE
    assert rig.safe_mode.entered_reasons == []
    # Each take profit was written ahead and SENT before its placement started.
    assert statuses_at_placement == [
        ("TAKE_PROFIT_1", ExecutionIntentStatus.SENT),
        ("TAKE_PROFIT_2", ExecutionIntentStatus.SENT),
    ]
    assert rig.log == [
        "store.record_protective_intent:TAKE_PROFIT_1",
        "store.mark_sent:TAKE_PROFIT_1",
        "adapter.place_algo_protective",
        "store.record_result:TAKE_PROFIT_1",
        "store.record_protective_intent:TAKE_PROFIT_2",
        "store.mark_sent:TAKE_PROFIT_2",
        "adapter.place_algo_protective",
        "store.record_result:TAKE_PROFIT_2",
    ]
    assert placed_ids(rig) == [TP1_ID, TP2_ID]
    tp1_call, tp2_call = (c["kwargs"] for c in rig.fake.calls_to("place_algo_protective"))
    assert tp1_call == {
        "symbol": "BTCUSDT",
        "client_algo_id": TP1_ID,
        "side": "SELL",
        "position_side": "BOTH",
        "algo_type": "CONDITIONAL",
        "type": "TAKE_PROFIT_MARKET",
        "trigger_price": Decimal("62000.00"),
        "close_position": False,
        "quantity": Decimal("0.005"),
        "reduce_only": True,
        "working_type": "MARK_PRICE",
    }
    assert str(tp1_call["quantity"]) == "0.005"
    assert str(tp1_call["trigger_price"]) == "62000.00"
    assert tp2_call == {
        "symbol": "BTCUSDT",
        "client_algo_id": TP2_ID,
        "side": "SELL",
        "position_side": "BOTH",
        "algo_type": "CONDITIONAL",
        "type": "TAKE_PROFIT_MARKET",
        "trigger_price": Decimal("64000.00"),
        "close_position": True,
        "quantity": None,
        "reduce_only": None,
        "working_type": "MARK_PRICE",
    }
    tp1_row, tp2_row = row(rig, "TAKE_PROFIT_1"), row(rig, "TAKE_PROFIT_2")
    assert (tp1_row.intent_status, tp1_row.intended_quantity) == (
        ExecutionIntentStatus.ACKED,
        Decimal("0.005"),
    )
    assert (tp2_row.intent_status, tp2_row.intended_quantity) == (
        ExecutionIntentStatus.ACKED,
        None,
    )
    assert (tp1_row.intended_price, tp2_row.intended_price) == (
        Decimal("62000.00"),
        Decimal("64000.00"),
    )
    assert row(rig, "STOP_LOSS") is None, "attach wrote a stop intent"
    # The three legs are open on the exchange, the stop untouched.
    assert set(rig.fake.open_algos) == {STOP_ID, TP1_ID, TP2_ID}


def test_attach_signature_has_no_symbol_side_plan_hash_or_snapshot_parameter() -> None:
    parameters = inspect.signature(attach_protectives_to_fill).parameters
    assert list(parameters) == [
        "entry",
        "position_quantity",
        "live_lot_filters",
        "adapter",
        "intent_store",
        "now_utc",
        "safe_mode_controller",
    ]
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in parameters.values())
    for forbidden in (
        "symbol",
        "side",
        "candidate_position_side",
        "plan_hash",
        "constraint_snapshot",
        "fill_events",
        "protective_template",
    ):
        assert forbidden not in parameters


# --------------------------------------------------------------------------- #
# D-01: the entry must agree with its own snapshot and filters.
# --------------------------------------------------------------------------- #


async def test_entry_snapshot_for_another_symbol_is_refused_before_any_adapter_call() -> None:
    rig = await protected_rig(
        plan_constraint_snapshot=complete_constraint_snapshot(symbol="ETHUSDT")
    )
    outcome = await run_attach(rig)
    assert outcome.is_no_trade is True
    assert outcome.reason_code == "PLAN_SYMBOL_MISMATCH"
    assert outcome.placed_legs == ()
    assert rig.fake.calls == []
    assert rig.log == []
    assert rig.safe_mode.entered_reasons == [HOLD]


async def test_entry_snapshot_for_another_trade_plan_is_refused_before_any_adapter_call() -> None:
    rig = await protected_rig(
        plan_constraint_snapshot=complete_constraint_snapshot(trade_plan_id="another-plan")
    )
    outcome = await run_attach(rig)
    assert (outcome.is_no_trade, outcome.reason_code) == (True, "PLAN_SYMBOL_MISMATCH")
    assert rig.fake.calls == []
    assert rig.log == []
    assert rig.safe_mode.entered_reasons == [HOLD]


async def test_live_filters_for_another_symbol_are_refused_before_any_adapter_call() -> None:
    rig = await protected_rig()
    other = dataclasses.replace(lot_filters_for_tests(), symbol="ETHUSDT")
    outcome = await run_attach(rig, live_lot_filters=other, now_utc=STALE_NOW)
    assert (outcome.is_no_trade, outcome.reason_code) == (True, "PLAN_SYMBOL_MISMATCH")
    assert rig.fake.calls == []
    assert rig.log == []
    assert rig.safe_mode.entered_reasons == [HOLD]


async def test_non_live5_symbol_raises_before_any_adapter_call() -> None:
    rig = await make_rig(
        register=False,
        place_entry=False,
        symbol="DOGEUSDT",
        plan_constraint_snapshot=complete_constraint_snapshot(symbol="DOGEUSDT"),
    )
    with pytest.raises(ValueError, match="live-5"):
        await run_attach(rig)
    assert rig.fake.calls == []
    assert rig.log == []


async def test_missing_safe_mode_controller_raises_before_any_adapter_call() -> None:
    rig = await protected_rig()
    with pytest.raises(ValueError, match="safe_mode_controller is required"):
        await run_attach(rig, safe_mode=None)
    assert rig.fake.calls == []


async def test_hedge_mode_is_not_supported_and_holds_before_any_adapter_call() -> None:
    rig = await protected_rig(position_mode="HEDGE")
    outcome = await run_attach(rig)
    assert_held(rig, outcome)
    assert outcome.failure_detail == "position mode HEDGE is not supported"
    assert rig.fake.calls == []


# --------------------------------------------------------------------------- #
# D-11 / D-17: the stop must be ACTIVE by REST; attach never places one.
# --------------------------------------------------------------------------- #

_SEVEN_ALGO_STATUSES = (
    "NEW",
    "TRIGGERING",
    "TRIGGERED",
    "FINISHED",
    "CANCELED",
    "REJECTED",
    "EXPIRED",
)


@pytest.mark.parametrize("status", _SEVEN_ALGO_STATUSES)
async def test_existing_stop_adoption_follows_the_status_table(status: str) -> None:
    """The stop is adopted exactly when `is_protection_confirmed(status)`; otherwise attach holds
    ENTRY_WITHOUT_PROTECTIVE, places no take profit and writes no row (derived from the table)."""
    rig = await protected_rig()
    script_algo_status(rig.fake, STOP_ID, status)

    outcome = await run_attach(rig)

    if is_protection_confirmed(status):
        assert outcome.is_no_trade is False, outcome
        assert outcome.placed_legs == ALL_THREE
        assert placed_ids(rig) == [TP1_ID, TP2_ID]
        assert rig.safe_mode.entered_reasons == []
    else:
        assert_held(rig, outcome)
        assert outcome.failure_detail == f"STOP_LOSS: existing leg status {status!r}"
        assert outcome.placed_legs == ()
        assert placed_ids(rig) == []
        assert rig.log == []
        assert row(rig, "TAKE_PROFIT_1") is None


async def test_absent_stop_holds_without_placing_a_stop_or_a_take_profit() -> None:
    rig = await protected_rig(stop=False)
    outcome = await run_attach(rig)
    assert_held(rig, outcome)
    assert outcome.failure_detail == "STOP_LOSS: not found"
    assert outcome.placed_legs == ()
    assert rig.fake.calls_to("place_algo_protective") == []
    assert rig.log == []


async def test_stop_probe_failure_fails_closed_without_placement() -> None:
    rig = await protected_rig()
    rig.fake.fail_next("query_algo_order_by_client", TimeoutError("probe timeout"))
    outcome = await run_attach(rig)
    assert_held(rig, outcome)
    assert outcome.failure_detail == "STOP_LOSS: probe TimeoutError"
    assert rig.fake.calls_to("place_algo_protective") == []
    assert rig.log == []


async def test_unreadable_stop_answer_fails_closed() -> None:
    rig = await protected_rig()
    original = rig.fake.query_algo_order_by_client

    async def odd(**kwargs: Any) -> Any:
        if kwargs["client_algo_id"] == STOP_ID:
            return object()  # neither found=True nor found=False
        return await original(**kwargs)

    rig.fake.query_algo_order_by_client = odd  # type: ignore[method-assign]
    outcome = await run_attach(rig)
    assert_held(rig, outcome)
    assert outcome.failure_detail == "STOP_LOSS: probe outcome unknown"
    assert placed_ids(rig) == []


# --------------------------------------------------------------------------- #
# A rejected or unconfirmed take-profit leg is the CR-03 branch: the stop is kept.
# --------------------------------------------------------------------------- #


async def test_rejected_tp1_holds_entry_without_protective_and_keeps_the_stop() -> None:
    rig = await protected_rig()
    rig.fake.reject_next_algo(-4016, "price too far")

    outcome = await run_attach(rig)

    assert_held(rig, outcome)
    assert outcome.placed_legs == ("STOP_LOSS",)
    assert outcome.failure_detail == "TAKE_PROFIT_1: BadRequestError"  # never the message text
    assert rig.fake.calls_to("place_algo_protective")[0]["kwargs"]["client_algo_id"] == TP1_ID
    assert len(rig.fake.calls_to("place_algo_protective")) == 1, "TP2 attempted after TP1 failed"
    assert row(rig, "TAKE_PROFIT_1").intent_status is ExecutionIntentStatus.REJECTED
    assert row(rig, "TAKE_PROFIT_2") is None
    assert STOP_ID in rig.fake.open_algos


async def test_ambiguous_tp1_failure_leaves_the_intent_unknown() -> None:
    rig = await protected_rig()
    rig.fake.fail_next("place_algo_protective", TimeoutError("simulated read timeout"))

    outcome = await run_attach(rig)

    assert_held(rig, outcome)
    assert outcome.placed_legs == ("STOP_LOSS",)
    assert outcome.failure_detail == "TAKE_PROFIT_1: TimeoutError"
    assert row(rig, "TAKE_PROFIT_1").intent_status is ExecutionIntentStatus.UNKNOWN
    assert STOP_ID in rig.fake.open_algos


async def test_refused_before_send_tp1_is_rejected_and_the_stop_is_kept() -> None:
    from src.domain.exchange_errors import PreSendRefusal

    rig = await protected_rig()
    rig.fake.fail_next("place_algo_protective", PreSendRefusal("paused"))

    outcome = await run_attach(rig)

    assert_held(rig, outcome)
    assert outcome.failure_detail == "TAKE_PROFIT_1: PreSendRefusal"
    assert row(rig, "TAKE_PROFIT_1").intent_status is ExecutionIntentStatus.REJECTED


async def test_rejected_tp2_keeps_tp1_and_the_stop_in_place() -> None:
    rig = await protected_rig()
    original = rig.fake.place_algo_protective

    async def reject_tp2(**kwargs: Any) -> Any:
        if kwargs["client_algo_id"] == TP2_ID:
            rig.fake.reject_next_algo(-4016, "price too far")
        return await original(**kwargs)

    rig.fake.place_algo_protective = reject_tp2  # type: ignore[method-assign]

    outcome = await run_attach(rig)

    assert_held(rig, outcome)
    assert outcome.placed_legs == ("STOP_LOSS", "TAKE_PROFIT_1")
    assert outcome.failure_detail == "TAKE_PROFIT_2: BadRequestError"
    assert row(rig, "TAKE_PROFIT_1").intent_status is ExecutionIntentStatus.ACKED
    assert row(rig, "TAKE_PROFIT_2").intent_status is ExecutionIntentStatus.REJECTED
    assert {STOP_ID, TP1_ID} <= set(rig.fake.open_algos)


async def test_a_placed_leg_that_rest_does_not_show_active_is_unconfirmed() -> None:
    rig = await protected_rig()
    original = rig.fake.query_algo_order_by_client
    calls_for_tp1 = 0

    async def lose_tp1_after_placement(**kwargs: Any) -> Any:
        nonlocal calls_for_tp1
        if kwargs["client_algo_id"] == TP1_ID:
            calls_for_tp1 += 1
            if calls_for_tp1 >= 2:  # the confirmation query, after the placement
                return AlgoOrderProbe(
                    client_algo_id=TP1_ID, found=False, algo_status=None, update_time_utc=None
                )
        return await original(**kwargs)

    rig.fake.query_algo_order_by_client = lose_tp1_after_placement  # type: ignore[method-assign]

    outcome = await run_attach(rig)

    assert_held(rig, outcome)
    assert outcome.placed_legs == ("STOP_LOSS",)
    assert outcome.failure_detail == "TAKE_PROFIT_1: not confirmed by REST"
    assert row(rig, "TAKE_PROFIT_1").intent_status is ExecutionIntentStatus.UNKNOWN
    assert len(rig.fake.calls_to("place_algo_protective")) == 1


async def test_a_failing_confirmation_query_is_unconfirmed() -> None:
    rig = await protected_rig()
    original = rig.fake.query_algo_order_by_client
    calls_for_tp1 = 0

    async def fail_confirmation(**kwargs: Any) -> Any:
        nonlocal calls_for_tp1
        if kwargs["client_algo_id"] == TP1_ID:
            calls_for_tp1 += 1
            if calls_for_tp1 >= 2:
                raise TimeoutError("confirmation timeout")
        return await original(**kwargs)

    rig.fake.query_algo_order_by_client = fail_confirmation  # type: ignore[method-assign]

    outcome = await run_attach(rig)

    assert_held(rig, outcome)
    assert outcome.failure_detail == "TAKE_PROFIT_1: confirm probe TimeoutError"
    assert row(rig, "TAKE_PROFIT_1").intent_status is ExecutionIntentStatus.UNKNOWN


def _placement_result(status: str) -> AlgoPlacementResult:
    return AlgoPlacementResult(
        symbol="BTCUSDT",
        client_algo_id=TP1_ID,
        algo_id="1",
        algo_type="CONDITIONAL",
        order_type="TAKE_PROFIT_MARKET",
        side="SELL",
        position_side="BOTH",
        algo_status=status,
        trigger_price=Decimal("62000.00"),
        close_position=False,
        working_type="MARK_PRICE",
        update_time_utc=TEST_ONLY_REGISTERED_AT,
    )


@pytest.mark.parametrize(
    ("status", "confirmed"),
    [
        ("NEW", True),
        ("REJECTED", False),
        ("EXPIRED", False),
        ("CANCELED", False),
        ("TRIGGERED", False),
        ("", False),
    ],
)
def test_leg_confirmation_reads_the_real_dataclass_with_the_allow_list(
    status: str, confirmed: bool
) -> None:
    """WR-03: the placement response is read as the REAL dataclass or a dict (class ACTIVE only)."""
    from src.execution.manager import _is_leg_confirmed

    assert _is_leg_confirmed(_placement_result(status)) is confirmed
    assert _is_leg_confirmed({"algo_status": status}) is confirmed


async def test_a_rejected_placement_response_for_tp1_is_unconfirmed_even_if_rest_shows_it() -> None:
    """The response must confirm AND a REST query must answer ACTIVE: either failing holds."""
    rig = await protected_rig()
    original = rig.fake.place_algo_protective

    async def rejected_response(**kwargs: Any) -> Any:
        await original(**kwargs)  # the leg is open on the fake, the response says REJECTED
        return _placement_result("REJECTED")

    rig.fake.place_algo_protective = rejected_response  # type: ignore[method-assign]

    outcome = await run_attach(rig)

    assert_held(rig, outcome)
    assert outcome.placed_legs == ("STOP_LOSS",)
    assert outcome.failure_detail == "TAKE_PROFIT_1: not confirmed"
    assert row(rig, "TAKE_PROFIT_1").intent_status is ExecutionIntentStatus.UNKNOWN
    assert len(rig.fake.calls_to("place_algo_protective")) == 1


# --------------------------------------------------------------------------- #
# Idempotence: query-first by the deterministic id, never a duplicate.
# --------------------------------------------------------------------------- #


async def test_a_second_attach_for_the_same_plan_places_nothing_new() -> None:
    rig = await protected_rig()
    first = await run_attach(rig)
    assert first.is_no_trade is False
    assert placed_ids(rig) == [TP1_ID, TP2_ID]

    second = await run_attach(rig)

    assert (second.is_no_trade, second.reason_code) == (False, "OK"), second
    assert second.placed_legs == ALL_THREE
    assert placed_ids(rig) == [TP1_ID, TP2_ID], "a second attach duplicated a leg"
    assert rig.safe_mode.entered_reasons == []


async def test_an_existing_non_active_tp1_is_never_re_placed() -> None:
    rig = await protected_rig()
    script_algo_status(rig.fake, TP1_ID, "CANCELED")

    outcome = await run_attach(rig)

    assert_held(rig, outcome)
    assert outcome.failure_detail == "TAKE_PROFIT_1: existing leg status 'CANCELED'"
    assert placed_ids(rig) == []
    assert outcome.placed_legs == ("STOP_LOSS",)
    assert row(rig, "TAKE_PROFIT_1").intent_status is ExecutionIntentStatus.UNKNOWN
    assert STOP_ID in rig.fake.open_algos


# --------------------------------------------------------------------------- #
# D-18 / D-19: sizing from the real position; un-sizeable TP1 is the CR-03 branch.
# --------------------------------------------------------------------------- #


async def test_tp1_below_the_minimum_quantity_holds_and_keeps_the_stop() -> None:
    rig = await protected_rig(filled=Decimal("0.001"))
    outcome = await run_attach(rig, position_quantity=Decimal("0.001"))
    assert_held(rig, outcome)
    assert outcome.sized is not None and outcome.sized.reason_code == "MIN_QTY_REJECT"
    assert outcome.failure_detail == "TAKE_PROFIT_1 sizing: MIN_QTY_REJECT"
    assert outcome.placed_legs == ("STOP_LOSS",)
    assert placed_ids(rig) == []
    assert rig.log == []  # nothing written ahead for a leg that is never sent


async def test_tp1_below_the_minimum_notional_holds_and_keeps_the_stop() -> None:
    rig = await protected_rig(filled=Decimal("0.002"))
    outcome = await run_attach(rig, position_quantity=Decimal("0.002"))
    assert_held(rig, outcome)
    assert outcome.sized is not None and outcome.sized.reason_code == "NOTIONAL_REJECT"
    assert outcome.failure_detail == "TAKE_PROFIT_1 sizing: NOTIONAL_REJECT"
    assert placed_ids(rig) == []


async def test_tp1_is_sized_from_the_position_quantity_argument_not_the_planned_quantity() -> None:
    """The planned entry quantity is 0.010; a partially filled entry leaves 0.004 (REST)."""
    rig = await protected_rig(filled=Decimal("0.004"))
    outcome = await run_attach(rig, position_quantity=Decimal("0.004"))
    assert outcome.is_no_trade is False, outcome
    tp1 = rig.fake.calls_to("place_algo_protective")[0]["kwargs"]
    assert tp1["quantity"] == Decimal("0.002")


@pytest.mark.parametrize("quantity", [Decimal("0"), Decimal("-0.010")])
async def test_a_flat_or_negative_position_quantity_is_no_fill(quantity: Decimal) -> None:
    rig = await protected_rig()
    outcome = await run_attach(rig, position_quantity=quantity)
    assert (outcome.is_no_trade, outcome.reason_code) == (True, "NO_FILL")
    assert rig.fake.calls == []
    assert rig.safe_mode.entered_reasons == []


async def test_a_non_decimal_position_quantity_is_a_type_error() -> None:
    rig = await protected_rig()
    with pytest.raises(TypeError, match="position_quantity"):
        await run_attach(rig, position_quantity=0.01)  # type: ignore[arg-type]
    assert rig.fake.calls == []


# --------------------------------------------------------------------------- #
# D-20 / G4-038: the plan snapshot must be valid for live; stale is re-sized, incomplete refused.
# --------------------------------------------------------------------------- #


def _live_filters_with_a_coarser_step() -> LotFilters:
    return dataclasses.replace(
        lot_filters_for_tests(),
        lot_min_quantity=Decimal("0.002"),
        lot_step_size=Decimal("0.002"),
        market_lot_min_quantity=Decimal("0.002"),
        market_lot_step_size=Decimal("0.002"),
    )


async def test_a_stale_but_complete_snapshot_is_re_sized_with_the_live_filters() -> None:
    rig = await protected_rig()
    outcome = await run_attach(
        rig, now_utc=STALE_NOW, live_lot_filters=_live_filters_with_a_coarser_step()
    )
    assert (outcome.is_no_trade, outcome.reason_code) == (False, "OK"), outcome
    tp1 = rig.fake.calls_to("place_algo_protective")[0]["kwargs"]
    # 0.005 floored onto the live 0.002 grid, not the snapshot's 0.001 grid (which gives 0.005).
    assert tp1["quantity"] == Decimal("0.004")
    assert row(rig, "TAKE_PROFIT_1").intended_quantity == Decimal("0.004")


async def test_a_stale_but_complete_snapshot_without_live_filters_is_refused() -> None:
    rig = await protected_rig()
    outcome = await run_attach(rig, now_utc=STALE_NOW, live_lot_filters=None)
    assert_held(rig, outcome)
    assert outcome.failure_detail == "plan snapshot is stale and no live filters were read"
    assert placed_ids(rig) == []
    assert rig.log == []


async def test_a_future_dated_snapshot_is_treated_as_stale() -> None:
    rig = await protected_rig()
    before_capture = TEST_ONLY_REGISTERED_AT - timedelta(minutes=5)
    outcome = await run_attach(rig, now_utc=before_capture, live_lot_filters=None)
    assert_held(rig, outcome)
    assert placed_ids(rig) == []


@pytest.mark.parametrize(
    "unknown",
    ["margin_type", "leverage", "equity_used", "max_quantity", "market_lot_step_size"],
)
async def test_an_incomplete_snapshot_is_refused_even_with_live_filters(unknown: str) -> None:
    """The consequence recorded for the owner: with real data (margin type, leverage and equity
    unknown until Phases 21-22) every TP placement is refused into the CR-03 hold."""
    rig = await protected_rig(
        plan_constraint_snapshot=complete_constraint_snapshot(**{unknown: None})
    )
    outcome = await run_attach(rig, live_lot_filters=lot_filters_for_tests())
    assert_held(rig, outcome)
    assert outcome.failure_detail == "plan snapshot is INCOMPLETE and not valid for live"
    assert outcome.placed_legs == ("STOP_LOSS",)
    assert placed_ids(rig) == []
    assert rig.log == []
    assert STOP_ID in rig.fake.open_algos


# --------------------------------------------------------------------------- #
# Write-ahead store failures (D034: protection outranks the audit row).
# --------------------------------------------------------------------------- #


async def test_a_failing_intent_write_places_no_take_profit_and_holds() -> None:
    rig = await protected_rig()
    store = FailingIntentStore(
        "record_protective_intent",
        StoreUnavailable("down"),
        inner=rig.inner_store,
        role="TAKE_PROFIT_1",
    )

    outcome = await run_attach(rig, store=store)

    assert_held(rig, outcome)
    assert outcome.failure_detail == "TAKE_PROFIT_1: intent store StoreUnavailable"
    assert placed_ids(rig) == [], "a take profit was sent without a durable intent"


async def test_a_failing_result_write_after_the_placement_keeps_the_confirmed_leg() -> None:
    rig = await protected_rig()
    store = FailingIntentStore(
        "record_result", StoreUnavailable("down"), inner=rig.inner_store, role="TAKE_PROFIT_1"
    )

    outcome = await run_attach(rig, store=store)

    assert (outcome.is_no_trade, outcome.reason_code) == (False, "OK"), outcome
    assert outcome.placed_legs == ALL_THREE
    assert rig.safe_mode.entered_reasons == ["DB_FAILURE"]
    assert placed_ids(rig) == [TP1_ID, TP2_ID]


# --------------------------------------------------------------------------- #
# Purity: no float() and no Binance SDK import in manager.py.
# --------------------------------------------------------------------------- #


def test_manager_module_has_no_float() -> None:
    module_path = Path(__file__).resolve().parents[1] / "src" / "execution" / "manager.py"
    source = module_path.read_text(encoding="utf-8")
    match = re.search(r"\bfloat\s*\(", source)
    assert match is None, f"float() found in {module_path}: {match.group(0)!r}"


def test_manager_module_does_not_import_binance_sdk() -> None:
    module_path = Path(__file__).resolve().parents[1] / "src" / "execution" / "manager.py"
    source = module_path.read_text(encoding="utf-8")
    for pattern in (r"\bimport\s+binance_sdk\b", r"\bfrom\s+binance_sdk\b"):
        match = re.search(pattern, source)
        assert match is None, f"forbidden import in {module_path}: {match.group(0)!r}"


def test_attach_docstring_states_d034_supersedes_d02() -> None:
    """D-17: the docstring no longer claims 'no rescue placement is ever issued (D-02)'."""
    doc = inspect.getdoc(attach_protectives_to_fill) or ""
    assert "no rescue placement is ever issued" not in doc
    assert "D034" in doc
    assert "emergency_close" in doc
    assert "emergency_manual_close" in doc


def test_resting_entry_helper_matches_the_tracer_ids() -> None:
    """Guards the derived ids this file relies on against a change of the helper's plan hash."""
    entry = resting_entry_for_tests()
    assert entry.plan_hash == TEST_ONLY_PLAN_HASH
    assert entry.symbol == TEST_ONLY_SYMBOL
