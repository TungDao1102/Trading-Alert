---
phase: 13-research-data-foundation-fixes
plan: 08
subsystem: data-backfill
tags: [binance, backfill, cli, data-sufficiency, archive-fallback, funding-history, d043, protocol-split, parquet]
status: complete

requires:
  - phase: 13-research-data-foundation-fixes
    provides: "13-05 archive ingest (ArchiveKlineSource, archive_last_day); 13-06 backfill_funding_history; 13-07 backfill CLI and SymbolWindow; 13-09 gap_ranges_for_files (single gap definition)"
provides:
  - "src/data/sufficiency.py: SufficiencyRow/SplitCoverage/SufficiencyReport, build_sufficiency_report, split_boundaries, expected_bar_count, render_report_table, write_report_json, validate_report_file, MISSING_DATA_CAUSES, TRADE_FLOOR_NOTE, DEPTH_EXTENSION_NOTE, python -m src.data.sufficiency validate"
  - "backfill_cli: prints the sufficiency table after every backfill, --report-out, exit codes 0/1/2/3, per-symbol archive fallback, --funding/--no-funding"
  - "BackfillRunReport.sufficiency / .sources / .funding; run_backfill(archive_client=...) injection seam; _sources.json provenance sidecar next to the cursors"
affects: [13-12, 13-13, 14]

actuals:
  tokens: 20800
  tasks: 3
  commits: 6
plan_head_before: 2d9dd6051fba42a525d2d9d993dfa9fda7b2962e
plan_head_after: 1d9e4ced115c99920206234be2a654bc269ecc3c

tech-stack:
  added: []
  patterns:
    - "Report causes are derived from the planned window, the stored day files and the SAME gap definition the case-input builder refuses on; exit 3 only for NOT_BACKFILLED, GAP, UNAVAILABLE"
    - "Source is decided per (dataset, symbol): REST first, archive only after a REST -1121 or for a symbol exchangeInfo no longer lists; mark is REST-only, UNAVAILABLE otherwise"
    - "Canonical report JSON: sorted keys, LF, UTF-8, tmp + os.replace, byte-identical on an identical re-run"

key-files:
  created:
    - src/data/sufficiency.py
    - tests/test_sufficiency.py
  modified:
    - src/data/backfill_cli.py
    - tests/test_backfill_cli.py

key-decisions:
  - "The report checks data depth only: TRADE_FLOOR_NOTE states the D043 floor (100 pooled closed trades over the four Validation folds, 30 per fold) cannot be measured until the Phase 14 causal simulator exists; no trade count is estimated, no exit code depends on trades, RESEARCH_PROTOCOL.md is untouched"
  - "Cause precedence: NOT_LISTED_IN_RANGE -> NO_WINDOW; DELIVERY_UNKNOWN or UNAVAILABLE source -> UNAVAILABLE; nothing expected -> informational; no stored bar -> NOT_BACKFILLED; gap -> GAP; else ONBOARD_LIMITED / DELISTED_CAPPED / OK"
  - "Mid-day (onboard) window starts are aligned up to the next bar boundary before the gap check, so a listing at 07:30 is not a leading gap"
  - "Split blocks are cut on the 1h/4h dataset timeline (start + span * percent // 100, integer ms); expected_1m is the whole block so pre-1m-start blocks show 0.00%; the D-21 archive-extension note prints only when a block lies entirely before a non-onboard-limited symbol's 1m start and holds no 1m bar"
  - "Source discovery is lazy, per symbol (try REST, catch -1121) instead of an up-front probe, so no extra klines request is made and 13-07 resume behavior is unchanged; provenance is persisted in _sources.json so a complete re-run still reports ARCHIVE"
  - "An archive-capped window (end = last archive day) is trimmed for the report to the last archived bar, because a delisted symbol's last archive day holds bars only up to delivery"

patterns-established:
  - "Tests reach the archive only through an injected httpx.AsyncClient over MockTransport (FakeArchive); CLI-level tests patch backfill_cli.make_archive_client"

requirements-completed: [DATA-01, DATA-02]

