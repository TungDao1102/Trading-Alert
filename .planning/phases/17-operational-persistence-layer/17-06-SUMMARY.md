---
phase: 17-operational-persistence-layer
plan: 06
subsystem: execution
tags: [constraint-snapshot, exchange-info, market-lot-size, percent-price, canonical-json, decimal, tdd]

requires:
  - phase: 17-operational-persistence-layer
    provides: "plan 01/02: plan_constraint_snapshots table (UNKNOWN-sentinel text columns), LiveInputsStatus enum"
provides:
  - "src/adapters/binance_usdm.py: six optional trailing SymbolFilters fields (market_lot_min/max_quantity, market_lot_step_size, percent_price_multiplier_up/down/decimals) parsed from MARKET_LOT_SIZE and PERCENT_PRICE"
  - "src/execution/constraint_snapshot.py: PlanConstraintSnapshot, ExchangeFilterExtras, build_plan_constraint_snapshot, canonical_json, snapshot_sha256, parse_snapshot_json, snapshot_is_valid_for_live, ttl_from_parameter_set, UNKNOWN"
  - "tests/test_symbol_filters_extra.py and tests/test_constraint_snapshot.py"
affects: [17-13, 17-15]

actuals:
  tokens: 13400
  tasks: 2
  commits: 4
plan_head_before: 227291b3ebbf8278dc51f7b34f0fcae0ed361c1b
plan_head_after: a7fb7e8d2deec7b601a90e9cf97a40b49e137846

tech-stack:
  added: []
  patterns:
    - "Absent exchange filter is None in the adapter and the explicit UNKNOWN sentinel in the snapshot JSON, never zero or an invented default"
    - "Evidence hash (snapshot sha256) kept outside plan_hash so the approval binding contract does not move"
    - "Pure execution-layer module takes primitive inputs (ExchangeFilterExtras) so it never imports the adapter or the SDK"

key-files:
  created:
    - src/execution/constraint_snapshot.py
    - tests/test_constraint_snapshot.py
    - tests/test_symbol_filters_extra.py
  modified:
    - src/adapters/binance_usdm.py

key-decisions:
  - "max_quantity (LOT_SIZE maxQty) counts as a filter value for completeness: a snapshot whose max_quantity is None is INCOMPLETE and invalid for live (stricter than the plan's minimum, fail closed)"
  - "JSON carries a snapshot_schema_version (1); parse_snapshot_json rejects any other version, unknown keys, missing keys, JSON floats and NaN/Infinity constants"
  - "margin_type is validated only as a non-empty text of at most 16 characters that is not the UNKNOWN sentinel; no margin vocabulary is hard-coded (Phases 21-22 supply it from Binance)"
  - "ttl_from_parameter_set accepts only a positive int (bool, float, str, 0, negative and missing all raise ValueError)"

patterns-established:
  - "Plan 13 can persist canonical_json/snapshot_sha256/live_inputs_status straight into plan_constraint_snapshots: UNKNOWN literals line up with the table's NOT NULL text columns and its complete_has_live_inputs CHECK"

requirements-completed: [EXEC-04]

coverage:
  - id: D1
    description: "Adapter parses MARKET_LOT_SIZE and PERCENT_PRICE into optional SymbolFilters fields (Decimal, int decimals), None when absent, ValueError when present but malformed or incomplete"
    requirement: EXEC-04
    verification:
      - kind: unit
        ref: "tests/test_symbol_filters_extra.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "PlanConstraintSnapshot is built, canonically serialized, hashed and round-tripped, with UNKNOWN sentinels making live_inputs_status INCOMPLETE"
    requirement: EXEC-04
    verification:
      - kind: unit
        ref: "tests/test_constraint_snapshot.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "snapshot_is_valid_for_live is False for INCOMPLETE, stale (age > ttl) and future-dated captures, True at exactly ttl; ttl comes from constraint_snapshot_ttl_seconds"
    requirement: EXEC-04
    verification:
      - kind: unit
        ref: "tests/test_constraint_snapshot.py#test_age_exactly_ttl_is_valid_and_one_microsecond_over_is_stale"
        status: pass
      - kind: unit
        ref: "tests/test_constraint_snapshot.py#test_ttl_reads_a_real_registered_parameter_set"
        status: pass
    human_judgment: false

duration: 45min
completed: 2026-10-01
status: complete
---

# Phase 17 Plan 06: Per-Plan Constraint Snapshot Summary

**The adapter now parses MARKET_LOT_SIZE and PERCENT_PRICE as optional SymbolFilters fields, and a pure `PlanConstraintSnapshot` records the exact exchange constraints per plan as canonical JSON with a sha256, explicit `UNKNOWN` sentinels, and a staleness/completeness predicate for live validity (EXEC-04, D-18, D-19).**

## Performance

- **Duration:** ~45 min (about 13 of them one full-suite run)
- **Tasks:** 2 (both TDD: RED then GREEN)
- **Files:** 3 created, 1 modified

## Accomplishments

