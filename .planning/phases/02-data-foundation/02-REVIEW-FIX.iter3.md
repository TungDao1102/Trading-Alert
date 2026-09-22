---
phase: 02-data-foundation
fixed_at: 2026-09-22T00:00:00Z
review_path: C:/Users/daotu/OneDrive/Documents/Trading-Alert/.planning/phases/02-data-foundation/02-REVIEW.md
iteration: 2
findings_in_scope: 7
fixed: 7
skipped: 0
status: all_fixed
---

# Phase 02: Code Review Fix Report

**Fixed at:** 2026-09-22T00:00:00Z
**Source review:** `02-REVIEW.md` (iteration-2 re-review: 0 Critical / 7 Warning / 7 Info)
**Iteration:** 2

**Summary:**
- Findings in scope: 7 (all Warnings; Info findings out of scope per fix_scope)
- Fixed: 7
- Skipped: 0

**Verification (per fix, main checkout):** `uv run python -m pytest tests/ -q` green (77 passed at end, up from 64 baseline via new regression tests), `uv run ruff check src tests scripts` clean, and `uv run mypy src` converges to `Success: no issues found in 15 source files` (was 84 errors). One mid-run failure is documented under WR-05 (architectural guard caught the first attempt; reworked and green). No failing test was deleted; tests were only added or updated to corrected behavior. All work ran in the main checkout (no isolated worktree — `workflow.use_worktrees` is unset and the PowerShell environment has no worktree tooling; prior `fix(02)` commits also landed directly on `master`).

## Fixed Issues

### WR-01: `backup-drill.ps1` still splits roots on whitespace

**Files modified:** `scripts/backup-drill.ps1`
**Commit:** 6c4b266
**Applied fix:** Root splitter changed from `-split "[;\s]+"` to `-split ";"` with per-entry `Trim()` and empty filtering, so space-containing roots (OneDrive profiles) survive as single paths. Also corrected the two comments that claimed whitespace-splitting was safe / "spaces also accepted" — `;` is now documented as the ONLY separator.

### WR-02: Scratch-root guard omits the live immutable store

**Files modified:** `src/ops/backup.py`, `tests/test_backup.py`
**Commit:** 98b0d9d
**Applied fix:** `_assert_safe_scratch_root` now refuses the live raw store in both directions — the store itself, anything inside it (partial wipe), and anything above it (wiping an ancestor such as `data` deletes the store when the bundle lives off-host). This closes the exact gap the docstring already claimed ("or `data/raw`") but the code never enforced. New `test_drill_refuses_live_raw_store_as_scratch` covers all three directions plus a passing unrelated scratch dir.

### WR-03: `exchange_info` fabricates zero/empty fields; OI harvest silently drops rows

**Files modified:** `src/adapters/binance_usdm.py`, `tests/test_adapter_strictness.py` (new)
**Commit:** 9d47fc3
**Applied fix:** (a) `tick_size`/`step_size`/`min_qty`/`notional` missing → immediate `ValueError` (never `or "0"`); missing identity fields (`symbol`, `contract_type`, `status`, base/quote/margin assets) → drift path (log + collect + raise at end, never `or ""`). `order_types or []` kept — empty capabilities is honest absence, not a fabricated measurement. (b) `open_interest_statistics` malformed rows now `raise ValueError` instead of `continue`, matching the canonical OI/funding paths. New test module pins all of this against the real installed SDK pydantic models (5 tests). No existing test called `exchange_info` directly, so no behavior updates were needed elsewhere.

### WR-04: Bundle never prunes — restores resurrect deleted data

**Files modified:** `src/ops/backup.py`, `tests/test_backup.py`
**Commit:** 2d2cfcf
**Applied fix:** Added `prune_bundle()` + `prune` CLI subcommand (with `--dry-run`): garbage-collects bundle entries under `parquet/<basename>/...` whose source file no longer exists, removes newly-empty dirs, and rewrites the manifest. Keys that cannot be mapped to a known root (`pg.dump`, unknown basenames, malformed keys) are always kept. `backup()` docstring updated to state the append-only contract + prune pointer (replacing the bare "never deletes" aside). Three new tests: stale-entry pruning (+manifest rewrite), dry-run purity, unmapped-key retention.

