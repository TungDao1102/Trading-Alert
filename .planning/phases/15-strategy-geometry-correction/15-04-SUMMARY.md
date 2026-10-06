---
phase: 15-strategy-geometry-correction
plan: 04
subsystem: strategy-core
tags: [geometry, validator, family-a, tdd, hand-derived, p9, F6]

requires:
  - phase: 15-strategy-geometry-correction
    provides: "15-03 pivots, geometry_version gate, Family A pivot geometry, registry keys"
provides:
  - "src/core/planner.py: _geometry_rejection (D-06, D-07, D-08, F6 in a fixed order) with its single call site in plan()"
  - "RR and TP2 RR computed from the signed profit-side leg"
  - "Family A SHORT, opposite-pivot TP1, missing-pivot, audit-anchor, p9 and detection tests pinned to hand-derived values"
affects: [15-05, 15-06, 15-08, 15-13, 15-14]

actuals:
  tokens: 11750
  tasks: 3
  commits: 4
plan_head_before: 2ffa3f84b5322e5bf45acf9be75349ec66662c91
plan_head_after: e1904034e7f7b162b9b15c26a567f57fccc6a4fa

tech-stack:
  added: []
  patterns:
    - "One private validator, one call site, fixed check order with existing RejectionReason values only; an AST test pins the single call"
    - "Affine rescaling of a hand-derived constant-range window (close' = half*close + offset) keeps every ratio of the derivation at another price scale"

key-files:
  created:
    - tests/test_core_strategy_geometry.py
  modified:
    - src/core/planner.py
    - tests/geometry_builders.py
    - tests/test_planner_geometry.py
    - tests/fixtures/phase15/DERIVATIONS.md
    - tests/fixtures/phase15/geometry_cases.json

key-decisions:
  - "The validator runs only for sets that carry geometry_version (all of Family A's new path; B and C keep the legacy path until their own plans, and 15-13 makes it universal)"
  - "The call sits before the risk <= 0 guard, so a stop at entry_ref is STOP_TOO_TIGHT rather than RR_TOO_LOW"
  - "TP1 'beyond the entry zone' (handoff from 15-03) is NOT added: the plan fixes check 4 as 'strictly on the profit side of entry_ref'; recorded as a deferred observation below"

requirements-completed: [STRAT-01, STRAT-02]

duration: ~45min
completed: 2026-10-06
status: complete
---

# Phase 15 Plan 04: Shared Geometry Validator and Family A Completion Summary

**`_geometry_rejection` is now the single place for the plan invariants (stop outside the whole zone, signal bar not through the stop, optional ATR floor, TP1 on the profit side), runs in that fixed order before the RR gate, and Family A is pinned by hand-derived LONG, SHORT, audit-anchor (stop 59,680 below entry_min 59,760; 58,760 below 58,820) and p9 cases.**

## TDD record

The plan is `type: tdd`; RED then GREEN for the tracer, then test-first tasks 2 and 3. `gsd_run check tdd-red-evidence` only parses node:test TAP and Surefire XML, so it cannot classify pytest output; RED evidence is recorded by failing test names (same note as 15-02 and 15-03).

**Task 1 (tracer)**
- RED `56d7818`: 17 failing tests. Direct validator tests failed with `AttributeError` (the function did not exist yet; the test module reaches it through `planner_module._geometry_rejection` so collection still succeeds). The through-plan tests failed on behavior: `test_tp_loss_side_through_plan_even_with_a_tiny_minimum_rr` got a READY plan (abs() accepted pivot high 105.00 below entry_ref 106.00), `test_stop_inside_zone_through_plan_with_zero_stop_buffer` and `test_min_stop_atr_through_plan` got plans, `test_order_through_plan_stop_inside_zone_wins_over_rr` got `OK`. The AST test found 0 calls.
- GREEN `fd17050`: `_geometry_rejection` plus the single call after quantization. Tracer gate: `<verify>` re-run end to end after GREEN (`test_planner_geometry`, `test_core_planner`, `test_core_tracer`: all green) before expanding.

**Task 2** `26135cd`: the new cases (a_short_worked, both audit anchors, missing opposite pivot, determinism) passed on their first run because the Task 1 validator and the 15-03 pivot geometry already implement the behavior. No src change was needed; the hand derivations were written before the expectations and the builders were checked against `recent_pivots` only for construction (not for expected values).

**Task 3** `e190403`: the seven strategy-level tests passed on first run for the same reason (no defect in `_detect_pivot_setup` or the dispatch was exposed). The p9 beyond-tolerance test also asserts that the legacy set still signals on the same window, which demonstrates the defect and the fix.

## Accomplishments

