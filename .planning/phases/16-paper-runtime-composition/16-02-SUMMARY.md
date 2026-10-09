---
phase: 16-paper-runtime-composition
plan: 02
subsystem: paper-gate / freeze
tags: [paper-start-gate, allowlist, registry-root, review-fixes, determinism]

requires:
  - phase: 15-strategy-geometry-correction
    provides: "paper-start gate (pin_stream_epoch, PaperAllowlistEntry, empty allowlist) and its review 15-REVIEW-PAPER-GATE.md"
provides:
  - "PaperAllowlistEntry.__post_init__: a malformed user allowlist entry fails at construction naming the field"
  - "resolve_registry_root() and load_parameter_set_at_root() in src/paper/freeze.py: the registry root is resolved at call time, never bound at import"
  - "run_paper_tick resolves the root once, loads the set from it and hands the same root to pin_stream_epoch"
  - "tests/test_paper_allowlist_entry.py and tightened tests/test_paper_start_gate.py"
affects: [16-09 freeze CLI allowlist mode, 16-22 runtime composition]

actuals:
  tokens: 6000
  tasks: 2
  commits: 3
plan_head_before: 3b46a7f5ba88892b8e15395e6938805717aa07f5
plan_head_after: e9eaf03f7c239de5dbc1a7abb520094ab4f439fa
commits: 3

tech-stack:
  added: []
  patterns:
    - "Registry root read from the registry module at call time through one helper; no import-time copy of a mutable module global"
    - "Gate and loop share one resolved root, with the loop's hash-equality check kept as a fail-closed backstop"

key-files:
  created:
    - tests/test_paper_allowlist_entry.py
  modified:
    - src/paper/freeze.py
    - src/paper/loop.py
    - tests/test_paper_start_gate.py

key-decisions:
  - "The registry root is resolved once per run_paper_tick call and passed to pin_stream_epoch; the loop loads the set through freeze.load_parameter_set_at_root instead of registry.load_parameter_set so both read the same root by construction"
  - "The strategy_version ValueError keeps running before the rationale gate; the order is documented as a contract, not changed (D-02: no exception type or digest moves)"
  - "check_registry_unchanged also resolves the root at call time (it shared the import-time binding)"

requirements-completed: [PAPER-01]

coverage:
  - id: D1
    description: "A PaperAllowlistEntry with a malformed hash, blank id, non-ISO approved_at, blank purpose or basis, or a non-str field cannot be constructed; PAPER_START_ALLOWLIST stays ()"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_allowlist_entry.py#test_a_malformed_field_raises_value_error_naming_the_field"
        status: pass
      - kind: unit
        ref: "tests/test_paper_allowlist_entry.py#test_a_non_str_field_raises_type_error_naming_the_field"
        status: pass
      - kind: unit
        ref: "tests/test_paper_start_gate.py#test_production_allowlist_is_empty_by_user_decision"
        status: pass
    human_judgment: false
  - id: D2
    description: "The gate and the loop judge the same registry file: the verdict follows registry.REGISTRY_ROOT in both directions, a stale module binding cannot decide it, and the loop hands the gate the root it loaded from"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_start_gate.py#test_gate_and_loop_resolve_one_registry_root"
        status: pass
      - kind: unit
        ref: "tests/test_paper_start_gate.py#test_pin_stream_epoch_resolves_the_registry_root_at_call_time"
        status: pass
      - kind: unit
        ref: "tests/test_paper_start_gate.py#test_run_paper_tick_hands_the_gate_the_root_it_loaded_from"
        status: pass
    human_judgment: false
  - id: D3
    description: "run_paper_tick output and every pinned paper digest are byte-identical before and after"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_parity.py, tests/test_paper_reviewfix_pins.py, tests/test_paper_feed_gates.py, tests/test_paper_closed_candle.py (unedited, 148 tests across the six files pass)"
        status: pass
    human_judgment: false

duration: 21min
completed: 2026-10-09
status: complete
---

# Phase 16 Plan 02: Paper gate review fixes (G4-018) Summary

**`PaperAllowlistEntry` now validates every field at construction, and `run_paper_tick` resolves the registry root once so the paper-start gate and the loop read the same file; docstrings now match behaviour and no pinned digest moved.**

## Performance

- **Duration:** 21 min (2026-10-09T03:05:31Z to 03:26:29Z)
- **Tasks:** 2 (Task 1 tracer, Task 2 auto, both TDD)
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments

- Tracer (IN-01): `PaperAllowlistEntry.__post_init__` raises `TypeError` for a non-str field and `ValueError` naming the field for a hash that is not exactly 64 lowercase hex characters, a blank `strategy_id`, `parameter_set_id`, `purpose` or `basis`, and an `approved_at` that is not a real `YYYY-MM-DD` date (compact `20261008`, a timestamp or `2026-02-30` are refused). `PAPER_START_ALLOWLIST` is still the single empty tuple literal and `test_production_allowlist_is_empty_by_user_decision` is untouched.
- IN-05: the import-time `REGISTRY_ROOT` binding in `src/paper/freeze.py` is gone. `resolve_registry_root()` reads `src.domain.registry.REGISTRY_ROOT` at call time; `pin_stream_epoch` and `check_registry_unchanged` use it. `run_paper_tick` resolves the root once, loads the set through `load_parameter_set_at_root` and passes the same root as `registry_root=` to `pin_stream_epoch`. The loop's hash-equality check remains as a backstop and has its own test.
- IN-02 and IN-03: `run_paper_tick` docstring no longer claims "no I/O", states that the outcome depends on the registry files and the allowlist, and has a `Raises:` section (TypeError, UnregisteredParameterSet, ValueError including the strategy_version-before-rationale order contract, UnrationalizedParameterSet, KeyError). The `loop.py` module docstring lists the real imports. "Stream-start gate" became "per-call gate" in the code, the error message and the test header, with a note that the runtime (plan 16-22) adds a once-per-process start gate and pins the epoch once.
- IN-04: the redundant `freeze.REGISTRY_ROOT` patches are removed; the seeded-violation test ties every message to its own path; an empty `[rationale]` table and a scalar `rationale = "x"` are tested on the allowlist-versus-rationale branch (an exact-hash allowlist entry does not admit them); the import test also asserts the allowlist prints as `()`; `test_fully_rationalized_set_runs_without_the_flag` now says that the digest equality with the flagged run is the real assertion.

## RED Evidence

- **Task 1** (`08fab1c`, tests only) against the unchanged `PaperAllowlistEntry`: every malformed-field case and every non-str case failed (`Failed: DID NOT RAISE TypeError`, and the ValueError cases likewise); the valid-construction and empty-allowlist tests passed. After `1febad4`: all of `tests/test_paper_allowlist_entry.py` plus `tests/test_paper_start_gate.py` pass (118 tests).
- **Task 2 (IN-05):** run against the pre-change `freeze.py` and `loop.py` (restored from `HEAD`, with two shim functions appended so the new test module imports), `test_gate_and_loop_resolve_one_registry_root`, `test_pin_stream_epoch_resolves_the_registry_root_at_call_time` and `test_run_paper_tick_hands_the_gate_the_root_it_loaded_from` failed; the working-tree files were then restored from a scratch copy and all pass. The pre-change gate read `params/` through its import-time root while the loop read the moved registry, in both directions (a rich-rationale file refused, a poor-rationale file waved through).
- The empty `[rationale]` and scalar `rationale` tests, and the tightened seeded-violation and import tests, characterise existing behaviour and pass before and after (no RED expected).

## Task Commits

1. **Task 1 (tracer): allowlist entry validation** - `08fab1c` (test, RED), `1febad4` (feat, GREEN)
2. **Task 2: single registry root, docstrings, test nits** - `e9eaf03` (fix)

**Plan metadata:** committed separately (docs: complete plan).

## Verification

- `.venv/Scripts/python -m pytest tests/test_paper_start_gate.py tests/test_paper_parity.py tests/test_paper_reviewfix_pins.py tests/test_paper_feed_gates.py tests/test_paper_closed_candle.py tests/test_paper_allowlist_entry.py -q -p no:cacheprovider`: 148 passed.
- Also green, one file per process: `test_paper_freeze` (10), `test_rationale` (34), `test_cost_per_unit` (113), `test_kill_gate_docs` (13), `test_domain_no_float` (3), `test_decision_alignment_params` (58), `test_paper_attribution` (16), `test_paper_notify` (6), `test_paper_resync` (6), `test_paper_supervisor_backfill` (16).
- `ruff check`, `ruff format --check` (432 files) and `mypy src` (149 files) are clean.
- `git diff 3b46a7f -- tests/test_paper_parity.py tests/test_paper_reviewfix_pins.py tests/test_paper_feed_gates.py tests/test_paper_closed_candle.py` is empty (no expected digest edited). `git diff 3b46a7f -- src/paper/freeze.py tests/test_paper_start_gate.py` shows no change to the `PAPER_START_ALLOWLIST` literal and none to `test_production_allowlist_is_empty_by_user_decision`.
- A full `pytest -m "not docker"` run in one process was started and aborted on the 10 minute tool limit (faulthandler stack dump, no test failure reported); the targeted suites above replace it. This is an environment limit, not a plan finding.

## WR-01..WR-05 Re-check (Phase 15 review)

