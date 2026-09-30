# Lane A1: docs_trading_soundness

Role: a senior crypto-futures risk manager and quant-methodology reviewer, reviewing an AI-written design for a part-time retail trader with $500–1,000 on Binance USDⓈ-M perpetuals. Input is the snapshot at commit 63ca176. Treat the docs as documented intent, not as ground truth (charter §11). Profitability is out of scope; only methodology is judged.

## Scope

- **Docs (all of `docs/`):**
  - `00_PRODUCT_SCOPE`, `01_ENGINEERING_PRINCIPLES`, `DECISIONS`, `GLOSSARY`
  - `strategy/TRADING_STRATEGY_SPEC`
  - `trading/RISK_MANAGEMENT`, `trading/EXECUTION_SPEC`, `trading/SIGNAL_AND_ALERTS`
  - `backtest/BACKTEST_SPEC`, `backtest/METRICS`
  - `research/RESEARCH_PROTOCOL`, `research/TRADING_STRATEGY_RESEARCH` (§1, §6–§10, §13, §17, §25–26), `research/families/*`
  - `configuration/CONFIGURATION`
  - `operations/SECURITY_AND_OPERATIONS`, `operations/RUNBOOK`
  - `integration/BINANCE`, `integration/TELEGRAM`, `integration/TRADINGVIEW`
  - `implementation/IMPLEMENTATION_PLAN`
  - `architecture/DATA_PIPELINE` (§2–§3, §9–§10)
- **Params:** all 10 files under `params/**/*.toml`.
- **Audit inputs:** `INVARIANTS.md`, in particular the Domain-soundness flags, AMB-001..039 and the "Candidate Doc-Design Concerns".
- **Planning:** `.planning/ROADMAP.md` phases 11–17, used for the known-prior tags.
- **Exchange filters:** `tests/fixtures/exchange_info_sample.json`, read only for the recorded exchangeInfo filter values (added 2026-09-19, commit 53fdfce).
- **Probe:** `tmp/docs_trading_soundness/feasibility.py`. It is pure Decimal arithmetic and does not import snapshot code. It uses assumed prices: BTC 60,000, ETH 3,000, BNB 600, SOL 150, XRP 0.60.
- **Public sources:** read-only, listed at the end.
- **Excluded:** no code was judged, which is Stage C's job, and no Binance API was called.

## Coverage

| file | level | note |
|---|---|---|
| docs/00_PRODUCT_SCOPE.md | DEEP_READ | capital, availability, return envelope |
| docs/01_ENGINEERING_PRINCIPLES.md | DEEP_READ | |
| docs/DECISIONS.md | DEEP_READ | D001–D030 |
| docs/GLOSSARY.md | NORMAL_READ | §7–§9 (states, rejection reasons) |
| docs/strategy/TRADING_STRATEGY_SPEC.md | DEEP_READ | template, all TBD |
| docs/trading/RISK_MANAGEMENT.md | DEEP_READ | |
| docs/trading/EXECUTION_SPEC.md | DEEP_READ | |
| docs/trading/SIGNAL_AND_ALERTS.md | DEEP_READ | |
| docs/backtest/BACKTEST_SPEC.md | DEEP_READ | |
| docs/backtest/METRICS.md | DEEP_READ | |
| docs/research/RESEARCH_PROTOCOL.md | DEEP_READ | |
| docs/research/TRADING_STRATEGY_RESEARCH.md | NORMAL_READ | §1, §6–§10, §13, §17, §25–26 deep; the rest by headings |
| docs/research/families/trend-pullback.md | DEEP_READ | |
| docs/research/families/range-mr.md | NORMAL_READ | §1–§4, footer |
| docs/research/families/breakout-retest.md | NORMAL_READ | grep of gates, expiry, footer |
| docs/research/kill_gate_decisions.json | METADATA_ONLY | |
| docs/configuration/CONFIGURATION.md | DEEP_READ | |
| docs/operations/SECURITY_AND_OPERATIONS.md | DEEP_READ | |
| docs/operations/RUNBOOK.md | DEEP_READ | |
| docs/integration/BINANCE.md | DEEP_READ | |
| docs/integration/TELEGRAM.md | DEEP_READ | |
| docs/integration/TRADINGVIEW.md | NORMAL_READ | |
| docs/implementation/IMPLEMENTATION_PLAN.md | DEEP_READ | |
| docs/architecture/DATA_PIPELINE.md | NORMAL_READ | §2–§3, §9–§10 |
| docs/data/DATA_MODEL.md, ARCHITECTURE.md, TESTING_STRATEGY.md, TECHNOLOGY_STACK.md, DOC_STATUS.md, SOURCES.md, README.md, AGENT_INSTRUCTIONS.md | METADATA_ONLY | keyword grep only (leverage, liquidation, workingType, trailing, USDC, survivorship and similar), no hits beyond those cited |
| params/**/*.toml (10 files) | DEEP_READ | |
| tests/fixtures/exchange_info_sample.json | NORMAL_READ | only the LOT_SIZE, MIN_NOTIONAL and PRICE_FILTER values |
| .planning/ROADMAP.md (L26–32, L355–432) | NORMAL_READ | known priors P11–P17 |
| AUDIT/INVARIANTS.md | NORMAL_READ | §G–§L, AMB list, Candidate concerns |

## Verified Safe Areas (Doc Rules Verified Sound)

These rules are correct and safe as written, judged against trading practice and public Binance documentation. Code lanes should enforce them as stated.

1. **Risk-first sizing (INV-053 concept, INV-061, INV-062).**
   - Size comes from equity × risk_rate ÷ SL distance. Leverage is never the size driver.
   - Risk never increases after losses, and there is no daily target.
   - The PRODUCT_SCOPE §10 return envelope is arithmetically correct and honest. At $800, 0.5% risk, 15 trades and 0.175R: $800 × 0.005 × 15 × 0.175 = $10.50 per month.
2. **Floor-only quantization with NO_TRADE preferred over round-up (INV-055, INV-057).**
   - Correct per Binance LOT_SIZE and MIN_NOTIONAL semantics.
   - The 60% utilization rule (INV-056) is sound. At this universe and capital it only ever binds on BTCUSDT (F-003).
   - Reduce-only exits are exempt from the min-notional rule (Binance "New Minimum Order Notional Limit Rule"), so small partial-fill positions can still be closed.
3. **Identical sizing and quantization in every mode (INV-058).** This is the right parity principle. The fee source is still an open question (AMB-005, F-031).
4. **Fail closed and the exchange is authoritative (INV-072, INV-073, INV-092).**
   - User-data WS is used for realtime state.
   - Periodic REST reconciliation covers normal orders, algo orders and positions (INV-093).
   - The orphan-protective sweep runs after position verification (INV-094).
   - There is no blind retry after an ambiguous placement (INV-088).
   - All of this matches Binance's own guidance.
5. **Protective exits via Algo CONDITIONAL orders (INV-080).**
   - `closePosition` cannot be combined with quantity or reduceOnly (INV-082). Confirmed on developers.binance.com New-Algo-Order.
   - `positionSide` is mandatory in Hedge mode. Confirmed on the same page.
   - A2 owns the full Binance fact check.
6. **Stop never silently widened (INV-086), and pending entries always expire (INV-089).** Sound. A GTD backstop is added in F-016.
7. **Approval design (INV-043 to INV-048, INV-052).**
   - Approval is bound to the plan hash.
   - Tokens are one-time, callbacks are treated as at-least-once, and the replay returns the current state.
   - There is no auto-approve when Telegram fails.
   - Only an authorized identity can approve.
   - All of this is correct for Telegram's delivery semantics.
8. **Closed-candle, no-repaint and warm-up rules (INV-003 to INV-006).** Correct. The family sheet also correctly timestamps swing confirmation at `t+N`, not `t`.
9. **Intrabar ambiguity (INV-103).**
   - 1m resolution is used, with a conservative adverse-first tie-break fixed before evaluation.
   - "Never TP-first because it looks nicer" is correct.
   - The code lane should apply the same tie-break to the entry-fill bar (see Corrected Rule 18).
10. **Research controls (INV-100, INV-101, INV-102, INV-104, INV-105).**
    - Costs are modeled from experiment #1, and slippage is never zero.
    - A three-way split keeps an untouched holdout.
    - Uncertainty is reported with block bootstrap.
    - Baselines are compared.
    - There is no retroactive fill after expiry.
    - The system, user and opportunity reports are split, which is the right tool against approval-selection bias.
