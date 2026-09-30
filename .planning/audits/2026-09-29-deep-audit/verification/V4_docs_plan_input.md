# Verification batch V4_docs_plan — BLIND INPUT (claims + locations only)

## F-001
- Claimed severity: HIGH
- Claim: Sizing formula adds 'modeled_costs' to a price distance without units, and the research doc drops costs from sizing entirely; SL losses exceed the risk budget by the cost share.
- Expected behavior (per claimant): Every term in risk_per_unit is quote-currency per unit of base, so realized loss at SL (fees + slippage included) is <= equity x risk_rate.
- Location(s): docs/trading/RISK_MANAGEMENT.md:19-23
- Component: RISK_MANAGEMENT sizing formula

## F-007
- Claimed severity: HIGH
- Claim: Nothing requires a live-price check after APPROVE. Price can cross the SL or leave the zone during the 4 h validity, so the LIMIT fills instantly and the SELL/BUY stop is rejected as 'would immediately trigger', leaving a naked position.
- Expected behavior (per claimant): Placement is refused when the current price has reached the SL (or the invalidation) since signal time or when the entry would be marketable beyond the planned zone; if an SL is rejected after a fill, the position is closed immediately.
- Location(s): docs/trading/EXECUTION_SPEC.md:1-25
- Component: Approval -> placement re-check

## F-008
- Claimed severity: HIGH
- Claim: Protective exits are placed only after the entry fill is observed; a LIMIT rests for up to 4 h, so if the process, host or user-data stream is down when it fills, the position is unprotected until restart.
- Expected behavior (per claimant): An exposure-creating order is never left on the exchange unless protection will exist even if the bot dies.
- Location(s): docs/trading/EXECUTION_SPEC.md:87-98
- Component: Protection window / resting entries

## F-022
- Claimed severity: HIGH
- Claim: Numeric pass thresholds are set only after Validation evidence from the three families has been seen, 'passing' is a human decision, and there is no multiple-testing correction across roughly 25+ variants plus parameter sweeps.
- Expected behavior (per claimant): Thresholds and the selection procedure are frozen before any out-of-sample data are looked at; the number of trials is recorded and penalized.
- Location(s): docs/research/RESEARCH_PROTOCOL.md:205-236
- Component: Acceptance methodology

## F-903
- Claimed severity: HIGH
- Claim: Phase-1 research framed pre-registered numeric acceptance thresholds as an overfitting anti-pattern. This is the planning origin of F-022.
- Expected behavior (per claimant): Acceptance thresholds, the trial-count penalty and the holdout protocol are frozen before any Validation run (Corrected Rule 31). Only parameter values are left to research.
- Location(s): .planning/phases/01-research-formalization/01-RESEARCH.md:226-238
- Component: 01-RESEARCH Don't Hand-Roll + Pitfall 2 -> RESEARCH_PROTOCOL numeric-gate reservation

## F-953
- Claimed severity: HIGH
- Claim: Live enablement gate is negative-only: enable() accepts KillGateState.WITHIN_BUDGET (no family passed), requires no paper exit gate or recorded passing candidate; paper soak never started (07-04 WS smoke BLOCKED, M3) while phases 8-10 executed; paper evidence thresholds never defined.
- Expected behavior (per claimant): Positive gate: recorded PASSING_CANDIDATE under frozen thresholds AND recorded paper-exit verdict (Rule 32) checked in code and journaled.
- Location(s): src/execution/enablement.py:147-208
- Component: Phase 7 D-05, Phase 9 D-04, Phase 10 D-03; LiveEnablementController.enable

## F-954
- Claimed severity: HIGH
- Claim: Money-safety fixes P11-P15 are sequenced after the live-rollout phase 9 (only a human LIVE-TAP checkpoint left) with no rule tying live enable to them; P11 (changes sizing and hashes) is not ordered before the paper soak epoch.
- Expected behavior (per claimant): Explicit 'LIVE enable blocked until P11-P15 verified' gate; P11 before soak start.
- Location(s): .planning/ROADMAP.md:286-435
- Component: ROADMAP phases 9, 11-15
