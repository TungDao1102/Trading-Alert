---
phase: "12"
slug: "fee-cost-model-correctness"
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-09-30"
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Source: `12-RESEARCH.md` § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9, pytest-asyncio auto mode |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `.venv/Scripts/python -m pytest tests/test_risk_sizing.py tests/test_risk_quantization.py tests/test_risk_parity.py tests/test_risk_portfolio.py tests/test_backtest_simulator.py tests/test_registry.py tests/test_domain_enums.py -q` |
| **Full suite command** | `.venv/Scripts/python -m pytest -q` (+ `.venv/Scripts/python scripts/verify_decision_alignment.py`, `ruff check src tests scripts`, `mypy src`) |
| **Estimated runtime** | ~190 seconds (full), tens of seconds (quick) |

---

## Sampling Rate

- **After every task commit:** Run the quick run command
- **After every plan wave:** Run the full suite plus `scripts/verify_decision_alignment.py`
- **Before `/gsd-verify-work`:** Full suite, gates, ruff and mypy green
- **Max feedback latency:** 190 seconds

---

## Per-Task Verification Map

| Requirement | Behavior | Test Type | Automated Command | File Exists |
|-------------|----------|-----------|-------------------|-------------|
| RISK-01 | Producer hand-derived BTC/XRP, linear scaling | unit | `pytest tests/test_cost_per_unit.py -x` | ❌ W0 |
| RISK-01 | SL loss <= allowed_risk grid; old formula fails (mutation) | property | `pytest tests/test_sl_loss_property.py -x` | ❌ W0 |
| RISK-01 | STOP_TOO_TIGHT / COST_TO_RISK_EXCEEDED boundaries | unit | `pytest tests/test_risk_cost_guards.py -x` | ❌ W0 |
| RISK-01 | Cost parity across producer, evaluate_risk, simulator, paper | parity | `pytest tests/test_cost_parity.py -x` | ❌ W0 |
| RISK-01 | max(param, account) per side; fail closed, never zero | unit | `pytest tests/test_commission_rates.py -x` | ❌ W0 |
| RISK-01 | Adapter parses commission response strictly | adapter | `pytest tests/test_adapter_strictness.py -x` | ✅ extend |
| BKTS-01 | `_apply_costs` price × qty × rate oracle | unit | `pytest tests/test_backtest_simulator.py -x` | ✅ modify |
| BKTS-01 | Regenerated fixtures yield trades, pinned digests | golden | `pytest tests/test_backtest_simulator.py tests/test_paper_parity.py tests/test_paper_closed_candle.py -x` | ✅ regenerate |
| DOMN-02 | Old sets locked; v5 sets pinned with four keys | gate | `pytest tests/test_decision_alignment_params.py -x` | ✅ extend |
| DOMN-02 | Loader rejects rate > 0.01 | unit | `pytest tests/test_registry.py -x` | ✅ extend |
| DOMN-02 | cost_model_hash canonicalization matrix | unit | `pytest tests/test_backtest_experiment.py tests/test_backtest_binding.py tests/test_registry.py -x` | ✅ rewrite |
| D-09 | Enum equals GLOSSARY §9.1; GL gates green | unit/gate | `pytest tests/test_domain_enums.py tests/test_decision_alignment_bookkeeping.py -x` | ✅ modify |

*Oracle rule: expected values are hard-coded literals or explicit arithmetic, never computed by the code under test.*

---

## Wave 0 Requirements

- [ ] `tests/test_cost_per_unit.py`
- [ ] `tests/test_sl_loss_property.py`
- [ ] `tests/test_risk_cost_guards.py`
- [ ] `tests/test_commission_rates.py`
- [ ] `tests/test_cost_parity.py`

---

## Manual-Only Verifications

All phase behaviors have automated verification. (Binance Demo behavior of `commissionRate` is deferred to Phase 24.)

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 190s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
