---
phase: 17-operational-persistence-layer
plan: 12
subsystem: execution
tags: [restart-recovery, execution-intent, postgresql, safe-mode, fail-closed, concurrency, sc4, negative-control]

requires:
  - phase: 17-operational-persistence-layer
    provides: "plan 01 ExecutionIntentStore Protocol, PgExecutionStateStore, BinanceSemanticsFakeAdapter, pg_db fixtures; plan 03 EXECUTION_INTENT transition table; plan 11 write-ahead flow, CrashAfter, FailingIntentStore"
provides:
  - "src/execution/intent_recovery.py: resolve_unresolved_intents and RecoveryReport (query-only restart recovery, fail closed into SAFE_MODE UNRESOLVED_EXECUTION_INTENT)"
  - "ExecutionIntentStore.list_unresolved_intents (Protocol, PgExecutionStateStore single SELECT, in-memory and other test doubles)"
  - "GLOSSARY 9.4 row for UNRESOLVED_EXECUTION_INTENT (and DB_FAILURE emitters)"
  - "Full SC4 matrix on PostgreSQL: open/filled/canceled x same-process/restart, two-thread races with separate engines, negative controls"
  - "Fix: the consume race loser now returns False instead of raising IntentStateConflict"
affects: [17-14, 17-15, phase-19, phase-20, phase-24]

actuals:
  tokens: 18900
  tasks: 2
  commits: 4
plan_head_before: db1a7269647c422d82d874af7e7955377ced172b
plan_head_after: e85cc109c6b96c0ae2186626cfbb5ce82f94fc37

tech-stack:
  added: []
  patterns:
    - "Recovery takes a two-method read-only probe Protocol (IntentProbeAdapter), so placing an order is structurally impossible, not just untested"
    - "Barrier store wrapper (BarrierBeforeConsume) releases two racers at the same instant just before consume; its __getattr__ delegation needs no edit when the Protocol grows"
    - "A unique violation on a secondary arbiter that only reflects a concurrent insert of the SAME (approval_id, role) row is a lost race (False); with no such row it stays IntentStateConflict"

key-files:
  created:
    - src/execution/intent_recovery.py
    - tests/test_intent_recovery.py
    - tests/test_intent_recovery_pg.py
  modified:
    - src/execution/intent_store.py
    - src/persistence/execution_state.py
    - tests/support/intent_store_fakes.py
    - tests/test_execution_exactly_once_pg.py
    - docs/GLOSSARY.md

key-decisions:
  - "Recovery order (D-14): INTENDED/SENT -> UNKNOWN first, then probe by deterministic id (ENTRY by query_order_by_client, protective legs by query_algo_order_by_client): found -> ACKED (any age); definitively absent and intended less than lookup_window ago -> REJECTED; probe error, indeterminate answer (anything but a literal True/False) or an absent order at or past the window -> stays UNKNOWN. Exactly 3 days old is NOT young (fail closed). lookup_window defaults to 3 days (Binance Query Order retention, Pitfall 11) and is a keyword argument."
  - "SAFE_MODE UNRESOLVED_EXECUTION_INTENT is entered exactly once per pass when anything stays UNKNOWN or a status write fails; an unreadable store enters SAFE_MODE DB_FAILURE and re-raises (nothing-to-resolve is never confused with could-not-look). Exit stays Phase 20."
  - "The ENTRY probe reads order_id and status; the algo probe has no order id, so a STOP_LOSS ACKED by recovery keeps exchange_order_id NULL and stores algo_status as exchange_status."
  - "intent_recovery imports the pure-Python src.persistence.errors (PersistenceError), the same typed failures the manager catches; no SQLAlchemy import."
  - "Consume/protective-insert race fix (for D051): the loser of a same-approval race can hit uq_execution_intents_plan_role before the targeted ON CONFLICT arbiter reports the winner; the store now re-checks (fresh transaction) whether the (approval_id, role) row exists and answers False, otherwise it still raises IntentStateConflict (a different approval holding the plan)."

requirements-completed: [EXEC-03]

