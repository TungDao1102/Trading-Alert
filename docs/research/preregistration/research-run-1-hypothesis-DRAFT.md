DRAFT - not approved by the user; drafted without any backtest or research result
# Research run 1 - hypothesis and parameter grid (agent draft for decision O-02)

> Status: DRAFT. Written by an agent on 2026-10-12 for Phase 16 plan 16-45 (closure-chain step "a hypothesis and parameter grid written or explicitly approved by the user", L-10, D061 item J).
> Nothing in this file is approved, preregistered or hashed. It becomes a preregistration only after the user approves, changes or replaces it (checkpoint O-02), and approving it does NOT authorize a research run (that is a separate user command, O-03, plan 16-46).
> No experiment has been recorded and `docs/research/holdout_consumed.json` has no entries, so no research result existed while this was written. Every value below comes from a family sheet, the protocol, a DECISIONS row, the existing seed sets, or the drafter's own design choice (stated as such). No value was chosen, ranked or tuned from a backtest or any count (D059 item 5, anti-overfitting rules R1 to R6).

## 0. Questions the user must answer (nothing is pre-selected)

1. **Which family or families does run 1 cover?** Open. This draft describes all three (section 4: trend-pullback, section 5: breakout-retest, section 6: range-mr) so the user can pick any subset, or none of them. The draft does not recommend one (D012: no family is preferred before backtest plus out-of-sample evidence). Cost of choosing more than one: Holm-Bonferroni is applied inside one family only, so selecting among families adds an uncorrected layer, about 14% worst-case false-pass rate for three families (protocol section 4).
2. **Is the grid shape acceptable?** The draft uses one full 2 x 2 x 2 x 2 grid per family, 16 points, inside the variant budget N = 25 per family (protocol section 4). The user may add, remove or replace any varied parameter or value, as long as the family stays at 25 points or fewer.
3. **Provenance labels for fixed seed values (section 2).** Many fixed values (for example `min_stop_atr` 0.5, `swing_lookback` 20, `atr_period` 14) were labelled with the placeholder basis in `baseline-v6` because no spec or decision fixes them, and they have no empirical basis. A registered candidate may carry no placeholder label (`src/research/register.py`), so this draft labels them EXPERIMENT: a setting fixed by this preregistration before any result exists. The label records that the value was preregistered, not that it is supported by evidence. The user decides whether that label is acceptable or whether a value should be changed or moved to a DECISION row.
4. **`max_cost_to_risk`** is kept at 0.15 (see section 2). The user may instead put a revisit into the grid now, before any result exists (D046 item 6).
5. **`signal_expiry_hours`** is listed as a candidate parameter in every family (section 3). The user may fix it instead of varying it, or change the values (it is the approval expiry of REV-12, O-08).
6. **Anything the user wants to add**: another varied parameter, another hypothesis, a different grid design (for example a one-at-a-time design instead of a full grid).

## 1. Rules this draft follows

- Closed-bar decisions only; execution at 1m; costs from experiment 1 (R4); NO_TRADE is a valid outcome (R5, R6).
- Every grid point becomes a new, immutable parameter set `params/<family>/research-run-1-<point>.toml`. No committed set is edited (AGENTS.md). Registration happens only after approval (plan 16-45 Task 3).
- Provenance labels used: STRUCTURAL (fixed by a spec), COST_GUARD (a guard of D046), DECISION (a DECISIONS row), EXPERIMENT (a setting or a varied value fixed by this preregistration; its `ref` is `research-run-1/O-02`). The placeholder label is not used anywhere in the sets.
- The 40/40/20 split, four validation folds, G1 to G5, the single-use holdout and the cost model are the frozen protocol v2.2.0 and are not part of this draft. The data window, universe and split dates are decided separately at O-03.
- Power note (protocol section 4, D043): with sigma about 1.2 R the trade floor of G1 (100 pooled, 30 per fold) detects only a large edge, and the floor may be unreachable at the decided dataset depth. A shortfall is reported, never papered over, and a smaller grid means a lighter Holm correction. Neither fact is a reason to change a value.

## 2. Values that are fixed in every family

Same value in all points of all families unless a family section says otherwise. `Source` names where the value or its label comes from.

