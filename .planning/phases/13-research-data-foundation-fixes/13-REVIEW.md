---
phase: 13-research-data-foundation-fixes
reviewed: 2026-10-03T13:30:00Z
depth: deep
files_reviewed: 37
files_reviewed_list:
  - scripts/decision_alignment/bookkeeping.py
  - scripts/decision_alignment/universe.py
  - src/adapters/binance_usdm.py
  - src/data/archive.py
  - src/data/backfill.py
  - src/data/backfill_cli.py
  - src/data/case_input.py
  - src/data/collect_list.py
  - src/data/collector.py
  - src/data/coverage.py
  - src/data/metadata.py
  - src/data/quality.py
  - src/data/store.py
  - src/data/sufficiency.py
  - src/data/universe_freeze.py
  - src/paper/supervisor.py
  - tests/test_adapter_strictness.py
  - tests/test_archive_ingest.py
  - tests/test_backfill.py
  - tests/test_backfill_cli.py
  - tests/test_backfill_closed_day.py
  - tests/test_backup.py
  - tests/test_case_input_builder.py
  - tests/test_collect_list.py
  - tests/test_collector.py
  - tests/test_coverage.py
  - tests/test_decision_alignment_bookkeeping.py
  - tests/test_decision_alignment_universe.py
  - tests/test_mark_klines.py
  - tests/test_metadata.py
  - tests/test_paper_resync.py
  - tests/test_paper_supervisor_backfill.py
  - tests/test_quality_gates.py
  - tests/test_store_atomic.py
  - tests/test_sufficiency.py
  - tests/test_tracer_slice.py
  - tests/test_universe_freeze.py
findings:
  critical: 4
  warning: 7
  info: 4
  total: 15
status: issues_found
---

# Phase 13: Code Review Report

**Reviewed:** 2026-10-03T13:30:00Z
**Depth:** deep
**Files Reviewed:** 37
**Status:** issues_found

## Summary

Source files were read in full. Test files were treated as evidence of coverage, not reviewed line by line. Three of the four critical findings were reproduced against the code or the real `data/raw` store, not only inferred.

- **CR-01** was reproduced with a deterministic fake adapter. `backfill_symbol_interval` never terminates when a corrupt page follows a good page on the same UTC day. `MAX_CONSECUTIVE_REJECTIONS` never trips. `StructuralRejectionError` has no test.
- **CR-02** is the resume-floor issue you flagged. It is confirmed and graded BLOCKER. The persisted cursor causes the same skip, and so does the funding watermark (CR-04).
- **CR-03** is new. The Parquet Decimal columns are not pinned to `scale=8`. The real store already holds mixed-scale partitions (DOGSUSDT, SOLUSDT). Multi-file reads in the case-input builder raise `SchemaError`.
- **CR-04** is new. `backfill_funding_history` starts at `watermark + 1`. A running collector therefore silently prevents the 2-year funding backfill. The CLI still exits 0.

The CursorStore retry from commit 413e0e6 is correct and bounded, with minor robustness notes (WR-07). The closed-day logic, the archive ingestion hardening (size caps, checksum, redirects off) and the atomic Parquet writer are otherwise sound.

## Critical Issues

### CR-01: Structural-rejection budget can be reset forever, so backfill never terminates

**File:** `src/data/backfill.py:618-623, 685-703` (reset at line 699)
**Issue:** On a corrupt page the cursor is rolled back to `last_published_open_ms + interval` (line 697). Rows of the still-buffered "latest date" are already in `seen_open_times`. The re-fetch after the rollback returns only already-seen rows. They are all de-duplicated, so `closed` is empty and `corrupt_rejection` is False. Control falls into `elif raw_page:` (line 698), which sets `consecutive_rejections = 0`. The next fetch hits the same corrupt page, the counter goes 0 to 1, and it rolls back again. The counter never exceeds `MAX_CONSECUTIVE_REJECTIONS` (5), so the documented fail-closed guard is dead in this shape.

The shape is realistic for 1m data. A page of 1000 bars is shorter than a 1440-bar day, so a good page and a corrupt page share one date, and nothing is published yet.

Reproduced with a fake adapter: good rows 0-999, then 440 rows with `high < open`. The run made more than 200 fetches and never raised. With the fix below, the same input raises `StructuralRejectionError` after 12 calls. The reproduction script is `scratchpad/loop_repro.py`.

`FakeAdapter` in `tests/test_backfill.py` returns `[]` once its scripted responses run out. This is why `test_corrupt_page_rejected...` passes. No test references `StructuralRejectionError` or `MAX_CONSECUTIVE_REJECTIONS`.

