# Phase 10: Journal Depth + Kill-Gate Operations - Context

**Gathered:** 2026-09-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 10 delivers honest analytics and an institutional stop rule on top of the journal rows Phases 6–9 already emit. (1) Journal/analytics reports MFE/MAE, execution-quality latencies (signal→seen, signal→approve, approve→order, intended→actual entry deviation, fill %, wait-to-fill, expiry-without-fill), approval-delay impact (system vs user-execution vs opportunity reports), and robustness slices — always with the full unsliced report visible (JRN-01). (2) A kill-gate dashboard tracks the D013 budget (3 independently specified families AND ≥6 months of research) with live-5 vs research-universe slices, and records `NO_TRADE / INSUFFICIENT EDGE` as a valid terminal outcome that keeps live disabled (GOV-01). No new strategy families, no parameter tuning from analytics, no auto-enabling of live, no new order paths, no web service. Analytics must work on backtest + paper evidence and on live rows when they exist — Phase 9 live orders are not a prerequisite for the report to render; an empty live-5 slice is displayed explicitly as "no data", never hidden or imputed.

</domain>

<decisions>
## Implementation Decisions

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

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Analytics + metrics contract (JRN-01)

- `docs/backtest/METRICS.md` — §3 system/user/opportunity reports, §4 execution-quality metrics, §5 robustness dimensions ("full report must remain visible"), §6 MFE/MAE, §7 daily PnL as output not constraint, §8 statistical uncertainty.
- `docs/backtest/BACKTEST_SPEC.md` — §§1–13: 1m intrabar semantics, costs-from-run-#1, six-field identity, acceptance gates and "Statistical power and uncertainty" the reports must respect.
- `docs/data/DATA_MODEL.md` — §2.7 Order identifiers, §2.8 Fill as event, §2.10 JournalEvent (append-only, not a substitute for current-state tables).
- `docs/trading/SIGNAL_AND_ALERTS.md` — signal/approve/expire timestamp lineage the latency metrics derive from.
- `docs/GLOSSARY.md` — canonical enum/status/reason-code vocabulary (OrderStatus, ApprovalResult, NO_TRADE categories).

### Kill gate + governance (GOV-01)

- `docs/DECISIONS.md` — D013 (kill gate, Provisional: ≥3 independently specified families AND ≥6 months, none passing → stop adding complexity, keep live disabled, research/journal platform); D001 determinism; Phase-1 D022–D028 no-silent-rename precedent for recording the AND/OR resolution.
- `docs/research/RESEARCH_PROTOCOL.md` — FROZEN v1.0.0: §"Kill gate D013" (AND/OR wording to reconcile), NO_TRADE first-class outcome + reason categories, 10 acceptance gates, freeze timestamp (research-clock provenance).
- `docs/implementation/IMPLEMENTATION_PLAN.md` — "Project kill gate" section and live-rollout gates; a passing candidate still needs a separate decision record.
- `docs/research/families/trend-pullback.md`, `docs/research/families/breakout-retest.md`, `docs/research/families/range-mr.md` — the three independently specified family sheets (7-slot template) the "independently specified" test keys on.
- `docs/research/TRADING_STRATEGY_RESEARCH.md` — acceptance-draft categories and stop conditions.

### Architecture + operations boundaries

- `docs/architecture/ARCHITECTURE.md` — Journal component ("consumes all lifecycle events, including skipped signals"), §3 forbidden dependencies (UI → Binance order API).
- `docs/operations/SECURITY_AND_OPERATIONS.md` — `LIVE_ORDERS_DISABLED` default and enablement semantics the kill-gate side-effect composes with.
- `docs/00_PRODUCT_SCOPE.md` — full signal/order/position journal scope.
- `docs/01_ENGINEERING_PRINCIPLES.md` — determinism, Decimal-only, UTC-at-boundary, fail-closed.
- `docs/TECHNOLOGY_STACK.md` — Polars/DuckDB confined to research adapters; FastAPI edge-only and NOT used this phase; SQLAlchemy/Alembic rules.
- `docs/configuration/CONFIGURATION.md` — §7 experiment identity + cost-model hashing; registry identity for provenance fields.

### Project context

