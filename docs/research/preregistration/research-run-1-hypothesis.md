# Research run 1 - hypothesis and parameter grid (approved by the user at decision O-02)

> Status: APPROVED WITH CHANGES by the user on 2026-10-12, recorded verbatim in `.planning/phases/16-paper-runtime-composition/decisions/16-DEC-O-02.md` (option approve-with-changes). Registered by Phase 16 plan 16-45 Task 3. The agent draft it derives from is kept unchanged as history in `docs/research/preregistration/research-run-1-hypothesis-DRAFT.md` (commit e9eb307).
> **This approval is NOT an authorization to run research.** It authorizes only the registration of the sets and grids below. Every real research run needs its own user authorization (O-03, plan 16-46), and none may be requested before the blocker in section 8 (cross-family multiplicity) is resolved by a decision or protocol amendment.
> No experiment has been recorded and `docs/research/holdout_consumed.json` has no entries, so no research result existed when this was written or approved. No value was chosen, ranked or tuned from a backtest or any count (D059 item 5, anti-overfitting rules R1 to R6). The holdout is not read by this registration.

## 0. What the user decided at O-02 (approve-with-changes)

1. **Scope.** All three families are registered: trend-pullback, breakout-retest and range-mr. Each keeps the 16-point 2 x 2 x 2 x 2 grid of the draft (48 points in total, 16 per family, inside the variant budget N = 25 per family of the protocol). No point is added, removed or changed after results start to be seen.
2. **Fixed values.** `max_cost_to_risk` stays 0.15 and is not varied (revisit only by a new set chosen before any result, D046 item 6). `signal_expiry_hours` stays {4, 8}. The EXPERIMENT label means "fixed and preregistered before any result", not "shown to be good". No PLACEHOLDER label is used.
3. **Expiry semantics** (section 3).
4. **`constraint_snapshot_ttl_seconds` = 2400**, label DECISION, source O-07 (`decisions/16-DEC-O-07.md`), in every set. Nuance in section 3.
5. **Blocker**: cross-family multiplicity (section 8).
6. **Allowed now:** create the immutable parameter sets and the preregistration grids by the existing process. **Not allowed:** authorizing any research run; reading or consuming the holdout in the feasibility gate; editing a grid after registration to re-run the same experiment; changing any other decision or threshold.

## 1. Rules this registration follows

- Closed-bar decisions only; execution at 1m; costs from experiment 1 (R4); NO_TRADE is a valid outcome (R5, R6).
- Every grid point is a new, immutable parameter set `params/<family>/research-run-1-<point>.toml`. No committed set is edited (AGENTS.md). Each set has a complete `[rationale.<key>]` table and no PLACEHOLDER label, and a pin entry in `tests/fixtures/phase4/parameters.json`.
- Provenance labels used: STRUCTURAL (fixed by a spec), COST_GUARD (a guard of D046), DECISION (a DECISIONS row or a user decision record), EXPERIMENT (a setting or a varied value fixed by this preregistration; its `ref` is `research-run-1/O-02`).
- The 40/40/20 split, four validation folds, G1 to G5, the single-use holdout and the cost model are the frozen protocol v2.2.0 and are not part of this registration. The data window, universe and split dates are decided separately at O-03.
- Power note (protocol section 4, D043): with sigma about 1.2 R the trade floor of G1 (100 pooled, 30 per fold) detects only a large edge, and the floor may be unreachable at the decided dataset depth. A shortfall is reported, never papered over. Neither fact is a reason to change a value.
- `strategy_version` stays `v5.0.0` for all 48 sets. The strategy code and geometry are those of `baseline-v6`; the points differ in parameter values only, as `baseline-no-trade-v4` and `baseline-simple-trend-v4` already do at the same version. A parameter set is identified by its id and its hash, and a lineage (protocol, holdout marker) is a `strategy_id` plus its `strategy_version`, so one lineage per family covers its 16 points.

## 2. Values that are fixed in every family

Same value in all points of all families unless a family section says otherwise. `Source` names where the value or its label comes from.

