---
phase: 09-live-execution-rollout
fixed_at: 2026-09-29T03:40:09Z
review_path: .planning/phases/09-live-execution-rollout/09-REVIEW.md
iteration: 1
findings_in_scope: 22
fixed: 21
skipped: 1
status: partial
---

# Phase 9: Code Review Fix Report

**Fixed at:** 2026-09-29T03:40:09Z
**Source review:** .planning/phases/09-live-execution-rollout/09-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 22 (10 Critical, 12 Warning; the 7 Info findings were out of scope for `critical_warning`)
- Fixed: 21. Ten of these are marked "requires human verification". Three of those ten (CR-04, CR-08, WR-06) are only partial fixes, and the report says which part is still open.
- Skipped: 1 (WR-07, which needs a design decision)

**Where verification ran:** in the main checkout (`workflow.use_worktrees=false`, so no isolated worktree was created). You can reproduce the results below from `master` at `8ee17fa`.

**Verification results (after all fixes):**
- `uv run pytest`: 728 passed, 5 skipped, 0 failed. Every fix added or changed tests.
- `uv run mypy src`: 5 errors, down from 9 at baseline. The 4 `arg-type` errors in `src/adapters/binance_usdm.py` are gone (WR-11). The 5 that remain are older errors in files this pass did not touch: `src/reconcile/compare.py`, `src/adapters/telegram_notify.py`, `src/ops/drills.py`, and `src/paper/supervisor.py` (2).
- `uv run mypy` on the touched source files (`src/execution/*`, `src/adapters/binance_usdm.py`, `src/ops/health.py`, `src/domain/journal.py`, `src/risk/*`): no issues.
- `uv run ruff check` (whole repo): 36 errors, down from 38. The 2 E501 errors in `tests/test_execution_gates.py` are fixed. The rest are older errors in scripts and other modules.
- `uv run ruff check` on the touched files: only 2 errors remain, both older F841 errors in `src/risk/portfolio.py` (unused `warning_threshold_quote` / `stop_threshold_quote` inside `check_portfolio`). They were in the baseline, and I left them alone.

**API changes callers must follow:** nothing in `src/` calls these functions yet, and plan 09-04 is still blocked at task 3.
- `execute_approved_plan` is now `async`. It now requires `safe_mode_controller`, `journal`, `enablement`, and `gate_kwargs`. `gate_kwargs` must contain exactly `open_algo_count`, `planned_leg_count`, and `positions_reconciled`. `risk_kwargs["now_utc"]` must equal `now_utc`.
- `attach_protectives_to_fill` no longer takes `has_protective` and now requires `safe_mode_controller`.
- `LiveEnablementController.enable(...)` now requires `health_verdict`, which must be a passing `HealthVerdict`.
- In the `ExecutionAdapter` Protocol, `cancel_order` became `cancel_normal_order(*, symbol, orig_client_order_id)`, and `query_algo_order_by_client` was added.
- `build_sl_leg` requires `price_tick_size`.
- `fold_fills` now raises on malformed or foreign events.
- The golden fixture `tests/fixtures/phase9/placement_sequences/expected.json` has a new `method_sequence`: `get_position_mode, place_entry, query_algo_order_by_client, place_algo_protective`. This follows from the probe-first SL (CR-04/CR-05) and position-mode detection (WR-02).

