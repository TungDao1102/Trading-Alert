---
phase: 08-approval-reconciliation-hardening
verified: 2026-10-03T00:00:00Z
status: passed
score: 5/5 success criteria verified at library level by offline tests; 2 live-only human items and 1 bookkeeping item outstanding, 0 blocking gaps
covered_files:
  - .planning/phases/08-approval-reconciliation-hardening/08-01-PLAN.md
  - .planning/phases/08-approval-reconciliation-hardening/08-01-SUMMARY.md
  - .planning/phases/08-approval-reconciliation-hardening/08-02-PLAN.md
  - .planning/phases/08-approval-reconciliation-hardening/08-02-SUMMARY.md
  - .planning/phases/08-approval-reconciliation-hardening/08-03-PLAN.md
  - .planning/phases/08-approval-reconciliation-hardening/08-03-SUMMARY.md
  - .planning/phases/08-approval-reconciliation-hardening/08-04-PLAN.md
  - .planning/phases/08-approval-reconciliation-hardening/08-04-SUMMARY.md
  - .planning/phases/08-approval-reconciliation-hardening/08-05-PLAN.md
  - .planning/phases/08-approval-reconciliation-hardening/08-05-SUMMARY.md
  - src/adapters/telegram_callbacks.py
  - src/adapters/telegram_notify.py
  - src/approval/__init__.py
  - src/approval/binding.py
  - src/approval/mapping.py
  - src/approval/replay.py
  - src/approval/tokens.py
  - src/db/alembic/versions/0003_callback_mapping.py
  - src/execution/order_ids.py
  - src/ops/drills.py
  - src/reconcile/__init__.py
  - src/reconcile/compare.py
  - src/reconcile/safe_mode.py
  - src/reconcile/sweeper.py
  - tests/test_approval_message.py
  - tests/test_approval_replay.py
  - tests/test_drills.py
  - tests/test_order_ids.py
  - tests/test_phase8_audit_reviewfix.py
  - tests/test_reconcile.py
covered_digest: "v2:sha256:8dbd3b86af9f3d5c93b021af2c755b3b54aa87e8426944e4e6d1db297f5b61ab"
behavior_unverified: 0
overrides_applied: 0
gaps: []
deferred:
  - truth: "Reconciler tick, sweeper, Telegram receiver and SAFE_MODE controller are composed into a running process with durable SAFE_MODE"
    addressed_in: "Phase 20 and Phase 24"
    evidence: "ROADMAP Phase 20: 'Reconcile + SAFE_MODE Hardening + Alerts - durable SAFE_MODE'; Phase 24: 'Live Runtime Composition + Demo Rehearsal'"
  - truth: "User-id authorization, two-step CONFIRM card, keyboard removal on the Telegram approval"
    addressed_in: "Phase 23"
    evidence: "ROADMAP Phase 23: 'Telegram Approval Hardening + Two-Step Confirm'"
human_verification: []
---

# Phase 8: Approval + Reconciliation Hardening Verification Report

**Phase Goal:** Human control and exchange-truth safety land before any live order exists - much of it built during the paper soak.
**Verified:** 2026-10-03
**Status:** passed (remaining human items accepted by the operator on 2026-10-04; see the final section)
**Re-verification:** No, initial verification

## Goal Achievement

