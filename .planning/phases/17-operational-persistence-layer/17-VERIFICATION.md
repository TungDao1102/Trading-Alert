---
phase: 17-operational-persistence-layer
verified: 2026-10-02T00:00:00Z
status: human_needed
score: 5/5 must-haves verified
covered_files:
  - src/db/alembic/versions/0004_persistence_integrity.py
  - src/execution/manager.py
  - src/persistence/approvals.py
  - src/persistence/engine.py
  - src/persistence/execution_state.py
  - src/persistence/uow.py
  - src/reconcile/safe_mode.py
  - tests/pg_support.py
  - tests/test_execution_exactly_once_pg.py
covered_digest: "v2:sha256:2aa637fcf532be8cae25858630f7863e51f54c8ac28a2ee3fe2247b6c65e7512"
behavior_unverified: 0
overrides_applied: 0
re_verification: false
human_verification:
  - test: "Confirm or amend the DOMN-04 transition tables (src/domain/transitions.py, GLOSSARY section 11, terminal-trigger arguments in migration 0004)"
    expected: "Owner accepts the auto-mode draft, or changes all three places together. Open points: TradePlan APPROVED -> SUPERSEDED is illegal in the draft; Order and Position UNKNOWN exits are legal (reconciliation-only); the terminal sets."
    why_human: "D051(f) records the tables as an auto-mode default that still awaits user confirmation. The code and tests enforce the draft correctly, but whether the draft is the intended state machine is a product decision."
  - test: "Observe the first remote CI run of the PostgreSQL battery (ci.yml `test` job with the postgres:17.11 service, TRADING_CI_STRICT=1)"
    expected: "The Phase 17 *_pg tests execute (no skips) and pass on ubuntu-24.04 against the digest-pinned service."
    why_human: "The battery was run locally against PostgreSQL 17.11 in Docker only. D051(i) states the first remote run has not been observed. SC5 is verified by code and by a local strict run, not by a remote run."
  - test: "Re-read the Binance facts from the live developers.binance.com pages (newClientOrderId unique among OPEN orders only; Query Order 3-day retention of canceled/expired orders without fills) before the Phase 19/20 order paths"
    expected: "The live docs agree with BinanceSemanticsFakeAdapter and with the 3-day recovery window in the restart-recovery code."
    why_human: "The facts come from Internet Archive snapshots (confidence MEDIUM) because the live pages answered with a WAF challenge. The fake was not validated against a live Binance account (AGENTS.md exchange-authority rule)."
  - test: "Accept the CR-01 policy choice: manager._enter_safe_mode swallows a failing SAFE_MODE audit write so the stop loss and the unprotected-entry cancel still run"
    expected: "Owner agrees that losing the SAFE_MODE audit row (flag still set in memory) is preferable to skipping the stop loss during a database outage."
    why_human: "17-REVIEW-FIX marks this fail-closed logic change as 'requires human verification'. The behavior is covered by four regression tests and I judge it consistent with D034, but it is a safety-policy trade-off."
---

# Phase 17: Operational Persistence Layer Verification Report

**Phase Goal:** Operational state lives durably in PostgreSQL with integrity constraints. A replayed callback or a restart can never create a second entry.
**Verified:** 2026-10-02
**Status:** human_needed (all five success criteria verified in code and by tests I ran myself; four items need a human decision or observation, none is a defect)
**Re-verification:** No, initial verification.

## Goal Achievement

