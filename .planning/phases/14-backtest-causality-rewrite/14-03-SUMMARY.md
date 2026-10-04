---
phase: 14-backtest-causality-rewrite
plan: 03
subsystem: backtest
tags: [backtest, funding, causality, decimal, coverage, fail-closed, tdd]

requires:
  - phase: 14-backtest-causality-rewrite
    provides: "plan 14-01: MinuteSource/ListMinuteSource, FUNDING_MAX_CADENCE, FUNDING_JITTER, FUNDING_CONVENTION, tests/backtest_plan_helpers.py"
provides:
  - "src/backtest/funding.py: FundingRow, parse_funding_row, funding_pnl, OpenSegment, FundingEvent, FundingResult, FundingGap, FundingCoverageError, funding_events, check_funding_coverage"
  - "tests/test_backtest_funding.py: hand-computed funding oracles, TP1 segment, mark fallback and coverage tests (39 tests)"
affects: [14-04, 14-06, 14-07, 14-08, 14-10, 14-16]

actuals:
  tokens: 9300
  tasks: 2
  commits: 4
plan_head_before: 43ec983c7be8a4eab732deaeb0a99d1f2eb5ff19
plan_head_after: 3455dae3346dd18e3cdee5a0c4792c77e1595fc1

tech-stack:
  added: []
  patterns:
    - "Funding is a pure function of (symbol, direction, open-quantity segments, funding rows, mark source, allow-gaps, loaded range); no clock, no float"
    - "Coverage rule: a funding instant at or before the window start, one at or after its end, and no spacing above cadence plus jitter between, else FundingCoverageError carrying the holes"

key-files:
  created:
    - src/backtest/funding.py
    - tests/test_backtest_funding.py
  modified: []

key-decisions:
  - "The funding window is the span from the first segment start to the last segment end (one coverage check per holding window, not per segment); a zero-length window skips coverage because it cannot contain an instant"
  - "Holes are reported with the real neighbouring funding instants when one exists outside the extended range (so a 503 h hole reads as the two real rows), else the synthetic window edge"
  - "An allow-gap covers a hole only by full containment (same symbol, gap.start <= hole.start and gap.end >= hole.end); plan 14-10 must map Phase 13 GapRange values to these bounds"
  - "Mark fallback queries mark_minutes over (t - 60 s, t + 60 s] and selects open <= t < open + 60 s, so an instant in the last millisecond after the minute's close time still finds its own minute; a missing series or minute raises FundingCoverageError"
  - "Overlapping or unordered segments raise ValueError so one instant can never be charged twice"

patterns-established:
  - "RED skeletons return wrong values (never raise NotImplementedError) so the RED run fails on assertions, not on imports"

requirements-completed: [BKTS-01]

duration: 7min
completed: 2026-10-04
status: complete
---

# Phase 14 Plan 03: Funding Schedule, Sign Convention and Coverage Summary

**Pure funding module booking `-sign x open_quantity x markPrice(fundingTime) x rate` at every actual fundingTime inside a half-open holding window, with a mark-kline fallback and fail-closed cadence coverage whose only escape is an explicit, recorded same-symbol allow-gap.**

## Performance

- **Duration:** about 7 min (13:53Z to 14:00Z)
- **Completed:** 2026-10-04
- **Tasks:** 2 (1 tracer, 1 auto, both tdd)
- **Files:** 2 created (`src/backtest/funding.py`, `tests/test_backtest_funding.py`)

## Accomplishments

