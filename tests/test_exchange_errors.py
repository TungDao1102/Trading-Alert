"""Exchange error taxonomy: classification by (class, code, call kind) only (plan 18-05).

The code table is documentation text read per docs/SOURCES.md section "Facts
read for Phase 18" (WebFetch summaries, not verified live); -4509 is
Demo-observed only. Nothing here reads exception message text (D-10).
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from binance_common.configuration import ConfigurationRestAPI
from binance_common.utils import send_request
from src.adapters.binance_errors import error_facts_from_exception
from src.domain.exchange_errors import (
    DEMO_SMOKE_DATE,
    ERROR_CODE_TABLE,
    ERROR_TABLE_READ_DATE,
    ERROR_TABLE_REREAD_DATE,
    ERROR_TABLE_SOURCE,
    EVIDENCE_LABELS,
    CallKind,
    ErrorFacts,
    ExchangeErrorCategory,
    HttpClass,
    RateLimitDecision,
    classify,
    rate_limit_decision,
    retry_eligible,
    safe_mode_eligible,
)

from tests.support.ast_guards import (
    float_constructor_calls,
    forbidden_imports,
    module_imports,
    wall_clock_calls,
)

ROOT = Path(__file__).resolve().parents[1]
TAXONOMY = ROOT / "src" / "domain" / "exchange_errors.py"
NORMALIZER = ROOT / "src" / "adapters" / "binance_errors.py"


class _Response:
    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self.headers = {"Content-Type": "application/json"}
        self.text = json.dumps(body)

    def json(self) -> Any:
        return json.loads(self.text)


class _Session:
    def __init__(self, response: _Response) -> None:
        self._response = response

    def request(self, **_: Any) -> _Response:
        return self._response


def _sdk_error(status: int, body: dict[str, Any]) -> BaseException:
    """An exception raised by the installed `send_request` for a stubbed answer."""
    config = ConfigurationRestAPI(
        api_key="TEST_ONLY_KEY",
        api_secret="TEST_ONLY_SECRET",
        base_path="https://example.invalid",
        retries=0,
        timeout=1000,
    )
    with pytest.raises(Exception) as info:
        send_request(
            _Session(_Response(status, body)),  # type: ignore[arg-type]
            config,
            method="GET",
            path="/fapi/v1/order",
            payload={"symbol": "BTCUSDT"},
            is_signed=False,
        )
    return info.value


# --------------------------------------------------------------------------- #
# Task 1 tracer
# --------------------------------------------------------------------------- #


def test_sdk_2013_on_query_is_order_absent() -> None:
    exc = _sdk_error(400, {"code": -2013, "msg": "Order does not exist."})
    facts = error_facts_from_exception(exc)
    assert facts == ErrorFacts(HttpClass.BAD_REQUEST, -2013, None)
    assert classify(facts, CallKind.QUERY) is ExchangeErrorCategory.ORDER_ABSENT


def test_sdk_2013_on_placement_is_unknown_exchange_error() -> None:
    exc = _sdk_error(400, {"code": -2013, "msg": "Order does not exist."})
    facts = error_facts_from_exception(exc)
    assert classify(facts, CallKind.PLACEMENT) is ExchangeErrorCategory.UNKNOWN_EXCHANGE_ERROR


def test_runtime_error_with_code_text_is_never_read() -> None:
    facts = error_facts_from_exception(RuntimeError("-2013 NO_SUCH_ORDER"))
    assert facts == ErrorFacts(HttpClass.NON_SDK, None, None)
    for kind in CallKind:
        assert classify(facts, kind) is ExchangeErrorCategory.UNKNOWN_EXCHANGE_ERROR


def test_taxonomy_is_pure_stdlib_no_float_no_clock() -> None:
    imports = module_imports(TAXONOMY)
    non_stdlib = [
        name
        for name in imports
        if name.split(".")[0] not in sys.stdlib_module_names and name != "__future__"
    ]
    assert non_stdlib == []
    assert forbidden_imports(TAXONOMY, ("binance*", "requests", "aiohttp", "src", "tests")) == []
    assert float_constructor_calls(TAXONOMY) == []
    assert wall_clock_calls(TAXONOMY) == []


def test_normalizer_never_reads_message_text() -> None:
    """`str(exc)`, `exc.args`, `error_message` and `repr` never appear in the normalizer."""
    tree = ast.parse(NORMALIZER.read_text(encoding="utf-8"))
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"args", "error_message", "msg"}:
            offenders.append((node.lineno, node.attr))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"str", "repr", "format"}
        ):
            offenders.append((node.lineno, node.func.id))
        if isinstance(node, ast.JoinedStr):
            offenders.append((node.lineno, "f-string"))
        if isinstance(node, ast.Constant) and node.value in {"error_message", "args", "msg"}:
            offenders.append((node.lineno, f"constant {node.value!r}"))
    assert offenders == []


# --------------------------------------------------------------------------- #
# Task 2: the code table
# --------------------------------------------------------------------------- #

_C = ExchangeErrorCategory
_K = CallKind
_ALL = tuple(CallKind)
_PLACEMENT = (_K.PLACEMENT,)

# The expected category per call kind for every required code (plan 18-05
# Task 2 behavior block). A call kind not listed is UNKNOWN_EXCHANGE_ERROR.
_EXPECTED_BY_CODE: dict[int, tuple[ExchangeErrorCategory, tuple[CallKind, ...]]] = {
    -1003: (_C.RATE_LIMITED, _ALL),
    -1006: (_C.STATUS_UNKNOWN, _ALL),
    -1007: (_C.STATUS_UNKNOWN, _ALL),
    -1008: (_C.RATE_LIMITED, _ALL),
    -1015: (_C.RATE_LIMITED, _ALL),
    -1021: (_C.CLOCK_SKEW, _ALL),
    -1022: (_C.AUTH_OR_SIGNATURE, _ALL),
    -1111: (_C.REJECTED_DEFINITIVE, _PLACEMENT),
    -1121: (_C.REJECTED_DEFINITIVE, (_K.PLACEMENT, _K.CANCEL, _K.QUERY)),
    # Added on purpose: the owner decided on 2026-10-17 (plan 18-26, 18-DEC-TAXONOMY-CODES.md).
    -1106: (_C.REJECTED_DEFINITIVE, _PLACEMENT),
    -1125: (_C.INVALID_LISTEN_KEY, (_K.LISTEN_KEY,)),
    -2010: (_C.REJECTED_DEFINITIVE, _PLACEMENT),
    -2011: (_C.ORDER_ABSENT, (_K.QUERY, _K.CANCEL)),
    -2013: (_C.ORDER_ABSENT, (_K.QUERY, _K.CANCEL)),
    -2014: (_C.AUTH_OR_SIGNATURE, _ALL),
    -2015: (_C.AUTH_OR_SIGNATURE, _ALL),
    -2017: (_C.AUTH_OR_SIGNATURE, _ALL),
    -2018: (_C.REJECTED_DEFINITIVE, _PLACEMENT),
    -2019: (_C.REJECTED_DEFINITIVE, _PLACEMENT),
    -2021: (_C.REJECTED_DEFINITIVE, _PLACEMENT),
    -2022: (_C.REJECTED_DEFINITIVE, _PLACEMENT),
    -2024: (_C.REJECTED_DEFINITIVE, _PLACEMENT),
    -2026: (_C.REJECTED_DEFINITIVE, _PLACEMENT),
    -4003: (_C.REJECTED_DEFINITIVE, _PLACEMENT),
    -4004: (_C.REJECTED_DEFINITIVE, _PLACEMENT),
    -4005: (_C.REJECTED_DEFINITIVE, _PLACEMENT),
    -4014: (_C.REJECTED_DEFINITIVE, _PLACEMENT),
    -4067: (_C.POSITION_MODE, _ALL),
    -4068: (_C.POSITION_MODE, _ALL),
    -4116: (_C.DUPLICATE_CLIENT_ID, _PLACEMENT),
    -4120: (_C.REJECTED_DEFINITIVE, _PLACEMENT),
    -4137: (_C.REJECTED_DEFINITIVE, _PLACEMENT),
    -4138: (_C.REJECTED_DEFINITIVE, _PLACEMENT),
    -4142: (_C.REJECTED_DEFINITIVE, _PLACEMENT),
    -4016: (_C.REJECTED_DEFINITIVE, _PLACEMENT),
    -4024: (_C.REJECTED_DEFINITIVE, _PLACEMENT),
    -4164: (_C.REJECTED_DEFINITIVE, _PLACEMENT),
    -4400: (_C.REJECTED_DEFINITIVE, _PLACEMENT),
    -4401: (_C.REJECTED_DEFINITIVE, _PLACEMENT),
    -4509: (_C.PRECONDITION_NO_POSITION, _PLACEMENT),
}


def test_table_has_exactly_the_required_codes() -> None:
    assert set(ERROR_CODE_TABLE) == set(_EXPECTED_BY_CODE)


@pytest.mark.parametrize("code", sorted(_EXPECTED_BY_CODE), ids=lambda c: f"code{c}")
@pytest.mark.parametrize("http_class", [HttpClass.BAD_REQUEST, HttpClass.NOT_FOUND])
def test_code_classifies_per_call_kind(code: int, http_class: HttpClass) -> None:
    category, kinds = _EXPECTED_BY_CODE[code]
    facts = ErrorFacts(http_class, code, None)
    for kind in CallKind:
        expected = category if kind in kinds else _C.UNKNOWN_EXCHANGE_ERROR
        assert classify(facts, kind) is expected, (code, kind)


# The codes of the second read of the error-code page (2026-10-17, plan 18-26). Every other
# entry keeps the first read date. Changed on purpose, owner decided 2026-10-17.
_REREAD_CODES: frozenset[int] = frozenset({-1106, -4016, -4024, -1125})


def _expected_read_date(code: int) -> str:
    return ERROR_TABLE_REREAD_DATE if code in _REREAD_CODES else ERROR_TABLE_READ_DATE


@pytest.mark.parametrize("code", sorted(_EXPECTED_BY_CODE), ids=lambda c: f"code{c}")
def test_table_entry_metadata(code: int) -> None:
    entry = ERROR_CODE_TABLE[code]
    assert entry.code == code
    assert entry.name.strip() != ""
    assert entry.source == ERROR_TABLE_SOURCE
    assert entry.read_date == _expected_read_date(code)
    assert entry.evidence in EVIDENCE_LABELS
    assert entry.note.strip() != ""
    with pytest.raises(TypeError):
        entry.categories_by_call_kind[_K.TIME] = _C.ORDER_ABSENT  # type: ignore[index]


def test_evidence_vocabulary() -> None:
    assert frozenset({"documented", "demo-observed", "documented-elsewhere"}) == EVIDENCE_LABELS


def test_4509_is_demo_observed_only() -> None:
    entry = ERROR_CODE_TABLE[-4509]
    assert entry.evidence == "demo-observed"
    assert "09-DEMO-REHEARSAL-FINDINGS" in entry.note
    assert "documented" not in entry.evidence


# The codes the Demo probe observed that are already in the table (evidence/18-probe-check.txt,
# "Facts for plan 18-21", Demo 2026-10-16, not mainnet): (code, call kind, category, message).
_PROBE_OBSERVED_IN_TABLE: tuple[tuple[int, CallKind, ExchangeErrorCategory, str], ...] = (
    (-2013, CallKind.QUERY, _C.ORDER_ABSENT, "Order does not exist."),
    (-2011, CallKind.CANCEL, _C.ORDER_ABSENT, "Unknown order sent."),
    (-4116, CallKind.PLACEMENT, _C.DUPLICATE_CLIENT_ID, "ClientOrderId is duplicated."),
    (-4509, CallKind.PLACEMENT, _C.PRECONDITION_NO_POSITION, "Time in Force (TIF) GTE"),
    (-2021, CallKind.PLACEMENT, _C.REJECTED_DEFINITIVE, "Order would immediately trigger."),
    # Changed on purpose, owner decided 2026-10-17 (plan 18-26): the two codes the probe saw
    # that the table did not decide (18-21) are now in the table.
    (
        -1106,
        CallKind.PLACEMENT,
        _C.REJECTED_DEFINITIVE,
        "Parameter 'reduceonly' sent when not required.",
    ),
    (
        -4016,
        CallKind.PLACEMENT,
        _C.REJECTED_DEFINITIVE,
        "Limit price can't be higher than 86305.10.",
    ),
)
# The Demo user-data smoke answer that is in the table (evidence/18-smoke-check.txt item f,
# 2026-10-16): a keepalive (PUT) after a delete answered -1125 INVALID_LISTEN_KEY.
_SMOKE_OBSERVED_IN_TABLE: tuple[tuple[int, CallKind, ExchangeErrorCategory], ...] = (
    (-1125, CallKind.LISTEN_KEY, _C.INVALID_LISTEN_KEY),
)


def test_demo_observed_codes_are_exactly_the_probe_observed_codes_in_the_table() -> None:
    observed = sorted(code for code, entry in ERROR_CODE_TABLE.items() if entry.demo_observed_on)
    assert observed == sorted(
        [code for code, *_ in _PROBE_OBSERVED_IN_TABLE]
        + [code for code, *_ in _SMOKE_OBSERVED_IN_TABLE]
    )
    assert observed == [-4509, -4116, -4016, -2021, -2013, -2011, -1125, -1106]
    assert -4024 not in observed
    for code in observed:
        assert ERROR_CODE_TABLE[code].demo_observed_on == "2026-10-16"
        # The read date of the documentation is not changed by a Demo observation.
        assert ERROR_CODE_TABLE[code].read_date == _expected_read_date(code)


def test_probe_answers_classify_as_the_probe_check_file_says() -> None:
    for code, kind, category, _message in _PROBE_OBSERVED_IN_TABLE:
        facts = ErrorFacts(HttpClass.BAD_REQUEST, code, None)
        assert classify(facts, kind) is category, code
    for code, kind, category in _SMOKE_OBSERVED_IN_TABLE:
        facts = ErrorFacts(HttpClass.BAD_REQUEST, code, None)
        assert classify(facts, kind) is category, code


def test_a_demo_observation_does_not_relabel_a_documented_code() -> None:
    for code in (-2013, -2011, -4116, -2021, -1106, -4016, -4024, -1125):
        assert ERROR_CODE_TABLE[code].evidence == "documented"
    assert ERROR_CODE_TABLE[-4509].evidence == "demo-observed"
    # The duplicate clientAlgoId case was observed as -4116 (DUPLICATE_CLIENT_ID on placement).
    assert "clientAlgoId" in ERROR_CODE_TABLE[-4116].note
    assert "observed" in ERROR_CODE_TABLE[-4116].note


def test_demo_observed_on_must_be_an_iso_date() -> None:
    entry = ERROR_CODE_TABLE[-4116]
    with pytest.raises(ValueError, match="demo_observed_on"):
        dataclasses.replace(entry, demo_observed_on="yesterday")


def test_placement_never_maps_to_order_absent() -> None:
    for entry in ERROR_CODE_TABLE.values():
        assert entry.categories_by_call_kind.get(_K.PLACEMENT) is not _C.ORDER_ABSENT


def _phase18_section() -> str:
    text = (ROOT / "docs" / "SOURCES.md").read_text(encoding="utf-8")
    start = text.index("## Facts read for Phase 18")
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end]


def _error_code_row() -> list[str]:
    rows = [
        line
        for line in _phase18_section().splitlines()
        if line.startswith("| ") and "usds-margined-futures/error-code" in line.split("|")[1]
    ]
    assert len(rows) == 1
    return [cell.strip() for cell in rows[0].strip().strip("|").split("|")]


def test_read_date_is_the_latest_checked_on_date_of_the_error_code_row() -> None:
    """Changed on purpose (owner decided 2026-10-17): the row now records two reads."""
    assert "Facts read for Phase 18" in ERROR_TABLE_SOURCE
    assert "error-code" in ERROR_TABLE_SOURCE
    checked_on = _error_code_row()[2]
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", checked_on)
    assert dates, checked_on
    assert max(dates) == ERROR_TABLE_REREAD_DATE
    assert ERROR_TABLE_READ_DATE in dates
    assert ERROR_TABLE_READ_DATE < ERROR_TABLE_REREAD_DATE
    assert ERROR_TABLE_READ_DATE in _phase18_section()
    assert ERROR_TABLE_REREAD_DATE in _phase18_section()


_REREAD_MARKER = "Re-read 2026-10-17"


def _quoted_codes(text: str) -> set[int]:
    return {int(c) for c in re.findall(r"(?<![\d-])(-\d{4})(?!\d)", text)}


def test_reread_codes_match_the_sources_row() -> None:
    """The codes quoted before the marker are the ones whose note says re-read 2026-10-16
    (plus -4509); the codes quoted after it are the ones of the second read (2026-10-17)."""
    used_for = _error_code_row()[1]
    assert used_for.count(_REREAD_MARKER) == 1
    before, after = used_for.split(_REREAD_MARKER)
    quoted_before = _quoted_codes(before)
    assert -4509 in quoted_before  # named as absent from the page
    assert "-4509 is absent from the page" in before
    reread_first = {
        code for code, entry in ERROR_CODE_TABLE.items() if "re-read 2026-10-16" in entry.note
    }
    assert reread_first == quoted_before - {-4509}
    for code in reread_first:
        assert ERROR_CODE_TABLE[code].evidence == "documented"
    quoted_after = _quoted_codes(after)
    reread_second = {
        code for code, entry in ERROR_CODE_TABLE.items() if "re-read 2026-10-17" in entry.note
    }
    by_read_date = {
        code
        for code, entry in ERROR_CODE_TABLE.items()
        if entry.read_date == ERROR_TABLE_REREAD_DATE
    }
    assert quoted_after == reread_second == by_read_date == set(_REREAD_CODES)
    for code in reread_second:
        assert ERROR_CODE_TABLE[code].evidence == "documented"


_ERROR_CODE_ROW_FIRST_CELL = (
    "https://developers.binance.com/docs/derivatives/usds-margined-futures/error-code; "
    "working URL https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/"
    "error-code"
)
_OUT_OF_SCOPE_CODES = ("4131", "4183", "4184")


def test_error_code_row_keeps_one_row_and_records_the_second_read() -> None:
    cells = _error_code_row()
    assert len(cells) == 4
    assert cells[0] == _ERROR_CODE_ROW_FIRST_CELL
    segment = cells[1].split(_REREAD_MARKER)[1]
    for required in (
        "page last modified 2026-10-16",
        "18-error-code-page-reread-20261017.txt",
        "derivatives-trading-usds-futures/error-code",
        "A parameter was sent when not required.",
        "Parameter 'reduceonly' sent when not required.",
        "issue 4231",
        "secondary",
    ):
        assert required in segment, required
    assert "Demo wording differs" in segment
    assert "https://" not in segment  # the Nautilus reference carries no URL scheme
    for number in _OUT_OF_SCOPE_CODES:
        assert number not in cells[1]
    assert "re-read 2026-10-17" in cells[2]
    assert "page last modified 2026-10-16" in cells[2]
    assert "second read 2026-10-17" in cells[3]
    assert "18-error-code-page-reread-20261017.txt" in cells[3]
    # The first read is kept as it was.
    assert "Read 2026-10-16 (WebFetch summary)" in cells[1]


def test_entry_read_date_defaults_to_the_first_read_and_can_be_overridden() -> None:
    assert ERROR_TABLE_READ_DATE == "2026-10-16"
    assert ERROR_TABLE_REREAD_DATE == "2026-10-17"
    assert ERROR_TABLE_REREAD_DATE > ERROR_TABLE_READ_DATE
    for code, entry in ERROR_CODE_TABLE.items():
        expected = ERROR_TABLE_REREAD_DATE if code in _REREAD_CODES else ERROR_TABLE_READ_DATE
        assert entry.read_date == expected, code
    override = dataclasses.replace(ERROR_CODE_TABLE[-2013], read_date=ERROR_TABLE_REREAD_DATE)
    assert override.read_date == ERROR_TABLE_REREAD_DATE


def test_code_entry_validates_read_date() -> None:
    entry = ERROR_CODE_TABLE[-2013]
    with pytest.raises(ValueError, match="read_date"):
        dataclasses.replace(entry, read_date="yesterday")
    with pytest.raises(ValueError, match="read_date"):
        dataclasses.replace(entry, read_date="")


def test_only_the_owner_codes_carry_the_second_read_date() -> None:
    """Changed on purpose (owner decided 2026-10-17): the set is one constant of this file."""
    second = {c for c, e in ERROR_CODE_TABLE.items() if e.read_date == ERROR_TABLE_REREAD_DATE}
    assert second == set(_REREAD_CODES)
    for code, entry in ERROR_CODE_TABLE.items():
        if code not in _REREAD_CODES:
            assert entry.read_date == ERROR_TABLE_READ_DATE, code


def test_1106_entry_keeps_page_and_demo_wording_apart() -> None:
    entry = ERROR_CODE_TABLE[-1106]
    assert entry.name == "PARAM_NOT_REQUIRED"
    assert entry.evidence == "documented"
    assert entry.read_date == ERROR_TABLE_REREAD_DATE
    assert entry.demo_observed_on == "2026-10-16"
    assert dict(entry.categories_by_call_kind) == {_K.PLACEMENT: _C.REJECTED_DEFINITIVE}
    for required in (
        "PARAM_NOT_REQUIRED",
        "wrongly built request",
        "reduceOnly",
        "positionSide",
        "hedge mode",
        "not mapped to POSITION_MODE",
        "official USD-M",
        "nautilus_trader issue 4231",
        "secondary",
        "re-read 2026-10-17",
        "Parameter 'reduceonly' sent when not required.",
        "A parameter was sent when not required.",
        "rejected_protective_variants",
    ):
        assert required in entry.note, required
    assert "re-read 2026-10-16" not in entry.note
    for kind in CallKind:
        assert _C.POSITION_MODE is not classify(
            ErrorFacts(HttpClass.BAD_REQUEST, -1106, None), kind
        )


# --------------------------------------------------------------------------- #
# Task 2: HTTP-class rules (the class overrides the code)
# --------------------------------------------------------------------------- #

_SAMPLE_CODES: tuple[int | None, ...] = (None, -2013, -2011, -1021, -4509, -1003, -999999)

_CLASS_RULES: dict[HttpClass, ExchangeErrorCategory] = {
    HttpClass.BANNED_418: _C.IP_BANNED,
    HttpClass.TOO_MANY_429: _C.RATE_LIMITED,
    HttpClass.SERVER_5XX: _C.STATUS_UNKNOWN,
    HttpClass.CLIENT_OTHER: _C.STATUS_UNKNOWN,
    HttpClass.NETWORK: _C.STATUS_UNKNOWN,
    HttpClass.UNAUTHORIZED: _C.AUTH_OR_SIGNATURE,
    HttpClass.FORBIDDEN: _C.AUTH_OR_SIGNATURE,
    HttpClass.NON_SDK: _C.UNKNOWN_EXCHANGE_ERROR,
}


@pytest.mark.parametrize("http_class", list(_CLASS_RULES), ids=lambda c: c.value)
def test_class_rule_overrides_the_code(http_class: HttpClass) -> None:
    for code in _SAMPLE_CODES:
        for kind in CallKind:
            facts = ErrorFacts(http_class, code, None)
            assert classify(facts, kind) is _CLASS_RULES[http_class], (code, kind)


def test_every_http_class_has_a_rule_or_uses_the_table() -> None:
    assert set(_CLASS_RULES) | {HttpClass.BAD_REQUEST, HttpClass.NOT_FOUND} == set(HttpClass)


@pytest.mark.parametrize("http_class", [HttpClass.BAD_REQUEST, HttpClass.NOT_FOUND])
@pytest.mark.parametrize("code", [None, -999999, -1000, 0, 418, 429, -4531])
def test_table_class_with_missing_or_unknown_code_is_unknown(
    http_class: HttpClass, code: int | None
) -> None:
    for kind in CallKind:
        assert classify(ErrorFacts(http_class, code, None), kind) is _C.UNKNOWN_EXCHANGE_ERROR


def test_retry_after_does_not_change_the_category() -> None:
    for kind in CallKind:
        assert classify(ErrorFacts(HttpClass.TOO_MANY_429, -1003, 7), kind) is _C.RATE_LIMITED
        assert classify(ErrorFacts(HttpClass.BANNED_418, -1003, 7), kind) is _C.IP_BANNED


@pytest.mark.parametrize(
    ("code", "retry_after"),
    [(True, None), (False, None), ("-2013", None), (None, -1), (None, True), (None, "7")],
)
def test_error_facts_validation(code: Any, retry_after: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        ErrorFacts(HttpClass.BAD_REQUEST, code, retry_after)


def test_classify_rejects_wrong_argument_types() -> None:
    with pytest.raises(TypeError):
        classify(ErrorFacts(HttpClass.BAD_REQUEST, -2013, None), "QUERY")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        classify((HttpClass.BAD_REQUEST, -2013, None), CallKind.QUERY)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Task 2: retry and SAFE_MODE eligibility
# --------------------------------------------------------------------------- #

_RETRY_KINDS = frozenset({_K.QUERY, _K.CANCEL, _K.TIME, _K.LISTEN_KEY})


@pytest.mark.parametrize("category", list(ExchangeErrorCategory), ids=lambda c: c.value)
@pytest.mark.parametrize("call_kind", list(CallKind), ids=lambda k: k.value)
def test_retry_eligible_cross_product(category: ExchangeErrorCategory, call_kind: CallKind) -> None:
    expected = category is _C.STATUS_UNKNOWN and call_kind in _RETRY_KINDS
    assert retry_eligible(category, call_kind) is expected
    if call_kind is _K.PLACEMENT:
        assert retry_eligible(category, call_kind) is False
    if category in {_C.RATE_LIMITED, _C.IP_BANNED}:
        assert retry_eligible(category, call_kind) is False


@pytest.mark.parametrize("category", list(ExchangeErrorCategory), ids=lambda c: c.value)
def test_safe_mode_eligible_only_for_unknown(category: ExchangeErrorCategory) -> None:
    assert safe_mode_eligible(category) is (category is _C.UNKNOWN_EXCHANGE_ERROR)


def test_eligibility_rejects_wrong_argument_types() -> None:
    with pytest.raises(TypeError):
        retry_eligible("STATUS_UNKNOWN", _K.QUERY)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        retry_eligible(_C.STATUS_UNKNOWN, "QUERY")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        safe_mode_eligible("UNKNOWN_EXCHANGE_ERROR")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Task 2: rate-limit decision (user record 18-DEC-O-18-01.md and its amendment
# of 2026-10-16). The values below are test-only and deliberately distinct so a
# swapped 418/429 fallback or a missing cap fails; they are NOT the user's
# numbers and no number exists in src.
# --------------------------------------------------------------------------- #

TEST_ONLY_418_FALLBACK_SECONDS = 11
TEST_ONLY_429_FALLBACK_SECONDS = 5
TEST_ONLY_CAP_SECONDS = 13


def _kw(**overrides: int) -> dict[str, int]:
    kwargs = {
        "no_retry_after_wait_418_seconds": TEST_ONLY_418_FALLBACK_SECONDS,
        "no_retry_after_wait_429_seconds": TEST_ONLY_429_FALLBACK_SECONDS,
        "retry_after_cap_seconds": TEST_ONLY_CAP_SECONDS,
    }
    kwargs.update(overrides)
    return kwargs


def test_ip_banned_without_retry_after_uses_418_fallback() -> None:
    decision = rate_limit_decision(_C.IP_BANNED, None, **_kw())
    assert decision == RateLimitDecision(retry=False, wait_seconds=TEST_ONLY_418_FALLBACK_SECONDS)


def test_rate_limited_without_retry_after_uses_429_fallback() -> None:
    decision = rate_limit_decision(_C.RATE_LIMITED, None, **_kw())
    assert decision == RateLimitDecision(retry=False, wait_seconds=TEST_ONLY_429_FALLBACK_SECONDS)


def test_valid_retry_after_is_honoured_for_both_statuses() -> None:
    for category in (_C.IP_BANNED, _C.RATE_LIMITED):
        assert rate_limit_decision(category, 7, **_kw()) == RateLimitDecision(False, 7)
        assert rate_limit_decision(category, 0, **_kw()) == RateLimitDecision(False, 0)


def test_cap_bounds_retry_after_and_both_fallbacks() -> None:
    for category in (_C.IP_BANNED, _C.RATE_LIMITED):
        capped = rate_limit_decision(category, 50, **_kw())
        assert capped == RateLimitDecision(False, TEST_ONLY_CAP_SECONDS)
        at_cap = rate_limit_decision(category, TEST_ONLY_CAP_SECONDS, **_kw())
        assert at_cap == RateLimitDecision(False, TEST_ONLY_CAP_SECONDS)
    big_418 = rate_limit_decision(_C.IP_BANNED, None, **_kw(no_retry_after_wait_418_seconds=20))
    assert big_418 == RateLimitDecision(False, TEST_ONLY_CAP_SECONDS)
    big_429 = rate_limit_decision(_C.RATE_LIMITED, None, **_kw(no_retry_after_wait_429_seconds=20))
    assert big_429 == RateLimitDecision(False, TEST_ONLY_CAP_SECONDS)


def test_rate_limit_decision_never_retries() -> None:
    for category in ExchangeErrorCategory:
        for retry_after in (None, 0, 7, 50):
            decision = rate_limit_decision(category, retry_after, **_kw())
            assert decision.retry is False
            if category not in {_C.IP_BANNED, _C.RATE_LIMITED}:
                assert decision == RateLimitDecision(False, None)


@pytest.mark.parametrize(
    "missing",
    [
        "no_retry_after_wait_418_seconds",
        "no_retry_after_wait_429_seconds",
        "retry_after_cap_seconds",
    ],
)
def test_rate_limit_decision_requires_each_keyword(missing: str) -> None:
    kwargs = _kw()
    del kwargs[missing]
    with pytest.raises(TypeError):
        rate_limit_decision(_C.RATE_LIMITED, None, **kwargs)


@pytest.mark.parametrize(
    "name",
    [
        "no_retry_after_wait_418_seconds",
        "no_retry_after_wait_429_seconds",
        "retry_after_cap_seconds",
    ],
)
@pytest.mark.parametrize("bad", [True, False, 0, -1, "5", None])
def test_rate_limit_decision_rejects_bool_zero_and_negative(name: str, bad: Any) -> None:
    kwargs: dict[str, Any] = _kw()
    kwargs[name] = bad
    with pytest.raises(ValueError):
        rate_limit_decision(_C.IP_BANNED, None, **kwargs)
    with pytest.raises(ValueError):
        rate_limit_decision(_C.ORDER_ABSENT, None, **kwargs)


@pytest.mark.parametrize("bad", [True, False, -1, "7"])
def test_rate_limit_decision_rejects_bad_retry_after(bad: Any) -> None:
    with pytest.raises(ValueError):
        rate_limit_decision(_C.RATE_LIMITED, bad, **_kw())


def test_rate_limit_decision_rejects_non_category() -> None:
    with pytest.raises(TypeError):
        rate_limit_decision("RATE_LIMITED", None, **_kw())  # type: ignore[arg-type]


def test_rate_limit_decision_has_only_retry_and_wait_fields() -> None:
    assert [f.name for f in dataclasses.fields(RateLimitDecision)] == ["retry", "wait_seconds"]
    params = inspect.signature(rate_limit_decision).parameters
    assert list(params) == [
        "category",
        "retry_after_seconds",
        "no_retry_after_wait_418_seconds",
        "no_retry_after_wait_429_seconds",
        "retry_after_cap_seconds",
    ]
    for name in list(params)[2:]:
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert params[name].default is inspect.Parameter.empty
    assert not any("kind" in name or "call" in name for name in params)
    with pytest.raises(dataclasses.FrozenInstanceError):
        RateLimitDecision(False, None).retry = True  # type: ignore[misc]


def test_rate_limit_decision_body_has_no_number_but_zero() -> None:
    tree = ast.parse(TAXONOMY.read_text(encoding="utf-8"))
    funcs = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "rate_limit_decision"
    ]
    assert len(funcs) == 1
    numbers = [
        node.value
        for node in ast.walk(funcs[0])
        if isinstance(node, ast.Constant)
        and isinstance(node.value, int | float | complex)
        and not isinstance(node.value, bool)
    ]
    assert set(numbers) <= {0}


def test_no_users_number_is_a_module_constant_of_src() -> None:
    """The user's ratified waits live in config (plans 18-07/18-09), never in this module."""
    source = TAXONOMY.read_text(encoding="utf-8")
    for number in ("259200", "120"):
        assert re.search(rf"(?<!\d){number}(?!\d)", source) is None


