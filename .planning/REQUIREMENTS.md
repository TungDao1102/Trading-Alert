# Requirements: Deterministic Binance Futures Research & Semi-Automated Execution System

**Defined:** 2026-09-19
**Core Value:** Every trading decision is deterministic, reproducible, and explainable from market data plus a versioned strategy spec — no AI/LLM in the decision path.

Auto-derived in `--auto` mode from the project brief + Core Docs v0.3 + `.planning/research/` (STACK/FEATURES/ARCHITECTURE/PITFALLS/SUMMARY). All Active requirements are hypotheses until shipped and validated. Strategy V1 family selection (D012) stays TBD — no winner declared without evidence.

## v1 Requirements

### Research Formalization

- [ ] **RSCH-01**: Research protocol is frozen (dataset splits, cost model, execution assumptions, acceptance methodology) before any parameter work begins
- [ ] **RSCH-02**: Three candidate families are specified independently (Trend Pullback, Breakout+Retest, Range Mean-Reversion) with deterministic alternatives per concept (informal → machine-detectable → alternatives → bias → parameters → backtest)
- [ ] **RSCH-03**: Core Doc contradictions are resolved with decisions recorded in DECISIONS.md (SystemMode naming, order-lifecycle APPROVED, timezone canonicalization, §12 status names, duplicate section numbers)

### Data Foundation

- [ ] **DATA-01**: User can bootstrap 1m/1H/4H candles per symbol with continuity/quality checks (duplicates, OHLC validity, regressions, gaps) and query effective per-symbol coverage
- [ ] **DATA-02**: System collects OI snapshots continuously from Phase 0 plus funding history, so the 30-day API window never destroys research data
- [ ] **DATA-03**: System records versioned symbol metadata (onboard time, tick/step, min/max qty, notional constraints, position modes) from live exchangeInfo instead of hard-coded values
- [ ] **DATA-04**: System passes an automated backup + restore drill covering PostgreSQL state and the self-collected OI dataset

### Domain & Reproducibility

- [ ] **DOMN-01**: System persists seven separate entities (Signal, TradePlan, Approval, Order, Fill, Position, JournalEvent) with GLOSSARY-canonical enums and no nullable-column state inference
- [ ] **DOMN-02**: Every backtest/paper/alert/order plan is traceable to an immutable versioned parameter set (strategyVersion + parameterSetId + parameterSetHash + experiment linkage)
- [ ] **DOMN-03**: Strategy correctness is enforced by golden fixtures (candles.csv + parameters.json + expected signals/plans) plus no-lookahead, prefix-invariance, candle-close-timing, and boundary suites

### Strategy & Planning

- [ ] **STRAT-01**: Feature engine computes deterministic indicators/structure/zones from closed candles only, with warm-up gates (e.g. EMA200-4H invalid until history suffices)
- [ ] **STRAT-02**: Strategy engine is a pure function (market snapshot + account state + strategy version + config → NO_TRADE or SETUP) emitting deterministic SignalIds
- [ ] **STRAT-03**: Trade planner translates each valid setup into entry zone, SL, TP(s), invalidation, expiry, expected RR, and plan hash

### Risk

- [ ] **RISK-01**: System sizes positions from equity × risk-rate ÷ SL-distance including modeled costs, floors quantity to stepSize, rejects below the utilization threshold or minimums, and uses identical logic in backtest/paper/live
- [ ] **RISK-02**: System enforces portfolio limits (max open positions, aggregate risk, correlated-cluster cap, DAILY_STOP states) and fails closed on uncertain account/risk state

### Backtest & Evidence

- [ ] **BKTS-01**: Backtest simulator resolves intrabar SL/TP ordering with 1m data, models limit fills/partials/expiry/invalidation, and applies fees/funding/slippage before any selection decision
- [x] **BKTS-02**: Every experiment is reproducible from dataset + strategy + parameter set + cost + execution versions and is compared against no-trade and simple-trend baselines
- [ ] **BKTS-03**: Reports show trade counts and slices (symbol/period/regime/version), R distribution, bootstrap intervals, and parameter-plateau analysis — never a single headline number

### Paper & Forward Validation

- [ ] **PAPER-01**: Realtime paper engine ingests WS market data with warm-up/reconnect/resync, evaluates closed candles only, and journals gaps without fabricating signals
- [ ] **PAPER-02**: Paper loop records system vs user-executed vs opportunity (skipped/expired) attribution with signal/approve/order/fill timestamps
- [ ] **PAPER-03**: Forward evidence accumulates over wall-clock observation (3–6 months envelope) with no tuning on the paper stream

### Approval

- [x] **APRV-01**: User receives Telegram alerts (SIMULATE/APPROVE/SKIP) carrying symbol, direction, setup, entry, SL, TP(s), RR, risk, expiry, invalidation, exposure, and reason codes
- [x] **APRV-02**: Approval is bound to SignalId + strategy version + plan hash + expiry + authorized chat + one-time token, idempotent across at-least-once callback replays, with no auto-approve on notification failure

