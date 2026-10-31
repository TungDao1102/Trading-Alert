---
phase: 24-live-runtime-composition-demo
plan: 21
subsystem: live
tags: [scheduled-cancel, entry-expiry, sweeper, algo-cancel-lag, entry-price, decimal-boundary, phase-24]

requires:
  - phase: 24-live-runtime-composition-demo
    provides: "24-10 scheduler (LiveCadences.scheduled_cancel_check); 24-15 SDK boundary conventions; 24-04 live rig"
provides:
  - "src/live/scheduled_cancel.py: cancel_expired_entries_once, ScheduledCancelResult, PlanStore and CoordinatorView ports"
  - "tests/support/fake_binance_exchange.py: algo_cancel_query_lag"
  - "src/reconcile/sweeper.py: STILL_OPEN verdict re-checked against the open-algo list"
  - "src/adapters/binance_usdm.py: PositionSnapshot.entry_price_from_float and the entry-price conversion"
affects: [24-27, 24-34, 25]

key-files:
  created:
    - src/live/scheduled_cancel.py
    - tests/test_live_scheduled_cancel.py
    - tests/test_sweeper_cancel_lag.py
    - tests/test_adapter_entry_price_decimal.py
  modified:
    - tests/support/fake_binance_exchange.py
    - src/reconcile/sweeper.py
    - src/adapters/binance_usdm.py

key-decisions:
  - "Trigger reason is the canonical `expiry_time` (EXECUTION_SPEC section 4, `_EXPIRY_TRIGGERS`), not the plan's descriptive `PLAN_EXPIRED`; adding a trigger would have meant editing src/execution/manager.py, which the plan does not list."
  - "The plan store port is keyed by plan hash: `async expiry_utc_for(plan_hash) -> datetime | None`. PlanProtection carries no trade_plan_id and the PG store has no by-hash reader, so the composition root (24-27) supplies the adapter."
  - "Only AWAITING_FILL plans are examined; only status NEW with an executed quantity that is exactly Decimal zero is cancelled. Everything else is left to the coordinator."
  - "Sweeper: only the STILL_OPEN verdict triggers the open-list re-check (the lag signature). UNKNOWN (query failed) keeps the older unverified result."
  - "entry_price: the installed SDK (17.4.0) types entryPrice as a strict string, so the exchange text is used exactly; a float that still arrives is converted by its text and flagged entry_price_from_float=True."

requirements-completed: [EXEC-02]  # not marked in STATE/REQUIREMENTS: the orchestrator owns those files

plan_head_before: f76eacb8
plan_head_after: b9f41e8d5b2b32398012e1f0daa16de967f9daf3
actuals:
  tokens: 30000
  tasks: 3
  commits: 3
status: complete
completed: 2026-10-31
---

# Phase 24 Plan 21: Scheduled cancel, algo cancel lag, entry price Decimal Summary

**A scheduler task body now cancels a resting entry past its plan expiry only after a fresh REST read shows zero fills; the sweeper no longer reads a lagging by-id answer as a failed cancel; and the position entry price is never turned into a noisy Decimal at the SDK boundary.**

## Accomplishments

### Task 1 (tracer) - scheduled cancel of an expired unfilled entry (D-13)

`cancel_expired_entries_once(*, coordinator, plan_store, adapter, journal, spill, now_utc)`:

- walks `coordinator.protections()`, AWAITING_FILL only;
- reads the stored expiry through the plan store; before it nothing else happens (no REST call);
- one fresh `query_order_by_client`; cancels only on found, status NEW and executed quantity exactly zero, through the single `expire_pending_entry(..., trigger_reason="expiry_time")` call (acts first, verifies afterwards, journals its own pre/post images);
- left to the coordinator and journaled (`LIVE_SCHEDULED_CANCEL`, deterministic id per plan/outcome/detail): any executed quantity or PARTIALLY_FILLED/FILLED, unknown executed quantity, entry not found, unexpected status;
- a failing read, cancel or store read is journaled by exception class name and never raised; an entry already ended with no fill returns `not_resting` and writes nothing, so a second run does nothing;
- no leg cancel, no placement call, no retry, no wall clock (the module text is asserted free of those names).

### Task 2 - lagging fake and the sweeper rule (D-34)

- Fake: `BinanceSemanticsFakeAdapter(algo_cancel_query_lag=timedelta(0))`. After an algo cancel, `query_algo_order_by_client` answers NEW until the fake's `now_utc` passes the lag; the open-algo list is empty at once. A triggered algo is not affected. Default zero leaves every older test unchanged.
- Sweeper: after the post-cancel query, a `STILL_OPEN` verdict is re-checked once with `snapshot_open_algo_orders(symbol=...)`; an id absent from a list that was read successfully counts as swept (post-image carries `verified_by: open_algo_list`), with no second cancel, no `SWEEP_SKIPPED`, no escalation. A list that cannot be read, still holds the id, or an adapter without the read (narrow fakes) keeps `cancel_unverified`.

### Task 3 - entry_price at the SDK boundary (D-34)

