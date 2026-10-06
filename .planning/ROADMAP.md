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
- [ ] **Phase 14: Backtest Simulator Causality Rewrite** - Fills only after the signal bar, multi-bar holding, TP1/TP2 ladder, funding, mark-price triggers
- [ ] **Phase 15: Strategy Geometry Correction** - Trend-pullback SL outside zone, confirmed pivots, min stop distance; families match their sheets
- [ ] **Phase 16: Paper Runtime Composition + SHADOW Approval Mode** - Runnable paper process (M3), fixed WS await, simulated fills, SHADOW APPROVE/SKIP journaled with no order path (D040); soak can start
- [ ] **Phase 17: Operational Persistence Layer** - PostgreSQL journal/approval/execution stores, integrity constraints, durable approval consumption, write-ahead intent
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

**Plans:** 16/16 plans executed

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

**Plans:** 14/15 plans executed

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
- [ ] 15-15-PLAN.md — Criterion-4 readiness (smoke and census on v6 sets), final audit verdicts, D054 with regeneration inventory

### Phase 16: Paper Runtime Composition + SHADOW Approval Mode

**Goal**: A runnable paper process observes the corrected families forward, so the wall-clock-bound soak can finally start. The operator can already APPROVE/SKIP (with the D041 confirm step) in SHADOW mode to build a decision history, with no possible path to a real order (D040).

**Depends on**: Phase 12, Phase 15

**Requirements**: PAPER-01, PAPER-02, PAPER-03

**Success Criteria**:
1. The paper supervisor → tick → journal writer chain is composed and runnable as a process (M3) (F-201).
2. The WS adapter awaits the async SDK call. Fakes are contract-bound to the SDK's async signatures (F-125, F-607).
3. A simulated fill producer uses the same fill semantics as Phase 14. Approval delay is measured, not a fixed 30 s. SIMULATE buttons are functional (F-961).
4. The paper exit criteria are quantitative and pre-registered (F-023).
5. SHADOW mode (D040): SIMULATE/APPROVE messages are clearly labelled "SHADOW — no real order"; APPROVE → CONFIRM (D041) / SKIP / expiry are journaled with timestamps and approval delay; each confirmed plan gets a simulated position using the Phase-14 fill semantics on live market data, and the journal reports system vs user vs opportunity outcomes (F-961).
6. Hard isolation: in SHADOW the process loads no trade-capable API key and never constructs an order adapter; a test proves that no code path from a SHADOW confirm reaches `execute_approved_plan` or any order endpoint.
7. **Carried over from Phase 7 (live WS):** a live smoke run shows `ws_subscribe` succeeding and delivering closed-candle events to the supervisor (`soak_smoke.log` reads `ws_subscribe=BLOCKED` with 0 events today). Phase 7 verified WS ingestion only with fakes. Live probe on mainnet (2026-10-04) found three stacked causes, all in `src/adapters/paper_ws.py`: (a) `create_connection` and `kline_candlestick_streams` are coroutines called without `await`; (b) the SDK interval Enum is passed through, and on Python 3.13 it formats as `...IntervalEnum.INTERVAL_1m`, so the stream name is invalid and Binance sends nothing, silently; pass the plain string `"1m"`; (c) the default `ConfigurationWebSocketStreams()` has no `stream_url` (use the SDK PROD constant). A spike with awaited calls, a plain-string interval and `stream_url` received 3 BTCUSDT kline events in 3 s; the handle is a `RequestStreamHandle` (`.on("message", cb)`, no `on_message`), and the stream delivers open candles too, so the supervisor must keep only `is_closed` events.
8. **Carried over from Phase 7 (SC3 soak evidence):** the stream epoch is pinned (`pin_stream_epoch`) and `python -m src.paper.freeze` runs hourly for the soak window; `logs/paper/pinned_epoch.json` and `logs/paper/registry_diff.jsonl` exist, every diff line is CLEAN, there is one `epoch_id`, and the pinned hash is unchanged. Nothing has ever been pinned yet. Source: `07-VERIFICATION.md` `behavior_unverified_items`.
9. **Requirement closure rule:** PAPER-01, PAPER-02 and PAPER-03 stay Pending until criteria 1, 2, 7 and 8 hold. Phase 7 was closed on 2026-10-04 by operator decision with these requirements still unmet, so Phase 16 is the phase that closes them and must not mark them complete on the strength of fake-level tests.

**Audit refs**: F-201, F-125, F-607, F-961, F-023, D040, D041; carry-over from Phase 7 (`.planning/phases/07-paper-forward-observation/07-VERIFICATION.md`)

**Plans:** 0 plans

Plans:
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

