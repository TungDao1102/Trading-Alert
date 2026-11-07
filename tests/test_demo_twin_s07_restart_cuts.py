"""S07 (restart mid-flow, three cuts) on the CI twin: the fake composed process (plan 25-12).

TEST_ONLY, EXEC-01, EXEC-03, D079, D080. The process is crashed (`abandon`, no drain) and a second
process is built over the same stores and the same exchange at three points: after the fill and the
confirmed stop (c), before the entry answer is known (a) and between the fill and the stop (b). The
same `s07_restart_cuts.run(env, recorder, cut=...)` is what the owner's Demo test calls (D-04,
D-05).

On the twin every step is SYNTHETIC. On Demo an injected trigger (the lost entry answer, the held
stop placement) is DEMO_FAULT_INJECTED and only what the second process does is DEMO_OBSERVED.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import demo_rehearsal as dr
from src.execution.protection import ProtectionState

from tests.support.demo_scenarios import s07_restart_cuts
from tests.support.demo_scenarios.catalog import by_id
from tests.support.demo_scenarios.harness import (
    DEMO_FAULT_INJECTED,
    DEMO_OBSERVED,
    SYNTHETIC,
    EnvOptions,
    ScenarioPrecondition,
    ScenarioRecorder,
    build_fake_scenario_env,
)
from tests.support.execution_limits import TEST_ONLY_EXECUTION_LIMIT_VALUES
from tests.support.fault_edge import MODE_DROP_RESPONSE, MODE_HOLD
from tests.support.live_rig import forbid_real_sleep

FAKE_NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)

# The existing tests this twin builds on (the coverage inventory of plan 25-17 reads this tuple).
REUSES = (
    "tests/test_live_restart_rehydrate.py::test_a_protected_plan_comes_back_protected_and_its_stop_is_not_placed_again",
    "tests/test_live_restart_rehydrate.py::test_an_entry_sent_with_an_unknown_result_stays_unknown_with_safe_mode",
    "tests/test_intent_recovery_unknown_entry.py::test_a_found_order_becomes_acked_with_journaled_evidence",
    "tests/test_live_restart_rehydrate.py::test_a_fill_for_the_rebuilt_entry_reaches_the_coordinator_as_a_known_order",
    "tests/test_live_stream_to_protection.py::test_a_fill_frame_at_the_transport_edge_ends_in_a_rest_confirmed_stop",
)


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def _recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S07", mode=dr.RunMode.DRY_RUN, environ={}, clock=lambda: FAKE_NOW)


def _status(recorder: ScenarioRecorder) -> dict[str, str]:
    return {step["name"]: step["status"] for step in recorder.steps}


def test_the_catalog_pins_s07_to_this_plan() -> None:
    s07 = by_id("S07")
    assert (s07.plan, s07.module) == ("25-12", "tests/support/demo_scenarios/s07_restart_cuts.py")
    assert s07.twin_test == "tests/test_demo_twin_s07_restart_cuts.py"
    assert s07.demo_test == "tests/demo/test_demo_s07_restart_cuts.py"
    assert set(s07.requirements) == {"EXEC-01", "EXEC-03"}


async def test_an_unknown_cut_is_refused_before_anything_runs(tmp_path: Path) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    with pytest.raises(ValueError, match="cut"):
        await s07_restart_cuts.run(env, recorder, cut="z")
    assert recorder.steps == [], "nothing was recorded, nothing was read"
    assert env.fake.calls_to("place_entry") == []


# --------------------------------------------------------------------------------------------- #
# Cut (c): restart after the fill and the confirmed stop.
# --------------------------------------------------------------------------------------------- #

_CUT_C_STEPS = (
    "precondition_clean",
    "start",
    "signal",
    "card",
    "approve",
    "confirm_entry",
    "stop_confirmed",
    "restart",
    s07_restart_cuts.STEP_C_REHYDRATED,
    s07_restart_cuts.STEP_C_NOTHING_SENT,
    s07_restart_cuts.STEP_C_RECONCILE_CLEAN,
    "close_cleanup",
    "account_clean",
)


async def test_cut_c_runs_end_to_end_and_every_step_is_synthetic(tmp_path: Path) -> None:
    recorder = _recorder()
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    outcome = await s07_restart_cuts.run(env, recorder, cut="c")
    assert outcome == dr.OUTCOME_COMPLETE and recorder.outcome == outcome
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}
    statuses = _status(recorder)
    for name in _CUT_C_STEPS:
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)
    assert recorder.details["cut"] == "c"


async def test_cut_c_the_second_process_restored_one_plan_and_it_is_protected(
    tmp_path: Path,
) -> None:
    recorder = _recorder()
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await s07_restart_cuts.run(env, recorder, cut="c")
    starts = recorder.details["start_sequences"]
    assert [s["label"] for s in starts] == ["start", "restart"]
    assert starts[0]["plans_restored"] == 0 and starts[1]["plans_restored"] == 1
    assert starts[1]["admitted"] is True and starts[1]["safe_mode_reasons"] == []
    facts = recorder.details["cut_c"]
    assert facts["state_before_crash"] == facts["state_after_restart"]
    assert facts["state_after_restart"] in {
        ProtectionState.PROTECTED.value,
        ProtectionState.COMPLETE.value,
        ProtectionState.TP_UNAVAILABLE.value,
    }
    assert facts["stop_confirmed_after_restart"] is True


async def test_cut_c_the_second_process_sends_nothing_to_the_exchange(tmp_path: Path) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    await s07_restart_cuts.run(env, recorder, cut="c")
    facts = recorder.details["cut_c"]
    assert facts["mutating_calls_after_restart"] == facts["mutating_calls_before_crash"]
    # The exchange's own view: one entry, and every protective id placed exactly once.
    assert len(env.fake.calls_to("place_entry")) == 1
    ids = [c["kwargs"]["client_algo_id"] for c in env.fake.calls_to("place_algo_protective")]
    assert len(ids) == len(set(ids)), "a protective id was placed twice"
    assert ids.count(facts["stop_client_algo_id"]) == 1, "the stop was placed once, by process 1"


async def test_cut_c_a_new_exchange_call_after_the_restart_fails_the_step(tmp_path: Path) -> None:
    """Negative control: if the second process placed anything the scenario must stop."""
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    original = s07_restart_cuts.mutating_counts
    calls = {"n": 0}

    def growing(env_: Any) -> dict[str, int]:
        counts = original(env_)
        calls["n"] += 1
        if calls["n"] >= 2:  # the read after the restart
            counts["place_algo_protective"] += 1
        return counts

    s07_restart_cuts.mutating_counts = growing  # type: ignore[assignment]
    try:
        with pytest.raises(dr.SmokeHalt):
            await s07_restart_cuts.run(env, recorder, cut="c")
    finally:
        s07_restart_cuts.mutating_counts = original  # type: ignore[assignment]
    assert _status(recorder)[s07_restart_cuts.STEP_C_NOTHING_SENT] == dr.STEP_FAILED


async def test_cut_c_a_dirty_account_stops_before_anything_is_placed(tmp_path: Path) -> None:
    from decimal import Decimal

    env = build_fake_scenario_env(tmp_path, EnvOptions())
    env.fake.positions["BTCUSDT"] = Decimal("0.01")
    with pytest.raises(ScenarioPrecondition):
        await s07_restart_cuts.run(env, _recorder(), cut="c")
    assert env.fake.calls_to("place_entry") == []


# --------------------------------------------------------------------------------------------- #
# Cut (a): the entry answer is lost, the probe fails, the process crashes (D080).
# --------------------------------------------------------------------------------------------- #

_CUT_A_STEPS = (
    "precondition_clean",
    "start",
    "signal",
    "card",
    "approve",
    s07_restart_cuts.STEP_A_LOST_ANSWER,
    s07_restart_cuts.STEP_A_ENTRY_UNKNOWN,
    "restart",
    s07_restart_cuts.STEP_A_RECOVERY,
    s07_restart_cuts.STEP_A_ONE_ENTRY,
    "cancel_resting_entry",
    "safe_mode_left",
    "account_clean",
)


async def _run_a(tmp_path: Path, **kwargs: Any) -> tuple[Any, ScenarioRecorder]:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    outcome = await s07_restart_cuts.run(env, recorder, cut="a", **kwargs)
    assert outcome == dr.OUTCOME_COMPLETE and recorder.outcome == outcome
    return env, recorder


async def test_cut_a_found_runs_end_to_end_and_every_step_is_synthetic(tmp_path: Path) -> None:
    _, recorder = await _run_a(tmp_path)
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}
    statuses = _status(recorder)
    for name in _CUT_A_STEPS:
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)
    assert recorder.details["cut"] == "a"


async def test_cut_a_one_place_entry_across_both_processes(tmp_path: Path) -> None:
    env, _ = await _run_a(tmp_path)
    assert len(env.fake.calls_to("place_entry")) == 1, "the exchange saw one entry POST"
    assert len(env.faults.calls_to("place_entry")) == 1, "the process sent one entry POST"
    (record,) = env.faults.calls_to("place_entry")
    assert record["injected"] is True and record["mode"] == MODE_DROP_RESPONSE
    assert env.fake.calls_to("place_algo_protective") == [], "nothing filled, no stop"
    assert env.fake.calls_to("place_market_close") == []


async def test_cut_a_the_first_process_ends_unknown_with_safe_mode(tmp_path: Path) -> None:
    _, recorder = await _run_a(tmp_path)
    facts = recorder.details["cut_a"]
    assert facts["intent_after_lost_answer"] == "UNKNOWN"
    assert facts["safe_mode_reason_first_process"] == "ENTRY_STATE_UNKNOWN"
    assert facts["probe_calls_first_process"] == 1


async def test_cut_a_the_recovery_probes_once_by_client_id_and_acks_the_entry(
    tmp_path: Path,
) -> None:
    env, recorder = await _run_a(tmp_path)
    facts = recorder.details["cut_a"]
    assert facts["recovery_probe_calls"] == 1, "exactly one probe in the start sequence"
    assert facts["recovery_resolved"] == [["ENTRY", "ACKED"]]
    assert facts["recovery_unresolved"] == []
    assert facts["intent_after_restart"] == "ACKED"
    assert facts["plan_tracked_after_restart"] is True
    probes = env.faults.calls_to("query_order_by_client")
    entry_id = env.fake.calls_to("place_entry")[0]["kwargs"]["new_client_order_id"]
    assert probes[0]["injected"] is True, "the first probe is the injected failure"
    assert probes[1]["kwargs"]["orig_client_order_id"] == entry_id
    assert probes[1]["injected"] is False


async def test_cut_a_the_second_process_starts_blocked_and_the_owner_leaves_safe_mode(
    tmp_path: Path,
) -> None:
    env, recorder = await _run_a(tmp_path)
    starts = recorder.details["start_sequences"]
    assert [s["label"] for s in starts] == ["start", "restart"]
    assert starts[1]["admitted"] is True and starts[1]["plans_restored"] == 1
    facts = recorder.details["cut_a"]
    assert facts["restart_in_safe_mode"] is True and facts["restart_entries_enabled"] is False
    assert facts["safe_mode_after_exit"] is False, "left through /safemode_exit"
    assert env.rig.stores.journal.by_type("SAFE_MODE_EXIT")


async def test_cut_a_probe_error_branch_stays_unknown_with_safe_mode_and_never_resends(
    tmp_path: Path,
) -> None:
    env, recorder = await _run_a(tmp_path, probe_error=True)
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}
    facts = recorder.details["cut_a"]
    assert facts["branch"] == "probe_error"
    assert facts["recovery_resolved"] == []
    assert facts["recovery_unresolved"] == [["ENTRY", "UNKNOWN"]]
    assert facts["recovery_safe_mode_entered"] is True
    assert facts["restart_in_safe_mode"] is True and facts["restart_entries_enabled"] is False
    assert facts["safe_mode_reason_after_restart"] in {
        "ENTRY_STATE_UNKNOWN",
        "UNRESOLVED_EXECUTION_INTENT",
    }
    probes = env.faults.calls_to("query_order_by_client")
    assert probes[0]["injected"] is True and probes[1]["injected"] is True
    assert len(env.fake.calls_to("place_entry")) == 1
    assert len(env.faults.calls_to("place_entry")) == 1
    assert facts["safe_mode_after_exit"] is False, "resolved the documented way"
    assert env.rig.stores.journal.by_type("SAFE_MODE_EXIT")


async def test_cut_a_a_second_place_entry_fails_the_step(tmp_path: Path) -> None:
    """Negative control: if the exchange saw a second POST the scenario must stop, not pass."""
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    original = s07_restart_cuts.place_entry_calls

    def counted_twice(env_: Any) -> int:
        return original(env_) + 1

    s07_restart_cuts.place_entry_calls = counted_twice  # type: ignore[assignment]
    try:
        with pytest.raises(dr.SmokeHalt):
            await s07_restart_cuts.run(env, recorder, cut="a")
    finally:
        s07_restart_cuts.place_entry_calls = original  # type: ignore[assignment]
    assert _status(recorder)[s07_restart_cuts.STEP_A_ONE_ENTRY] == dr.STEP_FAILED


async def test_cut_a_a_probe_error_is_only_for_the_twin_and_only_for_cut_a(
    tmp_path: Path,
) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    with pytest.raises(ValueError, match="probe_error"):
        await s07_restart_cuts.run(env, _recorder(), cut="c", probe_error=True)
    demo_like = SimpleNamespace(synthetic=False, label=DEMO_OBSERVED)
    with pytest.raises(ValueError, match="probe_error"):
        await s07_restart_cuts.run(demo_like, _recorder(), cut="a", probe_error=True)


def test_on_demo_the_lost_answer_is_fault_injected_and_the_recovery_is_observed() -> None:
    recorder = ScenarioRecorder("S07", mode=dr.RunMode.EXECUTE, environ={}, clock=lambda: FAKE_NOW)
    env = SimpleNamespace(synthetic=False, label=DEMO_OBSERVED)
    s07_restart_cuts.record_lost_answer(env, recorder, "the entry answer was dropped")
    s07_restart_cuts.record_recovery(env, recorder, "the recovery probed once")
    steps = {step["name"]: step["label"] for step in recorder.steps}
    assert steps[s07_restart_cuts.STEP_A_LOST_ANSWER] == DEMO_FAULT_INJECTED
    assert steps[s07_restart_cuts.STEP_A_RECOVERY] == DEMO_OBSERVED


# --------------------------------------------------------------------------------------------- #
# Cut (b): the stop placement is held, the process crashes between the fill and the stop.
# --------------------------------------------------------------------------------------------- #

_CUT_B_STEPS = (
    "precondition_clean",
    "start",
    "signal",
    "card",
    "approve",
    "confirm_entry",
    s07_restart_cuts.STEP_B_HELD,
    "restart",
    s07_restart_cuts.STEP_B_RESTORED,
    s07_restart_cuts.STEP_B_STOP_PLACED,
    s07_restart_cuts.STEP_B_ONE_ENTRY,
    "close_cleanup",
    "safe_mode_left",
    "account_clean",
)


async def _run_b(tmp_path: Path, **kwargs: Any) -> tuple[Any, ScenarioRecorder]:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    outcome = await s07_restart_cuts.run(env, recorder, cut="b", **kwargs)
    assert outcome == dr.OUTCOME_COMPLETE and recorder.outcome == outcome
    return env, recorder


async def test_cut_b_runs_end_to_end_and_every_step_is_synthetic(tmp_path: Path) -> None:
    _, recorder = await _run_b(tmp_path)
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}
    statuses = _status(recorder)
    for name in _CUT_B_STEPS:
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)
    assert recorder.details["cut"] == "b"


async def test_cut_b_the_held_stop_never_reached_the_exchange_the_second_process_placed_it(
    tmp_path: Path,
) -> None:
    env, recorder = await _run_b(tmp_path)
    facts = recorder.details["cut_b"]
    stop_id = facts["stop_client_algo_id"]
    edge = [
        c
        for c in env.faults.calls_to("place_algo_protective")
        if c["kwargs"]["client_algo_id"] == stop_id
    ]
    assert len(edge) == 2, "the held call of the first process and the real one"
    assert edge[0]["mode"] == MODE_HOLD and edge[1]["injected"] is False
    on_exchange = [
        c["kwargs"]["client_algo_id"] for c in env.fake.calls_to("place_algo_protective")
    ]
    assert on_exchange.count(stop_id) == 1, "the exchange saw one stop, from the second process"
    assert facts["stop_calls_at_exchange_before_restart"] == 0
    assert facts["stop_confirmed_after_restart"] is True


async def test_cut_b_the_second_process_restores_unprotected_and_blocks_entries(
    tmp_path: Path,
) -> None:
    env, recorder = await _run_b(tmp_path)
    facts = recorder.details["cut_b"]
    assert facts["state_before_crash"] == ProtectionState.UNPROTECTED.value
    assert facts["state_after_restart"] == ProtectionState.UNPROTECTED.value
    assert facts["blocks_new_entries_after_restart"] is True
    assert facts["restart_in_safe_mode"] is True and facts["restart_entries_enabled"] is False
    starts = recorder.details["start_sequences"]
    assert [s["label"] for s in starts] == ["start", "restart"]
    assert starts[1]["plans_restored"] == 1
    assert len(env.fake.calls_to("place_entry")) == 1, "no second entry opened"
    assert len(env.faults.calls_to("place_entry")) == 1


async def test_cut_b_the_protected_plan_is_closed_the_owner_leaves_safe_mode(
    tmp_path: Path,
) -> None:
    env, recorder = await _run_b(tmp_path)
    facts = recorder.details["cut_b"]
    assert facts["state_after_stop"] in {"PROTECTED", "COMPLETE", "TP_UNAVAILABLE"}
    assert facts["safe_mode_after_exit"] is False
    assert env.rig.stores.journal.by_type("SAFE_MODE_EXIT")
    assert env.fake.open_orders == {} and env.fake.open_algos == {}
    assert len(env.fake.calls_to("place_market_close")) == 1, "the operator close"


async def test_cut_b_a_late_restart_closes_at_the_deadline_instead_of_protecting(
    tmp_path: Path,
) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    outcome = await s07_restart_cuts.run(env, recorder, cut="b", late_restart=True)
    assert outcome == dr.OUTCOME_COMPLETE_WITH_GAPS, "SAFE_MODE could not be left (finding F1)"
    facts = recorder.details["cut_b"]
    assert facts["branch"] == "late_restart"
    assert (
        facts["late_restart_seconds"] * 1000
        > TEST_ONLY_EXECUTION_LIMIT_VALUES["protection.max_unprotected_ms"]
    )
    assert facts["state_after_restart"] == ProtectionState.UNPROTECTED.value
    assert facts["first_closing_state"] == ProtectionState.CLOSE_REQUIRED.value
    assert statuses_of(recorder)[s07_restart_cuts.STEP_B_CLOSED] == dr.STEP_PASSED
    assert len(env.fake.calls_to("place_market_close")) == 1
    assert len(env.fake.calls_to("place_entry")) == 1
    assert env.fake.positions.get("BTCUSDT", 0) == 0
    assert statuses_of(recorder)["account_clean"] == dr.STEP_PASSED
    # What the code does after the deadline close (finding F1 of plan 25-12): the plan's stop
    # intent stays UNKNOWN and the operator exit refuses it. The step is a gap, not a pass.
    assert facts["stop_intent_after_close"] == "UNKNOWN"
    assert "UNKNOWN_INTENT_PRESENT" in facts["safe_mode_exit_refusals"]
    assert statuses_of(recorder)["safe_mode_left"] == dr.STEP_NOT_REHEARSED


@pytest.mark.xfail(
    strict=True,
    reason="finding F1 (plan 25-12): after a restart past max_unprotected_ms and the deadline "
    "close, the plan's STOP_LOSS intent stays UNKNOWN and /safemode_exit refuses "
    "UNKNOWN_INTENT_PRESENT; the owner decides whether src should resolve it",
)
async def test_cut_b_a_late_restart_close_lets_the_operator_leave_safe_mode(
    tmp_path: Path,
) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    outcome = await s07_restart_cuts.run(env, recorder, cut="b", late_restart=True)
    assert outcome == dr.OUTCOME_COMPLETE


def statuses_of(recorder: ScenarioRecorder) -> dict[str, str]:
    return _status(recorder)


async def test_cut_b_a_second_place_entry_fails_the_step(tmp_path: Path) -> None:
    """Negative control: if the exchange saw a second entry POST the scenario must stop."""
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    original = s07_restart_cuts.place_entry_calls

    def counted_twice(env_: Any) -> int:
        return original(env_) + 1

    s07_restart_cuts.place_entry_calls = counted_twice  # type: ignore[assignment]
    try:
        with pytest.raises(dr.SmokeHalt):
            await s07_restart_cuts.run(env, recorder, cut="b")
    finally:
        s07_restart_cuts.place_entry_calls = original  # type: ignore[assignment]
    assert _status(recorder)[s07_restart_cuts.STEP_B_ONE_ENTRY] == dr.STEP_FAILED


async def test_cut_b_the_held_call_does_not_survive_the_crash(tmp_path: Path) -> None:
    env, _ = await _run_b(tmp_path)
    assert env.faults.held("place_algo_protective") is False


async def test_cut_b_late_restart_is_only_for_the_twin_and_only_for_cut_b(
    tmp_path: Path,
) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    with pytest.raises(ValueError, match="late_restart"):
        await s07_restart_cuts.run(env, _recorder(), cut="a", late_restart=True)
    demo_like = SimpleNamespace(synthetic=False, label=DEMO_OBSERVED)
    with pytest.raises(ValueError, match="late_restart"):
        await s07_restart_cuts.run(demo_like, _recorder(), cut="b", late_restart=True)


def test_on_demo_the_held_stop_is_fault_injected_and_the_restore_is_observed() -> None:
    recorder = ScenarioRecorder("S07", mode=dr.RunMode.EXECUTE, environ={}, clock=lambda: FAKE_NOW)
    env = SimpleNamespace(synthetic=False, label=DEMO_OBSERVED)
    s07_restart_cuts.record_held_stop(env, recorder, "the stop placement was held")
    s07_restart_cuts.record_restored(env, recorder, "the plan came back UNPROTECTED")
    steps = {step["name"]: step["label"] for step in recorder.steps}
    assert steps[s07_restart_cuts.STEP_B_HELD] == DEMO_FAULT_INJECTED
    assert steps[s07_restart_cuts.STEP_B_RESTORED] == DEMO_OBSERVED


async def test_the_evidence_file_has_the_scenario_schema_and_one_kind(tmp_path: Path) -> None:
    recorder = _recorder()
    await s07_restart_cuts.run(build_fake_scenario_env(tmp_path, EnvOptions()), recorder, cut="c")
    path = recorder.write(tmp_path / "evidence")
    assert path.name.startswith("25-DEMO-SCENARIO-DRYRUN-S07-20261107T120000Z")
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    assert document["schema"] == "demo-scenario-evidence/schema-1"
    assert document["scenario_id"] == "S07"
    assert document["evidence_kinds"] == ["SYNTHETIC"]
    assert document["outcome"] == dr.OUTCOME_COMPLETE
    assert document["details"]["cut"] == "c"


def test_the_twin_names_the_existing_tests_it_reuses() -> None:
    assert len(REUSES) >= 1
    for reference in REUSES:
        path, _, name = reference.partition("::")
        assert name in Path(path).read_text(encoding="utf-8")
