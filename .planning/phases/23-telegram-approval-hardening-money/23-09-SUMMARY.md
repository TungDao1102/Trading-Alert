---
phase: 23-telegram-approval-hardening-money
plan: 09
subsystem: telegram-messages
status: complete
tags: [telegram, approval-message, money-at-stake, utc, golden-fixtures, simulate, tdd]
requirements-addressed: [APRV-01]
requires:
  - phase: 23-02
    provides: "MoneyAtStake, parse_money_json, MONEY_AT_STAKE_MISSING"
  - phase: 23-03
    provides: "scripts/gen_phase23_fixtures.py render_all() and --check, tests/fixtures/phase23/DERIVATIONS.md"
provides:
  - "src/adapters/telegram_notify.py: format_utc, _approve_lines, format_approve (UTC, no Display note), render_money_block, require_money_consistent, format_approval_request, REQUEST_MODE_LABELS, build_decision_keyboard"
  - "src/paper/notify.py: format_simulate(..., approved_quantity, money) and notify_simulate payload keys approved_quantity and money"
  - "generator _messages_section(), approve_fields(), fixture_money(), fixture_money_json(); goldens messages/{approve_base,approve_request_demo,approve_request_live,simulate}.txt"
  - "tests/support/simulate_payload.py: make_simulate_payload(), make_money()"
affects: [23-11, 23-12, 23-13]
tech-stack:
  added: []
  patterns:
    - "the message layer only formats stored values: format(value, 'f') and string joins (AST test: no BinOp/AugAssign in the money renderers)"
    - "one shared consistency check (require_money_consistent) used by the DEMO/LIVE request and SIMULATE"
key-files:
  created:
    - tests/support/simulate_payload.py
    - tests/fixtures/phase23/messages/approve_base.txt
    - tests/fixtures/phase23/messages/approve_request_demo.txt
    - tests/fixtures/phase23/messages/approve_request_live.txt
    - tests/fixtures/phase23/messages/simulate.txt
  modified:
    - src/adapters/telegram_notify.py
    - src/paper/shadow.py
    - src/paper/notify.py
    - scripts/gen_phase23_fixtures.py
    - tests/fixtures/phase23/DERIVATIONS.md
    - tests/test_approval_message.py
    - tests/test_paper_notify.py
    - tests/test_phase23_fixtures.py
    - tests/test_paper_reviewfix_pins.py
key-decisions:
  - "Money lines sit directly after Quantity: Notional, Margin (leverage and its source), Loss at SL gross and net, one Profit line per TP, Equity used (source, observed time in UTC); every value is format(value, 'f') of the stored Decimal."
  - "A request refuses (ValueError) a money that is missing (text names MONEY_AT_STAKE_MISSING) or disagrees on direction, quantity, stop, the number of TPs, a TP price or a TP fraction; the mode label must be DEMO or LIVE."
  - "The shared check and the renderers live in telegram_notify and are imported by src/paper/notify.py, because tests/test_paper_notify.py pins the set of functions defined in notify.py."
  - "D025 (Asia/Ho_Chi_Minh as presentation zone) vs D-14 (UTC with suffix, O-3 open) is recorded, not resolved: D025 is not edited; SHADOW texts keep their UTC + Asia/Ho_Chi_Minh pairs."
metrics:
  completed: 2026-10-25
commits: 6
plan_head_before: 3b4789cc9be79d9f96cd77644409b07a239a3196
plan_head_after: 08f947ce2af3ca5ad0af219e19267883066d21e1
actuals:
  tokens: 15000
  tasks: 3
  commits: 6
---

# Phase 23 Plan 09: Money at stake and honest times in the approval messages Summary

The DEMO/LIVE APPROVE request and the SIMULATE message now show the quantity and the full money block (notional, margin with leverage source, loss at the stop gross and net, profit per take-profit gross and net, equity with source and observation time), formatted from the stored `MoneyAtStake` with no arithmetic; every time reads `YYYY-MM-DD HH:MM:SS UTC`, the false `Display: Asia/Ho_Chi_Minh` note is gone, and one APPROVE+SKIP keyboard serves every mode. SHADOW text is byte-identical.

## What was built

- **Task 1 (tracer; RED `9167ad41`, GREEN `2d88fdd3`).** `format_utc`; `format_approve`'s validation and lines moved into `_approve_lines` (optional `mode_label` and `money_lines`), Detected and Expiry via `format_utc`, no Display line; `render_money_block`; `require_money_consistent`; `format_approval_request` (labels DEMO/LIVE only, `Mode:` line after the first line, money lines after `Quantity:`). `format_shadow_alert` strips exactly two lines (`Detected: `, `Expiry: `) in the same commit so SHADOW never raises. Generator `_messages_section()` plus three goldens and a "Messages" section in DERIVATIONS.md (each figure derived from the 23-02 LONG fixture inputs).
- **Task 2 (`3d05e6b4` tests, `989145a6` src).** `build_decision_keyboard` (one row, `APR:` and `SKP:`, 36 bytes each); `build_shadow_decision_keyboard` delegates (wire-identical, asserted). `build_approve_keyboard`, `build_skip_keyboard`, `build_simulate_keyboard` unchanged; docstrings state that no production path sends them since Phase 23. Refusal tests (money None or not a MoneyAtStake, quantity, stop, direction, TP count, TP price, TP fraction, bad labels) and a plain-figure test (`1E+2` prints `100`, `0.100` stays `0.100`, no exponent text anywhere).
- **Task 3 (RED `bd51fac7`, GREEN `08f947ce`).** `format_simulate` requires `approved_quantity` and `money`, prints the Quantity line and the same money lines as the request, UTC times, no Display note; `notify_simulate` reads both keys and a payload without them or with a disagreeing money is FAILED with zero attempts and no bot call. Golden `simulate.txt`.

