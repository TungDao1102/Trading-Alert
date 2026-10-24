"""The shared operator-evidence module (plan 18-16): exit codes, jsonable, the atomic scrubbed
evidence write, the typed confirmation phrase, the owner's order-limits files and sha256_lf.

Every value written to a limits file here is TEST_ONLY (never an owner-approved size), and every
"secret" is a synthetic string that was never a credential.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum, StrEnum
from pathlib import Path
from types import MappingProxyType

import pytest
from src.ops import operator_evidence as oe
from src.ops import redaction
from src.ops.redaction import REDACTED, Redactor

# Synthetic values, never credentials.
TEST_ONLY_SECRET_VALUE = "TestOnlySecretValueNotACredential0001"
TEST_ONLY_RUNTIME_SECRET = "TestOnlyRuntimeSecretNotACredential002"

TEST_ONLY_SMOKE_LIMITS = """
[order]
symbol = "BTCUSDT"
quantity = "0.002"
far_price_fraction = "0.96"

[waits]
event_wait_seconds = 30
cleanup_timeout_seconds = 60
"""

TEST_ONLY_PROBE_LIMITS = """
[order]
symbol = "BTCUSDT"
quantity = "0.002"
max_notional_quote = "150"
far_price_fraction = "0.96"

[waits]
case_timeout_seconds = 45
cleanup_timeout_seconds = 90

