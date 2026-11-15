---
phase: 24-live-runtime-composition-demo
reviewed: 2026-11-07T00:00:00Z
depth: deep
files_reviewed: 52
files_reviewed_list:
  - config/execution/execution-limits-v1.toml
  - deploy/backup-drill.sh
  - deploy/backup-real-s3-gate.sh
  - deploy/backup.sh
  - deploy/compose-rehearsal.sh
  - deploy/compose-soak.sh
  - deploy/heartbeat.sh
  - deploy/lib.sh
  - deploy/soak-image.sh
  - deploy/update.sh
  - deploy/systemd/trading-live-heartbeat.service
  - deploy/systemd/trading-live-heartbeat.timer
  - deploy/systemd/trading-soak-backup.service
  - docker-compose.yml
  - src/adapters/code_version.py
  - src/adapters/telegram_callbacks.py
  - src/db/alembic/versions/0015_order_event_time.py
  - src/domain/exchange_errors.py
  - src/execution/approval_desk.py
  - src/execution/intent_recovery.py
  - src/execution/live_context.py
  - src/execution/manager.py
  - src/execution/protection.py
  - src/live/alerts.py
  - src/live/approval_sender.py
  - src/live/commission.py
  - src/live/config.py
  - src/live/enablement.py
  - src/live/exchange.py
  - src/live/execution_service.py
  - src/live/feeds.py
  - src/live/health.py
  - src/live/operator.py
  - src/live/order_index.py
  - src/live/reconcile.py
  - src/live/reservation_release.py
  - src/live/risk_inputs.py
  - src/live/runtime.py
  - src/live/scheduled_cancel.py
  - src/live/scheduler.py
  - src/live/signal_source.py
  - src/live/smoke_injection.py
  - src/live/startup.py
  - src/live/stream.py
  - src/live/stream_persistence.py
  - src/live/telegram_runner.py
  - src/live/wiring.py
  - src/live/wiring_parts.py
  - src/ops/health.py
  - src/ops/store_executor.py
  - src/persistence/execution_state.py
  - src/persistence/risk_reservations.py
  - src/persistence/shadow_stores.py
  - src/reconcile/safe_mode.py
  - src/reconcile/sweeper.py
findings:
  critical: 1
  warning: 5
  info: 5
  total: 11
status: issues_found
---

# Phase 24: Code Review Report

**Reviewed:** 2026-11-07
**Depth:** deep (cross-file tracing of the start sequence, the placement path, SAFE_MODE, the Telegram gates, the reservation lifecycle and the deploy scripts)
**Files Reviewed:** 52 (read in full or in the parts that carry the money-risk paths; see the coverage note)
**Status:** issues_found

## Summary

The composition is careful. The start order is as documented (STREAM before RECONCILE; no handler runs before RECOVERY; ENABLE only in DEMO, only after a clean start). A placement has one `place_entry` POST per approval, `sdk_retries = 0`, an ambiguous result is probed once and ends UNKNOWN plus SAFE_MODE, and the same-approval replay is arbitrated by the database insert, not by memory. Both Telegram gates (authorized chat, then private chat plus user allow-list) are applied to the callback handler, to every operator command and to `/demo_signal`. The raw APPROVE token is memory only. The deploy scripts keep the ping URL out of argv, logs and the environment (stdin config for curl, 0600 files, xtrace refusal, strict URL allow-list). The compose env split holds (the `live` service replaces the shared `env_file`).

One defect is a blocker: the live process builds its database engine without the bounded timeouts every on-loop store call in the placement and protection path is documented to rely on. The warnings are an operational dead-end after an interrupted first install, a cross-mode expiry of DEMO approvals by the SHADOW runtime, reservation rows that never advance to PLACED/OPEN, resting entries left on the exchange at shutdown, and synchronous store work on the event loop in the operator path.

Coverage note: the large adapter files (`binance_usdm.py`, `binance_probe.py`, `binance_public.py`, `binance_userdata.py`, `binance_ratelimit_gate.py`), `confirm_core.py`, `confirm_flow.py`, `src/db/models.py`, `entities.py`, `approvals.py`, `src/ops/alerts.py`, the `scripts/` files and `src/paper/*` were checked only by targeted search (retry settings, error classification, call sites, diffs), not read line by line.

