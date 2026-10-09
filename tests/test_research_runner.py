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
from src.research.authorization import RunAuthorization, RunNotAuthorized, require_authorized
from src.research.manifest import (
    DatasetManifest,
    GridPoint,
    ManifestError,
    ParameterGrid,
    grid_hash,
    manifest_hash,
    research_splits,
)
from src.research.run import run_research

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
    assert {r.split_role for r in records} == {"DEVELOPMENT", "VALIDATION"}
    stdout = capsys.readouterr().out
    assert "experiment_id=" in stdout
    assert VERDICT_WORDS.search(stdout) is None, stdout
    assert _tree_digest(REPO_ROOT / "params") == params_before
    assert holdout_marker.read_bytes() == marker_before


def test_identity_inputs_are_computed_in_one_function() -> None:
    manifest_sentinel: Any = object()
    inputs = research_run.experiment_identity_inputs(manifest_sentinel, "f" * 64)
    assert inputs == {"data_snapshot_id": "f" * 64}


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
