---
phase: 16-paper-runtime-composition
plan: 12
subsystem: research feasibility gate (reporting only)
status: complete
tags: [feasibility, sample-size, g1, g5, holdout, d-26, rev-06, q-o]

requires:
  - phase: 16-paper-runtime-composition
    provides: "16-06 research runner (run_research, research_splits, trade lists per window)"
provides:
  - "src/research/feasibility.py: G1_POOLED_FLOOR=100, G1_PER_FOLD_FLOOR=30, G5_HOLDOUT_FLOOR=30, G5_NOT_ASSESSED_LINE, count_closed_trades, feasibility_report, render_feasibility"
  - "src/research/run.py prints the feasibility counts per grid point and the G5 line after the neutral record lines; records are unchanged"
  - "decisions/16-DEC-Q-O.md: user decision, option not-assessed"
affects: [16-37 first real research run (G3-027 now measurable), phase 26 G5 evaluation]

requirements-completed: []

actuals:
  tokens: 21000
  tasks: 3
  commits: 5
plan_head_before: 451351312aa482a03bfe3554558775b15ddb1a28
plan_head_after: 94b44e1c253131e6437e110ca97d1be6b819d8b6
commits: 5

tech-stack:
  added: []
  patterns:
    - "Reporting-only gate: no rank, order, score or verdict field; shortfalls are plain text; floors are Final constants pinned to the protocol sentences by an alignment test"
    - "The closed-trade rule is imported from backtest semantics and pinned by test to the private sets in src/backtest/report.py (report.py untouched)"

key-files:
  created:
    - src/research/feasibility.py
    - tests/test_research_feasibility.py
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-Q-O.md
  modified:
    - src/research/run.py

key-decisions:
  - "Q-O: option not-assessed, decided by the user (reply 'not-assessed (Recommended)'), 2026-10-09. The holdout is never counted, extrapolated or simulated; the gate prints 'G5 floor not assessed (holdout untouched)' once per run. No other option is implemented."
  - "Development closed and END_OF_DATA counts are reported beside the Validation counts (option text: Development and Validation counts only); Development carries no floor."

patterns-established:
  - "Holdout-untouched proof: a spy on simulator.run asserts every requested window starts and ends at or before holdout_start_utc, holdout_consumed.json is byte-identical after a run, and feasibility.py contains no reference to the simulator, the marker or the holdout bounds"
---

BKTS-03 is claimed by this plan's frontmatter but is not marked complete here (other plans claim it; left to requirements.ready-ids).

# Phase 16 Plan 12: Feasibility and sample-size gate Summary

Reporting-only G1 trade-floor feasibility (100 pooled, 30 per fold, closed = SL or TP2, END_OF_DATA apart) appended to the research runner output, with the G5 floor printed as "not assessed (holdout untouched)" per the user's Q-O decision.

## Tasks

| Task | Name | Commits |
| ---- | ---- | ------- |
| 1 | Tracer: G1 pooled and per-fold counts | 4002ba8 (RED), bb1fed2 (GREEN) |
| 2 | Checkpoint Q-O (user decision, not-assessed) | 2436bfe |
| 3 | G5 not-assessed reporting and holdout-never-simulated guard | 2445086 (RED), 94b44e1 (GREEN) |

## Verification

- `tests/test_research_feasibility.py` and `tests/test_research_runner.py` pass; `ruff check`, `ruff format --check` and `mypy src` clean.
- `git diff 451351312aa482a03bfe3554558775b15ddb1a28 -- src/backtest` is empty.
- Decision grep verify passes (`option: not-assessed`).
- Threat T-16-29: spy test proves no holdout window is simulated; the marker is byte-identical after a run. T-16-30: alignment test pins the floors to the protocol sentences.

## Deviations from Plan

None - plan executed as written. Task 3 added Development counts to the report (not an extra option: it is the "Development and Validation counts" wording of the chosen option).

## Known Stubs

None.

## Threat Flags

None.

## Self-Check: PASSED
