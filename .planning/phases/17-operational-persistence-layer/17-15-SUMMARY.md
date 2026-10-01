---
phase: 17-operational-persistence-layer
plan: 15
subsystem: docs
tags: [documentation, decision-record, D051, data-model, execution-spec, runbook, sources, phase-gate, postgresql]

requires:
  - phase: 17-operational-persistence-layer
    provides: "plans 01-14: migration 0004, src/persistence stores, write-ahead execution flow, restart recovery, snapshots, system state, transitions, PostgreSQL test battery"
provides:
  - "Canonical docs that describe the shipped persistence layer: DATA_MODEL 2.14-2.16 and integrity rules, EXECUTION_SPEC sections 7 and 10.1, BINANCE 6.1, SOURCES 'Facts verified for Phase 17', TESTING_STRATEGY 8, 10, 11 and 12.1, RUNBOOK 5, 6, 9, 11.5, 14.4, SECURITY_AND_OPERATIONS 9"
  - "DECISIONS D051 (stores, schema 0004, plan hash and regeneration inventory, write-ahead and recovery, snapshots, transitions, tests, known gaps) and the DOC_STATUS change-log line"
  - "17-CONTEXT.md 'Post-research corrections' note (C1, C2, C8, D-22)"
  - "Phase 17 gate evidence: full suite, strict PostgreSQL battery, ruff, format, mypy, uv lock, decision alignment"
affects: [phase-18, phase-19, phase-20, phase-21, phase-22, phase-23, phase-24, phase-26]

actuals:
  tokens: 15800
  tasks: 2
  commits: 3
plan_head_before: facac498540150f62d96f642bb52cfa725581a91
plan_head_after: a1b418d42e7c595a7f170f266560b2f87dbd4d6d

tech-stack:
  added: []
  patterns:
    - "Binance facts behind a WAF challenge are read from Internet Archive snapshots of the official URL or from the official SDK docstring, with the snapshot date and MEDIUM confidence recorded per row"
    - "D051 carries the full deliberate-regeneration inventory (D048 style) and every planner refinement, so no auto-mode default is undocumented"
    - "CRLF-preserving doc edits through a line-ending-aware helper (kept in the scratchpad, not committed)"

key-files:
  created:
    - .planning/phases/17-operational-persistence-layer/17-15-SUMMARY.md
  modified:
    - docs/data/DATA_MODEL.md
    - docs/trading/EXECUTION_SPEC.md
    - docs/integration/BINANCE.md
    - docs/SOURCES.md
    - docs/testing/TESTING_STRATEGY.md
    - docs/operations/RUNBOOK.md
    - docs/operations/SECURITY_AND_OPERATIONS.md
    - docs/DECISIONS.md
    - docs/DOC_STATUS.md
    - .planning/phases/17-operational-persistence-layer/17-CONTEXT.md
    - .planning/phases/17-operational-persistence-layer/17-RESEARCH.md

key-decisions:
  - "D051 is the next free decision id (D050 was the last row; verified at write time, D052 and later absent); Status 'Accepted (2026-10-01, Phase 17 auto-mode defaults ...; the user may override)'"
  - "The six transition tables stay 'Accepted (auto-mode default; user to confirm)': APPROVED -> SUPERSEDED is illegal in the draft, Order and Position UNKNOWN exits are reconciliation-only, equal old/new is an idempotent no-op (assert_transition raises, repositories check equality first)"
  - "Binance facts are MEDIUM confidence: the live pages answer with a CloudFront WAF challenge (HTTP 202, empty body); three pages were read from Wayback snapshots (2026-05-19, 2026-06-16, 2026-06-17) and the New Order sentence from the official SDK 17.4.0 docstring"
  - "Pre-existing lint item fixed by running ruff format on the single research file (the smallest safe change); the broader option of excluding .planning in [tool.ruff] is left to the user"

patterns-established:
  - "A doc that states a Binance fact cites SOURCES 'Facts verified for Phase N' and carries a 'verify against current Binance docs before implementation' marker when the live page could not be read"

requirements-completed: [DOMN-01, APRV-02, EXEC-03, EXEC-04, DOMN-04]

