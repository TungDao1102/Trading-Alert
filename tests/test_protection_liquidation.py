"""The post-fill liquidation comparison of the protection coordinator (plan 22-13; D-12, A10, O-4).

Run over the Phase 19 stateful fake exchange (constructed with `enforce_flat_stop_rejection=True`),
virtual time and a scripted watch. The fake serves `liquidation_price=None`, so the tests wrap
`snapshot_positions` to put a TEST_ONLY liquidation price on the rows; none of those numbers is
exchange data, and the exchange's isolated `liquidationPrice` has never been observed with this
code. A green test proves the hook and the reuse of the CLOSE_REQUIRED path, not the exchange's
behavior. The ProtectionState enum, the transition table and every deadline are untouched; the
Phase 19 and 20 protection suites run unchanged beside this file.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from src.execution.liquidation_watch import (
    LIQUIDATION_PRICE_DIFFERS,
    LIQUIDATION_TOO_CLOSE_AFTER_FILL,
    LIQUIDATION_UNKNOWN_AFTER_FILL,
    LiquidationFailurePolicy,
    LiquidationWatch,
    LiquidationWatchAction,
    LiquidationWatchInput,
    LiquidationWatchVerdict,
)
from src.execution.protection import (
    BRANCH_B6_LIQUIDATION_TOO_CLOSE,
    EVENT_LIQUIDATION_CHECK_ERROR,
    EVENT_LIQUIDATION_CHECKED,
    EVENT_LIQUIDATION_FAILED_ALERT_ONLY,
    EVENT_LIQUIDATION_PRICE_DIFFERS,
    ProtectionCoordinator,
    ProtectionState,
)

from tests.support.execution_limits import test_only_execution_limits as limits_with
from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.protection_doubles import (
    TEST_ONLY_PLAN_HASH,
    ProtectionRig,
    make_rig,
)

D = Decimal
LIQUIDATION_TYPES = {
    EVENT_LIQUIDATION_CHECKED,
    EVENT_LIQUIDATION_PRICE_DIFFERS,
    EVENT_LIQUIDATION_FAILED_ALERT_ONLY,
    EVENT_LIQUIDATION_CHECK_ERROR,
}
# TEST_ONLY liquidation price put on the fake's position rows.
ROW_LIQUIDATION = D("41000.5")
LOCAL_LIQUIDATION = D("41000.4999")


@dataclass
class ScriptedWatch:
    """A `LiquidationWatchPort` answering from a script; it records each input."""

    verdict: Any = None
    error: Exception | None = None
    calls: list[LiquidationWatchInput] = field(default_factory=list)

    async def check(self, inputs: LiquidationWatchInput) -> Any:
        self.calls.append(inputs)
        if self.error is not None:
            raise self.error
        return self.verdict


def _verdict(
    action: LiquidationWatchAction,
    reason: str,
    exchange: Decimal | None = ROW_LIQUIDATION,
    local: Decimal | None = LOCAL_LIQUIDATION,
) -> LiquidationWatchVerdict:
    return LiquidationWatchVerdict(action, reason, exchange, local)


def _put_liquidation_price(fake: BinanceSemanticsFakeAdapter, value: Decimal | None) -> None:
    original = fake.snapshot_positions

    async def with_price(**kwargs: Any) -> Any:
        rows = await original(**kwargs)
        return [replace(row, liquidation_price=value) for row in rows]

    fake.snapshot_positions = with_price  # type: ignore[method-assign]


async def _rig_with_price(
    watch: Any, *, price: Decimal | None = ROW_LIQUIDATION, **kwargs: Any
) -> ProtectionRig:
    rig = await make_rig(liquidation_watch=watch, **kwargs)
    _put_liquidation_price(rig.fake, price)
    return rig


async def _to_protected(rig: ProtectionRig) -> None:
    """Fill, place the stop (step 1), REST-confirm it (step 2): PROTECTED, watch not yet asked."""
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()
    await rig.clock.advance(1)
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.PROTECTED


def _state(rig: ProtectionRig) -> ProtectionState:
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    return protection.state


def _events(rig: ProtectionRig, event_type: str) -> list[dict[str, str]]:
    return [json.loads(e.payload_json) for e in rig.journal.calls if e.event_type == event_type]


def _transition_triples(rig: ProtectionRig) -> list[tuple[str, str, str]]:
    triples = []
    for body in _events(rig, "PROTECTION_TRANSITION"):
        triples.append((body["from"], body["to"], body["reason"]))
    return triples


def _entered_b6(rig: ProtectionRig) -> bool:
    """The plan went to CLOSE_REQUIRED with the B6 branch (the scripted closer then fails)."""
    return any(
        to == "CLOSE_REQUIRED" and reason == BRANCH_B6_LIQUIDATION_TOO_CLOSE
        for _, to, reason in _transition_triples(rig)
    )


def _liquidation_events(rig: ProtectionRig) -> list[str]:
    return [e.event_type for e in rig.journal.calls if e.event_type in LIQUIDATION_TYPES]


# --- the watch hook: tracer --------------------------------------------------------------------


async def test_close_verdict_enters_close_required_once_and_keeps_the_stop() -> None:
    watch = ScriptedWatch(_verdict(LiquidationWatchAction.CLOSE, LIQUIDATION_TOO_CLOSE_AFTER_FILL))
    rig = await _rig_with_price(watch)  # the scripted closer answers "not flat"
    await _to_protected(rig)
    assert watch.calls == []  # not before the stop is confirmed and the plan is PROTECTED
    stops_placed = len(rig.fake.calls_to("place_algo_protective"))

    await rig.clock.advance(1)
    await rig.coordinator.step()

    assert BRANCH_B6_LIQUIDATION_TOO_CLOSE == "B6_LIQUIDATION_TOO_CLOSE"
    triples = _transition_triples(rig)
    assert ("PROTECTED", "CLOSE_REQUIRED", BRANCH_B6_LIQUIDATION_TOO_CLOSE) in triples
    # The unchanged close flow then ran once: an unconfirmed close is CLOSE_FAILED, as ever.
    assert _state(rig) is ProtectionState.CLOSE_FAILED
    assert len(watch.calls) == 1
    # SAFE_MODE once, the critical alert, one emergency close with the branch as its reason.
    assert rig.safe_mode.entered_reasons == ["CLOSE_REQUIRED"]
    assert [(a.event, a.reason) for a in rig.alerts.alerts] == [
        ("CLOSE_REQUIRED", BRANCH_B6_LIQUIDATION_TOO_CLOSE)
    ]
    assert len(rig.closer.calls) == 1  # type: ignore[union-attr]
    assert rig.closer.calls[0]["reason"] == BRANCH_B6_LIQUIDATION_TOO_CLOSE  # type: ignore[union-attr]
    # The stop was not cancelled and no other order was sent by the check.
    assert rig.fake.calls_to("cancel_algo_order") == []
    assert len(rig.fake.calls_to("place_algo_protective")) == stops_placed
    assert rig.fake.calls_to("place_market_close") == []  # the scripted closer sent nothing
    assert _events(rig, EVENT_LIQUIDATION_CHECKED)[0]["action"] == "CLOSE"


async def test_close_verdict_with_the_real_closer_ends_flat_through_one_reduce_only_close() -> None:
    watch = ScriptedWatch(_verdict(LiquidationWatchAction.CLOSE, LIQUIDATION_TOO_CLOSE_AFTER_FILL))
    rig = await _rig_with_price(watch, real_closer=True)
    await _to_protected(rig)

    await rig.clock.advance(1)
    await rig.coordinator.step()

    assert ("PROTECTED", "CLOSE_REQUIRED", BRANCH_B6_LIQUIDATION_TOO_CLOSE) in (
        _transition_triples(rig)
    )
    assert len(rig.fake.calls_to("place_market_close")) == 1
    assert rig.fake.positions[rig.entry.symbol] == D("0")
    assert len(watch.calls) == 1


async def test_the_watch_input_is_built_from_the_position_row_and_the_plan() -> None:
    watch = ScriptedWatch(_verdict(LiquidationWatchAction.OK, "OK"))
    rig = await _rig_with_price(watch)
    await _to_protected(rig)

    await rig.coordinator.step()

    (inputs,) = watch.calls
    assert inputs.symbol == rig.entry.symbol
    assert inputs.side == "LONG"
    assert inputs.stop_price == rig.entry.sl_trigger_price
    assert inputs.leverage == rig.entry.plan_constraint_snapshot.leverage
    assert inputs.quantity == D("0.004")
    assert inputs.entry_price == D("60000.00")
    assert inputs.exchange_liquidation_price == ROW_LIQUIDATION


# --- the other verdicts ------------------------------------------------------------------------


async def test_ok_verdict_journals_once_and_the_plan_is_never_checked_again() -> None:
    watch = ScriptedWatch(_verdict(LiquidationWatchAction.OK, "OK"))
    rig = await _rig_with_price(watch)
    await _to_protected(rig)

    for _ in range(3):
        await rig.clock.advance(1)
        await rig.coordinator.step()

    assert len(watch.calls) == 1
    assert _liquidation_events(rig) == [EVENT_LIQUIDATION_CHECKED]
    assert _state(rig) is not ProtectionState.CLOSE_REQUIRED
    assert rig.alerts.alerts == []
    assert rig.safe_mode.entered_reasons == []


async def test_ok_differs_journals_both_exact_prices_and_raises_no_alert() -> None:
    """WR-05: the recorded Demo position differs by the rounded wallet; that is calibration."""
    watch = ScriptedWatch(
        _verdict(
            LiquidationWatchAction.OK_DIFFERS,
            LIQUIDATION_PRICE_DIFFERS,
            exchange=D("64968.85373637"),
            local=D("64968.853735"),
        )
    )
    rig = await _rig_with_price(watch)
    await _to_protected(rig)

    await rig.coordinator.step()

    (note,) = _events(rig, EVENT_LIQUIDATION_PRICE_DIFFERS)
    assert note["exchange_price"] == "64968.85373637"
    assert note["local_price"] == "64968.853735"
    assert _liquidation_events(rig) == [EVENT_LIQUIDATION_PRICE_DIFFERS]
    assert note["reason"] == LIQUIDATION_PRICE_DIFFERS
    assert rig.alerts.alerts == []  # no owner tolerance exists, so a difference never alerts
    assert rig.safe_mode.entered_reasons == []
    assert _state(rig) is not ProtectionState.CLOSE_REQUIRED
    assert rig.closer.calls == []  # type: ignore[union-attr]


async def test_alert_only_failed_journals_and_alerts_but_never_closes() -> None:
    watch = ScriptedWatch(
        _verdict(LiquidationWatchAction.ALERT_ONLY_FAILED, LIQUIDATION_TOO_CLOSE_AFTER_FILL)
    )
    rig = await _rig_with_price(watch)
    await _to_protected(rig)

    await rig.coordinator.step()

    assert _liquidation_events(rig) == [EVENT_LIQUIDATION_FAILED_ALERT_ONLY]
    assert [(a.event, a.reason) for a in rig.alerts.alerts] == [
        ("DIVERGENCE", LIQUIDATION_TOO_CLOSE_AFTER_FILL)
    ]
    assert _state(rig) is not ProtectionState.CLOSE_REQUIRED
    assert rig.closer.calls == []  # type: ignore[union-attr]
    assert rig.safe_mode.entered_reasons == []


# --- fail closed -------------------------------------------------------------------------------


async def test_a_watch_that_raises_is_a_close_and_journals_only_the_class_name() -> None:
    watch = ScriptedWatch(error=RuntimeError("secret detail"))
    rig = await _rig_with_price(watch)
    await _to_protected(rig)

    await rig.coordinator.step()

    assert _entered_b6(rig)
    (note,) = _events(rig, EVENT_LIQUIDATION_CHECK_ERROR)
    assert note["error_type"] == "RuntimeError"
    assert "secret detail" not in json.dumps(note)
    assert len(rig.closer.calls) == 1  # type: ignore[union-attr]


async def test_a_verdict_of_the_wrong_type_is_a_close() -> None:
    rig = await _rig_with_price(ScriptedWatch("OK"))
    await _to_protected(rig)

    await rig.coordinator.step()

    assert _entered_b6(rig)
    assert _events(rig, EVENT_LIQUIDATION_CHECK_ERROR)[0]["error_type"] == "TypeError"


@dataclass
class PolicyWatch(ScriptedWatch):
    """A scripted watch that also exposes the owner's policy (O-4), as the real watch does."""

    policy: LiquidationFailurePolicy = LiquidationFailurePolicy.CLOSE_POSITION


