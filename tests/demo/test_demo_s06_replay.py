"""S06 replayed and concurrent presses on Binance Demo (plan 25-10; EXEC-03, APRV-02).

OWNER ONLY (`-m demo` with `TRADING_DEMO_RUN=1`); skipped in every agent and CI run. It builds the
real live process on Demo through the production assembly (`make_demo_env`) and runs the SAME
`s06_replay.run(env, recorder)` the CI twin runs on the fake: one approved "far" request, two
concurrent CONFIRM presses through the runner's handler, then a replayed APPROVE and CONFIRM. On
Demo exactly one `place_entry` POST must leave the process (counted at the fault edge) and the
journal must hold one non-refused placement outcome. No trigger is injected, so the steps are
DEMO_OBSERVED. The resting entry is cancelled by its client id at the end; the account must be
clean at the start (`scripts/demo_clear.py` otherwise).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s06_replay
from tests.support.demo_scenarios.harness import EnvOptions, ScenarioRecorder

pytestmark = pytest.mark.demo


async def test_s06_replayed_and_concurrent_presses_place_exactly_one_entry_on_demo(
    scenario_recorder: Callable[[str], ScenarioRecorder],
    make_demo_env: Callable[..., Awaitable[Any]],
) -> None:
    recorder = scenario_recorder("S06")
    env = await make_demo_env(recorder, EnvOptions())
    try:
        outcome = await s06_replay.run(env, recorder)
    finally:
        # `run` stops the process in order whatever happens; the evidence is kept on failure too.
        recorder.write()
    assert outcome == dr.OUTCOME_COMPLETE
    assert recorder.default_label == dr.EVIDENCE_KIND_DEMO
