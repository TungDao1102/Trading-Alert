"""Scope of each Phase 10 review item in the shared registry (Phase 16, plan 16-05, REV-15).

The committed registry must classify WR-01, WR-06, WR-12 and WR-13 as report blockers and WR-10
as a live-enable blocker only, so the report guard is not widened and Phase 26 cannot forget
the enablement binding (D065 item 1).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from src.analytics.killgate_guard import (
    DEFAULT_REGISTRY_PATH,
    EvidenceClass,
    KillGateReportBlocked,
    live_enable_allowed,
    load_review_registry,
    require_report_conclusion_allowed,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMITTED = REPO_ROOT / "docs" / "research" / "kill_gate_review_registry.json"

# REV-15 classification table: id -> (blocks_report, blocks_live_enable).
SCOPE_TABLE = {
    "WR-01": (True, False),
    "WR-06": (True, False),
    "WR-10": (False, True),
    "WR-12": (True, False),
    "WR-13": (True, False),
}


def _registry_file(tmp_path: Path, *, resolved: tuple[str, ...]) -> Path:
    items: list[dict[str, Any]] = []
    for item_id, (report, live) in SCOPE_TABLE.items():
        done = item_id in resolved
        items.append(
            {
                "id": item_id,
                "state": "RESOLVED" if done else "UNRESOLVED",
                "blocks_report": report,
                "blocks_live_enable": live,
                "source": "test",
                "fix_commit": "abc1234" if done else None,
            }
        )
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps({"schema": "kill-gate-review-registry/1", "items": items}), encoding="utf-8"
    )
    return path


@pytest.mark.parametrize(("item_id", "scope"), sorted(SCOPE_TABLE.items()))
def test_committed_scope_equals_the_rev15_table(item_id: str, scope: tuple[bool, bool]) -> None:
    by_id = {item.id: item for item in load_review_registry(COMMITTED)}
    item = by_id[item_id]
    assert (item.blocks_report, item.blocks_live_enable) == scope


def test_committed_registry_has_exactly_the_five_items() -> None:
    raw = json.loads(COMMITTED.read_text(encoding="utf-8"))
    assert sorted(entry["id"] for entry in raw["items"]) == sorted(SCOPE_TABLE)


def test_live_enable_is_refused_while_wr10_is_unresolved(tmp_path: Path) -> None:
    assert live_enable_allowed(load_review_registry(COMMITTED)) is False
    only_report_items_done = _registry_file(tmp_path, resolved=("WR-01", "WR-06", "WR-12", "WR-13"))
    assert live_enable_allowed(load_review_registry(only_report_items_done)) is False


def test_live_enable_is_allowed_only_when_wr10_is_resolved_with_a_fix_commit(
    tmp_path: Path,
) -> None:
    resolved = _registry_file(tmp_path, resolved=("WR-10",))
    assert live_enable_allowed(load_review_registry(resolved)) is True


def test_a_report_with_only_wr10_unresolved_is_not_blocked(tmp_path: Path) -> None:
    items = load_review_registry(
        _registry_file(tmp_path, resolved=("WR-01", "WR-06", "WR-12", "WR-13"))
    )
    require_report_conclusion_allowed(items, EvidenceClass.REAL)


def test_resolving_wr10_alone_does_not_unblock_the_report(tmp_path: Path) -> None:
    items = load_review_registry(_registry_file(tmp_path, resolved=("WR-10",)))
    with pytest.raises(KillGateReportBlocked):
        require_report_conclusion_allowed(items, EvidenceClass.REAL)


def test_default_registry_path_stays_inside_docs_research() -> None:
    assert DEFAULT_REGISTRY_PATH.parent == REPO_ROOT / "docs" / "research"
    assert DEFAULT_REGISTRY_PATH.name == "kill_gate_review_registry.json"
