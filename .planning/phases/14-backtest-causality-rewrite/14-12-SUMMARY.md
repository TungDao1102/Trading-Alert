---
phase: 14-backtest-causality-rewrite
plan: 12
subsystem: backtest
tags: [backtest, causality, simulator, fixtures, regression-snapshots, paper-parity, generator, tdd, decimal]

requires:
  - phase: 14-backtest-causality-rewrite
    provides: "14-08 engine.simulate, case-input v2 and tests/backtest_case_helpers.py; 14-09 typed run_summary and regime on records; 14-11 v2 record vocabulary in analytics and phase 10 helpers"
provides:
  - "src/backtest/simulator.py: run(case_input, *, minute_source=None) delegating to engine.simulate with evaluate_risk read from the module globals at call time; TradeRecord re-export"
  - "src/backtest/__init__.py: exports run and simulate; IntrabarOutcome, SimulatorResult and resolve_intrabar removed"
  - "scripts/gen_phase6_fixtures.py: v2 generator, 1m trade and mark minutes from 10:00 (bar N+1), funding rows, constraint history, data window"
  - "ten regenerated v2 inputs: seven phase6 cases, two baselines, the phase7 parity input"
  - "tests/fixtures/phase6/REGRESSION_SNAPSHOTS.md: F-608 relabel of every non-golden phase6 case"
  - "migrated suites: test_phase6_fixture_geometry, test_backtest_simulator, test_cost_parity, test_paper_parity, test_backtest_experiment"
affects: [14-13, 14-14, 14-15, 14-16]

requirements-completed: [DOMN-03, BKTS-02]

actuals:
  tokens: 30000
  tasks: 3
  commits: 4
plan_head_before: 0f21e8aa30f8920ee93a9122658764a12e3122ab
plan_head_after: d6acf893ae920f1cbb975324ace6e78f93e42e54

tech-stack:
  added: []
  patterns:
    - "The public entry point looks evaluate_risk up in its own module globals at call time, so a monkeypatch of src.backtest.simulator.evaluate_risk reaches every engine risk call; mutating run to capture it at import fails seven tests"
    - "A generator writes 1m data only from bar N+1; a geometry test fails if any minute row opens or closes inside the signal bar"
    - "Regression-snapshot digests pin the whole output dict (trades plus run_summary), with the scenario tuple asserted beside the digest so a drift is readable"

key-files:
  created:
    - tests/fixtures/phase6/REGRESSION_SNAPSHOTS.md
  modified:
    - src/backtest/simulator.py
    - src/backtest/__init__.py
    - scripts/gen_phase6_fixtures.py
    - tests/test_phase6_fixture_geometry.py
    - tests/test_backtest_simulator.py
    - tests/test_cost_parity.py
    - tests/test_paper_parity.py
    - tests/test_backtest_experiment.py
    - tests/fixtures/phase6/baselines/no_trade/input.json
    - tests/fixtures/phase6/baselines/simple_trend/input.json
    - tests/fixtures/phase6/intrabar_both_touched/input.json
    - tests/fixtures/phase6/intrabar_both_touched_short/input.json
    - tests/fixtures/phase6/intrabar_missing_fallback/input.json
    - tests/fixtures/phase6/invalidation_cancels_entry/input.json
    - tests/fixtures/phase6/limit_expiry/input.json
    - tests/fixtures/phase6/limit_partial_fill/input.json
    - tests/fixtures/phase6/limit_touch_no_fill/input.json
    - tests/fixtures/phase7/parity_overlapping_history/input.json

