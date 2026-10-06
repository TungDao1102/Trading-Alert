---
phase: 15-strategy-geometry-correction
plan: 03
subsystem: strategy-core
tags: [pivots, geometry, family-a, registry, tdd, hand-derived, F-301]

requires:
  - phase: 15-strategy-geometry-correction
    provides: "15-01 geometry audit; 15-02 rationale record (new sets carry rationale tables)"
  - phase: 12-fee-cost-model-correctness
    provides: "optional-key registry pattern (hash-neutral for older sets)"
provides:
  - "src/core/pivots.py: pivot_at, recent_pivots (pure, Decimal-only, closed candles, prefix-invariant)"
  - "src/core/strategy.py: geometry_version(parameter_set) and _detect_pivot_setup; evaluate dispatches Family A to it when the key is present"
  - "src/core/planner.py: _pivot_geometry; _long_geometry/_short_geometry take keyword entry_buffer; Family A geometry_version 1 puts the stop beyond the whole entry zone"
  - "src/domain/registry.py: optional keys pivot_left_bars, pivot_right_bars, geometry_version, tp_mode, min_stop_atr; GEOMETRY_VERSION_VALUES, TP_MODE_VALUES; _check_geometry_keys"
  - "tests/geometry_builders.py and tests/fixtures/phase15/{DERIVATIONS.md,geometry_cases.json}: hand-derived constant-range window and sidecar"
affects: [15-04, 15-05, 15-06, 15-08, 15-14]

actuals:
  tokens: 11600
  tasks: 3
  commits: 6
plan_head_before: 21674b1ff320ce4c0aadc4d4f67cfd7bcddc3303
plan_head_after: 1e78d9870347b0b5e3f6bb046f0f2b5acb99423c

tech-stack:
  added: []
  patterns:
    - "geometry_version gate: key absent means the legacy path byte for byte; key present selects the pivot path in both evaluate and plan"
    - "Planner re-derives the pivot level and TP1 from the same setup candles the detector used (CR-05), never from the signal"
    - "Constant-range candle windows (high - low = 2, closes step <= 1) make ATR equal the bar range exactly so a case is hand-derivable"

key-files:
  created:
    - src/core/pivots.py
    - tests/geometry_builders.py
    - tests/test_core_pivots.py
    - tests/test_planner_geometry.py
    - tests/fixtures/phase15/DERIVATIONS.md
    - tests/fixtures/phase15/geometry_cases.json
  modified:
    - src/core/strategy.py
    - src/core/planner.py
    - src/domain/registry.py
    - tests/test_registry.py
    - tests/test_domain_no_float.py

key-decisions:
  - "Tie rule as implemented follows the interface contract (left non-strict, right strict): of two equal lows in one window the RIGHT one is the pivot, and the last bar of a plateau followed by a strictly higher right side qualifies. The plan prose said 'leftmost'; that contradicts its own contract, so the contract won."
  - "pivot_right_bars + 1 <= swing_lookback is enforced at load only when both keys are present; geometry_version alone is legal in a breakout-retest set (15-05 will consume it), while trend-pullback and range-mr sets need both pivot widths, and range-mr also tp_mode"
  - "min_stop_atr is independent of geometry_version in the registry (range (0, 10]); the planner check that consumes it is a later plan"
  - "A missing pivot (either side) returns all-None geometry, which plan() maps to STALE_SETUP; evaluate returns the existing NO_TRADE_REGIME 'no setup' reason (D-03, no fallback)"

patterns-established:
  - "New optional registry keys come with a closed value set, range branch in _check_value_range and a cross-key rule in _check_geometry_keys, plus an ambient-config rejection test"

requirements-completed: [STRAT-01, STRAT-02]

duration: ~40min
completed: 2026-10-06
status: complete
---

# Phase 15 Plan 03: Confirmed Pivots and Corrected Family A Geometry Summary

**Family A with `geometry_version = 1` now keys off the most recent confirmed 3/3 pivot (evaluated bar excluded) and places the stop beyond the whole entry zone: in the hand-derived LONG case entry_min 97.80, stop 97.40, TP1 106.00, against 96.80 / 97.60 (inside the zone) for the legacy path on the same candles.**

## TDD record

The plan is `type: tdd`; each task has a RED then a GREEN commit. RED evidence is recorded by failing test name; `gsd_run check tdd-red-evidence` only parses node:test TAP and Surefire XML, so it cannot classify pytest output (same note as 15-02).

