"""Plan 16-45 Task 3: the research-run-1 grid is registered as hash-locked, rationalized sets.

The user approved the hypothesis and the three 16-point grids at decision O-02
(`.planning/phases/16-paper-runtime-composition/decisions/16-DEC-O-02.md`, approve-with-changes).
This module checks the registered artifacts only: the grid files, the 48 immutable parameter sets
under `params/` and their pins. It runs no simulator and reads no market data, no result and no
holdout. Approval and registration are not an authorization to run research (O-03).
"""

from __future__ import annotations

import hashlib
import itertools
import json
from decimal import Decimal
from pathlib import Path

import pytest
from src.domain.rationale import check_rationale, load_rationale, placeholder_keys
from src.domain.registry import load_parameter_set
from src.research.manifest import ParameterGrid, load_grid
from src.research.register import list_grid, validate_candidate

REPO_ROOT = Path(__file__).resolve().parent.parent
PARAMS_ROOT = REPO_ROOT / "params"
PIN_FILE = REPO_ROOT / "tests" / "fixtures" / "phase4" / "parameters.json"
PREREG_DIR = REPO_ROOT / "docs" / "research" / "preregistration"

STRATEGY_VERSION = "v5.0.0"
TTL_SECONDS = 2400
BASELINE_ID = "baseline-v6"
VARIANT_BUDGET_PER_FAMILY = 25

# family -> (id letter, ordered varied axes with their two registered values)
FAMILIES: dict[str, tuple[str, tuple[tuple[str, tuple[str, str]], ...]]] = {
    "trend-pullback": (
        "a",
        (
            ("pivot_bars", ("3", "5")),
            ("zone_tolerance_atr", ("0.5", "1.0")),
            ("sl_buffer_atr", ("0.2", "0.5")),
            ("signal_expiry_hours", ("4", "8")),
        ),
    ),
    "breakout-retest": (
        "b",
        (
            ("retest_window_bars", ("5", "10")),
            ("retest_depth_atr", ("0.3", "0.6")),
            ("zone_tolerance_atr", ("0.5", "1.0")),
            ("signal_expiry_hours", ("4", "8")),
        ),
    ),
    "range-mr": (
        "c",
        (
            ("regime_filter_lookback", ("50", "100")),
            ("zone_min_touches", ("2", "3")),
            ("range_break_buffer_atr", ("0.2", "0.5")),
            ("signal_expiry_hours", ("4", "8")),
        ),
    ),
}


def _grid_path(family: str) -> Path:
    return PREREG_DIR / f"research-run-1-grid-{family}.json"


def _set_ids(family: str) -> list[str]:
    letter = FAMILIES[family][0]
    return [f"research-run-1-{letter}{index:02d}" for index in range(1, 17)]


def _grid(family: str) -> ParameterGrid:
    return load_grid(_grid_path(family))


def _pins() -> dict[tuple[str, str], str]:
    document = json.loads(PIN_FILE.read_text(encoding="utf-8"))
    return {
        (entry["strategy_id"], entry["parameter_set_id"]): entry["parameter_set_hash"]
        for entry in document["parameter_sets"]
    }


def _same(left: object, right: object) -> bool:
    if isinstance(left, str) or isinstance(right, str):
        return left == right
    return Decimal(str(left)) == Decimal(str(right))


