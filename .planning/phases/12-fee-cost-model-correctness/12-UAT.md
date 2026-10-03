---
status: complete
phase: 12-fee-cost-model-correctness
source: [12-VERIFICATION.md]
started: 2026-10-04T00:00:00Z
updated: 2026-10-04T00:00:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Commission rates, mark klines, constraint snapshot (incl. PG)
expected: behaviour holds
result: pass
verified: 131 passed (test_commission_rates, test_mark_klines, test_cost_parity, test_constraint_snapshot*). Checked by Claude on 2026-10-04.

### 2. Mainnet taker fee equals fee_rate_entry (D036)
expected: behaviour holds
result: pass
verified: Read-only check on 2026-10-04: mainnet taker 0.0005 matches; demo taker 0.0004. Checked by Claude on 2026-10-04.

## Summary

total: 2
passed: 2
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
