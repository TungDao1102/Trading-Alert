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
# Phase 21 (plan 21-02; D-03, F-012): the sixteenth key, the first required Phase 21 key. The owner
# set it on 2026-10-23 (DECISIONS D084, 15000 ms), so the committed file no longer leaves it unset.
EQUITY_AGE_KEY = "account.max_equity_age_ms"
EQUITY_AGE_DECIDED_MS = 15000
# Phase 21 review WR-05: the daily-loss age, REQUIRED. The owner set 300000 on 2026-10-25
# (DECISIONS D087), so the committed file no longer leaves it unset.
DAILY_LOSS_AGE_KEY = "account.max_daily_loss_age_ms"
DAILY_LOSS_AGE_DECIDED_MS = 300000
# Phase 22 (plan 22-02; D-10, D-11, D-13, amendment A4): the three margin keys, REQUIRED. The owner
# set them on 2026-10-24 (DECISIONS D085, O-2 and O-3), so the committed file no longer leaves
# them unset. The section is the last one, after `account`.
MARGIN_KEYS = (
    "margin.liquidation_buffer_bps",
    "margin.max_bracket_age_ms",
    "margin.headroom_bps",
)
MARGIN_FIELDS = {
    "margin.liquidation_buffer_bps": "margin_liquidation_buffer_bps",
    "margin.max_bracket_age_ms": "margin_max_bracket_age_ms",
    "margin.headroom_bps": "margin_headroom_bps",
}
# The numbers the owner set for the margin keys (DECISIONS D085, 2026-10-24), provenance DECISION.
MARGIN_DECIDED = {
    "margin.liquidation_buffer_bps": 300,
    "margin.max_bracket_age_ms": 60000,
    "margin.headroom_bps": 1000,
}
# The required keys the committed file leaves unset, in file order: since DECISIONS D089 (owner
# answer 2026-10-31) only the user-data silence bound, which the owner did not answer. The equity
# age is set by D084, the three margin keys by D085, the daily-loss age by D087.
COMMITTED_UNSET: tuple[str, ...] = ()  # D091 set the last one (key 14)
# The numbers the owner set for the other Phase 19 and Phase 20 keys (DECISIONS D089, 2026-10-31),
# provenance DECISION; `reconcile.entry_stale_grace_ms` is the alert-only one.
D089_DECIDED = {
    "protection.max_unprotected_ms": 180000,
    "protection.entry_terminal_timeout_ms": 900000,
    "protection.entry_unknown_grace_ms": 1800000,
    "protection.emergency_close_poll_timeout_ms": 30000,
    "pre_placement.min_remaining_validity_seconds": 900,
    "pre_placement.max_mark_price_age_ms": 5000,
    "pre_placement.max_last_price_age_ms": 30000,
    "reconcile.tick_interval_ms": 15000,
    "reconcile.entry_unknown_probe_count": 3,
    "reconcile.entry_unknown_probe_interval_ms": 5000,
    "reconcile.lot_filter_refresh_interval_ms": 3600000,
    "reconcile.entry_stale_grace_ms": 900000,
    "stale_feed.max_mark_price_age_ms": 60000,
    "stale_feed.max_user_data_silence_ms": 420000,  # D091, from the Demo silence probe
    "alerts.dedupe_window_ms": 300000,
}
# Every required key in file order, the equity age included.
ALL_REQUIRED_KEYS = (*EXPECTED_UNSET, EQUITY_AGE_KEY, DAILY_LOSS_AGE_KEY, *MARGIN_KEYS)

# Plan 24-03 (DECISIONS D083 item 4): the clock margin of the 418 ban end time, an OPTIONAL
# REFINEMENT key. It is NOT_CONFIGURED in the committed file (the owner sets it, plan 24-06) and it
# never keeps the live path refused.
BAN_END_MARGIN_KEY = "rest_gate.ban_end_clock_margin_ms"
BAN_END_MARGIN_FIELD = "rest_gate_ban_end_clock_margin_ms"
STALL_KEY = "scheduler.protection_stall_after_ms"
STALL_FIELD = "scheduler_protection_stall_after_ms"
# Quick task 261115-kra (D112): the window of the scheduler duration summary rows, an OPTIONAL
# REFINEMENT key (it switches no alert): unset, only the new-maximum rows are written.
SUMMARY_KEY = "scheduler.duration_summary_interval_ms"
SUMMARY_FIELD = "scheduler_duration_summary_interval_ms"

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


