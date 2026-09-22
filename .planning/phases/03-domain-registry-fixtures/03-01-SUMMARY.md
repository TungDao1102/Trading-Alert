---
phase: 03-domain-registry-fixtures
plan: "01"
subsystem: domain
tags: [domain, registry, fixtures, tdd, tracer]
requires: []
provides:
  - src/domain package (pure, dependency-free)
  - params/ file registry (immutable TOML seeds)
  - tests/fixtures/phase3 golden triple
  - SignalRow ORM mirror + signal mappers
affects:
  - Phase 4 (Pure Core) consumes domain types
  - Phase 5 (Risk) consumes registry identity
  - Phase 6 (Backtest) consumes fixtures + suites
tech-stack:
  added: []
  patterns:
    - frozen dataclass + Decimal + UTC + Enum (D-01/D-12)
    - canonical-hash identity (D-04)
    - fail-closed registry loader (D-04/D-05/D-06)
    - ORM mirror + thin total mappers (D-02)
    - golden triple + placeholder-mechanism harness (D-07/D-09)
key-files:
  created:
    - src/domain/__init__.py
    - src/domain/enums.py
    - src/domain/canonical.py
    - src/domain/ids.py
    - src/domain/signal.py
    - src/domain/registry.py
    - src/db/mappers.py
    - params/trend-pullback/baseline-v1.toml
    - tests/fixtures/phase3/candles.csv
    - tests/fixtures/phase3/parameters.json
    - tests/fixtures/phase3/expected_signals.json
    - tests/fixtures/phase3/expected_plans.json
    - tests/test_domain_enums.py
    - tests/test_domain_ids.py
    - tests/test_registry.py
    - tests/test_fixture_harness.py
  modified:
    - src/db/models.py
    - tests/conftest.py
    - pyproject.toml
key-decisions:
  - "D-10: enum values copy GLOSSARY §§2-9 verbatim; str+Enum mixin (not StrEnum) per research canonical pattern"
  - "D-04: parameterSetHash = SHA256 over canonical JSON of normalized TOML body (sorted keys, compact separators, ensure_ascii, allow_nan=False)"
  - "D-03: SignalId input list = strategyVersion + parameterSetId + symbol + source_timeframe + source_candle_close_utc + setup_fingerprint"
  - "D-06: closed whitelist of strategy-semantic keys (STRATEGY_KEYS); unknown keys raise StrategyKeyOutsideRegistry"
  - "D-12: float rejected loudly in canonical hash; TOML floats coerced to Decimal via str() before hashing"
  - "D-11: explicit status columns; nullable timestamps only for 'transition never happened'"
  - "D-09: Phase 3 expectations are minimal placeholders (empty signals/plans); Phase 4 populates real family expectations"
requirements-completed:
  - DOMN-01
  - DOMN-02
  - DOMN-03
duration: "~15 minutes"
completed: "2026-09-22"
status: complete
plan_head_before: fac43a1f2644ec8473373d0a03f3792c0fda9bfa
commits: 2
actuals:
  tokens: 40725
  tasks: 2
  commits: 2
---

# Phase 3 Plan 1: Domain + Registry + Fixtures (Tracer Slice) Summary

Tracer slice proving the reproducibility spine end-to-end on one path: TOML seed file loads through the fail-closed registry loader per D-04, its hash feeds a content-hash SignalId per D-03, a Signal dataclass round-trips through the ORM mapper per D-02, and the golden fixture triple loads with placeholder expectations per D-07/D-09.

## One-liner

Pure-Python domain package + TOML parameter registry + SignalRow ORM mirror + golden fixture triple, all green in 36 tests.

## Accomplishments

### RED Phase (commit `9f6465c`)

