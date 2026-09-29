---
phase: 09-live-execution-rollout
reviewed: 2026-09-29T02:52:45Z
depth: deep
files_reviewed: 37
files_reviewed_list:
  - pyproject.toml
  - src/adapters/binance_usdm.py
  - src/execution/enablement.py
  - src/execution/fill_monitor.py
  - src/execution/gates.py
  - src/execution/manager.py
  - src/execution/placement.py
  - src/ops/health.py
  - tests/fixtures/phase9/attach/expected.json
  - tests/fixtures/phase9/attach/input.json
  - tests/fixtures/phase9/enablement/disabled/expected.json
  - tests/fixtures/phase9/enablement/disabled/input.json
  - tests/fixtures/phase9/enablement/emergency/expected.json
  - tests/fixtures/phase9/enablement/emergency/input.json
  - tests/fixtures/phase9/enablement/enabled/expected.json
  - tests/fixtures/phase9/enablement/enabled/input.json
  - tests/fixtures/phase9/gates/daily_stop_block/expected.json
  - tests/fixtures/phase9/gates/daily_stop_block/input.json
  - tests/fixtures/phase9/gates/headroom_reject/expected.json
  - tests/fixtures/phase9/gates/headroom_reject/input.json
  - tests/fixtures/phase9/gates/stale_constraints/expected.json
  - tests/fixtures/phase9/gates/stale_constraints/input.json
  - tests/fixtures/phase9/mode_branches/hedge/expected.json
  - tests/fixtures/phase9/mode_branches/hedge/input.json
  - tests/fixtures/phase9/mode_branches/one_way/expected.json
  - tests/fixtures/phase9/mode_branches/one_way/input.json
  - tests/fixtures/phase9/partial_fills/expected.json
  - tests/fixtures/phase9/partial_fills/input.json
  - tests/fixtures/phase9/placement_sequences/expected.json
  - tests/fixtures/phase9/placement_sequences/input.json
  - tests/test_execution_attach.py
  - tests/test_execution_enablement.py
  - tests/test_execution_gates.py
  - tests/test_execution_health.py
  - tests/test_execution_manager.py
  - tests/test_execution_modes.py
  - tests/test_execution_partials.py
findings:
  critical: 10
  warning: 12
  info: 7
  total: 29
status: issues_found
---

# Phase 9: Code Review Report

**Reviewed:** 2026-09-29T02:52:45Z
**Depth:** deep
**Files Reviewed:** 37
**Status:** issues_found

## Summary

I reviewed the Phase 9 live-execution surface at deep depth. That covers the execution manager, placement math, fill monitor, placement gates, enablement controller, health probes, the new placement methods in the Binance adapter, and all Phase 9 tests and fixtures. I traced every manager call through the real `BinanceUsdmAdapter`, `check_binding_full`, `evaluate_risk` / `check_portfolio`, and `SafeModeController`. I also checked the SDK's `new_algo_order` signature and the adapter's method surface directly, using `inspect.signature(...).bind(...)` against the installed package.

The 43 Phase 9 tests pass, but they are green only because every test injects a `**kwargs` fake adapter. Against the real adapter, the protective-attach path and the expiry/emergency paths fail on their first exchange call:

- `attach_protectives_to_fill` raises `TypeError: got an unexpected keyword argument 'reduce_only'` (verified).
- `expire_pending_entry` / `emergency_manual_close` raise `AttributeError` because the adapter has no `cancel_order` method (verified).

Neither failure is caught, so no `ENTRY_WITHOUT_PROTECTIVE` / SAFE_MODE signal is raised. There are other paths where a filled position ends up with no stop at all:

- TP1 sizing rejections abort before the SL is placed.
- Reusing the same deterministic IDs makes the attach collide with the SL that `execute_approved_plan` already placed.
- Adapter exceptions propagate without any SAFE_MODE composition.

On the entry side, the adapter retries order placement blindly with the same client ID on any non-programming error. It does this even though Binance client IDs are unique only among OPEN orders, which violates EXECUTION_SPEC §10. The manager's safety gates (enablement, placement gates) are optional and default off, and there is no SAFE_MODE guard at all. The approval binding never checks that the approval is actually APPROVE/APPROVED, or that the plan being executed is the plan that was approved.

