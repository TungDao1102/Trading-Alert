---
phase: 19-execution-plan-binding-price-check
plan: 11
subsystem: execution
tags: [protection, closePosition, stop-loss, fill-driven, coordinator, tdd, binance]
requires: ["19-01", "19-05", "19-08", "19-09", "19-10"]
provides:
  - "src/execution/protection.py: ProtectionState, RestingEntry, PlanProtection, ProtectionRegistry, CriticalAlertSink, EmergencyCloser, ProtectionAdapter, RoutedFillLike, ProtectionCoordinator"
  - "tests/support/protection_doubles.py: RecordingAlerts, ScriptedEmergencyCloser, RecordingSafeMode, resting_entry_for_tests, make_rig"
affects: [19-12, 19-13, 19-14, 19-15, 19-16, 19-17]
tech-stack:
  added: []
  patterns: [step-driven coordinator with injected clock, asyncio.gather for D-12 concurrency, journal-per-transition with deterministic ids, duck-typed router sink]
key-files:
  created:
    - src/execution/protection.py
    - tests/support/protection_doubles.py
    - tests/test_protection_coordinator.py
    - tests/test_protection_router_rig.py
  modified: []
decisions:
  - "Exchange order id of a stream fill is matched to a plan by the id learned from a REST probe, else by the single (symbol, entry side) candidate; otherwise the fill is journaled PROTECTION_UNKNOWN_FILL and the REST poll still covers the plan"
  - "A failed query of the stop before the first placement does not stop the placement (the exchange rejects a second open algo order with the same client id, so protecting wins over a possible duplicate)"
  - "RestingEntry refuses a working_type that differs from its plan_constraint_snapshot working type"
status: complete
commits: 5
plan_head_before: 4e37e15d10c652818053e9e5d36895f64ed2c561
plan_head_after: c3bede11136f2bd4cd59c6828f91ffa5ce4247c9
actuals:
  tokens: 20700
  tasks: 3
  commits: 5
---

# Phase 19 Plan 11: Fill-driven protection coordinator Summary

A step-driven coordinator that, on the first positive fill of a registered resting entry (user-data stream or REST probe), writes the STOP_LOSS intent INTENDED then SENT and starts the closePosition STOP_MARKET placement and the cancel of the entry remainder together, then counts the position as protected only after a REST query of the stop answers ACTIVE (branch B0 of D-10, plus REST-only detection and the router wiring).

## What was built

1. **Tracer (Task 1, tracer-type).** `ProtectionCoordinator(adapter, intent_store, journal, safe_mode_controller, alert_sink, emergency_closer, limits, clock)`. The constructor calls `limits.require_live_ready()` before anything else; `register_resting_entry` refuses Hedge (and any unknown position mode) and a duplicate plan hash; `fill_sink` is a synchronous, non-blocking enqueue that never raises; `step()` runs plans concurrently in a deterministic start order. First fill: `UNPROTECTED`, `record_protective_intent(role=STOP_LOSS, intended_quantity=None)` then `mark_sent`, then `asyncio.gather(place stop, cancel remainder)`. The stop is query-first by its deterministic id (an existing ACTIVE stop is adopted). Stop payload: `side=exit_side, algo_type=CONDITIONAL, type=STOP_MARKET, position_side=BOTH, trigger_price=sl_trigger_price, close_position=True, quantity=None, working_type=entry.working_type`, no `reduce_only`. The next step queries the stop (ACTIVE only through `is_protection_confirmed`) and the entry (FILLED/CANCELED/EXPIRED/EXPIRED_IN_MATCH): intent ACKED, state `PROTECTED` (stop confirmed, entry terminal) or `PROTECTED_ENTRY_OPEN` (stop confirmed, entry still open). A store `PersistenceError` enters SAFE_MODE(DB_FAILURE) once, later store writes are skipped, protection continues; a journal failure is handled the same way.
2. **REST path and duplicates (Task 2).** Every AWAITING_FILL entry is polled each step. `executed_quantity > 0` is a first fill whatever the status (a CANCELED entry that kept a partial fill still has a position); PARTIALLY_FILLED/FILLED with the quantity missing or zero is a first fill too and journals `PROTECTION_FILL_QUANTITY_UNKNOWN`; CANCELED/EXPIRED/EXPIRED_IN_MATCH with executed 0 goes to `ENTRY_ENDED_NO_FILL` and places nothing; an ended entry with executed `None` is settled by `snapshot_positions` (open position: first fill; flat: no fill; unreadable: stay and retry). Replayed fills and fills for later-state plans never place a second stop; a fill no plan owns is journaled once as `PROTECTION_UNKNOWN_FILL`. Two `start_together` tests hold the cancel (stop still completes in the step) and hold the stop (cancel still completes).
3. **Router rig and purity (Task 3).** The real `UserDataRouter` with `fill_sink=coordinator.fill_sink` routes a synthetic TRADE frame (also with `after_gap=True`); a `REST_FALLBACK` fill is accepted as evidence; stream and REST-only fills give the same calls and states. An AST test pins `protection.py` imports (stdlib, `src.domain`, `src.execution.*`, `src.persistence.errors`), no float, no wall clock, no `asyncio.sleep`.

## State names (stable for Phase 20)

