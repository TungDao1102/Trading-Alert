"""S03 (price crossed the stop) on the CI twin: the fake composed process (plan 25-11).

TEST_ONLY, EXEC-01, D-05. Two variants of one scenario:

(i) the mark the pre-placement check reads (`adapter.get_mark_price`, answered through
    `FaultEdge.override`) sits past the stop at CONFIRM: the check refuses with
    MARK_PRICE_CROSSED_STOP, nothing is sent, the refusal is journaled;
(ii) after a fill the stop request is answered with -2021 (the fake does not model the trigger
    rule, so the answer is injected; on Demo the stop payload is mutated to the wrong side and the
    exchange's real answer is recorded): the outcome equals S04.

On the twin every step is SYNTHETIC; the Demo label rule is pinned on a non-synthetic stub env.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import demo_rehearsal as dr
from src.domain.enums import OrderRole
from src.execution.order_ids import derive_algo_client_id

from tests.support.demo_scenarios import s03_crossed_stop, s04_stop_rejected
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

D = Decimal
FAKE_NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)

# The existing tests this twin builds on (the coverage inventory of plan 25-17 reads this tuple).
REUSES = (
    "tests/test_pre_placement.py::test_evaluate_refuses_a_crossed_mark_price",
    "tests/test_pre_placement.py::test_check_mark_price_position",
    "tests/test_protection_branches.py::test_branch_b5_definitive_stop_rejection_after_a_fill_closes_and_ends_flat",
    "tests/test_exchange_errors.py::test_demo_observed_codes_are_exactly_the_probe_observed_codes_in_the_table",
)


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def _recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S03", mode=dr.RunMode.DRY_RUN, environ={}, clock=lambda: FAKE_NOW)


def _status(recorder: ScenarioRecorder) -> dict[str, str]:
    return {step["name"]: step["status"] for step in recorder.steps}


def test_the_catalog_pins_s03_to_this_plan() -> None:
    s03 = by_id("S03")
    assert (s03.plan, s03.module) == ("25-11", "tests/support/demo_scenarios/s03_crossed_stop.py")
    assert s03.twin_test == "tests/test_demo_twin_s03_crossed_stop.py"
    assert s03.demo_test == "tests/demo/test_demo_s03_crossed_stop.py"
    assert s03.requirements == ("EXEC-01",)


async def test_both_variants_end_refused_or_closed_and_the_account_is_clean(
    tmp_path: Path,
) -> None:
    recorder = _recorder()
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    outcome = await s03_crossed_stop.run(env, recorder)
    assert outcome == dr.OUTCOME_COMPLETE, recorder.steps
    assert {step["label"] for step in recorder.steps} == {SYNTHETIC}
    statuses = _status(recorder)
    for name in (
        "precondition_clean",
        s03_crossed_stop.STEP_MARK_INJECT,
        s03_crossed_stop.STEP_REFUSED,
        s03_crossed_stop.STEP_NOTHING_SENT,
        s03_crossed_stop.STEP_PLAN_RELEASED,
        s03_crossed_stop.STEP_WRONG_SIDE_INJECT,
        s03_crossed_stop.STEP_ANSWER,
        s04_stop_rejected.STEP_STOP_NOT_RESENT,
        s04_stop_rejected.STEP_CLOSE_REQUIRED,
        s04_stop_rejected.STEP_BLOCKED,
        s04_stop_rejected.STEP_CLOSE,
        s04_stop_rejected.STEP_ALERTS,
        s04_stop_rejected.STEP_SAFE_MODE_LEFT,
        "account_clean",
    ):
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)


async def test_variant_one_refuses_at_confirm_with_the_price_check_reason_and_sends_nothing(
    tmp_path: Path,
) -> None:
    recorder = _recorder()
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await s03_crossed_stop.run(env, recorder)
    crossed = recorder.details["crossed_mark"]
    assert crossed["reason_code"] == "MARK_PRICE_CROSSED_STOP"
    assert crossed["place_entry_calls_after_confirm"] == 0
    assert crossed["event_type"] in (
        "DEMO_CONFIRM_EXPIRED",
        "LIVE_PLACEMENT_OUTCOME",
        "LIVE_PLACEMENT_REFUSED",
    )
    marks = [c for c in env.faults.calls_to("get_mark_price") if c["injected"]]
    assert marks and {c["mode"] for c in marks} == {"override"}
    assert len(env.fake.calls_to("place_entry")) == 1, "only variant (ii) placed an entry"


async def test_variant_two_equals_s04_one_stop_call_one_close_flat(tmp_path: Path) -> None:
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await s03_crossed_stop.run(env, _recorder())
    (protection,) = [p for p in env.wiring.coordinator.protections()]
    stop_id = derive_algo_client_id(plan_hash=protection.plan_hash, role=OrderRole.STOP_LOSS.value)
    stops = [c for c in env.faults.calls_to("place_algo_protective")]
    assert len(stops) == 1 and stops[0]["kwargs"]["client_algo_id"] == stop_id
    assert stops[0]["injected"] is True and stops[0]["mode"] == "override"
    assert len(env.fake.calls_to("place_market_close")) == 1
    assert not env.fake.positions.get("BTCUSDT")
    assert env.fake.open_orders == {} and env.fake.open_algos == {}


async def test_the_answer_is_recorded_as_code_and_class_never_as_message_text(
    tmp_path: Path,
) -> None:
    recorder = _recorder()
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    await s03_crossed_stop.run(env, recorder)
    answer = recorder.details["stop_answer"]
    assert answer == {
        "answer": "REJECTED",
        "code": -2021,
        "exception_class": "BadRequestError",
        "source": "injected",
    }
    assert "TEST_ONLY injected rejection" not in json.dumps(recorder.details, default=str)
    assert "TEST_ONLY injected rejection" not in json.dumps(recorder.steps, default=str)


async def test_an_exchange_that_accepts_the_wrong_side_stop_is_not_observed_and_ends_clean(
    tmp_path: Path,
) -> None:
    """Assumption A2: if the exchange answers something else, the scenario records it honestly."""

    async def accepting_sender(env: Any, kwargs: dict[str, Any]) -> Any:
        return await env.faults.inner.place_algo_protective(**kwargs)

    recorder = _recorder()
    env = build_fake_scenario_env(tmp_path, EnvOptions())
    outcome = await s03_crossed_stop.run(env, recorder, stop_sender=accepting_sender)
    assert outcome == dr.OUTCOME_COMPLETE_WITH_GAPS
    assert recorder.details["stop_answer"]["answer"] == "ACCEPTED"
    assert _status(recorder)[s03_crossed_stop.STEP_ANSWER] == dr.STEP_NOT_REHEARSED
    assert _status(recorder)["account_clean"] == dr.STEP_PASSED
    assert not env.fake.positions.get("BTCUSDT")


def _stub_env(*, synthetic: bool) -> Any:
    return SimpleNamespace(synthetic=synthetic, label=SYNTHETIC if synthetic else DEMO_OBSERVED)


def _demo_recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S03", mode=dr.RunMode.EXECUTE, environ={}, clock=lambda: FAKE_NOW)


def test_on_demo_the_injections_and_the_refusal_are_fault_injected_never_observed() -> None:
    recorder = _demo_recorder()
    env = _stub_env(synthetic=False)
    s03_crossed_stop.record_mark_injection(env, recorder, "mark past the stop")
    s03_crossed_stop.record_refusal(
        env, recorder, "MARK_PRICE_CROSSED_STOP", "LIVE_PLACEMENT_OUTCOME"
    )
    s04_stop_rejected.record_injection_step(
        env, recorder, "wrong side", name=s03_crossed_stop.STEP_WRONG_SIDE_INJECT
    )
    labels = {step["name"]: step["label"] for step in recorder.steps}
    assert labels[s03_crossed_stop.STEP_MARK_INJECT] == DEMO_FAULT_INJECTED
    assert labels[s03_crossed_stop.STEP_REFUSED] == DEMO_FAULT_INJECTED, (
        "driven by the injected mark"
    )
    assert labels[s03_crossed_stop.STEP_WRONG_SIDE_INJECT] == DEMO_FAULT_INJECTED


def test_on_demo_the_exchange_answer_is_observed_when_it_rejected_and_not_observed_otherwise() -> (
    None
):
    rejected, accepted = _demo_recorder(), _demo_recorder()
    env = _stub_env(synthetic=False)
    s03_crossed_stop.record_answer(
        env, rejected, {"answer": "REJECTED", "code": -2021, "source": "exchange"}
    )
    s03_crossed_stop.record_answer(env, accepted, {"answer": "ACCEPTED", "code": None})
    (seen,) = rejected.steps
    (missed,) = accepted.steps
    assert seen["label"] == DEMO_OBSERVED and seen["status"] == dr.STEP_PASSED
    assert missed["label"] == NOT_OBSERVED and missed["status"] == dr.STEP_NOT_REHEARSED


def test_on_demo_a_rejection_with_another_code_is_recorded_but_not_a_pass() -> None:
    recorder = _demo_recorder()
    s03_crossed_stop.record_answer(
        _stub_env(synthetic=False),
        recorder,
        {"answer": "REJECTED", "code": -4014, "source": "exchange"},
    )
    (step,) = recorder.steps
    assert step["status"] == dr.STEP_NOT_REHEARSED and "-4014" in step["detail"]


@pytest.mark.parametrize(
    ("side", "stop", "mark", "wrong_is_above_mark"),
    [("SELL", "98000.0", "100000.37", True), ("BUY", "102000.0", "100000.37", False)],
)
def test_the_wrong_side_trigger_mirrors_the_stop_around_the_mark_on_the_stop_precision(
    side: str, stop: str, mark: str, wrong_is_above_mark: bool
) -> None:
    wrong = s03_crossed_stop.wrong_side_trigger(side=side, stop=D(stop), mark=D(mark))
    assert (wrong > D(mark)) is wrong_is_above_mark
    assert wrong.as_tuple().exponent == D(stop).as_tuple().exponent
    assert wrong > 0


def test_a_mirror_that_would_not_be_positive_is_refused() -> None:
    with pytest.raises(ValueError):
        s03_crossed_stop.wrong_side_trigger(side="BUY", stop=D("300"), mark=D("100"))


def test_the_crossed_mark_is_beyond_the_stop_for_both_sides() -> None:
    assert s03_crossed_stop.crossed_mark(direction="LONG", stop=D("98000.0")) < D("98000.0")
    assert s03_crossed_stop.crossed_mark(direction="SHORT", stop=D("102000.0")) > D("102000.0")
    with pytest.raises(ValueError):
        s03_crossed_stop.crossed_mark(direction="FLAT", stop=D("1"))


async def test_the_evidence_file_has_the_scenario_schema_and_one_kind(tmp_path: Path) -> None:
    recorder = _recorder()
    await s03_crossed_stop.run(build_fake_scenario_env(tmp_path, EnvOptions()), recorder)
    document: dict[str, Any] = json.loads(
        recorder.write(tmp_path / "evidence").read_text(encoding="utf-8")
    )
    assert document["schema"] == "demo-scenario-evidence/schema-1"
    assert document["scenario_id"] == "S03"
    assert document["evidence_kinds"] == ["SYNTHETIC"]
    assert document["details"]["crossed_mark"]["reason_code"] == "MARK_PRICE_CROSSED_STOP"


def test_the_twin_names_the_existing_tests_it_reuses() -> None:
    assert len(REUSES) >= 1
    for reference in REUSES:
        path, _, name = reference.partition("::")
        assert name in Path(path).read_text(encoding="utf-8"), reference


class _InnerStub:
    """The real adapter's two calls `send_wrong_side` makes, recording what it was sent."""

    def __init__(self, mark: str) -> None:
        self._mark = D(mark)
        self.sent: list[dict[str, Any]] = []

    async def get_mark_price(self, *, symbol: str) -> Any:
        return SimpleNamespace(symbol=symbol, mark_price=self._mark)

    async def place_algo_protective(self, **kwargs: Any) -> str:
        self.sent.append(kwargs)
        return "placed"


def _stop_kwargs(side: str, trigger: str) -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT",
        "side": side,
        "trigger_price": D(trigger),
        "close_position": True,
        "client_algo_id": "a-x",
    }


async def test_send_wrong_side_mirrors_a_protective_stop_and_keeps_every_other_field() -> None:
    inner = _InnerStub("100000.37")
    env = SimpleNamespace(faults=SimpleNamespace(inner=inner))
    await s03_crossed_stop.send_wrong_side(env, _stop_kwargs("SELL", "98000.0"))
    (sent,) = inner.sent
    assert sent["trigger_price"] == D("102000.7") and sent["close_position"] is True
    assert sent["client_algo_id"] == "a-x" and sent["side"] == "SELL"


async def test_send_wrong_side_sends_an_already_crossed_stop_unchanged() -> None:
    inner = _InnerStub("97000.0")
    env = SimpleNamespace(faults=SimpleNamespace(inner=inner))
    await s03_crossed_stop.send_wrong_side(env, _stop_kwargs("SELL", "98000.0"))
    (sent,) = inner.sent
    assert sent["trigger_price"] == D("98000.0"), "the exchange answers for the crossed stop itself"
