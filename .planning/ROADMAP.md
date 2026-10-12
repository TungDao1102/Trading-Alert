# Roadmap: Deterministic Binance Futures Research & Semi-Automated Execution System

## Overview

Research-first path from frozen protocol to cautious live orders: formalize the research contract and resolve doc contradictions (Phase 1), bootstrap the irrecoverable data foundation with the OI collector running from day one (Phase 2), lock reproducibility via domain model plus versioned registry plus fixture harness (Phase 3), build the pure deterministic core (Phase 4) and identical-everywhere risk engine (Phase 5), earn evidence through the backtest parity engine (Phase 6) and the 3–6-month paper forward-observation long pole (Phase 7), harden approval plus reconciliation plus RUNBOOK rehearsal before any live order (Phase 8), roll out live on smallest capital (Phase 9), then deepen journal analytics and operate the kill gate where NO_TRADE is a valid terminal outcome (Phase 10).

**Re-plan 2026-09-30 (deep audit).** A read-only deep audit of snapshot `63ca176` is archived in `.planning/audits/2026-09-29-deep-audit/`. Start with `BAO_CAO_TONG_HOP.md`, then read `DEEP_AUDIT_REPORT.md`, whose §19 is the remediation plan and §20 lists the human decisions. It found:
- 152 findings (0 CRITICAL, 12 HIGH).
- Backtest evidence is invalid: same-bar look-ahead and fills at untraded prices.
- The live path is library-only: no runtime composition, no operational persistence, no user-data stream.
- Several auto-selected planning decisions were wrong.

The user decided D031–D039 in `docs/DECISIONS.md`. Phases 11–27 below replace the earlier backlog-promoted phases 11–17 and carry their scope forward:
- old 11 → 12
- old 12 → 21
- old 13 + 14 → 22
- old 15 → 19
- old 16 → 23
- old 17 → 27

Order rule:
- Evidence correctness (11–16) comes before any paper soak is trusted.
- Every money-safety phase (17–23) comes before any live order.
- Live enablement (26) requires 11–25 complete, and follows the D040 release path SHADOW → DEMO → CANARY → LIVE.

Finding IDs (F-xxx) refer to `.planning/audits/2026-09-29-deep-audit/findings.json`.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Research Formalization** - Frozen protocol, three family hypotheses, doc contradictions resolved
- [x] **Phase 2: Data Foundation** - Candles, day-one OI collector, funding, metadata, backup drill (completed 2026-10-04)
- [x] **Phase 3: Domain + Registry + Fixtures** - Seven entities, versioned params, golden-fixture harness (completed 2026-10-04)
- [x] **Phase 4: Pure Core (Feature + Strategy + Planner)** - Deterministic signals and trade plans from closed candles (completed 2026-10-03)
- [x] **Phase 5: Risk Engine** - Identical sizing/quantization/portfolio caps in every mode (completed 2026-10-03)
- [x] **Phase 6: Backtest Simulator + Experiment Registry** - 1m intrabar parity engine with uncertainty-first reports (completed 2026-09-26; VOID (Phase 14, D052): the v1 simulator evidence is void, BKTS-01 and BKTS-02 are re-verified by Phase 14)
- [x] **Phase 7: Paper Forward Observation** - WS realtime loop, three-way attribution, no tuning on paper (completed 2026-10-04)
- [x] **Phase 8: Approval + Reconciliation Hardening** - Idempotent Telegram approvals, orphan sweeper, SAFE_MODE rehearsed (completed 2026-09-27)
- [x] **Phase 9: Live Execution Rollout** - LIMIT-zone entries, Algo protective exits, smallest capital (completed 2026-10-04)
- [x] **Phase 10: Journal Depth + Kill-Gate Operations** - MFE/MAE analytics and the 3-families/6-months stop rule (completed 2026-10-04)
- [x] **Phase 11: Decision Alignment (docs + params)** - Apply D031–D039 to canonical docs and parameter sets; protocol v1.1.0 pre-registration (completed 2026-10-04)
- [x] **Phase 12: Fee + Cost Model Correctness** - Costs in quote currency everywhere, taker entry, exit slippage, real commission rate (was Phase 11) (completed 2026-09-30)
- [x] **Phase 13: Research Data Foundation Fixes** - Collector covers the D039 research universe, history depth, point-in-time universe, mark-price klines, backfill robustness, Parquet→backtest builder (completed 2026-10-03)
- [x] **Phase 13.1: Deployment & CI** (INSERTED) - CI on every commit, pinned images, one-command bootstrap and provider-portable migrate, S3-compatible encrypted backups; real VPS provisioning deferred
- [x] **Phase 14: Backtest Simulator Causality Rewrite** - Fills only after the signal bar, multi-bar holding, TP1/TP2 ladder, funding, mark-price triggers (completed 2026-10-07)
- [x] **Phase 15: Strategy Geometry Correction** - Trend-pullback SL outside zone, confirmed pivots, min stop distance; families match their sheets (completed 2026-10-07)
- [ ] **Phase 16: Paper Runtime Composition + SHADOW Approval Mode** - Runnable paper process (M3), fixed WS await, simulated fills, SHADOW APPROVE/SKIP journaled with no order path (D040); soak can start
- [x] **Phase 17: Operational Persistence Layer** - PostgreSQL journal/approval/execution stores, integrity constraints, durable approval consumption, write-ahead intent (completed 2026-10-07)
- [ ] **Phase 18: Binance User-Data Stream + Exchange Error Taxonomy** - listenKey + ORDER/ALGO/ACCOUNT events, error-code mapping, demo/testnet switch, clock checks
- [ ] **Phase 19: Execution Plan Binding + Pre-Placement Checks** - Symbol/side/qty bound to the approved plan, live-price check, SL-reject fallback (absorbs old Phase 15)
- [ ] **Phase 20: Reconcile + SAFE_MODE Hardening + Alerts** - No blind spots, pending-entry SL kept, auto SL re-place (D034), durable SAFE_MODE, operational alerts
- [ ] **Phase 21: Account Equity + Daily Loss from Binance** - Binance-canonical equity and D033 daily-loss state (was Phase 12)
- [ ] **Phase 22: Leverage, Margin + Liquidation Guard** - ISOLATED, 5x cap, liquidation beyond SL, available margin incl. resting entries (was Phases 13 + 14)
- [ ] **Phase 23: Telegram Approval Hardening + Two-Step Confirm + Money Amounts** - User-id auth, working SKIP, APPROVE→CONFIRM card (D041), keyboard removal, $ amounts (was Phase 16)
- [ ] **Phase 24: Live Runtime Composition + Demo Rehearsal** - Wire APPROVE→execute, bot runner, schedulers, live risk inputs; end-to-end on Binance Demo Trading
- [ ] **Phase 25: Binance Demo Integration Test Campaign** - Automated failure-scenario suite on Binance Demo, APPROVE+CONFIRM→demo orders, multi-week demo soak (D040)
- [ ] **Phase 26: Go-Live Readiness Gate** - Affirmative enablement gate, verification closure, real backups, CI, mainnet read-only check + small canary (D040)
- [ ] **Phase 27: Configurable Quote Asset (USDC readiness)** - Remove USDT hard-coding; deliberate USDC evaluation (was Phase 17)

## Phase Details

### Phase 1: Research Formalization

**Goal**: Parameter work is gated by a frozen, auditable research contract — no backtest is an anecdote.
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: RSCH-01, RSCH-02, RSCH-03
**Success Criteria** (what must be TRUE):

  1. Researcher can read the frozen protocol stating dataset splits, cost model, execution assumptions, and acceptance gates before any parameter run exists
  2. Each of the three families (Trend Pullback, Breakout+Retest, Range Mean-Reversion) has an independent spec tracing informal concept → machine-detectable rule → deterministic alternatives → bias notes → parameters → backtest path
  3. Every known Core Docs v0.3 contradiction appears as an explicit resolved decision in DECISIONS.md (SystemMode naming, APPROVED lifecycle, timezone, §12 status names, duplicate sections) — no silent renames
  4. A parameter run attempted without a frozen protocol and registered parameter set is rejected by gate, not by convention

**Plans**: 4/4 plans complete

Plans:

- [x] 01-01: Frozen protocol doc DRAFT (tracer slice with verification greps)
- [x] 01-02: Three family sheets in the fixed 7-slot template
- [x] 01-03: C1–C7 edit batch + DECISIONS D022–D028 + DOC_STATUS bump
- [x] 01-04: CI gate YAML + required-status-check + freeze beat + negative test

### Phase 2: Data Foundation

**Goal**: Irrecoverable data is safe — OI accumulates from day one and every symbol has queryable, quality-checked coverage.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: DATA-01, DATA-02, DATA-03, DATA-04
**Success Criteria** (what must be TRUE):

  1. User can bootstrap 1m/1H/4H candles per symbol and query effective per-symbol coverage with duplicates, OHLC violations, and gaps flagged
  2. OI snapshots accumulate continuously from day one plus funding history, so the 30-day API window can never destroy research data going forward
  3. Symbol metadata (tick/step, min/max qty, notional constraints, position modes, onboard time) loads versioned from live exchangeInfo instead of hard-coded values
  4. Automated backup + restore drill passes covering PostgreSQL state and the self-collected OI dataset

**Plans**: 5/5 plans complete

Plans:

- [x] 02-01: Toolchain + storage skeleton + SDK re-verify + COVERAGE matrix
- [x] 02-02: Tracer end-to-end candle slice (one symbol, one interval)
- [x] 02-03: Full live-5 bounded-depth bootstrap with TDD quality gates
- [x] 02-04: Versioned metadata + day-one OI/funding collector (TDD)
- [x] 02-05: Coverage CLI/views + backup drill on off-host target

### Phase 3: Domain + Registry + Fixtures

**Goal**: Every decision is traceable and reproducible — new behavior must be expressible as a versioned set before it exists.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: DOMN-01, DOMN-02, DOMN-03
**Success Criteria** (what must be TRUE):

  1. Seven entities (Signal, TradePlan, Approval, Order, Fill, Position, JournalEvent) persist separately with GLOSSARY-canonical enums and no state inferred from nullable columns
  2. Any backtest, paper run, alert, or order plan displays its immutable identity (strategyVersion + parameterSetId + parameterSetHash + experiment linkage)
  3. Golden fixtures (candles.csv + parameters.json + expected signals/plans) plus no-lookahead, prefix-invariance, candle-close-timing, and boundary suites pass in CI; unregistered semantic changes are rejected

**Plans**: 5/5 plans complete

Plans:

- [x] 03-01-PLAN.md
- [x] 03-02-PLAN.md
- [x] 03-03-PLAN.md
- [x] 03-04-PLAN.md
- [x] 03-05-PLAN.md

**Wave 1**

- [x] 03-01: Tracer registry-to-Signal-to-row slice with seed TOML and fixture triple

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 03-02: Remaining six domain entities with ApprovalResult assumption (TDD)
- [x] 03-03: Registry hardening plus fail-closed negative gates (TDD)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 03-04: Seven-table ORM mirror plus mappers plus migration 0002 with parity gate
- [x] 03-05: Determinism suites plus CI registry gate plus no-float guard

### Phase 4: Pure Core (Feature + Strategy + Planner)

**Goal**: Closed candles in, deterministic setups out — the pure core simulators will consume is fixture-green.
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: STRAT-01, STRAT-02, STRAT-03
**Success Criteria** (what must be TRUE):

  1. Feature engine computes indicators/structure/zones from closed candles only, and long-warm-up features (e.g. EMA200-4H) report invalid until history suffices
  2. Same market snapshot + account state + strategy version + config always yields the byte-identical decision (NO_TRADE or SETUP) with a deterministic SignalId — prefix-invariance check passes
  3. Every valid setup translates into a plan carrying entry zone, SL, TP(s), invalidation, expiry, expected RR, and plan hash
  4. No strategy family is declared a winner — all three remain hypotheses pending backtest plus out-of-sample evidence

**Plans**: 4/4 plans complete

Plans:

- [x] 04-01-PLAN.md
- [x] 04-02-PLAN.md
- [x] 04-03-PLAN.md
- [x] 04-04-PLAN.md

**Wave 1**

- [x] 04-01: Tracer trend-pullback end-to-end (src/core slice + D-06 enums + fixture skeleton)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 04-02: Feature validity hardening + determinism suites rewired to real evaluate
- [x] 04-03: Full planner contract + registry extension + family B/C param sets

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 04-04: Breakout-retest + range-mr slices + per-family determinism + phase gate

### Phase 5: Risk Engine

**Goal**: Risk math is byte-identical everywhere — no sizing surprise appears for the first time with money attached.
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: RISK-01, RISK-02
**Success Criteria** (what must be TRUE):

  1. Position size derives from equity × risk-rate ÷ SL-distance including modeled costs, floors quantity to stepSize, and rejects below the utilization threshold or exchange minimums (QUANTIZATION_REJECT / NO_TRADE preferred over round-up)
  2. Portfolio limits (max open positions, aggregate risk, correlated-cluster cap, DAILY_STOP states) are enforced, and uncertain account/risk state fails closed to NO_TRADE with no new orders
  3. Backtest, paper, and live produce identical sizing outputs for identical inputs (parity fixture green)

**Plans**: 2/2 plans complete

Plans:

- [x] 05-01-PLAN.md — Tracer sizing-plus-quantization slice with parity fixture (TDD, D-01/D-02/D-05)
- [x] 05-02-PLAN.md — Portfolio gates plus DAILY_STOP plus fail-closed with phase gate (TDD, D-03/D-04)

### Phase 6: Backtest Simulator + Experiment Registry

**Goal**: Backtest is the canonical validation authority — selection decisions rest on costs-included, uncertainty-first evidence.
**Mode:** mvp
**Depends on**: Phase 5
**Requirements**: BKTS-01, BKTS-02, BKTS-03
**Success Criteria** (what must be TRUE):

  1. Both-touched SL/TP bars resolve with 1m intrabar data (SL-first conservative fallback), limit fills/partials/expiry/invalidation are modeled, and fees/funding/slippage apply from run #1 before any selection decision
  2. Every experiment reproduces from dataset + strategy + parameter set + cost + execution versions and is compared against no-trade and simple-trend baselines
  3. Reports show trade counts and slices (symbol/period/regime/version), R distribution, bootstrap intervals, and parameter-plateau analysis — never a single headline number — and no winner is declared without out-of-sample confirmation

**Plans**: 2/3 plans executed

Plans:
**Wave 1**

- [x] 06-01-PLAN.md — Tracer intrabar-plus-costs parity slice (costs, simulator core, limit model, parity gates)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 06-02-PLAN.md — Experiment registry with six-field identity, cost-key extension, same-engine baselines (TDD)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 06-03-PLAN.md — Uncertainty-first report with seeded bootstrap, no-float guard, phase gate (TDD)

### Phase 7: Paper Forward Observation

**Goal**: Forward evidence accumulates over wall-clock time — the schedule long pole runs without contaminating itself.
**Mode:** mvp
**Depends on**: Phase 6
**Requirements**: PAPER-01, PAPER-02, PAPER-03
**Success Criteria** (what must be TRUE):

  1. Paper engine ingests WS market data with warm-up/reconnect/resync, evaluates closed candles only, and journals gaps without fabricating signals
  2. Paper loop records system vs user-executed vs opportunity (skipped/expired) attribution with signal/approve/order/fill timestamps
  3. Forward observation accumulates over the 3–6-month wall-clock envelope with zero tuning on the paper stream (registry diff proves no parameter change touched the running stream)

**Plans**: 4/4 plans complete

Plans:

- [x] 07-01-PLAN.md
- [x] 07-02-PLAN.md
- [x] 07-03-PLAN.md
- [x] 07-04-PLAN.md

**Wave 1**

- [x] 07-01: Tracer closed-candle realtime tick plus feed fail-closed gates (PAPER-01)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 07-02: Supervisor plus REST resync plus backtest parity gate (PAPER-01)
- [x] 07-03: Three-way attribution journaling on existing ORM shapes (PAPER-02, TDD)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 07-04: Pinned-epoch freeze monitor plus SIMULATE notify plus soak readiness (PAPER-03)

### Phase 07.1: Close gap: B1 registry-cost to backtest identity binding (INSERTED)

**Goal:** Only registry-consistent cost models are assemblable into experiment records — mismatched pairs raise fail-closed, consistent pairs keep byte-identical IDs.
**Requirements**: BKTS-02
**Depends on:** Phase 6
**Plans:** 2/2 plans complete

Plans:
**Wave 1**

- [x] 07.1-01-PLAN.md — D-04 guard plus tracer binding slice: helper, assemble() gate, v3 sets, match fixture (wave 1)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 07.1-02-PLAN.md — Refusal coverage plus v3 test migration plus static gates (wave 2, blocked on 07.1-01)

