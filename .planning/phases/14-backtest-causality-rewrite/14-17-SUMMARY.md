---
phase: 14-backtest-causality-rewrite
plan: 17
subsystem: backtest-simulator
tags: [backtest, lifecycle, mark-price, coverage-note, annotation, tdd, gap-closure]

requires:
  - phase: 14-backtest-causality-rewrite
    provides: "14-01..14-16: the v2 lifecycle driver, WR-09 closing-bar fallback, engine, report and frozen protocol v2.0.0"
provides:
  - "PlanState.mark_settled_through_utc: internal settle marker, never copied into a record"
  - "Minute-continuity hole scan in advance: a gap of more than one minute between consecutive walked mark minutes (or the minute before the fill minute and the first walked minute) is noted in coverage_note, in every window including hours with no strategy bar"
  - "END_OF_DATA trailing note for whole minutes missing between the settle marker and the data end"
  - "tests/test_backtest_mark_hole_coverage.py: engine-to-report tracer plus 11 lifecycle tests (12 tests)"
  - "BACKTEST_SPEC section 4 paragraph (annotation only) and the deferred-items From plan 14-17 entry"
affects: [15-strategy-geometry-research-runner]

requirements-completed: [BKTS-01]

actuals:
  tokens: 21000
  tasks: 3
  commits: 5
plan_head_before: 0cccae501ba5aafd85f99d7ce443a77743ac4549
plan_head_after: fbd93dd16cb051d092b33a72bedb0534410e0af7

tech-stack:
  added: []
  patterns:
    - "Detection by minute continuity between consecutive walked mark minutes, not by an expected-minute grid: no window-boundary or close-offset convention, same notes however windows are cut"
    - "One replace per advance call, never per minute; a monotonic settle marker makes re-advancing a walked window a no-op"

key-files:
  created:
    - tests/test_backtest_mark_hole_coverage.py
  modified:
    - src/backtest/lifecycle.py
    - tests/test_backtest_exits.py
    - docs/backtest/BACKTEST_SPEC.md
    - .planning/phases/14-backtest-causality-rewrite/deferred-items.md

key-decisions:
  - "Annotate-only: a mark hole outside a closing-bar fallback is recorded in coverage_note and nothing else changes (no event, price, time, cost, fallback_applied or count); what a hole should do to a trade is OQ-1, left to the user"
  - "SIMULATOR_SEMANTICS_VERSION stays 2.0.0: nothing the simulator prices or books changes"
  - "The accepted double note (a mid-bar window sees a hole, the later closing-bar scan resolves the same hole by fallback) is documented by a test, not de-duplicated"

duration: about 12 min (36 to 48 minutes past 10 local, 2026-10-07)
completed: 2026-10-07
status: complete
---

# Phase 14 Plan 17: Mark-hole coverage notes Summary

Mark-price holes inside the life of an open position are now recorded in the trade's `coverage_note` in every window (including an hour in which the symbol has no strategy bar and the trailing minutes before the data end), by annotation only; UAT test 6 (G-14-06) and the remaining half of WR-09 are closed.

BASE (git rev-parse HEAD before Task 1): `0cccae501ba5aafd85f99d7ce443a77743ac4549`.

## What changed

