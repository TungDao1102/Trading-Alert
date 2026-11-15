"""S06 (replayed and concurrent presses) on the CI twin: the fake composed process (plan 25-10).

TEST_ONLY: the exchange is the Binance-semantics fake, the presses are fake and the stores are in
memory (D-02), so every step is SYNTHETIC. The same `s06_replay.run(env, recorder)` is what the
owner's Demo test calls (D-04, D-05). EXEC-03 and APRV-02: one approved plan, two concurrent
CONFIRM presses and then replays of APPROVE and CONFIRM lead to exactly one `place_entry` and one
non-refused `LIVE_PLACEMENT_OUTCOME`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s06_replay
from tests.support.demo_scenarios.catalog import by_id
from tests.support.demo_scenarios.harness import (
    SYNTHETIC,
    EnvOptions,
    ScenarioPrecondition,
    ScenarioRecorder,
    build_fake_scenario_env,
)
from tests.support.live_rig import forbid_real_sleep

FAKE_NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)

# The existing tests this twin builds on (the coverage inventory of plan 25-17 reads this tuple).
REUSES = (
    "tests/test_live_replay_restart.py::test_two_concurrent_confirm_presses_lead_to_exactly_one_place_entry",
    "tests/test_live_replay_restart.py::test_a_replayed_confirm_places_exactly_one_entry_with_the_derived_client_id",
    "tests/test_live_replay_restart.py::test_a_replayed_approve_keeps_one_decision_and_places_nothing",
)


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def _recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S06", mode=dr.RunMode.DRY_RUN, environ={}, clock=lambda: FAKE_NOW)


def _status(recorder: ScenarioRecorder) -> dict[str, str]:
    return {step["name"]: step["status"] for step in recorder.steps}


def test_the_catalog_pins_s06_to_this_plan() -> None:
    s06 = by_id("S06")
    assert (s06.plan, s06.module) == ("25-10", "tests/support/demo_scenarios/s06_replay.py")
    assert s06.twin_test == "tests/test_demo_twin_s06_replay.py"
    assert s06.demo_test == "tests/demo/test_demo_s06_replay.py"
    assert set(s06.requirements) == {"EXEC-03", "APRV-02"}


async def test_s06_runs_end_to_end_and_every_step_is_synthetic(tmp_path: Path) -> None:
    recorder = _recorder()
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    outcome = await s06_replay.run(env, recorder)
    assert outcome == dr.OUTCOME_COMPLETE and recorder.outcome == outcome
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}
    statuses = _status(recorder)
    for name in (
        "precondition_clean",
        "start",
        "signal",
        "card",
        "approve",
        "confirm_entry",
        s06_replay.STEP_CONCURRENT_CONFIRM,
        s06_replay.STEP_REPLAYS,
        s06_replay.STEP_ONE_OUTCOME,
        s06_replay.STEP_CANCEL_ENTRY,
        "account_clean",
    ):
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)


async def test_the_exchange_saw_exactly_one_place_entry(tmp_path: Path) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await s06_replay.run(env, _recorder())
    assert len(env.fake.calls_to("place_entry")) == 1, "one POST for one approved plan"
    assert len(env.faults.calls_to("place_entry")) == 1, "the edge count the Demo test relies on"


async def test_the_journal_holds_one_non_refused_placement_outcome(tmp_path: Path) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await s06_replay.run(env, _recorder())
    assert env.rig is not None
    rows = env.rig.stores.journal.by_type("LIVE_PLACEMENT_OUTCOME")
    assert len(rows) == 1
    payload = json.loads(rows[0].payload_json)
    assert payload["is_no_trade"] is False
    assert env.rig.stores.journal.by_type("LIVE_PLACEMENT_REFUSED") == []


async def test_the_account_is_clean_and_the_entry_was_cancelled_by_its_id(tmp_path: Path) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await s06_replay.run(env, _recorder())
    (cancel,) = env.fake.calls_to("cancel_normal_order")
    assert cancel["kwargs"]["orig_client_order_id"].startswith("x-")
    assert env.fake.open_orders == {} and env.fake.open_algos == {}
    assert env.fake.calls_to("cancel_algo_order") == [], "no blanket cancel, no protective touched"
    assert env.fake.calls_to("place_algo_protective") == []


async def test_the_press_ids_were_distinct_and_both_reached_the_handler(tmp_path: Path) -> None:
    """The two concurrent CONFIRMs are two handler calls, not one press delivered twice."""
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await s06_replay.run(env, _recorder())
    assert env.rig is not None
    owner_n = env.owner._n  # type: ignore[attr-defined]
    # approve, two confirms, replay approve, replay confirm: five distinct query ids
    assert owner_n == 5


async def test_a_second_place_entry_fails_the_concurrent_step(tmp_path: Path) -> None:
    """Negative control: if the exchange saw a second POST the scenario must stop, not pass."""
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    original = s06_replay.place_entry_calls

    def counted_twice(env_: Any) -> int:
        return original(env_) + 1

    s06_replay.place_entry_calls = counted_twice  # type: ignore[assignment]
    try:
        with pytest.raises(dr.SmokeHalt):
            await s06_replay.run(env, recorder)
    finally:
        s06_replay.place_entry_calls = original  # type: ignore[assignment]
    statuses = _status(recorder)
    assert statuses[s06_replay.STEP_CONCURRENT_CONFIRM] == dr.STEP_FAILED


async def test_a_dirty_account_stops_before_anything_is_placed(tmp_path: Path) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    from decimal import Decimal

    env.fake.positions["BTCUSDT"] = Decimal("0.01")
    recorder = _recorder()
    with pytest.raises(ScenarioPrecondition):
        await s06_replay.run(env, recorder)
    assert env.fake.calls_to("place_entry") == []


async def test_the_evidence_file_has_the_scenario_schema_and_one_kind(tmp_path: Path) -> None:
    recorder = _recorder()
    await s06_replay.run(build_fake_scenario_env(tmp_path, EnvOptions()), recorder)
    path = recorder.write(tmp_path / "evidence")
    assert path.name.startswith("25-DEMO-SCENARIO-DRYRUN-S06-20261107T120000Z")
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    assert document["schema"] == "demo-scenario-evidence/schema-1"
    assert document["scenario_id"] == "S06"
    assert document["evidence_kinds"] == ["SYNTHETIC"]
    assert document["outcome"] == dr.OUTCOME_COMPLETE


def test_the_twin_names_the_existing_tests_it_reuses() -> None:
    assert len(REUSES) >= 1
    for reference in REUSES:
        path, _, name = reference.partition("::")
        assert name in Path(path).read_text(encoding="utf-8")
