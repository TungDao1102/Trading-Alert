# Candidate Family C — Range Mean-Reversion

> Status: HYPOTHESIS — **NOT FROZEN**
>
> This sheet is one of three mutually-comparable candidate families (A/B/C). All three share the same 7-slot template, the same TBD discipline, and the same D012 footer.
> Values remain `TBD` until the research methodology is exercised on real data per `docs/research/RESEARCH_PROTOCOL.md` §0–§4 and §1 (anti-overfitting rules R1–R6).
> Source material: `docs/research/TRADING_STRATEGY_RESEARCH.md` §4.2 (support/resistance zones; range machinery), §5.3 (Candidate C), §6.3 (NO_TRADE fallback), §14 (Stage C gated by regime filter and dataset), §15 (research questions Q1–Q12), §16 (anti-overfitting rules R1–R6).
> Cross-references: `docs/strategy/TRADING_STRATEGY_SPEC.md` (TBD slot template), `docs/configuration/CONFIGURATION.md` §3 (parameter registry examples).
> Sibling sheets: `docs/research/families/trend-pullback.md` (Family A), `docs/research/families/breakout-retest.md` (Family B).

## 1. Informal definition (prose hypothesis)

**Hypothesis:** when the market is range-bound (the higher-timeframe regime is neither a clean up-trend nor a clean down-trend), price oscillates between a range-high and a range-low; selling at the range-high and buying at the range-low, with stop outside the range and take-profit at the mid or the opposite boundary, captures the mean-reversion behavior.

The informal definition does NOT pick which regime filter to use, which TP mode (mid vs opposite), or which entry timing (touch / close / hybrid). Those are the machine-detectable candidates in §2 and the explicit alternatives in §3. Picking one is a Stage C baseline that must clear backtest plus out-of-sample evidence before any family can be promoted.

## 2. Machine-detectable definition (closed-bar composition)

The strategy is composed from a 4H regime detector (NO_TRADE on trend) and a 1H range-edge setup. Decisions are taken on closed bars only (no unclosed pivots, no current-candle high/low).

### 2.1 Range definition

A range is a pair of zones (range-high and range-low) constructed from swing highs and swing lows inside a volatility-adjusted tolerance — the same zone machinery as Family A / Family B, transcribed from `TRADING_STRATEGY_RESEARCH.md` §4.2. The range is "valid" while:

- The range-high zone and the range-low zone are both present (neither has aged out per `zone_aging_bars`).
- The 4H regime filter (per §2.2) returns `range` — see NO_TRADE rule below.

