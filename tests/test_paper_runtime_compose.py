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


# ---- plan 16-56 Task 2: the state port's engine and an unreachable database (B1-WR-02) ------- #

_DB_URL = "postgresql://paper:not-a-real-password@127.0.0.1:1/trading"


def test_the_state_port_is_built_with_make_sync_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.persistence.engine as engine_module

    seen: list[str] = []

    def spy(url: str, **_kwargs: object) -> object:
        seen.append(url)
        raise engine_module.StoreUnavailable("cannot reach PostgreSQL (OperationalError)")

    monkeypatch.setattr(engine_module, "make_sync_engine", spy)
    with pytest.raises(engine_module.StoreUnavailable):
        runtime._state_from_env({"DATABASE_URL_SYNC": _DB_URL})
    assert seen == [_DB_URL], "timeouts, pool_pre_ping and the UTC pin come from make_sync_engine"


@pytest.fixture
def admitted_rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> object:
    import src.domain.registry as domain_registry

    from tests.test_paper_runtime_admission import _Rig
    from tests.test_rationale import write_rationalized_set

    rig = _Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(domain_registry, "REGISTRY_ROOT", rig.root)
    write_rationalized_set(rig.root)
    rig.authorize()
    return rig


@pytest.mark.parametrize("error_name", ["StoreUnavailable", "SessionTimeZoneNotUtc"])
def test_an_unreachable_database_at_start_exits_7_with_one_line_and_no_traceback(
    admitted_rig: object,
    error_name: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import src.persistence.engine as engine_module
    import src.persistence.errors as errors

    error = getattr(errors, error_name)

    def unreachable(_url: str, **_kwargs: object) -> object:
        raise error("details that name the host 127.0.0.1")

    monkeypatch.setattr(engine_module, "make_sync_engine", unreachable)
    rig: object = admitted_rig
    started: list[object] = []
    code = runtime.main(
        ["--pinned-state", str(rig.pinned_path)],  # type: ignore[attr-defined]
        environ={**rig.environ(), "DATABASE_URL_SYNC": _DB_URL},  # type: ignore[attr-defined]
        wait_for_stop=lambda: None,
        registry_root=rig.root,  # type: ignore[attr-defined]
        run_loop=started.append,
    )

    assert code == ExitCode.FAIL_CLOSED_RUNTIME == 7
    assert started == [], "no run, so no RUNTIME_START"
    err = capsys.readouterr().err
    lines = [line for line in err.splitlines() if line.strip()]
    assert len(lines) == 1, err
    assert error_name in lines[0]
    assert "Traceback" not in err and "not-a-real-password" not in err


@pytest.mark.parametrize("error_name", ["StoreUnavailable", "SessionTimeZoneNotUtc"])
def test_the_healthcheck_answers_unhealthy_on_an_unreachable_database(
    admitted_rig: object,
    error_name: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import src.persistence.engine as engine_module
    import src.persistence.errors as errors

    from tests.test_paper_runtime_admission import _Rig

    rig = admitted_rig
    assert isinstance(rig, _Rig)
    assert rig.run("--pin-epoch") == 0
    capsys.readouterr()  # the pin's own output
    error = getattr(errors, error_name)

    def unreachable(_url: str, **_kwargs: object) -> object:
        raise error("details")

    monkeypatch.setattr(engine_module, "make_sync_engine", unreachable)
    code = runtime.main(
        ["--healthcheck", "--pinned-state", str(rig.pinned_path)],
        environ={**rig.environ(), "DATABASE_URL_SYNC": _DB_URL},
        registry_root=rig.root,
    )
    assert code == 1
    out = capsys.readouterr().out
    assert out.startswith("unhealthy") and error_name in out


def test_the_production_public_adapter_maps_sdk_transport_errors() -> None:
    """The paper path's reader raises project errors, so the poller's one retry can match them."""
    public = runtime._resolve_public(runtime.LoopWiring())
    assert public._project_errors is True
