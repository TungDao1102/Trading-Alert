"""S13 (margin and liquidation guards) on the CI twin: the fake composed process (25-15).

TEST_ONLY, OPS-01, EXEC-01. Gate 5f2 of the placement path (`MarginGuard`) refuses before anything
is sent, in two cases the Demo account cannot produce on demand. The readings are injected at the
adapter edge (`FaultEdge.override`) and the guards' reactions are the real process's:

* an available balance below the margin the plan needs (`account_information_snapshot`, both the
  account figure and the USDT row, so the guard's cross-check holds) is refused
  INSUFFICIENT_MARGIN;
* a leverage-bracket table whose maintenance ratio is derived so that the computed liquidation
  price lies between the entry and the stop (`leverage_brackets_snapshot`) is refused
  LIQUIDATION_TOO_CLOSE.

Both values are computed from the plan the process built, the target leverage and the account's
real bracket table, never typed in. Neither refusal sends an entry or a symbol-configuration POST.
With the overrides cleared a request is placed and cancelled and the account ends clean. The
exchange-side -2019 stays with the owner probe case `insufficient_margin_order` (Demo-observed
2026-10-24). The same `s13_margin_liquidation.run(env, recorder)` is what the owner's Demo test
calls.
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
from src.execution.symbol_config_guard import TARGET_LEVERAGE

from tests.support.demo_scenarios import s13_margin_liquidation
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

FAKE_NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)

# The existing tests this twin builds on (the coverage inventory of plan 25-17 reads this tuple).
REUSES = (
    "tests/test_margin_guard.py::test_recorded_crossed_x20_account_flows_through_every_check_to_one_pass",
    "tests/test_margin_guard.py::test_every_refusal_has_its_exact_plain_code_and_touches_nothing_later",
    "tests/test_margin_guard.py::test_a_plan_refused_by_a_pure_check_leaves_the_recorded_account_untouched",
    "tests/test_margin_check.py::test_recorded_demo_shape_initial_margin",
    "tests/test_live_liquidation_and_tp.py::test_a_failed_check_judges_close_for_a_liquidation_price_at_the_stop",
)


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def _recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S13", mode=dr.RunMode.DRY_RUN, environ={}, clock=lambda: FAKE_NOW)


def _status(recorder: ScenarioRecorder) -> dict[str, str]:
    return {step["name"]: step["status"] for step in recorder.steps}


async def _run(tmp_path: Path) -> tuple[Any, ScenarioRecorder, str]:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    outcome = await s13_margin_liquidation.run(env, recorder)
    return env, recorder, outcome


def test_the_catalog_pins_s13_to_this_plan() -> None:
    s = by_id("S13")
    assert (s.plan, s.module) == ("25-15", "tests/support/demo_scenarios/s13_margin_liquidation.py")
    assert s.twin_test == "tests/test_demo_twin_s13_margin_liquidation.py"
    assert s.demo_test == "tests/demo/test_demo_s13_margin_liquidation.py"
    assert s.requirements == ("OPS-01", "EXEC-01")
    assert s.leaves_state is False


async def test_margin_and_liquidation_refusals_send_nothing_and_a_normal_request_is_placed(
    tmp_path: Path,
) -> None:
    _env, recorder, outcome = await _run(tmp_path)
    assert outcome == dr.OUTCOME_COMPLETE, recorder.steps
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}
    statuses = _status(recorder)
    for name in (
        "precondition_clean",
        "start",
        s13_margin_liquidation.STEP_MARGIN_INJECT,
        s13_margin_liquidation.STEP_MARGIN_REFUSED,
        s13_margin_liquidation.STEP_ENTRY_PLACED,
        s13_margin_liquidation.STEP_LIQUIDATION_INJECT,
        s13_margin_liquidation.STEP_LIQUIDATION_REFUSED,
        "account_clean",
    ):
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)


async def test_a_low_available_balance_makes_the_margin_guard_refuse_before_placement(
    tmp_path: Path,
) -> None:
    env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["margin_liquidation"]
    margin = facts["margin"]
    assert margin["reason"] == "INSUFFICIENT_MARGIN"
    assert margin["decisions"] and all(d["refused"] for d in margin["decisions"])
    assert margin["place_entry_calls_before"] == margin["place_entry_calls_after"] == 0
    assert margin["config_posts"] == 0
    # The injected figure is below the initial margin the plan needs, computed from the plan.
    plan = facts["plan"]
    needed = Decimal(plan["quantity"]) * Decimal(plan["entry_price"]) / Decimal(plan["leverage"])
    assert Decimal(margin["needed_initial_margin"]) == needed
    assert Decimal(margin["available_injected"]) < needed
    assert plan["leverage"] == TARGET_LEVERAGE
    assert margin["injected_reads"] >= 1
    assert len(env.faults.calls_to("account_information_snapshot")) >= 1


async def test_a_narrow_liquidation_distance_makes_the_liquidation_guard_refuse(
    tmp_path: Path,
) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["margin_liquidation"]
    liquidation = facts["liquidation"]
    assert liquidation["reason"] == "LIQUIDATION_TOO_CLOSE"
    assert liquidation["decisions"] and all(d["refused"] for d in liquidation["decisions"])
    assert liquidation["config_posts"] == 0
    assert liquidation["place_entry_calls_before"] == liquidation["place_entry_calls_after"]
    # The derived ratio puts the computed liquidation price between the entry and the stop.
    entry = Decimal(facts["plan"]["entry_price"])
    stop = Decimal(facts["plan"]["stop_price"])
    target = Decimal(liquidation["liquidation_price_target"])
    assert min(entry, stop) < target < max(entry, stop)
    assert 0 < Decimal(liquidation["maint_margin_ratio_injected"]) < 1
    assert liquidation["injected_reads"] >= 1


async def test_with_the_overrides_cleared_a_request_is_placed_once_and_the_account_ends_clean(
    tmp_path: Path,
) -> None:
    env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["margin_liquidation"]
    assert facts["normal"]["placed"] is True
    assert facts["normal"]["place_entry_calls"] == 1
    assert len(env.faults.calls_to("place_entry")) == 1, "only the normal request was ever sent"
    assert _status(recorder)["account_clean"] == dr.STEP_PASSED


async def test_the_injections_are_labelled_fault_injected_on_demo() -> None:
    recorder = ScenarioRecorder("S13", mode=dr.RunMode.EXECUTE, environ={}, clock=lambda: FAKE_NOW)
    env = SimpleNamespace(synthetic=False, label=DEMO_OBSERVED)
    s13_margin_liquidation.record_inject(
        env, recorder, s13_margin_liquidation.STEP_MARGIN_INJECT, "a low available balance"
    )
    s13_margin_liquidation.record_inject(
        env, recorder, s13_margin_liquidation.STEP_LIQUIDATION_INJECT, "a narrow distance"
    )
    s13_margin_liquidation.record_reaction(env, recorder, "x", "the guard refused")
    labels = {step["name"]: step["label"] for step in recorder.steps}
    assert labels[s13_margin_liquidation.STEP_MARGIN_INJECT] == DEMO_FAULT_INJECTED
    assert labels[s13_margin_liquidation.STEP_LIQUIDATION_INJECT] == DEMO_FAULT_INJECTED
    assert labels["x"] == DEMO_OBSERVED


async def test_a_balance_that_was_never_lowered_stops_the_run_at_the_margin_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control: with no override the request is placed and the refusal step fails."""
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    monkeypatch.setattr(env.faults, "override", lambda *args, **kwargs: None)
    recorder = _recorder()
    with pytest.raises(dr.SmokeHalt):
        await s13_margin_liquidation.run(env, recorder)
    failed = [step for step in recorder.steps if step["status"] == dr.STEP_FAILED]
    assert failed and failed[0]["name"] == s13_margin_liquidation.STEP_MARGIN_REFUSED


async def test_the_evidence_file_has_the_scenario_schema_and_one_kind(tmp_path: Path) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    document: dict[str, Any] = json.loads(
        recorder.write(tmp_path / "evidence").read_text(encoding="utf-8")
    )
    assert document["schema"] == "demo-scenario-evidence/schema-1"
    assert document["scenario_id"] == "S13"
    assert document["evidence_kinds"] == ["SYNTHETIC"]
    assert document["details"]["margin_liquidation"]["margin"]["reason"] == "INSUFFICIENT_MARGIN"


def test_the_twin_names_the_existing_tests_it_reuses() -> None:
    assert len(REUSES) >= 1
    for reference in REUSES:
        path, _, name = reference.partition("::")
        assert name in Path(path).read_text(encoding="utf-8"), reference
