---
phase: 11-decision-alignment
plan: 02
subsystem: parameter-registry
tags: [parameter-registry, d036, d037, d038, pins, byte-lock, working-type]
status: complete

requires:
  - phase: 11-decision-alignment
    provides: plan 11-01 protocol v1.1.0 (D036-D038 alignment statement, gate-module pattern)
provides:
  - Five new versioned parameter sets (trend-pullback baseline-v4, baseline-no-trade-v2, baseline-simple-trend-v2; breakout-retest baseline-v4; range-mr baseline-v4), strategy_version v3.0.0
  - Registry support for optional closed-set working_type key (MARK_PRICE, CONTRACT_PRICE), not a cost key
  - Pins for all 15 parameter sets (registry-gate re-hash step green)
  - scripts/decision_alignment/params.py gates PA-01..PA-06
affects: [11-03, 12-exchange-truth, 14-causal-simulator, 26-analytics-gates]

actuals:
  tokens: 9000
  tasks: 3
  commits: 3
plan_head_before: 417c8d7b1b61376aaae30479f35b56676b9d8729
plan_head_after: 3f7d196b608abdf98470641d1ef1f33925255b91

tech-stack:
  added: []
  patterns:
    - "Superseding parameter sets: old files are never edited; the Supersedes note lives in the new file header"
    - "Byte lock on immutable files via LF-normalised sha256, CRLF tolerated"
    - "Gate helpers take a params root so negative tests run against tmp_path copies"

key-files:
  created:
    - params/trend-pullback/baseline-v4.toml
    - params/trend-pullback/baseline-no-trade-v2.toml
    - params/trend-pullback/baseline-simple-trend-v2.toml
    - params/breakout-retest/baseline-v4.toml
    - params/range-mr/baseline-v4.toml
    - scripts/decision_alignment/params.py
    - tests/test_decision_alignment_params.py
  modified:
    - src/domain/registry.py
    - tests/fixtures/phase4/parameters.json
    - tests/test_registry.py
    - tests/test_analytics_files.py

key-decisions:
  - "working_type is a registry string key with a closed value set, fail closed at load; it is deliberately outside COST_KEYS so no cost_model_hash moves"
  - "Seven previously unpinned sets were registered from their unchanged pre-change loader hashes (pin registration, not regeneration); three baseline-v1 pins untouched"
  - "range-mr gets baseline-v4 (no v3 exists) carrying all seven cost keys so it binds like the other families"
  - "The -v2 baselines keep the baseline-* prefix, so RSCH-02 family independence is unaffected"

requirements-completed: [RSCH-01, RSCH-02]

coverage:
  - id: D1
    description: "Five aligned candidate/baseline sets carry taker entry fee 0.0005, partial_fill_fraction 1, working_type MARK_PRICE, strategy_version v3.0.0"
    requirement: "RSCH-02"
    verification:
      - kind: unit
        ref: "tests/test_registry.py::test_v4_sets_match_d036_d038 and tests/test_decision_alignment_params.py (PA-04)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Old sets provably untouched: ten LF-normalised file digests and ten parameter_set_hash values locked"
    requirement: "RSCH-01"
    verification:
      - kind: unit
        ref: "tests/test_registry.py::test_pre_phase_11_hashes_and_versions_are_unchanged; PA-02, PA-03"
        status: pass
    human_judgment: false
  - id: D3
    description: "Registry gate re-hash step green for all 15 sets; working_type closed-set validation"
    requirement: "RSCH-01"
    verification:
      - kind: unit
        ref: "tests/test_registry.py::test_every_params_toml_has_a_pin_that_verifies, working_type tests; PA-01, PA-06"
        status: pass
    human_judgment: false
---

# Phase 11 Plan 02: D036-D038 Parameter Sets, working_type Key and Complete Pins Summary

**Five new v3.0.0 parameter sets carry taker entry fees, full fills and MARK_PRICE triggers, the registry accepts working_type as a closed-set key, and all 15 sets are pinned with the ten old files and hashes locked.**

## Performance

