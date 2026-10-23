"""Divergence policy table and local-intent derivation (Phase 20, plan 20-12, D-01, D-02, D-07).

Unit level, no loop: the pure table that says what each compare kind does, and the pure function
that turns the coordinator's views plus unresolved intent rows into the local side of compare v2.
Evidence label: executed unit tests; nothing here touches an exchange.
"""

from __future__ import annotations

import dataclasses
import importlib
from decimal import Decimal
from typing import Any

import pytest
from src.domain.enums import OrderRole
from src.execution.order_ids import derive_algo_client_id, derive_client_order_id
from src.execution.protection import NOTIFIABLE_DIVERGENCE_KINDS, ProtectionState
from src.ops.alerts import ALERT_EVENTS
from src.reconcile.classify import (
    ALERT_DIVERGENCE,
    ALERT_FOREIGN_ORDER,
    ALERT_STALE_DATA,
    ALERT_UNKNOWN_ORDER,
    ALERT_UNPROTECTED_POSITION,
    POLICY_BY_KIND,
    DivergenceAction,
    classify,
)
from src.reconcile.compare import compare
from src.reconcile.local_intent import STATE_RULES, LocalIntent, derive_local_intent

from tests.support.reconcile_doubles import (
    make_algo_order,
    make_intent_record,
    make_open_order,
    make_plan_protection,
    make_position,
)
from tests.support.reconcile_rig import NOW, build_rig

H1 = "1" * 64
H2 = "2" * 64
ENTRY_ID = derive_client_order_id(plan_hash=H1, role=OrderRole.ENTRY.value)
SL_ID = derive_algo_client_id(plan_hash=H1, role=OrderRole.STOP_LOSS.value)
TP1_ID = derive_algo_client_id(plan_hash=H1, role=OrderRole.TAKE_PROFIT_1.value)
TP2_ID = derive_algo_client_id(plan_hash=H1, role=OrderRole.TAKE_PROFIT_2.value)

# --------------------------------------------------------------------------- #
# The policy table.
# --------------------------------------------------------------------------- #

_KINDS = importlib.import_module("src.reconcile.compare")._DIVERGENCE_KINDS

#: kind -> (action, alert event): the plan's table, written out independently of the module.
EXPECTED_POLICY: dict[str, tuple[DivergenceAction, str]] = {
    "ORPHAN_PROTECTIVE": (DivergenceAction.SWEEP_ORPHAN, "DIVERGENCE"),
    "POSITION_WITHOUT_STOP": (DivergenceAction.DELEGATE_TO_COORDINATOR, "UNPROTECTED_POSITION"),
    "TP_ONLY_POSITION": (DivergenceAction.DELEGATE_TO_COORDINATOR, "UNPROTECTED_POSITION"),
    "ENTRY_WITHOUT_PROTECTIVE": (
        DivergenceAction.DELEGATE_TO_COORDINATOR,
        "UNPROTECTED_POSITION",
    ),
    "SIGN_FLIPPED_POSITION": (DivergenceAction.DELEGATE_TO_COORDINATOR, "DIVERGENCE"),
    "DOUBLED_POSITION": (DivergenceAction.DELEGATE_TO_COORDINATOR, "DIVERGENCE"),
    "FOREIGN_ORDER": (DivergenceAction.ALERT_ONLY, "FOREIGN_ORDER"),
    "UNTRACKED_SYSTEM_ORDER": (DivergenceAction.ALERT_ONLY, "UNKNOWN_ORDER"),
    "UNSYNCED_NORMAL": (DivergenceAction.ALERT_ONLY, "DIVERGENCE"),
    "UNSYNCED_ALGO": (DivergenceAction.ALERT_ONLY, "DIVERGENCE"),
    "UNSYNCED_POSITION": (DivergenceAction.ALERT_ONLY, "DIVERGENCE"),
    "DUPLICATE_EXCHANGE_ID": (DivergenceAction.ALERT_ONLY, "DIVERGENCE"),
    "AMBIGUOUS_POSITION_OWNER": (DivergenceAction.ALERT_ONLY, "DIVERGENCE"),
    "UNSUPPORTED_POSITION_SIDE": (DivergenceAction.ALERT_ONLY, "DIVERGENCE"),
    "STREAM_SINK_FAILURE": (DivergenceAction.ALERT_ONLY, "DIVERGENCE"),
    # Plan 20-16: a halted user-data stream is stale data, not a book divergence.
    "STREAM_TASK_DIED": (DivergenceAction.ALERT_ONLY, "STALE_DATA"),
}


