"""Tests for the terminal declaration of a manifest known gap (Phase 16, plan 16-54).

The recorded user decisions (decisions/16-DEC-GAP-REASON.md) are KG-1 DELISTED_CAPPED (the one
reason, required), KG-2 wrapper (a declaration is its own entry type, GapRange untouched, no
version key), KG-3 declaration-and-geometry (one declaration per symbol; a gap is accepted only
when it is a trailing hole that follows the data geometry) and KG-4 inline with the single source
host www.binance.com (nothing is fetched).

Every store is synthetic and written through the real publishers. The symbol DELISTUSDT stands for
a REEFUSDT-shaped symbol: its series stop before the end of the range, the last day partial (the
08:00 4h bar and the 08:00 funding instant exist, the next missing slot of those two is 12:00).
No real REEFUSDT value is used: the terminal time, the symbol and the URL are all synthetic.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_usdm import FundingTick
from src.data import case_input as ci
from src.data.collector import _write_funding_tick
from src.data.coverage import GapRange
from src.data.store import publish_batch, publish_mark_batch
from src.research import manifest as mf
from src.research import run as research_run

from tests import test_case_input_builder as tb

LONG = "BTCUSDT"
TERM = "DELISTUSDT"
OTHER_TERM = "GONEUSDT"
STORE_START = datetime(2026, 3, 1, tzinfo=UTC)
DEV_END = datetime(2026, 3, 9, tzinfo=UTC)
VAL_END = datetime(2026, 3, 17, tzinfo=UTC)
HOLD_END = datetime(2026, 3, 19, tzinfo=UTC)
CUT = datetime(2026, 3, 4, 9, tzinfo=UTC)  # first instant of the term symbol that is not published
TERMINAL_AT = CUT
SOURCE_URL = "https://www.binance.com/synthetic/test-only-terminal-notice"
REASON = "DELISTED_CAPPED"
LAST_DAY = datetime(2026, 3, 4, tzinfo=UTC)  # the partial last day of the term symbol
HOUR = timedelta(hours=1)


def _publish_terminal_symbol(root: Path, symbol: str, start: datetime, cut: datetime) -> None:
    """Publish `symbol` from `start` up to (excluding) `cut`: a partial last day, 4h funding."""
    for interval in ("1h", "4h", "1m"):
        publish_batch(
            [tb._kline(interval, ms, symbol) for ms in tb._slots(start, cut, interval)],
            interval=interval,
            symbol=symbol,
            raw_root=root,
        )
    publish_mark_batch(
        [tb._mark(ms, symbol) for ms in tb._slots(start, cut, "1m")],
        interval="1m",
        symbol=symbol,
        raw_root=root,
    )
    for ms in range(tb._ms(start), tb._ms(cut), 4 * 3_600_000):
        _write_funding_tick(
            FundingTick(
                symbol=symbol,
                funding_time_utc=tb._from_ms(ms),
                funding_rate=Decimal("0.0001"),
                mark_price=Decimal("100.50"),
            ),
            root,
        )


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A long-history symbol over the research window and a REEFUSDT-shaped symbol."""
    root = tmp_path_factory.mktemp("known_gap_reason_store") / "raw"
    tb.build_store(root, start=STORE_START, end=VAL_END, symbols=(LONG,))
    _publish_terminal_symbol(root, TERM, STORE_START, CUT)
    return root


def _declaration_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "symbol": TERM,
        "reason": REASON,
        "terminal_at_utc": "2026-03-04T09:00:00Z",
        "source_url": SOURCE_URL,
    }
    row.update(overrides)
    return row


def _payload(
    *, known_gaps: list[Any] | None = None, dataset_id: str = "0" * 64, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "universe_id": "research-universe-v1",
        "symbols": [LONG, TERM],
        "dataset_id": dataset_id,
        "development_start_utc": "2026-03-01T00:00:00Z",
        "development_end_utc": "2026-03-09T00:00:00Z",
        "validation_start_utc": "2026-03-09T00:00:00Z",
        "validation_end_utc": "2026-03-17T00:00:00Z",
        "holdout_start_utc": "2026-03-17T00:00:00Z",
        "holdout_end_utc": "2026-03-19T00:00:00Z",
        "strategy_interval": "1h",
        "context_interval": "4h",
        "data_source": "binance-usdm-public",
        "data_source_version": "test-1",
        "excluded_periods": [],
        "known_gaps": [_declaration_row()] if known_gaps is None else known_gaps,
        "equity": "1000",
        "risk_rate": "0.005",
        "constraint_source": "constraints.json",
        "constraint_sha256": "1" * 64,
    }
    payload.update(overrides)
    return payload


