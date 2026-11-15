---
phase: quick-261115-kra
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  # Task 1 (one commit; every file is CRLF in the working tree, see <context>)
  - src/live/scheduler.py
  - src/live/wiring_parts.py
  - src/live/wiring.py
  - src/execution/execution_limits.py
  - config/execution/execution-limits-v1.toml
  - config/execution/README.md
  - tests/support/execution_limits.py
  - tests/test_live_scheduler.py
  - tests/test_live_wiring_parts.py
  - tests/test_live_wiring.py
  - tests/test_execution_limits.py
  - tests/test_no_unratified_defaults.py
  - tests/test_phase18_gate.py
  # Task 2 (one commit, docs, CRLF)
  - docs/DECISIONS.md
  - docs/DOC_STATUS.md
  - docs/GLOSSARY.md
  - docs/operations/RUNBOOK.md
  # Task 3 (no commit; the orchestrator commits it)
  - .planning/quick/261115-kra-per-run-duration-record-for-live-schedul/261115-kra-SUMMARY.md
autonomous: true
# Quick task: no REQUIREMENTS.md id is closed. The ids name the two owner-approved deliverables.
requirements: [kra-1-duration-record, kra-2-measurement-docs]

estimate:
  tokens: 90000
  raw_tokens: 90000
  tasks: 3
  confidence: low   # estimate-calibration: factor 1, applied false, sample_count 0

must_haves:
  truths:
    - "Every run of every live scheduler task that ends (ok or failed) is timed from the scheduler's injected clock in whole milliseconds: (end - start) floor-divided by a one-millisecond timedelta, a negative difference counts as 0; a cancelled run is not counted; the new code has no float constructor and no new seconds conversion"
    - "Per task the scheduler keeps, since process start, runs, total_ms, max_ms (all int) and window_max_ms; it writes AT MOST ONE TaskDurationSummary per run end: always when the run sets a new maximum (strictly greater; the first run of a task is one), and, only when scheduler.duration_summary_interval_ms is set, at the first run end at least that interval after the window start (window_end true, then the window restarts at that run end and window_max_ms restarts)"
    - "Default: the new key scheduler.duration_summary_interval_ms ships NOT_CONFIGURED with provenance NOT_CONFIGURED, is in OPTIONAL_REFINEMENT_LIMIT_KEYS (never refuses the start, never named by unset_keys or require_live_ready), and while it is unset only the new-maximum rows are written; no number exists in code for it, and no value is chosen for it or for scheduler.protection_stall_after_ms"
    - "Observe only: with or without the duration record the scheduler makes the same sleeps, the same TaskEvent rows and the same TaskResult values; a duration writer that raises is logged by exception class name and the loop goes on; nothing is cancelled; the existing TaskEventKind set (first_run, failure, recovery, stall) is unchanged"
    - "Not an alert: LIVE_TASK_DURATION is not in ALERT_EVENTS, EVENT_WORDING or OPS05_MATRIX; LiveWiring._record_task_duration journals through self.record and never touches the alert sink (the queue stays empty)"
    - "Production path: LiveWiring builds its Scheduler with record_duration=self._record_task_duration and duration_summary_interval=self.cadences.duration_summary_interval; task_duration_journal writes event_type LIVE_TASK_DURATION, entity_type LiveScheduler, entity_id the task name, correlation_id live_scheduler, and a compact sorted JSON payload with exactly max_ms, new_max, runs, task, total_ms, window_end, window_max_ms"
    - "Every pinned count is updated with a history comment: GUARDED_NAMES 66 -> 68 (tests/test_no_unratified_defaults.py and tests/test_phase18_gate.py), dotted key count 22 -> 23, shipped NOT_CONFIGURED strings 4 -> 6, the optional-refinement set and tuples, the distinct TEST_ONLY values check (None excluded), the positive-cadence check (both optional fields skipped)"
    - "docs: D112 (contiguous after D111, same 5-pipe layout), one DOC_STATUS line, one GLOSSARY 9.3 row, RUNBOOK 22.7 bullet and 22.8 rewritten: read-only SQL over the LIVE_TASK_DURATION rows and the rule 'longest observed run x an owner margin, below protection.max_unprotected_ms (180000 ms)'; the transitions proxy query and the trial-bound procedure are gone; every 22.8 claim has a file:line in the SUMMARY"
    - "All named gates pass; two commits with the trailer Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>; owner-modified and untracked files untouched; CRLF = LF counts recorded before and after for every touched file"
  artifacts:
    - path: src/live/scheduler.py
      provides: "TaskDurationSummary, RecordDuration, Scheduler(record_duration=..., duration_summary_interval=...), _note_duration, LiveCadences.duration_summary_interval"
      contains: "class TaskDurationSummary"
    - path: src/live/wiring_parts.py
      provides: "EVENT_TASK_DURATION = \"LIVE_TASK_DURATION\" and task_duration_journal(summary)"
      contains: "def task_duration_journal"
    - path: src/live/wiring.py
      provides: "LiveWiring._record_task_duration and the two Scheduler keyword arguments"
      contains: "record_duration=self._record_task_duration"
    - path: src/execution/execution_limits.py
      provides: "key scheduler.duration_summary_interval_ms, field scheduler_duration_summary_interval_ms, property scheduler_duration_summary_interval, membership of OPTIONAL_REFINEMENT_LIMIT_KEYS"
      contains: "duration_summary_interval_ms"
    - path: config/execution/execution-limits-v1.toml
      provides: "[scheduler] duration_summary_interval_ms = \"NOT_CONFIGURED\" and its NOT_CONFIGURED provenance"
    - path: docs/DECISIONS.md
      provides: "row D112"
      contains: "| D112 |"
    - path: docs/operations/RUNBOOK.md
      provides: "22.8 measurement from LIVE_TASK_DURATION rows; 22.7 bullet for the new key"
      contains: "LIVE_TASK_DURATION"
  key_links:
    - from: src/live/scheduler.py Scheduler._loop
      to: src/live/scheduler.py Scheduler._note_duration
      via: "end instant taken first in the existing finally; called after _note, before _wait"
    - from: src/live/wiring.py LiveWiring (Scheduler construction, today line 984)
      to: src/live/wiring.py LiveWiring._record_task_duration -> src/live/wiring_parts.py task_duration_journal -> self.record
      via: "record_duration keyword argument"
    - from: config/execution/execution-limits-v1.toml [scheduler]
      to: ExecutionLimits.scheduler_duration_summary_interval -> LiveCadences.duration_summary_interval -> Scheduler duration_summary_interval
      via: "LiveCadences.from_limits; unset = None = new-maximum rows only"
