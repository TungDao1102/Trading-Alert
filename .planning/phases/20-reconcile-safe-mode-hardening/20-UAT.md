---
status: partial
phase: 20-reconcile-safe-mode-hardening
source: 20-01-SUMMARY.md to 20-31-SUMMARY.md
started: 2026-10-23T00:00:00Z
updated: 2026-10-23T00:00:00Z
---

## Current Test

[testing paused - 4 items outstanding, all need the owner or a connected Demo machine]

## How this session was run

The owner asked the assistant to answer the UAT questions (2026-10-23). The assistant is not the acceptance authority, so every `pass` below means: the behavior was exercised by running the named tests on `develop` (strict mode, local PostgreSQL, fakes) in this session. Nothing here is `[DEMO]`. Items that need the owner or a connected Demo machine are `blocked`, not passed.

## Tests

### 1. Reconcile compare catches bad exchange state
expected: A doubled position, a sign-flipped position, a foreign order, a TP-only plan and a missing stop are each reported as a divergence; a clean state agrees; missing local data never reads as agreement.
result: pass
source: assistant-run
evidence: tests/test_reconcile_compare_v2.py, 117 passed

### 2. A resting entry is not an alarm, a filled entry without a stop is
expected: An unfilled GTD entry that is still NEW raises no divergence and does not block the SAFE_MODE exit; a filled or partly filled entry with no stop, or an entry that vanished from the exchange, is still flagged; an entry past its goodTillDate plus the grace raises only a STALE_ENTRY_ORDER alert.
result: pass
source: assistant-run
evidence: tests/test_reconcile_classify.py, tests/test_reconcile_stale_entry.py, 96 passed

### 3. Every fill leads to a protective stop, and no new entry opens while a position is unprotected
expected: After a fill the coordinator places the stop and confirms it; a plan without a confirmed stop blocks new entries; the take-profit legs follow the stop.
result: pass
source: assistant-run
evidence: tests/test_protection_supervision.py, test_protection_take_profits.py, test_pending_actions.py, 68 passed

### 4. Stop rules: re-place once if never confirmed, never after a confirmed stop is lost
expected: A never-confirmed stop that REST proves absent is re-placed once per step under the same id, including the step that reaches max_unprotected_ms; a stop confirmed and later lost is never re-placed (the position is closed instead); the open-algo-orders list confirms a stop that the by-id query denies; a duplicate id (-4116) means "exists, awaiting REST".
result: pass
source: assistant-run
evidence: tests/test_protection_demo_shapes.py, test_protection_deadline_attempt.py, test_protection_stop_lost.py, test_protection_branches.py, 43 passed

### 5. Emergency close is safe
expected: The closer reads the position itself; two zero reads send no order; a REST gate refusal ends as NOT_SENT with a pending row and an alert, not as a generic read failure; stored lot filters are used and floored.
result: pass
source: assistant-run
evidence: tests/test_emergency_close_gate_refusal.py, test_emergency_market_close.py, test_emergency_close_filters.py, 104 passed

### 6. SAFE_MODE is durable and only an operator leaves it
expected: SAFE_MODE survives a restart; an unreadable store means SAFE_MODE; the exit needs an operator id, fresh Binance reads, a clean compare with the ownership check, a complete restore, a clean gate and a LIVE stream, and each refusal is journaled.
result: pass
source: assistant-run
evidence: tests/test_safe_mode_persistence.py (+ _pg), test_safe_mode_exit_operator.py, test_controller_rehydrate.py, 267 passed

### 7. A standing reason does not flood the journal, and a normal TP1 fill is not an alarm
expected: Two standing reasons write no new SAFE_MODE rows on later ticks; a TP1 fill that halves the position does not raise UNSYNCED_ALGO.
result: pass
source: assistant-run
evidence: tests/test_safe_mode_reentry.py, test_reconcile_tp1_fill.py, 28 passed

### 8. A database outage never blocks risk reduction, and an unreadable spill fails closed
expected: Disable-entries, cancel and close still act when the journal is down and leave a spill record; at start an unreadable spill directory or a corrupt entry puts the system in SAFE_MODE instead of "nothing pending".
result: pass
source: assistant-run
evidence: tests/test_risk_first_spill.py, test_startup_recovery.py, test_protection_rebuild.py, 94 passed