def _write(directory: Path, payload: dict[str, Any], name: str = "manifest.json") -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _gap(
    series: str,
    interval: str,
    start: datetime,
    end: datetime,
    missing: int,
    symbol: str = TERM,
) -> GapRange:
    return GapRange(
        series=series,
        symbol=symbol,
        interval=interval,
        start_utc=start,
        end_utc=end,
        missing=missing,
    )


def _terminal_holes(end: datetime, *, last_day: datetime = LAST_DAY) -> list[GapRange]:
    """The five trailing holes of the term symbol up to `end`, from the data geometry by hand.

    The 1h and 1m series stop at 08:xx (first missing slot 09:00), the 4h bar and the 4h funding
    stop at 08:00 (first missing slot 12:00). Counts are hours converted by hand, not read from
    the code under test.
    """
    one_h_start = last_day + 9 * HOUR
    four_h_start = last_day + 12 * HOUR
    hours_1h = (end - one_h_start) // HOUR
    hours_4h = (end - four_h_start) // HOUR
    return [
        _gap("trade", "1h", one_h_start, end, hours_1h),
        _gap("trade", "4h", four_h_start, end, hours_4h // 4),
        _gap("intrabar_1m", "1m", one_h_start, end, hours_1h * 60),
        _gap("mark_1m", "1m", one_h_start, end, hours_1h * 60),
        _gap("funding", "4h", four_h_start, end, hours_4h // 4),
    ]


def _build(raw_root: Path, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "symbols": [LONG, TERM],
        "start_utc": STORE_START,
        "end_utc": VAL_END,
        "as_of_day_utc": VAL_END.date(),
        "series": ci.ENGINE_SERIES,
    }
    kwargs.update(overrides)
    return ci.build_case_input_data(raw_root, **kwargs)


# --------------------------------------------------------------------------- #
# Task 5 - tracer.
# --------------------------------------------------------------------------- #


def test_tracer_manifest_file_is_loaded_hashed_and_acknowledged(
    store: Path, tmp_path: Path
) -> None:
    first = mf.load_manifest(_write(tmp_path, _payload()))
    assert len(first.known_gaps) == 1
    declaration = first.known_gaps[0]
    assert declaration.symbol == TERM
    assert declaration.reason == REASON
    assert declaration.terminal_at_utc == TERMINAL_AT
    assert declaration.source_url == SOURCE_URL

    dataset_id = _build(store, terminal_declarations=first.known_gaps).dataset_id
    manifest = mf.load_manifest(_write(tmp_path, _payload(dataset_id=dataset_id), "real.json"))
    digest = mf.manifest_hash(manifest)
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)

    # The pre-flight of the runner runs without CaseInputGapError ...
    research_run._check_manifest_against_store(manifest, store)
    # ... and acknowledges exactly the five trailing holes of the term symbol, none of the other.
    data = _build(store, terminal_declarations=manifest.known_gaps)
    assert list(data.allowed_gaps) == _terminal_holes(VAL_END)
    assert {g.symbol for g in data.allowed_gaps} == {TERM}


def test_without_a_declaration_the_same_holes_still_raise(store: Path) -> None:
    with pytest.raises(ci.CaseInputGapError) as excinfo:
        _build(store)
    assert list(excinfo.value.gaps) == _terminal_holes(VAL_END)


def _decl(**overrides: Any) -> Any:
    fields: dict[str, Any] = {
        "symbol": TERM,
        "reason": REASON,
        "terminal_at_utc": TERMINAL_AT,
        "source_url": SOURCE_URL,
    }
    fields.update(overrides)
    return ci.TerminalDeclaration(**fields)


@pytest.mark.parametrize(
    ("override", "refused", "message"),
    [
        # A declaration for another symbol acknowledges nothing of the term symbol.
        ({"symbol": LONG}, _terminal_holes(VAL_END), None),
        # The terminal time is after the first missing slot of the 1h and 1m series (09:00).
        (
            {"terminal_at_utc": datetime(2026, 3, 4, 10, tzinfo=UTC)},
            [g for g in _terminal_holes(VAL_END) if g.series != "funding" and g.interval != "4h"],
            "terminal timestamp is after",
        ),
        # The terminal time is after the first missing slot of every series (09:00 and 12:00).
        (
            {"terminal_at_utc": datetime(2026, 3, 4, 12, 30, tzinfo=UTC)},
            _terminal_holes(VAL_END),
            "terminal timestamp is after",
        ),
    ],
)
def test_a_mismatching_declaration_leaves_the_holes_unacknowledged(
    store: Path, override: dict[str, Any], refused: list[GapRange], message: str | None
) -> None:
    with pytest.raises(ci.CaseInputGapError) as excinfo:
        _build(store, terminal_declarations=(_decl(**override),))
    assert list(excinfo.value.gaps) == refused
    if message is not None:
        assert message in str(excinfo.value)


def test_the_hash_binds_the_terminal_fields(tmp_path: Path) -> None:
    base = mf.manifest_hash(mf.load_manifest(_write(tmp_path, _payload(), "a.json")))
    again = mf.manifest_hash(mf.load_manifest(_write(tmp_path, _payload(), "b.json")))
    assert base == again
    for override in (
        {"terminal_at_utc": "2026-03-04T08:30:00Z"},
        {"source_url": "https://www.binance.com/synthetic/another-notice"},
        {"symbol": LONG},
    ):
        row = _declaration_row(**override)
        changed = mf.manifest_hash(
            mf.load_manifest(_write(tmp_path, _payload(known_gaps=[row]), "c.json"))
        )
        assert changed != base, override
    # The reason is inside the canonical form that the hash covers.
    manifest = mf.load_manifest(_write(tmp_path, _payload(), "d.json"))
    assert manifest.canonical()["known_gaps"][0]["reason"] == REASON


@pytest.mark.parametrize(
    "row",
    [
        _declaration_row(reason="TERMINAL"),
        _declaration_row(reason="DATA_LOSS"),
        _declaration_row(reason="delisted_capped"),
        _declaration_row(extra_key="x"),
        _declaration_row(source_url="http://www.binance.com/synthetic/notice"),
        _declaration_row(source_url="https://example.invalid/synthetic/notice"),
        _declaration_row(source_url="https://user:secret@www.binance.com/synthetic/notice"),
        _declaration_row(source_url="https://www.binance.com/synthetic notice"),
        {k: v for k, v in _declaration_row().items() if k != "reason"},
    ],
)
def test_the_loader_refuses_a_malformed_declaration(tmp_path: Path, row: dict[str, Any]) -> None:
    with pytest.raises(mf.ManifestError) as excinfo:
        mf.load_manifest(_write(tmp_path, _payload(known_gaps=[row])))
    assert "secret" not in str(excinfo.value)
    assert "example.invalid" not in str(excinfo.value)


def test_the_closed_top_level_key_set_still_refuses_an_unknown_key(tmp_path: Path) -> None:
    with pytest.raises(mf.ManifestError):
        mf.load_manifest(_write(tmp_path, _payload(manifest_schema="1")))


# --------------------------------------------------------------------------- #
# Task 6 - expansion.
# --------------------------------------------------------------------------- #

DAY1 = datetime(2026, 3, 1, tzinfo=UTC)
DAY2 = datetime(2026, 3, 2, tzinfo=UTC)
DAY3 = datetime(2026, 3, 3, tzinfo=UTC)
SMALL_CUT = datetime(2026, 3, 2, 9, tzinfo=UTC)  # the term symbol stops on day 2 at 09:00
INTERIOR_HOUR = datetime(2026, 3, 1, 10, tzinfo=UTC)


def _interior_gap() -> GapRange:
    return _gap("intrabar_1m", "1m", INTERIOR_HOUR, INTERIOR_HOUR + HOUR, 60, symbol=LONG)


@pytest.fixture
def small_store(tmp_path: Path) -> Path:
    """Two days: a long-history symbol with an interior 1m hole, and a term symbol cut on day 2."""
    root = tmp_path / "raw"
    tb.build_store(root, start=DAY1, end=DAY3, skip_1m_hour=INTERIOR_HOUR, symbols=(LONG,))
    _publish_terminal_symbol(root, TERM, DAY1, SMALL_CUT)
    return root


def _build_small(root: Path, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {"start_utc": DAY1, "end_utc": DAY3, "as_of_day_utc": DAY3.date()}
    kwargs.update(overrides)
    return _build(root, **kwargs)


def test_an_interior_gap_is_never_covered_by_a_declaration(small_store: Path) -> None:
    # The declaration for the long-history symbol starts exactly at the hole (terminal <= gap
    # start), yet an interior hole is data followed by data: it is not acknowledged.
    declarations = (
        _decl(symbol=LONG, terminal_at_utc=INTERIOR_HOUR),
        _decl(terminal_at_utc=SMALL_CUT),
    )
    with pytest.raises(ci.CaseInputGapError) as excinfo:
        _build_small(small_store, terminal_declarations=declarations)
    assert list(excinfo.value.gaps) == [_interior_gap()]
    assert "not trailing" in str(excinfo.value)
    # The same hole with an exact data-loss entry is acknowledged, exactly as before; the
    # declared holes of the term symbol come along, in gap order.
    data = _build_small(
        small_store, terminal_declarations=declarations, allow_gaps=(_interior_gap(),)
    )
    assert list(data.allowed_gaps) == [_interior_gap(), *_terminal_holes(DAY3, last_day=DAY2)]


def test_terminal_stated_after_the_hole_starts_is_refused_and_names_the_condition(
    small_store: Path,
) -> None:
    after = _decl(terminal_at_utc=SMALL_CUT + HOUR)
    with pytest.raises(ci.CaseInputGapError) as excinfo:
        _build_small(small_store, terminal_declarations=(after,), allow_gaps=(_interior_gap(),))
    # The 09:00 slots of the 1h trade, 1m trade and 1m mark series precede the stated terminal.
    refused = [g for g in _terminal_holes(DAY3, last_day=DAY2) if g.start_utc == SMALL_CUT]
    assert len(refused) == 3
    assert list(excinfo.value.gaps) == refused
    assert "terminal timestamp is after the gap start" in str(excinfo.value)


def test_an_observation_at_or_after_the_terminal_timestamp_is_refused(small_store: Path) -> None:
    holes = _terminal_holes(DAY3, last_day=DAY2)
    # 08:00 is the last 1h bar, the last 4h bar and the last funding instant: every series has
    # an observation at or after it.
    at = _decl(terminal_at_utc=SMALL_CUT - HOUR)
    with pytest.raises(ci.CaseInputGapError) as excinfo:
        _build_small(small_store, terminal_declarations=(at,), allow_gaps=(_interior_gap(),))
    assert list(excinfo.value.gaps) == holes
    assert "observation at or after the terminal timestamp" in str(excinfo.value)
    # 08:30: only the 1m trade and mark series (last observation 08:59) reach past it.
    half = _decl(terminal_at_utc=SMALL_CUT - timedelta(minutes=30))
    with pytest.raises(ci.CaseInputGapError) as excinfo:
        _build_small(small_store, terminal_declarations=(half,), allow_gaps=(_interior_gap(),))
    assert list(excinfo.value.gaps) == [g for g in holes if g.interval == "1m"]


def test_a_window_without_a_file_follows_the_terminal_timestamp(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    tb.build_store(root, start=DAY1, end=datetime(2026, 3, 5, tzinfo=UTC), symbols=(LONG,))
    declaration = _decl(terminal_at_utc=DAY2)
    window_end = datetime(2026, 3, 4, tzinfo=UTC)
    # The term symbol has no file at all: each series is ONE hole covering the window.
    data = _build(
        root,
        start_utc=DAY2,
        end_utc=window_end,
        as_of_day_utc=window_end.date(),
        terminal_declarations=(declaration,),
    )
    assert list(data.allowed_gaps) == [
        _gap("trade", "1h", DAY2, window_end, 48),
        _gap("trade", "4h", DAY2, window_end, 12),
        _gap("intrabar_1m", "1m", DAY2, window_end, 2880),
        _gap("mark_1m", "1m", DAY2, window_end, 2880),
        _gap("funding", "8h", DAY2, window_end, 6),
    ]
    # A window that starts before the terminal timestamp is refused.
    with pytest.raises(ci.CaseInputGapError) as excinfo:
        _build(
            root,
            start_utc=DAY1,
            end_utc=DAY3,
            as_of_day_utc=DAY3.date(),
            terminal_declarations=(declaration,),
        )
    assert len(excinfo.value.gaps) == 5
    assert "terminal timestamp is after the gap start" in str(excinfo.value)


def test_the_six_builder_calls_each_acknowledge_exactly_five_gaps(
    store: Path, tmp_path: Path
) -> None:
    manifest = mf.load_manifest(_write(tmp_path, _payload()))
    assert len(manifest.known_gaps) == 1  # one declaration, not 30 rows
    windows = [(w.start_utc, w.end_utc) for w in mf.research_splits(manifest)]
    assert len(windows) == 5
    ranges = [(STORE_START, VAL_END), *windows]  # the whole-range pre-flight plus 5 windows
    assert len(ranges) == 6
    for start, end in ranges:
        data = _build(
            store,
            start_utc=start,
            end_utc=end,
            as_of_day_utc=VAL_END.date(),
            terminal_declarations=manifest.known_gaps,
        )
        assert len(data.allowed_gaps) == 5
        assert {g.symbol for g in data.allowed_gaps} == {TERM}
        assert [(g.series, g.interval) for g in data.allowed_gaps][:4] == [
            ("trade", "1h"),
            ("trade", "4h"),
            ("intrabar_1m", "1m"),
            ("mark_1m", "1m"),
        ]
        # The funding label as the builder derives it: 4h where the symbol has rows, 8h where
        # the window has none (the four folds, which start after the terminal day).
        expected_label = "4h" if start < LAST_DAY else "8h"
        assert data.allowed_gaps[4].series == "funding"
        assert data.allowed_gaps[4].interval == expected_label
    # The development window, by hand: 111 hours of 1h, 108 hours of 4h bars.
    dev = _build(
        store,
        start_utc=STORE_START,
        end_utc=DEV_END,
        as_of_day_utc=VAL_END.date(),
        terminal_declarations=manifest.known_gaps,
    )
    assert list(dev.allowed_gaps) == _terminal_holes(DEV_END)
    assert [g.missing for g in dev.allowed_gaps] == [111, 27, 6660, 6660, 27]


def test_a_data_loss_entry_needs_the_exact_six_field_match(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    tb.build_store(root, start=DAY1, end=DAY3, skip_1m_hour=INTERIOR_HOUR, symbols=(LONG,))
    exact = _interior_gap()
    for field, value in (
        ("series", "mark_1m"),
        ("symbol", TERM),
        ("interval", "5m"),
        ("start_utc", INTERIOR_HOUR + timedelta(minutes=1)),
        ("end_utc", INTERIOR_HOUR + timedelta(minutes=59)),
        ("missing", 59),
    ):
        entry = GapRange(**{**exact.__dict__, field: value})
        with pytest.raises(ci.CaseInputGapError) as excinfo:
            _build(
                root,
                symbols=[LONG],
                start_utc=DAY1,
                end_utc=DAY3,
                as_of_day_utc=DAY3.date(),
                allow_gaps=(entry,),
            )
        assert list(excinfo.value.gaps) == [exact], field
    data = _build(
        root,
        symbols=[LONG],
        start_utc=DAY1,
        end_utc=DAY3,
        as_of_day_utc=DAY3.date(),
        allow_gaps=(exact,),
    )
    assert data.allowed_gaps == (exact,)


def test_the_builder_refuses_two_declarations_for_one_symbol(small_store: Path) -> None:
    with pytest.raises(ci.CaseInputError, match="one per symbol"):
        _build_small(
            small_store,
            terminal_declarations=(_decl(), _decl(terminal_at_utc=SMALL_CUT + HOUR)),
            allow_gaps=(_interior_gap(),),
        )


def _geometry_case(**gap_overrides: Any) -> tuple[Any, list[int], dict[str, Any]]:
    """A 1h trade series observed up to 08:00 on the last day, window end 2026-03-05."""
    end = datetime(2026, 3, 5, tzinfo=UTC)
    last = datetime(2026, 3, 4, 8, tzinfo=UTC)
    first_missing = last + HOUR
    gap = _gap("trade", "1h", first_missing, end, (end - first_missing) // HOUR)
    gap = GapRange(**{**gap.__dict__, **gap_overrides})
    kwargs = {
        "terminal_at_utc": first_missing,
        "step_ms": 3_600_000,
        "start_utc": STORE_START,
        "end_utc": end,
    }
    return gap, [tb._ms(last)], kwargs


def test_the_geometry_check_accepts_a_consistent_gap_and_names_each_failure() -> None:
    gap, observed, kwargs = _geometry_case()
    assert ci._terminal_refusal(gap, observed_ms=observed, **kwargs) is None

    def refusal(**override: Any) -> str:
        bad, obs, kw = _geometry_case(**override)
        result = ci._terminal_refusal(bad, observed_ms=obs, **kw)
        assert result is not None
        return result

    assert "missing count" in refusal(missing=gap.missing + 1)
    assert "missing count" in refusal(missing=gap.missing - 1)
    assert "first slot after the last observation" in refusal(start_utc=gap.start_utc + HOUR)
    assert "not trailing" in refusal(end_utc=gap.end_utc - HOUR)
    # Data after the gap start: the series continues after the hole.
    after = ci._terminal_refusal(
        gap, observed_ms=[*observed, tb._ms(gap.start_utc + 2 * HOUR)], **kwargs
    )
    assert after is not None
    assert "observation at or after the terminal timestamp" in after
    # A terminal timestamp after the gap start is refused although the geometry is right.
    kwargs["terminal_at_utc"] = gap.start_utc + HOUR
    late = ci._terminal_refusal(gap, observed_ms=observed, **kwargs)
    assert late is not None
    assert "terminal timestamp is after the gap start" in late
    # An observation at or after the terminal timestamp is refused.
    kwargs["terminal_at_utc"] = datetime(2026, 3, 4, 8, tzinfo=UTC)
    seen = ci._terminal_refusal(gap, observed_ms=observed, **kwargs)
    assert seen is not None
    assert "observation at or after the terminal timestamp" in seen


@pytest.mark.parametrize(
    "mutation",
    [
        {"terminal_at_utc": "2026-03-04T09:00:00"},
        {"terminal_at_utc": "2026-03-04T09:00:00+07:00"},
        {"terminal_at_utc": "not a time"},
        {"terminal_at_utc": 1741078800},
        {"symbol": "XYZUSDT"},
        {"symbol": "btcusdt"},
        {"reason": None},
        {"source_url": ""},
        {"source_url": 7},
    ],
)
def test_the_loader_refuses_a_bad_field(tmp_path: Path, mutation: dict[str, Any]) -> None:
    with pytest.raises(mf.ManifestError):
        mf.load_manifest(_write(tmp_path, _payload(known_gaps=[_declaration_row(**mutation)])))


def test_the_loader_refuses_structural_errors(tmp_path: Path) -> None:
    rows: list[Any] = [_declaration_row(), _declaration_row(terminal_at_utc="2026-03-04T08:00:00Z")]
    with pytest.raises(mf.ManifestError, match="more than one"):
        mf.load_manifest(_write(tmp_path, _payload(known_gaps=rows)))
    with pytest.raises(mf.ManifestError):
        mf.load_manifest(_write(tmp_path, _payload(known_gaps="x")))
    with pytest.raises(mf.ManifestError):
        mf.load_manifest(_write(tmp_path, _payload(known_gaps=["x"])))
    # A six-key row of the old shape (a range, no reason) is refused: the reason is required.
    old_row = {
        "series": "trade",
        "symbol": TERM,
        "interval": "1h",
        "start_utc": "2026-03-04T09:00:00Z",
        "end_utc": "2026-03-17T00:00:00Z",
        "missing": 303,
    }
    with pytest.raises(mf.ManifestError):
        mf.load_manifest(_write(tmp_path, _payload(known_gaps=[old_row])))
    # A JSON float anywhere is refused.
    path = tmp_path / "float.json"
    path.write_text(json.dumps(_payload()).replace('"equity": "1000"', '"equity": 1000.5'))
    with pytest.raises(mf.ManifestError):
        mf.load_manifest(path)


def test_the_constants_hold_the_recorded_vocabulary_and_host() -> None:
    assert mf.KNOWN_GAP_REASONS == frozenset({"DELISTED_CAPPED"})
    assert mf.KNOWN_GAP_SOURCE_HOSTS == frozenset({"www.binance.com"})


def _expected_base() -> dict[str, Any]:
    """The canonical form written by hand: the keys and the values of today, known_gaps empty."""
    return {
        "universe_id": "research-universe-v1",
        "symbols": [LONG, TERM],
        "dataset_id": "0" * 64,
        "development_start_utc": "2026-03-01T00:00:00+00:00",
        "development_end_utc": "2026-03-09T00:00:00+00:00",
        "validation_start_utc": "2026-03-09T00:00:00+00:00",
        "validation_end_utc": "2026-03-17T00:00:00+00:00",
        "holdout_start_utc": "2026-03-17T00:00:00+00:00",
        "holdout_end_utc": "2026-03-19T00:00:00+00:00",
        "strategy_interval": "1h",
        "context_interval": "4h",
        "data_source": "binance-usdm-public",
        "data_source_version": "test-1",
        "excluded_periods": [],
        "known_gaps": [],
        "equity": "1000",
        "risk_rate": "0.005",
        "constraint_source": "constraints.json",
        "constraint_sha256": "1" * 64,
    }


def _independent_hash(expected: dict[str, Any]) -> str:
    text = json.dumps(expected, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _plain_canonical(manifest: Any) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(
        json.dumps(
            manifest.canonical(),
            default=lambda v: v.isoformat() if isinstance(v, datetime) else str(v),
        )
    )
    return out


def test_the_canonical_form_and_hash_are_pinned_against_literals(tmp_path: Path) -> None:
    empty = mf.load_manifest(_write(tmp_path, _payload(known_gaps=[]), "empty.json"))
    expected_empty = _expected_base()
    # No version key: the canonical form with known_gaps empty is the form of today.
    assert _plain_canonical(empty) == expected_empty
    assert mf.manifest_hash(empty) == _independent_hash(expected_empty)

    one = mf.load_manifest(_write(tmp_path, _payload(), "one.json"))
    expected_one = _expected_base()
    expected_one["known_gaps"] = [
        {
            "symbol": TERM,
            "reason": "DELISTED_CAPPED",
            "terminal_at_utc": "2026-03-04T09:00:00+00:00",
            "source_url": SOURCE_URL,
        }
    ]
    assert _plain_canonical(one) == expected_one
    assert mf.manifest_hash(one) == _independent_hash(expected_one)
    assert mf.manifest_hash(one) != mf.manifest_hash(empty)


def test_the_declaration_stays_out_of_the_case_input_and_the_build_is_deterministic(
    small_store: Path,
) -> None:
    from src.backtest.case import parse_case_input

    declarations = (_decl(terminal_at_utc=SMALL_CUT),)
    builds = [
        _build_small(small_store, terminal_declarations=declarations, allow_gaps=(_interior_gap(),))
        for _ in range(2)
    ]
    assert builds[0].allowed_gaps == builds[1].allowed_gaps
    cases = [b.to_case_input(**tb._scenario((LONG, TERM), scripted_plans=[])) for b in builds]
    assert json.dumps(cases[0], sort_keys=True) == json.dumps(cases[1], sort_keys=True)
    rows = cases[0]["allowed_gaps"]
    assert len(rows) == 6  # the interior hole plus the five declared holes
    for row in rows:
        assert set(row) == {"series", "symbol", "start_utc", "end_utc", "missing"}
    assert parse_case_input(cases[0]).allowed_gaps  # the closed v2 parser accepts the rows
    flat = json.dumps(cases[0])
    assert REASON not in flat
    assert "www.binance.com" not in flat


def test_reordering_the_declarations_does_not_change_the_result(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    tb.build_store(root, start=DAY1, end=DAY3, symbols=(LONG,))
    _publish_terminal_symbol(root, TERM, DAY1, SMALL_CUT)
    _publish_terminal_symbol(root, OTHER_TERM, DAY1, DAY2 + 5 * HOUR)
    first = _decl(terminal_at_utc=SMALL_CUT)
    second = _decl(symbol=OTHER_TERM, terminal_at_utc=DAY2 + 5 * HOUR)
    forward = _build(
        root,
        symbols=[LONG, TERM, OTHER_TERM],
        start_utc=DAY1,
        end_utc=DAY3,
        as_of_day_utc=DAY3.date(),
        terminal_declarations=(first, second),
    )
    backward = _build(
        root,
        symbols=[LONG, TERM, OTHER_TERM],
        start_utc=DAY1,
        end_utc=DAY3,
        as_of_day_utc=DAY3.date(),
        terminal_declarations=(second, first),
    )
    assert forward.allowed_gaps == backward.allowed_gaps
    assert {g.symbol for g in forward.allowed_gaps} == {TERM, OTHER_TERM}
    assert len(forward.allowed_gaps) == 10
