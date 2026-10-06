---
phase: 15-strategy-geometry-correction
plan: 06
subsystem: strategy-core
tags: [geometry, family-c, range-mr, pivot-regime, s3-stop, t-mid, leakage, tdd, hand-derived]

requires:
  - phase: 15-strategy-geometry-correction
    provides: "15-03 pivot function (recent_pivots), 15-04 shared _geometry_rejection validator and sidecar, 15-05 SetupLevels and the levels/wrapper pattern"
provides:
  - "src/core/strategy.py: _resolve_regime_pivots (Family C regime on the two newest confirmed 4H pivots per side), _detect_range_mr_levels (sr_far_edge under geometry_version), evaluate regime dispatch for range-mr geometry_version 1; _detect_range_mr_setup kept as a 4-tuple wrapper"
  - "src/core/planner.py: _range_mr_geometry, the S3 stop beyond the narrow S/R zone and the tp_mode target (T_MID midpoint, T_OPPOSITE opposite boundary) for Family C"
  - "Hand-derived Family C cases c_long_worked, c_short_worked, c_long_t_opposite, c_long_legacy_contrast, narrow-range RR gate, D-06/D-07/D-08 validator cases, D-13 leakage proof"
affects: [15-07, 15-08, 15-13, 15-14]

actuals:
  tokens: 16496
  tasks: 3
  commits: 4
plan_head_before: f8a55537c3c51de420006857cbee72d0ecba64e0
plan_head_after: 432c0527429ff2ce0bc7b74a36883105381cebfd

tech-stack:
  added: []
  patterns:
    - "One levels function (SetupLevels) feeds detector, evaluate and planner for B and C; the planner re-derives the setup (CR-05)"
    - "Pivot regime is a pure function of the 4H candle list; the oracle in the tests recomputes pivots from the definition on every prefix"
    - "Hand-derived windows: triangle-wave 1H closes and exact waypoint-interpolated 4H closes, constant-range bars so ATR stays exactly 2.00"

key-files:
  created: []
  modified:
    - src/core/strategy.py
    - src/core/planner.py
    - tests/geometry_builders.py
    - tests/test_core_strategy_range_mr.py
    - tests/test_planner_geometry.py
    - tests/fixtures/phase15/DERIVATIONS.md
    - tests/fixtures/phase15/geometry_cases.json

key-decisions:
  - "Under geometry_version Family C regime is BULLISH only for a strictly higher newest pivot high AND strictly higher newest pivot low, BEARISH only for both strictly lower, NEUTRAL otherwise; an equal pair is neither higher nor lower, so one tied pair is NEUTRAL whatever the other does"
  - "Fewer than two confirmed pivots of either kind inside regime_filter_lookback returns NO_TRADE, which evaluate maps to NO_TRADE_REGIME without a regime name; the regime is never defaulted"
  - "A tp_mode outside the registry values raises ValueError in the planner (configuration error, like a missing key) rather than returning STALE_SETUP"
  - "Test-local values only: pivot widths 3/3, regime_filter_lookback 50, tp_mode and geometry_version are set in memory in the tests; nothing under params/ changed (15-08 owns ratification)"

requirements-completed: [STRAT-01, STRAT-02]

duration: ~1h20m
completed: 2026-10-06
status: complete
---

# Phase 15 Plan 06: Family C Pivot Regime, S3 Stop and T-mid Target Summary

**Under geometry_version 1, Family C reads its regime from the two newest confirmed 4H pivots per side (HH+HL bullish, LH+LL bearish, otherwise neutral, fewer than two NO_TRADE) and trades only in NEUTRAL, stops beyond the far edge of the narrow S/R zone (LONG `(zone_lower - tol x ATR_ref) - sl_buffer`), and targets the range midpoint (T_MID) or the opposite boundary (T_OPPOSITE), with hand-derived LONG and SHORT cases, a leakage proof and the legacy output pinned byte for byte.**

## TDD record

The plan is `type: tdd` with a tracer first task. `gsd_run check tdd-red-evidence` only parses node:test TAP and Surefire XML, so pytest RED evidence is recorded by failing test names (same note as 15-02..15-05).

