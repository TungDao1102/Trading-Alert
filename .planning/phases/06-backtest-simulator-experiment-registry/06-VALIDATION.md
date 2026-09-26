---
phase: "06"
slug: "backtest-simulator-experiment-registry"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-09-26"
---

# Phase 06 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x (pytest-asyncio auto mode) |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/test_backtest_simulator.py tests/test_backtest_experiment.py tests/test_backtest_report.py -q` |
| **Full suite command** | `uv run pytest tests/ -q` |
| **Estimated runtime** | ~120 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_backtest_simulator.py tests/test_backtest_experiment.py tests/test_backtest_report.py -q`
- **After every plan wave:** Run `uv run pytest tests/ -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 300 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | BKTS-01 | — | N/A (deterministic simulator, no trust boundary) | unit | `uv run pytest tests/test_backtest_simulator.py -q` | ❌ W0 | ⬜ pending |
| 06-02-01 | 02 | 1 | BKTS-02 | — | N/A (file-canonical registry, no secrets) | unit | `uv run pytest tests/test_backtest_experiment.py -q` | ❌ W0 | ⬜ pending |
| 06-03-01 | 03 | 1 | BKTS-03 | — | N/A (report-only, no PII) | unit | `uv run pytest tests/test_backtest_report.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_backtest_simulator.py` — stubs for BKTS-01 (intrabar resolution, limit fills, costs-from-run-#1)
- [ ] `tests/test_backtest_experiment.py` — stubs for BKTS-02 (six-field identity, baselines, reproducibility)
- [ ] `tests/test_backtest_report.py` — stubs for BKTS-03 (slices, R distribution, bootstrap, plateau)
- [ ] `tests/fixtures/phase6/` — golden inputs (strategy candles + 1m intrabar incl. both-touched bars + parameters + costs)
- [ ] `tests/conftest.py` — shared fixtures (already exists — extend, do not duplicate)

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 300s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