- `_geometry_rejection(*, direction, entry_min, entry_max, entry_ref, stop_loss, take_profit_1, atr, signal_low, signal_high, min_stop_atr) -> str | None`: (1) LONG `stop >= entry_min` / SHORT `stop <= entry_max` is STOP_TOO_TIGHT (D-06); (2) signal bar low `<=` stop (LONG) or high `>=` stop (SHORT) is INVALIDATED (D-07, touching counts); (3) `|entry_ref - stop| < min_stop_atr * ATR` is STOP_TOO_TIGHT when the key is present (D-08, equality passes); (4) signed TP1 leg `<= 0` is RR_TOO_LOW (F6). No enum member was added.
- `plan()` calls it exactly once (AST-tested), on the stored (quantized) prices, when `geometry_version(parameter_set)` is not None, before the risk guard and the RR gate (D-26). `min_stop_atr` is read with `params.get` and coerced with `Decimal(str(...))`.
- The RR gate and the persisted `tp2_rr` use the signed profit-side legs.
- Hand-derived cases (sections in `DERIVATIONS.md`, entries in `geometry_cases.json`): `a_short_worked` (entry 99.80-102.20, stop 102.60, TP1 94, TP2 87), `a_long_audit_60000` (entry 59,760-60,240, stop 59,680, TP1 61,400, TP2 62,800), `a_long_audit_59000` (entry 58,820-59,180, stop 58,760, TP1 60,050, TP2 61,100), `a_long_no_opposite_pivot` (signal, then STALE_SETUP at plan time), `tp_loss_side` and `p9_regression`.
- Strategy-level tests: no confirmed pivot is NO_TRADE_REGIME with regime BULLISH (not WARMUP_INSUFFICIENT); confirmation at t+R through `evaluate` (bar 248 cut gives no setup although its low is inside the zone, bar 249 signals); p9 beyond tolerance (low 96.00 vs P 99.00, no signal) and inside tolerance (low 98.20, signal, stop 97.40 below the bar low); warm-up distinct from no-pivot (199 bars WARMUP_INSUFFICIENT, 200 bars NO_TRADE_REGIME; fewer than 7 bars never yield a pivot); legacy set unchanged.

## Task Commits

1. Task 1 RED: `56d7818` test(15-04): add failing tracer for the shared geometry validator
2. Task 1 GREEN: `fd17050` feat(15-04): shared geometry validator before the RR gate with signed profit-side legs
3. Task 2: `26135cd` test(15-04): Family A SHORT, audit anchors, missing pivot and determinism against the sidecar
4. Task 3: `e190403` test(15-04): strategy-level Family A pivot detection, p9 regression and legacy path

## Derivation one-liners used

Independent `python -c` Decimal computations with no project imports, pasted with their output in `tests/fixtures/phase15/DERIVATIONS.md` per section. Core ones:

```
a_short_worked      python -c "from decimal import Decimal as D; H=D('200')-D('99'); h=D('0.5')*D('2'); zl=H-h; zu=H+h; eb=D('0.1')*D('2'); sb=D('0.2')*D('2'); emin=zl-eb; emax=zu+eb; print(H, zl, zu, emin, emax, emax+sb, (emin+emax)/2)"   -> 101 100.0 102.0 99.8 102.2 102.6 101.0
audit 60,000 / 400  ... print(zl, zu, emin, emax, (emin+emax)/2, emin-sb)   -> 59800.0 60200.0 59760.0 60240.0 60000.0 59680.0
audit 59,000 / 300  ... print(zl, zu, emin, emax, (emin+emax)/2, emin-sb)   -> 58850.0 59150.0 58820.0 59180.0 59000.0 58760.0
tp_loss_side        ... print(P, zl, zu, zl-eb, zu+eb, zl-eb-sb, ((zl-eb)+(zu+eb))/2) -> 106 105.0 107.0 104.8 107.2 104.4 106.0
p9_regression       ... print(zl, zu, emin, emax, ref, emin-sb, tp1-ref, (tp1-ref)/(ref-(emin-sb)), ref+2*(tp1-ref)) -> 98.0 100.0 97.8 100.2 99.0 97.4 3.5 2.1875 106.0
```

## Deviations from Plan

### Auto-fixed Issues

None. No Rule 1-4 fix was needed beyond the plan.

### Notes

