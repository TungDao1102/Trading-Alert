---
phase: 14-backtest-causality-rewrite
plan: 04
subsystem: backtest
tags: [backtest, cost-identity, funding, hashing, fixtures, tdd, decimal]

requires:
  - phase: 14-backtest-causality-rewrite
    provides: "plan 14-01 semantics.FUNDING_CONVENTION = MARK_NOTIONAL_SIGNED_V1"
  - phase: 12-fee-cost-model-correctness
    provides: "presence-driven optional cost key exit_slippage_rate (D-14 option B) and the hash-to-hash binding gates"
provides:
  - "src/backtest/costs.py: CostModel.funding_convention, OPTIONAL_COST_KEYS with funding_convention, cost_slice append rule, value validation"
  - "Nine-key cost identity for every sizeable (exit_slippage_rate) registry set; seven-key legacy hashes byte-locked"
  - "Regenerated phase6 simulator/baseline inputs and phase7 parity input/expected (inventory below, feeds D053 in 14-16)"
affects: [14-05, 14-06, 14-07, 14-08, 14-09, 14-10, 14-11, 14-12, 14-13, 14-15, 14-16]

actuals:
  tokens: 7000
  tasks: 3
  commits: 4
plan_head_before: 2ba8bec92a9716b791aa7b4309f1dfbd0dbc670a
plan_head_after: d4fd13da77670f0116d0ebe53da6a131091a46d7

tech-stack:
  added: []
  patterns:
    - "Per-key presence-driven optional cost keys: each optional key joins the hash payload only when the model carries it"
    - "String cost key hashed as-is (absent from _NUMERIC_HASH_KEYS), numerics hashed as canonical text"
    - "Code-constant cost key: cost_slice appends semantics.FUNDING_CONVENTION, never a params/ value"

key-files:
  created: []
  modified:
    - src/backtest/costs.py
    - tests/test_cost_per_unit.py
    - tests/test_backtest_binding.py
    - tests/test_phase6_fixture_geometry.py
    - tests/test_backtest_experiment.py
    - tests/test_backtest_simulator.py
    - scripts/gen_phase6_fixtures.py
    - tests/fixtures/phase7/parity_overlapping_history/expected.json

key-decisions:
  - "funding_convention is the only funding fact in the cost hash; funding data identity rides in data_snapshot_id plus recorded allowed_gaps (D-36)"
  - "Hash payload became per-key presence (not 'all optional keys iff exit_slippage_rate'), so a model may carry funding_convention without exit_slippage_rate; cost_slice still only ever appends both together"
  - "gen_phase6_fixtures.py writes the convention as a literal (the script imports nothing from src/); drift is guarded by a test comparing the generator literal and every fixture to FUNDING_CONVENTION and by the sizing binding gate"
  - "Hand-built cost dicts in test_cost_parity, test_paper_parity, test_case_input_builder and the _COST8 dict in test_backtest_simulator do not bind a registry set (no gate, no registry hash compare), so they were deliberately left untouched"

patterns-established:
  - "A fixture or hand-built v5 cost dict lacking funding_convention is refused by both binding gates (CostModelBindingMismatch)"

requirements-completed: [BKTS-02]

duration: 35min
completed: 2026-10-04
status: complete
---

# Phase 14 Plan 04: Funding Convention in Cost Identity Summary

**The funding sign convention now joins experiment identity as one presence-driven string cost key, appended by `cost_slice` for every sizeable set, with all legacy seven-key hashes byte-identical and the changed v5 hash derived from the registry rather than typed.**

## Performance

- **Duration:** about 35 min (includes two full-suite runs of about 9 min each)
- **Tasks:** 3 (1 tracer, 2 auto)
- **Files modified:** 18 (8 hand-edited, 10 regenerated fixture inputs; expected.json counted in the 8)

## Accomplishments

