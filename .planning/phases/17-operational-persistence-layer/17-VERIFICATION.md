---
phase: 17-operational-persistence-layer
verified: 2026-10-07T04:50:48Z
status: passed
score: 5/5 must-haves verified
covered_files:
  - .github/workflows/ci.yml
  - .planning/phases/17-operational-persistence-layer/17-01-PLAN.md
  - .planning/phases/17-operational-persistence-layer/17-01-SUMMARY.md
  - .planning/phases/17-operational-persistence-layer/17-02-PLAN.md
  - .planning/phases/17-operational-persistence-layer/17-02-SUMMARY.md
  - .planning/phases/17-operational-persistence-layer/17-03-PLAN.md
  - .planning/phases/17-operational-persistence-layer/17-03-SUMMARY.md
  - .planning/phases/17-operational-persistence-layer/17-04-PLAN.md
  - .planning/phases/17-operational-persistence-layer/17-04-SUMMARY.md
  - .planning/phases/17-operational-persistence-layer/17-05-PLAN.md
  - .planning/phases/17-operational-persistence-layer/17-05-SUMMARY.md
  - .planning/phases/17-operational-persistence-layer/17-06-PLAN.md
  - .planning/phases/17-operational-persistence-layer/17-06-SUMMARY.md
  - .planning/phases/17-operational-persistence-layer/17-07-PLAN.md
  - .planning/phases/17-operational-persistence-layer/17-07-SUMMARY.md
  - .planning/phases/17-operational-persistence-layer/17-08-PLAN.md
  - .planning/phases/17-operational-persistence-layer/17-08-SUMMARY.md
  - .planning/phases/17-operational-persistence-layer/17-09-PLAN.md
  - .planning/phases/17-operational-persistence-layer/17-09-SUMMARY.md
  - .planning/phases/17-operational-persistence-layer/17-10-PLAN.md
  - .planning/phases/17-operational-persistence-layer/17-10-SUMMARY.md
  - .planning/phases/17-operational-persistence-layer/17-11-PLAN.md
  - .planning/phases/17-operational-persistence-layer/17-11-SUMMARY.md
  - .planning/phases/17-operational-persistence-layer/17-12-PLAN.md
  - .planning/phases/17-operational-persistence-layer/17-12-SUMMARY.md
  - .planning/phases/17-operational-persistence-layer/17-13-PLAN.md
  - .planning/phases/17-operational-persistence-layer/17-13-SUMMARY.md
  - .planning/phases/17-operational-persistence-layer/17-14-PLAN.md
  - .planning/phases/17-operational-persistence-layer/17-14-SUMMARY.md
  - .planning/phases/17-operational-persistence-layer/17-15-PLAN.md
  - .planning/phases/17-operational-persistence-layer/17-15-SUMMARY.md
  - src/db/alembic/versions/0004_persistence_integrity.py
  - src/domain/transitions.py
  - src/execution/intent_store.py
  - src/execution/manager.py
  - src/persistence/approvals.py
  - src/persistence/engine.py
  - src/persistence/execution_state.py
  - src/persistence/uow.py
  - src/reconcile/safe_mode.py
  - tests/pg_support.py
  - tests/test_execution_exactly_once_pg.py
  - tests/test_execution_write_ahead_pg.py
  - tests/test_persistence_migration_pg.py
covered_digest: "v2:sha256:b44f4e503788086be90fb1bbe422efd7ab8814bc5de93df50525b4169fd48772"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  re_verified: 2026-10-07T04:50:48Z
  previous_status: human_needed
  previous_score: 5/5 must-haves verified
  gaps_closed: []
  gaps_remaining: []
  regressions: []
  reason: "The first report (2026-10-02) listed only 9 files in covered_files, so the shared status query reported stale. The four human items have since been resolved by the owner or by evidence (see Human Verification). No Phase 17 source or test file changed after that report; the only differences in the covered set are a docstring in src/domain/transitions.py (DOMN-04 confirmation text) and persist-credentials / shellcheck edits in .github/workflows/ci.yml."
deferred:
  - truth: "Binance duplicate-id error code -4116 for algo orders (clientAlgoId), and that a client id is accepted again once its first order is closed"
    addressed_in: "Phase 18 demo/testnet probe (docs/SOURCES.md 'Live re-read of the Phase 17 facts': both need the demo environment before Phase 19); Phase 25 demo campaign"
    evidence: "docs/SOURCES.md line 125: 'Still NOT verified live: the duplicate-id error code -4116 for algo orders, and the inference that a replayed id is accepted once the first order is closed. Both need the demo environment (Phase 18 probe) before Phase 19.' ROADMAP Phase 18 success criterion 2 requires a demo or testnet probe but names only the GET order / GET algoOrder not-found codes, not these two facts; the owner is therefore recorded in SOURCES.md and not yet in the ROADMAP text (see Notes)."
