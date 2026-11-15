"""S01 happy path on Binance Demo: the first step of the owner's campaign (plan 25-09).

OWNER ONLY (`-m demo` with `TRADING_DEMO_RUN=1`); skipped in every agent and CI run. It builds the
real live process on Demo through the production assembly (`make_demo_env`), runs the SAME
`s01_happy.run(env, recorder)` the CI twin runs on the fake, and writes the evidence. It proves the
pytest harness itself on Demo: the programmatic owner presses through the runner's handler, the
labels are DEMO_OBSERVED, and the session ends with one evidence index. The 2026-11-06
`demo_rehearsal --execute` smoke (21 of 21 steps, real Telegram taps) stays the proof of the
Telegram transport; set `TRADING_DEMO_OWNER=console` to tap on the real bot here too.

The account must be clean (no open order, algo order, position or approval): a dirty start stops
with the `scripts/demo_clear.py` instruction before anything is placed. The first start of a fresh
install needs `TRADING_DEMO_INITIALIZE_GATE_STATE=1`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s01_happy
from tests.support.demo_scenarios.harness import EnvOptions, ScenarioRecorder

pytestmark = pytest.mark.demo


async def test_s01_the_happy_path_runs_on_demo_through_the_production_assembly(
    scenario_recorder: Callable[[str], ScenarioRecorder],
    make_demo_env: Callable[..., Awaitable[Any]],
) -> None:
    recorder = scenario_recorder("S01")
    env = await make_demo_env(recorder, EnvOptions())
    try:
        outcome = await s01_happy.run(env, recorder)
    finally:
        # `run_composed_smoke` stops the running process in order whatever happens, so there is
        # nothing to abandon; the evidence is kept even when the run failed.
        recorder.write()
    assert outcome in (dr.OUTCOME_COMPLETE, dr.OUTCOME_COMPLETE_WITH_GAPS), outcome
    assert recorder.default_label == dr.EVIDENCE_KIND_DEMO