- `SymbolFilters` gained six trailing optional fields after `delivery_date_ms` (no symbol_metadata column, no migration, research C10). MARKET_LOT_SIZE maps to min/max quantity and step size, PERCENT_PRICE to multiplierUp/Down (Decimal) and multiplierDecimal (int). An absent filter leaves None; a present filter with a missing, empty, non-numeric, non-finite field (or a non-integer or negative multiplierDecimal) raises ValueError. The existing required-filter drift handling is untouched.
- `src/execution/constraint_snapshot.py` (stdlib, Decimal, `src.domain`, `src.risk.types` only) provides the frozen `PlanConstraintSnapshot` and `ExchangeFilterExtras`, `build_plan_constraint_snapshot`, `canonical_json` (via `canonical_bytes`: sorted keys, Decimal as text, `+00:00` datetimes), `snapshot_sha256`, strict `parse_snapshot_json`, `snapshot_is_valid_for_live` and `ttl_from_parameter_set`.
- `working_type` is restricted to `WORKING_TYPE_VALUES` (MARK_PRICE only, D037). Float inputs raise TypeError, naive or non-UTC datetimes raise ValueError, leverage must be a positive int (bool rejected), equity a positive finite Decimal.
- Live validity mirrors the gates.py stale predicate (`age > ttl or age < 0`): False for INCOMPLETE, for age over the TTL by a microsecond and for a future-dated capture, True at exactly the TTL. Age is measured from the exchangeInfo capture time, not the snapshot record time.
- The snapshot hash is evidence only: `plan_hash`, `src/core/planner.py` and the approval binding are untouched.

## Task Commits

1. Task 1 RED: `a07ad6d` test(17-06): RED for MARKET_LOT_SIZE and PERCENT_PRICE SymbolFilters parsing
2. Task 1 GREEN: `e1be105` feat(17-06): parse MARKET_LOT_SIZE and PERCENT_PRICE into optional SymbolFilters fields
3. Task 2 RED: `154eaf2` test(17-06): RED for PlanConstraintSnapshot canonical JSON, UNKNOWN sentinels and live validity
4. Task 2 GREEN: `a7fb7e8` feat(17-06): pure PlanConstraintSnapshot with canonical JSON, sha256 and live-validity predicate

No REFACTOR commit (nothing to clean up).

## TDD Gate Compliance

RED and GREEN commits exist for both tasks, in order. Task 1's RED run failed on the target assertions (AttributeError for the missing fields, "DID NOT RAISE ValueError" x13 for the malformed-filter cases). Task 2's RED run failed at collection with `ModuleNotFoundError: No module named 'src.execution.constraint_snapshot'` (the module is brand new, so absence of the feature is the failure); this is a missing-feature import failure rather than an assertion failure, which the strict #3770 definition would label INVALID_RED. The `gsd_run check tdd-red-evidence` verifier was not run for either RED (no evidence record was persisted); the failing output above is the evidence.

## Verification (real runs)

- Task 1 verify: `pytest tests/test_symbol_filters_extra.py tests/test_execution_adapter_contract.py tests/test_metadata.py tests/test_adapter_strictness.py -x -q` exit 0.
- Task 2 verify: `pytest tests/test_constraint_snapshot.py tests/test_symbol_filters_extra.py tests/test_execution_manager.py -x` -> **107 passed**.
- `mypy src`: no issues in 126 source files. `ruff check`: all checks passed. `ruff format --check src tests`: 283 files already formatted.
- Plan-level: `pytest -m "not docker" -q -p no:cacheprovider` exit 0, no failures (about 3060 passed, 154 skipped; the skips are PostgreSQL-bound and other environment tests because `TEST_DATABASE_URL` was not set, which this plan does not need).
- Acceptance greps: `grep -n "market_lot_step_size: Decimal | None = None" src/adapters/binance_usdm.py` -> line 260; `grep -c PERCENT_PRICE src/adapters/binance_usdm.py` -> 8; `grep -nE "^(from|import) (src\.adapters|binance)" src/execution/constraint_snapshot.py` -> no output; `def snapshot_is_valid_for_live` once (line 394); `UNKNOWN = "UNKNOWN"` once (line 38).
- Fixtures: no fixture, expected file or hash moved. `git diff --stat 227291b..HEAD` lists only the four plan files; `tests/fixtures/exchange_info_sample.json` is unchanged and no regeneration was needed.

## Deviations from Plan

None - plan executed exactly as written.

Scope notes (choices inside the plan's latitude, listed under key-decisions): `max_quantity` participates in the COMPLETE rule, a `snapshot_schema_version` key was added for "versionable", and `build_plan_constraint_snapshot` takes `margin_type`, `leverage`, `equity_used` and `captured_at_utc` keyword-only.

**Total deviations:** 0.

## Known Stubs

None. Margin type, leverage and equity are intentionally UNKNOWN until Phases 21-22 (D-19, D-21); that is the designed INCOMPLETE state, not a stub.

## Threat Flags

None. T-17-16 mitigated (UNKNOWN sentinel, INCOMPLETE status, invalid for live; absent filters never become zero or defaults). T-17-17 mitigated (Decimal-only inputs, float rejected with TypeError, canonical_bytes, round-trip test, JSON floats rejected on parse). T-17-SC: no packages installed.

## Issues Encountered

- One transient failure of `tests/test_backfill_cli.py::test_cli_refreshes_metadata_before_backfill` appeared once when run in a combined invocation with `tests/test_universe_freeze.py` and `tests/test_wave0_sanity.py`. It did not reproduce: the same combination passed afterwards (73 passed), the test passed 3 more times alone, and the full suite passed. Treated as an unreproduced transient; not investigated further.

## Self-Check: PASSED

- `src/execution/constraint_snapshot.py`, `tests/test_constraint_snapshot.py`, `tests/test_symbol_filters_extra.py` and this SUMMARY exist; commits a07ad6d, e1be105, 154eaf2, a7fb7e8 exist; measured commit count 4 from the recorded plan head 227291b.

## Next

Ready for plan 17-07. Plan 13 persists `canonical_json`, `snapshot_sha256` and `live_inputs_status` into `plan_constraint_snapshots` (Phase 19/24 wire `SymbolFilters` to `ExchangeFilterExtras`; re-sizing on a stale snapshot is Phase 19).