---

# Phase 17: Operational Persistence Layer Verification Report

**Phase Goal:** Operational state lives durably in PostgreSQL with integrity constraints. A replayed callback or a restart can never create a second entry.
**Verified:** 2026-10-07T04:50:48Z (HEAD 0e4f23a; working tree changes are only .planning/config.json, .planning/state.json and .gsd/, none touched)
**Status:** passed (re-verified; was human_needed)
**Re-verification:** Yes. The five success criteria were re-checked against current code and tests, not copied from the 2026-10-02 report.

## Goal Achievement

The goal is achieved in the codebase. `execute_approved_plan` first checks identity, then reads the stored ENTRY intent by approval id and returns the stored outcome with zero adapter calls. The intent row is written in the same transaction that marks the approval consumed, before `place_entry`. The database primary key `(approval_id, role)` and the partial-unique client-id indexes are a second line of defence that does not depend on Python. The tests prove this against a fake that really frees a client id after FILLED or CANCELED, across a restart (disposed engines, new store and manager) and across two concurrent threads, each with a negative control.

What changed since the first report (git diff e740a77..HEAD over every Phase 17 path): `src/persistence`, `src/execution`, `src/reconcile`, `src/db` and all Phase 17 tests have zero changes. Two differences: `src/domain/transitions.py` (docstring only: the DOMN-04 tables are now recorded as confirmed by the user, with the UNKNOWN-exit evidence rule and the deliberate `APPROVED -> SUPERSEDED` illegality) and `.github/workflows/ci.yml` (`persist-credentials: false`, shellcheck `-P SCRIPTDIR`). Both are in `covered_files`.

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC1 | PG implementations of the journal, approval and execution-state stores exist; the row mappers have production callers (F-202) | VERIFIED | Stores under `src/persistence` (`journal.py`, `approvals.py`, `entities.py`, `execution_state.py`, `snapshots.py`, `system_state.py`) call the `src/db/mappers.py` pairs; `src/execution/intent_store.py` is the stdlib-only `ExecutionIntentStore` Protocol the manager requires. Ran `test_persistence_journal_pg` (21), `test_persistence_approvals_pg` (27), `test_domain_mappers_pg` (5), `test_persistence_roundtrip_pg` (7), `test_plan_hash_roundtrip_pg` (22): all pass, no skips. No live process composes the stores yet; that is Phase 24 by CONTEXT scope. |
| SC2 | Unique token hash, one decided approval per plan, unique client_order_id; FKs and CHECKs; widths that fit; UTC session pin; ORM indexes in parity | VERIFIED | Migration `0004_persistence_integrity.py` (unchanged). Ran against a fresh PostgreSQL 17.11: `test_persistence_constraints_pg` (45), `test_persistence_migration_pg` (32, upgrade/downgrade/upgrade, 0003 to 0004 with data, `compare_metadata` parity), `test_persistence_enum_columns_pg` (25), `test_persistence_triggers_pg` (60), `test_persistence_transitions_pg` (65), `test_persistence_engine_pg` (5), `test_persistence_engine_timeouts` (5), `test_persistence_uow_pg` (5): all pass. |
| SC3 | Approval consumption is durable; execution intent is written ahead before `place_entry` and between entry and SL (F-126, F-951, F-703) | VERIFIED | `manager.py` order re-read: `intent_store.consume_and_record_entry_intent` (line 669), then `mark_sent` (748), then the entry placement (call at 224 inside the entry helper), `finalize_entry_outcome` (736), STOP_LOSS `mark_sent` (841), `place_algo_protective` (1103). Behavior-dependent, so it needs a test: `test_execution_write_ahead_pg` (10) reads the committed row from a second connection during the adapter call and injects crashes between steps; `test_intent_recovery` (21) and `test_intent_recovery_pg` (13) pass. |
| SC4 | A test calls `execute_approved_plan` twice with the same approval and across a restart, against a Binance-semantics fake, and proves exactly one entry (F-603) | VERIFIED | Behavior-dependent. `tests/test_execution_exactly_once_pg.py` (28 tests) re-run with `TEST_DATABASE_URL` and `TRADING_CI_STRICT=1`: pass, no skips. It covers double call after fill, replay after cancel, restart with zero adapter calls, the open/filled/canceled x restart matrix, a two-thread race with separate engines, and negative controls (a never-remembering store places two entries; two concurrent calls without a durable row both reach the exchange). Also `test_approval_replay_pg` (5), `test_approval_replay` (16), `test_callback_redelivery_pg` (12): pass. The fake's open-orders-only uniqueness rule is the documented Binance rule, re-read live on 2026-10-07 (docs/SOURCES.md). |
| SC5 | PG and migration tests run on a disposable `_test` database in CI (F-606) | VERIFIED | `tests/pg_support.py` builds a template only by `alembic upgrade head` and creates per-test databases with generated `_test` names. With `TEST_DATABASE_URL` unset and `TRADING_CI_STRICT=1`, a PG test ERRORs with "missing infrastructure is a failure" (run by me); `test_pg_fixture_guard` (25) passes. First remote run now observed: `gh run 37180873501` (push to master, 2026-10-04, SHA 8763ac3) concluded success for lint, types, docker and test; the test job log shows `3756 passed, 17 deselected` with `TRADING_CI_STRICT: 1`. 8763ac3 contains 06a3d42, 2a62ab6, 1b65bcd (the last Phase 17 source commits) and also the transitions docstring and ci.yml hardening. |

