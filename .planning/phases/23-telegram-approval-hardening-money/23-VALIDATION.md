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
| TBD | | | | | | | ⬜ pending |

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
