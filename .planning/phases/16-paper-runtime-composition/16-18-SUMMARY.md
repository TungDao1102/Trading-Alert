---
phase: 16-paper-runtime-composition
plan: 18
subsystem: research runner reporting (reporting only)
status: complete
tags: [plateau, bkts-03, mark-hole, oq-1, modeled-costs-per-unit, rev-09, rev-10, time-run, g4-009, d-27, d-29, d-30]

requires:
  - phase: 16-paper-runtime-composition
    provides: "16-12 feasibility report and G5 line; 16-06 research runner (run_research, research_splits, trade lists per window)"
provides:
  - "src/research/plateau.py: plateau_report / render_plateau over the preregistered grid (grid-file order, one-step axis neighbours, existing report figures, no marker or ordering)"
  - "src/research/report.py: render_run_report (feasibility, plateau, mark-hole count per grid point, cost-field limitation, deferred-item statements), count_mark_hole_trades, summarize_trades over src.backtest.report.build"
  - "src/research/run.py: prints the composed report, --time-run flag (perf_counter per split, run log only)"
  - "tests/test_modeled_costs_none_guard.py: REV-09 AST consumer audit plus behavioural None checks"
affects: [16-37 first real research run, 16-41 O-10 restoration of modeled_costs_per_unit, requirements batch (BKTS-03 status)]

requirements-completed: []

actuals:
  tokens: 12350
  tasks: 3
  commits: 6
plan_head_before: 099bbad0279dd9cdb8549740b873040b64216c95
plan_head_after: 94856416f6aa8effdff309d54d6f99aff8db831b
commits: 6

tech-stack:
  added: []
  patterns:
    - "Reporting-only section: grid-file order, no marker/score/order field, forbidden-vocabulary and order-reversal tests"
    - "AST consumer audit pinned as a Counter keyed by (file, enclosing symbol, kind, detail); a new reader fails the test"

key-files:
  created:
    - src/research/plateau.py
    - src/research/report.py
    - tests/test_research_report.py
    - tests/test_modeled_costs_none_guard.py
  modified:
    - src/research/run.py
    - tests/test_research_runner.py

key-decisions:
  - "Per-point plateau figures are the existing src.backtest.report.build outputs over the point's pooled Validation trades (closed_trades, end_of_data_trades, mean_r, median_r, std_r, wins, losses, observed_max_drawdown_r). The bootstrap interval is not shown, so the fixed seed 0 and 100 resamples choose no printed figure."
  - "Axis neighbours: values of one axis are ordered numerically when all parse as Decimal, otherwise by first appearance in the grid file. That orders parameter values, never results."
  - "The mark-hole count is printed once per grid point over every simulated window (Development and Validation) of that point, as a bare count with the OQ-1 sentence; it enters no other figure."
  - "The deferral and max_cost_to_risk statements are printed in every run log, not only with --time-run."

patterns-established:
  - "Run report composition in one place (render_run_report) so section order is pinned by test"

---

BKTS-03 is claimed by this plan's frontmatter but not marked complete here: its REQUIREMENTS status change stays with the requirements batch (D-27), as the plan states.

# Phase 16 Plan 18: Runner reporting - plateau, mark holes, cost-field guard, timing Summary

The research runner now prints a parameter-plateau section (grid order, one-step axis neighbours, existing report figures, no marker), the OQ-1 mark-hole trade count, the `modeled_costs_per_unit` limitation backed by a pinned AST consumer audit, the two deferred-item statements, and optional `--time-run` wall-clock timing per split without tracemalloc.

## Tasks

| Task | Name | Commits |
| ---- | ---- | ------- |
| 1 | Tracer: two-axis grid prints a plateau section in grid order with no ranking | 405179f (RED), 53fdda5 (GREEN) |
| 2 | Mark-hole count (OQ-1 report only) and modeled_costs_per_unit guard with consumer audit | 1c3b97a (RED), 95b4d2d (GREEN) |
| 3 | `--time-run` timing hook without tracemalloc and the untouched-guard statements | 16fec80 (RED), 9485641 (GREEN) |

The Task 1 tracer `<verify>` was re-run end to end after the GREEN commit and passed before expansion (`tests/test_research_report.py`, `test_research_runner.py`, `test_research_feasibility.py`). In Task 2 the guard tests (audit pin, behavioural None checks, report-digest invariance) characterise existing behaviour and passed on first run; the RED for Task 2 is the report-line tests (import error until `count_mark_hole_trades`, `mark_hole_line`, `COST_FIELD_LINE` existed).

## REV-09 consumer audit (re-run 2026-10-09; research S3 list held)

Pinned in `tests/test_modeled_costs_none_guard.py`. Readers of the field on `TradeRecord` values (both preserve None; behavioural tests prove None stays None, never `Decimal("0")`):

| Reader | Kind | None behaviour |
| ------ | ---- | -------------- |
| `src/backtest/experiment.py` `_DECIMAL_TRADE_FIELDS`, iterated only by `_trade_from_dict` | round-trip parse via `_coerce_trade_decimal` | None stays None |
| `src/adapters/analytics_files.py` `_TRADE_DECIMAL_FIELDS`, iterated only by `_check_trade_fields` | evidence-file validation | None skipped; loaded record keeps None |

Same name on values that are NOT trade records (never see a v2 filled record): `src/backtest/engine.py` `_Engine._size_and_register` `sized.modeled_costs_per_unit` x2 (SizedResult bound from `verdict.sized`, passed to REJECT records); `src/risk/types.py` `SizedResult.__post_init__` loop key; `src/risk/sizing.py` `size_position` `_require_decimal` label (None is refused with TypeError); `src/execution/manager.py` `execute_approved_plan` kwargs refusal. Not reads: `__all__` exports in `src/backtest/__init__.py` and `src/backtest/costs.py` (the `costs.modeled_costs_per_unit()` function), and the one writer of None on filled records, `src/backtest/records.py` `build_trade_record`. Additionally the backtest report digest and the research point summary are proven invariant to the field's value (None, "0", "0.0008", "5"), so no figure uses it. Nothing was changed about the field (O-10 / plan 16-41).

## Verification

- `tests/test_research_report.py`, `tests/test_modeled_costs_none_guard.py`, `tests/test_research_runner.py`, `tests/test_research_feasibility.py` pass.
- Full `pytest -m "not docker"` passes with only the known pre-existing `tests/test_cost_parity.py::test_simulator_and_paper_call_evaluate_risk_with_identical_arguments` deselected (deferred-items.md, plan 16-15; not touched here).
- `ruff check`, `ruff format --check` (474 files) and `mypy src` (165 files) clean.
- `git diff 099bbad... -- src/backtest src/core params` is empty.

## Deviations from Plan

None - plan executed as written. Design choices inside the plan's latitude (which existing figures to show, axis ordering, one mark-hole line per grid point, statements printed on every run) are listed under key-decisions.

## Known Stubs

None.

## Threat Flags

None. T-16-42 (plateau used as a selector): grid-file order only, forbidden-word and order-reversal tests, dataclass-field test for marker/score/order names. T-16-43 (None read as zero cost): AST audit plus behavioural checks. T-16-SC: no package installed.

## Self-Check: PASSED

- Created files present: src/research/plateau.py, src/research/report.py, tests/test_research_report.py, tests/test_modeled_costs_none_guard.py.
- Commits present: 405179f, 53fdda5, 1c3b97a, 95b4d2d, 16fec80, 9485641 (6 measured from the plan-head ledger).
