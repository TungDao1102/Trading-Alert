"""S14 (SAFE_MODE entry and operator exit) on the CI twin: the fake composed process (25-15).

TEST_ONLY, OPS-01. An entry whose state cannot be resolved (the POST reached the exchange, its
answer was lost, the probe by client id fails: all injected) puts the process in SAFE_MODE
ENTRY_STATE_UNKNOWN (D080). While it stands the reconcile and health ticks keep running, no second
request gets a card and a CONFIRM places nothing, and `/safemode_exit` plus `/confirm` is refused
(`UNKNOWN_INTENT_PRESENT`). Once the probe works again the reconcile resolver finds the order and
records it ACKED, which never exits SAFE_MODE (D-15). The operator then cancels the resting entry,
a CONFIRM is still refused, `/safemode_exit` plus `/confirm <token>` leaves SAFE_MODE and a new
request is placed. The same `s14_safe_mode.run(env, recorder)` is what the owner's Demo test calls.

On the twin every step is SYNTHETIC. On Demo the injection step is DEMO_FAULT_INJECTED, the lost
answer being the injected trigger; the reactions are the real process's.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s14_safe_mode
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
    "tests/test_live_safe_mode_drill.py::test_the_drill_enter_blocked_refused_exit_operator_exit_entry_allowed",
    "tests/test_live_safe_mode_drill.py::test_each_failing_exit_row_keeps_safe_mode_and_is_named",
    "tests/test_safe_mode_exit_operator.py::test_operator_exit_checks_journals_persists_then_flips",
    "tests/test_intent_recovery_unknown_entry.py::test_a_found_order_becomes_acked_with_journaled_evidence",
    "tests/test_demo_twin_s07_restart_cuts.py::test_cut_a_the_first_process_ends_unknown_with_safe_mode",
)


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def _recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S14", mode=dr.RunMode.DRY_RUN, environ={}, clock=lambda: FAKE_NOW)


def _status(recorder: ScenarioRecorder) -> dict[str, str]:
    return {step["name"]: step["status"] for step in recorder.steps}


async def _run(tmp_path: Path) -> tuple[Any, ScenarioRecorder, str]:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    outcome = await s14_safe_mode.run(env, recorder)
    return env, recorder, outcome


def test_the_catalog_pins_s14_to_this_plan() -> None:
    s = by_id("S14")
    assert (s.plan, s.module) == ("25-15", "tests/support/demo_scenarios/s14_safe_mode.py")
    assert s.twin_test == "tests/test_demo_twin_s14_safe_mode.py"
    assert s.demo_test == "tests/demo/test_demo_s14_safe_mode.py"
    assert s.requirements == ("OPS-01",)
    assert s.leaves_state is False


async def test_an_unresolved_entry_enters_safe_mode_and_the_operator_exit_restores_entries(
    tmp_path: Path,
) -> None:
    _env, recorder, outcome = await _run(tmp_path)
    assert outcome == dr.OUTCOME_COMPLETE, recorder.steps
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}
    statuses = _status(recorder)
    for name in (
        "precondition_clean",
        "start",
        s14_safe_mode.STEP_INJECT,
        s14_safe_mode.STEP_UNKNOWN,
        s14_safe_mode.STEP_MONITORING,
        s14_safe_mode.STEP_SECOND_REQUEST,
        s14_safe_mode.STEP_EXIT_REFUSED,
        s14_safe_mode.STEP_RECONCILED,
        s14_safe_mode.STEP_CONFIRM_REFUSED,
        s14_safe_mode.STEP_EXIT,
        s14_safe_mode.STEP_ENTRY_ALLOWED,
        "account_clean",
    ):
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)


async def test_the_lost_answer_leaves_the_entry_unknown_and_nothing_is_resent(
    tmp_path: Path,
) -> None:
    env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["safe_mode_drill"]
    assert facts["intent_after_lost_answer"] == "UNKNOWN"
    assert facts["safe_mode_reason_at_entry"] == "ENTRY_STATE_UNKNOWN"
    assert "ENTRY_STATE_UNKNOWN" in facts["safe_mode_enter_reasons"]
    assert facts["dropped_posts"] == 1 and facts["first_probe_injected"] is True
    # The first request's entry was POSTed once; the second request after the exit once more.
    assert facts["place_entry_calls_while_unknown"] == 1
    assert len(env.faults.calls_to("place_entry")) == 2


async def test_the_reconcile_and_health_ticks_keep_running_in_safe_mode(tmp_path: Path) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    monitoring = recorder.details["safe_mode_drill"]["monitoring"]
    assert monitoring["in_safe_mode_throughout"] is True
    assert monitoring["reconcile_ticks_journaled"] >= 2
    assert monitoring["health_verdicts_journaled"] >= 2
    assert monitoring["probes_failed_after_the_first"] >= 1, "the resolver probed and it failed"


async def test_no_second_card_is_issued_while_the_entry_is_unresolved(tmp_path: Path) -> None:
    """The sender's one-plan-per-symbol rule is the first fail-closed layer (observed, recorded)."""
    _env, recorder, _outcome = await _run(tmp_path)
    second = recorder.details["safe_mode_drill"]["second_request"]
    assert second["refused"] is True
    assert second["reason"] == "CONFLICT_WITH_OPEN_POSITION"
    assert "UNRESOLVED_ENTRY_INTENT" in second["sources"]


