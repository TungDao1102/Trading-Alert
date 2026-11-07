"""The session guard of the owner-run Demo suite (plan 25-01, D-03, OPS-02, T-25-02, T-25-03).

TEST_ONLY: the environments are fakes with sentinel values and nothing opens a network client.
The guard must refuse a LIVE credential name, an xdist worker, a missing run variable and a
non-DEMO mode, and every refusal names variables only, never a value.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from src.adapters.binance_client import Environment
from src.ops import redaction

from tests.support.demo_guard import DemoRunRefused, assert_demo_run_environment

SENTINELS = {
    "BINANCE_DEMO_API_KEY": "FAKE-DEMO-KEY-SENTINEL-0101",
    "BINANCE_DEMO_API_SECRET": "FAKE-DEMO-SECRET-SENTINEL-0102",
    "TELEGRAM_LIVE_BOT_TOKEN": "999999:FAKE-BOT-TOKEN-SENTINEL-0103",
    "BINANCE_LIVE_API_KEY": "FAKE-LIVE-KEY-SENTINEL-0104",
    "BINANCE_LIVE_API_SECRET": "FAKE-LIVE-SECRET-SENTINEL-0105",
}


@pytest.fixture(autouse=True)
def _clean_redaction() -> Iterator[None]:
    """`parse_live_environment` registers its secrets process-wide; undo that around each test."""
    redaction.clear_runtime_secrets()
    yield
    redaction.clear_runtime_secrets()


def _demo_environ(**extra: str) -> dict[str, str]:
    environ = {
        "TRADING_DEMO_RUN": "1",
        "LIVE_RUNTIME_MODE": "DEMO",
        "BINANCE_DEMO_API_KEY": SENTINELS["BINANCE_DEMO_API_KEY"],
        "BINANCE_DEMO_API_SECRET": SENTINELS["BINANCE_DEMO_API_SECRET"],
        "TELEGRAM_LIVE_BOT_TOKEN": SENTINELS["TELEGRAM_LIVE_BOT_TOKEN"],
        "TELEGRAM_LIVE_AUTHORIZED_CHAT_ID": "424242",
        "TELEGRAM_AUTHORIZED_USER_IDS": "424242",
    }
    environ.update(extra)
    return environ


def _refusal(environ: dict[str, str]) -> str:
    with pytest.raises(DemoRunRefused) as raised:
        assert_demo_run_environment(environ)
    message = str(raised.value)
    for sentinel in SENTINELS.values():
        assert sentinel not in message, "a refusal message must name variables, never values"
    return message


def test_a_complete_demo_environment_returns_the_admitted_demo_config() -> None:
    config = assert_demo_run_environment(_demo_environ())
    assert config.mode is Environment.DEMO


def test_any_binance_live_name_is_refused_by_name_and_not_by_value() -> None:
    message = _refusal(_demo_environ(BINANCE_LIVE_API_KEY=SENTINELS["BINANCE_LIVE_API_KEY"]))
    assert "BINANCE_LIVE_API_KEY" in message


def test_a_binance_live_name_outside_the_credential_pair_is_refused_too() -> None:
    message = _refusal(_demo_environ(BINANCE_LIVE_ANYTHING_ELSE="x"))
    assert "BINANCE_LIVE_ANYTHING_ELSE" in message


def test_both_live_credentials_are_named_in_sorted_order() -> None:
    message = _refusal(
        _demo_environ(
            BINANCE_LIVE_API_SECRET=SENTINELS["BINANCE_LIVE_API_SECRET"],
            BINANCE_LIVE_API_KEY=SENTINELS["BINANCE_LIVE_API_KEY"],
        )
    )
    assert message.index("BINANCE_LIVE_API_KEY") < message.index("BINANCE_LIVE_API_SECRET")


def test_an_xdist_worker_is_refused() -> None:
    message = _refusal(_demo_environ(PYTEST_XDIST_WORKER="gw0"))
    assert "PYTEST_XDIST_WORKER" in message
    assert "xdist" in message


@pytest.mark.parametrize("value", [None, "", "0", "true"])
def test_a_missing_or_inexact_run_variable_is_refused(value: str | None) -> None:
    environ = _demo_environ()
    del environ["TRADING_DEMO_RUN"]
    if value is not None:
        environ["TRADING_DEMO_RUN"] = value
    assert "TRADING_DEMO_RUN" in _refusal(environ)


def test_a_missing_mode_is_refused_with_the_admission_reason() -> None:
    environ = _demo_environ()
    del environ["LIVE_RUNTIME_MODE"]
    assert "LIVE_RUNTIME_MODE" in _refusal(environ)


def test_a_non_demo_mode_is_refused_with_the_admission_reason() -> None:
    message = _refusal(_demo_environ(LIVE_RUNTIME_MODE="LIVE"))
    assert "DEMO" in message or "LIVE" in message


def test_missing_demo_credentials_are_refused_by_name() -> None:
    environ = _demo_environ()
    del environ["BINANCE_DEMO_API_SECRET"]
    assert "BINANCE_DEMO_API_SECRET" in _refusal(environ)


def test_the_shadow_bot_token_next_to_the_demo_run_is_refused() -> None:
    message = _refusal(_demo_environ(TELEGRAM_BOT_TOKEN="123:SHADOW-SENTINEL-0106"))
    assert "SHADOW-SENTINEL-0106" not in message
    assert "TELEGRAM_BOT_TOKEN" in message