coverage:
  - id: D1
    description: "DATA_MODEL documents execution_intents, plan_constraint_snapshots, system_state_events, the approval consumption columns, every 0004 constraint family, UTC session rule, append-only and terminal triggers, 18-digit storage rule and deterministic journal ids"
    requirement: DOMN-01
    verification:
      - kind: command
        ref: "grep -n execution_intents docs/data/DATA_MODEL.md; grep -n system_state_events docs/data/DATA_MODEL.md"
        status: pass
      - kind: command
        ref: "scripts/verify_decision_alignment.py all"
        status: pass
    human_judgment: false
  - id: D2
    description: "EXECUTION_SPEC section 7 states the write-ahead order, consumption only at placement, identity -> stored outcome -> expiry, one entry per plan in the database, the SL write-failure policy, and that exchange clientOrderId dedup is not relied on (retires Phase 08 D-04, F-951); section 10.1 states restart recovery"
    requirement: EXEC-03
    verification:
      - kind: command
        ref: "grep -n 'unique id among open orders' docs/trading/EXECUTION_SPEC.md docs/integration/BINANCE.md"
        status: pass
    human_judgment: false
  - id: D3
    description: "Binance clientOrderId/clientAlgoId uniqueness, -4116 and the Query Order retention windows are recorded with provenance and confidence in SOURCES and BINANCE 6.1"
    requirement: EXEC-03
    verification:
      - kind: command
        ref: "grep -n 'Facts verified for Phase 17' docs/SOURCES.md"
        status: pass
    human_judgment: true
    rationale: "The live developers.binance.com pages could not be fetched (WAF challenge); facts come from archived snapshots and the SDK docstring at MEDIUM confidence and must be re-read from the live pages before Phase 19 and 20 order paths"
  - id: D4
    description: "TESTING_STRATEGY replaces the nonexistent TradePlanStatus CANCELED example, documents the disposable t17_*_test databases, TRADING_CI_STRICT and the SC4 matrix with negative controls; RUNBOOK states db-upgrade applies 0004, restore runs alembic upgrade head, append-only tables and what UNRESOLVED_EXECUTION_INTENT means"
    requirement: DOMN-01
    verification:
      - kind: unit
        ref: "tests/test_deploy_docs.py"
        status: pass
      - kind: command
        ref: "grep -nE '^TradePlanStatus: +CANCELED' docs/testing/TESTING_STRATEGY.md (no output)"
        status: pass
    human_judgment: false
  - id: D5
    description: "DECISIONS D051, DOC_STATUS change-log line and the CONTEXT post-research corrections note exist; D051 follows D050 contiguously"
    requirement: APRV-02
    verification:
      - kind: unit
        ref: "tests/test_decision_alignment_bookkeeping.py"
        status: pass
      - kind: command
        ref: "grep -n '^| D051 |' docs/DECISIONS.md; grep -n 'Post-research corrections' 17-CONTEXT.md"
        status: pass
    human_judgment: false
  - id: D6
    description: "Phase gate: full suite with TEST_DATABASE_URL, strict-mode PostgreSQL battery with zero skips, ruff, ruff format, mypy, uv lock --check, decision alignment"
    requirement: EXEC-04
    verification:
      - kind: command
        ref: "pytest -m 'not docker' -rs (3604 passed, 10 skipped, 16 deselected)"
        status: pass
      - kind: command
        ref: "TRADING_CI_STRICT=1 pytest <21 Phase 17 PostgreSQL modules> -rs (541 passed, 0 skipped)"
        status: pass
    human_judgment: false
  - id: D7
    description: "The six transition tables (GLOSSARY section 11, src/domain/transitions.py, 0004 terminal-trigger arguments) are the right business rules"
    requirement: DOMN-04
    human_judgment: true
    rationale: "Research C3: the tables were authored as an auto-mode default and are recorded in D051 as 'Accepted (auto-mode default; user to confirm)'; only the user can confirm or override them"

duration: 36min
completed: 2026-10-01
status: complete
---

# Phase 17 Plan 15: Canonical docs, D051 and the phase gate Summary

**The canonical documents now describe exactly what Phase 17 shipped (three new tables, the write-ahead flow, restart recovery, the PostgreSQL test policy) and state that the exchange does not deduplicate client order ids, D051 records every auto-mode default, planner refinement and the plan-hash regeneration inventory, and the full PostgreSQL battery passes with zero skips.**

## Performance

