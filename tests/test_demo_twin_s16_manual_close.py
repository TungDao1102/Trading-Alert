"""S16 (manual close outside the system, G2-016, G4-035) on the CI twin: the fake composed process.

TEST_ONLY, EXEC-02, OPS-01. A system plan is filled and protected; a test actor then closes the
whole position with a reduce-only MARKET order the system did not send. The real coordinator and
reconcile loop must end flat, with no divergence, no SAFE_MODE and no orphan protective leg, and
the system must not send a close of its own. The same `s16_manual_close.run(env, recorder)` is what
the owner's Demo test calls.

Twin model (A3, labelled): on Demo (2026-10-22, `20-DEFERRED.md`) the closePosition legs ended
EXPIRED when the position was closed outside the system and none was orphaned. The fake exchange
has no such expiry, so the twin ends the closePosition legs (the stop and TP2) as EXPIRED itself,
right after the actor's close, and records that as a SYNTHETIC step. That Binance record covers
closePosition legs only; the explicit-quantity TP1 is not covered, so the twin leaves it open and
the system's own sweep ends it. The variant `legs="stay"` ends nothing: the orphan branch of
G4-035, in which the system must remove every leg itself. On Demo the legs' final status is read
from the exchange and recorded verbatim by status code; nothing is modelled.

The actor calls the adapter the edge wraps (`env.faults.inner`), so the edge ledger only holds what
the system sent: it must hold no close at all.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import demo_rehearsal as dr
from src.execution.order_ids import is_system_client_id

from tests.support.demo_scenarios import s16_manual_close
from tests.support.demo_scenarios.catalog import by_id
from tests.support.demo_scenarios.harness import (
    DEMO_OBSERVED,
    SYNTHETIC,
    EnvOptions,
    ScenarioRecorder,
    build_fake_scenario_env,
)
from tests.support.live_rig import forbid_real_sleep

FAKE_NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
_BINANCE_ID = re.compile(r"^[\.A-Z\:/a-z0-9_-]{1,36}$")

# The existing tests this twin builds on (the coverage inventory of plan 25-17 reads this tuple).
REUSES = (
    "tests/test_drills.py::test_manual_close_drill_removes_the_legs_that_stayed_after_a_filled_entry",
    "tests/test_drills.py::test_manual_close_drill_orphan_variant_sweeps_the_legs_that_stayed_after_a_failed_read",
    "tests/test_drills.py::test_manual_close_drill_auto_cancel_variant_has_nothing_to_sweep",
    "tests/test_drills.py::test_manual_close_drill_with_the_position_still_open_never_cancels_the_stop",
    "tests/test_reconcile_tp1_fill.py::test_tp1_filled_and_position_reduced_is_no_divergence",
)


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def _recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S16", mode=dr.RunMode.DRY_RUN, environ={}, clock=lambda: FAKE_NOW)


def _status(recorder: ScenarioRecorder) -> dict[str, str]:
    return {step["name"]: step["status"] for step in recorder.steps}


async def _run(tmp_path: Path, *, legs: str = s16_manual_close.LEGS_EXPIRE) -> Any:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    outcome = await s16_manual_close.run(env, recorder, legs=legs)
    return env, recorder, outcome


def test_the_catalog_pins_s16_to_this_plan_and_flags_the_held_state() -> None:
    s = by_id("S16")
    assert (s.plan, s.module) == ("25-16", "tests/support/demo_scenarios/s16_manual_close.py")
    assert s.twin_test == "tests/test_demo_twin_s16_manual_close.py"
    assert s.demo_test == "tests/demo/test_demo_s16_manual_close.py"
    assert s.requirements == ("EXEC-02", "OPS-01")
    assert s.leaves_state is True


# ---- the actor and the labels ------------------------------------------------------------------ #


def test_an_actor_client_id_can_never_be_taken_for_a_system_id() -> None:
    client_id = s16_manual_close.actor_client_id("close", 1_762_603_200, 3)
    assert not is_system_client_id(client_id)
    assert _BINANCE_ID.match(client_id) and client_id.startswith(s16_manual_close.ACTOR_ID_PREFIX)


def test_actor_and_leg_steps_carry_the_env_label_and_the_exchange_status_verbatim() -> None:
    demo = SimpleNamespace(synthetic=False, label=DEMO_OBSERVED)
    recorder = ScenarioRecorder("S16", mode=dr.RunMode.EXECUTE, environ={}, clock=lambda: FAKE_NOW)
    s16_manual_close.record_actor_step(demo, recorder, "x", "closed the position")
    assert recorder.steps[-1]["label"] == DEMO_OBSERVED
    assert "test actor" in recorder.steps[-1]["detail"]
    s16_manual_close.record_leg_status_step(
        demo, recorder, {"STOP_LOSS": "EXPIRED", "TAKE_PROFIT_1": None, "TAKE_PROFIT_2": "CANCELED"}
    )
    step = recorder.steps[-1]
    assert step["name"] == s16_manual_close.STEP_LEGS_READ and step["label"] == DEMO_OBSERVED
    assert "STOP_LOSS=EXPIRED" in step["detail"]
    assert "TAKE_PROFIT_1=ABSENT" in step["detail"]
    assert "TAKE_PROFIT_2=CANCELED" in step["detail"]


async def test_a_demo_env_refuses_the_twin_only_leg_variant_before_anything_is_touched() -> None:
    env = SimpleNamespace(synthetic=False, label=DEMO_OBSERVED)
    with pytest.raises(ValueError, match="twin"):
        await s16_manual_close.run(env, _recorder(), legs=s16_manual_close.LEGS_STAY)


def test_the_twin_ends_only_close_position_legs_as_expired() -> None:
    fake = SimpleNamespace(
        now_utc=FAKE_NOW,
        open_algos={
            "a": SimpleNamespace(close_position=True, status="NEW", updated_at_utc=None),
            "b": SimpleNamespace(close_position=False, status="NEW", updated_at_utc=None),
        },
        algo_history={},
    )
    ended = s16_manual_close.end_close_position_legs(fake)
    assert ended == ["a"]
    assert list(fake.open_algos) == ["b"]
    assert fake.algo_history["a"].status == s16_manual_close.TWIN_LEG_STATUS == "EXPIRED"


# ---- the scenario on the twin ------------------------------------------------------------------ #


async def test_a_manual_close_leaves_a_flat_clean_orphan_free_account(tmp_path: Path) -> None:
    env, recorder, outcome = await _run(tmp_path)
    assert outcome == dr.OUTCOME_COMPLETE, recorder.steps
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}
    statuses = _status(recorder)
    for name in (
        "precondition_clean",
        "start",
        s16_manual_close.STEP_PROTECTED,
        s16_manual_close.STEP_ACTOR_CLOSED,
        s16_manual_close.STEP_TWIN_LEGS,
        s16_manual_close.STEP_FLAT_RECORDED,
        s16_manual_close.STEP_RECONCILE_FLAT,
        s16_manual_close.STEP_LEGS_READ,
        s16_manual_close.STEP_NO_ORPHAN,
        s16_manual_close.STEP_NEW_REQUEST,
        s16_manual_close.STEP_ENTRY_AFTER,
        "account_clean",
    ):
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)
    assert env.fake.positions.get("BTCUSDT", 0) == 0
    assert env.fake.open_algos == {}


async def test_the_twin_step_that_models_the_demo_leg_expiry_says_so(tmp_path: Path) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    step = next(s for s in recorder.steps if s["name"] == s16_manual_close.STEP_TWIN_LEGS)
    assert step["label"] == SYNTHETIC
    assert "A3" in step["detail"] and "EXPIRED" in step["detail"]


async def test_the_system_records_the_external_close_and_sends_no_close_of_its_own(
    tmp_path: Path,
) -> None:
    env, recorder, _outcome = await _run(tmp_path)
    flat = recorder.details["manual_close"]["flat"]
    assert flat["protection_state"] == "FLAT"
    assert flat["transition_reason"] == "POSITION_CLOSED"
    assert flat["system_close_orders"] == 0
    assert env.faults.calls_to("place_market_close") == [], "only the actor closed the position"
    actor = recorder.details["manual_close"]["actor"]
    assert not is_system_client_id(actor["client_id"])
    assert actor["quantity"] == recorder.details["manual_close"]["system_position"]
    for call in env.faults.calls_to("place_entry"):
        assert call["kwargs"]["new_client_order_id"] != actor["client_id"]


async def test_the_reconcile_reports_flat_without_any_divergence_or_safe_mode(
    tmp_path: Path,
) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    reconcile = recorder.details["manual_close"]["reconcile"]
    assert reconcile["ticks_after_close"] >= 1
    assert reconcile["divergent_ticks"] == 0 and reconcile["kinds"] == []
    assert reconcile["safe_mode_after"] is False


async def test_the_demo_recorded_leg_behaviour_is_modelled_and_no_orphan_remains(
    tmp_path: Path,
) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["manual_close"]
    assert facts["legs_model"] == s16_manual_close.LEGS_EXPIRE
    legs = facts["legs"]
    assert legs["STOP_LOSS"]["final_status"] == "EXPIRED"
    assert legs["TAKE_PROFIT_2"]["final_status"] == "EXPIRED"
    # TP1 carries an explicit quantity, so the A3 record does not cover it: the system ended it.
    assert legs["TAKE_PROFIT_1"]["final_status"] == "CANCELED"
    assert legs["TAKE_PROFIT_1"]["system_cancel_calls"] >= 1
    assert facts["open_algo_orders_after"] == 0


async def test_when_no_leg_expires_the_system_removes_every_leg_itself(tmp_path: Path) -> None:
    """The orphan branch of G4-035: nothing auto-cancels, the system must leave no orphan."""
    env, recorder, outcome = await _run(tmp_path, legs=s16_manual_close.LEGS_STAY)
    assert outcome == dr.OUTCOME_COMPLETE, recorder.steps
    facts = recorder.details["manual_close"]
    assert facts["legs_model"] == s16_manual_close.LEGS_STAY
    for role in ("STOP_LOSS", "TAKE_PROFIT_1", "TAKE_PROFIT_2"):
        assert facts["legs"][role]["final_status"] == "CANCELED", role
        assert facts["legs"][role]["system_cancel_calls"] == 1, role
    assert facts["open_algo_orders_after"] == 0
    assert env.fake.open_algos == {}
    assert s16_manual_close.STEP_TWIN_LEGS not in _status(recorder)


async def test_a_new_request_waits_for_the_first_plan_to_expire_then_places(
    tmp_path: Path,
) -> None:
    """Whatever the code defines is recorded: the closed plan's approval holds the symbol."""
    env, recorder, _outcome = await _run(tmp_path)
    request = recorder.details["manual_close"]["new_request"]
    assert request["refused"] is True
    assert request["sources"] == ["PENDING_OR_APPROVED_APPROVAL"]
    after = recorder.details["manual_close"]["entry_after"]
    assert after["placed"] is True and after["cancelled"] is True
    assert len(env.faults.calls_to("place_entry")) == 2, "the fill request and the later one"


