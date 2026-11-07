"""S12 (DAILY_STOP) on the CI twin: the fake composed process (25-15).

TEST_ONLY, OPS-01. Loss rows are fed through the day-risk reader edge (`user_trades_in_window`,
injected through `FaultEdge.override`); they are sized from the daily stop rate the process loaded
and from the day base it persisted, never from a literal. The day service folds them, the verdict is
DAILY_STOP (latched in the day store for the UTC day) and a CONFIRM afterwards is refused
`DAILY_STOP_BLOCK` with nothing sent. The same `s12_daily_stop.run(env, recorder)` is what the
owner's Demo test calls.

Run S12 LAST in an owner session: DAILY_STOP holds for the UTC day (`leaves_state`).

Finding F1 (pinned as observed, with a strict xfail for the desired behaviour):
`enforce_daily_state` (D-12: cancel the resting entries at DAILY_STOP, keep the stops, alert) is
built and unit-tested but no live composition calls it, so a resting entry stays on the exchange
and no `DAILY_STOP` alert is journaled.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import demo_rehearsal as dr
from src.risk.daily_loss import DayRiskState

from tests.support.demo_scenarios import s12_daily_stop
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
    "tests/test_daily_stop.py::test_latched_daily_stop_cancels_the_entry_keeps_the_stop_and_alerts_after",
    "tests/test_day_risk_service.py::test_a_derived_stop_is_latched_in_the_store_before_the_verdict_returns",
    "tests/test_day_risk_service.py::test_a_restart_inside_the_day_keeps_the_stored_base_and_the_latch",
    "tests/test_day_risk_stream.py::test_an_invalidation_makes_the_loss_unknown_until_the_next_backfill",
    "tests/test_demo_twin_s11_db_outage.py::test_the_close_goes_out_once_reduce_only_while_the_journal_is_down",
)


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def _recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S12", mode=dr.RunMode.DRY_RUN, environ={}, clock=lambda: FAKE_NOW)


def _status(recorder: ScenarioRecorder) -> dict[str, str]:
    return {step["name"]: step["status"] for step in recorder.steps}


async def _run(tmp_path: Path) -> tuple[Any, ScenarioRecorder, str]:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    outcome = await s12_daily_stop.run(env, recorder)
    return env, recorder, outcome


def test_the_catalog_pins_s12_to_this_plan_and_flags_the_held_state() -> None:
    s = by_id("S12")
    assert (s.plan, s.module) == ("25-15", "tests/support/demo_scenarios/s12_daily_stop.py")
    assert s.twin_test == "tests/test_demo_twin_s12_daily_stop.py"
    assert s.demo_test == "tests/demo/test_demo_s12_daily_stop.py"
    assert s.requirements == ("OPS-01",)
    assert s.leaves_state is True


def test_the_scenario_says_to_run_it_last_because_the_stop_holds_for_the_utc_day() -> None:
    doc = s12_daily_stop.__doc__ or ""
    assert "LAST" in doc and "UTC day" in doc
    demo = Path("tests/demo/test_demo_s12_daily_stop.py").read_text(encoding="utf-8")
    assert "LAST" in demo and "UTC day" in demo


async def test_injected_losses_reach_daily_stop_and_the_confirm_is_refused(tmp_path: Path) -> None:
    _env, recorder, outcome = await _run(tmp_path)
    assert outcome == dr.OUTCOME_COMPLETE_WITH_GAPS, recorder.steps
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}
    statuses = _status(recorder)
    for name in (
        "precondition_clean",
        "start",
        s12_daily_stop.STEP_BASELINE,
        s12_daily_stop.STEP_INJECT,
        s12_daily_stop.STEP_LOSS_KNOWN,
        s12_daily_stop.STEP_DAILY_STOP,
        s12_daily_stop.STEP_CONFIRM_REFUSED,
        "account_clean",
    ):
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)
    assert statuses[s12_daily_stop.STEP_RESTING_ENTRY] == dr.STEP_NOT_REHEARSED


async def test_the_loss_is_sized_from_the_loaded_stop_rate_and_the_persisted_day_base(
    tmp_path: Path,
) -> None:
    env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["daily_stop"]
    rate = Decimal(str(env.assembly.params["daily_loss_stop_threshold"]))
    base = Decimal(facts["day_base"])
    assert facts["stop_rate"] == str(env.assembly.params["daily_loss_stop_threshold"])
    assert Decimal(facts["stop_threshold"]) == rate * base
    assert Decimal(facts["injected_loss"]) > Decimal(facts["stop_threshold"])
    assert Decimal(facts["loss_known"]) == Decimal(facts["injected_loss"])
    assert facts["injection_calls"] >= 1, "the backfill read the injected rows"


async def test_the_day_state_moves_to_daily_stop_and_the_latch_is_persisted(
    tmp_path: Path,
) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    verdict = recorder.details["daily_stop"]["verdict"]
    assert verdict["state"] == "DAILY_STOP"
    assert verdict["reason_code"] == "DAILY_STOP_BLOCK"
    assert verdict["latched_in_the_store"] is True
    assert verdict["evaluated_by"] == "scenario"


async def test_a_confirm_under_daily_stop_places_nothing_and_names_the_reason(
    tmp_path: Path,
) -> None:
    env, recorder, _outcome = await _run(tmp_path)
    confirm = recorder.details["daily_stop"]["confirm"]
    assert confirm["decisions"] and all(d["refused"] for d in confirm["decisions"])
    assert confirm["decisions"][-1]["reason"] == "DAILY_STOP_BLOCK"
    assert confirm["place_entry_calls_before"] == confirm["place_entry_calls_after"] == 1
    assert len(env.faults.calls_to("place_entry")) == 1, "only the resting entry was ever sent"


async def test_finding_f1_a_resting_entry_is_not_cancelled_and_no_alert_is_journaled(
    tmp_path: Path,
) -> None:
    """Finding F1 (25-15 SUMMARY), pinned as observed: nothing wires `enforce_daily_state`."""
    _env, recorder, _outcome = await _run(tmp_path)
    resting = recorder.details["daily_stop"]["resting_entry"]
    assert resting["entry_still_open"] is True
    assert resting["cancel_calls_after_the_stop"] == 0
    assert resting["protection_state"] == "AWAITING_FILL"
    assert resting["daily_stop_alerts"] == 0


@pytest.mark.xfail(
    strict=True,
    reason=(
        "25-15 finding F1: enforce_daily_state (D-12: cancel the resting entries at DAILY_STOP, "
        "keep the stops, alert DAILY_STOP) is not called by any live composition, so the resting "
        "entry stays and no DAILY_STOP alert is journaled (plan truth: resting entries are "
        "handled as D033 defines)"
    ),
)
async def test_a_resting_entry_is_cancelled_at_daily_stop_and_the_alert_is_journaled(
    tmp_path: Path,
) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    resting = recorder.details["daily_stop"]["resting_entry"]
    assert resting["entry_still_open"] is False
    assert resting["daily_stop_alerts"] == 1


async def test_the_injection_is_labelled_fault_injected_on_demo() -> None:
    recorder = ScenarioRecorder("S12", mode=dr.RunMode.EXECUTE, environ={}, clock=lambda: FAKE_NOW)
    env = SimpleNamespace(synthetic=False, label=DEMO_OBSERVED)
    s12_daily_stop.record_inject(env, recorder, "loss rows beyond the stop")
    s12_daily_stop.record_reaction(env, recorder, "x", "the verdict is DAILY_STOP")
    labels = {step["name"]: step["label"] for step in recorder.steps}
    assert labels[s12_daily_stop.STEP_INJECT] == DEMO_FAULT_INJECTED
    assert labels["x"] == DEMO_OBSERVED


async def test_losses_that_were_never_injected_stop_the_run_at_the_loss_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control: with no loss rows the day never reaches the stop and the step fails."""
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    monkeypatch.setattr(env.faults, "override", lambda *args, **kwargs: None)
    recorder = _recorder()
    with pytest.raises(dr.SmokeHalt):
        await s12_daily_stop.run(env, recorder)
    failed = [step for step in recorder.steps if step["status"] == dr.STEP_FAILED]
    assert failed and failed[0]["name"] == s12_daily_stop.STEP_LOSS_KNOWN


