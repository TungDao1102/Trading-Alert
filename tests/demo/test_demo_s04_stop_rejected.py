"""S04 stop rejected after a fill on Binance Demo (plan 25-11; EXEC-01, OPS-01).

OWNER ONLY (`-m demo` with `TRADING_DEMO_RUN=1`); skipped in every agent and CI run. It builds the
real live process on Demo (`make_demo_env`) and runs the SAME `s04_stop_rejected.run(env, recorder)`
the CI twin runs on the fake. Demo cannot reject a stop on demand, so the rejection (code -2021) is
injected at the adapter edge before anything is sent: that step is DEMO_FAULT_INJECTED. The
coordinator's reaction is real: one reduce-only MARKET close under an `xc-` client id is a real Demo
order (DEMO_OBSERVED), the plan ends FLAT, the critical alerts are journaled and the account ends
clean. SAFE_MODE is left through `/safemode_exit` and `/confirm` at the end.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s04_stop_rejected
from tests.support.demo_scenarios.harness import EnvOptions, ScenarioRecorder

pytestmark = pytest.mark.demo


async def test_s04_a_rejected_stop_ends_in_one_reduce_only_close_on_demo(
    scenario_recorder: Callable[[str], ScenarioRecorder],
    make_demo_env: Callable[..., Awaitable[Any]],
) -> None:
    recorder = scenario_recorder("S04")
    env = await make_demo_env(recorder, EnvOptions())
    try:
        outcome = await s04_stop_rejected.run(env, recorder)
    finally:
        recorder.write()
    assert outcome in (dr.OUTCOME_COMPLETE, dr.OUTCOME_COMPLETE_WITH_GAPS), outcome
    assert recorder.default_label == dr.EVIDENCE_KIND_DEMO
