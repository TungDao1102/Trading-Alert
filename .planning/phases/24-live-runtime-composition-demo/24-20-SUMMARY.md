---
phase: 24-live-runtime-composition-demo
plan: 20
subsystem: live
status: complete
tags: [reconcile, sweeper, safe-mode, lot-filters, composition, exec-02]
requirements-addressed: [EXEC-02]
requires: [24-05, 24-12, 24-13]
provides:
  - "src/live/reconcile.py: ReconcileBundle, build_reconcile, build_lot_filters, make_risk_reducer, entry_good_till_from_store, entry_good_till_by_plan_hash, reconcile_tick_once"
  - "SafeModeController(spill=...) and SafeModeController.load(spill=...)"
affects: [24-19, 24-26, 24-27]
key-files:
  created:
    - src/live/reconcile.py
    - tests/test_live_reconcile_wiring.py
  modified:
    - src/reconcile/safe_mode.py
    - tests/test_safe_mode_persistence.py
    - tests/test_controller_rehydrate.py
key-decisions:
  - "No second position verifier: ReconcileLoop already hands the sweeper its own (two fresh adapter reads, a non-Decimal row raises), so make_position_verifier from the plan was not written."
  - "make_risk_reducer steps the coordinator only. MarketEmergencyCloser has no step and is called only from the coordinator, so stepping the coordinator IS the closer's pending-action retry. The closer is accepted and unused so the composition names both parts."
  - "Spill record only for SAFE_MODE_ENTER, SAFE_MODE_REENTER and the unreadable-start record. Exit rows are not spilled: a spilled EXIT row would claim an exit that did not happen."
  - "OrphanSweeper is built without now_utc; the loop passes the tick time on every sweep. A test patches datetime in the sweeper and controller modules with a class whose now() raises."
plan_head_before: f76eacb857742886d156e121945fda992c59873c
plan_head_after: 39417fb50f67ef64ff708869cfd096715a574b3c
commits: 2
actuals:
  tokens: 36000
  tasks: 3
  commits: 2
completed: 2026-10-31
---

# Phase 24 Plan 20: Reconcile composition Summary

`build_reconcile` composes the real `ReconcileLoop`, `OrphanSweeper`, `UnknownEntryResolver` and `LotFilterSource` over one adapter, the durable SAFE_MODE controller, the coordinator, the alert sink and the plan 24-19 feed and stream sources; `SafeModeController` now leaves its entry record in a spill when the journal is down.

## What was built

