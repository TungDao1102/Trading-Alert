"""Edge adapter: the verifiable code version of a run (Phase 14, plan 14-15, D-22, T-14-30).

`read_code_version(repo_root)` reads the git commit (`git rev-parse HEAD`) and the dirty flag
(`git status --porcelain` is non-empty) and returns the `CodeVersion` that
`src.backtest.experiment.assemble` binds into the experiment identity. It lives in the
adapters because the pure `src/backtest` package may not run subprocesses.

Both git calls use a list argv (the repo path is one argv element, never interpolated into
a string), `shell=False`, and a timeout. A missing git binary, a timeout, a non-zero exit
or a malformed commit is a `CodeVersionError`; git's stderr is never echoed.

No network, no exchange access, no database, no float.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.backtest.experiment import CodeVersion, IncompleteExperimentRecord

__all__ = ["CodeVersionError", "read_code_version"]

_GIT_TIMEOUT_SECONDS = 30


class CodeVersionError(Exception):
    """The git commit or dirty flag could not be read (fail closed, no stderr echoed)."""


def _git(repo_root: Path, *args: str) -> str:
    """Run one git command in `repo_root` and return its stdout (list argv, no shell)."""
    argv = ["git", "-C", str(repo_root), *args]
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
    except FileNotFoundError:
        raise CodeVersionError("git executable not found") from None
    except subprocess.TimeoutExpired:
        raise CodeVersionError(
            f"git {args[0]} timed out after {_GIT_TIMEOUT_SECONDS} seconds"
        ) from None
    except OSError as exc:
        raise CodeVersionError(
            f"git {args[0]} could not be started ({type(exc).__name__})"
        ) from None
    if completed.returncode != 0:
        raise CodeVersionError(f"git {args[0]} exited with code {completed.returncode}")
    return completed.stdout


def read_code_version(repo_root: Path) -> CodeVersion:
    """Return the commit of `HEAD` and whether the working tree differs from it.

    `dirty` is True when `git status --porcelain` prints anything (modified, staged or
    untracked files), so an experiment never claims a clean commit it did not run on.

    Raises:
        CodeVersionError: git is missing, times out, exits non-zero, or prints a commit that
            is not 40 lowercase hex characters.
    """
    commit = _git(repo_root, "rev-parse", "HEAD").strip()
    porcelain = _git(repo_root, "status", "--porcelain")
    try:
        return CodeVersion(commit=commit, dirty=porcelain.strip() != "")
    except IncompleteExperimentRecord:
        raise CodeVersionError(
            "git rev-parse HEAD did not print 40 lowercase hex characters"
        ) from None
