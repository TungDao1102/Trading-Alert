---
phase: 25-demo-integration-test-campaign
plan: 17
subsystem: phase-gate
tags: [D-05, D-14, gate, inventory, register, tdd, EXEC-01, EXEC-02, EXEC-03, APRV-01, APRV-02, OPS-01, OPS-02]
requires: [25-03, 25-04, 25-05, 25-06, 25-07, 25-09, 25-10, 25-11, 25-12, 25-13, 25-14, 25-15, 25-16]
provides:
  - "tests/test_phase25_gate.py: the Phase 25 structural gate (scenario structure, S20 rows, no new src/live module, REQUIREMENT_TESTS, DECISION_EVIDENCE, inventory check, register invariants)"
  - ".planning/phases/25-demo-integration-test-campaign/25-SCENARIO-INVENTORY.md: the S01-S20 coverage inventory"
  - ".planning/phases/25-demo-integration-test-campaign/25-DEFERRED.md: status of every inherited item, every finding F1.. and the smaller open points"
affects: [25-18, 25-19, 25-20, 25-21, 25-22, 25-23, 25-24, 25-25]
tech-stack:
  added: []
  patterns:
    - "every check is a function that takes a root, so a negative control runs it on a tmp_path copy and asserts the scenario id in the message"
    - "tests are resolved with ast and never imported or run from the gate; only the pure-data catalog is imported"
    - "register rows are parsed from the ROADMAP entry and the plan SUMMARYs, so a new inherited id or a new F-labelled finding fails the gate until it has a row"
key-files:
  created:
    - tests/test_phase25_gate.py
    - .planning/phases/25-demo-integration-test-campaign/25-SCENARIO-INVENTORY.md
    - .planning/phases/25-demo-integration-test-campaign/25-DEFERRED.md
  modified: []
key-decisions:
  - "Owner-open rows (R-21, R-22, D056, ERR1003-KEY, OWNER-4) are not pinned to a status in the gate, so the owner's later answers (plans 25-19 to 25-23) can move them without editing the gate; only the permanent statuses are pinned (P20-ERR1003 superseded, R-23 and R-28 deferred, R-24 and R-25 covered). A covered row must name the plan or scenario that covers it."
  - "Every finding F1.. of the plan summaries is an owner-open register row (id 25-NN-Fk), including observations and twin-fidelity notes, as the orchestrator asked; the register chooses nothing. The gate fails if a SUMMARY labels a finding with no row, or a finding row has no SUMMARY label."
  - "Every strict xfail twin test must be named in the register (parsed with ast from tests/test_demo_twin_s*.py): three today."
  - "The inventory expected-label column is the 25-RESEARCH catalog label refined by what each scenario module records; it is an expectation, never an observation, and the gate only checks the words are harness labels."
requirements-completed: []
estimate:
  tokens: 75000
actuals:
  tokens: 21700
  tasks: 3
  commits: 5
plan_head_before: d6ca0910409b3798786cba7d886525eec9ddb579
plan_head_after: b86f42863defc09b909baaca7c13d2637086771e
duration: 40min
completed: 2026-11-07
status: complete
---

# Phase 25 Plan 17: Phase 25 gate, scenario inventory and inherited-item register Summary

A structural gate that fails CI by scenario id when a catalog scenario loses its module, twin, REUSES target or demo mark, plus the S01-S20 inventory and a register that gives all twelve inherited ROADMAP items and all 20 summary findings a status without deciding any owner question.

## What was built

- `tests/test_phase25_gate.py` (about 1,300 lines, 65 collected tests). It asserts, with `ast` and no network:
  - each of S01-S19 has its module with a top-level `async def run`, a twin file with at least one test and a module-level `REUSES` tuple whose every `path::function` resolves to an existing function, and a demo file with at least one test and `pytestmark` holding `pytest.mark.demo`; no scenario-shaped file exists outside the catalog; all 20 `tests/demo/test_demo_s*.py` files carry the mark (T-25-42, next to the plan 25-01 guard);
  - S20 is covered by DEMO_VS_MAINNET.md rows for A2, A3, B2/B3, the 418 beyond 259200 s and the 429/418 queue order, the last two labelled NOT_OBSERVED;
  - the `src/live` module set still equals the Phase 24 `LIVE_MODULES` (no new live module) and live placement is still disabled;
  - `REQUIREMENT_TESTS`: EXEC-01, EXEC-02, EXEC-03, APRV-01, APRV-02, OPS-01 and OPS-02 each map to at least two ast-resolved tests; `DECISION_EVIDENCE`: D-01 to D-14 each map to a plan id with an existing `PLAN.md` and existing test functions or document anchors (D-09 to the evaluator tests until plan 25-24 adds the registration; D-14 to the CONTEXT decision and the R-23 and R-28 register rows);
  - the inventory has one row per catalog scenario and agrees with the catalog and the `REUSES` tuples;
  - the register has a row and a status for every ROADMAP Phase 25 inherited id, an owner-open row for every F-labelled finding, names every strict xfail twin, names only existing test files, and claims nothing mainnet-observed, host-observed or DEMO_OBSERVED without an evidence path.
- Negative controls on `tmp_path` copies: twin without REUSES, empty REUSES, REUSES naming a missing function or file, demo test without the mark (and a mark on one function only), module without `async def run`, missing files, scenario file outside the catalog, S20 rows missing or a 418 row claiming an observation, requirement and decision evidence missing, inventory drift (REUSES, labels, leaves_state, title, path), register status and finding drift, forbidden claims, and an unnamed strict xfail.
- `25-SCENARIO-INVENTORY.md`: 20 rows (id, title, twin test, demo test, REUSES, expected Demo labels, leaves_state), generated from the REUSES tuples and committed as text.
- `25-DEFERRED.md`: section A (12 inherited ids), A2 (ERR1003-KEY, OWNER-4), B (20 findings), C (7 smaller open points).