def test_same_input_same_output() -> None:
    facts = ErrorFacts(HttpClass.BAD_REQUEST, -2019, None)
    first = [classify(facts, kind) for kind in CallKind]
    second = [classify(facts, kind) for kind in CallKind]
    assert first == second
    assert rate_limit_decision(_C.RATE_LIMITED, None, **_kw()) == rate_limit_decision(
        _C.RATE_LIMITED, None, **_kw()
    )


def test_table_is_read_only() -> None:
    assert isinstance(ERROR_CODE_TABLE, Mapping)
    with pytest.raises(TypeError):
        ERROR_CODE_TABLE[-1] = ERROR_CODE_TABLE[-2013]  # type: ignore[index]


def test_codes_outside_the_owner_decision_stay_unknown() -> None:
    """-4131, -4183 and -4184 are listed by the same page and are not added (owner point 5)."""
    for code in (-4131, -4183, -4184):
        assert code not in ERROR_CODE_TABLE
        for http_class in (HttpClass.BAD_REQUEST, HttpClass.NOT_FOUND):
            facts = ErrorFacts(http_class, code, None)
            for kind in CallKind:
                assert classify(facts, kind) is _C.UNKNOWN_EXCHANGE_ERROR, (code, kind)


def test_4016_entry_keeps_page_and_demo_wording_apart() -> None:
    entry = ERROR_CODE_TABLE[-4016]
    assert entry.name == "PRICE_HIGHTER_THAN_MULTIPLIER_UP"
    assert entry.evidence == "documented"
    assert entry.read_date == ERROR_TABLE_REREAD_DATE
    assert entry.demo_observed_on == "2026-10-16"
    assert dict(entry.categories_by_call_kind) == {_K.PLACEMENT: _C.REJECTED_DEFINITIVE}
    for required in (
        "mark price multiplier cap",
        "Price is higher than mark price multiplier cap.",
        "Limit price can't be higher than 86305.10.",
        "wording differs",
        "HIGHTER",
        "no retry",
        "never evidence that an order is protected",
        "re-read 2026-10-17",
        "refreshing the mark price and the filters",
        "consumer",
        "Phase 19/20",
    ):
        assert required in entry.note, required
    assert "re-read 2026-10-16" not in entry.note