11. **Kill gate D013/D030 as a time and complexity budget (INV-098).** Sound as a stop rule. It is not evidence (F-025).
12. **Ops basics (INV-078, INV-079, INV-113, INV-115).**
    - Live orders are disabled by default.
    - Restart follows a fixed sequence.
    - Health signals are defined.
    - Backups are encrypted, kept off-host and restore-drilled.
    - The API key has no withdrawal permission.
    - The planned 24 h market-WS reconnect is correct.
13. **OI self-collection from day one (INV-110).** Correct: Binance historical OI statistics cover only about the last month.
14. **Human-approval-first scope and small live universe (INV-119, INV-120).** Appropriate for this user.

## Findings

### F-001 — Sizing formula adds 'modeled_costs' to a price distance without units, and the research doc drops costs from sizing entirely; SL losses exceed the risk budget by the cost share.

- **Severity:** HIGH · **Confidence:** HIGH · **Classification:** DEFECT · **Category:** risk-sizing
- **Component:** RISK_MANAGEMENT sizing formula
- **File / Lines:** `docs/trading/RISK_MANAGEMENT.md:19-23`
- **Invariant:** INV-053, INV-054, AMB-002, AMB-004 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** KNOWN: ROADMAP Phase 11 (code bug in modeled_costs_per_unit); doc-level ambiguity not fixed by P11.
- **Evidence:** RISK_MANAGEMENT.md:19-23 `risk_per_unit = worst_case_distance_to_SL + modeled_costs`; TRADING_STRATEGY_RESEARCH.md:551 `quantity = risk_budget / abs(entry - stop)` (costs only as later 'adjustments'); RESEARCH_PROTOCOL.md:91 `entry_fee` in 'basis points per side'; params fee_rate_entry = 0.0002 (a fraction). Probe (tmp/docs_trading_soundness/feasibility.py): cost share of R = (0.02%+0.05%+0.01%)/SL% = 0.27R at SL 0.3%, 0.16R at 0.5%, 0.08R at 1%; if entry is also taker 0.40R / 0.24R / 0.12R.
- **Expected:** Every term in risk_per_unit is quote-currency per unit of base, so realized loss at SL (fees + slippage included) is <= equity x risk_rate.
- **Actual:** The unit of modeled_costs is unstated; the ambiguity already produced the confirmed code bug (rate 0.0008 added to a 600 USDT distance).
- **Reproduction:** python -B tmp/docs_trading_soundness/feasibility.py (pure arithmetic; assumed prices)
- **Impact:** At $800 equity and 0.5% risk ($4.00), an SL at 0.5% distance loses about $4.64 (1.16x budget), at 0.3% about $5.07 (1.27x); with a taker entry up to 1.4x. The risk cap, the core safety rule, is silently exceeded on every tight-stop trade in backtest, paper and live.
- **Why tests miss it:** Golden fixtures are derived from the same formula; no test asserts 'loss at SL incl. costs <= allowed_risk'.
- **Remediation (corrected rule):** Doc wrong -> use: risk_per_unit = |entry_worst - SL| + entry_ref x fee_entry_rate + SL x (fee_exit_rate + slip_exit_rate) (+ entry_ref x slip_entry_rate when the entry is a taker fill). entry_worst = adverse edge of the entry zone (LONG: entry_max; SHORT: entry_min). All rates are decimal fractions. Acceptance test: simulated SL exit P&L incl. fees and slippage >= -allowed_risk.

### F-002 — No minimum stop distance or cost-to-risk ceiling; tight stops let fees and slippage consume the whole planned edge.

- **Severity:** MEDIUM · **Confidence:** HIGH · **Classification:** GAP · **Category:** risk-sizing
- **Component:** Strategy spec / risk gates
- **File / Lines:** `docs/strategy/TRADING_STRATEGY_SPEC.md:65-69`
- **Invariant:** INV-042, INV-054, INV-105 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** TRADING_STRATEGY_SPEC.md:69 has only `Maximum allowed stop distance: TBD`; no minimum. 00_PRODUCT_SCOPE.md:137-142 plans with expectancy +0.175R. Cost in R (maker in, taker out, 1bp): 0.27R at 0.3% SL, 0.16R at 0.5% SL.
- **Expected:** A plan is rejected when round-trip modeled cost is a large fraction of the risk unit.
- **Actual:** Nothing in the docs prevents a 0.2-0.4% SL on a 1H setup, where costs are 0.2-0.4R, larger than the planning expectancy.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** Backtests on gross-favourable tight-stop setups become net-negative live; also inflates notional (0.3% SL -> $833 notional on $500), raising margin needs.
- **Why tests miss it:** No rule exists to test.
- **Remediation (corrected rule):** Doc silent -> minimum safe rule: reject with NO_TRADE when (modeled round-trip cost per unit) / risk_per_unit > max_cost_to_risk (registry parameter; research baseline 0.15). Record the ratio on the plan. Needs a canonical rejection reason (decision required; do not invent a synonym).

### F-003 — At $500 equity BTCUSDT rejects most swing stops (minNotional/utilization); the other live-5 symbols are feasible. The NO_TRADE rate is undocumented and the 60% rule creates a non-monotonic rejection band.

- **Severity:** LOW · **Confidence:** MEDIUM · **Classification:** GAP · **Category:** small-capital feasibility
- **Component:** Quantization rules at $500-1,000
- **File / Lines:** `docs/trading/RISK_MANAGEMENT.md:113-124`
- **Invariant:** INV-056, INV-057, INV-119 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** Probe tmp/docs_trading_soundness/feasibility.py (assumed prices BTC 60,000 / ETH 3,000 / BNB 600 / SOL 150 / XRP 0.60; filters from tests/fixtures/exchange_info_sample.json, recorded 2026-09-19: BTC step 0.001, minNotional 50; Binance 2023 announcement says BTC 100). $500, risk $2.50: BTC OK at SL <=2.08%, UTILIZATION_REJECT 2.08-2.5% (qty floors 0.00185 -> 0.001, util 0.55), OK 2.5-4.17% (qty 0.001, util 0.6-1.0), MIN_QTY above 4.17%. If minNotional is 100: NOTIONAL_REJECT for every SL > 2.08%. ETH/BNB/SOL/XRP OK at 0.5-5% SL. $1000: all OK up to 4-5%.
- **Expected:** The docs state which symbol/SL combinations are infeasible at the declared capital and require the NO_TRADE-by-reason rate to be reported.
- **Actual:** Rules are sound but their effect is unquantified; the 60% rule is non-binding except on BTC.
- **Reproduction:** python -B tmp/docs_trading_soundness/feasibility.py (pure arithmetic; assumed prices)
- **Impact:** Research results for BTC at $500 will not match what live can trade; minor (NO_TRADE is the safe outcome).
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc correct (keep floor -> min checks -> 60% rule, NO_TRADE over round-up). Add: the backtest must run sizing at the actual live equity (e.g. $500 and $1,000), not a large notional, and report NO_TRADE counts by reason per symbol. A2 to confirm current BTCUSDT minNotional (50 vs 100).

### F-004 — Slippage is defined on the entry of a LIMIT order (where there is none) and set to a flat 1 bp; stop-market exits, which suffer real slippage, get no explicit model; touch-vs-fill has no rule.

- **Severity:** MEDIUM · **Confidence:** MEDIUM · **Classification:** DEFECT · **Category:** cost realism
- **Component:** Slippage and fill model
- **File / Lines:** `docs/research/RESEARCH_PROTOCOL.md:97-111`
- **Invariant:** INV-104, INV-105, AMB-037 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** RESEARCH_PROTOCOL.md:101-103 `effective_entry = intended_entry + slippage`; TRADING_STRATEGY_RESEARCH.md:698-710 'và tương ứng cho exit' (sign unspecified); params `expected_slippage = 0.0001  # 1 bps`, `slippage_model = "FIXED_BPS"`.
- **Expected:** Slippage applies adversely to every taker fill (STOP_MARKET SL, TAKE_PROFIT_MARKET TP, marketable entries). A resting limit fills at its price but only when price trades through it.
- **Actual:** A resting limit gets synthetic slippage, SL exits in fast markets get 1 bp, and a wick touch may count as a fill.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** Two optimistic biases: 1 bp on BTC/ETH SL is roughly the normal-market floor, and SOL/XRP stops in fast moves often slip several to tens of bps; touch=fill overstates fill rate on exactly the setups that reverse at the level (adverse selection). Expectancy is overstated by a few hundredths of R per trade, which is the same order as the planned edge.
- **Why tests miss it:** Fixtures encode the same FIXED_BPS assumption.
- **Remediation (corrected rule):** Doc wrong -> use: (1) limit entry fills only if the 1m low < limit (LONG) / high > limit (SHORT) by >= 1 tick; touch-only is 'no fill' and is reported. (2) Every taker fill gets adverse slippage slip_bps(symbol), with a research baseline >= 2 bps on BTC/ETH and >= 5 bps on BNB/SOL/XRP, plus a mandatory 3x stress run. (3) Slippage sign is always adverse (LONG buys up and sells down; SHORT the reverse). (4) Calibrate from paper/live fills per protocol amendment.