## Tasks and commits

| Task | Commit | What |
|---|---|---|
| 1 tracer | 1e4a27f0 | Gate: scenario structure, S20, live inventory, negative controls (green on the tree, red evidence is the negative controls) |
| 2 RED | f73a20ab | Requirement and decision maps and inventory check; inventory missing |
| 2 GREEN | 7d9d28a7 | 25-SCENARIO-INVENTORY.md |
| 3 RED | 64005355 | Register invariants; 25-DEFERRED.md missing (7 failures) |
| 3 GREEN | b86f4286 | 25-DEFERRED.md and the D-14 register anchors |

## Verification

- `uv run pytest -m "not docker"` on the 19 twin files, `tests/test_phase25_gate.py`, `tests/test_phase24_gate.py` and `tests/test_demo_marker_guard.py` (the plan's phase suite plus the Phase 24 gate): all passed, 3 xfailed (the strict xfails below).
- `tests/test_phase25_gate.py tests/test_demo_twin_s01_happy.py tests/test_demo_marker_guard.py` passed.
- Scoped `ruff check` and `ruff format --check` on the gate: clean. `uv run mypy src`: no issues in 291 files. `uv lock --check`: ok.
- `git diff --exit-code -- src scripts pyproject.toml uv.lock` exits 0 (no source, script or dependency change).
- The inventory acceptance one-liner (ids equal S01-S20) exits 0.
- No docs/ file was edited, so `verify_decision_alignment.py` was not needed.

## Twins still marked strict xfail (gap-closure items before the campaign)

Each holds a plan's desired behaviour that `src` does not do today; each is an owner decision with its own DECISIONS row (register section B):

1. `tests/test_demo_twin_s07_restart_cuts.py::test_cut_b_a_late_restart_close_lets_the_operator_leave_safe_mode` (25-12-F1)
2. `tests/test_demo_twin_s11_db_outage.py::test_after_the_database_returns_and_the_exit_a_new_request_is_placed` (25-14-F1)
3. `tests/test_demo_twin_s12_daily_stop.py::test_a_resting_entry_is_cancelled_at_daily_stop_and_the_alert_is_journaled` (25-15-F1)

Plan 25-20's precondition (`git grep -n "xfail(strict=True" -- "tests/test_demo_twin_*.py"` prints nothing) will not hold until the owner decides these three; that is the owner's call, not this plan's.

## Findings captured in the register (all owner-open, none decided)

Behaviour gaps: 25-12-F1, 25-13-F1 (nothing calls `request_resync()`), 25-14-F1 (coordinator rows not spilled during a DB outage), 25-15-F1 (`enforce_daily_state` has no live caller). Owner decisions on observed behaviour: 25-11-F1 (`/close` ends CLOSE_ALREADY_REQUIRED), 25-16-F1 (a new request is refused until the closed plan's approval expires), 25-13-F2 (health verdict observational at runtime, D102 wording), 25-14-F3, 25-15-F2, 25-16-F2. Remaining observations and twin-fidelity notes: 25-12-F2, 25-13-F3, 25-13-F4, 25-14-F2, 25-14-F4, 25-15-F3 to 25-15-F5, 25-16-F3, 25-16-F4.

## Deviations from Plan

None in behavior. Choices inside the plan's latitude:

- The tracer (Task 1) is test-only and green on its first run, because every scenario file already exists; the negative controls are its red evidence (same shape as plan 25-05). The plan's `<automated>` for Task 1 also runs `tests/test_phase24_gate.py`; it passed.
- Task 3 adds section A2 (ERR1003-KEY, OWNER-4), section B (findings) and section C (smaller points) beyond the 12 inherited rows, because the orchestrator asked that every F-labelled finding be captured and because the plan truth names `rest_gate.ban_end_clock_margin_ms` as owner-open. The gate enforces section B against the SUMMARYs.
- `LIVE_MODULES` is imported from `tests/test_phase24_gate.py` rather than re-typed, so the two gates cannot disagree.
- The register's claim that no plan summary records R-23 or R-28 as exposed is a reading of the summaries 25-08 to 25-16, not a machine check.

## Not covered by an agent-run test

- Nothing here ran against Binance Demo, PostgreSQL or Telegram; the gate checks structure only. It proves a scenario has a twin with REUSES and a marked Demo file, not that the Demo run passes.
- The inventory's expected-label column and the register's statuses and prose are hand-written from the summaries and the RESEARCH catalog; the gate checks their format, the label words, the REUSES agreement, status words, plan or scenario citations, and the finding and xfail coverage, not their correctness.
- The register gate depends on the `**Fk (` label format of the SUMMARYs; a finding written in another format would not be caught.
- Every owner-session item of the "Not covered by an agent-run test" sections of SUMMARYs 25-02 to 25-16 remains unobserved (register row 25-17-C1).

## Known Stubs

None.

## Threat Flags

None. The plan adds a test file and two planning documents; no network, auth, file-access or schema surface.

## Self-Check: PASSED

- FOUND: tests/test_phase25_gate.py, 25-SCENARIO-INVENTORY.md, 25-DEFERRED.md
- FOUND commits: 1e4a27f0, f73a20ab, 7d9d28a7, 64005355, b86f4286 (all ancestors of HEAD)
