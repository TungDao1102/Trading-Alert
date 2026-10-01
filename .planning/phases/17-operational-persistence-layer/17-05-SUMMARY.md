---
phase: 17-operational-persistence-layer
plan: 05
subsystem: domain
tags: [plan-hash, decimal, quantization, canonicalization, determinism, tdd]

requires:
  - phase: 17-operational-persistence-layer
    provides: "plan 01: persistence foundations (NUMERIC(38,18) plan columns)"
provides:
  - "src/domain/canonical.py: canonical_decimal_text (D047 helper moved), STORAGE_DECIMAL_PLACES = 18, quantize_for_storage (ROUND_HALF_EVEN, local prec 60)"
  - "src/core/planner.py: every persisted plan Decimal and every TP price quantized to 18 fractional digits before JSON build and hashing; _plan_hash is spelling-invariant"
  - "tests/test_domain_canonical_decimal.py and planner tests for storage-scale values and spelling-invariant hash"
  - "Regeneration inventory for D051 (one fixture: tests/fixtures/phase4/expected_plans.json)"
affects: [17-10, 17-15]

actuals:
  tokens: 6900
  tasks: 3
  commits: 3
plan_head_before: 365bcbbb608843bd93f5da87688403017ada2e46
plan_head_after: f63e64cc750a1fb72b22aa3de152c6eca77f4c6d

tech-stack:
  added: []
  patterns:
    - "One rounding rule for every persisted plan value: ROUND_HALF_EVEN to 18 places, applied where the geometry is final, with downstream sizing computed from the quantized prices"
    - "Hash inputs that are Decimals go through canonical_decimal_text so a PostgreSQL fixed-scale read-back hashes like the in-memory value"

key-files:
  created:
    - tests/test_domain_canonical_decimal.py
  modified:
    - src/domain/canonical.py
    - src/backtest/costs.py
    - src/core/planner.py
    - tests/test_core_planner.py
    - tests/fixtures/phase4/expected_plans.json

key-decisions:
  - "Task 1 checkpoint:decision auto-selected option id: locked (CONTEXT D-12: quantize to the NUMERIC(38,18) scale with ROUND_HALF_EVEN, canonical decimal text in _plan_hash)"
  - "canonical_scalars and canonical_bytes untouched; no guard added to TradePlan (the store-boundary PrecisionError guard and PG round-trip test are plan 10)"
  - "TP prices in take_profit_json stay str() of the quantized Decimal (so they carry 18 fractional digits, the same spelling a NUMERIC read-back returns); expected_rr_json and invalidation_rule_json break_distance_atr stay unquantized TEXT"
  - "quantize_for_storage raises ValueError (never a wrong value) for non-finite input or a result that exceeds the 60-digit working precision"

patterns-established:
  - "Plan 10 can assert value == quantize_for_storage(value) at the store boundary and recompute _plan_hash from a read-back row"

requirements-completed: [DOMN-01, APRV-02]

coverage:
  - id: D1
    description: "canonical_decimal_text matches the old D047 behavior and quantize_for_storage rounds half-even to 18 places, fails closed on non-finite or oversize input and ignores ambient precision"
    requirement: DOMN-01
    verification:
      - kind: unit
        ref: "tests/test_domain_canonical_decimal.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Every persisted planner Decimal and TP price has at most 18 fractional digits and plan_hash recomputes from the canonical text of the stored fields; hash is spelling-invariant"
    requirement: APRV-02
    verification:
      - kind: unit
        ref: "tests/test_core_planner.py#test_persisted_decimals_fit_numeric_38_18"
        status: pass
      - kind: unit
        ref: "tests/test_core_planner.py#test_plan_hash_recomputable_from_payload"
        status: pass
      - kind: unit
        ref: "tests/test_core_planner.py#test_plan_hash_is_spelling_invariant"
        status: pass
    human_judgment: false
  - id: D3
    description: "Cost hashes did not move: tests/test_cost_per_unit.py unchanged since 99d3a94 and passing"
    requirement: DOMN-01
    verification:
      - kind: unit
        ref: "tests/test_cost_per_unit.py"
        status: pass
    human_judgment: false

duration: 40min
completed: 2026-10-01
status: complete
---

# Phase 17 Plan 05: Reproducible plan_hash Summary

**Every persisted plan Decimal is quantized to the NUMERIC(38,18) scale (ROUND_HALF_EVEN) before JSON and hashing, and `_plan_hash` hashes canonical decimal text, so a plan read back from PostgreSQL recomputes the same hash (F-410, D-12).**

