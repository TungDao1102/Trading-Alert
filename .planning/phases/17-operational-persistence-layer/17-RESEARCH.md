# Phase 17: Operational Persistence Layer - Research

**Researched:** 2026-10-01
**Domain:** PostgreSQL 17 operational persistence (SQLAlchemy 2.0 sync repositories, psycopg 3, Alembic), write-ahead execution intent, schema integrity, disposable-DB test infrastructure
**Confidence:** HIGH on codebase facts and library behavior (read this session); MEDIUM on PG-runtime behaviors that could not be executed locally (Docker daemon is down on this machine, see Environment Availability); LOW only where tagged `[ASSUMED]`

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Store architecture**
- **D-01:** The stores are synchronous SQLAlchemy 2.0 Core/ORM repositories over `postgresql+psycopg://`, one module per store under a new `src/persistence/` package (journal, approvals, execution_state, plus a shared engine/session factory). Sync, not async: the existing Protocol surfaces (`JournalLike.record`, `LookupByTokenHash`, `SaveApproval`) are synchronous, and F-202 is about missing implementations, not about concurrency. The async layer can wrap them in `asyncio.to_thread` at the Phase 24 composition point. — **Reversibility:** costly — every Phase 18-24 caller binds to these signatures; moving to async later touches all call sites.
- **D-02:** The domain model stays the authority; ORM rows are never passed into strategy/execution code. Repositories accept and return domain objects through the existing mappers (`src/db/mappers.py`), and the Protocol surfaces in `src/approval/replay.py`, `src/execution/enablement.py`, `src/reconcile/safe_mode.py`, `src/reconcile/sweeper.py` are satisfied structurally. No new Protocol is invented where one exists. The mappers are fixed in place, not duplicated.
- **D-03:** Transactions are explicit and owned by the caller via a unit-of-work context manager (`with store.transaction():`). Every multi-row change that must be atomic (approval decision + short-id mapping, approval consume + execution-intent insert, order row + journal event) commits in one transaction. No autocommit-per-call.
- **D-04:** Connection settings: engine factory pins the session `TimeZone` to UTC on every connection (`options=-c timezone=UTC` or a connect event), uses `pool_pre_ping=True`, and fails closed (raises, never degrades to in-memory state) when the database is unreachable. A store call that cannot reach PostgreSQL returns an error that callers translate to NO_TRADE/SAFE_MODE, never to a retry loop on the order path. (F-406)

**Schema integrity (Alembic migration `0004`)**
- **D-05:** One new migration `0004_persistence_integrity` (revision chain after `0003_callback_mapping`), authored by hand, applied by `deploy/migrate.sh` and by the CI test. Never `create_all` in production paths. All 0001-0003 content stays untouched.
- **D-06:** Unique constraints: `approvals.approval_token_hash` (unique); at most one *decided* approval per `trade_plan_id` (partial unique index `WHERE status <> 'PENDING'`, so a PENDING row can be decided but a second decision cannot land); `orders.client_order_id` (unique where not null); `orders.algo_client_id` (unique where not null); `fills (order_id, exchange_trade_id)` stays. (F-404)
- **D-07:** Foreign keys with `ON DELETE RESTRICT`: `trade_plans.signal_id`, `approvals.trade_plan_id`, `approvals.signal_id`, `orders.trade_plan_id`, `orders.position_id`, `orders.parent_order_id`, `fills.order_id`, and the journal reference columns. `short_id_mapping` keeps no FK to `trade_plans` (0003 documents that it must survive plan supersede). Nothing is ever cascade-deleted from an audit table.
- **D-08:** CHECK constraints: every status/enum-valued column is constrained to the GLOSSARY enum values generated from the Python enums (single source: `src/domain/enums.py`, so a new enum value fails a parity test rather than a production insert); quantities and prices `> 0`; `filled_quantity >= 0`; timestamps for "transition never happened" stay nullable per the 0001 convention (D-11 there).
- **D-09:** Widths: widen `positions.status` and `symbol_metadata.contract_type` to fit the longest real enum value with headroom, and add a test that inserts every enum member into every enum-typed column in PostgreSQL. A VARCHAR width that cannot hold an enum value is a test failure, not a runtime surprise. (F-403)
- **D-10:** Journal is append-only: a trigger (or `REVOKE UPDATE, DELETE` for the application role plus a trigger as belt and braces) rejects UPDATE/DELETE on `journal_events`. Journal ids are made deterministic and collision-free: `journal_event_id` is derived from (correlation_id, event_type, entity_id, a per-correlation monotonic sequence), not from (name, millisecond) and never `uuid4` for callback outcomes, so replay writes the same id and the PK makes it idempotent. Fix the SAFE_MODE/sweeper/drill/callback-outcome id builders (`src/reconcile/safe_mode.py:327` and siblings). (F-412)
- **D-11:** ORM/migration parity: declare every migration index on the ORM models (the 14 missing ones, including the unique rebinding guard on `short_id_mapping`), and replace the column-name-only parity test with one that diffs full Alembic autogenerate output (`compare_metadata`) against a database built by running the migrations. The test fails on any drift in indexes, constraints, types or widths. (F-411)
- **D-12:** Persisted plan values: Decimal prices/quantities that feed `plan_hash` are quantized to the NUMERIC(38,18) scale *before* hashing, so the hash is reproducible from the stored row (round-trip test: plan -> row -> plan -> same `plan_hash`). If the planner currently hashes unquantized precision-28 values, the canonicalization is fixed in the domain/planner and the change is recorded as a deliberate hash regeneration in DECISIONS (same discipline as D047/D048). (F-410) — **Reversibility:** one-way — `plan_hash` is bound into approvals and fixtures; changing the canonical form later invalidates stored hashes.

**Durable approval consumption and execution intent**
- **D-13:** New table `execution_intents`, one row per (approval_id, role) with role in {ENTRY, SL, TP1, TP2}, primary key on `(approval_id, role)` plus a unique `client_order_id`. Columns: deterministic `client_order_id`/`algo_client_id` (from `src/execution/order_ids.py`), `intent_status` in {INTENDED, SENT, ACKED, REJECTED, UNKNOWN}, `plan_hash`, quantity/price as intended, timestamps. "Consuming" an approval means inserting the ENTRY intent row in the same transaction that marks the approval consumed; a second attempt hits the primary key and returns the stored result. This is what makes EXEC-03 true; the exchange's clientOrderId dedup is explicitly NOT relied on (08 D-04 premise was wrong: Binance only rejects a duplicate while the earlier order is still open). (F-126, F-951) — **Reversibility:** one-way — Phases 18-24 and the reconcile logic key off these rows.
- **D-14:** Write-ahead order of operations in `execute_approved_plan`: (1) commit approval-consumed + ENTRY intent INTENDED, (2) call `place_entry`, (3) commit SENT/ACKED/REJECTED from the response, (4) before placing the SL commit the SL intent INTENDED, (5) place SL, (6) commit its outcome. A crash between any two steps leaves a durable row that restart recovery reads. An intent left INTENDED or SENT after a restart is UNKNOWN: it is never re-sent blindly; it is resolved by querying the exchange by deterministic client id (open and recent orders) and recorded, and when it cannot be resolved the system fails closed (no new entries; the SAFE_MODE trigger itself is Phase 20's hardening, this phase exposes the "unresolved intents" query and raises the existing `enter_safe_mode` path). (F-703)
- **D-15:** Replay and double-call semantics: the second call to `execute_approved_plan` with the same approval returns the stored `ExecutionOutcome` for that approval (idempotent), with zero adapter calls. A call after a restart does the same by reading PostgreSQL. A replayed APPROVED callback therefore can never reach `place_entry` twice. `ExecutionOutcome` is persistable (a serializable result stored on the ENTRY intent row).
- **D-16:** The approval row gains explicit consumption state rather than inferring it: `consumed_at_utc` (nullable, "transition never happened" convention) set only by the consume transaction. `check_binding_full` and replay treat a consumed approval as "already executed, return stored result", not as "approved, execute".
- **D-17:** The store keeps the existing in-process per-token lock in `src/approval/replay.py` only as a latency optimization. Correctness comes from the database constraint (a lost race surfaces as a unique-violation that the store catches and converts to "return existing row"), so a second process or worker cannot double-execute.

**Constraint snapshot persistence (EXEC-04)**
- **D-18:** Persist the exact exchange constraint snapshot used for sizing per trade plan in a `plan_constraint_snapshots` table (one row per `trade_plan_id`, FK-linked): symbol, tick/step sizes, min notional, MARKET_LOT_SIZE and PERCENT_PRICE filters, working type, margin type, leverage, equity used, and the exchangeInfo capture timestamp, stored as a canonical JSON column plus its sha256. The hash is included in the plan's evidence, not in `plan_hash` (so the existing approval binding contract does not move). Staleness is revalidated at placement time against a configured max age; a stale snapshot is NO_TRADE (re-sizing happens in Phase 19's pre-placement checks, this phase stores and exposes the age check). Values are Decimal text, never float.
- **D-19:** Live margin type, leverage and equity are placeholders until Phases 21-22 supply them: the columns exist and are NOT NULL with an explicit `UNKNOWN`/unset sentinel that the staleness check treats as invalid for live placement. No invented defaults.

**State-transition validation (DOMN-04)**
- **D-20:** A pure `src/domain/transitions.py` holds the legal-transition tables for Signal, TradePlan, Order, Position, copied from the GLOSSARY state machines and unit-tested against the GLOSSARY text. Repositories call it inside the same transaction as the write and raise a typed `IllegalTransition` that no caller can swallow into a silent save. A parity test fails if an enum gains a value without a transition entry. The database additionally enforces the terminal-state rule where cheap (a CHECK or trigger on terminal statuses never reverting).
- **D-21:** Entity creation uses the existing seven-entity model; no nullable-column state inference (DOMN-01). Any state that is currently inferred from a nullable column in the new tables (consumed, intent status) uses an explicit status column instead.

**Other durable state tables**
- **D-22:** Provide tables and repositories (not wiring) for state that must survive restart: SAFE_MODE state, enablement state, kill-gate state. One generic append-only `system_state_events` table plus a "latest per key" view/query, written through the journal so the audit trail and current state cannot diverge. Rehydration functions exist and are tested (restart test: write state, build a fresh store on a fresh connection, read it back). Phase 20 owns the SAFE_MODE exit rules and the live wiring; this phase only guarantees that persisting and rehydrating is possible and tested. (F-606 restart-rehydrate gap)

**Test strategy and CI**
- **D-23:** Tests use a disposable database. The PG test fixture creates a uniquely named database whose name must end with `_test`, runs Alembic `upgrade head` (never `create_all`), and drops it afterward; it refuses to run against any database whose name does not end with `_test`. `TEST_DATABASE_URL` points at the server, the fixture derives the per-session database. Locally the module skips with an explicit, loud reason when no URL is set; in CI the skip is a hard failure (the CI job sets an env flag that turns a PG skip into an error), so the PG tests cannot silently stop running. (F-606)
- **D-24:** The existing `ci.yml` PostgreSQL service container (`postgres:17.11-bookworm`, pinned by digest in Phase 13.1) is reused; this phase adds no new service. The migration test also runs `upgrade head`, `downgrade base`, `upgrade head` once to prove reversibility, and a data-bearing upgrade from 0003 to 0004 to prove existing rows survive.
- **D-25:** The exactly-one-entry test (SC4) uses a `FakeExecutionAdapter` that models Binance's real semantics: `newClientOrderId` is unique only among *open* orders (a FILLED or CANCELED order frees its id; a duplicate while open returns the -4116-style rejection). The test: (a) calls `execute_approved_plan` twice with the same approval, (b) simulates a restart by building a new store and manager against the same database, (c) fills/cancels the first entry between calls so the fake would accept the same id again, and asserts exactly one `place_entry` and one entry intent row in every case. A negative control proves the test fails against the old no-persistence behavior. (F-603)
- **D-26:** Additional proofs: concurrent consume (two threads, one winner), crash-injection between each write-ahead step (restart leaves a readable INTENDED/SENT row and no second order), approval double-decision rejected by the DB (not just by Python), and a round-trip property test for every mapper pair.

**Documentation and decision record**
- **D-27:** Same-change doc updates (D031 authority rule): `docs/data/DATA_MODEL.md` (new tables, constraints, widths, UTC, append-only journal), `docs/trading/EXECUTION_SPEC.md` (write-ahead intent, consumption, "exchange dedup is not relied on"; this fixes the wrong 08 D-04 premise recorded in audit F-951), `docs/testing/TESTING_STRATEGY.md` (disposable `_test` DB, CI hard-fail on skip), `docs/operations/RUNBOOK.md` (migration `0004`, restore expectations), `docs/DECISIONS.md` (new row D051 for this phase; the next free number after D050 must be verified at write time), and a `docs/DOC_STATUS.md` change-log line. If the planner finds D051 already taken, use the next free number and record it.

