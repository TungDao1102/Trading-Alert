"""S09 (clock skew) on the CI twin: the fake composed process (plan 25-13).

TEST_ONLY, OPS-01. The process clock is skewed beyond the ratified drift limit (twice the larger of
the two limits). The real `ClockDriftGuard` measures it (`measure_clock_drift` over the server time
the twin answers `skew` behind the process clock), blocks new entries (`OUT_OF_LIMITS`), and a
request that is approved and confirmed places nothing; the refusal is journaled. The same
`s09_clock_skew.run(env, recorder)` is what the owner's Demo test calls with an env built with
`EnvOptions(clock_offset=...)`.

Twin-only shim (stated, not hidden): the fake serves `place_entry`, so the real adapter's own
guard method (`_require_entries_allowed`) is called ahead of it, in the order
`BinanceUsdmAdapter.place_entry` runs it. The exchange-side -1021 stays with the owner opt-in probe case
`timestamp_outside_recv_window`.

On the twin every step is SYNTHETIC. On Demo the injected skew is DEMO_FAULT_INJECTED.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import demo_rehearsal as dr
from src.adapters.binance_clock import ClockDriftGuard, DriftBlockReason, DriftVerdict
from src.adapters.binance_limits import DriftLimits

from tests.support.demo_scenarios import s09_clock_skew
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
    "tests/test_clock_drift.py::test_an_out_of_limit_measurement_is_a_successful_verdict_outside_limits",
    "tests/test_clock_drift.py::test_a_minus_1021_never_re_enables_entries_by_itself",
    "tests/test_live_demo_smoke.py::test_a_start_whose_clock_drift_guard_blocks_entries_stops_before_any_card",
)


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def _recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S09", mode=dr.RunMode.DRY_RUN, environ={}, clock=lambda: FAKE_NOW)


def _status(recorder: ScenarioRecorder) -> dict[str, str]:
    return {step["name"]: step["status"] for step in recorder.steps}


def _twin(tmp_path: Path) -> Any:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    s09_clock_skew.install_twin_skew(env)
    return env


async def _run(tmp_path: Path) -> tuple[Any, ScenarioRecorder, str]:
    env = _twin(tmp_path)
    recorder = _recorder()
    outcome = await s09_clock_skew.run(env, recorder)
    return env, recorder, outcome


def test_the_catalog_pins_s09_to_this_plan() -> None:
    s = by_id("S09")
    assert (s.plan, s.module) == ("25-13", "tests/support/demo_scenarios/s09_clock_skew.py")
    assert s.twin_test == "tests/test_demo_twin_s09_clock_skew.py"
    assert s.demo_test == "tests/demo/test_demo_s09_clock_skew.py"
    assert s.requirements == ("OPS-01",)


def test_the_skew_is_twice_the_larger_drift_limit_never_a_literal() -> None:
    limits = DriftLimits(
        ahead_limit_ms=500,
        behind_limit_ms=300,
        include_measurement_uncertainty=True,
        max_measurement_age_seconds=60,
        periodic_remeasure_interval_seconds=None,
    )
    assert s09_clock_skew.skew_for(limits) == timedelta(milliseconds=1000)
    wider = DriftLimits(
        ahead_limit_ms=500,
        behind_limit_ms=900,
        include_measurement_uncertainty=False,
        max_measurement_age_seconds=60,
        periodic_remeasure_interval_seconds=30,
    )
    assert s09_clock_skew.skew_for(wider) == timedelta(milliseconds=1800)


async def test_a_clock_skewed_beyond_the_limit_blocks_entries_and_nothing_is_sent(
    tmp_path: Path,
) -> None:
    env, recorder, outcome = await _run(tmp_path)
    assert outcome == dr.OUTCOME_COMPLETE, recorder.steps
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}
    statuses = _status(recorder)
    for name in (
        "precondition_clean",
        "start",
        s09_clock_skew.STEP_SKEW,
        s09_clock_skew.STEP_GUARD,
        s09_clock_skew.STEP_NOTHING_PLACED,
        s09_clock_skew.STEP_JOURNALED,
        "account_clean",
    ):
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)
    assert env.fake.calls_to("place_entry") == [], "nothing reached the exchange"
    assert env.fake.open_orders == {} and env.fake.open_algos == {}


async def test_the_guard_measured_the_skew_and_reports_out_of_limits(tmp_path: Path) -> None:
    env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["clock_skew"]
    drift = env.assembly.binance_limits.drift
    assert facts["skew_ms"] == 2 * max(drift.ahead_limit_ms, drift.behind_limit_ms)
    assert facts["ahead_limit_ms"] == drift.ahead_limit_ms
    assert facts["behind_limit_ms"] == drift.behind_limit_ms
    assert facts["offset_ms"] == facts["skew_ms"], "the measured offset is the injected skew"
    assert facts["within_limits"] is False
    assert facts["blocked_reason"] == DriftBlockReason.OUT_OF_LIMITS.value
    assert facts["minus_1021_seen"] is False


async def test_the_refused_confirm_is_journaled_before_anything_is_sent(tmp_path: Path) -> None:
    env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["clock_skew"]
    assert facts["refusal_refused"] is True
    assert facts["refusal_reason"], "the refusal reason is journaled and recorded"
    calls = env.faults.calls_to("place_entry")
    assert len(calls) == 1 and calls[0]["mode"] == "override", "the guard refused the one call"


async def test_a_guard_that_does_not_block_fails_the_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control: with entries allowed the scenario must stop before any card."""
    env = _twin(tmp_path)
    monkeypatch.setattr(ClockDriftGuard, "blocked_reason", lambda self, now_utc: None)
    recorder = _recorder()
    with pytest.raises(dr.SmokeHalt):
        await s09_clock_skew.run(env, recorder)
    failed = [step for step in recorder.steps if step["status"] == dr.STEP_FAILED]
    assert failed and failed[0]["name"] == s09_clock_skew.STEP_GUARD
    assert "signal" not in _status(recorder)
    assert env.fake.calls_to("place_entry") == []


