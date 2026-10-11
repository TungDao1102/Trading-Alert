---
phase: 16-paper-runtime-composition
plan: 29
subsystem: paper-runtime / restart, downtime and warm-up
tags: [paper-runtime, restart, warm-up, downtime-gap, restart-fence, epoch-consistency, fail-closed]

requires:
  - phase: 16-paper-runtime-composition
    provides: "16-26 run_admitted, LoopWiring, _LiveLoop; 16-24 BarPipeline (history-only rule, _seen dedup); 16-16 RuntimeStatePort and PgRuntimeState; 16-08 PaperSupervisor.record_close; 16-22 ExitCode table and the pin rule"
provides:
  - "src/paper/restart.py: restore_runtime, downtime_gaps, warm_up, supervisor_cursors, apply_restart_fence, check_epoch_consistency, health_record, restart_gap_record"
  - "src/paper/runtime.py: restart wiring in run_admitted/_LiveLoop (restore, gaps, warm-up, cursor seed, fence, health states), epoch check in main (exit 6)"
  - "src/paper/pipeline.py: BarPipeline.seed_processed"
affects: [16-31 SHADOW wiring, 16-32 compose (exit 6 is a held refusal), 16-40 16-43 16-44 real restart evidence on the soak host]

actuals:
  tokens: 19100
  tasks: 3
  commits: 5
plan_head_before: 3884ab6395a9add5de74a90d863112d081cc262e
plan_head_after: 9f722d5442c82862387312a8f2b5757a958e2224
commits: 5

tech-stack:
  added: []
  patterns:
    - "Restart is decided before the first subscription: restore from the port, record downtime gaps, warm the engine windows from REST through the pipeline as REST_WARMUP, seed the supervisor cursor, set the restart fence"
    - "Gap ids are keyed on the expected close, so a repeated restart skips closes that already have a gap instead of rewriting them with another reason"
    - "A restart fence in the queue entry point demotes any non-live bar at or before the warm-up snapshot to history only, independent of the Q-D rule"

key-files:
  created:
    - src/paper/restart.py
    - tests/test_paper_runtime_restart.py
    - tests/test_paper_runtime_restart_pg.py
  modified:
    - src/paper/runtime.py
    - src/paper/pipeline.py

key-decisions:
  - "A downtime gap needs a baseline: only a pair with a processed bar gets gaps. A pair that never delivered a bar yields none (nothing was expected); this keeps the first run after a pin free of invented gaps"
  - "The previous run is the last RUNTIME_START/STOP strictly before this run's own START (new RuntimeContext.started_at_utc); no marker or a START without a STOP is CRASH"
  - "Hole classification is by open time: a downtime close the warm-up request covered and the exchange did not return is EXCHANGE_NO_CANDLE; a close older than the requested window keeps the restart reason"
  - "The supervisor cursor is the newest warm-up close (the downtime closes are already gaps), falling back to the restored last close for a pair the exchange returned nothing for, and never behind a processed close"
  - "HEALTHY is declared strictly after the DISCONNECTED record of the same start (at least one millisecond later), because health records are keyed on their time"
  - "check_epoch_consistency compares the pin file with the EPOCH_PINNED record of the same epoch_id (the port is epoch-keyed); a newer pin of a different epoch is not detectable without a new port query, see Deviations"

requirements-completed: []

