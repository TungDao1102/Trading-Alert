---
phase: 06-backtest-simulator-experiment-registry
verified: 2026-10-04T00:00:00Z
status: passed
score: 21/22 must-haves verified (1 deferred to Phase 14)
covered_files: [".planning/phases/06-backtest-simulator-experiment-registry/06-01-PLAN.md", ".planning/phases/06-backtest-simulator-experiment-registry/06-01-SUMMARY.md", ".planning/phases/06-backtest-simulator-experiment-registry/06-02-PLAN.md", ".planning/phases/06-backtest-simulator-experiment-registry/06-02-SUMMARY.md", ".planning/phases/06-backtest-simulator-experiment-registry/06-03-PLAN.md", ".planning/phases/06-backtest-simulator-experiment-registry/06-03-SUMMARY.md", "src/backtest/__init__.py", "src/backtest/binding.py", "src/backtest/costs.py", "src/backtest/experiment.py", "src/backtest/report.py", "src/backtest/simulator.py", "src/domain/registry.py", "tests/test_backtest_binding.py", "tests/test_backtest_experiment.py", "tests/test_backtest_report.py", "tests/test_backtest_simulator.py", "tests/test_domain_no_float.py"]
covered_digest: "v2:sha256:08581c832976a4d9037480039eb70ca97218f32e1c33ac69d2b968be05e9f660"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 19/22
  gaps_closed:
    - "G1 reproduce/verify tautology (CR-03) - closed by 06-REVIEW-FIX commit 9e582d7"
    - "G2 empty-intrabar IndexError (CR-01) - closed by commit 488bcd0"
    - "G4 wall-clock default in report digest (CR-08) - closed by commit c50b295"
  gaps_remaining: []
  regressions: []
deferred:
  - truth: "Limit expiry resolves against the bar being replayed, not one global fixture clock (prior gap G3 / CR-04)"
    addressed_in: "Phase 14"
    evidence: "Phase 14 goal: 'A plan created at the close of bar N can fill only from bar N+1, until expiry ... Positions carry across bars' (Backtest Simulator Causality Rewrite, claims BKTS-01/BKTS-02, declares all earlier backtest evidence void). Phase 14 has 0 plans so far."
---

# Phase 06: Backtest Simulator + Experiment Registry Verification Report

> VOID (Phase 14, D052): this report verified the v1 simulator (it examined the signal bar, filled at a touch, booked a single-exit TP1, ignored funding and the portfolio ledger). Protocol v2.0.0 declares all earlier backtest evidence void; BKTS-01, BKTS-02 and DOMN-03 are re-verified against the v2 engine in Phase 14. The text below is kept unchanged as history and must not be read as current evidence.

**Phase Goal:** Backtest is the canonical validation authority - selection decisions rest on costs-included, uncertainty-first evidence.
**Verified:** 2026-10-04
**Status:** passed (one prior gap deferred to Phase 14, see below)
**Re-verification:** Yes - after review-fix commits and later phases 7.1, 12, 17-05

> The 2026-09-26 report was written before the 06-REVIEW-FIX commits and before
> Phase 12 (cost model rewrite), 7.1 (registry/cost binding), and 13. Every
> recorded gap was re-checked against current code, not against SUMMARY text.

> **MVP-mode note:** ROADMAP marks Phase 6 `mode: mvp`, but the goal is not a
> User Story, so a User-Flow Coverage table is not produced; standard
> goal-backward verification was used. Goal repair is tracked outside this report.

## Prior Gap Disposition

| Gap | Prior truth | Current state | Evidence |
|-----|-------------|---------------|----------|
| G1 (CR-03) | Re-run of recorded tuple is byte-identical | CLOSED | `experiment.py`: `_check_inputs_bind_record` (l.321) checks parameter_set_id, strategy_version, parameter_set_hash, cost_model_hash against the record and raises on mismatch; `reproduce` (l.354) calls it; typed rebuild of Decimal/datetime at l.309-318; `verify_experiment` (l.397) compares against `_stored_trades_digest(record)` (l.379). Tests `test_cr03a/b/c` pass (commit 9e582d7) |
| G2 (CR-01) | Missing 1m coverage fails closed SL-first | CLOSED | `simulator.py:219` `if intrabar is None or len(intrabar) == 0`; `test_cr01_empty_intrabar_list_resolves_sl_first_fallback` covers `[]` and `None` (commit 488bcd0) |
| G3 (CR-04) | Limit expiry resolved against replayed bar | STILL OPEN IN CODE, DEFERRED to Phase 14 | `simulator.py:758` `_entry_now_utc = now_utc` (fixture clock) passed to `_resolve_entry` at l.881 while `evaluate_risk` gets `bar.close_time_utc` (l.848). Confirmed by code reading, not by a new multi-bar run. Phase 14 rewrites the entry/expiry machine (fills only from bar N+1 until expiry, multi-bar holding, evidence declared void) and claims BKTS-01; it has no plans yet |
| G4 (CR-08) | Seeded report digest reproducible on default path | CLOSED | `report.py:569` `built_at_utc` is a required parameter, validated UTC-aware (l.584); no `datetime.now` anywhere in report.py. `test_cr08_build_requires_explicit_built_at_utc` passes (commit c50b295) |