### Observable Truths (ROADMAP success criteria SC1 to SC5)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC1 | Telegram alerts (SIMULATE/APPROVE/SKIP) carry symbol, direction, setup, entry, SL, TP(s), RR, risk, expiry, invalidation, exposure, reason codes | VERIFIED | `src/adapters/telegram_notify.py` `format_approve_message` renders all 12 fields (risk_pct, expiry in UTC ISO, invalidation, exposure, reason codes) and rejects empty symbol/TPs, inverted entry bounds, naive datetimes, negative SL, newline reason codes. Keyboards emit `apr:`/`skp:` + 32-hex short id within 64 bytes. `tests/test_approval_message.py::test_format_approve_renders_all_12_aprv01_fields`, `test_build_*_keyboard_*` pass. |
| SC2 | Approval bound to SignalId + strategy version + plan hash + expiry + authorized chat + one-time token; 5x replay = exactly one transition; never auto-approves on notify failure; stale/invalid plans unapprovable | VERIFIED | `src/approval/replay.py::resolve_callback`: chat gate before any state lookup, token hashed (sha256, constant-time compare in `tokens.py`), per-token lock, stored decision returned on replay; `binding.py` checks hash/version/expiry. Tests: `test_resolve_callback_5x_replay_produces_exactly_one_transition`, `..._expired_plan...`, `..._exactly_at_expiry_is_unapprovable`, `..._one_second_before_expiry_is_approvable`, `..._plan_hash_mismatch_returns_stale_setup`, `..._version_mismatch...`, `..._wrong_chat_rejected_before_state_lookup`, `..._wrong_token_rejected`, `..._notify_failure_leaves_approval_pending`, concurrency `wr10_concurrent_same_token_single_transition`. Review-fix CR-01 (pressed button decides outcome) and WR-31 (SIMULATE cannot transition) covered by `tests/test_phase8_audit_reviewfix.py`. |
| SC3 | Reconciler comparing local vs open normal orders, open algo orders, positions detects an injected orphan/divergence, sweeps the orphan protective, forces SAFE_MODE | VERIFIED (library level) | `src/reconcile/compare.py` three-source compare incl. ENTRY_WITHOUT_PROTECTIVE (CR-03 fix), `sweeper.py` cancel-only `OrphanSweeper`, `safe_mode.py` `SafeModeController`. `tests/test_reconcile.py`: `test_orphan_protective_divergence_classified_and_swept`, `test_divergence_forces_safe_mode_without_cancel`, `test_entry_without_protective_divergence_does_not_sweep`, `test_transient_position_gap_blocks_premature_sweep`, plus static guards `test_no_place_order_path_in_src_reconcile` and `test_no_binance_sdk_import_in_src_reconcile`. Golden fixture `tests/fixtures/phase8/orphan_divergence`. Not yet driven by a scheduled loop in a running process (deferred, see below). |
| SC4 | Retries, restarts, replays never create duplicate entry orders (deterministic client/algo order IDs) | VERIFIED | `src/execution/order_ids.py` `derive_client_order_id`/`derive_algo_client_id` are pure functions of (64-hex plan hash, role); WR-18 rejects short/non-hex hashes. Consumed by `src/execution/manager.py` (import at line 48). `tests/test_order_ids.py` (21 tests) and golden fixture `order_ids/expected.json` pass. |
| SC5 | RUNBOOK 8 drills rehearsed and logged; SAFE_MODE blocks new entries while monitoring and reconciliation continue | VERIFIED (harness) / human item for real stack | `src/ops/drills.py` `DRILL_NAMES` = the 8 drills, `run_drill`, append-only `DrillLog`, double-run byte-identical (`test_double_run_drill_log_is_byte_identical`), golden `drill_log/expected.json`, no place-order path (`test_no_place_order_invariant_across_all_drills`), SAFE_MODE exit only via restore (`test_safe_mode_exit_only_via_restore_drill`). SAFE_MODE gate: `SafeModeController.guard_new_entries` is gate 3 of `src/execution/manager.py::execute_approved_plan` (line 543), and `enter_safe_mode` is invoked on indeterminate results (line 712); monitoring/reconcile functions keep running (`exit_safe_mode` needs a fresh clean compare plus a journaled restore). All drills use injected fakes; real-stack rehearsal is Human item 3. |

**Score:** 5/5 criteria verified at the library/fake level. Behaviour-dependent items (replay, expiry boundary, orphan sweep, SAFE_MODE exit) were exercised by passing tests, so none is left PRESENT_BEHAVIOR_UNVERIFIED.

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | Runtime composition of reconciler tick, sweeper, PTB receiver; durable SAFE_MODE | Phase 20, Phase 24 | ROADMAP Phase 20 and 24 goals |
| 2 | Telegram user-id auth, working SKIP card, CONFIRM step | Phase 23 | ROADMAP Phase 23 goal |

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `src/approval/{tokens,binding,replay,mapping}.py` | token, binding, replay, short-id mapping | VERIFIED | 62/256/269/135 lines, substantive, imported by telegram_callbacks, execution.manager, persistence.approvals |
| `src/adapters/telegram_callbacks.py` | PTB receiver seam | VERIFIED | 809 lines; PTB imported only here (test enforces) |
| `src/adapters/telegram_notify.py` | 12-field APPROVE/SKIP message | VERIFIED | 328 lines |
| `src/db/alembic/versions/0003_callback_mapping.py` | short-id mapping table | VERIFIED | `test_migration_0003_creates_short_id_mapping_table` passes |
| `src/execution/order_ids.py` | deterministic IDs | VERIFIED | 157 lines, used by manager |
| `src/reconcile/{compare,sweeper,safe_mode}.py` | reconciler, sweeper, SAFE_MODE | VERIFIED | 561/450/459 lines; journal wiring in `src/persistence/journal.py`; guard wired in manager |
| `src/ops/drills.py` | 8-drill harness | VERIFIED | 945 lines |
| `tests/fixtures/phase8/*` | golden fixtures | VERIFIED | replay_5x, order_ids, orphan_divergence, drill_log present |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| telegram_callbacks | approval.replay | `resolve_callback` import (line 59) | WIRED | chat gate runs before resolver (WR-01 test) |
| execution.manager | approval.binding / reconcile.safe_mode | `check_binding_*`, `guard_new_entries` | WIRED | fixed gate order, SAFE_MODE gate 3 |
| execution.manager | order_ids | `derive_*_client_id` | WIRED | |
| persistence.journal | reconcile.safe_mode / sweeper | `JournalLike` protocols | WIRED | |
| reconciler tick -> sweeper -> SAFE_MODE | scheduler/process | none | NOT COMPOSED | library-only by design, deferred to Phase 20/24 |

