"""Holm step-down over the 48 confirmatory hypotheses (protocol v2.3.0, decision D069).

One Holm-Bonferroni procedure at family-wise alpha = 0.05 runs over ONE set of 48 candidate-level
one-sided p-values: 16 per family, three families, the set fixed by the three registered grid files
(`docs/research/preregistration/research-run-1-grid-*.json`). It is never reset per family and never
extended by a re-run, a sensitivity scenario or a later look: scenario results (the S1 constraint
stress test included) never enter the correction. The set always holds all 48 p-values, including
candidates that fail G1; a candidate with no closed Validation trade is entered by the caller with
p = 1 (conservative, still counted in m). A candidate passes G3 only when its adjusted p-value is
strictly below 0.05 (`g3_passes`). G2 stays a separate, uncorrected conjunct and is not
computed here.

Scope: this module corrects p-values it is given. The seeded one-sided stationary block-bootstrap
p-value producer on pooled Validation trades does not exist yet; it is a later plan. Nothing here
claims that multiplicity is resolved end to end.

A hypothesis id is `"<strategy_id>/<parameter_set_id>"`, unique across the three families.
Statistical code that never gates an order: plain `float` is allowed here.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path

from .manifest import ManifestError, load_grid

FAMILY_WISE_ALPHA = 0.05
EXPECTED_HYPOTHESES = 48
_EXPECTED_GRID_FILES = 3
_PER_FAMILY = 16
_GRID_GLOB = "research-run-1-grid-*.json"
_DEFAULT_GRID_DIR = Path(__file__).resolve().parents[2] / "docs" / "research" / "preregistration"


class MultiplicityError(ManifestError):
    """The hypothesis set or a p-value is not what the registered correction accepts."""


def confirmatory_hypothesis_ids(directory: Path | None = None) -> tuple[str, ...]:
    """The 48 registered hypothesis ids, sorted; refuses any other grid layout (fail closed)."""
    root = _DEFAULT_GRID_DIR if directory is None else directory
    files = sorted(root.glob(_GRID_GLOB))
    if len(files) != _EXPECTED_GRID_FILES:
        raise MultiplicityError(
            f"expected exactly {_EXPECTED_GRID_FILES} registered grid files, found {len(files)}"
        )
    ids: list[str] = []
    strategies: set[str] = set()
    for path in files:
        grid = load_grid(path)
        if grid.strategy_id in strategies:
            raise MultiplicityError("two grid files share one strategy_id")
        strategies.add(grid.strategy_id)
        if len(grid.points) != _PER_FAMILY:
            raise MultiplicityError(
                f"grid {grid.strategy_id} holds {len(grid.points)} points, expected {_PER_FAMILY}"
            )
        ids.extend(f"{grid.strategy_id}/{point.parameter_set_id}" for point in grid.points)
    if len(ids) != EXPECTED_HYPOTHESES or len(set(ids)) != EXPECTED_HYPOTHESES:
        raise MultiplicityError(
            f"the registered grids must give {EXPECTED_HYPOTHESES} distinct hypothesis ids"
        )
    return tuple(sorted(ids))


def _validated(p_by_id: Mapping[str, object]) -> dict[str, float]:
    if not p_by_id:
        raise MultiplicityError("an empty hypothesis set cannot be corrected")
    clean: dict[str, float] = {}
    for raw_id, raw_p in p_by_id.items():
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise MultiplicityError("a hypothesis id must be a non-empty string")
        hypothesis_id = raw_id.strip()
        if hypothesis_id in clean:
            raise MultiplicityError("duplicate hypothesis id after normalization")
        if isinstance(raw_p, bool) or not isinstance(raw_p, float):
            raise MultiplicityError("a p-value must be a float")
        if math.isnan(raw_p) or not 0.0 <= raw_p <= 1.0:
            raise MultiplicityError("a p-value must lie in [0, 1]")
        clean[hypothesis_id] = raw_p
    return clean


def holm_adjust(p_by_id: Mapping[str, float]) -> dict[str, float]:
    """Holm step-down adjusted p-values over exactly the given hypotheses (m = their count).

    Sorted by (p, id); adjusted_j = min(1, max over i <= j of (m - i) * p_i), i from 0. The
    result is keyed in sorted-id order, so it does not depend on the input order; equal
    p-values receive equal adjusted values.
    """
    clean = _validated(p_by_id)
    m = len(clean)
    ordered = sorted(clean, key=lambda hypothesis_id: (clean[hypothesis_id], hypothesis_id))
    adjusted: dict[str, float] = {}
    running = 0.0
    for index, hypothesis_id in enumerate(ordered):
        running = max(running, (m - index) * clean[hypothesis_id])
        adjusted[hypothesis_id] = min(1.0, running)
    return {hypothesis_id: adjusted[hypothesis_id] for hypothesis_id in sorted(adjusted)}


def holm_adjust_confirmatory(p_by_id: Mapping[str, float]) -> dict[str, float]:
    """Holm over exactly the 48 registered hypotheses; refuses a missing, extra or unknown id."""
    clean = _validated(p_by_id)
    expected = set(confirmatory_hypothesis_ids())
    if set(clean) != expected:
        missing = len(expected - set(clean))
        unknown = len(set(clean) - expected)
        raise MultiplicityError(
            f"the p-value set must be exactly the {EXPECTED_HYPOTHESES} registered hypotheses "
            f"({missing} missing, {unknown} unknown)"
        )
    return holm_adjust(clean)


def g3_passes(adjusted_p: float) -> bool:
    """G3: true only when the Holm-adjusted p-value is strictly below the family-wise alpha."""
    if isinstance(adjusted_p, bool) or not isinstance(adjusted_p, float):
        raise MultiplicityError("an adjusted p-value must be a float")
    if math.isnan(adjusted_p) or not 0.0 <= adjusted_p <= 1.0:
        raise MultiplicityError("an adjusted p-value must lie in [0, 1]")
    return adjusted_p < FAMILY_WISE_ALPHA


__all__ = [
    "EXPECTED_HYPOTHESES",
    "FAMILY_WISE_ALPHA",
    "MultiplicityError",
    "confirmatory_hypothesis_ids",
    "g3_passes",
    "holm_adjust",
    "holm_adjust_confirmatory",
]