key-decisions:
  - "simulator.py is now a 60-line entry point: run calls engine.simulate(case_input, risk_fn=evaluate_risk, minute_source=minute_source) and nothing else; the v1 per-bar loop, entry state machine, resolve_intrabar, single-exit TP1 path, bar-direction invalidation heuristic and the fixture-clock expiry alias are deleted (D-01, D-04, D-35)"
  - "All seven phase6 cases keep their directory names but change semantics to fit the v2 lifecycle (fill needs a one-tick trade-through; expiry, touch, invalidation and fallback are judged by simulated minutes and bars). limit_touch_no_fill no longer uses partial_fill_fraction 0: it is three exact-limit touches that expire (touch_no_fill_count 3); limit_partial_fill continues into TP1 and TP2"
  - "Cases that need a strategy bar N+1 (intrabar_missing_fallback, invalidation_cancels_entry) carry bar 250 as an extra 1H row; the strategy fires a fresh setup at that close, so each of the two outputs holds a second PENDING_AT_DATA_END record. Eight bar shapes were tried and all produced it, so it is asserted, not avoided"
  - "invalidation_cancels_entry has a 1m data hole from 10:50: a real fall through the limit would fill the plan before the bar could invalidate it, so the case is a synthetic snapshot of the fill, then invalidation, then expiry precedence and is labelled so"
  - "Phase6 outputs are regression snapshots, not goldens: no expected.json is kept, each case pins its scenario tuple and a sha256 of the whole output in tests/test_backtest_simulator.py"
  - "Paper parity keeps a single-signal history on which the ledger never binds (D-18, RESEARCH Q7); the paper replay builds its input from the v2 case, stamping the constraint row with each bar close and ttl 0 as the engine does, and the test asserts the property explicitly (D052 input)"
  - "v2 filled records carry modeled_costs_per_unit = None, so the cost-parity tests read the sizing figure from the evaluate_risk verdict (logged in deferred-items.md); experiment._trade_from_dict leaves the v2 trailing fields as strings until plan 14-15"

patterns-established:
  - "Test migration inventory in the module docstring: every deleted v1 test names the test that replaces it"

duration: about 70 min
completed: 2026-10-05
status: complete
---

# Phase 14 Plan 12: Switch the Entry Point to the v2 Engine and Regenerate the Phase 6 Fixtures Summary

**`simulator.run` is now a thin shell over the event-loop engine (module-global `evaluate_risk` looked up at call time), the v1 per-bar code is gone, and the phase 6 generator emits ten v2 cases whose 1m trade and mark minutes start at bar N+1, with every old fixture relabelled a regression snapshot and every consumer suite migrated.**

## Accomplishments

- Retired `src/backtest/simulator.py`'s v1 body (about 1,000 lines). `run` returns `engine.simulate(case_input, risk_fn=evaluate_risk, minute_source=minute_source)`; `evaluate_risk` stays a module-level import, so `monkeypatch.setattr(src.backtest.simulator, "evaluate_risk", ...)` intercepts every risk call (proven by `tests/test_backtest_simulator.py` and `tests/test_paper_parity.py`; a mutation that captured the function at import made nine tests fail, then was restored).
- Rewrote `scripts/gen_phase6_fixtures.py`. Same 1H/4H geometry as Phase 12; new: `backtest-case/2` schema, `symbols`, `constraint_history` (observed 2026-09-01, before the 2026-09-11 00:00 data start), funding rows from 2026-09-10 16:00 to 2026-09-12 00:00 (8 h cadence), `data_window`, empty `allowed_gaps`, and trade and mark minutes from 10:00:00, the first minute after the 09:59:59 trigger close (D-24, F-602). Running it twice leaves `git status` unchanged; the geometry test also compares committed bytes with a temp-dir run.
- Scenarios (all hand-checked against the planner output: LONG zone 120.4586 to 122.5414, limit 121.50, stop 121.1529 snapped to 121.2, TP1 125.60, TP2 129.70, tick 0.10; sized 32.071 at equity 10000):
  - `intrabar_both_touched`: fills 10:05:59, stop at 10:06:59 at 121.20 (stop first beats TP1). SHORT mirror: limit 128.50, stop trigger 128.80.
  - `intrabar_missing_fallback`: mark hole from 10:06, bar 250 range touches the stop, SL at 121.20 resolved at 10:59:59, `fallback_applied`, coverage note names 10:06.
  - `limit_touch_no_fill`: three minutes with low exactly 121.50, EXPIRED 13:59:59, `touch_no_fill_count` 3.
  - `limit_partial_fill`: fraction 0.5, fill 16.035 of 32.071, TP1 8.017 at 125.60, TP2 at 129.70 at 10:07:59.
  - `limit_expiry`: never reached, EXPIRED 13:59:59. `invalidation_cancels_entry`: INVALIDATION_CANCEL at 10:59:59.
  - baselines: `no_trade` is a first-class RR_TOO_LOW REJECT (the baseline keeps filled trades, so still empty); `simple_trend` fills at 10:05 and stops at 10:06 (quantity 20.598).