**Score:** 5/5 truths verified (0 present but behavior-unverified, 0 overrides, 0 coincidental-reliance).

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | Duplicate-id code -4116 for algo orders, and id reuse after the first order is closed, not yet observed on a live Binance environment | Phase 18 demo/testnet probe (owner per docs/SOURCES.md), campaign in Phase 25 | SOURCES.md line 125. Phase 17 code does not depend on either: the exactly-once guarantee rests on the database intent row and the `(approval_id, role)` key, and the fake's behavior matches the documented "unique among open orders" rule that was re-read live. Only the extension (-4116 for `clientAlgoId`, reuse after close) is still an inference. |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/persistence/execution_state.py` | Durable consume plus write-ahead intents | VERIFIED | Wired through the `ExecutionIntentStore` Protocol; manager requires it (`None` raises ValueError) |
| `src/persistence/approvals.py`, `journal.py`, `entities.py`, `snapshots.py`, `system_state.py`, `uow.py`, `engine.py`, `errors.py` | Stores, UoW, engine | VERIFIED | `mypy src`: no issues in 149 files; `ruff check src tests`: all passed |
| `src/db/alembic/versions/0004_persistence_integrity.py` | Hand-written hardening, reversible | VERIFIED | Exercised by migration, constraint, trigger and enum tests |
| `src/domain/transitions.py` | DOMN-04 tables | VERIFIED | `test_transitions` (52) passes; docstring now states user confirmation |
| `tests/pg_support.py`, `tests/support/fake_binance_exchange.py` | Disposable DB, Binance-semantics fake | VERIFIED | See SC4, SC5 |
| `.github/workflows/ci.yml` | Digest-pinned PG service, strict flag, `TEST_DATABASE_URL` | VERIFIED | Confirmed by the green remote run |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| `execute_approved_plan` | `ExecutionIntentStore` | required kwarg `intent_store` | WIRED |
| manager replay gate | stored ENTRY row | identity check, then stored-outcome read, before the expiry gate | WIRED |
| `PgExecutionStateStore` | `approvals` table | same-transaction conditional UPDATE | WIRED |
| stores | `src/db/mappers.py` | `*_to_row` / `*_from_row` | WIRED |
| CI job | PG battery | service container, strict flag, `TEST_DATABASE_URL` | WIRED (remote run green) |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
|----------|------|--------|-----------|--------|
| Replay outcome | stored `ExecutionOutcome` | `execution_intents.outcome_*` columns via `get_entry` | Yes, asserted against raw SQL in tests | FLOWING |
| Plan hash | persisted plan Decimals | quantized before hashing; `PrecisionError` above 18 digits | Yes, `test_plan_hash_roundtrip_pg` | FLOWING |

### Behavioral Spot-Checks (run by this verifier, file by file)