def test_the_real_file_loads_with_the_owner_numbers_and_one_required_key_unset() -> None:
    limits = el.load_execution_limits(LIMITS_FILE)
    for dotted, value in D089_DECIDED.items():
        assert getattr(limits, el.EXECUTION_LIMIT_FIELDS[dotted]) == value, dotted  # D089
    assert limits.account_max_equity_age_ms == EQUITY_AGE_DECIDED_MS
    assert limits.account_max_daily_loss_age_ms == DAILY_LOSS_AGE_DECIDED_MS  # D087
    assert limits.unset_keys() == COMMITTED_UNSET
    for dotted, field_name in MARGIN_FIELDS.items():
        assert getattr(limits, field_name) == MARGIN_DECIDED[dotted], field_name  # D085


def test_the_committed_file_is_live_ready_since_d091() -> None:
    limits = el.load_execution_limits(LIMITS_FILE)
    limits.require_live_ready()  # no key is NOT_CONFIGURED any more (D091 set key 14)
    assert limits.unset_keys() == ()


def test_require_live_ready_refuses_naming_every_key() -> None:
    key = "stale_feed.max_user_data_silence_ms"
    limits = el.load_execution_limits(LIMITS_FILE)
    from dataclasses import replace

    unset = replace(limits, stale_feed_max_user_data_silence_ms=None)
    try:
        unset.require_live_ready()
    except el.ExecutionLimitsNotConfigured as exc:
        assert exc.keys == (key,)
        message = str(exc)
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
    assert limits.account_max_equity_age_ms == 10
    assert limits.account_max_daily_loss_age_ms == 11
    assert limits.margin_liquidation_buffer_bps == 10
    assert limits.margin_max_bracket_age_ms == 11
    assert limits.margin_headroom_bps == 12
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
        unset = value is None  # an alert-only key left NOT_CONFIGURED (D111)
        document.setdefault(section, {})[key] = el.NOT_CONFIGURED_WORD if unset else value
        document["provenance"].setdefault(section, {})[key] = (
            el.NOT_CONFIGURED_WORD if unset else "DECISION"
        )
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
        account_max_equity_age_ms=None,
        account_max_daily_loss_age_ms=None,
        margin_liquidation_buffer_bps=None,
        margin_max_bracket_age_ms=None,
        margin_headroom_bps=None,
        rest_gate_ban_end_clock_margin_ms=None,
        scheduler_protection_stall_after_ms=None,
        scheduler_duration_summary_interval_ms=None,
    )
    assert limits.unset_keys() == ALL_REQUIRED_KEYS
    assert limits.unset_alert_only_keys() == ("reconcile.entry_stale_grace_ms", STALL_KEY)
    # D112 (quick 261115-kra): the summary window is the second optional refinement key.
    assert limits.unset_optional_refinement_keys() == (BAN_END_MARGIN_KEY, SUMMARY_KEY)


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


def test_the_committed_file_names_only_not_configured_except_the_owner_numbers() -> None:
    text = LIMITS_FILE.read_text(encoding="utf-8")
    # The only numbers in the file are the owner's D084 equity age (2026-10-23) and the three
    # D085 margin keys (2026-10-24) and the D087 daily-loss age (2026-10-25).
    # The D089 numbers (2026-10-31) come first, in file order, then those four.
    numeric = re.findall(r"^\s*([a-z_]+)\s*=\s*[-+]?\d+", text, flags=re.MULTILINE)
    assert numeric == [
        *(dotted.split(".", 1)[1] for dotted in D089_DECIDED),
        "max_equity_age_ms",
        "max_daily_loss_age_ms",
        "liquidation_buffer_bps",
        "max_bracket_age_ms",
        "headroom_bps",
    ]
    assert f"max_equity_age_ms = {EQUITY_AGE_DECIDED_MS}\n" in text
    # Nineteen keys, each with a value and a provenance label (19-REVIEW WR-05 added the fifth,
    # WR-03 the sixth, quick task 261020-l4p the seventh, plan 20-01 the seven Phase 20 keys, plan
    # 20-28 the alert-only reconcile.entry_stale_grace_ms, plan 21-02 account.max_equity_age_ms,
    # plan 22-02 the three margin keys). The equity age has a number and the label DECISION since
    # D084, the daily-loss age since D087 and the three margin keys since D085: 40 minus 2 minus 2
    # minus 6 = 30; the D083 clock margin (plan 24-03) adds a value and a label: 32. D089 (plan
    # 24-06) sets 14 more keys, a value and a label each: 32 - 28 = 4 (the user-data silence bound
    # and the D083 clock margin, each a value and a label).
    # D091 set key 14: only the D083 margin and, since quick 261114-mp1 (D111), the alert-only
    # stall bound remain unset, a value and a label each.
    # Quick 261115-kra (D112) adds the optional summary window, unset: 4 + 2 = 6.
    assert text.count(f'"{el.NOT_CONFIGURED_WORD}"') == 6


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
    # The nineteen required keys plus the alert-only key of plan 20-28 and the optional refinement
    # key of plan 24-03 (D083), in file order.
    not_required = el.ALERT_ONLY_LIMIT_KEYS | el.OPTIONAL_REFINEMENT_LIMIT_KEYS
    assert [k for k in dotted_keys if k not in not_required] == list(ALL_REQUIRED_KEYS)
    # Quick 261115-kra (D112) adds the summary window as the second optional refinement key.
    assert el.OPTIONAL_REFINEMENT_LIMIT_KEYS == {BAN_END_MARGIN_KEY, SUMMARY_KEY}
    assert el.ALERT_ONLY_LIMIT_KEYS == {"reconcile.entry_stale_grace_ms", STALL_KEY}
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
    # Quick 261114-mp1 and 261115-kra leave the stall bound and the summary window unset (None),
    # so the distinctness holds for the numbers only.
    numbers = [value for value in values.values() if value is not None]
    assert len(set(numbers)) == len(numbers)


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


