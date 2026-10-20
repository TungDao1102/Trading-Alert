---
phase: 19-execution-plan-binding-price-check
reviewed: 2026-10-20T09:24:09Z
depth: deep
files_reviewed: 23
files_reviewed_list:
  - config/execution/execution-limits-v1.toml
  - scripts/demo_rehearsal.py
  - src/adapters/binance_public.py
  - src/adapters/binance_ratelimit_gate.py
  - src/adapters/binance_usdm.py
  - src/analytics/live_outcomes.py
  - src/core/planner.py
  - src/db/alembic/versions/0005_live_sized_risk.py
  - src/db/models.py
  - src/domain/exchange_errors.py
  - src/domain/lot_filters.py
  - src/execution/binding.py
  - src/execution/emergency_close.py
  - src/execution/execution_limits.py
  - src/execution/intent_store.py
  - src/execution/live_context.py
  - src/execution/lot_split.py
  - src/execution/manager.py
  - src/execution/order_ids.py
  - src/execution/pre_placement.py
  - src/execution/protection.py
  - src/execution/tp_sizing.py
  - src/persistence/execution_state.py
findings:
  critical: 3
  warning: 7
  info: 6
  total: 16
status: issues_found
---

# Phase 19: Code Review Report

**Reviewed:** 2026-10-20T09:24:09Z
**Depth:** deep
**Files Reviewed:** 23
**Status:** issues_found

## Summary

Deep review of the Phase 19 diff (`96a80e5..HEAD`). I traced these chains: manager → binding → pre_placement → protection registry hand-off; coordinator → attach_protectives_to_fill → tp_sizing/lot_split; coordinator → MarketEmergencyCloser → adapter; and intent write-ahead → PgExecutionStateStore → migration 0005.

What holds up:
- The plan-hash re-derivation is correct.
- The Q5 single-POST entry is correct.
- The PreSendRefusal taxonomy wiring (RestGateRefusal, EntriesBlocked and SignedCallPolicyMissing all subclass PreSendRefusal) is correct.
- The lot-grid arithmetic (CRT intersection, representability) is correct.
- The STOP_LOSS and TP intent write-ahead is correct.
- I found no float and no wall-clock read in the pure modules.

There are three blockers:
1. The mark-price age check compares a reading taken AFTER `now_utc` against `now_utc`. Fresh readings come out with a negative age and are refused.
2. The Demo rehearsal's `far` and `fill` scenarios can never pass the new mark-in-zone gate. The flow test hides this by forcing the fake mark onto the entry price.
3. The protection coordinator and the emergency closer declare FLAT, and cancel every protective leg (including an ACTIVE stop), on a single zero position read. This bypasses the project's two-consecutive-zero-reads rule (T-8-30).

The warnings cover gaps in binding, position checks and supervision:
- The approved quantity is not hash-bound.
- The same-symbol position check uses caller data, not a live read.
- The emergency close can re-send after a `found=False` probe and counts an ACK as closed.
- A stop that is lost while the entry is open is not a blocking state.
- An UNKNOWN entry is never watched.
- D-22 is never wired into analytics.

## Critical Issues

### CR-01: The mark-price age is measured against a `now_utc` captured before the read, so fresh readings are refused

**File:** `src/execution/manager.py:849`, `src/execution/manager.py:867-879`, `src/execution/pre_placement.py:273-277`
**Issue:** `execute_approved_plan` gets one `now_utc` at entry. Only later, in gate 5e (after binding, risk and the placement gates), does it call `adapter.get_mark_price`. `MarkPriceReading.exchange_time_utc` is Binance's `time` for that later response. `check_mark_price` then computes `age = now_utc - mark_time_utc` and returns `MARK_PRICE_UNAVAILABLE` when `age < 0`.

Any reading stamped after `now_utc` therefore fails the check. That is the normal case when the clocks are in sync, because the read happens after `now_utc` was taken. The only real caller shows this clearly:
- `scripts/demo_rehearsal.py:2611` takes `now = await guarded.server_time()`.
- It then makes several more REST round trips (exchangeInfo, commission, klines in `build_live_context`, `snapshot_open_algo_orders`) before the manager reads the mark.