## Verification

- Plan verification command (12 test files incl. `test_paper_reviewfix_pins.py`): 441 passed. `tests/test_paper_shadow_messages.py`, `test_paper_shadow_buttons.py`, `test_paper_shadow_confirm.py`, `test_paper_shadow_isolation.py` pass unedited; `git log --grep="(23-09)" -- tests/test_paper_shadow_messages.py tests/shadow_fakes.py` prints nothing.
- `uv run python -m scripts.gen_phase23_fixtures --check` exits 0; `grep -c Asia/Ho_Chi_Minh tests/fixtures/phase23/messages/*.txt` is 0 for each of the four files; no `Display: Asia/Ho_Chi_Minh` in `src/adapters` or `src/paper` source.
- Scoped `ruff check`, `ruff format --check` (9 files) and `mypy src/paper/notify.py src/adapters/telegram_notify.py src/paper/shadow.py` clean. `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS. `tests/test_agents_md.py`, `tests/test_domain_no_float.py` pass.
- `git diff --exit-code -- pyproject.toml uv.lock docs/trading/RISK_MANAGEMENT.md docs/DECISIONS.md` exits 0 (T-23-SC: no dependency change; D025 not edited).
- Line endings: the CRLF working files (`telegram_notify.py`, `notify.py`, `shadow.py`, `gen_phase23_fixtures.py`, `test_approval_message.py`, DERIVATIONS.md) kept CRLF; numstat shows no whole-file rewrite. `tests/test_paper_notify.py` is LF in the working tree and stayed LF.
- Tracer gate: after Task 1 the `<verify>` set (plus demo-rehearsal and phase8 reviewfix tests) was re-run end to end and passed before Task 2 started.
- Evidence label: executed tests and generated goldens [DESIGN]; no DEMO/LIVE sender is composed until Phase 24 (plans 23-11 and 23-12 call `format_approval_request`).

## Deviations from Plan

**1. [Rule 3 - Blocking] `tests/test_paper_reviewfix_pins.py` and a new `tests/support/simulate_payload.py`.** Three tests there send a SIMULATE payload through `notify_simulate`; with the new required keys they would fail closed. `_notify_payload()` now returns `make_simulate_payload(signal_id="sig_pin_0001")`, a payload with a money block built by the real `build_money_at_stake`. The helper is shared with `tests/test_paper_notify.py`. Neither file was in `files_modified`.

**2. [Rule 3 - Blocking] Shared helpers live in `telegram_notify`, not `notify.py`.** `tests/test_paper_notify.py::test_no_inbound_handler_can_mutate_approval_state` pins the set of functions defined in `src/paper/notify.py`, so the plan's "extract a shared private check" went into `src/adapters/telegram_notify.py` (public `require_money_consistent`) and `notify.py` imports it.

**3. [Rule 2 - correctness] Direction check added.** `require_money_consistent` also refuses a money block whose side differs from the message direction (the plan listed quantity, stop, TP prices and fractions); it also refuses a different number of TP legs.

**4. [Process] Task 2 had no failing RED for the refusal tests.** The Task 1 implementation already enforced every refusal, so those tests passed on first run; only the keyboard test failed (observed, then fixed). Committed as a `test(23-09)` commit followed by the `feat(23-09)` keyboard commit.

**5. [Plan example text] Money figures.** The plan's example `Margin: 801.6` is written `801.60` (the stored Decimal keeps its exponent; the renderer writes every digit), and profits show `36.000` / `33.1692000`. The golden files hold the generated text; DERIVATIONS.md explains the trailing zeros.

**6. [Not needed] `tests/test_demo_rehearsal_flow.py`.** Listed in `files_modified`, but none of its pins named the old time or Display lines, so it is unchanged and passes. `scripts/demo_rehearsal.py` calls `format_approve` and now renders UTC times.

**7. [Environment] Regenerating goldens rewrote the 16 alert goldens' working-copy line endings.** They are tracked LF with a CRLF working copy under `core.autocrlf`; the generator writes LF. No content differs, they show as modified in `git status`, and none was staged.

## Owner-visible conflict (for plan 23-13's register)

`docs/DECISIONS.md` D025 names Asia/Ho_Chi_Minh the canonical presentation timezone; D-14 (with O-3 open) shows these messages in UTC with an explicit suffix. Done per D-14 and orchestrator resolution 8; D025 is not edited. SHADOW alerts keep their UTC + Asia/Ho_Chi_Minh pairs.

## Known Stubs

None. `format_approval_request` has no production caller until plans 23-11 and 23-12 (Phase 24 composes the senders); `build_decision_keyboard` is used by SHADOW through the delegating `build_shadow_decision_keyboard`.

## Threat Flags

None. T-23-27 (mismatch refused, values only formatted, AST test, goldens), T-23-28 (money required, SIMULATE without it is FAILED with zero attempts), T-23-29 (explicit " UTC" on every time, false note removed, D025/O-3 raised) mitigated as planned; T-23-SC: no dependency change.

## Self-Check: PASSED

- FOUND files: tests/support/simulate_payload.py, tests/fixtures/phase23/messages/{approve_base,approve_request_demo,approve_request_live,simulate}.txt
- FOUND commits (ancestors of HEAD): 9167ad41, 2d88fdd3, 3d05e6b4, 989145a6, bd51fac7, 08f947ce