Nothing in `src/` calls these functions yet, and 09-04 is recorded as blocked at task 3. So none of this is live today. But every BLOCKER below would be unsafe the moment the wiring is completed as written.

`mypy --strict` fails with 4 errors in the adapter, and `ruff check` fails on `tests/test_execution_gates.py`.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Protective attach crashes against the real adapter (`reduce_only` kwarg), and TP1 would never be sent reduce-only

**File:** `src/execution/manager.py:539-546`, `src/execution/placement.py:291-333`, `src/adapters/binance_usdm.py:1071-1084, 1141-1157`
**Issue:**
- Every leg dict built by `size_protectives_to_filled_qty` contains a `"reduce_only"` key. For the SL, the value is `None`.
- `attach_protectives_to_fill` splats the dict into `adapter.place_algo_protective(**leg)`.
- `BinanceUsdmAdapter.place_algo_protective` is keyword-only and has no `reduce_only` parameter. Verified: `inspect.signature(BinanceUsdmAdapter.place_algo_protective).bind(...)` raises `TypeError: got an unexpected keyword argument 'reduce_only'`.

As a result, the very first leg (SL) of every attach raises. No protective is placed, and because the exception is not caught (see CR-02), no SAFE_MODE is entered. The entry fill is left naked.

A second problem appears once the kwarg is accepted: the adapter still never forwards `reduce_only` to the SDK, even though the SDK does accept it (`new_algo_order(..., reduce_only: NewAlgoOrderReduceOnlyEnum)`). In one-way mode, TP1 would then be a plain SELL/BUY `TAKE_PROFIT_MARKET` with an explicit quantity. If SL or TP2 has already closed the position, a later TP1 trigger opens a new reverse position.

The tests hide both problems because `FakeExecutionAdapter.place_algo_protective(**kwargs)` accepts anything.
**Fix:**
```python
async def place_algo_protective(self, *, symbol, side, algo_type, type, position_side,
                                trigger_price, close_position, quantity, working_type,
                                client_algo_id, reduce_only: bool | None = None):
    if close_position and (quantity is not None or reduce_only):
        raise ValueError("closePosition=true is exclusive with quantity/reduceOnly")
    ...
    reduce_only=(NewAlgoOrderReduceOnlyEnum.TRUE if reduce_only else None),
```
Also add a contract test that binds every fake-adapter call's kwargs against `inspect.signature(BinanceUsdmAdapter.<method>)`.

### CR-02: Adapter exceptions during attach leave the position unprotected with no SAFE_MODE; the default `safe_mode_controller=None` silently drops the signal

**File:** `src/execution/manager.py:464, 539-562, 396-399`
**Issue:** `attach_protectives_to_fill` only enters SAFE_MODE when a response is returned and judged unconfirmed. Many things raise instead of returning:
- The adapter re-raises every SDK error after three retries: timeouts, `-2021 would immediately trigger`, duplicate `clientAlgoId`, rate limits.
- The adapter raises `ValueError` itself on identity-less responses.

Any such exception, on any leg, propagates straight out. `require_protective_confirmation` is never called, SAFE_MODE is not entered, and the caller gets no `AttachOutcome`. If SL was confirmed and TP1 raises, TP2 is never attempted and nothing is signalled.

`safe_mode_controller` also defaults to `None`. In that case even the "unconfirmed" branch only returns a verdict, which is fail-open by default on the most safety-critical path in the system.
**Fix:** Wrap each leg placement in `try/except Exception` and treat the exception as unconfirmed. On any unconfirmed leg, call `require_protective_confirmation(...)` and return an `ENTRY_WITHOUT_PROTECTIVE` outcome. Make `safe_mode_controller` a required argument (no default), or raise if it is `None` outside tests.

### CR-03: A TP1 sizing rejection aborts before the SL is placed, leaving a filled position with no stop at all

**File:** `src/execution/manager.py:516-531`, `src/execution/placement.py:274-288`
**Issue:** `size_protectives_to_filled_qty` sizes TP1 first. If `filled_qty * tp1_fraction` floors below `min_quantity`, or its notional is below `min_notional`, the whole sizing returns `is_no_trade=True` with all legs set to `None`. `attach_protectives_to_fill` then returns before placing anything, including the SL.