The tests hide the problem. `tests/test_execution_manager.py:92-93` stamps the fake mark at `now_utc - mark_age_ms`, and `tests/test_demo_rehearsal_flow.py:247` stamps it `SERVER_NOW`. The staleness bound is also measured from the wrong instant: a reading can look fresh relative to an old `now_utc` while being stale relative to the moment of placement.

The result fails closed (no wrong order), but criterion 2's price check refuses correct placements on Demo and live.
**Fix:** Do not compare a post-read exchange time with a pre-read injected time. Keep the manager pure by injecting a clock callable through `LivePlacementContext`, or have the adapter return the local receipt time stamped by an injected clock. Then:
```python
# live_context: clock: Callable[[], datetime]   (injected, never read in a pure module itself)
received_at = live_context.clock()           # right after the read
age = received_at - mark_time_utc
if age < -live_context.gtd_clock_margin:      # tolerate the ratified drift, not any skew
    return MARK_PRICE_UNAVAILABLE
if age // _MILLISECOND > max_mark_price_age_ms:
    return MARK_PRICE_UNAVAILABLE
```
Add a regression test where the fake mark is stamped after `now_utc`.

### CR-02: The Demo rehearsal's `far` and `fill` scenarios can never pass gate 5e; the test forces the mark onto the entry

**File:** `scripts/demo_rehearsal.py:1600-1634`, `scripts/demo_rehearsal.py:1690-1691`, `src/execution/pre_placement.py:284-285`, `tests/test_demo_rehearsal_flow.py:158-160,693-694`
**Issue:** `derive_plan` builds a one-price zone (`entry_min_price = entry_max_price = entry`). It also requires the entry to sit strictly away from the mark:
- `far`: `entry < mark_price`, `FAR_BAND_FRACTION = 0.5` of the PERCENT_PRICE band.
- `fill`: `entry > mark_price`.

`check_mark_price` refuses any mark outside `[entry_min, entry_max]` with `MARK_PRICE_OUTSIDE_ZONE`. On the real exchange both order scenarios therefore always end with `RehearsalAbort("no order was attempted: MARK_PRICE_OUTSIDE_ZONE")`, even after the owner sets the four limits. The flow test passes only because it sets `exchange.gate_mark_price = _derive(scenario).entry_price`, a value Demo never returns.

This is the end-to-end tool the owner register names for the O-05 probes (`--scenario fill`, P1-P10). Those probes cannot run, so D055 cannot be closed with this script.
**Fix:** Make the rehearsal plan compatible with the gate:
- Give it a real zone that contains the live mark at placement, for example `entry_min = entry` and `entry_max = mark + k*tick` for `far`.
- Or re-derive the plan from the mark right before placement.

Then remove the `gate_mark_price` override from `run_flow`, so the test proves the derived plan passes `check_mark_price` against the fake's own mark.

### CR-03: A single zero position read declares FLAT and cancels every protective leg, including an ACTIVE stop (T-8-30 bypassed)

**File:** `src/execution/protection.py:1184-1190`, `src/execution/protection.py:1283-1287`, `src/execution/protection.py:1034-1039`, `src/execution/protection.py:705-720`, `src/execution/emergency_close.py:228-231`, `src/execution/emergency_close.py:301-305`
**Issue:** The reconciler's orphan sweeper (`src/reconcile/sweeper.py:187-198`, T-8-30) cancels protectives only after two consecutive zero position reads; one read is classed as `transient_position_gap`. The new coordinator moves to FLAT and calls `_sweep` (which runs `cancel_untriggered_protectives` for SL, TP1 and TP2) after ONE read in four places:
- `_attach_take_profits`: `amount == _ZERO`. Here the stop is in the PROTECTED state, i.e. confirmed ACTIVE.
- `_watch_exit`, from COMPLETE or TP_UNAVAILABLE.
- `_on_stop_lost`.
- `_on_no_position_on_stop`.

