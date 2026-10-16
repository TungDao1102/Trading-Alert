"""The structures that carry the O-18-01 safety thresholds and their strict loader (plan 18-07).

No number lives in this module. Every safety threshold of the Binance client, the signed
calls, the clock-drift guard and the user-data stream is a required, keyword-only field of a
frozen dataclass; the values are the user's (decision record ``18-DEC-O-18-01.md``) and reach
the process only through ``config/binance/binance-limits-v1.toml``, which plan 18-09 writes.
``tests/test_no_unratified_defaults.py`` scans ``src`` and ``scripts`` so that no canonical
key name is ever given a numeric default.

The file format (``config/binance/README.md``):

* exactly the sections ``client``, ``signed_calls``, ``drift``, ``stream`` and ``provenance``;
* exactly the 27 keys of ``CANONICAL_KEYS``; a missing or unknown key refuses to load (the
  former single key ``signed_calls.rate_limit_no_retry_after_wait_seconds`` is unknown: the
  user split it into a 418 key and a 429 key);
* integers that are not booleans, positive except ``client.sdk_retries`` and
  ``client.sdk_backoff_ms`` (zero allowed); ``drift.include_measurement_uncertainty`` is a
  boolean; the string ``none`` only for the three nullable keys;
* ``provenance.<section>.<key>`` gives every key one of STRUCTURAL, COST_GUARD, DECISION or
  EXPERIMENT; a PLACEHOLDER, unknown or absent label refuses to load;
* ``drift.behind_limit_ms`` must not exceed ``signed_calls.recv_window_ms`` (Binance rejects a
  request older than recvWindow, so a larger behind limit could never block first).

Every refusal raises ``LimitsNotRatified`` (``LimitsFileMissing`` for a missing file) with a
message that names keys or sections only: never a value and never a path.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from types import MappingProxyType
from typing import Any

from src.adapters.binance_client import ClientLimits

# --------------------------------------------------------------------------- #
# The canonical keys (decisions/18-O-18-01-table.md, 27 keys after the 2026-10-16 amendment).
# --------------------------------------------------------------------------- #

CANONICAL_KEYS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "client": ("rest_timeout_ms", "sdk_retries", "sdk_backoff_ms"),
        "signed_calls": (
            "recv_window_ms",
            "rate_limit_418_no_retry_after_wait_seconds",
            "rate_limit_429_no_retry_after_wait_seconds",
            "rate_limit_retry_after_cap_seconds",
        ),
        "drift": (
            "ahead_limit_ms",
            "behind_limit_ms",
            "include_measurement_uncertainty",
            "max_measurement_age_seconds",
            "periodic_remeasure_interval_seconds",
        ),
        "stream": (
            "keepalive_interval_seconds",
            "keepalive_failure_tolerance",
            "project_rotation_interval_seconds",
            "reconnect_max_attempts",
            "reconnect_max_delay_seconds",
            "reconnect_wait_multiplier_seconds",
            "reconnect_wait_max_seconds",
            "sdk_reconnect_delay_ms",
            "sdk_reconnect_attempts",
            "snapshot_deadline_seconds",
            "snapshot_max_attempts",
            "snapshot_wait_multiplier_seconds",
            "snapshot_wait_max_seconds",
            "max_liveness_age_seconds",
            "event_queue_max",
        ),
    }
)

PROVENANCE_SECTION = "provenance"
ALLOWED_SECTIONS: frozenset[str] = frozenset((*CANONICAL_KEYS, PROVENANCE_SECTION))
PROVENANCE_LABELS: frozenset[str] = frozenset(
    {"STRUCTURAL", "COST_GUARD", "DECISION", "EXPERIMENT"}
)
NONE_WORD = "none"

# The three keys that accept the word none (mapped to None).
NULLABLE_KEYS: frozenset[str] = frozenset(
    {
        "drift.periodic_remeasure_interval_seconds",
        "stream.project_rotation_interval_seconds",
        "stream.max_liveness_age_seconds",
    }
)
# The only boolean key.
BOOLEAN_KEYS: frozenset[str] = frozenset({"drift.include_measurement_uncertainty"})
# The only integers that may be zero (the SDK's own retry count and backoff unit).
ZERO_ALLOWED_KEYS: frozenset[str] = frozenset({"client.sdk_retries", "client.sdk_backoff_ms"})

# The signed_calls keys of the rate-limit policy and the RateLimitPolicy field each fills. The
# field names are the keyword names of `rate_limit_decision` (plan 18-05).
RATE_LIMIT_KEY_TO_FIELD: Mapping[str, str] = MappingProxyType(
    {
        "rate_limit_418_no_retry_after_wait_seconds": "no_retry_after_wait_418_seconds",
        "rate_limit_429_no_retry_after_wait_seconds": "no_retry_after_wait_429_seconds",
        "rate_limit_retry_after_cap_seconds": "retry_after_cap_seconds",
    }
)


# --------------------------------------------------------------------------- #
# Errors.
# --------------------------------------------------------------------------- #


class LimitsNotRatified(Exception):  # noqa: N818 - public name fixed by plan 18-07
    """The limits file is unreadable or incomplete; the message names keys or sections only."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("binance limits not ratified: " + "; ".join(self.problems))


