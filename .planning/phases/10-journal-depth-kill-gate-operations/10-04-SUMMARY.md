---
phase: 10-journal-depth-kill-gate-operations
plan: 04
subsystem: analytics
tags: [analytics, robustness-slices, dual-universe, no-trade, decimal, determinism, golden-fixtures, tdd]

requires:
  - phase: 10-journal-depth-kill-gate-operations
    provides: "10-01 analytics core: EvidenceKind, TradeOutcome, Estimate, stats helpers (estimate_mean, ordered_r_values, seed_for, is_low_n), purity/typing guards"
  - phase: 06-backtest
    provides: "LIVE5_SYMBOLS, _universe_hash / ExperimentRecord.universe_hash, _decimal_median, _max_drawdown, DualUniverseSection weak-live-universe rule"
provides:
  - "CoreMetrics / compute_core_metrics: reusable M-1 metric block (n, R-valued, zero-risk excluded, incomplete, mean R with interval, median, win rate, expectancy, max drawdown R, loss streak, low_n flag)"
  - "SlicesSection / SliceTable / SliceRow / build_slices: eight METRICS section 5 dimensions, ALL row first, stable favorability-blind ordering, UNKNOWN then INCOMPLETE pinned last, SESSION_BANDS, SLICE_VOCABULARY_VERSION slices/1, session_for"
  - "DualUniverseView / build_dual_universe / verify_research_universe: live-5 (imported) vs research side by side, explicit no-data live-5, VERIFIED / UNVERIFIED_UNIVERSE / NOT_APPLICABLE"
  - "NoTradeSection / count_no_trades / no_trade_from_paper / NO_TRADE_CATEGORY_BY_REASON: five protocol categories plus UNMAPPED and Total, split live-5 / research / all"
affects: [10-05, 10-06, 10-07, 10-08, 10-09, 10-10, 10-11, 10-12]

actuals:
  tokens: 31000
  tasks: 3
  commits: 6
plan_head_before: 98bdd1d934e761e8032fe3aad0f630ed665b9c86
plan_head_after: 572b8969bdf6b867af85304154658e581551b99e

tech-stack:
  added: []
  patterns:
    - "Every slice row is a CoreMetrics projection; the ALL row of every table is identical to the full report so a slice can never disagree with Section 3"
    - "Slice ordering is an explicit per-dimension total key (session by band index, direction LONG then SHORT, else A-Z on zero-padded labels), never a metric value; per-row bootstrap seed = base_seed + display ordinal (ALL = 0)"
    - "Universe sets are never held twice: LIVE5_SYMBOLS imported from src.backtest.report (source-level AST/text test), research symbols are evidence input"

key-files:
  created:
    - src/analytics/core_metrics.py
    - src/analytics/slices.py
    - src/analytics/universe.py
    - src/analytics/no_trade.py
    - tests/test_analytics_slices.py
    - tests/test_analytics_dual_universe.py
    - tests/test_analytics_no_trade.py
    - tests/fixtures/phase10/low_n_slices/
    - tests/fixtures/phase10/empty_live5_slice/
    - tests/fixtures/phase10/no_trade_categories/
  modified:
    - tests/phase10_helpers.py

key-decisions:
  - "An outcome is R-valued only when R is defined AND it has an exit time (the R series is ordered by exit_time_utc, trade_id via stats.ordered_r_values); any other non-zero-risk outcome is counted incomplete, never imputed"
  - "low_n is computed on the estimate sample size n_r_valued and is a display flag only - LOW_N_THRESHOLD is never an acceptance gate"
  - "Slice time bases pinned: month/quarter from EXIT time (YYYY-MM, YYYY-Qn), session from ENTRY-time UTC hour bands ASIA 00-08 / EUROPE 08-16 / US 16-24 (start-inclusive, end-exclusive); missing basis time -> INCOMPLETE bucket, absent tag -> UNKNOWN bucket"
  - "trend_range_regime maps BULLISH/BEARISH -> TREND, NEUTRAL -> RANGE, other non-empty tags verbatim (flagged assumption A4); volatility_regime is the outcome tag or UNKNOWN"
  - "The live-5 and research views overlap by design (side by side, not additive); live-5 and research bootstrap ordinals are 0 and 1 so their intervals use distinct seeds"
  - "Research universe hash compares _universe_hash(sorted, de-duplicated symbols) with the recorded ExperimentRecord hash; no hash supplied -> NOT_APPLICABLE (paper/live evidence)"
  - "NO_TRADE reason mapping (plan assumption): NO_TRADE_REGIME->REGIME_FILTER; RR_TOO_LOW->RR_FLOOR; MAX_POSITIONS_REJECT/SKIPPED_BUSY->OPEN_POSITION_CONFLICT; DATA_STALE/STALE_CONSTRAINTS/UNCERTAIN_ACCOUNT_STATE/RECONCILIATION_REQUIRED->DATA_UNAVAILABILITY; INSUFFICIENT_EDGE->KILL_GATE_TRIP; anything else UNMAPPED (counted)"

