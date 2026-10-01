# Phase 17: Operational Persistence Layer - Context

**Gathered:** 2026-10-01
**Status:** Ready for planning
**Mode:** --auto (recommended defaults chosen; the user may override any D-number before planning)

<domain>
## Phase Boundary

Operational state lives durably in PostgreSQL with integrity constraints, so a replayed Telegram callback or a process restart can never create a second entry order. The phase delivers: PostgreSQL implementations of the journal, approval and execution-state stores (the existing `*_to_row` / `*_from_row` mappers gain production callers); a schema-hardening migration (unique constraints, FKs, CHECKs, column widths, UTC session, ORM/migration index parity); durable approval consumption; write-ahead execution intent written before `place_entry` and between entry and SL; a persisted per-plan exchange constraint snapshot (EXEC-04); a state-transition guard (DOMN-04); and a test that proves exactly one entry across double-call and restart against a fake that models Binance's open-orders-only clientOrderId uniqueness. PG and migration tests run against a disposable `_test` database in CI.

Requirements: DOMN-01, APRV-02, EXEC-03, EXEC-04, DOMN-04. Audit refs: F-202, F-404, F-403, F-406, F-411, F-412, F-410, F-126, F-951, F-703, F-603, F-606.

Out of scope (belongs to other phases): the user-data stream and error-code mapping (18), symbol/side/qty binding and live-price check (19), reconcile logic, SAFE_MODE exit rules and persisted SAFE_MODE/enablement state wiring beyond giving them a table (20), equity and daily loss (21), margin/leverage (22), Telegram UX (23), the runnable live process that calls these stores (24). This phase adds the stores and the guarantees; it does not wire a live process.

</domain>

<decisions>
## Implementation Decisions

### Store architecture
- **D-01:** The stores are synchronous SQLAlchemy 2.0 Core/ORM repositories over `postgresql+psycopg://`, one module per store under a new `src/persistence/` package (journal, approvals, execution_state, plus a shared engine/session factory). Sync, not async: the existing Protocol surfaces (`JournalLike.record`, `LookupByTokenHash`, `SaveApproval`) are synchronous, and F-202 is about missing implementations, not about concurrency. The async layer can wrap them in `asyncio.to_thread` at the Phase 24 composition point. — **Reversibility:** costly — every Phase 18-24 caller binds to these signatures; moving to async later touches all call sites.
- **D-02:** The domain model stays the authority; ORM rows are never passed into strategy/execution code. Repositories accept and return domain objects through the existing mappers (`src/db/mappers.py`), and the Protocol surfaces in `src/approval/replay.py`, `src/execution/enablement.py`, `src/reconcile/safe_mode.py`, `src/reconcile/sweeper.py` are satisfied structurally. No new Protocol is invented where one exists. The mappers are fixed in place, not duplicated.
- **D-03:** Transactions are explicit and owned by the caller via a unit-of-work context manager (`with store.transaction():`). Every multi-row change that must be atomic (approval decision + short-id mapping, approval consume + execution-intent insert, order row + journal event) commits in one transaction. No autocommit-per-call.
- **D-04:** Connection settings: engine factory pins the session `TimeZone` to UTC on every connection (`options=-c timezone=UTC` or a connect event), uses `pool_pre_ping=True`, and fails closed (raises, never degrades to in-memory state) when the database is unreachable. A store call that cannot reach PostgreSQL returns an error that callers translate to NO_TRADE/SAFE_MODE, never to a retry loop on the order path. (F-406)