async def test_a_day_that_is_already_latched_stops_before_anything_is_placed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stop holds for the UTC day: a second run the same day halts at the precondition."""
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    latched = DayRiskState(
        utc_day=date(2026, 10, 9),
        equity_at_day_start=Decimal("4999.09343961"),
        base_observed_at_utc=datetime(2026, 10, 9, 3, 0, tzinfo=UTC),
        stop_latched_at_utc=datetime(2026, 10, 9, 4, 0, tzinfo=UTC),
        warning_alerted_at_utc=None,
    )

    async def already_latched(_env: Any) -> DayRiskState:
        return latched

    monkeypatch.setattr(s12_daily_stop, "persisted_day", already_latched)
    recorder = _recorder()
    with pytest.raises(dr.SmokeHalt):
        await s12_daily_stop.run(env, recorder)
    failed = [step for step in recorder.steps if step["status"] == dr.STEP_FAILED]
    assert failed and failed[0]["name"] == s12_daily_stop.STEP_PRECONDITION
    assert "DAILY_STOP" in failed[0]["detail"] and "UTC day" in failed[0]["detail"]
    assert env.faults.calls_to("place_entry") == []


async def test_the_evidence_file_has_the_scenario_schema_and_one_kind(tmp_path: Path) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    document: dict[str, Any] = json.loads(
        recorder.write(tmp_path / "evidence").read_text(encoding="utf-8")
    )
    assert document["schema"] == "demo-scenario-evidence/schema-1"
    assert document["scenario_id"] == "S12"
    assert document["evidence_kinds"] == ["SYNTHETIC"]
    assert document["details"]["daily_stop"]["verdict"]["state"] == "DAILY_STOP"


def test_the_twin_names_the_existing_tests_it_reuses() -> None:
    assert len(REUSES) >= 1
    for reference in REUSES:
        path, _, name = reference.partition("::")
        assert name in Path(path).read_text(encoding="utf-8"), reference
