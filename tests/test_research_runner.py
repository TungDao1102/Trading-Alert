"""Tests for the research runner (Phase 16, plan 16-06, D-24, D-25, REV-04..REV-06).

Every run reads a synthetic published store built in tmp_path through the real
publishers (the same builder as tests/test_case_input_builder.py); nothing touches the
network, a database or the real data root.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.backtest import simulator
from src.backtest.experiment import CodeVersion
from src.data.case_input import ENGINE_SERIES, build_case_input_data
from src.research import run as research_run
from src.research.authorization import (
    RunAuthorization,
    RunNotAuthorized,
    load_authorization,
    require_authorized,
)
from src.research.manifest import (
    DatasetManifest,
    GridPoint,
    ManifestError,
    ParameterGrid,
    grid_hash,
    load_grid,
    load_manifest,
    manifest_hash,
    research_splits,
)
from src.research.run import ExperimentAlreadyRecorded, main, run_research

from tests.backtest_case_helpers import constraint_row
from tests.test_case_input_builder import build_store

REPO_ROOT = Path(__file__).resolve().parents[1]
SYMBOL = "BTCUSDT"
STORE_START = datetime(2026, 7, 1, tzinfo=UTC)
STORE_END = datetime(2026, 7, 11, tzinfo=UTC)
DEV_START = datetime(2026, 7, 1, tzinfo=UTC)
DEV_END = datetime(2026, 7, 5, tzinfo=UTC)
VAL_START = DEV_END
VAL_END = datetime(2026, 7, 9, tzinfo=UTC)
HOLD_START = VAL_END
HOLD_END = STORE_END
FAKE_COMMIT = "a" * 40
VERDICT_WORDS = re.compile(r"\b(pass|fail|verdict|rank|best|winner)\w*", re.IGNORECASE)


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("research_store") / "raw"
    build_store(root, start=STORE_START, end=STORE_END, symbols=(SYMBOL,))
    return root


def _constraints_file(directory: Path) -> tuple[Path, str]:
    path = directory / "constraints.json"
    rows = [constraint_row(SYMBOL, datetime(2026, 6, 1, tzinfo=UTC))]
    path.write_text(json.dumps({"constraint_history": rows}), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _research_window_dataset_id(store: Path) -> str:
    data = build_case_input_data(
        store,
        symbols=[SYMBOL],
        start_utc=DEV_START,
        end_utc=VAL_END,
        as_of_day_utc=VAL_END.date(),
        series=ENGINE_SERIES,
    )
    return data.dataset_id


def _manifest(store: Path, directory: Path, **overrides: Any) -> DatasetManifest:
    constraints_path, constraints_sha = _constraints_file(directory)
    fields: dict[str, Any] = {
        "universe_id": "research-universe-v1",
        "symbols": (SYMBOL,),
        "dataset_id": _research_window_dataset_id(store),
        "development_start_utc": DEV_START,
        "development_end_utc": DEV_END,
        "validation_start_utc": VAL_START,
        "validation_end_utc": VAL_END,
        "holdout_start_utc": HOLD_START,
        "holdout_end_utc": HOLD_END,
        "strategy_interval": "1h",
        "context_interval": "4h",
        "data_source": "binance-usdm-public",
        "data_source_version": "test-1",
        "excluded_periods": (),
        "known_gaps": (),
        "equity": Decimal("1000"),
        "risk_rate": Decimal("0.005"),
        "constraint_source": str(constraints_path),
        "constraint_sha256": constraints_sha,
    }
    fields.update(overrides)
    return DatasetManifest(**fields)


def _grid() -> ParameterGrid:
    from src.domain.registry import load_parameter_set

    loaded = load_parameter_set("trend-pullback", "baseline-v5")
    point = GridPoint(
        parameter_set_id="baseline-v5",
        parameter_set_hash=loaded.parameter_set_hash,
        varied=(("minimum_rr", str(loaded.params["minimum_rr"])),),
    )
    return ParameterGrid(strategy_id="trend-pullback", points=(point,))


def _authorization(manifest: DatasetManifest, grid: ParameterGrid, **overrides: Any) -> Any:
    fields: dict[str, Any] = {
        "grid_hash": grid_hash(grid),
        "manifest_hash": manifest_hash(manifest),
        "authorized_at_utc": datetime(2026, 10, 9, tzinfo=UTC),
        "statement": "synthetic test authorization",
        "authorized_by": "synthetic test user",
    }
    fields.update(overrides)
    return RunAuthorization(**fields)


class _Spies:
    """Records every simulator.run window and read_code_version call."""

    def __init__(self) -> None:
        self.windows: list[tuple[str, str]] = []
        self.code_version_calls = 0


@pytest.fixture
def spies(monkeypatch: pytest.MonkeyPatch) -> _Spies:
    spy = _Spies()
    real_run = simulator.run

    def spy_run(case_input: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        window = case_input["data_window"]
        spy.windows.append((window["start_utc"], window["end_utc"]))
        return real_run(case_input, **kwargs)

    def fake_code_version(repo_root: Path) -> CodeVersion:
        spy.code_version_calls += 1
        return CodeVersion(commit=FAKE_COMMIT, dirty=False)

    monkeypatch.setattr(simulator, "run", spy_run)
    monkeypatch.setattr(research_run, "read_code_version", fake_code_version)
    return spy


def _tree_digest(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# --------------------------------------------------------------------------- #
# Test 1: canonical manifest and grid hashes.
# --------------------------------------------------------------------------- #


def test_manifest_and_grid_hashes_are_canonical_and_change_with_any_field(
    store: Path, tmp_path: Path
) -> None:
    manifest = _manifest(store, tmp_path)
    digest = manifest_hash(manifest)
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert digest == manifest_hash(_manifest(store, tmp_path))
    changes: dict[str, Any] = {
        "universe_id": "research-universe-v2",
        "symbols": (SYMBOL, "ETHUSDT"),
        "dataset_id": "0" * 64,
        "development_start_utc": datetime(2026, 6, 30, tzinfo=UTC),
        "holdout_end_utc": datetime(2026, 7, 12, tzinfo=UTC),
        "strategy_interval": "4h",
        "data_source_version": "test-2",
        "equity": Decimal("1000.0"),
        "risk_rate": Decimal("0.01"),
        "constraint_sha256": "1" * 64,
    }
    for name, value in changes.items():
        changed = dataclasses.replace(manifest, **{name: value})
        assert manifest_hash(changed) != digest, name

    grid = _grid()
    gdigest = grid_hash(grid)
    assert re.fullmatch(r"[0-9a-f]{64}", gdigest)
    point = grid.points[0]
    assert grid_hash(ParameterGrid("range-mr", grid.points)) != gdigest
    assert grid_hash(ParameterGrid(grid.strategy_id, (point, point))) != gdigest
    other = dataclasses.replace(point, parameter_set_hash="2" * 64)
    assert grid_hash(ParameterGrid(grid.strategy_id, (other,))) != gdigest
    varied = dataclasses.replace(point, varied=(("minimum_rr", "3"),))
    assert grid_hash(ParameterGrid(grid.strategy_id, (varied,))) != gdigest


def test_manifest_refuses_a_naive_non_contiguous_or_non_day_boundary(
    store: Path, tmp_path: Path
) -> None:
    with pytest.raises(ManifestError):
        _manifest(store, tmp_path, development_start_utc=datetime(2026, 7, 1))
    with pytest.raises(ManifestError):
        _manifest(store, tmp_path, validation_start_utc=datetime(2026, 7, 6, tzinfo=UTC))
    with pytest.raises(ManifestError):
        _manifest(store, tmp_path, development_end_utc=datetime(2026, 7, 5, 12, tzinfo=UTC))
    with pytest.raises(ManifestError):  # five validation days do not split into four folds
        _manifest(
            store,
            tmp_path,
            validation_end_utc=datetime(2026, 7, 10, tzinfo=UTC),
            holdout_start_utc=datetime(2026, 7, 10, tzinfo=UTC),
        ).validation_folds()


def test_research_splits_are_development_and_four_validation_folds_never_holdout(
    store: Path, tmp_path: Path
) -> None:
    manifest = _manifest(store, tmp_path)
    splits = research_splits(manifest)
    assert [s.role for s in splits] == ["DEVELOPMENT"] + ["VALIDATION"] * 4
    assert splits[0].start_utc == DEV_START and splits[0].end_utc == DEV_END
    assert splits[1].start_utc == VAL_START and splits[4].end_utc == VAL_END
    for before, after in zip(splits[1:], splits[2:], strict=False):
        assert before.end_utc == after.start_utc
    assert all(s.end_utc <= HOLD_START for s in splits)


# --------------------------------------------------------------------------- #
# Test 2: an authorized synthetic run writes experiment records end to end.
# --------------------------------------------------------------------------- #


def test_authorized_run_writes_one_record_per_split_and_no_verdict(
    store: Path,
    tmp_path: Path,
    spies: _Spies,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _manifest(store, tmp_path)
    grid = _grid()
    out = tmp_path / "experiments"
    params_before = _tree_digest(REPO_ROOT / "params")
    holdout_marker = REPO_ROOT / "docs" / "research" / "holdout_consumed.json"
    marker_before = holdout_marker.read_bytes()

    records = run_research(
        manifest=manifest,
        grid=grid,
        authorization=_authorization(manifest, grid),
        raw_root=store,
        output_dir=out,
        repo_root=REPO_ROOT,
    )

    assert len(records) == 5
    assert spies.code_version_calls == 1
    files = sorted(out.glob("*.json"))
    assert [f.stem for f in files] == sorted(r.experiment_id for r in records)
    for record in records:
        payload = json.loads((out / f"{record.experiment_id}.json").read_text(encoding="utf-8"))
        assert payload["experiment_id"] == record.experiment_id
        assert payload["code_commit"] == FAKE_COMMIT
        assert payload["parameter_set_id"] == "baseline-v5"
        assert payload["data_snapshot_id"] == record.data_snapshot_id
        assert payload["data_manifest_hash"] == manifest_hash(manifest)
        assert record.data_manifest_hash == manifest_hash(manifest)
    assert {r.split_role for r in records} == {"DEVELOPMENT", "VALIDATION"}
    stdout = capsys.readouterr().out
    assert "experiment_id=" in stdout
    assert VERDICT_WORDS.search(stdout) is None, stdout
    assert _tree_digest(REPO_ROOT / "params") == params_before
    assert holdout_marker.read_bytes() == marker_before


def test_identity_inputs_are_computed_in_one_function(store: Path, tmp_path: Path) -> None:
    manifest = _manifest(store, tmp_path)
    inputs = research_run.experiment_identity_inputs(manifest, "f" * 64)
    assert inputs == {"data_snapshot_id": "f" * 64, "data_manifest_hash": manifest_hash(manifest)}


# --------------------------------------------------------------------------- #
# Test 3: refusals happen before any simulation.
# --------------------------------------------------------------------------- #


def test_run_without_authorization_is_refused_before_simulate(
    store: Path, tmp_path: Path, spies: _Spies
) -> None:
    manifest = _manifest(store, tmp_path)
    with pytest.raises(RunNotAuthorized) as excinfo:
        run_research(
            manifest=manifest,
            grid=_grid(),
            authorization=None,
            raw_root=store,
            output_dir=tmp_path / "experiments",
            repo_root=REPO_ROOT,
        )
    assert excinfo.value.reason == "missing"
    assert spies.windows == []
    assert spies.code_version_calls == 0
    assert not (tmp_path / "experiments").exists()


@pytest.mark.parametrize(
    ("override", "reason"),
    [("grid_hash", "grid_hash_mismatch"), ("manifest_hash", "manifest_hash_mismatch")],
)
def test_mismatched_authorization_is_refused_before_simulate(
    store: Path, tmp_path: Path, spies: _Spies, override: str, reason: str
) -> None:
    manifest = _manifest(store, tmp_path)
    grid = _grid()
    authorization = _authorization(manifest, grid, **{override: "0" * 64})
    with pytest.raises(RunNotAuthorized) as excinfo:
        require_authorized(authorization, manifest=manifest, grid=grid)
    assert excinfo.value.reason == reason
    with pytest.raises(RunNotAuthorized):
        run_research(
            manifest=manifest,
            grid=grid,
            authorization=authorization,
            raw_root=store,
            output_dir=tmp_path / "experiments",
            repo_root=REPO_ROOT,
        )
    assert spies.windows == []


# --------------------------------------------------------------------------- #
# Test 4: the holdout is never simulated.
# --------------------------------------------------------------------------- #


def test_runner_never_simulates_the_holdout(store: Path, tmp_path: Path, spies: _Spies) -> None:
    manifest = _manifest(store, tmp_path)
    grid = _grid()
    run_research(
        manifest=manifest,
        grid=grid,
        authorization=_authorization(manifest, grid),
        raw_root=store,
        output_dir=tmp_path / "experiments",
        repo_root=REPO_ROOT,
    )
    assert len(spies.windows) == 5
    for start, end in spies.windows:
        assert datetime.fromisoformat(end) <= HOLD_START, (start, end)


def test_run_rejects_a_dataset_id_that_does_not_match_the_files(
    store: Path, tmp_path: Path, spies: _Spies
) -> None:
    manifest = _manifest(store, tmp_path, dataset_id="0" * 64)
    grid = _grid()
    with pytest.raises(ManifestError, match="dataset"):
        run_research(
            manifest=manifest,
            grid=grid,
            authorization=_authorization(manifest, grid),
            raw_root=store,
            output_dir=tmp_path / "experiments",
            repo_root=REPO_ROOT,
        )
    assert spies.windows == []


def test_run_rejects_a_grid_point_whose_registered_hash_differs(
    store: Path, tmp_path: Path, spies: _Spies
) -> None:
    manifest = _manifest(store, tmp_path)
    grid = _grid()
    bad = ParameterGrid(
        grid.strategy_id, (dataclasses.replace(grid.points[0], parameter_set_hash="3" * 64),)
    )
    with pytest.raises(ManifestError, match="parameter_set_hash"):
        run_research(
            manifest=manifest,
            grid=bad,
            authorization=_authorization(manifest, bad),
            raw_root=store,
            output_dir=tmp_path / "experiments",
            repo_root=REPO_ROOT,
        )
    assert spies.windows == []


# --------------------------------------------------------------------------- #
# Task 3 (checkpoint O-03a, option a): the committed authorization file and every refusal.
# --------------------------------------------------------------------------- #


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _manifest_json(manifest: DatasetManifest) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in manifest.canonical().items():
        if isinstance(value, datetime):
            out[key] = _iso(value)
        elif isinstance(value, Decimal):
            out[key] = str(value)
        else:
            out[key] = value
    out["excluded_periods"] = [
        {"start_utc": _iso(p.start_utc), "end_utc": _iso(p.end_utc), "reason": p.reason}
        for p in manifest.excluded_periods
    ]
    out["known_gaps"] = [
        {
            "series": g.series,
            "symbol": g.symbol,
            "interval": g.interval,
            "start_utc": _iso(g.start_utc),
            "end_utc": _iso(g.end_utc),
            "missing": g.missing,
        }
        for g in manifest.known_gaps
    ]
    return out


def _grid_json(grid: ParameterGrid) -> dict[str, Any]:
    return {
        "strategy_id": grid.strategy_id,
        "points": [
            {
                "parameter_set_id": p.parameter_set_id,
                "parameter_set_hash": p.parameter_set_hash,
                "varied": [[k, v] for k, v in p.varied],
            }
            for p in grid.points
        ],
    }


def _auth_json(manifest: DatasetManifest, grid: ParameterGrid, **overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "grid_sha256": grid_hash(grid),
        "manifest_sha256": manifest_hash(manifest),
        "authorized_at_utc": "2026-10-09T00:00:00Z",
        "statement": "synthetic test authorization",
        "authorized_by": "synthetic test user",
    }
    fields.update(overrides)
    return fields


def _write_json(path: Path, payload: Any) -> Path:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


class _Inputs:
    def __init__(self, directory: Path, manifest: DatasetManifest, grid: ParameterGrid) -> None:
        self.manifest = manifest
        self.grid = grid
        self.manifest_path = _write_json(directory / "manifest.json", _manifest_json(manifest))
        self.grid_path = _write_json(directory / "grid.json", _grid_json(grid))
        self.auth_path = _write_json(directory / "authorization.json", _auth_json(manifest, grid))


@pytest.fixture
def inputs(store: Path, tmp_path: Path) -> _Inputs:
    directory = tmp_path / "inputs"
    directory.mkdir()
    return _Inputs(directory, _manifest(store, directory), _grid())


def _argv(
    inputs: _Inputs,
    store: Path,
    out: Path,
    *,
    authorization: Path | None | str = "default",
) -> list[str]:
    argv = [
        "--manifest",
        str(inputs.manifest_path),
        "--grid",
        str(inputs.grid_path),
        "--raw-root",
        str(store),
        "--output-dir",
        str(out),
        "--repo-root",
        str(REPO_ROOT),
    ]
    chosen = inputs.auth_path if authorization == "default" else authorization
    if chosen is not None:
        argv += ["--authorization", str(chosen)]
    return argv


def test_authorization_file_parses_into_a_run_authorization(inputs: _Inputs) -> None:
    loaded = load_authorization(inputs.auth_path)
    assert loaded == RunAuthorization(
        grid_hash=grid_hash(inputs.grid),
        manifest_hash=manifest_hash(inputs.manifest),
        authorized_at_utc=datetime(2026, 10, 9, tzinfo=UTC),
        statement="synthetic test authorization",
        authorized_by="synthetic test user",
    )


@pytest.mark.parametrize(
    "mutation",
    [
        {"grid_sha256": None},
        {"manifest_sha256": None},
        {"authorized_at_utc": None},
        {"statement": None},
        {"authorized_by": None},
        {"grid_sha256": "abc"},
        {"manifest_sha256": "A" * 64},
        {"authorized_at_utc": "2026-10-09T00:00:00"},
        {"authorized_at_utc": "2026-10-09T07:00:00+07:00"},
        {"authorized_at_utc": "not a date"},
        {"authorized_at_utc": 20261009},
        {"statement": ""},
        {"authorized_by": "  "},
        {"unexpected": "key"},
    ],
)
def test_malformed_authorization_file_is_refused(
    inputs: _Inputs, tmp_path: Path, mutation: dict[str, Any]
) -> None:
    payload = _auth_json(inputs.manifest, inputs.grid)
    for key, value in mutation.items():
        if value is None:
            del payload[key]
        else:
            payload[key] = value
    path = _write_json(tmp_path / "bad_auth.json", payload)
    with pytest.raises(RunNotAuthorized) as excinfo:
        load_authorization(path)
    assert excinfo.value.reason == "malformed"


def test_authorization_file_that_is_not_a_json_object_or_is_absent(tmp_path: Path) -> None:
    for text in ("{not json", "[]", '"text"', ""):
        path = tmp_path / "bad.json"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(RunNotAuthorized) as excinfo:
            load_authorization(path)
        assert excinfo.value.reason == "malformed"
    with pytest.raises(RunNotAuthorized) as excinfo:
        load_authorization(tmp_path / "does_not_exist.json")
    assert excinfo.value.reason == "missing"


def test_manifest_and_grid_files_round_trip_to_the_same_hashes(inputs: _Inputs) -> None:
    assert load_manifest(inputs.manifest_path) == inputs.manifest
    assert load_grid(inputs.grid_path) == inputs.grid
    assert manifest_hash(load_manifest(inputs.manifest_path)) == manifest_hash(inputs.manifest)
    assert grid_hash(load_grid(inputs.grid_path)) == grid_hash(inputs.grid)


def test_manifest_file_refuses_floats_unknown_keys_and_bad_values(
    inputs: _Inputs, tmp_path: Path
) -> None:
    base = _manifest_json(inputs.manifest)
    for key, value in (
        ("equity", 1000.5),
        ("risk_rate", "abc"),
        ("unexpected", "x"),
        ("development_start_utc", "2026-07-01T00:00:00"),
        ("symbols", "BTCUSDT"),
    ):
        payload = dict(base)
        payload[key] = value
        with pytest.raises(ManifestError):
            load_manifest(_write_json(tmp_path / "m.json", payload))
    missing = dict(base)
    del missing["dataset_id"]
    with pytest.raises(ManifestError):
        load_manifest(_write_json(tmp_path / "m.json", missing))
    with pytest.raises(ManifestError):
        load_manifest(tmp_path / "absent.json")
    bad_grid = _grid_json(inputs.grid)
    bad_grid["extra"] = 1
    with pytest.raises(ManifestError):
        load_grid(_write_json(tmp_path / "g.json", bad_grid))


def test_main_runs_an_exactly_authorized_manifest_and_grid(
    inputs: _Inputs,
    store: Path,
    tmp_path: Path,
    spies: _Spies,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "experiments"
    marker = REPO_ROOT / "docs" / "research" / "holdout_consumed.json"
    marker_before = marker.read_bytes()
    assert main(_argv(inputs, store, out)) == 0
    assert len(spies.windows) == 5
    assert len(list(out.glob("*.json"))) == 5
    stdout = capsys.readouterr().out
    assert "experiment_id=" in stdout
    assert VERDICT_WORDS.search(stdout) is None, stdout
    assert marker.read_bytes() == marker_before


@pytest.mark.parametrize(
    ("override", "reason"),
    [("grid_sha256", "grid_hash_mismatch"), ("manifest_sha256", "manifest_hash_mismatch")],
)
def test_main_refuses_a_hash_mismatch_before_simulate(
    inputs: _Inputs,
    store: Path,
    tmp_path: Path,
    spies: _Spies,
    capsys: pytest.CaptureFixture[str],
    override: str,
    reason: str,
) -> None:
    _write_json(inputs.auth_path, _auth_json(inputs.manifest, inputs.grid, **{override: "0" * 64}))
    out = tmp_path / "experiments"
    assert main(_argv(inputs, store, out)) == 2
    assert reason in capsys.readouterr().err
    assert spies.windows == []
    assert spies.code_version_calls == 0
    assert not out.exists()


def test_main_refuses_a_missing_or_malformed_authorization(
    inputs: _Inputs,
    store: Path,
    tmp_path: Path,
    spies: _Spies,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "experiments"
    assert main(_argv(inputs, store, out, authorization=None)) == 2
    assert "missing" in capsys.readouterr().err
    assert main(_argv(inputs, store, out, authorization=tmp_path / "nope.json")) == 2
    assert "missing" in capsys.readouterr().err
    _write_json(inputs.auth_path, {"grid_sha256": "x"})
    assert main(_argv(inputs, store, out)) == 2
    assert "malformed" in capsys.readouterr().err
    assert spies.windows == []
    assert not out.exists()


def test_main_refuses_a_manifest_edited_after_authorization(
    inputs: _Inputs,
    store: Path,
    tmp_path: Path,
    spies: _Spies,
    capsys: pytest.CaptureFixture[str],
) -> None:
    edited = _manifest_json(inputs.manifest)
    edited["equity"] = "1001"
    _write_json(inputs.manifest_path, edited)
    assert main(_argv(inputs, store, tmp_path / "experiments")) == 2
    assert "manifest_hash_mismatch" in capsys.readouterr().err
    assert spies.windows == []


def test_main_refuses_a_grid_edited_after_authorization(
    inputs: _Inputs,
    store: Path,
    tmp_path: Path,
    spies: _Spies,
    capsys: pytest.CaptureFixture[str],
) -> None:
    edited = _grid_json(inputs.grid)
    edited["points"][0]["varied"] = [["minimum_rr", "99"]]
    _write_json(inputs.grid_path, edited)
    assert main(_argv(inputs, store, tmp_path / "experiments")) == 2
    assert "grid_hash_mismatch" in capsys.readouterr().err
    assert spies.windows == []


def test_rerun_of_a_recorded_experiment_is_refused_and_never_overwritten(
    inputs: _Inputs,
    store: Path,
    tmp_path: Path,
    spies: _Spies,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "experiments"
    assert main(_argv(inputs, store, out)) == 0
    before = _tree_digest(out)
    assert len(before) == 5
    capsys.readouterr()

    with pytest.raises(ExperimentAlreadyRecorded):
        run_research(
            manifest=inputs.manifest,
            grid=inputs.grid,
            authorization=_authorization(inputs.manifest, inputs.grid),
            raw_root=store,
            output_dir=out,
            repo_root=REPO_ROOT,
        )
    assert main(_argv(inputs, store, out)) == 2
    assert "experiment_already_recorded" in capsys.readouterr().err
    assert _tree_digest(out) == before


def test_rerun_with_one_existing_record_writes_no_new_file(
    inputs: _Inputs, store: Path, tmp_path: Path, spies: _Spies
) -> None:
    first = tmp_path / "first"
    records = run_research(
        manifest=inputs.manifest,
        grid=inputs.grid,
        authorization=_authorization(inputs.manifest, inputs.grid),
        raw_root=store,
        output_dir=first,
        repo_root=REPO_ROOT,
    )
    out = tmp_path / "partial"
    out.mkdir()
    last = records[-1].experiment_id
    (out / f"{last}.json").write_bytes((first / f"{last}.json").read_bytes())
    before = _tree_digest(out)
    with pytest.raises(ExperimentAlreadyRecorded):
        run_research(
            manifest=inputs.manifest,
            grid=inputs.grid,
            authorization=_authorization(inputs.manifest, inputs.grid),
            raw_root=store,
            output_dir=out,
            repo_root=REPO_ROOT,
        )
    assert _tree_digest(out) == before


def test_only_the_authorization_file_form_is_accepted(
    inputs: _Inputs, store: Path, tmp_path: Path, spies: _Spies
) -> None:
    argv = _argv(inputs, store, tmp_path / "experiments", authorization=None)
    for extra in (
        ["--authorize-grid-sha256", grid_hash(inputs.grid)],
        ["--authorize-manifest-sha256", manifest_hash(inputs.manifest)],
        ["--authorize", "yes"],
    ):
        with pytest.raises(SystemExit) as excinfo:
            main(argv + extra)
        assert excinfo.value.code == 2
    assert spies.windows == []


def test_runner_source_never_references_the_holdout_marker_or_the_allowlist() -> None:
    for path in sorted((REPO_ROOT / "src" / "research").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert "holdout_consumed" not in text, path.name
        assert "PAPER_START_ALLOWLIST" not in text, path.name


# --------------------------------------------------------------------------- #
# Plan 16-18 Task 3 (D-30, G4-009, G3-012): timing hook without tracemalloc, deferred items.
# --------------------------------------------------------------------------- #

DEFERRED_FEATURE_STATEMENT = (
    "incremental feature series deferred (D052 item h); any change must be an "
    "exact-equivalence refactor"
)
COST_TO_RISK_STATEMENT = "max_cost_to_risk unchanged (D046 item 6)"


def test_time_run_records_wall_seconds_per_split_and_never_starts_tracemalloc(
    inputs: _Inputs,
    store: Path,
    tmp_path: Path,
    spies: _Spies,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import tracemalloc

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("the runner must not start tracemalloc")

    ticks = iter(float(n) * 0.5 for n in range(1000))
    monkeypatch.setattr(tracemalloc, "start", forbidden)
    monkeypatch.setattr(research_run, "perf_counter", lambda: next(ticks))

    out_timed = tmp_path / "timed"
    assert main([*_argv(inputs, store, out_timed), "--time-run"]) == 0
    stdout = capsys.readouterr().out
    timing = [line for line in stdout.splitlines() if line.startswith("timing ")]
    assert len(timing) == 5
    assert all("wall_seconds=0.500" in line for line in timing)
    assert [("split_role=DEVELOPMENT" in line) for line in timing] == [
        True,
        False,
        False,
        False,
        False,
    ]
    assert VERDICT_WORDS.search(stdout) is None, stdout

    # The experiment records are byte-identical with and without the flag.
    out_plain = tmp_path / "plain"
    assert main(_argv(inputs, store, out_plain)) == 0
    assert "timing " not in capsys.readouterr().out
    assert _tree_digest(out_timed) == _tree_digest(out_plain)


def test_run_log_states_the_deferred_items_and_the_untouched_cost_guard(
    inputs: _Inputs,
    store: Path,
    tmp_path: Path,
    spies: _Spies,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(_argv(inputs, store, tmp_path / "experiments")) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines.count(DEFERRED_FEATURE_STATEMENT) == 1
    assert lines.count(COST_TO_RISK_STATEMENT) == 1


def test_runner_source_has_no_tracemalloc_and_params_stay_untouched() -> None:
    assert "tracemalloc" not in (REPO_ROOT / "src" / "research" / "run.py").read_text(
        encoding="utf-8"
    )
    for path in sorted((REPO_ROOT / "src" / "research").glob("*.py")):
        assert "tracemalloc" not in path.read_text(encoding="utf-8"), path.name
