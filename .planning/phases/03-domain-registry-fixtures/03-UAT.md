---
status: testing
phase: 03-domain-registry-fixtures
source: [03-VERIFICATION.md]
started: 2026-09-23T00:00:00Z
updated: 2026-09-23T00:00:00Z
---

## Current Test

number: 1
name: Apply migration 0002 on live Compose PG17
expected: |
  Boot Compose PostgreSQL 17, run `alembic upgrade head`, confirm signals, trade_plans, approvals, orders, fills, positions, journal_events tables exist. Upgrade applies cleanly with no errors; all seven tables present with content-hash PKs.
awaiting: user response

## Tests

### 1. Apply migration 0002 on live Compose PG17
expected: Upgrade applies cleanly with no errors; all seven tables present with content-hash PKs
result: [pending]

## Summary

total: 1
passed: 0
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
