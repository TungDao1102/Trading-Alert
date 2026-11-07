"""S19 (REST gate operator commands, P20-DEMO) on the CI twin: the fake composed process (25-14).

TEST_ONLY, OPS-01, D-06. A false 418 is injected under the REAL adapter and persisted by the real
gate; the process is stopped in order (RUNBOOK 22.5); `rest_gate_cli status` shows the persisted
ban; `clear` refuses the future deadline without `--force`; `clear --force` writes a fresh record and
its audit lines in `<state file>.clear-audit.jsonl`; the restarted process restores a clear gate and
places a request. The commands run in process through `rest_gate_cli.main`; the state file is never
edited by hand. The same `s19_rest_gate_cli.run(env, recorder)` is what the owner's Demo test calls.

On the twin every step is SYNTHETIC and the one clock read of the CLI is the env's virtual clock
(the gate deadline is virtual time; on Demo the CLI reads the wall clock). On Demo the injection
step is DEMO_FAULT_INJECTED.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import demo_rehearsal as dr
from src.ops import rest_gate_cli

from tests.support.demo_scenarios import s19_rest_gate_cli
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
    "tests/test_rest_gate_cli.py::test_clear_refuses_a_future_deadline_without_force",
    "tests/test_rest_gate_cli.py::test_clear_with_force_clears_and_says_forced",
    "tests/test_rest_gate_cli.py::test_clear_takes_effect_only_after_restart_restore",
    "tests/test_rest_gate_clear_audit.py::test_a_forced_clear_over_a_real_ban_records_who_why_and_what_was_overridden",
    "tests/test_fault_edge.py::test_an_injected_418_under_the_real_adapter_records_a_ban_and_nothing_is_resent",
)


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def _recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S19", mode=dr.RunMode.DRY_RUN, environ={}, clock=lambda: FAKE_NOW)


def _status(recorder: ScenarioRecorder) -> dict[str, str]:
    return {step["name"]: step["status"] for step in recorder.steps}


async def _run(tmp_path: Path) -> tuple[Any, ScenarioRecorder, str]:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    outcome = await s19_rest_gate_cli.run(env, recorder)
    return env, recorder, outcome


def test_the_catalog_pins_s19_to_this_plan() -> None:
    s = by_id("S19")
    assert (s.plan, s.module) == ("25-14", "tests/support/demo_scenarios/s19_rest_gate_cli.py")
    assert s.twin_test == "tests/test_demo_twin_s19_rest_gate_cli.py"
    assert s.demo_test == "tests/demo/test_demo_s19_rest_gate_cli.py"
    assert s.requirements == ("OPS-01",)


async def test_a_false_418_is_cleared_by_stop_status_clear_and_restart(tmp_path: Path) -> None:
    _env, recorder, outcome = await _run(tmp_path)
    assert outcome == dr.OUTCOME_COMPLETE, recorder.steps
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}
    statuses = _status(recorder)
    for name in (
        "precondition_clean",
        "start",
        s19_rest_gate_cli.STEP_BASELINE,
        s19_rest_gate_cli.STEP_INJECT,
        s19_rest_gate_cli.STEP_BAN_PERSISTED,
        s19_rest_gate_cli.STEP_STATUS_RUNNING,
        s19_rest_gate_cli.STEP_STOPPED,
        s19_rest_gate_cli.STEP_STATUS,
        s19_rest_gate_cli.STEP_CLEAR_REFUSED,
        s19_rest_gate_cli.STEP_CLEAR,
        s19_rest_gate_cli.STEP_AUDIT,
        s19_rest_gate_cli.STEP_STATUS_CLEARED,
        s19_rest_gate_cli.STEP_RESTORED_CLEAR,
        s19_rest_gate_cli.STEP_ENTRY_ALLOWED,
        "account_clean",
    ):
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)


async def test_status_shows_the_persisted_ban_and_clear_refuses_it_without_force(
    tmp_path: Path,
) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["rest_gate_cli"]
    assert len(facts["ban_alerts"]) == 1
    assert facts["status_running"]["exit_code"] == rest_gate_cli.EXIT_OK
    assert facts["status_running"]["ban_until_utc"] != "none"
    assert facts["status_stopped"]["exit_code"] == rest_gate_cli.EXIT_OK
    assert facts["status_stopped"]["future_deadline"] != "none"
    assert facts["clear_unforced"]["exit_code"] == rest_gate_cli.EXIT_FUTURE_DEADLINE
    assert facts["clear_unforced"]["audit_lines_after"] == 0, "a refused clear writes no audit line"


async def test_the_forced_clear_writes_a_fresh_record_and_its_audit_lines(tmp_path: Path) -> None:
    env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["rest_gate_cli"]
    assert facts["clear_forced"]["exit_code"] == rest_gate_cli.EXIT_OK
    assert facts["status_cleared"]["ban_until_utc"] == "none"
    assert facts["status_cleared"]["future_deadline"] == "none"
    state_path = env.assembly.config.gate_state_path
    audit_path = state_path.with_name(state_path.name + ".clear-audit.jsonl")
    lines = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert [line["outcome"] for line in lines] == ["requested", "cleared"]
    for line in lines:
        assert line["operator_id"] == s19_rest_gate_cli.OPERATOR_ID
        assert line["reason"] == s19_rest_gate_cli.CLEAR_REASON
        assert line["forced"] is True
        assert line["previous"] == "valid"
        assert line["overridden"] and line["overridden"][0].startswith("ban_until_utc")
    assert facts["audit"] == {"lines": 2, "outcomes": ["requested", "cleared"], "forced": True}


async def test_the_restarted_process_restores_a_clear_gate_and_places_a_request(
    tmp_path: Path,
) -> None:
    env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["rest_gate_cli"]
    assert facts["restart"]["restriction_after_restart"] is None
    assert facts["restart"]["recovery_status"] == "RESTORED_DURABLE"
    assert facts["restart"]["admitted_and_enabled"] is True
    # The first process sent nothing; the far entry of the second process is the only one.
    assert len(env.fake.calls_to("place_entry")) == 1


async def test_a6_is_recorded_as_observed_not_assumed(tmp_path: Path) -> None:
    """Research assumption A6: what `clear` does while a process still runs."""
    _env, recorder, _outcome = await _run(tmp_path)
    a6 = recorder.details["rest_gate_cli"]["a6"]
    assert a6["status_exit_code_while_running"] == rest_gate_cli.EXIT_OK
    assert a6["clear_unforced_exit_code_while_running"] == rest_gate_cli.EXIT_FUTURE_DEADLINE
    assert a6["refused_for"] == "future deadline"
    assert a6["state_unchanged_by_the_refusal"] is True
    assert a6["forced_clear_while_running"].startswith("NOT_ATTEMPTED")


async def test_the_cli_clock_on_the_twin_is_the_env_clock(tmp_path: Path) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    assert recorder.details["rest_gate_cli"]["cli_clock"] == "env clock (twin)"


def test_the_scenario_never_edits_the_state_file_by_hand() -> None:
    source = Path(s19_rest_gate_cli.__file__).read_text(encoding="utf-8")
    for forbidden in ("write_text", "write_bytes", "open(", "unlink", "shutil"):
        assert forbidden not in source, forbidden
    assert "rest_gate_cli.main" in source


async def test_the_injection_is_labelled_fault_injected_on_demo() -> None:
    recorder = ScenarioRecorder("S19", mode=dr.RunMode.EXECUTE, environ={}, clock=lambda: FAKE_NOW)
    env = SimpleNamespace(synthetic=False, label=DEMO_OBSERVED)
    s19_rest_gate_cli.record_inject(env, recorder, "an HTTP 418 is raised")
    s19_rest_gate_cli.record_reaction(env, recorder, "x", "the gate recorded it")
    labels = {step["name"]: step["label"] for step in recorder.steps}
    assert labels[s19_rest_gate_cli.STEP_INJECT] == DEMO_FAULT_INJECTED
    assert labels["x"] == DEMO_OBSERVED


async def test_a_clear_that_fails_stops_the_scenario_at_the_clear_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control: the restart is never reached when the operator clear does not succeed."""
    real = rest_gate_cli.clear_state

    def failing(store: Any, now_utc: Any, operator_id: str, reason: str, force: bool) -> Any:
        if force:
            return rest_gate_cli.CliResult(rest_gate_cli.EXIT_WRITE_FAILED, ("failed",))
        return real(store, now_utc, operator_id, reason, force)

    monkeypatch.setattr(rest_gate_cli, "clear_state", failing)
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    with pytest.raises(dr.SmokeHalt):
        await s19_rest_gate_cli.run(env, recorder)
    failed = [step for step in recorder.steps if step["status"] == dr.STEP_FAILED]
    assert failed and failed[0]["name"] == s19_rest_gate_cli.STEP_CLEAR


async def test_the_evidence_file_has_the_scenario_schema_and_one_kind(tmp_path: Path) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    document: dict[str, Any] = json.loads(
        recorder.write(tmp_path / "evidence").read_text(encoding="utf-8")
    )
    assert document["schema"] == "demo-scenario-evidence/schema-1"
    assert document["scenario_id"] == "S19"
    assert document["evidence_kinds"] == ["SYNTHETIC"]
    assert document["details"]["rest_gate_cli"]["clear_forced"]["exit_code"] == 0


def test_the_twin_names_the_existing_tests_it_reuses() -> None:
    assert len(REUSES) >= 1
    for reference in REUSES:
        path, _, name = reference.partition("::")
        assert name in Path(path).read_text(encoding="utf-8"), reference
