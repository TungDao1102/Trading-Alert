"""Tests for the parameter-set gate module (Phase 11, plan 11-02; D036-D038, F-810).

The real-repository test proves gates PA-01..PA-08 hold today; the negative tests run
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
    assert [name for name, _, _ in results] == [f"PA-0{i}" for i in range(1, 9)]
    failed = [(name, detail) for name, ok, detail in results if not ok]
    assert failed == []


def test_reference_tables_cover_ten_old_and_five_new_sets() -> None:
    assert len(gate.PRE_PHASE_HASHES) == 10
    assert set(gate.PRE_PHASE_FILE_SHA256) == set(gate.PRE_PHASE_HASHES)
    assert len(gate.NEW_SET_IDS) == 5
    assert set(gate.NEW_SET_IDS).isdisjoint(gate.PRE_PHASE_HASHES)
    assert len(gate.PHASE12_SET_IDS) == 5
    assert set(gate.PHASE12_SET_IDS).isdisjoint(gate.PRE_PHASE_HASHES)
    assert set(gate.PHASE12_SET_IDS).isdisjoint(gate.NEW_SET_IDS)
    assert len(gate.PHASE15_SET_IDS) == 5
    assert set(gate.PHASE15_SET_IDS).isdisjoint(gate.PRE_PHASE_HASHES)
    assert set(gate.PHASE15_SET_IDS).isdisjoint(gate.NEW_SET_IDS)
    assert set(gate.PHASE15_SET_IDS).isdisjoint(gate.PHASE12_SET_IDS)
    assert len(gate.load_pins()) == 25 + 48  # + research-run-1 (plan 16-45)


def test_pa01_passes_on_copy(params_copy: Path) -> None:
    assert gate.check_pins(params_copy, gate.load_pins()) == []


def test_pa01_unpinned_extra_file_fails(params_copy: Path) -> None:
    src = params_copy / "range-mr" / "baseline-v4.toml"
    shutil.copyfile(src, params_copy / "range-mr" / "baseline-v9.toml")
    problems = gate.check_pins(params_copy, gate.load_pins())
    assert any("range-mr/baseline-v9" in p and "no pinned hash" in p for p in problems)


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


_V5_TREND = ("trend-pullback", "baseline-v5")
_V5_RANGE = ("range-mr", "baseline-v5")


def test_pa07_passes_on_copy(params_copy: Path) -> None:
    assert gate.check_phase12_set_facts(params_copy, gate.PHASE12_SET_IDS) == []


def test_pa07_frozen_constants() -> None:
    from decimal import Decimal

    assert gate.EXPECTED_PHASE12_VERSION == "v4.0.0"
    assert gate.PHASE12_FROZEN == {
        "exit_slippage_rate": Decimal("0.0003"),
        "min_stop_distance_rate": Decimal("0.003"),
        "max_cost_to_risk": Decimal("0.15"),
        "commission_rate_ttl_seconds": 3600,
    }
    assert set(gate.PHASE12_SET_IDS) == {
        ("trend-pullback", "baseline-v5"),
        ("breakout-retest", "baseline-v5"),
        ("range-mr", "baseline-v5"),
        ("trend-pullback", "baseline-no-trade-v3"),
        ("trend-pullback", "baseline-simple-trend-v3"),
    }


@pytest.mark.parametrize(
    "key_line",
    [
        "exit_slippage_rate = 0.0003",
        "min_stop_distance_rate = 0.003",
        "max_cost_to_risk = 0.15",
        "commission_rate_ttl_seconds = 3600",
    ],
)
def test_pa07_missing_key_fails(params_copy: Path, key_line: str) -> None:
    path = params_copy / "trend-pullback" / "baseline-v5.toml"
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [ln for ln in lines if not ln.startswith(key_line)]
    assert len(kept) == len(lines) - 1
    path.write_text("\n".join(kept) + "\n", encoding="utf-8", newline="\n")
    problems = gate.check_phase12_set_facts(params_copy, gate.PHASE12_SET_IDS)
    name = key_line.split(" = ")[0]
    assert any("trend-pullback/baseline-v5" in p and name in p for p in problems)


def test_pa07_changed_frozen_value_fails(params_copy: Path) -> None:
    _edit(params_copy, _V5_RANGE, "max_cost_to_risk = 0.15", "max_cost_to_risk = 0.2")
    problems = gate.check_phase12_set_facts(params_copy, gate.PHASE12_SET_IDS)
    assert any("range-mr/baseline-v5" in p and "max_cost_to_risk" in p for p in problems)


def test_pa07_wrong_version_fails(params_copy: Path) -> None:
    _edit(params_copy, _V5_TREND, 'strategy_version = "v4.0.0"', 'strategy_version = "v3.0.0"')
    problems = gate.check_phase12_set_facts(params_copy, gate.PHASE12_SET_IDS)
    assert any("trend-pullback/baseline-v5" in p and "strategy_version" in p for p in problems)


def test_pa07_header_without_supersedes_fails(params_copy: Path) -> None:
    _edit(params_copy, ("breakout-retest", "baseline-v5"), "Supersedes", "Replaces")
    problems = gate.check_phase12_set_facts(params_copy, gate.PHASE12_SET_IDS)
    assert any("breakout-retest/baseline-v5" in p and "Supersedes" in p for p in problems)


def test_pa07_fee_changed_in_one_set_fails_parity(params_copy: Path) -> None:
    _edit(params_copy, _V5_RANGE, "fee_rate_exit = 0.0005", "fee_rate_exit = 0.0006")
    problems = gate.check_phase12_set_facts(params_copy, gate.PHASE12_SET_IDS)
    assert any("cost values differ" in p and "fee_rate_exit" in p for p in problems)


def test_pa07_fee_above_ceiling_fails_unit_check(params_copy: Path) -> None:
    _edit(params_copy, _V5_TREND, "fee_rate_entry = 0.0005", "fee_rate_entry = 2")
    problems = gate.check_phase12_set_facts(params_copy, gate.PHASE12_SET_IDS)
    assert any("trend-pullback/baseline-v5" in p and "fee_rate_entry" in p for p in problems)


def test_pa07_missing_file_fails(params_copy: Path) -> None:
    (params_copy / "range-mr" / "baseline-v5.toml").unlink()
    problems = gate.check_phase12_set_facts(params_copy, gate.PHASE12_SET_IDS)
    assert "range-mr/baseline-v5: file missing" in problems


def test_broken_v5_set_does_not_disturb_pa04_and_pa05(params_copy: Path) -> None:
    _edit(params_copy, _V5_TREND, "fee_rate_entry = 0.0005", "fee_rate_entry = 0.0006")
    assert gate.check_new_set_facts(params_copy, gate.NEW_SET_IDS) == []
    assert gate.check_cost_hash_parity(params_copy, gate.NEW_SET_IDS) == []
    assert gate.check_phase12_set_facts(params_copy, gate.PHASE12_SET_IDS) != []


# --------------------------------------------------------------------------- PA-08

_P15_TREND = ("trend-pullback", "baseline-v6")
_P15_RANGE = ("range-mr", "baseline-v6")
_P15_NO_TRADE = ("trend-pullback", "baseline-no-trade-v4")
_P15_SIMPLE = ("trend-pullback", "baseline-simple-trend-v4")


def _drop_key(root: Path, key: gate.SetKey, name: str) -> None:
    """Remove ``name`` from [parameters] and its [rationale.<name>] table (stays loadable)."""
    path = root / key[0] / f"{key[1]}.toml"
    kept: list[str] = []
    skipping = False
    dropped_line = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"[rationale.{name}]"):
            skipping = True
            continue
        if skipping:
            if line.strip() == "":
                skipping = False
            continue
        if not dropped_line and line.startswith(f"{name} = "):
            dropped_line = True
            continue
        kept.append(line)
    assert dropped_line, (key, name)
    path.write_text("\n".join(kept) + "\n", encoding="utf-8", newline="\n")


def test_pa08_passes_on_copy(params_copy: Path) -> None:
    assert gate.check_phase15_set_facts(params_copy, gate.PHASE15_SET_IDS) == []


def test_pa08_constants() -> None:
    assert gate.EXPECTED_PHASE15_VERSION == "v5.0.0"
    assert set(gate.PHASE15_SET_IDS) == {
        ("trend-pullback", "baseline-v6"),
        ("breakout-retest", "baseline-v6"),
        ("range-mr", "baseline-v6"),
        ("trend-pullback", "baseline-no-trade-v4"),
        ("trend-pullback", "baseline-simple-trend-v4"),
    }


def test_pa08_wrong_version_fails(params_copy: Path) -> None:
    _edit(params_copy, _P15_TREND, 'strategy_version = "v5.0.0"', 'strategy_version = "v4.0.0"')
    problems = gate.check_phase15_set_facts(params_copy, gate.PHASE15_SET_IDS)
    assert any("trend-pullback/baseline-v6" in p and "strategy_version" in p for p in problems)


def test_pa08_missing_geometry_version_fails(params_copy: Path) -> None:
    _drop_key(params_copy, _P15_RANGE, "geometry_version")
    problems = gate.check_phase15_set_facts(params_copy, gate.PHASE15_SET_IDS)
    assert any("range-mr/baseline-v6" in p and "geometry_version" in p for p in problems)


def test_pa08_wrong_geometry_version_fails(params_copy: Path) -> None:
    _edit(params_copy, _P15_NO_TRADE, "geometry_version = 1", "geometry_version = 0")
    problems = gate.check_phase15_set_facts(params_copy, gate.PHASE15_SET_IDS)
    assert any("baseline-no-trade-v4" in p and "geometry_version" in p for p in problems)


def test_pa08_changed_frozen_guard_value_fails(params_copy: Path) -> None:
    _edit(params_copy, _P15_RANGE, "max_cost_to_risk = 0.15", "max_cost_to_risk = 0.2")
    problems = gate.check_phase15_set_facts(params_copy, gate.PHASE15_SET_IDS)
    assert any("range-mr/baseline-v6" in p and "max_cost_to_risk" in p for p in problems)


def test_pa08_cost_value_differing_between_sets_fails(params_copy: Path) -> None:
    _edit(params_copy, _P15_SIMPLE, "fee_rate_exit = 0.0005", "fee_rate_exit = 0.0006")
    problems = gate.check_phase15_set_facts(params_copy, gate.PHASE15_SET_IDS)
    assert any("cost values differ" in p and "fee_rate_exit" in p for p in problems)


def test_pa08_deleted_rationale_table_fails(params_copy: Path) -> None:
    path = params_copy / "trend-pullback" / "baseline-v6.toml"
    text = path.read_text(encoding="utf-8")
    start = text.index("[rationale.sl_buffer_atr]")
    end = text.index("\n\n", start) + 2
    path.write_text(text[:start] + text[end:], encoding="utf-8", newline="\n")
    problems = gate.check_phase15_set_facts(params_copy, gate.PHASE15_SET_IDS)
    assert any("trend-pullback/baseline-v6" in p and "sl_buffer_atr" in p for p in problems)


def test_pa08_header_without_supersedes_fails(params_copy: Path) -> None:
    _edit(params_copy, _P15_SIMPLE, "Supersedes", "Replaces")
    problems = gate.check_phase15_set_facts(params_copy, gate.PHASE15_SET_IDS)
    assert any("baseline-simple-trend-v4" in p and "Supersedes" in p for p in problems)


def test_pa08_range_mr_without_tp_mode_fails(params_copy: Path) -> None:
    _drop_key(params_copy, _P15_RANGE, "tp_mode")
    problems = gate.check_phase15_set_facts(params_copy, gate.PHASE15_SET_IDS)
    assert any("range-mr/baseline-v6" in p and "tp_mode" in p for p in problems)


@pytest.mark.parametrize("name", ["pivot_left_bars", "pivot_right_bars"])
@pytest.mark.parametrize("key", [_P15_TREND, _P15_RANGE, _P15_NO_TRADE, _P15_SIMPLE])
def test_pa08_missing_pivot_key_fails(params_copy: Path, key: gate.SetKey, name: str) -> None:
    _drop_key(params_copy, key, name)
    problems = gate.check_phase15_set_facts(params_copy, gate.PHASE15_SET_IDS)
    assert any(f"{key[0]}/{key[1]}" in p and name in p for p in problems)


@pytest.mark.parametrize("key", [_P15_TREND, _P15_NO_TRADE, _P15_SIMPLE])
def test_pa08_trend_pullback_without_min_stop_atr_fails(
    params_copy: Path, key: gate.SetKey
) -> None:
    _drop_key(params_copy, key, "min_stop_atr")
    problems = gate.check_phase15_set_facts(params_copy, gate.PHASE15_SET_IDS)
    assert any(f"{key[0]}/{key[1]}" in p and "min_stop_atr" in p for p in problems)
    assert any("ROADMAP criterion 1" in p for p in problems)


def test_pa08_missing_file_fails(params_copy: Path) -> None:
    (params_copy / "trend-pullback" / "baseline-no-trade-v4.toml").unlink()
    problems = gate.check_phase15_set_facts(params_copy, gate.PHASE15_SET_IDS)
    assert "trend-pullback/baseline-no-trade-v4: file missing" in problems


def test_broken_phase15_set_does_not_disturb_pa07(params_copy: Path) -> None:
    _edit(params_copy, _P15_RANGE, "max_cost_to_risk = 0.15", "max_cost_to_risk = 0.2")
    assert gate.check_phase12_set_facts(params_copy, gate.PHASE12_SET_IDS) == []
    assert gate.check_phase15_set_facts(params_copy, gate.PHASE15_SET_IDS) != []


def test_pin_file_key_set_equals_every_recorded_set_table_exactly() -> None:
    expected = (
        set(gate.PRE_PHASE_HASHES)
        | set(gate.NEW_SET_IDS)
        | set(gate.PHASE12_SET_IDS)
        | set(gate.PHASE15_SET_IDS)
        # Plan 16-45: the 48 research-run-1 grid points (16 per family) are pinned too.
        | {
            (family, f"research-run-1-{letter}{n:02d}")
            for family, letter in (
                ("trend-pullback", "a"),
                ("breakout-retest", "b"),
                ("range-mr", "c"),
            )
            for n in range(1, 17)
        }
    )
    assert set(gate.load_pins()) == expected
