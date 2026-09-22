---
phase: 03-domain-registry-fixtures
plan: "03"
subsystem: domain
tags: [domain, registry, tdd, fail-closed, hash-stability, normalization]
requires:
  - phase: 03-01
    provides: tracer registry slice (load_parameter_set, verify_parameter_set, 4 typed exceptions)
provides:
  - Registry normalization with trailing-precision preservation
  - 7-bit ASCII parameter name enforcement
  - Volatile sidecar field split (author/timestamp never affect hash)
  - check_strategy_key_outside_registry ambient-config gate
  - tests/test_registry_gate.py with 4 negative gate tests
affects:
  - Phase 4 (Pure Core) consumes hardened registry identity
  - Phase 5 (Risk) consumes registry identity for risk parity
  - Phase 6 (Backtest) consumes registry identity for experiment linkage
  - Plan 03-05 (CI registry gate) uses these negative tests as gate evidence
tech-stack:
  added: []
  patterns:
    - raw-text extraction for trailing-precision preservation
    - 7-bit ASCII parameter name restriction
    - ambient-config strategy-key smuggling detection
key-files:
  created:
    - tests/test_registry_gate.py
  modified:
    - src/domain/registry.py
    - tests/test_registry.py
key-decisions:
  - "D-04/D-12: trailing precision preserved by reading raw TOML text and building Decimal from string form (1.50 stays Decimal('1.50'), not Decimal('1.5'))"
  - "D-06: parameter names restricted to 7-bit ASCII so code-point sorting matches the documented canonical profile"
  - "D-04: volatile sidecar fields (author, timestamp) never enter the hashed body; editing them does not change the hash"
  - "D-06: check_strategy_key_outside_registry raises StrategyKeyOutsideRegistry if any whitelisted strategy key appears in ambient configuration"
requirements-completed:
  - DOMN-02
duration: "~10 minutes"
completed: "2026-09-22"
status: complete
plan_head_before: c8d8144c719d96d7ba33aec7f4b3f9b9d47c47ed
commits: 4
actuals:
  tokens: 53100
  tasks: 2
  commits: 4
---

# Phase 3 Plan 3: Registry Hardening + Fail-Closed Negative Gates Summary

Hardened the tracer registry slice into the full fail-closed loader contract per D-04/D-05/D-06: numeric normalization with trailing-precision preservation, 7-bit ASCII parameter name enforcement, volatile sidecar field split, and the strategy-versus-runtime split with negative gate tests.

## One-liner

Registry hardening with trailing-precision preservation, ASCII name enforcement, sidecar split, and 4 negative gate tests proving unregistered/mutated/schema-mismatch/smuggled-key paths fail closed.

## Accomplishments

### Task 1: Registry normalization and hash stability (TDD)

**RED (commit `c36ea6f`):** Added 6 failing tests to `tests/test_registry.py`:
- Test 8: whole-number TOML values normalize to int
- Test 9: fractional TOML values become Decimal from string form
- Test 10: same TOML parsed twice yields identical hash
- Test 11: non-ASCII parameter name raises at load
- Test 12: volatile sidecar fields (author, timestamp) do not affect hash
- Test 13: Decimal values with different trailing precision yield different hashes

**GREEN (commit `ba6c218`):** Hardened `src/domain/registry.py`:
- `_extract_raw_param_strings`: reads raw TOML text to preserve trailing precision (e.g. `1.50` stays `Decimal("1.50")`, not `Decimal("1.5")`)
- `_normalize_params`: builds Decimal from raw string form when available
- `_check_ascii_keys`: raises `StrategyKeyOutsideRegistry` for non-ASCII parameter names
- Hash payload unchanged: `strategy_id + strategy_version + parameter_set_id + parameters` (volatile sidecar fields never enter the hashed body)

### Task 2: Fail-closed negative gates (TDD)

**RED (commit `0f4d58a`):** Created `tests/test_registry_gate.py` with 5 failing tests:
- Test 1: `load_parameter_set` on missing file raises `UnregisteredParameterSet`
- Test 2: `verify_parameter_set` on mutated copy raises `ParameterSetMutated`
- Test 3: `schema_version = 2` raises `RegistrySchemaMismatch`
- Test 4: `check_strategy_key_outside_registry` raises on whitelisted key in ambient config
- Test 4b: `check_strategy_key_outside_registry` passes on clean ambient config

**GREEN (commit `ccc5064`):** Added `check_strategy_key_outside_registry` to `src/domain/registry.py`:
- Scans ambient configuration dict for whitelisted strategy keys
- Raises `StrategyKeyOutsideRegistry` if any whitelisted key is found
- Runtime config (endpoints, tokens, log levels, poll intervals) is allowed

## Deviations from Plan

None - plan executed exactly as written.

## Files Created/Modified

### Created (1 file)
- `tests/test_registry_gate.py` — 5 negative gate tests

### Modified (2 files)
- `src/domain/registry.py` — added `_extract_raw_param_strings`, `_check_ascii_keys`, `check_strategy_key_outside_registry`; updated `_normalize_params` to use raw strings
- `tests/test_registry.py` — added 6 normalization/hash-stability tests

## Verification

- `uv run pytest tests/test_registry.py -q` → 13 passed
- `uv run pytest tests/test_registry_gate.py -q` → 5 passed
- `uv run pytest -q` → 152 passed (18 new + 134 existing)
- `uv run ruff check src/ tests/` → All checks passed
- `uv run mypy src/` → Success: no issues found in 28 source files

## Acceptance Criteria

### Task 1
- [x] Same TOML parsed twice yields identical `parameter_set_hash`
- [x] A non-ASCII parameter name raises at load with a typed exception
- [x] Decimal values with different trailing precision yield different hashes
- [x] The module reports all tests passed with zero failures

### Task 2
- [x] `load_parameter_set` on trend-pullback and a missing set name raises `UnregisteredParameterSet`
- [x] `verify_parameter_set` on a one-digit-mutated copy raises `ParameterSetMutated`
- [x] A `schema_version = 2` document raises `RegistrySchemaMismatch`
- [x] An ambient mapping containing a whitelisted strategy key raises `StrategyKeyOutsideRegistry`

## Must-Haves Verification

- [x] Unknown or mutated parameter sets fail closed with typed exceptions, never silent fallback
- [x] Strategy-semantic keys outside the registry fail closed instead of silently altering semantics
- [x] Hash identity is stable and Decimal-exact across orderings and reloads

## Next Steps

Phase 3 plan 04 (DOMN-02 storage half): seven-table ORM mirror + mappers + migration 0002 with parity gate.
