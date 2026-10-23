---
phase: 21-account-equity-daily-loss
plan: 01
subsystem: owner-decision
tags: [owner-decision, daily-loss, funding-policy, o-2]
requires:
  - phase: 21
    provides: "21-02 account.max_equity_age_ms, 21-04 equity_basis, 21-05 FundingPolicy, 21-09 day-state tables, 21-13 LiveDayRiskService"
provides:
  - "21-OWNER-DECISIONS.md: O-2 answer verbatim; O-1, O-3, O-4, O-5, O-6 OPEN with the defaults Phase 21 built"
affects: [21-14, phase-24]
key-files:
  created: [.planning/phases/21-account-equity-daily-loss/21-OWNER-DECISIONS.md]
  modified: []
key-decisions:
  - "O-2 answered by the owner on 2026-10-23: option A, FundingPolicy.TRADES_WITH_UNVERIFIED_FUNDING; the Phase 24 composition passes it"
requirements-addressed: [RISK-02]
status: complete
completed: 2026-10-23
commits: 1
---

# Phase 21 Plan 01: Owner decision O-2 and the owner decision record Summary

The owner answered O-2 and the record of the six Phase 21 owner items exists. No code, config, params or `docs/DECISIONS.md` file changed in this plan.

## Owner decision O-2

Owner answer, verbatim (2026-10-23):

> option A

Matching FundingPolicy member: `TRADES_WITH_UNVERIFIED_FUNDING`. The owner did not add a condition. The assistant's recommended check before real money (observe a FUNDING_FEE row, or hold a small Demo position across a funding settlement, or reconcile the wallet balance against the loss components, before the Phase 26 canary) was not answered and is recorded as an OPEN assistant recommendation in `21-OWNER-DECISIONS.md`, not as an owner decision.

## What was built

`21-OWNER-DECISIONS.md` with sections O-1 to O-6. O-2 is DECIDED; O-1, O-3, O-4, O-5 and O-6 are OPEN, each with the default Phase 21 built and the sentence that the assistant did not decide it. No number is written for any OPEN item.

## Defaults checked against the code (2026-10-23)

- `account.max_equity_age_ms = "NOT_CONFIGURED"` in `config/execution/execution-limits-v1.toml` (21-02).
- `def equity_basis` and the `multi_assets_margin` refusal in `src/risk/live_equity.py` (21-04).
- `class FundingPolicy` with both members and `FUNDING_SOURCE_VERIFIED: bool = False` in `src/risk/daily_loss.py` (21-05); `funding_policy` is a required constructor argument of `LiveDayRiskService` (21-13).
- No `delete`, `purge` or `remove` method in `src/persistence/day_risk.py` (21-09).
- The operator acknowledgement path for a missing day state with exposure is named "Not built here" in the `src/execution/day_risk_service.py` docstring (21-13).
- `LIVE_NET_PNL_SEMANTICS_VERIFIED: bool = False` in `src/analytics/live_outcomes.py`.

No default was missing from the code.

## Deviations

None. The plan's executor was this orchestrator session itself, inline, because the task is a recording task with one owner answer and no code. No requirement was marked complete; plan 21-14 records the status.