**Task 1 (tracer)**
- RED `8386a53`: `tests/test_planner_geometry.py`, builders and the sidecar. Assertion-level failures: `test_a_long_worked_plan_has_stop_beyond_the_whole_entry_zone` (got entry_min 96.80, expected 97.80) and `test_geometry_version_changes_the_signal_identity` (identical signal ids). The legacy contrast case passed immediately, which independently confirms the hand-derived legacy numbers (96.80, 99.20, 97.60, 114.00).
- GREEN `60040a4`: `pivot_at` (minimal), `geometry_version`, `_detect_pivot_setup`, `_pivot_geometry`, evaluate and plan dispatch. 29 tests green across the planner geometry, tracer and legacy planner suites before Task 2.
- Tracer gate: `<verify>` re-run end to end after GREEN (green) before expanding; `tests/test_core_tracer.py` and `tests/test_core_planner.py` pass unchanged.

**Task 2 (pivots)**
- RED `ec86282`: 13 pivot tests plus `src/core/pivots.py` in the no-float scan. A skeleton `recent_pivots` returning `()` is in the RED commit so the module imports and the failures are assertions, not collection errors. Failing: both tie-rule tests, `test_recent_pivots_are_newest_first_and_capped`, five `test_invalid_arguments_raise_value_error` cases, `test_recent_pivots_rejects_non_positive_count`. The `pivot_at` behaviors (confirmed exactly at t+R, never the evaluated bar, lookback bound, warm-up, prefix invariance with poisoned later candles) already passed from Task 1.
- GREEN `e3ab36e`: argument validation, shared `_confirmed` scan, `recent_pivots`.

**Task 3 (registry)**
- RED `2c58f52`: 15 failing tests (new keys unknown, ambient config not rejected, value and cross-key rules absent).
- GREEN `1e78d98`: keys, closed sets, range branches, `_check_geometry_keys`.

## Accomplishments

- `pivot_at` and `recent_pivots`: candidates `t` in `[max(left, i - lookback + 1), i - right]` scanned downward, so `t + right <= i` always holds (T-15-05). A 300-bar zig-zag proves `pivot_at(candles, i) == pivot_at(candles[:i+1], i)` for both sides at every `i`, and that replacing every later candle with extreme values leaves the value at `i` unchanged.
- Family A evaluate/plan on the pivot path: P = most recent confirmed pivot low (LONG) or high (SHORT) inside `swing_lookback`; zone = P +/- zone_tolerance_atr x ATR; entry zone widened by entry_buffer; stop = zone_lower - entry_buffer - sl_buffer (SHORT mirrored); TP1 = most recent confirmed opposite pivot; TP2 unchanged formula. No pivot gives NO_TRADE / STALE_SETUP, never a fallback.
- Hand-derived sidecar: `DERIVATIONS.md` (independence sentence, common inputs, `## a_long_worked`, `## a_long_legacy_contrast`, pasted Decimal one-liners with output) and `geometry_cases.json`; a test walks the parsed keys for the research-gate tripwire names.
- Registry keys are optional, typed, ranged and cross-checked; the pinned hash tests (PA-01..PA-03, `test_decision_alignment_params.py`) pass unchanged and a test asserts no committed set carries a Phase 15 key.

## Task Commits

1. Task 1 RED: `8386a53` test(15-03): add failing tracer for corrected Family A LONG geometry
2. Task 1 GREEN: `60040a4` feat(15-03): corrected Family A LONG/SHORT geometry from confirmed pivots
3. Task 2 RED: `ec86282` test(15-03): add failing pivot tests for ties, validation and recent_pivots
4. Task 2 GREEN: `e3ab36e` feat(15-03): complete pivot function with validation and recent_pivots
5. Task 3 RED: `2c58f52` test(15-03): add failing registry tests for the five Phase 15 keys
6. Task 3 GREEN: `1e78d98` feat(15-03): add optional pivot, geometry_version, tp_mode, min_stop_atr registry keys

## Deviations from Plan

### Process and wording notes (no Rule 1-4 fix was needed)

**1. [Process] RED skeleton for `recent_pivots`**
- The Task 2 RED commit carries a no-op `recent_pivots` so tests import and fail on assertions. Replaced in GREEN.

**2. [Plan wording] Tie rule "leftmost"**
- The behavior list says a flat series yields "the leftmost qualifying bar only when the right side is strictly higher". Under the plan's own interface contract (left non-strict, right strict) the qualifying bar of an equal run is the rightmost one, and a flat series has no pivot at all. Implemented and tested per the contract; the module docstring says so.