**1. [Plan wording] RR now uses the signed leg for every set, not only geometry_version sets.** The plan's action says to compute realized RR and TP2 RR from the signed leg (identical whenever the leg is positive). That is applied unconditionally in `plan()`, so a legacy set whose TP1 sits on the loss side (never observed in any committed fixture) would now be RR_TOO_LOW instead of accepted through `abs()`. All legacy suites (`test_core_planner`, `test_core_tracer`, `test_backtest_engine_strategy`, `test_backtest_simulator`, `test_decision_alignment_params`, `test_prefix_invariance`, `test_no_lookahead`) pass unchanged, so the effect is confined to a case that was a defect (F6). Called out because the plan also says legacy output is byte for byte unchanged.

**2. [Placement] Tracer window builder lives in `tests/geometry_builders.py`.** The plan lists only `src/core/planner.py` and `tests/test_planner_geometry.py` for Task 1; the new loss-side window builder was added to the shared builders module (a file the plan lists for Task 2) because later cases reuse `window_from_closes`.

**3. [Interpretation] "Warm-up" test.** The behavior line ("fewer than pivot_left_bars + pivot_right_bars + 1 bars after the feature warm-up boundary") is ambiguous because pivots are scanned over the whole series, not from the warm-up boundary. Implemented as: below the 200-bar EMA warm-up the reason is WARMUP_INSUFFICIENT; at the first valid length with no pivot it is NO_TRADE_REGIME; and `pivot_at` returns None at every index of a 6-bar series.

**4. [Pre-existing, out of scope] `tests/test_phase6_fixture_geometry.py::test_generator_is_deterministic_and_matches_committed_fixtures` fails on this Windows checkout** (LF generator output vs CRLF working-copy fixtures). Content is identical after normalizing line endings. Logged in `deferred-items.md`; not caused by this plan.

## Observations for later plans (not fixed here)

- **TP1 "beyond the entry zone" is not enforced.** Check 4 compares TP1 with `entry_ref` (the plan's contract and F6). A TP1 on the profit side of `entry_ref` but still inside the far half of the entry zone would pass. This is the handoff observation from 15-03; the plan's stated invariants do not include it, so it was not implemented. If wanted, it is a one-line tightening in `_geometry_rejection` (LONG `take_profit_1 > entry_max`, SHORT `take_profit_1 < entry_min`) with its own hand-derived case; a user or 15-13 decision.
- **Only Family A passes through the validator.** Breakout-retest and range-mr sets carry `geometry_version` only after their own plans (15-05, 15-06) and 15-13 extends the call to every set (D-06).
- **No SHORT p9 mirror.** The p9 regression is LONG only; the SHORT mirror of the pivot detector is covered by `a_short_worked` through `evaluate` and `plan`.
- `_plan_geometry_is_valid` in `src/risk/gating.py` still accepts a stop inside the zone at the risk layer (Pitfall 3 suggestion); untouched here.

## Verification

- `pytest tests/test_planner_geometry.py tests/test_core_strategy_geometry.py tests/test_core_pivots.py tests/test_core_planner.py tests/test_core_tracer.py tests/test_no_lookahead.py tests/test_prefix_invariance.py tests/test_candle_close_timing.py tests/test_backtest_engine_strategy.py tests/test_backtest_simulator.py tests/test_decision_alignment_params.py tests/test_domain_no_float.py tests/test_registry.py`: all pass.
- `ruff check src tests scripts`: clean; `ruff format --check src tests scripts`: 384 files already formatted; `mypy src`: no issues in 149 files.
- Targeted suites only, run in the foreground; no broad full-suite run (the known access-violation modules were not touched).

## Regeneration inventory

None. Legacy signals, plan hashes, fixtures, pins and parameter sets are unchanged: no committed set carries `geometry_version`, so `_geometry_rejection` never runs for them and `parameter_set_hash` values are untouched. No file was created or edited under `params/`. The one behavioral edge is Note 1 (signed leg), which changes no committed fixture.

## Known Stubs

None.

## Threat Flags

None. No network, auth or schema surface added. T-15-08 mitigated: one `_geometry_rejection` call after quantization for every geometry_version plan, fixed order, existing reason codes, AST test of the single call (universal extension is 15-13). T-15-09 mitigated: every expectation was derived with an independent Decimal one-liner pasted into `DERIVATIONS.md`, never regenerated from `src/`. T-15-SC accepted (no installs).

## Self-Check: PASSED

- FOUND: src/core/planner.py (`def _geometry_rejection`), tests/test_core_strategy_geometry.py, tests/test_planner_geometry.py, tests/geometry_builders.py, tests/fixtures/phase15/DERIVATIONS.md, tests/fixtures/phase15/geometry_cases.json
- FOUND: DERIVATIONS.md sections `## a_short_worked`, `## a_long_audit_60000`, `## a_long_audit_59000`; geometry_cases.json stop_loss "59680" and "58760"
- FOUND: commits 56d7818, fd17050, 26135cd, e190403
