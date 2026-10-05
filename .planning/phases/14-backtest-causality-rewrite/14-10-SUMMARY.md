---
phase: 14-backtest-causality-rewrite
plan: 10
subsystem: data
tags: [backtest, parquet, minute-source, case-input-v2, funding-cadence, constraint-history, dataset-identity, tdd, decimal]

requires:
  - phase: 14-backtest-causality-rewrite
    provides: "14-01 MinuteSource protocol, parse_minute_row, validate_minute_series; 14-05 parse_constraint_row; 14-08 case-input v2 parser and engine.simulate"
  - phase: 13-data-foundation
    provides: "published per-day 1m trade and mark partitions, funding sweep files, dataset_identity, coverage gap definition"
provides:
  - "src/data/minute_source.py: ParquetMinuteSource(raw_root, symbols, start_utc, end_utc, cache_days) with files_read(), loads, SYMBOL_RE"
  - "src/data/case_input.py: build_case_input_data(symbols=[...] or symbol=, with_minute_rows=False), CaseInputData v2 (symbols, trade_bars_1m, mark_bars_1m), infer_funding_cadence_ms, FUNDING_TOLERANCE_MS"
  - "src/data/metadata.py: read_constraint_history(session, symbols)"
affects: [14-11, 14-12, 14-13, 14-14, 14-15, 14-16]

actuals:
  tokens: 17000
  tasks: 3
  commits: 6
plan_head_before: a033c8ff0b5369a3b110eeece3cd849295889852
plan_head_after: f1ddf093f28bcfc0efcc2fb767add0e2c3173aef

tech-stack:
  added: []
  patterns:
    - "Lazy per-UTC-day Parquet source: window (start, end] opens only the day files its closes fall in, LRU of cache_days parsed days per (series, symbol), validate_minute_series on first touch, holes and unpublished days stay absent"
    - "Dataset identity input is a plain list of Paths: the builder hashes every file of the requested range, the source exposes the files it actually opened (always a subset)"
    - "src/data may import pure src/backtest constants (CASE_INPUT_SCHEMA, FUNDING_MAX_CADENCE, FUNDING_JITTER); the reverse stays forbidden and tests/test_backtest_purity.py still passes"

key-files:
  created:
    - src/data/minute_source.py
    - tests/test_minute_source.py
  modified:
    - src/data/case_input.py
    - src/data/metadata.py
    - tests/test_case_input_builder.py
    - tests/test_metadata.py

key-decisions:
  - "The builder dataset_id hashes every 1m trade and mark partition of the requested range when the 1m series are requested, whether or not rows are embedded. A lazy ParquetMinuteSource can only open files of that set (proved in the e2e test: files_read() is a subset of data.files), so the id covers every file a run reads without the builder having to know what the run will open. A run that requests series without the 1m series and still passes a minute source is outside the id; documented in the module docstring"
  - "The per-day cache is per (series, symbol) with cache_days entries, so memory is bounded by symbols x 2 x cache_days days and one series cannot evict the other's days"
  - "A day file whose rows are not all dated inside its own partition day is refused (MinuteSeriesError), in addition to the 14-01 validation; a day with no file is an empty hole and is not recorded in files_read()"
  - "Funding cadence is inferred per symbol by majority vote of the observed spacings (under 6 h votes 4 h, otherwise 8 h; tie or fewer than two observations gives 8 h). The tolerance is always FUNDING_MAX_CADENCE + FUNDING_JITTER (8 h + 60 s), equal by test to coverage.DEFAULT_FUNDING_INTERVAL_MS + FUNDING_JITTER_MS; the inferred cadence only sets the step used for the leading-hole rule and the missing count, and labels the GapRange interval ('8h' or '4h')"
  - "to_case_input exports allowed_gaps without the GapRange interval (the v2 gap shape has no interval key), omits open_interest (closed v2 schema, OI stays inert), and strips price_tick_count from mark minute rows"
  - "read_constraint_history normalizes Decimal text (no exponent, no column-scale trailing zeros) and treats a zone-less timestamp (SQLite only) as UTC"

patterns-established:
  - "tests/test_case_input_builder.build_store(symbols=...) publishes multi-symbol stores through the real writers; _scenario(symbols, **extra) builds the caller-owned v2 scenario keys"

requirements-completed: [BKTS-02]

