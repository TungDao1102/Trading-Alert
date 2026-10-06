---
phase: 15-strategy-geometry-correction
plan: 09
subsystem: parameter-registry
tags: [parameters, baselines, rationale, pa-08, gate, tdd]

requires:
  - phase: 15-strategy-geometry-correction
    provides: "15-08 ratified table (the two -v4 baselines), baseline-v6 sets, 15-02 check_rationale, 15-03 registry keys"
provides:
  - "params/trend-pullback/baseline-no-trade-v4.toml and baseline-simple-trend-v4.toml: comparison baselines at strategy_version v5.0.0, geometry_version 1, pivot keys and min_stop_atr, one rationale table per parameter"
  - "Gate PA-08 (PHASE15_SET_IDS, EXPECTED_PHASE15_VERSION, check_phase15_set_facts) over the five Phase 15 sets"
  - "Exact pin-set equality: pin file key set == PRE_PHASE_HASHES | NEW_SET_IDS | PHASE12_SET_IDS | PHASE15_SET_IDS (25 pins)"
affects: [15-13]

actuals:
  tokens: 16500
  tasks: 2
  commits: 2
plan_head_before: 859d70ce0d54a17997c6bb96bc55f30a06abdab5
plan_head_after: c800f3d6a76abf12864e5eb8198bb5b1ea1cbb3c

key-files:
  created:
    - params/trend-pullback/baseline-no-trade-v4.toml
    - params/trend-pullback/baseline-simple-trend-v4.toml
  modified:
    - tests/fixtures/phase4/parameters.json
    - tests/test_rationale.py
    - tests/test_decision_alignment_params.py
    - scripts/decision_alignment/params.py

key-decisions:
  - "Both -v4 baselines take the trend-pullback baseline-v6 values with only the ratified overrides (no-trade: minimum_rr 100; simple-trend: zone_tolerance_atr 1.0, minimum_rr 0.5); the executor chose no value"
  - "The three overridden values carry basis DECISION with ref D054, as recorded in 15-08-SUMMARY (flagged there for the user's attention)"
  - "PA-08 reuses the PA-07 frozen guard table and cost-key list so the five Phase 15 sets cannot drift from the Phase 12 cost set"

requirements-completed: [STRAT-02]

duration: ~25min
completed: 2026-10-06
status: complete
---

# Phase 15 Plan 09: -v4 comparison baselines and gate PA-08 Summary

**The no-trade and simple-trend baselines are re-issued as -v4 sets on the corrected geometry (v5.0.0, geometry_version 1, pivot keys, min_stop_atr) exactly as the user ratified, pinned with complete rationale tables, and gate PA-08 plus exact pin-set equality now guard all five Phase 15 sets against drift.**

## Accomplishments

- Task 1 (tracer): precondition verified (the line `Ratified-by: user (verbatim reply to checkpoint 15-08-01)` followed by `ratify` is in 15-08-SUMMARY.md, with a value and basis for every -v4 key) before any file was written. RED: `PHASE15_SETS` and `PHASE15_PLACEHOLDERS` extended, four behavior tests added (failed with missing files). GREEN: both files written from the baseline-v6 text with "Supersedes baseline-no-trade-v3" / "Supersedes baseline-simple-trend-v3" headers, the F-810 byte-identical note, 29 parameters and 29 `[rationale.<key>]` tables each (commit a1aac86).
  - `baseline-no-trade-v4`: differs from baseline-v6 only in `minimum_rr = 100` (DECISION, D054). On the `tests/geometry_builders.py` Family A window the signal is produced, the planner returns no plan with reason `RR_TOO_LOW` (invariants pass first, D-26).
  - `baseline-simple-trend-v4`: differs only in `zone_tolerance_atr = 1.0` and `minimum_rr = 0.5` (both DECISION, D054). On the same window it produces a plan whose stop is below `entry_min_price`.
  - Both ids are excluded from the trend-pullback candidate lists by their prefix; the family independence and analytics file tests pass unchanged.
  - Tracer gate: the `<verify>` set (test_rationale, test_decision_alignment_params, test_analytics_files, test_kill_gate_families, plus test_registry and test_registry_gate) was re-run end to end and passed before expansion.
