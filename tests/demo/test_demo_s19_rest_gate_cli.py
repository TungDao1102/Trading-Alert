"""S19 REST gate operator commands on Binance Demo (plan 25-14; OPS-01, D-06, P20-DEMO).

OWNER ONLY (`-m demo` with `TRADING_DEMO_RUN=1`); skipped in every agent and CI run. It builds the
real live process on Demo (`make_demo_env`) and runs the SAME `s19_rest_gate_cli.run(env, recorder)`
the CI twin runs on the fake.

A false 418 is injected under the real adapter (never provoked; DEMO_FAULT_INJECTED) and persisted
by the real gate. The process is stopped in order (RUNBOOK 22.5), `rest_gate_cli status` shows the
ban, `clear` refuses the future deadline, `clear --force` writes a fresh record and its audit lines
(`<state file>.clear-audit.jsonl`), the restarted process restores a clear gate and a request is
placed and cancelled. The commands run in process through `rest_gate_cli.main` and read the wall
clock; the state file is never edited by hand.

If the run stops after the injection and before the clear, the gate state file still holds a ban
that lasts days (the real fallback wait): stop the process, run
`python -m src.ops.rest_gate_cli status --path <state dir>/<gate state file>` and then `clear` with
`--force --operator-id <id> --reason "Phase 25 S19 false restriction"` (RUNBOOK 21.3) before any
other scenario.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios import s19_rest_gate_cli
from tests.support.demo_scenarios.harness import EnvOptions, ScenarioRecorder

pytestmark = pytest.mark.demo


async def test_s19_a_false_418_is_cleared_with_the_operator_commands_on_demo(
    scenario_recorder: Callable[[str], ScenarioRecorder],
    make_demo_env: Callable[..., Awaitable[Any]],
) -> None:
    recorder = scenario_recorder("S19")
    env = await make_demo_env(recorder, EnvOptions())
    try:
        outcome = await s19_rest_gate_cli.run(env, recorder)
    finally:
        recorder.write()
    assert outcome in (dr.OUTCOME_COMPLETE, dr.OUTCOME_COMPLETE_WITH_GAPS), outcome
    assert recorder.default_label == dr.EVIDENCE_KIND_DEMO
