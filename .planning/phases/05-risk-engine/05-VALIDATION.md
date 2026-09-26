---
phase: "05"
slug: "risk-engine"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
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
| 05-01-01 | 01 | 1 | RISK-01 | T-05-01 | Canonical sizing incl. modeled costs, Decimal-only | unit (TDD) | `uv run pytest tests/test_risk_sizing.py -x` | ✅ | ✅ green |
| 05-01-02 | 01 | 1 | RISK-01 | T-05-01 | Floor + utilization + min/notional gates, never round up | unit boundary (TDD) | `uv run pytest tests/test_risk_quantization.py -x` | ✅ | ✅ green |
| 05-01-03 | 01 | 1 | RISK-01 | T-05-02 | Byte-identical outputs incl. reason codes (CI-blocking parity) | golden fixture | `uv run pytest tests/test_risk_parity.py -x` | ✅ | ✅ green |
| 05-02-01 | 02 | 2 | RISK-02 | T-05-03 | Cluster → aggregate → count → daily gates, first-failure-wins | unit (TDD) | `uv run pytest tests/test_risk_portfolio.py -x` | ✅ | ✅ green |
| 05-02-02 | 02 | 2 | RISK-02 | T-05-03/04 | Fail-closed on uncertain/stale (equity None, unreconciled, missing/stale constraints) | unit negative (TDD) | `uv run pytest tests/test_risk_portfolio.py -x -k fail_closed` | ✅ | ✅ green |
| 05-0X-00 | 0X | X | RISK-01/02 | — | No `float(`/literal in `src/risk/`; mypy strict + Ruff clean | static gate | `uv run pytest tests/test_domain_no_float.py -x` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Task IDs are provisional — the planner assigns final IDs. Every plan task MUST carry an `<automated>` verify command from this map or a Wave 0 dependency.*

---

## Wave 0 Requirements

- [x] `src/risk/` package — sizing + quantization + portfolio + types + barrel (`__init__.py`)
- [x] `tests/test_risk_sizing.py`, `tests/test_risk_quantization.py`, `tests/test_risk_portfolio.py`, `tests/test_risk_parity.py`, `tests/test_domain_no_float.py` (note: no-float guard lives in `test_domain_no_float.py`, not `test_risk_no_float.py`)
- [x] `tests/fixtures/phase5/` golden files — 11 cases: happy-path long/short, utilization-reject edge, min-qty reject, notional reject, cluster/aggregate/max-positions rejects, daily-stop block, stale-constraints, uncertain-account
- [x] Registry extension — new risk keys in `STRATEGY_KEYS`/`INT_KEYS` + versioned `baseline-v2.toml` sets
- [x] Enum/GLOSSARY extension for D-05 reason codes (RejectionReason + DailyState promotion, GLOSSARY §9)
- [x] Framework install: none — pytest/Ruff/mypy already pinned

*Wave 0 installs nothing — existing infrastructure covers all phase requirements once stubs land.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| — | — | — | All phase behaviors have automated verification. |

*If none: "All phase behaviors have automated verification."*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 120s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** validated 2026-09-26 — retroactive audit, all 6 map rows green

## Validation Audit 2026-09-26
| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

Retroactive audit of the completed phase: all 6 Per-Task Map rows verified COVERED (test files exist, target the specified behavior, suite green — 81 passed exit 0 on the risk/domain/registry in-scope set). 11/11 parity goldens byte-exact. Review-fix hardening (CR-01 required side, CR-02 STALE_CONSTRAINTS default, prec-28 pinning, Decimal guards) pinned by tests per 05-REVIEW-FIX.md. One doc correction applied during audit: static-gate command path fixed from `tests/test_risk_no_float.py` to the actual `tests/test_domain_no_float.py`. No auditor spawn needed — no gaps to fill.
