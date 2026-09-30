---
phase: 13-research-data-foundation-fixes
plan: 07
subsystem: data-backfill
tags: [binance, backfill, cli, klines, mark-price, resume, delivery-cap, symbol-metadata, parquet]

requires:
  - phase: 13-research-data-foundation-fixes
    provides: "13-01 collect list; 13-02 closed-day paginator, CursorStore; 13-04 MarkKline dataset, DatasetSpec, SymbolFilters.delivery_date_ms"
provides:
  - "python -m src.data.backfill_cli: metadata first, per-symbol windows, trade and mark backfill at the decided depth, resumable, dry-run"
  - "backfill_universe keywords interval_start_ms, start_floor_ms, end_cap_ms, dataset, resume_from_store (defaults unchanged); DEPTH_MONTHS_DEFAULT, months_before, latest_published_day, DatasetSpec.root_subdir"
  - "METADATA_TEXT_MAX_LEN width guard (MetadataWidthError) in refresh_symbol_metadata"
affects: [13-08, 13-09, 13-12, 13-13]

actuals:
  tokens: 19300
  tasks: 3
  commits: 5
plan_head_before: 8d13d767a89faf14a4a1ec17d01d894e066e95bf
plan_head_after: ce57e3c6aa500e9290d807d2e1014cd5b8536017

tech-stack:
  added: []
  patterns:
    - "One explicit window per (dataset, symbol, interval): start = max(depth start, onboard), end = min(run day floor, deliveryDate) as a terminal end for non-TRADING contracts"
    - "Resume = per-dataset CursorStore plus a store floor at the day after the latest published partition"
    - "Symbols with no establishable window get a cause and no fetch (fail closed), never a guess up to now"

key-files:
  created:
    - src/data/backfill_cli.py
    - tests/test_backfill_cli.py
  modified:
    - src/data/backfill.py
    - src/data/metadata.py
    - tests/test_metadata.py

key-decisions:
  - "Windows are keyed per (dataset, symbol, interval) but backfill_universe takes per-interval starts and per-symbol floors/caps, so the CLI calls it once per (dataset, interval) with the window start as the symbol floor and the window end as the symbol cap"
  - "A symbol missing from exchangeInfo, or non-TRADING with no deliveryDate, gets cause DELIVERY_UNKNOWN and no window; the archive fallback (13-08) is the only way to bound it"
  - "When a symbol is both onboard-limited and delivery-capped the reported cause is DELISTED_CAPPED (the end bound is the one that changes what is published)"
  - "The default --cursor-root follows --raw-root (<raw-root>/_cursors), which is data/raw/_cursors by default"
  - "The default manifest path is a local relative constant (src/ must not import scripts/); a missing or invalid manifest is a config error (exit 2), never silently ignored, because a FROZEN manifest changes the 1h/4h start"

patterns-established:
  - "Failure output prints exception type names only; MetadataWidthError and BackfillConfigError messages are the sole exceptions and carry symbol/field/flag names, never values"

requirements-completed: [DATA-01, DATA-03]

coverage:
  - id: D1
    description: "CLI refreshes versioned metadata first, then backfills trade klines at the decided depth into closed-day Parquet and prints the depth and run date"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_cli_refreshes_metadata_before_backfill"
        status: pass
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_cli_prints_depth_in_run_header"
        status: pass
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_unknown_dataset_or_interval_exits_2_without_adapter_call"
        status: pass
    human_judgment: false
  - id: D2
    description: "Per-symbol windows: onboard floor, delivery terminal cap (no post-delivery bars), unknown-delivery and not-listed symbols get no window, mark windows equal trade windows"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_delivered_symbol_never_publishes_post_delivery_bars"
        status: pass
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_onboard_limited_window_starts_at_onboard_time"
        status: pass
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_mark_windows_match_trade_windows"
        status: pass
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_symbols_without_window_are_listed_and_never_fetched"
        status: pass
    human_judgment: false
  - id: D3
    description: "FROZEN manifest sets the 1h/4h start and joins the universe; DRAFT contributes nothing; explicit symbols replace the union"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_frozen_manifest_sets_htf_start"
        status: pass
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_draft_manifest_contributes_no_symbols_and_no_start"
        status: pass
    human_judgment: false
  - id: D4
    description: "Interrupted run resumes from the dataset cursor and, with cursors deleted, from the store floor; no day is published twice"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_resume_after_kill_uses_cursor_and_store_floor"
        status: pass
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_dry_run_fetches_nothing"
        status: pass
    human_judgment: false
  - id: D5
    description: "Versioned metadata rows for delisted and non-TRADING universe symbols; overlong contract_type/status raises instead of truncating; universe always passed; missing symbols reported"
    requirement: DATA-03
    verification:
      - kind: unit
        ref: "tests/test_metadata.py#test_refresh_inserts_rows_for_settling_and_pending_symbols"
        status: pass
      - kind: unit
        ref: "tests/test_metadata.py#test_overlong_metadata_text_raises_not_truncates"
        status: pass
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_cli_always_passes_universe_to_metadata"
        status: pass
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_missing_symbols_are_reported"
        status: pass
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_failure_prints_type_name_never_the_database_url"
        status: pass
    human_judgment: false
  - id: D6
    description: "The real backfill against Binance over 12/24 months for the research universe (weight budget, wall-clock, real exchangeInfo statuses)"
    requirement: DATA-01
    verification: []
    human_judgment: true
    rationale: "Only a real run shows the actual weight consumption, duration and exchangeInfo statuses; unit tests use a fake adapter. It is the operator run of plan 13-13."
