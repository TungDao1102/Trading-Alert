---
phase: 06-backtest-simulator-experiment-registry
plan: 02
subsystem: backtest
tags: [experiment-registry, six-field-identity, baseline, reproducibility, cost-model-hash]

# Dependency graph
requires:
  - phase: 06-backtest-simulator-experiment-registry
    provides: "Phase 6 plan 01 backtest simulator + cost model + fixture generator"
provides:
  - "ExperimentRecord frozen dataclass with six-field identity (experiment_id, strategy_version, parameter_set_hash + parameter_set_id alongside, data_snapshot_id, code_version, cost_model_hash)"
  - "assemble() builds experiment_id via sha256_hex over the identity payload"
  - "reproduce() reruns simulator.run with the recorded tuple"
  - "verify_experiment() returns None when reproducible, raises ExperimentReproducibilityBroken on drift"
  - "baseline_no_trade() and baseline_simple_trend() delegating to simulator.run with degenerated parameter sets"
  - "Registry STRATEGY_KEYS extended with four cost keys (funding_treatment, slippage_model, spread_fill_assumptions, partial_fill_fraction)"
  - "STRING_KEYS set for string-valued cost-model keys with non-empty validation"
affects: [06-03, 06-04, 07-paper, 08-approval, 10-journal]

# Actuals (#2632) — pairs with the plan's `estimate` to calibrate future estimates.
# Same estimateTokens scale (chars/4 over the realized diff), never a harness token count.
# Note: the diff includes ~12,396 lines of copied fixture data (the intrabar_both_touched
# candle sequence reused for baseline cases); the new code work is ~1,062 lines.
actuals:
  tokens: 92668
  tasks: 3
  commits: 3
  plan_head_before: "1932afb"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Six-field identity tuple assembled via sha256_hex (D-03 + RESEARCH_PROTOCOL §5)"
    - "parameterSetId alongside parameterSetHash (not inside hash payload) per CONFIGURATION §7"
    - "Universe hash sorts symbols alphabetically before hashing for order-stability"
    - "Baselines delegate to simulator.run with parameter-set-degenerated TOML files"
    - "Local _require helpers in experiment.py delegate _require_utc_aware to src/core/types.py"

key-files:
  created:
    - "src/backtest/experiment.py"
    - "tests/test_backtest_experiment.py"
    - "tests/fixtures/phase6/registry_identity/input.json"
    - "tests/fixtures/phase6/registry_identity/expected.json"
    - "tests/fixtures/phase6/baselines/no_trade/input.json"
    - "tests/fixtures/phase6/baselines/no_trade/expected.json"
    - "tests/fixtures/phase6/baselines/simple_trend/input.json"
    - "tests/fixtures/phase6/baselines/simple_trend/expected.json"
    - "params/trend-pullback/baseline-no-trade-v1.toml"
    - "params/trend-pullback/baseline-simple-trend-v1.toml"
  modified:
    - "src/domain/registry.py"
    - "src/backtest/__init__.py"

key-decisions:
  - "[06-02] D-01 assemble() loads parameter_set from registry (fail closed on UnregisteredParameterSet); the experiment_id is built from parameter_set.parameter_set_hash, not from a re-hash of the parameters"
  - "[06-02] D-02 universe_hash sorts symbols alphabetically before sha256_hex so input order cannot change identity (REFACTOR task)"
  - "[06-02] D-03 baselines (no_trade, simple_trend) are NEW TOML files in params/trend-pullback/ (baseline-no-trade-v1.toml with minimum_rr=100; baseline-simple-trend-v1.toml with looser zone + minimum_rr=0.5); baseline runners delegate to simulator.run with the new parameter_set_id"
  - "[06-02] D-04 baselines filter simulator.run output to filled trades only (entry_kind in {ENTRY_FILLED, PARTIAL_FILL}); REJECT records are risk-rejection outcomes, not filled trades"
  - "[06-02] D-05 STRING_KEYS set added alongside INT_KEYS and DECIMAL_KEYS in registry.py; three string-valued cost keys (funding_treatment, slippage_model, spread_fill_assumptions) validated as non-empty strings; partial_fill_fraction classified as DECIMAL_KEYS"

