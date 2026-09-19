# Candidate Family B — Breakout + Retest

> Status: HYPOTHESIS — **NOT FROZEN**
>
> This sheet is one of three mutually-comparable candidate families (A/B/C). All three share the same 7-slot template, the same TBD discipline, and the same D012 footer.
> Values remain `TBD` until the research methodology is exercised on real data per `docs/research/RESEARCH_PROTOCOL.md` §0–§4 and §1 (anti-overfitting rules R1–R6).
> Source material: `docs/research/TRADING_STRATEGY_RESEARCH.md` §4.3 (breakout candidates B1–B4), §4.4 (retest), §5.2 (Candidate B), §6 (entry/SL/TP candidates), §15 (research questions Q1–Q12), §16 (anti-overfitting rules R1–R6).
> Cross-references: `docs/strategy/TRADING_STRATEGY_SPEC.md` (TBD slot template), `docs/configuration/CONFIGURATION.md` §3 (parameter registry examples).
> Sibling sheets: `docs/research/families/trend-pullback.md` (Family A), `docs/research/families/range-mr.md` (Family C).

## 1. Informal definition (prose hypothesis)

**Hypothesis:** if price consolidates against a structure level, breaks out, and then returns to retest the broken level without breaking down through it, the retest entry filters out a fraction of false breakouts compared to entering immediately at the breakout bar.

The informal definition does NOT pick which breakout definition (close / wick+close / volume-confirmed / multi-bar), which retest definition (touch / close / rejection-candle / structure reclaim), or which entry timing (zone limit / confirmation close / hybrid). Those are the machine-detectable candidates in §2 and the explicit alternatives in §3. Picking one is a Stage B baseline that must clear backtest plus out-of-sample evidence before any family can be promoted.

## 2. Machine-detectable definition (closed-bar composition)

The strategy is composed from a 4H directional frame and a 1H breakout-plus-retest sequence. Decisions are taken on closed bars only (no unclosed pivots, no current-candle high/low).

### 2.1 Breakout definition candidates (transcribed from `TRADING_STRATEGY_RESEARCH.md` §4.3)

Each row is a separate testable alternative; they are never blended inside a single 4H-direction × 1H-zone frame.

- **B1 — Close breakout.** `close > resistance_zone_upper_bound` (LONG); `close < support_zone_lower_bound` (SHORT). The bar that closes outside the zone is the breakout bar.
- **B2 — Wick + close confirmation.** `high > resistance_zone_upper_bound AND close > resistance_zone_upper_bound` (LONG); symmetric for SHORT. The bar that prints a wick through and closes through is the breakout bar.
- **B3 — Volume-confirmed breakout.** B1 condition AND `volume / avgVolume(lookback) > breakout_volume_threshold` (LONG); symmetric for SHORT. Threshold value `TBD` per §6.
- **B4 — Multi-bar confirmation.** Two consecutive closes satisfy B1 (`close[t-1] > resistance AND close[t] > resistance` for LONG); symmetric for SHORT. The second close is the breakout bar.

### 2.2 Retest definition candidates (transcribed from `TRADING_STRATEGY_RESEARCH.md` §4.4)

After the breakout bar, the family waits up to `retest_window_bars` (value `TBD`) for one of the following retest signals (LONG; symmetric for SHORT):

- **R1 — Touch.** A 1H bar's low is inside the broken zone (`low ≤ resistance_zone_upper_bound AND low ≥ resistance_zone_lower_bound`).
- **R2 — Close-into-zone.** A 1H bar's close is inside the broken zone.
- **R3 — Rejection candle.** A 1H bar touches the zone AND the next 1H bar closes back outside the zone in the direction of the breakout (LONG: close > resistance_zone_upper_bound on bar `t+1`).
- **R4 — Reclaim without breakdown.** A 1H bar's low enters the broken zone but the close does not close back below the original resistance (LONG); symmetric for SHORT.

The break → return → no-breakdown-reclaim sequence is a single logical step in this family; the four retest alternatives above are mutually exclusive candidates inside that step, not blended alternatives.

### 2.3 Timeframe mapping

| Layer | Timeframe | Role |
|---|---|---|
| Direction / regime | 4H | Provides HH/HL or LH/LL context; the 4H direction gates whether long-biased breakouts (above resistance) or short-biased breakouts (below support) are admissible |
| Zone + breakout + retest | 1H | B1–B4 above, R1–R4 above |
| Entry-refinement (optional) | 15M | Only for confirmation candle; NOT for zone or breakout decisions |
| Execution simulation | 1m | Per `RESEARCH_PROTOCOL.md` §3 (Strategy timeframe vs execution timeframe); the only place intrabar order behavior is modeled |