### Phase 8: Approval + Reconciliation Hardening

**Goal**: Human control and exchange-truth safety land before any live order exists — much of it built during the paper soak.
**Mode:** mvp
**Depends on**: Phase 7 (construction may run parallel to the paper soak; enablement gates on paper evidence)
**Requirements**: APRV-01, APRV-02, EXEC-02, EXEC-03, OPS-01
**Success Criteria** (what must be TRUE):

  1. User receives Telegram alerts (SIMULATE/APPROVE/SKIP) carrying symbol, direction, setup, entry, SL, TP(s), RR, risk, expiry, invalidation, exposure, and reason codes
  2. Approval is bound to SignalId + strategy version + plan hash + expiry + authorized chat + one-time token, survives 5× duplicate-callback replay with exactly one state transition, and never auto-approves on notification failure; stale/invalid plans are unapprovable
  3. Reconciliation loop comparing local state against open normal orders, open algo orders, and positions detects an injected orphan/divergence, sweeps the orphan protective, and forces SAFE_MODE
  4. Retries, restarts, and replayed events never create duplicate entry orders (deterministic client/algo order identifiers verified)
  5. RUNBOOK failure drills (unprotected/orphan/duplicate/API-down/stale-feed/DB-failure/manual-close/restore) are rehearsed and logged; SAFE_MODE blocks new entries while monitoring and reconciliation continue

**Plans**: 5/5 plans complete

Plans:

- [x] 08-01-PLAN.md
- [x] 08-02-PLAN.md
- [x] 08-03-PLAN.md
- [x] 08-04-PLAN.md
- [x] 08-05-PLAN.md

**Wave 1**

- [x] 08-01: Tracer approval binding slice — tokens, binding, replay with 5x-replay proof (APRV-02, TDD, D-01)
- [x] 08-03: Deterministic plan-hash plus role order IDs with retry/restart/replay proof (EXEC-03, TDD, D-04)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 08-02: APPROVE/SKIP message plus PTB callback receiver plus short-id mapping migration (APRV-01, D-02)
- [x] 08-04: Three-source reconciler plus cancel-only sweeper plus SAFE_MODE (EXEC-02, D-03)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 08-05: RUNBOOK 8-drill harness plus journaled drill log plus phase gate (OPS-01, D-05)

### Phase 9: Live Execution Rollout

**Goal**: First cautious live orders on smallest capital — evidence earned in Phases 6–7 spends here.
**Mode:** mvp
**Depends on**: Phase 8
**Requirements**: EXEC-01, OPS-02
**Success Criteria** (what must be TRUE):

  1. Approved plan places a LIMIT-zone entry and Algo-Order protective exits (endpoints re-verified against current Binance docs), supports both position modes, and sizes protection correctly on partial fills
  2. Live constraints are revalidated from exchangeInfo at placement time and DAILY_STOP is enforced against live state
  3. Live credentials use no-withdrawal keys with IP allowlisting, secrets live off-source, logs are structured and secret-free, and health checks are green — first orders only on smallest capital in the live-5 universe

**Plans**: 4/4 plans complete

Plans:
**Wave 1**

- [x] 09-01-PLAN.md — Tracer approved-plan to LIMIT entry plus one CONDITIONAL SL leg on fake adapter with deterministic IDs plus SDK re-verification and COVERAGE update (EXEC-01, D-01/D-05, one-way decision gate)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 09-02-PLAN.md — Mode-correct protective sizing to filled quantity plus idempotent fill folding, one-way and hedge branches (EXEC-01 TDD, D-02)
- [x] 09-03-PLAN.md — Placement-time revalidation plus headroom plus reconciled-state portfolio gates plus default-disabled enablement (EXEC-01 + OPS-02 TDD, D-03/D-04)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 09-04-PLAN.md — Health probes plus protective confirmation plus expiry wiring plus testnet rehearsal and credential/LIVE-TAP blocking checkpoints (EXEC-01 + OPS-02, D-04)

### Phase 10: Journal Depth + Kill-Gate Operations

**Goal**: Honest analytics and an institutional stop rule — NO_TRADE stays a courageous, recordable outcome.
**Mode:** mvp
**Depends on**: Phase 9
**Requirements**: JRN-01, GOV-01
**Success Criteria** (what must be TRUE):

  1. Journal/analytics reports MFE/MAE, execution-quality latencies, approval-delay impact, and robustness slices without hiding the full report
  2. Kill-gate dashboard tracks the 3-families / 6-months budget with live-5 vs research-universe slices, and NO_TRADE / INSUFFICIENT EDGE is recordable as a valid terminal outcome

**Plans:** 12/12 plans complete
**UI hint**: yes

Plans:
**Wave 1**
- [x] 10-01-PLAN.md — Tracer: MFE/MAE end to end on backtest evidence (types, stats wrappers, excursion, digest) plus purity/typing/determinism guards (JRN-01, D-01, D-02)
- [x] 10-02-PLAN.md — D013 AND/OR reconciliation as D030 plus protocol v1.0.1 clarification, KillGateState enum and GLOSSARY 8.2, doc tripwire (GOV-01, D-03)

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 10-03-PLAN.md — Execution quality: lifecycle normalizers (paper/backtest/live) and latency legs, fill %, expiry rate, entry deviation (JRN-01, D-02)
- [x] 10-04-PLAN.md — Robustness slices (8 dimensions, ALL row first), dual-universe view, NO_TRADE by reason category (JRN-01, GOV-01, D-02, D-04)
- [x] 10-05-PLAN.md — Kill-gate evaluator tracer: D013 state machine, family independence facts, KILL_GATE_EVALUATION event; pre-approved one-way decision checkpoint (GOV-01, D-03)

**Wave 3** *(blocked on Wave 2 completion)*
- [x] 10-06-PLAN.md — Approval-delay impact (System/User/Opportunity, LIVE-only buckets) and live net-R normalizer behind verified exchange semantics (JRN-01, D-02)
- [x] 10-07-PLAN.md — Sticky terminal + human reset, clock-start parser, gate cells, enable() refusal on INSUFFICIENT_EDGE, registration tripwire (GOV-01, D-03)

**Wave 4** *(blocked on Wave 3 completion)*
- [x] 10-08-PLAN.md — Composed JournalDepthReport: per-kind blocks, provenance, INCOMPLETE ledger, kill-gate section, unpooled evidence (JRN-01, GOV-01, D-01, D-05)
- [x] 10-09-PLAN.md — Edge adapters: family/evidence/decision loaders, path confinement, SELECT-only journal/entity/candle readers, guarded idempotent append (JRN-01, GOV-01, D-05)

**Wave 5** *(blocked on Wave 4 completion)*
- [x] 10-10-PLAN.md — Renderer part 1: formatting/escaping primitives, header, Kill Gate view, Evidence Overview (JRN-01, GOV-01, D-04)

**Wave 6** *(blocked on Wave 5 completion)*
- [x] 10-11-PLAN.md — Renderer part 2: sections 3-10, JSON sidecar with digest verification, Telegram pointer text, governance scans (JRN-01, GOV-01, D-04)

**Wave 7** *(blocked on Wave 6 completion)*
- [x] 10-12-PLAN.md — CLI + PowerShell wrapper, explicit idempotent --record, closing purity/determinism/regression guards (JRN-01, GOV-01, D-04)

### Phase 11: Decision Alignment (docs + params)

**Goal**: The canonical docs and the versioned parameter sets say what the user decided in D031–D039. Under D031, DECISIONS.md outranks docs, so the conflicting doc text must be amended, and no later phase may be planned against stale rules.

**Depends on**: Phase 10

**Requirements**: RSCH-01, RSCH-02, RISK-02, EXEC-02, OPS-01. Thirteen new REQ-IDs for the lost MUST-level doc requirements (F-116) were added to REQUIREMENTS.md (plan 11-07) and are mapped to phases 13-26.

**Success Criteria**:
1. `docs/research/RESEARCH_PROTOCOL.md` v1.1.0 pre-registers numeric acceptance thresholds, the variant count with a multiple-testing correction, and a single-use holdout. It forbids a human "pass" override (D032; F-022, F-903, F-960).
2. The SAFE_MODE wording in SECURITY_AND_OPERATIONS / RUNBOOK / EXECUTION_SPEC is entries-only, with protective re-placement and a close fallback (D034; F-009, F-952). The daily loss definition in RISK_MANAGEMENT matches D033. Margin rules match D035.
3. The exchange facts in the docs are corrected:
   - the 200-conditional-order limit is account-wide;
   - algo trigger-time semantics (FINISHED ≠ filled; REJECTED/EXPIRED at trigger);
   - the WS URL split;
   - MARKET_LOT_SIZE / PERCENT_PRICE;
   - "HMAC-checked" is removed for TradingView (F-051, F-054, F-053, F-056, F-052).
4. New versioned parameter sets use `partial_fill_fraction = 1.0` and a taker-rate entry fee, and record `working_type = MARK_PRICE`. The research universe is defined point-in-time and hashed (D036–D039). The old sets are never edited in place (F-810).
5. The GLOSSARY synonym codes are resolved, and the ApprovalResult / reason codes the code emits are listed (F-110).

**Audit refs**: F-022, F-009, F-013, F-011, F-051, F-054, F-052, F-006, F-005, F-024, F-110, F-116, AMB-001…AMB-039 (report §20)

**Plans:** 8/8 plans complete

Plans:
**Wave 1**
- [x] 11-01-PLAN.md — Protocol v1.1.0: version-bound research-gate + negative test, freeze commit (header, D043, DOC_STATUS), numeric pre-registration, single-use holdout marker (RSCH-01, RSCH-02, D-01..D-05)
- [x] 11-02-PLAN.md — Parameter sets: working_type registry key, baseline-v4 x3 + baseline-no-trade-v2 + baseline-simple-trend-v2, pins for all 15 sets, old files byte-locked (RSCH-01, RSCH-02, D-06..D-08, D-18)
- [x] 11-03-PLAN.md — Point-in-time research universe manifest (DRAFT, docs/research/universe/) with validator and hash step for Phase 13 (RSCH-01, RSCH-02, D-09)
- [x] 11-04-PLAN.md — Ops/risk docs: entries-only SAFE_MODE ladder, D033 daily loss, D035 margin, canonical quantization order, constraint snapshot, plan fields, registry keys (RISK-02, OPS-01, EXEC-02, D-10..D-12)

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 11-05-PLAN.md — Exchange facts grounded in dated official sources: account-wide 200 limit, algo trigger-time semantics, WS URL split, workingType, MARKET_LOT_SIZE/PERCENT_PRICE, SOURCES.md (EXEC-02, OPS-01, RISK-02, D-13, D-14)
- [x] 11-06-PLAN.md — TradingView "HMAC-checked" removed (STACK.md then AGENTS.md), real webhook auth scheme, quantization order pointers in PROJECT.md/AGENTS.md (RISK-02, EXEC-02, D-12, D-13)

**Wave 3** *(blocked on Wave 2 completion)*
- [x] 11-07-PLAN.md — GLOSSARY section 9 canonical codes + ApprovalResult, 13 new REQ-IDs with traceability, DECISIONS D044/D045, DOC_STATUS log (F-110, F-116, D-15, D-16, D-19)

**Wave 4** *(blocked on Wave 3 completion)*
- [x] 11-08-PLAN.md — verify_decision_alignment.py over all gate modules, registry-gate CI wiring, phase-close full suite and validation sign-off (RSCH-01, RSCH-02, RISK-02, EXEC-02, OPS-01, D-17, D-18)

### Phase 12: Fee + Cost Model Correctness

**Goal**: Every mode (backtest, paper, live) sizes and books trades with costs in quote currency, so a stop-loss exit never loses more than `risk_rate` plus bounded slippage. Live uses the account's real commission rate.

This absorbs the confirmed bug from former Phase 11:
- `modeled_costs_per_unit` (`src/backtest/costs.py:184`) returns a rate sum.
- `size_position` (`src/risk/sizing.py:60`) adds that rate sum to a quote distance.

**Depends on**: Phase 11

**Requirements**: RISK-01, BKTS-01, DOMN-02

**Success Criteria**:
1. The cost per unit is `entry×fee_entry(taker, D036) + SL×(fee_exit + exit_slippage)`, in quote per unit. A property test asserts that the loss at SL is at most the risk budget across a price and stop-width grid, including a low-price symbol such as XRP (F-001, F-801, F-601).
2. Backtest slippage is multiplied by price (F-306). There is a minimum stop distance and a cost-to-risk ceiling that produce NO_TRADE (F-002).
3. Live reads `GET /fapi/v1/commissionRate` per symbol and uses max(parameter, account) for sizing. It never falls back to zero. The backtest stays on the versioned fees (F-962, F-031).
4. Golden fixtures and experiment hashes are regenerated deliberately, and the changes are recorded in a DECISIONS entry. The Phase-5 fixtures are no longer hand-typed costs (F-608).

**Audit refs**: F-001, F-801, F-601, F-306, F-002, F-962, F-005, F-028

**Plans:** 11/11 plans complete

Plans:
**Wave 1**
- [x] 12-01-PLAN.md — Rejection vocabulary window: STOP_TOO_TIGHT and COST_TO_RISK_EXCEEDED added, five deprecated aliases removed (GLOSSARY, enum, GL gates, tests)
- [x] 12-02-PLAN.md — Registry keys, unit and range guards, five v5/-v3 parameter sets at v4.0.0, pins and gate PA-07
- [x] 12-03-PLAN.md — CostRates and the quote-per-unit producer, presence-driven exit_slippage_rate in CostModel, canonical cost-hash text, cost_slice binding

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 12-04-PLAN.md — Phase 6 fixtures regenerated with guard-clearing geometry on the v5 sets (before the pipeline cutover), geometry pre-flight test
- [x] 12-05-PLAN.md — Live commission rate: pure per-side max(parameter, account) resolver, strict adapter method, SOURCES and BINANCE records

**Wave 3** *(blocked on Wave 2 completion)*
- [x] 12-06-PLAN.md — Risk pipeline cutover: adverse-edge sizing, shared producer inside evaluate_risk, cost guards before quantization, recorded cost trail

**Wave 4** *(blocked on Wave 3 completion)*
- [x] 12-07-PLAN.md — Phase 5 fixtures and risk tests migrated with hand-derived expectations
- [x] 12-08-PLAN.md — Execution manager: fail-closed live cost-rate gate and Phase 9 fixture migration
- [x] 12-09-PLAN.md — Simulator and paper cutover: per-leg slippage with exit_slippage_rate, price-aware modeled_costs_per_unit, parity fixture regenerated

**Wave 5** *(blocked on Wave 4 completion)*
- [x] 12-10-PLAN.md — SL-loss property test (Decimal grid with old-formula mutation check) and cross-call-site cost parity tests
- [x] 12-11-PLAN.md — DECISIONS D046-D048, RISK_MANAGEMENT and CONFIGURATION amendments, final regression

### Phase 13: Research Data Foundation Fixes

**Goal**: Research runs on enough correct, point-in-time data, and the Parquet store feeds the backtest directly. The OI/funding collector covers the full research universe and is ready to run 24/7 on the single VPS (D042). Packaging, hardening, backups and VPS provisioning live in Phase 13.1.

**Depends on**: Phase 11

**Requirements**: DATA-01, DATA-02, DATA-03, DATA-04, BKTS-02

**Success Criteria**:
1. The collector universe covers the D039 research universe (10–15 symbols), not only the live-5, so that it is ready to run 24/7 under Docker Compose (D042). Running it is time-sensitive, because each day of delay loses a day of OI permanently (F-107). It can run on a personal machine or on the VPS as soon as one exists, ahead of the rest of this phase. The Docker HEALTHCHECK fix (F-705), the PostgreSQL localhost binding (F-709) and the encrypted off-VPS backup (F-108, F-910) moved to Phase 13.1.
2. A CLI backfills the decided history depth: 1m for 6–12 months by default and 24 months as delivered (user decision D-21, 2026-10-03), 1H/4H for 2 years (F-906). It covers the point-in-time research universe from D039, including delisted symbols (F-024, F-907), and runs `backfill_universe` / `refresh_symbol_metadata` (F-122). Before any evaluation it freezes and hashes `docs/research/universe/research-universe-v1.toml` (DRAFT to FROZEN, D-09) and checks the decided history depth against the protocol v1.1.0 trade floor of D043, reporting a shortfall to the user instead of lowering the floor.
3. Mark-price klines are ingested for SL/TP trigger evaluation (D037).
4. Backfill never publishes a partial UTC day as immutable data. It writes files atomically (tmp + replace) and accepts zero-trade bars (F-402, F-408, F-409). The supervisor backfills before it resubscribes (F-413).
5. A Parquet → backtest case-input builder exists (M4, v0.3 audit).
6. The VPS baseline (provider and region, key-only SSH, chrony/NTP, external heartbeat monitor, deploy runbook) moved to Phase 13.1 and is executed by the operator once a host exists (D042).

