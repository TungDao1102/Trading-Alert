---
status: partial
phase: 23-telegram-approval-hardening-money
source: 23-01-SUMMARY.md .. 23-14-SUMMARY.md
started: 2026-10-30T12:00:00Z
updated: 2026-10-30T14:22:47.218Z
---

## Current Test

[testing complete]

## Tests

### 1. Only the authorized user in a private chat can approve
expected: A tap from a user not on TELEGRAM_AUTHORIZED_USER_IDS, from a group, or without a user id is refused before any approval lookup; an allowed press is decided with that user as actor_id.
result: pass
source: Claude, from code and tests (tests/test_telegram_authorization.py, all green; WR-01 made the gate mandatory). Not a live Telegram observation.

### 2. SKIP works and a decided message cannot be tapped again
expected: One message carries APPROVE and SKIP. A decision removes the keyboard in the same edit as the final text; a stale tap is refused; RetryAfter is bounded.
result: pass
source: Claude, from tests (test_telegram_decided_message.py, test_confirm_flow.py). The live keyboard removal is test 9.

### 3. APPROVE alone never places an order
expected: APPROVE turns the message into a confirmation card. Only CONFIRM reaches on_confirmed, once, even on a double tap or a redelivered callback.
result: pass
source: Claude, from tests (test_confirm_flow.py, test_confirm_core.py).

### 4. CONFIRM is single-use, bound and time-limited
expected: CONFIRM after the 60 s window, after plan expiry, from another user, or after a restart is refused and the card becomes final; the pre-placement checks re-run at confirm.
result: pass
source: Claude, from tests, including the review-fix cases WR-02 and WR-11.

### 5. Every SIMULATE and APPROVE message shows the money at stake
expected: Notional, loss at SL gross and net of costs, margin and TP legs appear, computed once in the risk layer, shown as Decimal text (no float look).
result: pass
source: Claude, from the generated goldens in tests/fixtures/phase23/messages and test_money_at_stake.py. The SHADOW alert has no money block (owner exemption R-1, carried to Phase 24).

### 6. Times read as Vietnam time with UTC in brackets
expected: DEMO, LIVE, SIMULATE and card messages show e.g. 2026-10-30 21:15:00 +07 (2026-10-30 14:15:00 UTC).
result: pass
source: Claude ran format_presentation_time(2026-10-30 14:15 UTC) and got exactly 2026-10-30 21:15:00 +07 (2026-10-30 14:15:00 UTC); goldens carry the same pairs.

### 7. An expired approval does not block a new one for the same plan
expected: Migration 0014 excludes EXPIRED from the one-decided-per-plan index (D088).
result: pass
source: Claude, from the PostgreSQL tests (test_persistence_approvals_pg.py, test_persistence_constraints_pg.py, TRADING_CI_STRICT=1, not skipped).

### 8. SHADOW behaviour is unchanged
expected: The SHADOW approval flow and texts are byte-identical to before Phase 23, apart from the approved UTC pairs.
result: pass
source: Claude, from the SHADOW test set (test_paper_shadow_*.py) and test_phase23_gate.py, all green.

### 9. Live Telegram checks (A1, G2-014, A2)
expected: On the real Bot API an empty keyboard removes the buttons; a tap from a second account or a group is rejected; an old callback gives the expected "Query is too old" text.
result: blocked
blocked_by: third-party
reason: needs a real Telegram bot and a second account; only the owner can run these (registered in 23-OWNER-CHECKS.md).

## Summary

total: 9
passed: 8
issues: 0
pending: 0
skipped: 0
blocked: 1

## Gaps

[none]