**Fix:** Reset the counter only when a page contributed new accepted rows.
```python
corrupt_rejection = False
accepted_new = False
if closed:
    verdict = dataset.validate(closed, interval)
    if not verdict.structural_ok:
        ...
    else:
        accepted_new = True
        ...
...
elif raw_page:
    if accepted_new:
        consecutive_rejections = 0
    consecutive_empty_pages = 0
    ...
```
Add a regression test in which the adapter keeps serving the same good page and then the same corrupt page, and assert that `StructuralRejectionError` is raised.

### CR-02: Store/cursor resume floor silently skips all older history (confirmed known issue)

**File:** `src/data/backfill.py:975-998` (floors), `:1007-1014` (log), `src/data/backfill_cli.py:748` (`resume_from_store=True`, always on)
**Issue:** The start of every key is floored in two ways, and both are monotone "everything before X is done" assumptions:
- `max(key_start_ms, persisted + interval)` (lines 977-980).
- `max(key_start_ms, day_after(latest_published_day))` (lines 990-998).

One stray partition or cursor value newer than the requested window start makes the run skip every older day. Missing days before the stray partition are never examined. When the floor pushes the start to or past the end, the only signal is `log.info("backfill.universe.empty_window")` (line 1008). That message is indistinguishable from "already complete". `backfill.universe.begin` also does not say that a floor overrode the requested depth start.

The sufficiency report does catch the leading hole later, as GAP or NOT_BACKFILLED with exit 3. By then the run has reported success per key, and the immutable store cannot be repaired by rerunning the same command. The `backfill_universe` docstring also contradicts itself. It promises "expand via a follow-up run with a deeper explicit window". Per line 978 and the store floor, such a run is clamped to the old cursor, so a deeper 1m extension (the D-21 user decision) is impossible via this CLI.

Grade: BLOCKER. It silently produces an incomplete research dataset in a fail-closed system.

The real store has the mirror image. SOLUSDT 1h holds stray partitions 2023-11-14 and 2023-11-15, then nothing until 2024-10-03. That hole is outside the committed report window, so it is harmless there. A stray partition inside the window would have caused the skip.

**Fix:**
- Replace the "latest day" floor with a contiguity-aware floor: the first day at or after the requested start that has no partition. Cap each segment at the next published day. If a published day exists after the requested start with a missing day before it, either fetch only the missing run, or fail with `ERROR` naming the hole. Do not skip it silently.
- Escalate the floor-induced empty window to `log.warning` and include `requested_start_ms`, `floored_start_ms` and the reason (cursor or store) so it is distinguishable from natural completion.
- Do the same for the cursor floor: only trust it if the store is contiguous from the requested start.

### CR-03: Parquet Decimal scale is data-dependent, not `scale=8`; real store has mixed-schema partitions and multi-file reads fail

**File:** `src/data/quality.py:113-131` (`klines_to_frame`), `:299-315` (`mark_klines_to_frame`); consumers `src/data/case_input.py:396-398`, `src/data/sufficiency.py:243-247`
**Issue:** `MAX_FRACTION_DIGITS` and the gate comment assume the frame stores `Decimal(scale=8)`. Only the empty-frame branch uses `pl.Decimal(scale=8)`. For real rows, `pl.DataFrame({"open": [Decimal(...)]})` infers the scale from the data, and `schema_overrides` pins only the two timestamp columns. Files published from different batches therefore carry different Decimal types. I checked the real `data/raw` store (64,074 partitions, 112 key directories):
- `interval=1h/symbol=DOGSUSDT`: 571 files at scale 7, 159 at scale 8.
- `interval=1m/symbol=DOGSUSDT` and `4h/DOGSUSDT`: mixed scales 7/8.
- `interval=1h/symbol=SOLUSDT`: volume scale 0, 1 or 2 depending on the day.

`pl.read_parquet([file_a, file_b], ...)` across two such files raises `SchemaError: data type mismatch for column open`; I reproduced it on DOGSUSDT 1h. That is exactly what `build_case_input_data` (via `_read_rows`) and `_has_flat_tail` do. The case-input builder will crash with an uncaught `polars.exceptions.SchemaError`, not a `CaseInputError`, for those symbols. DuckDB casts and hides the problem in the coverage views. Because partitions are immutable (D-04), the wrong schema is permanent unless it is repaired deliberately.

**Fix:**
- Pin the schema at write time.
```python
_DEC = pl.Decimal(38, 8)
pl.DataFrame({...}, schema_overrides={
    "open_time_utc": ..., "close_time_utc": ...,
    "open": _DEC, "high": _DEC, "low": _DEC, "close": _DEC,
    "volume": _DEC, "quote_volume": _DEC,
})
```
The same applies to `open`, `high`, `low` and `close` in the mark frame. I verified that `schema_overrides={"open": pl.Decimal(38, 8)}` works on polars 1.44. The gate already rejects more than 8 fractional digits, so the cast is exact.
- Make readers resilient: `pl.read_parquet(..., missing_columns=..., allow_missing...)` is not enough. Cast each file's Decimal columns to `Decimal(38, 8)` before concat, or read with DuckDB.
- Add a repair step (a new dataset version) for the existing mixed partitions, because D-04 forbids rewriting in place. Add a test asserting every published file has an identical schema.

