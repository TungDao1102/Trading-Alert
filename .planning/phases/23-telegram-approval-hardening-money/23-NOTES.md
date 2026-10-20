# Phase 23 notes (carried from Phase 19)

Input for `/gsd-discuss-phase 23` and the planner. Not a decision record. Written 2026-10-20 from `.planning/phases/19-execution-plan-binding-price-check/` and `.planning/phases/20-reconcile-safe-mode-hardening/20-NOTES.md` ("From Phase 19").

## 1. Messages for the operator alerts that Phase 20 emits

- Phase 20 builds the `CriticalAlertSink` and decides which events go out; this phase owns what the Telegram message says and how it is sent. Events the code already raises: `CLOSE_REQUIRED` (the reason is a branch code B1 to B5 or `NO_POSITION_ON_STOP_BUT_EXPOSED`), `TP_UNAVAILABLE`, `EMERGENCY_CLOSE_FAILED`, `EMERGENCY_CLOSE_NOT_SENT`. Entry-path events with no alert today: SAFE_MODE `ENTRY_STATE_UNKNOWN`, `PROTECTION_HANDOFF_FAILED`, `DB_FAILURE` and the outcome `RECONCILIATION_REQUIRED`.
- Each message should say in plain words what happened to the order or position, whether a position may be open or unprotected, what the system already did (for example "the entry was not re-sent"), and what the operator must do. Use the Phase 20 reason codes verbatim in the text so they can be searched in the journal.

## 2. A failed alert must not be silent

- Telegram is unreliable from the owner machine. A send failure of a critical alert must be journaled and retried within a bound, and must show up in health output (Phase 24). Retrying a message is allowed. Retrying an order is not: the owner decided on 2026-10-20 (Q5) that a placement is never re-sent.
- The approval path keeps the existing rule: no auto-approve on a notification failure.

## 3. What the operator sees after a placement problem

- Since Q5 an ambiguous entry failure ends as intent `UNKNOWN` plus SAFE_MODE, not as a silent NO_TRADE. The CONFIRM card flow (criterion 4) and any "already executed" message (G4-032) must show that state (needs reconciliation), not "rejected".
