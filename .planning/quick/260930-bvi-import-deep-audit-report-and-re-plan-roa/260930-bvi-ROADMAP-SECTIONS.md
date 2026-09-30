# Exact replacement content for .planning/ROADMAP.md (quick 260930-bvi)

Four blocks follow. Each is delimited by `<<<BLOCK n` … `BLOCK n>>>`. The delimiters themselves are not part of the content. Copy the text between the delimiters verbatim.

---

## BLOCK 1: append a new paragraph at the end of the `## Overview` section

Insert it after the existing Overview paragraph and before `## Phases`, separated from both by one blank line.

<<<BLOCK 1
**Re-plan 2026-09-30 (deep audit).** A read-only deep audit of snapshot `63ca176` is archived in `.planning/audits/2026-09-29-deep-audit/`. Start with `BAO_CAO_TONG_HOP.md`, then read `DEEP_AUDIT_REPORT.md`, whose §19 is the remediation plan and §20 lists the human decisions. It found:
- 152 findings (0 CRITICAL, 12 HIGH).
- Backtest evidence is invalid: same-bar look-ahead and fills at untraded prices.
- The live path is library-only: no runtime composition, no operational persistence, no user-data stream.
- Several auto-selected planning decisions were wrong.

The user decided D031–D039 in `docs/DECISIONS.md`. Phases 11–26 below replace the earlier backlog-promoted phases 11–17 and carry their scope forward:
- old 11 → 12
- old 12 → 21
- old 13 + 14 → 22
- old 15 → 19
- old 16 → 23
- old 17 → 26

Order rule:
- Evidence correctness (11–16) comes before any paper soak is trusted.
- Every money-safety phase (17–23) comes before any live order.
- Live enablement (25) requires 11–24 complete.

Finding IDs (F-xxx) refer to `.planning/audits/2026-09-29-deep-audit/findings.json`.
BLOCK 1>>>

---

## BLOCK 2: replace the seven phase-list lines

This replaces the lines from `- [ ] **Phase 11: Fix fee units in sizing ...` through `- [ ] **Phase 17: Configurable quote asset ...` inclusive.

<<<BLOCK 2
- [ ] **Phase 11: Decision Alignment (docs + params)** - Apply D031–D039 to canonical docs and parameter sets; protocol v1.1.0 pre-registration
- [ ] **Phase 12: Fee + Cost Model Correctness** - Costs in quote currency everywhere, taker entry, exit slippage, real commission rate (was Phase 11)
- [ ] **Phase 13: Research Data Foundation Fixes** - History depth, point-in-time universe, mark-price klines, backfill robustness, Parquet→backtest builder
- [ ] **Phase 14: Backtest Simulator Causality Rewrite** - Fills only after the signal bar, multi-bar holding, TP1/TP2 ladder, funding, mark-price triggers
- [ ] **Phase 15: Strategy Geometry Correction** - Trend-pullback SL outside zone, confirmed pivots, min stop distance; families match their sheets
- [ ] **Phase 16: Paper Runtime Composition** - Runnable paper process (M3), fixed WS await, simulated fills, measured approval delay; soak can start
- [ ] **Phase 17: Operational Persistence Layer** - PostgreSQL journal/approval/execution stores, integrity constraints, durable approval consumption, write-ahead intent
- [ ] **Phase 18: Binance User-Data Stream + Exchange Error Taxonomy** - listenKey + ORDER/ALGO/ACCOUNT events, error-code mapping, demo/testnet switch, clock checks
- [ ] **Phase 19: Execution Plan Binding + Pre-Placement Checks** - Symbol/side/qty bound to the approved plan, live-price check, SL-reject fallback (absorbs old Phase 15)
- [ ] **Phase 20: Reconcile + SAFE_MODE Hardening + Alerts** - No blind spots, pending-entry SL kept, auto SL re-place (D034), durable SAFE_MODE, operational alerts
- [ ] **Phase 21: Account Equity + Daily Loss from Binance** - Binance-canonical equity and D033 daily-loss state (was Phase 12)
- [ ] **Phase 22: Leverage, Margin + Liquidation Guard** - ISOLATED, 5x cap, liquidation beyond SL, available margin incl. resting entries (was Phases 13 + 14)
- [ ] **Phase 23: Telegram Approval Hardening + Money Amounts** - User-id auth, working SKIP, keyboard removal, $ amounts in messages (was Phase 16)
- [ ] **Phase 24: Live Runtime Composition + Demo Rehearsal** - Wire APPROVE→execute, bot runner, schedulers, live risk inputs; end-to-end on Binance Demo Trading
- [ ] **Phase 25: Go-Live Readiness Gate** - Affirmative enablement gate, verification closure 06–10, real backups, CI, ops minimum
- [ ] **Phase 26: Configurable Quote Asset (USDC readiness)** - Remove USDT hard-coding; deliberate USDC evaluation (was Phase 17)
BLOCK 2>>>

