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
  warning: 7
  info: 7
  total: 14
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-09-21T00:00:00Z
**Depth:** deep
**Files Reviewed:** 30
**Status:** issues_found

## Summary

Iteration-2 re-review at deep depth against the current on-disk source (27
`fix(02)` commits on top of the previously reviewed tree). Every one of the
prior 10 Critical (CR-01..CR-10) and 15 Warning (WR-01..WR-15) findings was
re-opened and re-read at the exact cited lines — **all 10 Criticals are
verified resolved** (per-interval backfill config with cadence validation,
post-gate dedup marking, rejection budget with `StructuralRejectionError`,
`TICK_WIDE_SYMBOL` sentinel with non-nullable PK in model + migration,
funding view on the real `funding_time_utc`/`sweep-*` shape, real `pg_dump`
runner as the production default, scratch-root guard, strict adapter
missing-field raises, `@asynccontextmanager` session scope, self-excluding
manifest plus full-set drill comparison). Verification: `uv run python -m
pytest tests/ -q` → 72 passed; `uv run ruff check src tests scripts` → clean.

No Critical defects remain. What remains are **7 warnings** — 6 narrowed
residuals where a fix closed the main vector but left a live edge
(space-path splitting, raw-store scratch gap, exchange-info
zero-fabrication, append-only bundle drift, SDK-rename-blind retry pinning,
no-op container entrypoint) plus a red `mypy --strict` gate the fixes
interact with — and **7 info items** (4 carried-over style items the fixer
correctly left out of scope, 3 new low-severity observations). No fix
introduced a regression that breaks tests or re-opens a Critical.

## Warnings

### WR-01: `backup-drill.ps1` still splits roots on whitespace — space-containing paths cannot survive

