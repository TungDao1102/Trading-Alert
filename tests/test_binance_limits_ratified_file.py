"""The ratified limits file, the environment rows and the DECISIONS row equal the user's record.

Plan 18-09. The single source of truth is the user's decision record
`.planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DEC-O-18-01.md`. Every
expectation below is parsed from that record at test time, never written as a literal, so the
repository cannot drift from the record: a changed value in the committed file, a changed row
or a changed record fails here. Only lines that start with `limit `, `env `, `credential ` or
`probe environment:` are parsed; the record's prose (which names the retired single rate-limit
key) is never read as a value. Every test is offline.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
from src.adapters import binance_client as bc
from src.adapters.binance_limits import (
    CANONICAL_KEYS,
    NULLABLE_KEYS,
    PROVENANCE_SECTION,
    RATE_LIMIT_KEY_TO_FIELD,
    BinanceLimits,
    load_binance_limits,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DECISION_RECORD = (
    REPO_ROOT
    / ".planning"
    / "phases"
    / "18-user-data-stream-error-taxonomy"
    / "decisions"
    / "18-DEC-O-18-01.md"
)
LIMITS_FILE = REPO_ROOT / "config" / "binance" / "binance-limits-v1.toml"

_LIMIT_LINE = re.compile(r"^limit ([a-z_]+)\.([a-z0-9_]+): (\S+)\s*$")
_EXPECTED_KEY_COUNT = sum(len(keys) for keys in CANONICAL_KEYS.values())


# --------------------------------------------------------------------------- #
# Record parsing.
# --------------------------------------------------------------------------- #


def _record_lines() -> list[str]:
    return DECISION_RECORD.read_text(encoding="utf-8").splitlines()


def _record_value(dotted: str, text: str) -> int | bool | str:
    """The typed value of one `limit` line: an integer, true/false, or the word none."""
    if re.fullmatch(r"[0-9]+", text):
        return int(text)
    if text in ("true", "false"):
        return text == "true"
    if text == "none":
        assert dotted in NULLABLE_KEYS, f"{dotted}: the word none on a key that is not nullable"
        return "none"
    raise AssertionError(f"{dotted}: the record value is not an integer, true, false or none")


def _record_limits() -> dict[str, int | bool | str]:
    """`section.key` -> typed value, from the `limit <section>.<key>: <value>` lines only."""
    limits: dict[str, int | bool | str] = {}
    for line in _record_lines():
        if not line.startswith("limit "):
            continue
        match = _LIMIT_LINE.match(line)
        assert match is not None, "a 'limit ' line of the record is malformed"
        section, key, text = match.groups()
        dotted = f"{section}.{key}"
        assert dotted not in limits, f"{dotted} appears twice in the record"
        limits[dotted] = _record_value(dotted, text)
    return limits


def _canonical_dotted() -> set[str]:
    return {f"{section}.{key}" for section, keys in CANONICAL_KEYS.items() for key in keys}


def _toml() -> dict[str, Any]:
    return tomllib.loads(LIMITS_FILE.read_text(encoding="utf-8"))


def _toml_values(document: dict[str, Any]) -> dict[str, Any]:
    return {
        f"{section}.{key}": value
        for section, body in document.items()
        if section != PROVENANCE_SECTION
        for key, value in body.items()
    }


def _loaded_value(limits: BinanceLimits, dotted: str) -> Any:
    """The value of one canonical key inside the loaded structure."""
    section, key = dotted.split(".")
    if section == "client":
        return getattr(limits.client, key)
    if section == "signed_calls":
        if key in RATE_LIMIT_KEY_TO_FIELD:
            return getattr(limits.signed.rate_limit, RATE_LIMIT_KEY_TO_FIELD[key])
        return getattr(limits.signed, key)
    if section == "drift":
        return getattr(limits.drift, key)
    return getattr(limits.stream, key)


# --------------------------------------------------------------------------- #
# Task 1: record -> file -> loader.
# --------------------------------------------------------------------------- #


def test_the_record_has_exactly_the_canonical_limit_lines() -> None:
    text = DECISION_RECORD.read_text(encoding="utf-8")
    assert "CODE CHANGE REQUESTED" not in text
    assert "option: values" in text.splitlines()
    record = _record_limits()
    assert len(record) == _EXPECTED_KEY_COUNT == 27
    assert set(record) == _canonical_dotted()


def test_the_file_has_exactly_the_record_values() -> None:
    record = _record_limits()
    values = _toml_values(_toml())
    assert len(values) == 27
    assert set(values) == set(record) == _canonical_dotted()
    for dotted, expected in record.items():
        actual = values[dotted]
        if isinstance(expected, bool):
            assert type(actual) is bool and actual is expected, dotted
        elif isinstance(expected, int):
            assert type(actual) is int and actual == expected, dotted
        else:
            assert actual == "none", dotted


def test_every_key_has_a_provenance_label() -> None:
    provenance = _toml()[PROVENANCE_SECTION]
    labelled = {
        f"{section}.{key}": label
        for section, body in provenance.items()
        for key, label in body.items()
    }
    assert set(labelled) == _canonical_dotted()
    # The record names no other label, so every key carries DECISION.
    assert set(labelled.values()) == {"DECISION"}


def test_the_file_sections_are_exactly_the_canonical_ones() -> None:
    assert set(_toml()) == {*CANONICAL_KEYS, PROVENANCE_SECTION}


def test_the_header_names_the_record() -> None:
    lines = LIMITS_FILE.read_text(encoding="utf-8").splitlines()
    header = [line for line in lines if line.startswith("#")]
    assert any("18-DEC-O-18-01.md" in line for line in header)
    assert any("2026-10-16" in line for line in header)


def test_the_file_has_no_line_that_is_not_a_record_value() -> None:
    """Outside comments, section headers and provenance, every line is one record value."""
    record = _record_limits()
    section = ""
    seen: set[str] = set()
    for line in LIMITS_FILE.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        header = re.fullmatch(r"\[([a-z_.]+)\]", line)
        if header is not None:
            section = header.group(1)
            continue
        match = re.fullmatch(r"([a-z0-9_]+) = (\S+)", line)
        assert match is not None, "a value line has an unexpected shape"
        key, literal = match.groups()
        if section.startswith(PROVENANCE_SECTION + "."):
            assert literal == '"DECISION"'
            continue
        dotted = f"{section}.{key}"
        assert dotted in record
        expected = record[dotted]
        if isinstance(expected, bool):
            assert literal == ("true" if expected else "false")
        elif isinstance(expected, int):
            assert literal == str(expected)
        else:
            assert literal == '"none"'
        seen.add(dotted)
    assert seen == set(record)


def test_the_file_ends_with_a_newline_and_uses_lf() -> None:
    """`.gitattributes` marks config/binance/*.toml `-text`: the bytes are LF on every checkout."""
    raw = LIMITS_FILE.read_bytes()
    assert raw.endswith(b"\n")
    assert b"\r" not in raw
    assert not raw.endswith(b"\n\n")
    attributes = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "config/binance/*.toml -text" in attributes


def test_the_real_loader_accepts_the_ratified_file_with_the_record_values() -> None:
    record = _record_limits()
    limits = load_binance_limits(Path("config/binance/binance-limits-v1.toml").resolve())
    assert isinstance(limits, BinanceLimits)
    for dotted, expected in record.items():
        value = _loaded_value(limits, dotted)
        if expected == "none":
            assert value is None, dotted
        else:
            assert type(value) is type(expected) and value == expected, dotted


@pytest.mark.parametrize(
    ("record_key", "field"),
    [
        (
            "signed_calls.rate_limit_418_no_retry_after_wait_seconds",
            "no_retry_after_wait_418_seconds",
        ),
        (
            "signed_calls.rate_limit_429_no_retry_after_wait_seconds",
            "no_retry_after_wait_429_seconds",
        ),
        ("signed_calls.rate_limit_retry_after_cap_seconds", "retry_after_cap_seconds"),
    ],
)
def test_the_rate_limit_fields_come_from_their_own_record_line(record_key: str, field: str) -> None:
    record = _record_limits()
    limits = load_binance_limits(LIMITS_FILE)
    assert getattr(limits.signed.rate_limit, field) == record[record_key]


def test_the_retired_single_wait_key_is_absent_from_the_file() -> None:
    assert "rate_limit_no_retry_after_wait_seconds" not in _toml()["signed_calls"]


# --------------------------------------------------------------------------- #
# Task 2: record -> environment rows and credential specs.
# --------------------------------------------------------------------------- #

_NOT_CONFIGURED = "NOT_CONFIGURED"
_URL_FIELDS = ("rest_url", "ws_streams_url", "ws_api_url")
_ENV_LINE = re.compile(r"^env ([A-Z]+)(?: ([a-z_]+))?: (\S+)\s*$")
_CREDENTIAL_LINE = re.compile(r"^credential ([A-Z]+) (key_variable|secret_variable): (\S+)\s*$")
_PROBE_LINE = re.compile(r"^probe environment: (\S+)\s*$")


def _record_env_lines() -> list[tuple[str, str | None, str]]:
    """(environment, field or None for a whole-row answer, value) per `env ` line."""
    found: list[tuple[str, str | None, str]] = []
    for line in _record_lines():
        if not line.startswith("env "):
            continue
        match = _ENV_LINE.match(line)
        assert match is not None, "an 'env ' line of the record is malformed"
        environment, field_name, value = match.groups()
        found.append((environment, field_name, value))
    return found


def _record_credentials() -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for line in _record_lines():
        if not line.startswith("credential "):
            continue
        match = _CREDENTIAL_LINE.match(line)
        assert match is not None, "a 'credential ' line of the record is malformed"
        environment, field_name, value = match.groups()
        names = found.setdefault(environment, {})
        assert field_name not in names, f"credential {environment} {field_name} appears twice"
        names[field_name] = value
    return found


def test_the_record_has_env_credential_and_probe_lines() -> None:
    env_lines = _record_env_lines()
    assert env_lines, "the record has no env line"
    named = {environment for environment, _, _ in env_lines}
    assert named <= {environment.value for environment in bc.Environment}
    credentials = _record_credentials()
    for environment, names in credentials.items():
        assert environment in {e.value for e in bc.Environment}
        assert set(names) == {"key_variable", "secret_variable"}, environment
    probes = [m.group(1) for line in _record_lines() if (m := _PROBE_LINE.match(line))]
    assert len(probes) == 1
    assert bc.parse_environment(probes[0]) in bc.ENVIRONMENT_ROWS


def test_environment_rows_equal_the_record() -> None:
    for environment_text, field_name, value in _record_env_lines():
        row = bc.ENVIRONMENT_ROWS[bc.parse_environment(environment_text)]
        expected = None if value == _NOT_CONFIGURED else value
        if field_name is None:
            # A whole-row answer: NOT_CONFIGURED leaves every surface unconfigured.
            assert value == _NOT_CONFIGURED, environment_text
            for name in _URL_FIELDS:
                assert getattr(row, name) is None, (environment_text, name)
            continue
        assert field_name in _URL_FIELDS, field_name
        assert getattr(row, field_name) == expected, (environment_text, field_name)


def test_the_probe_environment_has_its_rest_surface_configured() -> None:
    probes = [m.group(1) for line in _record_lines() if (m := _PROBE_LINE.match(line))]
    row = bc.ENVIRONMENT_ROWS[bc.parse_environment(probes[0])]
    assert row.rest_url is not None


def test_credential_specs_equal_the_record() -> None:
    credentials = _record_credentials()
    assert {environment.value for environment in bc.CREDENTIAL_SPECS} == set(credentials)
    for environment_text, names in credentials.items():
        spec = bc.credential_spec_for(bc.parse_environment(environment_text))
        assert spec.key_variable == names["key_variable"], environment_text
        assert spec.secret_variable == names["secret_variable"], environment_text
    for environment in bc.Environment:
        if environment.value not in credentials:
            with pytest.raises(bc.CredentialNamesNotRatified):
                bc.credential_spec_for(environment)


def test_demo_and_live_credential_names_are_disjoint() -> None:
    """OPS-06 keeps test-environment and live variable names apart."""
    demo = bc.credential_spec_for(bc.Environment.DEMO)
    live = bc.credential_spec_for(bc.Environment.LIVE)
    assert not set(demo.variables) & set(live.variables)


# --------------------------------------------------------------------------- #
# Task 3: the DECISIONS row pins the file.
# --------------------------------------------------------------------------- #

DECISIONS = REPO_ROOT / "docs" / "DECISIONS.md"
_ROW_TITLE = (
    "Phase 18 client configuration, user-data stream and exchange error taxonomy: "
    "user-ratified thresholds, environments and status classes"
)


def _phase18_row() -> str:
    """The one DECISIONS row with the Phase 18 title (found by title, not by number)."""
    rows = [
        line
        for line in DECISIONS.read_text(encoding="utf-8").splitlines()
        if re.match(r"^\| D\d{3} \| ", line) and f"| {_ROW_TITLE} |" in line
    ]
    assert len(rows) == 1, "exactly one DECISIONS row carries the Phase 18 title"
    return rows[0]


def test_decisions_row_pins_the_limits_file_hash() -> None:
    row = _phase18_row()
    match = re.search(r"sha256\b[^|]*?\b([0-9a-f]{64})\b", row)
    assert match is not None, "the row carries no 64-hex sha256"
    normalized = LIMITS_FILE.read_bytes().replace(b"\r\n", b"\n")
    assert match.group(1) == hashlib.sha256(normalized).hexdigest()
    assert "config/binance/binance-limits-v1.toml" in row
    assert "18-DEC-O-18-01.md" in row
    assert "Amendment 2026-10-16 (user): 429 semantics" in row
    assert "D055" in row and "OPEN" in row
