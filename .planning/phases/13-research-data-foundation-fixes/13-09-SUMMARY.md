---
phase: 13-research-data-foundation-fixes
plan: 09
subsystem: data-backtest-bridge
tags: [parquet, duckdb, polars, case-input, dataset-identity, gap-policy, determinism, backtest]

requires:
  - phase: 13-research-data-foundation-fixes
    provides: "13-02 closed-day publish and immutable partitions; 13-04 MarkKline dataset (dataset=mark_klines), quality INTERVAL_MS"
provides:
  - "src/data/case_input.py: build_case_input_data, CaseInputData.to_case_input, dataset_identity, SERIES_ALL, CaseInputError/CaseInputGapError/CaseInputRangeError"
  - "src/data/coverage.py: GapRange, gap_ranges_for_files (single definition of an unresolved gap), TICK_GAP_FACTOR, FUNDING_JITTER_MS"
  - "Deterministic 64-hex dataset_id that assemble() accepts as data_snapshot_id"
affects: [13-10, 13-12, 13-13, 14]

actuals:
  tokens: 12000
  tasks: 3
  commits: 5
plan_head_before: cc691ed430474ba917ba68cb411f823bb7cea54e
plan_head_after: 884d373dfec5051066cc4ee0dcbdebcdb9ffba67

tech-stack:
  added: []
  patterns:
    - "Case input is built from an explicit per-day file list (never a store-wide glob); the same file list feeds the gap check, the row reads and the dataset hash"
    - "Gap policy is fail closed: CaseInputGapError before any row is emitted; an allow_gaps entry counts only when equal to a real GapRange and is then recorded on the output"
    - "Integer epoch-millisecond arithmetic for all gap math; Decimal to plain-notation string, datetime to ISO UTC string; no float, no wall clock"

key-files:
  created:
    - src/data/case_input.py
    - tests/test_case_input_builder.py
  modified:
    - src/data/coverage.py
    - tests/test_coverage.py

key-decisions:
  - "dataset_id = sha256_hex({files: [{path: posix path relative to raw_root, sha256: file-bytes digest}] sorted by path}); a re-written dataset (Polars upgrade changing bytes) is a new dataset by design (A4)"
  - "Gap definition: interior hole when consecutive rows are more than max_step_ms apart; leading hole when the first row is later than start + (max_step_ms - step_ms) (any missing first bar for klines); trailing hole when end is more than max_step_ms after the last row"
  - "Funding tolerates 8h + 60 s between ticks; OI tolerates 2x the 5 min cadence (the collector healthcheck bound)"
  - "Hole start is the first missing expected point (previous row + step) and hole end the next observed row (or the range end), so a caller can copy GapRange values from CaseInputGapError.gaps straight into allow_gaps"
  - "Intrabar key maps to the 60 one-minute rows only when the full contiguous set is present, otherwise None; the simulator then takes its existing SL-first fallback"

patterns-established:
  - "Module purity guard by AST walk (no float call, no datetime.now/utcnow/today, no time.time, no time import) on case_input.py"

requirements-completed: [BKTS-02]