**Exchange facts that still need checking against the current Binance docs.** Where the code depends on one of these, it fails closed:
1. **Query-order "not found" code.** `-2013 NO_SUCH_ORDER` is deliberately not mapped to `found=False` in `query_order_by_client`. Today a probe that raises is treated as UNKNOWN, which enters SAFE_MODE and returns RECONCILIATION_REQUIRED. That is safe, but it means a genuinely rejected entry also enters SAFE_MODE. Before adding a `-2013` mapping, confirm it against the docs: a wrong mapping would allow a retry and risk a duplicate order. The existing `-2011` / `UNKNOWN_ORDER` mapping in `query_order_by_client` and `query_algo_order_by_client` should be re-checked too.
2. **Active algo statuses.** Only `algoStatus` `"NEW"` counts as "exists and active" (`_ACTIVE_ALGO_STATUSES`). Any other active state has to be confirmed before it is added.
3. **`reduceOnly` on CONDITIONAL algo orders.** The SDK accepts `reduce_only` (NewAlgoOrderReduceOnlyEnum). Still to confirm: how the exchange treats `reduceOnly=true` on a one-way TAKE_PROFIT_MARKET algo order, and that it is mutually exclusive with `closePosition=true`.
4. **MIN_NOTIONAL on reduce-only or close legs (CR-03).** It is not yet known whether this filter applies to them. If it does not, the TP1 notional gate is stricter than it needs to be.
5. **`MAX_NUM_ALGO_ORDERS` per symbol (WR-06).** This is needed before the 200 headroom literal can be replaced by a dynamic value.
6. **A `closePosition=true` STOP_MARKET with no open position.** This affects WR-07, the orphaned entry-time SL.

## Fixed Issues

### CR-01: Protective attach crashes against the real adapter (`reduce_only` kwarg), and TP1 would never be sent reduce-only

**Files modified:** `src/adapters/binance_usdm.py`, `tests/test_execution_attach.py`, `tests/test_execution_adapter_contract.py` (new)
**Commit:** 2caaac4
**Applied fix:**
- `place_algo_protective` now accepts `reduce_only: bool | None = None` and passes it to the SDK as `NewAlgoOrderReduceOnlyEnum.TRUE`, or leaves it out when it is None or False.
- It raises `ValueError` if `close_position=True` is combined with `quantity` or `reduce_only`, or if a non-close leg has no quantity.
- New contract tests bind every sized leg (one-way and hedge) against the real adapter signature. They drive the real adapter against a fake SDK to check `reduceOnly` on the wire.
- The attach test fake now binds kwargs against `inspect.signature(BinanceUsdmAdapter.place_algo_protective)`.

### CR-02: Adapter exceptions during attach leave the position unprotected with no SAFE_MODE; the default `safe_mode_controller=None` silently drops the signal

**Files modified:** `src/execution/manager.py`, `tests/test_execution_attach.py`
**Commit:** 5814046
**Applied fix:**
- Each leg placement now goes through `_place_protective_leg`, which catches any adapter exception and treats it as an unconfirmed leg. The result is `ENTRY_WITHOUT_PROTECTIVE` plus SAFE_MODE, always returned as an `AttachOutcome`.
- `AttachOutcome.failure_detail` records the leg role and the exception type. It never records the exception message.
- `safe_mode_controller` is now required in both `attach_protectives_to_fill` and `require_protective_confirmation`. Passing None raises `ValueError` before any adapter call.

### CR-03: A TP1 sizing rejection aborts before the SL is placed, leaving a filled position with no stop at all

**Files modified:** `src/execution/manager.py`, `src/execution/placement.py`, `tests/test_execution_attach.py`
**Commit:** f0d3200
**Applied fix:**
- New `build_sl_leg` helper builds the close-all SL independently of quantity. `size_protectives_to_filled_qty` reuses it.
- When TP1 sizing is rejected, attach still places the SL first. It then enters SAFE_MODE and returns `ENTRY_WITHOUT_PROTECTIVE`. The rejected sizing, with its MIN_QTY_REJECT or NOTIONAL_REJECT reason code, is kept in `sized` and `failure_detail`.
- Whether MIN_NOTIONAL applies to reduce-only legs still has to be checked against the docs (item 4 above).

### CR-04: Deterministic algo IDs collide between `execute_approved_plan` and `attach_protectives_to_fill`, and across successive partial fills

