# Phase 3: Domain + Registry + Fixtures - Context

**Gathered:** 2026-09-22
**Status:** Ready for planning

## Phase Boundary

Phase 3 delivers reproducibility plumbing: seven domain entities (Signal, TradePlan, Approval, Order, Fill, Position, JournalEvent) persisted separately with GLOSSARY-canonical enums and no nullable-column state inference, a versioned parameter registry so every backtest/paper/alert/order plan carries its immutable identity (strategyVersion + parameterSetId + parameterSetHash + experiment linkage), and a golden-fixture harness plus determinism suites (no-lookahead, prefix-invariance, candle-close-timing, boundary) passing in CI with unregistered semantic changes rejected. No strategy logic, no indicators, no sizing math — this phase produces the types, registry, and harness that Phase 4 (Pure Core) will fill with behavior. Success means new behavior must be expressible as a versioned set before it exists, and every decision is traceable to data plus spec version.

## Implementation Decisions

### Domain entity shape

- **D-01:** Seven entities live as frozen pure-Python dataclasses in a new `src/domain/` package (e.g. `src/domain/signal.py`, `trade_plan.py`, `approval.py`, `order.py`, `fill.py`, `position.py`, `journal.py`, plus `enums.py`, `ids.py`). The strategy core imports NOTHING from SQLAlchemy, Pydantic, Polars, or the Binance SDK — dependency-free domain keeps Phase 4 pure functions testable without a DB. — **Reversibility:** costly — every downstream consumer (core, risk, backtest, paper) imports these types; renaming/reshaping touches all readers.
- **D-02:** PostgreSQL tables mirror the domain 1:1 via a separate ORM layer in `src/db/` (new models + one reviewed Alembic migration, same single-Base + parity-gate discipline as Phase 2). Thin mapper functions (`src/db/mappers.py` or per-entity `to_row`/`from_row`) translate domain ↔ row; no ORM class IS the domain model. — **Reversibility:** one-way — once Phases 4–7 persist through these tables, reshaping needs a data migration.
- **D-03:** Deterministic IDs are content hashes, not sequences: `SignalId` = hash(strategyVersion + parameterSetId + symbol + source_timeframe + source_candle_close_utc + setup fingerprint); plan/order IDs derive from their parent signal hash plus a fixed discriminator. No auto-increment PKs anywhere in the seven entities. — **Reversibility:** one-way — IDs are stored in journal/experiment records forever.

### Parameter registry mechanics

- **D-04:** File-based registry is the source of truth: versioned TOML files under `params/` (e.g. `params/<strategy_id>/<parameter_set_id>.toml`), git-tracked and immutable once used. Identity = `parameterSetId` (human name) + `parameterSetHash` (SHA256 over canonical JSON with sorted keys, UTF-8, no whitespace variance). A loader (`src/domain/registry.py`) parses, validates against a schema version, computes the hash, and raises (fail-closed) on any unregistered or mutated set — never a silent fallback. — **Reversibility:** one-way — published backtests and approved plans reference hashes permanently.
- **D-05:** Enforcement is BOTH loader exception AND CI gate (Phase 1 D-07 "rejected by gate, not by convention"): any run path (backtest, paper signal, alert, order plan) without a registered `parameterSetId` + matching hash fails closed; a CI check plus negative test proves the rejection. A DB table may mirror registry rows for experiment-join queryability later, but files remain canonical in Phase 3. — **Reversibility:** reversible — adding a DB mirror later does not break the file contract.
- **D-06:** Strict split per CONFIGURATION.md: strategy parameters (lookbacks, tolerances, buffers, RR minima, risk rates) live ONLY in the registry; runtime config (endpoints, tokens, DB refs, log levels, poll intervals) lives in env/secret stores and must never silently alter strategy semantics. The loader rejects unknown strategy-semantic keys found outside the registry. — **Reversibility:** reversible — classification refinements are additive.

### Fixture harness scope

