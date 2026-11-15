---
phase: quick-261114-kxu
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/reconcile/startup.py
  - src/live/startup.py
  - tests/test_live_restart_rehydrate.py
  - tests/test_startup_recovery.py
  - tests/test_live_start_sequence.py
  - src/execution/protection.py
  - tests/test_protection_liquidation.py
  - src/ops/backup.py
  - src/ops/backup_remote.py
  - tests/test_backup.py
  - tests/test_backup_restore.py
  - tests/test_backup_remote.py
  - src/live/scheduler.py
  - tests/test_live_scheduler.py
  - tests/test_live_wiring_parts.py
  - .planning/quick/261114-kxu-harden-review-leads-restore-isolation-li/261114-kxu-SUMMARY.md
autonomous: true
requirements: [OPS-03, OPS-01, EXEC-01, DATA-04, OPS-06]
user_setup: []

estimate:
  tokens: 140000
  raw_tokens: 140000
  tasks: 5
  confidence: low

must_haves:
  truths:
    - "Restart with two restorable ENTRY rows where one is corrupt (no persisted plan, or a row that `resting_entry_from_intent` refuses): the healthy plan is installed in the coordinator (`coordinator.protection_of(<healthy hash>)` is not None, its client ids are in the index), the report counts `plans_restored == 1` and `plans_unrestorable == 1`, `COORDINATOR_RESTORED` is a failed step, SAFE_MODE is entered with reason `RESTORE_INCONSISTENT` (the controller's `on_enter` alert hook is called with it), and new entries stay blocked by SAFE_MODE."
    - "A store outage while building the plans (an exception outside the row-fault family, for example the test's `StoreUnavailable`) still fails the whole build exactly as before: SAFE_MODE `DB_FAILURE`, `restore_complete` False, `blocks_new_entries()` True."
    - "In the live start sequence a partial restore leaves the process admitted (not held), in SAFE_MODE, with `RECOVERY` in `degraded_steps` and the ENABLE step SKIPPED (placement never enabled)."
    - "A flat positionRisk read right after a fill no longer ends the post-fill liquidation check: a later read that shows the position calls the watch once and journals `PROTECTION_LIQUIDATION_CHECKED`; only after 3 consecutive flat reads is the plan marked checked without a call, with one `PROTECTION_LIQUIDATION_SKIPPED_FLAT` journal note."
    - "`backup()` refuses (ValueError, before pg_dump runs and before anything is deleted) a parquet root whose name is empty, `.` or `..`, or whose resolved path equals, lies inside, or contains the resolved bundle root; a pre-existing file in the bundle root survives the refused call."
    - "`prune_bundle()` refuses a manifest with any key that is unsafe or resolves outside the bundle root: it raises ValueError, deletes nothing and leaves the manifest unchanged; a file outside the bundle named by such a key survives."
    - "pg_dump, pg_restore, the alembic migrate child and the rclone child receive a whitelisted environment: a parent secret such as `BINANCE_DEMO_API_SECRET`, `TELEGRAM_BOT_TOKEN` or `BACKUP_S3_SECRET_ACCESS_KEY` is absent from the child env, while PATH (and SYSTEMROOT where set), the call's prefixed variables (PG* for pg tools, RCLONE_* for rclone) and the explicit mapped/extra variables (PGPASSWORD, DATABASE_URL, RCLONE_CONFIG_*) are present."
    - "A scheduler task whose run exceeds `TaskSpec.stall_after_seconds` produces exactly one `TaskEvent(kind=\"stall\")` per stalled run through the injected `record`; the run is never cancelled or timed out and completes normally; with the default `stall_after_seconds=None` the scheduler behaves exactly as before (same sleeps, same journal)."
    - "The SUMMARY holds: the process behavior after `StartupStepFailed` at RECOVERY, whether a DECISIONS row is needed (with proposed row text if so), the reconcile behavior for an exchange position whose plan was not restored, why no Telegram alert and no wiring value were added for the stall watchdog, and a findings table of the read-only audit of the order-write functions of `src/adapters/binance_usdm.py`."
  artifacts:
    - path: src/reconcile/startup.py
      provides: "PartialRestore exception (healthy plans + unrestorable count), step 4a partial branch (restore healthy plans, then fail COORDINATOR_RESTORED with RESTORE_INCONSISTENT), StartupReport.plans_unrestorable"
    - path: src/live/startup.py
      provides: "restored_plans_builder per-entry isolation over the row-fault family, raising PartialRestore after the index is rebuilt for the healthy plans"
    - path: src/execution/protection.py
      provides: "_Tracked.liquidation_flat_reads, LIQUIDATION_FLAT_READS_LIMIT, EVENT_LIQUIDATION_SKIPPED_FLAT, corrected _check_liquidation_once"
    - path: src/ops/backup.py
      provides: "child_env whitelist helper, parquet-root name/overlap refusal in backup() and run_drill(), prune_bundle unsafe-key refusal"
    - path: src/live/scheduler.py
      provides: "TaskSpec.stall_after_seconds, TaskEventKind 'stall', observe-only watchdog in Scheduler._loop"
    - path: .planning/quick/261114-kxu-harden-review-leads-restore-isolation-li/261114-kxu-SUMMARY.md
      provides: "RED/GREEN evidence per task, the reports asked for in Task 1 and Task 4, the binance_usdm audit table"
  key_links:
    - from: src/live/startup.py restored_plans_builder.build
      to: src/reconcile/startup.py run_startup_recovery step 4a
      via: "raise PartialRestore(plans, unrestorable) caught before the generic Exception clause"
      pattern: "except PartialRestore"
    - from: src/reconcile/startup.py step 4a
      to: SafeModeController.enter_safe_mode -> on_enter (SafeModeAlertObserver in src/live/wiring.py)
      via: "run.fail(STEP_COORDINATOR_RESTORED, SAFE_MODE_RESTORE_INCONSISTENT)"
      pattern: "SAFE_MODE_RESTORE_INCONSISTENT"
    - from: src/ops/backup_remote.py make_rclone_runner
      to: src/ops/backup.py child_env
      via: "import from src.ops.backup (backup_remote already imports from it; no new module, no cycle)"
      pattern: "child_env("
    - from: src/live/scheduler.py Scheduler._loop
      to: injected record (LiveWiring._record_task -> task_event_journal)
      via: "watchdog sibling task: injected sleep, then shielded record of TaskEvent(kind='stall')"
      pattern: "\"stall\""
