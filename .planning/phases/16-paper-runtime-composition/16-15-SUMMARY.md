---
phase: 16-paper-runtime-composition
plan: 15
subsystem: paper-evidence / coverage / freeze-continuity
tags: [coverage, health-intervals, evidence-gap, freeze-ticks, github-run-list, tick-timing, decimal, determinism]

requires:
  - phase: 16-paper-runtime-composition
    provides: "plan 16-08: HealthState, GapReason, RuntimeEventType (incl. PAPER_TICK_STATS), INTERVAL_MS; plan 16-09: DiffLogEntry and FreezeSkippedEntry lines with run_metadata (run_id, run_attempt, event_name, schedule, commit)"
provides:
  - "src/paper/coverage.py: HealthInterval, HealthThresholds, coverage_report, derive_health_intervals (runtime health and coverage, REV-01, REV-17)"
  - "src/paper/coverage.py: expected_slots, freeze_evidence_report, EvidenceGap, EvidenceGapReason, FreezeLine, GithubRun, parse_freeze_log, parse_github_runs (freeze-tick continuity, REV-02, REV-18)"
  - "src/paper/coverage.py: tick_timing_summary and TickTimingSummary (report-only, research A10 and P20)"
  - "RuntimeRecordLike protocol and the payload-key evidence contract the runtime plans must write"
affects: [16-24 bar pipeline payload, 16-25 exit-criteria evaluator, 16-26 live loop tick stats, 16-27 and 16-34 threshold ratification, 16-29 restart and health records, 16-30 cron checkpoint Q-Q, 16-47 cron constant]

actuals:
  tokens: 28200
  tasks: 4
  commits: 8
plan_head_before: 99a8e2d448a9c2dfcc6c845c3a1dee5cbacbc6a3
plan_head_after: fa65953919f9d4da04a79a62969ca3aedc234703
commits: 8

tech-stack:
  added: []
  patterns:
    - "One normalising sweep (_tile) serves both the coverage report and the health derivation: non-HEALTHY beats HEALTHY on overlap, the most specific reason wins, unlabelled time is UNKNOWN, adjacent equal segments merge, so the result never depends on input order"
    - "Decimal arithmetic on integer microseconds with a fixed 28-digit context; the 95 percent comparison is exact (covered_us >= 0.95 x window_us), no rounding can flip a verdict"
    - "User-owned numbers are keyword-only or dataclass fields with no default, pinned by an AST test that fails on any numeric default for those names"
    - "A reconciler returns records and never writes: an AST test bans file-writing calls and the freeze log append helper in the module"

key-files:
  created:
    - src/paper/coverage.py
    - tests/test_paper_coverage.py
    - tests/test_paper_freeze_evidence.py
  modified: []

key-decisions:
  - "Coverage window is the denominator and only HEALTHY time counts; a non-HEALTHY interval without a reason is reported as UNKNOWN, time with no interval at all is DISCONNECTED/UNKNOWN (REV-01)"
  - "A start-up wait is not HEALTHY: after every RUNTIME_START the time up to the first feed message (live closed bar, PAPER_TICK_STATS or WS_RECONNECT) is DISCONNECTED with reason WS_RECONNECT_WINDOW, matching plan 16-29's HEALTH_STATE_CHANGED rule"
  - "Only a LIVE_WS PAPER_BAR_PROCESSED record proves a bar arrived live; a REST_BACKFILL or REST_WARMUP record does not, so a recovered bar still leaves the wait uncovered until the next live bar"
  - "A freeze slot is satisfied only by a CLEAN line that is linked to a schedule-event run of the exported run list (line run_id equals run id), whose line event_name is schedule, whose recorded schedule equals the evaluated cron and whose run_attempt is 1; a re-run line is INVALID_LINE because it is run later than the slot"
  - "A CLEAN line whose run is not in the run list cannot satisfy a slot (NO_RUN_FOUND): the run list is the proof that a scheduled run existed"
  - "Grace is 0 <= grace < 3600 s; at or above the slot interval ValueError ('one run could stand for two slots'); lateness is measured on the run created_at, not on the line time"
  - "An undated unparsable line cannot be placed in time and fails the qualifying window closed (unplaced_line_count); a dated invalid line after the pin is a break"
  - "qualifying_from_pin is False when the window holds no slot at all (a vacuous truth must not read as qualifying)"

