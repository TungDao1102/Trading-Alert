---
phase: 20-reconcile-safe-mode-hardening
fixed_at: 2026-10-25
review_path: .planning/phases/20-reconcile-safe-mode-hardening/20-REVIEW.md
iteration: 1
findings_in_scope: 7
fixed: 6
skipped: 0
needs_owner: 1
status: partial
---

# Phase 20: Code Review Fix Report (deferred emergency-close and reduce-risk findings)

**Fixed at:** 2026-10-25
**Source review:** `.planning/phases/20-reconcile-safe-mode-hardening/20-REVIEW.md` (findings deferred by `20-DEFERRED.md`, section "Review findings not fixed in Phase 20")
**Requested by:** the owner, 2026-10-25, before any live use
**Branch:** `develop`, edited in the main checkout (no worktree, as instructed)

Evidence in this report is executed tests with fakes, a real `LocalSpill` in a temporary directory and a local PostgreSQL (`TEST_DATABASE_URL` set, `TRADING_CI_STRICT=1`). Nothing here is `[DEMO]`, and nothing claims that live execution is safe or ready. Every fix was written test-first: the new tests were seen failing against the old code for the reason the finding gives, then passing.

**Summary:**
- Findings in scope: 7 (WR-C8, WR-C7, WR-A4, WR-B5, WR-C5, WR-C6, WR-C10)
- Fixed: 6 (WR-C8, WR-C7, WR-A4, WR-B5, WR-C5, WR-C10)
- Skipped (review claim wrong): 0
- Needs owner: 1 (WR-C6)

## Fixed Issues

### WR-C8: Journal-first alerts are written before the emergency close

