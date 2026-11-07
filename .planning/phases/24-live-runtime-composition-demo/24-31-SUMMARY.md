---
phase: 24-live-runtime-composition-demo
plan: 31
subsystem: docs
tags: [decisions, runbook, telegram, data-model, agents-md, D098, D107, O-7, D-35]
requires: [24-06, 24-24, 24-25, 24-28, 24-29, 24-35]
provides:
  - "DECISIONS D098 to D106 (owner answers to 24-01 Q1 to Q8, Q11 to Q13, Q15) and D107 (Provisional)"
  - "RUNBOOK section 22 Live process (Phase 24) and the rewritten stale status lines"
  - "TELEGRAM.md live bot section, DATA_MODEL 0015 and approval mode marker, SECURITY_AND_OPERATIONS WR-06 closed"
  - "AGENTS.md routes agents to src/live/ and python -m src.live.runtime"
affects: [24-32]
key-files:
  modified:
    - docs/DECISIONS.md
    - docs/data/DATA_MODEL.md
    - docs/operations/RUNBOOK.md
    - docs/integration/TELEGRAM.md
    - docs/operations/SECURITY_AND_OPERATIONS.md
    - docs/DOC_STATUS.md
    - AGENTS.md
    - tests/test_phase20_gate.py
key-decisions:
  - "No existing DECISIONS row was edited by this plan (D097 was moved to Accepted earlier, commit e635d57a); ten rows were appended."
  - "Q9 (liquidation policy) and Q14 (verification flags) followed D085 and D086, so they have no new row; Q10 (SHADOW text version), Q16 (exact quantity compare) and Q15 (restart policy, in D106) need no rule beyond the plans that built them."
  - "Demo claims cite only what the smoke evidence 09-DEMO-REHEARSAL-EVIDENCE-smoke-20261106T160307Z.json lists as OBSERVED (21 of 21 steps); heartbeat, compose service, image revision stamp, /status, /disable_entries and /close as typed commands stay NOT_OBSERVED."
metrics:
  tasks: 3
  completed: 2026-11-07
status: complete
---

# Plan 24-31 summary

## New DECISIONS ids

| Id | Topic | Status |
|---|---|---|
| D098 | one live process, one loop (24-01 Q1) | Accepted, owner 2026-10-31 |
| D099 | StoreExecutor seam (Q2) | Accepted |
| D100 | migration 0015_order_event_time (Q3) | Accepted |
| D101 | SignalSource and the Demo smoke injector (Q4) | Accepted |
| D102 | DEMO enablement, feed probe meanings, D056 rows (Q5) | Accepted |
| D103 | live Telegram identity (Q6) | Accepted |
| D104 | operator commands and their authentication (Q7) | Accepted |
| D105 | mode-scoped approved-approvals reader (Q8) | Accepted |
| D106 | heartbeat per process, baked limits, revision stamp, restart policy (Q11, Q12, Q13, Q15) | Accepted |
| D107 | env split (D-29) and open-algo cancel confirmation (D-34) | Provisional, owner may override |

Each Accepted row quotes the owner's words of 2026-10-31 verbatim ("theo recommend của bạn hết đi, nếu có chỗ nào khó quyết, hãy thông báo với tôi"), names the 24-01 question, says what was built and how it is tested, what the Demo smoke observed, what stays open, and that LIVE_ORDERS_DISABLED stays.

## Documents

- RUNBOOK: new section 22 (verbs, start sequence, host clock rule, first-install gate and spill sentinel, env and compose, owner-run rehearsal with `demo_clear.py` and the `REHEARSAL:` Telegram messages, observed and not observed, open items); status lines of sections 3, 7, 11.9, 21, 21.2 and 21.3 rewritten (the acceptance grep for "composition is Phase 24" is 0); a known-limit paragraph in 21.4; the stale `TELEGRAM_CHAT_ID` name in 21.1a corrected to `TELEGRAM_LIVE_AUTHORIZED_CHAT_ID`. The WR-B6 and WR-C3 sentences were already in section 7 and stay.
- TELEGRAM: the "Not composed yet" bullet replaced; a "Phase 24: the live bot" section.
- DATA_MODEL: `exchange_event_time_utc`, `snapshot_event_time_utc`, `update_position_snapshot`, the `APPROVAL_MODE_RECORDED` marker, the D028 chain on the DEMO path.
- SECURITY_AND_OPERATIONS section 1: per-service env files, WR-06 closed, no more "live credentials commented out until Phase 24".
- AGENTS.md: `src/live/` row, entry point, execution-model note, the still-open limit key corrected; the gated Quantization bullet and the FastAPI row are untouched. DOC_STATUS change-log line added.
- `tests/test_phase20_gate.py` pins the ids after D078; its expected list and message now include D098 to D107.

## Verification

- `scripts/verify_decision_alignment.py all`: ALL_PASS.
- The docs-pinning tests (agents, decision alignment, deploy docs, kill-gate docs, phase 18 to 23 gates, soak runbook, research protocol) pass except one, below.
- `git diff -- pyproject.toml uv.lock src` is empty.

## Findings

1. **tests/test_phase18_gate.py::test_invariant_6_placement_is_single_attempt_and_decides_on_no_message_text fails** (`379: str(exc) outside a logger call`). The line is `src/execution/manager.py` in the `except PreSendRefusal` branch that commit 35d6904f added (journal why a placement was refused before sending). It is not caused by this plan and was not touched here (no `src` changes). It needs a decision: allow-list that call in the guard because `PreSendRefusal` messages are fixed project text, or journal the exception class only.
2. Open items recorded in RUNBOOK 22.7 and D104: no re-issued CONFIRM card after a restart (24-28 finding 1, owner decision pending, recommendation accept for V1), and the deferred UNTRACKED_SYSTEM_ORDER-on-manual-close case (24-NOTES.md item 7).
3. Not verifiable here: the claims about a host (heartbeat, compose service, image stamp) are documented as NOT_OBSERVED until plan 24-33.
