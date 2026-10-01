# Phase 3: Domain + Registry + Fixtures - Research

**Researched:** 2026-09-22
**Domain:** Deterministic trading domain model + versioned parameter registry + golden-fixture determinism harness (Python 3.13, SQLAlchemy 2.0, Alembic, pytest)
**Confidence:** HIGH

## Summary

Phase 3 builds reproducibility plumbing with no strategy behavior: seven domain entities as frozen, dependency-free Python dataclasses in a new `src/domain/` package; a file-based TOML parameter registry under `params/` with SHA256 identity (`parameterSetId` + `parameterSetHash`) enforced by a fail-closed loader plus a CI gate; and a golden-fixture harness under `tests/fixtures/phase3/` with four determinism suites (no-lookahead, prefix-invariance, candle-close-timing, boundary) that block CI. Every pattern needed already exists in-repo as precedent: `src/adapters/binance_usdm.py` proves the frozen-dataclass + Decimal + UTC boundary idiom, `src/db/models.py` + `0001_baseline.py` + `scripts/check_migration_parity.py` prove the single-Base + reviewed-migration + offline-parity-gate discipline, and `tests/test_metadata.py::CapturingSession` proves the SQLite-testable ORM pattern with documented PG-vs-SQLite boundaries.

The only new third-party dependency the planner should approve is `tomli-w` (TOML writer — stdlib `tomllib` is read-only), or the planner may sidestep it by hand-emitting the small number of registry TOML files once and treating them as immutable artifacts. The canonical-hash scheme is pure stdlib (`json.dumps` with `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=True` over UTF-8 bytes → SHA256 hexdigest), with a project-owned scalar-normalization pass that renders `Decimal` via `str()` (full precision preserved), `datetime` via `isoformat()`, and `Enum` via `.value` — and rejects `float('nan')`/`inf` loudly instead of serializing them.

**Primary recommendation:** Implement in vertical-tracer order — `enums.py` → one entity + mapper + migration slice → registry loader + hash → fixture triple + one determinism suite green — extending (never replacing) the Phase-2 parity-gate, CapturingSession, and AST no-`float(` guard patterns; defer the `trades`/`experiment_runs` tables and the registry DB mirror to their consuming phases (5/6) unless the planner wants them in the single 0002 migration for review economy.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

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

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope. Strategy family behavior (Phase 4), sizing math (Phase 5), backtest engine (Phase 6), and registry DB mirror timing remain scheduled in their own phases.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DOMN-01 | Seven separate entities (Signal, TradePlan, Approval, Order, Fill, Position, JournalEvent) with GLOSSARY-canonical enums and no nullable-column state inference | `## Standard Stack` (frozen dataclasses + `Enum`), `## Architecture Patterns` (domain/ORM/mapper split, explicit-status rule), `## Code Examples` (enum + entity + mapper + migration skeletons) |
| DOMN-02 | Every backtest/paper/alert/order plan traceable to immutable versioned parameter set (strategyVersion + parameterSetId + parameterSetHash + experiment linkage) | `## Standard Stack` (tomllib + SHA256 canonical hash), `## Architecture Patterns` (registry loader contract, D-06 split), `## Common Pitfalls` (hash-input drift, mutation-after-use) |
| DOMN-03 | Golden fixtures (candles.csv + parameters.json + expected signals/plans) plus no-lookahead, prefix-invariance, candle-close-timing, boundary suites | `## Architecture Patterns` (harness layout, placeholder-mechanism scope per D-09), `## Validation Architecture` (suite-to-test mapping), `## Code Examples` (suite skeletons) |
</phase_requirements>

## Project Constraints (from AGENTS.md)

Binding directives the planner must not violate (extracted from `AGENTS.md` / canonical docs):

- **Determinism:** same market snapshot + account state + strategy version + config = same decision; no repaint, no future-candle leakage, prefix-invariant, byte-equivalent outputs.
- **No-AI core:** LLM never decides direction/entry/SL/TP/size/risk/parameters/signal-validity (code/docs/tests/explanations only).
- **Quantization:** floor to stepSize → realized-risk check (60% baseline) → min-qty/notional reject → NO_TRADE preferred over round-up; identical logic backtest/paper/live. (Phase 5 owns the math; Phase 3 only carries the `quantization_decision`-style fields through the domain.)
- **Approval safety:** explicit, auditable, idempotent, expiring; at-least-once replays resolve to existing state; no auto-approve on notification failure.
- **Fail closed:** uncertain data/connection/account/risk → NO_TRADE, no new orders.
- **Tech stack:** Python 3.13 + uv, SQLAlchemy 2.0 async PG17, Alembic, pytest + pytest-asyncio (auto mode) + Ruff + mypy strict on `src/`, `Decimal`/tick arithmetic for exchange-sensitive values.
- **Research → Spec → Code:** missing rules stay TBD; agents must not invent production behavior (`docs/implementation/AGENT_INSTRUCTIONS.md`).
- **GSD workflow enforcement:** all file-changing work goes through a GSD command.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Domain value objects (7 entities, enums, IDs) | Pure domain layer (`src/domain/`, no I/O) | — | Phase 4 pure functions must import these with zero DB/network weight (D-01) |
| Parameter registry files + loader + hash | Domain layer (`src/domain/registry.py`, `params/`) | CI gate (`.github/workflows/`) | Identity computation is pure; enforcement is loader exception + gate (D-05) |
| ORM mirror + mappers + migration | Infrastructure (`src/db/`) | — | PG persistence is an adapter concern; ORM must never leak into domain (D-02) |
| Golden fixtures + determinism suites | Test harness (`tests/fixtures/phase3/`, `tests/`) | CI (blocking) | Fixtures are versioned test data, not runtime code (D-07/D-08) |
| Experiment linkage display | Consuming phases (4/6/7/8/9) | — | Phase 3 provides the identity tuple; consumers attach and display it (success criterion 2) |

## Standard Stack