**Task 1 (tracer)**
- RED `4f997ad`: `test_c_long_worked_plan_has_the_s3_stop_beyond_the_narrow_sr_zone` failed on behavior (evaluate returned NO_TRADE_REGIME with regime BULLISH: the legacy EMA50 equality gate never reaches NEUTRAL on a structure-defined range), `test_c_long_worked_levels_carry_the_far_edge_of_the_sr_zone` failed (no levels function) and `test_c_long_legacy_contrast_keeps_the_code_stop_and_the_opposite_boundary` failed (no levels function). The legacy-regime test passed (nothing changed yet), as intended.
- GREEN `8b55266`: `_resolve_regime_pivots`, `_detect_range_mr_levels`, the evaluate dispatch and `_range_mr_geometry`. Tracer gate: `<verify>` (test_planner_geometry, test_core_strategy_range_mr) plus test_core_strategy_geometry, test_core_strategy_breakout_retest, test_core_tracer, test_core_planner, no-lookahead, prefix-invariance, test_core_pivots, test_backtest_engine_strategy, test_domain_no_float and test_registry re-run end to end after GREEN, all green, before expanding.

**Task 2** `fc7ec49`: all new tests passed on first run (no src defect). A mutation check (`>` to `>=` on the BULLISH comparison) made three of them fail (`tied_highs_rising_lows`, `higher_high_tied_lows`, the lookback boundary test), so the tie and boundary cases have teeth; the mutation was reverted with `git checkout -- src/core/strategy.py` of the committed file.

**Task 3** `432c052`: all new tests passed on first run except one whose test bar was invalid (see Deviations). Hand numbers (ATR_last 2.214285714285714285714285714, stop 96.55714285714285714285714286) were derived before the assertions.

## Accomplishments

- `_resolve_regime_pivots(context_candles, parameter_set) -> str`: `recent_pivots(count=2)` for highs and lows at the last 4H index with `regime_filter_lookback` and `pivot_left_bars`/`pivot_right_bars`; BULLISH/BEARISH/NEUTRAL/NO_TRADE as above. It reads highs and lows only (no EMA feature). `evaluate` uses it for `range-mr` when `geometry_version` is set; Families A, B and legacy C keep `_resolve_regime` (EMA50).
- `_detect_range_mr_levels(*, setup_candles, parameter_set) -> SetupLevels | None`: detection identical to the legacy detector; `sr_far_edge` = `zone_lower - zone_tolerance_atr x ATR_ref` (LONG) or `zone_upper + zone_tolerance_atr x ATR_ref` (SHORT) only under `geometry_version`, None otherwise. `_detect_range_mr_setup` is the 4-tuple wrapper.
- `_range_mr_geometry` in the planner: LONG `(zone_lower, zone_lower, sr_far_edge - sl_buffer, TP1)`, SHORT `(zone_upper, zone_upper, sr_far_edge + sl_buffer, TP1)`, TP1 midpoint for T_MID and opposite boundary for T_OPPOSITE. A vanished or direction-mismatched setup is all-None (STALE_SETUP). The shared 15-04 validator already covers it.
- Hand-derived cases (every number from an independent `python -c` Decimal one-liner pasted in DERIVATIONS.md; 4H pivots verified by an independent standalone script):
  - `c_long_worked`: 4H pivots highs 111 then 109 (LH), lows 99 then 101 (HL), regime NEUTRAL; zone 98.00..106.00, sr_far_edge 97.00, entry 97.80..98.20, stop 96.60, TP1 102.00 (midpoint), TP2 106.00, risk 1.40, RR 2.857142857142857142857142857.
  - `c_short_worked` (mirror p -> 200 - p): zone 94.00..102.00, sr_far_edge 103.00, entry 101.80..102.20, stop 103.40, TP1 98.00, TP2 94.00.
  - `c_long_t_opposite`: same window, TP1 106.00, TP2 114.00, RR 5.714285714285714285714285714.
  - `c_long_legacy_contrast`: legacy set on a flat 4H window keeps stop 97.60 (`zone_lower - sl_buffer`) and TP1 106.00 (`zone_upper`).
  - Narrow range (zone 98..102): T_MID leg 2.00 < 2 x 1.40 is RR_TOO_LOW (RR 1.428571428571428571428571429, boundary checked with `minimum_rr` 1.4 admitted and 1.43 rejected); T_OPPOSITE gives a plan (TP1 102, TP2 106, RR 2.857142857142857142857142857).