def _param_keys(axis: str) -> tuple[str, ...]:
    return ("pivot_left_bars", "pivot_right_bars") if axis == "pivot_bars" else (axis,)


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_grid_has_sixteen_points_in_full_factorial_order(family: str) -> None:
    grid = _grid(family)
    assert grid.strategy_id == family
    assert len(grid.points) == 16 <= VARIANT_BUDGET_PER_FAMILY
    assert [p.parameter_set_id for p in grid.points] == _set_ids(family)
    axes = FAMILIES[family][1]
    expected = list(itertools.product(*(values for _axis, values in axes)))
    for point, combination in zip(grid.points, expected, strict=True):
        assert point.varied == tuple(
            (axis, value) for (axis, _values), value in zip(axes, combination, strict=True)
        )


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_exactly_sixteen_research_run_1_set_files_per_family(family: str) -> None:
    found = sorted(p.stem for p in (PARAMS_ROOT / family).glob("research-run-1-*.toml"))
    assert found == sorted(_set_ids(family))


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_every_point_has_loader_hash_pin_and_strategy_version(family: str) -> None:
    pins = _pins()
    for point in _grid(family).points:
        loaded = load_parameter_set(family, point.parameter_set_id)
        assert loaded.parameter_set_hash == point.parameter_set_hash
        assert pins[(family, point.parameter_set_id)] == point.parameter_set_hash
        assert loaded.strategy_version == STRATEGY_VERSION


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_list_grid_reports_every_point_structurally_valid(family: str) -> None:
    listing = list_grid(_grid_path(family), registry_root=PARAMS_ROOT)
    assert [entry.parameter_set_id for entry in listing] == _set_ids(family)
    assert all(entry.structurally_valid for entry in listing), [
        (e.parameter_set_id, e.reason) for e in listing if not e.structurally_valid
    ]


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_every_set_is_a_valid_registered_candidate(family: str) -> None:
    for set_id in _set_ids(family):
        result = validate_candidate(
            PARAMS_ROOT / family / f"{set_id}.toml",
            grid_path=_grid_path(family),
            pin_path=PIN_FILE,
            registry_root=PARAMS_ROOT,
        )
        assert result.valid, (set_id, result.reasons)
        assert result.grid_point_id == set_id


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_rationale_is_complete_and_placeholder_free(family: str) -> None:
    for set_id in _set_ids(family):
        path = PARAMS_ROOT / family / f"{set_id}.toml"
        assert check_rationale(path) == [], set_id
        assert placeholder_keys(path) == (), set_id


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_sets_differ_from_baseline_v6_only_on_varied_keys_and_the_ttl(family: str) -> None:
    baseline = load_parameter_set(family, BASELINE_ID).params
    axes = FAMILIES[family][1]
    allowed = {key for axis, _values in axes for key in _param_keys(axis)}
    allowed.add("constraint_snapshot_ttl_seconds")
    for point in _grid(family).points:
        params = load_parameter_set(family, point.parameter_set_id).params
        assert set(params) == set(baseline), point.parameter_set_id
        changed = {key for key in params if not _same(params[key], baseline[key])}
        assert changed <= allowed, (point.parameter_set_id, sorted(changed - allowed))
        assert params["constraint_snapshot_ttl_seconds"] == TTL_SECONDS
        assert params["max_cost_to_risk"] == baseline["max_cost_to_risk"] == Decimal("0.15")
        for axis, value in point.varied:
            for key in _param_keys(axis):
                assert Decimal(str(params[key])) == Decimal(value), (point.parameter_set_id, key)


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_point_01_matches_baseline_v6_except_for_the_ttl(family: str) -> None:
    baseline = load_parameter_set(family, BASELINE_ID).params
    first = load_parameter_set(family, _set_ids(family)[0]).params
    differing = sorted(key for key in first if not _same(first[key], baseline[key]))
    assert differing == ["constraint_snapshot_ttl_seconds"]


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_ttl_is_a_decision_value_sourced_to_o_07(family: str) -> None:
    for set_id in _set_ids(family):
        entry = load_rationale(PARAMS_ROOT / family / f"{set_id}.toml")[
            "constraint_snapshot_ttl_seconds"
        ]
        assert entry.basis == "DECISION"
        assert entry.value == str(TTL_SECONDS)
        assert "O-07" in entry.text
        assert "16-DEC-O-07" in entry.text


def test_the_hypothesis_is_registered_and_is_not_marked_draft() -> None:
    text = (PREREG_DIR / "research-run-1-hypothesis.md").read_text(encoding="utf-8")
    head = "\n".join(text.splitlines()[:3])
    assert "DRAFT - not approved" not in text
    assert not head.startswith("DRAFT")
    assert "16-DEC-O-02" in text
    assert "not an authorization" in text.lower() or "does not authorize" in text.lower()
    assert "cross-family multiplicity" in text.lower()
    assert (PREREG_DIR / "research-run-1-hypothesis-DRAFT.md").is_file()


# Quick 261014-cvk (protocol v2.3.0, D068 and D069): the approved hypothesis file is never edited;
# an addendum records the global Holm and the declared constraint assumption.
HYPOTHESIS_SHA256_LF = "5e580ac8559ff748a642da0594406d0b7cc01a36ef08404acec0262d0f98e230"
CONSTRAINT_BASELINE_SHA256 = "4307eec74feeab04081b872866895f70568f1d289b8a249fc7de702e71e11d3f"


def test_the_approved_hypothesis_file_is_not_edited() -> None:
    raw = (PREREG_DIR / "research-run-1-hypothesis.md").read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(raw).hexdigest() == HYPOTHESIS_SHA256_LF


def test_the_v230_addendum_records_the_global_holm_and_the_constraint_assumption() -> None:
    path = PREREG_DIR / "research-run-1-hypothesis-ADDENDUM-v2.3.0.md"
    text = path.read_text(encoding="utf-8")
    for token in ("v2.3.0", "D068", "D069", "global Holm", CONSTRAINT_BASELINE_SHA256):
        assert token in text, token
    assert "16-DEC-V230" in text
    assert "NOT an authorization" in text
    baseline = PREREG_DIR / "research-run-1-constraints-baseline.json"
    assert hashlib.sha256(baseline.read_bytes()).hexdigest() == CONSTRAINT_BASELINE_SHA256
