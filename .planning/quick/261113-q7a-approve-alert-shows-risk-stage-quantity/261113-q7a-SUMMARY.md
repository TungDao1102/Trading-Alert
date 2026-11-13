---
phase: quick-261113-q7a
plan: 01
subsystem: paper-shadow
tags: [shadow-alert, telegram-text, d108, d078, risk-stage-sizing]
requires: [D078, 16-DEC-EQUITY-BASE]
provides: [D108, risk-stage quantity and estimated loss on the SHADOW APPROVE alert]
affects: [src/paper/shadow.py, src/paper/shadow_runtime.py]
key-files:
  modified:
    - src/paper/shadow.py
    - src/paper/shadow_runtime.py
    - tests/test_paper_shadow_messages.py
    - tests/test_paper_shadow_runtime.py
    - tests/test_paper_shadow_money.py
    - tests/test_paper_shadow_confirm.py
    - tests/test_paper_shadow_buttons.py
    - docs/DECISIONS.md
    - docs/DOC_STATUS.md
decisions:
  - "D108: the SHADOW APPROVE alert shows verdict.sized quantity and estimated loss (card helpers); approved_quantity stays the planner quantity (D078)"
status: complete
commits: 3
plan_head_before: 38236862f5edd61187966092d46c5625802ffd8a
plan_head_after: d175a932d71c3c454ddbea26d345548ca609183b
actuals:
  tokens: 45000
  tasks: 3
  commits: 3
completed: 2026-11-14
---

# Phase quick-261113-q7a Plan 01: SHADOW alert shows the risk-stage quantity Summary

The SHADOW APPROVE alert now shows `verdict.sized.quantity` on `Quantity:` and a new `Estimated loss at SL (incl. costs): <realized_risk> quote` line, through the same two line helpers the confirmation card uses; `approved_quantity` on both approval rows stays the planner quantity (D078), recorded as D108.

## Commits (branch quick/261113-alert-qty)

| Task | Commit | Message |
|---|---|---|
| 1 RED | 0b17cfac | test(quick-261113-q7a): the SHADOW alert shows the risk-stage quantity and loss, rows keep the planner quantity (RED) |
| 2 GREEN | b1f6a5c1 | feat(quick-261113-q7a): the SHADOW alert shows the risk-stage quantity and estimated loss of the card; approved_quantity unchanged |
| 3 docs | d175a932 | docs(quick-261113-q7a): record D108, the SHADOW alert shows the risk-stage figures |

The orchestrator commits this PLAN.md and SUMMARY.md in a fourth docs commit.

## What changed

- `src/paper/shadow.py`: module-private `_QUANTITY_PREFIX`, `_ESTIMATED_LOSS_PREFIX`, `_quantity_line`, `_estimated_loss_line` (used by the CONFIRM_CARD branch and by the alert; card bytes unchanged), `_risk_stage_figures(sized)` (None / NO_TRADE / no quantity gives `(None, None)`), `_require_money_matches_sizing` (V2 only). `format_shadow_alert` and `send_shadow_alert` take keyword-only `sized: SizedResult | None` with no default. Order: V1 `Entry`, `Quantity`, estimated loss, `SL`; V2 `Entry`, `Quantity`, money rows, estimated loss, `SL`. Docstrings and the V1/V2 comment updated.
- `src/paper/shadow_runtime.py`: `on_outcome` passes `sized=verdict.sized` (one line).
- Tests: 12 new `d108` tests (11 in test_paper_shadow_messages.py, 1 end-to-end in test_paper_shadow_runtime.py); two obsolete r3b tests replaced; the existing V2 pin and the lifecycle test extended; three files updated mechanically for the new required keyword.
- Docs: DECISIONS D108 (appended after D107, 0 lines removed), DOC_STATUS dated line.

## Verification

- 369 passed in the ten regression files (baseline 359, +12 d108, -2 replaced r3b tests).
- Occurrence counter `(3, 1, 1)`: three D078 `approved_quantity=plan.quantity_after_rounding` sites intact, `sized=verdict.sized` once, quoted wording literal once in src.
- No diff since 38236862 under src/adapters, src/live, src/execution, src/approval, src/paper/notify.py, src/paper/shadow_confirm.py, params, config, scripts, tests/fixtures.
- ruff check and ruff format --check clean (src and tests: 931 files formatted); mypy src: no issues in 291 files.
- `scripts/verify_decision_alignment.py all`: ALL_PASS; test_decision_alignment_bookkeeping.py and test_agents_md.py: 49 passed.
- Worktree check: `src.__file__` resolved inside Trading-Alert-wt-alert-qty.

## V2 resolution

The planner check (`require_money_consistent(..., approved_quantity=plan.quantity_after_rounding, ...)`) is unchanged and runs first. A new check, V2 only, requires `sized` and `money.quantity == sized.quantity` and `money.loss_at_stop_net == sized.realized_risk`. A V2 alert still renders only when the planner and risk-stage quantities agree (pre-existing); only V1 (the production default) can show a `Quantity:` different from `approved_quantity`.

## Deviations from Plan

None - plan executed exactly as written. Two small notes: the plan's `sized`-with-`None` test helper `_send` uses a string sentinel default so that `sized=None` can be passed explicitly; the plan's SUMMARY-uncommitted instruction was superseded by the orchestrator (PLAN and SUMMARY are committed with explicit paths).

## Known Stubs

None.

## Owner follow-ups

(a) `docs/integration/TELEGRAM.md` section 4 still words the `Quantity:` line per D078 item (6); for the SHADOW alert D108 applies (not edited here, forbidden scope).
(b) The change reaches the host only with a new paper image; the owner decides about an epoch pin, as for 16-DEC-EQUITY-BASE.
(c) Pre-existing V2 limitation: a V2 alert renders only when the planner and risk-stage quantities agree.
(d) The orchestrator runs the full suite once.

## Self-Check: PASSED

Commits 0b17cfac, b1f6a5c1, d175a932 are ancestors of HEAD; all modified files exist.
