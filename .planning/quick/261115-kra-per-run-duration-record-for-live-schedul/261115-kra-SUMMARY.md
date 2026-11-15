---
phase: quick-261115-kra
plan: 01
subsystem: live-scheduler, execution-limits, runbook
tags: [d112, live-task-duration, scheduler, observe-only, optional-refinement-key, runbook-22-8]
requires: [quick-261114-mp1, quick-261115-k46]
provides:
  - "Every live scheduler run that ends is timed in whole integer milliseconds from the injected clock; at most one LIVE_TASK_DURATION journal row per run (each new maximum, plus one per window when the optional key is set)"
  - "Optional limit key scheduler.duration_summary_interval_ms (OPTIONAL_REFINEMENT_LIMIT_KEYS), shipped NOT_CONFIGURED; unset = new-maximum rows only"
  - "D112, GLOSSARY 9.3 row, DOC_STATUS line, RUNBOOK 22.7 bullet and 22.8 rewritten: read-only SQL over the duration rows and the rule 'longest observed run x owner margin, below protection.max_unprotected_ms (180000 ms)'"
affects: [src/live/scheduler.py, src/live/wiring_parts.py, src/live/wiring.py, src/execution/execution_limits.py, config/execution, docs/DECISIONS.md, docs/operations/RUNBOOK.md]
tech-stack:
  added: []
  patterns: ["observe-only record with counters updated before the write", "record-value volume bound"]
key-files:
  created: []
  modified:
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
    - docs/DECISIONS.md
    - docs/DOC_STATUS.md
    - docs/GLOSSARY.md
    - docs/operations/RUNBOOK.md
decisions:
  - "D112: bounded per-run duration record (LIVE_TASK_DURATION), optional window key shipped NOT_CONFIGURED, observe only, never an alert; no value chosen for the window or for scheduler.protection_stall_after_ms"
metrics:
  tasks: 3
  files: 17
status: complete
commits: 2
plan_head_before: a3efe1387f77c589b310df9890e51554420c2d1f
plan_head_after: 299a0c11ff1ae7433acf3bb4706ffa5932d05d74
actuals:
  tokens: 11600   # chars/4 over the added lines of the two commits (46,554 chars; code, tests and docs)
  tasks: 3
  commits: 2      # measured: git rev-list --count a3efe138..HEAD
---

# Phase quick-261115-kra Plan 01: Per-run duration record for the live scheduler Summary

Every run of every live scheduler task that ends is now timed (whole ms, injected clock) and summarised in at most one `LIVE_TASK_DURATION` journal row per run, so the owner can read the longest observed `protection_step` run with one SQL query and set `scheduler.protection_stall_after_ms` from data. Observe only, never an alert, no value chosen.

## Commits

| Task | Commit | Message | Files |
|---|---|---|---|
| 1 | `bebd4df5` | feat(quick-261115-kra): bounded per-run duration record of the live scheduler tasks | the 13 code, config and test files |
| 2 | `299a0c11` | docs(quick-261115-kra): D112 duration record and the RUNBOOK 22.8 measurement | docs/DECISIONS.md, docs/DOC_STATUS.md, docs/GLOSSARY.md, docs/operations/RUNBOOK.md |
| 3 | (none) | final gates and this SUMMARY; the orchestrator commits the SUMMARY | |

