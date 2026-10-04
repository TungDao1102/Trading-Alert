---
phase: 13-research-data-foundation-fixes
fixed_at: 2026-10-03T14:30:00Z
review_path: .planning/phases/13-research-data-foundation-fixes/13-REVIEW.md
iteration: 1
findings_in_scope: 11
fixed: 11
skipped: 0
status: all_fixed
---

# Phase 13: Code Review Fix Report

**Fixed at:** 2026-10-03T14:30:00Z
**Source review:** .planning/phases/13-research-data-foundation-fixes/13-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 11 (4 critical, 7 warning; Info findings were out of scope)
- Fixed: 11 (CR-04 only in part, see below)
- Skipped: 0

**Verification environment:** every gate ran in the main checkout (`workflow.use_worktrees` is `false`), so the numbers are reproducible from the tree you are looking at. Each commit ran its touched tests, `ruff check`, `ruff format` and `mypy` on the touched `src/` files first. No `.env`, database, collector, backfill or Binance call was used. Nothing under `data/raw/` was written, moved or deleted (one read-only `pl.read_parquet_schema` on a DOGSUSDT 1h partition to learn the legacy scale).

**Final full run:** after the last commit, `pytest tests` with the three files below excluded passes completely (exit 0, some docker-marked tests skipped).

**Unrelated failures seen in the earlier full test run (not caused by these commits):** `tests/test_deploy_workflows.py::test_ci_docker_job`, `tests/test_docker_cutover.py::test_the_reported_oi_gap_is_the_engineered_forty_five_minutes` and `tests/test_deploy_docs.py::test_refresh_pins_lookup_is_read_only_and_reports_moves`. They are CI-workflow, docker and deploy-script tests with no overlap with the changed code.

**Pre-existing lint item left alone on purpose:** `ruff check .` reports E501 on the `FROZEN_CONTENT_SHA256` line in `scripts/decision_alignment/universe.py`. That line is the hash witness the freeze test rewrites, so it is kept byte-identical (an auto-format wrapped it and broke `test_freeze_writes_matching_witnesses`; it was restored before the WR-03 commit).

## Fixed Issues

### CR-01: Structural-rejection budget can be reset forever

**Files modified:** `src/data/backfill.py`, `tests/test_backfill.py`
**Commit:** 8acad28
**Applied fix:** `consecutive_rejections` is reset only when the page contributed new accepted rows (`accepted_new`). A rollback re-fetch that returns only already-buffered, de-duplicated rows no longer clears the budget, so `StructuralRejectionError` trips. Added `test_corrupt_page_after_good_page_on_same_day_raises_instead_of_looping` with a stateless exchange-like fake (good page, then deterministically corrupt page, same UTC day). It fails on the old code and passes now, with a bound on the number of fetches.

### CR-02: Store/cursor resume floor silently skips older history

**Files modified:** `src/data/backfill.py`, `tests/test_backfill_resume_floor.py` (new)
**Commit:** b9accd9
**Applied fix:** With `resume_from_store=True` (always on in the CLI) the published store, not the newest partition or the cursor file, decides what is fetched. New helpers `published_days` and `missing_day_runs` split the requested window into runs of unpublished UTC days. Each run is one fetch segment that ends at the midnight of the next published day, so a stored day is never touched (D-04) and the closed-day and terminal-day rules are unchanged. A stray newer partition no longer hides older missing days, and a deeper explicit window now extends history backwards (the D-21 1m extension case). The cursor is advisory in this mode. Warning-level logs: `backfill.universe.interior_hole` (missing runs before published days), `backfill.universe.cursor_ahead_of_store`, and in the legacy cursor-only mode `backfill.universe.empty_window` now logs at warning, with `requested_start_ms`, `floored_start_ms` and `floor_reason`, when a cursor floor empties a window the caller requested. A fully covered window logs `complete_from_store` at info. `backfill.universe.begin` now carries `requested_start_ms`. 7 new tests cover stray partition, cursor ahead of store, contiguous store (no adapter call), deeper window, the legacy warning and the run splitter.
**Status note:** logic change, requires human verification.
**Behavior to be aware of:** an interior day that Binance genuinely has no bars for is re-requested on every run (one request per such run). The old latest-day floor skipped it silently. The cursor value can regress while an interior segment is published before a later one; the cursor is only advisory in store mode.

