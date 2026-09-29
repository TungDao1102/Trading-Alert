"""NO_TRADE counts by reason category (Phase 10, plan 10-04, GOV-01, D-04, D-05).

NO_TRADE is a first-class outcome (RESEARCH_PROTOCOL): counted by the five protocol
reason categories plus an UNMAPPED bucket that is counted, never dropped, split
into live-5 / research / all counts.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from src.analytics.no_trade import (
    NO_TRADE_CATEGORY_BY_REASON,
    NoTradeCategory,
    NoTradeRow,
    NoTradeSection,
    category_for,
    count_no_trades,
    no_trade_from_paper,
)
from src.analytics.types import AnalyticsInputError, EvidenceKind, NoTradeRecord
from src.backtest.report import LIVE5_SYMBOLS
from src.paper.attribution import AttributionKind
from src.paper.journal import PaperRecord

from tests.phase10_helpers import load_expected, load_input, make_paper_record

HEX64 = re.compile(r"^[0-9a-f]{64}$")
NO_TRADE_SRC = Path(__file__).resolve().parent.parent / "src" / "analytics" / "no_trade.py"


def records_from_fixture() -> list[NoTradeRecord]:
    return [
        NoTradeRecord(
            evidence=EvidenceKind(row["evidence"]),
            symbol=row["symbol"],
            reason_code=row["reason_code"],
            source_id=row["source_id"],
        )
        for row in load_input("no_trade_categories")["records"]
    ]


def test_category_values_and_order() -> None:
    assert [c.value for c in NoTradeCategory] == [
        "REGIME_FILTER",
        "RR_FLOOR",
        "OPEN_POSITION_CONFLICT",
        "DATA_UNAVAILABILITY",
        "KILL_GATE_TRIP",
        "UNMAPPED",
    ]


def test_reason_mapping_pinned() -> None:
    assert dict(NO_TRADE_CATEGORY_BY_REASON) == {
        "NO_TRADE_REGIME": NoTradeCategory.REGIME_FILTER,
        "RR_TOO_LOW": NoTradeCategory.RR_FLOOR,
        "MAX_POSITIONS_REJECT": NoTradeCategory.OPEN_POSITION_CONFLICT,
        "SKIPPED_BUSY": NoTradeCategory.OPEN_POSITION_CONFLICT,
        "DATA_STALE": NoTradeCategory.DATA_UNAVAILABILITY,
        "STALE_CONSTRAINTS": NoTradeCategory.DATA_UNAVAILABILITY,
        "UNCERTAIN_ACCOUNT_STATE": NoTradeCategory.DATA_UNAVAILABILITY,
        "RECONCILIATION_REQUIRED": NoTradeCategory.DATA_UNAVAILABILITY,
        "INSUFFICIENT_EDGE": NoTradeCategory.KILL_GATE_TRIP,
    }
    assert category_for("NO_TRADE_REGIME") is NoTradeCategory.REGIME_FILTER
    assert category_for("SOMETHING_NEW") is NoTradeCategory.UNMAPPED
    assert category_for("") is NoTradeCategory.UNMAPPED


def test_count_by_category_matches_fixture_with_unmapped_and_total() -> None:
    case_input = load_input("no_trade_categories")
    expected = load_expected("no_trade_categories")
    section = count_no_trades(
        records_from_fixture(),
        evidence=EvidenceKind(case_input["evidence"]),
        research_symbols=case_input["research_symbols"],
    )
    assert isinstance(section, NoTradeSection)
    assert section.evidence is EvidenceKind.PAPER
    assert [row.category for row in section.rows] == list(NoTradeCategory)
    for row, want in zip(section.rows, expected["rows"], strict=True):
        assert isinstance(row, NoTradeRow)
        assert row.category is NoTradeCategory(want["category"]), want["category"]
        assert row.live5_n == want["live5_n"], want["category"]
        assert row.research_n == want["research_n"], want["category"]
        assert row.all_n == want["all_n"], want["category"]
    regime = section.rows[0]
    assert (regime.live5_n, regime.research_n, regime.all_n) == (1, 2, 2)
    assert section.rows[-1].category is NoTradeCategory.UNMAPPED
    assert section.rows[-1].all_n == 1
    total = section.total
    assert total.all_n == expected["total"]["all_n"] == 7
    assert total.live5_n == expected["total"]["live5_n"]
    assert total.research_n == expected["total"]["research_n"]
    assert sum(row.all_n for row in section.rows) == total.all_n
    assert section.research_symbols == tuple(expected["research_symbols_sorted"])
    assert HEX64.match(section.digest())
    assert section.digest() == expected["section_digest"]


def test_unmapped_is_counted_never_dropped() -> None:
    section = count_no_trades(
        [
            NoTradeRecord(
                evidence=EvidenceKind.PAPER,
                symbol="BTCUSDT",
                reason_code="TOTALLY_NEW_CODE",
                source_id="X1",
            )
        ],
        evidence=EvidenceKind.PAPER,
        research_symbols=["BTCUSDT"],
    )
    assert section.rows[-1].category is NoTradeCategory.UNMAPPED
    assert section.rows[-1].all_n == 1
    assert section.total.all_n == 1


def test_empty_input_yields_all_rows_with_zero_counts() -> None:
    section = count_no_trades([], evidence=EvidenceKind.LIVE, research_symbols=[])
    assert section.evidence is EvidenceKind.LIVE
    assert len(section.rows) == 6
    assert all(row.all_n == 0 for row in section.rows)
    assert section.total.all_n == 0


def test_mixed_evidence_raises() -> None:
    mixed = [
        NoTradeRecord(
            evidence=EvidenceKind.BACKTEST,
            symbol="BTCUSDT",
            reason_code="RR_TOO_LOW",
            source_id="B1",
        )
    ]
    with pytest.raises(AnalyticsInputError):
        count_no_trades(mixed, evidence=EvidenceKind.PAPER, research_symbols=["BTCUSDT"])


def test_shuffled_records_yield_identical_digest() -> None:
    case_input = load_input("no_trade_categories")
    recs = records_from_fixture()
    base = count_no_trades(
        recs, evidence=EvidenceKind.PAPER, research_symbols=case_input["research_symbols"]
    )
    again = count_no_trades(
        list(reversed(recs)),
        evidence=EvidenceKind.PAPER,
        research_symbols=list(reversed(case_input["research_symbols"])),
    )
    assert again.digest() == base.digest()


def _paper_row(**overrides: object) -> PaperRecord:
    row: dict[str, object] = {
        "attribution": "system",
        "epoch_id": "EPOCH-1",
        "strategy_id": "S1",
        "strategy_version": "v2.0.0",
        "parameter_set_id": "P1",
        "parameter_set_hash": "a" * 64,
        "experiment_id": "X1",
        "symbol": "BTCUSDT",
        "signal_id": None,
        "plan_hash": None,
        "reason_code": "NO_TRADE_REGIME",
        "signal_detected_at_utc": None,
        "approval_acted_at_utc": None,
        "order_submitted_at_utc": None,
        "fill_time_utc": None,
    }
    row.update(overrides)
    return make_paper_record(row)


def test_no_trade_from_paper_keeps_only_system_rows_without_signal() -> None:
    rows = [
        _paper_row(symbol="BTCUSDT", reason_code="NO_TRADE_REGIME"),
        _paper_row(symbol="ETHUSDT", reason_code="RR_TOO_LOW"),
        # opportunity rows carry a signal and a reason but are NOT NO_TRADE
        _paper_row(
            attribution="opportunity",
            signal_id="SIG-1",
            plan_hash="b" * 64,
            reason_code="EXPIRED",
        ),
        # a system row WITH a signal is a real signal chain, not NO_TRADE
        _paper_row(signal_id="SIG-2", plan_hash="c" * 64, reason_code=""),
        _paper_row(attribution="user-executed-sim", signal_id="SIG-3", reason_code=""),
    ]
    assert isinstance(rows[0], PaperRecord)
    assert rows[0].attribution is AttributionKind.SYSTEM
    found = no_trade_from_paper(rows)
    assert [(r.symbol, r.reason_code) for r in found] == [
        ("BTCUSDT", "NO_TRADE_REGIME"),
        ("ETHUSDT", "RR_TOO_LOW"),
    ]
    assert all(r.evidence is EvidenceKind.PAPER for r in found)
    assert all(isinstance(r, NoTradeRecord) and r.source_id for r in found)


def test_no_trade_module_holds_no_universe_list_and_imports_live5() -> None:
    source = NO_TRADE_SRC.read_text(encoding="utf-8")
    assert "from src.backtest.report import" in source
    assert "LIVE5_SYMBOLS" in source
    for symbol in sorted(LIVE5_SYMBOLS):
        assert symbol not in source, f"{symbol} hard-coded in no_trade.py"
