# Requirements: Deterministic Binance Futures Research & Semi-Automated Execution System

**Defined:** 2026-09-19
**Core Value:** Every trading decision is deterministic, reproducible, and explainable from market data plus a versioned strategy spec — no AI/LLM in the decision path.

Auto-derived in `--auto` mode from the project brief + Core Docs v0.3 + `.planning/research/` (STACK/FEATURES/ARCHITECTURE/PITFALLS/SUMMARY). All Active requirements are hypotheses until shipped and validated. Strategy V1 family selection (D012) stays TBD — no winner declared without evidence.

## v1 Requirements

### Research Formalization

- [x] **RSCH-01**: Research protocol is frozen (dataset splits, cost model, execution assumptions, acceptance methodology) before any parameter work begins
- [x] **RSCH-02**: Three candidate families are specified independently (Trend Pullback, Breakout+Retest, Range Mean-Reversion) with deterministic alternatives per concept (informal → machine-detectable → alternatives → bias → parameters → backtest)
- [x] **RSCH-03**: Core Doc contradictions are resolved with decisions recorded in DECISIONS.md (SystemMode naming, order-lifecycle APPROVED, timezone canonicalization, §12 status names, duplicate section numbers)

### Data Foundation

- [x] **DATA-01**: User can bootstrap 1m/1H/4H candles per symbol with continuity/quality checks (duplicates, OHLC validity, regressions, gaps) and query effective per-symbol coverage
- [x] **DATA-02**: System collects OI snapshots continuously from Phase 0 plus funding history, so the 30-day API window never destroys research data
- [x] **DATA-03**: System records versioned symbol metadata (onboard time, tick/step, min/max qty, notional constraints, position modes) from live exchangeInfo instead of hard-coded values
- [x] **DATA-04**: System passes an automated backup + restore drill covering PostgreSQL state and the self-collected OI dataset

### Domain & Reproducibility

- [x] **DOMN-01**: System persists seven separate entities (Signal, TradePlan, Approval, Order, Fill, Position, JournalEvent) with GLOSSARY-canonical enums and no nullable-column state inference
- [x] **DOMN-02**: Every backtest/paper/alert/order plan is traceable to an immutable versioned parameter set (strategyVersion + parameterSetId + parameterSetHash + experiment linkage)
- [x] **DOMN-03**: Strategy correctness is enforced by golden fixtures (candles.csv + parameters.json + expected signals/plans) plus no-lookahead, prefix-invariance, candle-close-timing, and boundary suites (Phase 6 evidence is void per D052; re-verified by Phase 14 through tests/test_backtest_entry.py, tests/test_backtest_exits.py, tests/test_backtest_funding.py, tests/test_backtest_ledger.py, tests/test_backtest_expiry_clock.py, tests/test_backtest_goldens.py, tests/test_backtest_determinism.py and tests/test_backtest_chain.py)
- [x] **DOMN-04**: Signal, TradePlan, Order and Position state transitions are validated against the GLOSSARY state machines and illegal transitions are rejected

### Strategy & Planning

- [x] **STRAT-01**: Feature engine computes deterministic indicators/structure/zones from closed candles only, with warm-up gates (e.g. EMA200-4H invalid until history suffices)
- [x] **STRAT-02**: Strategy engine is a pure function (market snapshot + account state + strategy version + config → NO_TRADE or SETUP) emitting deterministic SignalIds
- [x] **STRAT-03**: Trade planner translates each valid setup into entry zone, SL, TP(s), invalidation, expiry, expected RR, and plan hash

### Risk

- [x] **RISK-01**: System sizes positions from equity × risk-rate ÷ SL-distance including modeled costs, floors quantity to stepSize, rejects below the utilization threshold or minimums, and uses identical logic in backtest/paper/live
- [x] **RISK-02**: System enforces portfolio limits (max open positions, aggregate risk, correlated-cluster cap, DAILY_STOP states) and fails closed on uncertain account/risk state
- [ ] **RISK-03**: A live protective stop is never loosened or removed while its position is open; any stop change is explicit, logged and permitted by the strategy and execution contract; automatic re-placement restores the original plan stop-loss, never a wider one
- [ ] **RISK-04**: The system never increases risk because of previous losses or an unmet target and never adds to a losing position (no averaging down)

### Backtest & Evidence

