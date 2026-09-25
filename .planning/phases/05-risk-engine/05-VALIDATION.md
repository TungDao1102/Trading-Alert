---
phase: "05"
slug: "risk-engine"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-09-25"
---

# Phase 05 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest>=9, `asyncio_mode = "auto"` |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `uv run pytest tests/test_risk_*.py -x` |
| **Full suite command** | `uv run pytest tests/ -x` |
| **Estimated runtime** | ~120 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_risk_*.py -x`
- **After every plan wave:** Run `uv run pytest tests/ -x`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | RISK-01 | T-05-01 | Canonical sizing incl. modeled costs, Decimal-only | unit (TDD) | `uv run pytest tests/test_risk_sizing.py -x` | ❌ W0 | ⬜ pending |
| 05-01-02 | 01 | 1 | RISK-01 | T-05-01 | Floor + utilization + min/notional gates, never round up | unit boundary (TDD) | `uv run pytest tests/test_risk_quantization.py -x` | ❌ W0 | ⬜ pending |
| 05-01-03 | 01 | 1 | RISK-01 | T-05-02 | Byte-identical outputs incl. reason codes (CI-blocking parity) | golden fixture | `uv run pytest tests/test_risk_parity.py -x` | ❌ W0 | ⬜ pending |
| 05-02-01 | 02 | 2 | RISK-02 | T-05-03 | Cluster → aggregate → count → daily gates, first-failure-wins | unit (TDD) | `uv run pytest tests/test_risk_portfolio.py -x` | ❌ W0 | ⬜ pending |
| 05-02-02 | 02 | 2 | RISK-02 | T-05-03/04 | Fail-closed on uncertain/stale (equity None, unreconciled, missing/stale constraints) | unit negative (TDD) | `uv run pytest tests/test_risk_portfolio.py -x -k fail_closed` | ❌ W0 | ⬜ pending |
| 05-0X-00 | 0X | X | RISK-01/02 | — | No `float(`/literal in `src/risk/`; mypy strict + Ruff clean | static gate | `uv run pytest tests/test_risk_no_float.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Task IDs are provisional — the planner assigns final IDs. Every plan task MUST carry an `<automated>` verify command from this map or a Wave 0 dependency.*

---

## Wave 0 Requirements

- [ ] `src/risk/` package — sizing + quantization + portfolio + types + barrel (`__init__.py`)
- [ ] `tests/test_risk_sizing.py`, `tests/test_risk_quantization.py`, `tests/test_risk_portfolio.py`, `tests/test_risk_parity.py`, `tests/test_risk_no_float.py`
- [ ] `tests/fixtures/phase5/` golden files — at minimum: happy-path sizing, utilization-reject edge, min-qty reject, notional reject, each portfolio gate, stale-constraints, uncertain-account, nonzero-cost case
- [ ] Registry extension — new risk keys in `STRATEGY_KEYS`/`INT_KEYS` + versioned TOML sets
- [ ] Enum/GLOSSARY extension for D-05 reason codes (or mapped-constants decision)
- [ ] Framework install: none — pytest/Ruff/mypy already pinned

*Wave 0 installs nothing — existing infrastructure covers all phase requirements once stubs land.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| — | — | — | All phase behaviors have automated verification. |

*If none: "All phase behaviors have automated verification."*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
