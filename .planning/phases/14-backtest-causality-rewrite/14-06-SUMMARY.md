---
phase: 14-backtest-causality-rewrite
plan: 06
subsystem: analytics
tags: [analytics, live-outcomes, r-denominator, parity, tdd, decimal]

requires:
  - phase: 14-backtest-causality-rewrite
    provides: "realized_risk_for_fill (14-01, D-20) and the v2 TradeRecord built by build_trade_record"
provides:
  - "src/analytics/live_outcomes.py: frozen SizedRisk(realized_risk, planned_quantity) and keyword-only sized_risks on normalize_live_outcomes"
  - "Live realized_risk computed through realized_risk_for_fill; plan.risk_budget is no longer a denominator anywhere in src/analytics (F-204)"
  - "tests/test_r_denominator_parity.py: backtest/live R parity on identical zero-funding trades (ROADMAP Phase 14 criterion 4)"
affects: [14-07, 14-08, 14-12, 14-15, 14-16]

actuals:
  tokens: 5200
  tasks: 2
  commits: 3
plan_head_before: 4a4b4c910a7d05c0f5864e34e9851794a30a4cc7
plan_head_after: ba653a4e7f75f025e120f447a1a5678ef47811d6

tech-stack:
  added: []
  patterns:
    - "Explicit optional sized input keyed by trade_plan_id instead of a persisted column (D-29)"
    - "Parity proven by pushing one hand-derived trade through two independent paths and comparing realized_risk and R"

key-files:
  created:
    - tests/test_r_denominator_parity.py
  modified:
    - src/analytics/live_outcomes.py
    - tests/test_analytics_live_outcomes.py

key-decisions:
  - "D-29 honored: no database column, migration or store method; the sized figure is a caller-supplied Mapping[str, SizedRisk], and its absence leaves the outcome INCOMPLETE(NO_RISK_VALUE)"
  - "A filled quantity above the sized planned quantity is a MALFORMED_ROW (outcome dropped, listed), not an exception and not a clamp"
  - "SizedRisk rejects non-Decimal, non-finite and non-positive fields with AnalyticsInputError at construction; a non-SizedRisk map entry also raises"
  - "src/analytics/cli.py is untouched: it keeps calling normalize_live_outcomes positionally, so live CLI outcomes now carry realized_risk None until a later phase supplies the sized figure"

patterns-established:
  - "Parity oracle uses a fee-only cost model (zero modeled slippage) because a live fill price already embeds slippage, and zero funding because LIVE_R_EXCLUDES funding"

requirements-completed: [BKTS-04]

duration: 15min
completed: 2026-10-04
status: complete
---

# Phase 14 Plan 06: Single R Denominator for Live Summary

**Live R now divides net PnL by `realized_risk_for_fill(sized, planned, filled)`, the same function the backtest record uses, and a parity test proves identical `realized_risk` and R on the same trade; `plan.risk_budget` is gone as a denominator.**

## Performance

- **Duration:** about 15 min wall time (21:45 to 22:00 +07:00 by commit timestamps, including the 9 min full-suite run; the start time was not captured in a shell variable)
- **Completed:** 2026-10-04
- **Tasks:** 2 (1 tracer, 1 auto, both tdd)
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments

- Parity oracle (LONG, limit 100.00, stop 98.00, tick 0.10, sized risk 50, planned 0.5, fee rate 0.0004, zero funding, zero modeled slippage): filled 0.5 gives gross -1.00, fees 0.0200 + 0.0196, net -1.0396, realized_risk 50, R -0.020792; filled 0.25 gives net -0.5198, realized_risk 25, R -0.020792. The backtest path (`advance` -> `build_trade_record` -> `normalize_backtest`) and the live path (rows -> `normalize_live_outcomes(..., sized_risks=...)`) agree on `realized_risk`, `realized_pnl` and R in both cases.
- Live without `sized_risks` (or with a sized figure for a different plan) yields `realized_risk` None and `(signal_id, NO_RISK_VALUE)` even though `plan.risk_budget` is positive (T-14-12). The AST acceptance check confirms no `risk_budget` attribute access remains in `live_outcomes.py`.
- `SizedRisk` validation (Decimal, finite, positive), partial-fill scaling (planned 4.0, filled 2.0 gives half of 10.00 and R 1.34), overfill as MALFORMED_ROW, and the fail-closed default (unverified semantics plus no sized input lists NO_RISK_VALUE for every candidate) are pinned in `tests/test_analytics_live_outcomes.py`.
- No file under `src/db/` and no alembic migration changed.

## Task Commits

1. **Task 1: Tracer** - `2db9498` (test, RED), `0a1f3c6` (feat, GREEN)
2. **Task 2: Migrate live-outcome tests** - `ba653a4` (test)

**Plan metadata:** committed separately after this file (docs: complete plan).

## Files Created/Modified