---

<objective>
Owner-approved: give the owner a measured basis for `scheduler.protection_stall_after_ms` (D111) by recording how long each live scheduler run takes, with a bounded journal volume, observe-only, never an alert. This plan does NOT choose the stall value, and it does not choose a value for the new window key either.

Design (decided here; executor implements exactly this):

1. What is measured. In `Scheduler._loop` (src/live/scheduler.py:184-200) the start instant already exists (`started = self._clock()`, :186). The end instant is taken as the first statement of the existing `finally` block (:195), before the watchdog is cancelled, so the duration is the run only. Duration in integer milliseconds = (end - start) floor-divided by a one-millisecond timedelta (precedent: src/live/runtime.py:317), clamped at 0 when the clock stepped back. Every run that ends is counted, ok or failed; a `CancelledError` propagates before the record (not counted), as today for `_note`.
2. What is kept. Per task, in memory, since process start: `runs`, `total_ms`, `max_ms` (int), plus `window_max_ms` (the longest run since the window started) and `window_started` (the start of the task's first run, then the end of the run that closed the previous window).
3. When a row is written: at most ONE row per run end, as a `TaskDurationSummary`, when (a) the run sets a new maximum (strictly greater than every earlier run of this process; the first run of a task is one), or (b) the window key is set and (run end - window_started) >= the interval; then the window restarts at that run end. One row can carry both flags.
4. Why this is bounded (justification for D112 and the SUMMARY). (a) New-maximum rows: per task the count is the number of record values of the run durations. For independent durations the expected count over n runs is the harmonic number H(n), about ln(n) + 0.58: a task on the 15 s tick (`reconcile.tick_interval_ms` = 15000) makes 5,760 runs a day, so about 9 rows on its first day and about 13 over 30 days; integer-ms ties (strictly greater required) only lower it. The only way to get one row per run is every run being strictly longer than all before it, and those rows are then exactly the slowdown evidence the owner needs; the count can never exceed the number of runs, and a restart adds one first-run row per task. (b) Window rows: at most one per run AND at most one per window, so per task at most floor(uptime / interval) + 1 per process; the live process has 13 scheduler tasks (src/live/wiring.py:1111-1137), so at most 13 x (86,400,000 / interval_ms + 1) window rows a day. A value at or below the 15 s tick gives at most one row per run; choosing the value is the owner's. For scale only: the health tick already writes about 63,000 journal rows a day (RUNBOOK 22.7, R-25).
5. Default when the window key is unset (the shipped state): new-maximum rows only. This already delivers the one number the stall rule needs (the longest observed run per task, never lost because the row is immediate), with no limits edit on the Demo host.
6. Window key: `scheduler.duration_summary_interval_ms`, in the existing `[scheduler]` section after `protection_stall_after_ms`, field `scheduler_duration_summary_interval_ms`, property `scheduler_duration_summary_interval` (timedelta or None), shipped `NOT_CONFIGURED` with provenance `NOT_CONFIGURED`, TEST_ONLY value None. It follows the pattern of `scheduler.protection_stall_after_ms` (D111, quick 261114-mp1) in every respect except one, on purpose: it goes into `OPTIONAL_REFINEMENT_LIMIT_KEYS` (src/execution/execution_limits.py:136), not `ALERT_ONLY_LIMIT_KEYS` (:126). Reason: it switches no alert (constraint: not an alert), and the optional-refinement contract ("refines a behaviour that already has a safe fallback") is exactly this case: the fallback is new-maximum rows only. Both sets have the same loader effect (never refused, never in `unset_keys`), and neither listing method has a production caller (only tests call `unset_alert_only_keys` / `unset_optional_refinement_keys`). No existing key was reused as the window: the only candidates (`reconcile.lot_filter_refresh_interval_ms`, `account.max_daily_loss_age_ms`, `alerts.dedupe_window_ms`) mean something else, and a later owner change to them would silently change this record; D-12 reuse (plan 24-37) requires the same kind of check.
7. Journal row: new event type `LIVE_TASK_DURATION` (constant `EVENT_TASK_DURATION`), entity_type `LiveScheduler`, entity_id the task name, correlation_id `live_scheduler` (same as `task_event_journal`, src/live/wiring_parts.py:226-247), compact sorted JSON payload with exactly `max_ms`, `new_max`, `runs`, `task`, `total_ms`, `window_end`, `window_max_ms`; journal id by `content_hash_event_id(prefix="live_task_duration", ...)`. `TaskEvent` and `TaskEventKind` (src/live/scheduler.py:57, :87-94) are NOT changed, so `alert_task_stall` (src/live/wiring_parts.py:256) can never see a duration row and no kind pin moves.
8. Observe only: the record call is wrapped like `_note` (:246-251): any `Exception` is logged by class name and swallowed; the counters are updated before the write, so a failed write loses that row only, never the counts. No row is written at stop (the max is never lost: its row is immediate).

Purpose: the owner sets the stall bound from measured data (RUNBOOK 22.8), not by trial and error.
Output: Task 1 commit (code, key, tests, pins), Task 2 commit (D112, DOC_STATUS, GLOSSARY, RUNBOOK 22.7/22.8), Task 3 gates and SUMMARY (no commit).

Shape: the owner fixed the shape (code+tests one commit, docs one commit, gates+SUMMARY). Task 1 is itself the end-to-end slice (limits key -> cadence -> scheduler -> wiring -> journal row), test-first; it touches 13 files because the key and every pinned count must land in the same commit to keep each commit green (the mp1/k46 lesson: a key added without its pins left tests/test_phase18_gate.py red for a day).
</objective>

<execution_context>
@~/.claude/gsd-core/workflows/execute-plan.md
@~/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@AGENTS.md
@.planning/quick/261114-mp1-follow-ups-to-kxu-cancel-resting-entry-o/261114-mp1-SUMMARY.md
@.planning/quick/261115-k46-robust-invariant-6-gate-test-clarify-one/261115-k46-SUMMARY.md

Rules for the executor (AGENTS.md and the owner brief):
- Run `codegraph explore "<symbol>"` (shell form; the MCP server is down) before reading code you need to locate.
- Never push or merge. Stage explicit paths only. Leave `.planning/STATE.md`, `.planning/config.json`, `.planning/REQUIREMENTS.md`, `.planning/state.json` (owner-modified) and every untracked file alone.
- Commit trailer exactly: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Always `uv run`. Run only the tests named in this plan. No full suite, no `-m demo`, no `--execute` script. A `*_pg.py` file only if `TEST_DATABASE_URL` is already set in the process environment (never read `.env`).
- Decimal/int only, no float; no wall clock in `src/live` (the clock is injected; tests/test_live_ast_guards.py); tests/test_phase24_gate.py invariant 1 forbids the float constructor anywhere in `src/live`. Do not write the float constructor text (the word float followed by an opening parenthesis) even inside a comment or docstring of a touched `src` file: the grep gate below counts it.
- No number may be chosen for `scheduler.duration_summary_interval_ms` or `scheduler.protection_stall_after_ms`, in code, config, tests' shipped-file expectations or docs. Tests use TEST_ONLY numbers through overrides only.

Line endings at HEAD a3efe138 (CRLF count = line count, all CRLF in the working tree, `core.autocrlf=true`): src/live/scheduler.py 375, src/live/wiring_parts.py 385, src/live/wiring.py 1550, src/execution/execution_limits.py 486, config/execution/execution-limits-v1.toml 117, config/execution/README.md 155, tests/support/execution_limits.py 124, tests/test_live_scheduler.py 705, tests/test_live_wiring_parts.py 555, tests/test_live_wiring.py 660, tests/test_execution_limits.py 1199, tests/test_no_unratified_defaults.py 428, tests/test_phase18_gate.py 647, docs/DECISIONS.md 115, docs/DOC_STATUS.md 95, docs/GLOSSARY.md 649, docs/operations/RUNBOOK.md 1237. Re-measure before editing (`grep -c $'\r$' f` and `wc -l < f`); edit bytes-aware (a throwaway helper in your scratchpad, run with `uv run python`, that reads bytes, keeps each file's line ending, asserts each anchor is found exactly once); record before/after in the SUMMARY. If the Edit tool is used on a CRLF file, re-check the counts right after.

Facts read for this plan (verify each against the code; cite file:line in the SUMMARY):
- src/live/scheduler.py: `TaskEventKind` :57; `TaskSpec` :60-84; `TaskEvent` :87-94; `_TaskState` :113-119; `Record` :122; `Scheduler.__init__` :128-147 (keyword-only); `_loop` :184-200 (start :186, finally :195-198, `_note` :199, `_wait` :200); `_record_stall` :215-221 and `_note` :223-251 swallow `Exception` and log the class name; `LiveCadences` :276-363 with the only defaulted field `protection_stall_after` :302 and `from_limits` :310-363; `__all__` :366-375. `total_seconds` appears twice today (:256 and :308).
- src/live/wiring_parts.py: `EVENT_TASK = "LIVE_TASK_EVENT"` :53; `task_event_journal` :226-247 (compact sorted JSON, `content_hash_event_id(prefix="live_task", ...)`, entity_type `LiveScheduler`, correlation `live_scheduler`); `alert_task_stall` :256-275; module docstring bullets :5-18; `__all__` :365-385.
- src/live/wiring.py: imports from wiring_parts :131-142; `self.record = self.db_writes.track(write_journal)` :535; `Scheduler(clock=clock, sleep=self.sleep, record=self._record_task, specs=specs)` :984; `_record_task` :1028-1034; `_specs` :1038-1137 (13 TaskSpecs; protection gets `stall_after_seconds` :1117).
- src/execution/execution_limits.py: module docstring :1-44 (key story :14-22); `EXECUTION_LIMIT_KEYS` :58-85 (`"scheduler": ("protection_stall_after_ms",)` :83); `EXECUTION_LIMIT_FIELDS` :93-118 (:116); `ALERT_ONLY_LIMIT_KEYS` :120-128; `OPTIONAL_REFINEMENT_LIMIT_KEYS` :130-136; class docstring ends :238-244 ("The file holds twenty-two keys: nineteen required, two alert-only, one optional."); last field :267; properties :269-279; the loader builds `ExecutionLimits(**flat)` generically from the key table (:428).
- config/execution/execution-limits-v1.toml: header key list :4-22 and the "except" paragraph :27-35; `[scheduler]` :76-77; `[provenance.scheduler]` :116-117; `protection.max_unprotected_ms = 180000` :40 (D089).
- config/execution/README.md: `[scheduler]` section :111-115 ("The one key of this section is ALERT ONLY ..."), "Still NOT_CONFIGURED" bullets :151-155. tests/test_execution_limits.py:470 `_KEY_LINE` requires one `- \`section.key\` - ...` bullet per key in table order; :487 forbids a key name followed by `=`/`:` and a digit.
- Journal table `journal_events`, `payload_json` is `sa.String()` (src/db/alembic/versions/0002_domain_registry.py:212), so `payload_json::jsonb` is a valid PostgreSQL cast.
- Production clock is `datetime.now(UTC)` (src/live/runtime.py:161-162): durations are differences of that clock (an NTP step can distort one sample; stated in the docs).
- Pins found (update each, with a history comment): tests/test_no_unratified_defaults.py:224 and tests/test_phase18_gate.py:534 (`== 66`); tests/test_execution_limits.py :426-452 (all-unset round trip: kwargs list and both unset tuples), :518 (NOT_CONFIGURED count 4), :552 (`OPTIONAL_REFINEMENT_LIMIT_KEYS == {BAN_END_MARGIN_KEY}`), :598 (`len(set(values.values())) == len(values)` breaks with two None values), :897-898 (key count 22 and the margin slice), :1045 and :1064 (`== (BAN_END_MARGIN_KEY,)`), :1073 (`== ()` with TEST_ONLY values), :1119 (scheduler key tuple); tests/test_live_scheduler.py:667-676 (skips only `protection_stall_after`). Tests that stay valid unchanged (checked): the phase 19/20/21/22 gates over the limits file, tests/test_live_limits_relationships.py, tests/test_execution_limits.py :1026-1033, :1118-1199 except :1119.
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Bounded per-run duration record, optional window key, tests and pins (one commit)</name>
  <files>src/live/scheduler.py, src/live/wiring_parts.py, src/live/wiring.py, src/execution/execution_limits.py, config/execution/execution-limits-v1.toml, config/execution/README.md, tests/support/execution_limits.py, tests/test_live_scheduler.py, tests/test_live_wiring_parts.py, tests/test_live_wiring.py, tests/test_execution_limits.py, tests/test_no_unratified_defaults.py, tests/test_phase18_gate.py</files>
  <read_first>src/live/scheduler.py (whole), src/live/wiring_parts.py:1-60 and :220-276, src/live/wiring.py:975-1040, src/execution/execution_limits.py:1-140 and :230-311, tests/test_live_scheduler.py:1-112, :293-450 and :660-705, tests/test_live_wiring.py:576-640, tests/test_live_wiring_parts.py:330-360, tests/test_execution_limits.py:96-128, :1026-1199, tests/support/execution_limits.py:26-84, tests/support/virtual_time.py</read_first>
  <behavior>
    Scheduler (tests/test_live_scheduler.py, new section headed "Quick task 261115-kra (D112)", virtual time, `Scheduler(..., record_duration=<recording async fn>, duration_summary_interval=...)`; a task "runs" for a duration by awaiting the injected `time.sleep`):
    - First run of 2.5 s: exactly one summary, runs 1, total_ms 2500, max_ms 2500, window_max_ms 2500, new_max True, window_end False, at_utc = start + 2.5 s; every numeric field is a plain int (not bool), every flag a bool.
    - Whole ms floored: a run of 2.5009 s gives 2500.
    - Durations 1.0, 0.5, 1.5, 1.5 s with no window: rows only after runs 1 and 3 (an equal run is not a new maximum); the second row has runs 3, total_ms 3000, max_ms 1500.
    - No window, 20 equal runs: exactly one row (the first run).
    - Window 60 s, interval 15 s, durations with one long run in the first window and short runs after: a window row (window_end True, new_max False) at the first run end at least 60 s after the first run's start; the next window row carries a smaller window_max_ms than max_ms (window max restarted); a run that both closes the window and is a new maximum writes ONE row with both flags True.
    - No runs, no rows: a task whose only run never ends writes no summary; a scheduler built without `record_duration` never calls anything new.
    - A failed run (raises ValueError after 1 s) is timed (runs 1, max_ms 1000); a run cancelled by cancelling `scheduler.run()` writes no summary.
    - A `record_duration` that raises RuntimeError: the loop keeps running, the TaskEvent journal still gets its rows, the next summary carries the counts including the run whose write failed, and the log line names "RuntimeError" without the exception message (caplog).
    - Observe only: two identical virtual-time runs, one with and one without `record_duration` (and with a window), give identical `time.sleeps`, identical TaskEvent kinds and identical `results()`.
    - A clock that steps back (scripted clock: end earlier than start) records 0 ms, never a negative number.
    - `duration_summary_interval` of zero or negative raises ValueError.
    - Cadences: unset key -> `LiveCadences.duration_summary_interval is None` and `from_limits` does not refuse; TEST_ONLY override `scheduler_duration_summary_interval_ms=6262` -> `timedelta(milliseconds=6262)`; an unset tick still refuses naming only `reconcile.tick_interval_ms`.
    Journal row (tests/test_live_wiring_parts.py):
    - `task_duration_journal(summary)` has event_type "LIVE_TASK_DURATION", entity_type "LiveScheduler", entity_id the task, correlation_id "live_scheduler", occurred_at_utc = summary.at_utc, payload_json exactly the compact sorted JSON of the seven keys (assert the literal string for one example); json.loads of the payload gives ints for the four numbers.
    - Same summary -> same journal_event_id; a summary differing only in runs -> a different id.
    - Not an alert: "LIVE_TASK_DURATION" not in `ALERT_EVENTS`, not in `EVENT_WORDING`, not an `OPS05_MATRIX` alert.
    Production path (tests/test_live_wiring.py):
    - With `handles.assembly.record` replaced by a recorder, `await handles.assembly._record_task_duration(summary)` journals exactly `[task_duration_journal(summary)]` and the alert sink queue stays empty.
    - The built scheduler carries the production recorder and the cadence window: `complete.scheduler._record_duration == handles.assembly._record_task_duration`; `complete.scheduler._duration_summary_interval is None` with the default limits; after `dataclasses.replace(cadences, duration_summary_interval=timedelta(milliseconds=6262))` it equals that timedelta.
    Limits (tests/test_execution_limits.py, new section after the stall-key section, mirroring :1118-1199): key declared second in `scheduler` with its prefixed field; in OPTIONAL_REFINEMENT and not in ALERT_ONLY (the two sets stay disjoint); the committed file leaves it NOT_CONFIGURED with label NOT_CONFIGURED, `unset_optional_refinement_keys() == (BAN_END_MARGIN_KEY, SUMMARY_KEY)`, `require_live_ready()` passes; `require_live_ready` never names it; a TEST_ONLY override loads as ms and timedelta; a positive int loads, PLACEHOLDER is refused naming the key, an int with label NOT_CONFIGURED is refused; the malformed list [0, -1, 1.5, True, False, "250", "not_configured", ""] is refused naming the key; a document without `scheduler` names both scheduler keys.
  </behavior>
  <action>
RED first. Write every test of the behavior list and every pin update below, run the verify set, and save the failing output for the SUMMARY (expected: collection ImportError for `TaskDurationSummary` / `task_duration_journal`, KeyError for the new key, count mismatches). Then implement:

src/live/scheduler.py (per D112, design points 1-8 of the objective):
- New frozen dataclass `TaskDurationSummary` with fields task (str), at_utc (datetime), runs, total_ms, max_ms, window_max_ms (int), new_max, window_end (bool), docstring naming D112; alias `RecordDuration = Callable[[TaskDurationSummary], Awaitable[None]]` beside `Record`; both added to `__all__`.
- A private mutable per-task state (runs, total_ms, max_ms or None before the first run, window_started or None, window_max_ms), kept in a dict keyed by task name like `self._state`. A module constant one-millisecond timedelta is the divisor (a unit, not a cadence).
- `Scheduler.__init__` gains keyword-only `record_duration: RecordDuration | None = None` and `duration_summary_interval: timedelta | None = None`; a non-positive interval raises ValueError naming `duration_summary_interval`. With `record_duration` None nothing is accumulated and nothing new is awaited, so every existing caller (src/live/wiring.py:984 until changed, tests/test_live_stream_to_protection.py:304) behaves exactly as before.
- `_loop`: the end instant is the first statement of the existing finally block (before the watchdog cancel); after `await self._note(...)` add `await self._note_duration(spec.name, started, ended)`; `_wait` stays last.
- `_note_duration`: return at once when `record_duration` is None; elapsed = (ended - started) floor-divided by the one-millisecond timedelta, clamped at 0; initialise window_started to `started` on the first run; update runs, total_ms, window_max_ms; new_max when max_ms is None or elapsed is strictly greater; window_end only when an interval is set and (ended - window_started) is at least the interval (timedelta comparison, no seconds conversion); return when neither; otherwise build the summary with at_utc=ended, then (if window_end) restart the window at `ended` with window_max_ms 0, then await the writer inside try/except Exception that logs `"scheduler duration record failed for %s: %s"` with the task name and the exception class name only, never re-raising.
- Module docstring: a "Duration record (D112)" paragraph (what is timed, the two triggers, one row per run at most, the bound, observe only, not an alert, unset key = new-maximum rows only). `LiveCadences`: new field `duration_summary_interval: timedelta | None = None` after `protection_stall_after`, filled by `from_limits` from `execution_limits.scheduler_duration_summary_interval` and never refused when unset (comment like :361); update the class docstring sentence that calls `protection_stall_after` the only defaulted field (now two optional fields; neither default is a number).

src/live/wiring_parts.py: `EVENT_TASK_DURATION = "LIVE_TASK_DURATION"` next to `EVENT_TASK`; `task_duration_journal(summary: TaskDurationSummary) -> JournalEvent` built exactly like `task_event_journal` (same entity_type, correlation, json.dumps sort_keys and compact separators) with prefix "live_task_duration" and the seven payload keys; a docstring bullet in the module list (D112, observe only, never an alert); both names in `__all__`. Do not touch `alert_task_stall`.

src/live/wiring.py: import `task_duration_journal`; the Scheduler construction gains `record_duration=self._record_task_duration` and `duration_summary_interval=self.cadences.duration_summary_interval`; new `async def _record_task_duration(self, summary: Any) -> None` right after `_record_task`, whose body only awaits `self.record(task_duration_journal(summary))`, with a comment: D112, observe only, never an alert (no sink call), a write failure propagates to the scheduler which logs it by class name.

src/execution/execution_limits.py: `"scheduler": ("protection_stall_after_ms", "duration_summary_interval_ms")`; `EXECUTION_LIMIT_FIELDS` entry `"scheduler.duration_summary_interval_ms": "scheduler_duration_summary_interval_ms"`; add the key to `OPTIONAL_REFINEMENT_LIMIT_KEYS` and extend the comment above it (unset: only the new-maximum duration rows are written, D112; no number chosen); last dataclass field `scheduler_duration_summary_interval_ms: int | None` (no default); property `scheduler_duration_summary_interval` like :275-279; module and class docstrings: one sentence each for the new key (quick 261115-kra, D112, OPTIONAL REFINEMENT) and the count sentence becomes twenty-three keys: nineteen required, two alert-only, two optional.

config/execution/execution-limits-v1.toml: `duration_summary_interval_ms = "NOT_CONFIGURED"` under `[scheduler]` and under `[provenance.scheduler]`, each right after the stall key; one header key-list line ("Quick 261115-kra, D112 (OPTIONAL): window of the scheduler duration summary rows; unset, only new-maximum rows") and one clause in the "except" paragraph (only refines the duration record, so while NOT_CONFIGURED only the new-maximum rows are written and nothing else changes). No number anywhere.

config/execution/README.md: `[scheduler]` heading adds "quick task 261115-kra; DECISIONS D112"; the intro paragraph describes two keys (the first ALERT ONLY, the second OPTIONAL via `OPTIONAL_REFINEMENT_LIMIT_KEYS`, listed by `unset_optional_refinement_keys()`); a bullet `- \`scheduler.duration_summary_interval_ms\` - OPTIONAL: ...` right after the stall bullet (meaning, unset = new-maximum rows only, set = also one window row per task per interval, at most one row per run, never an alert, a value needs a DECISIONS row and the provenance DECISION, milliseconds); one "Still NOT_CONFIGURED" bullet starting "- The key `scheduler.duration_summary_interval_ms`". Grep the README for other sentences the new key makes false and fix them.

tests/support/execution_limits.py: `"scheduler.duration_summary_interval_ms": None` with a comment (D112: optional and unset like the shipped file, so no wiring test writes window rows; override `scheduler_duration_summary_interval_ms=...`).

Pin updates (each with a short history comment): tests/test_no_unratified_defaults.py:224 and tests/test_phase18_gate.py:534 `66` -> `68` (key text `duration_summary_interval_ms` and field `scheduler_duration_summary_interval_ms`; add both names to the subset assertion at :225-226); tests/test_execution_limits.py: add `SUMMARY_KEY`/`SUMMARY_FIELD` constants beside `STALL_KEY`; :426-452 add the new field to the all-unset kwargs and expect `(BAN_END_MARGIN_KEY, SUMMARY_KEY)`; :518 `4` -> `6`; :552 the set gains `SUMMARY_KEY`; :598 compare only the non-None values; :897 `22` -> `23` and :898 slice shifted by one; :1045 and :1064 `(BAN_END_MARGIN_KEY, SUMMARY_KEY)`; :1073 `(SUMMARY_KEY,)`; :1119 the two-key tuple; tests/test_live_scheduler.py:671-673 skip both optional fields. Run each whole affected file afterwards and fix any further pin the run reveals (record it as a deviation).
  </action>
  <verify>
    <automated>uv run pytest tests/test_live_scheduler.py tests/test_live_wiring_parts.py tests/test_live_wiring.py tests/test_execution_limits.py tests/test_no_unratified_defaults.py tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_phase20_gate.py tests/test_phase21_gate.py tests/test_phase22_gate.py tests/test_phase24_gate.py tests/test_live_ast_guards.py tests/test_live_limits_relationships.py tests/test_reconcile_stale_entry.py tests/test_live_stream_to_protection.py tests/test_alerts.py tests/test_alert_wording.py tests/test_alerts_ops05_matrix.py -m "not docker" -n 4 -q && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src && uv run python scripts/verify_decision_alignment.py all</automated>
  </verify>
  <acceptance_criteria>
    - Baseline: the verify pytest set run at HEAD a3efe138 before any edit, counts recorded; RED output recorded; after GREEN the set passes with no new failure.
    - `grep -c -F 'float(' src/live/scheduler.py src/live/wiring_parts.py src/live/wiring.py src/execution/execution_limits.py` = 0 in each (HEAD a3efe138: none in any of the four).
    - `grep -o -F 'total_seconds()' src/live/scheduler.py | wc -l` = 2 (HEAD: 2, lines 256 and 308; no new seconds conversion).
    - `grep -n 'class TaskDurationSummary' src/live/scheduler.py`, `grep -n 'def task_duration_journal' src/live/wiring_parts.py`, `grep -n 'record_duration=self._record_task_duration' src/live/wiring.py` and `grep -n 'duration_summary_interval=self.cadences.duration_summary_interval' src/live/wiring.py` each print exactly one line (HEAD: none of the four exists).
    - `grep -v '^#' config/execution/execution-limits-v1.toml | grep -o duration_summary_interval_ms | wc -l` = 2 (HEAD: none); `grep -o -F '"NOT_CONFIGURED"' config/execution/execution-limits-v1.toml | wc -l` = 6 (HEAD: 4).
    - <!-- planner-discipline-allow: LIVE_TASK_DURATION --> The alert modules never name the new event type: `grep -c 'LIVE_TASK_DURATION' src/ops/alerts.py src/ops/alert_wording.py` = 0 in each (region-scoped to those two files; the literal legitimately appears in src/live/wiring_parts.py).
    - After the commit, `git show --stat --format= HEAD` lists exactly the 13 Task 1 files; CRLF = LF in every one.
    - One commit `feat(quick-261115-kra): bounded per-run duration record of the live scheduler tasks` with the Sonnet 5.5 trailer.
  </acceptance_criteria>
  <done>Every scheduler run that ends is timed in integer ms; at most one LIVE_TASK_DURATION row per run (new maximum always; window rows only with the optional key set); unset key = new-maximum rows only; the production record path writes the row and never alerts; every pin updated; the verify set, ruff, mypy and the decision gate pass; committed.</done>
</task>

<task type="auto">
  <name>Task 2: D112, DOC_STATUS, GLOSSARY and RUNBOOK 22.7/22.8 measurement procedure (one commit)</name>
  <files>docs/DECISIONS.md, docs/DOC_STATUS.md, docs/GLOSSARY.md, docs/operations/RUNBOOK.md</files>
  <read_first>docs/DECISIONS.md:3 and :115 (D111 row as the layout template), docs/DOC_STATUS.md:90-95, docs/GLOSSARY.md:206-212 and :320-325, docs/operations/RUNBOOK.md:1185-1237, and the Task 1 diff (for exact names and lines)</read_first>
  <action>
Re-read the committed Task 1 code first and take every name and line from it, not from this plan. Edit bytes-aware (CRLF).

docs/DECISIONS.md: append row D112 directly after D111 (DC-02 needs contiguous ids; tests/test_phase20_gate.py invariant 6 needs consecutive ids after D107), same four columns and exactly 5 pipes (no pipe character inside any cell, so no SQL in this row). Decision column: per-run duration record of the live scheduler tasks, bounded LIVE_TASK_DURATION summary rows, optional window key `scheduler.duration_summary_interval_ms` shipped NOT_CONFIGURED; observe only, not an alert. Status: Accepted (2026-11-15, owner approval; quick task 261115-kra). Rationale items: (1) problem (D111's bound had no measured basis; the journal held no per-run duration). (2) What is timed: injected scheduler clock, whole ms floored, negative counts as 0, failed runs counted, cancelled runs not, all 13 tasks. (3) Rows and triggers: at most one row per run end; new maximum always (first run included); window row only with the key set; payload keys; event type, correlation, entity. (4) Volume bound: the record-value argument (expected about ln(n) + 0.58 new-maximum rows per task over n runs; about 9 on the first day of a 15 s task), window rows at most floor(uptime / interval) + 1 per task per process and at most one per run, the 13-task formula; no number chosen. (5) The key: OPTIONAL REFINEMENT (why not alert-only, why no existing key reused), unset = new-maximum rows only, a value needs its own DECISIONS row and provenance DECISION. (6) Observe only: no behavior change, writer failure logged by class name and swallowed, no cancel, not in ALERT_EVENTS, TaskEvent kinds unchanged, no row at stop. (7) Use: RUNBOOK 22.8; the value of `scheduler.protection_stall_after_ms` stays the owner's (D111 item 5), longest observed run times an owner margin, below `protection.max_unprotected_ms`.

docs/DOC_STATUS.md: one change-log line after the last one: "2026-11-15 — `DECISIONS.md` D112 recorded (owner approval 2026-11-15, quick task 261115-kra): ..." naming the documents amended (`GLOSSARY.md` 9.3 row, `operations/RUNBOOK.md` 22.7 and 22.8) and the config README.

docs/GLOSSARY.md: one row in the 9.3 table (columns Code / Emitted in / Meaning / Status): `LIVE_TASK_DURATION`, emitted in `src/live/wiring_parts.py` (`task_duration_journal`, written by `LiveWiring._record_task_duration` for a `TaskDurationSummary` of `src/live/scheduler.py`); meaning: the journal event type of one bounded duration summary of a live scheduler task (payload keys; new-maximum and window triggers); status: journal event type (D112), not a rejection reason, not an alert, not a SAFE_MODE reason.

docs/operations/RUNBOOK.md:
- 22.7: one bullet after the stall-key bullet: the value of `scheduler.duration_summary_interval_ms` is the owner's; it ships NOT_CONFIGURED, so only the new-maximum duration rows are written (section 22.8, D112).
- 22.8 (keep the heading byte-identical): the Status line also names quick task 261115-kra and D112. Add a paragraph "**The duration record (D112).**": every run of every scheduler task that ends is timed in whole ms from the process clock; one `LIVE_TASK_DURATION` row (correlation `live_scheduler`, entity the task name) at most per run, at each new maximum of the process and, with `scheduler.duration_summary_interval_ms` set, once per window; payload keys and their meaning (`runs`, `total_ms`, `max_ms` count since the process started and restart at zero after a restart; `window_max_ms`; `new_max`, `window_end`); observe only, never an alert; a run that never ends is not in it (the stall watchdog covers that); the clock is the wall clock, so an NTP step can distort one sample.
- Replace the paragraph that starts "**Measuring a bound" and everything after it to the end of 22.8: remove the transitions proxy query with its reading note, the five-step trial-bound procedure and the closing sentence about an unbuilt record. New content: keep the existing stall-rows query (as query 1, text unchanged); query 2, read-only, the longest observed run and the row count per task: SELECT entity_id AS task, MAX((payload_json::jsonb ->> 'max_ms')::bigint) AS longest_run_ms, COUNT(*) AS duration_rows FROM journal_events WHERE correlation_id = 'live_scheduler' AND event_type = 'LIVE_TASK_DURATION' GROUP BY entity_id ORDER BY entity_id; query 3, read-only, the history of the protection task: SELECT occurred_at_utc, payload_json FROM journal_events WHERE correlation_id = 'live_scheduler' AND entity_id = 'protection_step' AND event_type = 'LIVE_TASK_DURATION' ORDER BY occurred_at_utc (each in a sql fence like the existing query; say a session filter on occurred_at_utc may be added). Then the owner procedure (owner-run Demo only, never an agent): run Demo sessions that exercise the protection step (fills, stop placement, restarts, take-profit attach) with the shipped image, no limits edit needed; read the protection_step row of query 2; the rule: bound = longest observed run of `protection_step` times a margin the owner chooses, and it must stay below `protection.max_unprotected_ms` (180000 ms, `config/execution/execution-limits-v1.toml`, D089) or the alert cannot fire before the unprotected deadline; if longest times margin is not below 180000 ms, do not set it and treat the slow protection run as the finding; adopt it with a DECISIONS row and provenance DECISION, then rebuild and re-pin the image (D106). No number is proposed for the bound or for the window.
Write down, for the SUMMARY, a table of every claim in the new 22.8 text with the file:line that backs it (scheduler timing and triggers, payload keys, event type/correlation/entity, observe-only and no-alert path, the 180000 value, the jsonb cast on a String column, the production clock).
  </action>
  <verify>
    <automated>uv run python scripts/verify_decision_alignment.py all && uv run pytest tests/test_phase20_gate.py tests/test_decision_alignment_bookkeeping.py tests/test_execution_limits.py -m "not docker" -q</automated>
  </verify>
  <acceptance_criteria>
    - <!-- planner-discipline-allow: LIVE_TASK_DURATION --> <!-- planner-discipline-allow: 180000 --> <!-- planner-discipline-allow: payload_json::jsonb --> These three literals are deliverables of this task (positive gates only; at HEAD a3efe138 none of them occurs in RUNBOOK, DECISIONS, DOC_STATUS or GLOSSARY, except one 180000 inside an older DECISIONS row).
    - `grep -o '^| D112 |' docs/DECISIONS.md | wc -l` = 1 (HEAD: none) and that line has exactly 5 pipe characters (the D111 line has 5).
    - `grep -n -F '261115-kra' docs/DOC_STATUS.md` prints at least one line; `grep -n -F 'LIVE_TASK_DURATION' docs/GLOSSARY.md` prints exactly one table row.
    - RUNBOOK: `grep -c -F 'LIVE_TASK_DURATION' docs/operations/RUNBOOK.md` >= 3; `grep -c -F '180000' docs/operations/RUNBOOK.md` >= 1; `grep -c -F 'payload_json::jsonb' docs/operations/RUNBOOK.md` >= 1; `grep -c -F 'Read-only query 2, the protection transitions' docs/operations/RUNBOOK.md` == 0 (HEAD: 1); `grep -c -F 'A per-run duration record would make this direct' docs/operations/RUNBOOK.md` == 0 (HEAD: 1); `grep -c -F 'lower the bound until the first stall rows appear' docs/operations/RUNBOOK.md` == 0 (HEAD: 1); `grep -n '^### 22.8 TASK_STALLED and the protection stall bound (D111)' docs/operations/RUNBOOK.md` prints one line (heading unchanged); no `##`/`###` heading changed (compare `grep -n '^##' docs/operations/RUNBOOK.md` before and after).
    - CRLF = LF in all four files; after the commit `git show --stat --format= HEAD -- src tests config` prints nothing.
    - One commit `docs(quick-261115-kra): D112 duration record and the RUNBOOK 22.8 measurement` with the Sonnet 5.5 trailer. If a gate fails only because code and docs are in separate commits, fold as the brief allows and record it.
  </acceptance_criteria>
  <done>D112, the DOC_STATUS line, the GLOSSARY row and RUNBOOK 22.7/22.8 describe exactly the committed code; 22.8 gives read-only SQL over LIVE_TASK_DURATION rows and the rule below 180000 ms; the proxy workaround is gone; the decision gate passes; committed.</done>
</task>

<task type="auto">
  <name>Task 3: Final gates and SUMMARY (no commit)</name>
  <files>.planning/quick/261115-kra-per-run-duration-record-for-live-schedul/261115-kra-SUMMARY.md</files>
  <read_first>.planning/quick/261115-k46-robust-invariant-6-gate-test-clarify-one/261115-k46-SUMMARY.md (format)</read_first>
  <action>
Run once, after both commits, one heavy process at a time: `uv run ruff check`; `uv run ruff format --check`; `uv run mypy src`; `uv run python scripts/verify_decision_alignment.py all`; the Task 1 pytest set; then the live sweep `uv run pytest tests/test_live_*.py -m "not docker" -n 4 -q` (the two `*_pg.py` files run only if `TEST_DATABASE_URL` is set in the process environment; otherwise they skip, say so). Record counts (passed/failed/skipped/xfailed) for each.

Write the SUMMARY in the k46 format: frontmatter (phase quick-261115-kra, plan 01, status, commits 2, plan_head_before a3efe138..., plan_head_after, actuals measured with git); commits table; the design as built (triggers, default, key placement and why OPTIONAL REFINEMENT, the volume bound with the numbers of the objective, the payload); RED and GREEN evidence; every pin changed with old -> new; CRLF before/after table for all 17 files; the 22.8 claim table with file:line; final gate results; deviations; not run (full suite, docker, `-m demo`, `--execute`, any `*_pg.py` that skipped); residuals for the owner: AGENTS.md "Still open (owner)" does not name the new key (gated file, not edited); the values of `scheduler.protection_stall_after_ms` and `scheduler.duration_summary_interval_ms` remain the owner's; nothing observed on Demo or a host; Self-Check (commits are ancestors of HEAD, nothing staged, owner-modified files still unstaged, untracked files untouched). Do not commit the SUMMARY.
  </action>
  <verify>
    <automated>uv run ruff check && uv run ruff format --check && uv run mypy src && uv run python scripts/verify_decision_alignment.py all && uv run pytest tests/test_live_*.py -m "not docker" -n 4 -q</automated>
  </verify>
  <acceptance_criteria>
    - All gates above pass (or every failure is shown to exist at HEAD a3efe138 with the same message, recorded).
    - `git rev-list --count a3efe138..HEAD` = 2; `git status --porcelain` shows no staged entry; `.planning/STATE.md`, `.planning/config.json`, `.planning/REQUIREMENTS.md`, `.planning/state.json` still modified and unstaged.
    - The SUMMARY file exists, carries the claim table and the CRLF table, and is not committed.
  </acceptance_criteria>
  <done>Gates recorded green after both commits; SUMMARY written with evidence, residuals and self-check; nothing pushed, nothing staged.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| scheduler loop -> journal (PostgreSQL via `self.record`) | a new write path inside every task loop, including the protection loop |
| journal payload -> operator (RUNBOOK SQL, Telegram never) | what a row may disclose; only integers, booleans and the task name |
| limits file -> scheduler | a new optional key that changes only the row cadence |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-kra-01 | Denial of service | journal volume from `_note_duration` | medium | mitigate | at most one row per run end; new-maximum rows only by default (expected about ln(n) + 0.58 per task); window rows at most floor(uptime / interval) + 1 per task and at most one per run; tests: 20 equal runs give one row, window rows once per window |
| T-kra-02 | Tampering (behavior change of the protection loop) | `Scheduler._loop` / `_note_duration` | high | mitigate | writer wrapped in try/except Exception logging the class name; counters updated in memory only; no cancel, no new await in the run itself; test proves identical sleeps, TaskEvent kinds and results with and without the record |
| T-kra-03 | Information disclosure | `task_duration_journal` payload, warning log | low | mitigate | payload is the task name plus four ints and two bools; the log line carries the task name and the exception class name only; literal payload asserted in a test |
| T-kra-04 | Spoofing / alert fatigue | alert contract | medium | mitigate | `LIVE_TASK_DURATION` kept out of `ALERT_EVENTS`, `EVENT_WORDING`, `OPS05_MATRIX`; `_record_task_duration` never calls the sink; TaskEvent kinds unchanged so `alert_task_stall` cannot see it; tests assert all three |
| T-kra-05 | Repudiation (measurement integrity) | wall-clock differences | low | accept | durations come from the injected clock (production `datetime.now(UTC)`); an NTP step can distort one sample; negative differences count as 0; documented in D112 and RUNBOOK 22.8 |
| T-kra-06 | Elevation of privilege (unratified number) | new limit key | medium | mitigate | key shipped NOT_CONFIGURED, guarded names 66 -> 68, no numeric default in src/scripts (tests/test_no_unratified_defaults.py), a value needs a DECISIONS row and provenance DECISION |
| T-kra-SC | Tampering | npm/pip/cargo installs | low | accept | no package is installed or upgraded by this plan; `uv.lock` untouched |
</threat_model>

<verification>
- Task 1 verify set green after the commit; ruff, ruff format, mypy src and the decision gate pass.
- Task 2 decision gate and the phase 20 / bookkeeping / limits tests pass.
- Task 3: the live sweep passes; counts and CRLF tables in the SUMMARY.
- Grep gates of both tasks hold against their recorded baselines.
</verification>

<success_criteria>
- The owner can read the longest observed run of `protection_step` with one read-only query after Demo sessions on the shipped image, and RUNBOOK 22.8 states the rule (longest x owner margin, below 180000 ms) without choosing a number.
- The journal volume is bounded by construction and the bound is written down (D112).
- No task behavior changed, no alert added, no value chosen; two commits, nothing pushed.
</success_criteria>

<output>
Create `.planning/quick/261115-kra-per-run-duration-record-for-live-schedul/261115-kra-SUMMARY.md` when done (not committed by the executor).
</output>
