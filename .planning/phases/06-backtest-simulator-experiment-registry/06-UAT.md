---
status: complete
phase: 06-backtest-simulator-experiment-registry
source: [06-VERIFICATION.md]
started: 2026-10-04T00:00:00Z
updated: 2026-10-04T00:00:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Simulator, experiment registry and report
expected: behaviour holds
result: pass
verified: 235 passed (simulator, experiment, report, registry, registry_gate, fixture geometry). Checked by Claude on 2026-10-04.

### 2. Entry-expiry clock uses simulated bar time
expected: behaviour holds
result: skipped
verified: Known gap G3: simulator.py ~758/881 still use the fixture's single now_utc. Owner: Phase 14 success criterion 6. Checked by Claude on 2026-10-04.

## Summary

total: 2
passed: 1
issues: 0
pending: 0
skipped: 1
blocked: 0

## Gaps
