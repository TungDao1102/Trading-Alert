---
phase: 22-leverage-margin-liquidation-guard
reviewed: 2026-10-24T00:00:00Z
depth: deep
files_reviewed: 29
files_reviewed_list:
  - src/execution/margin_guard.py
  - src/execution/symbol_config_guard.py
  - src/execution/bracket_cache.py
  - src/execution/liquidation_watch.py
  - src/execution/account_equity.py
  - src/execution/live_context.py
  - src/execution/manager.py
  - src/execution/protection.py
  - src/execution/execution_limits.py
  - src/risk/liquidation.py
  - src/risk/margin_check.py
  - src/risk/live_equity.py
  - src/risk/reservations.py
  - src/persistence/risk_reservations.py
  - src/db/alembic/versions/0012_reservation_margin.py
  - src/db/models.py
  - src/adapters/binance_usdm.py
  - src/adapters/binance_probe.py
  - src/domain/exchange_errors.py
  - src/ops/operator_evidence.py
  - scripts/demo_probe.py
  - scripts/demo_rehearsal.py
  - config/execution/execution-limits-v1.toml
  - tests/test_margin_guard.py
  - tests/test_symbol_config_guard.py
  - tests/test_liquidation_watch.py
  - tests/test_protection_liquidation.py
  - tests/test_risk_reservations.py
  - tests/test_paper_shadow_isolation.py
findings:
  critical: 0
  warning: 9
  info: 8
  total: 17
status: issues_found
---

# Phase 22: Code Review Report

**Reviewed:** 2026-10-24
**Depth:** deep (cross-file: guard -> config guard -> bracket cache -> account source -> claims store -> manager gate 5f2 -> protection hook)
**Files Reviewed:** 29 (23 source/config files read in the scope given; 6 test files read in part, see "Test coverage" below)
**Status:** issues_found

## Summary

I read the Phase 22 modules end to end and traced every path the task listed. I did not find a path
where an entry PASSES the guard when it should be refused, and I did not find a config POST that is
sent twice or retried inside one guard run. The money maths hold up under independent verification:
I wrote a brute-force liquidation solver (exact `Fraction` arithmetic, first margin-balance crossing
from the entry, the full ten-tier Demo table, LONG and SHORT, leverage 1 to 5, fee 0 to 5 bps) and
compared 300 random positions across tier edges with `src.risk.liquidation.liquidation_price`: zero
mismatches above 1e-6 relative; every `None` was a legitimate refusal (leverage above the entry bracket's
`initialLeverage`, or a wallet that cannot cover the position). `RejectionReason` still has 21 members. No
numeric default of buffer, age or headroom exists in `src/` or `scripts/`; no `float(`, no wall clock in the
pure modules; `entry_fee_rate` comes from the request (`manager.py:1014`), never a constant.

The defects are not in the arithmetic. They are in the seams: when the guard mutates the account, how long
it holds the placement path open, what the post-fill hook does on its error paths and after a restart, what
alert it raises on a normal fill, and a claims circuit that is not closed end to end. No finding is a
provable fail-open today (hence zero Critical), but WR-02 widens an existing duplicate-entry race and WR-03
turns a restart into a forced close once Phase 24 composes the watch; both should be fixed before Phase 24
wires these classes.

## Warnings

### WR-01: The configuration POSTs are sent for plans the guard will refuse a few lines later

