---
phase: 20-reconcile-safe-mode-hardening
closure_note: "CR-C1 and the warnings fixed by gap plans 20-27..20-30 (2026-10-23); the rest are in 20-DEFERRED.md"
reviewed: 2026-10-22T00:00:00Z
depth: deep
files_reviewed: 42
files_reviewed_list:
  - src/execution/protection.py
  - src/execution/protection_rebuild.py
  - src/execution/protection_replay.py
  - src/execution/emergency_close.py
  - src/execution/lot_filter_source.py
  - src/execution/pending_actions.py
  - src/execution/cancel_verification.py
  - src/execution/manager.py
  - src/execution/intent_recovery.py
  - src/execution/intent_store.py
  - src/execution/order_ids.py
  - src/execution/live_context.py
  - src/execution/enablement.py
  - src/execution/execution_limits.py
  - src/domain/transitions.py
  - src/domain/enums.py
  - src/domain/stream_records.py
  - src/db/models.py
  - src/reconcile/loop.py
  - src/reconcile/classify.py
  - src/reconcile/compare.py
  - src/reconcile/local_intent.py
  - src/reconcile/feed_freshness.py
  - src/reconcile/safe_mode.py
  - src/reconcile/startup.py
  - src/reconcile/sweeper.py
  - src/reconcile/__init__.py
  - src/persistence/safe_mode_store.py
  - src/persistence/pending_actions.py
  - src/persistence/lot_filters.py
  - src/persistence/execution_state.py
  - src/persistence/__init__.py
  - src/db/alembic/versions/0007_intent_resolution_reason.py
  - src/db/alembic/versions/0008_pending_protective_actions.py
  - src/db/alembic/versions/0009_validated_lot_filters.py
  - src/ops/alerts.py
  - src/ops/drills.py
  - src/ops/risk_first.py
  - src/ops/spill.py
  - src/ops/rest_gate_cli.py
  - src/ops/rest_gate_state.py
  - src/adapters/binance_ratelimit_gate.py
findings:
  critical: 1
  warning: 21
  info: 12
  total: 34
status: issues_found
---

# Phase 20: Code Review Report

**Reviewed:** 2026-10-22
**Depth:** deep (3 parallel reviewers, one per area: A execution, B reconcile + persistence, C ops + REST gate)
**Diff base:** 567dd8af (parent of the first Phase 20 merge)
**Scope:** the 42 Phase 20 source files; tests, the quick task 261021-sj0 files and scripts/decision_alignment were not reviewed.

## How to read this report

Each lane's reviewer confirmed its findings by reading the source; none of them ran the code except where a finding says so. The orchestrator re-read the code for CR-C1, WR-B1 and WR-B2 and found them consistent with the report, and for WR-A2 saw that `_read_position` is the first gated call. The other findings are the reviewers' unverified claims and should be re-read before a fix. All findings fail closed unless stated. CR-C1 is also an item of `20-DEFERRED.md` ("LocalSpill.scan() swallows an OSError"); the reviewer rates it Critical and the deferred register rated it as a known limit. Nothing here changes a Phase 20 owner decision.

## Summary by lane

| Lane | Files | Critical | Warning | Info |
|---|---|---|---|---|
| A: execution | 18 | 0 | 4 | 4 |
| B: reconcile + persistence + migrations | 17 | 0 | 7 | 3 |
| C: ops + REST gate | 7 | 1 | 10 | 5 |


# Lane A: execution

# Phase 20: Code Review Report (lane A, execution area)

**Reviewed:** 2026-10-22
**Depth:** deep (Phase 20 diff `567dd8af..HEAD`, traced through callers, the transition table, the journal and the REST gate)
**Files Reviewed:** 18
**Status:** issues_found

## Summary

I read the 18 lane-A files in full and traced the Phase 20 changes through their callers: the
`PROTECTION` transition table and its clearing rules, rebuild and replay, the stop supervision and
D077 paths, the B2/B3 same-id re-place, the operator controls, the emergency closer and its restart
state, the cancel verification, the UNKNOWN-entry resolver, the journal's replay-idempotence and the
REST gate.

No critical defect was found in the paths the brief singles out:

- A confirmed-then-lost stop is never re-placed. The only `_place_stop` callers are
  `_on_first_fill` and the `_confirm` ABSENT branch, which is reachable only when
  `stop_lost_at is None` and `stop_confirmed_at is None` (`protection.py:1829-1847`).
- The B2/B3 re-place is single-shot per step, uses the same deterministic id, and runs only on a
  `found=False` REST answer of this step.
- A placement is never re-sent by the closer without a terminal proof of the earlier attempt.
- No float is used, no wall clock is read in a pure module, and no exception is classified by its
  message text (grep-checked in all eleven new or heavily changed modules).
- The PROTECTION table edges used by the live code are all present, and the UNPROTECTED to
  PROTECTED clearing rule correctly forbids a stop-lost plan.

The four warnings are fail-closed livelocks or unreachable-feature defects, not fail-open ones. The
four info items are contract or documentation drifts. Findings already recorded in
`20-DEFERRED.md` (replay chain after a forced-UNPROTECTED restore, sticky PENDING rows, no sweep
backoff, wiring gaps) are deliberately not repeated.

## Warnings

### WR-A1: UnknownEntryResolver can never close or ack an entry once its evidence row has been written once

**File:** `src/execution/intent_recovery.py:602-616` (also `:647-661`, `:717-733`);
cause in `src/domain/stream_records.py:186-197`, `src/persistence/journal.py:51-64,138-153`

**Issue:** `_exit_event` builds the closing evidence with `exit_evidence_event`. That function gives
the row a deterministic id from `(correlation_id, event_type, entity_id, "UNKNOWN->REJECTED")` and
puts `observed_at_utc = now_utc` in `payload_json`. `PgJournalStore` treats `payload_json` as an
identity field: a second write with the same id and a different payload raises `JournalConflict`
(`_IDENTITY_FIELDS` includes `payload_json`, only the two time columns are excluded).

