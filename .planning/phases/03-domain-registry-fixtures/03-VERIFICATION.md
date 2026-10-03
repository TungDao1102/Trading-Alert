---
phase: 03-domain-registry-fixtures
verified: 2026-10-03T00:00:00Z
status: passed
score: 10/10 must-haves verified
covered_files:
  - .github/workflows/registry-gate.yml
  - .planning/phases/03-domain-registry-fixtures/03-01-PLAN.md
  - .planning/phases/03-domain-registry-fixtures/03-01-SUMMARY.md
  - .planning/phases/03-domain-registry-fixtures/03-02-PLAN.md
  - .planning/phases/03-domain-registry-fixtures/03-02-SUMMARY.md
  - .planning/phases/03-domain-registry-fixtures/03-03-PLAN.md
  - .planning/phases/03-domain-registry-fixtures/03-03-SUMMARY.md
  - .planning/phases/03-domain-registry-fixtures/03-04-PLAN.md
  - .planning/phases/03-domain-registry-fixtures/03-04-SUMMARY.md
  - .planning/phases/03-domain-registry-fixtures/03-05-PLAN.md
  - .planning/phases/03-domain-registry-fixtures/03-05-SUMMARY.md
  - params/trend-pullback/baseline-v1.toml
  - src/db/alembic/versions/0002_domain_registry.py
  - src/db/mappers.py
  - src/db/models.py
  - src/domain/__init__.py
  - src/domain/approval.py
  - src/domain/canonical.py
  - src/domain/enums.py
  - src/domain/fill.py
  - src/domain/ids.py
  - src/domain/journal.py
  - src/domain/order.py
  - src/domain/position.py
  - src/domain/registry.py
  - src/domain/signal.py
  - src/domain/trade_plan.py
  - src/domain/transitions.py
  - tests/conftest.py
  - tests/fixtures/phase3/candles.csv
  - tests/fixtures/phase3/expected_plans.json
  - tests/fixtures/phase3/expected_signals.json
  - tests/fixtures/phase3/parameters.json
  - tests/test_candle_close_timing.py
  - tests/test_domain_boundary.py
  - tests/test_domain_entities.py
  - tests/test_domain_enums.py
  - tests/test_domain_ids.py
  - tests/test_domain_mappers.py
  - tests/test_domain_no_float.py
  - tests/test_fixture_harness.py
  - tests/test_no_lookahead.py
  - tests/test_prefix_invariance.py
  - tests/test_registry.py
  - tests/test_registry_gate.py
covered_digest: "v2:sha256:4f1168394f0b8e70142f8a47a5ea335d6ca397358f14abb8a0fc97858006b4a7"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 10/10
  gaps_closed: []
  gaps_remaining: []
  regressions: []
deferred:
  - truth: "Every backtest/paper/alert/order plan displays experiment linkage alongside its registry identity"
    addressed_in: "Phase 6"
    evidence: "Phase 6 goal 'Backtest Simulator + Experiment Registry' is complete (2026-09-26); SC2 'Every experiment reproduces from dataset + strategy + parameter set + cost + execution versions'. Plan 03-04 checkpoint deferred experiment_runs table and the registry DB mirror to Phase 6."
human_verification: []
---

# Phase 03: Domain + Registry + Fixtures Verification Report

