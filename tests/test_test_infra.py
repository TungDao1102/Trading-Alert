"""Tests for the shared test-infrastructure helpers and the ``docker`` marker hook (13.1-01).

The helpers decide whether a missing piece of infrastructure (docker daemon, bash, a CLI
tool) skips a test locally or FAILS it in CI. ``TRADING_CI_STRICT=1`` is the switch: with it
set, a CI run can never pass vacuously by skipping every infrastructure-bound test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests import conftest, infra_helpers


class _FakeItem:
    """Minimal stand-in for a pytest Item: only the marker lookup the hook uses."""

    def __init__(self, *, docker: bool) -> None:
        self._docker = docker

    def get_closest_marker(self, name: str) -> object | None:
        return object() if (self._docker and name == "docker") else None


def test_infra_skip_skips_when_not_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(infra_helpers.STRICT_ENV, raising=False)
    with pytest.raises(pytest.skip.Exception) as excinfo:
        infra_helpers.infra_skip("x")
    assert "x" in str(excinfo.value)


def test_infra_skip_fails_when_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(infra_helpers.STRICT_ENV, "1")
    with pytest.raises(pytest.fail.Exception) as excinfo:
        infra_helpers.infra_skip("x")
    assert "x" in str(excinfo.value)


def test_infra_skip_strict_only_for_exact_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(infra_helpers.STRICT_ENV, "0")
    with pytest.raises(pytest.skip.Exception):
        infra_helpers.infra_skip("x")


def test_find_bash_rejects_windows_wsl_launcher(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(infra_helpers.sys, "platform", "win32")
    monkeypatch.setattr(
        infra_helpers.shutil, "which", lambda _name: r"C:\Windows\System32\bash.exe"
    )
    # ProgramFiles points at an empty dir, so the Git-for-Windows fallback is absent too.
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    assert infra_helpers.find_bash() is None


def test_find_bash_falls_back_to_program_files_git(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    git_bash = tmp_path / "Git" / "bin" / "bash.exe"
    git_bash.parent.mkdir(parents=True)
    git_bash.write_text("", encoding="utf-8")
    monkeypatch.setattr(infra_helpers.sys, "platform", "win32")
    monkeypatch.setattr(
        infra_helpers.shutil, "which", lambda _name: r"C:\Windows\System32\bash.exe"
    )
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    assert infra_helpers.find_bash() == str(git_bash)


def test_find_bash_returns_which_result_when_acceptable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(infra_helpers.shutil, "which", lambda _name: "/usr/bin/bash")
    assert infra_helpers.find_bash() == "/usr/bin/bash"


def test_require_tool_returns_path_or_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(infra_helpers.STRICT_ENV, raising=False)
    monkeypatch.setattr(infra_helpers.shutil, "which", lambda _name: "/opt/tool")
    assert infra_helpers.require_tool("tool") == "/opt/tool"
    monkeypatch.setattr(infra_helpers.shutil, "which", lambda _name: None)
    with pytest.raises(pytest.skip.Exception):
        infra_helpers.require_tool("tool")
    monkeypatch.setenv(infra_helpers.STRICT_ENV, "1")
    with pytest.raises(pytest.fail.Exception):
        infra_helpers.require_tool("tool")


def test_docker_marker_is_registered(pytestconfig: pytest.Config) -> None:
    markers = pytestconfig.getini("markers")
    assert any(str(m).startswith("docker:") for m in markers)


def test_docker_marked_item_skips_without_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(infra_helpers.STRICT_ENV, raising=False)
    monkeypatch.setattr(infra_helpers, "docker_daemon_reachable", lambda: (False, "daemon down"))
    with pytest.raises(pytest.skip.Exception) as excinfo:
        conftest.pytest_runtest_setup(_FakeItem(docker=True))  # type: ignore[arg-type]
    assert "docker daemon not reachable" in str(excinfo.value)
    assert "daemon down" in str(excinfo.value)


def test_docker_marked_item_fails_without_daemon_when_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(infra_helpers.STRICT_ENV, "1")
    monkeypatch.setattr(infra_helpers, "docker_daemon_reachable", lambda: (False, "daemon down"))
    with pytest.raises(pytest.fail.Exception) as excinfo:
        conftest.pytest_runtest_setup(_FakeItem(docker=True))  # type: ignore[arg-type]
    assert "docker daemon not reachable" in str(excinfo.value)


def test_docker_marked_item_runs_when_daemon_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(infra_helpers, "docker_daemon_reachable", lambda: (True, "27.0"))
    conftest.pytest_runtest_setup(_FakeItem(docker=True))  # type: ignore[arg-type]


def test_unmarked_item_never_probes_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> tuple[bool, str]:
        raise AssertionError("docker must not be probed for unmarked tests")

    monkeypatch.setattr(infra_helpers, "docker_daemon_reachable", _boom)
    conftest.pytest_runtest_setup(_FakeItem(docker=False))  # type: ignore[arg-type]


def test_docker_daemon_reachable_reports_missing_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    infra_helpers._reset_docker_cache()
    try:

        def _raise(*_a: object, **_k: object) -> object:
            raise FileNotFoundError("docker")

        monkeypatch.setattr(infra_helpers.subprocess, "run", _raise)
        ok, reason = infra_helpers.docker_daemon_reachable()
        assert ok is False
        assert reason
    finally:
        infra_helpers._reset_docker_cache()
