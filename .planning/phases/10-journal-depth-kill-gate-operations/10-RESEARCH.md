# Phase 10: Journal Depth + Kill-Gate Operations - Research

**Researched:** 2026-09-29
**Domain:** Internal deterministic analytics (pure stdlib + Decimal), governance state machine, static report generation. No external library research needed; stack constraints confirmed against AGENTS.md + pyproject.toml.
**Confidence:** HIGH for what exists in the repo (all read this session); MEDIUM for metric-vocabulary choices the docs leave open (session, volatility regime, low-n threshold) - these are flagged in the Assumptions Log.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

### Analytics engine shape + determinism

- **D-01:** A new pure analytics package (e.g. `src/analytics/`, layout at planner discretion) computes all journal-depth metrics from existing records only — `JournalEvent` rows, Order/Fill/Position rows, `PaperRecord` (Phase 7), `ExperimentRecord` + `UncertaintyReport` (Phase 6) — with stdlib + `Decimal` only, UTC datetimes in, deterministic ordering, frozen dataclasses, no `float(` in metric math (AST guard, mypy strict), and a content digest per report so the same inputs produce byte-identical output (same contract as `src/backtest/report.py` and `src/paper/journal.py::paper_records_digest`). Analytics is read-only over the journal: it never writes to Order/Fill/Position/Approval tables, never calls the exchange, and never feeds back into strategy/risk/parameters (D001 no-AI/no-tuning boundary). Any DB/Polars/DuckDB access lives in a thin adapter at the edge, not in the metric functions. TDD RED→GREEN, atomic commits, golden fixtures under `tests/fixtures/phase10/`. — **Reversibility:** costly — module paths, report dataclass shapes, and the digest contract become the input schema for the dashboard and any future analytics.
- [auto] Analytics shape — Q: "Pure deterministic read-only analytics package with digest-stamped reports vs ad-hoc notebook/SQL queries?" → Selected: "Pure deterministic package, digest-stamped, read-only" (recommended default)

### Metric definitions: MFE/MAE, execution quality, approval delay, robustness slices

- **D-02:** Metrics follow `docs/backtest/METRICS.md` §§3–6 verbatim. MFE/MAE are measured from actual/simulated entry fill to exit on 1m candles (same 1m intrabar authority as BACKTEST_SPEC), expressed both in price and in R-multiples of the plan's initial risk (zero-risk trades excluded and counted, as in `src/backtest/report.py`), with the diagnostic questions METRICS §6 names (TP too close / SL too tight / entry poor / holding too long) reported as descriptive distributions, never as tuning recommendations. Execution-quality latencies are computed from journal event timestamps (signal created → seen → approved → order placed → filled), intended-vs-actual entry deviation from plan zone vs fill price, plus fill %, average wait-to-fill, and expiry-without-fill rate. Approval-delay impact uses the three METRICS §3 reports (System = all valid signals, User execution = approved only, Opportunity = skipped/expired with hypothetical outcome tracked) so selection bias and the effect of time availability are visible side by side. Robustness slices are exactly METRICS §5 (symbol, month/quarter, session, long/short, volatility regime, trend/range regime, strategy version); every sliced view is rendered NEXT TO the full report, slice count and sample size `n` are always shown, and no slice is dropped, reordered by favorability, or omitted for low `n` (low-n slices are flagged, not hidden). Point estimates always carry the Phase-6 uncertainty presentation (bootstrap interval, `n`), never a bare number. Missing inputs (no fill event, no 1m coverage) are counted under an explicit `INCOMPLETE` bucket, never imputed. — **Reversibility:** costly — metric definitions and slice vocabulary become the reporting contract that kill-gate evidence cites.
- [auto] Metric definitions — Q: "METRICS.md-verbatim definitions with full report always visible, low-n flagged not hidden vs favorable-slice highlights?" → Selected: "METRICS.md-verbatim, full report always visible, INCOMPLETE bucket" (recommended default)

### Kill-gate state machine + terminal outcome (GOV-01)

- **D-03:** The kill gate is a pure, deterministic evaluator of D013 (`docs/DECISIONS.md`, Provisional). Inputs: the registry of independently specified families, ExperimentRecord acceptance outcomes per family (Phase 6 six-field identity), and the research-effort clock. States: `WITHIN_BUDGET` (fewer than 3 families tested OR fewer than 6 months elapsed — keep researching); `PASSING_CANDIDATE` (a family satisfies the acceptance methodology — the gate does NOT authorize live, it only records that evidence exists; a separate decision record is required per IMPLEMENTATION_PLAN); `INSUFFICIENT_EDGE` (terminal: ≥3 independently specified families tested under the frozen methodology AND ≥6 months elapsed AND none passes). The AND/OR wording in `RESEARCH_PROTOCOL.md` §"Kill gate D013" ("fires if fewer than three… OR fewer than six months… OR any family fails") contradicts D013's reading (both budgets exhausted with none passing); D013 is authoritative, and the planner records the resolution as a new DECISIONS.md entry + protocol amendment note rather than silently picking one (same no-silent-rename discipline as Phase 1 D022–D028). The research-clock start is the frozen-protocol freeze timestamp (Phase 1 freeze beat, verified at plan time from git/registry — not assumed); "independently specified" is decided by the family-sheet template plus registered distinct parameter-set/spec hashes, not by a free-text flag. `INSUFFICIENT_EDGE` / `NO_TRADE` is recorded as an append-only `JournalEvent` (event type e.g. `KILL_GATE_EVALUATION`) carrying evaluator inputs, evidence digest, state, and evaluated-at UTC — a valid terminal outcome, not an error — and its effect is fail-closed: it keeps `LIVE_ORDERS_DISABLED` via the existing `src/execution/enablement.py` posture and blocks new strategy-family registration until a new evidence-backed question is approved by an explicit human decision record; the gate never auto-enables live and never auto-clears itself. Evaluation is idempotent and replayable (same evidence + same evaluated-at → same state and same digest). — **Reversibility:** one-way — a recorded terminal outcome and its enablement side-effect enter the permanent decision/audit history and the live-safety contract.
- [auto] Kill-gate semantics — Q: "Deterministic D013 evaluator with journaled terminal INSUFFICIENT_EDGE that keeps live disabled vs advisory dashboard number with manual interpretation?" → Selected: "Deterministic evaluator, journaled terminal outcome, fail-closed live-disabled" (recommended default)

### Dashboard delivery form + slices + presentation

- **D-04:** The "dashboard" (roadmap `UI hint: yes`) is an offline, deterministic, generated report — not a web service: a CLI/module entry point (thin PowerShell wrapper in the `scripts/dev/` convention over a Python module) renders one Markdown/HTML document plus a machine-readable JSON sidecar from the analytics + kill-gate outputs, with the report digest embedded, byte-identical for identical inputs. No FastAPI/uvicorn/web server, no JavaScript dependency, no direct exchange access (ARCHITECTURE §3 keeps "UI → direct Binance order API" forbidden); charting, if any, is static and optional. The kill-gate view shows: families tested vs 3, research months elapsed vs 6 (with clock-start provenance), per-family acceptance status against the 10 gates, NO_TRADE counts by reason category (regime filter, RR floor, open-position conflict, data unavailability, kill-gate trip — RESEARCH_PROTOCOL §NO_TRADE), and the current gate state. Every kill-gate and analytics view shows the two universes side by side — live-5 (BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT) vs research universe — reusing the Phase-6 `DualUniverseSection` framing, with empty slices labelled "no data". Presentation timestamps use the Asia/Ho_Chi_Minh display edge; stored/computed values stay UTC. An optional short Telegram summary may reuse the existing notify adapter but is a pointer to the report, never a decision surface and never an approval path. — **Reversibility:** costly — report layout and CLI entry contract are operator-facing, but the underlying analytics dataclasses (D-01) stay stable beneath them.
- [auto] Dashboard form — Q: "Static deterministic generated report (Markdown/HTML + JSON, CLI) with dual-universe views vs live web dashboard served by FastAPI?" → Selected: "Static deterministic report + JSON sidecar, dual-universe, no web server" (recommended default)

### Persistence, journal inputs, and evidence provenance

- **D-05:** Analytics results are derived views, recomputed from journal/registry inputs on demand — no new operational tables for metrics. Kill-gate evaluations persist as append-only `JournalEvent` rows using the existing `content_hash_event_id` contract (`src/domain/journal.py`), so no schema migration is required unless the planner proves one is needed; if unavoidable it follows the `0001`–`0003` parity-gate discipline (`scripts/check_migration_parity.py`). Every report and kill-gate record carries full evidence provenance: strategyVersion + parameterSetId + parameterSetHash + experiment identity (six-field, Phase 6 D-02) + universe hash + dataset/version identifiers, so any headline number traces back to registered experiments and journal rows. Backtest, paper (Phase 7 three-way attribution categories), and live evidence stay separately labelled and are never silently pooled; a pooled headline number must be an explicit, labelled view. No parameter is changed, ranked-as-winner, or auto-selected by this phase — output is descriptive and uncertainty-first, consistent with the "no tuning on paper/live stream" locks. Fixtures under `tests/fixtures/phase10/` cover: complete/incomplete trade records, zero-risk exclusion, empty live-5 slice, skipped/expired opportunity outcomes, low-n slices, kill-gate WITHIN_BUDGET / PASSING_CANDIDATE / INSUFFICIENT_EDGE transitions, clock-start provenance, idempotent replay, and byte-identical digest regeneration. — **Reversibility:** costly — journal event vocabulary and provenance fields persist as the audit trail future amendments cite.
- [auto] Persistence + provenance — Q: "Derived views + append-only KILL_GATE_EVALUATION JournalEvents with full provenance and unpooled evidence vs new metrics tables with pooled headline numbers?" → Selected: "Derived views, journaled gate events, full provenance, unpooled evidence" (recommended default)

### Claude's Discretion