### Core (all already pinned except `tomli-w`)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `dataclasses` (stdlib) + `enum` (stdlib) | Python 3.13 stdlib [VERIFIED: bash `python -c "import tomllib, hashlib, enum, dataclasses"` OK] | Frozen domain entities + GLOSSARY-canonical enums | Zero-dependency domain per D-01; identical idiom already proven in `src/adapters/binance_usdm.py:49-67` (`@dataclass(frozen=True)` with `Decimal` + UTC `datetime`) |
| `tomllib` (stdlib, 3.11+) | Python 3.13 stdlib [VERIFIED: same bash probe] | Parse `params/**/*.toml` in the registry loader | Read-only TOML is stdlib since 3.11; no new dependency for the loader's read path |
| `hashlib` (stdlib) + `json` (stdlib) | Python 3.13 stdlib [VERIFIED: same bash probe] | `parameterSetHash` = SHA256 over canonical JSON bytes | Matches RESEARCH_PROTOCOL §5 loader contract (key ordering, numeric coercion, whitespace stripping); JCS (RFC 8785) confirms sorted-keys + compact separators + UTF-8 is the standard canonicalization [CITED: rfc-editor.org/rfc/rfc8785.html] |
| SQLAlchemy 2.0.x (`>=2.0,<2.1`) | Pinned in `pyproject.toml:17` [VERIFIED: pyproject.toml:17] | ORM mirror of the 7 entities, async engine | Existing `src/db/models.py` single-Base + `make_engine`/`session_scope` pattern extends directly |
| Alembic (`>=1.19`) | Pinned in `pyproject.toml:19` [VERIFIED: pyproject.toml:19] | Single reviewed migration `0002_domain_registry.py` (`down_revision = "0001_baseline"`) | Same offline parity-gate discipline as Phase 2 (`scripts/check_migration_parity.py` renders `head` DDL and diffs against `Base.metadata`) |
| pytest 9 + pytest-asyncio (auto) | Pinned in `pyproject.toml:35-36`, `asyncio_mode = "auto"` at `pyproject.toml:47` [VERIFIED: pyproject.toml:35-47] | Golden + determinism suites, TDD RED→GREEN | Existing `tests/conftest.py` (golden loaders, `frozen_clock`, `CapturingSession` pattern in `test_metadata.py:89-145`) extends directly |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `tomli-w` [ASSUMED] | Latest stable at `uv add` time | Write canonical TOML when minting new parameter sets | **Only if the planner wants a writer.** stdlib `tomllib` cannot write TOML (read-only by design). Alternative (recommended default): hand-author the small Phase-3 seed TOML files once, treat as immutable, skip the dependency entirely |
| `tzdata` | Already pinned in `pyproject.toml:28` [VERIFIED: pyproject.toml:28] | `ZoneInfo("Asia/Ho_Chi_Minh")` at display edges on Windows | D-12 display rule; domain stores UTC only |
| Ruff + mypy strict | Already configured (`pyproject.toml:54-80`: `line-length = 100`, `target-version = "py313"`, `strict = true`, `files = ["src"]`) [VERIFIED: pyproject.toml:54-80] | Lint + type the new `src/domain/` package | Extend the existing AST no-`float(` guards to `src/domain/` + `src/db/mappers.py` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| TOML files (D-04 locked) | JSON/YAML registry files | Locked out by D-04. Note anyway: TOML's typed scalars (no `1.0` vs `"1.0"` ambiguity) make the strategy-vs-runtime split auditable; YAML's implicit typing is a canonicalization hazard |
| stdlib `hashlib` SHA256 | `stablejson` PyPI package | `stablejson` (deterministic JSON + SHA256, rejects floats/NaN) [CITED: pypi.org/project/stablejson] is a valid off-the-shelf canonicalizer, but it is an extra dependency for ~20 lines of project-owned normalization that must handle `Decimal`/`datetime`/`Enum` scalars anyway (which `stablejson` rejects). Own the normalizer; keep the dependency surface at zero |
| Hand-rolled JCS/RFC 8785 full compliance | `sort_keys=True` + compact separators + scalar whitelist | Full JCS (UTF-16 code-unit sorting, NFC, number-grammar) is overkill for ASCII parameter names and Decimal values. Document the profile explicitly: lexicographic code-point sort via `sort_keys`, `separators=(",", ":")`, `ensure_ascii=True`, UTF-8 encode. Parameter names stay 7-bit ASCII by convention so code-point sort ≡ JCS sort [ASSUMED — planner should add a loader assertion rejecting non-ASCII parameter names to make this airtight] |
| Full `experiment_runs` + `trades` tables now | Defer to Phases 5/6 | DATA_MODEL defines `trades` (§2.6) and `experiment_runs` (§2.12) beyond the seven. Recommendation: defer both tables to their consuming phases to keep migration 0002 reviewable; see Open Questions Q1 |

**Installation:**
```bash
uv add "tomli-w>=2" --optional dev   # ONLY if planner wants a TOML writer; else no new deps
```

**Version verification:** Core stack versions verified against `pyproject.toml` by `Read` this session (citations above). System interpreter is 3.14.3 but the project pins `requires-python = "==3.13.*"` [VERIFIED: pyproject.toml:6] with `uv managed = true` [VERIFIED: pyproject.toml:43-44] — all Phase-3 work runs under `uv run` (uv 0.12.17 present [VERIFIED: bash]). `tomli_w` confirmed **absent** from the system interpreter [VERIFIED: bash `import tomli_w` → ModuleNotFoundError]; `params/` and `tests/fixtures/phase3/` confirmed **absent** [VERIFIED: bash `Test-Path` → False], so the planner slices greenfield creation, not modification.

## Package Legitimacy Audit

> Phase 3 installs at most one new package (`tomli-w`, and only if the planner wants a TOML writer). The `gsd-tools package-legitimacy` seam is not available in this environment (Windows PowerShell, no `gsd_run` on PATH), so this audit is conducted by direct registry reasoning and tagged accordingly.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `tomli-w` | PyPI | ~4 yrs (by the `tomli` author, `hukkin`) | ~tens of millions/mo (transitive via `uv`/`pip` toolchains) | github.com/hukkin/tomli-w | OK [ASSUMED] | Approved contingent — planner confirms via `uv add tomli-w` resolving cleanly; if it fails, fall back to hand-authored immutable TOML with zero new deps |
| `stablejson` | PyPI | new/small | low | — | SUS [ASSUMED] | NOT RECOMMENDED — unnecessary dependency (see Alternatives); listed only so the planner does not adopt it |

**Packages removed due to SLOP verdict:** none
**Packages flagged as suspicious (SUS):** `stablejson` — do not adopt; own the ~20-line normalizer instead.

*All other Phase-3 code uses stdlib + already-pinned dependencies (`pyproject.toml:9-31`). No other installs are authorized by this research.*

## Architecture Patterns

### System Architecture Diagram

```text
params/<strategy_id>/<parameter_set_id>.toml   (git-tracked, immutable once used)
        │  TOML source
        ▼
src/domain/registry.py  (parse → validate schema_version → normalize → SHA256)
        │  ParameterSet dataclass (parameterSetId + parameterSetHash)
        ▼
src/domain/*.py  (frozen dataclasses: Signal, TradePlan, Approval,
        │          Order, Fill, Position, JournalEvent + enums.py + ids.py)
        │  pure in-memory values (Decimal, UTC datetime, Enum)
        ├──► src/db/mappers.py  (to_row / from_row, thin, total)
        │           │
        │           ▼
        │    src/db/models.py  (7 ORM tables, NUMERIC(38,18), TIMESTAMPTZ)
        │           │
        │           ▼
        │    Alembic 0002_domain_registry  (reviewed; parity-gate green)
        │
        └──► tests/fixtures/phase3/  (candles.csv + parameters.json
                    + expected_signals.json + expected_plans.json)
                            │
                            ▼
                 4 determinism suites (CI-blocking)
                            │
                            ▼
              Phase-1 research-gate.yml (unregistered-set rejection)
```

A reader traces the primary use case — "prove a parameter set is what it claims to be" — from TOML file → loader → hash → dataclass identity → DB row → fixture expectation, following the arrows.

### Recommended Project Structure