`_step_one` writes the evidence row first and then calls `finalize_reconciled_resolution`. If
the finalize fails (a `PersistenceError`, `KEPT_STORE_FAILED`) or the process dies between the two
writes, the evidence row already exists. Every later attempt rebuilds the same id with a new
`observed_at_utc`. `self._journal.record` raises `JournalConflict`, `_journal_ok` returns False,
and the step returns `KEPT_JOURNAL_FAILED`. The same applies to `_ack` (`UNKNOWN->ACKED`).

**Failing scenario:** the DB blips once at the finalize call, then recovers. The probe count
restarts (`state.clean = 0`), the conditions are met again, and the evidence write conflicts. The
intent is `KEPT_JOURNAL_FAILED` on every future step. The entry intent stays UNKNOWN, so
`UNRESOLVED_EXECUTION_INTENT` SAFE_MODE can never be cleared by the system. Only manual DB surgery
resolves it. It fails closed, but it is a permanent livelock caused by one transient error or crash.

**Fix:** make the retry idempotent. Either keep the observed time stable per episode (store the
first `observed_at_utc` in `_ProbeState`, or in a persisted marker, and reuse it so the payload is
byte-identical), or include the attempt in the id (`step=f"UNKNOWN->{to}:{state.episode_no}"`).
Alternatively treat `JournalConflict` for this deterministic id as "evidence already journaled"
after reading the stored row back. Add a test: journal OK, finalize raises once, next step closes.

### WR-A2: The durable `CLOSE_NOT_SENT` path is unreachable under a real REST gate restriction

**File:** `src/execution/emergency_close.py:517-520` (also `:536-556`, `:562-586`, `:713-723`)

**Issue:** `RestRateLimitGate.check()` takes no category. Every signed SDK call, including
`snapshot_positions`, `symbol_lot_filters` and `query_order_by_client`, raises
`RateLimitBanActive`, `RateLimitPauseActive` or `GateNotRestored`, all `PreSendRefusal`s, while the
gate is restricted (`src/adapters/binance_usdm.py:714`, `binance_ratelimit_gate.py:84-125`).
`close_position` makes its first gated call at `_read_position`. The generic `except Exception`
turns the `PreSendRefusal` into `_fail("POSITION_READ_FAILED")`. The `PreSendRefusal` branch in
`_send_part` (`:713`), and with it `_not_sent`, `CLOSE_NOT_SENT` and the `NOT_SENT` status, are
reached only if the gate flips between the position read and the POST.

Plan 20-14 (D-19) states that a close the gate refuses is journaled as not sent and kept as a
durable PENDING row. In a 418 or 429 window that never happens for the close:

- No `CLOSE_NOT_SENT` row is written.
- `ProtectionCoordinator._close_failure()` reports `CLOSE_FAILED` rather than `CLOSE_NOT_SENT`.
- Each step enters SAFE_MODE `EMERGENCY_CLOSE_FAILED` with an alert reason `POSITION_READ_FAILED`.
- The `ALERT_EMERGENCY_CLOSE_NOT_SENT` code is dead in practice.

The same swallow applies to the lot-filter read, `discover_next_attempt_no` (reported as
`ATTEMPT_DISCOVERY_FAILED`) and the poll.

**Failing scenario:** a 429 pause starts while a plan is CLOSE_REQUIRED. The first `close_position`
call fails at the position read. After a restart nothing records that a close was refused. The
pending-action tests pass only because the fake adapter raises `PreSendRefusal` from
`place_market_close` alone.

**Fix:** in `close_position`, catch `PreSendRefusal` around `_read_position`,
`for_emergency_close`, `symbol_lot_filters` and `discover_next_attempt_no`, and route it to
`self._not_sent(entry, reason, parts_sent, _Outcome(_Kind.NOT_SENT, error_type=..., gate_reason=...,
retry_after_seconds=...))`. Do this before the generic `except Exception`. Add a test with a gate
that refuses every method.

### WR-A3: `emergency_manual_close` can never cancel the legs of an executed plan, contradicting its documented "second call once flat" workflow

**File:** `src/execution/manager.py:2345-2366` (keep logic), `:2524-2530`;
`src/execution/cancel_verification.py:94-107`

**Issue:** `_protectives_keep_reason` allows the legs to be cancelled only when
`entry_verdict in PROVEN_GONE` (CANCELED or GONE_NOT_CANCELED). For an entry that FILLED, the
normal executed case, `expire_pending_entry` cancels, the exchange answers -2011 (mapped to None),
and `confirm_entry_cancel` returns `FILLED_OR_PARTIAL`. The result is `KEEP_ENTRY_NOT_TERMINAL`,
even though both position reads are zero and a FILLED entry is terminal.

The `emergency_manual_close` docstring says the legs are removed "by the reconciler's orphan
sweeper or by a second call of this control once the position is flat". The second call can never
remove them, because the verdict is FILLED every time. Legs of a plan with no unfilled entry are
exactly the legs that exist: a stop and TPs are placed only after a fill. So step 5, the
cancel-and-verify branch and `MANUAL_CLOSE_ORPHAN_UNVERIFIED`, is effectively dead for the flow it
was written for. The journal row says `ENTRY_NOT_TERMINAL` for a terminal entry, which misleads the
operator.

**Fix:** distinguish FILLED from PARTIALLY_FILLED in the verdict. For example, add
`CancelVerdict.FILLED` as terminal, or have `_protectives_keep_reason` accept `FILLED_OR_PARTIAL`
when both fresh position reads are zero and a follow-up `confirm_entry_cancel` shows
`observed_status == "FILLED"`. Alternatively correct the docstring and the reason code and state
that the control never removes legs of a filled plan.

### WR-A4: The coordinator's FLAT sweep omits `spill`, so its protective-cancel audit rows are lost when the journal is down

**File:** `src/execution/protection.py:2405-2411` (callee `src/execution/manager.py:2205-2250`)

**Issue:** `cancel_untriggered_protectives` takes `spill` (D-16, F-702). The coordinator holds
`self._spill`, which it already uses for the operator audit rows and the pending-action intents,
but `_sweep` does not pass it. With the journal down, `act_then_record` and `record_after` find no
spill, so each leg raises `AuditRecordLost`. They are collected into an `ExceptionGroup`, the
`_sweep` handler logs `PROTECTION_SWEEP_FAILED`, and `sweep_done` is never set.