**File:** `src/execution/margin_guard.py:328-346` (POSTs), `:348-418` (the refusals that follow); pinned as intended by `tests/test_margin_guard.py:184-197`
**Issue:** `evaluate` runs the symbol-configuration guard (which sends up to two account-mutating POSTs) BEFORE the
liquidation check and BEFORE the margin check. A plan that is then refused for `LIQUIDATION_TOO_CLOSE`,
`NOTIONAL_ABOVE_MAX`, `LEVERAGE_ABOVE_BRACKET`, `INSUFFICIENT_MARGIN`, a stale second reading or an unusable bracket
set has already changed the symbol on the owner's account (CROSSED x20 -> ISOLATED x5). The test at line 184 asserts
exactly this ("The mutation happened before the refusal"). Every approve tap of a plan that cannot be placed repeats the
journal row and, while the exchange keeps refusing, the POSTs. The ordering is justified in the docstring only by "the
leverage every later number needs is the one the exchange confirmed"; but the verified leverage must equal the target
(`_matches` is exact equality), so both pure checks can be evaluated at the target leverage from the first account reading
and the brackets before any POST. Only `maxNotionalValue` (which depends on the leverage after the change) has to wait.
**Fix:** Pre-check first, mutate last.
```python
# 1a. account mode (unchanged)
# 1b. brackets + liquidation_verdict(leverage=self._target_leverage) + margin_verdict(leverage=target)
#     using `first` (reading already judged fresh). A refusal here sends NOTHING.
# 1c. only then cfg = await self._config_guard.ensure(...)
# 1d. re-run only the max_notional comparison and, if cfg.leverage != target, refuse.
```
Expose `target_leverage` on `ConfigGuardPort` (it is already a constructor argument of `SymbolConfigGuard`).

### WR-02: Gate 5f2 inserts about eight sequential REST calls between the price/same-symbol checks and the consume

**File:** `src/execution/manager.py:921-978` (reads and `evaluate_pre_placement`), `:1002-1026` (guard), `:1115` (consume), `:1209` (place)
**Issue:** The mark/last price age is measured once, at `mark_checked_at_utc` (`:942`), and the same-symbol / open-order /
unprotected checks use the reads of gate 5e. The guard then performs three account reads, a `symbolConfig` read, up to two
POSTs, a second `symbolConfig` read, a bracket read and a DB claims read (the tracer test counts eight REST calls, and its
own comment says 2 s per call exceeds the 9137 ms bound). Nothing is re-checked afterwards. Consequences:
(a) the mark price may be older than `max_mark_price_age_ms` by the time the order is sent, which the limit was meant to
bound; (b) `min_remaining_validity_seconds` and the exchange's 600 s `goodTillDate` floor are measured at `now_utc`
taken before the guard, so the guard's latency eats the margin and a late GTD rejection would happen AFTER the approval is
consumed; (c) the window in which two approvals for the same symbol can both pass the same-symbol check is now seconds
wide: I found no symbol-level arbiter between gate 5e and `consume_and_record_entry_intent` (the only unique key is
`uq_execution_intents_plan_role`), so two concurrent approvals for one symbol can both pass 5e, both pass the guard (the
second one sees an already-ISOLATED symbol and sends nothing), both consume and both place. Item (c) pre-dates Phase 22
but Phase 22 widens it from one REST call to eight.
**Fix:** After the guard returns a pass, re-read `live_context.clock()` and re-run the clock-dependent part of the
pre-placement evaluation (mark age, last-price age, remaining validity) with the fresh instant, or move the guard BEFORE
the gate 5e reads so that 5e is the last thing before the consume. Serialise per symbol (an in-process lock keyed by
`bound.symbol` around 5e..consume, plus a DB-level partial unique index on open entry intents per symbol) so two approvals
cannot interleave.

### WR-03: A restored plan has no verified leverage, so the watch closes a healthy position after every restart