| Key | Value | Label | Rationale | Source |
|---|---|---|---|---|
| geometry_version | 1 | DECISION | Selects the corrected Phase 15 geometry (pivot-anchored levels, stop outside the zone). | D054 |
| min_stop_atr | 0.5 | EXPERIMENT | Planner invariant: minimum entry-to-stop distance in ATR; fixed so that it is not a degree of freedom of this run. | CONTEXT Phase 15 D-08, `baseline-v6`, CONFIGURATION section 10 |
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
| expected_slippage | 0.0001 | DECISION | Entry-side slippage, non-zero from experiment 1 (R4). | D046 |
| exit_slippage_rate | 0.0003 | DECISION | Stop-market exit slippage. | D046 |
| min_stop_distance_rate | 0.003 | COST_GUARD | A stop closer than this fraction of price is rejected (STOP_TOO_TIGHT). | D046 |
| max_cost_to_risk | 0.15 | COST_GUARD | Kept at its current value; revisit only by a new set chosen before any result, D046 item 6. | D046 |
| commission_rate_ttl_seconds | 3600 | DECISION | Freshness window of the live commission rate. | D046 |
| constraint_snapshot_ttl_seconds | 2400 | DECISION | Freshness window of the exchange-constraint snapshot; changed from the `baseline-v6` value 3600 by the user decision O-07 (user, 2026-10-10). The registry requires a `D<3 digits>` ref for the DECISION label, so the set files cite D063 (item 1: O-07 is user-owned) and name O-07 and `decisions/16-DEC-O-07.md` in the text. See the nuance in section 3. | O-07 (`decisions/16-DEC-O-07.md`), D063 |
| funding_treatment | ADDITIVE | EXPERIMENT | Funding treatment declared for the cost model; the simulator charges funding at every actual `fundingTime`. | RESEARCH_PROTOCOL section 2, D052 |
| slippage_model | FIXED_BPS | EXPERIMENT | Slippage model declared for the cost model. | RESEARCH_PROTOCOL section 2 |
| spread_fill_assumptions | FULL_FILL | EXPERIMENT | Spread and fill assumption declared for the cost model. | RESEARCH_PROTOCOL section 2, D038 |
| partial_fill_fraction | 1.0 | DECISION | Full fills for all canonical cost sets. | D038 |
| working_type | MARK_PRICE | DECISION | Protective triggers on mark price. | D037 |
| atr_period | 14 | EXPERIMENT | ATR lookback (families B and C key); held at the seed. | `baseline-v6` seed (a common default, no spec fixes it) |

Note on `max_cost_to_risk` and the stop width: with 0.15 the cost-to-risk guard is the binding gate and implies a minimum stop of about 0.79 percent of price (CONFIGURATION section 10, D046 item 6). The stop distance is built from zone width and buffers measured in ATR, so wider values of `zone_tolerance_atr` and `sl_buffer_atr` reduce the share of plans rejected by this guard. That is arithmetic from D046, not a result, and it is the reason the upper values below are included.

## 3. Candidate parameters, expiry semantics and the TTL nuance

**Candidate parameter.** A candidate parameter is a key that a grid varies. `signal_expiry_hours` is a candidate parameter in every family (O-08): hours from the source candle close until the signal expires; seed 4, alternative 8 (two 4H strategy bars of validity versus one). Source for 4: `baseline-v6` seed; source for 8: the drafter's design choice, the next whole multiple of the 4H decision bar; no document fixes either. The other varied keys are listed in the family sections.

**Expiry semantics (O-02 change 3).**

- `signal_expiry_hours` decides the plan expiry under the existing semantics: the plan's `expiry_utc` is the source candle close plus `signal_expiry_hours`.
- The CONFIRM card TTL of D041 is a different concept. It is 60 s by default and configurable; it is not an invariant of the protocol, and O-02 changes no configuration and adds no CONFIRM TTL. It is never mixed with the plan expiry.
- CONFIRM does not revive an expired plan and does not restart the plan's expiry clock.
- A reservation never outlives the original plan's expiry and has no TTL of its own (Q-C, `decisions/16-DEC-Q-C.md`).

**What `constraint_snapshot_ttl_seconds` = 2400 changes (O-02 change 4).** In this repository `ttl_from_parameter_set` (`src/execution/constraint_snapshot.py`) is called by no production path (tests only). The simulator uses `timedelta(0)` (`src/backtest/engine.py:755`) and the paper runtime takes the TTL from the runtime configuration (`src/paper/runtime.py:830`). Changing the field from 3600 to 2400 therefore changes **only the parameter-set hash**; it does not change simulator behaviour, and the simulator does **not** apply 2400. Wiring the field into the simulator needs its own decision and plan and a review of the semantics and digest consequences.

Point 01 of each family is described exactly as: Matches the baseline-v6 seed values except for `constraint_snapshot_ttl_seconds`.

## 4. Family A - trend-pullback

