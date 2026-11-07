"""Session guard and fixtures of the owner-run Binance Demo suite (plans 25-01 and 25-09, OPS-02).

OWNER ONLY. Never run by CI or by an agent; every item here is skipped by the collection hook of
`tests/conftest.py` unless `-m demo` is selected together with `TRADING_DEMO_RUN=1`. Run it as

    $env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s

One Demo account and one user-data listenKey exist, so the suite never runs in parallel. The
guard below refuses a `BINANCE_LIVE_*` name, an xdist worker and a non-DEMO mode, by name only.
In a CI run these fixtures are never instantiated: every demo item is skipped at setup.

The fixture contract pinned by plan 25-08 (`harness.FIXTURE_SCENARIO_RECORDER` and
`FIXTURE_MAKE_DEMO_ENV`); scenario plans use them and never redefine them:

* `scenario_recorder(scenario_id)`: an EXECUTE-mode `ScenarioRecorder` whose `write()` goes to the
  phase evidence directory;
* `make_demo_env(recorder, options)`: an async callable that builds the real live process on Demo
  through `build_demo_scenario_env` with `os.environ`; the first env of the session may initialize
  the REST gate state (`TRADING_DEMO_INITIALIZE_GATE_STATE=1`), a restart never does.

Every owner session ends with one evidence index over the files it wrote (a recorder a failing
test never wrote is written first, outcome FAILED).
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Iterator

import pytest

from tests.support.demo_guard import DemoRunRefused, assert_demo_run_environment
from tests.support.demo_scenarios.demo_env import (
    EVIDENCE_DIR,
    DemoScenarioEnv,
    GateInitializer,
    SessionEvidence,
    build_demo_scenario_env,
)
from tests.support.demo_scenarios.harness import EnvOptions, ScenarioRecorder


@pytest.fixture(scope="session", autouse=True)
def _demo_run_guard() -> None:
    """Refuse to start a Demo session next to LIVE credentials, under xdist or outside DEMO."""
    try:
        assert_demo_run_environment(os.environ)
    except DemoRunRefused as refusal:
        pytest.fail(f"Demo suite refused: {refusal}", pytrace=False)


@pytest.fixture(scope="session")
def demo_session_evidence(_demo_run_guard: None) -> Iterator[SessionEvidence]:
    """The recorders of this session; its teardown writes the one session evidence index."""
    session = SessionEvidence(EVIDENCE_DIR, environ=os.environ)
    yield session
    index = session.finish()
    if index is not None:
        print(f"Demo session evidence index: {index}", flush=True)


@pytest.fixture(scope="session")
def _gate_initializer(_demo_run_guard: None) -> GateInitializer:
    return GateInitializer(os.environ)


@pytest.fixture
def scenario_recorder(
    demo_session_evidence: SessionEvidence,
) -> Callable[[str], ScenarioRecorder]:
    """`(scenario_id) -> ScenarioRecorder` in EXECUTE mode, writing to the phase evidence dir."""
    return demo_session_evidence.recorder


@pytest.fixture
def make_demo_env(
    _gate_initializer: GateInitializer,
) -> Callable[..., Awaitable[DemoScenarioEnv]]:
    """`async (recorder, options) -> env`: the real live process on Binance Demo (D-04, D-08)."""

    async def make(
        recorder: ScenarioRecorder, options: EnvOptions | None = None
    ) -> DemoScenarioEnv:
        return build_demo_scenario_env(
            recorder,
            options if options is not None else EnvOptions(),
            environ=os.environ,
            initialize_gate_state=_gate_initializer.take(),
        )

    return make