Checked against `15-REVIEW-PAPER-GATE-FIX.md` and against the code at execution time: WR-01 (`require_bool_flag`, gate bypass only on `is True`), WR-02 (AST guard extended), WR-03 (spied names extended, recording `case_input` test), WR-04 (`_check_registry_segment` in the shared reader and `_recompute_parameter_set_hash`), WR-05 (single `read_bytes`, text threaded through) are all applied with tests. **WR-01..WR-05 applied, nothing folded.**

## Decisions Made

- Public `load_parameter_set_at_root` is a thin wrapper over `_load_parameter_set_with_root` so `src/paper/loop.py` does not import a private name, while the existing tests that import the private name keep working.
- `check_registry_unchanged` also moved to call-time root resolution because it shared the same stale binding; its tests pass an explicit root and are unaffected.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Existing tests depended on the removed `freeze.REGISTRY_ROOT`**
- **Found during:** Task 2
- **Issue:** `tests/test_paper_start_gate.py` imported and monkeypatched `freeze.REGISTRY_ROOT` (`_production_hash`, two tests) and `test_run_paper_tick_passes_its_own_flag_through_by_name` required that `run_paper_tick` pass no `registry_root`. Removing the import-time binding and passing the root (the plan's own IN-05 change) broke them.
- **Fix:** `_production_hash` uses `REPO_ROOT / "params"` (the tests that call it move the registry root); the redundant patches are gone (IN-04); the pass-through test now asserts the exact keyword set `{strategy_id, parameter_set_id, opened_at_utc, registry_root, allow_unrationalized}`.
- **Files modified:** tests/test_paper_start_gate.py
- **Committed in:** e9eaf03

**2. [Rule 1 - Premise no longer holds] `test_gate_and_loop_must_judge_the_same_file` rewritten**
- **Found during:** Task 2
- **Issue:** The test built two different files (tampered tmp registry versus `params/`) and expected the loop's hash-mismatch `ValueError`. With one resolved root that divergence is no longer reachable, so the test failed by design.
- **Fix:** It now asserts the gate pins the tampered file's hash (same file as the loop). The mismatch `ValueError` backstop keeps its own test using a gate stub that returns a different hash, asserting no candle work happens.
- **Files modified:** tests/test_paper_start_gate.py
- **Committed in:** e9eaf03

**3. [Rule 1 - Bug in own change] Docstring tripped the allowlist guard**
- **Found during:** Task 2
- **Issue:** My first `run_paper_tick` docstring named `PAPER_START_ALLOWLIST`, which `_scan_src_violations` forbids outside `src/paper/freeze.py`.
- **Fix:** Reworded to "the approved paper-start allowlist of `src/paper/freeze.py`".
- **Files modified:** src/paper/loop.py
- **Committed in:** e9eaf03

### Plan notes (not defects)

- The plan asked to correct a stale line citation in `_load_parameter_set_with_root`; the WR-05 rewrite had already removed it, so only the docstring wording was brought up to date.
- Files in the working tree are CRLF (git `core.autocrlf=true`); the new test file is written with LF like other new files and git normalises it.

---

**Total deviations:** 3 auto-fixed (1 Rule 3, 2 Rule 1). **Impact:** all follow from the plan's own IN-05 change; no pinned digest, exception type or allowlist content moved.

## Issues Encountered

A first attempt to patch the test file through a scripted rewrite wrote real newlines into string literals (shell escaping of `\n`); it was caught by a collection SyntaxError before any commit and fixed with the Edit tool.

## Known Stubs

None.

## Threat Flags

None. T-16-04 (registry root divergence) is mitigated by the single call-time resolution plus `test_gate_and_loop_resolve_one_registry_root`; T-16-05 (allowlist entry) is mitigated by `__post_init__` and the unchanged `_scan_src_violations` guard; T-16-SC accepted, no package installed and `uv.lock` unchanged.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 16-09 (freeze CLI allowlist mode) and plan 16-22 (runtime) can rely on `PaperAllowlistEntry` rejecting malformed entries and on `resolve_registry_root()` / `load_parameter_set_at_root()` for one-root semantics.
- The allowlist remains empty by the user's decision (checkpoint 15-17-01, Option B); any change still needs a new user checkpoint (O-13 / G4-021, plan 16-42).

---
*Phase: 16-paper-runtime-composition*
*Completed: 2026-10-09*

## Self-Check: PASSED

`tests/test_paper_allowlist_entry.py`, `src/paper/freeze.py`, `src/paper/loop.py`, `tests/test_paper_start_gate.py` and this SUMMARY exist; commits 08fab1c, 1febad4, e9eaf03 found in git log; 148 tests pass across the six plan files; ruff check, ruff format --check and mypy src clean.