## Critical Issues

### CR-01: The live engine has no connect, lock, statement or UTC bounds, while the placement and protection paths call the store synchronously on the event loop

**File:** `src/live/runtime.py:483` (consumers: `src/execution/manager.py:686-695`, `src/execution/protection.py` `_write_stop_intent`, `blocks_new_entries`, `_journal_note`)

**Issue:** `default_assemble` builds the engine with a bare `create_engine(_sqlalchemy_url(url), pool_pre_ping=True)`. The project engine factory `src.persistence.engine.make_sync_engine` (used by the paper runtime, `src/paper/runtime.py:488,505`) adds libpq `connect_timeout`, `lock_timeout`, `statement_timeout`, `pool_timeout`, TCP keepalives and a one-time session-UTC probe. The live process uses none of them.

The code that runs on the event loop depends on exactly those bounds. `execute_approved_plan` documents (manager.py:686-695) that the intent store "is called directly on the event loop ... the engine bounds connect, lock wait, statement, pool checkout and a half-open socket ... a call can still block the loop for up to the longest of those bounds". In the live composition the manager gets `stores.execution_state` and `stores.journal` directly (wiring.py:748-762, 712-725), and the coordinator calls `record_protective_intent`, `mark_sent`, `record_result`, `list_open` and `journal.record` inline in `step()`. With no `statement_timeout`, `lock_timeout` or `connect_timeout`, one hung PostgreSQL connection or one long row/advisory lock (the approval save takes `APPROVAL_SERIALISATION_LOCK` and `FOR UPDATE` on the day row, risk_reservations.py:415-423) freezes the single event loop with no upper bound. That loop also runs the protection step, the user-data stream callbacks, the Telegram poller and the liveness stamp. A fill that arrives during the stall gets no stop (the invariant "no position left unprotected" is not enforceable while the loop cannot run), and `max_unprotected_ms` cannot fire because the clock-driven step is the thing that is blocked. A dead pooled connection with a half-open socket (no keepalives) behaves the same way. Fail-closed requires the bound, not just the SAFE_MODE logic that runs after the call returns.

A secondary effect: SQLAlchemy's `QueuePool` default (5 + 10 connections, 30 s checkout) can be exhausted by the writer thread plus `to_thread` reads. The resulting `sqlalchemy.exc.TimeoutError` is not a `DBAPIError`, so `OperationalDatabase.transaction()` does not wrap it into `StoreUnavailable`, and the manager (which catches only `PersistenceError`) lets it escape after the approval was consumed.

**Fix:** use the same factory as the paper runtime, so the UTC pin and every bound apply:

```python
from src.persistence.engine import make_sync_engine
...
    return build_wiring(
        ...
        engine=make_sync_engine(_normalize_database_url(url)),  # bounded waits, UTC verified
        ...
    )
```

`make_sync_engine` raises `StoreUnavailable` / `SessionTimeZoneNotUtc` at build time, which `run_admitted` already turns into a refused start (`the live process could not be built`). Add a test that pins `default_assemble` to `make_sync_engine` (an AST or call-spy test beside `tests/test_live_wiring.py`), so the bounded engine cannot be dropped again.

## Warnings

### WR-01: An interrupted first install leaves a gate state without the spill sentinel, and every later start degrades to SAFE_MODE with entries never enabled

**File:** `src/live/startup.py:817-847` (GATE), `src/live/startup.py:900-908` (SPILL_SENTINEL), `src/live/startup.py:1013-1014` (`_enable`)

**Issue:** `FileGateStateStore.initialize` runs in the GATE step and sets `run.first_install = True`. The sentinel is written much later, in the SPILL_SENTINEL step, and only `if run.first_install`. Steps ALEMBIC, SAFE_MODE and ENABLEMENT sit between them and are HOLD steps. If the first start holds in any of them (`ALEMBIC_HEAD_MISMATCH`, a database outage, a store error while loading SAFE_MODE) or the sentinel write itself fails, the gate state file exists but the sentinel does not. The recovery paths then fail:

- Re-running with `--initialize-gate-state` is refused with `GATE_STATE_EXISTS` ("never re-initialized silently").
- Running without the flag finds the gate state, `first_install` is False, `check_spill_sentinel` is False, and the step raises `StartupStepFailed(SPILL_SENTINEL_MISSING, RESTORE_INCONSISTENT)`. That enters SAFE_MODE on every start, and `run.degraded` is non-empty, so `_enable` skips ENABLE with `BLOCKED_STEP_FAILED` forever. An operator `/safemode_exit` does not help: the next restart enters SAFE_MODE again, and DEMO entries stay disabled.

The only way out is hand-creating `spill/.spill-initialized` with the right JSON on the volume, which the runbook does not document (and RUNBOOK says not to edit the spill directory by hand). The owner runbook step D2 runs this as `docker compose --profile live run --rm live ... --initialize-gate-state` without `--hold-on-refusal`, so a transient failure at that moment is plausible.

**Fix:** write the sentinel in the same step that creates the gate state, or make the sentinel idempotent per install: in the GATE step, after `initialize(...)` succeeds, also call `write_spill_sentinel(ports.spill_directory, now_utc=run.now_utc)` (it is atomic and idempotent); keep the SPILL_SENTINEL step as the check. Alternatively let `--initialize-gate-state` complete an install whose gate file exists but whose sentinel does not (sentinel only), instead of refusing.

### WR-02: A SHADOW runtime restart expires the DEMO process's PENDING approvals (`list_pending_approvals` is not mode-scoped)

**File:** `src/persistence/shadow_stores.py:187-188` and `:221-226`; caller `src/paper/shadow.py:1140`, `src/paper/shadow_runtime.py:978`

**Issue:** The module docstring scopes `list_approved_approvals` by mode (SHADOW sees unmarked and SHADOW rows, DEMO only its own), but `list_pending_approvals` is `_by_status(PENDING)` with no mode filter. `invalidate_pending_on_restart` (the SHADOW restart sweep) iterates `stores.list_pending_approvals()` and decides each row EXPIRED with reason `RUNTIME_RESTART`, journaling `"mode": "SHADOW"`, through the plain `approvals.save_atomic` (no reservation hook). SHADOW and DEMO share one database in the main stack (`paper` and `live` use the same `postgres` service), so any restart of the `paper` service silently expires the live process's outstanding approval cards. `approval_sender.make_open_demo_approvals_reader` already works around the same gap for its own reads (approval_sender.py:521-525), which confirms the store is the wrong layer. Side effects: the DEMO reservation row stays REQUESTED (the reserving hook is bypassed), and the DEMO plan's card cannot be approved any more although its message is still on the owner's phone.

**Fix:** scope the pending reader like the approved one:

```python
def list_pending_approvals(self) -> list[Approval]:
    with self._db.transaction() as session:
        rows = session.execute(
            select(ApprovalRow, JournalEventRow.payload_json)
            .outerjoin(JournalEventRow, and_(
                JournalEventRow.approval_id == ApprovalRow.approval_id,
                JournalEventRow.event_type == EVENT_APPROVAL_MODE_RECORDED))
            .where(ApprovalRow.status == ApprovalResult.PENDING.value)
        ).all()
        ...  # same marker / mode_includes filtering as list_approved_approvals
```

Then drop the `is_demo` workaround in `make_open_demo_approvals_reader` (or keep it as a belt-and-braces check) and add a test with one SHADOW and one DEMO PENDING row.

### WR-03: `mark_placed` and `mark_open` have no production caller, so an executed plan's reservation stays RESERVED for the life of the position

**File:** `src/persistence/risk_reservations.py:463-497` (docstring: "mark_placed, Phase 24 caller"); only caller: `src/live/reservation_release.py:146` (immediately before a release)

