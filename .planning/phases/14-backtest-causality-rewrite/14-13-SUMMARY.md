---
phase: 14-backtest-causality-rewrite
plan: 13
subsystem: backtest
tags: [backtest, causality, golden-fixtures, hand-derived-oracle, generator, derivations, decimal, funding, ledger]

requires:
  - phase: 14-backtest-causality-rewrite
    provides: "14-08 engine.simulate and the case-input v2 scripted_plans front end; 14-12 simulator.run as the public entry point and the phase 6 generator pattern (1m data from bar N+1)"
provides:
  - "scripts/gen_phase14_fixtures.py: deterministic input-only generator (--out), minute builder that raises on any minute opening at or before the plan's bar close"
  - "tests/fixtures/phase14/: 16 golden case directories, each with input.json and a hand-written expected.json"
  - "tests/fixtures/phase14/DERIVATIONS.md: Common inputs, Formulas and one section per case with standalone Decimal checks"
  - "tests/test_backtest_goldens.py: runs simulator.run on every case and compares field by field (Decimal equality, parsed datetimes)"
  - "tests/test_phase14_fixture_generator.py: 12 meta-tests (rerun byte-identical, equals committed, input.json only, no project imports, minutes after the plan close, builder guard, hand-field whitelist, research-gate name and key traps)"
affects: [14-14, 14-15, 14-16]

requirements-completed: [DOMN-03]

actuals:
  tokens: 233039
  tasks: 3
  commits: 3
plan_head_before: 67544a0cc17e420a0372486aa45bf4e5554ef5e3
plan_head_after: b2981c71e56e6f8c7c6d6b284b9bcdd4cf946acb

tech-stack:
  added: []
  patterns:
    - "Golden oracle independence: expected.json is typed by hand from a DERIVATIONS section whose numbers come from a standalone python -c Decimal one-liner (no src, tests or scripts import); the generator can only write input.json"
    - "Mutation check instead of RED: patch one engine rule in-process, run the goldens, see exactly the matching case fail"
    - "Structural guard in the generator: the minute builder refuses a minute opening at or before the plan's bar close, so a case cannot place 1m data inside the signal bar"

key-files:
  created:
    - scripts/gen_phase14_fixtures.py
    - tests/test_backtest_goldens.py
    - tests/test_phase14_fixture_generator.py
    - tests/fixtures/phase14/DERIVATIONS.md
    - "tests/fixtures/phase14/<16 cases>/input.json and expected.json"
  modified: []

key-decisions:
  - "Goldens use scripted plans on round numbers (zone 99 to 101, stop 98, TP1 104, TP2 108; SHORT mirror with stop 102, TP1 96, TP2 92) so every number is hand-derivable; the strategy front end is not involved"
  - "expected.json lists a hand-chosen field subset per trade plus six run_summary counters, compared numerically; a coverage_note_contains key checks the fallback note without copying code text"
  - "daily_loss_blocks_next uses three sequential stop-outs on three symbols plus a resting fourth, not two stop-outs: a stop-out at the zone mid loses about 34, the aggregate cap (100) and max_open_positions (2) forbid more concurrent exposure, and the realized equity (hence every later quantity) shrinks after each loss"
  - "Synthetic funding instants a few minutes apart (10:20, 10:40; 10:02, 10:30, 10:50) cross two or three actual fundingTimes in a short hold; D-14 allows any actual instant, and the 8 h grid rows sit outside every hold"

patterns-established:
  - "Per-case DERIVATIONS section: plan, numbered arithmetic, a pasted standalone check, a Result line the expected.json copies"
  - "Fixture files are committed with LF; the byte-equality meta-test normalises CRLF because git on this Windows checkout (autocrlf=true) writes CRLF into the working tree"

duration: about 1.5 hours
completed: 2026-10-05
status: complete
---

# Phase 14 Plan 13: Hand-derived Golden Cases and the Input Generator Summary