coverage:
  - id: D1
    description: "build_case_input_data reads only published Parquet partitions (trade 1h/4h/1m, mark 1m, funding, OI) for one symbol and a whole-UTC-day range and returns the simulator case-input keys with string Decimals and ISO timestamps; output runs through simulator.run"
    requirement: BKTS-02
    verification:
      - kind: unit
        ref: "tests/test_case_input_builder.py#test_builder_reads_published_partitions"
        status: pass
      - kind: unit
        ref: "tests/test_case_input_builder.py#test_bar_dicts_are_string_typed_and_keys_match_close_time"
        status: pass
      - kind: integration
        ref: "tests/test_case_input_builder.py#test_builder_output_runs_through_simulator_and_assemble"
        status: pass
      - kind: unit
        ref: "tests/test_case_input_builder.py#test_to_case_input_refuses_builder_key_collision"
        status: pass
    human_judgment: false
  - id: D2
    description: "Deterministic 64-hex dataset identity over sorted posix-relative path and file sha256; same partitions same id, any changed/removed partition changes it; assemble() accepts it as data_snapshot_id"
    requirement: BKTS-02
    verification:
      - kind: unit
        ref: "tests/test_case_input_builder.py#test_dataset_id_is_deterministic"
        status: pass
      - kind: unit
        ref: "tests/test_case_input_builder.py#test_dataset_id_changes_with_any_partition"
        status: pass
      - kind: unit
        ref: "tests/test_case_input_builder.py#test_dataset_identity_paths_are_posix_relative"
        status: pass
      - kind: unit
        ref: "tests/test_case_input_builder.py#test_dataset_identity_ignores_file_order"
        status: pass
    human_judgment: false
  - id: D3
    description: "Fail-closed gap policy: gap_ranges_for_files single definition; builder raises CaseInputGapError, never pads; allow_gaps lets exactly the listed gaps through and records them"
    requirement: BKTS-02
    verification:
      - kind: unit
        ref: "tests/test_coverage.py#test_gap_ranges_reports_interior_kline_gap"
        status: pass
      - kind: unit
        ref: "tests/test_coverage.py#test_gap_ranges_reports_leading_trailing_and_empty"
        status: pass
      - kind: unit
        ref: "tests/test_coverage.py#test_funding_jitter_is_not_a_gap_but_a_missing_tick_is"
        status: pass
      - kind: unit
        ref: "tests/test_coverage.py#test_oi_gap_bound_is_twice_the_cadence"
        status: pass
      - kind: unit
        ref: "tests/test_case_input_builder.py#test_builder_refuses_unresolved_gap"
        status: pass
      - kind: unit
        ref: "tests/test_case_input_builder.py#test_allowed_gap_is_recorded_on_output"
        status: pass
      - kind: unit
        ref: "tests/test_case_input_builder.py#test_builder_never_pads_an_empty_store"
        status: pass
    human_judgment: false
  - id: D4
    description: "No wall clock and no lookahead: as_of_day_utc input, ranges ending after that day refused, naive or non-midnight bounds refused, unsafe symbol/interval rejected before file access, no float or clock reference in the module"
    requirement: BKTS-02
    verification:
      - kind: unit
        ref: "tests/test_case_input_builder.py#test_range_after_as_of_day_is_refused"
        status: pass
      - kind: unit
        ref: "tests/test_case_input_builder.py#test_naive_or_non_midnight_start_is_refused"
        status: pass
      - kind: unit
        ref: "tests/test_case_input_builder.py#test_builder_rejects_unsafe_symbol_or_interval"
        status: pass
      - kind: unit
        ref: "tests/test_case_input_builder.py#test_case_input_module_has_no_clock_or_float"
        status: pass
    human_judgment: false
  - id: D5
    description: "The builder run against the real multi-month store the operator backfills (real partition sizes, real gaps, real exchange data)"
    requirement: BKTS-02
    verification: []
    human_judgment: true
    rationale: "Unit tests use generated three-day stores; only a run over the real backfilled store shows real gap patterns and read time. It belongs to the operator run of plan 13-13."

duration: 30min
completed: 2026-09-30
status: complete
---

# Phase 13 Plan 09: Parquet to backtest case-input builder Summary

**`build_case_input_data` turns the immutable published Parquet store (trade 1h/4h/1m, mark 1m, funding, OI) into the simulator's case-input keys for one symbol and a whole-UTC-day range, with a sha256 dataset identity over sorted posix path plus file-bytes digest that `assemble()` takes as `data_snapshot_id`, and a fail-closed gap policy built on one shared `gap_ranges_for_files` definition.**

## Performance

- **Duration:** about 30 min (start time not captured at launch; approximate)
- **Completed:** 2026-09-30T15:20Z (last task commit)
- **Tasks:** 3 (Task 1 tracer, Tasks 2 and 3 auto TDD)
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments

- `src/data/case_input.py` reads explicit per-day file lists (never a store-wide glob), returns 72 strategy bars, 18 context bars, 72 intrabar keys of 60 one-minute rows, 4320 mark bars and the funding/OI rows for a three-day store, all as string-typed dicts (plain-notation Decimals, ISO UTC times, intrabar key `SYMBOL|close_time_utc` exactly as the simulator builds it).
- The output runs through `simulator.run` and `assemble(data_snapshot_id=dataset_id)`; `to_case_input(**scenario)` refuses scenario keys that collide with builder keys.
- `coverage.gap_ranges_for_files` and frozen `GapRange` are the single definition of an unresolved gap (integer epoch-ms, DuckDB reads the explicit file list after CAST to TIMESTAMP under `TimeZone=UTC`); funding tolerates 8h + 60 s, OI 2x its 5 min cadence.
- The builder checks every requested series before emitting a row and raises `CaseInputGapError` (attribute `gaps`); `allow_gaps` entries that equal a real gap pass and land on `allowed_gaps` (and in the case-input `allowed_gaps` list); unmatched entries are ignored, never recorded. The affected intrabar key maps to `None`.
- No wall clock: `as_of_day_utc` is an argument, a range ending after its start is refused; an AST test forbids float calls, `datetime.now/utcnow/today`, `date.today`, `time.time` and any `time` import in the module.
- `src/backtest` is untouched (`git diff --stat` over the plan range is empty) and still free of Polars/DuckDB.

## Task Commits

1. **Task 1 (tracer): builder, identity, tracer through simulator + assemble** - RED `9397e3c` (test), GREEN `7b1ce85` (feat)
2. **Task 2: gap_ranges_for_files and the builder gap policy** - RED `7111253` (test), GREEN `4166c21` (feat)
3. **Task 3: determinism of builder and identity** - `884d373` (test; all five determinism tests were already green, see TDD note)

**Plan metadata:** committed separately (docs: complete plan).

## Files Created/Modified