The SL does not depend on quantity at all: it is `closePosition=true`. This case is common for this project:
- A BTCUSDT first partial fill of 0.001 with fraction 0.5 floors TP1 to 0 → `MIN_QTY_REJECT`.
- With $500–1,000 of capital, TP1 notional is frequently below BTCUSDT's minimum notional.

The returned `reason_code` is `MIN_QTY_REJECT` / `NOTIONAL_REJECT`, not `ENTRY_WITHOUT_PROTECTIVE`. Callers and the health probe therefore cannot tell that a live position has no stop. In addition, whether MIN_NOTIONAL even applies to reduce-only/close legs should be re-verified against current Binance docs; if it does not, this gate is over-strict.
**Fix:** Always size and place the SL (close-all) first, independent of TP sizing. If TP1 is un-sizeable, either (a) degrade to SL + TP2 close-all with an explicit, journaled reason, or (b) keep the SL and return `ENTRY_WITHOUT_PROTECTIVE` for the missing TP legs. Never return a plain sizing reason code while a fill exists without a stop.

### CR-04: Deterministic algo IDs collide between `execute_approved_plan` and `attach_protectives_to_fill`, and across successive partial fills

**File:** `src/execution/manager.py:236-238, 302-315, 541`
**Issue:**
- `execute_approved_plan` places the SL at entry time with `derive_algo_client_id(plan_hash, STOP_LOSS)`.
- `attach_protectives_to_fill` later derives the same ID for the same plan and places the SL again. Binance requires `clientAlgoId` to be "unique among open orders" (SDK docstring), so the attach SL is rejected. The adapter retries it 3 times, then raises. Per CR-02, the exception escapes, so TP1/TP2 are never placed and nothing is signalled.
- Attach is also meant to run as fills arrive (D-02: partial fills are first-class). A second invocation, after more fill events, re-places SL/TP1/TP2 with the same three IDs. It fails the same way, and TP1 stays sized to the first partial forever.
- Test Beh. 1 ("attach once") only proves dedup within a single call. It does not cover a second call.

**Fix:** Pick one owner of the SL leg. Either have the entry-time SL be the attach SL and skip it in attach when already confirmed (query by `clientAlgoId` first), or never place the SL in `execute_approved_plan`. For incremental partial fills, cancel-then-replace TP1 with a versioned role code (e.g. a fill-sequence suffix), or query existing legs and only resize TP1.

### CR-05: `execute_approved_plan` ignores the SL placement result and returns OK with the entry live and unprotected

**File:** `src/execution/manager.py:257-317`
**Issue:**
- The return value of `place_algo_protective` is discarded. `ExecutionOutcome(is_no_trade=False, "OK")` is returned even if the response reports REJECTED/EXPIRED.
- If the SL call raises (rejection, network) after `place_entry` succeeded, the exception escapes with a resting LIMIT entry on the book and no stop. No cancel, no SAFE_MODE, no journal.
- If the retry `place_entry` returns `None` again (or the probe returned a non-found object), the code still places the SL and returns OK.
- Only the SL is placed. TP1/TP2 are never attached on this path, yet `_REQUIRED_PROTECTIVE_ROLES` demands all three. The two paths disagree on what "protected" means.

**Fix:** Check the SL result with the same confirmation logic as attach. On any SL failure after the entry was acknowledged, cancel the entry by its deterministic ID (journal-first), call `safe_mode_controller.enter_safe_mode("ENTRY_WITHOUT_PROTECTIVE")`, and return a NO_TRADE outcome. Do not return OK unless both the entry identity and the SL are confirmed.

### CR-06: `execute_approved_plan` calls `asyncio.run` in a sync function, which cannot work in the production asyncio stack

**File:** `src/execution/manager.py:258-315`
**Issue:** The comment says "we use asyncio.run only if no loop is running", but the code calls `asyncio.run(...)` unconditionally, four times. The approval callback path runs inside a running event loop (python-telegram-bot v22, FastAPI). There, `asyncio.run` raises `RuntimeError: asyncio.run() cannot be called from a running event loop` (verified locally) and leaks an un-awaited coroutine.

In a sync caller, every call also spins up and tears down a fresh event loop between the entry and the SL. This widens the unprotected window and breaks any loop-bound resources inside the adapter or SDK. The attach, expire, and emergency functions are already `async`, so the manager is internally inconsistent.
**Fix:** Make `execute_approved_plan` `async def` and `await` each adapter call. Update the tests to `await` it (pytest `asyncio_mode = "auto"` is already configured).

