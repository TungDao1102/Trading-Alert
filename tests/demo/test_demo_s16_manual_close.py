"""S16 manual close outside the system on Binance Demo (plan 25-16; G2-016, G4-035, EXEC-02).

OWNER ONLY (`-m demo` with `TRADING_DEMO_RUN=1`); skipped in every agent and CI run. It builds the
real live process on Demo (`make_demo_env`) and runs the SAME `s16_manual_close.run(env, recorder)`
the CI twin runs on the fake.

A system plan is filled and protected on Demo; then a test actor closes the whole position with a
REAL reduce-only MARKET order made outside the system (client id `t25a-close-...`, never a system
id), exactly what an owner closing the position in the Binance UI does. The scenario reads the
final status of the stop and both take-profit legs from the exchange and records each one verbatim
by status code (the 2026-10-22 Demo record says the closePosition legs ended EXPIRED with none
orphaned; this run proves it for the live process). It asserts the plan ends FLAT without any close
of the system's own, the reconcile reports no divergence, no leg stays open, and that a new request
is placed once the first plan has expired. Nothing is injected and nothing is modelled on Demo, so
the steps carry DEMO_OBSERVED.

The scenario `leaves_state`. If the run stops early, close any open BTCUSDT position and algo order
in the Binance Demo UI, then run `scripts/demo_clear.py` (it expires the plans behind open
approvals).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s16_manual_close
from tests.support.demo_scenarios.harness import EnvOptions, ScenarioRecorder

pytestmark = pytest.mark.demo


async def test_s16_a_manual_close_leaves_a_flat_orphan_free_account_on_demo(
    scenario_recorder: Callable[[str], ScenarioRecorder],
    make_demo_env: Callable[..., Awaitable[Any]],
) -> None:
    recorder = scenario_recorder("S16")
    env = await make_demo_env(recorder, EnvOptions())
    try:
        outcome = await s16_manual_close.run(env, recorder)
    finally:
        recorder.write()
    assert outcome in (dr.OUTCOME_COMPLETE, dr.OUTCOME_COMPLETE_WITH_GAPS), outcome
    assert recorder.default_label == dr.EVIDENCE_KIND_DEMO