`snapshot_positions` drops zero rows, so one empty response is enough. The closer also returns True on one zero read, which `_close_flow` turns into FLAT plus a sweep.

One transient empty read (an exchange glitch, or eventual consistency right after a fill) cancels the ACTIVE closePosition stop and the TP legs of an open position. The plan then sits in FLAT, which does not block entries and is never supervised again. That is exactly the naked-position outcome Phase 19 exists to prevent.
**Fix:** Apply the same rule as the sweeper before any FLAT transition that cancels protectives:
```python
first = await self._position_amount(tracked)
if first != _ZERO:
    return
second = await self._position_amount(tracked)   # a fresh REST read
if second != _ZERO:
    self._journal_note(tracked, EVENT_REST_FAILED, {"call": "snapshot_positions",
                       "error_type": "TransientPositionGap"}, self._now())
    return
self._transition(tracked, ProtectionState.FLAT, ...)
```
Do the same in `MarketEmergencyCloser.close_position` before returning True, and in `_on_stop_lost` and `_on_no_position_on_stop`.

## Warnings

### WR-01: The approved quantity (D-02 bound) is not covered by the plan hash

**File:** `src/execution/binding.py:179`, `src/core/planner.py:59-92`, `src/execution/manager.py:802-809`
**Issue:** `bound.approved_quantity = trade_plan.quantity_after_rounding`, and that comes from the caller-supplied `risk_kwargs["trade_plan"]`. `plan_hash_from_fields` hashes only signal_id, zone, SL, TP json, invalidation json and expiry. None of `quantity_after_rounding`, `risk_rate` or `risk_budget` is hash-bound, and the approval binds only `request_hash == plan_hash`.

So a TradePlan object with an inflated `quantity_after_rounding` passes every hash and approval check, and gate 5b then allows a larger order than the one shown to the human. D-01 says "re-derived and compared, not trusted", but the quantity is trusted.
**Fix:** The hashed field set is frozen (D051 c), so bind the quantity elsewhere. Persist the quantity shown at approval on the Approval row (or a hash of it), and have `bind_plan` compare `trade_plan.quantity_after_rounding` against that. Otherwise document that the bound is only as strong as the stored TradePlan row and load the plan by id inside the live runner, never from a caller object.

### WR-02: The same-symbol POSITION refusal (D-05) uses the caller's list, not a live read

**File:** `src/execution/manager.py:873`, `scripts/demo_rehearsal.py:1536`
**Issue:** Open orders and algo orders are read live in gate 5e. `position_symbols`, however, is built from `risk_kwargs["open_positions"]`, which the caller supplies. The only caller passes `"open_positions": []` unconditionally. An existing position on the symbol (for example a manual one, or one left by an UNKNOWN entry) is never seen by `SYMBOL_HAS_POSITION`. The adapter already offers `snapshot_positions`.
**Fix:** Read the positions in gate 5e like the order snapshots, failing closed when the read fails:
```python
positions = await _read_or_none(lambda: adapter.snapshot_positions(symbol=bound.symbol))
position_symbols = None if positions is None else frozenset(p.symbol for p in positions)
# PrePlacementInputs: position_symbols: frozenset[str] | None -> None refuses SYMBOL_STATE_UNAVAILABLE
```

### WR-03: The emergency close can send more than the position: an ACK counts as CLOSED, and `found=False` right after an ambiguous error triggers a new send

**File:** `src/execution/emergency_close.py:361-365`, `src/execution/emergency_close.py:393-395`, `src/execution/emergency_close.py:262-313`, `src/execution/emergency_close.py:163-182`
**Issue:**
1. `_send_part` returns `_Kind.CLOSED` as soon as `place_market_close` returns. A MARKET ack is normally NEW with zero executed, as the `MarketCloseResult` docstring itself says. The immediate position re-read can still show the full position. With `parts_planned == 1` the loop ends with `PARTS_EXHAUSTED`, which means SAFE_MODE plus a critical alert, and the coordinator's next step sends attempt N+1 for the full size.
2. After an ambiguous error, a probe answering `found=False` becomes `NO_EFFECT`, and the loop sends a new attempt. Q5 rejected exactly this inference for entries ("found=False right after an ambiguous error is UNKNOWN, not absence"). `discover_next_attempt_no` makes the same inference across restarts.

