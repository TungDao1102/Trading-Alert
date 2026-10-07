---
phase: 15-strategy-geometry-correction
plan: 17
subsystem: paper
tags: [paper-start-gate, rationale, placeholder, allowlist, gap-closure, G-15-11]
status: complete

requires:
  - phase: 15-strategy-geometry-correction
    provides: pin_stream_epoch rationale/PLACEHOLDER gate and check_rationale (15-02), the five rationalized Phase 15 sets
provides:
  - run_paper_tick stream-start gate at the top of the function, before any candle is parsed
  - PaperAllowlistEntry and the empty PAPER_START_ALLOWLIST (exact-hash rule for sets without rationale tables)
  - AST guards keeping the test-only flag and the allowlist out of src/ runtime
affects: [phase-16 paper runtime, D054]

actuals:
  tokens: 10900
  tasks: 3
  commits: 5
plan_head_before: cd773efe3f574ecfa678ba0e9fe6d198ebac0fa2
plan_head_after: a35558cc77cf99a0f568faa823542a8de366f41d

tech-stack:
  added: []
  patterns: ["fail-closed gate at function entry", "exact-hash allowlist read at call time", "AST guard with seeded-violation controls"]

key-files:
  created:
    - tests/test_paper_start_gate.py
  modified:
    - src/paper/loop.py
    - src/paper/freeze.py
    - tests/test_paper_parity.py
    - tests/test_paper_closed_candle.py
    - tests/test_paper_feed_gates.py
    - tests/test_paper_reviewfix_pins.py

key-decisions:
  - "Checkpoint 15-17-01 (user, 2026-10-07, Option B): a set without rationale tables may start a paper stream only through an exact-hash PAPER_START_ALLOWLIST entry; the allowlist ships empty; D-27 unchanged"
  - "The gate runs in run_paper_tick before any candle is parsed; refusal is UnrationalizedParameterSet (no new RejectionReason)"
  - "pin_stream_epoch is called without cost_model: the strict 07.1 binding also compares partial_fill_fraction, which assert_sizing_costs_bind_registry deliberately excludes"

requirements-completed: [STRAT-01, STRAT-02]

duration: 6 min
completed: 2026-10-07
---

# Phase 15 Plan 17: Paper start gate wired into run_paper_tick Summary

`run_paper_tick` now runs the rationale/PLACEHOLDER gate (`pin_stream_epoch`) at its very top, before any candle is parsed, so a set with a missing rationale or a PLACEHOLDER key cannot start a paper stream; sets without rationale tables need an exact-hash entry in `PAPER_START_ALLOWLIST`, which ships empty by the user's decision (closes G-15-11).

## Decision on older parameter sets

Decided-by: user (verbatim replies 2026-10-07)

Checkpoint: 15-17-01 (asked and answered in the planning conversation, before execution)

Reply 1 (verbatim):

~~~text
B — chỉ cho phép các tập tham số được chỉ định đích danh và gắn với hash của từng tập.
Không cho phép mọi tập thiếu rationale tự động chạy paper.
Các tập mới của Phase 15 hiện vẫn phải bị reject cho tới khi có authorization/rationale phù hợp.
Giữ cơ chế fail-closed: run_paper_tick phải từ chối ngay trước khi đọc candle nếu parameter set không nằm trong allowlist được phê duyệt.
~~~

Reply 2 (verbatim):

~~~text
đồng ý cả hai, sửa plan 15-17 và chạy lại checker
~~~

Context for Reply 2 (Claude's words, not the user's): after Reply 1, Claude proposed two things and Reply 2 accepts both. (1) Amend plan 15-17: the allowlist is an exact parameter-set identity list (each entry: strategy_id, parameter_set_id, full 64-hex parameter_set_hash, purpose, approved_at, basis; the only pass decision is an exact match of the hash computed from the parameter file through the registry; ids are lookup only), it applies only to sets with no rationale tables, the gate runs in run_paper_tick before any candle is parsed, and a test proves the non-empty allowlist branch. (2) The allowlist is empty at this time and D-27 is not changed: the five Phase 15 sets stay refused and cannot be admitted through the allowlist.