class LimitsFileMissing(LimitsNotRatified):
    """The limits file does not exist (it is written only by plan 18-09)."""


# --------------------------------------------------------------------------- #
# Field validation (ValueError for a bad value, TypeError for a wrong member type).
# --------------------------------------------------------------------------- #


def _require_positive_int(owner: str, name: str, value: object) -> None:
    if type(value) is not int:
        raise ValueError(f"{owner}.{name} must be an int (not a bool)")
    if value <= 0:
        raise ValueError(f"{owner}.{name} must be positive")


def _require_positive_int_or_none(owner: str, name: str, value: object) -> None:
    if value is None:
        return
    if type(value) is not int:
        raise ValueError(f"{owner}.{name} must be an int (not a bool) or None")
    if value <= 0:
        raise ValueError(f"{owner}.{name} must be positive or None")


def _require_bool(owner: str, name: str, value: object) -> None:
    if type(value) is not bool:
        raise ValueError(f"{owner}.{name} must be a bool")


# --------------------------------------------------------------------------- #
# The structures. Every field is required and keyword-only; none has a default.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class RateLimitPolicy:
    """The REST waits after a rate-limit answer (user record ``18-DEC-O-18-01.md``).

    ``no_retry_after_wait_418_seconds``: the REST ban after an HTTP 418 without a usable
    Retry-After. ``no_retry_after_wait_429_seconds``: the pause of every REST call of the
    process after an HTTP 429 without one (no call is retried because of a 429).
    ``retry_after_cap_seconds``: bounds a valid Retry-After and both fallbacks. The three are
    the user's values; none is derived from another and no rule relates them. The field names
    equal the keyword names of ``rate_limit_decision`` (plan 18-05).
    """

    no_retry_after_wait_418_seconds: int
    no_retry_after_wait_429_seconds: int
    retry_after_cap_seconds: int

    def __post_init__(self) -> None:
        for item in fields(self):
            _require_positive_int("RateLimitPolicy", item.name, getattr(self, item.name))


@dataclass(frozen=True, kw_only=True)
class SignedCallPolicy:
    """The explicit ``recvWindow`` of every signed call and the rate-limit policy (D-14)."""

    recv_window_ms: int
    rate_limit: RateLimitPolicy

    def __post_init__(self) -> None:
        _require_positive_int("SignedCallPolicy", "recv_window_ms", self.recv_window_ms)
        if not isinstance(self.rate_limit, RateLimitPolicy):
            raise TypeError("SignedCallPolicy.rate_limit must be a RateLimitPolicy")


