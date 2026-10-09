"""Plan 16-13: candidate-registration validator (D-28, inherited D059-5, L-03).

`python -m src.research.register --check <toml> --grid <grid>` is one read-only machine check:
the set is structurally valid, has a complete rationale table, has no PLACEHOLDER key, equals
exactly one point of the preregistered grid and has a matching pin entry. Only then does it
print the exact parameter_set_hash the user authorizes.

Everything here runs on pytest tmp_path registries, grids and pin files; nothing writes under
params/ or tests/fixtures/.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import pytest
from src.domain.registry import load_parameter_set
from src.paper.freeze import load_parameter_set_at_root
from src.research import register
from src.research.register import CandidateCheck, list_grid, main, validate_candidate

from tests.test_rationale import BASE_SET as _BASE_SET
from tests.test_rationale import (
    STRATEGY_ID,
    complete_rationale,
    parsed_params,
    write_rationalized_set,
    write_set,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTER_SOURCE = REPO_ROOT / "src" / "research" / "register.py"
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


# --------------------------------------------------------------------------- #
# Task 2: every refusal reason, the committed baseline sets, the listing, no writes.
# --------------------------------------------------------------------------- #


def _check(world: dict[str, Any], **overrides: Any) -> CandidateCheck:
    kwargs: dict[str, Any] = {
        "grid_path": world["grid"],
        "pin_path": world["pins"],
        "registry_root": world["registry_root"],
    }
    kwargs.update(overrides)
    toml = kwargs.pop("toml", world["toml"])
    return validate_candidate(toml, **kwargs)


def _reasons(result: CandidateCheck) -> str:
    assert result.valid is False
    assert result.parameter_set_hash == ""
    return " | ".join(result.reasons)


def test_missing_rationale_table_is_refused(world: dict[str, Any]) -> None:
    toml = write_set(world["registry_root"], spec=None, set_id=SET_A)
    result = _check(world, toml=toml)
    assert "RATIONALE_INCOMPLETE" in _reasons(result)


def test_value_without_provenance_label_is_refused(world: dict[str, Any]) -> None:
    spec = complete_rationale(parsed_params(_BASE_SET))
    first = next(iter(spec))
    del spec[first]["basis"]
    toml = write_set(world["registry_root"], spec=spec, set_id=SET_A)
    result = _check(world, toml=toml)
    assert "RATIONALE_INCOMPLETE" in _reasons(result)
    assert first in " ".join(result.reasons)


def test_placeholder_label_is_refused(world: dict[str, Any]) -> None:
    toml = write_rationalized_set(
        world["registry_root"], placeholder_key="minimum_rr", set_id=SET_A
    )
    result = _check(world, toml=toml)
    reasons = _reasons(result)
    assert "PLACEHOLDER" in reasons
    assert "minimum_rr" in reasons


def test_a_set_that_is_not_a_grid_point_is_refused(world: dict[str, Any]) -> None:
    other = write_rationalized_set(world["registry_root"], set_id=SET_B)
    digest_b = _hash_of(world["registry_root"], SET_B)
    # SET_B is pinned but absent from the grid.
    pins = _write_pins(world["work"] / "pins2.json", [(SET_A, world["digest"]), (SET_B, digest_b)])
    result = _check(world, toml=other, pin_path=pins)
    assert "NOT_A_GRID_POINT" in _reasons(result)


def test_a_grid_point_with_a_different_hash_is_refused(world: dict[str, Any]) -> None:
    grid = _write_grid(world["work"] / "grid2.json", [(SET_A, "0" * 64)])
    result = _check(world, grid_path=grid)
    assert "NOT_A_GRID_POINT" in _reasons(result)


def test_a_missing_pin_entry_is_refused(world: dict[str, Any]) -> None:
    pins = _write_pins(world["work"] / "pins3.json", [])
    result = _check(world, pin_path=pins)
    assert "NO_PIN_ENTRY" in _reasons(result)


def test_a_pin_hash_mismatch_is_refused(world: dict[str, Any]) -> None:
    pins = _write_pins(world["work"] / "pins4.json", [(SET_A, "f" * 64)])
    result = _check(world, pin_path=pins)
    assert "PIN_HASH_MISMATCH" in _reasons(result)


def test_a_set_file_outside_the_registry_family_layout_is_refused(
    world: dict[str, Any],
) -> None:
    stray_dir = world["tmp"] / "elsewhere" / STRATEGY_ID
    stray_dir.mkdir(parents=True)
    stray = stray_dir / f"{SET_A}.toml"
    stray.write_bytes(world["toml"].read_bytes())
    result = _check(world, toml=stray)
    assert "OUTSIDE_REGISTRY" in _reasons(result)


def test_a_structurally_invalid_set_is_refused(world: dict[str, Any]) -> None:
    broken = world["registry_root"] / STRATEGY_ID / "broken.toml"
    broken.write_text("schema_version = 99\n", encoding="utf-8")
    result = _check(world, toml=broken)
    assert "STRUCTURALLY_INVALID" in _reasons(result)


def test_every_refusal_exits_one_and_prints_no_hash(
    world: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    pins = _write_pins(world["work"] / "pins5.json", [])
    code = main(
        [
            "--check",
            str(world["toml"]),
            "--grid",
            str(world["grid"]),
            "--pin-file",
            str(pins),
            "--registry-root",
            str(world["registry_root"]),
        ]
    )
    out = capsys.readouterr().out
    assert code == 1
    assert "INVALID" in out
    assert "NO_PIN_ENTRY" in out
    assert "parameter_set_hash=" not in out
    assert not HEX64.search(out)


@pytest.mark.parametrize("strategy_id", ["trend-pullback", "breakout-retest", "range-mr"])
def test_committed_baseline_v6_sets_are_invalid_for_placeholder(
    strategy_id: str, tmp_path: Path
) -> None:
    registry_root = REPO_ROOT / "params"
    toml = registry_root / strategy_id / "baseline-v6.toml"
    digest = load_parameter_set(strategy_id, "baseline-v6").parameter_set_hash
    grid_body = {
        "strategy_id": strategy_id,
        "points": [
            {
                "parameter_set_id": "baseline-v6",
                "parameter_set_hash": digest,
                "varied": [["minimum_rr", "2"]],
            }
        ],
    }
    grid = tmp_path / "grid.json"
    grid.write_text(json.dumps(grid_body), encoding="utf-8")
    pins = REPO_ROOT / "tests" / "fixtures" / "phase4" / "parameters.json"
    before = toml.read_bytes(), pins.read_bytes()
    result = validate_candidate(toml, grid_path=grid, pin_path=pins, registry_root=registry_root)
    assert result.valid is False
    assert "PLACEHOLDER" in " | ".join(result.reasons)
    assert (toml.read_bytes(), pins.read_bytes()) == before


def test_list_grid_follows_the_file_order_with_structure_only(
    world: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    ids = ["cand-z", "cand-a", "cand-m"]
    points: list[tuple[str, str]] = []
    for set_id in ("cand-z", "cand-a"):
        write_rationalized_set(world["registry_root"], set_id=set_id)
        points.append((set_id, _hash_of(world["registry_root"], set_id)))
    # cand-m has no file in the registry.
    points.append(("cand-m", "1" * 64))
    grid = _write_grid(world["work"] / "listing.json", points)

    entries = list_grid(grid, registry_root=world["registry_root"])
    assert [e.parameter_set_id for e in entries] == ids
    assert [e.structurally_valid for e in entries] == [True, True, False]

    code = main(
        ["--list-grid", "--grid", str(grid), "--registry-root", str(world["registry_root"])]
    )
    out = capsys.readouterr().out
    assert code == 0
    lines = [line for line in out.splitlines() if line.strip()]
    assert [line.split()[0] for line in lines] == ids
    assert [line.split()[1].rstrip(":") for line in lines] == [
        "STRUCTURALLY_VALID",
        "STRUCTURALLY_VALID",
        "STRUCTURALLY_INVALID",
    ]
    forbidden = r"(rank|ranked|score|metric|count|sharpe|pnl|profit|best|top)"
    assert re.search(forbidden, out.lower()) is None


_WRITE_ATTRS = {"write_text", "write_bytes", "rename", "unlink", "rmdir", "mkdir", "touch"}
# Names that are harmless on a str or a dict (replace, remove, copy) but write on os or shutil.
_WRITE_ATTRS_ON_OS = {"replace", "remove", "copy", "copyfile", "move", "rmtree", "rename"}


def _write_violations(source: str) -> list[str]:
    """Names of write-capable calls and imports in the source text."""
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in _WRITE_ATTRS:
                found.append(f"call .{func.attr}")
            if (
                isinstance(func, ast.Attribute)
                and func.attr in _WRITE_ATTRS_ON_OS
                and isinstance(func.value, ast.Name)
                and func.value.id in {"os", "shutil"}
            ):
                found.append(f"call {func.value.id}.{func.attr}")
            if isinstance(func, ast.Name) and func.id == "open":
                mode: ast.expr | None = node.args[1] if len(node.args) > 1 else None
                for keyword in node.keywords:
                    if keyword.arg == "mode":
                        mode = keyword.value
                if mode is not None and not (
                    isinstance(mode, ast.Constant)
                    and isinstance(mode.value, str)
                    and not set(mode.value) & set("wax+")
                ):
                    found.append("call open(write or unknown mode)")
            if isinstance(func, ast.Attribute) and func.attr == "open":
                found.append("call .open")
        if isinstance(node, ast.Import):
            found.extend(f"import {a.name}" for a in node.names if a.name.split(".")[0] == "shutil")
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "shutil":
            found.append("from shutil")
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "shutil":
                found.append("shutil.attribute")
    return found


def test_register_source_has_no_write_call_and_does_not_name_the_allowlist() -> None:
    source = REGISTER_SOURCE.read_text(encoding="utf-8")
    assert _write_violations(source) == []
    assert "allowlist" not in source.lower()
    assert "holdout_consumed" not in source


def test_write_scan_catches_seeded_violations() -> None:
    assert _write_violations("open('x', 'w')\n") != []
    assert _write_violations("open('x', mode='a')\n") != []
    assert _write_violations("p.write_text('x')\n") != []
    assert _write_violations("p.write_bytes(b'')\n") != []
    assert _write_violations("import os\nos.replace('a', 'b')\n") != []
    assert _write_violations("import shutil\n") != []
    assert _write_violations("from shutil import copy\n") != []
    assert _write_violations("x = open('x')\n") == []
    assert _write_violations("x = open('x', 'rb')\n") == []


def test_register_module_exposes_the_documented_entry_points() -> None:
    assert callable(register.validate_candidate)
    assert callable(register.list_grid)
    assert callable(register.main)
