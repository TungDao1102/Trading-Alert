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
- **After every plan wave:** quick run plus `tests/test_backtest_simulator.py tests/test_backtest_experiment.py tests/test_backtest_determinism.py tests/test_backtest_engine_strategy.py tests/test_paper_parity.py tests/test_cost_parity.py tests/test_phase6_fixture_geometry.py tests/test_phase6_fixture_scenarios.py`, ruff and mypy; no wave may end with a red test owned by a later plan (the Phase 6/7 fixture write and all its consumers share plan 15-12)
- **Before `/gsd-verify-work`:** full suite green except documented local environment items (PG-dependent tests), ruff, mypy, smoke runs
- **Max feedback latency:** 90 seconds per task

---

## Per-Task Verification Map

All commands run as `.venv/Scripts/python -m pytest <files> -q -p no:cacheprovider` from the repository root.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 15-01-01 | 01 | 1 | STRAT-02 | T-15-01 | audit table: Family A cells, verdict vocabulary, decision citations | doc check | `tests/test_geometry_audit_doc.py` | ❌ W0 (created here) | ⬜ pending |
| 15-01-02 | 01 | 1 | STRAT-02 | T-15-01 | B/C cells, leakage verdicts, flags F1-F12 | doc check | `tests/test_geometry_audit_doc.py tests/test_decision_alignment_authority.py tests/test_decision_alignment_exchange.py` | ✅ | ⬜ pending |
| 15-02-01 | 02 | 1 | STRAT-02 | T-15-02, T-15-04 | missing rationale or PLACEHOLDER refused by pin_stream_epoch; only tests pass the allow flag | unit | `tests/test_rationale.py tests/test_paper_freeze.py tests/test_cost_per_unit.py` | ❌ W0 (created here) | ⬜ pending |
| 15-02-02 | 02 | 1 | STRAT-02 | T-15-03 | value match, basis vocabulary, refs, hash neutrality over every pinned set | unit | `tests/test_rationale.py tests/test_domain_no_float.py` | ✅ | ⬜ pending |
| 15-03-01 | 03 | 2 | STRAT-01, STRAT-02 | T-15-05 | Family A LONG from a confirmed pivot; stop beyond the outer zone edge (hand-derived) | unit + sidecar | `tests/test_planner_geometry.py tests/test_core_tracer.py tests/test_core_planner.py` | ❌ W0 (created here) | ⬜ pending |
| 15-03-02 | 03 | 2 | STRAT-01 | T-15-05 | pivot confirmed exactly at t+R, evaluated bar never the level, prefix invariance | unit + property | `tests/test_core_pivots.py tests/test_domain_no_float.py tests/test_planner_geometry.py` | ❌ W0 (created here) | ⬜ pending |
| 15-03-03 | 03 | 2 | STRAT-02 | T-15-06, T-15-07 | new keys typed, ranged, cross-checked; old hashes unchanged | unit | `tests/test_registry.py tests/test_registry_gate.py tests/test_decision_alignment_params.py` | ✅ extend | ⬜ pending |
| 15-04-01 | 04 | 3 | STRAT-02 | T-15-08 | shared validator order D-06, D-07, D-08, F6 before RR; single call site | unit | `tests/test_planner_geometry.py tests/test_core_planner.py tests/test_core_tracer.py` | ✅ | ⬜ pending |
| 15-04-02 | 04 | 3 | STRAT-02 | T-15-09 | Family A SHORT, opposite pivot TP1, audit anchors (hand-derived) | unit + sidecar | `tests/test_planner_geometry.py` | ✅ | ⬜ pending |
| 15-04-03 | 04 | 3 | STRAT-01 | T-15-05 | no pivot is NO_TRADE_REGIME, p9 regression, legacy signals unchanged | unit | `tests/test_core_strategy_geometry.py tests/test_core_tracer.py tests/test_no_lookahead.py tests/test_prefix_invariance.py tests/test_candle_close_timing.py` | ❌ W0 (created here) | ⬜ pending |
| 15-05-01 | 05 | 4 | STRAT-01, STRAT-02 | T-15-10 | Family B anchored retest, S3 stop on the narrow S/R zone (hand-derived at breakout_confirmation_bars 1, the proposed baseline from sheet B1) | unit + sidecar | `tests/test_planner_geometry.py tests/test_core_strategy_breakout_retest.py` | ✅ extend | ⬜ pending |
| 15-05-02 | 05 | 4 | STRAT-01 | T-15-10, T-15-11 | stale/non-first retest rejected, with-direction gate, legacy unchanged; b_short_worked at value 1 and b_long_legacy_confirm3 (legacy value 3, not the baseline to be ratified) hand-derived | unit | `tests/test_core_strategy_breakout_retest.py tests/test_planner_geometry.py` | ✅ extend | ⬜ pending |
| 15-05-03 | 05 | 4 | STRAT-01 | T-15-11 | B leakage proof, validator cases on B | unit | `tests/test_core_strategy_breakout_retest.py tests/test_planner_geometry.py tests/test_core_tracer.py` | ✅ extend | ⬜ pending |
| 15-06-01 | 06 | 5 | STRAT-01, STRAT-02 | T-15-12 | Family C pivot NEUTRAL regime, S3 stop, T-mid target (hand-derived) | unit + sidecar | `tests/test_planner_geometry.py tests/test_core_strategy_range_mr.py` | ✅ extend | ⬜ pending |
| 15-06-02 | 06 | 5 | STRAT-01 | T-15-12 | pivot regime verdicts, insufficient pivots, prefix invariance, legacy regime unchanged | unit + property | `tests/test_core_strategy_range_mr.py tests/test_core_pivots.py` | ✅ extend | ⬜ pending |
| 15-06-03 | 06 | 5 | STRAT-01, STRAT-02 | T-15-12 | C SHORT, T_OPPOSITE, T-mid RR gate, leakage, validator cases | unit | `tests/test_planner_geometry.py tests/test_core_strategy_range_mr.py tests/test_core_strategy_breakout_retest.py tests/test_core_strategy_geometry.py` | ✅ extend | ⬜ pending |
| 15-07-01 | 07 | 6 | STRAT-02 | T-15-14 | census counts via public functions; independent invariant checker | unit | `tests/test_geometry_census.py` | ❌ W0 (created here) | ⬜ pending |
| 15-07-02 | 07 | 6 | STRAT-02 | T-15-08 | D-06 property over the ATR/tolerance/buffer grid, non-vacuous, all families | property | `tests/test_geometry_property.py` | ❌ W0 (created here) | ⬜ pending |
| 15-07-03 | 07 | 6 | STRAT-02 | T-15-13 | census run on real data: counts only and information only, one run per draft set (breakout-retest draft at breakout_confirmation_bars 1, no comparison run at alternative values), draft sets zero violations | run + unit | `tests/test_geometry_census.py tests/test_geometry_property.py` (plus the census CLI runs recorded in the SUMMARY) | ✅ | ⬜ pending |
| 15-08-01 | 08 | 7 | STRAT-02 | T-15-15 | user ratifies every value and basis (gate blocking-human: never auto-approved or auto-selected in any mode, no reply = stop); exactly one proposed value and one basis with its source per key; trend-pullback min_stop_atr presence not negotiable (criterion 1) | checkpoint:decision | n/a (human decision; the SUMMARY records the user-answer marker and the verbatim reply) | — | ⬜ pending |
| 15-08-02 | 08 | 7 | STRAT-02 | T-15-15, T-15-16 | refuses to run without the user-answer marker; trend-pullback v6 as ratified with min_stop_atr, pinned, rationale complete, PLACEHOLDER refused for paper | unit | marker `grep -qF` on 15-08-SUMMARY.md, then `tests/test_rationale.py tests/test_registry.py tests/test_registry_gate.py tests/test_decision_alignment_params.py tests/test_analytics_files.py` | ✅ extend | ⬜ pending |
| 15-08-03 | 08 | 7 | STRAT-02 | T-15-15, T-15-16 | refuses to run without the marker; B and C v6 as ratified, pinned; census re-run (invariant_violations 0) for every family whose ratified values differ from the 15-07 drafts | unit + run | marker `grep -qF`, then `tests/test_rationale.py tests/test_decision_alignment_params.py tests/test_analytics_files.py tests/test_kill_gate_families.py tests/test_analytics_cli.py tests/test_registry.py` (plus the census runs recorded in the SUMMARY) | ✅ extend | ⬜ pending |
| 15-09-01 | 09 | 8 | STRAT-02 | T-15-17 | -v4 baselines from the marked user answer only: no-trade gives RR_TOO_LOW, simple-trend plans, both carry min_stop_atr | unit | `tests/test_rationale.py tests/test_decision_alignment_params.py tests/test_analytics_files.py tests/test_kill_gate_families.py` | ✅ extend | ⬜ pending |
| 15-09-02 | 09 | 8 | STRAT-02 | T-15-17 | PA-08 (including min_stop_atr on every trend-pullback Phase 15 set, criterion 1) and exact pin-set equality with negative tests | unit | `tests/test_decision_alignment_params.py tests/test_rationale.py` | ✅ extend | ⬜ pending |
| 15-10-01 | 10 | 9 | STRAT-02 | T-15-27 | v6 LONG trigger payload in memory: independent geometry, real plan equal, stop-first scenario; CRLF-normalized committed comparison (F12); no committed fixture moves | unit | `tests/test_phase6_fixture_geometry.py tests/test_phase6_fixture_scenarios.py`, then the generator run and `git diff --quiet` on tests/fixtures/phase6 and phase7 | ❌ W0 (scenarios file created here) | ⬜ pending |
| 15-10-02 | 10 | 9 | STRAT-02 | T-15-27 | every v6 payload proves its named scenario and consumer facts (facts tabled with Decimal one-liners); existing consumers unchanged and green | unit + regression | `tests/test_phase6_fixture_scenarios.py tests/test_phase6_fixture_geometry.py tests/test_backtest_simulator.py tests/test_backtest_experiment.py tests/test_backtest_determinism.py tests/test_backtest_engine_strategy.py tests/test_paper_parity.py tests/test_cost_parity.py` | ✅ | ⬜ pending |
| 15-11-01 | 11 | 9 | STRAT-02 | T-15-20 | planner unit tests on v6 with intent kept | unit | `tests/test_core_planner.py tests/test_planner_geometry.py` | ✅ extend | ⬜ pending |
| 15-11-02 | 11 | 9 | STRAT-02 | T-15-19 | phase4 regeneration cannot clobber pins | script + unit | `scripts/_regen_phase4_expectations.py`, `git diff --quiet` on the pin file, `tests/test_core_features.py tests/test_fixture_harness.py` | ✅ extend | ⬜ pending |
| 15-12-01 | 12 | 10 | STRAT-02 | T-15-21 | writers emit build_v6_payloads(), fixtures regenerated, committed-file identity and geometry checks; engine and determinism on the regenerated trigger fixture with its declared identity | integration | `scripts/gen_phase6_fixtures.py` then `tests/test_phase6_fixture_geometry.py tests/test_phase6_fixture_scenarios.py tests/test_backtest_engine_strategy.py tests/test_backtest_determinism.py` | ✅ extend | ⬜ pending |
| 15-12-02 | 12 | 10 | STRAT-02 | T-15-18, T-15-21 | Phase 6 hand literals substituted from the 15-10 facts table; snapshots re-pinned only with V6_SCENARIOS proof | regression | `tests/test_backtest_simulator.py tests/test_phase6_fixture_scenarios.py tests/test_phase6_fixture_geometry.py` | ✅ extend | ⬜ pending |
| 15-12-03 | 12 | 10 | STRAT-02 | T-15-18, T-15-21 | paper parity on v6, cost parity hand legs, experiment; full suite green at the end of wave 10 (nothing deferred) | regression + suite | `tests/test_paper_parity.py tests/test_paper_closed_candle.py tests/test_paper_feed_gates.py tests/test_cost_parity.py tests/test_backtest_experiment.py tests/test_analytics_cli.py tests/test_analytics_report.py`, then `tests` | ✅ extend | ⬜ pending |
| 15-13-01 | 13 | 11 | STRAT-02 | T-15-22 | validator universal: legacy A STOP_TOO_TIGHT, legacy B/C INVALIDATED, passing legacy hashes unchanged | unit | `tests/test_planner_geometry.py tests/test_core_planner.py tests/test_core_tracer.py tests/test_core_strategy_geometry.py` | ✅ extend | ⬜ pending |
| 15-13-02 | 13 | 11 | STRAT-02 | T-15-22, T-15-23 | property over legacy and v1 shapes; full suite green | property + suite | `tests` (full suite) | ✅ extend | ⬜ pending |
| 15-14-01 | 14 | 9 | STRAT-01, STRAT-02 | T-15-24 | Family A sheet Implemented-as, Status NOT FROZEN | doc check | `tests/test_geometry_audit_doc.py tests/test_analytics_files.py tests/test_kill_gate_families.py` | ✅ extend | ⬜ pending |
| 15-14-02 | 14 | 9 | STRAT-01, STRAT-02 | T-15-24 | B/C sheets, GLOSSARY prose, CONFIGURATION keys; doc gates | doc check | `tests/test_geometry_audit_doc.py tests/test_decision_alignment_ops_risk.py tests/test_decision_alignment_bookkeeping.py tests/test_decision_alignment_authority.py tests/test_decision_alignment_exchange.py tests/test_domain_enums.py` | ✅ extend | ⬜ pending |
| 15-15-01 | 15 | 12 | STRAT-01, STRAT-02 | T-15-25 | trend-pullback v6 smoke twice with equal digests; census zero violations | unit + run | `tests/test_smoke_backtest_cli.py tests/test_geometry_census.py` (plus smoke and census runs) | ✅ extend | ⬜ pending |
| 15-15-02 | 15 | 12 | STRAT-01, STRAT-02 | T-15-25 | B and C readiness runs; final audit verdicts | doc check + run | `tests/test_geometry_audit_doc.py tests/test_decision_alignment_authority.py tests/test_decision_alignment_exchange.py tests/test_decision_alignment_protocol.py` | ✅ extend | ⬜ pending |
| 15-15-03 | 15 | 12 | STRAT-01, STRAT-02 | T-15-26 | D054 directly after D053 with the compiled inventory | doc check + suite | `tests/test_decision_alignment_bookkeeping.py tests/test_kill_gate_docs.py tests/test_decision_alignment_protocol.py tests/test_geometry_audit_doc.py`, then `tests` | ✅ extend | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Each missing test file is created RED-first by the task that first needs it (TDD mode); no separate Wave 0 plan is required.