**Files modified:** `src/execution/manager.py`, `tests/test_execution_attach.py`
**Commit:** 73159c1
**Status:** fixed (partial): requires human verification
**Applied fix:**
- Every leg is now probed by its deterministic `xa-` id (`query_algo_order_by_client`) before anything is placed.
- An existing active leg is adopted as confirmed and not submitted again. This covers the entry-time SL and legs placed by an earlier attach call.
- An existing leg in a non-active state is treated as unconfirmed and is never re-placed (no rescue placement).
- A probe that raises or returns an unclear result fails closed.
- Tests cover SL adoption, a second attach call, a non-active leg, and a failing probe.
- **Not done (needs a design decision):** resizing TP1 when later partial fills arrive, using cancel-then-replace with a versioned role id. An existing TP1 keeps the size of the fill it was first attached to. This is documented in the docstring. It does not leave the position unprotected, because SL and TP2 are close-all orders.

### CR-05: `execute_approved_plan` ignores the SL placement result and returns OK with the entry live and unprotected

**Files modified:** `src/execution/manager.py`, `tests/test_execution_manager.py`, `tests/fixtures/phase9/placement_sequences/expected.json`
**Commit:** 150852d
**Status:** fixed: requires human verification
**Applied fix:**
- The entry-time SL is now placed through the same probe-first confirmation as attach.
- If the SL fails or raises, the manager enters SAFE_MODE first. It then cancels the entry by its deterministic id, writing the journal entry before the cancel, via `expire_pending_entry` with the new trigger `protective_unconfirmed`. It returns NO_TRADE with `ENTRY_WITHOUT_PROTECTIVE`.
- A cancel failure is journaled and does not hide the outcome.
- The docstring now states that this path places only the pre-fill SL safety net. TP1 and TP2 are attached at fill time, and that path adopts this SL.

### CR-06: `execute_approved_plan` calls `asyncio.run` in a sync function, which cannot work in the production asyncio stack

**Files modified:** `src/execution/manager.py`, `tests/test_execution_manager.py`
**Commit:** 9244de9
**Applied fix:** `execute_approved_plan` is now `async def` and awaits every adapter call, with no `asyncio.run` left. The tests are async (`asyncio_mode = "auto"`), and a new test checks that it is a coroutine function and that the source contains no `asyncio.run(`.

### CR-07: Live placement gates are fail-open by default: enablement, placement gates, SAFE_MODE, and reconciliation are all skippable or absent

**Files modified:** `src/execution/manager.py`, `tests/test_execution_manager.py`
**Commit:** 4b983c2
**Applied fix:**
- `enablement` and `gate_kwargs` are required, and passing None raises `ValueError`. The placement gates therefore always run, including the `positions_reconciled` check.
- A new SAFE_MODE gate (`safe_mode_controller.guard_new_entries(trade_plan=...)`, which returns RECONCILIATION_REQUIRED) runs right after the enablement gate.
- Tests use the real `LiveEnablementController` and `SafeModeController`. They cover: live orders disabled, SAFE_MODE in force while enabled, unreconciled positions, and missing gates.

### CR-08: The approval binding does not check the approval's action or status, or that the executed plan is the approved plan

**Files modified:** `src/execution/manager.py`, `tests/test_execution_manager.py`
**Commit:** 1fead61
**Status:** fixed (partial): requires human verification
**Applied fix:**
- New `_check_approval_authorizes_plan` check runs after the binding. It requires `approval.action == APPROVE`, `result == status == APPROVED`, and `callback.action`, when present, to be APPROVE. Anything else returns INVALIDATED.
- It also requires the executed plan's `plan_hash` to equal both `callback.plan_hash` and `approval.request_hash`, its `trade_plan_id` to equal the approval's, and the caller's `expiry_utc` to equal `trade_plan.expiry_utc`. Anything else returns STALE_SETUP.
- I put this in the manager, not in `check_binding_full`, because the Phase 8 replay path legitimately binds SKIP callbacks.
- **Not done (needs a design decision on persisted execution state):** marking the approval as consumed, so that an at-least-once Telegram replay returns the stored outcome instead of re-running the pipeline.

### CR-09: The adapter blindly retries entry and algo placement with the same client ID on ambiguous failures, and the manager's no-blind-recovery probe is unreachable or broken

