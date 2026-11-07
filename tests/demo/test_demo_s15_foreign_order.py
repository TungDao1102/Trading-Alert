"""S15 foreign order and doubled position on Binance Demo (plan 25-16; EXEC-02, D-02, D-07).

OWNER ONLY (`-m demo` with `TRADING_DEMO_RUN=1`); skipped in every agent and CI run. It builds the
real live process on Demo (`make_demo_env`) and runs the SAME `s15_foreign_order.run(env, recorder)`
the CI twin runs on the fake.

A test actor makes REAL Demo orders on BTCUSDT through the adapter, outside the system: one far
resting BUY LIMIT, then (in the second flow, on top of a protected system position) one marketable
BUY LIMIT of the smallest valid size and a reduce-only MARKET close of that same quantity. The
actor's client ids start with `t25a-`, which no system id can; its sizes come from the loaded
exchange filters. The actor steps carry the label DEMO_OBSERVED and the detail "test actor".

The scenario `leaves_state`: SAFE_MODE is durable on Demo, so the run leaves it through the operator
exit itself. If the run stops early, the actor's resting order is cancelled by its own id; an actor
position is NOT closed automatically. Close any open BTCUSDT order and position in the Binance Demo
UI, leave SAFE_MODE with `/safemode_exit` and `/confirm`, then run `scripts/demo_clear.py`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s15_foreign_order
from tests.support.demo_scenarios.harness import EnvOptions, ScenarioRecorder

pytestmark = pytest.mark.demo


async def test_s15_reconcile_reports_a_foreign_order_and_a_doubled_position_on_demo(
    scenario_recorder: Callable[[str], ScenarioRecorder],
    make_demo_env: Callable[..., Awaitable[Any]],
) -> None:
    recorder = scenario_recorder("S15")
    env = await make_demo_env(recorder, EnvOptions())
    try:
        outcome = await s15_foreign_order.run(env, recorder)
    finally:
        recorder.write()
    assert outcome in (dr.OUTCOME_COMPLETE, dr.OUTCOME_COMPLETE_WITH_GAPS), outcome
    assert recorder.default_label == dr.EVIDENCE_KIND_DEMO
