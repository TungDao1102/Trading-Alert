"""S07 restart mid-flow on Binance Demo (plan 25-12; EXEC-01, EXEC-03, D079, D080).

OWNER ONLY (`-m demo` with `TRADING_DEMO_RUN=1`); skipped in every agent and CI run. Each test
builds the real live process on Demo (`make_demo_env`), crashes it at one cut (`abandon`: no drain,
the listenKey kept) and starts a second process over the same stores and the same exchange, with
the SAME `s07_restart_cuts.run(env, recorder, cut=...)` the CI twin runs on the fake.

* cut c, after the fill and the confirmed stop: the second process rehydrates the plan protected,
  sends nothing and the first reconcile is clean (DEMO_OBSERVED).
* cut a, before the entry answer is known: the lost answer and the failed in-process probe are
  injected (DEMO_FAULT_INJECTED); the second process probes once by client id, finds the entry and
  tracks it; one `place_entry` across both processes.
* cut b, between the fill and the stop: the stop placement is held (DEMO_FAULT_INJECTED) and the
  process crashes; the second process protects or closes the position. This leaves a REAL Demo
  position without a stop for the time of the restart.

Every cut ends flat with the account clean; the account must be clean at the start
(`scripts/demo_clear.py` otherwise).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s07_restart_cuts
from tests.support.demo_scenarios.harness import EnvOptions, ScenarioRecorder

pytestmark = pytest.mark.demo


async def _run_cut(
    cut: str,
    scenario_recorder: Callable[[str], ScenarioRecorder],
    make_demo_env: Callable[..., Awaitable[Any]],
) -> None:
    recorder = scenario_recorder("S07")
    env = await make_demo_env(recorder, EnvOptions())
    try:
        outcome = await s07_restart_cuts.run(env, recorder, cut=cut)
    finally:
        # `run` stops the running process in order whatever happens; keep the evidence on failure.
        recorder.write()
    assert outcome in (dr.OUTCOME_COMPLETE, dr.OUTCOME_COMPLETE_WITH_GAPS), outcome
    assert recorder.default_label == dr.EVIDENCE_KIND_DEMO


async def test_s07_cut_c_a_restart_after_the_fill_and_the_stop_rehydrates_protected_on_demo(
    scenario_recorder: Callable[[str], ScenarioRecorder],
    make_demo_env: Callable[..., Awaitable[Any]],
) -> None:
    await _run_cut("c", scenario_recorder, make_demo_env)


async def test_s07_cut_a_a_lost_entry_answer_is_probed_once_and_never_resent_on_demo(
    scenario_recorder: Callable[[str], ScenarioRecorder],
    make_demo_env: Callable[..., Awaitable[Any]],
) -> None:
    await _run_cut("a", scenario_recorder, make_demo_env)


async def test_s07_cut_b_a_crash_between_the_fill_and_the_stop_is_protected_by_the_next_process(
    scenario_recorder: Callable[[str], ScenarioRecorder],
    make_demo_env: Callable[..., Awaitable[Any]],
) -> None:
    await _run_cut("b", scenario_recorder, make_demo_env)
