---
phase: quick-261114-mp1
plan: 01
subsystem: restart-restore, execution-limits, live-scheduler, alert-contract
tags: [partial-restore-cancel, unrestored-entry, stall-bound-key, task-stalled-alert, d110, d111]
requires: [quick-261114-kxu]
provides:
  - "cancel_unrestored_entries: one cancel by client order id of the resting entry of each unrestorable plan after a partial restore, one position read, alerts, no placement, no close (D110)"
  - "UnrestorableEntry carried by PartialRestore into StartupReport.unrestorable_entries; RecoveryPorts.unrestored_entries"
  - "alert-only limit key scheduler.protection_stall_after_ms (NOT_CONFIGURED) feeding LiveCadences.protection_stall_after and the protection TaskSpec stall_after_seconds (D111)"
  - "HIGH alert TASK_STALLED in the closed ALERT_EVENTS contract (23 events), raised from the scheduler stall event through LiveWiring._record_task (D111)"
affects: [src/reconcile/startup.py, src/live/startup.py, src/live/scheduled_cancel.py, src/live/wiring.py, src/live/wiring_parts.py, src/live/scheduler.py, src/execution/execution_limits.py, src/ops/alerts.py, src/ops/alert_wording.py]
tech-stack:
  added: []
  patterns: ["data-only carrier in reconcile, side effect in the live layer behind a start-sequence port", "alert-only limit key (unset = feature off)", "closed alert contract extension with wording, glossary, matrix row and golden text"]
key-files:
  created:
    - tests/fixtures/phase23/alerts/TASK_STALLED.txt
  modified:
    - src/reconcile/startup.py
    - src/live/startup.py
    - src/live/scheduled_cancel.py
    - src/live/wiring.py
    - src/live/wiring_parts.py
    - src/live/scheduler.py
    - src/execution/execution_limits.py
    - src/ops/alerts.py
    - src/ops/alert_wording.py
    - config/execution/execution-limits-v1.toml
    - config/execution/README.md
    - docs/DECISIONS.md
    - docs/DOC_STATUS.md
    - docs/GLOSSARY.md
    - docs/operations/SECURITY_AND_OPERATIONS.md
    - scripts/gen_phase23_fixtures.py
    - tests/fixtures/phase23/DERIVATIONS.md
    - tests/support/execution_limits.py
    - tests/test_live_restart_rehydrate.py
    - tests/test_live_scheduled_cancel.py
    - tests/test_startup_recovery.py
    - tests/test_execution_limits.py
    - tests/test_no_unratified_defaults.py
    - tests/test_live_scheduler.py
    - tests/test_live_wiring.py
    - tests/test_live_wiring_parts.py
    - tests/test_alerts.py
    - tests/test_alert_wording.py
    - tests/test_alerts_ops05_matrix.py
    - tests/test_phase23_fixtures.py
decisions:
  - "D110: a restorable entry that cannot be rebuilt keeps the per-entry restore isolation (kxu) and its resting entry is cancelled once by its client order id; position alerted, never closed"
  - "D111: TASK_STALLED (HIGH) in the closed alert contract; its bound is the alert-only key scheduler.protection_stall_after_ms, shipped NOT_CONFIGURED"
metrics:
  duration: "about 45 minutes (start time was not recorded; estimate)"
  completed: 2026-11-14
status: complete
commits: 3
plan_head_before: 8ef1133d1bf3334199db8d377c7bfd007e99fbc4
plan_head_after: 91f9bfc07df59b9a0f788bb90533f104ddf902c8
actuals:
  tokens: 15450    # chars/4 over the +/- lines of src, tests, scripts and config in the three commits (git diff)
  tasks: 4
  commits: 3       # MEASURED: git rev-list --count 8ef1133d..HEAD
---

# Phase quick-261114-mp1 Plan 01: Follow-ups to kxu Summary

Three owner-approved follow-ups to quick task 261114-kxu: (A) after a partial restart restore, the resting entry of each unrestorable plan is cancelled once by its deterministic client order id (fail closed, position alerted and never closed); (B) the alert-only limit key `scheduler.protection_stall_after_ms`, shipped `NOT_CONFIGURED`, wired to the protection stall watchdog; (C) the HIGH alert `TASK_STALLED`, raised from the scheduler stall event. No value was chosen anywhere.

## Commits