def test_the_real_file_has_every_section_and_label_unset_except_the_decided_keys() -> None:
    import tomllib

    document = tomllib.loads(LIMITS_FILE.read_text(encoding="utf-8"))
    for section, keys in el.EXECUTION_LIMIT_KEYS.items():
        for key in keys:
            if f"{section}.{key}" == EQUITY_AGE_KEY:
                # Set by the owner on 2026-10-23 (D084): a number and the label DECISION.
                assert document[section][key] == EQUITY_AGE_DECIDED_MS
                assert document["provenance"][section][key] == "DECISION"
                continue
            if f"{section}.{key}" == DAILY_LOSS_AGE_KEY:
                # Set by the owner on 2026-10-25 (D087): a number and the label DECISION.
                assert document[section][key] == DAILY_LOSS_AGE_DECIDED_MS
                assert document["provenance"][section][key] == "DECISION"
                continue
            if f"{section}.{key}" in MARGIN_DECIDED:
                # Set by the owner on 2026-10-24 (D085): a number and the label DECISION.
                assert document[section][key] == MARGIN_DECIDED[f"{section}.{key}"]
                assert document["provenance"][section][key] == "DECISION"
                continue
            if f"{section}.{key}" in D089_DECIDED:
                # Set by the owner on 2026-10-31 (D089): a number and the label DECISION.
                assert document[section][key] == D089_DECIDED[f"{section}.{key}"]
                assert document["provenance"][section][key] == "DECISION"
                continue
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


# --------------------------------------------------------------------------- #
# Plan 21-02 (D-03, F-012, O-1): account.max_equity_age_ms, a REQUIRED key, NOT_CONFIGURED.
# --------------------------------------------------------------------------- #

_ACCOUNT_KEY = "account.max_equity_age_ms"
_ACCOUNT_FIELD = "account_max_equity_age_ms"


def _account_document(value: Any = 5, label: str = "DECISION") -> dict[str, Any]:
    """A valid all-set document whose account.max_equity_age_ms comes from a literal."""
    document = _document()
    document["account"]["max_equity_age_ms"] = value
    document["provenance"]["account"]["max_equity_age_ms"] = label
    return document


def test_the_committed_file_sets_the_equity_age_and_keeps_it_required() -> None:
    limits = el.load_execution_limits(LIMITS_FILE)
    assert limits.account_max_equity_age_ms == EQUITY_AGE_DECIDED_MS  # DECISIONS D084
    assert _ACCOUNT_KEY not in limits.unset_keys()
    assert limits.unset_keys() == COMMITTED_UNSET
    assert len(limits.unset_keys()) == 0  # D091 set the last one
    # D089 set the stale-entry grace; the D111 stall key is unset and alert-only.
    assert limits.unset_alert_only_keys() == (STALL_KEY,)
    assert _ACCOUNT_KEY not in el.ALERT_ONLY_LIMIT_KEYS
    # Since D091 every required key is set, so the file is live-ready (LIVE_ORDERS_DISABLED still
    # blocks real orders).
    limits.require_live_ready()


def test_the_account_section_precedes_margin_and_has_the_prefixed_field() -> None:
    assert list(el.EXECUTION_LIMIT_KEYS)[-4:] == ["account", "margin", "rest_gate", "scheduler"]
    assert el.EXECUTION_LIMIT_KEYS["account"] == ("max_equity_age_ms", "max_daily_loss_age_ms")
    assert el.EXECUTION_LIMIT_FIELDS[DAILY_LOSS_AGE_KEY] == "account_max_daily_loss_age_ms"
    assert el.EXECUTION_LIMIT_FIELDS[_ACCOUNT_KEY] == _ACCOUNT_FIELD
    assert _ACCOUNT_FIELD in el.ExecutionLimits.__dataclass_fields__