### Schema integrity (Alembic migration `0004`)
- **D-05:** One new migration `0004_persistence_integrity` (revision chain after `0003_callback_mapping`), authored by hand, applied by `deploy/migrate.sh` and by the CI test. Never `create_all` in production paths. All 0001-0003 content stays untouched.
- **D-06:** Unique constraints: `approvals.approval_token_hash` (unique); at most one *decided* approval per `trade_plan_id` (partial unique index `WHERE status <> 'PENDING'`, so a PENDING row can be decided but a second decision cannot land); `orders.client_order_id` (unique where not null); `orders.algo_client_id` (unique where not null); `fills (order_id, exchange_trade_id)` stays. (F-404)
- **D-07:** Foreign keys with `ON DELETE RESTRICT`: `trade_plans.signal_id`, `approvals.trade_plan_id`, `approvals.signal_id`, `orders.trade_plan_id`, `orders.position_id`, `orders.parent_order_id`, `fills.order_id`, and the journal reference columns. `short_id_mapping` keeps no FK to `trade_plans` (0003 documents that it must survive plan supersede). Nothing is ever cascade-deleted from an audit table.
- **D-08:** CHECK constraints: every status/enum-valued column is constrained to the GLOSSARY enum values generated from the Python enums (single source: `src/domain/enums.py`, so a new enum value fails a parity test rather than a production insert); quantities and prices `> 0`; `filled_quantity >= 0`; timestamps for "transition never happened" stay nullable per the 0001 convention (D-11 there).
- **D-09:** Widths: widen `positions.status` and `symbol_metadata.contract_type` to fit the longest real enum value with headroom, and add a test that inserts every enum member into every enum-typed column in PostgreSQL. A VARCHAR width that cannot hold an enum value is a test failure, not a runtime surprise. (F-403)
- **D-10:** Journal is append-only: a trigger (or `REVOKE UPDATE, DELETE` for the application role plus a trigger as belt and braces) rejects UPDATE/DELETE on `journal_events`. Journal ids are made deterministic and collision-free: `journal_event_id` is derived from (correlation_id, event_type, entity_id, a per-correlation monotonic sequence), not from (name, millisecond) and never `uuid4` for callback outcomes, so replay writes the same id and the PK makes it idempotent. Fix the SAFE_MODE/sweeper/drill/callback-outcome id builders (`src/reconcile/safe_mode.py:327` and siblings). (F-412)
- **D-11:** ORM/migration parity: declare every migration index on the ORM models (the 14 missing ones, including the unique rebinding guard on `short_id_mapping`), and replace the column-name-only parity test with one that diffs full Alembic autogenerate output (`compare_metadata`) against a database built by running the migrations. The test fails on any drift in indexes, constraints, types or widths. (F-411)
- **D-12:** Persisted plan values: Decimal prices/quantities that feed `plan_hash` are quantized to the NUMERIC(38,18) scale *before* hashing, so the hash is reproducible from the stored row (round-trip test: plan -> row -> plan -> same `plan_hash`). If the planner currently hashes unquantized precision-28 values, the canonicalization is fixed in the domain/planner and the change is recorded as a deliberate hash regeneration in DECISIONS (same discipline as D047/D048). (F-410) — **Reversibility:** one-way — `plan_hash` is bound into approvals and fixtures; changing the canonical form later invalidates stored hashes.

### Durable approval consumption and execution intent
- **D-13:** New table `execution_intents`, one row per (approval_id, role) with role in {ENTRY, SL, TP1, TP2}, primary key on `(approval_id, role)` plus a unique `client_order_id`. Columns: deterministic `client_order_id`/`algo_client_id` (from `src/execution/order_ids.py`), `intent_status` in {INTENDED, SENT, ACKED, REJECTED, UNKNOWN}, `plan_hash`, quantity/price as intended, timestamps. "Consuming" an approval means inserting the ENTRY intent row in the same transaction that marks the approval consumed; a second attempt hits the primary key and returns the stored result. This is what makes EXEC-03 true; the exchange's clientOrderId dedup is explicitly NOT relied on (08 D-04 premise was wrong: Binance only rejects a duplicate while the earlier order is still open). (F-126, F-951) — **Reversibility:** one-way — Phases 18-24 and the reconcile logic key off these rows.
- **D-14:** Write-ahead order of operations in `execute_approved_plan`: (1) commit approval-consumed + ENTRY intent INTENDED, (2) call `place_entry`, (3) commit SENT/ACKED/REJECTED from the response, (4) before placing the SL commit the SL intent INTENDED, (5) place SL, (6) commit its outcome. A crash between any two steps leaves a durable row that restart recovery reads. An intent left INTENDED or SENT after a restart is UNKNOWN: it is never re-sent blindly; it is resolved by querying the exchange by deterministic client id (open and recent orders) and recorded, and when it cannot be resolved the system fails closed (no new entries; the SAFE_MODE trigger itself is Phase 20's hardening, this phase exposes the "unresolved intents" query and raises the existing `enter_safe_mode` path). (F-703)
- **D-15:** Replay and double-call semantics: the second call to `execute_approved_plan` with the same approval returns the stored `ExecutionOutcome` for that approval (idempotent), with zero adapter calls. A call after a restart does the same by reading PostgreSQL. A replayed APPROVED callback therefore can never reach `place_entry` twice. `ExecutionOutcome` is persistable (a serializable result stored on the ENTRY intent row).
- **D-16:** The approval row gains explicit consumption state rather than inferring it: `consumed_at_utc` (nullable, "transition never happened" convention) set only by the consume transaction. `check_binding_full` and replay treat a consumed approval as "already executed, return stored result", not as "approved, execute".
- **D-17:** The store keeps the existing in-process per-token lock in `src/approval/replay.py` only as a latency optimization. Correctness comes from the database constraint (a lost race surfaces as a unique-violation that the store catches and converts to "return existing row"), so a second process or worker cannot double-execute.

### Constraint snapshot persistence (EXEC-04)
- **D-18:** Persist the exact exchange constraint snapshot used for sizing per trade plan in a `plan_constraint_snapshots` table (one row per `trade_plan_id`, FK-linked): symbol, tick/step sizes, min notional, MARKET_LOT_SIZE and PERCENT_PRICE filters, working type, margin type, leverage, equity used, and the exchangeInfo capture timestamp, stored as a canonical JSON column plus its sha256. The hash is included in the plan's evidence, not in `plan_hash` (so the existing approval binding contract does not move). Staleness is revalidated at placement time against a configured max age; a stale snapshot is NO_TRADE (re-sizing happens in Phase 19's pre-placement checks, this phase stores and exposes the age check). Values are Decimal text, never float.
- **D-19:** Live margin type, leverage and equity are placeholders until Phases 21-22 supply them: the columns exist and are NOT NULL with an explicit `UNKNOWN`/unset sentinel that the staleness check treats as invalid for live placement. No invented defaults.

