---
phase: quick-261014-nnl
plan: 07
subsystem: backtest
tags: [simulator-semantics, regeneration, version-bump]
requires:
  - phase: quick-261014-nnl
    provides: plans 01-06 (terminal settlement code under the old version string)
provides:
  - SIMULATOR_SEMANTICS_VERSION 2.1.0 in force
  - design test 10 (tests/test_semantics_version_regression.py)
affects: [plan 09 (D070, D071, protocol text)]
key-files:
  created:
    - tests/test_semantics_version_regression.py
  modified:
    - src/backtest/semantics.py
    - src/backtest/lifecycle.py
    - tests/test_backtest_simulator.py
    - tests/test_backtest_terminal_settlement.py
    - tests/test_backtest_engine.py
    - tests/test_backtest_experiment.py
    - tests/test_backtest_lifecycle.py
    - tests/test_backtest_run_summary.py
    - tests/test_analytics_files.py
    - tests/fixtures/phase6/REGRESSION_SNAPSHOTS.md
    - tests/fixtures/phase10/loaders/evidence_sample.json
decisions:
  - "Option S1 for evidence_sample.json: only simulator_semantics_version changed; the stale experiment_id was left as is (user words: approve S1)."
metrics:
  completed: 2026-10-15
status: complete
actuals:
  tokens: 9000
  tasks: 1
  commits: 1
plan_head_before: 22b7f41
---

# Phase quick-261014-nnl Plan 07: simulator semantics 2.1.0 Summary

SIMULATOR_SEMANTICS_VERSION moved 2.0.0 -> 2.1.0 and every version-derived pin, digest and stored record was regenerated from the approved inventory's own commands; design test 10 proves that, without `terminal_settlements`, only `simulator_semantics_version` and `trade_id` move.

Scope: Task 3 only. Task 1 (inventory, 4789c6a) and Task 2 (approval, 22b7f41, "approve S1", inventory sha256 dba5e32b... re-checked unchanged before starting) were done earlier.

## What was done (Task 3, commit ffda8c4)

1. Regression test first (red: version still 2.0.0, the trade_id/version difference assertions failed; the recomputed 2.0.0 hash already matched the inventory).
2. Bump in `src/backtest/semantics.py`; the three comment rewordings the inventory proposed (semantics.py WR-05 note and lines 88-92, lifecycle.py docstring).
3. Regenerated paths (no hash typed):
   - VERSION_PIN, 7 literal lines re-pinned: tests/test_backtest_engine.py:169, tests/test_backtest_experiment.py:803 and :1202, tests/test_backtest_lifecycle.py:154, tests/test_backtest_run_summary.py:167, tests/test_backtest_terminal_settlement.py:200, tests/test_analytics_files.py:507.
   - DERIVED_DIGEST, 9 digests computed with `_digest(run(_case(name)))` by a throwaway script (each old digest asserted to occur exactly once per file): tests/test_backtest_simulator.py, tests/fixtures/phase6/REGRESSION_SNAPSHOTS.md.
   - STORED_RECORD (S1), by the inventory's command: tests/fixtures/phase10/loaders/evidence_sample.json (one line).
4. Design test 10 (`tests/test_semantics_version_regression.py`, 4 tests): patches the constant to 2.0.0 in semantics, records, engine and experiment; checks the recomputed 2.0.0 output against the inventory's sha256 values (scripted_tracer be6cd8a6..., strategy_trigger_no_declaration 4635c92d...); depends only on committed case builders and those two hashes.

## Gates

pytest -m "not docker": 0 failures, 471 skipped (same count as the inventory's host baseline: 453 DB, 12 shellcheck, 6 Windows), 7060 collected (7056 + 4 new), 6589 passed (derived). ruff check, ruff format --check (543 files), mypy src (185 files), uv lock --check: clean.

The PostgreSQL test `tests/test_soak_evidence_export.py::test_the_pg_source_exports_every_record_stored_on_postgresql` stayed SKIPPED (TEST_DATABASE_URL not set): unverified on this host. Its input is the same S1-updated sample, so it is expected to pass where a database exists.

## Deviations from Plan

None in behavior. Two files outside the plan's files_modified (tests/test_backtest_simulator.py, tests/test_backtest_terminal_settlement.py) and REGRESSION_SNAPSHOTS.md were edited, as the user's approval names. The optional leak-check script was not committed (it depends on scratchpad paths and is not trivial); its result is recorded in the inventory (26 cases, 0 other differences).

## Protected paths

`git diff --quiet` for params, src/paper, tests/test_paper_shadow_fill.py, tests/test_backtest_funding.py, docs and docs/research/holdout_consumed.json against the pre-task HEAD: clean. No manifest freeze, no O-03, no Holdout read, no push.

## Self-Check: PASSED