### CR-07: Live placement gates are fail-open by default: enablement, placement gates, SAFE_MODE, and reconciliation are all skippable or absent

**File:** `src/execution/manager.py:134-135, 197-225`; `src/risk/gating.py:94,120`
**Issue:**
- `enablement=None` and `gate_kwargs=None` skip the `LIVE_ORDERS_DISABLED` guard and all placement-time gates (headroom, stale constraints, uncertain state). Yet this function places real orders through the adapter. The "backtest/paper compatibility" justification does not apply to a function whose only job is live placement.
- There is no SAFE_MODE check anywhere in the pipeline. `SafeModeController.guard_new_entries` is never consulted. So when attach enters SAFE_MODE on `ENTRY_WITHOUT_PROTECTIVE`, the next approved plan still places a new entry, unless an operator separately disabled live orders. This violates the constraint "SAFE_MODE blocks entries".
- When gates are skipped, reconciliation is never checked at all: `evaluate_risk` hard-codes `positions_reconciled=True`.

**Fix:** Make `enablement`, `safe_mode_controller` and the gate inputs required keyword arguments with no `None` defaults. Add a SAFE_MODE gate right after the enablement gate (`safe_mode_controller.guard_new_entries(trade_plan=...)` → NO_TRADE). Keep backtest/paper on a different entry point instead of optional live gates.

### CR-08: The approval binding does not check the approval's action or status, or that the executed plan is the approved plan

**File:** `src/execution/manager.py:178-195, 228-245`; `src/approval/binding.py:149-216`
**Issue:**
- `check_binding_full` checks chat, expiry, `callback.plan_hash == approval.request_hash`, version, and token. It never checks `approval.action == APPROVE` or `approval.result/status == APPROVED`. A SKIP/REJECTED approval row with a valid token binds OK and places orders.
- The trade plan actually executed comes from `risk_kwargs["trade_plan"]`. Its `plan_hash` (used to derive the order IDs) and `expiry_utc` are never compared with `callback.plan_hash`, `approval.request_hash` or `approval.trade_plan_id`.
- `expiry_utc` is a separate caller-supplied argument rather than `trade_plan.expiry_utc`, so a stale plan can be executed under a fresh approval.
- Nothing marks the approval as consumed. An at-least-once Telegram replay re-runs the full pipeline and re-sends the entry (see CR-09 for why the exchange-side dedup is not sufficient).

**Fix:**
```python
if approval.action is not ApprovalAction.APPROVE or approval.result is not ApprovalResult.APPROVED:
    return ExecutionOutcome(is_no_trade=True, reason_code=RejectionReason.INVALIDATED.value)
tp = risk_kwargs["trade_plan"]
if tp.plan_hash != callback.plan_hash or tp.plan_hash != approval.request_hash \
        or tp.trade_plan_id != approval.trade_plan_id or expiry_utc != tp.expiry_utc:
    return ExecutionOutcome(is_no_trade=True, reason_code=RejectionReason.STALE_SETUP.value)
```
Also add an idempotency check against persisted execution state (plan already submitted → replay existing outcome).

### CR-09: The adapter blindly retries entry and algo placement with the same client ID on ambiguous failures, and the manager's no-blind-recovery probe is unreachable or broken

**File:** `src/adapters/binance_usdm.py:131-139, 1038-1069, 1131-1166, 1193-1210`; `src/execution/manager.py:274-299`
**Issue:**
- `place_entry` and `place_algo_protective` retry on `_is_transient_reconcile`, which returns True for every exception except `ValueError`/`KeyError`/`TypeError`. That includes read timeouts and Binance 5xx "execution status unknown" responses, i.e. exactly the ambiguous cases EXECUTION_SPEC §10 says must be probed, not retried.
- Binance deduplicates `newClientOrderId` / `clientAlgoId` only among open orders. If the first attempt was accepted and immediately filled (a marketable LIMIT entry), the retry is accepted as a new order and doubles the position. If the first attempt is still open, the retry is rejected as a duplicate, the adapter raises, and the manager never places the SL for an order that exists.
- Non-transient 4xx errors (-2019 margin, -4014 tick, -1111 precision) are also retried 3 times.
- The manager's probe logic does not work with the real adapter:
  - The real adapter never returns `None`; it raises. So `if entry_response is None` is dead code.
  - `query_order_by_client` returns an `OrderProbe` dataclass, but the manager calls `probe.get("found")`, which raises `AttributeError`.
  - A `None` probe (unknown) is treated as "confirmed absent" and triggers a retry, which fails open.
  - `query_order_by_client` only maps `-2011`/`UNKNOWN_ORDER` to not-found. Binance's query-order not-found code is `-2013` (`NO_SUCH_ORDER`, "Order does not exist"), so a genuinely absent order raises instead of returning `found=False` (re-verify against current error-code docs).

