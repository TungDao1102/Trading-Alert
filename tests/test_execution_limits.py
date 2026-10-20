"""The execution-limits file and its fail-closed loader (Phase 19, plan 19-01; D-07, D-13).

The real repository file holds only NOT_CONFIGURED, so every field loads as None and the
live-readiness check refuses naming every key (five since the owner's 19-REVIEW WR-05 decision
added `protection.entry_unknown_grace_ms`). Values used in the positive cases are
TEST_ONLY values from `tests/support/execution_limits.py`, never ratified numbers.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from src.execution import execution_limits as el

from tests.support import execution_limits as tl
from tests.support.ast_guards import forbidden_imports

ROOT = Path(__file__).resolve().parents[1]
LIMITS_FILE = ROOT / "config" / "execution" / "execution-limits-v1.toml"
LIMITS_MODULE = ROOT / "src" / "execution" / "execution_limits.py"

EXPECTED_UNSET = (
    "protection.max_unprotected_ms",
    "protection.entry_terminal_timeout_ms",
    "protection.entry_unknown_grace_ms",
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
    assert limits.entry_unknown_grace_ms is None
    assert limits.min_remaining_validity_seconds is None
    assert limits.max_mark_price_age_ms is None
    assert limits.unset_keys() == EXPECTED_UNSET


def test_require_live_ready_refuses_naming_every_key() -> None:
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
    assert limits.entry_unknown_grace_ms == 12
    assert limits.min_remaining_validity_seconds == 10
    assert limits.max_mark_price_age_ms == 11
    assert limits.unset_keys() == ()
    assert limits.require_live_ready() is None


def test_the_module_imports_only_the_standard_library() -> None:
    offences = forbidden_imports(
        LIMITS_MODULE, ("src.adapters", "binance*", "sqlalchemy", "pydantic")
    )
    assert offences == []


# --------------------------------------------------------------------------- #
# The validation matrix: every refusal names the key or section and never the value.
# --------------------------------------------------------------------------- #

_KEY = "protection.max_unprotected_ms"
_PROV_KEY = "provenance.protection.max_unprotected_ms"


def _document() -> dict[str, Any]:
    """A valid all-set document built from the TEST_ONLY values."""
    document: dict[str, Any] = {"provenance": {}}
    for dotted, value in tl.TEST_ONLY_EXECUTION_LIMIT_VALUES.items():
        section, key = dotted.split(".", 1)
        document.setdefault(section, {})[key] = value
        document["provenance"].setdefault(section, {})[key] = "DECISION"
    return document


def _set(document: dict[str, Any], dotted: str, value: Any) -> dict[str, Any]:
    *parents, last = dotted.split(".")
    node = document
    for part in parents:
        node = node[part]
    node[last] = value
    return document


def _drop(document: dict[str, Any], dotted: str) -> dict[str, Any]:
    *parents, last = dotted.split(".")
    node = document
    for part in parents:
        node = node[part]
    del node[last]
    return document


def _extra_key(document: dict[str, Any]) -> dict[str, Any]:
    document["protection"]["surprise_ms"] = 5
    return document


def _extra_section(document: dict[str, Any]) -> dict[str, Any]:
    document["surprise"] = {"x": 5}
    return document


def _section_not_table(document: dict[str, Any]) -> dict[str, Any]:
    document["protection"] = "oops"
    return document


def _drop_provenance(document: dict[str, Any]) -> dict[str, Any]:
    del document["provenance"]
    return document


def _unknown_provenance_section(document: dict[str, Any]) -> dict[str, Any]:
    document["provenance"]["surprise"] = {}
    return document


def _unknown_provenance_key(document: dict[str, Any]) -> dict[str, Any]:
    document["provenance"]["protection"]["surprise_ms"] = "DECISION"
    return document


def _unset_with_decision_label(document: dict[str, Any]) -> dict[str, Any]:
    return _set(_set(document, _KEY, "NOT_CONFIGURED"), _PROV_KEY, "DECISION")


# (case id, mutation, text the message must name, offending value text it must not carry)
_REFUSALS: list[tuple[str, Any, str, str]] = [
    ("missing key", lambda d: _drop(d, _KEY), _KEY, ""),
    ("unknown key", _extra_key, "protection.surprise_ms", ""),
    ("unknown section", _extra_section, "surprise", ""),
    ("section not a table", _section_not_table, "protection", "oops"),
    ("bool value", lambda d: _set(d, _KEY, True), _KEY, "True"),
    ("float value", lambda d: _set(d, _KEY, 5.5), _KEY, "5.5"),
    ("zero", lambda d: _set(d, _KEY, 0), _KEY, ""),
    ("negative", lambda d: _set(d, _KEY, -987), _KEY, "987"),
    ("other string", lambda d: _set(d, _KEY, "none"), _KEY, ""),
    ("numeric string", lambda d: _set(d, _KEY, "4242"), _KEY, "4242"),
    ("missing provenance table", _drop_provenance, "provenance", ""),
    ("missing provenance label", lambda d: _drop(d, _PROV_KEY), _KEY, ""),
    ("placeholder label", lambda d: _set(d, _PROV_KEY, "PLACEHOLDER"), "PLACEHOLDER", ""),
    ("int with NOT_CONFIGURED label", lambda d: _set(d, _PROV_KEY, "NOT_CONFIGURED"), _KEY, ""),
    ("unset value with DECISION label", _unset_with_decision_label, _KEY, ""),
    ("unknown label", lambda d: _set(d, _PROV_KEY, "WHIM"), _KEY, "WHIM"),
    ("non-string label", lambda d: _set(d, _PROV_KEY, 7), _KEY, ""),
    ("unknown provenance section", _unknown_provenance_section, "provenance.surprise", ""),
    ("unknown provenance key", _unknown_provenance_key, "provenance.protection.surprise_ms", ""),
    (
        "provenance section not a table",
        lambda d: _set(d, "provenance.protection", "oops"),
        "provenance.protection",
        "oops",
    ),
]


def test_the_valid_baseline_document_loads() -> None:
    limits = el.parse_execution_limits(_document())
    assert limits == tl.test_only_execution_limits()


@pytest.mark.parametrize(
    ("mutate", "named", "value_text"),
    [pytest.param(m, n, v, id=case) for case, m, n, v in _REFUSALS],
)
def test_every_malformed_document_is_refused_by_name(
    mutate: Any, named: str, value_text: str
) -> None:
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(mutate(_document()))
    message = str(info.value)
    assert named in message
    if value_text:
        assert value_text not in message


def test_all_problems_are_reported_together() -> None:
    document = _drop(_set(_document(), "protection.entry_terminal_timeout_ms", 0), _KEY)
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(document)
    assert len(info.value.problems) == 2


def test_a_mixed_document_loads_and_lists_only_the_unset_keys() -> None:
    document = _document()
    for dotted in (
        "pre_placement.min_remaining_validity_seconds",
        "pre_placement.max_mark_price_age_ms",
    ):
        _set(document, dotted, "NOT_CONFIGURED")
        _set(document, f"provenance.{dotted}", "NOT_CONFIGURED")
    limits = el.parse_execution_limits(document)
    assert limits.max_unprotected_ms == tl.TEST_ONLY_EXECUTION_LIMIT_VALUES[_KEY]
    assert limits.unset_keys() == (
        "pre_placement.min_remaining_validity_seconds",
        "pre_placement.max_mark_price_age_ms",
    )
    with pytest.raises(el.ExecutionLimitsNotConfigured) as info:
        limits.require_live_ready()
    assert info.value.keys == limits.unset_keys()


def test_the_dataclass_has_no_defaults() -> None:
    with pytest.raises(TypeError):
        el.ExecutionLimits()  # type: ignore[call-arg]


# --------------------------------------------------------------------------- #
# The file loader and the TEST_ONLY writer.
# --------------------------------------------------------------------------- #


def test_a_missing_file_is_refused_without_a_path(tmp_path: Path) -> None:
    missing = tmp_path / "absent.toml"
    with pytest.raises(el.ExecutionLimitsFileMissing) as info:
        el.load_execution_limits(missing)
    assert str(tmp_path) not in str(info.value)
    assert "absent" not in str(info.value)


def test_invalid_toml_is_refused_without_a_path(tmp_path: Path) -> None:
    broken = tmp_path / "broken.toml"
    broken.write_text("[protection\nx = ", encoding="utf-8")
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.load_execution_limits(broken)
    assert str(tmp_path) not in str(info.value)


def test_round_trip_of_the_test_only_values(tmp_path: Path) -> None:
    path = tl.write_execution_limits_toml(
        tmp_path / "limits.toml", values=tl.TEST_ONLY_EXECUTION_LIMIT_VALUES
    )
    assert el.load_execution_limits(path) == tl.test_only_execution_limits()


def test_round_trip_of_an_all_unset_document(tmp_path: Path) -> None:
    values = dict.fromkeys(tl.TEST_ONLY_EXECUTION_LIMIT_VALUES)
    path = tl.write_execution_limits_toml(tmp_path / "limits.toml", values=values)
    limits = el.load_execution_limits(path)
    assert limits == tl.test_only_execution_limits(
        max_unprotected_ms=None,
        entry_terminal_timeout_ms=None,
        entry_unknown_grace_ms=None,
        min_remaining_validity_seconds=None,
        max_mark_price_age_ms=None,
    )
    assert limits.unset_keys() == EXPECTED_UNSET


def test_the_writer_can_write_a_bad_label_for_refusal_tests(tmp_path: Path) -> None:
    path = tl.write_execution_limits_toml(
        tmp_path / "limits.toml",
        values=tl.TEST_ONLY_EXECUTION_LIMIT_VALUES,
        provenance={_KEY: "PLACEHOLDER"},
    )
    with pytest.raises(el.ExecutionLimitsInvalid):
        el.load_execution_limits(path)


# --------------------------------------------------------------------------- #
# config/execution/README.md: the required keys, no values.
# --------------------------------------------------------------------------- #

README = ROOT / "config" / "execution" / "README.md"
_KEY_LINE = re.compile(r"^- `([a-z_]+)\.([a-z0-9_]+)` - \S")


def test_the_readme_lists_exactly_the_execution_limit_keys() -> None:
    keys = [
        (match.group(1), match.group(2))
        for line in README.read_text(encoding="utf-8").splitlines()
        if (match := _KEY_LINE.match(line))
    ]
    expected = [(s, k) for s, names in el.EXECUTION_LIMIT_KEYS.items() for k in names]
    assert keys == expected


def test_the_readme_carries_no_value_and_states_the_rules() -> None:
    text = README.read_text(encoding="utf-8")
    for names in el.EXECUTION_LIMIT_KEYS.values():
        for name in names:
            assert not re.search(rf"\b{name}\b`?\s*[=:]\s*[-+]?\d", text), name
    for word in ("NOT_CONFIGURED", "PLACEHOLDER", "DECISION", "no default", "sha256"):
        assert word in text, word
    assert "entry_terminal_timeout_ms" in text


def test_the_committed_file_names_only_the_not_configured_word() -> None:
    text = LIMITS_FILE.read_text(encoding="utf-8")
    assert not re.search(r"^\s*[a-z_]+\s*=\s*[-+]?\d", text, flags=re.MULTILINE)
    # Five keys, each with a value and a provenance label (19-REVIEW WR-05 added the fifth).
    assert text.count(f'"{el.NOT_CONFIGURED_WORD}"') == 10


def test_the_test_only_helper_rejects_an_unknown_field() -> None:
    with pytest.raises(TypeError):
        tl.test_only_execution_limits(bogus=1)
