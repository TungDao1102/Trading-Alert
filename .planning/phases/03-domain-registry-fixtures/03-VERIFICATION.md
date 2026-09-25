---
phase: 03-domain-registry-fixtures
verified: 2026-09-23T00:00:00Z
status: human_needed
score: 10/10 must-haves verified
covered_files:
  - .planning/phases/03-domain-registry-fixtures/03-01-PLAN.md
  - .planning/phases/03-domain-registry-fixtures/03-02-PLAN.md
  - .planning/phases/03-domain-registry-fixtures/03-03-PLAN.md
  - .planning/phases/03-domain-registry-fixtures/03-04-PLAN.md
  - .planning/phases/03-domain-registry-fixtures/03-05-PLAN.md
  - .planning/phases/03-domain-registry-fixtures/03-01-SUMMARY.md
  - .planning/phases/03-domain-registry-fixtures/03-02-SUMMARY.md
  - .planning/phases/03-domain-registry-fixtures/03-03-SUMMARY.md
  - .planning/phases/03-domain-registry-fixtures/03-04-SUMMARY.md
  - .planning/phases/03-domain-registry-fixtures/03-05-SUMMARY.md
  - src/domain/__init__.py
  - src/domain/enums.py
  - src/domain/canonical.py
  - src/domain/ids.py
  - src/domain/signal.py
  - src/domain/registry.py
  - src/domain/trade_plan.py
  - src/domain/approval.py
  - src/domain/order.py
  - src/domain/fill.py
  - src/domain/position.py
  - src/domain/journal.py
  - src/db/models.py
  - src/db/mappers.py
  - src/db/alembic/versions/0002_domain_registry.py
  - params/trend-pullback/baseline-v1.toml
  - tests/conftest.py
  - tests/fixtures/phase3/candles.csv
  - tests/fixtures/phase3/parameters.json
  - tests/fixtures/phase3/expected_signals.json
  - tests/fixtures/phase3/expected_plans.json
  - tests/test_domain_enums.py
  - tests/test_domain_ids.py
  - tests/test_registry.py
  - tests/test_registry_gate.py
  - tests/test_fixture_harness.py
  - tests/test_domain_entities.py
  - tests/test_domain_mappers.py
  - tests/test_no_lookahead.py
  - tests/test_prefix_invariance.py
  - tests/test_candle_close_timing.py
  - tests/test_domain_boundary.py
  - tests/test_domain_no_float.py
  - .github/workflows/registry-gate.yml
behavior_unverified: 0
overrides_applied: 0
deferred:
  - truth: "Every backtest/paper/alert/order plan displays experiment linkage alongside its registry identity"
    addressed_in: "Phase 6"
    evidence: "Phase 6 goal 'Backtest Simulator + Experiment Registry'; SC2 'Every experiment reproduces from dataset + strategy + parameter set + cost + execution versions'. Plan 03-04 checkpoint deferred experiment_runs table to Phase 6 and the registry DB mirror to Phase 6 with files canonical."
human_verification:
  - test: "Apply migration 0002 on live Compose PG17: boot Compose PostgreSQL 17, run `alembic upgrade head`, confirm signals, trade_plans, approvals, orders, fills, positions, journal_events tables exist"
    expected: "Upgrade applies cleanly with no errors; all seven tables present with content-hash PKs"
    why_human: "Needs a running PG17 via Compose; offline parity gate (model <-> rendered head DDL diff) is green but is not a live apply"
---

# Phase 03: Domain + Registry + Fixtures Verification Report

