"""S18 (unprotected-position drill, G2-016) on the CI twin: the fake composed process (plan 25-11).

TEST_ONLY, OPS-01, D-06. A stop rejection (as in S04) plus a failing reduce-only close leave the plan
CLOSE_FAILED: new entries stay blocked, SAFE_MODE is on, the critical alerts are journaled and the
coordinator retries the close at every step. The operator `/close` and `/confirm` (RUNBOOK 21.1a) are
sent through the real handler with the authorized identity; for a plan whose close is already
required the code answers CLOSE_ALREADY_REQUIRED and sends nothing (the retry is the coordinator's).
After the injected close failure is cleared the coordinator's own retry flattens the position.

On the twin every step is SYNTHETIC. On Demo the steps inside the fault window are
DEMO_FAULT_INJECTED and only the final close is a real Demo order (DEMO_OBSERVED).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import demo_rehearsal as dr
from src.execution.order_ids import derive_close_order_id
from src.execution.protection import ProtectionState

from tests.support.demo_scenarios import s04_stop_rejected as s04
from tests.support.demo_scenarios import s18_unprotected
from tests.support.demo_scenarios.catalog import by_id
from tests.support.demo_scenarios.harness import (
    CLEAR_INSTRUCTION,
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
    "tests/test_live_operator_commands.py::test_close_asks_for_a_confirm_and_closes_once_after_it",
    "tests/test_protection_branches.py::test_branch_close_failed_keeps_blocking_and_retries_every_step_until_flat",
    "tests/test_emergency_market_close.py::test_a_reduce_only_rejection_on_an_open_position_fails_without_a_resend",
    "tests/test_drills.py::test_unprotected_drill_blocks_entries_through_the_loop",
)


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def _recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S18", mode=dr.RunMode.DRY_RUN, environ={}, clock=lambda: FAKE_NOW)


def _status(recorder: ScenarioRecorder) -> dict[str, str]:
    return {step["name"]: step["status"] for step in recorder.steps}


def _plan_hash(env: Any) -> str:
    (protection,) = env.wiring.coordinator.protections()
    return str(protection.plan_hash)


def test_the_catalog_pins_s18_to_this_plan_and_flags_it_as_leaving_state() -> None:
    s18 = by_id("S18")
    assert (s18.plan, s18.module) == ("25-11", "tests/support/demo_scenarios/s18_unprotected.py")
    assert s18.twin_test == "tests/test_demo_twin_s18_unprotected.py"
    assert s18.demo_test == "tests/demo/test_demo_s18_unprotected.py"
    assert s18.requirements == ("OPS-01",)
    assert s18.leaves_state is True


async def test_a_rejected_stop_and_a_failing_close_end_close_failed_then_flat(
    tmp_path: Path,
) -> None:
    recorder = _recorder()
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    outcome = await s18_unprotected.run(env, recorder)
    assert outcome == dr.OUTCOME_COMPLETE, recorder.steps
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}
    statuses = _status(recorder)
    for name in (
        "precondition_clean",
        "start",
        s18_unprotected.STEP_INJECT,
        s18_unprotected.STEP_CLOSE_FAILED,
        s18_unprotected.STEP_ALERTS,
        s18_unprotected.STEP_RETRIES,
        s18_unprotected.STEP_OPERATOR_CLOSE,
        s18_unprotected.STEP_FLATTENED,
        s04.STEP_SAFE_MODE_LEFT,
        "account_clean",
    ):
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)


async def test_close_failed_blocks_entries_and_the_coordinator_retries_the_close(
    tmp_path: Path,
) -> None:
    recorder = _recorder()
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await s18_unprotected.run(env, recorder)
    failed = recorder.details["close_failed"]
    assert failed["state"] == ProtectionState.CLOSE_FAILED.value
    assert failed["blocks_new_entries"] is True
    assert failed["safe_mode"] is True
    assert failed["close_attempts_while_failed"] >= 2, "the close is retried every step"
    assert failed["position_still_open"] is True
    assert len(env.fake.calls_to("place_entry")) == 1, "no new entry opened meanwhile"
    stops = env.faults.calls_to("place_algo_protective")
    assert len(stops) == 1, "the rejected stop is never resent"


async def test_every_close_before_the_fault_is_cleared_was_injected_and_one_close_flattens(
    tmp_path: Path,
) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await s18_unprotected.run(env, _recorder())
    plan_hash = _plan_hash(env)
    closes = env.faults.calls_to("place_market_close")
    sent = [c for c in closes if not c["injected"]]
    assert len(sent) == 1 and len(closes) - 1 >= 2
    assert all(c["injected"] and c["mode"] == "raise_before_send" for c in closes[:-1])
    assert closes[-1] is sent[0], "the flattening close is the last one"
    close_id = sent[0]["kwargs"]["new_client_order_id"]
    assert close_id.startswith("xc-") and close_id == derive_close_order_id(
        plan_hash=plan_hash, attempt_no=1
    )
    assert len(env.fake.calls_to("place_market_close")) == 1, "one real close reached the exchange"
    assert not env.fake.positions.get("BTCUSDT")
    assert env.fake.open_orders == {} and env.fake.open_algos == {}


async def test_the_operator_close_is_answered_already_required_and_sends_nothing(
    tmp_path: Path,
) -> None:
    recorder = _recorder()
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await s18_unprotected.run(env, recorder)
    operator = recorder.details["operator_close"]
    assert operator["ask_code"] == "CONFIRM_REQUIRED"
    assert operator["confirm_code"] == "CLOSE_ALREADY_REQUIRED"
    assert operator["plan_state"] == ProtectionState.CLOSE_FAILED.value
    assert operator["close_calls_before"] == operator["close_calls_after"], "the command sent none"
    assert "token" not in json.dumps(recorder.details, default=str).lower()


async def test_the_alerts_name_the_rejected_stop_and_the_failed_close(tmp_path: Path) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await s18_unprotected.run(env, _recorder())
    plan_hash = _plan_hash(env)
    alerts = {
        (row["event"], row["reason"])
        for row in s04.alert_rows(env.rig.stores.journal, plan_hash)
    }
    assert ("CLOSE_REQUIRED", "B5_STOP_REJECTED") in alerts
    assert ("PROTECTIVE_REJECTED", "B5_STOP_REJECTED") in alerts
    assert any(event == "EMERGENCY_CLOSE_FAILED" for event, _reason in alerts)


async def test_a_close_that_never_recovers_halts_and_names_demo_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _recorder()
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    monkeypatch.setattr(env.faults, "clear", lambda method: None)  # the fault is never lifted
    with pytest.raises(dr.SmokeHalt):
        await s18_unprotected.run(env, recorder)
    steps = {step["name"]: step for step in recorder.steps}
    left = steps[s18_unprotected.STEP_STATE_LEFT]
    assert left["status"] == dr.STEP_FAILED
    assert "scripts/demo_clear.py" in left["detail"] and CLEAR_INSTRUCTION in left["detail"]
    assert s18_unprotected.STEP_FLATTENED in steps
    assert steps[s18_unprotected.STEP_FLATTENED]["status"] == dr.STEP_FAILED


def _stub_env(*, synthetic: bool) -> Any:
    return SimpleNamespace(synthetic=synthetic, label=SYNTHETIC if synthetic else DEMO_OBSERVED)


def _demo_recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S18", mode=dr.RunMode.EXECUTE, environ={}, clock=lambda: FAKE_NOW)


def test_on_demo_the_fault_window_is_fault_injected_and_only_the_final_close_is_observed() -> None:
    recorder = _demo_recorder()
    env = _stub_env(synthetic=False)
    s18_unprotected.record_fault_step(env, recorder, s18_unprotected.STEP_CLOSE_FAILED, "x")
    s18_unprotected.record_fault_step(env, recorder, s18_unprotected.STEP_OPERATOR_CLOSE, "y")
    s04.record_close_step(env, recorder, "z", name=s18_unprotected.STEP_FLATTENED)
    labels = {step["name"]: step["label"] for step in recorder.steps}
    assert labels[s18_unprotected.STEP_CLOSE_FAILED] == DEMO_FAULT_INJECTED
    assert labels[s18_unprotected.STEP_OPERATOR_CLOSE] == DEMO_FAULT_INJECTED
    assert labels[s18_unprotected.STEP_FLATTENED] == DEMO_OBSERVED


def test_the_confirm_token_is_read_from_either_bot_shape() -> None:
    fake_bot = SimpleNamespace(
        sent=[SimpleNamespace(chat_id=7, text="Close the BTCUSDT position? Within 60 s: /confirm tok1")]
    )
    recording_bot = SimpleNamespace(sent=[(7, "other"), (7, "Close? send: /confirm tok2 now")])
    assert s18_unprotected.confirm_token(fake_bot, 7, 0) == "tok1"
    assert s18_unprotected.confirm_token(recording_bot, 7, 0) == "tok2"
    assert s18_unprotected.confirm_token(recording_bot, 7, 2) is None, "only text after `since`"
    assert s18_unprotected.confirm_token(recording_bot, 8, 0) is None, "only the owner chat"


async def test_the_evidence_file_has_the_scenario_schema_and_one_kind(tmp_path: Path) -> None:
    recorder = _recorder()
    await s18_unprotected.run(build_fake_scenario_env(tmp_path, EnvOptions()), recorder)
    document: dict[str, Any] = json.loads(
        recorder.write(tmp_path / "evidence").read_text(encoding="utf-8")
    )
    assert document["schema"] == "demo-scenario-evidence/schema-1"
    assert document["scenario_id"] == "S18"
    assert document["evidence_kinds"] == ["SYNTHETIC"]
    assert document["details"]["close_failed"]["state"] == "CLOSE_FAILED"


def test_the_twin_names_the_existing_tests_it_reuses() -> None:
    assert len(REUSES) >= 1
    for reference in REUSES:
        path, _, name = reference.partition("::")
        assert name in Path(path).read_text(encoding="utf-8"), reference