- User runs `--auto --chain` (fully autonomous per `modes/auto.md`): all five gray areas above auto-resolved to recommended defaults with no interactive prompts. Single-pass cap observed — no re-pass gap-hunting.
- Exact package/module layout inside `src/analytics/` (metrics vs kill-gate vs render splits), report dataclass field names, HTML vs Markdown primary format, JSON sidecar schema, adapter used to read journal rows (SQLAlchemy read vs Parquet/DuckDB extract), CLI/PowerShell wrapper naming, low-n flag threshold (must flag, never hide), MFE/MAE bucketing, the precise research-clock-start source, wording of the D013 resolution entry, and plan slicing (tracer slice first: one metric family end-to-end, then kill-gate, then render) are at planner/researcher discretion, provided D-01–D-05 semantics hold.
- Pre-answered from prior phases (not re-asked): pure stdlib + `Decimal` cores with AST no-`float(` guards + mypy strict; frozen dataclasses + content-hash IDs; TDD RED→GREEN with atomic commits; adapter isolation (only adapters import SDK/PTB); uncertainty-first, full-report-visible reports (Phase 6 D-04); six-field experiment identity (Phase 6 D-02); three-way paper attribution and no tuning on paper (Phase 7 D-02/D-03); journal-first ordering and full-identity JournalEvents (Phases 7–9); `LIVE_ORDERS_DISABLED` default + explicit human enable (Phase 9 D-04); fail-closed posture; UTC storage with Asia/Ho_Chi_Minh display edge; ApprovalResult value set locked (PENDING/APPROVED/SKIPPED/EXPIRED) — planner must not relitigate.
- Phase 9 status note: STATE.md shows Plan 09-04 blocked at a human testnet/credential/LIVE-TAP checkpoint. Phase 10 planning proceeds on backtest + paper evidence and must not depend on live rows existing; live-5 slices populate when live journal rows appear.

### Deferred Ideas (OUT OF SCOPE)

- Live web dashboard / FastAPI-served UI, interactive charts, auth — deferred (V1 edge is webhook/health only; revisit only with a measured need).
- Telegram interactive analytics commands — deferred; only an optional one-way summary pointer is in scope.
- Automated parameter/threshold recommendations from MFE/MAE (TP/SL tuning suggestions) — out of scope; would violate no-tuning-on-paper/live and D001; any threshold amendment follows the protocol-amendment path after ≥3 families of Validation evidence.
- Regime-model upgrades, OI/funding as features, 15M refinement, extra families (REFN-01–05) → v2 requirements.
- Multi-venue analytics / ccxt research data → later, never on order paths.

</deferred>
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| JRN-01 | Journal/analytics reports MFE/MAE, execution-quality latencies, approval-delay impact, and robustness slices without hiding the full report | Sections "Input Inventory" (what timestamps/fields actually exist), "Metric Definitions", "Architecture Patterns" (pure analytics package, normalized input record, digest contract), "Common Pitfalls" P1-P8. Key constraint discovered: no `seen` timestamp is emitted anywhere; PaperRecord is not persisted or wired; TradeRecord has no regime/session/stop fields. |
| GOV-01 | Kill-gate dashboard tracks the 3-families / 6-months budget and preserves NO_TRADE / INSUFFICIENT EDGE as a valid terminal outcome | Sections "Kill-Gate Research" (clock start verified, family registry, D013 vs protocol discrepancy, acceptance-outcome input problem), "Enablement composition", "Doc reconciliation tasks". Key constraint discovered: acceptance thresholds are TBD in the frozen protocol, so a family PASS cannot be machine-derived - it must be an explicit recorded human decision input. |
</phase_requirements>

## Summary

Phase 10 is a read-only analytics layer plus a small deterministic governance evaluator, built on top of records Phases 3-9 already produce. The repo already contains every reusable primitive the CONTEXT names: `src/backtest/report.py` (Decimal stats, block bootstrap, `DualUniverseSection`, `LIVE5_SYMBOLS`), `src/domain/canonical.py::sha256_hex` (canonical-JSON digest, rejects floats and sets), `src/domain/journal.py::content_hash_event_id`, `src/paper/journal.py::paper_records_digest` (digest precedent), and `src/execution/enablement.py` (`LIVE_ORDERS_DISABLED` posture). No new library is required; nothing is installed in this phase.

Research surfaced six facts that change how the plan must be sliced. (1) **There is no "seen" timestamp anywhere** - `SignalStatus.VIEWED` exists but no code emits it or stores a `viewed_at`; the documented `seen_at if available` (SIGNAL_AND_ALERTS §7) and `NOTIFY_OUTCOME` (only in a docstring) are never journaled. Signal-to-seen latency must therefore render as `INCOMPLETE` (explicit "not measured"), with `Approval.requested_at_utc` as the only delivery proxy. (2) **`PaperRecord` is a pure assembler that is not wired into `run_paper_tick` and has no table or mapper** - "paper evidence" today exists only as in-memory dataclasses/fixtures, and the paper approval time is a synthetic `signal + 30s` constant. (3) **`TradeRecord` carries no stop price, regime, volatility, or session** and no MFE/MAE code exists anywhere (greenfield), so slices need a defined tag-sourcing rule with an `UNKNOWN` bucket. (4) **`ExperimentRecord` stores neither `strategy_id` (family) nor an acceptance outcome**, and the frozen protocol keeps every numeric acceptance threshold `TBD`; the family mapping is recoverable by re-hashing `params/` (verified), but a family PASS can only be an explicit human-recorded input. (5) **`RESEARCH_PROTOCOL.md` §"Kill gate D013" is not merely an AND/OR wording slip - as written it fires on day one** (`fewer than three ... OR fewer than six months`); three other documents agree with D013. (6) **No migration is needed** for `KILL_GATE_EVALUATION` (`journal_events.event_type` is `String(64)` with no CHECK), but there is also **no production DB-backed `JournalLike`** and no journal reader - the CLI edge must supply both.

**Primary recommendation:** Build `src/analytics/` as a pure package around one normalized frozen input record (`TradeOutcome`) with tracer-first slicing (MFE/MAE + digest on backtest `TradeRecord` first, then latency/approval-delay/slices, then the kill-gate evaluator + doc reconciliation + enablement composition, then render/CLI/adapters), keep the report path strictly read-only, and make `KillGateState` a GLOSSARY-canonical enum in `src/domain/enums.py` so `LiveEnablementController.enable()` can refuse on `INSUFFICIENT_EDGE` without importing analytics.

## Architectural Responsibility Map

This is not a browser/SSR system; the relevant tiers are the project's own layers (ARCHITECTURE §3 keeps "UI -> direct Binance order API" forbidden).

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| MFE/MAE, latency, approval-delay, slice math | Pure core (`src/analytics/`, stdlib + Decimal) | - | D-01: metric functions take frozen dataclasses in, return frozen dataclasses out; no I/O, no clock, no RNG except explicitly seeded `random.Random` |
| Digest stamping of reports | Pure core | - | Same contract as `src/backtest/report.py` and `paper_records_digest` |
| Kill-gate state evaluation (D013) | Pure core | Domain enum (`KillGateState` in `src/domain/enums.py`) | Deterministic function of (families, clock start, evaluated_at, prior events); enum shared so `src/execution/enablement.py` needs no analytics import |
| Journal / entity row reading (Signal, Approval, Order, Fill, Position, JournalEvent) | Adapter edge (`src/adapters/`, SQLAlchemy async) | - | Only edges touch DB; existing `journal_from_row` mapper + `session_scope` reused |
| 1m candle reading for MFE/MAE | Adapter edge (Polars/DuckDB over Hive Parquet `data/raw/interval=1m/...`) | - | TECHNOLOGY_STACK confines Polars/DuckDB to research adapters; pure core receives `tuple[Candle, ...]` |
| `KILL_GATE_EVALUATION` persistence | Adapter edge (append-only INSERT via `journal_to_row`) | Pure core builds the `JournalEvent` | No production `JournalLike` exists; edge supplies one. Idempotent by content-hash PK |
| Family registry snapshot (families, sheet hashes, param-set hashes) | Adapter edge (filesystem: `params/`, `docs/research/families/`) | Pure core validates | File reads at edge; pure evaluator receives fingerprints |
| Live-disabled effect of terminal outcome | `src/execution/enablement.py` (existing owner of the flag) | Domain enum | Composes with existing fail-closed flag; adds a refusal, no new order path |
| Report rendering (Markdown + JSON sidecar, optional Telegram pointer) | Render edge (`src/analytics/render.py` pure string building; CLI wrapper) | Adapter (existing `telegram_notify` for optional pointer) | Static, deterministic, no web server (D-04); Asia/Ho_Chi_Minh applied only at display |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib (`decimal`, `dataclasses`, `datetime`, `random`, `json`, `hashlib`, `zoneinfo`, `html`, `enum`) | 3.13.15 [VERIFIED: `uv run python --version` -> `Python 3.13.15`] | All metric math, dataclasses, seeded bootstrap, rendering | D-01 mandates stdlib + Decimal; matches Phase 4-9 purity precedent |
| `src/domain/canonical.py::sha256_hex` | in-repo | Report/evidence digests | `canonical_scalars` rejects `float` and `set`/`frozenset`, normalizes Decimal via `str()` and datetimes to `+00:00` [VERIFIED: src/domain/canonical.py] |
| `src/core/_decimal.py` (`_q`, `_add`, `_sub`, `_mul`, `_div`) | in-repo | Pinned-prec (28) Decimal arithmetic | Single source of truth for Decimal precision [VERIFIED: src/core/_decimal.py] |
| `src/backtest/report.py` (`build`, `UncertaintyReport`, `DualUniverseSection`, `LIVE5_SYMBOLS`, `_decimal_mean/_median/_pstdev`, `_quantile`, `_stationary_block_bootstrap_means`, `_r_multiple`, `_has_zero_risk`) | in-repo | R-multiples, bootstrap intervals, dual-universe framing | CONTEXT: "reuse, do not re-derive" |
| `src/domain/journal.py` (`JournalEvent`, `content_hash_event_id`) | in-repo | `KILL_GATE_EVALUATION` event + deterministic id | Existing append-only contract |
| SQLAlchemy async (`src/db/models.py::session_scope`, `src/db/mappers.py::journal_from_row/journal_to_row`) | `sqlalchemy>=2.0,<2.1` (pyproject) | Read journal/entity rows, append gate event - EDGE ONLY | Already used by collector/CLI paths |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Polars / DuckDB / pyarrow | `polars>=1.44,<2.0`, `duckdb==1.5.5`, `pyarrow>=19` (pyproject) | Read 1m candles from the immutable Hive-partitioned store at the adapter edge | Only inside the candle-reader adapter; convert to `src.core.types.Candle` before entering pure code |
| pytest / pytest-asyncio | `pytest>=9`, `pytest-asyncio>=1.4` (`asyncio_mode = "auto"`) | Test framework (existing) | All Phase 10 tests |
| mypy 2.3.1 / ruff 0.16.8 | [VERIFIED: `uv run mypy --version`, `uv run ruff --version`] | strict typing, lint (line-length 100) | Every new module |
| `zoneinfo` + `tzdata` | tzdata already a dependency | Asia/Ho_Chi_Minh display edge | Render layer only |
| `python-telegram-bot` via existing `src/adapters/telegram_notify.py` | `>=22.8,<23` | Optional one-way summary pointer | Optional; never an approval path, never emits callback data |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Markdown + JSON sidecar | Static HTML | HTML allowed by D-04 but adds an escaping surface (see Security). Recommend Markdown primary + JSON sidecar; HTML only via `html.escape` if wanted |
| Jinja2 templates | f-string/list-join rendering | Jinja is not a dependency and adds nothing for two fixed layouts; keep stdlib |
| Reusing `report.build()` per slice | Own slice statistics | `build()` needs an `experiment_record` and enforces `resamples >= 100`; reuse its private helpers instead for slices (see Pitfall P6 on cost) |

