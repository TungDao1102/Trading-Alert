---
phase: 19-execution-plan-binding-price-check
plan: 13
subsystem: execution
tags: [execution-manager, plan-binding, pre-placement, price-check, hedge-refusal, limits-gate, golden-fixture, rehearsal, tdd, binance]
requires: ["19-01", "19-02", "19-03", "19-05", "19-08", "19-09", "19-10", "19-11", "19-12"]
provides:
  - "src/execution/live_context.py: LivePlacementContext (signal, plan_constraint_snapshot, execution_limits, protection_registry, latest_closed_bar_close, gtd_clock_margin, tp1_quantity_fraction)"
  - "src/execution/manager.py: execute_approved_plan(..., live_context) with gates 1c, 2b, 5b, 5c, 5d, 5e, 5f; ExecutionAdapter Protocol gains get_mark_price, snapshot_open_normal_orders, snapshot_open_algo_orders"
  - "scripts/demo_rehearsal.py: build_live_context, require_execution_limits_set, RehearsalAlertSink, load_drift_limits, RunContext.execution_limits and drift_limits, GuardedAdapter get_mark_price, symbol_lot_filters, error_facts"
  - "tests/fixtures/phase9/placement_sequences regenerated (inventory below)"
affects: [19-14, 19-15, 19-16, 19-17]
tech-stack:
  added: []
  patterns: [one bundled keyword instead of many, pure refusals before reads before position mode, every refusal before consume, failed read is not available]
key-files:
  created:
    - src/execution/live_context.py
  modified:
    - src/execution/manager.py
    - tests/test_execution_manager.py
    - tests/fixtures/phase9/placement_sequences/input.json
    - tests/fixtures/phase9/placement_sequences/expected.json
    - scripts/demo_rehearsal.py
    - tests/test_demo_rehearsal_flow.py
    - tests/test_exchange_error_rejections.py
decisions:
  - "live_context is a required keyword with no default; None raises ValueError before any adapter call (fail closed, like intent_store). _GATE_KWARG_KEYS is unchanged"
  - "Order of the new gates: 1c binding (after 1b, replay stays first), 2b limits (right after enablement), then after the existing gate 5: 5b quantity, 5c snapped geometry, 5d TP1 sizeable (pure, no adapter call), 5e three reads and evaluate_pre_placement, 5f position mode with the Hedge refusal; consume and placement after that"
  - "Symbol, sides and approved quantity used at placement come from the BoundPlan, never from a caller value"
  - "TP1 is checked at the risk-sized quantity (what will be placed) with the frozen size_protectives_to_filled_qty in One-way mode; a rejection is the plan's NO_TRADE with its own MIN_QTY_REJECT or NOTIONAL_REJECT; no single-TP fallback (O-03 auto default)"
  - "A plan whose take_profit_json cannot be parsed is STALE_SETUP (unusable plan, fail closed); an approved quantity that is not positive is QUANTITY_ABOVE_APPROVED; an unreadable registry counts as blocking"
  - "A failed adapter read is None: mark price -> MARK_PRICE_UNAVAILABLE, either order snapshot -> SYMBOL_STATE_UNAVAILABLE. Any returned order row without a symbol counts as on the bound symbol"
  - "The Demo rehearsal checks the limits before it opens the channel or asks for an approval, so an unset file costs the owner no tap"
status: complete
commits: 6
plan_head_before: 592863d10022d704edfd7bdc3a6f4966fbc0909e
plan_head_after: 0fa57b1828e0e93afe59b94e368c64ce2f5082ea
actuals:
  tokens: 95000
  tasks: 3
  commits: 6
---

# Phase 19 Plan 13: Execution plan binding and pre-placement gates in the manager Summary

`execute_approved_plan` now places only the symbol, side and size of the approved, hash-verified plan, and every refusal (binding, unset limits, quantity, snapped geometry, TP1, live price, same-symbol exposure, unprotected positions, status, invalidation, validity, Hedge) is a NO_TRADE decided before the approval is consumed; the Demo rehearsal builds the new context and, with the committed NOT_CONFIGURED limits file, aborts before any mutation.

## What was built

