---
phase: 15-strategy-geometry-correction
plan: 05
subsystem: strategy-core
tags: [geometry, family-b, breakout-retest, anchoring, with-regime, s3-stop, leakage, tdd, hand-derived]

requires:
  - phase: 15-strategy-geometry-correction
    provides: "15-04 shared _geometry_rejection validator, geometry_version gate, hand-derived sidecar and builders"
provides:
  - "src/core/strategy.py: SetupLevels and _detect_breakout_retest_levels (anchored scan, direction filter, sr_far_edge under geometry_version 1); _detect_breakout_retest_setup kept as a 4-tuple wrapper"
  - "evaluate passes direction LONG in BULLISH and SHORT in BEARISH for geometry_version 1 breakout-retest sets"
  - "src/core/planner.py: _breakout_retest_geometry, the S3 stop on the narrow S/R zone for Family B"
  - "Hand-derived Family B cases b_long_worked, b_short_worked, b_long_legacy_confirm3 (+ legacy contrast), anchoring windows, leakage proof, D-06/D-07/D-08 cases on B"
affects: [15-06, 15-08, 15-13, 15-14]

actuals:
  tokens: 15617
  tasks: 3
  commits: 4
plan_head_before: ef8daf360d9d1411b80411aee0f371acdfa40f01
plan_head_after: c166622cac713702a83aaa0612a1714c4a9b9d03

tech-stack:
  added: []
  patterns:
    - "Anchored scan: breakout end bar i from n-2 down to max(confirm+1, n-1-window), first retest must be exactly n-1"
    - "Legacy and corrected paths share one function; a boolean from geometry_version selects scan range, direction filter and sr_far_edge"
    - "Hand-derived windows built from constant-range bars plus custom bars whose true range is still 2.00, so ATR stays exactly 2.00"

key-files:
  created: []
  modified:
    - src/core/strategy.py
    - src/core/planner.py
    - tests/geometry_builders.py
    - tests/test_core_strategy_breakout_retest.py
    - tests/test_planner_geometry.py
    - tests/fixtures/phase15/DERIVATIONS.md
    - tests/fixtures/phase15/geometry_cases.json

key-decisions:
  - "Under geometry_version 1 a bar that closes beyond its own (later, higher) edge is itself a candidate breakout end bar; the first-retest rule is evaluated per candidate, so a plateau bar can claim a retest on an earlier bar and be skipped, and the detector then continues down to the original breakout (documented in DERIVATIONS.md)"
  - "The levels function is shared by detector, evaluate and planner; the planner re-derives the setup with direction=signal.direction (CR-05) and never reads the signal zone"
  - "Test-local breakout_confirmation_bars is 1 for the main worked cases (proposed baseline of sheet B1, ratified only at 15-08) and 3 only in the labelled b_long_legacy_confirm3 case"

requirements-completed: [STRAT-01, STRAT-02]

duration: ~1h45m
completed: 2026-10-06
status: complete
---

# Phase 15 Plan 05: Family B Anchoring, With-Regime Gate and S3 Stop Summary

**Under geometry_version 1, Family B signals only when the first retest after a breakout is the evaluated bar, only with the 4H regime, and its stop sits beyond the far edge of the narrow broken S/R zone (LONG `swing_high_ref - tol x ATR_ref - sl_buffer`), with hand-derived LONG, SHORT and confirm-3 cases, a leakage proof and the legacy output pinned byte for byte.**

## TDD record

The plan is `type: tdd` with a tracer first task. `gsd_run check tdd-red-evidence` only parses node:test TAP and Surefire XML, so pytest RED evidence is recorded by failing test names (same note as 15-02..15-04).

