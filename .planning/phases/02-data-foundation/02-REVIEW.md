---
phase: 02-data-foundation
reviewed: 2026-09-21T00:00:00Z
depth: deep
files_reviewed: 30
files_reviewed_list:
  - pyproject.toml
  - Dockerfile
  - docker-compose.yml
  - alembic.ini
  - .env.example
  - scripts/backup-drill.ps1
  - scripts/check_migration_parity.py
  - src/__init__.py
  - src/adapters/binance_usdm.py
  - src/data/backfill.py
  - src/data/collector.py
  - src/data/coverage.py
  - src/data/metadata.py
  - src/data/quality.py
  - src/data/store.py
  - src/db/__init__.py
  - src/db/alembic/env.py
  - src/db/alembic/versions/0001_baseline.py
  - src/db/models.py
  - src/ops/backup.py
  - src/sql/coverage_v1.sql
  - tests/conftest.py
  - tests/test_backfill.py
  - tests/test_backup.py
  - tests/test_collector.py
  - tests/test_coverage.py
  - tests/test_metadata.py
  - tests/test_quality_gates.py
  - tests/test_tracer_slice.py
  - tests/test_wave0_sanity.py
findings:
  critical: 0
  warning: 1
  info: 7
  total: 8
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-09-21T00:00:00Z
**Depth:** deep
**Files Reviewed:** 30
**Status:** issues_found

## Summary

Iteration-3 re-review at deep depth against the current on-disk source, which
includes the iteration-2 fixer's claimed resolution of all 7 warnings from the
iteration-2 re-review (prior report at `02-REVIEW.iter3.md`). Every prior
finding was re-opened and re-read at the exact cited lines against current
source — **all 7 warnings are verified resolved**:

- **WR-01 (ps1 separator):** `scripts/backup-drill.ps1:44` now splits on `;`
  only with per-entry trim/empty-drop. Resolved.
- **WR-02 (scratch guard incl. data/raw):** `src/ops/backup.py:327-343` now
  refuses the live store itself, anything inside it, and anything above it
  (`resolved == live_raw or resolved.is_relative_to(live_raw) or
  live_raw.is_relative_to(resolved)`). The `data/raw` typo vector is closed.
  Resolved.
- **WR-03 (strict exchangeInfo/OI rows):** `src/adapters/binance_usdm.py:386-413`
  raises on missing numeric filter fields, and missing identity fields join
  the drift failure instead of defaulting to `""`; `open_interest_statistics`
  (`:289-292`) raises on malformed harvest rows. Resolved.
- **WR-04 (prune subcommand):** `prune_bundle()` (`src/ops/backup.py:243-289`)
  plus the `prune` CLI subcommand (`:536-551`), with dry-run support, unknown-
  basename keys kept, and the append-only contract documented in the `backup()`
  docstring. Covered by `test_prune_*` tests. Resolved.
- **WR-05 (real-SDK retry predicate):** `is_rate_limit_error` in
  `src/adapters/binance_usdm.py:140-158` matches `isinstance` against the real
  imported `TooManyRequestsError` / `RateLimitBanError`, with the substring
  sniff kept only as fallback; the pinning test (`tests/test_backfill.py:444-460`)
  imports the real installed SDK classes. Resolved.
- **WR-06 (real collector main() + healthcheck):** `src/data/collector.py`
  now defines `AdapterLike` as a `Protocol` (`:79-92`), a `main()` +
  `__main__` entrypoint with the 5-minute loop / `--once` / `--healthcheck`
  (`:752-833`), and a watermark-freshness probe (`_check_health`, `:652-703`);
  `Dockerfile:32-33` HEALTHCHECK and `docker-compose.yml:57` command point at
  the real entrypoint. Covered by `test_run_once_tick_*` / `test_healthcheck_*`
  tests. Resolved.
- **WR-07 (mypy strict):** `OICoverageRow` is now a `TypedDict`
  (`src/data/coverage.py:240-253`), `quality.py:158-162` narrows extrema to
  `datetime` before gap math, and the adapter boundary is a `Protocol`.
  Resolved.

Gates were run independently (not trusted from the fixer claim):

- `uv run python -m pytest tests/` → **77 passed**
- `uv run ruff check src tests scripts` → **All checks passed!**
- `uv run mypy src` → **Success: no issues found in 15 source files**
- `uv run python scripts/check_migration_parity.py` → **parity green**
  (4 tables, PKs match)

One **new Warning** below: the WR-06 fix ships a production loop that
promotes a latent sweep defect to a live wedge — a single transient
per-symbol funding failure permanently stalls funding ingestion for the
whole universe while the healthcheck stays green. No Critical defects remain.

## Warnings

### WR-01: New production loop wedges funding forever after one transient per-symbol failure