coverage:
  - id: D1
    description: "After a backfill the CLI prints a per-(dataset, symbol, interval) sufficiency table with expected, stored, missing bars and a cause, writes it canonically with --report-out, and exits 3 only for NOT_BACKFILLED, GAP or UNAVAILABLE"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_cli_exit_code_is_3_only_for_missing_data"
        status: pass
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_report_json_is_deterministic"
        status: pass
      - kind: unit
        ref: "tests/test_sufficiency.py#test_missing_day_is_a_gap_with_the_builders_gap_definition"
        status: pass
      - kind: unit
        ref: "tests/test_sufficiency.py#test_unbounded_causes_map_to_no_window_and_unavailable"
        status: pass
    human_judgment: false
  - id: D2
    description: "The report states the D043 trade floor is unmeasurable until the Phase 14 simulator, estimates no trade count and never edits the protocol"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_report_states_trade_floor_is_unmeasurable"
        status: pass
      - kind: unit
        ref: "tests/test_sufficiency.py#test_render_table_carries_rows_and_the_trade_floor_note"
        status: pass
      - kind: command
        ref: "git diff 2d9dd60..HEAD --name-only -- docs/research/RESEARCH_PROTOCOL.md (empty)"
        status: pass
    human_judgment: false
  - id: D3
    description: "1m coverage per protocol split block (40% Development, four 10% folds, 20% holdout) on the 1h/4h timeline with Decimal percentages, plus the D-21 archive-extension note and the flat-tail warning"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_sufficiency.py#test_split_boundaries_follow_protocol_40_40_20"
        status: pass
      - kind: unit
        ref: "tests/test_sufficiency.py#test_split_coverage_shows_missing_1m_in_development"
        status: pass
      - kind: unit
        ref: "tests/test_sufficiency.py#test_flat_tail_is_warned_not_failed"
        status: pass
      - kind: unit
        ref: "tests/test_sufficiency.py#test_validate_subcommand"
        status: pass
    human_judgment: false
  - id: D4
    description: "Symbols REST no longer serves (-1121) or exchangeInfo no longer lists are backfilled from the checksum-verified archive, capped at delivery or the last archive day, source recorded per symbol and dataset; a symbol no source serves is UNAVAILABLE; mark is REST-only"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_invalid_symbol_uses_archive_source"
        status: pass
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_archive_only_symbol_capped_at_last_archive_day"
        status: pass
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_unavailable_symbol_exits_3"
        status: pass
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_mark_for_archive_symbol_comes_from_rest_or_is_unavailable"
        status: pass
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_archive_source_survives_a_complete_rerun"
        status: pass
    human_judgment: false
  - id: D5
    description: "Funding history is backfilled per universe symbol over the 1h/4h dataset range, ending at the delivery cap; a funding failure is a gap row, not a crash; --no-funding skips it"
    requirement: DATA-02
    verification:
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_funding_step_runs_per_symbol_within_bounds"
        status: pass
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_funding_failure_is_a_gap_row_not_a_crash"
        status: pass
      - kind: unit
        ref: "tests/test_backfill_cli.py#test_no_funding_flag_skips_the_step"
        status: pass
    human_judgment: false
  - id: D6
    description: "The real backfill against Binance and data.binance.vision over the research universe (real -1121 behavior, real archive last days, weight and wall-clock cost, real sufficiency numbers against the D043 floor)"
    requirement: DATA-01
    verification: []
    human_judgment: true
    rationale: "Unit tests use a fake REST adapter and a mocked archive. Only the operator run of plan 13-13 shows the real exchange behavior and the real depth numbers the user decides the 12-versus-24-month 1m question on."
---

# Phase 13 Plan 08: Data-sufficiency report, archive fallback and funding step Summary

**`python -m src.data.backfill_cli` now ends every backfill with a per-(dataset, symbol, interval) data-sufficiency report (expected vs stored bars, cause, per-protocol-split 1m coverage) and exits 3 only for missing data; symbols REST rejects or exchangeInfo no longer lists are filled from the checksum-verified archive, and funding history is collected per symbol.**

## Performance

- **Duration:** about 35 min
- **Started:** 2026-09-30T15:50Z
- **Completed:** 2026-09-30T16:25Z
- **Tasks:** 3 (1 tracer, 2 auto/tdd)
- **Files:** 4 (2 created, 2 modified)