duration: about 20 min
completed: 2026-10-05
status: complete
---

# Phase 14 Plan 10: Published Store to Engine Summary

**A lazy per-day `ParquetMinuteSource`, a multi-symbol `backtest-case/2` builder with per-symbol funding cadence gap checks (8 h or 4 h, one tolerance with the engine), and a point-in-time `read_constraint_history`, so `engine.simulate` runs on published partitions with a dataset id that covers every file read.**

## Accomplishments

- `ParquetMinuteSource` serves the `MinuteSource` protocol from `interval=1m` trade and `dataset=mark_klines` mark day partitions. A window inside day 1 opens only day-1 files; a window across midnight adds day 2 (`files_read()` is ordered by first open); `cache_days=1` re-reads files (`loads` 4 against 2) and returns identical candles. Duplicated, decreasing or out-of-partition rows raise `MinuteSeriesError` on first touch, a missing minute stays a hole (59 candles for a one-hour window with one minute removed), an unpublished day reads as empty. Symbols outside `^[A-Z0-9]+USDT$` (`../BTCUSDT`, `btcusdt`, `BTCUSDT/..`, ``) are refused before any path is built (a test patches `partition_file` to fail if called).
- Tracer: the scripted LONG (zone 99-101, limit 100.00, stop 98.00) over two published UTC days fills on the 10:01 trade minute and stops on the 10:40 mark minute through `engine.simulate(..., minute_source=ParquetMinuteSource(...))` with the real `evaluate_risk` (quantity 15.928, same as the 14-08 hand oracle). Two runs give equal outputs and equal `dataset_identity(raw_root, source.files_read())`; rewriting one opened mark partition changes the identity.
- Builder: `build_case_input_data(symbols=[ETHUSDT, BTCUSDT], ...)` yields `case_input_schema` `backtest-case/2`, symbols sorted `[BTCUSDT, ETHUSDT]`, 144 strategy and 36 context bars, funding per symbol, `data_window` equal to the requested range, `dataset_id`, `allowed_gaps`; no `intrabar_1m_map`, no `open_interest`; `parse_case_input` accepts it. `with_minute_rows=True` adds 4320 trade and 4320 mark rows per symbol-range; the default leaves them out. The single `symbol=` keyword still works.
- End-to-end: builder output plus scenario keys (`account_state`, `cost_model` with `funding_convention`, `constraint_history`, `scripted_plans`) runs through `engine.simulate` with a `ParquetMinuteSource` twice with identical output; every opened minute partition is in the case `files` set and `run_summary.dataset_id` equals `data.dataset_id`.
- Funding: a 4 h series with one missed instant (one 8 h spacing) is accepted; an 8 h series with a 20-day hole raises `CaseInputGapError` with `GapRange(series=funding, interval=8h, 2026-07-02..2026-07-22, missing=60)` unless passed back in `allow_gaps`, which then appear on the output; a 4 h series hole names interval `4h`. `FUNDING_MAX_CADENCE`/`FUNDING_JITTER` equal `DEFAULT_FUNDING_INTERVAL_MS`/`FUNDING_JITTER_MS` by unit test (pairing the constants that 14-08 documented as mirrored).
- `read_constraint_history(session, ["ETHUSDT", "BTCUSDT"])` returns four rows sorted by `(symbol, observed_at)` as plain Decimal text and ISO UTC strings; every row parses with `parse_constraint_row` and loads into `ConstraintHistory`; a symbol without rows raises `ValueError` naming it; a cursor-event test shows the symbol travels as a bound parameter, not in the statement text.

## Task Commits

1. **Task 1 (tracer)**: `d4dd031` (test, RED: module missing), `5cc55f8` (feat, GREEN: `minute_source.py`)
2. **Task 2**: `93e0aff` (test, RED: 22 failing builder tests), `e73af1e` (feat: builder v2, cadence inference)
3. **Task 3**: `ce85949` (test, RED: ImportError), `f1ddf09` (feat: `read_constraint_history`)

## Deviations from Plan

None in scope. Two interpretive choices are recorded in key-decisions (dataset id hashes the whole requested 1m range, not only opened files; the cadence only sets step and label, the tolerance is fixed).

## TDD Gate Compliance