**Hypothesis (from `docs/research/families/trend-pullback.md` section 1).** If the 4H regime is directional and price pulls back to a confirmed 1H structure zone in the direction of the trend, entering at the zone with the stop outside the zone, and exiting at the structure target with the TP1/TP2 ladder, has a net expectancy above zero after taker fees, slippage and funding. The registered geometry is the Stage A baseline as implemented in Phase 15 (EMA50 4H regime proxy, P1 zone touch, E2 entry, S2 stop, structure target; deviations recorded in the sheet section 3.2 and D054). Null: mean net R per trade is at most 0 (G2, G3).

**Varied parameters (16 points, 2 x 2 x 2 x 2):**

| Key | Values | Label | Rationale | Source |
|---|---|---|---|---|
| pivot_left_bars and pivot_right_bars (set equal; grid axis `pivot_bars`) | 3, 5 | EXPERIMENT | Fractal pivot width; 3 is the narrowest symmetric fractal in `baseline-v6`, 5 gives fewer and more significant pivots; a pivot is confirmed that many bars after its candle closes. The registry rule `pivot_right_bars + 1 <= swing_lookback` holds (6 <= 20). | `baseline-v6` seed 3; 5 is the drafter's design choice; CONFIGURATION section 10 constraint |
| zone_tolerance_atr | 0.5, 1.0 | EXPERIMENT | Half-width of the pivot zone in ATR; the wider value tests a wider pullback zone and a wider stop (see the note after section 2). | `baseline-v6` seed 0.5; 1.0 is the drafter's design choice (one ATR) |
| sl_buffer_atr | 0.2, 0.5 | EXPERIMENT | ATR buffer beyond the outer entry-zone edge for the stop (S2). | `baseline-v6` seed 0.2; 0.5 is the drafter's design choice |
| signal_expiry_hours | 4, 8 | EXPERIMENT | See section 3. | section 3 |

**Fixed in this family:** everything in section 2, plus `swing_lookback` 20. No other key exists in a trend-pullback set.

**Grid points** (grid-file order: the first varied key is the slowest-changing, the last the fastest). Point a01 matches the baseline-v6 seed values except for `constraint_snapshot_ttl_seconds`.

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
| retest_depth_atr | 0.3, 0.6 | EXPERIMENT | Maximum distance of the retest from the broken edge in ATR (sheet section 6). | `baseline-v6` seed 0.3; 0.6 is the drafter's design choice (double) |
| zone_tolerance_atr | 0.5, 1.0 | EXPERIMENT | Half-width of the broken S/R zone in ATR; it also sets the far-edge stop (see the note after section 2). | `baseline-v6` seed 0.5; 1.0 is the drafter's design choice |
| signal_expiry_hours | 4, 8 | EXPERIMENT | See section 3. | section 3 |

**Fixed in this family:** everything in section 2, plus `breakout_confirmation_bars` 1 (STRUCTURAL: one close beyond the zone, sheet Stage B baseline B1) and `sl_buffer_atr` 0.2 (EXPERIMENT: ATR buffer beyond the far zone edge, seed of `baseline-v6`, held to keep the grid at four factors). Pivot keys do not exist in a breakout-retest set.

**Grid points** (grid-file order). Point b01 matches the baseline-v6 seed values except for `constraint_snapshot_ttl_seconds`.

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

**Hypothesis (from `docs/research/families/range-mr.md` section 1).** When the 4H regime is neither a clean up-trend nor a clean down-trend (the filter is ON; NO_TRADE otherwise), buying at the range-low and selling at the range-high with the stop outside the range zone and the take-profit at the range midpoint (T_MID) has a net expectancy above zero after costs. The registered geometry is the Stage C baseline as implemented in Phase 15 (deviations in the sheet section 3.2 and D054). Null: mean net R per trade is at most 0. The filter-off diagnostic and `T_OPPOSITE` are not part of this registration (they would need their own sets, sheet section 3.2).

**Varied parameters (16 points, 2 x 2 x 2 x 2):**

| Key | Values | Label | Rationale | Source |
|---|---|---|---|---|
| regime_filter_lookback | 50, 100 | EXPERIMENT | 4H bars searched for the pivots of the regime verdict (about 8 days versus about 17 days). | `baseline-v6` seed 50; 100 is the drafter's design choice (double) |
| zone_min_touches | 2, 3 | EXPERIMENT | Earlier touches a range edge needs before a setup is admitted (sheet section 6); more touches means a more established edge and fewer setups. | `baseline-v6` seed 2; 3 is the drafter's design choice (next integer) |
| range_break_buffer_atr | 0.2, 0.5 | EXPERIMENT | ATR buffer past a range edge that counts as a range break and invalidates the range (sheet section 2.4). | `baseline-v6` seed 0.2; 0.5 is the drafter's design choice |
| signal_expiry_hours | 4, 8 | EXPERIMENT | See section 3. | section 3 |