- `src/data/case_input.py` - builder, `CaseInputData`, `dataset_identity`, gap policy, exceptions
- `src/data/coverage.py` - `GapRange`, `gap_ranges_for_files`, `TICK_GAP_FACTOR`, `FUNDING_JITTER_MS`
- `tests/test_case_input_builder.py` - 15 tests: shape, string typing, simulator/assemble integration, gap refusal/allow, range refusal, determinism, identity recipe, purity guard
- `tests/test_coverage.py` - 5 gap-range tests (interior, leading/trailing/empty, funding jitter, OI bound, complete series)

## Decisions Made

See `key-decisions` in the frontmatter. In short: identity recipe fixed at path+file-bytes sha256; gap boundaries defined once in coverage.py with hole start = previous row + step so GapRange values round-trip into `allow_gaps`; intrabar key is `None` unless the full contiguous 1m set exists.

## Deviations from Plan

None - plan executed exactly as written. Small implementation choices (documented above): the leading-hole rule `first > start + (max_step_ms - step_ms)` unifies klines (any missing first bar) and ticks (tolerance measured from the range start); `series` in the output is always ordered by `SERIES_ALL`.

**Total deviations:** 0 auto-fixed. **Impact on plan:** none.

## TDD Gate Compliance

- Task 1 and Task 2 each have a `test(13-09)` RED commit followed by a `feat(13-09)` GREEN commit.
- RED failures were `ModuleNotFoundError` / `ImportError` / `AttributeError` for the not-yet-existing module and functions (the target tests failed, the shared store fixture built fine). They are not assertion failures on planned behaviour; `gsd_run check tdd-red-evidence` was not run because the plan gives no evidence-record path, so this is flagged as an advisory rather than verified RED evidence.
- Task 2: `test_range_after_as_of_day_is_refused` and `test_naive_or_non_midnight_start_is_refused` were already green at RED because Task 1's argument validation covers them (the plan puts range refusal in Task 1's input validation).
- Task 3: all five determinism tests passed on first run (the Task 1/2 implementation already sorts by posix path, normalises separators and validates arguments before file access). The plan allows this ("confirm RED for any that fail"); there is therefore no `feat`/`refactor` commit for Task 3 and it is committed as `test(13-09)`.
- Git protocol note: HEAD was `master` (protected/default branch by name). The dispatch explicitly designates `master` as the sequential execution branch and prior 13-0x plans committed there; commits were made on it without changing any config.

## Issues Encountered

None. A heredoc-based test-file edit failed once on shell quoting and was redone with the edit tools; nothing had been applied.

## Known Stubs

None. No hardcoded empty values flow to consumers; `allowed_gaps` is empty only when no gap was acknowledged.

## Threat Flags

None. The module only reads local Parquet files under the caller-supplied raw root; symbol and intervals are validated (regex/allow-list) before any file access (T-13-37).

## Threat Mitigations Verified

| Threat | Mitigation | Test |
|--------|-----------|------|
| T-13-34 non-deterministic identity | sorted posix relative path + file sha256 via `sha256_hex` | `test_dataset_id_is_deterministic`, `..._changes_with_any_partition`, `..._paths_are_posix_relative` |
| T-13-35 silent padding | `CaseInputGapError`, allow-list recorded on output | `test_builder_refuses_unresolved_gap`, `test_allowed_gap_is_recorded_on_output`, `test_builder_never_pads_an_empty_store` |
| T-13-36 lookahead | `as_of_day_utc` argument, range refusal, AST no-clock test | `test_range_after_as_of_day_is_refused`, `test_case_input_module_has_no_clock_or_float` |
| T-13-37 path traversal | regex + interval allow-list before filesystem | `test_builder_rejects_unsafe_symbol_or_interval` |
| T-13-38 float contamination | `format(Decimal, "f")`, AST no-float test | `test_bar_dicts_are_string_typed_and_keys_match_close_time`, AST test |

## Verification Results

- `pytest tests/test_case_input_builder.py tests/test_coverage.py tests/test_backtest_experiment.py tests/test_backtest_simulator.py tests/test_domain_no_float.py` - all pass (115 tests).
- `pytest tests/test_mark_klines.py` (uses coverage.py) - pass.
- `mypy src/data/case_input.py src/data/coverage.py` - Success: no issues found in 2 source files.
- `ruff check` on the four touched files - All checks passed.
- `git diff --stat cc691ed..HEAD -- src/backtest` - empty; `grep` for `src.data|polars|duckdb` under `src/backtest` - no hits.
- `grep -n "def gap_ranges_for_files" src/data/coverage.py` - one line; used in `src/data/case_input.py`.

## Next Phase Readiness

Ready for 13-10 onward. Phase 14 can consume `mark_price_bars`, `funding` and `open_interest` keys, which the simulator currently ignores. The builder has only been exercised on generated three-day stores; a real-store run belongs to the 13-13 operator run.

## Self-Check: PASSED

- `src/data/case_input.py`, `tests/test_case_input_builder.py`, `src/data/coverage.py`, `tests/test_coverage.py` exist.
- Commits `9397e3c`, `7b1ce85`, `7111253`, `4166c21`, `884d373` exist on master; `git rev-list --count cc691ed..HEAD` = 5 (matches `actuals.commits`).