**Plans:** 15/15 plans executed

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
2. A demo or testnet probe records the actual not-found codes for GET order and GET algoOrder. Adapter mappings are keyed on `status_code`, including -2011, -2013, -2019, -4164, -1021 and -2021 (F-501, F-205, F-503, F-502).
3. The client configuration supports:
   - explicit REST timeouts;
   - API key loading;
   - Demo (`demo-fapi.binance.com`) / testnet / live selection;
   - recvWindow with a server-time drift check that fails closed;
   - no retry on 418, and honoring `retry_after`.
   (F-504, F-128, F-505, F-706, F-506)

**Audit refs**: F-104, F-054, F-501, F-205, F-503, F-502, F-504, F-128, F-505, F-706, F-506

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
4. Two-step confirm (D041): APPROVE edits the message into a confirmation card (mode SHADOW/DEMO/LIVE, symbol, side, quantity, notional, estimated loss at SL, current mark price vs entry/SL, remaining validity) with CONFIRM/CANCEL. Only CONFIRM triggers placement. The confirm token is distinct, single-use, bound to the same user id and plan hash, with a short TTL (default 60 s); CANCEL/expiry places nothing and is journaled; pre-placement checks re-run at confirm time. Tests cover: double-tap, replayed CONFIRM callback, CONFIRM after TTL, CONFIRM by another user, CONFIRM after the plan expired or price crossed SL.
5. **Findings from the live Telegram test (2026-10-04, Phase 8 behaviour):** a decided message keeps its button and the bot answers every later tap (replays are idempotent: 3 taps gave 1 transition, but the keyboard must be removed and later taps refused); `actor_id` is empty on the decided approval, so the journal does not say who decided; APPROVE moves straight to APPROVED with no CONFIRM step (D041); the application has no error handler, so callbacks queued during downtime raise `BadRequest: Query is too old` at `query.answer()` and must be handled; the messages show no money amounts and the display note says Asia/Ho_Chi_Minh while the times are UTC; SIMULATE/APPROVE/SKIP are separate keyboards, so one message carries one button (decide whether one message should carry APPROVE and SKIP together).

**Audit refs**: F-508, F-707, F-405, F-509, F-127, F-015, F-016, D041

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

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 25 to break down)

### Phase 26: Go-Live Readiness Gate

**Goal**: Live trading can only be enabled affirmatively: a family has passed under protocol v1.1.0, the paper exit gate is met, the demo campaign passed, all safety phases are verified, operations are real, and a small canary on the real exchange succeeded (D040). Otherwise it cannot be enabled.

**Depends on**: Phase 25

**Requirements**: GOV-01, OPS-01, OPS-02, PAPER-03, GOV-02

**Success Criteria**:
1. `enable()` requires a recorded passing candidate, a met paper exit gate, a passed Phase-25 demo campaign and a minimum capital. WITHIN_BUDGET is refused. The skipped Phase-10 review items WR-01/06/10/12/13 are resolved (F-953, F-105, F-960).
2. Phases 06–25 each have a VERIFICATION.md written after their last review-fix wave. The ~30 "requires human verification" fixes are confirmed, and 05-VERIFICATION is reopened (F-807, F-808, F-109, F-956). One-way checkpoints carry recorded human decisions (F-124, F-809).
3. Backups are off-VPS and encrypted (D042), run on a schedule and follow a retention policy. The pg_dump URL is fixed. A real PostgreSQL restore drill onto a fresh machine passes (F-108, F-910, F-121, F-704).
4. CI on a real remote runs pytest, ruff, mypy and the registry gate, and all are green (F-101, F-605). The Docker healthcheck uses the venv and Postgres binds to localhost (both hardened in Phase 13.1, re-verified here). The images are pinned. Secrets are scrubbed from errors (F-705, F-709, F-708).
5. CANARY (D040): a mainnet READ-ONLY API key (trade and withdraw disabled, IP-restricted to the VPS address per D042) verifies real exchangeInfo filters, commission rates, mark prices and balances against what the system assumes; then a dedicated small isolated sub-account (order of USD 50–100, minimum size, leverage ≤ cap) executes a pre-registered number of trades with the operator watching, with zero divergences before full LIVE is allowed.

**Audit refs**: F-953, F-105, F-960, F-807, F-808, F-109, F-124, F-809, F-108, F-121, F-704, F-101, F-605, F-705, F-709, F-708, D040, D042

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
| 14. Backtest Simulator Causality Rewrite | 16/16 | In Progress|  |
| 15. Strategy Geometry Correction | 14/15 | In Progress|  |
| 16. Paper Runtime Composition + SHADOW Approval Mode | 0/TBD | Not started | - |
| 17. Operational Persistence Layer | 15/15 | In Progress|  |
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
