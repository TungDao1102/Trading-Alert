"""Freeze monitor tests — pinned-epoch + diff-proof per-epoch evidence (Phase 7, plan 07-04).

Per D-04: the soak pins its registry version at start (parameterSetId +
parameterSetHash, cost keys included via the 07.1 binding gate). Any
registry diff against the pinned set halts the stream's evidence claim:
the change is rejected-or-logged with a new stream epoch, and evidence
windows are per-epoch. The PAPER-03 acceptance artifact is the diff log
showing the pinned hash untouched for the whole window.

The tests load the golden fixture pair (input.json + expected.json)
from `tests/fixtures/phase7/pinned_epoch_clean/` and
`tests/fixtures/phase7/epoch_rollover/`, drive the freeze module, and
assert:

  1. pin_stream_epoch on a consistent registry returns the pinned
     (parameterSetId, parameterSetHash) tuple and writes the epoch-open
     record; a mismatched cost model raises CostModelBindingMismatch
     before any record exists.
  2. check_registry_unchanged with an untouched registry appends a
     clean diff-log entry and keeps the epoch; with a changed file it
     opens a new epoch, halts the old evidence claim with REGISTRY_DIFF,
     and never rewrites the old pinned hash.
  3. Absent cost-slice keys propagate as bare KeyError, never
     translated and never skipped.
  4. The CLI check appends one JSONL line per tick carrying epoch_id
     and outcome clean to the given diff-log path.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

PHASE7_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase7"


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _load_input(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "input.json").read_text(encoding="utf-8"))


def _load_expected(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))


def _parse_utc(raw: str) -> datetime:
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        raise ValueError(f"naive datetime in fixture: {raw!r}")
    return value.astimezone(UTC)


def _copy_registry_to(tmp_registry_root: Path, source_root: Path) -> None:
    """Copy the real params/ tree into a tmp registry root.

    Used by the rollover test to mutate a copy without touching the
    real registry files.
    """
    if tmp_registry_root.exists():
        shutil.rmtree(tmp_registry_root)
    shutil.copytree(source_root, tmp_registry_root)


def _mutate_toml_value(
    path: Path,
    *,
    key: str,
    new_value: str,
) -> None:
    """Replace `key = <old>` with `key = <new_value>` in a TOML file.

    Naive line-level replacement — sufficient for the freeze test
    because the registry loader re-parses the file on every read.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{key} ="):
            # Preserve leading whitespace.
            indent = line[: len(line) - len(line.lstrip())]
            lines[i] = f"{indent}{key} = {new_value}"
            break
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Beh. 1 — pin_stream_epoch on a consistent registry returns the pinned
# (parameterSetId, parameterSetHash) tuple and writes the epoch-open
# record.
# --------------------------------------------------------------------------- #


def test_pin_stream_epoch_returns_pinned_tuple_on_clean_registry() -> None:
    """Beh. 1: pin_stream_epoch on a consistent registry returns the
    pinned (parameterSetId, parameterSetHash) tuple and writes the
    epoch-open record.

    Per D-04: the soak pins its registry version at start. The pinned
    tuple is the canonical identity for the running stream epoch. The
    epoch_id is derived from (parameterSetId, parameterSetHash,
    opened_at_utc) so two streams opened at different times against
    the same registry get distinct epoch_ids.
    """
    from src.paper.freeze import pin_stream_epoch

    case_dir = PHASE7_FIXTURES_DIR / "pinned_epoch_clean"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    opened_at_utc = _parse_utc(case_input["opened_at_utc"])

    epoch = pin_stream_epoch(
        strategy_id=case_input["strategy_id"],
        parameter_set_id=case_input["parameter_set_id"],
        opened_at_utc=opened_at_utc,
    )

    # The pinned tuple is the canonical identity for the running stream.
    assert epoch.parameter_set_id == expected["parameter_set_id"]
    assert epoch.evidence_claim_open is True
    assert epoch.opened_at_utc == opened_at_utc

    # The parameter_set_hash is a 64-hex SHA256 string (D-04 byte-stability).
    assert isinstance(epoch.parameter_set_hash, str)
    assert len(epoch.parameter_set_hash) == 64
    assert all(c in "0123456789abcdef" for c in epoch.parameter_set_hash)

    # The epoch_id is a 64-hex SHA256 string derived from the pinned tuple.
    assert isinstance(epoch.epoch_id, str)
    assert len(epoch.epoch_id) == 64
    assert all(c in "0123456789abcdef" for c in epoch.epoch_id)


