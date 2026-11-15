"""TEST_ONLY: the pytest-level refusal of the owner-run Binance Demo suite (plan 25-01, OPS-02).

`assert_demo_run_environment(environ)` is called once per session by `tests/demo/conftest.py`. It
refuses, in this order, always naming variables and never values:

1. any `BINANCE_LIVE_*` name (LIVE credentials may not share a process with a Demo run);
2. a pytest-xdist worker (`PYTEST_XDIST_WORKER`): one Demo account, one listenKey;
3. a `TRADING_DEMO_RUN` that is not exactly `1`;
4. an environment the smoke does not admit (`admit_smoke_environment`: non-DEMO mode, missing
   or foreign credentials, the shadow bot token, a `NOT_CONFIGURED` limit).

It reads no clock, opens no network client and never prints the environment.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

LIVE_CREDENTIAL_PREFIX = "BINANCE_LIVE_"
XDIST_WORKER_VARIABLE = "PYTEST_XDIST_WORKER"
DEMO_RUN_VARIABLE = "TRADING_DEMO_RUN"


class DemoRunRefused(Exception):  # noqa: N818 - a refusal before any Demo test starts
    """The process may not run the Demo suite; the message names variables, never values."""


def assert_demo_run_environment(environ: Mapping[str, str]) -> Any:
    """The admitted DEMO `LiveConfig`, or `DemoRunRefused` (names only)."""
    live_names = sorted(name for name in environ if name.startswith(LIVE_CREDENTIAL_PREFIX))
    if live_names:
        raise DemoRunRefused(
            f"{', '.join(live_names)} present: the Demo suite never runs next to LIVE credentials"
        )
    if XDIST_WORKER_VARIABLE in environ:
        raise DemoRunRefused(
            f"{XDIST_WORKER_VARIABLE} present: the Demo suite never runs under xdist "
            "(one Demo account, one listenKey); use -p no:xdist"
        )
    if environ.get(DEMO_RUN_VARIABLE) != "1":
        raise DemoRunRefused(f"{DEMO_RUN_VARIABLE} must be 1 to run the Demo suite")

    from scripts.demo_rehearsal import SmokeRefused, admit_smoke_environment

    try:
        return admit_smoke_environment(environ)
    except SmokeRefused as refusal:
        raise DemoRunRefused(f"the environment is not admitted as a DEMO run: {refusal}") from None