patterns-established:
  - "Pattern: evidence functions take plain frozen values and injected times, return frozen reports with a human-readable statement field that carries the restart rule and the auxiliary rule verbatim"

requirements-completed: [PAPER-01]

coverage:
  - id: D1
    description: "Coverage uses the whole fixed window as denominator and counts only HEALTHY time; every uncovered interval has a reason code; an explained gap is still uncovered; a 14-day window reports 336 h, the 95 percent criterion and the DERIVED minimum 319.2 h"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_coverage.py#test_tracer_14_day_window_with_one_restart_and_one_disconnect"
        status: pass
      - kind: unit
        ref: "tests/test_paper_coverage.py#test_an_explained_gap_is_still_uncovered_and_missing_time_is_unknown"
        status: pass
      - kind: unit
        ref: "tests/test_paper_coverage.py#test_exactly_at_the_criterion_passes"
        status: pass
    human_judgment: false
  - id: D2
    description: "The longest continuous non-HEALTHY block is reported against the user-ratified ceiling, a required input with no default"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_coverage.py#test_longest_continuous_block_is_reported_against_the_ceiling"
        status: pass
      - kind: unit
        ref: "tests/test_paper_coverage.py#test_the_ceiling_is_a_required_input_with_no_default"
        status: pass
    human_judgment: false
  - id: D3
    description: "Health intervals are derived deterministically from the judged epoch's recorded events with user-owned thresholds only; earlier-epoch records are ignored"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_coverage.py#test_healthy_only_while_up_connected_fresh_and_every_bar_on_time"
        status: pass
      - kind: unit
        ref: "tests/test_paper_coverage.py#test_the_module_source_has_no_numeric_default_for_the_user_owned_names"
        status: pass
      - kind: unit
        ref: "tests/test_paper_coverage.py#test_records_of_an_earlier_epoch_are_ignored_and_not_mutated"
        status: pass
    human_judgment: false
  - id: D4
    description: "Every expected scheduled freeze slot from the pin to the window end is satisfied only by a CLEAN line of a schedule run with the same cron string; otherwise an EvidenceGap is produced, never CLEAN, never interpolated, with the restart rule stated; the grid follows the cron minute"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_freeze_evidence.py#test_a_slot_with_no_run_and_no_line_is_an_evidence_gap_never_clean"
        status: pass
      - kind: unit
        ref: "tests/test_paper_freeze_evidence.py#test_a_line_whose_schedule_differs_from_the_evaluated_cron_is_a_mismatch_gap"
        status: pass
      - kind: unit
        ref: "tests/test_paper_freeze_evidence.py#test_the_slot_grid_follows_the_minute_of_the_cron"
        status: pass
    human_judgment: false
  - id: D5
    description: "The freeze-tick grace can never turn a gap into CLEAN: a run serves exactly one slot, a grace at or above the slot interval is refused, and a property-style test over several grace values shows no slot without a CLEAN scheduled line becomes satisfied"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_freeze_evidence.py#test_no_grace_value_turns_a_slot_without_a_clean_line_into_clean"
        status: pass
      - kind: unit
        ref: "tests/test_paper_freeze_evidence.py#test_a_grace_at_or_above_the_slot_interval_is_refused"
        status: pass
      - kind: unit
        ref: "tests/test_paper_freeze_evidence.py#test_each_run_serves_at_most_its_own_slot_even_with_the_widest_grace"
        status: pass
    human_judgment: false
  - id: D6
    description: "Earlier-epoch lines and runs are retained untouched as auxiliary evidence, reproducible with their own pin, and never count toward the new trial; freeze integrity and runtime health are two separate reports"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_freeze_evidence.py#test_earlier_epoch_evidence_is_auxiliary_and_reproducible_with_its_own_pin"
        status: pass
      - kind: unit
        ref: "tests/test_paper_freeze_evidence.py#test_freeze_integrity_and_runtime_health_are_two_separate_reports"
        status: pass
    human_judgment: false
  - id: D7
    description: "A report-only tick timing summary over PAPER_TICK_STATS makes tick duration, queue depth and clock-skew drops visible and is compared with no limit"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_coverage.py#test_tick_timing_summary_reports_duration_depth_and_drops"
        status: pass
      - kind: unit
        ref: "tests/test_paper_coverage.py#test_tick_timing_summary_is_an_observation_never_a_criterion"
        status: pass
    human_judgment: false
  - id: D8
    description: "That the payload keys read here (tick_time_utc, source, expected_close_utc, reason, state, duration_ms, queue_depth_before, dropped_total, dropped_by_reason) are the keys the runtime actually writes, and that the user-ratified silence limit is compatible with the closed-bar cadence"
    requirement: PAPER-01
    verification: []
    human_judgment: true
    rationale: "The runtime producers (plans 16-24, 16-26, 16-29) do not exist yet; the contract is fixed here and in the RuntimeRecordLike docstring, and must be reconciled when those plans land. The silence-limit number is the user's (O-07) and is only meaningful relative to the journalled message cadence."

