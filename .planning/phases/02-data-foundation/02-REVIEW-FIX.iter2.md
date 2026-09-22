---
phase: 02-data-foundation
fixed_at: 2026-09-22T01:00:00+07:00
review_path: C:/Users/daotu/OneDrive/Documents/Trading-Alert/.planning/phases/02-data-foundation/02-REVIEW.md
iteration: 1
findings_in_scope: 25
fixed: 25
skipped: 0
status: all_fixed
---

# Phase 02: Code Review Fix Report

**Fixed at:** 2026-09-22T01:00:00+07:00
**Source review:** `02-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 25 (10 Critical + 15 Warning; 4 Info out of scope)
- Fixed: 25
- Skipped: 0

**Verification (per fix):** re-read modified section (Tier 1) + `ast` syntax
check (Tier 2) + targeted pytest module(s); final gates: full suite
**64 passed** (baseline 62 + 2 new tests) and `ruff check src/ tests/ scripts/`
clean. All work ran in the isolated worktree
`.claude/worktrees/rf-02-10036-1790037182` (branch `gsd-reviewfix/02-10036`,
fast-forwarded to `master` on completion) using the main checkout's `.venv`
interpreter with `PYTHONPATH` pointed at the worktree.

## Fixed Issues

### CR-01: `backfill_universe` shares one `interval_ms=0` config across all intervals

**Files modified:** `src/data/backfill.py`
**Commit:** 063d80e
**Applied fix:** Removed the shared `BackfillConfig(interval_ms=0)`; each
`(symbol, interval)` call now gets a per-interval config derived via
`dataclasses.replace(config, interval_ms=interval_ms(interval))` (or a fresh
default when no config is passed), preserving the caller's other knobs.

### CR-02: Dedup set poisoned before the quality gate

**Files modified:** `src/data/backfill.py`
**Commit:** 3e81964
**Applied fix:** The dedup loop no longer marks rows seen; open_times are
added to `seen_open_times` only inside the `structural_ok` branch after
`check_batch` passes. Rejected batches leave the set untouched, so the
rolled-back cursor re-encounters corrupt rows instead of skipping them.

### CR-03: Corrupt-page rollback with no rejection cap loops forever

**Files modified:** `src/data/backfill.py`
**Commit:** ee23945
**Applied fix:** Added `MAX_CONSECUTIVE_REJECTIONS = 5` plus
`StructuralRejectionError(symbol, interval, cursor_ms, consecutive)`; the
corrupt branch counts consecutive rejections and raises past the budget,
reset on any non-rejection iteration. Fail closed AND terminates.

### CR-04: `CollectorGap.symbol` nullable PK rejected by PostgreSQL

**Files modified:** `src/db/models.py`,
`src/db/alembic/versions/0001_baseline.py`, `src/data/collector.py`
**Commit:** 5847471 (+ cfebb47 regression test)
**Applied fix:** New `TICK_WIDE_SYMBOL = "__TICK__"` sentinel; model column is
non-nullable PK, baseline migration edited in place to `nullable=False`
(justified: the baseline has not shipped to any prod database yet), and all
four `symbol=None` writers (skip / OI error / funding error / harvest) now
pass the sentinel. `_record_gap` signature narrowed to `symbol: str`.
Regression test `test_gap_pk_columns_are_not_null_under_postgres_dialect`
compiles every table against the PG dialect and asserts no nullable PK
column (commit cfebb47).

### CR-05: Funding coverage views query a column and filename the collector never writes

**Files modified:** `src/sql/coverage_v1.sql`, `src/data/coverage.py`,
`tests/test_coverage.py`
**Commit:** 93c5f84
**Applied fix:** `funding_coverage_v1` now selects `funding_time_utc` from
`sweep-*.parquet`; added `oi_research_coverage_v1`; `all_tick_coverage_v1`
is a UNION of the three per-class views (no single glob can cover the two
filename shapes). The empty-glob stub projects per-view columns (funding
stub carries `funding_time_utc`). Test 7 seeder rewritten to the real
funding schema via a new `_seed_funding_tick` helper (it previously seeded
OI-shaped rows into the funding partition, masking the bug).

### CR-06: Production `backup` CLI wires a SQLite probe, not `pg_dump`

**Files modified:** `src/ops/backup.py`, `tests/test_backup.py`
**Commit:** c2d71b6
**Applied fix:** New `_prod_pg_dump_runner` shells to real `pg_dump`
(`PG_DUMP_BIN` / `DATABASE_URL_SYNC`→`DATABASE_URL`, `check=True`, raises
when unconfigured so `backup-OK` is refused without a real dump); it is now
the CLI default. The sqlite fake survives only behind an explicit
`--sqlite-fake-pg-dump` test flag; Test 10 passes that flag.

### CR-07: `run_drill` does unguarded `shutil.rmtree(scratch_root)`

**Files modified:** `src/ops/backup.py`
**Commit:** cd770bf
**Applied fix:** New `_assert_safe_scratch_root` runs before any delete and
refuses: scratch == bundle, filesystem root, home, cwd, bundle-inside-scratch
(wipe would destroy the backup), scratch-inside-bundle (ambiguous layout).
Verified: refuses same/root/home, allows sibling tmp dirs; backup tests green.

### CR-08: Adapter fabricates epoch-0 timestamps and zero OI/funding-rate

**Files modified:** `src/adapters/binance_usdm.py`
**Commit:** 5fc0b21
**Applied fix:** `open_interest` raises `ValueError` when `time` or
`open_interest` is `None`; `funding_rate` raises when `funding_time` /
`funding_rate` / resolved symbol is missing. No more `or 0` / `or "0"` /
`or ""` fabrication on these paths.

### CR-09: `session_scope` missing `@asynccontextmanager`

**Files modified:** `src/db/models.py`
**Commit:** 102754a
**Applied fix:** Added the decorator (plus the import); verified the helper
exposes `__aenter__` so `async with session_scope(factory)` works.

### CR-10: Drill reports `equal=True` on partial restores; manifest hashes itself

**Files modified:** `src/ops/backup.py`
**Commit:** 3783ca0
**Applied fix:** (a) `write_manifest` excludes `manifest.json` from its own
hash (stable incremental re-runs). (b) `run_drill` does a full-set
comparison — every manifest key (minus the manifest itself) must have been
visited, else `failed_files` + `equal=False`; also guards
`relative_to(scratch_root)` for custom pg dump paths.

### WR-01: `exchange_info` silently drops symbols with missing filters

**Files modified:** `src/adapters/binance_usdm.py`
**Commit:** c7a3d97
**Applied fix:** Missing-filter symbols log at error level with symbol +
missing filter names, and the refresh raises `ValueError` listing all
drifted symbols instead of reporting success on a shrunken universe.

### WR-02: Harvest path has no fail-closed handling; empty sweep indistinguishable

**Files modified:** `src/data/collector.py`
**Commit:** c981acb
**Applied fix:** Harvest loop is per-symbol isolated (gap row, no watermark
advance, remaining symbols continue). Funding sweep fetches per symbol with
per-symbol gaps. New `FundingSweepResult.empty` flag (True only when zero
rows AND zero gaps) separates "caught up" from "blind".

### WR-03: Collector Parquet writers silently overwrite

**Files modified:** `src/data/collector.py`
**Commit:** cd4346e
**Applied fix:** New `_guard_no_overwrite` (D-04, same rule as
`publish_batch`) called by all three tick writers; existing paths raise
`FileExistsError` instead of destroying evidence.

### WR-04: Gap `reason` never truncated

**Files modified:** `src/data/collector.py`
**Commit:** 3870ba6
**Applied fix:** `_record_gap` truncates to `reason[:256]` before insert so
the outage-recording insert itself cannot fail on PostgreSQL. Column widening
deferred (truncation alone fixes the crash; parity stays green).

### WR-05: Quality gate misses negatives, inverted close-times, mixed batches

**Files modified:** `src/data/quality.py`
**Commit:** a1eb704
**Applied fix:** New `negative_values` (negative OHLC/volume, `trade_count <=
0`), `bad_durations` (`close_time_utc <= open_time_utc`), and `mixed_keys`
(rows outside the first row's `(symbol, interval)`) counters on
`QualityVerdict` (defaulted, backwards compatible) and included in
`structural_ok`.

### WR-06: No batch homogeneity check in gate/store

**Files modified:** `src/data/store.py`
**Commit:** 8a97eb6
**Applied fix:** `publish_batch` rejects batches whose row symbols/intervals
do not exactly match the caller's `(symbol, interval)` partition args with
`ValueError` (no cross-partition contamination). Gate-side mixing is covered
by WR-05's `mixed_keys`.

### WR-07: Backup silently succeeds with zero payload; no pruning

**Files modified:** `src/ops/backup.py`
**Commit:** 8f8daf7
**Applied fix:** Missing parquet roots log a `backup.parquet_root_missing`
warning each; when ALL roots are missing the backup raises
`FileNotFoundError` instead of shipping a pg.dump-only "success". (Bundle
prune/GC left as documented follow-up; the manifest drift it causes is now
surfaced by CR-10's full-set drill comparison.)

### WR-08: Non-atomic cursor, float day math, wall-clock durations

**Files modified:** `src/data/backfill.py`
**Commit:** 74b9bd7
**Applied fix:** Cursor writes via tmp + `os.replace` (atomic); day snap is
integer `ms - ms % 86_400_000`; durations measured with `time.monotonic`
(telemetry only, excluded from equality).

### WR-09: Coverage loader interpolates paths, swallows view errors, never gaps funding

**Files modified:** `src/data/coverage.py`
**Commit:** 13a5f42
**Applied fix:** Glob literal escapes single quotes; required view-creation
failures raise `RuntimeError` with statement context instead of downgrading
to a warning; `build_oi_coverage` applies the 8h funding cadence
(`DEFAULT_FUNDING_INTERVAL_MS`) to funding rows.

### WR-10: Paginator robustness gaps

**Files modified:** `src/data/backfill.py`, `tests/test_backfill.py`
**Commit:** 167490d
**Applied fix:** (a) `cfg.interval_ms` validated against
`interval_ms(interval)` (loud `ValueError` on mismatch). (b) `on_publish`
fires in the end-of-loop flush. (c) Break after
`MAX_CONSECUTIVE_EMPTY_PAGES = 100` consecutive empty pages (small windows
unaffected, 43k-fetch holes break fast). (d) Dead `_RATE_LIMIT_ERRORS`
alias deleted; new `test_rate_limit_predicate_pins_canonical_sdk_error_names`
pins the retry predicate contract.

### WR-11: Container/packaging gaps

**Files modified:** `Dockerfile`, `docker-compose.yml`, `.env.example`
**Commit:** 417521f
**Applied fix:** Image copies `alembic.ini`; healthcheck imports the
collector module instead of always exiting 0; backup bundle mounted as
`backupdata:/app/data/backup` (survives restarts); non-root `appuser` with
owned `/app/data`; `.env.example` unified on canonical `data/backup`.

### WR-12: `backup-drill.ps1` breaks on spaces, mutates CWD, naive split

**Files modified:** `scripts/backup-drill.ps1`
**Commit:** 3ab8245
**Applied fix:** `Push-Location`/`Pop-Location` in `try`/`finally` (CWD
always restored), quoted path expansions, `;`/whitespace-tolerant root
splitting with empty-entry filtering, `OFF_HOST_BACKUP_TARGET` fallback,
defaults aligned on `data/backup`. PS parser syntax check passes; test 11
constraints respected (no `pg_dump` string in wrapper).

### WR-13: Engine/session leaks; weak strictness

**Files modified:** `src/db/models.py`, `pyproject.toml`
**Commit:** bddbc41
**Applied fix:** One shared async engine per URL (`_ENGINE_CACHE`) with
`dispose_engine()`; `make_engine` refuses URLs without an async driver
(`+psycopg`/`+asyncpg`); `ignore_missing_imports = false` under mypy strict.
Verified: shared identity, non-async refusal, async dispose.

### WR-14: Parity script compares names only

**Files modified:** `scripts/check_migration_parity.py`
**Commit:** 742d645
**Applied fix:** Parser compares full `(name, type, nullability)` specs plus
PK tuples, expanded type head list, schema-qualified table names, and fails
loudly on any unparsed line. Verified green on the real schema and catching
a synthetic `NUMERIC → FLOAT` drift (negative control).

### WR-15: One bad symbol kills the whole tick; half-fail without gap

**Files modified:** `src/data/collector.py`, `tests/test_collector.py`
**Commit:** d397b71
**Applied fix:** OI poll isolates failures per symbol (own gap row; healthy
symbols commit + advance); write+commit section journals a tick-wide gap and
re-raises on failure (with `rollback()`); funding sweep got the same
write-guard in WR-02. Test 2 rewritten to per-symbol semantics (mid-universe
ETH failure → 4 snapshots/watermarks + 1 ETH-scoped gap). The stale
"re-write is a no-op" docstring paragraph was replaced with the true
atomicity contract.

---

*Fixed: 2026-09-22T01:00:00+07:00*
*Fixer: the agent (gsd-code-fixer)*
*Iteration: 1*