- [x] **BKTS-01**: Backtest simulator resolves intrabar SL/TP ordering with 1m data, models limit fills/partials/expiry/invalidation, and applies fees/funding/slippage before any selection decision (Phase 6 evidence is void per D052; re-verified by Phase 14 through tests/test_backtest_entry.py, tests/test_backtest_exits.py, tests/test_backtest_funding.py, tests/test_backtest_ledger.py, tests/test_backtest_expiry_clock.py, tests/test_backtest_goldens.py, tests/test_backtest_determinism.py and tests/test_backtest_chain.py)
- [x] **BKTS-02**: Every experiment is reproducible from dataset + strategy + parameter set + cost + execution versions and is compared against no-trade and simple-trend baselines (Phase 6 evidence is void per D052; re-verified by Phase 14 through tests/test_backtest_entry.py, tests/test_backtest_exits.py, tests/test_backtest_funding.py, tests/test_backtest_ledger.py, tests/test_backtest_expiry_clock.py, tests/test_backtest_goldens.py, tests/test_backtest_determinism.py and tests/test_backtest_chain.py)
- [x] **BKTS-03**: Reports show trade counts and slices (symbol/period/regime/version), R distribution, bootstrap intervals, and parameter-plateau analysis — never a single headline number *(Originally mapped to Phase 6; `src/backtest/report.py` prints "not computed (BKTS-03 pending)". Owner: the Phase 16 research runner (D059 item 5, Backlog 999.2).)*
- [x] **BKTS-04**: Every experiment record carries the fields the research protocol requires, including NO_TRADE counts with reasons, the intrabar tie-break, timeframe, full parameters and costs, and a verifiable code version

### Paper & Forward Validation

- [ ] **PAPER-01**: Realtime paper engine ingests WS market data with warm-up/reconnect/resync, evaluates closed candles only, and journals gaps without fabricating signals *(Originally mapped to Phase 7; Phase 16 closes it when Phase 16 criteria 1, 2 and 7 hold, D061 item J.)*
- [ ] **PAPER-02**: Paper loop records system vs user-executed vs opportunity (skipped/expired) attribution with signal/approve/order/fill timestamps *(Originally mapped to Phase 7; Phase 16 closes it when Phase 16 criteria 3 and 5 hold, D061 item J.)*
- [ ] **PAPER-03**: Forward evidence accumulates over wall-clock observation (3–6 months envelope) with no tuning on the paper stream *(Originally mapped to Phase 7. D061 item J: Phase 16 starts the stream with a trial soak and leaves this Pending; the long soak keeps accumulating through Phases 18 to 25 and Phase 26 verifies the observation window and the no-tuning rule and closes it. Closing it on a trial soak would be false against the text above. Test events (D063 item 3), planned restarts and gaps never count as covered time or as forward evidence.)*

### Approval

- [x] **APRV-01**: User receives Telegram alerts (SIMULATE/APPROVE/SKIP) carrying symbol, direction, setup, entry, SL, TP(s), RR, risk, expiry, invalidation, exposure, and reason codes
- [x] **APRV-02**: Approval is bound to SignalId + strategy version + plan hash + expiry + authorized chat + one-time token, idempotent across at-least-once callback replays, with no auto-approve on notification failure

### Execution & Safety

- [ ] **EXEC-01**: Execution manager places LIMIT-zone entries and Algo-Order protective exits (re-verified against current Binance docs), supports both position modes and partial-fill protective sizing *(Implemented and unit-tested, not Demo-proven: `09-DEMO-REHEARSAL-FINDINGS.md` keeps it Pending until real Demo evidence exists; the Demo run stopped at SL placement with -4509 and the execution model is open (D055). Evidence owners: Phase 24 and Phase 25. Phase 18 (2026-10-18): library-proven offline (only `NEW` confirms protection; single-attempt placement; a blocked protective order surfaces as an unprotected position); Demo-observed protective-stop facts from the probe; partial fill and triggered `*_MARKET` exit NOT observed; stays Pending for Demo-proven evidence (Phases 24 and 25); D055 OPEN.)*
- [ ] **EXEC-02**: Reconciliation loop compares local state against open normal orders, open algo orders, and positions, sweeps orphan protective orders, and forces SAFE_MODE on divergence *(Implemented and verified at library level with fakes only (08-VERIFICATION); the reconcile loop is not composed into a running process and no live read-only reconcile has run. Demo-proven evidence pending, owners Phase 24 and Phase 25. Phase 18 (2026-10-18): library-proven offline; Demo-observed -2013 (GET order and algo), -2011 (cancel order and algo), -4116 duplicate `clientAlgoId`, id reuse after CANCELED and FILLED; stays Pending for Demo-proven reconcile evidence (Phases 24 and 25).)*
- [x] **EXEC-03**: Deterministic client/algo order identifiers prevent duplicate entry orders across retries, restarts, and replayed events
- [x] **EXEC-04**: The exact exchange constraint snapshot used for sizing, including MARKET_LOT_SIZE and PERCENT_PRICE filters, working type, margin type, leverage and equity, is persisted per trade plan and revalidated when stale
- [ ] **EXEC-05**: The Binance user-data stream for order, algo-order, account and position events drives fills and state, with REST as fallback *(Library-proven offline (fakes, SDK-shaped fakes, synthetic and recorded frames, replay and reorder proof) and Demo-observed by the user-run smoke of 2026-10-16 (`REAL_SMOKE`, SDK `user_data` route delivered typed events, keepalive and forced drop recovered). Not mainnet. Not composed into a running process (Phases 24 and 25); stays Pending until then. Phase 18 verification: `18-VERIFICATION.md`.)*
- [ ] **EXEC-06**: Manual emergency controls exist: cancel pending strategy orders, disable new entries, close strategy positions on explicit action, re-place protection, and enter SAFE_MODE
- [ ] **EXEC-07**: Protective-order execution assumptions that change results (the TP1 split fraction, the TP2 rule and the time in force) are versioned registry parameters, not code constants

