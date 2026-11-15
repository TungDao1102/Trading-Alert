"""S05 cancel racing a fill on Binance Demo (plan 25-10; EXEC-01).

OWNER ONLY (`-m demo` with `TRADING_DEMO_RUN=1`); skipped in every agent and CI run. It builds the
real live process on Demo (`make_demo_env`) and runs the SAME `s05_cancel_race.run(env, recorder)`
the CI twin runs on the fake. On Demo nothing is held: the "fill" request is marketable, and right
after the entry is acknowledged the scenario sends the entry cancel of the expiry path
(`expire_pending_entry`, the call the scheduled cancel makes) once. The race step is DEMO_OBSERVED
only if the entry rested (NEW) before the cancel and the exchange then showed it filled; otherwise
it is NOT_OBSERVED with the observed order of events. Whatever happened, the fill is protected or
the entry is cancelled, no second entry is placed and the account ends clean. The outcome is
COMPLETE_WITH_GAPS when the race was not observed; the twin is the deterministic proof.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s05_cancel_race
from tests.support.demo_scenarios.harness import EnvOptions, ScenarioRecorder

pytestmark = pytest.mark.demo


async def test_s05_a_cancel_racing_a_fill_ends_protected_or_cancelled_on_demo(
    scenario_recorder: Callable[[str], ScenarioRecorder],
    make_demo_env: Callable[..., Awaitable[Any]],
) -> None:
    recorder = scenario_recorder("S05")
    env = await make_demo_env(recorder, EnvOptions())
    try:
        outcome = await s05_cancel_race.run(env, recorder)
    finally:
        recorder.write()
    assert outcome in (dr.OUTCOME_COMPLETE, dr.OUTCOME_COMPLETE_WITH_GAPS), outcome
    assert recorder.default_label == dr.EVIDENCE_KIND_DEMO