patterns-established:
  - "Evidence kinds are never pooled: build_slices, build_dual_universe and count_no_trades take one EvidenceKind and raise AnalyticsInputError on mixed evidence"
  - "Empty input still yields a labelled section (ALL row n 0 / no-data slices), never an omitted one"

requirements-completed: [JRN-01, GOV-01]

coverage:
  - id: D1
    description: "Tracer: CoreMetrics block and the SYMBOL slice table with the ALL row first, low-n rows retained, shuffle-invariant ordering"
    requirement: JRN-01
    verification:
      - kind: unit
        ref: "tests/test_analytics_slices.py#test_tracer_core_metrics_and_symbol_slice"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_slices.py#test_tracer_all_row_equals_core_metrics_field_by_field"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_slices.py#test_tracer_symbol_rows_ascending_regardless_of_input_order"
        status: pass
    human_judgment: false
  - id: D2
    description: "All eight METRICS section 5 slice dimensions with pinned exit/entry time bases, session boundary mapping, UNKNOWN/INCOMPLETE buckets, favorability-blind ordering and per-row seeds"
    requirement: JRN-01
    verification:
      - kind: unit
        ref: "tests/test_analytics_slices.py#test_all_dimension_rows_match_hand_computed_fixture"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_slices.py#test_session_boundary_mapping_start_inclusive_end_exclusive"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_slices.py#test_ordering_ignores_results_best_slice_is_not_promoted"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_slices.py#test_pinned_full_section_digest"
        status: pass
    human_judgment: false
  - id: D3
    description: "Dual-universe view: live-5 vs research side by side, empty live-5 is explicit no data, research universe VERIFIED or UNVERIFIED_UNIVERSE, weak-live-universe rule mirrors Phase 6, LIVE5_SYMBOLS imported not copied"
    requirement: JRN-01
    verification:
      - kind: unit
        ref: "tests/test_analytics_dual_universe.py#test_empty_live5_slice_is_explicit_no_data_and_universe_verified"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_dual_universe.py#test_unverified_universe_when_expected_hash_is_wrong"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_dual_universe.py#test_weak_live_universe_rejection_when_research_positive_and_live5_not"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_dual_universe.py#test_live5_symbols_imported_never_a_third_copy"
        status: pass
    human_judgment: false
  - id: D4
    description: "NO_TRADE counted by the five protocol reason categories plus UNMAPPED and Total, split live-5 / research / all; paper NO_TRADE extraction excludes opportunity and signal-chain rows"
    requirement: GOV-01
    verification:
      - kind: unit
        ref: "tests/test_analytics_no_trade.py#test_count_by_category_matches_fixture_with_unmapped_and_total"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_no_trade.py#test_unmapped_is_counted_never_dropped"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_no_trade.py#test_no_trade_from_paper_keeps_only_system_rows_without_signal"
        status: pass
    human_judgment: false
  - id: D5
    description: "That the pinned session bands, LOW_N_THRESHOLD and reason-category mapping (flagged research assumptions A1/A2/A4) are the reporting vocabulary the operator wants kill-gate evidence to cite"
    requirement: JRN-01
    verification: []
    human_judgment: true
    rationale: "The constants are pinned into golden fixtures and documented as assumptions; whether they are the right descriptive conventions is a research-owner judgment, not something a test can assert"

duration: 27min
completed: 2026-09-29
status: complete
---

# Phase 10 Plan 04: Robustness Slices, Dual-Universe View and NO_TRADE Categories Summary