def test_a_set_account_equity_age_loads_into_its_prefixed_field() -> None:
    limits = el.parse_execution_limits(_account_document(5))
    assert limits.account_max_equity_age_ms == 5
    assert limits.unset_keys() == ()
    assert limits.require_live_ready() is None


def test_a_document_without_the_account_section_is_refused_by_name() -> None:
    document = _account_document()
    del document["account"]
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(document)
    assert _ACCOUNT_KEY in str(info.value)


def test_an_account_section_without_the_key_is_refused_by_name() -> None:
    document = _account_document()
    del document["account"]["max_equity_age_ms"]
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(document)
    assert _ACCOUNT_KEY in str(info.value)


def test_an_unknown_key_in_the_account_section_is_refused() -> None:
    document = _account_document()
    document["account"]["surprise_ms"] = 5
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(document)
    assert "account.surprise_ms" in str(info.value)


@pytest.mark.parametrize(
    ("mutate", "value_text"),
    [pytest.param(m, v, id=case) for case, m, v in _PHASE20_REFUSALS],
)
def test_every_malformed_account_equity_age_entry_is_refused_by_name(
    mutate: Any, value_text: str
) -> None:
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(mutate(_account_document(), _ACCOUNT_KEY))
    message = str(info.value)
    assert _ACCOUNT_KEY in message
    if value_text:
        assert value_text not in message


def test_the_account_test_only_value_is_set_and_may_be_unset_by_override() -> None:
    values = tl.TEST_ONLY_EXECUTION_LIMIT_VALUES
    assert values[_ACCOUNT_KEY] == 9137
    limits = tl.test_only_execution_limits()
    assert limits.account_max_equity_age_ms == 9137
    unset = tl.test_only_execution_limits(account_max_equity_age_ms=None)
    assert unset.account_max_equity_age_ms is None
    assert unset.unset_keys() == (_ACCOUNT_KEY,)
    with pytest.raises(el.ExecutionLimitsNotConfigured) as info:
        unset.require_live_ready()
    assert info.value.keys == (_ACCOUNT_KEY,)


# --------------------------------------------------------------------------- #
# Plan 22-02 (D-10, D-11, D-13, amendment A4; OWNER-OPEN O-2, O-3): the margin section, three
# REQUIRED keys, positive integers only (basis points and milliseconds). NOT_CONFIGURED until the
# owner answer of 2026-10-24 (DECISIONS D085): 300, 60000 and 1000, provenance DECISION.
# --------------------------------------------------------------------------- #

_MARGIN_KEYS_UNDER_TEST = MARGIN_KEYS


def test_the_margin_section_is_last_with_the_three_keys_in_order_and_prefixed_fields() -> None:
    # rest_gate (plan 24-03) and scheduler (quick 261114-mp1) follow it
    assert list(el.EXECUTION_LIMIT_KEYS)[-3] == "margin"
    assert el.EXECUTION_LIMIT_KEYS["margin"] == (
        "liquidation_buffer_bps",
        "max_bracket_age_ms",
        "headroom_bps",
    )
    for dotted, field_name in MARGIN_FIELDS.items():
        assert el.EXECUTION_LIMIT_FIELDS[dotted] == field_name, dotted
        assert field_name in el.ExecutionLimits.__dataclass_fields__, field_name
    dotted_keys = [f"{s}.{k}" for s, keys in el.EXECUTION_LIMIT_KEYS.items() for k in keys]
    # 22 keys until quick 261115-kra (D112) added the scheduler summary window: 23.
    assert len(dotted_keys) == 23
    assert dotted_keys[-6:-3] == list(MARGIN_KEYS)


def test_the_margin_keys_are_required_not_alert_only() -> None:
    for dotted in MARGIN_KEYS:
        assert dotted not in el.ALERT_ONLY_LIMIT_KEYS, dotted
    assert len(ALL_REQUIRED_KEYS) == 19


def test_the_committed_file_holds_the_margin_keys_set_with_the_decision_label() -> None:
    import tomllib

    document = tomllib.loads(LIMITS_FILE.read_text(encoding="utf-8"))
    for key in el.EXECUTION_LIMIT_KEYS["margin"]:
        assert document["margin"][key] == MARGIN_DECIDED[f"margin.{key}"], key  # DECISIONS D085
        assert document["provenance"]["margin"][key] == "DECISION", key
    limits = el.load_execution_limits(LIMITS_FILE)
    for dotted in MARGIN_KEYS:
        assert dotted not in limits.unset_keys()
    assert limits.unset_keys() == COMMITTED_UNSET
    assert limits.unset_alert_only_keys() == (STALL_KEY,)  # D089 set the grace; D111 key unset


