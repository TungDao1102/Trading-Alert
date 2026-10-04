---
phase: 05-risk-engine
verified: 2026-10-03T12:00:00Z
status: passed
score: 3/3 must-haves verified
covered_files:
  - .planning/phases/05-risk-engine/05-01-PLAN.md
  - .planning/phases/05-risk-engine/05-01-SUMMARY.md
  - .planning/phases/05-risk-engine/05-02-PLAN.md
  - .planning/phases/05-risk-engine/05-02-SUMMARY.md
  - src/risk/__init__.py
  - src/risk/cost_guards.py
  - src/risk/cost_rates.py
  - src/risk/gating.py
  - src/risk/live_commission.py
  - src/risk/portfolio.py
  - src/risk/quantization.py
  - src/risk/sizing.py
  - src/risk/types.py
  - tests/test_cost_parity.py
  - tests/test_domain_no_float.py
  - tests/test_paper_parity.py
  - tests/test_risk_cost_guards.py
  - tests/test_risk_parity.py
  - tests/test_risk_portfolio.py
  - tests/test_risk_quantization.py
  - tests/test_risk_sizing.py
  - tests/test_sl_loss_property.py
covered_digest: "v2:sha256:894456f25a292279b293849ef92e1ab3bdd72a318470e1f961ea3f9e2dd1d879"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: passed
  previous_score: 3/3
  gaps_closed:
    - "Advisory A1: candidate side was hardcoded LONG in evaluate_risk (now a required, validated Direction argument)"
    - "Advisory A2: no structlog lineage in quantize() (now emitted via quantization._emit_lineage; risk.cost_rates / risk.cost_guard events added in gating)"
    - "Advisory A3: non-positive equity contract documented in evaluate_risk docstring and pinned by test (WR-09)"
    - "Advisory A4: portfolio expected.json now asserted (test_portfolio_case_matches_expected_json)"
  gaps_remaining: []
  regressions: []
---

# Phase 5: Risk Engine Verification Report

**Phase Goal:** Risk math is byte-identical everywhere — no sizing surprise appears for the first time with money attached.
**Verified:** 2026-10-03T12:00:00Z
**Status:** passed
**Re-verification:** Yes — fresh re-verification against the current repo. Phases 9, 11 and 12 legitimately changed `src/risk/` (cost model, adverse-edge sizing, cost guards, live commission resolver); the Phase 5 goal was judged against the code as it stands now, not against the 2026-09-25 snapshot.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC1 | Position size derives from equity × risk-rate ÷ SL-distance including modeled costs, floors quantity to stepSize, rejects below utilization/minimums (QUANTIZATION_REJECT / NO_TRADE preferred over round-up) | ✓ VERIFIED | `src/risk/gating.py:size_and_quantize` computes cost per unit from `CostRates` (`per_unit_round_trip_cost`), sizes via `sizing.size_position` (equity × risk_rate ÷ (SL distance + costs)), runs STOP_TOO_TIGHT / COST_TO_RISK_EXCEEDED guards, then `quantization.quantize` (floor to stepSize, min-qty, min-notional, realized-risk utilization gate; no round-up path). Malformed geometry and zero SL distance fail closed to EXCHANGE_CONSTRAINT NO_TRADE. The Phase 12 adverse-zone-edge sizing supersedes the Phase 5 zone-mid entry; this is a strengthening (loss at stop ≤ allowed_risk anywhere in the zone) and the SC wording still holds. Tests green (below). |
| SC2 | Portfolio limits (max positions, aggregate risk, cluster cap, DAILY_STOP) enforced; uncertain account/risk state fails closed to NO_TRADE with no new orders | ✓ VERIFIED | `src/risk/portfolio.py:check_portfolio` fixed-order gates; `evaluate_risk` passes upstream NO_TRADE through with its reason preserved. Live placement `src/execution/gates.py` calls the same `check_portfolio` and `src/execution/manager.py` additionally requires verified live commission rates (`_live_cost_rates_are_verified`) and returns UNCERTAIN_ACCOUNT_STATE otherwise. 6 portfolio fixtures now asserted against `expected.json`. |
| SC3 | Backtest, paper, and live produce identical sizing outputs for identical inputs (parity fixture green) | ✓ VERIFIED | One shared entry point: `src/backtest/simulator.py:841`, `src/paper/loop.py:512` and `src/execution/manager.py:577` all call `src.risk.gating.evaluate_risk` with the same keyword contract (cost rates via `cost_rates_from_model`, guard rates via `guard_rates_from_params`). No mode branches in `src/risk/` (grep of mode/backtest/paper/live returns docstrings and the `modeled_costs_per_unit` name only). `tests/test_risk_parity.py`, `tests/test_cost_parity.py`, `tests/test_paper_parity.py` green. |

