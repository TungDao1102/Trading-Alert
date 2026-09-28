# Phase 9: Live Execution Rollout - Context

**Gathered:** 2026-09-28
**Status:** Ready for planning

## Phase Boundary

Phase 9 spends the evidence earned in Phases 6–7: the first cautious live orders on smallest capital in the live-5 universe. An approved plan places a LIMIT-zone entry plus Algo-Order protective exits through the official SDK behind adapters (endpoints re-verified against current Binance docs at plan time, Dec-2025 Algo-migration posture), supports both position modes with mode-correct protective parameters, sizes protection against actual filled quantity on partial fills, revalidates live constraints from exchangeInfo at placement time, enforces DAILY_STOP against live reconciled state, and runs under the hardened Phase-8 approval/reconciliation/SAFE_MODE contract with no-withdrawal keys, IP allowlisting, off-source secrets, secret-free structured logs, and green health checks. No new strategy families, no parameter tuning on the live stream, no journal-depth/kill-gate analytics (Phase 10). Success means real money moves only through approved, revalidated, reconciled, fully-protected orders — and anything uncertain fails closed to no new orders.

## Implementation Decisions

### Live entry + protective-exit wiring

- **D-01:** Entry is a LIMIT-zone order on the normal order endpoint; protective exits (STOP_MARKET / TAKE_PROFIT_MARKET legs) go through `POST /fapi/v1/algoOrder` with `algoType=CONDITIONAL` — never the legacy `/fapi/v1/order` conditional assumption. SDK surface (request method names, required/optional params, `ALGO_UPDATE.o.rm` rejection semantics) is re-verified against the installed `binance-sdk-derivatives-trading-usds-futures` version plus the Binance Futures changelog at plan time, following the 08-04 precedent ("no public REST signature change 17.3.1→17.4.0; Algo field semantics are WS-side") — the researcher records the installed version and any delta before execution code is written. User-data WS is the preferred realtime source for order/fill/position events (D002 posture); REST is fallback plus the periodic authoritative reconciliation tick (never WS-only). Ambiguous placement responses follow EXECUTION_SPEC §10 no-blind-recovery: never blind-retry, query by deterministic client/algo ID first (08-03/08-04 query-by-ID posture), retry only if absence is confirmed. — **Reversibility:** one-way — placed live orders and exchange-side fills are permanent financial facts.
- [auto] Entry + protective wiring — Q: "LIMIT-zone entry + CONDITIONAL algo exits with SDK re-verification and no-blind-recovery vs MARKET entry with assumed-legacy conditional endpoints?" → Selected: "LIMIT-zone + CONDITIONAL algo exits, re-verified SDK, no-blind-recovery" (recommended default)

### Position modes + partial-fill protective sizing

- **D-02:** Position mode (one-way vs hedge) is detected dynamically at startup and re-checked at placement time — never assumed, never hard-coded. Protective parameters are mode-correct per EXECUTION_SPEC §5: the one-way pattern (SL `closePosition=true`, TP1 `reduceOnly` + explicit quantity, TP2 `closePosition=true`) is one branch, hedge mode carries explicit `positionSide` with its own parameter constraints, verified against current Algo Order API semantics at implementation time. Partial fills are first-class: remaining entry quantity is cancellable, protective exits are sized against the actual filled quantity (never the planned quantity), and fill events arriving out of order or replayed reconcile to a single position view. Entry-without-protective is a divergence that forces SAFE_MODE via the Phase-8 reconciler (sweeper never places rescue protection). — **Reversibility:** one-way — mode handling and fill-sizing enter live order history permanently.
- [auto] Position modes + partial fills — Q: "Dynamic mode detection with mode-correct protectives sized to filled quantity vs one-way-only template sized to planned quantity?" → Selected: "Dynamic detection, mode-correct protectives, filled-quantity sizing" (recommended default)

### Placement-time revalidation + DAILY_STOP on live state + algo headroom