### 9. The REST gate survives a restart and fails closed on bad state
expected: A 418 ban and a 429 pause are restored; an expired restriction is ignored; a missing, corrupt, overflowing or implausible state file leaves the gate in an unknown, operator-cleared state; the CLI can read and clear it; the user-data supervisor is bounded while the gate is unknown.
result: pass
source: assistant-run
evidence: tests/test_gate_restart.py, test_gate_restore_bounds.py, test_rest_gate_cli.py, test_userdata_supervisor.py, test_userdata_supervisor_pause_slices.py, 134 passed

### 10. A stale or future-stamped feed puts the system in SAFE_MODE
expected: A silent user-data stream or an old mark price enters SAFE_MODE STALE_FEED; a feed time ahead of the clock beyond the ratified skew counts as stale; gate-restricted ticks skip reads.
result: pass
source: assistant-run
evidence: tests/test_feed_freshness.py, test_feed_freshness_skew.py, test_reconcile_loop.py, test_reconcile_stream_divergences.py, 147 passed

### 11. Alerts reach the sink, journal first, without secrets
expected: Each OPS-05 event (unprotected position, divergence, foreign order, stale data, auth failure, stale entry) is journaled then sent, deduplicated, with no secret in the text; the matrix names each producer and whether it is wired.
result: pass
source: assistant-run
evidence: tests/test_alerts.py, test_alert_producers.py, test_alerts_ops05_matrix.py, 113 passed

### 12. The eight drills run
expected: The UNPROTECTED, STALE_FEED, MANUAL_CLOSE and restore drills complete with the Phase 20 outcomes; the old no-place rule is retired.
result: pass
source: assistant-run
evidence: tests/test_drills.py, test_reconcile.py, 43 passed

### 13. Two plans on one symbol enter SAFE_MODE; risk reduction goes first in a tick
expected: More than one active plan on a symbol raises SYMBOL_OWNERSHIP_CONFLICT and refuses the exit; within a tick the lot-filter refresh and risk-reducing actions come first.
result: pass
source: assistant-run
evidence: tests/test_symbol_ownership.py, test_reconcile_queue_order.py, 51 passed

### 14. Manual controls and cancel verification
expected: The five EXEC-06 controls obey the rules (no re-placement after a lost stop, legs cancelled only after two flat reads and a terminal entry); a -2011 cancel is verified by a query; an UNKNOWN entry stays UNKNOWN until every condition holds.
result: pass
source: assistant-run
evidence: tests/test_manual_controls.py, test_cancel_verification.py, test_intent_recovery_unknown_entry.py, 141 passed

### 15. Nothing is wired into a running process yet
expected: No source file builds ReconcileLoop or SafeModeController outside their own modules, live placement stays disabled, and no requirement is marked complete. This is by design: composition is Phase 24.
result: pass
source: assistant-run
evidence: grep of src finds no construction outside src/reconcile; LIVE_ORDERS_DISABLED present; REQUIREMENTS.md shows EXEC-02, OPS-01, RISK-03, EXEC-06 and OPS-05 as Pending

### 16. A GTD entry ends with a terminal status on the exchange (A2)
expected: After goodTillDate the entry becomes EXPIRED and terminal on Binance.
result: blocked
blocked_by: server
reason: "Demo showed the entry still NEW 840 s after goodTillDate, and the case was NOT_OBSERVED twice. Rerun with a longer wait; the scheduled cancel is a Phase 24 blocker."

### 17. The eight new Demo cases and the remaining probes (A4, A8, -4164, -2019, P5, P7, -1021, income history, partial fill)
expected: Each returns OBSERVED with the exact answers or NOT_OBSERVED with a reason.
result: blocked
blocked_by: server
reason: "Owner runs the probe on a connected machine (.planning/DEMO-EVIDENCE-PLAN.md sections 16 to 23)."

### 18. Owner-set numbers for the NOT_CONFIGURED keys (O-G, O-04, the stale-entry grace)
expected: The owner sets max_unprotected_ms, the probe counts, the grace and the other keys after Demo evidence; until then the live path refuses.
result: blocked
blocked_by: prior-phase
reason: "Owner decision; needs Demo evidence first."

### 19. Owner decisions on DECISIONS rows (20-DECISION-AUDIT.md) and the Phase 24 blockers
expected: The owner accepts, rejects or edits the proposed wording and the Phase 24 blockers (scheduled entry cancel, second-plan refusal, D028 chain).
result: blocked
blocked_by: other
reason: "Owner decision; proposals only, DECISIONS.md untouched."

## Summary

total: 19
passed: 15
issues: 0
pending: 0
skipped: 0
blocked: 4

## Gaps

[none - no code issue found; the four blocked rows are owner or Demo prerequisites]
