"""Tests for the feasibility and sample-size report (Phase 16, plan 16-12, D-26, G3-027, D043).

The gate is reporting only: it counts closed trades the way the protocol G1 counts them,
compares them with the protocol floors and names any shortfall. It never ranks, orders by a
count, lowers a floor or simulates the holdout.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path
from typing import Any

import pytest
from src.backtest import report as backtest_report
from src.backtest import semantics
from src.research import feasibility
from src.research import run as research_run
from src.research.feasibility import (
    G1_PER_FOLD_FLOOR,
    G1_POOLED_FLOOR,
    G5_HOLDOUT_FLOOR,
    FeasibilityError,
    count_closed_trades,
    feasibility_report,
    render_feasibility,
)
from src.research.run import run_research

from tests.test_research_runner import (  # noqa: F401 - fixtures are used by name
    REPO_ROOT,
    VERDICT_WORDS,
    _authorization,
    _grid,
    _manifest,
    spies,
    store,
)

PROTOCOL = REPO_ROOT / "docs" / "research" / "RESEARCH_PROTOCOL.md"


def _trade(
    exit_kind: str | None,
    *,
    entry_kind: str = semantics.ENTRY_FILLED,
    outcome_kind: str = "OK",
) -> dict[str, Any]:
    return {
        "trade_id": "t",
        "outcome_kind": outcome_kind,
        "entry_kind": entry_kind,
        "exit_kind": exit_kind,
    }


def _closed(n: int) -> list[dict[str, Any]]:
    return [_trade(semantics.EXIT_SL if i % 2 else semantics.EXIT_TP2) for i in range(n)]


# --------------------------------------------------------------------------- #
# Test 1: the G1 closed-trade rule.
# --------------------------------------------------------------------------- #


def test_count_closed_trades_counts_sl_and_tp2_and_reports_end_of_data_apart() -> None:
    trades = [
        _trade(semantics.EXIT_SL),
        _trade(semantics.EXIT_TP2),
        _trade(semantics.EXIT_TP2, entry_kind=semantics.PARTIAL_FILL),
        _trade(semantics.EXIT_END_OF_DATA),
        _trade(None, entry_kind=semantics.EXPIRED),
        _trade(None, entry_kind=semantics.REJECT, outcome_kind="NO_TRADE"),
        _trade(semantics.EXIT_SL, entry_kind=semantics.EXPIRED),  # not a filled entry
    ]
    counts = count_closed_trades(trades)
    assert counts.closed == 3
    assert counts.end_of_data == 1


def test_count_closed_trades_refuses_a_filled_trade_with_an_unknown_exit() -> None:
    with pytest.raises(FeasibilityError):
        count_closed_trades([_trade("TP1")])
    with pytest.raises(FeasibilityError):
        count_closed_trades([_trade(None)])


def test_closed_exit_rule_is_the_backtest_report_rule() -> None:
    assert feasibility.CLOSED_EXIT_KINDS == backtest_report._CLOSED_EXIT_KINDS
    assert feasibility.FILLED_ENTRY_KINDS == backtest_report._FILLED_ENTRY_KINDS


# --------------------------------------------------------------------------- #
# Test 2: pooled and per-fold report, shortfalls, no ranking field.
# --------------------------------------------------------------------------- #


def test_feasibility_report_pools_folds_and_names_each_shortfall() -> None:
    folds = [_closed(40), _closed(12), _closed(30), [*_closed(29), _trade("END_OF_DATA")]]
    report = feasibility_report(folds, parameter_set_id="baseline-v5")
    assert report.parameter_set_id == "baseline-v5"
    assert report.pooled_closed == 111
    assert report.fold_closed == (40, 12, 30, 29)
    assert report.fold_end_of_data == (0, 0, 0, 1)
    assert report.pooled_floor == 100
    assert report.per_fold_floor == 30
    assert len(report.shortfalls) == 2
    assert any("fold 2" in s and "12" in s and "30" in s for s in report.shortfalls)
    assert any("fold 4" in s and "29" in s for s in report.shortfalls)


def test_feasibility_report_names_the_pooled_shortfall() -> None:
    report = feasibility_report([_closed(30)] * 3 + [_closed(9)], parameter_set_id="p")
    assert report.pooled_closed == 99
    assert any(s.startswith("pooled") and "99" in s and "100" in s for s in report.shortfalls)


def test_feasibility_report_with_no_shortfall_has_an_empty_list() -> None:
    report = feasibility_report([_closed(30)] * 4, parameter_set_id="p")
    assert report.pooled_closed == 120
    assert report.shortfalls == ()


def test_feasibility_report_has_no_rank_order_or_verdict_field() -> None:
    names = {f.name for f in dataclasses.fields(feasibility.FeasibilityReport)}
    assert not any(re.search(r"rank|order|verdict|score|best|status", n) for n in names), names
    report = feasibility_report([_closed(1)] * 4, parameter_set_id="p")
    text = "\n".join(render_feasibility(report))
    assert VERDICT_WORDS.search(text) is None, text
    assert "closed=" in text


# --------------------------------------------------------------------------- #
# Test 3: the floors are the protocol floors.
# --------------------------------------------------------------------------- #


def test_floors_are_constants_aligned_with_the_protocol_text() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")
    g1 = re.search(
        r"\*\*G1 \(trade floor\)\*\* — at least (\d+) closed trades pooled across the four "
        r"Validation folds and at least (\d+) closed trades in each Validation fold",
        text,
    )
    assert g1 is not None, "the protocol G1 sentence changed: update src/research/feasibility.py"
    assert (int(g1.group(1)), int(g1.group(2))) == (G1_POOLED_FLOOR, G1_PER_FOLD_FLOOR)
    g5 = re.search(
        r"\*\*G5 \(single-use holdout\)\*\*.*?requires at least (\d+) closed trades in the "
        r"holdout, counted exactly as G1 counts closed trades",
        text,
    )
    assert g5 is not None, "the protocol G5 sentence changed: update src/research/feasibility.py"
    assert int(g5.group(1)) == G5_HOLDOUT_FLOOR
    assert (G1_POOLED_FLOOR, G1_PER_FOLD_FLOOR, G5_HOLDOUT_FLOOR) == (100, 30, 30)


# --------------------------------------------------------------------------- #
# Test 4: the runner appends the report and the experiment records do not change.
# --------------------------------------------------------------------------- #


def test_run_research_appends_feasibility_and_leaves_records_unchanged(
    store: Path,  # noqa: F811
    tmp_path: Path,
    spies: Any,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _manifest(store, tmp_path)
    grid = _grid()
    out = tmp_path / "experiments"
    records = run_research(
        manifest=manifest,
        grid=grid,
        authorization=_authorization(manifest, grid),
        raw_root=store,
        output_dir=out,
        repo_root=REPO_ROOT,
    )
    stdout = capsys.readouterr().out
    assert "feasibility parameter_set_id=baseline-v5" in stdout
    assert "pooled_floor=100" in stdout and "fold_floor=30" in stdout
    assert VERDICT_WORDS.search(stdout) is None, stdout
    for record in records:
        raw = (out / f"{record.experiment_id}.json").read_text(encoding="utf-8")
        assert raw == research_run._record_text(record)
        assert "feasibility" not in json.loads(raw)
    assert research_run.feasibility_report is feasibility_report