duration: 22min
completed: 2026-10-09
status: complete
---

# Phase 16 Plan 15: Runtime coverage and freeze-tick continuity evidence Summary

**Pure evidence module `src/paper/coverage.py`: whole-window HEALTHY-only coverage with the derived 319.2 h and a no-default continuous-gap ceiling, health intervals derived from recorded runtime events with user-owned thresholds, and a freeze-tick reconciler that rebuilds the hourly slot grid from the pin and turns every missing, late, failed, manual, re-run or cron-mismatched tick into an EVIDENCE_GAP that can never read as CLEAN.**

## Performance

- **Duration:** about 22 min (2026-10-09T13:13Z to about 13:35Z)
- **Tasks:** 4 (Task 1 tracer, Tasks 2 to 4 auto, all TDD)
- **Files:** 3 created (1 source, 2 test files), 2802 lines

## Accomplishments

- Tracer (REV-01, REV-17): `coverage_report(window_start_utc, window_end_utc, intervals, continuous_uncovered_ceiling_seconds)` tiles the window, counts only HEALTHY time, and reports covered hours as `Decimal` (333.5 h of 336 h in the tracer case), the fraction, `coverage_pass` against the exact 95 percent comparison, the derived minimum 319.2 h labelled DERIVED and "not a threshold", every uncovered interval with a reason, and the longest continuous uncovered block (all reasons merged) against the ceiling. The ceiling is a required keyword; omitting it raises `TypeError`, a non-positive or non-integer value raises `ValueError`.
- `derive_health_intervals(records, *, epoch_id, window_start_utc, window_end_utc, intervals_expected, thresholds)`: HEALTHY only while the process is up, connected, a feed message is fresh and every expected closed bar of the expected (symbol, interval) pairs arrived live within the lateness limit and the runtime did not declare itself non-HEALTHY. START with a preceding STOP gives PLANNED_RESTART, START without one gives CRASH from the last evidence, time before the first START or after the last STOP is PROCESS_DOWN. `HealthThresholds` has four required positive integer fields and no default (an AST test fails on any numeric default for the four names and for `grace_seconds`). Records of another epoch are ignored; the input is never mutated; any input order gives the same intervals.
- Freeze reconciler (REV-02, REV-18): `expected_slots` (hourly `M * * * *` only, slots strictly after the pin up to and including the window end, any other cron raises), `freeze_evidence_report` (slots, satisfied slots, per-slot results, `EvidenceGap` records with the five reasons NO_RUN_FOUND, RUN_WITHOUT_LINE, RUN_LATE_BEYOND_GRACE, INVALID_LINE, SCHEDULE_MISMATCH, breaks from non-CLEAN lines after the pin, continuity segments, `qualifying_from_pin`, and a statement that carries "qualifying trial restarts with a new epoch pin (D065 item 4)" whenever anything failed). `parse_freeze_log` and `parse_github_runs` read the exported files; typed `DiffLogEntry` and `FreezeSkippedEntry` objects are accepted directly.
- Grace semantics fixed: a run is assigned to the latest slot not after its `created_at`, so it serves one slot; the grace only decides whether an existing run is late-but-valid or beyond the grace; a grace at or above 3600 s raises ("one run could stand for two slots"). A property-style test over `0, 1, 60, 300, 1800, 3599` shows the satisfied set is always a subset of the slots that have a CLEAN scheduled line and changes only for the existing late runs.
- Earlier-epoch evidence: lines and runs at or before the pin are not evaluated, are returned as the caller's own objects in `auxiliary` (count, span), and the same inputs with the old pin reproduce the old EvidenceGap exactly.
- `tick_timing_summary(records)`: min/median (lower middle)/max duration, max queue depth, dropped total and by reason, first and last tick, integers only; an AST test proves it contains no comparison against a numeric literal or a limit-like name.

