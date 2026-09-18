# Pitfalls Research

**Domain:** Deterministic Binance Futures research + semi-automated execution (4H/1H, Telegram APPROVE-gated, Algo-Order protective exits)
**Researched:** 2026-09-19
**Confidence:** HIGH (grounded in repo canonical docs: `docs/01_ENGINEERING_PRINCIPLES.md`, `docs/backtest/BACKTEST_SPEC.md`, `docs/trading/RISK_MANAGEMENT.md`, `docs/trading/EXECUTION_SPEC.md`, `docs/architecture/DATA_PIPELINE.md`, `docs/integration/TELEGRAM.md`; Binance endpoint details per docs' cited official references, to be re-verified before implementation)

## Critical Pitfalls

### Pitfall 1: Look-ahead via unclosed candles and future swing confirmation

**What goes wrong:**
Backtest shows excellent entries because the strategy "knew" the candle close, the swing high/low, or the breakout confirmation before it was knowable. Live, the same rule fires late, differently, or not at all. Expectancy collapses by 0.2–0.5R or flips sign.

**Why it happens:**
Using `close` of the in-progress candle, referencing `high[i+1]`-style confirmation (e.g. "swing confirmed 2 candles later") at decision time `i`, or evaluating indicators on partially-formed candles. Pandas makes this a one-character mistake (`shift` direction).

**How to avoid:**
- Hard rule (BACKTEST_SPEC §3, ENGINEERING_PRINCIPLES §5–§6): strategy decisions may use only information available **by the source candle close**. Encode `sourceCandleCloseTime` on every signal; engine asserts decision timestamp > source close.
- Freeze confirmation semantics in the strategy spec: e.g. "N-candle confirmation means signal timestamp = close of confirmation candle, entry evaluated after" — never backdate the signal to the swing candle.
- Prefix-invariance test: replaying data up to candle `t` must produce byte-identical decisions regardless of what candles `t+1…` contain. Add as a CI gate.

**Warning signs:**
- Backtest entry timestamps equal swing-pivot timestamps rather than confirmation-candle closes.
- Live/paper entries consistently 1–2 candles later than backtest entries.
- Removing the "confirmation" leg barely changes live behavior but destroys backtest performance.

**Phase to address:**
Phase 1 (strategy spec freeze + backtest engine) — acceptance gate "no material look-ahead". Re-verify in Phase 2 (paper vs backtest entry-timing diff).

---

### Pitfall 2: Repainting signals (historical signal ≠ live signal)

**What goes wrong:**
Research notebook declares a signal at candle `t` using data that later gets revised (unclosed candle, recalculated indicator state, re-fetched corrected klines), so the journaled backtest signal cannot be reproduced live from the same prefix. Restarts duplicate or move alerts.

**Why it happens:**
Indicator state seeded from incomplete history, mutable signal objects updated after emission, or strategy logic living inside throwaway notebook cells instead of the canonical engine.

**How to avoid:**
- Immutable signal identity: `strategyVersion + symbol + timeframe + sourceCandleCloseTime + setupType` (ENGINEERING_PRINCIPLES §7). Emitted signals are frozen value objects; corrections create new IDs, never mutate.
- Same decision code path in backtest/paper/live (frozen strategy library; notebooks call it, never reimplement — ENGINEERING_PRINCIPLES Python rules).
- Restart test: kill and reboot mid-session; assert zero duplicate alerts and identical re-emitted state.

**Warning signs:**
- "Signal disappeared on refresh" in notebooks.
- Duplicate Telegram alerts after reconnect/restart.
- Backtest trade count changes when re-running the same experiment ID.

**Phase to address:**
Phase 1 (engine + golden fixtures) with regression coverage; restart/reconnect rehearsal in Phase 2.

---

### Pitfall 3: Intrabar SL/TP ordering resolved optimistically on 1H OHLC

**What goes wrong:**
A 1H candle's range touches both stop and target; the backtest assumes TP filled first and books +2R. Live (or on 1m data), price hit SL first. This single assumption can fabricate most of a strategy's edge — especially for tight-stop / wide-target designs.

**Why it happens:**
Vectorized backtests see only OHLC and default to TP-first, close-price, or "both hit = win" logic. No finer resolution exists unless deliberately collected.

**How to avoid:**
- BACKTEST_SPEC §4: resolve both-touched bars with **1m intrabar data** (Phase-0 collection dependency). Where 1m is unavailable, apply the declared conservative assumption (SL-first) and report the assumption + sensitivity (what % of expectancy depends on ambiguous bars).
- Track ambiguous-bar share as a first-class metric; any candidate whose edge vanishes under SL-first ordering is rejected.
- Identical ordering semantics in paper/live execution simulation.

**Warning signs:**
- High win-rate concentrated in bars where `low <= SL and high >= TP`.
- Expectancy drops sharply when re-run with SL-first assumption.
- Strategy prefers Entry→SL/TP distances small relative to 1H ATR (more ambiguous bars).

**Phase to address:**
Phase 0 (1m collection) → Phase 1 (intrabar resolver + assumption reporting). Blocks acceptance.

---

### Pitfall 4: Isolated-optimum parameters (0.20 excellent / 0.19 and 0.21 poor)

**What goes wrong:**
A parameter (e.g. ATR multiplier 0.20) looks excellent while immediate neighbors fail. It ships, then dies live — the "optimum" was noise fitted to specific historical wiggles.

**Why it happens:**
Grid-searching many parameters on limited trades and picking the peak without checking the neighborhood. Low-frequency 4H/1H data means few independent trades, so peaks are sharp by chance.

**How to avoid:**
- Require **neighborhood stability plots** for every tuned parameter: report performance at ±1/±2 steps. Accept only plateaus, never spikes (BACKTEST_SPEC gate 9: no critical conclusion on an isolated parameter point).
- Prefer walk-forward over single-split optima (BACKTEST_SPEC §8), especially for structure/ATR rules.
- Freeze parameter registry with rationale (CONFIGURATION); any change = new strategy version + full revalidation.

**Warning signs:**
- Heatmap shows a single bright cell surrounded by red.
- Walk-forward windows disagree on the "best" value.
- Author defends the exact value with a story ("0.20 is the market's favorite").

**Phase to address:**
Phase 1 (research protocol + acceptance gates). Flag for re-check whenever parameters change.

---

### Pitfall 5: Holdout optimization + single-symbol / single-quarter dependence

**What goes wrong:**
The final holdout is peeked at ("just one more tweak"), or the edge lives in one symbol (SOL) or one quarter (a single trend episode). Live universe (BTC/ETH/BNB/SOL/XRP) underperforms the brochure.

**Why it happens:**
Small samples + researcher degrees of freedom. Peeking is incremental and feels harmless each time. Single-symbol testing hides regime dependence.

**How to avoid:**
- BACKTEST_SPEC §7/§10–11: strict Dev → Validation → **untouched Final holdout/forward test**. Log every experiment (ID, params, dataset, code/data version). Any holdout use = burn it; roll a new holdout window.
- Report per-symbol, per-quarter, per-regime breakdowns + bootstrap intervals (not point expectancy). Gate 4/5/9: not confined to one symbol/session; OOS not materially inconsistent without understood reason.
- Research may use 10–15 liquid symbols for power, but must report the **live-5 slice separately**; never accept on the broad universe rescuing a weak live universe (§10.1).
- Respect the kill gate: 3 families / 6 months with NO_TRADE a valid outcome (D013).

**Warning signs:**
- "Final" results edited after seeing holdout.
- One symbol/quarter carries >50% of total R.
- Validation Sharpe ≫ holdout Sharpe with no structural explanation.

**Phase to address:**
Phase 1 (protocol freeze before parameter work). Paper forward test (Phase 2) is the second holdout — do not tune on it.

---

### Pitfall 6: Costs added after selection (fees / funding / slippage)

**What goes wrong:**
A strategy is selected gross of costs, then net performance is ~zero or negative once 0.5%-risk sizing meets entry+exit fees, funding on multi-day holds, spread/slippage on LIMIT-zone fills, and partial-fill drag. With $4 nominal risk per trade at $800 equity, costs are a first-order term, not a haircut.

**Why it happens:**
Research defaults (zero fees, mid-price fills, no funding) are convenient; cost config is "added later" — after the winner is already chosen and emotionally locked in.

**How to avoid:**
- BACKTEST_SPEC §5 + RISK_MANAGEMENT §2–§3: every run declares entry fee, exit fee, funding treatment, slippage, spread/fill assumptions **from the first experiment**. Experiment record without cost fields is invalid.
- Size-aware costing: `risk_per_unit = worst_case_SL_distance + modeled_costs`; quantity derived after costs.
- Sensitivity table: show expectancy at 1×/2× modeled slippage; reject candidates that survive only at 0×.

**Warning signs:**
- Gross/net expectancy gap never shown.
- Holding multi-day positions with no funding line item.
- LIMIT-zone strategy assumed filled at touch with zero slippage.

**Phase to address:**
Phase 1 (cost model frozen in research protocol before parameter work).

---

### Pitfall 7: Quantity rounded UP to meet minimums (silent risk increase)

**What goes wrong:**
Risk-based size computes 0.003 BTC, exchange minimum is 0.005 — the code rounds up and the trade risks 0.8% instead of 0.5%. Across small-equity accounts this systematically breaches the 0.5%/trade and 1.0% aggregate caps.

**Why it happens:**
`ceil` feels helpful ("otherwise we'd miss the trade"); min-qty handling is coded at execution time, not in the risk contract.

**How to avoid:**
- RISK_MANAGEMENT §11 algorithm is the law: **floor** to stepSize → realized-risk check (60% baseline utilization) → below min-qty/notional = **reject with QUANTIZATION_REJECT / NO_TRADE**. Never round up past the risk budget. Identical logic in backtest/paper/live; log raw qty, rounded qty, realized risk.
- Prefer NO_TRADE over budget breach — explicitly (PROJECT.md constraints).

**Warning signs:**
- `math.ceil` / "round up to minimum" anywhere near sizing.
- Live risk/trade exceeds plan risk on small-quantity symbols (XRP/SOL).
- Backtest assumes fractional sizes the exchange would reject.

**Phase to address:**
Phase 1 (backtest quantization parity) → Phase 3 (live sizing re-check). Unit-test with adversarial raw quantities.

---

### Pitfall 8: Hard-coded precision / filters vs dynamic exchangeInfo

**What goes wrong:**
Tick size, stepSize, min notional, or leverage brackets change (or differ per symbol); orders get rejected (`LOT_SIZE`, `MIN_NOTIONAL`, `PRICE_FILTER`) or — worse — accepted at wrong precision. Strategy silently stops trading or mis-sizes.

**Why it happens:**
Copy-pasting filter values from a blog post or memory into constants; works on BTC, fails on XRP.

**How to avoid:**
- Load all filters from current `exchangeInfo` per symbol; snapshot exact constraints used per plan (`price_tick_size`, `quantity_step_size`, min/notional, leverage, `metadata_observed_at_utc` — RISK_MANAGEMENT §12). Revalidate stale-constraint plans before approval/execution.
- Never hard-code from memory — re-verify against current official docs before implementation (PROJECT.md constraints).
- Decimal/tick arithmetic for exchange-sensitive values, never float equality.

**Warning signs:**
- Constants like `STEP_SIZE = 0.001` in code or config.
- Rejections cluster on one symbol after a Binance filter update.
- No `metadata_observed_at_utc` on trade plans.

**Phase to address:**
Phase 0B (symbol metadata pipeline) → Phase 3 (pre-placement revalidation). Also a Phase 2 paper check.

---

### Pitfall 9: Legacy STOP_MARKET endpoint vs Algo Order service

**What goes wrong:**
Protective exits placed via legacy `/fapi/v1/order` STOP_MARKET/TAKE_PROFIT_MARKET calls fail or behave unexpectedly because since late 2025 USDⓈ-M conditional orders migrated to the **Algo Order service**. Position left unprotected while the system believes it is protected.

**Why it happens:**
Tutorials, old SDK examples, and memorized API knowledge predate the migration. Code "looks right" against 2024 docs.

**How to avoid:**
- EXECUTION_SPEC §2: implement protective SL/TP on current **Algo Order endpoints**; verify exact semantics against current official changelog/trade API before implementation, not from memory.
- Post-fill verification loop (§6): after entry fill, confirm the protective stop exists and is active via authoritative query; otherwise HIGH-PRIORITY alert, never assume protection.
- Track the 200-open-conditional-orders-per-symbol limit with headroom (§12); never depend on the removed `MAX_NUM_ALGO_ORDERS` filter.

**Warning signs:**
- `STOP_MARKET` sent to the ordinary order endpoint.
- "Protection placed" logged without an exchange-side order ID.
- Protection works on testnet memory but fails on live API version.

**Phase to address:**
Phase 3 (execution implementation) with a dedicated API re-verification task; RUNBOOK rehearsal must include protection-confirmation failure.

---

### Pitfall 10: closePosition / reduceOnly / position-mode misuse

**What goes wrong:**
`closePosition=true` combined with `quantity` or `reduceOnly` (rejected), or a One-way-Mode TP template (`TP1 reduceOnly+qty, TP2 closePosition`) deployed on a Hedge-Mode account (rejected or one-sided). Partial-fill TP quantities then mismatch the actual position, leaving residual exposure or unprotected remainders.

**Why it happens:**
Treating the EXECUTION_SPEC §5 pattern as a universal template instead of a mode-dependent example. Position mode assumed, never detected.

**How to avoid:**
- Detect position mode explicitly at startup; branch order construction per mode (§8). Never assume One-way or Hedge.
- Encode API constraints in code: `closePosition` only on supported market-triggered conditional types, mutually exclusive with `quantity`/`reduceOnly` (§2). Validate before send; fail closed on mismatch.
- Size protective exits against **actual filled quantity** (§5), with reconciliation for out-of-order/replayed fills.

**Warning signs:**
- Mode detection code missing; template pasted verbatim.
- Partial-fill + multi-TP tests absent.
- API rejections mentioning `closePosition`/`reduceOnly` in logs.

**Phase to address:**
Phase 3 (execution) + TESTING_STRATEGY golden fixtures for both modes and partial fills.

---

### Pitfall 11: Orphan protective orders after close

**What goes wrong:**
Position closes (TP hit, manual close, SL filled) but its stop/TP Algo orders remain open. A later price spike triggers a stale stop into a naked short/long — an unplanned position with no plan, no risk check, no approval.

**Why it happens:**
Local state trusted ("we closed, so we're flat") without canceling exchange-side conditional orders; WS-only tracking misses events during disconnects.

**How to avoid:**
- EXECUTION_SPEC §9 reconciliation loop: compare local state vs open normal orders vs open **algo/conditional** orders vs positions on startup/reconnect and periodically. Explicit orphan detection → cancel after authoritative position verification. Never rely on WS stream alone.
- Position-close is a transaction: close fill confirmed → cancel associated conditionals → verify zero open for that plan ID → journal.
- Orphan sweeper as a scheduled job, covered in RUNBOOK rehearsal.

**Warning signs:**
- Open algo-order count grows over days.
- Fills with no matching plan ID ("where did this short come from?").
- Reconciliation job missing or WS-only.

**Phase to address:**
Phase 3 (reconciliation + orphan sweeper) + Phase 2 paper soak (detect orphans without money at stake).

---

### Pitfall 12: Duplicate Telegram approval creating a second order

**What goes wrong:**
User taps APPROVE twice (impatient double-tap, delayed UI, retried callback); two entry orders are placed. Double size, double risk, possible aggregate-cap breach.

**Why it happens:**
Telegram callbacks are **at-least-once**; each tap looks like a fresh intent unless bound to a one-time token.

**How to avoid:**
- TELEGRAM.md §3/§6 + EXECUTION_SPEC §7: approval bound to (SignalId, strategy version, plan hash, expiry, user/chat, **one-time token**); deterministic client order IDs; consumed-token callback returns current state, **never creates a new order intent**.
- Approval expiry enforced; stale/invalid plans unapprovable (PROJECT.md constraints). No auto-approve on notification failure (§5).
- Concurrency test: fire the same callback 5× concurrently; assert exactly one order intent.

**Warning signs:**
- Approval handler without token lookup.
- Client order ID generated randomly per attempt instead of deterministically per plan.
- "Occasional double orders" in paper logs, dismissed as user error.

**Phase to address:**
Phase 2 (paper Telegram SIMULATE/APPROVE/SKIP path) — must pass idempotency tests before any live approval. Re-verify in Phase 3 rollout.

---

### Pitfall 13: Stale-data trading + missing warm-up (EMA200-4H and reconnects)

**What goes wrong:**
Signals computed on stale WS data, gapped history after reconnect, or indicators (EMA200-4H needs ~800 hours ≈ 33+ days of history) seeded from a truncated bootstrap — generating confident-looking plans from garbage state.

**Why it happens:**
WS assumed permanent; startup skips REST bootstrap; continuity never validated; staleness has no threshold.

**How to avoid:**
- DATA_PIPELINE §4–§6: closed-candle events only; heartbeat/reconnect + gap detection; **re-bootstrap after reconnect if uncertain**; data-quality rejects (duplicates, impossible OHLC, timestamp regression, stale feed, metadata mismatch) → fail closed (NO_TRADE).
- Warm-up sequence (§5): REST history → continuity validation → seed indicators → attach WS → verify latest closed candle. Block strategy evaluation until warm-up completes, with per-indicator minimum-history declarations.
- Stale-feed TTL per timeframe; breach = SAFE_MODE for entries, reconciliation continues.

**Warning signs:**
- Signals emitted within seconds of startup.
- No gap-detection or re-bootstrap code.
- EMA200 values that shift when longer history is backfilled.

**Phase to address:**
Phase 0 (pipeline + warm-up) → Phase 2 (reconnect chaos tests). Paper must log warm-up/gap events.

---

### Pitfall 14: OI history assumed available beyond the 30-day window

**What goes wrong:**
Six months into research, the team wants OI-regime analysis — but Binance's historical OI statistics cover only ~the latest month. The feature is untestable; strategy variants depending on it cannot be validated.

**Why it happens:**
Assuming any API-visible metric is backfillable. OI is a snapshot stream, not a perpetual archive.

**How to avoid:**
- DATA_PIPELINE §9/§12: start the `OpenInterestCollector` (periodic current-OI snapshots persisted with timestamp+symbol) **in Phase 0, before OI is used by any strategy** (D009). Historical candles/funding can be backfilled later; OI cannot.
- Declare OI-dependent hypotheses blocked until self-collected coverage suffices; do not proxy with visible-window-only data and pretend it generalizes.

**Warning signs:**
- Research plan lists OI filters with no collector running.
- OI analysis covers only the last 30 days, presented as representative.
- No OI table/partition in storage design.

**Phase to address:**
Phase 0 (day-one collector). Irreversible if missed — highest time-value pitfall.

---

### Pitfall 15: Daily-profit forcing / revenge sizing

**What goes wrong:**
A "make $X/day" expectation (explicit or ambient) pushes trades on no-setup days and larger sizes after losses. The system's 0.5% baseline becomes 1–2% "just this once," and a normal drawdown becomes an account event.

**Why it happens:**
Capital framed as income stream rather than research capital; loss aversion; zero-trade days feel like failure.

**How to avoid:**
- Structural: no fixed daily target (D010, RISK_MANAGEMENT §7 — never increase risk after losses or unmet targets); zero-trade days valid; kill gate bounds the work (D013). Journal separates system vs user-executed vs opportunity performance so discretionary overrides are visible, not hidden in system stats.
- Mechanical: daily risk states (NORMAL/WARNING/DAILY_STOP — §8); DAILY_STOP blocks new live positions, keeps protection active, alerts user. Max 2 open positions / 1.0% aggregate research placeholders (§4) + correlation-cluster rule for aligned BTC/ETH/SOL/XRP (§5).
- Monthly arithmetic envelope ($800×0.5%×15×0.175R) is illustration only — never an optimization target.

**Warning signs:**
- "Today is red, one more setup?" language; skipped-plan rate drops late in the day.
- Position sizes drifting above plan after losing days.
- Daily target added to dashboards or alerts.

**Phase to address:**
Every phase (culture + code): protocol (Phase 1), journal analytics (Phase 2+), DAILY_STOP enforcement (Phase 3). Review at each gate.

---

### Pitfall 16: Vectorized-library result treated as canonical validation

**What goes wrong:**
A VectorBT/pandas notebook shows a great equity curve and is presented as "validated" — but it models none of partial fills, LIMIT-zone expiry, quantization, or intrabar SL/TP ordering. The canonical engine later disagrees by a wide margin, and months of selection were spent on artifacts.

**Why it happens:**
Vectorized tools are fast and seductive; building the honest engine is slow. Notebook independence drifts from live semantics one shortcut at a time.

**How to avoid:**
- BACKTEST_SPEC §13 + ENGINEERING_PRINCIPLES Python rules: VectorBT/pandas/Polars are **exploratory-only**. Final validation must run the canonical strategy/backtest engine with declared execution semantics; notebooks call reusable library code, never duplicate strategy logic; live process never depends on notebook state.
- Parity tests: canonical engine vs notebook on golden fixtures; any divergence blocks acceptance. Baselines (§9) run through the same canonical path.

**Warning signs:**
- "Validation" artifacts are `.ipynb` files with inline strategy code.
- No golden-fixture parity test between notebook and engine.
- Words like "fill assumed at touch" in the fine print.

**Phase to address:**
Phase 1 (engine + TESTING_STRATEGY golden fixtures). Protocol freeze explicitly demotes notebooks to exploration.

---

### Pitfall 17: Strategy patched in prod code bypassing spec/version

**What goes wrong:**
A "tiny" live fix (tolerance tweak, extra filter, different expiry) is edited directly in production code without updating the strategy spec, parameter registry, or version. Backtest history no longer describes what's trading; the experiment record lies; the next researcher optimizes a ghost.

**Why it happens:**
Time pressure + "it's just one line" + version bumps feeling bureaucratic. Paper/live divergence blamed on "market change."

**How to avoid:**
- Determinism contract (ENGINEERING_PRINCIPLES §1): same snapshot + account state + **strategy version** + config = same decision. Any semantic change = new version + spec update + registry entry + revalidation (BACKTEST_SPEC §11 experiment record). No versionless edits to strategy semantics.
- Enforce mechanically: strategy parameters load only from the versioned registry (CONFIGURATION); signal IDs embed strategyVersion so mixed-version operation is detectable; CI rejects unregistered parameter changes.
- AGENT_INSTRUCTIONS/IMPLEMENTATION constraints: no-AI-in-decisions extends to no-stealth-edits — human-readable diff of spec+version required per change.

**Warning signs:**
- Live behavior paper can't reproduce from the recorded version.
- "Hotfix" commits touching strategy constants without version bump.
- Two environments running different semantics under the same version string.

**Phase to address:**
Phase 1 (registry + versioning discipline) enforced through Phase 2/3; audit at every promotion gate.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Notebook-only strategy, engine "later" | Fast first equity curve | Pitfalls 2/16: unreproducible signals, fake validation | Never for validation; exploration only |
| Zero-cost backtests, costs "later" | More candidates survive | Pitfall 6: selection on phantom edge | Never — costs from experiment #1 |
| `ceil` to min-qty | Fewer rejected trades | Pitfall 7: systematic risk-budget breach | Never |
| Hard-coded tick/step values | Less metadata plumbing | Pitfall 8: symbol-specific rejections/mis-size | Never in prod path; tolerable in one-off exploration |
| Legacy order-endpoint protection | Reuses old examples | Pitfall 9: unprotected live positions | Never |
| WS-only position tracking | Less code | Pitfall 11: orphan orders → naked positions | Never |
| Non-idempotent APPROVE handler | Simpler callback code | Pitfall 12: duplicate live orders | Never |
| 1H-OHLC-only backtest, 1m "later" | No storage work | Pitfall 3: fabricated edge on ambiguous bars | Only with declared SL-first assumption + sensitivity report; 1m required before acceptance |
| OI research without collector | No infra work | Pitfall 14: permanently untestable hypotheses | Never — collector starts Phase 0 |
| Hotfix strategy in prod | Fast incident response | Pitfall 17: version/spec/record corruption | Only to reduce risk (flatten/SAFE_MODE); semantic changes always versioned |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Binance Algo Orders | STOP_MARKET via `/fapi/v1/order`; `closePosition` + `quantity` combined; One-way template on Hedge account | Current Algo endpoints; constraint validation pre-send; explicit mode detection (EXECUTION_SPEC §2/§5/§8) |
| Binance exchangeInfo | Hard-coded step/tick/notional; trusting removed `MAX_NUM_ALGO_ORDERS` filter | Dynamic load per symbol; snapshot per plan with timestamp; 200-conditional-order headroom, re-verified limits (§12) |
| Binance user-data WS | Trusting stream for protection state; assuming permanent connection | User-data WS preferred realtime + periodic authoritative REST reconciliation incl. algo orders (§9) |
| Telegram callbacks | Each APPROVE = new intent; random client IDs | One-time token + deterministic client IDs + expiry; replay returns state (TELEGRAM.md §3/§6) |
| Telegram availability | Auto-approve or infer placement from missing notification | Journal signal, place nothing, never auto-approve (§5) |
| OI history API | Backfilling 6 months of OI from `/futures/data/openInterestHist` | Accept ~30-day window; self-collect from Phase 0 (DATA_PIPELINE §9/§12) |
| Market-data WS/REST | Trading on stale/gapped feed; no warm-up | Closed-candle + heartbeat + gap detect + re-bootstrap + warm-up gate; fail closed (DATA_PIPELINE §4–§6) |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| PostgreSQL as sole store for 1m history (~7.9M candles for 5 symbols × 3y) | Slow scans, bloated ops DB | Parquet (immutable raw) + DuckDB/Polars analysis; PostgreSQL for operational events; monthly partitioning (DATA_PIPELINE §11/§8-second) | Phase 1 research scale |
| Backtest engine doing network I/O | Non-reproducible runs, slow grids | Pure deterministic core; async/network outside strategy layer | First parameter sweep |
| Float equality on qty/price | Phantom rejects, off-by-tick orders | Decimal/tick arithmetic for exchange-sensitive values | First live symbol with awkward stepSize |
| Unbounded algo-order accumulation | Rejected protection near 200/symbol cap | Track open algo count + headroom; orphan sweeper | Months into live operation |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Telegram chat not allow-listed / approval token predictable | Unauthorized APPROVE → live orders | Bind approval to authorized chat + one-time unguessable token + expiry + plan hash (TELEGRAM.md §3; SECURITY_AND_OPERATIONS) |
| API keys with withdraw/universal transfer scope | Full account compromise on leak | Futures-only, no-withdraw keys; IP allow-list; secrets manager, never in repo/logs (SECURITY_AND_OPERATIONS) |
| Logging raw plans/keys/order responses verbosely | Secret + strategy leakage via logs | Redact secrets; log IDs/hashes, not credentials |
| No SAFE_MODE / kill-switch rehearsal | Panic-driven manual errors during incident | RUNBOOK-rehearsed SAFE_MODE (blocks entries, keeps reconciliation); manual cancel/close controls (EXECUTION_SPEC §11) |

## UX Pitfalls (operator = the part-time trader)

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Telegram alert missing R:R, expiry, invalidation, exposure | Approval under uncertainty → bad approves or paralysis | Mandatory message fields (TELEGRAM.md §4) incl. reason codes |
| Silent quantization reject / stale-plan unapprovable with no reason | "Bot is broken" mistrust | Clear reason codes (`QUANTIZATION_REJECT`, plan-stale cause) surfaced in Telegram + journal |
| Unprotected-position state invisible | False sense of safety | HIGH-PRIORITY alert + persistent unsafe-state banner until protection confirmed |
| Approval with no expiry shown | Approving a stale plan hours later | Visible countdown; expired plans require fresh signal |

## "Looks Done But Isn't" Checklist

- [ ] **Backtest:** Often missing 1m intrabar resolution + declared ambiguous-bar assumption — verify ambiguous-bar share and SL-first sensitivity reported
- [ ] **Backtest:** Often missing cost model — verify every experiment record has fees/funding/slippage fields
- [ ] **Backtest:** Often missing holdout discipline — verify holdout untouched log + per-symbol/quarter/regime breakdowns + bootstrap intervals
- [ ] **Backtest:** Often missing canonical-engine validation — verify VectorBT/notebook result reproduced by canonical engine on golden fixtures
- [ ] **Sizing:** Often missing quantization parity — verify floor/60%-reject logic identical in backtest/paper/live with raw/rounded/realized-risk logs
- [ ] **Data:** Often missing OI collector — verify snapshots flowing from Phase 0 with timestamp+symbol persistence
- [ ] **Data:** Often missing warm-up gate — verify no signals before REST bootstrap + continuity check + EMA200-history readiness
- [ ] **Execution:** Often missing Algo-Order migration — verify protection via current Algo endpoints with exchange-side order IDs
- [ ] **Execution:** Often missing orphan sweeper — verify reconciliation covers normal + algo orders + positions with RECONCILIATION_REQUIRED path tested
- [ ] **Approval:** Often missing idempotency — verify 5× duplicate-callback test yields exactly one order intent
- [ ] **Ops:** Often missing SAFE_MODE rehearsal — verify RUNBOOK drill (stale data, protection-unconfirmed, duplicate approval, disconnect) completed and logged

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Look-ahead / repaint discovered post-hoc | HIGH | Freeze protocol; add prefix-invariance test; re-run all candidates clean; demote tainted results to exploratory |
| Assume-TP-first edge | MEDIUM | Re-resolve with 1m data or SL-first; publish sensitivity; reject if edge was ambiguous-bar-dependent |
| Isolated optimum / holdout peeked | HIGH | Burn holdout; roll new window; require plateau + walk-forward; reset selection |
| Costs-after-selection | MEDIUM | Re-screen all candidates net of full costs; tighten universe to survivors |
| Round-up sizing shipped | MEDIUM | Hotfix to floor+reject (risk-reducing, allowed); audit past fills for cap breaches |
| Hard-coded filters / legacy endpoints | MEDIUM | Switch to dynamic exchangeInfo + Algo endpoints; re-verify vs current docs; replay paper suite |
| Orphan order triggers naked position | HIGH | Flatten per RUNBOOK; cancel orphans; post-mortem; harden reconciler + add alerting |
| Duplicate approval double order | MEDIUM–HIGH | Reduce to planned size immediately; fix idempotency; add duplicate-callback test |
| Stale-data signals | MEDIUM | Invalidate affected signals; add warm-up/staleness gates; backfill continuity checks |
| OI window missed | HIGH (irreversible) | Start collector immediately; defer OI hypotheses until coverage suffices; never fake history |
| Revenge sizing breach | HIGH | Enter DAILY_STOP/SAFE_MODE; review journal attribution; reaffirm no-target policy |
| Notebook-as-validation | MEDIUM | Re-run through canonical engine; quarantine notebook-only claims |
| Prod spec bypass | MEDIUM | Retro-version the change; revalidate; reinstate registry enforcement in CI |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 1 Look-ahead (unclosed/future confirmation) | Phase 1 — spec freeze + engine | Prefix-invariance test green; acceptance gate "no material look-ahead" |
| 2 Repainting | Phase 1 — golden fixtures + immutable IDs | Restart-duplication test; re-run experiment ID byte-identical |
| 3 Intrabar SL/TP ordering | Phase 0 (1m data) → Phase 1 (resolver) | Ambiguous-bar share + SL-first sensitivity in every report |
| 4 Isolated optimum | Phase 1 — research protocol | Neighborhood-stability plots; walk-forward agreement |
| 5 Holdout/single-symbol dependence | Phase 1 — protocol; Phase 2 — forward holdout | Holdout-access log; live-5 slice reported separately; kill-gate review |
| 6 Costs after selection | Phase 1 — cost model frozen first | All experiment records carry cost fields; 2× slippage sensitivity |
| 7 Round-UP sizing | Phase 1 (parity) → Phase 3 (live) | Adversarial qty unit tests; realized-risk logs |
| 8 Hard-coded filters | Phase 0B (metadata) → Phase 3 (revalidation) | No filter constants; plan carries metadata snapshot timestamp |
| 9 Legacy STOP_MARKET endpoint | Phase 3 — execution | Protection confirmations carry Algo order IDs; API re-verified vs current docs |
| 10 closePosition/reduceOnly/mode misuse | Phase 3 — execution + fixtures | Both position modes + partial-fill TP tests green |
| 11 Orphan protective orders | Phase 3 (reconciler+sweeper); soak in Phase 2 | Orphan-injection drill; open-algo-count dashboard |
| 12 Duplicate approval | Phase 2 (paper approval path) → Phase 3 | 5× duplicate-callback test = one intent; token-expiry test |
| 13 Stale data + warm-up | Phase 0 (pipeline) → Phase 2 (chaos tests) | Startup/reconnect drills; staleness TTL enforced; warm-up gate logged |
| 14 OI 30-day window | Phase 0 — collector day one | OI snapshots flowing with coverage dashboard |
| 15 Daily-profit forcing | All phases (policy + DAILY_STOP in Phase 3) | Journal attribution review; zero-trade-day acceptance at gates |
| 16 Vectorized-as-canonical | Phase 1 — engine + fixtures | Notebook/engine parity test; notebook-only claims quarantined |
| 17 Prod spec bypass | Phase 1 (registry/versioning) → enforced 2/3 | CI rejects unversioned semantic change; version-in-signal-ID audit |

## Sources

- Repo canonical docs: `docs/01_ENGINEERING_PRINCIPLES.md` (determinism, no-AI, fail-closed, no-repaint, immutable signal IDs), `docs/backtest/BACKTEST_SPEC.md` (§3–§11 acceptance gates, §13 canonical-engine rule), `docs/trading/RISK_MANAGEMENT.md` (§7 no-revenge, §11 quantization, §12 constraint snapshot), `docs/trading/EXECUTION_SPEC.md` (Algo-Order migration §2, lifecycle §3–§6, idempotency §7, modes §8, reconciliation/orphans §9, capacity §12), `docs/architecture/DATA_PIPELINE.md` (OI 30-day window §3, warm-up §5, collector §9/§12), `docs/integration/TELEGRAM.md` (one-time token §3, at-least-once §6, no auto-approve §5), `.planning/PROJECT.md` (kill gate D013, no daily target D010, quantization/approval/fail-closed constraints)
- Binance official references as cited in-repo (to re-verify before implementation; not fetched at research time): USDⓈ-M Exchange Information (filters), Algo/New-Algo-Order trade API (`closePosition` constraints), Futures changelog (STOP_MARKET migration, `MAX_NUM_ALGO_ORDERS` removal / 200-conditional limit), User Data Streams (WS preference)

---
*Pitfalls research for: Deterministic Binance Futures research + semi-automated execution*
*Researched: 2026-09-19*
