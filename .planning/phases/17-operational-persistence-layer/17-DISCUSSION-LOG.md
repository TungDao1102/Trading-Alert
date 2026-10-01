# Phase 17: Operational Persistence Layer - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-10-01
**Phase:** 17-operational-persistence-layer
**Areas discussed:** Store architecture, Schema integrity, Durable approval consumption and write-ahead intent, Constraint snapshot persistence, State-transition validation, Other durable state, Test strategy and CI, Documentation

**Mode:** `--auto` — every question resolved by the recommended default, no interactive prompts. The user may override any D-number before planning.

---

## Store architecture

| Option | Description | Selected |
|--------|-------------|----------|
| Sync SQLAlchemy repositories behind existing Protocols | Matches current synchronous Protocol surfaces; wrap in to_thread at composition | ✓ |
| Async repositories now | Matches asyncio runtime but changes every Protocol and caller | |

**Auto-selected:** sync repositories (recommended default). Transactions are caller-owned unit-of-work; UTC pinned per connection; fail closed on DB loss.

---

## Durable approval consumption and write-ahead intent

| Option | Description | Selected |
|--------|-------------|----------|
| `execution_intents` table keyed (approval_id, role), consume in same transaction | DB constraint makes a second entry impossible; no reliance on exchange dedup | ✓ |
| Rely on exchange clientOrderId dedup | Rejected: Binance dedups only among open orders (audit F-126/F-951) | |
| In-process lock only | Rejected: lost on restart, per-process | |

**Auto-selected:** intents table with write-ahead order; unresolved intents after restart are UNKNOWN, resolved by querying the exchange, fail closed otherwise.

---

## Schema integrity

| Option | Description | Selected |
|--------|-------------|----------|
| One hand-written migration `0004` with unique/FK/CHECK/width fixes, append-only journal, full autogenerate-diff parity test | Closes F-404/403/411/412 | ✓ |
| Fix via `create_all` in tests | Rejected: migrations never run (F-606) | |

**Auto-selected:** migration 0004; CHECKs generated from Python enums; widths proven by inserting every enum member.

---

## Test strategy and CI

| Option | Description | Selected |
|--------|-------------|----------|
| Disposable `_test` DB built by `alembic upgrade head`; PG skip is a hard failure in CI | Reuses Phase 13.1 service container | ✓ |
| Keep optional `TEST_DATABASE_URL` skip | Rejected: tests silently stop running | |

---

## Claude's Discretion

- Module names inside `src/persistence/`, ORM vs Core for hot paths, CHECK generation and append-only mechanisms, concrete widths, staleness max-age source, plan/wave split.

## Deferred Ideas

- Async repositories/pooling, SAFE_MODE exit rules (20), live equity/margin/leverage values (21-22), symbol/side/qty binding (19), DB roles/RLS (26), journal retention.