### Journal & Operations

- [x] **JRN-01**: Journal/analytics reports MFE/MAE, execution-quality latencies, approval-delay impact, and robustness slices without hiding the full report
- [ ] **OPS-01**: SAFE_MODE blocks new entries while monitoring continues, and the RUNBOOK (unprotected/orphan/duplicate/API-down/stale-feed/DB-failure/manual-close/restore) is rehearsed before live enablement *(SAFE_MODE gating and the 8-drill harness are verified with fakes (08-VERIFICATION); the real-stack RUNBOOK drill rehearsal is deferred. Demo-proven evidence pending, owners Phase 25 and Phase 26.)*
- [ ] **OPS-02**: Live credentials use no-withdrawal keys, IP allowlisting, off-source secret storage, and structured secret-free logging with health checks *(Health and secret-free posture verified; credential provisioning is not attested (09-VERIFICATION) and `09-DEMO-REHEARSAL-FINDINGS.md` keeps it Pending until real Demo evidence exists. Owners Phase 24, Phase 25 and Phase 26. Phase 18 (2026-10-18): library-proven offline (key loading, redaction, explicit environment, 27 ratified limits); attestation of no-withdrawal keys and IP allowlist stays a Phase 24 to 26 human item; stays Pending.)*
- [ ] **OPS-03**: The restart sequence loads config, validates time, reconciles Binance orders and positions, reconnects streams, verifies no duplicate action, and resumes only when state is consistent
- [ ] **OPS-04**: Health and diagnostic output includes the runtime Python version and the application git revision
- [ ] **OPS-05**: Operational alerts fire for an unprotected position, local versus exchange divergence, an unknown or foreign order, a duplicate execution attempt, stale data, a rejected protective action, an authentication failure, and daily-loss WARNING and DAILY_STOP
- [ ] **OPS-06**: Secrets stay outside source control, paper and test credentials are separate from live, and live secrets are held in a permission-restricted .env with provider disk encryption on the VPS (D042) *(Originally mapped to Phase 13.1, which closed with OPS-06 NEEDS HUMAN (13.1-VERIFICATION). Open owners: Phase 24 for WR-06, the per-service env split, and Phase 26 for the provider disk-encryption check on the real host. The traceability cell stays Phase 13.1 because `scripts/decision_alignment/bookkeeping.py` NEW_REQUIREMENTS pins it.)*
- [x] **GOV-01**: Kill-gate dashboard tracks the 3-families / 6-months budget and preserves NO_TRADE / INSUFFICIENT EDGE as a valid terminal outcome
- [ ] **GOV-02**: Live order enablement requires an affirmative set of prerequisites (a recorded passing candidate, a met paper exit gate, a passed demo campaign and a minimum capital), not merely the absence of a terminal kill-gate state

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

Evidence levels (a requirement can sit at any one; they do not imply each other):

- **Implemented**: code exists and unit tests pass.
- **Verified**: a verifier confirmed the requirement text at the level it claims, with offline evidence.
- **Demo-proven**: the behavior was observed against Binance Demo Trading with recorded evidence.
- **Live-ready**: Demo-proven and cleared by the Phase 26 go-live gate.
- The Status column says Complete only for Verified at the level the requirement text claims; a requirement that is implemented but lacks the Demo or live evidence its text asks for stays Pending.