**Issue:** `grep` over `src` finds `mark_placed` called only from the release sweep, and `mark_open` from nowhere. After an acknowledged entry nothing moves the row RESERVED -> PLACED (stamped after the exchange acknowledged, which the WR-06 margin logic needs) or PLACED -> OPEN (on fill). `list_margin_claims` returns RESERVED and PLACED rows; `other_claims_margin` (src/risk/margin_check.py:335-372) documents that "a RESERVED claim always counts" while a PLACED claim is netted against `availableBalance` and an OPEN position is never a claim. So the margin of a resting or filled entry is subtracted twice for every other plan (once by the exchange inside `availableBalance`, once by the stale RESERVED claim) until the position ends: "Counting it in both over-refuses" (Pitfall 5 in the same file). The error is in the safe direction, but it makes the margin guard wrong for any second plan, and the release module's comment about "the PLACED instant is the sweep's, later than the acknowledgement" shows the intended caller (the manager/coordinator after `ACKED`, and the first fill) was never wired. This is invisible today only because the live composition tracks one symbol.

**Fix:** call `mark_placed(trade_plan_id, now_utc=<clock read after the acknowledgement>)` from the execution path right after the entry is ACKED/found (through `StoreExecutor.write`, not inline), and `mark_open` from the coordinator's first-fill transition. Add a wiring-gate link for it (as for `LINK_RESERVATION_RELEASE`) and a test that a placed plan is PLACED/OPEN in the store.

### WR-04: Stopping the process leaves resting entries on the exchange with nothing watching them, and the placement drain runs after the coordinator and the stream are already stopped

**File:** `src/live/runtime.py:514-551` (`shutdown_in_order`), `src/live/execution_service.py:191-194` (`drain`)

**Issue:** Protection is fill-driven (D079): the stop is placed only after the process sees a fill. On SIGTERM `shutdown_in_order` stops the scheduler (which stops the protection step), the bot, the stream supervisor (closing the listen key), and only then drains the execution service. Two consequences:

1. A placement that is in flight at the stop finishes during the drain, after the protection step and the stream are gone. Its `register_resting_entry` succeeds but nothing steps that plan again in this process.
2. Every other resting GTD entry (and any entry that fills while the process is down) stays on the exchange without a stop until the next start rebuilds and protects it. The window can be as long as the plan lifetime. Nothing in the shutdown path cancels AWAITING_FILL entries (`expire_pending_entry` is only reachable from the expiry task and the hand-off failure branch), and `update.sh`/`docker compose stop live` are the normal ways to stop it.

The AGENTS invariant is "no new entry opens while any position is unprotected"; a restart window in which an entry can fill unprotected is the same hazard from the other side.

**Fix:** at shutdown, (a) drain `wiring.service` first, (b) then, before stopping the stream and scheduler, run one pass that cancels every plan still in AWAITING_FILL/ENTRY_UNRESOLVED through `expire_pending_entry` (journal-first, verified) and run `coordinator.step()` until no plan is UNPROTECTED or a bounded deadline passes, then stop the stream. If cancel-on-stop is not wanted, document the window in RUNBOOK 22 and make `update.sh` refuse to proceed while the `live` service runs.

### WR-05: Operator commands and start-time rehydration do synchronous database work on the event loop

**File:** `src/live/operator.py:362-373` (`_local_intent`, `_readiness`), `:536-569` (`_journal_row` calls `self._journal.record` inline), `src/live/wiring.py:846-859` (journal = `stores.journal`), `src/live/wiring.py:1216` (`expire_confirms` -> `ConfirmFlow.expire_on_restart`), `src/live/startup.py:569-597` (restore glue)

**Issue:** `OperatorCommands` receives the raw `PgJournalStore`, `PgExecutionStateStore` and `PgPendingActionStore` and calls them on the loop from the PTB handler: every command audit row, a rejected command's journal row, `list_unresolved_intents()` twice and `list_open()` during `/safemode_exit`, plus the readiness reads. The rest of the composition routes these through `StoreExecutor` (D-25), and `ExecutionService`, `ApprovalRequestSender` and the stream already do. During start, `expire_on_restart` and the restored-plans builder also run their store queries inline, after the user-data stream is LIVE. With CR-01 unfixed each of these can block the loop for an unbounded time; with it fixed they are bounded but still stall the protection step and the stream for the duration of the queries. An unauthorized user in the authorized chat is not possible, but the rejection path (`_authorize`) also writes a journal row inline for any message, so a burst of messages from other chats (the bot is public) turns directly into synchronous database writes on the loop.