coverage:
  - id: R1
    description: "After a restart the last closes are restored from the state port, the supervisor is seeded before start, and the engine windows (1000 closed 1h and 300 closed 4h bars per symbol) are fetched as REST_WARMUP and never evaluated or recorded before the first live bar (L-04, D-02, D-04)"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_runtime_restart.py#test_planned_restart_restores_warms_up_records_the_gaps_and_evaluates_the_next_live_bar"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_restart.py#test_warm_up_asks_for_exactly_the_engine_windows_and_drops_the_forming_bar"
        status: pass
    human_judgment: false
  - id: R2
    description: "Closes that happened while the process was down are gaps with a reason (PLANNED_RESTART after a RUNTIME_STOP, CRASH without one, EXCHANGE_NO_CANDLE for a hole), never bars, one per close, uncovered (L-11, REV-01)"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_runtime_restart.py#test_the_same_history_without_a_stop_record_gives_the_crash_reason"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_restart.py#test_a_close_the_exchange_does_not_return_is_an_exchange_hole_not_a_planned_restart"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_restart.py#test_a_repeated_restart_never_rewrites_a_recorded_gap_with_another_reason"
        status: pass
    human_judgment: false
  - id: R3
    description: "No bar that closed at or before the warm-up snapshot can become a signal, whatever the Q-D answer is; the negative control shows the spy catches the hazard when the fence is removed (D-06, L-11)"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_runtime_restart.py#test_no_bar_that_closed_during_downtime_is_evaluated_whatever_the_qd_rule_is"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_restart.py#test_negative_control_without_the_fence_the_evaluate_all_rule_does_evaluate_a_downtime_bar"
        status: pass
    human_judgment: false
  - id: R4
    description: "A restart never mints an epoch: a missing or differing EPOCH_PINNED record exits 6 (a held refusal) before any subscription or START record"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_runtime_restart.py#test_a_restart_with_a_missing_or_different_pin_record_exits_6_before_any_subscription"
        status: pass
    human_judgment: false
  - id: R5
    description: "Across a stop and start every expected 1h close has exactly one processed or gap record, a replay inserts nothing, and ids do not depend on the wall clock - proven on the in-memory port; the identical driver on the real PostgreSQL stores was NOT run (no TEST_DATABASE_URL on this machine)"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_runtime_restart.py#test_a_full_session_accounts_for_every_close_in_memory"
        status: pass
      - kind: integration
        ref: "tests/test_paper_runtime_restart_pg.py#test_a_full_session_leaves_one_record_per_expected_close_on_postgresql"
        status: skipped
    human_judgment: false
  - id: R6
    description: "Real restart behaviour on the soak host against the real feed and the real PostgreSQL database (not exercised here; fake-level green never closes PAPER-01, SC9)"
    requirement: PAPER-01
    human_judgment: true
    rationale: "Real runtime evidence comes from the trial soak (plans 16-40, 16-43, 16-44); every collaborator in these tests is a fake and the PostgreSQL test was skipped"

duration: about 2 hours of work in one session
completed: 2026-10-10
status: complete
---

# Phase 16 Plan 29: Restart, downtime and warm-up Summary

**A restart now restores the last close per pair from the state port, records every downtime close as an explained uncovered gap (PLANNED_RESTART, CRASH or EXCHANGE_NO_CANDLE), rebuilds the exact engine windows from REST as history-only bars, seeds the supervisor cursor before subscribing, and fences every non-live bar at or before the warm-up snapshot out of evaluation, so no Q-D answer can turn a downtime bar into a late signal.**

## Accomplishments