Plain reading (Claude's words): Option B. A set without rationale tables may start a paper stream only if the approved allowlist names it by strategy_id and parameter_set_id with its exact parameter_set_hash. The allowlist is empty at 2026-10-07, so all 20 older sets are refused as not in the approved allowlist; this is the decided safe state, not a fault. Sets with rationale tables always get the full rationale and PLACEHOLDER check, so the five Phase 15 sets stay refused (D-16, D-27 unchanged). Today no committed set can start a paper stream. Phase 16 can start a paper stream only after a new fully rationalized set with no PLACEHOLDER key exists, or after a new user checkpoint adds an exact-hash entry.

## Accomplishments

- Gate at the top of `run_paper_tick` (src/paper/loop.py): reads the three ids, parses `now_utc`, loads the set, checks `strategy_version`, calls `pin_stream_epoch` (no `cost_model`, no `registry_root`) and requires the gate's `parameter_set_hash` to equal the loaded set's (ValueError otherwise). `_parse_candle`, `_is_closed_event`, `evaluate`, `plan` and `evaluate_risk` are never reached for a refused set. Keyword-only `allow_unrationalized=False` on `run_paper_tick`, passed through by name.
- `PaperAllowlistEntry` (frozen, six str fields) and `PAPER_START_ALLOWLIST: tuple[PaperAllowlistEntry, ...] = ()` in src/paper/freeze.py. `_require_rationalized` takes the ids and the computed hash: no top-level `rationale` key (tomllib) means the allowlist is consulted (read at call time) and only an exact hash match admits; a rationale key (even empty or malformed) always gets the full `check_rationale` + `placeholder_keys` check. The empty-allowlist refusal says "missing rationale tables", "not in the approved allowlist" and "the approved allowlist is empty (checkpoint 15-17-01, Option B) ... the decided safe state, not a system fault". No import-time check, log or warning.
- `tests/test_paper_start_gate.py` (16 tests): refusal with zero candle/engine calls (spies), empty branch, decision record, PLACEHOLDER set (baseline-v6), injected exact match (digest equals clean_run expected and the flagged run), injected hash mismatch, neighbouring id not matched, injected entry never admits a set with rationale tables (baseline-v6 and a tmp set with a missing entry), fully rationalized tmp set runs without the flag with the same digest, hash guard (patched registry root), fresh-interpreter import with `-W error`, AST guards with seeded controls, signature, pass-through and entry-shape tests.
- Existing test call sites pass the test-only keyword (parity `_replay_paper_through_bars`, 6 + 6 + 4 direct calls); no fixture, params file or pinned digest changed.

## Task Commits

1. Task 1: `9c56347` docs(15-17) - verbatim decision record, Option B.
2. Task 2 RED: `b02e47e` test(15-17) - all 10 gate tests failed before the src change (ImportError on `PAPER_START_ALLOWLIST`, TypeError on the new keyword, no refusal raised): `test_empty_allowlist_refuses_set_without_rationale_before_any_candle`, `test_production_allowlist_is_empty_by_user_decision`, `test_placeholder_set_is_refused_before_any_candle`, `test_injected_exact_hash_match_lets_a_set_without_rationale_run`, `test_injected_hash_mismatch_is_refused`, `test_injected_entry_does_not_match_a_neighbouring_set_id`, `test_injected_entry_never_admits_a_set_that_has_rationale_tables`, `test_fully_rationalized_set_runs_without_the_flag`, `test_gate_and_loop_must_judge_the_same_file`, `test_import_with_the_empty_allowlist_emits_no_error_or_warning`.
3. Task 2 GREEN: `df7e9c8` feat(15-17) - gate, allowlist, call-site keyword. All four call-site files were edited because the empty allowlist refuses baseline-v3 and the gate refuses baseline-v6.
4. Task 3 RED: `da512e2` test(15-17) - three guard tests failed with `NameError: name '_scan_src_violations' is not defined` before the helper existed.
5. Task 3 GREEN: `a35558c` feat(15-17) - AST helper, signature/pass-through/entry-shape tests, freeze.py docstrings.

## Verification

- One pytest process per file, all passed: test_paper_start_gate (16), test_paper_parity, test_cost_parity, test_paper_closed_candle, test_paper_feed_gates, test_paper_reviewfix_pins, test_paper_freeze, test_rationale, test_cost_per_unit, test_domain_no_float, test_kill_gate_docs, test_decision_alignment_params.
- `ruff check src tests`, `ruff format --check src tests` clean; `mypy src` clean (149 files).
- Acceptance: `pin_stream_epoch` call at loop.py line 351, before both warm-up `_parse_candle` lines (373-374) and the feed-event loop (410); the call has no `cost_model` and no `registry_root`; `PAPER_START_ALLOWLIST: tuple[PaperAllowlistEntry, ...] = ()` count 1; `git grep -E "allow_unrationalized\s*=\s*True" -- src` empty; the flag appears only in src/paper/freeze.py and src/paper/loop.py; the allowlist name appears only in src/paper/freeze.py; `git status --porcelain -- tests/fixtures params` empty; test_paper_freeze.py not edited; Task 1 decision-record check passed before Task 2.
- CI-only (not run): PostgreSQL, docker, bootstrap and deploy tests.

## Limits of the guard

The AST scan cannot see a name built at runtime (string concatenation, writes through `vars()` or a module `__dict__`). The immutable tuple of frozen dataclasses prevents in-place extension, and code review covers the rest (accepted residual of T-15-38).

## Deviations from Plan

None - plan executed exactly as written. (The commit trailer names Claude Sonnet 5.5, per the dispatching instruction, where the plan text names Opus 5.5.)

## Known Stubs

None.

## Threat Flags

None.

## Notes for Phase 16

No committed parameter set can start a paper stream today: the five Phase 15 sets have PLACEHOLDER keys and the 20 older sets are not in the empty allowlist. The Phase 16 runtime needs a new fully rationalized set with no PLACEHOLDER key, or a new user checkpoint that adds an exact-hash allowlist entry (with a D054 update and an update of `test_production_allowlist_is_empty_by_user_decision`).

## Self-Check: PASSED

- src/paper/loop.py, src/paper/freeze.py, tests/test_paper_start_gate.py and the four call-site test files exist and are committed (9c56347, b02e47e, df7e9c8, da512e2, a35558c found in git log).
- All acceptance criteria and plan-level verification re-run and passing.
