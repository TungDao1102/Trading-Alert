---
phase: "21"
slug: account-equity-daily-loss
status: validated
nyquist_compliant: false
wave_0_complete: true
created: "2026-10-25"
---

# Phase 21 — Validation Strategy

> Per-phase validation contract. Requirements: RISK-01, RISK-02, EXEC-01, OPS-02.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (asyncio_mode = auto) |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest -m "not docker" tests/test_phase21_composition.py tests/test_daily_stop.py tests/test_day_risk_service.py tests/test_day_risk_stream.py tests/test_live_risk_inputs.py -p no:xdist` |
| **Full suite command** | `uv run pytest -m "not docker" -n 4` (PG files need `TEST_DATABASE_URL` in the process environment) |
| **Estimated runtime** | quick ~20 s; full ~9-10 min |

---

## Sampling Rate

- **After every task commit:** the quick run command (own test files only).
- **After every plan wave:** the Phase 21 file list below.
- **Before verify-work:** full suite once per phase, run by the orchestrator.

---

## Per-Task Verification Map

| Plan | Requirement | Behavior | Test files (`tests/`) | Command | Status |
|------|-------------|----------|-----------------------|---------|--------|
| 21-01..21-04 | RISK-01 | Owner limits, equity bounds, cancel verification, fixtures | `test_execution_limits.py`, `test_cancel_verification.py`, `test_phase21_fixtures.py` | `uv run pytest -m "not docker" tests/test_execution_limits.py tests/test_cancel_verification.py tests/test_phase21_fixtures.py -p no:xdist` | green |
| 21-05..21-07 | RISK-01 | Account reads adapter, trades adapter, live equity (fresh, age-bound, no stale fallback) | `test_account_reads_adapter.py`, `test_account_trades_adapter.py`, `test_live_equity.py`, `test_account_equity_source.py`, `test_snapshot_live_equity.py` | `uv run pytest -m "not docker" tests/test_account_reads_adapter.py tests/test_account_trades_adapter.py tests/test_live_equity.py tests/test_account_equity_source.py tests/test_snapshot_live_equity.py -p no:xdist` | green |
| 21-08..21-10 | RISK-02 | Daily loss fold, recorded Demo frames, DAILY_STOP cancel-then-alert | `test_daily_loss.py`, `test_daily_loss_recorded.py`, `test_daily_stop.py` | `uv run pytest -m "not docker" tests/test_daily_loss.py tests/test_daily_loss_recorded.py tests/test_daily_stop.py -p no:xdist` | green |
| 21-09, 21-12 | RISK-02 | Day state and reservations persistence (PG) | `test_day_risk_pg.py`, `test_risk_reservations.py`, `test_risk_reservations_pg.py`, `test_risk_reservation_approval_pg.py`, `test_risk_reservation_margin_pg.py` | `uv run pytest tests/test_risk_reservations.py -p no:xdist` (PG files: set `TEST_DATABASE_URL`) | green (PG only with URL) |
| 21-11, 21-13..21-16 | RISK-02, EXEC-01 | Live risk inputs, parity, day-risk service, stream path | `test_live_risk_inputs.py`, `test_live_risk_parity.py`, `test_day_risk_service.py`, `test_day_risk_stream.py` | `uv run pytest -m "not docker" tests/test_live_risk_inputs.py tests/test_live_risk_parity.py tests/test_day_risk_service.py tests/test_day_risk_stream.py -p no:xdist` | green |
| 21-14..21-16 | EXEC-01 | Manager gates (incl. 5f3 equity comparison), phase gate | `test_phase21_gate.py`, `test_execution_manager.py::test_gate_5f3_refuses_a_sizing_equity_above_the_live_equity_the_guard_read` | `uv run pytest -m "not docker" tests/test_phase21_gate.py tests/test_execution_manager.py -p no:xdist` | green |
| review-fix | RISK-01, RISK-02 | WR-01..WR-09 and WR-05/D087 pins live inside the files above (day_risk_service, daily_stop WR-07, live_risk_inputs WR-04, phase21_gate WR-03) | same files | same commands | green |
| Nyquist | EXEC-01 SC1 | Equity source + day service -> `build_live_risk_inputs` -> `check_portfolio`: stale equity gives UNCERTAIN_ACCOUNT_STATE, a latched day gives DAILY_STOP_BLOCK, a normal day passes | `test_phase21_composition.py` | `uv run pytest -m "not docker" tests/test_phase21_composition.py -p no:xdist` | green (3 tests) |
| Nyquist | RISK-02 | Failed DAILY_STOP alert is reported in `alerts_failed` and not re-sent on the next call | `test_daily_stop.py::test_a_failed_daily_stop_alert_is_not_resent_on_the_next_call` | `uv run pytest tests/test_daily_stop.py -p no:xdist` | green (pins current behavior) |

*Status: green = ran in this audit (non-PG files); PG files skip without `TEST_DATABASE_URL`.*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| ACCOUNT_UPDATE / stream-gap -> `invalidate()` link | RISK-01, RISK-02 | The wiring does not exist in `src` yet (no caller of `invalidate`, no `account_sink=` composition); it is Phase 24 composition. Not invented here. Both `invalidate` methods are unit-tested; the parsed event type exists. | After Phase 24: feed a parsed `AccountUpdateEvent` and an after-gap item through the router and assert both `LiveEquitySource` and `LiveDayRiskService` go unknown. **ESCALATED to Phase 24.** |
| WR-10 OPERATOR_RELEASED | RISK-02 | Owner decision; needs a migration | Owner decides; then add a release reason and migration test. |
| D-22 label comments | RISK-01 | Cosmetic | Read review. |
| OPS-02 | OPS-02 | Owner attestation (D-21) | Owner confirms the item. |
| FUNDING_FEE row, mainnet realizedPnl, 429/418 behavior | RISK-02 | Exchange-only proofs; Demo cannot show them | Phase 25/26 observation. |
| Running-process composition | EXEC-01 | Phase 24/26 | Observe in the running paper/live process. |
| DAILY_STOP alert lost when the sink fails | RISK-02 | Observation, accepted: one-shot alert, no retry; caller must log `alerts_failed` | None; pinned by the test above. |

---

## Validation Sign-Off

- [x] All tasks have automated verify or a Manual-Only reason
- [x] Sampling continuity
- [x] Wave 0 covers all MISSING references (none)
- [x] No watch-mode flags
- [ ] `nyquist_compliant` stays false: gap 3 (ACCOUNT_UPDATE and stream gap to invalidate) is not wired in src until Phase 24

**Approval:** approved 2026-10-25

## Validation Audit 2026-10-25

| Metric | Count |
|---|---|
| Gaps found | 3 |
| Resolved | 2 |
| Escalated | 1 |
