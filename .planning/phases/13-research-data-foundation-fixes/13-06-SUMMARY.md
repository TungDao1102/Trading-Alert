---
phase: 13-research-data-foundation-fixes
plan: 06
subsystem: data-collector
tags: [collector, funding, pagination, watermark, atomic-write, clock-probe, binance]

requires:
  - phase: 13-research-data-foundation-fixes
    provides: "13-01 collect-list universe and cadence-aligned main loop; 13-02 atomic_write_parquet; 13-04 BinanceUsdmAdapter.server_time and null markPrice funding rows"
provides:
  - "backfill_funding_history + FundingHistoryResult: paginated, per-symbol resumable funding-history walk (pages of up to 1000, watermark advanced and committed per page, page cap with truncated_symbols report)"
  - "OI, OI-research and funding tick writers publish through store.atomic_write_parquet (F-408)"
  - "_probe_server_clock + CLOCK_OFFSET_WARN_MS: warn-only local-vs-exchange offset probe run once at collector start"
  - "constants MAX_FUNDING_PAGES = 50, FUNDING_PAGE_PACE_SECONDS = 0.2; server_time on the collector AdapterLike Protocol"
affects: [13-07, 13-08, 13-09]

actuals:
  tokens: 8027
  tasks: 3
  commits: 6
plan_head_before: 8cc2fb1ddf1b0bd4ac3a82f7cb5ab1f913070de9
plan_head_after: 30ecf5cca63e26389423c94152f88465172100a9

tech-stack:
  added: []
  patterns:
    - "Funding history is a for/else page loop: break on failure, empty or short page, no progress, or cursor past end; the else branch reports the page cap"
    - "Clock probe samples local time before and after the round trip and uses the midpoint, so half the request latency is not reported as skew"

key-files:
  created: []
  modified:
    - src/data/collector.py
    - tests/test_collector.py

key-decisions:
  - "end_ms is inclusive (Binance endTime), so the funding walk continues while cursor <= end_ms rather than stopping at cursor >= end_ms"
  - "Only non-empty pages count in FundingHistoryResult.pages; an empty page ends the symbol's walk"
  - "_probe_server_clock takes a local_now callable (default datetime.now(UTC), not the _utc_now seam) so the probe does not consume the loop tests' patched clock"
  - "An adapter that returns nothing past the cursor stops the symbol's walk with a collector.funding_history.no_progress warning instead of refetching the same page"

requirements-completed: [DATA-02]

coverage:
  - id: D1
    description: "Two years of funding history are stored per symbol through a paginated walk from max(start, watermark + 1 ms) in pages of up to 1000, each tick once, watermark advanced per page"
    requirement: DATA-02
    verification:
      - kind: unit
        ref: "tests/test_collector.py#test_funding_history_paginates_and_advances_watermark"
        status: pass
    human_judgment: false
  - id: D2
    description: "Re-running the backfill writes nothing twice (watermark cutoff and FileExistsError-as-covered)"
    requirement: DATA-02
    verification:
      - kind: unit
        ref: "tests/test_collector.py#test_funding_history_rerun_writes_nothing_twice"
        status: pass
    human_judgment: false
  - id: D3
    description: "Historical funding rows with no markPrice are stored with a null mark_price, never a fabricated zero"
    requirement: DATA-02
    verification:
      - kind: unit
        ref: "tests/test_collector.py#test_funding_history_null_mark_price_is_stored_as_null"
        status: pass
    human_judgment: false
  - id: D4
    description: "One failing symbol records a funding gap row and never stops the others; the page cap is reported, not silent"
    requirement: DATA-02
    verification:
      - kind: unit
        ref: "tests/test_collector.py#test_funding_history_isolates_failing_symbol"
        status: pass
      - kind: unit
        ref: "tests/test_collector.py#test_funding_history_page_cap_is_reported"
        status: pass
    human_judgment: false
  - id: D5
    description: "OI, OI-research and funding tick files are written atomically and still refuse to overwrite"
    requirement: DATA-02
    verification:
      - kind: unit
        ref: "tests/test_collector.py#test_tick_writers_are_atomic"
        status: pass
      - kind: unit
        ref: "tests/test_collector.py#test_tick_writer_refuses_overwrite"
        status: pass
    human_judgment: false
  - id: D6
    description: "Clock offset measured and logged at start (warning above 1000 ms, info below); probe failure logged and never blocks or changes the exit code"
    requirement: DATA-02
    verification:
      - kind: unit
        ref: "tests/test_collector.py#test_clock_probe_warns_on_large_offset"
        status: pass
      - kind: unit
        ref: "tests/test_collector.py#test_clock_probe_failure_never_blocks_start"
        status: pass
      - kind: unit
        ref: "tests/test_collector.py#test_main_once_probes_clock_once_and_probe_failure_keeps_exit_code"
        status: pass
      - kind: unit
        ref: "tests/test_collector.py#test_loop_probes_clock_once_before_first_tick"
        status: pass
    human_judgment: false
