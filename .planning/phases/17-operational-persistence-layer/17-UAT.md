---
status: testing
phase: 17-operational-persistence-layer
source: [17-VERIFICATION.md]
started: 2026-10-01T19:24:05Z
updated: 2026-10-01T19:24:05Z
---

## Current Test

number: 2
name: Observe the first remote CI run of the PostgreSQL battery
expected: |
  ci.yml (digest-pinned postgres:17.11 service, TRADING_CI_STRICT=1) is green on the pushed branch; the PG tests have only run locally against Docker so far.
awaiting: user response

## Tests

### 1. Confirm or amend the DOMN-04 transition tables
expected: GLOSSARY section 11 and D051 (f) are accepted, or amended (see Current Test).
result: [pending]

### 2. Observe the first remote CI run of the PostgreSQL battery
expected: ci.yml (digest-pinned postgres:17.11 service, TRADING_CI_STRICT=1) is green on the pushed branch; the PG tests have only run locally against Docker so far.
result: [pending]

### 3. Re-read Binance clientOrderId facts from the live docs before Phase 19/20
expected: "newClientOrderId / clientAlgoId unique among open orders only" and the 3-day Query Order retention are confirmed on developers.binance.com (currently MEDIUM confidence from Internet Archive snapshots and SDK docstrings).
result: [pending]

### 4. Accept the CR-01 policy
expected: swallowing a failed SAFE_MODE audit-row write inside execute_approved_plan so the stop loss is still placed (consistent with D034) is accepted.
result: [pending]

## Summary

total: 4
passed: 1
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
