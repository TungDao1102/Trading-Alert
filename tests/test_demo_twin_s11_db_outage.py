"""S11 (DB outage during a risk-reducing close) on the CI twin: the fake composed process (25-14).

TEST_ONLY, OPS-01, R-24. S04's trigger (the stop is rejected after the fill) with the journal store
made unavailable at the same moment: the reduce-only close is still sent and the position goes flat,
the audit rows the journal refused land in the local spill, SAFE_MODE DB_FAILURE is entered and
entries are refused; once the database is back the operator exit restores entries and the next start
replays the spill into the journal (every row present once). The same
`s11_db_outage.run(env, recorder)` is what the owner's Demo test calls. The real PostgreSQL outage
(`docker compose stop postgres`) is not part of this scenario.

On the twin every step is SYNTHETIC. On Demo the injection step is DEMO_FAULT_INJECTED and the close
is a real Demo order (DEMO_OBSERVED).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s11_db_outage
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
    "tests/test_protection_sweep_spill.py::test_the_flat_sweep_spills_its_audit_rows_and_finishes_while_the_journal_is_down",
    "tests/test_risk_first_spill.py::test_act_then_record_keeps_the_spill_when_the_journal_is_down",
    "tests/test_risk_first_spill.py::test_replay_spill_records_the_event_once_and_a_second_replay_is_a_noop",
    "tests/test_risk_first_write_ahead.py::test_with_the_journal_down_the_record_waits_for_the_spill_and_is_kept",
    "tests/test_demo_twin_s04_stop_rejected.py::test_one_reduce_only_market_close_under_an_xc_id_flattens_the_position",
)


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def _recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S11", mode=dr.RunMode.DRY_RUN, environ={}, clock=lambda: FAKE_NOW)


def _status(recorder: ScenarioRecorder) -> dict[str, str]:
    return {step["name"]: step["status"] for step in recorder.steps}


async def _run(tmp_path: Path) -> tuple[Any, ScenarioRecorder, str]:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    outcome = await s11_db_outage.run(env, recorder)
    return env, recorder, outcome


def test_the_catalog_pins_s11_to_this_plan() -> None:
    s = by_id("S11")
    assert (s.plan, s.module) == ("25-14", "tests/support/demo_scenarios/s11_db_outage.py")
    assert s.twin_test == "tests/test_demo_twin_s11_db_outage.py"
    assert s.demo_test == "tests/demo/test_demo_s11_db_outage.py"
    assert s.requirements == ("OPS-01",)


async def test_a_db_outage_during_the_close_still_closes_spills_and_enters_safe_mode(
    tmp_path: Path,
) -> None:
    _env, recorder, outcome = await _run(tmp_path)
    assert outcome in (dr.OUTCOME_COMPLETE, dr.OUTCOME_COMPLETE_WITH_GAPS), recorder.steps
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}
    statuses = _status(recorder)
    for name in (
        "precondition_clean",
        "start",
        s11_db_outage.STEP_BASELINE,
        s11_db_outage.STEP_INJECT,
        s11_db_outage.STEP_CLOSE,
        s11_db_outage.STEP_SPILLED,
        s11_db_outage.STEP_SAFE_MODE,
        s11_db_outage.STEP_ENTRY_REFUSED,
        s11_db_outage.STEP_EXIT,
        s11_db_outage.STEP_REPLAYED,
        "account_clean",
    ):
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)


async def test_the_close_goes_out_once_reduce_only_while_the_journal_is_down(
    tmp_path: Path,
) -> None:
    env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["db_outage"]
    assert facts["stop_placements"] == 1, "the stop is never resent"
    assert facts["stop_injected"] == 1
    assert facts["close_calls"] == 1
    assert facts["close_client_id"].startswith("xc-")
    assert facts["position_flat"] is True
    assert facts["journal_write_failures"] >= 1
    assert len(env.fake.calls_to("place_market_close")) == 1
    assert facts["place_entry_calls_at_refusal"] == 1, "the refused request sent nothing"


async def test_the_refused_audit_rows_are_in_the_spill_with_a_db_failure_safe_mode(
    tmp_path: Path,
) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["db_outage"]
    types = set(facts["spilled_event_types"])
    assert {"EMERGENCY_CLOSE", "SAFE_MODE_ENTER", "OPERATIONAL_ALERT"} <= types
    assert facts["emergency_close_phases_spilled"] == ["pre_send"]
    assert "DB_FAILURE" in facts["safe_mode_reasons_spilled"]
    assert facts["in_safe_mode_after_the_close"] is True
    assert facts["entry_refusal_reason"] == "RECONCILIATION_REQUIRED"


async def test_the_spill_is_replayed_at_the_next_start_every_row_present_once(
    tmp_path: Path,
) -> None:
    env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["db_outage"]
    replay = facts["replay"]
    assert replay["replayed"] == facts["spilled_count"] > 0
    assert replay["already_present"] == 0
    assert replay["failed"] == [] and replay["conflicts"] == []
    assert replay["spill_pending_after"] == 0
    assert replay["all_in_the_journal_once"] is True
    assert len(set(replay["replayed_ids"])) == len(replay["replayed_ids"])
    # The twin's journal really holds the rows now.
    journal = env.rig.stores.journal
    assert all(journal.get(i) is not None for i in replay["replayed_ids"])


async def test_finding_f1_a_restart_after_an_outage_close_starts_in_safe_mode(
    tmp_path: Path,
) -> None:
    """Finding F1 b (25-14 SUMMARY), pinned as observed: the closed plan's PROTECTION_TRANSITION
    rows were not spilled (RUNBOOK 21.2), so the restart rebuilds the plan as live and the
    reconcile enters SAFE_MODE. A src change that spills them would change this step on purpose."""
    _env, recorder, outcome = await _run(tmp_path)
    facts = recorder.details["db_outage"]
    restart = facts["restart"]
    statuses = _status(recorder)
    assert restart["admitted"] is True
    assert restart["in_safe_mode"] is True and restart["enabled"] is False
    assert restart["plans_restored"] == 1
    assert statuses[s11_db_outage.STEP_RESTART_CLEAN] == dr.STEP_NOT_REHEARSED
    assert outcome == dr.OUTCOME_COMPLETE_WITH_GAPS
    assert statuses.get(s11_db_outage.STEP_SECOND_EXIT) == dr.STEP_PASSED
    # The restart settles it: the reconcile writes the end row to a healthy journal and the sweep
    # releases the reservation.
    assert facts["counted_reservations_after_the_restart"] == []


async def test_finding_f1_a_the_closed_plans_reservation_stays_counted_after_the_exit(
    tmp_path: Path,
) -> None:
    """Finding F1 a (25-14 SUMMARY), pinned as observed: the reservation sweep reads the FLAT row
    from the journal, and that row was lost in the outage, so the reservation stays RESERVED."""
    _env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["db_outage"]
    statuses = _status(recorder)
    assert facts["entry_after_exit_placed"] is False
    assert facts["entry_after_exit_refusal_reason"] == "CLUSTER_CAP_REJECT"
    assert facts["counted_reservations_after_the_exit"] == ["RESERVED"]
    assert statuses[s11_db_outage.STEP_ENTRY_ALLOWED] == dr.STEP_NOT_REHEARSED
    assert facts["place_entry_calls_at_refusal"] == 1, "the refused request sent nothing"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "F1 a: the coordinator's PROTECTION_TRANSITION rows are not spilled while the journal is "
        "down, so the reservation sweep never sees the FLAT row and the next request on the "
        "cluster is refused CLUSTER_CAP_REJECT until a restart (plan truth: the documented exit "
        "restores entries)"
    ),
)
async def test_after_the_database_returns_and_the_exit_a_new_request_is_placed(
    tmp_path: Path,
) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    assert recorder.details["db_outage"]["entry_after_exit_placed"] is True


async def test_the_injection_is_labelled_fault_injected_on_demo() -> None:
    recorder = ScenarioRecorder("S11", mode=dr.RunMode.EXECUTE, environ={}, clock=lambda: FAKE_NOW)
    env = SimpleNamespace(synthetic=False, label=DEMO_OBSERVED)
    s11_db_outage.record_inject(env, recorder, "the stop is rejected and the journal is down")
    s11_db_outage.record_reaction(env, recorder, "x", "the close was sent")
    labels = {step["name"]: step["label"] for step in recorder.steps}
    assert labels[s11_db_outage.STEP_INJECT] == DEMO_FAULT_INJECTED
    assert labels["x"] == DEMO_OBSERVED


async def test_an_outage_that_was_never_injected_leaves_no_spill_and_fails_the_spill_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control: with a healthy journal nothing is spilled and the step stops the run."""
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    monkeypatch.setattr(env.store_faults, "fail_store", lambda *args, **kwargs: None)
    recorder = _recorder()
    with pytest.raises(dr.SmokeHalt):
        await s11_db_outage.run(env, recorder)
    failed = [step for step in recorder.steps if step["status"] == dr.STEP_FAILED]
    assert failed and failed[0]["name"] == s11_db_outage.STEP_SPILLED


async def test_the_evidence_file_has_the_scenario_schema_and_one_kind(tmp_path: Path) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    document: dict[str, Any] = json.loads(
        recorder.write(tmp_path / "evidence").read_text(encoding="utf-8")
    )
    assert document["schema"] == "demo-scenario-evidence/schema-1"
    assert document["scenario_id"] == "S11"
    assert document["evidence_kinds"] == ["SYNTHETIC"]
    assert document["details"]["db_outage"]["close_calls"] == 1


def test_the_twin_names_the_existing_tests_it_reuses() -> None:
    assert len(REUSES) >= 1
    for reference in REUSES:
        path, _, name = reference.partition("::")
        assert name in Path(path).read_text(encoding="utf-8"), reference
