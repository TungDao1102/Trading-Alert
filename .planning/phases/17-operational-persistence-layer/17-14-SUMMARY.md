---
phase: 17-operational-persistence-layer
plan: 14
subsystem: persistence
tags: [approval-replay, callback-redelivery, restart, journal-idempotency, concurrency, postgresql, telegram, exactly-once]
status: complete

requires:
  - phase: 17-operational-persistence-layer
    provides: "plan 04 deterministic callback journal ids; plan 08 PgJournalStore; plan 09 PgApprovalStore (lookup_by_short_id, lookup_by_token_hash, save_atomic, insert_pending, record_short_id_mapping); plan 10 PgTradingEntityStore; plan 11 write-ahead execution manager; plan 12 BarrierBeforeConsume and the Binance-semantics fake"
provides:
  - "tests/test_approval_replay_pg.py: the production wiring (dispatch_callback + PgApprovalStore + PgJournalStore feeding execute_approved_plan + PgExecutionStateStore) and the restart, expiry and wrong-token proofs; its helpers (process_on, seed_parent_chain, dispatch, execute, deliver) are the integration the Phase 24 composition reuses"
  - "tests/test_callback_redelivery_pg.py: journal idempotency on redelivery (row counts, first-delivery timestamps) and the two-thread delivery race with and without the in-process token lock"
affects: [17-15, phase-19, phase-23, phase-24]

actuals:
  tokens: 8700
  tasks: 2
  commits: 2
plan_head_before: bf9b9eb308961d1038deba2e5d4d19c88800bf89
plan_head_after: 5e195eefc7bea920a39ef157cece0d6e1ccd9f14

tech-stack:
  added: []
  patterns:
    - "A restart in a test disposes every engine and rebuilds engine, stores and the manager call on the same database (process_on context manager)"
    - "A race test holds two deliveries between the token lookup and the decision with a threading.Barrier so both see PENDING and the database alone picks the winner; a negative control with a forgetful store proves the barrier really overlaps them"

key-files:
  created:
    - tests/test_approval_replay_pg.py
    - tests/test_callback_redelivery_pg.py
  modified: []

key-decisions:
  - "No defect was found in the owning modules, so no production file changed: replay, redelivery, expiry, wrong-token and concurrent delivery all behave as D-10, D-15, D-16, D-17 and D-26 specify"
  - "Observation (not a defect): after the plan expiry the callback layer rejects a redelivered APPROVE with APPROVAL_EXPIRED (check_binding_full keeps its expiry gate), so the stored outcome is returned by execute_approved_plan only when it is handed the stored approval directly; both behaviors fail closed and place nothing. Pinned by test_redelivery_after_expiry_still_returns_the_stored_outcome"
  - "The replayed dispatch returns the stored approval with consumption_status CONSUMED and consumed_at_utc set, while the first delivery's returned approval was still UNCONSUMED; the test compares the replay to the first approval plus that stamp rather than expecting byte equality"

requirements-completed: [APRV-02, EXEC-03]