- `.planning/PROJECT.md` — constraints (determinism, no-AI core, fail-closed, exchange authority).
- `.planning/REQUIREMENTS.md` — JRN-01, GOV-01.
- `.planning/ROADMAP.md` — Phase 10 goal and success criteria (no per-phase Canonical-refs block; refs assembled from REQUIREMENTS + docs above + scout).
- `.planning/phases/09-live-execution-rollout/09-CONTEXT.md` — D-05 journal row identity (analytics input), D-04 `LIVE_ORDERS_DISABLED` / live-5 scope.
- `.planning/phases/08-approval-reconciliation-hardening/08-CONTEXT.md` — approval identity binding and journaled drills feeding approval-delay analytics.
- `.planning/phases/07-paper-forward-observation/07-CONTEXT.md` — three-way attribution, PaperRecord, pinned-registry epochs, no-tuning-on-paper lock.
- `.planning/phases/06-backtest-simulator-experiment-registry/06-CONTEXT.md` — uncertainty-first reports, six-field experiment identity, dual-universe framing.
- `.planning/phases/03-domain-registry-fixtures/03-CONTEXT.md` — frozen dataclasses, content-hash IDs, fixture triple + determinism suites.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `src/backtest/report.py` (`UncertaintyReport`, `CountsSection`, `RDistributionSection`, `StabilitySection`, `DualUniverseSection`, `BootstrapInterval`, `DrawdownDistribution`, Decimal stats helpers, `_r_multiple` / `_has_zero_risk`) — canonical R-multiple, bootstrap, and dual-universe framing the new analytics extend; reuse, do not re-derive.
- `src/backtest/experiment.py` (`ExperimentRecord`, `assemble`, six-field identity, `_universe_hash`) — per-family acceptance evidence and provenance source for the kill gate.
- `src/paper/journal.py` (`PaperRecord`, `assemble_paper_record`, `assemble_no_trade_record`, `paper_records_digest`) + `src/paper/attribution.py` (`AttributionKind`) — paper evidence rows, NO_TRADE records, and the digest pattern to mirror.
- `src/domain/journal.py` (`JournalEvent`, `content_hash_event_id`) — append-only event type and deterministic id for `KILL_GATE_EVALUATION` records.
- `src/domain/order.py`, `src/domain/fill.py`, `src/domain/position.py`, `src/domain/approval.py` — frozen shapes for execution-quality and approval-delay inputs.
- `src/execution/enablement.py` — `LIVE_ORDERS_DISABLED` posture the terminal kill-gate outcome composes with.
- `src/ops/health.py` (`HealthCheckResult`, `_record_health_check_event`, `JournalLike` protocol) — precedent for journaling evaluator results through a `JournalLike` seam.
- `src/data/store.py` / `src/data/coverage.py` — 1m candle access + coverage checks for MFE/MAE and `INCOMPLETE` bucketing.
- `src/db/models.py` + `src/db/mappers.py` + `src/db/alembic/versions/0001–0003` + `scripts/check_migration_parity.py` — persistence and parity-gate discipline if a migration proves unavoidable.
- `scripts/dev/*.ps1` (`clean`, `test`, `migrate`, `_common.ps1`) — helper-script convention for a thin report-generation wrapper.

### Established Patterns

- Tracer-first rollout (Phases 4–9): land one metric family end-to-end first, then kill-gate, then rendering.
- TDD RED→GREEN, atomic commits, frozen dataclasses, content-hash IDs, byte-exact golden fixtures, INSERT-only/append-only history.
- Pure cores (stdlib + `Decimal`), AST no-`float(` guards, mypy strict, adapter-edge isolation for any I/O library.
- Uncertainty-first, full-report-visible reporting; no tuning on paper/live stream; journal-first ordering.

### Integration Points

- New `src/analytics/` (name at planner discretion) reading `JournalEvent` / Order / Fill / PaperRecord / ExperimentRecord and emitting digest-stamped report dataclasses + a `KILL_GATE_EVALUATION` JournalEvent.
- Kill-gate outcome → `src/execution/enablement.py` posture (keep live disabled) and family-registration block; no new order path.
- Thin PowerShell/CLI wrapper under `scripts/` for report generation; report + JSON sidecar written to a git-ignored output dir (planner decides).
- New `tests/fixtures/phase10/` golden files; new DECISIONS.md entry + protocol amendment note for the D013 AND/OR reconciliation.

</code_context>

<specifics>
## Specific Ideas

- No "I want it like X" references — `--auto` mode, open to standard approaches within the locked decisions above (same delegation pattern as Phases 1–9).
- The kill gate's terminal outcome is intentionally unglamorous: a recorded `INSUFFICIENT_EDGE` is a success of the process, not a failure to route around (roadmap goal: "NO_TRADE stays a courageous, recordable outcome").

</specifics>

<deferred>
## Deferred Ideas

- Live web dashboard / FastAPI-served UI, interactive charts, auth — deferred (V1 edge is webhook/health only; revisit only with a measured need).
- Telegram interactive analytics commands — deferred; only an optional one-way summary pointer is in scope.
- Automated parameter/threshold recommendations from MFE/MAE (TP/SL tuning suggestions) — out of scope; would violate no-tuning-on-paper/live and D001; any threshold amendment follows the protocol-amendment path after ≥3 families of Validation evidence.
- Regime-model upgrades, OI/funding as features, 15M refinement, extra families (REFN-01–05) → v2 requirements.
- Multi-venue analytics / ccxt research data → later, never on order paths.

</deferred>

---

*Phase: 10-Journal Depth + Kill-Gate Operations*
*Context gathered: 2026-09-29*
