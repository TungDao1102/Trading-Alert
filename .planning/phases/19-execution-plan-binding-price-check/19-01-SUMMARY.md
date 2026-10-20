---
phase: 19-execution-plan-binding-price-check
plan: 01
subsystem: execution
tags: [execution-limits, not-configured, fail-closed, toml, tdd, guard]

requires:
  - phase: 18-user-data-stream-error-taxonomy
    provides: "the binance_limits loader pattern, tests/support/limits.py and the unratified-default scan"
provides:
  - "config/execution/execution-limits-v1.toml: the four Phase 19 keys, all NOT_CONFIGURED"
  - "src/execution/execution_limits.py: ExecutionLimits with require_live_ready(), the strict loader and its errors"
  - "tests/support/execution_limits.py: TEST_ONLY values and a TOML writer for plans 19-11 to 19-16"
  - "the numeric-default guard extended from 30 to 34 names"
affects: [19-11, 19-13, 19-17]

actuals:
  tokens: 8500
  tasks: 3
  commits: 4
plan_head_before: 28e7f284da9b142f31b97d68a3400475dd8a2944
plan_head_after: 3325f04265acb6a5e2d5069e4dd22819ba88ac7f
commits: 4

tech-stack:
  added: []
  patterns:
    - "a separate versioned limits file with its own loader when the existing one is hash-pinned"
    - "NOT_CONFIGURED value mapped to None with a NOT_CONFIGURED provenance label; live path refuses via require_live_ready"

key-files:
  created:
    - config/execution/execution-limits-v1.toml
    - config/execution/README.md
    - src/execution/execution_limits.py
    - tests/support/execution_limits.py
    - tests/test_execution_limits.py
  modified:
    - tests/test_no_unratified_defaults.py
    - tests/test_phase18_gate.py
    - .gitattributes

key-decisions:
  - "The D-13 entry terminal timeout key is named entry_terminal_timeout_ms (the _ms suffix is added for unit clarity); max_unprotected_ms is verbatim"
  - "A NOT_CONFIGURED value requires provenance NOT_CONFIGURED and an integer requires one of STRUCTURAL, COST_GUARD, DECISION, EXPERIMENT; PLACEHOLDER refuses to load"
  - "ExecutionLimits has no field default; unset is None, and require_live_ready() raises ExecutionLimitsNotConfigured naming dotted keys only"
  - "OWNER-OPEN O-04 (the four numbers) stays open; no number for any of the four keys exists outside tests/support/execution_limits.py"

patterns-established:
  - "Separate file and loader for new keys beside a sha256-pinned ratified file; the ratified file is not edited"

requirements-completed: [EXEC-01]

coverage:
  - id: D1
    description: "The versioned file holds the four keys, every one NOT_CONFIGURED, and the real file loads with all four fields None"
    requirement: EXEC-01
    verification:
      - kind: unit
        ref: "tests/test_execution_limits.py#test_the_real_file_loads_with_every_field_unset"
        status: pass
      - kind: unit
        ref: "tests/test_execution_limits.py#test_the_committed_file_names_only_the_not_configured_word"
        status: pass
    human_judgment: false
  - id: D2
    description: "require_live_ready refuses naming exactly the unset keys, with no value and no path in the message"
    requirement: EXEC-01
    verification:
      - kind: unit
        ref: "tests/test_execution_limits.py#test_require_live_ready_refuses_naming_the_four_keys"
        status: pass
      - kind: unit
        ref: "tests/test_execution_limits.py#test_a_mixed_document_loads_and_lists_only_the_unset_keys"
        status: pass
    human_judgment: false
  - id: D3
    description: "The loader refuses every malformed document by key or section name, never by value (20 parametrized cases)"
    requirement: EXEC-01
    verification:
      - kind: unit
        ref: "tests/test_execution_limits.py#test_every_malformed_document_is_refused_by_name"
        status: pass
    human_judgment: false
  - id: D4
    description: "No numeric default for the four names or ExecutionLimits can enter src or scripts; the TEST_ONLY module cannot be imported by production code"
    requirement: EXEC-01
    verification:
      - kind: unit
        ref: "tests/test_no_unratified_defaults.py#test_no_canonical_key_gets_a_numeric_constant_in_src_or_scripts"
        status: pass
      - kind: unit
        ref: "tests/test_no_unratified_defaults.py#test_the_scanner_finds_every_forbidden_form"
        status: pass
      - kind: unit
        ref: "tests/test_phase18_gate.py#test_invariant_5_no_unratified_default_in_src_or_scripts"
        status: pass
    human_judgment: false

duration: 28min
completed: 2026-10-19
status: complete
---

# Phase 19 Plan 01: Execution limits file and fail-closed loader Summary

**A separate `config/execution/execution-limits-v1.toml` holds the four D-07/D-13 safety numbers as `NOT_CONFIGURED`, and `ExecutionLimits.require_live_ready()` refuses the live path naming the unset keys, with the numeric-default guard extended from 30 to 34 names.**

## Performance

- **Duration:** 28 min
- **Started:** 2026-10-19T12:31:52Z
- **Completed:** 2026-10-19T13:00:00Z
- **Tasks:** 3
- **Files:** 5 created, 3 modified

