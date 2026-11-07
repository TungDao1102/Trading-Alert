"""S08 (WS disconnect and listenKey expiry) on the CI twin: the fake composed process (plan 25-13).

TEST_ONLY, EXEC-02, OPS-01, D-07. The process's REAL `UserDataSupervisor` runs over a scripted
`SupervisedAdapter` (the twin's websocket edge) and every reaction is the production code's: the
state machine, the bounded reconnect, the after-gap REST snapshot, the sinks into health, reconcile
and SAFE_MODE. The same `s08_stream_loss.run(env, recorder, trigger=...)` is what the owner's Demo
test calls with the Demo trigger (the supervisor's own rebuild).

On the twin every step is SYNTHETIC. On Demo the injected drop is DEMO_FAULT_INJECTED, a step that
could not be produced (a real listenKey expiry) is NOT_OBSERVED.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s08_stream_loss as s08
from tests.support.demo_scenarios.catalog import by_id
from tests.support.demo_scenarios.harness import (
    DEMO_FAULT_INJECTED,
    DEMO_OBSERVED,
    NOT_OBSERVED,
    SYNTHETIC,
    EnvOptions,
    ScenarioRecorder,
    build_fake_scenario_env,
)
from tests.support.live_rig import forbid_real_sleep

FAKE_NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)

# The existing tests this twin builds on (the coverage inventory of plan 25-17 reads this tuple).
REUSES = (
    "tests/test_userdata_supervisor.py::test_tracer_start_live_close_unknown_rebuild_snapshot_live_after_gap",
    "tests/test_userdata_supervisor.py::test_listen_key_expired_event_rekeys_and_resyncs",
    "tests/test_live_stream_to_protection.py::test_a_gap_makes_the_equity_and_the_day_loss_unknown",
    "tests/test_reconcile_stream_divergences.py::test_a_halted_supervisor_is_a_divergence_enters_user_data_stream_halted_and_alerts",
    "tests/test_live_feed_source.py::test_silence_beyond_the_limit_is_stale_even_when_the_stream_says_live",
)


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def _recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S08", mode=dr.RunMode.DRY_RUN, environ={}, clock=lambda: FAKE_NOW)


def _status(recorder: ScenarioRecorder) -> dict[str, str]:
    return {step["name"]: step["status"] for step in recorder.steps}


def _twin(tmp_path: Path) -> tuple[Any, Any]:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    return env, s08.install_scripted_stream(env)


async def _run(tmp_path: Path, **kwargs: Any) -> tuple[Any, Any, ScenarioRecorder, str]:
    env, trigger = _twin(tmp_path)
    recorder = _recorder()
    outcome = await s08.run(env, recorder, trigger=trigger, **kwargs)
    return env, trigger, recorder, outcome


def test_the_catalog_pins_s08_to_this_plan() -> None:
    s = by_id("S08")
    assert (s.plan, s.module) == ("25-13", "tests/support/demo_scenarios/s08_stream_loss.py")
    assert s.twin_test == "tests/test_demo_twin_s08_stream_loss.py"
    assert s.demo_test == "tests/demo/test_demo_s08_stream_loss.py"
    assert s.requirements == ("EXEC-02", "OPS-01")


async def test_a_lost_stream_is_refused_reconciled_and_left_only_after_live_again(
    tmp_path: Path,
) -> None:
    env, _trigger, recorder, outcome = await _run(tmp_path)
    assert outcome == dr.OUTCOME_COMPLETE, recorder.steps
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}
    statuses = _status(recorder)
    for name in (
        "precondition_clean",
        "start",
        s08.STEP_BASELINE,
        s08.STEP_DROP,
        s08.STEP_GAP_HEALTH,
        s08.STEP_ENTRY_IN_GAP,
        s08.STEP_SILENCE,
        s08.STEP_NO_SELF_RESYNC,
        s08.STEP_RESTORED,
        s08.STEP_SAFE_MODE_EXIT,
        s08.STEP_CATCH_UP,
        s08.STEP_EXPIRY,
        s08.STEP_STATES,
        "account_clean",
    ):
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)


async def test_while_the_stream_is_not_live_health_says_no_trade_and_the_confirm_places_nothing(
    tmp_path: Path,
) -> None:
    env, _trigger, recorder, _outcome = await _run(tmp_path)
    gap = recorder.details["gap"]
    assert gap["state_after_drop"] == "UNKNOWN"
    assert gap["health_no_trade"] is True
    assert set(s08.HEALTH_STREAM_CHECKS) <= set(gap["health_failing"])
    assert gap["place_entry_calls"] == 0, "the CONFIRM during the gap placed nothing"
    assert gap["placement_refusal"] in {"UNCERTAIN_ACCOUNT_STATE", "RECONCILIATION_REQUIRED"}
    assert gap["safe_mode_reason"] in s08.SILENCE_REASONS
    assert gap["exit_refused_while_not_live"] is True
    # The only entry of the run is the one placed AFTER the documented exit.
    assert len(env.fake.calls_to("place_entry")) == 1


async def test_a_halted_stream_stays_down_until_a_resync_is_asked_for(tmp_path: Path) -> None:
    """Finding F2: nothing in src calls `request_resync()`; the scenario is the stand-in."""
    _env, trigger, recorder, _outcome = await _run(tmp_path)
    window = recorder.details["gap"]["no_self_resync"]
    assert window["state"] == "UNKNOWN"
    assert window["new_transitions"] == 0
    assert window["rebuild_calls_before"] == window["rebuild_calls_after"]
    assert recorder.details["resync_requested_by_scenario"] >= 2
    assert trigger.adapter.counts["rebuild"] >= 5


async def test_the_rest_reconcile_finds_the_order_change_the_stream_never_delivered(
    tmp_path: Path,
) -> None:
    env, trigger, recorder, _outcome = await _run(tmp_path)
    catch_up = recorder.details["catch_up"]
    assert catch_up["stream_items_queued"] == 0, "no frame was delivered for the change"
    assert catch_up["protection_state"] == "ENTRY_ENDED_NO_FILL"
    assert catch_up["snapshot_calls_after"] > catch_up["snapshot_calls_before"]
    assert trigger.adapter.queue.qsize() == 0


async def test_every_state_the_supervisor_reported_is_recorded_for_the_exit_row(
    tmp_path: Path,
) -> None:
    _env, _trigger, recorder, _outcome = await _run(tmp_path)
    states = recorder.details["stream_states"]
    assert ["UNKNOWN", "CONNECTION_CLOSED"] in states
    assert ["SYNCING", "SNAPSHOT"] in states
    assert ["LIVE", "SNAPSHOT_OK"] in states
    assert states[-1] == ["LIVE", "SNAPSHOT_OK"]


async def test_a_listen_key_expired_item_rekeys_the_stream_once_and_reconciles(
    tmp_path: Path,
) -> None:
    _env, trigger, recorder, _outcome = await _run(tmp_path)
    expiry = recorder.details["expiry"]
    assert expiry["transitions"] == [
        ["UNKNOWN", "LISTEN_KEY_EXPIRED"],
        ["SYNCING", "SNAPSHOT"],
        ["LIVE", "SNAPSHOT_OK"],
    ]
    assert expiry["rekey_calls"] == 1
    assert expiry["live_entries"] == 1, "no duplicate state change"
    assert expiry["snapshot_calls_after"] > expiry["snapshot_calls_before"]
    assert expiry["safe_mode"] is False
    assert trigger.adapter.counts["rekey"] == 1


async def test_a_confirm_right_after_the_drop_is_refused_by_the_invalidated_equity(
    tmp_path: Path,
) -> None:
    """Before any reconcile tick can enter SAFE_MODE the gap itself refuses the CONFIRM.

    The supervisor's UNKNOWN transition invalidates the equity and the day loss (STREAM_GAP), so
    the inputs of the placement are refused (`UNCERTAIN_ACCOUNT_STATE`); the health verdict is
    journaled but is not what refuses.
    """
    env, _trigger, recorder, outcome = await _run(tmp_path, early_confirm=True)
    assert outcome == dr.OUTCOME_COMPLETE, recorder.steps
    early = recorder.details["early_confirm"]
    assert early["health_no_trade_at_confirm"] is True
    assert early["place_entry_calls"] == 0
    assert early["safe_mode_at_confirm"] is False, "SAFE_MODE was not yet needed"
    assert early["placement_refusal"] == "UNCERTAIN_ACCOUNT_STATE"
    assert _status(recorder)[s08.STEP_ENTRY_IN_GAP] == dr.STEP_PASSED
    assert _status(recorder)["account_clean"] == dr.STEP_PASSED
    assert env.fake.calls_to("place_entry") == []


async def test_an_early_confirm_that_places_an_entry_fails_the_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, trigger = _twin(tmp_path)
    recorder = _recorder()
    monkeypatch.setattr(s08, "place_entry_calls", lambda env_: 1)
    with pytest.raises(dr.SmokeHalt):
        await s08.run(env, recorder, trigger=trigger, early_confirm=True)
    failed = [step for step in recorder.steps if step["status"] == dr.STEP_FAILED]
    assert failed and failed[0]["name"] == s08.STEP_ENTRY_IN_GAP


def test_early_confirm_needs_a_trigger_that_holds_the_stream_down() -> None:
    env = SimpleNamespace(synthetic=False, label=DEMO_OBSERVED)

    async def go() -> None:
        await s08.run(env, _demo_recorder(), trigger=s08.DemoStreamTrigger(), early_confirm=True)

    with pytest.raises(ValueError, match="holds"):
        asyncio.run(go())


async def test_a_placement_that_gets_through_the_gap_fails_the_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control: if the exchange saw an entry while the stream was down, stop."""
    env, trigger = _twin(tmp_path)
    recorder = _recorder()
    monkeypatch.setattr(s08, "place_entry_calls", lambda env_: 1)
    with pytest.raises(dr.SmokeHalt):
        await s08.run(env, recorder, trigger=trigger)
    failed = [step for step in recorder.steps if step["status"] == dr.STEP_FAILED]
    assert failed and failed[0]["name"] == s08.STEP_ENTRY_IN_GAP


