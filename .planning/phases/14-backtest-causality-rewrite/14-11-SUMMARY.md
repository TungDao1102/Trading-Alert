---
phase: 14-backtest-causality-rewrite
plan: 11
subsystem: backtest
tags: [backtest, analytics, report, validator, evidence-chain, regime, plateau, tdd, decimal]

requires:
  - phase: 14-backtest-causality-rewrite
    provides: "14-01 validate_trade_record, TradeRecord v2 fields, semantics vocabularies; 14-08 engine.simulate; 14-09 regime on records and typed run_summary"
provides:
  - "src/analytics/inputs.py: normalize_backtest runs validate_trade_record on every record and re-raises a violation as AnalyticsInputError chained from TradeRecordInvariantError"
  - "src/analytics/lifecycle.py: DAILY_STOP_CANCEL and PENDING_AT_DATA_END accepted as unfilled entry kinds"
  - "src/analytics/excursion.py: take-profit diagnostic group holds TP1 and TP2 exits"
  - "src/backtest/report.py: closed-trade counting, end_of_data_count, plan_outcome_counts, fixed NOT_COMPUTED plateau section, intrabar closed/END_OF_DATA totals"
  - "tests/test_backtest_chain.py: engine.simulate -> normalize_backtest -> compute_trade_excursion integration proof"
  - "tests/phase10_helpers.py: make_trade_record accepts every v2 TradeRecord field and derives valid signal_close_utc / planned_quantity"
affects: [14-12, 14-13, 14-15, 14-16]

actuals:
  tokens: 32000
  tasks: 3
  commits: 6
plan_head_before: 1a3d5ced679fe4fb40020dee7e285ed7b435e548
plan_head_after: 219eba0aa64d58f5599511a4a8ec91eafb6597a2

tech-stack:
  added: []
  patterns:
    - "Boundary re-validation: the shared window-independent trade validator runs again at the analytics normalizer, so a record that bypassed the builder is still refused (D-23, F-804)"
    - "Report population split: closed filled trades (SL, TP2) feed every statistic, END_OF_DATA trades and non-fill plan outcomes are counted apart, and a filled record with an unknown exit kind is refused rather than guessed"
    - "A section that has no evidence yet is a fixed NOT_COMPUTED structure, not an empty analysis"

key-files:
  created:
    - tests/test_backtest_chain.py
    - .planning/phases/14-backtest-causality-rewrite/deferred-items.md
  modified:
    - src/analytics/inputs.py
    - src/analytics/lifecycle.py
    - src/analytics/excursion.py
    - src/backtest/report.py
    - tests/phase10_helpers.py
    - tests/test_backtest_report.py
    - tests/test_analytics_lifecycle.py
    - tests/test_analytics_excursion.py
    - tests/test_analytics_report.py
    - tests/test_analytics_sidecar.py
    - tests/fixtures/phase6/report_slices/input.json
    - tests/fixtures/phase6/report_slices/expected.json
    - tests/fixtures/phase10/ (9 input.json, 3 expected.json, 3 render_golden files; see inventory)

key-decisions:
  - "A filled report record (outcome OK, entry ENTRY_FILLED or PARTIAL_FILL) whose exit_kind is not SL, TP2 or END_OF_DATA raises ReportBuildError. The plan said everything else is counted by entry_kind; a v1 TP1 or EOD record (or a filled record with no exit) has no safe meaning in a v2 report, so it fails closed instead of being silently counted as a plan outcome"
  - "PlateauSection is reduced to two fields (status NOT_COMPUTED, note 'not computed (BKTS-03 pending)'); PlateauRegion and the isolated-optimum warnings are deleted, so no input can produce a region or an optimum claim. parameter_region stays in the fixture as inert input"
  - "IntrabarCoverage keeps total_trades (now closed + END_OF_DATA, the filled population) and adds closed_trades and end_of_data_trades so both totals are stated"
  - "Fixture TOUCH_NO_FILL entries become INVALIDATION_CANCEL (still unfilled, expired_without_fill False) and TP1 exits become TP2 on backtest evidence only; live_net_r expectations keep TP1 because live outcomes model the TP1 order role"
  - "make_trade_record derives signal_close_utc (entry minus one hour) and planned_quantity (= quantity) only when the record filled and the caller did not pass them, so a default filled record satisfies validate_trade_record while an explicit override can still build an invalid record for negative tests"
  - "The report_slices zero-R trade_004 (was an EOD exit) is now a breakeven SL: an END_OF_DATA trade would leave the pool, and the golden needs a closed trade with R exactly 0"

