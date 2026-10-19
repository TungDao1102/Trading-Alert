"""Limit structures, the strict limits-file loader, the pure drift decision and the guard (18-07).

Every value used here is a TEST_ONLY value from `tests/support/limits.py`; none of them is a
ratified threshold. Nothing reads a clock, a network or `.env`.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from src.adapters import binance_clock as bclock
from src.adapters import binance_limits as bl
from src.adapters.binance_client import ClientLimits

from tests.support import limits as tl
from tests.support.ast_guards import float_constructor_calls, wall_clock_calls

ROOT = Path(__file__).resolve().parents[1]
LIMITS_MODULE = ROOT / "src" / "adapters" / "binance_limits.py"
CLOCK_MODULE = ROOT / "src" / "adapters" / "binance_clock.py"

T0 = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

EXPECTED_KEYS: dict[str, tuple[str, ...]] = {
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

NULLABLE = (
    "drift.periodic_remeasure_interval_seconds",
    "stream.project_rotation_interval_seconds",
    "stream.max_liveness_age_seconds",
)


# --------------------------------------------------------------------------- #
# Tracer: a TOML file becomes a BinanceLimits and feeds a drift verdict and the guard.
# --------------------------------------------------------------------------- #


def test_tracer_file_to_limits_to_verdict_to_guard(tmp_path: Path) -> None:
    limits = bl.load_binance_limits(tl.write_limits_toml(tmp_path / "limits.toml"))
    assert limits == tl.test_only_binance_limits()

    verdict = bclock.evaluate_clock_drift(
        before_ms=10_000,
        server_ms=10_000,
        after_ms=10_000,
        limits=limits.drift,
        measured_at_utc=T0,
    )
    assert verdict.within_limits is True
    guard = bclock.ClockDriftGuard(limits=limits.drift)
    assert guard.entries_allowed(T0) is False
    guard.record(verdict)
    assert guard.entries_allowed(T0) is True
    assert guard.blocked_reason(T0) is None


# --------------------------------------------------------------------------- #
# Structures: required keyword-only fields, no defaults, strict types.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "cls",
    [bl.RateLimitPolicy, bl.SignedCallPolicy, bl.DriftLimits, bl.StreamLimits, bl.BinanceLimits],
)
def test_no_argument_construction_raises_type_error(cls: type) -> None:
    with pytest.raises(TypeError):
        cls()


@pytest.mark.parametrize(
    "cls",
    [bl.RateLimitPolicy, bl.SignedCallPolicy, bl.DriftLimits, bl.StreamLimits, bl.BinanceLimits],
)
def test_every_field_is_required_keyword_only_and_frozen(cls: type) -> None:
    params = dataclasses.fields(cls)
    assert params
    for field in params:
        assert field.default is dataclasses.MISSING, field.name
        assert field.default_factory is dataclasses.MISSING, field.name
        assert field.kw_only is True, field.name
    assert cls.__dataclass_params__.frozen is True  # type: ignore[attr-defined]


def test_rate_limit_policy_field_names_are_rate_limit_decision_keywords() -> None:
    import inspect

    from src.domain.exchange_errors import rate_limit_decision

    keyword_only = {
        name
        for name, param in inspect.signature(rate_limit_decision).parameters.items()
        if param.kind is inspect.Parameter.KEYWORD_ONLY
    }
    fields = {field.name for field in dataclasses.fields(bl.RateLimitPolicy)}
    assert fields == {
        "no_retry_after_wait_418_seconds",
        "no_retry_after_wait_429_seconds",
        "retry_after_cap_seconds",
    }
    assert fields == keyword_only


def test_dataclass_field_order_follows_the_canonical_keys() -> None:
    assert tuple(f.name for f in dataclasses.fields(bl.DriftLimits)) == EXPECTED_KEYS["drift"]
    assert tuple(f.name for f in dataclasses.fields(bl.StreamLimits)) == EXPECTED_KEYS["stream"]
    assert tuple(f.name for f in dataclasses.fields(bl.SignedCallPolicy)) == (
        "recv_window_ms",
        "rate_limit",
    )
    assert tuple(f.name for f in dataclasses.fields(bl.BinanceLimits)) == (
        "client",
        "signed",
        "drift",
        "stream",
    )


def _replace(obj: Any, **changes: Any) -> Any:
    return dataclasses.replace(obj, **changes)


@pytest.mark.parametrize(
    ("builder", "field"),
    [
        (tl.test_only_rate_limit_policy, "no_retry_after_wait_418_seconds"),
        (tl.test_only_rate_limit_policy, "no_retry_after_wait_429_seconds"),
        (tl.test_only_rate_limit_policy, "retry_after_cap_seconds"),
        (tl.test_only_signed_call_policy, "recv_window_ms"),
        (tl.test_only_drift_limits, "ahead_limit_ms"),
        (tl.test_only_drift_limits, "behind_limit_ms"),
        (tl.test_only_drift_limits, "max_measurement_age_seconds"),
        (tl.test_only_drift_limits, "periodic_remeasure_interval_seconds"),
        *[(tl.test_only_stream_limits, key) for key in EXPECTED_KEYS["stream"]],
    ],
)
@pytest.mark.parametrize("bad", [True, False, 0, -1, 1.5, "7"])
def test_int_fields_reject_bool_non_int_and_non_positive(
    builder: Any, field: str, bad: object
) -> None:
    with pytest.raises(ValueError, match=field):
        _replace(builder(), **{field: bad})


@pytest.mark.parametrize(
    ("builder", "field"),
    [
        (tl.test_only_drift_limits, "periodic_remeasure_interval_seconds"),
        (tl.test_only_stream_limits, "project_rotation_interval_seconds"),
        (tl.test_only_stream_limits, "max_liveness_age_seconds"),
    ],
)
def test_the_three_nullable_fields_accept_none(builder: Any, field: str) -> None:
    assert getattr(_replace(builder(), **{field: None}), field) is None


@pytest.mark.parametrize(
    ("builder", "field"),
    [
        (tl.test_only_drift_limits, "ahead_limit_ms"),
        (tl.test_only_stream_limits, "keepalive_interval_seconds"),
        (tl.test_only_stream_limits, "event_queue_max"),
        (tl.test_only_signed_call_policy, "recv_window_ms"),
        (tl.test_only_rate_limit_policy, "retry_after_cap_seconds"),
    ],
)
def test_non_nullable_fields_refuse_none(builder: Any, field: str) -> None:
    with pytest.raises(ValueError, match=field):
        _replace(builder(), **{field: None})


@pytest.mark.parametrize("bad", [1, 0, None, "true"])
def test_include_measurement_uncertainty_accepts_only_a_bool(bad: object) -> None:
    with pytest.raises(ValueError, match="include_measurement_uncertainty"):
        _replace(tl.test_only_drift_limits(), include_measurement_uncertainty=bad)


def test_client_zero_retries_and_backoff_are_accepted() -> None:
    client = ClientLimits(
        rest_timeout_ms=tl.TEST_ONLY_REST_TIMEOUT_MS, sdk_retries=0, sdk_backoff_ms=0
    )
    limits = _replace(tl.test_only_binance_limits(), client=client)
    assert limits.client.sdk_retries == 0


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("client", object()),
        ("signed", tl.test_only_rate_limit_policy()),
        ("drift", tl.test_only_stream_limits()),
        ("stream", tl.test_only_drift_limits()),
    ],
)
def test_binance_limits_rejects_wrong_member_types(field: str, bad: object) -> None:
    with pytest.raises(TypeError, match=field):
        _replace(tl.test_only_binance_limits(), **{field: bad})


def test_signed_call_policy_rejects_a_non_policy_rate_limit() -> None:
    with pytest.raises(TypeError, match="rate_limit"):
        bl.SignedCallPolicy(recv_window_ms=tl.TEST_ONLY_RECV_WINDOW_MS, rate_limit=object())  # type: ignore[arg-type]


def test_behind_limit_above_recv_window_is_refused_by_the_structure() -> None:
    drift = _replace(tl.test_only_drift_limits(), behind_limit_ms=tl.TEST_ONLY_RECV_WINDOW_MS + 1)
    with pytest.raises(ValueError, match="behind_limit_ms"):
        _replace(tl.test_only_binance_limits(), drift=drift)
    equal = _replace(tl.test_only_drift_limits(), behind_limit_ms=tl.TEST_ONLY_RECV_WINDOW_MS)
    assert _replace(tl.test_only_binance_limits(), drift=equal).drift.behind_limit_ms == (
        tl.TEST_ONLY_RECV_WINDOW_MS
    )


# --------------------------------------------------------------------------- #
# Canonical keys.
# --------------------------------------------------------------------------- #


def test_canonical_keys_are_exactly_the_27_keys() -> None:
    assert dict(bl.CANONICAL_KEYS) == EXPECTED_KEYS
    assert [len(keys) for keys in bl.CANONICAL_KEYS.values()] == [3, 4, 5, 15]
    assert sum(len(keys) for keys in bl.CANONICAL_KEYS.values()) == 27
    assert bl.CANONICAL_KEYS["signed_calls"] == (
        "recv_window_ms",
        "rate_limit_418_no_retry_after_wait_seconds",
        "rate_limit_429_no_retry_after_wait_seconds",
        "rate_limit_retry_after_cap_seconds",
    )
    assert "rate_limit_no_retry_after_wait_seconds" not in bl.CANONICAL_KEYS["signed_calls"]


def test_canonical_keys_are_read_only() -> None:
    with pytest.raises(TypeError):
        bl.CANONICAL_KEYS["extra"] = ()  # type: ignore[index]


def test_the_test_only_rate_limit_values_are_pairwise_distinct() -> None:
    values = {
        tl.TEST_ONLY_RATE_LIMIT_418_NO_RETRY_AFTER_WAIT_SECONDS,
        tl.TEST_ONLY_RATE_LIMIT_429_NO_RETRY_AFTER_WAIT_SECONDS,
        tl.TEST_ONLY_RATE_LIMIT_RETRY_AFTER_CAP_SECONDS,
    }
    assert len(values) == 3


# --------------------------------------------------------------------------- #
# Loader: happy path and mapping.
# --------------------------------------------------------------------------- #


def test_happy_path_load_equals_the_test_only_object(tmp_path: Path) -> None:
    path = tl.write_limits_toml(tmp_path / "limits.toml")
    assert bl.load_binance_limits(path) == tl.test_only_binance_limits()
    assert bl.load_binance_limits(str(path)) == tl.test_only_binance_limits()


def test_rate_limit_keys_map_to_distinct_fields(tmp_path: Path) -> None:
    path = tl.write_limits_toml(
        tmp_path / "limits.toml",
        overrides={
            "signed_calls.rate_limit_418_no_retry_after_wait_seconds": 4181,
            "signed_calls.rate_limit_429_no_retry_after_wait_seconds": 4291,
            "signed_calls.rate_limit_retry_after_cap_seconds": 9991,
        },
    )
    policy = bl.load_binance_limits(path).signed.rate_limit
    assert policy.no_retry_after_wait_418_seconds == 4181
    assert policy.no_retry_after_wait_429_seconds == 4291
    assert policy.retry_after_cap_seconds == 9991


def test_no_consistency_rule_between_the_three_rate_limit_values(tmp_path: Path) -> None:
    path = tl.write_limits_toml(
        tmp_path / "limits.toml",
        overrides={
            "signed_calls.rate_limit_418_no_retry_after_wait_seconds": 50,
            "signed_calls.rate_limit_429_no_retry_after_wait_seconds": 70,
            "signed_calls.rate_limit_retry_after_cap_seconds": 10,
        },
    )
    assert bl.load_binance_limits(path).signed.rate_limit.retry_after_cap_seconds == 10


@pytest.mark.parametrize("dotted", NULLABLE)
def test_the_word_none_maps_to_none_for_the_three_nullable_keys(
    tmp_path: Path, dotted: str
) -> None:
    path = tl.write_limits_toml(tmp_path / "limits.toml", overrides={dotted: None})
    limits = bl.load_binance_limits(path)
    section, key = dotted.split(".")
    holder = limits.drift if section == "drift" else limits.stream
    assert getattr(holder, key) is None


def test_zero_retries_and_backoff_load(tmp_path: Path) -> None:
    path = tl.write_limits_toml(
        tmp_path / "limits.toml",
        overrides={"client.sdk_retries": 0, "client.sdk_backoff_ms": 0},
    )
    client = bl.load_binance_limits(path).client
    assert (client.sdk_retries, client.sdk_backoff_ms) == (0, 0)


@pytest.mark.parametrize("label", ["STRUCTURAL", "COST_GUARD", "DECISION", "EXPERIMENT"])
def test_every_allowed_provenance_label_loads(tmp_path: Path, label: str) -> None:
    path = tl.write_limits_toml(
        tmp_path / "limits.toml", overrides={"provenance.stream.event_queue_max": label}
    )
    assert bl.load_binance_limits(path) == tl.test_only_binance_limits()


def test_provenance_written_as_dotted_keys_under_one_table_loads(tmp_path: Path) -> None:
    lines = []
    for section, body in tl.TEST_ONLY_FILE_VALUES.items():
        lines.append(f"[{section}]")
        for key, value in body.items():
            rendered = (
                '"none"'
                if value is None
                else ("true" if value is True else "false" if value is False else str(value))
            )
            lines.append(f"{key} = {rendered}")
    lines.append("[provenance]")
    for section, body in tl.TEST_ONLY_FILE_VALUES.items():
        lines.extend(f'{section}.{key} = "DECISION"' for key in body)
    path = tmp_path / "limits.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert bl.load_binance_limits(path) == tl.test_only_binance_limits()


# --------------------------------------------------------------------------- #
# Loader: refusals (fail closed). Messages name keys or sections only.
# --------------------------------------------------------------------------- #

_REFUSALS: list[tuple[str, dict[str, Any], str]] = [
    # missing keys (each rate-limit key on its own)
    (
        "missing 418 fallback",
        {"drop": ["signed_calls.rate_limit_418_no_retry_after_wait_seconds"]},
        "signed_calls.rate_limit_418_no_retry_after_wait_seconds",
    ),
    (
        "missing 429 fallback",
        {"drop": ["signed_calls.rate_limit_429_no_retry_after_wait_seconds"]},
        "signed_calls.rate_limit_429_no_retry_after_wait_seconds",
    ),
    (
        "missing cap",
        {"drop": ["signed_calls.rate_limit_retry_after_cap_seconds"]},
        "signed_calls.rate_limit_retry_after_cap_seconds",
    ),
    (
        "missing recv window",
        {"drop": ["signed_calls.recv_window_ms"]},
        "signed_calls.recv_window_ms",
    ),
    ("missing client key", {"drop": ["client.rest_timeout_ms"]}, "client.rest_timeout_ms"),
    ("missing stream key", {"drop": ["stream.event_queue_max"]}, "stream.event_queue_max"),
    (
        "missing nullable key",
        {"drop": ["stream.max_liveness_age_seconds"]},
        "stream.max_liveness_age_seconds",
    ),
    ("missing section", {"drop": ["drift"]}, "drift.ahead_limit_ms"),
    # unknown keys and sections
    (
        "retired single rate-limit key",
        {"extra": {"signed_calls.rate_limit_no_retry_after_wait_seconds": 61}},
        "signed_calls.rate_limit_no_retry_after_wait_seconds",
    ),
    (
        "unknown key",
        {"extra": {"stream.keepalive_margin_seconds": 5}},
        "stream.keepalive_margin_seconds",
    ),
    ("unknown section", {"extra": {"health.max_age_seconds": 5}}, "health"),
    (
        "unknown provenance key",
        {"extra": {"provenance.stream.keepalive_margin_seconds": "DECISION"}},
        "provenance.stream.keepalive_margin_seconds",
    ),
    (
        "unknown provenance section",
        {"extra": {"provenance.health.x": "DECISION"}},
        "provenance.health",
    ),
    # malformed values
    (
        "float value",
        {"overrides": {"signed_calls.recv_window_ms": 4321.0}},
        "signed_calls.recv_window_ms",
    ),
    ("bool for int key", {"overrides": {"stream.event_queue_max": True}}, "stream.event_queue_max"),
    (
        "string other than none",
        {"overrides": {"drift.periodic_remeasure_interval_seconds": "never"}},
        "drift.periodic_remeasure_interval_seconds",
    ),
    (
        "none for a non-nullable key",
        {"overrides": {"drift.ahead_limit_ms": None}},
        "drift.ahead_limit_ms",
    ),
    ("string number", {"overrides": {"client.rest_timeout_ms": "1234"}}, "client.rest_timeout_ms"),
    (
        "negative value",
        {"overrides": {"stream.snapshot_max_attempts": -3}},
        "stream.snapshot_max_attempts",
    ),
    (
        "zero value",
        {"overrides": {"drift.max_measurement_age_seconds": 0}},
        "drift.max_measurement_age_seconds",
    ),
    (
        "zero nullable",
        {"overrides": {"stream.project_rotation_interval_seconds": 0}},
        "stream.project_rotation_interval_seconds",
    ),
    ("negative retries", {"overrides": {"client.sdk_retries": -1}}, "client.sdk_retries"),
    (
        "int for the bool key",
        {"overrides": {"drift.include_measurement_uncertainty": 1}},
        "drift.include_measurement_uncertainty",
    ),
    (
        "none for the bool key",
        {"overrides": {"drift.include_measurement_uncertainty": None}},
        "drift.include_measurement_uncertainty",
    ),
    # provenance
    (
        "PLACEHOLDER label",
        {"overrides": {"provenance.drift.behind_limit_ms": "PLACEHOLDER"}},
        "drift.behind_limit_ms",
    ),
    (
        "unknown label",
        {"overrides": {"provenance.drift.behind_limit_ms": "GUESS"}},
        "drift.behind_limit_ms",
    ),
    ("non-string label", {"overrides": {"provenance.client.sdk_retries": 3}}, "client.sdk_retries"),
    ("absent label", {"drop": ["provenance.stream.event_queue_max"]}, "stream.event_queue_max"),
    ("absent provenance section", {"drop": ["provenance.client"]}, "client.rest_timeout_ms"),
    ("absent provenance table", {"drop": ["provenance"]}, "provenance"),
    # cross-key rule
    (
        "behind limit above recv window",
        {"overrides": {"drift.behind_limit_ms": tl.TEST_ONLY_RECV_WINDOW_MS + 1}},
        "drift.behind_limit_ms",
    ),
]


@pytest.mark.parametrize(
    ("case", "edits", "named"), _REFUSALS, ids=[case for case, _, _ in _REFUSALS]
)
def test_refusals_raise_limits_not_ratified_naming_the_key(
    tmp_path: Path, case: str, edits: dict[str, Any], named: str
) -> None:
    path = tl.write_limits_toml(tmp_path / "limits.toml", **edits)
    with pytest.raises(bl.LimitsNotRatified) as caught:
        bl.load_binance_limits(path)
    assert named in str(caught.value)
    assert not isinstance(caught.value, bl.LimitsFileMissing)


@pytest.mark.parametrize("value", [4321.0, True, "never", -3, 999_999])
def test_refusal_messages_never_carry_a_value(tmp_path: Path, value: object) -> None:
    path = tl.write_limits_toml(
        tmp_path / "limits.toml", overrides={"drift.behind_limit_ms": value}
    )
    with pytest.raises(bl.LimitsNotRatified) as caught:
        bl.load_binance_limits(path)
    message = str(caught.value)
    assert "drift.behind_limit_ms" in message
    assert str(value) not in message
    assert str(tmp_path) not in message


def test_an_unparseable_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "limits.toml"
    path.write_text("[client\nrest_timeout_ms = = 1\n", encoding="utf-8")
    with pytest.raises(bl.LimitsNotRatified) as caught:
        bl.load_binance_limits(path)
    assert not isinstance(caught.value, bl.LimitsFileMissing)
    assert str(tmp_path) not in str(caught.value)


def test_a_section_that_is_not_a_table_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "limits.toml"
    # Only `stream` is wrong (a scalar); every other table is valid and nothing is renamed, so
    # the refusal can only come from the "must be a table" check (review WR-10).
    good = tl.write_limits_toml(tmp_path / "good.toml", drop=["stream"]).read_text(encoding="utf-8")
    path.write_text('stream = "off"\n' + good, encoding="utf-8")
    with pytest.raises(bl.LimitsNotRatified) as caught:
        bl.load_binance_limits(path)
    assert "stream (must be a table)" in str(caught.value)
    assert "stream_x" not in str(caught.value)


def test_a_missing_file_raises_limits_file_missing(tmp_path: Path) -> None:
    missing = tmp_path / "absent" / "binance-limits-v1.toml"
    with pytest.raises(bl.LimitsFileMissing) as caught:
        bl.load_binance_limits(missing)
    assert isinstance(caught.value, bl.LimitsNotRatified)
    assert str(tmp_path) not in str(caught.value)


def test_a_directory_is_not_a_limits_file(tmp_path: Path) -> None:
    with pytest.raises(bl.LimitsFileMissing):
        bl.load_binance_limits(tmp_path)


# --------------------------------------------------------------------------- #
# Pure drift decision.
# --------------------------------------------------------------------------- #


def _drift(*, include: bool) -> bl.DriftLimits:
    return _replace(tl.test_only_drift_limits(), include_measurement_uncertainty=include)


AHEAD = tl.TEST_ONLY_AHEAD_LIMIT_MS
BEHIND = tl.TEST_ONLY_BEHIND_LIMIT_MS


def _verdict(before: int, server: int, after: int, *, include: bool) -> bclock.DriftVerdict:
    return bclock.evaluate_clock_drift(
        before_ms=before,
        server_ms=server,
        after_ms=after,
        limits=_drift(include=include),
        measured_at_utc=T0,
    )


def test_offset_is_midpoint_minus_server_and_uncertainty_is_half_round_trip_rounded_up() -> None:
    verdict = _verdict(1_000, 900, 1_011, include=False)
    assert verdict.offset_ms == (1_000 + 1_011) // 2 - 900 == 105
    assert verdict.uncertainty_ms == 6
    assert verdict.measurement_failed is False
    assert verdict.failure_type is None
    assert verdict.measured_at_utc == T0
    even = _verdict(1_000, 1_000, 1_010, include=False)
    assert (even.offset_ms, even.uncertainty_ms) == (5, 5)


def test_a_host_behind_binance_has_a_negative_offset() -> None:
    assert _verdict(1_000, 1_300, 1_000, include=False).offset_ms == -300


@pytest.mark.parametrize("include", [False, True])
def test_exactly_at_the_limits_passes_with_zero_round_trip(include: bool) -> None:
    assert _verdict(10_000, 10_000 - AHEAD, 10_000, include=include).within_limits is True
    assert _verdict(10_000, 10_000 + BEHIND, 10_000, include=include).within_limits is True


@pytest.mark.parametrize("include", [False, True])
def test_one_over_the_limits_fails_with_zero_round_trip(include: bool) -> None:
    assert _verdict(10_000, 10_000 - AHEAD - 1, 10_000, include=include).within_limits is False
    assert _verdict(10_000, 10_000 + BEHIND + 1, 10_000, include=include).within_limits is False


def test_uncertainty_is_added_to_the_bound_only_when_included() -> None:
    # Round trip 10 ms: midpoint before + 5, uncertainty 5.
    mid = 10_005
    at_ahead_with_unc = mid - (AHEAD - 5)
    assert _verdict(10_000, at_ahead_with_unc, 10_010, include=True).within_limits is True
    assert _verdict(10_000, at_ahead_with_unc - 1, 10_010, include=True).within_limits is False
    assert _verdict(10_000, at_ahead_with_unc - 1, 10_010, include=False).within_limits is True
    assert _verdict(10_000, mid - AHEAD, 10_010, include=False).within_limits is True
    assert _verdict(10_000, mid - AHEAD - 1, 10_010, include=False).within_limits is False

    at_behind_with_unc = mid + (BEHIND - 5)
    assert _verdict(10_000, at_behind_with_unc, 10_010, include=True).within_limits is True
    assert _verdict(10_000, at_behind_with_unc + 1, 10_010, include=True).within_limits is False
    assert _verdict(10_000, at_behind_with_unc + 1, 10_010, include=False).within_limits is True
    assert _verdict(10_000, mid + BEHIND, 10_010, include=False).within_limits is True
    assert _verdict(10_000, mid + BEHIND + 1, 10_010, include=False).within_limits is False


def test_an_after_reading_earlier_than_the_before_reading_raises() -> None:
    with pytest.raises(ValueError, match="after_ms"):
        _verdict(1_000, 1_000, 999, include=True)


@pytest.mark.parametrize("name", ["before_ms", "server_ms", "after_ms"])
@pytest.mark.parametrize("bad", [1.0, True, "1", None])
def test_non_int_arguments_raise(name: str, bad: object) -> None:
    kwargs: dict[str, Any] = {"before_ms": 1, "server_ms": 1, "after_ms": 1}
    kwargs[name] = bad
    with pytest.raises(ValueError, match=name):
        bclock.evaluate_clock_drift(**kwargs, limits=tl.test_only_drift_limits())


def test_evaluate_requires_drift_limits() -> None:
    with pytest.raises(TypeError, match="limits"):
        bclock.evaluate_clock_drift(
            before_ms=1,
            server_ms=1,
            after_ms=1,
            limits=tl.test_only_stream_limits(),  # type: ignore[arg-type]
        )


def test_evaluate_rejects_a_naive_measured_at() -> None:
    with pytest.raises(ValueError, match="measured_at_utc"):
        bclock.evaluate_clock_drift(
            before_ms=1,
            server_ms=1,
            after_ms=1,
            limits=tl.test_only_drift_limits(),
            measured_at_utc=datetime(2026, 1, 1),  # noqa: DTZ001 - the naive value under test
        )


def test_drift_verdict_refuses_an_inconsistent_failed_verdict() -> None:
    with pytest.raises(ValueError):
        bclock.DriftVerdict(
            offset_ms=None,
            uncertainty_ms=None,
            within_limits=True,
            measurement_failed=True,
            measured_at_utc=T0,
            failure_type="X",
        )
    with pytest.raises(ValueError):
        bclock.DriftVerdict(
            offset_ms=None,
            uncertainty_ms=None,
            within_limits=False,
            measurement_failed=False,
            measured_at_utc=T0,
            failure_type=None,
        )


# --------------------------------------------------------------------------- #
# The entry guard.
# --------------------------------------------------------------------------- #


def _good(at: datetime = T0) -> bclock.DriftVerdict:
    return bclock.evaluate_clock_drift(
        before_ms=5_000,
        server_ms=5_000,
        after_ms=5_000,
        limits=tl.test_only_drift_limits(),
        measured_at_utc=at,
    )


def _failed(at: datetime = T0) -> bclock.DriftVerdict:
    return bclock.DriftVerdict.failed(failure_type="TimeoutError", measured_at_utc=at)


def test_guard_never_measured_blocks() -> None:
    guard = bclock.ClockDriftGuard(limits=tl.test_only_drift_limits())
    assert guard.entries_allowed(T0) is False
    assert guard.blocked_reason(T0) is bclock.DriftBlockReason.NEVER_MEASURED
    assert guard.last_verdict is None


def test_guard_failed_measurement_blocks() -> None:
    guard = bclock.ClockDriftGuard(limits=tl.test_only_drift_limits())
    guard.record(_good())
    guard.record(_failed(T0 + timedelta(seconds=1)))
    assert guard.entries_allowed(T0 + timedelta(seconds=1)) is False
    assert (
        guard.blocked_reason(T0 + timedelta(seconds=1))
        is bclock.DriftBlockReason.MEASUREMENT_FAILED
    )


def test_guard_out_of_limits_blocks() -> None:
    guard = bclock.ClockDriftGuard(limits=tl.test_only_drift_limits())
    out = bclock.evaluate_clock_drift(
        before_ms=5_000,
        server_ms=5_000 - AHEAD - 1,
        after_ms=5_000,
        limits=tl.test_only_drift_limits(),
        measured_at_utc=T0,
    )
    guard.record(out)
    assert guard.entries_allowed(T0) is False
    assert guard.blocked_reason(T0) is bclock.DriftBlockReason.OUT_OF_LIMITS


def test_guard_stale_blocks_and_the_age_boundary_is_inclusive() -> None:
    guard = bclock.ClockDriftGuard(limits=tl.test_only_drift_limits())
    guard.record(_good())
    age = timedelta(seconds=tl.TEST_ONLY_MAX_MEASUREMENT_AGE_SECONDS)
    assert guard.entries_allowed(T0 + age) is True
    later = T0 + age + timedelta(microseconds=1)
    assert guard.entries_allowed(later) is False
    assert guard.blocked_reason(later) is bclock.DriftBlockReason.STALE


def test_guard_now_before_the_measurement_is_stale() -> None:
    guard = bclock.ClockDriftGuard(limits=tl.test_only_drift_limits())
    guard.record(_good())
    assert guard.blocked_reason(T0 - timedelta(seconds=1)) is bclock.DriftBlockReason.STALE


def test_guard_allows_only_a_fresh_in_limit_verdict() -> None:
    guard = bclock.ClockDriftGuard(limits=tl.test_only_drift_limits())
    guard.record(_good())
    assert guard.entries_allowed(T0 + timedelta(seconds=1)) is True
    assert guard.blocked_reason(T0 + timedelta(seconds=1)) is None


def test_guard_block_reason_values() -> None:
    assert {reason.value for reason in bclock.DriftBlockReason} == {
        "NEVER_MEASURED",
        "MEASUREMENT_FAILED",
        "OUT_OF_LIMITS",
        "STALE",
    }


def test_guard_requires_drift_limits_and_aware_now() -> None:
    with pytest.raises(TypeError):
        bclock.ClockDriftGuard()  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="limits"):
        bclock.ClockDriftGuard(limits=tl.test_only_stream_limits())  # type: ignore[arg-type]
    guard = bclock.ClockDriftGuard(limits=tl.test_only_drift_limits())
    with pytest.raises(ValueError, match="now_utc"):
        guard.entries_allowed(datetime(2026, 1, 1))  # noqa: DTZ001 - the naive value under test


def test_guard_record_refuses_a_verdict_without_a_measurement_time() -> None:
    guard = bclock.ClockDriftGuard(limits=tl.test_only_drift_limits())
    timeless = bclock.evaluate_clock_drift(
        before_ms=1, server_ms=1, after_ms=1, limits=tl.test_only_drift_limits()
    )
    with pytest.raises(ValueError, match="measured_at_utc"):
        guard.record(timeless)
    with pytest.raises(TypeError):
        guard.record(object())  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Source guards.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("module", [LIMITS_MODULE, CLOCK_MODULE])
def test_no_float_constructor_and_no_wall_clock_in_the_modules(module: Path) -> None:
    assert float_constructor_calls(module) == []
    assert wall_clock_calls(module) == []