The goal is achieved in the codebase. A replayed APPROVE reaches `execute_approved_plan`, which reads the stored ENTRY intent row by approval id and returns the stored outcome with zero adapter calls. The row is written in the same transaction that marks the approval consumed, before `place_entry`. The database primary key `(approval_id, role)` and the partial-unique client-id indexes are the second line of defence, independent of Python. The tests prove this against a fake that really frees the client id after FILLED or CANCELED, across a restart (disposed engines, new store and manager) and across two concurrent threads, and each has a negative control.

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC1 | PG implementations of the journal, approval and execution-state stores exist; the row mappers have production callers (F-202) | VERIFIED | `src/persistence/journal.py` (`journal_to_row`/`journal_from_row`), `approvals.py` (`approval_to_row/from_row`, `short_id_mapping_to_row`), `entities.py` (signal, trade_plan, order, fill, position pairs via `_Spec` table), `execution_state.py`, `snapshots.py`, `system_state.py`. Each has a mypy-only conformance block against the existing consumer Protocols (D-02). Production callers are inside `src/persistence`; no live process composes them yet, which is Phase 24 by CONTEXT scope. |
| SC2 | Unique token hash, one decided approval per plan, unique client_order_id; FKs and CHECKs; widths that fit; UTC session pin; ORM indexes in parity | VERIFIED | Migration `0004_persistence_integrity.py`: `uq_approvals_token_hash`, partial `uq_approvals_one_decided_per_plan WHERE status <> 'PENDING'`, partial unique `orders.client_order_id`/`algo_client_id`, 12 `ON DELETE RESTRICT` FKs, 11 enum CHECKs plus price/quantity CHECKs, six columns widened to VARCHAR(32), append-only and terminal triggers. UTC: `build_connect_args` sets `-c timezone=UTC` and `make_sync_engine` asserts `SHOW TimeZone` (and the async engine in `src/db/models.py` pins it too). Parity: compare_metadata test plus catalog checks replace the deleted column-name script. Ran `test_persistence_constraints_pg.py` and `test_persistence_migration_pg.py`: pass. |
| SC3 | Approval consumption is durable; execution intent is written ahead before `place_entry` and between entry and SL (F-126, F-951, F-703) | VERIFIED | `PgExecutionStateStore.consume_and_record_entry_intent` inserts the ENTRY intent (`ON CONFLICT (approval_id, role) DO NOTHING`) and runs a conditional `UPDATE approvals` (UNCONSUMED -> CONSUMED, status APPROVED) in ONE transaction; rowcount != 1 raises and rolls back the insert. `manager.py` order: consume (669) -> `mark_sent` (748) -> `place_entry` (759) -> ACKED/UNKNOWN/REJECTED (777-815) -> STOP_LOSS INTENDED+SENT (824-846) -> `place_algo_protective` (857) -> SL result (875) -> `finalize_entry_outcome`. `test_execution_write_ahead_pg.py` reads the committed row from a second connection during the adapter call and injects crashes between steps. |
| SC4 | A test calls `execute_approved_plan` twice with the same approval and across a restart, against a Binance-semantics fake, and proves exactly one entry (F-603) | VERIFIED | `tests/test_execution_exactly_once_pg.py` + `tests/support/fake_binance_exchange.py` (rejects a duplicate OPEN client id with -4116, accepts it after `fill()`/`cancel()`, 3-day history retention; kwargs are bound against the real `BinanceUsdmAdapter` signature). Tests: double call after fill, replay after cancel, restart with zero adapter calls, SC4 matrix (open/filled/canceled x with/without restart), two-thread race with separate engines, and negative controls (a never-remembering store places two entries; two concurrent calls without a durable row both reach the exchange). I re-ran this file: pass. |
| SC5 | PG and migration tests run on a disposable `_test` database in CI | VERIFIED (remote run unobserved) | `tests/pg_support.py`: session template built only by `alembic upgrade head` (subprocess), per-test `CREATE DATABASE ... TEMPLATE`, names validated against `^t17_(tmpl_)?[0-9a-f]+_test$`, `DROP ... WITH (FORCE)`. Missing `TEST_DATABASE_URL` under `TRADING_CI_STRICT=1` is a failure: I ran a PG test with the variable unset and it ERRORed ("missing infrastructure is a failure"). `.github/workflows/ci.yml` has a digest-pinned postgres:17.11 service, `TRADING_CI_STRICT: "1"`, and `TEST_DATABASE_URL`; the run step is `pytest -m "not docker"`, which includes the PG tests. Migration test covers upgrade/downgrade/upgrade and a 0003 -> 0004 data-bearing upgrade. First remote CI run not observed: see human_verification. |