### State-transition validation (DOMN-04)
- **D-20:** A pure `src/domain/transitions.py` holds the legal-transition tables for Signal, TradePlan, Order, Position, copied from the GLOSSARY state machines and unit-tested against the GLOSSARY text. Repositories call it inside the same transaction as the write and raise a typed `IllegalTransition` that no caller can swallow into a silent save. A parity test fails if an enum gains a value without a transition entry. The database additionally enforces the terminal-state rule where cheap (a CHECK or trigger on terminal statuses never reverting).
- **D-21:** Entity creation uses the existing seven-entity model; no nullable-column state inference (DOMN-01). Any state that is currently inferred from a nullable column in the new tables (consumed, intent status) uses an explicit status column instead.

### Other durable state tables
- **D-22:** Provide tables and repositories (not wiring) for state that must survive restart: SAFE_MODE state, enablement state, kill-gate state. One generic append-only `system_state_events` table plus a "latest per key" view/query, written through the journal so the audit trail and current state cannot diverge. Rehydration functions exist and are tested (restart test: write state, build a fresh store on a fresh connection, read it back). Phase 20 owns the SAFE_MODE exit rules and the live wiring; this phase only guarantees that persisting and rehydrating is possible and tested. (F-606 restart-rehydrate gap)

### Test strategy and CI
- **D-23:** Tests use a disposable database. The PG test fixture creates a uniquely named database whose name must end with `_test`, runs Alembic `upgrade head` (never `create_all`), and drops it afterward; it refuses to run against any database whose name does not end with `_test`. `TEST_DATABASE_URL` points at the server, the fixture derives the per-session database. Locally the module skips with an explicit, loud reason when no URL is set; in CI the skip is a hard failure (the CI job sets an env flag that turns a PG skip into an error), so the PG tests cannot silently stop running. (F-606)
- **D-24:** The existing `ci.yml` PostgreSQL service container (`postgres:17.11-bookworm`, pinned by digest in Phase 13.1) is reused; this phase adds no new service. The migration test also runs `upgrade head`, `downgrade base`, `upgrade head` once to prove reversibility, and a data-bearing upgrade from 0003 to 0004 to prove existing rows survive.
- **D-25:** The exactly-one-entry test (SC4) uses a `FakeExecutionAdapter` that models Binance's real semantics: `newClientOrderId` is unique only among *open* orders (a FILLED or CANCELED order frees its id; a duplicate while open returns the -4116-style rejection). The test: (a) calls `execute_approved_plan` twice with the same approval, (b) simulates a restart by building a new store and manager against the same database, (c) fills/cancels the first entry between calls so the fake would accept the same id again, and asserts exactly one `place_entry` and one entry intent row in every case. A negative control proves the test fails against the old no-persistence behavior. (F-603)
- **D-26:** Additional proofs: concurrent consume (two threads, one winner), crash-injection between each write-ahead step (restart leaves a readable INTENDED/SENT row and no second order), approval double-decision rejected by the DB (not just by Python), and a round-trip property test for every mapper pair.

### Documentation and decision record
- **D-27:** Same-change doc updates (D031 authority rule): `docs/data/DATA_MODEL.md` (new tables, constraints, widths, UTC, append-only journal), `docs/trading/EXECUTION_SPEC.md` (write-ahead intent, consumption, "exchange dedup is not relied on"; this fixes the wrong 08 D-04 premise recorded in audit F-951), `docs/testing/TESTING_STRATEGY.md` (disposable `_test` DB, CI hard-fail on skip), `docs/operations/RUNBOOK.md` (migration `0004`, restore expectations), `docs/DECISIONS.md` (new row D051 for this phase; the next free number after D050 must be verified at write time), and a `docs/DOC_STATUS.md` change-log line. If the planner finds D051 already taken, use the next free number and record it.