### WR-05: Retry-predicate pinning test uses local fakes, not real SDK classes

**Files modified:** `src/data/backfill.py`, `src/adapters/binance_usdm.py`, `tests/test_backfill.py`
**Commit:** b468f2a
**Applied fix:** The predicate now matches `isinstance` against the real installed SDK errors (`TooManyRequestsError`, `RateLimitBanError`), with the class-name sniff kept only as fallback for wrapped errors; the pinning test imports the real SDK classes. **Mid-run correction (recorded):** the first attempt imported the SDK errors directly in `backfill.py`, which broke `test_adapter_returned_type_is_domain_kline` — the static guard enforcing that the adapter is the ONLY module importing the SDK. Reworked per the architecture: classification lives in `src/adapters/binance_usdm.py` as `is_rate_limit_error()` (adapter owns the SDK import), `backfill._is_rate_limit` delegates to it, and the adapter import fails loudly at import time on any SDK rename. Distinct 418-vs-429 retry policy was NOT changed (review said "consider"; retry parity preserved, no behavior change).

### WR-06: Shipped container entrypoint is a no-op

**Files modified:** `src/data/collector.py`, `Dockerfile`, `docker-compose.yml`, `tests/test_collector.py`
**Commit:** afa2e74
**Applied fix:** Added a real `main()` + `__main__` entrypoint: the 5-minute poll loop (universe default live-5, configurable cadence, per-tick sync session, OI tick + funding sweep per iteration with funding resuming at `watermark + 1` so the tick-file immutability guard is never tripped on restart), `--once` single-tick mode, and `--healthcheck` watermark-freshness probe (exit 0 iff every universe symbol has an OI watermark newer than 2x cadence). Per-tick unexpected exceptions are logged with traceback and the loop survives (fail-closed accounting already journaled a gap inside the tick); missing DB URL refuses to start. Dockerfile `HEALTHCHECK` promoted from import-only to the freshness probe; compose `command`/`CMD` (`python -m src.data.collector`) now actually runs the loop, and compose sets an in-network `DATABASE_URL` (container cannot reach PG via the `localhost` URL in `.env`; built from the already-required postgres vars). Module docstring updated (loop no longer "owned by the orchestrator"). Four new tests: `_run_once_tick` publishes + advances both watermark namespaces, healthcheck fails with no watermarks, passes with fresh ones, and `--help` subprocess proves a real entrypoint.

### WR-07: `mypy --strict` is red — 84 errors in 5 files

**Files modified:** `src/db/models.py`, `src/adapters/binance_usdm.py`, `src/data/quality.py`, `src/data/coverage.py`, `src/data/collector.py`, `src/ops/backup.py`
**Commit:** 408c11d
**Applied fix:** `uv run mypy src` → **0 errors** (was 84 + 4 self-introduced by the prune `report` reuse, all fixed). Per file: `models.py` — `make_engine() -> AsyncEngine`, engine cache typed `dict[str, AsyncEngine]` (fixes the `no-any-return` spillover), dropped the now-unused `Any` import; `binance_usdm.py` — `_row_to_kline` takes `Sequence[Any]` (SDK returns tuples), funding-history `data()` unwrapped defensively via `isinstance(..., list)` instead of trusting the single-model stub; `quality.py` — `open_time_utc` extrema narrowed with `isinstance(..., datetime)`, non-datetime raises fail-closed (schema drift) instead of guessing gap math (all 59 line-155 errors); `coverage.py` — new `OICoverageRow` TypedDict replaces `dict[str, object]` (runtime shape unchanged — TypedDict IS a dict), `build_oi_coverage` returns it, `build_oimeta_view` loop var renamed `r` → `cell` fixing the `CoverageCell`-vs-`dict` collision; `collector.py` — `AdapterLike` is now a `typing.Protocol` (IN-01 partial: mypy checks the adapter boundary; the phantom `date` stub column left untouched as out-of-scope Info), all three wrong-code `type: ignore[attr-defined]` dropped, schema dicts use `pl.String()` instances; `backup.py` — prune-branch variable renamed `prune_report` (was colliding with the drill `RestoreReport`). No `type: ignore` added anywhere; three wrong-code ones removed.

---

_Fixed: 2026-09-22T00:00:00Z_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: 2_