### Behavioral Spot-Checks and Command Results

| Check | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| Phase tests (offline) | `.venv/Scripts/python.exe -m pytest tests/test_approval_replay.py tests/test_approval_message.py tests/test_order_ids.py tests/test_reconcile.py tests/test_drills.py tests/test_approval_replay_pg.py tests/test_persistence_approvals_pg.py` | 82 passed, 32 skipped (all skips are `TEST_DATABASE_URL is not set` PostgreSQL tests) | PASS |
| Audit tests | `.venv/Scripts/python.exe -m pytest tests/test_phase8_audit_reviewfix.py` | 58 passed (all dots, exit 0) | PASS |
| ruff check | `.venv/Scripts/ruff.exe check` on the phase source and test files | All checks passed | PASS |
| ruff format | `ruff format --check` on phase source | 13 files already formatted | PASS |
| mypy | `.venv/Scripts/python.exe -m mypy` on the 13 phase source files | Success: no issues found | PASS |


### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| APRV-01 | 08-02 | 12-field Telegram alert | SATISFIED | SC1 |
| APRV-02 | 08-01 | bound, idempotent, expiring approval | SATISFIED | SC2 |
| EXEC-02 | 08-04 | reconcile + sweeper + SAFE_MODE | SATISFIED (library); live proof is Human item 2 | SC3 |
| EXEC-03 | 08-03 | deterministic order IDs | SATISFIED | SC4 |
| OPS-01 | 08-05 | SAFE_MODE blocks entries; RUNBOOK drills | SATISFIED (harness); real-stack is Human item 3 | SC5 |

No orphaned requirements: REQUIREMENTS.md maps exactly APRV-01/02, EXEC-02/03, OPS-01 to Phase 8.

### Anti-Patterns Found

None. No TBD/FIXME/XXX in the phase source files. The 3 CRITICAL and 31 WARNING review findings in 08-REVIEW.md are all marked fixed in 08-REVIEW-FIX.md, and `tests/test_phase8_audit_reviewfix.py` carries a test per finding.

### Bookkeeping Warnings (non-blocking)

- ROADMAP.md Phase 8 detail still shows `**Plans**: 4/5 plans executed` and `- [ ] 08-05` although 08-05-SUMMARY.md exists, `tests/test_drills.py` passes, the phase list line is `[x]` and REQUIREMENTS marks OPS-01 complete. Tick 08-05 and set 5/5.
- 08-VALIDATION.md keeps `nyquist_compliant: false` (PARTIAL) for the two manual-only live checks above.
- 32 PostgreSQL-backed tests (`test_approval_replay_pg.py`, `test_persistence_approvals_pg.py`) did not run (no `TEST_DATABASE_URL`); they belong to Phase 17 persistence but touch the Phase 8 approval store.

### Human Verification Required

See the `human_verification` frontmatter: 1) live Telegram callback delivery, 2) live read-only Binance reconcile proof, 3) real-stack RUNBOOK drill rehearsal.

### Gaps Summary

No blocking gaps. The phase delivers its goal as tested library code with fakes: idempotent expiring bound approvals, deterministic order IDs, a cancel-only orphan sweeper, SAFE_MODE gating the execution manager, and an 8-drill harness. Runtime composition (scheduled reconciler loop, durable SAFE_MODE) is explicitly owned by Phases 20 and 24.

---

_Verified: 2026-10-03_
_Verifier: Claude (gsd-verifier)_

## Accepted by Operator (2026-10-04)

All 5 success criteria hold at library/fake level. The 32 PostgreSQL-gated tests that were skipped in the verifier run were re-run on 2026-10-04 against a live PostgreSQL 17 (`TEST_DATABASE_URL` set) and pass.

| Item | Decision |
|------|----------|
| Live Telegram callback check | Deferred to Phases 23/24 (Telegram approval hardening; live runtime composition). |
| Live read-only Binance reconcile | Deferred to Phases 20/24. A read-only mainnet key and a Demo Trading key were both confirmed to authenticate on 2026-10-04 (position mode one-way), but the adapter has no signed-request path yet, so the reconcile loop cannot run against the exchange. |
| Real-stack RUNBOOK drill rehearsal | Deferred to Phases 24/25 (demo rehearsal and demo integration campaign). |

The reconciler loop is not yet composed into a running process; Phases 20 and 24 own that.
