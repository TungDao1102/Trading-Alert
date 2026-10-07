---
phase: 14-backtest-causality-rewrite
verified: 2026-10-07T04:19:53Z
status: human_needed
score: 6/6 must-haves verified
covered_files:
  - .planning/phases/14-backtest-causality-rewrite/14-01-PLAN.md
  - .planning/phases/14-backtest-causality-rewrite/14-01-SUMMARY.md
  - .planning/phases/14-backtest-causality-rewrite/14-02-PLAN.md
  - .planning/phases/14-backtest-causality-rewrite/14-02-SUMMARY.md
  - .planning/phases/14-backtest-causality-rewrite/14-03-PLAN.md
  - .planning/phases/14-backtest-causality-rewrite/14-03-SUMMARY.md
  - .planning/phases/14-backtest-causality-rewrite/14-04-PLAN.md
  - .planning/phases/14-backtest-causality-rewrite/14-04-SUMMARY.md
  - .planning/phases/14-backtest-causality-rewrite/14-05-PLAN.md
  - .planning/phases/14-backtest-causality-rewrite/14-05-SUMMARY.md
  - .planning/phases/14-backtest-causality-rewrite/14-06-PLAN.md
  - .planning/phases/14-backtest-causality-rewrite/14-06-SUMMARY.md
  - .planning/phases/14-backtest-causality-rewrite/14-07-PLAN.md
  - .planning/phases/14-backtest-causality-rewrite/14-07-SUMMARY.md
  - .planning/phases/14-backtest-causality-rewrite/14-08-PLAN.md
  - .planning/phases/14-backtest-causality-rewrite/14-08-SUMMARY.md
  - .planning/phases/14-backtest-causality-rewrite/14-09-PLAN.md
  - .planning/phases/14-backtest-causality-rewrite/14-09-SUMMARY.md
  - .planning/phases/14-backtest-causality-rewrite/14-10-PLAN.md
  - .planning/phases/14-backtest-causality-rewrite/14-10-SUMMARY.md
  - .planning/phases/14-backtest-causality-rewrite/14-11-PLAN.md
  - .planning/phases/14-backtest-causality-rewrite/14-11-SUMMARY.md
  - .planning/phases/14-backtest-causality-rewrite/14-12-PLAN.md
  - .planning/phases/14-backtest-causality-rewrite/14-12-SUMMARY.md
  - .planning/phases/14-backtest-causality-rewrite/14-13-PLAN.md
  - .planning/phases/14-backtest-causality-rewrite/14-13-SUMMARY.md
  - .planning/phases/14-backtest-causality-rewrite/14-14-PLAN.md
  - .planning/phases/14-backtest-causality-rewrite/14-14-SUMMARY.md
  - .planning/phases/14-backtest-causality-rewrite/14-15-PLAN.md
  - .planning/phases/14-backtest-causality-rewrite/14-15-SUMMARY.md
  - .planning/phases/14-backtest-causality-rewrite/14-16-PLAN.md
  - .planning/phases/14-backtest-causality-rewrite/14-16-SUMMARY.md
  - .planning/phases/14-backtest-causality-rewrite/14-17-PLAN.md
  - .planning/phases/14-backtest-causality-rewrite/14-17-SUMMARY.md
  - docs/DECISIONS.md
  - docs/DOC_STATUS.md
  - docs/SOURCES.md
  - docs/backtest/BACKTEST_SPEC.md
  - docs/research/RESEARCH_PROTOCOL.md
  - docs/research/holdout_consumed.json
  - docs/trading/RISK_MANAGEMENT.md
  - scripts/decision_alignment/bookkeeping.py
  - scripts/decision_alignment/protocol.py
  - scripts/gen_phase14_fixtures.py
  - scripts/gen_phase6_fixtures.py
  - scripts/smoke_backtest_realdata.py
  - src/adapters/analytics_files.py
  - src/adapters/code_version.py
  - src/analytics/excursion.py
  - src/analytics/inputs.py
  - src/analytics/lifecycle.py
  - src/analytics/live_outcomes.py
  - src/backtest/__init__.py
  - src/backtest/case.py
  - src/backtest/constraints.py
  - src/backtest/costs.py
  - src/backtest/engine.py
  - src/backtest/entry.py
  - src/backtest/exits.py
  - src/backtest/experiment.py
  - src/backtest/funding.py
  - src/backtest/ledger.py
  - src/backtest/lifecycle.py
  - src/backtest/records.py
  - src/backtest/report.py
  - src/backtest/semantics.py
  - src/backtest/series.py
  - src/backtest/simulator.py
  - src/backtest/validator.py
  - src/core/strategy.py
  - src/core/types.py
  - src/data/case_input.py
  - src/data/metadata.py
  - src/data/minute_source.py
  - src/risk/realized_risk.py