---

<objective>
Harden five review leads that were verified against the code this session:
(1) one bad restorable row no longer aborts the whole restart restore; (2) a flat positionRisk read no
longer permanently skips the post-fill liquidation comparison; (3) backup refuses parquet roots and
manifest keys that escape or overlap the bundle, and child processes get a whitelisted environment;
(4) the live scheduler gets an observe-only stall watchdog; (5) a read-only audit of the order-write
functions of `src/adapters/binance_usdm.py`, reported in the SUMMARY only.

Purpose: fail-closed behavior that keeps healthy plans supervised, closes a liquidation-check gap,
removes two data-loss paths and a secret-leak path in backup, and makes a hung periodic task visible
without ever cancelling it (a cancelled placement POST would break the "placement never re-sent" rule).

Output: four atomic code commits (each with its own tests, failing test first), one SUMMARY with the
reports and the audit table.

Shape notes (planner choices, documented):
- Quick mode, one plan with the task layout fixed by the orchestrator (4 code tasks + 1 report task).
  Tracer-first is not applied (equivalent of `--no-tracer`): the five items are independent fixes in
  already-proven code; each code task is its own vertical slice with an end-to-end test.
- `workflow.tdd_mode` is on: every code task is `tdd="true"`; run the new tests first and record the
  RED output (failing assertion lines) in the SUMMARY, then implement; ONE commit per task holding
  tests + fix (orchestrator rule), not separate RED/GREEN commits.
- No requirement is marked complete by this quick task (REQUIREMENTS.md is not edited).
</objective>

<execution_context>
@~/.claude/gsd-core/workflows/execute-plan.md
@~/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@AGENTS.md
@.planning/STATE.md

Read code through CodeGraph first (`.codegraph/` exists): `codegraph explore "<symbols>"` before Read/grep.

Verified facts (line numbers at HEAD cac77fb6; re-check before editing):
- `src/live/startup.py` 547-599 `restored_plans_builder` / `build`: the loop raises on the first bad row.
  `RestoreSourceMissing(RuntimeError)` at ~430. `resting_entry_from_intent` (~447) raises ValueError for a
  refused row; `src/execution/protection_rebuild.py` `rebuild_plan` (~277) raises TypeError/ValueError.
  The `recovery()` step body (~931-953) raises `StartupStepFailed(CODE_RECOVERY_INCOMPLETE,
  SAFE_MODE_RESTORE_INCONSISTENT)` when `report.failed_steps` or not `report.restore_complete`.
  `HOLD_STEPS` (~179-181) = CONFIG, GATE, ALEMBIC, SAFE_MODE, ENABLEMENT: RECOVERY is NOT a hold step,
  so `_Run.run` (~751-779) calls `degrade` (SAFE_MODE + FAILED step row); `admitted=held is None` (~1066).
  `_Run.enter_safe_mode` (~724) returns early when the controller is already in SAFE_MODE.
- `src/reconcile/startup.py` 268-281 step 4a: `restored_plans_builder(spill_rows_for)` in try; any
  exception -> `run.fail(STEP_COORDINATOR_RESTORED, SAFE_MODE_DB_FAILURE)` and `coordinator.restore`
  never runs. `PlansBuilder` type alias at ~108. `StartupReport` fields ~122-135, built at ~340-355.
- `src/execution/protection.py` `ProtectionCoordinator.restore` (~1019) sets restore_complete True when it
  returns; `blocks_new_entries` (~970). `SafeModeController` `on_enter` is called once per entry and once
  per re-entry with a NEW reason (`src/reconcile/safe_mode.py` ~238); production binds it to
  `SafeModeAlertObserver` (`src/live/wiring.py` ~653).
- `src/execution/protection.py` `_check_liquidation_once` 1741-1815: `tracked.liquidation_checked = True`
  at ~1782 sits before `if row is None: return False`. `_Tracked.__init__` sets `liquidation_checked`
  at ~785. Event constants ~285-323; `__all__` near ~3228.
- `src/ops/backup.py`: `backup()` 252-322 (roots copied to `bundle_root/parquet/<source.name>` with
  rmtree first, pg_dump runs at ~284 before the root loop); `prune_bundle()` 349-395 unlinks manifest
  keys unchecked; `run_drill()` 449+ has the same `<source.name>` rmtree pattern into the scratch root
  (~492-500); `_is_unsafe_key()` exists at ~602; env spread sites at ~884 (pg_dump), ~907 (pg_restore),
  ~918 (alembic). `src/ops/backup_remote.py` ~284 (rclone) and it already imports from `src.ops.backup`.
  Defaults: `DEFAULT_PARQUET_ROOT = data/raw`, `DEFAULT_BUNDLE_ROOT = data/backup` (siblings, no overlap).