- `src/live/reconcile.py`
  - `build_reconcile(*, adapter, gate, safe_mode, intent_store, coordinator, closer, alerts, journal, limits, binance_limits, feeds, stream, lot_filters, pending_actions, plan_store)` returns a frozen `ReconcileBundle(loop, sweeper, resolver, lot_filters)`. The loop gets `unknown_entries`, `feeds`, `stream`, `lot_filters`, `pending_actions`, `risk_reducer`, `entry_good_till` and `feed_clock_skew=clock_skew_from_drift(binance_limits.drift)` (WR-B6). Refusals happen at build, from the existing constructors: non-durable controller (ValueError), tick interval not strictly below `max_unprotected_ms` (`ExecutionLimitsInvalid`), unset limit (`ExecutionLimitsNotConfigured` naming the key).
  - `build_lot_filters(*, adapter, store, snapshot_store, limits, clock)` returns `LotFilterSource(..., snapshot_for=snapshot_store.get)` for `MarketEmergencyCloser(lot_filters=...)` (D081 Q3).
  - `entry_good_till_from_store(plan_store)` (resolver: `IntentRecord` to GTD) and `entry_good_till_by_plan_hash(plan_store, intent_store)` (loop: plan hash to GTD). Both use the stored plan expiry floored to the second, the same value the manager sends as `goodTillDate`.
  - `make_risk_reducer(coordinator, closer)` and `async reconcile_tick_once(bundle, now_utc)` (the scheduler task body; the loop's own lock gives `TICK_SKIPPED_OVERLAP`).
- `src/reconcile/safe_mode.py`: optional `spill` (a one-method `SafeModeSpill` Protocol, no `src.ops` import) on the constructor and `load`. On a failing journal write of an entry, the same event goes to the spill and the journal error still propagates; a failing spill is swallowed. Without a spill nothing changes.
- Tests: `tests/test_live_reconcile_wiring.py` (21 tests), 7 spill cases in `tests/test_safe_mode_persistence.py`.

## Verification

- `uv run pytest -m "not docker"`: test_live_reconcile_wiring, test_reconcile_loop, test_sweeper_verifier_failure, test_live_ast_guards, test_no_unratified_defaults, test_safe_mode_persistence, test_safe_mode_reentry, test_safe_mode_exit_operator, test_controller_rehydrate, test_live_alerts_wiring, test_agents_md (all pass); test_phase20/21/23_gate, test_reconcile_queue_order, test_live_exchange_wiring, test_live_tracer, test_protection_sweep_spill (all pass).
- Composed tests: a protected position from the real tracer path reconciles clean (agreement, no SAFE_MODE, lot-filter refresh stored last); an orphan stop leg is cancelled with the injected time while `datetime.now` raises in the sweeper and controller modules; an unshown local entry enters SAFE_MODE and its DIVERGENCE alerts are sent through the real sink and sender; an unreadable intent source enters DB_FAILURE and its SAFE_MODE alert is sent; the three build refusals; overlapping ticks; lot filters live, stored (stale), plan snapshot (stale), unknown plan fails closed, an entry never gets a stored row; a real `MarketEmergencyCloser` closes using the source; stale-entry alert from the stored plan expiry; risk reducer awaited before the reads when a pending row is open; feed skew behaviour at skew minus 1 ms (fresh) and skew plus 1 s (stale).
- `uv run mypy src` clean (280 files); scoped `ruff check` and `ruff format --check` clean; `verify_decision_alignment.py all` ALL_PASS; `pyproject.toml` and `uv.lock` unchanged.
- NOT run (by instruction): PostgreSQL tests (`tests/test_lot_filters_pg.py`, `tests/test_safe_mode_persistence_pg.py`) and the full suite. **Gap:** the plan's `TRADING_CI_STRICT=1 ... test_lot_filters_pg.py test_safe_mode_persistence_pg.py` line is not covered. The Pg stores are only touched through their existing Protocols; no persistence file changed.
- Line endings: the working copies of `safe_mode.py` and `test_safe_mode_persistence.py` are CRLF through autocrlf (index LF); edits were made with the Edit tool, `git diff --stat` shows only the added lines.

## Deviations from Plan

1. **[Rule 1 - redundancy] `make_position_verifier` not written.** The loop already passes the sweeper `self._position_amount` (two fresh reads, non-Decimal raises). A second verifier would be a second sweep path (Don't Hand-Roll).
2. **`make_risk_reducer(coordinator, closer)` steps only the coordinator** (see key decisions); no closer step exists.
3. **`build_reconcile` takes `lot_filters` and `plan_store`-based good-till helpers differently from the listed signature.** `lot_filters` is a required argument (the closer needs the same source before the loop is built, plan 24-27 builds it with `build_lot_filters` first). `build_lot_filters` takes `store` and `snapshot_store` objects instead of the Pg class names.
4. **[Rule 3] `tests/test_controller_rehydrate.py::test_constructor_signatures_are_unchanged`** pins the constructor parameter list; one line added for `spill` (not in the plan's file list; forced by the new optional keyword).
5. The plan text "after two ticks with zero position reads" is, in the code, two consecutive reads inside one sweep (sweeper rule T-8-30); the test asserts one tick cancels after two zero reads.

## Items for 24-DEFERRED

1. Stored-fallback maximum age of a lot-filter row: owner number, NOT built (`LotFilterSource` has none).
2. WR-B7: lot-filter refresh inside the tick lock has no timeout; a timeout is a new owner number, NOT built.
3. The loop and the resolver call sync stores (`list_unresolved_intents`, `list_open`, plan store `get_trade_plan`, the snapshot store) directly on the event loop; moving them behind `StoreExecutor` (24-05) needs a change in `src/reconcile/loop.py` and `intent_recovery.py`. The `LotFilterSource` store calls from the closer are sync too.
4. `entry_good_till_by_plan_hash` learns hash to trade plan id from unresolved ENTRY intents seen in this process; an entry acknowledged before a restart has no known plan id, its stale-entry alert is skipped (the loop journals `GOOD_TILL_UNKNOWN` once per order). A plan lookup by hash needs `src/persistence/entities.py` (not in this plan).
5. For plan 24-27: the shipped limits file still has `stale_feed.max_user_data_silence_ms` NOT_CONFIGURED (owner-open), so `build_reconcile` refuses on the shipped limits (the loop's `require_live_ready`). The test `test_the_build_names_an_unset_limit` pins the named key. 24-27 must also: pass `bundle.lot_filters` (built by `build_lot_filters`) to `MarketEmergencyCloser(lot_filters=...)`, pass `spill=` to `SafeModeController`, pass `alerts.safe_mode_observer` as its `on_enter`, restore the coordinator before the first tick, and schedule `reconcile_tick_once` at `limits.reconcile_tick_interval_ms`.

## DECISIONS row

None needed from this plan.

## Known Stubs

None.

## Threat Flags

None. T-24-58: two zero position reads before a cancel (existing rule), composed test cancels only after both. T-24-59: patched `datetime.now` raises in the sweeper and controller modules. T-24-60: the build refuses a controller without a state store; spill on journal failure. T-24-SC: `pyproject.toml` and `uv.lock` unchanged.

## Task Commits

1. Task 3 (SAFE_MODE spill, row 41): `77a09ef1`
2. Tasks 1 and 2 (reconcile composition and its tests, committed together because they share one file pair): `39417fb5`

## Self-Check: PASSED

- FOUND: src/live/reconcile.py, tests/test_live_reconcile_wiring.py, src/reconcile/safe_mode.py
- FOUND commits 77a09ef1 and 39417fb5 (ancestors of HEAD)