covered_digest: "v2:sha256:5880aa37399bbf8ed47bef1442defa8d1fd3ba7bf9c075c80a699fbc8e0a6f33"
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "OQ-1: decide how a trade held through mark-price holes is treated in the evidence (keep annotate-only, count it against coverage, exclude it from pooled R, or void it)"
    expected: "A recorded user decision (DECISIONS row or UAT entry). Today such a trade is annotated in coverage_note and otherwise counts as a normal trade; fallback_applied, fallback_count, the coverage percent and the ExperimentRecord do not change"
    why_human: "Evidence policy is the user's call (deferred-items.md 'Open decisions for the user'). The recommended default (annotate-only until the research runner decides the evidence format) is a recommendation, not a decision"
  - test: "Name an owner for 'modeled_costs_per_unit is None on v2 filled TradeRecords' or accept it as is"
    expected: "A ROADMAP phase or a recorded decision. D052 says the item is owed to 'the Phase 15 research runner', but Phase 15 is complete and its criterion 4 puts the research run outside any phase, so the named owner no longer points at a scheduled deliverable"
    why_human: "Choosing a phase or accepting the gap is a planning decision. Nothing in src reads the field today (sizing figures come from the evaluate_risk verdict), so no Phase 14 criterion depends on it"
  - test: "Name an owner for 'no runner calls read_code_version plus assemble outside tests'"
    expected: "A ROADMAP phase (or a decision) that builds the production research runner. D052 names the Phase 15 research runner (and Phase 26 for holdout-once only). Phase 15 is complete and built no runner; grep finds assemble( only in src/backtest/experiment.py and read_code_version only in src/adapters/code_version.py"
    why_human: "Same as above: the named owner is no longer a scheduled deliverable. The typed record, the binding checks and code_version verification exist and are tested; only the production caller is missing"
---

# Phase 14: Backtest Simulator Causality Rewrite Verification Report

**Phase Goal:** The backtest cannot see the future. A plan created at the close of bar N can fill only from bar N+1, until expiry, at a price that actually traded. Positions carry across bars, and exits follow live semantics. All earlier backtest evidence is declared void.
**Verified:** 2026-10-07T04:19:53Z (HEAD bffc4ba; working tree changes are only .planning/config.json, .planning/state.json and .gsd/, none of which were touched)
**Status:** human_needed
**Re-verification:** No. This is the first verification.

Note on code state: Phase 15 has executed on top of Phase 14, so HEAD includes Phase 15 changes (for example the re-pinned phase 6 regression digests, D-19 of Phase 15). Every Phase 14 test below was re-run against HEAD and passes.

## Goal Achievement

