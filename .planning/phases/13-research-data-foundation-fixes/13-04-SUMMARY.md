---
phase: 13-research-data-foundation-fixes
plan: 04
subsystem: data-adapter
tags: [binance, mark-price, klines, parquet, backfill, adapter, delivery-date, funding, cursor]

requires:
  - phase: 13-research-data-foundation-fixes
    provides: "13-02 closed-day paginator, atomic Parquet writer, QualityVerdict/bad-decimal checks, CursorStore"
provides:
  - "MarkKline + BinanceUsdmAdapter.mark_klines over GET /fapi/v1/markPriceKlines (price_tick_count, never trade_count/volume; D-11, D-29)"
  - "mark_klines_to_frame / check_mark_batch / publish_mark_batch into data/raw/dataset=mark_klines (same paginator, closed-day rule, validation, atomic writer)"
  - "Generic DatasetSpec with TRADE_DATASET / MARK_DATASET; dataset keyword on fetch_page_with_retry and backfill_symbol_interval; MarkKlineSource Protocol"
  - "CursorStore.dataset (mark__{symbol}_{interval}.cursor) plus a paginator guard refusing a cursor store of another dataset"
  - "SymbolFilters.delivery_date_ms, empty-markPrice funding rows parsed as None, BinanceUsdmAdapter.server_time, INVALID_SYMBOL_CODE / is_invalid_symbol_error"
affects: [13-05, 13-06, 13-07, 13-09, 14-simulator-mark-price-triggers]

actuals:
  tokens: 10992
  tasks: 3
  commits: 5
plan_head_before: 30a5654142a76dae9cac9197402feff06200378f
plan_head_after: a2ef13e5a24dc98d0a261f09a8dfe9ed555b0fb6

tech-stack:
  added: []
  patterns:
    - "DatasetSpec[S, R] (PEP 695 generics) injects fetch/validate/publish so one paginator serves several datasets with mypy-strict overloads for the default trade path"
    - "Second dataset lives under a dataset=<name> subdirectory of the raw root: invisible to the trade glob, inside the existing backup root"
    - "Cursor filename namespaced by dataset; trade name unchanged for compatibility"

key-files:
  created:
    - tests/test_mark_klines.py
    - tests/fixtures/phase13/mark_klines/mark_price_klines_sample.json
  modified:
    - src/adapters/binance_usdm.py
    - src/data/quality.py
    - src/data/store.py
    - src/data/backfill.py
    - tests/test_adapter_strictness.py
    - tests/test_backup.py

key-decisions:
  - "Mark rows carry OHLC + open/close time + price_tick_count only; the volume/quote-volume fields (always '0') are ignored by design and no volume/trade_count column exists (D-29)"
  - "Mark dataset root is data/raw/dataset=mark_klines so candles_v1 (interval=*/...) does not match it and the existing backup root covers it; no backup.py change (D-27)"
  - "Only the empty string markPrice maps to None; other malformed values still raise decimal.InvalidOperation, never fabricated as zero"
  - "BadRequestError imported from the SDK package top level (same class as binance_common.errors.BadRequestError, already exported next to TooManyRequestsError) to keep one import site"

patterns-established:
  - "Paginator dataset injection: add a new dataset by supplying a DatasetSpec, not by copying the loop"

requirements-completed: [DATA-01, DATA-03, DATA-04]

coverage:
  - id: D1
    description: "Mark-price klines fetched through the adapter as MarkKline domain values with price_tick_count and no SDK type leakage"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_mark_klines.py#test_adapter_mark_klines_calls_sdk_once_and_returns_domain_types"
        status: pass
      - kind: unit
        ref: "tests/test_mark_klines.py#test_row_maps_ohlc_times_and_price_tick_count"
        status: pass
    human_judgment: false
  - id: D2
    description: "Mark dataset published atomically to dataset=mark_klines with exactly nine columns, no volume/quote_volume/trade_count, nothing in the trade root"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_mark_klines.py#test_mark_kline_parquet_has_no_volume_or_trade_count_column"
        status: pass
      - kind: unit
        ref: "tests/test_mark_klines.py#test_mark_backfill_publishes_to_mark_root_only"
        status: pass
    human_judgment: false
  - id: D3
    description: "Mark validator rejects duplicates, OHLC/regression/negative/duration/mixed-key/bad-decimal faults and only warns on gaps"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_mark_klines.py#test_check_mark_batch_rejects_structural_faults"
        status: pass
    human_judgment: false
  - id: D4
    description: "Trade and mark cursors cannot collide and a mismatched cursor store is refused; trade view ignores the mark dataset"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_mark_klines.py#test_trade_and_mark_cursors_never_collide"
        status: pass
      - kind: unit
        ref: "tests/test_mark_klines.py#test_paginator_refuses_cursor_store_of_another_dataset"
        status: pass
      - kind: unit
        ref: "tests/test_mark_klines.py#test_candles_view_ignores_mark_dataset"
        status: pass
    human_judgment: false
  - id: D5
    description: "deliveryDate, empty-markPrice funding rows, server time and the -1121 predicate readable through the adapter"
    requirement: DATA-03
    verification:
      - kind: unit
        ref: "tests/test_adapter_strictness.py#test_exchange_info_exposes_delivery_date"
        status: pass
      - kind: unit
        ref: "tests/test_adapter_strictness.py#test_funding_row_with_empty_mark_price_parses_as_none"
        status: pass
      - kind: unit
        ref: "tests/test_adapter_strictness.py#test_server_time_returns_utc_datetime"
        status: pass
      - kind: unit
        ref: "tests/test_adapter_strictness.py#test_invalid_symbol_predicate"
        status: pass
    human_judgment: false
  - id: D6
    description: "Existing backup + restore drill covers the mark-kline subtree byte-for-byte without changing backup.py"
    requirement: DATA-04
    verification:
      - kind: unit
        ref: "tests/test_backup.py#test_backup_covers_mark_kline_subtree"
        status: pass
    human_judgment: false