def test_the_policy_table_covers_exactly_the_compare_vocabulary() -> None:
    assert set(POLICY_BY_KIND) == _KINDS
    assert set(EXPECTED_POLICY) == _KINDS


def test_classify_of_an_unknown_kind_raises_key_error() -> None:
    with pytest.raises(KeyError):
        classify("NOT_A_KIND")


@pytest.mark.parametrize("kind", sorted(_KINDS))
def test_each_kind_has_the_planned_action_alert_and_safe_mode_reason(kind: str) -> None:
    policy = classify(kind)
    action, alert = EXPECTED_POLICY[kind]
    assert (policy.action, policy.alert_event) == (action, alert)
    # The two kinds with a reason of their own: the supervisor halt (plan 20-16) and the
    # ownership conflict (plan 20-20, owner decision O-D).
    own_reason = {
        "STREAM_TASK_DIED": "USER_DATA_STREAM_HALTED",
        "AMBIGUOUS_POSITION_OWNER": "SYMBOL_OWNERSHIP_CONFLICT",
    }
    assert policy.safe_mode_reason == own_reason.get(kind, kind)
    assert policy.safe_mode_reason != ""


def test_only_orphans_are_sweepable() -> None:
    sweepable = {k for k, p in POLICY_BY_KIND.items() if p.action is DivergenceAction.SWEEP_ORPHAN}
    assert sweepable == {"ORPHAN_PROTECTIVE"}
    assert POLICY_BY_KIND["FOREIGN_ORDER"].action is DivergenceAction.ALERT_ONLY
    assert POLICY_BY_KIND["UNTRACKED_SYSTEM_ORDER"].action is DivergenceAction.ALERT_ONLY


def test_the_actions_are_the_three_owners_and_no_cancel_exists() -> None:
    assert {a.value for a in DivergenceAction} == {
        "SWEEP_ORPHAN",
        "DELEGATE_TO_COORDINATOR",
        "ALERT_ONLY",
    }


def test_delegated_kinds_are_exactly_the_kinds_the_coordinator_accepts() -> None:
    delegated = {
        k for k, p in POLICY_BY_KIND.items() if p.action is DivergenceAction.DELEGATE_TO_COORDINATOR
    }
    assert delegated == set(NOTIFIABLE_DIVERGENCE_KINDS)


def test_every_alert_event_is_in_the_operational_alert_vocabulary() -> None:
    used = {p.alert_event for p in POLICY_BY_KIND.values()}
    assert used <= set(ALERT_EVENTS)
    assert {
        ALERT_UNPROTECTED_POSITION,
        ALERT_DIVERGENCE,
        ALERT_FOREIGN_ORDER,
        ALERT_UNKNOWN_ORDER,
        ALERT_STALE_DATA,
    } <= set(ALERT_EVENTS)


def test_the_policy_table_cannot_be_edited() -> None:
    with pytest.raises(TypeError):
        POLICY_BY_KIND["FOREIGN_ORDER"] = POLICY_BY_KIND["ORPHAN_PROTECTIVE"]  # type: ignore[index]


# --------------------------------------------------------------------------- #
# derive_local_intent: one case per ProtectionState value.
# --------------------------------------------------------------------------- #


@dataclasses.dataclass(frozen=True)
class StateCase:
    name: str
    state: str
    flags: dict[str, bool]
    orders: tuple[tuple[str, str], ...]  # (client order id, local status)
    algos: tuple[tuple[str, str], ...]  # (client algo id, role)
    position: bool