- **D-03:** Every placement revalidates live constraints from exchangeInfo at placement time: tick/stepSize, min/max qty, notional minimums, plus open algo-order count against the 200-conditional-order-per-symbol limit with operational headroom left (EXECUTION_SPEC §12 — never depend on the removed `MAX_NUM_ALGO_ORDERS` filter). Constraint snapshots carry `metadata_observed_at_utc` with the Phase-5 D-04 registry TTL; stale snapshots fail closed to no new orders. Portfolio caps and DAILY_STOP (`NORMAL / WARNING / DAILY_STOP`, Phase-5 D-03) are evaluated against the live/reconciled position set — never plan-local assumptions — with the same enforcement order (per-trade sizing → cluster cap → aggregate cap → position count → daily state) and first-failing-gate reason code. Uncertain account/risk/reconciliation state fails closed to NO_TRADE with reason code (`STALE_CONSTRAINTS`, `UNCERTAIN_ACCOUNT_STATE`, `DAILY_STOP_BLOCK` vocabulary inherited). — **Reversibility:** costly — revalidation cadence and headroom policy enter the execution safety contract Phase 10 operates.
- [auto] Placement-time gates — Q: "Live exchangeInfo revalidation + caps/DAILY_STOP on reconciled state with fail-closed vs plan-time snapshot with best-effort warnings?" → Selected: "Live revalidation, reconciled-state gates, strict fail-closed" (recommended default)

### Live safety posture + rollout scope

- **D-04:** Live credentials use no-withdrawal keys with IP allowlisting, secrets encrypted at rest off-source (never in git, never in logs), and paper/test credentials strictly separated from live ones. Deployment default is `LIVE_ORDERS_DISABLED`; live execution requires an explicit operator enable step. Logs are structured (correlation ID, SignalId, client/algo order IDs, symbol, strategy version, UTC timestamp, event type, result) and secret-free — API keys/signatures never logged. Health checks are green before and during live enablement: market-feed freshness, last closed-candle time, WS connection state, user-data stream state, REST error rate, reconciliation drift, DB writes, Telegram delivery, unprotected positions, orphaned orders. Rollout scope is smallest capital in the live-5 universe only (BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT); smallest-capital sizing and the enable/disable + manual-close + SAFE_MODE emergency controls (EXECUTION_SPEC §11) are acceptance gates for the first order. — **Reversibility:** costly — credential handling and the enablement gate enter the operational security contract.
- [auto] Safety + rollout scope — Q: "No-withdrawal + allowlist + off-source secrets with default-disabled enablement and smallest-capital live-5 only vs permissive keys with orders enabled at deploy?" → Selected: "Locked-down credentials, explicit enablement, smallest-capital live-5" (recommended default)

### Execution module shape + purity + journaling

- **D-05:** A new execution manager (e.g. `src/execution/` extension at planner discretion — placement, protective attach, fill monitor, expiry/cancel paths) calls the identical Phase-5 `src/risk/` sizing + quantization functions (same inputs → byte-identical outputs incl. reason codes; no live-local sizing), gates every placement on the Phase-8 approval binding (SignalId + strategyVersion + parameterSetId/Hash + plan hash + expiry + authorized chat + one-time token; stale/mismatched/superseded plans unapprovable), reuses the deterministic `src/execution/order_ids.py` derivation for all client/algo IDs (retry/restart/replay-safe), and composes with the three-source reconciler + cancel-only sweeper + SAFE_MODE (any divergence blocks new entries while monitoring continues). Execution internals stay pure (stdlib + `Decimal` only for placement math and ID derivation, UTC datetimes in, deterministic ordering — same contract as `src/execution/order_ids.py`, `src/reconcile/`, `src/risk/`); all SDK imports live in `src/adapters/` (only adapters import the Binance SDK). Every placement, fill, cancel, divergence, and SAFE_MODE transition lands as a JournalEvent with full identity (strategyVersion + parameterSetId + parameterSetHash + SignalId + plan hash + experiment linkage). TDD RED→GREEN with atomic commits; fixtures under `tests/fixtures/phase9/` (placement sequences, partial-fill sizing, both position-mode branches, idempotent retry/restart, headroom-reject, DAILY_STOP-block). — **Reversibility:** costly — module paths, journal shapes, and fixture vocabulary persist in Phase-10 analytics inputs.
- [auto] Execution shape — Q: "Pure execution manager reusing risk/order-IDs/approval/reconciler contracts with journaled outcomes vs standalone live-trading module with local sizing?" → Selected: "Pure manager reusing canonical contracts, journaled" (recommended default)

### Agent's Discretion