**Sixteen goldens run through `simulator.run` against hand-written `expected.json` files whose numbers come from standalone Decimal arithmetic in `DERIVATIONS.md`; the generator writes `input.json` only and its minute builder cannot place 1m data inside the signal bar.**

## Accomplishments

- `scripts/gen_phase14_fixtures.py` (imports nothing from the project; `--out`, default `tests/fixtures/phase14`): one builder per case, sorted-key JSON with LF endings, byte-identical on rerun. `_minute_rows` raises `ValueError` for a minute whose open is at or before the plan's bar close and for an incoherent OHLC; `_single` and every multi-symbol builder go through it.
- Sixteen cases, all passing on their first run against the hand-written expectations (the engine and the independent arithmetic agreed everywhere, no expected value was edited after a run):
  - entry: `signal_bar_touch_no_fill` (signal bar high 101.5 and low 97.5 span the limit 100 and the stop 98, no fill or exit on that bar), `trade_through_vs_touch` (SHORT, two exact-limit touches then a one-tick trade-through), `gap_through_limit` (fill minute opens 1.5 below the limit, fill stays at 100.0);
  - expiry: `expiry_before_fill` (the 11:00 trade-through closes after the 10:59:59.999 expiry and is ignored), `g3_fill_before_expiry` (fill 11:20) and `g3_expire_after` (first reach 14:30, EXPIRED 13:59:59.999) with `signal_expiry_hours` 4;
  - exits: `hold_to_sl` (fill bar N+1, stop bar N+4), `tp1_then_tp2` (stop 98.50 makes the quantity 18.943 odd, so TP1 is floored to 9.471), `tp1_then_sl` (the stop does not move after TP1, R = 0.277), `stop_first_tie` (one mark minute reaches TP1 and SL, whole position stops);
  - funding: `funding_paid_received` (a LONG pays 1.608728 on the full size at +0.001 and receives 1.640584 on the post-TP1 remainder at -0.002, net +0.031856), `funding_between_times` (SHORT, instants 10:02 and 10:50 outside [entry, exit), only 10:30 charged, +0.787941);
  - ledger and data end: `daily_loss_blocks_next` (see deviation 1: three stop-outs of 34.0604352, 33.9449616 and 33.829488 reach 101.8348848 against the stop threshold 100, the resting DOGEUSDT entry ends DAILY_STOP_CANCEL at 12:10:59.999, the next signal is a DAILY_STOP_BLOCK reject, quantities shrink with the realized equity 15.928, 15.874, 15.820), `end_of_data` (END_OF_DATA at the last mark close 101.2, stop-style slippage), `missing_mark_fallback` (mark hole from 10:06, resolved once at the bar close 10:59:59.999, stop first, `fallback_applied`);
  - `nonzero_cost_parity`: SHORT with entry, TP1 and SL legs, each fee and slippage equal to price x leg quantity x rate (table in the section).
- `tests/test_backtest_goldens.py`: one parametrized test per case plus `test_cases_were_found` and `test_every_required_case_is_present`; amounts compare as Decimal, times as datetimes, so `98` and `98.00` never differ; every mismatch is listed with field, expected and actual.
- `tests/test_phase14_fixture_generator.py`: rerun byte-identical, committed inputs equal a fresh run (CRLF normalised), only `input.json` files are written and the case set equals the required set, no `src`/`tests`/`scripts` import in the generator, every committed minute opens strictly after its symbol's first plan close, the builder refuses minutes inside the signal bar (and an incoherent OHLC), every case has both files and a `## <case>` heading, the derivations file states the independence rule, expected.json holds hand-chosen fields only (no trade id or hash), no file or directory name starts with `experiment` or `backtest`, no JSON key is `parameters` or `parameters_json`.
- Verification: `gen_phase14_fixtures.py` then `pytest tests/test_backtest_goldens.py tests/test_phase14_fixture_generator.py` passes (30 tests: 16 goldens, 2 guards, 12 meta). `ruff check`, `ruff format --check` and `mypy` on the generator are clean. No `src/` file changed. The full `pytest -m "not docker"` run was not performed (coordinator instruction: known Windows access violation); `tests/test_analytics_cli.py` was not touched.