### Execution & Safety

- [ ] **EXEC-01**: Execution manager places LIMIT-zone entries and Algo-Order protective exits (re-verified against current Binance docs), supports both position modes and partial-fill protective sizing
- [ ] **EXEC-02**: Reconciliation loop compares local state against open normal orders, open algo orders, and positions, sweeps orphan protective orders, and forces SAFE_MODE on divergence
- [ ] **EXEC-03**: Deterministic client/algo order identifiers prevent duplicate entry orders across retries, restarts, and replayed events

### Journal & Operations

- [ ] **JRN-01**: Journal/analytics reports MFE/MAE, execution-quality latencies, approval-delay impact, and robustness slices without hiding the full report
- [ ] **OPS-01**: SAFE_MODE blocks new entries while monitoring continues, and the RUNBOOK (unprotected/orphan/duplicate/API-down/stale-feed/DB-failure/manual-close/restore) is rehearsed before live enablement
- [ ] **OPS-02**: Live credentials use no-withdrawal keys, IP allowlisting, off-source secret storage, and structured secret-free logging with health checks
- [ ] **GOV-01**: Kill-gate dashboard tracks the 3-families / 6-months budget and preserves NO_TRADE / INSUFFICIENT EDGE as a valid terminal outcome

## v2 Requirements

### Refinement & Features

- **REFN-01**: 15M entry-refinement trigger gated on measured approval-latency evidence
- **REFN-02**: OI snapshot history evaluated as an incremental strategy feature (not core gate)
- **REFN-03**: Funding-rate regime evaluated as an incremental strategy feature
- **REFN-04**: Portfolio correlation model replacing the conservative V1 cluster rule
- **REFN-05**: Additional strategy families beyond the initial three, each independently specified

### Integrations

- **INTG-01**: TradingView Pine cross-check harness comparing signal timestamps/levels against the Python engine
- **INTG-02**: TradingView webhook adapter (authenticated FastAPI endpoint, normalized domain messages) for operational alert experiments

## Out of Scope

| Feature | Reason |
|---------|--------|
| Fully autonomous live trading | Requires separate evidence/gates; user wants explicit approval control (D004) |
| AI/LLM price prediction or LLM-generated Entry/SL/TP/size | Violates determinism and D001; unbacktestable and unauditable |
| Forced daily profit target | Forces overtrading; zero-trade days are valid by product principle |
| HFT/scalping, order-book ML, reinforcement learning | Incompatible with part-time availability and research budget |
| 5M as required V1 timing dependency | Short-TTL signals mismatch full-time work (D006) |
| Kafka/RabbitMQ/K8s/large microservice topology | No measured bottleneck; keep contracts under project control |
| Rust full rewrite / NautilusTrader as mandatory foundation | Premature until a profiled bottleneck or measured requirement exists |
| $200/month income promise on $500–1,000 capital | Arithmetic envelope (≈9.5% risk/trade) contradicts capital preservation |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| RSCH-01 | Phase 1 | Pending |
| RSCH-02 | Phase 1 | Pending |
| RSCH-03 | Phase 1 | Pending |
| DATA-01 | Phase 2 | Pending |
| DATA-02 | Phase 2 | Pending |
| DATA-03 | Phase 2 | Pending |
| DATA-04 | Phase 2 | Pending |
| DOMN-01 | Phase 3 | Pending |
| DOMN-02 | Phase 3 | Pending |
| DOMN-03 | Phase 3 | Pending |
| STRAT-01 | Phase 4 | Pending |
| STRAT-02 | Phase 4 | Pending |
| STRAT-03 | Phase 4 | Pending |
| RISK-01 | Phase 5 | Pending |
| RISK-02 | Phase 5 | Pending |
| BKTS-01 | Phase 6 | Pending |
| BKTS-02 | Phase 6 | Complete |
| BKTS-03 | Phase 6 | Pending |
| PAPER-01 | Phase 7 | Pending |
| PAPER-02 | Phase 7 | Pending |
| PAPER-03 | Phase 7 | Pending |
| APRV-01 | Phase 8 | Complete |
| APRV-02 | Phase 8 | Complete |
| EXEC-01 | Phase 9 | Pending |
| EXEC-02 | Phase 8 | Pending |
| EXEC-03 | Phase 8 | Pending |
| JRN-01 | Phase 10 | Pending |
| OPS-01 | Phase 8 | Pending |
| OPS-02 | Phase 9 | Pending |
| GOV-01 | Phase 10 | Pending |

**Coverage:**

- v1 requirements: 30 total
- Mapped to phases: 30
- Unmapped: 0 ✓

---
*Requirements defined: 2026-09-19 after initialization*
*Last updated: 2026-09-19 after initial definition*