### F-005 — Entry fee is modeled as maker (2 bps) although the entry is placed hours after the signal, may be marketable at placement, and no post-only (GTX) rule exists.

- **Severity:** MEDIUM · **Confidence:** HIGH · **Classification:** DEFECT · **Category:** cost realism
- **Component:** Fee assumption vs entry order type
- **File / Lines:** `params/trend-pullback/baseline-v3.toml:43-44`
- **Invariant:** INV-081, INV-105, AMB-005 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** baseline-v3.toml:43 `fee_rate_entry = 0.0002  # 2 bps maker`, :44 `fee_rate_exit = 0.0005  # 5 bps taker`. EXECUTION_SPEC.md:27-31 entry `LIMIT or a defined limit-zone model`, no timeInForce. Binance USD-M regular tier: maker 0.02%, taker 0.05%, BNB -10% (finder.com, Binance fee page).
- **Expected:** Entry fee follows the actual liquidity role: a limit that is marketable when placed pays taker.
- **Actual:** Maker is always assumed. Exit taker is correct for STOP_MARKET/TAKE_PROFIT_MARKET.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** Underestimates cost by 3 bps on every marketable entry (about 0.06R at 0.5% SL); biases toward setups whose price is already inside the zone at approval time.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc silent -> minimum safe rule: backtest simulates placement at (signal close + modeled approval latency); if the limit is marketable at that moment the fill is taker (and at market + slippage). Live: either send entries as GTX (post-only; rejection = no trade, journaled) or size with the taker rate. Do not model the BNB discount.

### F-006 — The canonical cost sets model every fill as 50% partial, a value chosen to work around hash normalization; it contradicts the FULL_FILL label and the 1.0 used by the baselines.

- **Severity:** MEDIUM · **Confidence:** HIGH · **Classification:** DEFECT · **Category:** backtest methodology
- **Component:** partial_fill_fraction parameter
- **File / Lines:** `params/trend-pullback/baseline-v3.toml:51-57`
- **Invariant:** INV-104, AMB-036, AMB-022 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** baseline-v3.toml:53-57 `spread_fill_assumptions = "FULL_FILL"` ... `# Fractional value (NOT 1.0) to dodge the whole-number-trap (Pitfall 1)` `partial_fill_fraction = 0.5`; same in breakout-retest/baseline-v3.toml:55-61; baseline-no-trade-v1.toml:54 and baseline-simple-trend-v1.toml:56 use 1.0.
- **Expected:** Fill-model parameters are chosen from market reality and are identical between candidate and baselines.
- **Actual:** A serialization workaround sets a market assumption. At $60-$1,000 notional on BTC/ETH/BNB/SOL/XRP books, partial fills are rare; the real uncertainty is fill vs no-fill.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** A constant 50% fill halves realized risk (below the 60% utilization rule it is supposed to respect), halves $ P&L and drawdown, and makes candidate-vs-baseline comparison unlike-for-like. Paper/live parity (EXECUTION_SPEC 5) cannot hold.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc wrong -> use: partial_fill_fraction = 1.0 for V1 order sizes (and the same value in all compared sets); model fill uncertainty with the trade-through rule (F-004). Fix hash normalization in the loader, never by picking parameter values. The loader should reject a partial fraction < minimum utilization.

### F-007 — Nothing requires a live-price check after APPROVE. Price can cross the SL or leave the zone during the 4 h validity, so the LIMIT fills instantly and the SELL/BUY stop is rejected as 'would immediately trigger', leaving a naked position.

- **Severity:** HIGH · **Confidence:** HIGH · **Classification:** GAP · **Category:** execution
- **Component:** Approval -> placement re-check
- **File / Lines:** `docs/trading/EXECUTION_SPEC.md:1-25`
- **Invariant:** INV-049, INV-071, INV-085, AMB-014 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** KNOWN (partial): ROADMAP Phase 15 (price-vs-SL gate). The post-fill SL-rejection fallback is not in ROADMAP.
- **Evidence:** EXECUTION_SPEC.md:16 `Risk re-check` (risk only), :55-65 item 4 'symbol/market conditions make the plan stale' (undefined); params signal_expiry_hours = 4. Binance error -2021 'Order would immediately trigger': a SELL stop needs stopPrice below the latest price, a BUY stop above it (Binance docs, New Order / New Algo Order).
- **Expected:** Placement is refused when the current price has reached the SL (or the invalidation) since signal time or when the entry would be marketable beyond the planned zone; if an SL is rejected after a fill, the position is closed immediately.
- **Actual:** Docs define only risk re-check and plan-hash/expiry gates.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** Worst case: long approved after price already fell below SL -> buy limit fills as taker -> SL rejected -2021 -> unprotected position while the user is at work. Loss is unbounded by the plan (limited only by margin mode and liquidation).
- **Why tests miss it:** Unit tests use static prices; no scenario moves price between approval and placement.
- **Remediation (corrected rule):** Doc silent -> minimum safe rule: at placement read mark and last price; LONG: reject if min(price since signal) <= SL or current > entry_max + entry_buffer; SHORT symmetric; reject if the limit would be marketable unless the strategy spec permits marketable entries. After any fill, if the protective SL is rejected (e.g. -2021) or not acknowledged within N seconds, close with a reduce-only MARKET order, alert, and enter SAFE_MODE.

### F-008 — Protective exits are placed only after the entry fill is observed; a LIMIT rests for up to 4 h, so if the process, host or user-data stream is down when it fills, the position is unprotected until restart.

- **Severity:** HIGH · **Confidence:** MEDIUM · **Classification:** GAP · **Category:** execution
- **Component:** Protection window / resting entries
- **File / Lines:** `docs/trading/EXECUTION_SPEC.md:87-98`
- **Invariant:** INV-084, INV-085, INV-089 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** EXECUTION_SPEC.md:18-22 `Place entry -> Place/attach protective exits`, :87-98 verification 'After entry fill'; RUNBOOK.md:33-42 handles a missing stop only once detected. PRODUCT_SCOPE.md:11-14: the user cannot monitor and cannot respond within minutes.
- **Expected:** An exposure-creating order is never left on the exchange unless protection will exist even if the bot dies.
- **Actual:** No rule bounds the unprotected window or covers executor downtime.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** Single-host VPS restarts, DB outages (RUNBOOK 9) or network loss during a resting entry produce a naked leveraged position for hours.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc silent -> minimum safe rule: (a) arm Binance's USD-M auto-cancel 'kill switch' (countdownCancelAll heartbeat) on symbols with resting entries, so normal (entry) orders cancel if the bot stops sending heartbeats (A2 to verify it cancels normal and not algo orders); (b) OR pre-place the protective SL as closePosition STOP_MARKET together with the entry if Binance accepts it with no open position (A2 verify); (c) SL must be acknowledged within a bounded time after the fill event (e.g. 5 s), else reduce-only market close + SAFE_MODE; (d) on graceful shutdown/SAFE_MODE cancel all resting entries.

### F-009 — SAFE_MODE forbids 'new live order placement' without exempting protective or reduce-only orders, while the RUNBOOK asks to submit protection. Read literally, SAFE_MODE (entered exactly when a stop is missing) forbids placing the stop.

- **Severity:** HIGH · **Confidence:** HIGH · **Classification:** DEFECT · **Category:** ops/safety
- **Component:** SAFE_MODE semantics
- **File / Lines:** `docs/operations/SECURITY_AND_OPERATIONS.md:76-82`
- **Invariant:** INV-074, INV-075, INV-091, AMB-024 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** SECURITY_AND_OPERATIONS.md:80 `no new live order placement;`; RUNBOOK.md:33-42 `SAFE_MODE -> ... -> if stop is absent, submit protection only after risk validation -> otherwise require explicit manual intervention`.
- **Expected:** SAFE_MODE blocks exposure-increasing orders only.
- **Actual:** The contradiction lets an implementer either never re-protect or treat SAFE_MODE as advisory.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** A position whose stop vanished (rejection, orphan sweep bug, manual cancel) stays unprotected until a part-time user reacts.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc wrong -> use: SAFE_MODE blocks every order that can open or increase a position; reduce-only / closePosition protective orders and reduce-only closes are always allowed after an authoritative position query. Missing stop: auto re-place at the original plan SL (never wider); if price is already beyond the SL, reduce-only MARKET close. Manual intervention is optional, not required.

