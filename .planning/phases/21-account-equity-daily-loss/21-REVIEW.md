---
phase: 21-account-equity-daily-loss
reviewed: 2026-10-24T00:00:00Z
depth: deep
files_reviewed: 24
files_reviewed_list:
  - src/risk/daily_loss.py
  - src/risk/live_equity.py
  - src/risk/reservations.py
  - src/execution/account_equity.py
  - src/execution/day_risk_service.py
  - src/execution/daily_stop.py
  - src/execution/live_risk_inputs.py
  - src/execution/execution_limits.py
  - src/execution/manager.py
  - src/persistence/day_risk.py
  - src/persistence/risk_reservations.py
  - src/persistence/approvals.py
  - src/persistence/__init__.py
  - src/db/alembic/versions/0010_daily_risk_state.py
  - src/db/alembic/versions/0011_risk_reservations.py
  - src/db/models.py
  - src/adapters/binance_usdm.py
  - src/ops/alerts.py
  - scripts/gen_phase21_fixtures.py
  - config/execution/execution-limits-v1.toml
  - tests/test_day_risk_service.py
  - tests/test_day_risk_stream.py
  - tests/test_live_equity.py
  - tests/test_phase21_gate.py
findings:
  critical: 0
  warning: 10
  info: 9
  total: 19
status: issues_found
---

# Phase 21: Code Review Report

**Reviewed:** 2026-10-24
**Depth:** deep (cross-file: equity source -> day service -> store -> reservation -> approval transaction -> manager seam)
**Files Reviewed:** 24 (20 source/config files and 4 test files read in full or in the relevant part; cross-module reads of `src/risk/portfolio.py`, `src/persistence/uow.py`, `src/approval/replay.py`, `src/adapters/telegram_callbacks.py`, `src/execution/margin_guard.py`, `src/execution/fill_monitor.py`, `src/backtest/ledger.py` and `docs/trading/RISK_MANAGEMENT.md` to confirm the contracts)
**Status:** issues_found

## Summary

The pure rules are in good shape and I could not break them: the equity resolver rejects None, stale (age over the bound), future-dated (negative age), non-Decimal, bool, NaN/Inf and non-positive values, and the age edge is exactly right (equal passes, over fails, negative fails). `equity_basis` is the single place the basis is chosen and now returns `min(wallet, margin)` (D086). `fold_daily_loss` has the right signs (commission is MINUS the commission, funding as reported), counts a fill that both the stream and REST report once at the most adverse amount, never turns an unknown into zero, and the UTC-day boundary is half-open at 00:00:00.000. No `float(` constructor, no wall clock and no numeric default for `account.max_equity_age_ms` exists in `src`. Messages in the persistence layer name keys, never amounts. The approval transaction is composed correctly (decide, then hook, same session, any raise rolls back), the day-row `FOR UPDATE` lock is taken before the reservation lock everywhere, and the migrations match the ORM and have real downgrades.

I found no Critical defect, because nothing Phase 21 built is wired into a process and live placement is disabled. I found ten Warnings that must be closed before Phase 24 composes the pieces. The two I would fix first are WR-03 (the manager sizes from a caller-supplied `account_state` and never compares it with the live equity that the margin guard fetches in the same call, so the phase goal "never a caller-supplied constant" is not enforced at the one seam that matters) and WR-02 (the "single lock every approval serialises on" is a per-UTC-day row, so two approvals that straddle 00:00 UTC do not serialise and can both pass the caps). Two claims were confirmed by running the real service with the repo's own test doubles (WR-01 and WR-08; probe output quoted there).

Targeted checks only: no full suite was run and no network was used.

## Warnings

### WR-01: A held or just-derived DAILY_STOP is dropped to a state-less NO_TRADE on a store error, so no entry cancel is attempted

**File:** `src/execution/day_risk_service.py:425-428` and `:452-456`
**Issue:** `evaluate` reads the stored components before it consults the latch. If `list_components` raises, it returns `_blocked(day, DAY_STATE_UNREADABLE)` (state `None`) even though `opened.stop_latched_at_utc` is already set. The comment a few lines later (the fold-error branch, 439-441) states the invariant "a held latch must still answer DAILY_STOP", and `evaluate_day_state` implements it, but this earlier branch bypasses it. The second case is the same shape: when the loss newly crosses the stop and `latch_stop` raises, the verdict is replaced by a blocked one (state `None`).