Wrote 4 failing test modules (36 tests total) covering:
- **test_domain_enums** (12 tests): GLOSSARY-canonical enum values for SignalStatus, TradePlanStatus, ApprovalAction, OrderStatus, TradeStatus, PositionStatus, SystemMode, RejectionReason; unknown-status raises ValueError; .value storage contract; str+Enum mixin comparison.
- **test_domain_ids** (10 tests): make_signal_id returns 64-hex string; deterministic across key orderings; rejects naive datetime, float, set; different inputs produce different IDs; derive_child_id deterministic and discriminator-sensitive; Decimal precision preserved.
- **test_registry** (7 tests): load_parameter_set returns ParameterSet with 64-hex hash; hash stable across runs; unregistered set raises UnregisteredParameterSet; schema mismatch raises RegistrySchemaMismatch; unknown strategy key raises StrategyKeyOutsideRegistry; verify_parameter_set raises on mutation; verify passes when hash matches.
- **test_fixture_harness** (7 tests): phase3_candles/parameters/expected_signals/expected_plans fixtures load; fixture files exist on disk; parameters.json hash matches loaded registry; placeholder expectations match harness output byte-exactly.

All 36 tests failed with `ModuleNotFoundError: No module named 'src.domain'` — the expected RED state.

### GREEN Phase (commit `f8ff6e5`)