**3. [Process] Sequencing inside Task 1**
- Task 1's GREEN deliberately omitted `recent_pivots` and argument validation so Task 2's RED failed on real behavior; Task 2 added them as the plan intended.

## Observations for later plans (not fixed here)

- **TP1 direction is not validated.** `plan()`'s RR gate uses `abs(tp1 - entry_ref)`. With confirmed pivots the opposite pivot can in principle lie on the wrong side of the entry zone (price fell through it after it formed), and the gate would then accept a nonsense target. The plan did not ask for a direction guard and D-06/D-07 invariants belong to 15-04, so none was added; 15-04 should cover "TP1 beyond the entry zone" in the shared invariant.
- **Only the LONG case is hand-derived here.** The SHORT mirror in `_detect_pivot_setup` and `_pivot_geometry` is symmetric code but has no hand-derived case in this plan (D-18 SHORT case is a later plan's job).
- **`geometry_version` in a breakout-retest set loads but nothing consumes it yet** (15-05). A range-mr set with `tp_mode` loads but is not read by the planner yet (15-06).
- **`min_stop_atr` loads but is not consumed yet** (planner check is a later plan).

## Verification

- `pytest tests/test_core_pivots.py tests/test_planner_geometry.py tests/test_registry.py tests/test_core_tracer.py tests/test_no_lookahead.py tests/test_prefix_invariance.py tests/test_candle_close_timing.py tests/test_core_planner.py tests/test_decision_alignment_params.py tests/test_domain_no_float.py tests/test_registry_gate.py tests/test_backtest_engine_strategy.py tests/test_rationale.py tests/test_backtest_simulator.py`: all pass (about 360 tests).
- `ruff check src tests scripts`: clean; `ruff format --check src tests scripts`: 383 files already formatted; `mypy src`: no issues in 149 files.
- No broad full-suite run (the known access-violation modules were not touched; only the targeted suites above were run, in the foreground).

## Runtime-config grep (new key names)

Searched tracked files (`git grep -i` for `geometry_version|tp_mode|min_stop_atr|pivot_left_bars|pivot_right_bars`, excluding `.planning/`): matches only in `docs/research/GEOMETRY_AUDIT.md`, `docs/research/families/range-mr.md`, `src/core/{planner,strategy}.py`, `tests/test_planner_geometry.py`, `tests/fixtures/phase15/geometry_cases.json`. No tracked `.yml`, `.yaml`, `.toml` (outside `params/`), `.ini`, `.cfg` or env template uses any of the five names; `.env.example` and `docker-compose.yml` contain none. The untracked local `.env` was not read (the secret-read guard blocks it), so it is unchecked: if it defines a variable named `GEOMETRY_VERSION`, `TP_MODE`, `MIN_STOP_ATR`, `PIVOT_LEFT_BARS` or `PIVOT_RIGHT_BARS` it would now be rejected by `check_strategy_key_outside_registry`; the user may want to confirm.

## Regeneration inventory

None. Legacy signals, plan hashes, fixtures, pins and parameter sets are unchanged: every committed set lacks `geometry_version`, so the legacy `_detect_setup` and legacy `_long_geometry`/`_short_geometry` branches run, and `parameter_set_hash` values are untouched (PA-01..PA-03 and `tests/test_decision_alignment_params.py` pass without edits). No file was created or edited under `params/`.

## Known Stubs

None. (Keys that load but are not yet consumed are listed under Observations; they are optional and inert until their consumer plans.)

## Threat Flags

None. No network, auth or schema surface added. T-15-05 (look-ahead) mitigated by the `t + right <= i` scan bound and tests for confirmation exactly at t+R, strictly falling series and prefix invariance with poisoned later candles. T-15-06 mitigated by typed and ranged keys, NaN/Infinity/bool rejection, cross-key rules and ambient-config rejection tests. T-15-07 mitigated: keys optional, PA tests in the verify run. T-15-SC accepted (no installs).

## Self-Check: PASSED

- FOUND: src/core/pivots.py, tests/geometry_builders.py, tests/test_core_pivots.py, tests/test_planner_geometry.py, tests/fixtures/phase15/DERIVATIONS.md, tests/fixtures/phase15/geometry_cases.json
- FOUND: commits 8386a53, 60040a4, ec86282, e3ab36e, 2c58f52, 1e78d98
- `grep -q 'GEOMETRY_VERSION_VALUES = frozenset({1})' src/domain/registry.py`, `"tp_mode"`, `"min_stop_atr"` present; `"src/core/pivots.py"` present in tests/test_domain_no_float.py; DERIVATIONS.md contains "never from the output of the code under test" and "## a_long_worked"