### Observable Truths (ROADMAP success criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | The entry fills only after the signal bar, and only on a trade-through of the limit by at least one tick. `entry_time > signal_close` and `exit_time >= entry_time` are asserted on every trade | VERIFIED | Code read. `lifecycle.advance` clamps the window start to `max(start_exclusive, signal_close_utc)` (lifecycle.py:485). Both `MinuteSource` implementations select minutes whose close lies in `(start, end]` (`series._window`, `minute_source._window`), so no minute closing at or before the signal close is read. `entry.is_trade_through`: LONG `low <= limit - tick`, SHORT `high >= limit + tick`; a touch only increments `touch_no_fill_count`. The fill price is the limit and the fill time is the minute close (`_fill`). The tick comes from the point-in-time snapshot (`engine._size_and_register` passes `pit.snapshot.price_tick_size`). `validate_trade_record` raises `TradeRecordInvariantError` when `entry_time <= signal_close` or `exit_time < entry_time` (validator.py:169-177). It runs in strict mode on every engine record (`engine._close_entity`), again at the analytics boundary (`analytics/inputs.py:44`) and on reload (`experiment._trade_from_dict`). Reject records have no fill, so the time invariants do not apply. Tests re-run: test_backtest_entry 25, test_trade_record_validator 24, test_backtest_chain 13, goldens `signal_bar_touch_no_fill`, `trade_through_vs_touch` and `gap_through_limit` (in test_backtest_goldens, 18). All passed. |
| 2 | Positions are held across bars until SL, TP2 or data end. The TP1/TP2 ladder matches live (F-102). SL/TP triggers are evaluated on mark-price klines (D037) | VERIFIED | Code read. The OPEN loop of `advance` walks mark minutes only (`source.mark_minutes`) through `exits.resolve_mark_minute`: stop first, TP1 partial once, then TP2 for the remainder. On the fill minute only the stop is checked. `protective_levels_for_fill` calls the live `size_protectives_to_filled_qty` with `ProtectiveTemplate(tp1_quantity_fraction=TP1_QUANTITY_FRACTION)`. `TP1_QUANTITY_FRACTION = Decimal("0.5")` (semantics.py:28) was the user's choice (D-27, "dùng 0.5", 2026-10-04; D052 (c)). The stop is unchanged after TP1 (`_apply_leg` only lowers `remaining_quantity`). There is no time stop. `finalize_at_data_end` closes an open position as END_OF_DATA at the last mark close, and CR-01 floors that close at the TP1 time. A resting plan at data end becomes PENDING_AT_DATA_END. A stop gap books the adverse of trigger and open and sets a flag. A mark hole in a strategy bar resolves once at the bar close (`resolve_fallback_hour`) and sets `fallback_applied`. Tests re-run: test_backtest_exits 36, test_backtest_mark_hole_coverage 27, test_backtest_lifecycle 9, goldens `hold_to_sl`, `tp1_then_tp2`, `tp1_then_sl`, `stop_first_tie`, `end_of_data` and `missing_mark_fallback`. All passed. ROADMAP wording "until SL, TP2 or data end" is in place (D-39). |
| 3 | Funding is modeled with a documented sign convention. Constraints are point-in-time. Portfolio, daily-loss and equity state evolve through the run | VERIFIED | Funding: `funding_pnl = -sign x quantity x mark x rate`, charged at every actual `fundingTime` with `segment.start <= t < segment.end`. The engine builds constant-quantity segments split at TP1 (`engine._open_segments`), so the post-TP1 remainder is charged. Missing coverage raises `FundingCoverageError` unless an allowed gap covers it, and used gaps are recorded in `run_summary.allowed_gaps_used`. The convention is documented in BACKTEST_SPEC (line 51), RISK_MANAGEMENT section 3 and D052 (d), and it joins `cost_model_hash` as `funding_convention` `MARK_NOTIONAL_SIGNED_V1`. Net PnL includes funding (records.py:380). Point-in-time: `select_constraints` takes the latest row with `observed_at <= bar close`, back-extrapolates the earliest row before the first one (flagged, counted) and passes `ttl=timedelta(0)` and `now_utc=close` to the risk function. Ledger: `Ledger` is updated by dated bookings in `(time, symbol, rank)` order. The UTC-day loss uses `derive_daily_state`. DAILY_STOP cancels resting entries at that instant (`_cancel_resting`). Resting entries count as exposure. Signals are evaluated after the bookings, against ledger equity. I checked the funding golden arithmetic by hand: 15.928 x 101.0 x 0.001 = 1.608728 and 7.964 x 103.0 x 0.002 = 1.640584. Tests re-run: test_backtest_funding 40, test_backtest_ledger 26, test_backtest_pit_constraints 20, goldens `funding_paid_received`, `funding_between_times` and `daily_loss_blocks_next`. All passed. See the Info note on IN-03 (back-extrapolation on real data). |
| 4 | The R denominator is identical for backtest and live (F-204). The regime slice is emitted (F-123). ExperimentRecord carries the protocol-mandatory fields (F-118) | VERIFIED | `src/risk/realized_risk.py::realized_risk_for_fill` is the only denominator. It is used by `records.build_trade_record`, `engine._update_exposure` and `analytics/live_outcomes.py:270`. `excursion.py` divides by `outcome.realized_risk`. `grep risk_budget src/analytics` finds only a docstring saying it is no longer a denominator. Live R stays INCOMPLETE(NO_RISK_VALUE) without a sized input (D-29, recorded). The regime travels `SetupResult.regime` -> `_Entity.regime` -> `TradeRecord.regime` -> `report.counts_by_regime`. The plateau section reads "not computed (BKTS-03 pending)". `ExperimentRecord` has 17 typed fields (no_trade_counts, intrabar_tie_break, timeframe, context_timeframe, parameter_values, cost_values, simulator_semantics_version, code_commit, code_dirty, fallback_count, end_of_data_count, window sizes, allowed_gaps, split_role and boundaries), validated in `__post_init__` with `IncompleteExperimentRecord`. `assemble` binds the run identity (CR-02). Tests re-run: test_r_denominator_parity 4, test_analytics_live_outcomes 26, test_backtest_report 27, test_backtest_run_summary 9, test_backtest_experiment 14, test_code_version 14, test_analytics_files 111 (+1 skip: symlinks unavailable on Windows), test_analytics_cli 57. All passed. |
| 5 | Every golden case has a hand-derived expected output not produced by the code under test. The fixture generator no longer places 1m data inside the signal bar | VERIFIED | `tests/fixtures/phase14/` has 16 cases, each with `input.json` and `expected.json`, and `DERIVATIONS.md` has a section per case with standalone Decimal arithmetic. The generator writes `input.json` only, and a meta-test fails if it writes anything else or imports the project. Meta-tests also assert that no minute opens at or before the plan's bar close. `scripts/gen_phase6_fixtures.py` starts minutes at bar N+1, guarded by `test_no_minute_row_opens_inside_the_signal_bar`. Non-rebuilt phase 6 cases are labelled regression snapshots in `tests/fixtures/phase6/REGRESSION_SNAPSHOTS.md`. Tests re-run: test_backtest_goldens 18, test_phase14_fixture_generator 12, test_phase6_fixture_geometry 119, test_phase6_fixture_scenarios 48. All passed. Limit: whether the expected values were really derived before the code ran cannot be proven from the repository. The derivations are substantive and independently checkable, and I re-derived the funding numbers above. |
| 6 | (Phase 6 G3 carry-over) Entry expiry is judged against the simulated bar time, not the fixture's `now_utc`. A multi-bar test shows one limit that expires after `signal_expiry_hours` and one that fills before it | VERIFIED | `_entry_now_utc` no longer exists: `grep -rn "_entry_now_utc\|now_utc" src/backtest` finds only the v1-key refusal list in case.py (lines 62 and 66) and `now_utc=close` passed to risk. `entry.is_minute_eligible` compares `minute.close_time_utc <= plan.expiry_utc`, and `advance` ends an unfilled plan EXPIRED at `expiry_utc` once the window reaches it. The precedence is fill, then invalidation, then expiry. `advance` has no clock parameter, and a test asserts this. Tests: test_backtest_expiry_clock 10 (`test_plan_a_fills_on_bar_n_plus_2_before_expiry`, `test_plan_b_expires_when_the_limit_is_first_reached_after_expiry`, `test_expiry_boundary_minute_fills_and_the_next_minute_cannot`, bar-by-bar equals one window) and the engine-level goldens `g3_fill_before_expiry`, `g3_expire_after` (EXPIRED, resolved 13:59:59.999 = signal close + 4 h) and `expiry_before_fill`. All re-run and passed. G3 is closed in code. The open bookkeeping item is that `06-UAT.md` test 23 still reads `result: skipped`, "owned by Phase 14". That file is outside this verifier's write scope (see Notes for the orchestrator). |