## Accomplishments

- Tracer (task 1): the committed file, the loader and the refusal work end to end. Loading the real file gives four `None` fields and `require_live_ready()` raises `ExecutionLimitsNotConfigured` with `keys` equal to the four dotted names in file order. The module imports only the standard library (asserted with `forbidden_imports`).
- Validation (task 2): `parse_execution_limits` reports every problem together and names only the dotted key or section. Twenty parametrized refusals cover missing and unknown keys and sections, non-table sections, bool, float, zero, negative and foreign string values, missing, PLACEHOLDER, unknown and non-string labels, and the value/label mismatches. `tests/support/execution_limits.py` provides `TEST_ONLY_EXECUTION_LIMIT_VALUES` (7777, 13333, 777, 4321), `test_only_execution_limits` and `write_execution_limits_toml`, with round trips for the TEST_ONLY and the all-unset documents.
- Guard (task 3): `GUARDED_NAMES` is built from `EXECUTION_LIMIT_KEYS` (never re-typed) and is now 34; `ExecutionLimits` joined `LIMIT_CLASS_NAMES`; importing `tests.support.execution_limits` from `src` or `scripts` is an offence with negative controls; the count pin in `tests/test_phase18_gate.py` moved 30 to 34. `config/execution/README.md` lists the four keys with meaning and unit and carries no value; `.gitattributes` pins `config/execution/*.toml -text`.
- `config/binance/` is byte-identical (`git diff --exit-code -- config/binance/` exits 0) and the 27-key README test is untouched.

## Task Commits

1. **Task 1 RED:** `27b5451` test(19-01): tracer test for the NOT_CONFIGURED execution limits
2. **Task 1 GREEN:** `4828b90` feat(19-01): NOT_CONFIGURED execution limits file and fail-closed loader
3. **Task 2:** `b5f6543` test(19-01): execution limits validation matrix and TEST_ONLY values
4. **Task 3:** `3325f04` feat(19-01): guard the four execution limits, document them and pin LF

## Files Created/Modified

- `config/execution/execution-limits-v1.toml` - the four keys, `[protection]` and `[pre_placement]`, all `"NOT_CONFIGURED"`, with a matching provenance table.
- `config/execution/README.md` - purpose, format, provenance rules, the four keys, no value.
- `src/execution/execution_limits.py` - `NOT_CONFIGURED_WORD`, `EXECUTION_LIMIT_KEYS`, `ALLOWED_PROVENANCE_LABELS`, `ExecutionLimits`, three error classes, `parse_execution_limits`, `load_execution_limits`.
- `tests/support/execution_limits.py` - TEST_ONLY values and writer.
- `tests/test_execution_limits.py` - 37 tests.
- `tests/test_no_unratified_defaults.py`, `tests/test_phase18_gate.py`, `.gitattributes` - guard extension, count pin, LF pin.

## Decisions Made

- `entry_terminal_timeout_ms` carries the `_ms` suffix (D-13 names the concept `entry_terminal_timeout`); recorded in the README and here. Later plans must use this name.
- OWNER-OPEN O-04 (the four numbers) stays open and is to be recorded in plan 19-17. No number for the four keys exists in `src`, `scripts`, the TOML or the README.

## Deviations from Plan

None - plan executed exactly as written. Ordering note: the complete value and provenance validation was written with the tracer in task 1 (the committed file needs it to load), so task 2 added the test matrix and TEST_ONLY helpers against already-complete validation; the matrix went green on first run.

## Verification Results

- `uv run pytest -m "not docker" tests/test_execution_limits.py tests/test_no_unratified_defaults.py tests/test_phase18_gate.py tests/test_binance_limits_ratified_file.py tests/test_binance_limits.py -q`: all passed.
- Wider run of `tests/test_execution*.py`, `tests/test_phase*gate*.py`, `tests/test_bootstrap.py`, `tests/test_binance_usdm_source_guard.py`, `tests/test_deploy_images.py`, `tests/test_deploy_compose.py`: all passed (one skip).
- `uv run mypy src`: success, no issues in 203 source files. `uv run ruff check`: all checks passed. `uv run ruff format --check`: clean.
- The whole `-m "not docker"` suite was started but exceeds a ten-minute cap on this machine and was stopped at about 20 percent with no failure; it was not run to completion.

## Issues Encountered

None.

## Known Stubs

None. The four `None` values are the intended NOT_CONFIGURED state, not stubs.

## Threat Flags

None. No new network, auth or file-access surface; the loader only reads one repository TOML file.

## Next Phase Readiness

The consumers are plans 19-11 (coordinator check) and 19-13 (manager gate), which call `require_live_ready()`; 19-11 to 19-16 fixtures use the TEST_ONLY values. O-04 stays open for plan 19-17.

## Self-Check: PASSED

- FOUND: config/execution/execution-limits-v1.toml, config/execution/README.md, src/execution/execution_limits.py, tests/support/execution_limits.py, tests/test_execution_limits.py
- FOUND commits: 27b5451, 4828b90, b5f6543, 3325f04 (all ancestors of HEAD; `git rev-list --count` from the plan base is 4)
