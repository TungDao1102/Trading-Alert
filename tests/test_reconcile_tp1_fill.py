"""A TP1 that triggered and filled is not a divergence (plan 20-28, WR-B2).

Binance Demo (evidence `demo-probe-EVIDENCE-20261022T120704Z.json`, case `tp1_quantity_from_fill`)
showed that a TAKE_PROFIT_MARKET TP1 which triggers leaves the open algo orders: it goes TRIGGERING,
TRIGGERED, FINISHED, the position drops from 0.0008 to 0.0004, and `current_all_algo_open_orders`
lists no TP1. The protection coordinator has no "TP1 filled" state (a COMPLETE plan stays COMPLETE
until the position is flat), so the local intent kept expecting the TP1 leg and every normal TP1
fill became UNSYNCED_ALGO and SAFE_MODE.

The smallest correct signal that exists today is the exchange position itself: TP1 is the only
leg of a COMPLETE plan that reduces the position without ending the plan, so a TP1 that has left
the book while exactly one exchange position of the same plan exists on the plan's side and is
strictly below the plan's intended quantity is explained. Nothing else is relaxed: TP2 and the stop
stay required, and a full (or larger) position, a flat account, a wrong side or a second plan on
the symbol keep the divergence. Known limit (reported, not hidden): a plan whose entry only partly
filled has a position below the intended quantity from the start, so for it the position alone
cannot tell a filled TP1 from a vanished one; the coordinator would have to expose the TP1 quantity
or a TP1 fill time to close that gap (see 20-28-SUMMARY.md).

Evidence label: executed unit tests with fakes; the Demo behavior is quoted from the evidence file
above and is not re-observed here.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Any

from src.domain.enums import OrderRole
from src.execution.order_ids import derive_algo_client_id
from src.reconcile.compare import (
    DIVERGENCE_KIND_UNSYNCED_ALGO,
    CompareDiff,
    LocalAlgoIntent,
    compare,
)
from src.reconcile.local_intent import STATE_RULES, derive_local_intent
from src.reconcile.safe_mode import SafeModeController

from tests.support.reconcile_doubles import (
    make_algo_order,
    make_plan_protection,
    make_position,
)
from tests.support.reconcile_rig import NOW, build_rig

H1 = "1" * 64
H2 = "2" * 64
SL = OrderRole.STOP_LOSS.value
TP1 = OrderRole.TAKE_PROFIT_1.value
TP2 = OrderRole.TAKE_PROFIT_2.value


def algo_id(plan_hash: str, role: str) -> str:
    return derive_algo_client_id(plan_hash=plan_hash, role=role)


def exchange_algos(*roles: str, plan_hash: str = H1, symbol: str = "BTCUSDT") -> tuple[Any, ...]:
    return tuple(make_algo_order(algo_id(plan_hash, role), symbol) for role in roles)


def run_compare(
    *,
    plans: tuple[Any, ...],
    algos: tuple[Any, ...],
    positions: tuple[Any, ...],
) -> CompareDiff:
    local = derive_local_intent(plans, ())
    return compare(
        **local.compare_kwargs(),
        truth_normal_orders=(),
        truth_algo_orders=algos,
        truth_positions=positions,
    )


def complete_plan(**kwargs: Any) -> Any:
    return make_plan_protection(H1, state="COMPLETE", quantity="0.008", **kwargs)


def kinds(diff: CompareDiff) -> list[tuple[str, str]]:
    return [(d.kind, d.order_role) for d in diff.divergences]


# --------------------------------------------------------------------------- #
# The local side: which leg may be explained.
# --------------------------------------------------------------------------- #


def test_only_the_tp1_leg_of_a_complete_plan_carries_the_bound() -> None:
    local = derive_local_intent((complete_plan(),), ())

    bounds = {a.order_role: a.explained_when_position_below for a in local.algos}

    assert bounds == {SL: None, TP1: Decimal("0.008"), TP2: None}


def test_other_states_expect_no_tp1_at_all() -> None:
    for state, rule in STATE_RULES.items():
        if rule.take_profits:
            continue
        plan = make_plan_protection(H1, state=state, quantity="0.008")
        assert all(a.order_role != TP1 for a in derive_local_intent((plan,), ()).algos), state


def test_a_plan_without_a_usable_quantity_gets_no_leniency() -> None:
    plan = replace(complete_plan(), entry_quantity=None)

    local = derive_local_intent((plan,), ())

    assert {a.order_role: a.explained_when_position_below for a in local.algos}[TP1] is None


def test_the_bound_is_a_field_of_the_algo_carrier_with_no_default_leniency() -> None:
    carrier = LocalAlgoIntent(
        client_algo_id="x", symbol="BTCUSDT", order_role=TP1, status="NEW", plan_hash=H1
    )

    assert carrier.explained_when_position_below is None


# --------------------------------------------------------------------------- #
# compare: the cases the owner listed.
# --------------------------------------------------------------------------- #


def test_tp1_filled_and_position_reduced_is_no_divergence() -> None:
    diff = run_compare(
        plans=(complete_plan(),),
        algos=exchange_algos(SL, TP2),
        positions=(make_position("BTCUSDT", "0.004"),),
    )

    assert diff.agreement is True
    assert diff.divergences == ()


def test_the_short_side_is_judged_with_its_own_sign() -> None:
    plan = make_plan_protection(H1, state="COMPLETE", quantity="0.008", side="SHORT")

    reduced = run_compare(
        plans=(plan,),
        algos=exchange_algos(SL, TP2),
        positions=(make_position("BTCUSDT", "-0.004"),),
    )
    flipped = run_compare(
        plans=(plan,),
        algos=exchange_algos(SL, TP2),
        positions=(make_position("BTCUSDT", "0.004"),),
    )

    assert reduced.agreement is True
    assert flipped.agreement is False


def test_tp1_absent_with_the_full_position_is_still_a_divergence() -> None:
    diff = run_compare(
        plans=(complete_plan(),),
        algos=exchange_algos(SL, TP2),
        positions=(make_position("BTCUSDT", "0.008"),),
    )

    assert kinds(diff) == [(DIVERGENCE_KIND_UNSYNCED_ALGO, TP1)]


def test_tp1_absent_with_no_exchange_position_is_still_a_divergence() -> None:
    diff = run_compare(plans=(complete_plan(),), algos=exchange_algos(SL, TP2), positions=())

    assert (DIVERGENCE_KIND_UNSYNCED_ALGO, TP1) in kinds(diff)


def test_a_position_larger_than_the_plan_is_not_an_explanation() -> None:
    diff = run_compare(
        plans=(complete_plan(),),
        algos=exchange_algos(SL, TP2),
        positions=(make_position("BTCUSDT", "0.009"),),
    )

    assert (DIVERGENCE_KIND_UNSYNCED_ALGO, TP1) in kinds(diff)


def test_tp2_is_still_required_after_a_tp1_fill() -> None:
    diff = run_compare(
        plans=(complete_plan(),),
        algos=exchange_algos(SL),
        positions=(make_position("BTCUSDT", "0.004"),),
    )

    assert kinds(diff) == [(DIVERGENCE_KIND_UNSYNCED_ALGO, TP2)]


def test_the_stop_is_still_required_after_a_tp1_fill() -> None:
    diff = run_compare(
        plans=(complete_plan(),),
        algos=exchange_algos(TP2),
        positions=(make_position("BTCUSDT", "0.004"),),
    )

    assert (DIVERGENCE_KIND_UNSYNCED_ALGO, SL) in kinds(diff)
    assert all(role != TP1 for _kind, role in kinds(diff))


def test_a_tp1_that_is_still_resting_is_unchanged() -> None:
    diff = run_compare(
        plans=(complete_plan(),),
        algos=exchange_algos(SL, TP1, TP2),
        positions=(make_position("BTCUSDT", "0.008"),),
    )

    assert diff.agreement is True


def test_a_second_plan_on_the_symbol_keeps_the_divergence() -> None:
    other = make_plan_protection(H2, state="PROTECTED", quantity="0.008")
    diff = run_compare(
        plans=(complete_plan(), other),
        algos=exchange_algos(SL, TP2) + exchange_algos(SL, plan_hash=H2),
        positions=(make_position("BTCUSDT", "0.004"),),
    )

    assert (DIVERGENCE_KIND_UNSYNCED_ALGO, TP1) in kinds(diff)


def test_two_exchange_position_rows_for_the_symbol_keep_the_divergence() -> None:
    diff = run_compare(
        plans=(complete_plan(),),
        algos=exchange_algos(SL, TP2),
        positions=(
            make_position("BTCUSDT", "0.004"),
            make_position("BTCUSDT", "0.001", position_side="LONG"),
        ),
    )

    assert (DIVERGENCE_KIND_UNSYNCED_ALGO, TP1) in kinds(diff)


def test_another_symbols_position_does_not_explain_the_leg() -> None:
    diff = run_compare(
        plans=(complete_plan(),),
        algos=exchange_algos(SL, TP2),
        positions=(make_position("ETHUSDT", "0.004"),),
    )

    assert (DIVERGENCE_KIND_UNSYNCED_ALGO, TP1) in kinds(diff)


def test_a_legacy_carrier_without_the_field_behaves_as_before() -> None:
    """A caller that builds its own `LocalAlgoIntent` (no bound) still gets the divergence."""
    local = derive_local_intent((complete_plan(),), ())
    stripped = tuple(
        replace(a, explained_when_position_below=None) if a.order_role == TP1 else a
        for a in local.algos
    )

    diff = compare(
        local_open_orders=local.orders,
        local_open_algos=stripped,
        local_open_positions=local.positions,
        truth_normal_orders=(),
        truth_algo_orders=exchange_algos(SL, TP2),
        truth_positions=(make_position("BTCUSDT", "0.004"),),
        local_active_plans=local.active_plans,
    )

    assert (DIVERGENCE_KIND_UNSYNCED_ALGO, TP1) in kinds(diff)


# --------------------------------------------------------------------------- #
# The loop and the exit use the same local intent.
# --------------------------------------------------------------------------- #


async def test_the_loop_does_not_enter_safe_mode_for_a_normal_tp1_fill() -> None:
    rig = build_rig(
        plans=(complete_plan(),),
        algo=exchange_algos(SL, TP2),
        positions=(make_position("BTCUSDT", "0.004"),),
    )

    report = await rig.loop.tick(now_utc=NOW)

    assert report.agreement is True
    assert report.safe_mode_reasons == ()
    assert rig.safe_mode.in_safe_mode is False
    assert rig.alerts.alerts == []


async def test_the_loop_still_enters_safe_mode_when_tp1_vanished_with_the_full_position() -> None:
    rig = build_rig(
        plans=(complete_plan(),),
        algo=exchange_algos(SL, TP2),
        positions=(make_position("BTCUSDT", "0.008"),),
    )

    report = await rig.loop.tick(now_utc=NOW)

    assert report.agreement is False
    assert "UNSYNCED_ALGO" in report.safe_mode_reasons
    assert rig.safe_mode.in_safe_mode is True


async def test_the_operator_exit_accepts_the_tp1_fill_state() -> None:
    """The exit compare is the loop's compare: a plan in the TP1-filled state no longer blocks."""
    rig = build_rig(
        plans=(complete_plan(),),
        algo=exchange_algos(SL, TP2),
        positions=(make_position("BTCUSDT", "0.004"),),
    )
    controller = SafeModeController(adapter=rig.adapter, journal=rig.journal)
    controller.enter_safe_mode(reason="STALE_FEED", now_utc=NOW)

    def local() -> Any:
        return derive_local_intent(rig.protection.protections(), ())

    from src.reconcile.safe_mode import ExitReadiness

    decision = await controller.exit_safe_mode(
        operator_id="op-1",
        local_intent_fn=local,
        readiness=lambda: ExitReadiness(0, 0, 0, True),
        gate_status=lambda: (None, "RESTORED_DURABLE"),
        stream_state=lambda: "LIVE",
        now_utc=NOW + timedelta(minutes=1),
    )

    assert decision.exited is True, decision.refusals
