# Phase 3: Domain + Registry + Fixtures - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-22
**Phase:** 3-Domain + Registry + Fixtures
**Areas discussed:** Domain entity shape, Registry mechanics, Fixture harness scope, Enum + lifecycle discipline

---

## Area selection

| Option | Description | Selected |
|--------|-------------|----------|
| Domain entity shape | Pure dataclasses vs ORM vs Pydantic; new src/domain/; PG mirror 1:1 | ✓ |
| Registry mechanics | File vs DB registry; hash + canonical JSON; freeze enforcement | ✓ |
| Fixture harness scope | Golden files layout; which determinism suites; CI blocking | ✓ |
| Enum + lifecycle discipline | GLOSSARY Enums; explicit status columns; expires/invalidated | ✓ |

**User's choice:** all + auto mode ("mode --auto chọn recommend best option giúp tôi. tôi không có kiến thức về phần này")
**Notes:** User delegated all areas to recommended defaults (same pattern as Phase 2). Single-bundle confirmation gate used instead of 16-question default flow, per user instruction precedence over default mode.

---

## Recommended bundle confirmation

| Option | Description | Selected |
|--------|-------------|----------|
| Confirm bundle | Frozen dataclasses in src/domain/; file-based TOML registry + SHA256; golden fixtures + 4 suites CI-blocking; GLOSSARY Enums + explicit status | ✓ |
| Tweak domain shape | Change where entities live or what they are built from | |
| Tweak registry | Change file-vs-DB, hash, or freeze enforcement | |
| Tweak fixtures | Change fixture layout or determinism suite scope | |
| Tweak enums | Change enum or status/lifecycle representation | |

**User's choice:** Confirm bundle
**Notes:** No tweaks requested.

---

## Alternatives considered (not selected, for audit)

- **SQLAlchemy ORM as the domain model** — rejected: couples pure strategy core to DB driver, violates Phase-4 pure-function needs and the adapter-isolation precedent.
- **Pydantic v2 as the domain core** — rejected for hot path: Pydantic reserved for I/O boundaries per TECHNOLOGY_STACK; plain frozen dataclasses keep the core dependency-free.
- **DB-table-only registry** — rejected as canonical: worse auditability/reviewability than git-tracked files; DB mirror allowed later as a query convenience only.
- **Loader warning instead of exception** — rejected: violates fail-closed + Phase-1 D-07 gate semantics; unregistered sets must raise and CI must block.
- **Stringly-typed statuses / nullable-inferred state** — rejected: violates DOMN-01 "no state inferred from nullable columns"; explicit status + timestamp columns required.

---

## the agent's Discretion

- All four areas delegated to the agent; exact file layout, TOML schema, hash canonicalization edges, fixture column order, suite helpers, and plan slicing at planner/researcher discretion within D-01–D-12.
- Registry DB mirror timing (Phase 3 vs later) at planner's discretion.

## Deferred Ideas

None — discussion stayed within phase scope.