**File:** `src/data/collector.py:594-616,439-496`
**Issue:** `_funding_since_ms` returns the `min()` watermark across the whole
universe as a single global `since_ms`, but `_write_funding_tick` enforces
D-04 immutability (`_guard_no_overwrite` raises `FileExistsError` on an
already-written tick file) and `async_funding_sweep` has no
skip-existing/already-covered logic. Trace the failure: at an 8h funding
boundary, symbol A has a transient adapter error → per-symbol gap row, A's
watermark stays at W while B–E write event E and advance to E. The next tick
computes `since_ms = W + 1`, so healthy symbols re-fetch event E, which is
already on disk → `FileExistsError` → bulk-section abort → `session.rollback()`
(reverts staged DB advances, but the Parquet files written before the
collision are NOT transactional and stay on disk) → raise → `main()` logs and
sleeps. Every subsequent tick repeats identically (`since_ms` can never
advance past W+1), so funding ingestion is permanently wedged — while the OI
tick (separate call, separate commit, runs first) keeps succeeding and the
`--healthcheck` probe watches OI watermarks only, reporting healthy forever.
This path was latent before; the WR-06 loop makes it the shipped runtime, so
it is a regression introduced by this iteration's fixes. Not Critical: no data
loss or corruption (immutability guard + rollback keep store and DB
consistent) — but funding goes silently stale, which is exactly the outage
class D-08/D-09 exist to prevent.
**Fix:** Compute the resume point per symbol inside the sweep and skip ticks
already covered by that symbol's watermark (or already on disk), e.g.:
```python
for sym in universe:
    row = session.execute(
        select(CollectorWatermark).where(
            CollectorWatermark.symbol == sym,
            CollectorWatermark.data_class == "funding",
        )
    ).scalar_one_or_none()
    sym_since = (
        int(row.last_tick_utc.timestamp() * 1000) + 1
        if row is not None and row.last_tick_utc is not None
        else since_ms
    )
    sym_ticks = await adapter.funding_rate(
        symbol=sym, start_ms=sym_since, end_ms=end_ms, limit=limit
    )
    ...
    for tick in sym_ticks:
        if row is not None and tick.funding_time_utc <= row.last_tick_utc:
            continue  # already covered — never re-hit the immutability guard
        _write_funding_tick(tick, raw_root)
```
At minimum, a `FileExistsError` on a funding tick should be treated as
already-covered (skip + continue) rather than aborting the whole sweep.

## Info

### IN-01: `candles_v1` empty-frame stub carries a phantom `date` column

**File:** `src/data/coverage.py:158-173`
**Issue:** The `AdapterLike`-collapses-to-`object` half of the prior IN-01 is
fixed (now a `Protocol`, `collector.py:79-92`, and mypy strict is green). The
second half remains: the `candles_v1` stub projects `CAST(NULL AS DATE) AS
date`, which the real view (`coverage_v1.sql:33-49`) never selects. Harmless
(the stub only feeds `WHERE 1 = 0` compiles) but misleading to the next
reader.
**Fix:** Drop `date` from the stub or select it in the view.

### IN-02: Function-level `import json` in per-symbol helpers

**File:** `src/adapters/binance_usdm.py:484-487,490-508`
**Issue:** Unchanged: `_order_capabilities_blob` / `_position_mode_blob`
import `json` in the function body on every symbol of every `exchange_info`
call. Functionally fine, stylistically noisy.
**Fix:** Hoist `import json` to module top.

### IN-03: Canonical sets still triple-sourced and driftable

**File:** `src/data/quality.py:25`, `src/data/backfill.py:549-561`, `src/data/coverage.py:42-44`, `tests/conftest.py:27`
**Issue:** Unchanged: `INTERVAL_MS`, `LIVE_5` (defined separately in
`backfill` AND `conftest`), `DEFAULT_BACKFILL_WINDOWS_MS`, and
`CANONICAL_INTERVALS` encode the same universe in four places. Adding `15m`
to quality but not to the universe runner silently changes gap math vs
bootstrap vs CLI matrix.
**Fix:** Single constants module re-exported by backfill/coverage/tests.

### IN-04: Eager SDK construction in `BinanceUsdmAdapter.__init__`

**File:** `src/adapters/binance_usdm.py:209-210`
**Issue:** Unchanged: `DerivativesTradingUsdsFutures()` constructs eagerly
even for code paths needing only dataclass types, coupling setup to
network/config state and forcing every test to mock around it.
**Fix:** Lazy-construct on first API call (or a `default_client()` factory),
keeping `__init__(sdk_client=None)` cheap.

### IN-05: `oi_coverage_rows` still swallows query-time view errors

**File:** `src/data/coverage.py:387-394`
**Issue:** Unchanged: the per-view `SELECT` is still wrapped in bare
`except duckdb.Error: continue`, so a query-time failure on one class
silently drops that class's coverage rows. Build failures now raise loudly
in `_load_views`, which shrinks this window to SELECT-time faults — but a
funding-schema drift that compiles empty and fails at select would still
vanish without a trace.
**Fix:** Log at error level with the view name before `continue`, or let the
SELECT raise like view-build failures do.

### IN-06: Harvest completion marker shares the gap journal

**File:** `src/data/collector.py:544-551`
**Issue:** Unchanged (deliberate, documented design — hence Info): every
`harvest_open_interest_history` call writes a `reason="harvest_complete: ..."`
row into `collector_gaps` with an epoch-0 sentinel `expected_utc`. Any
consumer counting gap rows must parse `reason` prefixes to exclude non-gaps.
**Fix:** Write harvest markers to a separate audit/event table (or a
`collector_runs` log); at minimum document the `reason`-prefix filter
contract consumers must apply.

### IN-07: `backfill_universe` aborts the whole universe on the first per-key failure

**File:** `src/data/backfill.py:639-653`
**Issue:** Unchanged: a `StructuralRejectionError` (or adapter exception) for
one (symbol, interval) propagates out of `backfill_universe`, abandoning all
remaining keys and discarding the already-collected `per_key` results. One
corrupt window in `XRPUSDT/1m` blocks `BTCUSDT/4h` from bootstrapping in the
same run.
**Fix:** Wrap the per-key call in try/except, record the error in the result,
continue with remaining keys, and raise/signal at the end if any key failed.

---

_Reviewed: 2026-09-21T00:00:00Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