**Fix:** Do not retry placement inside the adapter at all, or only retry errors that are provably pre-send (connection refused before the request was written). Surface ambiguous outcomes as a typed `AmbiguousPlacement` result. In the manager, on ambiguity, probe by client ID using `probe.found` (attribute access), retry only on a definitive `found=False`, and on probe failure/`None` fail closed (NO_TRADE + SAFE_MODE). Map `-2013` to not-found in `query_order_by_client`.

### CR-10: The expiry and emergency-close paths call a non-existent adapter method, and the emergency sequence disables live orders and enters SAFE_MODE last

**File:** `src/execution/manager.py:81, 677, 732, 811-832`; `src/adapters/binance_usdm.py:860-924`
**Issue:**
- The `ExecutionAdapter` protocol declares `cancel_order(*, symbol, client_order_id)`, and `expire_pending_entry` calls `adapter.cancel_order(...)`. `BinanceUsdmAdapter` has no `cancel_order`. Its method is `cancel_normal_order(*, symbol, orig_client_order_id)` (verified: `hasattr(BinanceUsdmAdapter, "cancel_order") is False`). Every pending-entry expiry and every emergency manual close therefore raises `AttributeError` against the real adapter.
- `emergency_manual_close` runs cancel entry → cancel protectives → `enablement.disable` → `safe_mode_freeze` with no exception isolation. The step-1 `AttributeError`, or any cancel error that is not `-2011` (network, rate limit, a -2011-like message variant), aborts the sequence before live orders are disabled or SAFE_MODE is entered. That is exactly backwards for an emergency control.
- `cancel_untriggered_protectives` has the same flaw: one failing cancel leaves the remaining legs live.
- No test calls `expire_pending_entry`, `cancel_untriggered_protectives` or `emergency_manual_close`. `test_emergency_manual_close_plus_safe_mode_blocks_new_entries` calls `controller.disable()` and `enter_safe_mode()` directly.

**Fix:**
```python
async def emergency_manual_close(...):
    _require_live5_symbol(symbol)
    enablement.disable(operator_id=operator_id, now_utc=now_utc)          # block first
    safe_mode_freeze(safe_mode_controller=..., reason="MANUAL_CLOSE", now_utc=now_utc)
    errors = []
    for step in (expire_pending_entry(...), cancel_untriggered_protectives(...)):
        try: await step
        except Exception as exc: errors.append(exc); journal failure event
    if errors: raise ExceptionGroup("emergency cancel incomplete", errors)
```
Rename the protocol method to `cancel_normal_order(*, symbol, orig_client_order_id)` to match the adapter, and add real-adapter-signature contract tests for the emergency sequence.

## Warnings

### WR-01: Limit and trigger prices are never quantized to `price_tick_size`

**File:** `src/execution/placement.py:126-160`; `src/execution/manager.py:241-245`
**Issue:** `derive_limit_price` returns `(min+max)/2`, which is half a tick off whenever the zone width is an odd number of ticks (e.g. 100.01/100.02 → 100.015). `derive_sl_trigger_price` and the TP triggers pass plan prices through unchanged. Nothing in `src/execution` or `src/risk` quantizes a price to `price_tick_size` (grep confirms `price_tick_size` is only positivity-checked in `gates.py:153`). Binance rejects such orders (-4014 / -1111), the adapter retries 3 times, then raises.
**Fix:** Add a `quantize_price(price, tick, direction)` helper. Floor BUY limits and ceil SELL limits (or round toward the conservative side of the zone), and round triggers to tick in the protective direction. Apply the same helper in backtest and paper to keep parity.

### WR-02: Position mode is hard-coded to `BOTH` and never detected; the Protocol and adapter types disagree