---

# Phase 13 Plan 06: Funding history, atomic ticks and clock probe Summary

**Collector gains a paginated, watermark-resumable funding-history backfill (two years per symbol, no duplicates on re-run), atomic OI/funding tick writes through the 13-02 writer, and a warn-only exchange-clock probe at start.**

## Performance

- **Duration:** about 12 min
- **Started:** 2026-09-30T14:25:00Z
- **Completed:** 2026-09-30T14:37Z
- **Tasks:** 3 (1 tracer, 2 auto/tdd)
- **Files:** 2 modified (`src/data/collector.py`, `tests/test_collector.py`)

## Accomplishments

- Tracer slice: `backfill_funding_history` walks each symbol from `max(start_ms, watermark + 1 ms)`, writes each tick once to `data_class=funding` via `_write_funding_tick`, advances and commits the watermark per page, resumes at the page's latest funding time + 1 ms, ends on a short page, and reports a symbol that hits `max_pages` in `truncated_symbols` with a `collector.funding_history.truncated` log. Verified with 2190 ticks over 3 pages (1000, 1000, 190): 2190 files, watermark on the last tick, exactly 3 adapter calls, 0 files on re-run.
- Failure posture: an adapter error records one `funding` gap row (`adapter_error: ...`) and the next symbol proceeds; a write or commit error rolls back, records a gap row and re-raises.
- F-408: the three tick writers now call `atomic_write_parquet`; a monkeypatched crash mid-write leaves no tick file and no temp file, and a second write of the same tick raises `FileExistsError` with the first file's bytes intact.
- D-25 / F-706: `_probe_server_clock` logs `collector.clock_offset` (warning above `CLOCK_OFFSET_WARN_MS = 1000`, info otherwise) or `collector.clock_probe_failed` and returns the offset or `None`; `main` runs it once after the adapter is built and before the first tick (`--once` and loop), not for `--healthcheck`.

## Facts verified

Checked 2026-09-30 with public GETs against `https://fapi.binance.com`: `GET /fapi/v1/fundingRate?symbol=BTCUSDT&startTime=1704067200000&limit=1000` returned HTTP 200 with exactly 1000 rows ascending from 2024-01-01 to 2024-11-29 (about 333 days), each row carrying `fundingTime`, `fundingRate` and `markPrice`; `limit=1001` was rejected (`illegal params`). This matches the planning-time fact (limit max 1000, about 333 days per page) that sizes `page_limit` and the `MAX_FUNDING_PAGES = 50` cap (enough for about 18 years per symbol). The 500 requests per 5 minutes per IP shared limit and the empty-markPrice rows before 2024 were taken from the planning research and 13-04 (not re-probed); the walk is sequential and paced regardless. No SDK or endpoint changes were made in this plan.

## Task Commits

1. **Task 1 (tracer): paginated funding history**
   - `bd24eeb` test(13-06): failing paginated funding-history backfill tests (RED, ImportError)
   - `478766a` feat(13-06): paginated resumable funding-history backfill (GREEN)
2. **Task 2: atomic tick writers**
   - `bce11e0` test(13-06): failing atomic tick writer crash tests (RED, 3 crash cases fail)
   - `776084a` feat(13-06): publish OI and funding tick files atomically (GREEN)
3. **Task 3: server-time probe**
   - `278d872` test(13-06): failing warn-only server-time probe tests (RED)
   - `30ecf5c` feat(13-06): warn-only server-time probe at collector start (GREEN)

Tracer feedback gate: the tracer `<verify>` (pytest of `tests/test_collector.py` plus mypy on `src/data/collector.py`) passed before Tasks 2 and 3 started; tracer verified end-to-end, expanded.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Inclusive end boundary for the funding walk**
- **Found during:** Task 1
- **Issue:** The plan says to stop when `cursor >= end_ms`. Binance `endTime` is inclusive and the cursor is `latest + 1 ms`, so `cursor == end_ms` can still leave a tick at exactly `end_ms` unread.
- **Fix:** Continue while `cursor <= end_ms` (stop when `cursor > end_ms`).
- **Files modified:** src/data/collector.py
- **Commit:** 478766a

