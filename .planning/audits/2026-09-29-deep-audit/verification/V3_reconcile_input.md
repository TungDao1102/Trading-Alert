# Verification batch V3_reconcile — BLIND INPUT (claims + locations only)

## F-401
- Claimed severity: HIGH
- Claim: Reconcile compare treats the entry-time closePosition stop-loss of a resting (unfilled) LIMIT entry as ORPHAN_PROTECTIVE. The sweeper cancels it after two zero-position reads, so the entry later fills with no stop.
- Expected behavior (per claimant): A protective whose plan ENTRY is still working is not an orphan. A pre-placed closePosition stop is allowed protection for a resting entry (Corrected Rule 14).
- Location(s): src/reconcile/compare.py:293-339
- Component: src/reconcile/compare.py + src/reconcile/sweeper.py

## F-701
- Claimed severity: HIGH
- Claim: Reconciliation compare returns agreement=True for a doubled or sign-flipped position, for unknown exchange normal/algo orders, and for a position protected only by a TP (no SL). Exchange orders are never scanned for missing local intent, and positions are matched by (symbol, side) key only.
- Expected behavior (per claimant): Exchange-only orders are flagged (INV-093 unknown order). Signed position_amt mismatches are flagged (EXTERNAL / unexpected increase -> SAFE_MODE). A non-zero position without an exchange-present STOP_LOSS is flagged ENTRY_WITHOUT_PROTECTIVE.
- Location(s): src/reconcile/compare.py:228-468
- Component: reconcile/compare

## F-952
- Claimed severity: HIGH
- Claim: Planning chose a cancel-only reconciler that never re-places protection ('sweeper never places rescue protection'); 09 WR-07 (emergency close cancels SL before flat; expired entry leaves close-all SL) was skipped and no later phase picks it up.
- Expected behavior (per claimant): Protective re-placement / reduce-only close always allowed and automatic (Rule 24); post-fill SL reject -> reduce-only MARKET close + SAFE_MODE (Rule 14); keep SL until flat.
- Location(s): src/execution/manager.py:627-832
- Component: Phase 8 D-03, Phase 9 D-02, 09-REVIEW WR-07

## F-009
- Claimed severity: HIGH
- Claim: SAFE_MODE forbids 'new live order placement' without exempting protective or reduce-only orders, while the RUNBOOK asks to submit protection. Read literally, SAFE_MODE (entered exactly when a stop is missing) forbids placing the stop.
- Expected behavior (per claimant): SAFE_MODE blocks exposure-increasing orders only.
- Location(s): docs/operations/SECURITY_AND_OPERATIONS.md:76-82
- Component: SAFE_MODE semantics
