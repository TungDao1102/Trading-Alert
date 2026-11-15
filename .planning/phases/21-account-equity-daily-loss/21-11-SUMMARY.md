---
phase: 21-account-equity-daily-loss
plan: 11
subsystem: execution
tags: [live-risk-inputs, release-reasons, parity, fail-closed, pure-functions]
requires:
  - phase: 21
    provides: "21-04 LiveEquityResult, 21-05 DayRiskState/DayStateVerdict/day_thresholds, 21-06 reservations"
provides:
  - "src/execution/live_risk_inputs.py: build_live_risk_inputs, LiveRiskInputs, LiveRiskInputsResult, five release_reason_for_* mappings, FINAL_PLACEMENT_REFUSALS"
affects: [21-14, phase-24]
tech-stack:
  added: []
  patterns: ["current equity sizes, persisted day-start base gates", "reason-coupled result dataclass", "enum-exhaustive parametrized mapping tests"]
key-files:
  created: [src/execution/live_risk_inputs.py, tests/test_live_risk_inputs.py, tests/test_live_risk_parity.py]
  modified: []
key-decisions:
  - "FINAL_PLACEMENT_REFUSALS is defined in live_risk_inputs.py from the three pre_placement constants (pre_placement.py has no such set and is not edited)"
  - "A verdict with a state but no loss_quote is UNCERTAIN_ACCOUNT_STATE; a latched day returns DAILY_STOP_BLOCK before any loss is read"
  - "release_reason_for_protection_state imports the ProtectionState enum from src.execution.protection (type check by enum); the module itself imports no adapter, persistence or SDK module"
requirements-addressed: [RISK-01, RISK-02, EXEC-01]
status: complete
duration: 25min
completed: 2026-10-23
commits: 1
plan_head_before: 848fafee566c05c53d2a82216a8f779bbf759d58
plan_head_after: 05225a8af900dbd4b50e9d938780c467ffb30fa9
actuals:
  tokens: 14000
  tasks: 3
  commits: 1
---

# Phase 21 Plan 11: Live risk-input builder Summary

`build_live_risk_inputs` assembles the four `evaluate_risk` inputs the manager takes from `risk_kwargs` (current-equity `AccountState` for sizing, counted open positions minus the candidate, the day's loss, thresholds resolved against the persisted day-start base) from the Phase 21 live sources, fails closed on every unknown, blocks a latched day, and maps every terminal plan state to a reservation release reason; parity tests show the same open positions, thresholds and `check_portfolio` verdicts as the backtest ledger.

## What was built

- `LiveRiskInputs` (with `as_risk_kwargs()` returning exactly the four keys) and `LiveRiskInputsResult` (reason "OK" with inputs; UNCERTAIN_ACCOUNT_STATE or DAILY_STOP_BLOCK without).
- `build_live_risk_inputs` order: equity unknown, day/verdict missing, day mismatch, latched DAILY_STOP, verdict without state or loss, invalid thresholds, unexplained exchange exposure. No default is substituted.
- Release mappings: approval (EXPIRED/SKIPPED), plan (EXPIRED/INVALIDATED/SUPERSEDED, plus READY/APPROVAL_PENDING/APPROVED at `now_utc >= expiry_utc`), final placement refusal (PLAN_STATUS_INVALID, PLAN_INVALIDATED_BEFORE_PLACEMENT, VALIDITY_TOO_SHORT), entry intent (REJECTED), protection (ENTRY_ENDED_NO_FILL, FLAT). Non-final refusals map to None.
- Tests: 105 in `tests/test_live_risk_inputs.py` (fail-closed cases, candidate exclusion, two-equity threshold invariance, mappings parametrized over every ApprovalResult, ExecutionIntentStatus, ProtectionState, TradePlanStatus, every public pre_placement string constant via a literal table and every RejectionReason, release-source consistency, no clock and no forbidden imports) and 7 in `tests/test_live_risk_parity.py` (positions/thresholds equality, three reachable portfolio verdict cases, O-5 difference).

## Verification

- `uv run pytest -m "not docker" tests/test_live_risk_parity.py tests/test_live_risk_inputs.py tests/test_backtest_ledger.py`: pass.
- Gate files `tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_phase20_gate.py`: pass.
- ruff check, ruff format --check on the three files and mypy on the module: clean.
- `git diff --exit-code -- pyproject.toml uv.lock`: clean. `git log --grep="^[a-z]*(21-11):" -- src/backtest src/execution/manager.py src/execution/gates.py pyproject.toml uv.lock` prints nothing.
- Not run: `TRADING_CI_STRICT=1 uv run pytest tests/test_persistence_exit_evidence_pg.py` (needs `TEST_DATABASE_URL`; this plan touches no persistence code).

Evidence label: executed unit tests [DESIGN]; not wired into `execute_approved_plan` (Phase 24).

## Deviations from Plan

None - plan executed exactly as written. The three tasks were committed together as one commit (the code and both test files were written in one pass, each task's tests run green before the next).

## Known Stubs

None.

## Threat Flags

None.

## Owner items

O-5 (equity basis: live margin balance includes unrealized PnL, backtest is realized-only) remains open and is asserted visibly in `test_unrealized_pnl_makes_live_equity_differ_from_the_ledger_equity`. EXEC-01 stays Pending; no requirement marked complete (plan 21-14 records the status).

## Self-Check: PASSED

Files exist (live_risk_inputs.py, both test files); commit 05225a8a is on HEAD.
