---
phase: "15"
slug: "strategy-geometry-correction"
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-10-06"
---

# Phase 15 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Source: 15-RESEARCH.md "Validation Architecture".

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 (asyncio auto mode), `addopts = "-q"` |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]`; ruff line-length 100; mypy strict |
| **Quick run command** | `.venv/Scripts/python -m pytest tests/test_core_features.py tests/test_core_planner.py tests/test_core_strategy_breakout_retest.py tests/test_core_strategy_range_mr.py tests/test_core_tracer.py tests/test_no_lookahead.py tests/test_prefix_invariance.py tests/test_candle_close_timing.py tests/test_registry.py tests/test_registry_gate.py tests/test_decision_alignment_params.py tests/test_domain_enums.py tests/test_decision_alignment_bookkeeping.py -q -p no:cacheprovider` |
| **Full suite command** | `.venv/Scripts/python -m pytest tests -q -p no:cacheprovider` |
| **Static gates** | `.venv/Scripts/python -m ruff check src tests scripts`, `.venv/Scripts/python -m ruff format --check src tests scripts`, `.venv/Scripts/python -m mypy src` |
| **Estimated runtime** | quick ~65 s; wave merge ~6 min; full suite longer |

---

## Sampling Rate

- **After every task commit:** quick run command plus the task's new test file(s) (target under 90 s)
- **After every plan wave:** quick run plus `tests/test_backtest_simulator.py tests/test_backtest_experiment.py tests/test_backtest_determinism.py tests/test_backtest_engine_strategy.py tests/test_paper_parity.py tests/test_cost_parity.py tests/test_phase6_fixture_geometry.py`, ruff and mypy
- **Before `/gsd-verify-work`:** full suite green except documented local environment items (PG-dependent tests), ruff, mypy, smoke runs
- **Max feedback latency:** 90 seconds per task

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 15-xx-xx | TBD | TBD | STRAT-01 | — | pivot confirmed exactly at t+R, never earlier; evaluated bar excluded | unit, hand-derived | `pytest tests/test_core_pivots.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 15-xx-xx | TBD | TBD | STRAT-01 | — | pivot prefix-invariance | property | `pytest tests/test_core_pivots.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 15-xx-xx | TBD | TBD | STRAT-02 | — | SL outside entry zone else NO_TRADE; signal bar through SL invalidates; TP on loss side rejected | unit + property | `pytest tests/test_planner_geometry.py tests/test_geometry_property.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 15-xx-xx | TBD | TBD | STRAT-01 | — | B/C do not leak the evaluated bar; B retest anchored; B with-direction only; C regime from confirmed 4H pivots | unit | `pytest tests/test_core_strategy_breakout_retest.py tests/test_core_strategy_range_mr.py -q -p no:cacheprovider` | ✅ extend | ⬜ pending |
| 15-xx-xx | TBD | TBD | F-909 | — | rationale per key, hash-neutral; PLACEHOLDER refused at freeze | unit | `pytest tests/test_rationale.py tests/test_paper_freeze.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 15-xx-xx | TBD | TBD | F-113 | — | v6 sets pinned and registered, baselines re-issued as -v4 | unit | `pytest tests/test_decision_alignment_params.py tests/test_analytics_files.py -q -p no:cacheprovider` | ✅ extend | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_core_pivots.py`, `tests/test_core_strategy_geometry.py`, `tests/test_planner_geometry.py`, `tests/test_geometry_property.py`, `tests/test_rationale.py`
- [ ] `tests/fixtures/phase15/geometry_cases.json` and `DERIVATIONS.md` (hand-derived, independent arithmetic)
- [ ] `src/core/pivots.py`, `src/domain/rationale.py` added to `tests/test_domain_no_float.py` `SCANNED_FILES`
- [ ] line-ending fix for the Phase 6 generator comparison (research flag F12) before regenerating fixtures

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real-data smoke on the new sets (criterion 4) | STRAT-02 | slow (minutes), needs local data store | run `scripts/smoke_backtest_realdata.py` per RESEARCH section 7, twice, digests must match |
| User ratifies new parameter numbers | F-909 | money-relevant values | `checkpoint:decision` in the plan with worked examples at equity 500 and 1,000 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90 s per task
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
