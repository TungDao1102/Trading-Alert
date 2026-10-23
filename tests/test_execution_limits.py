"""The execution-limits file and its fail-closed loader (Phase 19, plan 19-01; D-07, D-13).

The real repository file holds only NOT_CONFIGURED, so every field loads as None and the
live-readiness check refuses naming every key (six since the owner's 19-REVIEW WR-05 and WR-03
decisions added `protection.entry_unknown_grace_ms` and
`protection.emergency_close_poll_timeout_ms`; seven since quick task 261020-l4p added
`pre_placement.max_last_price_age_ms`, the own age bound of the last-price check). Values used
in the positive cases are
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
    "protection.emergency_close_poll_timeout_ms",
    "pre_placement.min_remaining_validity_seconds",
    "pre_placement.max_mark_price_age_ms",
    "pre_placement.max_last_price_age_ms",
    # Phase 20 (plan 20-01; D-25, T-H): the seven new keys, in file order.
    "reconcile.tick_interval_ms",
    "reconcile.entry_unknown_probe_count",
    "reconcile.entry_unknown_probe_interval_ms",
    "reconcile.lot_filter_refresh_interval_ms",
    "stale_feed.max_mark_price_age_ms",
    "stale_feed.max_user_data_silence_ms",
    "alerts.dedupe_window_ms",
)

# The dotted Phase 20 keys and the ExecutionLimits field each one loads into. The field is
# "<section>_<key>" because stale_feed.max_mark_price_age_ms shares its key text with
# pre_placement.max_mark_price_age_ms.
PHASE20_FIELDS = {
    "reconcile.tick_interval_ms": "reconcile_tick_interval_ms",
    "reconcile.entry_unknown_probe_count": "reconcile_entry_unknown_probe_count",
    "reconcile.entry_unknown_probe_interval_ms": "reconcile_entry_unknown_probe_interval_ms",
    "reconcile.lot_filter_refresh_interval_ms": "reconcile_lot_filter_refresh_interval_ms",
    "stale_feed.max_mark_price_age_ms": "stale_feed_max_mark_price_age_ms",
    "stale_feed.max_user_data_silence_ms": "stale_feed_max_user_data_silence_ms",
    "alerts.dedupe_window_ms": "alerts_dedupe_window_ms",
    "reconcile.entry_stale_grace_ms": "reconcile_entry_stale_grace_ms",
}


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
    assert limits.emergency_close_poll_timeout_ms is None
    assert limits.min_remaining_validity_seconds is None
    assert limits.max_mark_price_age_ms is None
    assert limits.max_last_price_age_ms is None
    assert limits.unset_keys() == EXPECTED_UNSET
    for field_name in PHASE20_FIELDS.values():
        assert getattr(limits, field_name) is None, field_name


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
        assert "reconcile.tick_interval_ms" in message
        # The fourteen dotted names come in file order: protection, pre_placement, reconcile,
        # stale_feed, alerts.
        assert [part.strip() for part in message.split(": ", 1)[1].split(",")] == list(
            EXPECTED_UNSET
        )
    else:  # pragma: no cover - the assertion above must run
        raise AssertionError("require_live_ready did not refuse")


def test_a_fully_set_document_is_live_ready() -> None:
    limits = el.parse_execution_limits(_all_set_document())
    assert limits.max_unprotected_ms == 10
    assert limits.entry_terminal_timeout_ms == 11
    assert limits.entry_unknown_grace_ms == 12
    assert limits.emergency_close_poll_timeout_ms == 13
    assert limits.min_remaining_validity_seconds == 10
    assert limits.max_mark_price_age_ms == 11
    assert limits.max_last_price_age_ms == 12
    assert limits.reconcile_tick_interval_ms == 10
    assert limits.reconcile_entry_unknown_probe_count == 11
    assert limits.reconcile_entry_unknown_probe_interval_ms == 12
    assert limits.reconcile_lot_filter_refresh_interval_ms == 13
    assert limits.stale_feed_max_mark_price_age_ms == 10
    assert limits.stale_feed_max_user_data_silence_ms == 11
    assert limits.alerts_dedupe_window_ms == 10
    assert limits.unset_keys() == ()
    assert limits.require_live_ready() is None


def _reconcile_document(value: Any = 5, label: str = "DECISION") -> dict[str, Any]:
    """A document whose reconcile.tick_interval_ms is set from literals (plan 20-01, D-25)."""
    document = _phase20_document()
    document["reconcile"]["tick_interval_ms"] = value
    document["provenance"]["reconcile"]["tick_interval_ms"] = label
    return document


def test_a_set_reconcile_tick_interval_loads_into_its_prefixed_field() -> None:
    limits = el.parse_execution_limits(_reconcile_document(5))
    assert limits.reconcile_tick_interval_ms == 5
    assert limits.unset_keys() == ()


def test_a_document_without_the_reconcile_section_is_refused_by_name() -> None:
    document = _reconcile_document()
    del document["reconcile"]
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(document)
    assert "reconcile.tick_interval_ms" in str(info.value)


def test_a_reconcile_key_without_its_provenance_label_is_refused_by_name() -> None:
    document = _reconcile_document()
    del document["provenance"]["reconcile"]["tick_interval_ms"]
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(document)
    message = str(info.value)
    assert "reconcile.tick_interval_ms" in message
    assert "missing provenance label" in message


def test_a_bad_reconcile_tick_interval_value_is_refused_without_the_value() -> None:
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(_reconcile_document(-4711))
    message = str(info.value)
    assert "reconcile.tick_interval_ms" in message
    assert "4711" not in message


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
        "pre_placement.max_last_price_age_ms",
    ):
        _set(document, dotted, "NOT_CONFIGURED")
        _set(document, f"provenance.{dotted}", "NOT_CONFIGURED")
    limits = el.parse_execution_limits(document)
    assert limits.max_unprotected_ms == tl.TEST_ONLY_EXECUTION_LIMIT_VALUES[_KEY]
    assert limits.unset_keys() == (
        "pre_placement.min_remaining_validity_seconds",
        "pre_placement.max_mark_price_age_ms",
        "pre_placement.max_last_price_age_ms",
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
        emergency_close_poll_timeout_ms=None,
        min_remaining_validity_seconds=None,
        max_mark_price_age_ms=None,
        max_last_price_age_ms=None,
        reconcile_tick_interval_ms=None,
        reconcile_entry_unknown_probe_count=None,
        reconcile_entry_unknown_probe_interval_ms=None,
        reconcile_lot_filter_refresh_interval_ms=None,
        stale_feed_max_mark_price_age_ms=None,
        stale_feed_max_user_data_silence_ms=None,
        alerts_dedupe_window_ms=None,
        reconcile_entry_stale_grace_ms=None,
    )
    assert limits.unset_keys() == EXPECTED_UNSET
    assert limits.unset_alert_only_keys() == ("reconcile.entry_stale_grace_ms",)


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
    # Fifteen keys, each with a value and a provenance label (19-REVIEW WR-05 added the fifth,
    # WR-03 the sixth, quick task 261020-l4p the seventh, plan 20-01 the seven Phase 20 keys, plan
    # 20-28 the alert-only reconcile.entry_stale_grace_ms).
    assert text.count(f'"{el.NOT_CONFIGURED_WORD}"') == 30


def test_the_test_only_helper_rejects_an_unknown_field() -> None:
    with pytest.raises(TypeError):
        tl.test_only_execution_limits(bogus=1)


# --------------------------------------------------------------------------- #
# Plan 20-01 (D-25, D-11, D-21, D-23, T-H): the seven Phase 20 keys.
# --------------------------------------------------------------------------- #

_PHASE20_SECTIONS = {"reconcile": 5, "stale_feed": 2, "alerts": 1}


def _phase20_document() -> dict[str, Any]:
    """A valid all-set document whose Phase 20 values come from literals (7, 8, 9, ...)."""
    document = _document()
    for index, dotted in enumerate(PHASE20_FIELDS):
        section, key = dotted.split(".", 1)
        document.setdefault(section, {})[key] = 7 + index
        document["provenance"].setdefault(section, {})[key] = "DECISION"
    return document


def test_the_phase_20_sections_are_in_the_key_table() -> None:
    assert list(el.EXECUTION_LIMIT_KEYS)[:2] == ["protection", "pre_placement"]
    for section, count in _PHASE20_SECTIONS.items():
        assert len(el.EXECUTION_LIMIT_KEYS[section]) == count, section
    dotted_keys = [f"{s}.{k}" for s, keys in el.EXECUTION_LIMIT_KEYS.items() for k in keys]
    # The fourteen required keys plus the alert-only key of plan 20-28, in file order.
    assert [k for k in dotted_keys if k not in el.ALERT_ONLY_LIMIT_KEYS] == list(EXPECTED_UNSET)
    assert el.ALERT_ONLY_LIMIT_KEYS == {"reconcile.entry_stale_grace_ms"}
    assert dotted_keys.index("reconcile.entry_stale_grace_ms") == (
        dotted_keys.index("reconcile.lot_filter_refresh_interval_ms") + 1
    )


def test_the_field_table_names_every_key_once_and_keeps_the_phase_19_field_names() -> None:
    dotted_keys = [f"{s}.{k}" for s, keys in el.EXECUTION_LIMIT_KEYS.items() for k in keys]
    assert sorted(el.EXECUTION_LIMIT_FIELDS) == sorted(dotted_keys)
    assert len(set(el.EXECUTION_LIMIT_FIELDS.values())) == len(dotted_keys)
    for dotted in dotted_keys[:7]:
        assert el.EXECUTION_LIMIT_FIELDS[dotted] == dotted.split(".", 1)[1], dotted
    for dotted, field_name in PHASE20_FIELDS.items():
        assert el.EXECUTION_LIMIT_FIELDS[dotted] == field_name, dotted
    dataclass_fields = set(el.ExecutionLimits.__dataclass_fields__)
    assert dataclass_fields == set(el.EXECUTION_LIMIT_FIELDS.values())


def test_a_fully_set_phase_20_document_loads_every_new_field() -> None:
    limits = el.parse_execution_limits(_phase20_document())
    for index, field_name in enumerate(PHASE20_FIELDS.values()):
        assert getattr(limits, field_name) == 7 + index, field_name
    assert limits.unset_keys() == ()


def test_the_stale_feed_mark_age_is_not_the_pre_placement_mark_age() -> None:
    limits = el.parse_execution_limits(_phase20_document())
    pre_placement = tl.TEST_ONLY_EXECUTION_LIMIT_VALUES["pre_placement.max_mark_price_age_ms"]
    assert limits.max_mark_price_age_ms == pre_placement
    assert limits.stale_feed_max_mark_price_age_ms == 7 + 4
    assert limits.stale_feed_max_mark_price_age_ms != limits.max_mark_price_age_ms


def test_the_phase_20_test_only_values_are_distinct_and_the_tick_is_below_the_deadline() -> None:
    values = tl.TEST_ONLY_EXECUTION_LIMIT_VALUES
    assert values["reconcile.entry_unknown_probe_count"] == 3
    assert values["reconcile.entry_unknown_probe_interval_ms"] == 2345
    assert values["reconcile.lot_filter_refresh_interval_ms"] == 8642
    assert values["stale_feed.max_mark_price_age_ms"] == 3579
    assert values["stale_feed.max_user_data_silence_ms"] == 5791
    assert values["alerts.dedupe_window_ms"] == 6543
    assert (
        values["stale_feed.max_mark_price_age_ms"] != values["pre_placement.max_mark_price_age_ms"]
    )
    assert values["reconcile.tick_interval_ms"] < values["protection.max_unprotected_ms"]
    assert len(set(values.values())) == len(values)


def test_the_test_only_limits_object_carries_every_phase_20_value() -> None:
    limits = tl.test_only_execution_limits()
    for dotted, field_name in PHASE20_FIELDS.items():
        assert getattr(limits, field_name) == tl.TEST_ONLY_EXECUTION_LIMIT_VALUES[dotted], dotted
    assert limits.unset_keys() == ()


_PHASE20_KEYS_UNDER_TEST = (
    "reconcile.entry_unknown_probe_count",
    "stale_feed.max_mark_price_age_ms",
    "alerts.dedupe_window_ms",
)


def _prov(dotted: str) -> str:
    section, key = dotted.split(".", 1)
    return f"provenance.{section}.{key}"


_PHASE20_REFUSALS: list[tuple[str, Any, str]] = [
    ("missing key", lambda d, k: _drop(d, k), ""),
    ("bool value", lambda d, k: _set(d, k, True), "True"),
    ("float value", lambda d, k: _set(d, k, 5.5), "5.5"),
    ("zero", lambda d, k: _set(d, k, 0), ""),
    ("negative", lambda d, k: _set(d, k, -987), "987"),
    ("other string", lambda d, k: _set(d, k, "none"), ""),
    ("numeric string", lambda d, k: _set(d, k, "4242"), "4242"),
    ("missing provenance label", lambda d, k: _drop(d, _prov(k)), ""),
    ("placeholder label", lambda d, k: _set(d, _prov(k), "PLACEHOLDER"), ""),
    ("int with NOT_CONFIGURED label", lambda d, k: _set(d, _prov(k), "NOT_CONFIGURED"), ""),
    (
        "unset value with DECISION label",
        lambda d, k: _set(_set(d, k, "NOT_CONFIGURED"), _prov(k), "DECISION"),
        "",
    ),
    ("unknown label", lambda d, k: _set(d, _prov(k), "WHIM"), "WHIM"),
]


@pytest.mark.parametrize("dotted", _PHASE20_KEYS_UNDER_TEST)
@pytest.mark.parametrize(
    ("mutate", "value_text"),
    [pytest.param(m, v, id=case) for case, m, v in _PHASE20_REFUSALS],
)
def test_every_malformed_phase_20_entry_is_refused_by_name(
    dotted: str, mutate: Any, value_text: str
) -> None:
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(mutate(_phase20_document(), dotted))
    message = str(info.value)
    assert dotted in message
    if value_text:
        assert value_text not in message


@pytest.mark.parametrize("section", sorted(_PHASE20_SECTIONS))
def test_an_unknown_key_in_a_phase_20_section_is_refused(section: str) -> None:
    document = _phase20_document()
    document[section]["surprise_ms"] = 5
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(document)
    assert f"{section}.surprise_ms" in str(info.value)


@pytest.mark.parametrize("section", sorted(_PHASE20_SECTIONS))
def test_a_missing_phase_20_section_is_refused_naming_its_keys(section: str) -> None:
    document = _phase20_document()
    del document[section]
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(document)
    message = str(info.value)
    assert el.EXECUTION_LIMIT_KEYS[section], section
    for key in el.EXECUTION_LIMIT_KEYS[section]:
        assert f"{section}.{key}" in message


def test_the_real_file_has_every_section_and_label_unset() -> None:
    import tomllib

    document = tomllib.loads(LIMITS_FILE.read_text(encoding="utf-8"))
    for section, keys in el.EXECUTION_LIMIT_KEYS.items():
        for key in keys:
            assert document[section][key] == el.NOT_CONFIGURED_WORD, (section, key)
            assert document["provenance"][section][key] == el.NOT_CONFIGURED_WORD, (section, key)


def test_the_readme_separates_the_user_data_silence_key_from_the_paper_runtime_key() -> None:
    text = README.read_text(encoding="utf-8")
    assert "stale_feed.max_user_data_silence_ms" in text
    assert "max_ws_message_silence_seconds" in text
    assert "not the paper runtime" in text
    assert "DECISIONS row" in text


# --------------------------------------------------------------------------- #
# Plan 20-01 (D-25): the reconcile tick must be strictly below max_unprotected_ms.
# --------------------------------------------------------------------------- #


def test_the_cadence_check_does_nothing_while_both_values_are_unset() -> None:
    limits = tl.test_only_execution_limits(reconcile_tick_interval_ms=None, max_unprotected_ms=None)
    assert el.check_reconcile_cadence(limits) is None


def test_the_cadence_check_does_nothing_while_the_tick_is_unset() -> None:
    limits = tl.test_only_execution_limits(reconcile_tick_interval_ms=None)
    assert el.check_reconcile_cadence(limits) is None


def test_the_cadence_check_does_nothing_while_the_deadline_is_unset() -> None:
    limits = tl.test_only_execution_limits(max_unprotected_ms=None)
    assert el.check_reconcile_cadence(limits) is None


def test_a_tick_below_the_deadline_passes_the_cadence_check() -> None:
    limits = tl.test_only_execution_limits()
    assert limits.reconcile_tick_interval_ms == 1234
    assert limits.max_unprotected_ms == 7777
    assert el.check_reconcile_cadence(limits) is None


def _refused_cadence(tick: int, deadline: int) -> el.ExecutionLimitsInvalid:
    limits = tl.test_only_execution_limits(
        reconcile_tick_interval_ms=tick, max_unprotected_ms=deadline
    )
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.check_reconcile_cadence(limits)
    return info.value


def test_a_tick_equal_to_the_deadline_is_refused_naming_both_keys() -> None:
    error = _refused_cadence(4242, 4242)
    message = str(error)
    assert "reconcile.tick_interval_ms" in message
    assert "protection.max_unprotected_ms" in message
    assert error.problems == [
        "reconcile.tick_interval_ms (must be strictly below protection.max_unprotected_ms)"
    ]


def test_a_tick_above_the_deadline_is_refused_naming_both_keys() -> None:
    message = str(_refused_cadence(9191, 4242))
    assert "reconcile.tick_interval_ms" in message
    assert "protection.max_unprotected_ms" in message


def test_the_cadence_refusal_carries_neither_value() -> None:
    for tick, deadline in ((4242, 4242), (9191, 4242)):
        message = str(_refused_cadence(tick, deadline))
        assert str(tick) not in message
        assert str(deadline) not in message
        assert not any(character.isdigit() for character in message)


def test_the_cadence_check_is_exported() -> None:
    assert "check_reconcile_cadence" in el.__all__
