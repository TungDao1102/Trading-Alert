"""Parameter rationale record (Phase 15, D-16, D-27).

A parameter set file may carry one in-file `[rationale.<key>]` table per
`[parameters]` key:

    [rationale.minimum_rr]
    basis = "DECISION"
    value = "2.0"
    text  = "why this value"
    ref   = "D046"

The tables are metadata. The registry hashes only strategy_id,
strategy_version, parameter_set_id and the normalized `[parameters]`, so adding
or editing rationale tables never changes `parameter_set_hash`.

`check_rationale` reports every problem in a file and never raises on a
malformed entry; `load_rationale` is the strict reader. Pure stdlib and
float-free (D-21).
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from . import registry

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
    """One validated `[rationale.<key>]` table."""

    key: str
    basis: str
    value: str
    text: str
    ref: str | None


def _read_doc(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_bytes().decode("utf-8"))


def _raw_tables(doc: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The raw top-level `rationale` table and any structural problem with it."""
    raw = doc.get("rationale", {})
    if not isinstance(raw, dict):
        return {}, ["rationale: must be a table of [rationale.<key>] tables"]
    return raw, []


def _parameters(path: Path) -> dict[str, Any]:
    """Normalized `[parameters]` through the registry's own parse path."""
    text = path.read_bytes().decode("utf-8")
    _version, params = registry._parse_and_validate(text, path, path.parent.name, path.stem)
    return params


def load_rationale(path: Path) -> dict[str, RationaleEntry]:
    """Strict reader of the `rationale` table; ValueError on a malformed entry."""
    raw, structural = _raw_tables(_read_doc(path))
    if structural:
        raise ValueError(f"{path}: {structural[0]}")
    entries: dict[str, RationaleEntry] = {}
    for key, table in raw.items():
        if not isinstance(table, dict):
            raise ValueError(f"{path}: rationale entry {key!r} must be a table")
        fields: dict[str, str] = {}
        for field in ("basis", "value", "text"):
            item = table.get(field)
            if not isinstance(item, str):
                raise ValueError(
                    f"{path}: rationale entry {key!r} field {field!r} must be a string"
                )
            fields[field] = item
        ref = table.get("ref")
        if ref is not None and not isinstance(ref, str):
            raise ValueError(f"{path}: rationale entry {key!r} field 'ref' must be a string")
        entries[key] = RationaleEntry(
            key=key,
            basis=fields["basis"],
            value=fields["value"],
            text=fields["text"],
            ref=ref,
        )
    return entries


_D_NUMBER = re.compile(r"D\d{3}")


def _value_problem(key: str, recorded: str, parameter: Any) -> str | None:
    """Problem when the recorded value differs from the parsed parameter, else None.

    String parameters compare exactly; int and Decimal parameters compare
    numerically through Decimal, so "1.0" matches a parameter normalized to int 1.
    """
    if isinstance(parameter, str):
        if recorded != parameter:
            return f"{key}: recorded value {recorded!r} differs from parameter {parameter!r}"
        return None
    try:
        recorded_number = Decimal(recorded)
        comparable = recorded_number.is_finite()
        equal = comparable and recorded_number == Decimal(str(parameter))
    except InvalidOperation:
        comparable = False
        equal = False
    if not comparable:
        return f"{key}: recorded value {recorded!r} is not a finite number"
    if not equal:
        return f"{key}: recorded value {recorded!r} differs from parameter {str(parameter)!r}"
    return None


def _entry_problems(key: str, table: Any, parameter: Any) -> list[str]:
    """Every problem of one `[rationale.<key>]` table; never raises."""
    if not isinstance(table, dict):
        return [f"{key}: rationale entry must be a table"]
    problems: list[str] = []
    basis = table.get("basis")
    value = table.get("value")
    text = table.get("text")
    ref = table.get("ref")
    if not isinstance(basis, str):
        problems.append(f"{key}: missing or non-string field 'basis'")
    elif basis not in RATIONALE_BASES:
        problems.append(f"{key}: unknown basis {basis!r}, expected one of {RATIONALE_BASES}")
    if not isinstance(value, str):
        problems.append(f"{key}: missing or non-string field 'value'")
    else:
        mismatch = _value_problem(key, value, parameter)
        if mismatch is not None:
            problems.append(mismatch)
    if not isinstance(text, str):
        problems.append(f"{key}: missing or non-string field 'text'")
    elif not text.strip():
        problems.append(f"{key}: field 'text' is empty")
    if ref is not None and not isinstance(ref, str):
        problems.append(f"{key}: field 'ref' must be a string")
    elif basis == "EXPERIMENT" and not (ref and ref.strip()):
        problems.append(
            f"{key}: basis EXPERIMENT requires a non-empty 'ref' (experiment reference)"
        )
    elif basis in ("DECISION", "COST_GUARD") and not (ref and _D_NUMBER.fullmatch(ref)):
        problems.append(
            f"{key}: basis {basis} requires a 'ref' of the form D<3 digits>, got {ref!r}"
        )
    return problems


def check_rationale(path: Path) -> list[str]:
    """All rationale problems of a set file, sorted; empty when complete."""
    params = _parameters(path)
    raw, problems = _raw_tables(_read_doc(path))
    for key, parameter in params.items():
        if key not in raw:
            problems.append(f"{key}: missing rationale entry")
        else:
            problems.extend(_entry_problems(key, raw[key], parameter))
    for key in raw:
        if key not in params:
            problems.append(f"{key}: rationale entry for a key that is not in [parameters]")
    return sorted(problems)


def placeholder_keys(path: Path) -> tuple[str, ...]:
    """Sorted keys whose rationale basis is PLACEHOLDER."""
    raw, _structural = _raw_tables(_read_doc(path))
    return tuple(
        sorted(
            key
            for key, table in raw.items()
            if isinstance(table, dict) and table.get("basis") == "PLACEHOLDER"
        )
    )
