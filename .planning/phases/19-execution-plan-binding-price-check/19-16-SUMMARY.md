---
phase: 19-execution-plan-binding-price-check
plan: 16
subsystem: execution
tags: [take-profit, attach, protection-coordinator, tp-unavailable, snapshot-validity, write-ahead, demo-rehearsal, tdd, binance]
requires: ["19-07", "19-14", "19-15"]
provides:
  - "src/execution/manager.py: attach_protectives_to_fill(*, entry, position_quantity, live_lot_filters, adapter, intent_store, now_utc, safe_mode_controller) -> AttachOutcome; AttachOutcome.sized is a TakeProfitSizing; reason PLAN_SYMBOL_MISMATCH; corrected D-17 docstring"
  - "src/execution/protection.py: PROTECTED -> COMPLETE / TP_UNAVAILABLE step, COMPLETE / TP_UNAVAILABLE / PROTECTED -> FLAT with sweep; alert event TP_UNAVAILABLE; journal event PROTECTION_TP_UNAVAILABLE; reasons TP_LEGS_CONFIRMED, TP_UNAVAILABLE, POSITION_CLOSED"
  - "scripts/demo_rehearsal.py: coordinator-driven fill scenario; GuardedAdapter.place_market_close; evidence details protection_flow and live_context.plan_snapshot_status; steps protection_stop and attach_protectives"
  - "tests/test_protection_take_profits.py: coordinator TP, TP_UNAVAILABLE and exit tests"
affects: [19-17]
actuals:
  tokens: 24600
  tasks: 3
  commits: 7
status: complete
commits: 7
plan_head_before: c6275af69599592dd2112d11f5e37129df4d1b57
plan_head_after: e0be1935b45442cae13e63e0d51d39b291a5d9de
tech-stack:
  added: []
  patterns: [stop adopted by REST query and never placed or cancelled by the TP step, write-ahead TP intents with the TP1 quantity, query-first placement with a REST confirmation query, snapshot_is_valid_for_live gate with a live-filter re-size, hold routine shared by every refusal]
key-files:
  created: [tests/test_protection_take_profits.py]
  modified: [src/execution/manager.py, src/execution/protection.py, scripts/demo_rehearsal.py, tests/test_execution_attach.py, tests/test_exchange_error_rejections.py, tests/test_binance_usdm_signed_calls.py, tests/test_protection_coordinator.py, tests/test_protection_branches.py, tests/test_demo_rehearsal_flow.py, tests/test_demo_rehearsal_safety.py]
  deleted: [tests/fixtures/phase9/attach/expected.json, tests/fixtures/phase9/attach/input.json]
key-decisions:
  - "attach never places or cancels a stop: the stop must answer class ACTIVE to a REST query, otherwise ENTRY_WITHOUT_PROTECTIVE with SAFE_MODE and no take profit (D-11, D-17)"
  - "A leg is confirmed only when the placement response confirms it AND a REST query answers ACTIVE; its intent then becomes ACKED; a definitive rejection or a pre-send refusal is REJECTED, anything else UNKNOWN"
  - "The coordinator reads live lot filters only when the plan snapshot is stale but COMPLETE; an INCOMPLETE snapshot, or a stale one whose filter read failed, is refused by attach and ends in TP_UNAVAILABLE"
  - "attach enters SAFE_MODE for every refusal it reports; the coordinator adds a SAFE_MODE entry only for its own refusal (a REST position on the wrong side)"
requirements-completed: [EXEC-01, RISK-04]
---

# Phase 19 Plan 16: TP legs after the entry is terminal, attach rewritten, rehearsal fill flow Summary

Criterion 4 now holds inside the single protection model of D-10. Once the entry is terminal and the stop is confirmed ACTIVE by REST, the coordinator reads the real position and calls the rewritten `attach_protectives_to_fill`, which sizes TP1 and TP2 from that position on the exchange filters, writes their intents ahead and confirms them by REST. A leg that cannot be sized, is rejected or is not confirmed ends in the existing CR-03 branch (`TP_UNAVAILABLE`: stop kept, SAFE_MODE, critical alert, never a normal completion, never an automatic flatten for that reason alone). The Demo rehearsal's fill scenario now exercises that flow end to end.