def test_require_live_ready_still_refuses_and_no_longer_names_the_margin_keys() -> None:
    # D085 set the three margin keys; D091 set the last other key. A cleared key refuses again.
    from dataclasses import replace

    limits = replace(
        el.load_execution_limits(LIMITS_FILE), stale_feed_max_user_data_silence_ms=None
    )
    with pytest.raises(el.ExecutionLimitsNotConfigured) as info:
        limits.require_live_ready()
    assert len(info.value.keys) == 1  # only the cleared key
    for dotted in MARGIN_KEYS:
        assert dotted not in info.value.keys
        assert dotted not in str(info.value)
    assert not any(character.isdigit() for character in str(info.value))


def _margin_document(**values: Any) -> dict[str, Any]:
    """A valid all-set document whose margin values come from literals (5, 6, 7)."""
    document = _document()
    for offset, key in enumerate(el.EXECUTION_LIMIT_KEYS["margin"]):
        document["margin"][key] = values.get(key, 5 + offset)
        document["provenance"]["margin"][key] = "DECISION"
    return document


def test_a_set_margin_section_loads_into_its_prefixed_fields() -> None:
    limits = el.parse_execution_limits(_margin_document())
    assert limits.margin_liquidation_buffer_bps == 5
    assert limits.margin_max_bracket_age_ms == 6
    assert limits.margin_headroom_bps == 7
    assert limits.unset_keys() == ()
    assert limits.require_live_ready() is None


def test_a_document_without_the_margin_section_is_refused_naming_its_keys() -> None:
    document = _margin_document()
    del document["margin"]
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(document)
    message = str(info.value)
    for dotted in MARGIN_KEYS:
        assert dotted in message


def test_a_margin_section_without_provenance_is_refused_naming_its_keys() -> None:
    document = _margin_document()
    del document["provenance"]["margin"]
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(document)
    message = str(info.value)
    for dotted in MARGIN_KEYS:
        assert dotted in message
        assert "missing provenance label" in message


def test_an_unknown_key_in_the_margin_section_is_refused() -> None:
    document = _margin_document()
    document["margin"]["surprise_bps"] = 5
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(document)
    assert "margin.surprise_bps" in str(info.value)


@pytest.mark.parametrize("dotted", _MARGIN_KEYS_UNDER_TEST)
@pytest.mark.parametrize(
    ("mutate", "value_text"),
    [pytest.param(m, v, id=case) for case, m, v in _PHASE20_REFUSALS],
)
def test_every_malformed_margin_entry_is_refused_by_name(
    dotted: str, mutate: Any, value_text: str
) -> None:
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(mutate(_margin_document(), dotted))
    message = str(info.value)
    assert dotted in message
    if value_text:
        assert value_text not in message


def test_the_margin_test_only_values_are_the_fixed_fake_numbers() -> None:
    values = tl.TEST_ONLY_EXECUTION_LIMIT_VALUES
    assert values["margin.liquidation_buffer_bps"] == 137
    assert values["margin.max_bracket_age_ms"] == 4141
    assert values["margin.headroom_bps"] == 233
    limits = tl.test_only_execution_limits()
    for dotted, field_name in MARGIN_FIELDS.items():
        assert getattr(limits, field_name) == values[dotted], dotted


@pytest.mark.parametrize("dotted", MARGIN_KEYS)
def test_overriding_one_margin_field_with_none_leaves_exactly_that_key_unset(dotted: str) -> None:
    unset = tl.test_only_execution_limits(**{MARGIN_FIELDS[dotted]: None})
    assert unset.unset_keys() == (dotted,)
    with pytest.raises(el.ExecutionLimitsNotConfigured) as info:
        unset.require_live_ready()
    assert info.value.keys == (dotted,)


# --------------------------------------------------------------------------- #
# Plan 24-03 (DECISIONS D083 item 4): rest_gate.ban_end_clock_margin_ms, an OPTIONAL REFINEMENT key.
# NOT_CONFIGURED until the owner sets it (plan 24-06, O-1); unset, the 418 fallback wait applies and
# the live path is NOT kept refused (D-12 stays satisfiable).
# --------------------------------------------------------------------------- #