**File:** `src/execution/protection.py:1705` (reads `entry.plan_constraint_snapshot.leverage`), `:772` (docstring: "A restored plan starts False, so the comparison runs once after a restart as well"); `src/execution/manager.py:1061-1066` (leverage exists only on the IN-MEMORY snapshot, amendment A8); `src/execution/liquidation_watch.py:260-269`
**Issue:** The verified leverage is filled only into the in-memory `RestingEntry` (A8); the persisted
`plan_constraint_snapshots` row is write-once (append-only trigger) and keeps `leverage = None`. `restore()` installs plans from
`RestoredPlan.entry`, which Phase 24 must rebuild from persisted data. A restored PROTECTED/COMPLETE/TP_UNAVAILABLE plan therefore
reaches `_check_liquidation_once` with `leverage=None`; `LiquidationWatch.check` returns `LIQUIDATION_UNKNOWN_AFTER_FILL`
and, with the owner's policy `CLOSE_POSITION` (D085), the coordinator enters CLOSE_REQUIRED and sends a reduce-only MARKET
close on a position that has a REST-confirmed stop and a perfectly good liquidation price. The only test
(`tests/test_protection_liquidation.py:431`) asserts the flag starts False; it does not run a restored entry through the hook.
**Fix:** Do not infer "unknown" from a missing in-memory leverage. In `LiquidationWatch._local_price` the leverage is only needed
for the comparison, not for the decision; the decision (`liquidation_beyond_stop` on the exchange value) needs no leverage at all.
```python
# check(): drop `leverage is None or leverage < 1` from the fail-closed condition; pass leverage
# only to _local_price (None => skip the comparison, local_price=None, which is already supported).
```
Add a test that restores a PROTECTED plan whose snapshot leverage is `None` and asserts no B6 transition.

### WR-04: The coordinator closes on its own error paths even when the owner's policy is ALERT_ONLY

**File:** `src/execution/protection.py:1695-1721` (`except Exception` -> `_enter_close_required(... B6)`), `:1711-1712` (wrong verdict type), `:1696-1710` (input construction inside the same `try`)
**Issue:** The policy (CLOSE_POSITION vs ALERT_ONLY, owner item O-4) lives in the watch. When `watch.check` raises, when the
position row cannot be turned into a `LiquidationWatchInput` (`entry_price` not a positive Decimal, `position_amt` not Decimal), or
when the verdict has the wrong type, the coordinator unconditionally enters CLOSE_REQUIRED, whatever the policy. With
`ALERT_ONLY` an UNKNOWN exchange value only alerts (`liquidation_watch.py:267`), while the same uncertainty arriving as an
exception closes the position. The branch is unpinned: `test_a_watch_that_raises_is_a_close...` uses a `ScriptedWatch` that has no
policy concept, and the real-watch hook test uses `CLOSE_POSITION` only.
**Fix:** Expose the policy on the port (`LiquidationWatchPort.policy`) and, in the `except`, close only for `CLOSE_POSITION`;
for `ALERT_ONLY` journal `EVENT_LIQUIDATION_CHECK_ERROR`, raise the `_liquidation_alert` with `LIQUIDATION_UNKNOWN_AFTER_FILL`
and return False. Add the `ALERT_ONLY` x {raises, wrong type, bad row} tests.

### WR-05: `OK_DIFFERS` raises a critical DIVERGENCE alert on the normal case, including the project's own Demo record

**File:** `src/execution/protection.py:1735-1737`; `src/execution/liquidation_watch.py:186-195, 281-284`; `tests/test_liquidation_watch.py:129-145`
**Issue:** The watch calls two prices "equal" only when the local price rounded half-up to the exchange string's decimal places
equals the exchange string. The local price omits funding and the exit fee and the exchange rounds its wallet, so equality at the
exchange's own 8 places is the exception: the recorded Demo position (`22-DEMO-RESULTS.md` R-7, 64968.85373637 vs 64968.853735)
yields `OK_DIFFERS` (the test at line 129 asserts it), while the same numbers against a coarser exchange string are `OK` (line
144). So a critical `DIVERGENCE` alert (`self._alerts.critical`) goes to the operator on essentially every fill, for a result the
module docstring calls "calibration only". That trains the operator to ignore the one event type that also carries real
reconciliation divergences, and the "differs" predicate depends on how many digits the exchange happens to print, not on any
tolerance.
**Fix:** Journal `OK_DIFFERS` (already done) but do not alert on it; alert only when the difference exceeds a tolerance the owner
sets (a new `NOT_CONFIGURED` key, or keep it journal-only until calibration data exists). Remove the `_liquidation_alert` call at
`protection.py:1737` or gate it on that key.

### WR-06: The margin-claims circuit is not closed: nothing writes `required_margin`, nothing calls `mark_placed`

