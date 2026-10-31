---
phase: 24-live-runtime-composition-demo
plan: 14
subsystem: live
status: complete
tags: [approval-sender, signal-source, d028, second-plan-refusal, aprv-01, d-18]
requirements-addressed: [APRV-01]
requires: [24-04, 24-08]
provides:
  - "src/live/signal_source.py: SignalSource Protocol, SignalRequest, MoneyInputs, DemoSmokeSignalSource, build_request_money"
  - "src/live/approval_sender.py: ApprovalRequestSender, SendOutcome, make_demo_save_atomic, DemoDeskStores, apply_d028_chain, make_open_demo_approvals_reader"
affects: [24-13, 24-16, 24-17, 24-26, 24-29]
tech-stack:
  added: []
  patterns:
    - "refusal before any write; every conflict source is read and a read failure fails closed"
    - "reservation hook and D028 chain composed through a thin approval-store wrapper, no change to risk_reservations"
key-files:
  created:
    - src/live/signal_source.py
    - src/live/approval_sender.py
    - tests/test_live_approval_sender.py
  modified: []
key-decisions:
  - "A skipped TradePlan keeps APPROVAL_PENDING: GLOSSARY 11.2 names no state for a skip (SUPERSEDED means replaced before the human decided). Only the Signal moves (SKIPPED_USER / SKIPPED_BUSY). Open for the orchestrator or owner (possible DECISIONS row)."
  - "The Signal is persisted DETECTED and moves DETECTED -> NOTIFIED only after a successful send, because DETECTED -> APPROVED is illegal in GLOSSARY 11.1."
  - "The REQUESTED risk reservation is registered through an injected register_reservation callable, not by calling register_request, so the Phase 22 gate (invariant 13, nothing in src calls register_request) stays green."
  - "An open approval blocks a symbol only while its plan has not expired; otherwise an APPROVED approval of a finished plan would block the symbol forever."
plan_head_before: cc6e912c979c531661c70b9981cc58ea457fcf9a
plan_head_after: fbc32d1c658189ced7cc9440049ee0a443f6e306
commits: 1
actuals:
  tokens: 25700
  tasks: 3
  commits: 1
completed: 2026-10-31
---

# Phase 24 Plan 14: Approval request sender and SignalSource interface Summary

A DEMO signal now becomes one owner-approvable Telegram card (APRV-01 fields plus the stored money block) through `ApprovalRequestSender`, a second plan on a busy symbol is refused from five sources before any write, and the approval decision, its Phase 21 reservation and the D028 Signal/TradePlan chain commit or roll back as one transaction.

## What was built

- `src/live/signal_source.py`
  - `SignalSource` Protocol (`async next_request() -> SignalRequest | None`, never blocks), `SignalRequest` (signal, plan, `latest_closed_bar_close`, `MoneyInputs`, exposure, reason codes), `build_request_money` (money block from the SIZED result, never recomputed, F-015).
  - `DemoSmokeSignalSource`: the derivation of `scripts/demo_rehearsal.py derive_plan` moved behind the Protocol (rehearsal not edited; plan 24-29 switches it). The unmodified `evaluate_risk` must size exactly the derived quantity or `SignalDerivationError` is raised. Ids come from the namespace `demo-smoke:v1`, run id, symbol and sequence, so they never equal a SHADOW `make_signal_id` (P-8). `expected_rr_json` carries `tp1_rr` / `tp2_rr` (the rehearsal's `rr` key would not render on the desk's card). Strategy-driven DEMO signals are not built and nothing from the paper pipeline is imported.
- `src/live/approval_sender.py`
  - `ApprovalRequestSender.send_request`: validates the request (DETECTED signal, APPROVAL_PENDING unexpired plan), refuses a second plan from five sources (active tracked plan, unresolved ENTRY intent, resting entry order, non-zero REST position, unexpired PENDING/APPROVED DEMO approval) with `CONFLICT_WITH_OPEN_POSITION`, fail closed with `UNCERTAIN_ACCOUNT_STATE` and the read failure journaled by class name only. Then `money_for`, `desk.issue`, optional `register_reservation`, `desk.send`, and `DETECTED -> NOTIFIED` after the send. A lock serialises requests. A send failure approves nothing (both approvals PENDING, desk journals it). The sender holds no placement port and never calls the manager.
  - `make_demo_save_atomic` (+ `DemoDeskStores`, `apply_d028_chain`): `make_reserving_save_atomic` with the D028 chain in the same after_decide hook (reservation first, then Signal, then TradePlan). APPROVED: Signal APPROVED then TradePlan APPROVED. SKIPPED: Signal SKIPPED_USER (SKIPPED_BUSY for SKIP_BUSY). EXPIRED: Signal and TradePlan EXPIRED. Any failure rolls everything back.
  - `make_open_demo_approvals_reader`: PENDING approvals counted only with the DEMO marker of plan 24-08, APPROVED ones from the DEMO-scoped store.

