---
phase: 02-data-foundation
reviewed: 2026-09-22T00:00:00Z
depth: deep
files_reviewed: 2
files_reviewed_list:
  - src/data/collector.py
  - tests/test_collector.py
findings:
  critical: 0
  warning: 1
  info: 2
  total: 3
status: issues_found
---

# Phase 02: Code Review Report (convergence confirmation)

**Reviewed:** 2026-09-22T00:00:00Z
**Depth:** deep
**Files Reviewed:** 2
**Status:** issues_found

## Summary

**Scope note:** this is a convergence-confirmation review, not a full phase
re-review. Scope is the 2 files changed by the final fix commit `e37d80f`
(per-symbol funding resume, idempotent retry, funding-freshness
healthcheck). The other 28 files from the prior 30-file review
(`bd8c73f`, 0 Critical / 1 Warning / 7 Info) were not re-opened; prior
Info items living outside these 2 files (IN-01 second half, IN-02, IN-03,
IN-04, IN-05, IN-07) are carried as not-re-verified and are not
re-reported here.

**WR-01 (funding-ingestion wedge) is verified RESOLVED.** The prior review's
single open warning — global-`min()` resume plus `FileExistsError` abort
permanently wedging funding ingestion while the OI-only healthcheck stayed
green — is fixed on all three sub-claims, each re-read at the exact lines
against current source:

- **Per-symbol resume** (`src/data/collector.py:467-499`): each symbol
  fetches from just after its OWN funding watermark
  (`_tick_epoch_ms(wm) + 1`), never from the global minimum. A transient
  single-symbol failure can no longer force healthy symbols to re-fetch
  already-written ticks.
- **Idempotent skip** (`:503-533`): ticks at or below the symbol's
  watermark are skipped without touching the D-04 guard, and a
  `FileExistsError` (Parquet written, DB commit rolled back) is counted
  in `skipped_existing` with the watermark still advanced past the
  on-disk tick — instead of aborting the whole sweep.
- **Funding-aware healthcheck** (`:717-805`): `_check_health` now probes
  every symbol's `funding` watermark against a dedicated 9h bound
  (`FUNDING_HEALTH_MAX_AGE_SECONDS`, one 8h interval + margin) in addition
  to the OI probe, so a funding-only wedge surfaces as UNHEALTHY.

**The 3 new tests prove retry-convergence (not vacuous).** Each asserts a
post-condition that fails on the pre-fix code:

- `test_funding_sweep_retry_after_transient_failure_makes_progress`
  (`tests/test_collector.py:622-694`): sweep 1 fails BTC / writes ETH@E;
  sweep 2 must complete without `FileExistsError`, backfill BTC, report
  `skipped_existing == 1`, call ETH with `start_ms == E + 1` (per-symbol
  resume arg asserted at `:675-676`, compensating for `FakeAdapter`
  ignoring `start_ms` when selecting queued responses), converge both
  watermarks on E, and leave exactly 2 tick files. Pre-fix, sweep 2
  raises out of the bulk section — the test cannot pass without the fix.
- `test_funding_sweep_treats_existing_tick_file_as_covered`
  (`:697-736`): orphaned Parquet with no watermark must skip
  idempotently and still advance the watermark (`watermarks_advanced ==
  1`). Pre-fix, this raises `FileExistsError`.
- `test_healthcheck_fails_with_stale_funding` (`:546-586`): fresh OI +
  10h-stale funding watermarks must exit 1. Pre-fix probe watched OI
  only and exited 0.

**Regression sweep (deep, cross-file):** `async_funding_sweep`,
`FundingSweepResult`, `skipped_existing`, `_funding_since_ms`,
`_check_health`, and `_tick_epoch_ms` have **no consumers outside the 2
reviewed files** (repo-wide grep: all 37 matches land in
`src/data/collector.py` + `tests/test_collector.py`). In particular:
`coverage.py` `build_oi_coverage` / OI rows never reference the sweep
(they read Parquet partitions, which are still written exactly once —
`skipped_existing` only suppresses re-writes); no backup or backfill
universe code touches these symbols; the fix commit touched only these 2
files so `Dockerfile`/`docker-compose.yml` healthcheck wiring is
unchanged and `_check_health`'s new parameter is defaulted (backward
compatible). `FundingSweepResult.skipped_existing` defaults to `0`, so
existing constructions are unaffected.

**Gates run independently (not trusted from the fixer claim):**

- `uv run python -m pytest tests/` → **80 passed in 12.41s**
  (77 pre-fix + 3 new; `tests/test_collector.py` alone: 13 passed)