---

# Phase 13 Plan 04: Mark-price klines and adapter facts Summary

**Mark-price klines ingested as a separate, validated, atomically published Parquet dataset under `data/raw/dataset=mark_klines` through a generic `DatasetSpec` paginator, plus adapter access to deliveryDate, empty-markPrice funding rows, server time and the -1121 invalid-symbol condition.**

## Performance

- **Duration:** about 20 min of executor time (Bash was unavailable for a stretch; edits continued through the Edit tool)
- **Started:** 2026-09-30T13:48Z
- **Completed:** 2026-09-30T14:09Z
- **Tasks:** 3 (1 tracer, 2 auto/tdd)
- **Files:** 8 (2 created, 6 modified)

## Accomplishments

- Tracer slice end to end: recorded markPriceKlines rows go through `_row_to_mark_kline`, `BinanceUsdmAdapter.mark_klines`, `check_mark_batch` and `publish_mark_batch` to `dataset=mark_klines/interval=<TF>/symbol=<S>/date=<D>/part.parquet`; the Parquet has exactly `open_time_utc, close_time_utc, open, high, low, close, price_tick_count, interval, symbol`.
- One paginator serves both datasets: `DatasetSpec[S, R]` carries fetch/validate/publish; `TRADE_DATASET` is the default so every 13-02 caller is unchanged (`test_backfill`, `test_backfill_closed_day`, `test_tracer_slice` all pass). mypy strict passes via overloads.
- Isolation: `CursorStore.dataset` names mark cursors `mark__{symbol}_{interval}.cursor`; the paginator raises `ValueError` before any fetch when the cursor store's dataset differs from the run's; `candles_v1` reports only trade rows when both datasets share a raw root; the unchanged backup and restore drill covers the mark subtree.
- Adapter facts for plans 13-05..13-07: `SymbolFilters.delivery_date_ms` (optional trailing field, no migration), funding `markPrice ""` maps to `None` (malformed values still raise), `server_time()`, `INVALID_SYMBOL_CODE` and `is_invalid_symbol_error`.

## Facts verified

Required by the plan's exchange-authority rule (AGENTS.md), checked 2026-09-30:

- The documentation URL `https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Mark-Price-Kline-Candlestick-Data` answers HTTP 302 to `/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data#mark-price-kline-candlestick-data`; the redirected page answers a CloudFront WAF challenge (HTTP 202, empty body) to non-browser clients, so the page body could not be read from this environment. No WebFetch tool was available either.
- Substitute evidence, all from the authoritative sources reachable here: (1) the installed SDK 17.4.0 docstring for `mark_price_kline_candlestick_data` (generated from that docs page and citing that same URL) lists `GET /fapi/v1/markPriceKlines`, weights 1 / 2 / 5 / 10 for limit [1,100) / [100,500) / [500,1000] / >1000, and params symbol, interval, startTime, endTime, limit; (2) live public GETs against `https://fapi.binance.com/fapi/v1/markPriceKlines` returned 12-field rows with volume `"0"`, quote volume `"0"`, field 8 an integer update count (60, 24), limit 1500 returned 1500 rows, limit 1501 returned `-1130`, an unknown symbol returned `{"code":-1121,"msg":"Invalid symbol."}`; (3) the `x-mbx-used-weight-1m` header increased by +2 (limit 150), +5 (600), +10 (1200) and +10 (1500) between consecutive calls, matching the documented tiers.
- No contradiction with the planning-time facts was found, so coding proceeded. The default limit (500) is documented in the plan and unverified live; the adapter always passes an explicit limit.

## Task Commits

1. **Task 1 (tracer): mark klines through adapter, validator, paginator to Parquet**
   - `a302cf1` test(13-04): failing mark-kline adapter, schema and publish tests (RED, collection ImportError)
   - `24ba12f` feat(13-04): ingest mark-price klines as a separate immutable dataset (GREEN)
2. **Task 2: adapter facts for historical data**
   - `a56f9ee` test(13-04): failing adapter tests (RED, ImportError on INVALID_SYMBOL_CODE)
   - `fc49c6a` feat(13-04): deliveryDate, empty-markPrice funding, server time, -1121 predicate (GREEN)