### Claude's Discretion
- Exact module/file names inside `src/persistence/`, and whether repositories use ORM sessions or SQLAlchemy Core for hot paths, provided D-01 to D-04 hold.
- Exact enum-to-CHECK generation mechanism and the append-only mechanism (trigger vs revoke) provided D-08 and D-10 hold.
- Concrete widths (D-09), the staleness max-age number (D-18, taken from params, not hard-coded), and the exact journal id derivation (D-10) provided they are deterministic and collision-free.
- Plan split and wave ordering (suggested: migration + engine/UTC first as the tracer, then approval/intent stores and the exactly-one-entry test, then constraint snapshots and transitions, then docs/CI hardening).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Authority and decisions
- `AGENTS.md` — Determinism, fail-closed, approval-safety, quantization and tech-stack constraints (Decimal/tick arithmetic, SQLAlchemy 2.0.x, psycopg 3, Alembic, never `create_all` in production).
- `docs/DECISIONS.md` — D031 (source-of-authority precedence), D034 (SAFE_MODE blocks entries only), D040/D041 (release path, two-step confirm), D042 (single-VPS topology), D047/D048 (hash canonicalization and deliberate regeneration discipline), D050 (CI/deploy); new row for this phase.
- `docs/DOC_STATUS.md` — change-log and facts-verified conventions.

### Phase and requirements
- `.planning/ROADMAP.md` §Phase 17 — goal, success criteria 1-5, audit refs.
- `.planning/REQUIREMENTS.md` — DOMN-01, APRV-02, EXEC-03, EXEC-04, DOMN-04.
- `.planning/phases/08-approval-reconciliation-hardening/08-CONTEXT.md` — D-04 ("exchange dedups clientOrderId") is the wrong premise this phase corrects; read D-02 (short-id mapping and atomic write) for the transaction contract.

### Audit evidence
- `.planning/audits/2026-09-29-deep-audit/DEEP_AUDIT_REPORT.md` §6.9 (F-126 full scenario and fix), and the F-202, F-403, F-404, F-406, F-410, F-411, F-412, F-606, F-703, F-951, F-603 rows.
- `.planning/audits/2026-09-29-deep-audit/INVARIANTS.md` — INV-087 (idempotency, VIOLATED) and the data invariants.

### Canonical docs to update
- `docs/data/DATA_MODEL.md` — entity and table definitions, constraints.
- `docs/trading/EXECUTION_SPEC.md` — execution flow, idempotency.
- `docs/testing/TESTING_STRATEGY.md` — PG/migration test policy.
- `docs/operations/RUNBOOK.md` and `docs/operations/SECURITY_AND_OPERATIONS.md` — migration, backup/restore of the operational DB.
- `docs/GLOSSARY.md` — state machines and enum values for transitions (D-20) and CHECKs (D-08).
- `docs/integration/BINANCE.md` — clientOrderId uniqueness semantics (open orders only); re-verify against current official docs before encoding the fake (AGENTS exchange-authority rule).