**Failing scenario:** the journal is down at FLAT. The legs are cancelled, which is the risk-reducing
effect, but no record survives. Every following step cancels and re-queries all three legs again
(3 cancels and 3 queries per step) until the journal returns, and the `cancel_unverified` or
`post_cancel` verdicts are never seen.

**Fix:** pass `spill=self._spill` (typed as `LocalSpill | None`, or widen the parameter to the
`IntentSpill` protocol) at `:2405-2411`. Consider recording a verdict-only success so a lost audit
row does not block `sweep_done` when the legs were proven gone.

## Info

### IN-A1: `MarketEmergencyCloser._last_result` is shared across plans that close concurrently

**File:** `src/execution/emergency_close.py:439,504` and `src/execution/protection.py:2345-2351`

`ProtectionCoordinator.step` runs plans under `asyncio.gather`, so two `close_position` calls can
interleave at awaits. `_last_result` is one attribute: the second call resets it to None at entry
and overwrites it on exit. `_close_failure()` in the coordinator reads it after its own `await`, so
it can classify plan A's failure (`CLOSE_NOT_SENT` versus `CLOSE_FAILED`) from plan B's result. The
effect is only a journaled reason text, not a state edge, but the contract "describes how the last
call ended" is wrong with more than one plan.
**Fix:** return the result from `close_position` (for example a small result object), or key
`_last_result` by plan hash.

### IN-A2: The PROTECTION clearing guard does not require two-read evidence for FLAT from PROTECTED, COMPLETE or TP_UNAVAILABLE

**File:** `src/execution/protection_replay.py:80-82,101-106`; docstring `src/execution/protection.py:100-103`

The module docstring says every FLAT transition needs two consecutive zero reads, and FLAT sweeps
an ACTIVE stop. `_FLAT_NEEDS_EVIDENCE_FROM` lists only UNPROTECTED, PROTECTED_ENTRY_OPEN,
CLOSE_REQUIRED and CLOSE_FAILED. The three live callers (`_attach_take_profits`, `_watch_exit`,
`_on_stop_lost`) do pass the evidence, so nothing is reachable today. The guard and the replay would
accept a future caller, or a journal row, that moves a PROTECTED or COMPLETE plan to FLAT without
the evidence.
**Fix:** add PROTECTED, COMPLETE and TP_UNAVAILABLE to `_FLAT_NEEDS_EVIDENCE_FROM`. This is safe
because all current callers supply it.

### IN-A3: The verdict of the hand-off-failure entry cancel is discarded

**File:** `src/execution/manager.py:1163-1176` and `:1230-1241`

`expire_pending_entry` now returns a `CancelVerdict`, and its docstring says `FILLED_OR_PARTIAL`
means exposure that the coordinator owns. In the two `register_resting_entry` failure paths the
coordinator has just failed to take the plan. The verdict is ignored, so a filled entry gets no
extra signal beyond SAFE_MODE `PROTECTION_HANDOFF_FAILED`, and the reconcile loop that would notice
the unprotected position is not wired until Phase 24.
**Fix:** on `FILLED_OR_PARTIAL` or `STILL_OPEN`, enter a distinct SAFE_MODE reason, or alert, or
journal it, so an operator knows exposure exists that nothing watches.

### IN-A4: The `recheck` position read in `_confirm` has no effect

**File:** `src/execution/protection.py:1824-1825`

`notify_divergence` sets `recheck_requested`, and `_confirm` then calls
`await self._position_is_open(tracked)` and discards the result. The docstring says it "decides
nothing itself", and the path afterwards is unchanged, so a `POSITION_WITHOUT_STOP` divergence
costs one REST call and produces nothing except a possible `PROTECTION_REST_FAILED` row. For
PROTECTED, COMPLETE and TP_UNAVAILABLE plans the flag is cleared at `_step_plan` entry and ignored.
**Fix:** either feed the read into the existing decision (for example, a trusted-ACTIVE stop with a
position of the wrong side or size escalates), or drop the read and document that the notification
only forces the ordinary stop read.

---

_Reviewed: 2026-10-22_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_


# Lane B: reconcile, persistence and migrations

# Phase 20 lane B: Code Review Report (reconcile, persistence, migrations)

**Reviewed:** 2026-10-22
**Depth:** deep
**Files Reviewed:** 17
**Status:** issues_found

## Summary

I read all 17 files in full and followed the call chain loop -> safe_mode / compare / sweeper / local_intent -> coordinator and stores. I also checked the migrations against `src/db/models.py` and the revision chain, and checked the import graph for cycles.

What holds up:
- The loop never calls an exit and never places or cancels a normal order. The sweeper only cancels algo orders.
- Failed truth reads and failed local reads enter SAFE_MODE and skip the compare.
- Exceptions are classified through `adapter.error_facts` and `classify`, never by message text.
- The exit sequence is journal, then store, then memory, and has no await after the `_enter_calls` check.
- The revision chain 0006 -> 0009 is intact. Revision ids are at most 31 characters, so they fit `alembic_version`.
- The ORM models match the migrations for constraints, the partial unique index and nullability. Downgrades mirror upgrades.
- No import cycle exists between `src.reconcile` and `src.execution`.

No BLOCKER found. The seven WARNINGs are operational defects (SAFE_MODE churn and false positives), gaps where the exit check is weaker than the loop's check, and fail-open or stall edges.

Known and deferred items are NOT repeated here:
- The Pass-2 `ENTRY_WITHOUT_PROTECTIVE` for resting entries.
- The persisted SAFE_MODE reason being the last one entered.
- The split between the journal row and the state save on a failed exit.
- Targeted queries having no cap per tick.
- A gate-restricted tick judging no feed.

## Warnings

### WR-B1: Standing multi-reason divergences re-enter SAFE_MODE on every tick (journal and state-version growth, unbounded)

**File:** `src/reconcile/loop.py:727-733` (and `:962`, `:1056-1059`); `src/reconcile/safe_mode.py:444-460`
**Issue:** `_act` enters SAFE_MODE once per distinct reason, in ascending urgency, on every tick. `enter_safe_mode` treats a reason that differs from the stored one as a re-entry, which means:
- a `SAFE_MODE_REENTER` journal row,
- a `PgSystemStateStore.append` (a new append-only `system_state_events` row plus a `SYSTEM_STATE_CHANGED` journal event),
- an `_enter_calls` bump,
- an `on_enter` callback.

