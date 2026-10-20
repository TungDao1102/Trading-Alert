"""The fill-driven protection coordinator (plan 19-11; D-10, D-11, D-12, D-13, D-14).

The coordinator is step-driven: the tests inject virtual time, the stateful Phase 19 fake
exchange (constructed with `enforce_flat_stop_rejection=True`, so a closePosition stop placed
while flat is rejected the way Demo did), an in-memory intent store behind an event log and a
recording journal. Nothing sleeps and nothing touches a network. A green test proves agreement
with the fake's labelled rules (tests/support/fake_binance_exchange.py), not with mainnet.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest
from src.domain.enums import ExecutionIntentStatus
from src.domain.journal import correlated_event_id
from src.execution.execution_limits import ExecutionLimitsNotConfigured
from src.execution.order_ids import derive_algo_client_id
from src.execution.protection import (
    ProtectionCoordinator,
    ProtectionState,
)

from tests.support.execution_limits import test_only_execution_limits as limits_with
from tests.support.protection_doubles import (
    TEST_ONLY_PLAN_HASH,
    TEST_ONLY_SYMBOL,
    ProtectionRig,
    make_rig,
    resting_entry_for_tests,
)
from tests.support.virtual_time import TEST_ONLY_VIRTUAL_START

D = Decimal

STATE_NAMES = {
    "AWAITING_FILL",
    "UNPROTECTED",
    "PROTECTED_ENTRY_OPEN",
    "PROTECTED",
    "COMPLETE",
    "TP_UNAVAILABLE",
    "CLOSE_REQUIRED",
    "FLAT",
    "CLOSE_FAILED",
    "ENTRY_ENDED_NO_FILL",
    # 19-REVIEW WR-05 (owner): an ENTRY_STATE_UNKNOWN entry never found by GTD + grace.
    "ENTRY_UNRESOLVED",
}


# --------------------------------------------------------------------------- #
# Vocabulary and construction (D-13, D-14).
# --------------------------------------------------------------------------- #


def test_protection_state_names_are_the_eleven_stable_names() -> None:
    assert {member.name for member in ProtectionState} == STATE_NAMES
    assert all(member.value == member.name for member in ProtectionState)


@pytest.mark.parametrize(
    "unset",
    [
        "max_unprotected_ms",
        "entry_terminal_timeout_ms",
        "entry_unknown_grace_ms",
        "min_remaining_validity_seconds",
        "max_mark_price_age_ms",
    ],
)
def test_constructor_refuses_while_any_limit_is_not_configured(unset: str) -> None:
    with pytest.raises(ExecutionLimitsNotConfigured) as excinfo:
        ProtectionCoordinator(
            adapter=None,  # type: ignore[arg-type]
            intent_store=None,  # type: ignore[arg-type]
            journal=None,
            safe_mode_controller=None,
            alert_sink=None,  # type: ignore[arg-type]
            emergency_closer=None,  # type: ignore[arg-type]
            limits=limits_with(**{unset: None}),
            clock=None,  # type: ignore[arg-type]
        )
    assert unset in str(excinfo.value)


async def test_registering_puts_the_plan_in_awaiting_fill_and_does_not_block() -> None:
    rig = await make_rig()
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.AWAITING_FILL
    assert protection.symbol == TEST_ONLY_SYMBOL
    assert protection.first_fill_at_utc is None
    assert rig.coordinator.blocks_new_entries() is False
    assert rig.coordinator.protection_of("f" * 64) is None


async def test_hedge_mode_entry_is_refused_at_registration() -> None:
    rig = await make_rig(register=False)
    with pytest.raises(ValueError, match="HEDGE"):
        rig.coordinator.register_resting_entry(resting_entry_for_tests(position_mode="HEDGE"))
    assert rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH) is None


async def test_duplicate_plan_hash_is_refused() -> None:
    rig = await make_rig()
    with pytest.raises(ValueError, match="already registered"):
        rig.coordinator.register_resting_entry(rig.entry)


# --------------------------------------------------------------------------- #
# The tracer: first stream fill -> stop and remainder cancel -> REST confirmation.
# --------------------------------------------------------------------------- #


async def test_first_stream_fill_starts_the_stop_and_the_cancel_then_rest_confirms() -> None:
    rig = await make_rig()
    first_step_at = rig.clock.now()

    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()

    # The durable unprotected-since time: the STOP_LOSS intent was written INTENDED at the step,
    # then SENT, before the placement ran.
    stop_row = rig.stop_row()
    assert stop_row is not None
    assert stop_row.intended_at_utc == first_step_at
    assert stop_row.intent_status is ExecutionIntentStatus.SENT
    assert stop_row.intended_quantity is None
    assert stop_row.intended_price == rig.entry.sl_trigger_price
    assert stop_row.algo_client_id == rig.stop_id
    order = [line for line in rig.log if not line.startswith("adapter.cancel")]
    assert order[:3] == [
        "store.record_protective_intent:STOP_LOSS",
        "store.mark_sent:STOP_LOSS",
        "adapter.place_algo_protective",
    ]
    assert "adapter.cancel_normal_order" in rig.log

    # The stop payload, key by key (D-10): closePosition, no quantity, no reduceOnly,
    # the snapped plan trigger and the plan snapshot's working type.
    placements = rig.fake.calls_to("place_algo_protective")
    assert len(placements) == 1
    kwargs = placements[0]["kwargs"]
    assert kwargs == {
        "symbol": TEST_ONLY_SYMBOL,
        "side": "SELL",
        "algo_type": "CONDITIONAL",
        "type": "STOP_MARKET",
        "position_side": "BOTH",
        "trigger_price": rig.entry.sl_trigger_price,
        "close_position": True,
        "quantity": None,
        "working_type": rig.entry.working_type,
        "client_algo_id": rig.stop_id,
    }
    assert kwargs.get("reduce_only") is None

    # One cancel of the entry remainder, by the deterministic entry id.
    cancels = rig.fake.calls_to("cancel_normal_order")
    assert len(cancels) == 1
    assert cancels[0]["kwargs"] == {
        "symbol": TEST_ONLY_SYMBOL,
        "orig_client_order_id": rig.entry_id,
    }

    # A NEW placement response is not protection (D-11): unprotected, entries blocked.
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.UNPROTECTED
    assert protection.first_fill_at_utc == first_step_at
    assert protection.stop_confirmed_at_utc is None
    assert rig.coordinator.blocks_new_entries() is True

    # The next step reads the stop (NEW -> ACTIVE) and the entry (CANCELED, 0.004 executed).
    await rig.clock.advance(1)
    confirmed_at = rig.clock.now()
    await rig.coordinator.step()

    stop_row = rig.stop_row()
    assert stop_row is not None
    assert stop_row.intent_status is ExecutionIntentStatus.ACKED
    assert stop_row.exchange_status == "NEW"
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.PROTECTED
    assert protection.stop_confirmed_at_utc == confirmed_at
    assert protection.entry_terminal_at_utc == confirmed_at
    assert rig.coordinator.blocks_new_entries() is False
    assert rig.safe_mode.entered_reasons == []
    assert rig.alerts.alerts == []
    assert len(rig.fake.calls_to("place_algo_protective")) == 1

    # One PROTECTION_TRANSITION per transition, with deterministic ids.
    assert rig.transitions() == [
        ("NONE", "AWAITING_FILL"),
        ("AWAITING_FILL", "UNPROTECTED"),
        ("UNPROTECTED", "PROTECTED"),
    ]
    ids = [e.journal_event_id for e in rig.journal.by_type("PROTECTION_TRANSITION")]
    assert len(set(ids)) == 3
    assert ids[1] == correlated_event_id(
        prefix="ptr",
        correlation_id=f"protection_{TEST_ONLY_PLAN_HASH}",
        event_type="PROTECTION_TRANSITION",
        entity_id=TEST_ONLY_PLAN_HASH,
        step="2:AWAITING_FILL->UNPROTECTED",
    )


async def test_transition_journal_ids_are_the_same_in_a_replayed_scenario() -> None:
    async def run() -> list[str]:
        rig = await make_rig()
        rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
        await rig.coordinator.step()
        await rig.clock.advance(1)
        await rig.coordinator.step()
        return [e.journal_event_id for e in rig.journal.by_type("PROTECTION_TRANSITION")]

    assert await run() == await run()


async def test_a_stop_that_is_not_active_on_rest_never_counts_as_protected() -> None:
    rig = await make_rig()
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()
    # ALGO_UPDATE-style statuses are not protection: the exchange moves the stop to FINISHED.
    rig.fake.trigger_stop(rig.stop_id)

    await rig.coordinator.step()

    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.UNPROTECTED
    assert rig.coordinator.blocks_new_entries() is True
    stop_row = rig.stop_row()
    assert stop_row is not None
    assert stop_row.intent_status is not ExecutionIntentStatus.ACKED


async def test_entry_still_open_after_the_stop_is_confirmed_is_protected_entry_open() -> None:
    rig = await make_rig()
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    # The cancel is held, so the remainder stays open at the exchange after the stop is placed.
    rig.fake.hold("cancel_normal_order")
    stepping = asyncio.create_task(rig.coordinator.step())
    await rig.clock.settle()
    assert "place_algo_protective" in rig.fake.completed
    assert "cancel_normal_order" not in rig.fake.completed
    rig.fake.release("cancel_normal_order")
    await stepping
    # Roll the entry back to open to model a cancel that has not taken effect yet.
    record = rig.fake.history.pop(rig.entry_id)
    record.status = "PARTIALLY_FILLED"
    rig.fake.open_orders[rig.entry_id] = record

    await rig.coordinator.step()

    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.PROTECTED_ENTRY_OPEN
    assert protection.stop_confirmed_at_utc is not None
    assert protection.entry_terminal_at_utc is None
    assert rig.coordinator.blocks_new_entries() is False


async def test_a_store_failure_never_stops_the_stop_and_enters_safe_mode_once() -> None:
    from src.persistence.errors import PersistenceError

    rig = await make_rig()

    def broken(**_kwargs: object) -> bool:
        raise PersistenceError("TEST_ONLY store failure")

    rig.inner_store.record_protective_intent = broken  # type: ignore[method-assign, assignment]
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()

    assert len(rig.fake.calls_to("place_algo_protective")) == 1
    assert rig.safe_mode.entered_reasons == ["DB_FAILURE"]
    await rig.clock.advance(1)
    await rig.coordinator.step()
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.PROTECTED
    assert rig.safe_mode.entered_reasons == ["DB_FAILURE"]


async def test_an_existing_active_stop_is_adopted_not_duplicated() -> None:
    rig = await make_rig()
    routed = rig.stream_fill(D("0.004"))
    await rig.fake.place_algo_protective(
        symbol=TEST_ONLY_SYMBOL,
        side="SELL",
        algo_type="CONDITIONAL",
        type="STOP_MARKET",
        position_side="BOTH",
        trigger_price=rig.entry.sl_trigger_price,
        close_position=True,
        quantity=None,
        working_type="MARK_PRICE",
        client_algo_id=derive_algo_client_id(plan_hash=TEST_ONLY_PLAN_HASH, role="STOP_LOSS"),
    )
    rig.fake.calls.clear()

    rig.coordinator.fill_sink(routed)
    await rig.coordinator.step()
    await rig.coordinator.step()

    assert rig.fake.calls_to("place_algo_protective") == []
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.PROTECTED


# --------------------------------------------------------------------------- #
# Task 2: REST-only fill detection, zero-fill terminal, duplicates, concurrency.
# --------------------------------------------------------------------------- #


def _stop_and_cancel_calls(rig: ProtectionRig) -> tuple[list[Any], list[Any]]:
    placements = rig.fake.calls_to("place_algo_protective")
    cancels = rig.fake.calls_to("cancel_normal_order")
    return ([c["kwargs"] for c in placements], [c["kwargs"] for c in cancels])


async def test_rest_only_fill_gives_the_same_outcome_as_a_stream_fill() -> None:
    stream = await make_rig()
    stream.coordinator.fill_sink(stream.stream_fill(D("0.004")))
    await stream.coordinator.step()
    await stream.coordinator.step()

    rest = await make_rig()
    rest.fake.fill(rest.entry_id, quantity=D("0.004"))  # no stream event reaches the sink
    await rest.coordinator.step()
    protection = rest.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.UNPROTECTED
    assert rest.coordinator.blocks_new_entries() is True
    await rest.coordinator.step()

    assert _stop_and_cancel_calls(rest) == _stop_and_cancel_calls(stream)
    for rig in (stream, rest):
        protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
        assert protection is not None
        assert protection.state is ProtectionState.PROTECTED
        stop_row = rig.stop_row()
        assert stop_row is not None
        assert stop_row.intent_status is ExecutionIntentStatus.ACKED
    assert rest.transitions() == stream.transitions()


async def test_every_awaiting_entry_is_polled_over_rest_each_step() -> None:
    rig = await make_rig()
    await rig.coordinator.step()
    await rig.coordinator.step()
    assert len(rig.fake.calls_to("query_order_by_client")) == 2
    assert rig.fake.calls_to("place_algo_protective") == []
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.AWAITING_FILL


async def test_a_full_fill_seen_over_rest_places_the_stop() -> None:
    rig = await make_rig()
    rig.fake.fill(rig.entry_id)  # the whole 0.010: status FILLED
    await rig.coordinator.step()
    assert len(rig.fake.calls_to("place_algo_protective")) == 1
    await rig.coordinator.step()
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.PROTECTED


def _answer_executed_quantity_unknown(rig: ProtectionRig) -> None:
    """Make the entry probe answer like an exchange that omitted `executed_quantity`."""
    original = rig.fake.query_order_by_client

    async def probe(**kwargs: Any) -> Any:
        answer = await original(**kwargs)
        return replace(answer, executed_quantity=None)

    rig.fake.query_order_by_client = probe  # type: ignore[method-assign, assignment]


async def test_unknown_executed_quantity_on_a_filled_status_is_still_a_first_fill() -> None:
    rig = await make_rig()
    rig.fake.fill(rig.entry_id, quantity=D("0.004"))
    _answer_executed_quantity_unknown(rig)
    await rig.coordinator.step()
    assert len(rig.fake.calls_to("place_algo_protective")) == 1
    assert [e.event_type for e in rig.journal.calls].count("PROTECTION_FILL_QUANTITY_UNKNOWN") == 1
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.UNPROTECTED


@pytest.mark.parametrize("status", ["CANCELED", "EXPIRED"])
async def test_entry_ended_with_zero_executed_places_nothing(status: str) -> None:
    rig = await make_rig()
    rig.fake.cancel(rig.entry_id)
    if status == "EXPIRED":
        rig.fake.history[rig.entry_id].status = "EXPIRED"
    await rig.coordinator.step()
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.ENTRY_ENDED_NO_FILL
    assert protection.entry_terminal_at_utc == rig.clock.now()
    assert rig.fake.calls_to("place_algo_protective") == []
    assert rig.fake.calls_to("cancel_normal_order") == []
    assert rig.stop_row() is None
    assert rig.coordinator.blocks_new_entries() is False
    assert rig.transitions()[-1] == ("AWAITING_FILL", "ENTRY_ENDED_NO_FILL")
    await rig.coordinator.step()  # a finished plan is not polled again
    assert len(rig.fake.calls_to("query_order_by_client")) == 1


async def test_ended_entry_with_unknown_executed_quantity_is_settled_by_the_position() -> None:
    flat = await make_rig()
    flat.fake.cancel(flat.entry_id)
    _answer_executed_quantity_unknown(flat)
    await flat.coordinator.step()
    protection = flat.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.ENTRY_ENDED_NO_FILL
    assert flat.fake.calls_to("place_algo_protective") == []

    exposed = await make_rig()
    exposed.fake.fill(exposed.entry_id, quantity=D("0.004"))
    exposed.fake.cancel(exposed.entry_id)  # partially filled, then canceled
    _answer_executed_quantity_unknown(exposed)
    await exposed.coordinator.step()
    protection = exposed.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.UNPROTECTED
    assert len(exposed.fake.calls_to("place_algo_protective")) == 1


async def test_a_canceled_entry_that_kept_a_partial_fill_is_a_first_fill() -> None:
    rig = await make_rig()
    rig.fake.fill(rig.entry_id, quantity=D("0.004"))
    rig.fake.cancel(rig.entry_id)  # CANCELED with 0.004 executed: a position exists
    await rig.coordinator.step()
    assert len(rig.fake.calls_to("place_algo_protective")) == 1


async def test_replayed_fills_never_place_a_second_stop() -> None:
    rig = await make_rig()
    routed = rig.stream_fill(D("0.004"))
    rig.coordinator.fill_sink(routed)
    rig.coordinator.fill_sink(routed)
    await rig.coordinator.step()
    rig.coordinator.fill_sink(routed)  # replayed after the stop was placed
    await rig.coordinator.step()
    rig.coordinator.fill_sink(routed)
    await rig.coordinator.step()
    # Plan 19-16: the third step is the PROTECTED step, which adds the two take-profit legs.
    placed = [c["kwargs"]["client_algo_id"] for c in rig.fake.calls_to("place_algo_protective")]
    assert placed.count(rig.stop_id) == 1
    assert len(placed) == 3
    assert len(rig.fake.calls_to("cancel_normal_order")) == 1


def _foreign_fill(**overrides: Any) -> Any:
    from src.adapters.binance_userdata_router import FillSource, RoutedFill
    from src.execution.fill_monitor import FillEvent

    fields: dict[str, Any] = {
        "order_id": "ex-777",
        "exchange_trade_id": "foreign-trade-1",
        "symbol": "ETHUSDT",
        "side": "BUY",
        "position_side": "BOTH",
        "fill_price": D("2000.00"),
        "fill_quantity": D("0.5"),
        "fill_time_utc": TEST_ONLY_VIRTUAL_START,
    }
    fields.update(overrides)
    return RoutedFill(fill=FillEvent(**fields), source=FillSource.USER_DATA_EVENT, after_gap=False)


async def test_a_fill_for_an_order_no_plan_owns_is_journaled_not_acted_on() -> None:
    rig = await make_rig()
    rig.coordinator.fill_sink(_foreign_fill())  # must not raise
    await rig.coordinator.step()
    await rig.coordinator.step()
    assert rig.fake.calls_to("place_algo_protective") == []
    unknown = rig.journal.by_type("PROTECTION_UNKNOWN_FILL")
    assert len(unknown) == 1  # the same fill is journaled once
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.AWAITING_FILL


async def test_a_same_symbol_fill_of_another_order_is_unknown_once_the_entry_id_is_known() -> None:
    rig = await make_rig()
    await rig.coordinator.step()  # the REST poll learns the entry's exchange order id
    rig.coordinator.fill_sink(_foreign_fill(symbol=TEST_ONLY_SYMBOL, order_id="ex-777"))
    await rig.coordinator.step()
    assert rig.fake.calls_to("place_algo_protective") == []
    assert len(rig.journal.by_type("PROTECTION_UNKNOWN_FILL")) == 1


async def test_fill_sink_never_raises() -> None:
    rig = await make_rig()
    rig.coordinator.fill_sink(object())  # type: ignore[arg-type]
    assert rig.coordinator.fill_sink_failures == 1
    await rig.coordinator.step()
    assert rig.fake.calls_to("place_algo_protective") == []


async def test_stop_and_cancel_start_together_cancel_held() -> None:
    rig = await make_rig()
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    rig.fake.hold("cancel_normal_order")

    stepping = asyncio.create_task(rig.coordinator.step())
    await rig.clock.settle()

    # The stop completed in the same step while the cancel is still held (D-12).
    assert "place_algo_protective" in rig.fake.completed
    assert "cancel_normal_order" not in rig.fake.completed
    assert len(rig.fake.calls_to("cancel_normal_order")) == 1  # the cancel already started
    assert stepping.done() is False
    rig.fake.release("cancel_normal_order")
    await stepping
    assert "cancel_normal_order" in rig.fake.completed


async def test_stop_and_cancel_start_together_stop_held() -> None:
    rig = await make_rig()
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    rig.fake.hold("place_algo_protective")

    stepping = asyncio.create_task(rig.coordinator.step())
    await rig.clock.settle()

    # The cancel completed while the stop placement is held: the cancel does not wait for it.
    assert "cancel_normal_order" in rig.fake.completed
    assert "place_algo_protective" not in rig.fake.completed
    assert len(rig.fake.calls_to("place_algo_protective")) == 1  # the stop already started
    assert stepping.done() is False
    rig.fake.release("place_algo_protective")
    await stepping
    assert "place_algo_protective" in rig.fake.completed
