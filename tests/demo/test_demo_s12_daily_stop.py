"""S12 DAILY_STOP on Binance Demo (plan 25-15; OPS-01, D033).

OWNER ONLY (`-m demo` with `TRADING_DEMO_RUN=1`); skipped in every agent and CI run. It builds the
real live process on Demo (`make_demo_env`) and runs the SAME `s12_daily_stop.run(env, recorder)`
the CI twin runs on the fake.

Run S12 LAST in an owner session: DAILY_STOP holds for the UTC day. The loss rows are injected at
the adapter edge (DEMO_FAULT_INJECTED, `user_trades_in_window`), sized from the loaded daily stop
rate and the day base the process persisted; no real loss is made. Once the day state is latched,
every later CONFIRM on this Demo account is refused `DAILY_STOP_BLOCK` until 00:00 UTC, so the
other scenarios cannot run again that day. The scenario refuses to start when the day is already
latched.

A resting entry placed before the stop is expected to be handled as D033 says (cancelled, stops
kept, alert); the code does not do that in a live process today (finding F1 of plan 25-15), and
the run records what it sees. If the run stops early, close any open BTCUSDT order in the Binance
Demo UI and run `scripts/demo_clear.py`; the day latch itself ends at 00:00 UTC.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s12_daily_stop
from tests.support.demo_scenarios.harness import EnvOptions, ScenarioRecorder

pytestmark = pytest.mark.demo


async def test_s12_injected_losses_reach_daily_stop_and_refuse_new_entries_on_demo(
    scenario_recorder: Callable[[str], ScenarioRecorder],
    make_demo_env: Callable[..., Awaitable[Any]],
) -> None:
    recorder = scenario_recorder("S12")
    env = await make_demo_env(recorder, EnvOptions())
    try:
        outcome = await s12_daily_stop.run(env, recorder)
    finally:
        recorder.write()
    assert outcome in (dr.OUTCOME_COMPLETE, dr.OUTCOME_COMPLETE_WITH_GAPS), outcome
    assert recorder.default_label == dr.EVIDENCE_KIND_DEMO
