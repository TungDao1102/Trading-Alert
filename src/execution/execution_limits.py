"""The four Phase 19 execution limits and their fail-closed loader (plan 19-01; D-07, D-13).

No number lives in this module. The four safety numbers the owner has not chosen yet are
optional fields of a frozen dataclass that default to nothing: they reach the process only
through ``config/execution/execution-limits-v1.toml``, where each value is the word
``NOT_CONFIGURED`` until the owner sets it (OWNER-OPEN O-04). While any field is ``None`` the
live path refuses: ``ExecutionLimits.require_live_ready`` raises ``ExecutionLimitsNotConfigured``
naming the unset keys. ``tests/test_no_unratified_defaults.py`` scans ``src`` and ``scripts`` so
that no numeric default for these names ever appears.

The file is separate from ``config/binance/binance-limits-v1.toml``: that file is sha256-pinned
by a DECISIONS row and its loader demands exactly 27 keys, so it is not extended.

The file format (``config/execution/README.md``):

* exactly the sections ``protection``, ``pre_placement`` and ``provenance``;
* exactly the keys of ``EXECUTION_LIMIT_KEYS``; a missing or unknown key refuses to load;
* each value is a positive integer (not a boolean, not a float, not zero) or exactly the
  string ``NOT_CONFIGURED`` (read as ``None``);
* ``provenance.<section>.<key>`` gives every key a label: ``NOT_CONFIGURED`` for an unset value,
  one of STRUCTURAL, COST_GUARD, DECISION or EXPERIMENT for an integer. A PLACEHOLDER, unknown
  or absent label refuses to load: no placeholder number is a decision.

Every refusal raises ``ExecutionLimitsInvalid`` (``ExecutionLimitsFileMissing`` for a missing
file) with a message that names keys or sections only: never a value and never a path.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

NOT_CONFIGURED_WORD = "NOT_CONFIGURED"

EXECUTION_LIMIT_KEYS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "protection": ("max_unprotected_ms", "entry_terminal_timeout_ms"),
        "pre_placement": ("min_remaining_validity_seconds", "max_mark_price_age_ms"),
    }
)

PROVENANCE_SECTION = "provenance"
ALLOWED_SECTIONS: frozenset[str] = frozenset((*EXECUTION_LIMIT_KEYS, PROVENANCE_SECTION))
PROJECT_PROVENANCE_LABELS: frozenset[str] = frozenset(
    {"STRUCTURAL", "COST_GUARD", "DECISION", "EXPERIMENT"}
)
ALLOWED_PROVENANCE_LABELS: frozenset[str] = PROJECT_PROVENANCE_LABELS | {NOT_CONFIGURED_WORD}


# --------------------------------------------------------------------------- #
# Errors.
# --------------------------------------------------------------------------- #


class ExecutionLimitsInvalid(Exception):
    """The limits file is unreadable or malformed; the message names keys or sections only."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("execution limits invalid: " + "; ".join(self.problems))


class ExecutionLimitsFileMissing(ExecutionLimitsInvalid):
    """The execution-limits file does not exist."""


class ExecutionLimitsNotConfigured(Exception):
    """At least one limit is NOT_CONFIGURED; the live path must refuse (names keys only)."""

    def __init__(self, keys: tuple[str, ...]) -> None:
        self.keys = tuple(keys)
        super().__init__("execution limits not configured: " + ", ".join(self.keys))


# --------------------------------------------------------------------------- #
# The structure. Every field is required and keyword-only; none has a default.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class ExecutionLimits:
    """The four owner-chosen execution limits; ``None`` means NOT_CONFIGURED.

    ``max_unprotected_ms`` (D-13): the longest tolerated time an entry fill is open without a
    protective stop. ``entry_terminal_timeout_ms`` (D-13): how long the entry order may stay
    non-terminal. ``min_remaining_validity_seconds`` (D-07): the minimum remaining plan
    validity at placement. ``max_mark_price_age_ms`` (D-07): the maximum age of the mark
    price the price check uses.
    """

    max_unprotected_ms: int | None
    entry_terminal_timeout_ms: int | None
    min_remaining_validity_seconds: int | None
    max_mark_price_age_ms: int | None

    def unset_keys(self) -> tuple[str, ...]:
        """The dotted names of the keys still NOT_CONFIGURED, in the fixed file order."""
        return tuple(
            f"{section}.{key}"
            for section, keys in EXECUTION_LIMIT_KEYS.items()
            for key in keys
            if getattr(self, key) is None
        )

    def require_live_ready(self) -> None:
        """Refuse while any limit is unset.

        Raises:
            ExecutionLimitsNotConfigured: naming every unset key (never a value).
        """
        unset = self.unset_keys()
        if unset:
            raise ExecutionLimitsNotConfigured(unset)


# --------------------------------------------------------------------------- #
# The loader.
# --------------------------------------------------------------------------- #

_INVALID = object()


def _table(raw: Mapping[str, Any], name: str, problems: list[str]) -> Mapping[str, Any]:
    if name not in raw:
        return {}
    section = raw[name]
    if not isinstance(section, dict):
        problems.append(f"{name} (must be a table)")
        return {}
    return section


