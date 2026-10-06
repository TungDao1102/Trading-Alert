---
phase: 15-strategy-geometry-correction
plan: 02
subsystem: parameter-registry
tags: [rationale, provenance, paper-freeze, tdd, hash-neutrality, F-909]

requires:
  - phase: 11-decision-alignment
    provides: registry parse path (_parse_and_validate) and the pinned hash fixture over every committed set
  - phase: 07-paper-loop
    provides: pin_stream_epoch / StreamEpoch freeze path
provides:
  - "src/domain/rationale.py: RATIONALE_BASES, RationaleEntry, load_rationale, check_rationale, placeholder_keys, UnrationalizedParameterSet"
  - "pin_stream_epoch(..., allow_unrationalized=False): strict refusal of sets with missing/incomplete rationale or any PLACEHOLDER key"
  - "Hash-neutral in-file [rationale.<key>] tables (basis, value, text, optional ref) usable by every new parameter set"
affects: [15-03, 15-04, 15-05, 15-06, 15-08, 15-14, 15-15]

actuals:
  tokens: 7800
  tasks: 2
  commits: 4
plan_head_before: e47391a5ae7a4e9d3f9fc2fe0b26fbc335c0f4cc
plan_head_after: d21bdf1fab1d227436d06a857edc58d0fac1ca96

tech-stack:
  added: []
  patterns:
    - "Rationale tables are metadata outside the hash payload: the registry hashes strategy_id, strategy_version, parameter_set_id and [parameters] only"
    - "check_rationale never raises on a malformed entry (reports every problem, sorted); load_rationale is the strict ValueError reader"
    - "Test-only escape hatch as a keyword argument; acceptance grep proves no module under src/ passes it"

key-files:
  created:
    - src/domain/rationale.py
    - tests/test_rationale.py
  modified:
    - src/paper/freeze.py
    - tests/test_paper_freeze.py
    - tests/test_cost_per_unit.py
    - tests/test_domain_no_float.py

key-decisions:
  - "Rationale values compare numerically through Decimal for int/Decimal parameters ('1.0' matches int 1) and exactly for string parameters; a non-finite or unparseable recorded value is its own problem"
  - "ref rules: EXPERIMENT needs a non-empty ref; DECISION and COST_GUARD need re.fullmatch(D\\d{3}); STRUCTURAL and PLACEHOLDER need none"
  - "The rationale gate runs in pin_stream_epoch right after the set is loaded and before the cost model is built, so a refused set never reaches the epoch"

patterns-established:
  - "Cross-test helpers live in the test module that owns the concept (tests/test_rationale.py write_set, write_rationalized_set) and are imported by tests/test_paper_freeze.py"

requirements-completed: [STRAT-02]

duration: 40min
completed: 2026-10-06
status: complete
---

# Phase 15 Plan 02: Machine-Checked Parameter Rationale Summary

**In-file `[rationale.<key>]` tables with a five-basis vocabulary (STRUCTURAL, COST_GUARD, DECISION, EXPERIMENT, PLACEHOLDER), validated by `check_rationale`, hash-neutral on all 20 committed sets, and enforced at the paper freeze: `pin_stream_epoch` raises `UnrationalizedParameterSet` for a missing or incomplete rationale or any PLACEHOLDER key.**

## TDD record

The plan is `type: tdd`; each task produced a RED commit then a GREEN commit.

**Task 1 (tracer)**
- RED `e1ea921`: tests for hash neutrality, clean check, missing entry, extra entry, placeholder_keys, and four `pin_stream_epoch` cases (pins a fully rationalized set, refuses a PLACEHOLDER key and names it, refuses a set with no rationale, pins a legacy set with the flag). The RED commit carries a skeleton `rationale.py` (empty results) and the unused `allow_unrationalized` parameter so the tests import and fail on assertions. Failing targets: `test_check_rationale_reports_missing_entry`, `..._every_key_when_no_rationale_at_all`, `..._reports_extra_entry`, `test_placeholder_keys_returns_sorted_placeholder_keys`, `test_pin_stream_epoch_refuses_placeholder_key_and_names_it`, `test_pin_stream_epoch_refuses_set_without_rationale` (6 failed, assertion failures, rest passed).
- GREEN `3237308`: `check_rationale` (missing and extra), `placeholder_keys`, `_require_rationalized` in freeze.py, `allow_unrationalized: bool = False` and the extended Raises docstring.
- Tracer gate: the three target test files re-ran green (130 tests) before Task 2 expanded the rules.

**Task 2**
- RED `33df988`: one test per rule (empty text, unknown basis, missing basis, non-string value, value mismatch, equal numeric spelling, unparseable numeric, exact string compare, EXPERIMENT ref, DECISION/COST_GUARD D-number across five bad refs, no-ref bases, sorted output, `load_rationale`) plus hash neutrality over every pin of `tests/fixtures/phase4/parameters.json`. 10 failed on assertions for the targeted rules. `src/domain/rationale.py` joined `SCANNED_FILES` in `tests/test_domain_no_float.py`.
- GREEN `d21bdf1`: per-entry validation (`_entry_problems`, `_value_problem`), `D\d{3}` ref rule, sorted deterministic output.