## Accomplishments

- **Sufficiency report (tracer).** `build_sufficiency_report` computes, per window, the expected bars (bar opens on the step grid inside `[start, end)`), the stored bars (Polars row count over the window's day files, trade root or `dataset=mark_klines`), the gaps (`coverage.gap_ranges_for_files`, the definition the case-input builder fails closed on) and a cause: `OK`, `ONBOARD_LIMITED`, `DELISTED_CAPPED`, `NO_WINDOW`, `NOT_BACKFILLED`, `GAP`, `UNAVAILABLE`. The CLI prints the table, writes canonical JSON with `--report-out` (sorted keys, LF, tmp + `os.replace`; a second identical run is byte-identical) and exits 3 only for `NOT_BACKFILLED`, `GAP`, `UNAVAILABLE`. `--dry-run` produces no report and exits 0.
- **D043 honesty.** The report prints `TRADE_FLOOR_NOTE` (at least 100 closed trades pooled across the four Validation folds and 30 per fold cannot be measured until the Phase 14 causal simulator exists; this report checks depth only and never changes the floor). No trade estimate is emitted, no exit code depends on trades, and `docs/research/RESEARCH_PROTOCOL.md` has an empty diff for the plan.
- **Per-split 1m coverage (D-21).** `split_boundaries` cuts the 1h/4h timeline at `start + span * p // 100` for p in 0, 40, 50, 60, 70, 80, 100 (integer ms; literal instants for the 2024-09-30 to 2026-09-30 span are asserted: 2025-07-19, 2025-09-30, 2025-12-12, 2026-02-23, 2026-05-07). Each symbol gets expected, stored and a two-decimal Decimal percent per block; the archive-extension note prints only when depth left a block empty. A trade row whose last three stored days are flat zero-trade bars gets a WARNING line and `flat_tail`, never a failure.
- **`validate` subcommand.** `python -m src.data.sufficiency validate P` exits 0 for a valid report, 1 with the problems on stderr (wrong schema, missing rows/keys, unknown cause, arithmetic or `missing_data` inconsistency, altered floor note), 2 without a subcommand.
- **Archive fallback (D-08).** A REST `-1121` on a trade window, or a symbol absent from exchangeInfo, routes that symbol to `ArchiveKlineSource` through the same paginator, quality gate, closed-day rule and atomic publisher, capped at its delivery date or its last archive day (`archive_last_day`). The source is printed per symbol and dataset, listed in the table SOURCE column and persisted (`_sources.json`). A symbol no source serves is `UNAVAILABLE`. Mark klines only come from REST; a REST `-1121` on mark makes the mark row `UNAVAILABLE` and no mark file is ever built from trade data.
- **Funding (D-23).** After the kline datasets, `backfill_funding_history` runs once per symbol with a window, from the 1h/4h dataset start to `min(run end, delivery cap)`; `--no-funding` skips it; an adapter failure is a `collector_gaps` row and the run still reports.

## Task Commits

1. **Task 1 (tracer): backfill to sufficiency rows, table, JSON and exit 3**
   - `2092da1` test(13-08): failing sufficiency and exit-code tests (RED: `ModuleNotFoundError` on the missing module; CLI cases fail on the unknown `--report-out`)
   - `4360c5b` feat(13-08): data-sufficiency report with missing-data exit code (GREEN)
2. **Task 2: per-split 1m coverage, flat-tail warning, validate**
   - `dfbe0d9` test(13-08): failing tests for split coverage, flat tail and validate (RED)
   - `16482c3` feat(13-08): per-split 1m coverage, flat-tail warning and validate subcommand (GREEN)
3. **Task 3: archive fallback per symbol and the funding step**
   - `352daeb` test(13-08): failing tests for archive fallback and the funding step (RED)
   - `1d9e4ce` feat(13-08): archive fallback per symbol and funding history in the backfill CLI (GREEN)

Tracer feedback gate: the tracer `<verify>` (pytest of `test_sufficiency` and `test_backfill_cli`; mypy on `sufficiency.py` and `backfill_cli.py`) passed end to end before Tasks 2 and 3 started. Tracer verified end-to-end, then expanded.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Lazy per-symbol `-1121` discovery instead of an up-front REST probe**
- **Found during:** Task 3 design
- **Issue:** The plan resolves a source per symbol with a klines `limit 1` probe before backfilling. That extra request breaks three 13-07 guarantees that already have tests: the kill-on-the-second-klines-call test (the probe would consume call 1 and the kill would hit page 1), "a complete store makes no klines request", and "a resumed run only requests days after the stored ones". It also spends weight for nothing.
- **Fix:** Each symbol is bootstrapped through REST directly; a `BadRequestError -1121` (via `is_invalid_symbol_error`) on that symbol reroutes only it to the archive, every other error still propagates (fail closed). Because a complete re-run never asks REST, the archive provenance is persisted in `<cursor-root>/_sources.json` (only `trade|SYMBOL: ARCHIVE` entries; an unreadable file means "ask REST again"). Behavior is equivalent to the probe; `backfill_universe` is therefore called per symbol and the per-symbol results are merged into the same `(dataset, interval)` result.
- **Files modified:** src/data/backfill_cli.py
- **Commit:** 1d9e4ce

**2. [Rule 1 - Bug] Archive-capped windows would report a false trailing GAP**
- **Found during:** Task 3 design (test `test_archive_only_symbol_capped_at_last_archive_day`)
- **Issue:** An archive-only symbol is capped at the END of its last archive day, but a delisted contract's last day holds bars only up to delivery. Expecting the whole day would report a trailing hole for every such symbol and exit 3 forever.
- **Fix:** After the backfill, a window whose end was set by the archive cap is trimmed (trade and mark windows of that symbol and interval) to the last stored bar plus one step. Missing whole days and any hole before the last bar are still flagged; only the unknowable tail of the final day is not.
- **Files modified:** src/data/backfill_cli.py
- **Commit:** 1d9e4ce

**3. [Rule 3 - Blocking] 13-07 test scaffolding updated for the new behavior**
- **Found during:** Task 3
- **Issue:** `test_missing_symbols_are_reported` has a symbol absent from exchangeInfo, which now consults the archive (a real network call without an injected client). The 13-07 `FakeAdapter` had no `funding_rate`.
- **Fix:** That test passes an empty mocked archive (`archive_client=FakeArchive({}).client()`); `FakeAdapter` gained `skip_days_ms`, `invalid_symbols`, `invalid_mark_symbols`, `funding_fail_symbols` and `funding_rate`; the `_config` helper defaults `funding=False` so the 13-07 tests keep their original meaning. No 13-07 assertion was changed.
- **Files modified:** tests/test_backfill_cli.py
- **Commit:** 352daeb

**4. [Rule 2 - Missing critical functionality] Provenance sidecar (T-13-45)**
- **Found during:** Task 3
- **Issue:** T-13-45 requires the source recorded per symbol and dataset; without persistence a complete re-run would silently report `REST` for an archive-filled symbol.
- **Fix:** `_sources.json` in the cursor root (atomic write, only when something is archive-sourced, so dry runs and REST-only runs create nothing); `test_archive_source_survives_a_complete_rerun`.
- **Commit:** 1d9e4ce

### TDD notes

- Task 1 RED for the sufficiency unit tests is a missing module (as in 13-07); two of the seven CLI exit-code cases (`ONBOARD_LIMITED`, `DELISTED_CAPPED` with exit 0) passed at RED because the 13-07 CLI already exited 0 there; the other five and the report tests failed.
- The Task 3 RED commit also switches the shared `_config` helper to pass `funding=False`, so the older CLI tests fail with a `TypeError` until the GREEN commit adds the field. That is a shared-helper side effect, not a defect.
- Task 2's `test_full_1m_coverage_prints_no_extension_note` passed at RED (its assertion is the absence of a feature); it guards the negative case after GREEN.

**Total deviations:** 4 auto-fixed (1 Rule 1, 2 Rule 3, 1 Rule 2). **Impact:** none on scope; all plan must-haves and acceptance criteria are met.

## Issues Encountered

- One transient failure of the unchanged 13-07 test `test_cli_refreshes_metadata_before_backfill` occurred on a single run (first full run after the Task 1 GREEN edit); it passed alone and in 8 later runs of the same file and in the full suite. It writes 730 Parquet files under `%TEMP%`, so a Windows file-lock/indexer race at `os.replace` is the likely cause; not reproduced, not investigated further.
- Known pre-existing failures (decision-alignment RQ-01/RQ-04, plan 13-11 scope) and the `src/paper/supervisor.py` mypy chain error in `deferred-items.md` were not touched; the full suite was run with the two decision-alignment modules ignored.
- Fail-closed choices worth knowing before the 13-13 operator run: an archive-only symbol whose real listing is later than the depth start shows a leading GAP (exchangeInfo, which carries the onboard time, no longer lists it, so the start cannot be known); split-block `expected_1m` is the whole block regardless of a symbol's onboard or delivery; the funding step's gap rows do not change the exit code (they are in `collector_gaps`).
- `resume_from_store` hazard from the 13-07 summary still applies: run against an empty raw root, or read the report, because a short recent bootstrap already in `data/raw` shows up here as `GAP` rows rather than being silently skipped.

## Known Stubs

None.

## Threat Flags

None. The only new file written is the `_sources.json` provenance sidecar inside the existing cursor directory (symbol names matched against `SYMBOL_RE`, no credentials); the archive client, host and size caps are 13-05's and unchanged.

## Threat Model Coverage

- T-13-44: `MISSING_DATA_CAUSES` drive exit 3; `test_cli_exit_code_is_3_only_for_missing_data` covers GAP, NOT_BACKFILLED, UNAVAILABLE (3) and OK, ONBOARD_LIMITED, DELISTED_CAPPED, NO_WINDOW (0); gaps use `gap_ranges_for_files`.
- T-13-45: source in the run output, the table SOURCE column and the JSON; persisted across complete re-runs (`test_archive_source_survives_a_complete_rerun`).
- T-13-46: report text only; `RESEARCH_PROTOCOL.md` diff is empty; no trade estimate (`test_report_states_trade_floor_is_unmeasurable`).
- T-13-47: mark only from REST; `test_mark_for_archive_symbol_comes_from_rest_or_is_unavailable` asserts no mark day exists for the symbol REST rejected.
- T-13-SC: no packages installed.

## Next Phase Readiness

Plan 13-13 (operator run) can pass `--report-out` and read the sufficiency numbers per protocol block; `python -m src.data.sufficiency validate` checks the committed report file. The 12-versus-24-month 1m decision (D-21) is the user's, taken from the printed split coverage. Plan 13-12 (freeze) is independent: every 13-08 test uses tmp manifest and collect-list paths.

## Self-Check: PASSED

- FOUND: src/data/sufficiency.py, tests/test_sufficiency.py, src/data/backfill_cli.py, tests/test_backfill_cli.py; `grep -n "TRADE_FLOOR_NOTE" src/data/sufficiency.py` prints the constant and its use; `grep -n "ArchiveKlineSource\|backfill_funding_history" src/data/backfill_cli.py` prints both.
- FOUND: commits 2092da1, 4360c5b, dfbe0d9, 16482c3, 352daeb, 1d9e4ce (`git rev-list --count 2d9dd60..HEAD` = 6 before this summary commit).
- Acceptance criteria re-run: `test_cli_exit_code_is_3_only_for_missing_data` (7 cases) passes; `test_split_boundaries_follow_protocol_40_40_20` asserts the literal instants and passes; the five new Task 3 tests pass; `git diff 2d9dd60..HEAD -- docs/research/RESEARCH_PROTOCOL.md` is empty.
- Plan verification: `pytest tests/test_sufficiency.py tests/test_backfill_cli.py tests/test_archive_ingest.py tests/test_collector.py tests/test_case_input_builder.py` passes; `mypy src/data` reports no issues; `ruff check` clean on the four touched files; `python -m src.data.sufficiency --help` lists `validate`; `python -m src.data.backfill_cli --help` lists `--report-out` and `--funding/--no-funding`.
- Full suite with the two decision-alignment modules ignored: 2328 tests collected, all passed.
