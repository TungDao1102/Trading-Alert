"""Candidate-registration validator: `python -m src.research.register` (Phase 16, plan 16-13, D-28).

One read-only machine check of the candidate-set freeze (inherited D059-5, G4-003). A registered
candidate is a parameter-set TOML under `<registry root>/<family>/` that

- loads through the registry parse path (structurally valid),
- carries a complete rationale table (one provenance label per value),
- carries no PLACEHOLDER label,
- equals exactly one point of the approved, preregistered grid (same id and same hash),
- has a pin entry with the same hash in the pin file that `registry-gate.yml` checks.

Only a candidate that passes every check is reported VALID, and then the exact 64-hex
`parameter_set_hash` is printed: that is the value the user authorizes (O-04).

This module reads files and prints. It never writes to the registry, the pin file or anything
else, and it never orders, ranks or filters grid points by any result (L-03, L-10): the grid
listing is in the grid file's own order and carries structure verdicts only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.domain.rationale import check_rationale_text, placeholder_keys_text
from src.domain.registry import _check_registry_segment
from src.paper.freeze import _parameter_set_from_text, resolve_registry_root

from .manifest import GridPoint, ManifestError, ParameterGrid, load_grid

EXIT_VALID = 0
EXIT_INVALID = 1

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PIN_FILE = _REPO_ROOT / "tests" / "fixtures" / "phase4" / "parameters.json"

STRUCTURALLY_VALID = "STRUCTURALLY_VALID"
STRUCTURALLY_INVALID = "STRUCTURALLY_INVALID"


@dataclass(frozen=True)
class CandidateCheck:
    """The verdict on one candidate file; `parameter_set_hash` is empty unless `valid`."""

    valid: bool
    reasons: tuple[str, ...]
    parameter_set_hash: str
    grid_point_id: str


@dataclass(frozen=True)
class GridListing:
    """Structure verdict of one grid point, in the grid file's own order."""

    parameter_set_id: str
    structurally_valid: bool
    reason: str


@dataclass(frozen=True)
class _LoadedSet:
    strategy_id: str
    parameter_set_id: str
    parameter_set_hash: str
    text: str
    path: Path


def _invalid(*reasons: str) -> CandidateCheck:
    return CandidateCheck(
        valid=False, reasons=tuple(reasons), parameter_set_hash="", grid_point_id=""
    )


def _describe(error: Exception, path: Path) -> str:
    """The loader's message without the file system path, so a verdict names the file only."""
    message = str(error).replace(str(path), path.name)
    return f"{type(error).__name__}: {message}"


def _load(path: Path, strategy_id: str, parameter_set_id: str) -> _LoadedSet:
    """Read the file once; the hash and the rationale verdict both derive from this one read."""
    text = path.read_bytes().decode("utf-8")
    loaded = _parameter_set_from_text(text, path, strategy_id, parameter_set_id)
    return _LoadedSet(
        strategy_id=strategy_id,
        parameter_set_id=parameter_set_id,
        parameter_set_hash=loaded.parameter_set_hash,
        text=text,
        path=path,
    )


def _locate(toml_path: Path, registry_root: Path) -> tuple[str, str] | str:
    """(strategy_id, parameter_set_id) of a file at `<root>/<family>/<id>.toml`, else a reason."""
    resolved = toml_path.resolve()
    if resolved.suffix != ".toml" or resolved.parent.parent != registry_root.resolve():
        return f"OUTSIDE_REGISTRY: {toml_path.name} is not <registry root>/<family>/<id>.toml"
    strategy_id = resolved.parent.name
    parameter_set_id = resolved.stem
    try:
        _check_registry_segment(strategy_id, "strategy_id")
        _check_registry_segment(parameter_set_id, "parameter_set_id")
    except Exception as error:  # noqa: BLE001 - any segment error is a refusal reason
        return f"OUTSIDE_REGISTRY: {error}"
    return strategy_id, parameter_set_id


def _pins(pin_path: Path) -> dict[tuple[str, str], str] | str:
    """Pin hashes keyed by (strategy_id, parameter_set_id), else the reason the file is unusable."""
    try:
        document: Any = json.loads(pin_path.read_bytes().decode("utf-8"))
        entries = document["parameter_sets"] if "parameter_sets" in document else [document]
        return {
            (entry["strategy_id"], entry["parameter_set_id"]): entry["parameter_set_hash"]
            for entry in entries
        }
    except Exception as error:  # noqa: BLE001 - an unreadable pin file is a refusal reason
        return f"NO_PIN_ENTRY: pin file {pin_path.name} is unusable ({type(error).__name__})"