The `gsd_run check tdd-red-evidence` verb only parses node:test TAP and Surefire XML, so it cannot classify pytest output; RED evidence is recorded above by failing test name and failure kind instead (see Deviations).

## Accomplishments

- `src/domain/rationale.py`: pure stdlib (re, tomllib, decimal, pathlib, dataclasses) plus the registry parse path, float-free, in the no-float scan.
- `check_rationale` reports: missing entry per parameter key, entry for a key not in `[parameters]`, missing/non-string basis, unknown basis, non-string value, empty text, recorded value differing from the parsed parameter, EXPERIMENT without ref, DECISION or COST_GUARD without a D-number ref (Pitfall 6).
- `pin_stream_epoch` is strict by default (T-15-02); only legacy test pins pass `allow_unrationalized=True` (T-15-04): `grep -rn "allow_unrationalized=True" src` prints nothing.
- The hash-neutrality test appends a complete PLACEHOLDER rationale block to a tmp copy of each of the 20 committed sets and calls `verify_parameter_set` against the pinned hash; it asserts the count checked equals the number of pins (T-15-03: a value edit without a rationale edit is reported).
- No file was created under `params/`; all sets are written into pytest `tmp_path` registries.

## Task Commits

1. Task 1 RED: `e1ea921` test(15-02): add failing tests for rationale check and freeze refusal
2. Task 1 GREEN: `3237308` feat(15-02): refuse unrationalized and PLACEHOLDER sets in pin_stream_epoch
3. Task 2 RED: `33df988` test(15-02): add failing tests for remaining rationale rules and hash neutrality
4. Task 2 GREEN: `d21bdf1` feat(15-02): complete rationale rules (basis, value, ref) in check_rationale

## Deviations from Plan

### Non-code notes

**1. [Process] RED evidence not run through `gsd_run check tdd-red-evidence`**
- The verb classifies node:test TAP / Surefire XML only; pytest output would always be INVALID_RED (`no_target_test_failure`). The RED failures were instead verified by hand to be assertion failures on the target tests, not import, collection or fixture errors (the first collection error was fixed by adding the skeleton before committing RED).

**2. [Scope-neutral] Skeleton in the RED commit**
- The RED commit includes a no-op `rationale.py` and the unused flag so the test module imports. This is the smallest way to get an assertion-level RED and is replaced in GREEN.

Otherwise the plan was executed as written. The `value` field recorded for a numeric parameter is the string form of the normalized parameter (for example "2" for `minimum_rr = 2.0`); `"2.0"` is accepted as equal.

## Verification

- `pytest tests/test_rationale.py tests/test_paper_freeze.py tests/test_cost_per_unit.py tests/test_domain_no_float.py`: all pass (148 tests).
- `ruff check src tests scripts`: clean; `ruff format --check src tests scripts`: 378 files already formatted; `mypy src`: no issues in 148 files.
- Broader run of `tests/` (excluding `tests/test_deploy_backup_scripts.py` and `tests/test_docker*`, see below): no failure observed.

**Environment issue, not caused by this plan:** `tests/test_deploy_backup_scripts.py` and `tests/test_docker_backup_remote.py` abort the whole pytest process on this Windows machine with `Windows fatal exception: access violation` (no code in this plan is reachable from them). They were excluded from the broader run. Logged here rather than fixed (out of scope).

## Regeneration inventory

No hash, fixture, pin, signal id or parameter set moved. Legacy call sites that now pass `allow_unrationalized=True` (their intent, pinning a legacy set with no rationale tables, is unchanged):

- `tests/test_paper_freeze.py`: 6 call sites (`test_pin_stream_epoch_returns_pinned_tuple_on_clean_registry`, `test_pin_stream_epoch_raises_cost_model_binding_mismatch_on_mismatch`, `test_check_registry_unchanged_appends_clean_entry_and_keeps_epoch`, `test_check_registry_unchanged_opens_new_epoch_on_diff`, `test_pin_stream_epoch_propagates_keyerror_for_missing_cost_keys`, `test_cli_check_appends_clean_diff_log_entry`).
- `tests/test_cost_per_unit.py`: 2 call sites in `test_freeze_v5_set_pins_and_refuses_seven_key_model`.

## Known Stubs

None.

## Threat Flags

None. The change adds a refusal path and a metadata parser; no network, auth or schema surface. T-15-02, T-15-03, T-15-04 are mitigated by tests; T-15-SC accepted (no installs).

## Self-Check: PASSED

- FOUND: src/domain/rationale.py, tests/test_rationale.py
- FOUND: commits e1ea921, 3237308, 33df988, d21bdf1
- `grep -q "allow_unrationalized: bool = False" src/paper/freeze.py` ok; `grep -rn "allow_unrationalized=True" src` empty; `"src/domain/rationale.py"` present in `tests/test_domain_no_float.py`