**Audit refs**: F-107, F-906, F-907, F-024, F-122, F-402, F-408, F-409, F-413, F-706

**Plans:** 13/13 plans complete

Plans:
**Wave 1**
- [x] 13-01-PLAN.md — Collect list (live-5 union top 15 TRADING USDT perpetuals) drives the OI/funding collector; no live-5 fallback; list shipped in the image; loop on the cadence grid (ships first, independently)
- [x] 13-02-PLAN.md — Store hardening before any long backfill: closed-day publish, atomic tmp+replace writes, zero-trade acceptance, precision guard, KlineSource protocol
- [x] 13-03-PLAN.md — Paper supervisor backfills before resubscribing, verification pass and monotonic guard (no duplicate or skipped bar)

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 13-04-PLAN.md — Mark-price klines as a separate validated dataset under data/raw; adapter facts (deliveryDate, empty markPrice, server time, -1121); backup coverage
- [x] 13-05-PLAN.md — Checksum-verified, size-capped data.binance.vision archive source for delisted symbols, bucket listing and last archive day

**Wave 3** *(blocked on Wave 2 completion)*
- [x] 13-06-PLAN.md — Collector: paginated funding-history backfill, atomic tick writers, warn-only server-time probe
- [x] 13-07-PLAN.md — Backfill CLI core: metadata first, 12-month 1m / 24-month 1h-4h depth, onboard and delivery bounds, resumable trade and mark runs, metadata width guard
- [x] 13-09-PLAN.md — Parquet to backtest case-input builder with dataset identity (data_snapshot_id) and fail-closed gap policy
- [x] 13-10-PLAN.md — Point-in-time universe freeze tool: ranking, freeze report, approval hash and two-witness writer (tested on copies)

**Wave 4** *(blocked on Wave 3 completion)*
- [x] 13-08-PLAN.md — Backfill CLI completion: D043 data-sufficiency report with per-split 1m coverage and missing-data exit codes, archive fallback, funding step
- [x] 13-12-PLAN.md — Operator freeze: live proposal, one-way human decision, frozen manifest and witness in one commit (non-autonomous)

**Wave 5** *(blocked on Wave 4 completion)*
- [x] 13-11-PLAN.md — Documentation: Phase 13 facts in SOURCES/BINANCE, datasets and rules in DATA_MODEL/DATA_PIPELINE/CONFIGURATION, D049, requirements-gate OPS-06 mapping
- [x] 13-13-PLAN.md — Collect list re-issued with still-TRADING frozen symbols, operator backfill run, committed sufficiency report and shortfall surfaced (non-autonomous)

### Phase 13.1: Deployment & CI (INSERTED)

**Goal**: The project builds, tests and packages itself on every commit, and the whole stack can be rebuilt on any Linux VPS (EC2, Azure, GCP) with one command and moved between providers without losing data. Everything here runs locally; provisioning a real VPS is deferred to the operator.

**Depends on**: Phase 13

**Requirements**: OPS-02, OPS-06

**Success Criteria**:
1. CI runs pytest, ruff, mypy and the registry gate on every commit and all are green. The pipeline is defined in the repo and runs on a real remote (F-101, F-605).
2. Container images are pinned: the `uv` image is no longer `:latest`, and the Python and PostgreSQL bases are pinned to exact versions. A rebuild from a clean checkout produces the same dependency set (`uv.lock`).
3. One Compose stack covers collector, paper and live processes. Data lives only in named volumes. PostgreSQL is not published beyond localhost. Secrets come from env files and never appear in logs or error text (F-705, F-709, F-708).
4. `deploy/bootstrap.sh` prepares a fresh Ubuntu/Debian host: Docker, a non-root user, key-only SSH, minimal firewall, chrony/NTP, repo checkout, `.env` from a secrets file. It uses no provider-specific service (no RDS, Azure Database, Cloud SQL or provider secrets manager).
5. `deploy/migrate.sh <old> <new>` runs the cutover in a fixed order: pre-sync Parquet with rsync while the old host runs, stop the old collector, final sync plus `pg_dump`, restore on the new host, start the collector from its watermark, then print a coverage report. The old host is only shut down after that report is clean.
6. Backups go to a provider-neutral, S3-compatible object store, encrypted and scheduled, with a retention policy. `restore.sh` restores the latest bundle onto an empty host. Linux shell versions exist for the backup and restore drills (today `backup-drill.ps1` is PowerShell only).
7. A cutover test runs locally between two Docker environments and proves no Parquet file or watermark row is lost, and that the gap recorded across the switch is bounded and reported. The runbook for bootstrap, update, migrate and restore is written and tested by this run.

**Open decisions from review (not decided)**: WR-05 (sudo or PermitRootLogin after hardening), WR-06 (split env_file), CR-01 (`--size-only` trade-off); see `13.1-OPEN-DECISIONS.md`.

**Deferred to the operator (needs a real host, not required to close code work)**: choose the provider and a Binance-permitted region, create the VPS, run `bootstrap.sh`, add the IP whitelist for Binance keys, set up the off-VPS heartbeat monitor.

**Audit refs**: F-101, F-605, F-705, F-708, F-709, F-108, F-910, D042

**Plans:** 12/12 plans executed

Plans:
**Wave 1**
- [x] 13.1-01-PLAN.md — Gate repair (D-04): repo-wide ruff format in its own commit, narrow ruff/mypy fixes, docker marker, strict-aware skip helper, .python-version

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 13.1-02-PLAN.md — CI workflow ci.yml (test, lint, types, docker jobs) and SHA-pinned actions in all four workflows
- [x] 13.1-03-PLAN.md — Pinned Dockerfile (runtime and ops targets, venv HEALTHCHECK, owned mount points) and one compose stack with profiles, localhost-only PostgreSQL, db-upgrade
- [x] 13.1-04-PLAN.md — Secret redaction layer (structlog, stdlib, excepthooks, httpx) wired into collector and backfill; credential and backup variable names in .env.example
- [x] 13.1-05-PLAN.md — deploy/lib.sh and idempotent deploy/bootstrap.sh with the anti lock-out guard; LF enforcement and script hygiene gate

**Wave 3** *(blocked on Wave 2 completion)*
- [x] 13.1-06-PLAN.md — Backup core: verify, refusing restore, safe pg_dump/pg_restore (libpq URL, PGPASSWORD), dump and restore-db
- [x] 13.1-07-PLAN.md — Cutover verifier src/ops/cutover.py: fingerprints, watermarks, OI gap minutes and exit codes

**Wave 4** *(blocked on Wave 3 completion)*
- [x] 13.1-08-PLAN.md — Encrypted S3-compatible backups via rclone crypt, 7/4/6 retention with a fake-clock oracle, push/pull/scheduled/drill-remote
- [x] 13.1-09-PLAN.md — deploy/migrate.sh in the fixed cutover order and the two-environment docker cutover test

**Wave 5** *(blocked on Wave 4 completion)*
- [x] 13.1-10-PLAN.md — Linux backup, restore and drill wrappers, systemd backup timer, update and rollback script, docker drill test

**Wave 6** *(blocked on Wave 5 completion)*
- [x] 13.1-11-PLAN.md — Runbook (bootstrap, update, migrate, restore, pins, tested-vs-real-host), SECURITY_AND_OPERATIONS, D050, Facts verified for Phase 13.1

**Wave 7** *(blocked on Wave 6 completion)*
- [x] 13.1-12-PLAN.md — Local gate battery, then push and confirm the real GitHub Actions run is green (non-autonomous)

### Phase 14: Backtest Simulator Causality Rewrite

**Goal**: The backtest cannot see the future. A plan created at the close of bar N can fill only from bar N+1, until expiry, at a price that actually traded. Positions carry across bars, and exits follow live semantics. All earlier backtest evidence is declared void.

**Depends on**: Phase 12, Phase 13

**Requirements**: BKTS-01, BKTS-02, DOMN-03, BKTS-04

**Success Criteria**:
1. The entry fills only after the signal bar, and only on a trade-through of the limit price by at least one tick (F-120/F-901, F-902). The invariants `entry_time > signal_close` and `exit_time ≥ entry_time` are asserted on every trade (F-804).
2. Positions are held across bars until SL, TP2 or data end. The TP1/TP2 ladder matches live (F-102). SL/TP triggers are evaluated on mark-price klines (D037).
3. Funding is modeled with a documented sign convention (F-905, F-021). Constraints are point-in-time. Portfolio, daily-loss and equity state evolve through the run (F-305).
4. The R denominator is identical for backtest and live (F-204). The regime slice is emitted (F-123). ExperimentRecord carries the protocol-mandatory fields (F-118).
5. Every golden case has a hand-derived expected output that is not produced by the code under test. The fixture generator no longer places 1m data inside the signal bar (F-602, F-805, F-608).
6. **Carried over from Phase 6 (gap G3, entry-expiry clock):** the simulator no longer judges entry expiry with the fixture's single `now_utc`. `src/backtest/simulator.py` sets `_entry_now_utc = now_utc` (line ~758) and passes it to the entry check (line ~881), so expiry never advances with the bars. Expiry must be evaluated against the simulated bar time, and a multi-bar test must show a limit entry that expires after `signal_expiry_hours` and one that fills before it. Phase 6 was closed on 2026-10-04 with G3 still open because this phase rewrites the same entry and expiry logic (source: `06-VERIFICATION.md`).

**Audit refs**: F-120, F-901, F-902, F-102, F-804, F-905, F-305, F-204, F-123, F-118, F-602, F-805, F-904; carry-over from Phase 6 (`.planning/phases/06-backtest-simulator-experiment-registry/06-VERIFICATION.md`)

**Plans:** 17/17 plans complete

Plans:
**Wave 1**
- [x] 14-01-PLAN.md — Tracer lifecycle slice: semantics constants (D-27 TP1 policy), MinuteSource, entry/exit rules, pure lifecycle driver, TradeRecord v2 in records.py, shared validator, single R-denominator function, purity guards

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 14-02-PLAN.md — Entry lifecycle: simulated-time expiry (G3), trade-through both sides, touch counter, CANDLE_CLOSE invalidation, cancel API, PENDING_AT_DATA_END
- [x] 14-03-PLAN.md — Funding module: D-14 sign convention, actual fundingTimes, open-quantity segments, mark fallback, fail-closed coverage with recorded allow-gaps
- [x] 14-04-PLAN.md — Funding identity: presence-driven funding_convention cost key via cost_slice, legacy hashes locked, deliberate fixture fan-out
- [x] 14-05-PLAN.md — Simulated ledger (equity, exposures, UTC-day loss, DAILY_STOP) and point-in-time constraints with back-extrapolation flag
- [x] 14-06-PLAN.md — Live R denominator wiring (D-29) and backtest/live R parity test

**Wave 3** *(blocked on Wave 2 completion)*
- [x] 14-07-PLAN.md — Exit engine: live TP1/TP2 ladder, mark-price triggers, stop-first, fill-minute rule, stop gaps, fallback at bar close, END_OF_DATA, per-leg costs

**Wave 4** *(blocked on Wave 3 completion)*
- [x] 14-08-PLAN.md — v2 engine: case-input v2, event loop with D-18 ordering, windowed strategy and scripted front-ends, ledger-fed risk, one active per symbol, DAILY_STOP cancel, TP1 sizeability reject, funding wiring

**Wave 5** *(blocked on Wave 4 completion)*
- [x] 14-09-PLAN.md — Regime on SetupResult and records, typed run summary, simulator-level determinism and prefix-invariance suites
- [x] 14-10-PLAN.md — Data adapter: lazy ParquetMinuteSource, multi-symbol v2 builder with per-symbol funding cadence, constraint history reader

**Wave 6** *(blocked on Wave 5 completion)*
- [x] 14-11-PLAN.md — Analytics and report: validator at normalizer boundary, chain test, v2 kinds, closed-trade counting, regime slice, plateau not computed
- [x] 14-12-PLAN.md — Switch run to the v2 engine, retire v1, regenerate phase6/phase7 inputs as regression snapshots, migrate consumers

**Wave 7** *(blocked on Wave 6 completion)*
- [x] 14-13-PLAN.md — Hand-derived golden cases (16) with DERIVATIONS.md, input-only generator and meta-tests
- [x] 14-14-PLAN.md — Local real-data smoke script with runtime, memory and digest measurements
- [x] 14-15-PLAN.md — Typed ExperimentRecord, verifiable code version, reproduce/verify on v2, evidence schema v2

**Wave 8** *(blocked on Wave 7 completion)*
- [x] 14-16-PLAN.md — Protocol v2.0.0 amendment, D052/D053, spec updates, ROADMAP criterion 2 rewording (D-39), void markers

**Wave 9** *(gap closure: UAT test 6, review finding WR-09 remaining gap)*
- [x] 14-17-PLAN.md — Mark-price holes in windows with no strategy bar are detected and leave a coverage note that reaches the report (annotate-only, no result change for hole-free runs; what a hole should do to a trade is left to the user, OQ-1) (G-14-06, WR-09)

### Phase 15: Strategy Geometry Correction

**Goal**: Each family's implemented geometry matches its family sheet and is economically sane before any research run is trusted.

**Depends on**: Phase 14

**Requirements**: STRAT-01, STRAT-02

**Success Criteria**:
1. For trend-pullback, the SL lies outside the entry zone with a minimum ATR distance. Swings use confirmed pivots only, excluding the evaluated bar, so a setup cannot fire on a new 20-bar low (F-301).
2. The implemented geometries of all three families match the sheets' Stage baselines, or a DECISIONS entry records the deviation (F-113).
3. New versioned parameter sets record a rationale for every value; no fixture seed values are used (F-909).
4. A research re-run under protocol v2.0.0 is ready to start on the Phase-14 engine. The run itself is a research activity, not part of this phase.

Readiness evidence: docs/research/GEOMETRY_AUDIT.md 'Re-run readiness (criterion 4)' and D054.

**Audit refs**: F-301, F-113, F-909

**Plans:** 18/18 plans complete

Plans:

**Wave 1**
- [x] 15-01-PLAN.md — Geometry audit table (sheet Stage baseline vs code, verdicts, leakage, flag dispositions) before any geometry change (D-10)
- [x] 15-02-PLAN.md — Hash-neutral rationale record and PLACEHOLDER refusal in pin_stream_epoch (D-16, D-27)

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 15-03-PLAN.md — Tracer: confirmed-pivot Family A LONG end to end; pivot function under TDD; optional registry keys incl. geometry_version

**Wave 3** *(blocked on Wave 2 completion)*
- [x] 15-04-PLAN.md — Shared geometry validator (D-06/D-07/D-08/F6) and Family A complete: SHORT, opposite-pivot TP1, audit anchors, p9 regression

**Wave 4** *(blocked on Wave 3 completion)*
- [x] 15-05-PLAN.md — Family B under geometry_version 1: anchored retest, with-direction gate, S3 stop on the narrow S/R zone, leakage proof

**Wave 5** *(blocked on Wave 4 completion)*
- [x] 15-06-PLAN.md — Family C under geometry_version 1: range regime on confirmed 4H pivots, S3 stop, T-mid target, leakage proof

**Wave 6** *(blocked on Wave 5 completion)*
- [x] 15-07-PLAN.md — D-06 property test for all families; counts-only geometry census; census run and worked examples for the checkpoint

**Wave 7** *(blocked on Wave 6 completion)*
- [x] 15-08-PLAN.md — Checkpoint (blocking-human, never auto-selected): user ratifies every parameter value; baseline-v6 sets for A, B, C with rationale tables and pins

**Wave 8** *(blocked on Wave 7 completion)*
- [x] 15-09-PLAN.md — baseline-no-trade-v4 and baseline-simple-trend-v4; gate PA-08

**Wave 9** *(blocked on Wave 8 completion)*
- [x] 15-10-PLAN.md — Phase 6 generator v6 payloads (V-dip confirmed pivot) proven in memory: independent geometry, named scenarios, hand-derived fixture facts; CRLF fix (F12); no committed fixture moves
- [x] 15-11-PLAN.md — Planner unit tests and Phase 4 / PostgreSQL plan-hash snapshots on v6; pin-safe regeneration script
- [x] 15-14-PLAN.md — Family sheets "Implemented as" (NOT FROZEN), GLOSSARY reason-code prose, CONFIGURATION key table

