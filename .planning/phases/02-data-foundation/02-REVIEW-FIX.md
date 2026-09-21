---
phase: 02-data-foundation
fixed_at: 2026-09-22T00:00:00Z
review_path: C:/Users/daotu/OneDrive/Documents/Trading-Alert/.planning/phases/02-data-foundation/02-REVIEW.md
iteration: 3
findings_in_scope: 1
fixed: 1
skipped: 0
status: all_fixed
---

# Phase 02: Code Review Fix Report

**Fixed at:** 2026-09-22T00:00:00Z
**Source review:** `02-REVIEW.md` (iteration-3 re-review: 0 Critical / 1 Warning / 7 Info)
**Iteration:** 3

**Summary:**
- Findings in scope: 1 (Critical + Warning only; 7 Info findings out of scope per fix_scope)
- Fixed: 1
- Skipped: 0

**Verification (main checkout, no isolated worktree — `workflow.use_worktrees` is `false`):**
- `uv run python -m pytest tests/` → **80 passed** (77 baseline + 3 new WR-01 regression tests)
- `uv run ruff check src tests scripts` → **All checks passed!**
- `uv run mypy src` → **Success: no issues found in 15 source files** (strict stays at 0 errors)
- No failing test was deleted; tests were only added, plus one existing healthcheck test extended to seed the newly-required funding watermarks.

## Fixed Issues

### WR-01: New production loop wedges funding forever after one transient per-symbol failure

**Files modified:** `src/data/collector.py`, `tests/test_collector.py`
**Commit:** e37d80f
**Applied fix:**
- `async_funding_sweep` now snapshots each symbol's own funding watermark up front and fetches per symbol from `watermark + 1` (falling back to the global `since_ms` only for never-seen symbols), instead of fetching every symbol from the global `min()` watermark. A transient failure for one symbol can no longer force healthy symbols to re-fetch already-written ticks.
- Write path is idempotent on two layers: ticks at or below the symbol's watermark are skipped as already-covered (never re-hitting the D-04 immutability guard), and a `FileExistsError` from `_write_funding_tick` (Parquet-ahead-of-DB divergence after a rolled-back bulk commit) is treated as covered — counted in the new `FundingSweepResult.skipped_existing` field, logged via `collector.funding.tick_exists`, and still advanced past by the watermark — instead of aborting the whole sweep.
- Per-symbol adapter-failure gap rows now record `expected_utc` from that symbol's own resume point (`sym_since`) rather than the global window start.
- `_check_health` (and the `--healthcheck` probe) now covers funding freshness in addition to OI: every symbol needs a funding watermark newer than `FUNDING_HEALTH_MAX_AGE_SECONDS` (9h = one 8h funding interval + margin), via a shared `_watermark_staleness` helper. A funding-only wedge while OI keeps succeeding now reports UNHEALTHY instead of hiding behind the OI-only probe.
- New `_tick_epoch_ms` helper normalizes naive (SQLite roundtrip) vs aware (PostgreSQL) timestamps to epoch-ms so watermark comparisons are total-ordered on both backends.
- Tests: `test_funding_sweep_retry_after_transient_failure_makes_progress` (transient failure → retry converges, asserts per-symbol `start_ms` resume points, both watermarks converge, exactly 2 files, no raise), `test_funding_sweep_treats_existing_tick_file_as_covered` (orphaned Parquet file skipped idempotently with watermark advance), `test_healthcheck_fails_with_stale_funding` (fresh OI + 10h-stale funding → exit 1); extended `test_healthcheck_passes_with_fresh_watermarks` to seed funding watermarks alongside OI.

---

_Fixed: 2026-09-22T00:00:00Z_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: 3_