### CR-04: Funding backfill starts at `watermark + 1`, so a running collector prevents the 2-year funding history

**File:** `src/data/collector.py:641-648` (and `:688-709`); caller `src/data/backfill_cli.py:864-872`; exit code `:1117`
**Issue:** `backfill_funding_history` sets `cursor = max(start_ms, wm_ms + 1)` where `wm_ms` is the shared `data_class="funding"` watermark in PostgreSQL. The live collector's `async_funding_sweep` advances that same watermark every sweep. On any deployment where the collector ran before the backfill, the watermark is at "now". The walk then starts at "now" and fetches nothing, and the 24 months of funding history that D-23 requires is never fetched. The same applies to a backfill that is later repeated with a deeper start: the watermark clamps it, exactly as in CR-02.

Nothing surfaces this. A funding failure or emptiness is a gap row or `ticks=0` log line, and `missing_data` and the exit code are computed from kline rows only (`sufficiency.py` has no funding rows). The CLI prints `complete` and exits 0. The case-input builder fails closed on funding gaps later, but after the history cannot be reconstructed cheaply.

**Fix:**
- Do not use the live-sweep watermark as the history cursor. Derive the resume point from stored funding files (contiguous from `start_ms`) the way `latest_published_day` works for klines, or keep a separate `funding_history` watermark `data_class`.
- Add a funding row to the sufficiency report (expected 8h ticks versus stored, gaps, truncation) and include it in `missing_data` and exit 3.

## Warnings

### WR-01: 418 IP-ban is retried like a 429 with a sub-10-second window

**File:** `src/data/backfill.py:389-392`
**Issue:** `is_rate_limit_error` matches both `TooManyRequestsError` (429) and `RateLimitBanError` (418). The retry is 5 attempts with `wait_exponential_jitter(initial=0.5, max=jitter_max_seconds * 4)`, so waits are about 0.5, 1, 2 and 4 seconds. Binance documents that continuing to request through a 418 extends the ban. Retrying a ban within 8 seconds is the wrong behavior and can lengthen it. `Retry-After` is not honored.
**Fix:** Do not retry `RateLimitBanError` at all: raise immediately and let the run stop (it is resumable). For 429, honor `Retry-After` and use a larger cap, for example 30-60 s.

### WR-02: Archive-provenance sidecar is clobbered by subset runs and never cleared

**File:** `src/data/backfill_cli.py:687, 839-841, 496-508`
**Issue:** `archived = _load_archive_presets(...) & set(symbols)`, and `_save_archive_presets` then rewrites the whole file from `archived` filtered to this run's symbols. A run with `--symbols BTCUSDT` (or a changed collect list) therefore deletes the `ARCHIVE` provenance of every other symbol. The next complete run takes no REST call for a complete key, because the window is empty. The report then labels archive-sourced symbols `REST`, which is the T-13-45 failure the sidecar exists to prevent. Separately, `if not symbols: return` means the file is never cleared when no symbol is archived any more.
**Fix:** Merge: load the full set, update only the symbols processed in this run, and write the union. Write on empty only if the file exists and a processed symbol was removed.

### WR-03: `SYMBOL_RE.match` with `$` accepts a trailing newline

**File:** `src/data/collect_list.py:37,99`; `src/data/archive.py:57,105`; `scripts/decision_alignment/universe.py:46,117`; `src/data/backfill_cli.py:268,306,491`; `src/data/collector.py:1133`
**Issue:** `^[A-Z0-9]+USDT$` with `re.match` matches `"BTCUSDT\n"` because `$` matches before a trailing newline. The comments say symbols must be validated because they reach paths and URLs. A TOML value or CLI argument ending in `\n` passes, then flows into `symbol=...` directories, cursor file names and archive URLs. Only `case_input.py` uses `fullmatch` correctly.
**Fix:** Use `SYMBOL_RE.fullmatch(...)` everywhere, or change the pattern to `\Z`.

### WR-04: `universe_freeze propose` silently overwrites the committed freeze evidence

**File:** `src/data/universe_freeze.py:73-75, 819-823`
**Issue:** `--out` defaults to the committed `research-universe-v1.freeze-report.json`, and `write_report` uses an atomic replace with no existence check. Re-running `propose` after the manifest is FROZEN replaces the evidence the frozen manifest and `reissue_collect_list` rely on (hash-checked via `load_report`). Compare `collect_list`, whose writers use `open("x")` and refuse to overwrite.
**Fix:** Refuse when `--out` exists unless an explicit `--force` is passed, or default to a dated path.