**Wave 10** *(blocked on Wave 9 completion)*
- [x] 15-12-PLAN.md — Regenerate Phase 6/7 fixtures from the proven v6 payloads and migrate every consumer in the same plan (simulator snapshots, parity, cost parity, engine-strategy, determinism, experiment); full suite green

**Wave 11** *(blocked on Wave 10 completion)*
- [x] 15-13-PLAN.md — Validator universal for every set; legacy regression tests; full suite green

**Wave 12** *(blocked on Wave 11 completion)*
- [x] 15-15-PLAN.md — Criterion-4 readiness (smoke and census on v6 sets), final audit verdicts, D054 with regeneration inventory

**Wave 13** *(gap closure: UAT G-15-10, G-15-11)*
- [x] 15-16-PLAN.md — D054 labels the three -v4 override values as comparison reference points, not evidence-backed parameters (G-15-10, docs only, no params edit)
- [x] 15-17-PLAN.md — Checkpoint (blocking-human, never auto-selected): may older sets without rationale tables start paper; run_paper_tick calls pin_stream_epoch before any feed event; src guard on the test-only flag (G-15-11)

**Wave 14** *(blocked on Wave 13 completion)*
- [x] 15-18-PLAN.md — D054 item (i) records the paper-start gate and the user's decision; IN-01 fixed; file-by-file closure sweep (G-15-11)

### Phase 16: Paper Runtime Composition + SHADOW Approval Mode

**Goal**: A runnable paper process observes the corrected families forward, so the wall-clock-bound soak can finally start. The operator can already APPROVE/SKIP (with the D041 confirm step) in SHADOW mode to build a decision history, with no possible path to a real order (D040).

**Depends on**: Phase 12, Phase 13.1, Phase 15, Phase 17

**Plans**: 34/52 plans executed (16-01 to 16-50; plan-checker 2026-10-09: 0 blockers on 16-01 to 16-49; 16-50 added 2026-10-09 for the healthchecks.io heartbeat sender chosen by the user; open user questions Q-A to Q-Q are asked at the blocking-human checkpoints)

**Requirements**: PAPER-01, PAPER-02

**Success Criteria**:
1. The paper supervisor → tick → journal writer chain is composed and runnable as a process (M3) (F-201).
2. The WS adapter awaits the async SDK call. Fakes are contract-bound to the SDK's async signatures (F-125, F-607).
3. A simulated fill producer uses the same fill semantics as Phase 14. Approval delay is measured, not a fixed 30 s. SIMULATE buttons are functional (F-961).
4. The paper exit criteria are quantitative and pre-registered (F-023).
5. SHADOW mode (D040): SIMULATE/APPROVE messages are clearly labelled "SHADOW — no real order"; APPROVE → CONFIRM (D041) / SKIP / expiry are journaled with timestamps and approval delay; each confirmed plan gets a simulated position using the Phase-14 fill semantics on live market data, and the journal reports system vs user vs opportunity outcomes (F-961).
6. Hard isolation: in SHADOW the process loads no trade-capable API key and never constructs an order adapter; a test proves that no code path from a SHADOW confirm reaches `execute_approved_plan` or any order endpoint.
7. **Carried over from Phase 7 (live WS):** a live smoke run shows `ws_subscribe` succeeding and delivering closed-candle events to the supervisor (`soak_smoke.log` reads `ws_subscribe=BLOCKED` with 0 events today). Phase 7 verified WS ingestion only with fakes. Live probe on mainnet (2026-10-04) found three stacked causes, all in `src/adapters/paper_ws.py`: (a) `create_connection` and `kline_candlestick_streams` are coroutines called without `await`; (b) the SDK interval Enum is passed through, and on Python 3.13 it formats as `...IntervalEnum.INTERVAL_1m`, so the stream name is invalid and Binance sends nothing, silently; pass the plain string `"1m"`; (c) the default `ConfigurationWebSocketStreams()` has no `stream_url` (use the SDK PROD constant). A spike with awaited calls, a plain-string interval and `stream_url` received 3 BTCUSDT kline events in 3 s; the handle is a `RequestStreamHandle` (`.on("message", cb)`, no `on_message`), and the stream delivers open candles too, so the supervisor must keep only `is_closed` events.
8. **Carried over from Phase 7 (SC3 trial soak evidence, D061):** the stream epoch is pinned (`pin_stream_epoch`) and `python -m src.paper.freeze` runs hourly for the **trial soak window**, which is 14 calendar days on the EC2 host with runtime coverage of at least 95 percent of that fixed window, so the minimum covered time is the derived 319.2 of 336 hours and not a separate number (D061 item D, D065 item 3); only HEALTHY time counts as covered, and a planned restart, an outage or any other gap, explained or not, is uncovered and carries a reason code (D063 item 1); `logs/paper/pinned_epoch.json` and `logs/paper/registry_diff.jsonl` exist and are exported to the durable location the user approved, every diff line from the epoch pin onward is CLEAN (SKIPPED lines written before the pin, while the allowlist was empty, are expected and are not counted), a scheduled tick that is missing, invalid or without evidence is an EVIDENCE_GAP that is never CLEAN and is never filled in, and it breaks the qualifying window so the 14-day trial starts again with a new epoch pin (D063 item 2, D065 item 4), there is one `epoch_id`, and the pinned hash is unchanged. Nothing has ever been pinned yet. The 3 to 6 month wall-clock observation is NOT part of this criterion: it belongs to PAPER-03 and is verified in Phase 26. Source: `07-VERIFICATION.md` `behavior_unverified_items`.
9. **Requirement closure rule (D061 item J):** PAPER-01 completes when criteria 1, 2 and 7 hold; PAPER-02 completes when criteria 3 and 5 hold; PAPER-03 stays Pending when Phase 16 closes, because it asks for a 3 to 6 month wall-clock observation with no tuning, and Phase 26 verifies the observation window and the no-tuning rule and closes it. Phase 7 was closed on 2026-10-04 by operator decision with these requirements still unmet, so Phase 16 must not mark any of them complete on the strength of fake-level tests.

**Audit refs**: F-201, F-125, F-607, F-961, F-023, D040, D041; carry-over from Phase 7 (`.planning/phases/07-paper-forward-observation/07-VERIFICATION.md`)

**Inherited items** (owner registration, 2026-10-07; not success criteria, tracked so they are not dropped):
- [G2-007] The WS-to-`feed_events` producer sets `event["interval"]` per stream, REST-backfilled klines are converted into the loop's `feed_events` path, and `CONTEXT_BAR` (emitted at `src/paper/loop.py:455`, absent from docs/GLOSSARY.md) is confirmed as a feed-gate reason code and added to the GLOSSARY (source: .planning/phases/07-paper-forward-observation/07-REVIEW-FIX.md:76-80,150-154; decision: none required, confirmation task)
- [G2-008] Paper-vs-backtest parity cannot cover strategy-stage NO_TRADE or signal-less bars because the engine emits trades only; decided 2026-10-07 (D061 item B): parity stays at the current level and the plan finds a non-semantic way to compare the decision surface (closed bar, feature, signal, plan, risk verdict); if a simulator change is unavoidable the work stops and a new decision is recorded (source: tests/test_paper_parity.py:148-155, .planning/phases/07-paper-forward-observation/07-REVIEW-FIX.md:262-267; decision: D061)
- [G4-010] The paper loop has no ledger, so a multi-signal history diverges from the backtest by design; D052 item (i) says closing that gap belongs to a paper-loop phase (source: docs/DECISIONS.md D052 item (i); decision: D052)
- [G2-009] `.github/workflows/paper_freeze_check.yml` hard-codes `--strategy-id trend-pullback --parameter-set-id baseline-v3`; decided 2026-10-07 (D061 item A): the hourly check stays on GitHub Actions, reads the parameter set authorized through `PAPER_START_ALLOWLIST` and reports SKIPPED (allowlist empty) while it is empty (source: .github/workflows/paper_freeze_check.yml:80-81, .planning/phases/07-paper-forward-observation/07-REVIEW.md:602-610; decision: D061)
- [G4-021] No committed parameter set can start a paper stream today (PAPER_START_ALLOWLIST is empty by user decision; the five Phase 15 sets carry PLACEHOLDER keys); SC8 needs a fully rationalized non-PLACEHOLDER set or a new user checkpoint, a D054 update and the test `test_production_allowlist_is_empty_by_user_decision` revisited (source: .planning/phases/15-strategy-geometry-correction/15-17-SUMMARY.md:117-119, tests/test_paper_start_gate.py:228; decision: D054 item (i))
- [G4-018] Phase 15 paper-gate review Info items IN-01..IN-05 (PaperAllowlistEntry validates nothing, stale docstrings, the stream-start gate runs per tick, test nits, two independent REGISTRY_ROOT bindings); Phase 16 is the first consumer, so validate the allowlist entry and bind REGISTRY_ROOT once (source: .planning/phases/15-strategy-geometry-correction/15-REVIEW-PAPER-GATE.md:96-137; decision: none required, left open by user choice)
- [G3-026] One real fetch from data.binance.vision is observed during the live smoke (the Phase 13 UAT test for the live httpx client was skipped behind a TLS-intercepting proxy) (source: .planning/phases/13-research-data-foundation-fixes/13-UAT.md:179-182; decision: none required)
- [D059-5] Backlog 999.2 is not a numbered phase: Phase 16 owns the research runner, the feasibility and sample-size gate and the registration of candidate parameter sets; candidates come only from pre-registered values with a rationale, never from a backtest result, and still need the user's exact-hash approval before paper start (source: docs/DECISIONS.md D059 item 5; decision: D059)
- [D052-open] `modeled_costs_per_unit` is None on v2 filled `TradeRecord`s, and no runner calls `read_code_version` plus `assemble` outside tests; D052 says both are owed to the research runner (source: docs/DECISIONS.md D052, .planning/phases/14-backtest-causality-rewrite/deferred-items.md:17-31; decision: D059 item 5, restoring `modeled_costs_per_unit` is still an open user decision)
- [T-01] BKTS-03 parameter-plateau analysis and sweep runner: the report prints `not computed (BKTS-03 pending)` and the requirement is Pending against closed Phase 6; the runner built here owns it (source: .planning/REQUIREMENTS.md:47,134, src/backtest/report.py:50, .planning/phases/14-backtest-causality-rewrite/14-CONTEXT.md:14,155; decision: D059 item 5; the REQUIREMENTS re-map is left to the requirements batch)
- [G4-003] The research re-run itself, candidate-set freeze, data window and split, research-universe-v1, trade-floor reachability and the PLACEHOLDER resolution of baseline-v6 are "not part of Phase 15" and no other phase plans them (source: .planning/phases/15-strategy-geometry-correction/15-VERIFICATION.md:92,142, docs/DECISIONS.md D054 item (h); decision: D059 item 5)
- [G3-027] Measure the D043 trade-floor feasibility (at least 100 closed trades pooled across the Validation folds, at least 30 per fold) on the first real research run and report any shortfall; the floor is never lowered (source: .planning/phases/11-decision-alignment/11-01-SUMMARY.md:50,84, docs/DECISIONS.md D043; decision: D043)
- [G3-012] Revisit `max_cost_to_risk` 0.15 (implied minimum stop about 0.79 percent of price) once real stop widths are measured; only through a new parameter set chosen before any result is seen, never tuned afterwards (source: .planning/phases/12-fee-cost-model-correctness/12-VERIFICATION.md:167; decision: D046 item 6, values kept as locked until a new set)
- [G4-009] The incremental feature series stays deferred; re-time one run without tracemalloc first, and make any change an exact-equivalence refactor (source: docs/DECISIONS.md D052 item (h); decision: D052)
- [OQ-1] How a backtest trade held through mark-price holes is treated in the evidence (annotate only, count against coverage, exclude from pooled R, or void) is decided before any candidate is evaluated with that metric: the first real-data run may only measure how often it happens and never chooses the method (D063 item 8); D058 (live fail-closed) is not the answer to it (source: .planning/phases/14-backtest-causality-rewrite/deferred-items.md:45-47, docs/DECISIONS.md D058; decision: open user decision)
- [G2-038] The skipped kill-gate review items WR-01, WR-06, WR-12 and WR-13 must be resolved before the first kill-gate report is read on real evidence; decided 2026-10-07 (D061 item F): the fixes stay in Phase 26 and an enforced guard planned here blocks any kill-gate conclusion on real evidence until they land (source: .planning/phases/10-journal-depth-kill-gate-operations/10-VERIFICATION.md:193-194; decision: D061)
- [D057] The protocol G5 floor of 30 qualifying closed trades is in force since protocol v2.1.0 (D060, commit d52cd6a, 2026-10-07): RESEARCH_PROTOCOL.md, the decision-alignment gate and its tests carry it and each `holdout_consumed.json` entry carries its own `protocol_version` (schema holdout-consumed/2); nothing is applied backwards (source: docs/DECISIONS.md D057 and D060, docs/research/RESEARCH_PROTOCOL.md; decision: D060)
- [D059-4] The OI collector must be running and writing OI data successfully no later than 2026-10-08; a deployment that does not ingest does not count, every later OI gap is recorded as a coverage gap, and the dataset is never called full history while a known gap exists. The deadline is the user's and the repository cannot enforce it (source: docs/DECISIONS.md D059 item 4; decision: D059)
- [D061-A] The hourly freeze check drops the hard-coded `trend-pullback` / `baseline-v3`, reads the parameter set authorized through `PAPER_START_ALLOWLIST`, reports SKIPPED (allowlist empty) with an empty allowlist (never CLEAN, never a red error, never a fallback), and exports `pinned_epoch.json` and `registry_diff.jsonl` to a durable location the plan proposes and the user approves; CLEAN ticks do not prove the paper host ran, so an uptime and coverage measure is separate (source: docs/DECISIONS.md D061 item A, .github/workflows/paper_freeze_check.yml:78-83; decision: D061, the durable location is an open user decision)
- [D061-B] Paper-versus-backtest parity compares the decision surface (closed bar, feature, signal, plan, risk verdict) through shared core functions or a non-semantic observer without changing the Phase 14 simulator semantics or hashes; if a simulator change is unavoidable the work stops and a new decision is recorded (source: docs/DECISIONS.md D061 item B, tests/test_paper_parity.py:148-155; decision: D061)
- [D061-D] Paper exit criteria ratified by the user on 2026-10-07 after an agent proposal: trial soak 14 calendar days on the EC2 host; runtime coverage at least 95 percent with a healthy feed; time of day reported, not a pass condition; freeze CLEAN on every tick from the pin to the end; parity tolerance zero for the decision logic; every gap explained and no fabricated bar; clean warm-up after every restart with no duplicate signal and no missing journal row; no minimum trade count and one labelled test signal that runs in a separate rehearsal before the trial soak and never inside it (D063 item 3); the plan may refine wording but any change to these values before the trial soak starts needs a new user approval (source: docs/DECISIONS.md D061 item D; decision: D061, clarified by D063 and D065)
- [D061-F] One plan adds an enforced guard: no kill-gate report concludes on real evidence while WR-01, WR-06, WR-12 and WR-13 are unresolved, with an automated test; the WR fixes themselves stay in Phase 26 (source: docs/DECISIONS.md D061 item F, .planning/phases/10-journal-depth-kill-gate-operations/10-VERIFICATION.md:188-196; decision: D061)
- [D061-req] PAPER-03 is started here but closed in Phase 26, so it is deliberately not in this phase's Requirements line (completing the phase must not mark it complete); the long soak that starts here keeps accumulating through Phases 18 to 25 (source: docs/DECISIONS.md D061 item J, .planning/REQUIREMENTS.md:54; decision: D061)
- [D061-J] Closure chain: user-written or user-approved hypothesis and parameter grid, then a separate user command authorizing the research run, then a valid candidate (no G1 to G5 pass required, never ranked by them), then the user authorizes the exact hash, then paper start, epoch pin and a trial soak that meets the ratified criteria (source: docs/DECISIONS.md D061 item J; decision: D061)
- [D061-iso] The soak database is separate from the development and test database, the soak runs from a pinned image rather than the working tree, backups exist before the long soak, and `docker compose down -v` is never run on the soak project; the plan gives one concrete tested configuration (source: docs/DECISIONS.md D061 hosts; decision: D061)
- [D061-open] Decided 2026-10-07 (D061): no late signals for bars closed while the process was down (a gap is recorded); the OI collector moves to the EC2 host before the paper soak; the long soak starts right after this phase closes with the EC2 cost accepted; the paper exit criteria values are ratified (see D061-D); the hypothesis and parameter grid are drafted by an agent and approved by the user. Still open user decisions: the durable evidence location (the plan proposes, the user approves) and the closure-chain checkpoints decided when this phase executes (source: docs/DECISIONS.md D061; decision: D061, open user decision)
- [D062] The two 13.1 decisions come before the first EC2 bootstrap and the first real backup: WR-05 (the `trading` user joins sudo with a password and no NOPASSWD rule) was implemented on 2026-10-07 in commit 7148528 (bootstrap.sh, the checklist and RUNBOOK 13.1, 13.4, 13.5); CR-01 is replaced by D064 because a real rclone 1.75.1 run showed that `--checksum` falls back to `--size-only` on a crypt remote: the Parquet push decides content identity by SHA-256 against the manifests of the complete remote snapshots (a known path with a different hash is a hard failure, a new path uploads, a path the remote already holds outside any manifest is adopted only when identical), then `rclone cryptcheck` verifies the Parquet tree and `pg.dump` before `manifest.json` is published, and the real-rclone proof that cryptcheck detects a same-size change and a remote object modified after upload comes first; the EC2 host is created once both are implemented and tested, and only the collector moves then because the paper runtime does not exist yet (source: docs/DECISIONS.md D062 and D064, quick tasks 261007-mkw and 261007-mv4; decision: D062, D064)
- [D063-test] A test-only SHADOW path runs the single labelled test signal in a rehearsal before the trial soak: its own test identifier, `test_only` marking, no bypass of `PAPER_START_ALLOWLIST` in the production paper path, not a strategy candidate, excluded from signal counts, trade counts, parity evidence, G1 to G5 and PAPER-03; the D040 isolation tests (import graph, environment, behaviour spy) cover it; it only exercises SHADOW APPROVE then CONFIRM then journal and state transition, and the trial soak starts from a clean state afterwards (source: docs/DECISIONS.md D063 item 3; decision: D063)
- [D063-equity] The paper initial equity equals the exact intended initial live equity; if that value is not decided the plan stops at a blocking-human checkpoint and no other equity is chosen to reduce quantization rejections or raise the trade count (source: docs/DECISIONS.md D063 item 5; decision: D063, open user decision)
- [D065-WR] This phase builds the shared kill-gate review registry of five items (WR-01, WR-06, WR-10, WR-12, WR-13) with the machine-readable scopes `blocks_report` and `blocks_live_enable`, the report guard that uses only the four `blocks_report` items (WR-01, WR-06, WR-12, WR-13) and the scope tests, and the machine-checkable `fixture` definition (anything not explicitly marked fixture is real evidence) with its tests (source: docs/DECISIONS.md D061 item F, D063 item 9, D065 item 1; decision: D065)
- [D065-protocol] The research protocol is raised to v2.2.0 before the first real research execution, in a separate amendment task ordered before the research run authorization and not inside this phase's code plans: the experiment identity must contain the identity of the frozen data manifest (research universe, data source and version, candle intervals, exact train, validation and holdout UTC boundaries, dataset and file identity, known exclusions); the plan brings the choice between redefining `dataSnapshotId` and a seventh identity field to the user (source: docs/DECISIONS.md D065 item 2, src/backtest/experiment.py:236,704-713,994-998; decision: D065, open user decision)
- [D061-deploy] Deployment path for the data (blocking-human on the connected machine): the existing collector, its Parquet store and its database move from the user's machine to the EC2 host with `deploy/migrate.sh` (it reports Parquet fingerprints, watermarks and the OI gap the switch causes), the paper process and the collector then run in one Docker Compose project on that host, and the backup chain (encrypted pg.dump plus append-only Parquet to an S3 store) is how data reaches the development machine; the real-host checks 13.1 UAT 8 to 10 run here; the plan defines the exact command that pulls the research data to the development machine (source: docs/operations/RUNBOOK.md sections 11 (backup and restore) and 15 (provider migration), src/ops/backup_remote.py; decision: D061)
- [D061-ec2] Provisioning the EC2 host in region ap-southeast-1 (Singapore) is a blocking-human step on the connected machine with these prerequisites: WR-05 implemented (7148528) and the CR-01 replacement of D064 decided with its implementation pending, a paid plan with a budget alert, a fixed Elastic IP, encrypted EBS, a private encrypted S3 backup bucket, an external heartbeat monitor, chrony, and a public ping to fapi.binance.com from the instance confirming the region is accepted before anything else is installed (source: docs/DECISIONS.md D042 and D061 hosts, .planning/phases/13.1-deployment-ci/13.1-OPEN-DECISIONS.md; decision: D061)

