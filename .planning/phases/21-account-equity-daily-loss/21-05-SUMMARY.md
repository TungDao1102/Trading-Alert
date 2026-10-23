---
phase: 21-account-equity-daily-loss
plan: 05
subsystem: risk
tags: [daily-loss, daily-stop, d033, fail-closed, pure-functions]
requires:
  - phase: 18
    provides: shared derive_daily_state / resolve_absolute_thresholds rules
provides:
  - "src/risk/daily_loss.py: LossComponent fold, day-start thresholds, sticky DAILY_STOP latch, alert decisions, day-open rule"
affects: [21-09, 21-10, 21-13, 21-16]
tech-stack:
  added: []
  patterns: ["pure functions of rows and an injected time", "fail closed to UNCERTAIN_ACCOUNT_STATE with a blocked_reason"]
key-files:
  created: [src/risk/daily_loss.py, tests/test_daily_loss.py]
  modified: []
key-decisions:
  - "utc_day is a datetime.date; utc_day_of(at) returns the date, utc_day_start(day) the 00:00 UTC datetime"
  - "Threshold validity (all five portfolio keys typed, warning <= stop) is checked on the live path before derive_daily_state, because derive_daily_state answers NORMAL for a malformed set"
  - "Latch wins over unknown loss and over invalid thresholds"
requirements-addressed: [RISK-02]
status: complete
duration: 40min
completed: 2026-10-23
commits: 2
plan_head_before: 7de64d6ebeac513a10d68621d0375421bc8dde4f
plan_head_after: aa2645403f65529d2f791e850b03c9b35d511ccf
actuals:
  tokens: 12700
  tasks: 2
  commits: 2
---

# Phase 21 Plan 05: Live daily-loss rules Summary

Pure live D033 daily-loss rules: component fold with most-adverse-per-key, thresholds against the persisted day-start base, a sticky DAILY_STOP latch, once-only alert decisions, and the day-open rule; all fail closed and share `derive_daily_state` / `resolve_absolute_thresholds` with the backtest.

## What was built

- Task 1 (tracer, commit 4066b4bb): enums `ComponentKind`, `ComponentSource`, `FundingPolicy`; `FUNDING_SOURCE_VERIFIED: bool = False` and the label and blocked-reason constants; frozen dataclasses `LossComponent`, `DayRiskState`, `DailyLossResult`; `utc_day_of`, `utc_day_start`, `fold_daily_loss`, `day_thresholds`. Fold order: day check, completeness flags, funding policy, duplicate check per (kind, source, key), asset check, group by (kind, source_key) taking the smallest signed amount, sum with the pinned Decimal helpers, `loss = max(0, -sum)`.
- Task 2 (commit aa264540): `DayOpenAction`, `DayStateVerdict`, `evaluate_day_state`, `blocked_verdict`, `day_open_action`, `base_is_inside_day`.
- Tests: `tests/test_daily_loss.py`, 91 tests, one or more per behavior bullet of both tasks (literal oracles: base 1000, loss 5 = WARNING, loss 10 = DAILY_STOP).

## Verification

- `uv run pytest -m "not docker" tests/test_daily_loss.py` : 91 passed.
- `tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_phase20_gate.py tests/test_risk_portfolio.py tests/test_backtest_ledger.py` : all passed.
- `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_persistence_exit_evidence_pg.py` : all passed (TEST_DATABASE_URL set in the environment; value not read).
- `uv run mypy src/risk/daily_loss.py`, `ruff check`, `ruff format --check` on the two files: clean.
- `git diff --exit-code -- src/risk/portfolio.py src/backtest params pyproject.toml uv.lock`: exit 0.
- Evidence label: executed unit tests [DESIGN]; no [DEMO] claim. realizedPnl semantics stay unverified on mainnet (G2-042).

## Deviations from Plan

None - plan executed as written.

Notes (not deviations):
- `utc_day` type: the plan did not fix it; chosen `datetime.date` (matches the research table keyed by UTC date).
- `evaluate_day_state` imports `_extract_thresholds` (module-private) from `src/risk/portfolio.py` to detect a parameter set that `derive_daily_state` would silently turn into NORMAL. `portfolio.py` is unchanged. If plans want a public name, that is a one-line follow-up outside this plan.
- `plan_head_before` is the HEAD when this plan started on the shared tree; siblings 21-02, 21-03, 21-04 and 21-06 committed on the same branch meanwhile, so `git rev-list --count plan_head_before..HEAD` would show 9. This plan's own commits are the 2 above (`git log --grep "(21-05)"`).
- Windows CRLF: new files are written LF; git warns that LF will be replaced by CRLF on checkout (autocrlf), no content effect.

## Known Stubs

None.

## Issues / for the owner

- O-2 (funding policy) is not decided here: both `FundingPolicy` members exist and no default is chosen; callers must pass one. Under `REQUIRE_VERIFIED_FUNDING_SOURCE` the day loss is unknown until `FUNDING_SOURCE_VERIFIED` is set True (needs observed income rows, Phase 24/26).
- Open Question 5: the operator acknowledgement path for a missing day state with exposure is not built (BLOCKED_MISSING_STATE until reconstructed); owner item.
- Inverted warning/stop thresholds are rejected on the live path only (ROADMAP 999.3 Phase 05 IN-03); the shared `portfolio.py` rule still accepts them.

## Threat Flags

None.

## Self-Check: PASSED

- src/risk/daily_loss.py and tests/test_daily_loss.py exist; commits 4066b4bb and aa264540 exist.
