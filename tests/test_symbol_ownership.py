"""Symbol-ownership invariant (Phase 20, plan 20-20, T-F, owner decision O-D, EXEC-02).

The D-01a bound check is per symbol, so it equals a per-plan check only while one plan owns a
symbol. Reconciliation therefore treats more than one active plan on one symbol, or exposure whose
owning plan cannot be determined, as a divergence (AMBIGUOUS_POSITION_OWNER) that enters SAFE_MODE
with its own reason SYMBOL_OWNERSHIP_CONFLICT. It never closes anything by itself, never picks one
of two candidate owners and adds no plan-ingress rejection (the policy is the owner's O-D answer,
not D-13).

Evidence label: executed unit tests with fakes. Nothing here touches Binance, Telegram or a
database, and nothing is a Demo observation.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.domain.enums import OrderRole
from src.execution.order_ids import derive_client_order_id
from src.execution.protection import ProtectionState
from src.reconcile.classify import (
    ALERT_DIVERGENCE,
    POLICY_BY_KIND,
    SAFE_MODE_SYMBOL_OWNERSHIP_CONFLICT,
    DivergenceAction,
    classify,
)
from src.reconcile.compare import (
    DIVERGENCE_KIND_AMBIGUOUS_POSITION_OWNER,
    LocalActivePlan,
    LocalPositionIntent,
    compare,
)
from src.reconcile.local_intent import derive_local_intent
from src.reconcile.loop import (
    RECONCILE_SKIPPED_RESTORE_PENDING,
    SAFE_MODE_DB_FAILURE,
    TICK_COMPARED,
    TICK_READ_FAILED,
    TICK_SKIPPED_RESTORE_PENDING,
    ReconcileLoop,
)

from tests.support.execution_limits import test_only_execution_limits as make_test_limits
from tests.support.protection_doubles import make_rig as make_protection_rig
from tests.support.reconcile_doubles import (
    FakeGate,
    FakeIntentStore,
    FakeProtectionView,
    FakeReconcileAdapter,
    InMemorySafeModeStore,
    RecordingAlertSink,
    RecordingJournal,
    make_intent_record,
    make_open_order,
    make_plan_protection,
    make_position,
)
from tests.support.reconcile_rig import NoopSweeper, SpyingSafeMode

NOW = datetime(2026, 9, 19, 0, 0, tzinfo=UTC)
H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
REPO = Path(__file__).parent.parent
CONFLICT = "SYMBOL_OWNERSHIP_CONFLICT"
AMBIGUOUS = "AMBIGUOUS_POSITION_OWNER"


def _awaiting(plan_hash: str, symbol: str = "BTCUSDT") -> Any:
    return make_plan_protection(
        plan_hash,
        symbol=symbol,
        state="AWAITING_FILL",
        first_fill=False,
        stop_confirmed=False,
        entry_terminal=False,
    )


def _entry_id(plan_hash: str) -> str:
    return derive_client_order_id(plan_hash=plan_hash, role=OrderRole.ENTRY.value)


def _kinds(diff: Any) -> list[str]:
    return [d.kind for d in diff.divergences]


class _Rig:
    def __init__(self, loop: ReconcileLoop, **parts: Any) -> None:
        self.loop = loop
        self.__dict__.update(parts)


def _make_rig(
    *,
    plans: tuple[Any, ...] = (),
    normal: tuple[Any, ...] = (),
    positions: tuple[Any, ...] = (),
    intents: Any = None,
    protection: Any = None,
) -> _Rig:
    adapter = FakeReconcileAdapter(normal_orders=normal, algo_orders=(), positions=positions)
    safe_mode = SpyingSafeMode(
        adapter=adapter, journal=RecordingJournal(), state_store=InMemorySafeModeStore()
    )
    view = protection or FakeProtectionView(plans)
    alerts = RecordingAlertSink()
    journal = RecordingJournal()
    loop = ReconcileLoop(
        adapter=adapter,
        gate=FakeGate(),
        safe_mode=safe_mode,
        intent_store=intents if intents is not None else FakeIntentStore(),
        protection=view,
        sweeper=NoopSweeper(),
        alerts=alerts,
        journal=journal,
        limits=make_test_limits(),
    )
    return _Rig(
        loop,
        adapter=adapter,
        safe_mode=safe_mode,
        protection=view,
        alerts=alerts,
        journal=journal,
    )


def _empty_compare(**overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "local_open_orders": [],
        "local_open_algos": [],
        "local_open_positions": [],
        "truth_normal_orders": [],
        "truth_algo_orders": [],
        "truth_positions": [],
    }
    kwargs.update(overrides)
    return compare(**kwargs)


# --------------------------------------------------------------------------- #
# Task 2 (tracer): one tick, two tracked plans on one symbol.
# --------------------------------------------------------------------------- #


async def test_two_active_plans_on_one_symbol_enter_safe_mode() -> None:
    rig = _make_rig(
        plans=(_awaiting(H1), _awaiting(H2)),
        normal=(
            make_open_order(_entry_id(H1), "BTCUSDT"),
            make_open_order(_entry_id(H2), "BTCUSDT"),
        ),
    )

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_COMPARED
    owner = [d for d in report.divergences if d.kind == AMBIGUOUS]
    assert [d.symbol for d in owner] == ["BTCUSDT"]
    assert CONFLICT in rig.safe_mode.enter_calls
    assert CONFLICT in report.safe_mode_reasons
    assert rig.safe_mode.in_safe_mode is True
    assert ("DIVERGENCE", "BTCUSDT", AMBIGUOUS) in [
        (a.event, a.subject, a.reason) for a in rig.alerts.alerts
    ]


async def test_two_active_plans_on_one_symbol_never_delegate_or_close() -> None:
    rig = _make_rig(
        plans=(_awaiting(H1), _awaiting(H2)),
        normal=(
            make_open_order(_entry_id(H1), "BTCUSDT"),
            make_open_order(_entry_id(H2), "BTCUSDT"),
        ),
    )

    report = await rig.loop.tick(now_utc=NOW)

    # No coordinator notification for either plan, no close and no cancel: the policy is
    # alert-only for the ownership conflict (no owner is guessed).
    assert not any(kind == AMBIGUOUS for _plan, kind in rig.protection.notified)
    assert not any(kind == AMBIGUOUS for _plan, kind in report.delegated)
    assert "CLOSE_REQUIRED" not in rig.safe_mode.enter_calls
    assert rig.adapter.cancelled_normal == []
    assert rig.adapter.cancelled_algo == []
    assert rig.adapter.forbidden_calls == []


async def test_one_plan_on_btc_and_one_on_eth_have_no_ownership_divergence() -> None:
    rig = _make_rig(
        plans=(_awaiting(H1, "BTCUSDT"), _awaiting(H2, "ETHUSDT")),
        normal=(
            make_open_order(_entry_id(H1), "BTCUSDT"),
            make_open_order(_entry_id(H2), "ETHUSDT"),
        ),
    )

    report = await rig.loop.tick(now_utc=NOW)

    assert AMBIGUOUS not in [d.kind for d in report.divergences]
    assert CONFLICT not in rig.safe_mode.enter_calls


@pytest.mark.parametrize("inactive_state", ["FLAT", "ENTRY_ENDED_NO_FILL"])
async def test_a_second_plan_that_is_not_active_is_no_conflict(inactive_state: str) -> None:
    ended = make_plan_protection(
        H2, symbol="BTCUSDT", state=inactive_state, stop_confirmed=False, entry_terminal=True
    )
    rig = _make_rig(
        plans=(_awaiting(H1), ended),
        normal=(make_open_order(_entry_id(H1), "BTCUSDT"),),
    )

    report = await rig.loop.tick(now_utc=NOW)

    assert AMBIGUOUS not in [d.kind for d in report.divergences]
    assert CONFLICT not in rig.safe_mode.enter_calls


# --------------------------------------------------------------------------- #
# compare: the local_active_plans input.
# --------------------------------------------------------------------------- #


def test_compare_without_local_active_plans_is_unchanged() -> None:
    assert _empty_compare().agreement is True


def test_compare_emits_one_ambiguous_owner_per_symbol_with_two_distinct_plans() -> None:
    diff = _empty_compare(
        local_active_plans=[
            LocalActivePlan(plan_hash=H1, symbol="BTCUSDT"),
            LocalActivePlan(plan_hash=H2, symbol="BTCUSDT"),
            LocalActivePlan(plan_hash=H3, symbol="BTCUSDT"),
            LocalActivePlan(plan_hash=H1, symbol="ETHUSDT"),
        ]
    )

    assert _kinds(diff) == [DIVERGENCE_KIND_AMBIGUOUS_POSITION_OWNER]
    assert diff.divergences[0].symbol == "BTCUSDT"
    assert diff.orphan_protectives == ()


def test_compare_the_same_plan_listed_twice_is_not_a_conflict() -> None:
    diff = _empty_compare(
        local_active_plans=[
            LocalActivePlan(plan_hash=H1, symbol="BTCUSDT"),
            {"plan_hash": H1, "symbol": "BTCUSDT"},
        ]
    )

    assert diff.agreement is True


def test_compare_accepts_dict_style_items_like_the_other_carriers() -> None:
    diff = _empty_compare(
        local_active_plans=[
            {"plan_hash": H1, "symbol": "BTCUSDT"},
            {"plan_hash": H2, "symbol": "BTCUSDT"},
        ]
    )

    assert _kinds(diff) == [DIVERGENCE_KIND_AMBIGUOUS_POSITION_OWNER]


@pytest.mark.parametrize(
    "bad",
    [
        {"plan_hash": None, "symbol": "BTCUSDT"},
        {"plan_hash": "", "symbol": "BTCUSDT"},
        {"plan_hash": H1, "symbol": ""},
        {"plan_hash": H1, "symbol": None},
    ],
)
def test_compare_an_active_plan_that_cannot_be_named_fails_closed(bad: dict[str, Any]) -> None:
    diff = _empty_compare(local_active_plans=[bad])

    assert _kinds(diff) == [DIVERGENCE_KIND_AMBIGUOUS_POSITION_OWNER]


def test_compare_none_for_local_active_plans_raises_like_the_other_sources() -> None:
    with pytest.raises(TypeError, match="local_active_plans"):
        _empty_compare(local_active_plans=None)


def test_compare_exposure_with_two_owners_and_two_active_plans_yields_one_divergence() -> None:
    local_positions = [
        LocalPositionIntent(
            symbol="BTCUSDT",
            position_side="BOTH",
            position_amt=Decimal("0.004"),
            plan_hash=plan,
            expected_side="LONG",
            max_abs_amount=Decimal("0.004"),
        )
        for plan in (H1, H2)
    ]
    diff = _empty_compare(
        local_open_positions=local_positions,
        truth_positions=[make_position("BTCUSDT", "0.004")],
        local_active_plans=[
            LocalActivePlan(plan_hash=H1, symbol="BTCUSDT"),
            LocalActivePlan(plan_hash=H2, symbol="BTCUSDT"),
        ],
    )

    assert _kinds(diff).count(AMBIGUOUS) == 1


# --------------------------------------------------------------------------- #
# local_intent: which plans are active.
# --------------------------------------------------------------------------- #


def test_active_plans_are_every_tracked_plan_that_is_not_flat_or_ended_without_fill() -> None:
    plans = [
        _awaiting(H1),
        make_plan_protection(H2, symbol="ETHUSDT", state="PROTECTED"),
        make_plan_protection(H3, symbol="BTCUSDT", state="FLAT", stop_confirmed=False),
        make_plan_protection("4" * 64, symbol="SOLUSDT", state="ENTRY_ENDED_NO_FILL"),
    ]

    local = derive_local_intent(plans, [])

    assert [(p.symbol, p.plan_hash) for p in local.active_plans] == [
        ("BTCUSDT", H1),
        ("ETHUSDT", H2),
    ]
    assert local.compare_kwargs()["local_active_plans"] == local.active_plans


def test_a_plan_named_only_by_an_unresolved_entry_intent_is_active() -> None:
    entry = make_intent_record(H2, OrderRole.ENTRY.value, status="UNKNOWN", symbol="BTCUSDT")

    local = derive_local_intent([_awaiting(H1)], [entry])

    assert [(p.symbol, p.plan_hash) for p in local.active_plans] == [
        ("BTCUSDT", H1),
        ("BTCUSDT", H2),
    ]


def test_an_unresolved_entry_of_a_tracked_plan_is_counted_once() -> None:
    entry = make_intent_record(H1, OrderRole.ENTRY.value, status="SENT")

    local = derive_local_intent([_awaiting(H1)], [entry])

    assert len(local.active_plans) == 1


def test_an_intended_entry_and_a_protective_leg_alone_name_no_active_plan() -> None:
    intended = make_intent_record(H2, OrderRole.ENTRY.value, status="INTENDED")
    stop_only = make_intent_record(H3, OrderRole.STOP_LOSS.value, status="SENT")

    local = derive_local_intent([], [intended, stop_only])

    assert local.active_plans == ()


def test_an_unresolved_entry_of_a_tracked_inactive_plan_does_not_reactivate_it() -> None:
    ended = make_plan_protection(H1, state="FLAT", stop_confirmed=False)
    entry = make_intent_record(H1, OrderRole.ENTRY.value, status="SENT")

    local = derive_local_intent([ended], [entry])

    assert local.active_plans == ()


# --------------------------------------------------------------------------- #
# classify.
# --------------------------------------------------------------------------- #


def test_classify_maps_the_ambiguous_owner_to_its_own_reason_and_never_a_close() -> None:
    policy = classify(DIVERGENCE_KIND_AMBIGUOUS_POSITION_OWNER)

    assert policy.safe_mode_reason == CONFLICT == SAFE_MODE_SYMBOL_OWNERSHIP_CONFLICT
    assert policy.alert_event == ALERT_DIVERGENCE
    assert policy.action is DivergenceAction.ALERT_ONLY
    # Only the ambiguous owner carries this reason, and nothing is mapped to a direct close.
    assert [k for k, p in POLICY_BY_KIND.items() if p.safe_mode_reason == CONFLICT] == [AMBIGUOUS]
    assert not any(p.safe_mode_reason == "CLOSE_REQUIRED" for p in POLICY_BY_KIND.values())


# --------------------------------------------------------------------------- #
# Task 3: ambiguous exposure, unreadable or stale local data, D077 on top.
# --------------------------------------------------------------------------- #


async def test_exposure_with_two_candidate_plans_is_a_symbol_ownership_conflict() -> None:
    unprotected = make_plan_protection(
        H1, symbol="BTCUSDT", state="UNPROTECTED", stop_confirmed=False, entry_terminal=False
    )
    rig = _make_rig(
        plans=(unprotected, _awaiting(H2)),
        normal=(make_open_order(_entry_id(H2), "BTCUSDT"),),
        positions=(make_position("BTCUSDT", "0.004"),),
    )

    report = await rig.loop.tick(now_utc=NOW)

    assert [d.symbol for d in report.divergences if d.kind == AMBIGUOUS] == ["BTCUSDT"]
    assert CONFLICT in rig.safe_mode.enter_calls
    assert all(kind != AMBIGUOUS for _plan, kind in rig.protection.notified)
    assert "CLOSE_REQUIRED" not in rig.safe_mode.enter_calls


async def test_the_unprotected_plan_keeps_its_own_d077_deadline_under_a_conflict() -> None:
    """The ownership tick closes nothing: CLOSE_REQUIRED comes only from the plan's own deadline."""
    rig = await make_protection_rig(real_closer=True)
    coordinator = rig.coordinator
    coordinator.fill_sink(rig.stream_fill(Decimal("0.004")))
    await coordinator.step()
    rig.fake.open_algos[rig.stop_id].status = "TRIGGERING"  # UNKNOWN class: never protection
    await coordinator.step()
    own = coordinator.protection_of(rig.entry.plan_hash)
    assert own is not None and own.state is ProtectionState.UNPROTECTED

    class _View:
        """The real coordinator's views plus a second plan on the same symbol."""

        restore_complete = True

        def __init__(self) -> None:
            self.notified: list[tuple[str, str]] = []

        def protections(self) -> tuple[Any, ...]:
            return (*coordinator.protections(), _awaiting(H2, own.symbol))

        def notify_divergence(self, plan_hash: str, kind: str) -> bool:
            self.notified.append((plan_hash, kind))
            return bool(coordinator.notify_divergence(plan_hash, kind))

    view = _View()
    tick_rig = _make_rig(
        protection=view,
        normal=(make_open_order(_entry_id(H2), own.symbol),),
        positions=(make_position(own.symbol, "0.004"),),
    )

    report = await tick_rig.loop.tick(now_utc=NOW)

    assert CONFLICT in tick_rig.safe_mode.enter_calls
    assert all(kind != AMBIGUOUS for _plan, kind in view.notified)
    assert rig.fake.calls_to("place_market_close") == []
    still = coordinator.protection_of(rig.entry.plan_hash)
    assert still is not None and still.state is ProtectionState.UNPROTECTED
    assert report.outcome == TICK_COMPARED

    max_unprotected_ms = 7777  # the TEST_ONLY deadline of tests/support/execution_limits.py
    await rig.clock.advance((max_unprotected_ms - 1) / 1000)
    await coordinator.step()
    before = coordinator.protection_of(rig.entry.plan_hash)
    assert before is not None and before.state is ProtectionState.UNPROTECTED
    assert rig.fake.calls_to("place_market_close") == []

    await rig.clock.advance(1 / 1000)
    await coordinator.step()
    after = coordinator.protection_of(rig.entry.plan_hash)
    assert after is not None and after.state is ProtectionState.CLOSE_REQUIRED


