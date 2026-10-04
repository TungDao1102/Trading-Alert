---
status: complete
phase: 08-approval-reconciliation-hardening
source: [08-01-SUMMARY.md, 08-02-SUMMARY.md, 08-03-SUMMARY.md, 08-04-SUMMARY.md, 08-05-SUMMARY.md]
started: 2026-10-04T00:00:00Z
updated: 2026-10-04T00:00:00Z
---

## Current Test

[testing complete]

## Tests

### 1. 12-field APPROVE/SKIP alert with byte-stable formatting (D1)
expected: APPROVE/SKIP alert renders all 12 APRV-01 fields; invalid input (empty symbol, inverted bounds, empty TPs, naive datetime) is rejected
result: pass
source: automated
coverage_id: D1
verified: tests/test_approval_message.py format_approve tests pass (run with PG17 suite, no skips).

### 2. APR:/SKP: keyboards within 64-byte callback_data (D2)
expected: callback_data within Telegram 64-byte ceiling; both keyboards share one short id
result: pass
source: automated
coverage_id: D2
verified: tests/test_approval_message.py keyboard tests pass.

### 3. Phase-7 SIMULATE wire format unchanged (D3)
expected: SIM:/SKIP: callback_data byte-identical; paper notify tests still green
result: pass
source: automated
coverage_id: D3
verified: test_simulate_keyboard_callback_data_byte_identical passes.

### 4. Callback receiver ordering and gates (D5)
expected: chat gate before state lookup, journal-first receipt, atomic save with mapping, replay returns existing approval
result: pass
source: automated
coverage_id: D5
verified: tests/test_approval_message.py dispatch_callback/authorized_chat_gate/parse_callback_data tests pass.

### 5. Short-to-full id mapping and migration 0003 (D4)
expected: ShortIdMappingRow on single Base, mapper round-trips, migration 0003 creates/drops table cleanly
result: pass
verified: test_short_id_mapping_* and test_migration_0003_creates_short_id_mapping_table pass; test_approval_replay_pg, test_callback_redelivery_pg, test_persistence_approvals_pg pass against PG17 (126 passed, 0 skipped across the approval/reconcile/drill set). Note: classify-coverage flagged D4 present only due to non-schema verification kinds (automated_sql) in the SUMMARY; evidence itself is automated.

### 6. Approval binding, 5x replay yields one transition (08-01)
expected: fixed-order gate chat->expiry->plan-hash->version->token; 5 redeliveries produce exactly one transition; notify failure leaves PENDING
result: pass
verified: tests/test_approval_replay.py (13 tests), test_approval_replay_pg.py, test_callback_redelivery_pg.py, test_transitions.py pass.

### 7. Deterministic client/algo order IDs (08-03)
expected: 36-char Binance-safe IDs, deterministic across retry/restart, distinct per role, bad input raises
result: pass
verified: tests/test_order_ids.py (21 tests) pass.

### 8. Reconciler, cancel-only sweeper, SAFE_MODE (08-04)
expected: injected orphan swept with verification and journal; divergence forces SAFE_MODE; exit only on clean compare plus journaled event; no order placement
result: pass
verified: tests/test_reconcile.py passes; grep of src/reconcile, src/ops, src/approval, src/execution finds no place_order/new_order call (only an outcome-name constant).

### 9. Eight RUNBOOK drills rehearsed with fakes, deterministic log (08-05)
expected: eight drills produce ordered journaled outcomes identical across double runs; restore path rehearsed; no place-order path
result: pass
verified: tests/test_drills.py (9 tests) and test_phase8_audit_reviewfix.py pass.

### 10. Live Telegram tap gate (D6)
expected: real APPROVE tap and SKIP tap each produce exactly one Approval transition and clear spinner; unknown-chat callback rejected with no state change
result: skipped
reason: needs a real Telegram bot, TELEGRAM_BOT_TOKEN and authorized chat provisioned and operator taps; not available. Logic covered by automated callback-dispatch tests.

### 11. Reconciliation against a real exchange account
expected: reconciler/sweeper behave correctly against live Binance state
result: skipped
reason: needs the signed Binance adapter and real account; owners Phases 20/23/24/25. Fakes-only coverage passes (tests 8, 9).

## Summary

total: 11
passed: 9
issues: 0
pending: 0
skipped: 2
blocked: 0

## Gaps

[]
