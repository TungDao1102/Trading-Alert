"""Per-family acceptance-gate cells (Phase 10, plan 10-07, D-03, RESEARCH P3).

Cells use only MET / NOT_MET / PENDING_THRESHOLD_TBD / NOT_EVALUATED. Numeric acceptance
thresholds remain TBD in the frozen protocol, so judgement gates (G04, G05, G06, G09) are
always PENDING_THRESHOLD_TBD, and G01 / G02 (deterministic rules, no look-ahead) have no
machine derivation here and stay NOT_EVALUATED. Only gates whose evidence is a recorded
fact (cost-model hash, reproducibility verdict, uncertainty report, baseline comparison)
can be MET. No cell is ever a pass by inference. Pure: stdlib + in-repo only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.analytics.family import KillGateInputError
from src.domain.canonical import sha256_hex

__all__ = [
    "GATE_IDS",
    "GATE_LABELS",
    "FamilyGateFacts",
    "GateCell",
    "derive_gate_cells",
    "gate_cells_digest",
]

GATE_IDS: tuple[str, ...] = tuple(f"G{number:02d}" for number in range(1, 11))

GATE_LABELS: dict[str, str] = {
    "G01": "Deterministic rules",
    "G02": "No material look-ahead",
    "G03": "Costs modeled",
    "G04": "Not single-symbol/session",
    "G05": "OOS consistent",
    "G06": "Tolerable drawdown",
    "G07": "Reproducible",
    "G08": "Interval uncertainty",
    "G09": "No single-point dependence",
    "G10": "Baseline-compared",
}


class GateCell(str, Enum):
    """Closed cell vocabulary for the K-2b gate matrix."""

    MET = "MET"
    NOT_MET = "NOT_MET"
    PENDING_THRESHOLD_TBD = "PENDING_THRESHOLD_TBD"
    NOT_EVALUATED = "NOT_EVALUATED"


@dataclass(frozen=True)
class FamilyGateFacts:
    """Recorded facts about one family that machine-derivable gates may read."""

    cost_model_hash_present: bool
    reproducibility_verified: bool | None
    uncertainty_report_present: bool
    baseline_compared: bool
    tested: bool

    def __post_init__(self) -> None:
        for name in (
            "cost_model_hash_present",
            "uncertainty_report_present",
            "baseline_compared",
            "tested",
        ):
            if not isinstance(getattr(self, name), bool):
                raise KillGateInputError(f"{name} must be a bool")
        if self.reproducibility_verified is not None and not isinstance(
            self.reproducibility_verified, bool
        ):
            raise KillGateInputError("reproducibility_verified must be a bool or None")


def _evidence_cell(present: bool, tested: bool) -> GateCell:
    if present:
        return GateCell.MET
    return GateCell.NOT_MET if tested else GateCell.NOT_EVALUATED


def derive_gate_cells(facts: FamilyGateFacts) -> tuple[tuple[str, GateCell], ...]:
    """Ten (gate id, cell) pairs in G01..G10 order; never a pass by inference."""
    reproducible = facts.reproducibility_verified
    cells: dict[str, GateCell] = {
        "G01": GateCell.NOT_EVALUATED,
        "G02": GateCell.NOT_EVALUATED,
        "G03": _evidence_cell(facts.cost_model_hash_present, facts.tested),
        "G04": GateCell.PENDING_THRESHOLD_TBD,
        "G05": GateCell.PENDING_THRESHOLD_TBD,
        "G06": GateCell.PENDING_THRESHOLD_TBD,
        "G07": _evidence_cell(reproducible is True, facts.tested and reproducible is False),
        "G08": _evidence_cell(facts.uncertainty_report_present, facts.tested),
        "G09": GateCell.PENDING_THRESHOLD_TBD,
        "G10": _evidence_cell(facts.baseline_compared, facts.tested),
    }
    return tuple((gate_id, cells[gate_id]) for gate_id in GATE_IDS)


def gate_cells_digest(cells: tuple[tuple[str, GateCell], ...]) -> str:
    """SHA-256 over the (gate id, cell value) pairs (byte-stable)."""
    return sha256_hex({"cells": [[gate_id, cell.value] for gate_id, cell in cells]})