_OPEN = {"first_fill": False, "stop_confirmed": False, "entry_terminal": False}
_FILLED_ENTRY_OPEN = {"first_fill": True, "stop_confirmed": False, "entry_terminal": False}
_STOP_ENTRY_OPEN = {"first_fill": True, "stop_confirmed": True, "entry_terminal": False}
_STOP_ENTRY_DONE = {"first_fill": True, "stop_confirmed": True, "entry_terminal": True}
_NO_STOP_ENTRY_DONE = {"first_fill": True, "stop_confirmed": False, "entry_terminal": True}
_STOP_LOST = {**_STOP_ENTRY_DONE, "stop_lost": True}
_SL = ((SL_ID, "STOP_LOSS"),)
_ALL_LEGS = ((SL_ID, "STOP_LOSS"), (TP1_ID, "TAKE_PROFIT_1"), (TP2_ID, "TAKE_PROFIT_2"))

CASES: tuple[StateCase, ...] = (
    StateCase("awaiting", "AWAITING_FILL", _OPEN, ((ENTRY_ID, "NEW"),), (), False),
    StateCase("unresolved", "ENTRY_UNRESOLVED", _OPEN, ((ENTRY_ID, "SUBMITTING"),), (), False),
    StateCase(
        "unprotected",
        "UNPROTECTED",
        _FILLED_ENTRY_OPEN,
        ((ENTRY_ID, "PARTIALLY_FILLED"),),
        (),
        True,
    ),
    StateCase("unprotected-stop-lost", "UNPROTECTED", _STOP_LOST, (), (), True),
    StateCase(
        "protected-entry-open",
        "PROTECTED_ENTRY_OPEN",
        _STOP_ENTRY_OPEN,
        ((ENTRY_ID, "PARTIALLY_FILLED"),),
        _SL,
        True,
    ),
    StateCase("protected", "PROTECTED", _STOP_ENTRY_DONE, (), _SL, True),
    StateCase("complete", "COMPLETE", _STOP_ENTRY_DONE, (), _ALL_LEGS, True),
    StateCase("tp-unavailable", "TP_UNAVAILABLE", _STOP_ENTRY_DONE, (), _SL, True),
    StateCase("close-required-no-stop", "CLOSE_REQUIRED", _NO_STOP_ENTRY_DONE, (), (), True),
    StateCase("close-required-stop", "CLOSE_REQUIRED", _STOP_ENTRY_DONE, (), _SL, True),
    StateCase("close-failed", "CLOSE_FAILED", _NO_STOP_ENTRY_DONE, (), (), True),
    StateCase("flat", "FLAT", _STOP_ENTRY_DONE, (), (), False),
    StateCase("no-fill", "ENTRY_ENDED_NO_FILL", _OPEN, (), (), False),
)


def _plan(case: StateCase, **overrides: Any) -> Any:
    return make_plan_protection(H1, state=case.state, **{**case.flags, **overrides})


def _summary(local: LocalIntent) -> tuple[Any, ...]:
    return (
        tuple((o.client_order_id, o.status) for o in local.orders),
        tuple((a.client_algo_id, a.order_role) for a in local.algos),
        len(local.positions),
    )


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_each_protection_state_contributes_the_planned_local_intent(case: StateCase) -> None:
    local = derive_local_intent([_plan(case)], [])

    orders, algos, position_count = _summary(local)
    assert orders == case.orders
    assert tuple(sorted(algos)) == tuple(sorted(case.algos))
    assert position_count == (1 if case.position else 0)
    assert all(o.order_role == "ENTRY" for o in local.orders)
    assert all(o.plan_hash == H1 for o in local.orders)
    assert all(a.plan_hash == H1 and a.status == "NEW" for a in local.algos)


def test_every_protection_state_is_covered() -> None:
    names = {state.value for state in ProtectionState}
    assert set(STATE_RULES) == names
    assert {case.state for case in CASES} == names