---

## BLOCK 3: replace the Phase Details sections

This replaces everything from the heading `### Phase 11: Fix fee units in sizing + use the account's real commission rate` up to, but not including, `## Progress`.

<<<BLOCK 3
### Phase 11: Decision Alignment (docs + params)

**Goal**: The canonical docs and the versioned parameter sets say what the user decided in D031–D039. Under D031, DECISIONS.md outranks docs, so the conflicting doc text must be amended, and no later phase may be planned against stale rules.

**Depends on**: Phase 10

**Requirements**: RSCH-01, RSCH-02, RISK-02, EXEC-02, OPS-01. New REQ-IDs are to be added for the lost MUST-level doc requirements (F-116).

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

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 11 to break down)

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

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 12 to break down)

### Phase 13: Research Data Foundation Fixes

**Goal**: Research runs on enough correct, point-in-time data, and the Parquet store feeds the backtest directly.

**Depends on**: Phase 11

**Requirements**: DATA-01, DATA-02, DATA-03, BKTS-02

**Success Criteria**:
1. The OI collector is deployed and running. This is time-sensitive, because each day of delay loses a day of OI permanently; if it is not already running, do it first as an ops task (F-107).
2. A CLI backfills the decided history depth: 1m for 6–12 months, 1H/4H for 2 years (F-906). It covers the point-in-time research universe from D039, including delisted symbols (F-024, F-907), and runs `backfill_universe` / `refresh_symbol_metadata` (F-122).
3. Mark-price klines are ingested for SL/TP trigger evaluation (D037).
4. Backfill never publishes a partial UTC day as immutable data. It writes files atomically (tmp + replace) and accepts zero-trade bars (F-402, F-408, F-409). The supervisor backfills before it resubscribes (F-413).
5. A Parquet → backtest case-input builder exists (M4, v0.3 audit).

**Audit refs**: F-107, F-906, F-907, F-024, F-122, F-402, F-408, F-409, F-413

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 13 to break down)

### Phase 14: Backtest Simulator Causality Rewrite

**Goal**: The backtest cannot see the future. A plan created at the close of bar N can fill only from bar N+1, until expiry, at a price that actually traded. Positions carry across bars, and exits follow live semantics. All earlier backtest evidence is declared void.

**Depends on**: Phase 12, Phase 13

**Requirements**: BKTS-01, BKTS-02, DOMN-03

**Success Criteria**:
1. The entry fills only after the signal bar, and only on a trade-through of the limit price by at least one tick (F-120/F-901, F-902). The invariants `entry_time > signal_close` and `exit_time ≥ entry_time` are asserted on every trade (F-804).
2. Positions are held across bars until SL, TP or expiry. The TP1/TP2 ladder matches live (F-102). SL/TP triggers are evaluated on mark-price klines (D037).
3. Funding is modeled with a documented sign convention (F-905, F-021). Constraints are point-in-time. Portfolio, daily-loss and equity state evolve through the run (F-305).
4. The R denominator is identical for backtest and live (F-204). The regime slice is emitted (F-123). ExperimentRecord carries the protocol-mandatory fields (F-118).
5. Every golden case has a hand-derived expected output that is not produced by the code under test. The fixture generator no longer places 1m data inside the signal bar (F-602, F-805, F-608).

**Audit refs**: F-120, F-901, F-902, F-102, F-804, F-905, F-305, F-204, F-123, F-118, F-602, F-805, F-904

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 14 to break down)

### Phase 15: Strategy Geometry Correction

**Goal**: Each family's implemented geometry matches its family sheet and is economically sane before any research run is trusted.

**Depends on**: Phase 14

**Requirements**: STRAT-01, STRAT-02

**Success Criteria**:
1. For trend-pullback, the SL lies outside the entry zone with a minimum ATR distance. Swings use confirmed pivots only, excluding the evaluated bar, so a setup cannot fire on a new 20-bar low (F-301).
2. The implemented geometries of all three families match the sheets' Stage baselines, or a DECISIONS entry records the deviation (F-113).
3. New versioned parameter sets record a rationale for every value; no fixture seed values are used (F-909).
4. A research re-run under protocol v1.1.0 is ready to start on the Phase-14 engine. The run itself is a research activity, not part of this phase.

**Audit refs**: F-301, F-113, F-909

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 15 to break down)

### Phase 16: Paper Runtime Composition

**Goal**: A runnable paper process observes the corrected families forward, so the wall-clock-bound soak can finally start.

**Depends on**: Phase 12, Phase 15

**Requirements**: PAPER-01, PAPER-02, PAPER-03