**Task 1 (tracer)**
- RED `6b49e0d`: `test_b_long_worked_plan_has_the_s3_stop_beyond_the_narrow_sr_zone` failed on behavior (plan() returned INVALIDATED: the legacy detector picked the plateau bar 247 with edge 103.00 and stop 102.60, above the evaluated bar's low 102), `test_b_long_worked_levels_carry_the_far_edge_of_the_sr_zone` failed (no levels function) and `test_b_long_legacy_contrast_keeps_the_code_stop_edge_minus_sl_buffer` failed on the signal-identity comparison. The explicit-confirmation-bars test passed (parameter-only).
- GREEN `032c54b`: `SetupLevels`, `_detect_breakout_retest_levels`, the evaluate direction gate and `_breakout_retest_geometry`. Tracer gate: `<verify>` (test_planner_geometry, test_core_strategy_breakout_retest, test_core_tracer) plus test_core_planner, test_core_strategy_geometry, no-lookahead, prefix-invariance and the backtest suites re-run end to end after GREEN, all green, before expanding.

**Task 2** `a8c83f5`: the new tests passed on their first run except one test whose premise was wrong (see Deviations). No src defect was exposed.

**Task 3** `c166622`: leakage and validator tests passed on first run; the hand numbers (ATR 2.853498542274052478134110787, stop 99.42930029154518950437317784) were derived before the assertions.

## Accomplishments

- `_detect_breakout_retest_levels(*, setup_candles, parameter_set, direction=None) -> SetupLevels | None`. Legacy sets run the original scan byte for byte (from `n - 1`, any retest in the window, `direction` ignored, `sr_far_edge` None). With `geometry_version` the scan covers end bars `n - 2` down to `max(breakout_confirmation_bars + 1, n - 1 - retest_window_bars)`, requires `_find_retest_bar(..., i + 1) == n - 1`, honors `direction`, and sets `sr_far_edge` = `swing_high_ref - tol x ATR_ref` (LONG) or `swing_low_ref + tol x ATR_ref` (SHORT). The lower bound keeps `ref_prev = i - confirm - 1 >= 0` for every confirm value (proved for confirm 1, 2, 3, 5 over every window length 1..59, and by a minimal n = 8 window whose smallest scanned end bar is 2) and is exact for the window (an n = 9 variant with the retest six bars after the breakout gives no setup).
- `evaluate` with geometry_version 1 and `breakout-retest`: direction `LONG` in BULLISH, `SHORT` in BEARISH (NEUTRAL already returned NO_TRADE_REGIME); a counter-regime breakout is NO_TRADE_REGIME with the regime named.
- `_breakout_retest_geometry` in the planner: LONG `(edge, edge, sr_far_edge - sl_buffer, edge + height)`, SHORT `(edge, edge, sr_far_edge + sl_buffer, edge - height)`; a vanished or mismatched setup is all-None (STALE_SETUP). The shared validator from 15-04 now covers geometry_version Family B plans too.
- Hand-derived cases (every number from an independent `python -c` Decimal one-liner pasted in DERIVATIONS.md):
  - `b_long_worked` (test-local confirm 1): edge 102.00, zone_lower 97.00, sr_far_edge 100.00, entry 101.80..102.20, stop 99.60, TP1 107.00, TP2 112.00, RR 2.083333333333333333333333333.
  - `b_short_worked` (mirror p -> 200 - p, BEARISH): edge 98.00, zone_upper 103.00, sr_far_edge 100.00, entry 97.80..98.20, stop 100.40, TP1 93.00, TP2 88.00.
  - `b_long_legacy_confirm3` (labelled "legacy value, not the baseline to be ratified"): three closes above the edge, `ref_prev = i - 4 = 243` (bar 244 with high 102 stays out of the swing window, so the edge is 102.00, not 103.00); same plan numbers as b_long_worked; with one close above the edge the same set gives no signal.
  - `b_long_legacy_contrast`: the legacy path on the same window stops at the plateau bar 247 (edge 103.00, stop 102.60 = edge - 0.2 x ATR, TP1 109.00), unchanged.
- Anchoring regressions (each also shows the legacy set still signals where applicable): stale breakout 40 bars back, retest at n - 2 plus another touch at n - 1, first retest six bars after the breakout, LONG breakout under a BEARISH regime, SHORT breakout under a BULLISH regime.
- Leakage (D-13): replacing the evaluated bar with a higher high / other low / extreme values (LONG and SHORT) leaves `zone_upper`, `zone_lower` and `sr_far_edge` unchanged, and the legacy wrapper's zone bounds too.
- Validator on B: D-07 INVALIDATED (retest_depth_atr 2.0 crash window, low 98.50 below stop 99.4293...), D-08 STOP_TOO_TIGHT (`min_stop_atr` 2.0 and 1.21 reject, 1.2 passes with equality; risk 2.40 = 1.2 ATR), D-06 STOP_TOO_TIGHT (`zone_tolerance_atr` 0 with `sl_buffer_atr` 0.05, stop 101.90 vs entry_min 101.80).
- Legacy unchanged: signal ids and plan hashes of the existing long and short builders under baseline-v1 and baseline-v5, captured from the pre-change commit (ef8daf3), are pinned as literals and still match.

## Task Commits

1. Task 1 RED: `6b49e0d` test(15-05): add failing tracer for Family B anchored retest and S3 stop
2. Task 1 GREEN: `032c54b` feat(15-05): anchored with-regime Family B detector and S3 stop on the narrow S/R zone
3. Task 2: `a8c83f5` test(15-05): Family B anchoring, with-regime gate, SHORT and confirm-3 cases, legacy pins
4. Task 3: `c166622` test(15-05): Family B leakage proof and D-06/D-07/D-08 validator cases

## Deviations from Plan

### Auto-fixed Issues

None. No Rule 1-4 fix was needed beyond the plan.

### Notes

**1. [Test premise corrected] "first retest one bar earlier" assertion removed.** A draft test asserted that cutting the b_long_worked window to bar 248 gives no signal. It does signal: bar 247 (close 104) clears its own, later and higher, edge 103.00 and bar 248 (low 103) lies in that edge's band, so it is a legitimate anchored setup at a different end bar. This is the behavior the spec defines, not a defect, so the assertion was dropped rather than the detector changed. The nuance is recorded in DERIVATIONS.md (b_long_worked and the confirm-3 section).

**2. [Placement] Extra builders and helpers in `tests/geometry_builders.py`.** `trending_context` was extracted from `window_from_closes` (unchanged behavior; all Family A cases still pass) and Family B builders were added there; the plan lists the file for Task 1 only.

**3. [Extra case] `b_long_legacy_contrast` and a crash window.** The plan asks for the legacy stop comparison in prose; it is an actual sidecar case. The D-07 case needs the retest band to reach below the stop, which forces bars 247/248 far above the band and a large evaluated bar, so a dedicated `family_b_crash_window` with its own derivation (`## b_long_invalidated`) was added.

**4. [Pre-existing, out of scope] `tests/test_phase6_fixture_geometry.py::test_generator_is_deterministic_and_matches_committed_fixtures`** (CRLF vs LF) was not touched; already in `deferred-items.md`.

## Observations for later plans (not fixed here)

- **Plateau bars are candidate breakout end bars.** With `breakout_confirmation_bars` 1, any bar closing above its own edge (which rises with the preceding breakout bars' highs) is a candidate; the per-candidate first-retest rule resolves it, but a trend continuation can re-anchor a setup on a later bar with a higher edge. Not changed: the spec defines the scan this way.
- **TP1 "beyond the entry zone"** is still unenforced (15-04 observation); for B the measured-move TP1 is far from the entry zone in every derived case.
- **The legacy `risk` guards** (`_plan_geometry_is_valid` in `src/risk/gating.py`) were not touched.
- `evaluate` still routes `breakout-retest` through the legacy wrapper for sets without `geometry_version`; 15-13 makes the validator and the gate universal.

## Verification

- `pytest tests/test_core_strategy_breakout_retest.py tests/test_planner_geometry.py tests/test_core_strategy_geometry.py tests/test_core_tracer.py tests/test_no_lookahead.py tests/test_prefix_invariance.py tests/test_core_planner.py tests/test_backtest_engine_strategy.py tests/test_backtest_simulator.py tests/test_decision_alignment_params.py tests/test_domain_no_float.py tests/test_registry.py`: all pass. Also green: `tests/test_geometry_audit_doc.py`, `test_backtest_experiment.py`, `test_decision_alignment_protocol.py`, `test_cost_per_unit.py`, `test_kill_gate_event.py`, `test_constraint_snapshot.py`.
- `ruff check src tests scripts`: clean; `ruff format --check src tests scripts`: 384 files already formatted; `mypy src`: no issues in 149 files.
- Targeted suites only, foreground; no broad full-suite run (known access-violation modules not touched).

## Regeneration inventory

None. No committed parameter set carries `geometry_version`, so the legacy Family B detector, planner output, signal ids, plan hashes and `parameter_set_hash` values are unchanged (pinned by `test_legacy_unchanged_*`, which compare against ids recorded before the change). No file was created or edited under `params/`; every geometry_version key and `breakout_confirmation_bars` value in the new cases is test-local and in memory.

## Known Stubs

None.

## Threat Flags

None. No network, auth or schema surface added. T-15-10 mitigated: geometry_version 1 requires the first retest after the breakout to be the evaluated bar, with stale, not-first and out-of-window regressions. T-15-11 mitigated: behavior is gated by `geometry_version`, and legacy ids and plan hashes of the existing builders are pinned. T-15-SC accepted (no installs).

## Self-Check: PASSED

- FOUND: src/core/strategy.py (`class SetupLevels`, `def _detect_breakout_retest_levels`), src/core/planner.py (`def _breakout_retest_geometry`), tests/geometry_builders.py, tests/test_core_strategy_breakout_retest.py, tests/test_planner_geometry.py, tests/fixtures/phase15/DERIVATIONS.md, tests/fixtures/phase15/geometry_cases.json
- FOUND: DERIVATIONS.md sections `## b_long_worked`, `## b_short_worked`, `## b_long_legacy_confirm3` (contains "legacy value, not the baseline to be ratified"); geometry_cases.json keys `b_long_worked`, `b_short_worked`, `b_long_legacy_confirm3`
- FOUND: test names containing `stale_breakout`, `first_retest`, `counter_regime`, `legacy_unchanged`, `evaluated_bar_does_not_move_level`
- FOUND: commits 6b49e0d, 032c54b, a8c83f5, c166622