**Files modified:** `src/adapters/binance_usdm.py`, `src/execution/manager.py`, `tests/test_execution_manager.py`
**Commit:** 2c7f2b7
**Status:** fixed: requires human verification
**Applied fix:**
- `place_entry` and `place_algo_protective` now make a single attempt. The tenacity placement retries and the `_PLACEMENT_*` constants are removed.
- The manager's `_place_entry_no_blind_retry` treats either an exception or a None response as ambiguous and probes with `query_order_by_client`, reading `found` as an attribute.
- It retries at most once, and only when the probe definitively returns `found is False`.
- A probe that raises or returns anything other than a real bool counts as UNKNOWN: SAFE_MODE is entered and the result is RECONCILIATION_REQUIRED, with no retry and no SL.
- If two attempts both come back definitively absent, the result is NO_TRADE with EXCHANGE_CONSTRAINT.
- `-2013` is deliberately not mapped to not-found (see verification item 1).

### CR-10: The expiry and emergency-close paths call a non-existent adapter method, and the emergency sequence disables live orders and enters SAFE_MODE last

**Files modified:** `src/execution/manager.py`, `tests/test_execution_emergency.py` (new)
**Commit:** 8c1cbd5
**Applied fix:**
- The Protocol and callers now use the real `cancel_normal_order(*, symbol, orig_client_order_id)`.
- `expire_pending_entry` journals `cancel_failed` and then re-raises.
- `cancel_untriggered_protectives` isolates each leg: it attempts every leg and raises one `ExceptionGroup` at the end.
- `emergency_manual_close` now runs disable, then SAFE_MODE freeze, then the entry cancel, then the protective cancels. Every step is isolated, and all failures are raised together as an `ExceptionGroup`.
- New tests bind every fake call against the real adapter signatures.

### WR-01: Limit and trigger prices are never quantized to `price_tick_size`

**Files modified:** `src/execution/placement.py`, `src/execution/manager.py`, `tests/test_execution_price_ticks.py` (new), `tests/test_execution_manager.py`
**Commit:** 170e7e1
**Status:** fixed: requires human verification
**Applied fix:**
- New `quantize_price` helper does exact Decimal floor or ceil onto the tick grid.
- BUY limits round down and SELL limits round up. SL triggers round toward the entry (a tighter stop, so realized risk never exceeds the sized risk). TP triggers also round toward the entry.
- This is applied to the entry limit and SL in `execute_approved_plan`, and to the SL, TP1 and TP2 triggers in sizing. The TP1 notional check uses the rounded trigger.
- **Follow-up for a human decision:** the review asked for the same rounding in backtest and paper for parity. I did not change those engines, because doing so would change the Phase 5–7 golden fixtures. The rounding difference is at most one tick.

### WR-02: Position mode is hard-coded to `BOTH` and never detected; the Protocol and adapter types disagree

**Files modified:** `src/execution/manager.py`, `tests/test_execution_manager.py`, `tests/fixtures/phase9/placement_sequences/expected.json`
**Commit:** 757b27f
**Status:** fixed: requires human verification
**Applied fix:**
- `execute_approved_plan` now calls `get_position_mode()` at placement time. New `resolve_position_mode` maps the adapter's `PositionModeResult.dual_side_position` (which must be a real bool) to `HEDGE` or `ONE_WAY`.
- One-way mode sends `positionSide=BOTH`. Hedge mode sends LONG or SHORT on both the entry and the SL.
- If the mode cannot be determined, the result is NO_TRADE with UNCERTAIN_ACCOUNT_STATE, before any order.
- The Protocol return type is now `Any`, and the test fake returns the real `PositionModeResult`.
- `attach_protectives_to_fill` still takes `position_mode` from the caller. Its docstring now tells callers to derive it from a fresh `get_position_mode()` via `resolve_position_mode`.

### WR-03: `_is_leg_confirmed` is fail-open for any non-dict response, which is what the real adapter returns

