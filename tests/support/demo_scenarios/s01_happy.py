"""S01 happy path: signal, card, APPROVE, CONFIRM, fill, stop, take profits, restart, close (25-08).

TEST_ONLY. The scenario is the Phase 24 composed smoke (`run_composed_smoke`) run through the
scenario harness, so the CI twin (fake, every step SYNTHETIC) and the owner's Demo test assert the
same sequence (D-04, D-05). Labels: SYNTHETIC on the fake, DEMO_OBSERVED on Demo; no step of S01
is an injected trigger.

Clean start: the smoke itself records no precondition, so `ensure_clean_start` runs first
(Pitfall 8). The smoke's own `account_clean` step (orders, algo orders and positions after the
close) is the end check, so the harness `account_clean` is not called a second time.
"""

from __future__ import annotations

from typing import Any

from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios.harness import ScenarioRecorder, ensure_clean_start


async def run(env: Any, recorder: ScenarioRecorder) -> str:
    """Run the happy path on `env`; returns the smoke outcome (an `OUTCOME_*` constant)."""
    recorder.default_label = env.label
    await ensure_clean_start(env, recorder)
    outcome = await dr.run_composed_smoke(env, recorder)
    recorder.record_health(_latest_health(env))
    recorder.attestation_map = dr.build_smoke_attestation(recorder)
    recorder.outcome = outcome
    return outcome


def _latest_health(env: Any) -> Any:
    """The latest verdict of the process the caller built (facts only, never a judgement)."""
    wiring = env.assembly.wiring if env.assembly.is_complete else None
    return None if wiring is None else wiring.health.latest_verdict