coverage:
  - id: D1
    description: "list_unresolved_intents returns every INTENDED, SENT and UNKNOWN intent of either role ordered by intended_at_utc, approval_id, role, never ACKED or REJECTED; single SELECT on PostgreSQL"
    requirement: EXEC-03
    verification:
      - kind: unit
        ref: "tests/test_intent_recovery.py#test_list_unresolved_returns_intended_sent_unknown_in_deterministic_order"
        status: pass
      - kind: integration
        ref: "tests/test_intent_recovery_pg.py#test_list_unresolved_intents_returns_open_legs_only"
        status: pass
    human_judgment: false
  - id: D2
    description: "Recovery resolves only by deterministic-id query: found -> ACKED with the order id, young absent -> REJECTED, probe error / indeterminate / absent at or beyond 3 days -> UNKNOWN; place_entry and place_algo_protective call counts stay 0 in every case"
    requirement: EXEC-03
    verification:
      - kind: unit
        ref: "tests/test_intent_recovery.py (21 tests: found, never-sent, stop-loss by algo id, probe error, indeterminate x3, old, 3-day boundary, found-when-old, window kwarg, repeatable)"
        status: pass
      - kind: integration
        ref: "tests/test_intent_recovery_pg.py#test_recovery_after_a_crash_at_any_step_never_places_an_order"
        status: pass
    human_judgment: false
  - id: D3
    description: "Anything unresolved enters SAFE_MODE UNRESOLVED_EXECUTION_INTENT exactly once (GLOSSARY 9.4); an unreadable store enters DB_FAILURE and propagates; a failing status write leaves the intent unresolved"
    requirement: EXEC-03
    verification:
      - kind: unit
        ref: "tests/test_intent_recovery.py#test_safe_mode_is_entered_exactly_once_for_many_unresolved_intents"
        status: pass
      - kind: integration
        ref: "tests/test_intent_recovery_pg.py#test_probe_error_persists_unknown_and_enters_safe_mode_once"
        status: pass
    human_judgment: false
  - id: D4
    description: "Crash after entry_sent, restart on a fresh engine, recovery with the exchange holding the order resolves ENTRY to ACKED; a later execute_approved_plan with the same approval returns (True, RECONCILIATION_REQUIRED) with zero place_entry calls"
    requirement: EXEC-03
    verification:
      - kind: integration
        ref: "tests/test_intent_recovery_pg.py#test_crash_after_entry_sent_is_resolved_to_acked_and_never_resent"
        status: pass
    human_judgment: false
  - id: D5
    description: "Exactly one place_entry and one ENTRY row across first entry OPEN, FILLED, CANCELED, each same-process and across a restart on a fresh engine, with stored-outcome replay and zero adapter calls on the second call"
    requirement: EXEC-03
    verification:
      - kind: integration
        ref: "tests/test_execution_exactly_once_pg.py#test_sc4_double_call_places_exactly_one_entry"
        status: pass
    human_judgment: false
  - id: D6
    description: "Two threads with separate engines released by a threading.Barrier: store level yields exactly one True and one row; manager level places one entry and the loser returns the winner's outcome or RECONCILIATION_REQUIRED; 60-round hammer proves the loser never raises"
    requirement: EXEC-03
    verification:
      - kind: integration
        ref: "tests/test_execution_exactly_once_pg.py#test_two_threads_consuming_the_same_approval_yield_one_winner_and_one_row"
        status: pass
      - kind: integration
        ref: "tests/test_execution_exactly_once_pg.py#test_two_concurrent_manager_calls_place_exactly_one_entry"
        status: pass
      - kind: integration
        ref: "tests/test_execution_exactly_once_pg.py#test_consume_race_never_raises_for_the_loser_over_many_rounds"
        status: pass
    human_judgment: false
  - id: D7
    description: "Negative controls: a never-remembering store places two entries after fill and after cancel, the exchange rejects the duplicate with -4116 only while the first entry is open, and two overlapped never-remembering callers both reach place_entry, so the harness would catch a regression"
    requirement: EXEC-03
    verification:
      - kind: integration
        ref: "tests/test_execution_exactly_once_pg.py#test_negative_control_never_remembering_store_places_two_entries_after_free"
        status: pass
      - kind: integration
        ref: "tests/test_execution_exactly_once_pg.py#test_negative_control_open_entry_is_rejected_with_4116_by_the_exchange"
        status: pass
      - kind: integration
        ref: "tests/test_execution_exactly_once_pg.py#test_negative_control_concurrent_calls_without_a_durable_row_both_reach_the_exchange"
        status: pass
    human_judgment: false

duration: 32 min
completed: 2026-10-01
status: complete
---

# Phase 17 Plan 12: Restart Recovery and the Full SC4 Matrix Summary

**A restart now turns every in-flight intent into UNKNOWN and resolves it only by querying the exchange by its deterministic id (found -> ACKED, young and absent -> REJECTED, anything else stays UNKNOWN and enters SAFE_MODE UNRESOLVED_EXECUTION_INTENT), recovery can never place an order, and exactly one entry holds across open/filled/canceled, restarts and two-thread races; the race tests also exposed and fixed a real defect where the consume loser raised instead of returning False.**

## Performance

- **Duration:** about 32 min (about 25 of them waiting for full-suite runs)
- **Completed:** 2026-10-01
- **Tasks:** 2 (both TDD)
- **Files:** 3 created, 5 modified

