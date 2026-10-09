"""Plan 16-02 (D-03, review IN-01): a `PaperAllowlistEntry` validates every field at construction.

The production allowlist is empty by the user's decision (checkpoint 15-17-01, Option B), so an
entry only ever exists because the user approved one later. A malformed entry must fail loudly,
naming the field, instead of sitting in the tuple as a dead entry that only yields a generic
refusal. These tests build entries directly and never touch `params/` or the allowlist itself.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Any

import pytest

from src.domain.rationale import UnrationalizedParameterSet
from src.paper.freeze import PAPER_START_ALLOWLIST, PaperAllowlistEntry, pin_stream_epoch

VALID_HASH = "ab" * 32

VALID_FIELDS: dict[str, Any] = {
    "strategy_id": "trend-pullback",
    "parameter_set_id": "baseline-v3",
    "parameter_set_hash": VALID_HASH,
    "purpose": "test-only entry",
    "approved_at": "2026-10-08",
    "basis": "tests/test_paper_allowlist_entry.py (never production)",
}


def _build(**overrides: Any) -> PaperAllowlistEntry:
    return PaperAllowlistEntry(**{**VALID_FIELDS, **overrides})


def test_a_fully_valid_entry_constructs() -> None:
    entry = _build()
    assert entry.parameter_set_hash == VALID_HASH
    assert entry.approved_at == "2026-10-08"
    assert dataclasses.is_dataclass(entry)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("parameter_set_hash", "AB" * 32),
        ("parameter_set_hash", "ab" * 31 + "a"),
        ("parameter_set_hash", "ab" * 32 + "a"),
        ("parameter_set_hash", "g" + "a" * 63),
        ("parameter_set_hash", ""),
        ("parameter_set_hash", " " + "a" * 63),
        ("parameter_set_hash", "a" * 63 + "\n"),
        ("strategy_id", ""),
        ("strategy_id", "   "),
        ("parameter_set_id", ""),
        ("parameter_set_id", "\t"),
        ("approved_at", "08/10/2026"),
        ("approved_at", ""),
        ("approved_at", "2026-13-01"),
        ("approved_at", "2026-02-30"),
        ("approved_at", "20261008"),
        ("approved_at", "2026-10-08T10:00:00"),
        ("purpose", ""),
        ("purpose", "   "),
        ("basis", ""),
        ("basis", "  "),
    ],
)
def test_a_malformed_field_raises_value_error_naming_the_field(field: str, value: str) -> None:
    with pytest.raises(ValueError, match=field):
        _build(**{field: value})


@pytest.mark.parametrize("field", sorted(VALID_FIELDS))
@pytest.mark.parametrize("value", [None, 7, b"x", ["a"]])
def test_a_non_str_field_raises_type_error_naming_the_field(field: str, value: object) -> None:
    with pytest.raises(TypeError, match=field):
        _build(**{field: value})


def test_the_production_allowlist_is_still_the_empty_tuple() -> None:
    assert PAPER_START_ALLOWLIST == ()


def test_a_valid_injected_entry_still_never_admits_a_set_with_rationale_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing gate behaviour unchanged: baseline-v6 carries PLACEHOLDER keys and stays refused."""
    import src.paper.freeze as freeze
    from src.domain.registry import load_parameter_set

    v6 = load_parameter_set("trend-pullback", "baseline-v6").parameter_set_hash
    monkeypatch.setattr(
        freeze,
        "PAPER_START_ALLOWLIST",
        (_build(parameter_set_id="baseline-v6", parameter_set_hash=v6),),
    )
    with pytest.raises(UnrationalizedParameterSet) as excinfo:
        pin_stream_epoch(
            strategy_id="trend-pullback",
            parameter_set_id="baseline-v6",
            opened_at_utc=datetime(2026, 10, 8, 10, 0, tzinfo=UTC),
        )
    assert "PLACEHOLDER keys" in str(excinfo.value)