A range expires when either the range-high or the range-low zone becomes inadmissible (e.g. the lookback rolls past the zone's last pivot). The expiry is recorded as part of the setup's `valid_until` per `TRADING_STRATEGY_RESEARCH.md` §13.

### 2.2 4H regime filter (NO_TRADE rule)

This family explicitly answers Q9 (`TRADING_STRATEGY_RESEARCH.md` §15) — the regime filter is a **NO_TRADE rule**:

- If the 4H regime is `range` per §2.1's range validity, Family C emits signals.
- If the 4H regime is `trend-up` or `trend-down` (per Family A's R1 structure-only definition reused here), Family C emits **NO_TRADE** for that symbol for that decision cycle. The reason is the trend-break destruction risk noted in §4.2: a mean-reversion entry against an active trend is structurally destructive — the SL is outside the range but the trend's continuation moves through the SL.

The regime detector (R1 / R2 / R3) is shared with Family A and Family B; Family C's contribution is the NO_TRADE policy on non-range regimes, not the detector itself.

### 2.3 1H range-edge setup

The 1H setup is a touch / close / hybrid at the range-high (SHORT) or range-low (LONG). The same P1/P2/P3/P4 alternatives as Family A's pullback apply (touch / close / +EMA confluence / +volume confluence). Each Px is a separate testable row in §3.

### 2.4 Post-entry range expansion: invalidation, not redraw

A common failure mode for range strategies is to **redraw** the range when price exits one boundary ("the range was actually higher / lower"). Family C's binding rule is that this is **invalidation**, not redraw:

- If a 1H close breaks the range-high (LONG) or the range-low (SHORT) by more than `range_break_buffer_atr` (value `TBD` per §6), the range is invalidated and the position exits at SL per §2.5.
- The invalidated range is NOT modified in place. The system does NOT recompute a "new range" from the post-break bars and continue running the original setup.
- A new range (if one forms on the next leg) is a separate setup, with its own regime filter and SL/TP — see §5.2 single-setup rule.

### 2.5 Timeframe mapping

| Layer | Timeframe | Role |
|---|---|---|
| Regime (trend vs range) | 4H | R1/R2/R3 structure detector reused; NO_TRADE on non-range regimes per §2.2 |
| Range-edge setup | 1H | P1/P2/P3/P4 reused from Family A's pullback alternatives |
| Entry-refinement (optional) | 15M | Only for confirmation candle; NOT for range-edge decisions |
| Execution simulation | 1m | Per `RESEARCH_PROTOCOL.md` §3 (Strategy timeframe vs execution timeframe); the only place intrabar order behavior is modeled |

15M is optional; 1m is execution-simulation only. No layer may make a strategy decision off a timeframe not listed above.

## 3. Alternative definitions (competing rows, never blended)

Each row below is a separate testable alternative. The Stage C baseline is the **mandatory reference alternative** every other row is compared against; no row may be promoted as the selection without first clearing backtest plus out-of-sample evidence per `RESEARCH_PROTOCOL.md` §4 (acceptance methodology) and §5 (parameter-registry linkage).

| ID | Combination | What it adds over Stage C baseline |
|---|---|---|
| Stage C baseline | R1 (structure-only regime) + filter ON + P1 (range-edge touch) + E2 (zone + ATR buffer entry) + S3 (zone invalidation SL) + T-mid (TP at range midpoint) | Reference; never removed from the matrix |
| C-filter-on | Stage C baseline | Filter ON (NO_TRADE on trend regimes); default admissible variant |
| C-filter-off | R1 + filter OFF + P1 + E2 + S3 + T-mid | Diagnostic A/B; runs only as a filter-effect measurement, not as a candidate family |
| C-tp-mid | C-filter-on + T-mid (TP at range midpoint) | Stage C canonical TP mode |
| C-tp-opposite | C-filter-on + T-opposite (TP at opposite boundary) | Higher-RR candidate; structurally larger winners if the range holds |
| C-pullback-1 | C-filter-on + P1 + T-mid | Range-edge touch + TP-mid (Stage C canonical) |
| C-pullback-2 | C-filter-on + P2 + T-mid | Range-edge close + TP-mid (filters wicks that don't close at the edge) |
| C-pullback-3 | C-filter-on + P3 + T-mid | Range-edge + EMA confluence + TP-mid |
| C-pullback-4 | C-filter-on + P4 + T-mid | Range-edge + volume confluence + TP-mid |
| C-direction-1 | C-filter-on + P1 + T-opposite | Range-edge touch + TP-opposite (full-range capture) |
| C-direction-2 | C-filter-on + P2 + T-opposite | Range-edge close + TP-opposite |

The full cross-product is intentionally **not** enumerated here — that is the §7 backtest path's job. The rows above are the **must-test** set per `TRADING_STRATEGY_RESEARCH.md` §5.3 ("Lý do cần nghiên cứu"), §14 (Stage C gated by regime filter + dataset), and Q9's filter-side pointer.

### 3.1 Variants table (per-family sheet cosmetic)

| Variant ID | Filter | Pullback | Entry code | SL code | TP code | Status |
|---|---|---|---|---|---|---|
| Stage C baseline | ON | P1 touch | E2 | S3 | T-mid (range midpoint) | reference — pending backtest + OOS |
| C-filter-off | OFF | P1 touch | E2 | S3 | T-mid | diagnostic — pending backtest + OOS |
| C-pullback-1 | ON | P1 touch | E2 | S3 | T-mid | candidate — pending backtest + OOS |
| C-pullback-2 | ON | P2 close | E2 | S3 | T-mid | candidate — pending backtest + OOS |
| C-pullback-3 | ON | P3 +EMA | E4 | S3 | T-mid | candidate — pending backtest + OOS |
| C-pullback-4 | ON | P4 +volume | E2 | S3 | T-mid | candidate — pending backtest + OOS |
| C-tp-opposite | ON | P1 touch | E2 | S3 | T-opposite (opposite boundary) | candidate — pending backtest + OOS |
| C-direction-2 | ON | P2 close | E2 | S3 | T-opposite | candidate — pending backtest + OOS |

Selection-implying adjectives are intentionally absent — see `## V1 family selection` footer below.

### 3.2 Implemented as (Phase 15, D054)

This paragraph records what the code does for the Stage C baseline row, where it differs from the sheet, and where the record lives. It is an implementation record, not evidence: the sheet stays a hypothesis and no value below is claimed to be evidence-backed.

- **Set and versions.** `params/range-mr/baseline-v6.toml`, `strategy_version` v5.0.0, `geometry_version` 1, `tp_mode` T_MID (STRUCTURAL). Every parameter carries a basis in the in-file rationale table; the pivot widths 3 and 3, `min_stop_atr` 0.5, the range, touch, aging, buffer and `minimum_rr` values are labelled PLACEHOLDER, so the set is research-only.
- **Regime (D-22).** The filter is ON: NEUTRAL means neither higher highs with higher lows nor lower highs with lower lows on the confirmed 4H pivots (`pivot_left_bars` / `pivot_right_bars`) inside the last `regime_filter_lookback` 4H bars, closed bars only, evaluated at the last closed 4H bar. Fewer than two pivots of either kind is NO_TRADE, never a default. The earlier EMA50 equality test could not be satisfied in practice and is not used when `geometry_version` is present. This reads `regime_filter_lookback` as the pivot window of one verdict at the last closed 4H bar; the sheet's binding rule 2 (every closed 4H bar over the lookback returns `range`) is therefore only approximated, a recorded deviation.
- **Range and touches (deviation).** The range edges are the trailing `swing_lookback` high and low taken at the bar before the evaluated bar (one level per side, not merged zones). A touch is a bar whose high or low lies within `touch_tolerance_atr x ATR` of an edge; the setup needs `zone_min_touches` earlier touches with the newest inside `zone_aging_bars`, and a close beyond an edge by `range_break_buffer_atr x ATR` invalidates the range. The evaluated bar's low (LONG, lower edge) or high (SHORT, upper edge) must touch the near edge (P1). Range construction stays as implemented and is recorded in D054.
- **Entry.** E2: the entry zone is the touched range edge plus or minus `entry_buffer_atr x ATR`.
- **Stop (S3, D-23).** Beyond the far edge of the narrow S/R zone around the touched edge (the edge minus or plus `zone_tolerance_atr x ATR`), then `sl_buffer_atr x ATR` further out. Shared planner invariants apply: the stop is strictly outside the whole entry zone, the signal bar has not already traded through it (INVALIDATED), and `abs(entry reference - stop) >= min_stop_atr x ATR`.
- **Target.** TP1 is the range midpoint through `tp_mode` T_MID, the sheet's Stage C baseline (D-10). T-opposite (the opposite boundary, variants C-tp-opposite and C-direction-2) stays the named variant behind `tp_mode` T_OPPOSITE and needs its own parameter set; no set in this phase uses it. The shared planner applies the same TP2 positivity rule to this family: a plan whose TP2 is not above zero is NO_TRADE RR_TOO_LOW (protocol v2.6.0, D075; see trend-pullback.md).
- **Where the deviations are recorded.** D054 in `docs/DECISIONS.md` and the Family C rows of `docs/research/GEOMETRY_AUDIT.md` (D-22, D-23, D-10, D-14, D-25).

## 4. Advantages / Disadvantages

### 4.1 Why this family might earn backtest admission

- **Non-trending coverage rationale.** Families A and B are trend-gated; in a choppy / sideways market, both families emit NO_TRADE. Family C provides coverage in those windows, raising the system's per-month signal count without forcing signals during trends. This is the explicit non-overlap design per `TRADING_STRATEGY_RESEARCH.md` §5.3 ("Lý do cần nghiên cứu").
- **Symmetric setup.** LONG at range-low and SHORT at range-high are mirror images under the same code path, halving the implementation surface for setup detection. The TP modes (mid vs opposite) are a single switch.
- **Closed-bar boundaries.** Range-edge decisions on closed 1H bars; the regime filter on closed 4H bars; intrabar 1m data is execution-only — by construction zero repaint on the setup decision.

### 4.2 Why this family is at risk of under-signaling or under-performing

- **Trend-break destruction risk.** A range that breaks is no longer a range; entering before the break is structurally destructive (the SL is outside the range, but the trend continuation moves through the SL). The §2.2 NO_TRADE rule on trend regimes is the mitigation; the cost is that **the family is silent at the exact moment of regime transition** — by construction the family is always late to a trend's start.
- **Range-edge clustering risk.** In low-liquidity or weekend periods, the range can compress to a sub-ATR width that yields no entry; the `zone_tolerance_atr` minimum (value `TBD` per §6) is the mitigation, but tighter ranges starve the dataset of statistical power per `RESEARCH_PROTOCOL.md` §4.
- **Range-expansion-as-redraw failure mode.** Naïve implementations redraw the range when price exits one boundary; Family C explicitly forbids this per §2.4. Two implementations with different range-redraw policies are not directly comparable; the §7 backtest path must report per-variant.
- **Filter-off diagnostic risk.** Running C-filter-off against the same data looks superficially attractive (more signals, more trades) but measures the filter's value, not the family's edge. The filter is per §7 a diagnostic only — it is not in the candidate-family comparison matrix until the filter-on variants clear.

### 4.3 Pre-committed entry-quality metrics (Family C only)

Per `TRADING_STRATEGY_RESEARCH.md` §6.1 ("Research metric"). These are the entry-quality metrics this family commits to reporting alongside win-rate and expectancy. Each metric is computed at the variant level (Stage C baseline, C-filter-off, C-pullback-1…4, C-tp-opposite, C-direction-2):

- **Fill rate** — fraction of limit-zone entries filled at the intended range edge.
- **Missed-trade rate** — fraction of detected setups where the entry was never reached before expiry / invalidation. For Family C, "missed" includes "range invalidated before entry reached" (the post-entry range-expansion case per §2.4) and "regime filter flipped from `range` to `trend` before entry reached".
- **Entry slippage** — `effective_entry - intended_entry`, in price and in ATR units.
- **Post-touch MFE** — maximum favorable excursion measured from range-edge touch, irrespective of fill.
- **Post-touch MAE** — maximum adverse excursion measured from range-edge touch, irrespective of fill.

These five metrics are pre-committed so the Stage C baseline and every C-pullback-* / C-tp-opposite / C-direction-* variant is comparable on the same axes. A "winning" variant (per D012 pending backtest + OOS) must clear all five axes, not just expectancy.

## 5. Look-ahead-bias analysis

Per `RESEARCH_PROTOCOL.md` §3 (closed-candle rule) and `TRADING_STRATEGY_RESEARCH.md` §9.1 (no-repaint baseline).

The look-ahead questions below are the family-C binding answers:

| # | Question | Family C binding rule |
|---|---|---|
| 1 | Range-edge confirmation bar | The range-edge touch / close / hybrid is confirmed at the close of the bar that satisfies P1/P2/P3/P4 on a **closed** 1H bar. The bar's in-progress high or low is never used. |
| 2 | Regime filter confirmation | The regime filter's `range` verdict requires that the closed 4H bars over `regime_filter_lookback` (value `TBD` per §6) all return `range` from the R1 detector. A regime verdict is updated only at the close of each 4H bar. |
| 3 | Unclosed pivots / unconfirmed zones | NEVER used. Range-edge zones are computed only from closed 1H / 4H bars; a zone formed on a still-in-progress bar is inadmissible. |
| 4 | Repaint risk | Closed-bar only — by construction zero repaint on the range-edge / regime decision when the implementation enforces closed-bar strictness at every gate. The regime filter MUST be evaluated at the close of the 4H bar, not at any earlier intrabar sample. |
| 5 | Range expansion as redraw | FORBIDDEN per §2.4. A range that is broken by more than `range_break_buffer_atr` is invalidated; the position exits; no in-place recomputation of the range from the post-break bars. |
| 6 | 4H regime detector | Reused from Family A's R1 / R2 / R3; closed-bar rule applies uniformly. |

### 5.1 Zone-boundary touch semantics (RSCH-02/adjacency flagged assumption)

Per the phase assumption delta — Family C's binding rule:

- **Merge.** If two consecutive zones overlap (distance between zone midpoints < combined half-widths), the zones are merged into a single zone whose bounds are the union. (Default for Stage C baseline.)
- **Collide.** If two zones touch at exactly one price level (distance between zone midpoints == combined half-widths to machine precision), the touch is treated as a **single zone** for entry-zone classification but as **two zones** for invalidation purposes.
- **Separate.** If the gap between zones is positive (distance > combined half-widths), the zones are independent and an entry in the gap does not satisfy P1/P2/P3/P4.

For Family C specifically, a "valid range" requires both the range-high and the range-low to be well-defined zones after the merge / collide / separate rule is applied. A range with one of the boundaries undefined (e.g. the swing-pivot count is too low to form a zone) is inadmissible; Family C emits NO_TRADE for that symbol for that decision cycle per §2.2's NO_TRADE-on-non-range rule (no zone = no range = no admissible setup).

### 5.2 Single-setup and zero-setup behavior (RSCH-02/empty flagged assumption)

Per the phase assumption delta — Family C's binding rule:

- **Single-setup.** When exactly one qualifying range-edge exists on a symbol at decision time (the range is defined; the regime filter is `range`; the touch / close / hybrid is satisfied), the family emits exactly one signal with that setup's parameters. No batch dedup, no ranking across setups.
- **Zero-setup.** When zero setups qualify on a symbol at decision time, the family emits NO_TRADE for that symbol for that decision cycle. The three NO_TRADE cases for Family C are: (a) regime filter is `trend-up` or `trend-down` per §2.2; (b) range is not well-defined per §5.1 (zone missing); (c) range-edge touch / close / hybrid is not satisfied on any bar in `signal_expiry_hours`. NO_TRADE is a first-class outcome per `RESEARCH_PROTOCOL.md` §3 and is journaled separately per `data/DATA_MODEL.md` §6 (NO_TRADE slice).

A variant with "no signals for N days" is NOT a bug — it is the family being correctly silent. Forcing a signal in that window violates R5 ("Không target daily PnL"). Family C's signal rate is explicitly bounded above by the per-symbol regime-filter hit rate, which the §7 backtest path reports.

## 6. Testable parameters

Testable parameters for this family map onto the parameter-registry examples in `CONFIGURATION.md` §3 ("Strategy parameters"). Each parameter below is a placeholder; the **value** is TBD until exercised on real data per `RESEARCH_PROTOCOL.md` §0. The Phase 3 registry enforces this — no backtest run may use an unregistered parameter set (D-07).

| Parameter | Meaning | Source | Status |
|---|---|---|---|
| `regime_filter_lookback` | 4H bars over which the R1 detector must agree on `range` for the family to admit a setup | `TRADING_STRATEGY_RESEARCH.md` §5.3 + Q9 | value TBD |
| `range_filter_on` | Boolean: filter ON (default admissible) vs filter OFF (diagnostic only) | §2.2 + §3 C-filter-off | enum TBD per §3 |
| `pullback_variant` | P1 / P2 / P3 / P4 selection | §2.3 (reused from Family A) | enum TBD per §3 |
| `tp_mode` | T-mid (range midpoint) vs T-opposite (opposite boundary) | §3 C-tp-opposite | enum TBD per §3 |
| `zone_min_touches` | Minimum swing pivots inside the lookback to qualify a zone | `TRADING_STRATEGY_RESEARCH.md` §4.2 variables | value TBD |
| `zone_tolerance_atr` | Volatility-adjusted zone half-width in ATR units | `CONFIGURATION.md` §3 list + §4.2 | value TBD |
| `zone_aging_bars` | Bars after which an un-touched zone is dropped | §4.2 "Khi nào zone mất hiệu lực" | value TBD |
| `range_break_buffer_atr` | ATR buffer past range-edge that classifies a 1H close as range-break (invalidation) | §2.4 + §5 row 5 | value TBD |
| `entry_buffer_atr` | E2 buffer from range edge | `CONFIGURATION.md` §3 list | value TBD |
| `sl_buffer_atr` | S3 zone-invalidation ATR buffer (range-edge SL sits outside the zone by this buffer) | `CONFIGURATION.md` §3 list | value TBD |
| `minimum_rr` | Minimum risk:reward for a setup to be admitted; if `tp_mode = T-opposite` violates the floor, the setup flips to NO_TRADE per §6.3 of RESEARCH | `CONFIGURATION.md` §3 + Q8 + §6.3 constraint | value TBD |
| `signal_expiry_hours` | Setup validity window (UTC) | `CONFIGURATION.md` §3 list | value TBD |
| `risk_rate` | Per-trade equity fraction | `TRADING_STRATEGY_RESEARCH.md` §7.1 baseline | value TBD per §7 |
| `minimum_risk_utilization_after_rounding` | Realized-risk / intended-risk floor (60% baseline per AGENTS.md Quantization) | `CONFIGURATION.md` §3 list | value TBD per §7 |

If the backtest run reveals that the trade-off is **which** filter / TP / pullback variant to pick, the variant enums are the parameters that have to be swept — not a numeric value within a single variant. Variant-level sweeps are valid per `RESEARCH_PROTOCOL.md` §5 (parameter-registry linkage) only when the variant IDs are listed as discrete parameter values inside a registered set.

## 7. Backtest path

Per `RESEARCH_PROTOCOL.md` §0–§7 and `BACKTEST_SPEC.md` §11 (Acceptance gates) + §7 (Dataset splits).

### 7.1 Stage mapping

- **Stage A — Baseline trend strategy** (`TRADING_STRATEGY_RESEARCH.md` §14) belongs to Family A.
- **Stage B — Breakout/retest** (`TRADING_STRATEGY_RESEARCH.md` §14) belongs to Family B.
- **Stage C — Range strategy** (`TRADING_STRATEGY_RESEARCH.md` §14). The Stage C baseline is the **mandatory reference alternative**: every C-pullback-* / C-tp-opposite / C-direction-* variant is reported alongside the Stage C row. Removing Stage C from the matrix is a §4 gate violation. **Stage C is gated by regime filter and dataset** per `TRADING_STRATEGY_RESEARCH.md` §14 — the family is run only if (a) the 4H regime shows a non-trivial share of `range` windows on the development split AND (b) the dataset contains enough regime-filtered trades to clear the §7.4 sample-size gate. If the dataset does not satisfy (a) or (b), Stage C is recorded as "skipped — dataset insufficient" and the family is excluded from the comparison matrix.
- **Stage D — Context features** (`TRADING_STRATEGY_RESEARCH.md` §14). Funding, OI, taker flow, volatility regime, session/time-of-day are evaluated as **incremental-value tests** against Family C's Stage C baseline — never as required inputs. OI is experimental-only until the self-collected dataset is long enough (`§8.2` and `§20` of the research doc).

### 7.2 Cost model (transcribed verbatim from `RESEARCH_PROTOCOL.md` §2)

- Entry fee: per Binance USDⓈ-M fee schedule; value TBD per exchange-snapshot.
- Exit fee: same.
- Funding: accounted per funding event held overnight; model `TBD` per §2.
- Slippage: `effective_entry = intended_entry + slippage` (never zero by default); value TBD per §2 cost calibration; identical in backtest / paper / live per §2 "floor-only quantization identical across modes".
- Spread / fill: per `RESEARCH_PROTOCOL.md` §2; value TBD.
- Range-edge entry slippage: a Family C-specific line item. When the entry order sits at the range-edge, fill at the zone mid yields a slippage of `zone_half_width_atr` in ATR units against the intended edge; the slippage is computed against the **fill price**, not the edge mid. This is identical to Family A / Family B's slippage model; the variant just changes where the order sits on the bar timeline.

### 7.3 Execution simulation (transcribed from `RESEARCH_PROTOCOL.md` §3)

- Closed-candle rule (above) — the only decision layer.
- Strategy decision: 4H regime + 1H range-edge; execution simulation at 1m.
- Intrabar ambiguity: fixed-before-evaluation tie-break rule (conservative: assume adverse level hit first; details `TBD` per §3 of RESEARCH_PROTOCOL).
- Limit-order checklist with **no retroactive fill after expiry** per §3 of RESEARCH_PROTOCOL. For Family C, the limit order's expiry coincides with `signal_expiry_hours` past the range-edge touch.
- NO_TRADE is a first-class outcome, journaled separately per `DATA_MODEL.md` §6. Family C's three NO_TRADE cases (§5.2 a/b/c) are journaled with the reason in the row's `notes` field.

### 7.4 Acceptance gates

Per `RESEARCH_PROTOCOL.md` §4 (acceptance methodology) and `BACKTEST_SPEC.md` §11:

- Sample size ≥ `TBD` (research-baseline range to explore per `BACKTEST_SPEC.md` §10). Note: Family C's per-variant trade count is **explicitly lower** than Family A's and Family B's because the regime filter rejects trend windows AND the dataset-insufficiency gate (§7.1) may exclude the family entirely if the development split lacks range windows. The sample-size gate must be evaluated against the **pooled** Stage C baseline + variant set, not against a single variant.
- Expectancy positive after cost in **Development** AND **Validation** splits.
- Profit factor not concentrated in <5 trades.
- Drawdown within `TBD` envelope per risk register.
- Robustness: not dependent on a single parameter value, single symbol, single period; per `BACKTEST_SPEC.md` §11 and `TRADING_STRATEGY_RESEARCH.md` §16 R1–R6.
- Operational: closed-bar runnable, expiry handled, SL/TP auto-managed post-approval, audit log per signal.
- Comparative gates: the Stage C baseline's metrics must be **at least as good as** Family A's Stage A baseline and Family B's Stage B baseline on the same split for Family C to be a credible candidate. If Family C's baseline is materially worse, the family does not earn admission to the Stage D feature-incremental-value tests.
- Minimum-RR floor: when `tp_mode = T-opposite` would violate `minimum_rr` for a given range width and SL distance, the setup flips to NO_TRADE per `TRADING_STRATEGY_RESEARCH.md` §6.3 ("NO TRADE"). The §7 backtest path reports how often this flip happens per variant.

A "winning" variant is one that clears **all** acceptance gates — not just expectancy. The kill gate is `RESEARCH_PROTOCOL.md` §4 + D013 (three families × six months of forward evidence).

### 7.5 MFE / MAE reporting

Per `TRADING_STRATEGY_RESEARCH.md` §11.3 and §12 (System Performance vs User Performance): MFE and MAE are reported per `research/TRADING_STRATEGY_RESEARCH.md` §11.3 with time-to-MFE and time-to-MAE for every trade, separately from win-rate. Family C's MFE / MAE are measured **from the range-edge touch** (the family-specific anchor) — comparable across Family C variants but NOT directly comparable to Family A's "from pullback touch" or Family B's "from retest touch" anchors without an explicit bridge metric. The User-vs-System performance split is reported at the §12 slice.

---

## V1 family selection: TBD (D012)

This sheet does NOT declare Range Mean-Reversion as the V1 family. The V1 family is decided after **all three families** (A, B, C) clear backtest plus out-of-sample evidence per `RESEARCH_PROTOCOL.md` §4 + §5 (loader contract) and the kill gate D013 (three families × six months of forward evidence). Selecting Range Mean-Reversion before Families A and B also pass is a `D012` violation.

Comparative statements in this sheet carry the **pending backtest + OOS** qualifier where present. Selection-implying adjectives ("best", "preferred", "optimal", "chosen", "winner") are absent by construction; if any appear in future revisions, they MUST be qualified with the pending-backtest-plus-OOS phrase per D-08.

## Open questions

Per `TRADING_STRATEGY_RESEARCH.md` §15 (Research Questions Q1–Q12). This family's open questions are:

- **Q9 — Regime filter.** When does the family return `NO_TRADE`? — Family C's binding answer is in §2.2: when the 4H regime is `trend-up` or `trend-down` (per R1 structure-only detector); when the range is not well-defined per §5.1 (zone missing); when the range-edge touch / close / hybrid is not satisfied per §5.2 case (c). The three cases are journaled separately per `DATA_MODEL.md` §6 NO_TRADE slice.
- **Q8 — Minimum R:R.** Reject setups whose target structure yields `risk:reward < minimum_rr`? — Family C's binding answer is yes, with a `T-opposite` → NO_TRADE flip when the opposite-boundary target is below `minimum_rr`. The T-mid mode is exempt from this flip only because T-mid is symmetric and always yields at least 1:1 by construction (range mid is always closer than the opposite boundary); this is a §6.3 constraint, not a pre-judgment of T-opposite's standing.

Family A's Q1 (trend definition), Family A's Q5–Q7 (entry/SL/TP method codes), and Family B's Q3–Q4 (breakout/retest definitions) are NOT directly answered here — they are inherited from the sibling sheets.

## Acceptance status

- Stage C baseline implemented: `AS RECORDED` (baseline-v6, deviations in D054)
- C-filter-off / C-pullback-1…4 / C-tp-opposite / C-direction-2 variants implemented: `NO`
- Backtested on the same split as Families A and B: `NO`
- Out-of-sample validated: `NO`
- Forward tested: `NO`
- Approved for live human-approved trading: `NO`

## Implementation neutrality

The family spec is technology-independent. Python is the project implementation language, but family semantics must remain expressible as deterministic inputs/outputs and must not depend on pandas, Polars, notebooks, network calls, or Binance SDK objects. See `docs/strategy/TRADING_STRATEGY_SPEC.md` "Implementation neutrality" footer (this family sheet mirrors it).