[optional_cases]
explicit_time_in_force = true
stream_gap = false
market_lot_size_out_of_range = false
"""


@pytest.fixture(autouse=True)
def _isolated_runtime_secrets() -> Iterator[None]:
    redaction.clear_runtime_secrets()
    yield
    redaction.clear_runtime_secrets()


def _write(tmp_path: Path, text: str, name: str = "limits.toml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Exit codes and jsonable.
# --------------------------------------------------------------------------- #


def test_exit_codes_follow_the_operator_tool_convention() -> None:
    assert (oe.EXIT_OK, oe.EXIT_FAILED, oe.EXIT_REFUSED, oe.EXIT_ABORTED) == (0, 1, 2, 3)


class _Colour(StrEnum):
    RED = "RED"


class _Plain(Enum):
    ONE = 1


@dataclasses.dataclass(frozen=True)
class _Row:
    price: Decimal
    at: datetime
    colour: _Colour


def test_jsonable_converts_every_supported_type() -> None:
    plus_seven = timezone(timedelta(hours=7))
    value = {
        "price": Decimal("60000.10"),
        "tiny": Decimal("1E-8"),
        "at": datetime(2026, 10, 16, 19, 0, tzinfo=plus_seven),
        "enum": _Colour.RED,
        "plain_enum": _Plain.ONE,
        "row": _Row(Decimal("1.5"), datetime(2026, 10, 16, tzinfo=UTC), _Colour.RED),
        "seq": (1, "a", None, True),
        "mapping": MappingProxyType({"k": Decimal("2")}),
    }
    out = oe.jsonable(value)
    assert out == {
        "price": "60000.10",
        "tiny": "0.00000001",
        "at": "2026-10-16T12:00:00+00:00",
        "enum": "RED",
        "plain_enum": 1,
        "row": {"price": "1.5", "at": "2026-10-16T00:00:00+00:00", "colour": "RED"},
        "seq": [1, "a", None, True],
        "mapping": {"k": "2"},
    }
    json.dumps(out)


@pytest.mark.parametrize(
    "bad",
    [1.5, datetime(2026, 10, 16), object(), b"bytes", {1, 2}],
    ids=["float", "naive-datetime", "object", "bytes", "set"],
)
def test_jsonable_refuses_float_naive_time_and_unknown_types(bad: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        oe.jsonable({"value": bad})


# --------------------------------------------------------------------------- #
# write_evidence_atomic.
# --------------------------------------------------------------------------- #


def test_write_is_sorted_ascii_lf_and_returns_the_new_path(tmp_path: Path) -> None:
    document = {"b": "é", "a": Decimal("1.0"), "nested": {"z": 1, "y": [2, 3]}}
    path = oe.write_evidence_atomic(tmp_path / "out", "stem", document, Redactor(None))
    assert path == tmp_path / "out" / "stem.json"
    raw = path.read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"\n")
    text = raw.decode("ascii")
    assert text.index('"a"') < text.index('"b"') < text.index('"nested"')
    assert json.loads(text) == {"a": "1.0", "b": "é", "nested": {"y": [2, 3], "z": 1}}
    assert [p.name for p in (tmp_path / "out").iterdir()] == ["stem.json"], "no temp file left"


def test_a_secret_planted_in_the_document_is_scrubbed_before_the_write(tmp_path: Path) -> None:
    redactor = Redactor.from_environ({"SOME_API_SECRET": TEST_ONLY_SECRET_VALUE})
    document = {"error": f"failed with {TEST_ONLY_SECRET_VALUE}", "url": "x?signature=" + "a" * 64}
    path = oe.write_evidence_atomic(tmp_path, "stem", document, redactor)
    text = path.read_text(encoding="utf-8")
    assert TEST_ONLY_SECRET_VALUE not in text
    assert "a" * 64 not in text
    assert REDACTED in text


def test_a_runtime_registered_secret_is_scrubbed_too(tmp_path: Path) -> None:
    redaction.register_runtime_secret(TEST_ONLY_RUNTIME_SECRET)
    path = oe.write_evidence_atomic(
        tmp_path, "stem", {"note": f"key {TEST_ONLY_RUNTIME_SECRET}"}, Redactor(None)
    )
    assert TEST_ONLY_RUNTIME_SECRET not in path.read_text(encoding="utf-8")


class _NonIdempotentRedactor:
    """A scrubber that cannot clean its own output: the post-write scan must catch it."""

    def scrub(self, text: str) -> str:
        return text.replace("needle", "needle!")


def test_a_document_the_scrubber_cannot_clean_is_deleted_and_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="post-write secret scan"):
        oe.write_evidence_atomic(tmp_path, "stem", {"v": "needle"}, _NonIdempotentRedactor())
    assert list(tmp_path.iterdir()) == []


def test_the_write_never_overwrites_an_existing_file(tmp_path: Path) -> None:
    first = oe.write_evidence_atomic(tmp_path, "stem", {"n": 1}, Redactor(None))
    second = oe.write_evidence_atomic(tmp_path, "stem", {"n": 2}, Redactor(None))
    third = oe.write_evidence_atomic(tmp_path, "stem", {"n": 3}, Redactor(None))
    assert [first.name, second.name, third.name] == ["stem.json", "stem-2.json", "stem-3.json"]
    assert json.loads(first.read_text(encoding="utf-8")) == {"n": 1}


@pytest.mark.parametrize("stem", ["", "../escape", "a/b", "a\\b", "."])
def test_the_stem_must_be_a_plain_file_name(tmp_path: Path, stem: str) -> None:
    with pytest.raises(ValueError):
        oe.write_evidence_atomic(tmp_path, stem, {"n": 1}, Redactor(None))


# --------------------------------------------------------------------------- #
# confirm_execute.
# --------------------------------------------------------------------------- #

PHRASE = "DEMO SMOKE BTCUSDT"


def test_confirm_execute_accepts_only_the_exact_phrase_on_a_terminal() -> None:
    prompts: list[str] = []

    def reader(prompt: str) -> str:
        prompts.append(prompt)
        return PHRASE

    oe.confirm_execute(PHRASE, lambda: True, reader)
    assert len(prompts) == 1 and PHRASE in prompts[0]


def test_confirm_execute_refuses_without_a_terminal_and_never_prompts() -> None:
    def reader(prompt: str) -> str:
        raise AssertionError("must not prompt without a terminal")

    with pytest.raises(oe.ConfirmationRefused, match="interactive terminal"):
        oe.confirm_execute(PHRASE, lambda: False, reader)


@pytest.mark.parametrize(
    "typed", ["", "demo smoke btcusdt", "DEMO SMOKE BTCUSDT ", " DEMO SMOKE BTCUSDT", "DEMO SMOKE"]
)
def test_confirm_execute_refuses_a_wrong_phrase(typed: str) -> None:
    with pytest.raises(oe.ConfirmationRefused, match="did not match"):
        oe.confirm_execute(PHRASE, lambda: True, lambda _prompt: typed)


@pytest.mark.parametrize("error", [EOFError, OSError])
def test_confirm_execute_refuses_on_eof_or_a_closed_input(error: type[Exception]) -> None:
    def reader(prompt: str) -> str:
        raise error()

    with pytest.raises(oe.ConfirmationRefused, match="no confirmation"):
        oe.confirm_execute(PHRASE, lambda: True, reader)


# --------------------------------------------------------------------------- #
# sha256_lf.
# --------------------------------------------------------------------------- #


def test_sha256_lf_is_line_ending_independent(tmp_path: Path) -> None:
    lf = tmp_path / "lf.txt"
    crlf = tmp_path / "crlf.txt"
    lf.write_bytes(b"a = 1\nb = 2\n")
    crlf.write_bytes(b"a = 1\r\nb = 2\r\n")
    expected = hashlib.sha256(b"a = 1\nb = 2\n").hexdigest()
    assert oe.sha256_lf(lf) == expected
    assert oe.sha256_lf(crlf) == expected


# --------------------------------------------------------------------------- #
# load_demo_order_limits: smoke kind.
# --------------------------------------------------------------------------- #


def test_the_smoke_kind_loads_every_value_with_decimal_strings(tmp_path: Path) -> None:
    limits = oe.load_demo_order_limits(_write(tmp_path, TEST_ONLY_SMOKE_LIMITS), kind="smoke")
    assert limits == oe.DemoOrderLimits(
        kind="smoke",
        symbol="BTCUSDT",
        quantity=Decimal("0.002"),
        far_price_fraction=Decimal("0.96"),
        max_notional_quote=None,
        market_lot_probe_quantity=None,
        event_wait_seconds=30,
        case_timeout_seconds=None,
        cleanup_timeout_seconds=60,
        optional_cases=MappingProxyType({}),
        near_trigger_fraction=None,
        gtd_lifetime_seconds=None,
        gtd_expiry_wait_seconds=None,
        race_repeats=None,
        insufficient_margin_quantity=None,
        config_target_leverage=None,  # Phase 22 plan 22-05
    )
    assert limits.enabled_optional_cases == ()


def test_demo_order_limits_has_no_default_value() -> None:
    for item in dataclasses.fields(oe.DemoOrderLimits):
        assert item.default is dataclasses.MISSING, item.name
        assert item.default_factory is dataclasses.MISSING, item.name
    with pytest.raises(TypeError):
        oe.DemoOrderLimits()  # type: ignore[call-arg]


def _smoke_variant(old: str, new: str) -> str:
    assert old in TEST_ONLY_SMOKE_LIMITS
    return TEST_ONLY_SMOKE_LIMITS.replace(old, new)


SMOKE_REFUSALS = {
    "missing-symbol": _smoke_variant('symbol = "BTCUSDT"\n', ""),
    "missing-quantity": _smoke_variant('quantity = "0.002"\n', ""),
    "missing-wait": _smoke_variant("event_wait_seconds = 30\n", ""),
    "missing-section": _smoke_variant(
        "[waits]\nevent_wait_seconds = 30\ncleanup_timeout_seconds = 60\n", ""
    ),
    "unknown-key": _smoke_variant('symbol = "BTCUSDT"\n', 'symbol = "BTCUSDT"\nside = "BUY"\n'),
    "unknown-section": TEST_ONLY_SMOKE_LIMITS + "\n[extra]\nx = 1\n",
    "probe-key-in-smoke": _smoke_variant(
        'symbol = "BTCUSDT"\n', 'symbol = "BTCUSDT"\nmax_notional_quote = "150"\n'
    ),
    "quantity-float": _smoke_variant('quantity = "0.002"', "quantity = 0.002"),
    "quantity-int": _smoke_variant('quantity = "0.002"', "quantity = 1"),
    "quantity-exponent": _smoke_variant('quantity = "0.002"', 'quantity = "2E-3"'),
    "quantity-zero": _smoke_variant('quantity = "0.002"', 'quantity = "0"'),
    "quantity-negative": _smoke_variant('quantity = "0.002"', 'quantity = "-0.002"'),
    "quantity-text": _smoke_variant('quantity = "0.002"', 'quantity = "abc"'),
    "fraction-zero": _smoke_variant('far_price_fraction = "0.96"', 'far_price_fraction = "0"'),
    "fraction-one": _smoke_variant('far_price_fraction = "0.96"', 'far_price_fraction = "1"'),
    "fraction-above-one": _smoke_variant(
        'far_price_fraction = "0.96"', 'far_price_fraction = "1.5"'
    ),
    "symbol-lower": _smoke_variant('symbol = "BTCUSDT"', 'symbol = "btcusdt"'),
    "symbol-not-text": _smoke_variant('symbol = "BTCUSDT"', "symbol = 5"),
    "wait-zero": _smoke_variant("event_wait_seconds = 30", "event_wait_seconds = 0"),
    "wait-bool": _smoke_variant("event_wait_seconds = 30", "event_wait_seconds = true"),
    "wait-string": _smoke_variant("event_wait_seconds = 30", 'event_wait_seconds = "30"'),
    "wait-float": _smoke_variant("cleanup_timeout_seconds = 60", "cleanup_timeout_seconds = 6.5"),
    "not-toml": "this is [not toml",
}


@pytest.mark.parametrize("text", list(SMOKE_REFUSALS.values()), ids=list(SMOKE_REFUSALS))
def test_the_smoke_kind_refuses_every_missing_unknown_or_malformed_key(
    tmp_path: Path, text: str
) -> None:
    with pytest.raises(oe.DemoOrderLimitsRefused) as info:
        oe.load_demo_order_limits(_write(tmp_path, text), kind="smoke")
    # Problems name keys or sections, never a value.
    assert "0.002" not in str(info.value)


def test_a_missing_limits_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(oe.DemoOrderLimitsRefused):
        oe.load_demo_order_limits(tmp_path / "absent.toml", kind="smoke")


def test_an_unknown_kind_is_a_value_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        oe.load_demo_order_limits(_write(tmp_path, TEST_ONLY_SMOKE_LIMITS), kind="other")


# --------------------------------------------------------------------------- #
# load_demo_order_limits: probe kind (consumed by plans 18-17 and 18-23).
# --------------------------------------------------------------------------- #


def test_the_probe_kind_loads_every_value(tmp_path: Path) -> None:
    limits = oe.load_demo_order_limits(_write(tmp_path, TEST_ONLY_PROBE_LIMITS), kind="probe")
    assert limits.kind == "probe"
    assert limits.symbol == "BTCUSDT"
    assert limits.quantity == Decimal("0.002")
    assert limits.max_notional_quote == Decimal("150")
    assert limits.far_price_fraction == Decimal("0.96")
    assert limits.market_lot_probe_quantity is None
    assert limits.case_timeout_seconds == 45
    assert limits.cleanup_timeout_seconds == 90
    assert limits.event_wait_seconds is None
    assert dict(limits.optional_cases) == {
        "explicit_time_in_force": True,
        "stream_gap": False,
        "market_lot_size_out_of_range": False,
    }
    assert limits.enabled_optional_cases == ("explicit_time_in_force",)


def test_the_market_lot_probe_quantity_comes_with_its_optional_case(tmp_path: Path) -> None:
    text = TEST_ONLY_PROBE_LIMITS.replace(
        "market_lot_size_out_of_range = false", "market_lot_size_out_of_range = true"
    ).replace('symbol = "BTCUSDT"\n', 'symbol = "BTCUSDT"\nmarket_lot_probe_quantity = "150"\n')
    limits = oe.load_demo_order_limits(_write(tmp_path, text), kind="probe")
    assert limits.market_lot_probe_quantity == Decimal("150")
    assert "market_lot_size_out_of_range" in limits.enabled_optional_cases


def _probe_variant(old: str, new: str) -> str:
    assert old in TEST_ONLY_PROBE_LIMITS
    return TEST_ONLY_PROBE_LIMITS.replace(old, new)


PROBE_REFUSALS = {
    "missing-cap": _probe_variant('max_notional_quote = "150"\n', ""),
    "cap-zero": _probe_variant('max_notional_quote = "150"', 'max_notional_quote = "0"'),
    "cap-float": _probe_variant('max_notional_quote = "150"', "max_notional_quote = 150.0"),
    "missing-case-timeout": _probe_variant("case_timeout_seconds = 45\n", ""),
    "smoke-wait-in-probe": _probe_variant(
        "case_timeout_seconds = 45\n", "case_timeout_seconds = 45\nevent_wait_seconds = 30\n"
    ),
    "missing-optional-section": _probe_variant(
        "[optional_cases]\nexplicit_time_in_force = true\nstream_gap = false\n"
        "market_lot_size_out_of_range = false\n",
        "",
    ),
    "missing-optional-key": _probe_variant("stream_gap = false\n", ""),
    "unknown-optional-key": _probe_variant(
        "stream_gap = false\n", "stream_gap = false\nmystery = true\n"
    ),
    "optional-not-bool": _probe_variant("stream_gap = false", 'stream_gap = "false"'),
    "lot-quantity-without-case": _probe_variant(
        'symbol = "BTCUSDT"\n', 'symbol = "BTCUSDT"\nmarket_lot_probe_quantity = "150"\n'
    ),
    "case-without-lot-quantity": _probe_variant(
        "market_lot_size_out_of_range = false", "market_lot_size_out_of_range = true"
    ),
    "fraction-one": _probe_variant('far_price_fraction = "0.96"', 'far_price_fraction = "1.0"'),
    "quantity-negative": _probe_variant('quantity = "0.002"', 'quantity = "-1"'),
}


@pytest.mark.parametrize("text", list(PROBE_REFUSALS.values()), ids=list(PROBE_REFUSALS))
def test_the_probe_kind_refuses_every_missing_unknown_or_malformed_key(
    tmp_path: Path, text: str
) -> None:
    with pytest.raises(oe.DemoOrderLimitsRefused):
        oe.load_demo_order_limits(_write(tmp_path, text), kind="probe")


# --------------------------------------------------------------------------- #
# Quick task 261021-sj0: the ten owner opt-in evidence cases.
# --------------------------------------------------------------------------- #

PHASE18_PROBE_LIMITS = (
    Path(__file__).resolve().parents[1]
    / ".planning/phases/18-user-data-stream-error-taxonomy/decisions/18-probe-limits.toml"
)
NEW_KEYS = (
    "account_capture",
    "algo_query_timing",
    "close_position_with_position",
    "stop_trigger_after_fill",
    "stop_absent_same_id",
    "manual_close_open_legs",
    "commission_realized_pnl",
    "triggered_bracket",
    "tp1_from_fill",
    "gtd_expiry",
)


def _with_new_keys(*pairs: tuple[str, str]) -> str:
    """The TEST_ONLY probe file with `key = value` lines added to [optional_cases]."""
    return TEST_ONLY_PROBE_LIMITS + "".join(f"{key} = {value}\n" for key, value in pairs)


# Quick task 261022-sj1: five more keys, inserted before gtd_expiry (the only long case).
SJ1_KEYS = (
    "exchange_info_read",
    "gtd_min_lifetime",
    "partial_fill_attempt",
    "cancel_fill_race",
    "stream_loss",
)


# Quick task 261023-sj2: eight more keys, inserted before gtd_expiry (the only long case).
SJ2_KEYS = (
    "reduce_only_flat",
    "reduce_only_oversize",
    "min_notional_entry",
    "insufficient_margin",
    "stop_reject_after_accept",
    "trigger_cancel_race",
    "recv_window_error",
    "income_history",
)


# Phase 22 plans 22-05 and 22-09: the owner-run symbol-configuration keys, before gtd_expiry.
SJ3_KEYS = ("symbol_config_change", "available_balance_resting")


def test_the_evidence_case_keys_are_the_ten_the_five_and_the_eight_in_script_order() -> None:
    assert oe.EVIDENCE_CASE_KEYS == (
        *NEW_KEYS[:9],
        *SJ1_KEYS,
        *SJ2_KEYS,
        *SJ3_KEYS,  # Phase 22 plan 22-05
        NEW_KEYS[9],
    )
    assert oe.EVIDENCE_CASE_KEYS[-2] == SJ3_KEYS[-1]  # right before the long case
    assert oe.EVIDENCE_CASE_KEYS[-1] == "gtd_expiry"  # the case that waits runs last
    assert "EVIDENCE_CASE_KEYS" in oe.__all__
    assert not set(oe.EVIDENCE_CASE_KEYS) & set(oe.OPTIONAL_CASE_KEYS)


def test_the_real_phase18_probe_file_loads_to_the_unchanged_values() -> None:
    limits = oe.load_demo_order_limits(PHASE18_PROBE_LIMITS, kind="probe")
    assert limits.enabled_optional_cases == ()
    assert dict(limits.optional_cases) == {
        "explicit_time_in_force": False,
        "stream_gap": False,
        "market_lot_size_out_of_range": False,
    }
    assert limits.symbol == "BTCUSDT"
    assert limits.quantity == Decimal("0.0008")
    assert limits.max_notional_quote == Decimal("100")
    assert limits.far_price_fraction == Decimal("0.96")
    assert limits.case_timeout_seconds == 30
    assert limits.cleanup_timeout_seconds == 60
    assert limits.near_trigger_fraction is None
    assert limits.gtd_lifetime_seconds is None
    assert limits.gtd_expiry_wait_seconds is None


def test_an_evidence_key_enables_its_case_and_follows_the_phase18_keys(tmp_path: Path) -> None:
    text = _with_new_keys(("account_capture", "true"), ("algo_query_timing", "false"))
    text = text.replace("stream_gap = false", "stream_gap = true")
    limits = oe.load_demo_order_limits(_write(tmp_path, text), kind="probe")
    assert limits.optional_cases["account_capture"] is True
    assert limits.optional_cases["algo_query_timing"] is False
    assert "close_position_with_position" not in limits.optional_cases  # absent: not stored
    assert limits.enabled_optional_cases == (
        "explicit_time_in_force",
        "stream_gap",
        "account_capture",
    )


def test_a_non_bool_evidence_key_is_refused_by_name(tmp_path: Path) -> None:
    with pytest.raises(oe.DemoOrderLimitsRefused) as info:
        oe.load_demo_order_limits(
            _write(tmp_path, _with_new_keys(("account_capture", '"true"'))), kind="probe"
        )
    assert "optional_cases.account_capture" in str(info.value)
    assert "true" not in str(info.value).replace("must be true or false", "")


def test_an_unknown_key_in_optional_cases_is_still_refused(tmp_path: Path) -> None:
    with pytest.raises(oe.DemoOrderLimitsRefused) as info:
        oe.load_demo_order_limits(
            _write(tmp_path, _with_new_keys(("mystery_capture", "true"))), kind="probe"
        )
    assert "optional_cases.mystery_capture (unknown key)" in str(info.value)


_NEAR = 'near_trigger_fraction = "0.999"\n'


@pytest.mark.parametrize("key", ["triggered_bracket", "tp1_from_fill"])
def test_the_near_trigger_fraction_is_required_exactly_when_its_cases_are_on(
    tmp_path: Path, key: str
) -> None:
    on = _with_new_keys((key, "true")).replace(
        'symbol = "BTCUSDT"\n', 'symbol = "BTCUSDT"\n' + _NEAR
    )
    limits = oe.load_demo_order_limits(_write(tmp_path, on), kind="probe")
    assert limits.near_trigger_fraction == Decimal("0.999")
    with pytest.raises(oe.DemoOrderLimitsRefused) as missing:
        oe.load_demo_order_limits(_write(tmp_path, _with_new_keys((key, "true"))), kind="probe")
    assert "order.near_trigger_fraction (missing key" in str(missing.value)
    off = TEST_ONLY_PROBE_LIMITS.replace('symbol = "BTCUSDT"\n', 'symbol = "BTCUSDT"\n' + _NEAR)
    with pytest.raises(oe.DemoOrderLimitsRefused) as present:
        oe.load_demo_order_limits(_write(tmp_path, off), kind="probe")
    assert "order.near_trigger_fraction (only allowed when" in str(present.value)


@pytest.mark.parametrize(
    "value", ['"0"', '"1"', '"1.5"', '"-0.5"', "0.999", '"abc"', '"9E-1"', "1"]
)
def test_the_near_trigger_fraction_must_be_a_plain_decimal_strictly_between_0_and_1(
    tmp_path: Path, value: str
) -> None:
    text = _with_new_keys(("triggered_bracket", "true")).replace(
        'symbol = "BTCUSDT"\n', f'symbol = "BTCUSDT"\nnear_trigger_fraction = {value}\n'
    )
    with pytest.raises(oe.DemoOrderLimitsRefused) as info:
        oe.load_demo_order_limits(_write(tmp_path, text), kind="probe")
    assert "order.near_trigger_fraction" in str(info.value)


def _gtd_text(lifetime: str | None, wait: str | None, *, enabled: bool = True) -> str:
    text = _with_new_keys(("gtd_expiry", "true" if enabled else "false"))
    if lifetime is not None:
        text = text.replace(
            'symbol = "BTCUSDT"\n', f'symbol = "BTCUSDT"\ngtd_lifetime_seconds = {lifetime}\n'
        )
    if wait is not None:
        text = text.replace(
            "case_timeout_seconds = 45\n",
            f"case_timeout_seconds = 45\ngtd_expiry_wait_seconds = {wait}\n",
        )
    return text


def test_the_gtd_lifetime_and_wait_come_with_their_case(tmp_path: Path) -> None:
    limits = oe.load_demo_order_limits(_write(tmp_path, _gtd_text("660", "720")), kind="probe")
    assert limits.gtd_lifetime_seconds == 660
    assert limits.gtd_expiry_wait_seconds == 720
    assert "gtd_expiry" in limits.enabled_optional_cases


@pytest.mark.parametrize(
    ("lifetime", "wait", "enabled", "named"),
    [
        (None, "720", True, "order.gtd_lifetime_seconds"),
        ("660", None, True, "waits.gtd_expiry_wait_seconds"),
        ("660", "660", True, "waits.gtd_expiry_wait_seconds (must be greater"),
        ("660", "600", True, "waits.gtd_expiry_wait_seconds (must be greater"),
        ("0", "720", True, "order.gtd_lifetime_seconds (must be a positive integer)"),
        ("true", "720", True, "order.gtd_lifetime_seconds (must be a positive integer)"),
        ('"660"', "720", True, "order.gtd_lifetime_seconds (must be a positive integer)"),
        ("660", "7.5", True, "waits.gtd_expiry_wait_seconds (must be a positive integer)"),
        ("660", "720", False, "order.gtd_lifetime_seconds (only allowed when"),
        (None, "720", False, "waits.gtd_expiry_wait_seconds (only allowed when"),
    ],
)
def test_the_gtd_keys_are_refused_unless_valid_and_only_with_their_case(
    tmp_path: Path, lifetime: str | None, wait: str | None, enabled: bool, named: str
) -> None:
    with pytest.raises(oe.DemoOrderLimitsRefused) as info:
        oe.load_demo_order_limits(
            _write(tmp_path, _gtd_text(lifetime, wait, enabled=enabled)), kind="probe"
        )
    assert named in str(info.value)


def test_a_lifetime_below_the_exchange_floor_is_not_refused(tmp_path: Path) -> None:
    """The exchange's answer to a short lifetime is itself evidence (A1): no floor here."""
    limits = oe.load_demo_order_limits(_write(tmp_path, _gtd_text("30", "60")), kind="probe")
    assert limits.gtd_lifetime_seconds == 30


