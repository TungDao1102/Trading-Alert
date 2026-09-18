# Feature Research

**Domain:** Deterministic Binance Futures research + semi-automated execution (4H/1H swing, human-approved live only in V1)
**Researched:** 2026-09-19
**Confidence:** HIGH (derived from canonical Core Docs v0.3: 00_PRODUCT_SCOPE, DATA_MODEL, SIGNAL_AND_ALERTS, RISK_MANAGEMENT, EXECUTION_SPEC, BACKTEST_SPEC, METRICS, BINANCE/TELEGRAM/TRADINGVIEW, RUNBOOK, PROJECT.md)

## Feature Landscape

### Table Stakes (Users Expect These)

Capabilities the product is incomplete without. Missing any one breaks the canonical pipeline (Market Data → Features → Strategy → Plan → Risk → Approval → Execution → Journal → Research).

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Market-data ingestion: REST bootstrap + WS realtime (1m/1H/4H klines) | Without complete candles there are no signals; Binance docs mandate REST for history/reconcile + WS for realtime (24h conn validity, ping/pong) | MEDIUM | Adapter over official Binance Python connector (3.10+); REST bootstrap → WS subscribe → periodic REST reconcile; store immutable `market_candles` keyed (symbol, timeframe, open_time_utc), 1m partitioned by month |
| Reconnect / resync / warm-up / continuity checks | WS drops, VPS restarts, stale feeds produce phantom or missed signals; RUNBOOK mandates NO_NEW_SIGNALS on stale feed | MEDIUM | Freshness threshold (`now - last_expected_closed_candle`), gap-fill via REST, warm-up bars before strategy eval, closed-candle-only gate; fail-closed |
| OI + funding collectors (Phase-0 urgency) | Binance OI history window is ~30 days — irrecoverable if not self-collected from day one (D009); funding needed for cost model | MEDIUM | Daily/interval snapshot jobs for OI + funding rate + symbol metadata; append-only store; backup/restore smoke test. Highest schedule urgency, medium build complexity |
| Symbol metadata / exchangeInfo loader (dynamic constraints) | stepSize/tickSize/min-notional change; hard-coding breaks sizing and causes order rejects | LOW | Poll `exchangeInfo`, persist versioned `symbol_metadata` with `metadata_observed_at_utc`; sizing + validation read from snapshot, never literals |
| Feature engine (ATR / EMA / structure / zones) | Strategy families (Trend Pullback, Breakout+Retest, Range MR) all consume the same deterministic derived inputs; `feature_snapshots` with `feature_set_hash` enables reconstruction | MEDIUM | Pure functions on closed candles; Decimal-safe where exchange-sensitive; snapshot persisted per evaluated candle (id, strategy_version, feature_set_hash, features_json) |
| Deterministic strategy engine (closed-candle, no-repaint, prefix-invariant) | Core value prop: same snapshot + version + config = byte-identical decision; enables backtest≡paper≡live equivalence | HIGH | Rules frozen per StrategyVersion + parameter_set_hash; no future-candle leakage; deterministic SignalId `hash(version, symbol, TF, candle_close, setup)`; dedupe on restart |
| Trade planner (entry zone/SL/TP/invalidation/expiry/RR) | A signal without executable numbers cannot be approved or sized; scope §4 requires full plan fields | MEDIUM | Emits `trade_plans` (entry_min/max, SL, TP JSON, invalidation JSON, expiry_utc, expected RR, risk_budget, quantities pre/post rounding, plan_hash); one active plan per signal in V1; stale plans unapprovable |
| Risk engine (0.5% baseline, quantization floor, portfolio/correlation caps, daily-stop) | Capital preservation for $500–1000 account; $4 nominal risk/trade at $800 — rounding errors dominate without floor policy | MEDIUM | `allowed_risk = equity × risk_rate`; floor(raw/step)×step, never round up; 60% utilization floor else QUANTIZATION_REJECT; max 2 open / 1.0% aggregate (research placeholders); conservative correlated-cluster cap; NORMAL/WARNING/DAILY_STOP states; identical logic in all modes |
| Telegram approval channel (SIMULATE / APPROVE / SKIP + later CANCEL/CLOSE/SAFE_MODE) | Full-time worker can only review on mobile; human approval is the V1 live gate (D004) | MEDIUM | Rich alert card (symbol, direction, setup, entry zone, SL/TP, RR, risk%, expiry, invalidation, exposure, reason codes) with inline buttons; human-execution latency metrics (delivered/seen/approved/submitted) |
| Idempotent expiring approval tokens + at-least-once replay | Telegram redelivers callbacks; without idempotency one tap = duplicate orders; stale approvals = trading dead plans | MEDIUM | Approval bound to (SignalId, version, plan_hash, expiry, actor/chat); one-time token hash; replay → return current state, never new intent; re-validate plan + risk at execution time |
| Execution manager: LIMIT-zone entry + Algo-Order SL/TP | Binance migrated STOP_MARKET/TP_MARKET to Algo Order service (late 2025); legacy endpoint assumptions fail live | HIGH | Entry LIMIT (or limit-zone model) with pending-order expiry (time/invalidation/risk-change/stale/manual); SL/TP via current Algo endpoints; verify `closePosition`/`reduceOnly`/position-side semantics per mode at build time |
| Partial-fill handling | Swing LIMIT entries partially fill; protective exits sized on imagined quantity = unprotected remainder or over-hedged exits | MEDIUM | Track NEW→PARTIALLY_FILLED→FILLED/CANCELED/EXPIRED; size SL/TP against actual filled qty; cancel remainder path; out-of-order/replayed fill reconciliation |
| Reconciliation loop + orphan sweeper | Local state drifts from exchange (missed WS events, ambiguous timeouts); orphan stops can fire on zero position | HIGH | Startup + periodic 4-way compare (local vs normal open vs algo open vs positions); divergence → RECONCILIATION_REQUIRED; orphan protectives canceled after authoritative position=zero verification; never trust local order IDs |
| SAFE_MODE + manual emergency controls | Preserving capital beats resuming fast; every incident class in RUNBOOK funnels here | LOW | One-switch block on new live orders while monitoring/reconciliation continues; cancel-pending, close-per-explicit-action; rehearsed before live |
| User-data stream monitor (orders/positions/account) | REST polling misses fills under volatility; Binance recommends user-data WS as authoritative event path | MEDIUM | ORDER_TRADE_UPDATE handling (NEW/PARTIALLY_FILLED/FILLED/CANCELED/EXPIRED) + ALGO_UPDATE family; track normal and algo orders separately |
| Journal + analytics (system vs user vs opportunity, MFE/MAE) | Without three-way attribution you cannot tell strategy edge from approval-timing luck or availability bias | MEDIUM | Append-only `journal_events`; metric fields per METRICS.md (R, expectancy net of costs, profit factor, drawdown, execution latencies, fill%, expiry-without-fill); MFE/MAE per trade for SL/TP/entry diagnosis; slices by symbol/quarter/session/regime/version |
| Backtest engine (live-parity: no-lookahead, 1m intrabar, costs, quantization) | A backtest that disagrees with live semantics is marketing, not evidence; acceptance gates require parity | HIGH | Closed-candle rule; 1m intrabar resolution of SL/TP ambiguity (conservative fallback + disclosure when absent); fees/funding/slippage/spread config; LIMIT touch-vs-fill + expiry model; same quantization; experiment_runs record (strategy version, params hash, data/code/cost hashes, universe) |
| Validation gates (splits, walk-forward, baselines, uncertainty) | Single-backtest wins + point-estimate expectancy are how small accounts die confidently | MEDIUM | Dev→validation→holdout (holdout never tunes params); walk-forward for parameterized rules; baselines (no-trade, trend-filter); bootstrap/block-bootstrap expectancy intervals, Monte Carlo drawdown, stability across time/symbols; research universe (10–15) reported separately from live-5 slice |
| Paper-trading + forward-test engine | Backtest cannot prove operational reliability (reconnects, approval latency, expiry-without-fill); Phase 2 needs months of forward evidence | HIGH | Realtime WS path with warm-up/reconnect, planner+risk+journal+Telegram SIMULATE/APPROVE/SKIP; forward results feed kill-gate decision; 3–6 mo observation per plan |
| Backup / restore + OI dataset protection | OI self-collected data is irreplaceable; DB loss without tested restore = research restart | LOW | Automated PG logical backup + encrypted off-host copy + retention; restore drill required before live; backup invalid until restore test passes |
| TradingView cross-check adapter (Pine mirror + optional webhook) | Independent implementation catches look-ahead/repaint bugs the Python engine rationalizes to itself | LOW | Same concept in Pine + Python, compare signal timestamps/levels; webhook (if enabled) via authenticated FastAPI adapter normalizing to project message; TV never canonical for execution; explicit version alignment (TV alert copies don't follow chart edits) |

### Differentiators (Competitive Advantage)

Not expected, but each directly serves the core value (deterministic, explainable, part-time-compatible) and is cheap relative to its evidence value.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Prefix-invariant + byte-equivalent reproducibility harness | Turns "deterministic" from slogan into CI-enforced property; golden fixtures catch repaint/leakage regressions | MEDIUM | Fixture candles → assert identical Signal/Plan bytes across runs and prefix truncations; part of TESTING_STRATEGY; gates every strategy version bump |
| Three-way performance attribution (system / user-executed / opportunity) | Answers "is the edge real but my schedule eats it?" — selection-bias visibility most retail bots never provide | LOW | Builds on journal joins (Signal→Plan→sim outcome vs →Approval→Fill vs skipped→hypothetical); opportunity report is the differentiator |
| Uncertainty-first reporting (bootstrap CIs, Monte Carlo drawdown) | Prevents $500-account ruin from +0.15R point estimates with ±0.11R error bars; honest evidence for NO_TRADE courage | MEDIUM | SE ≈ σ/√n diagnostics, block bootstrap for clustered trades, parameter-region stability; single-expectancy numbers banned without n + interval |
| Approval-latency analytics for part-time fit | Quantifies whether 4H/1H TTLs actually fit a worker who can't answer in minutes; drives expiry design | LOW | Signal→seen→approve→order latencies + expiry-without-fill rate per symbol/session; feeds D006 (5M rejected) rationale |
| Deterministic id + content-hash lineage (Signal→Plan→Approval→Order→Fill) | Full audit trail: every fill explainable back to candle + strategy version + params; restart-safe dedupe | LOW | plan_hash, parameter_set_hash, feature_set_hash, token hash chain; replay-safe; enables post-mortem without guessing |
| Kill-gate dashboard (3 families / 6 months → NO_TRADE valid) | Institutionalizes stopping; most projects drift into endless complexity instead of accepting negative results | LOW | Tracks families tested, months elapsed, gate status (D013); NO_TRADE surfaced as success, not failure |
| Live-vs-research universe split reporting | Lets research use 10–15 symbols for power while keeping the live-5 claim honest | LOW | Every report shows both slices; acceptance cannot rest on broad universe rescuing weak live universe |
| Cost-aware sizing preview in the Telegram card | Shows realized-risk-after-rounding before approval so dust-quantity plans die at review, not at the exchange | LOW | Card includes raw vs rounded qty + realized risk% + QUANTIZATION_REJECT reason when applicable |
| RUNBOOK-rehearsed SAFE_MODE drills | Operational reliability as a feature: rehearsed incident paths before first live order | LOW | Drill log (stale feed, orphan, duplicate approval, DB failure); required checklist item in live rollout phase |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Fully autonomous live trading (LIVE_AUTONOMOUS) in V1 | "Don't bother me, just trade" | No evidence base yet; removes the only safety gate (human) before strategy proven; contradicts D004 + fail-closed | V1 LIVE_APPROVAL only; autonomous stays disabled-by-default future mode with separate evidence/gates |
| LLM/AI price prediction or LLM-generated entry/SL/TP/size | Feels like an edge multiplier | Non-deterministic, unreproducible, stale-context; violates D001 core value; untestable in backtest≡live parity | LLM limited to code/docs/tests/explanations; all trading numbers from versioned deterministic engine |
| Forced daily-profit target / $X-per-day optimization | $500–1000 "needs income" pressure | Forces overtrading on zero-setup days; revenge sizing; arithmetic shows $200/mo needs ~9.5% risk/trade at $800 — ruinous | Daily PnL as output metric only; optimize expectancy net of costs + drawdown + reliability; zero-trade days valid (D010) |
| HFT / scalping engine (5M core, sub-minute TTL) | More trades feel like more money | Incompatible with full-time job latency (can't answer in minutes), fee-dominated at small size, needs infra never budgeted | 4H regime + 1H setup; 15M entry-refinement optional; 1M execution-simulation only; 5M explicitly non-dependency (D005/D006) |
| ML on order book / RL policy trading | Sounds sophisticated | Data/cost/latency demands exceed research budget; opaque policies break explainability + acceptance gates | Deterministic three-family hypotheses (Trend Pullback, Breakout+Retest, Range MR) with versioned specs |
| News-sentiment discretionary override | "Trade the narrative" | Unquantifiable, unreproducible, unbacktestable; leaks subjectivity into deterministic path | News excluded from decision core; journal `SessionTag`/notes only for post-hoc regime analysis |
| Martingale / averaging-down / revenge sizing | Recover losses faster | Exponential ruin on $500–1000 account; violates fixed-fractional risk + no-compensation rule (RISK §7) | Fixed 0.5% baseline, stop integrity (never silently widen), DAILY_STOP blocks new entries |
| Rounding-up to dodge min-notional | "Don't miss the trade" | Silently exceeds risk budget; small-account death by a thousand over-risks | QUANTIZATION_REJECT + NO_TRADE preferred; log raw/rounded/realized-risk triple |
| Auto-approve on Telegram outage | "Don't miss signals when offline" | Trading without the human gate during degraded observability; exactly when fail-closed matters most | Journal signal, block order, never infer approval; alert on recovery |
| Kitchen-sink order-type support | "Support everything Binance has" | Surface area for Algo-migration bugs (STOP_MARKET legacy assumptions), position-mode errors, untested paths | Implement only frozen-strategy order types; verify Algo endpoints + mode semantics at build |
| Kafka / K8s / microservice topology / Rust rewrite / mandatory NautilusTrader | Resume-driven scaling | No measured bottleneck; low-frequency research workload; cedes strategy-contract control; multiplies ops burden for one part-timer | Modular Python 3.13 monolith (asyncio, adapters), PG + Parquet/DuckDB, Docker; adopt infra only on measured need |
| 5M timeframe as V1 timing dependency | Finer entries feel precise | Short-TTL signals expire before worker can approve; approval-latency analytics will condemn it | Keep 5M out of V1 critical path; discretionary aid at most |
| Single-symbol/quarter-tuned "winning" parameter point | Ships faster | Overfit point estimate collapses out-of-sample; fails gates 4/5/9 | Region-stability + walk-forward + multi-symbol/quarter reporting required |

## Feature Dependencies

```
Phase-0 Data Foundation
    ├──provides──> market_candles (REST+WS, reconnect/warm-up/continuity)
    ├──provides──> OI/funding snapshots (30-day urgency)
    └──provides──> symbol_metadata / exchangeInfo
                        │
Feature Engine ──requires──> market_candles + warm-up
    └──provides──> feature_snapshots
                        │
Strategy Engine ──requires──> feature_snapshots + StrategyVersion freeze
    └──provides──> signals (deterministic SignalId)
                        │
Trade Planner ──requires──> signals + symbol_metadata
    └──provides──> trade_plans (plan_hash, quantities)
                        │
Risk Engine ──requires──> trade_plans + account/positions + portfolio state
    └──provides──> approved-risk plans (or QUANTIZATION_REJECT / DAILY_STOP block)
                        │
Telegram Approval ──requires──> risk-checked plans + token/expiry infra
    └──provides──> approvals (idempotent, expiring)
                        │
Execution Manager ──requires──> approvals + user-data stream + Algo-order API
    ├──provides──> orders/fills/positions
    └──requires──> Reconciliation + orphan sweeper + SAFE_MODE (fail-closed)
                        │
Journal/Analytics ──requires──> ALL upstream entities (Signal→Plan→Approval→Order→Fill→Position)
    ├──provides──> system vs user vs opportunity reports + MFE/MAE + uncertainty
    └──feeds-back──> Backtest/Paper/Forward gates ──requires──> experiment_runs + cost model

TradingView cross-check ──enhances──> Strategy Engine (independent mirror, never canonical)
Approval-latency analytics ──enhances──> Telegram Approval + expiry design
Kill-gate dashboard ──enhances──> Validation gates (stop rule visibility)

LIVE_AUTONOMOUS ──conflicts──> Telegram Approval gate (human removed)
LLM decisions ──conflicts──> Deterministic Strategy Engine (reproducibility)
Daily-profit forcing ──conflicts──> Risk Engine + NO_TRADE validity
HFT/scalping ──conflicts──> Approval-latency reality + fee model
```

### Dependency Notes

- **Trade Planner requires symbol_metadata:** entry zones and quantities are meaningless without current tick/step/notional; stale-constraint plans must be revalidated.
- **Risk Engine requires portfolio state:** per-trade 0.5% is insufficient; aggregate 1.0%, cluster caps, and DAILY_STOP need live positions + journal.
- **Execution Manager requires reconciliation + SAFE_MODE:** placing Algo SL/TP without the 4-way compare and orphan sweeper risks unprotected positions and ghost stops.
- **Journal requires all upstream entities:** three-way attribution joins break if any of Signal/Plan/Approval/Order/Fill/Position is collapsed or missing (DATA_MODEL §5–6).
- **Backtest/paper gates require experiment_runs + cost model:** without hashed params/data/code/costs, results are anecdotes, not evidence.
- **Telegram Approval requires token/expiry infra first:** rich cards without idempotent expiring tokens ship duplicate-order risk.
- **OI collector has schedule dependency on nothing but calendar time:** it can (and must) start before strategy code exists — every delayed week permanently loses history outside the 30-day window.
- **Conflicts are V1-exclusionary:** autonomous/LLM/daily-target/HFT conflict with core guarantees and must not share a phase with live approval work.

## MVP Definition

### Launch With (v1)

Minimum to validate "deterministic setup → human-approved trade" on the live-5 universe. (Maps to Phase 0 → backtest → paper → first cautious live order.)

- [ ] Market-data ingestion + reconnect/warm-up/continuity — no candles, no product
- [ ] OI/funding collectors + backup/restore drill — irrecoverable data + survival prerequisite
- [ ] Feature engine + deterministic strategy engine (one family first, versioned) — the testable hypothesis
- [ ] Trade planner + risk engine (0.5%, quantization floor, portfolio caps, daily-stop) — executable + survivable plans
- [ ] Telegram SIMULATE/APPROVE/SKIP with idempotent expiring tokens — the part-time worker's control surface
- [ ] Execution manager (LIMIT-zone entry, Algo SL/TP, partial fills, reconciliation, orphan sweeper, SAFE_MODE) — live safety minimum
- [ ] Journal (three-way attribution, MFE/MAE) + backtest/paper parity engine with gates — evidence to earn live approval
- [ ] RUNBOOK rehearsal log — operate before you trade

### Add After Validation (v1.x)

- [ ] 15M entry-refinement overlay — trigger: approval-latency data shows entries systematically slip
- [ ] Extended Telegram actions (CANCEL ENTRY / CLOSE POSITION / SAFE MODE buttons) — trigger: manual ops during paper prove the need
- [ ] TradingView webhook adapter (operational use) — trigger: Pine/Python cross-check stable and version-alignment procedure proven
- [ ] Research-universe expansion reporting (10–15 symbols) — trigger: live-5 sample too thin for uncertainty targets
- [ ] Parameter-region stability + walk-forward automation — trigger: second strategy family enters validation

### Future Consideration (v2+)

- [ ] LIVE_AUTONOMOUS behind separate evidence/gates — why defer: explicitly out of scope until human-approved track record exists
- [ ] Multi-position / hedge-mode strategies — why defer: V1 assumes one-plan-per-signal and verified single mode
- [ ] Advanced correlation model replacing conservative cluster rule — why defer: placeholder cap is safer until portfolio data exists
- [ ] Automated retraining / adaptive parameters — why defer: conflicts with determinism guarantees; needs versioned-spec framework first

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| OI/funding collectors + backup drill | HIGH (irrecoverable) | MEDIUM | P1 |
| Market-data ingestion + reconnect/warm-up | HIGH | MEDIUM | P1 |
| Deterministic strategy engine | HIGH | HIGH | P1 |
| Trade planner | HIGH | MEDIUM | P1 |
| Risk engine + quantization floor | HIGH | MEDIUM | P1 |
| Telegram approval + idempotent tokens | HIGH | MEDIUM | P1 |
| Execution mgr + Algo SL/TP + reconcile + SAFE_MODE | HIGH | HIGH | P1 |
| Journal three-way + MFE/MAE | HIGH | MEDIUM | P1 |
| Backtest parity engine + gates | HIGH | HIGH | P1 |
| Paper/forward engine | HIGH | HIGH | P1 |
| Symbol metadata loader | HIGH | LOW | P1 |
| Feature engine | HIGH | MEDIUM | P1 |
| Prefix-invariant reproducibility harness | MEDIUM | MEDIUM | P2 |
| Uncertainty reporting (bootstrap/MC) | HIGH | MEDIUM | P1 |
| Approval-latency analytics | MEDIUM | LOW | P2 |
| Kill-gate dashboard | MEDIUM | LOW | P2 |
| TradingView Pine cross-check | MEDIUM | LOW | P2 |
| TradingView webhook (operational) | LOW | LOW | P3 |
| 15M entry refinement | MEDIUM | MEDIUM | P3 |
| LIVE_AUTONOMOUS | LOW (V1) | HIGH | P3 (out of scope) |
| LLM decisions / HFT / ML book / RL / daily-target | LOW (negative) | HIGH | P3 (anti-features) |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration (anti-features: explicitly excluded)

## Competitor Feature Analysis

| Feature | Typical retail bot (3Commas / Cryptohopper class) | Typical signal-group + manual execution | Our Approach |
|---------|---------------------------------------------------|------------------------------------------|--------------|
| Decision determinism | Rule configs, often ambiguous repaint behavior | Human discretion, unreproducible | Versioned spec + prefix-invariant + byte-equivalence harness; SignalId dedupe |
| Approval gate | Auto-trade default; approval as afterthought | Chat message, no binding to numbers | Bound idempotent expiring token (SignalId+version+plan_hash+expiry+actor); replay-safe |
| Risk/quantization | Leverage-first sizing, round-up common | Mental math | Equity×0.5% → floor-only rounding → 60% floor else reject; identical in backtest/paper/live |
| Protective exits | Exchange stops, orphan handling varies | Manual SL, often skipped | Algo-Order SL/TP + fill-sized protection + 4-way reconcile + orphan sweeper + SAFE_MODE |
| Attribution | Single PnL number | "My feel" | System vs user vs opportunity + MFE/MAE + bootstrap/MC uncertainty |
| Validation | Backtest-as-marketing | Screenshots | Splits + walk-forward + baselines + holdout + kill gate; NO_TRADE valid |
| Part-time fit | Assumes always-online or full-auto | Missed signals silently | Approval-latency metrics + expiry design + zero-trade-day validity |

## Sources

- Canonical: `docs/00_PRODUCT_SCOPE.md` (pipeline, modes, universe, timeframes, anti-scope), `docs/data/DATA_MODEL.md` (entity separation, lineage), `docs/trading/SIGNAL_AND_ALERTS.md` (SignalId, alert card, quality rules), `docs/trading/RISK_MANAGEMENT.md` (0.5%, quantization, portfolio, daily-stop, fail-closed), `docs/trading/EXECUTION_SPEC.md` (Algo migration, lifecycle, partials, reconcile, orphans, idempotency, SAFE_MODE), `docs/backtest/BACKTEST_SPEC.md` (parity, splits, baselines, uncertainty), `docs/backtest/METRICS.md` (three-way reports, MFE/MAE, latencies), `docs/integration/BINANCE.md` (REST+WS, user-data, OI 30-day window, Algo endpoints), `docs/integration/TELEGRAM.md` (SIMULATE/APPROVE/SKIP, token binding, at-least-once), `docs/integration/TRADINGVIEW.md` (cross-check, webhook caveats), `docs/operations/RUNBOOK.md` (SAFE_MODE, orphans, stale feed, backup drill), `.planning/PROJECT.md` (constraints, decisions D001–D021, out-of-scope)
- External (re-verify at implementation, never hard-code): Binance USDⓈ-M docs (exchangeInfo, Algo orders, WS streams, OI statistics, changelog Dec-2025 MAX_NUM_ALGO_ORDERS removal / 200-per-symbol limit); TradingView strategy/webhook support pages

---
*Feature research for: Deterministic Binance Futures research + semi-automated execution*
*Researched: 2026-09-19*
