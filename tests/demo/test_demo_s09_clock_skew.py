"""S09 clock skew on Binance Demo (plan 25-13; OPS-01).

OWNER ONLY (`-m demo` with `TRADING_DEMO_RUN=1`); skipped in every agent and CI run. It builds the
real live process on Demo with `EnvOptions(clock_offset=...)` set to twice the larger ratified
drift limit and runs the SAME `s09_clock_skew.run(env, recorder)` the CI twin runs on the fake.

The skew is injected into the PROCESS clock only (DEMO_FAULT_INJECTED); the real drift guard
measures it against Binance's server time and must block new entries (`OUT_OF_LIMITS`), so a
request that is approved and confirmed places nothing. Research assumption A3: the SDK stamps its
requests from the system clock, not the injected process clock, so the signed calls themselves are
expected to succeed. If Binance answers -1021 instead, the scenario records that outcome and still
asserts that nothing was placed. The exchange-side -1021 stays with the owner opt-in probe case
`timestamp_outside_recv_window`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s09_clock_skew
from tests.support.demo_scenarios.harness import EnvOptions, ScenarioRecorder

pytestmark = pytest.mark.demo


async def test_s09_a_skewed_process_clock_blocks_entries_and_nothing_is_sent_on_demo(
    scenario_recorder: Callable[[str], ScenarioRecorder],
    make_demo_env: Callable[..., Awaitable[Any]],
) -> None:
    recorder = scenario_recorder("S09")
    skew = s09_clock_skew.skew_for(s09_clock_skew.loaded_drift_limits())
    env = await make_demo_env(recorder, EnvOptions(clock_offset=skew))
    try:
        outcome = await s09_clock_skew.run(env, recorder)
    finally:
        recorder.write()
    assert outcome in (dr.OUTCOME_COMPLETE, dr.OUTCOME_COMPLETE_WITH_GAPS), outcome
    assert recorder.default_label == dr.EVIDENCE_KIND_DEMO
