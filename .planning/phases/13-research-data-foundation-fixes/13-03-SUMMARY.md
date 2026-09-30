---
phase: 13-research-data-foundation-fixes
plan: 03
subsystem: paper-supervisor
tags: [paper, supervisor, websocket, backfill, reconnect, seam, monotonic, determinism]

requires:
  - phase: 07-paper-loop
    provides: PaperSupervisor, resync.backfill_missed_closes, WS/REST adapter fakes
provides:
  - "Supervisor reconnect/rotation order is close handles -> REST backfill -> record closes -> resubscribe -> verification backfill (D-16, F-413)"
  - "PaperSupervisor._advance_last_close: lock-guarded monotonic check-and-set; record_close, the backfill and the WS handler all go through it (D-28)"
  - "_backfill_pairs helper keeping only closes that advance the last-close state, per-pair exception isolation, reason prefix per pass"
  - "Log events paper.supervisor.duplicate_close_dropped and paper.supervisor.verify_backfilled"
affects: [13-11, 16-paper-runtime, paper-loop-feed-events]

actuals:
  tokens: 7215
  tasks: 2
  commits: 4
plan_head_before: da5c720665b1c5a4bad33697862907ba01aa7852
plan_head_after: c660283e59e9a0a18dfe58f0ba1c36aa64be8876

tech-stack:
  added: []
  patterns:
    - "Monotonic cursor: one lock-guarded _advance_last_close is the single gate for WS dispatch and backfill returns, so a bar reaches the loop at most once"
    - "Two-pass seam closure: backfill before attach, verification backfill after attach from the updated cursor"
    - "Shared call log across WS and REST fakes so tests assert cross-adapter order by index (D-20)"

key-files:
  created: []
  modified:
    - src/paper/supervisor.py
    - tests/test_paper_supervisor_backfill.py
    - tests/test_paper_resync.py

key-decisions:
  - "Verification pass skips pairs whose first pass already raised: the first pass journaled that pair's outage gap, and re-running from the same unchanged cursor would double-count the same hole (keeps the one-gap-per-failing-pair contract)"
  - "The verification pass does not repeat the no_last_close ERROR log (log_missing_last_close=False); the first pass already reported it"
  - "The exception-path gap dict is named outage_gap to stop it shadowing the resync gap loop variable (mypy inferred dict[str, object])"

patterns-established:
  - "When two ingestion paths can deliver the same bar, gate both through one atomic monotonic cursor rather than deduplicating downstream"

requirements-completed: [DATA-01]

coverage:
  - id: D1
    description: "Unsolicited drop and 24h rotation close old handles, backfill every pair, then resubscribe; no reconnect entry on rotation"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_paper_supervisor_backfill.py#test_backfill_runs_before_resubscribe_on_unsolicited_drop"
        status: pass
      - kind: unit
        ref: "tests/test_paper_supervisor_backfill.py#test_backfill_runs_before_resubscribe_on_rotation"
        status: pass
    human_judgment: false
  - id: D2
    description: "Backfilled closes advance the last-close state; record_close never moves it backwards; a failing pair is still resubscribed with one outage gap"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_paper_supervisor_backfill.py#test_backfilled_closes_advance_last_close"
        status: pass
      - kind: unit
        ref: "tests/test_paper_supervisor_backfill.py#test_record_close_never_moves_backwards"
        status: pass
      - kind: unit
        ref: "tests/test_paper_supervisor_backfill.py#test_failing_pair_is_still_resubscribed_with_outage_gap"
        status: pass
    human_judgment: false
  - id: D3
    description: "A bar closing in the seam between backfill and WS attach is picked up once by the verification pass; the same bar from both passes is returned once"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_paper_supervisor_backfill.py#test_verification_pass_picks_up_bar_closed_in_seam"
        status: pass
      - kind: unit
        ref: "tests/test_paper_supervisor_backfill.py#test_same_bar_from_both_passes_returned_once"
        status: pass
      - kind: unit
        ref: "tests/test_paper_supervisor_backfill.py#test_verification_failure_keeps_first_pass_closes"
        status: pass
    human_judgment: false
  - id: D4
    description: "The WS handler drops a closed kline at or before the last close and never dispatches it twice; concurrent claims of one bar yield exactly one winner"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_paper_supervisor_backfill.py#test_ws_duplicate_of_backfilled_close_is_not_dispatched"
        status: pass
      - kind: unit
        ref: "tests/test_paper_supervisor_backfill.py#test_advance_last_close_is_atomic_under_threads"
        status: pass
    human_judgment: false
---

# Phase 13 Plan 03: Paper Supervisor Backfill Seam Summary

**PaperSupervisor now backfills missed closes before resubscribing, runs a verification backfill after attaching, and gates both the WS handler and the backfill through one lock-guarded monotonic last-close cursor so no bar is skipped or delivered twice across a reconnect or rotation.**

## Performance

- **Duration:** about 15 min
- **Started:** 2026-09-30T13:30Z (approx.)
- **Completed:** 2026-09-30T13:46Z
- **Tasks:** 2 (tracer + auto, both TDD)
- **Files modified:** 3 (1 source, 2 test)

