"""Enforced kill-gate report guard and the shared review registry (Phase 16, plan 16-05).

D061 F (L-06, D-31): Phase 10 review items WR-01, WR-06, WR-12 and WR-13 are design defects of
the kill-gate code. Their fixes stay in Phase 26. Until they are resolved no kill-gate
conclusion may be shown or journaled on real evidence. WR-10 lives in the same registry with
scope `blocks_live_enable` only (REV-15, D065 item 1), so it cannot be forgotten and does not
widen the report guard.

Evidence is real unless it is explicitly marked fixture (REV-11, D063 item 9).

This module changes no WR design and never touches `killgate.evaluate`. Phase 26 flips an item
by setting its state to RESOLVED together with the fix commit; this phase never flips one.
The registry loader fails closed: any malformed, duplicated, unknown, scope-tampered or
incomplete registry raises `ReviewRegistryError` (a `ValueError`).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "NOT_CONCLUDED",
    "REGISTRY_SCHEMA",
    "RULE_REF",
    "EvidenceClass",
    "KillGateReportBlocked",
    "ReviewItem",
    "ReviewRegistryError",
    "live_enable_allowed",
    "load_review_registry",
    "not_concluded_line",
    "require_report_conclusion_allowed",
    "unresolved_live_enable_blockers",
    "unresolved_report_blockers",
]

REGISTRY_SCHEMA = "kill-gate-review-registry/1"
DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "research" / "kill_gate_review_registry.json"
)
RULE_REF = "D061 F"
NOT_CONCLUDED = "NOT CONCLUDED"

UNRESOLVED = "UNRESOLVED"
RESOLVED = "RESOLVED"
_STATES = frozenset({UNRESOLVED, RESOLVED})

# REV-15 classification table: id -> (blocks_report, blocks_live_enable). The loader refuses a
# registry whose scope fields differ, so a scope cannot be edited away to unblock a report.
_CANONICAL_SCOPES: dict[str, tuple[bool, bool]] = {
    "WR-01": (True, False),
    "WR-06": (True, False),
    "WR-10": (False, True),
    "WR-12": (True, False),
    "WR-13": (True, False),
}
_ITEM_KEYS = frozenset(
    {"id", "state", "blocks_report", "blocks_live_enable", "source", "fix_commit"}
)


class EvidenceClass(str, Enum):
    """Whether evidence is a fixture (explicitly marked) or real (the default-deny class)."""

    FIXTURE = "fixture"
    REAL = "real"


class ReviewRegistryError(ValueError):
    """The review registry is unreadable or violates its schema; the guard fails closed."""


class KillGateReportBlocked(Exception):
    """A kill-gate conclusion on real evidence is refused; carries the blocking item ids."""

    def __init__(self, blocking_ids: tuple[str, ...]) -> None:
        self.blocking_ids = blocking_ids
        super().__init__(
            f"kill-gate conclusion withheld: unresolved review items {', '.join(blocking_ids)} "
            f"({RULE_REF})"
        )


@dataclass(frozen=True)
class ReviewItem:
    """One registry row: a Phase 10 review item with its enforcement scope."""

    id: str
    state: str
    blocks_report: bool
    blocks_live_enable: bool
    source: str
    fix_commit: str | None

    @property
    def resolved(self) -> bool:
        return self.state == RESOLVED


def _parse_item(raw: object, index: int) -> ReviewItem:
    where = f"items[{index}]"
    if not isinstance(raw, dict):
        raise ReviewRegistryError(f"{where}: must be an object")
    keys = set(raw)
    if keys != _ITEM_KEYS:
        raise ReviewRegistryError(f"{where}: keys must be exactly {sorted(_ITEM_KEYS)}")
    item_id = raw["id"]
    state = raw["state"]
    blocks_report = raw["blocks_report"]
    blocks_live_enable = raw["blocks_live_enable"]
    source = raw["source"]
    fix_commit = raw["fix_commit"]
    if not isinstance(item_id, str) or item_id == "":
        raise ReviewRegistryError(f"{where}: id must be a non-empty string")
    if state not in _STATES:
        raise ReviewRegistryError(f"{where}: state must be UNRESOLVED or RESOLVED")
    if not isinstance(blocks_report, bool) or not isinstance(blocks_live_enable, bool):
        raise ReviewRegistryError(f"{where}: scope fields must be booleans")
    if not isinstance(source, str) or source == "":
        raise ReviewRegistryError(f"{where}: source must be a non-empty string")
    if fix_commit is not None and (not isinstance(fix_commit, str) or fix_commit.strip() == ""):
        raise ReviewRegistryError(f"{where}: fix_commit must be null or a non-empty string")
    if state == RESOLVED and fix_commit is None:
        raise ReviewRegistryError(f"{where}: a RESOLVED item requires a fix_commit")
    return ReviewItem(
        id=item_id,
        state=state,
        blocks_report=blocks_report,
        blocks_live_enable=blocks_live_enable,
        source=source,
        fix_commit=fix_commit,
    )


def load_review_registry(path: Path = DEFAULT_REGISTRY_PATH) -> tuple[ReviewItem, ...]:
    """Load and validate the review registry fail-closed; items are returned sorted by id."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReviewRegistryError(
            f"review registry could not be read ({type(exc).__name__})"
        ) from None
    if not isinstance(doc, dict) or doc.get("schema") != REGISTRY_SCHEMA:
        raise ReviewRegistryError(f"review registry schema must be {REGISTRY_SCHEMA!r}")
    raw_items = doc.get("items")
    if not isinstance(raw_items, list):
        raise ReviewRegistryError("review registry 'items' must be a list")
    items = tuple(_parse_item(raw, index) for index, raw in enumerate(raw_items))
    ids = [item.id for item in items]
    if len(set(ids)) != len(ids):
        raise ReviewRegistryError("review registry has a duplicate item id")
    missing = sorted(set(_CANONICAL_SCOPES) - set(ids))
    if missing:
        raise ReviewRegistryError(f"review registry is missing item(s) {', '.join(missing)}")
    for item in items:
        expected = _CANONICAL_SCOPES.get(item.id)
        if expected is not None and (item.blocks_report, item.blocks_live_enable) != expected:
            raise ReviewRegistryError(f"review registry scope of {item.id} differs from REV-15")
    return tuple(sorted(items, key=lambda item: item.id))


