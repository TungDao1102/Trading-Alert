"""Unit tests of the scenario harness: labels, recorder, catalog, clean start and cleanup (25-08).

TEST_ONLY: the env is the composed process on the Binance-semantics fake with memory stores, the
exchange state is made-up values, and nothing here touches Binance (D-02). The Demo account of an
owner session is only ever read through the same helpers, so a dirty start is refused with the
`scripts/demo_clear.py` instruction (Pitfall 8, T-25-20).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import demo_rehearsal as dr
from src.domain.enums import TradePlanStatus

from tests.support.demo_scenarios.catalog import SCENARIOS, Scenario, by_id
from tests.support.demo_scenarios.harness import (
    DEMO_FAULT_INJECTED,
    DEMO_OBSERVED,
    NOT_OBSERVED,
    SYNTHETIC,
    EnvOptions,
    FakeScenarioEnv,
    ScenarioPrecondition,
    ScenarioRecorder,
    account_clean,
    build_fake_scenario_env,
    ensure_clean_start,
    label_for,
)
from tests.support.demo_scenarios.s01_happy import run as run_s01
from tests.support.live_rig import forbid_real_sleep

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
D = Decimal


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def _recorder(scenario_id: str = "S01", **kwargs: Any) -> ScenarioRecorder:
    kwargs.setdefault("mode", dr.RunMode.DRY_RUN)
    return ScenarioRecorder(scenario_id, clock=lambda: NOW, **kwargs)


async def _leave_resting_order(env: Any, client_id: str = "leftover-client-id") -> None:
    await env.fake.place_entry(
        symbol=dr.SYMBOL,
        new_client_order_id=client_id,
        quantity=D("0.001"),
        side="BUY",
        position_side="BOTH",
        time_in_force="GTC",
        price=D("100"),
    )


# ----- labels ------------------------------------------------------------------------------ #


def test_a_synthetic_env_is_synthetic_whatever_injected_says() -> None:
    env = SimpleNamespace(synthetic=True)
    assert label_for(env, injected=False) == SYNTHETIC
    assert label_for(env, injected=True) == SYNTHETIC


def test_a_demo_env_labels_an_injected_trigger_as_injected_never_observed() -> None:
    env = SimpleNamespace(synthetic=False)
    assert label_for(env, injected=True) == DEMO_FAULT_INJECTED
    assert label_for(env, injected=False) == DEMO_OBSERVED


# ----- recorder ---------------------------------------------------------------------------- #


def test_the_default_label_follows_the_run_mode() -> None:
    assert _recorder().default_label == SYNTHETIC
    assert _recorder(mode=dr.RunMode.EXECUTE).default_label == DEMO_OBSERVED


def test_add_step_carries_the_default_label_and_a_labeled_step_its_own() -> None:
    recorder = _recorder(mode=dr.RunMode.EXECUTE)
    recorder.add_step("a", "PASSED", "d")
    recorder.add_labeled_step("b", "PASSED", "d", label=DEMO_FAULT_INJECTED)
    recorder.add_labeled_step("c", "NOT_REHEARSED", "d", label=NOT_OBSERVED)
    assert [s["label"] for s in recorder.steps] == [
        DEMO_OBSERVED,
        DEMO_FAULT_INJECTED,
        NOT_OBSERVED,
    ]
    assert recorder.to_dict()["evidence_kinds"] == sorted(
        [DEMO_OBSERVED, DEMO_FAULT_INJECTED, NOT_OBSERVED]
    )


def test_a_synthetic_recorder_refuses_a_demo_label() -> None:
    recorder = _recorder()
    for label in (DEMO_OBSERVED, DEMO_FAULT_INJECTED, NOT_OBSERVED):
        with pytest.raises(ValueError, match="synthetic"):
            recorder.add_labeled_step("x", "PASSED", "d", label=label)
    assert recorder.steps == []


def test_an_unknown_label_or_scenario_is_refused() -> None:
    with pytest.raises(ValueError, match="label"):
        _recorder(default_label="OBSERVED_ISH")
    with pytest.raises(ValueError, match="label"):
        _recorder(mode=dr.RunMode.EXECUTE).add_labeled_step("x", "PASSED", "d", label="REAL")
    with pytest.raises(KeyError):
        _recorder("S99")


def test_the_document_has_the_scenario_schema_and_the_file_stem_follows_the_mode() -> None:
    dry = _recorder("S04")
    execute = _recorder("S04", mode=dr.RunMode.EXECUTE)
    assert dry.to_dict()["schema"] == "demo-scenario-evidence/schema-1"
    assert dry.to_dict()["scenario_id"] == "S04"
    assert dry._file_stem() == "25-DEMO-SCENARIO-DRYRUN-S04-20261107T120000Z"
    assert execute._file_stem() == "25-DEMO-SCENARIO-EVIDENCE-S04-20261107T120000Z"


def test_record_health_keeps_facts_only() -> None:
    at = NOW + timedelta(seconds=5)
    verdict = SimpleNamespace(
        is_no_trade=True,
        degraded_names=("stream",),
        results=(
            SimpleNamespace(check_name="rest", status="PASS", observed_at_utc=NOW),
            SimpleNamespace(check_name="mark", status="FAIL", observed_at_utc=at),
            SimpleNamespace(check_name="stream", status="DEGRADED", observed_at_utc=NOW),
        ),
    )
    recorder = _recorder()
    recorder.record_health(verdict)
    recorder.record_health(None)
    first, second = recorder.details["health"]
    assert first["is_no_trade"] is True
    assert first["degraded"] == ["stream"] and first["failing"] == ["mark"]
    assert first["at"] == at.isoformat() or str(first["at"]).startswith("2026-11-07T12:00:05")
    assert second == {"is_no_trade": None, "degraded": [], "failing": [], "at": None}
    json.dumps(recorder.to_dict())


# ----- catalog ----------------------------------------------------------------------------- #

_ALLOWED_PLANS = {"25-06", "25-08", *(f"25-{n}" for n in range(10, 17))}
_ALLOWED_REQUIREMENTS = {"EXEC-01", "EXEC-02", "EXEC-03", "APRV-01", "APRV-02", "OPS-01", "OPS-02"}


def test_ids_are_unique_and_ordered() -> None:
    ids = [s.id for s in SCENARIOS]
    assert ids == [f"S{n:02d}" for n in range(1, 21)]
    assert len({s.slug for s in SCENARIOS}) == 20


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_every_entry_follows_the_naming_rule(scenario: Scenario) -> None:
    if scenario.observation_only:
        assert scenario.id == "S20"
        assert (scenario.module, scenario.twin_test, scenario.demo_test) == (None, None, None)
        assert scenario.plan == "25-06" and not scenario.leaves_state
        return
    stem = f"s{scenario.id[1:]}_{scenario.slug}"
    assert re.fullmatch(r"[a-z0-9_]+", scenario.slug)
    assert scenario.module == f"tests/support/demo_scenarios/{stem}.py"
    assert scenario.twin_test == f"tests/test_demo_twin_{stem}.py"
    assert scenario.demo_test == f"tests/demo/test_demo_{stem}.py"
    assert scenario.plan in _ALLOWED_PLANS - {"25-06"}
    assert scenario.title and scenario.roadmap_bullet


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_every_entry_names_known_requirements(scenario: Scenario) -> None:
    assert scenario.requirements
    assert set(scenario.requirements) <= _ALLOWED_REQUIREMENTS


def test_by_id_returns_the_entry_and_refuses_an_unknown_id() -> None:
    assert by_id("S12").leaves_state is True
    assert by_id("S01").leaves_state is False
    with pytest.raises(KeyError):
        by_id("S21")


# ----- the fake factory --------------------------------------------------------------------- #


def test_the_fake_factory_refuses_a_clock_offset_it_cannot_apply(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="clock_offset"):
        build_fake_scenario_env(tmp_path, EnvOptions(clock_offset=timedelta(seconds=3)))


async def test_the_restart_env_is_a_scenario_env_too(tmp_path: Path) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    assert isinstance(env, FakeScenarioEnv) and env.restart is not None
    second = await env.restart()
    assert isinstance(second, FakeScenarioEnv)
    assert second.faults is env.faults
    await second.abandon()


# ----- clean start and cleanup -------------------------------------------------------------- #


async def test_a_clean_account_passes_the_precondition(tmp_path: Path) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    await ensure_clean_start(env, recorder)
    (step,) = recorder.steps
    assert (step["name"], step["status"], step["label"]) == (
        "precondition_clean",
        dr.STEP_PASSED,
        SYNTHETIC,
    )


async def test_a_leftover_resting_order_stops_the_start_with_the_clear_instruction(
    tmp_path: Path,
) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await _leave_resting_order(env)
    recorder = _recorder()
    with pytest.raises(ScenarioPrecondition) as raised:
        await ensure_clean_start(env, recorder)
    message = str(raised.value)
    assert "scripts/demo_clear.py" in message
    assert "normal_orders=1" in message and "algo_orders=0" in message
    assert "positions=0" in message and "open_approvals=0" in message
    assert "leftover-client-id" not in message, "counts only, never ids"
    (step,) = recorder.steps
    assert (step["name"], step["status"]) == ("precondition_clean", dr.STEP_FAILED)
    assert "leftover-client-id" not in step["detail"]


async def test_a_leftover_position_stops_the_start(tmp_path: Path) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await _leave_resting_order(env)
    env.fake.fill("leftover-client-id", quantity=D("0.001"))
    adapter = env.assembly.exchange.adapter
    assert await adapter.snapshot_open_normal_orders(symbol=dr.SYMBOL) == []
    with pytest.raises(ScenarioPrecondition, match=r"positions=1"):
        await ensure_clean_start(env, _recorder())


async def test_a_pending_card_of_a_real_process_counts_as_an_open_approval(
    tmp_path: Path,
) -> None:
    """The real reader over the in-memory shadow store sees a card the process issued."""
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    await dr._bring_up(env, recorder, "start")
    ids = await dr._inject(env, recorder, "fill", "signal")
    for _ in range(env.wait_ticks):
        row = await env.assembly.executor.read(
            env.wiring.stores.entities.get_trade_plan, ids.trade_plan_id
        )
        if row is not None:
            break
        await env.tick()
    with pytest.raises(ScenarioPrecondition, match=r"open_approvals=1"):
        await ensure_clean_start(env, _recorder())
    # Closed the official way (DOMN-04, the transition scripts/demo_clear.py makes): clean again.
    await env.assembly.executor.write(
        env.wiring.stores.entities.transition_trade_plan,
        ids.trade_plan_id,
        TradePlanStatus.EXPIRED,
        now_utc=env.clock(),
    )
    await ensure_clean_start(env, _recorder())


async def test_account_clean_records_passed_then_failed_with_the_same_counts(
    tmp_path: Path,
) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    assert await account_clean(env, recorder) is True
    await _leave_resting_order(env)
    assert await account_clean(env, recorder) is False
    passed, failed = recorder.steps
    assert (passed["name"], passed["status"]) == ("account_clean", dr.STEP_PASSED)
    assert (failed["name"], failed["status"]) == ("account_clean", dr.STEP_FAILED)
    assert "normal_orders=1" in failed["detail"] and "scripts/demo_clear.py" in failed["detail"]
    assert "leftover-client-id" not in failed["detail"]


async def test_the_account_is_clean_again_after_the_happy_path(tmp_path: Path) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await run_s01(env, _recorder())
    recorder = _recorder()
    await ensure_clean_start(env, recorder)
    assert [s["status"] for s in recorder.steps] == [dr.STEP_PASSED]