- `cost_slice(params)` for baseline-v5, baseline-no-trade-v3 and baseline-simple-trend-v3 (all five `V5_SETS`) now returns the seven `COST_KEYS` plus `exit_slippage_rate` plus `funding_convention == FUNDING_CONVENTION`. Legacy sets (v3/v4 and the v1/v2 baselines) still slice to exactly seven keys; every `LEGACY_COST_HASHES` case passes unchanged.
- `CostModel` gained a trailing defaulted `funding_convention: str | None = None`. A present value must equal `semantics.FUNDING_CONVENTION` (ValueError naming the accepted value otherwise); `build_cost_model` reads it by presence through `_require_cost_str` (non-string, empty string, bytes, `None` raise TypeError).
- `COST_KEYS` stays seven keys; `funding_convention` is in `OPTIONAL_COST_KEYS` and deliberately not in `_NUMERIC_HASH_KEYS` (hashed as-is). Nine keys hash for a v5 model.
- Both gates (`assert_cost_model_binds_registry`, `assert_sizing_costs_bind_registry`) work hash-to-hash without any change to `src/backtest/binding.py`: a v5 model lacking the convention is refused, one carrying it passes. `simulator.run` refuses a v5 fixture cost dict that lacks it.
- The generator and ten fixture inputs were regenerated; each input changed by exactly one added line. A second generator run leaves `git status --porcelain tests/fixtures` empty.

## Task Commits

1. **Task 1: Tracer** - `ff9b8ed` (test, RED), `bbf0f07` (feat, GREEN)
2. **Task 2: Regenerate fixtures** - `09894ca` (feat)
3. **Task 3: Pin the convention in geometry, generator-literal and run-binding tests; full suite green** - `d4fd13d` (test)

**Plan metadata:** committed separately after this file (docs: complete plan).

## Regeneration inventory

Reason for every row: funding_convention joins cost identity (D-16, D-36). For D053 in plan 14-16.

| File / pin | Item | Old value | New value |
|------------|------|-----------|-----------|
| registry-derived v5 `cost_model_hash` (trend-pullback/baseline-v5, breakout-retest/baseline-v5, range-mr/baseline-v5, trend-pullback/baseline-no-trade-v3, trend-pullback/baseline-simple-trend-v3; all five share one hash) | hash | `3063dc390cecf6d7a19c2bbb338629990db366fd881f5383151ccb0bcd07a0d4` | `6d6c4e237ed0b56996ed344f4449b09a59c253a8d148af60e3aba1c8436f1caa` |
| `tests/fixtures/phase7/parity_overlapping_history/expected.json` | `cost_model_hash` | `3063dc39...a07a0d4` (above) | `6d6c4e23...36f1caa` (above), re-derived with the existing parity computation `build_cost_model(cost_slice(load_parameter_set(...).params))` that `tests/test_paper_parity.py` asserts, not typed |
| `tests/fixtures/phase7/parity_overlapping_history/expected.json` | `digest` | `d06c739aa73e0aec8033908086f25da78525ace4d422356a88fcfd4e2d4d3efe` | unchanged (verdict digest does not cover the cost hash; verified, test still passes) |
| `tests/fixtures/phase7/parity_overlapping_history/expected.json` | `parameter_set_hash` | `41ed39d4...ac3df9` | unchanged |
| `tests/fixtures/phase7/parity_overlapping_history/input.json` | key added `cost_model.funding_convention` | absent | `"MARK_NOTIONAL_SIGNED_V1"` |
| `tests/fixtures/phase6/intrabar_both_touched/input.json` | key added | absent | same |
| `tests/fixtures/phase6/intrabar_both_touched_short/input.json` | key added | absent | same |
| `tests/fixtures/phase6/intrabar_missing_fallback/input.json` | key added | absent | same |
| `tests/fixtures/phase6/invalidation_cancels_entry/input.json` | key added | absent | same |
| `tests/fixtures/phase6/limit_expiry/input.json` | key added | absent | same |
| `tests/fixtures/phase6/limit_partial_fill/input.json` | key added | absent | same |
| `tests/fixtures/phase6/limit_touch_no_fill/input.json` | key added | absent | same |
| `tests/fixtures/phase6/baselines/no_trade/input.json` | key added | absent | same |
| `tests/fixtures/phase6/baselines/simple_trend/input.json` | key added | absent | same |
| `scripts/gen_phase6_fixtures.py` | `COST_MODEL` dict (and "nine-key" docstring) | eight keys | nine keys, `funding_convention` literal |
| `tests/test_phase6_fixture_geometry.py` | `EXPECTED_COST_KEYS` | eight keys | nine keys plus equality to `FUNDING_CONVENTION` |

Not moved (verified by the green suite): every `LEGACY_COST_HASHES` entry, all `params/` files, `registry_identity` and `report_slices` fixtures, phase5/phase9 fixtures, paper-freeze epoch pins (no test pinned a v5 cost hash outside the parity expected.json), `src/backtest/binding.py`. The old value above was reproduced by building the same v5 slice without the convention, matching the previously pinned `3063dc39...`, which confirms the eight-key payload remains byte-stable.

