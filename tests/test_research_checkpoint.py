"""Tests for the resumable research run: `--checkpoint-dir` (quick 261015-pdb).

With a checkpoint directory the runner saves every simulated window, writes a grid point's
records as soon as the point is done and, on a rerun, reuses the saved windows. The records, their
ids and the report must be exactly those of a run without a checkpoint directory. Synthetic
store in tmp_path; nothing touches the network, a database or the real data root.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from src.backtest import simulator
from src.backtest.experiment import CodeVersion
from src.research import run as research_run
from src.research.manifest import ParameterGrid, load_grid
from src.research.run import CheckpointInvalid, ExperimentAlreadyRecorded, main, run_research

from tests.test_research_runner import (  # noqa: F401 - fixtures are used by name
    FAKE_COMMIT,
    REPO_ROOT,
    _argv,
    _authorization,
    _Inputs,
    _manifest,
    _Spies,
    _tree_digest,
    inputs,
    spies,
    store,
)


@pytest.fixture(autouse=True)
def _code_paths_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    """The development tree may have uncommitted code; the guard has its own test."""
    monkeypatch.setattr(research_run, "_code_paths_dirty", lambda _root: [])


def _two_point_grid() -> ParameterGrid:
    """The first two points of the committed trend-pullback grid (distinct varied tuples)."""
    committed = load_grid(
        REPO_ROOT
        / "docs"
        / "research"
        / "preregistration"
        / "research-run-1-grid-trend-pullback.json"
    )
    return ParameterGrid(strategy_id=committed.strategy_id, points=committed.points[:2])


def _run(
    raw_root: Path,
    tmp_path: Path,
    out: Path,
    *,
    grid: ParameterGrid | None = None,
    checkpoint: Path | None = None,
    time_run: bool = False,
    **manifest_overrides: Any,
) -> tuple[Any, ...]:
    manifest = _manifest(raw_root, tmp_path, **manifest_overrides)
    chosen = grid if grid is not None else _two_point_grid()
    return run_research(
        manifest=manifest,
        grid=chosen,
        authorization=_authorization(manifest, chosen),
        raw_root=raw_root,
        output_dir=out,
        repo_root=tmp_path,
        time_run=time_run,
        checkpoint_dir=checkpoint,
    )


def _report_lines(stdout: str) -> list[str]:
    """The run log without the per-record lines and the timing lines."""
    prefixes = ("recorded ", "present ", "timing ")
    return [line for line in stdout.splitlines() if not line.startswith(prefixes)]


def test_a_checkpoint_run_writes_exactly_the_records_of_a_plain_run(
    store: Path,  # noqa: F811
    tmp_path: Path,
    spies: _Spies,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    plain = tmp_path / "plain"
    first = _run(store, tmp_path, plain)
    plain_log = _report_lines(capsys.readouterr().out)

    kept = tmp_path / "checkpointed"
    checkpoint = tmp_path / "ckpt"
    second = _run(store, tmp_path, kept, checkpoint=checkpoint)
    kept_log = _report_lines(capsys.readouterr().out)

    assert [r.experiment_id for r in first] == [r.experiment_id for r in second]
    assert _tree_digest(plain) == _tree_digest(kept)
    assert plain_log == kept_log
    assert len(list(checkpoint.glob("*.json"))) == 10  # two points x five windows
    assert list(checkpoint.glob("*.tmp")) == []


def test_an_interrupted_run_keeps_finished_points_and_resumes_the_rest(
    store: Path,  # noqa: F811
    tmp_path: Path,
    spies: _Spies,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reference = tmp_path / "reference"
    _run(store, tmp_path, reference)
    capsys.readouterr()
    spies.windows.clear()

    real_run = simulator.run
    calls = {"n": 0}

    def crashing(case_input: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] == 8:  # the third window of the second point
            raise RuntimeError("simulated crash")
        return real_run(case_input, **kwargs)

    out = tmp_path / "out"
    checkpoint = tmp_path / "ckpt"
    monkeypatch.setattr(simulator, "run", crashing)
    with pytest.raises(RuntimeError, match="simulated crash"):
        _run(store, tmp_path, out, checkpoint=checkpoint)
    # the first point is finished and written; the second point has two saved windows
    assert len(list(out.glob("*.json"))) == 5
    assert len(list(checkpoint.glob("*.json"))) == 7
    capsys.readouterr()

    monkeypatch.setattr(simulator, "run", real_run)
    spies.windows.clear()
    records = _run(store, tmp_path, out, checkpoint=checkpoint, time_run=True)
    log = capsys.readouterr().out
    assert len(spies.windows) == 3  # only the windows that were not saved are simulated again
    assert log.count("checkpoint=reused") == 7
    assert log.count("present experiment_id=") == 5
    assert log.count("recorded experiment_id=") == 5
    assert len(records) == 10
    assert _tree_digest(out) == _tree_digest(reference)


def test_a_complete_rerun_is_idempotent_and_simulates_nothing(
    store: Path,  # noqa: F811
    tmp_path: Path,
    spies: _Spies,  # noqa: F811
) -> None:
    out = tmp_path / "out"
    checkpoint = tmp_path / "ckpt"
    _run(store, tmp_path, out, checkpoint=checkpoint)
    before = _tree_digest(out)
    spies.windows.clear()
    _run(store, tmp_path, out, checkpoint=checkpoint)
    assert spies.windows == []
    assert _tree_digest(out) == before


def test_a_record_that_differs_from_the_one_built_now_is_never_overwritten(
    store: Path,  # noqa: F811
    tmp_path: Path,
    spies: _Spies,  # noqa: F811
) -> None:
    out = tmp_path / "out"
    checkpoint = tmp_path / "ckpt"
    _run(store, tmp_path, out, checkpoint=checkpoint)
    victim = sorted(out.glob("*.json"))[0]
    victim.write_text(victim.read_text(encoding="utf-8") + " ", encoding="utf-8")
    before = _tree_digest(out)
    with pytest.raises(ExperimentAlreadyRecorded):
        _run(store, tmp_path, out, checkpoint=checkpoint)
    assert _tree_digest(out) == before


def _first_checkpoint(checkpoint: Path) -> Path:
    return sorted(checkpoint.glob("*.json"))[0]


def test_a_damaged_checkpoint_stops_the_run(
    store: Path,  # noqa: F811
    tmp_path: Path,
    spies: _Spies,  # noqa: F811
) -> None:
    out = tmp_path / "out"
    checkpoint = tmp_path / "ckpt"
    _run(store, tmp_path, out, checkpoint=checkpoint)
    target = _first_checkpoint(checkpoint)
    payload = json.loads(target.read_text(encoding="ascii"))
    payload["body"]["output"]["run_summary"] = {"tampered": "1"}
    target.write_text(json.dumps(payload), encoding="ascii")
    other = tmp_path / "other"
    with pytest.raises(CheckpointInvalid, match="does not match its hash"):
        _run(store, tmp_path, other, checkpoint=checkpoint)
    assert not other.exists()


def test_a_checkpoint_of_another_code_version_or_manifest_is_refused(
    store: Path,  # noqa: F811
    tmp_path: Path,
    spies: _Spies,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = tmp_path / "ckpt"
    _run(store, tmp_path, tmp_path / "out", checkpoint=checkpoint)

    monkeypatch.setattr(
        research_run,
        "read_code_version",
        lambda _root: CodeVersion(commit="b" * 40, dirty=False),
    )
    with pytest.raises(CheckpointInvalid, match="code_version"):
        _run(store, tmp_path, tmp_path / "out2", checkpoint=checkpoint)

    monkeypatch.setattr(
        research_run,
        "read_code_version",
        lambda _root: CodeVersion(commit=FAKE_COMMIT, dirty=False),
    )
    with pytest.raises(CheckpointInvalid, match="manifest_sha256"):
        _run(
            store,
            tmp_path,
            tmp_path / "out3",
            checkpoint=checkpoint,
            data_source_version="test-3",
        )


def test_the_checkpoint_directory_must_not_be_the_output_directory(
    store: Path,  # noqa: F811
    tmp_path: Path,
    spies: _Spies,  # noqa: F811
) -> None:
    both = tmp_path / "same"
    with pytest.raises(CheckpointInvalid, match="must not be the output directory"):
        _run(store, tmp_path, both, checkpoint=both)
    assert spies.windows == []


def test_a_checkpoint_run_still_refuses_without_authorization_before_simulation(
    store: Path,  # noqa: F811
    tmp_path: Path,
    spies: _Spies,  # noqa: F811
) -> None:
    manifest = _manifest(store, tmp_path)
    grid = _two_point_grid()
    with pytest.raises(research_run.RunNotAuthorized):
        run_research(
            manifest=manifest,
            grid=grid,
            authorization=None,
            raw_root=store,
            output_dir=tmp_path / "out",
            repo_root=tmp_path,
            checkpoint_dir=tmp_path / "ckpt",
        )
    assert spies.windows == []
    assert not (tmp_path / "ckpt").exists()


def test_the_cli_accepts_a_checkpoint_dir_and_reports_a_damaged_one(
    inputs: _Inputs,  # noqa: F811
    store: Path,  # noqa: F811
    tmp_path: Path,
    spies: _Spies,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "experiments"
    checkpoint = tmp_path / "ckpt"
    argv = [*_argv(inputs, store, out), "--checkpoint-dir", str(checkpoint)]
    assert main(argv) == 0
    capsys.readouterr()
    assert len(list(checkpoint.glob("*.json"))) == 5
    _first_checkpoint(checkpoint).write_text("not json", encoding="ascii")
    assert main(argv) == 2
    assert "checkpoint_invalid" in capsys.readouterr().err


def test_the_checkpoint_never_changes_the_experiment_identity_inputs() -> None:
    names = {f.name for f in dataclasses.fields(research_run.ExperimentRecord)}
    assert "checkpoint" not in " ".join(names)


def test_a_checkpoint_run_refuses_uncommitted_code(
    store: Path,  # noqa: F811
    tmp_path: Path,
    spies: _Spies,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(research_run, "_code_paths_dirty", lambda _root: [" M src/x.py"])
    with pytest.raises(CheckpointInvalid, match="uncommitted changes"):
        _run(store, tmp_path, tmp_path / "out", checkpoint=tmp_path / "ckpt")
    assert spies.windows == []
    # a plain run (no checkpoint directory) is not affected by the guard
    assert len(_run(store, tmp_path, tmp_path / "plain")) == 10


def test_a_record_is_never_left_half_written(
    store: Path,  # noqa: F811
    tmp_path: Path,
    spies: _Spies,  # noqa: F811
) -> None:
    out = tmp_path / "out"
    _run(store, tmp_path, out, checkpoint=tmp_path / "ckpt")
    assert list(out.glob(".*.tmp")) == []
    victim = sorted(out.glob("*.json"))[0]
    victim.write_text(victim.read_text(encoding="utf-8")[:50], encoding="utf-8")
    with pytest.raises(ExperimentAlreadyRecorded, match="truncated"):
        _run(store, tmp_path, out, checkpoint=tmp_path / "ckpt")


def test_a_varied_value_is_compared_by_number_and_the_pivot_label_covers_both_widths() -> None:
    params = {"pivot_left_bars": 3, "pivot_right_bars": 3, "zone_tolerance_atr": 1}
    check = research_run._varied_value_is_registered
    assert check(params, "pivot_bars", "3")
    assert check(params, "zone_tolerance_atr", "1.0")
    assert not check(params, "pivot_bars", "5")
    assert not check({**params, "pivot_right_bars": 5}, "pivot_bars", "3")
    assert not check(params, "zone_tolerance_atr", "1.5")
    assert not check(params, "unknown", "1")
