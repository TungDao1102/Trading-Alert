---
phase: 15-strategy-geometry-correction
plan: 18
subsystem: decisions
tags: [decision-log, D054, paper-start-gate, review-disposition, gap-closure, G-15-11]
status: complete

requires:
  - phase: 15-strategy-geometry-correction
    provides: paper-start gate and empty PAPER_START_ALLOWLIST (15-17), -v4 reference-point label (15-16)
provides:
  - D054 item (i) in docs/DECISIONS.md recording the paper-start gate and the user's older-set decision
  - doc test test_d054_records_the_paper_start_gate (also pins the allowlist as the empty tuple)
  - IN-01 marked fixed in 15-REVIEW-DISPOSITION.md (open 6 -> 5)
affects: [phase-16 paper runtime]

actuals:
  tokens: 2600
  tasks: 2
  commits: 3
plan_head_before: 64a6bc56da5021230b88ec23054428f9dfecfbaf
plan_head_after: 5d961c93495b1d53d5c24f0c3fbf41cef78e5cfc

tech-stack:
  added: []
  patterns: ["verbatim user decision copied into the canonical decision log and checked byte for byte"]

key-files:
  created: []
  modified:
    - docs/DECISIONS.md
    - tests/test_kill_gate_docs.py
    - .planning/phases/15-strategy-geometry-correction/15-REVIEW-DISPOSITION.md

key-decisions:
  - "No new decision: D054 item (i) moves the user's 2026-10-07 decisions (15-UAT.md test 11, checkpoint 15-17-01 Option B) from the 15-17 summary into the canonical log; the allowlist stays empty and D-27 is unchanged"

requirements-completed: [STRAT-02]

duration: 8 min
completed: 2026-10-07
---

# Phase 15 Plan 18: D054 paper-start gate record and closure sweep Summary

D054 item (i) now records where the paper-start gate runs (top of `run_paper_tick`, before any candle), the user's replies verbatim, Option B with its empty exact-hash allowlist and D-27 unchanged, and when Phase 16 can start a paper stream; IN-01 is fixed and a file-by-file sweep shows nothing else moved (closes G-15-11 in the decision log).

## Accomplishments

- D054 item (d) gained the pointer "recorded in item (i)"; item (i) was appended before the row's closing pipe. The row is still one line directly after D053 with no pipe inside a cell (`row.count("|") == 5`).
- Verbatim record (copied by script from the source files, then checked byte for byte): user reply to 15-UAT.md test 11, "Nối ngay trong Phase 15" (meaning: wire it now, in Phase 15); Reply 1 of checkpoint 15-17-01 (four lines, joined by " / " as the plan prescribes); Reply 2 ("đồng ý cả hai, sửa plan 15-17 và chạy lại checker"). Plain reading beside them: Option B, an exact-hash allowlist admits only sets without rationale tables, the allowlist is empty at 2026-10-07, D-27 unchanged so the five Phase 15 sets stay refused. Phase 16 can start a paper stream only after a new fully rationalized set with no PLACEHOLDER key exists or a new user checkpoint adds an exact-hash entry.
- `test_d054_records_the_paper_start_gate` pins the item (i) tokens (ASCII only), that item (i) holds no 64-hex string, and that `src.paper.freeze.PAPER_START_ALLOWLIST == ()`, so the doc and the code agree.
- 15-REVIEW-DISPOSITION.md: IN-01 `fixed` in the frontmatter and the table, source "15-17-SUMMARY.md (commits df7e9c8, a35558c)" (the Task 2 and Task 3 GREEN commits of 15-17), `open: 5`. No other finding touched.
- No allowlist entry was added; no file under params/, tests/fixtures/ or src/ was edited.

## Task Commits

1. Task 1 RED: `0e4d00d` test(15-18) - `test_d054_records_the_paper_start_gate` failed with `AssertionError: D054 row must mention '(i) Paper-start gate'` before the D054 edits (the other 11 tests in the file passed).
2. Task 1 GREEN: `549329b` docs(15-18) - D054 item (i) and the item (d) pointer.
3. Task 2: `5d961c9` docs(15-18) - IN-01 fixed, open count 5.

## Closure sweep

One pytest process per file, all passed on `5d961c9`:

| File | Result |
|------|--------|
| tests/test_paper_start_gate.py | 16 passed |
| tests/test_paper_parity.py | 5 passed |
| tests/test_cost_parity.py | 9 passed |
| tests/test_paper_closed_candle.py | 5 passed |
| tests/test_paper_feed_gates.py | 5 passed |
| tests/test_paper_reviewfix_pins.py | 9 passed |
| tests/test_paper_freeze.py | 10 passed |
| tests/test_paper_attribution.py | 16 passed |
| tests/test_rationale.py | 34 passed |
| tests/test_cost_per_unit.py | 113 passed |
| tests/test_registry.py | 167 passed |
| tests/test_registry_gate.py | 7 passed |
| tests/test_backtest_simulator.py | 63 passed |
| tests/test_backtest_determinism.py | 16 passed |
| tests/test_backtest_engine_strategy.py | 11 passed |
| tests/test_phase6_fixture_geometry.py | 119 passed |
| tests/test_domain_no_float.py | 3 passed |
| tests/test_decision_alignment_params.py | 58 passed |
| tests/test_decision_alignment_bookkeeping.py | 46 passed |
| tests/test_kill_gate_docs.py | 12 passed |
| tests/test_geometry_audit_doc.py | 20 passed |

Also: `python -m scripts.decision_alignment.params` PA-01..PA-08 all ok; `ruff check src tests scripts` clean; `ruff format --check src tests scripts` 389 files already formatted; `mypy src` no issues in 149 source files.

No-move check: `git diff --name-only 3df767a268a0339198c94a42524db23f8b0fa481..HEAD -- params tests/fixtures` (base = plan_head_before of 15-16) printed nothing, and `git diff --name-only 64a6bc5..HEAD -- src params tests/fixtures` (this plan) printed nothing.

CI-only, not run here: PostgreSQL (`TEST_DATABASE_URL`), docker, bootstrap and deploy tests.

## Deviations from Plan

**[Rule 3 - Formatting] RED test reformatted before its commit.** Found during: Task 1. `ruff format --check` flagged one over-length line in the new test; `ruff format` fixed only that file and the corrected test was committed as the RED commit. No behavior change. (The commit trailer names Claude Sonnet 5.5, per the dispatching instruction, where the plan text names Opus 5.5.)

**Total deviations:** 1 auto-fixed (formatting). **Impact:** none.

## Known Stubs

None.

## Threat Flags

None.

## Notes for Phase 16

No committed set can start a paper stream today (20 older sets: not in the empty allowlist; five Phase 15 sets: PLACEHOLDER keys, D-27 unchanged). Phase 16 needs a new fully rationalized set with no PLACEHOLDER key, or a new user checkpoint that adds an exact-hash entry together with a D054 update and an update of `test_production_allowlist_is_empty_by_user_decision`.

## Self-Check: PASSED

- docs/DECISIONS.md, tests/test_kill_gate_docs.py and 15-REVIEW-DISPOSITION.md edited and committed (0e4d00d, 549329b, 5d961c9 found in git log).
- Acceptance greps: `^| D054 |` 1, `(i) Paper-start gate` 1, `recorded in item (i)` 1, `legacy-set rule: option B` 1, `The allowlist is empty at 2026-10-07` 1, `IN-01 | info | fixed` 1, frontmatter `open: 5`; the verbatim-reply script printed "D054 replies verbatim ok".