- **D-07:** Golden fixtures live under `tests/fixtures/phase3/` (or `tests/fixtures/golden/`): `candles.csv` (hand-built, boundary-covering bars) + `parameters.json` (pinned registry set) + `expected_signals.json` / `expected_plans.json` (byte-exact expectations). Layout and file names are the planner's discretion, but the triple (input candles + parameters → expected outputs) is mandatory. — **Reversibility:** reversible — fixtures grow per family in Phase 4 without breaking the harness.
- **D-08:** Four determinism suites land in Phase 3 as CI-blocking tests: (a) no-lookahead (shifting input window never changes earlier outputs), (b) prefix-invariance (same prefix → byte-identical prefix outputs), (c) candle-close-timing (no signal before its source candle closes), (d) boundary (empty input, single bar, warm-up-insufficient → explicit invalid, never crash). Any unregistered semantic change to domain outputs fails CI. — **Reversibility:** reversible — suites only grow.
- **D-09:** Harness in Phase 3 proves the MECHANISM with minimal placeholder expectations (registry round-trip + suite scaffolding over empty/minimal domain); real family expectations populate in Phase 4. No strategy family is specified or favored here — all three remain hypotheses. — **Reversibility:** reversible — placeholders are replaced, not migrated.

### Enum + lifecycle discipline

- **D-10:** GLOSSARY-canonical Python `Enum` classes in `src/domain/enums.py` (one enum per lifecycle: SignalStatus, TradePlanStatus, ApprovalStatus, OrderStatus, etc., mirroring GLOSSARY names exactly after Phase-1 C2/C3/C7 resolutions). No stringly-typed statuses; no invented names — an unknown status is a load-time error. — **Reversibility:** costly — enum names appear in stored rows, fixtures, and Telegram payloads.
- **D-11:** Explicit status columns on every entity — state is NEVER inferred from nullable columns (e.g. "approved iff approved_at non-null" is forbidden). Lifecycles use explicit `status` + explicit timestamp columns (`expires_at_utc`, `invalidated_at_utc`, decided/approved/filled at) where a NULL timestamp means "transition never happened" and `status` alone answers "what state". — **Reversibility:** one-way — rows written under this rule are read by journal analytics forever.
- **D-12:** Money/qty/price fields reuse the Phase-2 Decimal-only invariant (`Decimal` in domain, `NUMERIC(38,18)` in rows, AST no-`float(` guards in tests); UTC `datetime` internally with `Asia/Ho_Chi_Minh` only at display edges. — **Reversibility:** reversible — invariant already enforced, extended to new files.

### the agent's Discretion

- User delegated all four areas ("mode --auto chọn recommend best option giúp tôi; tôi không có kiến thức về phần này") and confirmed the recommended bundle in one gate. Exact file layout inside `src/domain/`, TOML schema details, hash input canonicalization edge cases, fixture CSV column order, suite helper design, and plan slicing are at the planner/researcher discretion, provided D-01–D-12 semantics hold.
- Whether the registry DB mirror lands in Phase 3 or a later phase is at the planner's discretion (files are canonical either way).

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Domain contract

- `docs/data/DATA_MODEL.md` — canonical persistence contract: seven entities, field lists, Signal ≠ TradePlan ≠ Approval ≠ Order ≠ Fill ≠ Position separation rule; Phase 3 implements it.
- `docs/GLOSSARY.md` — canonical enums and terminology; authority for D-10 naming (post Phase-1 C2/C3/C5/C7 resolutions).
- `docs/DECISIONS.md` — D001–D021 plus Phase-1 D022–D028; determinism, quantization, and approval-safety decisions bind this phase.

### Registry contract

- `docs/configuration/CONFIGURATION.md` — parameter-set identity (parameterSetId + parameterSetHash), runtime-vs-strategy split, immutability of frozen sets; Phase 3 builds it.
- `docs/research/RESEARCH_PROTOCOL.md` — FROZEN v1.0.0; acceptance gates the fixture suites must encode; "rejected by gate" semantics for D-05.
- `docs/backtest/BACKTEST_SPEC.md` — experiment identity (dataset + strategy + parameter + cost + execution versions) the registry must support.