## RED Evidence

- **Task 1** (`d74561c`): `ModuleNotFoundError: No module named 'src.paper.coverage'` at collection.
- **Task 2** (`829f922`): `ImportError: cannot import name 'HealthThresholds' from 'src.paper.coverage'` at collection (the Task 1 tests in the same file were blocked with it).
- **Task 3** (`e890990`): `ImportError: cannot import name 'EvidenceGapReason' from 'src.paper.coverage'` at collection.
- **Task 4** (`5a81eef`): `ImportError: cannot import name 'TickTimingSummary' from 'src.paper.coverage'` at collection of `tests/test_paper_coverage.py`; the grace, refusal and auxiliary tests of `tests/test_paper_freeze_evidence.py` have no implementation to run against (`report.auxiliary` and the grace refusal were deliberately withheld from the Task 3 implementation so these tests were red before Task 4).

## Task Commits

1. **Task 1 (tracer): coverage arithmetic** - `d74561c` (test, RED), `6c408f8` (feat, GREEN)
2. **Task 2: health derivation with user-owned thresholds** - `829f922` (test, RED), `9861362` (feat, GREEN)
3. **Task 3: freeze-tick reconciler** - `e890990` (test, RED), `d601518` (feat, GREEN)
4. **Task 4: grace semantics, auxiliary evidence, tick timing summary** - `5a81eef` (test, RED), `fa65953` (feat, GREEN)

Tracer gate (auto mode): tracer `<verify>` re-run end to end after Task 1 and again at the end of every later task; green each time, expansion continued.

**Plan metadata:** committed separately (docs: complete plan).

## Files Created

- `src/paper/coverage.py` - the evidence functions (pure: stdlib, Decimal, `src.paper.vocabulary`, and the line classes of `src.paper.freeze`; no clock, no float, no file write)
- `tests/test_paper_coverage.py` - coverage, health derivation, thresholds, tick timing (51 tests)
- `tests/test_paper_freeze_evidence.py` - slot grid, EvidenceGap reasons, segments, grace, auxiliary evidence, parsers (43 tests)

## Decisions Made

See `key-decisions`. The ones downstream plans must know:

- **Evidence contract (to be matched by plans 16-24, 16-26, 16-29).** `PAPER_BAR_PROCESSED`: `occurred_at_utc` is the bar close, `payload["source"]` "LIVE_WS" and `payload["tick_time_utc"]` (ISO string or datetime) are read; `PAPER_GAP`: `payload["expected_close_utc"]` and `payload["reason"]` (a `GapReason` value); `HEALTH_STATE_CHANGED`: `payload["state"]` and optional `"reason"`; `PAPER_TICK_STATS`: `duration_ms`, `queue_depth_before`, `dropped_total`, `dropped_by_reason` (matching the payload that plan 16-26 Test 5 writes). A bar record without `tick_time_utc` or without source "LIVE_WS" is treated as not arrived, so a mismatch shows as lost coverage rather than inflated coverage (fail closed).
- **Input protocol.** Plan 16-16's `RuntimeRecord` does not exist yet, so the functions take a `RuntimeRecordLike` protocol (read-only properties `event_type`, `epoch_id`, `symbol`, `interval`, `occurred_at_utc`, `payload`); the future frozen dataclass satisfies it unchanged.
- **Lateness uses the line-to-run link, not line times.** A line proves a tick only through its `run_metadata.run_id`; the grace is measured on the run's `created_at`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] A re-run must not fill a missed tick**
- **Found during:** Task 3 design (threat T-16-114, "a neighbouring tick filling a gap")
- **Issue:** a manual re-run of a failed scheduled run keeps `event=schedule` and the original `created_at` but executes later; its CLEAN line would otherwise satisfy the old slot, which is a gap filled after the fact.
- **Fix:** a CLEAN line whose `run_metadata.run_attempt` is not "1" does not satisfy the slot and yields INVALID_LINE (a missing attempt key is read as 1 so older lines still work). Covered by `test_a_rerun_line_does_not_fill_a_missed_tick`.
- **Files modified:** src/paper/coverage.py, tests/test_paper_freeze_evidence.py
- **Committed in:** d601518

**2. [Rule 2 - Missing critical functionality] Lines that cannot be placed in time**
- **Found during:** Task 3
- **Issue:** an unparsable append-only line has no timestamp; dropping it silently would let garbage in the evidence file pass.
- **Fix:** `parse_freeze_log` returns an INVALID line for anything unreadable; an undated one is counted in `unplaced_line_count` and makes `qualifying_from_pin` False (fail closed), a dated one after the pin is a break. This is stricter than the plan text, which names INVALID_LINE only; the plan's reason is kept for a dated invalid line of a slot's run.
- **Committed in:** d601518

**3. [Rule 2 - Missing critical functionality] Recorded gaps conflict with an on-time bar**
- **Found during:** Task 2
- **Issue:** if both a PAPER_GAP and a live bar exist for one close, trusting the bar would hide a recorded gap.
- **Fix:** a PAPER_GAP record always makes its slot non-HEALTHY (from the close to the next live arrival of that pair, a reconnect or process boundary, at least the lateness limit), whatever else exists.
- **Committed in:** 9861362

### Plan-shape choices (not defects)

- The plan's `HealthInterval.reason` is `GapReason | None`; a non-HEALTHY interval with `None` is reported as UNKNOWN, and a HEALTHY interval with a reason raises.
- `intervals_expected` is a sequence of `(symbol, interval)` pairs (the plan names the parameter but not its element type).
- The plan's "RUN_LATE_BEYOND_GRACE" for a run created after the grace is evaluated per run; when several runs fall in one slot the reason precedence is INVALID_LINE, SCHEDULE_MISMATCH, RUN_WITHOUT_LINE, RUN_LATE_BEYOND_GRACE and any satisfied run wins.
- A slot whose run has a non-CLEAN line (REGISTRY_DIFF or SKIPPED) is `BROKEN_BY_LINE` and appears under `breaks`, not as an EvidenceGap (the line exists and says what happened).
- Run conclusion is used only to label a gap (a run with no line is RUN_WITHOUT_LINE whatever its conclusion); a CLEAN line of a run that later failed an unrelated step still satisfies its slot.

---

**Total deviations:** 3 auto-fixed (all Rule 2, all tightening). **Impact:** stricter, never looser, than the plan; no threshold, default or semantics of an existing module changed, no package installed, `uv.lock` unchanged.

## Issues Encountered

- Shell heredocs containing apostrophes failed once or twice on quoting before any file was touched; larger additions were written through the Write tool into a scratch file and appended.
- One transient `.git/index.lock` collision (gone on retry, no git process running).