| Key | Value | Label | Rationale | Source |
|---|---|---|---|---|
| geometry_version | 1 | DECISION | Selects the corrected Phase 15 geometry (pivot-anchored levels, stop outside the zone). | D054 |
| min_stop_atr | 0.5 | EXPERIMENT | Planner invariant: minimum entry-to-stop distance in ATR; fixed so that it is not a degree of freedom of this run. | CONTEXT Phase 15 D-08, `baseline-v6`, CONFIGURATION section 10 (geometry keys) |
| swing_lookback | 20 | EXPERIMENT | How old a pivot or swing may be; held at the seed so the grid varies fewer things. | `baseline-v6` seed, plan 03-01 |
| entry_buffer_atr | 0.1 | EXPERIMENT | Entry zone widening in ATR (E2); held at the seed. | family sheets section 6, `baseline-v6` seed |
| minimum_rr | 2.0 | EXPERIMENT | Acceptance threshold on planned reward to risk, not a target builder (CR-03); held at the seed. | family sheets section 6, D054, `baseline-v6` seed |
| minimum_risk_utilization_after_rounding | 0.6 | STRUCTURAL | Realized-to-allowed risk floor after quantization. | AGENTS.md Constraints, RISK_MANAGEMENT section 11, D031 |
| max_open_positions | 2 | EXPERIMENT | Portfolio gate; RISK_MANAGEMENT section 4 calls it an initial research value to be validated; held. | RISK_MANAGEMENT section 4 |
| max_aggregate_open_risk | 0.01 | EXPERIMENT | Aggregate open-risk cap (1.0% of equity); held. | RISK_MANAGEMENT section 4 |
| cluster_cap | 0.005 | EXPERIMENT | Correlated-cluster risk cap (0.5%); held. | RISK_MANAGEMENT section 4 |
| daily_loss_warning_threshold | 0.005 | DECISION | Daily-loss warning threshold. | D033 |
| daily_loss_stop_threshold | 0.01 | DECISION | Daily-loss stop threshold. | D033 |
| fee_rate_entry | 0.0005 | DECISION | Entry fee at the taker rate. | D036 |
| fee_rate_exit | 0.0005 | DECISION | Exit fee at the taker rate. | D036 |
| expected_slippage | 0.0001 | DECISION | Entry-side slippage, non-zero from experiment 1 (R4). | D046 item 4 and 6 |
| exit_slippage_rate | 0.0003 | DECISION | Stop-market exit slippage. | D046 |
| min_stop_distance_rate | 0.003 | COST_GUARD | A stop closer than this fraction of price is rejected (STOP_TOO_TIGHT). | D046 |
| max_cost_to_risk | 0.15 | COST_GUARD | Kept at its current value; revisit only by a new set chosen before any result, D046 item 6. | D046 |
| commission_rate_ttl_seconds | 3600 | DECISION | Freshness window of the live commission rate. | D046 |
| constraint_snapshot_ttl_seconds | 3600 | EXPERIMENT | Freshness window of the exchange-constraint snapshot; no document fixes the number. | RISK_MANAGEMENT section 12, Phase 5 plan 05-01 |
| funding_treatment | ADDITIVE | EXPERIMENT | Funding treatment declared for the cost model; the simulator charges funding at every actual `fundingTime`. | RESEARCH_PROTOCOL section 2, D052 |
| slippage_model | FIXED_BPS | EXPERIMENT | Slippage model declared for the cost model. | RESEARCH_PROTOCOL section 2 |
| spread_fill_assumptions | FULL_FILL | EXPERIMENT | Spread and fill assumption declared for the cost model. | RESEARCH_PROTOCOL section 2, D038 |
| partial_fill_fraction | 1.0 | DECISION | Full fills for all canonical cost sets. | D038 |
| working_type | MARK_PRICE | DECISION | Protective triggers on mark price. | D037 |
| atr_period | 14 | EXPERIMENT | ATR lookback (families B and C key); held at the seed. | `baseline-v6` seed (a common default, no spec fixes it) |

Note on `max_cost_to_risk` and the stop width: with 0.15 the cost-to-risk guard is the binding gate and implies a minimum stop of about 0.79 percent of price (CONFIGURATION section 10, D046 item 6). The stop distance is built from zone width and buffers measured in ATR, so wider values of `zone_tolerance_atr` and `sl_buffer_atr` reduce the share of plans rejected by this guard. That is arithmetic from D046, not a result, and it is the reason the upper values below are included.

