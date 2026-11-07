"""S17 (stale feed drill, G2-016, D058) on the CI twin: the fake composed process (plan 25-13).

TEST_ONLY, OPS-01, D-06. A mark reading older than the configured mark-price age is injected at the
two readers the live process uses (the public reader that feeds the health check and the reconcile
feed check, and the signed adapter's `get_mark_price` that the pre-placement check reads). The
reaction is the production code's: the market-feed health check FAILs, the pre-placement gate
refuses the CONFIRM (fail closed, nothing sent), an active plan with a stale feed enters SAFE_MODE
STALE_FEED with a STALE_DATA alert, a fresh reading never leaves SAFE_MODE by itself and the
operator exit re-allows entries. The same `s17_stale_feed.run(env, recorder)` is what the owner's
Demo test calls.

On the twin every step is SYNTHETIC. On Demo the injection steps are DEMO_FAULT_INJECTED.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s17_stale_feed
from tests.support.demo_scenarios.catalog import by_id
from tests.support.demo_scenarios.harness import (
    DEMO_FAULT_INJECTED,
    DEMO_OBSERVED,
    SYNTHETIC,
    EnvOptions,
    ScenarioRecorder,
    build_fake_scenario_env,
)
from tests.support.execution_limits import test_only_execution_limits
from tests.support.live_rig import forbid_real_sleep

FAKE_NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)

# The existing tests this twin builds on (the coverage inventory of plan 25-17 reads this tuple).
REUSES = (
    "tests/test_live_feed_source.py::test_silence_beyond_the_limit_is_stale_even_when_the_stream_says_live",
    "tests/test_live_feed_source.py::test_the_loop_judges_a_dead_feed_through_the_live_feed_source",
    "tests/test_feed_freshness.py::test_only_the_asked_symbols_are_judged",
    "tests/test_drills.py::test_stale_feed_drill_enters_safe_mode_through_the_loops_feed_check",
)


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def _recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S17", mode=dr.RunMode.DRY_RUN, environ={}, clock=lambda: FAKE_NOW)


def _status(recorder: ScenarioRecorder) -> dict[str, str]:
    return {step["name"]: step["status"] for step in recorder.steps}


async def _run(tmp_path: Path) -> tuple[Any, ScenarioRecorder, str]:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    outcome = await s17_stale_feed.run(env, recorder)
    return env, recorder, outcome


def test_the_catalog_pins_s17_to_this_plan() -> None:
    s = by_id("S17")
    assert (s.plan, s.module) == ("25-13", "tests/support/demo_scenarios/s17_stale_feed.py")
    assert s.twin_test == "tests/test_demo_twin_s17_stale_feed.py"
    assert s.demo_test == "tests/demo/test_demo_s17_stale_feed.py"
    assert s.requirements == ("OPS-01",)


async def test_a_stale_mark_fails_the_feed_check_refuses_the_entry_and_enters_safe_mode(
    tmp_path: Path,
) -> None:
    _env, recorder, outcome = await _run(tmp_path)
    assert outcome == dr.OUTCOME_COMPLETE, recorder.steps
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}
    statuses = _status(recorder)
    for name in (
        "precondition_clean",
        "start",
        s17_stale_feed.STEP_BASELINE,
        s17_stale_feed.STEP_INJECT,
        s17_stale_feed.STEP_FEED_CHECK,
        s17_stale_feed.STEP_REFUSED,
        s17_stale_feed.STEP_SAFE_MODE,
        s17_stale_feed.STEP_ALERT,
        s17_stale_feed.STEP_FRESH,
        s17_stale_feed.STEP_EXIT,
        s17_stale_feed.STEP_ENTRIES_ALLOWED,
        "account_clean",
    ):
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)


async def test_the_stale_age_is_twice_the_configured_bound_never_a_literal(
    tmp_path: Path,
) -> None:
    env, recorder, _outcome = await _run(tmp_path)
    limits = env.assembly.config.limits
    bound = max(limits.stale_feed_max_mark_price_age_ms, limits.max_mark_price_age_ms)
    facts = recorder.details["stale"]
    assert facts["stale_age_ms"] == 2 * bound
    assert facts["feed_bound_ms"] == limits.stale_feed_max_mark_price_age_ms
    assert facts["pre_placement_bound_ms"] == limits.max_mark_price_age_ms
    assert s17_stale_feed.stale_age(limits) == timedelta(milliseconds=2 * bound)


def test_a_limit_that_is_not_configured_is_refused_never_defaulted() -> None:
    limits = test_only_execution_limits()
    unset = SimpleNamespace(
        stale_feed_max_mark_price_age_ms=None,
        max_mark_price_age_ms=limits.max_mark_price_age_ms,
    )
    with pytest.raises(ValueError, match="stale_feed.max_mark_price_age_ms"):
        s17_stale_feed.stale_age(unset)


async def test_the_confirm_on_a_stale_pre_placement_mark_is_refused_with_nothing_sent(
    tmp_path: Path,
) -> None:
    env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["stale"]
    assert facts["place_entry_calls_at_refusal"] == 0
    assert facts["refusal_event"] in {"LIVE_PLACEMENT_REFUSED", "LIVE_PLACEMENT_OUTCOME"} or (
        facts["refusal_event"] == "DEMO_CONFIRM_EXPIRED"
    )
    assert facts["refusal_reason"], "the refusal reason is journaled and recorded"
    injected = [c for c in env.faults.calls_to("get_mark_price") if c.get("injected") is True]
    assert injected, "the pre-placement mark was served stale"
    assert len(env.fake.calls_to("place_entry")) == 1, "only the entry after the exit"


async def test_the_stale_feed_reaction_is_safe_mode_and_a_stale_data_alert(tmp_path: Path) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["stale"]
    assert "market_feed_freshness" in facts["health_failing"]
    assert facts["safe_mode_reason"] == "STALE_FEED"
    assert ["STALE_DATA", "MARK_PRICE_STALE"] in facts["alerts"]
    assert facts["health_failing_after_fresh"] == []
    assert facts["safe_mode_after_fresh"] is True, "a fresh reading never leaves SAFE_MODE"


async def test_the_injection_is_labelled_fault_injected_on_demo() -> None:
    recorder = ScenarioRecorder("S17", mode=dr.RunMode.EXECUTE, environ={}, clock=lambda: FAKE_NOW)
    env = SimpleNamespace(synthetic=False, label=DEMO_OBSERVED)
    s17_stale_feed.record_inject(env, recorder, "stale marks armed")
    s17_stale_feed.record_reaction(env, recorder, "x", "the feed check failed")
    labels = {step["name"]: step["label"] for step in recorder.steps}
    assert labels[s17_stale_feed.STEP_INJECT] == DEMO_FAULT_INJECTED
    assert labels["x"] == DEMO_OBSERVED


async def test_a_stale_mark_that_was_never_armed_fails_the_feed_check_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control: with no stale reading the feed check stays PASS and the step stops."""
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    monkeypatch.setattr(env.faults, "stale_mark", lambda *args, **kwargs: None)
    recorder = _recorder()
    with pytest.raises(dr.SmokeHalt):
        await s17_stale_feed.run(env, recorder)
    failed = [step for step in recorder.steps if step["status"] == dr.STEP_FAILED]
    assert failed and failed[0]["name"] == s17_stale_feed.STEP_FEED_CHECK


async def test_the_evidence_file_has_the_scenario_schema_and_one_kind(tmp_path: Path) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    document: dict[str, Any] = json.loads(
        recorder.write(tmp_path / "evidence").read_text(encoding="utf-8")
    )
    assert document["schema"] == "demo-scenario-evidence/schema-1"
    assert document["scenario_id"] == "S17"
    assert document["evidence_kinds"] == ["SYNTHETIC"]
    assert document["details"]["stale"]["safe_mode_reason"] == "STALE_FEED"


def test_the_twin_names_the_existing_tests_it_reuses() -> None:
    assert len(REUSES) >= 1
    for reference in REUSES:
        path, _, name = reference.partition("::")
        assert name in Path(path).read_text(encoding="utf-8"), reference
