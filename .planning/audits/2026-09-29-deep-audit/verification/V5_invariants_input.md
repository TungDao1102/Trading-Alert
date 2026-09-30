# Verification batch V5_invariants — BLIND INPUT (claims + locations only)

## F-301
- Claimed severity: HIGH
- Claim: Trend-pullback baseline geometry puts the SL inside its own entry zone (entry_min = swing_low-0.6ATR < SL = swing_low-0.2ATR; 33% of the zone is beyond the stop), 0.2 ATR from the limit, and the trailing swing window includes the evaluated bar, so 'pullback to support' fires on bars making a new 20-bar low.
- Expected behavior (per claimant): SL beyond the whole entry zone; setup level = confirmed prior pivot (family sheet L18, L116-118); minimum stop distance / cost-to-risk ceiling (Corrected Rule 3).
- Location(s): src/core/planner.py:105-409
- Component: core/features, core/strategy, core/planner

## F-302
- Claimed severity: HIGH
- Claim: execute_approved_plan takes the order symbol from risk_kwargs['constraint_snapshot'].symbol and the side from risk_kwargs['candidate_position_side']; TradePlan has no symbol/direction and nothing re-checks them or the SL-side geometry against the approved plan.
- Expected behavior (per claimant): Symbol and direction fixed by the approved, hashed plan/signal; placement rejects any mismatch and side-inconsistent SL geometry (INV-044 'a mismatch on any of them rejects').
- Location(s): src/execution/manager.py:212-560
- Component: domain/trade_plan, execution/manager