## 3. Candidate parameters of this run

A candidate parameter is a key that a grid varies. `signal_expiry_hours` is a candidate parameter in every family (O-08): hours from the source candle close until the signal expires; seed 4, alternative 8 (two 4H strategy bars of validity versus one). Source for 4: `baseline-v6` seed; source for 8: the drafter's design choice, the next whole multiple of the 4H decision bar; no document fixes either. All other varied keys are listed in the family sections. Keys not listed as varied or in section 2 do not exist in that family's set.

## 4. Family A - trend-pullback

**Hypothesis (from `docs/research/families/trend-pullback.md` section 1).** If the 4H regime is directional and price pulls back to a confirmed 1H structure zone in the direction of the trend, entering at the zone with the stop outside the zone, and exiting at the structure target with the TP1/TP2 ladder, has a net expectancy above zero after taker fees, slippage and funding. The registered geometry is the Stage A baseline as implemented in Phase 15 (EMA50 4H regime proxy, P1 zone touch, E2 entry, S2 stop, structure target; deviations recorded in the sheet section 3.2 and D054). Null: mean net R per trade is at most 0 (G2, G3).

**Varied parameters (16 points, 2 x 2 x 2 x 2):**

| Key | Values | Label | Rationale | Source |
|---|---|---|---|---|
| pivot_left_bars and pivot_right_bars (set equal) | 3, 5 | EXPERIMENT | Fractal pivot width; 3 is the narrowest symmetric fractal in use in `baseline-v6`, 5 gives fewer and more significant pivots; a pivot is confirmed that many bars after its candle closes. Constraint `pivot_right_bars + 1 <= swing_lookback` holds (6 <= 20). | `baseline-v6` seed 3; 5 is the drafter's design choice; CONFIGURATION section 10 constraint |
| zone_tolerance_atr | 0.5, 1.0 | EXPERIMENT | Half-width of the pivot zone in ATR; the wider value tests a wider pullback zone and a wider stop (see the note after section 2). | `baseline-v6` seed 0.5; 1.0 is the drafter's design choice (one ATR) |
| sl_buffer_atr | 0.2, 0.5 | EXPERIMENT | ATR buffer beyond the outer entry-zone edge for the stop (S2). | `baseline-v6` seed 0.2; 0.5 is the drafter's design choice |
| signal_expiry_hours | 4, 8 | EXPERIMENT | See section 3. | section 3 |

**Fixed in this family:** everything in section 2, plus `swing_lookback` 20 (section 2). No other key exists in a trend-pullback set.

**Grid points** (grid-file order; the first varied key is the slowest-changing, the last the fastest; point a01 equals the `baseline-v6` values and is the reference corner):

| Point id | pivot bars (left = right) | zone_tolerance_atr | sl_buffer_atr | signal_expiry_hours |
|---|---|---|---|---|
| research-run-1-a01 | 3 | 0.5 | 0.2 | 4 |
| research-run-1-a02 | 3 | 0.5 | 0.2 | 8 |
| research-run-1-a03 | 3 | 0.5 | 0.5 | 4 |
| research-run-1-a04 | 3 | 0.5 | 0.5 | 8 |
| research-run-1-a05 | 3 | 1.0 | 0.2 | 4 |
| research-run-1-a06 | 3 | 1.0 | 0.2 | 8 |
| research-run-1-a07 | 3 | 1.0 | 0.5 | 4 |
| research-run-1-a08 | 3 | 1.0 | 0.5 | 8 |
| research-run-1-a09 | 5 | 0.5 | 0.2 | 4 |
| research-run-1-a10 | 5 | 0.5 | 0.2 | 8 |
| research-run-1-a11 | 5 | 0.5 | 0.5 | 4 |
| research-run-1-a12 | 5 | 0.5 | 0.5 | 8 |
| research-run-1-a13 | 5 | 1.0 | 0.2 | 4 |
| research-run-1-a14 | 5 | 1.0 | 0.2 | 8 |
| research-run-1-a15 | 5 | 1.0 | 0.5 | 4 |
| research-run-1-a16 | 5 | 1.0 | 0.5 | 8 |

Points in this family: 16 (budget 25).

## 5. Family B - breakout-retest