# --------------------------------------------------------------------------- #
# Beh. 2 — pin_stream_epoch with a mismatched cost model raises
# CostModelBindingMismatch before any record exists.
# --------------------------------------------------------------------------- #


def test_pin_stream_epoch_raises_cost_model_binding_mismatch_on_mismatch() -> None:
    """Beh. 2: pin_stream_epoch with a mismatched cost model raises
    CostModelBindingMismatch before any record exists.

    Per D-04 + 07.1 D-01: the binding gate refuses registry-inconsistent
    cost models. The freeze module reuses the 07.1 binding gate so a
    mismatched cost model fails the pin before any StreamEpoch is
    constructed. The exception is distinct from ExperimentReproducibilityBroken
    (replay drift) — this is assembly refusal.
    """
    from src.backtest.binding import CostModelBindingMismatch
    from src.backtest.costs import build_cost_model
    from src.paper.freeze import pin_stream_epoch

    # Build a cost model with a deliberately wrong fee_rate_entry.
    mismatched_cost_model = build_cost_model(
        {
            "fee_rate_entry": "0.0009",  # registry has 0.0002
            "fee_rate_exit": "0.0005",
            "funding_treatment": "ADDITIVE",
            "expected_slippage": "0.0001",
            "slippage_model": "FIXED_BPS",
            "spread_fill_assumptions": "FULL_FILL",
            "partial_fill_fraction": "0.5",
        }
    )

    with pytest.raises(CostModelBindingMismatch):
        pin_stream_epoch(
            strategy_id="trend-pullback",
            parameter_set_id="baseline-v3",
            opened_at_utc=datetime(2026, 9, 19, 10, 0, tzinfo=UTC),
            cost_model=mismatched_cost_model,
        )


# --------------------------------------------------------------------------- #
# Beh. 3 — check_registry_unchanged with an untouched registry appends a
# clean diff-log entry and keeps the epoch.
# --------------------------------------------------------------------------- #


def test_check_registry_unchanged_appends_clean_entry_and_keeps_epoch(
    tmp_path: Path,
) -> None:
    """Beh. 3: check_registry_unchanged with an untouched registry
    appends a clean diff-log entry and keeps the epoch.

    Per D-04: a clean tick (no registry diff) appends one JSONL line
    carrying the pinned hash and outcome "clean". The current_epoch
    equals the pinned_epoch (no rollover). The pinned_epoch is
    returned unchanged (frozen dataclass, never mutated).
    """
    from src.paper.freeze import check_registry_unchanged, pin_stream_epoch

    case_dir = PHASE7_FIXTURES_DIR / "pinned_epoch_clean"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    opened_at_utc = _parse_utc(case_input["opened_at_utc"])
    now_utc = _parse_utc(case_input["now_utc"])

    # Pin against the real registry.
    pinned_epoch = pin_stream_epoch(
        strategy_id=case_input["strategy_id"],
        parameter_set_id=case_input["parameter_set_id"],
        opened_at_utc=opened_at_utc,
    )

    diff_log_path = tmp_path / "registry_diff.jsonl"
    outcome = check_registry_unchanged(
        pinned_epoch,
        diff_log_path=diff_log_path,
        now_utc=now_utc,
    )

    # Clean tick: current_epoch equals pinned_epoch, no halt.
    assert outcome.current_epoch == pinned_epoch
    assert outcome.halted_epoch is None
    assert outcome.halted is False
    assert outcome.halted_reason == ""

    # The diff entry is appended to the log.
    assert diff_log_path.is_file()
    lines = diff_log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, f"expected 1 diff-log line, got {len(lines)}"
    entry = json.loads(lines[0])
    assert entry["epoch_id"] == pinned_epoch.epoch_id
    assert entry["pinned_hash"] == pinned_epoch.parameter_set_hash
    assert entry["current_hash"] == pinned_epoch.parameter_set_hash
    assert entry["outcome"] == expected["diff_outcome"]