def test_the_ban_end_margin_key_is_declared_last_with_a_prefixed_field() -> None:
    assert el.EXECUTION_LIMIT_KEYS["rest_gate"] == ("ban_end_clock_margin_ms",)
    assert list(el.EXECUTION_LIMIT_KEYS)[-2] == "rest_gate"  # `scheduler` (D111) follows it
    assert el.EXECUTION_LIMIT_FIELDS[BAN_END_MARGIN_KEY] == BAN_END_MARGIN_FIELD
    assert BAN_END_MARGIN_FIELD in el.ExecutionLimits.__dataclass_fields__
    assert BAN_END_MARGIN_KEY in el.OPTIONAL_REFINEMENT_LIMIT_KEYS
    assert BAN_END_MARGIN_KEY not in el.ALERT_ONLY_LIMIT_KEYS
    assert not el.ALERT_ONLY_LIMIT_KEYS & el.OPTIONAL_REFINEMENT_LIMIT_KEYS


def test_the_committed_file_leaves_the_ban_end_margin_unset_and_labelled_not_configured() -> None:
    import tomllib

    document = tomllib.loads(LIMITS_FILE.read_text(encoding="utf-8"))
    assert document["rest_gate"]["ban_end_clock_margin_ms"] == el.NOT_CONFIGURED_WORD
    assert document["provenance"]["rest_gate"]["ban_end_clock_margin_ms"] == el.NOT_CONFIGURED_WORD
    limits = el.load_execution_limits(LIMITS_FILE)
    assert limits.rest_gate_ban_end_clock_margin_ms is None
    assert limits.rest_gate_ban_end_clock_margin is None
    # D112 (quick 261115-kra): the summary window is unset in the committed file too.
    assert limits.unset_optional_refinement_keys() == (BAN_END_MARGIN_KEY, SUMMARY_KEY)
    assert BAN_END_MARGIN_KEY not in limits.unset_keys()
    assert BAN_END_MARGIN_KEY not in limits.unset_alert_only_keys()


def test_require_live_ready_never_names_the_ban_end_margin() -> None:
    from dataclasses import replace

    limits = replace(
        el.load_execution_limits(LIMITS_FILE), stale_feed_max_user_data_silence_ms=None
    )
    with pytest.raises(el.ExecutionLimitsNotConfigured) as info:
        limits.require_live_ready()
    assert BAN_END_MARGIN_KEY not in info.value.keys
    assert "ban_end_clock_margin" not in str(info.value)
    # With every REQUIRED key set and the optional one unset the live path is ready (D-12).
    ready = tl.test_only_execution_limits(rest_gate_ban_end_clock_margin_ms=None)
    assert ready.unset_keys() == ()
    assert ready.require_live_ready() is None
    assert ready.unset_optional_refinement_keys() == (BAN_END_MARGIN_KEY, SUMMARY_KEY)


def test_a_set_ban_end_margin_loads_as_milliseconds_and_as_a_timedelta() -> None:
    from datetime import timedelta

    limits = tl.test_only_execution_limits()
    assert limits.rest_gate_ban_end_clock_margin_ms == 4545
    assert limits.rest_gate_ban_end_clock_margin == timedelta(milliseconds=4545)
    # The TEST_ONLY summary window is None (D112), so it is the one unset optional key.
    assert limits.unset_optional_refinement_keys() == (SUMMARY_KEY,)


def _ban_end_document(value: Any) -> dict[str, Any]:
    document = _all_set_document()
    document["rest_gate"]["ban_end_clock_margin_ms"] = value
    return document


def test_a_positive_int_ban_end_margin_loads_and_a_set_value_needs_a_real_label() -> None:
    limits = el.parse_execution_limits(_ban_end_document(250))
    assert limits.rest_gate_ban_end_clock_margin_ms == 250
    placeholder = _ban_end_document(250)
    placeholder["provenance"]["rest_gate"]["ban_end_clock_margin_ms"] = "PLACEHOLDER"
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(placeholder)
    assert BAN_END_MARGIN_KEY in str(info.value)
    labelled_unset = _ban_end_document(250)
    labelled_unset["provenance"]["rest_gate"]["ban_end_clock_margin_ms"] = el.NOT_CONFIGURED_WORD
    with pytest.raises(el.ExecutionLimitsInvalid):
        el.parse_execution_limits(labelled_unset)


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, False, "250", "not_configured", ""])
def test_a_malformed_ban_end_margin_is_refused_by_name(bad: Any) -> None:
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(_ban_end_document(bad))
    assert BAN_END_MARGIN_KEY in str(info.value)


def test_a_document_without_the_rest_gate_section_is_refused_by_name() -> None:
    document = _all_set_document()
    del document["rest_gate"]
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(document)
    assert BAN_END_MARGIN_KEY in str(info.value)


