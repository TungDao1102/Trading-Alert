---
phase: 20-reconcile-safe-mode-hardening
plan: 01
subsystem: execution-config
tags: [execution-limits, config, fail-closed, not-configured, reconcile, stale-feed, alerts, tdd]

requires:
  - phase: 19-execution-plan-binding-price-check
    provides: config/execution/execution-limits-v1.toml, ExecutionLimits and its fail-closed loader (plan 19-01), the unratified-default scan
provides:
  - "seven new NOT_CONFIGURED execution limits: reconcile.tick_interval_ms, reconcile.entry_unknown_probe_count, reconcile.entry_unknown_probe_interval_ms, reconcile.lot_filter_refresh_interval_ms, stale_feed.max_mark_price_age_ms, stale_feed.max_user_data_silence_ms, alerts.dedupe_window_ms"
  - "EXECUTION_LIMIT_FIELDS (dotted key -> dataclass field name; Phase 20 fields are <section>_<key>)"
  - "check_reconcile_cadence(limits) -> None (tick strictly below max_unprotected_ms)"
  - "TEST_ONLY values for the seven keys and a numeric-default guard over key texts and field names"
affects: [20-10, 20-12, 20-13, 20-15, 20-16, 20-21, 20-07]

plan_head_before: 567dd8afd09a5ac26fc561732b26c23a441c3aec
plan_head_after: 9f22e14d0ffd8d1ba4300ec38a8d066d4e57e365

actuals:
  tokens: 10764   # chars/4 over `git diff 567dd8af HEAD` (43055 chars)
  tasks: 3
  commits: 6      # MEASURED: git rev-list --count 567dd8af..HEAD (3 test + 3 feat)

tech-stack:
  added: []
  patterns:
    - "dotted key -> field-name table (EXECUTION_LIMIT_FIELDS) as the only place the mapping lives"
    - "Phase 20 dataclass fields named <section>_<key> to avoid the max_mark_price_age_ms key-text collision"

key-files:
  created: []
  modified:
    - config/execution/execution-limits-v1.toml
    - config/execution/README.md
    - src/execution/execution_limits.py
    - tests/support/execution_limits.py
    - tests/test_execution_limits.py
    - tests/test_no_unratified_defaults.py
    - tests/test_phase18_gate.py

key-decisions:
  - "Phase 20 ExecutionLimits fields are <section>_<key>; the seven Phase 19 field names are unchanged so existing consumers keep reading limits.max_unprotected_ms."
  - "The numeric-default guard covers both the key texts and the <section>_<key> field names (GUARDED_NAMES 37 -> 50, computed from the code)."
  - "check_reconcile_cadence is a pure function with no caller in this plan; the ReconcileLoop constructor of plan 20-12 calls it."

requirements-completed: [EXEC-02, OPS-05]

coverage:
  - id: D1
    description: "Seven Phase 20 keys added to the execution-limits TOML, every value and provenance label NOT_CONFIGURED; the loader reads and validates all fourteen"
    requirement: "EXEC-02"
    verification:
      - kind: unit
        ref: "tests/test_execution_limits.py#test_the_real_file_loads_with_every_field_unset"
        status: pass
      - kind: unit
        ref: "tests/test_execution_limits.py#test_every_malformed_phase_20_entry_is_refused_by_name"
        status: pass
    human_judgment: false
  - id: D2
    description: "require_live_ready names every new unset key in file order, so the live path refuses while any is NOT_CONFIGURED"
    requirement: "EXEC-02"
    verification:
      - kind: unit
        ref: "tests/test_execution_limits.py#test_require_live_ready_refuses_naming_every_key"
        status: pass
    human_judgment: false
  - id: D3
    description: "check_reconcile_cadence refuses a tick not strictly below max_unprotected_ms and is silent while either value is unset"
    requirement: "EXEC-02"
    verification:
      - kind: unit
        ref: "tests/test_execution_limits.py#test_a_tick_equal_to_the_deadline_is_refused_naming_both_keys"
        status: pass
    human_judgment: false
  - id: D4
    description: "The unratified-default scan guards every new key text and field name; no numeric value for them exists in config, src or scripts"
    requirement: "OPS-05"
    verification:
      - kind: unit
        ref: "tests/test_no_unratified_defaults.py#test_the_scan_covers_src_and_scripts"
        status: pass
    human_judgment: false
  - id: D5
    description: "The numbers themselves (owner decision O-G) are not chosen; LIVE stays blocked"
    verification: []
    human_judgment: true
    rationale: "Choosing a number for any key is the owner's decision after Demo evidence (O-04, O-G); no test can assert it."

