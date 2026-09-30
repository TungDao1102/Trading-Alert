"""Tests for the parameter-set gate module (Phase 11, plan 11-02; D036-D038, F-810).

The real-repository test proves gates PA-01..PA-06 hold today; the negative tests run
each pure check over a tmp_path copy of params/ that has been deliberately broken so
a regression cannot pass silently.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from scripts.decision_alignment import params as gate

REPO_PARAMS = Path(__file__).resolve().parent.parent / "params"


@pytest.fixture
def params_copy(tmp_path: Path) -> Path:
    dest = tmp_path / "params"
    shutil.copytree(REPO_PARAMS, dest)
    return dest


def _edit(root: Path, key: gate.SetKey, old: str, new: str) -> None:
    path = root / key[0] / f"{key[1]}.toml"
    text = path.read_text(encoding="utf-8")
    assert old in text, (key, old)
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def test_real_repo_gates_all_ok() -> None:
    results = gate.run()
    assert [name for name, _, _ in results] == [f"PA-0{i}" for i in range(1, 7)]
    failed = [(name, detail) for name, ok, detail in results if not ok]
    assert failed == []


def test_reference_tables_cover_ten_old_and_five_new_sets() -> None:
    assert len(gate.PRE_PHASE_HASHES) == 10
    assert set(gate.PRE_PHASE_FILE_SHA256) == set(gate.PRE_PHASE_HASHES)
    assert len(gate.NEW_SET_IDS) == 5
    assert set(gate.NEW_SET_IDS).isdisjoint(gate.PRE_PHASE_HASHES)
    assert len(gate.load_pins()) == 15


def test_pa01_passes_on_copy(params_copy: Path) -> None:
    assert gate.check_pins(params_copy, gate.load_pins()) == []


def test_pa01_unpinned_extra_file_fails(params_copy: Path) -> None:
    src = params_copy / "range-mr" / "baseline-v4.toml"
    shutil.copyfile(src, params_copy / "range-mr" / "baseline-v5.toml")
    problems = gate.check_pins(params_copy, gate.load_pins())
    assert any("range-mr/baseline-v5" in p and "no pinned hash" in p for p in problems)


def test_pa01_orphan_pin_fails(params_copy: Path) -> None:
    (params_copy / "range-mr" / "baseline-v4.toml").unlink()
    problems = gate.check_pins(params_copy, gate.load_pins())
    assert any("range-mr/baseline-v4" in p and "pin without a file" in p for p in problems)


def test_pa01_mutated_value_fails(params_copy: Path) -> None:
    _edit(params_copy, ("range-mr", "baseline-v4"), "cluster_cap = 0.005", "cluster_cap = 0.006")
    problems = gate.check_pins(params_copy, gate.load_pins())
    assert any("range-mr/baseline-v4" in p for p in problems)


def test_pa01_toml_syntax_error_is_attributed_and_does_not_abort(params_copy: Path) -> None:
    bad = params_copy / "range-mr" / "baseline-v4.toml"
    bad.write_text("this is = = not toml\n", encoding="utf-8", newline="\n")
    problems = gate.check_pins(params_copy, gate.load_pins())
    assert any("range-mr/baseline-v4" in p and "load failed" in p for p in problems)
    # The other fourteen sets were still scanned and verified.
    assert not any("pin file unreadable" in p for p in problems)
    assert not any("trend-pullback/baseline-v4" in p for p in problems)


def test_pa02_passes_on_copy(params_copy: Path) -> None:
    assert gate.check_byte_lock(params_copy, gate.PRE_PHASE_FILE_SHA256) == []


def test_pa02_edited_old_file_fails(params_copy: Path) -> None:
    path = params_copy / "trend-pullback" / "baseline-v3.toml"
    with path.open("ab") as fh:
        fh.write(b"# touched\n")
    problems = gate.check_byte_lock(params_copy, gate.PRE_PHASE_FILE_SHA256)
    assert problems == ["trend-pullback/baseline-v3: file bytes changed (byte lock)"]
    # A comment-only edit leaves the parsed hash alone; PA-03 alone would miss it.
    assert gate.check_old_hashes(params_copy, gate.PRE_PHASE_HASHES) == []


def test_pa02_crlf_copy_still_passes(params_copy: Path) -> None:
    path = params_copy / "breakout-retest" / "baseline-v3.toml"
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    path.write_bytes(data)
    assert gate.check_byte_lock(params_copy, gate.PRE_PHASE_FILE_SHA256) == []


def test_pa02_missing_old_file_fails(params_copy: Path) -> None:
    (params_copy / "range-mr" / "baseline-v1.toml").unlink()
    problems = gate.check_byte_lock(params_copy, gate.PRE_PHASE_FILE_SHA256)
    assert problems == ["range-mr/baseline-v1: file missing"]


def test_pa03_changed_old_value_fails(params_copy: Path) -> None:
    _edit(params_copy, ("trend-pullback", "baseline-v2"), "risk_rate = 0.005", "risk_rate = 0.004")
    problems = gate.check_old_hashes(params_copy, gate.PRE_PHASE_HASHES)
    assert len(problems) == 1
    assert problems[0].startswith("trend-pullback/baseline-v2: hash moved")


def test_pa04_passes_on_copy(params_copy: Path) -> None:
    assert gate.check_new_set_facts(params_copy, gate.NEW_SET_IDS) == []


def test_pa04_partial_fill_half_fails(params_copy: Path) -> None:
    _edit(
        params_copy,
        ("trend-pullback", "baseline-v4"),
        "partial_fill_fraction = 1.0",
        "partial_fill_fraction = 0.5",
    )
    problems = gate.check_new_set_facts(params_copy, gate.NEW_SET_IDS)
    assert any("trend-pullback/baseline-v4" in p and "partial_fill_fraction" in p for p in problems)


def test_pa04_maker_entry_fee_fails(params_copy: Path) -> None:
    _edit(
        params_copy,
        ("breakout-retest", "baseline-v4"),
        "fee_rate_entry = 0.0005",
        "fee_rate_entry = 0.0002",
    )
    problems = gate.check_new_set_facts(params_copy, gate.NEW_SET_IDS)
    assert any("breakout-retest/baseline-v4" in p and "D036" in p for p in problems)


def test_pa04_wrong_working_type_fails(params_copy: Path) -> None:
    _edit(
        params_copy,
        ("range-mr", "baseline-v4"),
        'working_type = "MARK_PRICE"',
        'working_type = "CONTRACT_PRICE"',
    )
    problems = gate.check_new_set_facts(params_copy, gate.NEW_SET_IDS)
    # The registry now rejects CONTRACT_PRICE at load (WR-08), so PA-04 reports a load failure.
    assert any(
        "range-mr/baseline-v4" in p and ("D037" in p or "working_type" in p) for p in problems
    )


def test_pa04_wrong_version_and_missing_supersedes_fail(params_copy: Path) -> None:
    key = ("trend-pullback", "baseline-no-trade-v2")
    _edit(params_copy, key, 'strategy_version = "v3.0.0"', 'strategy_version = "v2.0.0"')
    _edit(params_copy, key, "Supersedes", "Replaces")
    problems = gate.check_new_set_facts(params_copy, gate.NEW_SET_IDS)
    assert any("strategy_version" in p for p in problems)
    assert any("Supersedes" in p for p in problems)


def test_pa05_passes_on_copy(params_copy: Path) -> None:
    assert gate.check_cost_hash_parity(params_copy, gate.NEW_SET_IDS) == []


def test_pa05_different_fee_fails(params_copy: Path) -> None:
    _edit(
        params_copy,
        ("trend-pullback", "baseline-simple-trend-v2"),
        "fee_rate_exit = 0.0005",
        "fee_rate_exit = 0.0006",
    )
    problems = gate.check_cost_hash_parity(params_copy, gate.NEW_SET_IDS)
    assert any("cost_model_hash differs" in p for p in problems)


def test_pa05_non_cost_difference_is_ignored(params_copy: Path) -> None:
    # minimum_rr is a strategy knob, not a cost key: the shared cost hash must hold.
    assert gate.check_cost_hash_parity(params_copy, gate.NEW_SET_IDS) == []
    _edit(params_copy, ("trend-pullback", "baseline-v4"), "minimum_rr = 2.0", "minimum_rr = 3.0")
    assert gate.check_cost_hash_parity(params_copy, gate.NEW_SET_IDS) == []


def test_pa06_working_type_registry_facts() -> None:
    assert gate.check_working_type_registry() == []
