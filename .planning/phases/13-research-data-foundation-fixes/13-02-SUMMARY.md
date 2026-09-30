---
phase: 13-research-data-foundation-fixes
plan: 02
subsystem: data-backfill
tags: [backfill, parquet, atomic-write, quality-gate, closed-day, zero-trade, decimal]

requires:
  - phase: 02-data-layer
    provides: kline paginator, quality gate, immutable per-day Parquet store, cursor store
provides:
  - "Backfill publishes only whole closed UTC days: effective end = min(end_ms, start of current UTC day), partial days held back and counted (BackfillResult.partial_days_held), terminal_end for a delivered contract's last day"
  - "KlineSource Protocol (keyword-only klines signature) so REST adapter and the 13-05 archive source share one validation and publish path"
  - "atomic_write_parquet (same-directory tmp, fsync, exists check, bounded os.replace retry) behind publish_batch; existing files still raise FileExistsError"
  - "Quality gate accepts zero-trade bars as telemetry (zero_trade_bars) and structurally rejects more than 8 fractional digits or non-finite Decimals (bad_decimals)"
affects: [13-03, 13-05, 13-06, 13-07, research-backfill, sufficiency-report]

actuals:
  tokens: 10063
  tasks: 3
  commits: 6
plan_head_before: 9ea7e8f7647732980147507c693c036ecc7525f0
plan_head_after: 9fd624e9cb3f56cd9a6a5872e04b4f3d6a2faaca

tech-stack:
  added: []
  patterns:
    - "Closed-day flush: buffered dates publish only when start-of-day + 86_400_000 <= effective_end (or terminal last day); everything else is held, logged and counted"
    - "Atomic immutable publish: hidden same-directory .<name>.<pid>.tmp, fsync, existence check, os.replace with bounded PermissionError retry, tmp removed in finally"
    - "Structural Protocol (KlineSource) instead of a concrete adapter type at the paginator boundary"
    - "Bad rows are counted then excluded before any Decimal comparison or Polars projection (Polars panics on NaN Decimals)"

key-files:
  created:
    - tests/test_backfill_closed_day.py
    - tests/test_store_atomic.py
  modified:
    - src/data/backfill.py
    - src/data/store.py
    - src/data/quality.py
    - tests/test_quality_gates.py
    - tests/test_backfill.py
    - tests/test_tracer_slice.py

key-decisions:
  - "Closed-day clamp applies to every run; terminal_end only counts when the caller's own end_ms is already a closed past instant (a clamped end is never terminal)"
  - "Days are held when the window did not cover them, never published short; the cursor is never written for held rows, so a later run refetches the whole day"
  - "Precision guard follows the plan (as_tuple exponent below -8): a value with trailing zeros beyond 8 digits is rejected too, because Polars would infer scale 9 and drift the Parquet schema"
  - "The paginator start_ms is not day-aligned by the paginator itself; callers (backfill_universe) already align, and the docstring says so"

patterns-established:
  - "Rewrite, never delete, tests whose old behavior changed on purpose; list each before/after in the SUMMARY (D-29)"

requirements-completed: [DATA-01]

coverage:
  - id: D1
    description: "Backfill never publishes the current UTC day; partial past days are held back (counted, cursor untouched) unless terminal_end marks a delivered contract's last day"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_backfill_closed_day.py#test_current_utc_day_is_never_published"
        status: pass
      - kind: unit
        ref: "tests/test_backfill_closed_day.py#test_partial_past_day_is_held_back_unless_terminal"
        status: pass
      - kind: unit
        ref: "tests/test_backfill_closed_day.py#test_resume_publishes_only_the_next_closed_day"
        status: pass
      - kind: unit
        ref: "tests/test_backfill_closed_day.py#test_listing_day_with_late_first_bar_is_published"
        status: pass
    human_judgment: false
  - id: D2
    description: "Published Parquet is written atomically; an interrupted write leaves no torn file or temporary file; an existing file is never overwritten"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_store_atomic.py#test_interrupted_write_leaves_no_partial_file"
        status: pass
      - kind: unit
        ref: "tests/test_store_atomic.py#test_existing_file_is_never_overwritten"
        status: pass
      - kind: unit
        ref: "tests/test_store_atomic.py#test_transient_permission_error_is_retried"
        status: pass
      - kind: unit
        ref: "tests/test_store_atomic.py#test_publish_after_a_simulated_crash_matches_a_clean_write"
        status: pass
    human_judgment: false
  - id: D3
    description: "Zero-trade bars pass the gate as telemetry; excess-precision or non-finite Decimals are structurally rejected"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_quality_gates.py#test_zero_trade_bar_is_accepted_and_counted"
        status: pass
      - kind: unit
        ref: "tests/test_quality_gates.py#test_excess_precision_is_rejected"
        status: pass
      - kind: unit
        ref: "tests/test_quality_gates.py#test_non_finite_decimal_is_rejected_without_raising"
        status: pass
      - kind: unit
        ref: "tests/test_backfill_closed_day.py#test_zero_trade_bars_are_published_with_the_rest_of_the_day"
        status: pass
    human_judgment: false
  - id: D4
    description: "Paginator accepts any object with the kline fetch signature (KlineSource) and feeds the same gate and store"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_backfill_closed_day.py#test_any_object_with_the_kline_signature_is_a_source"
        status: pass
      - kind: other
        ref: ".venv/Scripts/python -m mypy src/data/backfill.py src/data/store.py src/data/quality.py"
        status: pass
    human_judgment: false

