# Roadmap: Deterministic Binance Futures Research & Semi-Automated Execution System

## Overview

Research-first path from frozen protocol to cautious live orders: formalize the research contract and resolve doc contradictions (Phase 1), bootstrap the irrecoverable data foundation with the OI collector running from day one (Phase 2), lock reproducibility via domain model plus versioned registry plus fixture harness (Phase 3), build the pure deterministic core (Phase 4) and identical-everywhere risk engine (Phase 5), earn evidence through the backtest parity engine (Phase 6) and the 3–6-month paper forward-observation long pole (Phase 7), harden approval plus reconciliation plus RUNBOOK rehearsal before any live order (Phase 8), roll out live on smallest capital (Phase 9), then deepen journal analytics and operate the kill gate where NO_TRADE is a valid terminal outcome (Phase 10).

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Research Formalization** - Frozen protocol, three family hypotheses, doc contradictions resolved
- [ ] **Phase 2: Data Foundation** - Candles, day-one OI collector, funding, metadata, backup drill
- [ ] **Phase 3: Domain + Registry + Fixtures** - Seven entities, versioned params, golden-fixture harness
- [ ] **Phase 4: Pure Core (Feature + Strategy + Planner)** - Deterministic signals and trade plans from closed candles
- [ ] **Phase 5: Risk Engine** - Identical sizing/quantization/portfolio caps in every mode
- [x] **Phase 6: Backtest Simulator + Experiment Registry** - 1m intrabar parity engine with uncertainty-first reports (completed 2026-09-26)
- [ ] **Phase 7: Paper Forward Observation** - WS realtime loop, three-way attribution, no tuning on paper
- [x] **Phase 8: Approval + Reconciliation Hardening** - Idempotent Telegram approvals, orphan sweeper, SAFE_MODE rehearsed (completed 2026-09-27)
- [ ] **Phase 9: Live Execution Rollout** - LIMIT-zone entries, Algo protective exits, smallest capital
- [ ] **Phase 10: Journal Depth + Kill-Gate Operations** - MFE/MAE analytics and the 3-families/6-months stop rule

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

**Plans**: 4 plans

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

**Plans**: 5 plans

Plans:

- [ ] 02-01: Toolchain + storage skeleton + SDK re-verify + COVERAGE matrix
- [ ] 02-02: Tracer end-to-end candle slice (one symbol, one interval)
- [ ] 02-03: Full live-5 bounded-depth bootstrap with TDD quality gates
- [ ] 02-04: Versioned metadata + day-one OI/funding collector (TDD)
- [ ] 02-05: Coverage CLI/views + backup drill on off-host target

### Phase 3: Domain + Registry + Fixtures

**Goal**: Every decision is traceable and reproducible — new behavior must be expressible as a versioned set before it exists.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: DOMN-01, DOMN-02, DOMN-03
**Success Criteria** (what must be TRUE):

  1. Seven entities (Signal, TradePlan, Approval, Order, Fill, Position, JournalEvent) persist separately with GLOSSARY-canonical enums and no state inferred from nullable columns
  2. Any backtest, paper run, alert, or order plan displays its immutable identity (strategyVersion + parameterSetId + parameterSetHash + experiment linkage)
  3. Golden fixtures (candles.csv + parameters.json + expected signals/plans) plus no-lookahead, prefix-invariance, candle-close-timing, and boundary suites pass in CI; unregistered semantic changes are rejected

**Plans**: 5/5 plans executed

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

**Plans**: 4/4 plans executed

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

**Plans**: 2 plans

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

**Plans**: 4/4 plans executed

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

**Plans**: 4/5 plans executed

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

- [ ] 08-05: RUNBOOK 8-drill harness plus journaled drill log plus phase gate (OPS-01, D-05)

### Phase 9: Live Execution Rollout

**Goal**: First cautious live orders on smallest capital — evidence earned in Phases 6–7 spends here.
**Mode:** mvp
**Depends on**: Phase 8
**Requirements**: EXEC-01, OPS-02
**Success Criteria** (what must be TRUE):

  1. Approved plan places a LIMIT-zone entry and Algo-Order protective exits (endpoints re-verified against current Binance docs), supports both position modes, and sizes protection correctly on partial fills
  2. Live constraints are revalidated from exchangeInfo at placement time and DAILY_STOP is enforced against live state
  3. Live credentials use no-withdrawal keys with IP allowlisting, secrets live off-source, logs are structured and secret-free, and health checks are green — first orders only on smallest capital in the live-5 universe

**Plans**: 4/4 plans executed

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

**Plans:** 7/12 plans executed
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
- [ ] 10-08-PLAN.md — Composed JournalDepthReport: per-kind blocks, provenance, INCOMPLETE ledger, kill-gate section, unpooled evidence (JRN-01, GOV-01, D-01, D-05)
- [ ] 10-09-PLAN.md — Edge adapters: family/evidence/decision loaders, path confinement, SELECT-only journal/entity/candle readers, guarded idempotent append (JRN-01, GOV-01, D-05)

**Wave 5** *(blocked on Wave 4 completion)*
- [ ] 10-10-PLAN.md — Renderer part 1: formatting/escaping primitives, header, Kill Gate view, Evidence Overview (JRN-01, GOV-01, D-04)

**Wave 6** *(blocked on Wave 5 completion)*
- [ ] 10-11-PLAN.md — Renderer part 2: sections 3-10, JSON sidecar with digest verification, Telegram pointer text, governance scans (JRN-01, GOV-01, D-04)

**Wave 7** *(blocked on Wave 6 completion)*
- [ ] 10-12-PLAN.md — CLI + PowerShell wrapper, explicit idempotent --record, closing purity/determinism/regression guards (JRN-01, GOV-01, D-04)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 (Phase 8 construction may overlap the Phase 7 paper soak; Phase 8 enablement gates on paper evidence)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Research Formalization | 0/TBD | Not started | - |
| 2. Data Foundation | 0/TBD | Not started | - |
| 3. Domain + Registry + Fixtures | 5/5 | In Progress|  |
| 4. Pure Core (Feature + Strategy + Planner) | 4/4 | In Progress|  |
| 5. Risk Engine | 2/2 | In Progress|  |
| 6. Backtest Simulator + Experiment Registry | 3/3 | Complete   | 2026-09-26 |
| 7. Paper Forward Observation | 4/4 | In Progress|  |
| 8. Approval + Reconciliation Hardening | 5/5 | Complete   | 2026-09-27 |
| 9. Live Execution Rollout | 4/4 | In Progress|  |
| 10. Journal Depth + Kill-Gate Operations | 7/12 | In Progress|  |
