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
  critical: 10
  warning: 15
  info: 4
  total: 29
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-09-21T00:00:00Z
**Depth:** deep
**Files Reviewed:** 30
**Status:** issues_found

## Summary

Deep review of the Phase 2 data-foundation slice: Binance USDM adapter boundary,
deterministic kline paginator + cursor store, OI/funding collector with gap
journal, quality gate + immutable Parquet store, DuckDB coverage views + CLI,
versioned symbol metadata, four-table PG schema + baseline migration, backup +
scratch-restore drill, packaging (Docker/Compose/env), and the full test
surface. Cross-file tracing focused on the adapter single-import rule,
Decimal-only exchange values, UTC/TIMESTAMPTZ handling, Alembic-never-create_all,
fail-closed quality gates, gap journaling, and backup hash verification.

The structure is sound and the test surface is unusually thorough, but the
review finds **10 Critical defects that must block ship**: a shared
`interval_ms=0` config that freezes the universe-runner cursor, a
reject-then-dedup interaction that silently skips corrupt data it claims to
re-encounter, an unbounded re-fetch loop on corrupt pages, a NULL-in-PK gap
table that PostgreSQL will reject (SQLite masks it), a funding-coverage view
that queries a column and filename pattern the collector never writes, a
backup CLI that ships a SQLite probe while printing `backup-OK`, an unguarded
`shutil.rmtree(scratch_root)`, epoch-0/zero fabrication in the adapter's
`or "0"` fallbacks, an unusable `session_scope` (missing
`@asynccontextmanager`), and a drill that reports `equal=True` on partial
restores. Fifteen warnings and four info items follow.

## Critical Issues

### CR-01: `backfill_universe` shares one `interval_ms=0` config across all intervals — cursor never advances

**File:** `src/data/backfill.py:506,534,548-558`
**Issue:** `backfill_universe` builds `cfg = config or BackfillConfig(interval_ms=0)`
once and passes the SAME object to every `backfill_symbol_interval` call across
`("1m","1h","4h")`. Inside the callee, `cfg = config or ...` keeps the passed
object, so `cfg.interval_ms` is `0` for every key. Consequences: resume math
`persisted + cfg.interval_ms` does not advance; `last_published_open_ms =
start_ms - 0 = start_ms`; normal advance
`cursor = max(last_open + 0, page_start + 0)` sticks at `last_open` and the next
fetch re-requests the same page. With `interval_ms=0` the `while cursor < end_ms`
loop cannot terminate normally — it re-fetches the same boundary forever
(dedup hides the stall by collapsing rows while the cursor stays put).
**Fix:**
```python
# per-interval config; never share one interval_ms across timeframes
for interval in intervals:
    per_cfg = config or BackfillConfig(interval_ms=interval_ms(interval))
    ...
    result = await backfill_symbol_interval(..., config=per_cfg, ...)
```

### CR-02: Dedup set is poisoned before the quality gate — corrupt rows are silently skipped, not re-encountered

**File:** `src/data/backfill.py:294-323,381-395`
**Issue:** The comment claims open_times are tracked "only after the batch passes
the quality gate", but the code adds every `k_open_ms` to `seen_open_times`
BEFORE `check_batch` runs. On a structural rejection the cursor rolls back to
`last_published_open_ms + interval_ms`, so the next fetch returns the same
corrupt rows — which the dedup filter now drops as "duplicates" (`closed`
becomes `[]`, no verdict, no rejection counter), and the cursor then advances
via the `elif raw_page:` branch past the corrupt data. Net effect is the exact
opposite of the documented fail-closed behavior: corrupt data is skipped
silently instead of surfaced.
**Fix:**
```python
# move seen_open_times.add() to inside the `else:` (structural_ok) branch,
# after check_batch passes; on rejection leave the set untouched
```

### CR-03: Corrupt-page rollback with no rejection cap loops forever in-run