**Phase Goal:** Every decision is traceable and reproducible — new behavior must be expressible as a versioned set before it exists.
**Verified:** 2026-10-03T00:00:00Z
**Status:** passed (the live-PG item was closed on 2026-10-04: DB at head 0004, seven tables with content-hash PKs, 431 PG tests green)
**Re-verification:** Yes — prior report (2026-09-23) was stale. Phases 4 through 17 legitimately extended the registry, entities and migration chain (migrations 0003/0004, `src/domain/transitions.py`, extra rows such as ExecutionIntentRow, ShortIdMappingRow, PlanConstraintSnapshotRow, SystemStateEventRow, 40+ param sets). Judged against the Phase 3 goal still holding, not against the original file snapshot.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Seven entities exist as frozen dataclasses with GLOSSARY-canonical lifecycle enums | ✓ VERIFIED | `src/domain/{signal,trade_plan,approval,order,fill,position,journal,enums}.py` present; `tests/test_domain_entities.py` and `tests/test_domain_enums.py` pass |
| 2 | Seven entities persist in separate tables keyed by deterministic content-hash PKs, no auto-increment | ✓ VERIFIED | `src/db/models.py` has SignalRow, TradePlanRow, ApprovalRow, OrderRow, FillRow, PositionRow, JournalEventRow (plus later additive rows); migration 0002 has seven `op.create_table` blocks, grep for autoincrement/Sequence returns nothing |
| 3 | Explicit status columns; no state inferred from nullable columns; Approval carries action + result + status | ✓ VERIFIED | ApprovalRow carries explicit status columns; None round-trip tests in `tests/test_domain_mappers.py` pass; later phases added transition tables on top of the same explicit-status model |
| 4 | A registered seed set loads by id; hash stable across key orderings/reloads/TOML spelling; Decimal-exact | ✓ VERIFIED | `tests/test_registry.py` passes; `src/domain/registry.py` present; `params/trend-pullback/baseline-v1.toml` loads and matches pin in `tests/fixtures/phase3/parameters.json` (hash `e1579900…afae5`) |
| 5 | Unknown, mutated, schema-mismatched, or smuggled parameter sets fail closed with typed exceptions | ✓ VERIFIED | `tests/test_registry_gate.py` passes (UnregisteredParameterSet, ParameterSetMutated, RegistrySchemaMismatch, StrategyKeyOutsideRegistry) |
| 6 | Every entity mapper round-trips exactly, unknown statuses raise ValueError | ✓ VERIFIED | `src/db/mappers.py` present; `tests/test_domain_mappers.py` passes (round-trips, precision snapshots, unknown-status rejection, None round-trips) |
| 7 | Migration 0002 matches the ORM one-to-one; parity gate green | ✓ VERIFIED (offline) | Original `scripts/check_migration_parity.py` was intentionally removed in later phases; `tests/test_persistence_migration_pg.py` now enforces a `compare_metadata` parity check (and asserts the script is gone) but SKIPS without `TEST_DATABASE_URL`. Offline coverage: 0002 has 7 create_table blocks, down_revision chain 0001 to 0002 to 0003 to 0004 intact (`tests/test_approval_message.py` asserts it). Live proof routed to human verification |
| 8 | The golden triple loads and placeholder expectations match harness output | ✓ VERIFIED | `tests/fixtures/phase3/` has candles.csv, parameters.json, expected_signals.json, expected_plans.json; `tests/test_fixture_harness.py` passes |
| 9 | No-lookahead, prefix-invariance, candle-close-timing, boundary suites pass | ✓ VERIFIED | `tests/test_no_lookahead.py`, `test_prefix_invariance.py`, `test_candle_close_timing.py`, `test_domain_boundary.py` all pass |
| 10 | Unregistered/mutated parameter sets rejected by CI gate; no binary float on domain path | ✓ VERIFIED | `.github/workflows/registry-gate.yml` triggers on pull_request + push to master, re-hashes `params/**/*.toml` against pinned hashes (now the phase4 multi-set pin list; phase3 `parameters.json` is a legacy single-pin harness). `tests/test_domain_no_float.py` passes; grep `float(` in `src/domain` empty |

**Score:** 10/10 truths verified (0 present-but-behavior-unverified)

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | Experiment linkage on backtest/paper/alert/order-plan displays (registry identity half landed in Phase 3) | Phase 6 (completed 2026-09-26) | Phase 6 "Backtest Simulator + Experiment Registry"; 03-04 checkpoint records the deferral |

### Advisory (New Scope, Unevidenced)