**Plans:** 0 plans

Plans:
- [x] 16-01-PLAN.md
- [x] 16-02-PLAN.md
- [x] 16-03-PLAN.md
- [x] 16-04-PLAN.md
- [x] 16-05-PLAN.md
- [x] 16-06-PLAN.md
- [x] 16-07-PLAN.md
- [x] 16-08-PLAN.md
- [x] 16-09-PLAN.md
- [x] 16-10-PLAN.md
- [x] 16-11-PLAN.md
- [x] 16-12-PLAN.md
- [x] 16-13-PLAN.md
- [x] 16-14-PLAN.md
- [x] 16-15-PLAN.md
- [x] 16-16-PLAN.md
- [x] 16-17-PLAN.md
- [x] 16-18-PLAN.md
- [x] 16-19-PLAN.md
- [x] 16-20-PLAN.md
- [x] 16-21-PLAN.md
- [x] 16-22-PLAN.md
- [x] 16-23-PLAN.md
- [x] 16-24-PLAN.md
- [x] 16-25-PLAN.md
- [x] 16-26-PLAN.md
- [x] 16-27-PLAN.md
- [x] 16-28-PLAN.md
- [x] 16-29-PLAN.md
- [ ] 16-30-PLAN.md
- [ ] 16-31-PLAN.md
- [x] 16-32-PLAN.md
- [x] 16-33-PLAN.md
- [x] 16-34-PLAN.md
- [x] 16-35-PLAN.md
- [x] 16-36-PLAN.md
- [ ] 16-37-PLAN.md
- [ ] 16-38-PLAN.md
- [ ] 16-39-PLAN.md
- [ ] 16-40-PLAN.md
- [ ] 16-41-PLAN.md
- [ ] 16-42-PLAN.md
- [ ] 16-43-PLAN.md
- [ ] 16-44-PLAN.md
- [ ] 16-45-PLAN.md
- [ ] 16-46-PLAN.md
- [ ] 16-47-PLAN.md
- [ ] 16-48-PLAN.md
- [ ] 16-49-PLAN.md
- [x] 16-50-PLAN.md
- [x] 16-51-PLAN.md
- [ ] 16-52-PLAN.md
- [ ] TBD (run /gsd-plan-phase 16 to break down)

### Phase 17: Operational Persistence Layer

**Goal**: Operational state lives durably in PostgreSQL with integrity constraints. A replayed callback or a restart can never create a second entry.

**Depends on**: Phase 11

**Requirements**: DOMN-01, APRV-02, EXEC-03, EXEC-04, DOMN-04

**Success Criteria**:
1. PostgreSQL implementations exist for the journal, approval and execution-state stores. The row mappers have production callers (F-202).
2. The database has:
   - unique constraints on the approval token hash, on one decided approval per plan, and on client_order_id;
   - FKs and CHECKs;
   - VARCHAR widths that fit real values;
   - a session TimeZone pinned to UTC;
   - ORM indexes in parity with the migrations.
   (F-404, F-403, F-406, F-411, F-412, F-410)
3. Approval consumption is durable. Execution intent is written ahead, before `place_entry` and between entry and SL (F-126, F-951, F-703).
4. A test calls `execute_approved_plan` twice with the same approval, and against a restart. A fake models Binance's open-orders-only clientOrderId uniqueness. The test proves exactly one entry (F-603).
5. The PG and migration tests run against a disposable `_test` database in CI (F-606).

**Audit refs**: F-202, F-404, F-403, F-406, F-411, F-412, F-410, F-126, F-951, F-703, F-603, F-606

**Plans:** 15/15 plans complete

Plans:
**Wave 1**
- [x] 17-01-PLAN.md — Tracer: durable approval consumption + write-ahead ENTRY intent through migration 0004, store and manager; exactly-one-entry PG proof with negative control; disposable-DB fixtures (W1)

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 17-02-PLAN.md — Schema integrity in 0004: widths, enum/quantity CHECKs, unique and partial unique indexes, RESTRICT FKs, append-only and terminal triggers, snapshot and system-state tables (W2)
- [x] 17-03-PLAN.md — DOMN-04 transition tables (pure) + GLOSSARY sections 11-12 (W2)
- [x] 17-04-PLAN.md — Deterministic, collision-free journal ids; callback correlation from callback_query.id (W2)
- [x] 17-05-PLAN.md — D-12 plan_hash canonicalization (18-digit ROUND_HALF_EVEN) with fixture regeneration inventory (W2)
- [x] 17-06-PLAN.md — EXEC-04 constraint snapshot core: MARKET_LOT_SIZE/PERCENT_PRICE parsing, canonical snapshot, live-validity predicate (W2)

**Wave 3** *(blocked on Wave 2 completion)*
- [x] 17-07-PLAN.md — ORM/migration parity (compare_metadata + catalog checks), reversible and data-safe 0004, UTC session on both engines (W3)
- [x] 17-08-PLAN.md — PostgreSQL journal store (append-only, replay-idempotent, conflict-detecting) (W3)
- [x] 17-09-PLAN.md — PostgreSQL approval store, explicit consumption state, race-safe decisions (W3)
- [x] 17-10-PLAN.md — Entity repositories with in-transaction transitions, precision guard, round-trip and plan_hash proofs (W3)
- [x] 17-11-PLAN.md — Manager write-ahead completion: SL intent, identity-before-replay, fail-closed store errors, crash injection (W3)

**Wave 4** *(blocked on Wave 3 completion)*
- [x] 17-12-PLAN.md — Restart recovery by query only + full SC4 matrix with negative controls (W4)
- [x] 17-13-PLAN.md — Constraint snapshot and system-state stores, controller rehydrate across restart (W4)
- [x] 17-14-PLAN.md — End-to-end APPROVE replay across restart/expiry and callback redelivery on PostgreSQL (W4)

**Wave 5** *(blocked on Wave 4 completion)*
- [x] 17-15-PLAN.md — Canonical docs, D051, DOC_STATUS, phase gate (W5)

### Phase 18: Binance User-Data Stream + Exchange Error Taxonomy

**Goal**: The system learns fills, order and algo state, and account changes from Binance in real time. It interprets exchange errors by code, not by message text, and it can target Binance Demo Trading.

**Depends on**: Phase 17

**Requirements**: EXEC-01, EXEC-02, OPS-02, EXEC-05

**Success Criteria**:
1. A user-data stream is implemented: listenKey lifecycle; ORDER_TRADE_UPDATE, ALGO_UPDATE (including `o.rm`) and ACCOUNT_UPDATE handling; the `/private` WS URL. It feeds `fold_fills` and reconciliation. REST is the fallback (F-104, F-054).
2. A demo or testnet probe records the actual not-found codes for GET order and GET algoOrder. The same probe also records two Phase 17 facts that the live docs do not state (docs/SOURCES.md, "Facts verified for Phase 17"): the error code returned for a duplicate `clientAlgoId` on a new algo order (-4116 is documented only for `clientOrderId`), and whether an id is accepted again once the first order is FILLED or CANCELED. Phase 17's `BinanceSemanticsFakeAdapter` is corrected if the probe disagrees with it. Adapter mappings are keyed on `status_code`, including -2011, -2013, -2019, -4164, -1021 and -2021 (F-501, F-205, F-503, F-502).
   Demo probe cases recorded by D055 (the -4509 protective-stop question; results are labelled demo-observed, not mainnet; feasibility and safety verification only, never used to choose a trading parameter):
   - pre-place a STOP_MARKET with an explicit quantity and reduceOnly while no position exists;
   - an entry that never fills and is then cancelled: is the protective order orphaned, and does it cancel cleanly;
   - a full fill: does the protective order protect exactly the filled quantity;
   - a partial fill: how quantity and protection behave;
   - a rejected protective order;
   - reconciliation after each of these states.
3. The client configuration supports:
   - explicit REST timeouts;
   - API key loading;
   - Demo (`demo-fapi.binance.com`) / testnet / live selection;
   - recvWindow with a server-time drift check that fails closed;
   - no retry on 418, and honoring `retry_after`.
   (F-504, F-128, F-505, F-706, F-506)

**Audit refs**: F-104, F-054, F-501, F-205, F-503, F-502, F-504, F-128, F-505, F-706, F-506

**Inherited items** (owner registration, 2026-10-07; not success criteria, tracked so they are not dropped):
- [G3-001] First task: re-confirm the ALGO_UPDATE status list, the 24-hour WS lifetime and the Change-Position-Mode wording on the official Binance pages (Phase 11 could not fetch them; docs/SOURCES.md marks them as not fetched or MEDIUM) and update SOURCES.md (source: .planning/STATE.md:514, .planning/phases/11-decision-alignment/11-05-SUMMARY.md:125-126,135,152, docs/DECISIONS.md D044 item (7); decision: D044)
- [G2-028] Document a classification of every `algoStatus` value (NEW, TRIGGERING, TRIGGERED, FINISHED, CANCELED, REJECTED, EXPIRED) used by attach, reconcile and the sweeper; today `_ACTIVE_ALGO_STATUSES` is {"NEW"} only (source: src/execution/manager.py:1036, .planning/phases/09-live-execution-rollout/09-EXCHANGE-FACTS.md:37-49; decision: none required)
- [G2-029] Add to the Demo probe: a below-minimum-notional reduce-only conditional leg, and the MARKET_LOT_SIZE question for a triggered `*_MARKET` exit; record accept or reject, and correct BINANCE.md and Phase 19 criterion 4 if the probe disagrees (source: .planning/phases/09-live-execution-rollout/09-EXCHANGE-FACTS.md:69-79, .planning/phases/11-decision-alignment/11-05-SUMMARY.md:94,152; decision: none required, verification task)
- [G3-009] Parse `commission` and `commissionAsset` from ORDER_TRADE_UPDATE and feed them to the Phase 21 daily-loss accounting (source: .planning/phases/12-fee-cost-model-correctness/COVERAGE.md:16; decision: none required)
- [G4-034] Every Order or Position move out of UNKNOWN needs Binance evidence; record the evidence source (REST reconcile or user-data event) in the journal when the first caller exists (source: .planning/phases/20-reconcile-safe-mode-hardening/20-NOTES.md:17-18, docs/DECISIONS.md D051 item (i); decision: D051)
- [G4-043] Order `exchange_status` and `exchange_order_id` updates have no store method yet; add them with the first caller (source: .planning/phases/17-operational-persistence-layer/17-10-SUMMARY.md:167-168; decision: none required)
- [D055] The probe cases now listed under criterion 2 feed the -4509 decision: whether protection is placed after the entry fill or pre-placed before it stays OPEN until the user records a new decision row after the probe; alternative (b) with explicit quantity is UNVERIFIED on Demo (source: docs/DECISIONS.md D055; decision: D055, execution model is an open user decision)

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 18 to break down)

### Phase 19: Execution Plan Binding + Pre-Placement Checks

**Goal**: What the human approved is exactly what is placed: same symbol, same side, a quantity no larger than planned, and a price that is still valid. A rejected SL after a fill never leaves a naked position.

This absorbs former Phase 15 (live-price check).

**Depends on**: Phase 17, Phase 18

**Requirements**: APRV-01, APRV-02, EXEC-01, EXEC-02, RISK-04, EXEC-07

**Success Criteria**:
1. `execute_approved_plan` / `attach_protectives_to_fill` derive symbol and side from the hashed plan, not from the caller, and assert SL/entry geometry. The placement quantity may only be ≤ the approved quantity; otherwise the plan is rejected, never up-sized (F-302, F-203).
2. The placement is refused when:
   - mark or last price has crossed the SL or left the zone;
   - remaining validity is below a minimum;
   - another plan or position already exists on the same symbol;
   - TradePlan.status or the invalidation rule says the plan is invalid.
   GTD is used as the exchange-side expiry backstop (F-007, F-016, F-303, F-304, F-959).
3. If the SL is rejected or not acknowledged within N seconds after a fill, the system does a reduce-only close, alerts, and enters SAFE_MODE (F-007, D034).
4. `workingType = MARK_PRICE` is recorded on the plan (D037, F-507). TP legs are quantized with MARKET_LOT_SIZE, and there is no MIN_NOTIONAL check on reduce-only legs. The system falls back to a single TP when a leg is below minQty (F-208, F-307, F-056).

**Audit refs**: F-302, F-203, F-007, F-016, F-303, F-304, F-959, F-507, F-208, F-307

