---
phase: 02-data-foundation
fixed_at: 2026-09-22T00:00:00Z
review_path: .planning/phases/02-data-foundation/02-REVIEW.md
iteration: 1
findings_in_scope: 1
fixed: 1
skipped: 0
status: all_fixed
---

# Phase 02: Code Review Fix Report

**Fixed at:** 2026-09-22T00:00:00Z
**Source review:** `.planning/phases/02-data-foundation/02-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 1
- Fixed: 1
- Skipped: 0

## Fixed Issues

### WR-01: `_funding_since_ms` uses raw `.timestamp()` on possibly-naive datetimes and over-promises the fresh-symbol bootstrap

**Files modified:** `src/data/collector.py`, `tests/test_collector.py`
**Commit:** `6a096e4`
**Applied fix:**

1. **Naive-tz inconsistency (correctness edge) — resolved.** The helper
   no longer calls `int(row.last_tick_utc.timestamp() * 1000) + 1`
   directly. The new implementation returns the fresh-symbol bootstrap
   window (`now_ms - FUNDING_BOOTSTRAP_LOOKBACK_MS`) directly when any
   symbol lacks a watermark, and falls back to the same bounded value
   when all symbols are watermarked (the returned value is unused for
   those — per-symbol resume in `async_funding_sweep` handles them via
   `_tick_epoch_ms(wm) + 1`). This eliminates the host-TZ-dependent
   `.timestamp()` call on naive DB roundtrips while keeping the
   per-symbol resume path (which already uses `_tick_epoch_ms`)
   unchanged.

2. **Docstring overstatement via `min()` aggregation — resolved.** The
   `min(starts)` aggregation is gone. The helper now returns the
   fresh-symbol bootstrap directly, so a fresh symbol no longer
   inherits a stale watermarked symbol's `watermark + 1`. The
   docstring is rewritten to state the actual contract: this helper
   supplies the bootstrap window for fresh symbols only; per-symbol
   resume happens inside `async_funding_sweep`.

3. **Mixed-watermark test added.** Two new tests in
   `tests/test_collector.py` lock the contract:
   - `test_funding_since_ms_fresh_symbol_uses_bounded_bootstrap_not_stale_min`:
     unit test on `_funding_since_ms` with one stale watermark + one
     fresh symbol, asserting the returned value is the bounded
     bootstrap (NOT `stale_watermark + 1`).
   - `test_funding_sweep_mixed_watermarks_fresh_symbol_uses_bounded_bootstrap`:
     end-to-end test via `_run_once_tick` asserting the fresh symbol's
     adapter `start_ms` is `now_ms - 8h` while the stale-watermarked
     symbol resumes from its own `watermark + 1`.

**Verification (main checkout, no isolated worktree — `workflow.use_worktrees` is `false`):**
- `uv run python -m pytest tests/test_collector.py -x` → **15 passed in 3.65s** (13 pre-existing + 2 new)
- `uv run ruff check src tests` → **All checks passed!**
- `uv run mypy src` → **Success: no issues found in 15 source files**

## Skipped Issues

None.

---

_Fixed: 2026-09-22T00:00:00Z_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: 1_