@dataclass(frozen=True, kw_only=True)
class DriftLimits:
    """The server-time drift limits of ``ClockDriftGuard`` (D-14).

    Offsets are host minus Binance (positive: the host clock is ahead). With
    ``include_measurement_uncertainty`` half the round trip is added to the offset before it is
    compared with each limit. ``periodic_remeasure_interval_seconds`` may be None (re-measure
    only on request); the age rule applies either way.
    """

    ahead_limit_ms: int
    behind_limit_ms: int
    include_measurement_uncertainty: bool
    max_measurement_age_seconds: int
    periodic_remeasure_interval_seconds: int | None

    def __post_init__(self) -> None:
        _require_positive_int("DriftLimits", "ahead_limit_ms", self.ahead_limit_ms)
        _require_positive_int("DriftLimits", "behind_limit_ms", self.behind_limit_ms)
        _require_bool(
            "DriftLimits", "include_measurement_uncertainty", self.include_measurement_uncertainty
        )
        _require_positive_int(
            "DriftLimits", "max_measurement_age_seconds", self.max_measurement_age_seconds
        )
        _require_positive_int_or_none(
            "DriftLimits",
            "periodic_remeasure_interval_seconds",
            self.periodic_remeasure_interval_seconds,
        )


_STREAM_NULLABLE = frozenset({"project_rotation_interval_seconds", "max_liveness_age_seconds"})


@dataclass(frozen=True, kw_only=True)
class StreamLimits:
    """The user-data stream thresholds (keepalive, rotation, rebuild, snapshot, queue)."""

    keepalive_interval_seconds: int
    keepalive_failure_tolerance: int
    project_rotation_interval_seconds: int | None
    reconnect_max_attempts: int
    reconnect_max_delay_seconds: int
    reconnect_wait_multiplier_seconds: int
    reconnect_wait_max_seconds: int
    sdk_reconnect_delay_ms: int
    sdk_reconnect_attempts: int
    snapshot_deadline_seconds: int
    snapshot_max_attempts: int
    snapshot_wait_multiplier_seconds: int
    snapshot_wait_max_seconds: int
    max_liveness_age_seconds: int | None
    event_queue_max: int

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name in _STREAM_NULLABLE:
                _require_positive_int_or_none("StreamLimits", item.name, value)
            else:
                _require_positive_int("StreamLimits", item.name, value)


@dataclass(frozen=True, kw_only=True)
class BinanceLimits:
    """Every ratified threshold: ``client``, ``signed``, ``drift`` and ``stream``."""

    client: ClientLimits
    signed: SignedCallPolicy
    drift: DriftLimits
    stream: StreamLimits

    def __post_init__(self) -> None:
        for name, kind in (
            ("client", ClientLimits),
            ("signed", SignedCallPolicy),
            ("drift", DriftLimits),
            ("stream", StreamLimits),
        ):
            if not isinstance(getattr(self, name), kind):
                raise TypeError(f"BinanceLimits.{name} must be a {kind.__name__}")
        if self.drift.behind_limit_ms > self.signed.recv_window_ms:
            raise ValueError(
                "drift.behind_limit_ms must not exceed signed_calls.recv_window_ms "
                "(a request older than recvWindow is rejected before the guard could block)"
            )


# --------------------------------------------------------------------------- #
# The loader.
# --------------------------------------------------------------------------- #


def _table(raw: Mapping[str, Any], name: str, problems: list[str]) -> Mapping[str, Any]:
    if name not in raw:
        return {}
    section = raw[name]
    if not isinstance(section, dict):
        problems.append(f"{name} (must be a table)")
        return {}
    return section


def _read_value(section: Mapping[str, Any], dotted: str, key: str, problems: list[str]) -> Any:
    """The validated value of one key, or None after adding a problem (names only)."""
    if key not in section:
        problems.append(f"{dotted} (missing key)")
        return None
    value = section[key]
    if dotted in BOOLEAN_KEYS:
        if not isinstance(value, bool):
            problems.append(f"{dotted} (must be true or false)")
        return value
    if isinstance(value, str):
        if dotted in NULLABLE_KEYS and value == NONE_WORD:
            return None
        if dotted in NULLABLE_KEYS:
            problems.append(f"{dotted} (must be an integer or the word {NONE_WORD})")
        else:
            problems.append(f"{dotted} (must be an integer)")
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        problems.append(f"{dotted} (must be an integer, not a boolean or a float)")
        return None
    if value < 0 or (value == 0 and dotted not in ZERO_ALLOWED_KEYS):
        problems.append(f"{dotted} (must be a positive integer)")
        return None
    return value