All three tasks have a separate RED commit before GREEN. The RED states are collection or import failures for Tasks 1 and 3 (`ModuleNotFoundError: src.data.minute_source`, `ImportError: read_constraint_history`) and 22 failing tests for Task 2 (`TypeError` on the new `symbols`/`with_minute_rows` arguments, missing `infer_funding_cadence_ms`). No skeleton was committed to turn those into assertion failures. `gsd_run check tdd-red-evidence` was not run. Tasks 1 and 3 passed on the first GREEN run; Task 2 passed after one implementation pass.

## Issues Encountered

- Heredocs containing apostrophes fail in the shell tool; edit scripts were written with the Write tool and run from the scratchpad.
- Per the environment policy the whole suite was not run (`pytest -m "not docker"` crashes on Windows in the deploy tests).

## Verification (real output)

- `pytest tests/test_metadata.py tests/test_case_input_builder.py tests/test_minute_source.py tests/test_coverage.py`: all passed (82 tests).
- `pytest tests/test_minute_source.py tests/test_backtest_purity.py`: 29 passed (Task 1 verify, re-run as tracer gate: passed, expansion continued).
- `pytest tests/test_backtest_*.py tests/test_fixture_harness.py tests/test_domain_no_float.py tests/test_domain_boundary.py tests/test_store_atomic.py tests/test_quality_gates.py tests/test_analytics_purity.py`: all passed (449 tests).
- `ruff check src/data tests`: all checks passed; `ruff format --check .`: 399 files already formatted; `mypy src`: no issues in 146 source files.
- Acceptance: `CaseInputData` has no `intrabar_1m_map` field; `tests/test_case_input_builder.py` contains `src.backtest.engine` and `FUNDING_JITTER_MS`; `minute_source.py` defines `ParquetMinuteSource` and `files_read`; `tests/test_minute_source.py` calls `simulate(`; `metadata.py` defines `read_constraint_history` and uses `select(`; `tests/test_metadata.py` calls `parse_constraint_row`.
- Not run (known environment crash): `pytest -m "not docker"` from the plan `<verification>`.

## Regeneration inventory

No fixture, parameter set, hash or registry pin moved. Builder test pins that moved in `tests/test_case_input_builder.py`:

- `test_builder_reads_published_partitions`: the 72-entry `intrabar_1m_map` assertions and the default 4320 `mark_bars_1m` count are replaced; the default now has `trade_bars_1m == ()` and `mark_bars_1m == ()` and the 4320 counts move to the new `with_minute_rows=True` test.
- `test_bar_dicts_are_string_typed_and_keys_match_close_time` becomes `test_bar_dicts_are_string_typed` (the `SYMBOL|ISO_CLOSE` key check is gone with the map).
- `test_builder_output_runs_through_simulator_and_assemble` (v1 `simulator.run` + `assemble`) is replaced by the engine e2e test; `assemble()` remains covered by its own tests and by 14-15.
- `test_allowed_gap_is_recorded_on_output`: no `intrabar_1m_map[key] is None`; asserts the 60-minute hole in `trade_bars_1m` instead, and the exported gap has no `interval` key.
- `base_store` fixture now publishes BTCUSDT and ETHUSDT (BTC-only counts and dataset-id properties are unchanged).
- `_build` default is `symbols=[BTCUSDT]`; `_scenario()` returns the v2 caller-owned keys instead of the v1 fixture input.

## Known Stubs

None.

## Threat Flags

None. T-14-19 (symbol regex before path building, raw-root confinement, tested with a patched `partition_file`), T-14-20 (per-symbol cadence gaps fail closed, `allow_gaps` recorded, nothing padded) and T-14-21 (ORM select with bound parameters, missing symbol fails closed, cursor-capture test) are covered.

## Next Phase Readiness

Plan 14-11 onward can build real-data cases with `build_case_input_data(...).to_case_input(...)`, `ParquetMinuteSource` and `read_constraint_history`. A real run should pass `ParquetMinuteSource(raw_root, symbols=data.symbols, start_utc=data.start_utc, end_utc=data.end_utc)` and keep the series set that includes the 1m series so the dataset id covers the minute partitions.

## Self-Check: PASSED

`src/data/minute_source.py` and `tests/test_minute_source.py` exist; commits `d4dd031`, `5cc55f8`, `93e0aff`, `e73af1e`, `ce85949`, `f1ddf09` are in `git log`; acceptance greps and the plan verification commands (except the crashing full-suite run) re-ran green.
