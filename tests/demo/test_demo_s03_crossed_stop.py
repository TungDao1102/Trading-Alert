"""S03 price crossed the stop on Binance Demo (plan 25-11; EXEC-01).

OWNER ONLY (`-m demo` with `TRADING_DEMO_RUN=1`); skipped in every agent and CI run. It builds the
real live process on Demo (`make_demo_env`) and runs the SAME `s03_crossed_stop.run(env, recorder)`
the CI twin runs on the fake.

Variant (i): the mark the pre-placement check reads is moved past the stop at CONFIRM (a test seam
at the adapter edge, DEMO_FAULT_INJECTED); the real check refuses and nothing is sent. Variant (ii):
after a fill the stop payload is mutated to the wrong side of the mark and sent to Demo; the
exchange's own answer (research assumption A2: -2021) is recorded by code and class name only and
labelled DEMO_OBSERVED only if it really rejected with -2021; any other answer is NOT_OBSERVED with
the code recorded. The coordinator then reacts as in S04 (one reduce-only close, a real Demo order).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s03_crossed_stop
from tests.support.demo_scenarios.harness import EnvOptions, ScenarioRecorder

pytestmark = pytest.mark.demo


async def test_s03_a_crossed_stop_is_refused_or_closed_and_never_left_unprotected_on_demo(
    scenario_recorder: Callable[[str], ScenarioRecorder],
    make_demo_env: Callable[..., Awaitable[Any]],
) -> None:
    recorder = scenario_recorder("S03")
    env = await make_demo_env(recorder, EnvOptions())
    try:
        outcome = await s03_crossed_stop.run(env, recorder)
    finally:
        recorder.write()
    assert outcome in (dr.OUTCOME_COMPLETE, dr.OUTCOME_COMPLETE_WITH_GAPS), outcome
    assert recorder.default_label == dr.EVIDENCE_KIND_DEMO