### Methodology + platform

- `docs/01_ENGINEERING_PRINCIPLES.md` — determinism + fail-closed posture; Decimal-only and UTC-at-boundary rules extended by D-12.
- `docs/TECHNOLOGY_STACK.md` — Python 3.13 + uv; Pydantic v2 reserved for boundaries (NOT the domain core); pytest-asyncio auto mode; Ruff + mypy strict on `src/`.
- `docs/implementation/AGENT_INSTRUCTIONS.md` — Research → Spec → Code separation; missing rules stay TBD, agents must not invent production behavior.

### Project context

- `.planning/PROJECT.md` — project context, constraints, key decisions.
- `.planning/REQUIREMENTS.md` — DOMN-01, DOMN-02, DOMN-03.
- `.planning/ROADMAP.md` — Phase 3 goal and success criteria.
- `.planning/phases/01-research-formalization/01-CONTEXT.md` — Phase 1 locks (registry + CI gate D-07, frozen protocol location) this phase implements.
- `.planning/phases/02-data-foundation/02-CONTEXT.md` — Phase 2 locks (D-04 Hive layout, D-05 PG/Parquet split, versioned metadata, gap journal) this phase builds on.

## Existing Code Insights

### Reusable Assets

- `src/db/models.py` (single declarative Base, `make_engine`/`make_session_factory`/`session_scope`, TIMESTAMPTZ + NUMERIC(38,18) convention) — extend with 7 new tables + mappers; do NOT reuse ORM classes as domain types.
- `src/db/alembic/versions/0001_baseline.py` + `scripts/check_migration_parity.py` — migration + offline parity-gate pattern for the new domain migration.
- `tests/conftest.py` (golden-fixture loaders, frozen-clock helper) + `tests/test_metadata.py::CapturingSession` pattern — reuse for registry/fixture tests under SQLite (document PG-vs-SQLite boundaries as before).
- AST `no-float(` static guards (`test_metadata.py`, `test_coverage.py`, `test_backup.py`) — extend to `src/domain/` + new registry code.
- `src/adapters/binance_usdm.py` adapter-boundary isolation (sole SDK importer, frozen dataclasses with Decimal + UTC) — the precedent D-01 follows for the domain boundary.

### Established Patterns

- TDD RED→GREEN per behavior with atomic commits; frozen dataclasses; INSERT-only versioning; fail-closed loader/quality posture; structured lineage logging.
- Determinism and UTC/HCMC discipline from Phase 2 (D-06); determinism suites in D-08 formalize it for the domain.

### Integration Points

- New `src/domain/` package (pure, dependency-free) + `src/db/` extension (7 tables + mappers + migration 0002).
- New `params/` file registry + `src/domain/registry.py` loader; CI gate + negative test (extends Phase-1 gate story).
- New `tests/fixtures/phase3/` golden files + 4 determinism suites (extend `tests/` TDD layout).
- Phase 4 consumes domain types + registry + harness to implement features/strategy/planner; Phase 5 consumes registry identity for risk parity; Phase 6 consumes fixtures + suites for the backtest engine.

## Specific Ideas

- User delegated implementation choices to the agent (Vietnamese: "mode --auto chọn recommend best option giúp tôi. tôi không có kiến thức về phần này") and confirmed the four-area recommended bundle in a single confirmation gate — same delegation pattern as Phase 2.
- No "I want it like X" references — open to standard approaches within the locked decisions above.

## Deferred Ideas

None — discussion stayed within phase scope. Strategy family behavior (Phase 4), sizing math (Phase 5), backtest engine (Phase 6), and registry DB mirror timing remain scheduled in their own phases.

---

*Phase: 3-Domain + Registry + Fixtures*
*Context gathered: 2026-09-22*
