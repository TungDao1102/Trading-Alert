# Phase 20: Reconcile + SAFE_MODE Hardening + Alerts - Discussion Log

> Audit trail only. Not consumed by downstream agents.

**Date:** 2026-10-20
**Mode:** `--auto` (single pass, no interactive questions)

## Gray areas selected (all)
1. Compare reverse pass and signed amounts
2. Protection supervision and re-placement vs D077
3. Closing UNKNOWN entries left by Q5
4. SAFE_MODE durability and operator exit
5. Rate-limit pause versus protection (Q4)
6. Emergency close without exchangeInfo (Q3)
7. Alerts and stale-feed thresholds
8. Manual controls, tests, drills

## Auto-selected choices
- [auto] Compare — new divergence kinds added, existing five unchanged → recommended
- [auto] Criterion 2 wording → reconciled with D077 and Phase 19 D-10 (no blind re-place; position decides)
- [auto] UNKNOWN entry closing → repeated probes + GTD expiry + clean reconcile; numbers NOT_CONFIGURED
- [auto] SAFE_MODE → persisted, operator id on exit, clean compare still required
- [auto] Q3, Q4, Q5, D077 → taken verbatim from 20-NOTES (owner decided)
- [auto] Alerts → journal first, then send; message retry allowed, order retry never
- [auto] Reserved priority (Q4) → left OWNER-OPEN, nothing built

## Owner-open items carried
- Numeric values of all NOT_CONFIGURED keys (O-04, T-06)
- Definition of "reserved priority for risk-reducing calls"
- Extra NO_TRADE alerts beyond the SAFE_MODE reasons
- D055 closure and the unwritten DECISIONS rows

## Deviation from workflow
`--auto` normally persists the chain flag and auto-advances plan → execute. The user asked to stop after the pattern mapper, so the chain flag was NOT persisted.
