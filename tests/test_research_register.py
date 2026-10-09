"""Plan 16-13: candidate-registration validator (D-28, inherited D059-5, L-03).

`python -m src.research.register --check <toml> --grid <grid>` is one read-only machine check:
the set is structurally valid, has a complete rationale table, has no PLACEHOLDER key, equals
exactly one point of the preregistered grid and has a matching pin entry. Only then does it
print the exact parameter_set_hash the user authorizes.

Everything here runs on pytest tmp_path registries, grids and pin files; nothing writes under
params/ or tests/fixtures/.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from src.paper.freeze import load_parameter_set_at_root
from src.research.register import CandidateCheck, main, validate_candidate

from tests.test_rationale import (
    STRATEGY_ID,
    write_rationalized_set,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
HEX64 = re.compile(r"[0-9a-f]{64}")

SET_A = "cand-a"
SET_B = "cand-b"


def _hash_of(root: Path, set_id: str) -> str:
    return load_parameter_set_at_root(STRATEGY_ID, set_id, root).parameter_set_hash


def _write_grid(path: Path, points: list[tuple[str, str]]) -> Path:
    """A grid file; each point is (parameter_set_id, parameter_set_hash)."""
    body: dict[str, Any] = {
        "strategy_id": STRATEGY_ID,
        "points": [
            {
                "parameter_set_id": set_id,
                "parameter_set_hash": digest,
                "varied": [["minimum_rr", "2"]],
            }
            for set_id, digest in points
        ],
    }
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    return path


def _write_pins(path: Path, entries: list[tuple[str, str]]) -> Path:
    body = {
        "parameter_sets": [
            {
                "strategy_id": STRATEGY_ID,
                "parameter_set_id": set_id,
                "strategy_version": "v4.0.0",
                "parameter_set_hash": digest,
            }
            for set_id, digest in entries
        ]
    }
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    return path


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Any]:
    """A registry with one valid candidate, a grid holding it, and a pin file pinning it."""
    registry_root = tmp_path / "registry"
    toml = write_rationalized_set(registry_root, set_id=SET_A)
    digest = _hash_of(registry_root, SET_A)
    work = tmp_path / "work"
    work.mkdir()
    grid = _write_grid(work / "grid.json", [(SET_A, digest)])
    pins = _write_pins(work / "pins.json", [(SET_A, digest)])
    return {
        "tmp": tmp_path,
        "registry_root": registry_root,
        "toml": toml,
        "digest": digest,
        "grid": grid,
        "pins": pins,
        "work": work,
    }


# --------------------------------------------------------------------------- #
# Task 1 (tracer): a valid preregistered candidate prints VALID and its exact hash.
# --------------------------------------------------------------------------- #


def test_valid_candidate_is_valid_and_prints_the_loader_hash(
    world: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    result = validate_candidate(
        world["toml"],
        grid_path=world["grid"],
        pin_path=world["pins"],
        registry_root=world["registry_root"],
    )
    assert isinstance(result, CandidateCheck)
    assert result.valid is True
    assert result.reasons == ()
    assert result.grid_point_id == SET_A
    assert result.parameter_set_hash == world["digest"]
    assert HEX64.fullmatch(result.parameter_set_hash)

    code = main(
        [
            "--check",
            str(world["toml"]),
            "--grid",
            str(world["grid"]),
            "--pin-file",
            str(world["pins"]),
            "--registry-root",
            str(world["registry_root"]),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "VALID" in out
    lines = [line for line in out.splitlines() if line.startswith("parameter_set_hash=")]
    assert lines == [f"parameter_set_hash={world['digest']}"]
    assert HEX64.fullmatch(lines[0].split("=", 1)[1])


def test_the_check_leaves_every_file_byte_identical(
    world: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    before = _snapshot(world["tmp"])
    code = main(
        [
            "--check",
            str(world["toml"]),
            "--grid",
            str(world["grid"]),
            "--pin-file",
            str(world["pins"]),
            "--registry-root",
            str(world["registry_root"]),
        ]
    )
    capsys.readouterr()
    assert code == 0
    assert _snapshot(world["tmp"]) == before
