---
phase: 24-live-runtime-composition-demo
plan: 02
subsystem: domain
status: complete
tags: [rejection-reason, glossary, health, enablement, g3-005, g2-035]
requirements-addressed: [EXEC-01, OPS-02]
requires: []
provides:
  - "RejectionReason.NO_FILL and RejectionReason.HEALTH_CHECK_FAILED (23 members)"
  - "check_rest_error_rate refuses error_count above total_count as a FAIL result"
affects: [24-22, 24-32]
tech-stack:
  added: []
  patterns:
    - "plain-string code promoted to the enum with an identical value, emitters read .value"
key-files:
  created: []
  modified:
    - src/domain/enums.py
    - src/execution/manager.py
    - src/ops/health.py
    - src/approval/reason_codes.py
    - docs/GLOSSARY.md
    - scripts/decision_alignment/bookkeeping.py
    - tests/test_domain_enums.py
    - tests/test_phase19_gate.py
    - tests/test_phase20_gate.py
    - tests/test_phase21_gate.py
    - tests/test_phase22_gate.py
    - tests/test_phase23_gate.py
    - tests/test_margin_guard.py
    - tests/test_pre_placement.py
    - tests/test_telegram_authorization.py
    - tests/test_execution_health.py
    - tests/test_execution_manager.py
    - tests/test_decision_alignment_bookkeeping.py
    - tests/test_backtest_engine.py
    - tests/test_daily_loss.py
    - tests/test_geometry_audit_doc.py
key-decisions:
  - "NO_FILL and HEALTH_CHECK_FAILED are enum members with the same string values; GLOSSARY 9.1 holds them, 9.3 no longer does (G3-005, D-35)."
  - "check_rest_error_rate returns a FAIL result (not ValueError) for error_count above total_count; negative counts keep raising ValueError."
metrics:
  tasks: 3
  commits: 2
plan_head_before: f48f6d6eeb3b564c8ee565953791b92149e5565f
plan_head_after: a626d6283948ad8ad40d660580d849f7205da26e
commits: 2
actuals:
  tokens: 14000
  tasks: 3
  commits: 2
completed: 2026-10-31
---

# Phase 24 Plan 02: Promote NO_FILL and HEALTH_CHECK_FAILED, triage G2-035 Summary

`RejectionReason` now has 23 members: `NO_FILL` and `HEALTH_CHECK_FAILED` were promoted from the GLOSSARY 9.3 plain-string list with unchanged string values, the manager and health module emit them through the enum, and the Phase 9 warnings IN-06 and IN-07 are fixed, with IN-01 and IN-05 closed as won't-fix with reasons.

## What was built

- `src/domain/enums.py`: two appended members (no reorder, no existing value touched).
- `src/execution/manager.py`: the no-fill `AttachOutcome` reason is `RejectionReason.NO_FILL.value`.
- `src/ops/health.py`: the failing `HealthVerdict` reason and its validator use `RejectionReason.HEALTH_CHECK_FAILED.value`; the module docstring now names `src/domain/enums.py` as an allowed import.
- `docs/GLOSSARY.md`: both codes added to the 9.1 block with an explanatory paragraph, their two rows removed from 9.3, and the 9.1/9.2/9.3 prose now says 23 members (21 through Phase 23).
- `scripts/decision_alignment/bookkeeping.py`: GL-05 no longer expects the two codes in 9.3 (GL-03 now covers them in 9.1).
- Eleven size pins moved from 21 to 23, each message naming G3-005 (D-35); the Phase 23 gate gained invariant 5h (both codes in 9.1, absent from 9.3).

## G2-035 triage