- `src/backtest/lifecycle.py` only: new last field `PlanState.mark_settled_through_utc`; `_fill` sets it to the minute before the fill minute; the RESTING fill branch moves it to the fill mark minute; the OPEN loop of `advance` compares each walked minute with the marker, collects notes and applies ONE `replace`; the fallback block sets the marker to the last minute of the bar; a hole straddling the bar open gets a continuity note for the part before the bar region; `finalize_at_data_end` notes whole minutes missing before the data end (a partial last minute is never reported). New helpers `_skipped_span`, `_skipped_note`, `_join_notes`, `_last_minute_open` (the last is also used by `_first_missing_mark_open`, a pure refactor). No import added, no float.
- `tests/test_backtest_mark_hole_coverage.py`: Tests A to L (12 tests).
- `tests/test_backtest_exits.py`: one assertion in `test_a_window_that_ends_mid_bar_never_resolves_a_hole` (whole-state equality replaced by the marker check at 12:14 plus equality with the marker reset) and the `replace` import. This is the only existing assertion that changed (the planner's measured blast radius was exactly this one; observed: the same).
- `docs/backtest/BACKTEST_SPEC.md`: one paragraph in section 4 after the fallback paragraph (contains "annotation only").
- `.planning/phases/14-backtest-causality-rewrite/deferred-items.md`: "## From plan 14-17" entry, placed above the existing "Open decisions for the user" section so that section stays last. The OQ-1 text in that section (commit 4cfcca6) was neither reworded nor duplicated; the 14-17 entry points to it and gives the recommended default.

## Scope of the "no change" claim

No change for hole-free input: the 16 goldens, the pinned regression digests in `tests/test_backtest_simulator.py`, the determinism digests and the phase 6 and phase 7 fixture suites pass with no edit under `params/` or `tests/fixtures/`, and `SIMULATOR_SEMANTICS_VERSION` stays 2.0.0. For input with a hole inside a position's life only the `coverage_note` text moves, and with it the trade payload bytes and the hashes derived from them (experiment record, digests of such a run); the semantics version is unchanged. No event, price, time, cost, `fallback_applied`, `fallback_count`, coverage percent or `run_summary` value of such a trade changes (Test A compares the whole trade and run_summary against the hole-free run).

## TDD evidence

Round 1 (commit fb6f3c8 `test(14-17)` before 1c7291e `feat(14-17)`):
- Failed in RED, all with an assertion on `coverage_note` being None, not an import error: `test_tracer_mark_hole_in_a_bar_less_window_is_noted_and_reaches_the_report` (A), `test_a_hole_in_an_hour_with_no_strategy_bar_is_noted_and_changes_nothing` (C), `test_a_stop_after_the_hole_is_not_changed_and_the_closed_trade_keeps_the_note` (D).
- Passed from the start by design (guard): `test_a_hole_free_run_carries_no_note_and_keeps_the_oracle_pnl` (B).
- Test A's report step was run once before committing RED (a scratch probe, not committed): `report.build` accepts the one-trade list of the hole-free tracer and returns percent 100, fallback_count 0, total_trades 1, empty coverage_notes. The plan-checker's concern (a one-trade `build` unexercised) did not materialize and no relaxation to the `_classify` path was needed.

Round 2 (commit 7e3ca94 `test(14-17)` before 3de7208 `feat(14-17)`):
- Failed in RED for the predicted reasons: E `test_a_hole_that_straddles_the_bar_open_gets_one_note_before_the_bar_and_the_fallback` (only the fallback note existed, so the two-part split raised), F `test_no_second_note_after_a_fallback_resolved_hole` (two occurrences of the prefix because the marker was stale after the fallback), H `test_end_of_data_notes_the_minutes_missing_before_the_data_end` (no trailing note), J `test_re_advancing_a_walked_window_adds_nothing_and_never_moves_the_marker_back` (marker moved back to 10:59).
- Green from the start (honest unexpected-green; they are guards, not RED proof): G `test_a_hole_on_the_fill_minute_without_a_bar_is_noted_at_the_next_walked_minute`, I `test_hour_by_hour_and_one_window_give_the_same_state_and_notes`, K `test_a_noted_closed_trade_passes_the_record_validator`, L `test_a_hole_seen_mid_bar_and_resolved_at_the_bar_close_carries_both_notes`, and the two complements inside H (complete data, partial last minute) which sit in the same test function as the failing trailing case.

## Verification

Run file by file, one pytest process per file, all passing: the 27 test files of the Task 3 list (mark_hole_coverage, exits, lifecycle, expiry_clock, entry, engine, engine_strategy, goldens, simulator, determinism, chain, records, report, experiment, run_summary, purity, phase14_fixture_generator, phase6_fixture_scenarios, smoke_backtest_cli, analytics_files, analytics_cli, cost_parity, paper_parity, r_denominator_parity, domain_no_float, decision_alignment_protocol, kill_gate_docs). `ruff check src tests`, `ruff format --check src tests` (371 files formatted), `mypy src` (149 files, no issues) and `scripts/verify_decision_alignment.py all` (`ALL_PASS all`) are clean.

Acceptance checks: `grep -c "annotation only"` BACKTEST_SPEC = 1; `grep -c "From plan 14-17"` deferred-items = 1; `git diff --name-only BASE HEAD` over `params tests/fixtures docs/research docs/DECISIONS.md docs/DOC_STATUS.md exits.py engine.py records.py report.py semantics.py` prints nothing; the `src tests docs params scripts` diff lists only `docs/backtest/BACKTEST_SPEC.md`, `src/backtest/lifecycle.py`, `tests/test_backtest_exits.py`, `tests/test_backtest_mark_hole_coverage.py` (all in `files_modified`); commit order is test before feat in both rounds.

Not run here: PostgreSQL, docker, bootstrap and deploy tests (CI-only), and the real-data smoke script (manual-only). No backtest, research or smoke run was made; only unit and golden tests.

## Deviations from Plan

None - plan executed exactly as written. Two bookkeeping choices: the deferred-items section sits above the existing "Open decisions" section rather than at the very end (so that section stays last); the docs commit (fbd93dd) was made before this SUMMARY so that `commits: 5` and `plan_head_after` are measured values of the code and docs work, and the SUMMARY/STATE/ROADMAP commit follows it.

Threat register: T-14-34 to T-14-37 mitigations are in place (continuity scan and trailing note, Test A whole-trade comparison, byte-identical hole-free suites, note text states the stop and targets were not evaluated minute by minute). No new network, auth or file-access surface.

## Known Stubs

None.

## Notes for the user

- **OQ-1 (not decided): how a trade held through unresolved mark holes is treated in the evidence.** Such a trade is now annotated in `coverage_note` and reaches the report's `intrabar_coverage.coverage_notes`, but still counts as a normal trade: `fallback_applied`, `fallback_count`, the coverage percent and the experiment record do not change. Counting it against coverage, excluding it from pooled R or voiding it each needs a typed counter, a `run_summary` key, an `ExperimentRecord` field and a deliberate digest regeneration; that is a money and evidence choice. Recommended default if you do not answer: keep annotate-only until the Phase 15 research runner decides the evidence format. The full entry is under "Open decisions for the user" in `deferred-items.md`.
- **Informational:** `SIMULATOR_SEMANTICS_VERSION` stays 2.0.0. No non-test experiment record exists (D052 voids all earlier evidence and no runner calls `assemble` outside tests), so the changed note text of a hole-bearing run cannot invalidate a stored record today. If the manual 14-14 smoke run is repeated and only its digest moves while trades, prices and counts match, the real data has mark holes inside a position's life.

## Self-Check: PASSED

- Created file exists: `tests/test_backtest_mark_hole_coverage.py` (12 tests).
- Commits exist: fb6f3c8, 1c7291e, 7e3ca94, 3de7208, fbd93dd (`git log --oneline` shows all five; `git rev-list --count BASE..HEAD` = 5 at SUMMARY write).
- All task acceptance criteria re-run and passing.