duration: 15min
completed: 2026-10-21
status: complete
---

# Phase 20 Plan 01: Phase 20 configuration keys Summary

**Seven reconcile, stale-feed and alert limits added to the execution-limits file as NOT_CONFIGURED, loaded into `<section>_<key>` fields of `ExecutionLimits`, named by `require_live_ready`, guarded against numeric defaults, plus a cadence check that keeps the reconcile tick strictly below `max_unprotected_ms`.**

## Performance

- **Duration:** about 15 min
- **Completed:** 2026-10-21
- **Tasks:** 3 (one tracer, two auto, all `tdd="true"`; each had a RED and a GREEN commit)
- **Files modified:** 7 (no file created)

## Accomplishments

- `config/execution/execution-limits-v1.toml` gains `[reconcile]` (4 keys), `[stale_feed]` (2) and `[alerts]` (1) with matching `[provenance.*]` tables. Every value and every label is the word `NOT_CONFIGURED`; 28 such lines now exist. No number was chosen.
- `src/execution/execution_limits.py`: `EXECUTION_LIMIT_KEYS` extended, new `EXECUTION_LIMIT_FIELDS` mapping, seven new `int | None` fields, `unset_keys()` and `parse_execution_limits()` go through the mapping. `require_live_ready()` now names fourteen keys in file order (protection, pre_placement, reconcile, stale_feed, alerts).
- `stale_feed.max_mark_price_age_ms` loads into `stale_feed_max_mark_price_age_ms`, separate from `pre_placement.max_mark_price_age_ms`; `stale_feed.max_user_data_silence_ms` is a separate key from the paper runtime's `max_ws_message_silence_seconds` (`src/paper/coverage.py` untouched).
- `check_reconcile_cadence(limits)` added and exported: silent while either value is `None`, raises `ExecutionLimitsInvalid` naming both keys and no value when tick >= deadline. It has no caller yet (plan 20-12 adds it).
- `tests/support/execution_limits.py` carries the TEST_ONLY values (1234, 3, 2345, 8642, 3579, 5791, 6543); `test_only_execution_limits` builds field names through `EXECUTION_LIMIT_FIELDS`.
- `tests/test_no_unratified_defaults.py` guards the new key texts and the seven field names (GUARDED_NAMES computed from code: 50); `tests/test_phase18_gate.py` pin updated to match.
- `config/execution/README.md` lists the fourteen keys with meaning, unit and consumer plan, explains the `<section>_<key>` field rule, separates the user-data silence key from the paper key, and states that a set value needs a DECISIONS row and provenance `DECISION`.

## Task Commits

1. **Task 1 (tracer): reconcile.tick_interval_ms end to end**
   - RED `6fd902ad` (test) - 7 tests failed on assertions/refusal-by-name for the missing key
   - GREEN `a4e11c9b` (feat)
2. **Task 2: the remaining six keys, TEST_ONLY values, README, guard**
   - RED `80b6b899` (test)
   - GREEN `e69432aa` (feat)
3. **Task 3: check_reconcile_cadence**
   - RED `96122ea6` (test) - AttributeError: the function did not exist yet
   - GREEN `9f22e14d` (feat)

**Plan metadata:** the docs commit that adds this file (see git log, `docs(20-01)`).

## Evidence labels

- `[EXECUTED]` plan verification, run after the last task commit: `uv run pytest -m "not docker" tests/test_no_unratified_defaults.py tests/test_phase18_gate.py tests/test_execution_limits.py tests/test_binance_limits_ratified_file.py` gave 201 passed; `uv run mypy src` clean (214 files); `uv run ruff check` and `uv run ruff format --check` clean.
- `[EXECUTED]` one adjacent test that reads the same file and iterates `EXECUTION_LIMIT_KEYS`: `tests/test_phase19_gate.py -k invariant_4`, 1 passed.
- `[EXECUTED]` `git diff 567dd8af HEAD -- config/binance src/paper/coverage.py pyproject.toml uv.lock` is empty.
- `[NOT_RUN]` the full suite and the other Phase 19 gate tests (orchestrator runs them once per phase, per project rule).
- No `[DEMO]` claim. LIVE stays blocked: `LIVE_ORDERS_DISABLED` is untouched and all fourteen limits load as `None` from the committed file.

## Decisions Made