**Success Criteria**:
1. The paper supervisor → tick → journal writer chain is composed and runnable as a process (M3) (F-201).
2. The WS adapter awaits the async SDK call. Fakes are contract-bound to the SDK's async signatures (F-125, F-607).
3. A simulated fill producer uses the same fill semantics as Phase 14. Approval delay is measured, not a fixed 30 s. SIMULATE buttons are functional (F-961).
4. The paper exit criteria are quantitative and pre-registered (F-023).

**Audit refs**: F-201, F-125, F-607, F-961, F-023

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 16 to break down)

### Phase 17: Operational Persistence Layer

**Goal**: Operational state lives durably in PostgreSQL with integrity constraints. A replayed callback or a restart can never create a second entry.

**Depends on**: Phase 11

**Requirements**: DOMN-01, APRV-02, EXEC-03

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

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 17 to break down)

### Phase 18: Binance User-Data Stream + Exchange Error Taxonomy

**Goal**: The system learns fills, order and algo state, and account changes from Binance in real time. It interprets exchange errors by code, not by message text, and it can target Binance Demo Trading.

**Depends on**: Phase 17

**Requirements**: EXEC-01, EXEC-02, OPS-02. A new REQ-ID is to be added for the user-data stream (lost requirement, F-104).

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

**Requirements**: APRV-01, APRV-02, EXEC-01, EXEC-02

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

**Requirements**: EXEC-02, OPS-01. A new REQ-ID is to be added for operational alerts (F-106).

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
1. `change_margin_type` / `change_initial_leverage` are applied and verified via `/fapi/v1/symbolConfig`. positionRisk v3 has no leverage field. The system never inherits account defaults (F-011, F-964).
2. The liquidation check uses exchange leverage brackets and maintenance margin, never hard-coded values. The liquidation price must lie beyond the SL by a configured buffer (F-964).
3. The available-margin check uses `availableBalance`, the new order's initial margin plus fees, other resting entries and approved-but-unplaced plans (F-966).
4. Position mode is one-way single-asset only. Any other mode results in NO_TRADE (F-965, F-020).

**Audit refs**: F-011, F-964, F-966, F-965, F-020, F-019

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 22 to break down)

### Phase 23: Telegram Approval Hardening + Money Amounts

**Goal**: Only the authorized user in a private chat can approve. SKIP works. Decided messages cannot be tapped again. Every SIMULATE/APPROVE message shows the money at stake.

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

**Audit refs**: F-508, F-707, F-405, F-509, F-127, F-015, F-016

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 23 to break down)

### Phase 24: Live Runtime Composition + Demo Rehearsal

**Goal**: The live system runs end-to-end as named processes. It is proven on Binance Demo Trading before any real order.

**Depends on**: Phase 16, Phase 19, Phase 20, Phase 21, Phase 22, Phase 23

**Requirements**: APRV-01, EXEC-01, EXEC-02, EXEC-03, OPS-02

**Success Criteria**:
1. The composition root wires every link that has no production caller today (M1, M2, M5–M8) (F-201, F-956):
   - approval request sender;
   - Telegram bot runner (APPROVE → `execute_approved_plan`);
   - execution service;
   - reconcile, sweeper and health schedulers;
   - live risk-input producer: constraints, equity, daily loss, open algo count;
   - kill-gate event → `enable()`.
2. An end-to-end smoke test runs on Binance Demo Trading:
   - signal → approve → entry → SL/TP;
   - fill via the user-data stream;
   - reconcile clean;
   - SAFE_MODE drill;
   - restart and rehydrate.
   This executes the blocked 09-04 rehearsal with recorded demo order ids.
3. The approval → placement path is exercised with replayed callbacks and a restart mid-flow, and no duplicate orders result.

**Audit refs**: F-201, F-956, F-202, F-104, F-124

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 24 to break down)

### Phase 25: Go-Live Readiness Gate

**Goal**: Live trading can only be enabled affirmatively: a family has passed under protocol v1.1.0, the paper exit gate is met, all safety phases are verified, and operations are real. Otherwise it cannot be enabled.

**Depends on**: Phase 24

**Requirements**: GOV-01, OPS-01, OPS-02, PAPER-03

**Success Criteria**:
1. `enable()` requires a recorded passing candidate, a met paper exit gate and a minimum capital. WITHIN_BUDGET is refused. The skipped Phase-10 review items WR-01/06/10/12/13 are resolved (F-953, F-105, F-960).
2. Phases 06–24 each have a VERIFICATION.md written after their last review-fix wave. The ~30 "requires human verification" fixes are confirmed, and 05-VERIFICATION is reopened (F-807, F-808, F-109, F-956). One-way checkpoints carry recorded human decisions (F-124, F-809).
3. Backups are off-host and encrypted, run on a schedule and follow a retention policy. The pg_dump URL is fixed. A real PostgreSQL restore drill passes (F-108, F-910, F-121, F-704).
4. CI on a real remote runs pytest, ruff, mypy and the registry gate, and all are green (F-101, F-605). The Docker healthcheck uses the venv. The images are pinned. Postgres binds to localhost. Secrets are scrubbed from errors (F-705, F-709, F-708).