### Claude's Discretion
- Exact module/file names inside `src/persistence/`, and whether repositories use ORM sessions or SQLAlchemy Core for hot paths, provided D-01 to D-04 hold.
- Exact enum-to-CHECK generation mechanism and the append-only mechanism (trigger vs revoke) provided D-08 and D-10 hold.
- Concrete widths (D-09), the staleness max-age number (D-18, taken from params, not hard-coded), and the exact journal id derivation (D-10) provided they are deterministic and collision-free.
- Plan split and wave ordering (suggested: migration + engine/UTC first as the tracer, then approval/intent stores and the exactly-one-entry test, then constraint snapshots and transitions, then docs/CI hardening).

### Deferred Ideas (OUT OF SCOPE)
- Async repository variants and a connection pool tuned with `psycopg_pool` (decide at Phase 24 composition when the real concurrency shape is known).
- SAFE_MODE exit rules, auto SL re-place and live rehydration wiring: Phase 20.
- Live equity, margin type and leverage values for the constraint snapshot: Phases 21-22 (this phase stores the columns and the sentinel only).
- Symbol/side/quantity binding of the executed order to the approved plan and the stale-price recheck: Phase 19.
- Row-level security / separate DB roles for the app vs migrations beyond what the append-only journal needs: revisit at the go-live readiness gate (Phase 26).
- Retention/partitioning of `journal_events` at scale: not needed at V1 volume.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DOMN-01 | Seven separate entities persisted with GLOSSARY enums and no nullable-column state inference | Section "Stores and call-site map" (mappers get production callers via repositories), "Schema 0004 blueprint" (CHECKs, explicit consumption state, intent_status column), C8 (D-16 vs D-21 tension and resolution), "Enum width table" |
| APRV-02 | Approval bound and idempotent across at-least-once replays (this phase: durable, DB-enforced) | "Approvals store design" (token-hash unique, one-decided-per-plan partial unique index, conditional UPDATE, `ApprovalAlreadyDecided`), C15/C16 pitfalls, Pattern 3 |
| EXEC-03 | Deterministic ids prevent duplicate entry orders across retries, restarts, replays | "Write-ahead intent design" (intent PK + unique client id, insertion points in `execute_approved_plan`), Binance semantics (open-orders-only, cited), SC4 test design with stateful fake and negative control |
| EXEC-04 | Exact constraint snapshot (incl. MARKET_LOT_SIZE, PERCENT_PRICE, working type, margin type, leverage, equity) persisted per plan and revalidated when stale | "Constraint snapshot design" (adapter does not parse the two filters today: C10; reuse `constraint_snapshot_ttl_seconds`; sentinel columns) |
| DOMN-04 | Signal/TradePlan/Order/Position transitions validated; illegal transitions rejected | "Transitions" (GLOSSARY has no transition tables: C3; draft tables flagged `[ASSUMED]`; `IllegalTransition`; parity test) |
</phase_requirements>

## Project Constraints (from CLAUDE.md and AGENTS.md)

- Python 3.13 (`.python-version` = 3.13.15), uv, asyncio; SQLAlchemy `>=2.0,<2.1`, psycopg 3 (`postgresql+psycopg://`), Alembic; pytest + Ruff + strict mypy (`uv run mypy src` is a CI job); Decimal/tick arithmetic for every exchange-sensitive value, never float.
- Determinism: same inputs, same decision; execution functions take injected `now_utc` and never read the wall clock; no LLM in the decision path.
- Fail closed: uncertain state is NO_TRADE or SAFE_MODE; no retry loop on the order path; SAFE_MODE blocks entries while monitoring continues.
- Approval safety: explicit, auditable, idempotent, expiring; at-least-once Telegram callbacks replay to existing state; no auto-approve.
- Exchange authority: Binance facts re-verified against current official docs, never hard-coded from memory; record provenance in `docs/SOURCES.md`.
- Never `create_all` in production paths; Alembic migrations are the only schema authority.
- GSD workflow enforcement: file changes only through a GSD command (this research is the `/gsd-plan-phase` research step). `tdd_mode: true` and `security_enforcement: true` (ASVS level 1) in `.planning/config.json`.
- D031 authority rule: every canonical-doc change lands in the same commit as the code; docs named in D-27.
- CodeGraph (`.codegraph/` exists): executors should run `codegraph explore "<symbol>"` before Grep/Read when locating code.

## Summary

Phase 17 is mostly an internal build, and the code review shows the CONTEXT decisions are sound in direction but wrong or incomplete on about twenty concrete facts (section "CONTEXT conflicts", C1-C20). The load-bearing ones for planning: (1) `deploy/migrate.sh` is the provider-cutover script, not the Alembic runner (Alembic runs from the compose `db-upgrade` service and from `src/ops/backup.py` restore); (2) the GLOSSARY has value sets only, no transition tables, so DOMN-04 requires authoring the four state machines (a design decision that needs user confirmation, flagged `[ASSUMED]`); (3) `plan_hash` really is unreproducible from the stored row, with evidence: real planner output carries 23-27 fractional digits and `canonical_scalars` hashes `str(Decimal)`, while PostgreSQL `NUMERIC(38,18)` rounds to 18 digits and returns fixed-scale text; fixing it regenerates plan-derived fixtures (a D048-style inventory); (4) Alembic's `compare_metadata` does not compare partial-index predicates or CHECK predicates, so D-11's "any drift fails" needs two supplementary PG-level assertions plus the D-09 insert-every-enum-member test; (5) `TRADING_CI_STRICT=1` and `infra_helpers.infra_skip` already implement "skip becomes failure in CI", so no new env flag is needed; (6) the manager is `async def` while D-01 makes the stores sync, so every store call blocks the event loop (acceptable at this call volume, but must be a documented choice).

The exactly-once design that satisfies EXEC-03 is a write-ahead `execution_intents` table keyed `(approval_id, role)` with a unique deterministic client id, consumed by `INSERT ... ON CONFLICT (approval_id, role) DO NOTHING RETURNING` inside the transaction that stamps the approval. Binance's own dedup cannot be relied on: the official docs say `newClientOrderId` is "A unique id among open orders", so a FILLED/CANCELED order frees its id. The SC4 proof needs a stateful fake exchange, a restart simulation (fresh engine + stores on the same DB), crash injection with a `BaseException` subclass (the manager swallows `Exception`), a two-thread consume race, and a negative control that runs the same scenario with a non-remembering store and observes two entries.

PostgreSQL could not be run on this machine (Docker Desktop engine pipe missing), so DDL/runtime claims about PG behavior are tagged from official docs, library source or offline DDL compilation rather than executed. The plan must include a Wave 0 step that makes a PG server available before any PG-bound task is marked verified.

