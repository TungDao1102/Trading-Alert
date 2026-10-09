"""Parameter-plateau report over the preregistered grid (Phase 16, plan 16-18, D-27; BKTS-03).

Reporting only (L-03; protocol R2: prefer plateau behaviour over a point optimum). For every
grid point, in grid-file order, it shows that point's existing report metrics beside the same
metrics of its one-step neighbours along each varied axis. It defines no metric: the values are
whatever the caller took from the existing backtest report builders. It never marks a point,
never orders points by a value and never chooses one; a reader looks at the shape.

Neighbours: a point's neighbour along axis K is the grid point that agrees with it on every
other varied key and holds the next lower or next higher value of K. The values of one axis are
ordered numerically when they all parse as decimals, otherwise by first appearance in the grid
file; that is an ordering of parameter values, never of results.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .manifest import GridPoint, ParameterGrid

_STEP_LOWER = "lower"
_STEP_UPPER = "upper"
_ABSENT = "n/a"


class PlateauError(Exception):
    """The plateau input is incomplete: a grid point has no metric summary."""


MetricPairs = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class AxisNeighbour:
    """The metrics of the one-step neighbour of a point along one axis."""

    axis: str
    step: str
    parameter_set_id: str
    value: str
    metrics: MetricPairs


@dataclass(frozen=True)
class PlateauPoint:
    """One grid point, its metrics and its neighbours (in axis order, lower before upper)."""

    parameter_set_id: str
    varied: tuple[tuple[str, str], ...]
    metrics: MetricPairs
    neighbours: tuple[AxisNeighbour, ...]


@dataclass(frozen=True)
class PlateauReport:
    """The points in grid-file order. Holds no marker, ordering or verdict."""

    points: tuple[PlateauPoint, ...]


def _render_value(value: object) -> str:
    if value is None:
        return _ABSENT
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _metric_pairs(metrics: Mapping[str, object]) -> MetricPairs:
    return tuple((name, _render_value(value)) for name, value in metrics.items())


def _axis_values(grid: ParameterGrid, point: GridPoint, axis: str) -> list[str]:
    """Distinct values of `axis` over the points that differ from `point` on `axis` only."""
    keys = tuple(key for key, _ in point.varied)
    others = {key: value for key, value in point.varied if key != axis}
    distinct: list[str] = []
    for other in grid.points:
        if tuple(key for key, _ in other.varied) != keys:
            continue
        values = dict(other.varied)
        if any(values[key] != value for key, value in others.items()):
            continue
        if values[axis] not in distinct:
            distinct.append(values[axis])
    try:
        return sorted(distinct, key=Decimal)
    except InvalidOperation:
        return distinct


def _find(grid: ParameterGrid, point: GridPoint, axis: str, value: str) -> GridPoint:
    wanted = {key: val for key, val in point.varied if key != axis}
    wanted[axis] = value
    keys = tuple(key for key, _ in point.varied)
    for other in grid.points:
        if tuple(key for key, _ in other.varied) == keys and dict(other.varied) == wanted:
            return other
    raise PlateauError(f"no grid point holds {axis}={value}")  # pragma: no cover - built from grid


def plateau_report(
    grid: ParameterGrid, summaries_by_point: Mapping[str, Mapping[str, object]]
) -> PlateauReport:
    """Each grid point (grid-file order) with its one-step axis neighbours' metrics."""
    for point in grid.points:
        if point.parameter_set_id not in summaries_by_point:
            raise PlateauError(f"no metric summary for {point.parameter_set_id!r}")
    points: list[PlateauPoint] = []
    for point in grid.points:
        neighbours: list[AxisNeighbour] = []
        for axis, current in point.varied:
            values = _axis_values(grid, point, axis)
            index = values.index(current)
            for step, at in ((_STEP_LOWER, index - 1), (_STEP_UPPER, index + 1)):
                if at < 0 or at >= len(values):
                    continue
                other = _find(grid, point, axis, values[at])
                neighbours.append(
                    AxisNeighbour(
                        axis=axis,
                        step=step,
                        parameter_set_id=other.parameter_set_id,
                        value=values[at],
                        metrics=_metric_pairs(summaries_by_point[other.parameter_set_id]),
                    )
                )
        points.append(
            PlateauPoint(
                parameter_set_id=point.parameter_set_id,
                varied=point.varied,
                metrics=_metric_pairs(summaries_by_point[point.parameter_set_id]),
                neighbours=tuple(neighbours),
            )
        )
    return PlateauReport(points=tuple(points))


def _metrics_text(metrics: Sequence[tuple[str, str]]) -> str:
    return " ".join(f"{name}={value}" for name, value in metrics)


def render_plateau(report: PlateauReport) -> list[str]:
    """Neutral lines in grid-file order: no marker, no ordering by a value, no verdict wording."""
    lines = [
        "plateau section: reporting only; points in grid-file order, each beside its one-step "
        "neighbours along every varied axis"
    ]
    for point in report.points:
        varied = ",".join(f"{key}={value}" for key, value in point.varied)
        lines.append(
            f"plateau point parameter_set_id={point.parameter_set_id} varied={varied} "
            f"{_metrics_text(point.metrics)}"
        )
        if not point.neighbours:
            lines.append(f"plateau neighbours of={point.parameter_set_id} none")
        for neighbour in point.neighbours:
            lines.append(
                f"plateau neighbour of={point.parameter_set_id} axis={neighbour.axis} "
                f"step={neighbour.step} parameter_set_id={neighbour.parameter_set_id} "
                f"value={neighbour.value} {_metrics_text(neighbour.metrics)}"
            )
    return lines


__all__ = [
    "AxisNeighbour",
    "PlateauError",
    "PlateauPoint",
    "PlateauReport",
    "plateau_report",
    "render_plateau",
]