| Task | Commit | Message |
| ---- | ------ | ------- |
| A | 79aee9a8 | fix(quick-261114-mp1): cancel the resting entry of an unrestorable plan once after a partial restore |
| B | 3a9b220a | feat(quick-261114-mp1): NOT_CONFIGURED scheduler.protection_stall_after_ms feeds the protection stall watchdog |
| C | 91f9bfc0 | feat(quick-261114-mp1): TASK_STALLED alert for a stalled live scheduler task |
| D | none (final gates and this SUMMARY) | |

All three carry the trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Nothing was pushed or merged. Branch `develop`, sequential execution on the main working tree.

## The one-cancel rule (stated plainly)

The new code makes **one cancel request per plan**: `cancel_unrestored_entries` calls `expire_pending_entry` once per distinct plan hash, which sends one `cancel_normal_order` and one `query_order_by_client`. There is no retry, no loop and no second cancel in the new code.

**However, the adapter's `cancel_normal_order` has an existing, unchanged bounded STATUS_UNKNOWN retry** (`_cancel_retrying`, `src/adapters/binance_usdm.py:918`, ceilings `_RECONCILER_CANCEL_*`; an ORDER_ABSENT answer counts as success). So one request from the code can become a few identical, idempotent (by client order id) requests on the wire when the first answer is STATUS_UNKNOWN. The new code does not count or bypass them. If the owner wants a literal single wire request for this path, that is an adapter change (a flag on `cancel_normal_order` or a second method) and needs its own decision; not done. D110 item (6) records the same statement.

## Task A: partial-restore cancel (D110)

**What changed.**
- `src/reconcile/startup.py` (data only, no exchange call): `UnrestorableEntry` (trade_plan_id, approval_id, plan_hash, symbol, fault_class, `plan_hash_rebuilt`), `PartialRestore(plans, unrestorable, entries=())` (positional signature kept), `StartupReport.unrestorable_entries` (last field, default `()`).
- `src/live/startup.py`: `restored_plans_builder` builds the entries from the intent row (plan hash and symbol come from the row, so the entry id is known even without the persisted plan) and flags `plan_hash_rebuilt` with `dataclasses.replace` when another rebuilt plan has the same plan hash. `RecoveryPorts.unrestored_entries` (defaulted last field). The recovery step awaits it once, after `run.recovery = report` and before the existing `StartupStepFailed`; an exception from the port is logged by class name and never stops the start.
- `src/live/scheduled_cancel.py`: `cancel_unrestored_entries(*, entries, adapter, journal, spill, alerts, now_utc)`. Per distinct plan hash: rebuilt-hash guard (no cancel, `UNRESTORED_CANCEL_REFUSED`); one `expire_pending_entry` with the existing trigger `protection_handoff_failed`; `ValueError` (non-live-5 symbol, malformed hash) -> REFUSED; any other `Exception` -> `UNRESTORED_CANCEL_FAILED`; verdict `STILL_OPEN` or `UNKNOWN` -> `UNRESTORED_CANCEL_UNVERIFIED`; `CANCELED`, `GONE_NOT_CANCELED`, `FILLED_OR_PARTIAL` raise no cancel alert. Then one `snapshot_positions(symbol=...)`: a non-zero or non-Decimal amount -> DIVERGENCE `UNRESTORED_PLAN_POSITION`; the read raising or a symbol outside the live-5 universe (no read) -> DIVERGENCE `UNRESTORED_POSITION_UNKNOWN`. Nothing is closed. A raising alert sink is logged by class name and the next entry still runs; a `BaseException` propagates.
- `src/live/wiring.py`: `startup_ports` binds `unrestored_entries` to the closure that calls it with `self.exchange.adapter`, `stores.journal`, `self.spill`, `self.alerts.sink`.
- Docs: DECISIONS D110 (also records the per-entry restore isolation that kxu proposed and did not write), DOC_STATUS line, GLOSSARY rows (`RESTORE_INCONSISTENT`, `PROTECTION_HANDOFF_FAILED`, two alert-reason rows in 15.3).

**RED.** The new tests were written first; with the source at HEAD the three test modules failed at collection:
```
tests\test_live_restart_rehydrate.py:49: in <module>
    from src.live.scheduled_cancel import cancel_unrestored_entries
E   ImportError: cannot import name 'cancel_unrestored_entries' from 'src.live.scheduled_cancel'
```