### WR-05: `src/` imports `scripts/` despite stated rules; the collector now depends on it transitively

**File:** `src/data/universe_freeze.py:44-51`; `src/data/collect_list.py:15-16, 34`
**Issue:** The `collect_list` docstring says "`src/` must not import from `scripts/`", and `backfill_cli` repeats the rule for its manifest reader. `universe_freeze` imports `scripts.decision_alignment.universe`, and `collect_list` now imports `universe_freeze` (for `load_report`). `src/data/collector.py` imports `collect_list`, so the collector entrypoint and its container `HEALTHCHECK` now need the `scripts` package on `sys.path`, plus `httpx` and `tenacity`. It works today only because the Dockerfile copies `scripts/` and runs from `/app`.
**Fix:** Move manifest validation and hashing (`compute_content_sha256`, `validate_manifest`, `SYMBOL_RE`) into `src/` and have `scripts/` re-export it. Alternatively import `universe_freeze` lazily inside `reissue_collect_list`.

### WR-06: Reissued collect list uses freeze-time status, not current status

**File:** `src/data/collect_list.py:264-266`
**Issue:** `reissue_collect_list` keeps symbols whose status was `TRADING` in the freeze report. The report can be arbitrarily old. A symbol delisted or settling since then is added, and the collector journals a gap row for it every 5-minute tick (the T-13-53 problem the function claims to avoid). The docstring's "still TRADING" is not true of the implementation.
**Fix:** Cross-check against a fresh `exchangeInfo` (or take the status as a required input with a date) and name the as-of date in `selection_rule`.

### WR-07: `CursorStore.write` retry (commit 413e0e6): correct but has robustness gaps

**File:** `src/data/backfill.py:311-332`
**Issue:** The bounded retry is correct and tested. Gaps:
- `time.sleep` blocks the event loop for up to 0.4 s per cursor write, from inside `async def backfill_symbol_interval`.
- `finally: tmp.unlink(missing_ok=True)` can itself raise `PermissionError` on Windows while the file is locked, which masks the original error.
- No `fsync` before `os.replace` (the parquet writer fsyncs). A power loss can leave an empty or stale cursor. `read()` maps empty text to None, which `resume_from_store` mostly masks.
- `read()` has no matching retry for a transiently locked file.

**Fix:** Wrap the unlink in `contextlib.suppress(OSError)`. Add an fsync of the temp handle. Use `asyncio.sleep` or `asyncio.to_thread` for the write on the async path.

## Info

### IN-01: Dead code and stale comments

**File:** `src/data/metadata.py:44-45` (`if TYPE_CHECKING: pass`); `src/adapters/binance_usdm.py:1459-1466, 1081-1083` (`_is_already_canceled_response` always False, with the duplicated `return result`); `:1703-1712` (`_epoch_utc` unused); `src/data/coverage.py:95` (local `import re` shadows the module import); `Dockerfile` (comment still says `collect-list-v1.toml`, default is v2).
**Fix:** Remove or correct.

### IN-02: Float millisecond conversions contradict the module's own "no float round-trip" rule

**File:** `src/data/collector.py:197-206, 961`
**Issue:** `_tick_epoch_ms` and `now_ms = int(observed_utc.timestamp() * 1000)` truncate a float, which can be 1 ms low. `_datetime_to_epoch_ms` in the same file is exact. Comparisons stay self-consistent today, but the window passed to Binance can be off by 1 ms.
**Fix:** Use `_datetime_to_epoch_ms`.

### IN-03: `PaperSupervisor.start()` can wedge after a partial subscribe failure

**File:** `src/paper/supervisor.py:167-179, 419-440`
**Issue:** If `subscribe` raises midway, `_handles` is non-empty, so the next `start()` raises "called twice" and recovery needs `stop()`. `_close_failures` is reset to 0 at the end of every call, so the logged "consecutive" count is never greater than the failures within one call.
**Fix:** Roll back appended handles on failure. Keep `_close_failures` across calls and reset it only when a full close pass succeeds.

### IN-04: Funding walk and report depth fall back to defaults when 1h is not selected

**File:** `src/data/backfill_cli.py:572, 849, 894`
**Issue:** `depth` only contains the selected intervals. With `--intervals 1m` and a DRAFT or absent manifest, `depth_of("1h")` ignores `--depth-htf-months` and uses 24. The funding walk and the report's `dataset_start` then use that default.
**Fix:** Build `depth` from all configured intervals, or pass `config.depth_months` to `depth_of`.

---

_Reviewed: 2026-10-03T13:30:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