duration: 15min
completed: 2026-09-30
status: complete
---

# Phase 13 Plan 02: Backfill Writer-Path Hardening Summary

**The single Parquet writer path now publishes only whole closed UTC days, writes atomically (tmp, fsync, os.replace, no overwrite), accepts zero-trade bars as telemetry, and rejects excess-precision or non-finite Decimals, all behind a KlineSource Protocol so an archive source can reuse it.**

## Performance

- **Duration:** about 15 min
- **Completed:** 2026-09-30T13:39Z
- **Tasks:** 3 (1 tracer, 2 auto; all TDD, RED then GREEN each)
- **Files modified:** 8 (2 created, 6 modified)

## Accomplishments

- `backfill_symbol_interval` clamps to `min(end_ms, start of the current UTC day)`, drops rows at or after that end before buffering, and at the end-of-loop flush publishes a date only when its whole day lies inside the window (or it is the terminal last day). Held days are logged (`backfill.partial_day_held`), counted, and never advance the cursor. `backfill.clamped_to_closed_days` is logged when the clamp bites.
- `utc_ms` (integer timedelta arithmetic, rejects naive datetimes) replaces every `timestamp() * 1000` in the paginator; `DAY_MS` and the `KlineSource` Protocol are new; the adapter parameter of `fetch_page_with_retry`, `backfill_symbol_interval` and `backfill_universe` is typed `KlineSource`.
- `atomic_write_parquet` in `store.py` (`REPLACE_MAX_ATTEMPTS = 5`, `REPLACE_RETRY_SLEEP_SECONDS = 0.1`); `publish_batch` keeps its `exists()` guard and writes through it.
- `quality.py`: trade count rejected only when negative, `zero_trade_bars` and `bad_decimals` added to `QualityVerdict` (defaults 0), `MAX_FRACTION_DIGITS = 8`, `_is_bad_decimal`. Bad-decimal rows are counted and excluded before the frame is built (Polars panics on `Decimal("NaN")`).

## Task Commits

1. **Task 1 (tracer): closed-day publishing** - RED `c6f8ee2` (test), GREEN `825fea9` (feat, includes the seven rewritten tests)
2. **Task 2: atomic immutable publish** - RED `d6c6a1e` (test), GREEN `81ace61` (feat)
3. **Task 3: zero-trade acceptance and precision guard** - RED `545509e` (test), GREEN `9fd624e` (feat)

**Plan metadata:** committed separately (docs: complete plan).

Tracer gate: the tracer `<verify>` (pytest, mypy, ruff) was re-run end to end after Task 1 and passed, so expansion proceeded (`HUMAN_VERIFY_MODE` end-of-phase, automated-only verify).

## Files Created/Modified

- `src/data/backfill.py` - closed-day rule, `KlineSource`, `utc_ms`, `DAY_MS`, `terminal_end`, `partial_days_held`.
- `src/data/store.py` - `atomic_write_parquet` and retry constants; `publish_batch` uses it.
- `src/data/quality.py` - zero-trade acceptance, precision guard, two new verdict fields.
- `tests/test_backfill_closed_day.py` (new, 8 tests), `tests/test_store_atomic.py` (new, 10 tests), 7 cases added to `tests/test_quality_gates.py`.
- `tests/test_backfill.py`, `tests/test_tracer_slice.py` - rewritten tests (below).

## Deliberately Rewritten Tests (D-29)

No test was deleted. Each kept its name and subject; only the window or expectation moved to satisfy the closed-day rule.

