"""S02 (partial fill) on the CI twin: the fake composed process (plan 25-10; EXEC-01, D055/D079).

TEST_ONLY: the exchange is the Binance-semantics fake, so every step is SYNTHETIC and the partial
fill is scripted here (`make_partial_fill`: `fake.fill(quantity=)` plus the matching
ORDER_TRADE_UPDATE through `rig.route`). The same `s02_partial_fill.run(env, recorder)` is what the
owner's Demo test calls without a hook: there the entry fills when the exchange fills it, and the
partial step is NOT_OBSERVED unless it really was partial (T-25-25).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import demo_rehearsal as dr
from src.adapters.binance_usdm import UserTradeRow
from src.domain.enums import OrderRole
from src.execution.order_ids import derive_algo_client_id

from tests.support.demo_scenarios import s02_partial_fill
from tests.support.demo_scenarios.catalog import by_id
from tests.support.demo_scenarios.harness import (
    DEMO_OBSERVED,
    NOT_OBSERVED,
    SYNTHETIC,
    EnvOptions,
    ScenarioRecorder,
    build_fake_scenario_env,
)
from tests.support.live_rig import forbid_real_sleep
from tests.support.live_smoke_env import TEST_ONLY_FILL_ORDER_ID
from tests.support.userdata_frames import order_trade_update_frame

D = Decimal
ONE_STEP = D("0.001")
FAKE_NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)

# The existing tests this twin builds on (the coverage inventory of plan 25-17 reads this tuple).
REUSES = (
    "tests/test_protection_branches.py::test_branch_b1_slow_entry_cancel_keeps_the_stop_then_closes_at_its_own_deadline",
    "tests/test_protection_take_profits.py::test_tp_a_partially_closed_position_keeps_the_complete_state",
    "tests/test_live_scheduled_cancel.py::test_a_partly_filled_entry_is_not_cancelled_and_is_journaled",
)


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def _recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S02", mode=dr.RunMode.DRY_RUN, environ={}, clock=lambda: FAKE_NOW)


def _status(recorder: ScenarioRecorder) -> dict[str, str]:
    return {step["name"]: step["status"] for step in recorder.steps}


def make_partial_fill(env: Any, *, keep: Decimal = ONE_STEP) -> s02_partial_fill.PartialFill:
    """The twin's hook: the entry fills except `keep` (one lot step by default), fake and stream.

    A smaller first fill leaves a position too small for TP1 (NOTIONAL_REJECT at the fake prices),
    which is the TP_UNAVAILABLE test below.
    """

    async def deliver(request: Any) -> Decimal:
        rig = env.rig
        quantity = (request.quantity - keep).quantize(D("0.001"), rounding=ROUND_DOWN)
        assert D(0) < quantity < request.quantity, (quantity, request.quantity)
        env.fake.fill(request.entry_client_id, quantity=quantity)
        now = rig.clock.now()
        rig.day_reader.trades["BTCUSDT"] = (
            UserTradeRow(
                symbol="BTCUSDT",
                order_id=TEST_ONLY_FILL_ORDER_ID,
                trade_id=902,
                realized_pnl=D("0"),
                commission=D("0.02"),
                commission_asset="USDT",
                margin_asset="USDT",
                time_utc=now,
            ),
        )
        frame = order_trade_update_frame(
            c=request.entry_client_id,
            i=TEST_ONLY_FILL_ORDER_ID,
            t=902,
            q=str(request.quantity),
            l=str(quantity),
            z=str(quantity),
        )
        assert rig.route(frame).fills == 1
        return quantity

    return deliver


def _approved_quantity(env: Any) -> Decimal:
    (placement,) = env.fake.calls_to("place_entry")
    return D(str(placement["kwargs"]["quantity"]))


def test_the_catalog_pins_s02_to_this_plan() -> None:
    s02 = by_id("S02")
    assert (s02.plan, s02.module) == ("25-10", "tests/support/demo_scenarios/s02_partial_fill.py")
    assert s02.twin_test == "tests/test_demo_twin_s02_partial_fill.py"
    assert s02.requirements == ("EXEC-01",)


async def test_a_partial_fill_is_protected_after_the_first_fill_and_ends_clean(
    tmp_path: Path,
) -> None:
    recorder = _recorder()
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    outcome = await s02_partial_fill.run(env, recorder, partial_fill=make_partial_fill(env))
    assert outcome in (dr.OUTCOME_COMPLETE, dr.OUTCOME_COMPLETE_WITH_GAPS)
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}
    statuses = _status(recorder)
    for name in (
        "precondition_clean",
        "start",
        "confirm_entry",
        s02_partial_fill.STEP_PARTIAL_FILL,
        s02_partial_fill.STEP_BLOCKS_WHILE_UNPROTECTED,
        s02_partial_fill.STEP_STOP_AFTER_FIRST_FILL,
        s02_partial_fill.STEP_REMAINDER_CANCELLED,
        s02_partial_fill.STEP_TP_SIZING,
        s02_partial_fill.STEP_CLOSE,
        "account_clean",
    ):
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)


async def test_the_partial_run_is_complete_with_no_gap(tmp_path: Path) -> None:
    recorder = _recorder()
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    outcome = await s02_partial_fill.run(env, recorder, partial_fill=make_partial_fill(env))
    assert outcome == dr.OUTCOME_COMPLETE, recorder.steps


async def test_the_position_is_the_filled_quantity_never_above_the_approved_one(
    tmp_path: Path,
) -> None:
    recorder = _recorder()
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await s02_partial_fill.run(env, recorder, partial_fill=make_partial_fill(env))
    approved = _approved_quantity(env)
    filled = D(str(recorder.details["scripted_partial_quantity"]))
    assert D(0) < filled < approved
    (entry_id,) = (c["kwargs"]["new_client_order_id"] for c in env.fake.calls_to("place_entry"))
    record = env.fake.history[entry_id]
    assert record.status == "CANCELED", "the remainder of the entry was cancelled (D-12)"
    assert record.executed_quantity == filled
    for call in env.fake.calls_to("place_algo_protective"):
        quantity = call["kwargs"]["quantity"]
        if quantity is not None:
            assert D(str(quantity)) <= approved
    assert len(env.fake.calls_to("place_entry")) == 1


async def test_one_stop_is_placed_for_the_first_fill_as_a_close_position_order(
    tmp_path: Path,
) -> None:
    recorder = _recorder()
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await s02_partial_fill.run(env, recorder, partial_fill=make_partial_fill(env))
    (placement,) = env.fake.calls_to("place_entry")
    entry_id = placement["kwargs"]["new_client_order_id"]
    plan_hash = entry_id.removeprefix("x-")
    stop_id = derive_algo_client_id(plan_hash=_plan_hash_of(env), role=OrderRole.STOP_LOSS.value)
    stops = [
        c
        for c in env.fake.calls_to("place_algo_protective")
        if c["kwargs"]["client_algo_id"] == stop_id
    ]
    assert plan_hash and len(stops) == 1
    assert stops[0]["kwargs"]["close_position"] is True


def _plan_hash_of(env: Any) -> str:
    (protection,) = env.rig.wiring.coordinator.protections()
    return str(protection.plan_hash)


async def test_a_first_fill_too_small_for_tp1_keeps_the_stop_and_is_reported_as_a_gap(
    tmp_path: Path,
) -> None:
    """Half of 0.006 cannot be split into TP1 and TP2 (NOTIONAL_REJECT): the stop stays (D-12)."""
    recorder = _recorder()
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    outcome = await s02_partial_fill.run(
        env, recorder, partial_fill=make_partial_fill(env, keep=D("0.003"))
    )
    assert outcome == dr.OUTCOME_COMPLETE_WITH_GAPS
    statuses = _status(recorder)
    assert statuses[s02_partial_fill.STEP_STOP_AFTER_FIRST_FILL] == dr.STEP_PASSED
    assert statuses[s02_partial_fill.STEP_TP_SIZING] == dr.STEP_NOT_REHEARSED
    assert statuses["account_clean"] == dr.STEP_PASSED
    assert env.fake.calls_to("place_market_close") != [], "the operator close ran at the end"


async def test_a_full_fill_without_the_hook_marks_the_partial_step_as_not_rehearsed(
    tmp_path: Path,
) -> None:
    recorder = _recorder()
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    outcome = await s02_partial_fill.run(env, recorder)
    assert outcome == dr.OUTCOME_COMPLETE_WITH_GAPS
    statuses = _status(recorder)
    assert statuses[s02_partial_fill.STEP_PARTIAL_FILL] == dr.STEP_NOT_REHEARSED
    for name in (
        s02_partial_fill.STEP_STOP_AFTER_FIRST_FILL,
        s02_partial_fill.STEP_REMAINDER_CANCELLED,
        s02_partial_fill.STEP_CLOSE,
        "account_clean",
    ):
        assert statuses[name] == dr.STEP_PASSED, (name, recorder.steps)
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}


def _stub_env(*, synthetic: bool) -> Any:
    return SimpleNamespace(synthetic=synthetic, label=SYNTHETIC if synthetic else DEMO_OBSERVED)


def _demo_recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S02", mode=dr.RunMode.EXECUTE, environ={}, clock=lambda: FAKE_NOW)


def test_on_demo_a_full_fill_is_labelled_not_observed_never_demo_observed() -> None:
    recorder = _demo_recorder()
    s02_partial_fill._record_partial_step(
        _stub_env(synthetic=False), recorder, False, D("0.010"), D("0.010")
    )
    (step,) = recorder.steps
    assert step["label"] == NOT_OBSERVED and step["status"] == dr.STEP_NOT_REHEARSED
    assert "cannot be forced on Demo" in step["detail"]


def test_on_demo_a_real_partial_fill_is_demo_observed() -> None:
    recorder = _demo_recorder()
    s02_partial_fill._record_partial_step(
        _stub_env(synthetic=False), recorder, True, D("0.004"), D("0.010")
    )
    (step,) = recorder.steps
    assert step["label"] == DEMO_OBSERVED and step["status"] == dr.STEP_PASSED


async def test_the_evidence_file_has_the_scenario_schema_and_one_kind(tmp_path: Path) -> None:
    recorder = _recorder()
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await s02_partial_fill.run(env, recorder, partial_fill=make_partial_fill(env))
    document: dict[str, Any] = json.loads(
        recorder.write(tmp_path / "evidence").read_text(encoding="utf-8")
    )
    assert document["schema"] == "demo-scenario-evidence/schema-1"
    assert document["scenario_id"] == "S02"
    assert document["evidence_kinds"] == ["SYNTHETIC"]


def test_the_twin_names_the_existing_tests_it_reuses() -> None:
    assert len(REUSES) >= 1
    for reference in REUSES:
        path, _, name = reference.partition("::")
        assert name in Path(path).read_text(encoding="utf-8")
