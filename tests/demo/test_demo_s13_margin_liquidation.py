"""S13 margin and liquidation guards on Binance Demo (plan 25-15; OPS-01, EXEC-01).

OWNER ONLY (`-m demo` with `TRADING_DEMO_RUN=1`); skipped in every agent and CI run. It builds the
real live process on Demo (`make_demo_env`) and runs the SAME `s13_margin_liquidation.run(env,
recorder)` the CI twin runs on the fake.

Two readings are injected at the adapter edge (DEMO_FAULT_INJECTED): an available balance below the
margin the plan needs, and a leverage-bracket table whose maintenance ratio is derived so that the
computed liquidation price lies between the entry and the stop. Both values are computed from the
plan the process built, the target leverage and the account's real bracket table. The real guards
must refuse the CONFIRM before any entry or symbol-configuration POST. A normal request (no
override) is then placed and cancelled, and the account must end clean.

The bad-bracket case runs last: the process keeps a bracket reading for the owner's bound
(`margin.max_bracket_age_ms`), so the run waits that long once, in real time, before it. The
exchange-side -2019 is not part of this test: it is the owner probe case `insufficient_margin_order`
(Demo-observed 2026-10-24). If the run stops early, close any open BTCUSDT order in the Binance Demo
UI and run `scripts/demo_clear.py`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s13_margin_liquidation
from tests.support.demo_scenarios.harness import EnvOptions, ScenarioRecorder

pytestmark = pytest.mark.demo


async def test_s13_margin_and_liquidation_guards_refuse_before_anything_is_sent_on_demo(
    scenario_recorder: Callable[[str], ScenarioRecorder],
    make_demo_env: Callable[..., Awaitable[Any]],
) -> None:
    recorder = scenario_recorder("S13")
    env = await make_demo_env(recorder, EnvOptions())
    try:
        outcome = await s13_margin_liquidation.run(env, recorder)
    finally:
        recorder.write()
    assert outcome in (dr.OUTCOME_COMPLETE, dr.OUTCOME_COMPLETE_WITH_GAPS), outcome
    assert recorder.default_label == dr.EVIDENCE_KIND_DEMO