## Known Stubs

None.

## Known Limitations (for plans 16-24, 16-25, 16-26, 16-27, 16-29)

- **Silence limit versus message cadence.** The runtime journals one record per closed bar, per tick batch and per reconnect, not one per kline message. `max_ws_message_silence_seconds` is therefore measured against that cadence: a user-ratified limit shorter than the longest expected gap between journalled messages (1 h for a 1h stream) leaves the time DEGRADED. The result is visible in the report, never hidden, but plan 16-27 and the O-07 table should state this next to the number, or plan 16-26 should journal a message-level heartbeat if a tighter limit is wanted.
- **Start-up wait.** After every START the time to the first live closed bar is uncovered (up to one interval for a 1h-only stream, 4 h for a 4h-only stream). This is the reading of plan 16-29's HEALTH_STATE_CHANGED rule and of L-04 ("healthy feed"); it costs coverage at each restart.
- **Missing-bar resolution.** A bar that never arrived keeps the time non-HEALTHY until the next live arrival of that pair, a reconnect or a process boundary, so one missing 4h bar can cost up to a 4h interval of coverage. Conservative by design.
- The reconciler needs the run list exported by plan 16-30 and the `registry_diff.jsonl` copy; it never calls the network.

## Threat Flags

None. T-16-36 (missing freeze tick) mitigated: expected-slot grid plus run list, EvidenceGap records, no interpolation, restart rule in the output. T-16-37 (coverage inflation) mitigated: whole-window denominator, only HEALTHY counts, explained gaps uncovered, thresholds required inputs. T-16-114 (grace, cron edit or neighbouring tick turning a missing tick CLEAN) mitigated: one run serves one slot, grace at or above the interval refused, SCHEDULE_MISMATCH, re-run lines invalid, earlier-epoch evidence auxiliary only, property-style test over several grace values. T-16-SC accepted: no package installed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 16-25 (evaluator) can import `coverage_report`, `derive_health_intervals`, `freeze_evidence_report`, `tick_timing_summary` and render `CoverageReport.derived_minimum_label`, the longest block and `FreezeEvidenceReport.statement` as two separate evidence sets.
- Plans 16-24, 16-26 and 16-29 must write the payload keys listed under Decisions Made (or this module's reader is adjusted in the same change); plan 16-27/16-34 own the four `HealthThresholds` numbers and must state the silence-limit caveat with the number.
- Plan 16-30 exports the run list as JSON (array or `workflow_runs` object) and `registry_diff.jsonl`; plan 16-47 changing the cron minute changes only the `cron` argument.

## Verification

- `.venv/Scripts/python -m pytest tests/test_paper_freeze_evidence.py tests/test_paper_coverage.py tests/test_domain_no_float.py -q -p no:cacheprovider`: 94 passed (the new module is float-scanned through the `src/paper/*.py` glob).
- `ruff check` and `ruff format --check` (468 files) and `mypy src` (163 files) are clean; `mypy src/paper/coverage.py` clean.
- Plan acceptance checks: Tests 1 to 5 (Task 2) and the negative cases of Task 4 (a grace at or above the interval raises) are in the suites above.
- No file was deleted by any commit; no package installed; `uv.lock` unchanged.
- The whole `pytest -m "not docker"` suite was not run in one process (tool time limit). A `-x` run over the paper, domain, decision and freeze selection stopped at one failure that this plan did not cause: `tests/test_cost_parity.py::test_simulator_and_paper_call_evaluate_risk_with_identical_arguments` (`open_positions` list versus tuple in the simulator and paper `evaluate_risk` arguments). It is logged in `.planning/phases/16-paper-runtime-composition/deferred-items.md`; this plan changed no simulator, paper-loop or risk code.

## Self-Check: PASSED

- FOUND: src/paper/coverage.py, tests/test_paper_coverage.py, tests/test_paper_freeze_evidence.py
- FOUND commits: d74561c, 6c408f8, 829f922, 9861362, e890990, d601518, 5a81eef, fa65953