Failure scenario: DAILY_STOP is latched at 10:00 with a resting entry whose cancel was refused (rate-limit pause, `not_cancelled`). At 10:05 the components read hits a DB hiccup. `evaluate` returns state `None`; `enforce_daily_state` runs `_cancel_entries` only for `verdict.state is DAILY_STOP` (`daily_stop.py:230`), so the retry of the cancel does not happen and the resting entry stays live while the account is over its daily limit; it can fill and open a new position on a stopped day. The module docstring of `daily_stop.py` (lines 16-18) says exactly that "a later call while the latch holds is the retry of a cancel that did not finish".

Reproduced with the repo's own doubles (`tests/test_day_risk_service._latched_rig`, then `store.raise_next("list_components", StoreUnavailable)`):
`latched + unreadable components -> None DAY_STATE_UNREADABLE`.
`test_unreadable_components_block` (tests line 511) only covers the unlatched day, so this is unpinned.

**Fix:** Honour the latch before touching the components, and let a derived stop drive the cancels even if the latch write fails:
```python
opened = await self.ensure_day(...)
...
if opened.stop_latched_at_utc is not None:
    return evaluate_day_state(day=opened, loss=_unknown_loss_result(), parameter_set=self._parameter_set)
...
if verdict.latch_now:
    try:
        self._store.latch_stop(utc_day=day, at_utc=now_utc)
    except Exception as exc:
        self._last_error_type = type(exc).__name__
        # keep the DAILY_STOP verdict (it is risk-reducing); report the store failure separately
        return dataclasses.replace(verdict, latch_now=True)  # the next call retries the write
```
Add a PG-free test: latched day + `raise_next("list_components")` must return `DAILY_STOP`, and `enforce_daily_state` must attempt the cancel.

### WR-02: The approval serialisation lock is a per-UTC-day row, so approvals around 00:00 UTC do not serialise

**File:** `src/persistence/risk_reservations.py:355` (docstring lines 14-15 and 538-541)
**Issue:** `reserve_in` locks `daily_risk_days` for `utc_day_of(now_utc)` where `now_utc` is `approval.acted_at_utc`, i.e. the callback time chosen by the dispatcher, not the database time. The module claims this is "the one lock every approval serialises on". It is one lock per day. The counted-row read that follows (`_counted_rows`) is global across days. Two approvals decided within the same few hundred milliseconds across midnight (A with `acted_at` 23:59:59.9 locking day D, B with `acted_at` 00:00:00.1 locking day D+1) take different locks, both read the same counted set, and both pass `max_open_positions`, the aggregate cap or the cluster cap that either alone would have used up. The same split happens with any clock skew between the two dispatch processes. This is the F-407 race the table exists to prevent.
**Fix:** Serialise on a day-independent key. Either take a transaction-level advisory lock with a fixed key before the day lock (`SELECT pg_advisory_xact_lock(<constant>)`), or lock a single sentinel row. Keep the day-row lock for the latch read. Add a `*_pg.py` test that runs two approvals with `acted_at` on both sides of midnight and asserts only one reserves.

### WR-03: The manager sizes from a caller-supplied `account_state` and never compares it with the live equity of the same call

**File:** `src/execution/manager.py:796` (`evaluate_risk(**risk_kwargs)`), `:1057-1066`; `src/execution/margin_guard.py:427`
**Issue:** The phase goal is "sizing and DAILY_STOP use Binance-canonical equity, never a caller-supplied constant". In code, `execute_approved_plan` still takes `risk_kwargs["account_state"]` verbatim, and `live_risk_inputs.py` is only a convention for the caller. Since Phase 22 the same function fetches a fresh, age-checked equity (`guard_verdict.equity_used`) but uses it only to complete the in-memory snapshot; no line compares it with `risk_kwargs["account_state"].equity`. A caller that passes a larger (stale, cached, or hard-coded) `AccountState` sizes a larger quantity than the live equity allows, and the margin guard (which checks free margin, not risk-per-trade) does not catch it. `grep -rn account_state src/execution` shows no check.
**Fix:** After the guard passes, refuse when the sizing equity exceeds the live one:
```python
if risk_kwargs["account_state"].equity > guard_verdict.equity_used:
    return ExecutionOutcome(is_no_trade=True,
                            reason_code=RejectionReason.UNCERTAIN_ACCOUNT_STATE.value)
```
(or better, make the manager accept only a `LiveRiskInputs` object so `account_state`, `daily_loss_quote` and the thresholds cannot come from anywhere else). Pin it with a test that passes an inflated `AccountState`.

### WR-04: `build_live_risk_inputs` ignores the day's latch and has no freshness or "is today" check