## Task Commits

1. **Task 1 (tracer)**: `3d7df26` generator (one case), DERIVATIONS.md skeleton and the signal-bar case, golden test
2. **Task 2**: `1c17da7` nine entry and exit cases with derivations and expected files
3. **Task 3**: `b2981c7` six funding, ledger, data-end, fallback and cost-parity cases plus the meta-tests

Plan metadata commit (SUMMARY, STATE, ROADMAP) follows this file.

## Derivation method and standalone checks

Every `expected.json` was typed by hand from the `Result` line of its DERIVATIONS section; nothing in the repository writes one. The numbers were computed with plain `python -c "from decimal import Decimal as D; ..."` one-liners that import nothing from `src/`, `tests/` or `scripts/`, then pasted into the section (all 15 one-liners in the file were re-run after writing and printed exactly the quoted values). The same command serves several cases:

| Case | Standalone check (section of DERIVATIONS.md) |
| --- | --- |
| signal_bar_touch_no_fill, hold_to_sl, g3_fill_before_expiry, stop_first_tie (and the sizing of expiry_before_fill, g3_expire_after) | LONG stop-out: `e=101, s=98` sizing, then gross, fees, slippage, pnl, R (quantity 15.928, pnl -34.0604352) |
| trade_through_vs_touch | SHORT stop-out: `e=99, s=102` (quantity 15.918, pnl -34.0899888) |
| tp1_then_tp2 | LONG `s=98.5`, TP1 floor of half, two exit legs (quantity 18.943, pnl 111.318644) |
| tp1_then_sl | LONG TP1 then the unchanged stop (pnl 13.8509888) |
| gap_through_limit | LONG TP1 then TP2 in one minute (pnl 93.5992992) |
| funding_paid_received | the TP1+TP2 command plus `f1=-q*101*0.001`, `f2=-b*103*(-0.002)` (funding +0.031856, pnl 93.6311552) |
| funding_between_times | SHORT stop-out plus `f=q*99*0.0005` (funding +0.787941, pnl -33.3020478) |
| daily_loss_blocks_next | equity chain `q1,q2,q3` and day-loss sum (15.928, 15.874, 15.820, loss 101.8348848), then the per-trade legs lambda |
| end_of_data | LONG exit at `x=101.2` with stop-style slippage (pnl 16.86838912) |
| missing_mark_fallback | LONG `s=98.5` stop-out (pnl -31.0437884) |
| nonzero_cost_parity | SHORT TP1 96 then SL 102 (pnl 13.8550272) |

The commands themselves are in the corresponding `## <case>` section of `tests/fixtures/phase14/DERIVATIONS.md`.

## TDD Gate Compliance