**File:** `src/execution/manager.py:79, 266, 293, 308`; `src/adapters/binance_usdm.py:1212-1230`
**Issue:**
- `execute_approved_plan` sends `position_side="BOTH"` for entry and SL and never calls `get_position_mode()`, contrary to D-02 ("re-checked at placement time") and the AGENTS constraint. Hedge-mode accounts are rejected (-4061).
- The Protocol declares `get_position_mode() -> str`, but the adapter returns `PositionModeResult(dual_side_position: bool)`.
- `attach_protectives_to_fill` expects `"ONE_WAY"`/`"HEDGE"` strings, but no mapping from `PositionModeResult` exists.

**Fix:** Call `await adapter.get_position_mode()` at placement time. Map `dual_side_position` to `"HEDGE"`/`"ONE_WAY"` in one helper, and derive `position_side` from it for entry and all legs. Fix the Protocol return type.

### WR-03: `_is_leg_confirmed` is fail-open for any non-dict response, which is what the real adapter returns

**File:** `src/execution/manager.py:405-419`
**Issue:** The real adapter returns an `AlgoPlacementResult` dataclass, not a dict. For any non-dict response the function returns `True`, so `algo_status="REJECTED"` or an empty `""` status (the adapter maps a missing status to `""`) counts as confirmed. The status allow-list is also inverted: anything not in the deny-list, including `""` for dicts, is "confirmed". An ack is also not the "exists and active" verification EXECUTION_SPEC §6 requires.
**Fix:** Read `algo_status` via attribute or key, and confirm only on an explicit allow-list (`{"NEW"}`, plus any documented active states). Treat everything else as unconfirmed. Optionally re-query with `query_algo_order_by_client` before declaring the leg protected.

### WR-04: `fold_fills` sums unrelated fills, silently drops malformed ones, and gets the SHORT sign wrong

**File:** `src/execution/fill_monitor.py:190-229`; `src/execution/manager.py:506-514`
**Issue:**
- Fills are not filtered by the entry's order ID / client ID, symbol, or side. Fills from a TP1 exit, a different symbol, or the opposite side all add to `filled_quantity`, which then oversizes TP1.
- Events with missing IDs, or a `fill_quantity` that is not a `Decimal` (e.g. a raw WS string `"0.100"`), are silently skipped or not summed. This undercounts the fill and violates the D-09 "flag, never fabricate" discipline.
- `position_amt + filled_quantity` is wrong for SHORT positions (Binance amounts are negative).
- Attach ignores `folded.divergences`, so its `has_protective` argument has no effect.

**Fix:** Pass the entry `client_order_id`/`symbol`/expected side into the fold and reject (raise) on mismatch or on a non-Decimal quantity. Apply a signed quantity based on side. Drop `has_protective` from attach or act on the divergences.

### WR-05: Placement gates judge a different sizing, snapshot and clock than the order actually placed

**File:** `src/execution/manager.py:208-225, 248-250`
**Issue:** `decide_placement(**gate_kwargs)` runs before `evaluate_risk`. Its `sized`, `constraint_snapshot`, `candidate_symbol`/side and `now_utc` are all caller-supplied and independent of `risk_kwargs`. The portfolio caps are therefore checked against a pre-computed `SizedResult`, while the order uses `verdict.sized.quantity` from a separate risk run. The risk run also uses `risk_kwargs["now_utc"]`, which may differ from the binding's `now_utc`. A stale or foreign snapshot can pass one gate while the other uses a different one.
**Fix:** Run `evaluate_risk` first, then build the gate call from its `verdict.sized`, the same `constraint_snapshot`, the same symbol/side, and the manager's single `now_utc`. Reject if `risk_kwargs["now_utc"] != now_utc`.

### WR-06: The headroom limit is hard-coded, counts are unvalidated, and early rejects misreport `daily_state`

**File:** `src/execution/gates.py:34, 152-197`
**Issue:**
- `HEADROOM_LIMIT = 200` is a literal, while AGENTS requires dynamic detection (exchangeInfo `MAX_NUM_ALGO_ORDERS` per symbol).
- Negative `open_algo_count` / `planned_leg_count` pass silently.
- Gates 1–4 always return `DailyState.NORMAL`, even when `daily_loss_quote` is already at the stop threshold. That masks DAILY_STOP from downstream SAFE_MODE consumers, which `check_portfolio` explicitly avoids (portfolio.py:221-232).

