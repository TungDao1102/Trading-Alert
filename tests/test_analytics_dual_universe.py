"""Dual-universe view tests (Phase 10, plan 10-04, D-04, D-05).

The live-5 universe (imported LIVE5_SYMBOLS, never a third copy) and the research
universe sit side by side per evidence kind; an empty live-5 slice is an explicit
no-data slice, never hidden or imputed; the research-universe hash is verified or
labelled UNVERIFIED_UNIVERSE.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest
from src.analytics.types import MIN_RESAMPLES, AnalyticsInputError, EvidenceKind
from src.analytics.universe import (
    NOT_APPLICABLE,
    UNVERIFIED_UNIVERSE,
    VERIFIED,
    DualUniverseView,
    build_dual_universe,
    verify_research_universe,
)
from src.backtest.report import LIVE5_SYMBOLS
from src.core._decimal import _div

from tests.phase10_helpers import D, load_expected, load_input, make_outcomes

HEX64 = re.compile(r"^[0-9a-f]{64}$")
BASE_SEED = 20260929
UNIVERSE_SRC = Path(__file__).resolve().parent.parent / "src" / "analytics" / "universe.py"


def _view(case_input: dict[str, object], **overrides: object) -> DualUniverseView:
    rows = case_input["outcomes"]
    assert isinstance(rows, list)
    research = case_input["research_symbols"]
    assert isinstance(research, list)
    kwargs: dict[str, object] = {
        "evidence": EvidenceKind(str(case_input["evidence"])),
        "research_symbols": research,
        "expected_universe_hash": case_input.get("expected_universe_hash"),
        "base_seed": BASE_SEED,
        "resamples": MIN_RESAMPLES,
    }
    kwargs.update(overrides)
    outcomes = make_outcomes(rows, evidence=str(case_input["evidence"]))
    return build_dual_universe(outcomes, **kwargs)  # type: ignore[arg-type]


def test_empty_live5_slice_is_explicit_no_data_and_universe_verified() -> None:
    case_input = load_input("empty_live5_slice")
    expected = load_expected("empty_live5_slice")
    view = _view(case_input)
    assert isinstance(view, DualUniverseView)
    assert view.live5_empty is expected["live5_empty"] is True
    assert view.live5.n == expected["live5"]["n"] == 0
    assert view.live5.n_r_valued == 0
    assert view.live5.mean_r.value is None
    assert view.live5.win_rate is None
    assert view.live5.median_r is None
    assert view.live5.max_drawdown_r is None
    assert view.research.n == expected["research"]["n"] == 3
    num, den = expected["research"]["mean_r"]
    assert view.research.mean_r.value == _div(D(num), D(den))
    assert view.universe_status == expected["universe_status"] == VERIFIED
    assert view.research_symbols == tuple(expected["research_symbols_sorted"])
    assert view.weak_live_universe_rejection is expected["weak_live_universe_rejection"] is False
    assert HEX64.match(view.universe_hash)
    assert HEX64.match(view.digest())
    assert view.digest() == expected["view_digest"]


def test_unverified_universe_when_expected_hash_is_wrong() -> None:
    case_input = load_input("empty_live5_slice")
    view = _view(case_input, expected_universe_hash="0" * 64)
    assert view.universe_status == UNVERIFIED_UNIVERSE == "UNVERIFIED_UNIVERSE"
    # Unverified never hides the data - the slices are still computed.
    assert view.research.n == 3


def test_not_applicable_without_expected_hash() -> None:
    case_input = load_input("empty_live5_slice")
    view = _view(case_input, expected_universe_hash=None)
    assert view.universe_status == NOT_APPLICABLE == "NOT_APPLICABLE"


def test_verify_research_universe_is_order_independent_and_exact() -> None:
    expected = load_input("empty_live5_slice")["expected_universe_hash"]
    assert verify_research_universe(["LINKUSDT", "ADAUSDT"], expected) == VERIFIED
    assert verify_research_universe(["ADAUSDT", "LINKUSDT"], expected) == VERIFIED
    assert verify_research_universe(["ADAUSDT"], expected) == UNVERIFIED_UNIVERSE
    assert verify_research_universe(["ADAUSDT", "LINKUSDT"], None) == NOT_APPLICABLE


def test_weak_live_universe_rejection_when_research_positive_and_live5_not() -> None:
    outcomes = make_outcomes(
        [
            {
                "trade_id": "W1",
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "entry_time_utc": "2026-02-01T08:00:00+00:00",
                "exit_time_utc": "2026-02-01T12:00:00+00:00",
                "realized_pnl": "-10",
                "realized_risk": "10",
            },
            {
                "trade_id": "W2",
                "symbol": "ADAUSDT",
                "direction": "LONG",
                "entry_time_utc": "2026-02-02T08:00:00+00:00",
                "exit_time_utc": "2026-02-02T12:00:00+00:00",
                "realized_pnl": "30",
                "realized_risk": "10",
            },
            {
                "trade_id": "W3",
                "symbol": "ADAUSDT",
                "direction": "LONG",
                "entry_time_utc": "2026-02-03T08:00:00+00:00",
                "exit_time_utc": "2026-02-03T12:00:00+00:00",
                "realized_pnl": "20",
                "realized_risk": "10",
            },
        ]
    )
    # Research universe (ADA only) has mean R > 0; live-5 (BTC) mean R = -1 <= 0.
    view = build_dual_universe(
        outcomes,
        evidence=EvidenceKind.BACKTEST,
        research_symbols=["ADAUSDT"],
        base_seed=BASE_SEED,
        resamples=MIN_RESAMPLES,
    )
    assert view.live5.mean_r.value == Decimal(-1)
    assert view.research.mean_r.value == Decimal("2.5")  # ADA only: (3 + 2) / 2
    assert view.weak_live_universe_rejection is True
    assert view.live5_empty is False


def test_overlap_is_by_design_live5_symbols_count_in_both_views() -> None:
    outcomes = make_outcomes(
        [
            {
                "trade_id": "O1",
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "entry_time_utc": "2026-02-01T08:00:00+00:00",
                "exit_time_utc": "2026-02-01T12:00:00+00:00",
                "realized_pnl": "10",
                "realized_risk": "10",
            },
            {
                "trade_id": "O2",
                "symbol": "ZZZUSDT",
                "direction": "LONG",
                "entry_time_utc": "2026-02-02T08:00:00+00:00",
                "exit_time_utc": "2026-02-02T12:00:00+00:00",
                "realized_pnl": "10",
                "realized_risk": "10",
            },
        ]
    )
    view = build_dual_universe(
        outcomes,
        evidence=EvidenceKind.BACKTEST,
        research_symbols=["BTCUSDT", "BTCUSDT", "ETHUSDT"],
        base_seed=BASE_SEED,
        resamples=MIN_RESAMPLES,
    )
    assert view.live5.n == 1  # BTC only; ZZZ is outside live-5
    assert view.research.n == 1  # BTC only; ZZZ is outside the supplied research symbols
    assert view.research_symbols == ("BTCUSDT", "ETHUSDT")  # sorted, de-duplicated
    assert view.live5_empty is False


def test_mixed_evidence_raises() -> None:
    outcomes = make_outcomes(
        [
            {
                "trade_id": "M1",
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "evidence": "PAPER",
            }
        ]
    )
    with pytest.raises(AnalyticsInputError):
        build_dual_universe(
            outcomes,
            evidence=EvidenceKind.BACKTEST,
            research_symbols=["BTCUSDT"],
            base_seed=BASE_SEED,
            resamples=MIN_RESAMPLES,
        )


def test_empty_input_stays_labelled_with_no_data_slices() -> None:
    view = build_dual_universe(
        [],
        evidence=EvidenceKind.LIVE,
        research_symbols=["BTCUSDT"],
        base_seed=BASE_SEED,
        resamples=MIN_RESAMPLES,
    )
    assert view.evidence is EvidenceKind.LIVE
    assert view.live5_empty is True
    assert view.live5.n == 0
    assert view.research.n == 0
    assert view.weak_live_universe_rejection is False


def test_digest_is_deterministic_and_tracks_seed() -> None:
    case_input = load_input("empty_live5_slice")
    assert _view(case_input).digest() == _view(case_input).digest()
    assert _view(case_input, base_seed=BASE_SEED + 1).digest() != _view(case_input).digest()


def test_live5_symbols_imported_never_a_third_copy() -> None:
    source = UNIVERSE_SRC.read_text(encoding="utf-8")
    assert "from src.backtest.report import" in source
    assert "LIVE5_SYMBOLS" in source
    for symbol in sorted(LIVE5_SYMBOLS):
        assert symbol not in source, f"{symbol} hard-coded in universe.py"
    import ast

    tree = ast.parse(source)
    for node in ast.walk(tree):
        assert not isinstance(node, ast.Set), "set literal in universe.py"
