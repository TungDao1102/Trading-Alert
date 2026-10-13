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
