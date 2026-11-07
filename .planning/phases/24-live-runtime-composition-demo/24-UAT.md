---
status: partial
phase: 24-live-runtime-composition-demo
source: 24-01-SUMMARY.md .. 24-37-SUMMARY.md (37 files), checked against the 5 ROADMAP success criteria
started: 2026-11-07T00:00:00Z
updated: 2026-11-07T06:10:15.897Z
---

## Current Test

[testing complete]

## Tests

Answered by Claude at the owner's request ("tu tra loi cau hoi UAT giup toi"). Each answer cites evidence
that was run or read in this session. Nothing here is an owner observation on a host: items that only
the owner may run (AGENTS.md) are `blocked`, never `pass`.

### 1. Composition root wires every previously unwired link
expected: approval sender, Telegram runner, execution service, reconcile/sweeper/health schedulers, live risk-input producer and kill-gate to enable() are all composed by the live process.
result: pass
source: automated
evidence: tests/test_phase24_gate.py, test_live_wiring.py, test_live_run_admitted.py, test_live_approval_sender.py, test_live_telegram_runner.py, test_live_enablement_wiring.py all green on 2026-11-07.

### 2. APPROVE -> CONFIRM -> execute through the Telegram runner
expected: tapping APPROVE shows a CONFIRM prompt; CONFIRM places one entry; an unknown user or chat changes no state.
result: pass
source: automated
evidence: test_live_telegram_runner.py and test_live_approval_sender.py green; Demo evidence smoke-20261106T160307Z shows the operator tapped APPROVE then CONFIRM and recorded demo order id 28668586471. Unknown-chat tap on a real second account is test 9.

### 3. Demo end-to-end smoke with recorded order ids
expected: signal -> approve -> confirm -> entry -> SL/TP on Binance Demo, with order ids recorded.
result: pass
source: evidence
evidence: evidence/09-DEMO-REHEARSAL-EVIDENCE-smoke-20261106T160307Z.json: mode EXECUTE, base_url demo-fapi.binance.com, outcome COMPLETE, failures [], evidence_kind DEMO_OBSERVED, order ids recorded. Earlier same-day files show FAILED runs; only the last one is relied on. Not re-executed here (owner-only).

### 4. Fill via user-data stream and reconcile clean
expected: fill arrives on the user-data stream, protection follows, reconcile finds no divergence.
result: pass
source: automated + evidence
evidence: test_live_stream_to_protection.py green; the same Demo file records reconcile_after_fill agreement true, divergences 0, user_data_liveness state LIVE.

### 5. SAFE_MODE drill
expected: SAFE_MODE blocks entries while monitoring continues, and the operator can exit it.
result: pass
source: automated
evidence: test_live_safe_mode_drill.py green (also under TRADING_CI_STRICT=1 in the plan 24-32 run). A drill on Demo is covered by the smoke evidence only as far as that file records it; not independently re-observed.

### 6. Restart and rehydrate with replayed callbacks, no duplicate orders
expected: restart mid-flow rehydrates plans and intents; replayed callbacks create no second order.
result: pass
source: automated + evidence
evidence: tests/test_live_replay_restart_pg.py, test_live_stream_persistence_pg.py, test_approval_replay_pg.py green with TRADING_CI_STRICT=1 and PostgreSQL; test_live_restart_rehydrate.py green; Demo file lists first_process_shutdown_failed_steps [].

### 7. Live placement stays disabled and the process fails closed
expected: LIVE_ORDERS_DISABLED holds; bad config, DEGRADED health or a stale mark price refuse to enable.
result: pass
source: automated
evidence: test_live_config_refusal.py, test_live_enablement_wiring.py, test_live_start_sequence.py green. No mainnet use anywhere in this session.

### 8. Single VPS under Docker Compose, heartbeat and IP whitelist
expected: full runtime on the VPS with restart policies, heartbeat covering every long-running process, Demo key whitelisted to the VPS address.
result: blocked
blocked_by: server
reason: Compose service test (docker-marked) passed 2026-11-07 and heartbeat/env-split tests are green, but the VPS bootstrap, heartbeat firing and IP whitelist are host actions only the owner can run (RUNBOOK sections 13 and 17; plan 24-33).

### 9. Unknown-chat or other-user tap rejected live (G2-014)
expected: a tap from an unknown chat is rejected with no state change and a journaled chat_gate_rejected.
result: blocked
blocked_by: third-party
reason: needs a second Telegram account or a group; library-level rejection is covered by tests but never observed live.

### 10. Runtime Python version and git revision in health output (OPS-04)
expected: health and diagnostic output show the Python version and the application git revision.
result: pass
source: automated
evidence: test_code_version.py, test_live_runtime_cli.py and test_dockerfile_revision_stamp.py green in the 2026-11-07 runs.

### 11. Owner end-to-end session (plan 24-33)
expected: owner runs the runbook in one session and records results verbatim.
result: blocked
blocked_by: prior-phase
reason: plan 24-33 has no SUMMARY; owner-run checkpoint not yet executed.

## Summary

total: 11
passed: 8
issues: 0
pending: 0
skipped: 0
blocked: 3

## Gaps

[none yet]