Both commits carry `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. `git show --stat HEAD~1` lists exactly the 13 Task 1 files; `git show --stat HEAD -- src tests config` prints nothing (Task 2 is docs only). No file was deleted by either commit.

## Design as built

- **What is timed.** `Scheduler._loop` takes `ended = self._clock()` first in the existing `finally` (`src/live/scheduler.py:251`, start at `:241`), then `_note`, then `_note_duration` (`:256`), then `_wait`. Duration = `(ended - started) // _ONE_MILLISECOND`, clamped with `max(0, ...)` (`:316`). No float, no new `total_seconds()` (still 2 occurrences).
- **What is kept**, per task, in memory since process start: `runs`, `total_ms`, `max_ms`, `window_max_ms`, `window_started` (`_DurationState`).
- **When a row is written** (at most one per run end): (a) the run sets a strictly greater maximum, the first run of a task is one (`:323-328`); (b) only when `duration_summary_interval` is set and `ended - window_started >= interval` (`:331`); the window then restarts at `ended` with `window_max_ms` 0 (`:344-346`). One row can carry both flags.
- **Default.** The key ships `NOT_CONFIGURED`: only new-maximum rows. `Scheduler(record_duration=None)` accumulates and awaits nothing.
- **Key placement.** `scheduler.duration_summary_interval_ms`, second key of `[scheduler]`, field `scheduler_duration_summary_interval_ms`, property `scheduler_duration_summary_interval`, in `OPTIONAL_REFINEMENT_LIMIT_KEYS` and not in `ALERT_ONLY_LIMIT_KEYS`: it switches no alert and its fallback (new-maximum rows only) is safe. No existing key was reused as the window (`reconcile.lot_filter_refresh_interval_ms`, `account.max_daily_loss_age_ms`, `alerts.dedupe_window_ms` mean something else).
- **Volume bound** (written in D112 and the module docstring). New-maximum rows are the record values of the run durations: expected about ln(n) + 0.58 per task over n independent runs, never more than n; a task on the 15 s tick makes at most 5,760 runs a day, so about 9 rows on its first day and about 13 over 30 days; ties only lower it; a restart adds one first-run row per task. Window rows: at most one per run and per window, so per task at most floor(uptime / interval) + 1 per process and at most 13 x (86,400,000 / interval_ms + 1) a day. No number was chosen for the interval.
- **Row.** event type `LIVE_TASK_DURATION`, entity type `LiveScheduler`, entity id the task name, correlation `live_scheduler`, compact sorted JSON with exactly `max_ms`, `new_max`, `runs`, `task`, `total_ms`, `window_end`, `window_max_ms`. `TaskEvent` and `TaskEventKind` are unchanged; `LIVE_TASK_DURATION` is in none of `ALERT_EVENTS`, `EVENT_WORDING`, `OPS05_MATRIX` (grep count 0 in `src/ops/alerts.py` and `src/ops/alert_wording.py`).
- **Production path.** `LiveWiring` builds its `Scheduler` with `record_duration=self._record_task_duration` and `duration_summary_interval=self.cadences.duration_summary_interval` (`src/live/wiring.py:990-991`); `_record_task_duration` only awaits `self.record(task_duration_journal(summary))` (`:1044-1047`), never the alert sink.

## Task 1: RED and GREEN evidence

- Baseline at HEAD a3efe138 (the 18-file verify set, `-m "not docker" -n 4`): all dots, no F/s/x, 873 tests passed. The summary line itself was not printed because `addopts = "-q"` plus my `-q` is `-qq`; the 873 is a count of the progress dots (12 full rows of 72 plus 9). Later runs used `-o addopts=""` and print the summary line.
- RED (tests and pins written, no implementation): `39 failed, 265 passed, 47 errors` on the 6 affected files. Reasons: `KeyError: 'scheduler.duration_summary_interval_ms'` in the TEST_ONLY limits helper (65 occurrences, the 47 errors are fixtures built from it), `ImportError: cannot import name 'TaskDurationSummary'` (scheduler and wiring-parts tests), `assert 66 == 68` in `tests/test_phase18_gate.py` and `tests/test_no_unratified_defaults.py`, `unknown key` for the new key in the baseline document test, and the scheduler key tuple.
- GREEN: first run `1 failed, 909 passed`; the one failure was my own new wiring test (`complete_assembly` returns the cached wiring, so the second call could not see a changed cadence). I split it into two tests (default recorder with no window; a window set before the first completion). After that, and after `ruff format` re-wrapped one log call: **911 passed, 0 failed, 0 skipped** on the same 18-file set (873 -> 911, +38 tests: 18 scheduler incl. 2 parametrised, 3 wiring-parts, 3 wiring, 14 limits incl. 8 parametrised).
- Greps: `float(` 0 in each of the 4 `src` files; `total_seconds()` 2; `class TaskDurationSummary` 1 line; `def task_duration_journal` 1; `record_duration=self._record_task_duration` 1; `duration_summary_interval=self.cadences.duration_summary_interval` 1; toml `duration_summary_interval_ms` outside comments 2; toml `"NOT_CONFIGURED"` 6 (HEAD 4).
- `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src` (291 files), `uv run python scripts/verify_decision_alignment.py all` (ALL_PASS): pass.