The stored reason is always the LAST one entered, so the next tick's FIRST reason differs again. With two standing reasons, each tick does two re-entries, two DB versions and two journal events, forever. `system_state_events` has no delete, and a trigger forbids it.

**Failing scenario:** A foreign order (`FOREIGN_ORDER`) sits on the account and the user-data feed is silent (`STALE_FEED`).
- Each tick `_check_feeds` enters STALE_FEED, which differs from the stored FOREIGN_ORDER and so writes a row.
- `_act` then enters FOREIGN_ORDER, which differs from the stored STALE_FEED and writes another row.
- At a few seconds per tick that is tens of thousands of append-only rows per day. Each reason also fires `on_enter` again, which is held back only by the alert sink's dedupe window.
- The same flip-flop happens with a standing `STREAM_TASK_DIED` plus any compare divergence.

**Fix:** Re-entering a reason that SAFE_MODE has already recorded since the last exit must be a no-op. Either keep a `set` of reasons entered in the current episode inside `SafeModeController`, journal and persist only when a new reason is added, and keep the first or most urgent reason as `entered_reason`. Or have the loop remember the reasons already entered this episode and skip them:
```python
# SafeModeController
self._episode_reasons: set[str] = set()   # cleared on exit
...
if self._in_safe_mode:
    if reason in self._episode_reasons:
        if self._persist_pending:
            self._persist(now_utc=effective_now)
        return
    self._episode_reasons.add(reason)
    ...
```
Persist `episode_reasons` (or at least the first reason) so a restart keeps it.

### WR-B2: A normal TP1 fill puts the system in SAFE_MODE (`UNSYNCED_ALGO`), and the exit stays refused until the plan is FLAT

**File:** `src/reconcile/local_intent.py:246-254` (rule table `:105`); `src/reconcile/compare.py:497-509`
**Issue:** In state COMPLETE the local intent always expects TP1, TP2 and the SL as open algo orders (status NEW). The coordinator has no "TP1 filled" state (`protection.py:2256-2272`, `_watch_exit` keeps COMPLETE until the REST position is flat). `snapshot_open_algo_orders` returns only open algo orders, so a triggered TP1 disappears from the truth. Pass 1 then finds a local algo with no exchange algo, and `has_position` is true, so it takes the non-orphan branch and emits `UNSYNCED_ALGO`.

**Failing scenario:** The profitable path (TP1 fires, TP2 and the SL still rest, the position is still open) triggers SAFE_MODE `UNSYNCED_ALGO` and an alert. New entries are blocked on every symbol. `exit_safe_mode` runs the same compare, which stays dirty while the plan is COMPLETE and the TP1 leg is missing. The operator cannot exit until TP2 or the SL ends the plan, and then has to exit manually. This is fail-closed, but it makes the normal winning trade a SAFE_MODE event. The deferred register lists TP-leg limits (`20-DEFERRED.md`, "Local intent is built from strictly listed states"), but not this case.

**Fix:** The coordinator should expose which legs are expected (or a state/flag for "TP1 consumed"), and `derive_local_intent` should stop emitting TP1 once the position is smaller than the entry quantity and the TP1 leg is not open. Or accept a missing TP leg of a COMPLETE plan with a confirmed stop as an alert-only, non-SAFE_MODE divergence. At minimum, document and test the TP1-fired path explicitly.

### WR-B3: `exit_safe_mode` runs a weaker compare than the loop: the symbol-ownership input (`local_active_plans`) is dropped

**File:** `src/reconcile/safe_mode.py:757-774` (`_read_local_intent`), `:663-680` (`_compare_is_clean`); `LocalIntentLike` at `:119-129`
**Issue:** The loop calls `compare(**local.compare_kwargs(), ...)`, which includes `local_active_plans`. The exit reads only `orders`, `algos` and `positions` from the same `LocalIntent` and calls `self._compare` without `local_active_plans`. Pass 3b (`AMBIGUOUS_POSITION_OWNER` for more than one active plan per symbol, the O-D rule) is therefore never evaluated at exit.

**Failing scenario:**
- Two tracked PROTECTED plans on one symbol, each with a confirmed stop resting, and the exchange position reads flat.
- The loop reports `AMBIGUOUS_POSITION_OWNER` and enters `SYMBOL_OWNERSHIP_CONFLICT`.
- The operator's `exit_safe_mode` compare sees both positions and both stops, no exchange exposure, and no orphan (a local position exists). It reports agreement. SAFE_MODE exits while the conflict is still present, and the next tick re-enters it.
- The effect is narrow because exposure normally produces other divergences, but it contradicts D-15 ("compare v2" on fresh reads) and the O-D decision.

**Fix:** Add `active_plans` to `LocalIntentLike` and `_read_local_intent` (return a 4-tuple), and pass `local_active_plans=` to the compare. Treat a missing `active_plans` attribute as an unreadable source (`LOCAL_SOURCE_UNREADABLE`) for any compare function that accepts it.

### WR-B4: Exit readiness does not require the coordinator's restore to be complete

**File:** `src/reconcile/safe_mode.py:846-877` (`build_exit_readiness`, `_plan_blocks`); `src/execution/protection.py:843-863`
**Issue:** `protections()` returns whatever is tracked, with no `restore_complete` guard. The loop refuses to read a half-restored view as "no plans" (`_restore_complete`, `loop.py:512`). The exit has no such rule, and rows 1-7 do not mention restore.

**Failing scenario:**
- Startup enters SAFE_MODE because `coordinator.restore` raised (`RESTORE_INCONSISTENT`), so `restore_complete` stays False and the tracked set is empty or partial.
- The account is flat and no intents are unresolved. The operator calls `exit_safe_mode`.
- `blocking_plans` is 0, because the CLOSE_REQUIRED or UNPROTECTED plan was never restored. The compare is clean and the exit succeeds.
- `blocks_new_entries()` still returns True (`protection.py:828`), so entries stay blocked, but SAFE_MODE has been declared over with the protection state unrecovered. The loop is still skipping every tick with `RESTORE_PENDING`.