15M is optional; 1m is execution-simulation only. No layer may make a strategy decision off a timeframe not listed above.

### 2.4 4H-direction gate

The 4H direction is defined per the same R1/R2/R3 alternatives as Family A's 4H regime. The must-test set for Family B is **R1 only** (structure-only); R2/R3 are §3 alternative rows. A breakout that runs against the 4H direction is **inadmissible** for this family — no counter-trend breakout trades in this sheet. Mixed-direction breakouts are reported separately as a §3 alternative (B5 counter-trend) only after the with-direction variants clear backtest plus OOS.

## 3. Alternative definitions (competing rows, never blended)

Each row below is a separate testable alternative. The Stage B baseline is the **mandatory reference alternative** every other row is compared against; no row may be promoted as the selection without first clearing backtest plus out-of-sample evidence per `RESEARCH_PROTOCOL.md` §4 (acceptance methodology) and §5 (parameter-registry linkage).

| ID | Combination | What it adds over Stage B baseline |
|---|---|---|
| Stage B baseline | B1 (close breakout) + R1 (touch retest) + E2 (zone + ATR buffer entry) + S3 (zone invalidation SL) + T1 (fixed-R TP) | Reference; never removed from the matrix |
| B-breakout-1 | B1 | Close breakout only (Stage B canonical) |
| B-breakout-2 | B2 | Wick + close confirmation |
| B-breakout-3 | B3 | Volume-confirmed breakout |
| B-breakout-4 | B4 | Two-bar close confirmation |
| B-retest-1 | B1 + R1 | Close breakout + touch retest (Stage B canonical) |
| B-retest-2 | B1 + R2 | Close breakout + close-into-zone retest |
| B-retest-3 | B1 + R3 | Close breakout + rejection-candle retest |
| B-retest-4 | B1 + R4 | Close breakout + reclaim-without-breakdown |
| B-direction-1 | B2 + R3 | Wick+close + rejection (fewer-false-breakout variant) |
| B-direction-2 | B3 + R3 | Volume-confirmed + rejection (tighter filter) |
| B-counter-trend | B1 + R1 + 4H-counter-trend allowed | Counter-trend breakout, only admissible after B-direction rows clear |

The full cross-product is intentionally **not** enumerated here — that is the §7 backtest path's job. The rows above are the **must-test** set per `TRADING_STRATEGY_RESEARCH.md` §4.3, §4.4, and §5.2 ("Điều phải test") plus the Q3–Q8 must-test pointers.

### 3.1 Variants table (per-family sheet cosmetic)

| Variant ID | Breakout | Retest | Entry code | SL code | TP code | Status |
|---|---|---|---|---|---|---|
| Stage B baseline | B1 close | R1 touch | E2 | S3 | T1 | reference — pending backtest + OOS |
| B-retest-1 | B1 close | R1 touch | E2 | S3 | T1 | candidate — pending backtest + OOS |
| B-retest-2 | B1 close | R2 close-into-zone | E2 | S3 | T1 | candidate — pending backtest + OOS |
| B-retest-3 | B1 close | R3 rejection-candle | E3 | S3 | T1 | candidate — pending backtest + OOS |
| B-retest-4 | B1 close | R4 reclaim-no-breakdown | E4 | S3 | T2 next structure | candidate — pending backtest + OOS |
| B-direction-1 | B2 wick+close | R3 rejection-candle | E3 | S3 | T1 | candidate — pending backtest + OOS |
| B-direction-2 | B3 volume-confirmed | R3 rejection-candle | E3 | S3 | T1 | candidate — pending backtest + OOS |
| B-breakout-4 | B4 two-bar | R1 touch | E2 | S3 | T1 | candidate — pending backtest + OOS |
| B-counter-trend | B1 close | R1 touch | E2 | S3 | T1 | candidate — pending backtest + OOS |

Selection-implying adjectives are intentionally absent — see `## V1 family selection` footer below.

## 4. Advantages / Disadvantages

### 4.1 Why this family might earn backtest admission