# ---- negative controls and the held state ------------------------------------------------------ #


async def test_an_actor_that_closes_nothing_stops_the_run_at_the_close_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())

    async def nothing(self: Any, *args: Any, **kwargs: Any) -> str:
        return "t25a-nothing-0-0"

    monkeypatch.setattr(s16_manual_close._Actor, "close_position", nothing)
    recorder = _recorder()
    with pytest.raises(dr.SmokeHalt):
        await s16_manual_close.run(env, recorder)
    failed = [step for step in recorder.steps if step["status"] == dr.STEP_FAILED]
    assert failed and failed[0]["name"] == s16_manual_close.STEP_ACTOR_CLOSED
    assert "scripts/demo_clear.py" in failed[-1]["detail"]
    assert "scripts/demo_clear.py" in str(recorder.details["leaves_state"])


async def test_a_leg_that_is_still_open_is_an_orphan_and_fails_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())

    async def an_orphan(env: Any) -> list[str]:
        return ["xa-an-orphan-leg-the-system-never-cancelled"]

    monkeypatch.setattr(s16_manual_close, "_open_algo_ids", an_orphan)
    recorder = _recorder()
    with pytest.raises(dr.SmokeHalt):
        await s16_manual_close.run(env, recorder)
    failed = [step for step in recorder.steps if step["status"] == dr.STEP_FAILED]
    assert failed and failed[0]["name"] == s16_manual_close.STEP_NO_ORPHAN
    assert "scripts/demo_clear.py" in failed[0]["detail"]


def test_the_scenario_says_it_leaves_state_and_how_to_clear_it() -> None:
    doc = s16_manual_close.__doc__ or ""
    assert "leaves_state" in doc and "scripts/demo_clear.py" in doc
    demo = Path("tests/demo/test_demo_s16_manual_close.py").read_text(encoding="utf-8")
    assert "scripts/demo_clear.py" in demo and "test actor" in demo


async def test_the_evidence_file_has_the_scenario_schema_and_one_kind(tmp_path: Path) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    document: dict[str, Any] = json.loads(
        recorder.write(tmp_path / "evidence").read_text(encoding="utf-8")
    )
    assert document["schema"] == "demo-scenario-evidence/schema-1"
    assert document["scenario_id"] == "S16"
    assert document["evidence_kinds"] == ["SYNTHETIC"]
    assert document["details"]["manual_close"]["flat"]["protection_state"] == "FLAT"


def test_the_twin_names_the_existing_tests_it_reuses() -> None:
    assert len(REUSES) >= 1
    for reference in REUSES:
        path, _, name = reference.partition("::")
        assert name in Path(path).read_text(encoding="utf-8"), reference