def _put_row_field(fake: BinanceSemanticsFakeAdapter, **changes: Any) -> None:
    original = fake.snapshot_positions

    async def edited(**kwargs: Any) -> Any:
        rows = await original(**kwargs)
        return [replace(row, **changes) for row in rows]

    fake.snapshot_positions = edited  # type: ignore[method-assign]


@pytest.mark.parametrize("case", ["raises", "wrong type", "bad row"])
async def test_alert_only_policy_alerts_instead_of_closing_on_the_error_paths(case: str) -> None:
    """WR-04: ALERT_ONLY is the owner's policy for every unknown, including the error paths."""
    if case == "raises":
        watch: Any = PolicyWatch(
            error=RuntimeError("secret detail"), policy=LiquidationFailurePolicy.ALERT_ONLY
        )
    elif case == "wrong type":
        watch = PolicyWatch("OK", policy=LiquidationFailurePolicy.ALERT_ONLY)
    else:
        watch = _real_watch(LiquidationFailurePolicy.ALERT_ONLY)
    rig = await _rig_with_price(watch)
    if case == "bad row":
        _put_row_field(rig.fake, entry_price=None)
    await _to_protected(rig)

    await rig.coordinator.step()

    assert not _entered_b6(rig)
    assert _state(rig) is not ProtectionState.CLOSE_REQUIRED
    assert rig.closer.calls == []  # type: ignore[union-attr]
    assert "CLOSE_REQUIRED" not in rig.safe_mode.entered_reasons
    (note,) = _events(rig, EVENT_LIQUIDATION_CHECK_ERROR)
    assert "secret detail" not in json.dumps(note)
    assert [(a.event, a.reason) for a in rig.alerts.alerts] == [
        ("DIVERGENCE", LIQUIDATION_UNKNOWN_AFTER_FILL)
    ]
    # Once per plan: a later step neither asks again nor alerts again.
    await rig.clock.advance(1)
    await rig.coordinator.step()
    assert len(rig.alerts.alerts) == 1