# --------------------------------------------------------------------------- #
# Beh. 4 — check_registry_unchanged with a changed registry opens a new
# epoch, halts the old evidence claim with REGISTRY_DIFF, and never
# rewrites the old pinned hash.
# --------------------------------------------------------------------------- #


def test_check_registry_unchanged_opens_new_epoch_on_diff(tmp_path: Path) -> None:
    """Beh. 4: check_registry_unchanged with a changed registry opens a
    new epoch, halts the old evidence claim with REGISTRY_DIFF, and
    never rewrites the old pinned hash.

    Per D-04: a registry diff against the pinned set halts the stream's
    evidence claim. The change is logged with a new stream epoch, and
    evidence windows are per-epoch. The pinned hash of the running
    window is never rewritten — the old epoch's parameter_set_hash
    string is preserved on the halted copy.
    """
    from src.paper.freeze import check_registry_unchanged, pin_stream_epoch

    case_dir = PHASE7_FIXTURES_DIR / "epoch_rollover"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    # Copy the real registry into a tmp root so we can mutate it.
    real_registry_root = Path(__file__).resolve().parents[1] / "params"
    tmp_registry_root = tmp_path / "params"
    _copy_registry_to(tmp_registry_root, real_registry_root)

    opened_at_utc_epoch1 = _parse_utc(case_input["opened_at_utc_epoch1"])
    now_utc_epoch2 = _parse_utc(case_input["now_utc_epoch2"])

    # Pin epoch 1 against the tmp registry (untouched).
    pinned_epoch = pin_stream_epoch(
        strategy_id=case_input["strategy_id"],
        parameter_set_id=case_input["parameter_set_id"],
        opened_at_utc=opened_at_utc_epoch1,
        registry_root=tmp_registry_root,
    )

    # Mutate one parameter value to trigger a registry diff.
    target_file = (
        tmp_registry_root / case_input["strategy_id"] / f"{case_input['parameter_set_id']}.toml"
    )
    _mutate_toml_value(
        target_file,
        key=case_input["mutated_key"],
        new_value=case_input["mutated_value"],
    )

    # Check the registry — expect rollover.
    diff_log_path = tmp_path / "registry_diff.jsonl"
    outcome = check_registry_unchanged(
        pinned_epoch,
        registry_root=tmp_registry_root,
        diff_log_path=diff_log_path,
        now_utc=now_utc_epoch2,
    )

    # The new epoch differs from the pinned epoch.
    assert outcome.current_epoch.epoch_id != pinned_epoch.epoch_id, (
        "rollover must produce a new epoch_id"
    )
    assert outcome.current_epoch.parameter_set_id == pinned_epoch.parameter_set_id
    assert outcome.current_epoch.opened_at_utc == now_utc_epoch2
    assert outcome.current_epoch.evidence_claim_open is True

    # The old epoch is halted with REGISTRY_DIFF.
    assert outcome.halted is True
    assert outcome.halted_reason == expected["halted_reason"]
    assert outcome.halted_epoch is not None
    assert outcome.halted_epoch.evidence_claim_open is False
    # The old pinned hash is preserved on the halted copy (D-04).
    assert outcome.halted_epoch.parameter_set_hash == pinned_epoch.parameter_set_hash, (
        "halted epoch must preserve the old pinned hash (D-04)"
    )
    assert outcome.halted_epoch.epoch_id == pinned_epoch.epoch_id

    # The pinned_epoch itself is unchanged (frozen dataclass).
    assert pinned_epoch.evidence_claim_open is True
    assert pinned_epoch.parameter_set_hash == outcome.halted_epoch.parameter_set_hash

    # The diff entry is appended with REGISTRY_DIFF outcome.
    assert diff_log_path.is_file()
    lines = diff_log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["epoch_id"] == pinned_epoch.epoch_id
    assert entry["pinned_hash"] == pinned_epoch.parameter_set_hash
    assert entry["current_hash"] != pinned_epoch.parameter_set_hash
    assert entry["outcome"] == expected["diff_outcome"]


# --------------------------------------------------------------------------- #
# Beh. 5 — absent cost-slice keys propagate as bare KeyError, never
# translated and never skipped.
# --------------------------------------------------------------------------- #