**Inherited items** (owner registration, 2026-10-07; not success criteria, tracked so they are not dropped):
- [D055] `execute_approved_plan` still places the protective stop right after the entry (`src/execution/manager.py` gate 6 near line 613 and the SL intent near line 818), which Demo rejects with -4509 while no position exists; criteria 1, 3 and 4 are NOT amended here and depend on the D055 outcome (the Phase 18 probe, then a user decision) (source: docs/DECISIONS.md D055, .planning/phases/09-live-execution-rollout/09-DEMO-REHEARSAL-FINDINGS.md; decision: D055, execution model is an open user decision)
- [D059-1,2] The TP1 far-half-of-zone rejection rule stays deferred to Backlog 999.1, and maker or post-only entries are deferred; neither is part of this phase's execution scope (source: docs/DECISIONS.md D059 items 1 and 2; decision: D059)
- [T-04] EXEC-07 is listed in this phase's requirements but no criterion names it: the TP1 split fraction, the TP2 rule and the time in force as versioned registry parameters, while D052 item (c) keeps `TP1_QUANTITY_FRACTION` a code constant; the two have to be reconciled (source: .planning/REQUIREMENTS.md:69,152, docs/DECISIONS.md D052 item (c); decision: open user decision)
- [G4-006] The live producer of the TP1 quantity and exit ladder (F-103) has no phase number ("a later phase" in D052); it must use the backtest fraction and `size_protectives_to_filled_qty` (source: docs/DECISIONS.md D052 item (c), .planning/phases/14-backtest-causality-rewrite/14-VERIFICATION.md:255; decision: D052)
- [G4-007] The criterion 4 single-TP fallback differs from the backtest rule D-27 (an un-sizeable TP1 is NO_TRADE); the backtest and the live fallback must change together so the parity test stays green (source: .planning/phases/14-backtest-causality-rewrite/14-VERIFICATION.md:255; decision: none required, the two must move together)
- [G2-032] TP1 is not resized when later partial fills arrive (cancel-then-replace with a versioned role id); decide and implement it, or document that SL and TP2 close-all suffice (source: .planning/phases/09-live-execution-rollout/09-REVIEW-FIX.md:88-90; decision: open user decision)
- [G4-038] Write TP legs ahead with `record_protective_intent`, and check `snapshot_is_valid_for_live` before placement, re-sizing or refusing on a stale snapshot (source: .planning/phases/17-operational-persistence-layer/17-11-SUMMARY.md:198-201, src/execution/constraint_snapshot.py:394; decision: none required)
- [G4-008] `realized_risk` is not persisted for live fills, so live R stays INCOMPLETE (NO_RISK_VALUE); persist it with the fill record (the audit allowed Phase 19 or 20, placed here) (source: docs/DECISIONS.md D052 item (f); decision: D052)
- [G4-017] INVALIDATED now carries two meanings (planner D-07 reject versus approval and binding invalidation); distinguish them when criterion 2 invalidation is built (source: .planning/phases/15-strategy-geometry-correction/15-REVIEW.md:106-110, .planning/phases/15-strategy-geometry-correction/15-REVIEW-DISPOSITION.md:45; decision: none required)
- [G4-020] The planner has no tick size, so a stop within one tick of the zone edge could be snapped by the risk layer; assert SL and entry geometry after tick snap (source: .planning/phases/15-strategy-geometry-correction/15-13-SUMMARY.md:90; decision: D054, accepted limitation)
- [G4-036] An executed TradePlan stays APPROVED and `expiry_utc` governs only an unfilled entry; nothing may move an executed plan to EXPIRED, so the criterion 2 plan-status check must not contradict this (source: .planning/phases/20-reconcile-safe-mode-hardening/20-NOTES.md:19-20, docs/DECISIONS.md D051 item (i); decision: D051)

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 19 to break down)

### Phase 20: Reconcile + SAFE_MODE Hardening + Alerts

**Goal**: Reconciliation sees every dangerous divergence. A protective stop is never canceled or left missing. SAFE_MODE survives restarts, and exiting it needs an operator. A DB outage never blocks risk-reducing actions.

**Depends on**: Phase 17, Phase 18

**Requirements**: EXEC-02, OPS-01, RISK-03, EXEC-06, OPS-05

**Success Criteria**:
1. The compare runs a reverse pass over exchange orders, compares signed amounts per position, and requires a STOP on the exchange for every open position. A doubled position, a sign-flipped position, a foreign order or a TP-only position is a divergence (F-701).
2. The entry-time SL of a resting entry is never classified as an orphan (F-401). When an SL is missing, the system re-places it automatically, or closes the position if re-placement fails (D034, F-952). Expiry and emergency-close follow the WR-07 ordering rules.
3. SAFE_MODE is persisted and needs an operator id to exit (F-711, F-127). Risk-reducing actions execute first and are journaled afterwards, with a fallback (F-702). The -2011 cancel result is verified by a post-cancel query (F-502).
4. Alerts go out for:
   - an unprotected position;
   - a local-vs-exchange divergence;
   - a foreign order;
   - DAILY_STOP;
   - stale data;
   - an auth failure.
   (F-106)
5. The tests that asserted the old rules ("reconciler never places") are rewritten (F-604).

**Audit refs**: F-701, F-401, F-952, F-009, F-711, F-127, F-702, F-502, F-106, F-604

Input: .planning/phases/20-reconcile-safe-mode-hardening/20-NOTES.md

**Inherited items** (owner registration, 2026-10-07; not success criteria, tracked so they are not dropped):
- [D055] Criterion 2 presumes an entry-time SL on a resting entry, which Demo rejects with -4509; it is NOT amended here and depends on the D055 outcome (the Phase 18 probe, then a user decision), with the invariant that no new entry opens while any position is unprotected (source: docs/DECISIONS.md D055; decision: D055, execution model is an open user decision)
- [D058] Stale-feed handling: execution fails closed when the mark-price data needed for risk or protection is missing or stale; this phase detects and handles the stale feed, and Phase 24 owns the enablement gate (source: docs/DECISIONS.md D058; decision: D058)
- [G2-026] The "WR-07 ordering rules" in criterion 2 are defined only as a skipped review item: expiry would cancel a plan's protective legs only with zero fills, which needs an agreed fill-state source; the emergency close needs either a reduce-only MARKET order or a flat-confirmation contract (source: .planning/phases/09-live-execution-rollout/09-REVIEW-FIX.md:266-277; decision: open user decision, premise also depends on D055)
- [G4-035] Manual close outside the system: whether the closePosition protective legs auto-cancel or orphan decides what the sweeper and reconcile do; re-read the live Binance pages and prove it on Demo (Phase 25 scenario) before relying on either answer (source: .planning/phases/20-reconcile-safe-mode-hardening/20-NOTES.md:5-12; decision: none required, verification task)
- [G2-016] Drills to rehearse for the reconcile and alert work (also listed in Phase 25): UNPROTECTED position, STALE_FEED and MANUAL_CLOSE, from the eight RUNBOOK drills (source: src/ops/drills.py:71-80, .planning/phases/08-approval-reconciliation-hardening/08-VERIFICATION.md; decision: none required)
- [G4-029] `resolve_unresolved_intents` and `list_unresolved_intents` have no production caller; restart must run intent recovery, including an acknowledged ENTRY with a STOP_LOSS intent that is rejected or absent (source: .planning/phases/17-operational-persistence-layer/17-12-SUMMARY.md:201, src/execution/intent_recovery.py:234; decision: none required, Phase 24 wires the caller)
- [G4-034] Order and Position exits from UNKNOWN record the evidence source in the journal (see the Phase 18 entry) (source: .planning/phases/20-reconcile-safe-mode-hardening/20-NOTES.md:17-18; decision: D051)
- [G4-043] Position quantity and PnL updates by reconciliation have no store method yet (`update_position_snapshot`) (source: .planning/phases/17-operational-persistence-layer/17-10-SUMMARY.md:167; decision: none required)
- [G2-019] Duplicate exchange client ids collapse silently in the compare index (08-REVIEW IN-15) and skipped sweeper cancels leave no journal trace (IN-14); surface both as divergences or journal events (source: .planning/phases/08-approval-reconciliation-hardening/08-REVIEW.md:714,724; decision: none required)
- [T-05] OPS-05 also requires alerts for a duplicate execution attempt, a rejected protective action and a daily-loss WARNING, which the criterion 4 list omits (source: .planning/REQUIREMENTS.md:78; decision: none required)
- [T-06] The reconcile cadence, stale-feed threshold and WS-silence threshold have no values ("configured freshness threshold"); they must be registry parameters with provenance labels (source: docs/operations/RUNBOOK.md:113-115, .planning/audits/2026-09-29-deep-audit/DEEP_AUDIT_REPORT.md:636 (F-026); decision: open user decision, the values)
- [G3-005] Promote `ENTRY_WITHOUT_PROTECTIVE` into the RejectionReason enum and update GLOSSARY 9.3 (source: docs/GLOSSARY.md:206, docs/DECISIONS.md D044 item (1); decision: D044)

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 20 to break down)

### Phase 21: Account Equity + Daily Loss from Binance

**Goal**: Sizing and DAILY_STOP use Binance-canonical equity and the D033 daily-loss definition, never a caller-supplied constant.

This was former Phase 12. Today `AccountState.equity` and `daily_loss_quote` are injected by the caller.

**Depends on**: Phase 18

**Requirements**: RISK-01, RISK-02, EXEC-01, OPS-02

**Success Criteria**:
1. Equity comes from `/fapi/v3/account` or `/fapi/v3/balance` plus ACCOUNT_UPDATE, with the equity field chosen and documented. If equity is unknown or stale, the result is NO_TRADE (F-012).
2. The daily loss follows D033:
   - UTC day;
   - realized PnL + commissions + funding;
   - base is equity at day start;
   - persisted state.
   At DAILY_STOP, pending entries are canceled and protective SLs are kept (F-013, F-963).
3. Portfolio caps count resting entries and approved-but-unplaced plans, and approvals reserve risk atomically (F-407, F-955).

**Audit refs**: F-012, F-013, F-963, F-407, F-955, F-908, F-014

**Inherited items** (owner registration, 2026-10-07; not success criteria, tracked so they are not dropped):
- [G4-039] Phases 21 and 22 replace the UNKNOWN margin type, leverage and equity in the plan constraint snapshot so that it can become COMPLETE (source: .planning/phases/17-operational-persistence-layer/17-13-SUMMARY.md:208; decision: none required)
- [G2-042] Daily loss (D033) counts commissions, but whether Binance `realizedPnl` excludes commission is unverified: `LIVE_NET_PNL_SEMANTICS_VERIFIED` is False, so live R stays INCOMPLETE; the verification itself is owned by Phase 24 and this phase depends on its outcome (source: src/analytics/live_outcomes.py:77, .planning/phases/10-journal-depth-kill-gate-operations/10-VERIFICATION.md:208; decision: none required)

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 21 to break down)

### Phase 22: Leverage, Margin + Liquidation Guard

**Goal**: Before any entry, the system explicitly sets ISOLATED margin and leverage (at most 5x) per symbol. The order is refused unless the liquidation price lies beyond the SL with a buffer, and unless the available margin covers the new order plus other resting entries (D035).

This was former Phases 13 and 14.

**Depends on**: Phase 21

**Requirements**: RISK-01, RISK-02, EXEC-01, EXEC-02

**Success Criteria**:
1. `change_margin_type` / `change_initial_leverage` are applied and verified via `/fapi/v1/symbolConfig`. positionRisk v3 has no leverage field. The system never inherits account defaults (F-011, F-964). Evidence (live Demo probe 2026-10-04): the demo account's BTCUSDT config was x20 CROSSED from account defaults, and nothing in the system had read or set it.
2. The liquidation check uses exchange leverage brackets and maintenance margin, never hard-coded values. The liquidation price must lie beyond the SL by a configured buffer (F-964).
3. The available-margin check uses `availableBalance`, the new order's initial margin plus fees, other resting entries and approved-but-unplaced plans (F-966).
4. Position mode is one-way single-asset only. Any other mode results in NO_TRADE (F-965, F-020).

**Audit refs**: F-011, F-964, F-966, F-965, F-020, F-019

**Inherited items** (owner registration, 2026-10-07; not success criteria, tracked so they are not dropped):
- [G3-001] The Change-Position-Mode wording was not fetched in Phase 11 and docs/SOURCES.md still carries it unconfirmed; re-confirm it on the official page before criterion 4 relies on the one-way check (source: .planning/phases/11-decision-alignment/11-05-SUMMARY.md:125-126, docs/SOURCES.md:46; decision: D044)
- [G4-039] Fill the UNKNOWN margin type and leverage fields of the plan constraint snapshot so it can become COMPLETE (see Phase 21) (source: .planning/phases/17-operational-persistence-layer/17-13-SUMMARY.md:208; decision: none required)

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 22 to break down)

### Phase 23: Telegram Approval Hardening + Two-Step Confirm + Money Amounts

**Goal**: Only the authorized user in a private chat can approve. SKIP works. An APPROVE tap alone never places an order: a second CONFIRM step on a confirmation card is required (D041). Decided messages cannot be tapped again. Every SIMULATE/APPROVE message shows the money at stake.

This was former Phase 16.

**Depends on**: Phase 12, Phase 21, Phase 22

**Requirements**: APRV-01, APRV-02, PAPER-02

**Success Criteria**:
1. The authorization checks `from_user.id` against an allowlist and requires a private chat (F-508/F-707). APPROVE and SKIP use distinct short ids, so SKIP is recorded (F-405). The message is edited and the keyboard removed after a decision, and RetryAfter is honored (F-509). The token trust model is documented (F-127).
2. Messages show:
   - quantity;
   - notional;
   - margin at the configured leverage;
   - estimated loss at SL and profit at each TP, gross and net of modeled costs;
   - the equity used, with its source and timestamp.
   All values come from the risk pipeline output, never recomputed (F-015).
3. The expiry window shown and the remaining-validity rule match Phase 19 (F-016).
4. Two-step confirm (D041; the SHADOW form is delivered by Phase 16 criterion 5 and this phase extends it to DEMO and LIVE): APPROVE edits the message into a confirmation card (mode SHADOW/DEMO/LIVE, symbol, side, quantity, notional, estimated loss at SL, current mark price vs entry/SL, remaining validity) with CONFIRM/CANCEL. Only CONFIRM triggers placement. The confirm token is distinct, single-use, bound to the same user id and plan hash, with a short TTL (default 60 s); CANCEL/expiry places nothing and is journaled; pre-placement checks re-run at confirm time. Tests cover: double-tap, replayed CONFIRM callback, CONFIRM after TTL, CONFIRM by another user, CONFIRM after the plan expired or price crossed SL.
5. **Findings from the live Telegram test (2026-10-04, Phase 8 behaviour):** a decided message keeps its button and the bot answers every later tap (replays are idempotent: 3 taps gave 1 transition, but the keyboard must be removed and later taps refused); `actor_id` is empty on the decided approval, so the journal does not say who decided; APPROVE moves straight to APPROVED with no CONFIRM step (D041); the application has no error handler, so callbacks queued during downtime raise `BadRequest: Query is too old` at `query.answer()` and must be handled; the messages show no money amounts and the display note says Asia/Ho_Chi_Minh while the times are UTC; SIMULATE/APPROVE/SKIP are separate keyboards, so one message carries one button (decide whether one message should carry APPROVE and SKIP together).

**Audit refs**: F-508, F-707, F-405, F-509, F-127, F-015, F-016, D041

**Inherited items** (owner registration, 2026-10-07; not success criteria, tracked so they are not dropped):
- [G4-032] After a plan expires, a redelivered APPROVE is answered APPROVAL_EXPIRED even if the plan was executed; if the message should show "already executed", the composition must read the stored outcome via `PgExecutionStateStore.get_entry`, and criterion 4 tests should cover it (source: .planning/phases/17-operational-persistence-layer/17-14-SUMMARY.md:159; decision: none required)
- [G4-042] `uq_approvals_one_decided_per_plan` conflicts with expiring sibling approval rows (a second sibling EXPIRED write violates the index); decide the expiry rule (exclude EXPIRED from the index predicate, or plan-level expiry) and record it in DATA_MODEL (source: .planning/phases/17-operational-persistence-layer/17-REVIEW.md:160; decision: open user decision)

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 23 to break down)

### Phase 24: Live Runtime Composition + Demo Rehearsal

**Goal**: The live system runs end-to-end as named processes. It is proven on Binance Demo Trading before any real order.

**Depends on**: Phase 16, Phase 19, Phase 20, Phase 21, Phase 22, Phase 23

**Requirements**: APRV-01, EXEC-01, EXEC-02, EXEC-03, OPS-02, OPS-03, OPS-04