## Performance

- **Duration:** ~40 min (about 25 of them two full-suite runs of 12.5 min each)
- **Tasks:** 3 (Task 1 checkpoint auto-resolved, Task 2 TDD RED then GREEN, Task 3 regeneration)
- **Files:** 1 created, 5 modified

## Task 1: Decision

`checkpoint:decision` (gate "blocking", auto_select "locked") auto-approved under auto mode. Selected option id: **locked**. The one-way door is recorded here for D051.

## Accomplishments

- `canonical_decimal_text` moved to `src/domain/canonical.py` with the exact D047 algorithm (error text generalized to "decimal value must be finite"). `src/backtest/costs.py` imports it and keeps the private alias `_canonical_decimal_text`; the local definition is deleted.
- `STORAGE_DECIMAL_PLACES = 18` and `quantize_for_storage` added: ROUND_HALF_EVEN inside a local context of precision 60, InvalidOperation translated to ValueError, non-finite rejected.
- Planner: entry_min, entry_max, stop_loss, tp1, tp2, risk_rate, risk_budget, suggested_quantity (and so quantity_before/after_rounding) are quantized; entry reference, risk, TP2 and RR are computed from the quantized prices; `take_profit_json` and `invalidation_rule_json.level` carry the quantized values. `_plan_hash` passes `canonical_decimal_text(...)` for the three hashed Decimals.
- Behavior change in the stored plan values: values are now scale-18 (for example `risk_rate` `0.005` is now `0.005000000000000000`, `tp1` `52840.00` is now `52840.000000000000000000`). Numerically equal, different spelling, intentionally matching a NUMERIC read-back.

## Task Commits

1. Task 2 RED: `2d6eee0` test(17-05): RED for canonical decimal helper, storage-scale quantization and spelling-invariant plan hash
2. Task 2 GREEN: `b1616b2` feat(17-05): quantize persisted plan Decimals to NUMERIC(38,18) and hash canonical decimal text
3. Task 3: `f63e64c` test(17-05): regenerate phase4 expected_plans.json for D-12 storage-scale quantization and canonical hash

## Regeneration Inventory (for D051, D048 style)

The full suite was run once right after the planner change (commit b1616b2, with `TEST_DATABASE_URL` pointing at the dev PostgreSQL `trading_test`): exit 0, no failures. No test failed because of the planner change, so by the plan's rule (regenerate only what fails) no failing fixture existed. One fixture is however a byte-exact planner expectation that no test consumes (the `phase4_expected_plans` conftest fixture has no test caller), so it could not fail while being demonstrably stale; it is listed in the plan's `files_modified` and in RESEARCH's blast radius, so it was regenerated from its generator rather than left stale.

| Path | Generator command | Old sha256 | New sha256 | Reason |
|------|-------------------|------------|------------|--------|
| tests/fixtures/phase4/expected_plans.json | `.venv/Scripts/python scripts/_regen_phase4_expectations.py`, keeping only this file | working tree (CRLF): `3e4d3275fa51b2536d8310452569e0a211936911f35739a645fd91b48417f4ae`; git blob (LF): `5612e71abeafeb1efba5343218212fa73c80d70b740c9ec0c7eea9518720b5d7` | working tree (CRLF): `6c198849f35cecaf066a391018d57f41c72f46b349698142b976f57d1d3f9dad`; git blob (LF): `9488ee07028a0c4a21d143a35c3c60323692cd3d236fdb917dda400b7535d056` | D-12 storage-scale quantization and canonical-text plan hash |

Per-plan `plan_hash` movement inside that file (trend-pullback, breakout-retest, range-mr):

| Plan | Old plan_hash | New plan_hash |
|------|---------------|---------------|
| trend-pullback | a8e41ec86094d8e3dc4f99bcf44c77425aecfe6b9a6f9cdddd09ae1450d64091 | 99d38a1d1fec0eb273e15fd323099cfdfcb7700e1a7d1f06010088aae934a2c0 |
| breakout-retest | 134dc488791a4db6f05932b05be9a6e6eccf9762cf51fc783d8be96827809818 | 8b7b24eedd950b6b8326df44e17a3ea88d54dc61bc6062f5f95103f3066bda9d |
| range-mr | c9505f7440ca485db74f3ab5bbd1b0727419778ceb0d3cf4abe45145c8ae74b3 | d90a223225aa1a630cd360897867db8e68e3ed44b1a5d9958876b2d8feec01cf |