Tests added (all virtual time, TEST_ONLY numbers through overrides only): first run 2.5 s gives one row with plain ints and bool flags; floor of 2.5009 s is 2500; durations 1.0/0.5/1.5/1.5 write rows only after runs 1 and 3; 20 equal runs write one row; a 60 s window writes one row per window and restarts `window_max_ms`; a run that closes the window and sets a maximum writes one row with both flags; a run that never ends writes nothing; no writer means nothing new is called; a failed run is timed; a cancelled scheduler writes no row; a writer that raises is logged by class name only (caplog) and the next row carries the counts of the failed one; identical sleeps, TaskEvent kinds and results with and without the record; a backwards clock gives 0 ms; a non-positive interval raises; cadence unset/set/tick-still-refuses; the literal journal payload; id stability; not an alert; production recorder never queues an alert; the scheduler carries the recorder and the cadence window; the limits matrix (declared second, optional not alert-only, committed file unset, never named by `require_live_ready`, TEST_ONLY override loads as ms and timedelta, PLACEHOLDER and labelled-unset refused, 8 malformed values refused by name, a missing section names both keys).

## Pins changed (old -> new)

| File | Pin | Old | New |
|---|---|---|---|
| tests/test_no_unratified_defaults.py | `len(GUARDED_NAMES)`, plus the two new names in the subset assertion | 66 | 68 |
| tests/test_phase18_gate.py | `len(unratified_tests.GUARDED_NAMES)` | 66 | 68 |
| tests/test_execution_limits.py | dotted key count / margin slice | 22 / `[-5:-2]` | 23 / `[-6:-3]` |
| tests/test_execution_limits.py | shipped `"NOT_CONFIGURED"` strings | 4 | 6 |
| tests/test_execution_limits.py | `OPTIONAL_REFINEMENT_LIMIT_KEYS` | `{BAN_END_MARGIN_KEY}` | `{BAN_END_MARGIN_KEY, SUMMARY_KEY}` |
| tests/test_execution_limits.py | `unset_optional_refinement_keys()` (all-unset round trip, committed file, `ready` object) | `(BAN_END_MARGIN_KEY,)` | `(BAN_END_MARGIN_KEY, SUMMARY_KEY)` |
| tests/test_execution_limits.py | `unset_optional_refinement_keys()` with TEST_ONLY values | `()` | `(SUMMARY_KEY,)` |
| tests/test_execution_limits.py | distinct TEST_ONLY values | all values | the non-None values |
| tests/test_execution_limits.py | all-unset kwargs | 22 fields | + `scheduler_duration_summary_interval_ms` |
| tests/test_execution_limits.py | scheduler key tuple | `("protection_stall_after_ms",)` | two-key tuple |
| tests/test_live_scheduler.py | positive-cadence loop skips | `protection_stall_after` | + `duration_summary_interval` |
| tests/support/execution_limits.py | TEST_ONLY values | 22 keys | + `"scheduler.duration_summary_interval_ms": None` |