**Carried from Phase 13.1 (open, undecided)**: WR-06 split the shared `env_file` per service before real `BINANCE_LIVE_API_*` keys enter `.env`; see `.planning/phases/13.1-deployment-ci/13.1-OPEN-DECISIONS.md`.

**Success Criteria**:
1. The composition root wires every link that has no production caller today (M1, M2, M5–M8) (F-201, F-956):
   - approval request sender;
   - Telegram bot runner (APPROVE → CONFIRM → `execute_approved_plan`, D041);
   - execution service;
   - reconcile, sweeper and health schedulers;
   - live risk-input producer: constraints, equity, daily loss, open algo count;
   - kill-gate event → `enable()`.
2. An end-to-end smoke test runs on Binance Demo Trading:
   - signal → approve → confirm → entry → SL/TP;
   - fill via the user-data stream;
   - reconcile clean;
   - SAFE_MODE drill;
   - restart and rehydrate.
   This executes the blocked 09-04 rehearsal with recorded demo order ids.
3. The approval → placement path is exercised with replayed callbacks and a restart mid-flow, and no duplicate orders result.
4. The full runtime runs on the single VPS (D042) under Docker Compose with restart policies. The external heartbeat monitor covers every long-running process. The Binance Demo API key is IP-whitelisted to the VPS address.
5. **Findings from the live Binance Demo probe (2026-10-04, key verified for trading):** `BinanceUsdmAdapter(sdk_client)` already works against `demo-fapi.binance.com` (place, query, cancel of a LIMIT order; algo place/query/cancel); a `closePosition=true` SL/TP is rejected with `-4509` while no position is open and accepted once the position is filled, so protective legs must be placed after the entry fills; `query_algo_order_by_client` still reports `NEW` for about a second after a cancel (open-algo list already empty), so the reconciler and sweeper must not read that as a failed cancel; `snapshot_positions` returned `entry_price` `84816.40000000001` (float noise at the SDK boundary, check the Decimal conversion); the adapter has no market-order or close-position helper (the probe used marketable LIMIT orders).

**Audit refs**: F-201, F-956, F-202, F-104, F-124, D042

**Inherited items** (owner registration, 2026-10-07; not success criteria, tracked so they are not dropped):
- [D055] The -4509 finding in criterion 5 (protective legs placed after the entry fills) is a recorded observation, not a chosen execution model; criteria 1 and 2 are NOT amended and depend on the D055 outcome (the Phase 18 probe, then a user decision); no LIVE execution until D055 is closed with a verified execution policy (source: docs/DECISIONS.md D055; decision: D055, execution model is an open user decision)
- [D056] DEGRADED health policy: on mainnet a DEGRADED health state cannot enable any order-capable capability and, once enabled, no new entry may be created until health returns to an allowed state; Demo may run DEGRADED only in an explicit Demo or Rehearsal mode that journals the health state and can never switch to LIVE. Today `src/ops/health.py` lets DEGRADED pass and nothing under `src` produces it, so a producer, a state transition and an explicit mode are designed here together with Phase 26 (source: docs/DECISIONS.md D056, src/ops/health.py:37-39; decision: D056)
- [D058] Live mark-price gate: execution fails closed when the mark-price data needed for risk or protection is missing or stale, and LIVE cannot be enabled in that state; a stale or degraded mark price while LIVE is enabled is an invalid state and LIVE never bypasses it. This phase owns the enablement side; Phase 20 owns stale-feed handling (source: docs/DECISIONS.md D058; decision: D058)
- [G2-014] A tap from an unknown chat or another user has never been observed live (NOT_REHEARSED); reject it live with no state change and a journaled `chat_gate_rejected` (needs a second Telegram account or a group) (source: .planning/phases/09-live-execution-rollout/09-DEMO-REHEARSAL-FINDINGS.md:9,35; decision: none required)
- [G2-042] Verify against current Binance docs and a Demo fill whether `realizedPnl` excludes commission, record the citation, then decide whether to set `LIVE_NET_PNL_SEMANTICS_VERIFIED` (Phase 10 assigned this to Phase 24) (source: .planning/phases/10-journal-depth-kill-gate-operations/10-VERIFICATION.md:208, src/analytics/live_outcomes.py:77; decision: none required, verification task)
- [G3-008] Live commission wiring: `resolve_live_cost_rates` has no production caller; add per-symbol commission rates to the live risk-input producer (scheduler, cache, refresh loop, fail closed), re-read the official commissionRate page first (MEDIUM confidence) and record Demo behaviour (source: .planning/phases/12-fee-cost-model-correctness/12-05-SUMMARY.md:93, .planning/phases/12-fee-cost-model-correctness/12-VERIFICATION.md:71,83; decision: D046 item 7)
- [G3-014] Fold phase 12 review Info IN-01 (negative maker rate fails closed) and IN-05 (`assert`-based invariants) into the commission-wiring plan (source: .planning/phases/12-fee-cost-model-correctness/12-REVIEW.md:121,150; decision: none required)
- [G3-029] WR-06: per-service env allowlists (the shared `env_file` split) are in place and verified, with the cutover test and drills re-run, before real live keys enter `.env`; WR-05 was implemented on 2026-10-07 (commit 7148528, D062) and the CR-01 replacement decided in D064 is implemented before the first EC2 bootstrap and the first real backup (source: .planning/phases/13.1-deployment-ci/13.1-OPEN-DECISIONS.md:10-12; decision: D062, D064)
- [G3-033] The VPS is built with `deploy/bootstrap.sh` and the RUNBOOK section 13 and section 17 "real host" rows are executed and recorded (docker apt install, ufw, sshd drop-in, chrony replacing timesyncd, NTP drift monitoring); the systemd backup timer firing and catching up after downtime and one real `migrate.sh` run (or an explicit waiver) are checked too (source: .planning/phases/13.1-deployment-ci/13.1-UAT.md:60-71; decision: D042)
- [T-04] OPS-04 is listed in this phase's requirements but no criterion names it: health and diagnostic output includes the runtime Python version and the application git revision (source: .planning/REQUIREMENTS.md:77; decision: none required)
- [G4-029] Wire `resolve_unresolved_intents` (startup intent recovery) and the system-state and constraint-snapshot rehydrate paths into the composition root (source: .planning/phases/17-operational-persistence-layer/17-12-SUMMARY.md:201, .planning/phases/17-operational-persistence-layer/17-13-SUMMARY.md:202; decision: none required)
- [G4-040] The sync PostgreSQL store runs on the event loop; wrap store calls in `asyncio.to_thread` or use an async pool, or record the decision (source: .planning/phases/17-operational-persistence-layer/17-01-SUMMARY.md:63, docs/DECISIONS.md D051 item (a); decision: open user decision)
- [G3-005] Promote `NO_FILL` and `HEALTH_CHECK_FAILED` into the RejectionReason enum and update GLOSSARY 9.3 (source: docs/GLOSSARY.md:207-208, docs/DECISIONS.md D044 item (1); decision: D044)
- [G2-035] Phase 9 review Info IN-01 (pyproject.toml E501 ignore), IN-05 (headroom fixture 198+3), IN-06 (`plan_hash=approval.trade_plan_id` at `src/execution/manager.py:532`) and IN-07 (`src/ops/health.py:404` accepts error_count above total_count) were carried here as warnings and need triage or a won't-fix note (source: .planning/phases/09-live-execution-rollout/09-REVIEW-DISPOSITION.md:94-118,153; decision: none required)
- [T-02] OPS-06 (separate paper and live credentials, WR-06, provider disk encryption) is Pending and mapped to closed Phase 13.1; the WR-06 half belongs here and the disk-encryption half to Phase 26 (source: .planning/REQUIREMENTS.md:79,158; decision: none required, the REQUIREMENTS re-map is a separate change)
- [16-50] Phase 16 plan 16-50 ships the external heartbeat sender (`deploy/heartbeat.sh` with a systemd timer, service healthchecks.io, D042 condition 1) and it probes the collector only. The paper and live process probes, and the external monitor's coverage of every long-running process that criterion 4 requires, are built here (source: .planning/phases/16-paper-runtime-composition/16-50-PLAN.md; decision: the user chose healthchecks.io on 2026-10-09, recorded in .planning/phases/16-paper-runtime-composition/decisions/16-DEC-O-12.md with the interval and grace still open)

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 24 to break down)

### Phase 25: Binance Demo Integration Test Campaign

**Goal**: The complete system is proven correct and robust on Binance Demo Trading (D040 DEMO stage) — including failure paths — before any real money. Profitability is explicitly out of scope; correctness is the only goal.

**Depends on**: Phase 24

**Requirements**: EXEC-01, EXEC-02, EXEC-03, APRV-01, APRV-02, OPS-01, OPS-02

**Success Criteria**:
1. An automated demo scenario suite runs against Binance Demo, separated from unit tests (e.g. `pytest -m demo`, credentials from env, never in CI by default). It covers at least:
   - happy path;
   - partial fill;
   - price crossed SL before placement (-2021);
   - SL rejected after fill → reduce-only close;
   - cancel racing a fill;
   - duplicate/replayed APPROVE and CONFIRM callbacks;
   - restart mid-flow (before entry ACK, between entry and SL, after fill);
   - WS disconnect and listenKey expiry;
   - clock skew;
   - rate limit / 418;
   - DB outage during a risk-reducing action;
   - DAILY_STOP;
   - liquidation-guard and available-margin rejections;
   - SAFE_MODE entry and operator exit;
   - foreign order and doubled position detected by reconcile.
2. APPROVE → CONFIRM places real orders on the Demo account through the same code path as live (only the endpoint and keys differ); journal, reconcile and alerts behave as in live.
3. A continuous demo soak of at least 3 weeks (duration pre-registered) ends with zero unexplained local-vs-exchange divergences, zero positions without an exchange-side SL, zero duplicate entries, and every alert explained. Any defect found restarts the soak clock after the fix.
4. Known demo-vs-mainnet differences (liquidity, fills, filters, fees, resets) are documented, so that CANARY (Phase 26) targets exactly what demo cannot prove.

**Audit refs**: F-501, F-104, F-124, F-702, F-701, F-401, F-126, D040, D041

**Inherited items** (owner registration, 2026-10-07; not success criteria, tracked so they are not dropped):
- [G2-016] The scenario list in criterion 1 omits three of the eight RUNBOOK drills: manual close outside the system (do the protective legs orphan or auto-cancel, see Phase 20), stale feed and an unprotected-position drill (source: src/ops/drills.py:71-80, .planning/phases/20-reconcile-safe-mode-hardening/20-NOTES.md:5-12; decision: none required)
- [D055] The scenarios "SL rejected after fill" and "partial fill" depend on the execution model chosen after the D055 probe; they are not amended here (source: docs/DECISIONS.md D055; decision: D055, execution model is an open user decision)
- [D056] Demo runs in a DEGRADED state are never evidence of live readiness; the scenario suite and the soak must also run in a healthy state (source: docs/DECISIONS.md D056 item 2(d); decision: D056)
- [G2-030] After Phase 24, fill the "Demo cross-check" lines of `09-EXCHANGE-FACTS.md` (Facts 3 and 5 and the addenda read NOT YET OBSERVED) from the recorded Demo order ids (source: .planning/phases/09-live-execution-rollout/09-EXCHANGE-FACTS.md:15,51,67; decision: none required)

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 25 to break down)

### Phase 26: Go-Live Readiness Gate

**Goal**: Live trading can only be enabled affirmatively: a family has passed under protocol v1.1.0, the paper exit gate is met, the demo campaign passed, all safety phases are verified, operations are real, and a small canary on the real exchange succeeded (D040). Otherwise it cannot be enabled.

**Depends on**: Phase 25

**Requirements**: GOV-01, OPS-01, OPS-02, PAPER-03, GOV-02

**Success Criteria**:
1. `enable()` requires a recorded passing candidate, a met paper exit gate, a passed Phase-25 demo campaign and a minimum capital. WITHIN_BUDGET is refused. The skipped Phase-10 review items WR-01/06/10/12/13 are resolved (F-953, F-105, F-960) and `enable()` is bound to the shared WR registry (D065 item 1).
2. Phases 06–25 each have a VERIFICATION.md written after their last review-fix wave. The ~30 "requires human verification" fixes are confirmed, and 05-VERIFICATION is reopened (F-807, F-808, F-109, F-956). One-way checkpoints carry recorded human decisions (F-124, F-809).
3. Backups are off-VPS and encrypted (D042), run on a schedule and follow a retention policy. The pg_dump URL is fixed. A real PostgreSQL restore drill onto a fresh machine passes (F-108, F-910, F-121, F-704).
4. CI on a real remote runs pytest, ruff, mypy and the registry gate, and all are green (F-101, F-605). The Docker healthcheck uses the venv and Postgres binds to localhost (both hardened in Phase 13.1, re-verified here). The images are pinned. Secrets are scrubbed from errors (F-705, F-709, F-708).
5. CANARY (D040): a mainnet READ-ONLY API key (trade and withdraw disabled, IP-restricted to the VPS address per D042) verifies real exchangeInfo filters, commission rates, mark prices and balances against what the system assumes; then a dedicated small isolated sub-account (order of USD 50–100, minimum size, leverage ≤ cap) executes a pre-registered number of trades with the operator watching, with zero divergences before full LIVE is allowed.

**Audit refs**: F-953, F-105, F-960, F-807, F-808, F-109, F-124, F-809, F-108, F-121, F-704, F-101, F-605, F-705, F-709, F-708, D040, D042

**Inherited items** (owner registration, 2026-10-07; not success criteria, tracked so they are not dropped):
- [T-03] The goal text says "a family has passed under protocol v1.1.0", but D052 voids all earlier backtest evidence; the goal is not edited here, read it as the protocol version in force (v2.0.0 or later) when this phase is planned (source: docs/DECISIONS.md D052 item (k), Phase 26 Goal above; decision: D052)
- [D059-3] D013 stays Provisional; its own condition (three independently specified candidate families and at least 6 months of research) is unchanged and does not move because Phase 16 or an implementation finishes (source: docs/DECISIONS.md D059 item 3; decision: D059)
- [D059-5] `enable()` requires a passing candidate produced by the Phase 16 research runner work (Backlog 999.2 is not a numbered phase); candidates come only from pre-registered values with a rationale, never from a backtest result, and need the user's exact-hash approval before paper start (source: docs/DECISIONS.md D059 item 5; decision: D059)
- [D057] The executable G5 evaluation enforces the minimum of 30 qualifying closed trades (the protocol text and the decision-alignment gate already carry it since v2.1.0, D060): a candidate under the floor fails G5 and the holdout counts as consumed for that lineage; the executable gate code is built here (source: docs/DECISIONS.md D057 and D060; decision: D057, D060)
- [D056] Enablement refuses to treat DEGRADED health as an allowed state on mainnet, and live-readiness evidence comes only from healthy runs (source: docs/DECISIONS.md D056 items 1 to 3; decision: D056)
- [G3-004] The executable G1-G5 gate code (`src/analytics/gates.py`), the append-only `holdout_consumed.json` writer and the `candidate_sha256` serialization (defined only in `scripts/decision_alignment/protocol.py`) do not exist in `src` yet (source: .planning/phases/11-decision-alignment/11-01-SUMMARY.md:143,151, docs/DECISIONS.md D043 and D044 item (3); decision: D043)
- [G1-001] The research-gate is not a required status check on master (GitHub returned 403 on a private repo and an override was accepted); require it, or record a waiver, when the repo or plan changes (source: .planning/phases/01-research-formalization/01-VERIFICATION.md:11-14,126,150; decision: open user decision)
- [G2-041] Triage Phase 10 review Info IN-01, IN-02 and IN-04 to IN-10, with IN-08 first (`scripts/dev/journal-report.ps1` `Import-DotEnv` exports every `.env` secret to the analytics process) (source: .planning/phases/10-journal-depth-kill-gate-operations/10-REVIEW.md:369-373; decision: none required)
- [G2-045] Run the journal-report CLI against a populated Demo or paper journal and have the operator read the first report before any real-evidence kill-gate decision (source: .planning/phases/10-journal-depth-kill-gate-operations/10-VERIFICATION.md:154; decision: none required)
- [G3-005] Promote `DISABLED` into the RejectionReason enum and update GLOSSARY 9.3 (source: docs/GLOSSARY.md:205, docs/DECISIONS.md D044 item (1); decision: D044)
- [G3-030] CR-01 is replaced by D064 (a real rclone run showed that `--checksum` falls back to `--size-only` on a crypt remote): the Parquet push compares SHA-256 against the complete remote manifests and verifies the tree with `rclone cryptcheck` before the manifest is published; the code change is a quick task before the first real backup and this phase re-verifies it in the real restore drill (source: .planning/phases/13.1-deployment-ci/13.1-OPEN-DECISIONS.md:12,51, docs/DECISIONS.md D064; decision: D064)
- [G3-032] OPS-06 provider disk encryption check on the real host (source: .planning/phases/13.1-deployment-ci/13.1-UAT.md:72-77, .planning/REQUIREMENTS.md:79,158; decision: none required, see the Phase 24 entry T-02)
- [G4-033] Separate database roles for the application and for migrations stay deferred to the go-live gate; the application role should not be the table owner and so should not be able to disable the append-only triggers (source: .planning/phases/17-operational-persistence-layer/17-CONTEXT.md:148, .planning/phases/17-operational-persistence-layer/17-02-SUMMARY.md:211; decision: none required)
- [PAPER-03] Verify the 3 to 6 month wall-clock observation window and the no-tuning rule (registry diff, pinned epoch, runtime coverage and time-of-day report) from the long soak that starts after Phase 16, and close PAPER-03; Phase 26 confirms the evidence and does not start the soak; test events (D063 item 3), planned restarts and gaps never count as covered time or as evidence, and a missing freeze tick restarts the qualifying trial (D065 item 4) (source: docs/DECISIONS.md D061 item J, D063, D065, .planning/REQUIREMENTS.md:54; decision: D061, D063, D065)
- [D061-D] The paper exit gate that `enable()` requires is the set of criteria the user ratified before the trial soak (D061 item D), including the runtime coverage fraction and the time-of-day rule; the gate is not redefined here (source: docs/DECISIONS.md D061; decision: D061, clarified by D063 and D065)
- [D065-WR] `LiveEnablementController.enable` reads the shared kill-gate review registry and refuses while any `blocks_live_enable` item (WR-10) is UNRESOLVED, with an automated test; this phase flips each WR item in the registry with its fix commit, and the Phase 16 report guard stays in force for the four `blocks_report` items until then (source: docs/DECISIONS.md D065 item 1, .planning/phases/10-journal-depth-kill-gate-operations/10-REVIEW-DISPOSITION.md; decision: D065)
- [D061-F] The WR-01, WR-06, WR-12 and WR-13 fixes of the kill-gate code are done and verified here; the Phase 16 guard stays in force until then (source: docs/DECISIONS.md D061 item F; decision: D061)

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 26 to break down)