None of the three tasks carries `tdd="true"` and none has an independent RED commit, and none can: the code under test (plans 14-01 to 14-12) already exists, so a new oracle can only pass or expose a bug, and all sixteen passed on the first run. To prove the goldens are not vacuous I mutated one engine rule at a time in-process (nothing was written to `src/`), ran `tests/test_backtest_goldens.py`, and recorded which case failed: stop-exit slippage rate swapped for the entry rate (the tracer case failed), trade-through replaced by touch (`trade_through_vs_touch`), expiry ignored (`expiry_before_fill`, `g3_expire_after`), TP1 fraction 0.4 (`tp1_then_tp2`, `tp1_then_sl`, `gap_through_limit`), TP before stop (`stop_first_tie`), funding sign flipped (`funding_paid_received`, `funding_between_times`), fallback disabled (`missing_mark_fallback`), DAILY_STOP cancel disabled (`daily_loss_blocks_next`), END_OF_DATA slippage swapped (`end_of_data`). `gsd_run check tdd-red-evidence` was not run. The generator guard is covered by `test_minute_builder_refuses_a_minute_inside_the_signal_bar`, which fails if the guard is removed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `daily_loss_blocks_next` needs three stop-outs, not two**
- **Found during:** Task 3 design
- **Issue:** The plan text says two stop-outs on two symbols reach the stop threshold. With the zone mid as the fill price and the sizing at the adverse edge, one stop-out loses 34.06 (about 0.34 percent of equity), so two reach only 68; the single-trade cap (50 per symbol), the aggregate cap (100) and `max_open_positions` 2 also forbid a larger or a third concurrent exposure. A point zone or a deep stop gap would have reached 100 but would hide the mechanism behind an unrealistic plan.
- **Fix:** Three sequential stop-outs (ADAUSDT, BNBUSDT, LTCUSDT) with the resting DOGEUSDT entry alive throughout and a fifth signal (ADAUSDT) after the stop. Because the engine sizes on the realized equity, B and C are smaller (15.874, 15.820); the derivation carries the equity chain and a standalone check.
- **Files modified:** scripts/gen_phase14_fixtures.py, tests/fixtures/phase14/DERIVATIONS.md, tests/fixtures/phase14/daily_loss_blocks_next/*
- **Commit:** b2981c7

**2. [Interpretation] expected.json carries a `coverage_note_contains` key and a six-counter run summary**
- The plan lists the record fields and "the relevant run_summary counts". Every expected.json pins the six counters (`end_of_data_count`, `fallback_count`, `gap_through_stop_count`, `pending_at_data_end_count`, `touch_no_fill_total`, `no_trade_counts`); the fallback case checks the coverage note by the substring `mark_price_1m_missing_from_2026-01-05T10:06:00`, which names the first missing minute (derived, not copied from code output).
- **Commit:** 1c17da7, b2981c7

**3. [Scope] full-suite verification not run**
- The plan's second verification line is the whole `pytest -m "not docker"`; the coordinator forbids it (known Windows access violation). The two new files, `ruff` and `mypy` on the generator ran instead. No `src/` or other test file was edited.

**Total deviations:** 3 (1 blocking-adaptation, 2 interpretation or scope). **Impact:** none on any source, hash or registry value.

## Issues Encountered

- `git config core.autocrlf` is `true`, so the working tree holds CRLF for committed LF files. The generator writes LF bytes and git stores LF; the committed-equals-regenerated meta-test compares after CRLF to LF normalisation, while the two fresh generator runs are compared strictly.
- The first ruff pass flagged three docstrings over 100 columns in the generator; shortened.

## Regeneration inventory

None: every file in this plan is new (`scripts/gen_phase14_fixtures.py`, `tests/fixtures/phase14/**`, the two test modules). No existing fixture, hash, parameter set or `params/` file changed; `parameter_set_hash`, `cost_model_hash` and the strategy version are untouched.

## Known Stubs

None.

## Threat Flags

None. T-14-26 (golden expectations repudiated or self-fulfilling) is mitigated as planned: expected.json is hand-written from DERIVATIONS with standalone checks, the generator writes input.json only (meta-test), and the minute builder refuses signal-bar minutes (meta-test, builder test). T-14-SC: no package installs.

## Next Phase Readiness

Plan 14-14 can add its own cases under `tests/fixtures/phase14` with the same generator and derivations pattern (the required-case tuple in `tests/test_backtest_goldens.py` and `CASES` in the generator are the two places to extend, plus a `## <case>` heading). Plans 14-15 and 14-16 are unaffected; the deferred `tests/test_analytics_cli.py` failures (14-15 Task 3) were not touched.

## Self-Check: PASSED

Files exist: `scripts/gen_phase14_fixtures.py`, `tests/test_backtest_goldens.py`, `tests/test_phase14_fixture_generator.py`, `tests/fixtures/phase14/DERIVATIONS.md` and 16 case directories each with `input.json` and `expected.json`. Commits `3d7df26`, `1c17da7` and `b2981c7` are in `git log`; `git rev-list --count 67544a0..HEAD` is 3. The acceptance greps passed (`never from the output of the code under test` and `## signal_bar_touch_no_fill` in DERIVATIONS.md, `parameters_json`, `"experiment"` and `"backtest"` in the generator meta-test, 16 case directories with both files).