- `uv run ruff check src tests scripts` → **All checks passed!**
- `uv run mypy src` → **Success: no issues found in 15 source files**

**Convergence verdict: YES — the phase has converged.** The blocking
defect (WR-01) is resolved with genuine regression tests, gates are
green, and no Critical defects remain. The one residual Warning below is
minor (dev/SQLite timezone edge + docstring overstatement, production
PostgreSQL path unaffected) and does not block the phase; the two Info
items are non-blocking. No further fix loop is required, though the
Warning should be picked up opportunistically.

## Warnings

### WR-01: `_funding_since_ms` uses raw `.timestamp()` on possibly-naive datetimes and over-promises the fresh-symbol bootstrap

**File:** `src/data/collector.py:659-681`
**Issue:** Two defects in the resume helper, both surviving the fix
because the fix moved per-symbol resume into `async_funding_sweep`
(`:483`, which correctly uses `_tick_epoch_ms`) while leaving this
helper on the old formula:

1. **Naive-tz inconsistency (correctness edge).** Line 680 computes
   `int(row.last_tick_utc.timestamp() * 1000) + 1` directly. On the
   SQLite roundtrip `last_tick_utc` comes back naive, and naive
   `.timestamp()` interprets the value in the **host local timezone** —
   while `_tick_epoch_ms` (`:158-167`) normalizes naive as UTC. On any
   non-UTC host (e.g. a `+0700` dev machine) the two helpers disagree by
   the UTC offset for the same watermark. Production PostgreSQL
   (TIMESTAMPTZ, aware roundtrip) is unaffected, but the deterministic
   "same snapshot = same decision" posture should not depend on host TZ
   on the dev/test backend.
2. **Docstring overstatement via `min()` aggregation.** The docstring
   (`:662-668`) promises "symbols without a watermark (fresh deploy)
   start one funding interval back." But the return is `min(starts)`: if
   any watermarked symbol is older than 8h, a fresh symbol inherits that
   stale `watermark + 1` instead of its own bounded bootstrap window and
   over-fetches (extra exchange weight; worst case `limit=1000`
   truncation pressure on the first sweep). The value is now only a
   fallback for watermark-less symbols (watermarked symbols bypass it at
   `:483`), so the blast radius is small — but the contract as written
   is false.
**Fix:**
```python
# line 680: reuse the naive-safe helper
starts.append(_tick_epoch_ms(row.last_tick_utc) + 1)
```
and either compute per-symbol fallbacks at the call site (drop the
`min()` for fresh symbols, giving each `now_ms -
FUNDING_BOOTSTRAP_LOOKBACK_MS`) or correct the docstring to state that
fresh symbols start at the universe minimum. A mixed-watermark test
(one stale watermark + one fresh symbol, asserting the fresh symbol's
fetch `start_ms`) would lock the contract — that case is currently
uncovered (`_funding_since_ms` is only exercised via `_run_once_tick`
with all-fresh watermarks).

## Info

### IN-01: `FundingSweepResult.empty` is True for skipped-only sweeps

**File:** `src/data/collector.py:559`
**Issue:** `empty=(inserted == 0 and gaps == 0)` reports `True` when the
sweep did substantive work that converged (returned rows, all
already-covered, `skipped_existing > 0`) — indistinguishable from "the
upstream returned nothing." No production consumer reads `.empty` today
(the only caller, `_run_once_tick`, ignores it), so this is latent, but
the field's own docstring (`:118-123`) promises to distinguish
"genuinely nothing new" from a blind sweep, and a skipped-only sweep is
neither.
**Fix:** If the field is ever consumed, tighten to `empty=(inserted == 0
and skipped_existing == 0 and gaps == 0)` so "upstream silent" and
"caught up via skips" are distinguishable. No action needed while it
remains unread.

### IN-02: Harvest completion marker still shares the gap journal (carried forward)

**File:** `src/data/collector.py:609-617`
**Issue:** Unchanged by the fix commit and still present:
`harvest_open_interest_history` writes a `reason="harvest_complete:
..."` row into `collector_gaps` with an epoch-0 sentinel
`expected_utc`. Deliberate documented design (hence Info, carried
forward from the prior review's IN-06): any consumer counting gap rows
must filter `reason`-prefixes to exclude non-gaps.
**Fix:** Write harvest markers to a separate audit/event table (or a
`collector_runs` log); at minimum document the `reason`-prefix filter
contract consumers must apply.

---

_Reviewed: 2026-09-22T00:00:00Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
