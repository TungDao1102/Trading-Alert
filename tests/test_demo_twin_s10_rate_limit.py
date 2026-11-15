"""S10 (rate limit and 418, injected only) on the CI twin: the fake composed process (plan 25-14).

TEST_ONLY, OPS-01, D-07. A 429 or a 418 answer is raised under the REAL adapter (`SdkFaults`) before
anything is sent; the real REST gate records and persists it, the CONFIRM that follows is refused
with nothing sent, nothing is re-sent while the gate is restricted, the reconcile loop journals its
skip and, once the Retry-After has passed, entries are allowed again. The 418 variant (twin only)
takes the ratified fallback wait, raises the ban alert and survives a restart. The same
`s10_rate_limit.run(env, recorder, variant=...)` is what the owner's Demo test calls (429 only).

On the twin every step is SYNTHETIC. On Demo the injection step is DEMO_FAULT_INJECTED.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s10_rate_limit
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
    "tests/test_binance_ratelimit_gate.py::test_valid_retry_after_is_capped_for_ban_and_pause",
    "tests/test_gate_restart.py::test_restart_with_active_418_ban_still_refuses",
    "tests/test_fault_edge.py::test_an_injected_418_under_the_real_adapter_records_a_ban_and_nothing_is_resent",
    "tests/test_fault_edge.py::test_an_injected_429_pauses_the_shared_gate",
)


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def _recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S10", mode=dr.RunMode.DRY_RUN, environ={}, clock=lambda: FAKE_NOW)


def _status(recorder: ScenarioRecorder) -> dict[str, str]:
    return {step["name"]: step["status"] for step in recorder.steps}


async def _run(tmp_path: Path, variant: str = "429") -> tuple[Any, ScenarioRecorder, str]:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    outcome = await s10_rate_limit.run(env, recorder, variant=variant)
    return env, recorder, outcome


def test_the_catalog_pins_s10_to_this_plan() -> None:
    s = by_id("S10")
    assert (s.plan, s.module) == ("25-14", "tests/support/demo_scenarios/s10_rate_limit.py")
    assert s.twin_test == "tests/test_demo_twin_s10_rate_limit.py"
    assert s.demo_test == "tests/demo/test_demo_s10_rate_limit.py"
    assert s.requirements == ("OPS-01",)


async def test_an_injected_429_restricts_the_gate_refuses_the_entry_and_opens_again(
    tmp_path: Path,
) -> None:
    _env, recorder, outcome = await _run(tmp_path)
    assert outcome == dr.OUTCOME_COMPLETE, recorder.steps
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}
    statuses = _status(recorder)
    for name in (
        "precondition_clean",
        "start",
        s10_rate_limit.STEP_BASELINE,
        s10_rate_limit.STEP_INJECT,
        s10_rate_limit.STEP_RESTRICTED,
        s10_rate_limit.STEP_REFUSED,
        s10_rate_limit.STEP_REPLAY,
        s10_rate_limit.STEP_NOT_RESENT,
        s10_rate_limit.STEP_RECONCILE_SKIP,
        s10_rate_limit.STEP_NO_ALERT,
        s10_rate_limit.STEP_OPEN_AGAIN,
        s10_rate_limit.STEP_ENTRY_ALLOWED,
        "account_clean",
    ):
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)


async def test_the_429_pause_is_the_retry_after_and_it_is_persisted(tmp_path: Path) -> None:
    env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["rate_limit"]
    policy = s10_rate_limit.policy_of(env)
    assert facts["retry_after_seconds"] == s10_rate_limit.RETRY_AFTER_SECONDS
    assert facts["retry_after_seconds"] < policy.no_retry_after_wait_429_seconds
    assert facts["restriction_reason"] == "RATE_LIMIT_PAUSE_429"
    assert facts["persisted_wait_seconds"] == facts["retry_after_seconds"], "the header wins"
    assert facts["persisted_other_deadline_is_none"] is True
    assert facts["persisted_deadline_utc"] is not None


async def test_the_confirm_during_the_restriction_places_nothing_and_nothing_is_re_sent(
    tmp_path: Path,
) -> None:
    env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["rate_limit"]
    assert facts["place_entry_calls_at_refusal"] == 0
    assert facts["place_entry_calls_after_replay"] == 0
    assert facts["refusal_reason"] == "UNCERTAIN_ACCOUNT_STATE"
    assert facts["sdk_injected_calls"] == 1 and facts["sdk_injections"] == 1
    assert facts["replay_window_restricted"] is True
    assert facts["sdk_calls_since_arming"] == 1, "one SDK call: the injected one"
    # Only the entry after the pause reached the exchange edge.
    assert len(env.fake.calls_to("place_entry")) == 1
    assert [i.method for i in env.sdk_faults.injections] == [s10_rate_limit.SDK_METHOD]


async def test_the_reconcile_loop_journals_its_gate_skip_and_a_pause_raises_no_ban_alert(
    tmp_path: Path,
) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["rate_limit"]
    assert facts["reconcile_gate_skips"] >= 1
    assert facts["reconcile_skip_reasons"] == ["RATE_LIMIT_PAUSE_429"]
    assert facts["ban_alerts"] == []


async def test_a_418_takes_the_ratified_fallback_alerts_and_survives_a_restart(
    tmp_path: Path,
) -> None:
    env, recorder, outcome = await _run(tmp_path, "418")
    assert outcome == dr.OUTCOME_COMPLETE, recorder.steps
    facts = recorder.details["rate_limit"]
    policy = s10_rate_limit.policy_of(env)
    assert facts["restriction_reason"] == "IP_BAN_418"
    assert facts["fallback_418_seconds"] == policy.no_retry_after_wait_418_seconds
    assert facts["persisted_wait_seconds"] == policy.no_retry_after_wait_418_seconds
    (alert,) = facts["ban_alerts"]
    assert (alert["event"], alert["reason"], alert["subject"]) == (
        "REST_GATE_BAN_ENTERED",
        "IP_BAN_418",
        "SYSTEM",
    )
    assert alert["until_utc"], "the alert carries the gate's own deadline"
    restart = facts["restart"]
    assert restart["admitted"] is True and restart["enabled"] is False
    assert restart["restored_reason"] == "IP_BAN_418"
    assert restart["restored_until_utc"] == restart["expected_until_utc"]
    statuses = _status(recorder)
    for name in (s10_rate_limit.STEP_ALERT, s10_rate_limit.STEP_RESTART, "account_clean"):
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)
    assert len(env.fake.calls_to("place_entry")) == 0, "nothing is sent under a ban"


async def test_the_418_variant_is_twin_only_and_refused_before_anything_is_recorded() -> None:
    recorder = ScenarioRecorder("S10", mode=dr.RunMode.EXECUTE, environ={}, clock=lambda: FAKE_NOW)
    demo_env = SimpleNamespace(synthetic=False, label=DEMO_OBSERVED)
    with pytest.raises(ValueError, match="S19"):
        await s10_rate_limit.run(demo_env, recorder, variant="418")
    assert recorder.steps == []


async def test_an_unknown_variant_is_refused() -> None:
    recorder = _recorder()
    with pytest.raises(ValueError, match="unknown variant"):
        await s10_rate_limit.run(SimpleNamespace(synthetic=True), recorder, variant="503")
    assert recorder.steps == []


def test_the_retry_after_must_be_shorter_than_the_cap_and_the_fallback() -> None:
    ok = SimpleNamespace(retry_after_cap_seconds=999, no_retry_after_wait_429_seconds=33)
    assert s10_rate_limit.retry_after_for(ok) == s10_rate_limit.RETRY_AFTER_SECONDS
    too_short_cap = SimpleNamespace(retry_after_cap_seconds=5, no_retry_after_wait_429_seconds=33)
    with pytest.raises(ValueError, match="cap"):
        s10_rate_limit.retry_after_for(too_short_cap)
    too_short_fallback = SimpleNamespace(
        retry_after_cap_seconds=999, no_retry_after_wait_429_seconds=10
    )
    with pytest.raises(ValueError, match="fallback"):
        s10_rate_limit.retry_after_for(too_short_fallback)


async def test_the_injection_is_labelled_fault_injected_on_demo() -> None:
    recorder = ScenarioRecorder("S10", mode=dr.RunMode.EXECUTE, environ={}, clock=lambda: FAKE_NOW)
    env = SimpleNamespace(synthetic=False, label=DEMO_OBSERVED)
    s10_rate_limit.record_inject(env, recorder, "an HTTP 429 is raised")
    s10_rate_limit.record_reaction(env, recorder, "x", "the gate recorded it")
    labels = {step["name"]: step["label"] for step in recorder.steps}
    assert labels[s10_rate_limit.STEP_INJECT] == DEMO_FAULT_INJECTED
    assert labels["x"] == DEMO_OBSERVED


async def test_an_answer_that_was_never_injected_stops_at_the_restriction_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control: with no armed answer the gate stays open and the step fails."""
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    monkeypatch.setattr(env.sdk_faults, "fail_sdk", lambda *args, **kwargs: None)
    recorder = _recorder()
    with pytest.raises(dr.SmokeHalt):
        await s10_rate_limit.run(env, recorder)
    failed = [step for step in recorder.steps if step["status"] == dr.STEP_FAILED]
    assert failed and failed[0]["name"] in (
        s10_rate_limit.STEP_RESTRICTED,
        s10_rate_limit.STEP_REFUSED,
    )


async def test_the_evidence_file_has_the_scenario_schema_and_one_kind(tmp_path: Path) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    document: dict[str, Any] = json.loads(
        recorder.write(tmp_path / "evidence").read_text(encoding="utf-8")
    )
    assert document["schema"] == "demo-scenario-evidence/schema-1"
    assert document["scenario_id"] == "S10"
    assert document["evidence_kinds"] == ["SYNTHETIC"]
    assert document["details"]["rate_limit"]["restriction_reason"] == "RATE_LIMIT_PAUSE_429"


def test_the_twin_names_the_existing_tests_it_reuses() -> None:
    assert len(REUSES) >= 1
    for reference in REUSES:
        path, _, name = reference.partition("::")
        assert name in Path(path).read_text(encoding="utf-8"), reference