**Hypothesis (from `docs/research/families/breakout-retest.md` section 1).** If price breaks a structure zone on a single closed 1H close in the direction of the 4H regime (B1) and then retests the broken edge without breaking down, entering at the retest with the stop beyond the far edge of the broken zone and exiting at the measured move, has a net expectancy above zero after costs; the retest filters out a fraction of false breakouts compared with entering at the breakout bar. The registered geometry is the Stage B baseline as implemented in Phase 15 (deviations in the sheet section 3.2 and D054). Null: mean net R per trade is at most 0.

**Varied parameters (16 points, 2 x 2 x 2 x 2):**

| Key | Values | Label | Rationale | Source |
|---|---|---|---|---|
| retest_window_bars | 5, 10 | EXPERIMENT | Bars after the breakout in which the retest must occur (sheet Q4); the longer window admits later retests. | `baseline-v6` seed 5; 10 is the drafter's design choice (double) |
| retest_depth_atr | 0.3, 0.6 | EXPERIMENT | Maximum distance of the retest from the broken edge in ATR (sheet section 6); the deeper value admits shallower and deeper retests. | `baseline-v6` seed 0.3; 0.6 is the drafter's design choice (double) |
| zone_tolerance_atr | 0.5, 1.0 | EXPERIMENT | Half-width of the broken S/R zone in ATR; it also sets the far-edge stop (see the note after section 2). | `baseline-v6` seed 0.5; 1.0 is the drafter's design choice |
| signal_expiry_hours | 4, 8 | EXPERIMENT | See section 3. | section 3 |

**Fixed in this family:** everything in section 2, plus `breakout_confirmation_bars` 1 (STRUCTURAL: one close beyond the zone, sheet Stage B baseline B1) and `sl_buffer_atr` 0.2 (EXPERIMENT: ATR buffer beyond the far zone edge, seed of `baseline-v6`, held to keep the grid at four factors). Pivot keys do not exist in a breakout-retest set.

**Grid points** (grid-file order; point b01 equals the `baseline-v6` values and is the reference corner):

| Point id | retest_window_bars | retest_depth_atr | zone_tolerance_atr | signal_expiry_hours |
|---|---|---|---|---|
| research-run-1-b01 | 5 | 0.3 | 0.5 | 4 |
| research-run-1-b02 | 5 | 0.3 | 0.5 | 8 |
| research-run-1-b03 | 5 | 0.3 | 1.0 | 4 |
| research-run-1-b04 | 5 | 0.3 | 1.0 | 8 |
| research-run-1-b05 | 5 | 0.6 | 0.5 | 4 |
| research-run-1-b06 | 5 | 0.6 | 0.5 | 8 |
| research-run-1-b07 | 5 | 0.6 | 1.0 | 4 |
| research-run-1-b08 | 5 | 0.6 | 1.0 | 8 |
| research-run-1-b09 | 10 | 0.3 | 0.5 | 4 |
| research-run-1-b10 | 10 | 0.3 | 0.5 | 8 |
| research-run-1-b11 | 10 | 0.3 | 1.0 | 4 |
| research-run-1-b12 | 10 | 0.3 | 1.0 | 8 |
| research-run-1-b13 | 10 | 0.6 | 0.5 | 4 |
| research-run-1-b14 | 10 | 0.6 | 0.5 | 8 |
| research-run-1-b15 | 10 | 0.6 | 1.0 | 4 |
| research-run-1-b16 | 10 | 0.6 | 1.0 | 8 |

Points in this family: 16 (budget 25).

## 6. Family C - range-mr

**Hypothesis (from `docs/research/families/range-mr.md` section 1).** When the 4H regime is neither a clean up-trend nor a clean down-trend (the filter is ON; NO_TRADE otherwise), buying at the range-low and selling at the range-high with the stop outside the range zone and the take-profit at the range midpoint (T_MID) has a net expectancy above zero after costs. The registered geometry is the Stage C baseline as implemented in Phase 15 (deviations in the sheet section 3.2 and D054). Null: mean net R per trade is at most 0. The filter-off diagnostic and `T_OPPOSITE` are not part of this draft (they would need their own sets, sheet section 3.2).

**Varied parameters (16 points, 2 x 2 x 2 x 2):**