1. **Tracer (Task 1).** `LivePlacementContext` is a frozen, keyword-only dataclass with seven required fields and type/range validation (no field has a default). `execute_approved_plan` takes it as the new required keyword `live_context`. Gate 1c runs right after the approval-authorizes-plan gate: `bind_plan` (hash re-derivation, Signal, strategy version, parameter set, symbol and side cross-checks) then `check_working_type` on the plan constraint snapshot. The placement code now takes `symbol`, `entry_side`, `exit_side` and the position side from the `BoundPlan`. The stored-outcome replay is untouched and still precedes the new gates (a refusing context after a consumed approval returns the stored outcome with zero adapter calls).
2. **Pre-placement gates (Task 2).** Gate 2b refuses with `LIMITS_NOT_CONFIGURED` if `execution_limits.unset_keys()` is non-empty, after enablement and before SAFE_MODE and risk. After the unchanged gate 5: 5b `check_quantity_bound` (never clipped), 5c `check_snapped_geometry` on the tick-snapped limit and stop, 5d the frozen `size_protectives_to_filled_qty` at the sized quantity, then 5e: `get_mark_price`, `snapshot_open_normal_orders(symbol)` and `snapshot_open_algo_orders(symbol)` (a raising read becomes `None`), `registry.blocks_new_entries()` once, and `evaluate_pre_placement` with positions from `risk_kwargs["open_positions"]`, the Signal's `invalidated_at_utc`, the bar close, the TEST_ONLY-or-owner limits and the mark reading. 5f: an unreadable mode stays `UNCERTAIN_ACCOUNT_STATE`, `HEDGE` is `HEDGE_MODE_UNSUPPORTED`; `order_position_side` is now always `BOTH`. The `ExecutionAdapter` Protocol has the three reads.
3. **Rehearsal (Task 3).** `derive_plan` computes the hash with `plan_hash_from_fields` (it was a run-id hash) and writes a `CANDLE_CLOSE` invalidation rule (level = stop) instead of `DEMO_REHEARSAL`; the quantity fields already carried the sized quantity. `build_live_context(ctx, plan, filters, constraints, now, safe_mode=, intent_store=)` builds the Signal, a MARK_PRICE plan snapshot from the re-checked filters, the limits (injected or `config/execution/execution-limits-v1.toml`), a `ProtectionCoordinator` over the guarded adapter with a `MarketEmergencyCloser` and a `RehearsalAlertSink` (evidence entry plus operator instruction), the latest closed 1h kline close (skipping the forming bar, `None` if unreadable), the larger of the ratified drift limits as the GTD margin and `TP1_QUANTITY_FRACTION`. `require_execution_limits_set` runs at the start of `run_order_scenario` (before the channel opens) and records a failed step `execution_limits` naming `LIMITS_NOT_CONFIGURED` and the unset keys, then raises `RehearsalAbort` (exit 3, `ABORTED_NO_ORDER`, `mutating_attempts == 0`). `main(..., execution_limits=)` and `build_context(..., execution_limits=, drift_limits=)` are the injection seams.

## Gate order (final)

0 identity and replay, 1 binding+expiry, 1b approval authorizes plan, **1c plan binding and working type**, 2 enablement, **2b limits ready**, 3 SAFE_MODE, 4a cost rates, 4b risk, 5 `decide_placement`, **5b quantity bound, 5c snapped geometry, 5d TP1 sizeable** (pure), **5e reads then `evaluate_pre_placement`** (status, invalidation, validity, symbol free, mark price), **5f position mode and Hedge**, then consume ENTRY intent and placement (unchanged). Tests pin the order by failing two gates at once in nine pairs (`test_gate_order_is_pinned_by_failing_two_gates_at_once`) and pin that 5b-5d make zero adapter calls even when the mark price would also cross the stop.

## Consequence for the owner (recorded, not decided)

With the committed all-NOT_CONFIGURED limits file every live and Demo placement refuses with `LIMITS_NOT_CONFIGURED` before any adapter call (`test_the_committed_not_configured_limits_file_refuses_every_live_placement`), and `scripts/demo_rehearsal.py` order scenarios abort before the approval (`test_committed_limits_end_the_main_run_as_aborted_no_order`). The Phase 18 probe `scripts/demo_probe.py` does not use this path. Q2 (mark price only), Q6 (bar close injected, producer Phase 24), Q7 (exchange snapshot is the authority for open orders, no intent cross-check), O-04 (numbers) and O-01 (LIVE stays blocked) are untouched.

## Open items found while executing (for 19-15, 19-16 and the owner)