**Fixed in this family:** everything in section 2, plus `tp_mode` T_MID (STRUCTURAL: sheet Stage C baseline T-mid, CONTEXT Phase 15 D-10), `pivot_left_bars` 3 and `pivot_right_bars` 3 (EXPERIMENT, seed of `baseline-v6`), `zone_tolerance_atr` 0.5, `sl_buffer_atr` 0.2 (EXPERIMENT, seed), `zone_aging_bars` 50 (EXPERIMENT, seed; bars after which a zone ages out), `touch_tolerance_atr` 0.3 (EXPERIMENT, seed; touch tolerance in ATR).

**Structural rules of the registry for this family (checked at registration).** Pivot widths are fixed at 3, so `pivot_right_bars + 1` = 4 is within `swing_lookback` (20) and within both values of `regime_filter_lookback` (50, 100); `zone_aging_bars` 50 is a plain integer count with no registry range rule (the detector needs `swing_lookback + zone_aging_bars + 1` = 71 setup bars of history before it can emit a setup, a warm-up fact and not a validity rule). All 16 combinations load and every point is reported STRUCTURALLY_VALID by `python -m src.research.register --list-grid`. No combination of the draft was found structurally invalid and no value was changed from the draft.

**Grid points** (grid-file order). Point c01 matches the baseline-v6 seed values except for `constraint_snapshot_ttl_seconds`.

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

## 7. Registration

One `ParameterGrid` (`src/research/manifest.py`) binds one `strategy_id` and the runner loads every point of a grid under that id, so the preregistration is three grid files, one per family, in place of a single `research-run-1-grid.json`. Each grid lists the 16 points in the order above with the parameter-set id, the loader hash and the varied keys.

| Family | Grid file | Grid hash (`grid_hash`) | Set ids |
|---|---|---|---|
| trend-pullback | `docs/research/preregistration/research-run-1-grid-trend-pullback.json` | `13207b306df9a2bc1d580df456b1e6a3d3478eff82c5eb1ff6ac6a9daac14411` | `research-run-1-a01` to `a16` |
| breakout-retest | `docs/research/preregistration/research-run-1-grid-breakout-retest.json` | `2ed8577ea225b294eaaa82c4478fee6dbf2b3d5a76eca8f967b5d769171c4069` | `research-run-1-b01` to `b16` |
| range-mr | `docs/research/preregistration/research-run-1-grid-range-mr.json` | `3388fceb664ba7999477070ef9d49f15ccff0b073d3587ad58351dd5c5d297c6` | `research-run-1-c01` to `c16` |

The 48 set files are `params/<family>/research-run-1-<letter><nn>.toml`; each has a pin entry in `tests/fixtures/phase4/parameters.json` with the loader hash. In the Family A grid the axis `pivot_bars` stands for `pivot_left_bars` and `pivot_right_bars` set equal. Registered sets are never edited in place: a later change is a new set, a new registration and, where behaviour differs, a new `strategy_version` (REV-05).

## 8. Blockers (nothing here may be skipped)

1. **Cross-family multiplicity.** The protocol corrects multiplicity only inside each family (Holm-Bonferroni per family, `docs/research/RESEARCH_PROTOCOL.md` line ~250: about 14% worst-case family-wise false-pass rate across three families). Registering all three families makes this layer real. Before O-03 and before any real research execution a user decision or a protocol amendment must resolve cross-family multiplicity. Until then "at least one family PASSES" must not be read as an overall confirmation. `RESEARCH_PROTOCOL.md` is not edited by this registration.
2. **No research authorization.** Registration does not authorize a run. Each real run needs its own O-03 authorization.
3. **Dataset, manifest and feasibility** (window, universe, split dates, constraint source) are decided at O-03 and are outside this registration. The holdout must not be read or consumed in the feasibility gate.
4. **The `constraint_snapshot_ttl_seconds` field is not wired into the simulator** (section 3); a decision to wire it needs its own plan.

## 9. What this registration does not claim

It does not claim that any value is good, that any family is promising, that the grid will produce a passing candidate, or that the G1 trade floor is reachable. Point 01 of each family reproduces the seed values of `baseline-v6` (except the TTL), which were themselves chosen without evidence. A narrow isolated optimum, should one ever appear, is a robustness warning and not a finding (R2).
