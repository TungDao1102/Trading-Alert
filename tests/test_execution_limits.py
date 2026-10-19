"""The execution-limits file and its fail-closed loader (Phase 19, plan 19-01; D-07, D-13).

The real repository file holds only NOT_CONFIGURED, so every field loads as None and the
live-readiness check refuses naming the four keys. Values used in the positive cases are
TEST_ONLY values from `tests/support/execution_limits.py`, never ratified numbers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.execution import execution_limits as el

from tests.support.ast_guards import forbidden_imports

ROOT = Path(__file__).resolve().parents[1]
LIMITS_FILE = ROOT / "config" / "execution" / "execution-limits-v1.toml"
LIMITS_MODULE = ROOT / "src" / "execution" / "execution_limits.py"

EXPECTED_UNSET = (
    "protection.max_unprotected_ms",
    "protection.entry_terminal_timeout_ms",
    "pre_placement.min_remaining_validity_seconds",
    "pre_placement.max_mark_price_age_ms",
)


def _all_set_document(label: str = "DECISION") -> dict[str, Any]:
    values: dict[str, dict[str, Any]] = {}
    provenance: dict[str, dict[str, Any]] = {}
    for section, keys in el.EXECUTION_LIMIT_KEYS.items():
        values[section] = {key: 10 + index for index, key in enumerate(keys)}
        provenance[section] = dict.fromkeys(keys, label)
    return {**values, "provenance": provenance}


def test_the_real_file_loads_with_every_field_unset() -> None:
    limits = el.load_execution_limits(LIMITS_FILE)
    assert limits.max_unprotected_ms is None
    assert limits.entry_terminal_timeout_ms is None
    assert limits.min_remaining_validity_seconds is None
    assert limits.max_mark_price_age_ms is None
    assert limits.unset_keys() == EXPECTED_UNSET


def test_require_live_ready_refuses_naming_the_four_keys() -> None:
    limits = el.load_execution_limits(LIMITS_FILE)
    try:
        limits.require_live_ready()
    except el.ExecutionLimitsNotConfigured as exc:
        assert exc.keys == EXPECTED_UNSET
        message = str(exc)
        for key in EXPECTED_UNSET:
            assert key in message
        assert str(ROOT) not in message
        assert "toml" not in message
        assert not any(character.isdigit() for character in message)
    else:  # pragma: no cover - the assertion above must run
        raise AssertionError("require_live_ready did not refuse")


def test_a_fully_set_document_is_live_ready() -> None:
    limits = el.parse_execution_limits(_all_set_document())
    assert limits.max_unprotected_ms == 10
    assert limits.entry_terminal_timeout_ms == 11
    assert limits.min_remaining_validity_seconds == 10
    assert limits.max_mark_price_age_ms == 11
    assert limits.unset_keys() == ()
    assert limits.require_live_ready() is None


def test_the_module_imports_only_the_standard_library() -> None:
    offences = forbidden_imports(
        LIMITS_MODULE, ("src.adapters", "binance*", "sqlalchemy", "pydantic")
    )
    assert offences == []
