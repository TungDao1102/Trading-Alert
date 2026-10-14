"""Consumers of the terminal settlement vocabulary (quick 261014-nnl, plan 05).

Design 16-DRAFT-S-B-interval-design.md rev3 section 4: every consumer that refuses unknown
kinds accepts SETTLEMENT (exit) and SETTLEMENT_CANCEL (entry) with the one vocabulary of
`src/backtest/semantics.py`. SETTLEMENT is counted apart like END_OF_DATA: never a closed
trade, never in pooled R, the trade floor or the G1 counts. A settlement is a filled trade for
the intrabar coverage population (so its fixed coverage note surfaces). Reports and feasibility
lines of inputs without a settlement stay byte-identical: the settlement figures join a digest
payload or a rendered line only when non-zero.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from typing import Any

import pytest
from src.adapters.analytics_files import load_evidence_file
from src.analytics.lifecycle import normalize_backtest_lifecycle
from src.backtest import report as backtest_report
from src.backtest.report import ReportBuildError
from src.backtest.semantics import EXIT_SETTLEMENT, SETTLEMENT_CANCEL
from src.backtest.validator import validate_trade_record
from src.domain.canonical import sha256_hex
from src.research import feasibility
from src.research.feasibility import (
    FeasibilityError,
    count_closed_trades,
    feasibility_report,
    render_feasibility,
)
from src.research.report import MARK_HOLE_MARKER, count_mark_hole_trades

from tests.backtest_plan_helpers import make_record
from tests.test_analytics_files import _evidence_with
from tests.test_analytics_lifecycle import _outcome
from tests.test_backtest_report import (
    _build_report,
    _end_of_data_trade,
    _gap_trade,
    _make_experiment_record,
    _plan_outcome,
)
from tests.test_backtest_terminal_settlement import LONG_NOTE, RESTING_NOTE

_SEED = 11


def _settlement_trade(
    trade_id: str, pnl: str = "-0.30", risk: str = "0.10", **over: object
) -> dict:
    """A filled trade the terminal settlement closed, with the plan 03 fixed coverage note."""
    over.setdefault("coverage_note", LONG_NOTE)
    return _gap_trade(trade_id, pnl, risk, exit_kind=EXIT_SETTLEMENT, **over)


def _report(trades: list[dict]) -> backtest_report.UncertaintyReport:
    report = _build_report(
        experiment_record=_make_experiment_record(),
        trade_records=trades,
        bootstrap_seed=_SEED,
        resamples=100,
    )
    assert isinstance(report, backtest_report.UncertaintyReport)
    return report


def _two_closed() -> list[dict]:
    return [
        _gap_trade("c-1", "0.20", "0.10", exit_kind="TP2"),
        _gap_trade("c-2", "-0.10", "0.10", exit_kind="SL"),
    ]


def _old_counts_payload(report: backtest_report.UncertaintyReport) -> dict[str, object]:
    """Today's seven-key CountsSection digest payload, built from the report's own values."""
    counts = report.counts
    return {
        "trade_count": counts.trade_count,
        "end_of_data_count": counts.end_of_data_count,
        "plan_outcome_counts": counts.plan_outcome_counts,
        "counts_by_symbol": counts.counts_by_symbol,
        "counts_by_quarter": counts.counts_by_quarter,
        "counts_by_regime": counts.counts_by_regime,
        "counts_by_version": counts.counts_by_version,
    }


def _old_coverage_payload(report: backtest_report.UncertaintyReport) -> dict[str, object]:
    """Today's six-key IntrabarCoverage digest payload, built from the report's own values."""
    coverage = report.intrabar_coverage
    return {
        "percent": coverage.percent,
        "fallback_count": coverage.fallback_count,
        "total_trades": coverage.total_trades,
        "closed_trades": coverage.closed_trades,
        "end_of_data_trades": coverage.end_of_data_trades,
        "coverage_notes": list(coverage.coverage_notes),
    }


# --------------------------------------------------------------------------- #
# Backtest report (src/backtest/report.py)
# --------------------------------------------------------------------------- #


def test_report_counts_settlement_apart_and_keeps_it_out_of_pooled_r() -> None:
    without = _report(_two_closed())
    with_settlement = _report([*_two_closed(), _settlement_trade("s-1", "-9.00", "0.10")])

    assert with_settlement.counts.trade_count == 2
    assert with_settlement.counts.settlement_count == 1
    assert with_settlement.counts.end_of_data_count == 0
    assert with_settlement.r_distribution == without.r_distribution
    assert with_settlement.counts.counts_by_symbol == without.counts.counts_by_symbol
    assert with_settlement.counts.digest() == sha256_hex(
        {**_old_counts_payload(with_settlement), "settlement_count": 1}
    )


def test_counts_digest_without_settlement_is_byte_identical() -> None:
    report = _report([*_two_closed(), _end_of_data_trade("e-1", "0.10", "0.10")])
    assert report.counts.settlement_count == 0
    assert report.counts.digest() == sha256_hex(_old_counts_payload(report))


def test_report_counts_settlement_cancel_as_a_plan_outcome() -> None:
    report = _report([*_two_closed(), _plan_outcome("p-1", SETTLEMENT_CANCEL)])
    assert report.counts.plan_outcome_counts[SETTLEMENT_CANCEL] == 1
    assert report.counts.trade_count == 2
    assert report.counts.settlement_count == 0


def test_intrabar_coverage_includes_settlement_trades_and_surfaces_their_note() -> None:
    report = _report([_gap_trade("c-1", "0.20", "0.10", exit_kind="TP2"), _settlement_trade("s-1")])
    coverage = report.intrabar_coverage
    assert coverage.total_trades == 2
    assert coverage.closed_trades == 1
    assert coverage.end_of_data_trades == 0
    assert coverage.settlement_trades == 1
    assert LONG_NOTE in coverage.coverage_notes
    assert coverage.percent == Decimal("100")


def test_intrabar_coverage_counts_a_settlement_fallback() -> None:
    report = _report(
        [
            _gap_trade("c-1", "0.20", "0.10", exit_kind="TP2"),
            _settlement_trade("s-1", fallback_applied=True),
        ]
    )
    coverage = report.intrabar_coverage
    assert coverage.fallback_count == 1
    assert coverage.total_trades == 2
    assert coverage.percent == Decimal("50")


def test_coverage_digest_without_settlement_is_byte_identical() -> None:
    report = _report(
        [*_two_closed(), _end_of_data_trade("e-1", "0.10", "0.10", fallback_applied=True)]
    )
    assert report.intrabar_coverage.settlement_trades == 0
    assert report.intrabar_coverage.digest() == sha256_hex(_old_coverage_payload(report))


def test_coverage_digest_with_settlement_carries_the_count() -> None:
    report = _report([*_two_closed(), _settlement_trade("s-1")])
    assert report.intrabar_coverage.digest() == sha256_hex(
        {**_old_coverage_payload(report), "settlement_trades": 1}
    )


def test_report_refusal_message_lists_the_four_exit_kinds() -> None:
    with pytest.raises(ReportBuildError) as info:
        _report([_gap_trade("v-1", "0.20", "0.10", exit_kind="MYSTERY")])
    message = str(info.value)
    for kind in ("END_OF_DATA", "SETTLEMENT", "SL", "TP2"):
        assert kind in message


# --------------------------------------------------------------------------- #
# Feasibility (src/research/feasibility.py)
# --------------------------------------------------------------------------- #


def _f_trade(exit_kind: str | None) -> dict[str, object]:
    return {
        "trade_id": f"f-{exit_kind}",
        "outcome_kind": "OK",
        "entry_kind": "ENTRY_FILLED",
        "exit_kind": exit_kind,
    }


def test_count_closed_trades_counts_settlement_apart() -> None:
    counts = count_closed_trades([_f_trade("SL"), _f_trade("TP2"), _f_trade(EXIT_SETTLEMENT)])
    assert counts.closed == 2
    assert counts.end_of_data == 0
    assert counts.settlement == 1


def test_feasibility_counts_settlement_apart_in_development() -> None:
    development = [_f_trade("SL"), _f_trade("TP2"), _f_trade(EXIT_SETTLEMENT)]
    report = feasibility_report(
        [[_f_trade("SL")]], parameter_set_id="P", development_trades=development
    )
    assert report.development_closed == 2
    assert report.development_settlement == 1
    assert "development_settlement=1" in render_feasibility(report)[0]


def test_feasibility_render_without_settlement_is_byte_identical() -> None:
    report = feasibility_report(
        [[_f_trade("SL")]], parameter_set_id="P", development_trades=[_f_trade("SL")]
    )
    assert report.development_settlement is None or report.development_settlement == 0
    assert render_feasibility(report)[0] == (
        "feasibility parameter_set_id=P development_closed=1 development_end_of_data=0 "
        "pooled_closed=1 pooled_floor=100 fold_closed=1 fold_floor=30 "
        "end_of_data_pooled=0 end_of_data_by_fold=0"
    )
    assert "settlement" not in render_feasibility(report)[0]


def test_feasibility_refuses_a_settlement_in_a_validation_fold() -> None:
    with pytest.raises(FeasibilityError, match="manifest guard"):
        feasibility_report([[_f_trade("SL")], [_f_trade(EXIT_SETTLEMENT)]], parameter_set_id="P")


def test_feasibility_still_refuses_an_unknown_exit_kind() -> None:
    with pytest.raises(FeasibilityError, match="SETTLEMENT"):
        count_closed_trades([_f_trade("MYSTERY")])


def test_closed_exit_kinds_stay_sl_and_tp2() -> None:
    assert feasibility.CLOSED_EXIT_KINDS == frozenset({"SL", "TP2"})
    assert backtest_report._CLOSED_EXIT_KINDS == frozenset({"SL", "TP2"})
    assert EXIT_SETTLEMENT not in feasibility.CLOSED_EXIT_KINDS


def test_resting_note_is_not_a_filled_trade_note() -> None:
    # The RESTING note belongs to a SETTLEMENT_CANCEL plan outcome, which has no fill and so
    # is never in the filled coverage population.
    report = _report(
        [
            _gap_trade("c-1", "0.20", "0.10", exit_kind="TP2"),
            _plan_outcome("p-1", SETTLEMENT_CANCEL, coverage_note=RESTING_NOTE),
        ]
    )
    assert report.intrabar_coverage.total_trades == 1
    assert RESTING_NOTE not in report.intrabar_coverage.coverage_notes


# --------------------------------------------------------------------------- #
# Validator, analytics lifecycle, analytics evidence loader, mark-hole count
# --------------------------------------------------------------------------- #


def _cancel_record() -> Any:
    """An engine-shaped SETTLEMENT_CANCEL record: never filled, every fill field None."""
    return make_record(
        entry_kind=SETTLEMENT_CANCEL,
        entry_price=None,
        entry_time_utc=None,
        quantity=None,
        exit_kind=None,
        exit_price=None,
        exit_time_utc=None,
        realized_pnl=None,
        realized_risk=None,
        gross_pnl=None,
        entry_fee=None,
        exit_fee=None,
        funding_amount=None,
        slippage_amount=None,
    )


@pytest.mark.parametrize("strict", [False, True])
def test_validator_accepts_settlement_exit_and_settlement_cancel_records(strict: bool) -> None:
    validate_trade_record(make_record(exit_kind=EXIT_SETTLEMENT), strict=strict)
    validate_trade_record(_cancel_record(), strict=strict)


def test_analytics_lifecycle_normalizes_settlement_cancel_as_unfilled() -> None:
    cancelled = _outcome("A", entry_kind=SETTLEMENT_CANCEL, intended="100")
    (record,) = normalize_backtest_lifecycle([cancelled])
    assert record.entry_filled is False
    assert record.expired_without_fill is False
    assert record.actual_entry_price is None


def test_analytics_lifecycle_normalizes_a_settlement_exit_as_filled() -> None:
    settled = dataclasses.replace(
        _outcome("B", entry_kind="ENTRY_FILLED", intended="100", entry="100"),
        exit_kind=EXIT_SETTLEMENT,
    )
    (record,) = normalize_backtest_lifecycle([settled])
    assert record.entry_filled is True
    assert record.actual_entry_price == Decimal("100")


def test_analytics_evidence_loader_accepts_a_settlement_trade(tmp_path: Any) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        entry = doc["backtest"][0]
        assert entry["experiment"]["end_of_data_count"] == 0
        settled, other = entry["trades"]
        settled["exit_kind"] = EXIT_SETTLEMENT
        settled["coverage_note"] = LONG_NOTE
        other.update(
            entry_kind=SETTLEMENT_CANCEL,
            outcome_kind="OK",
            reason_code="OK",
            coverage_note=RESTING_NOTE,
        )

    evidence = load_evidence_file(_evidence_with(tmp_path, mutate))
    trades = evidence.backtest[0].trades
    assert [t.exit_kind for t in trades] == [EXIT_SETTLEMENT, None]
    assert [t.entry_kind for t in trades] == ["ENTRY_FILLED", SETTLEMENT_CANCEL]


def test_mark_hole_count_ignores_the_settlement_note() -> None:
    assert MARK_HOLE_MARKER not in LONG_NOTE
    assert MARK_HOLE_MARKER not in RESTING_NOTE
    trades = [
        _settlement_trade("s-1"),
        _gap_trade("c-1", "0.20", "0.10", exit_kind="TP2"),
        _plan_outcome("p-1", SETTLEMENT_CANCEL, coverage_note=RESTING_NOTE),
    ]
    assert count_mark_hole_trades(trades) == 0


def test_mark_hole_count_still_counts_a_settlement_trade_held_through_a_hole() -> None:
    # A settlement trade is in the filled population (it filters on outcome and entry kind
    # only), so a mark hole in its note is counted like any other filled trade.
    note = f"{MARK_HOLE_MARKER} span; {LONG_NOTE}"
    assert count_mark_hole_trades([_settlement_trade("s-1", coverage_note=note)]) == 1