### Phase 27: Configurable Quote Asset (USDC readiness)

**Goal**: The quote/margin asset becomes configuration instead of a constant, so a USDC pair can be evaluated deliberately. This was former Phase 17; its priority is lowered below all safety work.

The following are hard-coded today:
- `LIVE_5` in `src/data/backfill.py:549` and `src/backtest/report.py:34`;
- `QUOTE_ASSET = "USDT"` in `src/analytics/live_outcomes.py:65`.

Switching an instrument requires a DECISIONS entry, new data, a new versioned parameter set with current fees, and re-research. USDT evidence does not transfer.

**Depends on**: Phase 26

**Requirements**: DATA-01, DOMN-02, BKTS-02, JRN-01

**Audit refs**: F-208 (live-5 list duplicated in 4 places), F-031

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 27 to break down)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → … → 10 → 11 → 12 → … → 27. (Phase 8 construction may overlap the Phase 7 paper soak; Phase 8 enablement gates on paper evidence. Phase 13 and Phase 17 depend only on Phase 11, so they may run in parallel with the evidence track 12→14→15→16. No real-money order before Phase 26 is complete (D040: SHADOW → DEMO → CANARY → LIVE).)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Research Formalization | 4/4 | Complete    | 2026-10-04 |
| 2. Data Foundation | 5/5 | Complete    | 2026-10-04 |
| 3. Domain + Registry + Fixtures | 5/5 | Complete    | 2026-10-04 |
| 4. Pure Core (Feature + Strategy + Planner) | 4/4 | Complete    | 2026-10-03 |
| 5. Risk Engine | 2/2 | Complete    | 2026-10-03 |
| 6. Backtest Simulator + Experiment Registry | 3/3 | Complete   | 2026-09-26 |
| 7. Paper Forward Observation | 4/4 | Complete    | 2026-10-04 |
| 8. Approval + Reconciliation Hardening | 5/5 | Complete    | 2026-09-27 |
| 9. Live Execution Rollout | 4/4 | Complete    | 2026-10-04 |
| 10. Journal Depth + Kill-Gate Operations | 12/12 | Complete    | 2026-10-04 |
| 11. Decision Alignment (docs + params) | 8/8 | Complete    | 2026-10-04 |
| 12. Fee + Cost Model Correctness | 11/11 | Complete    | 2026-09-30 |
| 13. Research Data Foundation Fixes | 13/13 | Complete    | 2026-10-03 |
| 13.1. Deployment & CI | 12/12 | Complete | 2026-10-04 |
| 14. Backtest Simulator Causality Rewrite | 17/17 | Complete    | 2026-10-07 |
| 15. Strategy Geometry Correction | 18/18 | Complete    | 2026-10-07 |
| 16. Paper Runtime Composition + SHADOW Approval Mode | 34/52 | In Progress|  |
| 17. Operational Persistence Layer | 15/15 | Complete    | 2026-10-07 |
| 18. Binance User-Data Stream + Exchange Error Taxonomy | 0/TBD | Not started | - |
| 19. Execution Plan Binding + Pre-Placement Checks | 0/TBD | Not started | - |
| 20. Reconcile + SAFE_MODE Hardening + Alerts | 0/TBD | Not started | - |
| 21. Account Equity + Daily Loss from Binance | 0/TBD | Not started | - |
| 22. Leverage, Margin + Liquidation Guard | 0/TBD | Not started | - |
| 23. Telegram Approval Hardening + Two-Step Confirm + Money Amounts | 0/TBD | Not started | - |
| 24. Live Runtime Composition + Demo Rehearsal | 0/TBD | Not started | - |
| 25. Binance Demo Integration Test Campaign | 0/TBD | Not started | - |
| 26. Go-Live Readiness Gate | 0/TBD | Not started | - |
| 27. Configurable Quote Asset (USDC readiness) | 0/TBD | Not started | - |

## Backlog

### Phase 999.1: Follow-up — Phase 15 deferred UAT follow-up: Test 9 (BACKLOG)

**Goal:** Resolve the UAT checkpoint deferred during Phase 15 verification
**Source phase:** 15
**Deferred at:** 2026-10-07 during /gsd-verify-work 15 session completion
**Follow-ups:**
- [ ] Test 9: hoãn — revisit whether to reject a TP1 inside the far half of the entry zone after the research re-run (D054 item g) (deferred 2026-10-07)

### Phase 999.2: Research runner owner (BACKLOG)

**Goal:** Give an owner to the research-runner items that Phase 14 deferred to "the Phase 15 research runner", which no phase plans
**Source phase:** 14
**Recorded at:** 2026-10-07 during the Phase 14 close (user agreed)
**Ownership (D059 item 5, 2026-10-07):** this is not a numbered phase. Phase 16 owns the research runner, the feasibility and sample-size gate and the registration of candidate parameter sets; Phase 26 requires a passing candidate produced by that work. Candidates come only from pre-registered values with a rationale, never from a backtest result, and still need the user's exact-hash approval before paper start. The matching entries are in the Inherited items blocks of Phase 16 and Phase 26.
**Follow-ups:**
- [ ] `modeled_costs_per_unit` is `None` on v2 filled `TradeRecord`s (14-12 item, D052): decide whether the runner restores it
- [ ] No production caller of `read_code_version` plus `assemble` exists outside tests (D052): the runner must call them so a real run produces an `ExperimentRecord`; Phase 26 only owns holdout-once enforcement
- [ ] OQ-1 (deferred-items.md "Open decisions for the user"): how a trade held through mark-price holes is treated in the evidence, to measure with the first real-data research run and to decide the methodology before any candidate is evaluated with that metric (D063 item 8)
- [ ] BKTS-03 parameter-plateau analysis and sweep runner: REQUIREMENTS.md keeps BKTS-03 Pending against closed Phase 6 and `src/backtest/report.py` prints "not computed (BKTS-03 pending)"; Phase 14 left it to a runner (14-CONTEXT.md D-21, D-37), so the Phase 16 research runner delivers it

### Phase 999.3: Info-finding cleanups (BACKLOG)

**Goal:** Give every review Info finding and housekeeping item that no phase owns a named home and a pick-up trigger, so none is silently dropped. Each line says what it is, where it came from and when to pick it up. Triggers are proposals; none is a user decision.
**Source phase:** 02 to 17 review files
**Recorded at:** 2026-10-07 during the ownership batch
**Follow-ups:**
- [ ] Phase 02 (`02-REVIEW.md` IN-01, IN-02; `02-REVIEW.iter3.md` IN-02, IN-04 to IN-07): FundingSweepResult.empty ambiguity, the harvest-complete marker sharing `collector_gaps`, `oi_coverage_rows` swallowing `except duckdb.Error: continue` (`src/data/coverage.py:514`), `backfill_universe` aborting the whole universe on the first key failure. Trigger: the next change to `src/data` coverage or backfill; take `coverage.py:514` and the harvest marker first.
- [ ] Phase 03 (`03-REVIEW.md` IN-01, IN-04, IN-06): registry barrel omits public API, `JournalEventRow.created_at_utc` nullable (`src/db/models.py:720`), `derive_child_id` discriminators are convention only. Trigger: the next persistence or id change; IN-04 matters before audit rows are relied on.
- [ ] Phase 04 (`04-REVIEW.md` IN-01, IN-02, IN-07 substantive; IN-03, IN-05, IN-06 cosmetic): `Decimal(str(x))` float fallback at boundaries, bare `int()` truncation of Decimal parameters, `Signal.direction`, `setup_type` and `source_timeframe` as unvalidated strings (`src/domain/signal.py:50-51`, can fork ids). Trigger: before the research runner registers a candidate (Phase 16).
- [ ] Phase 05 (`05-REVIEW.md` IN-01, IN-03, IN-04): a structlog failure propagates from pure risk math (`src/risk/quantization.py`), inverted warning and stop thresholds are not rejected, `src/risk/__init__.py` docstring overstates purity. Trigger: Phase 21 daily-loss work (fail-closed hygiene).
- [ ] Phase 06 (`06-REVIEW.md` IN-06): `verify_parameter_set` derives identity from `path.parent.name` (`src/domain/registry.py:621`) with no REGISTRY_ROOT anchor. Trigger: the next registry change.
- [ ] Phase 07 (`07-REVIEW.md` IN-01 to IN-07; IN-04 is owned by Phase 16): dead identity helpers, barrel omits the supervisor, duplicated retry ceilings, the SKIP label, `test_domain_no_float` scan list. Trigger: Phase 16 planning, or close as won't-fix.
- [ ] Phase 07.1 (`07.1-REVIEW.md` IN-01 to IN-05): `binding.py` docstring misattributes the KeyError source, bare KeyError lacks the set identity, no divergent-keys hint, no breakout match fixture, `reproduce()` raises a bare KeyError outside the tripwire vocabulary. Trigger: the next change to `src/backtest/binding.py`.
- [ ] Phase 08 (`08-REVIEW.md` IN-01 to IN-16; IN-10 is owned by Phase 18, IN-14 and IN-15 by Phase 20): dead code and two drill outcomes never emitted (`src/ops/drills.py`). Trigger: Phase 20 planning.
- [ ] Phase 09 (`09-REVIEW-DISPOSITION.md` IN-01 to IN-07): carried into Phase 24 (see its Inherited items); IN-02 and IN-04 look stale and need a check first. Trigger: Phase 24 planning.
- [ ] Phase 10 (`10-REVIEW.md` IN-01 to IN-10): owned by Phase 26 (see its Inherited items); IN-03 looks stale. Trigger: Phase 26 planning.
- [ ] Phase 11 (`11-REVIEW.md` IN-01 to IN-08): tautological UN-03/04/05 gates, `SYMBOL_RE` in `scripts/decision_alignment/universe.py`, triplicated hash tables, weak bash freeze witnesses, power note. Trigger: the next decision-alignment gate change.
- [ ] Phase 12 (`12-REVIEW.md` IN-01 to IN-06): IN-01 and IN-05 are folded into Phase 24 commission wiring; the rest (ASCII regex before Decimal, `MAX_RATE` defined in four places, "byte-locked" wording, lazy guard-rate load) wait. Trigger: Phase 24 commission-wiring plan.
- [ ] Phase 13.1 (`13.1-REVIEW.md` IN-01 to IN-10): unquoted replacement in `backup.sh`, hard-coded systemd `User=trading`, Docker apt key not fingerprint-pinned, plaintext restore copies accumulate, `drill-remote` compares only row counts, stale `BACKUP_TARGET` docs, dead `portfolio.py` assignments and the F841 waiver, CI triggers on master only so develop is ungated, compose lacks no-new-privileges and cap_drop. Trigger: Phase 26 criterion 4 hardening review.
- [ ] Phase 14 (`14-REVIEW.md` IN-01 to IN-08; `14-REVIEW-MARK-HOLES.md` IN-01 to IN-03): IN-03 latent look-ahead (constraints back-extrapolated, only counted), IN-04 duplicate scripted `signal_id`, IN-05 dead kind and float coercion, IN-06 population standard deviation feeding a standard error, IN-08 latent run abort; the mark-holes items were left open by choice. Trigger: the first real-data research run (Phase 16); IN-03 needs an evidence gate on the extrapolated-constraint count.
- [ ] Phase 15 (`15-REVIEW-DISPOSITION.md` IN-02 to IN-06; IN-02 is placed in Phase 19): census extra bar, snapshot script asserts, non-ASCII digits in the rationale checker, maintainability. Trigger: mark IN-03 to IN-06 `deferred` in the disposition file at the next Phase 15 file touch. The paper-gate review Info items (`15-REVIEW-PAPER-GATE.md` IN-01 to IN-05) are in Phase 16.
- [ ] Phase 17 (`17-REVIEW.md` IN-01 to IN-03; IN-04 is placed in Phase 23): stale "exchange-deduped" docstring (`src/execution/__init__.py:4`), SQL params chained into errors, the consume UPDATE not bound to plan and hash. Also `src/persistence/__init__.py` module map lists 4 of 9 modules. Trigger: the first Phase 18 or Phase 20 plan that touches `src/persistence`.
- [ ] Housekeeping: funding is stored one Parquet file per tick (about 50,000 files under `data/raw/data_class=funding`); group by day or month, which changes backfill, the case-input builder and the backup readers together. Trigger: before the first full-history backup restore drill (Phase 26 criterion 3). Source: `.planning/phases/13-research-data-foundation-fixes/deferred-items.md:35`.
- [ ] Housekeeping: `tests/test_backfill_cli.py` fails intermittently (`rc == 1`, about 1 in 15 to 30 runs) and the cause is unknown; explain and fix it, a rerun-once policy is not acceptable. Trigger: the first CI flake on the Phase 26 remote CI, or sooner. Source: `.planning/phases/13.1-deployment-ci/13.1-12-SUMMARY.md:59`.
- [ ] Housekeeping: doc overclaims. `.env.example:66-68` and `docs/operations/SECURITY_AND_OPERATIONS.md:12` say a paper process can never pick up a live credential (true only of variable names, see WR-06 in Phase 24); `docs/operations/RUNBOOK.md:390` says the CI docker job "has run nowhere" although it has run. Trigger: one docs quick task, or WR-06 closing in Phase 24.
- [ ] Housekeeping: `src/execution/gates.py:26-38` comment still says the 200 conditional-order limit is per symbol and a "KNOWN GAP"; docs/trading/EXECUTION_SPEC.md:236 says it is an account-wide count with the 200 limit from the docs. Trigger: the next change to `src/execution/gates.py`.
- [ ] Housekeeping: `src/risk/gating.py:50` docstring "A stop inside the zone is deliberately..." predates the D054 baseline wording. Trigger: the next risk-code touch (Phase 19 or 22).
- [ ] Housekeeping: `src/paper/journal.py:17` docstring still says the Parquet extract mirror is "deferred to Phase 10", but Phase 10 chose SELECT-only SQL readers. Trigger: the next change to `src/paper/journal.py`.
- [ ] Housekeeping: `10-UI-SPEC.md` lacks CLI exit code 3 (defined in `src/analytics/cli.py:14` and `journal-report.ps1`). Trigger: the next analytics CLI change.
- [ ] Housekeeping: each SDK minor bump (`>=17.3,<18`) re-runs the COVERAGE re-verification; nothing assigns this step. Trigger: every bump of `binance-sdk-derivatives-trading-usds-futures`, see `.planning/phases/02-data-foundation/COVERAGE.md:88`.
