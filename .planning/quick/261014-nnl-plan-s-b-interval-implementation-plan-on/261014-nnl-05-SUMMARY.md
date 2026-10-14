---
phase: quick-261014-nnl
plan: 05
subsystem: backtest report / feasibility / analytics consumers of the terminal settlement
tags: [s-b-interval, settlement, report, feasibility, analytics-lifecycle, tdd]
requires: ["03"]
provides:
  - "src/backtest/report.py: _classify settlement group; settlement trades in the filled coverage population; CountsSection.settlement_count and IntrabarCoverage.settlement_trades (defaulted 0, in their digest payloads only when non-zero)"
  - "src/research/feasibility.py: TradeCounts.settlement, FeasibilityReport.development_settlement, Validation settlement refused, development_settlement rendered only when non-zero"
  - "src/analytics/lifecycle.py: SETTLEMENT_CANCEL in the unfilled backtest kinds"
affects: [quick-261014-nnl plan 06]
key-files:
  created:
    - tests/test_terminal_settlement_consumers.py
  modified:
    - src/backtest/report.py
    - src/research/feasibility.py
    - src/analytics/lifecycle.py
decisions:
  - "settlement_count and settlement_trades join their digest payloads only when non-zero (planner choice confirmed in the index), so every settlement-free report digest and golden is byte-identical"
  - "A settlement is a filled trade for the coverage population (total_trades, fallback_count, percent, coverage_notes) and stays out of every closed-trade figure"
  - "CLOSED_EXIT_KINDS stays exactly {SL, TP2}; the private report set and the feasibility set are both pinned by the new tests as well as by the existing pin test"
  - "lifecycle.py uses the string literal (the module imports nothing from src.backtest; its kinds are literals), with a comment naming semantics.SETTLEMENT_CANCEL"
requirements-completed: []
status: complete
commits: 4
plan_head_before: 9f8cef338776807459b14d4f12169cc6407b9261
plan_head_after: c89357570aeb736969a8b03022810a65dc04b010
actuals:
  tokens: 7400   # chars/4 over the diff 9f8cef3..HEAD (src and tests)
  tasks: 2
  commits: 4
metrics:
  completed: 2026-10-14
---

# Phase quick-261014-nnl Plan 05: Consumers count SETTLEMENT apart Summary

The backtest report, the feasibility report and the analytics lifecycle normalizer now accept the terminal-settlement vocabulary (exit SETTLEMENT, entry SETTLEMENT_CANCEL): a settlement is counted apart from closed trades (never in pooled R, the trade floor or the G1 counts), belongs to the filled coverage population so its fixed note surfaces, is refused inside a Validation fold, and leaves every settlement-free digest and rendered line byte-identical.

## Task results

| Task | Name | Commits | Result |
| ---- | ---- | ------- | ------ |
| 1 | Backtest report and feasibility count SETTLEMENT apart | 7405ad3 (RED), deaa649 (GREEN) | RED: 13 of 15 new tests failed (missing `settlement_count`, `settlement_trades`, `TradeCounts.settlement`, `development_settlement`, SETTLEMENT refused as unknown exit); GREEN: all pass together with the five named neighbour suites |
| 2 | Analytics lifecycle, evidence loader, validator, mark-hole count | bdb8456 (RED), c893575 (GREEN) | RED: 1 failure (`unknown backtest entry_kind 'SETTLEMENT_CANCEL'`); GREEN: lifecycle accepts it |

## What was built

- `report.py`: `_classify` returns a fourth group (SETTLEMENT exits); the refusal message lists END_OF_DATA, SETTLEMENT, SL, TP2. `build` appends the group to `filled_trades` after the END_OF_DATA trades, so `IntrabarCoverage.total_trades`, `fallback_count`, `percent` and `coverage_notes` include settlement trades. `CountsSection.settlement_count` and `IntrabarCoverage.settlement_trades` are last, defaulted fields added to their digest payload only when non-zero. Settlement trades stay out of `closed_trades`, the R distribution, stability, dual-universe slices and drawdown. Docstrings name the three groups.
- `feasibility.py`: `TradeCounts.settlement`; `count_closed_trades` counts `EXIT_SETTLEMENT` apart; `FeasibilityReport.development_settlement` (last, defaulted); `feasibility_report` raises `FeasibilityError` naming the manifest guard when a Validation fold holds a settlement; `render_feasibility` appends `development_settlement=<n> ` after the Development figures only when non-zero.
- `lifecycle.py`: `"SETTLEMENT_CANCEL"` joined `_BACKTEST_UNFILLED_KINDS`; docstring updated.
- Not changed (by plan): `src/research/report.py` (`count_mark_hole_trades` already counts every filled trade whatever its exit kind; `point_summary` reads pooled Validation trades only, where a settlement cannot exist), `src/backtest/validator.py` (already reads the semantics vocabulary), `src/adapters/analytics_files.py` (the loader test was green without a change: its END_OF_DATA check counts only that exit kind and the trade parser goes through the shared non-strict validator).