| Requirement | Phase | Status |
|-------------|-------|--------|
| RSCH-01 | Phase 1 | Complete |
| RSCH-02 | Phase 1 | Complete |
| RSCH-03 | Phase 1 | Complete |
| DATA-01 | Phase 2 | Complete |
| DATA-02 | Phase 2 | Complete |
| DATA-03 | Phase 2 | Complete |
| DATA-04 | Phase 2 | Complete |
| DOMN-01 | Phase 3 | Complete |
| DOMN-02 | Phase 3 | Complete |
| DOMN-03 | Phase 3 | Complete |
| STRAT-01 | Phase 4 | Complete |
| STRAT-02 | Phase 4 | Complete |
| STRAT-03 | Phase 4 | Complete |
| RISK-01 | Phase 5 | Complete |
| RISK-02 | Phase 5 | Complete |
| BKTS-01 | Phase 6 | Complete |
| BKTS-02 | Phase 6 | Complete |
| BKTS-03 | Phase 16 | Complete |
| PAPER-01 | Phase 16 | Pending |
| PAPER-02 | Phase 16 | Pending |
| PAPER-03 | Phase 26 | Pending |
| APRV-01 | Phase 8 | Complete |
| APRV-02 | Phase 8 | Complete |
| EXEC-01 | Phase 9 | Pending |
| EXEC-02 | Phase 8 | Pending |
| EXEC-03 | Phase 8 | Complete |
| JRN-01 | Phase 10 | Complete |
| OPS-01 | Phase 8 | Pending |
| OPS-02 | Phase 9 | Pending |
| GOV-01 | Phase 10 | Complete |
| RISK-03 | Phase 20 | Pending |
| RISK-04 | Phase 19 | Pending |
| EXEC-04 | Phase 17 | Complete |
| EXEC-05 | Phase 18 | Pending |
| EXEC-06 | Phase 20 | Pending |
| EXEC-07 | Phase 19 | Pending |
| DOMN-04 | Phase 17 | Complete |
| BKTS-04 | Phase 14 | Complete |
| OPS-03 | Phase 24 | Pending |
| OPS-04 | Phase 24 | Pending |
| OPS-05 | Phase 20 | Pending |
| OPS-06 | Phase 13.1 | Pending |
| GOV-02 | Phase 26 | Pending |

> Traceability note (Phase 14, D052): the Phase 6 evidence behind the BKTS-01, BKTS-02 and DOMN-03 rows is void. Phase 14 re-verifies those requirements against the v2 engine (tests/test_backtest_entry.py, tests/test_backtest_exits.py, tests/test_backtest_funding.py, tests/test_backtest_ledger.py, tests/test_backtest_expiry_clock.py, tests/test_backtest_goldens.py, tests/test_backtest_determinism.py and tests/test_backtest_chain.py). The status cells above are unchanged; the verifier owns them.

> Traceability note (2026-10-07 evidence-level review): EXEC-01, EXEC-02, OPS-01 and OPS-02 are Pending because Demo-proven evidence is missing (sources: 08-VERIFICATION, 09-VERIFICATION, 09-DEMO-REHEARSAL-FINDINGS); their Phase column keeps the implementing phase, and the Phase 24, 25 and 26 Requirements lines in ROADMAP.md own the missing evidence. OPS-06 is open in Phases 24 (WR-06) and 26 (disk encryption) as ROADMAP Inherited items T-02, G3-029 and G3-032 record, but its cell stays Phase 13.1 until the pinned mapping in `scripts/decision_alignment/bookkeeping.py` and `tests/test_decision_alignment_bookkeeping.py` is changed.

**Coverage:**

- v1 requirements: 43 total
- Mapped to phases: 43
- Unmapped: 0 ✓

---
*Requirements defined: 2026-09-19 after initialization*
*Last updated: 2026-09-30 after Phase 11 (F-116 additions: 13 requirement IDs registered, mapped to phases 13-26)*
*Evidence-level review 2026-10-07: EXEC-01, EXEC-02, OPS-01, OPS-02 set to Pending; BKTS-03 re-mapped to Phase 16; OPS-06 owners noted*
*Phase 18 closing 2026-10-18: EXEC-01, EXEC-02, EXEC-05 and OPS-02 stay Pending (library-proven offline, Demo-observed, not mainnet, not composed into a running process); no requirement status changed*
*D063 and D065 notes 2026-10-07: PAPER-03 wording clarified (test events, planned restarts and gaps are never evidence); no requirement status changed*