**Score:** 6/6 truths verified (0 present but behavior-unverified). Each truth is behavior-dependent (fills, expiry, ladder transitions, funding timing, ledger state). Each one is backed by named tests that exercise the behavior, and those tests were re-run here, not just read in a SUMMARY.

Plan-level must_haves of the 17 plans (lifecycle driver, entry rule, funding module, cost identity, ledger and PIT, R parity, exit engine, v2 engine, regime/run summary/determinism, data adapter, analytics boundary, v1 retirement, goldens, smoke CLI, typed record, protocol amendment, mark-hole notes) were checked as supporting evidence for the six criteria above. None contradicts a criterion.

### Goal clause "All earlier backtest evidence is declared void"

VERIFIED by reading the documents. D052 (k) declares all v1 evidence void and records the evidence-store check: kill_gate_decisions.json has no family decision, holdout_consumed.json has no entry, and git tracks no experiment or backtest evidence file. The Phase 6 ROADMAP line carries "VOID (Phase 14, D052)". REQUIREMENTS BKTS-01, BKTS-02 and DOMN-03 carry the void note and a traceability note. `RESEARCH_PROTOCOL.md` header: v2.0.0, FROZEN, Frozen on 2026-09-19, Amended on 2026-10-05, Supersedes v1.1.0. The evidence schema `analytics-evidence/2` refuses old files. `scripts/verify_decision_alignment.py all` returns ALL_PASS (re-run). test_decision_alignment_protocol 24, test_decision_alignment_bookkeeping 46, test_kill_gate_docs 12 and test_research_gate_negative 15 all passed.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/backtest/semantics.py` | Constants incl. TP1 0.5, STOP_FIRST, funding convention, version 2.0.0 | VERIFIED | Read in full |
| `src/backtest/series.py`, `src/data/minute_source.py` | Lazy MinuteSource with `(start, end]` close-time windows, validated, no padding | VERIFIED / WIRED | Engine and lifecycle read minutes only through it; smoke script uses `ParquetMinuteSource` |
| `src/backtest/entry.py`, `lifecycle.py`, `exits.py` | Entry rule, expiry, invalidation, ladder, fallback, END_OF_DATA, mark-hole notes | VERIFIED / WIRED | `advance` calls the entry and exit rules; the engine calls `advance`, `cancel_plan` and `finalize_at_data_end` |
| `src/backtest/funding.py`, `ledger.py`, `constraints.py` | Funding, ledger, PIT constraints | VERIFIED / WIRED | Engine `_push_funding` / `_book` / `select_constraints` |
| `src/backtest/engine.py`, `simulator.py` | v2 event loop; `run` delegates with module-global `evaluate_risk` | VERIFIED / WIRED | simulator.py is 59 lines of delegation; v1 code gone |
| `src/backtest/validator.py`, `src/risk/realized_risk.py` | Shared validator; single R function | VERIFIED / WIRED | Called at the engine, the analytics boundary and reload |
| `src/backtest/experiment.py`, `src/adapters/code_version.py`, `src/adapters/analytics_files.py` | Typed record, code version, evidence v2 | VERIFIED (production caller missing, see human items) | Used by tests and the evidence loader; no production runner calls `assemble` |
| `src/backtest/report.py` | Closed-trade counting, regime slice, plateau not computed | VERIFIED | |
| `tests/fixtures/phase14/**`, `DERIVATIONS.md`, `scripts/gen_phase14_fixtures.py` | 16 hand-derived goldens, input-only generator | VERIFIED | |
| `scripts/smoke_backtest_realdata.py` | Real-data smoke CLI | VERIFIED (CLI tests); real-data run is recorded evidence | test_smoke_backtest_cli 16 passed |
| `docs/DECISIONS.md` D052/D053, protocol v2.0.0, BACKTEST_SPEC | Decisions, inventory, spec | VERIFIED | Text read; gate ALL_PASS |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| `simulator.run` | `engine.simulate` | `simulate(case_input, risk_fn=evaluate_risk, ...)` | WIRED |
| `engine._process_window` | `lifecycle.advance` / `finalize_at_data_end` | per active symbol per close | WIRED |
| `lifecycle.advance` | `entry.is_minute_eligible` / `is_trade_through` / `is_invalidated` | RESTING loop | WIRED |
| `lifecycle.advance` | `exits.resolve_mark_minute` / `resolve_fallback_hour` | OPEN loop | WIRED |
| `exits.protective_levels_for_fill` | `execution.placement.size_protectives_to_filled_qty` | `ProtectiveTemplate(tp1_quantity_fraction=TP1_QUANTITY_FRACTION)` | WIRED |
| `engine._push_funding` | `funding.funding_events` | segments split at TP1 | WIRED |
| `engine._size_and_register` | `risk_fn` + `select_constraints` + ledger | ledger equity, exposures, daily loss, ttl 0 | WIRED |
| `records.build_trade_record` / `live_outcomes` | `realized_risk_for_fill` | import + call | WIRED |
| `analytics.inputs.normalize_backtest` | `validate_trade_record` | per record, re-raised as AnalyticsInputError | WIRED |
| `lifecycle` coverage_note | `records` -> `report.coverage_notes` | existing field | WIRED (tracer test passes) |
| `experiment.assemble` / `read_code_version` | production runner | none | NOT WIRED outside tests (recorded open item, D052) |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
|----------|------|--------|-----------|--------|
| TradeRecord fills/exits | trade and mark 1m minutes | `MinuteSource` (in-memory or Parquet) | Yes (synthetic in tests; Parquet in the smoke run) | FLOWING |
| Funding amounts | funding rows | case `funding` rows parsed by `parse_funding_row` | Yes | FLOWING |
| Regime slice | `SetupResult.regime` | `strategy.evaluate` | Yes | FLOWING |
| `modeled_costs_per_unit` on filled records | - | hard-coded `None` (records.py:318) | No consumer reads it | STATIC (recorded open item, D052) |

### Behavioral Spot-Checks (one pytest process per file, Windows rule)

| File | Result |
|------|--------|
| test_backtest_entry | 25 passed |
| test_backtest_exits | 36 passed |
| test_backtest_funding | 40 passed |
| test_backtest_ledger | 26 passed |
| test_backtest_pit_constraints | 20 passed |
| test_backtest_expiry_clock | 10 passed |
| test_trade_record_validator | 24 passed |
| test_backtest_chain | 13 passed |
| test_backtest_determinism | 16 passed |
| test_backtest_goldens | 18 passed |
| test_r_denominator_parity | 4 passed |
| test_phase14_fixture_generator | 12 passed |
| test_backtest_report | 27 passed |
| test_backtest_experiment | 14 passed |
| test_backtest_mark_hole_coverage | 27 passed |
| test_backtest_simulator | 63 passed |
| test_backtest_engine | 39 passed |
| test_backtest_engine_strategy | 11 passed |
| test_backtest_lifecycle | 9 passed |
| test_backtest_records | 24 passed |
| test_backtest_series | 15 passed |
| test_backtest_run_summary | 9 passed |
| test_backtest_binding | 20 passed |
| test_backtest_purity | 9 passed |
| test_minute_source | 20 passed |
| test_case_input_builder | 23 passed |
| test_smoke_backtest_cli | 16 passed |
| test_domain_no_float | 3 passed |
| test_code_version | 14 passed |
| test_analytics_live_outcomes | 26 passed |
| test_cost_parity | 9 passed |
| test_paper_parity | 5 passed |
| test_phase6_fixture_scenarios | 48 passed |
| test_phase6_fixture_geometry | 119 passed |
| test_analytics_cli | 57 passed |
| test_analytics_files | 111 passed, 1 skipped (symlinks unavailable on Windows) |
| test_analytics_sidecar | 16 passed |
| test_analytics_purity | 9 passed |
| test_decision_alignment_protocol | 24 passed |
| test_decision_alignment_bookkeeping | 46 passed |
| test_kill_gate_docs | 12 passed |
| test_research_gate_negative | 15 passed |

Also re-run: `uv run ruff check` (all checks passed), `uv run ruff format --check` (429 files formatted), `uv run mypy src` (no issues, 149 files), `uv run python scripts/verify_decision_alignment.py all` (ALL_PASS).

**Not run here:**
- The full suite in one process (Windows rule).
- PostgreSQL tests (they need `TEST_DATABASE_URL`) and the docker, bootstrap and deploy tests. These are CI-only on this machine.
- The real-data smoke run (plan 14-14). This is **recorded evidence, not re-run**. 14-14-SUMMARY reports BTCUSDT over 90 closed days: 162 trades, digest `806c885e4422dc4bec8a94b928bccd9d03eb2ff90580acadf64d7e6343f08bb4` on both runs, 384.6 s and 371.2 s with tracemalloc, a heap peak of about 7.8 MB, and RSS unavailable on Windows. The constraints were today's values (plumbing evidence only). The digest predates 14-17 and the Phase 15 geometry changes, so a re-run today is not expected to reproduce it.
- No backtest, census or research run, and no Phase 16 work.

### Probe Execution

The phase declares no probe scripts. Step 7c: SKIPPED.

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| BKTS-01 | 14-01, 02, 03, 05, 07, 08, 11, 16, 17 | Intrabar SL/TP with 1m data; limit fills/partials/expiry/invalidation; fees/funding/slippage | SATISFIED | Criteria 1, 2, 3 and 6. Re-verified against the v2 engine (Phase 6 evidence void per D052) |
| BKTS-02 | 14-04, 09, 10, 12, 14, 15, 16 | Reproducible experiments; no-trade and simple-trend baselines | SATISFIED | Determinism suites, reproduce/verify_experiment tests, baselines run through the v2 engine (regression snapshots), smoke digest recorded |
| DOMN-03 | 14-02, 09, 11, 12, 13, 16 | Golden fixtures plus no-lookahead/prefix/candle-close/boundary suites | SATISFIED | Criterion 5; prefix-invariance and 1m no-lookahead in test_backtest_determinism |
| BKTS-04 | 14-06, 09, 11, 15, 16 | Experiment record carries the protocol-required fields incl. verifiable code version | SATISFIED | Criterion 4. The production caller of `read_code_version` + `assemble` is still missing (human item 3) |

All four IDs from the PLAN frontmatter match the ROADMAP requirement list. No orphaned requirement: `grep "Phase 14" REQUIREMENTS.md` finds only the BKTS-04 row plus the traceability note. Bookkeeping observation: the traceability table rows still read `BKTS-01 | Phase 6 | Complete`, `BKTS-02 | Phase 6 | Complete` and `DOMN-03 | Phase 3 | Complete`. The note under the table says "the status cells above are unchanged; the verifier owns them". I did not edit REQUIREMENTS.md (out of my write scope). The orchestrator may want to point those rows at Phase 14.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| Phase 14 src, scripts | - | TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER | none found | - |
| `src/backtest/records.py` | 318 | `modeled_costs_per_unit` hard-coded `None` on filled/unfilled records | Info (recorded open, D052) | No consumer; see human item 2 |
| `src/backtest/constraints.py` / `src/data/metadata.py` | - | Review IN-03: real `symbol_metadata.observed_at` is the refresh time, so on historical data every bar back-extrapolates the earliest row | Info (decided, D-30 / D052 (e)) | Criterion 3 holds by its decided mechanism (select by `observed_at <= close`, otherwise extrapolate, flag and count). On real data today every trade is `constraints_extrapolated`, which the smoke run confirmed ("today's constraints"). Readers of evidence should see `constraints_extrapolated_count` |
| `src/backtest/engine.py` | 675-683 | Review IN-08: a planner reason code outside `RejectionReason` would raise in `build_reject_record` (latent run abort) | Info (open by choice) | Fail-loud, not silent; not reachable while planner and evaluate agree |
| 14-REVIEW.md | - | IN-01..IN-08 open; 14-REVIEW-MARK-HOLES.md IN-01..IN-03 open | Info (open by choice) | None blocks a criterion. All Critical and Warning findings (13 + 5) were fixed with tests |
| ROADMAP Phase 19 criterion 4 | - | Plans a live single-TP fallback when a leg is below minQty, while the backtest (D-27) rejects an un-sizeable TP1 as NO_TRADE | Info (future phase) | Not a Phase 14 gap: backtest and current live helper agree today. When Phase 19 changes live, the backtest must change with it or the parity of criterion 2 breaks. The live TP1 producer (F-103) has no ROADMAP phase number ("a later phase" in D052) |

### Human Verification Required

These items are recorded, not decided. The verifier does not decide them.

### 1. OQ-1: treatment of trades held through mark-price holes

**Test:** Decide whether such a trade stays annotate-only, counts against coverage, is excluded from pooled R, or is voided.
**Expected:** A recorded user decision. Current behaviour (verified in code and by test_backtest_mark_hole_coverage): the note reaches `report.intrabar_coverage.coverage_notes`, and nothing priced, counted or hashed in `run_summary` changes.
**Why human:** This is evidence policy. deferred-items.md marks it "the user has not decided". The suggested trigger is after the real-data research re-run.

### 2. Owner of `modeled_costs_per_unit = None` on v2 filled records

**Test:** Name a ROADMAP phase or record acceptance.
**Expected:** D052 says the item is "owed to the Phase 15 research runner". Phase 15 is complete (its verification passed) and built no runner. ROADMAP Phase 15 criterion 4 says the research run is "a research activity, not part of this phase". So the recorded owner no longer points at any scheduled work.
**Why human:** Planning decision. No Phase 14 criterion depends on it.

### 3. Owner of the production caller of `read_code_version` + `assemble`

**Test:** Name a ROADMAP phase (or record a decision) for the research runner.
**Expected:** Same situation as item 2. Phase 26 owns only holdout-once enforcement.
**Why human:** Planning decision. The typed record, identity binding and code-version checks are built and tested. Only the production caller is missing.

### Notes for the orchestrator (not gaps, outside the verifier's write scope)

- `.planning/phases/06-backtest-simulator-experiment-registry/06-UAT.md` test 23 ("Entry-expiry clock uses simulated bar time (G3)") still reads `result: skipped` and "owned by Phase 14", so audit-uat keeps listing it. This verification found G3 closed in code and tests (criterion 6). Closing that UAT entry is a bookkeeping step for the orchestrator or user.
- `06-VERIFICATION.md` `covered_digest` is stale because 14-16 added VOID notes to the Phase 6 SUMMARYs. That is intended (deferred-items.md).
- ROADMAP Phase 26 goal still names protocol v1.1.0 (deferred-items.md, fix when Phase 26 is planned).
- The 14-17 SUMMARY and deferred-items.md still describe the WR-03 double note as accepted behaviour. That is stale after the mark-hole review fix (14-REVIEW-MARK-HOLES-FIX.md). Docs only.

### Gaps Summary

No gaps. All six ROADMAP criteria hold in the current code, and the goal clause that earlier evidence is void is recorded and enforced (protocol v2.0.0, evidence schema v2, D052 (k)). I re-ran 42 test files one process at a time, plus ruff, mypy and the decision-alignment gate, and all are green. The status is `human_needed`, not `passed`, for one reason. Three open items have no recorded decision or no live deferral owner: OQ-1 is an explicit open user decision, and the two D052 OPEN items name "the Phase 15 research runner" as owner, which Phase 15 did not deliver and the ROADMAP does not schedule. None of the three makes a Phase 14 criterion fail.

---

_Verified: 2026-10-07T04:19:53Z_
_Verifier: Claude (gsd-verifier)_

**Digest refresh (2026-10-07, orchestrator, not a re-verification):** after this report was written, `14-17-SUMMARY.md` (a covered file) and `deferred-items.md` got documentation-only corrections (the superseded "accepted double note", the backlog 999.2 pointer). No source, script, doc or test file in the covered list changed after the verifier ran (`git diff --name-only` over `src scripts docs tests` is empty), so `covered_digest` was recomputed with `verification.fingerprint` over the same covered files. The three human items below were agreed by the user on 2026-10-07 to be closed as deferred, with owner ROADMAP Backlog 999.2 (items 2 and 3) and `deferred-items.md` (OQ-1).