Each carries a history comment. A grep of `tests/`, `scripts/` and `src/` for the old counts and names (`twenty-two`, `== 22`, `== 66`, `(BAN_END_MARGIN_KEY,)`, `OPTIONAL_REFINEMENT_LIMIT_KEYS`, `protection_stall_after_ms`, `LIVE_TASK_EVENT`, `EVENT_TASK`, `ExecutionLimits(`, `TaskEventKind`) found no further pin: the only direct `ExecutionLimits(...)` constructors are the TEST_ONLY helper and the generic loader.

## Line endings (CRLF / LF counts, measured with Python on the bytes)

| File | Before | After |
|---|---|---|
| src/live/scheduler.py | 375/375 | 482/482 |
| src/live/wiring_parts.py | 385/385 | 423/423 |
| src/live/wiring.py | 1550/1550 | 1563/1563 |
| src/execution/execution_limits.py | 486/486 | 506/506 |
| config/execution/execution-limits-v1.toml | 0/117 (LF) | 0/123 (LF) |
| config/execution/README.md | 155/155 | 157/157 |
| tests/support/execution_limits.py | 124/124 | 128/128 |
| tests/test_live_scheduler.py | 705/705 | 1039/1039 |
| tests/test_live_wiring_parts.py | 555/555 | 621/621 |
| tests/test_live_wiring.py | 660/660 | 718/718 |
| tests/test_execution_limits.py | 0/1199 (LF) | 0/1315 (LF) |
| tests/test_no_unratified_defaults.py | 428/428 | 435/435 |
| tests/test_phase18_gate.py | 647/647 | 648/648 |
| docs/DECISIONS.md | 115/115 | 116/116 |
| docs/DOC_STATUS.md | 95/95 | 96/96 |
| docs/GLOSSARY.md | 649/649 | 650/650 |
| docs/operations/RUNBOOK.md | 1237/1237 | 1253/1253 |

Format is CRLF = LF (or LF only) in every file, no mixed endings. Edits were bytes-aware (throwaway scripts in the scratchpad; the Edit tool was used once, on the LF file `tests/test_execution_limits.py`). `ruff format` re-wrapped one line of `src/live/scheduler.py` and kept CRLF (482/482 afterwards).

## RUNBOOK 22.8 claim table (every claim re-read in the committed code)