**Phase Goal:** Every decision is traceable and reproducible — new behavior must be expressible as a versioned set before it exists.
**Verified:** 2026-09-23T00:00:00Z
**Status:** human_needed (all automated checks green; one env-gated live-PG item needs an operator)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Seven entities exist as frozen dataclasses with GLOSSARY-canonical lifecycle enums | ✓ VERIFIED | `src/domain/` holds signal, trade_plan, approval, order, fill, position, journal + enums (incl. ApprovalResult PENDING/APPROVED/SKIPPED/EXPIRED); `tests/test_domain_entities.py` (22 tests) + `tests/test_domain_enums.py` (12 tests) pass; single-statement barrel import works |
| 2 | Seven entities persist in separate tables keyed by deterministic content-hash PKs with no auto-increment | ✓ VERIFIED | `src/db/models.py` has SignalRow + 6 new rows, all String(128) PKs; migration 0002 has seven create_table blocks; grep for autoincrement/Sequence in 0002 returns nothing; parity script lists all 7 tables with hash PKs |
| 3 | Explicit status columns; no state inferred from nullable columns; Approval carries action + result + status, never inferred from timestamps | ✓ VERIFIED | ApprovalRow carries action/result/status; nullable only on never-happened transitions (invalidated/acted/canceled/closed/message); None round-trip tests (5) pass; Approval status reads correctly with acted_at_utc=None |
| 4 | A registered seed set loads by id; hash stable across key orderings, reloads, and TOML spelling; Decimal-exact incl. trailing precision | ✓ VERIFIED | `load_parameter_set("trend-pullback","baseline-v1")` returns ParameterSet with 64-hex hash; `tests/test_registry.py` (13 tests: normalization, ASCII keys, sidecar split, trailing-precision-distinct) passes; registry.py has `_extract_raw_param_strings`, `_normalize_params`, `_check_ascii_keys` |
| 5 | Unknown, mutated, schema-mismatched, or smuggled parameter sets fail closed with typed exceptions, never silent fallback | ✓ VERIFIED | Four exception types + `check_strategy_key_outside_registry` present; `tests/test_registry_gate.py` (5 negative tests) passes: UnregisteredParameterSet, ParameterSetMutated, RegistrySchemaMismatch, StrategyKeyOutsideRegistry |
| 6 | Every entity mapper round-trips exactly (`from_row(to_row(x)) == x`), with unknown statuses raising ValueError | ✓ VERIFIED | `src/db/mappers.py` has total pairs for all 7 entities, Enum via `.value`/`Enum(value)`; `tests/test_domain_mappers.py` (25 tests: 7 round-trips + 7 CapturingSession precision snapshots + 6 unknown-status rejections + 5 None round-trips) passes |
| 7 | Migration 0002 matches the ORM one-to-one and the offline parity gate is green | ✓ VERIFIED | `uv run python scripts/check_migration_parity.py` → OK, all 11 tables, no drift; reverse-order downgrade present; down_revision 0001_baseline |
| 8 | The golden triple loads and placeholder expectations match harness output | ✓ VERIFIED | `tests/fixtures/phase3/` triple on disk; conftest loaders present; `tests/test_fixture_harness.py` (9 tests incl. digest-pinned tripwire + registry identity match) passes |
| 9 | No-lookahead, prefix-invariance, candle-close-timing, and boundary suites pass as mechanism-only tests | ✓ VERIFIED | `tests/test_no_lookahead.py` (2), `tests/test_prefix_invariance.py` (2), `tests/test_candle_close_timing.py` (2), `tests/test_domain_boundary.py` (4, explicit invalid reasons via MIN_BARS_TBD test-local entry point) — all pass |
| 10 | Unregistered or mutated parameter sets are rejected by a CI gate; no binary float exists on the domain/mapper/registry path | ✓ VERIFIED | `.github/workflows/registry-gate.yml` triggers on pull_request + push to master, re-hashes params/**/*.toml, runs gate tests; `tests/test_domain_no_float.py` AST guard over 12 domain modules + mappers passes; grep for `float(` in src/domain returns nothing; full suite 189 passed; ruff clean; mypy strict clean (20 files) |

**Score:** 10/10 truths verified (0 present-but-behavior-unverified)

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | Experiment linkage on backtest/paper/alert/order-plan displays (registry identity half is landed; experiment_runs table + registry DB mirror deferred by design) | Phase 6 | Phase 6 "Backtest Simulator + Experiment Registry", SC "Every experiment reproduces from dataset + strategy + parameter set + cost + execution versions"; 03-04 checkpoint records both deferrals |

### Advisory (New Scope, Unevidenced)

