"""Kill-gate report guard and review registry (Phase 16, plan 16-05, D061 F, REV-11, REV-15)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from src.adapters.analytics_files import EvidenceFileError, load_evidence_file
from src.analytics.killgate_guard import (
    DEFAULT_REGISTRY_PATH,
    EvidenceClass,
    KillGateReportBlocked,
    ReviewItem,
    load_review_registry,
    require_report_conclusion_allowed,
    unresolved_live_enable_blockers,
    unresolved_report_blockers,
)

from tests.test_analytics_cli import (
    EVIDENCE_FIXTURE,
    _db_run,
    _Env,
    _FakeFactory,
    _FakeStore,
    _run,
    _stdout_lines,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMITTED = REPO_ROOT / "docs" / "research" / "kill_gate_review_registry.json"
REPORT_IDS = ("WR-01", "WR-06", "WR-12", "WR-13")


def _item(item_id: str, *, resolved: bool = False, fix_commit: str | None = None) -> dict[str, Any]:
    report = item_id in REPORT_IDS
    return {
        "id": item_id,
        "state": "RESOLVED" if resolved else "UNRESOLVED",
        "blocks_report": report,
        "blocks_live_enable": item_id == "WR-10",
        "source": "test",
        "fix_commit": fix_commit if resolved else None,
    }


def _write(tmp_path: Path, items: list[dict[str, Any]]) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps({"schema": "kill-gate-review-registry/1", "items": items}), encoding="utf-8"
    )
    return path


def _registry(tmp_path: Path, *, resolved: tuple[str, ...] = ()) -> tuple[ReviewItem, ...]:
    ids = ("WR-01", "WR-06", "WR-10", "WR-12", "WR-13")
    items = [_item(i, resolved=i in resolved, fix_commit="abc1234") for i in ids]
    return load_review_registry(_write(tmp_path, items))


def test_committed_registry_lists_the_five_unresolved_items() -> None:
    items = load_review_registry(COMMITTED)
    by_id = {item.id: item for item in items}
    assert sorted(by_id) == ["WR-01", "WR-06", "WR-10", "WR-12", "WR-13"]
    assert all(item.state == "UNRESOLVED" for item in items)
    for item_id in REPORT_IDS:
        assert by_id[item_id].blocks_report is True
    assert by_id["WR-10"].blocks_report is False
    assert by_id["WR-10"].blocks_live_enable is True


def test_real_evidence_with_unresolved_report_blockers_is_refused() -> None:
    items = load_review_registry(COMMITTED)
    with pytest.raises(KillGateReportBlocked) as caught:
        require_report_conclusion_allowed(items, EvidenceClass.REAL)
    assert caught.value.blocking_ids == REPORT_IDS
    assert unresolved_report_blockers(items) == REPORT_IDS


def test_fixture_evidence_is_allowed() -> None:
    items = load_review_registry(COMMITTED)
    require_report_conclusion_allowed(items, EvidenceClass.FIXTURE)


def test_only_wr10_unresolved_does_not_block_the_report(tmp_path: Path) -> None:
    items = _registry(tmp_path, resolved=REPORT_IDS)
    require_report_conclusion_allowed(items, EvidenceClass.REAL)
    assert unresolved_report_blockers(items) == ()
    assert unresolved_live_enable_blockers(items) == ("WR-10",)


@pytest.mark.parametrize("unresolved", REPORT_IDS)
def test_flipping_any_one_item_back_blocks_again(tmp_path: Path, unresolved: str) -> None:
    resolved = tuple(i for i in REPORT_IDS if i != unresolved)
    items = _registry(tmp_path, resolved=resolved)
    with pytest.raises(KillGateReportBlocked) as caught:
        require_report_conclusion_allowed(items, EvidenceClass.REAL)
    assert caught.value.blocking_ids == (unresolved,)


def _five() -> list[dict[str, Any]]:
    return [_item(i) for i in ("WR-01", "WR-06", "WR-10", "WR-12", "WR-13")]


def test_registry_fails_closed_on_malformed_input(tmp_path: Path) -> None:
    unknown_state = _five()
    unknown_state[0]["state"] = "MAYBE"
    missing_scope = _five()
    del missing_scope[1]["blocks_live_enable"]
    duplicate = [*_five(), _item("WR-01")]
    resolved_without_commit = _five()
    resolved_without_commit[0]["state"] = "RESOLVED"
    resolved_without_commit[0]["fix_commit"] = None
    scope_tampered = _five()
    scope_tampered[0]["blocks_report"] = False
    missing_item = _five()[1:]
    for bad in (
        unknown_state,
        missing_scope,
        duplicate,
        resolved_without_commit,
        scope_tampered,
        missing_item,
    ):
        with pytest.raises(ValueError):
            load_review_registry(_write(tmp_path, bad))


def test_registry_rejects_wrong_schema_and_bad_json(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"schema": "other/1", "items": _five()}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_review_registry(path)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_review_registry(path)


def test_guard_rejects_wrong_input_types() -> None:
    with pytest.raises(TypeError):
        require_report_conclusion_allowed(load_review_registry(COMMITTED), "real")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        require_report_conclusion_allowed(["WR-01"], EvidenceClass.REAL)  # type: ignore[arg-type]


def test_default_registry_path_is_the_committed_file() -> None:
    assert DEFAULT_REGISTRY_PATH == COMMITTED


# --------------------------------------------------------------------------- #
# Task 2: fixture classification (REV-11) and CLI / renderer integration (D-31)
# --------------------------------------------------------------------------- #

NOT_CONCLUDED_LINE = "NOT CONCLUDED (blocked by WR-01, WR-06, WR-12, WR-13; D061 F)"
_STATE_VALUES = ("WITHIN_BUDGET", "PASSING_CANDIDATE", "INSUFFICIENT_EDGE")


@pytest.fixture(autouse=True)
def _no_ambient_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)


@pytest.fixture
def env(tmp_path: Path) -> _Env:
    return _Env(tmp_path)


def _evidence_variant(tmp_path: Path, *, evidence_class: object = None, drop: bool = False) -> Path:
    document = json.loads(EVIDENCE_FIXTURE.read_text(encoding="utf-8"))
    document.pop("evidence_class", None)
    if not drop and evidence_class is not None:
        document["evidence_class"] = evidence_class
    path = tmp_path / "variant-evidence.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_the_committed_evidence_sample_is_marked_fixture() -> None:
    assert load_evidence_file(EVIDENCE_FIXTURE).evidence_class is EvidenceClass.FIXTURE


def test_loader_defaults_to_real_and_accepts_only_the_fixture_literal(tmp_path: Path) -> None:
    assert load_evidence_file(_evidence_variant(tmp_path, drop=True)).evidence_class is (
        EvidenceClass.REAL
    )
    assert load_evidence_file(
        _evidence_variant(tmp_path, evidence_class="fixture")
    ).evidence_class is (EvidenceClass.FIXTURE)
    for bad in ("real", "FIXTURE", "", True, None, 1):
        document = json.loads(EVIDENCE_FIXTURE.read_text(encoding="utf-8"))
        document["evidence_class"] = bad
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(EvidenceFileError, match="evidence_class"):
            load_evidence_file(path)


def test_cli_withholds_the_conclusion_on_unmarked_real_evidence(
    env: _Env, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    env.evidence = _evidence_variant(tmp_path, drop=True)
    code, out, err = _run(capsys, env.argv())
    assert code == 0, err
    lines = _stdout_lines(out)
    assert len(lines) == 4
    assert lines[3] == f"Kill gate: {NOT_CONCLUDED_LINE}"
    markdown = Path(lines[0].removeprefix("Report: ")).read_text(encoding="utf-8")
    section = markdown.split("## 1. Kill Gate", 1)[1].split("\n---\n", 1)[0]
    assert NOT_CONCLUDED_LINE in section
    assert not any(value in section for value in _STATE_VALUES)
    assert "KILL GATE STATE:" not in markdown
    # The journal-depth sections are still produced (D-18).
    assert "## 2. Evidence Overview" in markdown
    sidecar = json.loads(Path(lines[1].removeprefix("Sidecar: ")).read_text(encoding="utf-8"))
    assert sidecar["report"]["kill_gate"]["verdict"]["state"] == "NOT CONCLUDED"
    assert sidecar["kill_gate_withheld"]["blocked_by"] == ["WR-01", "WR-06", "WR-12", "WR-13"]


def test_cli_record_on_real_evidence_exits_one_and_journals_nothing(
    env: _Env,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env.evidence = _evidence_variant(tmp_path, drop=True)
    store = _FakeStore()
    code, out, err = _db_run(env, _FakeFactory(store), capsys, monkeypatch, "--record")
    assert code == 1
    assert out == ""
    assert "Report not produced: kill-gate conclusion withheld" in err
    assert "WR-01, WR-06, WR-12, WR-13" in err
    assert store.kill_gate_ids() == []
    assert store.inserts() == []
    assert env.files() == []


def test_cli_run_without_an_evidence_file_is_real_and_withheld(
    env: _Env, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = [item for item in env.argv() if item != str(env.evidence)]
    argv.remove("--evidence")
    code, out, err = _run(capsys, argv)
    assert code == 0, err
    assert _stdout_lines(out)[3] == f"Kill gate: {NOT_CONCLUDED_LINE}"


def test_cli_run_over_a_fixture_marked_file_prints_the_verdict(
    env: _Env, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _run(capsys, env.argv())
    assert code == 0, err
    assert _stdout_lines(out)[3] == "Kill gate: WITHIN_BUDGET"


def test_cli_fails_closed_on_a_malformed_registry(
    env: _Env, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    bad = tmp_path / "bad-registry.json"
    bad.write_text("{}", encoding="utf-8")
    code, out, err = _run(capsys, env.argv("--review-registry", str(bad)))
    assert code == 1
    assert out == ""
    assert "review registry schema" in err
    assert env.files() == []


def test_cli_with_all_report_items_resolved_prints_the_verdict_on_real_evidence(
    env: _Env, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    env.evidence = _evidence_variant(tmp_path, drop=True)
    ids = ("WR-01", "WR-06", "WR-10", "WR-12", "WR-13")
    items = [_item(i, resolved=i in REPORT_IDS, fix_commit="abc1234") for i in ids]
    registry = _write(tmp_path, items)
    code, out, err = _run(capsys, env.argv("--review-registry", str(registry)))
    assert code == 0, err
    assert _stdout_lines(out)[3] == "Kill gate: WITHIN_BUDGET"