**Primary recommendation:** Build in this order: (W0) disposable-DB fixtures with strict skip, env.py connection seam, RED parity/enum/width tests; (W1) models + migration `0004` + enum/transition modules; (W2) `src/persistence` engine/UoW + journal and approval stores + deterministic journal ids; (W3) intents store + manager integration + stateful fake + SC4 tests; (W4) D-12 plan-hash canonicalization (own plan, fixture regeneration) + constraint snapshots + system-state events; (W5) docs, D051, CI/RUNBOOK. Use `ON CONFLICT ... RETURNING` plus SAVEPOINTs for every idempotent write, and a template-database clone per test (the append-only journal blocks TRUNCATE/DELETE cleanup).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Idempotent approval consumption, one entry per approval | Database / Storage (unique PK on `execution_intents`) | API / Backend (`execute_approved_plan`) | The constraint is the correctness line; Python lock is only a latency optimization (D-17) |
| Write-ahead execution intent ordering | API / Backend (execution manager) | Database / Storage | The manager decides when to commit each step; the DB makes each step durable |
| Schema integrity (unique, FK, CHECK, widths, append-only) | Database / Storage (migration `0004`) | API / Backend (typed error mapping) | Constraints must hold even if a caller skips the Python check |
| State-transition legality | API / Backend (pure `src/domain/transitions.py`) | Database / Storage (terminal-state CHECK/trigger where cheap) | Tables are domain logic; DB backs only the terminal rule |
| Deterministic journal ids | API / Backend (id builders) | Database / Storage (PK makes replay idempotent) | Id is a pure function of stable inputs |
| Session UTC pinning | API / Backend (engine factory) | Database / Storage (`options=-c timezone=UTC`) | psycopg returns timestamptz in session TimeZone; domain rejects non-UTC offsets |
| Plan hash reproducibility | API / Backend (planner canonicalization) | Database / Storage (NUMERIC(38,18) scale) | Hash input must equal stored value; planner must quantize before hashing |
| Constraint snapshot capture and staleness | API / Backend | Database / Storage (canonical JSON + sha256) | Age check reuses the existing placement predicate |
| Test database lifecycle | Test infrastructure (pytest fixtures) | CI (PG service container) | Disposable `_test` DB per session/test; strict skip policy |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | 2.0.54 installed; pyproject `>=2.0,<2.1` | Sync ORM/Core repositories, `pg_insert().on_conflict_do_nothing()`, `begin_nested()` savepoints | Locked stack (D-01); `[VERIFIED: .venv runtime import, 2.0.54]` |
| psycopg | 3.3.6 installed; pyproject `>=3.3,<4` (`binary,pool` extras) | Driver; `psycopg.errors.UniqueViolation.sqlstate == '23505'`, `Diagnostic.constraint_name` | Locked stack; `[VERIFIED: offline import, sqlstates 23505/23503/23514 printed]` |
| Alembic | 1.20.0 installed; pyproject `>=1.19` | Hand-written migration `0004`; `compare_metadata` parity | Locked stack; `[VERIFIED: .venv, 1.20.0]` |
| pytest + pytest-asyncio (auto mode) | pytest 9.1.1 (from pyc names), asyncio_mode = "auto" | Tests incl. async manager tests | `[VERIFIED: pyproject.toml addopts/asyncio_mode; tests/__pycache__ names]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `alembic.ext.checkconstraint_byname` | ships with Alembic >= 1.19.2 (opt-in) | Detect presence/absence of NAMED CHECK constraints in `compare_metadata` | Parity test; `[VERIFIED: alembic/runtime/plugins.py `_legacy_plugin_names` comment "renamed in 1.19.2 when the plugin became opt-in"]`. It compares names only (see Pitfall 4). |
| `src/ops/redaction.py` (existing) | in-repo | Redact secrets in logs | Never log the DB URL; use `URL.render_as_string(hide_password=True)` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Truncate-per-test cleanup | Template database + `CREATE DATABASE ... TEMPLATE` per test | Required because the append-only trigger blocks DELETE/TRUNCATE on `journal_events`; clone cost is small for an empty schema |
| `psycopg_pool` | SQLAlchemy `QueuePool` (default) | Deferred by CONTEXT to Phase 24 |
| PG ENUM types | VARCHAR + named CHECK | VARCHAR + CHECK is simpler to migrate (ALTER TYPE is awkward) and matches current columns |

**Installation:** none. This phase adds no external package. Optional: raise the pyproject floor to `alembic>=1.19.2` (then `uv lock` and commit `uv.lock`; CI runs `uv lock --check`) so the opt-in check plugin name is guaranteed. The lockfile already resolves 1.20.0.

**Version verification:** `[VERIFIED: uv.lock]` alembic 1.20.0; runtime import printed `2.0.54 3.3.6 1.20.0` for sqlalchemy, psycopg, alembic. (AGENTS.md lists older numbers; the lockfile is authoritative.)

## Package Legitimacy Audit

No new packages are introduced, so the legitimacy gate has nothing to run. All three libraries are already locked in `uv.lock` and in use since Phase 2.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| (none new) | - | - | - | - | - | n/a |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## CONTEXT conflicts and corrections (read before planning)

Each item says what CONTEXT assumes, what the code or docs show, and the recommended resolution. Items marked **BLOCKER** need a planner decision or user confirmation.

| # | CONTEXT says | Evidence | Resolution |
|---|--------------|----------|------------|
| C1 | D-05: migration "applied by `deploy/migrate.sh`" | `deploy/migrate.sh` header: "Provider-to-provider cutover: move the running collector, its Parquet store and its database from an OLD host to a NEW host" (lines 2-4). Alembic runs from compose `db-upgrade` (`docker-compose.yml:69` `command: ["/app/.venv/bin/alembic", "upgrade", "head"]`), `src/ops/backup.py:860-863` (`[sys.executable, "-m", "alembic", "upgrade", "head"]`), `scripts/dev/migrate.ps1`. | Do not touch `migrate.sh`. RUNBOOK text should say `db-upgrade` applies 0004. The cutover restore path already runs `alembic upgrade head` after `pg_restore`. |
| C2 | D-13: role in {ENTRY, SL, TP1, TP2} | `OrderRole` values are `ENTRY`, `STOP_LOSS`, `TAKE_PROFIT_1`, `TAKE_PROFIT_2` (`src/domain/enums.py:239-245`); `ROLE_CODES` keys are those values (`src/execution/order_ids.py:37-42`). | Use the `OrderRole` values as the `role` column and CHECK list. |
| C3 **BLOCKER** | D-20/DOMN-04: transition tables "copied from the GLOSSARY state machines and unit-tested against the GLOSSARY text" | GLOSSARY §2-§8, §10 contain value sets only; the only transition-like text is D028 ("Signal APPROVED → TradePlan APPROVED → Order PLANNED", GLOSSARY §2.1) and the DailyState machine (§8.1). The only drawn machine is the entry order lifecycle in `docs/trading/EXECUTION_SPEC.md` §3 (PLANNED → SUBMITTING → NEW → {PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED}; REJECTED and UNKNOWN absent). `docs/testing/TESTING_STRATEGY.md` §8 lists example invalid transitions and names `TradePlanStatus: CANCELED`, a value that does not exist in the enum (`enums.py:32-40`). `docs/data/DATA_MODEL.md` §5: "State transitions must be validated in application code." | The tables must be authored. Add a new GLOSSARY section (D031: GLOSSARY is the status authority; keep decision-alignment gates GL-01..GL-06 green, see Pitfall 17) and record in D051. Draft tables are in "Transitions" below, tagged `[ASSUMED]`; the planner should add a human-confirm checkpoint before they are frozen. Also fix the stale `CANCELED` token in TESTING_STRATEGY §8. |
| C4 | D-08: "quantities and prices `> 0`; `filled_quantity >= 0`" | `OrderRow` has no `filled_quantity` (`src/db/models.py:273-308`; only `quantity`); `FillRow` has `fill_quantity`. SL legs are `close_position=True` with `quantity: None` (`src/execution/manager.py:599-608`), so an `Order` row for it needs `quantity` 0 (domain requires a Decimal); a flat/closed `Position` has quantity 0. | `> 0` for: plan prices (entry_min/max, stop_loss), `risk_rate`, `risk_budget`, fills `fill_price`/`fill_quantity`. `>= 0` for: `orders.quantity`, `positions.quantity`, `fills.commission`, execution-intent quantity (nullable). `price`/`stop_price`: `IS NULL OR > 0`. Drop the `filled_quantity` clause. `[ASSUMED]` column choices; confirm in review. |
| C5 | D-09: widen `symbol_metadata.contract_type` | Phase 13 added a code guard `METADATA_TEXT_MAX_LEN = 16` (`src/data/metadata.py:47`) and a test that uses `TRADIFI_PERPETUAL` (17 chars) as the overlong example (`tests/test_metadata.py:391-395`). `symbol_metadata.status` has the same hazard: `docs/SOURCES.md:68` records `TRADING_CANCEL_ONLY` (19 chars) in the status enum. | Widen BOTH `contract_type` and `status` (suggest 32). Derive the guard from the model (`SymbolMetadata.contract_type.type.length`) instead of a literal; rewrite `test_overlong_metadata_text_raises_not_truncates` to use a string longer than the new width. |
| C6 | D-11: "the 14 missing ones" | `grep -c "op.create_index"`: 0001 = 2, 0002 = 13, 0003 = 3 (total 18). `src/db/models.py` has no `Index(`, `index=True` or `unique=True` (only the `uq_fills_order_trade` UniqueConstraint). | The count is 18, not 14. The parity test, not the number, is the arbiter. Name every ORM index exactly as the migrations did. |
| C7 | D-10: id from "(correlation_id, event_type, entity_id, a per-correlation monotonic sequence)" | The callback correlation id is itself non-deterministic per delivery: `correlation_id = f"cb:{short_id}:{ms}:{uuid.uuid4().hex[:8]}"` (`src/adapters/telegram_callbacks.py:646-650`), and `_journal_outcome` adds another `uuid4` suffix (lines 571-585). A DB-derived sequence (`max(seq)+1`) would also make a replay write a new id. | Derive callback correlation from the Telegram `callback_query.id` (stable across redelivery) and make journal ids pure functions of (prefix, correlation_id, event_type, entity_id, step label) with NO clock and NO randomness. A caller-supplied fixed step label (receipt, outcome) replaces the "sequence". Keep `content_hash_event_id` (it already includes timestamp + payload) for non-correlated events such as SAFE_MODE and sweeper. See Pattern 6. |
| C8 | D-16 (nullable `consumed_at_utc` is the state) vs D-21 (no state inferred from nullable columns) | Both are CONTEXT decisions; they conflict. | Authoritative consumption state = the explicit ENTRY intent row (`intent_status`) plus an explicit non-null `consumption_status` on `approvals` (`UNCONSUMED`/`CONSUMED`), with `consumed_at_utc` as the nullable "never happened" timestamp and a CHECK tying them together. `check_binding_full` stays untouched; the manager consults the store. This satisfies both D-16 and D-21. New values need a GLOSSARY entry (D016/D031). |
| C9 | D-23: "the CI job sets an env flag that turns a PG skip into an error"; canonical_refs: `docs/integration/BINANCE.md` documents clientOrderId semantics | The flag already exists: `TRADING_CI_STRICT: "1"` at workflow level (`.github/workflows/ci.yml:24`) and `tests/infra_helpers.py:41-47` `infra_skip` calls `pytest.fail` when it is "1", else `pytest.skip`. `TEST_DATABASE_URL` is set on the test step (`ci.yml:71`). `grep -i clientorderid docs/integration/BINANCE.md` returns nothing; the only in-repo statements are code comments (`src/adapters/binance_usdm.py:120-127`, `src/execution/manager.py:778-783`). | Reuse `infra_skip`; add no new env var, no ci.yml change is required for D-23. Add the clientOrderId facts to `docs/SOURCES.md` ("Facts verified for Phase 17") and to BINANCE.md or EXECUTION_SPEC with provenance (Binance facts section below). `tests/test_deploy_workflows.py` text-asserts ci.yml, so avoid gratuitous workflow edits. |
| C10 | D-18: snapshot includes MARKET_LOT_SIZE and PERCENT_PRICE | `SymbolFilters` (`src/adapters/binance_usdm.py:225-253`) parses PRICE_FILTER, LOT_SIZE, MIN_NOTIONAL only; `grep MARKET_LOT_SIZE\|PERCENT_PRICE src` returns nothing, although `tests/fixtures/exchange_info_sample.json` carries both for all 5 symbols. `risk.types.ConstraintSnapshot` (`src/risk/types.py:65-95`) has only symbol, tick, step, min_qty, min_notional, observed_at. | Extend the adapter parse with optional trailing fields (no migration to `symbol_metadata` needed) and persist a superset record; absent filter = explicit sentinel, never a fabricated default. |
| C11 | D-12 | See "Plan hash" section: real planner output has 23-27 fractional digits. | Locked: quantize in the planner. Blast radius and regeneration inventory documented. |
| C12 | D-01 sync stores | `execute_approved_plan` is `async def` (`manager.py:290`), awaits the adapter on the caller's loop (CR-06), and a test asserts it is a coroutine function and never calls `asyncio.run` (`tests/test_execution_manager.py:871-882`). | Manager calls the sync store directly (short local queries, bounded by `lock_timeout`); document the event-loop-blocking tradeoff; Phase 24 may wrap with `asyncio.to_thread` (the adapter already does this for SDK calls, `binance_usdm.py:1194`). Keep `manager.py` free of SQLAlchemy imports: depend on a Protocol (see Pattern 2). |
| C13 | D-16 | `Approval` has no consumption fields (`src/domain/approval.py:42-53`); `approval_to_row/from_row` are total mappers with a round-trip contract. | Add fields with defaults to `Approval` and `ApprovalRow`, update both mappers and the round-trip test; `analytics_store` reads via `approval_from_row` so a new defaulted field is backward compatible. |
| C14 | D-22 | `SafeModeController.__init__(adapter, journal, compare_fn)` and `LiveEnablementController.__init__(journal)` have no way to start in a non-default state (`safe_mode.py:131-150`-ish, `enablement.py:99-107`); after a restart SAFE_MODE silently reads "not in safe mode" (fail open). | Add optional keyword constructor state (`initial_*`) or a `rehydrate` classmethod. Wiring stays Phase 20/24. |
| C15 | D-17 | `SaveApproval = Callable[[Approval], None]` and `resolve_callback` returns the locally computed `new_approval` after `save` (`replay.py:225-236`). A lost race (another process decided first, possibly with a different action) would return the wrong approval. | The store raises a typed `ApprovalAlreadyDecided(existing)`; `_resolve_locked` catches it and returns the existing row (or rejects when the existing action differs). Small change to `replay.py`. |
| C16 | D-02 mapping | `short_id = sha256(signal_id)[:32]` is keyed by signal only (`src/approval/mapping.py` `derive_short_id`), PK is `short_id`. A superseded plan for the same signal reuses the same `short_id` with a different `trade_plan_id`. `ON CONFLICT (short_id) DO NOTHING` would silently keep the old binding. | After insert-or-conflict, re-SELECT and compare `(signal_id, trade_plan_id)`; mismatch raises (fail closed, matches 0003's stated intent "re-plans fail closed instead of silently rebinding"). |
| C17 | D-07 FK on journal reference columns | Journal-first controllers record events before the entity row exists in some flows; an FK violation would drop an audit event. | Keep the FKs (locked) but require every journal writer to insert parents first inside the same UoW, and test each existing writer (enablement, safe_mode, sweeper, drills, callbacks, execution cancel events) against the FK-bearing schema. Existing writers leave the FK columns NULL (verified in `telegram_callbacks.py:518-522`, `enablement.py:259-285`), so the risk is for future writers. |
| C18 | stale doctrine in code | `order_ids.py:3-5, 90-95` says "the exchange uses this identifier to dedupe retries - a blind retry without ID reuse is impossible by construction"; `manager.py:237-239` NOTE says consumption "is NOT handled here". | Update these docstrings in the same change (D031) so the code stops asserting the wrong premise. |
| C19 | D-11 | `scripts/check_migration_parity.py` is the column-name-only check (header lines 1-10) and is referenced by nothing in `tests/`, `docs/` or `.github/`. | Replace with the pytest `compare_metadata` test and delete the script (or have the script import the shared helper). |
| C20 | D-05 "All 0001-0003 content stays untouched" | `tests/test_phase8_audit_reviewfix.py:1415-1423` reads `0003_callback_mapping.py` text and asserts `purge`, `uq_short_id_mapping_signal_trade_plan`, `unique=True`; `tests/test_approval_message.py:419-443` asserts the 0002/0003 revision chain. | Consistent with leaving old migrations untouched. Do not add imports of project modules to any old migration. |

## Architecture Patterns

### System Architecture Diagram

```
Telegram callback ──> parse/chat gate ──> dispatch_callback ──> resolve_callback(lookup, save)
 (query.id stable)        │ journal receipt (deterministic id)         │
                          ▼                                            ▼
                  PgJournalStore.record ───────────┐        PgApprovalStore
                                                    │         ├ lookup_by_token_hash   (unique idx)
                                                    │         ├ save_atomic: tx{ conditional UPDATE WHERE status='PENDING'
                                                    │         │                  + short_id_mapping insert-or-verify }
                                                    │         └ 23505 on uq_approvals_one_decided_per_plan -> ApprovalAlreadyDecided
                                                    ▼
                                         journal_events (append-only trigger)

execute_approved_plan(approval, store=PgExecutionStateStore, ...)
   1 args/gates (binding, enablement, SAFE_MODE, cost, risk, placement gates)   -- zero DB writes
   2 stored_outcome = store.get_entry_intent(approval_id)? ──yes──> return stored ExecutionOutcome (0 adapter calls)
   3 get_position_mode (adapter)
   4 TX1: INSERT execution_intents(ENTRY, INTENDED) ON CONFLICT(approval_id,role) DO NOTHING RETURNING
         + UPDATE approvals SET consumption_status='CONSUMED', consumed_at_utc  ── lost race? read stored, return
   5 TX2: ENTRY -> SENT, then await adapter.place_entry   (crash here => durable SENT, restart => UNKNOWN)
   6 TX3: ENTRY -> ACKED | REJECTED | UNKNOWN from the response/probe
   7 TX4: INSERT intent(STOP_LOSS, INTENDED); TX5: -> SENT; await adapter.place_algo_protective
   8 TX6: SL -> ACKED | REJECTED | UNKNOWN; finalize ENTRY outcome (reason_code) ; return ExecutionOutcome

Restart: PgExecutionStateStore.list_unresolved_intents() -> {INTENDED,SENT,UNKNOWN}
         -> never re-send; optional resolve by query_order_by_client / query_algo_order_by_client
         -> unresolved => safe_mode_controller.enter_safe_mode(...)  (fail closed)

system_state_events (append-only, per-key version) <- tx with journal event; latest(key) -> rehydrate controllers
plan_constraint_snapshots (1 row per trade_plan_id, canonical JSON + sha256) -> age check vs constraint_snapshot_ttl_seconds
```

### Recommended Project Structure
```
src/
├── persistence/
│   ├── __init__.py
│   ├── engine.py          # make_sync_engine (UTC options, pre_ping, lock_timeout), assert_session_utc
│   ├── uow.py             # OperationalDatabase.transaction() -> Tx with bound repos
│   ├── errors.py          # StoreUnavailable, ApprovalAlreadyDecided, IllegalTransition re-export, PrecisionError
│   ├── journal.py         # PgJournalStore (record = own tx; append(tx) = inside UoW), id builders live in src/domain/journal.py
│   ├── approvals.py       # PgApprovalStore (lookup_by_token_hash, save, save_atomic, insert_pending, lookup_by_short_id)
│   ├── execution_state.py # PgExecutionStateStore (intents, consume, outcomes, unresolved query)
│   ├── plans.py           # plan/signal/order/fill/position repos using db.mappers + transitions + precision guard
│   ├── snapshots.py       # plan_constraint_snapshots repo + staleness predicate
│   └── system_state.py    # system_state_events append / latest / rehydrate helpers
├── domain/transitions.py  # pure legal-transition tables + IllegalTransition
├── execution/intent_store.py  # Protocol ExecutionIntentStore + in-memory fake for unit tests (no SQLAlchemy import)
└── db/{models.py,mappers.py,alembic/versions/0004_persistence_integrity.py}
tests/
├── pg_support.py (or conftest fixtures)   # server URL, template DB, per-test clone, strict skip
└── test_persistence_*.py, test_execution_exactly_once_pg.py, test_transitions.py, test_journal_ids.py ...
```
`src/execution/manager.py` currently documents "no SQLAlchemy" (module docstring lines 9-12); keep it so by depending on a Protocol defined in `src/execution/`.

### Pattern 1: Engine factory with UTC pinned and verified
**What:** one factory builds a sync engine whose every connection has `TimeZone=UTC`, fails closed on unreachable DB, and bounds lock waits.
**When:** all stores; migrations keep their own NullPool engine in `env.py`.
```python
# Source: libpq connection options (psycopg make_conninfo verified offline: options='-c timezone=UTC'); psycopg docs
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


def make_sync_engine(database_url: str) -> Engine:
    if database_url.startswith(
        "postgresql://"
    ):  # bare scheme would select psycopg2 (not installed)
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if not database_url.startswith("postgresql+psycopg://"):
        raise ValueError("refusing engine: expected postgresql+psycopg://")
    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={
            "options": "-c timezone=UTC -c lock_timeout=5000"
        },  # lock_timeout value is a design choice [ASSUMED]
    )
    with engine.connect() as conn:  # raises OperationalError if unreachable (fail closed)
        if conn.execute(text("SHOW TimeZone")).scalar_one() != "UTC":
            raise RuntimeError("session TimeZone is not UTC")
    return engine
