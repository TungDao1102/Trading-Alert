"""Plan 16-47 (Q-F, Q-Q, D-21, D-22, L-01, REV-18, G15): how the hourly freeze check gets its pin.

The user decided, and recorded in `decisions/`, how the scheduled workflow on `master` obtains the
pinned epoch (Q-F: `commit-pinned-state`, the file the user commits to `master`) and the cron
minute it runs at (Q-Q). These tests read the records and hold the workflow text to them:

- the workflow copies the committed pin into the path the freeze CLI reads, before the check, with
  no secret, no credential and the read-only token it already had;
- the one `- cron:` entry equals the recorded line, and the reconciler's slot grid follows it;
- the recorded O-01 and Q-F decisions are mutually compatible.

Nothing here touches the network; the copy step is run as a shell script against a temp tree.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.infra_helpers import find_bash, infra_skip
from tests.test_paper_freeze_allowlist_mode import (
    EXPECTED_FREEZE_CRON,
    _cron_lines,
    _workflow_text,
)

ROOT = Path(__file__).resolve().parent.parent
DECISIONS = ROOT / ".planning" / "phases" / "16-paper-runtime-composition" / "decisions"

# The one place the user commits the pinned epoch to (Q-F). RUNBOOK 20.7 names the same path.
COMMITTED_PIN_PATH = "evidence/paper/pinned_epoch.json"
PIN_STEP_NAME = "Use the committed pinned epoch"


def record(name: str) -> dict[str, str]:
    """The `key: value` lines of a decision record (first occurrence wins)."""
    values: dict[str, str] = {}
    for line in (DECISIONS / name).read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([a-z_ ]+): (.*)$", line)
        if match and match.group(1) not in values:
            values[match.group(1)] = match.group(2).strip()
    return values


def assert_records_compatible(o01: Mapping[str, str], q_f: Mapping[str, str]) -> None:
    """A workflow that reads the evidence off-host cannot be paired with evidence stored
    through the backup crypt remote: it would be ciphertext without the passphrases (S2)."""
    assert q_f.get("option") in {"commit-pinned-state", "read-from-durable-store"}, "Q-F option"
    assert o01.get("through_crypt_remote") in {"yes", "no", "not applicable"}, "O-01 crypt line"
    assert o01.get("write_timing", "").split(",")[0] in {"daily-snapshot", "exporter-schedule"}
    if q_f["option"] == "read-from-durable-store":
        assert o01["through_crypt_remote"] != "yes", (
            "Q-F read-from-durable-store with O-01 through_crypt_remote: yes is incompatible"
        )


def _step_block(text: str, name: str) -> str:
    """The lines of the workflow step called `name` (up to the next `- name:` item)."""
    lines = text.split("\n")
    start = next((i for i, line in enumerate(lines) if line.strip() == f"- name: {name}"), None)
    assert start is not None, f"workflow has no step named {name!r}"
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("      - name:"):
            end = i
            break
    return "\n".join(lines[start:end])


def _step_script(text: str, name: str) -> str:
    block = _step_block(text, name).split("\n")
    run = next(i for i, line in enumerate(block) if line.strip() == "run: |")
    return "\n".join(line[10:] for line in block[run + 1 :])


# ----- Q-F: the pin comes from a commit ---------------------------------------------------


def test_the_recorded_q_f_option_is_the_one_this_plan_implements() -> None:
    q_f = record("16-DEC-Q-F.md")
    assert q_f["option"] == "commit-pinned-state", (
        "only the recorded option is implemented; another option needs a new plan"
    )
    assert q_f["decided by"] == "user"


def test_the_workflow_copies_the_committed_pin_between_the_cache_restore_and_the_check() -> None:
    text = _workflow_text()
    order = [
        text.index("- name: Checkout"),
        text.index("- name: Restore freeze state"),
        text.index(f"- name: {PIN_STEP_NAME}"),
        text.index("- name: Run freeze check"),
    ]
    assert order == sorted(order), "checkout, cache restore, committed pin, then the check"
    block = _step_block(text, PIN_STEP_NAME)
    assert COMMITTED_PIN_PATH in block
    assert "PAPER_PINNED_STATE: ${{ github.workspace }}/logs/paper/pinned_epoch.json" in block
    check = _step_block(text, "Run freeze check")
    assert '--pinned-state "$PAPER_PINNED_STATE"' in check
    assert "--from-allowlist" in check


def test_the_committed_pin_step_uses_no_secret_and_keeps_the_read_only_scope() -> None:
    text = _workflow_text()
    code = "\n".join(line for line in text.split("\n") if not line.lstrip().startswith("#"))
    assert "secrets." not in code, "commit-pinned-state needs no credential on GitHub"
    assert "GITHUB_TOKEN" not in code
    assert re.search(r"^permissions:\s*\n  contents: read\s*$", text, re.MULTILINE)
    assert "persist-credentials: false" in text
    block = _step_block(text, PIN_STEP_NAME)
    assert "cat " not in block, "the step never prints the pinned state"


def _run_pin_step(tmp_path: Path, *, committed: str | None, cached: str | None) -> Path:
    bash = find_bash()
    if bash is None:
        infra_skip("no bash to run the workflow step")
    workspace = tmp_path / "ws"
    state = workspace / "logs" / "paper" / "pinned_epoch.json"
    if committed is not None:
        pin = workspace / COMMITTED_PIN_PATH
        pin.parent.mkdir(parents=True)
        pin.write_text(committed, encoding="utf-8")
    if cached is not None:
        state.parent.mkdir(parents=True)
        state.write_text(cached, encoding="utf-8")
    script = _step_script(_workflow_text(), PIN_STEP_NAME)
    env = {
        **os.environ,
        "COMMITTED_PIN": (workspace / COMMITTED_PIN_PATH).as_posix(),
        "PAPER_PINNED_STATE": state.as_posix(),
    }
    done = subprocess.run(
        [bash, "-ec", script], env=env, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
    return state


def test_the_step_replaces_a_cached_pin_with_the_committed_one(tmp_path: Path) -> None:
    state = _run_pin_step(tmp_path, committed='{"epoch": "committed"}', cached='{"epoch": "stale"}')
    assert state.read_text(encoding="utf-8") == '{"epoch": "committed"}'


def test_the_step_copies_the_committed_pin_when_the_cache_is_empty(tmp_path: Path) -> None:
    state = _run_pin_step(tmp_path, committed='{"epoch": "committed"}', cached=None)
    assert state.read_text(encoding="utf-8") == '{"epoch": "committed"}'


def test_without_a_committed_pin_no_cached_pin_survives(tmp_path: Path) -> None:
    """The cache is operational state, not evidence (L-01): an absent commit means no pin."""
    state = _run_pin_step(tmp_path, committed=None, cached='{"epoch": "stale"}')
    assert not state.exists()


# ----- 16-59 Q2 (B2-WR-05): two ticks never run at once --------------------------------------

CONCURRENCY_BLOCK = (
    "concurrency:\n  group: paper-freeze-check\n  cancel-in-progress: false\n  queue: max\n"
)


def test_the_workflow_serialises_its_runs_and_queues_up_to_the_maximum() -> None:
    """The owner's decision (16-DEC-FREEZE-LOG-ASSEMBLY, correction 3 and the queue amendment):
    one run at a time, a pending run is not cancelled by a newer one when `queue: max` allows
    it, and the combination with `cancel-in-progress: true` (a validation error) never appears."""
    text = _workflow_text()
    code = "\n".join(line for line in text.split("\n") if not line.lstrip().startswith("#"))
    assert ("\n" + CONCURRENCY_BLOCK) in ("\n" + code), "a top-level concurrency block"
    assert code.count("concurrency:") == 1
    assert "cancel-in-progress: true" not in code
    assert code.index("concurrency:") > code.index("permissions:"), "after the permissions block"
    assert code.index("concurrency:") < code.index("jobs:")


def test_the_serialising_block_changes_nothing_else_in_the_workflow() -> None:
    text = _workflow_text()
    assert len(_cron_lines(text)) == 1
    assert re.search(r"^permissions:\s*\n  contents: read\s*$", text, re.MULTILINE)
    assert "key: paper-freeze-state" in text and "key: paper-freeze-${{ github.run_id }}" in text
    assert "name: registry-diff-${{ github.run_id }}" in text
    assert "if: always()" in _step_block(text, "Upload diff log")


# ----- Q-Q: the recorded cron line ------------------------------------------------------------


def _recorded_cron() -> str:
    q_q = record("16-DEC-Q-Q.md")
    assert q_q["decided by"] == "user"
    return q_q["cron"]


def test_the_recorded_cron_is_of_the_form_the_decision_allows() -> None:
    q_q = record("16-DEC-Q-Q.md")
    cron = q_q["cron"]
    if q_q["option"] == "keep-top-of-hour":
        assert cron == "0 * * * *"
    else:
        assert q_q["option"] == "off-hour-minute"
        match = re.fullmatch(r"([1-9]|[1-5][0-9]) \* \* \* \*", cron)
        assert match is not None, cron


def _assert_workflow_cron(text: str, recorded: str) -> None:
    crons = _cron_lines(text)
    assert len(crons) == 1, f"expected exactly one cron entry, got {crons}"
    assert crons[0] == recorded, f"cron {crons[0]!r} != recorded {recorded!r}"


def test_the_workflow_cron_equals_the_recorded_line_character_for_character() -> None:
    _assert_workflow_cron(_workflow_text(), _recorded_cron())


def test_the_expected_cron_constant_is_the_recorded_line() -> None:
    assert EXPECTED_FREEZE_CRON == _recorded_cron()


def test_the_reconciler_slot_grid_follows_the_recorded_minute() -> None:
    from src.paper.coverage import expected_slots

    cron = _recorded_cron()
    minute = int(cron.split(" ")[0])
    pin = datetime(2026, 11, 1, 3, 10, tzinfo=UTC)
    slots = expected_slots(pin, datetime(2026, 11, 1, 8, 0, tzinfo=UTC), cron)
    assert slots, "the grid is not empty"
    assert {s.minute for s in slots} == {minute}
    assert all(s > pin for s in slots)


def test_a_workflow_with_any_other_cron_fails_the_check() -> None:
    """Negative control on a test copy: the checker is not vacuous."""
    recorded = _recorded_cron()
    text = _workflow_text()
    other = "17 * * * *" if recorded != "17 * * * *" else "18 * * * *"
    changed = text.replace(f'"{recorded}"', f'"{other}"', 1)
    assert changed != text
    with pytest.raises(AssertionError, match="cron"):
        _assert_workflow_cron(changed, recorded)


# ----- the records agree with each other ---------------------------------------------------------


def test_the_recorded_o_01_and_q_f_decisions_are_compatible() -> None:
    assert_records_compatible(record("16-DEC-O-01.md"), record("16-DEC-Q-F.md"))


def test_a_seeded_incompatible_pair_fails_the_same_check() -> None:
    o01 = {**record("16-DEC-O-01.md"), "through_crypt_remote": "yes"}
    q_f = {**record("16-DEC-Q-F.md"), "option": "read-from-durable-store"}
    with pytest.raises(AssertionError, match="incompatible"):
        assert_records_compatible(o01, q_f)
    # commit-pinned-state does not read the store, so a crypt remote does not conflict with it.
    assert_records_compatible(o01, {**q_f, "option": "commit-pinned-state"})
