"""Tests for the D039 point-in-time research-universe manifest (Phase 11, plan 11-03)."""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any

import pytest
from scripts.decision_alignment import universe

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "docs" / "research" / "universe" / "research-universe-v1.toml"

SYNTHETIC_SYMBOLS = [f"{c * 3}USDT" for c in "ABCDEFGHIJKL"]


def _real_doc() -> dict[str, Any]:
    with MANIFEST.open("rb") as fh:
        return tomllib.load(fh)


def _draft() -> dict[str, Any]:
    return copy.deepcopy(_real_doc())


def _frozen(symbols: list[str] | None = None) -> dict[str, Any]:
    doc = _draft()
    doc["status"] = "FROZEN"
    doc["symbols"] = list(SYNTHETIC_SYMBOLS if symbols is None else symbols)
    doc["top_n"] = len(doc["symbols"])
    doc["selection_date"] = "2024-01-01"
    doc["content_sha256"] = universe.compute_content_sha256(doc)
    return doc


# ---------------------------------------------------------------- real manifest


def test_real_manifest_validates_with_zero_problems() -> None:
    assert universe.validate_manifest(_real_doc()) == []


def test_real_manifest_is_draft_with_empty_freeze_fields() -> None:
    doc = _real_doc()
    assert doc["schema"] == "research-universe/1"
    assert doc["status"] == "DRAFT"
    assert doc["top_n"] == 12
    assert doc["include_delisted"] is True
    assert doc["symbols"] == []
    assert doc["selection_date"] == ""
    assert doc["content_sha256"] == ""
    assert doc["freeze_owner"] == "Phase 13"


def test_run_gates_un01_to_un05_all_ok() -> None:
    results = universe.run()
    assert [name for name, _, _ in results] == [
        "UN-01",
        "UN-02",
        "UN-03",
        "UN-04",
        "UN-05",
    ]
    assert all(ok for _, ok, _ in results), results


def test_params_universe_directory_does_not_exist() -> None:
    assert not (REPO_ROOT / "params" / "universe").exists()


# ---------------------------------------------------------------- rejections


def _assert_rejected(doc: dict[str, Any], fragment: str) -> None:
    problems = universe.validate_manifest(doc)
    assert problems, "expected at least one problem"
    assert any(fragment in p for p in problems), problems


def test_rejects_wrong_schema() -> None:
    doc = _draft()
    doc["schema"] = "research-universe/2"
    _assert_rejected(doc, "schema")


def test_rejects_unknown_status() -> None:
    doc = _draft()
    doc["status"] = "PENDING"
    _assert_rejected(doc, "status")


@pytest.mark.parametrize("bad", [9, 16, 0, "12", True, 12.0])
def test_rejects_bad_top_n(bad: object) -> None:
    doc = _draft()
    doc["top_n"] = bad
    _assert_rejected(doc, "top_n")


def test_rejects_include_delisted_not_true() -> None:
    doc = _draft()
    doc["include_delisted"] = False
    _assert_rejected(doc, "include_delisted")


def test_rejects_draft_with_symbol() -> None:
    doc = _draft()
    doc["symbols"] = ["AAAUSDT"]
    _assert_rejected(doc, "DRAFT")


def test_rejects_draft_with_selection_date() -> None:
    doc = _draft()
    doc["selection_date"] = "2024-01-01"
    _assert_rejected(doc, "DRAFT")


def test_rejects_draft_with_hash() -> None:
    doc = _draft()
    doc["content_sha256"] = "0" * 64
    _assert_rejected(doc, "DRAFT")


def test_valid_frozen_document_passes() -> None:
    assert universe.validate_manifest(_frozen()) == []


def test_rejects_frozen_symbol_count_differs_from_top_n() -> None:
    doc = _frozen()
    doc["top_n"] = 11
    doc["content_sha256"] = universe.compute_content_sha256(doc)
    _assert_rejected(doc, "top_n")


@pytest.mark.parametrize("count", [9, 16])
def test_rejects_frozen_symbol_count_out_of_range(count: int) -> None:
    symbols = [f"{chr(65 + i) * 3}USDT" for i in range(count)]
    doc = _frozen(symbols)
    _assert_rejected(doc, "10-15")


def test_rejects_duplicate_symbols() -> None:
    symbols = list(SYNTHETIC_SYMBOLS)
    symbols[1] = symbols[0]
    doc = _frozen(symbols)
    _assert_rejected(doc, "duplicate")


@pytest.mark.parametrize("bad", ["btcusdt", "BTCUSD", "USDT", "BTC-USDT", "BTCUSDT "])
def test_rejects_malformed_symbols(bad: str) -> None:
    symbols = list(SYNTHETIC_SYMBOLS)
    symbols[0] = bad
    doc = _frozen(symbols)
    _assert_rejected(doc, "symbol")


@pytest.mark.parametrize("bad", ["", "2024-13-01", "20240101", "2024/01/01", "2024-1-1"])
def test_rejects_frozen_bad_selection_date(bad: str) -> None:
    doc = _frozen()
    doc["selection_date"] = bad
    doc["content_sha256"] = universe.compute_content_sha256(doc)
    _assert_rejected(doc, "selection_date")


def test_rejects_hash_mismatch() -> None:
    doc = _frozen()
    doc["content_sha256"] = "f" * 64
    _assert_rejected(doc, "content_sha256")


def test_rejects_missing_live_universe_note() -> None:
    doc = _draft()
    del doc["live_universe_note"]
    _assert_rejected(doc, "live_universe_note")


def test_rejects_live_universe_note_without_live5_or_unchanged() -> None:
    doc = _draft()
    doc["live_universe_note"] = "some other note"
    _assert_rejected(doc, "live_universe_note")


def test_frozen_reordered_symbols_still_validate() -> None:
    doc = _frozen()
    doc["symbols"] = list(reversed(doc["symbols"]))
    assert universe.validate_manifest(doc) == []


def test_frozen_changed_symbol_fails() -> None:
    doc = _frozen()
    doc["symbols"][0] = "ZZZUSDT"
    _assert_rejected(doc, "content_sha256")
