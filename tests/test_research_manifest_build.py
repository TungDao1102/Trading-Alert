"""Tests for `python -m src.research.manifest --build` (plan 16-37 Task 3, tests 1 to 3).

The builder reads the user's O-03b decision record (`## Final values`), the published day files
and the committed settlement evidence. These tests use a synthetic store and a synthetic record
in `tmp_path`; the REEF settlement entry is checked against the real committed evidence. Nothing
touches the network, a database or the real data root, and the Holdout is never read.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from src.backtest.semantics import SIMULATOR_SEMANTICS_VERSION
from src.data.case_input import ENGINE_SERIES, TerminalDeclaration, build_case_input_data
from src.research import run as research_run
from src.research.authorization import RunAuthorization, require_authorized
from src.research.manifest import (
    GridPoint,
    ManifestError,
    ParameterGrid,
    grid_hash,
    load_manifest,
    manifest_hash,
)
from src.research.manifest_build import (
    REQUIRED_KEYS,
    SETTLEMENT_CONDITION,
    build_manifest,
    build_terminal_settlement,
    main,
    manifest_json_text,
    parse_decision_values,
    write_manifest,
)

from tests.backtest_case_helpers import constraint_row
from tests.test_case_input_builder import build_store
from tests.test_research_terminal_settlement_manifest import (
    CONDITION,
    REEF_URL,
    reef_settlement,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SYMBOL = "BTCUSDT"
STORE_START = datetime(2026, 7, 1, tzinfo=UTC)
STORE_END = datetime(2026, 7, 11, tzinfo=UTC)
VAL_END = datetime(2026, 7, 9, tzinfo=UTC)
DEV_START = STORE_START


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("manifest_build_store") / "raw"
    build_store(root, start=STORE_START, end=STORE_END, symbols=(SYMBOL,), oi=False)
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A stand-in repository root holding the constraint file named by the record."""
    path = tmp_path / "constraints.json"
    rows = [constraint_row(SYMBOL, datetime(2026, 6, 1, tzinfo=UTC))]
    path.write_text(json.dumps({"constraint_history": rows}), encoding="utf-8")
    return tmp_path


def _constraint_sha(repo_root: Path) -> str:
    return hashlib.sha256((repo_root / "constraints.json").read_bytes()).hexdigest()


def _values(repo_root: Path) -> dict[str, str]:
    return {
        "universe_id": "research-universe-test",
        "symbols": SYMBOL,
        "window_start_utc": "2026-07-01T00:00:00Z",
        "window_end_utc": "2026-07-11T00:00:00Z",
        "development_start_utc": "2026-07-01T00:00:00Z",
        "development_end_utc": "2026-07-05T00:00:00Z",
        "validation_start_utc": "2026-07-05T00:00:00Z",
        "validation_end_utc": "2026-07-09T00:00:00Z",
        "validation_folds": (
            "4 x 1 day (2026-07-05, 2026-07-06, 2026-07-07, 2026-07-08, 2026-07-09 boundaries)"
        ),
        "holdout_start_utc": "2026-07-09T00:00:00Z",
        "holdout_end_utc": "2026-07-11T00:00:00Z",
        "strategy_interval": "1h",
        "context_interval": "4h",
        "data_source": "binance-usdm-public",
        "data_source_version": "synthetic store",
        "excluded_periods": "[]",
        "equity": "600",
        "risk_rate": "0.005",
        "constraint_source": "constraints.json",
        "constraint_sha256": _constraint_sha(repo_root),
        "known_gaps": "none",
    }


def _record(values: dict[str, str]) -> str:
    body = "\n".join(f"{key}: {value}" for key, value in values.items())
    return (
        "# 16-DEC-O-03b (synthetic)\n\nsome words\n\n## Pasted by the user\n```\n"
        "ignored: this block is not read\n```\n\n## Final values\n```\n" + body + "\n```\n\n"
        "## Not decided\ntext\n"
    )


def _window_dataset_id(store: Path) -> str:
    return build_case_input_data(
        store,
        symbols=[SYMBOL],
        start_utc=DEV_START,
        end_utc=VAL_END,
        as_of_day_utc=VAL_END.date(),
        strategy_interval="1h",
        context_interval="4h",
        series=ENGINE_SERIES,
    ).dataset_id


# --------------------------------------------------------------------------- #
# Test 1: the build uses only the recorded values and refuses what is missing.
# --------------------------------------------------------------------------- #


