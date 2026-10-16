"""TEST_ONLY limit objects and a TOML writer for the loader tests (plan 18-07).

TEST_ONLY values are NOT ratified values. They never appear in `src` or `scripts`, no
production code imports this module (`tests/test_no_unratified_defaults.py` enforces it), and
they exist only to build limit objects and limit files in tests. The ratified numbers live in
the user's decision record (`decisions/18-DEC-O-18-01.md`) and reach the repository only
through `config/binance/binance-limits-v1.toml`, written by plan 18-09.

Every value below is deliberately odd-looking so that it cannot be mistaken for a chosen
threshold, and the three rate-limit values are pairwise different so that a consumer reading
the wrong field fails its test.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from src.adapters.binance_client import ClientLimits
from src.adapters.binance_limits import (
    BinanceLimits,
    DriftLimits,
    RateLimitPolicy,
    SignedCallPolicy,
    StreamLimits,
)

# --------------------------------------------------------------------------- #
# [client]
# --------------------------------------------------------------------------- #
TEST_ONLY_REST_TIMEOUT_MS = 1234
TEST_ONLY_SDK_RETRIES = 2
TEST_ONLY_SDK_BACKOFF_MS = 111

# --------------------------------------------------------------------------- #
# [signed_calls]
# --------------------------------------------------------------------------- #
TEST_ONLY_RECV_WINDOW_MS = 4321
TEST_ONLY_RATE_LIMIT_418_NO_RETRY_AFTER_WAIT_SECONDS = 777
TEST_ONLY_RATE_LIMIT_429_NO_RETRY_AFTER_WAIT_SECONDS = 33
TEST_ONLY_RATE_LIMIT_RETRY_AFTER_CAP_SECONDS = 999

# --------------------------------------------------------------------------- #
# [drift]
# --------------------------------------------------------------------------- #
TEST_ONLY_AHEAD_LIMIT_MS = 432
TEST_ONLY_BEHIND_LIMIT_MS = 876
TEST_ONLY_INCLUDE_MEASUREMENT_UNCERTAINTY = True
TEST_ONLY_MAX_MEASUREMENT_AGE_SECONDS = 97
TEST_ONLY_PERIODIC_REMEASURE_INTERVAL_SECONDS = 41

# --------------------------------------------------------------------------- #
# [stream]
# --------------------------------------------------------------------------- #
TEST_ONLY_KEEPALIVE_INTERVAL_SECONDS = 1717
TEST_ONLY_KEEPALIVE_FAILURE_TOLERANCE = 2
TEST_ONLY_PROJECT_ROTATION_INTERVAL_SECONDS = 3333
TEST_ONLY_RECONNECT_MAX_ATTEMPTS = 4
TEST_ONLY_RECONNECT_MAX_DELAY_SECONDS = 88
TEST_ONLY_RECONNECT_WAIT_MULTIPLIER_SECONDS = 2
TEST_ONLY_RECONNECT_WAIT_MAX_SECONDS = 17
TEST_ONLY_SDK_RECONNECT_DELAY_MS = 2222
TEST_ONLY_SDK_RECONNECT_ATTEMPTS = 5
TEST_ONLY_SNAPSHOT_DEADLINE_SECONDS = 13
TEST_ONLY_SNAPSHOT_MAX_ATTEMPTS = 6
TEST_ONLY_SNAPSHOT_WAIT_MULTIPLIER_SECONDS = 3
TEST_ONLY_SNAPSHOT_WAIT_MAX_SECONDS = 11
TEST_ONLY_MAX_LIVENESS_AGE_SECONDS = 222
TEST_ONLY_EVENT_QUEUE_MAX = 512

# The provenance label the writer gives every key (an allowed, non-PLACEHOLDER label).
TEST_ONLY_PROVENANCE_LABEL = "DECISION"

# The file values, section by section, in the canonical key order. A value of None is
# written as the word none (only the three nullable keys may carry it).
TEST_ONLY_FILE_VALUES: Mapping[str, Mapping[str, int | bool | None]] = {
    "client": {
        "rest_timeout_ms": TEST_ONLY_REST_TIMEOUT_MS,
        "sdk_retries": TEST_ONLY_SDK_RETRIES,
        "sdk_backoff_ms": TEST_ONLY_SDK_BACKOFF_MS,
    },
    "signed_calls": {
        "recv_window_ms": TEST_ONLY_RECV_WINDOW_MS,
        "rate_limit_418_no_retry_after_wait_seconds": (
            TEST_ONLY_RATE_LIMIT_418_NO_RETRY_AFTER_WAIT_SECONDS
        ),
        "rate_limit_429_no_retry_after_wait_seconds": (
            TEST_ONLY_RATE_LIMIT_429_NO_RETRY_AFTER_WAIT_SECONDS
        ),
        "rate_limit_retry_after_cap_seconds": TEST_ONLY_RATE_LIMIT_RETRY_AFTER_CAP_SECONDS,
    },
    "drift": {
        "ahead_limit_ms": TEST_ONLY_AHEAD_LIMIT_MS,
        "behind_limit_ms": TEST_ONLY_BEHIND_LIMIT_MS,
        "include_measurement_uncertainty": TEST_ONLY_INCLUDE_MEASUREMENT_UNCERTAINTY,
        "max_measurement_age_seconds": TEST_ONLY_MAX_MEASUREMENT_AGE_SECONDS,
        "periodic_remeasure_interval_seconds": TEST_ONLY_PERIODIC_REMEASURE_INTERVAL_SECONDS,
    },
    "stream": {
        "keepalive_interval_seconds": TEST_ONLY_KEEPALIVE_INTERVAL_SECONDS,
        "keepalive_failure_tolerance": TEST_ONLY_KEEPALIVE_FAILURE_TOLERANCE,
        "project_rotation_interval_seconds": TEST_ONLY_PROJECT_ROTATION_INTERVAL_SECONDS,
        "reconnect_max_attempts": TEST_ONLY_RECONNECT_MAX_ATTEMPTS,
        "reconnect_max_delay_seconds": TEST_ONLY_RECONNECT_MAX_DELAY_SECONDS,
        "reconnect_wait_multiplier_seconds": TEST_ONLY_RECONNECT_WAIT_MULTIPLIER_SECONDS,
        "reconnect_wait_max_seconds": TEST_ONLY_RECONNECT_WAIT_MAX_SECONDS,
        "sdk_reconnect_delay_ms": TEST_ONLY_SDK_RECONNECT_DELAY_MS,
        "sdk_reconnect_attempts": TEST_ONLY_SDK_RECONNECT_ATTEMPTS,
        "snapshot_deadline_seconds": TEST_ONLY_SNAPSHOT_DEADLINE_SECONDS,
        "snapshot_max_attempts": TEST_ONLY_SNAPSHOT_MAX_ATTEMPTS,
        "snapshot_wait_multiplier_seconds": TEST_ONLY_SNAPSHOT_WAIT_MULTIPLIER_SECONDS,
        "snapshot_wait_max_seconds": TEST_ONLY_SNAPSHOT_WAIT_MAX_SECONDS,
        "max_liveness_age_seconds": TEST_ONLY_MAX_LIVENESS_AGE_SECONDS,
        "event_queue_max": TEST_ONLY_EVENT_QUEUE_MAX,
    },
}


def test_only_client_limits() -> ClientLimits:
    return ClientLimits(
        rest_timeout_ms=TEST_ONLY_REST_TIMEOUT_MS,
        sdk_retries=TEST_ONLY_SDK_RETRIES,
        sdk_backoff_ms=TEST_ONLY_SDK_BACKOFF_MS,
    )


def test_only_rate_limit_policy() -> RateLimitPolicy:
    return RateLimitPolicy(
        no_retry_after_wait_418_seconds=TEST_ONLY_RATE_LIMIT_418_NO_RETRY_AFTER_WAIT_SECONDS,
        no_retry_after_wait_429_seconds=TEST_ONLY_RATE_LIMIT_429_NO_RETRY_AFTER_WAIT_SECONDS,
        retry_after_cap_seconds=TEST_ONLY_RATE_LIMIT_RETRY_AFTER_CAP_SECONDS,
    )


def test_only_signed_call_policy() -> SignedCallPolicy:
    return SignedCallPolicy(
        recv_window_ms=TEST_ONLY_RECV_WINDOW_MS,
        rate_limit=test_only_rate_limit_policy(),
    )


def test_only_drift_limits() -> DriftLimits:
    return DriftLimits(
        ahead_limit_ms=TEST_ONLY_AHEAD_LIMIT_MS,
        behind_limit_ms=TEST_ONLY_BEHIND_LIMIT_MS,
        include_measurement_uncertainty=TEST_ONLY_INCLUDE_MEASUREMENT_UNCERTAINTY,
        max_measurement_age_seconds=TEST_ONLY_MAX_MEASUREMENT_AGE_SECONDS,
        periodic_remeasure_interval_seconds=TEST_ONLY_PERIODIC_REMEASURE_INTERVAL_SECONDS,
    )


def test_only_stream_limits() -> StreamLimits:
    return StreamLimits(
        keepalive_interval_seconds=TEST_ONLY_KEEPALIVE_INTERVAL_SECONDS,
        keepalive_failure_tolerance=TEST_ONLY_KEEPALIVE_FAILURE_TOLERANCE,
        project_rotation_interval_seconds=TEST_ONLY_PROJECT_ROTATION_INTERVAL_SECONDS,
        reconnect_max_attempts=TEST_ONLY_RECONNECT_MAX_ATTEMPTS,
        reconnect_max_delay_seconds=TEST_ONLY_RECONNECT_MAX_DELAY_SECONDS,
        reconnect_wait_multiplier_seconds=TEST_ONLY_RECONNECT_WAIT_MULTIPLIER_SECONDS,
        reconnect_wait_max_seconds=TEST_ONLY_RECONNECT_WAIT_MAX_SECONDS,
        sdk_reconnect_delay_ms=TEST_ONLY_SDK_RECONNECT_DELAY_MS,
        sdk_reconnect_attempts=TEST_ONLY_SDK_RECONNECT_ATTEMPTS,
        snapshot_deadline_seconds=TEST_ONLY_SNAPSHOT_DEADLINE_SECONDS,
        snapshot_max_attempts=TEST_ONLY_SNAPSHOT_MAX_ATTEMPTS,
        snapshot_wait_multiplier_seconds=TEST_ONLY_SNAPSHOT_WAIT_MULTIPLIER_SECONDS,
        snapshot_wait_max_seconds=TEST_ONLY_SNAPSHOT_WAIT_MAX_SECONDS,
        max_liveness_age_seconds=TEST_ONLY_MAX_LIVENESS_AGE_SECONDS,
        event_queue_max=TEST_ONLY_EVENT_QUEUE_MAX,
    )


def test_only_binance_limits() -> BinanceLimits:
    return BinanceLimits(
        client=test_only_client_limits(),
        signed=test_only_signed_call_policy(),
        drift=test_only_drift_limits(),
        stream=test_only_stream_limits(),
    )


# The builders are named `test_only_*` by plan 18-07; a test module that imports one by name
# would otherwise have pytest collect it as a test function.
for _builder in (
    test_only_client_limits,
    test_only_rate_limit_policy,
    test_only_signed_call_policy,
    test_only_drift_limits,
    test_only_stream_limits,
    test_only_binance_limits,
):
    _builder.__test__ = False  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# TOML writer.
# --------------------------------------------------------------------------- #

_Tree = dict[str, dict[str, object]]


def _render_value(value: object) -> str:
    """A TOML literal for a Python value; None is the word none (a string)."""
    if value is None:
        return '"none"'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    raise TypeError(f"cannot render a {type(value).__name__} as TOML")


def _default_tree() -> tuple[_Tree, _Tree]:
    values: _Tree = {section: dict(keys) for section, keys in TEST_ONLY_FILE_VALUES.items()}
    provenance: _Tree = {
        section: dict.fromkeys(keys, TEST_ONLY_PROVENANCE_LABEL)
        for section, keys in TEST_ONLY_FILE_VALUES.items()
    }
    return values, provenance


def _split(path: str) -> tuple[bool, list[str]]:
    """(is_provenance, the dotted parts after the optional leading `provenance`)."""
    parts = path.split(".")
    if parts[0] == "provenance":
        return True, parts[1:]
    return False, parts


def _apply(values: _Tree, provenance: _Tree, path: str, value: object) -> None:
    is_prov, parts = _split(path)
    tree = provenance if is_prov else values
    if len(parts) != 2:
        raise ValueError(f"a set path must be section.key or provenance.section.key: {path}")
    tree.setdefault(parts[0], {})[parts[1]] = value


def _remove(values: _Tree, provenance: _Tree, path: str) -> None:
    is_prov, parts = _split(path)
    tree = provenance if is_prov else values
    if is_prov and not parts:
        provenance.clear()
        provenance["__dropped__"] = {}
        return
    if len(parts) == 1:
        del tree[parts[0]]
    elif len(parts) == 2:
        del tree[parts[0]][parts[1]]
    else:
        raise ValueError(f"a drop path must be a section or a section.key: {path}")


def write_limits_toml(
    path: Path,
    *,
    overrides: Mapping[str, object] | None = None,
    drop: Iterable[str] | None = None,
    extra: Mapping[str, object] | None = None,
) -> Path:
    """Write a valid limits file built from the TEST_ONLY values, then let a test break it.

    `overrides` and `extra` map a dotted path (`section.key` for a value,
    `provenance.section.key` for a label) to a Python value: an int, a bool, a float, a
    string or None (the word none). `overrides` changes an existing entry, `extra` adds one
    (an unknown key or an unknown section). `drop` removes `section.key`, a whole `section`,
    `provenance.section.key`, `provenance.section` or the whole `provenance` table.
    """
    values, provenance = _default_tree()
    for dotted, value in (overrides or {}).items():
        _apply(values, provenance, dotted, value)
    for dotted, value in (extra or {}).items():
        _apply(values, provenance, dotted, value)
    for dotted in drop or ():
        _remove(values, provenance, dotted)
    lines = ["# TEST_ONLY limits file written by tests/support/limits.py; not ratified values."]
    for section, body in values.items():
        lines.append("")
        lines.append(f"[{section}]")
        lines.extend(f"{key} = {_render_value(value)}" for key, value in body.items())
    if "__dropped__" not in provenance:
        for section, body in provenance.items():
            lines.append("")
            lines.append(f"[provenance.{section}]")
            lines.extend(f"{key} = {_render_value(value)}" for key, value in body.items())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


__all__ = [
    "TEST_ONLY_FILE_VALUES",
    "TEST_ONLY_PROVENANCE_LABEL",
    "test_only_binance_limits",
    "test_only_client_limits",
    "test_only_drift_limits",
    "test_only_rate_limit_policy",
    "test_only_signed_call_policy",
    "test_only_stream_limits",
    "write_limits_toml",
]