**Pure, digest-stamped robustness slices over all eight METRICS section 5 dimensions (ALL row first, favorability-blind order, low-n flagged not dropped), a live-5 vs research-universe view that renders an empty live-5 as explicit no data with a verified/unverified universe hash, and NO_TRADE counts by the five protocol reason categories plus an UNMAPPED catch-all.**

## Performance

- **Duration:** ~27 min (wall-clock)
- **Completed:** 2026-09-29
- **Tasks:** 3 (1 tracer + 2 auto), all TDD with separate RED then GREEN commits
- **Files:** 4 source modules, 3 test modules, 3 fixture sets (plus a shared helper addition)

## Accomplishments

- `compute_core_metrics` is the single M-1 block: counts (n, R-valued, zero-risk excluded, incomplete), mean R via the Phase-6 seeded stationary bootstrap (interval or explicit interval-absent marker), median, win rate as an exact Decimal fraction, expectancy (= mean R, already net of modeled costs), max drawdown R and longest loss streak over R ordered by (exit time, trade id).
- `build_slices` renders the eight dimensions in fixed order. Every table is `ALL` first (identical to the full report), then rows in an explicit documented key order, then `UNKNOWN`, then `INCOMPLETE`. Month/quarter use exit time (F3 entered in March, exited 2026-04-01, lands in April / Q2), session uses the entry-time UTC hour (07:59:59 ASIA, 08:00:00 EUROPE, 15:59:59 EUROPE, 16:00:00 US, 23:59:59 US). A test pins that the best-mean slice is not promoted (the best strategy version sorts last) and that shuffled input yields an identical section digest.
- `build_dual_universe` puts live-5 (imported `LIVE5_SYMBOLS`) and research metrics side by side; an empty live-5 slice has n 0 and every estimate None; the weak-live-universe flag uses the Phase-6 rule (research mean > 0 and live-5 mean <= 0).
- `count_no_trades` returns the six fixed-order category rows plus Total; unrecognized reason codes fall to `UNMAPPED` and are counted in Total.

## Task Commits

1. **Task 1 RED:** `6a11c77` test(10-04): failing core metrics and symbol slice tracer tests
2. **Task 1 GREEN:** `0504d73` feat(10-04): core metric block and symbol slice table with ALL row first
3. **Task 2 RED:** `30c9315` test(10-04): failing eight-dimension slice tests with pinned time bases
4. **Task 2 GREEN:** `7e13db0` feat(10-04): eight slice dimensions with pinned time bases and stable ordering
5. **Task 3 RED:** `2169551` test(10-04): failing dual-universe and NO_TRADE category tests
6. **Task 3 GREEN:** `572b896` feat(10-04): dual-universe view and NO_TRADE counts by reason category

## Files Created/Modified

- `src/analytics/core_metrics.py` - CoreMetrics, compute_core_metrics.
- `src/analytics/slices.py` - SliceDimension, SliceRow, SliceTable (with `display_rows`), SlicesSection, SESSION_BANDS, SLICE_VOCABULARY_VERSION, session_for, build_slices.
- `src/analytics/universe.py` - VERIFIED / UNVERIFIED_UNIVERSE / NOT_APPLICABLE, DualUniverseView, verify_research_universe, build_dual_universe.
- `src/analytics/no_trade.py` - NoTradeCategory, NO_TRADE_CATEGORY_BY_REASON, NoTradeRow, NoTradeSection, category_for, no_trade_from_paper, count_no_trades.
- `tests/test_analytics_slices.py`, `tests/test_analytics_dual_universe.py`, `tests/test_analytics_no_trade.py` - tracer, dimensions, boundaries, ordering, shuffle, no-data, universe status, mapping, source-level no-third-copy guards.
- `tests/fixtures/phase10/{low_n_slices,empty_live5_slice,no_trade_categories}/` - hand-authored inputs and hand-computed pinned expectations (digests pinned).
- `tests/phase10_helpers.py` - added `make_outcome` / `make_outcomes` shared TradeOutcome builders.

## Decisions Made

See `key-decisions` above. The most consequential are the pinned time bases (exit time for month/quarter, entry-time UTC bands for session) and the NO_TRADE reason-to-category mapping; both are documented plan assumptions pinned into golden fixtures, so changing them later changes every pinned digest.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Shared TradeOutcome builders added to tests/phase10_helpers.py**
- **Found during:** Task 1 (RED)
- **Issue:** All three test modules build `TradeOutcome`s from JSON fixtures; the plan's file list did not include the shared helper module.
- **Fix:** Added `make_outcome` / `make_outcomes` (no behavior change to existing helpers).
- **Files modified:** tests/phase10_helpers.py
- **Commit:** 6a11c77