**Installation:** none. No new packages are recommended for this phase.

**Version verification:** no external packages are introduced; tool versions above were read from the running environment this session.

## Package Legitimacy Audit

No external packages are installed by this phase, so the Package Legitimacy Gate produces no rows.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| (none) | - | - | - | - | - | - |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Input Inventory (what actually exists)

### Journal event vocabulary emitted by Phases 7-9 [VERIFIED: grep of `event_type=` across src this session]

| event_type | Emitter | entity_type / entity_id | Useful to Phase 10 |
|------------|---------|-------------------------|--------------------|
| `ENTRY_EXPIRY` | `src/execution/manager.py` (`_build_cancel_event`) | `Order` / client_order_id; payload `{symbol, identifier, trigger_reason, phase}`, `phase` in `pre_cancel` / `cancel_failed` / `post_cancel` | Expiry-without-fill count (count `post_cancel` only; `pre_cancel` and `post_cancel` are twins) |
| `PROTECTIVE_CANCEL` | manager | same pattern | Not needed for metrics |
| `SAFE_MODE_ENTER` / `SAFE_MODE_REENTER` / `SAFE_MODE_EXIT` | `src/reconcile/safe_mode.py` | - | Optional context |
| `ORPHAN_SWEEP` | `src/reconcile/sweeper.py` | - | Not needed |
| `LIVE_ORDERS_ENABLED` / `LIVE_ORDERS_DISABLED` | `src/execution/enablement.py` (`entity_type="LiveEnablement"`, `entity_id="LIVE_ORDERS_DISABLED"`, `correlation_id="execution_enablement"`) | payload `{operator_id, live_orders_disabled, live_orders_disabled_before}` | Dashboard can show current live-enable state |
| `HEALTH_CHECK` | `src/ops/health.py` | `HealthProbe` | Not needed |
| `DRILL_OUTCOME` | `src/ops/drills.py` | - | Not needed |
| `CALLBACK_RECEIVED` / `CALLBACK_RESOLVED` / `CALLBACK_REJECTED` | `src/adapters/telegram_callbacks.py` | `Approval` / `short:{short_id}`; `signal_id`/`approval_id` are **None** on the event | Approval-tap timestamps; join to a signal only via `derive_short_id(signal_id)` (`sha256(signal_id)[:32]`) [VERIFIED: src/approval/mapping.py:44] |
| `NOTIFY_OUTCOME` | **not emitted** - only named in a docstring (src/paper/notify.py:89) | - | No delivery timestamp is journaled |

Pitfall inside the vocabulary: callback receipts use non-content-hash ids (`cb-receipt:{correlation_id}`, `cb-outcome:{short_id}:{ms}:{uuid4 hex[:8]}`), so **never order or dedupe analytics inputs by `journal_event_id`**; sort by `(occurred_at_utc, event_type, entity_id, journal_event_id)` as a total order.

### Entity shapes (frozen dataclasses, Decimal money, UTC-aware datetimes) [VERIFIED: src/domain/*.py read this session]

- `Signal`: `detected_at_utc`, `source_candle_close_utc`, `expires_at_utc`, `status: SignalStatus`, `strategy_id`, `strategy_version`, `parameter_set_id`, `parameter_set_hash`, `symbol`, `direction`, `setup_type`. **No `viewed_at`.**
- `TradePlan`: `entry_min_price`, `entry_max_price`, `stop_loss_price`, `take_profit_json`, `expiry_utc`, `risk_budget`, `suggested_quantity`, `quantity_after_rounding`, `plan_hash`, `created_at_utc`.
- `Approval`: `requested_at_utc`, `acted_at_utc` (None until acted; PENDING must be None, non-PENDING must be set), `status`/`result: ApprovalResult`, `action: ApprovalAction`. ApprovalResult verbatim: `PENDING`, `APPROVED`, `SKIPPED`, `EXPIRED` [VERIFIED: src/domain/enums.py:56-65] (locked; do not relitigate).
- `Order`: `order_role` (ENTRY/STOP/TP/...), `price`, `submitted_at_utc`, `updated_at_utc`, `canceled_at_utc`, `local_status: OrderStatus`, `client_order_id`.
- `Fill`: `fill_price`, `fill_quantity`, `commission`, `realized_pnl`, `fill_time_utc`, `is_maker`, `order_id`.
- `Position`: `opened_at_utc`, `closed_at_utc`, `realized_pnl`, `status`.
- `SignalStatus` includes `NOTIFIED` and `VIEWED`, but only `Signal.detected_at_utc` / `expires_at_utc` / `invalidated_at_utc` carry timestamps.

### Timestamp chain available per evidence source

| Metric leg | Backtest (`TradeRecord`) | Paper (`PaperRecord`) | Live (rows) |
|------------|-------------------------|----------------------|-------------|
| Signal created | via `signal_id` join only | `signal_detected_at_utc` | `Signal.detected_at_utc` |
| Delivered / seen | none | none | `Approval.requested_at_utc` is the only proxy (delivery-request time); true "seen" = **not measured** -> `INCOMPLETE` |
| Approved | n/a (simulated) | `approval_acted_at_utc` = `signal + APPROVAL_DELAY_LAG_SECONDS` (**synthetic constant 30**, src/paper/attribution.py:51) | `Approval.acted_at_utc` |
| Order placed | n/a | `order_submitted_at_utc` | `Order.submitted_at_utc` (role ENTRY) |
| Filled | `entry_time_utc` | `fill_time_utc` | first `Fill.fill_time_utc` for the entry order |
| Entry intended vs actual | plan zone requires `TradePlan` join via `trade_plan_id` | no prices at all on `PaperRecord` | `Order.price` (limit) vs `Fill.fill_price` |
| Exit / PnL / risk | `exit_*`, `realized_pnl`, `realized_risk` | none | `Position` + exit `Fill`s; risk from `TradePlan.risk_budget` |

Consequences the planner must design for: paper approval-delay analytics are **synthetic** (a constant lag), so delay-bucket analysis is only meaningful on live `Approval` rows; opportunity (skipped/expired) rows carry **no hypothetical outcome fields**, so hypothetical outcomes must be supplied by a simulator-run adapter or land in `INCOMPLETE`.

### Backtest / experiment inputs [VERIFIED: src/backtest/simulator.py:117-152, experiment.py:91-146]

`TradeRecord` fields: `trade_id, signal_id, trade_plan_id, strategy_version, parameter_set_hash, symbol, direction, entry_kind, entry_price, entry_time_utc, quantity, exit_kind, exit_price, exit_time_utc, realized_pnl, realized_risk, gross_pnl, entry_fee, exit_fee, funding_amount, slippage_amount, modeled_costs_per_unit, coverage_note, fallback_applied, outcome_kind, reason_code`. `entry_kind` in {ENTRY_FILLED, PARTIAL_FILL, TOUCH_NO_FILL, EXPIRED, INVALIDATION_CANCEL}; `exit_kind` in {SL, TP1, EOD, None}; `outcome_kind` in {OK, REJECT}. **No stop price, no regime, no volatility, no session field.** `report.build()` reads `regime`, `parameter_region`, `exit_time_utc`, `symbol`, `strategy_version`, `fallback_applied`, `coverage_note` from a `Mapping` - these extra keys are supplied by the caller today, not by the simulator.

`ExperimentRecord` fields: `experiment_id, strategy_version, parameter_set_id, parameter_set_hash, data_snapshot_id, code_version, cost_model_hash, time_range_start_utc, time_range_end_utc, universe_hash, run_type, result_summary_json, notes`. `_RUN_TYPES` verbatim: `frozenset({"CANDIDATE", "BASELINE_NO_TRADE", "BASELINE_SIMPLE_TREND"})` (experiment.py:62). **No `strategy_id`, no family, no acceptance outcome, no split label.** `universe_hash` is `sha256_hex({"universe": sorted(universe)})` - symbols themselves are not stored.

### Live-5 vs research universe representation

`LIVE5_SYMBOLS: frozenset[str] = frozenset({"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"})` is defined **twice** - `src/backtest/report.py:34` and `src/execution/manager.py:51` [VERIFIED]. The research universe has **no code definition**; Phase 6 slices it via a caller-supplied `universe_tags` mapping (`"research_universe"` / `"live5_universe"` tags per symbol; `build()` raises if a live5-tagged symbol is not in `LIVE5_SYMBOLS`). Recommendation: import `LIVE5_SYMBOLS` from `src/backtest/report.py` (never a third copy); take the research universe symbols as evidence input and verify `_universe_hash(sorted(symbols)) == ExperimentRecord.universe_hash` (fail closed / label `UNVERIFIED_UNIVERSE`), and render the live-5 slice as an explicit "no data" when empty.

