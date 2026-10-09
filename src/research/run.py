"""Research runner entrypoint: `python -m src.research.run` (Phase 16, plan 16-06, D-24, D-25).

Infrastructure only (L-03). An authorized run goes: authorization check, registered
parameter-set check, constraint-file check, dataset-identity check, then for every grid point
and every development / validation-fold window: case input from the published store,
`simulator.run`, `read_code_version`, `experiment.assemble`, one experiment record file named
by its `experiment_id`. The holdout is never simulated here. The runner prints one neutral
line per record (identifiers and a trade count) and no verdict, ranking or selection, and it
writes nothing outside the output directory.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from src.adapters.code_version import read_code_version
from src.backtest import simulator
from src.backtest.costs import build_cost_model, cost_slice
from src.backtest.experiment import ExperimentRecord, assemble
from src.data.case_input import ENGINE_SERIES, build_case_input_data
from src.data.minute_source import ParquetMinuteSource
from src.domain.registry import load_parameter_set

from .authorization import RunAuthorization, require_authorized
from .manifest import (
    DatasetManifest,
    GridPoint,
    ManifestError,
    ParameterGrid,
    SplitWindow,
    research_splits,
)

EXIT_OK = 0
EXIT_REFUSED = 2

_RUN_TYPE = "CANDIDATE"
_CONSTRAINT_KEY = "constraint_history"


def experiment_identity_inputs(manifest: DatasetManifest, dataset_id: str) -> dict[str, str]:
    """The experiment identity inputs derived from the manifest and the case dataset id.

    This is the ONE place the data identity of an experiment is decided (REV-16 is open: the
    frozen-manifest identity may later become `data_snapshot_id` or a seventh field, an edit
    made here only). Today `data_snapshot_id` is the case `dataset_id`, unchanged.
    """
    return {"data_snapshot_id": dataset_id}


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
        allow_gaps=manifest.known_gaps,
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
) -> ExperimentRecord:
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
        allow_gaps=manifest.known_gaps,
    )
    case = data.to_case_input(
        strategy_id=grid.strategy_id,
        strategy_version=parameter_set.strategy_version,
        parameter_set_id=point.parameter_set_id,
        account_state={"equity": str(manifest.equity), "risk_rate": str(manifest.risk_rate)},
        cost_model=cost_dict,
        constraint_history=constraints,
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
    print(
        f"recorded experiment_id={record.experiment_id} "
        f"parameter_set_id={point.parameter_set_id} split_role={window.role} "
        f"split_start_utc={window.start_utc.isoformat()} trades={len(output['trades'])}",
        flush=True,
    )
    return record


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
) -> tuple[ExperimentRecord, ...]:
    """Run the authorized manifest and grid over the development and validation windows.

    Every refusal (authorization, registry hash, constraint file, dataset identity) happens
    before any simulation. Records are written only after every window has run, each to
    `<experiment_id>.json` created exclusively (an existing file is never overwritten).
    """
    require_authorized(authorization, manifest=manifest, grid=grid)
    _check_grid_is_registered(grid)
    constraints = _load_constraints(manifest)
    _check_manifest_against_store(manifest, raw_root)

    code_version = read_code_version(repo_root)
    records: list[ExperimentRecord] = []
    for point in grid.points:
        for window in research_splits(manifest):
            records.append(
                _run_split(
                    manifest=manifest,
                    grid=grid,
                    point=point,
                    window=window,
                    raw_root=raw_root,
                    constraints=constraints,
                    code_version=code_version,
                )
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        with (output_dir / f"{record.experiment_id}.json").open("x", encoding="utf-8") as handle:
            handle.write(_record_text(record))
    return tuple(records)


def main(argv: Sequence[str] | None = None) -> int:
    """Entrypoint. The authorization input form is chosen by the user at checkpoint O-03a.

    Until that form is implemented, no command line can authorize a run, so every invocation
    is refused (fail closed).
    """
    del argv
    print(
        "run refused: no authorization input form is implemented (checkpoint O-03a pending)",
        file=sys.stderr,
    )
    return EXIT_REFUSED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