@pytest.mark.parametrize(
    "extra",
    [
        ("order", 'near_trigger_fraction = "0.999"\n'),
        ("order", "gtd_lifetime_seconds = 660\n"),
        ("waits", "gtd_expiry_wait_seconds = 720\n"),
        ("optional_cases", "account_capture = true\n"),
    ],
)
def test_the_smoke_kind_refuses_the_new_keys_as_unknown(
    tmp_path: Path, extra: tuple[str, str]
) -> None:
    section, line = extra
    text = TEST_ONLY_SMOKE_LIMITS.replace(f"[{section}]\n", f"[{section}]\n{line}", 1)
    if section == "optional_cases":
        text += f"\n[optional_cases]\n{line}"
    with pytest.raises(oe.DemoOrderLimitsRefused):
        oe.load_demo_order_limits(_write(tmp_path, text), kind="smoke")


def test_the_refusals_of_the_new_keys_never_carry_a_value(tmp_path: Path) -> None:
    text = _gtd_text("123456", "123457", enabled=False)
    with pytest.raises(oe.DemoOrderLimitsRefused) as info:
        oe.load_demo_order_limits(_write(tmp_path, text), kind="probe")
    assert "123456" not in str(info.value) and "123457" not in str(info.value)


def test_a_smoke_file_is_refused_as_a_probe_file_and_the_reverse(tmp_path: Path) -> None:
    with pytest.raises(oe.DemoOrderLimitsRefused):
        oe.load_demo_order_limits(_write(tmp_path, TEST_ONLY_SMOKE_LIMITS, "s.toml"), kind="probe")
    with pytest.raises(oe.DemoOrderLimitsRefused):
        oe.load_demo_order_limits(_write(tmp_path, TEST_ONLY_PROBE_LIMITS, "p.toml"), kind="smoke")