- **Tracer (Task 1):** `run_admitted` takes a snapshot time, calls `restore_runtime`, `warm_up` (1000 closed 1h and 300 closed 4h bars per symbol, the forming bar dropped) and `downtime_gaps` before `supervisor.start()`. The gaps are written as PAPER_GAP records (source `RESTART`), the warm-up goes through the pipeline as REST_WARMUP (the loop fails closed if a warm-up bar evaluates or records anything), the supervisor is seeded with `record_close` and the first live closed 1h bar is evaluated once. `HEALTH_STATE_CHANGED` says DISCONNECTED from the RUNTIME_START and HEALTHY at the first live closed event.
- **Restart fence:** `apply_restart_fence(bar, snapshot)` is called for every bar entering the queue; a non-live bar whose close is at or before the snapshot is re-tagged REST_WARMUP. The test builds the real `BarPipeline` behind three Q-D rules (history-only, fresh-within-bound with a very large bound, evaluate-all), lets the supervisor's open-event verification backfill return a bar that closed 30 seconds before the restart, and the `evaluate_closed_bar` spy sees only the next live bar. The negative control replaces the fence with a pass-through and the evaluate-all rule does evaluate the downtime bar.
- **Epoch (Task 2):** `check_epoch_consistency` refuses (exit 6, before any subscription and before RUNTIME_START) when the pin file has no EPOCH_PINNED record or when strategy, parameter set, hash or opening time differ.
- **Replay safety:** `BarPipeline.seed_processed` marks each pair's restored last close as processed; the supervisor cursor falls back to the restored last close when the exchange returns nothing, and never moves behind a processed close. A repeated restart skips closes that already have a gap, so a first PLANNED_RESTART gap is never rewritten as CRASH after an immediate crash.
- **Holes:** a downtime close the warm-up asked for and the exchange did not return is EXCHANGE_NO_CANDLE (classified by open time); closes older than the requested window keep the restart reason.
- **Integration (Task 3):** one session driver (pin, stopped process with bars up to C, downtime, start with warm-up, two live bars) runs on the in-memory port (3 tests, passing) and on `PgRuntimeState` (3 tests, SKIPPED here, see below).

## RED Evidence

- **Task 1** (`10499d2`): 10 tests failed individually (`ModuleNotFoundError: No module named 'src.paper.restart'`, a missing `apply_restart_fence` attribute, and assertion timeouts for the integration tests); GREEN `fcb70d9`: all passing together with the 20 loop tests.
- **Task 2** (`e1d66d7`): 7 of 8 new tests failed (missing `check_epoch_consistency`, no exit 6, `RuntimeRecordConflict` when a processed bar is redelivered without the restored state, missing `seed_processed`, no cursor fallback, `PLANNED_RESTART` instead of `EXCHANGE_NO_CANDLE`, no `warm` argument). `test_a_repeated_restart_never_rewrites_a_recorded_gap_with_another_reason` passed at RED because the Task 1 code already skips recorded gaps (characterization test, not a RED). GREEN `d6b5357`.
- **Task 3** (`9f722d5`): no source change in this task (the plan states no schema change), so there is no RED: the tests exercise behaviour from Tasks 1 and 2.

## Task Commits

1. **Task 1 (tracer):** `10499d2` (test, RED), `fcb70d9` (feat, GREEN)
2. **Task 2:** `e1d66d7` (test, RED), `d6b5357` (feat, GREEN)
3. **Task 3:** `9f722d5` (test)

## Verification

- `tests/test_paper_runtime_restart.py` (21 tests), `tests/test_paper_runtime_loop.py` (20), `test_paper_runtime_pipeline.py`, `test_paper_runtime_admission.py`, `test_paper_market_inputs.py` and the rest of the `paper or runtime or soak or no_float` selection pass; `mypy src` clean (178 files); `ruff check` and `ruff format --check` clean for `src` and the two new test files.
- **PostgreSQL integration test: NOT RUN.** `tests/test_paper_runtime_restart_pg.py` has 3 tests; with no `TEST_DATABASE_URL` they skip (3 skipped), and with `TRADING_CI_STRICT=1` they fail by design (infrastructure missing). The plan's Task 3 acceptance (three pass, none skip) is therefore **not met** on this machine; it needs a disposable PostgreSQL. The same driver passes on the in-memory port.
- One failure outside this plan: `tests/test_cost_parity.py::test_simulator_and_paper_call_evaluate_risk_with_identical_arguments` (`[] != ()`), already logged in `deferred-items.md` by plan 16-15 and reproduced on a clean checkout of the commit before this plan's source changes.
- Fake-level green never closes PAPER-01 (SC9); real restart evidence comes from plans 16-40, 16-43 and 16-44.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] HEALTHY and DISCONNECTED in the same millisecond collided**
- **Found during:** Task 1 GREEN (seven existing loop tests failed with `RuntimeRecordConflict`).
- **Issue:** health records are keyed on their time (`runtime:<ms>`), and a fixed clock puts both states in one millisecond.
- **Fix:** the HEALTHY record is written at `max(clock, RUNTIME_START + 1 ms)`.
- **Files modified:** src/paper/runtime.py; **Commit:** fcb70d9