@pytest.mark.parametrize("case", ["raises", "wrong type", "bad row"])
async def test_close_position_policy_still_closes_on_the_error_paths(case: str) -> None:
    if case == "raises":
        watch: Any = PolicyWatch(error=RuntimeError("x"))
    elif case == "wrong type":
        watch = PolicyWatch("OK")
    else:
        watch = _real_watch(LiquidationFailurePolicy.CLOSE_POSITION)
    rig = await _rig_with_price(watch)
    if case == "bad row":
        _put_row_field(rig.fake, entry_price=None)
    await _to_protected(rig)

    await rig.coordinator.step()

    assert _entered_b6(rig)
    assert len(rig.closer.calls) == 1  # type: ignore[union-attr]


@pytest.mark.parametrize("value", [None, D("0"), D("0.00000000")])
async def test_the_real_watch_closes_on_the_cross_margin_sentinel_through_the_hook(
    value: Decimal | None,
) -> None:
    class NoBrackets:
        async def get(self, *, symbol: str) -> None:
            return None

    class NoFee:
        async def entry_fee_rate(self, *, symbol: str) -> None:
            return None

    watch = LiquidationWatch(
        brackets=NoBrackets(),
        fee_rates=NoFee(),
        limits=limits_with(),
        policy=LiquidationFailurePolicy.CLOSE_POSITION,
    )
    rig = await _rig_with_price(watch, price=value)
    await _to_protected(rig)

    await rig.coordinator.step()

    assert _entered_b6(rig)
    assert _events(rig, EVENT_LIQUIDATION_CHECKED)[0]["reason"] == LIQUIDATION_UNKNOWN_AFTER_FILL