## Accomplishments

- `src/execution/intent_recovery.py`: `resolve_unresolved_intents(*, store, adapter, safe_mode_controller, now_utc, lookup_window=timedelta(days=3))` and frozen `RecoveryReport(resolved, unresolved, safe_mode_entered)` with `(approval_id, role, final status)` tuples in the store's deterministic order. The adapter parameter is `IntentProbeAdapter`, a Protocol with only `query_order_by_client` and `query_algo_order_by_client`, so the module has no way to place an order (also grep-proven). Probe exceptions are caught per intent; `found` is read like the manager does and only a literal `True`/`False` counts.
- `list_unresolved_intents()` added to the Protocol, `PgExecutionStateStore` (one SELECT, `ORDER BY intended_at_utc, approval_id, role`), `InMemoryExecutionIntentStore`, `AlwaysWinsIntentStore`, `CrashAfter`, `FailingIntentStore`.
- GLOSSARY 9.4: `UNRESOLVED_EXECUTION_INTENT` row; the `DB_FAILURE` row now also lists `src/execution/manager.py` (added by 17-11, never recorded) and the new module.
- `tests/test_execution_exactly_once_pg.py` extended (tracer tests untouched): 6-case open/filled/canceled x same-process/restart matrix, store-level and manager-level two-thread Barrier races (3 attempts each), a 60-round race hammer, regression test that a different approval of the same plan still conflicts, and four negative controls. `BarrierBeforeConsume` added to `tests/support/intent_store_fakes.py`.

## Task Commits

1. Task 1 RED: `2e6f1d9` test(17-12): RED for restart recovery of in-flight execution intents (collection failed: module absent)
2. Task 1 GREEN: `8812d80` feat(17-12): restart recovery resolves in-flight intents by query and fails closed
3. Task 2 tests (RED for the race hammer): `00b58c6` test(17-12): full SC4 matrix, barrier race tests and negative controls
4. Task 2 fix (GREEN): `e85cc10` fix(17-12): consume race loser returns False instead of raising on a secondary unique arbiter

## Verification (real runs)

PostgreSQL runs used the dev server (`TEST_DATABASE_URL` set inline; credential not written to any file). Precondition probe exited 0.

- Task 1: `pytest tests/test_intent_recovery.py -x -q` exit 0 (21 tests). `TRADING_CI_STRICT=1 pytest tests/test_intent_recovery_pg.py -x -q -rs` exit 0, 13 tests, no SKIPPED line. `mypy src`: no issues in 130 source files. `ruff check` (repo root): all checks passed. `ruff format --check src tests`: 298 files already formatted. `scripts/verify_decision_alignment.py all`: ALL_PASS.
- Task 2: `TRADING_CI_STRICT=1 pytest tests/test_execution_exactly_once_pg.py -q -rs` exit 0, 28 tests, no SKIPPED line.
- Acceptance greps: `UNRESOLVED_EXECUTION_INTENT` appears in `docs/GLOSSARY.md` and `src/execution/intent_recovery.py`; `grep -nE "\.place_(entry|algo_protective)\("` and `grep -nE "^(from|import) sqlalchemy"` on `intent_recovery.py` print nothing; `Barrier` appears in both test files; `negative_control` appears 4 times in `test_execution_exactly_once_pg.py` (needs 2).
- Harness is not vacuous: before the fix the race hammer failed in 4 of 5 runs and the plain two-thread test failed in 1 of about 24 runs (`IntentStateConflict ... uq_execution_intents_plan_role`); after the fix 6 of 6 runs of the hammer plus both thread tests passed. A scratch run of two threads on `AlwaysWinsIntentStore` through `BarrierBeforeConsume` produced 2 `place_entry` calls (kept as a permanent test).
- Related suites after the fix: `test_execution_manager`, `test_execution_write_ahead_pg`, `test_execution_exactly_once_pg`, `test_intent_recovery_pg`, `test_persistence_approvals_pg`, `test_persistence_migration_pg`, `test_persistence_transitions_pg`, `test_persistence_triggers_pg`, `test_pg_fixture_guard` all green under `TRADING_CI_STRICT=1`.
- Plan-level full suite: `pytest -m "not docker" -q` with `TEST_DATABASE_URL` set: 3480 passed, 10 skipped (the pre-existing Windows/NTFS/shellcheck/symlink set), 1 failed: `tests/test_universe_freeze.py::test_refreeze_refuses` with a Windows `PermissionError` on a temp file ("witness write failed"). That module passes 3 of 3 runs alone and is unrelated to this plan (same file-locking flake class as the known `tests/test_backfill_cli.py` one, which also failed once under an earlier `-x` run and passed alone). An earlier full run under `TRADING_CI_STRICT=1 -x` stopped on the backfill flake, so it is not a clean strict run; strict runs were done per module as listed above.
- Repo-root `ruff format --check` still reports only `.planning/phases/17-operational-persistence-layer/17-RESEARCH.md` (pre-existing, logged in `deferred-items.md` since 17-01).