D-15 says "never a duplicate close". As written, nothing but the unverified assumption A4 (reduce-only on a flat or smaller position is rejected) prevents an over-close.
**Fix:** Treat an ACK as `PENDING` and confirm it by `query_order_by_client` until FILLED or terminal before re-reading the position. Map `found=False` right after an ambiguous send to `_Kind.UNKNOWN` (PENDING_UNKNOWN), the same as the Q5 entry path. Make `discover_next_attempt_no` stop with an unknown history when the last found attempt is not terminal.

### WR-04: A once-confirmed stop that is lost while the entry is open leaves the plan non-blocking and unescalated

**File:** `src/execution/protection.py:986-990`, `src/execution/protection.py:1027-1039`, `src/execution/protection.py:213-219`
**Issue:** In PROTECTED_ENTRY_OPEN, a stop reading of ABSENT or NOT_ACTIVE calls `_on_stop_lost` and returns before the B1 deadline check.
- If the position read fails (`exposed is None`), or reads flat while the entry is still open, nothing happens: no SAFE_MODE, no alert, no deadline.
- The state stays PROTECTED_ENTRY_OPEN, which is not in `BLOCKING_STATES`, so `blocks_new_entries()` is False even though the coordinator knows the stop is gone.
- A further partial fill in that window is unprotected until a later step happens to read the position.
**Fix:** On `_on_stop_lost`, move the plan to UNPROTECTED (blocking) whenever exposure is not proven zero with the entry terminal. Keep evaluating `_entry_deadline_reached` and `_unprotected_deadline_reached` (reset `first_fill_at` semantics or use a separate "stop lost at" timestamp), so an unreadable position escalates to CLOSE_REQUIRED.

### WR-05: An entry left ENTRY_STATE_UNKNOWN is never handed to the coordinator, so a resting GTD entry can fill without a stop

**File:** `src/execution/manager.py:1045-1061`
**Issue:** Under Q5 the UNKNOWN path enters SAFE_MODE and returns without `register_resting_entry`. The GTD LIMIT may well exist (the reason it is UNKNOWN). If it fills, no component places the closePosition stop until a Phase 20 reconciler exists. SAFE_MODE blocks entries only; it does not protect a fill. The register records this consequence, but registering costs nothing: the coordinator's `_poll_entry` handles `found` not True by waiting, and the record was already built at gate 5g.
**Fix:** Register the `resting_entry` on the UNKNOWN path too (inside the same try/except used for the ACKED hand-off). The coordinator then protects a fill if the entry turns out to exist and stays inert if it never does. SAFE_MODE and the UNKNOWN intent stay as they are.

### WR-06: `MARK_PRICE_OUTSIDE_ZONE` refuses the normal resting-limit case (a LONG with the mark above the zone)

**File:** `src/execution/pre_placement.py:278-286`
**Issue:** The check refuses any mark outside `[entry_min, entry_max]`, in both directions. For a LONG pullback plan, a mark above the zone is the expected state when a GTD BUY LIMIT is placed to rest. That is exactly what the GTD backstop of D-05 exists for. Only a mark below the zone (a marketable limit) or below the stop is adverse.

As written, a live entry can only be placed while the mark is already inside the zone, which makes the resting GTD model almost unreachable. `tests/test_execution_manager.py:3011` pins this as intended, so this is a spec question for the owner rather than an accident. CR-02 is one concrete consequence.
**Fix:** Confirm the D-05 meaning with the owner. If "left the zone" means "moved past the zone through the entry side", refuse only the adverse direction:
```python
if side == _LONG and mark_price < entry_min_price: return MARK_PRICE_OUTSIDE_ZONE
if side == _SHORT and mark_price > entry_max_price: return MARK_PRICE_OUTSIDE_ZONE
```