patterns-established:
  - "Pattern 1: six-field experiment identity follows D-03 + RESEARCH_PROTOCOL §5 verbatim field names; experiment_id = sha256_hex over {strategy_version, parameter_set_hash, data_snapshot_id, code_version, cost_model_hash, time_range_start_utc, time_range_end_utc, universe_hash}"
  - "Pattern 2: ExperimentRecord.__post_init__ validates all six identity fields are 64-hex strings and raises IncompleteExperimentRecord on missing/malformed fields (D-03 acceptance gate)"
  - "Pattern 3: Baseline runners preserve execution semantics by delegating to simulator.run identically (BACKTEST_SPEC §9); only the parameter set is degenerated via new TOML files"

requirements-completed: [BKTS-02]

# Coverage metadata (#1602) — one entry per shipped deliverable.
coverage:
  - id: D1
    description: "ExperimentRecord frozen dataclass with six-field identity + __post_init__ validation"
    requirement: BKTS-02
    verification:
      - kind: unit
        ref: "tests/test_backtest_experiment.py#test_experiment_assemble_stable_64_hex_identity"
        status: pass
      - kind: unit
        ref: "tests/test_backtest_experiment.py#test_experiment_assemble_missing_field_raises"
        status: pass
    human_judgment: false
  - id: D2
    description: "reproduce() + verify_experiment() runtime tripwire for byte-identical reproduction"
    requirement: BKTS-02
    verification:
      - kind: unit
        ref: "tests/test_backtest_experiment.py#test_experiment_reproduce_byte_identical"
        status: pass
      - kind: unit
        ref: "tests/test_backtest_experiment.py#test_verify_experiment_returns_none_when_reproducible"
        status: pass
      - kind: unit
        ref: "tests/test_backtest_experiment.py#test_run_twice_record_stability"
        status: pass
    human_judgment: false
  - id: D3
    description: "Unregistered parameterSetId fails closed with UnregisteredParameterSet"
    requirement: BKTS-02
    verification:
      - kind: unit
        ref: "tests/test_backtest_experiment.py#test_experiment_unregistered_set_fails_closed"
        status: pass
    human_judgment: false
  - id: D4
    description: "No-trade baseline (minimum_rr=100) returns empty filled-trade list"
    requirement: BKTS-02
    verification:
      - kind: unit
        ref: "tests/test_backtest_experiment.py#test_baseline_no_trade_returns_empty_trades"
        status: pass
    human_judgment: false
  - id: D5
    description: "Simple-trend baseline (looser minimum_rr + wider zone) returns single-direction trade list"
    requirement: BKTS-02
    verification:
      - kind: unit
        ref: "tests/test_backtest_experiment.py#test_baseline_simple_trend_returns_single_direction"
        status: pass
    human_judgment: false
  - id: D6
    description: "costModelHash differs between fee_rate_entry 0.00020 vs 0.0002 (trailing-precision discipline)"
    requirement: BKTS-02
    verification:
      - kind: unit
        ref: "tests/test_backtest_experiment.py#test_cost_model_hash_precision_discipline"
        status: pass
    human_judgment: false
  - id: D7
    description: "Empty simulator_inputs yields valid ExperimentRecord with empty trade list (no exception)"
    requirement: BKTS-02
    verification:
      - kind: unit
        ref: "tests/test_backtest_experiment.py#test_empty_input_yields_valid_record_with_zero_trades"
        status: pass
    human_judgment: false
  - id: D8
    description: "Universe order stability — input order cannot change identity"
    requirement: BKTS-02
    verification:
      - kind: unit
        ref: "tests/test_backtest_experiment.py#test_universe_order_stability"
        status: pass
    human_judgment: false

# Metrics
duration: 45min
completed: 2026-09-26
status: complete
---

# Phase 6 Plan 2: Experiment Registry Summary

**Versioned experiment registry with six-field identity, fail-closed reproduction, and same-engine no-trade + simple-trend baselines**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-09-26T12:55:00Z
- **Completed:** 2026-09-26T13:40:00Z
- **Tasks:** 3 (RED, GREEN, REFACTOR)
- **Files modified:** 12

## Accomplishments

- `ExperimentRecord` frozen dataclass carrying the canonical six-field identity tuple per D-03 + BACKTEST_SPEC §11 + RESEARCH_PROTOCOL §5
- `assemble()` builds the `experiment_id` via `sha256_hex` over the identity payload; loads parameter set from the registry (fail closed on `UnregisteredParameterSet`)
- `reproduce()` re-runs `simulator.run` with the recorded tuple; `verify_experiment()` returns None when reproducible, raises `ExperimentReproducibilityBroken` on drift
- `baseline_no_trade()` + `baseline_simple_trend()` delegate to `simulator.run` with degenerated parameter sets via NEW TOML files (baseline-no-trade-v1.toml with minimum_rr=100; baseline-simple-trend-v1.toml with looser zone + minimum_rr=0.5)
- Registry `STRATEGY_KEYS` extended with the four missing cost keys (funding_treatment, slippage_model, spread_fill_assumptions, partial_fill_fraction); `STRING_KEYS` set added for string-valued keys
- Universe hash sorts symbols alphabetically before hashing for order-stability (D-03)
- 11 experiment tests cover identity stability, missing-field gate, reproduce byte-identity, unregistered fail-closed, both baselines, cost-hash precision, empty-input handling, run-twice stability, and universe-order stability

