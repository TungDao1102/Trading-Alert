"""S05 (cancel racing a fill) on the CI twin: the fake composed process (plan 25-10; EXEC-01).

TEST_ONLY: the exchange is the Binance-semantics fake, so every step is SYNTHETIC. The race is made
deterministic with the fault edge's hold/release on `cancel_normal_order`: the entry cancel of the
expiry path (`expire_pending_entry`, the call the scheduled cancel makes) is held at the exchange,
the entry fills while it is held, then the cancel is released and finds the order already filled.
The same `s05_cancel_race.run(env, recorder)` is what the owner's Demo test calls: there nothing is
held and the race is best effort, DEMO_OBSERVED only if the fill really crossed the cancel and
NOT_OBSERVED otherwise (T-25-25).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import demo_rehearsal as dr
from src.domain.enums import OrderRole
from src.execution.cancel_verification import CancelVerdict
from src.execution.order_ids import derive_algo_client_id
from src.execution.protection import ProtectionState
from src.live.wiring import TASK_SCHEDULED_CANCEL

from tests.support.demo_scenarios import s05_cancel_race, s06_replay
from tests.support.demo_scenarios.catalog import by_id
from tests.support.demo_scenarios.harness import (
    DEMO_OBSERVED,
    NOT_OBSERVED,
    SYNTHETIC,
    EnvOptions,
    ScenarioRecorder,
    build_fake_scenario_env,
)
from tests.support.live_rig import forbid_real_sleep
from tests.support.virtual_time import yield_to_loop

D = Decimal
FAKE_NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)

# The existing tests this twin builds on (the coverage inventory of plan 25-17 reads this tuple).
REUSES = (
    "tests/test_live_scheduled_cancel.py::test_an_unfilled_entry_past_its_plan_expiry_is_cancelled_by_its_client_id",
    "tests/test_live_scheduled_cancel.py::test_a_fully_filled_entry_is_left_to_the_coordinator",
    "tests/test_protection_cancel_lag.py::test_a_lagging_by_id_query_after_the_cancel_is_a_success",
)


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def _recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S05", mode=dr.RunMode.DRY_RUN, environ={}, clock=lambda: FAKE_NOW)


def _status(recorder: ScenarioRecorder) -> dict[str, str]:
    return {step["name"]: step["status"] for step in recorder.steps}


def _entry_id(env: Any) -> str:
    (placement,) = env.fake.calls_to("place_entry")
    return str(placement["kwargs"]["new_client_order_id"])


def test_the_catalog_pins_s05_to_this_plan() -> None:
    s05 = by_id("S05")
    assert (s05.plan, s05.module) == ("25-10", "tests/support/demo_scenarios/s05_cancel_race.py")
    assert s05.twin_test == "tests/test_demo_twin_s05_cancel_race.py"
    assert s05.demo_test == "tests/demo/test_demo_s05_cancel_race.py"
    assert s05.requirements == ("EXEC-01",)


async def test_a_fill_that_crosses_a_held_cancel_ends_protected_and_clean(tmp_path: Path) -> None:
    recorder = _recorder()
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    outcome = await s05_cancel_race.run(env, recorder)
    assert outcome == dr.OUTCOME_COMPLETE, recorder.steps
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}
    statuses = _status(recorder)
    for name in (
        "precondition_clean",
        "start",
        "confirm_entry",
        s05_cancel_race.STEP_RACE,
        s05_cancel_race.STEP_PROTECTED,
        s05_cancel_race.STEP_NO_ORPHAN,
        s06_replay.STEP_CLOSE,
        "account_clean",
    ):
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)
    race = recorder.details["cancel_race"]
    assert race["pre_status"] == "NEW" and race["verdict"] == "FILLED_OR_PARTIAL"
    assert race["crossed"] is True


async def test_the_cancel_was_held_while_the_entry_filled_and_found_it_already_filled(
    tmp_path: Path,
) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await s05_cancel_race.run(env, _recorder())
    entry_id = _entry_id(env)
    record = env.fake.history[entry_id]
    assert record.status == "FILLED", "the cancel never converted the filled entry to CANCELED"
    assert record.executed_quantity == record.quantity
    cancels = env.faults.calls_to("cancel_normal_order")
    assert cancels and all(c["kwargs"]["orig_client_order_id"] == entry_id for c in cancels)
    assert not env.faults.held("cancel_normal_order"), "the hold was released"
    rows = env.rig.stores.journal.by_type("ENTRY_EXPIRY")
    assert any("FILLED_OR_PARTIAL" in row.payload_json for row in rows), "cancel_unverified audit"
    assert not any('"post_cancel"' in row.payload_json for row in rows), "no false post_cancel"


async def test_the_fill_is_protected_with_one_stop_and_no_orphan_or_second_entry(
    tmp_path: Path,
) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await s05_cancel_race.run(env, _recorder())
    assert len(env.fake.calls_to("place_entry")) == 1, "no second entry"
    plan_hash = _entry_id(env).removeprefix("x-")
    assert plan_hash
    stop_calls = [
        c
        for c in env.fake.calls_to("place_algo_protective")
        if c["kwargs"]["client_algo_id"].endswith("SL")
    ]
    assert len(stop_calls) == 1 and stop_calls[0]["kwargs"]["close_position"] is True
    assert env.fake.open_orders == {} and env.fake.open_algos == {}
    assert env.fake.positions.get("BTCUSDT", D(0)) == D(0), "flat at the end"


async def test_without_a_scripted_fill_the_cancel_wins_and_the_race_is_not_rehearsed(
    tmp_path: Path,
) -> None:
    """The Demo-like branch on the fake: nothing is held and nothing fills, so the cancel wins."""
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    env.deliver_fill = None
    recorder = _recorder()
    outcome = await s05_cancel_race.run(env, recorder)
    assert outcome == dr.OUTCOME_COMPLETE_WITH_GAPS
    statuses = _status(recorder)
    assert statuses[s05_cancel_race.STEP_RACE] == dr.STEP_NOT_REHEARSED
    assert statuses["account_clean"] == dr.STEP_PASSED
    assert recorder.details["cancel_race"]["verdict"] == "CANCELED"
    assert recorder.details["cancel_race"]["crossed"] is False
    assert env.fake.calls_to("place_algo_protective") == [], "nothing filled, nothing to protect"
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}


@pytest.mark.parametrize(
    ("pre_status", "verdict", "crossed"),
    [
        ("NEW", CancelVerdict.FILLED_OR_PARTIAL, True),
        ("NEW", CancelVerdict.CANCELED, False),
        ("FILLED", CancelVerdict.FILLED_OR_PARTIAL, False),
        ("PARTIALLY_FILLED", CancelVerdict.FILLED_OR_PARTIAL, False),
        ("NEW", CancelVerdict.UNKNOWN, False),
    ],
)
def test_the_fill_crossed_the_cancel_only_when_the_entry_rested_before_it(
    pre_status: str, verdict: CancelVerdict, crossed: bool
) -> None:
    assert s05_cancel_race.crossed(pre_status, verdict) is crossed


def _stub_env(*, synthetic: bool) -> Any:
    return SimpleNamespace(synthetic=synthetic, label=SYNTHETIC if synthetic else DEMO_OBSERVED)


def _demo_recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S05", mode=dr.RunMode.EXECUTE, environ={}, clock=lambda: FAKE_NOW)


def test_on_demo_a_crossed_race_is_demo_observed_and_a_missed_one_is_not_observed() -> None:
    seen, missed = _demo_recorder(), _demo_recorder()
    s05_cancel_race.record_race_step(_stub_env(synthetic=False), seen, "NEW", "FILLED_OR_PARTIAL")
    s05_cancel_race.record_race_step(
        _stub_env(synthetic=False), missed, "FILLED", "FILLED_OR_PARTIAL"
    )
    (seen_step,) = seen.steps
    (missed_step,) = missed.steps
    assert seen_step["label"] == DEMO_OBSERVED and seen_step["status"] == dr.STEP_PASSED
    assert missed_step["label"] == NOT_OBSERVED and missed_step["status"] == dr.STEP_NOT_REHEARSED
    assert "FILLED" in missed_step["detail"], "the observed order of events is in the detail"


async def test_the_scheduled_cancel_task_racing_a_fill_leaves_the_fill_to_the_coordinator(
    tmp_path: Path,
) -> None:
    """The real `scheduled_cancel` task body past the plan expiry, its cancel held, a fill lands."""
    recorder = _recorder()
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder.default_label = env.label
    s06_replay.start_evidence(env, recorder)
    await dr._bring_up(env, recorder, "start")
    first = await s06_replay.place_approved_entry(env, recorder, "fill")
    await env.pause((first.expiry_utc - env.clock()).total_seconds() + 1)
    specs = {spec.name: spec for spec in env.wiring.specs}

    env.faults.hold("cancel_normal_order")
    task = asyncio.ensure_future(specs[TASK_SCHEDULED_CANCEL].run())
    for _ in range(5000):
        if env.faults.held("cancel_normal_order") or task.done():
            break
        await yield_to_loop()
    assert env.faults.held("cancel_normal_order"), "the scheduled cancel reached the exchange"
    assert env.deliver_fill is not None
    await env.deliver_fill(first)
    env.faults.release("cancel_normal_order")
    await task

    assert env.fake.history[first.entry_client_id].status == "FILLED"

    async def protected() -> bool:
        view = env.wiring.coordinator.protection_of(first.plan_hash)
        return view is not None and view.stop_confirmed_at_utc is not None

    assert await dr._wait_until(env, protected)
    view = env.wiring.coordinator.protection_of(first.plan_hash)
    assert view is not None and view.state is not ProtectionState.CLOSE_REQUIRED
    stop_id = derive_algo_client_id(plan_hash=first.plan_hash, role=OrderRole.STOP_LOSS.value)
    assert stop_id in env.fake.open_algos
    assert len(env.fake.calls_to("place_entry")) == 1
    await dr._smoke_read(env, env.wiring.stores.entities.get_trade_plan, first.trade_plan_id)
    await s06_replay.shutdown(env)


async def test_the_evidence_file_has_the_scenario_schema_and_one_kind(tmp_path: Path) -> None:
    recorder = _recorder()
    await s05_cancel_race.run(build_fake_scenario_env(tmp_path, EnvOptions()), recorder)
    document: dict[str, Any] = json.loads(
        recorder.write(tmp_path / "evidence").read_text(encoding="utf-8")
    )
    assert document["schema"] == "demo-scenario-evidence/schema-1"
    assert document["scenario_id"] == "S05"
    assert document["evidence_kinds"] == ["SYNTHETIC"]
    assert document["details"]["cancel_race"]["crossed"] is True


def test_the_twin_names_the_existing_tests_it_reuses() -> None:
    assert len(REUSES) >= 1
    for reference in REUSES:
        path, _, name = reference.partition("::")
        assert name in Path(path).read_text(encoding="utf-8")