## Deviations from Plan

**1. [Rule 1 - Bug] Consume race loser raised IntentStateConflict instead of returning False**
- **Found during:** Task 2 (two-thread race tests)
- **Issue:** `consume_and_record_entry_intent` (and `record_protective_intent`) use `ON CONFLICT (approval_id, role) DO NOTHING`. When two writers race on the same approval, the loser can reach the secondary unique index `uq_execution_intents_plan_role` before the primary-key arbiter reports the winner, and PostgreSQL raises a unique violation instead of skipping the insert. The store mapped it to `IntentStateConflict`; the manager mapped that to `(True, INVALIDATED)` instead of replaying the winner's outcome. One entry still held (no unsafe behavior), but D-17 and this plan's truth ("two threads ... exactly one True and one row") were violated, about 1 run in 24.
- **Fix:** a new private `_lost_race_to_same_row` checks, after the failed transaction rolled back and in a fresh one, whether the (approval_id, role) row exists; if yes the call returns False (the replay path), otherwise the violation is still translated to `IntentStateConflict` (a different approval holding the plan). Only SQLSTATE 23505 qualifies; FK violations still raise `ParentRowMissing`. Applies to both insert methods.
- **Files modified:** `src/persistence/execution_state.py`, `tests/test_execution_exactly_once_pg.py` (hammer test and different-approval regression test)
- **Verification:** hammer test red before (4 of 5 runs), green after (6 of 6); different-approval conflict test green; `mypy src`, ruff clean.
- **Commit:** `e85cc10` (tests that exposed it: `00b58c6`)

**Total deviations:** 1 auto-fixed (Rule 1). **Impact:** production change confined to the two insert paths of an in-plan file; no signature or behavior change on the winner path.

Judgment calls inside the plan's latitude: (a) an absent order exactly 3 days old stays UNKNOWN (young means strictly less than the window); (b) a SENT/INTENDED row whose UNKNOWN write fails is reported unresolved with its stored status and still triggers SAFE_MODE; (c) the manager-level race test accepts the loser returning either the winner's `(False, OK)` or `(True, RECONCILIATION_REQUIRED)`, as the plan states; (d) the Task 2 plan said "Keep the plan 01 tracer test intact": done, and the pre-existing never-remembering test is kept next to the new parametrized controls.

## Known Stubs

None.

## Threat Flags

None. T-17-31 mitigated (recovery only queries by deterministic id; place counts asserted 0 on every path and on a crash after each write-ahead step on PostgreSQL). T-17-32 mitigated and tightened by the race fix above (Barrier races at store and manager level, 60-round hammer). T-17-33 mitigated (absent and older than the window, or exactly at it, stays UNKNOWN with SAFE_MODE). T-17-SC: no packages installed.

## Issues Encountered

None blocking. For later phases:

- A STOP_LOSS leg that recovery resolves to REJECTED (absent, young) while its ENTRY resolves to ACKED means an acknowledged entry with no stop. This plan does not enter SAFE_MODE for that case (the plan's rules cover UNKNOWN only); it is the 17-11 known gap and belongs to Phase 20 reconciliation, which reads the same rows through `list_unresolved_intents` and the ENTRY/STOP_LOSS statuses.
- `resolve_unresolved_intents` is a tested function, not wired into a live process (Phase 20/24 own wiring). `RECONCILIATION_REQUIRED` for a replay after recovery is unchanged: no outcome is ever recorded by recovery.
- Per-approval ordering of `list_unresolved_intents` across several approvals is proven in memory; the PostgreSQL test proves the role tie-break on one approval (one seeded approval chain).
- For D051 (plan 15): the consume race fix, the recovery rules and 3-day window, SAFE_MODE reason `UNRESOLVED_EXECUTION_INTENT`.

## Next Phase Readiness

Plan 17-14 and Phase 20 can read in-flight intents with `list_unresolved_intents` and reuse `resolve_unresolved_intents`; Phase 20 owns SAFE_MODE exit and the entry-without-stop case.

## Self-Check: PASSED

- Files exist: `src/execution/intent_recovery.py`, `tests/test_intent_recovery.py`, `tests/test_intent_recovery_pg.py`, this SUMMARY.
- Commits exist: `2e6f1d9`, `8812d80`, `00b58c6`, `e85cc10`; measured commit count 4 from the recorded plan head `db1a726`.