- Migrated tests. `test_phase6_fixture_geometry.py` parses cases with `parse_case_input` and adds the minute-after-signal-bar, funding-coverage, v2-schema and "v1 code is gone" assertions. `test_backtest_simulator.py` was rewritten: one scenario test per case, one regression-snapshot digest per case, run-twice, junk minute inside the signal bar and after the data end changing nothing, parse refusals, binding refusals, delegation seam, `minute_source` precedence, and end-to-end cost arithmetic recomputed from literal rates (including a TP ladder: gross 98.6173). `test_cost_parity.py` adds per-leg parity (entry, TP1, final leg) against hand arithmetic through `simulate_detailed` bookings. `test_paper_parity.py` builds the paper input from the v2 case and asserts the ledger never binds. `test_backtest_experiment.py` adds baseline, reproduce and verify_experiment tests on the v2 engine (stored digest match, forged digest, changed minute series).
- Verification: geometry, engine, simulator, cost parity, paper parity, experiment, binding, report, decision-alignment bookkeeping, sl-loss property, case-input builder suites pass; the 148 test files that touch `src.core`, `src.backtest`, `src.risk`, `src.domain`, `src.paper`, `src.analytics`, `src.data` (plus all `test_analytics_*`, `test_paper_*`, `test_fixture_harness`) pass with `tests/test_analytics_cli.py` excluded, and 18 further files (decision alignment, execution, adapter strictness, domain no-float, others) pass; `ruff check`, `ruff format --check` (401 files) and `mypy src` (146 files) are clean. `tests/test_analytics_cli.py` still has exactly its 31 known failures (deferred to 14-15 Task 3). The deploy, docker, backup, PG and universe-freeze files were not run (known crash on a full-suite run; none touches this plan).

## Task Commits

1. **Task 1 (tracer)**: `8f0c498` (test, RED: 36 geometry tests failed on the v1 fixtures and the v1 helpers still existing), `de8829d` (feat, GREEN: simulator, `__init__`, generator, ten regenerated inputs)
2. **Task 2**: `615bf23` (test: simulator, cost-parity and paper-parity suites, `REGRESSION_SNAPSHOTS.md`)
3. **Task 3**: `d6acf89` (test: experiment baselines, reproduce, verify_experiment)

Plan metadata commit (SUMMARY, STATE, ROADMAP, REQUIREMENTS, deferred-items) follows this file.

## TDD Gate Compliance

Task 1 has a real RED: `8f0c498` rewrote the geometry guard to expect v2 cases (it failed 36 tests on the v1 fixtures: parser refusal of removed keys, `limit_touch_no_fill` partial fraction, v1 helpers present), then `de8829d` made it pass. `gsd_run check tdd-red-evidence` was not run.

Tasks 2 and 3 have NO independent RED, and cannot: they migrate tests of behavior that Task 1 and plan 14-08 already implemented, so the new tests passed on first run. To show they are not vacuous I mutated `simulator.run` to capture `evaluate_risk` at import (nine tests failed, including the paper parity spy and the cost-parity call-site test), then restored it; the geometry RED covers the fixture side; the drift test in `test_backtest_experiment.py` changes a minute and expects `ExperimentReproducibilityBroken`; and `test_minutes_inside_the_signal_bar_are_never_examined` poisons the series with a junk fill and stop minute. The plan tasks 2 and 3 are `type="auto"` without `tdd="true"`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Phase 7 root override in the generator**
- **Found during:** Task 1
- **Issue:** The determinism test overrode only `FIXTURE_ROOT`, so `main()` wrote the phase 7 parity input to the real tree on both runs and the phase 7 byte-equality was never compared with a temp run.
- **Fix:** The test sets `generator.PHASE7_FIXTURE_ROOT` too and compares the temp output with the committed phase 7 file.
- **Files modified:** tests/test_phase6_fixture_geometry.py
- **Commit:** 8f0c498

**2. [Rule 1 - Bug] v2 records have no `modeled_costs_per_unit`**
- **Found during:** Task 2
- **Issue:** The v1 cost-parity assertions read `trade["modeled_costs_per_unit"]`; v2 filled records carry `None` (`records.py` line 318), so the test would have compared against nothing.
- **Fix:** The tests read the sizing figure from the verdict the engine received through a spy on the module-global `evaluate_risk` (this also exercises the seam). The gap itself is logged in `deferred-items.md` rather than changing the engine records, which no Phase 14 plan owns.
- **Files modified:** tests/test_backtest_simulator.py, tests/test_cost_parity.py
- **Commit:** 615bf23

**3. [Ordering] `tests/test_paper_parity.py` committed with Task 2, not Task 3**
- **Found during:** Task 2
- **Issue:** `tests/test_cost_parity.py` imports `_replay_paper_through_bars` from `test_paper_parity`; committing Task 2 first would leave its verify command failing at that commit.
- **Fix:** The paper parity migration rides in the Task 2 commit. Task 3 keeps the experiment tests and the broad run.
- **Commit:** 615bf23

