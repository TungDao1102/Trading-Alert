"""Quick 261014-nnl plan 02: the manifest entry `terminal_settlements` and its guard.

Data contract D1 and the statistics guard of `16-DRAFT-S-B-interval-design.md` sections 2 and 4
(design test 2). The REEFUSDT row lives only inside these tests: no manifest file is written, no
store is read, no network, no ExperimentRecord outside pytest tmp_path, no Holdout.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from src.backtest.semantics import (
    TERMINAL_EVALUATION_UNION_ADVERSE_BOUND,
    TERMINAL_KIND_BOUNDED_BY_INDEX_KLINES,
)
from src.data.case_input import TerminalDeclaration
from src.domain.canonical import canonical_scalars, sha256_hex
from src.research.manifest import (
    DatasetManifest,
    EvidenceFile,
    ManifestError,
    TerminalSettlement,
    load_manifest,
    manifest_hash,
)

from tests import test_research_known_gap_reason as kg

D = Decimal
REEF = "REEFUSDT"
BTC = "BTCUSDT"
REEF_URL = "https://www.binance.com/en/support/announcement/detail/572715f2d96e47769ebbb967c2a6e445"
TERMINAL = datetime(2025, 1, 22, 9, 0, tzinfo=UTC)
WINDOW_START = datetime(2025, 1, 22, 8, 30, tzinfo=UTC)
DEV_START = datetime(2025, 1, 1, tzinfo=UTC)
VAL_START = datetime(2025, 2, 1, tzinfo=UTC)
VAL_END = datetime(2025, 3, 1, tzinfo=UTC)
HOLD_END = datetime(2025, 4, 1, tzinfo=UTC)
TICK = D("0.000001")
PLUS7 = timezone(timedelta(hours=7))

EVIDENCE_DIR = "docs/research/preregistration/evidence/terminal-settlement/REEFUSDT"
INDEX_PATH = f"{EVIDENCE_DIR}/B_indexPriceKlines_before_settlement.body.json"
INDEX_SHA = "56afae6cbbbfe185876432143936d492f727b2fc0236b1d3537c033e714769b8"
TRADE_PATH = f"{EVIDENCE_DIR}/A_klines_after_settlement.body.json"
TRADE_SHA = "2a82295368afc1fe31f0661e735f458ebc035f106782349b530d3e8f7deb2fa1"
SUPPORT_PATH = f"{EVIDENCE_DIR}/F_indexklines_sample_day.body.json"
SUPPORT_SHA = "c3e7ef5b419678031a05fbf33a78067bd5c5590f90823580ac05daa68b39f176"
CONDITION = (
    "unverified assumptions: settlement is the mean of per-second index values over "
    "08:30-09:00 UTC, 60 equal-weight samples per minute, klines serve unrevised history, "
    "rounding within one tick; the 09:00 trade candle (open = close = 0.000880, 102 trades) "
    "lies above the index bound and is not read as the settlement price"
)

# The hash of the manifest below WITHOUT a settlement, captured from the code as it stood before
# `terminal_settlements` existed (quick 261014-nnl base 60f75b2): an undeclared manifest must
# keep hashing byte for byte.
BASE_HASH = "567af7e5924dfe6c79f976858b95566e7020055e2d220ec16f4f55940280b806"


def reef_settlement(**overrides: Any) -> TerminalSettlement:
    fields: dict[str, Any] = {
        "symbol": REEF,
        "kind": TERMINAL_KIND_BOUNDED_BY_INDEX_KLINES,
        "recorded_evaluation": TERMINAL_EVALUATION_UNION_ADVERSE_BOUND,
        "bound_window_start_utc": WINDOW_START,
        "samples_per_minute": 60,
        "nominal_lower": "5123/6000000",
        "nominal_upper": "347/400000",
        "price_tick_size": TICK,
        "index_lower": D("0.000852"),
        "index_upper": D("0.000869"),
        "trade_candle_low": D("0.000845"),
        "trade_candle_high": D("0.000887"),
        "price_lower": D("0.000845"),
        "price_upper": D("0.000887"),
        "index_klines": EvidenceFile(INDEX_PATH, INDEX_SHA),
        "trade_kline": EvidenceFile(TRADE_PATH, TRADE_SHA),
        "supporting_evidence": (EvidenceFile(SUPPORT_PATH, SUPPORT_SHA),),
        "condition": CONDITION,
        "official_confirmation": None,
    }
    fields.update(overrides)
    return TerminalSettlement(**fields)


def reef_declaration(terminal: datetime = TERMINAL) -> TerminalDeclaration:
    return TerminalDeclaration(
        symbol=REEF, reason="DELISTED_CAPPED", terminal_at_utc=terminal, source_url=REEF_URL
    )


def make_manifest(**overrides: Any) -> DatasetManifest:
    fields: dict[str, Any] = {
        "universe_id": "research-universe-v1",
        "symbols": (BTC, REEF),
        "dataset_id": "1" * 64,
        "development_start_utc": DEV_START,
        "development_end_utc": VAL_START,
        "validation_start_utc": VAL_START,
        "validation_end_utc": VAL_END,
        "holdout_start_utc": VAL_END,
        "holdout_end_utc": HOLD_END,
        "strategy_interval": "1h",
        "context_interval": "4h",
        "data_source": "binance-usdm-public",
        "data_source_version": "test-1",
        "excluded_periods": (),
        "known_gaps": (reef_declaration(),),
        "equity": D("1000"),
        "risk_rate": D("0.005"),
        "constraint_source": "constraints.json",
        "constraint_sha256": "2" * 64,
    }
    fields.update(overrides)
    return DatasetManifest(**fields)


def with_settlement(**row_overrides: Any) -> DatasetManifest:
    return make_manifest(terminal_settlements=(reef_settlement(**row_overrides),))


def shifted_terminal_manifest(terminal: datetime) -> DatasetManifest:
    """A REEF row whose declaration T is `terminal`, the bound window the 30 minutes before."""
    return make_manifest(
        known_gaps=(reef_declaration(terminal),),
        terminal_settlements=(
            reef_settlement(bound_window_start_utc=terminal - timedelta(minutes=30)),
        ),
    )


# --------------------------------------------------------------------------- #
# Canonical omission: an undeclared manifest hashes exactly as before.
# --------------------------------------------------------------------------- #


def test_manifest_without_settlements_hashes_exactly_as_before() -> None:
    manifest = make_manifest()
    assert manifest.terminal_settlements == ()
    canonical = manifest.canonical()
    assert "terminal_settlements" not in canonical
    assert manifest_hash(manifest) == sha256_hex(canonical)
    assert manifest_hash(manifest) == BASE_HASH
    expected_keys = {
        "universe_id",
        "symbols",
        "dataset_id",
        "development_start_utc",
        "development_end_utc",
        "validation_start_utc",
        "validation_end_utc",
        "holdout_start_utc",
        "holdout_end_utc",
        "strategy_interval",
        "context_interval",
        "data_source",
        "data_source_version",
        "excluded_periods",
        "known_gaps",
        "equity",
        "risk_rate",
        "constraint_source",
        "constraint_sha256",
    }
    assert set(canonical) == expected_keys


def test_an_explicit_empty_tuple_is_the_same_as_the_default() -> None:
    assert manifest_hash(make_manifest(terminal_settlements=())) == BASE_HASH


# --------------------------------------------------------------------------- #
# The REEF row is accepted and sits inside the hash.
# --------------------------------------------------------------------------- #


def test_reef_settlement_row_is_accepted_and_changes_the_hash() -> None:
    manifest = with_settlement()
    assert manifest_hash(manifest) != BASE_HASH
    row = canonical_scalars(manifest.canonical()["terminal_settlements"])
    assert len(row) == 1
    assert row[0] == {
        "symbol": REEF,
        "kind": "BOUNDED_BY_INDEX_KLINES",
        "recorded_evaluation": "UNION_ADVERSE_BOUND",
        "bound_window_start_utc": "2025-01-22T08:30:00+00:00",
        "samples_per_minute": 60,
        "nominal_lower": "5123/6000000",
        "nominal_upper": "347/400000",
        "price_tick_size": "0.000001",
        "index_lower": "0.000852",
        "index_upper": "0.000869",
        "trade_candle_low": "0.000845",
        "trade_candle_high": "0.000887",
        "price_lower": "0.000845",
        "price_upper": "0.000887",
        "index_klines": {"path": INDEX_PATH, "sha256": INDEX_SHA},
        "trade_kline": {"path": TRADE_PATH, "sha256": TRADE_SHA},
        "supporting_evidence": [{"path": SUPPORT_PATH, "sha256": SUPPORT_SHA}],
        "condition": CONDITION,
        "official_confirmation": None,
    }
    assert manifest_hash(with_settlement()) == manifest_hash(manifest)


def test_the_rest_of_the_canonical_form_is_unchanged_by_a_settlement() -> None:
    plain = make_manifest().canonical()
    declared = with_settlement().canonical()
    assert declared.pop("terminal_settlements")
    assert declared == plain


@pytest.mark.parametrize(
    "change",
    [
        {"condition": CONDITION + " (edited)"},
        {"bound_window_start_utc": datetime(2025, 1, 22, 8, 0, tzinfo=UTC)},
        {"index_klines": EvidenceFile(INDEX_PATH, "9" * 64)},
        {"index_klines": EvidenceFile(f"{EVIDENCE_DIR}/other.body.json", INDEX_SHA)},
        {"trade_kline": EvidenceFile(TRADE_PATH, "9" * 64)},
        {"supporting_evidence": ()},
        {"supporting_evidence": (EvidenceFile(SUPPORT_PATH, "9" * 64),)},
        {
            "supporting_evidence": (
                EvidenceFile(f"{EVIDENCE_DIR}/A_other.json", "8" * 64),
                EvidenceFile(SUPPORT_PATH, SUPPORT_SHA),
            )
        },
    ],
)
def test_every_field_change_moves_the_hash(change: dict[str, Any]) -> None:
    assert manifest_hash(with_settlement(**change)) != manifest_hash(with_settlement())


def test_the_declared_terminal_moves_the_hash_of_a_settlement_manifest() -> None:
    later = datetime(2025, 1, 22, 10, 0, tzinfo=UTC)
    moved = make_manifest(
        known_gaps=(reef_declaration(later),),
        terminal_settlements=(reef_settlement(),),
    )
    assert manifest_hash(moved) != manifest_hash(with_settlement())


# --------------------------------------------------------------------------- #
# Design test 2: the guard against Validation and Holdout (T3-09).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "terminal",
    [
        VAL_START,
        datetime(2025, 2, 10, 9, 0, tzinfo=UTC),
        datetime(2025, 2, 28, 23, 59, tzinfo=UTC),
        VAL_END,
        datetime(2025, 3, 10, 9, 0, tzinfo=UTC),
        HOLD_END,
        datetime(2025, 6, 1, 9, 0, tzinfo=UTC),
    ],
    ids=[
        "equals_validation_start",
        "inside_validation",
        "last_validation_minute",
        "equals_holdout_start",
        "inside_holdout",
        "equals_holdout_end",
        "after_holdout",
    ],
)
def test_settlement_at_or_after_validation_start_is_refused(terminal: datetime) -> None:
    with pytest.raises(ManifestError, match="Validation or Holdout"):
        shifted_terminal_manifest(terminal)


def test_the_last_development_minute_is_still_accepted() -> None:
    manifest = shifted_terminal_manifest(VAL_START - timedelta(minutes=1))
    assert len(manifest.terminal_settlements) == 1


@pytest.mark.parametrize(
    "terminal",
    [DEV_START, datetime(2024, 12, 31, 9, 0, tzinfo=UTC)],
    ids=["equals_development_start", "before_development_start"],
)
def test_settlement_at_or_before_development_start_is_refused(terminal: datetime) -> None:
    with pytest.raises(ManifestError, match="development_start_utc"):
        shifted_terminal_manifest(terminal)


# --------------------------------------------------------------------------- #
# Cross-validation against the known_gaps declaration.
# --------------------------------------------------------------------------- #


def test_settlement_needs_a_known_gap_declaration_for_its_symbol() -> None:
    with pytest.raises(ManifestError, match="known_gaps"):
        make_manifest(known_gaps=(), terminal_settlements=(reef_settlement(),))
    other = TerminalDeclaration(BTC, "DELISTED_CAPPED", TERMINAL, REEF_URL)
    with pytest.raises(ManifestError, match="known_gaps"):
        make_manifest(known_gaps=(other,), terminal_settlements=(reef_settlement(),))


def test_a_settlement_for_a_symbol_outside_the_universe_is_refused() -> None:
    with pytest.raises(ManifestError):
        make_manifest(symbols=(BTC,), known_gaps=(), terminal_settlements=(reef_settlement(),))


def test_one_settlement_per_symbol() -> None:
    twin = reef_settlement(condition=CONDITION + " second")
    with pytest.raises(ManifestError, match="more than one"):
        make_manifest(terminal_settlements=(reef_settlement(), twin))


def test_only_terminal_settlement_instances_are_accepted() -> None:
    with pytest.raises(ManifestError, match="TerminalSettlement"):
        make_manifest(terminal_settlements=({"symbol": REEF},))


@pytest.mark.parametrize(
    "start",
    [
        TERMINAL,
        TERMINAL + timedelta(minutes=1),
        datetime(2025, 1, 22, 8, 30, 30, tzinfo=UTC),
        datetime(2025, 1, 22, 8, 30, 0, 1, tzinfo=UTC),
        datetime(2025, 1, 22, 8, 30),
        datetime(2025, 1, 22, 15, 30, tzinfo=PLUS7),
    ],
    ids=["equals_T", "after_T", "seconds", "microseconds", "naive", "non_utc_offset"],
)
def test_bound_window_must_end_before_the_declared_terminal_in_whole_minutes(
    start: datetime,
) -> None:
    with pytest.raises(ManifestError, match="bound_window_start_utc"):
        with_settlement(bound_window_start_utc=start)


def test_terminal_must_be_minute_aligned() -> None:
    odd = datetime(2025, 1, 22, 9, 0, 30, tzinfo=UTC)
    with pytest.raises(ManifestError, match="minute-aligned"):
        make_manifest(
            known_gaps=(reef_declaration(odd),), terminal_settlements=(reef_settlement(),)
        )


# --------------------------------------------------------------------------- #
# Stored bounds follow the tick-widening and union rule.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("field", ["index_lower", "index_upper", "price_lower", "price_upper"])
@pytest.mark.parametrize("sign", [1, -1], ids=["plus_one_tick", "minus_one_tick"])
def test_stored_bounds_must_follow_the_tick_and_union_rule(field: str, sign: int) -> None:
    value = getattr(reef_settlement(), field) + sign * TICK
    with pytest.raises(ManifestError, match=field):
        with_settlement(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("trade_candle_low", D("0.000850")),
        ("trade_candle_high", D("0.000860")),
        ("trade_candle_low", D("0.000900")),
    ],
)
def test_the_union_must_use_the_stored_trade_candle(field: str, value: Decimal) -> None:
    with pytest.raises(ManifestError):
        with_settlement(**{field: value})


def test_a_different_tick_breaks_the_widening_rule() -> None:
    with pytest.raises(ManifestError, match="index_lower"):
        with_settlement(price_tick_size=D("0.0000001"))


def test_bounds_off_the_tick_grid_are_refused() -> None:
    with pytest.raises(ManifestError, match="tick"):
        with_settlement(
            price_tick_size=D("0.000002"),
            index_lower=D("0.000852"),
            index_upper=D("0.000869"),
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"price_lower": D("0.00085"), "trade_candle_low": D("0.00085")},
        {"price_upper": D("0.000869"), "trade_candle_high": D("0.000869")},
    ],
)
def test_the_stored_union_cannot_hide_a_wider_index_bound(overrides: dict[str, Any]) -> None:
    with pytest.raises(ManifestError):
        with_settlement(**overrides)


# --------------------------------------------------------------------------- #
# Canonical decimal text and reduced fractions.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("price_lower", D("0.00084500")),
        ("price_upper", D("0.0008870")),
        ("index_lower", D("0.00085200")),
        ("index_upper", D("0.000869000")),
        ("trade_candle_low", D("0.00084500")),
        ("trade_candle_high", D("0.00088700")),
        ("price_tick_size", D("0.0000010")),
    ],
)
def test_bounds_must_be_canonical_decimal_text(field: str, value: Decimal) -> None:
    assert value == getattr(reef_settlement(), field)  # the same number, a longer spelling
    with pytest.raises(ManifestError, match="canonical"):
        with_settlement(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("nominal_lower", "10246/12000000"),
        ("nominal_upper", "694/800000"),
        ("nominal_lower", "05123/6000000"),
        ("nominal_lower", "+5123/6000000"),
        ("nominal_lower", " 5123/6000000"),
        ("nominal_lower", "5123/0"),
        ("nominal_lower", "0.000853833"),
        ("nominal_lower", ""),
    ],
)
def test_fractions_must_be_reduced_p_over_q_text(field: str, value: str) -> None:
    with pytest.raises(ManifestError, match=field):
        with_settlement(**{field: value})


def test_a_fraction_object_or_a_float_is_not_a_manifest_value() -> None:
    with pytest.raises(ManifestError, match="nominal_lower"):
        with_settlement(nominal_lower=Fraction(5123, 6000000))
    with pytest.raises(ManifestError, match="nominal_upper"):
        with_settlement(nominal_upper=0.000867)
    with pytest.raises(ManifestError, match="price_lower"):
        with_settlement(price_lower=0.000845)


@pytest.mark.parametrize("bad", [D("NaN"), D("Infinity"), D("0"), D("-0.000845")])
def test_non_finite_or_non_positive_prices_are_refused(bad: Decimal) -> None:
    with pytest.raises(ManifestError, match="price_lower"):
        with_settlement(price_lower=bad)


def test_price_lower_must_be_below_price_upper() -> None:
    with pytest.raises(ManifestError):
        with_settlement(price_upper=D("0.000845"), trade_candle_high=D("0.000845"))


# --------------------------------------------------------------------------- #
# Evidence paths and hashes.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path",
    [
        "/etc/evidence.json",
        "C:/evidence/B.json",
        "C:\\evidence\\B.json",
        "docs\\research\\B.json",
        "../outside/B.json",
        "docs/../../outside/B.json",
        "docs//B.json",
        "./docs/B.json",
        "docs/B.json/",
        "",
    ],
)
def test_evidence_path_must_be_posix_relative_and_clean(path: str) -> None:
    with pytest.raises(ManifestError, match="path"):
        with_settlement(index_klines=EvidenceFile(path, INDEX_SHA))
    with pytest.raises(ManifestError, match="path"):
        with_settlement(trade_kline=EvidenceFile(path, TRADE_SHA))
    with pytest.raises(ManifestError, match="path"):
        with_settlement(supporting_evidence=(EvidenceFile(path, SUPPORT_SHA),))


@pytest.mark.parametrize("digest", ["", "A" * 64, "1" * 63, "1" * 65, "g" * 64])
def test_evidence_sha256_must_be_lowercase_hex64(digest: str) -> None:
    with pytest.raises(ManifestError, match="sha256"):
        with_settlement(index_klines=EvidenceFile(INDEX_PATH, digest))


def test_supporting_evidence_must_be_sorted_by_path_and_unique() -> None:
    first = EvidenceFile(f"{EVIDENCE_DIR}/A_other.json", "8" * 64)
    second = EvidenceFile(SUPPORT_PATH, SUPPORT_SHA)
    assert with_settlement(supporting_evidence=(first, second)).terminal_settlements
    with pytest.raises(ManifestError, match="sorted"):
        with_settlement(supporting_evidence=(second, first))
    with pytest.raises(ManifestError, match="unique"):
        with_settlement(supporting_evidence=(second, second))
    with pytest.raises(ManifestError, match="unique"):
        with_settlement(supporting_evidence=(first, EvidenceFile(first.path, "7" * 64)))


def test_supporting_evidence_must_be_a_tuple_of_evidence_files() -> None:
    with pytest.raises(ManifestError, match="supporting_evidence"):
        with_settlement(supporting_evidence=[EvidenceFile(SUPPORT_PATH, SUPPORT_SHA)])
    with pytest.raises(ManifestError, match="supporting_evidence"):
        with_settlement(supporting_evidence=({"path": SUPPORT_PATH, "sha256": SUPPORT_SHA},))
    with pytest.raises(ManifestError, match="index_klines"):
        with_settlement(index_klines={"path": INDEX_PATH, "sha256": INDEX_SHA})


# --------------------------------------------------------------------------- #
# Closed vocabulary, confirmation and condition.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "confirmation", ["https://www.binance.com/x", True, False, 0, "", {"url": "x"}, ["x"]]
)
def test_official_confirmation_must_be_null(confirmation: Any) -> None:
    with pytest.raises(ManifestError, match="official_confirmation"):
        with_settlement(official_confirmation=confirmation)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "OTHER"),
        ("kind", "bounded_by_index_klines"),
        ("kind", ""),
        ("recorded_evaluation", "INDEX_CONDITIONAL"),
        ("recorded_evaluation", ""),
    ],
)
def test_vocabulary_is_closed(field: str, value: str) -> None:
    with pytest.raises(ManifestError, match=field):
        with_settlement(**{field: value})


@pytest.mark.parametrize("value", [59, 61, 0, True, False, 60.0, "60", None])
def test_samples_per_minute_is_the_int_60(value: Any) -> None:
    with pytest.raises(ManifestError, match="samples_per_minute"):
        with_settlement(samples_per_minute=value)


@pytest.mark.parametrize("value", ["", "   ", None, 5])
def test_condition_is_a_non_empty_string(value: Any) -> None:
    with pytest.raises(ManifestError, match="condition"):
        with_settlement(condition=value)


def test_the_tick_must_be_a_positive_finite_decimal() -> None:
    for bad in (D("0"), D("-0.000001"), D("NaN"), 0.000001, "0.000001"):
        with pytest.raises(ManifestError, match="price_tick_size"):
            with_settlement(price_tick_size=bad)


# --------------------------------------------------------------------------- #
# Loader: the optional key, strict row keys, no floats, the same hash after a round trip.
# --------------------------------------------------------------------------- #


def settlement_row_json(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "symbol": REEF,
        "kind": "BOUNDED_BY_INDEX_KLINES",
        "recorded_evaluation": "UNION_ADVERSE_BOUND",
        "bound_window_start_utc": "2025-01-22T08:30:00Z",
        "samples_per_minute": 60,
        "nominal_lower": "5123/6000000",
        "nominal_upper": "347/400000",
        "price_tick_size": "0.000001",
        "index_lower": "0.000852",
        "index_upper": "0.000869",
        "trade_candle_low": "0.000845",
        "trade_candle_high": "0.000887",
        "price_lower": "0.000845",
        "price_upper": "0.000887",
        "index_klines": {"path": INDEX_PATH, "sha256": INDEX_SHA},
        "trade_kline": {"path": TRADE_PATH, "sha256": TRADE_SHA},
        "supporting_evidence": [{"path": SUPPORT_PATH, "sha256": SUPPORT_SHA}],
        "condition": CONDITION,
        "official_confirmation": None,
    }
    row.update(overrides)
    return row


def manifest_payload(rows: list[Any] | None = None, *, key: bool = True) -> dict[str, Any]:
    payload = kg._payload(
        symbols=[BTC, REEF],
        development_start_utc="2025-01-01T00:00:00Z",
        development_end_utc="2025-02-01T00:00:00Z",
        validation_start_utc="2025-02-01T00:00:00Z",
        validation_end_utc="2025-03-01T00:00:00Z",
        holdout_start_utc="2025-03-01T00:00:00Z",
        holdout_end_utc="2025-04-01T00:00:00Z",
        known_gaps=[
            kg._declaration_row(
                symbol=REEF, terminal_at_utc="2025-01-22T09:00:00Z", source_url=REEF_URL
            )
        ],
        dataset_id="1" * 64,
        constraint_sha256="2" * 64,
        constraint_source="constraints.json",
    )
    if key:
        payload["terminal_settlements"] = [settlement_row_json()] if rows is None else rows
    return payload


def test_loader_accepts_the_optional_key(tmp_path: Path) -> None:
    loaded = load_manifest(kg._write(tmp_path, manifest_payload()))
    assert loaded.terminal_settlements == (reef_settlement(),)


def test_loader_without_the_key_matches_a_manifest_without_settlements(tmp_path: Path) -> None:
    loaded = load_manifest(kg._write(tmp_path, manifest_payload(key=False)))
    assert loaded.terminal_settlements == ()
    assert manifest_hash(loaded) == BASE_HASH


def test_loader_round_trips_to_the_same_hash(tmp_path: Path) -> None:
    loaded = load_manifest(kg._write(tmp_path, manifest_payload()))
    assert manifest_hash(loaded) == manifest_hash(with_settlement())
    assert loaded.canonical() == with_settlement().canonical()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.update(extra="x"),
        lambda row: row.pop("condition"),
        lambda row: row.pop("official_confirmation"),
        lambda row: row.pop("trade_kline"),
        lambda row: row.pop("supporting_evidence"),
        lambda row: row.update(T="2025-01-22T09:00:00Z"),
        lambda row: row.update(index_klines={"path": INDEX_PATH}),
        lambda row: row.update(
            index_klines={"path": INDEX_PATH, "sha256": INDEX_SHA, "extra": "x"}
        ),
        lambda row: row.update(supporting_evidence=[{"path": SUPPORT_PATH}]),
    ],
    ids=[
        "unknown_key",
        "missing_condition",
        "missing_confirmation",
        "missing_trade_kline",
        "missing_supporting",
        "extra_terminal_key",
        "evidence_missing_sha",
        "evidence_extra_key",
        "supporting_missing_sha",
    ],
)
def test_loader_refuses_unknown_or_missing_row_keys(tmp_path: Path, mutation: Any) -> None:
    row = settlement_row_json()
    mutation(row)
    with pytest.raises(ManifestError):
        load_manifest(kg._write(tmp_path, manifest_payload([row])))


def test_loader_refuses_float_numbers_in_a_settlement_row(tmp_path: Path) -> None:
    for key, value in (
        ("samples_per_minute", 60.0),
        ("price_lower", 0.000845),
        ("nominal_lower", 0.000853833),
        ("price_tick_size", 1e-06),
    ):
        path = kg._write(tmp_path, manifest_payload([settlement_row_json(**{key: value})]))
        with pytest.raises(ManifestError):
            load_manifest(path)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("samples_per_minute", True),
        ("samples_per_minute", "60"),
        ("price_lower", 845),
        ("index_lower", None),
        ("symbol", 5),
        ("kind", None),
        ("condition", ["x"]),
        ("bound_window_start_utc", "2025-01-22T08:30:00"),
        ("bound_window_start_utc", "2025-01-22T15:30:00+07:00"),
        ("bound_window_start_utc", "not-a-time"),
        ("price_lower", "abc"),
        ("official_confirmation", "https://www.binance.com/x"),
    ],
)
def test_loader_refuses_wrong_types_and_values_in_a_settlement_row(
    tmp_path: Path, key: str, value: Any
) -> None:
    path = kg._write(tmp_path, manifest_payload([settlement_row_json(**{key: value})]))
    with pytest.raises(ManifestError):
        load_manifest(path)


@pytest.mark.parametrize("rows", [[], {}, "x", None, [5], [[]]])
def test_loader_refuses_a_bad_settlement_list(tmp_path: Path, rows: Any) -> None:
    with pytest.raises(ManifestError):
        load_manifest(kg._write(tmp_path, manifest_payload(rows)))


def test_loader_still_refuses_an_unknown_top_level_key(tmp_path: Path) -> None:
    payload = manifest_payload()
    payload["terminal_settlement"] = []
    with pytest.raises(ManifestError, match="unknown keys"):
        load_manifest(kg._write(tmp_path, payload))


def test_loader_applies_the_guard_and_the_cross_validation(tmp_path: Path) -> None:
    late = manifest_payload()
    late["known_gaps"] = [
        kg._declaration_row(
            symbol=REEF, terminal_at_utc="2025-02-10T09:00:00Z", source_url=REEF_URL
        )
    ]
    with pytest.raises(ManifestError, match="Validation or Holdout"):
        load_manifest(kg._write(tmp_path, late))
    bare = manifest_payload()
    bare["known_gaps"] = []
    with pytest.raises(ManifestError, match="known_gaps"):
        load_manifest(kg._write(tmp_path, bare, "bare.json"))


def test_loader_wraps_a_recompute_mismatch_as_a_manifest_error(tmp_path: Path) -> None:
    row = settlement_row_json(index_lower="0.000853")
    with pytest.raises(ManifestError, match="index_lower"):
        load_manifest(kg._write(tmp_path, manifest_payload([row])))


def test_a_settlement_dataclass_keeps_the_declaration_untouched() -> None:
    fields = [f.name for f in dataclasses.fields(TerminalDeclaration)]
    assert fields == ["symbol", "reason", "terminal_at_utc", "source_url"]