## Verification

- `uv run pytest -m "not docker"` on tests/test_live_approval_sender.py (60 tests), tests/test_approval_desk.py, tests/test_live_ast_guards.py, tests/test_phase22_gate.py: all pass.
- `uv run mypy src/live` clean; scoped `ruff check` and `ruff format --check` clean; `git diff --exit-code -- pyproject.toml uv.lock` exits 0; `grep -n "src.paper"` on the two new modules prints nothing.
- Covered: tracer card with money rows and one send; ids differ from SHADOW ids; send failure leaves both approvals PENDING; five parametrized conflict sources plus fail-closed read failures, finished plans, other symbols, expiry of an open approval, SHADOW pending not blocking, concurrent requests; D028 order, skip/expiry targets, rollback of decision + reservation + transitions, a press through `on_callback`.
- PostgreSQL: the module's 4 `test_pg_*` cases (composed `make_demo_save_atomic` against the real stores: approve, skip, expiry, rollback) PASSED. `TEST_DATABASE_URL` is set in this shell, so they ran with the module; they use the throwaway `_test` clone fixture. No other `*_pg.py` file was run. Later runs unset the variable.
- Not run: the full suite (orchestrator).

## Deviations from Plan

**1. [Rule 2 - Missing critical functionality] `register_reservation` seam**
- **Found during:** Task 3. `reserve_in` only turns a REQUESTED row into RESERVED, and no Phase 24 plan registers that row (grep of the phase plans and `src`). Without it every APPROVE press would be refused `UNCERTAIN_ACCOUNT_STATE`. Calling `PgRiskReservationStore.register_request` from `src` would break `tests/test_phase22_gate.py` invariant 13 on purpose.
- **Fix:** optional injected `register_reservation(request, money, now)` on the sender (called after the rows exist, before the card is sent; if it raises, no card goes out). The composition plan binds it to `register_request` and updates invariant 13 / 22-DEFERRED on purpose. A reservation also needs `required_margin` for the margin claims (plan 24-16 reads `list_margin_claims`).
- **Files:** src/live/approval_sender.py. **Commit:** fbc32d1c.

**2. [Rule 3 - Blocking] D028 chain composed by wrapping, not by editing `risk_reservations`**
- `make_reserving_save_atomic` has no extension parameter, so a thin `_ChainedApprovals` proxy hands the store a combined hook (reservation hook, then the chain). `risk_reservations.py` is untouched.

**3. [Rule 1/2] Signal NOTIFIED transition added**
- The desk inserts the Signal as given and DETECTED -> APPROVED is illegal, so the sender moves DETECTED -> NOTIFIED after a successful send (journaled `DEMO_SIGNAL_NOTIFY_FAILED` if that fails; the card then cannot be approved, fail closed).

**4. Skipped plan state and equity label (judgement calls, see key-decisions and Known gaps).**

**5. Process:** the three tasks share two new modules and one test file, so they were committed together in one commit instead of one per task.

## Known gaps for the orchestrator

- DECISIONS row candidate (D090, orchestrator assigns): "a skipped TradePlan keeps APPROVAL_PENDING" and "Signal is NOTIFIED after the send".
- The smoke card shows `Equity used: ... (PAPER_CONFIG:initial_equity)` and `Margin ... (PAPER_CONFIG:target_leverage)`: the back-solved rehearsal equity needs a label from the existing vocabulary and `ACCOUNT_LIVE` would be false. The `DEMO_SMOKE` reason code marks the card; a dedicated source label would need a `money_at_stake` change (not in this plan's files).
- Sync store reads (`protections`, intents, approvals reader) run on the event loop inside `send_request`; plan 24-26 may wrap them (plan 24-17 moves the dispatch side to the writer thread).
- `PgShadowStores.list_pending_approvals` is not mode-scoped; the reader filters by the DEMO marker. The composition must build the reader on a `confirm_mode="DEMO"` store (enforced).
- `positions_reader` and `register_reservation` implementations over the adapter / reservation store belong to the composition plan (24-26 or the plan that wires the sender).
- `DemoDeskStores` must be what `ApprovalDesk` is built with, otherwise a press bypasses the reservation and the chain.

## Self-Check: PASSED

- FOUND: src/live/signal_source.py, src/live/approval_sender.py, tests/test_live_approval_sender.py
- FOUND commit fbc32d1c (ancestor of HEAD)