None — initial verification; no new-scope findings raised.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/domain/*.py` (12 modules) | Pure frozen dataclasses, stdlib-only | ✓ VERIFIED | All present; no `src.db` imports; no float/TODO/FIXME/placeholder markers |
| `src/domain/registry.py` | Fail-closed loader + 4 exceptions + smuggling gate | ✓ VERIFIED | load/verify/check_strategy_key_outside_registry all present and tested |
| `params/trend-pullback/baseline-v1.toml` | Immutable seed set, schema_version 1 | ✓ VERIFIED | Present; loads with stable hash |
| `src/db/models.py` + `src/db/mappers.py` | 7 rows + 7 total mapper pairs | ✓ VERIFIED | Present; 25 mapper tests green |
| `src/db/alembic/versions/0002_domain_registry.py` | 7 create_table blocks, no auto-increment | ✓ VERIFIED | Present; parity green |
| `tests/fixtures/phase3/` (4 files) | Golden triple + pinned parameters | ✓ VERIFIED | Present; harness tripwire green |
| `tests/test_*.py` (12 modules) | Discipline + determinism + guard suites | ✓ VERIFIED | All pass (107 phase-scoped, 189 full) |
| `.github/workflows/registry-gate.yml` | Re-hash + negative-test CI job | ✓ VERIFIED | Present; triggers on PR + push to master |

Note: `src/domain/__init__.py` does not re-export `ParameterSetMutated` or `check_strategy_key_outside_registry` — cosmetic only; both are importable from `src.domain.registry` and exercised by tests. Not a gap.

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| registry ParameterSetHash | Signal.parameter_set_hash identity field | loader output feeds Signal construction in tests | WIRED | Round-trip + harness identity tests pass |
| Signal domain object | SignalRow | signal_to_row / signal_from_row on shared Base | WIRED | Round-trip equality green |
| Fixture parameters.json | registry loader | pinned identity match test | WIRED | Harness registry round-trip test passes |
| TradePlan.trade_plan_id | parent SignalId | derive_child_id(parent, trade_plan:v1) | WIRED | Entity construction tests pass |
| Mapper Enum translation | domain Enums <-> row strings | `.value` storage / `Enum(value)` restore, only bridge | WIRED | Unknown-status rejection tests (6) pass |
| verify_parameter_set | CI registry gate | workflow runs gate + registry tests per PR | WIRED | Workflow file verified; local run green |

### Data-Flow Trace (Level 4)

N/A — Phase 3 renders no dynamic user-visible data; all outputs are test-pinned fixtures and ORM round-trips. No hollow props, no static fallbacks masquerading as queries.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 107 phase-scoped tests pass | `uv run pytest <12 phase modules> -q` | 107 passed | ✓ PASS |
| Full suite green | `uv run pytest -q` | 189 passed | ✓ PASS |
| Offline migration parity | `uv run python scripts/check_migration_parity.py` | OK, 11 tables, no drift | ✓ PASS |
| Lint + types | `ruff check` + `mypy src/domain src/db` | clean / no issues in 20 files | ✓ PASS |
| Live `alembic upgrade head` on PG17 | — (needs Compose PG) | not run | ? SKIP → human verification |

### Probe Execution

No phase-declared or conventional probes (`scripts/*/tests/probe-*.sh` unrelated to this phase). Skipped.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| DOMN-01 | 03-01, 03-02, 03-04 | Seven entities, canonical enums, no nullable-state inference | ✓ SATISFIED | Truths 1, 2, 3, 6, 7; 7 tables + 7 mappers + enums green |
| DOMN-02 | 03-01, 03-03, 03-05 | Traceable to immutable versioned set (id + hash); experiment linkage | ✓ SATISFIED (mechanism; experiment linkage deferred to Phase 6) | Truths 4, 5, 10; loader + negatives + CI gate green |
| DOMN-03 | 03-01, 03-05 | Golden fixtures + 4 determinism suites; unregistered changes rejected | ✓ SATISFIED | Truths 8, 9, 10; fixtures + suites + gate green |

No orphaned requirements: REQUIREMENTS.md maps exactly DOMN-01/02/03 to Phase 3, and every ID is claimed across the five plans.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | — | — | — | Grep for TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER/placeholder/not-implemented/`return null`/`float(`/hardcoded empty data in `src/domain/` returns zero matches |

### Human Verification Required

### 1. Live migration apply on Compose PG17

**Test:** Boot Compose PostgreSQL 17, run `alembic upgrade head`, confirm the seven domain tables exist with content-hash PKs.
**Expected:** Upgrade applies cleanly; signals, trade_plans, approvals, orders, fills, positions, journal_events present.
**Why human:** Needs a running PG17 via Compose — offline parity (rendered head DDL vs full Base metadata diff) is green but is not a live apply. Pre-declared Manual-Only operator step per plan 03-04.

### Gaps Summary

No gaps. All 10 must-have truths verified against the codebase with passing tests, a green parity gate, and clean lint/types. One deferred-by-design item (experiment linkage → Phase 6) and one env-gated operator check (live alembic apply) are recorded above; neither blocks the phase goal, but the live-PG check requires a human with Compose, hence `human_needed`.

---
_Verified: 2026-09-23T00:00:00Z_
_Verifier: the agent (gsd-verifier)_