**File:** `scripts/backup-drill.ps1:38-40`
**Issue:** The WR-12 fix quotes expansions and restores CWD, but the root
splitter is `-split "[;\s]+"`, which fragments on ANY whitespace run. A
single root under a space-containing profile (the documented OneDrive case,
e.g. `C:\Users\daotu\OneDrive\...\data\raw`) is chopped into pieces and
passed as multiple `--parquet-roots` args, so the drill backs up the wrong
paths or fails. The comment on line 38-39 claims the opposite ("so roots
under space-containing profiles survive as single paths") — the claim is
false for the `[...\s...]` alternative. A path with a space is unpassable no
matter which separator the operator uses, because spaces always split.
**Fix:**
```powershell
$RootList = @($ParquetRoots -split ";" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
```
Split on `;` only (the documented separator per line 20-21); trim each entry.

### WR-02: Scratch-root guard omits the live immutable store — `--scratch-root data/raw` still wipes it

**File:** `src/ops/backup.py:212-246`, `src/ops/backup.py:279-280`
**Issue:** The CR-07 guard now blocks fs-root, home, CWD, bundle==scratch,
and bundle↔scratch nesting — but `data/raw` (the live D-04 store) is none of
those: it resolves differently from CWD (repo root), home, and
`data/backup`, so `_assert_safe_scratch_root` passes and `shutil.rmtree`
deletes every collected candle/tick. `data` itself IS caught (bundle nests
inside it), but the single most plausible typo (`data/raw` vs
`data/backup-drill`) is not. Residual data-loss vector from the original
Critical.
**Fix:**
```python
# refuse to wipe the live store / any path inside the repo data dir
# that is not an explicit drill directory:
resolved = scratch_root.resolve()
if resolved == Path("data/raw").resolve() and "drill" not in resolved.parts:
    raise ValueError(f"refusing drill: {scratch_root} is the live raw store")
```
Or allowlist scratch roots to names containing `drill`/`scratch`.

### WR-03: `exchange_info` still fabricates zero/empty-string fields; OI harvest silently drops malformed rows

**File:** `src/adapters/binance_usdm.py:255-259,343-349,360-371`
**Issue:** CR-08 fixed `open_interest`/`funding_rate`, but two fabrication
paths remain on the same adapter. (a) `Decimal(str(f_price.tick_size or
"0"))` / `step_size` / `min_qty` / `notional` turn a missing filter field
into a plausible `0`: a zero `price_tick_size` persists to
`symbol_metadata` and poisons downstream quantization (divide-by-zero or
floor-everything-to-zero), wearing the clothes of real data — the exact
D-09 violation CR-08 removed elsewhere. Same for `sym.symbol or ""` /
`contract_type or ""` / asset `or ""` (empty-string symbol partition).
`max_qty` is already strict (`is not None` check) — the siblings should
match. (b) `open_interest_statistics` does `if ts is None or oi is None:
continue` — silently dropping corrupt harvest rows while the canonical OI
and funding paths raise. A harvest with 29 corrupt + 1 good row reports
success with no signal.
**Fix:**
```python
# (a) strict, like max_qty two lines below:
if f_price.tick_size is None or f_lot.step_size is None:
    raise ValueError(f"exchangeInfo filter missing numeric field: {sym.symbol!r}")
tick = Decimal(str(f_price.tick_size))
# (b) raise instead of continue, matching open_interest/funding_rate:
if ts is None or oi is None:
    raise ValueError(f"open_interest_statistics row missing fields: {item!r}")
```

### WR-04: Bundle never prunes — restores resurrect deleted source data, manifest drifts from source of truth

**File:** `src/ops/backup.py:167-168,186-194`
**Issue:** WR-07 fixed the silent pg.dump-only bundle (warn + refuse when
all roots missing), but the second half — stale-file pruning — is still
absent, now explicitly entrenched by the docstring ("never deletes files in
`bundle_root` — operators can run it incrementally"). Files deleted from
`data/raw` survive in the bundle and its manifest forever, so a restore
resurrects data the operator deliberately removed and the manifest no longer
describes the source. For an append-only design this must be an operator-
visible contract with a `prune` path, not a code-comment aside.
**Fix:** Either garbage-collect bundle entries absent from the source roots
on each run, or document the bundle as append-only in the module docstring +
CLI help and add a `prune` subcommand that reconciles bundle against source.

### WR-05: Retry predicate works today but the pinning test never touches the real SDK classes

**File:** `src/data/backfill.py:180-188`, `tests/test_backfill.py:444-462`
**Issue:** Verified against the installed SDK (17.x): it exposes
`TooManyRequestsError` and `RateLimitBanError`, both matched by the
substring sniff, so retries fire correctly today. The residual is the
failure mode WR-10(d) named: the predicate still sniffs class-name
substrings instead of importing the real classes, and the new pinning test
defines LOCAL fakes (`class TooManyRequestsError(Exception)` in the test
file) rather than importing the installed SDK's errors. A Binance SDK rename
keeps the test green while silently disabling all bootstrap retry — the test
provides false confidence about exactly the coupling it claims to pin. (Note:
`RateLimitBanError` is the 418 IP-ban signal; retrying a ban with backoff
can extend the ban per Binance docs — worth a deliberate policy, not silent
parity with 429.)
**Fix:**
```python
# test against the real installed SDK surface:
from binance_sdk_derivatives_trading_usds_futures import (
    RateLimitBanError, TooManyRequestsError,
)
assert _is_rate_limit(TooManyRequestsError("429")) is True
assert _is_rate_limit(RateLimitBanError("418")) is True
```
And consider importing the SDK errors in `_is_rate_limit` (isinstance)
with the substring sniff as fallback, plus distinct handling for 418 (abort
to SAFE_MODE rather than backoff-retry).

### WR-06: Shipped container entrypoint is a no-op — `python -m src.data.collector` imports and exits

**File:** `Dockerfile:32-34`, `docker-compose.yml:49`, `src/data/collector.py` (no `main`/`__main__`)
**Issue:** `src/data/collector.py` exposes `async_oi_tick` /
`async_funding_sweep` / `harvest_open_interest_history` but defines no
`main()` and no `if __name__ == "__main__"` block (grep over `src/` confirms
zero production callers of any of the three operations). Both the Dockerfile
`CMD` and the compose `command` invoke `python -m src.data.collector`,
which therefore imports the module and exits 0 having polled nothing. Paired
with the import-only HEALTHCHECK (always healthy — the WR-11 residual), the
deployed "collector" is a silent no-op that reports healthy forever: no
crash, no log, no watermark, no gap row. The module docstring says "the loop
is owned by the orchestrator", but no loop/scheduler exists anywhere in the
repo, so D-07 has no runnable path as shipped.
**Fix:** Add a `main()` + `__main__` entrypoint to `src/data/collector.py`
that runs the 5-minute poll loop (universe, cadence, watermark session,
fail-closed handling) and point `CMD`/compose at it; promote HEALTHCHECK to
watermark-freshness (or at minimum a process-liveness probe that fails when
no tick has completed within 2× cadence).

### WR-07: `mypy --strict` is red — 84 errors in 5 files; the fixes extend the untyped pattern

**File:** `src/data/quality.py:155` (64 errors), `src/data/coverage.py:405-421,438-453`
(19 errors), `src/data/collector.py:328,403,486,...` (12 errors),
`src/adapters/binance_usdm.py:213,286` (2 errors), `src/db/models.py:186`
(1 error)
**Issue:** `uv run mypy src` (`strict = true` per `pyproject.toml`, and the
STACK mandates strict typing over domain/execution paths) reports 84 errors
in 5 files. Most are pre-existing baseline debt, but the iteration-1 fixes
interact with it two ways. (a) The WR-09 fix's new funding-cadence branch in
`build_oi_coverage` copies the existing untyped pattern: `oi_coverage_rows`
returns `list[dict[str, object]]`, so every `r["start_utc"]` / `r["end_utc"]`
/ `int(r["rows"])` access in BOTH the oi and the new funding branch is an
`arg-type`/`call-overload` error, and `build_oimeta_view` mixes
`CoverageCell` attribute access with `dict[str, Any]` rows (19 errors in
`coverage.py` alone). New code was added in a form that can never pass the
project's own type gate. (b) The WR-13 strictness flip (`ignore_missing_
imports = false` + `warn_unused_ignores = true`) now flags the
`AdapterLike`-collapse fallout directly: `collector.py:486` reports `Unused
"type: ignore" comment` + `union-attr not covered by "type:
ignore[attr-defined]"` — every `# type: ignore[attr-defined]` on the
adapter calls names the wrong error code (the true error is `union-attr`
from `BinanceUsdmAdapter | object`), so the ignores are both incorrect AND,
under the new flags, errors themselves. `quality.py:155` (`v.total_
seconds()` on a `diff()` union) dominates the count and is the same
untyped-frame pattern. The suite is green only because no gate runs mypy.
**Fix:** Type the coverage rows (`TypedDict` with `datetime | None` /
`int` fields instead of `dict[str, object]`, or convert to `CoverageCell`
at the boundary); fix the ignore codes to `type: ignore[union-attr]` (or
adopt the `Protocol` from IN-01 and drop the ignores); narrow the
`quality.py:155` diff handling to `timedelta` before calling
`.total_seconds()`; add `mypy src` to the phase verification gates so the
strict contract is enforced instead of aspirational.

## Info

### IN-01: `AdapterLike` still collapses to `object`; candles stub carries a phantom `date` column

**File:** `src/data/collector.py:52`, `src/data/coverage.py:158-173`
**Issue:** Residual of prior IN-01 (dead alias was correctly removed).
`AdapterLike = BinanceUsdmAdapter | object` collapses to `object`, so the
`# type: ignore[attr-defined]` comments on every adapter call are load-
bearing and mypy strict learns nothing at the adapter boundary — exactly
where strictness matters. Separately, the `candles_v1` empty-frame stub
projects `CAST(NULL AS DATE) AS date`, which the real view never selects
(harmless: the stub only feeds `WHERE 1 = 0` compiles, but misleading to the
next reader).
**Fix:** Model the adapter as a `typing.Protocol` with the four methods
tests rely on (`klines`, `open_interest`, `funding_rate`,
`open_interest_statistics`); drop `date` from the stub or select it in the
view.

### IN-02: Function-level `import json` in per-symbol helpers

**File:** `src/adapters/binance_usdm.py:413-416,419-437`
**Issue:** Unchanged from prior review: `_order_capabilities_blob` /
`_position_mode_blob` import `json` in the function body on every symbol of
every `exchange_info` call. Functionally fine, stylistically noisy.
**Fix:** Hoist `import json` to module top.

### IN-03: Canonical sets still triple-sourced and driftable

**File:** `src/data/quality.py:24-32`, `src/data/backfill.py:544-558`, `src/data/coverage.py:42-44`, `tests/conftest.py:27`
**Issue:** Unchanged: `INTERVAL_MS`, `DEFAULT_BACKFILL_WINDOWS_MS`,
`CANONICAL_INTERVALS`, and `LIVE_5` (defined separately in `backfill` AND
`conftest`) encode the same universe in four places. Adding `15m` to quality
but not to the universe runner silently changes gap math vs bootstrap vs CLI
matrix.
**Fix:** Single constants module re-exported by backfill/coverage/tests.

### IN-04: Eager SDK construction in `BinanceUsdmAdapter.__init__`

**File:** `src/adapters/binance_usdm.py:180-181`
**Issue:** Unchanged: `DerivativesTradingUsdsFutures()` constructs eagerly
even for code paths needing only dataclass types, coupling setup to
network/config state and forcing every test to mock around it.
**Fix:** Lazy-construct on first API call (or a `default_client()` factory),
keeping `__init__(sdk_client=None)` cheap.

### IN-05: `oi_coverage_rows` still swallows query-time view errors

**File:** `src/data/coverage.py:371-378`
**Issue:** Narrowed residual of WR-09 (loader escaping, loud build failures,
and funding gap cadence all verified fixed): the per-view `SELECT` is still
wrapped in bare `except duckdb.Error: continue`, so a query-time failure on
one class silently drops that class's coverage rows. Build failures now raise
loudly in `_load_views`, which shrinks this window to SELECT-time faults —
but a funding-schema drift that compiles empty and fails at select would
still vanish without a trace.
**Fix:** Log at error level with the view name before `continue`, or let the
SELECT raise like view-build failures do.

### IN-06: Harvest completion marker shares the gap journal

**File:** `src/data/collector.py:504-511`
**Issue:** New observation (deliberate, documented design — hence Info, not
Warning): every `harvest_open_interest_history` call writes a
`reason="harvest_complete: ..."` row into `collector_gaps` with an epoch-0
sentinel `expected_utc`. Any consumer counting gap rows (outage accounting,
D-11 continuity) must parse `reason` prefixes to exclude non-gaps, and the
epoch-0 row joins oddly with real gap ranges. The PK-merge makes repeat
harvests idempotent, so this is semantics, not corruption.
**Fix:** Write harvest markers to a separate audit/event table (or a
`collector_runs` log), keeping `collector_gaps` exclusively for missing-data
flags; at minimum document the `reason`-prefix filter contract consumers
must apply.

### IN-07: `backfill_universe` aborts the whole universe on the first per-key failure

**File:** `src/data/backfill.py:636-650`
**Issue:** New observation: a `StructuralRejectionError` (or adapter
exception) for one (symbol, interval) propagates out of
`backfill_universe`, abandoning all remaining keys and discarding the
already-collected `per_key` results. Fail-closed per key is correct, but the
runner lacks the per-symbol isolation the collector just gained (WR-15):
one corrupt window in `XRPUSDT/1m` blocks `BTCUSDT/4h` from bootstrapping in
the same run, and the operator loses the partial summary.
**Fix:** Wrap the per-key call in try/except, record the error in the result
(e.g. `failed: dict[tuple[str,str], str]`), continue with remaining keys,
and raise/signal at the end if any key failed.

---

_Reviewed: 2026-09-21T00:00:00Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
