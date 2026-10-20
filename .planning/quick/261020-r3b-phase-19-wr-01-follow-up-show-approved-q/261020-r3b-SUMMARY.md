---
phase: quick-261020-r3b
plan: 01
subsystem: telegram-approval-message
tags: [phase-19, WR-01, APRV-01, RISK-04, D078, approval, telegram]
requires:
  - quick-261020-q1o (approvals.approved_quantity, D078)
provides:
  - "format_approve renders `Quantity: <value>` (required, validated approved_quantity)"
  - "SHADOW alert and Demo rehearsal approval message show the stored approved quantity"
  - "D078 item (6) Display"
affects:
  - src/adapters/telegram_notify.py
  - src/paper/shadow.py
  - scripts/demo_rehearsal.py
tech-stack:
  added: []
  patterns: ["fail-closed required keyword", "format(Decimal, 'f') fixed-point rendering"]
key-files:
  modified:
    - src/adapters/telegram_notify.py
    - src/paper/shadow.py
    - scripts/demo_rehearsal.py
    - tests/test_approval_message.py
    - tests/test_phase8_audit_reviewfix.py
    - tests/test_paper_shadow_messages.py
    - tests/test_demo_rehearsal_flow.py
    - docs/DECISIONS.md
    - docs/DOC_STATUS.md
    - docs/integration/TELEGRAM.md
    - docs/data/DATA_MODEL.md
    - .planning/phases/19-execution-plan-binding-price-check/19-OWNER-GAPS.md
    - .planning/phases/19-execution-plan-binding-price-check/19-REVIEW-FIX.md
    - .planning/phases/23-telegram-approval-hardening-money/23-NOTES.md
decisions:
  - "No new DECISIONS row; D078 amended with item (6) (DC-02 contiguity with unwritten provisional D079/D080; TELEGRAM.md section 4 lists the 12 fields as a minimum)"
  - "Shown figure is the stored value: SHADOW plan.quantity_after_rounding (same frozen attribute ShadowApprovalBook.issue stores), Demo issued.approval.approved_quantity"
  - "Rendering is format(value, 'f'): fixed-point, every digit, no rounding, no exponent, no float, no clock"
  - "approved_quantity is a required keyword-only parameter of format_approve, validated as a finite Decimal above zero"
metrics:
  duration: "about 22 minutes"
  completed: 2026-10-20
status: complete
actuals:
  tokens: 14000
  tasks: 3
  commits: 5
plan_head_before: 996f91ffb4a305abe6d22febcc01e2199c213978
plan_head_after: 00c79b21c1bd7027acc21ea23c820760305861ca
commits: 5
---

# Phase quick-261020-r3b Plan 01: Show the approved quantity on the APPROVE message Summary

The APPROVE message (`format_approve`, used by the SHADOW alert and the Demo rehearsal approval message) now carries a `Quantity:` line directly after `Entry:`, showing the exact `approved_quantity` that D078 stores on the approval row and that `bind_plan` later enforces.

## What changed

- `format_approve` takes a required keyword-only `approved_quantity: Decimal`. A missing keyword raises TypeError; None, bool, int, float, str, a non-finite Decimal, zero or a negative value raise ValueError naming `approved_quantity`. The line is `Quantity: {format(approved_quantity, 'f')}`.
- `format_shadow_alert` passes `plan.quantity_after_rounding` (the attribute `ShadowApprovalBook.issue` writes to both PENDING rows). `send_shadow_alert` keeps format-before-issue, so a zero-quantity plan is refused before anything is stored or sent.
- Demo rehearsal: `render_approval_text` takes `approved_quantity` and `issue_and_send` feeds it from `issued.approval.approved_quantity`; an Approval with no stored quantity records a FAILED step `approval carries no approved quantity` and aborts (ABORTED_NO_ORDER) before any send, with no `telegram_send` failure.
- Docs: D078 item (6) added and item (5) corrected in place (still 78 rows, ends at D078); TELEGRAM.md section 4, DATA_MODEL 2.5, DOC_STATUS, 19-OWNER-GAPS WR-01 row, 19-REVIEW-FIX batch 4 and 23-NOTES updated.

## Planning decisions (as recorded in the plan)