**File:** `src/execution/live_risk_inputs.py:160-188`
**Issue:** The builder trusts `verdict` and `day` as given. (a) It never looks at `day.stop_latched_at_utc`: a verdict computed before the latch (state NORMAL or WARNING) paired with a freshly read latched `day` yields inputs. The latch semantics ("held for the rest of the UTC day whatever the loss does", D-14) then exist only if the caller happened to evaluate after the latch. `execute_approved_plan` itself takes only `daily_loss_quote`, so a later gain can lower the quote below the stop and entries re-open the same day. (b) Only `verdict.utc_day == day.utc_day` is checked; there is no `now_utc`, so yesterday's day row plus yesterday's verdict builds inputs on the next day, and a verdict hours old has no age bound while the equity has 15 s. (c) `LiveEquityResult` carries `observed_at_utc` but the builder does not re-check it, so the "resolve with a `now` read after refresh" contract is convention only.
**Fix:** Add `now_utc` and `max_equity_age` parameters; refuse when `day.stop_latched_at_utc is not None` (`DAILY_STOP_BLOCK`), when `day.utc_day != utc_day_of(now_utc)`, or when `now_utc - equity.observed_at_utc` is outside `[0, max_age]`. Test each.

### WR-05: A "known" daily loss never expires by time

**File:** `src/execution/day_risk_service.py:285-287` and `:466-469`
**Issue:** After one successful `backfill`, `_backfill_is_current` stays true until `invalidate` or an unusable fill bumps the generation. The equity has an owner age bound (15000 ms); the loss, which gates DAILY_STOP and the approval reservation (`current_daily_loss_quote`), has none. A fill that the stream never delivers and that raises no gap (a manual trade in the exchange UI, a symbol outside `symbols`, a liquidation or ADL frame that is dropped, a half-open socket) leaves the loss "known" and understated for the rest of the day. The mitigation (the SAFE_MODE user-data-silence alert of Phase 20) is a different module and is not part of this contract.
**Fix:** Stamp the backfill with `observed_at` (the clock after the reads) and make `_backfill_is_current` also require `now - stamp <= max_loss_age` from an owner key (`NOT_CONFIGURED` until the owner decides, same hygiene as the equity key). At minimum, document in `current_daily_loss_quote` that freshness is delegated to the stream-silence alert.

### WR-06: The "late open is over-counted at worst" claim is wrong for a day that started with a gain

