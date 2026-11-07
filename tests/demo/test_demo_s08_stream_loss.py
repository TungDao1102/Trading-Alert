"""S08 WS disconnect and listenKey expiry on Binance Demo (plan 25-13; EXEC-02, OPS-01, D-07).

OWNER ONLY (`-m demo` with `TRADING_DEMO_RUN=1`); skipped in every agent and CI run. It builds the
real live process on Demo (`make_demo_env`) and runs the SAME `s08_stream_loss.run(env, recorder,
trigger=...)` the CI twin runs on the fake.

The drop is injected: a "close" connection event of the current connection is posted into the
supervisor's own listener, so the supervisor runs its own rebuild (a real keepalive, a real new
websocket connection, a real REST snapshot): DEMO_FAULT_INJECTED trigger, real reconnection. The
states it passes through (UNKNOWN, SYNCING, LIVE) are recorded for the SAFE_MODE exit row 7 (D-07).
A real listenKey expiry needs the keepalive suppressed for more than the 60 minute key life; it
runs only when the owner sets `TRADING_DEMO_SLOW=1` (keepalive failures injected through
`SdkFaults`). Without it that step is NOT_OBSERVED with the reason, and the outcome is
COMPLETE_WITH_GAPS.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s08_stream_loss
from tests.support.demo_scenarios.harness import EnvOptions, ScenarioRecorder
from tests.support.fault_edge import SdkFaults

pytestmark = pytest.mark.demo


async def test_s08_a_dropped_stream_is_rebuilt_by_the_supervisor_and_reconciled_on_demo(
    scenario_recorder: Callable[[str], ScenarioRecorder],
    make_demo_env: Callable[..., Awaitable[Any]],
) -> None:
    recorder = scenario_recorder("S08")
    env = await make_demo_env(recorder, EnvOptions(sdk_faults=SdkFaults()))
    try:
        outcome = await s08_stream_loss.run(
            env, recorder, trigger=s08_stream_loss.DemoStreamTrigger()
        )
    finally:
        recorder.write()
    assert outcome in (dr.OUTCOME_COMPLETE, dr.OUTCOME_COMPLETE_WITH_GAPS), outcome
    assert recorder.default_label == dr.EVIDENCE_KIND_DEMO