patterns-established:
  - "Chain tests rebuild TradeRecord objects from engine output dicts with a local converter until plan 14-15 supplies the shared one"

requirements-completed: [BKTS-04, DOMN-03, BKTS-01]

duration: about 1 h
completed: 2026-10-05
status: complete
---

# Phase 14 Plan 11: Evidence Chain, Closed-Trade Report and Plateau Suppression Summary

**The v2 records now flow engine -> validated normalizer -> excursion with no NEGATIVE_INTERVAL, analytics speaks the v2 entry/exit vocabulary, and the report counts only closed SL/TP2 trades (END_OF_DATA and non-fills counted apart) with regime slices and a fixed "not computed (BKTS-03 pending)" plateau section.**

## Accomplishments

- **Validated boundary (F-804, D-23).** `normalize_backtest` calls `validate_trade_record(trade)` (no window) for every record and re-raises a `TradeRecordInvariantError` as `AnalyticsInputError` (`raise ... from error`, the message names the trade id). Tests: entry at its own `signal_close_utc` and exit before entry are both refused with the validator error as `__cause__`.
- **Integration tracer.** A five-symbol scripted case (BTC stop-out, ETH TP1 then TP2, ADA EXPIRED, SOL END_OF_DATA, LTC risk REJECT) runs through `engine.simulate`; the output dicts are rebuilt into `TradeRecord`s, normalized (LTC becomes a `NoTradeRecord`, four `TradeOutcome`s), and `compute_trade_excursion` over the three filled outcomes with the mark minutes returns `incomplete_reason is None` for all of them; `build_excursion_section` reports no `NEGATIVE_INTERVAL` and `n_measured == 3`. Tracer gate: the verify command was re-run after GREEN, passed, expansion continued.
- **v2 analytics vocabulary.** Lifecycle unfilled kinds add `DAILY_STOP_CANCEL` and `PENDING_AT_DATA_END` (`TOUCH_NO_FILL` kept for old evidence; an unknown kind still raises). The excursion take-profit diagnostic group is `exit_kind in {"TP1", "TP2"}` (TP1 stays for live outcomes, TP2 is the v2 backtest take profit).
- **Report (D-34, D-37, D-21).** `build` splits records through `_classify`: closed filled trades (SL or TP2) feed `trade_count`, the R distribution, bootstrap, drawdown, stability, baselines, the by-symbol/quarter/regime/version slices and the dual-universe slices; END_OF_DATA trades are counted in `end_of_data_count` and kept out of the pooled R; non-fills are counted by `entry_kind` in `plan_outcome_counts` (sorted). Forty EXPIRED plans alone give `trade_count == 0` and no interval. `counts_by_regime` is keyed by each closed trade's `regime` (UNKNOWN only for None). The plateau section is `PlateauSection(status="NOT_COMPUTED", note="not computed (BKTS-03 pending)")` for every input. Intrabar coverage counts fallback over closed and END_OF_DATA trades and states both totals (`closed_trades`, `end_of_data_trades`).
- **Phase 10 helpers.** `make_trade_record` accepts all eleven v2 fields (Decimal and datetime overrides parsed) and derives valid `signal_close_utc` and `planned_quantity` for filled records. Backtest fixtures moved to the v2 vocabulary and every moved pin was regenerated (inventory below).

## Task Commits