- Pivot regime unit tests: HH+HL, LH+LL, contracting, expanding, four tie variants (rule documented in the test docstring), one pivot high, one pivot low, flat window, evaluate returning NO_TRADE_REGIME with regime None, a pivot one bar outside the lookback ignored (and counted one bar later, and dropped again with lookback 49), an unconfirmed swing in the last `pivot_right_bars` bars ignored (BULLISH on 249 bars, NEUTRAL once bar 249 confirms it), a uniform price shift leaves the verdict unchanged.
- Prefix invariance: for every k of a 320-bar 4H zig-zag the verdict on `context[: k + 1]` equals a by-definition oracle computed on that prefix (all four verdicts occur), and altering every later bar leaves earlier verdicts unchanged.
- Leakage (D-13): replacing the evaluated bar (LONG: lower low inside the band, higher high; SHORT mirror) leaves `zone_upper`, `zone_lower` and `sr_far_edge` unchanged; legacy zone bounds too; a range-breaking bar voids the setup without moving the levels.
- Validator on C: D-07 INVALIDATED (`touch_tolerance_atr` 2.0, crash bar low 95.00 under stop 96.5571...), D-08 STOP_TOO_TIGHT (`min_stop_atr` 1.0 and 0.71 reject, 0.7 passes with equality; risk 1.40 = 0.7 ATR), D-06 STOP_TOO_TIGHT (`zone_tolerance_atr` 0 with `sl_buffer_atr` 0.05, stop 97.90 vs entry_min 97.80). Also: a vanished setup at plan time is STALE_SETUP, an unknown `tp_mode` raises.
- Legacy unchanged: signal ids and plan hashes of the existing long and short builders under range-mr baseline-v1 and baseline-v5, captured by running the pre-change commit (f8a5553) from a `git archive` copy, are pinned as literals and still match; the legacy regime still needs exact EMA50 equality (a contracting window gives NO_TRADE_REGIME with BULLISH/BEARISH named under a legacy set).

## Task Commits

1. Task 1 RED: `4f997ad` test(15-06): add failing tracer for Family C pivot regime, S3 stop and T-mid target
2. Task 1 GREEN: `8b55266` feat(15-06): Family C pivot regime, S3 stop on the narrow S/R zone and tp_mode target
3. Task 2: `fc7ec49` test(15-06): Family C pivot regime cases, ties, lookback, prefix invariance and legacy pins
4. Task 3: `432c052` test(15-06): Family C SHORT, T_OPPOSITE, T-mid RR gate, leakage proof and validator cases

## Deviations from Plan

### Auto-fixed Issues

None. No Rule 1-4 fix was needed beyond the plan.

### Notes

**1. [Test premise corrected] Signal id contrast dropped for Family C.** A draft `c_long_legacy_contrast` test asserted that the corrected and the legacy signal ids differ (true for A and B because their zone changes). For Family C the zone, regime name and ATR are identical, and both in-memory sets reuse baseline-v5's `parameter_set_id`, so the id is the same. In production a set carrying `geometry_version` has its own id and hash. The assertion was removed; the differences (stop, TP1, regime) are asserted instead.

**2. [Test bar corrected] "moved" bar in the stale-setup test.** `Candle` requires `low <= open <= high`; the first replacement bar (low 103, open 100) was invalid, so it became low 100.

**3. [Placement] Sidecar helper and builders.** `_number` in `tests/test_planner_geometry.py` now returns text for non-numeric values (`tp_mode`). `tests/geometry_builders.py` gained `interpolated_closes`, `four_hour_context`, `pivot_context`, `flat_context`, `range_mr_closes` and the `range_mr_*_window` builders (the plan names the file for Task 1).

