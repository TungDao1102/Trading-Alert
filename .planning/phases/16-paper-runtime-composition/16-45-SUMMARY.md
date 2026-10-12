---
phase: 16-paper-runtime-composition
plan: 45
subsystem: research preregistration (closure-chain step O-02, L-10)
tags: [hypothesis, parameter-grid, preregistration, draft, o-02]

requires:
  - phase: 16-paper-runtime-composition
    provides: "plans 16-40 (runtime and SHADOW chain proven) and 16-13 (src/research/register.py candidate validator)"
provides:
  - "docs/research/preregistration/research-run-1-hypothesis-DRAFT.md: agent draft of the hypothesis and parameter grid, labelled DRAFT, not approved"
affects: [16-45 Task 2 (user decision O-02), 16-45 Task 3 (registration), 16-46 (research run, needs a separate user authorization)]

requirements-completed: []

status: tracer done, Task 2 (O-02) pending user, Task 3 not started
actuals:
  tokens: 4800
  tasks: 1
  commits: 1
plan_head_before: 0501acd6bd75249e1e6b0754e92e3494fc7bb7a5
plan_head_after: e9eb307276dd38e9c33a68050f9ae6c9ab06e8af
commits: 1

tech-stack:
  added: []
  patterns:
    - "Draft states provenance label, rationale and source per value; fixed seed values of baseline-v6 that carried the placeholder basis are proposed as EXPERIMENT (preregistered fixed setting), flagged as a question for the user"

key-files:
  created:
    - docs/research/preregistration/research-run-1-hypothesis-DRAFT.md
    - .planning/phases/16-paper-runtime-composition/16-45-SUMMARY.md
  modified: []

key-decisions:
  - "Nothing chosen on the user's behalf: which family or families to run is an explicit open question (draft section 0, question 1)"

patterns-established: []

requirements: [PAPER-01]
---

# Phase 16 Plan 45: Hypothesis and parameter grid (tracer) Summary

Status: tracer done, Task 2 (O-02) pending user, Task 3 not started. Task 1 (the tracer) produced a sourced, plain-language DRAFT of the first research run hypothesis and grid for the user to approve, change, replace or postpone. No requirement is complete: `requirements-completed` is empty.

Plan base (HEAD before Task 1): `0501acd6bd75249e1e6b0754e92e3494fc7bb7a5`. This is the commit that Task 3's `git diff --name-only --diff-filter=MDR <plan-base> -- params/` test must use.

## What was built

`docs/research/preregistration/research-run-1-hypothesis-DRAFT.md` (commit `e9eb307`):

- Line 1 is "DRAFT - not approved by the user; drafted without any backtest or research result".
- Section 0 lists six questions for the user (see below). Section 1 states the rules (closed-bar, no result used, labels, frozen protocol v2.2.0 untouched).
- Section 2 is the table of values fixed in every family (25 rows), each with label, rationale and source. `max_cost_to_risk` stays 0.15 with the note "revisit only by a new set chosen before any result, D046 item 6".
- Section 3 lists `signal_expiry_hours` as a candidate parameter in every family (values 4 and 8).
- Sections 4 to 6: one hypothesis per family (trend-pullback, breakout-retest, range-mr) with four varied parameters each, a full 2 x 2 x 2 x 2 grid of 16 points per family, ids `research-run-1-a01..a16`, `b01..b16`, `c01..c16` in grid-file order. 48 points in the draft in total, at most 16 per family (budget 25 per family).
- Sections 7 and 8: what happens after the decision, and what the draft does not claim.

Varied parameters: A pivot width (3, 5), `zone_tolerance_atr` (0.5, 1.0), `sl_buffer_atr` (0.2, 0.5), `signal_expiry_hours` (4, 8); B `retest_window_bars` (5, 10), `retest_depth_atr` (0.3, 0.6), `zone_tolerance_atr` (0.5, 1.0), `signal_expiry_hours` (4, 8); C `regime_filter_lookback` (50, 100), `zone_min_touches` (2, 3), `range_break_buffer_atr` (0.2, 0.5), `signal_expiry_hours` (4, 8). Seed values come from `baseline-v6`; the second value of each pair is the drafter's design choice and is stated as such.

Verification: the plan's automated check printed `True` (DRAFT line within the first three lines, no value row labelled with the placeholder basis). The registry and simulator were not run (out of scope for this run).

## What the user must decide

Nothing below was pre-selected by the executor. Task 2 (checkpoint O-02, `blocking-human`) takes one of: approve-as-drafted, approve-with-changes (with the changes written), user-writes-own, postpone. The decisions that the draft leaves open:

1. **Which family or families run 1 covers** (trend-pullback, breakout-retest, range-mr; any subset). Choosing among families adds an uncorrected layer on top of Holm inside a family (about 14% worst-case false-pass rate for three families, protocol section 4).
2. **Grid shape**: is a 16-point full grid per family acceptable, or another design / other varied parameters / other values (limit: 25 points per family).
3. **Provenance labels for fixed seed values**: values such as `min_stop_atr` 0.5, `swing_lookback` 20, `atr_period` 14 and the three portfolio caps had the placeholder basis in `baseline-v6` and have no empirical basis. A registered candidate may carry no placeholder label, so the draft labels them EXPERIMENT (a preregistered fixed setting, not evidence). The user decides whether that label is acceptable.
4. **`max_cost_to_risk`**: kept at 0.15; the user may put a revisit into the grid now, before any result exists.
5. **`signal_expiry_hours`**: varied as a candidate parameter (4, 8); the user may fix or change it (O-08).
6. **Anything to add** (another hypothesis, parameter or value).

A reply outside the four ids is recorded as `option: other` and the plan stops (plan Task 2). Approval does not authorize a research run (O-03, plan 16-46).

## Deviations from Plan

None - the plan was executed as written for Task 1. Two notes:

- The task commit was made on `master` in the main working tree as instructed; `.planning/config.json` has `git.branching_strategy: none` and all earlier Phase 16 commits are on `master`, so the generic protected-branch guard was not treated as a halt.
- The draft proposes, but does not decide, that Task 3 gives the new sets a new `strategy_version` (settled against the registry gate at Task 3).

## Known Stubs

None.

## Threat Flags

None. The draft adds no network, auth or schema surface. T-16-101 (values taken from results or tuned): mitigated so far by labelling DRAFT, a source for every value and no result being available (`docs/research/holdout_consumed.json` has no entries).

## Self-Check: PASSED

- `docs/research/preregistration/research-run-1-hypothesis-DRAFT.md` exists; commit `e9eb307` exists; the plan's automated verify passed.
- Not done by design: Task 2 (user decision), Task 3 (registration), ROADMAP.md and STATE.md updates (the orchestrator owns them).
