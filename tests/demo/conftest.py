"""Session guard of the owner-run Binance Demo suite (plan 25-01, D-03, OPS-02).

OWNER ONLY. Never run by CI or by an agent; every item here is skipped by the collection hook of
`tests/conftest.py` unless `-m demo` is selected together with `TRADING_DEMO_RUN=1`. Run it as

    $env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s

One Demo account and one user-data listenKey exist, so the suite never runs in parallel. The
guard below refuses a `BINANCE_LIVE_*` name, an xdist worker and a non-DEMO mode, by name only.
In a CI run this fixture is never instantiated: every demo item is skipped at setup.
"""

from __future__ import annotations

import os

import pytest

from tests.support.demo_guard import DemoRunRefused, assert_demo_run_environment


@pytest.fixture(scope="session", autouse=True)
def _demo_run_guard() -> None:
    """Refuse to start a Demo session next to LIVE credentials, under xdist or outside DEMO."""
    try:
        assert_demo_run_environment(os.environ)
    except DemoRunRefused as refusal:
        pytest.fail(f"Demo suite refused: {refusal}", pytrace=False)
