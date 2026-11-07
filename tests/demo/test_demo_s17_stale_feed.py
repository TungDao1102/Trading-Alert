"""S17 stale feed drill (G2-016, D058) on Binance Demo (plan 25-13; OPS-01, D-06).

OWNER ONLY (`-m demo` with `TRADING_DEMO_RUN=1`); skipped in every agent and CI run. It builds the
real live process on Demo (`make_demo_env`) and runs the SAME `s17_stale_feed.run(env, recorder)`
the CI twin runs on the fake.

A mark reading older than twice the configured mark-price age is injected at the public reader and
at the signed adapter's `get_mark_price` (DEMO_FAULT_INJECTED, nothing is sent to the exchange for
it). The real process must fail the market-feed health check, refuse the CONFIRM at the
pre-placement mark gate, and, with a resting entry, enter SAFE_MODE STALE_FEED with a STALE_DATA
alert. The fault is cleared, the operator leaves SAFE_MODE through `/safemode_exit` and the
account ends clean. SAFE_MODE is durable on Demo (PostgreSQL), so the exit is part of the run.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s17_stale_feed
from tests.support.demo_scenarios.harness import EnvOptions, ScenarioRecorder

pytestmark = pytest.mark.demo


async def test_s17_a_stale_mark_fails_closed_and_the_reaction_is_journaled_on_demo(
    scenario_recorder: Callable[[str], ScenarioRecorder],
    make_demo_env: Callable[..., Awaitable[Any]],
) -> None:
    recorder = scenario_recorder("S17")
    env = await make_demo_env(recorder, EnvOptions())
    try:
        outcome = await s17_stale_feed.run(env, recorder)
    finally:
        recorder.write()
    assert outcome in (dr.OUTCOME_COMPLETE, dr.OUTCOME_COMPLETE_WITH_GAPS), outcome
    assert recorder.default_label == dr.EVIDENCE_KIND_DEMO