**Files modified:** `src/execution/manager.py`, `tests/test_execution_attach.py`
**Commit:** 17ed35f
**Applied fix:**
- `algo_status` is now read as an attribute or a key, so it works on the real `AlgoPlacementResult` dataclass.
- Confirmation uses an allow-list (`{"NEW"}`). None, `""`, REJECTED, EXPIRED, CANCELED, TRIGGERED and unknown statuses are all treated as unconfirmed.
- Tests are parameterized over the real dataclass. The "exists and active" check uses the probe-first step from CR-04.

### WR-04: `fold_fills` sums unrelated fills, silently drops malformed ones, and gets the SHORT sign wrong

**Files modified:** `src/execution/fill_monitor.py`, `src/execution/manager.py`, `tests/test_execution_partials.py`, `tests/test_execution_attach.py`
**Commit:** 4e44793
**Status:** fixed: requires human verification
**Applied fix:**
- `fold_fills` now raises instead of silently skipping. It raises on missing ids, a non-Decimal quantity, an unknown side, and mismatches against the new optional `expected_symbol`, `expected_side` and `expected_order_id` filters.
- `position_amt` now moves by a signed quantity (BUY adds, SELL subtracts).
- Attach folds only this symbol's entry-side fills and no longer takes `has_protective`.
- If the fill stream is malformed or contains foreign fills, attach still places or adopts the close-all SL, enters SAFE_MODE, and returns `ENTRY_WITHOUT_PROTECTIVE`.
- Attach does not pass `expected_order_id`, because it does not know the entry's exchange order id.

### WR-05: Placement gates judge a different sizing, snapshot and clock than the order actually placed

**Files modified:** `src/execution/manager.py`, `tests/test_execution_manager.py`
**Commit:** 82c339b
**Status:** fixed: requires human verification
**Applied fix:**
- `evaluate_risk` now runs first. `decide_placement` is built from the verdict's own `sized` plus the `risk_kwargs` snapshot, symbol, side, positions, daily loss, TTL and parameter set, and the manager's single `now_utc`.
- `gate_kwargs` may contain only `open_algo_count`, `planned_leg_count` and `positions_reconciled`. Any other key raises.
- A `risk_kwargs["now_utc"]` different from `now_utc` raises.
- The asserts on the placement path were replaced by an explicit `RuntimeError`.

### WR-06: The headroom limit is hard-coded, counts are unvalidated, and early rejects misreport `daily_state`

**Files modified:** `src/execution/gates.py`, `src/risk/portfolio.py`, `tests/test_execution_gates.py`
**Commit:** 87e7d90
**Status:** fixed (partial): requires human verification
**Applied fix:**
- `open_algo_count` and `planned_leg_count` must be ints ≥ 0. Negative values and bools raise.
- `daily_state` is now worked out before any early return, using a new public `derive_daily_state` in `src/risk/portfolio.py` (same rule as `check_portfolio`). Early rejects therefore report DAILY_STOP instead of NORMAL.
- **Not done:** detecting the limit dynamically from `MAX_NUM_ALGO_ORDERS`. That needs a new field in `ConstraintSnapshot`/`SymbolFilters`, adapter projection from exchangeInfo, and the doc check in item 5. The literal 200 stays as a conservative fallback, and a "KNOWN GAP" comment now marks it.

### WR-08: The health aggregate passes on incomplete probe sets and never gates enablement

**Files modified:** `src/ops/health.py`, `src/execution/enablement.py`, `tests/test_execution_health.py`, `tests/test_execution_enablement.py`, `tests/test_execution_manager.py`
**Commit:** c587377
**Status:** fixed: requires human verification
**Applied fix:**
- `run_health_checks` returns HEALTH_CHECK_FAILED unless there is exactly one non-FAIL result for each name in `ALL_CHECK_NAMES`. A duplicate or missing probe counts as a failure.
- `HealthVerdict.__post_init__` enforces completeness on any PASS verdict, so a hand-built partial "OK" is impossible.
- `LiveEnablementController.enable(...)` now requires a passing `health_verdict`. Otherwise it raises before writing the journal, and the flag stays disabled.
- The DEGRADED policy is unchanged: it still does not block. Whether amber health should block enablement is a policy decision.

