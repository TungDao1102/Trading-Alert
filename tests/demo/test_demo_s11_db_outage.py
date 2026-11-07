"""S11 DB outage during a risk-reducing close on Binance Demo (plan 25-14; OPS-01, R-24).

OWNER ONLY (`-m demo` with `TRADING_DEMO_RUN=1`); skipped in every agent and CI run. It builds the
real live process on Demo (`make_demo_env`) and runs the SAME `s11_db_outage.run(env, recorder)` the
CI twin runs on the fake.

The first stop placement after the fill is rejected at the adapter edge (DEMO_FAULT_INJECTED, with
code -2021) and, at the same instant, the journal store raises `StoreUnavailable` (a test-only proxy
over the real PostgreSQL store; the database itself stays up). The real process must still send ONE
reduce-only MARKET close (a real Demo order, DEMO_OBSERVED), end flat, write the audit rows the
journal refused to the local spill and enter SAFE_MODE DB_FAILURE. The fault is then cleared, the
operator leaves SAFE_MODE through `/safemode_exit`, entries work again, and the next start replays
the spill into the journal. SAFE_MODE is durable on Demo, so the exit is part of the run.

The real database outage (`docker compose stop postgres`) is an optional owner variant listed in the
runbook; it is not part of this test. If the run stops early, close any open BTCUSDT position in the
Binance Demo UI and run `scripts/demo_clear.py`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s11_db_outage
from tests.support.demo_scenarios.harness import EnvOptions, ScenarioRecorder

pytestmark = pytest.mark.demo


async def test_s11_a_db_outage_during_the_close_still_closes_spills_and_replays_on_demo(
    scenario_recorder: Callable[[str], ScenarioRecorder],
    make_demo_env: Callable[..., Awaitable[Any]],
) -> None:
    recorder = scenario_recorder("S11")
    env = await make_demo_env(recorder, EnvOptions())
    try:
        outcome = await s11_db_outage.run(env, recorder)
    finally:
        recorder.write()
    assert outcome in (dr.OUTCOME_COMPLETE, dr.OUTCOME_COMPLETE_WITH_GAPS), outcome
    assert recorder.default_label == dr.EVIDENCE_KIND_DEMO