**2. [Rule 2 - Missing critical functionality] No-progress guard in the page loop**
- **Found during:** Task 1
- **Issue:** A page whose latest funding time is not past the cursor would refetch the same page until the page cap.
- **Fix:** Stop that symbol's walk with a `collector.funding_history.no_progress` warning.
- **Files modified:** src/data/collector.py
- **Commit:** 478766a

**3. [Rule 3 - Blocking] Probe local clock argument is a callable, and does not use `_utc_now`**
- **Found during:** Task 3
- **Issue:** The plan text wrote both `local_now=fixed` and `local_now()`. The existing loop test patches `_utc_now` with a two-value iterator, so a probe defaulting to it would exhaust the iterator.
- **Fix:** `local_now: Callable[[], datetime] | None`, default `datetime.now(UTC)`; the offset uses the midpoint of a before and after sample.
- **Files modified:** src/data/collector.py, tests/test_collector.py
- **Commit:** 30ecf5c

**4. [Rule 1 - Bug] Test-only defects fixed in the Task 3 GREEN commit**
- **Issue:** The first version of `test_main_once_probes_clock_once_and_probe_failure_keeps_exit_code` reused one raw root (the fixed snapshot time then hit the D-04 no-overwrite guard) and compared the universe unsorted (the collect list is sorted).
- **Fix:** Separate raw root and database per run, compare sorted.
- **Files modified:** tests/test_collector.py
- **Commit:** 30ecf5c

Two Task 2 tests (`test_tick_writer_refuses_overwrite`) passed in RED because `_guard_no_overwrite` already provided that behavior; they are kept as regression cover, and the crash tests were the failing RED.

**Total deviations:** 4 auto-fixed (2 Rule 1, 1 Rule 2, 1 Rule 3). **Impact:** none on scope or acceptance criteria.

## Issues Encountered

- `ruff format --check src/data/collector.py` reports the file was already not format-clean before this plan (checked against the pre-plan copy); left untouched to keep the diff scoped. `ruff check` is clean.
- Full suite excluding the two known decision-alignment files (RQ-01/RQ-04, fixed by 13-11 per `deferred-items.md`) passes.

## Known Stubs

None.

## Threat Flags

None. No new endpoint, auth path or trust boundary; the `time` and `fundingRate` reads sit behind the existing adapter boundary.

## Threat Model Coverage

- T-13-24: watermark-covered skip, FileExistsError-as-covered, atomic writes; `test_funding_history_rerun_writes_nothing_twice` (0 files rewritten, mtimes unchanged).
- T-13-25: `atomic_write_parquet` in all three writers; `test_tick_writers_are_atomic` (3 cases).
- T-13-26: sequential per-symbol walk, `pace_seconds` between pages, `MAX_FUNDING_PAGES` cap, failure records a gap and never retries; `test_funding_history_page_cap_is_reported`, `test_funding_history_isolates_failing_symbol`.
- T-13-27: probe swallows exceptions and only logs; `test_clock_probe_failure_never_blocks_start`, `test_main_once_probes_clock_once_and_probe_failure_keeps_exit_code`.
- T-13-28: gap reason format unchanged (accepted).
- T-13-SC: no packages installed.

## Next Phase Readiness

Plan 13-08's backfill CLI can call `backfill_funding_history(adapter, session, symbols=..., start_ms=..., end_ms=..., raw_root=..., observed_utc=...)` and read `truncated_symbols` to re-run. Fail-closed clock checks remain Phase 18; VPS chrony remains Phase 13.1.

## Self-Check: PASSED

- FOUND: src/data/collector.py (`grep -n "def backfill_funding_history"` prints line 590 region), tests/test_collector.py
- FOUND: commits bd24eeb, 478766a, bce11e0, 776084a, 278d872, 30ecf5c
- `grep -c "atomic_write_parquet" src/data/collector.py` prints 5; `grep -n "CLOCK_OFFSET_WARN_MS"` prints the constant and its comparison.
- Plan verification: `pytest tests/test_collector.py tests/test_coverage.py tests/test_collect_list.py` passes; `mypy src/data/collector.py` prints "Success: no issues found in 1 source file"; `ruff check` clean.
