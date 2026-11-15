"""Tests for the verifiable code version adapter (Phase 14, plan 14-15, D-22, T-14-30).

`read_code_version(repo_root)` reads the git commit and the dirty flag with list argv, no
shell and a timeout (it lives in `src/adapters` because `src/backtest` may not run
subprocesses). Unit tests monkeypatch `subprocess.run`; one test reads the real repository,
read-only.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from typing import Any

import pytest
from src.adapters import code_version as adapter
from src.adapters.code_version import (
    BuildRevisionError,
    CodeVersionError,
    read_build_revision,
    read_code_version,
)
from src.backtest.experiment import CodeVersion

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMIT = "0123456789abcdef0123456789abcdef01234567"


class _Git:
    """A scripted stand-in for `subprocess.run` that records every call."""

    def __init__(self, *, commit: str = COMMIT + "\n", porcelain: str = "", returncode: int = 0):
        self.commit = commit
        self.porcelain = porcelain
        self.returncode = returncode
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), kwargs))
        out = self.commit if "rev-parse" in argv else self.porcelain
        return subprocess.CompletedProcess(argv, self.returncode, stdout=out, stderr="boom")


def _patch(monkeypatch: pytest.MonkeyPatch, fake: Any) -> None:
    monkeypatch.setattr(adapter.subprocess, "run", fake)


def test_a_clean_tree_reads_the_commit_and_dirty_false(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _Git()
    _patch(monkeypatch, fake)
    assert read_code_version(REPO_ROOT) == CodeVersion(commit=COMMIT, dirty=False)


def test_a_non_empty_porcelain_status_is_dirty(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _Git(porcelain=" M src/backtest/experiment.py\n?? scratch.txt\n"))
    version = read_code_version(REPO_ROOT)
    assert version.dirty is True
    assert version.text == f"{COMMIT}-dirty"


def test_git_is_called_with_list_argv_no_shell_and_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _Git()
    _patch(monkeypatch, fake)
    read_code_version(REPO_ROOT)
    assert len(fake.calls) == 2
    for argv, kwargs in fake.calls:
        assert isinstance(argv, list) and argv[0] == "git"
        assert all(isinstance(part, str) for part in argv)
        assert not kwargs.get("shell", False)
        assert isinstance(kwargs.get("timeout"), int)
        assert kwargs["timeout"] > 0
        assert str(REPO_ROOT) in argv
    assert any("rev-parse" in argv and "HEAD" in argv for argv, _ in fake.calls)
    assert any("status" in argv and "--porcelain" in argv for argv, _ in fake.calls)


def test_a_missing_git_binary_is_a_project_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(argv: list[str], **kwargs: Any) -> Any:
        raise FileNotFoundError("git")

    _patch(monkeypatch, missing)
    with pytest.raises(CodeVersionError, match="git"):
        read_code_version(REPO_ROOT)


def test_a_git_timeout_is_a_project_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(argv: list[str], **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    _patch(monkeypatch, slow)
    with pytest.raises(CodeVersionError, match="timed out"):
        read_code_version(REPO_ROOT)


def test_a_non_zero_git_exit_is_a_project_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _Git(returncode=128))
    with pytest.raises(CodeVersionError, match="128"):
        read_code_version(REPO_ROOT)


def test_git_stderr_is_never_echoed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _Git(returncode=128))
    with pytest.raises(CodeVersionError) as info:
        read_code_version(REPO_ROOT)
    assert "boom" not in str(info.value)


@pytest.mark.parametrize("commit", ["", "abc\n", "g" * 40 + "\n", "A" * 40 + "\n", "a" * 41 + "\n"])
def test_a_commit_that_is_not_40_lowercase_hex_is_a_project_error(
    monkeypatch: pytest.MonkeyPatch, commit: str
) -> None:
    _patch(monkeypatch, _Git(commit=commit))
    with pytest.raises(CodeVersionError, match="40"):
        read_code_version(REPO_ROOT)


def test_the_real_repository_is_read_without_changing_it() -> None:
    head = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout.strip()
    status_before = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout
    version = read_code_version(REPO_ROOT)
    assert version.commit == head
    assert len(version.commit) == 40
    assert version.dirty is (status_before.strip() != "")
    assert version.text == (f"{head}-dirty" if version.dirty else head)


def test_the_adapter_never_uses_a_shell() -> None:
    """AST guard (T-14-30): every `*.run(...)` call in the adapter keeps shell falsy."""
    tree = ast.parse((REPO_ROOT / "src" / "adapters" / "code_version.py").read_text("utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "run"
    ]
    assert calls, "the adapter must call subprocess.run"
    for call in calls:
        keywords = {kw.arg: kw.value for kw in call.keywords}
        assert "timeout" in keywords
        shell = keywords.get("shell")
        assert shell is None or (isinstance(shell, ast.Constant) and shell.value is False)
        assert isinstance(call.args[0], (ast.List, ast.Name))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "os" not in imported  # no os.system / os.popen route


# --- the build stamp (plan 24-11, OPS-04, D-31): validation only, no subprocess ---------------


def test_the_build_revision_is_the_stamp_when_it_is_forty_lowercase_hex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _Git()
    _patch(monkeypatch, fake)
    assert read_build_revision({"TRADING_APP_REVISION": COMMIT}) == COMMIT
    assert fake.calls == []  # a stamp never starts a subprocess


def test_an_absent_build_stamp_is_none_and_starts_no_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _Git()
    _patch(monkeypatch, fake)
    assert read_build_revision({}) is None
    assert fake.calls == []


@pytest.mark.parametrize(
    "bad",
    ["", COMMIT.upper(), COMMIT[:-1], COMMIT + "0", f" {COMMIT}", f"{COMMIT}\n", "g" * 40],
)
def test_a_malformed_build_stamp_raises_without_echoing_the_value(bad: str) -> None:
    with pytest.raises(BuildRevisionError) as caught:
        read_build_revision({"TRADING_APP_REVISION": bad})
    assert "TRADING_APP_REVISION" in str(caught.value)
    if bad:
        assert bad not in str(caught.value)
