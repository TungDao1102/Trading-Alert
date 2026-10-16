"""Plan 16-09 (L-01, D-21, D061 A, G2-009): the hourly freeze check reads the paper-start allowlist.

`python -m src.paper.freeze --check --from-allowlist` takes no strategy id and no parameter set id.
With the allowlist empty (the production state, checkpoint 15-17-01 Option B) it appends exactly
one SKIPPED line and exits 0; it never writes a clean line, never fails and never falls back to a
legacy set. Every line can carry the run metadata of the GitHub Actions run that wrote it, so the
reconciler of plan 16-15 can tell scheduled ticks from manual runs.
"""

from __future__ import annotations

import dataclasses
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

# The one cron line the freeze workflow is expected to carry: the line recorded in
# decisions/16-DEC-Q-Q.md (hourly at minute 34, the user's checkpoint Q-Q of plan 16-30; before
# plan 16-47 it was `0 * * * *`, the line on master). It must stay of the hourly form
# `M * * * *` (M from 0 to 59), the only form the reconciler of plan 16-15 accepts. Moving the
# cron does not relax the rule that a missing tick is an EVIDENCE_GAP.
EXPECTED_FREEZE_CRON = "34 * * * *"
HOURLY_CRON_RE = re.compile(r"^([0-9]|[1-5][0-9]) \* \* \* \*$")
ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "paper_freeze_check.yml"
REPO_PARAMS = ROOT / "params"
STRATEGY_ID = "trend-pullback"
PARAMETER_SET_ID = "baseline-v3"

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


def test_empty_allowlist_appends_one_skipped_line_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.paper.freeze import _cli_main, allowlist_entries

    _inject(monkeypatch)
    assert allowlist_entries() == ()
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


def test_two_empty_ticks_append_two_skipped_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.paper.freeze import _cli_main

    _inject(monkeypatch)
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


# --------------------------------------------------------------------------- #
# Task 2: the non-empty allowlist path, run metadata on every line, the workflow.
# --------------------------------------------------------------------------- #


def _registry_copy(tmp_path: Path) -> Path:
    root = tmp_path / "params"
    shutil.copytree(REPO_PARAMS, root)
    return root


def _set_hash(registry_root: Path) -> str:
    from src.paper.freeze import _recompute_parameter_set_hash

    return _recompute_parameter_set_hash(
        strategy_id=STRATEGY_ID, parameter_set_id=PARAMETER_SET_ID, registry_root=registry_root
    )


def _entry(parameter_set_hash: str, *, parameter_set_id: str = PARAMETER_SET_ID) -> Any:
    from src.paper.freeze import PaperAllowlistEntry

    return PaperAllowlistEntry(
        strategy_id=STRATEGY_ID,
        parameter_set_id=parameter_set_id,
        parameter_set_hash=parameter_set_hash,
        purpose="test-only entry",
        approved_at="2026-10-09",
        basis="tests/test_paper_freeze_allowlist_mode.py (injected, never production)",
    )


def _inject(monkeypatch: pytest.MonkeyPatch, *entries: Any) -> None:
    import src.paper.freeze as freeze

    monkeypatch.setattr(freeze, "PAPER_START_ALLOWLIST", tuple(entries))


