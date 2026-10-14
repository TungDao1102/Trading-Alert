"""Research runner entrypoint: `python -m src.research.run` (Phase 16, plan 16-06, D-24, D-25).

Infrastructure only (L-03). An authorized run goes: authorization check, registered
parameter-set check, constraint-file check, dataset-identity check, then for every grid point
and every development / validation-fold window: case input from the published store,
`simulator.run`, `read_code_version`, `experiment.assemble`, one experiment record file named
by its `experiment_id`. The holdout is never simulated here. The runner prints one neutral
line per record (identifiers and a trade count), then the G1 feasibility counts per grid point
(plan 16-12, reporting only), then the parameter-plateau section over the grid (plan 16-18,
reporting only), and no verdict, ranking or selection, and it writes nothing outside the
output directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from time import perf_counter
from typing import Any

from src.adapters.code_version import read_code_version
from src.backtest import simulator
from src.backtest.costs import build_cost_model, cost_slice
from src.backtest.experiment import ExperimentRecord, assemble
from src.data.case_input import ENGINE_SERIES, build_case_input_data
from src.data.minute_source import ParquetMinuteSource
from src.domain.canonical import canonical_decimal_text
from src.domain.registry import load_parameter_set

from .authorization import (
    RunAuthorization,
    RunNotAuthorized,
    load_authorization,
    require_authorized,
)
from .feasibility import G5_NOT_ASSESSED_LINE, feasibility_report, render_feasibility
from .manifest import (
    DatasetManifest,
    GridPoint,
    ManifestError,
    ParameterGrid,
    SplitWindow,
    load_grid,
    load_manifest,
    manifest_hash,
    research_splits,
)
from .plateau import plateau_report
from .report import count_mark_hole_trades, render_run_report, summarize_trades

EXIT_OK = 0
EXIT_REFUSED = 2

_REPO_ROOT = Path(__file__).resolve().parents[2]


class ExperimentAlreadyRecorded(Exception):  # noqa: N818 - the name is the plan's public contract
    """A record for this `experiment_id` already exists: a new iteration is a new registration."""

    def __init__(self, experiment_id: str) -> None:
        self.experiment_id = experiment_id
        super().__init__(f"experiment_already_recorded: {experiment_id}")


_RUN_TYPE = "CANDIDATE"
_CONSTRAINT_KEY = "constraint_history"


def experiment_identity_inputs(manifest: DatasetManifest, dataset_id: str) -> dict[str, str]:
    """The experiment identity inputs derived from the manifest and the case dataset id.

    This is the ONE place the data identity of an experiment is decided. REV-16 is decided as
    route B (16-DEC-REV-16, protocol v2.2.0 section 5, D067): `data_snapshot_id` stays the
    case `dataset_id`, and the seventh identity field `data_manifest_hash` is
    `manifest_hash(manifest)`, the value a run authorization binds as `manifest_sha256`, so a
    record always names the manifest the user authorized.
    """
    return {"data_snapshot_id": dataset_id, "data_manifest_hash": manifest_hash(manifest)}


def _load_constraints(manifest: DatasetManifest) -> list[dict[str, Any]]:
    path = Path(manifest.constraint_source)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ManifestError(f"constraint source unreadable ({type(exc).__name__})") from None
    if hashlib.sha256(raw).hexdigest() != manifest.constraint_sha256:
        raise ManifestError("constraint source bytes do not match the manifest constraint_sha256")
    try:
        loaded = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise ManifestError("constraint source is not valid JSON") from None
    rows = loaded.get(_CONSTRAINT_KEY) if isinstance(loaded, dict) else loaded
    if not isinstance(rows, list):
        raise ManifestError("constraint source must hold a list of rows")
    kept = [r for r in rows if isinstance(r, dict) and r.get("symbol") in manifest.symbols]
    missing = sorted(s for s in manifest.symbols if not any(r["symbol"] == s for r in kept))
    if missing:
        raise ManifestError(f"constraint source has no row for {missing}")
    return kept


def _check_grid_is_registered(grid: ParameterGrid) -> None:
    for point in grid.points:
        loaded = load_parameter_set(grid.strategy_id, point.parameter_set_id)
        if loaded.parameter_set_hash != point.parameter_set_hash:
            raise ManifestError(
                f"parameter_set_hash of {point.parameter_set_id!r} in the grid is not the "
                "registry hash"
            )
        for key, value in point.varied:
            if key not in loaded.params or str(loaded.params[key]) != value:
                raise ManifestError(
                    f"varied value for {key!r} in {point.parameter_set_id!r} is not the "
                    "registered value"
                )


def terminal_settlement_case_rows(
    manifest: DatasetManifest, window: SplitWindow
) -> list[dict[str, str]]:
    """The `terminal_settlements` case rows of one window (design sections 2 and 4).

    A row is emitted only for a window that contains the declared terminal instant T strictly
    inside (`start < T < end`): in a run the Development window. Validation folds and the
    whole-range store check never carry one, and the manifest guard keeps T out of Validation
    and Holdout in the first place. Rows are in symbol order; every value is a string, and the
    bounds are written in canonical decimal text.
    """
    terminals = {g.symbol: g.terminal_at_utc for g in manifest.known_gaps}
    rows: list[dict[str, str]] = []
    for entry in sorted(manifest.terminal_settlements, key=lambda e: e.symbol):
        terminal = terminals[entry.symbol]
        if window.start_utc < terminal < window.end_utc:
            rows.append(
                {
                    "symbol": entry.symbol,
                    "terminal_at_utc": terminal.isoformat(),
                    "price_lower": canonical_decimal_text(entry.price_lower),
                    "price_upper": canonical_decimal_text(entry.price_upper),
                    "kind": entry.kind,
                    "recorded_evaluation": entry.recorded_evaluation,
                }
            )
    return rows


def _check_manifest_against_store(manifest: DatasetManifest, raw_root: Path) -> None:
    if manifest.excluded_periods:
        raise ManifestError(
            "excluded_periods are not supported by the runner: refusing rather than "
            "simulating a window the manifest excludes"
        )
    data = build_case_input_data(
        raw_root,
        symbols=list(manifest.symbols),
        start_utc=manifest.development_start_utc,
        end_utc=manifest.validation_end_utc,
        as_of_day_utc=manifest.validation_end_utc.date(),
        strategy_interval=manifest.strategy_interval,
        context_interval=manifest.context_interval,
        series=ENGINE_SERIES,
        terminal_declarations=manifest.known_gaps,
    )
    if data.dataset_id != manifest.dataset_id:
        raise ManifestError(
            "dataset_id of the published files over the research window is not the "
            "manifest dataset_id"
        )


def _run_split(
    *,
    manifest: DatasetManifest,
    grid: ParameterGrid,
    point: GridPoint,
    window: SplitWindow,
    raw_root: Path,
    constraints: list[dict[str, Any]],
    code_version: Any,
) -> tuple[ExperimentRecord, list[dict[str, Any]]]:
    parameter_set = load_parameter_set(grid.strategy_id, point.parameter_set_id)
    cost_dict = {key: str(value) for key, value in cost_slice(parameter_set.params).items()}
    data = build_case_input_data(
        raw_root,
        symbols=list(manifest.symbols),
        start_utc=window.start_utc,
        end_utc=window.end_utc,
        as_of_day_utc=manifest.validation_end_utc.date(),
        strategy_interval=manifest.strategy_interval,
        context_interval=manifest.context_interval,
        series=ENGINE_SERIES,
        terminal_declarations=manifest.known_gaps,
    )
    settlement_rows = terminal_settlement_case_rows(manifest, window)
    optional_keys: dict[str, Any] = (
        {"terminal_settlements": settlement_rows} if settlement_rows else {}
    )
    case = data.to_case_input(
        strategy_id=grid.strategy_id,
        strategy_version=parameter_set.strategy_version,
        parameter_set_id=point.parameter_set_id,
        account_state={"equity": str(manifest.equity), "risk_rate": str(manifest.risk_rate)},
        cost_model=cost_dict,
        constraint_history=constraints,
        **optional_keys,
    )
    source = ParquetMinuteSource(
        raw_root,
        symbols=list(manifest.symbols),
        start_utc=window.start_utc,
        end_utc=window.end_utc,
    )
    output = simulator.run(case, minute_source=source)
    identity = experiment_identity_inputs(manifest, data.dataset_id)
    record = assemble(
        parameter_set_id=point.parameter_set_id,
        strategy_id=grid.strategy_id,
        strategy_version=parameter_set.strategy_version,
        code_version=code_version,
        cost_model=build_cost_model(cost_dict),
        time_range_start_utc=window.start_utc,
        time_range_end_utc=window.end_utc,
        universe=list(manifest.symbols),
        run_type=_RUN_TYPE,
        run_summary=output["run_summary"],
        run_identity=output,
        split_role=window.role,
        split_start_utc=window.start_utc,
        split_end_utc=window.end_utc,
        **identity,
    )
    return record, list(output["trades"])


def _record_text(record: ExperimentRecord) -> str:
    return json.dumps(
        record.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def run_research(
    *,
    manifest: DatasetManifest,
    grid: ParameterGrid,
    authorization: RunAuthorization | None,
    raw_root: Path,
    output_dir: Path,
    repo_root: Path,
    time_run: bool = False,
) -> tuple[ExperimentRecord, ...]:
    """Run the authorized manifest and grid over the development and validation windows.

    Every refusal (authorization, registry hash, constraint file, dataset identity) happens
    before any simulation. An `experiment_id` is only known once `assemble` has built the
    record, so the rerun check (`ExperimentAlreadyRecorded`) runs right after each window is
    assembled and again over all records before the first write: a rerun stops at its first
    window and writes nothing. Records are written only after every window has run, each to
    `<experiment_id>.json` created exclusively (an existing file is never overwritten).

    `time_run` (D-30, G4-009) adds one `timing` line per split to the run log: wall seconds from
    `perf_counter`, never written into a record, so identity and digests do not move. No
    memory tracing is started.
    """
    require_authorized(authorization, manifest=manifest, grid=grid)
    _check_grid_is_registered(grid)
    constraints = _load_constraints(manifest)
    _check_manifest_against_store(manifest, raw_root)

    code_version = read_code_version(repo_root)
    records: list[ExperimentRecord] = []
    trade_lists: list[list[dict[str, Any]]] = []
    timing_lines: list[str] = []
    for point in grid.points:
        for window in research_splits(manifest):
            started = perf_counter()
            record, trade_list = _run_split(
                manifest=manifest,
                grid=grid,
                point=point,
                window=window,
                raw_root=raw_root,
                constraints=constraints,
                code_version=code_version,
            )
            elapsed = perf_counter() - started
            if time_run:
                timing_lines.append(
                    f"timing parameter_set_id={point.parameter_set_id} "
                    f"split_role={window.role} split_start_utc={window.start_utc.isoformat()} "
                    f"wall_seconds={elapsed:.3f}"
                )
            _refuse_if_recorded(output_dir, record)
            records.append(record)
            trade_lists.append(trade_list)

    report_lines = render_run_report(
        feasibility_lines=_feasibility_lines(manifest, grid, records, trade_lists),
        plateau=plateau_report(grid, _plateau_summaries(manifest, grid, records, trade_lists)),
        mark_hole_trade_counts=_mark_hole_counts(manifest, grid, trade_lists),
    )
    for record in records:
        _refuse_if_recorded(output_dir, record)
    output_dir.mkdir(parents=True, exist_ok=True)
    for record, trade_list in zip(records, trade_lists, strict=True):
        try:
            with (output_dir / f"{record.experiment_id}.json").open(
                "x", encoding="utf-8"
            ) as handle:
                handle.write(_record_text(record))
        except FileExistsError:
            raise ExperimentAlreadyRecorded(record.experiment_id) from None
        print(
            f"recorded experiment_id={record.experiment_id} "
            f"parameter_set_id={record.parameter_set_id} split_role={record.split_role} "
            f"split_start_utc={record.split_start_utc.isoformat()} trades={len(trade_list)}",
            flush=True,
        )
    for line in [*report_lines, *timing_lines]:
        print(line, flush=True)
    return tuple(records)


def _mark_hole_counts(
    manifest: DatasetManifest,
    grid: ParameterGrid,
    trade_lists: Sequence[Sequence[Mapping[str, Any]]],
) -> dict[str, int]:
    """Filled trades held through mark-price holes per grid point (OQ-1, D-29): a bare count
    over every simulated window of the point, never classified and never part of a record."""
    per_point = len(research_splits(manifest))
    return {
        point.parameter_set_id: count_mark_hole_trades(
            [
                t
                for trades in trade_lists[index * per_point : (index + 1) * per_point]
                for t in trades
            ]
        )
        for index, point in enumerate(grid.points)
    }


def _plateau_summaries(
    manifest: DatasetManifest,
    grid: ParameterGrid,
    records: Sequence[ExperimentRecord],
    trade_lists: Sequence[Sequence[Mapping[str, Any]]],
) -> dict[str, dict[str, object]]:
    """Existing report figures per grid point over its pooled Validation trades (D-27).

    Reporting only: the figures come from `src.backtest.report.build` unchanged and never enter
    a record. A point owns one consecutive block of records (see `_feasibility_lines`).
    """
    per_point = len(research_splits(manifest))
    summaries: dict[str, dict[str, object]] = {}
    for index, point in enumerate(grid.points):
        validation = [
            i
            for i in range(index * per_point, (index + 1) * per_point)
            if records[i].split_role == "VALIDATION"
        ]
        summaries[point.parameter_set_id] = summarize_trades(
            experiment_record=records[validation[0]],
            trade_records=[t for i in validation for t in trade_lists[i]],
            built_at_utc=manifest.validation_end_utc,
        )
    return summaries


def _feasibility_lines(
    manifest: DatasetManifest,
    grid: ParameterGrid,
    records: Sequence[ExperimentRecord],
    trade_lists: Sequence[Sequence[Mapping[str, Any]]],
) -> list[str]:
    """G1 feasibility counts per grid point (D-26): reporting only, never part of a record.

    Records are in grid-point order, `research_splits` order within a point, so a point owns
    one consecutive block; its Validation folds are the VALIDATION entries of that block.
    """
    per_point = len(research_splits(manifest))
    lines: list[str] = []
    for index, point in enumerate(grid.points):
        block = range(index * per_point, (index + 1) * per_point)
        folds = [trade_lists[i] for i in block if records[i].split_role == "VALIDATION"]
        development = [
            t for i in block if records[i].split_role == "DEVELOPMENT" for t in trade_lists[i]
        ]
        lines.extend(
            render_feasibility(
                feasibility_report(
                    folds,
                    parameter_set_id=point.parameter_set_id,
                    development_trades=development,
                )
            )
        )
    lines.append(G5_NOT_ASSESSED_LINE)
    return lines


def _refuse_if_recorded(output_dir: Path, record: ExperimentRecord) -> None:
    if (output_dir / f"{record.experiment_id}.json").exists():
        raise ExperimentAlreadyRecorded(record.experiment_id)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.research.run",
        allow_abbrev=False,
        description=(
            "Run an authorized research experiment (infrastructure only: no verdict, no "
            "ranking, no selection). The only accepted authorization form is a "
            "user-committed JSON file (checkpoint O-03a, option a)."
        ),
    )
    parser.add_argument("--manifest", type=Path, required=True, help="dataset manifest JSON")
    parser.add_argument("--grid", type=Path, required=True, help="parameter grid JSON")
    parser.add_argument(
        "--authorization",
        type=Path,
        default=None,
        help="user-committed authorization JSON (grid_sha256, manifest_sha256, "
        "authorized_at_utc, statement, authorized_by)",
    )
    parser.add_argument("--raw-root", type=Path, required=True, help="published data root")
    parser.add_argument("--output-dir", type=Path, required=True, help="experiment record dir")
    parser.add_argument("--repo-root", type=Path, default=_REPO_ROOT, help="git repository root")
    parser.add_argument(
        "--time-run",
        action="store_true",
        help="print wall-clock seconds per split in the run log (no memory tracing; records "
        "are unchanged)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entrypoint: refuse (exit 2, cause on stderr) unless the authorization file binds the
    grid and manifest hashes of the files re-read from disk right now (REV-04, REV-05).
    """
    args = _parser().parse_args(argv)
    try:
        authorization = (
            load_authorization(args.authorization) if args.authorization is not None else None
        )
        manifest = load_manifest(args.manifest)
        grid = load_grid(args.grid)
        run_research(
            manifest=manifest,
            grid=grid,
            authorization=authorization,
            raw_root=args.raw_root,
            output_dir=args.output_dir,
            repo_root=args.repo_root,
            time_run=args.time_run,
        )
    except RunNotAuthorized as exc:
        print(f"run refused: {exc.reason}", file=sys.stderr)
        return EXIT_REFUSED
    except ManifestError as exc:
        print(f"run refused: manifest_or_grid_invalid: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except ExperimentAlreadyRecorded as exc:
        print(f"run refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