async def test_a_drop_that_never_recovers_halts_and_names_the_exit_rows(tmp_path: Path) -> None:
    env, trigger = _twin(tmp_path)

    async def never(env_: Any) -> None:
        return None

    trigger.release = never  # the reconnect keeps failing
    recorder = _recorder()
    with pytest.raises(dr.SmokeHalt):
        await s08.run(env, recorder, trigger=trigger)
    failed = {step["name"]: step for step in recorder.steps if step["status"] == dr.STEP_FAILED}
    assert s08.STEP_RESTORED in failed


def _demo_stub(*, synthetic: bool) -> Any:
    return SimpleNamespace(synthetic=synthetic, label=SYNTHETIC if synthetic else DEMO_OBSERVED)


def _demo_recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S08", mode=dr.RunMode.EXECUTE, environ={}, clock=lambda: FAKE_NOW)


def test_on_demo_the_drop_is_fault_injected_and_a_missing_expiry_is_not_observed() -> None:
    recorder = _demo_recorder()
    env = _demo_stub(synthetic=False)
    s08.record_injection_step(env, recorder, "the drop", name=s08.STEP_DROP)
    s08.record_gap(env, recorder, s08.STEP_EXPIRY, "needs 60 minutes")
    s08.record_step(env, recorder, s08.STEP_RESTORED, "the supervisor reconnected")
    labels = {step["name"]: step["label"] for step in recorder.steps}
    assert labels[s08.STEP_DROP] == DEMO_FAULT_INJECTED
    assert labels[s08.STEP_EXPIRY] == NOT_OBSERVED
    assert labels[s08.STEP_RESTORED] == DEMO_OBSERVED
    assert {s["name"]: s["status"] for s in recorder.steps}[
        s08.STEP_EXPIRY
    ] == dr.STEP_NOT_REHEARSED