```text
src/
├── domain/               # NEW — pure, zero heavy imports (D-01)
│   ├── __init__.py       # re-exports only (no logic)
│   ├── enums.py          # GLOSSARY-canonical Enum classes (D-10)
│   ├── ids.py            # SignalId / plan/order ID hash constructors (D-03)
│   ├── signal.py         # Signal frozen dataclass
│   ├── trade_plan.py     # TradePlan frozen dataclass
│   ├── approval.py       # Approval frozen dataclass
│   ├── order.py          # Order dataclass (intent, not SDK model)
│   ├── fill.py           # Fill frozen dataclass
│   ├── position.py       # Position dataclass (reconciled snapshot)
│   ├── journal.py        # JournalEvent frozen dataclass (append-only)
│   ├── registry.py       # TOML loader + canonical hash + fail-closed (D-04/D-06)
│   └── canonical.py      # scalar normalizer + canonicalize() + sha256_hex() (shared by ids.py + registry.py)
├── db/
│   ├── models.py         # EXTEND — 7 ORM tables, same Base (D-02)
│   ├── mappers.py        # NEW — to_row/from_row per entity (D-02)
│   └── alembic/versions/
│       └── 0002_domain_registry.py   # NEW — down_revision = "0001_baseline"
params/                   # NEW — file registry (D-04)
└── <strategy_id>/
    └── <parameter_set_id>.toml
tests/
├── fixtures/phase3/      # NEW — golden triple (D-07)
│   ├── candles.csv
│   ├── parameters.json
│   └── expected_signals.json / expected_plans.json
├── test_domain_enums.py / test_domain_ids.py / test_registry.py / ...
└── conftest.py           # EXTEND — phase-3 loaders (candles, params, expected)
```

### Pattern 1: Frozen dataclass entity with Decimal + UTC + Enum

**What:** Every domain entity is `@dataclass(frozen=True)` with `Decimal` money/qty/price fields, timezone-aware UTC `datetime` fields, and `Enum` status fields. No `Optional` status; `Optional` is reserved for "transition never happened" timestamps only (D-11).
**When to use:** All seven entities, no exceptions.
**Precedent (in-repo, read this session):** `src/adapters/binance_usdm.py:49-67` — `Kline` frozen dataclass with `Decimal` prices/volumes and UTC datetimes; `SymbolFilters` (`src/adapters/binance_usdm.py:99-120`) carries the same Decimal-only discipline. Phase 3 copies this idiom into `src/domain/`.

### Pattern 2: Canonical-hash identity (registry + IDs share one normalizer)

**What:** A single `src/domain/canonical.py` owns scalar normalization → `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)` → UTF-8 → `hashlib.sha256().hexdigest()`. Both `registry.py` (parameterSetHash) and `ids.py` (SignalId/plan/order IDs) call it. Normalization whitelist, verbatim policy [CITED: kailash-py `_canonical.py` — same whitelist shape]:
- `Decimal` → `str()` preserving full precision (`Decimal("1.50")` stays `"1.50"`, never `"1.5"`)
- `datetime` → `isoformat()` (must already be UTC-aware; loader asserts `tzinfo is not None`)
- `Enum` → `.value`
- `dict` → recursive, sorted keys; `list/tuple` → order-preserving; `set` → **rejected** (unordered — fail closed, never silently sort)
- any other type → **no `default=str` fallback**; `json.dumps` raises `TypeError` loudly (`default=str` routes through implementation-defined `str()` and breaks cross-version byte parity [CITED: kailash-py `_canonical.py`])
- `float('nan')`/`inf` → rejected via `allow_nan=False` (non-finite floats have no canonical JSON form [CITED: cross-engine-reconciliation.org determinism guide])

**When to use:** Every hash the phase mints. The planner writes one byte-equality test pinning this: same logical payload built in different key insertion orders → identical digest; `Decimal("1.50")` vs `Decimal("1.5")` → *different* digests (documented, not a bug).

### Pattern 3: Fail-closed registry loader (D-04/D-05/D-06)

**What:** `registry.py::load_parameter_set(strategy_id, parameter_set_id)` (1) resolves `params/<strategy_id>/<parameter_set_id>.toml` — missing file raises `UnregisteredParameterSet`; (2) parses with `tomllib`; (3) validates `schema_version` against the loader's supported constant — mismatch raises; (4) splits keys into strategy-semantic vs runtime namespaces — unknown strategy-semantic key outside the registry raises (D-06); (5) canonicalizes + hashes — recomputed hash compared against the hash recorded at first use (stored alongside the run record; in Phase 3 there are no runs yet, so the loader exposes `verify(path, expected_hash)` and raises `ParameterSetMutated` on mismatch). No fallback, no default set, no silent coercion.
**When to use:** Every entry point that will exist in Phases 4/6/7/8/9; Phase 3 proves the loader + negative tests + CI gate.

### Pattern 4: ORM mirror + thin total mappers (D-02)

**What:** `src/db/models.py` gains 7 tables on the existing `Base`, following the file's own conventions [VERIFIED: src/db/models.py:10-13] — `TIMESTAMPTZ` timestamps, `NUMERIC(38,18)` money/qty, JSON-as-TEXT blobs, composite PKs where the domain ID is compound. `src/db/mappers.py` holds `to_row(domain) -> OrmRow` / `from_row(row) -> Domain` per entity; mappers are total (every field mapped, `from_row(to_row(x)) == x` round-trip test per entity). No ORM class is imported by `src/domain/` or (later) `src/strategy/`.
**Migration:** one reviewed `0002_domain_registry.py` with `down_revision = "0001_baseline"`, `op.create_table(...)` per table mirroring the ORM 1:1 (same convention as `0001_baseline.py:1-17` docstring: "autogenerate `op.create_table(...)` calls match `Mapped[...]` columns 1:1"). `scripts/check_migration_parity.py` covers the new tables with zero script changes (it renders `head` DDL and diffs the full `Base.metadata` — new tables flow through automatically) [VERIFIED: scripts/check_migration_parity.py:137-154, 178-210].

### Pattern 5: Golden triple + placeholder-mechanism harness (D-07/D-09)

**What:** `tests/fixtures/phase3/` holds the mandatory triple — `candles.csv` (columns per TESTING_STRATEGY §2: `symbol,timeframe,open_time_utc,open,high,low,close,volume` [VERIFIED: docs/testing/TESTING_STRATEGY.md:25-29]), `parameters.json` (pinned registry set), `expected_signals.json` + `expected_plans.json` (byte-exact). Per D-09, Phase 3 expectations are **minimal placeholders** (e.g. empty-signal expectation + registry round-trip), proving the harness mechanism; Phase 4 populates real family expectations without changing the harness. Fixture loaders extend `tests/conftest.py` beside `golden_exchange_info`/`frozen_clock` [VERIFIED: tests/conftest.py:30-49].
**Determinism suites (D-08)** — each as a focused test module over the placeholder domain function surface:
- (a) **no-lookahead:** run over prefix ending at T, append arbitrary bars after T, re-run; outputs at/before T byte-identical (TESTING_STRATEGY §3 [VERIFIED: docs/testing/TESTING_STRATEGY.md:40-50]).
- (b) **prefix-invariance:** same prefix in two different longer inputs → byte-identical prefix outputs (stdlib `hashlib` over canonical JSON of outputs for the byte comparison).
- (c) **candle-close-timing:** signal absent on the forming candle, appears exactly once after close (TESTING_STRATEGY §4 [VERIFIED: docs/testing/TESTING_STRATEGY.md:54-66]; precedent: `Kline.close_time_utc <= now_utc` invariant in `src/adapters/binance_usdm.py:49-55`).
- (d) **boundary:** empty input, single bar, warm-up-insufficient → explicit invalid reason (never exception, never crash) (TESTING_STRATEGY §5 [VERIFIED: docs/testing/TESTING_STRATEGY.md:70-78]).
- **unregistered-change rejection:** CI gate (extends `.github/workflows/research-gate.yml` Phase-1 story per D-05) + negative test (loader raises on unknown/mutated set; gate workflow exits non-zero).