**File:** `src/execution/day_risk_service.py:37-39`, `:389-405`
**Issue:** When the first read of a UTC day happens after 00:00, the base is the equity of that moment while the backfill counts every fill since 00:00. After a morning loss L the base is `E0 - L` (thresholds smaller: conservative, true). After a morning gain G the base is `E0 + G`: the thresholds are `r*(E0+G)`, larger than the `r*E0` D033 prescribes, and the net day PnL is `-(G) + new loss`, so the account can lose `r*E0 + G*(1+r)` before DAILY_STOP. The docstring says the opposite; the base is also `min(wallet, margin)` so unrealised PnL at that moment shifts it again.
**Fix:** Derive the day-start base from facts instead of the first read: `base = equity_now - net_day_pnl` (wallet at the read minus the sum of the day's components), or refuse to open a late day while the net day PnL is positive, or correct the docstring and record the divergence next to O-6. The first is exact and uses data the service already has.

### WR-07: Failed, unverified and unmatched DAILY_STOP cancels emit no alert, and the one-shot alert is swallowed silently

**File:** `src/execution/daily_stop.py:188-206`, `:239-269`
**Issue:** `enforce_daily_state` only alerts for `verdict.alerts_due` (non-empty only on the evaluation that latches) and for the two DB reasons. The outcome fields `not_cancelled` (rate-limit pause, snapshot failure), `unverified` (`STILL_OPEN`, `GONE_NOT_CANCELED`, `UNKNOWN`) and `unmatched_entry_orders` are returned to the caller and alerted nowhere, so an entry that failed to cancel at a stopped day produces the same single "DAILY_STOP" message as a clean stop. `_emit` also returns silently on any sink exception: a sink that queued the alert and then raised `AuditRecordLost` (`JournalFirstAlertSink` does this by design) is reported as not emitted, and a sink that raised before queuing loses the only DAILY_STOP alert (the verification report lists the one-shot delivery as advisory 1; the lost-cancel part is new).
**Fix:** Emit a second event (for example reuse `UNKNOWN_ORDER` / add `DAILY_STOP_CANCEL_INCOMPLETE`) when any of the three tuples is non-empty; log the swallowed exception class through the spill; re-emit the DAILY_STOP alert while the latch is held and the last cancel was incomplete. Test `not_cancelled` -> alert.

### WR-08: One missing prior day plus an open position blocks the day permanently with no way out

**File:** `src/risk/daily_loss.py:515-537`, `src/execution/day_risk_service.py:369-370`
**Issue:** `previous_present` looks only at `day - 1`. After any outage of two UTC days or more (a weekend maintenance window), today has no row and yesterday has no row, so with `exposure=True` (or unknown) `day_open_action` returns `BLOCKED_MISSING_STATE`, forever, for as long as the position is open; the acknowledgement path is explicitly not built. Positions are only protected by stops, so the account can sit in DAY_STATE_MISSING (and `DB_FAILURE` alerts) for days. Fail-closed in direction, but the rule "a rollover from a persisted previous day" (D-08) is satisfied by any persisted earlier day, which proves the store is intact. Reproduced:
`two-day gap with exposure -> None DAY_STATE_MISSING`.
**Fix:** Replace `has_day(day - 1)` with "any earlier day row exists" (`SELECT 1 FROM daily_risk_days WHERE utc_day < :day LIMIT 1`). Keep the block only for a store that has never held a day. Add the two-day-gap test.

### WR-09: The REST backfill covers only the configured symbols and only FUNDING_FEE, but is labelled "trades_complete"

**File:** `src/execution/day_risk_service.py:268-277`, `:285-287`
**Issue:** `backfill` reads `userTrades` for `self._symbols` and `income` for `FUNDING_FEE` only, then sets both completeness flags. Realised PnL and commission of a trade on any other symbol (a leftover position, a manual trade, a delisted contract) and income types such as `INSURANCE_CLEAR` (the liquidation clearance fee) never enter the fold, while `fold_daily_loss(trades_complete=True)` reports a known loss. The deferred register lists "symbols outside the live universe" as `[NOT_TESTED]`, but the flag name and the docstrings say complete. This is the understated-loss direction.
**Fix:** Cross-check the sum of the day's `REALIZED_PNL` and `COMMISSION` income rows (all symbols, one paged call) against the folded fills; if they differ beyond zero, mark the loss unknown. Until then rename the flags (`symbols_complete`) and state the limit in `fold_daily_loss`.

### WR-10: The release table can leave counted risk with no exit, contrary to its own docstring

**File:** `src/risk/reservations.py:14-15`, `:97-109`; `src/persistence/risk_reservations.py:415-426`
**Issue:** `RELEASE_SOURCE_STATUSES` permits `POSITION_CLOSED` only from `OPEN`, and `OPEN` is reached only by `mark_open` (PLACED to OPEN). If the first fill is missed by the caller (stream gap, restart between fill and `mark_open`), protection reaches FLAT, `release(POSITION_CLOSED)` raises `RowConflict` on the PLACED row, and the row stays counted (`max_open_positions`, aggregate and cluster caps) until someone edits the table: there is no operator release and no other permitted reason from PLACED for a position that existed. The module claims "no counted reservation is left without an exit (D-16)" and the deferred register (row 26) records it only as a caller rule.
**Fix:** Permit `POSITION_CLOSED` from `{PLACED, OPEN}` (a closed position implies the entry filled) and add an operator reason (`OPERATOR_RELEASED`) to the CHECK in a migration 0013, and update the docstring. Test PLACED -> POSITION_CLOSED.

## Info

### IN-01: `ck_risk_reservations_released_coherent` accepts partial release fields on a non-released row

**File:** `src/db/alembic/versions/0011_risk_reservations.py:106-109` (same text in `src/db/models.py:1184-1187`)
**Issue:** `(status = 'RELEASED') = (release_reason IS NOT NULL AND released_at_utc IS NOT NULL)` is satisfied by a REQUESTED/RESERVED row that carries `release_reason` but a NULL `released_at_utc` (or the reverse): both sides are false.
**Fix:** `(status = 'RELEASED' AND release_reason IS NOT NULL AND released_at_utc IS NOT NULL) OR (status <> 'RELEASED' AND release_reason IS NULL AND released_at_utc IS NULL)`, in the next migration.

### IN-02: "Never cleared or moved" is enforced by application code only

**File:** `src/persistence/day_risk.py:176-217`, `src/db/alembic/versions/0010_daily_risk_state.py`
**Issue:** The latch and the warning mark are set once by a conditional UPDATE, but nothing in the database stops a raw `UPDATE ... SET stop_latched_at_utc = NULL` (the approvals table, by contrast, uses a unique index for the same kind of rule). No CHECK keeps the marks inside `utc_day`; the domain object does that on read, and a bad row then fails every `get_day`.
**Fix:** A `BEFORE UPDATE` trigger or CHECKs `stop_latched_at_utc IS NULL OR stop_latched_at_utc::date = utc_day` and a trigger refusing NULL-ing of a set mark.

### IN-03: The invalidation contract is two independent hooks with duplicated constants, and ACCOUNT_CONFIG_UPDATE is not one of the reasons

**File:** `src/execution/account_equity.py:55`, `src/execution/day_risk_service.py:87`
**Issue:** Equity and loss are invalidated by two `invalidate` methods with separate copies of `{"ACCOUNT_UPDATE", "STREAM_GAP"}`. Phase 24 must call both from the router and the supervisor; nothing ties them. An `ACCOUNT_CONFIG_UPDATE` (leverage or multi-asset change on the stream) invalidates neither; the cached `multi_assets_margin=False` can live up to the age bound (15 s).
**Fix:** One shared constant and one fan-out helper (`invalidate_account_reads(reason)`) in the composition layer; accept an `ACCOUNT_CONFIG_UPDATE` reason for the equity source.

### IN-04: `fold_daily_loss` puts amounts in an exception message

**File:** `src/risk/daily_loss.py:312-315`
**Issue:** The `ValueError` text includes both amounts. Everything in `src/persistence` avoids amounts and the service keeps only the type name, but a future direct caller that logs `str(exc)` leaks account figures (OPS-02 posture).
**Fix:** Name the key and the kind only.

### IN-05: Stale header and docstring claims

**File:** `config/execution/execution-limits-v1.toml:1-26`, `src/execution/day_risk_service.py:47`
**Issue:** The file header still says "Every value is the string NOT_CONFIGURED until the owner fills them" and does not list the `margin.*` keys, while four keys are now set (D084, D085). The service docstring says "stdlib and `src.risk` only" but imports `src.domain.enums`.
**Fix:** Edit the header comment (it is not hashed; the values and provenance tables are what the loader reads) and the docstring.

### IN-06: `assert` is the only type guard on port results

**File:** `src/execution/day_risk_service.py:381`, `src/risk/daily_loss.py:489`
**Issue:** `assert isinstance(today, DayRiskState)` narrows a value that comes from an `Any`-typed port. Under `python -O` the check disappears and a mis-shaped store result is used as a day state (it still fails later with an AttributeError, so it does not fail open, but not at the place intended).
**Fix:** `if not isinstance(today, DayRiskState): return self._blocked(day, BLOCKED_DAY_STATE_UNREADABLE)`.

### IN-07: Non-atomic equity reads are checked for exact equality, and the identities are demo-only

**File:** `src/risk/live_equity.py:237-248`, `src/execution/account_equity.py:183-185`
**Issue:** `accountConfig`, `account` and `balance` are three sequential reads, never retried (D-20), and `balance_endpoint_wallet == total_wallet_balance` is exact. A fill or funding event between the second and third read makes the reading unusable (NO_TRADE until the next refresh). The identities (margin = wallet + unrealised, quote row = account total, balance row = wallet) are demonstrated only on the Demo account whose totals exclude other assets; on a mainnet account holding BNB or USDC the totals may differ and the equity would be permanently NO_TRADE. Both fail closed.
**Fix:** Nothing to change now; add the identity check against a real mainnet read-only capture to the Phase 26 canary list.

### IN-08: The `userTrades` first page assumes ascending order and an unknown default limit

**File:** `src/adapters/binance_usdm.py:1936-1972`
**Issue:** Page 1 sends the window and no `limit`; later pages use `fromId = last_id + 1`. The docstring admits the paging order is not documented. A descending page raises (ids must increase), but a first page that holds the newest N rows of the window in ascending order would be followed by an empty `fromId` page and silently drop the older rows.
**Fix:** Send an explicit `limit=1000` and, when page 1 is full, assert its first row is the earliest in the window (re-read with `startTime` of the first row's time to confirm nothing precedes it), or cross-check with the day's `REALIZED_PNL` income sum (WR-09).

### IN-09: Branches the tests do not pin

**File:** `tests/test_day_risk_service.py`, `tests/test_risk_reservation_approval_pg.py`
**Issue:** No test covers: a latched day with unreadable components (WR-01); a latch write failure on a stop that should cancel entries (WR-01); a two-day gap with exposure (WR-08); two approvals across midnight (WR-02); `PLACED -> POSITION_CLOSED` (WR-10); a failed/unverified cancel producing an alert (WR-07). The positive tests I read assert the right thing; none masks a defect.
**Fix:** Add the six tests with the fixes above.

---

_Reviewed: 2026-10-24_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