1. No new DECISIONS row; D078 item (6) amends the row (DC-02 contiguity, D079/D080 are unwritten provisional ids; the 12 fields are a minimum).
2. Same value as the stored row (SHADOW: frozen plan attribute; Demo: the issued Approval object).
3. `format(value, "f")` formatting; label `Quantity:`, directly after `Entry:`.
4. Fail closed: required keyword, validated like `Approval.approved_quantity`.
5. Out of scope: SIMULATE message, notional/margin/loss/profit/equity (Phase 23 criterion 2), consume-time database check (follow-up 2 of 2).

## Commits

| Commit | Message |
|---|---|
| 4be03ce | test(19): r3b failing tests for the approved quantity on the APPROVE message |
| a691e72 | feat(19): r3b show the stored approved quantity on the APPROVE message |
| 0d9a50a | test(19): r3b failing test for a Demo approval without a stored quantity |
| 94ff08f | fix(19): r3b a Demo approval without a stored quantity is never sent |
| 00c79b2 | docs(19): D078 item (6) records the approved quantity on the APPROVE message |

## RED evidence

- Task 1 RED (4be03ce): 21 tests failed: tests/test_approval_message.py (12), tests/test_phase8_audit_reviewfix.py (6) and tests/test_paper_shadow_messages.py (3), including existing format_approve callers (TypeError on the unexpected `approved_quantity` keyword for the updated payload helpers; the SHADOW tests failed on the missing `Quantity:` line and DID NOT RAISE).
- Task 2 RED (0d9a50a): the guard test failed (the missing quantity was recorded as a `telegram_send` failure); the per-message test passed already, as the plan predicted (1 failed, 1 passed).

## Verification (own tests only)

- Task 1 set: `pytest -n 4` on 11 files: 423 passed, 0 skipped. PG files (`TRADING_CI_STRICT=1`, `TEST_DATABASE_URL` from the process env): tests/test_paper_shadow_pg.py, tests/test_paper_shadow_reservations_pg.py, tests/test_paper_shadow_runtime_pg.py: 10 passed, 0 skipped.
- Task 2 set (demo flow, safety, binance client config, userdata replay): 161 passed.
- Task 3 set (phase19 gate, agents_md, decision_alignment x4): 197 passed. `verify_decision_alignment.py all`: ALL_PASS. DECISIONS has 78 rows ending at D078.
- `ruff check src tests scripts` clean; `ruff format --check src tests scripts` clean (621 files); `mypy src` clean (214 files); `uv lock --check` clean (62 packages resolved, no change).
- `git diff 996f91f HEAD` over src/core, src/domain, src/execution, src/persistence, src/db, src/approval, params, config, pyproject.toml, uv.lock, AGENTS.md, ROADMAP.md, REQUIREMENTS.md, STATE.md: empty. `git diff --name-only 996f91f HEAD` lists exactly the 14 files of `files_modified`.
- Line endings unchanged per file (CRLF files stayed CRLF, LF files stayed LF); numstat per file is small (docs 1/1, 1/0, 2/0, 1/1, 1/1, 3/0, 5/0).

## Not run

The full suite, `-m docker`, any Demo or network run (`--execute` smoke scripts), and any sequential recorded gate. The orchestrator runs the full suite once.

## Deviations from Plan

None in behavior. Execution notes: edits to CRLF files were made through byte-aware scripts rather than the Edit tool; `format_approve`'s error message was split across two string literals to satisfy the 100-column ruff limit; the Demo guard tests `issued.approval.approved_quantity is None` directly (no extra local variable).

## Known Stubs

None.

## Threat Flags

None. No new endpoint, auth path, file access or schema change; the plan hash, planner, binding, store and migrations are unchanged.

## Self-Check: PASSED

- All five commits are ancestors of HEAD (4be03ce, a691e72, 0d9a50a, 94ff08f, 00c79b2).
- Key-link patterns present: `approved_quantity=plan.quantity_after_rounding` in `format_shadow_alert`, `approved_quantity=issued.approval.approved_quantity` and `approval carries no approved quantity` in scripts/demo_rehearsal.py, `(6) Display` in docs/DECISIONS.md.