async def test_exposure_with_no_tracked_plan_and_no_unresolved_intent_stays_unsynced() -> None:
    rig = _make_rig(positions=(make_position("BTCUSDT", "0.004"),))

    report = await rig.loop.tick(now_utc=NOW)

    kinds = [d.kind for d in report.divergences]
    assert "UNSYNCED_POSITION" in kinds
    assert AMBIGUOUS not in kinds
    assert CONFLICT not in rig.safe_mode.enter_calls


async def test_an_unreadable_intent_store_is_db_failure_with_no_ownership_decision() -> None:
    rig = _make_rig(
        plans=(_awaiting(H1), _awaiting(H2)),
        intents=FakeIntentStore(raises=RuntimeError("db down")),
    )

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_READ_FAILED
    assert rig.safe_mode.enter_calls == [SAFE_MODE_DB_FAILURE]
    assert CONFLICT not in report.safe_mode_reasons
    assert report.divergences == ()


async def test_an_unreadable_protection_view_is_db_failure_with_no_ownership_decision() -> None:
    view = FakeProtectionView(protections_raises=RuntimeError("view down"))
    rig = _make_rig(protection=view)

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_READ_FAILED
    assert rig.safe_mode.enter_calls == [SAFE_MODE_DB_FAILURE]
    assert report.divergences == ()


