# Candidate Family A — Trend Pullback

> Status: HYPOTHESIS — **NOT FROZEN**
>
> This sheet is one of three mutually-comparable candidate families (A/B/C). All three share the same 7-slot template, the same TBD discipline, and the same D012 footer.
> Values remain `TBD` until the research methodology is exercised on real data per `docs/research/RESEARCH_PROTOCOL.md` §0–§4 and §1 (anti-overfitting rules R1–R6).
> Source material: `docs/research/TRADING_STRATEGY_RESEARCH.md` §5.1 (Candidate A), §6 (entry/SL/TP candidates), §15 (research questions Q1–Q12), §16 (anti-overfitting rules R1–R6).
> Cross-references: `docs/strategy/TRADING_STRATEGY_SPEC.md` (TBD slot template), `docs/configuration/CONFIGURATION.md` §3 (parameter registry examples).

## 1. Informal definition (prose hypothesis)

**Hypothesis:** if the higher timeframe (4H) is in a directional regime and price pulls back to a previously broken structure level or a moving-average / zone confluence, the trade idea is "enter in the direction of the larger trend at a structurally meaningful pullback, with stop on the wrong side of that structure".

The pullback-with-larger-trend idea only makes sense under a 4H regime that is itself defined deterministically. The informal definition does NOT pick which regime detector is used (structure, EMA, ATR-filtered structure, etc.) — those are the machine-detectable candidates in §2 and the explicit alternatives in §3. Picking one of them is a Stage A baseline (see §7) that must clear backtest plus out-of-sample evidence before any family can be promoted.

## 2. Machine-detectable definition (closed-bar composition)

The strategy is composed from a 4H regime detector and a 1H setup detector. Decisions are taken on closed bars only (no unclosed pivots, no current-candle high/low).

### 2.1 4H regime detector (Trend Pullback needs a trend)

Three regime candidates are transcribed from `TRADING_STRATEGY_RESEARCH.md` Q1:

- **R1 — Structure-only.** 4H regime = `Higher High + Higher Low` for LONG; `Lower High + Lower Low` for SHORT. Swing lookback N (left/right bars) is `TBD` per risk register; close-bar confirmation rule is `TBD` per §5 look-ahead analysis.
- **R2 — EMA-only.** 4H regime = `close > EMA(period)` for LONG; `close < EMA(period)` for SHORT. EMA period `TBD` per §6; warm-up rules per `RESEARCH_PROTOCOL.md` §3 (warm-up).
- **R3 — Structure + EMA.** 4H regime requires BOTH (a) market-structure HH/HL or LH/LL over the swing lookback AND (b) close-vs-EMA alignment. The combination rule (AND / OR / weighted) is `TBD` per §6.

A regime candidate that fails to produce a stable bull/bear/neutral split on the 4H development slice is treated as **inadmissible** for this family (see §5 look-ahead + §7 backtest path).

### 2.2 1H setup detector (the pullback entry)

The 1H setup is a pullback to a structurally meaningful level in the direction of the 4H regime. The structural level is a **support zone** (LONG) or **resistance zone** (SHORT) built from swing highs/lows inside a volatility-adjusted tolerance (`TRADING_STRATEGY_RESEARCH.md` §4.2). Pullback definitions to test:

- **P1 — Zone touch.** 1H bar's low ≤ zone upper bound AND 1H bar's low ≥ zone lower bound (LONG); symmetric for SHORT.
- **P2 — Zone close.** 1H bar closes inside the zone (LONG: close ≥ zone lower bound AND close ≤ zone upper bound); symmetric for SHORT.
- **P3 — Zone + EMA confluence.** P1 or P2 AND 1H close aligns with an EMA on the 1H chart.
- **P4 — Zone + volume confluence.** P1 or P2 AND volume ratio `volume / avgVolume(lookback)` exceeds a threshold (threshold `TBD`).

Each Px is a separate testable row in §3 — they are never blended inside a single 4H-direction × 1H-zone frame.

### 2.3 Timeframe mapping

| Layer | Timeframe | Role |
|---|---|---|
| Regime / context | 4H | R1/R2/R3 above |
| Setup / entry zone | 1H | P1/P2/P3/P4 above |
| Entry-refinement (optional) | 15M | Only for confirmation candle; NOT for regime or zone decisions |
| Execution simulation | 1m | Per `RESEARCH_PROTOCOL.md` §3 (Strategy timeframe vs execution timeframe); the only place intrabar order behavior is modeled |