def test_pin_stream_epoch_propagates_keyerror_for_missing_cost_keys() -> None:
    """Beh. 5: pin_stream_epoch with a parameter set missing cost-slice
    keys propagates bare KeyError from build_cost_model.

    Per D-04 + 07.1 D-02: the binding gate reads the registry slice
    and lets build_cost_model raise the bare KeyError it already raises
    on absent keys — never translates it into CostModelBindingMismatch
    (which is reserved for the present-but-unequal path), never skips
    the check (silent defaults are forbidden by the project fail-closed
    posture). baseline-v2 has only 3 of 7 COST_KEYS, so it takes this
    path.
    """
    from src.paper.freeze import pin_stream_epoch

    with pytest.raises(KeyError):
        pin_stream_epoch(
            strategy_id="trend-pullback",
            parameter_set_id="baseline-v2",
            opened_at_utc=datetime(2026, 9, 19, 10, 0, tzinfo=UTC),
        )


# --------------------------------------------------------------------------- #
# Beh. 6 — CLI check appends one JSONL line per tick carrying epoch_id
# and outcome clean to the given diff-log path.
# --------------------------------------------------------------------------- #


def test_cli_check_appends_clean_diff_log_entry(tmp_path: Path) -> None:
    """Beh. 6: the CLI check appends one JSONL line per tick carrying
    epoch_id and outcome clean to the given diff-log path.

    Per D-04: the PAPER-03 acceptance artifact is the diff log. The CLI
    is the periodic invoker (hourly cron or operator process). A clean
    tick must append exactly one JSONL line with the pinned epoch_id
    and outcome "clean".
    """
    from src.paper.freeze import run_check_cli

    case_dir = PHASE7_FIXTURES_DIR / "pinned_epoch_clean"
    case_input = _load_input(case_dir)

    # Copy the real registry into a tmp root so the CLI uses a stable
    # registry state.
    real_registry_root = Path(__file__).resolve().parents[1] / "params"
    tmp_registry_root = tmp_path / "params"
    _copy_registry_to(tmp_registry_root, real_registry_root)

    # Write a pinned state file the CLI can load.
    pinned_state_path = tmp_path / "pinned_epoch.json"
    pinned_state = {
        "epoch_id": "0" * 64,
        "strategy_id": case_input["strategy_id"],
        "parameter_set_id": case_input["parameter_set_id"],
        "parameter_set_hash": "0" * 64,
        "opened_at_utc": case_input["opened_at_utc"],
        "evidence_claim_open": True,
    }
    pinned_state_path.write_text(json.dumps(pinned_state), encoding="utf-8")

    diff_log_path = tmp_path / "registry_diff.jsonl"
    now_utc = _parse_utc(case_input["now_utc"])

    # The CLI will load the pinned state, re-read the registry, and
    # append a diff-log entry. Since the pinned hash in the state file
    # is all-zeros (not the real hash), the CLI will detect a diff and
    # log REGISTRY_DIFF. To test the "clean" path, we need the pinned
    # hash to match the real registry hash.
    from src.paper.freeze import pin_stream_epoch

    real_epoch = pin_stream_epoch(
        strategy_id=case_input["strategy_id"],
        parameter_set_id=case_input["parameter_set_id"],
        opened_at_utc=_parse_utc(case_input["opened_at_utc"]),
        registry_root=tmp_registry_root,
    )
    pinned_state["epoch_id"] = real_epoch.epoch_id
    pinned_state["parameter_set_hash"] = real_epoch.parameter_set_hash
    pinned_state_path.write_text(json.dumps(pinned_state), encoding="utf-8")

    # Run the CLI check.
    exit_code = run_check_cli(
        strategy_id=case_input["strategy_id"],
        parameter_set_id=case_input["parameter_set_id"],
        pinned_state_path=pinned_state_path,
        diff_log_path=diff_log_path,
        registry_root=tmp_registry_root,
        now_utc=now_utc,
    )
    assert exit_code == 0

    # The diff log has exactly one line carrying epoch_id and outcome clean.
    assert diff_log_path.is_file()
    lines = diff_log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, f"expected 1 diff-log line, got {len(lines)}"
    entry = json.loads(lines[0])
    assert entry["epoch_id"] == real_epoch.epoch_id
    assert entry["outcome"] == "clean"
    assert entry["pinned_hash"] == real_epoch.parameter_set_hash
    assert entry["current_hash"] == real_epoch.parameter_set_hash