1. **The rehearsal's far/fill geometry cannot pass gate 5e in a real Demo run.** The rehearsal zone is the single far entry price (`entry_min == entry_max`), while `check_mark_price` requires the live mark inside the zone. Once the owner sets the limits, `far` and `fill` will be refused with `MARK_PRICE_OUTSIDE_ZONE`. The flow tests only pass because the fake `get_mark_price` reports the derived entry price (`FakeDemoAdapter.gate_mark_price`, set in `run_flow`). The rehearsal needs a zone that contains the mark (which changes its limit price, sizing edge and expected prices); plan 19-15 and 19-16 already rewrite its far and fill paths, so I did not redesign it here.
2. **Expiry margin versus GTD.** `PLAN_EXPIRY_MARGIN` is 10 minutes after the approval timeout, so the remaining validity at placement is `900 s - tap latency`; it must exceed 600 s plus the drift margin and the owner's `min_remaining_validity_seconds`. A tap slower than about 299 s, or an owner minimum above about 880 s, refuses with `VALIDITY_TOO_SHORT`.
3. **The emergency closer is wired but unusable until 19-16.** `GuardedAdapter` has no `place_market_close` (plan 19-16 adds it, together with its DRY_RUN block and the safety-test entry). No entry is registered with the coordinator in this plan (19-15 does that), so `blocks_new_entries()` is `False` and the closer is never called.

## Golden fixture inventory (D048 style)

`tests/fixtures/phase9/placement_sequences/input.json`:

| Field | Before | After | Why |
|-------|--------|-------|-----|
| `plan_hash` | `3333...3333` (synthetic) | `64464f8e874de2316bbf2847a1dbc6ede3f1914cf7ae3dc0e21feb583fd1e7d6` | `plan_hash_from_fields` of the plan's own fields; the binding refuses a hash the planner does not reproduce (pinned by `test_fixture_plan_hash_is_the_rederived_hash`) |
| `suggested_quantity` | `0.500` | `2.4157` | F-203: the plan quantity was below the risk-sized one; 10 / 4.1396 |
| `quantity_before_rounding` | `0.500` | `2.4157` | same |
| `quantity_after_rounding` | `0.500` | `2.415` | equals the risk-sized quantity floored to the 0.001 step; gate 5b now passes with equality |
| `signal` (new) | absent | `strategy_id`, `setup_type`, `source_timeframe`, `source_candle_close_utc`, `detected_at_utc`, `expires_at_utc` | the persisted Signal the binding needs (symbol, direction, strategy version and parameter set come from existing fields) |
| `live` (new) | absent | `mark_price` 101.00, `mark_age_ms` 1000, `latest_closed_bar_close` 101.50, `tp1_quantity_fraction` 0.5 | the context and the fake adapter's mark reading |

Every other field is unchanged (ids, token, chat, times, costs, constraints, parameter set).

`expected.json`:

| Field | Before | After |
|-------|--------|-------|
| `plan_hash` | `3333...3333` | the re-derived hash |
| `method_sequence` | `get_position_mode, place_entry, query_algo_order_by_client, place_algo_protective` | `get_mark_price, snapshot_open_normal_orders, snapshot_open_algo_orders, get_position_mode, place_entry, query_algo_order_by_client, place_algo_protective` |
| `entry_client_order_id` | `x-33333333333333333333333333333333EN` | `x-64464f8e874de2316bbf2847a1dbc6edEN` |
| `sl_algo_client_id` | `xa-3333333333333333333333333333333SL` | `xa-64464f8e874de2316bbf2847a1dbc6eSL` |
| `outcome_reason_code` | `OK` | `OK` (unchanged) |

The placed entry is unchanged: LIMIT GTC, quantity 2.415, price 101.00, then the unchanged `closePosition` stop (the single protection model is plan 19-15).

## Test inventory

Rewritten or changed in `tests/test_execution_manager.py`: `test_hedge_mode_sends_explicit_position_side_on_entry_and_sl` became `test_hedge_mode_is_refused_before_any_order` (the hedge payload matrix stays proven in `tests/test_execution_modes.py`); `test_definitive_absence_allows_exactly_one_retry`, `test_probe_failure_fails_closed_to_safe_mode_without_retry_or_sl` and `test_undeterminable_position_mode_fails_closed_before_any_order` list the three reads first; `test_odd_tick_zone_mid_is_floored_for_a_buy_limit` edits the case (the zone is a hashed field, the case re-derives its hash) and gives the fake a mark inside the zone; the entry-id literals now come from `expected.json`. New: 34 test functions (several loop over variants) for the context, the binding refusals (eight variants, zero calls, no ENTRY row), replay-first, every gate above, the `risk04` pair, the committed-file refusal and the nine gate-order pairs. Each refusal test also proves the approval was not consumed: a corrected call under the same store places.