**Fix:** Add a readiness field, for example `restore_complete: bool | None`. `build_exit_readiness` takes a `restore_complete_fn`, and an unreadable or False value refuses with a new code such as `RESTORE_NOT_COMPLETE`. Alternatively, make the `protections_fn` passed in raise while `restore_complete` is False, so the field is `None` and refuses as `READINESS_UNREADABLE`.

### WR-B5: A raising position verifier aborts the whole sweep, loses the report of already-cancelled orphans and leaves an un-awaited coroutine

**File:** `src/reconcile/sweeper.py:210-215` (and `:267`); consumer `src/reconcile/loop.py:1211-1245`
**Issue:**
- `first_read = position_verifier(...)` and `second_read = position_verifier(...)` are both created before either is awaited.
- `_position_amount` in the loop deliberately raises (`TypeError`, or a network error from `snapshot_positions`) so an unreadable position never reads as zero.
- The `await` is outside any `try`. When the first read raises, the exception escapes `sweep()`, and the already-created `second_read` coroutine is never awaited ("coroutine was never awaited").
- The `already_gone` journal write at `:267` is also unguarded.

**Failing scenario:** Orphans [A, B]. A is cancelled and verified. The position read for B fails. `sweep()` raises, and the loop's `_sweep` reports `swept=()` with `action_failures=["sweep"]`. A's cancel is therefore invisible to the report and the tick counters. The sweeper docstring ("NEVER raises on a single cancel failure") is not true for this path. No safety breach, because B is retried next tick, but the audit and report are wrong.

**Fix:** Wrap the verification per orphan:
```python
try:
    first = position_verifier(symbol=symbol)
    first = await first if _is_awaitable(first) else first
    second = position_verifier(symbol=symbol)
    second = await second if _is_awaitable(second) else second
except Exception as exc:
    skipped.append(SweepSkip(symbol, client_algo_id, f"position_read_failed: {type(exc).__name__}"))
    self._record_skip_best_effort(...)
    continue
```
Read sequentially so nothing is left un-awaited. Wrap the `already_gone` journal call in the same best-effort handling.

### WR-B6: A feed timestamp in the future counts as fresh without bound (the stale-feed guard fails open)

**File:** `src/reconcile/feed_freshness.py:101-106`
**Issue:** `now_utc - seen_at_utc > limit` is False for any future `seen_at_utc`. The module comment says the drift bound lives in the pre-placement check, but nothing in the reconcile path bounds the feed time. A source bug (milliseconds treated as seconds, a wrong timezone, or a clock that jumped forward) produces a mark-price or user-data time far in the future. Stale-feed detection is then disabled indefinitely, with no alert.

**Failing scenario:** `FeedSource.read_feed()` returns `user_data_last_event_at_utc` as year 2100 after a unit bug, and the stream is actually dead. `assess_feeds` returns `user_data_silent=False` every tick, and the reconcile loop never enters STALE_FEED.

**Fix:** Treat a time ahead of `now_utc` by more than a small, configured skew as unreadable, hence stale. Reusing the ratified pre-placement drift bound avoids inventing a number. If no key exists, add one under `stale_feed.*` as `NOT_CONFIGURED` and refuse with `ValueError` like the other limits, so the loop's fail-closed branch handles it.

### WR-B7: The background lot-filter refresh runs inside the tick lock with no timeout, so a stalled refresh blocks all later risk-reducing work

**File:** `src/reconcile/loop.py:489-496`, `:526`, `:898-917`
**Issue:** `tick()` holds `self._lock` for the whole `_run`, including `_background`, which awaits `refresh_if_due` once per tracked symbol. The docstring says it "never raises by contract", but nothing bounds how long it takes. A hung REST call or a slow exchangeInfo read makes this tick's lock outlive the cadence. Every later `tick()` returns `TICK_SKIPPED_OVERLAP` at once, so `_risk_reducing_first`, the feed and stream checks, the truth reads and the orphan sweep stop running. That defeats the Q4 ordering, where risk-reducing work comes first and the refresh comes last. With N symbols, even healthy refreshes stretch the tick beyond `tick_interval_ms`. The tick interval is the very quantity that `check_reconcile_cadence` bounds below `max_unprotected_ms` (D-25).

**Failing scenario:** exchangeInfo stalls (no response), or the refresh waits on a rate-limited path. The tick never finishes, and the pending `CLOSE_NOT_SENT` row is never handed to the reducer again until the call returns.

**Fix:** Bound the background phase, for example `await asyncio.wait_for(self._refresh_all(symbols), timeout=...)` with the timeout taken from the limits (a new `NOT_CONFIGURED` key, not an invented number). Journal a timeout as `RECONCILE_ACTION_FAILED`. Or run the refresh outside the lock as its own task, started only when no pending row is open. Equally, give every awaited step a deadline.

## Info

### IN-B1: `UNSYNCED_POSITION` uses the raw symbol where every neighbour uses the sanitised one

**File:** `src/reconcile/compare.py:619-628`
**Issue:** `Divergence(symbol=raw_symbol)` raises `ValueError` if the exchange row has a missing or empty symbol, while the Hedge-mode and bound-check branches just above and below use `symbol_text` (fallback `"UNKNOWN"`). The failure is still fail-closed (the loop treats the compare error as an `API_DEGRADATION` read failure), but it loses all other divergences of that tick and mislabels the cause.
**Fix:** Use `symbol=symbol_text`.

### IN-B2: Stale package docstring and a wall-clock fallback in a "pure" package

**File:** `src/reconcile/__init__.py:13-16`; `src/reconcile/sweeper.py:188-193`; `src/reconcile/safe_mode.py:441`
**Issue:**
- The package docstring still says the package is "stdlib + `src/domain/*` + sibling modules only". `compare.py`, `sweeper.py`, `startup.py` and `loop.py` now import `src.execution.*`; importing `src.reconcile` loads `src.execution.order_ids` and `cancel_verification`. No cycle exists, but the dependency statement is wrong, and `src/execution/protection.py:277-278` states the opposite direction as a rule.
- `OrphanSweeper.sweep` and `enter_safe_mode(now_utc=None)` still fall back to `datetime.now(UTC)`. The loop and startup always inject the clock, and `src/reconcile` is not covered by `WALL_CLOCK_CALLS`. The fallbacks are dead weight on the production path.
**Fix:** Update the docstring. Make `now_utc` required in the production signatures (keep a test-only helper if needed).