async def test_an_unreadable_position_read_is_journaled_and_the_next_step_tries_again() -> None:
    watch = ScriptedWatch(_verdict(LiquidationWatchAction.OK, "OK"))
    rig = await _rig_with_price(watch)
    await _to_protected(rig)
    original = rig.fake.snapshot_positions
    failures = [RuntimeError("down")]

    async def flaky(**kwargs: Any) -> Any:
        if failures:
            raise failures.pop()
        return await original(**kwargs)

    rig.fake.snapshot_positions = flaky  # type: ignore[method-assign]

    await rig.coordinator.step()
    assert watch.calls == []
    assert _liquidation_events(rig) == []
    assert any(e["call"] == "snapshot_positions" for e in _events(rig, "PROTECTION_REST_FAILED"))

    await rig.clock.advance(1)
    await rig.coordinator.step()
    assert len(watch.calls) == 1
    assert _liquidation_events(rig) == [EVENT_LIQUIDATION_CHECKED]


async def test_a_flat_position_marks_the_plan_checked_without_asking_the_watch() -> None:
    watch = ScriptedWatch(_verdict(LiquidationWatchAction.CLOSE, LIQUIDATION_TOO_CLOSE_AFTER_FILL))
    rig = await _rig_with_price(watch)
    await _to_protected(rig)
    rig.fake.positions[rig.entry.symbol] = D("0")

    await rig.coordinator.step()
    assert watch.calls == []
    assert _liquidation_events(rig) == []

    # Checked: a position that appears later is not judged by this hook.
    rig.fake.positions[rig.entry.symbol] = D("0.004")
    await rig.clock.advance(1)
    await rig.coordinator.step()
    assert watch.calls == []


