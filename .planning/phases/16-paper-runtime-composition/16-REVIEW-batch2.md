---
phase: 16-paper-runtime-composition
reviewed: 2026-10-16T00:00:00Z
depth: deep
files_reviewed: 32
files_reviewed_list:
  - src/paper/shadow.py
  - src/paper/shadow_confirm.py
  - src/paper/shadow_fill.py
  - src/paper/shadow_ledger.py
  - src/paper/shadow_runtime.py
  - src/paper/rehearsal.py
  - src/paper/attribution.py
  - src/paper/coverage.py
  - src/paper/exit_criteria.py
  - src/paper/evidence_bundle.py
  - src/paper/evidence_export.py
  - src/ops/evidence_remote.py
  - src/persistence/shadow_stores.py
  - src/adapters/telegram_callbacks.py
  - src/adapters/telegram_notify.py
  - scripts/export_soak_evidence.py
  - scripts/evaluate_trial_soak.py
  - scripts/soak_host_acceptance.py
  - scripts/shadow_rehearsal.py
  - scripts/paper_ws_smoke.py
  - deploy/compose-soak.sh
  - deploy/compose-rehearsal.sh
  - deploy/soak-image.sh
  - deploy/heartbeat.sh
  - deploy/systemd/trading-heartbeat.service
  - deploy/systemd/trading-heartbeat.timer
  - deploy/systemd/trading-backup.service
  - deploy/systemd/trading-backup.timer
  - deploy/soak.env.example
  - deploy/evidence.env.example
  - .github/workflows/paper_freeze_check.yml
  - docker-compose.yml
findings:
  critical: 5
  warning: 8
  info: 8
  total: 21
status: issues_found
---

# Phase 16: Code Review Report (batch 2: SHADOW approval, ledger, evidence, operations)

**Reviewed:** 2026-10-16
**Depth:** deep (cross-file: import graph, call chains, thread/lock interplay, journal identity rules)
**Files Reviewed:** 32
**Status:** issues_found

## Summary

The SHADOW approval/confirm/ledger chain, the coverage and exit-criteria judge, the evidence
export/publish path and the soak operations files were read in full, and their callees were traced
where a claim depended on them (`src/backtest/ledger.py`, `src/paper/live_minutes.py`,
`src/backtest/exits.py`, `src/persistence/journal.py`, `src/approval/replay.py`,
`src/paper/runtime.py`, `Dockerfile`, `src/domain/registry.py`, RUNBOOK 20.x).

The pure judges (`coverage.py`, `exit_criteria.py`, `evidence_bundle.py`) are careful: denominators
are the whole window, unobserved time is never HEALTHY, a missing tick is never CLEAN, and floats
are refused in bundles. No path was found that turns a gap into a PASS.

The serious defects are in the running chain and in the operations path:

- a lock-order inversion that can hang the whole event loop on a CONFIRM (CR-01);
- reservation release driven by the wall clock instead of the data horizon, which journals a false
  `SHADOW_PLAN_EXPIRED_UNFILLED` and later crashes the poller when a last-minute fill is processed
  (CR-02);
- a confirmed plan the fill driver refuses (a TP1 leg that cannot be sized) crash-loops the runtime
  until the plan expires (CR-03);
- the hourly publish procedure cannot work: the second publish of an epoch is always refused and
  the final 14-day bundle can never be published to the recorded location (CR-04);
- the paper container image holds neither `params/` nor the runtime configuration, so the composed
  `paper` service cannot admit its parameter set (CR-05).

Counts: 5 Critical, 8 Warning, 8 Info (21 total). None of CR-01 to CR-04 or WR-01 to WR-05 has a
test that exercises the failing scenario (checked by grep over `tests/`; the existing tests cover
the single-threaded, in-order paths).

## Critical Issues

### CR-01: Lock-order inversion between the CONFIRM section and the poll worker can deadlock the process

**File:** `src/paper/shadow_runtime.py:639-664`, `src/paper/shadow_runtime.py:705`, `src/paper/shadow_confirm.py:842-860`, `src/paper/shadow_confirm.py:1009-1011`, `src/paper/shadow_ledger.py:598-610`
**Issue:** Two code paths take the same two locks in opposite order:

- Event-loop thread (CONFIRM press): `ConfirmBook.handle_confirm` holds `ShadowReservations.section()`
  (= `ShadowLedger.lock`) for the whole press, and `_finish_confirm` calls
  `on_confirmed` = `ShadowCoordinator._on_confirmed` -> `_ensure_drivers`, which takes the
  coordinator's `self._lock`. Order: ledger lock -> coordinator lock.
- Worker thread (`poll_once` -> `await asyncio.to_thread(self._ensure_drivers)`): takes
  `self._lock`, then calls `self._reservations.pending_reservations()` / `positions()`, which take
  `self._ledger.lock`. Order: coordinator lock -> ledger lock.

While `poll_once` awaits the worker, the loop is free to run the PTB callback handler, so the two
really do overlap. Failure scenario: the worker enters `_ensure_drivers` while a CONFIRM is inside
its ledger-locked section (which includes PostgreSQL round trips: `lookup_by_token_hash`, the
`SHADOW_CONFIRMED` append, the reserve). The worker holds `self._lock` and blocks on the ledger lock;
the loop thread then blocks on `self._lock` inside `_on_confirmed`. Both block forever. Because
`handle_confirm` is synchronous on the event loop, the WebSocket consumer, Telegram polling and the
poller all stop; the process does not exit, so `restart: on-failure` never fires (see WR-07), and
coverage is lost until a human notices. Any finding after the epoch pin forces a new trial.
**Fix:** Never hold the coordinator lock while acquiring the ledger lock, and never call back into the
coordinator from inside the CONFIRM section. For example:
```python
def _ensure_drivers(self) -> None:
    # snapshot under the ledger lock only, then build under the coordinator lock
    wanted = (*self._reservations.pending_reservations(), *self._reservations.positions())
    with self._lock:
        for reservation in wanted:
            if reservation.key not in self._positions:
                self._positions[reservation.key] = self._build_position(reservation)

def _on_confirmed(self, approval, plan, confirmed_at_utc) -> None:
    self._drivers_dirty = True   # no locking, no I/O inside the CONFIRM section;
                                 # poll_once builds the driver on its next step
```
Add a test that runs `poll_once` and a CONFIRM concurrently with a store that blocks inside the
section.

### CR-02: Reservations are released at the wall-clock expiry before the fill driver has seen the last minutes; a late-processed fill produces false evidence and crashes the poller