**Audit refs**: F-953, F-105, F-960, F-807, F-808, F-109, F-124, F-809, F-108, F-121, F-704, F-101, F-605, F-705, F-709, F-708

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 25 to break down)

### Phase 26: Configurable Quote Asset (USDC readiness)

**Goal**: The quote/margin asset becomes configuration instead of a constant, so a USDC pair can be evaluated deliberately. This was former Phase 17; its priority is lowered below all safety work.

The following are hard-coded today:
- `LIVE_5` in `src/data/backfill.py:549` and `src/backtest/report.py:34`;
- `QUOTE_ASSET = "USDT"` in `src/analytics/live_outcomes.py:65`.

Switching an instrument requires a DECISIONS entry, new data, a new versioned parameter set with current fees, and re-research. USDT evidence does not transfer.

**Depends on**: Phase 25

**Requirements**: DATA-01, DOMN-02, BKTS-02, JRN-01

**Audit refs**: F-208 (live-5 list duplicated in 4 places), F-031

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 26 to break down)

BLOCK 3>>>

---

## BLOCK 4: Progress section

**4a.** Replace the "Execution Order" sentence (the line starting `Phases execute in numeric order: 1 → 2 → …`) with:

<<<BLOCK 4a
Phases execute in numeric order: 1 → 2 → … → 10 → 11 → 12 → … → 26. (Phase 8 construction may overlap the Phase 7 paper soak; Phase 8 enablement gates on paper evidence. Phase 13 and Phase 17 depend only on Phase 11, so they may run in parallel with the evidence track 12→14→15→16. No live order before Phase 25 is complete.)
BLOCK 4a>>>

**4b.** Replace the seven progress-table rows for phases 11–17 with:

<<<BLOCK 4b
| 11. Decision Alignment (docs + params) | 0/TBD | Not started | - |
| 12. Fee + Cost Model Correctness | 0/TBD | Not started | - |
| 13. Research Data Foundation Fixes | 0/TBD | Not started | - |
| 14. Backtest Simulator Causality Rewrite | 0/TBD | Not started | - |
| 15. Strategy Geometry Correction | 0/TBD | Not started | - |
| 16. Paper Runtime Composition | 0/TBD | Not started | - |
| 17. Operational Persistence Layer | 0/TBD | Not started | - |
| 18. Binance User-Data Stream + Exchange Error Taxonomy | 0/TBD | Not started | - |
| 19. Execution Plan Binding + Pre-Placement Checks | 0/TBD | Not started | - |
| 20. Reconcile + SAFE_MODE Hardening + Alerts | 0/TBD | Not started | - |
| 21. Account Equity + Daily Loss from Binance | 0/TBD | Not started | - |
| 22. Leverage, Margin + Liquidation Guard | 0/TBD | Not started | - |
| 23. Telegram Approval Hardening + Money Amounts | 0/TBD | Not started | - |
| 24. Live Runtime Composition + Demo Rehearsal | 0/TBD | Not started | - |
| 25. Go-Live Readiness Gate | 0/TBD | Not started | - |
| 26. Configurable Quote Asset (USDC readiness) | 0/TBD | Not started | - |
BLOCK 4b>>>

---

## Phase directory mapping

All the old directories contain only `.gitkeep`. Use `git mv` for renames and `git add` for new directories that contain a `.gitkeep`.

| Old dir | New dir |
|---|---|
| 11-fee-units-and-real-commission | 12-fee-cost-model-correctness |
| 12-account-equity-from-binance | 21-account-equity-daily-loss |
| 13-leverage-margin-liquidation-guard | 22-leverage-margin-liquidation-guard |
| 14-available-margin-check | (remove — merged into 22) |
| 15-pre-placement-price-check | 19-execution-plan-binding-price-check |
| 16-notification-money-amounts | 23-telegram-approval-hardening-money |
| 17-configurable-quote-asset | 26-configurable-quote-asset |
| (new) | 11-decision-alignment |
| (new) | 13-research-data-foundation-fixes |
| (new) | 14-backtest-causality-rewrite |
| (new) | 15-strategy-geometry-correction |
| (new) | 16-paper-runtime-composition |
| (new) | 17-operational-persistence-layer |
| (new) | 18-user-data-stream-error-taxonomy |
| (new) | 20-reconcile-safe-mode-hardening |
| (new) | 24-live-runtime-composition-demo |
| (new) | 25-go-live-readiness-gate |