@pytest.fixture(autouse=True)
def _start_from_an_empty_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests exercise the allowlist mode on an empty list unless a test injects entries.

    The production allowlist holds the user's single entry since checkpoint G4-021 (the pin test
    lives in tests/test_paper_start_gate.py), so every test here starts from an injected empty one.
    """
    _inject(monkeypatch)


def _pin(tmp_path: Path, registry_root: Path, *, state_set_id: str = PARAMETER_SET_ID) -> Path:
    """Write a pinned-state file for the registry's current state; return its path.

    `state_set_id` rewrites the parameter set id recorded in the state (the hash stays the one
    of baseline-v3), to build a state that belongs to another set than the allowlist entry.
    """
    from src.paper.freeze import pin_stream_epoch, write_pinned_state

    epoch = pin_stream_epoch(
        strategy_id=STRATEGY_ID,
        parameter_set_id=PARAMETER_SET_ID,
        opened_at_utc=datetime(2026, 10, 9, 0, 0, tzinfo=UTC),
        registry_root=registry_root,
        allow_unrationalized=True,
    )
    epoch = dataclasses.replace(epoch, parameter_set_id=state_set_id)
    path = tmp_path / "pinned_epoch.json"
    write_pinned_state(epoch, path)
    return path


def _argv(tmp_path: Path, registry_root: Path, pinned: Path) -> list[str]:
    return [
        "--check",
        "--from-allowlist",
        "--diff-log",
        str(tmp_path / "registry_diff.jsonl"),
        "--pinned-state",
        str(pinned),
        "--registry-root",
        str(registry_root),
    ]


def _mutate_set(registry_root: Path) -> None:
    target = registry_root / STRATEGY_ID / f"{PARAMETER_SET_ID}.toml"
    text = target.read_text(encoding="utf-8")
    assert "fee_rate_entry = 0.0002" in text
    target.write_text(
        text.replace("fee_rate_entry = 0.0002", "fee_rate_entry = 0.0003", 1), encoding="utf-8"
    )


def test_one_entry_clean_tick_exits_zero_and_checks_exactly_that_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.paper.freeze import _cli_main

    root = _registry_copy(tmp_path)
    _inject(monkeypatch, _entry(_set_hash(root)))
    pinned = _pin(tmp_path, root)

    assert _cli_main(_argv(tmp_path, root, pinned)) == 0

    lines = _lines(tmp_path / "registry_diff.jsonl")
    assert [line["outcome"] for line in lines] == ["clean"]
    assert lines[0]["pinned_hash"] == lines[0]["current_hash"] == _set_hash(root)


def test_one_entry_registry_change_is_a_rollover_exit_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.paper.freeze import _cli_main, load_pinned_state

    root = _registry_copy(tmp_path)
    approved = _set_hash(root)
    _inject(monkeypatch, _entry(approved))
    pinned = _pin(tmp_path, root)
    _mutate_set(root)

    code = _cli_main(_argv(tmp_path, root, pinned))

    assert code == 3
    lines = _lines(tmp_path / "registry_diff.jsonl")
    assert [line["outcome"] for line in lines] == ["REGISTRY_DIFF"]
    assert load_pinned_state(pinned).parameter_set_hash != approved


def test_one_entry_missing_pinned_state_exits_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.paper.freeze import _cli_main

    root = _registry_copy(tmp_path)
    _inject(monkeypatch, _entry(_set_hash(root)))

    code = _cli_main(_argv(tmp_path, root, tmp_path / "absent.json"))

    assert code == 2
    assert not (tmp_path / "registry_diff.jsonl").exists()


def test_one_entry_with_other_ids_than_the_pinned_state_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.paper.freeze import _cli_main

    root = _registry_copy(tmp_path)
    _inject(monkeypatch, _entry(_set_hash(root)))
    pinned = _pin(tmp_path, root, state_set_id="baseline-v2")

    assert _cli_main(_argv(tmp_path, root, pinned)) == 1
    assert not (tmp_path / "registry_diff.jsonl").exists()


def test_pinned_hash_must_equal_the_entry_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pinned state for the same ids but another hash than the user approved is refused."""
    from src.paper.freeze import _cli_main

    root = _registry_copy(tmp_path)
    _inject(monkeypatch, _entry("1" * 64))
    pinned = _pin(tmp_path, root)

    assert _cli_main(_argv(tmp_path, root, pinned)) == 1
    assert not (tmp_path / "registry_diff.jsonl").exists(), "no clean line for an unapproved hash"


def test_two_entries_are_ambiguous_exit_one_and_nothing_is_guessed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.paper.freeze import _cli_main
    from structlog.testing import capture_logs

    root = _registry_copy(tmp_path)
    _inject(
        monkeypatch,
        _entry(_set_hash(root)),
        _entry("2" * 64, parameter_set_id="baseline-v2"),
    )
    pinned = _pin(tmp_path, root)

    with capture_logs() as logs:
        code = _cli_main(_argv(tmp_path, root, pinned))

    assert code == 1
    assert any("ambiguous allowlist" in str(event.get("reason", "")) for event in logs)
    assert not (tmp_path / "registry_diff.jsonl").exists()


