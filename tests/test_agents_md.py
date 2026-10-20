"""AGENTS.md stays a short router for AI agents (owner decision 2026-10-20).

The file lists rules, commands and where to read; the long maps live in ``.planning/codebase/``.
These checks keep it from growing back into a copy of those maps and keep its paths true.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS = REPO_ROOT / "AGENTS.md"

MAX_LINES = 230
PATH_ROOTS = ("src/", "docs/", ".planning/", "scripts/", "deploy/", "tests/", "config/", "params/")
PATH_RE = re.compile(r"`((?:" + "|".join(re.escape(r) for r in PATH_ROOTS) + r")[^`\s]*)`")


def _text() -> str:
    return AGENTS.read_text(encoding="utf-8")


def test_agents_md_stays_a_short_router() -> None:
    lines = _text().splitlines()
    assert len(lines) <= MAX_LINES, (
        f"AGENTS.md has {len(lines)} lines (cap {MAX_LINES}); put the detail in "
        ".planning/codebase/ or docs/ and link to it"
    )


def test_agents_md_has_no_generated_gsd_blocks() -> None:
    assert "<!-- GSD:" not in _text(), "do not run generate-claude-md on AGENTS.md"


def test_every_path_named_in_agents_md_exists() -> None:
    missing = []
    for raw in sorted(set(PATH_RE.findall(_text()))):
        if any(mark in raw for mark in ("*", "<", "phaseN")):
            continue
        path = raw.split("::", 1)[0].rstrip("/.,;:")
        if not (REPO_ROOT / path).exists():
            missing.append(raw)
    assert not missing, f"AGENTS.md names paths that do not exist: {missing}"