## Decisions Made

See `key-decisions` in the frontmatter.

## Deviations from Plan

### Auto-fixed Issues

None needed for correctness. Departures from the literal plan text, recorded for later plans:

**1. Hand-built cost dicts in test_cost_parity.py, test_paper_parity.py, test_case_input_builder.py and test_backtest_simulator.py `_COST8` were not edited**
- **Found during:** Task 3
- **Reason:** the plan says to add the key to hand-built dicts "that bind a set carrying exit_slippage_rate". The full suite was green after Task 2 apart from the nine geometry tests, so none of these dicts reaches a binding gate. Adding the key where no gate reads it would add noise without coverage.
- **Instead:** `tests/test_phase6_fixture_geometry.py` (the only suite failures, nine parametrized cases) was updated; `tests/test_backtest_experiment.py` gained a generator-literal drift guard; `tests/test_backtest_simulator.py` gained `test_run_refuses_cost_dict_without_funding_convention`.

**2. Per-key hash-payload presence instead of "all optional keys iff exit_slippage_rate present"**
- A `CostModel` may now carry `funding_convention` without `exit_slippage_rate`. `cost_slice` still appends both together, so registry-derived identities are unchanged in shape. The previous rule would have hashed a `None` funding_convention into the payload.

---

**Total deviations:** 2 minor, no impact on the Interfaces contract.

## TDD Gate Compliance

Task 1 (tracer, tdd): `test(14-04)` RED commit `ff9b8ed` before `feat(14-04)` GREEN `bbf0f07`. RED evidence: 17 tests failed at runtime (no collection or import error); the one failure inspected in detail was an assertion (`set(sliced) == {...}` with `funding_convention` listed as the missing extra item). The other 16 failure reasons were not individually inspected before the GREEN commit. `gsd_run check tdd-red-evidence` was not run. Tasks 2 and 3 are `type="auto"` regeneration/test-pin tasks, committed as feat/test without a separate RED. Task 3's pins were red before the edit in the full-suite run (9 geometry failures), then green.

## Verification (real output)

- Task 1 verify: `pytest tests/test_cost_per_unit.py tests/test_backtest_binding.py` all passed (133 tests).
- Task 2 verify: generator exit 0; `grep -L funding_convention` over the ten inputs printed nothing; second generator run left `git status --porcelain tests/fixtures` empty; `tests/test_cost_per_unit.py` and `tests/test_paper_parity.py` passed.
- Full suite `uv run pytest -m "not docker" -rs -p no:cacheprovider`: `3474 passed, 423 skipped, 17 deselected in 540.32s`. The first full run (after Task 2, before Task 3) had exactly nine failures, all `tests/test_phase6_fixture_geometry.py` (`test_fixture_carries_phase12_identity` x7, `test_baseline_fixture_carries_phase12_identity` x2). Skips are the pre-existing PostgreSQL tests (`TEST_DATABASE_URL` unset).
- `ruff check`: All checks passed. `ruff format --check`: 383 files already formatted. `mypy src`: no issues in 141 source files.
- Acceptance: `'funding_convention' not in _NUMERIC_HASH_KEYS` ok; `len(COST_KEYS) == 7` ok; `FUNDING_CONVENTION` imported in costs.py; `git diff --name-only` shows no `params/` file and no `src/backtest/binding.py`.

## Known Stubs

None.

## Threat Flags

None. T-14-08 (sizeable slices always carry the convention, gates refuse a model without it, unknown values raise) and T-14-09 (`LEGACY_COST_HASHES` parametrized test green, presence-driven payload) are mitigated and test-covered.

## Next Phase Readiness

Ready for 14-05 and later plans. Anything that hand-builds a v5 cost dict and passes it to `assemble`, `simulator.run`, `run_paper_tick` or `pin_stream_epoch` must include `funding_convention` (or build it through `cost_slice`). D053 (plan 14-16) should copy the Regeneration inventory above.

## Self-Check: PASSED

Files modified exist on disk, the four task commits (`ff9b8ed`, `bbf0f07`, `09894ca`, `d4fd13d`) are in `git log`, and the plan-level verification commands re-ran green (see Verification).

---
*Phase: 14-backtest-causality-rewrite*
*Completed: 2026-10-04*