`AWAITING_FILL`, `UNPROTECTED`, `PROTECTED_ENTRY_OPEN`, `PROTECTED`, `COMPLETE`, `TP_UNAVAILABLE`, `CLOSE_REQUIRED`, `FLAT`, `CLOSE_FAILED`, `ENTRY_ENDED_NO_FILL` (value equals name; a test pins the set). Implemented transitions here: `AWAITING_FILL -> UNPROTECTED -> PROTECTED_ENTRY_OPEN -> PROTECTED`, `UNPROTECTED -> PROTECTED`, `AWAITING_FILL -> ENTRY_ENDED_NO_FILL`. `blocks_new_entries()` is True for `UNPROTECTED`, `CLOSE_REQUIRED`, `CLOSE_FAILED`. COMPLETE/TP_UNAVAILABLE (19-16) and CLOSE_REQUIRED/FLAT/CLOSE_FAILED (19-14) are not reachable yet.

## What Phase 20 and later plans read

- **STOP_LOSS intent row**: `intended_at_utc` is the unprotected-since time (written at the step that detected the first fill); status SENT until REST answers ACTIVE (then ACKED with `exchange_status` the algo status), UNKNOWN when REST finds the stop in a non-ACTIVE status. An ENTRY row ACKED with no STOP_LOSS row is the normal resting state.
- **Journal**: `PROTECTION_TRANSITION` (entity_type `ProtectionState`, entity_id plan hash, correlation `protection_<plan_hash>`, id `ptr_...` = `correlated_event_id(step="<seq>:<from>-><to>")`, payload keys approval_id/from/reason/seq/symbol/to/trade_plan_id; registration is `NONE -> AWAITING_FILL`). Diagnostics: `PROTECTION_FILL_QUANTITY_UNKNOWN`, `PROTECTION_UNKNOWN_FILL`, `PROTECTION_REST_FAILED`, `PROTECTION_STOP_PLACEMENT_FAILED`, `PROTECTION_ENTRY_CANCEL_FAILED`, `PROTECTION_STEP_ERROR` (exception TYPE names only).
- **Restart rebuild** of coordinator state is Phase 20/24 (G4-029, research P8). **Step cadence** is a Phase 24 number and must be compatible with `max_unprotected_ms`; nothing here decides it. Exchange order ids learned from the stream are overwritten by the REST probe id (both are the exchange id on the real exchange; the test fake uses `ex-N` vs a numeric stream id).

## Deviations from Plan

None to the files or the contract. Judgement calls inside the plan (also in `decisions` above):

1. **Failed stop probe still places.** The plan says query-first; when the probe itself raises, the coordinator journals `PROTECTION_REST_FAILED` and places anyway (Binance rejects a duplicate open algo client id, so no duplicate open stop; not placing would leave a fill unprotected). The manager's older helper treats an unknown probe as unconfirmed and does not place; plan 19-14 may revisit.
2. **Fill-to-plan matching** needed an exchange order id the `RestingEntry` field list does not carry; solved without a new field (learned id, else unique symbol and entry side).
3. **Task 3 had no RED run.** The router sink contract was already satisfied by the Task 1 `fill_sink`, so `tests/test_protection_router_rig.py` passed on first run and no `src/execution/protection.py` change was needed (the plan allowed one). Its assertions would fail if the sink were not wired (`result.fills == 1`, the placement counts); no mutation run was made.

## Not done here (by plan)

- No retry of a failed or ambiguous stop placement, no re-issue of a failed entry cancel, no `max_unprotected_ms` / `entry_terminal_timeout_ms` deadline, no CLOSE_REQUIRED, no alert or emergency close call: plan 19-14 (the limits are only checked for configuration). `alert_sink` and `emergency_closer` are stored but unused.
- A later fill of a plan past AWAITING_FILL is discarded (branch B4 detection, plan 19-14).
- No TP legs (19-16) and no manager hand-off (19-15); `blocks_new_entries()` is consumed by plan 19-13.
- Rate-limit gate pause (Q4, src/WR-12) is not handled: a refusal is just a failed call journaled as a REST failure; "never naked" is not claimed.
- Hedge, mainnet behavior, partial fills on Demo, and `closePosition` with an open position (Demo probe 1) remain unverified; LIVE stays blocked (O-01, D055).

## Verification (real runs from the worktree, branch p19-11)

- `uv run pytest -m "not docker" tests/test_protection_coordinator.py tests/test_protection_router_rig.py tests/test_userdata_rig.py -x`: 39 passed.
- `uv run mypy src`: Success, no issues in 210 source files.
- `uv run ruff check`: All checks passed. `uv run ruff format --check`: 654 files already formatted.
- Extra: `tests/test_no_unratified_defaults.py tests/test_fake_exchange_v2.py tests/test_execution_limits.py`: all passed. The full suite was not run (the orchestrator runs it after the merge).

## Known Stubs

None. (`alert_sink` and `emergency_closer` are injected and unused until plan 19-14; they are interfaces, not placeholder data.)

## Threat Flags

None. T-19-26 (missed stream event): REST poll of every AWAITING_FILL entry, same result as the stream path (tests). T-19-27: protection only on REST ACTIVE (`test_a_stop_that_is_not_active_on_rest_never_counts_as_protected`). T-19-28: `blocks_new_entries()` exposed for plan 19-13; constructor refuses unset limits; Hedge refused.

## Self-Check: PASSED

- Files exist: src/execution/protection.py, tests/support/protection_doubles.py, tests/test_protection_coordinator.py, tests/test_protection_router_rig.py.
- Commits on p19-11 (RED before GREEN): 9db28a3 test, 6f456be feat, 90f3984 test, 8c7bfe9 feat, c3bede1 test (Task 3, no RED run, see deviations); `git rev-list --count 4e37e15..HEAD` was 5 before this SUMMARY commit.
- No STATE.md, ROADMAP.md or file outside files_modified changed.