def _require_items(items: Iterable[ReviewItem]) -> tuple[ReviewItem, ...]:
    materialized = tuple(items)
    if not all(isinstance(item, ReviewItem) for item in materialized):
        raise TypeError("review registry items must be ReviewItem instances")
    return materialized


def unresolved_report_blockers(items: Iterable[ReviewItem]) -> tuple[str, ...]:
    """Sorted ids of UNRESOLVED items whose scope includes `blocks_report`."""
    return tuple(
        sorted(
            item.id for item in _require_items(items) if item.blocks_report and not item.resolved
        )
    )


def unresolved_live_enable_blockers(items: Iterable[ReviewItem]) -> tuple[str, ...]:
    """Sorted ids of UNRESOLVED items whose scope includes `blocks_live_enable`."""
    return tuple(
        sorted(
            item.id
            for item in _require_items(items)
            if item.blocks_live_enable and not item.resolved
        )
    )


def live_enable_allowed(items: Iterable[ReviewItem]) -> bool:
    """True only when every `blocks_live_enable` item is RESOLVED with a fix commit.

    This is the reader Phase 26 binds `LiveEnablementController.enable` to (ROADMAP Phase 26
    item [D065-WR], D065 item 1): `enable()` must call it and journal the registry state it
    used. The binding is not built here and `src/execution/enablement.py` is untouched; WR-10
    (`enable` trusts a caller-supplied kill-gate state) stays UNRESOLVED until that phase.
    """
    return not any(
        item.blocks_live_enable and not (item.resolved and item.fix_commit)
        for item in _require_items(items)
    )


def require_report_conclusion_allowed(
    items: Iterable[ReviewItem], evidence_class: EvidenceClass
) -> None:
    """Raise `KillGateReportBlocked` when real evidence meets an unresolved report blocker.

    Fixture evidence is always allowed (REV-11); anything not explicitly a fixture is real.
    Pure predicate, modelled on `killgate.registration_allowed`.
    """
    if not isinstance(evidence_class, EvidenceClass):
        raise TypeError("require_report_conclusion_allowed requires an EvidenceClass")
    blockers = unresolved_report_blockers(items)
    if evidence_class is EvidenceClass.FIXTURE:
        return
    if blockers:
        raise KillGateReportBlocked(blockers)


def not_concluded_line(blocking_ids: tuple[str, ...]) -> str:
    """The one-line text printed and rendered in place of a kill-gate verdict."""
    return f"{NOT_CONCLUDED} (blocked by {', '.join(blocking_ids)}; {RULE_REF})"