| Key | Values | Label | Rationale | Source |
|---|---|---|---|---|
| regime_filter_lookback | 50, 100 | EXPERIMENT | 4H bars searched for the pivots of the regime verdict (about 8 days versus about 17 days). | `baseline-v6` seed 50; 100 is the drafter's design choice (double) |
| zone_min_touches | 2, 3 | EXPERIMENT | Earlier touches a range edge needs before a setup is admitted (sheet section 6); more touches means a more established edge and fewer setups. | `baseline-v6` seed 2; 3 is the drafter's design choice (next integer) |
| range_break_buffer_atr | 0.2, 0.5 | EXPERIMENT | ATR buffer past a range edge that counts as a range break and invalidates the range (sheet section 2.4). | `baseline-v6` seed 0.2; 0.5 is the drafter's design choice |
| signal_expiry_hours | 4, 8 | EXPERIMENT | See section 3. | section 3 |

**Fixed in this family:** everything in section 2, plus `tp_mode` T_MID (STRUCTURAL: sheet Stage C baseline T-mid, CONTEXT Phase 15 D-10), `pivot_left_bars` 3 and `pivot_right_bars` 3 (EXPERIMENT, seed of `baseline-v6`, fractal width held), `zone_tolerance_atr` 0.5, `entry_buffer_atr` 0.1 (section 2), `sl_buffer_atr` 0.2 (EXPERIMENT, seed), `zone_aging_bars` 50 (EXPERIMENT, seed; bars after which a zone ages out), `touch_tolerance_atr` 0.3 (EXPERIMENT, seed; touch tolerance in ATR). Whether every combination of these keys passes the registry's structural checks is verified at registration (plan 16-45 Task 3), not assumed here.

**Grid points** (grid-file order; point c01 equals the `baseline-v6` values and is the reference corner):

| Point id | regime_filter_lookback | zone_min_touches | range_break_buffer_atr | signal_expiry_hours |
|---|---|---|---|---|
| research-run-1-c01 | 50 | 2 | 0.2 | 4 |
| research-run-1-c02 | 50 | 2 | 0.2 | 8 |
| research-run-1-c03 | 50 | 2 | 0.5 | 4 |
| research-run-1-c04 | 50 | 2 | 0.5 | 8 |
| research-run-1-c05 | 50 | 3 | 0.2 | 4 |
| research-run-1-c06 | 50 | 3 | 0.2 | 8 |
| research-run-1-c07 | 50 | 3 | 0.5 | 4 |
| research-run-1-c08 | 50 | 3 | 0.5 | 8 |
| research-run-1-c09 | 100 | 2 | 0.2 | 4 |
| research-run-1-c10 | 100 | 2 | 0.2 | 8 |
| research-run-1-c11 | 100 | 2 | 0.5 | 4 |
| research-run-1-c12 | 100 | 2 | 0.5 | 8 |
| research-run-1-c13 | 100 | 3 | 0.2 | 4 |
| research-run-1-c14 | 100 | 3 | 0.2 | 8 |
| research-run-1-c15 | 100 | 3 | 0.5 | 4 |
| research-run-1-c16 | 100 | 3 | 0.5 | 8 |

Points in this family: 16 (budget 25).

## 7. What happens after the user decides

- **Approve as drafted, or approve with changes:** the approval and the user's words are recorded verbatim in `decisions/16-DEC-O-02.md`. Then Task 3 writes the approved hypothesis (no DRAFT line), one TOML set per approved point under `params/<family>/`, one pin entry per set in `tests/fixtures/phase4/parameters.json`, and the grid file `docs/research/preregistration/research-run-1-grid.json`, and records the grid hash. Sets for families the user did not choose are not created. The strategy version of the new sets (a new version where behavior differs from `baseline-v6`) is settled at Task 3 against the registry gate; no committed set is edited.
- **User writes their own, or postpones:** this draft is discarded or kept as history; nothing is registered.
- In every case the research run itself needs a separate authorization by the user (O-03).

## 8. What this draft does not claim

It does not claim that any value is good, that any family is promising, that the grid will produce a passing candidate, or that the G1 trade floor is reachable. Reference-corner points reproduce the seed values of `baseline-v6`, which were themselves chosen without evidence. A narrow isolated optimum, should one ever appear, is a robustness warning and not a finding (R2).