1. **Task 1 (tracer)**: `0877c39` (test, RED: 6 failures on the target assertions, validator not raised, TP2 group empty, DAILY_STOP_CANCEL and PENDING_AT_DATA_END unknown), `2d46b64` (feat, GREEN)
2. **Task 2**: `49d7240` (test, RED: 7 failing tests), `84e5737` (feat: report, v2 fixture, regenerated digest)
3. **Task 3**: `fe31a9a` (test, RED: new helper tests fail on unknown override fields and missing signal_close_utc), `219eba0` (feat: helpers, fixtures, regenerated pins)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Phase 10 JSON fixtures and four extra test files carried v1 vocabulary**
- **Found during:** Task 3
- **Issue:** With the boundary validator active, every analytics test that normalizes a backtest record with `exit_kind` TP1 or `entry_kind` TOUCH_NO_FILL (about 110 tests across render, sidecar, report, digest, slices) raised. The plan only listed the lifecycle and excursion test modules.
- **Fix:** 9 backtest `input.json` fixtures: `exit_kind` TP1 -> TP2, `entry_kind` TOUCH_NO_FILL -> INVALIDATION_CANCEL; `tests/test_analytics_excursion.py` (two parametrized TP1 -> TP2), `tests/test_analytics_report.py` (one record), digest pins and goldens regenerated (see inventory). No assertion weakened.
- **Files modified:** see key-files, `tests/test_analytics_sidecar.py` (stem pin)
- **Commit:** 219eba0

**2. [Interpretation] filled record with a non-v2 exit kind is refused by the report (see key-decisions)**
- **Commit:** 84e5737

**Total deviations:** 1 auto-fixed (blocking), 1 documented interpretation. **Impact:** none on source semantics beyond the plan; the fixture and pin moves are inventoried below.

## Deferred Issues

- **`tests/test_analytics_cli.py` (31 tests) fails until plan 14-15 Task 3.** Cause: the CLI loads backtest trades via `src/adapters/analytics_files.py` and `experiment._trade_from_dict`, which still build v1-shaped records from `tests/fixtures/phase10/loaders/evidence_sample.json` (exit TP1, entry TOUCH_NO_FILL, no `signal_close_utc`); since this plan `normalize_backtest` validates, and the CLI prints `trade 'T-1' violates a record invariant`. Plan 14-15 owns the loader field fan-out, the `analytics-evidence/2` bump and the sample regeneration, and its Task 3 verify runs `tests/test_analytics_cli.py`; pulling that forward would duplicate it. Logged in `deferred-items.md`. `tests/test_analytics_files.py` and `tests/test_analytics_store.py` pass.

## TDD Gate Compliance

All three tasks have a separate RED commit before GREEN. Task 1 RED: the chain integration assertions that depend on the new behavior failed (validator not raised twice, TP2 take-profit group empty, two lifecycle kinds unknown) while the pure engine-flow assertions passed, i.e. the failing test was the target one. Task 2 RED: 7 target tests failed (counts fields missing, plateau structure, intrabar totals, v1 exit refused). Task 3 RED was produced by running the new helper tests against the original `tests/phase10_helpers.py` (restored from git, the GREEN helper kept in the scratchpad meanwhile): 2 failed on missing v2 fields; the third new test and the lifecycle kind-mapping extension passed because Task 1 already supplied the behavior. `gsd_run check tdd-red-evidence` was not run.

## Regeneration inventory

All digests were produced by running each test's own build path (scripts in the scratchpad), never typed. Old -> new:

| Pin | Old | New |
|-----|-----|-----|
| tests/fixtures/phase6/report_slices/expected.json `EXPECTED_REPORT_DIGEST` (D-25; input moved to v2 shapes: TP1 -> TP2, zero-R EOD -> breakeven SL, +1 END_OF_DATA, 2 EXPIRED, 1 INVALIDATION_CANCEL, 1 REJECT) | 864aab053fdbf82a435ab56c381f544f1ba3c08281ea249d3d97e9b3f033ee91 | 74bbcc50fb94ee1f24a41f72668f3a9c32df7889355c521b146e56b518f4a2ec |
| tests/fixtures/phase10/complete_trade/expected.json `section_digest` | 43a8c98e0007090bd81055c436ec8cadbdea30eb00e24519581973e35d654e8b | b0e9235da56080c83697d9a684ed0c3e94df8806150382578186326295513a70 |
| tests/fixtures/phase10/digest_regeneration/expected.json `section_digest` | 6d90c24b6313c8e67d2a56ac88cdaf2996849d0a8021aa990d7f0684823a0241 | aea2203563b427bd7aa6ef42ef90c61566cdad54e54037923ed2d21bda89b7c3 |
| tests/fixtures/phase10/report_composite/expected.json `report_digest` | 57bcaab6d328210b2484b20d98250c9b63e8d65628ffb68d8fb5e418744535ee | 2838cb3aa82744bee5ccf588c3e1ef5a0b9e20bb6e1814f4ca88dcfb4db33627 |
| tests/fixtures/phase10/render_golden/expected.md (one line: Report digest) | sha256:57bcaab6... | sha256:2838cb3a... (28392 bytes both) |
| tests/fixtures/phase10/render_golden/expected_sections_0_2.md (same line) | sha256:57bcaab6... | sha256:2838cb3a... (5758 bytes both) |
| tests/fixtures/phase10/render_golden/expected.json (sidecar golden: report digest and markdown_sha256) | derived from the old report | regenerated from `build_pair()` (43176 bytes both) |
| tests/test_analytics_sidecar.py file-stem pin | journal-depth-20270401T000000Z-57bcaab6d328 | journal-depth-20270401T000000Z-2838cb3aa827 |