- **Fewer-false-breakout rationale.** Entering at the breakout bar commits capital before the market has confirmed the break; entering on a retest rejects trades where the breakout bar's follow-through never materialized. The fewer-false-breakout hypothesis is the core rationale for separating this family from Family A — it is an explicit hypothesis to be tested, not a pre-judgment of the family's standing among A and C per `TRADING_STRATEGY_RESEARCH.md` §5.2.
- **Closed-bar confirmation rule.** R3 (rejection candle) and R4 (reclaim without breakdown) require a subsequent 1H bar to close in the breakout direction; this closed-bar rule prevents the retest from being triggered on the in-progress bar — by construction zero repaint on the retest decision.
- **Stage B comparison.** The Stage B baseline is a smaller combinatorial change from Family A's Stage A baseline (B1 ≈ P1 with a wick/close rule; R1 ≈ zone touch) than a true regime swap. Cross-family comparison at the same split is therefore feasible per `RESEARCH_PROTOCOL.md` §4 (acceptance methodology) without confounding regime effects.

### 4.2 Why this family is at risk of under-signaling or under-performing

- **Retest-waiting repaint risk.** A naïve "wait for retest" implementation can repaint: the in-progress bar's high or low may momentarily enter the broken zone, the strategy flags "retest!", and then the bar closes outside the zone. The closed-bar confirmation rule (R3 / R4 require bar `t+1` close) eliminates this — but only if the implementation enforces closed-bar strictness at every retest gate. Two retest variants with different confirmation rules are not directly comparable; the §7 backtest path must report per-variant.
- **False-positive at low-liquidity zones.** A breakout through a zone that has been touched only once (low `zone_min_touches`) is more likely to be a one-time sweep than a structural break. The Stage B baseline inherits `zone_min_touches` from `CONFIGURATION.md` §3 — the value is `TBD` per §6 and must be calibrated on the development split.
- **Counter-trend variants excluded by default.** A breakout against the 4H direction is inadmissible in the default variant set; this caps the trade count in trends and may starve the dataset of statistical power per `RESEARCH_PROTOCOL.md` §4. The B-counter-trend alternative row is a §3 diagnostic only and is NOT admitted to the comparison matrix until the with-direction variants clear.
- **Hypothesis under-specification risk.** "Retest filters false breakouts" is qualitatively plausible but quantitatively unspecified until backtest: the fewer-false-breakout advantage must be net positive after the cost of missed trades (the trades where the breakout ran without a retest). This is a Stage B measurement, not a pre-backtest assumption.

### 4.3 Pre-committed entry-quality metrics (Family B only)

Per `TRADING_STRATEGY_RESEARCH.md` §6.1 ("Research metric"). These are the entry-quality metrics this family commits to reporting alongside win-rate and expectancy. Each metric is computed at the variant level (Stage B baseline, B-retest-1…4, B-direction-1…2, B-breakout-4, B-counter-trend):

- **Fill rate** — fraction of limit-zone entries filled at the intended retest zone.
- **Missed-trade rate** — fraction of detected setups where the entry was never reached before expiry / invalidation. For Family B, "missed" also includes "breakout ran without a retest within `retest_window_bars`" — this is a *deliberate* family-B miss that does not exist in Family A.
- **Entry slippage** — `effective_entry - intended_entry`, in price and in ATR units.
- **Post-touch MFE** — maximum favorable excursion measured from retest touch, irrespective of fill.
- **Post-touch MAE** — maximum adverse excursion measured from retest touch, irrespective of fill.

These five metrics are pre-committed so the Stage B baseline and every B-retest-* / B-direction-* variant is comparable on the same axes. A "winning" variant (per D012 pending backtest + OOS) must clear all five axes, not just expectancy.

## 5. Look-ahead-bias analysis

Per `RESEARCH_PROTOCOL.md` §3 (closed-candle rule) and `TRADING_STRATEGY_RESEARCH.md` §9.1 (no-repaint baseline).

The look-ahead questions below are the family-B binding answers:

| # | Question | Family B binding rule |
|---|---|---|
| 1 | Breakout confirmation bar | The breakout bar is the bar at which B1/B2/B3/B4 first fires on a **closed** 1H bar. The breakout cannot be flagged on an in-progress bar. |
| 2 | Retest confirmation bar | The retest is confirmed at the close of the bar that satisfies R1/R2/R3/R4 on a **closed** 1H bar. R3 and R4 in particular require `t+1`'s close to be a closed bar, not the in-progress `t+1`. |
| 3 | Unclosed pivots / unconfirmed zones | NEVER used. Zone bounds are computed only from closed 1H / 4H bars; a zone formed on a still-in-progress bar is inadmissible. |
| 4 | Repaint risk | Closed-bar only — by construction zero repaint on the breakout / retest decision when the implementation enforces closed-bar strictness at every gate (B1–B4 and R1–R4). The `retest_window_bars` countdown starts at the breakout bar's close; an implementation that starts the countdown at the breakout bar's open is repainting and is inadmissible. |
| 5 | 4H direction source | Structure-only (R1) by default for Family B's must-test set; R2/R3 are §3 alternative rows for Family B's regime sub-matrix. Closed-bar rule applies uniformly. |