# --- where and when it runs --------------------------------------------------------------------


async def test_it_never_runs_before_the_stop_is_confirmed() -> None:
    watch = ScriptedWatch(_verdict(LiquidationWatchAction.CLOSE, LIQUIDATION_TOO_CLOSE_AFTER_FILL))
    rig = await _rig_with_price(watch)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))

    await rig.coordinator.step()  # first fill: the stop is placed, NEW is not protection

    assert _state(rig) is ProtectionState.UNPROTECTED
    assert watch.calls == []


async def test_it_runs_in_protected_entry_open_too() -> None:
    watch = ScriptedWatch(_verdict(LiquidationWatchAction.OK, "OK"))
    rig = await _rig_with_price(watch)
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    rig.fake.hold("cancel_normal_order")
    stepping = asyncio.create_task(rig.coordinator.step())
    await rig.clock.settle()
    rig.fake.release("cancel_normal_order")
    await stepping
    # Roll the entry back to open: a cancel that has not taken effect yet.
    record = rig.fake.history.pop(rig.entry_id)
    record.status = "PARTIALLY_FILLED"
    rig.fake.open_orders[rig.entry_id] = record
    await rig.coordinator.step()
    assert _state(rig) is ProtectionState.PROTECTED_ENTRY_OPEN
    assert watch.calls == []

    await rig.coordinator.step()

    assert len(watch.calls) == 1
    assert _liquidation_events(rig) == [EVENT_LIQUIDATION_CHECKED]


async def test_the_stop_placement_and_deadlines_are_the_same_with_a_watch() -> None:
    plain = await make_rig()
    watched = await _rig_with_price(ScriptedWatch(_verdict(LiquidationWatchAction.OK, "OK")))
    for rig in (plain, watched):
        await _to_protected(rig)
    assert [c["kwargs"] for c in watched.fake.calls_to("place_algo_protective")] == [
        c["kwargs"] for c in plain.fake.calls_to("place_algo_protective")
    ]
    assert watched.transitions() == plain.transitions()