`tests/test_demo_rehearsal_flow.py`: `FakeDemoAdapter.get_mark_price`, TEST_ONLY limits injected by default in `run_flow` and `make_ctx`, plus nine new tests (hash, context, bar close, alert sink, read passthrough, committed-limits abort for context and for `main`, single unset key, taps need no limits, dry-run far reads the mark).

## Deviations from Plan

**1. [Rule 3 - Blocking] Stale pin in another file.** `tests/test_exchange_error_rejections.py`: the literal `"x-33333333333333333333333333333333EN"` became `derive_client_order_id(plan_hash=_load_input()["plan_hash"], role="ENTRY")` (import added), and the call-sequence list in `test_entry_rejection_sequence_is_unchanged_by_the_table` now starts with `*PRE_PLACEMENT_READS` (docstring sentence adjusted). Both are required by the new fixture hash and the new reads.

**2. [Rule 3 - Blocking] Stateful-fake suites needed a mark price.** `BinanceSemanticsFakeAdapter` raises for a symbol without a mark price (by design). Instead of touching the PG suites, `_run_plan` in `tests/test_execution_manager.py` calls `_prime_mark_price` (sets the fixture mark when the fake has none). The five negative controls that run a store which never remembers (`AlwaysWinsIntentStore`) in `test_approval_replay_pg.py`, `test_execution_exactly_once_pg.py` and `test_realized_risk_persistence_pg.py` would now be stopped by gate 5e (an open stop or entry on the symbol) before reaching the exchange, which makes them vacuous. `_run_plan` wraps the adapter in `_ExchangeStateBlind` (open-order snapshots answer "none", everything else delegated) only for that store, so those controls still prove the durable row is the guard (F-126, F-951). No other test file was edited.

**3. [Rule 2 - Missing critical] Fail-closed edges.** `blocks_new_entries()` raising counts as blocking; an unparseable `take_profit_json` is `STALE_SETUP`; a non-positive approved quantity is `QUANTITY_ABOVE_APPROVED`; a non-`TradePlanStatus` plan status raises `TypeError` before any order; a mark reading with a naive time or a non-Decimal price is unavailable. A symbol-less open-order row counts as on the symbol.

**4. [Rule 3 - Blocking] Rehearsal plan basis.** The pre-placement invalidation check accepts only `CANDLE_CLOSE`, so `derive_plan` writes `{"basis":"CANDLE_CLOSE","level":<stop>}` instead of `DEMO_REHEARSAL` (the plan only named the hash). `GuardedAdapter` also got `symbol_lot_filters` and `error_facts` (read-only, needed by the coordinator's adapter Protocol) next to `get_mark_price`; `place_market_close` is left to plan 19-16.

## Known Stubs

None. The `RehearsalAlertSink` records and prints only (Telegram alert UX is Phase 23, stated in its docstring).

## Threat Flags

None beyond the plan's threat model: T-19-32 (bound symbol, side and quantity, zero calls), T-19-33 (refusals before consume, failed reads are NO_TRADE, Hedge refused) and T-19-34 (limits gate and rehearsal abort) are covered by tests named above.

## Self-Check: PASSED

- Files: `src/execution/live_context.py`, `src/execution/manager.py`, `scripts/demo_rehearsal.py`, `tests/test_execution_manager.py`, `tests/test_demo_rehearsal_flow.py`, `tests/test_exchange_error_rejections.py`, both fixture files, this SUMMARY: present on branch p19-13.
- Commits: 8ebae43, 1317b13, 8addd2f, 335b027, 99ee3d3, 0fa57b1 are ancestors of HEAD.
- Verification: the plan command (six test files) 241 passed; mypy src, ruff check, ruff format --check clean; wider affected set (PG exactly-once, replay, write-ahead, recovery, realized risk, redelivery, isolation, source guard, defaults, pre-placement, gates, client config, userdata replay) 388 passed. `STATE.md` and `ROADMAP.md` untouched.