### Anti-Patterns to Avoid

- **Stringly-typed statuses:** `"APPROVED"` vs `"Approved"` vs `"approved"` in different modules — GLOSSARY already forbids synonyms (`Skipped-User`/`USER_SKIPPED`/`SKIPPED_USER` warning [VERIFIED: docs/GLOSSARY.md:145]). Use the `Enum` or fail at load.
- **Nullable-column state inference:** `approved_at IS NOT NULL ⇒ approved` — forbidden by D-11. NULL timestamp = "transition never happened"; `status` alone answers state.
- **`default=str` in the canonicalizer:** silently implementation-defined; breaks byte parity across versions. Let `TypeError` fire.
- **`float` anywhere on the Decimal path:** `float(Decimal("0.1"))` then re-quantize can flip a rounding gate. Extend the existing AST no-`float(` tests to `src/domain/`, `src/db/mappers.py`, `src/domain/registry.py`, `canonical.py`.
- **Auto-increment / UUID4 PKs on domain tables:** destroys content-addressability and restart idempotence (ENGINEERING_PRINCIPLES §7 immutable signal identity [VERIFIED: docs/01_ENGINEERING_PRINCIPLES.md:67-77]). Hash IDs only.
- **`create_all()` in prod paths:** migration-only schema authority (`src/db/alembic/env.py:9-10` [VERIFIED]). Tests may use `Base.metadata.create_all` on SQLite exactly as `test_metadata.py:72-86` does, with the documented NUMERIC-tzinfo lossiness handled via `CapturingSession`-style snapshots where precision is asserted.
- **Inventing strategy semantics in the harness:** D-09 placeholders must be mechanism-only (empty/minimal); any threshold-looking constant in a fixture needs a RESEARCH_PROTOCOL source or a TBD marker per AGENT_INSTRUCTIONS §10.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| TOML parsing | Custom line parser / regex over TOML | stdlib `tomllib` | Correct string/escape/multiline/date handling; zero deps; read-only is fine for an immutable registry |
| TOML writing (if needed) | String templating `"key = ..."` | `tomli-w` (or skip: hand-author once, immutable) | Templating breaks on quoting/escaping edge cases; a writer lib or write-once discipline avoids a whole bug class |
| Canonical JSON bytes | Ad-hoc `json.dumps` defaults | Project `canonical.py` (sort_keys + compact separators + whitelist + `allow_nan=False`) | Default `json.dumps` has whitespace variance, insertion-order dependence, and silent NaN output — all digest-breakers |
| Deterministic IDs | `uuid4()` / DB sequences / `hash()` builtin | SHA256 over canonical JSON of the identity fields | Builtin `hash()` is salted per process (PYTHONHASHSEED); UUID4/sequences are non-reproducible and non-idempotent across restarts |
| Status validation | `if status not in ("A","B",...)` string checks | `Enum` + `Enum(value)` coercion at boundaries (raises `ValueError` on unknown) | String lists drift across modules; Enum is single-source and mypy-checkable |
| UTC discipline | Naive datetimes + "assume UTC" | Aware `datetime` (`tzinfo=UTC`) enforced at loader/mapper boundaries; `ZoneInfo("Asia/Ho_Chi_Minh")` only at display | Naive datetimes compare/sort silently wrong across DST-free UTC vs local confusion; Windows needs `tzdata` (already pinned) |
| Schema drift detection | Eyeballing migration vs models | `scripts/check_migration_parity.py` (unmodified — new tables flow through) | Renders `head` DDL offline, diffs name+type+nullability+PK, fails loudly on unparsed lines |
| Test clock | Wall-clock in determinism tests | `frozen_clock` fixture (`2026-09-19T00:00:00Z` [VERIFIED: tests/conftest.py:43-49]) | Wall-clock makes prefix-invariance/no-lookahead tests flaky by construction |

**Key insight:** Every determinism primitive in this phase (canonical bytes, content-hash IDs, frozen values, explicit statuses) exists to make one property cheap: *re-running the same inputs anywhere produces byte-identical outputs*. Custom shortcuts in any of these (string statuses, default JSON dumps, salted hashes, naive datetimes) don't just risk bugs — they silently void the phase's entire success criterion while all tests still pass.

## Common Pitfalls

### Pitfall 1: Hash-input drift (same set, different hash across versions/machines)

**What goes wrong:** `parameterSetHash` recomputed in Phase 6 doesn't match the Phase 3 value for the identical TOML file — every stored linkage breaks.
**Why it happens:** `Decimal("1.50")` vs `Decimal("1.5")` render differently; TOML `1.0` parses to `float` while JSON `1` parses to `int`; dict insertion order differs; a Python upgrade changes `repr(float)`.
**How to avoid:** Canonicalizer coerces numerics at TOML-parse time (whole-number floats → `int` only when exactly integral, else reject non-Decimal-representable floats per RESEARCH_PROTOCOL §5 "numeric type coercion" [VERIFIED: docs/research/RESEARCH_PROTOCOL.md:270-272]); `Decimal` renders via `str()` (precision-preserving); pin the byte-equality test across the repo's Python versions; keep volatile fields (created_by, timestamps) OUT of the hashed body in an unhashed sidecar [CITED: determinism-manifest guide].
**Warning signs:** A hash test that passes on first write but fails after a `uv lock` Python bump.

### Pitfall 2: Mutating a used parameter set

**What goes wrong:** Someone edits `params/<id>.toml` after a backtest references its hash; old reports become unverifiable.
**Why it happens:** Files are editable by nature; nothing stops `git commit` from changing them.
**How to avoid:** Loader `verify(path, expected_hash)` raises `ParameterSetMutated` on mismatch (D-04/D-05); CI gate re-hashes every `params/**` file and compares against hashes recorded in run records (vacuous-green on empty registry, same tripwire story as Phase-1 D029); convention "never mutate, always mint new set + bump strategy version" from CONFIGURATION §5 [VERIFIED: docs/configuration/CONFIGURATION.md:77-83].
**Warning signs:** A PR touching `params/**` without a new `parameter_set_id`.

### Pitfall 3: Strategy-semantic key leaking into runtime config (D-06)

**What goes wrong:** A lookback or RR minimum rides in an env var "temporarily" and silently changes strategy semantics without a registry bump — backtest/paper/live diverge with identical hashes.
**Why it happens:** Env config is convenient; the split is convention-only unless enforced.
**How to avoid:** Loader owns the closed whitelist of strategy-semantic keys; any such key found outside the registry raises at load (D-06). Negative test: env var `STRATEGY_SWING_LOOKBACK=50` present → loader/run-path fails closed.
**Warning signs:** A new `os.environ.get` call anywhere near strategy-adjacent code.

### Pitfall 4: SQLite test green, PG behavior different