def test_4024_entry_is_documented_and_not_observed_on_demo() -> None:
    entry = ERROR_CODE_TABLE[-4024]
    assert entry.name == "PRICE_LOWER_THAN_MULTIPLIER_DOWN"
    assert entry.evidence == "documented"
    assert entry.read_date == ERROR_TABLE_REREAD_DATE
    assert entry.demo_observed_on is None
    assert dict(entry.categories_by_call_kind) == {_K.PLACEMENT: _C.REJECTED_DEFINITIVE}
    for required in (
        "mark price multiplier floor",
        "Price is lower than mark price multiplier floor.",
        "not observed on Demo",
        "no retry",
        "snapshot",
        "re-read 2026-10-17",
    ):
        assert required in entry.note, required
    assert "re-read 2026-10-16" not in entry.note


def test_1125_keeps_its_mapping_and_records_the_smoke_observation() -> None:
    entry = ERROR_CODE_TABLE[-1125]
    assert dict(entry.categories_by_call_kind) == {_K.LISTEN_KEY: _C.INVALID_LISTEN_KEY}
    assert entry.evidence == "documented"
    assert entry.demo_observed_on == DEMO_SMOKE_DATE == "2026-10-16"
    assert entry.read_date == ERROR_TABLE_REREAD_DATE
    assert "assumed" not in entry.note
    for required in (
        "re-read 2026-10-16",
        "re-read 2026-10-17",
        "unchanged",
        "observed on Demo (smoke)",
        "evidence/18-smoke-check.txt item f",
        "PUT after DELETE answered BAD_REQUEST -1125 (INVALID_LISTEN_KEY)",
        "not mainnet",
    ):
        assert required in entry.note, required
    for kind in CallKind:
        facts = ErrorFacts(HttpClass.BAD_REQUEST, -1125, None)
        expected = _C.INVALID_LISTEN_KEY if kind is _K.LISTEN_KEY else _C.UNKNOWN_EXCHANGE_ERROR
        assert classify(facts, kind) is expected


def test_sources_row_names_all_four_codes_after_the_marker_and_keeps_the_demo_wording_apart() -> (
    None
):
    segment = _error_code_row()[1].split(_REREAD_MARKER)[1]
    assert _quoted_codes(segment) == {-1106, -4016, -4024, -1125}
    for required in (
        "PRICE_HIGHTER_THAN_MULTIPLIER_UP",
        "Price is higher than mark price multiplier cap.",
        "Limit price can't be higher than 86305.10.",
        "PRICE_LOWER_THAN_MULTIPLIER_DOWN",
        "Price is lower than mark price multiplier floor.",
        "-4024 was not observed on Demo",
        "evidence/18-smoke-check.txt item f",
    ):
        assert required in segment, required