Input fixtures changed (vocabulary only): `phase10/{complete_trade,digest_regeneration,empty_live5_slice,incomplete_no_1m,incomplete_no_fill,low_n_slices,report_composite,short_trade,zero_risk_excluded}/input.json` (TP1 -> TP2, TOUCH_NO_FILL -> INVALIDATION_CANCEL). Unchanged on purpose: `live_net_r/expected.json` (live TP1 order role) and `loaders/evidence_sample.json` (plan 14-15 regenerates it). Moves: the diffs of the three render goldens are exactly the digest line, so no number in them changed.

## Issues Encountered

- Heredocs containing apostrophes fail in the shell tool; larger edit scripts were written with the Write tool and run from the scratchpad.
- Per the environment policy the whole suite was not run (`pytest -m "not docker"` crashes on Windows in the deploy tests), so the plan's final verify line was not executed as written. Instead: `tests/test_analytics_*.py tests/test_r_denominator_parity.py tests/test_backtest_*.py tests/test_trade_record_validator.py tests/test_fixture_harness.py tests/test_domain_no_float.py tests/test_domain_boundary.py` (only the 31 deferred CLI tests failed), the targeted list `tests/test_analytics_{lifecycle,excursion,digest,report,slices,no_trade,incomplete,render,sidecar,files,store}.py tests/test_backtest_chain.py tests/test_backtest_report.py` (all passed, 2 pre-existing skips), and core/risk/paper/domain/quality-gate suites.
- `ruff check .`, `ruff format --check .` (400 files) and `mypy src` (146 files) are clean.

## Verification (real output)

- Task 1 verify `pytest tests/test_backtest_chain.py tests/test_analytics_purity.py`: all passed.
- Task 2 verify `pytest tests/test_backtest_report.py`: all passed (including the regenerated digest pin).
- Acceptance greps: `validate_trade_record` in `src/analytics/inputs.py`; `DAILY_STOP_CANCEL` and `PENDING_AT_DATA_END` in `src/analytics/lifecycle.py`; `NEGATIVE_INTERVAL` in `tests/test_backtest_chain.py`; `BKTS-03` and `END_OF_DATA` in `src/backtest/report.py`; `plan_outcome_counts` and `end_of_data_count` in `tests/test_backtest_report.py`; `signal_close_utc` and `funding_event_count` in `tests/phase10_helpers.py`.
- Not run (known environment crash): `pytest -m "not docker"`.

## Known Stubs

None.

## Threat Flags

None. T-14-22 (only closed filled trades count; END_OF_DATA and plan outcomes counted apart; v1 or unknown exit kinds refused) and T-14-23 (plateau section is a fixed NOT_COMPUTED structure naming BKTS-03, no regions computed) are mitigated and tested.

## Next Phase Readiness

Plan 14-12 can switch `simulator.run` to `engine.simulate`. Plan 14-15 must migrate the evidence loader and `evidence_sample.json` (it also turns `tests/test_analytics_cli.py` green again) and move `tests/test_backtest_report.py` / `tests/test_analytics_report.py` to the typed `ExperimentRecord` fields; `tests/test_backtest_chain.py::record_from_dict` is the local converter it should replace with the shared one.

## Self-Check: PASSED

`tests/test_backtest_chain.py` and `deferred-items.md` exist; commits `0877c39`, `2d46b64`, `49d7240`, `84e5737`, `fe31a9a`, `219eba0` are in `git log`; acceptance greps and the targeted verification commands re-ran green (full-suite and the 31 deferred CLI tests excepted, as documented).