**2. [Rule 3 - Blocking] Phase-6 helpers imported from src.backtest.report, not via stats**
- **Found during:** Task 1 (GREEN)
- **Issue:** `stats._decimal_median` / `stats._max_drawdown` are not explicit re-exports, so mypy strict (guarded by tests/test_analytics_typing.py) rejected them.
- **Fix:** `core_metrics.py` imports them directly from `src.backtest.report` (the same Phase-6 helpers, still guarded by the pinned digests).
- **Files modified:** src/analytics/core_metrics.py
- **Commit:** 0504d73

**3. [Rule 2 - Missing critical] R-valued requires an exit time; empty-R metrics are None**
- **Found during:** Task 1 design
- **Issue:** `stats.ordered_r_values` silently skips an outcome that has R but no exit time, and the Phase-6 `_max_drawdown` / `_decimal_median` return 0 on an empty series - a fabricated zero would read as a real measurement.
- **Fix:** `n_r_valued` is the length of the ordered R series (so counts and estimates agree), the remainder is counted `incomplete`, and median/win rate/expectancy/drawdown/loss streak are None when there is no R value.
- **Files modified:** src/analytics/core_metrics.py
- **Commit:** 0504d73

**4. [Additive] SliceTable.display_rows and SliceRow.zero_risk_excluded**
- **Issue:** Downstream renderers need "ALL first" as one sequence, and hiding the zero-risk exclusion count in slices would contradict the no-silent-exclusion rule.
- **Fix:** Added a `display_rows` property (`(all_row, *rows)`) and a `zero_risk_excluded` field on `SliceRow`; neither changes any planned field.
- **Commit:** 0504d73, 7e13db0

**5. [Note - RED evidence] RED for new-module tests is a collection ImportError**
- Task 1 and Task 3 REDs fail with `ModuleNotFoundError` (the modules did not exist yet), matching the plan 10-03 practice. Task 2 RED fails on real assertions (one dimension present instead of eight, missing `session_for`, unpinned digest) since the modules existed.

**Total deviations:** 4 auto-fixed (1 missing-critical, 2 blocking, 1 additive) plus 1 RED-evidence note. **Impact:** no scope creep; all strengthen the no-imputation and single-source guarantees.

## Issues Encountered

- mypy strict flagged the private re-export access above and was fixed before the Task 1 GREEN commit. The pre-existing `src/adapters/telegram_notify.py` mypy error is unchanged and out of scope. `ruff format` was run only on files created in this plan.

## Verification

- `pytest tests/test_analytics_dual_universe.py tests/test_analytics_no_trade.py tests/test_analytics_slices.py tests/test_analytics_purity.py tests/test_analytics_typing.py`: all pass (47 tests).
- `pytest tests/test_backtest_report.py` plus the other analytics test modules (digest, lifecycle, latency, excursion, incomplete): all pass - Phase 6 helpers untouched.
- `ruff check src/analytics` and the three new test modules: clean. `mypy src/analytics`: clean (only the pre-existing telegram_notify error remains repo-wide).

## Known Stubs

None. Empty/None values are the explicit no-data representation by design, not placeholders.

## Threat Flags

None. No new endpoints, auth paths, file access or schema changes. T-10-10 (slice cherry-picking), T-10-11 (universe drift/unverified hash) and T-10-12 (unmapped reason codes dropped) are mitigated as specified and pinned by tests.

## Next Phase Readiness

Ready for the report plans: `SlicesSection`, `DualUniverseView` and `NoTradeSection` are the stable, digest-stamped contracts the S-1 / U-1 / K-3 renderers consume (`SliceTable.display_rows` gives the ALL-first sequence; `NoTradeSection.total` is the Total row).

## Self-Check: PASSED

- All created source, test and fixture paths exist on disk; the six task commits (6a11c77, 0504d73, 30c9315, 7e13db0, 2169551, 572b896) are present in `git log`.
- TDD gates: RED `test(10-04)` commits precede each GREEN `feat(10-04)` commit; no REFACTOR commit was needed.