### Persistence facts

- `journal_events` columns: `journal_event_id String(128) PK`, `event_type String(64)`, `entity_type String(64)`, `entity_id String(128)`, `correlation_id String(128)`, five nullable linkage ids, `payload_json String NOT NULL`, `created_at_utc` [VERIFIED: src/db/alembic/versions/0002_domain_registry.py:212-229]. Indexes exist on `correlation_id` and `occurred_at_utc` only. **No CHECK constraint on `event_type`.**
- `content_hash_event_id` returns `"{prefix}_{64-hex}"`; prefix must be non-empty and `<= 63` chars to fit 128 (src/domain/journal.py:20-44).
- **No journal reader and no production `JournalLike` writer exist**: `record(...)` is a Protocol in `enablement.py`, `health.py`, `safe_mode.py`, `sweeper.py`; the only concrete `record` is an in-memory log in `src/ops/drills.py:225`. The phase's CLI edge must own a DB-backed append writer (INSERT ... ON CONFLICT DO NOTHING on the content-hash PK gives idempotency) and a reader.
- **No Order/Fill/Position production writer is confirmed** (Phase 9 plan 09-04 is blocked at a human checkpoint per STATE.md) - live slices will be empty until it lands; that is required to render as "no data".

## Metric Definitions (recommendations within D-02)

D-02 fixes the vocabulary (METRICS §§3-6). The docs leave the following open; each is pinned here and must be pinned again in golden fixtures.

