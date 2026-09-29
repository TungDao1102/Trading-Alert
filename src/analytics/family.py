"""Family-independence facts for the kill gate (Phase 10, plan 10-05, D-03, D013/D030).

"Independently specified" is decided by facts, never by a free-text flag: a family sheet
carrying the 7-slot template, a distinct sheet content hash, and registered parameter-set
hashes disjoint from every other accepted family. A family's TESTED_PASS / TESTED_FAIL
status is a recorded human decision input (decision_ref, decided-at, Development and
Validation experiment ids); nothing here derives a pass from data because numeric
acceptance thresholds remain TBD in the frozen protocol.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

REQUIRED_SLOTS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_BASELINE_PREFIXES = ("baseline-no-trade-", "baseline-simple-trend-")


class KillGateInputError(ValueError):
    """Malformed kill-gate evidence or evaluator input (fail closed, never repaired)."""


class FamilyStatus(str, Enum):
    """Recorded human decision status of one candidate family."""

    NOT_TESTED = "NOT_TESTED"
    TESTED_FAIL = "TESTED_FAIL"
    TESTED_PASS = "TESTED_PASS"


def _require_hex64(value: str, name: str) -> None:
    if not isinstance(value, str) or _HEX64.match(value) is None:
        raise KillGateInputError(f"{name} must be a 64-char lowercase hex digest")


def _require_utc(value: datetime | None, name: str) -> None:
    if value is None or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise KillGateInputError(f"{name} must be a UTC-aware datetime")


def _require_ids(values: Iterable[str], name: str) -> None:
    for value in values:
        if not isinstance(value, str) or value.strip() == "":
            raise KillGateInputError(f"{name} entries must be non-empty strings")


@dataclass(frozen=True)
class FamilyEvidence:
    """Facts about one candidate family, as recorded by humans and the registry."""

    family_id: str
    sheet_sha256: str | None
    sheet_slots_present: tuple[int, ...]
    candidate_param_set_hashes: tuple[str, ...]
    experiment_ids: tuple[str, ...]
    status: FamilyStatus
    decision_ref: str | None
    decided_at_utc: datetime | None
    development_experiment_ids: tuple[str, ...]
    validation_experiment_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.family_id, str) or self.family_id.strip() == "":
            raise KillGateInputError("family_id must be a non-empty string")
        if self.sheet_sha256 is not None:
            _require_hex64(self.sheet_sha256, "sheet_sha256")
        for param_hash in self.candidate_param_set_hashes:
            _require_hex64(param_hash, "candidate_param_set_hashes entry")
        _require_ids(self.experiment_ids, "experiment_ids")
        _require_ids(self.development_experiment_ids, "development_experiment_ids")
        _require_ids(self.validation_experiment_ids, "validation_experiment_ids")
        if self.status is FamilyStatus.NOT_TESTED:
            return
        # T-10-14: a TESTED_* status is only ever a recorded human decision.
        if self.decision_ref is None or self.decision_ref.strip() == "":
            raise KillGateInputError(f"{self.status.value} requires a non-empty decision_ref")
        _require_utc(self.decided_at_utc, "decided_at_utc")
        experiments = set(self.experiment_ids)
        for label, ids in (
            ("development_experiment_ids", self.development_experiment_ids),
            ("validation_experiment_ids", self.validation_experiment_ids),
        ):
            if not ids:
                raise KillGateInputError(f"{self.status.value} requires non-empty {label}")
            if not set(ids) <= experiments:
                raise KillGateInputError(f"{label} must be a subset of experiment_ids")


def is_baseline_parameter_set_id(parameter_set_id: str) -> bool:
    """True for baseline comparison ids (excluded from candidate-family counts).

    Only the two named baseline prefixes qualify: an id such as `baseline-v1` is a
    candidate despite starting with the word "baseline".
    """
    return parameter_set_id.startswith(_BASELINE_PREFIXES)


def independent_family_ids(
    families: Iterable[FamilyEvidence],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split family ids into (independent, non_independent), both sorted.

    Families are processed in family_id order. A family is independent iff it has a sheet
    hash, the complete 7-slot template, at least one candidate parameter-set hash, a sheet
    hash different from every already-accepted family, and parameter-set hashes disjoint
    from every already-accepted family.
    """
    ordered = sorted(families, key=lambda family: family.family_id)
    ids = [family.family_id for family in ordered]
    if len(set(ids)) != len(ids):
        raise KillGateInputError("family_id values must be unique")
    accepted_sheets: set[str] = set()
    accepted_params: set[str] = set()
    independent: list[str] = []
    non_independent: list[str] = []
    for family in ordered:
        params = set(family.candidate_param_set_hashes)
        ok = (
            family.sheet_sha256 is not None
            and tuple(sorted(family.sheet_slots_present)) == REQUIRED_SLOTS
            and len(params) >= 1
            and family.sheet_sha256 not in accepted_sheets
            and params.isdisjoint(accepted_params)
        )
        if ok and family.sheet_sha256 is not None:
            accepted_sheets.add(family.sheet_sha256)
            accepted_params |= params
            independent.append(family.family_id)
        else:
            non_independent.append(family.family_id)
    return tuple(independent), tuple(non_independent)