15M is optional; 1m is execution-simulation only. No layer may make a strategy decision off a timeframe not listed above.

## 3. Alternative definitions (competing rows, never blended)

Each row below is a separate testable alternative. The Stage A baseline (see §7) is the **mandatory reference alternative** every other row is compared against; no row may be promoted as the selection without first clearing backtest plus out-of-sample evidence per `RESEARCH_PROTOCOL.md` §4 (acceptance methodology) and §5 (parameter-registry linkage).

| ID | Combination | What it adds over Stage A baseline |
|---|---|---|
| Stage A baseline | R1 (structure-only) + P1 (zone touch) + E2 (zone + ATR buffer entry) + S2 (structure + ATR buffer SL) + T1 (fixed-R TP) | Reference; never removed from the matrix |
| A1 | R1 + P1 | Structure-only with zone touch (Stage A canonical) |
| A2 | R1 + P2 | Structure-only with zone close (filters wicks that don't close inside zone) |
| A3 | R1 + P3 | Structure + 1H EMA confluence on pullback |
| A4 | R1 + P4 | Structure + volume confluence on pullback |
| A5 | R2 + P1 | EMA-only regime with zone touch |
| A6 | R3 + P3 | Structure+EMA regime with zone+EMA pullback (most-confluent variant) |

The full cross-product is intentionally **not** enumerated here — that is the §7 backtest path's job. The rows above are the **must-test** set per `TRADING_STRATEGY_RESEARCH.md` §5.1 ("Các phiên bản cần test") plus the regime-detector must-test set per Q1. Any single-row claim of superiority requires backtest plus OOS evidence per D012; no row is preferred yet (pending backtest + OOS).

### 3.1 Variants table (per-family sheet cosmetic)

| Variant ID | Regime | Pullback | Entry code | SL code | TP code | Status |
|---|---|---|---|---|---|---|
| Stage A baseline | R1 structure | P1 zone touch | E2 | S2 | T1 | reference — pending backtest + OOS |
| A1 | R1 structure | P1 zone touch | E2 | S2 | T1 | candidate — pending backtest + OOS |
| A2 | R1 structure | P2 zone close | E3 | S2 | T1 | candidate — pending backtest + OOS |
| A3 | R1 structure | P3 zone+EMA | E4 | S2 | T1 | candidate — pending backtest + OOS |
| A4 | R1 structure | P4 zone+volume | E2 | S2 | T1 | candidate — pending backtest + OOS |
| A5 | R2 EMA | P1 zone touch | E2 | S1 | T1 | candidate — pending backtest + OOS |
| A6 | R3 struct+EMA | P3 zone+EMA | E4 | S2 | T3 hybrid | candidate — pending backtest + OOS |

Selection-implying adjectives ("highest-ranked", "first-pick", "top-of-list") are intentionally absent by construction — see `## V1 family selection` footer below.

## 4. Advantages / Disadvantages

### 4.1 Why this family might earn backtest admission

- **Defined-stops hypothesis.** A swing-based or zone-based SL is structurally meaningful (CME Proper Position Size principle — risk is sized to the stop, not the other way around). The stop is on the wrong side of the structure that justified the entry, not a fixed percentage.
- **Trend-filter dependence.** A pullback in a trend is a different trade from a pullback in a range; the 4H regime filter formalizes this distinction. Filter ON is the only variant run by default; filter OFF (no regime gate) is a diagnostic A/B comparison per §7.
- **Closed-bar decisions only.** No repaint risk by construction — every P1/P2/P3/P4 decision references a closed 1H bar; every R1/R2/R3 decision references a closed 4H bar; intrabar 1m data is execution-only.

### 4.2 Why this family is at risk of under-signaling or under-performing

- **In-range under-signal risk.** When the 4H regime is neutral (range-bound or choppy), the regime filter is `TBD` per §2.1 — the default-admissible behavior is NO_TRADE for this family (Q9 pointer; see `TRADING_STRATEGY_RESEARCH.md` Q9). The family is silent in those windows; this is intentional (avoiding the "force a signal" failure mode) but it caps the per-month trade count.
- **Pullback definition sensitivity.** P1 (touch) vs P2 (close) materially changes fill behavior at zone boundaries — see §5 zone-boundary semantics. P3 and P4 add EMA / volume gates that further shrink the signal pool; statistical power per `RESEARCH_PROTOCOL.md` §4 (acceptance methodology) needs enough trades to clear uncertainty gates, and tight variants may starve the dataset.
- **Mean-reversion competitors.** A flat or choppy regime favors Family C (Range Mean-Reversion) more than Family A. A selection verdict cannot be made for Family A until Family C is also run on the same split — see D012 footer.

### 4.3 Pre-committed entry-quality metrics (Family A only)

Per `TRADING_STRATEGY_RESEARCH.md` §6.1 ("Research metric") — these are the entry-quality metrics this family commits to reporting alongside win-rate and expectancy. Each metric is computed at the variant level (Stage A baseline, A1, …, A6):

- **Fill rate** — fraction of limit-zone entries filled at the intended zone.
- **Missed-trade rate** — fraction of detected setups where the entry was never reached before expiry / invalidation.
- **Entry slippage** — `effective_entry - intended_entry`, in price and in ATR units.
- **Post-touch MFE** — maximum favorable excursion measured from zone touch, irrespective of fill.
- **Post-touch MAE** — maximum adverse excursion measured from zone touch, irrespective of fill.

These five metrics are pre-committed so the Stage A baseline and every A1–A6 variant is comparable on the same axes. A "winning" variant must clear all five axes, not just expectancy.

## 5. Look-ahead-bias analysis

Per `RESEARCH_PROTOCOL.md` §3 (closed-candle rule) and `TRADING_STRATEGY_RESEARCH.md` §9.1 (no-repaint baseline).

The look-ahead questions below are transcribed from `TRADING_STRATEGY_RESEARCH.md` §4.1 and §15; each answer is the family-A binding rule for that question.

| # | Question | Family A binding rule |
|---|---|---|
| 1 | Swing high/low left/right bars | Use closed bars only. Pivot N is defined as "the highest high in [t-N, t+N]" with t's right boundary at a **closed** bar; right-extension rule is `TBD` per §6 (options: fixed lookback, or no-right-lookback with delayed confirmation). |
| 2 | Swing "confirmed" timestamp | A swing is confirmed at the close of the bar at `t + N` (right lookback). Decision-making uses confirmed swings only. |
| 3 | Unclosed pivots | NEVER used. The system evaluates only closed 1H / 4H bars; no decision is made on the in-progress bar's high or low. |
| 4 | Repaint risk | Closed-bar only — by construction zero repaint on the regime / setup decision. The retest / entry candle confirmation step (§2.2 P3/P4) must also use closed 1H bars; a 15M confirmation candle is acceptable only when that 15M bar is closed. |
| 5 | 4H regime definition source | Structure, EMA, or structure+EMA — the choice is a §3 alternative row, not a §2 binding. The closed-bar rule applies uniformly. |

### 5.1 Zone-boundary touch semantics (RSCH-02/adjacency flagged assumption)

This is a **flagged assumption** that the slot template must state explicitly per the phase assumption delta. The semantics are:

- **Merge.** If two consecutive zones overlap (distance between zone midpoints < combined half-widths), the zones are merged into a single zone whose bounds are the union. (Default for Stage A baseline.)
- **Collide.** If two zones touch at exactly one price level (distance between zone midpoints == combined half-widths to machine precision), the touch is treated as a **single zone** for entry-zone classification but as **two zones** for invalidation purposes.
- **Separate.** If the gap between zones is positive (distance > combined half-widths), the zones are independent and an entry in the gap does not satisfy P1/P2.

Variants A1–A6 must publish which merge / collide / separate rule they use. Two variants with different boundary semantics are not directly comparable; the §7 backtest path must report per-variant.

### 5.2 Single-setup and zero-setup behavior (RSCH-02/empty flagged assumption)

This is a **flagged assumption** per the phase assumption delta. Behavior is explicit:

- **Single-setup.** When exactly one qualifying setup exists on a symbol at decision time, the family emits exactly one signal with that setup's parameters. No batch dedup, no ranking across setups.
- **Zero-setup.** When zero setups qualify on a symbol at decision time, the family emits NO_TRADE for that symbol for that decision cycle. NO_TRADE is a first-class outcome per `RESEARCH_PROTOCOL.md` §3 and is journaled separately per `data/DATA_MODEL.md` §6 (NO_TRADE slice).

A variant with "no signals for N days" is NOT a bug — it is the family being correctly silent. Forcing a signal in that window violates R5 ("Không target daily PnL").

## 6. Testable parameters

Testable parameters for this family map onto the parameter-registry examples in `CONFIGURATION.md` §3 ("Strategy parameters"). Each parameter below is a placeholder; the **value** is TBD until exercised on real data per `RESEARCH_PROTOCOL.md` §0. The Phase 3 registry enforces this — no backtest run may use an unregistered parameter set (D-07).

| Parameter | Meaning | Source | Status |
|---|---|---|---|
| `swing_lookback_left` / `swing_lookback_right` | Pivot left/right bars for swing detection | `CONFIGURATION.md` §3 list | value TBD; per-risk-register range to explore |
| `zone_min_touches` | Minimum number of swing pivots inside the lookback to qualify a zone | `TRADING_STRATEGY_RESEARCH.md` §4.2 variables | value TBD |
| `zone_tolerance_atr` | Volatility-adjusted zone half-width in ATR units | `CONFIGURATION.md` §3 list + §4.2 | value TBD |
| `zone_aging_bars` | Bars after which an un-touched zone is dropped | §4.2 "Khi nào zone mất hiệu lực" | value TBD |
| `entry_buffer_atr` | E2 buffer from zone edge | `CONFIGURATION.md` §3 list | value TBD |
| `sl_buffer_atr` | S2 ATR buffer below swing low / above swing high | `CONFIGURATION.md` §3 list | value TBD |
| `pullback_variant` | P1 / P2 / P3 / P4 selection | §2.2 | enum TBD per §3 |
| `regime_variant` | R1 / R2 / R3 selection | §2.1 | enum TBD per §3 |
| `minimum_rr` | Minimum risk:reward for a setup to be admitted | `CONFIGURATION.md` §3 + §6.3 constraint | value TBD |
| `signal_expiry_hours` | Setup validity window (UTC) | `CONFIGURATION.md` §3 list | value TBD |
| `risk_rate` | Per-trade equity fraction | `TRADING_STRATEGY_RESEARCH.md` §7.1 baseline (0.5% as research baseline) | value TBD per §7 |
| `minimum_risk_utilization_after_rounding` | Realized-risk / intended-risk floor (60% baseline per AGENTS.md Quantization) | `CONFIGURATION.md` §3 list | value TBD per §7 |

If the backtest run reveals that the trade-off is **which** variant to pick, the variant enum is the parameter that has to be swept — not a numeric value within a single variant. Variant-level sweeps are valid per `RESEARCH_PROTOCOL.md` §5 (parameter-registry linkage) only when the variant IDs are listed as discrete parameter values inside a registered set.

## 7. Backtest path

Per `RESEARCH_PROTOCOL.md` §0–§7 and `BACKTEST_SPEC.md` §11 (Acceptance gates) + §7 (Dataset splits).

### 7.1 Stage mapping

- **Stage A — Baseline trend strategy** (`TRADING_STRATEGY_RESEARCH.md` §14). The Stage A baseline is the **mandatory reference alternative**: every A1–A6 variant is reported alongside the Stage A row. Removing Stage A from the matrix is a §4 gate violation.
- **Stages B and C** are out of scope for Family A's first backtest pass. They are listed under Family B and Family C respectively; cross-family comparison is a downstream beat.
- **Stage D — Context features** (`TRADING_STRATEGY_RESEARCH.md` §14). Funding, OI, taker flow, volatility regime, session/time-of-day are evaluated as **incremental-value tests** against Family A's Stage A baseline — never as required inputs. OI is experimental-only until the self-collected dataset is long enough (`§8.2` and `§20` of the research doc).

### 7.2 Cost model (transcribed verbatim from `RESEARCH_PROTOCOL.md` §2)

- Entry fee: per Binance USDⓈ-M fee schedule; value TBD per exchange-snapshot.
- Exit fee: same.
- Funding: accounted per funding event held overnight; model `TBD` per §2.
- Slippage: `effective_entry = intended_entry + slippage` (never zero by default); value TBD per §2 cost calibration; identical in backtest / paper / live per §2 "floor-only quantization identical across modes".
- Spread / fill: per `RESEARCH_PROTOCOL.md` §2; value TBD.

### 7.3 Execution simulation (transcribed from `RESEARCH_PROTOCOL.md` §3)

- Closed-candle rule (above) — the only decision layer.
- Strategy decision: 4H regime + 1H setup; execution simulation at 1m.
- Intrabar ambiguity: fixed-before-evaluation tie-break rule (conservative: assume adverse level hit first; details `TBD` per §3 of RESEARCH_PROTOCOL).
- Limit-order checklist with **no retroactive fill after expiry** per §3 of RESEARCH_PROTOCOL.
- NO_TRADE is a first-class outcome, journaled separately per `DATA_MODEL.md` §6.

### 7.4 Acceptance gates

Per `RESEARCH_PROTOCOL.md` §4 (acceptance methodology) and `BACKTEST_SPEC.md` §11:

- Sample size ≥ `TBD` (research-baseline range to explore per `BACKTEST_SPEC.md` §10).
- Expectancy positive after cost in **Development** AND **Validation** splits.
- Profit factor not concentrated in <5 trades.
- Drawdown within `TBD` envelope per risk register.
- Robustness: not dependent on a single parameter value, single symbol, single period; per `BACKTEST_SPEC.md` §11 and `TRADING_STRATEGY_RESEARCH.md` §16 R1–R6.
- Operational: closed-bar runnable, expiry handled, SL/TP auto-managed post-approval, audit log per signal.

A "winning" variant is one that clears **all** acceptance gates — not just expectancy. The kill gate is `RESEARCH_PROTOCOL.md` §4 + D013 (three families × six months of forward evidence).

### 7.5 MFE / MAE reporting

Per `TRADING_STRATEGY_RESEARCH.md` §11.3 and §12 (System Performance vs User Performance): MFE and MAE are reported per `research/TRADING_STRATEGY_RESEARCH.md` §11.3 with time-to-MFE and time-to-MAE for every trade, separately from win-rate. The User-vs-System performance split is reported at the §12 slice.

---

## V1 family selection: TBD (D012)

This sheet does NOT declare Trend Pullback as the V1 family. The V1 family is decided after **all three families** (A, B, C) clear backtest plus out-of-sample evidence per `RESEARCH_PROTOCOL.md` §4 + §5 (loader contract) and the kill gate D013 (three families × six months of forward evidence). Selecting Trend Pullback before Families B and C also pass is a `D012` violation.

Comparative statements in this sheet carry the **pending backtest + OOS** qualifier where present. Selection-implying adjectives ("best", "preferred", "optimal", "chosen", "winner") are absent by construction; if any appear in future revisions, they MUST be qualified with the pending-backtest-plus-OOS phrase per D-08.

## Open questions

Per `TRADING_STRATEGY_RESEARCH.md` §15 (Research Questions Q1–Q12). This family's open questions are:

- **Q1 — Trend definition.** Which 4H regime detector (structure / EMA / structure+EMA) is the §3 Stage A baseline? — Gate input for §3 R1/R2/R3.
- **Q5 — Entry.** Which E-code (E1 level retest / E2 zone + ATR / E3 confirmation close / E4 hybrid) is the Stage A baseline entry? — Gate input for §3.
- **Q6 — Stop.** Which S-code (S1 swing / S2 structure + ATR / S3 zone invalidation) is the Stage A baseline SL? — Gate input for §3.
- **Q7 — TP.** Which T-code (T1 fixed-R / T2 next structure / T3 hybrid) is the Stage A baseline TP? — Gate input for §3.
- **Q8 — Minimum R:R.** Reject setups whose target structure yields `risk:reward < minimum_rr`? Value TBD per §6.
- **Q9 — Regime filter.** When does the family return `NO_TRADE`? Default-admissible per §4.2: 4H regime neutral. Edge cases (mixed regime, partial-day volatility regime) are TBD per §6.

Family B's questions (Q3 / Q4) and Family C's question (Q9's filter-side) are NOT addressed here — they belong to their respective sheets.

## Acceptance status

- Stage A baseline implemented: `NO`
- A1–A6 variants implemented: `NO`
- Backtested on the same split as Families B and C: `NO`
- Out-of-sample validated: `NO`
- Forward tested: `NO`
- Approved for live human-approved trading: `NO`

## Implementation neutrality

The family spec is technology-independent. Python is the project implementation language, but family semantics must remain expressible as deterministic inputs/outputs and must not depend on pandas, Polars, notebooks, network calls, or Binance SDK objects. See `docs/strategy/TRADING_STRATEGY_SPEC.md` "Implementation neutrality" footer (this family sheet mirrors it).
