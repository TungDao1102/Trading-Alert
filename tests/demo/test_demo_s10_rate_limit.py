"""S10 rate limit (injected 429 only) on Binance Demo (plan 25-14; OPS-01, D-07).

OWNER ONLY (`-m demo` with `TRADING_DEMO_RUN=1`); skipped in every agent and CI run. It builds the
real live process on Demo (`make_demo_env`) and runs the SAME `s10_rate_limit.run(env, recorder)`
the CI twin runs on the fake (variant "429"; the 418 variant is twin only, and S19 runs the Demo
418 variant and clears it at once).

A real 429 or 418 is NEVER provoked (owner decision 2026-10-22, 25-RESEARCH Pitfall 7). The answer
is raised under the real adapter before the SDK sends anything (`SdkFaults`, DEMO_FAULT_INJECTED),
with a short Retry-After derived from the loaded limits. The real gate must record and persist the
pause, the CONFIRM must be refused with no order sent, and entries must work again after the pause.
The real 418 beyond 259200 s and the 429/418 queue order stay permanent NOT_OBSERVED rows of
DEMO_VS_MAINNET.md.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s10_rate_limit
from tests.support.demo_scenarios.harness import EnvOptions, ScenarioRecorder

pytestmark = pytest.mark.demo


async def test_s10_an_injected_429_pauses_the_gate_and_refuses_the_entry_on_demo(
    scenario_recorder: Callable[[str], ScenarioRecorder],
    make_demo_env: Callable[..., Awaitable[Any]],
) -> None:
    recorder = scenario_recorder("S10")
    env = await make_demo_env(recorder, EnvOptions())
    try:
        outcome = await s10_rate_limit.run(env, recorder, variant=s10_rate_limit.VARIANT_429)
    finally:
        recorder.write()
    assert outcome in (dr.OUTCOME_COMPLETE, dr.OUTCOME_COMPLETE_WITH_GAPS), outcome
    assert recorder.default_label == dr.EVIDENCE_KIND_DEMO