### Existing code that anchors the work
- `src/db/models.py`, `src/db/mappers.py`, `src/db/alembic/versions/0001_baseline.py`, `0002_domain_registry.py`, `0003_callback_mapping.py`, `src/db/alembic/env.py`.
- `src/execution/manager.py` (`execute_approved_plan`, `_place_entry_no_blind_retry`), `src/execution/order_ids.py`, `src/execution/enablement.py`.
- `src/approval/replay.py`, `src/approval/binding.py`, `src/adapters/telegram_callbacks.py`.
- `src/reconcile/safe_mode.py`, `src/reconcile/sweeper.py`.
- `tests/test_domain_mappers_pg.py`, `tests/conftest.py`, `.github/workflows/ci.yml`, `deploy/migrate.sh`, `docker-compose.yml`.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/db/mappers.py`: complete `*_to_row`/`*_from_row` pairs for Signal, TradePlan, Approval, Order, Fill, Position, JournalEvent, ShortIdMapping; currently with zero production callers (F-202). The repositories are their callers.
- `src/db/models.py` (ORM mirror, `Numeric(38,18)`, UTC `DateTime(timezone=True)`) and three Alembic revisions; migration conventions (hash/deterministic PKs, no auto-increment, nullable only for never-happened transitions) carry forward.
- `src/execution/order_ids.py`: `derive_client_order_id(plan_hash, role)` and `derive_algo_client_id`, already deterministic; they become the keys of `execution_intents`.
- `src/approval/replay.py` Protocol-style callables (`LookupByTokenHash`, `SaveApproval`) and `JournalLike.record` in enablement, safe_mode and sweeper: the store implementations plug in with no signature change.
- `deploy/migrate.sh`, `ci.yml` PostgreSQL 17.11 service and `TEST_DATABASE_URL`, `docker-compose.yml` PostgreSQL with named volume: the infrastructure already exists from Phase 13.1.
- `tests/test_domain_mappers_pg.py`: starting point for the PG fixture, to be rebuilt on `alembic upgrade head`.

### Established Patterns
- Domain objects are the authority; ORM rows stay at the adapter edge; strict mypy on domain/execution paths; Decimal for all exchange-sensitive values.
- Fail closed: uncertain state is NO_TRADE or SAFE_MODE, never a retry loop on order paths; execution functions take injected `now_utc` and never read the wall clock.
- Deliberate hash/fixture regeneration is recorded as a DECISIONS inventory row, never done silently (D047/D048).
- Logic in Python modules, shell scripts thin; every canonical-doc change lands in the same commit as the code (D031).

### Integration Points
- `execute_approved_plan(journal=..., ...)` and `resolve_callback(lookup, save, ...)` gain the PostgreSQL implementations; their public signatures should change as little as possible (the intent/consume call is added inside the manager through an injected store, required, no `None` default, per 09-REVIEW CR-07).
- `analytics_store` already reads the operational tables that nothing wrote; the new writers must keep its column expectations valid (check `src/adapters/analytics_store.py` before the migration).
- Phase 18 (user-data stream) will write fills/orders through these repositories; Phase 19 binds symbol/side/qty using the stored plan and snapshot; Phase 20 reconciles against `execution_intents`; Phase 24 composes everything. Keep repository APIs narrow and documented for those consumers.

</code_context>

<specifics>
## Specific Ideas

- The central proof is the "fake that models Binance's real clientOrderId rule" (open-orders-only uniqueness): the old fake accepted unlimited resubmits, which is why the 08 tests could not see F-126.
- Prefer a second failure line of defense in the database over trusting Python: the duplicate must be impossible at the constraint level even if a caller bug skips the check.
- Consumption is recorded by an explicit row/state, never inferred from a null column.

</specifics>

<deferred>
## Deferred Ideas

- Async repository variants and a connection pool tuned with `psycopg_pool` (decide at Phase 24 composition when the real concurrency shape is known).
- SAFE_MODE exit rules, auto SL re-place and live rehydration wiring: Phase 20.
- Live equity, margin type and leverage values for the constraint snapshot: Phases 21-22 (this phase stores the columns and the sentinel only).
- Symbol/side/quantity binding of the executed order to the approved plan and the stale-price recheck: Phase 19.
- Row-level security / separate DB roles for the app vs migrations beyond what the append-only journal needs: revisit at the go-live readiness gate (Phase 26).
- Retention/partitioning of `journal_events` at scale: not needed at V1 volume.

### Reviewed Todos (not folded)
None matched this phase.

</deferred>

## Post-research corrections (Phase 17 planning)

Recorded by plan 17-15 after research and execution; the decisions above are not rewritten. The full list of resolutions (C1-C20) is in `17-RESEARCH.md` and in DECISIONS D051.

- **C1 (D-05, D-24):** migration `0004_persistence_integrity` is applied by the compose `db-upgrade` service (`alembic upgrade head`) and by the restore path in `src/ops/backup.py` (`alembic upgrade head` after `pg_restore`), not by `deploy/migrate.sh`, which is the provider-to-provider cutover script and is untouched. Read "applied by `deploy/migrate.sh`" in D-05 and D-24 accordingly.
- **C2 (D-13):** the `role` values are the real `OrderRole` values `ENTRY`, `STOP_LOSS`, `TAKE_PROFIT_1`, `TAKE_PROFIT_2`, not `SL`, `TP1`, `TP2`.
- **C8 (D-16, D-21):** consumption is an explicit `approvals.consumption_status` (`UNCONSUMED` / `CONSUMED`) with `consumed_at_utc` as the nullable "never happened" timestamp, tied together by a CHECK; the ENTRY intent row is the authority. This satisfies D-16 and D-21 together.
- **D-22:** "latest per key" is a query (`PgSystemStateStore.latest`), not a view.

---

*Phase: 17-operational-persistence-layer*
*Context gathered: 2026-10-01*