Implemented the slice per D-01, D-02, D-03, D-04, D-06, D-10, D-11, D-12:
- **src/domain/enums.py**: 8 GLOSSARY-canonical enums with str+Enum mixin.
- **src/domain/canonical.py**: scalar normalizer (Decimal→str full precision, datetime→isoformat with naive rejected, Enum→.value, set/float rejected) + canonical_bytes (sorted keys, compact separators, ensure_ascii, allow_nan=False) + sha256_hex.
- **src/domain/ids.py**: make_signal_id (D-03 binding superset) + derive_child_id (parent hash + discriminator).
- **src/domain/signal.py**: frozen Signal dataclass with Decimal money fields, UTC-aware datetime, SignalStatus enum, nullable invalidated_at_utc.
- **src/domain/registry.py**: TOML loader with REGISTRY_ROOT, SCHEMA_VERSION=1, STRATEGY_KEYS whitelist, 4 exception types (UnregisteredParameterSet, ParameterSetMutated, RegistrySchemaMismatch, StrategyKeyOutsideRegistry), ParameterSet dataclass, load_parameter_set + verify_parameter_set. TOML floats coerced to Decimal via str() before hashing.
- **src/domain/__init__.py**: barrel re-exports.
- **src/db/models.py**: SignalRow on existing Base (String(128) PK on signal_id, explicit status String(16), TIMESTAMPTZ timestamps, nullable invalidated_at_utc).
- **src/db/mappers.py**: signal_to_row + signal_from_row (total, round-trip tested, Enum(value) coercion at boundary).
- **params/trend-pullback/baseline-v1.toml**: seed parameter set (schema_version=1, strategy_id=trend-pullback, strategy_version=v1.0.0, 9 strategy-semantic keys).
- **tests/fixtures/phase3/**: golden triple (candles.csv with 5 boundary-covering bars, parameters.json pinning the registry hash, expected_signals.json + expected_plans.json with empty placeholders).
- **tests/conftest.py**: phase3_candles, phase3_parameters, phase3_expected_signals, phase3_expected_plans fixtures.
- **pyproject.toml**: ignore UP042 (str+Enum mixin is canonical per research).

All 36 tests pass. Full suite: 118 tests pass. Ruff clean. Mypy strict clean.

### Tracer Feedback Gate

Re-ran the verify command per auto-mode protocol: `uv run pytest tests/test_domain_enums.py tests/test_domain_ids.py tests/test_registry.py tests/test_fixture_harness.py -q` → 36 passed. Tracer verified end-to-end.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed TOML float handling in registry loader**
- **Found during:** Task 2 GREEN phase
- **Issue:** TOML parses `0.5` as a Python float; the canonicalizer rejects float loudly (D-12). The initial `_normalize_params` left non-integral floats as-is, causing `TypeError: float in canonical hash input` on every load.
- **Fix:** Coerce non-integral floats to `Decimal(str(value))` in `_normalize_params` before hashing. Whole-number floats coerce to int (preserving integer type).
- **Files modified:** src/domain/registry.py
- **Commit:** f8ff6e5

**2. [Rule 2 - Missing critical] Added UP042 to ruff ignore list**
- **Found during:** Task 2 GREEN phase (ruff check)
- **Issue:** Ruff UP042 suggests `StrEnum` instead of `str, Enum` mixin. The research and patterns docs explicitly use the `str, Enum` mixin pattern; switching to `StrEnum` would change `str(member)` semantics.
- **Fix:** Added `UP042` to `[tool.ruff.lint] ignore` in pyproject.toml with a comment citing the research canonical pattern.
- **Files modified:** pyproject.toml
- **Commit:** f8ff6e5

**3. [Rule 2 - Missing critical] Added type arguments to dict types for mypy strict**
- **Found during:** Task 2 GREEN phase (mypy check)
- **Issue:** Mypy strict mode requires type arguments on generic types. The initial code used bare `dict` annotations.
- **Fix:** Added `dict[str, Any]` type arguments to `canonical_bytes`, `sha256_hex`, `_normalize_params`, and `ParameterSet.params`. Added `Any` import to registry.py.
- **Files modified:** src/domain/canonical.py, src/domain/registry.py
- **Commit:** f8ff6e5

**Total deviations:** 3 auto-fixed (1 bug, 2 missing critical). **Impact:** None — all fixes are correctness/quality improvements that align with the plan's intent.

## Files Created/Modified

### Created (16 files)
- `src/domain/__init__.py` — barrel re-exports
- `src/domain/enums.py` — 8 GLOSSARY-canonical enums
- `src/domain/canonical.py` — scalar normalizer + canonical JSON + SHA256
- `src/domain/ids.py` — make_signal_id + derive_child_id
- `src/domain/signal.py` — frozen Signal dataclass
- `src/domain/registry.py` — TOML loader + fail-closed hash verification
- `src/db/mappers.py` — signal_to_row + signal_from_row
- `params/trend-pullback/baseline-v1.toml` — seed parameter set
- `tests/fixtures/phase3/candles.csv` — 5 boundary-covering bars
- `tests/fixtures/phase3/parameters.json` — pinned registry set
- `tests/fixtures/phase3/expected_signals.json` — empty placeholder
- `tests/fixtures/phase3/expected_plans.json` — empty placeholder
- `tests/test_domain_enums.py` — 12 enum tests
- `tests/test_domain_ids.py` — 10 ID tests
- `tests/test_registry.py` — 7 registry tests
- `tests/test_fixture_harness.py` — 7 fixture harness tests

### Modified (3 files)
- `src/db/models.py` — added SignalRow on existing Base
- `tests/conftest.py` — added phase3 fixtures
- `pyproject.toml` — added UP042 to ruff ignore

## Verification

- `uv run pytest tests/test_domain_enums.py tests/test_domain_ids.py tests/test_registry.py tests/test_fixture_harness.py -q` → 36 passed
- `uv run pytest` → 118 passed (36 new + 82 existing)
- `uv run ruff check src/ tests/` → All checks passed
- `uv run mypy src/` → Success: no issues found in 22 source files
- `uv run python --version` → Python 3.13.15

## Acceptance Criteria

- [x] src/domain imports nothing beyond stdlib, verified by inspection of the import blocks.
- [x] load_parameter_set on trend-pullback baseline-v1 returns a ParameterSet with a 64-character hex hash.
- [x] make_signal_id is deterministic across key orderings and rejects naive datetimes.
- [x] signal_from_row of signal_to_row output equals the original Signal.
- [x] The four listed test modules all report passed with zero failures.

## Must-Haves Verification

- [x] A registered seed parameter set loads by id and its hash is stable across key orderings
- [x] A Signal built from the registry identity tuple maps to a row and back with equality
- [x] The golden triple loads and the placeholder expectations match harness output byte-exactly

## Next Steps

Phase 3 plan 02 (DOMN-01/DOMN-02 expansion): add the remaining 6 domain entities (TradePlan, Approval, Order, Fill, Position, JournalEvent), full migration 0002, and registry hardening (DB mirror, CI gate).