def test_a_minus_1021_is_recorded_by_the_guard_state_when_it_occurs() -> None:
    """Assumption A3: if signed calls fail with -1021 the guard has a re-measure pending."""
    guard = ClockDriftGuard(
        limits=DriftLimits(
            ahead_limit_ms=500,
            behind_limit_ms=500,
            include_measurement_uncertainty=False,
            max_measurement_age_seconds=60,
            periodic_remeasure_interval_seconds=None,
        )
    )
    guard.record(
        DriftVerdict(
            offset_ms=0,
            uncertainty_ms=0,
            within_limits=True,
            measurement_failed=False,
            measured_at_utc=FAKE_NOW,
            failure_type=None,
        )
    )
    assert s09_clock_skew.drift_answer(guard, FAKE_NOW)["minus_1021_seen"] is False
    guard.note_clock_skew_error()
    answer = s09_clock_skew.drift_answer(guard, FAKE_NOW)
    assert answer["minus_1021_seen"] is True
    assert answer["blocked_reason"] == DriftBlockReason.STALE.value


def test_the_twin_skew_refuses_a_demo_env() -> None:
    env = SimpleNamespace(synthetic=False, label=DEMO_OBSERVED)
    with pytest.raises(ValueError, match="twin"):
        s09_clock_skew.install_twin_skew(env)


async def test_on_demo_the_injected_skew_is_fault_injected_and_the_guard_is_observed() -> None:
    recorder = ScenarioRecorder("S09", mode=dr.RunMode.EXECUTE, environ={}, clock=lambda: FAKE_NOW)
    env = SimpleNamespace(synthetic=False, label=DEMO_OBSERVED)
    s09_clock_skew.record_skew(env, recorder, "the process clock runs 1000 ms ahead")
    s09_clock_skew.record_reaction(env, recorder, s09_clock_skew.STEP_GUARD, "the guard blocks")
    labels = {step["name"]: step["label"] for step in recorder.steps}
    assert labels[s09_clock_skew.STEP_SKEW] == DEMO_FAULT_INJECTED
    assert labels[s09_clock_skew.STEP_GUARD] == DEMO_OBSERVED


async def test_the_evidence_file_has_the_scenario_schema_and_one_kind(tmp_path: Path) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    document: dict[str, Any] = json.loads(
        recorder.write(tmp_path / "evidence").read_text(encoding="utf-8")
    )
    assert document["schema"] == "demo-scenario-evidence/schema-1"
    assert document["scenario_id"] == "S09"
    assert document["evidence_kinds"] == ["SYNTHETIC"]
    assert document["details"]["clock_skew"]["blocked_reason"] == "OUT_OF_LIMITS"


def test_the_twin_names_the_existing_tests_it_reuses() -> None:
    assert len(REUSES) >= 1
    for reference in REUSES:
        path, _, name = reference.partition("::")
        assert name in Path(path).read_text(encoding="utf-8"), reference