def test_the_record_block_is_the_only_input_read() -> None:
    parsed = parse_decision_values(_record({"a": "1", "b": "x: y"}))
    assert parsed == {"a": "1", "b": "x: y"}


def test_the_real_decision_record_holds_every_required_value() -> None:
    record = REPO_ROOT / ".planning/phases/16-paper-runtime-composition/decisions/16-DEC-O-03b.md"
    parsed = parse_decision_values(record.read_text(encoding="utf-8"))
    assert all(parsed.get(key) for key in REQUIRED_KEYS)
    assert set(parsed) <= set(REQUIRED_KEYS) | {"terminal_settlements"}


@pytest.mark.parametrize(
    "text",
    [
        "no section here\n",
        "## Final values\nno fence\n",
        "## Final values\n```\na: 1\n",
        "## Final values\n```\nnot a pair\n```\n",
        "## Final values\n```\na: 1\na: 2\n```\n",
    ],
)
def test_a_malformed_record_is_refused(text: str) -> None:
    with pytest.raises(ManifestError):
        parse_decision_values(text)


def test_the_manifest_is_built_from_the_recorded_values(store: Path, repo: Path) -> None:
    manifest = build_manifest(decision_text=_record(_values(repo)), raw_root=store, repo_root=repo)
    assert manifest.universe_id == "research-universe-test"
    assert manifest.symbols == (SYMBOL,)
    assert manifest.dataset_id == _window_dataset_id(store)
    assert manifest.development_start_utc == DEV_START
    assert manifest.holdout_end_utc == STORE_END
    assert manifest.equity == Decimal("600")
    assert manifest.risk_rate == Decimal("0.005")
    assert manifest.known_gaps == ()
    assert manifest.terminal_settlements == ()
    assert manifest.excluded_periods == ()
    assert manifest.constraint_source == "constraints.json"


@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_a_missing_recorded_value_refuses_the_build(store: Path, repo: Path, key: str) -> None:
    values = _values(repo)
    del values[key]
    with pytest.raises(ManifestError, match="does not hold"):
        build_manifest(decision_text=_record(values), raw_root=store, repo_root=repo)


def test_an_empty_recorded_value_refuses_the_build(store: Path, repo: Path) -> None:
    values = _values(repo)
    values["data_source"] = ""
    with pytest.raises(ManifestError):
        build_manifest(decision_text=_record(values), raw_root=store, repo_root=repo)


def test_an_unregistered_key_refuses_the_build(store: Path, repo: Path) -> None:
    values = _values(repo)
    values["invented"] = "x"
    with pytest.raises(ManifestError, match="unregistered"):
        build_manifest(decision_text=_record(values), raw_root=store, repo_root=repo)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("excluded_periods", "2026-07-02T00:00:00Z .. 2026-07-03T00:00:00Z"),
        ("window_start_utc", "2026-06-30T00:00:00Z"),
        ("window_end_utc", "2026-07-10T00:00:00Z"),
        ("validation_folds", "4 x 1 day (2026-07-05, 2026-07-06, 2026-07-07, 2026-07-09)"),
        ("development_start_utc", "2026-07-01T00:00:00"),
        ("equity", "six hundred"),
        ("constraint_sha256", "0" * 64),
        ("known_gaps", "not a declaration"),
    ],
)
def test_an_inconsistent_value_refuses_the_build(
    store: Path, repo: Path, key: str, value: str
) -> None:
    values = _values(repo)
    values[key] = value
    with pytest.raises(ManifestError):
        build_manifest(decision_text=_record(values), raw_root=store, repo_root=repo)


def test_the_file_reloads_to_the_same_hash_and_is_never_overwritten(
    store: Path, repo: Path, tmp_path: Path
) -> None:
    manifest = build_manifest(decision_text=_record(_values(repo)), raw_root=store, repo_root=repo)
    out = tmp_path / "draft" / "manifest.json"
    digest = write_manifest(manifest, out)
    assert digest == manifest_hash(manifest) == manifest_hash(load_manifest(out))
    assert out.read_text(encoding="utf-8") == manifest_json_text(manifest)
    assert "\r" not in out.read_text(encoding="utf-8")
    with pytest.raises(ManifestError, match="never overwrites"):
        write_manifest(manifest, out)