**GREEN.** Verify set (`tests/test_live_restart_rehydrate.py tests/test_live_scheduled_cancel.py tests/test_startup_recovery.py tests/test_live_start_sequence.py tests/test_live_replay_restart.py tests/test_demo_twin_s07_restart_cuts.py tests/test_live_wiring.py tests/test_live_ast_guards.py tests/test_phase24_gate.py`, `-m "not docker"`): 363 passed, 1 xfailed, 0 skipped. `TEST_DATABASE_URL` was set in the environment, so `tests/test_live_replay_restart_pg.py` was also run: 10 passed. Decision alignment ALL_PASS. New tests: builder carries `UnrestorableEntry` with `plan_hash_rebuilt` True (shared hash) and False (distinct hash); full restore and store outage leave `unrestorable_entries == ()`; start-sequence E2E (plan A healthy and resting, plan B unrestorable and resting on the fake exchange: exactly one `cancel_normal_order` with B's id during the start, B gone, A still open and supervised, no `place_entry`, `place_algo_protective` or `place_market_close` call, SAFE_MODE `RESTORE_INCONSISTENT`, RECOVERY degraded, no alert, journal rows with trigger `protection_handoff_failed`); E2E with a partial fill (one cancel, one DIVERGENCE `UNRESTORED_PLAN_POSITION`, no close, position unchanged); start without the port behaves as before; unit tests for cancel failure, unverified (absent and still open), shared hash, non-live-5 symbol, unreadable position, non-zero position, two entries with one hash, two distinct plans, raising sink, `BaseException`, alert-contract membership.

## Task B: stall bound key (D111, part 1)

**What changed.** Section `scheduler` with key `protection_stall_after_ms`, the last section of `EXECUTION_LIMIT_KEYS`; field `scheduler_protection_stall_after_ms` (last, kw-only, no default) and property `scheduler_protection_stall_after`; the key is in `ALERT_ONLY_LIMIT_KEYS` (not in `unset_keys()`, not an optional refinement); the shipped TOML carries `NOT_CONFIGURED` for both value and provenance; `config/execution/README.md` (new section, one "still NOT_CONFIGURED" bullet, sections line). `LiveCadences.protection_stall_after: timedelta | None = None` (the only defaulted field; the default is not a number) and `protection_stall_after_seconds` (`total_seconds()`, no `float(...)`); `from_limits` does not refuse an unset stall key. `LiveWiring._specs` passes `stall_after_seconds=cadences.protection_stall_after_seconds` to the protection TaskSpec only. TEST_ONLY value for the key is `None` (unset, like the shipped file), so every wiring test keeps the watchdog off.

**RED** (key block, scheduler and wiring tests written first, source at HEAD):
```
71  E   KeyError: 'scheduler.protection_stall_after_ms'
12  E   KeyError: 'scheduler'
 7  E   ExecutionLimitsInvalid: execution limits invalid: scheduler (unknown section); provenance.scheduler (unknown section)
 2  E   AssertionError: assert () == ('scheduler.protection_stall_after_ms',)
```
**GREEN.** Verify set (13 modules incl. the phase 19, 21, 22, 24 gates): 656 passed. `tests/test_phase20_gate.py`: only invariant 6 fails (unchanged reason, see Residuals). `grep -v '^#' config/execution/execution-limits-v1.toml | grep -c protection_stall_after_ms` = 2; `grep -c "stall_after_seconds=" src/live/wiring.py` = 1; the shipped file still has `unset_keys() == ()`.

## Task C: TASK_STALLED alert (D111, part 2)

**What changed.** `ALERT_EVENTS["TASK_STALLED"] = HIGH` (23 events) and its `OPS05_MATRIX` row (producer `src/live/wiring_parts.py`); `EVENT_WORDING["TASK_STALLED"]` (four single lines; says the task was not stopped or restarted, nothing was cancelled or re-sent, the stall is journaled; operator must check); `alert_task_stall(event, sink)` in `src/live/wiring_parts.py` (stall kind only, subject = task name, reason `STALL_BOUND_EXCEEDED`, `now_utc=event.at_utc`, a raising sink is swallowed and logged by class name); `LiveWiring._record_task` journals first and calls `alert_task_stall` in a `finally`, so a failing journal write does not lose the alert (the journal exception still propagates to the scheduler, which already absorbs it). Docs: DECISIONS D111 (also records the B key), DOC_STATUS, GLOSSARY row, SECURITY_AND_OPERATIONS 5.1 row.

**RED:** `KeyError: 'TASK_STALLED'` (wording and alert create), `AssertionError: TASK_STALLED` (matrix collection), `Extra items in the right set: 'TASK_STALLED'` (contract set), and the two wiring tests failing with `assert 0 == 1` (no alert queued).

**GREEN.** Verify set plus the Phase 23 fixture tests and the phase 20 gate: 463 passed, 1 failed (phase 20 invariant 6, pre-existing). Decision alignment ALL_PASS.

## Final gates (Task D)

Run once after the third commit:
- `uv run ruff check`: All checks passed. `uv run ruff format --check`: 1029 files already formatted. `uv run mypy src`: Success, no issues in 291 source files. `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- Union of the test sets of A, B, C plus the Phase 23 fixture and gate tests, `-m "not docker" -n 4`: **1133 passed, 1 xfailed, 0 skipped** (the xfail is the one already present in the kxu run). `tests/test_live_replay_restart_pg.py` (TEST_DATABASE_URL set): 10 passed.
- Not run: the full suite (orchestrator), docker-marked tests, `pytest -m demo`, `--execute` scripts, any `*_pg.py` file other than `test_live_replay_restart_pg.py`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Phase 23 golden alert text, generator row and derivation note for TASK_STALLED**
- **Found during:** Task C
- **Issue:** `tests/test_phase23_fixtures.py` requires exactly one golden file per worded event and `render_all()` equal to the files on disk; adding wording for `TASK_STALLED` without them fails both. The plan's file list did not include them.
- **Fix:** one `ALERT_CASES` row in `scripts/gen_phase23_fixtures.py` (subject `protection_step`, reason `STALL_BOUND_EXCEEDED`); `tests/fixtures/phase23/alerts/TASK_STALLED.txt` was written by the generator's own `render_all`/`_write_text` (not typed, only the new file, no other golden touched); the file-count pin 18 -> 19; one row in `tests/fixtures/phase23/DERIVATIONS.md`.
- **Files modified:** scripts/gen_phase23_fixtures.py, tests/fixtures/phase23/alerts/TASK_STALLED.txt, tests/fixtures/phase23/DERIVATIONS.md, tests/test_phase23_fixtures.py
- **Commit:** 91f9bfc0

**2. [Rule 1 - Test pins] Tests that pinned the old key set, the old event count or an all-timedelta cadence**
- **Found during:** Tasks B and C
- **Issue:** `test_every_cadence_is_a_positive_timedelta` iterated all `LiveCadences` fields; `test_the_alert_contract_of_phase_20_is_untouched` pinned 22 events; the shipped-file test counted two `NOT_CONFIGURED` strings; the section-order test listed three trailing sections; the README key-list test needed the new bullet.
- **Fix:** pins updated (the cadence test skips the one optional field with a comment; 23 events; four `NOT_CONFIGURED` strings; four trailing sections; README bullet added).
- **Files modified:** tests/test_live_scheduler.py, tests/test_alert_wording.py, tests/test_execution_limits.py
- **Commits:** 3a9b220a, 91f9bfc0

**3. [Rule 1 - Test data] Partial fill in the position E2E uses 0.03, not 0.5**
- **Found during:** Task A. The rig's entry quantity is 0.071, so a 0.5 fill is refused by the fake. Test constant only.

### Process notes (not code deviations)
- Working-tree line endings: nearly every file is CRLF in the working tree (`core.autocrlf=true`, index LF), more files than the plan listed. All edits went through a bytes-aware helper that keeps each file's line ending; `git diff --cached --stat` of each commit shows only the intended line counts. `tests/test_execution_limits.py` is LF in the working tree and was left LF (git prints the usual CRLF warning).
- `DIVERGENCE` is raised through the same `alerts.critical(...)` call as PROTECTION_HANDOFF_FAILED: `JournalFirstAlertSink.critical` takes any event and the severity comes from `ALERT_EVENTS`, so one sink protocol (`CriticalAlertSink`) covers both and the dedupe key stays (event, symbol, reason).
- Duration was not timed at start; the figure in the frontmatter is an estimate.

## Design choices

- **Where the cancel lives.** `src/live/scheduled_cancel.py` (so the pinned `LIVE_MODULES` inventory of `tests/test_phase24_gate.py` is unchanged), called from the live recovery step through `RecoveryPorts.unrestored_entries`. `src/reconcile/startup.py` only carries data; its probe adapter stays read-only.
- **No new vocabulary except five alert reason codes.** The existing trigger `protection_handoff_failed` and the existing events PROTECTION_HANDOFF_FAILED (CRITICAL; unverified, failed or refused cancel) and DIVERGENCE (HIGH; position) are reused. Added: `UNRESTORED_CANCEL_UNVERIFIED`, `UNRESTORED_CANCEL_FAILED`, `UNRESTORED_CANCEL_REFUSED`, `UNRESTORED_PLAN_POSITION`, `UNRESTORED_POSITION_UNKNOWN`.
- **Shared plan-hash guard.** An unrestorable row whose plan hash equals a rebuilt plan's is never cancelled (the deterministic id would hit a supervised order). The existing two-row tests share the healthy plan's hash, so they exercise exactly this guard.
- **One position read per symbol, never a close.** The position's owner is not determined; the operator decides (RUNBOOK 21).
- **The intent row of the cancelled entry is not rewritten** by the cancel (journal only, as for the scheduled cancel). It stays as restored.
- **The stall key is alert-only and unset in the TEST_ONLY values too** (`None`), so no wiring test turns the watchdog on by accident.
- The adapter's existing bounded STATUS_UNKNOWN retry of a cancel is unchanged (see "The one-cancel rule"); the owner may ask to bypass it.

## Measuring a value for `scheduler.protection_stall_after_ms` (no value chosen)

**What the journal holds at HEAD.** A protection run's duration is **not** journaled. `journal_events` rows with `correlation_id = 'live_scheduler'` and `entity_id = 'protection_step'` exist only for the scheduler outcome changes: `first_run`, `failure`, `recovery` and (only when a bound is set) `stall`. Their `event_type` is `LIVE_TASK_EVENT` and `payload_json` is compact JSON with `task`, `kind` and `error_class`. There is no start time, end time or duration per run, and the per-run `_note` only journals on a change. The untracked Demo evidence under `.planning/phases/24-live-runtime-composition-demo/evidence/` records no step or call times either: the rehearsal files carry `steps` (name, status, detail only), `runner_clock_utc` (started and finished of the whole run) and `cancel_query_lag_observations`; no per-run protection timing.

**Columns** (from `src/db/alembic/versions/0002_domain_registry.py`, table `journal_events`): `journal_event_id`, `occurred_at_utc`, `event_type`, `entity_type`, `entity_id`, `correlation_id`, `signal_id`, `trade_plan_id`, `approval_id`, `order_id`, `position_id`, `payload_json` (text), `created_at_utc`.

**Read-only query 1: the stall rows of the protection task** (empty while the key is unset):
```sql
SELECT occurred_at_utc, payload_json
FROM journal_events
WHERE correlation_id = 'live_scheduler'
  AND entity_id = 'protection_step'
  AND event_type = 'LIVE_TASK_EVENT'
  AND payload_json LIKE '%"kind":"stall"%'
ORDER BY occurred_at_utc;
```

**Best existing proxy for the longest protection work, read-only query 2: the protection transitions of one plan** (correlation `protection_<plan_hash>`, event type `PROTECTION_TRANSITION`; payload keys `from`, `to`, `reason`, `seq`, `symbol`):
```sql
SELECT correlation_id, occurred_at_utc, payload_json
FROM journal_events
WHERE correlation_id LIKE 'protection\_%'
  AND event_type = 'PROTECTION_TRANSITION'
ORDER BY correlation_id, occurred_at_utc;
```
Per plan, take the time from the transition to `UNPROTECTED` (fill seen) to the transition to `PROTECTED_ENTRY_OPEN` or `PROTECTED` (stop confirmed). This is a **lower bound only, and only when both transitions were journaled by the same run**: the journal does not say which run wrote a row, so a gap that spans two runs includes the wait between runs (`reconcile.tick_interval_ms`) and is not a run duration. A fill also wakes the protection task (`wake=parts.stream.wake`), so runs are not strictly on the tick.

**Direct method, no code change (owner-run Demo only, never an agent):**
1. The live CLI has **no flag** to choose the limits file: `default_limits_path(repo_root)` (`src/live/config.py`) is `config/execution/execution-limits-v1.toml` under the repository or image root; `main(limits_path=...)` is a Python argument, not a command-line option. So the owner edits the Demo host's copy of that file **for the measurement only** (an image or checkout used only for the Demo run) and does not commit it.
2. In that copy set `[scheduler] protection_stall_after_ms = <trial bound in milliseconds>` and, in `[provenance.scheduler]`, a label the loader accepts for an integer (STRUCTURAL, COST_GUARD, DECISION or EXPERIMENT; use EXPERIMENT for a trial). `NOT_CONFIGURED` or PLACEHOLDER with an integer is refused at load.
3. Run Demo sessions that exercise the protection step (fills, stop placement, restarts, TP attach) and count the `kind = stall` rows (query 1) per trial bound. A bound that produces no stall row over the sessions covers every run observed at that bound; lower the bound until the first stall rows appear to find the observed maximum.
4. The bound the owner adopts = the maximum observed run duration plus a margin the owner chooses. Relations to keep in mind (no number is chosen here): it must stay **below `protection.max_unprotected_ms`** if the alert is to fire before the unprotected deadline; the alert is deduplicated per (event, task name, reason) inside `alerts.dedupe_window_ms`, so repeated stalls inside that window are suppressed in Telegram (journaled as `ALERT_SUPPRESSED`) while every stall still gets its `LIVE_TASK_EVENT` row.
5. Adopting it needs its own DECISIONS row and the provenance label `DECISION` in the shipped file (D111 item 5).

A per-run duration record (one journal row per run with its duration) would make this measurement direct and permanent, but it would need a new decision (journal volume and the closed event vocabulary); not done.

## Residuals and follow-ups (for the owner)

- **`tests/test_phase20_gate.py::test_invariant_6_decisions_gained_no_row_and_d055_stays_open` fails before and after for the same reason** (it pins Phase 20's view of the DECISIONS table and sees rows after D107). Not edited, as instructed. Before (at HEAD 8ef1133d): the rows after D078 end `... 'D107', 'D108', 'D109'` (message "Left contains 2 more items, first extra item: 'D108'"). After this plan: the same assertion at `tests/test_phase20_gate.py:409`, the list now ends `... 'D107', 'D108', 'D109', 'D110', 'D111'`. It would only be legitimate to extend its list if the owner asks.
- **RUNBOOK** sections 21 and 22 do not yet describe the restart cancel (D110) or `TASK_STALLED` (D111): owner follow-up (not edited, as instructed).
- **AGENTS.md** "Still open (owner)" does not name the new `NOT_CONFIGURED` key `scheduler.protection_stall_after_ms` (gated file, not edited): owner follow-up.
- A literal single wire request for the restart cancel needs an adapter change (see "The one-cancel rule").
- `scripts/export_soak_evidence.py:848` full-environment spread (kxu lead) is still open.
- Not verified here: the real adapter's `snapshot_positions` over a real symbol after a restart and a real Binance cancel answer for an unrestorable plan (the E2E runs on the Binance-semantics fake; the Demo restart rehearsal is owner-run).
- Skipped by design: full suite, docker-marked tests, `pytest -m demo`, `--execute` scripts, `*_pg.py` other than `test_live_replay_restart_pg.py` (which ran, 10 passed, because `TEST_DATABASE_URL` was set).

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model. New surface: three log lines by class name only (`live.restore.unrestored_cancel_failed`, `live.restore.unrestored_cancel_refused`, `live.restore.unrestored_position_unreadable`, `live.restore.unrestored_alert_failed`, `live.task_stall_alert_failed`; ids and class names, no exchange or row text). T-mp1-01 to T-mp1-05 mitigations are implemented as planned (deterministic id only, shared-hash guard, live-5 refusal before any call, no placement path reachable and the AST guards green, one request per plan, codes only in alerts, journal-first audit through `expire_pending_entry`).

## Self-Check: PASSED

- Commits 79aee9a8, 3a9b220a, 91f9bfc0 are ancestors of HEAD; `git rev-list --count 8ef1133d..HEAD` = 3.
- Created file exists: `tests/fixtures/phase23/alerts/TASK_STALLED.txt`.
- `git status` shows no staged change; `.planning/STATE.md`, `.planning/config.json`, `.planning/REQUIREMENTS.md` and `.planning/state.json` remain unstaged owner modifications; untracked files were not touched.
- Acceptance greps: `grep -c "cancel_unrestored_entries" src/live/scheduled_cancel.py` >= 2; `grep -c "unrestored_entries=" src/live/wiring.py` = 1; `^| D110 |` and `^| D111 |` in docs/DECISIONS.md = 1 each; `"TASK_STALLED"` in src/ops/alerts.py >= 2; `alert_task_stall` in src/live/wiring.py >= 1; CRLF and LF byte counts equal in every CRLF file touched.