### 5.1 Zone-boundary touch semantics (RSCH-02/adjacency flagged assumption)

Per the phase assumption delta — Family B's binding rule:

- **Merge.** If two consecutive zones overlap (distance between zone midpoints < combined half-widths), the zones are merged into a single zone whose bounds are the union. (Default for Stage B baseline.)
- **Collide.** If two zones touch at exactly one price level (distance between zone midpoints == combined half-widths to machine precision), the touch is treated as a **single zone** for entry-zone classification but as **two zones** for invalidation purposes.
- **Separate.** If the gap between zones is positive (distance > combined half-widths), the zones are independent and an entry in the gap does not satisfy R1/R2/R3/R4.

For Family B specifically, the breakout bar is the first bar whose close / wick exceeds the merged-or-collided zone's outer bound; the retest is the first bar inside the `retest_window_bars` whose low / close enters the zone. Variants B-retest-1…4 and B-direction-1…2 must publish which merge / collide / separate rule they use. Two variants with different boundary semantics are not directly comparable; the §7 backtest path must report per-variant.

### 5.2 Single-setup and zero-setup behavior (RSCH-02/empty flagged assumption)

Per the phase assumption delta — Family B's binding rule:

- **Single-setup.** When exactly one qualifying breakout + retest exists on a symbol at decision time, the family emits exactly one signal with that setup's parameters. No batch dedup, no ranking across setups. If two qualifying zones break out on the same 1H bar, only the first detected breakout counts; the second is reported as a missed-trade in the same `valid_until` window.
- **Zero-setup.** When zero setups qualify on a symbol at decision time, the family emits NO_TRADE for that symbol for that decision cycle. NO_TRADE is a first-class outcome per `RESEARCH_PROTOCOL.md` §3 and is journaled separately per `data/DATA_MODEL.md` §6 (NO_TRADE slice).

A variant with "no signals for N days" is NOT a bug — it is the family being correctly silent. Forcing a signal in that window violates R5 ("Không target daily PnL"). Family B is expected to have **fewer** signals than Family A by construction (the retest filter rejects some breakouts), and statistical-power concerns per `RESEARCH_PROTOCOL.md` §4 are real; the §7 backtest path reports the trade-count per variant so this can be diagnosed explicitly.

## 6. Testable parameters

Testable parameters for this family map onto the parameter-registry examples in `CONFIGURATION.md` §3 ("Strategy parameters"). Each parameter below is a placeholder; the **value** is TBD until exercised on real data per `RESEARCH_PROTOCOL.md` §0. The Phase 3 registry enforces this — no backtest run may use an unregistered parameter set (D-07).

| Parameter | Meaning | Source | Status |
|---|---|---|---|
| `breakout_variant` | B1 / B2 / B3 / B4 selection | `TRADING_STRATEGY_RESEARCH.md` §4.3 candidates | enum TBD per §3 |
| `breakout_volume_threshold` | B3 volume ratio cutoff | `TRADING_STRATEGY_RESEARCH.md` §4.3 + Q3 | value TBD |
| `breakout_confirmation_bars` | B4 consecutive-closes count | `CONFIGURATION.md` §3 list + Q3 | value TBD |
| `retest_variant` | R1 / R2 / R3 / R4 selection | `TRADING_STRATEGY_RESEARCH.md` §4.4 | enum TBD per §3 |
| `retest_window_bars` | Maximum bars after breakout for retest validity | `TRADING_STRATEGY_RESEARCH.md` §4.4 + Q4 | value TBD |
| `retest_depth_atr` | Maximum distance from zone for retest validity | §4.4 "Maximum distance từ zone" | value TBD |
| `zone_min_touches` | Minimum swing pivots inside the lookback to qualify a zone | `TRADING_STRATEGY_RESEARCH.md` §4.2 variables | value TBD |
| `zone_tolerance_atr` | Volatility-adjusted zone half-width in ATR units | `CONFIGURATION.md` §3 list + §4.2 | value TBD |
| `entry_buffer_atr` | E2 buffer from zone edge | `CONFIGURATION.md` §3 list | value TBD |
| `sl_buffer_atr` | S3 zone-invalidation ATR buffer | `CONFIGURATION.md` §3 list | value TBD |
| `minimum_rr` | Minimum risk:reward for a setup to be admitted | `CONFIGURATION.md` §3 + §6.3 constraint + Q8 | value TBD |
| `signal_expiry_hours` | Setup validity window (UTC) | `CONFIGURATION.md` §3 list | value TBD |
| `risk_rate` | Per-trade equity fraction | `TRADING_STRATEGY_RESEARCH.md` §7.1 baseline | value TBD per §7 |
| `minimum_risk_utilization_after_rounding` | Realized-risk / intended-risk floor (60% baseline per AGENTS.md Quantization) | `CONFIGURATION.md` §3 list | value TBD per §7 |