**Fix:** Source the limit from the constraint snapshot (add a field populated from exchangeInfo), validate that counts are ≥ 0, and derive `daily_state` before the early returns, as `check_portfolio` does.

### WR-07: Entry expiry orphans the entry-time close-all SL, and the emergency close opens an unprotected window

**File:** `src/execution/manager.py:627-688, 761-832`
**Issue:** `execute_approved_plan` places a `closePosition=true` SL at entry time. `expire_pending_entry` cancels only the entry, so the close-all SL stays live. In one-way mode, it will later close whatever position exists on that symbol, including a position from a different plan. Separately, `emergency_manual_close` cancels the SL/TP legs before the operator has closed the position ("operator closes the position through the exchange UI"), which leaves a live position with no stop for an unbounded time.
**Fix:** On expiry with zero fills, also cancel the plan's protective legs. In the emergency path, close the position (reduce-only market by an explicit operator action) before cancelling its SL, or keep the SL until the position is confirmed flat.

### WR-08: The health aggregate passes on incomplete probe sets and never gates enablement

**File:** `src/ops/health.py:573-594`; `src/execution/enablement.py:146-168`
**Issue:**
- `run_health_checks` passes any non-empty list with no FAIL entries. A single `ws_connection_state` PASS yields `OK` even if `unprotected_positions`/`orphaned_orders` were never evaluated.
- Duplicate or missing check names are not detected, and `DEGRADED` counts as PASS.
- `LiveEnablementController.enable()` does not consult any health verdict, so "RED health blocks enablement" is not enforced anywhere.

**Fix:** Require that `{r.check_name for r in results} == set(ALL_CHECK_NAMES)` with no duplicates. Otherwise return `HEALTH_CHECK_FAILED`. Require a passing `HealthVerdict` argument in `enable()`.

### WR-09: `journal_event_id` values collide on the same injected timestamp (the DB primary key)

**File:** `src/ops/health.py:211`; `src/execution/enablement.py:205-207`; `src/execution/manager.py:615-617`; PK at `src/db/models.py:386`
**Issue:** IDs take the form `health_check_{name}_{ms}` / `enablement_{type}_{ms}`. Two runs of the same probe, or two `disable()` calls, at the same `now_utc` produce identical primary keys. The persisted journal then raises an integrity error, or silently drops the event under upsert semantics. `test_any_fail_probe_blocks_enablement_with_health_check_failed` already emits two `health_check_ws_connection_state_<same ms>` events. The model docstring says the PK is a content hash; these IDs are not.
**Fix:** Derive the ID from a hash of `(event_type, entity_id, occurred_at, payload_json)`, or add a monotonically increasing sequence / UUID component.

### WR-10: The enablement journal payload records the pre-transition state

**File:** `src/execution/enablement.py:213-219`
**Issue:** `_journal_enablement_event` serializes `self._disabled` before the flip, so a `LIVE_ORDERS_ENABLED` event carries `"live_orders_disabled": true`, and a `LIVE_ORDERS_DISABLED` event carries `false`. That audit record contradicts itself.
**Fix:** Pass the target state explicitly, e.g. `"live_orders_disabled_after": False` for enable. Optionally include both the before and after states.

### WR-11: Quality gates are red: `mypy --strict` and `ruff check` fail

**File:** `src/adapters/binance_usdm.py:1056, 1057, 1149, 1153`; `tests/test_execution_gates.py:114-115`
**Issue:** mypy strict reports 4 `arg-type` errors: `Decimal` is passed where the SDK stub expects `float | None`. Ruff reports 2 E501 errors in the gates test. CI enforcement per the stack guidance would fail.
**Fix:** Convert explicitly at the SDK edge with a typed helper (`_to_wire(d: Decimal) -> str` plus a single targeted `# type: ignore[arg-type]` with a justification comment), and wrap the long test lines.

### WR-12: The tests validate fakes, not the adapter contract, and leave the risky paths untested

