"""Quick 261014-nnl plan 01 Task 3: pure recompute of the REEFUSDT bounded settlement interval.

The evidence (Binance index-price and trade klines) is committed byte for byte under
docs/research/preregistration/evidence/terminal-settlement/REEFUSDT/. These tests recompute the
nominal bounds, the tick-widened index bounds, the 09:00 trade candle and the union from those
bytes (design test 9), and check that tampered, missing, duplicated or extra minutes fail closed.
No network, no market-data store, no ExperimentRecord, no Holdout.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from src.domain.canonical import canonical_decimal_text
from src.research.settlement_evidence import (
    KlineRow,
    RecomputedBounds,
    SettlementEvidenceError,
    fraction_text,
    nominal_index_bounds,
    parse_fraction_text,
    parse_klines,
    recompute_settlement_bounds,
    sha256_bytes,
    tick_widened_bounds,
    trade_candle_bounds,
    union_bounds,
)

D = Decimal
EVIDENCE = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "research"
    / "preregistration"
    / "evidence"
    / "terminal-settlement"
    / "REEFUSDT"
)
STEMS = (
    "A_klines_after_settlement",
    "B_indexPriceKlines_before_settlement",
    "F_indexklines_sample_day",
)
INDEX_STEM = "B_indexPriceKlines_before_settlement"
TRADE_STEM = "A_klines_after_settlement"
TERMINAL = datetime(2025, 1, 22, 9, 0, tzinfo=UTC)
WINDOW_START = datetime(2025, 1, 22, 8, 30, tzinfo=UTC)
TICK = D("0.000001")
RECORD_KEYS = frozenset(
    {
        "schema",
        "scratch_name",
        "request_url",
        "request_url_source",
        "method",
        "http_date_header",
        "fetched_at_utc",
        "body_file",
        "body_sha256",
        "headers_file",
        "origin_host",
        "host_rule_note",
    }
)


def _body(stem: str) -> bytes:
    return (EVIDENCE / f"{stem}.body.json").read_bytes()


def _index_rows() -> tuple[KlineRow, ...]:
    return parse_klines(_body(INDEX_STEM), what="index klines")


def _trade_rows() -> tuple[KlineRow, ...]:
    return parse_klines(_body(TRADE_STEM), what="trade klines")


def _dump(rows: list[Any]) -> bytes:
    return json.dumps(rows, separators=(",", ":")).encode("utf-8")


def _raw_rows(stem: str) -> list[Any]:
    loaded = json.loads(_body(stem))
    assert isinstance(loaded, list)
    return loaded


def _strict_json(path: Path) -> dict[str, Any]:
    def refuse(text: str) -> Any:
        raise AssertionError(f"float literal {text} in {path.name}")

    loaded = json.loads(path.read_text(encoding="utf-8"), parse_float=refuse, parse_constant=refuse)
    assert isinstance(loaded, dict)
    return loaded


# --------------------------------------------------------------------------- committed evidence


@pytest.mark.parametrize("stem", STEMS)
def test_committed_evidence_files_match_their_recorded_sha256(stem: str) -> None:
    record = _strict_json(EVIDENCE / f"{stem}.request.json")
    body = _body(stem)
    assert record["body_sha256"] == hashlib.sha256(body).hexdigest()
    assert record["body_sha256"] == sha256_bytes(body)


def test_known_sha256_of_the_mandatory_bodies() -> None:
    assert sha256_bytes(_body(INDEX_STEM)) == (
        "56afae6cbbbfe185876432143936d492f727b2fc0236b1d3537c033e714769b8"
    )
    assert sha256_bytes(_body(TRADE_STEM)) == (
        "2a82295368afc1fe31f0661e735f458ebc035f106782349b530d3e8f7deb2fa1"
    )
    assert sha256_bytes(_body("F_indexklines_sample_day")) == (
        "c3e7ef5b419678031a05fbf33a78067bd5c5590f90823580ac05daa68b39f176"
    )


@pytest.mark.parametrize("stem", STEMS)
def test_request_records_name_url_fetch_time_and_body_hash(stem: str) -> None:
    record = _strict_json(EVIDENCE / f"{stem}.request.json")
    assert set(record) == RECORD_KEYS
    assert record["schema"] == "fetch-record/1"
    assert record["method"] == "GET"
    assert record["body_file"] == f"{stem}.body.json"
    assert record["headers_file"] == f"{stem}.headers.txt"
    assert record["origin_host"] == "fapi.binance.com"
    assert str(record["request_url"]).startswith("https://fapi.binance.com/fapi/v1/")
    assert "REEFUSDT" in str(record["request_url"])
    assert "KG4" in str(record["host_rule_note"])
    for value in record.values():
        assert isinstance(value, str)
    headers = (EVIDENCE / f"{stem}.headers.txt").read_bytes().decode("ascii")
    assert record["http_date_header"] in headers.split("\r\n")
    assert str(record["http_date_header"]).startswith("Date: ")
    fetched = datetime.strptime(str(record["fetched_at_utc"]), "%Y-%m-%dT%H:%M:%SZ")
    stamped = datetime.strptime(
        str(record["http_date_header"])[len("Date: ") :], "%a, %d %b %Y %H:%M:%S GMT"
    )
    assert fetched == stamped


def test_request_record_urls_state_the_documented_endpoint_and_window() -> None:
    urls = {
        stem: str(_strict_json(EVIDENCE / f"{stem}.request.json")["request_url"]) for stem in STEMS
    }
    assert urls[TRADE_STEM].startswith("https://fapi.binance.com/fapi/v1/klines?symbol=REEFUSDT")
    assert "startTime=1737536400000" in urls[TRADE_STEM]
    assert urls[INDEX_STEM].startswith(
        "https://fapi.binance.com/fapi/v1/indexPriceKlines?pair=REEFUSDT"
    )
    assert "startTime=1737534600000" in urls[INDEX_STEM]
    assert "startTime=1735720200000" in urls["F_indexklines_sample_day"]


def test_sample_day_index_klines_parse_and_cover_the_same_half_hour() -> None:
    rows = parse_klines(_body("F_indexklines_sample_day"), what="sample day klines")
    start = datetime(2025, 1, 1, 8, 30, tzinfo=UTC)
    assert [r.open_utc for r in rows] == [start + timedelta(minutes=i) for i in range(30)]


# --------------------------------------------------------------------------- recompute


def test_index_klines_cover_exactly_the_thirty_minutes_before_the_terminal() -> None:
    rows = _index_rows()
    assert len(rows) == 30
    assert [r.open_utc for r in rows] == [WINDOW_START + timedelta(minutes=i) for i in range(30)]
    assert rows[0].open_utc == datetime(2025, 1, 22, 8, 30, tzinfo=UTC)
    assert rows[-1].open_utc == datetime(2025, 1, 22, 8, 59, tzinfo=UTC)


def test_nominal_bounds_recompute_to_the_recorded_fractions() -> None:
    lower, upper = nominal_index_bounds(
        _index_rows(), window_start_utc=WINDOW_START, window_end_utc=TERMINAL
    )
    assert lower == Fraction(5123, 6000000)
    assert upper == Fraction(347, 400000)
    assert fraction_text(lower) == "5123/6000000"
    assert fraction_text(upper) == "347/400000"
    assert parse_fraction_text("5123/6000000") == lower
    assert parse_fraction_text("347/400000") == upper


def test_tick_widened_index_bounds_are_0_000852_and_0_000869() -> None:
    lower, upper = tick_widened_bounds(Fraction(5123, 6000000), Fraction(347, 400000), tick=TICK)
    assert lower == D("0.000852")
    assert upper == D("0.000869")
    assert canonical_decimal_text(lower) == "0.000852"
    assert canonical_decimal_text(upper) == "0.000869"


def test_tick_widening_of_exact_tick_multiples_still_widens_by_one_tick() -> None:
    lower, upper = tick_widened_bounds(Fraction(853, 1000000), Fraction(868, 1000000), tick=TICK)
    assert (lower, upper) == (D("0.000852"), D("0.000869"))


def test_trade_candle_at_the_terminal_is_low_0_000845_high_0_000887() -> None:
    low, high = trade_candle_bounds(_trade_rows(), open_utc=TERMINAL)
    assert low == D("0.000845")
    assert high == D("0.000887")
    assert canonical_decimal_text(low) == "0.000845"
    assert canonical_decimal_text(high) == "0.000887"


def test_union_bounds_are_0_000845_and_0_000887() -> None:
    lower, upper = union_bounds(D("0.000852"), D("0.000869"), D("0.000845"), D("0.000887"))
    assert (lower, upper) == (D("0.000845"), D("0.000887"))
    # a trade candle inside the index interval never narrows it
    assert union_bounds(D("0.000852"), D("0.000869"), D("0.000860"), D("0.000861")) == (
        D("0.000852"),
        D("0.000869"),
    )


def test_recompute_settlement_bounds_from_the_committed_bytes() -> None:
    bounds = recompute_settlement_bounds(
        index_klines=_body(INDEX_STEM),
        trade_kline=_body(TRADE_STEM),
        window_start_utc=WINDOW_START,
        terminal_at_utc=TERMINAL,
        tick=TICK,
    )
    assert isinstance(bounds, RecomputedBounds)
    assert bounds.nominal_lower == Fraction(5123, 6000000)
    assert bounds.nominal_upper == Fraction(347, 400000)
    assert bounds.index_lower == D("0.000852")
    assert bounds.index_upper == D("0.000869")
    assert bounds.trade_low == D("0.000845")
    assert bounds.trade_high == D("0.000887")
    assert bounds.price_lower == D("0.000845")
    assert bounds.price_upper == D("0.000887")
    assert canonical_decimal_text(bounds.price_lower) == "0.000845"
    assert canonical_decimal_text(bounds.price_upper) == "0.000887"


def test_every_index_value_on_the_settlement_day_is_a_tick_multiple() -> None:
    rows = _index_rows()
    values = [v for r in rows for v in (r.open, r.high, r.low, r.close)]
    assert len(values) == 120
    assert all(v % TICK == 0 for v in values)


# --------------------------------------------------------------------------- fail closed


def test_recompute_refuses_a_missing_duplicate_or_extra_minute() -> None:
    raw = _raw_rows(INDEX_STEM)
    missing = raw[:10] + raw[11:]
    duplicate = raw[:10] + [raw[10]] + raw[10:29]
    extra = raw + [[1737536400000, "0.000880", "0.000880", "0.000880", "0.000880", "0"]]
    short = raw[:29]
    reordered = [raw[1], raw[0], *raw[2:]]
    for bad in (missing, duplicate, extra, short, reordered):
        rows = parse_klines(_dump(bad), what="index klines")
        with pytest.raises(SettlementEvidenceError):
            nominal_index_bounds(rows, window_start_utc=WINDOW_START, window_end_utc=TERMINAL)


def test_nominal_bounds_refuse_a_misaligned_or_empty_window() -> None:
    rows = _index_rows()
    with pytest.raises(SettlementEvidenceError):
        nominal_index_bounds(
            rows, window_start_utc=WINDOW_START + timedelta(seconds=1), window_end_utc=TERMINAL
        )
    with pytest.raises(SettlementEvidenceError):
        nominal_index_bounds(rows, window_start_utc=TERMINAL, window_end_utc=WINDOW_START)
    with pytest.raises(SettlementEvidenceError):
        nominal_index_bounds(
            rows,
            window_start_utc=WINDOW_START.replace(tzinfo=None),
            window_end_utc=TERMINAL,
        )


def test_a_tampered_row_changes_the_hash_and_the_recomputed_bound() -> None:
    raw = _raw_rows(INDEX_STEM)
    raw[5][3] = "0.00080000"  # a lower low changes the mean, so the bound no longer matches
    bounds = recompute_settlement_bounds(
        index_klines=_dump(raw),
        trade_kline=_body(TRADE_STEM),
        window_start_utc=WINDOW_START,
        terminal_at_utc=TERMINAL,
        tick=TICK,
    )
    assert bounds.nominal_lower != Fraction(5123, 6000000)
    assert sha256_bytes(_dump(raw)) != sha256_bytes(_body(INDEX_STEM))


def test_recompute_refuses_a_json_float_or_a_non_string_price() -> None:
    text = _body(INDEX_STEM).decode("utf-8")
    with_float = text.replace('"0.00092300"', "0.000923", 1)
    assert with_float != text
    with pytest.raises(SettlementEvidenceError):
        parse_klines(with_float.encode("utf-8"), what="index klines")
    with pytest.raises(SettlementEvidenceError):
        parse_klines(b'[[1737534600000,NaN,"1","1","1"]]', what="index klines")
    raw = _raw_rows(INDEX_STEM)
    raw[0][1] = 1
    with pytest.raises(SettlementEvidenceError):
        parse_klines(_dump(raw), what="index klines")
    raw = _raw_rows(INDEX_STEM)
    raw[0][0] = True
    with pytest.raises(SettlementEvidenceError):
        parse_klines(_dump(raw), what="index klines")
    raw = _raw_rows(INDEX_STEM)
    raw[0][2] = "abc"
    with pytest.raises(SettlementEvidenceError):
        parse_klines(_dump(raw), what="index klines")
    raw = _raw_rows(INDEX_STEM)
    raw[0][2] = "-0.1"
    with pytest.raises(SettlementEvidenceError):
        parse_klines(_dump(raw), what="index klines")


def test_parse_klines_refuses_malformed_documents() -> None:
    for bad in (b"", b"{}", b"[]", b"[1]", b"[[1,2]]", b"not json", b"\xff\xfe"):
        with pytest.raises(SettlementEvidenceError):
            parse_klines(bad, what="klines")


def test_recompute_refuses_a_trade_kline_without_the_terminal_minute() -> None:
    raw = _raw_rows(TRADE_STEM)
    without = raw[1:]
    with pytest.raises(SettlementEvidenceError):
        trade_candle_bounds(parse_klines(_dump(without), what="trade klines"), open_utc=TERMINAL)
    twice = [raw[0], *raw]
    with pytest.raises(SettlementEvidenceError):
        trade_candle_bounds(parse_klines(_dump(twice), what="trade klines"), open_utc=TERMINAL)
    with pytest.raises(SettlementEvidenceError):
        recompute_settlement_bounds(
            index_klines=_body(INDEX_STEM),
            trade_kline=_dump(without),
            window_start_utc=WINDOW_START,
            terminal_at_utc=TERMINAL,
            tick=TICK,
        )


@pytest.mark.parametrize(
    "tick",
    [D("0"), D("-0.000001"), D("NaN"), D("Infinity"), 0.000001, "0.000001", 1, None],
)
def test_recompute_refuses_a_non_positive_or_non_decimal_tick(tick: Any) -> None:
    with pytest.raises(SettlementEvidenceError):
        tick_widened_bounds(Fraction(5123, 6000000), Fraction(347, 400000), tick=tick)


def test_tick_widening_refuses_inverted_or_non_positive_bounds() -> None:
    with pytest.raises(SettlementEvidenceError):
        tick_widened_bounds(Fraction(2, 1000), Fraction(1, 1000), tick=TICK)
    with pytest.raises(SettlementEvidenceError):
        tick_widened_bounds(Fraction(1, 2000000), Fraction(1, 1000), tick=TICK)
    with pytest.raises(SettlementEvidenceError):
        tick_widened_bounds(Fraction(0), Fraction(1, 1000), tick=TICK)


def test_union_bounds_refuse_an_inverted_interval() -> None:
    with pytest.raises(SettlementEvidenceError):
        union_bounds(D("0.000900"), D("0.000800"), D("0.000900"), D("0.000800"))


@pytest.mark.parametrize(
    "text",
    ["2/4", "-1/2", "1/0", "0/5", "5/-3", "1.5/2", "1/2/3", "1", "", " 1/2", "1/2 ", "01/2", "a/b"],
)
def test_parse_fraction_text_refuses_unreduced_negative_or_zero_denominator(text: str) -> None:
    with pytest.raises(SettlementEvidenceError):
        parse_fraction_text(text)


def test_fraction_text_round_trips_through_parse_fraction_text() -> None:
    for value in (Fraction(5123, 6000000), Fraction(347, 400000), Fraction(3, 1)):
        assert parse_fraction_text(fraction_text(value)) == value