- Phase 20 dataclass fields are `<section>_<key>`; Phase 19 fields keep their names. The collision that forces it is `stale_feed.max_mark_price_age_ms` vs `pre_placement.max_mark_price_age_ms`.
- The guard covers field names as well as key texts, so a numeric default cannot hide behind either spelling.
- No gate-cooldown key was added; it exists only if the owner picks option-b at the O-C checkpoint of plan 20-07 (per the plan).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Task 1 also touched the README and two pinned counts**
- **Found during:** Task 1 (tracer GREEN)
- **Issue:** Task 1 adds a section to `EXECUTION_LIMIT_KEYS`, which immediately breaks `test_the_readme_lists_exactly_the_execution_limit_keys`, the TOML `NOT_CONFIGURED` count test (both inside the Task 1 verify file) and the pinned `len(GUARDED_NAMES)` in `tests/test_no_unratified_defaults.py` and `tests/test_phase18_gate.py`. The plan scheduled README and pins for Task 2.
- **Fix:** Task 1 adds the one README bullet for `reconcile.tick_interval_ms` and moves the pins 37 -> 38 and the count 14 -> 16, so every commit is green. Task 2 then set the final values (50 and 28).
- **Files modified:** `config/execution/README.md`, `tests/test_no_unratified_defaults.py`, `tests/test_phase18_gate.py`, `tests/test_execution_limits.py`
- **Commit:** `a4e11c9b`

**2. [Rule 3 - Blocking] RED evidence could not be verified with `gsd_run check tdd-red-evidence`**
- **Found during:** Task 1 RED
- **Issue:** the checker only parses TAP, node:test and Surefire output; given the pytest output of a genuine failing run it returned `INVALID_RED / zero_tests_discovered` (0 tests parsed). The plan is `type: execute`, so the plan-level TDD gate does not apply, but the per-task `tdd="true"` discipline does.
- **Fix:** RED was established from the pytest output itself: the named target tests failed on assertions for the planned behavior (for example `unset_keys()` missing `reconcile.tick_interval_ms`, "DID NOT RAISE"/missing name in the refusal message), and no GREEN code existed. Task 3's RED failed with `AttributeError` because the function did not exist. The checker verdict was not obtained and is not claimed.
- **Files modified:** none

**3. [Rule 1 - Bug] Two of my own new test expectations were wrong and were corrected before GREEN was committed**
- **Found during:** Task 2 GREEN
- **Issue:** the refusal matrix asserted that the label word `PLACEHOLDER` must not appear in the message, but the loader names the label by design (the existing matrix expects it); and the Task 1 test built its document without the Task 2 sections.
- **Fix:** the placeholder case no longer forbids the label text; the reconcile document helper builds on the full Phase 20 document.
- **Commit:** `e69432aa`

**Total deviations:** 3 (2 blocking-type, 1 bug in new tests). **Impact:** none on scope; no key value, dependency or Binance file was touched.

## Known Stubs

None. `check_reconcile_cadence` having no caller is deliberate and stated in the plan (plan 20-12 adds the call).

## Threat Flags

None. No new network, auth or file-access surface. T-20-01 (hand-edited config file) and T-20-02 (numeric default in `src`) are mitigated as planned: the loader accepts only a positive int with a project label or `NOT_CONFIGURED`, and the guard covers the new names. T-20-SC: `pyproject.toml` and `uv.lock` unchanged.

## Notes for later plans

- The numbers of all fourteen limits are the owner's (O-04, O-G); none was chosen here.
- Consumers: 20-10 (`reconcile_entry_unknown_probe_count/_interval_ms`), 20-12 (`check_reconcile_cadence`, `reconcile_tick_interval_ms`), 20-13 (`alerts_dedupe_window_ms`), 20-16 (`stale_feed_*`), 20-21 (`reconcile_lot_filter_refresh_interval_ms`), 20-15 (removes `SAFE_MODE_TICK_SECONDS`).
- Working-tree note: `src/execution/execution_limits.py`, the touched tests and `config/execution/README.md` are CRLF in the working tree (LF in the index) and were kept that way; the TOML is LF (`-text`).

## Self-Check: PASSED

All seven modified files and this SUMMARY exist; all six task commits (`6fd902ad`, `a4e11c9b`, `80b6b899`, `e69432aa`, `96122ea6`, `9f22e14d`) are in the log; every task acceptance criterion was re-run and held (NOT_CONFIGURED line count 28 >= 28, subset assertion present, `git diff` on `config/binance/`, `src/paper/coverage.py`, `pyproject.toml`, `uv.lock` empty).