def test_the_refusal_names_the_problems_by_key(tmp_path: Path) -> None:
    with pytest.raises(oe.DemoOrderLimitsRefused) as info:
        oe.load_demo_order_limits(_write(tmp_path, SMOKE_REFUSALS["quantity-float"]), kind="smoke")
    assert "order.quantity" in str(info.value)
    assert info.value.problems


def test_the_module_imports_no_sdk_and_no_adapter() -> None:
    import ast

    source = Path(oe.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(name.startswith(("binance", "src.adapters", "src.paper")) for name in imported)
    assert {name for name in imported if name.startswith("src")} == {"src.ops.redaction"}


# --------------------------------------------------------------------------- #
# Quick task 261022-sj1: five more owner opt-in cases and the key race_repeats.
# --------------------------------------------------------------------------- #


def _race_text(repeats: str | None, *, enabled: bool = True) -> str:
    text = _with_new_keys(("cancel_fill_race", "true" if enabled else "false"))
    if repeats is not None:
        text = text.replace(
            'symbol = "BTCUSDT"\n', f'symbol = "BTCUSDT"\nrace_repeats = {repeats}\n'
        )
    return text


@pytest.mark.parametrize("key", SJ1_KEYS)
def test_each_sj1_key_enables_only_its_case(tmp_path: Path, key: str) -> None:
    text = _race_text("3") if key == "cancel_fill_race" else _with_new_keys((key, "true"))
    limits = oe.load_demo_order_limits(_write(tmp_path, text), kind="probe")
    assert [k for k in limits.enabled_optional_cases if k in oe.EVIDENCE_CASE_KEYS] == [key]
    off = oe.load_demo_order_limits(
        _write(tmp_path, _with_new_keys((key, "false")), "off.toml"), kind="probe"
    )
    assert not [k for k in off.enabled_optional_cases if k in oe.EVIDENCE_CASE_KEYS]
    assert off.race_repeats is None


def test_race_repeats_comes_with_its_case_and_is_a_small_positive_integer(tmp_path: Path) -> None:
    limits = oe.load_demo_order_limits(_write(tmp_path, _race_text("3")), kind="probe")
    assert limits.race_repeats == 3
    assert isinstance(oe.RACE_REPEATS_MAX, int) and 1 <= oe.RACE_REPEATS_MAX <= 10
    top = oe.load_demo_order_limits(
        _write(tmp_path, _race_text(str(oe.RACE_REPEATS_MAX)), "top.toml"), kind="probe"
    )
    assert top.race_repeats == oe.RACE_REPEATS_MAX


@pytest.mark.parametrize(
    ("repeats", "enabled", "named"),
    [
        (None, True, "order.race_repeats (missing key"),
        ("0", True, "order.race_repeats (must be a positive integer)"),
        ("-2", True, "order.race_repeats (must be a positive integer)"),
        ("true", True, "order.race_repeats (must be a positive integer)"),
        ('"3"', True, "order.race_repeats (must be a positive integer)"),
        ("2.5", True, "order.race_repeats (must be a positive integer)"),
        ("11", True, "order.race_repeats (must be at most"),
        ("1000000", True, "order.race_repeats (must be at most"),
        ("3", False, "order.race_repeats (only allowed when"),
    ],
)
def test_race_repeats_is_refused_unless_valid_and_only_with_its_case(
    tmp_path: Path, repeats: str | None, enabled: bool, named: str
) -> None:
    with pytest.raises(oe.DemoOrderLimitsRefused) as info:
        oe.load_demo_order_limits(
            _write(tmp_path, _race_text(repeats, enabled=enabled)), kind="probe"
        )
    assert named in str(info.value)


def test_the_race_repeats_refusal_never_carries_the_value(tmp_path: Path) -> None:
    with pytest.raises(oe.DemoOrderLimitsRefused) as info:
        oe.load_demo_order_limits(_write(tmp_path, _race_text("987654")), kind="probe")
    assert "987654" not in str(info.value)


def test_the_smoke_kind_refuses_race_repeats_and_the_sj1_case_keys(tmp_path: Path) -> None:
    lines = [("order", "race_repeats = 3\n")] + [
        ("optional_cases", f"{key} = true\n") for key in SJ1_KEYS
    ]
    for section, line in lines:
        text = TEST_ONLY_SMOKE_LIMITS.replace(f"[{section}]\n", f"[{section}]\n{line}", 1)
        if section == "optional_cases":
            text += f"\n[optional_cases]\n{line}"
        with pytest.raises(oe.DemoOrderLimitsRefused):
            oe.load_demo_order_limits(_write(tmp_path, text), kind="smoke")


def test_the_phase18_file_has_no_race_repeats() -> None:
    limits = oe.load_demo_order_limits(PHASE18_PROBE_LIMITS, kind="probe")
    assert limits.race_repeats is None


# --------------------------------------------------------------------------- #
# Quick task 261023-sj2: eight more owner opt-in cases and their keys.
# --------------------------------------------------------------------------- #

MARGIN_QUANTITY_LINE = 'insufficient_margin_quantity = "5"\n'
NEAR_LINE = 'near_trigger_fraction = "0.999"\n'
RACE_LINE = "race_repeats = 3\n"


def _sj2_text(*keys: str, extra_order: str = "") -> str:
    text = _with_new_keys(*((key, "true") for key in keys))
    if extra_order:
        text = text.replace('symbol = "BTCUSDT"\n', f'symbol = "BTCUSDT"\n{extra_order}', 1)
    return text


_SJ2_NEEDS: dict[str, str] = {
    "stop_reject_after_accept": NEAR_LINE,
    "trigger_cancel_race": NEAR_LINE + RACE_LINE,
    "insufficient_margin": MARGIN_QUANTITY_LINE,
}


@pytest.mark.parametrize("key", SJ2_KEYS)
def test_each_sj2_key_enables_only_its_case(tmp_path: Path, key: str) -> None:
    text = _sj2_text(key, extra_order=_SJ2_NEEDS.get(key, ""))
    limits = oe.load_demo_order_limits(_write(tmp_path, text), kind="probe")
    assert [k for k in limits.enabled_optional_cases if k in oe.EVIDENCE_CASE_KEYS] == [key]
    off = oe.load_demo_order_limits(
        _write(tmp_path, _with_new_keys((key, "false")), "off.toml"), kind="probe"
    )
    assert not [k for k in off.enabled_optional_cases if k in oe.EVIDENCE_CASE_KEYS]
    assert off.near_trigger_fraction is None
    assert off.race_repeats is None
    assert off.insufficient_margin_quantity is None


def test_the_near_trigger_fraction_serves_the_two_new_stop_cases(tmp_path: Path) -> None:
    for key in ("stop_reject_after_accept", "trigger_cancel_race"):
        extra = _SJ2_NEEDS[key]
        limits = oe.load_demo_order_limits(
            _write(tmp_path, _sj2_text(key, extra_order=extra), f"{key}.toml"), kind="probe"
        )
        assert limits.near_trigger_fraction == Decimal("0.999")
        with pytest.raises(oe.DemoOrderLimitsRefused) as info:
            oe.load_demo_order_limits(
                _write(
                    tmp_path,
                    _sj2_text(key, extra_order=extra.replace(NEAR_LINE, "")),
                    f"{key}-no.toml",
                ),
                kind="probe",
            )
        assert "order.near_trigger_fraction (missing key" in str(info.value)


def test_race_repeats_serves_either_race_case_and_is_refused_otherwise(tmp_path: Path) -> None:
    both = _sj2_text("cancel_fill_race", "trigger_cancel_race", extra_order=NEAR_LINE + RACE_LINE)
    limits = oe.load_demo_order_limits(_write(tmp_path, both), kind="probe")
    assert limits.race_repeats == 3
    missing = _sj2_text("trigger_cancel_race", extra_order=NEAR_LINE)
    with pytest.raises(oe.DemoOrderLimitsRefused) as info:
        oe.load_demo_order_limits(_write(tmp_path, missing, "n.toml"), kind="probe")
    assert "order.race_repeats (missing key" in str(info.value)
    assert "optional_cases.trigger_cancel_race" in str(info.value)
    toolong = _sj2_text("trigger_cancel_race", extra_order=NEAR_LINE + "race_repeats = 11\n")
    with pytest.raises(oe.DemoOrderLimitsRefused) as info2:
        oe.load_demo_order_limits(_write(tmp_path, toolong, "t.toml"), kind="probe")
    assert "order.race_repeats (must be at most" in str(info2.value)


def test_the_margin_quantity_is_the_owners_own_key_and_the_cap_is_unchanged(
    tmp_path: Path,
) -> None:
    text = _sj2_text("insufficient_margin", extra_order=MARGIN_QUANTITY_LINE)
    limits = oe.load_demo_order_limits(_write(tmp_path, text), kind="probe")
    assert limits.insufficient_margin_quantity == Decimal("5")
    assert limits.max_notional_quote == Decimal("150")
    assert limits.quantity == Decimal("0.002")


@pytest.mark.parametrize(
    ("line", "enabled", "named"),
    [
        ("", True, "order.insufficient_margin_quantity (missing key"),
        (
            'insufficient_margin_quantity = "<OWNER: whole quantity>"\n',
            True,
            "order.insufficient_margin_quantity (must be a plain decimal string)",
        ),
        (
            'insufficient_margin_quantity = "0"\n',
            True,
            "order.insufficient_margin_quantity (must be positive)",
        ),
        (
            'insufficient_margin_quantity = "-3"\n',
            True,
            "order.insufficient_margin_quantity (must be positive)",
        ),
        (
            "insufficient_margin_quantity = 5\n",
            True,
            "order.insufficient_margin_quantity (must be a plain decimal string)",
        ),
        (
            'insufficient_margin_quantity = "5"\n',
            False,
            "order.insufficient_margin_quantity (only allowed when",
        ),
    ],
)
def test_the_margin_quantity_is_refused_unless_a_positive_decimal_and_only_with_its_case(
    tmp_path: Path, line: str, enabled: bool, named: str
) -> None:
    text = _with_new_keys(("insufficient_margin", "true" if enabled else "false")).replace(
        'symbol = "BTCUSDT"\n', f'symbol = "BTCUSDT"\n{line}', 1
    )
    with pytest.raises(oe.DemoOrderLimitsRefused) as info:
        oe.load_demo_order_limits(_write(tmp_path, text), kind="probe")
    assert named in str(info.value)
    assert "OWNER" not in str(info.value)  # a refusal names keys, never a value


def test_the_smoke_kind_refuses_the_sj2_case_keys_and_the_margin_quantity(tmp_path: Path) -> None:
    for key in SJ2_KEYS:
        text = TEST_ONLY_SMOKE_LIMITS + f"\n[optional_cases]\n{key} = true\n"
        with pytest.raises(oe.DemoOrderLimitsRefused):
            oe.load_demo_order_limits(_write(tmp_path, text), kind="smoke")
    text = TEST_ONLY_SMOKE_LIMITS.replace(
        "[order]\n", '[order]\ninsufficient_margin_quantity = "5"\n', 1
    )
    with pytest.raises(oe.DemoOrderLimitsRefused):
        oe.load_demo_order_limits(_write(tmp_path, text, "m.toml"), kind="smoke")


def test_the_phase18_file_has_no_margin_quantity() -> None:
    limits = oe.load_demo_order_limits(PHASE18_PROBE_LIMITS, kind="probe")
    assert limits.insufficient_margin_quantity is None


# --------------------------------------------------------------------------- #
# Phase 22 plan 22-05: symbol_config_change and order.config_target_leverage.
# --------------------------------------------------------------------------- #

CONFIG_LEVERAGE_LINE = "config_target_leverage = 5\n"


def _config_text(*, enabled: bool | None, line: str) -> str:
    """The TEST_ONLY probe file with the flag (None: absent) and one `[order]` line."""
    text = TEST_ONLY_PROBE_LIMITS
    if enabled is not None:
        text = _with_new_keys(("symbol_config_change", "true" if enabled else "false"))
    return text.replace('symbol = "BTCUSDT"\n', f'symbol = "BTCUSDT"\n{line}', 1)


def test_the_owner_leverage_is_loaded_exactly_when_the_flag_is_on(tmp_path: Path) -> None:
    on = oe.load_demo_order_limits(
        _write(tmp_path, _config_text(enabled=True, line=CONFIG_LEVERAGE_LINE)), kind="probe"
    )
    assert on.config_target_leverage == 5 and type(on.config_target_leverage) is int
    assert "symbol_config_change" in on.enabled_optional_cases
    off = oe.load_demo_order_limits(
        _write(tmp_path, _config_text(enabled=False, line=""), "off.toml"), kind="probe"
    )
    assert off.config_target_leverage is None
    assert "symbol_config_change" not in off.enabled_optional_cases
    absent = oe.load_demo_order_limits(
        _write(tmp_path, _config_text(enabled=None, line=""), "absent.toml"), kind="probe"
    )
    assert absent.config_target_leverage is None


_POSITIVE = "order.config_target_leverage (must be a positive integer)"


@pytest.mark.parametrize(
    ("line", "enabled", "named"),
    [
        ("", True, "order.config_target_leverage (missing key"),
        ("config_target_leverage = 0\n", True, _POSITIVE),
        ("config_target_leverage = -5\n", True, _POSITIVE),
        ("config_target_leverage = true\n", True, _POSITIVE),
        ("config_target_leverage = 5.0\n", True, _POSITIVE),
        ('config_target_leverage = "5"\n', True, _POSITIVE),
        ("config_target_leverage = 5\n", False, "order.config_target_leverage (only allowed when"),
        ("config_target_leverage = 5\n", None, "order.config_target_leverage (only allowed when"),
    ],
)
def test_the_owner_leverage_is_refused_unless_a_positive_int_and_only_with_its_flag(
    tmp_path: Path, line: str, enabled: bool | None, named: str
) -> None:
    text = _config_text(enabled=enabled, line=line)
    with pytest.raises(oe.DemoOrderLimitsRefused) as info:
        oe.load_demo_order_limits(_write(tmp_path, text), kind="probe")
    assert named in str(info.value)


def test_an_owner_placeholder_for_the_leverage_is_refused_without_echoing_it(
    tmp_path: Path,
) -> None:
    text = _config_text(enabled=True, line="config_target_leverage = <OWNER: a whole number>\n")
    with pytest.raises(oe.DemoOrderLimitsRefused) as info:
        oe.load_demo_order_limits(_write(tmp_path, text), kind="probe")
    assert "OWNER" not in str(info.value)  # a refusal names keys, never a value


def test_the_smoke_kind_refuses_the_leverage_key_and_the_config_flag(tmp_path: Path) -> None:
    text = TEST_ONLY_SMOKE_LIMITS.replace("[order]\n", "[order]\nconfig_target_leverage = 5\n", 1)
    with pytest.raises(oe.DemoOrderLimitsRefused):
        oe.load_demo_order_limits(_write(tmp_path, text), kind="smoke")
    flag = TEST_ONLY_SMOKE_LIMITS + "\n[optional_cases]\nsymbol_config_change = true\n"
    with pytest.raises(oe.DemoOrderLimitsRefused):
        oe.load_demo_order_limits(_write(tmp_path, flag, "f.toml"), kind="smoke")


def test_the_phase18_file_has_no_config_target_leverage() -> None:
    limits = oe.load_demo_order_limits(PHASE18_PROBE_LIMITS, kind="probe")
    assert limits.config_target_leverage is None