- **Duration:** about 25 min
- **Completed:** 2026-09-30
- **Tasks:** 3 (1 tracer, 2 auto/tdd)
- **Files:** 11 (7 created, 4 modified); no existing params file touched

## Accomplishments

- Step 0 recomputed all ten pre-phase hashes, strategy versions and LF-normalised file digests from the untouched tree: every value equals the plan's reference constants.
- `src/domain/registry.py`: `working_type` added to `STRATEGY_KEYS` and `STRING_KEYS`, `WORKING_TYPE_VALUES` frozenset, closed-set check in `_check_param_types`. Diff touches only those spots plus comments; `src/backtest/costs.py` untouched.
- Pin file grew from 3 to 15 entries: seven registrations from pre-change hashes (breakout-retest baseline-v2/v3, range-mr baseline-v2, trend-pullback no-trade-v1, simple-trend-v1, baseline-v2, baseline-v3) and five new sets; `git diff` against 679825c shows only added entries.
- `git diff 679825c --name-status -- params/` lists exactly five added files and nothing else.
- All five new sets share one `cost_model_hash` (PA-05).
- The registry-gate CI defect (F6: seven unpinned sets, red gate) is closed; `test_every_params_toml_has_a_pin_that_verifies` mirrors the workflow's re-hash step.

## Task Commits

1. Task 1 (tracer): `313384d` - working_type key, pins for all existing sets, trend-pullback baseline-v4, family-scan expectation
2. Task 2: `f87d2a1` - breakout-retest and range-mr baseline-v4, pins, parametrised v4-facts tests
3. Task 3: `3f7d196` - baseline-no-trade-v2, baseline-simple-trend-v2, gate module PA-01..PA-06 and negative tests

## Verification

- `pytest tests/test_decision_alignment_params.py tests/test_registry.py tests/test_registry_gate.py tests/test_analytics_files.py tests/test_paper_freeze.py tests/test_backtest_binding.py tests/test_backtest_experiment.py`: all pass (one pre-existing symlink skip in test_analytics_files).
- `python -c ... params.run()`: 6 gates, 0 failed.
- `ruff check` on registry.py and every new/changed test and script: clean; `mypy src/domain/registry.py` and `mypy scripts/decision_alignment/params.py`: clean.

## Deviations from Plan

### Ordering notes

**1. [Ordering] Task 3 gate module written before its tests**
- The `params.py` gate module was written before `tests/test_decision_alignment_params.py`, so RED against a missing module was not demonstrated. The negative tests do exercise each gate against broken tmp copies (edited old file, unpinned extra file, 0.5 fill, different fee, CRLF copy), which is the behavioural evidence the plan asked for.

**2. [Ordering] Per-task single commits instead of separate RED commits**
- Tasks 1 and 2 ran RED (confirmed failing pin, working_type-content and v4 tests before the files/registry change) but were committed once per task, matching the acceptance criteria and the 11-01 convention.

**Total deviations:** 0 auto-fixes, 2 ordering notes. **Impact:** none on scope or outputs.

## Issues Encountered

None. The tracer verify commands (pytest, mypy, ruff) passed on the first GREEN run.

## Known Stubs

None.

## Threat Flags

None. T-11-05 (silent mutation / unpinned sets) mitigated by PA-01..PA-03; T-11-06 (working_type bypass) mitigated by the closed-set check with loader tests for LAST, empty string, int, bool and case variants; T-11-07 (ambient key named working_type now rejected) accepted and documented in the registry.py comment (runtime configuration must use a different name).

## Next Phase Readiness

Ready for 11-03. Follow-ups: the fee_rate_entry = 0.0005 taker value is assumed equal to fee_rate_exit until Phase 12 reads the account commission rate; the "superseded by v4" mention in the DECISIONS summary row and CONFIGURATION runtime-config guidance (working_type name reserved) belong to later Phase 11 plans.

## Self-Check: PASSED

All seven created files exist; commits 313384d, f87d2a1, 3f7d196 found in git log; task acceptance commands re-run green.