**File:** `src/data/backfill.py:380-395`
**Issue:** On `corrupt_rejection`, `cursor` is reset to
`last_published_open_ms + interval_ms`. When the FIRST page is corrupt (or every
subsequent fetch returns the same corrupt window), the cursor never advances and
the `while cursor < end_ms` loop re-fetches the identical page with no
max-rejections / max-pages guard and no raise. The inline comment ("a real
Binance rate-limit response will eventually surface so we don't loop forever")
is not a mechanism — a deterministically corrupt window never becomes a
rate-limit. One bad page hangs the bootstrap indefinitely.
**Fix:**
```python
# fail closed AND terminate: count consecutive rejections, then raise
consecutive_rejections += 1
if consecutive_rejections > MAX_CONSECUTIVE_REJECTIONS:
    raise StructuralRejectionError(symbol, interval, cursor)
# reset to 0 on any successful publish
```

### CR-04: `CollectorGap.symbol` is a nullable PK column — PostgreSQL rejects every tick-wide gap row

**File:** `src/db/models.py:124-128`, `src/db/alembic/versions/0001_baseline.py:67-76`, `src/data/collector.py:283-294,305-316,368-379,439-446`
**Issue:** The gap journal's PK is `(symbol, data_class, expected_utc)` but
`symbol` is declared `nullable=True`, and every tick-wide/skip/funding-error
path inserts `symbol=None`. PostgreSQL implicitly forces PK columns NOT NULL,
so all of these inserts fail on PG with a not-null violation. The suite passes
only because tests run on SQLite, which tolerates NULLs in PKs. This breaks
D-09 gap journaling on the real database — the exact path the fail-closed
posture depends on.
**Fix:**
```python
# use a sentinel instead of NULL for tick-wide gaps, e.g.:
symbol: Mapped[str] = mapped_column(String(32), primary_key=True, nullable=False)
# writer: symbol=symbol or "__TICK__"
```
Alternatively remodel the PK (surrogate id + unique constraint) via a reviewed
migration. Either way, add a PG-backed (or PG-dialect-compile) test so SQLite
no longer masks the constraint.

### CR-05: Funding coverage views query a column and filename pattern the collector never writes

**File:** `src/sql/coverage_v1.sql:81-92,95-106`, `src/data/collector.py:162-188`
**Issue:** Double mismatch. (a) The collector writes funding ticks with column
`funding_time_utc` to files named `sweep-<iso>.parquet`; `funding_coverage_v1`
and `all_tick_coverage_v1` select `CAST(observed_at_utc AS TIMESTAMP)` from glob
`tick-*.parquet`. The column does not exist in funding files and the glob never
matches `sweep-*` files, so the views error (swallowed by `_load_views` into a
`coverage.view_skipped` warning) and funding coverage is permanently empty.
(b) The `_columns_for_view` empty-frame stub for funding views projects
`observed_at_utc/open_interest`, compounding the shape lie. Test
`test_oi_coverage_view_reports_per_symbol_range` masks this by seeding the
`funding` partition with OI-shaped rows (`observed_at_utc`) instead of the real
funding schema.
**Fix:**
```sql
-- funding view must read the real column + real filename:
CREATE OR REPLACE VIEW funding_coverage_v1 AS
SELECT symbol, data_class,
  MIN(CAST(funding_time_utc AS TIMESTAMP)) AS historical_data_start_utc,
  MAX(CAST(funding_time_utc AS TIMESTAMP)) AS historical_data_end_utc,
  COUNT(*) AS rows
FROM read_parquet('data/raw/data_class=funding/symbol=*/date=*/sweep-*.parquet',
  hive_partitioning = true) GROUP BY symbol, data_class;
```
And fix the test seeder to write `funding_time_utc/funding_rate` rows plus the
empty-frame stub columns.

### CR-06: Production `backup` CLI wires a SQLite probe, not `pg_dump` — fake `backup-OK`

**File:** `src/ops/backup.py:280-295,332-347`
**Issue:** `_default_pg_dump_runner` writes a toy SQLite `_probe` table and
`main()` unconditionally uses it (`pg_dump_runner=lambda out:
_default_pg_dump_runner(out)`). The operator path (`scripts/backup-drill.ps1`
→ `python -m src.ops.backup backup`) therefore always prints `backup-OK` while
archiving zero PostgreSQL state. D-12 (operational PG state is restorable
off-host) is silently void in production.
**Fix:**
```python
# default runner must shell out to the real pg_dump (env-configured),
# and refuse to print backup-OK when it did not run:
def _prod_pg_dump_runner(out: Path) -> Path:
    subprocess.run(
        ["pg_dump", "--format=custom", "-f", str(out), os.environ["DATABASE_URL_SYNC"]], check=True
    )
    return out
```

### CR-07: `run_drill` does unguarded `shutil.rmtree(scratch_root)` — one misconfigured path deletes user data

**File:** `src/ops/backup.py:216-219`
**Issue:** `if scratch_root.exists(): shutil.rmtree(scratch_root)` with no
validation. A typo (`--scratch-root .`, `/`, `~`, the bundle root itself, or
`data/raw`) permanently deletes the working tree / live store / backup bundle.
Destructive recursive delete on an operator-supplied path must fail closed.
**Fix:**
```python
# refuse dangerous scratch roots before any delete:
resolved = scratch_root.resolve()
assert resolved != bundle_root.resolve(), "scratch must differ from bundle"
assert "backup-drill" in resolved.parts or os.environ.get("ALLOW_SCRATCH_RM") == "1"
# or at minimum require --scratch-root to be empty-or-missing, never wipe non-empty blindly
```

### CR-08: Adapter fabricates epoch-0 timestamps and zero OI/funding-rate on missing fields

**File:** `src/adapters/binance_usdm.py:219-223,282-294`
**Issue:** `int(oi.time or 0)` / `int(item.funding_time or 0)` turns a missing
timestamp into `1970-01-01T00:00:00Z`, and `Decimal(str(oi.open_interest or "0"))`
/ `Decimal(str(item.funding_rate or "0"))` turns a missing measurement into a
plausible-looking `0`. Downstream watermarks, gap math, and funding analytics
then treat fabricated values as real observations — a direct violation of the
flag-never-fabricate (D-09) posture. `symbol ... or ""` has the same shape
(empty-string symbol partition). Note `0 or "0"` also misfires on a genuine
numeric `0` (same output by accident, but the pattern is still wrong for
`None` vs `0` discrimination).
**Fix:**
```python
if oi.time is None or oi.open_interest is None:
    raise ValueError(f"open_interest response missing fields: {oi!r}")
observed_at_utc = _ms_to_utc(int(oi.time))
open_interest = Decimal(str(oi.open_interest))
# same strictness for funding_rate rows: skip-and-log or raise, never default to 0/epoch
```

### CR-09: `session_scope` is an async generator without `@asynccontextmanager` — every caller crashes

**File:** `src/db/models.py:189-194`
**Issue:** Defined as `async def session_scope(...) -> AsyncIterator` containing
`yield`, but never decorated with `@contextlib.asynccontextmanager`. Callers
doing the documented `async with session_scope(factory) as session:` get
`TypeError: 'async_generator' object does not support the asynchronous context
manager protocol`. The helper is dead code as written.
**Fix:**
```python
from contextlib import asynccontextmanager
@asynccontextmanager
async def session_scope(factory ...):
    async with factory() as session:
        yield session
```

### CR-10: Drill reports `equal=True` on partial restores; manifest hashes itself

**File:** `src/ops/backup.py:122-138,240-272`
**Issue:** Two compounding gaps. (a) `write_manifest` walks the whole bundle
root, so on any second/incremental run into the same `bundle_root` the pre-
existing `manifest.json` is hashed into the new manifest (self-referential
entry whose stored hash is immediately stale). (b) `run_drill` only verifies
files it chose to restore (`pg.dump` + requested `parquet_roots`) and never
compares the full manifest key set against the restored set — extra bundle
files, a skipped root, or the `manifest.json` entry itself are never flagged,
so truncated restores still yield `equal=True`.
**Fix:**
```python
# (a) exclude the manifest itself from its own hash:
files = sorted(p for p in payload_root.rglob("*") if p.is_file() and p.name != MANIFEST_NAME)
# (b) after re-hashing, assert set(manifest) - {"manifest.json"} == set(restored)
#     and fail on any manifest key never visited
```

## Warnings

### WR-01: `exchange_info` silently drops symbols with missing filters instead of surfacing contract drift

**File:** `src/adapters/binance_usdm.py:303-310`
**Issue:** The comment says a missing PRICE/LOT_SIZE/MIN_NOTIONAL filter "should
surface loudly via the fail-closed posture", but the code does `continue` with
no log, no counter, no raise. A delisted/changed live-5 symbol silently shrinks
the metadata refresh while the refresh reports success.
**Fix:** Log at error level with symbol + missing filter names and either raise
or return a per-symbol error count the caller must handle.

### WR-02: Harvest path has no fail-closed handling; funding empty-sweep is indistinguishable from success

**File:** `src/data/collector.py:339-447`
**Issue:** `async_funding_sweep` returns `funding_inserted=0, gaps=0` both when
there is genuinely nothing new and when every symbol returned empty due to an
upstream outage — callers cannot tell "caught up" from "blind". Worse,
`harvest_open_interest_history` has no try/except at all: an adapter exception
mid-universe leaves partial `oi_research` files on disk with no gap row and an
unpropagated partial state (inconsistent with the OI/funding paths that journal
a tick-wide gap).
**Fix:** Wrap the harvest loop like the funding sweep (one gap row on exception,
no watermark advance) and emit an explicit `sweep_empty` vs `sweep_ok`
distinction (e.g. record `last_poll_empty_utc` or return the per-symbol tick
counts).

### WR-03: Collector Parquet writers silently overwrite — no D-04 guard, tick-filename collisions

**File:** `src/data/collector.py:104-188`
**Issue:** Unlike `store.publish_batch` (raises `FileExistsError`),
`_write_oi_snapshot` / `_write_oi_research_snapshot` / `_write_funding_tick`
call `df.write_parquet(path)` unconditionally. Two ticks in the same minute
(same `_tick_iso` second-granularity name) or a retried tick silently
overwrites. The OI docstring even claims re-write "is a no-op against the
immutable store" — it is an overwrite, and with different data it destroys
evidence.
**Fix:** Check `path.exists()` first and raise (or write to a unique
`tick-<iso>-<nanos>.parquet`), matching the store's immutability rule.

### WR-04: Gap `reason` (String(256)) is never truncated — verbose adapter errors break gap journaling

**File:** `src/data/collector.py:305-313,368-376`, `src/db/models.py:132`
**Issue:** `reason=f"adapter_error: {type(exc).__name__}: {exc}"` is unbounded.
SQLite ignores the length; PostgreSQL raises `value too long for type character
varying(256)`, so the very insert meant to record the failure fails. The outage
then surfaces as a DB error instead of a gap row.
**Fix:** `reason=reason[:256]` (or widen the column via migration + truncate at
the writer; do both).

### WR-05: Quality gate misses negative prices/volumes, inverted close-times, and mixed-symbol batches

**File:** `src/data/quality.py:94-167`
**Issue:** `check_batch` catches duplicates, OHLC impossibility, regressions,
and density gaps — but a batch with negative `open/high/low/close/volume`,
`trade_count <= 0`, `close_time_utc <= open_time_utc`, or rows from two symbols
/ intervals passes `structural_ok=True` and is published. For an exchange-data
gate these are the cheapest structural rejects available.
**Fix:** Add `negative_values`, `bad_durations`, and `mixed_keys` counters to
the verdict and include them in `structural_ok`.

### WR-06: Neither `check_batch` nor `publish_batch` verifies batch homogeneity

**File:** `src/data/quality.py:94-101`, `src/data/store.py:43-58`
**Issue:** A batch mixing `BTCUSDT` and `ETHUSDT` rows (or `1m` + `1h`) passes
the gate and is written under whichever `(symbol, interval)` the caller passed
— cross-contaminating the immutable partition. The store trusts caller args
instead of the rows.
**Fix:** Assert `len({k.symbol}) == 1 and len({k.interval}) == 1` and that they
match the `publish_batch(symbol=, interval=)` arguments; reject otherwise.

### WR-07: Backup silently succeeds with zero payload; stale files are never pruned

**File:** `src/ops/backup.py:141-187`
**Issue:** Missing `parquet_roots` are `continue`d without a warning, so a
typo'd root yields a "successful" bundle containing only `pg.dump`. Conversely
the bundle is never pruned — files deleted from the source survive in the
bundle (and its manifest) forever, so restores resurrect deleted data and the
manifest drifts from the source of truth.
**Fix:** Warn (or fail when ALL roots are missing) and either garbage-collect
bundle entries absent from the source or document the bundle as append-only
with a `prune` subcommand.

### WR-08: Cursor persistence is non-atomic; day-alignment and durations use float time math

**File:** `src/data/backfill.py:75-77,136-139,255,275-285`
**Issue:** Three determinism/robustness nits in one path: (a)
`CursorStore.write` does a bare `write_text` — a kill mid-write leaves a torn
cursor that `read` then treats as corrupt/None. (b) `align_to_day_start_ms`
round-trips through float `timestamp() * 1000` (up to 1 ms skew; use integer
`ms - ms % 86_400_000`). (c) `durations_ms` uses wall-clock `datetime.now(UTC)`
rather than the injected `clock`, so `BackfillResult` is never byte-reproducible
despite the determinism contract.
**Fix:** Atomic write via tmp+`os.replace`; integer day snap; measure durations
with `time.monotonic` (and exclude them from any equality assertion) or drop
the field from the reproducibility contract.

### WR-09: Coverage loader interpolates paths into SQL, swallows view errors, and never gaps funding

**File:** `src/data/coverage.py:46-143,349-399`
**Issue:** (a) `f"SELECT count(*) FROM glob('{glob_pat}')"` interpolates
`raw_root` without escaping — a `'` in the path breaks the statement (local-
operator SQL injection/crash). (b) View-creation failures are caught and
downgraded to a `view_skipped` warning, so later `SELECT ... FROM coverage_v1`
crashes far from the cause. (c) `build_oi_coverage` computes `gap_count` only
for `data_class == "oi"`; funding rows always report `gap_count: 0`,
under-reporting D-11 continuity.
**Fix:** Bind the glob path as a query parameter (or escape single quotes),
re-raise when a required view fails to build, and apply the cadence estimator
to funding (8h funding cadence) or document why funding is exempt.

### WR-10: Paginator robustness gaps — shared cadence, missing flush callback, empty-page spin, dead retry alias

**File:** `src/data/backfill.py:40-42,147-187,390-398,400-434`
**Issue:** (a) `backfill_universe` reuses one cadence for all intervals (see
CR-01) — even fixed, `BackfillConfig.interval_ms` is not cross-checked against
`interval_ms(interval)`. (b) `on_publish` fires for buffered-date publishes but
NOT for the end-of-loop flush, so progress consumers undercount. (c) An empty
`raw_page` advances only one `interval_ms` per round-trip, so a 30-day `1m`
hole issues ~43k serial fetches instead of breaking fast. (d)
`_RATE_LIMIT_ERRORS = (tenacity.RetryError,)` is dead code (the retry predicate
is `_is_rate_limit`), and `_is_rate_limit` sniffs exception class-name
substrings that were never verified against the installed SDK's real error
types — a renamed SDK exception silently disables all retry.
**Fix:** Validate `cfg.interval_ms == interval_ms(interval)`; fire `on_publish`
in the flush loop; `break` (or jump to `end_ms`) after N consecutive empty
pages; delete the dead alias and pin the retry predicate with a test against
the real SDK exception path.

### WR-11: Container/packaging gaps — missing `alembic.ini`, no-op healthcheck, unmounted backup path, root runtime

**File:** `Dockerfile:14-26`, `docker-compose.yml:39-50`, `.env.example:29`
**Issue:** (a) The image copies `src` + `scripts` but not `alembic.ini`, so any
in-container `alembic upgrade head` fails (config missing). (b) `HEALTHCHECK`
runs `python -c "import sys; sys.exit(0)"` — always healthy, even with a dead
collector loop. (c) `rawdata:/app/data/raw` is mounted but the backup bundle
(`data/backup`, `OFF_HOST_BACKUP_TARGET=./backup`, ps1 default `data/backup`)
lives on the container's ephemeral FS — restarts silently discard "off-host"
bundles. (d) No `USER` directive — the collector runs as root.
**Fix:** `COPY alembic.ini ./`; healthcheck the watermark freshness or process
liveness; mount the backup bundle to the host/OneDrive path and unify the three
conflicting backup-path defaults; add `RUN useradd` + `USER`.

### WR-12: `backup-drill.ps1` breaks on spaces, mutates caller CWD, splits roots naively

**File:** `scripts/backup-drill.ps1:30-61`
**Issue:** (a) `Set-Location $ScriptRoot\..` is unquoted and never restored
(`Push-Location`/`Pop-Location`) — it permanently changes the operator's shell
directory and fails on space-containing repo paths. (b)
`($ParquetRoots -split " ")` and unquoted `--bundle-root $BackupTarget` splits
any path containing a space (common under OneDrive/user profiles). (c)
`BACKUP_TARGET` default `data/backup` disagrees with `.env.example`
`./backup`, so the wrapper and the documented env var target different
directories by default.
**Fix:** Quote all path expansions, use `Push-Location (Join-Path $ScriptRoot
"..")` + `Pop-Location` in `finally`, accept `;`-separated roots, and align
all three defaults on one canonical path.

### WR-13: Engine/session helpers leak connections; config weakens the strictness it claims

**File:** `src/db/models.py:171-186`, `pyproject.toml:73-79`
**Issue:** (a) `make_session_factory` builds a NEW engine per call with no
dispose path — repeated calls (tests, CLI, collector restarts) leak pools.
(b) `make_engine` claims "the async swap lives here" but only rewrites the
bare `postgresql://` scheme; the canonical `.env` URL is already
`postgresql+psycopg://` (sync-scheme string) handed to `create_async_engine`
without validation that the resolved dialect is actually async. (c)
`[tool.mypy] ignore_missing_imports = true` with `strict = true` silently hides
missing SDK/type stubs — the adapter boundary is exactly where strictness
matters most.
**Fix:** Cache/share one engine per URL (or expose `dispose`), assert the final
URL's async dialect, and set `ignore_missing_imports = false` (add explicit
per-module overrides if the SDK ships no stubs).

