---
phase: "23"
slug: "telegram-approval-hardening-money"
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-10-25"
---

# Phase 23 — Validation Strategy

> Source of truth: the "Validation Architecture" section of `23-RESEARCH.md` (requirement-to-test map, Wave 0 gaps, pinning SHADOW tests). Plans copy their `<automated>` commands from it.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (`asyncio_mode = "auto"`), pytest-xdist in the dev extra |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/test_paper_shadow_confirm.py tests/test_paper_shadow_buttons.py tests/test_paper_shadow_messages.py tests/test_paper_shadow_telegram_failures.py tests/test_approval_message.py tests/test_alerts.py -x -q` |
| **Full suite command** | `uv run pytest -m "not docker" -n 4` (orchestrator, once per phase) |
| **Estimated runtime** | quick ~60 s; full ~9-10 min |

## Sampling Rate

- **After every task commit:** the quick command for the touched area plus `uv run ruff check <files>`
- **After every plan wave:** the SHADOW set and, for persistence waves, the `*_pg.py` files with `TEST_DATABASE_URL`
- **Before `/gsd-verify-work`:** full suite green, `uv run python scripts/verify_decision_alignment.py all`
- **Max feedback latency:** 120 s

## Per-Task Verification Map

Filled by the planner from the research map (APRV-01, APRV-02, PAPER-02; decisions D-01..D-17).

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 23-01-T1 | 23-01 | 1 | APRV-02 (D-01, D-03, D-15) | unit (gate + on_callback + dispatch) | `uv run pytest -m "not docker" tests/test_telegram_authorization.py -x` | NEW | ⬜ pending |
| 23-01-T2 | 23-01 | 1 | APRV-02 (D-02) | unit (callers restored, store-failure code) | `uv run pytest -m "not docker" tests/test_journal_ids.py tests/test_phase8_audit_reviewfix.py tests/test_demo_rehearsal_flow.py tests/test_paper_shadow_buttons.py tests/test_paper_shadow_confirm.py tests/test_paper_shadow_telegram_failures.py tests/test_telegram_authorization.py -x` | exists | ⬜ pending |
| 23-01-T3 | 23-01 | 1 | APRV-02 (D-02) | unit (env, runtime, wiring) | `uv run pytest -m "not docker" tests/test_paper_runtime_env.py tests/test_env_example.py tests/test_paper_shadow_runtime.py tests/test_demo_rehearsal_safety.py -x` | exists | ⬜ pending |
| 23-02-T1/T2 | 23-02 | 1 | APRV-01 (D-13) | unit (independent recomputation) | `uv run pytest -m "not docker" tests/test_money_at_stake.py tests/test_domain_no_float.py -x` | NEW | ⬜ pending |
| 23-03-T1/T2 | 23-03 | 1 | APRV-01 (D-14) | unit + golden | `uv run pytest -m "not docker" tests/test_alert_wording.py tests/test_alerts.py tests/test_phase23_fixtures.py -x` | NEW | ⬜ pending |
| 23-04-T1/T2 | 23-04 | 1 | PAPER-02, APRV-01 (D-03, D-13) | PG + migration | `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_persistence_approvals_pg.py tests/test_persistence_migration_pg.py -x` | exists; extend | ⬜ pending |
| 23-05-T1/T2 | 23-05 | 1 | APRV-02 (D-11, D-12) | unit | `uv run pytest -m "not docker" tests/test_confirm_recheck.py tests/test_prior_outcome_reply.py -x` | NEW | ⬜ pending |
| 23-06-T1 | 23-06 | 2 | APRV-02 (D-09) | unit (SHADOW set unedited) | `uv run pytest -m "not docker" tests/test_confirm_core.py tests/test_paper_shadow_confirm.py tests/test_paper_shadow_isolation.py tests/test_paper_shadow_lock_order.py -x` | NEW + exists | ⬜ pending |
| 23-06-T2/T3 | 23-06 | 2 | APRV-02 (D-10, D-16 P16R-02) | unit | `uv run pytest -m "not docker" tests/test_confirm_core.py -x` | NEW | ⬜ pending |
| 23-07-T1..T3 | 23-07 | 2 | APRV-02 (D-06, D-07, D-08) | unit with FakeBot | `uv run pytest -m "not docker" tests/test_telegram_decided_message.py tests/test_telegram_error_handler.py -x` | NEW | ⬜ pending |
| 23-08-T1/T2 | 23-08 | 3 | PAPER-02 (D-16 G4-042) | PG + migration | `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_persistence_constraints_pg.py tests/test_persistence_approvals_pg.py tests/test_persistence_migration_pg.py -x` | exists; extend | ⬜ pending |
| 23-08-T3 | 23-08 | 3 | PAPER-02 (O-2) | owner checkpoint | blocking-human decision, answer recorded in 23-08-SUMMARY.md | n/a | ⬜ pending |
| 23-09-T1..T3 | 23-09 | 3 | APRV-01 (D-05, D-13, D-14) | unit + golden | `uv run pytest -m "not docker" tests/test_approval_message.py tests/test_paper_notify.py tests/test_phase23_fixtures.py tests/test_paper_shadow_messages.py -x` | exists; extend | ⬜ pending |
| 23-10-T1/T2 | 23-10 | 3 | APRV-02 (D-06, D-08) | unit (SHADOW) | `uv run pytest -m "not docker" tests/test_paper_shadow_decided_message.py tests/test_paper_shadow_runtime.py -x` | NEW | ⬜ pending |
| 23-11-T1..T3 | 23-11 | 4 | APRV-01, APRV-02, PAPER-02 (D-05, D-07, D-12) | unit with fakes | `uv run pytest -m "not docker" tests/test_approval_desk.py tests/test_demo_rehearsal_flow.py -x` | NEW + exists | ⬜ pending |
| 23-12-T1..T3 | 23-12 | 5 | APRV-02 (D-09, D-10, D-11, criterion 3/4) | unit through on_callback + golden | `uv run pytest -m "not docker" tests/test_confirm_flow.py tests/test_phase23_fixtures.py -x` | NEW | ⬜ pending |
| 23-13-T1..T3 | 23-13 | 6 | all (D-04, D-15, D-17) | gate + docs | `uv run pytest -m "not docker" tests/test_phase23_gate.py -x` and `uv run python scripts/verify_decision_alignment.py all` | NEW | ⬜ pending |

## Wave 0 Requirements

- [ ] `tests/test_telegram_authorization.py`, `tests/test_telegram_decided_message.py`, `tests/test_telegram_error_handler.py`, `tests/test_confirm_core.py`, `tests/test_prior_outcome_reply.py`, `tests/test_money_at_stake.py`, `tests/test_alert_wording.py`, `tests/test_phase23_gate.py`
- [ ] `tests/shadow_fakes.py`: `chat_type="private"`, mode-parametrized `FakeBot`, user-id allow-list constant
- [ ] `scripts/gen_phase23_fixtures.py` + `tests/fixtures/phase23/` (golden texts generated, never hand-typed)
- [ ] migration-head pins updated (`test_phase21_gate.py`, `test_phase22_gate.py`, `test_persistence_migration_pg.py`)

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Empty `reply_markup` removes the live keyboard (research A1) | APRV-02 | needs a real Telegram bot | owner-run live check, registered for Phase 24/25 |
| Tap from a second account / group is rejected live (G2-014) | APRV-02 | needs a second account | owner-run, Phase 24/25 |

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] No 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
