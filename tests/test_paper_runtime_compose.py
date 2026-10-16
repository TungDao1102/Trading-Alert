"""Plan 16-22: the paper process entrypoint `python -m src.paper.runtime` (D-01, L-05, D061 E).

Task 1 is the tracer: an empty allowlist ends the process with exit 0 and the event text
"SKIPPED (allowlist empty)" before any adapter, database engine or Telegram application exists.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from src.paper import runtime, runtime_config
from src.paper.runtime_config import REFUSAL_CODES, ExitCode

REPO_ROOT = Path(__file__).resolve().parent.parent
SKIPPED_TEXT = "SKIPPED (allowlist empty)"
BASE_ENV = {
    "PAPER_STRATEGY_ID": "trend-pullback",
    "PAPER_PARAMETER_SET_ID": "baseline-v3",
}


class _ConstructionSpy:
    """Fails the test when any of the production collaborators is constructed."""

    def __init__(self) -> None:
        self.constructed: list[str] = []


@pytest.fixture
def construction_spy(monkeypatch: pytest.MonkeyPatch) -> _ConstructionSpy:
    import sqlalchemy
    from src.adapters import binance_public, paper_ws
    from src.db import models

    spy = _ConstructionSpy()

    def trip(label: str) -> object:
        def _tripped(*_args: object, **_kwargs: object) -> None:
            spy.constructed.append(label)
            raise AssertionError(f"{label} was constructed before the start gate")

        return _tripped

    monkeypatch.setattr(paper_ws.PaperWsAdapter, "__init__", trip("PaperWsAdapter"))
    monkeypatch.setattr(
        binance_public.BinancePublicMarketData, "__init__", trip("BinancePublicMarketData")
    )
    monkeypatch.setattr(sqlalchemy, "create_engine", trip("sqlalchemy.create_engine"))
    monkeypatch.setattr(models, "make_engine", trip("make_engine"))
    try:
        from telegram.ext import ApplicationBuilder

        monkeypatch.setattr(ApplicationBuilder, "build", trip("telegram Application"))
    except ImportError:  # pragma: no cover - telegram is a locked dependency
        pass
    return spy


@pytest.fixture(autouse=True)
def _start_from_an_empty_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests exercise the runtime on an empty allowlist unless a test injects entries.

    The production allowlist holds the user's single entry since checkpoint G4-021 (pinned in
    tests/test_paper_start_gate.py), so each test here starts from an injected empty one.
    """
    import src.paper.freeze as freeze

    monkeypatch.setattr(freeze, "PAPER_START_ALLOWLIST", ())


def test_empty_allowlist_exits_zero_skipped_and_builds_nothing(
    construction_spy: _ConstructionSpy, capsys: pytest.CaptureFixture[str]
) -> None:
    code = runtime.main([], environ=dict(BASE_ENV))

    assert code == 0
    assert SKIPPED_TEXT in capsys.readouterr().out
    assert construction_spy.constructed == []


def test_module_entrypoint_answers_help() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "src.paper.runtime", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--hold-on-refusal" in completed.stdout


def test_exit_code_table_is_exactly_the_documented_one() -> None:
    assert {member.name: int(member) for member in ExitCode} == {
        "OK": 0,
        "USAGE": 2,
        "TRADE_KEY_REFUSED": 3,
        "CONFIG_NOT_RATIFIED": 4,
        "NO_PINNED_EPOCH": 5,
        "ADMISSION_OR_EPOCH_MISMATCH": 6,
        "FAIL_CLOSED_RUNTIME": 7,
        "INSTANCE_LEASE_HELD": 8,
    }
    assert REFUSAL_CODES == frozenset({3, 4, 5, 6, 8})
    assert 1 not in REFUSAL_CODES, "status 1 is an uncaught exception and is restartable"
    assert int(ExitCode.FAIL_CLOSED_RUNTIME) not in REFUSAL_CODES


def test_readme_names_every_exit_code_member() -> None:
    text = (REPO_ROOT / "config" / "paper" / "README.md").read_text(encoding="utf-8")
    for member in ExitCode:
        assert f"`{member.name}`" in text, f"config/paper/README.md lacks {member.name}"


def test_module_docstring_states_which_codes_are_restartable() -> None:
    doc = runtime_config.__doc__ or ""
    assert "restartable" in doc
    assert "never succeed" in doc


def _stop_recorder() -> tuple[list[int], object]:
    stops: list[int] = []

    def wait_for_stop() -> None:
        stops.append(1)

    return stops, wait_for_stop


def test_hold_on_refusal_holds_until_the_stop_then_returns_the_refusal_code(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    stops, wait_for_stop = _stop_recorder()
    environ = {**BASE_ENV, "BINANCE_LIVE_API_KEY": "x"}

    code = runtime.main(
        ["--hold-on-refusal", "--pinned-state", str(tmp_path / "pinned_epoch.json")],
        environ=environ,
        wait_for_stop=wait_for_stop,  # type: ignore[arg-type]
    )

    assert code == ExitCode.TRADE_KEY_REFUSED
    assert stops == [1]
    assert "BINANCE_LIVE_API_KEY" in capsys.readouterr().err


def test_refusal_without_the_flag_returns_at_once(capsys: pytest.CaptureFixture[str]) -> None:
    stops, wait_for_stop = _stop_recorder()
    environ = {**BASE_ENV, "BINANCE_LIVE_API_KEY": "x"}

    code = runtime.main([], environ=environ, wait_for_stop=wait_for_stop)  # type: ignore[arg-type]

    assert code == ExitCode.TRADE_KEY_REFUSED
    assert stops == []
    capsys.readouterr()


def test_skipped_holds_with_the_flag_and_returns_0_only_when_stopped(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """16-55 Q1 = A amends the 16-22 rule "SKIPPED never holds" (16-DEC-RESTART-POLICY).

    Under `restart: unless-stopped` an exit 0 is restarted, so SKIPPED holds like a refusal.
    """
    stops, wait_for_stop = _stop_recorder()

    code = runtime.main(
        ["--hold-on-refusal", "--pinned-state", str(tmp_path / "pinned_epoch.json")],
        environ=dict(BASE_ENV),
        wait_for_stop=wait_for_stop,  # type: ignore[arg-type]
    )

    assert code == 0
    assert stops == [1]
    assert SKIPPED_TEXT in capsys.readouterr().out


def test_skipped_without_the_flag_returns_0_at_once(capsys: pytest.CaptureFixture[str]) -> None:
    stops, wait_for_stop = _stop_recorder()

    code = runtime.main([], environ=dict(BASE_ENV), wait_for_stop=wait_for_stop)  # type: ignore[arg-type]

    assert code == 0
    assert stops == []
    assert SKIPPED_TEXT in capsys.readouterr().out


def test_production_wait_for_stop_is_the_default_and_blocks_on_a_signal() -> None:
    import inspect

    default = inspect.signature(runtime.main).parameters["wait_for_stop"].default
    assert default is None, "None selects the production signal wait inside main"
    assert callable(runtime.wait_for_stop_signal)