```
Never print `engine.url` with the password; use `engine.url.render_as_string(hide_password=True)`.

### Pattern 2: Injected execution-state Protocol (minimal churn)
**What:** `execute_approved_plan` gains ONE required keyword argument (no `None` default, per 09-REVIEW CR-07), typed by a Protocol in `src/execution/`; production passes `PgExecutionStateStore`, unit tests pass an in-memory fake with identical semantics.
```python
# src/execution/intent_store.py  (stdlib only)
class ExecutionIntentStore(Protocol):
    def get_entry_outcome(self, *, approval_id: str) -> StoredEntry | None: ...
    def consume_and_record_entry_intent(self, *, approval_id: str, trade_plan_id: str, plan_hash: str,
                                        client_order_id: str, quantity: Decimal, price: Decimal,
                                        now_utc: datetime) -> bool: ...   # True = this caller won
    def mark_sent(self, *, approval_id: str, role: str, now_utc: datetime) -> None: ...
    def record_result(self, *, approval_id: str, role: str, status: str,
                      exchange_order_id: str | None, exchange_status: str | None, now_utc: datetime) -> None: ...
    def record_intent(self, *, approval_id: str, role: str, plan_hash: str, client_id: str, ...) -> bool: ...
    def finalize_entry_outcome(self, *, approval_id: str, is_no_trade: bool, reason_code: str, now_utc: datetime) -> None: ...
    def list_unresolved_intents(self) -> Sequence[StoredIntent]: ...
```
Call sites in tests: `tests/test_execution_manager.py:209-222` `_live_wiring()` is the single place that builds the collaborators; direct calls at lines 468, 550, 599, 656, 709, 844 all go through `**_live_wiring()` or `_run_plan`, so adding one entry there covers all 6 sites. `tests/test_execution_attach.py` does not call `execute_approved_plan` (docstring mention only, line 492).

### Pattern 3: Idempotent insert + conditional update (no exceptions on the happy path)
```python
# Source: SQLAlchemy 2.0 postgresql insert().on_conflict_do_nothing(); PG ON CONFLICT semantics
from sqlalchemy.dialects.postgresql import insert as pg_insert

stmt = (
    pg_insert(ExecutionIntentRow)
    .values(**row_values)
    .on_conflict_do_nothing(index_elements=["approval_id", "role"])  # named arbiter only
    .returning(ExecutionIntentRow.approval_id)
)
won = session.execute(stmt).first() is not None
```
A violation of a DIFFERENT unique index (for example `client_order_id` reused by another approval of the same plan) is NOT suppressed by a targeted arbiter and raises `IntegrityError`; map it to a fail-closed NO_TRADE (`INVALIDATED`) and roll back. Any `IntegrityError` aborts the current transaction in PostgreSQL, so code that must continue after catching one wraps the statement in `with session.begin_nested():` (SAVEPOINT).
```python
try:
    with session.begin_nested():
        res = session.execute(
            update(ApprovalRow)
            .where(ApprovalRow.approval_id == aid, ApprovalRow.status == "PENDING")
            .values(result=..., status=..., acted_at_utc=now)
        )
except IntegrityError as exc:
    name = getattr(
        getattr(exc.orig, "diag", None), "constraint_name", None
    )  # Diagnostic.constraint_name verified offline
    if name == "uq_approvals_one_decided_per_plan":
        raise ApprovalAlreadyDecided(...) from exc
    raise
if res.rowcount == 0:
    raise ApprovalAlreadyDecided(...)  # someone else decided first
```
The constraint name reported for a unique INDEX violation is the index name `[ASSUMED]` (standard PG behavior, not re-run here); the test must assert it on a real server.

### Pattern 4: Disposable database via template clone
```python
# session scope: create template, run alembic upgrade head into it, dispose all connections
# function scope: CREATE DATABASE t17_<hex>_test TEMPLATE t17_tmpl_<hex>_test ; yield url ; DROP DATABASE ... WITH (FORCE)
admin = create_engine(
    server_url, isolation_level="AUTOCOMMIT"
)  # CREATE/DROP DATABASE cannot run in a transaction
assert name.endswith("_test") and name.startswith("t17_")  # refuse anything else (D-23)
```
Facts: `CREATE DATABASE ... TEMPLATE` fails if any other session is connected to the source `[CITED: postgresql.org/docs/17/manage-ag-templatedbs.html]`; `DROP DATABASE ... WITH (FORCE)` terminates remaining connections, except with prepared transactions, logical slots or subscriptions `[CITED: postgresql.org/docs/17/sql-dropdatabase.html]`. The CI service user `trading` is the container superuser (`POSTGRES_USER`, `ci.yml:36`), so CREATEDB is available. Reason for templates: `journal_events` rejects DELETE/TRUNCATE (D-10), so row cleanup between tests is impossible; clone per test instead. Read-only schema tests can share the session template DB.

### Pattern 5: Alembic parity test (compare_metadata)
```python
# Source: alembic/autogenerate/api.py:358 (autogenerate_plugins read from MigrationContext opts);
#         alembic/ddl/impl.py:610-624 (compare_type compares type AND args such as length/precision)
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

opts = {
    "compare_type": True,
    "compare_server_default": True,
    "autogenerate_plugins": ["alembic.autogenerate.*", "alembic.ext.checkconstraint_byname"],
}
with engine.connect() as conn:
    diff = compare_metadata(MigrationContext.configure(conn, opts=opts), Base.metadata)
assert diff == [], diff
```
Requirements: NAME every CHECK, UNIQUE, FK and Index explicitly (the check plugin only considers named constraints, `ext/checkconstraint_byname.py` filters on `_constraint_is_named`). Do not add a MetaData `naming_convention` (it would change implicit names of 0001-0003 objects). PG limits that the diff cannot see are covered by supplementary assertions (Pitfall 4).

### Pattern 6: Deterministic, collision-free journal ids
```python
def correlated_event_id(
    *, prefix: str, correlation_id: str, event_type: str, entity_id: str, step: str
) -> str:
    material = json.dumps(
        [correlation_id, event_type, entity_id, step], separators=(",", ":"), ensure_ascii=True
    )
    return f"{prefix}_{hashlib.sha256(material.encode()).hexdigest()}"  # prefix + 65 chars <= 128
```
Rules: no clock, no uuid, no counter read from the DB. Replays with the same correlation id and step produce the same id, so `INSERT ... ON CONFLICT (journal_event_id) DO NOTHING` is idempotent; the store then re-SELECTs on conflict and compares `payload_json`, raising `JournalConflict` on mismatch (a silent drop of a different event is the exact F-412 failure). Existing `content_hash_event_id` (`src/domain/journal.py:20-49`, covers event_type, entity_id, occurred_at, payload; used by enablement, manager cancel events, health, killgate) stays for events with no stable correlation. Builders to fix: `src/reconcile/safe_mode.py:313`, `src/reconcile/sweeper.py:315,343,370`, `src/ops/drills.py:402`, `src/adapters/telegram_callbacks.py:514,552,585,650`.

### Anti-Patterns to Avoid
- **Relying on `ON CONFLICT DO NOTHING` without a target** for intents: it would also swallow the cross-approval `client_order_id` violation, hiding a second-entry attempt.
- **Catching `Exception` around store calls on the order path in the manager:** a crash-injection or a real DB failure must propagate to the caller as fail-closed; the manager's `except Exception` blocks (`manager.py:187, 196`) surround adapter calls only.
- **A DB-computed "next sequence" in journal ids** (breaks replay idempotency).
- **Importing project enums into migration 0004** (migrations are immutable snapshots; copy literals, let the parity/insert tests detect later drift).
- **`Base.metadata.create_all` in new PG tests** (D-23; the audit finding F-606).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Idempotent insert / lost-race handling | try/except IntegrityError loops | `pg_insert(...).on_conflict_do_nothing(index_elements=[...]).returning(...)` + `begin_nested()` where an exception is unavoidable | Atomic and race-free in PG; exceptions abort the transaction |
| Schema drift detection | column-name regex over rendered DDL (`scripts/check_migration_parity.py`) | `alembic.autogenerate.compare_metadata` + `ext.checkconstraint_byname` + targeted PG catalog assertions | Compares types, args, indexes, FKs, uniques |
| UTC handling | per-query `AT TIME ZONE` conversions | `options=-c timezone=UTC` on every connection + startup `SHOW TimeZone` assertion | psycopg returns timestamptz in the connection TimeZone `[CITED: psycopg.org/psycopg3/docs/basic/adapt.html]` |
| Test DB isolation | TRUNCATE/DELETE between tests | Template DB clone per test | Append-only journal forbids DELETE/TRUNCATE |
| Constant-time token compare | custom compare | existing `verify_token_hash` (`hmac.compare_digest`, `src/approval/tokens.py`) | Already correct |
| Decimal canonical text | new formatter | extract the existing `_canonical_decimal_text` (`src/backtest/costs.py:66-85`, D047) into `src/domain/canonical.py` and import it from both | One rule, built from the digit tuple, context-independent |
| CI skip policy | new env var | `tests/infra_helpers.infra_skip` + `TRADING_CI_STRICT` | Already wired in `ci.yml:24` |
| Per-call exchange dedup assumption | trusting `-4116` | persisted intent row | Binance only dedups among open orders |

**Key insight:** every "second entry" scenario (replay, restart, cancel-then-replay) is a state the exchange cannot see; only a durable local record keyed by approval and plan can see it, and the DB constraint must be the line of defense.

## Schema 0004 blueprint

Migration file `src/db/alembic/versions/0004_persistence_integrity.py`, `down_revision = "0003_callback_mapping"`, hand-written with explicit constraint names. Hand-write literal enum values (copy from `src/domain/enums.py` at authoring time).

**Enum-to-column map (the columns that get a named CHECK; all values `[VERIFIED: src/domain/enums.py:16-256]`):**

| Column | Enum | Longest value (len) | Current width | Action |
|--------|------|---------------------|---------------|--------|
| `signals.status` | SignalStatus (8) | SKIPPED_USER (12) | 16 | CHECK; widen to 32 for headroom |
| `trade_plans.status` | TradePlanStatus (6) | APPROVAL_PENDING (16) | 16 (exact fit, no headroom) | CHECK; widen to 32 |
| `approvals.action` | ApprovalAction (5) | SKIP_USER/SKIP_BUSY (9) | 16 | CHECK |
| `approvals.result`, `approvals.status` | ApprovalResult (4) | APPROVED (8) | 16 | CHECK |
| `orders.local_status` | OrderStatus (9) | PARTIALLY_FILLED (16) | 16 (exact fit) | CHECK; widen to 32 |
| `positions.status` | PositionStatus (5) | LIQUIDATION_REPORTED (20) | **16** | **widen to 32** (F-403) + CHECK |
| `signals.direction` | Direction (2) | SHORT (5) | 8 | CHECK |
| `signals.setup_type` | SetupType (6) | BREAKOUT_RETEST_SHORT (21) | 64 | CHECK |
| `signals.source_timeframe` | SourceTimeframe (3) | 1m/1h/4h (2) | 8 | CHECK |
| `trade_plans.entry_model` | EntryModel (2) | LIMIT_ZONE (10) | 32 | CHECK |
| `orders.order_role` | OrderRole (4) | TAKE_PROFIT_1 (13) | 32 | **No CHECK**: `Order.order_role` is a free string documented as "ENTRY / STOP / TP / CANCEL_REPLACE / OTHER" (`src/domain/order.py` field comment), which does not equal `OrderRole`; decide in review `[ASSUMED]`. `execution_intents.role` does get the CHECK. |
| `trade_plans.quantization_decision` | QuantizationDecision (3) | DEFERRED_TO_RISK (16) | 32 | **No CHECK**: existing tests use the non-enum value `"ACCEPT"` (`tests/test_domain_mappers.py` `sample_trade_plan`, `tests/test_domain_mappers_pg.py:147`) |
| `symbol_metadata.contract_type` | exchange string | TRADIFI_PERPETUAL (17) | **16** | widen to 32; no CHECK (exchange-defined, may grow) |
| `symbol_metadata.status` | exchange string | TRADING_CANCEL_ONLY (19, per `docs/SOURCES.md:68`) | **16** | widen to 32; no CHECK |

`ALTER COLUMN ... TYPE VARCHAR(32)` from VARCHAR(16) is a metadata-only change in PostgreSQL (no table rewrite) `[ASSUMED: standard PG behavior]`, so the 0004 upgrade is safe on the live host whose only populated tables are collector tables (Runtime State Inventory below).

**Unique / partial indexes (all named):**
- `uq_approvals_token_hash` UNIQUE(`approval_token_hash`).
- `uq_approvals_one_decided_per_plan` UNIQUE(`trade_plan_id`) `WHERE status <> 'PENDING'` (D-06). Declare with BOTH `postgresql_where=` and `sqlite_where=`, otherwise the many SQLite `create_all` tests get a full unique index; offline compile confirmed both dialects render `... WHERE status <> 'PENDING'`.
- `uq_orders_client_order_id` UNIQUE(`client_order_id`) `WHERE client_order_id IS NOT NULL`; `uq_orders_algo_client_id` likewise (in PG a plain unique already ignores NULLs; the partial form states intent and matches D-06).
- `execution_intents`: PK(`approval_id`, `role`); UNIQUE(`client_order_id`) WHERE NOT NULL; UNIQUE(`algo_client_id`) WHERE NOT NULL; recommended extra UNIQUE(`trade_plan_id`, `role`) (one entry per plan regardless of approval).
- The 18 existing migration indexes declared on the ORM with identical names (C6).

**Foreign keys, all `ondelete="RESTRICT"`, all named (`fk_<table>_<col>`):** D-07 list; `execution_intents.approval_id -> approvals`, `.trade_plan_id -> trade_plans`; `plan_constraint_snapshots.trade_plan_id -> trade_plans` (UNIQUE). Dependency order for inserts: signals, trade_plans, approvals, positions, orders, fills; no cycles (orders self-FK `parent_order_id` only).

**Append-only trigger (PostgreSQL 17; `CREATE TRIGGER ... EXECUTE FUNCTION` is the current syntax):**
```sql
CREATE FUNCTION reject_journal_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'journal_events is append-only (% blocked)', TG_OP USING ERRCODE = 'P0001'; END $$;
CREATE TRIGGER trg_journal_events_append_only BEFORE UPDATE OR DELETE ON journal_events
  FOR EACH ROW EXECUTE FUNCTION reject_journal_mutation();