- User runs `--auto --chain` (fully autonomous per `modes/auto.md`): all five gray areas above auto-resolved to recommended defaults with no interactive prompts. Single-pass cap observed — no re-pass gap-hunting.
- Exact module layout inside `src/execution/` (placement vs protective-attach vs fill-monitor vs expiry splits), adapter method additions in `src/adapters/binance_usdm.py` (new-order/query/cancel algo + normal surfaces), reconciler tick cadence for the live loop, entry-zone limit-price policy details (zone edge vs mid, time-in-force), TP1/TP2 split mechanics, expiry/invalidation cancel wiring, health-check mechanics (process vs endpoint), enablement-flag storage, and plan slicing (tracer placement-first vs vertical slices) are at the planner/researcher discretion, provided D-01–D-05 semantics hold.
- Pre-answered from prior phases (not re-asked): approval full-identity binding + replay-to-existing + no auto-approve (Phase 8 D-01); PTB polling behind adapters + short-id mapping (Phase 8 D-02); three-source compare + cancel-only sweeper + SAFE_MODE on divergence (Phase 8 D-03); deterministic plan-hash+role IDs ≤36 chars (Phase 8 D-04, `src/execution/order_ids.py` pinned shape); RUNBOOK 8-drill rehearsal + journaled drill log (Phase 8 D-05); identical core+risk+backtest-semantics engine calls (Phase 7 D-02); closed-candle-only pure core + warm-up flags + planner full-zone contract (Phase 4); risk-owned floor+reject quantization + 60% baseline + registry caps + DAILY_STOP + strict fail-closed (Phase 5 D-01–D-04); six-field experiment identity + costs-from-run-#1 (Phase 6 D-02–D-03); adapter isolation — only adapters import SDK/PTB (Phases 2/7/8); purity contracts (stdlib + `Decimal` only in core/risk/backtest/reconcile/execution, AST no-`float(` guards + mypy strict); TDD RED→GREEN with atomic commits; frozen dataclasses; content-hash IDs; TOML registry + SHA256 with 07.1 cost-binding gate; fail-closed posture; single-Base ORM + parity-gate discipline.
- ApprovalResult value set (PENDING/APPROVED/SKIPPED/EXPIRED) carried forward as locked (Phase 3 D-10 planner assumption, Phase 8 carried) — planner must not relitigate it.

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Execution contract (what to build)

- `docs/trading/EXECUTION_SPEC.md` — §§1–12: APPROVE→risk-recheck→entry→protective→user-data flow, LIMIT-zone V1 style, Algo migration (CONDITIONAL endpoints), entry lifecycle, pending-order expiry (never leave LIMIT open indefinitely), partial-fill rules, mode-dependent SL/TP patterns (§5), protective-confirmation requirement (§6), deterministic IDs (§7), position-mode detection (§8), three-source reconciliation + orphan cancel (§9), no-blind-recovery (§10), emergency controls (§11), 200-algo headroom (§12). EXEC-01 source.
- `docs/data/DATA_MODEL.md` — §2.5 Approval fields (incl. `approval_token_hash`, `request_hash`), §2.7 Order three identifier fields, §2.8 Fill as event; placement/monitor rows conform to these shapes.
- `docs/trading/SIGNAL_AND_ALERTS.md` — signal/plan schema, no-stale-approval rule, approve/expire timestamp lineage the placement gate enforces.
- `docs/configuration/CONFIGURATION.md` — §7 experiment identity + cost-model hashing; §§2/4/5 registry identity + immutability; every live placement traceable to strategyVersion + parameterSetId + parameterSetHash.
- `docs/GLOSSARY.md` — canonical enums (OrderRole, OrderStatus, ApprovalResult, position/approval vocabulary); authority for status and reason-code naming.

### Exchange connectivity (how to place and reconcile)

- `docs/integration/BINANCE.md` — WS/REST surface, user-data streams (preferred realtime), exchangeInfo dynamics; re-verify SDK minor + changelog before wiring (Dec-2025 Algo-migration precedent).
- `docs/TECHNOLOGY_STACK.md` — `binance-sdk-derivatives-trading-usds-futures>=17.3` (never legacy connectors), adapter-layer isolation, asyncio single loop, tenacity bounded retries (fail-closed, never infinite on order-adjacent paths); installed minor re-verified at plan time.

### Safety + operations (what guards live orders)

- `docs/operations/SECURITY_AND_OPERATIONS.md` — §§1–8: no-withdrawal keys, off-source encrypted secrets, IP allowlisting, paper/live credential separation, `LIVE_ORDERS_DISABLED` default, heartbeat/reconnect/backoff + reconciliation, health-check list (§4), high-priority alerts (§5), structured secret-free logging (§6), SAFE_MODE semantics (§7), restart behavior (§8). OPS-02 source.
- `docs/operations/RUNBOOK.md` — failure drills (unprotected/orphan/duplicate/API-down/stale-feed/DB-failure/manual-close/restore); Phase-8 rehearsed the log Phase 9 operates under.