**Files modified:** `src/execution/protection.py`, `tests/test_protection_close_first.py` (new), `tests/test_protection_branches.py`, `tests/test_protection_stop_lost.py`
**Commit:** `e222cdbc`
**Verified against the code first:** true. `_enter_close_required` flipped the state (its `_transition` wrote a journal row), wrote the B1 note, called `enter_safe_mode` (a journal write plus a state save) and `critical()` once or twice (each a journal write through `JournalFirstAlertSink`), all synchronous, and only then awaited `_attempt_close`.
**Applied fix:**
- The plan state flips in memory first (`blocks_new_entries()` is True from that moment, so new entries fail closed). The journal rows that this stretch would write (the CLOSE_REQUIRED transition and, for B1, the accepted-knowingly note) are parked by a list the stretch sets and clears with no `await` inside, so no other coroutine can park into it.
- `_attempt_close` takes an `after_close` hook that runs exactly once, as soon as the closer has answered or raised, before any row of that attempt (so the journal keeps its order: CLOSE_REQUIRED row, then CLOSE_FAILED row). The hook writes the parked rows, enters SAFE_MODE `CLOSE_REQUIRED` and raises the critical alert(s), each in its own guard, so one failing never skips the others or the close.
- The journal/SAFE_MODE/alert failure is recorded after the close and never stops it.
**Tests:** `tests/test_protection_close_first.py`: `test_the_close_goes_out_before_the_journal_safe_mode_and_alert` (the close is the first event; at close time the plan is CLOSE_REQUIRED and `blocks_new_entries()` is True), `test_the_b5_branch_closes_first_and_still_raises_both_alerts`, `test_a_failing_journal_safe_mode_and_alert_sink_never_stop_the_close` (every collaborator raises: one close, state `CLOSE_FAILED`, entries blocked), `test_an_exception_from_the_closer_still_records_safe_mode_and_the_alert`.
**Changed existing tests (order only, no behavior lost):** `test_branch_q4_refused_stop_...` now expects the closer's own alert `EMERGENCY_CLOSE_NOT_SENT` before the coordinator's `CLOSE_REQUIRED` (time order); `test_wr04_stop_lost_position_unreadable_throughout...` checks `"CLOSE_REQUIRED" in entered_reasons` instead of position 0 (the closer's `EMERGENCY_CLOSE_FAILED` can now enter first, and the persisted SAFE_MODE reason is the last one entered).
**Status:** fixed: requires human verification (a reordering of side effects around the most important risk-reducing action).
**Residual, not changed (see "For the owner"):**
- The real `MarketEmergencyCloser._send_part` still writes its own `pre_send` record (spill, then `journal.record`) before the MARKET send. That is the D-16 / plan 20-19 crash-recovery write-ahead of the closer itself, not an alert, and it is outside WR-C8's cited lines. A slow database can still delay the send by that one journal call.
- `_close_pending_for_transition` (a pending-store write that supersedes a queued stop) still runs in the in-memory stretch before the close.
- The sync journal calls after the close still block the event loop for their own timeout; they no longer sit in front of the close.
- A process kill between the in-memory flip and the close answer loses the parked CLOSE_REQUIRED row; the restart rebuilds from Binance truth and the closer's own `pre_send` record.

### WR-C7: `act_then_record` does a blocking fsync write-ahead before the risk-reducing action

**Files modified:** `src/ops/risk_first.py`, `tests/test_risk_first_write_ahead.py` (new), `tests/test_risk_first_spill.py`
**Commit:** `d413f66d`
**Verified against the code first:** true. `_try_spill(spill, event)` (open, write, `os.fsync`, `replace_with_retry` with its Windows sleeps, directory fsync) ran synchronously on the loop before `await action()`. Its only production caller is `_cancel_then_audit` in `src/execution/manager.py` (the entry and protective cancels, the manual controls).
**Applied fix (the review's "start the action first and do the write-ahead concurrently ... at minimum `to_thread`"):** the write-ahead starts in a worker thread (`run_in_executor`) and the action runs beside it; the action never waits for the spill disk and no other coroutine is frozen. After the action: if the journal took the record, the spill file is discarded as soon as its write has finished (a done-callback if it is still running), without waiting; only when the journal failed does the call wait for the write (after the action has ended, also when the action raised), because that file is then the one remaining record and decides whether `AuditRecordLost` is raised. In that double fault (journal down AND a stalled spill disk) the return is delayed, so a following leg of `cancel_untriggered_protectives` would start late; the action itself never waits. An action exception is preserved exactly as before. No timeout and no new number were added.
**Tests:** `tests/test_risk_first_write_ahead.py` (a spill whose `write` blocks until released): the action runs and the call returns while the write is stalled, the write runs off the loop thread, the finished write is discarded afterwards; the loop keeps ticking during the stall; journal down: the action still runs first and only the settling waits, the file is kept (also for a raising action); journal and spill both failing raises `AuditRecordLost`; a raising action is not held. `tests/test_risk_first_spill.py`: the old test "writes the spill before the action" now asserts the new contract (spilled beside the action, journaled once, cleared).
**Status:** fixed: requires human verification. The strict "file exists before the action starts" ordering is gone on purpose: with a healthy disk the write lands in milliseconds, but a crash in that window loses the write-ahead copy.

### WR-A4: The coordinator's FLAT sweep omits `spill`

**Files modified:** `src/execution/protection.py`, `tests/test_protection_sweep_spill.py` (new)
**Commit:** `5693421b`
**Verified against the code first:** true. `_sweep` called `cancel_untriggered_protectives(...)` with no `spill`, while `self._spill` is held by the coordinator.
**Applied fix:** `spill=self._spill` is passed (typed `IntentSpill`, the runtime object is a `LocalSpill`; one `# type: ignore[arg-type]` with a comment, like the adapter argument beside it).
**Test:** `test_the_flat_sweep_spills_its_audit_rows_and_finishes_while_the_journal_is_down`: journal down at FLAT, three cancels, six spilled rows (pre and post image of each leg), and later steps do not cancel again (the sweep is done). Seen failing before: no spill file was written.
**Not done:** the review's optional "record a verdict-only success so a lost audit row does not block `sweep_done`". It needs `cancel_untriggered_protectives` to return verdicts together with a lost-audit error (a changed return contract). With the journal down and the spill also failing the sweep still repeats each step (idempotent, fail closed).

### WR-B5: A raising position verifier aborts the whole sweep

**Files modified:** `src/reconcile/sweeper.py`, `tests/test_sweeper_verifier_failure.py` (new)
**Commit:** `3fceff63`
**Verified against the code first:** true (both verifier calls created before either was awaited, awaited outside any `try`; the `already_gone` row unguarded).
**Applied fix:** the two reads run one after the other inside a per-orphan `try`; on an exception that orphan is skipped with reason `position_read_failed: <ExceptionClass>` (class name only) and a best-effort `SWEEP_SKIPPED` row, and the sweep continues; the `already_gone` row goes through `_record_failure_best_effort`.
**Tests:** a failing first read keeps the already-cancelled orphan A in the report and skips B without a cancel; a failing async verifier is called once and leaves no un-awaited coroutine (warnings are errors); a failing second read; a failing `already_gone` row does not end the sweep.
**Status:** fixed.

### WR-C5: tenacity swallows `CancelledError` inside `_send_bounded`

**Files modified:** `src/ops/alerts.py`, `tests/test_alerts_cancellation.py` (new)
**Commit:** `230208df`
**Verified against the code first:** true (`_is_retryable(CancelledError)` returned True; the installed tenacity attempt manager stores any `BaseException`).
**Applied fix:** `_is_retryable` returns False for anything that is not an `Exception` (the review's fix, verbatim). `drain()` re-raises the cancellation at once and puts the alert back at the head of the queue.
**Tests:** a cancellation during the send is attempted once, with no backoff sleep, the alert stays queued; the cancellation is not swallowed by a would-be-successful retry; only ordinary exceptions are retryable.
**Status:** fixed.

### WR-C10: `clear --reason` (and `--force`) is not durably recorded

**Files modified:** `src/ops/rest_gate_cli.py`, `src/ops/rest_gate_state.py`, `docs/operations/RUNBOOK.md` (section 21.3), `tests/test_rest_gate_clear_audit.py` (new), `tests/test_rest_gate_cli.py` (two directory-listing assertions now allow the sidecar)
**Commit:** `b6bfb3d9`
**Verified against the code first:** true at HEAD before this change (`rest_gate_cli.clear_state` passed `reason` and `forced` only to `log.info`; see "WR-C10 resolution").
**Applied fix (the review's sidecar option):** before anything changes, `clear_state` appends one fsynced JSON line to `<state file>.clear-audit.jsonl` (operator id, reason, forced flag, overridden deadlines, previous state `valid`/`corrupt`/`missing`, `now_utc`, outcome `requested`) and a closing line (`cleared` or `failed`) afterwards, best effort. If the first line cannot be written the clear is refused with exit 4 and nothing is changed. A refused clear (future deadline without `--force`, empty operator id or reason) writes nothing. No new key, no number, no migration.
**Tests:** forced clear over a real ban records who, why and the overridden deadline; unforced clears append; refused clears write nothing; an unwritable audit line changes nothing; a failed state write leaves `requested` and `failed`.
**Status:** fixed.

## Needs owner (not done)

### WR-C6: A CRITICAL alert whose send failed is never re-queued in process

**File:** `src/ops/alerts.py:616-654` (drain) with `:390-408` (suppression)
**Why not done:** the review offers two fixes and both need a decision.
1. Re-queue on a non-permanent failure "with a bounded redelivery count (and a not-before time)": the count and the not-before delay are new numbers (the `alerts.*` keys are owner-set; a hard-coded value would be a new default). Unbounded re-queue would instead repeat `ALERT_SEND_FAILED` rows for as long as Telegram is down, or forever for a permanent misconfiguration (a wrong chat id), and the retry cadence depends on how Phase 24 schedules `drain()`.
2. "Do not suppress a repeat while the episode's first alert has no `ALERT_DELIVERED` outcome": the sink and the sender share only a deque (IN-C2), so this needs a new channel from the sender back to the sink and a change to the Phase 24 composition. And the producers (coordinator "once per plan", reconcile tick) may never repeat, so it does not by itself tell the operator.
**Owner choice needed:** (a) the redelivery bound and delay (or "retry on every drain, no bound, permanent failures excluded"), and (b) whether to wire sender-to-sink delivery state in Phase 24. Until then `requeue_undelivered` at restart is the only recovery.

## WR-C10 resolution (the documents' contradiction)

The task said `20-29-SUMMARY.md` mentions WR-C10 as fixed while `20-DEFERRED.md` lists it as not fixed. Read against the sources: **`20-29-SUMMARY.md` does not say that.** Its section "Not done and known limits" says "Not touched: WR-C3 ..., WR-C10 (`clear --reason` not durable) ..." (line 86), and `20-DEFERRED.md` lists WR-C10 as not fixed (row `WR-C10`, receiving phase "Phase 23 / 24 (operator surface)"). No Phase 20 document claims WR-C10 fixed; `grep` over `.planning/` finds no other mention. The documents were consistent with each other and with the code: at `HEAD` before this change `src/ops/rest_gate_cli.py::clear_state` recorded `reason` and `forced` only through `structlog` calls, and nothing durable existed (the same plan 20-29 did fix WR-C1, WR-C2 and WR-C9 in `rest_gate_cli.py` and `rest_gate_state.py` (commit `c9810cd2`), which is the likely source of the mix-up). So there was no wrong document and the code was truly unfixed. It was small, specified by the review and needs no number, so it is fixed here (above) and the `20-DEFERRED.md` row is updated.

## For the owner

- **WR-C6** needs your choice (above).
- **Closer pre_send journal write.** `MarketEmergencyCloser._send_part` journals `pre_send` (spill first, then a synchronous `journal.record`) before the MARKET send. With a dead database the send can still wait for the database timeout. It is the closer's own D-16 write-ahead (plan 20-19), not an alert, and was not among the cited findings; making the journal half of it post-send is possible but changes the recorded evidence order. Say if you want it.
- **`src/paper/shadow.py::_is_retryable`** has the same WR-C5 shape (a copy). It is the paper path, outside this request; a one-line change if wanted.
- No migration is needed (head stays 0012), no `params/**/*.toml` was edited, no new `NOT_CONFIGURED` key, no number, no `float(`, and no wall clock in a pure module.
- Order change visible to an operator: when a close fails, the closer's own alert and SAFE_MODE reason (`EMERGENCY_CLOSE_...`) now come before the coordinator's `CLOSE_REQUIRED` ones, and `CLOSE_REQUIRED` is the last reason entered (so it is the persisted SAFE_MODE reason). Both rows are journaled.

## Verification

Run in the main checkout of `develop` (not a worktree), so the numbers are reproducible from this tree. `TRADING_CI_STRICT=1`, `TEST_DATABASE_URL` set in the process environment (not echoed), `-p no:xdist -o addopts=""`:

- Touched and neighbouring files plus the Phase 19, 20, 21 and 22 gates and `test_agents_md.py`: 742 passed, 0 failed.
- A wider run of 108 test files that import the touched modules (risk_first, sweeper, protection, alerts, rest gate, enablement, emergency close): 5300 passed, 6 skipped, 1 failed. The failure was a real race in my first WR-C7 version (a raising action with the journal down returned before the write-ahead reached the disk; `test_a_failing_cancel_is_still_recorded_as_cancel_failed_and_reraised`). Fixed in the same commit series (see the follow-up commit): the settling now waits whenever the journal failed. After the fix the 14 spill test files (408 tests) passed three times in a row.
- `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src` (253 files) clean; `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- The full suite was not run (the orchestrator's job).

---

_Fixed: 2026-10-25_
_Fixer: Claude (gsd-code-fixer, Claude Sonnet 5.5)_
_Iteration: 1_
