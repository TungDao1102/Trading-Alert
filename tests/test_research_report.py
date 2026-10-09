"""Tests for the runner's reporting (Phase 16, plan 16-18, D-27, D-29, D-30; BKTS-03).

The plateau section is reporting only: grid-file order, each point's existing report metrics
beside its one-step axis neighbours, no marker, no ordering by a metric. Nothing here reads
the holdout or changes a record.
"""

from __future__ import annotations

import dataclasses
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.research import plateau as plateau_module
from src.research import run as research_run
from src.research.manifest import GridPoint, ParameterGrid
from src.research.plateau import PlateauError, plateau_report, render_plateau
from src.research.report import render_run_report
from src.research.run import run_research

from tests.test_research_runner import (  # noqa: F401 - fixtures are used by name
    REPO_ROOT,
    VERDICT_WORDS,
    _authorization,
    _grid,
    _manifest,
    spies,
    store,
)

FORBIDDEN_WORDS = ("best", "top", "rank", "winner", "select", "recommended")


def _point(pid: str, a: str, b: str) -> GridPoint:
    return GridPoint(
        parameter_set_id=pid,
        parameter_set_hash="a" * 64,
        varied=(("axis_a", a), ("axis_b", b)),
    )


def _grid_2x2() -> ParameterGrid:
    return ParameterGrid(
        strategy_id="trend-pullback",
        points=(
            _point("p11", "1", "10"),
            _point("p12", "1", "20"),
            _point("p21", "2", "10"),
            _point("p22", "2", "20"),
        ),
    )


def _summaries(values: dict[str, str]) -> dict[str, dict[str, object]]:
    return {pid: {"mean_r": Decimal(v), "closed_trades": 7} for pid, v in values.items()}


# --------------------------------------------------------------------------- #
# Test 1: grid-file order, each point beside its one-step axis neighbours.
# --------------------------------------------------------------------------- #


def test_plateau_report_lists_points_in_grid_order_with_one_step_neighbours() -> None:
    grid = _grid_2x2()
    report = plateau_report(
        grid, _summaries({"p11": "0.1", "p12": "0.2", "p21": "0.3", "p22": "0.4"})
    )
    assert [p.parameter_set_id for p in report.points] == ["p11", "p12", "p21", "p22"]
    first = report.points[0]
    assert dict(first.metrics) == {"mean_r": "0.1", "closed_trades": "7"}
    assert [(n.axis, n.step, n.parameter_set_id) for n in first.neighbours] == [
        ("axis_a", "upper", "p21"),
        ("axis_b", "upper", "p12"),
    ]
    assert dict(first.neighbours[0].metrics) == {"mean_r": "0.3", "closed_trades": "7"}
    last = report.points[3]
    assert [(n.axis, n.step, n.parameter_set_id) for n in last.neighbours] == [
        ("axis_a", "lower", "p12"),
        ("axis_b", "lower", "p21"),
    ]


def test_plateau_report_orders_an_axis_numerically_not_by_file_order() -> None:
    points = (
        GridPoint("p3", "a" * 64, (("axis_a", "3"),)),
        GridPoint("p1", "a" * 64, (("axis_a", "1"),)),
        GridPoint("p2", "a" * 64, (("axis_a", "2"),)),
    )
    grid = ParameterGrid("trend-pullback", points)
    report = plateau_report(grid, _summaries({"p1": "0", "p2": "0", "p3": "0"}))
    assert [p.parameter_set_id for p in report.points] == ["p3", "p1", "p2"]
    middle = report.points[2]
    assert [(n.step, n.parameter_set_id) for n in middle.neighbours] == [
        ("lower", "p1"),
        ("upper", "p3"),
    ]


def test_plateau_report_refuses_a_missing_point_summary() -> None:
    with pytest.raises(PlateauError):
        plateau_report(_grid_2x2(), _summaries({"p11": "0.1"}))


# --------------------------------------------------------------------------- #
# Test 2: no ranking vocabulary and no metric ordering.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "values",
    [
        {"p11": "0.1", "p12": "0.2", "p21": "0.3", "p22": "0.4"},
        {"p11": "0.4", "p12": "0.3", "p21": "0.2", "p22": "0.1"},
    ],
)
def test_rendered_plateau_has_no_ranking_words_and_keeps_grid_order(
    values: dict[str, str],
) -> None:
    lines = render_plateau(plateau_report(_grid_2x2(), _summaries(values)))
    text = "\n".join(lines).lower()
    for word in FORBIDDEN_WORDS:
        assert word not in text, word
    assert VERDICT_WORDS.search(text) is None, text
    point_lines = [line for line in lines if line.startswith("plateau point ")]
    assert [line.split("parameter_set_id=")[1].split()[0] for line in point_lines] == [
        "p11",
        "p12",
        "p21",
        "p22",
    ]


def test_plateau_report_has_no_marker_order_or_score_field() -> None:
    names: set[str] = set()
    for cls in (
        plateau_module.PlateauReport,
        plateau_module.PlateauPoint,
        plateau_module.AxisNeighbour,
    ):
        names |= {f.name for f in dataclasses.fields(cls)}
    for forbidden in ("best", "rank", "score", "winner", "order", "selected", "verdict"):
        assert not any(forbidden in name for name in names), (forbidden, names)


def test_plateau_module_source_has_no_sort_by_metric() -> None:
    source = Path(plateau_module.__file__).read_text(encoding="utf-8")
    assert ".sort(" not in source
    # The only ordering is of one axis's own parameter values (numeric), never of a metric.
    for line in source.splitlines():
        if "sorted(" in line and not line.lstrip().startswith("#"):
            assert "key=Decimal" in line, line


# --------------------------------------------------------------------------- #
# Test 3: the runner prints the section after feasibility; records are unchanged.
# --------------------------------------------------------------------------- #


def test_run_research_prints_plateau_after_feasibility_and_leaves_records_unchanged(
    store: Path,  # noqa: F811
    tmp_path: Path,
    spies: Any,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _manifest(store, tmp_path)
    grid = _grid()
    out = tmp_path / "experiments"
    records = run_research(
        manifest=manifest,
        grid=grid,
        authorization=_authorization(manifest, grid),
        raw_root=store,
        output_dir=out,
        repo_root=REPO_ROOT,
    )
    lines = capsys.readouterr().out.splitlines()
    g5 = lines.index("G5 floor not assessed (holdout untouched)")
    plateau_at = [i for i, line in enumerate(lines) if line.startswith("plateau ")]
    assert plateau_at and min(plateau_at) > g5
    assert any(line.startswith("plateau point parameter_set_id=baseline-v5") for line in lines)
    assert VERDICT_WORDS.search("\n".join(lines)) is None
    for record in records:
        raw = (out / f"{record.experiment_id}.json").read_text(encoding="utf-8")
        assert raw == research_run._record_text(record)
        assert "plateau" not in json.loads(raw)


def test_render_run_report_puts_feasibility_before_plateau() -> None:
    plateau = plateau_report(
        _grid_2x2(), _summaries({"p11": "0.1", "p12": "0.2", "p21": "0.3", "p22": "0.4"})
    )
    lines = render_run_report(feasibility_lines=["feasibility x", "G5 line"], plateau=plateau)
    assert lines[:2] == ["feasibility x", "G5 line"]
    assert all(line.startswith("plateau") for line in lines[2:])
