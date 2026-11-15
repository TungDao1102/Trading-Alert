"""S02 partial fill on Binance Demo (plan 25-10; EXEC-01, D055/D079).

OWNER ONLY (`-m demo` with `TRADING_DEMO_RUN=1`); skipped in every agent and CI run. It builds the
real live process on Demo (`make_demo_env`) and runs the SAME `s02_partial_fill.run(env, recorder)`
the CI twin runs on the fake, with no scripted fill: the entry fills when Binance fills it. A
partial fill cannot be forced on Demo (`scripts/demo_probe.py`, `partial_fill_attempt`), so the
`partial_fill` step is recorded NOT_OBSERVED with its reason unless the entry really was partial;
the protection assertions (stop after the first fill, REST-confirmed, remainder cancelled, legs
sized from the position, flat at the end) are checked on the real fill either way. The outcome is
COMPLETE_WITH_GAPS when the partial fill was not observed; the twin is the proof of that branch.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s02_partial_fill
from tests.support.demo_scenarios.harness import EnvOptions, ScenarioRecorder

pytestmark = pytest.mark.demo


async def test_s02_a_partial_fill_is_protected_from_its_first_fill_on_demo(
    scenario_recorder: Callable[[str], ScenarioRecorder],
    make_demo_env: Callable[..., Awaitable[Any]],
) -> None:
    recorder = scenario_recorder("S02")
    env = await make_demo_env(recorder, EnvOptions())
    try:
        outcome = await s02_partial_fill.run(env, recorder)
    finally:
        recorder.write()
    assert outcome in (dr.OUTCOME_COMPLETE, dr.OUTCOME_COMPLETE_WITH_GAPS), outcome
    assert recorder.default_label == dr.EVIDENCE_KIND_DEMO