**What goes wrong:** Mapper round-trip passes on SQLite but PG rejects (NULL in PK, tzinfo handling, NUMERIC precision).
**Why it happens:** SQLite stores NUMERIC as REAL and drops tzinfo; PG enforces both (documented in `test_metadata.py::CapturingSession` [VERIFIED: tests/test_metadata.py:89-99] and the `__TICK__` sentinel comment [VERIFIED: src/db/models.py:116-120]).
**How to avoid:** Reuse the `CapturingSession` snapshot pattern for precision assertions; never use NULL symbols in PKs (sentinel pattern); keep PG-only features (partial indexes, JSONB) out of migration 0002; record any PG-vs-SQLite boundary in the test docstring as Phase 2 did.
**Warning signs:** A test asserting on post-commit re-read values for NUMERIC/TIMESTAMPTZ columns.

### Pitfall 5: SignalId collision by under-specified fingerprint (D-03)

**What goes wrong:** Two distinct setups on the same candle produce the same SignalId → duplicate suppression eats a real signal, or restart replays collide.
**Why it happens:** Fingerprint omits a discriminating field (e.g. setup variant, direction, or regime) that Phase 4 later needs.
**How to avoid:** D-03's input list (`strategyVersion + parameterSetId + symbol + source_timeframe + source_candle_close_utc + setup fingerprint`) is the floor; `ids.py` takes the fingerprint as an opaque canonical-JSON string so Phase 4 can widen it without changing the ID scheme. Note the canonical docs vary slightly (ENGINEERING_PRINCIPLES §7 lists `strategyVersion + symbol + timeframe + sourceCandleCloseTime + setupType` [VERIFIED: docs/01_ENGINEERING_PRINCIPLES.md:71-75]; SIGNAL_AND_ALERTS §3 shows `hash(StrategyVersion, Symbol, SourceTimeframe, SourceCandleCloseUtc, SetupType)` [VERIFIED: docs/trading/SIGNAL_AND_ALERTS.md:52-59]) — D-03's list (adds `parameterSetId` + fingerprint) is the binding superset for Phase 3; planner implements D-03 exactly.
**Warning signs:** An ID constructor with positional args that Phase 4 must extend — use an explicit fingerprint payload instead.

### Pitfall 6: Enum drift between GLOSSARY, domain, rows, and fixtures

**What goes wrong:** `TRADE_PLAN.APPROVED` vs `APPROVED` vs `Approved` in different layers; stored rows disagree with fixtures.
**Why it happens:** Copy-paste of string literals across `enums.py`, ORM defaults, fixtures, Telegram payloads.
**How to avoid:** `enums.py` is the single source; ORM `status` columns store `.value` via mapper (never re-declared strings); fixtures reference the same values; a "no invented names" test asserts every status string appearing in `tests/fixtures/phase3/` is a member of the corresponding Enum; unknown status at any boundary raises `ValueError` (D-10).
**Warning signs:** A string literal matching an enum value anywhere outside `enums.py` and its test.

## Code Examples

Verified patterns from in-repo sources read this session (planner lifts these shapes into task actions):

### GLOSSARY-canonical enums (`src/domain/enums.py` target shape)

```python
# Source: docs/GLOSSARY.md §§2-8 (verbatim values — copy exactly, invent nothing)
from enum import Enum


class SignalStatus(str, Enum):
    DETECTED = "DETECTED"
    NOTIFIED = "NOTIFIED"
    VIEWED = "VIEWED"
    APPROVED = "APPROVED"
    SKIPPED_USER = "SKIPPED_USER"
    SKIPPED_BUSY = "SKIPPED_BUSY"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class TradePlanStatus(str, Enum):
    READY = "READY"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    APPROVED = "APPROVED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
    SUPERSEDED = "SUPERSEDED"


class ApprovalAction(
    str, Enum
):  # NOTE: GLOSSARY defines ApprovalAction, not ApprovalStatus — see Q2
    SIMULATE = "SIMULATE"
    APPROVE = "APPROVE"
    SKIP_USER = "SKIP_USER"
    SKIP_BUSY = "SKIP_BUSY"
    CANCEL = "CANCEL"


class OrderStatus(str, Enum):
    PLANNED = "PLANNED"  # entry state — no approval state on orders (D024)
    SUBMITTING = "SUBMITTING"
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    LIQUIDATION_REPORTED = "LIQUIDATION_REPORTED"
    UNKNOWN = "UNKNOWN"


class SystemMode(str, Enum):
    RESEARCH = "RESEARCH"
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE_APPROVAL = "LIVE_APPROVAL"
    SAFE_MODE = "SAFE_MODE"
    LIVE_AUTONOMOUS_DISABLED = "LIVE_AUTONOMOUS_DISABLED"


# Values verbatim from docs/GLOSSARY.md:39-48, 58-65, 69-75, 81-90, 105-110, 115-121.
# TradeStatus (PENDING/OPEN/CLOSED/ABORTED/UNKNOWN, GLOSSARY.md:95-100) + rejection
# reasons (NO_TRADE_REGIME … APPROVAL_EXPIRED, GLOSSARY.md:129-143) ride along.
# `str, Enum` mixin keeps ORM/JSON `.value` storage trivial while preserving Enum identity.
```

### Frozen domain entity + content-hash ID

```python
# Shape precedent: src/adapters/binance_usdm.py:49-67 (Kline frozen dataclass)
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .canonical import sha256_hex
from .enums import SignalStatus


@dataclass(frozen=True)
class Signal:
    signal_id: str  # content hash from ids.make_signal_id — never passed in by callers
    strategy_id: str
    strategy_version: str
    parameter_set_id: str
    parameter_set_hash: str
    symbol: str
    direction: str  # LONG/SHORT — Phase 4 may promote to Enum; D-09 keeps Phase 3 minimal
    setup_type: str
    source_timeframe: str
    source_candle_close_utc: datetime  # aware UTC; loader/mapper assert tzinfo
    detected_at_utc: datetime
    status: SignalStatus  # explicit — never inferred (D-11)
    expires_at_utc: datetime
    invalidated_at_utc: datetime | None = None  # None = "never happened" (D-11)


# ids.py — D-03 binding superset (parameterSetId included; cf. Pitfall 5)
def make_signal_id(
    *,
    strategy_version: str,
    parameter_set_id: str,
    symbol: str,
    source_timeframe: str,
    source_candle_close_utc: datetime,
    setup_fingerprint: str,
) -> str:
    return sha256_hex(
        {
            "strategy_version": strategy_version,
            "parameter_set_id": parameter_set_id,
            "symbol": symbol,
            "source_timeframe": source_timeframe,
            "source_candle_close_utc": source_candle_close_utc,  # canonical.py → isoformat
            "setup_fingerprint": setup_fingerprint,
        }
    )


def derive_child_id(parent_signal_id: str, discriminator: str) -> str:
    # plan/order IDs: parent hash + fixed discriminator ("trade_plan:v1", "order:entry", …)
    return sha256_hex({"parent_signal_id": parent_signal_id, "discriminator": discriminator})
```

### Canonicalizer core (`src/domain/canonical.py`)