3. **Task 3: mark dataset isolation, cursor naming, view disjointness, backup coverage**
   - `a2ef13e` test(13-04): isolation, cursor namespacing and backup round-trip tests

The tracer feedback gate: the tracer `<verify>` (pytest of test_mark_klines, test_backfill_closed_day, test_backfill, test_tracer_slice plus mypy on the four modules) passed before Tasks 2 and 3 started.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Task 3 has no separate RED commit**
- **Found during:** Task 3
- **Issue:** The `CursorStore.dataset` field and the cursor-store mismatch guard are load-bearing for the Task 1 paginator change (the `DatasetSpec` refactor needs the guard to be safe), so they were implemented in Task 1. The Task 3 tests therefore passed on first run and no failing state existed to commit.
- **Fix:** Committed the Task 3 tests as one `test(13-04)` commit; the plan's Task 3 GREEN step was already satisfied by `24ba12f`. The tests do assert the behavior (file names, refusal before any fetch, view disjointness, backup manifest).
- **Files modified:** none beyond the plan
- **Commit:** a2ef13e

**2. [Rule 3 - Blocking] PEP 695 generics and `Any` in overload implementations**
- **Found during:** Task 1 (ruff UP046/UP047)
- **Issue:** The `Generic`/`TypeVar` form the plan implied is flagged by the repo's ruff config.
- **Fix:** Used Python 3.13 type-parameter syntax (`class DatasetSpec[S, R: _TimedRow]`, generic overloads). The implementation signature of the two overloaded functions uses `Any` internally; the public overloads are fully typed so callers see no `Any`.
- **Files modified:** src/data/backfill.py
- **Commit:** 24ba12f

**3. [Rule 3 - Blocking] `BadRequestError` import site**
- **Issue:** Plan said import from `binance_common.errors`; the SDK package re-exports the same class next to `TooManyRequestsError`, which the module already imports from there.
- **Fix:** Imported from the SDK package top level (one import site, same class).
- **Files modified:** src/adapters/binance_usdm.py
- **Commit:** fc49c6a

**Total deviations:** 3 auto-fixed (all Rule 3, none behavioral). **Impact:** none on scope or acceptance criteria.

## Issues Encountered

- The docs page was not readable from this environment (WAF challenge); see "Facts verified" for the substitute evidence.
- A transient tooling failure of the shell classifier interrupted Bash for several calls; edits were applied through the Edit tool and verified once Bash returned.
- Full-suite run: the only failures are the four known pre-existing decision-alignment RQ-01/RQ-04 failures (`test_decision_alignment.py::test_all_mode_passes_on_real_repository` and three in `test_decision_alignment_bookkeeping.py`), fixed by plan 13-11 per `deferred-items.md`. `ruff check src/adapters` reports one pre-existing I001 in `src/adapters/telegram_callbacks.py`, not touched here.

## Known Stubs

None.

## Threat Flags

None. No new network endpoint, auth path or trust boundary beyond the plan's threat model (the new `markPriceKlines` GET and `time` GET sit behind the existing adapter boundary).

## Threat Model Coverage

- T-13-13: separate `dataset=mark_klines` root outside the `candles_v1` glob; `test_candles_view_ignores_mark_dataset`.
- T-13-14: field `price_tick_count`; `test_mark_kline_parquet_has_no_volume_or_trade_count_column`.
- T-13-15: `CursorStore.dataset` plus the mismatch guard; `test_trade_and_mark_cursors_never_collide`, `test_paginator_refuses_cursor_store_of_another_dataset`.
- T-13-16: only `""` maps to `None`; `test_funding_row_with_malformed_mark_price_still_raises`.
- T-13-17: dataset kept under `data/raw`; `test_backup_covers_mark_kline_subtree` with `src/ops/backup.py` and `src/backtest/` unchanged (empty diff versus the plan base).
- T-13-SC: no packages installed.

## Next Phase Readiness

Ready for 13-05 onward. Plans that build the backfill CLI, freeze and collector can call `adapter.mark_klines`, pass `dataset=MARK_DATASET` with `CursorStore(root, dataset="mark")`, read `SymbolFilters.delivery_date_ms`, `adapter.server_time()` and `is_invalid_symbol_error`. Mark-kline bounds (start at trade onboard, end at delivery) must be applied by the caller, per 13-RESEARCH Pattern 3. The simulator is untouched; mark-price trigger use is Phase 14.

## Self-Check: PASSED

- FOUND: tests/test_mark_klines.py, tests/fixtures/phase13/mark_klines/mark_price_klines_sample.json
- FOUND: commits a302cf1, 24ba12f, a56f9ee, fc49c6a, a2ef13e
- `grep -n "dataset=mark_klines" src/data/store.py` prints the MARK_DATASET_DIR definition; `grep -n "delivery_date_ms" src/adapters/binance_usdm.py` prints the field and the exchange_info mapping.
- Verification commands: pytest (mark_klines, adapter_strictness, backup, coverage, backfill, backfill_closed_day, tracer_slice, metadata, collector) all pass; `mypy src/adapters/binance_usdm.py src/data` reports no issues; `ruff check` clean on the touched files.