CREATE TRIGGER trg_journal_events_no_truncate BEFORE TRUNCATE ON journal_events
  FOR EACH STATEMENT EXECUTE FUNCTION reject_journal_mutation();
```
Row triggers do not fire on TRUNCATE, hence the second statement-level trigger. The table owner can still `DISABLE TRIGGER`; owner-vs-app-role separation is explicitly deferred (Phase 26). Do the same for `system_state_events`. `DROP TABLE` in the downgrade is unaffected. Triggers and functions are not in `Base.metadata`, so the parity test asserts them from `pg_trigger`.

**Terminal-state DB rule ("where cheap", D-20):** a `BEFORE UPDATE OF status` trigger rejecting changes whose OLD status is terminal (`approvals`: APPROVED/SKIPPED/EXPIRED; `signals`, `trade_plans`, `orders`, `positions` terminals from the transition tables) is cheap and mirrors the Python table; keep the terminal set in one generated place and cover with the same parity test. Optional if time-boxed; the unique partial index already enforces the approval case.

**New tables:** `execution_intents`, `plan_constraint_snapshots`, `system_state_events` (below). All timestamps TIMESTAMPTZ, money NUMERIC(38,18), no auto-increment, nullable only for "transition never happened".

**Alembic operations to use:** `op.alter_column(table, col, type_=sa.String(32), existing_type=sa.String(16), existing_nullable=False)`, `op.create_check_constraint(name, table, sqltext)`, `op.create_index(..., unique=True, postgresql_where=sa.text("..."))`, `op.create_foreign_key(name, src, dst, [src_col], [dst_col], ondelete="RESTRICT")`, `op.execute(...)` for function/trigger DDL; downgrade drops in reverse order and narrows widths back (the reversibility test runs on an empty database; a downgrade that would truncate data should fail loudly, never silently).

## Write-ahead intent design (EXEC-03, F-126, F-703)

Insertion points in `execute_approved_plan` (all line numbers `[VERIFIED: src/execution/manager.py]`):

| Step | Where | Store call |
|------|-------|-----------|
| 0 | after arg validation (lines 372-386), before Gate 1 or right after Gate 1b | `get_entry_outcome(approval_id)`; if present return the stored outcome with zero adapter calls (D-15). |
| 1 | after `resolve_position_mode` (line 546-549) and quantity/price derivation, immediately before `_place_entry_no_blind_retry` (line 558) | `consume_and_record_entry_intent(...)` TX1: insert ENTRY INTENDED + stamp approval consumed; `False` = lost race, re-read stored outcome and return it |
| 2 | still before the adapter call | `mark_sent` (commit SENT) |
| 3 | after `entry_state` known (lines 570-583) | `record_result`: PLACED/EXISTS -> ACKED; ABSENT -> REJECTED (definitive absence, no exposure); UNKNOWN -> UNKNOWN and `enter_safe_mode(reason=_ENTRY_STATE_UNKNOWN)` as today |
| 4 | before `_place_protective_leg` (line 594) | insert STOP_LOSS intent INTENDED then SENT (id from `derive_algo_client_id`, the same call `_place_protective_leg` makes at line 776) |
| 5 | after SL result (lines 610-631) | SL -> ACKED / REJECTED / UNKNOWN; `finalize_entry_outcome(is_no_trade, reason_code)` with the exact `ExecutionOutcome` fields |

Notes:
- `_place_entry_no_blind_retry` retries `place_entry` once after a DEFINITIVE absence probe (`_ENTRY_MAX_ATTEMPTS = 2`, line 159). Keep the intent SENT across that retry; adapter call-sequence assertions in `test_execution_manager.py` (for example the six-method sequence at lines 734-741) are unaffected because store calls are not adapter calls.
- Before this phase, with the first entry still OPEN, a second call is already safe by accident: `place_entry` raises, the probe finds the order, `ENTRY_EXISTS`, SL is adopted by query-first (`_place_protective_leg`, lines 776-798). The bug exists only when the first entry is FILLED or CANCELED. The negative control must use that state.
- `ExecutionOutcome` (`manager.py:97-120`) is `(is_no_trade: bool, reason_code: str)`: persist as two columns (`outcome_is_no_trade`, `outcome_reason_code`) plus an explicit `outcome_recorded BOOLEAN NOT NULL DEFAULT FALSE` (C8), CHECK `(outcome_recorded = (outcome_reason_code IS NOT NULL))`. A replay that finds ENTRY in INTENDED/SENT/UNKNOWN without a recorded outcome returns `ExecutionOutcome(True, RECONCILIATION_REQUIRED)` and never touches the adapter.
- Gate 2 passes `plan_hash=approval.trade_plan_id` to `guard_placement` (`manager.py:421-423`), which ignores the argument (`enablement.py` docstring: "accepted (and ignored)"). Harmless; do not "fix" it in this phase.
- Pre-placement rejections (binding, enablement, SAFE_MODE, cost, risk, placement gates) do not consume the approval, so a later retry of the same approved plan re-runs every gate. This is the default; see Open Question 1.
- Crash recovery contract (D-14): intents in `INTENDED`/`SENT`/`UNKNOWN` after restart are unresolved. `list_unresolved_intents()` plus a small async `resolve_unresolved_intents(store, adapter, safe_mode_controller, now_utc)` that queries `query_order_by_client` / `query_algo_order_by_client` and records ACKED/REJECTED, else `enter_safe_mode`. Binance's order-by-client lookup does NOT find an order that is "CANCELED or EXPIRED AND NO filled trade AND created time + 3 days < current time" or older than 90 days `[CITED: developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Query-Order]`, so "not found" is a definitive absence only for intents younger than 3 days; older unresolved intents must stay UNKNOWN. The algo-order query retention is undocumented `[ASSUMED]`.

### Binance facts (re-verified this session, official docs)
- `newClientOrderId`: "A unique id among open orders. Automatically generated if not sent."; pattern `^[\.A-Z\:/a-z0-9_-]{1,36}$` `[CITED: developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Order]`. The project ids (`x-` + 32 hex + 2, 36 chars; `xa-` + 31 hex + 2) fit.
- `clientAlgoId`: "A unique id among open orders. Automatically generated if not sent. Can only be string following the rule: `^[\.A-Z\:/a-z0-9_-]{1,36}$`" `[CITED: .../trade/rest-api/New-Algo-Order]`. The docs name no error code for a duplicate algo id `[ASSUMED]` that it behaves like -4116; the fake should reject duplicates with a generic client error for algo ids.
- Error `-4116 DUPLICATED_CLIENT_ORDER_ID`, text "clientOrderId is duplicated" `[CITED: developers.binance.com/docs/derivatives/usds-margined-futures/error-code]` (also `-4115 DUPLICATED_CLIENT_TRAN_ID`, unrelated, 7-day window). Search result dates -4116 to 2024-12-03 `[CITED: developers.binance.com/docs/derivatives/change-log]` (search summary only).
- Therefore a FILLED or CANCELED order frees its id: this follows from the documented rule, and is the audit's F-126 premise.
- Record these in `docs/SOURCES.md` "Facts verified for Phase 17" with confidence MEDIUM (WebFetch summaries by a small model, not raw page text, same caveat the repo already records for other Binance pages).

### Stateful fake for SC4 (D-25)
Build `tests/support/fake_binance_exchange.py` (or inside the test module) implementing the 8-method adapter surface (`place_entry`, `place_algo_protective`, `query_order_by_client`, `query_algo_order_by_client`, `get_position_mode`, `cancel_normal_order`, `cancel_algo_order`). Reuse the signature-binding guard from `FakeExecutionAdapter._bind_real` (`tests/test_execution_manager.py:121-129`) so kwargs bind to the REAL adapter signatures. State: `open_orders: dict[client_id, status]`, `history: dict[client_id, status]`. `place_entry` raises (`RuntimeError("-4116 clientOrderId is duplicated")`) only when the id is in `open_orders`; `fill(client_id)` / `cancel(client_id)` move it out of `open_orders` so a later identical id is ACCEPTED. `query_order_by_client` returns `OrderProbe(found=...)` from `history` (found for filled/canceled within the 3-day window, matching Query Order). The probe/response types are `src/adapters/binance_usdm.py:349-437`.

SC4 test matrix (each asserts exactly one `place_entry` call and one ENTRY intent row): (a) double call with first entry OPEN; (b) double call after `fill()`; (c) double call after `cancel()`; (d) restart between calls (new engine, new store, new manager on the same DB), for (a)-(c); (e) concurrent double call (two threads); plus the NEGATIVE CONTROL: the same scenario with `AlwaysWinsIntentStore` (never remembers) yields TWO entries in (b) and (c), proving the fake catches F-126.

## Approvals store design (APRV-02)

- `lookup_by_token_hash(h) -> Approval | None`: `SELECT ... WHERE approval_token_hash = :h` through `approval_from_row`.
- `insert_pending(approval)`: idempotent on `approval_id`; today nothing in `src/` creates PENDING approval rows (grep `Approval(` only finds the mapper), so the store must offer it for Phase 23/24 senders.
- `save_atomic(approval, mapping)` (matches `SaveAtomic = Callable[[Approval, ShortIdMapping | None], None]`, `telegram_callbacks.py:215`) in ONE transaction: (1) conditional UPDATE `WHERE approval_id=:id AND status='PENDING'` inside a SAVEPOINT; (2) mapping insert-or-verify (C16); (3) on 0 rows or `uq_approvals_one_decided_per_plan` violation raise `ApprovalAlreadyDecided(existing)`.
- `resolve_callback` change (C15): catch `ApprovalAlreadyDecided` in `_resolve_locked` and return the existing approval (replay-to-existing) unless the existing row's action differs from the pressed button, in which case raise `ApprovalRejected(INVALIDATED)`.
- The in-process `_TOKEN_LOCKS` (`replay.py:55-65`) stays as a latency optimization only (D-17).
- Callback correlation (C7): `on_callback` builds `callback_at_utc = datetime.now(UTC)` and a uuid correlation per delivery (`telegram_callbacks.py:646-650`); derive the correlation id from `query.id` and keep `callback_at_utc` out of the id material.

## Constraint snapshot design (EXEC-04)

- Table `plan_constraint_snapshots`: `trade_plan_id` PK/FK RESTRICT, `symbol`, `constraints_observed_at_utc` (TIMESTAMPTZ, the exchangeInfo capture time = `ConstraintSnapshot.metadata_observed_at_utc`), `snapshot_json` TEXT (canonical JSON, Decimal as text, sorted keys, no float; reuse `canonical_bytes`), `snapshot_sha256` CHAR(64), `live_inputs_status` explicit (`COMPLETE`/`INCOMPLETE`; INCOMPLETE while margin type, leverage or equity carry the `"UNKNOWN"` sentinel) (D-19).
- JSON keys: symbol, price_tick_size, quantity_step_size, min_quantity, max_quantity, min_notional, MARKET_LOT_SIZE (min/max/step) and PERCENT_PRICE (multiplier up/down, decimals) as parsed Decimals/ints or the sentinel `"UNKNOWN"` when the adapter did not supply them, `working_type` (the manager hard-codes `"MARK_PRICE"` for SL, `manager.py:607`; the registry param `working_type` is validated against a closed set, `registry.py` ~372), margin type, leverage, equity used. Sentinels are explicit strings, never zero or invented values.
- The sha256 goes into plan evidence, NOT into `plan_hash` (the approval binding contract does not move, D-18).
- Staleness: reuse the existing predicate from `src/execution/gates.py:190-199` (`age = now_utc - metadata_observed_at_utc; stale if age > ttl or age < 0`) with the registry parameter `constraint_snapshot_ttl_seconds` (`src/domain/registry.py:108, 299`; value 3600 in current param files). Expose `snapshot_is_valid_for_live(snapshot, now_utc, ttl)` returning False for stale OR `INCOMPLETE`.
- Adapter change (C10): add optional trailing fields on `SymbolFilters` for MARKET_LOT_SIZE and PERCENT_PRICE parsed with `Decimal(str(...))` like the others, `None` when the filter is absent; no `symbol_metadata` column is needed.

## Transitions (DOMN-04) - DRAFT, needs confirmation

`src/domain/transitions.py`, pure stdlib, `IllegalTransition(ValueError)`. Repositories call `assert_transition(kind, old, new)` inside the same transaction as the UPDATE, preceded by a conditional UPDATE (`WHERE status = :old`) so concurrent writers cannot skip states. Parity test: every enum member appears as a key in its table (fails when an enum gains a value without an entry). Draft tables (`[ASSUMED]`, derived from GLOSSARY §2.1/D028, EXECUTION_SPEC §3, TESTING_STRATEGY §8 examples and the code paths that exist):

- **Signal:** DETECTED -> {NOTIFIED, SKIPPED_BUSY, EXPIRED, INVALIDATED}; NOTIFIED -> {VIEWED, APPROVED, SKIPPED_USER, SKIPPED_BUSY, EXPIRED, INVALIDATED}; VIEWED -> {APPROVED, SKIPPED_USER, SKIPPED_BUSY, EXPIRED, INVALIDATED}; terminal: APPROVED, SKIPPED_USER, SKIPPED_BUSY, EXPIRED, INVALIDATED. (`EXPIRED -> APPROVED` is the documented invalid example.)
- **TradePlan:** READY -> {APPROVAL_PENDING, EXPIRED, INVALIDATED, SUPERSEDED}; APPROVAL_PENDING -> {APPROVED, EXPIRED, INVALIDATED, SUPERSEDED}; APPROVED -> {EXPIRED, INVALIDATED}; terminal: EXPIRED, INVALIDATED, SUPERSEDED. Open: whether APPROVED -> SUPERSEDED is legal.
- **Order:** PLANNED -> {SUBMITTING, CANCELED}; SUBMITTING -> {NEW, REJECTED, UNKNOWN, CANCELED}; NEW -> {PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED, REJECTED, UNKNOWN}; PARTIALLY_FILLED -> {FILLED, CANCELED, EXPIRED, UNKNOWN}; UNKNOWN -> {NEW, PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED, REJECTED} (reconciliation only); terminal: FILLED, CANCELED, EXPIRED, REJECTED.
- **Position:** OPEN -> {CLOSING, CLOSED, LIQUIDATION_REPORTED, UNKNOWN}; CLOSING -> {CLOSED, OPEN, UNKNOWN}; LIQUIDATION_REPORTED -> {CLOSED, UNKNOWN}; UNKNOWN -> {OPEN, CLOSING, CLOSED, LIQUIDATION_REPORTED} (reconciliation only); terminal: CLOSED.
- Also cheap and useful: **Approval** (PENDING -> {APPROVED, SKIPPED, EXPIRED}, all else terminal) and **ExecutionIntent** (INTENDED -> SENT -> {ACKED, REJECTED, UNKNOWN}; INTENDED -> {UNKNOWN, REJECTED}; UNKNOWN -> {ACKED, REJECTED}; ACKED/REJECTED terminal).
- New enums (`ExecutionIntentStatus`, approval consumption status) need `src/domain/enums.py` members and a GLOSSARY section; the decision-alignment gates only pin RejectionReason (§9.1), ApprovalResult (§10) and the §8.2 kill-gate block, so a new GLOSSARY section is allowed if it does not disturb those blocks (Pitfall 17).

## Plan hash (D-12, F-410): evidence and blast radius

Evidence (all read this session):
- `_plan_hash` (`src/core/planner.py:52-77`) hashes `signal_id`, `entry_min_price`, `entry_max_price`, `stop_loss_price` as Decimals, plus three JSON text fields and `expiry_utc`, via `sha256_hex`.
- `canonical_scalars` renders `Decimal` as `str(value)` "full precision: 1.50 != 1.5 by design" (`src/domain/canonical.py:48-49`).
- The planner computes at `prec=28` (`src/core/_decimal.py:19-58`), and real plans carry 23-27 fractional digits: `tests/fixtures/phase4/expected_plans.json` line 5-6: `"entry_max_price": "50976.11812218609640044949190"`, `"entry_min_price": "50703.88187781390359955050810"`, `"stop_loss_price": "50794.62729260463453318350270"`, `"suggested_quantity": "1.101984053195538022097961153"`.
- PostgreSQL rounds a value whose scale exceeds the column's declared scale `[CITED: postgresql.org/docs/17/datatype-numeric.html]`; offline, `Decimal("50976.11812218609640044949190").quantize(Decimal("1e-18"))` = `50976.118122186096400449` (different digits) and `Decimal("50000").quantize(...)` stringifies as `50000.000000000000000000`. So a plan read back from the row hashes differently from the stored `plan_hash` (both by rounding and by spelling), and this never raises: PG rounds silently.

Recommended implementation (honors D-12):
1. In `plan()` quantize every stored Decimal that is persisted (`entry_min`, `entry_max`, `stop_loss`, `tp1`, `tp2`, `risk_rate`, `risk_budget`, `suggested_quantity`, `quantity_before/after_rounding`) to `Decimal("1e-18")` BEFORE building the JSON text fields and BEFORE hashing, with an explicit rounding mode (`ROUND_HALF_EVEN`, record it in D051). Quantize inside a local context with enough precision (`quantize` raises `InvalidOperation` when the result exceeds the context precision; offline test confirmed this for a 24-integer-digit value, which is the desired fail-closed behavior).
2. Make the hash spelling-invariant by moving `_canonical_decimal_text` (D047) to `src/domain/canonical.py` and applying it to the three hashed Decimals in `_plan_hash`; import it back into `src/backtest/costs.py` (behavior unchanged, its pinned `cost_model_hash` values must stay byte-identical: `tests/test_cost_per_unit.py` asserts them).
3. Add a store-boundary guard (`PrecisionError`) in the plan repository: any persisted Decimal whose `value != value.quantize(Decimal("1e-18"))` is refused. Do NOT put this guard in `TradePlan.__post_init__` (tests construct plans with 27-digit strings; a domain guard would break them).
4. Round-trip test: plan -> `trade_plan_to_row` -> PG -> `trade_plan_from_row` -> recompute `_plan_hash` == stored `plan_hash`, over the real planner outputs (not hand-made 18-digit samples).

Blast radius (a D048-style regeneration inventory, recorded in D051): `tests/fixtures/phase4/expected_plans.json` (hash and all quantized fields); `tests/test_core_planner.py` (`test_plan_hash_recomputable_from_payload`, lines 521-549, recomputes with the old Decimal payload and must be updated to the canonical form), `tests/test_core_tracer.py`; every consumer of `src.core.planner.plan`: `src/backtest/simulator.py:25`, `src/paper/loop.py:29`, and the fixtures generated through them (`scripts/gen_phase6_fixtures.py`, `scripts/_regen_phase4_expectations.py`, `scripts/_compute_phase4_fixtures.py`), including backtest/paper parity digests if they include raw plan Decimals. Fixtures that merely carry a literal `plan_hash` string for approval/order-id tests (phase5, phase8, phase9, phase10 inputs) do not recompute it and stay valid. The executor must run the full suite after the planner change and regenerate only what fails, listing each in D051 (never silently).

## Doc and decision-record notes (D-27)
- `docs/DECISIONS.md` last row is D050; D051 is free `[VERIFIED: grep of "| D05" rows]`; the decision-alignment bookkeeping gate requires D001..D0NN contiguous with a minimum last id (`scripts/decision_alignment/bookkeeping.py:454-466`), so append D051 exactly after D050.
- `docs/DOC_STATUS.md` change-log lines follow the pattern at lines 56-57.
- Also update `docs/SOURCES.md` (Facts verified for Phase 17), `docs/GLOSSARY.md` (transitions, intent status, consumption status), `docs/data/DATA_MODEL.md` §3 and §5, `docs/trading/EXECUTION_SPEC.md` §7 (currently two sentences) and §10, `docs/testing/TESTING_STRATEGY.md` §8, `docs/operations/RUNBOOK.md` (db-upgrade applies 0004; restore expectations).
- RUNBOOK section 16 holds a pins table compared with files by `tests/test_deploy_docs.py`; do not touch that table.

## Runtime State Inventory

This is a schema-hardening migration, not a rename, but the "what already exists at runtime" question still matters for 0004 safety.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | Production DB (compose `postgres` volume `pgdata`) is populated only by the Phase 2/13 collector tables (`symbol_metadata`, `collector_watermarks`, `collector_gaps`, `coverage_windows`). The seven domain tables and `short_id_mapping` have no production writer today (F-202). `[VERIFIED: grep found no non-test caller of any *_to_row; analytics_store only reads]` | 0004 adds constraints to empty domain tables and widens two `symbol_metadata` columns (existing rows survive). Write the 0003-to-0004 data-bearing test with valid rows in every table anyway. |
| Live service config | None (no n8n/Datadog/etc.). | none |
| OS-registered state | systemd backup timer and compose services exist (Phase 13.1) but reference no table or revision name. | none |
| Secrets / env vars | `DATABASE_URL` (env.py requires it, `src/db/alembic/env.py:29-34`), `TEST_DATABASE_URL`; no key renamed. | none |
| Build artifacts | Docker `runtime` image copies `src/db/alembic` (Dockerfile comment line 33), so the new revision ships on the next image build; `db-upgrade` runs it. `src/ops/backup.py` restore runs `alembic upgrade head` after `pg_restore`, so restoring an older dump upgrades through 0004. | RUNBOOK note only. |

## Common Pitfalls

### Pitfall 1: A caught IntegrityError poisons the transaction
**What goes wrong:** after a unique violation PostgreSQL rejects further statements ("current transaction is aborted").
**Why:** PG aborts the whole transaction on any error. **Avoid:** `ON CONFLICT ... RETURNING` for expected conflicts; `session.begin_nested()` around statements that may raise; never swallow the exception outside the savepoint.
**Warning sign:** `InFailedSqlTransaction` in a lost-race test.

### Pitfall 2: Swallowed crash in crash-injection tests
**What:** the manager has `except Exception` around adapter and probe calls (`manager.py:187, 196, 547, 627`).
**Avoid:** make the injected crash `class SimulatedCrash(BaseException)` so nothing converts it into a handled ambiguity; assert with `pytest.raises(SimulatedCrash)` then "restart" with new objects.

### Pitfall 3: NUMERIC rounds silently
The PG numeric overflow error covers only the integer part; extra fractional digits are rounded without error (cited). The only existing PG test checks integer overflow (`tests/test_domain_mappers_pg.py:121-154`). Add the store-boundary precision guard and the round-trip hash test.

### Pitfall 4: `compare_metadata` is blind to predicates
`alembic/ddl/postgresql.py:324-382` `compare_indexes` checks uniqueness, expression count/text and `nulls_not_distinct` only (no WHERE predicate); `alembic/ddl/impl.py:835-840` `compare_check_constraint` returns `ComparisonResult.Equal()` unconditionally. So with the opt-in plugin only the PRESENCE of named CHECKs is compared. Add: (a) a test reading `pg_get_indexdef` for each partial index and asserting the exact predicate string; (b) the D-09 insert-every-enum-member test per enum column (catches both a CHECK missing a value and a width too small); (c) a `pg_get_constraintdef` test asserting each enum-derived CHECK mentions every current enum value and no extra literal; (d) a `pg_trigger` assertion for the append-only triggers.

### Pitfall 5: Alembic `env.py` side effects in-process
`env.py` calls `fileConfig(...)` at import (resets logging, can disable existing loggers) and hard-requires `DATABASE_URL` from the environment (lines 25-34). Running `command.upgrade` in-process from tests risks log-state leakage and env mutation. Preferred: add an `env.py` seam: if `config.attributes.get("connection")` is set use it, and skip `fileConfig` when `config.attributes.get("configure_logger") is False` (the attribute names are this project's own choice; the connection-sharing pattern is standard Alembic practice `[ASSUMED]` from the cookbook, not re-fetched). Fallback: run `python -m alembic upgrade head` as a subprocess with `DATABASE_URL` in the child env, exactly like `src/ops/backup.py:860-863`. `DATABASE_URL` must use `postgresql+psycopg://`; the bare `postgresql://` scheme would select psycopg2, which is not a dependency.

### Pitfall 6: SQLite `create_all` tests and new constraints
Many tests build the ORM on SQLite (`tests/test_domain_mappers.py:93`, `test_analytics_store.py:164,575`, `test_collector.py`, `test_cutover.py:48`, `test_backfill_cli.py:235`, `test_metadata.py:80`). New named CHECKs are enforced by SQLite; FKs are not (no PRAGMA); partial unique indexes need `sqlite_where` (Pattern 3 note). Samples that may violate new CHECKs: `quantization_decision="ACCEPT"`, `quantity` 0 rows, free-string `order_role`. This is why enum CHECKs are limited to the columns in the map above.

### Pitfall 7: Existing PG test is destructive and silently skippable
`tests/test_domain_mappers_pg.py` skips at module level when `TEST_DATABASE_URL` is unset (lines 26-29) and calls `Base.metadata.drop_all(engine)` against whatever database that URL names (line 43). Rebuild it on the new fixtures; its `test_fills_order_trade_unique_pair_raises` inserts a `FillRow` with a nonexistent `order_id` (line 98-118), which will violate the new `fills.order_id` FK, so it must create the parent chain first.

### Pitfall 8: Two tables carry the same client id
`orders.client_order_id` (written by Phase 18's stream) and `execution_intents.client_order_id` are separate uniques. No cross-table constraint exists or is required, but Phase 18 must look up intents by id when it creates the order row.

### Pitfall 9: Journal-first controllers and a PG journal
`LiveEnablementController.disable` journals BEFORE flipping its flag (`enablement.py` `disable`/`_journal_enablement_event`), so with a PG journal that raises on DB loss the flag will not flip (audit F-702). `SafeModeController.enter_safe_mode` sets `_in_safe_mode = True` BEFORE journaling (`safe_mode.py` lines ~176-190), so SAFE_MODE entry survives a journal failure. Do not "fix" F-702 here (Phase 20), but the PG journal's failure type must be a distinct, documented exception so callers can translate it, and tests must cover `emergency_manual_close` with a failing journal (its steps are isolated, `manager.py:1334-1371`).

### Pitfall 10: Event-loop blocking
Sync stores inside the async manager block the loop during each query. Calls are single-row indexed queries with a `lock_timeout`; acceptable for a 4H/1H system. Document it; do not add `asyncio.to_thread` in the manager now (it would change the call shape that Phase 24 owns).

### Pitfall 11: Binance order lookup retention
Unresolved-intent resolution cannot distinguish "never existed" from "canceled with no fills more than 3 days ago" (cited above). Treat older intents as UNKNOWN.

### Pitfall 12: `short_id` collision on re-plan
See C16. Insert-or-verify, never insert-or-ignore.

### Pitfall 13: Approval rows per action
`resolve_callback` rejects a callback whose action differs from the stored row's action (`replay.py:214-218`), so a message with APPROVE and SKIP buttons implies one approval row per action (the sender does not exist yet). The partial unique index `uq_approvals_one_decided_per_plan` still gives exactly one decision per plan, but Phase 23 must create rows accordingly. Tests must cover "APPROVE decided, then a pending SKIP row for the same plan tries to decide" -> DB rejection.

### Pitfall 14: Domain datetime validation vs session TimeZone
Domain constructors reject non-UTC offsets (`_require_utc_aware`, for example `src/domain/signal.py:25-30`, `approval.py:20-25`), so a non-UTC session TimeZone does not merely shift values; every row read fails conversion. `analytics_store` counts such rows as rejected (`analytics_store.py:179-189`). The engine factory's startup assertion is the guard (F-406).

### Pitfall 15: The local machine cannot run PG
Docker Desktop's engine pipe is missing (`docker ps` fails with "dockerDesktopLinuxEngine ... cannot find the file"), `psql`/`postgres` are not installed, `TEST_DATABASE_URL` is unset. Every PG-bound task is unverifiable locally until Docker Desktop is started. Plans must say so, and verification of PG tasks must run against a real server (CI or local container) before the phase is marked done.

### Pitfall 16: pyproject/lock changes
Raising the Alembic floor changes `pyproject.toml`; CI's lint job runs `uv lock --check`, so regenerate and commit `uv.lock` in the same commit.

### Pitfall 17: GLOSSARY edits and the alignment gates
`scripts/decision_alignment/bookkeeping.py` `check_glossary` (GL-01..GL-06) parses §9.1, §9.2, §9.3, §8.2 and §10 and compares them with `RejectionReason`, `ApprovalResult` and the kill-gate tokens. Add new GLOSSARY content as a new section without altering those blocks, then run `uv run pytest tests/test_decision_alignment*.py -q`.

## Code Examples

### Disposable database fixtures (strict skip, `_test` guard)
```python
# tests/pg_support.py  (sketch; uses existing infra_helpers)
import os, secrets, subprocess, sys
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from tests.infra_helpers import infra_skip


@pytest.fixture(scope="session")
def pg_server_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        infra_skip(
            "TEST_DATABASE_URL is not set; PG tests cannot run"
        )  # fails when TRADING_CI_STRICT=1
    return url


def _admin(url: str):
    return create_engine(url, isolation_level="AUTOCOMMIT")


@pytest.fixture(scope="session")
def pg_template(pg_server_url: str):
    name = f"t17_tmpl_{secrets.token_hex(4)}_test"
    assert name.endswith("_test")
    with _admin(pg_server_url).connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(pg_server_url).set(database=name).render_as_string(hide_password=False)
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env={**os.environ, "DATABASE_URL": url},
    )  # never create_all
    yield name
    with _admin(pg_server_url).connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture
def pg_db(pg_server_url: str, pg_template: str):
    name = f"t17_{secrets.token_hex(6)}_test"
    assert name.endswith("_test") and name.startswith("t17_")
    with _admin(pg_server_url).connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}" TEMPLATE "{pg_template}"'))
    yield make_url(pg_server_url).set(database=name).render_as_string(hide_password=False)
    with _admin(pg_server_url).connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
```
Notes: the template must have no open connections at clone time (alembic subprocess exits, so it is idle). The CI URL in `ci.yml:71` is `postgresql+psycopg://trading:...@localhost:5432/trading_test`; the fixture only uses it as the maintenance connection and creates its own `t17_*_test` databases. Local fallback (needs Docker Desktop running): `docker run -d --rm -p 127.0.0.1:55432:5432 -e POSTGRES_USER=trading -e POSTGRES_PASSWORD=<throwaway> postgres:17.11-bookworm@sha256:639ab7ceb90e13123085b741fb31ef493fba25463002f6da665352e7b534b652` then `TEST_DATABASE_URL=postgresql+psycopg://trading:<throwaway>@127.0.0.1:55432/postgres`.

### Crash injection and restart
```python
class SimulatedCrash(BaseException): ...
class CrashAfter:                       # wraps a PgExecutionStateStore, raises after the Nth write
    def __init__(self, inner, *, after: str): ...
    def mark_sent(self, **kw): self._inner.mark_sent(**kw); if self._after == "mark_sent": raise SimulatedCrash
# 1 run manager -> SimulatedCrash   2 new engine + new store + new manager   3 assert intent row INTENDED/SENT,
# adapter.place_entry call count unchanged, second execute_approved_plan returns stored outcome
```

### Concurrent consume
Two `ThreadPoolExecutor` workers, each with its own store/engine, released by a `threading.Barrier`; assert exactly one `consume_and_record_entry_intent(...) is True`, one row, and the loser's stored outcome equals the winner's.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Alembic check-constraint detection built in/implicit | Opt-in `alembic.ext.checkconstraint_byname` plugin, names only | 1.19.2 (opt-in) | Must pass `autogenerate_plugins` and name constraints |
| `execute("CREATE TRIGGER ... EXECUTE PROCEDURE")` | `EXECUTE FUNCTION` | PG 11+ | Use FUNCTION form on PG 17 |
| SQLAlchemy 1.x `Session.begin_nested` implicit | 2.0 explicit `session.begin_nested()` context manager | 2.0 | Use `with` form |
| Exchange-side dedup trusted (08 D-04) | Local durable intent | Audit 2026-09-29 | The premise is retired by D051 |

**Deprecated/outdated:** `scripts/check_migration_parity.py` (column-name regex); module-level `skipif(TEST_DATABASE_URL)` in PG tests.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Draft transition tables for Signal/TradePlan/Order/Position/Approval/Intent | Transitions | Illegal-but-real transitions rejected in production, or illegal ones accepted; needs user confirmation and a GLOSSARY record |
| A2 | Column-level `>0` vs `>=0` choices (C4) | CONTEXT conflicts | A valid row (closePosition leg, flat position) rejected by CHECK |
| A3 | Skip CHECK on `orders.order_role` and `trade_plans.quantization_decision` | Schema blueprint | Garbage values admitted in those two columns |
| A4 | Unique-index violation reports the index name in `Diagnostic.constraint_name` | Pattern 3 | Wrong exception mapping; must be asserted on a real server |
| A5 | VARCHAR(16)->VARCHAR(32) is metadata-only in PG | Schema blueprint | A slow table rewrite on a large table (tables are small/empty today) |
| A6 | `lock_timeout=5000` value in engine options | Pattern 1 | Too short fails valid slow commits (fail closed, not unsafe) |
| A7 | Alembic `env.py` connection/`configure_logger` seam pattern | Pitfall 5 | Fallback to subprocess works regardless |
| A8 | Algo-order duplicate error code and algo query retention undocumented | Binance facts | Fake models a code Binance does not use; harmless to the persisted-intent design |
| A9 | NO_TRADE before placement does not consume the approval | Write-ahead design | A retried callback re-runs gates later (default); alternative is to consume on any terminal outcome |
| A10 | Callback correlation can derive from Telegram `callback_query.id` being stable across redelivery | C7 | If not stable, replay writes a second receipt event (audit noise, not a safety issue) |
| A11 | Phase 24/20 callers will pass a store satisfying `ExecutionIntentStore` | Pattern 2 | Signature churn later |

## Open Questions

1. **Should a definitive pre-placement NO_TRADE also consume the approval?**
   - Known: only placement consumes (D-13/D-15 text); a risk or cost reject leaves the approved plan retryable until expiry.
   - Unclear: whether that is the intended semantics when Telegram redelivers the same APPROVE minutes later.
   - Recommendation: keep "consume only at placement"; record the choice in D051; revisit in Phase 19 (live-price check).
2. **Order of the stored-outcome lookup versus the expiry gate.**
   - Known: `check_binding_full` rejects `now >= expiry` (`binding.py:181`), so a replay after expiry of an already-executed plan reports `APPROVAL_EXPIRED` unless the lookup runs first.
   - Recommendation: run Gate 1 identity checks (chat, token, plan hash), then consult the store BEFORE applying expiry; return the stored outcome if consumed. Planner to pick and test.
3. **Transition tables** (A1): who confirms and where is the authority recorded (GLOSSARY §11 plus a DECISIONS row)?
4. **`approvals` consumption columns** (C8): confirm the explicit `consumption_status` + nullable `consumed_at_utc` pairing and the GLOSSARY addition.
5. **Plan-level uniqueness**: add `UNIQUE(trade_plan_id, role)` on `execution_intents`? (Recommended; cheap, closes the "second approval row for the same plan" path.)
6. **Quantization rounding mode** for D-12 (`ROUND_HALF_EVEN` recommended, deterministic, record in D051).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | all | yes | 3.13.x (`.python-version` 3.13.15; `.venv` imports OK) | - |
| uv | all | yes | 0.12.20 (CI pins 0.12.21) | - |
| SQLAlchemy / psycopg / Alembic | stores, migration | yes | 2.0.54 / 3.3.6 / 1.20.0 | - |
| Docker CLI | local PG | CLI yes (29.5.3), **daemon not running** | - | Start Docker Desktop; or a native PG 17 install |
| PostgreSQL server | all PG tests | **no** (no psql/postgres on PATH, `TEST_DATABASE_URL` unset) | CI: postgres:17.11-bookworm (digest-pinned) | CI service container; local throwaway container once Docker runs |
| GitHub Actions PG service | CI | yes (`ci.yml:31-46`) | 17.11 | - |
| Network access for web verification | Binance doc checks | yes (WebFetch worked) | - | - |

**Missing dependencies with no fallback:** none for authoring; PG-bound verification is blocked locally until a server is available (a plan Wave 0 task: "start PG and set TEST_DATABASE_URL", with a human-verify checkpoint if the machine cannot run Docker).
**Missing dependencies with fallback:** PostgreSQL locally (Docker Desktop restart, or rely on CI for PG-bound proofs while keeping pure/unit tests local).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + pytest-asyncio (auto mode); Ruff; mypy strict on `src` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`addopts = "-q"`, `testpaths = ["tests"]`, marker `docker`) |
| Quick run command | `uv run pytest tests/test_transitions.py tests/test_journal_ids.py tests/test_execution_manager.py -x -q` (pure/unit, no DB) |
| PG run command | `TEST_DATABASE_URL=postgresql+psycopg://<user>:<pw>@127.0.0.1:<port>/postgres uv run pytest tests/test_persistence_*.py tests/test_execution_exactly_once_pg.py -x -q -rs` |
| Full suite command | `uv run pytest -m "not docker" -rs -p no:cacheprovider` plus `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src` (the CI jobs `test`, `lint`, `types`) |

### Phase Requirements to Test Map (success criteria 1-5)

| Req / SC | Behavior | Test Type | Automated Command | File Exists? |
|----------|----------|-----------|-------------------|-------------|
| SC1 / DOMN-01 | Each store satisfies its Protocol; every mapper pair has a production caller and round-trips through real PG | integration (PG) + property | `uv run pytest tests/test_persistence_roundtrip_pg.py -x` | Wave 0 |
| SC1 | Protocol conformance without PG (structural) | unit | `uv run pytest tests/test_persistence_protocols.py -x` | Wave 0 |
| SC2 / DOMN-01, F-404 | Token-hash unique, one decided per plan (DB-level, also via concurrent threads), `client_order_id` unique, FK RESTRICT, CHECKs | integration (PG) | `uv run pytest tests/test_persistence_constraints_pg.py -x` | Wave 0 |
| SC2 / F-403 | Insert every enum member into every enum-typed column; widths; contract_type/status 17-19 char values | integration (PG) | `uv run pytest tests/test_persistence_enum_columns_pg.py -x` | Wave 0 |
| SC2 / F-411 | `compare_metadata` empty diff after `upgrade head`; partial-index predicates, CHECK defs, triggers asserted from catalogs | integration (PG) | `uv run pytest tests/test_persistence_migration_pg.py -k parity -x` | Wave 0 |
| SC2 / F-406 | Engine pins UTC; non-UTC session fails the assertion; rows read back UTC | integration (PG) | `uv run pytest tests/test_persistence_engine_pg.py -x` | Wave 0 |
| SC2 / F-410 | plan -> row -> plan -> same `plan_hash` over real planner outputs; precision guard refuses 19+ digits | integration (PG) + unit | `uv run pytest tests/test_plan_hash_roundtrip_pg.py tests/test_core_planner.py -x` | Wave 0 + update |
| SC2 / F-412 | Journal ids deterministic and collision-free; replay idempotent; append-only trigger rejects UPDATE/DELETE/TRUNCATE | unit + PG | `uv run pytest tests/test_journal_ids.py tests/test_persistence_journal_pg.py -x` | Wave 0 |
| SC2 / D-24 | `upgrade head`, `downgrade base`, `upgrade head`; 0003 -> 0004 with data | integration (PG) | `uv run pytest tests/test_persistence_migration_pg.py -k "cycle or data" -x` | Wave 0 |
| SC3 / EXEC-03, F-126, F-703 | Intent written before `place_entry` and between entry and SL (assert row state at the moment the fake adapter is called); crash after each step leaves a readable row and no second order | integration (PG) | `uv run pytest tests/test_execution_write_ahead_pg.py -x` | Wave 0 |
| SC4 / F-603 | Exactly one `place_entry` and one ENTRY row across double call, restart, fill-then-replay, cancel-then-replay, concurrent calls; negative control shows two entries | integration (PG) | `uv run pytest tests/test_execution_exactly_once_pg.py -x` | Wave 0 |
| SC3 / APRV-02 | Replayed APPROVED callback after restart reaches `place_entry` zero times | integration (PG) | `uv run pytest tests/test_approval_replay_pg.py -x` | Wave 0 |
| SC5 / F-606 | PG tests run on a disposable `_test` DB; fixture refuses non-`_test` names; missing URL fails under `TRADING_CI_STRICT=1` | unit + meta | `uv run pytest tests/test_pg_fixture_guard.py -x` | Wave 0 |
| EXEC-04 | Snapshot persisted per plan with canonical JSON + sha256; stale and `INCOMPLETE` snapshots invalid; reads `constraint_snapshot_ttl_seconds` | integration (PG) + unit | `uv run pytest tests/test_constraint_snapshot_pg.py -x` | Wave 0 |
| DOMN-04 | Tables unit-tested; every enum member has an entry; illegal transition raises through the repository inside the transaction; terminal-state DB rule | unit + PG | `uv run pytest tests/test_transitions.py tests/test_persistence_transitions_pg.py -x` | Wave 0 |
| F-606 restart | SAFE_MODE / enablement / kill-gate state persists and rehydrates on a fresh engine | integration (PG) | `uv run pytest tests/test_system_state_pg.py -x` | Wave 0 |
| D-27 | Decision alignment and docs gates stay green | existing | `uv run pytest tests/test_decision_alignment*.py tests/test_deploy_docs.py -q` | exists |

### Sampling Rate
- **Per task commit:** the pure/unit modules touched plus the single PG module for that task (PG module is skipped locally with a loud reason when no URL, and FAILS under `TRADING_CI_STRICT=1`).
- **Per wave merge:** full `-m "not docker"` suite with `TEST_DATABASE_URL` set, `ruff check`, `ruff format --check`, `mypy src`; read the `-rs` output and require ZERO skips from `tests/test_persistence_*` and `tests/test_execution_*_pg.py`.
- **Phase gate:** the same in CI (`TRADING_CI_STRICT=1`) green on the pushed branch before `/gsd-verify-work`. Add a canary test that, under `TRADING_CI_STRICT=1`, asserts `TEST_DATABASE_URL` is set and the PG server answers, so a misconfigured CI cannot pass vacuously.
- **Fail fast:** `-x` on every PG module; order PG tests so schema/constraint tests run before store tests.

### Wave 0 Gaps
- [ ] `tests/pg_support.py` (or conftest fixtures): `pg_server_url`, `pg_template`, `pg_db`, strict-skip via `infra_skip`; `tests/test_pg_fixture_guard.py`.
- [ ] `src/db/alembic/env.py` connection/logging seam (or documented subprocess runner) before parity tests.
- [ ] RED tests for parity, enum-columns, constraints, write-ahead, exactly-once, with the stateful fake and `SimulatedCrash` helper.
- [ ] Rebuild `tests/test_domain_mappers_pg.py` on the new fixtures (Pitfall 7).
- [ ] A way to run PG locally (Pitfall 15) or an explicit "verified in CI only" note per PG task.
- [ ] Framework install: none.

## Security Domain

### Applicable ASVS Categories (level 1, `security_enforcement: true`)

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2/V3 Authentication, Session | no (no new user-facing auth; chat/token gates already exist) | existing `authorized_chat_gate`, `verify_token_hash` |
| V4 Access Control | yes (authorization of who may consume an approval) | DB-level unique/FK constraints; chat gate unchanged; role separation deferred (Phase 26) |
| V5 Input Validation | yes | SQLAlchemy bound parameters only (no f-string SQL; the only dynamic SQL is the test-fixture database name, which is generated and validated against `^t17_[0-9a-f]+_test$`); domain constructors validate; enum CHECKs |
| V6 Cryptography | yes (hashing) | existing sha256 helpers; token stored only as hash; never hand-roll |
| V7 Error handling and logging | yes | never log DB URL or raw token; `render_as_string(hide_password=True)`; errors carry names and counts only (existing project convention) |
| V8 Data protection | yes | journal payloads must not carry raw tokens (existing T-8-13 rule); `approval_token_hash` is a hash |
| V10 Malicious code / integrity | yes | append-only triggers on `journal_events` and `system_state_events`; hash-bound plan identity |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Replay of a captured APPROVE callback causing a second entry | Tampering / Repudiation | Durable consume + PK on `(approval_id, role)` + unique client id (DB, not Python) |
| Race between two workers consuming one approval | Tampering | `ON CONFLICT DO NOTHING RETURNING` winner election; conditional UPDATE; partial unique decided index |
| Audit-trail tampering (UPDATE/DELETE of journal) | Repudiation | Append-only trigger (UPDATE, DELETE, TRUNCATE); deterministic ids with conflict-compare |
| Silent data loss through NUMERIC rounding or VARCHAR truncation | Tampering | Precision guard at store boundary; widths + insert-every-member test |
| Credential leakage via engine URL in logs/exceptions | Information disclosure | `hide_password`, existing redaction (`src/ops/redaction.py`), never `repr(url)` |
| Test fixture dropping a real database | Denial of service | Generated `t17_*_test` names only, `endswith("_test")` assertion, never `drop_all`, never touch the URL's own database |
| DB outage causing fail-open (in-memory fallback) | Elevation / DoS | Fail closed: store raises; manager returns NO_TRADE/SAFE_MODE; no retry loop on order path (D-04) |
| Restart clearing SAFE_MODE | Tampering | Persisted `system_state_events` + rehydrate on startup (C14) |

## Sources

### Primary (HIGH confidence)
- Repository files read this session (paths with line ranges cited inline): `src/db/models.py`, `src/db/mappers.py`, `src/db/alembic/env.py` and versions 0001-0003, `src/execution/manager.py`, `src/execution/order_ids.py`, `src/execution/enablement.py`, `src/execution/gates.py`, `src/approval/replay.py`, `binding.py`, `mapping.py`, `tokens.py`, `src/adapters/telegram_callbacks.py`, `analytics_store.py`, `binance_usdm.py`, `src/reconcile/safe_mode.py`, `sweeper.py`, `src/ops/drills.py`, `src/core/planner.py`, `src/core/_decimal.py`, `src/domain/*.py`, `src/data/metadata.py`, `src/backtest/costs.py`, `tests/conftest.py`, `tests/infra_helpers.py`, `tests/test_domain_mappers_pg.py`, `tests/test_execution_manager.py`, `.github/workflows/ci.yml`, `docker-compose.yml`, `deploy/migrate.sh`, `docs/GLOSSARY.md`, `docs/data/DATA_MODEL.md`, `docs/trading/EXECUTION_SPEC.md`, `docs/testing/TESTING_STRATEGY.md`, `docs/DECISIONS.md`, `docs/SOURCES.md`, `.planning/audits/2026-09-29-deep-audit/DEEP_AUDIT_REPORT.md` (F-126 section, finding rows).
- Installed library source read this session: Alembic 1.20.0 `ddl/postgresql.py:315-419`, `ddl/impl.py:610-640, 835-840`, `autogenerate/api.py:345-370`, `ext/checkconstraint_byname.py`, `runtime/plugins.py`.
- Offline experiments this session (project `.venv`): psycopg error sqlstates and `Diagnostic` attributes; `make_conninfo(options=...)`; SQLAlchemy partial-index DDL for PostgreSQL and SQLite (`postgresql_where`/`sqlite_where`); Decimal quantization behavior.
- PostgreSQL 17 docs (WebFetch): DROP DATABASE FORCE; template-database copy limitation; NUMERIC rounding/overflow.
- psycopg 3 docs (WebFetch): timestamptz returned in the connection TimeZone.

### Secondary (MEDIUM confidence)
- Binance official docs via WebFetch (summaries by a small model, not raw text): New Order `newClientOrderId`; New Algo Order `clientAlgoId`; Error Code `-4116 DUPLICATED_CLIENT_ORDER_ID`; Query Order "orders not found" rules (3 days / 90 days). Change-log date for -4116 (2024-12-03) from a search-result summary only.
- Alembic autogenerate docs (WebFetch): what autogenerate detects; CHECK constraints need the opt-in named-constraint plugin.

### Tertiary (LOW confidence)
- Items tagged `[ASSUMED]` in the Assumptions Log (A1-A11).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH, nothing new; versions read from the live environment.
- Architecture: HIGH for insertion points and constraint design (read the code); MEDIUM for PG runtime behavior that could not be executed locally.
- Pitfalls: HIGH for code-evidenced items (C1-C20, Pitfalls 4-9, 14); MEDIUM for PG-semantics items (1, 11).
- Transitions: LOW until confirmed (A1).

**Research date:** 2026-10-01
**Valid until:** ~2026-10-31 (stable libraries; re-check Binance docs before Phase 18/19 and any change to the 3-day/90-day order-lookup retention)