| Test | Before | After |
|------|--------|-------|
| `test_backfill.py::test_windowed_cursor_emits_every_expected_candle` | 3 pages of 5 bars, end mid-day, 15 rows | 3 pages of 8 bars, end at the next day boundary, 24 rows |
| `test_backfill.py::test_forming_candle_at_frozen_now_is_excluded` | frozen clock inside the current day, 1 closed bar published, pages 1 | same clock; nothing published, pages 0, no adapter call, cursor untouched (the closed bar of the current day is excluded too) |
| `test_backfill.py::test_killed_run_resumes_from_persisted_cursor` | end at `base + 96h`, 97 unique candles, 73 rows on resume | same end; the 96h candle (open == end) is outside the window: 96 unique candles, 72 rows on resume |
| `test_backfill.py::test_corrupt_page_rejected_cursor_not_advanced_past_good_data` | end `base + 10h`, 5 good rows published | end `base + 24h` (day boundary); same assertions (5 rows, 1 rejection, cursor at the last good bar) |
| `test_tracer_slice.py::test_paginator_drops_forming_candle_at_frozen_clock` | frozen at 23:14 inside the forming bar, 1 row | frozen at 2023-11-15T00:10Z so the forming bar straddles midnight and the `close_time` filter (not the day cut) is what drops it; same assertions (1 row, 1 page) |
| `test_tracer_slice.py::test_duplicate_open_time_across_pages_collapse_to_one_row` | 22:13:20 base crossing midnight, 3 rows | day-aligned base, first three hours of a past day, `terminal_end=True` (mid-day mechanics, stated in a comment); same assertions |
| `test_tracer_slice.py::test_paced_fetch_sleeps_and_retries_429_then_resumes` | odd mid-day base | day-aligned base, one-hour window, `terminal_end=True`; same assertions |

## Decisions Made

- The corrupt-page test still ends with a published 5-row day. That is the pre-existing warn-only-gaps design (a rejected page never heals with a real source, where the refetch raises `StructuralRejectionError` after 5 tries before any flush); it was not widened here (see Issues Encountered).
- The `terminal_end` flag is ignored when `end_ms` is past today's start: an open day can never be terminal.
- `backfill_universe` does not expose `terminal_end`; it always runs to "now" so the clamp applies.

## Deviations from Plan

None - plan executed exactly as written. Small implementation notes, none a deviation:

- The RED test for Task 2 reaches the new API through `store.atomic_write_parquet` and `store.os`/`store.time` attribute access inside each test, so RED fails per test instead of at collection.
- The precision guard also rejects trailing-zero values with more than 8 digits (for example `1.000000000`), as the plan's exponent rule specifies, because Polars infers scale 9 for them and would drift the Parquet schema.

**Total deviations:** 0. **Impact:** none.

## Issues Encountered

- Pre-existing failures outside this plan (recorded in `deferred-items.md` by 13-01, plan 13-11 owns the fix): 7 tests in `tests/test_decision_alignment.py` and `tests/test_decision_alignment_bookkeeping.py` (RQ-01/RQ-04). They were deselected in the wide regression run; every other test in `tests/` passes (all tests outside the deselected files).
- `ruff check src` reports 7 pre-existing errors in files this plan did not touch (for example an unused `stop_threshold_quote` variable); `ruff check` on every file this plan changed is clean. Not fixed (scope boundary).
- Known limitation, pre-existing and not widened: a page that fails the quality gate, followed by a source that then returns no rows, leaves the buffered good rows to publish as a short day at the flush (gaps are warn-only by design, D-10/D-11). With the real adapter a repeated corrupt page raises `StructuralRejectionError` before any flush, so the path is not reachable in practice.
- Mid-day `start_ms` is not held back by the paginator (only the end side is bounded, per the plan). `backfill_universe` aligns its start to a day boundary and resume starts at cursor plus one interval, so the production paths are day-aligned.

## Known Stubs

None.

## Threat Flags

None. Threats T-13-05 (partial or current-day publish), T-13-06 (torn file), T-13-07 (silent overwrite), T-13-08 (silent Decimal rounding) and T-13-09 (Windows replace PermissionError) are all mitigated by the tests named in the coverage block. No new network, auth or trust-boundary surface.

## User Setup Required

None.

## TDD Gate Compliance

Each task has a `test(13-02)` RED commit before its `feat(13-02)` GREEN commit (Task 1: `c6f8ee2` then `825fea9`; Task 2: `d6c6a1e` then `81ace61`; Task 3: `545509e` then `9fd624e`). Each RED failed on the planned behavior (assertion failures, or a missing new API for Task 2's new function and the new `terminal_end` keyword); no REFACTOR commits were needed.

## Next Phase Readiness

- Plan 13-05 (archive source) can pass any object with the `KlineSource` signature to the paginator and get the same closed-day rule, gate and atomic store.
- Long backfills can start: the writer path can no longer produce a torn, partial-day or silently rounded immutable file.

## Self-Check: PASSED

- Files present: `src/data/backfill.py`, `src/data/store.py`, `src/data/quality.py`, `tests/test_backfill_closed_day.py`, `tests/test_store_atomic.py`, `tests/test_quality_gates.py`, `tests/test_backfill.py`, `tests/test_tracer_slice.py`.
- Commits present: `c6f8ee2`, `825fea9`, `d6c6a1e`, `81ace61`, `545509e`, `9fd624e`.
- Plan verification: `pytest tests/test_backfill_closed_day.py tests/test_store_atomic.py tests/test_quality_gates.py tests/test_backfill.py tests/test_tracer_slice.py tests/test_coverage.py` passes (60 tests); `mypy src/data/backfill.py src/data/store.py src/data/quality.py` reports "Success: no issues found in 3 source files".
