---
phase: "12"
slug: "fee-cost-model-correctness"
status: complete
nyquist_compliant: true
wave_0_complete: true
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

| Plan / Task | Requirement | Behavior | Test Type | Automated Command | Status |
|-------------|-------------|----------|-----------|-------------------|--------|
| 12-01 / 1-2 | DOMN-02 | 20-code RejectionReason; retired aliases; GL gates | unit/gate | `pytest tests/test_domain_enums.py tests/test_decision_alignment_bookkeeping.py -q` | green |
| 12-02 / 1-3 | DOMN-02 | Registry unit guard, cost-guard keys, v5 sets pinned, gate PA-07 | gate | `pytest tests/test_registry.py tests/test_decision_alignment_params.py -q` | green |
| 12-03 / 1 | RISK-01 | Producer hand-derived BTC/XRP, linear scaling | unit | `pytest tests/test_cost_per_unit.py -q` | green |
| 12-03 / 2 | DOMN-02 | cost_model_hash canonicalization matrix, 8-key binding and freeze | unit | `pytest tests/test_cost_per_unit.py tests/test_backtest_experiment.py tests/test_backtest_binding.py tests/test_paper_freeze.py -q` | green |
| 12-04 / 1-2 | BKTS-01 | Phase 6 fixtures regenerated, guard geometry, determinism | golden | `pytest tests/test_phase6_fixture_geometry.py tests/test_backtest_experiment.py -q` | green |
| 12-05 / 1-2 | RISK-01 | max(param, account) per side; fail closed; adapter strict parsing | unit/adapter | `pytest tests/test_commission_rates.py tests/test_adapter_strictness.py -q` | green |
| 12-06 / 1-2 | RISK-01 | size_and_quantize; STOP_TOO_TIGHT / COST_TO_RISK_EXCEEDED boundaries | unit | `pytest tests/test_risk_cost_guards.py tests/test_risk_sizing.py tests/test_risk_quantization.py -q` | green |
| 12-07 / 1-3 | RISK-01 | Phase 5 fixtures and portfolio suite on the corrected contract | golden | `pytest tests/test_risk_parity.py tests/test_risk_portfolio.py -q` | green |
| 12-08 / 1-2 | RISK-01 | Live manager refuses non-account rates | unit | `pytest tests/test_execution_manager.py -q` | green |
| 12-09 / 1-3 | BKTS-01 | `_apply_costs` price x qty x rate oracle; simulator and paper parity | unit/golden | `pytest tests/test_backtest_simulator.py tests/test_paper_parity.py tests/test_paper_closed_candle.py -q` | green |
| 12-10 / 1-3 | RISK-01 | SL loss <= allowed_risk grid; old formula fails (mutation); cost parity | property/parity | `pytest tests/test_sl_loss_property.py tests/test_cost_parity.py -q` | green |
| 12-11 / 1-3 | DOMN-02 | D046-D048 recorded; DC-02 minimum 48; docs amended | gate | `pytest tests/test_decision_alignment_bookkeeping.py -q` and `python scripts/verify_decision_alignment.py all` | green |

*Oracle rule: expected values are hard-coded literals or explicit arithmetic, never computed by the code under test.*

---

## Wave 0 Requirements

- [x] `tests/test_cost_per_unit.py`
- [x] `tests/test_sl_loss_property.py`
- [x] `tests/test_risk_cost_guards.py`
- [x] `tests/test_commission_rates.py`
- [x] `tests/test_cost_parity.py`

---

## Manual-Only Verifications

All phase behaviors have automated verification. (Binance Demo behavior of `commissionRate` is deferred to Phase 24.)

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 190s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** complete (2026-09-30). Final regression: `pytest -q` exit 0; `verify_decision_alignment.py all` ALL_PASS; ruff and mypy report only findings in files this phase did not touch (recorded in 12-11-SUMMARY.md).