### F-010 — workingType and priceProtect are never chosen. Binance defaults are CONTRACT_PRICE and false; priceProtect=true can stop an SL from triggering when mark and last diverge; the backtest price series must match the trigger series.

- **Severity:** MEDIUM · **Confidence:** MEDIUM · **Classification:** GAP · **Category:** execution
- **Component:** SL/TP trigger configuration
- **File / Lines:** `docs/integration/BINANCE.md:50-50`
- **Invariant:** INV-080, INV-012, INV-103 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** BINANCE.md:50 'Flags such as ... working type ... must be verified'; no doc selects values. Binance New Algo Order: workingType default CONTRACT_PRICE, priceProtect default false; when price reaches stopPrice the MARK/CONTRACT deviation cannot exceed the symbol triggerProtect (developers.binance.com New-Algo-Order). Liquidation is on Mark Price (Binance FAQ).
- **Expected:** The trigger price type and priceProtect are explicit, recorded on the plan, and matched by the backtest price series.
- **Actual:** Left to SDK defaults.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** Mismatch between the backtest (1m last-price klines) and live trigger; a priceProtect=true SL may not fire in a dislocation.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc silent -> minimum safe rule for V1: SL = STOP_MARKET workingType=CONTRACT_PRICE, priceProtect=false (guaranteed trigger, parity with last-price 1m backtest). Switching to MARK_PRICE requires backtesting on markPriceKlines. TP may use priceProtect=true. Record both on the plan and the constraint snapshot.

### F-011 — Canonical docs treat leverage as read-only and never pick a margin type or require liquidation to lie beyond the SL. Risk-based sizing keeps effective leverage low, so the danger is concentrated in isolated mode at high account-default leverage.

- **Severity:** MEDIUM · **Confidence:** HIGH · **Classification:** GAP · **Category:** margin/leverage
- **Component:** Leverage, margin type, liquidation
- **File / Lines:** `docs/trading/RISK_MANAGEMENT.md:87-91`
- **Invariant:** INV-068, INV-069, INV-070, AMB-019 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** KNOWN: ROADMAP Phase 13 (leverage, margin type, liquidation guard) and Phase 14 (available margin).
- **Evidence:** RISK_MANAGEMENT.md:89-91 'Leverage must be treated as an exchange/account constraint ... read current account/symbol constraints'; BINANCE.md:52-59 'read and record'. Arithmetic: $500, 0.5% risk: SL 0.5% -> notional $500 (1x per position, 2x for two); SL 0.3% -> $833 each. Isolated 50x -> liquidation ~2% - MMR from entry (inside a 2% SL); isolated 20x -> ~4.6%; cross -> effectively the whole wallet backs the position.
- **Expected:** The margin type and leverage are set explicitly, and liquidation is verified to lie well beyond the SL.
- **Actual:** Orders inherit whatever the account has.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** Isolated + high leverage: premature liquidation (plus clearance fee) and a divergence from the backtest. Leverage 1x: entries rejected for margin when combined notional exceeds equity. Cross: one unprotected position can drain the whole wallet.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc silent -> minimum safe rule: margin type ISOLATED per symbol. Leverage set explicitly as the smallest integer L such that notional/L fits availableBalance with >= 20% headroom, capped at 5x. Guard: projected isolated liquidation price (bracket MMR from exchange) is beyond the SL by >= 1x the SL distance, else NO_TRADE. Refuse if the account mode differs and cannot be changed (open orders or positions).

### F-012 — 'Account equity' is undefined (wallet vs margin balance vs available) and so is its timing (signal vs approval vs placement).

- **Severity:** MEDIUM · **Confidence:** HIGH · **Classification:** AMBIGUITY · **Category:** risk-sizing
- **Component:** Equity definition
- **File / Lines:** `docs/trading/RISK_MANAGEMENT.md:7-23`
- **Invariant:** INV-053, INV-067, AMB-003, AMB-018 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** KNOWN: ROADMAP Phase 12 (equity source).
- **Evidence:** RISK_MANAGEMENT.md:7 'Risk is determined from account equity'; :20 `allowed_risk = equity x risk_rate`.
- **Expected:** One definition that cannot be inflated by unrealized profit.
- **Actual:** Undefined, and caller-injected in code (ROADMAP P12).
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** Using totalMarginBalance with an open winner upsizes the next trade on paper profit; a stale equity oversizes after losses.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc silent -> minimum safe rule: sizing equity = min(totalWalletBalance, totalMarginBalance) of the quote asset (unrealized losses count, unrealized gains do not), snapshotted at plan creation and stored on the plan. At placement, re-read: if planned risk > risk_rate x current equity x 1.05, reject (re-plan). Never upsize. Backtest/paper: equity = simulated wallet balance with the same rule.

### F-013 — The daily loss stop has no day boundary, PnL basis, equity base, comparison operator or reset rule; the docs say TBD while params fix 1%.

- **Severity:** MEDIUM · **Confidence:** HIGH · **Classification:** AMBIGUITY · **Category:** risk limits
- **Component:** Daily loss stop
- **File / Lines:** `docs/trading/RISK_MANAGEMENT.md:44-85`
- **Invariant:** INV-066, AMB-012 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** RISK_MANAGEMENT.md:51 `daily loss stop: TBD`; :71-85 NORMAL/WARNING/DAILY_STOP; params `daily_loss_stop_threshold = 0.01`, `daily_loss_warning_threshold = 0.005`.
- **Expected:** An exact, reproducible definition.
- **Actual:** Undefined.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** Inconsistent blocking between modes; the stop may reset mid-session with a restart or on a local-time boundary.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc silent -> minimum safe rule: day = 00:00-24:00 UTC. daily_loss = -(realized PnL + commissions + funding) booked in that UTC day, from exchange data in live. Base = equity snapshot at 00:00 UTC. A state is reached when daily_loss >= threshold x base. DAILY_STOP persists across restarts until the next UTC day, cancels resting unfilled entries and never cancels protective orders. Note: 1% = two full losses at 0.5%; one slipped loss already reaches WARNING.

### F-014 — Cluster membership and direction handling are undefined; with cluster_cap = risk_rate at most one aligned position is possible, so max_open_positions = 2 is reachable only as long+short in correlated coins. What counts as 'open' (working entries, pending approvals) is undefined, which allows two approvals to race past the caps.

- **Severity:** MEDIUM · **Confidence:** MEDIUM · **Classification:** AMBIGUITY · **Category:** portfolio risk
- **Component:** Cluster cap / open-risk accounting
- **File / Lines:** `docs/trading/RISK_MANAGEMENT.md:44-59`
- **Invariant:** INV-063, INV-064, INV-065, AMB-016, AMB-017 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** RISK_MANAGEMENT.md:50 `max risk for one correlated cluster: TBD`, :57-59; params `cluster_cap = 0.005  # single-trade risk_rate`, `max_open_positions = 2`, `max_aggregate_open_risk = 0.01`.
- **Expected:** An explicit cluster and a consistent open-risk ledger.
- **Actual:** Undefined.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** Either correlated double exposure (if the cluster is empty) or silent de-facto single-position operation.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc silent -> minimum safe rule: one cluster = all live-5 symbols (crypto beta), cap applied per direction. Open risk = filled positions (at original plan risk) + working entry orders + APPROVED-not-yet-placed plans. Gates are evaluated under one serialized lock at approval and again at placement. State explicitly that effective aligned exposure is one position.

### F-015 — The approval message shows prices, R:R and 'risk %' but no quantity, notional, $ loss at SL net of costs, margin, leverage, liquidation price, or the equity used.

- **Severity:** MEDIUM · **Confidence:** HIGH · **Classification:** GAP · **Category:** approval UX
- **Component:** Telegram message contents
- **File / Lines:** `docs/integration/TELEGRAM.md:34-49`
- **Invariant:** INV-050, INV-051 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** KNOWN: ROADMAP Phase 16.
- **Evidence:** TELEGRAM.md:34-49 minimum contents; SIGNAL_AND_ALERTS.md:80-106 example `Risk: 0.5%`, `Valid until: 16:00 UTC`.
- **Expected:** A non-expert approving a live order sees exactly what money is at stake.
- **Actual:** Percentages only.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** The human cannot detect a sizing bug (e.g. F-001, or a wrong equity) before approving; the approval step provides no real check.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc silent -> minimum rule: add qty, notional, estimated $ loss at SL (gross and net of fees/slippage), $ at each TP, leverage and margin used, liquidation price, equity used with source and timestamp, current price and distance to entry/SL, and time remaining; values come from the risk pipeline output, never recomputed in the renderer.