def test_the_cli_prints_the_hash_and_refuses_with_exit_2(
    store: Path, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    decision = tmp_path / "record.md"
    decision.write_text(_record(_values(repo)), encoding="utf-8")
    out = tmp_path / "out" / "manifest.json"
    args = [
        "--build",
        "--decision",
        str(decision),
        "--raw-root",
        str(store),
        "--repo-root",
        str(repo),
        "--out",
        str(out),
    ]
    assert main(args) == 0
    printed = capsys.readouterr().out
    assert f"manifest_hash={manifest_hash(load_manifest(out))}" in printed
    assert f"dataset_id={_window_dataset_id(store)}" in printed
    assert main(args) == 2  # the file exists now
    assert "refused:" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# The REEF settlement entry is recomputed from the committed evidence.
# --------------------------------------------------------------------------- #

REEF_DECLARATION = TerminalDeclaration(
    symbol="REEFUSDT",
    reason="DELISTED_CAPPED",
    terminal_at_utc=datetime(2025, 1, 22, 9, 0, tzinfo=UTC),
    source_url=REEF_URL,
)


def test_the_reef_entry_equals_the_pinned_fixture_entry() -> None:
    entry = build_terminal_settlement(
        declaration=REEF_DECLARATION,
        tick=Decimal("0.000001"),
        expected_lower=Decimal("0.000845"),
        expected_upper=Decimal("0.000887"),
        repo_root=REPO_ROOT,
    )
    assert entry == reef_settlement()
    assert SETTLEMENT_CONDITION == CONDITION


@pytest.mark.parametrize(("lower", "upper"), [("0.000846", "0.000887"), ("0.000845", "0.000900")])
def test_bounds_that_differ_from_the_evidence_refuse_the_build(lower: str, upper: str) -> None:
    with pytest.raises(ManifestError, match="not the"):
        build_terminal_settlement(
            declaration=REEF_DECLARATION,
            tick=Decimal("0.000001"),
            expected_lower=Decimal(lower),
            expected_upper=Decimal(upper),
            repo_root=REPO_ROOT,
        )


def test_missing_evidence_refuses_the_build(tmp_path: Path) -> None:
    with pytest.raises(ManifestError):
        build_terminal_settlement(
            declaration=REEF_DECLARATION,
            tick=Decimal("0.000001"),
            expected_lower=Decimal("0.000845"),
            expected_upper=Decimal("0.000887"),
            repo_root=tmp_path,
        )


# --------------------------------------------------------------------------- #
# Tests 2 and 3: the identity names the manifest the authorization binds (REV-16, route B).
# --------------------------------------------------------------------------- #


def test_authorization_hash_and_identity_manifest_value_are_the_same_object(
    store: Path, repo: Path
) -> None:
    manifest = build_manifest(decision_text=_record(_values(repo)), raw_root=store, repo_root=repo)
    inputs = research_run.experiment_identity_inputs(manifest, manifest.dataset_id)
    assert inputs == {
        "data_snapshot_id": manifest.dataset_id,
        "data_manifest_hash": manifest_hash(manifest),
    }
    grid = ParameterGrid(
        strategy_id="trend-pullback",
        points=(GridPoint(parameter_set_id="x", parameter_set_hash="a" * 64, varied=()),),
    )
    authorization = RunAuthorization(
        grid_hash=grid_hash(grid),
        manifest_hash=manifest_hash(manifest),
        authorized_at_utc=datetime(2026, 10, 15, tzinfo=UTC),
        statement="synthetic test authorization",
        authorized_by="synthetic test user",
        simulator_semantics_version=SIMULATOR_SEMANTICS_VERSION,
    )
    require_authorized(authorization, manifest=manifest, grid=grid)
    assert authorization.manifest_hash == inputs["data_manifest_hash"]


# --------------------------------------------------------------------------- #
# Review follow-ups: the settlement path through build_manifest, refusals, atomic writes.
# --------------------------------------------------------------------------- #

REAL_RECORD = REPO_ROOT / ".planning/phases/16-paper-runtime-composition/decisions/16-DEC-O-03b.md"


@pytest.fixture
def stub_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the heavy day-file read: the real record is built against the real repo files."""
    from types import SimpleNamespace

    import src.research.manifest_build as module

    monkeypatch.setattr(
        module, "build_case_input_data", lambda *a, **k: SimpleNamespace(dataset_id="1" * 64)
    )


def test_the_real_record_builds_the_reef_settlement_through_build_manifest(
    stub_window: None, tmp_path: Path
) -> None:
    text = REAL_RECORD.read_text(encoding="utf-8")
    manifest = build_manifest(decision_text=text, raw_root=tmp_path, repo_root=REPO_ROOT)
    assert len(manifest.symbols) == 12
    assert [s.symbol for s in manifest.terminal_settlements] == ["REEFUSDT"]
    assert manifest.terminal_settlements[0] == reef_settlement()
    out = tmp_path / "manifest.json"
    digest = write_manifest(manifest, out)
    assert manifest_hash(load_manifest(out)) == digest
    research_run.check_terminal_settlement_evidence(load_manifest(out), REPO_ROOT)


def _with(text: str, old: str, new: str) -> str:
    assert old in text
    return text.replace(old, new, 1)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("price_lower 0.000845", "price_lower abc"),
        ("price_lower 0.000845", "price_lower 0.000846"),
        ("terminal_settlements: REEFUSDT,", "terminal_settlements: XYZUSDT,"),
        ("constraint_source: docs/", "constraint_source: ../Trading/docs/"),
        ("constraint_source: docs/", "constraint_source: C:/x/docs/"),
    ],
)
def test_bad_settlement_or_path_values_in_the_real_record_are_refused(
    stub_window: None, tmp_path: Path, old: str, new: str
) -> None:
    text = _with(REAL_RECORD.read_text(encoding="utf-8"), old, new)
    with pytest.raises(ManifestError):
        build_manifest(decision_text=text, raw_root=tmp_path, repo_root=REPO_ROOT)


def test_a_settlement_for_a_symbol_without_decided_evidence_is_refused() -> None:
    other = TerminalDeclaration(
        symbol="ETHUSDT",
        reason="DELISTED_CAPPED",
        terminal_at_utc=datetime(2025, 1, 22, 9, 0, tzinfo=UTC),
        source_url=REEF_URL,
    )
    with pytest.raises(ManifestError, match="no settlement evidence"):
        build_terminal_settlement(
            declaration=other,
            tick=Decimal("0.000001"),
            expected_lower=Decimal("0.000845"),
            expected_upper=Decimal("0.000887"),
            repo_root=REPO_ROOT,
        )


def test_two_constraint_rows_for_one_symbol_are_refused(store: Path, repo: Path) -> None:
    path = repo / "constraints.json"
    row = constraint_row(SYMBOL, datetime(2026, 6, 1, tzinfo=UTC))
    path.write_text(json.dumps({"constraint_history": [row, row]}), encoding="utf-8")
    values = _values(repo)
    values["constraint_sha256"] = _constraint_sha(repo)
    with pytest.raises(ManifestError, match="two rows"):
        build_manifest(decision_text=_record(values), raw_root=store, repo_root=repo)


def test_a_failed_reload_check_leaves_no_file(
    store: Path, repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.research.manifest_build as module

    manifest = build_manifest(decision_text=_record(_values(repo)), raw_root=store, repo_root=repo)

    def refuse(_path: Path) -> object:
        raise ManifestError("cannot reload")

    monkeypatch.setattr(module, "load_manifest", refuse)
    out = tmp_path / "x" / "manifest.json"
    with pytest.raises(ManifestError, match="cannot reload"):
        module.write_manifest(manifest, out)
    assert not out.exists()
    assert list(out.parent.iterdir()) == []


def test_holdout_day_files_do_not_move_the_built_manifest(
    store: Path, repo: Path, tmp_path: Path
) -> None:
    import shutil

    copy = tmp_path / "raw_copy"
    shutil.copytree(store, copy)
    before = manifest_hash(
        build_manifest(decision_text=_record(_values(repo)), raw_root=copy, repo_root=repo)
    )
    held = sorted(p for p in copy.rglob("*.parquet") if "date=2026-07-10" in p.as_posix())
    assert held
    for path in held:
        path.write_bytes(path.read_bytes() + b"\0")
    after = manifest_hash(
        build_manifest(decision_text=_record(_values(repo)), raw_root=copy, repo_root=repo)
    )
    assert before == after


def test_main_refuses_unreadable_or_odd_input_with_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "record.md"
    broken.write_bytes(b"\xff\xfe\x00bad")
    args = ["--build", "--decision", str(broken), "--raw-root", str(tmp_path), "--out"]
    assert main([*args, str(tmp_path / "m.json")]) == 2
    assert "refused:" in capsys.readouterr().out