## What was built

1. **Tracer (Task 1).** `attach_protectives_to_fill(*, entry, position_quantity, live_lot_filters, adapter, intent_store, now_utc, safe_mode_controller)` has no symbol, side, plan-hash, snapshot, fill-event or template argument (an `inspect.signature` test pins the list). Order: bind check (an entry whose snapshot symbol or trade plan id, or whose live filters' symbol, disagree is `PLAN_SYMBOL_MISMATCH` before any adapter call, with SAFE_MODE), non-positive quantity is `NO_FILL`, One-way only (D-14), the stop query (ACTIVE adopted; absent, non-active, unreadable or odd answers hold), `snapshot_is_valid_for_live`, `size_take_profits` with `entry.tp1_quantity_fraction` and `entry.working_type`, then TP1 and TP2 one after the other: `record_protective_intent` (TP1 with its quantity, TP2 with `None`), `mark_sent`, query-first placement under the deterministic `xa-` id, a REST confirmation query, `record_result` ACKED. A failed leg stops the sequence (no TP2 after a failed TP1), keeps the stop and every confirmed leg, and nothing is cancelled. Every scenario goes through a helper that asserts zero STOP_LOSS placements and zero cancels. The docstring says D034 supersedes D-02 and names `src/execution/emergency_close.py` and `emergency_manual_close` (D-17).
2. **Coordinator (Task 2).** `PROTECTED` is now stepped: the REST position is read (unreadable: wait, journal, retry; flat: FLAT with a sweep; wrong side: TP_UNAVAILABLE), a stale but COMPLETE snapshot gets `adapter.symbol_lot_filters` read, attach runs once, OK is COMPLETE (`TP_LEGS_CONFIRMED`), a refusal is TP_UNAVAILABLE (`TP_UNAVAILABLE`, journal note `PROTECTION_TP_UNAVAILABLE`, critical alert `TP_UNAVAILABLE` with the fixed failure text). From COMPLETE or TP_UNAVAILABLE a step that reads a flat position goes FLAT (`POSITION_CLOSED`) and sweeps SL/TP1/TP2 by id; an open or unreadable position keeps the state. `blocks_new_entries()` stays False for both states. The legs are placed once after the entry is terminal, so no resize path exists (G2-032).
3. **Rehearsal (Task 3).** `_fill_flow` steps `coordinator.step()` with the injected sleep until COMPLETE, TP_UNAVAILABLE, FLAT, CLOSE_FAILED, ENTRY_ENDED_NO_FILL or the old poll bound; at the bound with no fill it cancels the entry and lets the coordinator observe the end. The synthetic `FillEvent` (`position-view:` trade id, research Phase 18 P13) and `_attach_after_fill` are gone. `GuardedAdapter.place_market_close` is a mutating method (counted, planned only in DRY_RUN); `symbol_lot_filters` was already a read passthrough. `MarketCloseResult` is an accepted order record in EXECUTE. Steps: `fill_wait`, `protection_stop`, `attach_protectives` (known gap = NOT_REHEARSED with the reason), `protection_outcome` (only when the run failed); evidence adds `details.protection_flow` (final state and transitions) and `live_context.plan_snapshot_status`. `main(..., snapshot_live_inputs=)` is a test seam (no CLI flag) that supplies margin type, leverage and equity; without it the snapshot is INCOMPLETE, the real behavior.

## TDD gates

| Task | RED | GREEN | RED failures |
|---|---|---|---|
| 1 tracer | fbcda93 | 466ea5f | 52 failed (new signature, new details) |
| 2 | 57c23d5 | 2579aa6 | 18 failed (no PROTECTED step) |
| 3 | 8355606 | b007bea | 31 failed (most through the new `run_flow(snapshot_live_inputs=)` seam) |
| follow-up | | e0be193 | tests only: the real-dataclass leg confirmation and the rejected-response case |

Tracer feedback gate: not `blocking-human`; the plan's `<verify>` commands were re-run end to end after the tracer commit (tests, `mypy src`, `ruff`) and passed, so expansion went ahead.

## Legacy-assertion inventory (research P12)

| Old test (plan 09-04 / 18-26) | Outcome |
|---|---|
| `test_partial_fill_replayed_fills_fold_and_attach_once` | replaced by `test_tracer_attach_adopts_the_confirmed_stop_and_places_tp1_and_tp2`; attach no longer folds fills (`fold_fills` keeps `tests/test_execution_partials.py`) |
| `test_unconfirmed_sl_leg_yields_entry_without_protective_with_zero_rescue` | removed: attach places no stop; covered by `test_absent_stop_holds_without_placing_a_stop_or_a_take_profit` and the status table |
| `test_non_live5_symbol_raises_before_any_adapter_call` | rewritten (entry-based) |
| `test_adapter_exception_on_tp1_forces_safe_mode_and_stops` | rewritten: `test_ambiguous_tp1_failure_leaves_the_intent_unknown` |
| `test_unsizeable_tp1_still_places_sl_first_and_holds_entry_without_protective` | rewritten: `test_tp1_below_the_minimum_quantity_holds_and_keeps_the_stop` (no SL placed any more) plus `..._minimum_notional_...` |
| `test_entry_time_sl_is_adopted_not_duplicated` | replaced by the status table case `[NEW]` (the entry-time stop no longer exists, plan 19-15) |
| `test_second_attach_call_for_same_plan_places_nothing_new` | rewritten: `test_a_second_attach_for_the_same_plan_places_nothing_new` |
| `test_existing_non_active_leg_is_unconfirmed_and_never_re_placed` | rewritten for the stop (status table `[CANCELED]`) and TP1 (`test_an_existing_non_active_tp1_is_never_re_placed`) |
| `test_existing_sl_leg_adoption_follows_the_status_table` | kept, now `test_existing_stop_adoption_follows_the_status_table` over the REST stop query |
| `test_sl_placement_response_confirmation_follows_the_status_table` | removed: attach never places the stop; the response table stays pinned by `tests/test_algo_status.py` |
| `test_probe_failure_fails_closed_without_placement` | kept: `test_stop_probe_failure_fails_closed_without_placement` |
| `test_missing_safe_mode_controller_raises_before_any_adapter_call` | kept (async) |
| `test_manager_module_has_no_float_in_new_attach_code`, `test_manager_module_does_not_import_binance_sdk` | kept (the first renamed `test_manager_module_has_no_float`) |
| `test_leg_confirmation_reads_real_dataclass_with_allow_list` | kept: `test_leg_confirmation_reads_the_real_dataclass_with_the_allow_list` |
| `test_rejected_dataclass_response_holds_entry_without_protective` | rewritten: `test_a_rejected_placement_response_for_tp1_is_unconfirmed_even_if_rest_shows_it` |
| `test_foreign_fill_in_stream_still_places_sl_and_holds` | removed: attach takes no fill stream |
| `tests/test_exchange_error_rejections.py::test_rejected_stop_loss_in_attach_is_entry_without_protective` | rewritten on TP1: `test_rejected_take_profit_in_attach_is_entry_without_protective_and_keeps_the_stop` (three owner codes) |
| `tests/test_exchange_error_rejections.py::test_rejected_take_profit_in_attach_is_entry_without_protective` | rewritten: `test_rejected_second_take_profit_in_attach_keeps_tp1_and_the_stop` |
| `tests/test_binance_usdm_signed_calls.py::test_protective_blocked_by_pause_or_ban_surfaces_unprotected_position` | cases rewritten: pause and ban refuse the stop query (STOP_LOSS, 0 and 0 calls); 429 and 418 hit TP1 (1 placement, 2 queries); the paused confirmation query hits TP1; `RecordingRest.absent_after` added |
| `tests/test_protection_coordinator.py::test_replayed_fills_never_place_a_second_stop` | adjusted: one STOP placement, three placements in total after the PROTECTED step |
| `tests/test_protection_branches.py::test_branch_b2_a_stop_active_one_step_before_the_deadline_avoids_close_required` | adjusted: the step after PROTECTED is COMPLETE; the test still pins no CLOSE_REQUIRED |
| `tests/test_demo_rehearsal_flow.py::test_fill_scenario_attaches_sl_tp1_tp2_with_half_quantity` | rewritten: `test_fill_scenario_completes_through_the_coordinator_with_a_complete_snapshot` |
| `tests/test_demo_rehearsal_flow.py::test_fill_scenario_unfilled_entry_cancels_and_skips_attach` | rewritten: `test_fill_scenario_unfilled_entry_ends_no_fill_after_the_cancel` |

New: `test_attach_signature_has_no_symbol_side_plan_hash_or_snapshot_parameter`, the three PLAN_SYMBOL_MISMATCH tests, `test_hedge_mode_is_not_supported_and_holds_before_any_adapter_call`, the stale, future-dated and INCOMPLETE snapshot tests, the two store-failure tests, 18 coordinator tests in `tests/test_protection_take_profits.py` (all 18 match `-k tp`, including the INCOMPLETE refusal), `test_fill_scenario_with_the_incomplete_snapshot_is_tp_unavailable_a_known_gap`, `test_fill_scenario_with_a_rejected_stop_closes_by_market_and_fails`, `test_the_dry_run_fill_scenario_attaches_nothing`. The orphaned golden fixtures `tests/fixtures/phase9/attach/{input,expected}.json` were deleted (intentional; nothing else read them).

## The INCOMPLETE-snapshot consequence (for the owner, recorded in 19-17)

`snapshot_is_valid_for_live` is False for an INCOMPLETE snapshot, and margin type, leverage and equity have no source until Phases 21-22. With real data every TP placement is therefore refused: the plan ends in `TP_UNAVAILABLE` with the stop kept, SAFE_MODE(`ENTRY_WITHOUT_PROTECTIVE`) and a critical alert. This is the fail-closed reading of D-20, not worked around. The Demo rehearsal shows it honestly: `attach_protectives` is NOT_REHEARSED with "known gap: plan snapshot is INCOMPLETE ...", the outcome is COMPLETE_WITH_GAPS and attestation item 1 stays NOT_OBSERVED until a COMPLETE snapshot exists.

## Open items (recorded, not decided)

- **O-02 / EXEC-07**: the TP1 fraction is still the D052(c) constant passed by the caller; EXEC-07 is not claimed here and stays Pending.
- **O-03 / G4-007**: no single-TP fallback; an un-sizeable TP1 is `TP_UNAVAILABLE`.
- **19-NOTES question**: a partial fill whose quantity is below the minimum risk utilization is not treated as a normal completion; only minQty and MIN_NOTIONAL decide, through `TP_UNAVAILABLE`.
- **A3**: whether a closePosition leg auto-cancels on a flat position is not assumed; the sweep runs regardless and tolerates unknown ids.
- **No stop supervision after PROTECTED**: a COMPLETE or TP_UNAVAILABLE plan only watches the position; a stop that stops being ACTIVE while the position stays open (a B4-like case after COMPLETE) is not detected here. Phase 20/24 (reconcile) should own it.
- **TP_UNAVAILABLE is terminal for the plan**: a pre-send refusal (418/429 pause, Q4) on a TP leg also ends there (intent REJECTED, SAFE_MODE, alert); a retry after the pause is an operator or Phase 24 decision.
- **Hedge**: attach refuses any position mode other than One-way (D-14, fail closed); the coordinator already refuses to register Hedge.
- **Requirements**: `requirements mark-complete` was not run; EXEC-01 and RISK-04 keep their Pending status in REQUIREMENTS.md as for plans 19-14 and 19-15 (no running-process proof), the phase gate 19-17 owns that.
- **O-01 stays open**: nothing here enables live orders or edits `docs/DECISIONS.md` or the ROADMAP criteria. All evidence is fake-exchange agreement (the fake's `trigger_stop`, `place_market_close` codes and algo statuses are labelled conventions), not Demo or mainnet behaviour. No `--execute`, Demo or network call was made.

## Deviations from Plan

**1. [Rule 2 - Critical] Guards not listed in the plan.** attach refuses any non-One-way position mode (`position mode HEDGE is not supported`) and a refusal for a bind mismatch also enters SAFE_MODE; the coordinator treats a REST position on the wrong side of the plan as TP_UNAVAILABLE (SAFE_MODE entered by the coordinator). Each has a test.

**2. [Scope] Files outside `files_modified`.** `tests/test_protection_coordinator.py` and `tests/test_protection_branches.py` each had one test that steps past PROTECTED and now sees the TP legs (adjusted as in the inventory); `tests/test_demo_rehearsal_safety.py` is named by Task 3's action; the two `tests/fixtures/phase9/attach` files were deleted as orphans. Task 2's verify list already includes the two protection files.

**3. [Design] `_place_protective_leg` and `_is_leg_confirmed` stay.** `tests/test_algo_status.py` (not in this plan) pins both. `_place_protective_leg` is now a thin wrapper over the new `_attempt_protective_leg` and has no caller in `src`; removing it needs that test edited, left to plan 19-17.

**4. [Design] Known gap uses status NOT_REHEARSED.** The rehearsal's step vocabulary has no "known gap" status; NOT_REHEARSED with a `known gap:` detail keeps it from counting as PASSED.

**5. [Process] Branch name.** The commits are on `p19-15`, the branch the dispatch named; it is not in the `agent-*` namespace of the pre-commit allow-list, and it is not a protected branch. No other branch was created or touched.

**6. [Process] State tools.** STATE.md in this worktree still showed plan 11 as current (the earlier plans 11 to 15 were never recorded here). `roadmap update-plan-progress` derives from the SUMMARY files on disk, so it also ticked plans 11 to 15; `state advance-plan` was not used so as not to invent a position.

## Verification (real runs, worktree branch p19-15, TEST_DATABASE_URL set)

- `uv run pytest -m "not docker" tests/test_execution_attach.py tests/test_exchange_error_rejections.py tests/test_binance_usdm_signed_calls.py tests/test_protection_take_profits.py tests/test_protection_branches.py tests/test_protection_coordinator.py tests/test_demo_rehearsal_flow.py tests/test_demo_rehearsal_safety.py -x`: all passed.
- `tests/test_execution_manager.py tests/test_execution_write_ahead_pg.py tests/test_approval_replay_pg.py tests/test_execution_exactly_once_pg.py tests/test_callback_redelivery_pg.py tests/test_algo_status.py tests/test_protection_router_rig.py tests/test_emergency_market_close.py tests/test_execution_partials.py tests/test_execution_gates.py tests/test_execution_modes.py tests/test_tp_sizing.py` with `-rs`: all passed, no skips (the PG tests ran).
- `tests/test_ast_guards.py tests/test_binance_usdm_source_guard.py tests/test_no_unratified_defaults.py tests/test_demo_probe_*.py tests/test_analytics_edge_guards.py tests/test_risk_cost_guards.py`: all passed.
- `uv run mypy src`: no issues in 212 source files. `uv run ruff check`: all checks passed. `uv run ruff format --check`: 659 files already formatted.
- `git grep -n "position-view:" -- scripts/demo_rehearsal.py`: no match.
- The whole suite was not run.

## Self-Check: PASSED

- Files: `src/execution/manager.py`, `src/execution/protection.py`, `scripts/demo_rehearsal.py`, `tests/test_protection_take_profits.py` and the edited test files exist; the two deleted fixture files are absent.
- Commits found in `git log`: fbcda93, 466ea5f, 57c23d5, 2579aa6, 8355606, b007bea, e0be193.
