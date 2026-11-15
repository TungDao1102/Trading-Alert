"""The probe verbs of the live process and the OPS-04 diagnostics (plan 24-11; D-03, D-31, T-04).

`--liveness` and `--healthcheck` read two small files and the limits file; they open no network or
database client (the socket and the engine factory are replaced by functions that fail the test).
The revision and Python version reach the health output without git (OPS-04).
"""

from __future__ import annotations

import json
import socket
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy
from src.adapters.code_version import CodeVersionError
from src.backtest.experiment import CodeVersion
from src.live import runtime
from src.live.config import (
    LIVE_LIVENESS_SCHEMA,
    live_liveness_path,
    write_live_liveness,
)
from src.paper import held_marker

from tests.support.execution_limits import (
    TEST_ONLY_EXECUTION_LIMIT_VALUES,
    write_execution_limits_toml,
)

NOW = datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC)
BOUND_MS = TEST_ONLY_EXECUTION_LIMIT_VALUES["stale_feed.max_mark_price_age_ms"]
REVISION = "0123456789abcdef0123456789abcdef01234567"
SEEDED_SECRET = "demo-secret-SEEDED-9876543210"


@pytest.fixture
def limits_file(tmp_path: Path) -> Path:
    return write_execution_limits_toml(
        tmp_path / "limits.toml", values=dict(TEST_ONLY_EXECUTION_LIMIT_VALUES)
    )


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "state"
    directory.mkdir()
    return directory