def _check_provenance(raw: Mapping[str, Any], problems: list[str]) -> None:
    if PROVENANCE_SECTION not in raw:
        problems.append(f"{PROVENANCE_SECTION} (missing table: every key needs a label)")
        return
    provenance = _table(raw, PROVENANCE_SECTION, problems)
    for section in sorted(set(provenance) - set(CANONICAL_KEYS)):
        problems.append(f"{PROVENANCE_SECTION}.{section} (unknown section)")
    for section, keys in CANONICAL_KEYS.items():
        labels = provenance.get(section, {})
        if not isinstance(labels, dict):
            problems.append(f"{PROVENANCE_SECTION}.{section} (must be a table)")
            labels = {}
        for key in sorted(set(labels) - set(keys)):
            problems.append(f"{PROVENANCE_SECTION}.{section}.{key} (unknown key)")
        for key in keys:
            dotted = f"{section}.{key}"
            if key not in labels:
                problems.append(f"{dotted} (missing provenance label)")
                continue
            label = labels[key]
            if label == "PLACEHOLDER":
                problems.append(f"{dotted} (provenance PLACEHOLDER refuses to load)")
            elif not isinstance(label, str) or label not in PROVENANCE_LABELS:
                problems.append(
                    f"{dotted} (provenance label must be one of "
                    + ", ".join(sorted(PROVENANCE_LABELS))
                    + ")"
                )


def parse_binance_limits(raw: Mapping[str, Any]) -> BinanceLimits:
    """Validate a parsed TOML document; every key is required and nothing else is allowed.

    Raises:
        LimitsNotRatified: naming every missing, unknown or invalid key or section.
    """
    problems: list[str] = []
    for section in sorted(set(raw) - ALLOWED_SECTIONS):
        problems.append(f"{section} (unknown section)")
    values: dict[str, dict[str, Any]] = {}
    for section, keys in CANONICAL_KEYS.items():
        body = _table(raw, section, problems)
        for key in sorted(set(body) - set(keys)):
            problems.append(f"{section}.{key} (unknown key)")
        values[section] = {
            key: _read_value(body, f"{section}.{key}", key, problems) for key in keys
        }
    _check_provenance(raw, problems)
    if problems:
        raise LimitsNotRatified(problems)

    signed = values["signed_calls"]
    try:
        return BinanceLimits(
            client=ClientLimits(**values["client"]),
            signed=SignedCallPolicy(
                recv_window_ms=signed["recv_window_ms"],
                rate_limit=RateLimitPolicy(
                    **{field: signed[key] for key, field in RATE_LIMIT_KEY_TO_FIELD.items()}
                ),
            ),
            drift=DriftLimits(**values["drift"]),
            stream=StreamLimits(**values["stream"]),
        )
    except ValueError as exc:
        # The structure's own messages name fields and keys only, never a value.
        raise LimitsNotRatified([str(exc)]) from None


def load_binance_limits(path: Path | str) -> BinanceLimits:
    """Load the ratified limits file. There is no default file and no default value.

    Raises:
        LimitsFileMissing: the file does not exist (the message carries no path).
        LimitsNotRatified: the file is not valid TOML or any entry is missing or invalid.
    """
    file = Path(path)
    if not file.is_file():
        raise LimitsFileMissing(["the binance limits file does not exist (plan 18-09 writes it)"])
    try:
        raw = tomllib.loads(file.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError):
        raise LimitsNotRatified(["the binance limits file is not valid TOML"]) from None
    return parse_binance_limits(raw)


__all__ = [
    "ALLOWED_SECTIONS",
    "BOOLEAN_KEYS",
    "CANONICAL_KEYS",
    "NULLABLE_KEYS",
    "PROVENANCE_LABELS",
    "RATE_LIMIT_KEY_TO_FIELD",
    "ZERO_ALLOWED_KEYS",
    "BinanceLimits",
    "DriftLimits",
    "LimitsFileMissing",
    "LimitsNotRatified",
    "RateLimitPolicy",
    "SignedCallPolicy",
    "StreamLimits",
    "load_binance_limits",
    "parse_binance_limits",
]