# --------------------------------------------------------------------------- #
# Quick task 261114-mp1 (DECISIONS D111): scheduler.protection_stall_after_ms, an ALERT-ONLY key.
# NOT_CONFIGURED until the owner sets it from a Demo measurement; unset, the observe-only stall
# watchdog of the protection task is off and nothing else changes. No number is chosen.
# --------------------------------------------------------------------------- #


def test_the_stall_key_is_declared_last_alert_only_with_a_prefixed_field() -> None:
    # Quick 261115-kra (D112) added `duration_summary_interval_ms` as the second scheduler key.
    assert el.EXECUTION_LIMIT_KEYS["scheduler"] == (
        "protection_stall_after_ms",
        "duration_summary_interval_ms",
    )
    assert list(el.EXECUTION_LIMIT_KEYS)[-1] == "scheduler"
    assert el.EXECUTION_LIMIT_FIELDS[STALL_KEY] == STALL_FIELD
    assert STALL_FIELD in el.ExecutionLimits.__dataclass_fields__
    assert STALL_KEY in el.ALERT_ONLY_LIMIT_KEYS
    assert STALL_KEY not in el.OPTIONAL_REFINEMENT_LIMIT_KEYS
    assert not el.ALERT_ONLY_LIMIT_KEYS & el.OPTIONAL_REFINEMENT_LIMIT_KEYS


def test_the_committed_file_leaves_the_stall_key_unset_and_labelled_not_configured() -> None:
    import tomllib

    document = tomllib.loads(LIMITS_FILE.read_text(encoding="utf-8"))
    assert document["scheduler"]["protection_stall_after_ms"] == el.NOT_CONFIGURED_WORD
    assert document["provenance"]["scheduler"]["protection_stall_after_ms"] == (
        el.NOT_CONFIGURED_WORD
    )
    limits = el.load_execution_limits(LIMITS_FILE)
    assert limits.scheduler_protection_stall_after_ms is None
    assert limits.scheduler_protection_stall_after is None
    assert limits.unset_alert_only_keys() == (STALL_KEY,)
    assert STALL_KEY not in limits.unset_keys()
    assert STALL_KEY not in limits.unset_optional_refinement_keys()
    limits.require_live_ready()  # an unset alert-only key never keeps the live path refused


def test_require_live_ready_never_names_the_stall_key() -> None:
    from dataclasses import replace

    limits = replace(
        el.load_execution_limits(LIMITS_FILE), stale_feed_max_user_data_silence_ms=None
    )
    with pytest.raises(el.ExecutionLimitsNotConfigured) as info:
        limits.require_live_ready()
    assert STALL_KEY not in info.value.keys
    assert "protection_stall_after" not in str(info.value)


def test_a_set_stall_bound_loads_as_milliseconds_and_as_a_timedelta() -> None:
    from datetime import timedelta

    assert tl.test_only_execution_limits().scheduler_protection_stall_after_ms is None
    limits = tl.test_only_execution_limits(scheduler_protection_stall_after_ms=5353)
    assert limits.scheduler_protection_stall_after_ms == 5353
    assert limits.scheduler_protection_stall_after == timedelta(milliseconds=5353)
    assert limits.unset_alert_only_keys() == ()


def _stall_document(value: Any) -> dict[str, Any]:
    document = _all_set_document()
    document["scheduler"]["protection_stall_after_ms"] = value
    return document


def test_a_positive_int_stall_bound_loads_and_a_set_value_needs_a_real_label() -> None:
    limits = el.parse_execution_limits(_stall_document(250))
    assert limits.scheduler_protection_stall_after_ms == 250
    placeholder = _stall_document(250)
    placeholder["provenance"]["scheduler"]["protection_stall_after_ms"] = "PLACEHOLDER"
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(placeholder)
    assert STALL_KEY in str(info.value)
    labelled_unset = _stall_document(250)
    labelled_unset["provenance"]["scheduler"]["protection_stall_after_ms"] = el.NOT_CONFIGURED_WORD
    with pytest.raises(el.ExecutionLimitsInvalid):
        el.parse_execution_limits(labelled_unset)


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, False, "250", "not_configured", ""])
def test_a_malformed_stall_bound_is_refused_by_name(bad: Any) -> None:
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(_stall_document(bad))
    assert STALL_KEY in str(info.value)


def test_a_document_without_the_scheduler_section_is_refused_by_name() -> None:
    document = _all_set_document()
    del document["scheduler"]
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(document)
    assert STALL_KEY in str(info.value)