@pytest.fixture(autouse=True)
def _no_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """A probe that opens a socket or builds a database engine fails the test."""

    def refuse_socket(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a probe must not open a socket")

    def refuse_engine(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a probe must not build a database engine")

    monkeypatch.setattr(socket, "socket", refuse_socket)
    monkeypatch.setattr(socket, "create_connection", refuse_socket)
    monkeypatch.setattr(sqlalchemy, "create_engine", refuse_engine)


def probe(
    verb: str,
    state_dir: Path,
    limits_file: Path,
    *,
    environ: dict[str, str] | None = None,
    now: datetime = NOW,
) -> int:
    return runtime.main(
        [verb, "--state-dir", str(state_dir)],
        environ={"LIVE_RUNTIME_MODE": "DEMO", "BINANCE_DEMO_API_SECRET": SEEDED_SECRET}
        if environ is None
        else environ,
        clock=lambda: now,
        limits_path=limits_file,
    )


def stamp(state_dir: Path, *, age_ms: int = 0, tasks: dict[str, str] | None = None) -> None:
    write_live_liveness(
        state_dir,
        mode="DEMO",
        loop_alive_utc=NOW - timedelta(milliseconds=age_ms),
        tasks={"reconcile": "PASS", "user_data": "PASS"} if tasks is None else tasks,
    )


# --------------------------------------------------------------------------- #
# --liveness
# --------------------------------------------------------------------------- #


def test_liveness_passes_with_a_fresh_stamp_and_no_marker(
    state_dir: Path, limits_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stamp(state_dir, age_ms=BOUND_MS)
    assert probe("--liveness", state_dir, limits_file) == 0
    out = capsys.readouterr().out
    assert out.strip() == "live"
    assert SEEDED_SECRET not in out


def test_liveness_fails_one_millisecond_past_the_bound(
    state_dir: Path, limits_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stamp(state_dir, age_ms=BOUND_MS + 1)
    assert probe("--liveness", state_dir, limits_file) == 1
    assert "not live" in capsys.readouterr().out


def test_liveness_fails_with_a_held_marker_even_with_a_fresh_stamp(
    state_dir: Path, limits_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stamp(state_dir)
    held_marker.write_marker(state_dir, code=3, refusal="CREDENTIAL_REFUSED")
    assert probe("--liveness", state_dir, limits_file) == 1
    assert "CREDENTIAL_REFUSED" in capsys.readouterr().out


def test_liveness_fails_without_a_stamp(
    state_dir: Path, limits_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert probe("--liveness", state_dir, limits_file) == 1
    assert "no liveness stamp" in capsys.readouterr().out


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        json.dumps({"schema": "live-liveness/0"}),
        json.dumps({"schema": LIVE_LIVENESS_SCHEMA, "container": "x"}),
        json.dumps(
            {
                "schema": LIVE_LIVENESS_SCHEMA,
                "container": held_marker.container_name(),
                "mode": "DEMO",
                "loop_alive_utc": "2026-10-31T12:00:00",
                "tasks": {},
            }
        ),
        json.dumps(
            {
                "schema": LIVE_LIVENESS_SCHEMA,
                "container": held_marker.container_name(),
                "mode": "DEMO",
                "loop_alive_utc": "2026-10-31T12:00:00+00:00",
                "tasks": {"reconcile": 1},
            }
        ),
    ],
)
def test_liveness_fails_with_a_corrupt_stamp(
    state_dir: Path, limits_file: Path, content: str, capsys: pytest.CaptureFixture[str]
) -> None:
    live_liveness_path(state_dir).write_text(content, encoding="utf-8")
    assert probe("--liveness", state_dir, limits_file) == 1
    assert "unreadable" in capsys.readouterr().out


def test_liveness_fails_for_a_stamp_dated_in_the_future(
    state_dir: Path, limits_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stamp(state_dir, age_ms=-1000)
    assert probe("--liveness", state_dir, limits_file) == 1
    assert "future" in capsys.readouterr().out


def test_liveness_fails_when_the_bound_key_is_not_configured(
    tmp_path: Path, state_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    values: dict[str, int | None] = dict(TEST_ONLY_EXECUTION_LIMIT_VALUES)
    values["stale_feed.max_mark_price_age_ms"] = None
    unset = write_execution_limits_toml(tmp_path / "unset.toml", values=values)
    stamp(state_dir)
    assert probe("--liveness", state_dir, unset) == 1
    assert "stale_feed.max_mark_price_age_ms" in capsys.readouterr().out


def test_liveness_fails_when_the_limits_file_is_missing(
    tmp_path: Path, state_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stamp(state_dir)
    assert probe("--liveness", state_dir, tmp_path / "missing.toml") == 1
    assert "not live" in capsys.readouterr().out


def test_the_stamp_belongs_to_one_container(
    state_dir: Path, limits_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_live_liveness(
        state_dir, mode="DEMO", loop_alive_utc=NOW, tasks={}, container="another-container"
    )
    assert probe("--liveness", state_dir, limits_file) == 1
    assert "no liveness stamp" in capsys.readouterr().out


def test_the_two_probes_cannot_be_combined(state_dir: Path, limits_file: Path) -> None:
    code = runtime.main(
        ["--liveness", "--healthcheck", "--state-dir", str(state_dir)],
        environ={},
        clock=lambda: NOW,
        limits_path=limits_file,
    )
    assert code == 2


# --------------------------------------------------------------------------- #
# --healthcheck
# --------------------------------------------------------------------------- #


def test_healthcheck_prints_one_json_object_and_exits_zero_when_live(
    state_dir: Path, limits_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stamp(state_dir, age_ms=1000, tasks={"reconcile": "PASS", "user_data": "DEGRADED"})
    environ = {
        "LIVE_RUNTIME_MODE": "DEMO",
        "TRADING_APP_REVISION": REVISION,
        "BINANCE_DEMO_API_SECRET": SEEDED_SECRET,
    }
    assert probe("--healthcheck", state_dir, limits_file, environ=environ) == 0
    out = capsys.readouterr().out
    assert SEEDED_SECRET not in out
    payload = json.loads(out)
    assert payload["mode"] == "DEMO"
    assert payload["python_version"] == sys.version
    assert payload["app_revision"] == REVISION
    assert payload["held"] is False
    assert payload["liveness_age_ms"] == 1000
    assert payload["tasks"] == {"reconcile": "PASS", "user_data": "DEGRADED"}
    assert payload["healthy"] is True
    assert payload["problem"] is None


def test_healthcheck_reports_unhealthy_with_a_held_marker(
    state_dir: Path, limits_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stamp(state_dir)
    held_marker.write_marker(state_dir, code=5, refusal="MODE_REFUSED")
    assert probe("--healthcheck", state_dir, limits_file) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["held"] is True
    assert payload["held_refusal"] == "MODE_REFUSED"
    assert payload["healthy"] is False


def test_healthcheck_reports_unhealthy_for_a_stale_stamp_and_still_answers(
    state_dir: Path, limits_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stamp(state_dir, age_ms=BOUND_MS + 500)
    assert probe("--healthcheck", state_dir, limits_file) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["liveness_age_ms"] == BOUND_MS + 500
    assert payload["healthy"] is False
    assert "python_version" in payload


def test_healthcheck_without_a_stamp_answers_unhealthy(
    state_dir: Path, limits_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert probe("--healthcheck", state_dir, limits_file) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["liveness_age_ms"] is None
    assert payload["tasks"] == {}


def test_healthcheck_names_an_unresolved_mode(
    state_dir: Path, limits_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert probe("--healthcheck", state_dir, limits_file, environ={"LIVE_RUNTIME_MODE": "x"}) == 1
    assert json.loads(capsys.readouterr().out)["mode"] == "UNRESOLVED"


def test_the_probes_open_no_socket_and_no_engine(
    state_dir: Path, limits_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The autouse guard raises on a socket or engine open; both verbs run through it."""
    stamp(state_dir)
    assert probe("--liveness", state_dir, limits_file) == 0
    assert probe("--healthcheck", state_dir, limits_file) == 0
    capsys.readouterr()
    with pytest.raises(AssertionError, match="socket"):
        socket.socket()


# --------------------------------------------------------------------------- #
# OPS-04: the Python version and the revision without git
# --------------------------------------------------------------------------- #


class RecordingReader:
    def __init__(self, result: CodeVersion | Exception) -> None:
        self.result = result
        self.calls = 0

    def __call__(self, _root: Path) -> CodeVersion:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_the_stamp_wins_and_git_is_not_asked() -> None:
    reader = RecordingReader(CodeVersion(commit="f" * 40, dirty=False))
    payload = runtime.diagnostic_payload({"TRADING_APP_REVISION": REVISION}, version_reader=reader)
    assert payload == {"python_version": sys.version, "app_revision": REVISION}
    assert reader.calls == 0


def test_a_malformed_stamp_gives_unknown_and_names_the_problem_without_the_value() -> None:
    reader = RecordingReader(CodeVersion(commit="f" * 40, dirty=False))
    bad = "NOT-A-REVISION-SEEDED"
    payload = runtime.diagnostic_payload({"TRADING_APP_REVISION": bad}, version_reader=reader)
    assert payload["app_revision"] == "unknown"
    assert "TRADING_APP_REVISION" in payload["app_revision_problem"]
    assert bad not in json.dumps(payload)
    assert reader.calls == 0


@pytest.mark.parametrize(
    "bad", ["", REVISION.upper(), REVISION[:-1], REVISION + "0", f" {REVISION}"]
)
def test_a_stamp_that_is_not_exactly_forty_lowercase_hex_is_malformed(bad: str) -> None:
    payload = runtime.diagnostic_payload({"TRADING_APP_REVISION": bad})
    assert payload["app_revision"] == "unknown"
    assert "app_revision_problem" in payload


def test_an_absent_stamp_on_a_dev_checkout_falls_back_to_the_code_version_reader() -> None:
    reader = RecordingReader(CodeVersion(commit=REVISION, dirty=False))
    payload = runtime.diagnostic_payload({}, version_reader=reader)
    assert payload["app_revision"] == REVISION
    assert reader.calls == 1
    assert "app_revision_problem" not in payload


def test_an_absent_stamp_without_git_is_unknown() -> None:
    reader = RecordingReader(CodeVersionError("git executable not found"))
    payload = runtime.diagnostic_payload({}, version_reader=reader)
    assert payload["app_revision"] == "unknown"
    assert "app_revision_problem" not in payload
    assert payload["python_version"] == sys.version


def test_healthcheck_never_fails_for_a_missing_revision(
    state_dir: Path,
    limits_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def no_git(_root: Path) -> Any:
        raise CodeVersionError("git executable not found")

    monkeypatch.setattr(runtime, "read_code_version", no_git)
    stamp(state_dir)
    assert probe("--healthcheck", state_dir, limits_file) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["app_revision"] == "unknown"
    assert payload["healthy"] is True
