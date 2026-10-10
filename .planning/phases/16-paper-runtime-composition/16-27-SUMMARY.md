---
phase: 16-paper-runtime-composition
plan: 27
subsystem: paper-runtime / O-07 health and timing numbers
tags: [o-07, user-decision, health, timing, paper-soak]
requires: [16-21, 16-22, 16-24]
provides:
  - "decisions/16-O-07-table.md: every health and timing number with source, facts, smoke observations and the user's value"
  - "decisions/16-DEC-O-07.md: user-ratified values for the 11 [health] and [timing] keys; every code constant ratify current"
affects: [16-34 writes [health] and [timing] of config/paper/paper-runtime-v1.toml from the record, 16-15, 16-19, 16-22, 16-24, 16-26]
actuals:
  tokens: 14000
  tasks: 2
  commits: 2
plan_head_before: b6f6b714cd977f097a4a420235df717f39c84522
plan_head_after: 57fe5936d9ef9fc7da1cbbcc47afb063d06ac30b
commits: 2
requirements-completed: []
status: complete
---

# Phase 16 Plan 27: O-07 healthy-feed and timing numbers Summary

**The user ratified 11 paper-soak health and timing numbers (recorded verbatim in 16-DEC-O-07.md) and ratified every existing code constant as it is; the numbers define HEALTHY for the paper soak only, not LIVE thresholds.**

`commits: 2` counts the two code-free decision commits (table 43f724b, record 57fe593). The SUMMARY commit follows `plan_head_after`.

## Decision record

- Option `values`, decided by the user on 2026-10-10. Words verbatim: "ok.tôi duyệy". The reply approved the orchestrator's final proposal (the reviewer's 11-value set with one change: `max_ws_message_silence_seconds` 3900 instead of 15, because `coverage.py:525-651` judges silence on journaled evidence that arrives about hourly). The executor chose none of the numbers.
- `[health]`: max_ws_message_silence_seconds 3900, max_closed_bar_lateness_seconds 10, continuous_uncovered_ceiling_seconds 900, freeze_tick_grace_seconds 1800.
- `[timing]`: sibling_4h_wait_seconds 15, constraint_snapshot_ttl_seconds 2400, exchange_info_refresh_seconds 900, minute_poll_interval_seconds 2, minute_close_lag_seconds 5, healthcheck_max_bar_age_seconds 3900, rest_backfill_depth_bars 1500.
- Code constants: all `ratify current`. No CODE CHANGE REQUESTED, so the plan did not stop. The structural engine windows (1000/300) are not ratifiable here and are marked so in the table.
- Scope unchanged: coverage rules, freeze continuity and Q-D history-only.

## Consistency checks (run, all pass)

- All values positive; `minute_close_lag_seconds` 5 (zero allowed); `freeze_tick_grace_seconds` 1800 < 3600 (hourly cron slot); `constraint_snapshot_ttl_seconds` 2400 > `exchange_info_refresh_seconds` 900; `healthcheck_max_bar_age_seconds` 3900 > 3625; `sibling_4h_wait_seconds` 15 < `STALENESS_THRESHOLD_SECONDS` 60.
- `parse_runtime_config` accepted the 11 values (scratch run with throwaway account/scope, structure check only; no file written).
- `tests/test_paper_exit_evaluator.py`, `test_paper_coverage.py`, `test_coverage.py`, `test_paper_runtime_env.py`, `test_paper_runtime_admission.py`, `test_paper_runtime_compose.py`, `test_paper_market_inputs.py`: all pass.

## Deviations from Plan

- Task 1's "user value cells empty" check was true when the table was presented (commit 43f724b) and is intentionally no longer true after the user's values were recorded (57fe593). The `STRATEGY_WINDOW_BARS`/`CONTEXT_WINDOW_BARS` row reads "not applicable (structural)" rather than a value.
- No code, STATE.md or ROADMAP.md was edited.

## Known Stubs

None.

## Threat Flags

None.

## Notes for next plans

- Plan 16-34 writes `[health]` and `[timing]` from `16-DEC-O-07.md` verbatim; `[account]` and `[scope]` come from its own checkpoint.
- requirements-completed stays empty: PAPER-01/02 close only with real soak evidence (SC9).

## Self-Check: PASSED

- Files exist: decisions/16-O-07-table.md, decisions/16-DEC-O-07.md.
- Commits found: 43f724b, 57fe593.
- `grep -E "^option: (values|postpone)$"` matches in 16-DEC-O-07.md.