- `src/analytics/live_outcomes.py` - `SizedRisk`, keyword-only `sized_risks`, `realized_risk_for_fill` call, docstring names the shared function and D-29
- `tests/test_r_denominator_parity.py` - 4 cases: parity at full and partial fill, absent sized input, sized input for an unrelated plan
- `tests/test_analytics_live_outcomes.py` - `_Rows` passes `sized_risks` equal to the old budgets with full fills; budget test replaced; 8 new cases (14 parametrized assertions)

## Decisions Made

See `key-decisions` in the frontmatter. One behavior goes beyond the plan text: a live entry quantity above the sized planned quantity cannot be passed to `realized_risk_for_fill` (it raises), so the normalizer treats it as `MALFORMED_ROW` and drops the outcome, consistent with the existing non-positive-fill handling.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical] Overfill and non-SizedRisk map entries fail closed**
- **Found during:** Task 1
- **Issue:** `realized_risk_for_fill` raises `ValueError` when filled exceeds planned; letting that escape from a live-row normalizer would abort a whole report on one bad row, and a non-SizedRisk map value would surface as an `AttributeError`.
- **Fix:** overfill becomes `(signal_id, MALFORMED_ROW)` and the candidate is skipped; a non-`SizedRisk` entry raises `AnalyticsInputError`.
- **Files modified:** src/analytics/live_outcomes.py, tests/test_analytics_live_outcomes.py
- **Commit:** 0a1f3c6 (code), ba653a4 (tests)

### Other notes

- Commit `0a1f3c6` (Task 1 GREEN) leaves `test_verified_semantics_branch_gives_net_r` and `test_unverified_semantics_branch_is_fail_closed` failing until `ba653a4` migrates them, as the plan splits the work across the two tasks. The history is not bisect-green between those two commits.
- A mypy variable-reuse error found during Task 1 was fixed before the GREEN commit (loop variable renamed), so it is not a separate commit.

**Total deviations:** 1 auto-fixed (Rule 2). **Impact:** none on the plan's interfaces.

## TDD Gate Compliance

`test(14-06)` RED (`2db9498`) precedes `feat(14-06)` GREEN (`0a1f3c6`). RED evidence, stated honestly: of the 4 parity tests, 1 failed on a real assertion (`assert Decimal('1.50') is None`, the old `risk_budget` denominator); the other 3 failed with `AttributeError` on `live_outcomes.SizedRisk` because the API did not exist yet. Collection succeeded (module attribute access inside tests, no top-level import of the new name). `gsd_run check tdd-red-evidence` was not run. Task 2 migrated existing tests after the GREEN commit; no refactor commit was needed.

## Verification (real output)

- Plan verify: `pytest tests/test_analytics_live_outcomes.py tests/test_r_denominator_parity.py tests/test_analytics_cli.py tests/test_analytics_render.py tests/test_analytics_report.py` all passed (no failures or errors).
- All analytics tests (`tests/test_analytics_*.py`): all passed, 2 pre-existing skips.
- Parity tests alone: 4 passed (plan requires at least 3).
- `ruff check src/analytics tests`: All checks passed. `ruff format --check src tests`: already formatted. `mypy src`: `Success: no issues found in 143 source files`.
- Acceptance: `grep -c realized_risk_for_fill src/analytics/live_outcomes.py` = 4; AST check prints `AST OK`; `git diff --name-only` shows nothing under `src/db/` or alembic; `grep -c sized_risks tests/test_analytics_live_outcomes.py` = 12.
- Full suite `uv run pytest -m "not docker" -rs -p no:cacheprovider`: `3537 passed, 423 skipped, 17 deselected in 549.53s (0:09:09)`. Skips are the pre-existing PostgreSQL tests (`TEST_DATABASE_URL is not set`).

## Regeneration inventory

none. No fixture, golden or digest moved: `tests/fixtures/phase10/live_net_r/expected.json` (realized_risk, r and both result digests) is unchanged because the migrated tests pass sized figures equal to the old budgets with full fills, and the CLI, render and report tests needed no regeneration. The only behavior shift is outside any pinned output: the production live CLI path (`src/analytics/cli.py`) passes no `sized_risks`, so its LIVE outcomes now carry `realized_risk` None (R was already INCOMPLETE there because `LIVE_NET_PNL_SEMANTICS_VERIFIED` is False).

## Known Stubs

None. The live CLI not supplying `sized_risks` is the intended D-29 state (INCOMPLETE until a later phase persists the sized figure), not a stub.

## Threat Flags

None. T-14-12 (live R denominator repudiation) is mitigated: the `risk_budget` denominator is removed (AST check) and an absent sized input gives INCOMPLETE(NO_RISK_VALUE), never an imputed value.

## Next Phase Readiness

The single-denominator contract is in force for both paths. A later phase that persists the sized figure only needs to build the `sized_risks` mapping and pass it from `src/analytics/cli.py`.

## Self-Check: PASSED

`tests/test_r_denominator_parity.py` exists, commits `2db9498`, `0a1f3c6` and `ba653a4` are in `git log`, and every task acceptance criterion and plan-level verification command re-ran green (see Verification).

---
*Phase: 14-backtest-causality-rewrite*
*Completed: 2026-10-04*