async def test_the_demo_drop_posts_a_close_event_of_the_current_connection() -> None:
    posted: list[Any] = []
    supervisor = SimpleNamespace(_on_connection_event=posted.append)
    stream = SimpleNamespace(supervisor=supervisor, adapter=SimpleNamespace(epoch=7))
    env = SimpleNamespace(wiring=SimpleNamespace(stream=stream), clock=lambda: FAKE_NOW)
    await s08.DemoStreamTrigger().drop(env)
    (event,) = posted
    assert (event.name, event.epoch, event.at_utc) == ("close", 7, FAKE_NOW)


async def test_the_demo_expiry_is_not_observed_unless_the_owner_sets_the_slow_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(s08.SLOW_ENV, raising=False)
    answer = await s08.DemoStreamTrigger().expire(_demo_stub(synthetic=False), None)
    assert answer != "EXPIRED" and s08.SLOW_ENV in answer and "60 minutes" in answer
    assert os.environ.get(s08.SLOW_ENV) is None


async def test_the_evidence_file_has_the_scenario_schema_and_one_kind(tmp_path: Path) -> None:
    _env, _trigger, recorder, _outcome = await _run(tmp_path)
    document: dict[str, Any] = json.loads(
        recorder.write(tmp_path / "evidence").read_text(encoding="utf-8")
    )
    assert document["schema"] == "demo-scenario-evidence/schema-1"
    assert document["scenario_id"] == "S08"
    assert document["evidence_kinds"] == ["SYNTHETIC"]
    assert document["details"]["stream_states"]


def test_the_twin_names_the_existing_tests_it_reuses() -> None:
    assert len(REUSES) >= 1
    for reference in REUSES:
        path, _, name = reference.partition("::")
        assert name in Path(path).read_text(encoding="utf-8"), reference