Superseded/related by later phases (informational, previously warnings): WR-03 funding/slippage hashed-but-unread was addressed for fees and per-leg slippage by Phase 12 (commits b25519d, 2c13b87, fe830d6); funding modeling and TP1/TP2 ladder (WR-02) are explicit Phase 14 success criteria. CR-06, CR-07, CR-09, CR-11, WR-05, WR-06 have regression tests in the current suites (`test_cr06/07/09/11`, `test_wr05/06`).

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 01-1 | Both-touched bar resolves via 1m, SL before TP, LONG+SHORT | VERIFIED | fixtures `intrabar_both_touched[_short]`; simulator tests pass |
| 01-2 | Missing 1m coverage gives SL-first + fallback_applied + coverage_note (None and []) | VERIFIED | G2 closed; CR-01 test |
| 01-3 | Costs from run #1 via modeled costs + realized PnL, no cost-free path | VERIFIED | Phase 12 shared cost path (`cost_rates_from_model`, price-aware per-unit costs); `test_cost_parity.py`, `test_cost_per_unit.py` pass |
| 01-4 | Quantization/realized-risk rejects are first-class records | VERIFIED | reject-record path; simulator tests |
| 01-5 | Exact-threshold inputs pass | VERIFIED | delegates to `evaluate_risk`; `test_risk_parity.py` passes |
| 01-6 | Decimal-only, no float in src/backtest | VERIFIED | `test_domain_no_float.py` lists all six src/backtest files (incl. binding.py) and passes |
| 01-7 | Sorted bar iteration, run-twice identical | VERIFIED | determinism tests pass |
| 01-8 | No 1m leakage across decision boundary | VERIFIED | simulator test passes |
| 01-9 | Limit fills/partials/expiry/invalidation modeled; expiry per replayed bar | DEFERRED (Phase 14) | fixture cases (`limit_expiry`, `limit_partial_fill`, `invalidation_cancels_entry`) pass; per-bar expiry clock defect G3 deferred |
| 02-1 | Six identity fields + parameterSetId; missing field raises | VERIFIED | experiment tests |
| 02-2 | Re-run of recorded tuple is byte-identical via digest | VERIFIED | G1 closed |
| 02-3 | Unregistered/mutated sets fail closed | VERIFIED | registry + experiment tests; Phase 7.1 binding (`binding.py`, `test_backtest_binding.py`) pass |
| 02-4 | Empty input gives valid zero-trade record | VERIFIED | test passes |
| 02-5 | No-trade and simple-trend baselines via same engine | VERIFIED | baseline tests; CR-07/CR-11 enforcement tests |
| 02-6 | Trailing-precision discipline for cost hash | VERIFIED | `test_cost_model_hash_precision_discipline`, `test_cr05` |
| 03-1..03-8 | Nine report sections, seeded bootstrap with SE, plateau, dual-universe, <2 trades, zero-R, stable ordering, no float | VERIFIED | `test_backtest_report.py` all pass incl. pinned digest, seed stability, CR-08, CR-12, WR-05/06/10 |

### Roadmap Success-Criteria Rollup

| SC | Status | Basis |
|----|--------|-------|
| SC1 | VERIFIED with deferred caveat | mechanism, fixtures and costs green; multi-bar expiry clock (G3) deferred to Phase 14 rewrite |
| SC2 | VERIFIED | reproduce/verify now record-bound and digest-checked; baselines on shared simulator |
| SC3 | VERIFIED | nine-section report pinned; no winner-selection code in src/backtest |

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|--------------|----------|
| 1 | Per-bar limit-expiry clock in simulator (old G3/CR-04) | Phase 14 | Goal: fills only from bar N+1 until expiry, multi-bar holding, earlier evidence void; 0 plans yet |

### Behavioral Spot-Checks (run 2026-10-04, offline, .venv)

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Simulator/experiment/report/binding | `pytest tests/test_backtest_{simulator,experiment,report,binding}.py` | 108 passed | PASS |
| Plus no-float, cost parity, cost per-unit, paper parity, risk parity | same + `test_domain_no_float.py test_cost_parity.py test_cost_per_unit.py test_paper_parity.py test_risk_parity.py` | 234 passed | PASS |
| Lint | `ruff check src/backtest` / `ruff format --check src/backtest` | clean / 6 files formatted | PASS |
| Types | `mypy src/backtest` | no issues in 6 files | PASS |

TEST_DATABASE_URL was not set; no PostgreSQL-backed tests were run (none are needed by these suites).

### Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| BKTS-01 | SATISFIED for Phase 6 scope | intrabar + costs + limit machine green; per-bar expiry clock deferred to Phase 14 (which re-claims BKTS-01) |
| BKTS-02 | SATISFIED | reproducibility tripwire now real (G1 closed) |
| BKTS-03 | SATISFIED | G4 closed; report suite green |

No orphaned requirements.

### Anti-Patterns Found

Debt-marker scan (`TBD|FIXME|XXX|TODO|HACK`) over src/backtest: no hits. Remaining warnings (non-blocking, owned by Phase 14): funding not modeled, TP2 not resolved, expiry clock (G3), and same-bar fill causality, all of which the Phase 14 rewrite covers.

### Human Verification Required

None.

### Gaps Summary

No open gaps in Phase 6 scope. Three of four prior gaps are closed by 06-REVIEW-FIX commits with regression tests. G3 (single fixture clock for the entry-expiry gate) remains in the code at `simulator.py:758/881`; it is deferred, not fixed, because Phase 14 rewrites the same entry/expiry machine and declares earlier backtest evidence void. If Phase 14 is rescoped to exclude the expiry clock, reopen G3.

---
_Verified: 2026-10-04_
_Verifier: Claude (gsd-verifier)_