## Test coverage (tests/test_terminal_settlement_consumers.py, 22 collected tests)

Report: settlement kept out of pooled R and `trade_count` with `counts.digest()` equal to `sha256_hex` of today's seven-key payload plus `settlement_count: 1`; settlement-free `counts.digest()` and `intrabar_coverage.digest()` equal `sha256_hex` of today's seven and six key payloads; `SETTLEMENT_CANCEL` counted as a plan outcome; coverage includes settlement trades and surfaces the plan 03 fixed note (percent 100), a settlement fallback gives fallback_count 1 and percent 50, the RESTING note is not in the filled population; refusal message names all four exit kinds. Feasibility: settlement counted apart, Development figure rendered only when non-zero and the zero-settlement line equals the pre-change text literally, Validation settlement refused, unknown exit still refused, `CLOSED_EXIT_KINDS` pinned at `{SL, TP2}` on both sides. Consumers: validator accepts SETTLEMENT and SETTLEMENT_CANCEL records (strict and non-strict), lifecycle normalizes both, an evidence file with one SETTLEMENT trade and one SETTLEMENT_CANCEL record loads, the fixed settlement notes do not contain `MARK_HOLE_MARKER` and a settlement trade held through a mark hole is still counted.

Test helpers are imported, not copied: `_gap_trade`, `_build_report`, `_make_experiment_record`, `_end_of_data_trade`, `_plan_outcome` (tests/test_backtest_report.py), `LONG_NOTE`, `RESTING_NOTE` (plan 03 tests), `_evidence_with` (tests/test_analytics_files.py), `_outcome` (tests/test_analytics_lifecycle.py), `make_record` (tests/backtest_plan_helpers.py).

## Verification

- `pytest tests/test_terminal_settlement_consumers.py tests/test_research_feasibility.py tests/test_research_report.py tests/test_backtest_report.py tests/test_backtest_mark_hole_coverage.py`: all pass. `pytest tests/test_terminal_settlement_consumers.py tests/test_analytics_files.py tests/test_analytics_lifecycle.py`: all pass.
- Whole suite `pytest -m "not docker"` (AST purity and no-float guards included): 6592 passed, 459 skipped (DB-dependent tests without `TEST_DATABASE_URL`), 28 deselected, exit 0 (plan 04 baseline 6570 + 22 new tests).
- `mypy src`: no issues in 185 files. `ruff check` and `ruff format --check`: clean (541 files). `uv lock --check`: resolved, no change.
- `git diff --name-status 9f8cef3 HEAD`: `M` for the three source files, `A tests/test_terminal_settlement_consumers.py`; no existing test file touched, no deletion; nothing under params/, src/paper/, docs/, .gsd/, package files, `holdout_consumed.json` or any manifest. No version bump (2.0.0).

## Deviations from Plan

1. [Judgement] `src/adapters/analytics_files.py` was not touched: the plan allows a change only if the loader test is red for a reason inside that file, and it was green at RED. The validator, loader and mark-hole tests pin behaviour that already held; the RED evidence for Task 2 is the one lifecycle failure.
2. [Environment] The three source files are CRLF in the working tree (`core.autocrlf=true`, index is LF); edits kept the working-tree line endings and the commits are LF. The new test file is LF.
3. [Style] `_classify` return type uses a module alias `_TradeGroup` to stay inside the 100-column limit (ruff E501); not a behaviour change.
4. [Scope] Four tests beyond the plan's list: digest with settlement carries the count, the refusal message lists the four kinds, the RESTING note is outside the filled population, a settlement trade held through a mark hole is still counted.
5. The branch is `develop`, which the generic executor protected-branch assertion lists; committing there was directed by the caller and the plan, on the main tree with no worktree.

No auth gates. No stubs. No threat flags beyond the plan's threat model (T-nnl-13 mitigated: closed-trade definition pinned, Validation settlement refused; T-nnl-14 mitigated: one vocabulary from semantics, acceptance test per reader).

## Not done (by scope)

Plans 06 to 10: integration through `run_research`, version bump (2.0.0 stays), protocol text, `holdout_consumed.json`, manifest files, ROADMAP and STATE updates, any G2/G3/G4 producer (none exists in src).

## Self-Check: PASSED

`tests/test_terminal_settlement_consumers.py` exists, the four commits (7405ad3, deaa649, bdb8456, c893575) are in `git log`, and `commits: 4` was measured with `git rev-list --count` from the persisted ledger (base 9f8cef3).