- **IN-07: fixed.** `check_rest_error_rate` returns a FAIL result when `error_count > total_count` (never a pass, never a rate above 1); `check_telegram_delivery` also treats a `False` send result as FAIL. Tests in `tests/test_execution_health.py` pin the over-count FAIL, the equal-count boundary and the False send result.
- **IN-06: fixed (argument half), won't-fix (validator half).** The manager passed `approval.trade_plan_id` as `plan_hash`; it now passes `bound.plan_hash`, pinned by `test_the_enablement_guard_receives_the_bound_plan_hash_not_the_plan_id`. The guard ignores the argument, so no journal schema or behavior changed. The `EnablementVerdict` validator still accepts `is_no_trade=False` with a non-None reason code; `src/execution/enablement.py` is outside this plan's file set and a sibling Phase 24 plan may own it, so the one-line tightening is left for the plan that edits that file.
- **IN-01: won't-fix.** Removing the `src/adapters/binance_usdm.py` E501 ignore from `pyproject.toml` produces 17 E501 errors (an `--isolated --select E501` run), mostly the long module docstring table and `# noqa: E501` lines that have no effect inside a string. Reflowing the adapter docstring is outside this plan; `pyproject.toml` and `uv.lock` are unchanged.
- **IN-05: won't-fix.** The `tests/fixtures/phase9/gates/*` fixtures have no generator script in `scripts/` (they are hand-written JSON), so a 197+3 headroom case would be a new hand-typed fixture, which AGENTS.md forbids. Splitting the uncertain-state test and asserting `daily_state` belong in a test-only change in `tests/test_execution_gates.py`, not in this plan.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Extra files carried an enum-size pin or the GL-05 list**
- **Found during:** Task 2 (searching `len(RejectionReason)` and `== 21` beyond the plan's list)
- **Issue:** `tests/test_backtest_engine.py`, `tests/test_daily_loss.py`, `tests/test_geometry_audit_doc.py`, `tests/test_decision_alignment_bookkeeping.py` (and the `len(tokens) == 21` check in `tests/test_domain_enums.py`) pin the enum size or the 9.1 block size; `scripts/decision_alignment/bookkeeping.py` listed the two codes as required 9.3 plain strings (gate GL-05), which would fail once they moved.
- **Fix:** updated the pins to 23, removed the two codes from `STRING_CODES`, added `PHASE_24_CODES` to the referenced-code allow-set, and pointed the GL-05 negative test at `EXPIRED`. `src/approval/reason_codes.py` had a docstring saying 21 members; updated to 23.
- **Files modified:** the files listed above
- **Commit:** d73b1798, a626d628

**2. [Rule 3 - Blocking] Phase 23 gate 5f required "21 members" in the 9.3 introduction**
- **Fix:** the introduction now states both counts and 5f asserts "21 members through Phase 23" and "23 members since Phase 24".
- **Commit:** d73b1798

**3. [Plan correction] Acceptance grep for "proposed canonical, promote in Phase 24"**
- The criterion expects no output, but about twenty other 9.3 rows (binding and pre-placement codes) carry that status and are not part of this plan. Only the NO_FILL and HEALTH_CHECK_FAILED rows were in scope; both are gone (`git grep` for those two codes with that status returns 0).

**4. [Format] `ruff format` applied to the twelve test files whose long G3-005 messages exceeded line length 100.**

## Verification

- Plan tests (domain enums, phase 19..23 gates, execution health, manager, enablement, attach, margin guard, pre-placement, telegram authorization, bookkeeping alignment, geometry audit doc, daily loss, backtest engine, demo rehearsal flow, agents md): all passed.
- `uv run ruff check src tests scripts`: clean. `uv run mypy src`: no issues in 263 files. `uv lock --check`: passes; `uv.lock` unchanged.
- `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- The full suite was not run (orchestrator runs it once per phase).

## Known Stubs

None.

## Threat Flags

None. T-24-03 mitigated (over-count is a FAIL); T-24-04 mitigated (string values byte-identical, Phase 23 and golden tests green); T-24-SC mitigated (no dependency change).

## Self-Check: PASSED

Commits d73b1798 and a626d628 are on `develop`; all modified files exist.
