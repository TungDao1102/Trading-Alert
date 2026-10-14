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
claims that multiplicity is complete end to end.

A hypothesis id is `"<strategy_id>/<parameter_set_id>"`, unique across the three families.
P-values are `Decimal` (a bootstrap p-value is the rational (k + 1) / (B + 1)); a float, an int, a
bool or a string is refused, which keeps the correction free of binary-float noise and inside the
Decimal-only scan that covers `src/research` (tests/test_domain_no_float.py).
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

from .manifest import ManifestError, load_grid

FAMILY_WISE_ALPHA = Decimal("0.05")
EXPECTED_HYPOTHESES = 48
_EXPECTED_GRID_FILES = 3
_PER_FAMILY = 16
_GRID_GLOB = "research-run-1-grid-*.json"
_DEFAULT_GRID_DIR = Path(__file__).resolve().parents[2] / "docs" / "research" / "preregistration"
_ZERO = Decimal(0)
_ONE = Decimal(1)


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


def _check_probability(value: object, what: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise MultiplicityError(f"{what} must be a Decimal")
    if not value.is_finite() or not _ZERO <= value <= _ONE:
        raise MultiplicityError(f"{what} must lie in [0, 1]")
    return value


def _validated(p_by_id: Mapping[str, object]) -> dict[str, Decimal]:
    if not p_by_id:
        raise MultiplicityError("an empty hypothesis set cannot be corrected")
    clean: dict[str, Decimal] = {}
    for raw_id, raw_p in p_by_id.items():
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise MultiplicityError("a hypothesis id must be a non-empty string")
        hypothesis_id = raw_id.strip()
        if hypothesis_id in clean:
            raise MultiplicityError("duplicate hypothesis id after normalization")
        clean[hypothesis_id] = _check_probability(raw_p, "a p-value")
    return clean


def holm_adjust(p_by_id: Mapping[str, Decimal]) -> dict[str, Decimal]:
    """Holm step-down adjusted p-values over exactly the given hypotheses (m = their count).

    Sorted by (p, id); adjusted_j = min(1, max over i <= j of (m - i) * p_i), i from 0. The
    result is keyed in sorted-id order, so it does not depend on the input order; equal
    p-values receive equal adjusted values.
    """
    clean = _validated(p_by_id)
    m = len(clean)
    ordered = sorted(clean, key=lambda hypothesis_id: (clean[hypothesis_id], hypothesis_id))
    adjusted: dict[str, Decimal] = {}
    running = _ZERO
    for index, hypothesis_id in enumerate(ordered):
        running = max(running, Decimal(m - index) * clean[hypothesis_id])
        adjusted[hypothesis_id] = min(_ONE, running)
    return {hypothesis_id: adjusted[hypothesis_id] for hypothesis_id in sorted(adjusted)}


def holm_adjust_confirmatory(p_by_id: Mapping[str, Decimal]) -> dict[str, Decimal]:
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


def g3_passes(adjusted_p: Decimal) -> bool:
    """G3: true only when the Holm-adjusted p-value is strictly below the family-wise alpha."""
    return _check_probability(adjusted_p, "an adjusted p-value") < FAMILY_WISE_ALPHA


__all__ = [
    "EXPECTED_HYPOTHESES",
    "FAMILY_WISE_ALPHA",
    "MultiplicityError",
    "confirmatory_hypothesis_ids",
    "g3_passes",
    "holm_adjust",
    "holm_adjust_confirmatory",
]
