"""D-05 snapshot test (Phase 22, plan 22-15; G4-039, amendment A8, 22-NOTES.md).

`attach_protectives_to_fill` places take-profit orders only when `snapshot_is_valid_for_live`
holds for the plan snapshot the entry handed to the protection coordinator. Phase 21 supplied the
equity (`tests/test_snapshot_live_equity.py`); this file shows that the margin type, leverage and
equity the Phase 22 guard VERIFIED on the exchange complete that snapshot, and that it stays
invalid when any of the three is unknown.

The verdict is a real one: the recorded Demo account (CROSSED x20, equity 4999.09343961) goes
through the plan 22-14 composite rig (real adapter, equity source, configuration guard and bracket
cache) and ends with ISOLATED x5. Demo-observed payloads, not mainnet.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from src.domain.enums import LiveInputsStatus
from src.execution.constraint_snapshot import (
    PlanConstraintSnapshot,
    build_plan_constraint_snapshot,
    snapshot_is_valid_for_live,
)
from src.execution.margin_guard import MarginGuardVerdict

from tests.support.margin_guard_fakes import build_rig, request
from tests.support.margin_guard_stub import StubMarginGuard
from tests.test_execution_manager import (
    FakeExecutionAdapter,
    StubProtectionRegistry,
    _build_live_context,
    _filled_plan_snapshot,
    _load_input,
    _parse_utc,
    _run_plan,
)
from tests.test_snapshot_live_equity import (
    OBSERVED,
    TTL,
    _constraints,
    _extras,
)

DEMO_EQUITY = Decimal("4999.09343961")


async def _real_verdict() -> MarginGuardVerdict:
    verdict = await build_rig().guard.evaluate(request())
    assert verdict.is_no_trade is False
    return verdict


def _base_snapshot() -> PlanConstraintSnapshot:
    """The snapshot as the planner stores it: the seven filter values, no margin side yet."""
    return build_plan_constraint_snapshot(
        "plan-1",
        _constraints(),
        _extras(),
        Decimal("1000"),
        "MARK_PRICE",
        captured_at_utc=OBSERVED,
    )


def _completed(verdict: MarginGuardVerdict, **overrides: Any) -> PlanConstraintSnapshot:
    values: dict[str, Any] = {
        "margin_type": verdict.margin_type,
        "leverage": verdict.leverage,
        "equity_used": verdict.equity_used,
    }
    values.update(overrides)
    return dataclasses.replace(_base_snapshot(), **values)


async def test_the_guard_verified_values_complete_the_snapshot_and_make_it_valid_for_live() -> None:
    verdict = await _real_verdict()
    assert (verdict.margin_type, verdict.leverage, verdict.equity_used) == (
        "ISOLATED",
        5,
        DEMO_EQUITY,
    )
    base = _base_snapshot()
    assert base.live_inputs_status is LiveInputsStatus.INCOMPLETE
    assert snapshot_is_valid_for_live(base, now_utc=OBSERVED, ttl=TTL) is False

    snapshot = _completed(verdict)
    assert snapshot.live_inputs_status is LiveInputsStatus.COMPLETE
    # Exactly the TTL after the exchangeInfo capture is still valid (the bound is inclusive).
    assert snapshot_is_valid_for_live(snapshot, now_utc=OBSERVED, ttl=TTL) is True
    assert snapshot_is_valid_for_live(snapshot, now_utc=OBSERVED + TTL, ttl=TTL) is True
    assert (
        snapshot_is_valid_for_live(
            snapshot, now_utc=OBSERVED + TTL + timedelta(milliseconds=1), ttl=TTL
        )
        is False
    )


@pytest.mark.parametrize("missing", ["margin_type", "leverage", "equity_used"])
async def test_a_snapshot_missing_any_of_the_three_verified_values_is_not_valid_for_live(
    missing: str,
) -> None:
    snapshot = _completed(await _real_verdict(), **{missing: None})
    assert snapshot.live_inputs_status is LiveInputsStatus.INCOMPLETE
    assert snapshot_is_valid_for_live(snapshot, now_utc=OBSERVED, ttl=TTL) is False


async def test_the_unknown_sentinel_margin_type_cannot_reach_a_snapshot() -> None:
    with pytest.raises(ValueError):
        _completed(await _real_verdict(), margin_type="UNKNOWN")


async def test_a_manager_placement_with_a_real_verdict_hands_protection_a_valid_snapshot() -> None:
    """The whole seam: real verdict -> gate 5f2 -> RestingEntry snapshot valid for live, while the
    context's own (write-once evidence) snapshot stays INCOMPLETE."""
    verdict = await _real_verdict()
    case_input = _load_input()
    base = _filled_plan_snapshot(case_input)
    registry = StubProtectionRegistry()
    context = _build_live_context(
        case_input,
        plan_constraint_snapshot=base,
        protection_registry=registry,
        margin_guard=StubMarginGuard(verdict=verdict),
    )
    outcome = await _run_plan(FakeExecutionAdapter(), live_context=context)
    assert (outcome.is_no_trade, outcome.reason_code) == (False, "OK")

    handed = registry.entries[0].plan_constraint_snapshot
    now = _parse_utc(case_input["now_utc"])
    ttl = timedelta(seconds=int(case_input["ttl_seconds"]))
    assert (handed.margin_type, handed.leverage, handed.equity_used) == (
        "ISOLATED",
        5,
        DEMO_EQUITY,
    )
    assert handed.live_inputs_status is LiveInputsStatus.COMPLETE
    assert snapshot_is_valid_for_live(handed, now_utc=now, ttl=ttl) is True
    assert context.plan_constraint_snapshot is base
    assert base.live_inputs_status is LiveInputsStatus.INCOMPLETE
    assert snapshot_is_valid_for_live(base, now_utc=now, ttl=ttl) is False