coverage:
  - id: D1
    description: "A replayed APPROVED callback after a restart (entry filled, every engine disposed, new engine and stores) returns the stored approval and the stored OK outcome with zero adapter calls; place_entry stays at one; one ENTRY and one STOP_LOSS intent row; one decided approval, CONSUMED"
    requirement: APRV-02
    verification:
      - kind: integration
        ref: "tests/test_approval_replay_pg.py#test_replayed_approve_after_restart_reaches_place_entry_zero_times"
        status: pass
    human_judgment: false
  - id: D2
    description: "Redelivery after the plan's expiry: execute_approved_plan returns the stored outcome with zero adapter calls (identity passes, lookup precedes expiry); a never-executed approval still expires; the callback layer itself fails closed with APPROVAL_EXPIRED"
    requirement: EXEC-03
    verification:
      - kind: integration
        ref: "tests/test_approval_replay_pg.py#test_redelivery_after_expiry_still_returns_the_stored_outcome"
        status: pass
      - kind: integration
        ref: "tests/test_approval_replay_pg.py#test_expiry_does_not_unlock_a_plan_that_was_never_executed"
        status: pass
    human_judgment: false
  - id: D3
    description: "A wrong token for the same short id is INVALIDATED at dispatch and at execution, never reveals the stored outcome and leaves the stored rows unchanged"
    requirement: APRV-02
    verification:
      - kind: integration
        ref: "tests/test_approval_replay_pg.py#test_wrong_token_for_the_same_short_id_is_invalidated_and_sees_no_outcome"
        status: pass
    human_judgment: false
  - id: D4
    description: "The same callback_query.id delivered three times (with a restart between) leaves exactly one CALLBACK_RECEIVED and one CALLBACK_RESOLVED row at the first delivery's occurred_at_utc; a rejected redelivery adds nothing; a rejected delivery and a later valid delivery with another query id are four distinct rows"
    requirement: APRV-02
    verification:
      - kind: integration
        ref: "tests/test_callback_redelivery_pg.py#test_same_callback_delivered_three_times_leaves_one_receipt_and_one_resolved_row"
        status: pass
      - kind: integration
        ref: "tests/test_callback_redelivery_pg.py#test_a_rejected_redelivery_adds_no_row_either"
        status: pass
      - kind: integration
        ref: "tests/test_callback_redelivery_pg.py#test_rejected_then_valid_delivery_leave_distinct_rows_without_conflict"
        status: pass
    human_judgment: false
  - id: D5
    description: "Two threads with separate engines delivering the same APPROVE (same and different query ids, with the in-process token lock and without it so the database arbitrates) end with one decision, one ENTRY intent and one place_entry; the loser gets the stored outcome or fail-closed RECONCILIATION_REQUIRED; no unhandled exception"
    requirement: EXEC-03
    verification:
      - kind: integration
        ref: "tests/test_callback_redelivery_pg.py#test_two_concurrent_deliveries_of_the_same_approve_place_exactly_one_entry"
        status: pass
    human_judgment: false
  - id: D6
    description: "Negative controls prove the tests are not vacuous: a store that never remembers places a second entry after the fill, and a forgetful decision store lets both overlapped deliveries decide"
    requirement: EXEC-03
    verification:
      - kind: integration
        ref: "tests/test_approval_replay_pg.py#test_negative_control_a_store_that_never_remembers_places_two_entries"
        status: pass
      - kind: integration
        ref: "tests/test_callback_redelivery_pg.py#test_negative_control_without_the_database_two_deliveries_would_decide_twice"
        status: pass
    human_judgment: false
---

# Phase 17 Plan 14: Approval Replay and Callback Redelivery on PostgreSQL Summary

**The real callback dispatch wired to the PostgreSQL approval and journal stores feeds the real execution path: a replayed or redelivered APPROVE after a restart, after expiry, or raced by two threads places one entry, writes one decision and one audit row per step.**

## Performance

- **Duration:** about 25 min
- **Started:** 2026-10-01T17:26:10Z
- **Tasks:** 2 (test-only plan)
- **Files created:** 2 (no production file changed)

## Accomplishments

- End-to-end chain on PostgreSQL: `dispatch_callback` (with `PgApprovalStore.lookup_by_short_id`, `lookup_by_token_hash`, `save_atomic` and `PgJournalStore.record`) then `execute_approved_plan` with `PgExecutionStateStore`. Parents come from `PgTradingEntityStore` and `PgApprovalStore.insert_pending`; the short-id mapping is seeded with `record_short_id_mapping` first.
- Restart proof (T-17-37): delivery 1 places one entry and the fake then fills it; every engine is disposed; delivery 2 (same query id) on a rebuilt engine returns the stored approval (same decision, now stamped CONSUMED) and the stored `ExecutionOutcome(False, "OK")` with zero adapter calls. `execution_intents` holds one ENTRY and one STOP_LOSS row (both ACKED), `approvals` one decided CONSUMED row.
- Expiry: handed the stored approval after the plan's expiry, `execute_approved_plan` still returns the stored outcome with zero adapter calls; an approval that was never executed still expires and places nothing.
- Wrong token: INVALIDATED at dispatch (unknown token hash) and at execution (identity gate before the stored-outcome lookup); no stored row changes.
- Journal idempotency (T-17-38): three deliveries of one `callback_query.id` leave exactly one CALLBACK_RECEIVED and one CALLBACK_RESOLVED row, both carrying the first delivery's `occurred_at_utc`; a rejected (wrong chat) redelivery adds no row; a rejected delivery plus a later valid one with another query id leave four distinct rows.
- Concurrency: two threads with separate engines, released at a barrier, for the same and for different query ids, with the in-process token lock and without it (monkeypatched away, with both deliveries held between lookup and decision so the database picks the winner: exactly one `won` and one `lost` save). One decision, one ENTRY intent, one `place_entry`; the loser returns the stored outcome or fail-closed RECONCILIATION_REQUIRED.
- Two negative controls show the assertions are not vacuous (a never-remembering store places two entries; a forgetful decision store lets both overlapped deliveries decide).