**Fix:** give `OperatorCommands` the `run_sync`/`run_read` seam used by `ApprovalRequestSender` (`journal` via `executor.write`, intents and pending reads via `executor.read`), and make the rejection journal fire-and-forget through the executor. Do the same for `expire_on_restart`.

## Info

### IN-01: Emergency-close order updates are persisted as stream failures

**File:** `src/live/stream_persistence.py:134-135`, `:198-211`, `:254-262`

**Issue:** `is_system_client_id` accepts the `xc-` family, but an emergency close has no `ExecutionIntent` row (`intent_for_client_id` returns None). Every ORDER_TRADE_UPDATE of a close order (NEW, FILLED) therefore ends in `_fail("ORDER", cid, ..., NO_INTENT)`: a `STREAM_PERSISTENCE_FAILURE` journal row and a warning log per event, and `stats.failures` rises, during exactly the incident an operator reads these rows for.

**Fix:** treat `xc-` ids as known but not persisted (count them as `stats.close_orders`, no failure row), or persist them from the closer's attempt row.

### IN-02: Health tick writes eleven journal rows every reconcile interval

**File:** `src/live/health.py:495-506`

**Issue:** `health_tick_once` journals ten `HEALTH_CHECK` rows and one `HEALTH_VERDICT` per tick (cadence 15 s), each with a time-dependent id, so the append-only journal grows by about 63,000 rows a day from this task alone, whether or not anything changed.

**Fix:** journal the verdict every tick, the individual checks only when a status changes (or at a coarser cadence).

### IN-03: The liveness probe and the external heartbeat ignore the per-task results the stamp carries

**File:** `src/live/config.py:395-427`, `src/live/runtime.py:289-328`

**Issue:** The stamp stores each scheduler task's PASS/FAIL, but `live_liveness_problem` only checks the held marker and the stamp age. A process whose `protection_step` or `reconcile_tick` fails on every tick keeps the heartbeat green and the container healthy. This matches the module docstring, so it is a design limit, not a bug; it is worth recording because the stamp is written by a task of the same loop (so it proves the loop turns, not that protection runs).

**Fix:** optionally make `healthy` false when `protection_step` has FAIL for more than N ticks, once the owner sets N.

### IN-04: `CommissionCache` is built without `record`, so refresh failures are never journaled

**File:** `src/live/wiring.py:560-566`

**Issue:** The cache supports a failure/recovery journal callback, but the composition omits it. A persistently failing commission refresh is visible only as `rest_error_rate` and a refusal at the next placement (`UNCERTAIN_ACCOUNT_STATE`).

**Fix:** pass a `record` that adapts `CommissionRefreshEvent` to `self.record` (as `task_event_journal` does for scheduler events).

### IN-05: `heartbeat.sh --install-timer` validates the checkout path less strictly than `backup.sh`

**File:** `deploy/heartbeat.sh:411-416` vs `deploy/backup.sh:143-152`

**Issue:** `backup.sh` rejects a checkout path outside `^(/|X:/)[A-Za-z0-9._/+=,~-]+$` (systemd specifiers `%` and the replacement character `&` break the unit text). `heartbeat.sh` only rejects whitespace before writing `@TRADING_DIR@` into `WorkingDirectory=` and `ExecStart=`. It also sets `LC_ALL=C` globally inside `validate_url_text` (a side effect on the rest of the run). Both are minor.

**Fix:** reuse `UNIT_PATH_PATTERN` for `REPO_ROOT` in `install_timer`, and scope the `LC_ALL=C` with `local`/a subshell.

---

_Reviewed: 2026-11-07_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