## Task Commits

Each task was committed atomically:

1. **Task 1: RED — failing experiment identity and baseline tests plus fixtures** — `6f0e4bc` (test)
2. **Task 2: GREEN — experiment module, registry cost keys, baseline runners** — `67262df` (feat)
3. **Task 3: REFACTOR — empty-input handling, run-twice stability, universe-order stability, helper delegation** — `eecc3bc` (refactor)

**Plan metadata:** (this docs commit)

## Files Created/Modified

- `src/backtest/experiment.py` — ExperimentRecord, exceptions, assemble/reproduce/verify_experiment/baseline_no_trade/baseline_simple_trend
- `src/backtest/__init__.py` — re-export the experiment module public API
- `src/domain/registry.py` — extend STRATEGY_KEYS with four cost keys; add STRING_KEYS set
- `tests/test_backtest_experiment.py` — 11 tests covering all 8 behaviors in the plan's must_haves
- `tests/fixtures/phase6/registry_identity/input.json` + `expected.json` — six-field identity fixture
- `tests/fixtures/phase6/baselines/no_trade/input.json` + `expected.json` — no-trade baseline fixture
- `tests/fixtures/phase6/baselines/simple_trend/input.json` + `expected.json` — simple-trend baseline fixture
- `params/trend-pullback/baseline-no-trade-v1.toml` — minimum_rr=100
- `params/trend-pullback/baseline-simple-trend-v1.toml` — looser zone + minimum_rr=0.5

## Decisions Made

- **D-01:** `assemble()` loads `parameter_set` from the registry and uses `parameter_set.parameter_set_hash` (the registry's canonical hash) inside the `experiment_id` payload — never re-hashes the parameters. This binds the experiment identity to the registry's authoritative hash, so a parameter set mutation is detected at load time (Phase-3 D-05) and the experiment identity changes accordingly.
- **D-02:** `universe_hash` sorts symbols alphabetically before `sha256_hex` so input order cannot change identity (D-03 + REFACTOR task).
- **D-03:** Baselines are NEW TOML files in `params/trend-pullback/` (not ambient edits to `baseline-v2`). The baseline runners delegate to `simulator.run` with the new `parameter_set_id`. This preserves the registry whitelist + fail-closed gates (D-06) and keeps execution semantics identical (BACKTEST_SPEC §9).
- **D-04:** Baselines filter simulator output to filled trades only (`entry_kind in {ENTRY_FILLED, PARTIAL_FILL}`). REJECT records are risk-rejection outcomes, not filled trades — the "empty trade list" semantics hold when no plan passes the gates.
- **D-05:** `STRING_KEYS` set added alongside `INT_KEYS` and `DECIMAL_KEYS` in `registry.py`. Three string-valued cost keys (funding_treatment, slippage_model, spread_fill_assumptions) validated as non-empty strings; partial_fill_fraction classified as DECIMAL_KEYS (its type is Decimal).
- **D-06:** `_require_utc_aware` delegated to `src/core/types.py` (shared helper, D-12 fail-closed); the other two helpers (`_require_non_empty_str`, `_require_64_hex`) are experiment-specific. The existing `simulator.py` and `costs.py` keep their local copies — consolidating them is a future refactor scope.

## Deviations from Plan

None - plan executed exactly as written. All 3 tasks completed in order; all acceptance criteria met.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Experiment registry is ready for plan 06-03 (uncertainty-first reporting) and plan 06-04 (CLI integration).
- The `assemble() → reproduce() → verify_experiment()` pipeline is the canonical reproducibility tripwire; later phases (paper forward-observation in Phase 7, approval binding in Phase 8) can rely on byte-identical reproduction from dataset + strategy + parameter set + cost + execution versions.
- Cost keys are now in the registry whitelist; new cost assumptions will fail closed at load time instead of being silently shared across experiments.
- No blockers for the next phase.

---

*Phase: 06-backtest-simulator-experiment-registry*
*Completed: 2026-09-26*