def test_a_position_intent_carries_what_compare_v2_needs() -> None:
    case = next(c for c in CASES if c.name == "protected")
    (position,) = derive_local_intent([_plan(case)], []).positions

    assert position.symbol == "BTCUSDT"
    assert position.position_side == "BOTH"
    assert position.position_amt == Decimal("0.004")
    assert position.plan_hash == H1
    assert position.expected_side == "LONG"
    assert position.max_abs_amount == Decimal("0.004")


def test_a_short_plan_carries_a_negative_amount_and_a_positive_bound() -> None:
    case = next(c for c in CASES if c.name == "protected")
    (position,) = derive_local_intent([_plan(case, side="SHORT")], []).positions

    assert position.position_amt == Decimal("-0.004")
    assert position.expected_side == "SHORT"
    assert position.max_abs_amount == Decimal("0.004")


@pytest.mark.parametrize("side", ["BUY", "", None])
def test_an_unusable_side_stays_none_and_compare_reads_the_owner_as_ambiguous(
    side: str | None,
) -> None:
    case = next(c for c in CASES if c.name == "protected")
    plan = dataclasses.replace(_plan(case), side=side)
    local = derive_local_intent([plan], [])

    assert local.positions[0].expected_side is None
    diff = compare(
        **local.compare_kwargs(),
        truth_normal_orders=[],
        truth_algo_orders=[make_algo_order(SL_ID, "BTCUSDT")],
        truth_positions=[make_position("BTCUSDT", "0.004")],
    )
    assert [d.kind for d in diff.divergences] == ["AMBIGUOUS_POSITION_OWNER"]


def test_a_missing_quantity_leaves_the_bound_none_and_fails_closed_in_compare() -> None:
    case = next(c for c in CASES if c.name == "protected")
    plan = dataclasses.replace(_plan(case), entry_quantity=None)
    local = derive_local_intent([plan], [])

    assert local.positions[0].max_abs_amount is None
    diff = compare(
        **local.compare_kwargs(),
        truth_normal_orders=[],
        truth_algo_orders=[make_algo_order(SL_ID, "BTCUSDT")],
        truth_positions=[make_position("BTCUSDT", "0.004")],
    )
    assert [d.kind for d in diff.divergences] == ["AMBIGUOUS_POSITION_OWNER"]


def test_an_unknown_protection_state_raises_value_error() -> None:
    odd = dataclasses.replace(make_plan_protection(H1), state="NOT_A_STATE")
    with pytest.raises(ValueError, match="unknown protection state"):
        derive_local_intent([odd], [])


# --------------------------------------------------------------------------- #
# Unresolved intent rows.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("status", ["SENT", "UNKNOWN"])
def test_a_sent_or_unknown_stop_row_adds_a_local_algo_intent(status: str) -> None:
    row = make_intent_record(H1, "STOP_LOSS", status=status)
    local = derive_local_intent([], [row])

    assert [(a.client_algo_id, a.order_role, a.status) for a in local.algos] == [
        (SL_ID, "STOP_LOSS", "SUBMITTING")
    ]
    assert local.orders == () and local.positions == ()


@pytest.mark.parametrize("status", ["SENT", "UNKNOWN"])
def test_a_sent_or_unknown_entry_row_adds_a_local_order_intent(status: str) -> None:
    row = make_intent_record(H1, "ENTRY", status=status)
    local = derive_local_intent([], [row])

    assert [(o.client_order_id, o.order_role, o.status) for o in local.orders] == [
        (ENTRY_ID, "ENTRY", "SUBMITTING")
    ]
    assert local.algos == ()


@pytest.mark.parametrize("role", ["ENTRY", "STOP_LOSS", "TAKE_PROFIT_1", "TAKE_PROFIT_2"])
def test_an_intended_row_adds_nothing_because_nothing_was_sent(role: str) -> None:
    local = derive_local_intent([], [make_intent_record(H1, role, status="INTENDED")])
    assert local.orders == () and local.algos == ()