**Score:** 5/5 truths verified (0 behavior-unverified, 0 overrides).

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/persistence/execution_state.py` (386 lines) | Durable consume + write-ahead intents | VERIFIED | Substantive; wired through `ExecutionIntentStore` Protocol; targeted ON CONFLICT, lost-race re-check, `with_for_update` plus `assert_transition` on status writes |
| `src/persistence/approvals.py`, `journal.py`, `entities.py`, `snapshots.py`, `system_state.py`, `uow.py`, `engine.py`, `errors.py` | Stores, UoW, engine | VERIFIED | All substantive; no TBD/FIXME/XXX/TODO/HACK |
| `src/db/alembic/versions/0004_persistence_integrity.py` (690 lines) | Hand-written schema hardening, reversible | VERIFIED | No project imports (immutable snapshot); full downgrade |
| `src/domain/transitions.py` | DOMN-04 tables | VERIFIED | Six machines; asserted in repositories; mirrored by DB terminal triggers; GLOSSARY text parity test |
| `src/domain/journal.py` | Deterministic ids | VERIFIED | `correlated_event_id`, `content_hash_event_id`; no `uuid4` in `src` outside migrations |
| `tests/pg_support.py`, `tests/support/fake_binance_exchange.py` | Disposable DB, Binance-semantics fake | VERIFIED | See SC4/SC5 |
| Canonical docs (DATA_MODEL, EXECUTION_SPEC, TESTING_STRATEGY, RUNBOOK, GLOSSARY, DOC_STATUS, DECISIONS D051) | D-27 same-change updates | VERIFIED | Each contains Phase 17 / 0004 / execution_intents / write-ahead content; D051 row present |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `execute_approved_plan` | `ExecutionIntentStore` | required arg (`None` raises `ValueError`) | WIRED | manager.py:450 |
| manager replay gate | `get_entry` | identity check (Gate 0) then stored-outcome read, before expiry gate | WIRED | manager.py:470-496 |
| `PgExecutionStateStore` | `approvals` table | same-transaction conditional UPDATE | WIRED | execution_state.py consume |
| stores | `src/db/mappers.py` | `*_to_row` / `*_from_row` | WIRED | journal, approvals, entities |
| `PgJournalStore` | SafeMode / sweeper / enablement / health / killgate `JournalLike` | structural; mypy conformance block | WIRED | journal.py `_conforms` |
| CI job | PG battery | service container + strict flag + `TEST_DATABASE_URL` | WIRED | ci.yml |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
|----------|------|--------|-----------|--------|
| Replay outcome | stored `ExecutionOutcome` | `execution_intents.outcome_*` columns, read by `get_entry` | Yes, real SELECT; asserted against raw SQL in tests | FLOWING |
| Plan hash | persisted plan Decimals | planner quantizes to 18 digits before hashing; repository raises `PrecisionError` above 18 digits | Yes; 15 real planner plans stored, read back and re-hashed on PG | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Core SC2/SC3/SC4/SC5 proofs | `TEST_DATABASE_URL=... TRADING_CI_STRICT=1 pytest tests/test_execution_exactly_once_pg.py tests/test_execution_write_ahead_pg.py tests/test_approval_replay_pg.py tests/test_persistence_migration_pg.py tests/test_persistence_constraints_pg.py -rs` | exit 0, 120 tests, no skips | PASS |
| Wider Phase 17 battery (all `test_persistence_*`, `*_pg`, intent recovery, system state, redelivery, snapshot, plan-hash round trip, mappers, transitions, journal ids/failure paths, execution manager) under strict | same env, ~500 tests | exit 0, no skips | PASS |
| Strict mode fails closed without a database | `env -u TEST_DATABASE_URL TRADING_CI_STRICT=1 pytest tests/test_persistence_constraints_pg.py -x` | ERROR "missing infrastructure is a failure" | PASS |

### Probe Execution

No probe-based verification is declared by this phase. SKIPPED.

### Locked Decisions D-01..D-27

| Decision | Status | Evidence |
|----------|--------|----------|
| D-01 sync SQLAlchemy stores, `src/persistence/` | Honored | sync `Session`, psycopg, one module per store |
| D-02 domain authoritative, existing Protocols, mappers in place | Honored | mypy conformance blocks; no new Protocol except the stdlib-only `ExecutionIntentStore` the CONTEXT integration note calls for |
| D-03 explicit UoW | Honored | `OperationalDatabase.transaction()` |
| D-04 UTC pin, pre_ping, fail closed | Honored | engine.py; WR-01/WR-02 later added typed `StoreFailure` and bounded timeouts |
| D-05 migration 0004, hand-written | Honored with documented correction C1 | applied by compose `db-upgrade` and `src/ops/backup.py` restore path, not `deploy/migrate.sh` (D051(b), CONTEXT "Post-research corrections") |
| D-06 unique constraints | Honored | token hash, one decided per plan (partial), client ids (partial); `fills (order_id, exchange_trade_id)` kept. Extra: `UNIQUE(trade_plan_id, role)` on intents |
| D-07 FKs ON DELETE RESTRICT | Honored | 12 FKs; no FK on `short_id_mapping` |
| D-08 CHECKs | Honored with documented refinement C4 | `positions.quantity` has no sign CHECK (signed amount); `orders.quantity >= 0` |
| D-09 widths + insert-every-enum-member test | Honored | six columns to VARCHAR(32); `test_persistence_enum_columns_pg.py` |
| D-10 append-only journal, deterministic ids | Honored with documented correction C7 | triggers incl. TRUNCATE; ids are content/correlation hashes, not a per-correlation sequence (D051(b)) |
| D-11 ORM/migration parity via compare_metadata | Honored | 18 pre-existing indexes (not 14) declared; drift-sensitivity tests |
| D-12 plan_hash reproducible from stored row | Honored | quantize-before-hash, `canonical_decimal_text`; fixture regeneration inventoried in D051(c) |
| D-13 execution_intents | Honored with correction C2 | roles are real `OrderRole` values (ENTRY, STOP_LOSS, TAKE_PROFIT_1/2) |
| D-14 write-ahead order | Honored | see SC3 |
| D-15 replay returns stored outcome, zero adapter calls | Honored | `_stored_entry_outcome`; an ENTRY row without a recorded outcome returns RECONCILIATION_REQUIRED (fail closed) |
| D-16 explicit consumption state | Honored with correction C8 | `consumption_status` + `consumed_at_utc` tied by CHECK |
| D-17 DB constraint is correctness, lock only an optimization | Honored | lost race returns False; secondary-arbiter race re-checked in a fresh transaction (17-12 fix) |
| D-18 constraint snapshot table, canonical JSON + sha256, not in plan_hash | Honored | `plan_constraint_snapshots`, write-once triggers, `snapshots.py` |
| D-19 UNKNOWN sentinel for margin/leverage/equity | Honored | NOT NULL text + `live_inputs_status` CHECK |
| D-20 pure transitions + DB terminal rule | Honored (tables await owner confirmation) | `transitions.py`, six terminal triggers |
| D-21 no nullable-state inference | Honored | explicit status columns |
| D-22 system_state_events via journal; rehydrate | Honored with note | "latest" is a query, not a view (CONTEXT correction); SafeMode/Enablement `state_snapshot` + `rehydrate` constructors |
| D-23 disposable `_test` DB, CI hard-fail | Honored | stricter than asked (generated names only) |
| D-24 reuse ci.yml service; up/down/up; 0003 -> 0004 data test | Honored | |
| D-25 Binance-semantics fake + negative control | Honored | see SC4 |
| D-26 concurrency, crash-injection, DB double-decision, mapper round trip | Honored | `test_persistence_roundtrip_pg.py`, write-ahead and recovery tests |
| D-27 same-change doc updates, D051 | Honored | D051 present (verified free at write time) |

### Code Review Fixes (17-REVIEW-FIX), confirmed in code

| Finding | Status | Evidence |
|---------|--------|----------|
| CR-01 DB outage skipped the stop loss | Fixed | `manager.py:702-714` `_enter_safe_mode` wraps `enter_safe_mode` in `try/except Exception`; used at `_store_write`, the ENTRY_STATE_UNKNOWN branch and the ENTRY_WITHOUT_PROTECTIVE branch. Four `test_cr01_*` tests ran in `test_execution_manager.py` (pass) |
| WR-01 raw driver errors escaped | Fixed | `uow.py`: `IntegrityError` re-raised, connection errors -> `StoreUnavailable`, other `DBAPIError` -> `StoreFailure` (`from None`); `test_persistence_uow_pg.py` passes |
| WR-02 no connect/statement timeout | Fixed | `engine.py` `build_connect_args` (connect_timeout, statement_timeout, lock_timeout, keepalives, tcp_user_timeout), pool timeout |
| WR-03 SAFE_MODE exit cleared flag before journaling | Fixed | `safe_mode.py:352-360` journals `SAFE_MODE_EXIT` first, then clears the flag |
| WR-04 async `make_engine` echoed the URL | Fixed | `models.py:912-937` message names only the scheme via `_scheme_class` |

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|--------------|-------------|--------|----------|
| DOMN-01 | 17-01, 02, 04, 05, 07, 08, 09, 10, 13, 15 | Seven entities persisted, GLOSSARY enums, no nullable-state inference | SATISFIED | Stores for all seven entities, enum CHECKs, explicit status columns |
| APRV-02 | 17-01, 02, 04, 05, 09, 11, 14, 15 | Approval bound, one-time token, idempotent across replays | SATISFIED | Unique token hash, one decided per plan, durable consumption, replay tests across restart and after expiry |
| EXEC-03 | 17-01, 02, 11, 12, 14, 15 | Deterministic ids prevent duplicate entries across retries/restarts/replays | SATISFIED | SC3 + SC4 |
| EXEC-04 | 17-06, 13, 15 | Constraint snapshot (incl. MARKET_LOT_SIZE, PERCENT_PRICE, working type, margin, leverage, equity) persisted per plan and revalidated when stale | SATISFIED (as scoped) | Snapshot table, hash-verified reads, age/UNKNOWN validity predicate. Live margin/leverage/equity values are UNKNOWN sentinels until Phases 21-22 by D-19, so a live placement is invalid until then |
| DOMN-04 | 17-02, 03, 10, 15 | Transitions validated against GLOSSARY state machines; illegal ones rejected | SATISFIED (tables await owner confirmation) | `assert_transition` in repositories + DB triggers; human_verification item 1 |

All five IDs from the ROADMAP and from the PLAN frontmatter (15 plans) are accounted for in REQUIREMENTS.md. Observation: the traceability table maps DOMN-01 to Phase 3 and APRV-02 / EXEC-03 to Phase 8 (all marked Complete) and does not list Phase 17 for them, although the ROADMAP re-claims them for Phase 17 hardening. This is a bookkeeping inconsistency only (no requirement is orphaned); the orchestrator may want to add "(hardened Phase 17)" to the three rows.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | | TBD/FIXME/XXX/TODO/HACK scan over `src/persistence`, `src/domain/transitions.py`, `src/execution`, `src/reconcile`, the 0004 migration, `tests/pg_support.py`, `tests/support` | none | clean |

Advisory items already recorded by the code review (Info, intentionally not fixed): IN-03 (consume UPDATE does not also bind the approval row to plan and hash; the intent row and manager checks already do), IN-04 (`uq_approvals_one_decided_per_plan` also counts an EXPIRED sibling as "decided"). Neither breaks a must-have. D051(h) lists known gaps owned by later phases (no startup rehydrate wiring, restart does not place a missing stop loss, owner can disable append-only triggers).

### Human Verification Required

1. **Confirm the DOMN-04 transition tables.** Test: review `src/domain/transitions.py` / GLOSSARY section 11. Expected: accepted or amended (all three places together). Why human: auto-mode default awaiting owner confirmation.
2. **Observe the first remote CI run of the PG battery.** Expected: tests execute with no skips and pass. Why human: only run locally so far.
3. **Re-verify Binance clientOrderId and Query Order retention facts against the live docs before Phase 19/20.** Why human: MEDIUM-confidence archive sources; fake not validated against a live account.
4. **Accept the CR-01 swallow-the-audit-write policy.** Why human: safety-policy trade-off flagged "requires human verification" by the fixer.

### Gaps Summary

No gaps. Every success criterion is backed by code I read and tests I ran (about 500 PostgreSQL-backed tests under `TRADING_CI_STRICT=1`, no skips), every locked decision D-01..D-27 is honored or deviates only in the documented ways (C1, C2, C4, C7, C8, view-vs-query), and CR-01 and WR-01..WR-04 are fixed in the code. The status is `human_needed` solely because of the four items above.

---

_Verified: 2026-10-02_
_Verifier: Claude (gsd-verifier)_