---

# Phase 13 Plan 07: History-depth backfill CLI Summary

**`python -m src.data.backfill_cli` writes versioned symbol metadata first, then backfills trade and mark klines at 12 months of 1m and 24 months of 1h/4h over each symbol's real trading life (onboard floor, delivery terminal cap), resumably, with a fail-closed metadata width guard.**

## Performance

- **Duration:** about 20 min
- **Started:** 2026-09-30T14:41Z
- **Completed:** 2026-09-30T15:01Z
- **Tasks:** 3 (1 tracer, 2 auto/tdd)
- **Files:** 5 (2 created, 3 modified)

## Accomplishments

- Tracer slice end to end: exchangeInfo, a `symbol_metadata` row, a 730-day 1h window `[2024-09-30, 2026-09-30)` with cause `FULL_DEPTH`, and day files published under `interval=1h/symbol=BTCUSDT/`, none for the current day. The run header prints `run_date`, `depth 1m=12 months, 1h=24 months, ...`, datasets, universe size and pace.
- `backfill_universe` gained `interval_start_ms`, `start_floor_ms`, `end_cap_ms`, `dataset` and `resume_from_store`; with them omitted its behavior and results are identical (a key whose start is at or beyond its end now returns an empty result instead of making a zero-page call; the result values are the same). Existing callers and `test_backfill`, `test_backfill_closed_day`, `test_mark_klines` pass unchanged.
- Window rules (`plan_windows`): start = `max(depth start, onboard)`; a non-TRADING contract with a `deliveryDate` below the run end ends there as a terminal window (the partly covered delivery day is published, no later day is); non-TRADING with no `deliveryDate`, or absent from exchangeInfo, gets `DELIVERY_UNKNOWN` and no window; onboarding after the run end is `NOT_LISTED_IN_RANGE`; the far-future sentinel on a TRADING contract is never a cap. Mark windows are copied from the trade windows.
- Universe and frozen manifest: default = collect list union a FROZEN manifest's symbols; a FROZEN manifest's `selection_date` is the 1h/4h start for every symbol (1m still counts back from the run date); a DRAFT manifest contributes nothing; `--symbols` replaces the union but keeps the frozen start.
- Resume: per-dataset `CursorStore` plus a store floor at the day after the latest published partition. Kill on page 2, re-run, delete cursors, re-run: each day exists exactly once, first-run files are byte-identical, and the third run makes no klines request.
- Metadata: universe symbols in SETTLING or PENDING_TRADING are inserted as ordinary versioned rows; `refresh_symbol_metadata` raises `MetadataWidthError` (a `ValueError` naming symbol and field) for a universe row whose `contract_type` or `status` exceeds 16 characters, before any `session.add`, after a rollback. The CLI always passes `universe=set(resolved symbols)` and lists symbols missing from exchangeInfo.

## Task Commits

1. **Task 1 (tracer): backfill CLI from exchangeInfo to metadata to a published 1h day file**
   - `7b3f09e` test(13-07): failing backfill CLI tracer tests (RED, ModuleNotFoundError/ImportError on the missing module)
   - `0eaa887` feat(13-07): history-depth backfill CLI with metadata first (GREEN)
2. **Task 2: per-symbol windows, delivery cap, frozen start, resume, dry-run**
   - `1a9d951` test(13-07): per-symbol windows, delivery cap, frozen start, resume, dry-run (tests only, see Deviations)
3. **Task 3: metadata for delisted/non-TRADING symbols, universe always applied, width guard**
   - `caf144b` test(13-07): failing metadata width guard, universe and missing-symbol tests (RED: `DID NOT RAISE ValueError` on both parametrizations)
   - `ce57e3c` feat(13-07): fail-closed metadata width guard and CLI universe wiring (GREEN)

Tracer feedback gate: the tracer `<verify>` (pytest of test_backfill_cli, test_backfill, test_backfill_closed_day, test_mark_klines; mypy on `backfill_cli.py` and `backfill.py`; `--help` lists `--depth-1m-months` and `--datasets`) passed end to end before Tasks 2 and 3 started.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Task 2 has no separate RED commit**
- **Found during:** Task 2
- **Issue:** The window planner, universe resolver, resume floor and dry-run are load-bearing for the Task 1 tracer (the 1h window start and the closed-day files depend on them), so they were implemented in Task 1 and the Task 2 tests passed on first run. No failing state existed to commit.
- **Fix:** Committed the Task 2 tests as one `test(13-07)` commit. To show they are not vacuous, the delivery cap and the store floor were disabled temporarily (mutation check): `test_delivered_symbol_never_publishes_post_delivery_bars` and `test_resume_after_kill_uses_cursor_and_store_floor` failed, and both mutations were reverted before committing. A first run also exposed an off-by-one in the test's own day count (62 days, not 61), corrected in the test.
- **Files modified:** none beyond the plan
- **Commit:** 1a9d951

