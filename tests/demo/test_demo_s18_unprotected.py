"""S18 unprotected-position drill (G2-016) on Binance Demo (plan 25-11; OPS-01).

OWNER ONLY (`-m demo` with `TRADING_DEMO_RUN=1`); skipped in every agent and CI run. It builds the
real live process on Demo (`make_demo_env`) and runs the SAME `s18_unprotected.run(env, recorder)`
the CI twin runs on the fake. This scenario LEAVES STATE if it fails: a real Demo position without
a stop may stay open with SAFE_MODE on. Its recorded failure step names the recovery: close the
position and orders in the Binance Demo UI, then run `scripts/demo_clear.py`.

The stop rejection (-2021) and the rejection of every reduce-only close (-2022) are injected at the
adapter edge, nothing is sent for them (DEMO_FAULT_INJECTED). With the position open and unprotected
the real coordinator must hold CLOSE_FAILED, block entries, retry the close at every step and
journal the critical alerts. The operator `/close` and `/confirm` are sent through the real handler;
the code answers CLOSE_ALREADY_REQUIRED. Then the close fault is lifted and the coordinator's own
retry sends a real reduce-only MARKET close (DEMO_OBSERVED); the plan ends FLAT, SAFE_MODE is left
through `/safemode_exit` and the account ends clean.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s18_unprotected
from tests.support.demo_scenarios.harness import EnvOptions, ScenarioRecorder

pytestmark = pytest.mark.demo


async def test_s18_the_unprotected_position_drill_ends_flat_through_the_coordinator_on_demo(
    scenario_recorder: Callable[[str], ScenarioRecorder],
    make_demo_env: Callable[..., Awaitable[Any]],
) -> None:
    recorder = scenario_recorder("S18")
    env = await make_demo_env(recorder, EnvOptions())
    try:
        outcome = await s18_unprotected.run(env, recorder)
    finally:
        recorder.write()
    assert outcome in (dr.OUTCOME_COMPLETE, dr.OUTCOME_COMPLETE_WITH_GAPS), outcome
    assert recorder.default_label == dr.EVIDENCE_KIND_DEMO