### F-016 — One 4 h validity is used for signal, approval and entry. There is no minimum remaining validity at approval, no exchange-side expiry, and no rule for how the user's availability (Asia/Ho_Chi_Minh office hours and sleep) biases which trades get taken.

- **Severity:** MEDIUM · **Confidence:** MEDIUM · **Classification:** GAP · **Category:** approval UX
- **Component:** Expiry windows
- **File / Lines:** `params/trend-pullback/baseline-v3.toml:31-31`
- **Invariant:** INV-047, INV-089, AMB-013, AMB-031 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** `signal_expiry_hours = 4`; PRODUCT_SCOPE.md:14 'cannot guarantee response within minutes'; EXECUTION_SPEC.md:55-65. Binance GTD requires goodTillDate >= now + 600 s (New Algo Order docs; A2 to confirm for normal orders).
- **Expected:** The approval deadline equals the plan expiry, and approval is refused when too little time remains for the entry to work.
- **Actual:** Unspecified.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** Late approvals place entries that are canceled minutes later (fees, orphan risk). Night-time (UTC 16:00-00:00) signals systematically expire, so user-executed results differ from system results.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc silent -> minimum safe rule: approval deadline = plan.expiry_utc (measured from the source candle close). Reject approval if remaining validity < max(600 s, min_remaining_validity parameter). Entry is sent with GTD = expiry_utc as an exchange-side backstop in addition to the local cancel. The opportunity report slices by hour-of-day (UTC+7) to quantify the availability bias.

### F-017 — 'Revalidated before approval/execution' does not say whether revalidation may change qty or prices, which would execute something other than what the human approved.

- **Severity:** MEDIUM · **Confidence:** HIGH · **Classification:** AMBIGUITY · **Category:** approval safety
- **Component:** Post-approval revalidation
- **File / Lines:** `docs/trading/RISK_MANAGEMENT.md:143-143`
- **Invariant:** INV-044, INV-049, INV-060, AMB-014 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** RISK_MANAGEMENT.md:143 'A plan calculated with stale constraints must be revalidated before approval/execution.'; TELEGRAM.md:23-30 approval bound to the exact plan hash.
- **Expected:** The approved plan is executed exactly or not at all.
- **Actual:** Ambiguous.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** Silent re-sizing after approval defeats plan-hash binding.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc ambiguous -> use: revalidation is reject-only. Qty, prices and side of the approved plan are immutable; any change produces a new plan requiring a new approval.

### F-018 — The TP1/TP2 template gives no quantity-rounding rule, and nothing says what happens to the SL after TP1 (breakeven? trailing?) or how to replace a stop without an unprotected gap.

- **Severity:** MEDIUM · **Confidence:** HIGH · **Classification:** GAP · **Category:** execution
- **Component:** TP ladder, breakeven, trailing, SL modification
- **File / Lines:** `docs/trading/EXECUTION_SPEC.md:77-85`
- **Invariant:** INV-084, INV-086, INV-055 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** EXECUTION_SPEC.md:77-83 `TP1 : TAKE_PROFIT_MARKET, reduceOnly=true, explicit quantity`; RISK_MANAGEMENT.md:61-65 only 'must not silently widen'. Example: BTC qty 0.003, TP1 50% = 0.0015 is not a multiple of step 0.001; qty 0.001 cannot be split at all.
- **Expected:** Leg quantities are floored to step with a deterministic remainder rule; stop management is either absent or specified and backtested identically.
- **Actual:** Silent.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** Rejected TP orders, an over-sized final leg, or a stop cancel/replace window without protection; backtest/live divergence if the live system moves stops the backtest does not.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc silent -> minimum safe rule: TP_i qty = floor(q x frac_i / step) x step; if any leg < minQty, use a single TP; the last TP closes the exact remainder (or closePosition). SL is closePosition (one-way) or qty == position. V1: no breakeven or trailing unless the frozen strategy spec declares it and the backtest simulates it. Any SL change may only tighten, and the new stop must be acknowledged before the old one is canceled (or the position is closed).

### F-019 — Liquidation and auto-deleveraging (ADL), which close or reduce a position without our order, are not described beyond a LIQUIDATION_REPORTED status.

- **Severity:** LOW · **Confidence:** MEDIUM · **Classification:** GAP · **Category:** reconciliation
- **Component:** Liquidation / ADL / external close
- **File / Lines:** `docs/GLOSSARY.md:103-111`
- **Invariant:** INV-092, INV-094, INV-096 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** GLOSSARY.md:109 `LIQUIDATION_REPORTED`; no mention of ADL or external close anywhere in docs (grep).
- **Expected:** Any position change not caused by our own order is detected and handled.
- **Actual:** Silent.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** Journal PnL and open-risk ledger drift; orphan protectives remain (covered by the sweep) but a partial ADL could leave SL qty > position.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc silent -> minimum rule: reconciliation classifies unexplained position deltas (liquidation, ADL, manual) as EXTERNAL, journals them with exchange PnL, re-sizes or cancels protectives after an authoritative query, and enters SAFE_MODE if the position increased unexpectedly.

### F-020 — 'Support the chosen position mode' vs 'support both'; the Multi-Assets mode effect on margin is unaddressed.

- **Severity:** LOW · **Confidence:** HIGH · **Classification:** AMBIGUITY · **Category:** execution
- **Component:** Position mode scope
- **File / Lines:** `docs/trading/EXECUTION_SPEC.md:106-112`
- **Invariant:** INV-083, AMB-030 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** EXECUTION_SPEC.md:108-110; BINANCE.md:56-57.
- **Expected:** A minimal supported scope with fail-closed detection.
- **Actual:** Open-ended.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** Hedge-mode templates (positionSide mandatory, no reduceOnly) are a large untested surface.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc ambiguous -> use: V1 supports One-way + Single-Asset mode only; any other detected mode -> no new entries (fail closed) with an alert.

### F-021 — The funding sign convention is 'documented' nowhere, 'ADDITIVE' is undefined, and funding intervals are assumed uniform.

- **Severity:** MEDIUM · **Confidence:** MEDIUM · **Classification:** AMBIGUITY · **Category:** cost realism
- **Component:** Funding model
- **File / Lines:** `docs/research/RESEARCH_PROTOCOL.md:113-115`
- **Invariant:** INV-105, INV-110, AMB-037 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** RESEARCH_PROTOCOL.md:115 'Funding is signed per side per the documented convention'; params `funding_treatment = "ADDITIVE"`.
- **Expected:** The Binance convention: positive rate means longs pay shorts; the fee = position notional at mark x rate, charged only if the position is open at the funding timestamp.
- **Actual:** Undefined.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** A wrong sign flips a cost into income; multi-day swing holds (3-9 funding events) carry 0.03-0.1%+ of notional (about 0.03-0.2R at 0.5-1% SL), more in funding spikes.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc silent -> use: funding_pnl = -sign(position) x qty x markPrice(fundingTime) x fundingRate for each actual fundingTime from the funding history (no fixed 8 h grid) while the position is open at that instant. Included in net R, not in sizing.

### F-022 — Numeric pass thresholds are set only after Validation evidence from the three families has been seen, 'passing' is a human decision, and there is no multiple-testing correction across roughly 25+ variants plus parameter sweeps.