## Accomplishments

- Reordered `_resubscribe_and_backfill` to close -> backfill -> record -> `start()` -> verification pass (D-16, F-413). The `(backfilled, outage_gaps)` return shape is unchanged.
- Added `_advance_last_close` (strictly-later check-and-set under `_last_close_lock`); `record_close`, `_backfill_pairs` and the WS kline handler all use it (D-28, T-13-10).
- Extracted `_backfill_pairs(now, *, reason_prefix, journal_outage_gaps)`; first pass uses `backfill_exception`, second uses `verify_backfill_exception`. A close is kept only if it advances the cursor, processed in close order.
- WS handler drops a closed kline at or before the last close and logs `paper.supervisor.duplicate_close_dropped`; forming klines are still ignored.
- Verification pass merges its kept closes per pair in close order and logs `paper.supervisor.verify_backfilled`.
- `src/paper/resync.py`, `src/paper/loop.py`, `src/adapters/paper_ws.py` untouched (empty diff).

## Task Commits

1. **Task 1 RED:** `7134141` test(13-03): failing ordering tests with shared call-log fakes
2. **Task 1 GREEN (tracer):** `e98792c` feat(13-03): backfill before resubscribe, monotonic last close
3. **Task 2 RED:** `e124031` test(13-03): failing verification-pass and duplicate-guard tests
4. **Task 2 GREEN:** `c660283` feat(13-03): verification pass and WS duplicate guard

Tracer gate: `<verify>` re-run end-to-end after Task 1 (pytest green; ruff clean; mypy clean for supervisor.py, see Issues) before starting Task 2.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Existing resync tests asserted one REST call per pair**
- **Found during:** Task 2 (running the plan's verify set)
- **Issue:** `tests/test_paper_resync.py::test_rotation_treated_as_scheduled_resubscribes_and_backfills` and `::test_unsolicited_disconnect_reconnects_and_resyncs` asserted exactly `initial + 2` klines calls (2 pairs). The mandated verification pass legitimately makes 2 calls per pair, so the contract changed by design (D-28).
- **Fix:** Updated both assertions to `initial + 4` (first pass + verification pass per pair) with comments; the start_ms loop check is unchanged. Rewritten, not deleted (D-29).
- **Files modified:** tests/test_paper_resync.py (not listed in the plan's files_modified)
- **Commit:** c660283

**2. [Rule 1 - Bug] Verification pass double-counted a failing pair's outage gap**
- **Found during:** Task 2
- **Issue:** When the first pass raised for a pair, the verification pass retried from the same unchanged cursor and raised again, producing two gaps for one hole; the existing test and the plan's one-gap contract require one.
- **Fix:** Verification pass skips pairs that already have an outage gap from the first pass (`skip_pairs`).
- **Files modified:** src/paper/supervisor.py
- **Commit:** c660283

**3. [Rule 3 - Blocking] mypy attr-defined on a shadowed variable**
- **Found during:** Task 1
- **Issue:** The exception-path `gap` dict (dict[str, object]) shadowed the resync gap loop variable, giving `"object" has no attribute "isoformat"`.
- **Fix:** Renamed the exception-path dict to `outage_gap`.
- **Commit:** e98792c

**Total deviations:** 3 auto-fixed (2 Rule 1, 1 Rule 3). **Impact:** none on scope; the test edit is a forced contract update.

## Issues Encountered

- The plan's mypy verify expects "Success: no issues found", but `mypy src/paper/supervisor.py` still reports one pre-existing error pulled in transitively: `src/adapters/telegram_notify.py:287` (datetime assigned to a Decimal variable). `src/paper/supervisor.py` is clean. Logged in `deferred-items.md`; out of scope.
- Known pre-existing failures (decision-alignment RQ-01/RQ-04) untouched; fixed by plan 13-11.

## Known Stubs

None.

## Threat Flags

None. Mitigations T-13-10 (monotonic lock-guarded cursor, duplicate tests), T-13-11 (backfill before resubscribe plus verification pass, two-value clock seam test), T-13-12 (per-pair isolation, failing pair still resubscribed) are all covered by tests. No packages installed (stdlib `threading` only).

## Verification

- `pytest tests/test_paper_supervisor_backfill.py tests/test_paper_resync.py tests/test_paper_ws_connect.py tests/test_paper_reviewfix_pins.py` : 39 passed.
- `pytest -k "paper or supervisor"` across tests: all passed.
- `ruff check` on supervisor.py and both edited test files: clean.
- `git diff` on resync.py, loop.py, paper_ws.py: empty.

## Next Phase Readiness

Ready for the next Phase 13 plan. Phase 16 composes the paper runtime on this supervisor; callers that consume the returned backfilled closes now receive a merged first+verification list per pair.

## Self-Check: PASSED

- src/paper/supervisor.py, tests/test_paper_supervisor_backfill.py, tests/test_paper_resync.py exist.
- Commits 7134141, e98792c, e124031, c660283 exist in git log.