async def test_no_watch_means_no_new_event_and_an_identical_happy_path_journal() -> None:
    first = await make_rig()
    second = await make_rig(liquidation_watch=None)
    for rig in (first, second):
        await _to_protected(rig)
        for _ in range(2):
            await rig.clock.advance(1)
            await rig.coordinator.step()

    def snapshot(rig: ProtectionRig) -> list[tuple[str, str]]:
        return [(e.event_type, e.payload_json) for e in rig.journal.calls]

    assert snapshot(first) == snapshot(second)
    assert _liquidation_events(first) == []
    assert first.fake.calls_to("snapshot_positions") == second.fake.calls_to("snapshot_positions")


async def test_a_restored_plan_starts_unchecked() -> None:
    from src.execution.protection import _Tracked

    rig = await make_rig(register=False)
    tracked = _Tracked(rig.entry, restored_state=ProtectionState.PROTECTED)
    assert tracked.liquidation_checked is False


class _NoBrackets:
    async def get(self, *, symbol: str) -> None:
        return None


class _NoFee:
    async def entry_fee_rate(self, *, symbol: str) -> None:
        return None


def _real_watch(policy: LiquidationFailurePolicy) -> LiquidationWatch:
    return LiquidationWatch(
        brackets=_NoBrackets(), fee_rates=_NoFee(), limits=limits_with(), policy=policy
    )


async def test_a_plan_without_a_leverage_is_not_closed_when_the_value_is_far_away() -> None:
    """WR-03: a restored plan (persisted snapshot: leverage UNKNOWN) keeps its healthy position."""
    from tests.support.protection_doubles import complete_constraint_snapshot

    watch = _real_watch(LiquidationFailurePolicy.CLOSE_POSITION)
    rig = await _rig_with_price(
        watch, plan_constraint_snapshot=complete_constraint_snapshot(leverage=None)
    )
    assert rig.entry.plan_constraint_snapshot.leverage is None
    await _to_protected(rig)

    await rig.coordinator.step()

    assert not _entered_b6(rig)
    assert _state(rig) is not ProtectionState.CLOSE_REQUIRED
    assert rig.closer.calls == []  # type: ignore[union-attr]
    # (An incomplete snapshot also leaves the take-profits unattached, which is its own SAFE_MODE
    # reason; the liquidation check adds none and closes nothing.)
    assert "CLOSE_REQUIRED" not in rig.safe_mode.entered_reasons
    (note,) = _events(rig, EVENT_LIQUIDATION_CHECKED)
    assert note["action"] == "OK"
    assert note["local_price"] == "NONE"  # the comparison was skipped


async def test_a_plan_without_a_leverage_is_still_closed_when_the_value_is_inside_the_buffer() -> (
    None
):
    from tests.support.protection_doubles import complete_constraint_snapshot

    watch = _real_watch(LiquidationFailurePolicy.CLOSE_POSITION)
    # Entry 60000, stop 59000, TEST_ONLY buffer 137 bps = 822: 58900 is inside the buffer.
    rig = await _rig_with_price(
        watch,
        price=D("58900"),
        plan_constraint_snapshot=complete_constraint_snapshot(leverage=None),
    )
    await _to_protected(rig)

    await rig.coordinator.step()

    assert _entered_b6(rig)


@pytest.mark.parametrize("bad", [object(), "check", 1])
async def test_the_constructor_refuses_a_watch_without_a_callable_check(bad: Any) -> None:
    rig = await make_rig(register=False)
    with pytest.raises(TypeError):
        ProtectionCoordinator(
            adapter=rig.fake,
            intent_store=rig.inner_store,  # type: ignore[arg-type]
            journal=rig.journal,
            safe_mode_controller=rig.safe_mode,
            alert_sink=rig.alerts,
            emergency_closer=rig.closer,
            limits=limits_with(),
            clock=lambda: datetime(2026, 10, 24, tzinfo=UTC),
            liquidation_watch=bad,
        )