**File:** `src/persistence/risk_reservations.py:237-250, 254-319, 402-413`; `src/risk/margin_check.py:331-368`; `src/execution/margin_guard.py:386-402`
**Issue:** `grep` of `src`/`scripts` finds no writer of `required_margin`/`margin_entry_price`/`margin_leverage` (only
`register_request` stores a given value) and no caller of `mark_placed`/`mark_open`. The deferral is recorded in `22-VERIFICATION`,
but its effect on the guard is worse than "claims proven on fakes only":
1. Every approved-but-unplaced peer is a RESERVED row with `required_margin = None`; `other_claims_margin` returns `None` for any
   counted claim with unknown margin, so ONE approved peer makes every other placement `UNCERTAIN_ACCOUNT_STATE`, and two approved
   peers refuse each other symmetrically. Nothing releases a RESERVED row after a guard refusal (`release_reason_for_placement_refusal`
   returns None for margin refusals), so the refusal lasts until the plan expires.
2. `register_request` can only set the trio at creation of the REQUESTED row (the identity check at `:305-314` turns a later write
   into `RowConflict`); there is no setter, so the margin must be known before the leverage is verified.
3. The netting branch (`placed_at_utc <= reading.observed_at_utc` is skipped, margin_check.py:363) is correct only if
   `placed_at_utc` is stamped AFTER the exchange holds the order. The reading is stamped BEFORE its first request
   (`account_equity.py:182`). If Phase 24 stamps `placed_at` at `mark_placed` before the POST (the write-ahead pattern used for the
   consume), a guard whose reading starts after `placed_at` but whose server-side read precedes the order's registration counts the
   claim in neither place. No test pins which instant `placed_at` must be.
**Fix:** Record the Phase 24 contract in code, not prose: (a) a `PgRiskReservationStore.set_margin(trade_plan_id, ...)` used by the
approval path, or compute the margin from `quantity`, `margin_entry_price` and `margin_leverage` in the reader so a claim is never
unknown for a Phase 22 row; (b) `placed_at_utc` is stamped from the ack time, with a documented skew margin added in
`other_claims_margin`; (c) release the RESERVED row on a `INSUFFICIENT_MARGIN`/`LIQUIDATION_TOO_CLOSE` refusal or treat that
refusal as non-claiming. Pin each in `tests/test_phase22_gate.py`.

### WR-07: `required_margin` is not tied to `quantity x margin_entry_price / margin_leverage`; a stored understatement is trusted

**File:** `src/risk/reservations.py:156-175`; `src/db/alembic/versions/0012_reservation_margin.py:57-68`; `src/persistence/risk_reservations.py:183-189`
**Issue:** The migration docstring and `RiskReservationRow` docstring state `required_margin = quantity x margin_entry_price /
margin_leverage`, but neither `ReservationRequest._require_margin_trio`, the CHECK constraints (`coherent`, `positive`) nor the reader
enforces it. `_claim_from_row` copies `required_margin` as stored. Any positive value passes (`tests/test_risk_reservations.py:483`
only exercises the correct value). A writer that stores 0.000001 understates the claim, and the placement-time sum then over-admits
plans: the failure mode this phase exists to prevent, via the one column the guard cannot cross-check.
**Fix:** Derive it. Either compute `required_margin` inside `ReservationRequest.__post_init__` and reject a different supplied value,
or drop the stored amount and compute `quantity * margin_entry_price / margin_leverage` in `_claim_from_row`; add a CHECK
`required_margin = quantity * margin_entry_price / margin_leverage` (exact `NUMERIC` equality) to a new migration.

### WR-08: The rehearsal's `margin_guard` seam gives the guard a way around the DRY_RUN and Demo-host guard