**4. [Contract change] `limit_touch_no_fill` no longer uses `partial_fill_fraction` 0**
- v1 modeled touch-no-fill as a zero partial fraction. In v2 that value is a MIN_QTY_REJECT, and the plan's own wording ("limit touched but never traded through before expiry") describes the new case. The geometry test's `EXPECTED_PARTIAL_FILL` map now holds only `limit_partial_fill`.

**Total deviations:** 4 (1 blocking, 1 bug, 1 ordering, 1 contract). **Impact:** none on hashes, params or the engine; one gap logged for 14-15/14-16.

## Issues Encountered

- A shell heredoc containing apostrophes fails in this tool (seen in 14-08 too); the edits were applied from `.py` script files and the Write tool.
- The first background run of the migrated suites started before the rewrite and showed the expected v1-era failures; they were re-run on the migrated files.
- Full `pytest -m "not docker"` was not run (coordinator instruction: known Windows access violation). The broad subset above stands in for it; no stray pytest processes remain.

## Regeneration inventory

No file under `params/` changed. `parameter_set_hash`, `cost_model_hash`, strategy version (v4.0.0) and every registry value are unchanged. `tests/fixtures/phase4/parameters.json` is untouched.

| Item | Old | New | Reason |
| --- | --- | --- | --- |
| `phase6/intrabar_both_touched/input.json` | sha256 9888a4c308f2, 163,056 B; keys `intrabar_1m_map`, `constraint_snapshot`, `now_utc`, `ttl_seconds`, `open_positions`, `daily_loss_quote`; 60 minutes starting 09:00 (inside the signal bar) | cab7a96f7ee6, 185,302 B; `backtest-case/2`; minutes from 10:00 | v2 case, D-24, F-602 |
| `phase6/intrabar_both_touched_short/input.json` | 820296065ab8, 163,065 B | 1134395dece2, 185,311 B | same |
| `phase6/intrabar_missing_fallback/input.json` | f2883e93ee18, 144,514 B; intrabar value `null` | 63e49aed1acc, 170,804 B; mark hole from 10:06, extra bar 250 | missing 1m is now a mark hole resolved at the bar close |
| `phase6/invalidation_cancels_entry/input.json` | 575f51a22b14, 144,514 B; trigger bar rewritten to close at 122.50 (bar-direction heuristic) | 9e6545612410, 179,880 B; trigger bar unchanged, bar 250 closes 120.80, minute hole from 10:50 | invalidation is a bar close beyond the level at the next bar (D-05, D-35) |
| `phase6/limit_expiry/input.json` | 33bec9cc438c, 144,514 B; `now_utc` 260 h (fixture clock) | f97ef6020ba9, 288,262 B; 240 minutes to the 13:59:59 expiry | expiry judged against simulated minutes (D-04) |
| `phase6/limit_partial_fill/input.json` | 486c695e142f, 163,056 B; same path as both-touched | 642fad66ecd3, 185,302 B; fill then TP1 then TP2 | TP ladder replaces the single-exit TP1 (D-11) |
| `phase6/limit_touch_no_fill/input.json` | e9f326fde4de, 144,512 B; `partial_fill_fraction` "0" | 23ca8f614ab5, 288,262 B; fraction "1.0", three exact-limit touches | touch is counted, never terminal (D-07, D-34) |
| `phase6/baselines/no_trade/input.json` | 81a183f9d1ed, 163,065 B | 5a6d07f62b04, 185,311 B | v2 case |
| `phase6/baselines/simple_trend/input.json` | e2937d7bb351, 163,069 B | 72a313120818, 185,315 B | v2 case |
| `phase7/parity_overlapping_history/input.json` | 9888a4c308f2, 163,056 B | cab7a96f7ee6, 185,302 B (byte-equal to `intrabar_both_touched`) | v2 case |
| `phase7/parity_overlapping_history/expected.json` digest | d06c739aa73e0aec8033908086f25da78525ace4d422356a88fcfd4e2d4d3efe | unchanged (re-verified: engine and paper both produce it) | the digest is over `(signal_id, reason_code)` verdicts; the signal id, the OK reason and the one-verdict history did not move |
| `expected.json` parameter_set_hash 41ed39d4..., cost_model_hash 6d6c4e23..., trade_count 1 | | unchanged | no params or cost change |
| `phase6` per-case expected sidecars | none existed | none kept; REGRESSION_SNAPSHOTS.md added | D-25, F-608 |
| Pinned digest: `intrabar_both_touched` | v1 trades list (no pin) | 8361c7ee192ec0b3d845b618118b81d702bc7325961efb710ef65357983d41bb | new regression snapshot (whole output) |
| Pinned digest: `intrabar_both_touched_short` | no pin | 12ab88b86e5d676d53d486f71569cc32783752bb68117441811c61ef8dd2c6dc | same |
| Pinned digest: `intrabar_missing_fallback` | no pin | 8beeb6e4aee7ad546e259c4d8154fd4d4be1ed27b51f5dbea4492578adfb0dee | same |
| Pinned digest: `limit_touch_no_fill` | no pin | 3d97433276538773911a9873f07760497f2c94dd6b7501201450af1488a73812 | same |
| Pinned digest: `limit_partial_fill` | no pin | a51dfcddef59c29711e12a43bc1ae18269d8ecbab220ea8ace08d3c4b69969db | same |
| Pinned digest: `limit_expiry` | no pin | f4a1733a2162d95430c8216792b672a6afda3eb77978becfdcca0bf1a3a3cf1c | same |
| Pinned digest: `invalidation_cancels_entry` | no pin | 76856083699f1bac96d423336fc9c258282acd693ef9ccca4d0c876c587b9fcb | same |
| Scenario outcomes | TOUCH_NO_FILL (fraction 0); PARTIAL_FILL with TP1 whole-position exit; SL via `intrabar_1m_map`; EXPIRED by fixture clock; INVALIDATION_CANCEL by a bar closing against the direction | EXPIRED with 3 touches; PARTIAL_FILL then TP1 then TP2; SL from mark minutes (fill 10:05:59, exit 10:06:59); EXPIRED 13:59:59; INVALIDATION_CANCEL at 10:59:59 | v2 lifecycle semantics |
| `EXPECTED_PARTIAL_FILL` in the geometry test | `limit_touch_no_fill: "0"`, `limit_partial_fill: "0.5"` | `limit_partial_fill: "0.5"` only | see deviation 4 |
| Public API | `IntrabarOutcome`, `SimulatorResult`, `resolve_intrabar` exported from `src.backtest` | removed; `simulate` exported | D-01 |
| `phase6/registry_identity`, `phase6/report_slices` | | untouched (not simulator inputs; used by experiment and report tests) | named in REGRESSION_SNAPSHOTS.md |