def _read_value(section: Mapping[str, Any], dotted: str, key: str, problems: list[str]) -> Any:
    """The validated int, None (NOT_CONFIGURED) or the _INVALID marker after a problem."""
    if key not in section:
        problems.append(f"{dotted} (missing key)")
        return _INVALID
    value = section[key]
    if isinstance(value, str):
        if value == NOT_CONFIGURED_WORD:
            return None
        problems.append(f"{dotted} (must be a positive integer or the word {NOT_CONFIGURED_WORD})")
        return _INVALID
    if isinstance(value, bool) or not isinstance(value, int):
        problems.append(f"{dotted} (must be an integer, not a boolean or a float)")
        return _INVALID
    if value <= 0:
        problems.append(f"{dotted} (must be a positive integer)")
        return _INVALID
    return value


def _check_label(dotted: str, value: object, label: object, problems: list[str]) -> None:
    if label == "PLACEHOLDER":
        problems.append(f"{dotted} (provenance PLACEHOLDER refuses to load)")
    elif not isinstance(label, str) or label not in ALLOWED_PROVENANCE_LABELS:
        problems.append(
            f"{dotted} (provenance label must be one of "
            + ", ".join(sorted(ALLOWED_PROVENANCE_LABELS))
            + ")"
        )
    elif value is _INVALID:
        return
    elif value is None and label != NOT_CONFIGURED_WORD:
        problems.append(f"{dotted} (an unset value needs provenance {NOT_CONFIGURED_WORD})")
    elif value is not None and label == NOT_CONFIGURED_WORD:
        problems.append(f"{dotted} (a set value cannot carry provenance {NOT_CONFIGURED_WORD})")


def _check_provenance(
    raw: Mapping[str, Any], values: Mapping[str, Mapping[str, object]], problems: list[str]
) -> None:
    if PROVENANCE_SECTION not in raw:
        problems.append(f"{PROVENANCE_SECTION} (missing table: every key needs a label)")
        return
    provenance = _table(raw, PROVENANCE_SECTION, problems)
    for section in sorted(set(provenance) - set(EXECUTION_LIMIT_KEYS)):
        problems.append(f"{PROVENANCE_SECTION}.{section} (unknown section)")
    for section, keys in EXECUTION_LIMIT_KEYS.items():
        labels = provenance.get(section, {})
        if not isinstance(labels, dict):
            problems.append(f"{PROVENANCE_SECTION}.{section} (must be a table)")
            labels = {}
        for key in sorted(set(labels) - set(keys)):
            problems.append(f"{PROVENANCE_SECTION}.{section}.{key} (unknown key)")
        for key in keys:
            dotted = f"{section}.{key}"
            if key not in labels:
                problems.append(f"{dotted} (missing provenance label)")
                continue
            _check_label(dotted, values[section][key], labels[key], problems)


def parse_execution_limits(raw: Mapping[str, Any]) -> ExecutionLimits:
    """Validate a parsed TOML document; every key is required and nothing else is allowed.

    Raises:
        ExecutionLimitsInvalid: naming every missing, unknown or invalid key or section.
    """
    problems: list[str] = []
    for section in sorted(set(raw) - ALLOWED_SECTIONS):
        problems.append(f"{section} (unknown section)")
    values: dict[str, dict[str, Any]] = {}
    for section, keys in EXECUTION_LIMIT_KEYS.items():
        body = _table(raw, section, problems)
        for key in sorted(set(body) - set(keys)):
            problems.append(f"{section}.{key} (unknown key)")
        values[section] = {
            key: _read_value(body, f"{section}.{key}", key, problems) for key in keys
        }
    _check_provenance(raw, values, problems)
    if problems:
        raise ExecutionLimitsInvalid(problems)

    flat: dict[str, Any] = {key: value for body in values.values() for key, value in body.items()}
    return ExecutionLimits(**flat)


def load_execution_limits(path: Path | str) -> ExecutionLimits:
    """Load the execution-limits file. There is no default file and no default value.

    Raises:
        ExecutionLimitsFileMissing: the file does not exist (the message carries no path).
        ExecutionLimitsInvalid: the file is not valid TOML or any entry is missing or invalid.
    """
    file = Path(path)
    if not file.is_file():
        raise ExecutionLimitsFileMissing(["the execution limits file does not exist"])
    try:
        raw = tomllib.loads(file.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError):
        raise ExecutionLimitsInvalid(["the execution limits file is not valid TOML"]) from None
    return parse_execution_limits(raw)


__all__ = [
    "ALLOWED_PROVENANCE_LABELS",
    "ALLOWED_SECTIONS",
    "EXECUTION_LIMIT_KEYS",
    "NOT_CONFIGURED_WORD",
    "PROJECT_PROVENANCE_LABELS",
    "ExecutionLimits",
    "ExecutionLimitsFileMissing",
    "ExecutionLimitsInvalid",
    "ExecutionLimitsNotConfigured",
    "load_execution_limits",
    "parse_execution_limits",
]