- Sign convention D-14 pinned by hand oracles (RESEARCH "Funding oracle"): LONG qty 0.5 over t1 rate +0.0001 mark 100 gives -0.005 (pays), over t2 rate -0.0002 mark 102 gives +0.0102 (receives), total +0.0052; SHORT gives +0.005, -0.0102, total -0.0052. The expected numbers are literals from hand arithmetic, not read back from the code.
- Half-open window `start <= fundingTime < end` at both ends: opened between two instants is not charged at the first, closed exactly at an instant is not charged there, opened exactly at an instant is charged. Rows are charged in time order regardless of input order; other symbols' rows are ignored.
- TP1 partial (D-36): segments `[entry, tp1)` qty 0.5 and `[tp1, exit)` qty 0.25 charge a later instant on 0.25 (t2 = +0.0051, total +0.0001), and an instant exactly at the TP1 time belongs to the remainder (-0.007575, total -0.007475).
- Mark price (D-15): the row's mark wins; only None or an empty string maps to missing; a missing mark uses the open of the mark minute containing the instant (99.80 gives -0.00499, `mark_from_kline` True), including an instant in the last millisecond after that minute's close time; a hole at that minute or no mark series for the symbol raises, never a neighbour minute.
- Coverage (D-36) with G = 8 h + 60 s: a 4 h series and an 8 h series cover; jitter of 7 h 59 m 59.990 s and 8 h 0 m 0.040 s is covered; a spacing of 8 h 1 m 1 s is a hole; a 503 h hole raises with `holes == (FundingGap(symbol, prev_row, next_row))` and the symbol and both bounds in the message; a window outside the loaded range raises. A same-symbol allow-gap that fully contains the hole lets the call succeed and is returned in `FundingResult.used_allowed_gaps` (a wider one works, an unneeded one is not recorded, another symbol's or a partial one does not cover).
- Duplicate `funding_time_utc` for one symbol raises ValueError; the same instant for two symbols is fine. Floats and naive datetimes are refused at parse time and in `funding_pnl`.

## Task Commits

1. **Task 1 (tracer): signed funding events, half-open window** - `6f42f27` (test, RED), `278c556` (feat, GREEN)
2. **Task 2: TP1 segments, mark fallback, coverage, allow-gaps** - `507173d` (test, RED), `3455dae` (feat, GREEN)

**Plan metadata:** committed separately after this file (docs: complete plan).

## Files Created/Modified

- `src/backtest/funding.py` - the whole funding contract (about 400 lines), docstring states the sign convention, window rule, the not-modeled 15 s grace (RESEARCH Pitfall 9) and assumption A2
- `tests/test_backtest_funding.py` - 39 tests

## Decisions Made

See `key-decisions` in the frontmatter. One note for later plans: `FundingGap` is a new name (the plan listed no type for an allow-gap), reused for both holes and allow-gaps.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test window in the "just beyond tolerance" case produced two holes**
- **Found during:** Task 2 GREEN
- **Issue:** the RED test `test_a_spacing_just_beyond_the_tolerance_is_a_hole` used a window ending at 12:00 while the last row was at 08:01:01. By the plan's own coverage rule (a row at or after the window end is required) that is a second, trailing hole, so asserting exactly one hole was a test mistake, not a code mistake.
- **Fix:** the window now ends at 08:00 (before the last row), isolating the single 8 h 1 m 1 s spacing hole. The rule itself is unchanged.
- **Files modified:** `tests/test_backtest_funding.py`
- **Commit:** `3455dae` (folded into the GREEN commit)

**Total deviations:** 1 auto-fixed (1 test bug). **Impact:** none on the contract.

## TDD Gate Compliance

Both tasks have a `test(14-03)` RED commit before their `feat(14-03)` GREEN commit; no refactor commits. `gsd_run check tdd-red-evidence` was not run; RED evidence, stated honestly:
- Task 1 RED (`6f42f27`): the module did not exist, so the RED commit carries a wrong-valued skeleton of `funding.py` (zero amounts, no validation) so the failures are assertions, not imports. 12 of 14 tests failed on assertions (for example `Decimal('0') != Decimal('-0.005')`, `DID NOT RAISE TypeError`); two passed on arrival by design (the exclusive-end case and the None-mark parse case, which the skeleton satisfied trivially).
- Task 2 RED (`507173d`, re-run from a `git archive` copy to count): the skeleton gained `FundingGap`, a no-op `check_funding_coverage` and the `holes` attribute. 13 of 39 tests failed (all 13 are among the 25 new tests), for example `DID NOT RAISE FundingCoverageError` for holes, loaded-range, allow-gap mismatch and a no-row window, `() != (FundingGap(...),)` for recorded allow-gaps, `DID NOT RAISE ValueError` for duplicates; the two fallback tests failed because the skeleton raised the older 'no mark price' error instead of using the kline. The other 12 new tests pinned behavior Task 1 already satisfied (TP1 segments, row-mark-wins, 4 h/8 h/jitter coverage, zero-length window, per-symbol duplicates).

## Issues Encountered

- A heredoc-based edit through the shell failed to parse because of apostrophes in the payload; the test additions were written to a scratchpad file and appended instead, with no effect on the result.
- `tests/test_backtest_funding.py` and `src/backtest/funding.py` were reformatted by `ruff format` between my reads; the harness reported them as changed and I re-read before editing.

## Verification (real output)

- `pytest tests/test_backtest_funding.py`: 39 passed. With `tests/test_backtest_purity.py` and `tests/test_domain_no_float.py`: 51 passed.
- Wider backtest regression (`test_backtest_entry`, `_expiry_clock`, `_lifecycle`, `_series`, `_simulator`): 115 passed.
- `ruff check` (whole repo): all checks passed; `ruff format --check`: 383 files already formatted; `mypy src`: no issues found in 141 source files.
- Acceptance greps all green: "0.0052" and "0.0102" in the tests, `def funding_pnl`, `def funding_events`, `class FundingCoverageError`, `def check_funding_coverage`, `FUNDING_MAX_CADENCE`, `FUNDING_JITTER`, `used_allowed_gaps` in the tests. The purity and no-float guards pick up the new module by glob and pass.
- Tracer gate (end-of-phase mode, automated verify only): re-ran the tracer verify, passed, then expanded.

## Regeneration inventory

none. No fixture, parameter set, pin or hash moved; `src/domain/enums.py` and the cost model are untouched. The `funding_convention` cost key and binding functions belong to the cost-identity plan.

## Known Stubs

None. Nothing is wired into the simulator yet: `simulator.py` still books zero funding until the engine plans call `funding_events` (14-07/14-08), and plan 14-10 owns the equality test between `FUNDING_MAX_CADENCE`/`FUNDING_JITTER` and `src/data/coverage.py` plus the mapping from Phase 13 `GapRange` to `FundingGap`.

## Threat Flags

None. T-14-06 (holes raise `FundingCoverageError`; only explicit same-symbol allow-gaps pass and are returned) and T-14-07 (LONG and SHORT oracles with positive and negative rates pin the sign) are mitigated by tests.

## Next Phase Readiness

Ready for the engine plans: they pass one `OpenSegment` per constant-quantity stretch (split at the TP1 instant), the loaded closed-UTC-day range, and the run's allow-gaps, and must record `FundingResult.used_allowed_gaps` on the run summary.

## Self-Check: PASSED

`src/backtest/funding.py` and `tests/test_backtest_funding.py` exist on disk, the four task commits (`6f42f27`, `278c556`, `507173d`, `3455dae`) are in `git log`, and every acceptance criterion and plan verification command re-ran green.

---
*Phase: 14-backtest-causality-rewrite*
*Completed: 2026-10-04*