If the backtest run reveals that the trade-off is **which** breakout / retest variant to pick, the variant enums are the parameters that have to be swept — not a numeric value within a single variant. Variant-level sweeps are valid per `RESEARCH_PROTOCOL.md` §5 (parameter-registry linkage) only when the variant IDs are listed as discrete parameter values inside a registered set.

## 7. Backtest path

Per `RESEARCH_PROTOCOL.md` §0–§7 and `BACKTEST_SPEC.md` §11 (Acceptance gates) + §7 (Dataset splits).

### 7.1 Stage mapping

- **Stage A — Baseline trend strategy** (`TRADING_STRATEGY_RESEARCH.md` §14) belongs to Family A; Family B references Stage A only as a cross-family benchmark, never as a within-family baseline.
- **Stage B — Breakout/retest** (`TRADING_STRATEGY_RESEARCH.md` §14). The Stage B baseline is the **mandatory reference alternative**: every B-retest-* / B-direction-* / B-breakout-4 variant is reported alongside the Stage B row. Removing Stage B from the matrix is a §4 gate violation.
- **Stage C — Range strategy** belongs to Family C.
- **Stage D — Context features** (`TRADING_STRATEGY_RESEARCH.md` §14). Funding, OI, taker flow, volatility regime, session/time-of-day are evaluated as **incremental-value tests** against Family B's Stage B baseline — never as required inputs. OI is experimental-only until the self-collected dataset is long enough (`§8.2` and `§20` of the research doc).

### 7.2 Cost model (transcribed verbatim from `RESEARCH_PROTOCOL.md` §2)

- Entry fee: per Binance USDⓈ-M fee schedule; value TBD per exchange-snapshot.
- Exit fee: same.
- Funding: accounted per funding event held overnight; model `TBD` per §2.
- Slippage: `effective_entry = intended_entry + slippage` (never zero by default); value TBD per §2 cost calibration; identical in backtest / paper / live per §2 "floor-only quantization identical across modes".
- Spread / fill: per `RESEARCH_PROTOCOL.md` §2; value TBD.
- Retest re-entry slippage: a Family B-specific line item. When the retest fires, the entry order is placed at the zone; if the order fills partway through the zone (e.g. fill at zone top instead of zone bottom), the entry slippage is computed against the **fill price**, not the zone mid. This is identical to Family A's slippage model; the variant just changes where the order sits on the bar timeline.

### 7.3 Execution simulation (transcribed from `RESEARCH_PROTOCOL.md` §3)

- Closed-candle rule (above) — the only decision layer.
- Strategy decision: 4H direction + 1H breakout/retest; execution simulation at 1m.
- Intrabar ambiguity: fixed-before-evaluation tie-break rule (conservative: assume adverse level hit first; details `TBD` per §3 of RESEARCH_PROTOCOL).
- Limit-order checklist with **no retroactive fill after expiry** per §3 of RESEARCH_PROTOCOL. For Family B, the limit order's expiry coincides with `retest_window_bars` past the breakout bar — the order expires regardless of whether a partial fill occurred.
- NO_TRADE is a first-class outcome, journaled separately per `DATA_MODEL.md` §6.

### 7.4 Acceptance gates

Per `RESEARCH_PROTOCOL.md` §4 (acceptance methodology) and `BACKTEST_SPEC.md` §11:

- Sample size ≥ `TBD` (research-baseline range to explore per `BACKTEST_SPEC.md` §10). Note: Family B's per-variant trade count is expected to be lower than Family A's because the retest filter is a stricter gate; the sample-size gate must be evaluated against the **pooled** Stage B baseline + variant set, not against a single variant.
- Expectancy positive after cost in **Development** AND **Validation** splits.
- Profit factor not concentrated in <5 trades.
- Drawdown within `TBD` envelope per risk register.
- Robustness: not dependent on a single parameter value, single symbol, single period; per `BACKTEST_SPEC.md` §11 and `TRADING_STRATEGY_RESEARCH.md` §16 R1–R6.
- Operational: closed-bar runnable, expiry handled, SL/TP auto-managed post-approval, audit log per signal.
- Comparative gates: the Stage B baseline's metrics must be **at least as good as** Family A's Stage A baseline on the same split for Family B to be a credible candidate. If Family B's baseline is materially worse, the family does not earn admission to the Stage D feature-incremental-value tests.

A "winning" variant is one that clears **all** acceptance gates — not just expectancy. The kill gate is `RESEARCH_PROTOCOL.md` §4 + D013 (three families × six months of forward evidence).

### 7.5 MFE / MAE reporting

Per `TRADING_STRATEGY_RESEARCH.md` §11.3 and §12 (System Performance vs User Performance): MFE and MAE are reported per `research/TRADING_STRATEGY_RESEARCH.md` §11.3 with time-to-MFE and time-to-MAE for every trade, separately from win-rate. Family B's MFE / MAE are measured **from the retest touch** (the family-specific anchor) — this is a Family B measurement choice that is comparable across Family B variants but is NOT directly comparable to Family A's "from pullback touch" anchor without an explicit bridge metric. The User-vs-System performance split is reported at the §12 slice.

---

## V1 family selection: TBD (D012)

This sheet does NOT declare Breakout+Retest as the V1 family. The V1 family is decided after **all three families** (A, B, C) clear backtest plus out-of-sample evidence per `RESEARCH_PROTOCOL.md` §4 + §5 (loader contract) and the kill gate D013 (three families × six months of forward evidence). Selecting Breakout+Retest before Families A and C also pass is a `D012` violation.

Comparative statements in this sheet carry the **pending backtest + OOS** qualifier where present. Selection-implying adjectives ("best", "preferred", "optimal", "chosen", "winner") are absent by construction; if any appear in future revisions, they MUST be qualified with the pending-backtest-plus-OOS phrase per D-08.

## Open questions

Per `TRADING_STRATEGY_RESEARCH.md` §15 (Research Questions Q1–Q12). This family's open questions are:

- **Q3 — Breakout definition.** Which breakout (B1 close / B2 wick+close / B3 volume-confirmed / B4 two-bar) is the Stage B baseline? — Gate input for §3.
- **Q4 — Retest definition.** Which retest (R1 touch / R2 close-into-zone / R3 rejection-candle / R4 reclaim-no-breakdown) is the Stage B baseline? — Gate input for §3. The retest-window bar count and depth cap are gate inputs too.
- **Q5 — Entry.** Which E-code (E1 level retest / E2 zone + ATR / E3 confirmation close / E4 hybrid) is the Stage B baseline entry? — Gate input for §3. The hybrid E4 is the candidate variant B-retest-4 entry.
- **Q6 — Stop.** Which S-code (S1 swing / S2 structure + ATR / S3 zone invalidation) is the Stage B baseline SL? — Stage B baseline uses S3 (zone invalidation on the other side of the broken zone); the gate input is the S-code.
- **Q7 — TP.** Which T-code (T1 fixed-R / T2 next structure / T3 hybrid) is the Stage B baseline TP? — Gate input for §3.
- **Q8 — Minimum R:R.** Reject setups whose target structure yields `risk:reward < minimum_rr`? Value TBD per §6.

Family A's Q1 (trend definition) is NOT directly answered here — Family B inherits the same R1 structure-only regime as Family A's must-test set. Family C's Q9 (regime filter) is NOT directly answered here — Family B's 4H direction gate is per §2.4.

## Acceptance status

- Stage B baseline implemented: `NO`
- B-retest-* / B-direction-* / B-breakout-4 / B-counter-trend variants implemented: `NO`
- Backtested on the same split as Families A and C: `NO`
- Out-of-sample validated: `NO`
- Forward tested: `NO`
- Approved for live human-approved trading: `NO`

## Implementation neutrality

The family spec is technology-independent. Python is the project implementation language, but family semantics must remain expressible as deterministic inputs/outputs and must not depend on pandas, Polars, notebooks, network calls, or Binance SDK objects. See `docs/strategy/TRADING_STRATEGY_SPEC.md` "Implementation neutrality" footer (this family sheet mirrors it).