- `src/live/scheduler.py` `_loop` ~170-179 awaits `spec.run()` unbounded. `TaskEventKind` ~48,
  `TaskSpec` ~52-70. The record path in production is `LiveWiring._record_task` (`src/live/wiring.py`
  ~1026) -> `task_event_journal` (`src/live/wiring_parts.py` ~218): journal row only, no alert.
- `src/ops/alerts.py` `ALERT_EVENTS` (~96) is a closed contract (the OPS-05 matrix, 20-REVIEW-RESOLUTIONS
  T-G); `tests/test_alerts.py` and `tests/test_alert_wording.py` pin its exact set (22 events).
- No config key for a stall bound exists (`grep -n "stall\|watchdog"` in
  `src/execution/execution_limits.py` and `config/execution/execution-limits-v1.toml` returns nothing).
- Every touched file is `i/lf w/crlf` (git normalizes); keep the working-tree form, check `git diff`
  shows only intended lines.
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Isolate each restorable entry in the restart restore (healthy plans restored, bad ones -> SAFE_MODE RESTORE_INCONSISTENT)</name>
  <files>src/reconcile/startup.py, src/live/startup.py, tests/test_live_restart_rehydrate.py, tests/test_startup_recovery.py, tests/test_live_start_sequence.py</files>
  <read_first>src/live/startup.py (lines 420-600, 690-800, 925-960), src/reconcile/startup.py (1-140, 230-372), tests/test_live_restart_rehydrate.py (1-260, 540-621), tests/test_startup_recovery.py (130-240, 740-780), tests/test_live_start_sequence.py (700-760)</read_first>
  <behavior>
    - tests/test_live_restart_rehydrate.py, new: two restorable ENTRY rows, one corrupt (a reader wrapper yields the real entry row plus a second row made with `dataclasses.replace` on it: distinct approval_id, trade_plan_id and a later intended_at; `plan_for` returns None for the corrupt trade_plan_id and delegates otherwise). The builder raises `PartialRestore` whose `plans` hold exactly the healthy plan and `unrestorable == 1`; after `restart.recover()`: `coordinator.protection_of(healthy_hash)` is not None, the healthy entry's client id is in the index, `report.plans_restored == 1`, `report.plans_unrestorable == 1`, "COORDINATOR_RESTORED" in `report.failed_steps`, "RESTORE_INCONSISTENT" in `report.safe_mode_reasons`, `restart.safe_mode.in_safe_mode` is True, and an `on_enter` recorder passed to the controller saw "RESTORE_INCONSISTENT". Build the restart with `crash_in_safe_mode=None` so the reason is new.
    - Same file, new: a second corrupt variant where the extra row fails `resting_entry_from_intent` with ValueError (for example a foreign client id) -> same partial outcome.
    - Same file, new: a store outage (`transition_events_for` raising a non-row exception such as OSError) still makes the builder raise that exception (not PartialRestore); recovery enters "DB_FAILURE", `restore_complete` is False, `blocks_new_entries()` is True.
    - Same file, updated: `test_a_restorable_entry_without_its_plan_or_snapshot_fails_closed` now expects `PartialRestore` with `plans == ()` and `unrestorable == 1`, "RESTORE_INCONSISTENT" (not DB_FAILURE) in the reasons, SAFE_MODE on; rename it to say the entry is isolated. Adapt `test_a_row_with_a_foreign_client_id_is_refused` if it expects the builder to raise ValueError (a direct `resting_entry_from_intent` ValueError assertion stays as is).
    - tests/test_startup_recovery.py, new: a builder raising `PartialRestore(<real plans from the harness builder>, 1)` -> `coordinator.restore` ran (the plans are tracked, `restore_complete` True), STEP_COORDINATOR_RESTORED in `failed_steps`, "RESTORE_INCONSISTENT" in `h.safe_mode.entered_reasons`, `report.plans_unrestorable == 1`. The existing `broken_builder` (StoreUnavailable) test stays green unchanged.
    - tests/test_live_start_sequence.py: add `pytest.param("RECOVERY", {"builder": _builder_partial}, id="recovery-builder-partial")` to `FAILING_STEPS`, where `_builder_partial` raises `PartialRestore((), 1)`; the existing parametrized test then proves admitted, in SAFE_MODE, RECOVERY degraded, ENABLE skipped.
  </behavior>
  <action>
    In src/reconcile/startup.py: add `class PartialRestore(Exception)` (with the project's `# noqa: N818` comment style) next to the `PlansBuilder` alias. Its constructor takes `plans: Sequence[RestoredPlan]` and `unrestorable: int`, stores `self.plans` as a tuple and `self.unrestorable`, and passes a fixed message with the count only (never row text). Export it in `__all__`. In step 4a add an `except PartialRestore as partial` clause BEFORE the generic `except Exception` clause: run `coordinator.restore(partial.plans, now_utc=now_utc)` under the same try/except the healthy branch uses (a refused restore -> `run.fail(STEP_COORDINATOR_RESTORED, SAFE_MODE_RESTORE_INCONSISTENT)`); on success set `restore_report` and `plans_restored` as the healthy branch does and then call `run.fail(STEP_COORDINATOR_RESTORED, SAFE_MODE_RESTORE_INCONSISTENT)` exactly once (never `run.ok`). A small local helper shared by both branches is fine. Add `plans_unrestorable: int = 0` as the LAST field of `StartupReport` and set it from the partial count. Extend the module docstring step 4 with one sentence on the partial case.

    In src/live/startup.py: add a module constant `_ROW_FAULTS` = (RestoreSourceMissing, ValueError, TypeError, LookupError, ArithmeticError) with a comment: these are faults of ONE row (missing plan/snapshot, a row the rebuild refuses, a malformed value incl. decimal.InvalidOperation); any other class (a store or journal outage) still propagates and fails the whole build as before, because restoring zero plans as "complete" during an outage would let the reconcile loop read a half-restored registry (plan 20-19 F6). In `build`, wrap the per-entry body (plan/snapshot reads, the None check that raises RestoreSourceMissing, `resting_entry_from_intent`, the transition/stop-intent/spill reads, `rebuild_plan`) in try/except `_ROW_FAULTS`; on a fault record (trade_plan_id, approval_id, exception class name) in a local list, emit one structlog `log.error("live.restore.entry_unrestorable", ...)` line with the two ids and the class name only (never the message), and continue. After the loop call `rebuild_client_id_index(index, plans, intents)` for the healthy plans as today, then raise `PartialRestore(plans, len(unrestorable))` if any entry failed, else return the plans. Import `PartialRestore` through the existing `from src.reconcile.startup import (...)` block. Rewrite the docstring paragraph about RestoreSourceMissing to describe the isolation, the PartialRestore hand-off, SAFE_MODE RESTORE_INCONSISTENT and the store-outage exception. Do not change `run_start_sequence`'s recovery step: its existing StartupStepFailed + degrade path is the intended outcome.

    Tests per <behavior>. For the on_enter recorder, extend the test helper `_restart`/`Restart` with an optional `on_enter` argument passed to `SafeModeController.load` (it accepts `on_enter`); confirm `StoreUnavailable` (or whatever outage class you use) is not a subclass of any `_ROW_FAULTS` member. Run the new tests first, record the RED output in the SUMMARY, then implement.

    Report into the SUMMARY (investigation, no code): (a) what the process does after `StartupStepFailed` at RECOVERY (degrade not hold; admitted; SAFE_MODE; ENABLE skipped so placement is never enabled; `--hold-on-refusal` in src/live/runtime.py applies only to a held start, `_run_async` ~565) with file:line evidence; (b) what the reconcile loop does with an exchange position and its stop whose plan was NOT restored (read `src/reconcile/compare.py` and `src/reconcile/classify.py`: confirm ORPHAN_PROTECTIVE needs no exchange position, so the stop is never swept, and name the divergence/SAFE_MODE/alert the untracked position produces); (c) whether a DECISIONS row is needed: grep `docs/DECISIONS.md`, `docs/operations/RUNBOOK.md` (section 22) and `docs/` for statements of the old behavior (`RestoreSourceMissing`, `COORDINATOR_RESTORED`, restore after restart with DB_FAILURE); do NOT edit docs and do NOT invent a decision; if a canonical statement contradicts the new behavior, write a proposed DECISIONS row text and the doc lines to update into the SUMMARY for the owner.

    Commit (explicit paths only): `fix(quick-261114-kxu): isolate each restorable entry in the restart restore` with trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
  </action>
  <verify>
    <automated>uv run pytest tests/test_live_restart_rehydrate.py tests/test_startup_recovery.py tests/test_live_start_sequence.py tests/test_live_replay_restart.py tests/test_demo_twin_s07_restart_cuts.py tests/test_phase24_gate.py -q</automated>
  </verify>
  <acceptance_criteria>
    - `grep -c "class PartialRestore" src/reconcile/startup.py` is 1 (baseline 0 at HEAD).
    - `grep -c "except PartialRestore" src/reconcile/startup.py` is 1 (baseline 0).
    - `grep -c "plans_unrestorable" src/reconcile/startup.py` is at least 2 (baseline 0).
    - `grep -c "_ROW_FAULTS" src/live/startup.py` is at least 2 (baseline 0).
    - The verify command passes with the new tests included; tests/test_live_replay_restart_pg.py may skip without TEST_DATABASE_URL (state it in the SUMMARY).
  </acceptance_criteria>
  <done>One corrupt restorable row no longer blocks the restore of the healthy plans; the corrupt one enters SAFE_MODE RESTORE_INCONSISTENT (alert hook fired) and new entries stay blocked; a store outage keeps the old DB_FAILURE behavior; the three SUMMARY reports are written; one commit.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Post-fill liquidation check survives a flat positionRisk read (bounded at 3 consecutive flat reads)</name>
  <files>src/execution/protection.py, tests/test_protection_liquidation.py</files>
  <read_first>src/execution/protection.py (280-325, 745-800, 1741-1830), tests/test_protection_liquidation.py (1-145, 394-520)</read_first>
  <behavior>
    - New: flat read then position -> after the first step with position 0 the watch has no call and the plan is not checked; set the position to 0.004, advance the clock, step -> the watch is called exactly once and `_liquidation_events(rig) == [EVENT_LIQUIDATION_CHECKED]`.
    - New: three consecutive flat reads (three steps, clock advanced between them) -> no watch call, one `PROTECTION_LIQUIDATION_SKIPPED_FLAT` journal note whose payload carries `flat_reads` "3"; a position that appears afterwards is not judged (watch still has no call).
    - New: an unreadable read between two flat reads neither counts nor resets (flat, REST failure, flat, position -> watch called once).
    - Replaced: `test_a_flat_position_marks_the_plan_checked_without_asking_the_watch` (its old second half asserts the opposite of the fix); remove it in favor of the tests above.
    - `test_a_restored_plan_starts_unchecked` also asserts the flat-read counter starts at 0.
  </behavior>
  <action>
    In src/execution/protection.py: add the module constant `LIQUIDATION_FLAT_READS_LIMIT: Final = 3` with a comment (structural retry bound for the positionRisk lag right after a fill; not an owner number) and the event constant `EVENT_LIQUIDATION_SKIPPED_FLAT = "PROTECTION_LIQUIDATION_SKIPPED_FLAT"` next to the other liquidation events; add both to `__all__`. In `_Tracked.__init__` add `self.liquidation_flat_reads = 0` beside `liquidation_checked` with a comment. In `_check_liquidation_once`, move the assignment of `tracked.liquidation_checked = True` so it happens only when a non-flat row was found (just before the watch call block). On a flat read (row is None): increment `tracked.liquidation_flat_reads`; when it reaches `LIQUIDATION_FLAT_READS_LIMIT`, set `liquidation_checked = True` and journal one note via `self._journal_note(tracked, EVENT_LIQUIDATION_SKIPPED_FLAT, {"flat_reads": str(count)}, self._now())`; return False in both cases. The unreadable-read branch is unchanged (it neither counts nor resets). Update the docstring sentence that currently says a flat read marks the plan checked: describe the counter, the limit and the note. Nothing else in the method changes (the error/ALERT_ONLY paths stay as they are).

    Tests per <behavior>, reusing the file's helpers (`_rig_with_price`, `_to_protected`, `_events`, `_liquidation_events`, `rig.fake.positions[...]`, `rig.clock.advance`). Run them first, record RED in the SUMMARY, then implement.

    Commit: `fix(quick-261114-kxu): keep the post-fill liquidation check pending across flat position reads` with trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
  </action>
  <verify>
    <automated>uv run pytest tests/test_protection_liquidation.py -q</automated>
  </verify>
  <acceptance_criteria>
    - `grep -c "liquidation_flat_reads" src/execution/protection.py` is at least 3 (baseline 0 at HEAD).
    - `grep -c "PROTECTION_LIQUIDATION_SKIPPED_FLAT" src/execution/protection.py` is 1 (baseline 0).
    - The verify command passes, including the three new tests.
  </acceptance_criteria>
  <done>A flat read no longer ends the check; the watch runs when the position appears; 3 consecutive flat reads end it with one journal note; one commit.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Backup path safety (roots, manifest keys) and whitelisted child-process environment</name>
  <files>src/ops/backup.py, src/ops/backup_remote.py, tests/test_backup.py, tests/test_backup_restore.py, tests/test_backup_remote.py</files>
  <read_first>src/ops/backup.py (60-120, 252-400, 440-500, 600-660, 850-945), src/ops/backup_remote.py (50-70, 266-300), tests/test_backup.py (grep `prune_bundle` and `def test_` first), tests/test_backup_restore.py (360-480), tests/test_backup_remote.py (495-520)</read_first>
  <behavior>
    - tests/test_backup.py: `backup()` with `parquet_roots=(bundle_root / "..",)`, with `(Path("."),)`, with the bundle root itself, with a directory inside the bundle root, and with a directory that contains the bundle root -> ValueError; the pg_dump runner spy was NOT called and a sentinel file placed in the bundle root beforehand still exists.
    - tests/test_backup.py: `run_drill()` with a root named `..` -> ValueError before anything is deleted.
    - tests/test_backup.py: `prune_bundle()` with a manifest containing `parquet/<base>/../../outside.txt` (and a variant with an absolute or backslash key) -> ValueError; the file outside the bundle survives; the manifest bytes are unchanged; with only safe keys the existing prune tests stay green.
    - tests/test_backup_restore.py: `child_env` unit tests with an explicit `environ` mapping: unrelated secrets (`BINANCE_DEMO_API_SECRET`, `TELEGRAM_BOT_TOKEN`, `BACKUP_S3_SECRET_ACCESS_KEY`) dropped; PATH and SYSTEMROOT kept; `PGSSLMODE` kept only when the "PG" prefix is requested; `RCLONE_CONFIG_X` kept only with the "RCLONE_" prefix; `extra` overrides. Extend the existing pg_dump / pg_restore / migrate spy tests (around lines 385-475) with monkeypatched secrets asserted absent from the spy env, PGPASSWORD / DATABASE_URL still present.
    - tests/test_backup_remote.py: extend the rclone env test (~503-514): a monkeypatched `DATABASE_URL` and `BINANCE_DEMO_API_SECRET` are absent from the child env, the `RCLONE_CONFIG_*` mapped values still present.
  </behavior>
  <action>
    (a) Roots. In src/ops/backup.py add `_check_root_name(source)` (ValueError when `source.name` is "", "." or "..", naming the root path) and `_checked_parquet_roots(parquet_roots, bundle_root)` (name check, then with `resolve()` on both: ValueError when the root equals the bundle root, lies inside it, or contains it — `Path.is_relative_to` both ways). Call `_checked_parquet_roots` as the FIRST statement of `backup()`, before `bundle_root.mkdir` and before the pg_dump runner, so a refused call has no side effect. Call `_check_root_name` for every root at the start of `run_drill()` before any rmtree. Update the `backup()` docstring with the refusal.

    (b) Prune. In `prune_bundle()`, after loading the manifest and before computing anything, collect every key for which `_is_unsafe_key(key)` is true or whose `(bundle_root / key).resolve()` is not relative to `bundle_root.resolve()`; if any, raise ValueError with the count ("refusing prune: N manifest keys escape the bundle root"), deleting nothing and leaving the manifest unchanged. Keep a defensive inside-the-bundle check in the unlink loop as well (skip a path outside). Update its docstring.

    (c) Child env. Add a public helper `child_env(*, prefixes=(), extra=None, environ=None) -> dict[str, str]` in src/ops/backup.py (backup_remote already imports from this module, so no new module and no import cycle). It copies from `environ` (default: the process environment read at call time) only the names in a module frozenset `_CHILD_ENV_NAMES` — PATH, PATHEXT, SYSTEMROOT, SYSTEMDRIVE, WINDIR, COMSPEC, HOME, USERPROFILE, APPDATA, LOCALAPPDATA, TEMP, TMP, TMPDIR, LANG, LC_ALL, LC_CTYPE, TZ, SSL_CERT_FILE, SSL_CERT_DIR, HTTP_PROXY, HTTPS_PROXY, NO_PROXY, http_proxy, https_proxy, no_proxy, PYTHONPATH, PYTHONDONTWRITEBYTECODE, PYTHONUNBUFFERED, PYTHONUTF8, PYTHONIOENCODING — plus every name starting with one of `prefixes`, then applies `extra` last. Docstring: why (a parent secret such as Binance, Telegram or bucket keys must not reach pg_dump/rclone/alembic children), and that values are never logged. Replace the four whole-environment spreads: pg_dump and pg_restore runners use `child_env(prefixes=("PG",), extra=target.env)`; the alembic migrate runner uses `child_env(extra={"DATABASE_URL": url})`; `make_rclone_runner` in src/ops/backup_remote.py uses `child_env(prefixes=("RCLONE_",), extra={**mapped, **extra})`, importing `child_env` through its existing `from src.ops.backup import (...)` block. Before finishing, grep `deploy/*.sh`, `docker-compose*.yml`, `Dockerfile` and `docs/operations/RUNBOOK.md` for any variable a child (pg_dump, pg_restore, rclone, alembic) reads from its own environment that the whitelist would drop; add it to `_CHILD_ENV_NAMES` if found and list what you checked in the SUMMARY. Note in the SUMMARY (do not fix) that `scripts/export_soak_evidence.py` ~848 has the same whole-environment spread pattern. Never put a real secret value in a test; use obvious placeholders.

    Tests per <behavior>; run first, record RED, then implement.

    Commit: `fix(quick-261114-kxu): refuse escaping backup roots and manifest keys, whitelist child env` with trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
  </action>
  <verify>
    <automated>uv run pytest -m "not docker" tests/test_backup.py tests/test_backup_restore.py tests/test_backup_remote.py tests/test_backup_retention.py tests/test_backup_lock.py tests/test_backup_gate.py -q</automated>
  </verify>
  <acceptance_criteria>
    - `grep -v '^\s*#' src/ops/backup.py | grep -c '\*\*os\.environ'` is 0 (baseline 3 at HEAD).
    - `grep -v '^\s*#' src/ops/backup_remote.py | grep -c '\*\*os\.environ'` is 0 (baseline 1 at HEAD).
    - `grep -c "def child_env" src/ops/backup.py` is 1 (baseline 0); `grep -c "child_env(" src/ops/backup_remote.py` is at least 1 (baseline 0).
    - `grep -c "_checked_parquet_roots" src/ops/backup.py` is at least 2 (baseline 0).
    - The verify command passes, including the new tests.
  </acceptance_criteria>
  <done>No parquet root or manifest key can make backup or prune delete outside its subtree; children get only whitelisted plus explicit variables; existing backup tests stay green; one commit.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 4: Observe-only stall watchdog for scheduler tasks (journals once per stalled run, never cancels)</name>
  <files>src/live/scheduler.py, tests/test_live_scheduler.py, tests/test_live_wiring_parts.py</files>
  <read_first>src/live/scheduler.py (whole file, 320 lines), tests/test_live_scheduler.py (1-112, 263-410), tests/support/virtual_time.py, tests/test_live_wiring_parts.py (grep `task_event_journal`), tests/test_live_ast_guards.py (the scheduler rules)</read_first>
  <behavior>
    - New: a task whose run waits on an `asyncio.Event`, interval 15, `stall_after_seconds=30`: after advancing 31 virtual seconds the journal holds exactly one ("a", "stall") event (at_utc = the virtual clock at detection, error_class None); advancing 120 more adds none; setting the event lets the run finish normally (then the usual "first_run" event), and the run coroutine observed no CancelledError.
    - New: the next run stalls again -> a second "stall" event (once per stalled run, not once per task).
    - New: a run that ends before the bound -> no "stall" event and no watchdog task left pending (the stop/run test pattern ends cleanly with no "Task was destroyed" warning).
    - New: cancelling `scheduler.run()` while a run is stalled cancels the run exactly as before (existing shutdown semantics) and the watchdog is cleaned up.
    - New: a `record` that raises on the stall event does not stop the loop.
    - New: `TaskSpec(..., stall_after_seconds=0)`, negative, NaN or inf -> ValueError naming the task.
    - Unchanged: with the default None every existing test passes as is (for example `sorted(set(time.sleeps)) == [15.0, 60.0]`).
    - tests/test_live_wiring_parts.py, new: `task_event_journal(TaskEvent(task="protection", kind="stall", ...))` produces a row whose payload kind is "stall" and error_class null.
  </behavior>
  <action>
    In src/live/scheduler.py: extend `TaskEventKind` with "stall". Add `stall_after_seconds: float | None = None` to `TaskSpec` (after `wake`) and validate it in `__post_init__` (when set it must be finite and > 0, else ValueError naming the task). In `_loop`, before awaiting the run, start a watchdog sibling task (with `asyncio.ensure_future`, as `_wait` does) only when `spec.stall_after_seconds` is set; keep awaiting `spec.run()` directly so its cancellation semantics are unchanged; in a `finally` around the run, cancel the watchdog and gather it with `return_exceptions=True` (the same cleanup idiom as `_wait`). The watchdog coroutine awaits the injected `self._sleep(spec.stall_after_seconds)`, then logs one `_LOGGER.error` line (task name and the bound, observe only) and records `TaskEvent(task=..., kind="stall", at_utc=self._clock(), error_class=None)` through `self._record`, wrapped in `asyncio.shield` around a small coroutine that catches Exception and logs the class name (like `_note`), so a run that ends during the journal write does not cut the row and nothing raises out. The watchdog never touches the run: no cancel of the run, no timeout wrapper around it — do not name any asyncio timeout helper in code or docstrings (a gate counts it). Do not change `TaskResult`. Update the module docstring with a "Stall watchdog" paragraph: observe only, why the run is never cancelled (a cancelled placement POST would break the "placement never re-sent" rule, AGENTS.md / D080), one event per stalled run, default off. Keep the module free of wall-clock calls and real `asyncio.sleep` (tests/test_live_ast_guards.py), and use no `float(...)` constructor anywhere in src/live (tests/test_phase24_gate.py forbids it; validate with `math.isfinite` and a `> 0` comparison, the annotation `float | None` is fine).

    Do NOT modify src/live/wiring.py: no config home for a stall bound exists (no key in `config/execution/execution-limits-v1.toml` or `src/execution/execution_limits.py`, and D-12 forbids a cadence number in code), so the protection task keeps the default None. Do NOT add an alert event: the record path is journal-only and `ALERT_EVENTS` in `src/ops/alerts.py` is a closed contract pinned by tests. Write both points into the SUMMARY with a proposal for the owner: a new limit key (e.g. `scheduler.protection_stall_after_ms`, NOT_CONFIGURED until the owner sets it) and a new HIGH alert event (e.g. `TASK_STALLED`) with its wording, GLOSSARY entry and the two pinned alert tests to update.

    Tests per <behavior> in the file's virtual-time style (`VirtualTime`, `Journal`, `_scheduler`, the autouse forbidden real sleep). Run first, record RED, then implement.

    Commit: `feat(quick-261114-kxu): observe-only stall watchdog for live scheduler tasks` with trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
  </action>
  <verify>
    <automated>uv run pytest tests/test_live_scheduler.py tests/test_live_ast_guards.py tests/test_live_wiring_parts.py tests/test_live_wiring.py tests/test_phase24_gate.py -q</automated>
  </verify>
  <acceptance_criteria>
    - `grep -c "stall_after_seconds" src/live/scheduler.py` is at least 3 (baseline 0 at HEAD).
    - `grep -v '^\s*#' src/live/scheduler.py | grep -c 'wait_for'` is 0 (baseline 0 at HEAD; must stay 0).
    - `git diff --quiet HEAD -- src/live/wiring.py` at the end of this task (wiring untouched).
    - The verify command passes, including the new tests.
  </acceptance_criteria>
  <done>A stalled run is journaled once per stall, never cancelled; default behavior unchanged; the wiring and alert gaps are documented with proposals; one commit.</done>
</task>

<task type="auto">
  <name>Task 5: Read-only audit of the order-write functions of src/adapters/binance_usdm.py, then final gates and SUMMARY</name>
  <files>.planning/quick/261114-kxu-harden-review-leads-restore-isolation-li/261114-kxu-SUMMARY.md</files>
  <read_first>src/adapters/binance_usdm.py: `cancel_normal_order` (~1178), `cancel_algo_order` (~1237), `place_entry` (~1299), `place_market_close` (~1394), `place_algo_protective` (~1480), `change_margin_type` (~1879), `change_initial_leverage` (~1910) and the private helpers they call (use `codegraph explore` on these names)</read_first>
  <action>
    READ ONLY: do not change any file under src/ or tests/ in this task. For each function above, check whether the adapter itself validates, before any network call: quantity positive; price / trigger price positive when sent; side within the BUY/SELL enum; order type / algo type within the allowed set; reduceOnly vs closePosition combinations (closePosition with a quantity, reduceOnly on an entry, closePosition on a non-stop type); symbol non-empty; Decimal-only arithmetic and formatting (no float conversion of a price or quantity); timeInForce / goodTillDate consistency for the GTD entry; client order id format and length; leverage and margin type ranges for the two account calls. For every check record: present (file:line), absent, or delegated (name the upstream guard with file:line, for example plan binding, quantization or the SDK). Write a table into the SUMMARY with columns Function | Check | Status (present/absent/delegated) | Evidence (file:line) | Risk if absent | Recommendation. Recommendations are text only; no decision is invented.

    Then run the end gates once: `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src`, and the union of the four task test commands once more. Run `uv run python scripts/verify_decision_alignment.py all` once as a safety check (no docs were edited; report its result). Do not run the full suite.

    Write the SUMMARY (template summary.md) with: per task the RED output lines, the GREEN result, the commit hash; the three Task 1 reports; the Task 3 env-variable check and the `scripts/export_soak_evidence.py` lead; the two Task 4 proposals; the audit table; the gate results; any test that skipped and why. Stage and commit only the SUMMARY path if the orchestrator's quick workflow does not commit it itself (check the workflow; never stage .gsd/, .planning/milestone.lock, .planning/config.json, .planning/STATE.md, .planning/state.json or .planning/REQUIREMENTS.md). Never push.
  </action>
  <verify>
    <automated>git diff --quiet HEAD -- src/adapters/binance_usdm.py && grep -c "| Function | Check | Status" .planning/quick/261114-kxu-harden-review-leads-restore-isolation-li/261114-kxu-SUMMARY.md && uv run ruff check && uv run ruff format --check && uv run mypy src</automated>
  </verify>
  <acceptance_criteria>
    - `src/adapters/binance_usdm.py` is unchanged against HEAD.
    - The SUMMARY contains the audit table header line and at least one row per audited function (7 functions).
    - ruff check, ruff format --check and mypy src are clean.
  </acceptance_criteria>
  <done>The audit table, all reports and gate results are in the SUMMARY; no adapter code changed.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| persisted DB rows -> restart restore | intent, plan, snapshot and journal rows can be missing or malformed after a crash |
| Binance positionRisk -> protection coordinator | the read can lag a fill and show flat |
| CLI args / manifest file -> filesystem deletes | `--parquet-roots` and `manifest.json` keys decide what rmtree/unlink touch |
| parent process env -> child processes | pg_dump, pg_restore, alembic and rclone inherit whatever env they are given |
| periodic task -> exchange | a hung task (for example a placement POST) must stay visible without being cancelled |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-261114kxu-01 | Denial of service | `restored_plans_builder` (src/live/startup.py) | high | mitigate | Per-entry isolation over `_ROW_FAULTS`; healthy plans restored; PartialRestore -> SAFE_MODE RESTORE_INCONSISTENT blocks entries; a store outage keeps DB_FAILURE (Task 1 tests). |
| T-261114kxu-02 | Tampering | partial restore leaves a position untracked | high | mitigate | SAFE_MODE stays on (operator exit only); reconcile never sweeps a stop of a live position (ORPHAN_PROTECTIVE needs no exchange position); Task 1 SUMMARY report (b) confirms with file:line. |
| T-261114kxu-03 | Elevation of privilege | `_check_liquidation_once` | medium | mitigate | Checked flag set only when a position row is read; bounded at 3 flat reads with a journal note (Task 2 tests). |
| T-261114kxu-04 | Tampering | `backup()` / `run_drill()` root handling | high | mitigate | Names "", ".", ".." and bundle overlap refused before any side effect (Task 3 tests with a sentinel file). |
| T-261114kxu-05 | Tampering | `prune_bundle()` manifest keys | high | mitigate | `_is_unsafe_key` + resolved containment check; any bad key refuses the whole prune, nothing deleted (Task 3 tests). |
| T-261114kxu-06 | Information disclosure | child env of pg_dump/pg_restore/alembic/rclone | high | mitigate | `child_env` whitelist + per-call prefixes; tests assert Binance/Telegram/bucket secrets absent; no secret values in tests or logs. |
| T-261114kxu-07 | Denial of service | `Scheduler._loop` hung run | medium | mitigate | Observe-only watchdog journals one stall event per stalled run; the run is never cancelled (placement never re-sent); default off until an owner key exists. |
| T-261114kxu-08 | Information disclosure | new log lines (restore, stall) | low | mitigate | Ids, task names and exception class names only; never exception messages or row text. |
| T-261114kxu-09 | Tampering | adapter order-write functions | medium | accept | Task 5 is read-only; findings go to the SUMMARY for an owner decision; no behavior change in this task. |
| T-261114kxu-SC | Tampering | npm/pip/cargo installs | low | accept | No package is added or upgraded in this plan (no `uv add`, `uv.lock` untouched). |
</threat_model>

<verification>
- Per task: its `<verify>` command passes and its acceptance greps hold (baselines recorded above at HEAD cac77fb6).
- End: `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src` clean; the four task test sets pass together; `uv run python scripts/verify_decision_alignment.py all` result reported. No full suite (the orchestrator runs it).
- `git log --oneline -5` shows four code commits with the Sonnet trailer; `git status` shows no staged change to .gsd/, .planning/milestone.lock, .planning/config.json, .planning/STATE.md, .planning/state.json, .planning/REQUIREMENTS.md.
</verification>

<success_criteria>
- Restart restore isolates bad rows, keeps healthy plans supervised, enters SAFE_MODE RESTORE_INCONSISTENT for the rest, and still fails whole on a store outage.
- The post-fill liquidation comparison runs when the position becomes visible within 3 reads.
- Backup and prune cannot delete outside their subtree; children no longer inherit unrelated secrets.
- A stalled scheduler run is journaled once per stall and never cancelled.
- The SUMMARY answers every report question and holds the binance_usdm audit table.
</success_criteria>

<output>
Create `.planning/quick/261114-kxu-harden-review-leads-restore-isolation-li/261114-kxu-SUMMARY.md` when done
</output>