### IN-B3: `finalize_reconciled_resolution` and other new store methods do not validate `now_utc` as UTC-aware

**File:** `src/persistence/execution_state.py:373-436`
**Issue:** The sibling stores `pending_actions`, `lot_filters` and `system_state` check `now_utc` with `_require_utc_aware` before the transaction. This method (and the older ones in the file) write `now_utc` straight into `TIMESTAMPTZ` columns. A naive datetime would be interpreted in the session time zone.
**Fix:** Add the same guard before opening the transaction. Consistency only; the callers inject UTC.

---

_Reviewed: 2026-10-22_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_


# Lane C: ops and the REST gate

# Phase 20 lane C: Code Review Report

**Reviewed:** 2026-10-22
**Depth:** deep (Phase 20 diff `567dd8af..HEAD`, traced into `src/reconcile/startup.py`, `src/execution/protection.py`, `src/execution/manager.py`, `src/adapters/binance_userdata_supervisor.py`, `src/reconcile/loop.py`, `src/adapters/telegram_notify.py`, tenacity)
**Files Reviewed:** 7
**Status:** issues_found

## Summary

The gate state store, the spill, the journal-first sink and the act-first helpers are carefully built: atomic
writes, class-name-only messages, no wall clock in the gate, store or spill, and no exception text classification. I found
one fail-open path (an unreadable spill reads as an empty spill at startup) and several robustness gaps
around restart recovery of the REST gate, cancellation inside the Telegram retry, and the ordering of
synchronous journal writes before a risk-reducing action. Every finding below was confirmed by reading the
cited lines (and by running the two parser crashes in CR/WR-C1).

Checked and found sound: no lock-order inversion between `_restore_lock`, `_save_lock` and `_lock`; `check()` cannot
pass before `restore()` has produced a verdict; `restore()` merges a pre-restore `record()` correctly; the
bot token is never logged or placed in an exception (`TelegramFailure.detail` is a class name); the spill
file name is built only from a validated event id (no traversal).

## Critical Issues

### CR-C1: `LocalSpill.scan()` turns an unreadable spill directory into "nothing pending" at startup (fail-open)

**File:** `src/ops/spill.py:238-243`, consumed at `src/reconcile/startup.py:167-179` and `:255-260`
**Issue:** `scan()` catches every `OSError` from `os.listdir` and returns `SpillScan(records=(), corrupt=())`.
`_scan_spill` in startup was written to treat an exception from `scan()` as "unreadable, proves nothing"
(`readable=False`, then `SAFE_MODE_RESTORE_INCONSISTENT`, and `spill_rows_for` returns `None`), but that
branch can never fire for an I/O fault because `scan()` already swallowed it. `PermissionError`, an I/O error,
an unmounted or removed spill volume (the constructor re-creates an empty directory, so a missing volume
looks like a fresh empty one) all read as `readable=True`, `spill_ok=True`, `spilled=()`.
**Failing scenario:** the journal was down during an emergency close; `act_then_record`/`record_after` put the
`pre_send` EMERGENCY_CLOSE row only in the spill. The process restarts with the spill directory unreadable
(permission change, EIO, volume not mounted). Startup step 3 passes, `_close_events_by_plan` sees no
spilled close attempt, `closer.restore_pending` is never told about the in-flight attempt, and no SAFE_MODE is
entered. The docstring even says "a missing or empty spill proves nothing (D-30)", yet the caller is told
"empty and healthy".
**Fix:** only a `FileNotFoundError` may be an empty scan; everything else must propagate (or be reported in
`SpillScan`).
```python
try:
    names = sorted(os.listdir(self._directory))
except FileNotFoundError:
    return SpillScan(records=(), corrupt=())
# any other OSError propagates; startup._scan_spill already maps an exception to SAFE_MODE
```
Better still, add a `unreadable: bool` field so `replay_spill` cannot return `is_clean` for a directory it could not read.

## Warnings

### WR-C1: `decode_record` lets `OverflowError` and `RecursionError` escape; the operator CLI cannot read or clear such a file

**File:** `src/ops/rest_gate_state.py:70-81` and `:99-102`; `src/ops/rest_gate_cli.py:93-98`, `:138-144`; `src/ops/rest_gate_state.py:165-178`
**Issue:** `_parse_time` calls `parsed.astimezone(UTC)` outside the `try`. A timestamp such as
`"9999-12-31T23:59:59-05:00"` raises `OverflowError` (verified by running `decode_record`), and
`json.loads(b"[" * 200000)` raises `RecursionError` (verified). Neither is `GateStateCorrupt`, `ValueError` or `OSError`.
Consequences: (1) `load()` does not set the file aside; (2) `inspect()` raises; (3) `status_report` and `clear_state`
catch only `OSError`, so both crash with a traceback and `clear` never reaches `reinitialize`. The documented
remedy for a corrupt file ("`clear` writes a valid record") is unusable for exactly these files.
**Failing scenario:** a bit-flip or hand edit turns one timestamp into year 9999 with a negative offset. Every
start is `GATE_STATE_UNKNOWN`; `python -m src.ops.rest_gate_cli clear ...` dies with `OverflowError`.
**Fix:** wrap the whole decode: in `_parse_time` catch `(ValueError, OverflowError)` around both `fromisoformat` and `astimezone`; in
`decode_record` catch `RecursionError` next to `ValueError`; and in the CLI treat any unexpected `Exception` from `inspect()` as corrupt for `clear`.

### WR-C2: A failed gate save is never retried, so the file stays stale for the whole ban

