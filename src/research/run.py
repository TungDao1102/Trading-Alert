"""Research runner entrypoint: `python -m src.research.run` (Phase 16, plan 16-06, D-24, D-25).

Infrastructure only (L-03). An authorized run goes: authorization check, registered
parameter-set check, constraint-file check, terminal-settlement evidence check (quick
261014-nnl: the stored bounds are recomputed from the committed evidence bytes, a mismatch
refuses), dataset-identity check, then for every grid point
and every development / validation-fold window: case input from the published store,
`simulator.run`, `read_code_version`, `experiment.assemble`, one experiment record file named
by its `experiment_id`. The holdout is never simulated here. The runner prints one neutral
line per record (identifiers; a trade count unless `--checkpoint-dir` is given, which prints
`recorded` or `present` lines instead), then the G1 feasibility counts per grid point
(plan 16-12, reporting only), then the parameter-plateau section over the grid (plan 16-18,
reporting only), and no verdict, ranking or selection. It writes nothing outside the output
directory, except the window files of `--checkpoint-dir` when that option is given.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath, PureWindowsPath
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
    EvidenceFile,
    GridPoint,
    ManifestError,
    ParameterGrid,
    SplitWindow,
    grid_hash,
    load_grid,
    load_manifest,
    manifest_hash,
    research_splits,
)
from .plateau import plateau_report
from .report import count_mark_hole_trades, render_run_report, summarize_trades
from .settlement_evidence import SettlementEvidenceError, recompute_settlement_bounds

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


# A grid label that stands for several registered parameters set to the same value.
_VARIED_ALIASES = {"pivot_bars": ("pivot_left_bars", "pivot_right_bars")}


def _varied_value_is_registered(params: Mapping[str, Any], key: str, value: str) -> bool:
    """True when every registered parameter behind `key` equals `value` numerically.

    The grid writes values as text (`"1.0"`) and the registry loads TOML numbers (`1`), so
    the comparison is by number, not by spelling. `pivot_bars` is the grid label for the
    left and right pivot widths, which the registered sets keep equal.
    """
    names = _VARIED_ALIASES.get(key, (key,))
    for name in names:
        if name not in params:
            return False
        try:
            if Decimal(str(params[name])) != Decimal(value):
                return False
        except InvalidOperation:
            if str(params[name]) != value:
                return False
    return True


def _check_grid_is_registered(grid: ParameterGrid) -> None:
    for point in grid.points:
        loaded = load_parameter_set(grid.strategy_id, point.parameter_set_id)
        if loaded.parameter_set_hash != point.parameter_set_hash:
            raise ManifestError(
                f"parameter_set_hash of {point.parameter_set_id!r} in the grid is not the "
                "registry hash"
            )
        for key, value in point.varied:
            if not _varied_value_is_registered(loaded.params, key, value):
                raise ManifestError(
                    f"varied value for {key!r} in {point.parameter_set_id!r} is not the "
                    "registered value"
                )


def _evidence_bytes(repo_root: Path, evidence: EvidenceFile, label: str) -> bytes:
    """The bytes of one committed evidence file, confined to `repo_root` and sha256-checked.

    Messages name the field (`label`) only; file content is never echoed.
    """
    root = repo_root.resolve()
    target = (root / evidence.path).resolve()
    rooted_elsewhere = (
        PurePosixPath(evidence.path).is_absolute()
        or PureWindowsPath(evidence.path).is_absolute()
        or PureWindowsPath(evidence.path).drive != ""
    )
    if rooted_elsewhere or not target.is_relative_to(root):
        raise ManifestError(f"{label} path resolves outside the repository root")
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise ManifestError(f"{label} file unreadable ({type(exc).__name__})") from None
    if hashlib.sha256(raw).hexdigest() != evidence.sha256:
        raise ManifestError(f"{label} bytes do not match the manifest sha256")
    return raw


def check_terminal_settlement_evidence(manifest: DatasetManifest, repo_root: Path) -> None:
    """Recompute every stored settlement bound from the committed evidence; refuse a mismatch.

    For each `terminal_settlements` entry (design section 2): resolve each evidence path under
    `repo_root` (a path that resolves outside it is refused), compare the sha256 of the bytes of
    the index klines, the trade kline and every supporting file, recompute the nominal bounds,
    the tick-widened index bounds, the trade candle and the union over [bound_window_start_utc,
    T) with the stored tick, and compare the nominal fractions and all six Decimals with the
    entry. Any difference raises `ManifestError` naming the field. A manifest without entries
    passes without reading anything. Runs before any simulation.
    """
    terminals = {g.symbol: g.terminal_at_utc for g in manifest.known_gaps}
    for entry in manifest.terminal_settlements:
        label = f"terminal settlement {entry.symbol}"
        index_raw = _evidence_bytes(repo_root, entry.index_klines, f"{label} index_klines")
        trade_raw = _evidence_bytes(repo_root, entry.trade_kline, f"{label} trade_kline")
        for position, support in enumerate(entry.supporting_evidence):
            _evidence_bytes(repo_root, support, f"{label} supporting_evidence[{position}]")
        try:
            recomputed = recompute_settlement_bounds(
                index_klines=index_raw,
                trade_kline=trade_raw,
                window_start_utc=entry.bound_window_start_utc,
                terminal_at_utc=terminals[entry.symbol],
                tick=entry.price_tick_size,
            )
        except SettlementEvidenceError as exc:
            raise ManifestError(
                f"{label}: the committed evidence does not recompute: {exc}"
            ) from None
        nominal_lower, nominal_upper = entry.nominal_bounds()
        for name, expected, stored in (
            ("nominal_lower", recomputed.nominal_lower, nominal_lower),
            ("nominal_upper", recomputed.nominal_upper, nominal_upper),
            ("index_lower", recomputed.index_lower, entry.index_lower),
            ("index_upper", recomputed.index_upper, entry.index_upper),
            ("trade_candle_low", recomputed.trade_low, entry.trade_candle_low),
            ("trade_candle_high", recomputed.trade_high, entry.trade_candle_high),
            ("price_lower", recomputed.price_lower, entry.price_lower),
            ("price_upper", recomputed.price_upper, entry.price_upper),
        ):
            if expected != stored:
                raise ManifestError(
                    f"{label} {name} does not match the value recomputed from the evidence"
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


def _simulate_split(
    *,
    manifest: DatasetManifest,
    grid: ParameterGrid,
    point: GridPoint,
    window: SplitWindow,
    raw_root: Path,
    constraints: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """The heavy part of one window: the case from the published store and the simulator output.

    Returns the case `dataset_id` and the engine output; `_assemble_split` turns them into the
    experiment record.
    """
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
    return data.dataset_id, simulator.run(case, minute_source=source)


def _assemble_split(
    *,
    manifest: DatasetManifest,
    grid: ParameterGrid,
    point: GridPoint,
    window: SplitWindow,
    code_version: Any,
    dataset_id: str,
    output: dict[str, Any],
) -> tuple[ExperimentRecord, list[dict[str, Any]]]:
    """The cheap part of one window: the experiment record built from a simulator output."""
    parameter_set = load_parameter_set(grid.strategy_id, point.parameter_set_id)
    cost_dict = {key: str(value) for key, value in cost_slice(parameter_set.params).items()}
    identity = experiment_identity_inputs(manifest, dataset_id)
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
    dataset_id, output = _simulate_split(
        manifest=manifest,
        grid=grid,
        point=point,
        window=window,
        raw_root=raw_root,
        constraints=constraints,
    )
    return _assemble_split(
        manifest=manifest,
        grid=grid,
        point=point,
        window=window,
        code_version=code_version,
        dataset_id=dataset_id,
        output=output,
    )


def _record_text(record: ExperimentRecord) -> str:
    return json.dumps(
        record.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


class CheckpointInvalid(ValueError):
    """A checkpoint file does not belong to this run or is damaged (the run stops, no overwrite)."""


_CHECKPOINT_SCHEMA = "research-checkpoint/1"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def _checkpoint_file(checkpoint_dir: Path, point: GridPoint, window: SplitWindow) -> Path:
    stamp = window.start_utc.strftime("%Y%m%dT%H%M%SZ")
    return checkpoint_dir / f"{point.parameter_set_id}.{window.role}.{stamp}.json"


def _checkpoint_header(
    *, run_key: Mapping[str, str], point: GridPoint, window: SplitWindow
) -> dict[str, str]:
    return {
        "schema": _CHECKPOINT_SCHEMA,
        **run_key,
        "parameter_set_id": point.parameter_set_id,
        "split_role": window.role,
        "split_start_utc": window.start_utc.isoformat(),
        "split_end_utc": window.end_utc.isoformat(),
    }


def _write_checkpoint(
    path: Path,
    *,
    header: Mapping[str, str],
    dataset_id: str,
    output: dict[str, Any],
) -> None:
    """Save one simulated window (temporary file, then replace: no half-written checkpoint)."""
    body = {"dataset_id": dataset_id, "output": output}
    try:
        body_text = _canonical_json(body)
    except (TypeError, ValueError):
        raise CheckpointInvalid("the simulator output is not plain JSON data") from None
    if json.loads(body_text) != body:
        raise CheckpointInvalid("the simulator output does not survive a JSON round trip")
    payload = {
        **header,
        "body_sha256": hashlib.sha256(body_text.encode("ascii")).hexdigest(),
        "body": body,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(_canonical_json(payload), encoding="ascii", newline="\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_checkpoint(path: Path, *, header: Mapping[str, str]) -> tuple[str, dict[str, Any]]:
    """Read a checkpoint written by this run; anything else stops the run."""
    try:
        payload = json.loads(path.read_text(encoding="ascii"))
    except (OSError, ValueError):
        raise CheckpointInvalid(f"{path.name}: unreadable or not valid JSON") from None
    if not isinstance(payload, dict):
        raise CheckpointInvalid(f"{path.name}: not a JSON object")
    body = payload.get("body")
    if not isinstance(body, dict) or set(payload) != {*header, "body_sha256", "body"}:
        raise CheckpointInvalid(f"{path.name}: unexpected structure")
    for key, expected in header.items():
        if payload.get(key) != expected:
            raise CheckpointInvalid(f"{path.name}: {key} is not this run's value")
    body_text = _canonical_json(body)
    if hashlib.sha256(body_text.encode("ascii")).hexdigest() != payload["body_sha256"]:
        raise CheckpointInvalid(f"{path.name}: the content does not match its hash")
    dataset_id, output = body.get("dataset_id"), body.get("output")
    if not isinstance(dataset_id, str) or not isinstance(output, dict):
        raise CheckpointInvalid(f"{path.name}: unexpected body")
    return dataset_id, output


def _create_exclusive(path: Path, text: str) -> bool:
    """Create `path` with `text` all at once; False when the file already exists.

    The text goes to a temporary file first and is then hard-linked to the final name, which
    fails if the name exists, so an interrupted write never leaves a truncated record.
    """
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(text)
        try:
            os.link(temporary, path)
        except FileExistsError:
            return False
        return True
    finally:
        temporary.unlink(missing_ok=True)


def _code_paths_dirty(repo_root: Path) -> list[str]:
    """Uncommitted or untracked files under the code and parameter directories."""
    result = subprocess.run(  # noqa: S603 - fixed argument list, no shell
        ["git", "status", "--porcelain", "--", "src", "params"],  # noqa: S607
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _write_point_records(output_dir: Path, records: Sequence[ExperimentRecord]) -> None:
    """Save one grid point's records; a file that already exists must hold the same record."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        path = output_dir / f"{record.experiment_id}.json"
        text = _record_text(record)
        if _create_exclusive(path, text):
            state = "recorded"
        else:
            if path.read_text(encoding="utf-8") != text:
                raise ExperimentAlreadyRecorded(
                    f"{record.experiment_id} (the file differs from the record built now; "
                    "if it is truncated or not valid JSON after an interrupted write, delete "
                    "that one file and rerun)"
                ) from None
            state = "present"
        print(
            f"{state} experiment_id={record.experiment_id} "
            f"parameter_set_id={record.parameter_set_id} split_role={record.split_role} "
            f"split_start_utc={record.split_start_utc.isoformat()}",
            flush=True,
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
    checkpoint_dir: Path | None = None,
) -> tuple[ExperimentRecord, ...]:
    """Run the authorized manifest and grid over the development and validation windows.

    Without `checkpoint_dir`: every refusal (authorization, registry hash, constraint file,
    terminal-settlement evidence, dataset identity) happens before any simulation. An
    `experiment_id` is only known once
    `assemble` has built the record, so the rerun check (`ExperimentAlreadyRecorded`) runs
    right after each window is assembled and again over all records before the first write: a
    rerun stops at its first window and writes nothing. Records are written only after every
    window has run, each to `<experiment_id>.json` created exclusively (an existing file is
    never overwritten).

    With `checkpoint_dir` the run is resumable and keeps its results as it goes: every simulated
    window is saved to the checkpoint directory (which must not be the output directory), a
    grid point's records are written as soon as its windows are done, and a rerun with the same
    directory reuses the saved windows instead of simulating them again. A saved window is
    accepted only for the same manifest hash, grid hash, code version, parameter set and window,
    and only when its content matches its hash. A record file that already exists must be
    byte-equal to the record built now, otherwise the run stops with `ExperimentAlreadyRecorded`.
    The records, their ids and the report are the same as without a checkpoint directory.

    `time_run` (D-30, G4-009) adds one `timing` line per split to the run log: wall seconds from
    `perf_counter`, never written into a record, so identity and digests do not move. No
    memory tracing is started.
    """
    require_authorized(authorization, manifest=manifest, grid=grid)
    _check_grid_is_registered(grid)
    constraints = _load_constraints(manifest)
    check_terminal_settlement_evidence(manifest, repo_root)
    _check_manifest_against_store(manifest, raw_root)
    if checkpoint_dir is not None:
        ck, out = checkpoint_dir.resolve(), output_dir.resolve()
        if ck == out or ck in out.parents or out in ck.parents:
            raise CheckpointInvalid(
                "the checkpoint directory must not be the output directory or nested with it"
            )

    if checkpoint_dir is not None and (dirty_code := _code_paths_dirty(repo_root)):
        raise CheckpointInvalid(
            "src or params has uncommitted changes, so saved windows could mix code versions: "
            + "; ".join(dirty_code[:5])
        )
    code_version = read_code_version(repo_root)
    run_key = {
        "manifest_sha256": manifest_hash(manifest),
        "grid_sha256": grid_hash(grid),
        "code_version": (
            f"{code_version.commit}-dirty" if code_version.dirty else code_version.commit
        ),
    }
    records: list[ExperimentRecord] = []
    trade_lists: list[list[dict[str, Any]]] = []
    timing_lines: list[str] = []
    for point in grid.points:
        point_records: list[ExperimentRecord] = []
        for window in research_splits(manifest):
            started = perf_counter()
            reused = False
            if checkpoint_dir is None:
                record, trade_list = _run_split(
                    manifest=manifest,
                    grid=grid,
                    point=point,
                    window=window,
                    raw_root=raw_root,
                    constraints=constraints,
                    code_version=code_version,
                )
            else:
                path = _checkpoint_file(checkpoint_dir, point, window)
                header = _checkpoint_header(run_key=run_key, point=point, window=window)
                if path.exists():
                    dataset_id, output = _load_checkpoint(path, header=header)
                    reused = True
                else:
                    dataset_id, output = _simulate_split(
                        manifest=manifest,
                        grid=grid,
                        point=point,
                        window=window,
                        raw_root=raw_root,
                        constraints=constraints,
                    )
                    _write_checkpoint(path, header=header, dataset_id=dataset_id, output=output)
                record, trade_list = _assemble_split(
                    manifest=manifest,
                    grid=grid,
                    point=point,
                    window=window,
                    code_version=code_version,
                    dataset_id=dataset_id,
                    output=output,
                )
            elapsed = perf_counter() - started
            if time_run:
                timing_lines.append(
                    f"timing parameter_set_id={point.parameter_set_id} "
                    f"split_role={window.role} split_start_utc={window.start_utc.isoformat()} "
                    f"wall_seconds={elapsed:.3f}" + (" checkpoint=reused" if reused else "")
                )
            if checkpoint_dir is None:
                _refuse_if_recorded(output_dir, record)
            records.append(record)
            point_records.append(record)
            trade_lists.append(trade_list)
        if checkpoint_dir is not None:
            _write_point_records(output_dir, point_records)

    report_lines = render_run_report(
        feasibility_lines=_feasibility_lines(manifest, grid, records, trade_lists),
        plateau=plateau_report(grid, _plateau_summaries(manifest, grid, records, trade_lists)),
        mark_hole_trade_counts=_mark_hole_counts(manifest, grid, trade_lists),
    )
    if checkpoint_dir is None:
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
        "--checkpoint-dir",
        type=Path,
        default=None,
        help="keep each simulated window here and write a grid point's records as soon as it "
        "is done; a rerun with the same directory reuses the saved windows (resume). Not the "
        "output directory; keep it outside the repository",
    )
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
            checkpoint_dir=args.checkpoint_dir,
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
    except CheckpointInvalid as exc:
        print(f"run refused: checkpoint_invalid: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