1. **Normalized input record.** One frozen `TradeOutcome` dataclass (Decimal money, UTC datetimes, `evidence: BACKTEST|PAPER|LIVE`, identity tuple, direction, entry/exit prices+times, quantity, `realized_pnl`, `realized_risk`, `exit_kind`, plan zone/limit price when known, plus optional descriptive tags `regime`, `vol_regime`, `session`). Pure normalizers convert `TradeRecord` / `PaperRecord` / live rows into it. Every downstream metric consumes only `TradeOutcome`.
2. **R-multiple** = `realized_pnl / realized_risk` via the existing `_r_multiple`; `realized_risk == 0` excluded and counted via `_has_zero_risk` (WR-10 precedent).
3. **MFE/MAE (price and R).** Over 1m candles in the window `[minute containing entry_time, minute containing exit_time]` inclusive. LONG: `MFE = max(0, max(high) - entry_price)`, `MAE = max(0, entry_price - min(low))`; SHORT mirrored. R form: `excursion_price * quantity / realized_risk` (same denominator as `_r_multiple`, so it needs no TradePlan join). Also `time_to_mfe` / `time_to_mae` (first minute attaining the extreme; earlier candle wins ties) - required by family sheets §7.5. Including the entry and exit minute is conservative (may include pre-fill price within the fill minute); document it as a convention. Missing 1m coverage or a `fallback_applied` trade -> `INCOMPLETE` bucket with reason, never imputed.
4. **METRICS §6 diagnostic questions** are rendered as descriptive distributions only: MFE_R of SL-exit trades ("how far did losers run first"), MAE_R of TP-exit trades, MFE_R vs realized R (give-back), holding-duration distribution. No thresholds, no suggestions (deferred-ideas boundary).
5. **Latency legs** (seconds, `Decimal`): signal->delivered-proxy, delivered->approve, signal->approve, approve->order, order->fill (wait-to-fill). signal->seen is always `INCOMPLETE` until a real VIEWED source exists; the report states that. Rates: fill % (filled entry orders / entry orders), expiry-without-fill rate (`ENTRY_EXPIRY` `post_cancel` events / entry orders, joined by `entity_id == Order.client_order_id`).
6. **Intended vs actual entry deviation**: signed by direction (positive = worse for the trader) against `Order.price` for live, plan zone edge for backtest; in price and in bps of intended.
7. **Approval-delay impact** = three reports (System / User execution / Opportunity) computed over the same metric block, side by side, plus signal->approve delay-bucket table for live rows (bin edges are a documented constant, e.g. `<1m, 1-5m, 5-30m, >=30m` [ASSUMED]). Paper delay is a labelled synthetic constant - surface `APPROVAL_DELAY_LAG_SECONDS` in provenance and do **not** change it in this phase (Phase 7 says it is "calibrated against measured Telegram latency in Phase 10"; report the measured distribution as calibration evidence and leave any constant change to an explicit decision record - see Open Question 4).
8. **Robustness slices** (exactly seven dimensions from METRICS §5): symbol; month; quarter; session; long/short; volatility regime; trend/range regime; plus strategy version. Each slice row: key, `n`, `n_r_valued`, mean R, bootstrap interval when `n_r_valued >= 2` (else explicit "interval absent"), `low_n` flag. Never sort by favorability - sort by stable key. Empty slices render with "no data". `LOW_N_THRESHOLD` is a **display flag only**, not an acceptance threshold (protocol keeps "minimum trade count by slice" TBD) [ASSUMED value: 30].
9. **Tag sourcing.** `direction` and `strategy_version` come from the record; `month`/`quarter`/`session` derive from `entry_time_utc` (or exit time - pick one and pin it; report.py's `_quarter` uses **exit** time). `regime` (BULLISH/BEARISH/NEUTRAL from the 4H EMA50 gate, src/core/strategy.py:98-118) and `vol_regime` are **caller-supplied optional tags**; absent -> `UNKNOWN` slice shown explicitly. `session` and `vol_regime` are **undefined anywhere in the docs** (only "session/time-of-day" and "volatility regime" appear as Stage-D incremental tests). Recommend a documented analytics-only `session` constant (UTC hour bands, e.g. ASIA 00-08 / EUROPE 08-16 / US 16-24) and `vol_regime` deferred to `UNKNOWN` in the tracer with a later optional ATR-percentile derivation - both flagged [ASSUMED]; neither may feed back into strategy.
10. **Uncertainty.** Point estimates carry `n` and, where computable, the Phase-6 stationary block bootstrap (`BootstrapInterval` shape). Use a configurable `resamples` (>= 100, as `build()` enforces) and a deterministic per-slice seed derived from a base seed plus a stable ordinal (never built-in `hash()`).
11. **Evidence separation.** Every report section is labelled BACKTEST / PAPER / LIVE; no pooled headline unless an explicit "POOLED (labelled)" view is added by the planner.

## Kill-Gate Research (GOV-01)

### D013 vs RESEARCH_PROTOCOL discrepancy (verified)

- D013 (docs/DECISIONS.md:17), verbatim: `After 3 independently specified candidate families AND at least 6 months of research, if none passes the acceptance methodology, stop adding strategy complexity, keep live trading disabled, and classify the project as a research/journal platform until a new evidence-backed question is approved` (status `Provisional`).
- IMPLEMENTATION_PLAN "Project kill gate" (docs/implementation/IMPLEMENTATION_PLAN.md:151-159) agrees with D013: `If **3 independently specified candidate strategy families** have been tested under the frozen methodology and **at least 6 months** of research have elapsed without a candidate passing the acceptance methodology, stop adding strategy complexity.`
- Family sheets (trend-pullback.md "V1 family selection") say `kill gate D013 (three families x six months of forward evidence)` - slightly different wording ("forward evidence") but same AND shape.
- RESEARCH_PROTOCOL.md §"Kill gate D013" (line 226) verbatim: `The kill gate fires if: fewer than three **independently specified** candidate families have completed backtest + out-of-sample evidence, **or** fewer than six months of research effort have been invested across those families, **or** any family fails the 10 acceptance gates materially.` As written this is inverted relative to D013: it would fire at project start and after a single failing family. Three documents against one; D013 is authoritative per CONTEXT D-03.

**Where the resolution must be recorded** (Appendix A "Amendment procedure", protocol lines 366-370, and DECISIONS numbering):
1. New DECISIONS.md row **D030** (next free id; last row is D029, no D030/D031 reference exists in docs or STATE.md - verified by grep) stating the resolution, naming the protocol section, and citing D013 as authoritative. Follows the D022-D028 no-silent-rename discipline.
2. Protocol amendment note. Clarification-only (`v1.0.x`) vs semantic (`v1.1.0` per "semantic change to ... acceptance gates") is a judgement call - see Open Question 1. Either way: **do not alter `Frozen on: 2026-09-19`** (it is the research-clock start and witness 1 of the research-gate), keep the D029 row intact (witness 3 greps `protocol v1\.0\.0 frozen|RESEARCH_PROTOCOL.*frozen|frozen.*RESEARCH_PROTOCOL` in DECISIONS.md, `.github/workflows/research-gate.yml`), and keep the DOC_STATUS.md protocol line free of the words `pending-freeze`, `DRAFT`, `Living research` (witness 2 regex). Update the DOC_STATUS version line (Appendix A step 3 pattern) and add its changelog entry.
3. Add a doc-tripwire test so the reconciliation cannot silently regress: DECISIONS has the D030 row; protocol kill-gate paragraph no longer contains the "fewer than ... or" firing conditions; `Frozen on:` still `2026-09-19`.

### Research-clock start (verified from git, not assumed)

- Protocol header: `> **Frozen on:** 2026-09-19` (docs/research/RESEARCH_PROTOCOL.md:5). Date only, no time.
- Freeze commit `281ccd0894ea35717cc741788b6133cfb202af82`, author date `2026-09-19T14:08:12+07:00` (= 2026-09-19T07:08:12Z), message `docs(01-04): research-gate workflow + protocol freeze beat (D029)`; diff flips `Status: DRAFT` -> `FROZEN` and `Frozen on:` -> `2026-09-19` [VERIFIED: `git show 281ccd0`]. First project commit is `2026-09-19 00:16:24 +0700`.
- Recommendation: clock start = header date parsed at the edge with the same regex the CI gate uses (`^>\s*\*\*Frozen on:\*\*\s*[0-9]{4}-[0-9]{2}-[0-9]{2}`), taken as `2026-09-19T00:00:00Z`, with provenance `{source: docs/research/RESEARCH_PROTOCOL.md header, freeze_commit: 281ccd0..., commit_author_date: 2026-09-19T14:08:12+07:00}` recorded in every evaluation. This is independent of git at runtime (reproducible in CI and in tests). "6 months" = 6 **calendar** months (add-months with day clamping, pure stdlib helper; no python-dateutil dependency): earliest possible `INSUFFICIENT_EDGE` is `2027-03-19`. The kill gate therefore cannot legitimately be terminal in the near term - tests must use injected `evaluated_at` values.
- What "research effort" means (elapsed wall-clock since freeze vs cumulative effort) is an assumption; wall-clock is the only deterministic, auditable reading (Assumption A3).

### Family registry and "independently specified" (verified)

- `params/` contains exactly three strategy directories = the three families: `trend-pullback`, `breakout-retest`, `range-mr`, with parameter sets (`baseline-v1/v2/v3`, plus `baseline-no-trade-v1` and `baseline-simple-trend-v1` under trend-pullback, which are **baselines, not candidates**) [VERIFIED: `PYTHONPATH=. uv run python` loading every set through `load_parameter_set`; all 10 hashes distinct].
- `parameter_set_hash` payload includes `strategy_id` (src/domain/registry.py:398-403), so hashes are distinct across families **by construction** - a "distinct hash" test alone is vacuous. Independence therefore needs: distinct `strategy_id`, **and** a family sheet at `docs/research/families/<strategy_id>.md` carrying the 7-slot template (`## 1.`..`## 7.` headings; verified present in all three sheets), **and** distinct sheet content hashes (sha256 of file bytes, recorded at evaluation; sheets are `Status: HYPOTHESIS - NOT FROZEN`, so bind by recording, not by pinning).
- `ExperimentRecord` has no `strategy_id`; recover family by building `{parameter_set_hash -> (strategy_id, parameter_set_id)}` from a registry scan (edge) and looking up `record.parameter_set_hash`. Unknown hash -> family `UNKNOWN`, counted, never guessed. Exclude `run_type != "CANDIDATE"` and `baseline-*` sets from "families tested".
- Family sheets carry an `## Acceptance status` checklist (`Backtested on the same split ...: NO`, `Out-of-sample validated: NO`, `Forward tested: NO`, ...) - a hand-edited status block, useful as display evidence but too soft to drive the gate.

### The acceptance-outcome problem (biggest design constraint for GOV-01)

Protocol §4 "Thresholds remain TBD": expectancy magnitude, drawdown ceiling, loss-streak ceiling, OOS margin, minimum trade count are all `TBD` until real data. Therefore `passes the acceptance methodology` **cannot be computed** by code. Recommended model:

- A per-family `FamilyEvidence` input: `family_id`, `sheet_sha256`, `param_set_hashes`, `experiment_ids`, `status in {NOT_TESTED, TESTED_FAIL, TESTED_PASS}`, and `decision_ref` (required non-empty for TESTED_PASS / TESTED_FAIL: a DECISIONS.md id or journaled human decision). Status comes from a **recorded human decision**, not from the evaluator.
- Per-gate display (10 gates, protocol §4): each gate is one of `MET`, `NOT_MET`, `PENDING_THRESHOLD_TBD`, `NOT_EVALUATED`. Only evidence-existence gates can be machine-derived (3 costs modeled: `cost_model_hash` present; 7 reproducible: `verify_experiment` / stored `trades_digest`; 8 uncertainty: report present; 10 baseline-compared: baseline summaries present; 4/9: by-symbol/quarter counts show dominance). Judgement gates (5 OOS consistent, 6 drawdown tolerable, threshold-bearing parts) render `PENDING_THRESHOLD_TBD`. Never fabricate a pass.
- "Tested" = at least one CANDIDATE experiment exists **and** a recorded `TESTED_*` decision; ExperimentRecord has no split label, so "Development + Validation evidence" cannot be verified from the record alone (Open Question 3).

### State machine (D-03, restated as an evaluator contract)

`evaluate(evidence, clock_start, evaluated_at_utc, prior_events, human_resets) -> KillGateVerdict`:
- `INSUFFICIENT_EDGE` if `tested_independent_families >= 3` AND `elapsed >= 6 calendar months` AND no family is `TESTED_PASS`; **sticky**: if any prior `KILL_GATE_EVALUATION` with state `INSUFFICIENT_EDGE` exists and no later explicit human reset event exists, the state stays `INSUFFICIENT_EDGE` regardless of new evidence (never auto-clears).
- `PASSING_CANDIDATE` if some family is `TESTED_PASS` and the state is not sticky-terminal; records evidence exists, **never** authorizes live.
- else `WITHIN_BUDGET`.
- Reset = a separate, explicit human event (name at planner discretion, e.g. `KILL_GATE_QUESTION_APPROVED`) with non-empty `operator_id` and `decision_ref`; the evaluator only reads it.
- Verdict carries inputs, evidence digest (`sha256_hex`), state, clock-start provenance, `evaluated_at_utc`; the builder returns a `JournalEvent` with `event_type="KILL_GATE_EVALUATION"`, `entity_type="KillGate"`, deterministic `content_hash_event_id(prefix="kill_gate", ...)`. Same evidence + same `evaluated_at` -> same state, digest, and id (idempotent replay; INSERT ... ON CONFLICT DO NOTHING).

### Enablement composition ("keeps live disabled", "blocks family registration")

- `LiveEnablementController.enable(self, *, operator_id, now_utc, health_verdict)` (src/execution/enablement.py:146) has **no kill-gate input**; the controller default is already disabled. To make the terminal outcome fail-closed, add a required keyword `kill_gate_state: KillGateState` and raise `ValueError` before journaling when it is `INSUFFICIENT_EDGE` (mirrors the existing health-verdict refusal). Only 7 `.enable(` call sites exist, all in tests [VERIFIED: grep]; update them.
- Put `KillGateState` in `src/domain/enums.py` (already covered by the no-float AST scan) and add a GLOSSARY section (D016: GLOSSARY is the only source of truth for statuses; precedent: `DailyState` at GLOSSARY §8.1). This lets `enablement.py` stay dependency-free (its module docstring promises stdlib + `src/domain/journal.py` only).
- "Blocks new strategy-family registration": no registration API exists - families are TOML files under `params/` guarded by `.github/workflows/registry-gate.yml`, which re-hashes every TOML against `tests/fixtures/phase4/parameters.json` pins. A journal-only state cannot be read by CI. Minimum viable enforcement: a pure `registration_allowed(state) -> bool` used by the CLI/evaluator plus a documented rule; a stronger option (committed decision-record file that a test compares against `params/` directory names) is a planner decision - Open Question 5.

## Architecture Patterns

### System Architecture Diagram

```
 EVIDENCE SOURCES (read-only)                        EDGE ADAPTERS                    PURE CORE (stdlib + Decimal)                 OUTPUTS
 ---------------------------                         --------------                   ----------------------------                 -------
 Backtest: TradeRecord list + ExperimentRecord ----> normalize_backtest() --+
 Paper:    PaperRecord list (in-memory/fixtures) --> normalize_paper()    ---+--> TradeOutcome[] (frozen, evidence-labelled)
 Live:     Signal/TradePlan/Approval/Order/Fill/     journal_reader          |        |
           Position rows + JournalEvents (Postgres)-> (async SQLAlchemy) ----+        +--> excursion.py (needs 1m Candle tuples <-- candle_reader (Polars/DuckDB over Parquet))
 1m candles: data/raw/interval=1m/... (Parquet) ----> candle_reader ---------------------+--> latency.py / approval_delay.py / slices.py
                                                                                         +--> JournalDepthReport (frozen) --digest()--> render.py --> report.md + report.json (+ digest)
 Registry: params/*/*.toml, docs/research/families/*.md -> family_snapshot (hashes) --+                                                   |
 Protocol header `Frozen on` (+ git provenance) --------> clock_start_reader --------+--> killgate.evaluate() --> KillGateVerdict ---> render.py (dashboard sections)
 Prior KILL_GATE_* events + human reset events ---------> journal_reader ------------+                              |
                                                                                                                    +--> KILL_GATE_EVALUATION JournalEvent --> journal_writer (append, ON CONFLICT DO NOTHING)  [explicit `--record` only]
                                                                                                                    +--> KillGateState --> LiveEnablementController.enable() refuses on INSUFFICIENT_EDGE
 CLI: scripts/dev/journal-report.ps1 --> `uv run python -m src.analytics.cli` (reads clock ONCE at the edge; `--as-of` pins it) ; optional one-way Telegram pointer via existing notify adapter
```

### Recommended Project Structure
```
src/analytics/
├── __init__.py        # barrel, no logic
├── types.py           # TradeOutcome, EvidenceKind, INCOMPLETE reasons, slice/metric result dataclasses
├── inputs.py          # pure normalizers: TradeRecord / PaperRecord / live entities -> TradeOutcome
├── excursion.py       # MFE/MAE (+time-to) over Sequence[Candle]
├── latency.py         # execution-quality legs + fill %, wait-to-fill, expiry rate, entry deviation
├── approval_delay.py  # System / User / Opportunity blocks + delay buckets
├── slices.py          # 7-dimension robustness slices + low-n flag (full report always alongside)
├── report.py          # JournalDepthReport assembly + digest
├── family.py          # FamilyEvidence, independence check (pure over fingerprints), tag mapping
├── killgate.py        # KillGateVerdict, evaluate(), add_months(), event builder
├── render.py          # Markdown + JSON sidecar (pure string building, Asia/Ho_Chi_Minh display edge)
└── cli.py             # EDGE: composes adapters; NOT in the purity scan list
src/adapters/analytics_store.py   # EDGE: async reader (journal + entities), 1m candle reader, append writer
src/domain/enums.py               # + KillGateState (WITHIN_BUDGET, PASSING_CANDIDATE, INSUFFICIENT_EDGE)
scripts/dev/journal-report.ps1    # thin wrapper (see Windows convention)
tests/fixtures/phase10/<case>/{input.json,expected.json}
tests/test_analytics_*.py, tests/test_kill_gate*.py
```
Layout is at planner discretion (D-01); the pure/edge split and the single `TradeOutcome` seam are the load-bearing parts.

### Pattern 1: One normalized, evidence-labelled input record
**What:** All metric code consumes `TradeOutcome`; provenance (six-field identity, `epoch_id`, `universe_hash`, `data_snapshot_id`) rides on it or on a sibling `ProvenanceBlock`.
**When to use:** Always - it is what keeps backtest/paper/live unpooled and lets INCOMPLETE reasons be uniform.
**Example (digest contract - mirror, do not re-invent):**
```python
# Source: src/paper/journal.py::paper_records_digest and src/backtest/report.py::UncertaintyReport.digest
# sort by a total key, hand canonical JSON to sha256_hex (rejects float/set; Decimal -> str)
def report_digest(self) -> str:
    return sha256_hex({"sections": [s.digest() for s in self.sections_in_fixed_order],
                       "provenance": self.provenance_payload,   # includes evaluated/as_of, seeds, vocabulary versions
                       "evidence": self.evidence_kind.value})
```

### Pattern 2: Journal-first gate event through a `JournalLike` seam
**What:** Pure `build_kill_gate_event(verdict) -> JournalEvent`; the edge writer persists it. Mirrors `src/ops/health.py::_record_health_check_event` and `enablement._journal_enablement_event` (content-hash id, `correlation_id` constant, compact `json.dumps(..., separators=(",", ":"))` payload).

### Pattern 3: Tracer-first plan slicing (Phases 4-9 precedent)
Plan 1 tracer: `TradeOutcome` + MFE/MAE + digest on backtest `TradeRecord` end-to-end with a golden fixture (input -> report -> digest). Plan 2: latency + approval-delay + slices (+ paper/live normalizers). Plan 3: D013 doc reconciliation (D030 + protocol amendment + doc-tripwire test) then kill-gate evaluator + `KillGateState` + enablement refusal + event builder. Plan 4: render + edge adapters + CLI + PowerShell wrapper + optional Telegram pointer. Doc reconciliation should land before the evaluator so the evaluator cites a committed decision.

### Anti-Patterns to Avoid
- **Writing from the report path.** Report generation is read-only (D-01). Persisting `KILL_GATE_EVALUATION` is a separate explicit `--record` step and the only write this phase performs.
- **Wall-clock or RNG in pure code.** `evaluated_at_utc` / `as_of` are injected; the CLI reads the clock once. Bootstrap uses `random.Random(seed)` only.
- **`hash()`, set/dict iteration order, or unsorted input for ordering or seeds.** Python str hashing is randomized per process; sort by explicit total keys.
- **Hiding low-n slices, reordering by favorability, or dropping `UNKNOWN`/`INCOMPLETE` buckets** (violates D-02 and METRICS §5).
- **Pooling evidence silently** or treating synthetic paper delay as measured latency.
- **A third `LIVE5_SYMBOLS` copy** or a new symbol list.
- **`float` anywhere in metric math** (also `Decimal(float)`, float literals like `0.5`, `np.float64`): the AST guard flags all of them.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Canonical digest | custom JSON dumper/hasher | `src/domain/canonical.py::sha256_hex` | Already rejects float/set, normalizes Decimal and UTC datetimes |
| Content-hash event id | ad-hoc id (`f"{name}:{ms}"`) | `content_hash_event_id` | Same-ms collisions were review finding WR-09 |
| R-multiple, mean/median/std, quantile, block bootstrap, drawdown | new statistics | `src/backtest/report.py` helpers | Phase-6 verified, Decimal-pinned, seeded; `statistics.*` returns floats |
| Pinned-precision Decimal ops | raw `a / b` | `src/core/_decimal.py` helpers | Ambient-context drift was review CR-04 |
| Dual-universe framing | new structure | `DualUniverseSection` / `LIVE5_SYMBOLS` | Phase 6 D-04 framing is the required presentation |
| Family <-> parameter-set mapping | free-text family flag | registry scan via `load_parameter_set` + `parameter_set_hash` lookup | D-03: independence must not be a free-text flag |
| Calendar-month arithmetic | day-count approximation (`30*6`) | small pure `add_months` with day clamping | `python-dateutil` is not a dependency; day approximations misplace the boundary |
| Journal DB session | new engine plumbing | `make_session_factory` + `session_scope` + `journal_from_row/journal_to_row` | Existing single-Base ORM |
| HTML/Markdown escaping | manual replace | `html.escape` (HTML) / fenced code + table-cell escaping for `|` (Markdown) | Reason codes / notes are DB-sourced text |

**Key insight:** every hard part (determinism, digests, R/bootstrap, event ids, dual-universe framing) already exists and is pinned by tests; this phase's risk is in inputs and definitions, not in algorithms.

## Runtime State Inventory

Not a rename/refactor/migration phase - omitted by rule. (Only additive: one enum, one journal event type, one `enable()` keyword.)

## Common Pitfalls

### P1: Treating a missing timestamp as zero or imputing it
**What goes wrong:** `signal->seen` latency shows a number that was never measured. **Why:** `VIEWED` has no writer; `Approval.requested_at_utc` is a delivery-request proxy, not a read receipt. **Avoid:** an explicit `INCOMPLETE(reason="NO_SEEN_TIMESTAMP")` bucket with counts; label the proxy leg by what it is. **Warning sign:** any latency leg with n equal to total signals on a source that never emits the event.

### P2: Pooling paper's synthetic approval lag with live latency
**What goes wrong:** approval-delay "impact" looks like a real measurement. **Why:** `approval_acted_at_utc = signal + 30s` for every user-executed-sim row. **Avoid:** carry `synthetic_lag=True` in provenance; delay-bucket analysis only over LIVE rows; show the constant's value. **Warning sign:** all paper delays identical (zero variance).

### P3: Kill gate that can "pass" or "fail" a family by itself
**What goes wrong:** a fabricated acceptance result. **Why:** thresholds are TBD in the frozen protocol. **Avoid:** family status is a recorded human decision input; per-gate cells use `PENDING_THRESHOLD_TBD`; `PASSING_CANDIDATE` never authorizes live. **Warning sign:** an evaluator branch that compares expectancy to a numeric constant.

### P4: Family identity by parameter-set hash alone
**What goes wrong:** independence check passes trivially (hash includes `strategy_id`). **Avoid:** strategy_id + sheet template + distinct sheet hash; baselines excluded.

### P5: Clock arithmetic and boundaries
**What goes wrong:** off-by-a-day at the 6-month edge, or naive datetime. **Avoid:** parse header date as UTC midnight, calendar-month add with clamp, `evaluated_at_utc >= start + 6 months` (inclusive) pinned in a boundary fixture (2027-03-18T23:59:59Z -> WITHIN_BUDGET, 2027-03-19T00:00:00Z -> eligible). Do not touch `Frozen on:` when amending the protocol.

### P6: Decimal bootstrap cost explosion
**What goes wrong:** 7+ dimensions x many slices x 10,000 resamples of Decimal arithmetic takes minutes and makes the suite/CLI unusable. **Why:** `_stationary_block_bootstrap_means` is pure-Python Decimal per resample. **Avoid:** make `resamples` a report parameter (default ~1000, floor 100 as `build()` enforces), compute the full-report interval at the higher count, and keep per-slice intervals at the lower count; keep test fixtures small. Seeds: `base_seed + ordinal` where ordinal is the slice's index in a sorted key list.

### P7: `report.build()` private-helper coupling
**What goes wrong:** importing `_decimal_mean`, `_quantile`, `_r_multiple` (underscore names) from another package; a refactor in `report.py` silently breaks analytics. **Avoid:** either promote thin public aliases in `report.py` in an early atomic commit or import them with a comment and cover them by the fixture digests. `int(idx_float)` in `_quantile` is safe (not a `float` call).

### P8: journal-derived joins that silently drop rows
**What goes wrong:** callback events carry `signal_id=None`; `ENTRY_EXPIRY` keys on `client_order_id` in `entity_id`, not `order_id`. **Avoid:** explicit join functions that return `(matched, unmatched_count)` and surface unmatched counts in the report.

### P9: Fill.realized_pnl semantics
**What goes wrong:** live R computed from gross `realized_pnl` ignoring commission/funding. **Avoid:** define live net PnL = sum(`realized_pnl`) - sum(`commission`, converted only if `commission_asset` is the quote asset; else `INCOMPLETE`) and pin it in a fixture. Binance's `realizedPnl` excluding commission is [ASSUMED] from training knowledge - re-verify against current official docs before implementation (project constraint: exchange semantics are never taken from memory).

### P10: Report timestamps breaking byte-identity
**What goes wrong:** rendering `now()`, locale-dependent formatting, or `Decimal` str with exponent (`1E+1`). **Avoid:** inject `as_of`; render Decimals with a pinned `format(d, "f")`/quantize policy; Asia/Ho_Chi_Minh is fixed UTC+7 (no DST) via `zoneinfo`; write files with `newline="\n"` and UTF-8 so Windows CRLF does not change bytes.

## Code Examples

### Decimal-only AST guard - extend by file list only
```python
# Source: tests/test_domain_no_float.py (SCANNED_FILES tuple + _find_float_calls walker)
SCANNED_FILES = (
    # ... existing entries ...
    # Phase 10 - pure analytics (D-01 purity):
    "src/analytics/__init__.py", "src/analytics/types.py", "src/analytics/inputs.py",
    "src/analytics/excursion.py", "src/analytics/latency.py", "src/analytics/approval_delay.py",
    "src/analytics/slices.py", "src/analytics/report.py", "src/analytics/family.py",
    "src/analytics/killgate.py", "src/analytics/render.py",
)
```
`src/analytics/cli.py` and `src/adapters/analytics_store.py` stay out of the list (I/O edges), but forbid `float(` there too by review.

### Journal-first event builder (mirror of the health/enablement builders)
```python
# Source: src/execution/enablement.py::_journal_enablement_event, src/ops/health.py::_record_health_check_event
payload_json = json.dumps(verdict_payload, separators=(",", ":"), sort_keys=True)
event = JournalEvent(
    journal_event_id=content_hash_event_id(prefix="kill_gate", event_type="KILL_GATE_EVALUATION",
        entity_id="KILL_GATE", occurred_at_utc=evaluated_at_utc, payload_json=payload_json),
    occurred_at_utc=evaluated_at_utc, event_type="KILL_GATE_EVALUATION", entity_type="KillGate",
    entity_id="KILL_GATE", correlation_id="analytics_kill_gate", payload_json=payload_json)
```
(`event_type`/`entity_type` are free validated non-empty strings; the literals above are the CONTEXT's suggested names, planner may rename. Payload Decimals must be `str` - `json.dumps` cannot serialize `Decimal`.)

### Enablement refusal (mirror of the health-verdict refusal)
```python
# Source pattern: src/execution/enablement.py:146-176 (enable() raises ValueError BEFORE journaling)
if kill_gate_state is KillGateState.INSUFFICIENT_EDGE:
    raise ValueError("enable: kill gate is INSUFFICIENT_EDGE (terminal); live stays disabled "
                     "until an explicit human decision record clears it")
```

## Windows / PowerShell wrapper convention (verified)

`scripts/dev/*.ps1` pattern [VERIFIED: _common.ps1, test.ps1, migrate.ps1, README.md]: dot-source `_common.ps1` (`$ErrorActionPreference='Stop'`, `Push-Location` to repo root, `Assert-Uv`, `Import-DotEnv`, `Set-ScopedEnv`, `Exit-RepoRoot` in `finally`), call `uv run ...`, capture `$LASTEXITCODE`, `exit $code`. Add `scripts/dev/journal-report.ps1` (params such as `-AsOf`, `-OutDir`, `-Record`, `-Universe`) invoking `uv run python -m src.analytics.cli @args`, and add a row to `scripts/dev/README.md`. Default output under `data/reports/` - `data/` is already git-ignored (.gitignore line 18) with only `!src/data/` re-included, so reports containing account PnL never enter git (no `.gitignore` edit needed). Run form: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev/journal-report.ps1`. Note `python` on PATH is 3.14.3 while `uv run` resolves the project's 3.13.15 - always go through `uv run`.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `PaperRecord` as an in-memory assembler with "Parquet extraction deferred to Phase 10" (src/paper/journal.py docstring) | Phase 10 decides whether paper evidence is extracted/persisted | Phase 7 deferral | Planner must choose: accept `PaperRecord` lists as an input contract (fixtures/extract file) vs build a Parquet extract; recommendation: input contract + optional JSON/Parquet extract adapter, no new operational table (D-05) |
| Protocol kill-gate OR-list | D013 AND-with-none-passing | D030 (this phase) | Evaluator implements D013 only |

**Deprecated/outdated:** the protocol §4 kill-gate wording (to be superseded by the D030 amendment).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `session` buckets = UTC hour bands ASIA 00-08 / EUROPE 08-16 / US 16-24 (analytics-only constant) | Metric Definitions 9 | Slice vocabulary becomes the reporting contract that kill-gate evidence cites (D-02 "costly"); user may want other session definitions |
| A2 | `LOW_N_THRESHOLD` = 30 as a display flag only; delay-bucket edges `<1m, 1-5m, 5-30m, >=30m` | Metric Definitions 7-8 | Cosmetic, but pinned in golden fixtures - changing later changes digests |
| A3 | "6 months of research effort" = 6 calendar months of wall-clock since the protocol freeze date, clock start `2026-09-19T00:00:00Z` | Kill-Gate Research | If the user counts effort differently (e.g. from first project commit 2026-09-18T17:16Z or actual paper start), the earliest terminal date shifts by days/months |
| A4 | Volatility-regime and trend/range tags are caller-supplied optional with `UNKNOWN` fallback (tracer); NEUTRAL->RANGE, BULLISH/BEARISH->TREND mapping | Metric Definitions 9 | Slices may be mostly `UNKNOWN` until a derivation lands |
| A5 | Family acceptance status is a recorded human decision (`decision_ref`), never machine-derived | Kill-Gate Research | If the user expects automatic PASS/FAIL, thresholds must first be proposed and recorded per protocol §4 (after >=3 families) - not possible in this phase |
| A6 | MFE/MAE window includes the entry and exit minute candles; excursion measured on 1m high/low | Metric Definitions 3 | Slightly conservative excursions; must match the pinned fixture |
| A7 | Binance `Fill.realizedPnl` excludes commission and funding is absent from `Fill` | Pitfall P9 | Live R misstated; re-verify against official docs before implementing live normalizer |
| A8 | Protocol amendment classified as clarification (`v1.0.1`) rather than semantic (`v1.1.0`) | Kill-Gate Research | Semantic bump triggers "new strategy-version lineage" text in the protocol; user decision (Open Question 1) |
| A9 | Elapsed-time tests use injected `evaluated_at` values; the gate cannot legitimately be terminal before 2027-03-19 | Kill-Gate Research | None functional; documents expectation |
| A10 | Suggested event/state names (`KILL_GATE_EVALUATION`, `KillGateState`, reset event name, `entity_type="KillGate"`) | Architecture | Names at planner discretion per CONTEXT; changing after first persisted event is one-way |

## Open Questions

1. **Protocol amendment class for the kill-gate wording.**
   - Known: D013 + IMPLEMENTATION_PLAN + family sheets agree; protocol §4 disagrees (fires on day one); Appendix A splits `v1.0.x` (wording) from `v1.1.0` (semantic change to gates).
   - Unclear: whether correcting a transcription error that changes firing behavior counts as "semantic".
   - Recommendation: record D030 as a *correction to conform to authoritative D013* with a `v1.0.1` header bump that leaves `Status`/`Frozen on` lines untouched; surface for user confirmation because a `v1.1.0` bump carries downstream lineage obligations.
2. **What "independently specified" additionally requires beyond distinct strategy_id + template + sheet hash.**
   - Known: the three sheets share one template and explicit "mutually-comparable" framing; A and C share the regime detector (family C reuses A's R1), B reuses A's 4H direction gate.
   - Unclear: whether shared detector components disqualify independence.
   - Recommendation: treat the sheets as independently specified (the roadmap Phase 1 success criterion already asserts it) and record the shared-component note in the dashboard rather than blocking on it.
3. **Development vs Validation split evidence.** `ExperimentRecord` has no split label; protocol says "tested" means backtest + OOS evidence. Recommendation: require the human decision record to name the experiment ids for each split; do not infer from time ranges.
4. **Approval-lag constant calibration.** Phase 7 promised Phase 10 calibration of `APPROVAL_DELAY_LAG_SECONDS`. Recommendation: report measured live signal->approve distribution as evidence and leave the constant unchanged (changing it is a code+decision change and touches the no-tuning-on-paper lock).
5. **Enforcement depth for "blocks new strategy-family registration".** Options: (a) pure predicate + documentation, (b) committed decision-record file plus a pytest that fails if `params/` gains a strategy directory while the record says `INSUFFICIENT_EDGE`. Recommendation: (b) - CI can read a committed file, not the journal.
6. **Where paper evidence comes from at runtime.** `PaperRecord` is unpersisted and unwired. Recommendation: accept it as an input contract now; a persisted paper extract is a separate decision (D-05 forbids new operational tables).
7. **Optional Telegram summary.** Reuse `src/adapters/telegram_notify.py` only if a plain-text send helper exists without callback buttons; otherwise skip (optional per D-04).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python via `uv run` | all code + tests | yes | 3.13.15 (system `python` is 3.14.3 - do not use) | - |
| uv | env/task runner | yes | 0.12.20 | - |
| pytest suite | tests | yes | collects successfully (`uv run pytest --collect-only -q`) | - |
| mypy / ruff | quality gates | yes | 2.3.1 / 0.16.8 | - |
| PowerShell | wrapper | yes (project primary shell) | - | Bash/`uv run` directly |
| PostgreSQL (Docker Compose) | live/journal adapter integration test | not probed | - | Adapter tests use in-memory fakes/`JournalLike`; a PG-backed test may be marked skipped like `tests/test_domain_mappers_pg.py` |
| 1m Parquet data (`data/raw/interval=1m/...`) | real-data MFE/MAE | not probed (git-ignored, machine-local) | - | Fixture candles; missing coverage -> `INCOMPLETE` |
| Network / Binance / Telegram | none (report path) | not required | - | Report path must not need them |

**Missing dependencies with no fallback:** none.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >= 9 with pytest-asyncio (`asyncio_mode = "auto"`), `testpaths = ["tests"]`, `addopts = "-q"` [VERIFIED: pyproject.toml] |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, `[tool.mypy] strict = true`, `[tool.ruff]` line-length 100) |
| Quick run command | `uv run pytest tests/test_analytics_*.py tests/test_kill_gate*.py -x` |
| Full suite command | `scripts/dev/test.ps1` (wraps `uv run pytest`; extra args forwarded) or `uv run pytest` |
| Static gates | `uv run mypy src` (strict), `uv run ruff check src tests`, `uv run python scripts/check_migration_parity.py` (should stay green with zero schema change) |

### Fixture and precedent conventions
- Fixtures: `tests/fixtures/phase10/<case>/input.json` + `expected.json` (Phase 6/7/9 layout; e.g. `tests/fixtures/phase6/report_slices/{input.json,expected.json}` with `EXPECTED_REPORT_DIGEST` pinned). Money as strings, datetimes ISO `+00:00`.
- Digest tests (Phase 6 precedent, tests/test_backtest_report.py): pinned-digest equality; same-seed rebuild identical; different seed -> different interval digest.
- AST no-float guard: extend `SCANNED_FILES` in `tests/test_domain_no_float.py` (walker flags `float(...)`, float literals, `Decimal(<float>)`, `np.float64` etc.).
- Domain purity/import-boundary precedent: `tests/test_domain_boundary.py`, `tests/test_adapter_strictness.py`; add an analytics purity test asserting no `polars|pandas|numpy|sqlalchemy|pydantic|fastapi|binance|telegram` imports in the pure modules.
- Enum verbatim tests: `tests/test_domain_enums.py` style for `KillGateState`.

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| JRN-01 | MFE/MAE price+R, time-to-extreme, LONG/SHORT, zero-risk excluded+counted | unit + golden | `uv run pytest tests/test_analytics_excursion.py -x` | Wave 0 |
| JRN-01 | INCOMPLETE bucket (no fill, no 1m coverage, no seen timestamp) never imputed | unit + golden | `uv run pytest tests/test_analytics_incomplete.py -x` | Wave 0 |
| JRN-01 | Latency legs, fill %, wait-to-fill, expiry-without-fill, entry deviation | unit + golden | `uv run pytest tests/test_analytics_latency.py -x` | Wave 0 |
| JRN-01 | System/User/Opportunity reports side by side; synthetic-lag labelling | unit | `uv run pytest tests/test_analytics_approval_delay.py -x` | Wave 0 |
| JRN-01 | Seven slice dimensions, low-n flagged not hidden, full report alongside, stable ordering | unit + golden | `uv run pytest tests/test_analytics_slices.py -x` | Wave 0 |
| JRN-01 | Empty live-5 slice renders "no data"; evidence kinds never pooled | unit | `uv run pytest tests/test_analytics_dual_universe.py -x` | Wave 0 |
| JRN-01 | Byte-identical digest regeneration; different inputs/seed -> different digest | determinism | `uv run pytest tests/test_analytics_digest.py -x` | Wave 0 |
| JRN-01 | Pure-module float/import guards | static | `uv run pytest tests/test_domain_no_float.py tests/test_analytics_purity.py -x` | extend existing + Wave 0 |
| GOV-01 | WITHIN_BUDGET / PASSING_CANDIDATE / INSUFFICIENT_EDGE transitions incl. 6-month boundary (2027-03-18T23:59:59Z vs 2027-03-19T00:00:00Z) | unit + golden | `uv run pytest tests/test_kill_gate_state.py -x` | Wave 0 |
| GOV-01 | Sticky terminal + reset only via explicit human event; never auto-clears | unit | `uv run pytest tests/test_kill_gate_sticky.py -x` | Wave 0 |
| GOV-01 | Clock-start provenance from protocol header (regex identical to research-gate) | unit | `uv run pytest tests/test_kill_gate_clock.py -x` | Wave 0 |
| GOV-01 | Independence: distinct strategy_id + template + sheet hash; baselines excluded; unknown hash -> UNKNOWN | unit | `uv run pytest tests/test_kill_gate_families.py -x` | Wave 0 |
| GOV-01 | `KILL_GATE_EVALUATION` event: content-hash id, idempotent replay, inputs+digest in payload | unit | `uv run pytest tests/test_kill_gate_event.py -x` | Wave 0 |
| GOV-01 | `enable()` refuses on INSUFFICIENT_EDGE before journaling; existing enable tests updated | unit | `uv run pytest tests/test_execution_enablement.py -x` | extend existing |
| GOV-01 | Doc tripwire: D030 row present, protocol `Frozen on` unchanged, kill-gate paragraph matches D013 | doc-parity | `uv run pytest tests/test_kill_gate_docs.py -x` | Wave 0 |
| GOV-01 | NO_TRADE counts by reason category incl. `UNMAPPED` bucket; `INSUFFICIENT_EDGE` rendered as terminal not error | unit + render | `uv run pytest tests/test_analytics_render.py -x` | Wave 0 |
| Both | Render byte-identity (Markdown + JSON sidecar, digest embedded, LF newlines, Asia/Ho_Chi_Minh display) | golden | `uv run pytest tests/test_analytics_render.py -x` | Wave 0 |
| Both | No migration: parity gate green, `journal_events` unchanged | script | `uv run python scripts/check_migration_parity.py` | exists |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_analytics_*.py tests/test_kill_gate*.py -x` plus `uv run mypy src/analytics`.
- **Per wave merge:** `uv run pytest` + `uv run mypy src` + `uv run ruff check src tests`.
- **Phase gate:** full suite green + migration parity green before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/fixtures/phase10/` cases: `complete_trade`, `incomplete_no_fill`, `incomplete_no_1m`, `zero_risk_excluded`, `short_trade`, `empty_live5_slice`, `opportunity_skipped_expired`, `low_n_slices`, `kill_within_budget`, `kill_passing_candidate`, `kill_insufficient_edge`, `kill_clock_boundary`, `kill_sticky_reset`, `clock_start_provenance`, `idempotent_replay`, `digest_regeneration`, `render_golden`
- [ ] `tests/test_analytics_*.py`, `tests/test_kill_gate_*.py` (list above)
- [ ] Extend `SCANNED_FILES` in `tests/test_domain_no_float.py`; update 7 `.enable(` call sites (tests/test_execution_enablement.py, test_execution_health.py, test_execution_manager.py)
- [ ] `KillGateState` enum + verbatim enum test; GLOSSARY section
- Framework install: none - pytest/mypy/ruff already present.

## Security Domain

`security_enforcement` is enabled (absent = enabled; config `security_asvs_level: 1`).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (no service, no login) | - |
| V3 Session Management | no | - |
| V4 Access Control | yes (limited) | Terminal-outcome reset and family-registration unblock require explicit human `operator_id` + `decision_ref` (non-empty validated, journaled); optional Telegram summary carries no callback data and cannot approve anything |
| V5 Input Validation | yes | Treat `payload_json` and DB text as untrusted: `json.loads` inside try/except -> `INCOMPLETE`/rejected row counted, never a crash or silent skip; validate UTC-aware datetimes and Decimal-parseable strings; escape text on render |
| V6 Cryptography | yes (integrity only) | `hashlib.sha256` via `sha256_hex`; no custom crypto; no secrets involved |
| V7 Error handling / logging | yes | Reports and journal payloads must be secret-free (mirror the Phase-9 log-scan tests, `tests/test_execution_secret_posture.py`); never render exception messages containing request material (journal exception TYPE only, as `manager._build_cancel_event` does) |
| V8 Data protection | yes | Report output contains account PnL: write only under git-ignored `data/reports/`; refuse output paths outside the chosen root (no `..` traversal) |
| V12 Files | yes | CLI writes only to the resolved output dir; reads only `params/`, `docs/research/families/`, protocol header (fixed paths) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Injection via journal `payload_json` / reason-code text into HTML/Markdown report | Tampering | `html.escape` for HTML; escape `|` and newlines in Markdown table cells; prefer Markdown + JSON |
| Gate bypass by mutating the terminal state (auto-clear) | Elevation of privilege | Sticky terminal state; reset only by a separate journaled human event; evaluator never writes a reset |
| Repudiation of a terminal outcome | Repudiation | Append-only `KILL_GATE_EVALUATION` with content-hash id, inputs, evidence digest, evaluated-at |
| Fabricated PASS to unlock live | Spoofing/Tampering | PASS requires `decision_ref`; `PASSING_CANDIDATE` never enables live (needs separate decision record per IMPLEMENTATION_PLAN) |
| Path traversal on `--out` | Tampering | Resolve and confine to the reports root |
| Secrets in reports/logs | Information disclosure | Payload allow-lists (keys explicitly enumerated); reuse the secret-substring scan test approach |
| Read path mutating operational tables | Tampering | Reader adapter uses SELECT only; only the explicit `--record` path INSERTs a single event type |

## Sources

### Primary (HIGH confidence - in-repo files read this session)
- `src/domain/{journal,order,fill,position,approval,signal,trade_plan,canonical,enums,registry}.py`
- `src/paper/{journal,attribution,notify,loop,__init__}.py`, `src/backtest/{report,experiment,simulator}.py`
- `src/execution/{enablement,manager}.py`, `src/ops/health.py`, `src/adapters/telegram_callbacks.py`, `src/approval/mapping.py`
- `src/db/{models,mappers}.py`, `src/db/alembic/versions/0002_domain_registry.py`, `scripts/check_migration_parity.py`
- `docs/DECISIONS.md` (D013, D029), `docs/research/RESEARCH_PROTOCOL.md` (§0, §4 kill gate, Appendix A), `docs/implementation/IMPLEMENTATION_PLAN.md`, `docs/backtest/METRICS.md`, `docs/data/DATA_MODEL.md` §2.10/§6, `docs/trading/SIGNAL_AND_ALERTS.md` §7, `docs/research/families/*.md`, `.github/workflows/{research-gate,registry-gate}.yml`
- `pyproject.toml`, `.gitignore`, `scripts/dev/*`, `tests/test_domain_no_float.py`, `tests/test_backtest_report.py`, `tests/conftest.py`
- `git show 281ccd0` (freeze commit), `git log` (first commit), `PYTHONPATH=. uv run python` registry scan, `uv run` tool version probes

### Secondary (MEDIUM confidence)
- AGENTS.md project stack constraints (pre-verified by earlier project research; no new external lookups this phase)

### Tertiary (LOW confidence)
- Binance `realizedPnl` commission semantics (training knowledge, tagged A7; re-verify before live normalizer)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - stdlib + existing in-repo primitives; no packages added; versions probed.
- Architecture: HIGH for pure/edge split and seams (verified against Phase 4-9 precedent); MEDIUM for exact module layout (planner discretion).
- Input inventory / gaps: HIGH - every claim traced to a file read or a command run this session.
- Metric vocabulary (session, vol regime, low-n): MEDIUM/LOW - docs leave these open; flagged A1-A4.
- Pitfalls: HIGH for repo-derived (P1-P8, P10); MEDIUM for P9 (exchange semantics unverified).

**Research date:** 2026-09-29
**Valid until:** ~2026-10-29 for repo facts, but re-verify Phase 9 outputs (live Order/Fill writers, any new journal event types) at plan time because Plan 09-04 is still blocked; exchange-semantic claims (A7) must be re-verified against current Binance docs before any live-row normalizer is implemented.