- **Severity:** HIGH · **Confidence:** HIGH · **Classification:** DEFECT · **Category:** research methodology
- **Component:** Acceptance methodology
- **File / Lines:** `docs/research/RESEARCH_PROTOCOL.md:205-236`
- **Invariant:** INV-098, INV-100, INV-101, INV-038 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** RESEARCH_PROTOCOL.md:211 'After >=3 independently specified families ... have produced Validation evidence, then and only then are candidate numerical thresholds proposed'; :236 'a family's passing status is a recorded human decision ... never computed'. Variant rows: trend-pullback 7, range-mr 11, breakout-retest 7+; plus sweeps (CONFIGURATION 8).
- **Expected:** Thresholds and the selection procedure are frozen before any out-of-sample data are looked at; the number of trials is recorded and penalized.
- **Actual:** Thresholds chosen after results = maximal researcher degrees of freedom; the user states little trading expertise.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** High probability of promoting a noise-fit variant to live (money loss), exactly the failure the kill gate is meant to prevent.
- **Why tests miss it:** Governance, not code.
- **Remediation (corrected rule):** Doc wrong -> use: before the first Validation run, a protocol amendment (v1.1.0) freezes the numeric gates: min trades overall/per symbol/per quarter; the lower bound of a block-bootstrap 95% CI of net expectancy > 0 at 1x costs and >= 0 at 2x costs; max drawdown and loss-streak ceilings at live equity. Every tried variant/parameter point is logged (trial count N) and a multiple-testing adjustment is applied (Deflated Sharpe, White's Reality Check, or Bonferroni). Exactly one pre-selected candidate touches the final holdout, once. A human decision may reject a numerically passing candidate but may never pass a failing one.

### F-023 — 3-6 months of paper cannot statistically confirm the edge, and the exit gate ('minimum forward evidence defined by the actual signal frequency') is undefined.

- **Severity:** MEDIUM · **Confidence:** HIGH · **Classification:** GAP · **Category:** research methodology
- **Component:** Paper-soak exit gate
- **File / Lines:** `docs/implementation/IMPLEMENTATION_PLAN.md:79-101`
- **Invariant:** INV-120, INV-101 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** IMPLEMENTATION_PLAN.md:81, :98. BACKTEST_SPEC.md:101-107 own SE example. 15 trades/month x 6 months = 90 trades; sigma 1.2R -> SE 0.126R, 95% CI +/-0.25R versus a planning expectancy of +0.175R (PRODUCT_SCOPE:137-142).
- **Expected:** The paper gate tests what paper can test: operational parity and consistency with the backtest.
- **Actual:** Undefined gate; risk of reading 90 trades as proof.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** Either an endless soak or a false green light.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc silent -> minimum rule: the paper exit requires (1) replaying the paper period through the backtest engine reproduces the same signals and plans byte-for-byte; (2) realized fill rate, slippage and latency are within the modeled assumptions; (3) paper net expectancy is not below the backtest block-bootstrap lower bound (consistency, not significance); (4) a pre-registered minimum n (e.g. >= 30 closed trades) and >= 3 months. Live starts at minimum capital.

### F-024 — The research universe is chosen as '10-15 sufficiently liquid symbols' today, with no point-in-time rule, so survivorship and selection bias are built in (delisted or faded coins excluded).

- **Severity:** MEDIUM · **Confidence:** MEDIUM · **Classification:** GAP · **Category:** research methodology
- **Component:** Research universe selection
- **File / Lines:** `docs/backtest/BACKTEST_SPEC.md:111-119`
- **Invariant:** INV-100, INV-109, INV-119 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** BACKTEST_SPEC.md:115; RESEARCH_PROTOCOL.md:60; DATA_PIPELINE.md:107-120 records status_history but not the selection rule.
- **Expected:** A point-in-time, pre-declared universe rule.
- **Actual:** Discretionary present-day selection.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** Breakout/trend families look better on coins that survived and trended.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc silent -> minimum rule: at each walk-forward window start, the universe = top-N USD-M perpetuals by trailing 30-day quote volume as of that date (list frozen and hashed into the experiment record before evaluation), including later delisted symbols where klines exist. The live-5 ex-post choice is disclosed as such.

### F-025 — Family sheets restate the kill gate as 'three families x six months of forward evidence' and require 'all three families' to clear before a V1 family is chosen, contradicting D030 and making selection impossible if any family fails.

- **Severity:** LOW · **Confidence:** HIGH · **Classification:** DRIFT · **Category:** research governance
- **Component:** Family sheets vs D030
- **File / Lines:** `docs/research/families/trend-pullback.md:199-209`
- **Invariant:** INV-098 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** trend-pullback.md:199, :209; breakout-retest.md:216, :226; range-mr.md:222, :232 vs DECISIONS.md D030 (six calendar months since freeze; backtest + OOS).
- **Expected:** One wording.
- **Actual:** Three contradicting sheets.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** Governance confusion; a code lane could implement the wrong gate.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc wrong -> use D030 as the only rule; V1 selection = any family holding a recorded pass after all three were evaluated on the same split (not 'all three pass'). The 6-month clock is a time budget, not a sample size; it gives no statistical evidence.

### F-026 — 'Periodically' and 'configured freshness threshold' have no values or classification; an unset threshold disables fail-closed.

- **Severity:** MEDIUM · **Confidence:** MEDIUM · **Classification:** AMBIGUITY · **Category:** ops/safety
- **Component:** Reconciliation cadence and freshness thresholds
- **File / Lines:** `docs/trading/EXECUTION_SPEC.md:114-132`
- **Invariant:** INV-075, INV-076, INV-093, INV-095, AMB-023 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** EXECUTION_SPEC.md:116 'On startup/reconnect and periodically'; RUNBOOK.md:81-86 'configured freshness threshold'.
- **Expected:** Concrete bounded defaults.
- **Actual:** None.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** Stale state or data could be trusted indefinitely.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc silent -> minimum rule (runtime config, non-null, fail-closed defaults): full REST reconciliation (positions, open orders, open algo orders) at start and reconnect and every <= 60 s while any position or working order exists (<= 5 min otherwise). User-data listenKey keepalive every <= 30 min (A2 verify the 60 min validity). A 1H/4H decision requires the closed kline within <= 90 s of the candle close, else DATA_STALE for that cycle. Market WS silent > 60 s -> reconnect + resync.

### F-027 — IP allowlisting is only 'preferred', and other permissions (universal transfer, spot/margin) are not restricted.

- **Severity:** LOW · **Confidence:** HIGH · **Classification:** GAP · **Category:** security
- **Component:** API key permissions
- **File / Lines:** `docs/operations/SECURITY_AND_OPERATIONS.md:3-10`
- **Invariant:** INV-111 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** SECURITY_AND_OPERATIONS.md:5 'API key must not have withdrawal permission', :7 'Prefer IP allowlisting where practical'.
- **Expected:** Least privilege for a key that can place leveraged orders.
- **Actual:** Only withdrawal is excluded.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** A leaked key can trade the account into loss or move funds between wallets.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc weak -> use: the live key is IP-allowlisted (mandatory), Futures trading + read only, no withdrawal, no universal transfer, no spot/margin; collectors use a separate read-only key; keys are rotated on any suspected exposure.

### F-028 — The protocol defines fees in basis points per side while the parameter sets store fractions (0.0002).

- **Severity:** LOW · **Confidence:** HIGH · **Classification:** DEFECT · **Category:** risk-sizing
- **Component:** Fee unit definition
- **File / Lines:** `docs/research/RESEARCH_PROTOCOL.md:91-92`
- **Invariant:** INV-054, AMB-002 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** RESEARCH_PROTOCOL.md:91 '`entry_fee` | Taker/maker fee applied at entry, basis points per side'; baseline-v3.toml:43 `fee_rate_entry = 0.0002  # 2 bps maker`.
- **Expected:** One unit.
- **Actual:** Two units; a value of 2 entered 'per protocol' would be a 200% fee.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** A 10,000x unit error risk in future parameter sets.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc wrong -> use: fee and slippage rates are decimal fractions with a `_rate` suffix; the loader rejects any fee rate > 0.01 as a unit error.

### F-029 — The tick size is listed as a constraint, but the rounding direction for entry/SL/TP and the order of rounding versus sizing are unspecified.

- **Severity:** LOW · **Confidence:** MEDIUM · **Classification:** GAP · **Category:** risk-sizing
- **Component:** Price tick rounding
- **File / Lines:** `docs/trading/RISK_MANAGEMENT.md:25-32`
- **Invariant:** INV-011, INV-055 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** RISK_MANAGEMENT.md:29 'price tick size' (validation only).
- **Expected:** Deterministic rounding, with sizing done on the rounded prices.
- **Actual:** Silent.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** Small risk overshoot and RR-gate flips at the boundary; backtest/live divergence.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc silent -> use: round to tickSize before sizing. LONG entry down, SHORT entry up; SL away from entry (keeps the structural meaning); TP toward entry. Compute qty and RR from the rounded prices.

### F-030 — 'the range is invalidated and the position exits at SL' on a 1H close break describes a closed-candle discretionary exit that is not an exchange-side order.

- **Severity:** LOW · **Confidence:** MEDIUM · **Classification:** AMBIGUITY · **Category:** strategy semantics
- **Component:** Range-MR close-based exit
- **File / Lines:** `docs/research/families/range-mr.md:47-47`
- **Invariant:** INV-106, INV-012 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** none (new)
- **Evidence:** range-mr.md:47.
- **Expected:** Open positions exit only via exchange-side SL/TP, or via an explicitly specified close-based exit that the backtest simulates identically.
- **Actual:** Ambiguous mechanism.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** A live/backtest mismatch, or a reliance on the bot being alive to exit.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc ambiguous -> use: either drop it (the exchange-side SL governs) or specify 'reduce-only MARKET close at the next bar open after a qualifying closed 1H bar', simulated identically, with the exchange-side SL kept in place as a backstop.

### F-031 — Fee tiers, the BNB discount and USDC-margined pairs are not addressed; live commission may differ from the versioned parameter fees.

- **Severity:** INFO · **Confidence:** MEDIUM · **Classification:** IMPROVEMENT · **Category:** cost realism
- **Component:** Fee source, BNB discount, USDC
- **File / Lines:** `docs/trading/RISK_MANAGEMENT.md:34-42`
- **Invariant:** INV-058, INV-118, AMB-005 · **Phase/commit:** docs (pre-code design) / 63ca176
- **Known-prior:** KNOWN: ROADMAP Phase 11 (commissionRate), Phase 17 (quote asset).
- **Evidence:** RISK_MANAGEMENT.md:34-42 cost list only; Binance regular tier 0.02%/0.05%, BNB -10% (third-party summaries of Binance fee page).
- **Expected:** A conservative, reproducible fee choice.
- **Actual:** Unaddressed.
- **Reproduction:** Read the cited doc lines; no code path involved (design review).
- **Impact:** Minor; sizing could understate costs if the account rate > parameter rate.
- **Why tests miss it:** Design-level doc issue; tests encode the documented (or absent) rule.
- **Remediation (corrected rule):** Doc silent -> use: live sizing uses max(parameter fee, account commissionRate) per side, recorded on the plan; ignore the BNB discount in sizing; USDC pairs are a universe change (new data, new parameter set, re-backtest), out of V1.

## Corrected Rules for Code Audit

This is the binding list for the Stage B and C lanes. Each rule carries one of three verdicts:

- **"doc correct"**: enforce the doc as written.
- **"doc wrong → use X"**: judge the code against X.
- **"doc silent → minimum safe rule X"**: a missing X is a GAP. It is a DEFECT only where a canonical doc or requirement already implies X.

Items tagged KNOWN are already planned in ROADMAP P11–P17. Report them as KNOWN, not as new findings.

### Risk and sizing

1. **Risk sizing basis (INV-053).** Doc correct: `allowed_risk = equity × risk_rate` and qty = allowed_risk ÷ risk_per_unit. Leverage never affects qty.

2. **Risk per unit (INV-054, AMB-002, AMB-004, F-001).** Doc wrong → use:
   - Formula: `risk_per_unit = |entry_worst − SL| + entry_ref×fee_entry_rate + SL×(fee_exit_rate + slip_exit_rate)`.
   - When the entry is a taker fill, add `+ entry_ref×slip_entry_rate`.
   - `entry_worst` is the adverse zone edge: `entry_max` for a LONG, `entry_min` for a SHORT.
   - All rates are decimal fractions.
   - Check: the simulated SL exit, including fees and slippage, must lose ≤ allowed_risk.
   - KNOWN P11.

3. **Cost-to-risk ceiling (F-002).** Doc silent → minimum safe rule:
   - Reject when modeled round-trip cost per unit ÷ risk_per_unit exceeds `max_cost_to_risk`.
   - `max_cost_to_risk` is a registry parameter; the research baseline is 0.15.

4. **Quantization order (INV-055, INV-056, INV-057, AMB-006, AMB-007).** Doc correct:
   - Floor to stepSize in Decimal.
   - Reject when the floored qty is below minQty, or the notional below minNotional.
   - Reject when realized risk after rounding is below `minimum_risk_utilization_after_rounding` × allowed_risk.
   - Never round up.
   - Utilization numerator: rounded_qty × risk_per_unit. Denominator: allowed_risk.
   - Evaluation order changes only the reason code, not the outcome.

5. **Notional price reference (AMB-027).** Doc silent → minimum safe rule: check minNotional at the order's limit price and at the current mark price, and reject if either fails.

6. **Tick rounding (F-029).** Doc silent → use:
   - Round prices to tickSize first, then size.
   - LONG entry rounds down; SHORT entry rounds up.
   - SL rounds away from entry; TP rounds toward entry.
   - Compute RR and qty from the rounded prices.

7. **Equity (AMB-003, INV-067, F-012).** Doc silent → minimum safe rule:
   - Equity = min(totalWalletBalance, totalMarginBalance), snapshotted at plan creation.
   - At placement, reject when planned risk > risk_rate × current equity × 1.05.
   - Never upsize.
   - Unknown or stale equity → NO_TRADE.
   - KNOWN P12.

8. **Fees (AMB-005, F-005, F-028, F-031).** Doc wrong/silent → use:
   - Rates are fractions. The loader rejects any rate > 0.01.
   - The backtest uses the versioned fees.
   - Live sizing uses max(parameter fee, account commissionRate) per side, recorded on the plan.
   - An entry that is marketable at (simulated) placement pays the taker fee, or is sent GTX (post-only).
   - The BNB discount is never assumed.
   - KNOWN P11.

### Portfolio and daily limits

9. **Portfolio caps (INV-063, INV-064, INV-065, AMB-016, AMB-017, F-014).** Doc silent → minimum safe rule:
   - All live-5 symbols form one cluster, capped per direction.
   - Open risk = filled positions + working entries + APPROVED-but-unplaced plans.
   - Check the caps under one serialized lock, both at approval and at placement.
   - Params doc correct as placeholders: max positions 2, aggregate 1%, cluster 0.5%.

10. **Daily loss (INV-066, AMB-012, F-013).** Doc silent → minimum safe rule:
    - The day runs over the UTC day.
    - Loss = −(realized PnL + commission + funding) for that day.
    - Base = equity at 00:00 UTC. A threshold counts as reached at ≥.
    - DAILY_STOP persists across restart until the next UTC day.
    - DAILY_STOP cancels resting entries and never cancels protective orders.

### Margin, leverage and liquidation

11. **Leverage, margin type and liquidation (INV-068, INV-069, INV-070, AMB-019, F-011).** Doc silent → minimum safe rule:
    - Isolated margin.
    - Leverage set explicitly: the smallest integer that fits availableBalance with ≥ 20% headroom, capped at 5x.
    - Projected liquidation must lie beyond the SL by ≥ 1× the SL distance, using the exchange bracket MMR.
    - Otherwise NO_TRADE (`INSUFFICIENT_MARGIN` / constraint reject).
    - KNOWN P13 and P14.

### Execution

12. **Entry type (INV-081).** Doc correct: LIMIT or limit-zone only, no market entry by default.
    - Add: send the entry with GTD = plan expiry as an exchange backstop to the local cancel.
    - GTD needs ≥ 600 s of remaining validity. If less remains, refuse the placement.

13. **Pre-placement price gate (INV-071, F-007).** Doc silent → minimum safe rule:
    - Reject if the price has reached the SL (or the invalidation level) since the signal.
    - Reject if the entry would be marketable beyond the zone.
    - Use both mark and last price.
    - KNOWN P15.

14. **Post-fill protection (INV-084, INV-085, F-007, F-008).** Doc silent → minimum safe rule:
    - The SL is acknowledged within a bounded time after the fill (≤ 5 s default).
    - If the SL is rejected (for example -2021) or not acknowledged: reduce-only MARKET close, alert, SAFE_MODE.
    - Size protectives to the filled qty.
    - Resting entries are either covered by a dead-man auto-cancel, or protected by a pre-placed closePosition stop. A2 to verify both mechanisms.
    - Resting entries are canceled on shutdown and on SAFE_MODE.

15. **SL/TP trigger configuration (F-010).** Doc silent → minimum safe rule for V1:
    - SL: `STOP_MARKET`, `workingType=CONTRACT_PRICE`, `priceProtect=false`.
    - Both values are recorded on the plan.
    - Using MARK_PRICE requires a mark-price-kline backtest.

16. **TP ladder and stop moves (INV-086, F-018).** Doc silent → minimum safe rule:
    - TP leg qty is floored to step. If any leg is below minQty, use a single TP.
    - The last leg closes the exact remainder.
    - No breakeven or trailing unless the frozen spec declares it and the backtest simulates it.
    - An SL may only be tightened, and the new stop must be acknowledged before the old one is canceled.

17. **Position mode (INV-083, AMB-030, F-020).** Doc ambiguous → use:
    - Support One-way + Single-Asset mode only.
    - Detect the mode on start and before each entry.
    - Any other mode → no new entries.

### Backtest methodology

18. **Fill simulation (INV-104, AMB-036, F-004, F-006).** Doc wrong → use:
    - A limit fill needs a trade-through by ≥ 1 tick. A touch is not a fill.
    - `partial_fill_fraction = 1.0` at V1 sizes, identical across the candidate and its baselines.
    - Parameter values are never chosen for hash convenience.
    - If the entry-fill 1m bar also reaches the SL, count the SL as hit.

19. **Slippage and funding (INV-105, AMB-037, F-004, F-021).** Doc wrong/silent → use:
    - Adverse slippage on every taker fill: ≥ 2 bps on BTC/ETH, ≥ 5 bps on BNB/SOL/XRP baseline, plus a 3× stress run.
    - funding_pnl = −sign(pos) × qty × mark(fundingTime) × rate, at the actual funding timestamps while the position is open.
    - Funding is included in net R.

20. **Intrabar tie-break (INV-103, AMB-035).** Doc correct: adverse-first, fixed before evaluation, and recorded in the experiment identity.

### Approval

21. **Approval deadline and expiry (INV-047, INV-089, AMB-013, AMB-031, F-016).** Doc silent → minimum safe rule:
    - Approval deadline = plan expiry, counted from the source candle close.
    - Refuse approval when remaining validity < max(600 s, `min_remaining_validity`).
    - A local cancel plus GTD enforce the expiry.
    - An expiry boundary equal to `expiry_utc` counts as expired.

22. **Revalidation after approval (INV-049, AMB-014, F-017).** Doc ambiguous → use: reject-only. Qty, prices and side are immutable, and any change requires a new approval.

23. **Approval message (INV-050, INV-051, F-015).** Doc silent → minimum rule:
    - Show qty, notional, $ loss at SL gross and net, $ at each TP, leverage and margin, liquidation price, the equity used with its source and time, current price, and time left.
    - Values come from the sizing output.
    - KNOWN P16.

### Safety and operations

24. **SAFE_MODE (INV-074, AMB-024, F-009).** Doc wrong → use:
    - SAFE_MODE blocks only orders that open or increase exposure.
    - Reduce-only and closePosition protective orders and closes are always allowed after an authoritative position query.
    - A missing stop is re-placed automatically at the original plan SL, never wider. If the price is already beyond the SL, close reduce-only at market.

25. **SAFE_MODE triggers and exit (INV-075, AMB-015).** Doc correct on the triggers.
    - Minimum safe rule: exit from SAFE_MODE is manual only, and the mode persists across restart.

26. **Reconciliation cadence and freshness (INV-076, INV-093, INV-095, AMB-023, F-026).** Doc silent → minimum safe rule:
    - Full REST reconciliation every ≤ 60 s while any position or order exists (≤ 5 min otherwise).
    - listenKey keepalive every ≤ 30 min.
    - Closed kline required within ≤ 90 s of candle close, else DATA_STALE.
    - WS silent > 60 s → reconnect.
    - These values must be non-null.

27. **External position changes (INV-092, INV-094, INV-096, F-019).** Doc silent → minimum rule:
    - Unexplained position deltas (liquidation, ADL, manual close) are classified EXTERNAL and journaled.
    - Protectives are resized or canceled after an authoritative query.
    - An unexpected increase → SAFE_MODE.

28. **Deterministic client IDs (INV-087).** Doc correct but insufficient. Binance enforces client-ID uniqueness only among open orders (A2 to verify).
    - Minimum rule: a durable local dedup keyed on the approval token and plan hash must block re-submission after the first order filled or was canceled.

29. **API key (INV-111, F-027).** Doc weak → use:
    - IP allowlist is mandatory.
    - Permissions: futures trade + read only. No withdrawal, no universal transfer, no spot/margin.
    - A separate read-only key for the collectors.

30. **Backups (INV-115).** Doc correct.

### Research governance

31. **Acceptance gates (INV-098, INV-100, INV-101, INV-038, F-022).** Doc wrong → use:
    - Numeric gates and the trial-count penalty are frozen before any Validation run (protocol v1.1.0).
    - The lower bound of the block-bootstrap CI of net expectancy is > 0 at 1× costs and ≥ 0 at 2× costs.
    - Minimum trade counts per slice.
    - Drawdown and loss-streak ceilings are measured at live equity.
    - A multiple-testing adjustment covers all tried variants.
    - The holdout is used once, for one candidate.
    - A human may veto a pass, but never pass a failing candidate.

32. **Paper exit gate (INV-120, F-023).** Doc silent → minimum rule:
    - Byte-identical replay parity.
    - Fill rate, slippage and latency within the model.
    - Paper expectancy ≥ the backtest bootstrap lower bound.
    - ≥ 30 closed trades and ≥ 3 months.
    - Live starts at minimum capital.

33. **Research universe (INV-100, INV-109, F-024).** Doc silent → minimum rule:
    - Point-in-time top-N by trailing 30-day quote volume at each window start.
    - The list is frozen and hashed before evaluation.
    - Include delisted symbols where data exists.
    - Report the live-5 separately (doc correct on that).

34. **Kill gate (INV-098, F-025).** D030 wording is the only valid rule.
    - The family-sheet phrases "forward evidence" and "all three families clear" are wrong.
    - V1 selection = any family with a recorded pass after all three were evaluated on the same split.

35. **Warm-up, closed candle, no-lookahead (INV-003 to INV-006).** Doc correct.

36. **Range-MR close-based exit (F-030).** Doc ambiguous → use:
    - Either the exchange SL only, or a reduce-only market close at the next bar open, simulated identically.
    - The exchange SL always stays in place as a backstop.

37. **Small-capital feasibility (INV-057, INV-119, F-003).** Doc correct on rejecting.
    - Add: the backtest sizes at the actual live equity ($500 / $1,000) and reports NO_TRADE counts by reason per symbol.

## Open Questions

**For A2 `docs_exchange_facts`:**
- Current BTCUSDT minNotional. The recorded fixture (2026-09-19) says 50; the 2023 announcement says 100.
- Whether `closePosition=true` STOP_MARKET algo orders are accepted with no open position (pre-placed protection, F-008).
- Whether `countdownCancelAll` (auto-cancel kill switch) exists for USD-M and whether it covers algo orders.
- Whether GTD's minimum of +600 s applies to normal LIMIT orders.
- The per-symbol funding interval.
- listenKey validity (60 min).
- clientOrderId uniqueness scope.
- `-2021` behavior for algo conditional orders.
- `triggerProtect` values per symbol.

**For B1/B2 (planning):**
- Whether the Phase 5 D-05 cluster and aggregate decisions define cluster membership.
- Who chose `partial_fill_fraction = 0.5` and `signal_expiry_hours = 4`. Both look like AI-picked defaults without trading rationale.
- Whether the Phase 10 kill-gate design adopted the family-sheet wording.

**For Stage C code lanes:**
- Check that the code's SAFE_MODE gate exempts reduce-only and protective orders (Corrected Rule 24).
- Check for a post-fill SL-rejection fallback (Corrected Rule 14).
- Check which `workingType` and `priceProtect` values are actually sent (Corrected Rule 15).
- Check whether the backtest treats a touch as a fill (Corrected Rule 18).

**Methodology assumptions stated in this lane (Medium confidence):**
- Slippage floors (2 bps / 5 bps).
- Cost-to-risk ceiling of 0.15.
- Leverage cap of 5x with a liquidation distance ≥ 1× the SL distance.
- 60 s / 90 s ops thresholds.

These are proposed minimum safe defaults, not exchange facts. They should become registry or runtime parameters recorded by a human decision.

## Sources (public, read-only)

- Binance New Algo Order (workingType default CONTRACT_PRICE, priceProtect default false, GTD ≥ 600 s, closePosition/reduceOnly/positionSide constraints): https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order
- Binance minimum notional announcements: https://www.binance.com/en/support/announcement/new-minimum-order-notional-limit-rule-for-usd%E2%93%A2-m-futures-76719bbaeeb847bbac4daa2906fcdcc0 (reduce-only exempt) ; https://www.binance.com/en/support/announcement/updates-on-minimum-notional-value-for-btcusdt-and-ethusdt-perpetual-contracts-2023-11-02-e4384cba297a4bd2a154be644d5d76f9 (BTC 100 / ETH 20 / others 5 USDT, 2023)
- Binance USD-M fee rate page (login-gated content): https://www.binance.com/en/fee/futureFee ; summary with regular tier 0.02% maker / 0.05% taker and a 10% BNB discount: https://www.finder.com/cryptocurrency/trading/binance-futures-fees
- Binance liquidation price FAQ (liquidation triggers on Mark Price; isolated vs cross wallet balance): https://www.binance.com/en/support/faq/how-to-calculate-liquidation-price-of-usd%E2%93%A2-m-futures-contracts-b3c689c1f50a44cabb3a84e663b81d93
- Leverage and margin FAQ: https://www.binance.com/en/support/faq/detail/360033162192
- -2021 "Order would immediately trigger" and priceProtect/triggerProtect semantics: https://0xhardman.xlog.app/binance-futures-api-guide?locale=en (secondary source) and https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order