**File:** `src/adapters/binance_ratelimit_gate.py:444-473` (callers `:332-333`, `:430-431`)
**Issue:** `_persist()` runs only when an end time changes. If `store.save` fails (Windows `PermissionError` past the
bounded replace retry, disk full), `_save_failed=True` and nothing retries it. The in-memory ban is enforced, but
the file still holds the previous record (no deadline) until another 418/429 extends the deadline.
**Failing scenario:** a 418 arrives, the save loses a race with an antivirus scan, `PERSISTENCE_FAILED`. The
process is restarted (deploy or crash) 10 minutes later during the ban: `restore()` reads a valid record with no
deadline, status `RESTORED_DURABLE`, and REST is sent into an active ban, which extends it.
**Fix:** retry the save from a cheap hook while `_save_failed` is set (for example at the top of `check()`/`restriction()`, rate limited by
the injected clock, or a public `flush()` the runtime calls on its tick) and keep `recovery_status()` at `PERSISTENCE_FAILED` until it succeeds.

### WR-C3: `restore()` adopts any persisted deadline, however far in the future; the user-data supervisor then sleeps for it

**File:** `src/adapters/binance_ratelimit_gate.py:415-423`; consumer `src/adapters/binance_userdata_supervisor.py:652-662`
**Issue:** a deadline that the policy could never have produced (greater than `recorded_at_utc` plus the largest of
`retry_after_cap_seconds`, `no_retry_after_wait_418_seconds`, `no_retry_after_wait_429_seconds`) is adopted as is. Host clock skew when the
record was written, or a corrupted year, gives a multi-day or multi-year restriction. For a pause (reason
`RATE_LIMIT_PAUSE_429`) `_await_rest_allowed` does `await self._sleep(remaining)` for the whole value, parking the recovery
for that long; a ban halts recovery and only the CLI `clear --force` lifts it.
**Fix:** in `restore()`, treat a record with `ban_until_utc` or `pause_until_utc` beyond `recorded_at_utc + max_wait` (plus a small skew allowance) as untrusted: set `_unknown_state`
and alert `REST_GATE_RECOVERY_REQUIRED` (fail closed, operator clears). Also cap the supervisor sleep (for example `min(remaining, 60)` and re-check).

### WR-C4: `GATE_STATE_UNKNOWN` is permanent in process but the user-data supervisor waits on it as if it were a pause

**File:** `src/adapters/binance_ratelimit_gate.py:285-288`, `:344-346`; consumer `src/adapters/binance_userdata_supervisor.py:652-662`, `:674-684`
**Issue:** `_unknown_state` is never cleared in process (only a restart reads a valid record). `restriction()` reports it with
`reason=GATE_STATE_UNKNOWN`, `remaining_seconds=1`. `_await_rest_allowed` halts only for `IP_BAN_418`; any other reason sleeps
`remaining` and loops. `_gated` has no bound and the `_bounded` retry budget counts attempts, not waits inside one, so the recovery spins
every second forever, writes an INFO log line per second, never calls `on_failure`, and the stream stays UNKNOWN with no operator-facing reason.
**Fix:** treat `GATE_STATE_UNKNOWN` like a ban in `_await_rest_allowed` (`raise _RecoveryHalted(GATE_STATE_UNKNOWN)`), so the halt is reported once through `on_failure`
and the recovery waits for `request_resync()`. Keep `GATE_NOT_RESTORED` as the transient wait but bound it.

### WR-C5: tenacity swallows `CancelledError` inside `_send_bounded`; cancellation of `drain()` is delayed or lost

**File:** `src/ops/alerts.py:499-509`, `:556-565` (and the dead handler at `:624-626`)
**Issue:** `with attempt:` is tenacity's `AttemptManager`, whose `__exit__` catches `BaseException`, stores it and returns True
(verified in the installed tenacity). `_is_retryable(CancelledError)` returns True (it is not ValueError/KeyError/TypeError/TelegramSendError), so the
retry loop sleeps and sends again. A `task.cancel()` or `asyncio.timeout` around `drain()` during shutdown is therefore ignored for up to `NOTIFY_MAX_DELAY_SECONDS`
(30 s) and, if a later attempt succeeds, is swallowed entirely and `drain` returns normally. The `except BaseException: appendleft` in `drain` only sees the cancellation when
the budget ends. The same shape was copied from `src/paper/shadow.py`.
**Fix:**
```python
def _is_retryable(exc: BaseException) -> bool:
    if not isinstance(exc, Exception):   # CancelledError, KeyboardInterrupt, SystemExit
        return False
    ...
```
With `reraise=True` tenacity then re-raises the cancellation at once.

### WR-C6: A CRITICAL alert whose send failed is never re-queued in process, and the dedupe window then suppresses its repeats

**File:** `src/ops/alerts.py:616-654` (drain) with `:390-408` (suppression)
**Issue:** `drain` pops the alert, and on failure only journals `ALERT_SEND_FAILED`; the alert is not queued again. Only
`requeue_undelivered` (restart) re-queues. Meanwhile a repeat of the same `(event, subject, reason)` inside
`alerts.dedupe_window_ms` is not queued, only journaled as `ALERT_SUPPRESSED`.
**Failing scenario:** Telegram is unreachable for 40 s while `UNPROTECTED_POSITION` fires. The first message fails its 3 attempts / 30 s budget and is dropped; every
repeat within the window is suppressed; the producers (coordinator "once per plan", reconcile tick) may not alert again. The operator hears nothing about an
unprotected position until a restart or until the window ends and a producer happens to re-alert.
**Fix:** on a non-permanent failure, re-append the alert to the queue with a bounded redelivery count (and a not-before time), or make the sink consult the delivery state:
do not suppress a repeat while the episode's first alert has no `ALERT_DELIVERED` outcome.

### WR-C7: `act_then_record` does a blocking fsync write-ahead before the risk-reducing action

**File:** `src/ops/risk_first.py:114-116`
**Issue:** the module promises "risk-reducing controls never wait for the journal", but the write-ahead `spill.write(event)` runs synchronously on the event loop before
`await action()`: open, write, `os.fsync`, `replace_with_retry` (which `time.sleep(0.1)` up to 5 times on a Windows `PermissionError`, so up to 0.4 s), and no timeout. A stalled disk
or an antivirus lock delays the cancel of a stale entry (or any caller that adopts this helper) by the stall, and blocks every other coroutine meanwhile.
**Fix:** start the action first and do the write-ahead concurrently, for example `spill_task = asyncio.to_thread(_try_spill, ...)` awaited together with the action; or bound the
write-ahead with a short timeout and fall back to the journal-after path. At minimum run it via `to_thread` so the loop is not blocked.

