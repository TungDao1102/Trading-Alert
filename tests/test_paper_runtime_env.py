"""Plan 16-22: the environment layer of the paper runtime (D-13 layer 2, SC6, D040, T-16-50).

The runtime refuses to start when any `BINANCE_*` variable is present (names only are printed,
even an empty value refuses), and it reads only a closed set of variable names, so an unrelated
variable is neither used nor logged.
"""

from __future__ import annotations

import pytest
from src.paper import runtime
from src.paper.runtime_config import (
    ALLOWED_ENV_NAMES,
    ExitCode,
    read_env,
    refuse_trade_capable_env,
)

SECRET_VALUE = "s3cr3t-value-must-never-appear"
BASE_ENV = {
    "PAPER_STRATEGY_ID": "trend-pullback",
    "PAPER_PARAMETER_SET_ID": "baseline-v3",
}


class _Events:
    """Records the order in which the start gate reads the allowlist."""

    def __init__(self) -> None:
        self.calls: list[str] = []


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> _Events:
    seen = _Events()
    original = runtime.allowlist_entries

    def spy() -> tuple[object, ...]:
        seen.calls.append("allowlist")
        return tuple(original())

    monkeypatch.setattr(runtime, "allowlist_entries", spy)
    return seen


@pytest.mark.parametrize(
    "name", ["BINANCE_LIVE_API_KEY", "BINANCE_TESTNET_API_SECRET", "BINANCE_FOO"]
)
@pytest.mark.parametrize("value", [SECRET_VALUE, ""])
def test_any_binance_variable_refuses_with_code_3_names_only_before_the_allowlist(
    name: str,
    value: str,
    events: _Events,
    capsys: pytest.CaptureFixture[str],
) -> None:
    environ = {**BASE_ENV, name: value}

    code = runtime.main([], environ=environ)

    assert code == ExitCode.TRADE_KEY_REFUSED == 3
    captured = capsys.readouterr()
    assert name in captured.err
    assert SECRET_VALUE not in captured.err
    assert SECRET_VALUE not in captured.out
    assert events.calls == [], "the trade-key refusal must run before the allowlist is read"


def test_every_binance_name_is_listed_and_sorted() -> None:
    environ = {"BINANCE_B": "1", "BINANCE_A": "", "DATABASE_URL": "x", "binance_lower": "1"}

    assert refuse_trade_capable_env(environ) == ["BINANCE_A", "BINANCE_B"]


def test_no_binance_variable_means_no_refusal() -> None:
    assert refuse_trade_capable_env({"DATABASE_URL": "x", "PAPER_STRATEGY_ID": "y"}) == []


def test_read_env_keeps_only_allowed_names() -> None:
    environ = {
        "DATABASE_URL": "postgresql+psycopg://u@h/d",
        "PAPER_RUNTIME_CONFIG": "config/paper/paper-runtime-v1.toml",
        "UNRELATED_THING": "leak-me",
        "PATH": "/usr/bin",
    }

    read = read_env(environ)

    assert set(read) == {"DATABASE_URL", "PAPER_RUNTIME_CONFIG"}
    assert "UNRELATED_THING" not in read


def test_allowed_names_are_exactly_the_documented_set() -> None:
    assert ALLOWED_ENV_NAMES == frozenset(
        {
            "DATABASE_URL",
            "DATABASE_URL_SYNC",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "POSTGRES_DB",
            "POSTGRES_HOST",
            "POSTGRES_PORT",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_AUTHORIZED_CHAT_ID",
            "PAPER_RUNTIME_CONFIG",
            "PAPER_STRATEGY_ID",
            "PAPER_PARAMETER_SET_ID",
        }
    )
    assert not any(name.startswith("BINANCE_") for name in ALLOWED_ENV_NAMES)


@pytest.fixture(autouse=True)
def _start_from_an_empty_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests exercise the runtime on an empty allowlist unless a test injects entries.

    The production allowlist holds the user's single entry since checkpoint G4-021 (pinned in
    tests/test_paper_start_gate.py), so each test here starts from an injected empty one.
    """
    import src.paper.freeze as freeze

    monkeypatch.setattr(freeze, "PAPER_START_ALLOWLIST", ())


def test_unrelated_variable_is_never_logged(capsys: pytest.CaptureFixture[str]) -> None:
    environ = {**BASE_ENV, "UNRELATED_THING": "leak-me-please"}

    code = runtime.main([], environ=environ)

    assert code == ExitCode.OK
    captured = capsys.readouterr()
    assert "leak-me-please" not in captured.out + captured.err
    assert "UNRELATED_THING" not in captured.out + captured.err
