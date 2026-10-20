---
status: partial
phase: 19-execution-plan-binding-price-check
source: 19-01-SUMMARY.md .. 19-17-SUMMARY.md, quick 261020-q1o, 261020-r3b, 261020-q2d
started: 2026-10-20T13:00:00Z
updated: 2026-10-20T13:00:00Z
---

## Current Test

[testing paused — 8 owner-only items outstanding]

Answers marked `source: automated` were answered by the agent from evidence it could run or read
(2253 passed, 0 skipped, `TRADING_CI_STRICT=1`, 56 phase test files; `verify_decision_alignment.py all`
ALL_PASS). The agent did NOT answer for the owner: every item that needs an owner decision or a run
on Binance Demo is `blocked` below, not `pass`.

## Tests

### 1. Symbol and side come from the hashed plan, not the caller (criterion 1)
expected: A plan whose symbol or side differs from the Signal is refused (PLAN_SYMBOL_MISMATCH / PLAN_SIDE_MISMATCH); SL and entry geometry are asserted after the tick snap.
result: pass
source: automated
evidence: tests/test_execution_binding.py, tests/test_execution_price_ticks.py (green in the phase run)

### 2. Placement quantity is never larger than the approved quantity (criterion 1)
expected: A quantity above the approved one is refused and never clipped; the approved bound is the value stored on the approval row (D078), re-read from the database at consume time.
result: pass
source: automated
evidence: tests/test_execution_binding.py, tests/test_consume_approved_quantity_pg.py (PG, not skipped), tests/test_execution_manager.py. Inconsistent stored value enters SAFE_MODE APPROVED_QUANTITY_INCONSISTENT; NULL legacy row is NO_TRADE only.

### 3. The owner sees the quantity before APPROVE (WR-01 follow-up)
expected: The APPROVE message and the Demo message show a `Quantity:` line equal to the stored approved quantity.
result: pass
source: automated
evidence: tests/test_approval_message.py, tests/test_paper_shadow_messages.py, tests/test_demo_rehearsal_flow.py

### 4. Pre-placement refusals (criterion 2)
expected: Refused when the mark price crossed the SL or left the zone on the adverse side, the remaining validity is below the minimum (GTD floor), another plan or position exists on the symbol, the plan status or invalidation rule says invalid, or Hedge mode is on. A refusal never consumes the approval.
result: pass
source: automated
evidence: tests/test_pre_placement.py, tests/test_execution_manager.py, tests/test_execution_modes.py. The LAST price part of "mark or last price" is not built (WR-06 work item, see test 10).

### 5. Fill-driven protection and no naked position (criterion 3)
expected: After a fill the stop is placed and REST-confirmed; a stop that cannot be placed leads to a reduce-only MARKET close, an alert and SAFE_MODE; no new entry opens while a position is unprotected; a placement is never re-sent.
result: pass
source: automated
evidence: tests/test_protection_coordinator.py, tests/test_protection_branches.py, tests/test_emergency_market_close.py, tests/test_execution_exactly_once_pg.py (fake exchange only)

### 6. Take-profit legs sized from the real position (criterion 4)
expected: TP legs are quantized to LOT_SIZE and sized from the real filled quantity; an un-sizeable TP1 is refused (TP_UNAVAILABLE) with the stop kept.
result: pass
source: automated
evidence: tests/test_tp_sizing.py, tests/test_protection_take_profits.py. Note: the single-TP fallback of criterion 4 is NOT built (O-03), only the refusal.

### 7. Persistence and migrations
expected: Migrations 0005 (sized_realized_risk) and 0006 (approved_quantity) upgrade and downgrade with data; the stores and the five test doubles agree.
result: pass
source: automated
evidence: tests/test_persistence_migration_pg.py, tests/test_realized_risk_persistence_pg.py, tests/test_persistence_approvals_pg.py

### 8. Documentation and decision gates
expected: GLOSSARY, DECISIONS (D077, D078), DOC_STATUS and the owner-gap register are consistent with the code.
result: pass
source: automated
evidence: verify_decision_alignment.py all, glossary, reqs: ALL_PASS; tests/test_phase19_gate.py

### 9. Owner confirms the one-way schema door (migration 0005, plan 19-06 Task 1)
expected: The owner's answer ("column-on-entry-intent" or "defer-d22") is recorded in 19-06-SUMMARY.
result: blocked
blocked_by: third-party
reason: Owner decision (the owner is the blocker); the agent does not answer it. Check 19-06-SUMMARY for a recorded answer.

### 10. WR-06 last-price read
expected: A last-price read behind the ExecutionAdapter Protocol, so criterion 2 "mark or last price" holds in full.
result: blocked
blocked_by: third-party
reason: Open work item (19-OWNER-GAPS WR-06), not built; needs scheduling.

### 11. D055 closure (O-01) and the EXEC-07 reconciliation (O-02)
expected: DECISIONS row for the fill-driven model accepted; the TP1 fraction, TP2 rule and time in force reconciled with D052 (c).
result: blocked
blocked_by: third-party
reason: Owner decisions. Drafts are 19-DEC-D055-DRAFT.md (provisional D079) and 19-DEC-Q5-DRAFT.md (D080). Live placement stays disabled until accepted.

### 12. Single-TP fallback versus backtest D-27 (O-03) and N1 partial-fill remainder
expected: Owner decides whether to build the single-TP fallback (backtest and live must move together) and whether a partial-fill remainder is normal completion.
result: blocked
blocked_by: third-party
reason: Owner decisions, still OPEN.

### 13. The six numeric limits (O-04)
expected: protection.max_unprotected_ms, entry_terminal_timeout_ms, entry_unknown_grace_ms, emergency_close_poll_timeout_ms and the other keys of config/execution/execution-limits-v1.toml are set by the owner.
result: blocked
blocked_by: third-party
reason: Owner-only numbers; all NOT_CONFIGURED, live readiness refuses while unset. The agent must not invent them.

### 14. Q3 / Q4 policies
expected: Owner chooses the emergency-close policy when exchangeInfo is unreadable (Q3) and the protection exemption during a 429/418 pause (Q4).
result: blocked
blocked_by: third-party
reason: Owner decisions, still OPEN.

### 15. The 11 Demo probes (O-05)
expected: P1..P11 of 19-OWNER-GAPS section 2 run on Binance Demo by the owner (`--execute`, typed phrase), evidence recorded.
result: blocked
blocked_by: third-party
reason: Needs the owner at an interactive terminal on Binance Demo. No Phase 19 plan and no agent ran one; AGENTS.md reserves `--execute` for the owner.

### 16. Owner reads the owner-gap register
expected: 19-OWNER-GAPS.md read; every open item is listed and none is presented as solved.
result: blocked
blocked_by: third-party
reason: Human check of plan 19-17 Task 3.

## Summary

total: 16
passed: 8
issues: 0
pending: 0
skipped: 0
blocked: 8

## Gaps

none from automated testing. The 8 blocked items are owner decisions or Demo runs, tracked in 19-OWNER-GAPS.md; they are not defects.