async def test_a_coordinator_whose_restore_is_not_complete_skips_the_tick() -> None:
    view = FakeProtectionView((_awaiting(H1), _awaiting(H2)), restore_complete=False)
    rig = _make_rig(protection=view)

    report = await rig.loop.tick(now_utc=NOW)

    assert report.outcome == TICK_SKIPPED_RESTORE_PENDING
    assert RECONCILE_SKIPPED_RESTORE_PENDING in [e.event_type for e in rig.journal.events]
    assert rig.safe_mode.enter_calls == []
    assert report.divergences == ()
    assert view.protections_calls == 0


async def test_an_untracked_unresolved_entry_on_a_tracked_symbol_is_a_conflict() -> None:
    entry = make_intent_record(H2, OrderRole.ENTRY.value, status="UNKNOWN", symbol="BTCUSDT")
    rig = _make_rig(
        plans=(_awaiting(H1),),
        normal=(make_open_order(_entry_id(H1), "BTCUSDT"),),
        intents=FakeIntentStore([entry]),
    )

    report = await rig.loop.tick(now_utc=NOW)

    assert AMBIGUOUS in [d.kind for d in report.divergences]
    assert CONFLICT in rig.safe_mode.enter_calls


# --------------------------------------------------------------------------- #
# Scope guards and documentation.
# --------------------------------------------------------------------------- #


def test_glossary_94_has_exactly_one_symbol_ownership_conflict_row() -> None:
    text = (REPO / "docs" / "GLOSSARY.md").read_bytes().decode("utf-8")
    section = text.split("### 9.4 SAFE_MODE entry reasons", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith(f"| `{CONFLICT}`")]
    assert len(rows) == 1
    assert "src/reconcile/classify.py" in rows[0]
    assert "src/reconcile/loop.py" in rows[0]
    assert "O-D" in rows[0]
    assert "D-13" in rows[0]  # named only to say the policy is not a D-13 decision
    assert text.count(CONFLICT) == 1


def test_the_local_active_plan_carrier_is_frozen() -> None:
    plan = LocalActivePlan(plan_hash=H1, symbol="BTCUSDT")
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.symbol = "ETHUSDT"  # type: ignore[misc]