**2. [Rule 2 - Missing critical functionality] `MetadataWidthError` subclass and a URL-leak test**
- **Found during:** Task 3
- **Issue:** The plan asks for a `ValueError` naming symbol and field, and for the CLI to print exception type names only. Printing only `ValueError` would hide which symbol and field overflowed, and the "no URL in output" mitigation (T-13-31) had no test.
- **Fix:** The guard raises `MetadataWidthError(ValueError)` (still a `ValueError`); the CLI prints its message (symbol, field, length, no values) and exits 1, and prints only type names for every other failure. Added `test_failure_prints_type_name_never_the_database_url`.
- **Files modified:** src/data/metadata.py, src/data/backfill_cli.py, tests/test_backfill_cli.py
- **Commit:** ce57e3c

**3. [Rule 3 - Blocking] A live-connection URL-leak test hung, replaced**
- **Found during:** Task 3
- **Issue:** A first version of the leak test connected to `127.0.0.1:1`, which did not fail fast on this Windows host (the run exceeded 120 s before finishing).
- **Fix:** Replaced it with a deterministic test that monkeypatches `refresh_symbol_metadata` to raise an error embedding the URL and asserts the output holds only the type name.
- **Commit:** ce57e3c

**Total deviations:** 3 auto-fixed (1 Rule 2, 2 Rule 3, none behavioral versus the plan's acceptance criteria). **Impact:** none on scope.

## Issues Encountered

- Known pre-existing failures (decision-alignment RQ-01/RQ-04, plan 13-11 scope) and the pre-existing `src/paper/supervisor.py` mypy chain error listed in `deferred-items.md` were not touched. The full suite was run with the decision-alignment test modules deselected (see Self-Check).
- Hazard for plan 13-13 (not a defect in this plan): `resume_from_store` floors the start at the day after the LATEST published partition, as the plan specifies. If `data/raw` already holds a short recent bootstrap (for example the earlier 30-day live-5 backfill) for a symbol, that symbol's 24-month history before the earliest stored day would be skipped silently. Run against an empty raw root, or inspect `interval=*/symbol=*/date=*` first; the 13-08 sufficiency report will show such a hole as missing bars.
- A window whose start falls mid-day (onboard time) publishes that first day as a partial day (bars from the onboard instant), which is the contract's whole life for that day and is intended.

## Known Stubs

None.

## Threat Flags

None. No new network endpoint or trust boundary beyond the plan's threat model.

## Threat Model Coverage

- T-13-29: terminal cap at `deliveryDate`; `DELIVERY_UNKNOWN` gets no window; `test_delivered_symbol_never_publishes_post_delivery_bars`, `test_symbols_without_window_are_listed_and_never_fetched`.
- T-13-30: universe always passed (`test_cli_always_passes_universe_to_metadata`); width guard raises and rolls back (`test_overlong_metadata_text_raises_not_truncates`).
- T-13-31: type-name-only failure output (`test_failure_prints_type_name_never_the_database_url`); `--database-url` is read once by the engine factory and never printed.
- T-13-32: symbols and intervals run sequentially, page size 1000 (weight 5), default `--pace-seconds 0.25`, existing bounded tenacity retry. Real weight consumption is measured only in the plan 13-13 run.
- T-13-33: per-dataset `CursorStore` plus `latest_published_day` store floor; `test_resume_after_kill_uses_cursor_and_store_floor`.
- T-13-SC: no packages installed.

## Next Phase Readiness

Plan 13-08 adds the archive fallback, funding history and the data-sufficiency report to the same CLI: `SymbolWindow` causes and `BackfillRunReport.missing_from_exchange_info` are the hooks (symbols with no REST window are exactly the archive-fallback candidates). Plan 13-12 freezes the manifest and 13-13 runs the operator backfill; both must pass explicit `--manifest`/`--collect-list` paths only where tests are concerned (the tests here always do).

## Self-Check: PASSED

- FOUND: src/data/backfill_cli.py, tests/test_backfill_cli.py, `grep -n "METADATA_TEXT_MAX_LEN" src/data/metadata.py` prints the constant (line 47) and the comparison (line 95).
- FOUND: commits 7b3f09e, 0eaa887, 1a9d951, caf144b, ce57e3c (`git rev-list --count 8d13d76..HEAD` = 5).
- Full suite (decision-alignment modules deselected, plan 13-11 scope): 2234 passed, 7 skipped, 65 deselected.
- Verification: `pytest tests/test_backfill_cli.py tests/test_metadata.py tests/test_backfill.py tests/test_backfill_closed_day.py tests/test_mark_klines.py tests/test_collector.py tests/test_tracer_slice.py` all pass; `mypy src/data` reports no issues; `ruff check` clean on the touched files; `python -m src.data.backfill_cli --help` lists `--depth-1m-months`, `--depth-htf-months`, `--datasets`, `--dry-run`.