def test_a_row_without_stored_ids_uses_the_deterministic_ones() -> None:
    entry = dataclasses.replace(make_intent_record(H1, "ENTRY"), client_order_id=None)
    stop = dataclasses.replace(make_intent_record(H1, "STOP_LOSS"), algo_client_id=None)
    local = derive_local_intent([], [entry, stop])

    assert [o.client_order_id for o in local.orders] == [ENTRY_ID]
    assert [a.client_algo_id for a in local.algos] == [SL_ID]


def test_a_plan_entry_and_its_sent_row_make_one_order() -> None:
    case = next(c for c in CASES if c.name == "awaiting")
    local = derive_local_intent([_plan(case)], [make_intent_record(H1, "ENTRY")])

    assert [(o.client_order_id, o.status) for o in local.orders] == [(ENTRY_ID, "NEW")]


def test_an_unknown_intent_role_raises_value_error() -> None:
    row = dataclasses.replace(make_intent_record(H1, "ENTRY"), role="CLOSE_ALL")
    with pytest.raises(ValueError, match="unknown intent role"):
        derive_local_intent([], [row])


def test_a_sent_stop_row_keeps_a_stop_that_may_exist_from_being_foreign() -> None:
    plan = make_plan_protection(H1, state="UNPROTECTED", **_FILLED_ENTRY_OPEN)
    exchange = {
        "truth_normal_orders": [make_open_order(ENTRY_ID, "BTCUSDT")],
        "truth_algo_orders": [make_algo_order(SL_ID, "BTCUSDT")],
        "truth_positions": [make_position("BTCUSDT", "0.004")],
    }

    without_row = compare(**derive_local_intent([plan], []).compare_kwargs(), **exchange)
    with_row = compare(
        **derive_local_intent(
            [plan], [make_intent_record(H1, "STOP_LOSS", status="SENT")]
        ).compare_kwargs(),
        **exchange,
    )

    assert "UNTRACKED_SYSTEM_ORDER" in [d.kind for d in without_row.divergences]
    assert [d.kind for d in with_row.divergences] == []


# --------------------------------------------------------------------------- #
# Determinism and the compare seam.
# --------------------------------------------------------------------------- #


def test_the_result_does_not_depend_on_the_input_order() -> None:
    first = make_plan_protection(H1, symbol="BTCUSDT", state="PROTECTED")
    second = make_plan_protection(H2, symbol="ETHUSDT", state="COMPLETE")
    rows = [make_intent_record(H1, "TAKE_PROFIT_1"), make_intent_record(H2, "ENTRY")]

    forward = derive_local_intent([first, second], rows)
    backward = derive_local_intent([second, first], list(reversed(rows)))

    assert forward == backward


def test_compare_kwargs_names_exactly_the_local_inputs_of_compare() -> None:
    kwargs = derive_local_intent([], []).compare_kwargs()
    # Plan 20-20 added local_active_plans (symbol ownership, owner decision O-D).
    assert set(kwargs) == {
        "local_open_orders",
        "local_open_algos",
        "local_open_positions",
        "local_active_plans",
    }
    assert all(isinstance(value, tuple) for value in kwargs.values())


def test_a_quiet_protected_plan_that_the_exchange_mirrors_is_agreement() -> None:
    case = next(c for c in CASES if c.name == "complete")
    local = derive_local_intent([_plan(case)], [])
    diff = compare(
        **local.compare_kwargs(),
        truth_normal_orders=[],
        truth_algo_orders=[make_algo_order(i, "BTCUSDT") for i in (SL_ID, TP1_ID, TP2_ID)],
        truth_positions=[make_position("BTCUSDT", "0.004")],
    )
    assert diff.agreement is True


# --------------------------------------------------------------------------- #
# A resting entry that has had no fill (plan 20-31, W1; D079, D-10).
#
# Since Phase 19 the stop is placed only AFTER a fill, so an entry that rests unfilled is the
# normal state of an approved plan, not a divergence. Fail closed stays: any sign of a fill, or a
# fill state the local side does not know, is still ENTRY_WITHOUT_PROTECTIVE.
# --------------------------------------------------------------------------- #


