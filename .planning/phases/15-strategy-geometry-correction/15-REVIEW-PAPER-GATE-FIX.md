---
phase: 15-strategy-geometry-correction
fixed_at: 2026-10-07T00:00:00Z
review_path: .planning/phases/15-strategy-geometry-correction/15-REVIEW-PAPER-GATE.md
iteration: 1
findings_in_scope: 5
fixed: 5
skipped: 0
status: all_fixed
---

# Phase 15: Code Review Fix Report (plan 15-17 paper-start gate)

**Fixed at:** 2026-10-07
**Source review:** .planning/phases/15-strategy-geometry-correction/15-REVIEW-PAPER-GATE.md
**Iteration:** 1

**Summary:**
- Findings in scope: 5 (WR-01..WR-05; Info items IN-01..IN-05 not touched by instruction)
- Fixed: 5
- Skipped: 0

Verification ran in the main checkout (`workflow.use_worktrees` is false, no worktree was created), so the numbers are reproducible from the current tree on branch `develop`.

TDD order: WR-01, WR-02, WR-04 and WR-05 each have a failing-test commit followed by the fix commit. WR-03 is test-only (the gate already precedes the parsing); it has no failing-first commit, and instead was verified by mutation (see below).

## Fixed Issues

### WR-01: Any truthy `allow_unrationalized` disables the gate

**Files modified:** `src/paper/freeze.py`, `src/paper/loop.py`, `tests/test_paper_start_gate.py`
**Commits:** test `97cf55c`, fix `0df34a7`
**Status:** fixed: requires human verification (logic change in a fail-closed gate)
**Applied fix:** New `require_bool_flag` in `src/paper/freeze.py` raises `TypeError` for any non-bool. `pin_stream_epoch` calls it first and bypasses the gate only on `allow_unrationalized is True`. `run_paper_tick` calls it before reading any `case_input` field. Valid calls (True and False) behave as before. Tests cover `"False"`, `"0"`, `"no"`, `"yes"`, `""`, `1`, `0`, `1.0`, `None`, `[]`, `["x"]` for both entry points, plus True/False behaviour.

### WR-02: The AST guard has verified blind spots

**Files modified:** `tests/test_paper_start_gate.py`
**Commits:** test `69eae7f`, fix `6a12634`
**Status:** fixed: requires human verification (guard logic)
**Applied fix:** `_scan_src_violations` now reports a keyword `allow_unrationalized` whose value is anything but the literal `False`, with one exception: `run_paper_tick` in `paper/loop.py` forwarding its own parameter by name (tracked through an enclosing-function visitor). That closes int and string literals, `not False`, bound names, call results, and the own-name form in any other function. `_bound_names` now also covers walrus, for, comprehension and with targets, def, class, except-as, and `globals()["NAME"] = ...`. The allowlist check also reports the name as a keyword argument (`globals().update(NAME=...)`) or as a string. The docstring states what stays uncovered (runtime-built names, `**kwargs` forwarding, tuple content). Seeded cases added for each form, plus an allowed-form case. The real `src/` scan still returns `[]`.
**Design note:** I did not make the scan require an empty tuple literal. Emptiness stays asserted by `test_production_allowlist_is_empty_by_user_decision` (and `test_kill_gate_docs`), as the review itself judged acceptable; making the scan enforce it would add a third place to edit when the user later approves an entry. The docstring now says this.

### WR-03: The refusal tests do not prove the "before any candle is parsed or feed event read" claim

**Files modified:** `tests/test_paper_start_gate.py`
**Commit:** `179b925`
**Applied fix:** `SPIED_NAMES` extended with `_parse_account_state`, `_parse_constraint_snapshot`, `_parse_open_positions`, `_coerce_money`, `build_cost_model`, `assert_sizing_costs_bind_registry`, `check_feature_validity`, `check_feed_freshness`. New tests: a recording `case_input` proves a refused set (baseline-v3 empty allowlist, baseline-v6 PLACEHOLDER) reads only `strategy_id`, `strategy_version`, `parameter_set_id` and `now_utc`; and a refused set raises `UnrationalizedParameterSet` (not `KeyError`) when every other field is missing. Mutation check: temporarily parsing `account_state` above the gate made 8 tests fail; the mutation was reverted with `git checkout`.

### WR-04: The public gate entry `pin_stream_epoch` does not validate registry path segments

**Files modified:** `src/paper/freeze.py`, `tests/test_paper_start_gate.py`
**Commits:** test `7c94a01`, fix `a097370`
**Applied fix:** `_check_registry_segment` (from `src/domain/registry.py`) now runs on both ids at the top of `_load_parameter_set_with_root` (via the shared reader after WR-05) and `_recompute_parameter_set_hash`, raising `UnregisteredParameterSet`. Tests: a traversing `parameter_set_id` that resolves to a real file outside the registry (it previously loaded), unsafe segments (`../x`, `a/b`, `a\b`, empty, NUL, absolute) for `pin_stream_epoch`, and `_recompute_parameter_set_hash`.

### WR-05: The rationale verdict and the hash come from different reads of the file

**Files modified:** `src/paper/freeze.py`, `src/domain/rationale.py`, `tests/test_paper_start_gate.py`
**Commits:** test `80b671a`, fix `128a4d4`
**Applied fix:** `pin_stream_epoch` reads the set file once through new `_read_registry_file` (segment check, existence check, one `read_bytes`) and threads the text through `_parameter_set_from_text`, `_has_rationale_tables(text)` and `_require_rationalized(path, text, ...)`. `src/domain/rationale.py` gained `check_rationale_text` and `placeholder_keys_text`; `check_rationale(path)` and `placeholder_keys(path)` keep their signatures and now read once and delegate. The test stubs `Path.read_bytes` so the first read returns content A (no rationale, allowlisted by its hash) and later reads return B (incomplete rationale); it asserts exactly one read and a pinned hash equal to A's.
**Left open (IN-05, out of scope):** the loop's own `load_parameter_set` still reads `registry.REGISTRY_ROOT` separately, and the loop's hash-equality check remains the guard between the two roots.

## Skipped Issues

None.

## Verification

Run in the main checkout, one test file per process, all green:

| File | Result |
|------|--------|
| tests/test_paper_start_gate.py | 70 passed (16 before) |
| tests/test_paper_freeze.py | 10 passed |
| tests/test_paper_parity.py | 5 passed |
| tests/test_paper_closed_candle.py | 5 passed |
| tests/test_paper_feed_gates.py | 5 passed |
| tests/test_paper_reviewfix_pins.py | 9 passed |
| tests/test_rationale.py | 34 passed |
| tests/test_kill_gate_docs.py | 12 passed |
| tests/test_decision_alignment_params.py | 58 passed |

`ruff check`: clean. `ruff format --check`: 428 files already formatted. `mypy src`: no issues in 149 source files. Docker/PostgreSQL tests were not run (CI-only).

Constraints kept: no change to `params/`, `tests/fixtures/` or any pinned digest; `PAPER_START_ALLOWLIST` stays `()`; `src/` never sets `allow_unrationalized=True`; no backtest, census or research run. `.planning/config.json`, `.planning/state.json`, `.gsd/` and `.planning/milestone.lock` were never staged. This report is not committed.

---

_Fixed: 2026-10-07_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
