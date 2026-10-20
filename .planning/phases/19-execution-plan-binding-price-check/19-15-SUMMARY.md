---
phase: 19-execution-plan-binding-price-check
plan: 15
subsystem: execution
tags: [manager, gtd-entry, fill-driven-protection, taxonomy, pre-send-refusal, write-ahead, tdd, binance]
requires: ["19-13", "19-14"]
provides:
  - "src/execution/manager.py: fill-driven execute_approved_plan (GTD LIMIT entry, no entry-time stop, hand-off via live_context.protection_registry.register_resting_entry); taxonomy-aware _place_entry_no_blind_retry; ExecutionAdapter.error_facts; reason ENTRY_REFUSED_BEFORE_SEND; SAFE_MODE reasons PROTECTION_HANDOFF_FAILED and UNKNOWN_EXCHANGE_ERROR"
  - "scripts/demo_rehearsal.py: far scenario without an entry-time stop; GuardedAdapter.place_entry(..., good_till_date)"
  - "tests/test_execution_write_ahead_pg.py: coordinator write-ahead PG test (STOP_LOSS INTENDED then SENT before place_algo_protective)"
affects: [19-16, 19-17]
actuals:
  tasks: 3
  commits: 7
status: complete
commits: 7
plan_head_before: 9a6093d
plan_head_after: 3716b16
tech-stack:
  added: []
  patterns: [fill-driven protection hand-off, classify(error_facts, PLACEMENT) instead of message text, GTD backstop from the plan expiry]
key-files:
  created: []
  modified: [src/execution/manager.py, scripts/demo_rehearsal.py, tests/test_execution_manager.py, tests/test_exchange_error_rejections.py, tests/test_execution_write_ahead_pg.py, tests/test_approval_replay_pg.py, tests/test_callback_redelivery_pg.py, tests/test_demo_rehearsal_flow.py, tests/fixtures/phase9/placement_sequences/expected.json]
requirements-completed: [EXEC-01, EXEC-02, APRV-02]
---

# Phase 19 Plan 15: Fill-driven manager, GTD entry and taxonomy on the entry path Summary

The live entry path now follows the single protection model of D-10. `execute_approved_plan` places only the GTD LIMIT entry (`time_in_force="GTD"`, `good_till_date=good_till_date_ms(trade_plan.expiry_utc)`) and hands it to the protection coordinator; the closePosition stop that Demo rejects with -4509 while flat is no longer sent at entry time. The manager also reads the Phase 18 taxonomy on the entry path (D-21, Phase 18 review src/WR-02).

## What was built

1. **Tracer (Task 1).** After ENTRY ACKED or EXISTS the manager builds a `RestingEntry` from the bound plan and the snapped prices and calls `register_resting_entry`. A registration failure enters SAFE_MODE(`PROTECTION_HANDOFF_FAILED`), cancels the entry by its deterministic id and returns RECONCILIATION_REQUIRED. A store failure after the ACK enters SAFE_MODE(DB_FAILURE) once and still hands the entry off (protection outranks the audit row, D034). The entry-time SL intent, the entry-time `_place_protective_leg` call and the ENTRY_WITHOUT_PROTECTIVE cancel branch are gone from `execute_approved_plan`; the helpers stay for `attach_protectives_to_fill` until plan 19-16.
2. **Taxonomy (Task 2).** `ExecutionAdapter.error_facts` was added to the Protocol and the fake. A `PreSendRefusal` is NO_TRADE `ENTRY_REFUSED_BEFORE_SEND` with the ENTRY intent REJECTED, no probe, no second attempt and no SAFE_MODE. A `REJECTED_DEFINITIVE` answer (for example -1106, -4016, -4024) is NO_TRADE without a probe. An `UNKNOWN_EXCHANGE_ERROR` answer is probed and never retried: found is handed off, absent enters SAFE_MODE(`UNKNOWN_EXCHANGE_ERROR`) with RECONCILIATION_REQUIRED. A failing `error_facts` is treated as UNKNOWN_EXCHANGE_ERROR (fail closed). Every other failure keeps the probe-then-second-attempt rule. The manager never reads exception text.
3. **PG and rehearsal (Task 3).** The write-ahead PG test now proves ENTRY INTENDED then SENT before `place_entry` and no STOP_LOSS row after the manager run; a new PG test drives the coordinator after a fake fill and shows STOP_LOSS INTENDED then SENT committed before `place_algo_protective` (the D-14 write-ahead lives in the coordinator). The Demo rehearsal far scenario no longer expects a stop at entry time and `GuardedAdapter.place_entry` accepts `good_till_date`.

## Legacy-assertion inventory (research P12)