def test_find_allowlist_entry_is_exact_and_refuses_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.paper.freeze import allowlist_entries, find_allowlist_entry

    _inject(monkeypatch)
    assert allowlist_entries() == ()
    assert find_allowlist_entry(STRATEGY_ID, PARAMETER_SET_ID) is None

    first = _entry("a" * 64)
    _inject(monkeypatch, first)
    assert allowlist_entries() == (first,)
    assert find_allowlist_entry(STRATEGY_ID, PARAMETER_SET_ID) is first
    assert find_allowlist_entry(STRATEGY_ID, "baseline-v2") is None
    assert find_allowlist_entry("range-mr", PARAMETER_SET_ID) is None

    _inject(monkeypatch, first, _entry("b" * 64))
    with pytest.raises(ValueError, match="ambiguous allowlist"):
        find_allowlist_entry(STRATEGY_ID, PARAMETER_SET_ID)


def test_clean_and_rollover_lines_carry_run_metadata_when_the_variables_are_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.paper.freeze import _cli_main

    root = _registry_copy(tmp_path)
    _inject(monkeypatch, _entry(_set_hash(root)))
    pinned = _pin(tmp_path, root)
    for name, value in RUN_ENV.items():
        monkeypatch.setenv(name, value)

    assert _cli_main(_argv(tmp_path, root, pinned)) == 0
    _mutate_set(root)
    assert _cli_main(_argv(tmp_path, root, pinned)) == 3

    clean, rollover = _lines(tmp_path / "registry_diff.jsonl")
    assert clean["outcome"] == "clean"
    assert rollover["outcome"] == "REGISTRY_DIFF"
    assert clean["run_metadata"] == RUN_METADATA
    assert rollover["run_metadata"] == RUN_METADATA


def test_explicit_id_mode_also_stamps_run_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.paper.freeze import _cli_main

    root = _registry_copy(tmp_path)
    pinned = _pin(tmp_path, root)
    for name, value in RUN_ENV.items():
        monkeypatch.setenv(name, value)

    code = _cli_main(
        [
            "--check",
            "--strategy-id",
            STRATEGY_ID,
            "--parameter-set-id",
            PARAMETER_SET_ID,
            "--diff-log",
            str(tmp_path / "registry_diff.jsonl"),
            "--pinned-state",
            str(pinned),
            "--registry-root",
            str(root),
        ]
    )

    assert code == 0
    assert _lines(tmp_path / "registry_diff.jsonl")[0]["run_metadata"] == RUN_METADATA


def test_lines_without_run_metadata_are_byte_identical_to_the_pinned_shape() -> None:
    """DiffLogEntry renders exactly the pre-16-09 bytes when no metadata is attached."""
    from src.paper.freeze import DiffLogEntry

    entry = DiffLogEntry(
        checked_at_utc=datetime(2026, 10, 9, 5, 0, tzinfo=UTC),
        epoch_id="e" * 64,
        pinned_hash="a" * 64,
        current_hash="a" * 64,
        outcome="clean",
    )
    expected = (
        '{"checked_at_utc":"2026-10-09T05:00:00+00:00",'
        '"current_hash":"' + "a" * 64 + '","epoch_id":"' + "e" * 64 + '",'
        '"outcome":"clean","pinned_hash":"' + "a" * 64 + '"}'
    )
    assert entry.to_jsonl() == expected
    with_meta = DiffLogEntry(
        checked_at_utc=entry.checked_at_utc,
        epoch_id=entry.epoch_id,
        pinned_hash=entry.pinned_hash,
        current_hash=entry.current_hash,
        outcome="clean",
        run_metadata=RUN_METADATA,
    )
    assert json.loads(with_meta.to_jsonl())["run_metadata"] == RUN_METADATA
    with pytest.raises(ValueError, match="run_metadata"):
        DiffLogEntry(
            checked_at_utc=entry.checked_at_utc,
            epoch_id=entry.epoch_id,
            pinned_hash=entry.pinned_hash,
            current_hash=entry.current_hash,
            outcome="clean",
            run_metadata={"unknown": "x"},
        )