**2. [Rule 2 - Missing critical] A repeated restart could rewrite a recorded gap with another reason**
- **Issue:** a restart that crashes right after writing its gaps would, on the next start, recompute the same closes as CRASH and conflict with the stored PLANNED_RESTART records (fail closed forever).
- **Fix:** `restore_runtime` reads the existing PAPER_GAP keys and `downtime_gaps` skips them (first writer wins).
- **Commit:** fcb70d9 (test in e1d66d7)

**3. [Rule 3 - Blocking] Composition seams not named in the plan**
- `RuntimeContext.started_at_utc` (set by `main` to the RUNTIME_START time) lets the restore ignore this run's own marker and read the previous run; `RestartPlan` carries the decisions into `_LiveLoop`; the pipeline gained `seed_processed`, called through an optional runtime-checkable protocol so test doubles without it keep working.
- **Commit:** fcb70d9, d6b5357

### Plan points implemented differently

- **Epoch check is epoch-scoped.** The plan says "the latest EPOCH_PINNED record in the state port". `RuntimeStatePort` reads by `epoch_id` only, so the check compares the pin file with the EPOCH_PINNED record of the same epoch and refuses a missing record or a differing strategy, parameter set, hash or opening time. A newer pin of a *different* epoch in the database is not detected; detecting it needs a new cross-epoch port query and a PostgreSQL implementation that could not be tested here, so it was not added. A decision for a later gap plan if wanted.
- **Q-D rules other than history-only are modelled in the test.** Only history-only exists in `src` (the ratified rule), so the fresh-within-bound and evaluate-all variants are a test-local wrapper that admits REST_BACKFILL bars as live ones in front of the real `BarPipeline`; the fence removes the hazard before it.
- **Pairs without a processed bar get no downtime gap** (no baseline); stated in the module docstring.
- **The warm-up is a single request per pair** with no retry: a failure is `RuntimeFailClosed` (exit 7, restartable) before any subscription.

**Total deviations:** 3 auto-fixed (1 Rule 1, 1 Rule 2, 1 Rule 3) and 4 plan points implemented differently. **Impact:** no pinned constant, ratified value or decision file changed; no parity replay input recording was added (decision 16-DEC-PARITY belongs to a later gap plan).

## Known Stubs

None. The risk-inputs port stays unbound until plan 16-31 (documented in the 16-26 summary).

## Threat Flags

None beyond the plan's threat model: T-16-66 (late signal from a downtime bar) is mitigated by the REST_WARMUP tag, the gap records and the restart fence with a negative control; T-16-67 (unexplained gap or forked epoch) by one gap per downtime close with a reason, the epoch check and the replay-safety tests (in memory; the PostgreSQL replay test is unrun).

## Self-Check: PASSED

- Created files exist: `src/paper/restart.py`, `tests/test_paper_runtime_restart.py`, `tests/test_paper_runtime_restart_pg.py`.
- Commits found: 10499d2, fcb70d9, e1d66d7, d6b5357, 9f722d5.
- STATE.md and ROADMAP.md untouched; no `.env` read; no network used.

## PostgreSQL verification (orchestrator, 2026-10-11)
`tests/test_paper_runtime_restart_pg.py` run against the local Compose PostgreSQL 17 (database `trading_test`, user with CREATEDB, throwaway `t17_*_test` databases) with `TRADING_CI_STRICT=1`: 3 passed, 0 skipped, exit 0. This closes the Task 3 acceptance that the executor could not meet on a machine without PostgreSQL. The connection string was supplied through the process environment only and is not recorded here.
