"""S00 preflight of the owner-run Demo suite (plan 25-01): no order, no network call.

Owner-run only (`-m demo` with TRADING_DEMO_RUN=1). It checks that the process environment is
admitted as a DEMO run and that the Demo host constant is the Demo Trading host. It never sends a
request, signed or not.
"""

from __future__ import annotations

import os

import pytest
from scripts import demo_rehearsal as dr
from src.adapters.binance_client import Environment

pytestmark = pytest.mark.demo


def test_s00_the_environment_is_admitted_as_demo_and_the_host_is_the_demo_host() -> None:
    config = dr.admit_smoke_environment(os.environ)
    assert config.mode is Environment.DEMO
    dr.assert_demo_base_url(dr.DEMO_BASE_URL)
