"""Negative tests for the version-bound research-gate freeze step (Phase 11, plan 11-01, D-02).

The freeze step of ``.github/workflows/research-gate.yml`` is executed for real (under
bash) against temporary copies of the three freeze witnesses: the protocol header, the
DECISIONS freeze row and the DOC_STATUS index line. Every missing or mismatched witness
must exit non-zero, including the half-frozen case (header bumped, only the older row).

Synthetic triplets prove the step derives the version from the header; the real-file
tests prove the repository itself is frozen consistently.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "research-gate.yml"
REAL_PROTOCOL = REPO_ROOT / "docs" / "research" / "RESEARCH_PROTOCOL.md"
REAL_DECISIONS = REPO_ROOT / "docs" / "DECISIONS.md"
REAL_DOC_STATUS = REPO_ROOT / "docs" / "DOC_STATUS.md"


def _find_bash() -> str | None:
    found = shutil.which("bash")
    if found and not (sys.platform == "win32" and "system32" in found.lower()):
        return found
    if sys.platform == "win32":
        program_files = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        candidate = program_files / "Git" / "bin" / "bash.exe"
        if candidate.is_file():
            return str(candidate)
    return None


BASH = _find_bash()
if BASH is None:
    pytest.skip("bash is required to run the research-gate freeze step", allow_module_level=True)


def _freeze_script() -> str:
    """Return the ``run`` block of the ``Freeze check`` step (LF-normalised, dedented)."""
    text = WORKFLOW.read_text(encoding="utf-8").replace("\r\n", "\n")
    lines = text.split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.strip().startswith("- name: Freeze check"))
    run_at = next(i for i in range(start, len(lines)) if lines[i].strip() == "run: |")
    body: list[str] = []
    for ln in lines[run_at + 1 :]:
        if re.match(r"^      - name:", ln):
            break
        body.append(ln)
    script = textwrap.dedent("\n".join(body)).strip("\n")
    assert script, "Freeze check run block is empty"
    return script + "\n"


def _run(
    tmp_path: Path, protocol: str, decisions: str, doc_status: str
) -> subprocess.CompletedProcess[str]:
    for rel, content in (
        ("docs/research/RESEARCH_PROTOCOL.md", protocol),
        ("docs/DECISIONS.md", decisions),
        ("docs/DOC_STATUS.md", doc_status),
    ):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
    assert BASH is not None
    # The script goes through a file: passing it via `bash -c` would let Windows
    # command-line quoting rewrite the backslashes the version escaping depends on.
    script_path = tmp_path / "_freeze_step.sh"
    with script_path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(_freeze_script())
    return subprocess.run(
        [BASH, script_path.name],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _protocol(
    version: str = "1.1.0",
    status: str = "FROZEN",
    frozen_on: str | None = "2026-09-19",
    with_version: bool = True,
) -> str:
    lines = ["# Research Protocol (Frozen)", ""]
    if with_version:
        lines.append(f"> **Protocol version:** v{version}")
    lines.append(f"> **Status:** {status}")
    if frozen_on is not None:
        lines.append(f"> **Frozen on:** {frozen_on}")
    lines.append("> **Amended on:** 2026-09-30")
    lines.append("> **Supersedes:** v1.0.1")
    lines.append("")
    lines.append("## Section 0")
    return "\n".join(lines) + "\n"


def _decisions(versions: list[str]) -> str:
    rows = [
        "| ID | Decision | Status |",
        "|---|---|---|",
    ]
    for i, v in enumerate(versions, start=29):
        rows.append(f"| D0{i} | Research protocol {v} frozen | Accepted |")
    return "\n".join(rows) + "\n"


def _doc_status(version: str, tag: str = "") -> str:
    suffix = f" {tag}" if tag else ""
    return (
        "# Doc status\n\n## Stable / canonical\n\n"
        "- `research/RESEARCH_PROTOCOL.md` - Frozen on 2026-09-19 "
        f"(v{version}; D029, D030){suffix}\n"
    )


def _combined(version: str = "1.1.0") -> tuple[str, str, str]:
    return _protocol(version), _decisions([f"v{version}"]), _doc_status(version)


def _assert_fails(result: subprocess.CompletedProcess[str], *mentions: str) -> None:
    assert result.returncode != 0, result.stdout + result.stderr
    for mention in mentions:
        assert mention in result.stdout, f"{mention!r} not in stdout: {result.stdout!r}"


def test_intact_v110_triplet_passes(tmp_path: Path) -> None:
    result = _run(tmp_path, *_combined("1.1.0"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Freeze check passed" in result.stdout


def test_version_is_read_from_header_not_hard_coded(tmp_path: Path) -> None:
    result = _run(tmp_path, *_combined("1.2.0"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Freeze check passed" in result.stdout


def test_half_frozen_header_bumped_with_only_d029_row_fails(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _protocol("1.1.0"),
        _decisions(["v1.0.0"]),
        _doc_status("1.1.0"),
    )
    _assert_fails(result, "DECISIONS")


def test_half_frozen_same_triplet_with_v110_row_passes(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _protocol("1.1.0"),
        _decisions(["v1.0.0", "v1.1.0"]),
        _doc_status("1.1.0"),
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_dots_in_version_are_escaped(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _protocol("1.1.0"),
        _decisions(["v1x1x0"]),
        _doc_status("1.1.0"),
    )
    _assert_fails(result, "DECISIONS")


def test_header_status_draft_fails(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _protocol("1.1.0", status="DRAFT"),
        _decisions(["v1.1.0"]),
        _doc_status("1.1.0"),
    )
    _assert_fails(result, "header")


def test_header_without_frozen_on_date_fails(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _protocol("1.1.0", frozen_on=None),
        _decisions(["v1.1.0"]),
        _doc_status("1.1.0"),
    )
    _assert_fails(result, "header")


def test_header_without_protocol_version_line_fails(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _protocol("1.1.0", with_version=False),
        _decisions(["v1.1.0"]),
        _doc_status("1.1.0"),
    )
    _assert_fails(result, "header")


def test_doc_status_without_protocol_entry_fails(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _protocol("1.1.0"),
        _decisions(["v1.1.0"]),
        "# Doc status\n\n## Stable / canonical\n\n- `GLOSSARY.md`\n",
    )
    _assert_fails(result, "DOC_STATUS")


def test_doc_status_pending_freeze_tag_fails(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _protocol("1.1.0"),
        _decisions(["v1.1.0"]),
        _doc_status("1.1.0", tag="pending-freeze"),
    )
    _assert_fails(result, "DOC_STATUS")


def test_doc_status_at_old_version_while_header_is_v110_fails(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _protocol("1.1.0"),
        _decisions(["v1.1.0"]),
        _doc_status("1.0.1"),
    )
    _assert_fails(result, "DOC_STATUS")


def _real() -> tuple[str, str, str]:
    return (
        REAL_PROTOCOL.read_text(encoding="utf-8"),
        REAL_DECISIONS.read_text(encoding="utf-8"),
        REAL_DOC_STATUS.read_text(encoding="utf-8"),
    )


def test_real_triplet_passes(tmp_path: Path) -> None:
    result = _run(tmp_path, *_real())
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Freeze check passed" in result.stdout


def test_real_decisions_without_d043_row_fails(tmp_path: Path) -> None:
    protocol, decisions, doc_status = _real()
    kept = [ln for ln in decisions.splitlines() if not ln.startswith("| D043 |")]
    assert len(kept) == len(decisions.splitlines()) - 1
    result = _run(tmp_path, protocol, "\n".join(kept) + "\n", doc_status)
    _assert_fails(result, "DECISIONS")


def test_real_doc_status_reverted_to_old_version_fails(tmp_path: Path) -> None:
    protocol, decisions, doc_status = _real()
    out: list[str] = []
    changed = 0
    for ln in doc_status.splitlines():
        if ln.startswith("- `research/RESEARCH_PROTOCOL.md`"):
            ln = ln.replace("v1.1.0", "v1.0.1")
            changed += 1
        out.append(ln)
    assert changed == 1
    result = _run(tmp_path, protocol, decisions, "\n".join(out) + "\n")
    _assert_fails(result, "DOC_STATUS")


def test_real_protocol_without_version_header_fails(tmp_path: Path) -> None:
    protocol, decisions, doc_status = _real()
    kept = [ln for ln in protocol.splitlines() if not ln.startswith("> **Protocol version:**")]
    assert len(kept) == len(protocol.splitlines()) - 1
    result = _run(tmp_path, "\n".join(kept) + "\n", decisions, doc_status)
    _assert_fails(result, "header")