- [ ] `tests/test_rationale.py` (15-02-01), `tests/test_planner_geometry.py` (15-03-01), `tests/test_core_pivots.py` (15-03-02), `tests/test_core_strategy_geometry.py` (15-04-03), `tests/test_geometry_census.py` (15-07-01), `tests/test_geometry_property.py` (15-07-02), `tests/test_geometry_audit_doc.py` (15-01-01), `tests/test_phase6_fixture_scenarios.py` (15-10-01)
- [ ] `tests/fixtures/phase15/geometry_cases.json` and `DERIVATIONS.md` (15-03-01, extended in 15-04, 15-05, 15-06; hand-derived, independent arithmetic)
- [ ] `src/domain/rationale.py` (15-02-02) and `src/core/pivots.py` (15-03-02) added to `tests/test_domain_no_float.py` `SCANNED_FILES`
- [ ] line-ending fix for the Phase 6 generator comparison (research flag F12) in 15-10-01, before the fixtures are re-pinned

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real-data smoke on the new sets (criterion 4) | STRAT-02 | slow (minutes), needs local data store | 15-15-01 and 15-15-02: `scripts/smoke_backtest_realdata.py` per family on BTCUSDT, 30 days ending 2026-10-01, two runs, digests must match; census invariant_violations 0 |
| Census on real data before freezing (D-10, D-11) | STRAT-02 | slow, needs local data store | 15-07-03: `scripts/geometry_census.py` on draft and legacy sets for BTCUSDT, ETHUSDT, SOLUSDT; counts recorded in 15-07-SUMMARY.md |
| User ratifies new parameter numbers | F-909 | money-relevant values | 15-08-01 `checkpoint:decision` with gate blocking-human (never auto-approved or auto-selected in any mode; no reply = stop) and worked examples at equity 500 and 1,000; 15-08 Tasks 2-3 and 15-09 Task 1 refuse to run without the user-answer marker in 15-08-SUMMARY.md |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90 s per task
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