### Domain + risk inputs (what to reuse identically)

- `docs/trading/RISK_MANAGEMENT.md` — §§1–12: sizing formula, modeled costs, portfolio caps, V1 cluster rule, DAILY_STOP states, fail-closed, quantization + 60% baseline, constraint snapshots; placement calls this math identically.
- `docs/DECISIONS.md` — D001–D021 plus Phase-1 D022–D028; determinism (D001), exchange authority, quantization, approval-safety, fail-closed bind this phase.
- `docs/01_ENGINEERING_PRINCIPLES.md` — determinism + fail-closed posture; Decimal-only and UTC-at-boundary rules.
- `docs/architecture/DATA_PIPELINE.md` — versioned symbol metadata from live exchangeInfo (step/tick/min/notional/position modes) + gap/quality fail-closed posture feeding D-03.

### Evidence inputs (what authorizes spending evidence)

- `docs/backtest/BACKTEST_SPEC.md` — §§1–13: the canonical semantics live execution must match (closed-candle, intrabar SL-first, costs-from-run-#1, limits/partials/expiry, six-field identity); divergence from these semantics is an incident, not a patch site.
- `docs/research/RESEARCH_PROTOCOL.md` — FROZEN v1.0.0; acceptance methodology and identity tuple the live stream must satisfy to count as evidence.
- `docs/implementation/IMPLEMENTATION_PLAN.md` — phased build plan and live-rollout gates; the Phase-9 schedule envelope.

### Project context

- `.planning/PROJECT.md` — project context, constraints (determinism, quantization, approval safety, fail-closed, exchange authority), key decisions.
- `.planning/REQUIREMENTS.md` — EXEC-01, OPS-02.
- `.planning/ROADMAP.md` — Phase 9 goal and success criteria (no per-phase Canonical-refs block; refs above assembled from REQUIREMENTS + EXECUTION_SPEC + SECURITY_AND_OPERATIONS + scout).
- `.planning/phases/08-approval-reconciliation-hardening/08-CONTEXT.md` — Phase 8 locks (approval binding, PTB intake, three-source reconciler + cancel-only sweeper + SAFE_MODE, deterministic IDs, RUNBOOK rehearsal) live placement composes with.
- `.planning/phases/07-paper-forward-observation/07-CONTEXT.md` — Phase 7 locks (identical engine calls, three-way attribution, pinned-registry epochs, SIMULATE boundary) the live loop graduates from.
- `.planning/phases/05-risk-engine/05-CONTEXT.md` — Phase 5 locks (canonical sizing with modeled costs, risk-owned floor+reject quantization, registry caps + DAILY_STOP, strict fail-closed, dependency-free `src/risk/`) placement calls identically.
- `.planning/phases/04-pure-core-feature-strategy-planner/04-CONTEXT.md` — Phase 4 locks (pure `src/core/`, closed-candle-only, warm-up flags, planner full-zone contract with `DEFERRED_TO_RISK`) the entry zone derives from.
- `.planning/phases/03-domain-registry-fixtures/03-CONTEXT.md` — Phase 3 locks (frozen dataclasses, content-hash IDs, TOML registry + SHA256 with 07.1 cost-binding gate, fixture triple + determinism suites) live records conform to.

## Existing Code Insights

### Reusable Assets

- `src/execution/order_ids.py` (pinned `x-`/`xa-` 36-char derivation from plan hash + `OrderRole` code, stdlib-only) — every live placement and protective leg reuses these IDs; retry/restart/replay-safe by construction.
- `src/adapters/binance_usdm.py` (sole SDK importer, frozen Decimal/UTC dataclasses, verified 17.4.0 reconciler truth surface: open normal/algo orders, positions, query-by-client-ID, idempotent cancels) — the adapter live placement extends; domain/execution never import the SDK directly.
- `src/approval/binding.py` + `src/approval/replay.py` + `src/approval/tokens.py` + `src/approval/mapping.py` (full-identity binding, replay-to-existing, token-hash discipline, short→full mapping) — the placement authorization gate.
- `src/reconcile/compare.py` + `src/reconcile/sweeper.py` + `src/reconcile/safe_mode.py` (three-source compare with five divergence kinds, cancel-only orphan sweep, SAFE_MODE transitions) — the live safety loop placement composes with.
- `src/risk/sizing.py` + `src/risk/quantization.py` + `src/risk/portfolio.py` + `src/risk/gating.py` (canonical sizing, floor+reject quantization, portfolio caps, DAILY_STOP/fail-closed) — placement calls identically; reason codes are first-class placement outcomes.
- `src/core/features.py` + `src/core/strategy.py` + `src/core/planner.py` (closed-candle features, pure `evaluate`, zone+TP1/TP2+RR-gate+`plan_hash` contract) — the entry zone and protective levels derive here, never in execution.
- `src/data/metadata.py` (versioned exchange metadata + `metadata_observed_at_utc` TTL posture) — placement-time constraint snapshots.
- `src/paper/loop.py` + `src/paper/supervisor.py` + `src/paper/resync.py` (single-loop WS supervision, REST resync, journaled gaps) — operational precedent for the live monitor loop.
- `src/ops/drills.py` (RUNBOOK drill harness + journaled drill log) — the rehearsed restore paths live SAFE_MODE exits use.
- `src/domain/order.py` + `src/domain/position.py` + `src/domain/journal.py` + `src/domain/approval.py` (three identifier fields, frozen shapes, WR-07 coherence) — placement/monitor record shapes.
- `src/db/models.py` + `src/db/mappers.py` (single-Base ORM, Enum translation) + migrations `0001_baseline.py` / `0002_domain_registry.py` / `0003_callback_mapping.py` — persistence pattern + parity-gate discipline for any execution migration.

### Established Patterns

- TDD RED→GREEN per behavior with atomic commits; frozen dataclasses; INSERT-only versioning; fail-closed loader/quality posture; structured lineage logging.
- Decimal-only + UTC-at-boundary + Asia/Ho_Chi_Minh display-edge discipline (Phases 2–8).
- Adapter-edge isolation for all SDK types (Binance SDK, python-telegram-bot); core/risk/reconcile/execution stay dependency-free.
- Tracer-first rollout precedent (Phases 4–8): land the placement slice first (LIMIT entry + one protective leg on smallest capital), then modes/partials/headroom slices.
- Query-by-ID before retry (08-03/08-04); journal-first ordering (Phase 7/8); periodic REST truth tick over WS-only reliance (08-04 T-8-33).

### Integration Points

- New execution manager (e.g. `src/execution/` extension at planner discretion: placement + protective attach + fill monitor + expiry/cancel) consuming approved registry-pinned plans + live constraint snapshots + reconciled positions, emitting Order/Fill/Position rows + JournalEvents + Telegram status updates.
- Adapter surface extension inside `src/adapters/binance_usdm.py` (new algo/normal order methods; execution-core never imports the SDK directly).
- Reconciler/SAFE_MODE composition: live loop feeds the existing three-source compare; divergences block new entries per D-03.
- New `tests/fixtures/phase9/` golden files (placement sequences, partial-fill sizing, mode branches, idempotent retry, headroom/DAILY_STOP rejects, byte-exact).
- Phase 10 deepens MFE/MAE, execution-quality latencies, and approval-delay analytics on top of D-05 journal rows; kill-gate operates on live evidence.

## Specific Ideas

- No "I want it like X" references — `--auto` mode, open to standard approaches within the locked decisions above (same delegation pattern as Phases 1–8 and 07.1).
- Prior delegation precedent (Phases 1–8 CONTEXTs): user delegates implementation choices to recommended defaults; planner/researcher discretion governs layout and slicing.

## Deferred Ideas

- Journal depth (MFE/MAE, execution-quality latencies, approval-delay impact) + kill-gate operations → Phase 10 (D-05 journal rows are the input, not the full analytics).
- Correlation model upgrade (REFN-04), OI/funding as strategy features (REFN-02/REFN-03), 15M refinement (REFN-01), extra families (REFN-05) → v2 requirements, not Phase 9.
- FastAPI inbound webhook receiver for Telegram callbacks → deferred (V1 uses PTB polling; revisit only with a measured need).
- TWAP/VP execution algos (`binance-sdk-algo`) → Phase 3+ evaluation only, not V1 (protective exits use CONDITIONAL algo orders in the futures SDK).
- None — discussion stayed within phase scope.

---

*Phase: 9-Live Execution Rollout*
*Context gathered: 2026-09-28*