**File:** `src/paper/shadow_runtime.py:698-720`, `src/paper/shadow_runtime.py:763-770`, `src/paper/shadow_ledger.py:798-817`, `src/paper/shadow_ledger.py:855-867`, `src/paper/shadow_ledger.py:335-381`, `src/paper/live_minutes.py:265-272`
**Issue:** `poll_once` advances each driver only to `settled_through_utc = now - close_lag`
(`LiveMinutePoller.poll_once`), but `_sweep(now)` calls `release_expired(now)` with the wall clock.
When `now >= plan_expiry_utc` while the driver's horizon is still before the expiry, the minutes in
`(horizon, plan_expiry]` (at least `close_lag` plus the open minute, more after a slow fetch) have
not been simulated, yet the reservation is released and `SHADOW_PLAN_EXPIRED_UNFILLED` is journaled
and the key is added to `_ended`. The docstring claim at lines 701-702 ("a fill is journaled before
an expiry sweep can release its reservation") does not hold.

On the next poll the driver processes those minutes. If the plan fills there:
- `_apply_new_events` skips `record_position_opened` (the key is no longer in `_held`), so no
  `SHADOW_POSITION_OPENED` is ever journaled;
- `apply_event(FILL)` sets `_remaining` but registers no exposure (with `partial_fill_fraction = 1.0`
  the re-register branch is skipped), so the next risk verdicts see no open position and
  `holds_symbol` is false: a second plan on the same symbol can be alerted and confirmed while a
  simulated position is open;
- the fill fee booking is applied to equity;
- at TP1 or EXIT, `update_exposure` / `remove_exposure` raise `ValueError` (unknown id), `sync_many`
  raises, `poll_once` raises, and `_run_shadow_poller` fails the runtime closed.

After the restart, `rebuild_from_records` sees the terminal `SHADOW_PLAN_EXPIRED_UNFILLED` and
restores nothing, so equity differs from what the risk verdicts used before the crash, and the
journal says "expired unfilled" for a plan the live data filled (fabricated outcome).
**Fix:** Release a reservation only when the data has passed the expiry, not the wall clock:
```python
def _sweep(self, now: datetime) -> None:
    with self._lock:
        positions = dict(self._positions)
    self._reservations.sync_many({k: p.driver for k, p in positions.items()})
    ...
    horizon = now - timedelta(seconds=self._close_lag_seconds)
    self._reservations.release_expired(horizon)   # or: release only keys whose driver
                                                  # advanced_to_utc >= plan_expiry_utc
```
and make `_apply_new_events` fail loudly (journal a conflict) instead of applying a FILL for a key
that is in `_ended`. Add a test with a fill in the last minute before expiry and a positive lag.

### CR-03: A confirmed plan whose fill driver refuses to open crash-loops the runtime until the plan expires

**File:** `src/paper/shadow_runtime.py:666-694`, `src/paper/shadow_runtime.py:655-664`, `src/paper/shadow_runtime.py:705`, `src/paper/shadow_runtime.py:870`, `src/paper/shadow_ledger.py:653-681`, `src/paper/shadow_fill.py:271-284`, `src/paper/runtime.py:679-688`
**Issue:** `ShadowFillDriver.open` can refuse a risk-passed plan (`MIN_QTY_REJECT` when the fill
quantity floors to zero, or a `ProtectiveReject` such as `MIN_QTY_REJECT` / `NOTIONAL_REJECT` when
the TP1 leg cannot be sized at `TP1_QUANTITY_FRACTION` of the fill). The paper pipeline never runs
`protective_levels_for_fill` (only `src/backtest` and `src/execution` call it), and
`ShadowReservations.check` does not either, so such a plan is alerted, APPROVED, CONFIRMED and
reserved. Then `_build_position` raises `ShadowRuntimeError("... cannot rest as a simulated plan")`:
- in `_on_confirmed` it is logged and swallowed;
- in the next `poll_once` it escapes `await asyncio.to_thread(self._ensure_drivers)`, the poller
  task fails, and `run()` raises `RuntimeFailClosed`;
- after the compose restart, `restore()` -> `_restore_positions` rebuilds the still-valid reservation
  and calls `_ensure_drivers` again (line 870), so `start()` fails again. The container crash-loops
  (each start writes RUNTIME_START and CRASH gaps) until the plan's own expiry, which can be hours.

With $500-1000 research equity, quantities near the exchange minimum (where a 50 percent TP1 leg
falls below min quantity or min notional) are realistic; the backtest engine handles exactly this
case as a NO_TRADE, which shows it is expected. One such CONFIRM can push coverage under 95 percent.
**Fix:** Run the same open check before accepting the CONFIRM (inside `ShadowReservations.check`:
build a throw-away driver with the context's constraint snapshot and refuse with the reject code),
and in `_ensure_drivers` handle a refusal per reservation instead of raising: journal a terminal
`SHADOW_RESERVATION_REFUSED` with the reject code and release the reservation. Never let one plan
stop the poller or `restore()`.

### CR-04: The recorded hourly publish procedure cannot work: every publish after the first is refused, and the final bundle can never be published

**File:** `scripts/export_soak_evidence.py:572-605` (refusal at 587-589), `docs/operations/RUNBOOK.md` 20.7 ("Write timing", step 3)
**Issue:** `publish_bundle` stores objects at `<prefix>/<epoch_id>/<file>` and raises
`PublishError("epoch ... is already published; it is never replaced")` when that epoch prefix
already holds `manifest.json`. The recorded O-01 decision and RUNBOOK 20.7 say the operator runs the
export and publish "every hour" for the trial (loss window "at most the last hour"). Every export of
the same epoch has the same `epoch_id`, so:
- the first hourly publish succeeds with a partial, mid-trial bundle;
- every later hourly publish exits 4; nothing more of the trial ever leaves the host;
- the final 14-day bundle can never be published to the recorded location (the prefix is
  immutable by design), and the only published bundle of the epoch is the partial one;
- a host disk loss loses everything after hour one, contrary to the recorded loss window.
The refusal is unit-tested (`tests/test_soak_evidence_export.py:990`), the schedule interplay is not.
**Fix:** Key each bundle by its own identity and keep immutability per bundle, for example
`<prefix>/<epoch_id>/<export_utc>-<sha256(manifest)[:12]>/<file>` (manifest last), and refuse only
when that exact key exists. Alternatively change the recorded procedure, but then the RUNBOOK and
16-DEC-O-01 must change together with the code.

### CR-05: The composed `paper` service cannot load its parameter set or its runtime configuration

**File:** `docker-compose.yml:116-132`, `Dockerfile:34-39` (cross-file), `src/domain/registry.py:41`, `src/paper/runtime.py:255-256`, `src/paper/runtime.py:781-782`
**Issue:** The runtime admits and loads the parameter set from `resolve_registry_root(None)` =
`REGISTRY_ROOT = Path(registry.py).parents[2] / "params"`, i.e. `/app/params` in the image. The
Dockerfile copies only `src`, `scripts`, `alembic.ini` and `docs/research/universe`; `params/` and
`config/paper/paper-runtime-v1.toml` are not in the image, and the `paper` service mounts only the
`logs` volume. There is no environment or CLI override for the registry root in production. The
start gate and `--pin-epoch` therefore cannot load `research-run-1-a01`, the runtime refuses (held
by `--hold-on-refusal`, unhealthy), and `PAPER_RUNTIME_CONFIG` has no in-container file to point at.
The rehearsal runs on the host with `uv run`, so it does not catch this.
**Fix:** Copy the registry and the ratified configuration into the image (they are part of the
frozen decision surface and belong in the image hash):
```dockerfile
COPY params ./params
COPY config/paper ./config/paper
```
and set `PAPER_RUNTIME_CONFIG=/app/config/paper/paper-runtime-v1.toml` in the soak env template.
Add an image test that runs `python -m src.paper.runtime --healthcheck` far enough to load the set.

## Warnings

### WR-01: A CONFIRM shortly after UTC midnight rolls the ledger forward by the wall clock; a late booking of the previous day then crashes the poller

**File:** `src/paper/shadow_ledger.py:271-272`, `src/paper/shadow_ledger.py:653-681`, `src/paper/shadow_ledger.py:740-746`, `src/backtest/ledger.py:140-158`, `src/backtest/ledger.py:186-197`
**Issue:** `ShadowLedger.admit` calls `roll_to(self._ledger, now_utc)` with the CONFIRM wall-clock
instant (from `check` and `reserve`). Bookings, however, arrive with the data lag (`close_lag` plus
the poll interval). If a CONFIRM lands between 00:00:00 UTC and the moment the poller has applied
every booking of minute 23:59 (07:00 Asia/Ho_Chi_Minh, a likely time for the operator to act) and
another open position has a fill, TP or exit in that last minute, `apply_booking` -> `_roll` raises
`ValueError("cannot roll the ledger backwards")`, `sync_many` raises and the runtime fails closed.
`_adopt_stored_confirm` -> `reserve(confirmed_at=<stored, earlier>)` hits the same rule and is
journaled as a reservation refusal for a journaled CONFIRM.
**Fix:** Do not roll the shared ledger from the CONFIRM path: evaluate `admit` on a rolled copy
(`roll_to` returns a new value) and leave the stored ledger's day to the booking stream and the bar
clock, or roll to `min(now, data horizon)`.

### WR-02: An unknown-outcome CONFIRM append is ignored by CANCEL and by the TTL sweep, producing two terminal confirm events and a reservation for a cancelled plan

**File:** `src/paper/shadow_confirm.py:903-909`, `src/paper/shadow_confirm.py:954-962`, `src/paper/shadow_confirm.py:1028-1080`, `src/paper/shadow_confirm.py:1084-1112`
**Issue:** When the `SHADOW_CONFIRMED` append raises and the journal read-back also raises,
`entry.confirm_append_unknown` stays True and the state stays PENDING. Only `handle_confirm`
consults the flag. `handle_cancel` journals `SHADOW_CONFIRM_CANCELLED`, and `expire_due` /
`expire_if_due` journal `SHADOW_CONFIRM_EXPIRED`, even if the CONFIRMED event did commit. The
journal then holds two terminal events (`assert_no_stranded_approvals` fails), attribution takes
`terminal[0]` by time (CONFIRMED), and after a restart `rebuild_from_records` restores the
reservation from the committed `SHADOW_CONFIRMED` payload and simulates a plan the operator
cancelled.
**Fix:** In `handle_cancel`, `expire_if_due` and the `expire_due` loop, reconcile first when the
flag is set (the same `_stored_confirmed` / `_adopt_stored_confirm` step), and fail closed (raise,
write nothing) when the journal cannot be read.

### WR-03: Stale `_last` records make replies describe the wrong plan or outcome

**File:** `src/paper/shadow_confirm.py:635-646`, `src/paper/shadow_confirm.py:679-690`, `src/paper/shadow_confirm.py:994-1003`, `src/paper/shadow_confirm.py:1096-1112`, `src/paper/shadow_confirm.py:1405-1426`, `src/paper/shadow.py:898-920`
**Issue:** `ConfirmBook._result` sets `self._last` on every call, including the TTL sweep
(`expire_due` -> `_expire_ttl`, run by every `poll_once`) and `_finish_confirm` before `reserve`
runs. The reply function prefers `confirm_book.take_last_result()` over the decision record. So
after a background TTL expiry, the reply to the next unrelated press (a SKIP on another alert, a
replayed APPROVE, even a chat-gate rejection) is rendered as "Confirm: EXPIRED_TTL ... Nothing was
simulated" for the wrong plan, and the actual SKIPPED decision is not shown. If `reserve` raises
after `_result`, a stale "Confirm: CONFIRMED ... SHADOW only" is shown on the next reply. If
`deliver_confirm_card` raises, `approvals.take_last_decision()` is skipped and the stale
`DecisionRecord` is used later. The journal is correct; the operator-facing record is wrong.
**Fix:** Do not use shared "last" slots. Return the record from the handler and pass it to the
reply explicitly (for example keyed by `press.correlation_id`), and never set it from sweeps.

### WR-04: Confirm-layer rejection events carry the processing time in the payload, so a redelivered callback raises `JournalConflict` instead of replaying

**File:** `src/paper/shadow_confirm.py:427-448`, `src/paper/shadow_confirm.py:740-770`, `src/persistence/journal.py:52-63`, `src/persistence/journal.py:148-153`
**Issue:** `_journal_rejection` and `_reject_unknown` derive the event id from the callback query id
(`step=press:<cbq:...>[:reason]`), but put `rejected_at_utc = now_utc` (the local clock at
processing, `on_callback` line 777) in `payload_json`, which is an identity field of the PG journal.
Telegram redelivers an unacknowledged `callback_query` with the same id after a crash; the second
processing builds the same id with a different payload and `_verify_replay` raises
`JournalConflict`. The press then ends in the error handler with no reply. This breaks the project
rule that at-least-once callbacks replay to existing state (the Phase 8 receipts were made
redelivery-safe for exactly this reason, `telegram_callbacks.py:574-576`).
**Fix:** Keep wall-clock instants out of the payload of correlation-keyed events (use
`occurred_at_utc`, which is not an identity field), or include the delivery time in the step.

### WR-05: The freeze workflow has no concurrency group; overlapping runs lose a freeze line and create an EVIDENCE_GAP

**File:** `.github/workflows/paper_freeze_check.yml:47-54`, `.github/workflows/paper_freeze_check.yml:89-95`, `.github/workflows/paper_freeze_check.yml:142-147`
**Issue:** Each run restores the newest `paper-freeze-*` cache, appends one line and saves under a
new key `paper-freeze-<run_id>`. Two overlapping runs (a `workflow_dispatch` during a scheduled run,
or a delayed scheduled run catching up) both restore the same state S and save S+a and S+b; the
next run restores only the newest, so one line is lost from the log that RUNBOOK 20.7 tells the
operator to export ("the newest run's artifact is the whole log"). The slot of the lost line becomes
`RUN_WITHOUT_LINE`, an EVIDENCE_GAP, and the qualifying trial restarts.
**Fix:**
```yaml
concurrency:
  group: paper-freeze-check
  cancel-in-progress: false
```
and, for robustness, let the exporter merge the lines of all run artifacts (deduplicated by
`run_id` and `run_attempt`) instead of trusting the newest one.

### WR-06: The exporter writes EVIDENCE_GAP records for slots that have not happened yet

**File:** `scripts/export_soak_evidence.py:386-394`, `scripts/export_soak_evidence.py:424-442`
**Issue:** `freeze_evidence_report` is called with `window_end_utc=end` and
`detected_at_utc=end` with no "as of" bound. An export run before the window end (which the hourly
procedure of RUNBOOK 20.7 does, with the fixed 14-day window that `_trial_window` requires) produces
`NO_RUN_FOUND` EVIDENCE_GAP lines for every future slot, with a `detected_at_utc` in the future, in
`evidence_gaps.jsonl`. The bundle states gaps that have not occurred, and an evaluation of it prints
the "qualifying trial restarts with a new epoch pin" rule, which can lead an operator to re-pin a
healthy trial.
**Fix:** Take an explicit `--as-of` (default: now) and compute slots and gaps only up to
`min(window_end, as_of - grace)`; refuse `as_of < window_end + grace` for a bundle marked final.

### WR-07: Nothing restarts or reports a hung paper runtime, and the timers target the `trading` project, not the soak

**File:** `docker-compose.yml:116-132`, `deploy/heartbeat.sh:222-246`, `deploy/systemd/trading-heartbeat.service:11-17`, `deploy/systemd/trading-backup.service:7-15`
**Issue:** `restart: on-failure` acts only on exit; Docker never restarts an unhealthy container
(the Dockerfile comment says so). The external heartbeat probes only the collector of the project
named by `docker-compose.yml` (`name: trading`, `.env` in the checkout), and the backup unit sets no
`COMPOSE_PROJECT_NAME`/`TRADING_ENV_FILE`, so the nightly backup covers `trading`, not
`trading-soak_pgdata` where the soak evidence lives. A hang of the paper process (CR-01, or a stuck
DB call on the event loop) produces no exit, no external alert and no restart: coverage burns
silently for as long as nobody looks.
**Fix:** For the soak window, add a paper-process check to the external monitor (or a small
watchdog that restarts `paper` via `deploy/compose-soak.sh restart paper` after N unhealthy probes,
journaled as a restart), and give the backup unit an explicit soak instance
(`Environment=COMPOSE_PROJECT_NAME=trading-soak` and the soak env file) or document a second timer.

### WR-08: `dispatch_callback` turns every infrastructure exception into an `INVALIDATED` rejection with no log

**File:** `src/adapters/telegram_callbacks.py:511-538`
**Issue:** `except Exception` around `resolve_callback` journals `CALLBACK_REJECTED` with reason
`INVALIDATED` and returns, with no log line. A PostgreSQL outage, a `ParentRowMissing` or a bug in
`save_atomic` during an APPROVE press is recorded in the evidence as an invalid press; the operator
sees "Rejected (INVALIDATED)". It fails closed (nothing is approved), but the cause is lost from the
journal and the logs, which matters for SC5 evidence and for diagnosing a soak incident.
**Fix:** Keep the fail-closed return, but log the exception class and journal a distinct reason
(for example `STORE_UNAVAILABLE` / the exception class name in the payload), or re-raise
non-domain exceptions so the error handler counts them.

## Info

### IN-01: The soak wrapper's project guard misses the `-p=name` and `-pname` forms

**File:** `deploy/compose-soak.sh:46-62`
**Issue:** Only `-p <name>`, `--project-name <name>` and `--project-name=<name>` are inspected.
`compose-soak.sh -p=trading stop` passes the guard; docker compose's flag parser accepts the
attached short forms, so the wrapper can be pointed at another project. The `down -v` guard still
catches volume removal.
**Fix:** Also match `-p=*` and `-p?*` (and refuse any project flag at all, since the wrapper sets it).

### IN-02: A malformed callback is not journaled, contrary to the parse docstring

**File:** `src/adapters/telegram_callbacks.py:145-151`, `src/adapters/telegram_callbacks.py:759-763`
**Issue:** `on_callback` raises `ValueError` on missing or malformed data before any receipt is
written; the docstring says the receiver journals the malformed receipt. Such presses leave only an
error-handler counter.
**Fix:** Journal a `CALLBACK_RECEIVED` with a `malformed` flag (no raw token is involved) before raising.

### IN-03: A chat-gate rejection is answered in the unauthorized chat with SHADOW content

**File:** `src/adapters/telegram_callbacks.py:795-798`, `src/paper/shadow.py:898-920`
**Issue:** The reply goes to `query.message.chat_id` of the foreign chat and is built by the SHADOW
reply function, which may also consume a stale confirm record (WR-03) with plan times.
**Fix:** Do not reply to an unauthorized chat, or send a fixed text without any record.

### IN-04: Rehearsal and smoke evidence is scrubbed before writing, so the post-write scan can never fail and secrets are silently altered

**File:** `src/paper/rehearsal.py:574-594`, `scripts/paper_ws_smoke.py:471-494`
**Issue:** The text is scrubbed, then written, then re-scrubbed and compared; scrubbing is
idempotent, so the "file that fails the scan is deleted" branch is dead and a secret-looking value
is replaced inside the evidence instead of refusing it (the soak exporter refuses, exit 3).
**Fix:** Scan the unscrubbed text and refuse on a finding, as `export_soak_evidence._scan` does.

### IN-05: `run_rehearsal` writes no evidence when the reference price or the test outcome fails

**File:** `src/paper/rehearsal.py:724-743`
**Issue:** `observed_reference_price` and `build_test_outcome` run inside the outer `try/finally`
only; their exception propagates before `_observe` and `write_evidence`, contrary to the docstring
("a failure while the chain runs still writes the evidence").
**Fix:** Move them inside the inner `try` and guard `_observe` against an unset `plan`.

### IN-06: Rehearsal evidence carries a float

**File:** `src/paper/rehearsal.py:546-548`
**Issue:** `measured_delay_seconds = round(total_seconds(), 3)` is a float in an evidence file; the
bundle loader of the soak refuses floats for the same kind of data.
**Fix:** Write integer milliseconds (`(acted - requested) // timedelta(milliseconds=1)`).

### IN-07: The restart sweep changes the attribution of plans that had already expired untouched

**File:** `src/paper/shadow.py:951-1002`, `src/paper/shadow_runtime.py:939-946`
**Issue:** `invalidate_pending_on_restart` decides EXPIRED for every PENDING approval, including
plans whose expiry passed days earlier. `records_for` then reports `opportunity RUNTIME_RESTART`
instead of `opportunity EXPIRED`, so the attribution of the same history depends on whether a
restart happened later (only the rehearsal consumes `records_for` today; the soak analytics rows are
not built yet).
**Fix:** Sweep only approvals whose plan expiry is still in the future; journal the others as
expired by the plan expiry.

### IN-08: Card-delivery back-off sleeps inside the sequential callback handler and the press time is the processing time

**File:** `src/paper/shadow_confirm.py:1257-1276`, `src/adapters/telegram_callbacks.py:777`
**Issue:** PTB processes updates sequentially by default; a 429 back-off inside `approved_handler`
holds every later press (including the operator's CONFIRM) for up to the confirm TTL, and
`callback_at_utc` is read when the update is processed, so the measured human delay and the TTL
check include this queueing time.
**Fix:** Record the delay as a separate observation, or schedule card delivery as its own task so
the next update is not blocked.

---

_Reviewed: 2026-10-16_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