**File:** `scripts/demo_rehearsal.py:1940-1946, 2022, 2974-3041`; `GuardedAdapter` at `:633-990`
**Issue:** `GuardedAdapter` states "in DRY_RUN never reach a mutating method" and counts `mutating_attempts`; it has none of the Phase 22
adapter methods (`symbol_config_snapshot`, `leverage_brackets_snapshot`, `change_margin_type`, `change_initial_leverage`, the three
account reads), so a `MarginGuard` injected through `main(margin_guard=...)` cannot be built over `GuardedAdapter`. The only
way to build one is over the raw adapter (`bundle.inner`), and then `evaluate` POSTs the configuration to the host even in DRY_RUN,
without the host-guard call (`self._guard()`), the error log or the evidence record. The seam type (`MarginGuardPort`) carries no
indication of that.
**Fix:** Add the six methods to `GuardedAdapter` (reads pass, the two POSTs follow the `mutating_attempts`/DRY_RUN rule and return a
simulated success only if the guard also simulates the read-back), and make `build_context` refuse a `margin_guard` that was not built
over the guarded adapter (an `adapter` attribute check, or construct the guard inside the rehearsal from `ctx.guarded`).

### WR-09: The 5x cap is enforced only inside `SymbolConfigGuard`; `MarginGuard` accepts any leverage the port reports

**File:** `src/execution/margin_guard.py:456-466` (`_verified_configuration`); cap at `src/execution/symbol_config_guard.py:142-143`
**Issue:** `MarginGuard` talks to `ConfigGuardPort` and re-checks the margin type (`TARGET_MARGIN_TYPE`) but not the leverage cap: any
`int >= 1` from the port is used for the initial margin and the liquidation price. With `SymbolConfigGuard` the verified leverage can only
be the constructor target (<= 5), so today this is safe; a different port implementation (a Telegram-driven control, which D085 records as
a future requirement and which must "never exceed the D035 cap") would pass 50x straight through the guard whose job is to enforce the
cap. This is a safety property that is true only by convention between two files.
**Fix:** `from src.execution.symbol_config_guard import TARGET_LEVERAGE` and in `_verified_configuration` return None when
`leverage > TARGET_LEVERAGE`; add a test with a scripted port returning leverage 6.

## Info

### IN-01: Error-table rows and probe comments still say "not observed" for facts the 2026-10-24 Demo run observed

**File:** `src/domain/exchange_errors.py:654-665` (-4028: "not stated and not observed"), `:632-643` (-4047 "HTTP class not stated"), `:467-473` (-2019 has no Demo date); `scripts/demo_probe.py:4705` ("-4028 or -4209, unobserved")
**Issue:** `22-DEMO-RESULTS.md` R-2, R-3 and R-6 record -4047, -4028 and -2019 as BAD_REQUEST / REJECTED_DEFINITIVE on Demo. The table rows are the audit trail for the classifier and now understate the evidence.
**Fix:** Add the Demo date and the observed class to the three rows (the `source` still names the page read).

### IN-02: `22-VERIFICATION.md` contradicts the repository after D085

**File:** `.planning/phases/22-leverage-margin-liquidation-guard/22-VERIFICATION.md:73-76, 115, 140`
**Issue:** It says the three `margin.*` keys are `NOT_CONFIGURED` ("lines 56 to 59 and 89 to 92") and that the netting constant "stays False"; the committed file has 300 / 60000 / 1000 with provenance DECISION and the constant is True. D085 also says Phase 24 must pass `CLOSE_POSITION` "to `ProtectionCoordinator`" while the code takes the policy in `LiquidationWatch.__init__` (the coordinator takes the watch).
**Fix:** Re-run the verification digest or add an "as of D085" addendum; correct the D085 wording at the next DECISIONS touch.

### IN-03: `equity_used` on the in-memory snapshot is the guard's reading, not the equity the order was sized with

**File:** `src/execution/manager.py:1061-1066`
**Issue:** `replace(..., equity_used=guard_verdict.equity_used)` takes the equity of the guard's own reading, which is a second REST reading seconds after the one that sized the order (`risk_kwargs["account_state"].equity`). The field name and D-05 say "equity used"; the value can differ.
**Fix:** Set `equity_used=risk_kwargs["account_state"].equity` (assert equal to the same basis) and keep the guard's value only for the margin judgement.

### IN-04: The configuration POSTs do not honour the adapter's drift guard

