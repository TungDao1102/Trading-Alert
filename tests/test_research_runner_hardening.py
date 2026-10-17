"""Hardening of the research runner before the 2.2.0 rerun (plan 16-61, Task 1).

Findings B3-WR-02 to B3-WR-05 of 16-REVIEW-batch3.md and the owner's decision 16-60 Q4 = B
(a required sixth authorization key, `simulator_semantics_version`). Every run here goes
through `run_research` or `main` on a synthetic published store in tmp_path; the real data
root, the 240 committed records of research run 1 and the real Holdout are never touched.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.backtest import simulator
from src.backtest.experiment import (
    CodeVersion,
    ExperimentReproducibilityBroken,
    reproduce,
    stored_trades_digest,
    trades_digest,
    verify_experiment,
)
from src.backtest.semantics import SIMULATOR_SEMANTICS_VERSION
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
)
from src.research.run import ExperimentAlreadyRecorded, main, run_research

from tests.backtest_case_helpers import constraint_row
from tests.test_backtest_experiment import (
    PHASE6_FIXTURES_DIR,
    _load_bound_input,
    _simple_trend_record,
)
from tests.test_research_runner import (  # noqa: F401 - the store fixture is used by name
    DEV_END,
    DEV_START,
    FAKE_COMMIT,
    HOLD_END,
    HOLD_START,
    STORE_END,
    STORE_START,
    SYMBOL,
    VAL_END,
    VAL_START,
    _grid,
    _grid_json,
    _manifest_json,
    _research_window_dataset_id,
    _tree_digest,
    _write_json,
    store,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PREREG = REPO_ROOT / "docs" / "research" / "preregistration"
HASHES_EVIDENCE = (
    REPO_ROOT
    / ".planning"
    / "phases"
    / "16-paper-runtime-composition"
    / "evidence"
    / "16-46-hashes.txt"
)
FAMILIES = ("trend-pullback", "breakout-retest", "range-mr")


# --------------------------------------------------------------------------- #
# A synthetic repository root: constraints, manifest, grid and authorization files.
# --------------------------------------------------------------------------- #


def _manifest(raw_store: Path, repo: Path, **overrides: Any) -> DatasetManifest:
    """A manifest whose constraint file `constraints.json` sits at the root of `repo`."""
    path = repo / "constraints.json"
    rows = [constraint_row(SYMBOL, datetime(2026, 6, 1, tzinfo=UTC))]
    path.write_text(json.dumps({"constraint_history": rows}), encoding="utf-8")
    fields: dict[str, Any] = {
        "universe_id": "research-universe-v1",
        "symbols": (SYMBOL,),
        "dataset_id": _research_window_dataset_id(raw_store),
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
        "constraint_source": "constraints.json",
        "constraint_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    fields.update(overrides)
    return DatasetManifest(**fields)


def _auth_json(manifest: DatasetManifest, grid: ParameterGrid, **overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "grid_sha256": grid_hash(grid),
        "manifest_sha256": manifest_hash(manifest),
        "authorized_at_utc": "2026-10-16T07:22:56+00:00",
        "statement": "synthetic hardening authorization",
        "authorized_by": "synthetic test user",
        "simulator_semantics_version": SIMULATOR_SEMANTICS_VERSION,
    }
    fields.update(overrides)
    return fields


def _authorization(manifest: DatasetManifest, grid: ParameterGrid, **overrides: Any) -> Any:
    fields: dict[str, Any] = {
        "grid_hash": grid_hash(grid),
        "manifest_hash": manifest_hash(manifest),
        "authorized_at_utc": datetime(2026, 10, 16, 7, 22, 56, tzinfo=UTC),
        "statement": "synthetic hardening authorization",
        "authorized_by": "synthetic test user",
        "simulator_semantics_version": SIMULATOR_SEMANTICS_VERSION,
    }
    fields.update(overrides)
    return RunAuthorization(**fields)


class _Spy:
    """What reached the simulator, the code-version reader and the store."""

    def __init__(self) -> None:
        self.windows: list[tuple[str, str]] = []
        self.code_version_calls = 0
        self.store_reads = 0


@dataclasses.dataclass
class _World:
    repo: Path
    store: Path
    manifest: DatasetManifest
    grid: ParameterGrid
    manifest_path: Path
    grid_path: Path
    auth_path: Path
    spy: _Spy

    def argv(
        self, out: Path, *, repo_root: Path | None = None, extra: tuple[str, ...] = ()
    ) -> list:
        return [
            "--manifest",
            str(self.manifest_path),
            "--grid",
            str(self.grid_path),
            "--authorization",
            str(self.auth_path),
            "--raw-root",
            str(self.store),
            "--output-dir",
            str(out),
            "--repo-root",
            str(self.repo if repo_root is None else repo_root),
            *extra,
        ]

    def run(self, out: Path, **kwargs: Any) -> tuple[Any, ...]:
        return run_research(
            manifest=self.manifest,
            grid=self.grid,
            authorization=_authorization(self.manifest, self.grid),
            raw_root=self.store,
            output_dir=out,
            repo_root=self.repo,
            **kwargs,
        )


@pytest.fixture
def world(store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _World:  # noqa: F811
    """A repository root of its own: the code 'was imported from' it and the cwd is inside it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = _manifest(store, repo)
    grid = _grid()
    manifest_path = _write_json(repo / "manifest.json", _manifest_json(manifest))
    grid_path = _write_json(repo / "grid.json", _grid_json(grid))
    auth_path = _write_json(repo / "authorization.json", _auth_json(manifest, grid))
    spy = _Spy()
    real_run = simulator.run
    real_build = research_run.build_case_input_data

    def spy_run(case_input: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        window = case_input["data_window"]
        spy.windows.append((window["start_utc"], window["end_utc"]))
        return real_run(case_input, **kwargs)

    def spy_build(*args: Any, **kwargs: Any) -> Any:
        spy.store_reads += 1
        return real_build(*args, **kwargs)

    def fake_code_version(repo_root: Path) -> CodeVersion:
        spy.code_version_calls += 1
        return CodeVersion(commit=FAKE_COMMIT, dirty=False)

    monkeypatch.setattr(simulator, "run", spy_run)
    monkeypatch.setattr(research_run, "build_case_input_data", spy_build)
    monkeypatch.setattr(research_run, "read_code_version", fake_code_version)
    monkeypatch.setattr(research_run, "_code_paths_dirty", lambda _root: [])
    monkeypatch.setattr(research_run, "_REPO_ROOT", repo.resolve())
    monkeypatch.chdir(repo)
    return _World(repo, store, manifest, grid, manifest_path, grid_path, auth_path, spy)


# --------------------------------------------------------------------------- #
# Test 5: the sixth authorization key (owner decision 16-60 Q4 = B).
# --------------------------------------------------------------------------- #


def test_the_authorization_carries_exactly_six_keys(world: _World, tmp_path: Path) -> None:
    loaded = load_authorization(world.auth_path)
    assert loaded.simulator_semantics_version == SIMULATOR_SEMANTICS_VERSION
    assert loaded == _authorization(world.manifest, world.grid)

    payload = _auth_json(world.manifest, world.grid)
    del payload["simulator_semantics_version"]
    for bad in (
        payload,  # the five-key form
        {**_auth_json(world.manifest, world.grid), "unexpected": "key"},
        _auth_json(world.manifest, world.grid, simulator_semantics_version=""),
        _auth_json(world.manifest, world.grid, simulator_semantics_version="  "),
        _auth_json(world.manifest, world.grid, simulator_semantics_version=2),
        _auth_json(world.manifest, world.grid, simulator_semantics_version=None),
    ):
        path = _write_json(tmp_path / "bad.json", bad)
        with pytest.raises(RunNotAuthorized) as excinfo:
            load_authorization(path)
        assert excinfo.value.reason == "malformed"


@pytest.mark.parametrize("family", FAMILIES)
def test_each_existing_five_key_authorization_file_is_refused_as_malformed(family: str) -> None:
    path = PREREG / f"research-run-1-authorization-{family}.json"
    before = path.read_bytes()
    assert len(json.loads(before)) == 5
    with pytest.raises(RunNotAuthorized) as excinfo:
        load_authorization(path)
    assert excinfo.value.reason == "malformed"
    assert path.read_bytes() == before


def test_a_version_other_than_the_codes_is_refused_and_names_the_key(world: _World) -> None:
    other = _authorization(world.manifest, world.grid, simulator_semantics_version="2.1.0")
    with pytest.raises(RunNotAuthorized) as excinfo:
        require_authorized(other, manifest=world.manifest, grid=world.grid)
    assert excinfo.value.reason == "simulator_semantics_version_mismatch"
    assert "synthetic hardening authorization" not in excinfo.value.reason
    require_authorized(
        _authorization(world.manifest, world.grid), manifest=world.manifest, grid=world.grid
    )


def test_main_refuses_a_five_key_file_and_a_wrong_version_before_any_simulation(
    world: _World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "experiments"
    five = _auth_json(world.manifest, world.grid)
    del five["simulator_semantics_version"]
    _write_json(world.auth_path, five)
    assert main(world.argv(out)) == 2
    assert "malformed" in capsys.readouterr().err

    _write_json(
        world.auth_path,
        _auth_json(world.manifest, world.grid, simulator_semantics_version="2.1.0"),
    )
    assert main(world.argv(out)) == 2
    assert "simulator_semantics_version_mismatch" in capsys.readouterr().err

    assert world.spy.windows == []
    assert world.spy.store_reads == 0
    assert world.spy.code_version_calls == 0
    assert not out.exists()

    _write_json(world.auth_path, _auth_json(world.manifest, world.grid))
    assert main(world.argv(out)) == 0
    assert len(world.spy.windows) == 5
    assert len(list(out.glob("*.json"))) == 5


# --------------------------------------------------------------------------- #
# Test 1 (B3-WR-02): the records attest their trades.
# --------------------------------------------------------------------------- #


def _canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def test_every_record_carries_the_digest_of_its_windows_trades(
    world: _World, tmp_path: Path
) -> None:
    out = tmp_path / "experiments"
    records = world.run(out)
    assert len(records) == 5
    empty_digest = trades_digest([])
    for record in records:
        assert record.result_summary_json == _canonical({"trades_digest": empty_digest})
        assert stored_trades_digest(record) == empty_digest
        payload = json.loads((out / f"{record.experiment_id}.json").read_text(encoding="utf-8"))
        assert payload["result_summary_json"] == record.result_summary_json


def test_the_digest_covers_real_trades_and_verify_experiment_uses_it() -> None:
    case = _load_bound_input(PHASE6_FIXTURES_DIR / "baselines" / "simple_trend")
    output = simulator.run(case)
    assert output["trades"], "the fixture must produce trades for this test to mean anything"
    summary = research_run._result_summary_json(output)
    assert json.loads(summary) == {
        "trades_digest": trades_digest(reproduce(_simple_trend_record(case), simulator_inputs=case))
    }
    attested = _simple_trend_record(case, result_summary_json=summary)
    assert verify_experiment(attested, simulator_inputs=case) is None

    changed = json.loads(json.dumps(output))
    changed["trades"][0]["realized_pnl"] = "123456789"
    forged = _simple_trend_record(
        case, result_summary_json=research_run._result_summary_json(changed)
    )
    with pytest.raises(ExperimentReproducibilityBroken, match="trades_digest"):
        verify_experiment(forged, simulator_inputs=case)


def test_a_reused_window_whose_trades_differ_from_the_record_on_disk_is_refused(
    world: _World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "experiments"
    checkpoint = tmp_path / "ckpt"
    world.run(out, checkpoint_dir=checkpoint)
    before = _tree_digest(out)
    assert len(before) == 5

    monkeypatch.setattr(
        research_run,
        "_result_summary_json",
        lambda _output: _canonical({"trades_digest": "f" * 64}),
    )
    with pytest.raises(ExperimentAlreadyRecorded):
        world.run(out, checkpoint_dir=checkpoint)
    assert _tree_digest(out) == before


# --------------------------------------------------------------------------- #
# Test 2 (B3-WR-03): the constraint source is rooted at the repository root.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "bad",
    [
        "/etc/constraints.json",
        "C:/x/constraints.json",
        "C:\\x\\constraints.json",
        "\\\\host\\share\\c.json",
        "../constraints.json",
        "docs/../../constraints.json",
        "docs\\constraints.json",
        "docs//constraints.json",
        "./constraints.json",
        "docs/",
        "",
    ],
)
def test_the_manifest_refuses_a_constraint_source_that_is_not_repo_relative(
    world: _World, bad: str
) -> None:
    with pytest.raises(ManifestError, match="constraint_source"):
        dataclasses.replace(world.manifest, constraint_source=bad)
    payload = _manifest_json(world.manifest)
    payload["constraint_source"] = bad
    with pytest.raises(ManifestError):
        load_manifest(_write_json(world.repo / "bad_manifest.json", payload))


def test_a_clean_relative_constraint_source_is_accepted(world: _World) -> None:
    manifest = dataclasses.replace(
        world.manifest, constraint_source="docs/research/constraints.json"
    )
    assert manifest.constraint_source == "docs/research/constraints.json"


def test_the_runner_reads_the_constraints_at_the_repo_root_not_in_the_cwd(
    world: _World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    decoy = elsewhere / "constraints.json"
    decoy.write_text('{"constraint_history": []}', encoding="utf-8")
    monkeypatch.chdir(elsewhere)

    out = tmp_path / "experiments"
    assert main(world.argv(out)) == 0
    assert len(list(out.glob("*.json"))) == 5
    assert decoy.read_text(encoding="utf-8") == '{"constraint_history": []}'
    capsys.readouterr()

    missing = tmp_path / "missing_root"
    missing.mkdir()
    with pytest.raises(ManifestError, match="constraint source unreadable"):
        research_run._load_constraints(world.manifest, missing)


def test_the_runner_confines_the_constraint_source_to_the_repo_root(world: _World) -> None:
    escaping = dataclasses.replace(world.manifest)
    object.__setattr__(escaping, "constraint_source", "../outside.json")
    with pytest.raises(ManifestError, match="outside the repository root"):
        research_run._load_constraints(escaping, world.repo)
    rooted_elsewhere = dataclasses.replace(world.manifest)
    object.__setattr__(rooted_elsewhere, "constraint_source", "C:/outside.json")
    with pytest.raises(ManifestError, match="outside the repository root"):
        research_run._load_constraints(rooted_elsewhere, world.repo)


def test_the_committed_manifest_loads_and_its_hash_is_unchanged() -> None:
    manifest = load_manifest(PREREG / "research-run-1-manifest.json")
    recorded = HASHES_EVIDENCE.read_text(encoding="utf-8")
    assert manifest_hash(manifest) == (
        "ec161733076f99e626da6900b7cc354ed68aa3104f5ac60de486b3b39f7ac569"
    )
    assert manifest_hash(manifest) in recorded
    assert manifest.constraint_source == (
        "docs/research/preregistration/research-run-1-constraints-baseline.json"
    )
    rows = research_run._load_constraints(manifest, REPO_ROOT)
    assert {row["symbol"] for row in rows} >= set(manifest.symbols)


# --------------------------------------------------------------------------- #
# Test 3 (B3-WR-04): the repository root is the root the code was imported from.
# --------------------------------------------------------------------------- #


def test_main_refuses_a_repo_root_other_than_the_import_root(
    world: _World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    other = tmp_path / "other_checkout"
    other.mkdir()
    (other / "constraints.json").write_bytes((world.repo / "constraints.json").read_bytes())
    out = tmp_path / "experiments"
    assert main(world.argv(out, repo_root=other)) == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "repo_root" in err
    assert world.spy.windows == []
    assert world.spy.store_reads == 0
    assert world.spy.code_version_calls == 0
    assert not out.exists()


def test_main_accepts_the_import_root_spelled_another_way(world: _World, tmp_path: Path) -> None:
    spelled = world.repo / "sub" / ".."
    (world.repo / "sub").mkdir()
    assert os.path.samefile(spelled, world.repo)
    out = tmp_path / "experiments"
    assert main(world.argv(out, repo_root=spelled)) == 0
    assert len(list(out.glob("*.json"))) == 5


# --------------------------------------------------------------------------- #
# Test 4 (B3-WR-05): a grid with a duplicate point is refused at load.
# --------------------------------------------------------------------------- #


def _point(set_id: str, value: str, *, key: str = "minimum_rr") -> GridPoint:
    return GridPoint(parameter_set_id=set_id, parameter_set_hash="1" * 64, varied=((key, value),))


def test_a_grid_refuses_a_duplicate_parameter_set_id_or_varied_tuple() -> None:
    with pytest.raises(ManifestError, match="duplicate parameter_set_id"):
        ParameterGrid("trend-pullback", (_point("a01", "2"), _point("a01", "3")))
    with pytest.raises(ManifestError, match="duplicate varied"):
        ParameterGrid("trend-pullback", (_point("a01", "2"), _point("a02", "2")))
    with pytest.raises(ManifestError, match="duplicate varied"):
        ParameterGrid("trend-pullback", (_point("a01", "2"), _point("a02", "2.0")))
    ParameterGrid("trend-pullback", (_point("a01", "2"), _point("a02", "3")))


def test_a_grid_whose_points_vary_different_keys_is_refused() -> None:
    with pytest.raises(ManifestError, match="same keys"):
        ParameterGrid(
            "trend-pullback", (_point("a01", "2"), _point("a02", "3", key="sl_buffer_atr"))
        )


def test_main_refuses_a_duplicate_point_grid_file_and_writes_nothing(
    world: _World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = _grid_json(world.grid)
    payload["points"] = [payload["points"][0], dict(payload["points"][0])]
    _write_json(world.grid_path, payload)
    with pytest.raises(ManifestError, match="duplicate"):
        load_grid(world.grid_path)
    out = tmp_path / "experiments"
    assert main(world.argv(out)) == 2
    assert "manifest_or_grid_invalid" in capsys.readouterr().err
    assert world.spy.windows == []
    assert not out.exists()


@pytest.mark.parametrize("family", FAMILIES)
def test_the_committed_grids_load_unchanged(family: str) -> None:
    expected = {
        "trend-pullback": "13207b306df9a2bc1d580df456b1e6a3d3478eff82c5eb1ff6ac6a9daac14411",
        "breakout-retest": "2ed8577ea225b294eaaa82c4478fee6dbf2b3d5a76eca8f967b5d769171c4069",
        "range-mr": "3388fceb664ba7999477070ef9d49f15ccff0b073d3587ad58351dd5c5d297c6",
    }[family]
    grid = load_grid(PREREG / f"research-run-1-grid-{family}.json")
    assert len(grid.points) == 16
    assert grid_hash(grid) == expected
    assert expected in HASHES_EVIDENCE.read_text(encoding="utf-8")