### WR-14: Parity script compares column names only — type/nullability/PK drift passes green

**File:** `scripts/check_migration_parity.py:37-47,85-121`
**Issue:** The DDL regex extracts only column NAMES and only for a hardcoded
type list (`VARCHAR|TIMESTAMP|NUMERIC|...` — no `BIGINT/JSONB/UUID`). A drift
from `NUMERIC(38,18)` → `FLOAT`, `TIMESTAMPTZ` → naive `TIMESTAMP`, or a lost
PK/index passes as "parity green". The table-name split (`split()[2]`) also
breaks on schema-qualified names.
**Fix:** Compare `(name, type, nullable, pk)` tuples (render both sides via
`CreateTable(...).compile()` and diff the full column spec), and fail loudly
on unparsed lines instead of ignoring them.

### WR-15: Collector availability posture — one bad symbol kills the whole tick; writes can half-fail without a gap

**File:** `src/data/collector.py:300-336,361-404`
**Issue:** (a) The OI loop aborts the ENTIRE 5-symbol tick on the first adapter
exception (documented as "deferred per-symbol recovery") — a single delisted
symbol blinds the other four indefinitely. (b) Parquet writes happen before
`session.commit()` with no try/except: a disk-full / permission error mid-loop
leaves partial files, no commit, no gap row, and an unjournaled inconsistency
the docstring waves through as "acceptable".
**Fix:** Per-symbol try/except (healthy symbols commit + advance; failed symbols
get per-symbol gap rows), and wrap the write+commit section so any failure
records a gap row before propagating.

