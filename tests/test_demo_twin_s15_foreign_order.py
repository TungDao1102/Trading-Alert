"""S15 (foreign order and doubled position) on the CI twin: the fake composed process (25-16).

TEST_ONLY, EXEC-02. A test actor (client ids that cannot match a system id, sizes taken from the
loaded exchange filters) places a resting order and, in a second flow, adds a position on top of a
protected system position. The real reconcile loop must report FOREIGN_ORDER and DOUBLED_POSITION,
enter SAFE_MODE and alert; the system never cancels or closes what it did not make; the operator
exit is refused while the divergence stands and accepted after the actor cleaned up. The same
`s15_foreign_order.run(env, recorder)` is what the owner's Demo test calls.

The actor calls go straight to the adapter the edge wraps (`env.faults.inner`), so they never
appear in the edge ledger: the ledger keeps counting only what the system process sends. On the
twin the actor's marketable order is filled by `fake.fill` (the exchange fills it by itself on
Demo); the user-data stream is not told, the reconcile reads the position over REST.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import demo_rehearsal as dr
from src.execution.order_ids import is_system_client_id

from tests.support.demo_scenarios import s15_foreign_order
from tests.support.demo_scenarios.catalog import by_id
from tests.support.demo_scenarios.harness import (
    DEMO_OBSERVED,
    SYNTHETIC,
    EnvOptions,
    ScenarioRecorder,
    build_fake_scenario_env,
)
from tests.support.live_composed_rig import btc_filters
from tests.support.live_rig import forbid_real_sleep

FAKE_NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
_BINANCE_ID = re.compile(r"^[\.A-Z\:/a-z0-9_-]{1,36}$")

# The existing tests this twin builds on (the coverage inventory of plan 25-17 reads this tuple).
REUSES = (
    "tests/test_live_reconcile_divergences.py::test_a_duplicate_exchange_client_id_is_journaled_enters_safe_mode_and_alerts",
    "tests/test_reconcile_compare_v2.py::test_a_foreign_normal_order_is_a_foreign_order_divergence_and_never_sweepable",
    "tests/test_reconcile_compare_v2.py::test_a_foreign_order_next_to_an_orphan_protective_keeps_only_the_orphan_sweepable",
    "tests/test_reconcile_classify.py::test_each_kind_has_the_planned_action_alert_and_safe_mode_reason",
    "tests/test_reconcile_tp1_fill.py::test_a_position_larger_than_the_plan_is_not_an_explanation",
    "tests/test_demo_twin_s14_safe_mode.py::test_the_catalog_pins_s14_to_this_plan",
)


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def _recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S15", mode=dr.RunMode.DRY_RUN, environ={}, clock=lambda: FAKE_NOW)


def _status(recorder: ScenarioRecorder) -> dict[str, str]:
    return {step["name"]: step["status"] for step in recorder.steps}


async def _run(tmp_path: Path) -> tuple[Any, ScenarioRecorder, str]:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    recorder = _recorder()
    outcome = await s15_foreign_order.run(env, recorder)
    return env, recorder, outcome


def test_the_catalog_pins_s15_to_this_plan_and_flags_the_held_state() -> None:
    s = by_id("S15")
    assert (s.plan, s.module) == ("25-16", "tests/support/demo_scenarios/s15_foreign_order.py")
    assert s.twin_test == "tests/test_demo_twin_s15_foreign_order.py"
    assert s.demo_test == "tests/demo/test_demo_s15_foreign_order.py"
    assert s.requirements == ("EXEC-02", "OPS-01")
    assert s.leaves_state is True


# ---- the actor --------------------------------------------------------------------------------- #


def test_an_actor_client_id_can_never_be_taken_for_a_system_id() -> None:
    for role in ("rest", "add", "reduce"):
        client_id = s15_foreign_order.actor_client_id(role, 1_762_603_200, 7)
        assert not is_system_client_id(client_id)
        assert _BINANCE_ID.match(client_id), client_id
        assert client_id.startswith(s15_foreign_order.ACTOR_ID_PREFIX)


def test_the_actor_prefix_is_refused_if_it_would_look_like_a_system_family() -> None:
    assert not is_system_client_id(s15_foreign_order.ACTOR_ID_PREFIX + "rest-1-1")
    for bad in ("x-", "xa-", "xc-"):
        assert is_system_client_id(bad + "a" * 33), "the control: a system id is recognised"


def test_the_actor_is_sized_from_the_loaded_filters_not_from_a_literal() -> None:
    mark = Decimal("50000")
    default = s15_foreign_order.actor_sizing(btc_filters(), mark)
    assert default.quantity * default.price_below >= btc_filters().min_notional
    assert default.price_below < mark < default.price_above
    other = btc_filters(
        min_notional=Decimal("250"),
        quantity_step_size=Decimal("0.01"),
        min_quantity=Decimal("0.01"),
        price_tick_size=Decimal("0.5"),
    )
    sized = s15_foreign_order.actor_sizing(other, mark)
    assert sized.quantity != default.quantity
    assert sized.quantity % Decimal("0.01") == 0
    assert sized.quantity * sized.price_below >= Decimal("250")
    assert sized.price_below % Decimal("0.5") == 0 and sized.price_above % Decimal("0.5") == 0


def test_the_actor_refuses_filters_without_the_percent_price_band() -> None:
    with pytest.raises(ValueError, match="PERCENT_PRICE"):
        s15_foreign_order.actor_sizing(
            btc_filters(percent_price_multiplier_up=None), Decimal("50000")
        )


def test_actor_steps_are_labelled_as_test_actor_actions() -> None:
    demo = SimpleNamespace(synthetic=False, label=DEMO_OBSERVED)
    recorder = ScenarioRecorder("S15", mode=dr.RunMode.EXECUTE, environ={}, clock=lambda: FAKE_NOW)
    s15_foreign_order.record_actor_step(demo, recorder, "x", "placed an order")
    step = recorder.steps[-1]
    assert step["label"] == DEMO_OBSERVED and "test actor" in step["detail"]
    twin = SimpleNamespace(synthetic=True, label=SYNTHETIC)
    s15_foreign_order.record_actor_step(twin, _recorder(), "x", "placed an order")


# ---- the scenario on the twin ------------------------------------------------------------------ #


async def test_both_flows_complete_and_every_step_is_synthetic(tmp_path: Path) -> None:
    _env, recorder, outcome = await _run(tmp_path)
    assert outcome == dr.OUTCOME_COMPLETE, recorder.steps
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}
    statuses = _status(recorder)
    for name in (
        "precondition_clean",
        "start",
        s15_foreign_order.STEP_FOREIGN_PLACED,
        s15_foreign_order.STEP_FOREIGN_DETECTED,
        s15_foreign_order.STEP_FOREIGN_UNTOUCHED,
        s15_foreign_order.STEP_FOREIGN_NO_CARD,
        s15_foreign_order.STEP_FOREIGN_EXIT_REFUSED,
        s15_foreign_order.STEP_FOREIGN_REMOVED,
        s15_foreign_order.STEP_FOREIGN_CLEAN,
        s15_foreign_order.STEP_FOREIGN_EXIT,
        s15_foreign_order.STEP_FOREIGN_CARD_AGAIN,
        s15_foreign_order.STEP_DOUBLED_BASELINE,
        s15_foreign_order.STEP_DOUBLED_PLACED,
        s15_foreign_order.STEP_DOUBLED_DETECTED,
        s15_foreign_order.STEP_DOUBLED_EXIT_REFUSED,
        s15_foreign_order.STEP_DOUBLED_REDUCED,
        s15_foreign_order.STEP_DOUBLED_CLEAN,
        s15_foreign_order.STEP_DOUBLED_EXIT,
        s15_foreign_order.STEP_ENTRY_RESTORED,
        "account_clean",
    ):
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)


async def test_a_foreign_resting_order_is_reported_enters_safe_mode_and_is_never_touched(
    tmp_path: Path,
) -> None:
    env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["foreign_order"]
    assert not is_system_client_id(facts["client_id"])
    detected = facts["detected"]
    assert detected["counts"].get("FOREIGN_ORDER", 0) >= 1
    assert "FOREIGN_ORDER" in detected["safe_mode_reasons"]
    assert "FOREIGN_ORDER" in detected["enter_reasons"]
    assert detected["alerts"] >= 1 and detected["alert_event"] == "FOREIGN_ORDER"
    # ALERT_ONLY for good (D-02): the system neither cancelled nor swept what it did not make.
    untouched = facts["left_untouched"]
    assert untouched["still_open_after_ticks"] is True
    assert untouched["system_cancel_calls_naming_it"] == 0
    assert env.faults.calls_to("cancel_normal_order") == [], "no system cancel at all"


async def test_a_new_request_gets_no_card_while_the_foreign_order_rests(tmp_path: Path) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    no_card = recorder.details["foreign_order"]["no_card"]
    assert no_card["refused"] is True
    assert "RESTING_ENTRY_ORDER" in no_card["sources"]
    assert no_card["place_entry_calls_before"] == no_card["place_entry_calls_after"] == 0


async def test_the_operator_exit_is_refused_while_the_divergence_stands(tmp_path: Path) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    for flow in ("foreign_order", "doubled_position"):
        refused = recorder.details[flow]["exit_refused"]
        assert refused["still_in_safe_mode"] is True
        assert "COMPARE_NOT_CLEAN" in refused["refusals"]
        assert refused["refused_rows_added"] == 1


async def test_safe_mode_stands_after_the_actor_cleaned_up_until_the_operator_exits(
    tmp_path: Path,
) -> None:
    """The reconcile loop never leaves SAFE_MODE by itself (D-15)."""
    _env, recorder, _outcome = await _run(tmp_path)
    for flow, key in (
        ("foreign_order", "after_actor_cancel"),
        ("doubled_position", "after_reduce"),
    ):
        clean = recorder.details[flow][key]
        assert clean["last_tick_divergences"] == 0
        assert clean["in_safe_mode"] is True
        exit_facts = recorder.details[flow]["exit"]
        assert exit_facts["in_safe_mode_after"] is False
        assert exit_facts["exit_rows"] == 1 and exit_facts["exit_operator_recorded"] is True


async def test_a_second_position_on_top_of_a_protected_one_is_a_doubled_position(
    tmp_path: Path,
) -> None:
    env, recorder, _outcome = await _run(tmp_path)
    facts = recorder.details["doubled_position"]
    assert facts["baseline"]["protection_state"] == "COMPLETE"
    assert facts["baseline"]["last_tick_divergences"] == 0
    assert Decimal(facts["total_position"]) == Decimal(facts["system_position"]) + Decimal(
        facts["actor_quantity"]
    )
    detected = facts["detected"]
    assert detected["counts"].get("DOUBLED_POSITION", 0) >= 1
    assert "DOUBLED_POSITION" in detected["safe_mode_reasons"]
    assert "DOUBLED_POSITION" in detected["enter_reasons"]
    assert detected["delegated"] >= 1, "the coordinator was told (D-07)"
    assert detected["alerts"] >= 1 and detected["alert_reason"] == "DOUBLED_POSITION"
    # What the system did about it: nothing risky. No close, no second entry, stop still resting.
    assert detected["system_close_orders"] == 0
    assert detected["place_entry_calls_unchanged"] is True
    assert detected["stop_still_open"] is True
    assert detected["protection_state_after"] == "COMPLETE"
    assert env.faults.calls_to("place_market_close") == []


async def test_after_the_exit_entries_are_allowed_again_and_the_account_ends_clean(
    tmp_path: Path,
) -> None:
    env, recorder, _outcome = await _run(tmp_path)
    assert recorder.details["foreign_order"]["card_after_exit"]["issued"] is True
    restored = recorder.details["doubled_position"]["entry_restored"]
    assert restored["placed"] is True and restored["cancelled"] is True
    # The edge ledger only holds the system's own sends: the fill request and the restored one.
    assert len(env.faults.calls_to("place_entry")) == 2
    actor = recorder.details["actor"]
    assert [a["role"] for a in actor["actions"]] == ["rest", "cancel", "add", "reduce"]
    assert all(not is_system_client_id(a["client_id"]) for a in actor["actions"])


async def test_the_actor_never_asks_the_system_to_place_or_cancel(tmp_path: Path) -> None:
    env, recorder, _outcome = await _run(tmp_path)
    actor_ids = {a["client_id"] for a in recorder.details["actor"]["actions"]}
    for method in ("place_entry", "place_market_close", "cancel_normal_order"):
        for call in env.faults.calls_to(method):
            kwargs = call.get("kwargs", {})
            assert kwargs.get("new_client_order_id") not in actor_ids
            assert kwargs.get("orig_client_order_id") not in actor_ids


# ---- negative controls and the held state ------------------------------------------------------ #


async def test_an_actor_that_places_nothing_stops_the_run_at_the_detection_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())

    async def nothing(self: Any) -> str:
        return "t25a-nothing-0-0"

    monkeypatch.setattr(s15_foreign_order._Actor, "rest", nothing)
    recorder = _recorder()
    with pytest.raises(dr.SmokeHalt):
        await s15_foreign_order.run(env, recorder)
    failed = [step for step in recorder.steps if step["status"] == dr.STEP_FAILED]
    assert failed and failed[0]["name"] == s15_foreign_order.STEP_FOREIGN_DETECTED


async def test_a_failed_run_names_the_cleanup_script_because_the_scenario_leaves_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())

    async def nothing(self: Any) -> str:
        return "t25a-nothing-0-0"

    monkeypatch.setattr(s15_foreign_order._Actor, "rest", nothing)
    recorder = _recorder()
    with pytest.raises(dr.SmokeHalt):
        await s15_foreign_order.run(env, recorder)
    failed = [step for step in recorder.steps if step["status"] == dr.STEP_FAILED]
    assert "scripts/demo_clear.py" in failed[-1]["detail"]
    assert "scripts/demo_clear.py" in str(recorder.details["leaves_state"])


async def test_the_actors_resting_order_is_removed_even_when_the_run_stops_early(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())

    async def never(*args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(dr, "_wait_until", never)
    recorder = _recorder()
    with pytest.raises(dr.SmokeHalt):
        await s15_foreign_order.run(env, recorder)
    assert env.fake.open_orders == {}, "the actor's own order was cancelled by its own id"


def test_the_scenario_says_it_leaves_state_and_how_to_clear_it() -> None:
    doc = s15_foreign_order.__doc__ or ""
    assert "leaves_state" in doc and "scripts/demo_clear.py" in doc
    demo = Path("tests/demo/test_demo_s15_foreign_order.py").read_text(encoding="utf-8")
    assert "scripts/demo_clear.py" in demo and "test actor" in demo


async def test_the_evidence_file_has_the_scenario_schema_and_one_kind(tmp_path: Path) -> None:
    _env, recorder, _outcome = await _run(tmp_path)
    document: dict[str, Any] = json.loads(
        recorder.write(tmp_path / "evidence").read_text(encoding="utf-8")
    )
    assert document["schema"] == "demo-scenario-evidence/schema-1"
    assert document["scenario_id"] == "S15"
    assert document["evidence_kinds"] == ["SYNTHETIC"]
    assert "FOREIGN_ORDER" in document["details"]["foreign_order"]["detected"]["counts"]


def test_the_twin_names_the_existing_tests_it_reuses() -> None:
    assert len(REUSES) >= 1
    for reference in REUSES:
        path, _, name = reference.partition("::")
        assert name in Path(path).read_text(encoding="utf-8"), reference
