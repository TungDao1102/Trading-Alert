"""Plan 16-09 (L-01, D-21, D061 A, G2-009): the hourly freeze check reads the paper-start allowlist.

`python -m src.paper.freeze --check --from-allowlist` takes no strategy id and no parameter set id.
With the allowlist empty (the production state, checkpoint 15-17-01 Option B) it appends exactly
one SKIPPED line and exits 0; it never writes a clean line, never fails and never falls back to a
legacy set. Every line can carry the run metadata of the GitHub Actions run that wrote it, so the
reconciler of plan 16-15 can tell scheduled ticks from manual runs.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

RUN_ENV = {
    "GITHUB_RUN_ID": "1234567890",
    "GITHUB_RUN_ATTEMPT": "2",
    "GITHUB_EVENT_NAME": "schedule",
    "GITHUB_SHA": "f6fb5b18aae8a0ea35b2ccf3ed56306d907371d1",
    "PAPER_EVENT_SCHEDULE": "0 * * * *",
}
RUN_METADATA = {
    "run_id": "1234567890",
    "run_attempt": "2",
    "event_name": "schedule",
    "schedule": "0 * * * *",
    "commit": "f6fb5b18aae8a0ea35b2ccf3ed56306d907371d1",
}


@pytest.fixture(autouse=True)
def _no_ambient_run_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CI runner sets GITHUB_*; no test may depend on the ambient environment."""
    for name in RUN_ENV:
        monkeypatch.delenv(name, raising=False)


def _lines(path: Path) -> list[dict[str, Any]]:
    assert path.is_file(), f"no diff log at {path}"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --------------------------------------------------------------------------- #
# Task 1 (tracer): empty allowlist -> one SKIPPED line, exit 0, through the real CLI entry.
# --------------------------------------------------------------------------- #


def test_empty_allowlist_appends_one_skipped_line_and_exits_zero(tmp_path: Path) -> None:
    from src.paper.freeze import PAPER_START_ALLOWLIST, _cli_main

    assert PAPER_START_ALLOWLIST == ()
    diff_log = tmp_path / "registry_diff.jsonl"

    code = _cli_main(
        [
            "--check",
            "--from-allowlist",
            "--diff-log",
            str(diff_log),
            "--pinned-state",
            str(tmp_path / "pinned_epoch.json"),
        ]
    )

    assert code == 0
    lines = _lines(diff_log)
    assert len(lines) == 1
    assert lines[0]["outcome"] == "SKIPPED"
    assert lines[0]["reason"] == "allowlist empty"
    assert datetime.fromisoformat(lines[0]["checked_at_utc"]).utcoffset() is not None
    assert "clean" not in diff_log.read_text(encoding="utf-8")
    assert not (tmp_path / "pinned_epoch.json").exists(), "SKIPPED must not pin or write state"


def test_two_empty_ticks_append_two_skipped_lines(tmp_path: Path) -> None:
    from src.paper.freeze import _cli_main

    diff_log = tmp_path / "registry_diff.jsonl"
    argv = ["--check", "--from-allowlist", "--diff-log", str(diff_log)]
    assert _cli_main(argv) == 0
    assert _cli_main(argv) == 0
    assert [line["outcome"] for line in _lines(diff_log)] == ["SKIPPED", "SKIPPED"]


def test_skipped_entry_renders_canonical_json_and_validates() -> None:
    from src.paper.freeze import FreezeSkippedEntry

    when = datetime(2026, 10, 9, 5, 0, tzinfo=UTC)
    entry = FreezeSkippedEntry(checked_at_utc=when, reason="allowlist empty")
    assert entry.outcome == "SKIPPED"
    assert entry.to_jsonl() == json.dumps(
        {
            "checked_at_utc": "2026-10-09T05:00:00+00:00",
            "outcome": "SKIPPED",
            "reason": "allowlist empty",
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    with_meta = FreezeSkippedEntry(
        checked_at_utc=when, reason="allowlist empty", run_metadata=RUN_METADATA
    )
    assert json.loads(with_meta.to_jsonl())["run_metadata"] == RUN_METADATA

    with pytest.raises(ValueError, match="UTC-aware"):
        FreezeSkippedEntry(checked_at_utc=datetime(2026, 10, 9, 5, 0), reason="allowlist empty")
    with pytest.raises(ValueError, match="reason"):
        FreezeSkippedEntry(checked_at_utc=when, reason=" ")


@pytest.mark.parametrize(
    "extra",
    [
        ["--strategy-id", "trend-pullback"],
        ["--parameter-set-id", "baseline-v3"],
        ["--strategy-id", "trend-pullback", "--parameter-set-id", "baseline-v3"],
    ],
)
def test_from_allowlist_forbids_explicit_ids(tmp_path: Path, extra: list[str]) -> None:
    from src.paper.freeze import _cli_main

    diff_log = tmp_path / "registry_diff.jsonl"
    with pytest.raises(SystemExit) as excinfo:
        _cli_main(["--check", "--from-allowlist", "--diff-log", str(diff_log), *extra])
    assert excinfo.value.code == 2
    assert not diff_log.exists(), "a usage error must write no line"


@pytest.mark.parametrize(
    "ids",
    [
        [],
        ["--strategy-id", "trend-pullback"],
        ["--parameter-set-id", "baseline-v3"],
    ],
)
def test_without_from_allowlist_both_ids_are_still_required(tmp_path: Path, ids: list[str]) -> None:
    from src.paper.freeze import _cli_main

    with pytest.raises(SystemExit) as excinfo:
        _cli_main(["--check", "--diff-log", str(tmp_path / "registry_diff.jsonl"), *ids])
    assert excinfo.value.code == 2


def test_skipped_line_carries_run_metadata_from_the_five_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.paper.freeze import _cli_main

    for name, value in RUN_ENV.items():
        monkeypatch.setenv(name, value)
    diff_log = tmp_path / "registry_diff.jsonl"

    assert _cli_main(["--check", "--from-allowlist", "--diff-log", str(diff_log)]) == 0

    assert _lines(diff_log)[0]["run_metadata"] == RUN_METADATA


def test_skipped_line_has_no_run_metadata_key_without_the_variables(tmp_path: Path) -> None:
    from src.paper.freeze import _cli_main

    diff_log = tmp_path / "registry_diff.jsonl"
    assert _cli_main(["--check", "--from-allowlist", "--diff-log", str(diff_log)]) == 0
    assert "run_metadata" not in _lines(diff_log)[0]


def test_a_manual_dispatch_is_recorded_with_an_empty_schedule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """github.event.schedule is empty on workflow_dispatch; the line must say so, not omit it."""
    from src.paper.freeze import _cli_main

    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("PAPER_EVENT_SCHEDULE", "")
    diff_log = tmp_path / "registry_diff.jsonl"

    assert _cli_main(["--check", "--from-allowlist", "--diff-log", str(diff_log)]) == 0

    assert _lines(diff_log)[0]["run_metadata"] == {
        "event_name": "workflow_dispatch",
        "schedule": "",
    }
