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