### WR-07: D-22 sized risk is persisted but never reaches analytics

**File:** `src/analytics/live_outcomes.py:121-144`, `src/analytics/cli.py:580`, `src/persistence/execution_state.py:117-134`
**Issue:**
- `sized_risks_from_entry_intents` has no production caller.
- `src/analytics/cli.py:580` calls `normalize_live_outcomes(rows.signals, rows.plans, rows.orders, rows.fills)` without `sized_risks`.
- The store has no method that lists resolved ENTRY intents (`list_unresolved_intents` returns only INTENDED, SENT and UNKNOWN).

So every live candidate stays INCOMPLETE(NO_RISK_VALUE). The module docstring and owner gap A9 say "only NO_RISK_VALUE goes away", but in practice it does not.
**Fix:** Add a store read of the ENTRY intents per trade plan, and pass `sized_risks_from_entry_intents(...)` into `normalize_live_outcomes` in the CLI, with a PG test. Otherwise correct the docstring and the register to say the column is written but not yet consumed.

## Info

### IN-01: The CLOSE_FAILED retry loop raises a critical alert on every step

**File:** `src/execution/protection.py:1354-1373`, `src/execution/emergency_close.py:430-464`, `src/execution/emergency_close.py:466-487`
**Issue:** Every step in CLOSE_FAILED calls `close_position`. Each failure (`_fail`) or pre-send refusal (`_not_sent`) sends a critical alert. A ban window or a persistent rejection floods the alert channel at the step cadence.
**Fix:** Deduplicate by (plan_hash, code) in the closer or coordinator and re-alert only on a change or after an interval.

### IN-02: The TP1 fraction ranges disagree across three validators

**File:** `src/execution/live_context.py:83-84`, `src/execution/protection.py:297-298`, `src/execution/tp_sizing.py:144-145`
**Issue:** `LivePlacementContext` and `size_take_profits` accept `(0, 1]`, but `RestingEntry` requires `< 1`. A fraction of 1 passes the context, only to be refused at gate 5g as `PROTECTION_INPUTS_INVALID`.
**Fix:** Use one shared validator with `(0, 1)` in all three places.

### IN-03: Dead `_place_protective_leg` and a stale comment

**File:** `src/execution/manager.py:766-767`, `src/execution/manager.py:1404-1416`
**Issue:** `_place_protective_leg` has no caller in `src` (the register notes this). The comment at 766-767 still says the SL's `xa-` id "is derived inside `_place_protective_leg`", but no SL is placed by the manager any more.
**Fix:** Remove the function (and its pinning test) or move it into test support. Update the comment.

### IN-04: The plan-status check is a deny-list

**File:** `src/execution/pre_placement.py:66-68`, `src/execution/pre_placement.py:144-153`
**Issue:** A new `TradePlanStatus` member added later would pass the check by default, which fails open.
**Fix:** Use an allow-list `{READY, APPROVAL_PENDING, APPROVED}`, so an unknown status refuses.

### IN-05: The new market-close mapper puts the raw SDK response in an exception message

**File:** `src/adapters/binance_usdm.py:1659`
**Issue:** `ValueError(f"new_order response missing identity fields: {raw!r}")` copies the existing pattern. The project rule is that exception messages may reach logs, and the response repr may carry account data. The callers only log the type, but the message still travels with the exception.
**Fix:** Name only the missing field, not `raw`.

### IN-06: `fill_sink` silently drops a non-Decimal or non-positive quantity

**File:** `src/execution/protection.py:557-559`
**Issue:** A fill with a missing or zero quantity returns without incrementing `fill_sink_failures`, so a malformed stream fill leaves no trace. The REST poll still covers it.
**Fix:** Count it in `fill_sink_failures`, or journal it once, like unknown fills.

---

_Reviewed: 2026-10-20T09:24:09Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