### WR-09: `journal_event_id` values collide on the same injected timestamp (the DB primary key)

**Files modified:** `src/domain/journal.py`, `src/ops/health.py`, `src/execution/enablement.py`, `src/execution/manager.py`, `tests/test_execution_health.py`
**Commit:** d029a21
**Applied fix:**
- New `content_hash_event_id` builds the id as `{prefix}_{sha256(event_type, entity_id, occurred_at, payload_json)}`, at most 128 characters.
- It is used for health-check, enablement and cancel journal events.
- Ids stay deterministic, and different events at the same millisecond no longer collide. Byte-identical events still map to the same id on purpose, since they carry no new information.

### WR-10: The enablement journal payload records the pre-transition state

**Files modified:** `src/execution/enablement.py`, `tests/test_execution_enablement.py`
**Commit:** 670d51b
**Applied fix:** The payload now records `live_orders_disabled` as the state after the transition, plus `live_orders_disabled_before`. This matches the `live_orders_disabled` semantics used in the enablement fixtures.

### WR-11: Quality gates are red: `mypy --strict` and `ruff check` fail

**Files modified:** `src/adapters/binance_usdm.py`, `tests/test_execution_gates.py`, `tests/test_execution_adapter_contract.py`
**Commit:** 0d730e9
**Applied fix:**
- New `_decimal_to_wire(value: Decimal) -> Any` helper converts values with `format(value, "f")` at the SDK boundary. It covers the entry price and quantity and the algo trigger price and quantity, with no `type: ignore`.
- This also fixes IN-02 (exponent notation reaching the wire). A test checks that `1.06E+2` and `1E-3` go out as `"106"` and `"0.001"`.
- The E501 test lines are wrapped.
- mypy on the adapter is clean.

### WR-12: The tests validate fakes, not the adapter contract, and leave the risky paths untested

**Files modified:** `tests/test_execution_attach.py`, `tests/test_execution_health.py`, `tests/test_execution_manager.py`, `tests/test_execution_modes.py`, `tests/test_execution_partials.py`. The contract-test part of this finding was delivered in the commits for CR-01, CR-09, CR-10, WR-03 and CR-07.
**Commit:** 8ee17fa
**Applied fix:**
- The purity tests now find their files via `Path(__file__).resolve().parents[1] / "src" / ...`. The fill-monitor purity test now fails instead of skipping.
- Checked by running the purity tests from `tests/` as the working directory.
- Earlier commits already delivered the rest of this finding:
  - The manager, attach and emergency fakes bind every call to the real adapter signature.
  - The gated manager path, the emergency sequence, and a failing or raising SL are now tested.
  - The ambiguous-entry tests cover `found=False`, a raising probe, and an unclear probe.

## Skipped Issues

### WR-07: Entry expiry orphans the entry-time close-all SL, and the emergency close opens an unprotected window

**File:** `src/execution/manager.py:627-688, 761-832`
**Reason:** Skipped because both halves need a design decision that goes beyond a local fix.
1. Expiry would have to cancel the plan's protective legs "with zero fills". But `expire_pending_entry` does not know the fill state. The fix needs an agreed source of truth for fills at expiry time (the reconciler, persisted fill rows, or a caller contract), plus the doc check on how `closePosition=true` behaves with no open position (item 6).
2. For the emergency path, the fix is either to close the position with an explicit operator-directed reduce-only MARKET order, which is a new order type and adapter method outside the V1 approval model, or to keep the SL until the position is confirmed flat, which needs a flat-confirmation contract.

CR-10's reordering already guarantees that live orders are disabled and SAFE_MODE is entered before any cancel runs.
**Original issue:** `expire_pending_entry` cancels only the entry, so the close-all SL placed at entry time stays live. In one-way mode it can later close another plan's position on the same symbol. `emergency_manual_close` cancels the SL/TP legs before the operator has closed the position, so a live position has no stop for an unbounded time.

---

_Fixed: 2026-09-29T03:40:09Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