def _grid_reason(grid_path: Path) -> ParameterGrid | str:
    try:
        return load_grid(grid_path)
    except (ManifestError, OSError, ValueError) as error:
        return f"NOT_A_GRID_POINT: grid file {grid_path.name} is unusable ({error})"


def _matching_points(grid: ParameterGrid, loaded: _LoadedSet) -> list[GridPoint]:
    if grid.strategy_id != loaded.strategy_id:
        return []
    return [
        point
        for point in grid.points
        if point.parameter_set_id == loaded.parameter_set_id
        and point.parameter_set_hash == loaded.parameter_set_hash
    ]


def validate_candidate(
    toml_path: Path,
    *,
    grid_path: Path,
    pin_path: Path,
    registry_root: Path,
) -> CandidateCheck:
    """Read-only check of one candidate set file; VALID only when every rule holds."""
    located = _locate(toml_path, registry_root)
    if isinstance(located, str):
        return _invalid(located)
    strategy_id, parameter_set_id = located
    try:
        loaded = _load(toml_path.resolve(), strategy_id, parameter_set_id)
    except Exception as error:  # noqa: BLE001 - every loader failure is a refusal reason
        return _invalid(f"STRUCTURALLY_INVALID: {_describe(error, toml_path)}")

    reasons: list[str] = []
    try:
        problems = check_rationale_text(loaded.text, loaded.path)
        placeholders = placeholder_keys_text(loaded.text)
    except Exception as error:  # noqa: BLE001 - every loader failure is a refusal reason
        return _invalid(f"STRUCTURALLY_INVALID: {_describe(error, toml_path)}")
    if problems:
        reasons.append("RATIONALE_INCOMPLETE: " + "; ".join(problems))
    if placeholders:
        reasons.append("PLACEHOLDER: " + ", ".join(placeholders))

    grid = _grid_reason(grid_path)
    grid_point_id = ""
    if isinstance(grid, str):
        reasons.append(grid)
    else:
        matches = _matching_points(grid, loaded)
        if len(matches) == 1:
            grid_point_id = matches[0].parameter_set_id
        elif matches:
            reasons.append(
                f"NOT_A_GRID_POINT: {parameter_set_id} appears more than once in the grid"
            )
        else:
            reasons.append(
                f"NOT_A_GRID_POINT: {strategy_id}/{parameter_set_id} with hash "
                f"{loaded.parameter_set_hash} is not a point of the approved grid"
            )

    pins = _pins(pin_path)
    if isinstance(pins, str):
        reasons.append(pins)
    else:
        pinned = pins.get((strategy_id, parameter_set_id))
        if pinned is None:
            reasons.append(f"NO_PIN_ENTRY: {strategy_id}/{parameter_set_id} is not in the pin file")
        elif pinned != loaded.parameter_set_hash:
            reasons.append(
                f"PIN_HASH_MISMATCH: pin file holds {pinned}, the file computes "
                f"{loaded.parameter_set_hash}"
            )

    if reasons:
        return _invalid(*reasons)
    return CandidateCheck(
        valid=True,
        reasons=(),
        parameter_set_hash=loaded.parameter_set_hash,
        grid_point_id=grid_point_id,
    )


def _render_check(result: CandidateCheck) -> str:
    if not result.valid:
        lines = ["INVALID", *(f"reason: {reason}" for reason in result.reasons)]
        return "\n".join(lines) + "\n"
    return (
        "VALID\n"
        f"grid_point={result.grid_point_id}\n"
        f"parameter_set_hash={result.parameter_set_hash}\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; exit 0 for VALID, 1 for INVALID, argparse's 2 for a usage error."""
    parser = argparse.ArgumentParser(
        prog="python -m src.research.register",
        description="Read-only candidate-registration check (D-28).",
        allow_abbrev=False,
    )
    parser.add_argument("--check", type=Path, required=True, help="Candidate set TOML file.")
    parser.add_argument("--grid", type=Path, required=True, help="Approved parameter grid JSON.")
    parser.add_argument("--pin-file", type=Path, default=DEFAULT_PIN_FILE, help="Pin JSON file.")
    parser.add_argument(
        "--registry-root",
        type=Path,
        default=None,
        help="Registry root directory (default: src.domain.registry.REGISTRY_ROOT).",
    )
    args = parser.parse_args(argv)
    result = validate_candidate(
        args.check,
        grid_path=args.grid,
        pin_path=args.pin_file,
        registry_root=resolve_registry_root(args.registry_root),
    )
    sys.stdout.write(_render_check(result))
    return EXIT_VALID if result.valid else EXIT_INVALID


if __name__ == "__main__":
    sys.exit(main())