**Score:** 3/3 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/risk/sizing.py` | canonical formula | ✓ VERIFIED | Decimal-only, 103 lines |
| `src/risk/quantization.py` | floor + reject gates + lineage | ✓ VERIFIED | `_emit_lineage` present |
| `src/risk/portfolio.py` | portfolio gates + fail-closed + `derive_daily_state` | ✓ VERIFIED | Consumed by `evaluate_risk` and `execution/gates.py` |
| `src/risk/gating.py` | single pipeline for all modes | ✓ VERIFIED | `size_and_quantize`, `evaluate_risk`; wired from simulator, paper loop, execution manager |
| `src/risk/cost_rates.py`, `cost_guards.py`, `live_commission.py` | Phase 12 additions feeding the pipeline | ✓ VERIFIED | Wired in gating / manager; covered by `test_risk_cost_guards.py`, `test_cost_parity.py` |
| `src/risk/types.py` | frozen Decimal/UTC-guarded envelopes | ✓ VERIFIED | `SizedResult` carries cost trail |
| `tests/fixtures/phase5/*` | 11 golden cases | ✓ VERIFIED | 11 dirs present with `input.json` + `expected.json` |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| backtest simulator | `evaluate_risk` | direct call | WIRED | `simulator.py:841` |
| paper loop | `evaluate_risk` | direct call | WIRED | `paper/loop.py:512` |
| execution manager (live) | `evaluate_risk` | `evaluate_risk(**risk_kwargs)` | WIRED | `manager.py:577`; `gates.py` reuses `check_portfolio` |
| gating | cost_rates / cost_guards / quantize / check_portfolio | fixed-order pipeline | WIRED | Confirmed in source |

### Data-Flow Trace (Level 4)

N/A — pure in-process Decimal math; exchange metadata and account state arrive as frozen input structs.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Risk + parity + cost + property tests | `pytest tests/test_risk_sizing.py test_risk_quantization.py test_risk_portfolio.py test_risk_parity.py test_risk_cost_guards.py test_cost_parity.py test_paper_parity.py test_sl_loss_property.py test_execution_gates.py test_domain_no_float.py test_registry.py` (.venv, offline) | `293 passed in 37.20s` | ✓ PASS |
| Lint | `ruff check src/risk tests/test_risk_*.py` | All checks passed | ✓ PASS |
| Types | `mypy src/risk` | Success: no issues found in 9 source files | ✓ PASS |
| Purity | grep `float(` / third-party imports in `src/risk` | none (structlog only via local lineage imports) | ✓ PASS |
| Debt markers | grep TBD/FIXME/XXX/TODO in `src/risk` | none | ✓ PASS |

### Probe Execution

Step 7c: SKIPPED — no probes declared by Phase 5 plans.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| RISK-01 | 05-01 | Sizing with costs, floor to stepSize, reject below utilization/minimums, identical everywhere | ✓ SATISFIED | SC1 + SC3 |
| RISK-02 | 05-02 | Portfolio limits + DAILY_STOP, fail closed on uncertain state | ✓ SATISFIED | SC2 |

No orphaned requirements.

### Anti-Patterns Found

None blocking. The four prior advisories (A1–A4) are closed (see `re_verification.gaps_closed`).

### Human Verification Required

None.

### Gaps Summary

No gaps. The Phase 5 goal still holds after the Phase 9, 11 and 12 changes: one branch-free `evaluate_risk` pipeline is the sole sizing/quantization/portfolio path used by backtest, paper and live, with parity tests green. Note for ROADMAP hygiene: the Phase 5 checkbox in the ROADMAP phase list is still `[ ]` although both plans are `[x]`; this report does not edit the roadmap.

---

_Verified: 2026-10-03T12:00:00Z_
_Verifier: Claude (gsd-verifier)_