| Old test | Outcome |
|---|---|
| `test_happy_path_places_one_entry_and_one_sl_leg` | rewritten: `test_happy_path_places_only_the_gtd_entry_and_hands_it_to_the_registry` |
| `test_golden_fixture_adapter_call_sequence_matches_expected` | kept; fixture regenerated (below) |
| `test_rejected_sl_cancels_entry_and_forces_safe_mode` | rewritten: `test_a_failed_hand_off_cancels_the_entry_and_requires_reconciliation` |
| `test_raising_sl_after_entry_ack_fails_closed` | rewritten: `test_a_resting_entry_that_cannot_be_built_is_refused_before_anything_is_sent` |
| `test_successful_run_stores_entry_and_stop_loss_rows` | rewritten: `test_successful_run_stores_only_the_entry_row` |
| `test_store_down_after_entry_ack_enters_safe_mode_and_still_places_the_sl` | rewritten: `..._still_hands_the_entry_off` |
| `test_store_down_when_recording_the_entry_ack_still_places_the_sl` | rewritten: `..._still_hands_the_entry_off` |
| `test_store_down_and_sl_unconfirmed_still_cancels_the_entry` | rewritten: `test_store_down_and_a_failed_hand_off_still_cancels_the_entry` |
| `test_cr01_db_outage_after_entry_ack_still_places_the_sl_with_real_controller` | rewritten: `..._still_hands_the_entry_off_real_controller` |
| `test_cr01_db_outage_at_sl_intent_still_places_the_sl_with_real_controller` | removed: no SL intent exists at entry time; the coordinator tests of 19-11 and 19-14 and the new coordinator write-ahead PG test cover the stop-side intent |
| `test_cr01_failing_journal_at_entry_without_protective_still_cancels_the_entry` | rewritten: `test_cr01_failing_journal_at_a_failed_hand_off_still_cancels_the_entry` |
| `test_unconfirmed_sl_leaves_the_stop_loss_row_unknown` | removed: no entry-time stop row; the coordinator branch tests of 19-14 (B2, B3) cover an unconfirmed stop |
| `test_tracer_1106_on_the_protective_stop_is_entry_without_protective` | rewritten: `test_tracer_1106_on_the_protective_stop_after_a_fill_goes_close_required` (B5 on the coordinator) |
| `test_safe_mode_eligible_is_false_but_the_manager_branch_still_fires` | rewritten: `..._the_coordinator_branch_still_fires` |
| `test_entry_rejection_sequence_is_unchanged_by_the_table` | rewritten: `test_entry_rejection_by_an_owner_code_is_definitive_and_not_retried` |
| `test_rows_are_committed_before_each_order_call` (PG) | rewritten: `test_rows_are_committed_before_the_entry_call_and_no_stop_row_exists`; new `test_the_coordinator_writes_the_stop_loss_intent_ahead_of_the_stop` |
| `test_approval_replay_pg.py` intent rows | `[("ENTRY","ACKED"),("STOP_LOSS","ACKED")]` became `[("ENTRY","ACKED")]` |
| `test_callback_redelivery_pg.py` | PG rows are ENTRY only after the fill-driven switch |
| `test_far_scenario_entry_no_longer_new_leaves_the_stop_in_place` | rewritten: `..._leaves_the_position_for_the_operator` |

New tests: `test_q5_the_second_entry_attempt_is_kept_and_pinned_at_two`; `test_refusal_before_send_is_no_trade_without_probe_retry_or_safe_mode`; `test_refusal_on_the_second_attempt_is_also_no_trade_before_send`; `test_a_definitive_rejection_is_no_trade_without_probe_or_second_attempt`; `test_an_unknown_exchange_error_found_by_the_probe_is_handed_off`; `test_an_unknown_exchange_error_absent_by_the_probe_is_never_retried`; `test_a_second_unknown_exchange_error_is_not_retried_either`; `test_a_failing_error_facts_is_treated_as_an_unknown_exchange_error`; `test_no_outcome_of_the_manager_places_a_protective_stop`.

## Golden-fixture inventory

`tests/fixtures/phase9/placement_sequences/expected.json` `method_sequence`: `place_entry`, `query_algo_order_by_client`, `place_algo_protective` became `place_entry` only.

## Open items (recorded, not decided)

- **Q5**: `_ENTRY_MAX_ATTEMPTS == 2` is kept unchanged for STATUS_UNKNOWN and other ambiguous failures after a definitive-absence probe; a test pins it with a comment naming Q5. The owner decides whether to remove it.
- **O-01 stays open**: this plan does not enable live orders, does not edit `docs/DECISIONS.md` and does not edit the ROADMAP criteria. LIVE stays blocked until the owner accepts the D055 closure draft and runs the Demo probes (O-05).
- The rehearsal fill scenario still calls `attach_protectives_to_fill`; plan 19-16 rewires it.
- All evidence is fake-adapter agreement, not Demo or mainnet behaviour.

## Deviations from Plan

None in code. **Process:** the plan was executed by an earlier session that ended before writing this SUMMARY; the implementation commits (8cd4a5e to 3716b16) were verified and this SUMMARY was written afterwards in a new worktree session (branch `p19-15`). `tests/test_callback_redelivery_pg.py` changed (a 3-line assertion change) although it is not in the plan's `files_modified`; it asserted the old ENTRY plus STOP_LOSS rows.

## Verification (real runs, worktree branch p19-15)

- `uv run pytest -m "not docker"` on `tests/test_execution_manager.py tests/test_exchange_error_rejections.py tests/test_execution_write_ahead_pg.py tests/test_approval_replay_pg.py tests/test_execution_exactly_once_pg.py tests/test_demo_rehearsal_flow.py tests/test_demo_rehearsal_safety.py tests/test_protection_branches.py tests/test_binance_usdm_source_guard.py -rs`: all passed, no skips (TEST_DATABASE_URL set, PG tests ran).
- `uv run mypy src`: Success, no issues found in 212 source files. `uv run ruff check`: All checks passed. `uv run ruff format --check`: 658 files already formatted.
- The whole suite was not run.