## Info

### IN-01: Dead code and imprecise types

**File:** `src/data/backfill.py:42`, `src/data/collector.py:52`, `src/data/coverage.py:153-178`
**Issue:** `_RATE_LIMIT_ERRORS` is defined but never referenced (the live
predicate is `_is_rate_limit`); `AdapterLike = BinanceUsdmAdapter | object`
collapses to `object` (no type checking value — use a `Protocol`); the
`candles_v1` empty-frame stub projects a `date` column the real view never
selects (harmless but misleading).
**Fix:** Delete the dead alias, model the adapter as a `Protocol` with the four
methods tests rely on, and align the stub column list with the real SELECT.

### IN-02: Function-level `import json` in hot helpers

**File:** `src/adapters/binance_usdm.py:376-400`
**Issue:** `_order_capabilities_blob` / `_position_mode_blob` import `json`
inside the function body on every symbol of every `exchange_info` call.
Functionally fine, stylistically noisy.
**Fix:** Hoist `import json` to module top.

### IN-03: Canonical sets are triple-sourced and can drift

**File:** `src/data/quality.py:24-32`, `src/data/backfill.py:466-479`, `src/data/coverage.py:42-43`, `tests/conftest.py:27`
**Issue:** `INTERVAL_MS`, `DEFAULT_BACKFILL_WINDOWS_MS`, `CANONICAL_INTERVALS`,
and `LIVE_5` (defined separately in `backfill` AND `conftest`) encode the same
universe in four places. Adding `15m` to one table but not the others silently
changes gap math vs bootstrap vs CLI matrix.
**Fix:** Single `src/data/universe.py` (or constants module) re-exported by
backfill/coverage/tests.

### IN-04: Eager SDK construction in `BinanceUsdmAdapter.__init__`

**File:** `src/adapters/binance_usdm.py:177-178`
**Issue:** `DerivativesTradingUsdsFutures()` is constructed eagerly even for
code paths that only need the dataclass types, coupling import-time-adjacent
setup to network/config state and making every test pay for (or mock around)
client construction.
**Fix:** Lazy-construct on first API call (or require explicit injection with a
`default_client()` factory), keeping `__init__(sdk_client=None)` cheap.

---

_Reviewed: 2026-09-21T00:00:00Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