def _kinds(diff: Any) -> list[str]:
    return [d.kind for d in diff.divergences]


def _awaiting_compare(**exchange: Any) -> Any:
    case = next(c for c in CASES if c.name == "awaiting")
    local = derive_local_intent([_plan(case)], [])
    return compare(
        **local.compare_kwargs(),
        **{"truth_normal_orders": [], "truth_algo_orders": [], "truth_positions": [], **exchange},
    )


def test_a_resting_entry_with_no_fill_is_agreement() -> None:
    diff = _awaiting_compare(truth_normal_orders=[make_open_order(ENTRY_ID, "BTCUSDT")])

    assert diff.agreement is True
    assert _kinds(diff) == []


def test_a_zero_amount_exchange_row_is_not_a_fill() -> None:
    diff = _awaiting_compare(
        truth_normal_orders=[make_open_order(ENTRY_ID, "BTCUSDT")],
        truth_positions=[make_position("BTCUSDT", "0")],
    )

    assert diff.agreement is True


async def test_a_tick_over_a_resting_unfilled_entry_enters_no_safe_mode_and_alerts_nothing() -> (
    None
):
    awaiting = _plan(next(c for c in CASES if c.name == "awaiting"))
    rig = build_rig(plans=(awaiting,), normal=(make_open_order(ENTRY_ID, "BTCUSDT"),))

    report = await rig.loop.tick(now_utc=NOW)

    assert report.agreement is True
    assert report.safe_mode_reasons == ()
    assert rig.safe_mode.enter_calls == []
    assert [a for a in rig.alerts.alerts if a.event == ALERT_UNPROTECTED_POSITION] == []
    assert rig.alerts.alerts == []
    assert report.delegated == () and report.undelegated == ()


async def test_a_tick_over_a_filled_entry_without_a_stop_still_alerts_and_enters_safe_mode() -> (
    None
):
    awaiting = _plan(next(c for c in CASES if c.name == "awaiting"))
    rig = build_rig(
        plans=(awaiting,),
        normal=(make_open_order(ENTRY_ID, "BTCUSDT"),),
        positions=(make_position("BTCUSDT", "0.004"),),
    )

    report = await rig.loop.tick(now_utc=NOW)

    assert report.agreement is False
    assert "ENTRY_WITHOUT_PROTECTIVE" in [d.kind for d in report.divergences]
    assert "ENTRY_WITHOUT_PROTECTIVE" in report.safe_mode_reasons
    assert ALERT_UNPROTECTED_POSITION in {a.event for a in rig.alerts.alerts}


def test_a_resting_entry_with_an_exchange_position_on_the_symbol_is_still_flagged() -> None:
    """The entry may have filled between two reads: a position on the symbol is exposure."""
    diff = _awaiting_compare(
        truth_normal_orders=[make_open_order(ENTRY_ID, "BTCUSDT")],
        truth_positions=[make_position("BTCUSDT", "0.004")],
    )

    assert "ENTRY_WITHOUT_PROTECTIVE" in _kinds(diff)
    assert diff.agreement is False


def test_a_position_on_another_symbol_does_not_make_the_entry_filled() -> None:
    diff = _awaiting_compare(
        truth_normal_orders=[make_open_order(ENTRY_ID, "BTCUSDT")],
        truth_positions=[make_position("ETHUSDT", "0.5")],
    )

    assert "ENTRY_WITHOUT_PROTECTIVE" not in _kinds(diff)


@pytest.mark.parametrize("status", ["PARTIALLY_FILLED", "FILLED", "UNKNOWN", ""])
def test_an_entry_that_the_exchange_shows_with_any_status_but_new_is_still_flagged(
    status: str,
) -> None:
    diff = _awaiting_compare(
        truth_normal_orders=[make_open_order(ENTRY_ID, "BTCUSDT", status=status)]
    )

    assert "ENTRY_WITHOUT_PROTECTIVE" in _kinds(diff)


