"""Parameter rationale record (Phase 15, D-16, D-27).

RED skeleton: names and signatures of the interface contract only; the
validation rules land in the GREEN step.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

RATIONALE_BASES: tuple[str, ...] = (
    "STRUCTURAL",
    "COST_GUARD",
    "DECISION",
    "EXPERIMENT",
    "PLACEHOLDER",
)


class UnrationalizedParameterSet(Exception):
    """Raised when a set lacks a complete rationale or still carries PLACEHOLDER keys."""


@dataclass(frozen=True)
class RationaleEntry:
    key: str
    basis: str
    value: str
    text: str
    ref: str | None


def load_rationale(path: Path) -> dict[str, RationaleEntry]:
    return {}


def check_rationale(path: Path) -> list[str]:
    return []


def placeholder_keys(path: Path) -> tuple[str, ...]:
    return ()
