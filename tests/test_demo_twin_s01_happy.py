"""S01 (happy path) on the CI twin: the scenario harness over the fake composed process (25-08).

TEST_ONLY: the exchange is the Binance-semantics fake, the presses are fake and the stores are in
memory (D-02), so every step of these runs is labelled SYNTHETIC; nothing here is, or is reported
as, Demo-observed. The same `s01_happy.run(env, recorder)` is what the owner's Demo test calls
(D-04, D-05), so the assertions cannot drift between the two environments.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.shadow_fakes import assert_live_text
from tests.support.demo_scenarios import harness
from tests.support.demo_scenarios.catalog import SCENARIOS, by_id
from tests.support.demo_scenarios.harness import (
    SYNTHETIC,
    EnvOptions,
    ScenarioRecorder,
    build_fake_scenario_env,
)
from tests.support.demo_scenarios.s01_happy import run
from tests.support.fault_edge import FaultEdge, SdkFaults, StoreFaults
from tests.support.live_rig import forbid_real_sleep
from tests.test_live_demo_smoke import SENTINELS

FAKE_NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)

# The existing tests this twin builds on (the coverage inventory of plan 25-17 reads this tuple).
REUSES = (
    "tests/test_live_demo_smoke.py::test_the_whole_sequence_runs_on_the_composed_process_and_is_synthetic",
    "tests/test_live_demo_smoke.py::test_one_entry_is_placed_gtd_limit_with_no_entry_time_stop_and_no_replay_places",
    "tests/test_live_demo_smoke.py::test_no_secret_reaches_the_evidence_file_or_stdout",
)


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def _recorder(environ: dict[str, str] | None = None) -> ScenarioRecorder:
    return ScenarioRecorder(
        "S01", mode=dr.RunMode.DRY_RUN, environ=environ or {}, clock=lambda: FAKE_NOW
    )


def test_the_catalog_pins_s01_to_this_plan_and_every_scenario_id() -> None:
    assert [s.id for s in SCENARIOS] == [f"S{n:02d}" for n in range(1, 21)]
    assert [s.id for s in SCENARIOS if s.observation_only] == ["S20"]
    s01 = by_id("S01")
    assert (s01.plan, s01.module) == ("25-08", "tests/support/demo_scenarios/s01_happy.py")
    assert s01.twin_test == "tests/test_demo_twin_s01_happy.py"


def test_the_fake_env_carries_the_fault_objects_of_the_options(tmp_path: Path) -> None:
    faults, sdk, store = FaultEdge(), SdkFaults(), StoreFaults()
    env = build_fake_scenario_env(
        tmp_path, EnvOptions(faults=faults, sdk_faults=sdk, store_faults=store)
    )
    assert env.synthetic is True
    assert env.faults is faults and env.sdk_faults is sdk and env.store_faults is store


def test_omitted_faults_are_fresh_objects(tmp_path: Path) -> None:
    first = build_fake_scenario_env(tmp_path / "a", EnvOptions())
    second = build_fake_scenario_env(tmp_path / "b", EnvOptions())
    assert isinstance(first.faults, FaultEdge)
    assert isinstance(first.sdk_faults, SdkFaults)
    assert isinstance(first.store_faults, StoreFaults)
    assert first.faults is not second.faults


async def test_s01_runs_end_to_end_and_every_step_is_synthetic(tmp_path: Path) -> None:
    recorder = _recorder()
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    outcome = await run(env, recorder)
    assert outcome == dr.OUTCOME_COMPLETE
    assert recorder.steps, "the run recorded no step"
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}
    statuses = {step["name"]: step["status"] for step in recorder.steps}
    for name in dr._SMOKE_STEPS:
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)
    assert recorder.outcome == outcome


async def test_the_evidence_file_has_the_scenario_schema_name_and_one_kind(
    tmp_path: Path,
) -> None:
    recorder = _recorder()
    await run(build_fake_scenario_env(tmp_path, EnvOptions()), recorder)
    path = recorder.write(tmp_path / "evidence")
    assert path.name.startswith("25-DEMO-SCENARIO-DRYRUN-S01-20261107T120000Z")
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    assert document["schema"] == "demo-scenario-evidence/schema-1"
    assert document["scenario_id"] == "S01"
    assert document["evidence_kinds"] == ["SYNTHETIC"]
    assert all(step["label"] == "SYNTHETIC" for step in document["steps"])
    assert document["details"]["evidence_kind"] == "SYNTHETIC"


async def test_no_sentinel_secret_reaches_the_evidence_file(tmp_path: Path) -> None:
    recorder = _recorder(SENTINELS)
    await run(build_fake_scenario_env(tmp_path, EnvOptions()), recorder)
    for secret in SENTINELS.values():
        recorder.record_failure_name("probe", "ValueError", f"leaked {secret}")
    text = recorder.write(tmp_path / "evidence").read_text(encoding="utf-8")
    for secret in SENTINELS.values():
        assert secret not in text


async def test_every_card_the_run_sent_passes_the_live_text_check(tmp_path: Path) -> None:
    """APRV-01: the symbol, direction, entry, stop, targets, risk and expiry are on each card."""
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await run(env, _recorder())
    cards = [m.text for m in env.rig.bot.sent if "BTCUSDT" in m.text]
    assert cards, "no approval card was sent"
    for text in cards:
        assert_live_text(text, "DEMO")


async def test_the_run_records_the_health_facts_without_judging_them(tmp_path: Path) -> None:
    recorder = _recorder()
    await run(build_fake_scenario_env(tmp_path, EnvOptions()), recorder)
    (entry,) = recorder.details["health"]
    assert set(entry) == {"is_no_trade", "degraded", "failing", "at"}


def test_the_twin_names_the_existing_tests_it_reuses() -> None:
    assert len(REUSES) >= 1
    for reference in REUSES:
        path, _, name = reference.partition("::")
        assert name in Path(path).read_text(encoding="utf-8")


def test_the_harness_module_exposes_the_fixture_contract_names() -> None:
    assert harness.FIXTURE_SCENARIO_RECORDER == "scenario_recorder"
    assert harness.FIXTURE_MAKE_DEMO_ENV == "make_demo_env"