**File:** `tests/test_execution_attach.py:147-163`; `tests/test_execution_manager.py:77-126, 297-308, 465-468`; `tests/test_execution_enablement.py:123-174`; `tests/test_execution_partials.py:291-293`; purity tests using relative `Path("src/...")`
**Issue:**
- All fakes accept `**kwargs` and return dicts. That hides CR-01 (`reduce_only`), CR-09 (`OrderProbe.get`), CR-10 (`cancel_order`) and WR-03 (the dataclass response).
- `execute_approved_plan` is never tested with `enablement=` or `gate_kwargs=`.
- `expire_pending_entry`, `cancel_untriggered_protectives` and `emergency_manual_close` have zero tests.
- The ambiguous-entry test only covers `found=True`.
- The purity tests read `Path("src/...")` relative to the working directory, and `test_fill_monitor_module_purity` skips silently if the file is not found. Running from another directory gives a false green.

**Fix:** Add signature-binding contract tests between each fake and `BinanceUsdmAdapter`. Add tests for the gated manager path, the emergency sequence, and a failing SL placement. Resolve module paths via `Path(__file__).parents[1] / "src" / ...` and fail instead of skipping.

## Info

### IN-01: A file-wide E501 ignore covers the most safety-critical adapter

**File:** `pyproject.toml:75`
**Issue:** `"src/adapters/binance_usdm.py" = ["E501"]` disables line-length linting for the whole order-placement adapter just to accommodate a docstring table. The `# noqa: E501` markers inside the docstring (lines 50-53) have no effect because they sit inside a string.
**Fix:** Reflow the docstring table, or move it to a doc file, and remove the per-file ignore.

### IN-02: Decimals reach the SDK raw, not as strings as documented

**File:** `src/adapters/binance_usdm.py:1056-1057, 1149, 1153`
**Issue:** The docstring promises "string-mediated Decimal-to-edge conversion", but the raw `Decimal` is passed to the SDK, which urlencodes it via `str()`. `str(Decimal)` can produce exponent notation (`1E-8`, `1E+1`), which Binance rejects.
**Fix:** Pass `format(value, "f")` at the edge.

### IN-03: Dead or redundant code

**File:** `src/adapters/binance_usdm.py:1153, 1457-1466`; `src/execution/fill_monitor.py:30-32`
**Issue:**
- `quantity=quantity if quantity is not None else None` is a no-op.
- `_epoch_utc()` is unused.
- `_DIVERGENCE_KINDS` is unused.
- The `if _is_already_canceled_response(result): return result` branches are identical to the fall-through `return result`.

**Fix:** Remove them.

### IN-04: `assert` is used for runtime invariants on the placement path

**File:** `src/execution/manager.py:248-249, 540`
**Issue:** These checks disappear under `python -O`.
**Fix:** Replace them with explicit `if ...: raise RuntimeError(...)`.

### IN-05: Fixture and test precision gaps

**File:** `tests/fixtures/phase9/gates/headroom_reject/*.json`; `tests/fixtures/phase9/gates/*/expected.json`; `tests/test_execution_gates.py:369-399`
**Issue:**
- The headroom fixture uses 198+3=201 (declared `headroom_margin: 0`), so the `== 200` boundary the docstring emphasizes is never exercised.
- The expected fields `daily_state`, `gate` and `adapter_place_calls` are never asserted.
- The uncertain-state test sets both `daily_loss_quote=None` and `positions_reconciled=False` at once, so it cannot tell which sub-gate fired. It also reuses the `enablement/disabled` fixture.

**Fix:** Add a 197+3 case, assert `daily_state`, and split the uncertain-state test into two cases.

### IN-06: `EnablementVerdict` validation is lopsided, and the guard receives a mislabelled argument

**File:** `src/execution/enablement.py:63-76`; `src/execution/manager.py:199-201`
**Issue:** `EnablementVerdict(is_no_trade=False, reason_code="DISABLED")` is accepted by the validator. The manager passes `approval.trade_plan_id` as `plan_hash`.
**Fix:** Require `reason_code is None` when `is_no_trade=False`, and pass the real plan hash.

### IN-07: Health probe edge cases

**File:** `src/ops/health.py:381-391, 493-507`
**Issue:** `check_rest_error_rate` accepts `error_count > total_count`, which gives a rate above 1. `check_telegram_delivery` treats any non-`None` response (including `False`) as delivered.
**Fix:** Validate `error_count <= total_count`, and require a truthy or message-shaped response.

---

_Reviewed: 2026-09-29T02:52:45Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