async def test_the_exit_is_refused_while_the_entry_is_unresolved(tmp_path: Path) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    refused = recorder.details["safe_mode_drill"]["exit_refused"]
    assert refused["still_in_safe_mode"] is True
    assert "UNKNOWN_INTENT_PRESENT" in refused["refusals"]
    assert refused["refused_rows_added"] >= 1


async def test_the_reconcile_resolves_the_entry_and_that_never_exits_safe_mode(
    tmp_path: Path,
) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    resolved = recorder.details["safe_mode_drill"]["reconciled"]
    assert resolved["intent_after"] == "ACKED"
    assert resolved["unknown_probe_calls_after_clear"] >= 1
    assert resolved["in_safe_mode_after_resolution"] is True


async def test_a_confirm_in_safe_mode_places_nothing(tmp_path: Path) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["safe_mode_drill"]
    refused = facts["confirm_in_safe_mode"]
    assert refused["decisions"] and all(d["refused"] for d in refused["decisions"])
    assert refused["decisions"][-1]["reason"] == "RECONCILIATION_REQUIRED"
    assert refused["place_entry_calls_before"] == refused["place_entry_calls_after"] == 1


async def test_the_exit_is_accepted_after_the_reconcile_and_a_new_request_is_placed(
    tmp_path: Path,
) -> None:
    env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["safe_mode_drill"]
    assert facts["exit"]["in_safe_mode_after"] is False
    assert facts["exit"]["exit_rows"] == 1
    assert facts["exit"]["exit_operator_recorded"] is True
    assert facts["entry_after_exit"]["placed"] is True
    assert len(env.faults.calls_to("place_entry")) == 2
    journal = env.rig.stores.journal
    assert len(journal.by_type("SAFE_MODE_EXIT")) == 1


async def test_the_injection_is_labelled_fault_injected_on_demo() -> None:
    recorder = ScenarioRecorder("S14", mode=dr.RunMode.EXECUTE, environ={}, clock=lambda: FAKE_NOW)
    env = SimpleNamespace(synthetic=False, label=DEMO_OBSERVED)
    s14_safe_mode.record_inject(env, recorder, "the answer was lost and the probe failed")
    s14_safe_mode.record_reaction(env, recorder, "x", "SAFE_MODE is on")
    labels = {step["name"]: step["label"] for step in recorder.steps}
    assert labels[s14_safe_mode.STEP_INJECT] == DEMO_FAULT_INJECTED
    assert labels["x"] == DEMO_OBSERVED


async def test_an_entry_that_was_never_made_unknown_halts_at_the_unknown_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control: with no lost answer the entry is ACKED and the run stops there."""
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    monkeypatch.setattr(env.faults, "drop_response_after_send", lambda *args, **kwargs: None)
    recorder = _recorder()
    with pytest.raises(dr.SmokeHalt):
        await s14_safe_mode.run(env, recorder)
    failed = [step for step in recorder.steps if step["status"] == dr.STEP_FAILED]
    assert failed and failed[0]["name"] == s14_safe_mode.STEP_UNKNOWN


async def test_the_evidence_file_has_the_scenario_schema_and_one_kind(tmp_path: Path) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    document: dict[str, Any] = json.loads(
        recorder.write(tmp_path / "evidence").read_text(encoding="utf-8")
    )
    assert document["schema"] == "demo-scenario-evidence/schema-1"
    assert document["scenario_id"] == "S14"
    assert document["evidence_kinds"] == ["SYNTHETIC"]
    assert document["details"]["safe_mode_drill"]["exit"]["in_safe_mode_after"] is False


def test_the_twin_names_the_existing_tests_it_reuses() -> None:
    assert len(REUSES) >= 1
    for reference in REUSES:
        path, _, name = reference.partition("::")
        assert name in Path(path).read_text(encoding="utf-8"), reference