None.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/domain/*.py` (13 modules incl. later `transitions.py`) | Pure frozen dataclasses, stdlib-only | ✓ VERIFIED | Present; no TBD/FIXME/XXX/TODO/HACK markers; no `float(` |
| `src/domain/registry.py` | Fail-closed loader + exceptions + smuggling gate | ✓ VERIFIED | Present, tested |
| `params/trend-pullback/baseline-v1.toml` | Immutable seed set | ✓ VERIFIED | Present, pinned hash matches |
| `src/db/models.py` + `src/db/mappers.py` | 7 rows + total mapper pairs | ✓ VERIFIED | Present, tested |
| `src/db/alembic/versions/0002_domain_registry.py` | 7 create_table blocks, no auto-increment | ✓ VERIFIED | Present |
| `tests/fixtures/phase3/` (4 files) | Golden triple + pinned parameters | ✓ VERIFIED | Present, harness green |
| `tests/test_*.py` (12 phase modules + canonical decimal) | Discipline, determinism, guard suites | ✓ VERIFIED | 288 passed (13 modules) |
| `.github/workflows/registry-gate.yml` | Re-hash + negative-test CI job | ✓ VERIFIED | Present |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| registry ParameterSetHash | Signal.parameter_set_hash | loader output feeds Signal in tests | WIRED | Harness identity tests pass |
| Signal | SignalRow | signal_to_row / signal_from_row | WIRED | Round-trip green |
| Fixture parameters.json | registry loader | pinned identity match | WIRED | Harness test passes |
| TradePlan.trade_plan_id | parent SignalId | derive_child_id | WIRED | Entity tests pass |
| Mapper Enum translation | domain Enums <-> row strings | `.value` / `Enum(value)` | WIRED | Unknown-status tests pass |
| verify_parameter_set | CI registry gate | workflow re-hash + gate tests | WIRED | Workflow present and tests pass locally |

### Data-Flow Trace (Level 4)

N/A — no dynamic user-visible rendering in this phase.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Phase-scoped suites | `.venv/Scripts/python.exe -m pytest tests/test_domain_{enums,ids,entities,mappers,boundary,no_float,canonical_decimal}.py tests/test_registry.py tests/test_registry_gate.py tests/test_fixture_harness.py tests/test_no_lookahead.py tests/test_prefix_invariance.py tests/test_candle_close_timing.py -q` | 288 passed, exit 0 | ✓ PASS |
| Lint | `.venv/Scripts/ruff.exe check src tests` | All checks passed | ✓ PASS |
| Types | `.venv/Scripts/mypy.exe src/domain src/db` | no issues in 23 source files | ✓ PASS |
| PG-gated migration/mapper suites | `pytest tests/test_persistence_migration_pg.py tests/test_domain_mappers_pg.py -rs` | all skipped (TEST_DATABASE_URL not set) | ? SKIP → human verification |

Full workspace suite not re-run for this verification (scoped to Phase 3 modules).

### Probe Execution

No phase-declared or conventional probes. Skipped.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| DOMN-01 | 03-01, 03-02, 03-04 | Seven entities, canonical enums, no nullable-state inference | ✓ SATISFIED | Truths 1, 2, 3, 6, 7 |
| DOMN-02 | 03-01, 03-03, 03-05 | Traceable to immutable versioned set; experiment linkage | ✓ SATISFIED (mechanism; experiment linkage delivered by Phase 6) | Truths 4, 5, 10 |
| DOMN-03 | 03-01, 03-05 | Golden fixtures + 4 determinism suites; unregistered changes rejected | ✓ SATISFIED | Truths 8, 9, 10 |

No orphaned requirements: DOMN-01/02/03 are the only Phase 3 IDs. (DOMN-04 transition tables belong to Phase 17.)

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | — | grep for TBD/FIXME/XXX/TODO/HACK in `src/domain` and `src/db/mappers.py` returned zero matches | — | — |

### Human Verification Required

### 1. Live migration apply on Compose PG17 (03-UAT.md test 1, pending)

**Test:** Boot Compose PostgreSQL 17 with `TEST_DATABASE_URL` set, run `alembic upgrade head`, confirm the seven domain tables exist with content-hash PKs; optionally run `tests/test_persistence_migration_pg.py` and `tests/test_domain_mappers_pg.py`.
**Expected:** Upgrade applies cleanly; signals, trade_plans, approvals, orders, fills, positions, journal_events present; PG tests no longer skip and pass.
**Why human:** Requires a running PG17; the offline gate cannot substitute for a live apply.

### Gaps Summary

No gaps. All 10 truths hold against the current repo, which has since extended the Phase 3 registry and entities without regressing the goal. The only open item is the env-gated live-PG apply (03-UAT.md test 1, pending), hence `human_needed`.

---
_Verified: 2026-10-03T00:00:00Z_
_Verifier: the agent (gsd-verifier)_
