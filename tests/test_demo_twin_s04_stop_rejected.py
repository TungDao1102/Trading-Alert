"""S04 (stop rejected after a fill) on the CI twin: the fake composed process (plan 25-11).

TEST_ONLY, EXEC-01 / OPS-01, D079 / D077 / D080. A "fill" request is approved, confirmed and filled;
the first `place_algo_protective` is rejected at the adapter edge (`FaultEdge.raise_before_send`,
code -2021, nothing is sent). The REAL coordinator must then never re-send the stop (one call),
enter CLOSE_REQUIRED with branch B5, send one reduce-only MARKET close under an `xc-` client id,
end FLAT, journal the critical alerts, and block new entries while the close is outstanding.

On the twin every step is SYNTHETIC. On Demo the injection step is DEMO_FAULT_INJECTED and the close
is a real Demo order (DEMO_OBSERVED); the label rule is pinned here on a non-synthetic stub env.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import demo_rehearsal as dr
from src.domain.enums import OrderRole
from src.execution.order_ids import derive_algo_client_id, derive_close_order_id
from src.execution.protection import ProtectionState

from tests.support.demo_scenarios import s04_stop_rejected
from tests.support.demo_scenarios.catalog import by_id
from tests.support.demo_scenarios.harness import (
    DEMO_FAULT_INJECTED,
    DEMO_OBSERVED,
    SYNTHETIC,
    EnvOptions,
    ScenarioRecorder,
    build_fake_scenario_env,
)
from tests.support.live_rig import forbid_real_sleep

D = Decimal
FAKE_NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)

# The existing tests this twin builds on (the coverage inventory of plan 25-17 reads this tuple).
REUSES = (
    "tests/test_protection_branches.py::test_branch_b5_definitive_stop_rejection_after_a_fill_closes_and_ends_flat",
    "tests/test_protection_branches.py::test_branch_close_failed_keeps_blocking_and_retries_every_step_until_flat",
    "tests/test_fault_edge.py::test_an_injected_stop_rejection_after_a_fill_ends_in_close_required_and_a_close",
    "tests/test_emergency_market_close.py::test_tracer_one_part_closes_the_position_and_reports_flat",
)


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def _recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S04", mode=dr.RunMode.DRY_RUN, environ={}, clock=lambda: FAKE_NOW)


def _status(recorder: ScenarioRecorder) -> dict[str, str]:
    return {step["name"]: step["status"] for step in recorder.steps}


def _plan_hash(env: Any) -> str:
    (protection,) = env.wiring.coordinator.protections()
    return str(protection.plan_hash)


def test_the_catalog_pins_s04_to_this_plan() -> None:
    s04 = by_id("S04")
    assert (s04.plan, s04.module) == ("25-11", "tests/support/demo_scenarios/s04_stop_rejected.py")
    assert s04.twin_test == "tests/test_demo_twin_s04_stop_rejected.py"
    assert s04.demo_test == "tests/demo/test_demo_s04_stop_rejected.py"
    assert s04.requirements == ("EXEC-01", "OPS-01")
    assert s04.leaves_state is False


async def test_a_rejected_stop_after_a_fill_ends_in_one_close_and_a_clean_account(
    tmp_path: Path,
) -> None:
    recorder = _recorder()
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    outcome = await s04_stop_rejected.run(env, recorder)
    assert outcome == dr.OUTCOME_COMPLETE, recorder.steps
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}
    statuses = _status(recorder)
    for name in (
        "precondition_clean",
        "start",
        "confirm_entry",
        s04_stop_rejected.STEP_INJECT,
        s04_stop_rejected.STEP_STOP_NOT_RESENT,
        s04_stop_rejected.STEP_CLOSE_REQUIRED,
        s04_stop_rejected.STEP_BLOCKED,
        s04_stop_rejected.STEP_CLOSE,
        s04_stop_rejected.STEP_ALERTS,
        s04_stop_rejected.STEP_SAFE_MODE_LEFT,
        "account_clean",
    ):
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)


async def test_the_stop_is_called_once_and_never_reaches_the_exchange(tmp_path: Path) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await s04_stop_rejected.run(env, _recorder())
    plan_hash = _plan_hash(env)
    stop_id = derive_algo_client_id(plan_hash=plan_hash, role=OrderRole.STOP_LOSS.value)
    stops = [c for c in env.faults.calls_to("place_algo_protective")]
    assert len(stops) == 1, "a definitive rejection is never re-sent (D077, D080)"
    assert stops[0]["kwargs"]["client_algo_id"] == stop_id
    assert stops[0]["injected"] is True and stops[0]["mode"] == "raise_before_send"
    assert env.fake.calls_to("place_algo_protective") == [], "the rejection came from the edge"
    # The only trigger is the stop rejection; the close is delayed (held) for one look on the twin.
    assert [(i.method, i.mode) for i in env.faults.injections] == [
        ("place_algo_protective", "raise_before_send"),
        ("place_market_close", "hold"),
    ]
    assert len(env.fake.calls_to("place_entry")) == 1, "a placement is never re-sent"


async def test_one_reduce_only_market_close_under_an_xc_id_flattens_the_position(
    tmp_path: Path,
) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await s04_stop_rejected.run(env, _recorder())
    plan_hash = _plan_hash(env)
    (close,) = env.fake.calls_to("place_market_close")
    kwargs = close["kwargs"]
    assert kwargs["new_client_order_id"] == derive_close_order_id(plan_hash=plan_hash, attempt_no=1)
    assert kwargs["new_client_order_id"].startswith("xc-")
    assert kwargs["side"] == "SELL" and kwargs["position_side"] == "BOTH"
    (placement,) = env.fake.calls_to("place_entry")
    assert kwargs["quantity"] == placement["kwargs"]["quantity"]
    assert not env.fake.positions.get("BTCUSDT"), "flat at the end"
    assert env.fake.open_orders == {} and env.fake.open_algos == {}


async def test_the_journal_holds_the_b5_transition_and_the_critical_alerts(tmp_path: Path) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    await s04_stop_rejected.run(env, recorder)
    plan_hash = _plan_hash(env)
    journal = env.rig.stores.journal
    transitions = [
        (row["from"], row["to"], row["reason"])
        for row in s04_stop_rejected.protection_rows(journal, plan_hash)
    ]
    assert ("UNPROTECTED", "CLOSE_REQUIRED", "B5_STOP_REJECTED") in transitions
    assert transitions[-1][1] == "FLAT"
    alerts = {
        (row["event"], row["reason"]) for row in s04_stop_rejected.alert_rows(journal, plan_hash)
    }
    assert ("CLOSE_REQUIRED", "B5_STOP_REJECTED") in alerts
    assert ("PROTECTIVE_REJECTED", "B5_STOP_REJECTED") in alerts
    stop_id = derive_algo_client_id(plan_hash=plan_hash, role=OrderRole.STOP_LOSS.value)
    intent = env.wiring.stores.execution_state.intent_for_client_id(stop_id)
    assert intent is not None and intent.intent_status.value == "REJECTED"


async def test_new_entries_are_blocked_while_the_close_is_outstanding(tmp_path: Path) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    await s04_stop_rejected.run(env, recorder)
    window = recorder.details["close_required_window"]
    assert window["observed"] is True
    assert window["blocks_new_entries"] is True
    assert window["state"] == ProtectionState.CLOSE_REQUIRED.value
    assert env.wiring.coordinator.blocks_new_entries() is False, "blocking ends with FLAT"
    assert len(env.fake.calls_to("place_entry")) == 1, "no new entry opened meanwhile"


async def test_safe_mode_is_left_through_the_operator_commands(tmp_path: Path) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await s04_stop_rejected.run(env, _recorder())
    assert env.wiring.safe_mode.in_safe_mode is False
    rows = env.rig.stores.journal.by_type("SAFE_MODE_EXIT")
    assert rows, "the exit is journaled with the operator id"


def _stub_env(*, synthetic: bool) -> Any:
    return SimpleNamespace(synthetic=synthetic, label=SYNTHETIC if synthetic else DEMO_OBSERVED)


def _demo_recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S04", mode=dr.RunMode.EXECUTE, environ={}, clock=lambda: FAKE_NOW)


def test_on_demo_the_injection_is_fault_injected_and_the_close_is_observed() -> None:
    recorder = _demo_recorder()
    env = _stub_env(synthetic=False)
    s04_stop_rejected.record_injection_step(env, recorder, "the stop was rejected")
    s04_stop_rejected.record_close_step(env, recorder, "one reduce-only close")
    steps = {step["name"]: step["label"] for step in recorder.steps}
    assert steps[s04_stop_rejected.STEP_INJECT] == DEMO_FAULT_INJECTED
    assert steps[s04_stop_rejected.STEP_CLOSE] == DEMO_OBSERVED


def test_on_the_twin_both_steps_are_synthetic() -> None:
    recorder = ScenarioRecorder("S04", mode=dr.RunMode.DRY_RUN, environ={}, clock=lambda: FAKE_NOW)
    env = _stub_env(synthetic=True)
    s04_stop_rejected.record_injection_step(env, recorder, "x")
    s04_stop_rejected.record_close_step(env, recorder, "y")
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}


def test_stop_placements_counts_only_the_plans_stop_id() -> None:
    plan_hash = "a" * 64
    stop_id = derive_algo_client_id(plan_hash=plan_hash, role=OrderRole.STOP_LOSS.value)
    tp_id = derive_algo_client_id(plan_hash=plan_hash, role=OrderRole.TAKE_PROFIT_1.value)
    calls = [
        {"kwargs": {"client_algo_id": stop_id}},
        {"kwargs": {"client_algo_id": tp_id}},
        {"kwargs": {"client_algo_id": stop_id}},
    ]
    faults = SimpleNamespace(calls_to=lambda method: calls)
    env = SimpleNamespace(faults=faults)
    assert len(s04_stop_rejected.stop_placements(env, plan_hash)) == 2


async def test_the_evidence_file_has_the_scenario_schema_and_one_kind(tmp_path: Path) -> None:
    recorder = _recorder()
    await s04_stop_rejected.run(build_fake_scenario_env(tmp_path, EnvOptions()), recorder)
    document: dict[str, Any] = json.loads(
        recorder.write(tmp_path / "evidence").read_text(encoding="utf-8")
    )
    assert document["schema"] == "demo-scenario-evidence/schema-1"
    assert document["scenario_id"] == "S04"
    assert document["evidence_kinds"] == ["SYNTHETIC"]
    assert document["details"]["close_required_window"]["observed"] is True


def test_the_twin_names_the_existing_tests_it_reuses() -> None:
    assert len(REUSES) >= 1
    for reference in REUSES:
        path, _, name = reference.partition("::")
        assert name in Path(path).read_text(encoding="utf-8"), reference