# --------------------------------------------------------------------------- #
# Quick task 261115-kra (DECISIONS D112): scheduler.duration_summary_interval_ms, an OPTIONAL
# REFINEMENT key. NOT_CONFIGURED until the owner sets it; unset, only the new-maximum rows of the
# scheduler duration record are written and nothing else changes. It switches no alert, so it is
# not alert-only. No number is chosen.
# --------------------------------------------------------------------------- #


def test_the_summary_key_is_declared_second_in_scheduler_optional_with_a_prefixed_field() -> None:
    assert el.EXECUTION_LIMIT_KEYS["scheduler"] == (
        "protection_stall_after_ms",
        "duration_summary_interval_ms",
    )
    assert list(el.EXECUTION_LIMIT_KEYS)[-1] == "scheduler"
    assert el.EXECUTION_LIMIT_FIELDS[SUMMARY_KEY] == SUMMARY_FIELD
    assert SUMMARY_FIELD in el.ExecutionLimits.__dataclass_fields__
    assert SUMMARY_KEY in el.OPTIONAL_REFINEMENT_LIMIT_KEYS
    assert SUMMARY_KEY not in el.ALERT_ONLY_LIMIT_KEYS
    assert not el.ALERT_ONLY_LIMIT_KEYS & el.OPTIONAL_REFINEMENT_LIMIT_KEYS


def test_the_committed_file_leaves_the_summary_key_unset_and_labelled_not_configured() -> None:
    import tomllib

    document = tomllib.loads(LIMITS_FILE.read_text(encoding="utf-8"))
    assert document["scheduler"]["duration_summary_interval_ms"] == el.NOT_CONFIGURED_WORD
    assert document["provenance"]["scheduler"]["duration_summary_interval_ms"] == (
        el.NOT_CONFIGURED_WORD
    )
    limits = el.load_execution_limits(LIMITS_FILE)
    assert limits.scheduler_duration_summary_interval_ms is None
    assert limits.scheduler_duration_summary_interval is None
    assert limits.unset_optional_refinement_keys() == (BAN_END_MARGIN_KEY, SUMMARY_KEY)
    assert SUMMARY_KEY not in limits.unset_keys()
    assert SUMMARY_KEY not in limits.unset_alert_only_keys()
    limits.require_live_ready()  # an unset optional key never keeps the live path refused


def test_require_live_ready_never_names_the_summary_key() -> None:
    from dataclasses import replace

    limits = replace(
        el.load_execution_limits(LIMITS_FILE), stale_feed_max_user_data_silence_ms=None
    )
    with pytest.raises(el.ExecutionLimitsNotConfigured) as info:
        limits.require_live_ready()
    assert SUMMARY_KEY not in info.value.keys
    assert "duration_summary_interval" not in str(info.value)


def test_a_set_summary_interval_loads_as_milliseconds_and_as_a_timedelta() -> None:
    from datetime import timedelta

    assert tl.test_only_execution_limits().scheduler_duration_summary_interval_ms is None
    limits = tl.test_only_execution_limits(scheduler_duration_summary_interval_ms=6262)
    assert limits.scheduler_duration_summary_interval_ms == 6262
    assert limits.scheduler_duration_summary_interval == timedelta(milliseconds=6262)
    assert limits.unset_optional_refinement_keys() == ()


def _summary_document(value: Any) -> dict[str, Any]:
    document = _all_set_document()
    document["scheduler"]["duration_summary_interval_ms"] = value
    return document


def test_a_positive_int_summary_interval_loads_and_a_set_value_needs_a_real_label() -> None:
    limits = el.parse_execution_limits(_summary_document(250))
    assert limits.scheduler_duration_summary_interval_ms == 250
    placeholder = _summary_document(250)
    placeholder["provenance"]["scheduler"]["duration_summary_interval_ms"] = "PLACEHOLDER"
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(placeholder)
    assert SUMMARY_KEY in str(info.value)
    labelled_unset = _summary_document(250)
    labelled_unset["provenance"]["scheduler"]["duration_summary_interval_ms"] = (
        el.NOT_CONFIGURED_WORD
    )
    with pytest.raises(el.ExecutionLimitsInvalid):
        el.parse_execution_limits(labelled_unset)


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, False, "250", "not_configured", ""])
def test_a_malformed_summary_interval_is_refused_by_name(bad: Any) -> None:
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(_summary_document(bad))
    assert SUMMARY_KEY in str(info.value)


def test_a_document_without_the_scheduler_section_names_both_scheduler_keys() -> None:
    document = _all_set_document()
    del document["scheduler"]
    with pytest.raises(el.ExecutionLimitsInvalid) as info:
        el.parse_execution_limits(document)
    assert STALL_KEY in str(info.value)
    assert SUMMARY_KEY in str(info.value)
