"""Plan 15-02: machine-checked, hash-neutral parameter rationale (D-16, D-27).

A parameter set file may carry one `[rationale.<key>]` table per `[parameters]`
key. The tables are metadata: they never enter the canonical hash payload
(strategy_id, strategy_version, parameter_set_id, parameters), so adding them
leaves `parameter_set_hash` unchanged.

Sets are written into pytest tmp_path registries only; nothing here creates a
file under params/ (PA-01 reads every params/**/*.toml as a set).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.domain import registry
from src.domain.rationale import check_rationale, placeholder_keys

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE_SET = REPO_ROOT / "params" / "trend-pullback" / "baseline-v5.toml"

STRATEGY_ID = "trend-pullback"
SET_ID = "baseline-v5"

RationaleSpec = dict[str, dict[str, str]]


# --------------------------------------------------------------------------- #
# Helpers (imported by tests/test_paper_freeze.py).
# --------------------------------------------------------------------------- #


def parsed_params(path: Path) -> dict[str, Any]:
    """Normalized [parameters] of a set file via the registry's own parse path."""
    text = path.read_bytes().decode("utf-8")
    _version, params = registry._parse_and_validate(text, path, path.parent.name, path.stem)
    return params


def complete_rationale(
    params: dict[str, Any],
    *,
    basis: str = "DECISION",
    ref: str | None = "D046",
) -> RationaleSpec:
    """One entry per parameter key; value is the parsed parameter as a string."""
    spec: RationaleSpec = {}
    for key, value in params.items():
        entry = {"basis": basis, "value": str(value), "text": f"why {key}"}
        if ref is not None:
            entry["ref"] = ref
        spec[key] = entry
    return spec


def render_rationale(spec: RationaleSpec) -> str:
    """Render rationale tables as TOML text (JSON strings are valid TOML basic strings)."""
    blocks: list[str] = []
    for key, entry in spec.items():
        lines = [f"[rationale.{key}]"]
        for field, value in entry.items():
            lines.append(f"{field} = {json.dumps(value)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def write_set(
    root: Path,
    *,
    spec: RationaleSpec | None,
    strategy_id: str = STRATEGY_ID,
    set_id: str = SET_ID,
) -> Path:
    """Copy baseline-v5 into root/<strategy_id>/<set_id>.toml and append rationale tables."""
    base_text = BASE_SET.read_bytes().decode("utf-8")
    if spec is not None:
        base_text = base_text.rstrip("\n") + "\n\n" + render_rationale(spec)
    path = root / strategy_id / f"{set_id}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base_text.encode("utf-8"))
    return path


def write_rationalized_set(
    root: Path,
    *,
    placeholder_key: str | None = None,
    set_id: str = SET_ID,
) -> Path:
    """Write a fully rationalized copy of baseline-v5, optionally with one PLACEHOLDER key."""
    params = parsed_params(BASE_SET)
    spec = complete_rationale(params)
    if placeholder_key is not None:
        spec[placeholder_key] = {
            "basis": "PLACEHOLDER",
            "value": str(params[placeholder_key]),
            "text": "seed value, not yet justified",
        }
    return write_set(root, spec=spec, set_id=set_id)


# --------------------------------------------------------------------------- #
# Task 1 tracer behaviors.
# --------------------------------------------------------------------------- #


def test_rationale_tables_do_not_change_parameter_set_hash(tmp_path: Path) -> None:
    from src.paper.freeze import _load_parameter_set_with_root

    bare_root = tmp_path / "bare"
    rich_root = tmp_path / "rich"
    bare = write_set(bare_root, spec=None)
    rich = write_rationalized_set(rich_root)
    assert "[rationale." not in bare.read_bytes().decode("utf-8")
    assert "[rationale." in rich.read_bytes().decode("utf-8")

    bare_set = _load_parameter_set_with_root(STRATEGY_ID, SET_ID, bare_root)
    rich_set = _load_parameter_set_with_root(STRATEGY_ID, SET_ID, rich_root)
    assert bare_set.parameter_set_hash == rich_set.parameter_set_hash
    assert bare_set.params == rich_set.params


def test_check_rationale_clean_for_complete_set(tmp_path: Path) -> None:
    path = write_rationalized_set(tmp_path)
    assert check_rationale(path) == []


def test_check_rationale_reports_missing_entry(tmp_path: Path) -> None:
    params = parsed_params(BASE_SET)
    spec = complete_rationale(params)
    del spec["swing_lookback"]
    path = write_set(tmp_path, spec=spec)
    problems = check_rationale(path)
    assert len(problems) == 1
    assert "swing_lookback" in problems[0]
    assert "missing" in problems[0]


def test_check_rationale_reports_every_key_when_no_rationale_at_all(tmp_path: Path) -> None:
    path = write_set(tmp_path, spec=None)
    problems = check_rationale(path)
    assert len(problems) == len(parsed_params(path))
    assert problems == sorted(problems)


def test_check_rationale_reports_extra_entry(tmp_path: Path) -> None:
    params = parsed_params(BASE_SET)
    spec = complete_rationale(params)
    spec["not_a_parameter"] = {"basis": "STRUCTURAL", "value": "1", "text": "stray"}
    path = write_set(tmp_path, spec=spec)
    problems = check_rationale(path)
    assert len(problems) == 1
    assert "not_a_parameter" in problems[0]


def test_placeholder_keys_returns_sorted_placeholder_keys(tmp_path: Path) -> None:
    params = parsed_params(BASE_SET)
    spec = complete_rationale(params)
    for key in ("sl_buffer_atr", "minimum_rr"):
        spec[key] = {"basis": "PLACEHOLDER", "value": str(params[key]), "text": "seed"}
    path = write_set(tmp_path, spec=spec)
    assert placeholder_keys(path) == ("minimum_rr", "sl_buffer_atr")


def test_placeholder_keys_empty_without_rationale(tmp_path: Path) -> None:
    path = write_set(tmp_path, spec=None)
    assert placeholder_keys(path) == ()