### CR-03: Parquet Decimal scale is data-dependent

**Files modified:** `src/data/quality.py`, `src/data/store.py`, `src/data/case_input.py`, `src/data/sufficiency.py`, `scripts/repair_parquet_scale.py` (new), `tests/test_parquet_schema_pinning.py` (new)
**Commit:** 17520c5
**Applied fix:**
- Writer: `klines_to_frame` and `mark_klines_to_frame` now pin `open/high/low/close/volume/quote_volume` (mark: the four prices) to `pl.Decimal(38, 8)` through `schema_overrides`; the empty-frame schemas use the same constant (`PRICE_DECIMAL`). The gate already rejects more than 8 fractional digits, so the cast is exact. A test asserts that a scale-0/1/2 input produces one schema and that two published files share one schema.
- Readers: new `store.read_partitions(files, columns, pin_price_scale=...)` reads each file on its own and widens every Decimal column to the largest scale seen (never narrows, so funding's scale-10 column is untouched). The case-input builder (`_read_rows`) and the flat-tail check use it, with the price scale floored at 8 for kline and mark reads, so the same number renders as the same text whichever batch wrote the file. A test shows plain `pl.read_parquet` over mixed legacy files still raises `SchemaError` and `read_partitions` and `_read_rows` do not. The case-input text for symbols whose partitions all had a scale below 8 now renders 8 fractional digits (no case-input output had been committed).
- Existing partitions were NOT repaired (see below).

**Optional repair script, not executed:** `scripts/repair_parquet_scale.py`. Default is a dry run that lists partitions whose price columns are not `Decimal(38, 8)`. `--apply --output-root NEW_ROOT` writes corrected COPIES under a new, empty root that must not be inside the input root. It never writes in place (D-04), skips any file whose cast would not round-trip exactly, and only reads `--raw-root`. A synthetic-data test covers dry run, refusal, copy and byte-identical input. Suggested use if you want it: `uv run python scripts/repair_parquet_scale.py --raw-root data/raw` to see the count, then decide whether to publish a repaired copy as a new dataset version. Until then the readers above tolerate the mixed-scale partitions.

### CR-04: Funding backfill starts at `watermark + 1`

**Files modified:** `src/data/collector.py`, `tests/test_collector.py`
**Commit:** 9d6d4e5
**Applied fix (partial):** `backfill_funding_history` now starts its walk at `start_ms` (the dataset window), not at the shared live-sweep watermark, and de-duplicates on write: an existing tick file raises `FileExistsError` and counts as covered. The watermark still only moves forward (never regresses). A full re-walk costs about three pages per symbol for 24 months of 8h funding. New test `test_funding_history_ignores_a_live_sweep_watermark_at_now` seeds a watermark at "now" plus one live-written tick and asserts the history is still fetched, the live tick is de-duplicated and the watermark is unchanged. The two existing re-run tests still pass.
**Not done (second half of the finding):** adding a funding row to the sufficiency report and to `missing_data` / exit 3. That is a report-schema and exit-code design change (new row type, thresholds for funding gaps and truncation) which I did not want to settle from the code alone. The CLI therefore still prints `complete` and exits 0 when funding fetched nothing; the failure is now only visible as `ticks=0` and gap rows. Needs a decision before the report is extended.
**Status note:** logic change, requires human verification.

### WR-01: 418 IP-ban retried like a 429

**Files modified:** `src/adapters/binance_usdm.py`, `src/data/backfill.py`, `tests/test_backfill.py`
**Commit:** 80689c0 (follow-up de7e81a removes a `float()` the adapter float-ban test rejected)
**Applied fix:** `RateLimitBanError` (418) is raised immediately, no retry, no sleep. A 429 backs off 5 s doubling with jitter to a 60 s cap and never waits less than the SDK's `Retry-After` (capped). New adapter helpers `is_rate_limit_ban_error` and `rate_limit_retry_after_seconds`; `is_rate_limit_error` is unchanged. Two tests (418 not retried, 429 honors `Retry-After` and starts above 5 s).

### WR-02: Archive-provenance sidecar clobbered by subset runs

**Files modified:** `src/data/backfill_cli.py`, `tests/test_backfill_cli.py`
**Commit:** 8c7847c
**Applied fix:** The sidecar is now saved as (persisted symbols not processed this run) union (this run's ARCHIVE symbols). `_save_archive_presets` removes the file when the resulting set is empty. New test runs two archive-sourced symbols, then a subset run, then both again, and asserts the sidecar and the report still say ARCHIVE; it fails without the fix.

### WR-03: `SYMBOL_RE.match` with `$` accepts a trailing newline

**Files modified:** `src/data/collect_list.py`, `src/data/archive.py`, `src/data/universe_freeze.py`, `src/data/backfill_cli.py`, `src/data/collector.py`, `scripts/decision_alignment/universe.py`, `tests/test_symbol_validation.py` (new)
**Commit:** 058c9af
**Applied fix:** Every `SYMBOL_RE.match(...)` is now `fullmatch(...)`, and so is the archive stamp check in `archive_zip_url` (it reaches the URL too). Pattern strings and the frozen-universe witness line are unchanged. Tests cover `"BTCUSDT\n"`, `"\r\n"`, leading newline, lowercase, space and empty on all three pattern owners, the URL builder and the collect-list validator. Other `$` patterns (`DATE_RE`, hash patterns) were left alone: they do not reach paths or URLs.

### WR-04: `universe_freeze propose` overwrites the committed evidence

**Files modified:** `src/data/universe_freeze.py`, `tests/test_universe_freeze.py`
**Commit:** 4d8cb34
**Applied fix:** `propose` refuses (exit 2, before any network call) when `--out` already exists unless `--force` is passed. The test checks the file is untouched on refusal and replaced with `--force`.

### WR-05: `src/` imports `scripts/`; collector depends on it transitively

**Files modified:** `src/data/collect_list.py`, `tests/test_collect_list.py`
**Commit:** fc03686
**Applied fix:** `universe_freeze` is imported lazily inside `reissue_collect_list` and `main` (the reviewer's alternative; moving the manifest validation into `src/` would have touched the witnessed manifest code). A subprocess test imports `src.data.collect_list` and `src.data.collector` and asserts that neither `scripts*` nor `src.data.universe_freeze` ends up in `sys.modules`; it fails without the fix.

### WR-06: Reissued collect list uses freeze-time status

**Files modified:** `src/data/collect_list.py`, `tests/test_collect_list.py`
**Commit:** be5e9a3
**Applied fix:** `reissue_collect_list` takes an optional caller-supplied current `exchange_info`; the CLI gets `--exchange-info-json` (same offline pattern as `propose`, no network call added). With it, a frozen symbol is added only if it is currently an eligible TRADING USDT perpetual and `selection_rule` names `chosen_on` as the as-of date. Without it the old behavior is kept (existing tests and the committed v2 list are unaffected) but `selection_rule` states "status was TRADING in the freeze report of <run_date> (not re-checked against the exchange)", the CLI warns on stderr and the file's source note records the basis. Not re-run against live exchangeInfo, because that needs the network.

### WR-07: `CursorStore` robustness

**Files modified:** `src/data/backfill.py`, `tests/test_backfill.py`
**Commit:** 16fb36e
**Applied fix:** `write` fsyncs the temp file before `os.replace`; the `finally` cleanup is wrapped in `contextlib.suppress(OSError)` so a locked tmp file cannot mask the original error; the paginator calls `write` through `asyncio.to_thread` so the retry sleep no longer blocks the event loop; `read` retries a transient `PermissionError` with the same bounded policy. Four tests (fsync before replace, unlink failure does not mask, read retry, write runs off the loop thread).

## Skipped Issues

None. CR-04's sufficiency/exit-code half was deliberately not attempted (described above) rather than skipped as a whole finding.

---

_Fixed: 2026-10-03T14:30:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