### WR-C8: Journal-first alerts are written synchronously before the emergency close; a journal outage delays the close

**File:** `src/ops/alerts.py:410-413` (via `record_after` -> `journal.record`), call sites `src/execution/protection.py:2306-2321` (before `_attempt_close` at `:2323`)
**Issue:** `_enter_close_required` calls `self._alerts.critical(...)` (twice for B5) and only then awaits `_attempt_close`. `JournalFirstAlertSink.alert` calls the blocking
`journal.record` first. With the database down this costs the connect timeout (`DEFAULT_CONNECT_TIMEOUT_S = 3`) or pool/statement timeouts (5 s, 10 s) per alert, on the event loop, plus the spill fsync,
before the position is closed. This contradicts D-16 for the most important risk-reducing action.
**Fix:** for the CRITICAL paths either send `critical()` after `_attempt_close` has been awaited, or make the sink queue first and journal off-loop (`asyncio.to_thread`) with the journal row
still written before the Telegram send (journal-first applies to the send, not to the close).

### WR-C9: The gate state file write has no directory fsync; the record can roll back after a power loss

**File:** `src/ops/rest_gate_state.py:147-156` (compare `src/ops/spill.py:288-301`, which does fsync the directory)
**Issue:** `_write_atomic` fsyncs the temp file but not the parent directory after `os.replace`. On POSIX a power loss shortly after a 418 can leave the old directory entry (the
record without the ban). The spill, written in the same phase, does the directory fsync; the gate store, whose whole purpose is surviving a restart, does not.
`initialize()` also checks `exists()` and then writes with no exclusive create, so two concurrent bootstraps can overwrite each other.
**Fix:** after `replace_with_retry`, fsync the directory (same best-effort helper as the spill, a no-op on Windows). For `initialize()` use `os.open(..., O_CREAT | O_EXCL)` on the final name or `os.link` of the temp file.

### WR-C10: `clear --reason` (and `--force`) is not durably recorded

**File:** `src/ops/rest_gate_cli.py:147`, `:166-172`; `src/ops/rest_gate_state.py:208-232`
**Issue:** the free-text `--reason` and the `forced` flag only go to `structlog` calls. The CLI never configures structlog, so they reach whatever the default console renderer prints, and
nothing lands in the state file, in a journal row or in a file next to it. Only `initialized_by` (the operator id) is persisted. A `--force` that overrode a real future ban leaves no durable reason.
**Fix:** write a small sidecar next to the aside file (or an `audit` line appended to a file in the same directory, fsynced) holding operator id, reason, forced flag, the overridden deadlines and `now_utc`; or journal a row when the
database is reachable.

## Info

### IN-C1: `_CLASS_NAME_RE` lets a 64-character alphanumeric secret through as a "reason"

**File:** `src/ops/alerts.py:122`, `:128-129`
**Issue:** `[A-Z][A-Za-z0-9]{0,63}` matches any capitalised alphanumeric token up to 64 characters, which is exactly the shape and length of a Binance API key or secret that starts with an upper-case letter. The module header says
redaction is not relied on, but the guarantee is only "looks like a code or class name". No current caller passes such a value.
**Fix:** require a class-name shape that Python can produce (`[A-Z][a-z0-9]+([A-Z][a-z0-9]*)*`, max 40) or resolve the name against `builtins`/an allow-list of known exception classes.

### IN-C2: The sink and the sender share a queue only by convention

**File:** `src/ops/alerts.py:353-368`, `:599-614`
**Issue:** `JournalFirstAlertSink` creates its own `deque` when none is given and `TelegramAlertSender` requires one. Composing `TelegramAlertSender(queue=deque())` (a separate deque) compiles and runs and every alert is journaled but never sent.
The deque is also unbounded.
**Fix:** construct the sender from the sink (`TelegramAlertSender(sink=...)` reading `sink.queue`) or assert `sender._queue is sink.queue` in the composition test and give the deque a `maxlen` with a journaled overflow row.

### IN-C3: Spill file hygiene

**File:** `src/ops/spill.py:196`, `:216-231`, `:44`
**Issue:** (a) `mkdir(mode=0o700, exist_ok=True)` does not tighten an existing directory and the files are created with the default umask; (b) the event-id pattern allows names such as `CON` or `aux`, which are Windows
device names even with the `.json` suffix, and ids differing only by case collide on case-insensitive filesystems (ids are normally `prefix_<hex>` so this is theoretical); (c) there is no cap on the number of spilled files while the journal stays down.
**Fix:** `os.chmod` the directory and `os.open(..., 0o600)` for the temp file; reject Windows reserved stems in `is_valid_event_id`; raise or alert past a file-count threshold.

### IN-C4: Manual-close drill reports `OUTCOME_SAFE_MODE_ENTERED` without asserting a flat position

**File:** `src/ops/drills.py:875-882`
**Issue:** when `diff.orphan_protectives` is empty the drill returns `OUTCOME_SAFE_MODE_ENTERED` after checking only that nothing was swept. It never asserts that `truth["positions"]` is flat, so a
fake exchange where the close did nothing and the stop stayed passes the drill, which documents itself as rehearsing both answers of G4-035.
**Fix:** assert `all(position amount == 0 for position in truth["positions"])` on that branch (or return a distinct outcome for "position still open").

### IN-C5: `ALERT_DELIVERED` / `ALERT_SEND_FAILED` rows carry the alert's time, not the delivery time

**File:** `src/ops/alerts.py:629-649`
**Issue:** `_outcome_event` is given `occurred_at_utc=alert.occurred_at_utc`, so the journal cannot show when delivery happened or how long it was delayed, and the content-hash id of a repeated failure with the same
attempts/kind is identical (idempotent, but then a second failure series is invisible). The sender has no injected clock, which is why.
**Fix:** inject a `clock: Callable[[], datetime]` into `TelegramAlertSender` and use it for the outcome rows (keep the alert id as `entity_id`).

---

_Reviewed: 2026-10-22_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