Environment: a throwaway `postgres:17.11-bookworm` container (port 55432, CI's throwaway credentials, removed afterwards), `TRADING_CI_STRICT=1`. Every file below exited 0; with strict mode on, a skip would have been a failure. The user's own running compose database was not used.

| Group | Files (tests) | Result |
|-------|---------------|--------|
| Core SC2 to SC5 | exactly_once_pg 28, write_ahead_pg 10, approval_replay_pg 5, migration_pg 32, constraints_pg 45 | pass |
| Persistence stores and DB | approvals_pg 27, engine_pg 5, engine_timeouts 5, enum_columns_pg 25, journal_pg 21, roundtrip_pg 7, transitions_pg 65, triggers_pg 60, uow_pg 5 | pass |
| Recovery, state, snapshot | intent_recovery 21, intent_recovery_pg 13, system_state_pg 28, callback_redelivery_pg 12, constraint_snapshot 50, constraint_snapshot_pg 16, plan_hash_roundtrip_pg 22, domain_mappers_pg 5 | pass |
| Pure logic and manager | transitions 52, journal_ids 30, journal_failure_paths 7, pg_fixture_guard 25, approval_replay 16, execution_manager 61 (includes the CR-01 tests) | pass |
| Fail closed without a database | `env -u TEST_DATABASE_URL TRADING_CI_STRICT=1 pytest tests/test_persistence_constraints_pg.py -x` | ERROR "missing infrastructure is a failure" (expected) |
| Static | `mypy src`; `ruff check src tests` | no issues in 149 files; all checks passed |

I did not run the whole workspace suite (Windows crashes on a full run); the remote CI run (3756 passed, strict) is the full-suite evidence for the same code.

### Probe Execution

No probe-based verification is declared by this phase. SKIPPED.

### Requirements Coverage

| Requirement | Source Plans | Status | Evidence |
|-------------|--------------|--------|----------|
| DOMN-01 | 17-01, 02, 04, 05, 07, 08, 09, 10, 13, 15 | SATISFIED | Stores for all seven entities, enum CHECKs, explicit status columns |
| APRV-02 | 17-01, 02, 04, 05, 09, 11, 14, 15 | SATISFIED | Unique token hash, one decided per plan, durable consumption, replay tests |
| EXEC-03 | 17-01, 02, 11, 12, 14, 15 | SATISFIED | SC3 and SC4 |
| EXEC-04 | 17-06, 13, 15 | SATISFIED (as scoped) | Constraint snapshot table with hash-verified reads; live margin/leverage/equity stay UNKNOWN sentinels until Phases 21-22 by D-19 |
| DOMN-04 | 17-02, 03, 10, 15 | SATISFIED | `assert_transition` in repositories plus DB terminal triggers; tables confirmed by the user 2026-10-02 (D051 item (i)) |

REQUIREMENTS.md bookkeeping note (unchanged from the first report): the traceability table maps DOMN-01 to Phase 3 and APRV-02 / EXEC-03 to Phase 8 and does not list Phase 17, although the ROADMAP re-claims them. No requirement is orphaned.

### Anti-Patterns Found

TBD/FIXME/XXX/TODO/HACK scan over `src/persistence`, `src/domain/transitions.py`, `src/execution`, `src/reconcile`, the 0004 migration, `tests/pg_support.py` and `tests/support`: no matches. Code-review items IN-03 and IN-04 stay recorded as Info in 17-REVIEW-FIX and break no must-have. D051(h) lists gaps owned by later phases.

### Human Verification

None open. State of the four items from the first report, per 17-UAT.md (4 of 4 passed) and re-checked here:

| Item | State | Basis |
|------|-------|-------|
| DOMN-04 transition tables | Resolved | User confirmed 2026-10-02 (D051 item (i)); `transitions.py` docstring updated; `test_transitions` and `test_persistence_transitions_pg` pass |
| First remote CI run of the PG battery | Resolved | gh run 37180873501 (master 8763ac3, 2026-10-04): all four jobs success, 3756 passed, strict mode on. Checked with `gh run view` by this verifier |
| Binance clientOrderId and retention facts | Resolved for what is documented; remainder deferred | Live re-read 2026-10-07 recorded in docs/SOURCES.md; -4116 for algo ids and id reuse after close are in Deferred Items |
| CR-01 policy (swallow a failing SAFE_MODE audit write so the stop loss still runs) | Resolved | User accepted 2026-10-07 (D034: losing the audit row beats skipping the stop loss); `test_cr01_*` pass in `test_execution_manager` |

### Gaps Summary

No gaps. All five success criteria hold on code read and on tests run by this verifier, and the remote CI run confirms the full suite. The verdict follows the evidence: no open human item remains, and the one unverified Binance behavior is a deferred item with a named owner.

### Notes for the orchestrator

1. ROADMAP Phase 18 success criterion 2 (the demo/testnet probe) names only the GET order / GET algoOrder not-found codes. The two Phase 17 leftovers (-4116 for algo ids, id reuse after close) are owned in docs/SOURCES.md only. Consider adding them to the Phase 18 probe criterion or plan so the deferral cannot be lost. No file outside 17-VERIFICATION.md was changed by this verifier.
2. `.planning/ROADMAP.md` still shows Phase 17 as `[ ]` in the phase list although all 15 plans are executed.

---

_Verified: 2026-10-07T04:50:48Z_
_Verifier: Claude (gsd-verifier)_
