"""S14 SAFE_MODE entry and operator exit on Binance Demo (plan 25-15; OPS-01).

OWNER ONLY (`-m demo` with `TRADING_DEMO_RUN=1`); skipped in every agent and CI run. It builds the
real live process on Demo (`make_demo_env`) and runs the SAME `s14_safe_mode.run(env, recorder)` the
CI twin runs on the fake.

The answer of the entry POST is dropped after it was sent (the order is really on Demo, a GTD LIMIT
far from the market) and the probe by client id fails; both are DEMO_FAULT_INJECTED. The real
process must leave the entry UNKNOWN, enter SAFE_MODE ENTRY_STATE_UNKNOWN, keep its reconcile and
health ticks running, refuse the operator exit, resolve the entry through its own reconcile probe
once the fault is cleared, refuse a CONFIRM while SAFE_MODE stands and accept `/safemode_exit` plus
`/confirm <token>`. SAFE_MODE is durable on Demo, so the exit is part of the run. If the run stops
early, leave SAFE_MODE by hand (RUNBOOK 21.1a), cancel any open BTCUSDT order in the Binance Demo UI
and run `scripts/demo_clear.py`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s14_safe_mode
from tests.support.demo_scenarios.harness import EnvOptions, ScenarioRecorder

pytestmark = pytest.mark.demo


async def test_s14_an_unresolved_entry_enters_safe_mode_and_the_operator_exit_works_on_demo(
    scenario_recorder: Callable[[str], ScenarioRecorder],
    make_demo_env: Callable[..., Awaitable[Any]],
) -> None:
    recorder = scenario_recorder("S14")
    env = await make_demo_env(recorder, EnvOptions())
    try:
        outcome = await s14_safe_mode.run(env, recorder)
    finally:
        recorder.write()
    assert outcome in (dr.OUTCOME_COMPLETE, dr.OUTCOME_COMPLETE_WITH_GAPS), outcome
    assert recorder.default_label == dr.EVIDENCE_KIND_DEMO