```python
# Policy: kailash-py _canonical.py whitelist (no default=str; Decimal→str full precision)
# + RFC 8785 JCS profile (sorted keys, compact separators, UTF-8) + allow_nan=False.
import hashlib
import json
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any


def canonical_scalars(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: canonical_scalars(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [canonical_scalars(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)  # full precision: "1.50" ≠ "1.5" by design
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive datetime in canonical hash input")
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (set, frozenset)):
        raise TypeError("unordered set in canonical hash input — use a sorted list")
    if isinstance(value, float):
        raise TypeError("float in canonical hash input — use Decimal/str/int")
    return value  # str/int/bool/None pass through; anything else → json TypeError


def canonical_bytes(payload: dict) -> bytes:
    return json.dumps(
        canonical_scalars(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(payload: dict) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()
```

### Registry loader skeleton (fail-closed)

```python
# Contract: docs/configuration/CONFIGURATION.md §§2-7 + docs/research/RESEARCH_PROTOCOL.md §5
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .canonical import canonical_bytes, sha256_hex

REGISTRY_ROOT = Path("params")
SCHEMA_VERSION = 1
# Closed whitelist of strategy-semantic keys (D-06). Anything strategy-semantic
# found OUTSIDE the registry raises; anything unknown INSIDE raises.
STRATEGY_KEYS = frozenset(
    {
        "swing_lookback",
        "zone_tolerance_atr",
        "breakout_confirmation_bars",
        "entry_buffer_atr",
        "sl_buffer_atr",
        "minimum_rr",
        "signal_expiry_hours",
        "risk_rate",
        "minimum_risk_utilization_after_rounding",
    }
)  # seed list from CONFIGURATION.md §3 strategy examples — planner extends deliberately, never silently


class UnregisteredParameterSet(Exception): ...


class ParameterSetMutated(Exception): ...


class RegistrySchemaMismatch(Exception): ...


class StrategyKeyOutsideRegistry(Exception): ...


@dataclass(frozen=True)
class ParameterSet:
    strategy_id: str
    strategy_version: str
    parameter_set_id: str
    parameter_set_hash: str  # sha256 over canonical JSON of the normalized params doc
    params: dict  # normalized values (Decimals preserved, not floats)


def load_parameter_set(strategy_id: str, parameter_set_id: str) -> ParameterSet:
    path = REGISTRY_ROOT / strategy_id / f"{parameter_set_id}.toml"
    if not path.is_file():
        raise UnregisteredParameterSet(f"{strategy_id}/{parameter_set_id}")
    doc = tomllib.loads(path.read_bytes().decode("utf-8"))
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise RegistrySchemaMismatch(f"{path}: {doc.get('schema_version')!r}")
    # …validate identity fields, normalize numerics (whole floats→int iff integral
    # else Decimal(str(v))), reject unknown keys, sha256 over canonical body…
```

### ORM row + mapper (extends `src/db/models.py` conventions)

```python
# models.py addition — conventions verbatim from src/db/models.py:10-13:
# TIMESTAMPTZ + NUMERIC(38, 18), JSON-as-TEXT blobs, PK on the deterministic id.
class SignalRow(Base):
    __tablename__ = "signals"
    signal_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    parameter_set_id: Mapped[str] = mapped_column(String(64), nullable=False)
    parameter_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # SignalStatus.value — explicit (D-11)
    source_candle_close_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    invalidated_at_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # …remaining DATA_MODEL §2.3 fields; prices/qty NUMERIC(38,18); payloads String…


# mappers.py — total + round-trip tested
def signal_to_row(s: Signal) -> SignalRow: ...
def signal_from_row(r: SignalRow) -> Signal: ...


# assert signal_from_row(signal_to_row(s)) == s  (per-entity round-trip test)
```

### Migration 0002 (same convention as 0001)

```python
# src/db/alembic/versions/0002_domain_registry.py
"""Domain + registry mirror — Phase 3 (DOMN-01/DOMN-02 storage half).

op.create_table(...) calls match src/db/models.py Mapped[...] columns 1:1
(same convention as 0001_baseline.py). Verified offline by
scripts/check_migration_parity.py — no script changes needed.
"""

revision: str = "0002_domain_registry"
down_revision = "0001_baseline"
# upgrade(): 7× op.create_table + indexes on (symbol, source_candle_close_utc),
#   (parameter_set_id, parameter_set_hash); downgrade(): drop in reverse.
```

### Determinism suite skeletons