Paper-parity choice for D052: the parity fixture is a single-signal history (one plan, no resting entry, no open position, no daily loss) on which the engine ledger never binds, so the stateless paper verdicts and the engine verdicts stay comparable. `_assert_ledger_never_binds` (at most one OK verdict, no DAILY_STOP reason or cancel, no conflict skip, no exhausted-equity skip) runs in the digest test and the documentary-fields test. The paper replay stamps the constraint snapshot with each bar close and uses ttl 0, as the engine does (`select_constraints`, D-17). A multi-signal history would diverge by design because paper has no ledger; closing that gap would be a paper-loop change outside this phase.

## Known Stubs

None.

## Threat Flags

None. T-14-24 (v1 keys refused by `case.py`, regenerated inputs carry the v2 schema literal, geometry test asserts minutes start after the trigger bar, relabel file marks regression snapshots) and T-14-25 (the seam resolves `evaluate_risk` from simulator globals at call time; the paper parity spy and the delegation test assert interception) are mitigated as planned.

## Next Phase Readiness

Plan 14-15 types the v2 trailing fields in `_trade_from_dict`, bumps the evidence schema and fixes the 31 `tests/test_analytics_cli.py` failures. Plans 14-13 and 14-14 add the hand-derived goldens under `tests/fixtures/phase14` that the relabel file points to. The two cases that carry a follow-up PENDING_AT_DATA_END record and the `modeled_costs_per_unit` gap are in `deferred-items.md`.

## Self-Check: PASSED

Created and modified files exist on disk (generator, simulator, REGRESSION_SNAPSHOTS.md, the ten regenerated inputs, the five migrated test files); commits `8f0c498`, `de8829d`, `615bf23` and `d6acf89` are in `git log`; the acceptance commands re-ran green (no `resolve_intrabar` or `_resolve_entry` attribute, `backtest-case/2` in the both-touched input, `from src.risk.gating import evaluate_risk` in the simulator, a second generator run leaves `git status` unchanged, no `params/` path in the diff, `src.backtest.simulator.evaluate_risk` literal in the paper parity test, twelve lines with "regression snapshot" in the note, no deleted helper name imported by the simulator test).