## Task Commits

1. **Task 1: End-to-end APPROVE replay across restart and after expiry on PostgreSQL** - `270654e` (test)
2. **Task 2: Callback redelivery journal idempotency and concurrent delivery race** - `5e195ee` (test; also adds optional `lookup_by_token_hash` / `save_atomic` hooks to the shared `dispatch` and `deliver` helpers of module 1)

The tests passed on their first run: every behavior is already provided by plans 04, 08, 09, 11 and 12, so there is no RED commit for a missing implementation; the negative controls stand in for the RED evidence that the chain would show the double entry if the durable row were absent.

## Verification

- `TRADING_CI_STRICT=1 pytest tests/test_approval_replay_pg.py` : 5 passed, 0 skipped.
- `TRADING_CI_STRICT=1 pytest tests/test_callback_redelivery_pg.py tests/test_approval_replay_pg.py -x -q -rs` : 17 passed, 0 skipped. The race tests were re-run four more times: all green.
- `ruff check src tests`, `ruff format --check src tests` (305 files) and `mypy src` (132 files): clean.
- Acceptance greps: `dispatch_callback(` (test_approval_replay_pg.py:202), `dispose` (lines 107/126/318/352), `Barrier` and `CALLBACK_RECEIVED` in test_callback_redelivery_pg.py all print matches.
- Full suite (plan verification): `pytest -q -rs` over the whole repository with `TEST_DATABASE_URL` set exits 0 (no failures, no PostgreSQL skips). The 21 skipped tests are host infrastructure only: `shellcheck` not on PATH (8), the `trading-alert-ops:dev` image not built (11), NTFS cannot represent POSIX modes (1), symlinks unavailable (1). A first full run under `TRADING_CI_STRICT=1 -x` stopped at `test_script_passes_shellcheck[backup-drill.sh]` because `shellcheck` is not installed on this Windows host (strict mode turns missing infrastructure into a failure); that is unrelated to this plan, so the strict run was repeated without the flag and without `-x`.

## Deviations from Plan

None - plan executed exactly as written. No defect was found in any owning module, so no production file was edited and no regression test was added for a fix.

## Issues Encountered

None.

## Known Stubs

None.

## Threat Flags

None. No new network endpoint, auth path or schema; test files only.

## Notes for later phases

- Observation for Phase 23/24 (not a defect): after the plan expiry a redelivered APPROVE is answered `APPROVAL_EXPIRED` by the callback layer, not with the stored outcome. If the Telegram message should then show "already executed", the composition has to read the stored outcome itself (`PgExecutionStateStore.get_entry`) before treating the rejection as final.
- The "restart" in these tests rebuilds engines, stores and the manager call; the in-process per-token lock dictionary of `src/approval/replay.py` survives inside the one test process. That is harmless (it is only a latency optimization, and the `db_arbiter` variants remove it), but a real subprocess restart is not simulated.

## Self-Check: PASSED

- tests/test_approval_replay_pg.py and tests/test_callback_redelivery_pg.py exist on disk.
- Commits 270654e and 5e195ee exist on master.