**Chosen path, pinned by tests and stated here:** the string path. The installed SDK model `PositionInformationV3ResponseInner` (SDK 17.4.0) types `entryPrice` as `StrictStr`, a JSON number is refused by its validation (the SDK then returns raw dicts, which the adapter refuses with `AttributeError`), so the exchange text reaches the adapter and `Decimal(text)` is exact: `"84816.4"` stays `Decimal("84816.4")`. As defence in depth, a float that still reaches a row (a model built without validation, another SDK version) is converted through its shortest text, never rounded or quantized, and `PositionSnapshot.entry_price_from_float=True` (new field, default False) tells readers. I could not reproduce the Demo noise with the installed SDK; the 2026-10-04 probe probably ran an older model or its own float handling.

**Residual for Phase 25:** a float cannot be repaired after the fact, and no consumer reads the new flag yet (the reconcile bound check and the liquidation estimate were not edited; they are outside this plan's files). With the installed SDK the flag is never True.

### Criterion-5 items that need no code

- `-4509` (closePosition stop before a fill): the D079 fill-driven protection model; covered by tests/test_fake_exchange_v2.py, tests/test_protection_branches.py, tests/test_protection_supervision.py, tests/test_exchange_errors.py.
- Close helper: `place_market_close` (Phase 19); covered by tests/test_emergency_market_close.py and tests/test_binance_usdm_signed_calls.py.

## Verification

- `uv run pytest -m "not docker"` on tests/test_live_scheduled_cancel.py, test_sweeper_cancel_lag.py, test_adapter_entry_price_decimal.py, test_reconcile_loop.py, test_protection_router_rig.py, test_binance_usdm_signed_calls.py, test_sweeper_verifier_failure.py, test_live_ast_guards.py, test_no_unratified_defaults.py: all pass.
- Directly affected suites also pass: test_cancel_verification, test_phase8_audit_reviewfix, test_drills, test_reconcile, test_protection_stop_lost, test_protection_liquidation, test_manual_controls, test_journal_ids, test_intent_recovery*, test_execution_manager, test_emergency_close_filters, test_daily_stop, test_system_throttle_protection, test_fake_exchange_v2, test_fake_binance_semantics, test_execution_attach, test_emergency_market_close, test_live_tracer, test_adapter_strictness, test_binance_usdm_source_guard, test_domain_no_float.
- `uv run mypy src`: no issues (280 files). Scoped `ruff check` and `ruff format --check`: clean.
- `git grep -e cancel_algo -e place_algo_protective -- src/live/scheduled_cancel.py`: nothing.
- `git diff --exit-code -- pyproject.toml uv.lock`: clean. CRLF line endings of sweeper.py, binance_usdm.py and the fake kept (edits were byte-aware).
- No PostgreSQL test (`*_pg.py`, TEST_DATABASE_URL) was run and no full suite; none of this plan's code touches PG, but the `*_pg.py` files that import the fake or `OrphanSweeper` (test_persistence_journal_pg, test_intent_recovery_pg, test_approval_replay_pg and others) were NOT run: a gap for the orchestrator's run.

## Deviations from Plan

**1. [Rule 3 - Blocking] Trigger name.** The plan says "trigger PLAN_EXPIRED"; `expire_pending_entry` accepts only its canonical triggers and `expiry_time` is the one for expiry. Used `expiry_time`; no edit to manager.py.

**2. [Rule 3 - Blocking] Plan store keyed by plan hash.** See key-decisions. Tests adapt the rig's in-memory plans.

**3. Task commits.** Tasks 1, 2, 3 are commits 778b75e3, 3a421b0f, b9f41e8d (one each). The tracer feedback gate (re-run of the verify command) passed before Task 2.

## Hand-off notes (for 24-27 and 24-34)

- 24-27 must schedule `TaskSpec("scheduled_cancel", lambda: cancel_expired_entries_once(coordinator=wiring.coordinator, plan_store=..., adapter=..., journal=..., spill=..., now_utc=clock()), interval=cadences.scheduled_cancel_check)` and supply a `PlanStore` whose `expiry_utc_for(plan_hash)` reads the stored plan (via the StoreExecutor read). The store needs a by-hash lookup of `trade_plans.expiry_utc` (the existing `get_trade_plan` is keyed by trade_plan_id).
- 24-34 can use `BinanceSemanticsFakeAdapter(algo_cancel_query_lag=...)` for its coordinator rule; `cancel_algo` (the test-side cancel) and the adapter cancel both honour the lag.
- No DECISIONS row is needed.

## Known Stubs

None.

## Threat Flags

None. Mitigations: T-24-61 (zero-fill REST read required; partial fill left to the coordinator; tests), T-24-62 (no algo call in the module; grep and source test), T-24-63 (open-list rule; lag tests), T-24-64 (string path, flag, no rounding; tests), T-24-SC (no dependency change).

## Self-Check: PASSED

- src/live/scheduled_cancel.py, tests/test_live_scheduled_cancel.py, tests/test_sweeper_cancel_lag.py, tests/test_adapter_entry_price_decimal.py exist.
- Commits 778b75e3, 3a421b0f, b9f41e8d are ancestors of HEAD.