**4. [Extra cases] `c_long_t_opposite` and the unconfirmed/lookback-boundary windows** are actual cases with derivations rather than prose.

**5. [Pre-existing, out of scope] `tests/test_phase6_fixture_geometry.py::test_generator_is_deterministic_and_matches_committed_fixtures`** (CRLF vs LF) was not touched; already in `deferred-items.md`.

## Observations for later plans (not fixed here)

- **Contracting regime and range detector are independent.** The regime says "4H structure is neither trending up nor down"; the detector still defines the range on the 1H swing window. Nothing ties the two, as the spec defines them.
- **Bar 200 style boundary pivots.** A flat stretch followed by an ascent makes the first ascent bar a confirmed pivot low, so flat-then-move windows contribute an extra older pivot. The tests state this explicitly where it matters (`PIVOT_*` tables, lookback-boundary case).
- **`regime_filter_lookback` now sizes the pivot window for C** (it was an EMA-era key). Its value, the pivot widths and `tp_mode` are ratified only at 15-08; all test values are in memory.
- **TP1 "beyond the entry zone"** is still unenforced (15-04 observation); for C the midpoint leg exceeds the entry zone in every derived case, and the narrow case is rejected by the RR gate.

## Verification

- `pytest tests/test_core_strategy_range_mr.py tests/test_planner_geometry.py tests/test_core_strategy_breakout_retest.py tests/test_core_strategy_geometry.py tests/test_core_pivots.py tests/test_core_tracer.py tests/test_no_lookahead.py tests/test_prefix_invariance.py tests/test_core_planner.py tests/test_backtest_engine_strategy.py tests/test_backtest_simulator.py tests/test_decision_alignment_params.py tests/test_domain_no_float.py tests/test_registry.py tests/test_geometry_audit_doc.py`: all pass.
- `ruff check src tests scripts`: clean; `ruff format --check src tests scripts`: 384 files already formatted; `mypy src`: no issues in 149 files.
- Targeted suites only, foreground; no broad full-suite run (known access-violation modules not touched).

## Regeneration inventory

None. No committed parameter set carries `geometry_version`, so the legacy Family C regime, detector, planner output, signal ids, plan hashes and `parameter_set_hash` values are unchanged (pinned by `test_legacy_unchanged_signal_id_and_plan_hash_match_the_pre_change_values`, which compares against ids recorded from the pre-change commit). No file was created or edited under `params/`; every `geometry_version`, `tp_mode` and pivot-width value in the new cases is test-local and in memory.

## Known Stubs

None.

## Threat Flags

None. No network, auth or schema surface added. T-15-12 mitigated: confirmed pivots only (`t + right <= last index`), the lookback window is enforced (boundary tests at 199/200 and lookback 49), and the prefix-invariance tests compare every bar of a 320-bar path with a by-definition oracle and alter later bars. T-15-SC accepted (no installs).

## Self-Check: PASSED

- FOUND: src/core/strategy.py (`def _resolve_regime_pivots`, `def _detect_range_mr_levels`), src/core/planner.py (`def _range_mr_geometry`), tests/geometry_builders.py, tests/test_core_strategy_range_mr.py, tests/test_planner_geometry.py, tests/fixtures/phase15/DERIVATIONS.md, tests/fixtures/phase15/geometry_cases.json
- FOUND: DERIVATIONS.md sections `## c_long_worked`, `## c_short_worked`, `## c_long_t_opposite`, `## c_long_legacy_contrast`, `## Family C narrow range and validator cases`; geometry_cases.json keys `c_long_worked`, `c_short_worked`, `c_long_t_opposite`, `c_long_legacy_contrast`
- FOUND: test names containing `pivot_regime_bullish`, `pivot_regime_bearish`, `pivot_regime_neutral`, `insufficient_pivots`, `regime_prefix_invariance`, `evaluated_bar_does_not_move_level`, `test_c_d07`, `test_c_d08`, `test_c_d06`, `t_opposite`, `rr_too_low`
- FOUND: commits 4f997ad, 8b55266, fc7ec49, 432c052