- Task 2: gate PA-08 (`check_phase15_set_facts`) over `PHASE15_SET_IDS` (three baseline-v6 ids and two -v4 ids): version `v5.0.0`, `geometry_version == 1` (int), the four frozen Phase 12 guard values and types, rate keys within 0..0.01, "Supersedes" in the header, empty `check_rationale`, pivot keys for trend-pullback and range-mr sets, `tp_mode` for range-mr, `min_stop_atr` in every trend-pullback Phase 15 set (failure message names ROADMAP criterion 1), cost keys including `exit_slippage_rate` identical across the five. Registered in `run()`; docstring and imports updated (commit c800f3d).
  - 24 new test cases: constants, pass-on-copy, wrong version, missing and wrong geometry_version, changed frozen guard, differing cost value, deleted rationale table, removed Supersedes, range-mr without tp_mode, eight pivot-key removals (both keys, four sets), three min_stop_atr removals (baseline-v6 and both -v4 baselines, each asserting the ROADMAP criterion 1 wording), missing file, PA-07 isolation, and exact pin-set equality replacing the bare count.
- `python -m scripts.decision_alignment.params` reports PA-01..PA-08 all ok on the real repository.

## Regeneration inventory

New pins appended to `tests/fixtures/phase4/parameters.json` (list now 25 entries; `scripts/_regen_phase4_expectations.py` was not run; the diff is 12 inserted lines):

| strategy_id | parameter_set_id | strategy_version | parameter_set_hash |
|---|---|---|---|
| trend-pullback | baseline-no-trade-v4 | v5.0.0 | 98e541eec72b3771f73adaae6f039d2de2a2ef9bcb66baa4d3507d3fe32bac9c |
| trend-pullback | baseline-simple-trend-v4 | v5.0.0 | 27f4c18b92b44c28387299edb69be32977e3ab48004c1b0301fbbcc2e0d08c5f |

Moved digests: none. No existing pin, file byte lock or `parameter_set_hash` changed; PA-01..PA-07 still pass. The two baseline ids are not family candidates, so no candidate hash list in the analytics scan changed.

## Deviations from Plan

None - plan executed exactly as written.

## Notes

- **Basis of the overridden values (carried over from 15-08, for the user's attention).** The checkpoint text names no basis for `minimum_rr 100`, `zone_tolerance_atr 1.0` and `minimum_rr 0.5`; they are recorded as DECISION with ref D054 following the wording of this plan. D054 does not exist yet in docs/DECISIONS.md (a later Phase 15 plan writes it); `check_rationale` only requires the form D plus three digits.
- **Omitted keys.** As in baseline-v6, `risk_rate`, `breakout_confirmation_bars` and `atr_period` are not written in the -v4 sets (no module under src/ reads them for this family); the ratified table has no row for them.
- **PLACEHOLDER keys.** baseline-no-trade-v4 has 15 (v6's 16 minus `minimum_rr`), baseline-simple-trend-v4 has 14 (minus `zone_tolerance_atr` and `minimum_rr`); both stay research-only because `pin_stream_epoch` refuses PLACEHOLDER keys.
- **Pre-existing, out of scope.** `tests/test_phase6_fixture_geometry.py::test_generator_is_deterministic_and_matches_committed_fixtures` (CRLF vs LF) already in deferred-items.md; not touched.

## Verification

- `pytest tests/test_decision_alignment_params.py tests/test_rationale.py tests/test_analytics_files.py tests/test_kill_gate_families.py tests/test_registry_gate.py tests/test_registry.py tests/test_decision_alignment.py`: all pass (one skipped test is pre-existing).
- `ruff check src tests scripts`: clean; `ruff format --check src tests scripts`: 387 files formatted; `mypy src`: no issues in 149 files.
- Targeted suites only, foreground; no background process left.

## Known Stubs

None. PLACEHOLDER values are ratified, labelled values, not stubs.

## Threat Flags

None. T-15-17 mitigated: PA-08 plus exact pin-set equality, each check proven by a negative test on a params copy. T-15-SC accepted (no installs).

## Self-Check: PASSED

- FOUND: params/trend-pullback/baseline-no-trade-v4.toml, params/trend-pullback/baseline-simple-trend-v4.toml
- FOUND: commits a1aac86, c800f3d
- FOUND: "Supersedes baseline-no-trade-v3" and "Supersedes baseline-simple-trend-v3" headers, `^min_stop_atr = ` in both, 25 pins, `"PA-08"` and `PHASE15_SET_IDS` in scripts/decision_alignment/params.py