```python
# tests/test_no_lookahead.py — TESTING_STRATEGY §3: prefix through T, append after T, re-run
def test_appended_bars_never_change_earlier_outputs(phase3_candles) -> None:
    before = run_domain_pipeline(phase3_candles[:N])          # placeholder fn per D-09
    after = run_domain_pipeline(phase3_candles[:N] + EXTRA_BARS)
    assert canonical_of(after[:N]) == canonical_of(before)    # byte comparison via canonical_bytes

# tests/test_candle_close_timing.py — signal absent on forming candle, exactly once after close
def test_no_signal_before_source_candle_close(phase3_candles) -> None:
    assert run_domain_pipeline(phase3_candles[:N-1]) == run_domain_pipeline(phase3_candles[:N-1])
    # forming-candle input: no signal referencing close(N); closed-candle input: exactly one

# tests/test_registry_gate.py — D-05 negative tests
def test_unregistered_set_fails_closed() -> None:
    with pytest.raises(UnregisteredParameterSet):
        load_parameter_set("trend-pullback", "does-not-exist")

def test_mutated_set_fails_closed(tmp_path) -> None:
    # copy seed TOML, flip one digit, load_parameter_set + verify(..., expected_hash) → ParameterSetMutated
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `binance-connector` / `binance-futures-connector` | `binance-sdk-derivatives-trading-usds-futures>=17.3` | 2026-04-30 (legacy archived) | Phase 3 touches no SDK code, but domain `order.py` must model Algo-Order-shaped IDs (`client_order_id` vs `algo_client_id` separate columns per DATA_MODEL §2.7) |
| Ad-hoc `json.dumps` for hashes | Canonical profile (sorted keys, compact separators, scalar whitelist) | Current best practice (RFC 8785 JCS, 2020; stablejson PyPI) | Planner pins the profile in `canonical.py` docstring so future readers don't "simplify" it |
| UUID4 / sequences for entity PKs | Content-hash IDs | Locked by D-03 for this project | Restart-idempotent; journal/experiment records can cite IDs as content addresses |
| Nullable-column state inference | Explicit `status` + transition timestamps | Locked by D-11 | Journal analytics reads `status` alone; NULL timestamp = transition never happened |

**Deprecated/outdated:**
- Legacy Binance connectors (archived 2026-04-30) — never reference in domain naming.
- `float` for any exchange-sensitive value — project-wide ban, extended to `src/domain/` in this phase.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `tomli-w` is a legitimate tiny dependency by the `tomli` author; `uv add` will resolve it | Standard Stack / Package Audit | LOW — fallback (hand-authored immutable TOML, zero new deps) is already the recommended default |
| A2 | `stablejson` rejected as unnecessary; ~20-line owned normalizer suffices | Alternatives | LOW — planner can revisit, but owning the Decimal/datetime/Enum whitelist is required regardless |
| A3 | Parameter names stay 7-bit ASCII so code-point sort ≡ JCS sort; loader should assert this | Alternatives | LOW — one assertion makes it airtight |
| A4 | `str, Enum` mixin is the right base (ORM `.value` storage trivial, mypy-friendly) | Code Examples | LOW — plain `Enum` + explicit `.value` at mappers works identically; planner picks one and standardizes |
| A5 | Single `0002_domain_registry` migration with all 7 tables is reviewable (~7 `create_table` blocks + indexes) | Architecture Patterns | MEDIUM — if review finds it too large, split into 0002 (signals/plans/approvals) + 0003 (orders/fills/positions/journal); parity script handles either |
| A6 | SQLite remains adequate for mapper tests via `CapturingSession` pattern (no PG-only features in 0002) | Pitfalls | LOW — same boundary as Phase 2; any PG-only index need discovered later gets a documented exception |

## Open Questions (RESOLVED 2026-09-22 — plan-checker revision 1)

| # | Disposition | Owner |
|---|-------------|-------|
| Q1 | DEFER both tables to Phases 5/6; migration 0002 carries exactly the seven entities | 03-04 checkpoint:decision |
| Q2 | Map D-10 "ApprovalStatus" to approval `result` lifecycle PENDING/APPROVED/SKIPPED/EXPIRED as flagged assumption behind blocking checkpoint | 03-01 + 03-02 checkpoints |
| Q3 | DEFER registry DB mirror to Phase 6; files canonical in Phase 3 | 03-03 (planner discretion, within CONTEXT) |
| Q4 | Validated non-empty strings in Phase 3; Enum promotion in Phase 4 | 03-02 checkpoint |

1. **`trades` + `experiment_runs` tables: now or with consumers?**
   - What we know: DATA_MODEL defines `trades` (§2.6) and `experiment_runs` (§2.12) beyond the seven; Phase 3 success criteria name only the seven; CONTEXT D-02 says "7 new tables + mappers".
   - Recommendation: defer both to Phases 5 (risk/`trades`) and 6 (backtest/`experiment_runs`); migration 0002 carries exactly the seven. If the planner prefers one migration for review economy, adding them now is harmless as long as no Phase-3 code writes to them.

2. **No canonical `ApprovalStatus` enum exists — only `ApprovalAction`.**
   - What we know: D-10 names "ApprovalStatus" but GLOSSARY §4 defines `ApprovalAction` (`SIMULATE/APPROVE/SKIP_USER/SKIP_BUSY/CANCEL` [VERIFIED: docs/GLOSSARY.md:68-75]) and DATA_MODEL §2.5 gives approvals `action` + `result` columns with no `status`.
   - Recommendation: planner maps D-10 "ApprovalStatus" to the `result` lifecycle (needs user confirmation of the `result` value set — candidate: `PENDING/APPROVED/SKIPPED/EXPIRED`, but this is invented until confirmed) or treats `action` as the enum and adds an explicit `status` column per D-11. Either way this needs a discuss-phase confirmation, not a silent planner pick.

3. **Registry DB mirror in Phase 3 or later?**
   - What we know: D-05 leaves it to planner discretion; CONFIGURATION §6 recommends the hybrid (files → loader → canonical JSON → DB row).
   - Recommendation: defer the mirror table to Phase 6 (experiment registry), since no Phase-3 consumer joins against it. If added now, it is one more table in 0002 storing `(parameter_set_id, parameter_set_hash, canonical_json, registered_at_utc)` with a UNIQUE on the hash.

4. **Direction/setup_type/regime as Enum now or in Phase 4?**
   - What we know: D-10 demands one enum per lifecycle; direction/setup/regime vocabularies belong to the frozen strategy spec (Phase 4), and D-09 forbids favoring any family.
   - Recommendation: Phase 3 keeps `direction/setup_type/regime` as validated non-empty strings on the dataclasses; Phase 4 promotes them to Enums when the family specs freeze the vocabularies. The no-invented-names test covers only lifecycle statuses in Phase 3.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.13 (via `uv run`) | All Phase-3 code | ✓ (pinned `==3.13.*`, uv managed) | uv 0.12.17 present [VERIFIED: bash] | System python is 3.14.3 [VERIFIED: bash] — never use directly; planner prefixes every command with `uv run` |
| PostgreSQL 17 | Migration 0002 apply + parity render | Unknown (Phase-2 Compose stack assumed) | — | Parity script renders DDL offline without a live DB [VERIFIED: scripts/check_migration_parity.py:137-154]; mapper tests run on SQLite |
| `params/` + `tests/fixtures/phase3/` | Registry + harness | ✗ (absent [VERIFIED: bash]) | — | Greenfield creation sliced into planner tasks (no migration of existing files) |
| CI gate file (`.github/workflows/research-gate.yml`) | D-05 enforcement | Unknown — planner verifies existence | — | If absent, Phase-3 task creates the registry-gate workflow (Phase-1 D029 pattern) |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** live PG (offline parity + SQLite cover it); `tomli-w` (hand-authored TOML covers it).

## Validation Architecture

> Nyquist validation is enabled (`.planning/config.json: workflow.nyquist_validation = true`, `tdd_mode = true`). Per-task test strategy the planner lifts into VALIDATION.md.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9 + pytest-asyncio (auto mode; no decorators needed) |
| Config file | `pyproject.toml:46-51` (`testpaths = ["tests"]`, `asyncio_mode = "auto"`) |
| Quick run command | `uv run pytest tests/test_domain_enums.py tests/test_registry.py -x -q` |
| Full suite command | `uv run pytest -q` plus `uv run python scripts/check_migration_parity.py` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| DOMN-01 | 7 entities persist separately; GLOSSARY enums round-trip; no nullable-state inference | unit (mapper round-trip ×7, enum membership, invalid-transition rejection) | `uv run pytest tests/test_domain_mappers.py tests/test_domain_enums.py -x -q` | ❌ Wave 0 — `src/domain/`, `src/db/mappers.py`, tests to be created |
| DOMN-01 | Migration 0002 matches ORM 1:1 (columns, types, PKs) | static (offline parity gate) | `uv run python scripts/check_migration_parity.py` | ✅ script exists; ❌ migration to be created |
| DOMN-01 | No `float(` in domain/mapper/registry code | static (AST guard) | `uv run pytest tests/test_domain_no_float.py -x -q` | ❌ Wave 0 — extend existing guard pattern |
| DOMN-02 | Registered set loads; hash stable across key orderings; Decimal precision preserved | unit (loader + byte-equality vectors) | `uv run pytest tests/test_registry.py -x -q` | ❌ Wave 0 |
| DOMN-02 | Unregistered set raises; mutated set raises; strategy key outside registry raises | unit (negative) + CI gate job | `uv run pytest tests/test_registry_gate.py -x -q` | ❌ Wave 0 |
| DOMN-03 | Golden triple loads; placeholder expectations byte-exact | unit (harness mechanism) | `uv run pytest tests/test_fixture_harness.py -x -q` | ❌ Wave 0 — `tests/fixtures/phase3/` to be created |
| DOMN-03 | No-lookahead / prefix-invariance / candle-close-timing / boundary suites green | unit (determinism) | `uv run pytest tests/test_no_lookahead.py tests/test_prefix_invariance.py tests/test_candle_close_timing.py tests/test_domain_boundary.py -x -q` | ❌ Wave 0 |
| DOMN-03 | Unregistered semantic change to domain outputs fails CI | CI (golden byte-compare job) | gate workflow on PR | ❌ Wave 0 — workflow extension to be created |

### Sampling Rate

- **Per task commit:** quick run for the touched area (`uv run pytest tests/test_<area>.py -x -q`) + `ruff check` + `mypy` on `src/` (strict per `pyproject.toml:74-80`)
- **Per wave merge:** `uv run pytest -q` (full suite) + `uv run python scripts/check_migration_parity.py`
- **Phase gate:** full suite green + parity green + gate workflow green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `src/domain/` package (`enums.py`, `ids.py`, `canonical.py`, 7 entity modules, `registry.py`) — covers DOMN-01/DOMN-02 Code
- [ ] `src/db/mappers.py` + 7 ORM tables in `src/db/models.py` + `0002_domain_registry.py` — covers DOMN-01 Code
- [ ] `params/<strategy_id>/` seed TOML(s) — covers DOMN-02 fixture input
- [ ] `tests/fixtures/phase3/{candles.csv,parameters.json,expected_signals.json,expected_plans.json}` — covers DOMN-03 fixture input
- [ ] `tests/conftest.py` extensions (phase-3 loaders) + `tests/test_*.py` suite files above — covers DOMN-01/02/03 tests
- [ ] CI gate extension for registry rejection (or new workflow if Phase-1 file absent — planner verifies) — covers DOMN-02/D-05 gate
- [ ] Framework install: none — pytest/Ruff/mypy already in `dev` extras [VERIFIED: pyproject.toml:33-40]

## Security Domain

> `security_enforcement` is enabled (absent = enabled; confirmed `true` in `.planning/config.json:57`, ASVS Level 1).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|------------------|
| V2 Authentication | no | Phase 3 has no auth surface; approval tokens arrive in Phase 8 |
| V3 Session Management | no | No sessions in Phase 3 |
| V4 Access Control | no | Single-operator local tool; no multi-actor paths yet |
| V5 Input Validation | **yes** | Registry loader validates `schema_version`, closed strategy-key whitelist, TOML types; `Enum(value)` coercion rejects unknown statuses; canonicalizer rejects `float`/`set`/naive-datetime/NaN loudly |
| V6 Cryptography | partial | SHA256 content hashes are integrity identifiers, not secrets — stdlib `hashlib` is correct; never hand-roll a hash; no password/token hashing in this phase (`approval_token_hash` column exists in DATA_MODEL but token minting is Phase 8) |
| V10 Malicious Code / Supply Chain | **yes** | At most one new dep (`tomli-w`); verify via `uv add` resolution + lockfile; no network calls in domain/loader code paths |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Mutated registry file silently changing strategy semantics | Tampering | `verify()` hash check + CI re-hash gate; fail closed (D-04/D-05) |
| Strategy-semantic key smuggled via env/config outside registry | Tampering | Closed key whitelist; loader raises on out-of-registry strategy keys (D-06) |
| Fixture poisoning (expected-outputs edited to match buggy code) | Tampering | Fixture changes reviewed as semantic changes; placeholder→real expectations only in Phase 4 with spec citations |
| `float` precision drift flipping a future quantization gate | Tampering (integrity) | AST no-`float(` guards extended to all new domain code (D-12) |

## Sources

### Primary (HIGH confidence)

- In-repo canonical docs read this session: `docs/data/DATA_MODEL.md` (§§2-6), `docs/configuration/CONFIGURATION.md`, `docs/GLOSSARY.md` (§§2-9), `docs/DECISIONS.md` (D001-D029), `docs/01_ENGINEERING_PRINCIPLES.md`, `docs/testing/TESTING_STRATEGY.md`, `docs/research/RESEARCH_PROTOCOL.md` (§5), `docs/backtest/BACKTEST_SPEC.md`, `docs/architecture/ARCHITECTURE.md`, `docs/trading/SIGNAL_AND_ALERTS.md`, `docs/implementation/AGENT_INSTRUCTIONS.md`
- In-repo code read this session: `src/db/models.py` (1-228), `src/db/alembic/versions/0001_baseline.py`, `src/db/alembic/env.py`, `src/adapters/binance_usdm.py` (1-120), `tests/conftest.py`, `tests/test_metadata.py` (1-120), `tests/test_adapter_strictness.py`, `scripts/check_migration_parity.py`, `pyproject.toml`, `.planning/config.json`
- `03-CONTEXT.md` D-01–D-12 (locked decisions — planner authority, not research claims)

### Secondary (MEDIUM confidence)

- RFC 8785 JSON Canonicalization Scheme (sorted keys, UTF-8, deterministic property sorting) [CITED: rfc-editor.org/rfc/rfc8785.html]
- Python `json` stdlib docs (`sort_keys`, `separators=(',',':')`, `allow_nan`, `parse_float=Decimal`) [CITED: docs.python.org/3/library/json.html]
- `stablejson` PyPI (deterministic JSON + SHA256 profile: compact separators, reject floats/NaN) [CITED: pypi.org/project/stablejson]
- kailash-py `_canonical.py` scalar-whitelist shape (Decimal→str full precision, datetime→isoformat, Enum→value, no `default=str`) [CITED: github.com/terrene-foundation/kailash-py]
- Deterministic-manifest canonicalization guide (NFC, fixed floats, reject non-finite, volatile fields in unhashed sidecar) [CITED: cross-engine-reconciliation.org]

### Tertiary (LOW confidence)

- `tomli-w` authorship/popularity (training knowledge, [ASSUMED] — planner confirms via `uv add` resolution)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every pinned version verified by `Read` of `pyproject.toml`; stdlib availability verified by `bash`; only `tomli-w` is [ASSUMED] with a zero-dep fallback
- Architecture: HIGH — all five patterns are extensions of in-repo, already-reviewed Phase-1/2 precedent (adapter boundary, single-Base + parity gate, CapturingSession, frozen-clock, research-gate workflow)
- Pitfalls: HIGH — each pitfall is grounded in a specific in-repo constraint (D-03/D-04/D-06/D-11/D-12) or a documented Phase-2 lesson (SQLite lossiness, `__TICK__` sentinel)
- Canonical-hash profile: MEDIUM — JCS + stdlib docs + two independent implementations agree on the shape, but cross-version byte-stability should be pinned by the repo's own byte-equality test, not by citation

**Research date:** 2026-09-22
**Valid until:** 30 days (stable domain — stdlib + frozen in-repo contracts; re-verify only if `pyproject.toml` pins or GLOSSARY enums change)

**Tool-strategy note:** the `gsd-tools research-plan / classify-confidence / package-legitimacy` seam was unavailable in this environment (Windows PowerShell, no `gsd_run` on PATH; all remote providers `false` in `.planning/config.json`). External lookups were limited to one built-in web search (canonical-JSON hashing) plus direct `bash` probes (stdlib presence, absent dirs/files, interpreter versions). This is proportionate: Phase 3 is ~90% in-repo-contract implementation (D-01–D-12 bind nearly every choice) with a stdlib-only technical core, so training-knowledge claims are fenced into the Assumptions Log and the four genuine judgment calls are surfaced as Open Questions for discuss-phase confirmation.