| Claim in the new 22.8 text (and D112) | Backed by |
|---|---|
| Every run that ends, successful or failed, is timed | `src/live/scheduler.py:247-256` (the try/except around `spec.run()` at `:246-249`, then `_note_duration` at `:256` for both outcomes) |
| Timed with the process clock `datetime.now(UTC)` (wall clock) | `src/live/runtime.py:161-162` (`_utc_now`), injected at `src/live/runtime.py:355`; end instant taken at `src/live/scheduler.py:251`, start at `:241` |
| Whole milliseconds, a negative difference counts as 0 | `src/live/scheduler.py:75` (`_ONE_MILLISECOND`), `:316` (`max(0, ... // _ONE_MILLISECOND)`); test `test_a_clock_that_steps_back_records_zero_milliseconds_never_a_negative_number` |
| At most one row per run | one `TaskDurationSummary` built at `src/live/scheduler.py:334-343` and one `await record(summary)` at `:348` |
| A row at each new maximum, the first run of a task is one | `src/live/scheduler.py:323-328` (`previous_max is None or elapsed_ms > previous_max`) |
| With the key set, once per window; the window restarts | `src/live/scheduler.py:331` (`ended - window_started >= interval`), `:344-346` (restart), `:317-318` (first window starts at the first run's start) |
| `runs`, `total_ms`, `max_ms` count since process start; `window_max_ms` is the window maximum | in-memory `_DurationState` updated at `src/live/scheduler.py:319-322` and `:329`, never persisted, so a restart begins at zero |
| Payload keys `task`, `runs`, `total_ms`, `max_ms`, `window_max_ms`, `new_max`, `window_end` | `src/live/wiring_parts.py:256-268` (sorted compact JSON); literal asserted in `tests/test_live_wiring_parts.py` |
| Event type `LIVE_TASK_DURATION`, correlation `live_scheduler`, entity the task name | `src/live/wiring_parts.py:57` (`EVENT_TASK_DURATION`), `:278-281` |
| Production wiring writes it | `src/live/wiring.py:990-991` (Scheduler arguments), `:1044-1047` (`_record_task_duration` awaits `self.record(...)`) |
| Never an alert; kinds unchanged | no sink call in `src/live/wiring.py:1044-1047`; `LIVE_TASK_DURATION` count 0 in `src/ops/alerts.py` (`ALERT_EVENTS` `:96`, `OPS05_MATRIX` `:882`) and `src/ops/alert_wording.py` (`EVENT_WORDING` `:258`); tests assert absence and an empty alert queue |
| A failing journal write is logged by class name and the scheduler goes on | `src/live/scheduler.py:347-350`; counters advance first (`:319-329`); test with a `RuntimeError` writer and caplog |
| A cancelled run is not counted; no row at stop | `except Exception` at `src/live/scheduler.py:248` does not catch `CancelledError`, so it propagates before `:256`; no write path outside `_note_duration`; test `test_a_run_cancelled_with_the_scheduler_writes_no_summary` |
| A run that never ends is not in it; the stall watchdog covers that once its bound is set | the row is written only after the run returns (`:256`); `_watch_stall` at `src/live/scheduler.py:259`; only the protection task has a bound: `src/live/wiring.py:1125-1131` |
| Unset window key means new-maximum rows only | `src/live/scheduler.py:331` (`interval is not None`); key shipped unset at `config/execution/execution-limits-v1.toml:82` and `:123`; `src/execution/execution_limits.py:140-145` (optional refinement) |
| 13 scheduler tasks | `src/live/wiring.py:179-191` (13 names) and the 13 `TaskSpec` at `:1125-1149` |
| `protection.max_unprotected_ms` is 180000 ms (D089) | `config/execution/execution-limits-v1.toml:44` |
| `payload_json::jsonb` is a valid cast on the journal column | `src/db/alembic/versions/0002_domain_registry.py:212` (`payload_json` is `sa.String()`) |
| 15 s tick, at most 5,760 runs a day | `reconcile.tick_interval_ms` = 15000 (D089, `tests/test_execution_limits.py` `D089_DECIDED`); interval measured from the end of the run, so the real count is a little lower |
| Limits are baked into the image; a value means a rebuilt and re-pinned image | RUNBOOK 22.4, D106 (already stated in the old 22.8; unchanged) |

The two SQL queries 2 and 3 were not run: no PostgreSQL journal with duration rows exists here, and an agent never runs the Demo. They are text only; the cast is checked only against the column type.

## Final gates (after both commits)

| Gate | Result |
|---|---|
| `uv run ruff check` | pass |
| `uv run ruff format --check` | pass (1029 files) |
| `uv run mypy src` | pass (291 files) |
| `uv run python scripts/verify_decision_alignment.py all` | ALL_PASS |
| Task 1 verify set (18 files, `-m "not docker" -n 4`) | 911 passed, 0 failed, 0 skipped (baseline 873) |
| Task 2 set (`test_phase20_gate`, `test_decision_alignment_bookkeeping`, `test_execution_limits`) | 279 passed |
| Live sweep `uv run pytest tests/test_live_*.py -m "not docker" -n 4` | 1227 passed, **1 failed** (pre-existing, below), 0 skipped |

`TEST_DATABASE_URL` was set in the process environment (database name ends in `_test`; the value was not read or printed), so the two `*_pg.py` files of the sweep (`tests/test_live_replay_restart_pg.py`, `tests/test_live_stream_persistence_pg.py`) ran rather than skipped, and passed.

**The one failure is pre-existing at HEAD a3efe138.** `tests/test_live_demo_smoke.py::test_a_restart_that_finds_no_snapshot_row_fails_closed` fails with `assert ['RESTORE_INCONSISTENT'] == ['DB_FAILURE']` (the test is defined at line 156 and the assertion is at line 166, the same at HEAD and now). I reproduced it on a `git archive a3efe138` copy outside the repository (with the repository's interpreter, no `TaskDurationSummary` in that copy) with the same message. D110 item 1 explains the behavior (a fault of one restorable row is `RESTORE_INCONSISTENT`, a fault of the store is `DB_FAILURE`), so the test expects the older reason. It does not touch the scheduler, the limits or the journal rows of this task. Left unfixed; deferred for the owner or a follow-up quick task. The copy was removed from the scratchpad.

## Deviations from Plan

1. **[Premise corrected] Two files are LF, not CRLF.** The plan said every touched file is CRLF (its grep used `$'\r$'`, which in this shell evidently matched every line, so my first "before" counts repeated the line count). Measured on the bytes: `tests/test_execution_limits.py` (0/1199 before) and `config/execution/execution-limits-v1.toml` (attribute `-text`, 0/117) are LF; the other 15 files are CRLF. The helper preserves each file's own ending; the table above is measured with Python.
2. **[Rule 1 - test fix] One wiring test split in two.** `complete_assembly` returns the cached wiring, so a test that completed once and then replaced the cadences saw the old window. The default-recorder assertion and the window assertion are now two tests (the window one replaces the cadence before the first completion, like the mp1 stall test).
3. **[Formatting] `ruff format` re-wrapped one `_LOGGER.warning` line** in `src/live/scheduler.py` to one line (same text); CRLF kept.
4. **Line references.** The plan quoted `src/live/wiring.py:1111-1137` for the 13 specs and `:984` for the Scheduler construction; the committed lines are `:1125-1149` and `:990-991` (the earlier edits shifted them). The table above uses the committed lines.
5. **Pre-existing failure** in the live sweep, see above (out of scope, not fixed).

README note: `config/execution/README.md` still has older stale sentences that this task did not make false (line 9 "four are filled", "Of the twenty keys...", the REQUIRED `stale_feed.max_user_data_silence_ms` bullet in the "Still NOT_CONFIGURED" list that D091 already set). I left them alone.

## Auth gates

None.

## Known Stubs

None. (`scheduler.duration_summary_interval_ms` and `scheduler.protection_stall_after_ms` are NOT_CONFIGURED by design, not stubs.)

## Threat Flags

None. The only new write path is the journal row inside the existing loops (T-kra-02); the payload is a task name, four integers and two booleans (T-kra-03).

## Not run

The full suite, docker-marked tests, `pytest -m demo`, any `--execute` script, any live or Demo call. The two RUNBOOK 22.8 SQL queries 2 and 3 (no database with duration rows).

## Residuals for the owner

- `AGENTS.md` "Still open (owner)" does not name the new key `scheduler.duration_summary_interval_ms` (gated file, not edited here); a follow-up should add it beside the stall key.
- The values of `scheduler.protection_stall_after_ms` and `scheduler.duration_summary_interval_ms` remain the owner's; both ship `NOT_CONFIGURED`. RUNBOOK 22.8 gives the rule (longest observed `protection_step` run x an owner margin, below 180000 ms) and no number.
- Nothing was observed on Demo or on a host; the duration rows exist only in tests. The shipped image has to carry this commit before the owner can read any row.
- The pre-existing `tests/test_live_demo_smoke.py` failure above.

## Self-Check: PASSED

- `bebd4df5` and `299a0c11` are ancestors of HEAD; `git rev-list --count a3efe138..HEAD` = 2; `plan_head_before` and `plan_head_after` in the frontmatter match the ledger and `git rev-parse HEAD`.
- All created and modified files exist; `git diff --cached` is empty (nothing staged); `.planning/REQUIREMENTS.md`, `.planning/STATE.md`, `.planning/config.json` and `.planning/state.json` are still modified and unstaged; untracked files are untouched.
- No file deleted by either commit; nothing pushed; branch `develop` unchanged.