**File:** `src/adapters/binance_usdm.py:1858-1915` (no `_require_entries_allowed()`), compare `:1353` (`place_entry`)
**Issue:** While the clock-drift guard blocks new entries, `place_entry` raises `EntriesBlocked` but `change_margin_type` / `change_initial_leverage` still go out, so a plan that cannot be placed still mutates the account (same effect as WR-01, different trigger).
**Fix:** Call `self._require_entries_allowed()` first in both methods; the guard already treats any exception as "unverified".

### IN-05: Two things that are the same by convention only

**File:** `src/execution/margin_guard.py:243-246` and `src/execution/bracket_cache.py:56-59`; `margin_guard.py:259-311`, `bracket_cache.py:107-131`, `liquidation_watch.py:201-217`
**Issue:** (a) Two different Protocols are both called `BracketPort` (`get(symbol)` vs `leverage_brackets_snapshot(symbol)`). (b) `MarginGuard`, `BracketCache`, `LiquidationWatch` and the manager's gate 2b each receive their own `ExecutionLimits` instance; nothing asserts they are the same object, so the guard's 60 s bracket bound and the cache's can differ. (c) `MarginGuard` and `BracketCache` validate the limit values as plain ints >= 1, `LiquidationWatch` does not (a buffer of 0 makes `check` raise `ValueError` out of `liquidation_beyond_stop`, outside any `try`, and the coordinator then closes under WR-04).
**Fix:** Rename the guard-side protocol to `BracketSource`, validate `buffer_bps` in `LiquidationWatch.__init__`, and build all four from the one loaded object in the Phase 24 composition (add that to the gate test).

### IN-06: Owner-run probe cases do not apply the D035 cap and always send both POSTs

**File:** `scripts/demo_probe.py:4564, 4586-4595`; `src/ops/operator_evidence.py:483-499`
**Issue:** `config_target_leverage` accepts any positive int, so a typo (50) leaves the Demo symbol at x50, and `_symbol_config_change_to_isolated` sends the margin-type and leverage POSTs even when it has just recorded `already_at_target = true` (the -4046 answer is data, but the leverage POST is still a mutation).
**Fix:** Reject `config_target_leverage > TARGET_LEVERAGE` in `operator_evidence`; skip the POSTs when `already_at_target`.

### IN-07: A B6 close from PROTECTED_ENTRY_OPEN returns before the entry-remainder cancel

**File:** `src/execution/protection.py:1422-1426` vs `:2066-2069`
**Issue:** For the `UNPROTECTED`/`PROTECTED_ENTRY_OPEN` branch the liquidation hook runs before `_confirm`, and a CLOSE verdict returns without issuing the cancel of the open entry remainder that `_confirm` issues on every step. `_close_flow` cancels it on the next step and FLAT needs the entry terminal, so a late fill is closed later and never missed; the exposure window is one step interval.
**Fix:** Call `await self._cancel_entry_remainder(tracked)` inside `_check_liquidation_once` before `_enter_close_required` when `tracked.entry_terminal_at is None`.

### IN-08: Branches the tests leave unpinned or pin to the wrong thing

**File:** `tests/test_protection_liquidation.py:273-295, 431-436`; `tests/test_risk_reservations.py:483-496`; `tests/test_liquidation_watch.py:129-145`
**Issue:** (1) No test runs the real `LiquidationWatch` with `ALERT_ONLY` through the coordinator, or a restored entry with `leverage=None` (WR-03/WR-04). (2) Nothing pins the relation `required_margin == quantity * price / leverage` (WR-07) or which instant `placed_at_utc` means (WR-06). (3) The Demo-record test asserts the `OK_DIFFERS` outcome that WR-05 argues is noise, so a fix will have to change it deliberately. (4) I read only the test names, not the bodies, of `test_bracket_cache.py`, `test_liquidation_price.py`, `test_margin_check.py`, `test_snapshot_margin_leverage.py`, `test_leverage_margin_adapter.py`, `test_risk_reservation_margin_pg.py`, `test_phase22_gate.py`; the review of those rests on reading the modules they test.
**Fix:** Add the tests named under WR-03, WR-04, WR-06 and WR-07.

---

_Reviewed: 2026-10-24_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