signal_id and trade_plan_id values are unchanged (they derive from signal inputs, not from plan values).

Explicitly not regenerated:

- `tests/fixtures/phase4/parameters.json`: the generator script also rewrites it, and its output differs (it drops the breakout-retest/range-mr/no-trade parameter-set entries added by later phases). That drift is unrelated to the planner change, so the generator's output for this file was reverted (`git checkout --` on that file). `expected_features.json` and `expected_signals.json` were rewritten byte-identically.
- `scripts/gen_phase6_fixtures.py` was re-run as a reproducibility probe: it wrote byte-identical files (it generates candles only, no plan-derived values). Nothing under `tests/fixtures/phase6`, `phase7` changed.
- Literal-hash fixtures (phase5, phase8, phase9, phase10): untouched, `git diff --exit-code 99d3a94 -- tests/fixtures/phase5 tests/fixtures/phase8 tests/fixtures/phase9 tests/fixtures/phase10` exits 0.
- `tests/test_core_tracer.py`: needed no edit (it pins no quantized value).
- Backtest/paper parity digests and the phase6/7 expected fixtures were unaffected (suite green with no regeneration).

## Verification (real runs)

- Task 2 verify: `pytest tests/test_domain_canonical_decimal.py tests/test_core_planner.py tests/test_cost_per_unit.py -x -q` exit 0 (RED run before the GREEN commit failed at collection with an ImportError for the new helpers).
- `mypy src`: no issues in 125 source files. `ruff check src tests`: all checks passed. `ruff format --check src tests`: 280 files already formatted. (Repo-root `ruff format --check` still trips on the planning document `17-RESEARCH.md`, already in `deferred-items.md` from plan 17-01; not touched.)
- Full suite after the fixture regeneration: `pytest -m "not docker"` -> **3135 passed, 10 skipped, 16 deselected in 751.27s**, exit 0. Skips: 1 symlinks unavailable on Windows, 1 NTFS POSIX modes, 8 `shellcheck` not on PATH (all unrelated to this plan). The first full run (before regeneration) also exited 0 with no failures.
- `scripts/verify_decision_alignment.py all`: ALL_PASS.
- Acceptance greps: `def canonical_decimal_text` once in `src/domain/canonical.py`; no `def _canonical_decimal_text` in `src/backtest/costs.py`; `ROUND_HALF_EVEN` present in canonical.py; `quantize_for_storage(` appears 9 times in planner.py (at least 5 required); `git diff --exit-code --stat 99d3a94 -- tests/test_cost_per_unit.py` exits 0.

## Deviations from Plan

### Auto-fixed Issues

**1. [Plan scope note] `expected_plans.json` regenerated although no test failed**
- **Found during:** Task 3
- **Issue:** The plan says regenerate only fixtures that fail, but also lists this fixture in `files_modified`. No test reads it, so it cannot fail; it was stale against the new planner output.
- **Fix:** Regenerated from `scripts/_regen_phase4_expectations.py`; reverted the unrelated `parameters.json` drift the same script produces.
- **Files modified:** tests/fixtures/phase4/expected_plans.json
- **Commit:** f63e64c

**2. [Plan scope note] `tests/test_core_tracer.py` needed no edit** (it was in `files_modified`; it passes unchanged).

**Total deviations:** 0 auto-fixed, 2 scope notes. **Impact:** none on behavior. Test adjustment to be aware of: `test_entry_zone_math_long` now compares against `quantize_for_storage(expected)` (a deliberate consequence of D-12, not a weakened assertion).

## Known Stubs

None.

## Threat Flags

None. T-17-14 mitigated (explicit rounding mode before hashing, spelling-invariant text; store-boundary guard and PG round-trip test remain plan 10). T-17-15 mitigated (inventory above, literal-hash fixtures byte-identical). T-17-SC: no packages installed.

## Issues Encountered

None blocking. The `parameters.json` generator drift above is pre-existing and was left alone (candidate for a later cleanup of `_regen_phase4_expectations.py`).

## Self-Check: PASSED

- `src/domain/canonical.py`, `tests/test_domain_canonical_decimal.py` and this SUMMARY exist; commits 2d6eee0, b1616b2, f63e64c exist; measured commit count 3 from the recorded plan head 365bcbb.

## Next

Ready for plan 17-06 and the remaining Phase 17 plans. Plan 10 owns the store-boundary PrecisionError guard and the PostgreSQL round-trip test over real planner outputs; plan 15 records D051 from the inventory above.