def test_run_metadata_reads_only_the_five_named_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.paper.freeze import read_run_metadata

    assert read_run_metadata({}) is None
    assert read_run_metadata({"GITHUB_TOKEN": "secret", "PATH": "/bin"}) is None
    mixed = {**RUN_ENV, "GITHUB_TOKEN": "secret", "GITHUB_REPOSITORY": "a/b"}
    assert read_run_metadata(mixed) == RUN_METADATA
    monkeypatch.setenv("GITHUB_RUN_ID", "77")
    assert read_run_metadata() == {"run_id": "77"}


# ----- the workflow text -----------------------------------------------------------------


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8").replace("\r\n", "\n")


CRON_ITEM_RE = re.compile(r"^\s*-\s+cron:\s*[\"']?([^\"'#]*?)[\"']?\s*(?:#.*)?$")


def _cron_lines(text: str) -> list[str]:
    """The `- cron:` list items of the schedule (comment lines are ignored)."""
    found: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = CRON_ITEM_RE.match(line)
        if match is not None:
            found.append(match.group(1).strip())
    return found


def _check_freeze_cron(text: str) -> None:
    crons = _cron_lines(text)
    assert len(crons) == 1, f"expected exactly one cron entry, got {crons}"
    assert crons[0] == EXPECTED_FREEZE_CRON, f"cron {crons[0]!r} != {EXPECTED_FREEZE_CRON!r}"


def test_expected_cron_is_of_the_hourly_form_the_reconciler_accepts() -> None:
    assert HOURLY_CRON_RE.match(EXPECTED_FREEZE_CRON) is not None
    for bad in ("*/5 * * * *", "0 */2 * * *", "60 * * * *", "0 * * * 1", "0 0 * * *"):
        assert HOURLY_CRON_RE.match(bad) is None, bad


def test_workflow_has_exactly_the_expected_cron_line() -> None:
    _check_freeze_cron(_workflow_text())


def test_cron_check_fails_on_a_changed_a_second_or_a_missing_cron() -> None:
    """Negative control: the checker is not vacuous."""
    text = _workflow_text()
    changed = text.replace(f'"{EXPECTED_FREEZE_CRON}"', '"17 * * * *"', 1)
    assert changed != text
    with pytest.raises(AssertionError, match="cron"):
        _check_freeze_cron(changed)
    doubled = text.replace(
        f'    - cron: "{EXPECTED_FREEZE_CRON}"\n',
        f'    - cron: "{EXPECTED_FREEZE_CRON}"\n    - cron: "30 * * * *"\n',
        1,
    )
    assert doubled != text
    with pytest.raises(AssertionError, match="exactly one"):
        _check_freeze_cron(doubled)
    commented_only = re.sub(r"^(\s*)- cron:", r"\1# - cron:", text, flags=re.MULTILINE)
    assert commented_only != text
    with pytest.raises(AssertionError, match="exactly one"):
        _check_freeze_cron(commented_only)


def test_workflow_reads_the_allowlist_and_hard_codes_no_set() -> None:
    text = _workflow_text()
    assert "--from-allowlist" in text
    assert "--strategy-id" not in text
    assert "--parameter-set-id" not in text
    assert "trend-pullback" not in text
    assert "baseline-v3" not in text


def test_workflow_stamps_the_schedule_and_keeps_its_hardening() -> None:
    from tests.test_deploy_workflows import PINNED_USES_RE, USES_RE

    text = _workflow_text()
    assert "PAPER_EVENT_SCHEDULE: ${{ github.event.schedule }}" in text
    assert re.search(r"^permissions:\s*\n  contents: read\s*$", text, re.MULTILINE)
    assert "persist-credentials: false" in text
    uses = [m.group(0) for m in USES_RE.finditer(text)]
    pinned = [m.group(0) for m in PINNED_USES_RE.finditer(text)]
    assert uses and uses == pinned, "every action must be pinned to a commit SHA"


def test_workflow_header_says_what_the_check_does_not_prove() -> None:
    header = _workflow_text().split("name: Paper Freeze Check")[0].lower()
    assert "registry immutability" in header
    assert "never" in header and "host" in header
    assert "cache" in header and "not evidence" in header