- **Duration:** about 36 min (an estimate; the clock was not recorded at start), of which about 16 min is the full-suite run
- **Completed:** 2026-10-01
- **Tasks:** 2 (both documentation; Task 2 includes the phase gate)
- **Files:** 11 modified (10 in the plan's list plus 17-RESEARCH.md for the lint item), 1 created (this file); 295 insertions, 33 deletions

## Accomplishments

- **DATA_MODEL:** new sections 2.14 `execution_intents`, 2.15 `plan_constraint_snapshots`, 2.16 `system_state_events` (columns, keys, constraints, purpose, which phase reads them); 2.4 states that the constraint snapshot is a separate write-once table, not `trade_plans` columns; 2.5 approvals gains `consumption_status`/`consumed_at_utc`; 2.7, 2.9, 2.10 carry the unique client ids, the signed `positions.quantity` (no sign CHECK) and the append-only, deterministic-id journal; section 3 points to GLOSSARY 11 and 12; section 5 lists RESTRICT FKs, named enum CHECKs, price/quantity CHECK conventions, VARCHAR(32) widths, UTC session pin, append-only and terminal-status triggers, 18-digit `ROUND_HALF_EVEN` storage with `PrecisionError`, deterministic journal ids and the migration-only schema rule.
- **EXECUTION_SPEC:** section 7 rewritten (7.1 the exchange does not deduplicate and the Phase 08 D-04 premise is retired, F-951; 7.2 write-ahead order with commit points, consumption only at placement, gate order identity -> stored outcome -> expiry, database-enforced one-entry-per-plan, replay with zero adapter calls, the callers' note on `APPROVAL_EXPIRED`; 7.3 failure policy including the SL write-failure rule); new 10.1 restart recovery (UNKNOWN, deterministic-id query, 3-day window, SAFE_MODE `UNRESOLVED_EXECUTION_INTENT`, implementation status and the Phase 20 gap).
- **Binance facts:** BINANCE 6.1 and SOURCES "Facts verified for Phase 17" record `newClientOrderId`/`clientAlgoId` ("unique id among open orders"), `-4116 DUPLICATED_CLIENT_ORDER_ID`, and the Query Order retention (3 and 90 days), each with source, date, method and MEDIUM confidence (see Deviations for the retrieval method).
- **TESTING_STRATEGY:** the stale `TradePlanStatus: CANCELED` example is replaced with `EXPIRED -> APPROVED` and tied to `tests/test_transitions.py` and the PostgreSQL terminal-trigger parity test; sections 10 and 11 list the replay, redelivery, write-ahead, crash-injection, SC4 and recovery tests with their negative controls; new 12.1 states the PostgreSQL test policy (template clone, generated names, never `create_all`, `TRADING_CI_STRICT`, the `_test` URL convention from `deferred-items.md`).
- **RUNBOOK and SECURITY_AND_OPERATIONS:** section 5 (read-only SQL and how to read `execution_intents`), 6 (replay returns the stored outcome), 9 (fail-closed stores, `UNRESOLVED_EXECUTION_INTENT`, append-only tables), 11.5 and 14.4 (`db-upgrade` applies migration 0004, restore runs `alembic upgrade head` through 0004); one SECURITY_AND_OPERATIONS paragraph (append-only audit tables, role separation deferred to Phase 26, backups carry the new tables). RUNBOOK section 16 and every test-enforced step table are untouched.
- **DECISIONS D051 and DOC_STATUS:** one table row after D050 covering items (a) to (i): stores and contracts, schema 0004 (C1, C4 refinement, C5, C6, C19, alembic floor), plan hash (D-12, ROUND_HALF_EVEN, the full regeneration inventory with old and new sha256), consumption and write-ahead (C2, C8, Open Q1, Q2, Q5, SL failure policy, consume race fix, recovery rules, F-951), snapshots and system state (C10, C14), transitions (auto-mode default, user to confirm), tests and CI (C9), known gaps, verification status. A DOC_STATUS change-log line lists every amended document.
- **17-CONTEXT.md:** "Post-research corrections (Phase 17 planning)" note: C1 (`db-upgrade` and the restore path, not `deploy/migrate.sh`), C2, C8, D-22; the decisions themselves are not rewritten.
- **Lint item:** `ruff format` run on `17-RESEARCH.md` (one file, the fenced Python sketches); repo-root `ruff format --check` now passes (754 files).

## Task Commits

1. **Task 1: DATA_MODEL, EXECUTION_SPEC, BINANCE, SOURCES, TESTING_STRATEGY** - `6fa5cad` (docs)
2. **Task 2: RUNBOOK, SECURITY_AND_OPERATIONS, D051, DOC_STATUS, CONTEXT note** - `36409db` (docs)
3. **Lint item (research document code blocks)** - `a1b418d` (chore)

**Plan metadata:** docs commit follows this SUMMARY (STATE.md, ROADMAP.md, REQUIREMENTS.md).

## Phase gate (real runs, PostgreSQL 17.11 in Docker, `TEST_DATABASE_URL` set to the `trading_test` database)

| Check | Result |
|-------|--------|
| `pytest -m "not docker" -rs -q` (full suite, after the last commit `a1b418d`) | exit 0: **3604 passed, 10 skipped, 16 deselected in 946 s** |
| Skips in that run | 1 symlinks unavailable on Windows, 1 NTFS cannot represent POSIX modes, 8 `shellcheck` not on PATH. **Zero PostgreSQL skips.** The 16 deselected are the `docker`-marked tests (image not built on this host) |
| `TRADING_CI_STRICT=1 pytest` over the 21 Phase 17 PostgreSQL modules (`tests/test_persistence_*`, `tests/test_execution_*_pg.py`, `test_intent_recovery_pg`, `test_constraint_snapshot_pg`, `test_system_state_pg`, `test_controller_rehydrate`, `test_approval_replay_pg`, `test_callback_redelivery_pg`, `test_plan_hash_roundtrip_pg`, `test_domain_mappers_pg`, `test_pg_fixture_guard`, `test_analytics_store`) | exit 0: **541 passed, 0 skipped in 244 s** (no SKIPPED line) |
| `ruff check` | All checks passed |
| `ruff format --check` (repo root, no path) | 754 files already formatted |
| `mypy src` | Success: no issues found in 132 source files |
| `uv lock --check` | exit 0 (Resolved 60 packages) |
| `scripts/verify_decision_alignment.py all` | ALL_PASS (DC-01..DC-06 pass) |
| `pytest tests/test_deploy_docs.py tests/test_deploy_workflows.py tests/test_decision_alignment*.py tests/test_kill_gate_docs.py tests/test_transitions.py` | all passed (471 tests, run after the last documentation edit) |

Why the strict run is per module and not the whole suite: under `TRADING_CI_STRICT=1` this Windows host fails the 8 shellcheck tests and the docker-image tests (missing infrastructure is a failure by design), exactly as 17-14 recorded. The strict canary (`tests/test_pg_fixture_guard.py`) proves that a missing `TEST_DATABASE_URL` fails under strict mode. The known Windows flakes (`PermissionError` in `tests/test_backfill_cli.py`, `tests/test_universe_freeze.py`) did not occur in this run.

Acceptance criteria re-run: `grep -n "Facts verified for Phase 17" docs/SOURCES.md` one line (103); the open-orders sentence is found in EXECUTION_SPEC (129) and BINANCE (64, 66); `execution_intents` and `system_state_events` are in DATA_MODEL; no `TradePlanStatus: CANCELED` line remains; `^| D051 |` exactly one row and no `D052`-`D059` row; `Phase 17` in DOC_STATUS (line 58); `Post-research corrections` one line in 17-CONTEXT.md (156); `db-upgrade` present in RUNBOOK (lines 277, 297, 298, 407).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] WebFetch re-verification was not possible; Binance pages read from archive snapshots and the SDK docstring**
- **Found during:** Task 1
- **Issue:** the plan asks for WebFetch of four official Binance pages. No WebFetch tool exists in this environment, and the live developers.binance.com pages answer `curl` with HTTP 202, an empty body and `x-amzn-waf-action: challenge` (the same WAF behaviour SOURCES already records for Phase 13), also after the 302 redirect to the new `/en/docs/...` URLs.
- **Fix:** read Wayback Machine snapshots of the same official URLs (error codes 2026-06-16, Query Order 2026-06-17, New Algo Order 2026-05-19) and extracted the text; the New Order page has no readable snapshot (it redirects to a challenged catalog URL), so its `newClientOrderId` sentence was taken from the official SDK 17.4.0 docstring (`trade_api.py`, `new_order`), which is the version in `uv.lock`. Every SOURCES row states the method, date and MEDIUM confidence, the New Order row says "live page NOT fetched", and BINANCE 6.1 and EXECUTION_SPEC carry the "verify against current Binance docs before implementation" marker, as the plan prescribes for a page that could not be retrieved.
- **Files modified:** docs/SOURCES.md, docs/integration/BINANCE.md
- **Commit:** 6fa5cad

**2. [Rule 3 - Blocking] `ruff format --check` at the repo root fails on a planning document**
- **Found during:** Task 2 (phase gate; the plan's verify command runs it at the repo root)
- **Issue:** `.planning/phases/17-operational-persistence-layer/17-RESEARCH.md` has unformatted fenced Python (deferred-items.md, plan 17-01); CI's lint job would fail on it.
- **Fix:** `ruff format` on that one file (the smallest safe change, 56 lines of code-block whitespace). Not done: excluding `.planning/` in `[tool.ruff]`, which would also protect later research documents.
- **Files modified:** .planning/phases/17-operational-persistence-layer/17-RESEARCH.md
- **Commit:** a1b418d

**3. [Plan note] `docs/data/DATA_MODEL.md` is matched by a `.gitignore` pattern (`docs/data`)** although the file is tracked; `git add` refuses it, so it was staged with `git add -u` (no force-add, no ignore change). Phase 13-11 had the same situation.

**4. [Plan note] `src/persistence/__init__.py` module map is stale** (lists four of the nine modules); it is outside this plan's file list and was not changed. A one-line follow-up for the next plan that touches the package.

**Total deviations:** 2 auto-fixed (Rule 3), 2 notes. **Impact:** none on scope; the Binance facts are weaker (MEDIUM) than a live read would give.

## Open items for the user

- **DOMN-04 (manual-only check):** read GLOSSARY section 11 and the D051 item (f) and confirm or override the six transition tables. In particular: should TradePlan `APPROVED -> SUPERSEDED` be legal (it is illegal in the draft), and are Order/Position `UNKNOWN` exits reconciliation-only. Expected reply: "confirmed", or the changed pairs; a change touches `src/domain/transitions.py`, GLOSSARY 11 and the 0004 terminal-trigger arguments together.
- Re-read the four Binance pages from the live site (or a browser) before Phase 19 and 20 order paths; confirm on the demo environment that a filled or canceled client id is accepted again (the SC4 fake models it, a live account was not used).
- The first remote CI run of the Phase 17 tests has not been observed; everything above ran on the development machine.
- Optional: exclude `.planning/` in `[tool.ruff]` so later research documents cannot trip the lint job again.

## Known gaps owned by later phases (all recorded in D051 item (h))

- (a) A crash after the STOP_LOSS intent leaves an acknowledged entry without a stop and a restart does not place one (Phase 20).
- (b) With a failing journal, controller disable, `expire_pending_entry`, `cancel_untriggered_protectives` and `emergency_manual_close` behave unsafely (plan 17-08 finding, F-702, Phase 20).
- (c) After the plan's expiry `dispatch_callback` answers a redelivered APPROVE with `APPROVAL_EXPIRED` although execution happened; Phase 23/24 must read `PgExecutionStateStore.get_entry` for the message.
- (d) Nothing yet writes or reads the system-state, snapshot or recovery paths at startup (Phase 20 and 24).

## Known Stubs

None. (Documentation plan; the INCOMPLETE constraint snapshots are an intended, documented state, not a stub.)

## Threat Flags

None. T-17-39 mitigated (Binance facts carry URL, date, method and confidence; EXECUTION_SPEC states the open-orders-only rule), T-17-40 mitigated (D051 carries the regeneration inventory, both checkpoint resolutions and every refinement; DOC_STATUS line). T-17-SC: no packages installed.

## Self-Check: PASSED

- All ten files of the plan's list plus `17-RESEARCH.md` are modified and committed; `17-15-SUMMARY.md` exists.
- Commits `6fa5cad`, `36409db`, `a1b418d` exist on `master`; measured commit count 3 from the recorded plan head `facac49`.
- Task acceptance criteria and the plan-level verification were re-run after the last commit (results in the gate table above).