def test_an_awaiting_entry_missing_on_the_exchange_keeps_both_divergences() -> None:
    """Gone from the book is no proof of "no fill" (it may have filled, expired or been
    cancelled): UNSYNCED_NORMAL stays and so does ENTRY_WITHOUT_PROTECTIVE (test_phase8 WR-13)."""
    diff = _awaiting_compare()

    assert set(_kinds(diff)) == {"UNSYNCED_NORMAL", "ENTRY_WITHOUT_PROTECTIVE"}
    assert diff.agreement is False


def test_an_awaiting_entry_missing_on_the_exchange_with_a_position_is_flagged_too() -> None:
    diff = _awaiting_compare(truth_positions=[make_position("BTCUSDT", "0.004")])

    assert "ENTRY_WITHOUT_PROTECTIVE" in _kinds(diff)
    assert "UNSYNCED_NORMAL" in _kinds(diff)


def test_an_unresolved_entry_may_have_filled_and_is_still_flagged() -> None:
    """ENTRY_UNRESOLVED (SUBMITTING) and a SENT row: the fill state is unknown."""
    case = next(c for c in CASES if c.name == "unresolved")
    for local in (
        derive_local_intent([_plan(case)], []),
        derive_local_intent([], [make_intent_record(H1, "ENTRY", status="SENT")]),
    ):
        diff = compare(
            **local.compare_kwargs(),
            truth_normal_orders=[make_open_order(ENTRY_ID, "BTCUSDT")],
            truth_algo_orders=[],
            truth_positions=[],
        )
        assert "ENTRY_WITHOUT_PROTECTIVE" in _kinds(diff)


@pytest.mark.parametrize("status", ["PARTIALLY_FILLED", "SUBMITTING", "PLANNED", None])
def test_only_a_local_status_of_new_means_no_fill(status: str | None) -> None:
    entry = {
        "client_order_id": ENTRY_ID,
        "symbol": "BTCUSDT",
        "order_role": "ENTRY",
        "status": status,
        "plan_hash": H1,
    }
    diff = compare(
        local_open_orders=[entry],
        local_open_algos=[],
        local_open_positions=[],
        truth_normal_orders=[make_open_order(ENTRY_ID, "BTCUSDT")],
        truth_algo_orders=[],
        truth_positions=[],
    )

    assert "ENTRY_WITHOUT_PROTECTIVE" in _kinds(diff)


def test_a_local_position_intent_on_the_symbol_means_the_entry_may_have_filled() -> None:
    case = next(c for c in CASES if c.name == "awaiting")
    local = derive_local_intent([_plan(case)], [])
    other = derive_local_intent(
        [_plan(next(c for c in CASES if c.name == "protected"), symbol="BTCUSDT")], []
    )
    diff = compare(
        local_open_orders=local.orders,
        local_open_algos=(),
        local_open_positions=other.positions,
        truth_normal_orders=[make_open_order(ENTRY_ID, "BTCUSDT")],
        truth_algo_orders=[],
        truth_positions=[],
    )

    assert "ENTRY_WITHOUT_PROTECTIVE" in _kinds(diff)


def test_a_resting_entry_next_to_a_protected_plan_on_another_symbol_agrees() -> None:
    awaiting = _plan(next(c for c in CASES if c.name == "awaiting"))
    protected = make_plan_protection(
        H2, symbol="ETHUSDT", state="PROTECTED", side="LONG", quantity="0.5"
    )
    stop_id = derive_algo_client_id(plan_hash=H2, role=OrderRole.STOP_LOSS.value)
    local = derive_local_intent([awaiting, protected], [])
    diff = compare(
        **local.compare_kwargs(),
        truth_normal_orders=[make_open_order(ENTRY_ID, "BTCUSDT")],
        truth_algo_orders=[make_algo_order(stop_id, "ETHUSDT")],
        truth_positions=[make_position("ETHUSDT", "0.5")],
    )

    assert diff.agreement is True
