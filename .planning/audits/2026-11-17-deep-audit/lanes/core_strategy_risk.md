# Lane M01: core_strategy_risk

## Scope

`src/core/*`; `src/domain/*` except `exchange_errors.py`, `algo_status.py`, `stream_records.py`;
`src/risk/{sizing,quantization,portfolio,gating,cost_rates,cost_guards,realized_risk,types}.py`; `params/**`.
Snapshot commit `55885b9`. Finding IDs G-0100..G-0199.

(Sections below are appended incrementally; the final consolidated tables are at the end when `## DONE` is present.)

## Progress log (partial-run notes; superseded by the final sections below when present)

- [read pass 1 done] DEEP_READ: src/core/{planner,strategy,features,pivots,types,_decimal,__init__}.py;
  src/risk/{sizing,quantization,gating,cost_rates,cost_guards,realized_risk,portfolio,types}.py;
  src/domain/{registry,canonical,ids,trade_plan,signal,lot_filters,rationale,transitions,enums,approval,order,fill,position,journal,__init__}.py.
- Leads to probe (not yet findings):
  L1 cluster_cap (0.005) == risk_rate (0.005) and thresholds are resolved on DAY-START equity while
     allowed_risk uses CURRENT equity -> after an intraday gain a ~100 % utilised candidate exceeds the cap.
  L2 forming-bar gate in strategy.evaluate compares close_time to prev.close_time + duration; a Binance
     in-progress kline carries its scheduled close time, so the gate cannot see it. Check upstream guard.
  L3 no cross-stream check that context (4H) last close <= setup (1H) last close in evaluate().
  L4 small-capital tradability (equity 500/1000, risk 0.5 %): MIN_QTY / NOTIONAL / UTILIZATION rejects.
  L5 registry: no required-key schema, several keys unranged; rationale not hashed.
  L6 EMA is seeded on the window start -> value depends on window length (parity backtest/paper/live).

---

# FINAL SECTIONS (consolidated; the progress log above is superseded)

Probes (all read-only, snapshot code imported, outputs saved next to the scripts):
`tmp/core_strategy_risk/probe_sizing.py|.out`, `probe_edge.py|.out`, `probe_core.py|.out`, `probe_guards.py|.out`.
Exchange filters used in the probes are those of `tests/fixtures/exchange_info_sample.json` (recorded 2026-09-19);
prices are round assumptions (BTC 100000, ETH 3500, SOL 200, XRP 2.5). No network call was made.

## Coverage

| File | Level | Note |
|---|---|---|
| src/core/planner.py | DEEP_READ | all geometry branches, validator, TP2 guard, hash |
| src/core/strategy.py | DEEP_READ | three detectors, regime, forming-bar gate, evaluate |
| src/core/features.py | DEEP_READ | EMA/ATR/swing, gap check, last-bar shortcut |
| src/core/pivots.py | DEEP_READ | confirmation index arithmetic |
| src/core/types.py | DEEP_READ | |
| src/core/_decimal.py | DEEP_READ | |
| src/core/__init__.py | DEEP_READ | |
| src/risk/sizing.py | DEEP_READ | + probe |
| src/risk/quantization.py | DEEP_READ | + probe |
| src/risk/gating.py | DEEP_READ | + probe |
| src/risk/portfolio.py | DEEP_READ | + probe |
| src/risk/cost_rates.py | DEEP_READ | |
| src/risk/cost_guards.py | DEEP_READ | |
| src/risk/realized_risk.py | DEEP_READ | callers located, not read |
| src/risk/types.py | DEEP_READ | |
| src/domain/registry.py | DEEP_READ | + probe (text-level mutations, no file written) |
| src/domain/canonical.py | DEEP_READ | |
| src/domain/rationale.py | DEEP_READ | |
| src/domain/transitions.py | DEEP_READ | + completeness probe |
| src/domain/enums.py | DEEP_READ | |
| src/domain/ids.py, trade_plan.py, signal.py, lot_filters.py | DEEP_READ | |
| src/domain/approval.py, order.py, fill.py, position.py, journal.py, __init__.py | NORMAL_READ | value objects only |
| src/domain/exchange_errors.py, algo_status.py, stream_records.py | NOT_READ | out of lane scope (guard coverage only, via probe) |
| params/range-mr/baseline-v6.toml | DEEP_READ | |
| params/trend-pullback/baseline-v6.toml | NORMAL_READ | by diff against range-mr v6 |
| params/trend-pullback/research-run-1-a01.toml | NORMAL_READ | parameters and rationale labels |
| params/** (other 70 files) | METADATA_ONLY | every file loaded, hashed and compared with the pin file, rationale checked by probe; values not read one by one |
| Out of scope, read only to trace a caller: src/execution/placement.py (150-215), src/backtest/ledger.py (50-215), src/backtest/engine.py (735-900), src/live/risk_inputs.py (600-730), src/live/signal_source.py (330-600), src/paper/bars.py (1-60), src/paper/loop.py (300-400), tests/test_domain_no_float.py, tests/test_candle_close_timing.py, tests/test_core_tracer.py | NORMAL_READ (ranges) | |

## Verified Safe Areas

| Rule or behaviour | What was checked | Where | Why it holds |
|---|---|---|---|
| Quantity floors, never rounds up | code + sweep of 4 symbols x 3 equities x about 150 stop distances x 2 sides | src/risk/quantization.py:91-92; probe_sizing section C | `steps = raw // step`; max realised/allowed over all accepted cases = 0.999997 (never above 1) |
| Gate order: floor, min qty, min notional, utilisation | code | quantization.py:94-136 | fixed order, first failure returns; matches AGENTS "Quantization" |
| Cost guards run before any rounding and cannot be disabled | code | gating.py:102-105, 164-191; cost_guards.py:42-56 | thresholds are required Decimals, range checked, NaN refused |
| Cost unit is quote currency per unit of base (old F-001/F-801/F-126 family) | code + probe numbers | cost_rates.py:122-151 | `entry*(fee+slip) + stop*(fee+slip)`; a rate above 1 % is refused at CostRates and at the registry (probe_core section 4: `fee_rate_entry = 0.02` REFUSED) |
| LONG/SHORT symmetry of sizing | probe section A | probe_sizing.out | realised risk of mirrored plans differs only by the exit-leg price term (BTC 1 %: 2.2784 vs 2.2816) |
| Sized loss covers every reachable fill | code | gating.py:122-126, placement.py:191-202 | sizing uses the adverse zone edge; the entry limit rounds away from paying up; the stop trigger rounds toward the entry, so tick rounding can only lower the loss at the stop |
| Tick rounding direction of SL / TP / entry | code | src/execution/placement.py:160-210 | SL LONG up / SHORT down (tighter), TP toward entry, entry BUY floor / SELL ceil |
| Stop strictly outside the entry zone, signal bar not through the stop, TP1 on the profit side, TP2 > 0 | code | planner.py:373-411, 646-667 | one validator on the stored (quantised) prices, before the RR gate, for every family and both sides |
| Pivots are confirmed only (no lookahead) | index arithmetic | pivots.py:57-70 | candidates are `t <= i - right`, so bar `i` only confirms; strict inequality on the right side |
| Detectors never take a reference level or ATR from the evaluated bar | code | strategy.py:395-417 (B: `ref_prev = i - k - 1`), 569-573 (C: `ref_idx = last - 1`) | |
| Backtest and paper cut the same windows without future bars | code | backtest/engine.py:802-810; paper/bars.py:1-30 | `bisect_right(closes, close)`; 1000 x 1h and 300 x 4h in both |
| Plan identity is stable across storage | code | planner.py:59-92, canonical.py:108-149 | prices quantised to 18 dp before hashing, hashed as spelling-invariant text |
| Parameter sets are hash-locked | probe | probe_core section 3 | 73 files load; every hash is present in tests/fixtures/phase4/parameters.json |
| Unknown key / unit error / bad type refuse to load | probe | probe_core section 4 | `foo = 1`, `fee_rate_entry = 0.02`, `swing_lookback = 0` are REFUSED |
| Provenance labels complete for the current sets | probe | probe_core section 3 | v6 and research-run sets: zero rationale problems (v1-v5 predate rationale tables) |
| Transition tables complete | probe | probe_core section 6 | keys == enum members for all six persisted machines; successors inside the enum; only the initial state is never a successor |
| No float, no wall clock, no third-party import at module level in src/core, src/domain, lane risk files | own AST scan with the project's walkers | probe_guards.out | 0 float shapes, 0 wall-clock calls; only `structlog` imported inside two logging functions (quantization.py:207, gating.py:299, 320) |

## Decision review

| Decision / rule | Verdict | Yardstick | Reason |
|---|---|---|---|
| AGENTS "Quantization floors, never rounds up"; RISK_MANAGEMENT section 11 | SOUND | arithmetic (probe C), risk practice | realised risk never exceeds the budget; NO_TRADE instead of a breach is right for small capital |
| `minimum_risk_utilization_after_rounding` = 0.6 (labelled STRUCTURAL) | DOUBTFUL | arithmetic | the 60 % is a chosen number, not a structural fact; it is measured against a loss that cannot occur (G-0102), so the real floor is about 36 % of the budget for Family A; it also cuts bands out of the BTC stop range (Owner decisions 3) |
| D046 item 1: cost = quote per unit, entry and stop legs | SOUND | arithmetic, exchange (fees are charged on notional per leg) | units right by construction; closes F-001/F-801 |
| D046 item 2: size at the adverse zone edge ("fill anywhere in the zone") | DOUBTFUL | arithmetic, the project's own execution rule | the entry is one LIMIT at the zone mid, so no fill beyond the mid exists; the rule is safe but the real risk is 39-41 % below the budget for Family A; D046 itself says it was "decided in the unattended run without a checkpoint" (G-0102) |
| D046 items 5/6: `max_cost_to_risk` 0.15 binds at a stop of about 0.79 % | SOUND as a guard, value CANNOT_JUDGE | arithmetic (probe B: every stop below 0.80 % is COST_TO_RISK_EXCEEDED) | the derivation in D046 reproduces; whether 15 % is the right ceiling is a research question; the owner ratified it knowing the consequence |
| Tick rounding toward the entry for SL, away from paying up for the entry | SOUND | arithmetic | can only reduce the loss at the stop |
| Phase 15 D-01/D-03 confirmed pivots, no fallback to the trailing extreme | SOUND | logic (no lookahead) | index proof above |
| Phase 15 D-06/D-07/D-08/F6 structural validator before the RR gate | SOUND | logic | closes old F-301 (stop inside the zone) for every set, legacy included |
| TP2 > 0 guard (owner 2026-10-17, Option A) | SOUND | arithmetic | only a SHORT with TP1 <= entry/2 can fail; rejecting is fail closed |
| RR gate on zone-mid risk without costs (`minimum_rr` 2.0, PLACEHOLDER/EXPERIMENT) | CANNOT_JUDGE | research practice | a gross RR is a common filter; the number has no derivation (the files say so) |
| D033 thresholds on day-start equity, sizing on current equity ("two equities, on purpose") | DOUBTFUL | arithmetic | sound for the daily-loss gates; combined with `cluster_cap == risk_rate` it rejects trades after a same-day gain (G-0101) |
| `cluster_cap` = single-trade risk; cluster = BTC/ETH/SOL/XRP same side, hard-coded | DOUBTFUL | risk practice, the 12-symbol research universe | KNOWN:21-DEFERRED (F-908): 8 of the 12 research symbols (BNB, DOGE, 1000PEPE, WIF, SUI, WLD, DOGS, REEF) are outside the cluster although alt-coins move together; bounded by `max_open_positions` 2 and the 1 % aggregate cap |
| Rationale labels; "EXPERIMENT means fixed and preregistered, no PLACEHOLDER label" (16-DEC-O-02) | DOUBTFUL | logic | the label that the paper-start gate reads changed while the values and their "no empirical basis" text did not (G-0105) |
| Hash spelling rule (`0.5` != `0.50`, whole floats become int) | SOUND | logic | fail closed: a respelling is a new hash and is caught by the pin file |
| Closed-candle rule D-02 enforced inside the pure core | DOUBTFUL | exchange (Binance kline format) | the core gate cannot recognise an in-progress Binance kline; the working guard is upstream (G-0104) |
| GLOSSARY section 11 transition tables (D051) | SOUND | logic | complete and consistent with the enums |

## Findings

### G-0101
- ID: G-0101 · Severity: MEDIUM (now) / MEDIUM (mainnet) · Confidence: CONFIRMED · Classification: DESIGN
- Category: risk-gates / research-validity · Component: portfolio gate + ledger thresholds
- File: src/risk/portfolio.py · Lines: 307-322 (with src/backtest/ledger.py:124-198, src/execution/live_risk_inputs.py:15-19, params `cluster_cap = 0.005`)
- Rule: RISK_MANAGEMENT section 4 (cluster cap), D033, 16-DEC-EQUITY-BASE · Known-prior: KNOWN:16-43 for the loss direction only (closed 2026-11-08); the gain direction is not recorded anywhere I could find
- Evidence: `cluster_sum = _add(cluster_open_risk, candidate_risk)` / `if cluster_sum > cluster_cap_quote:` gives `CLUSTER_CAP_REJECT` (portfolio.py:315-316). The cap is `cluster_cap x equity_at_day_start` (`thresholds=_resolve_thresholds(params, equity)` at ledger start and in `_roll`, ledger.py:104, 156) while `apply_booking` changes `equity` inside the day without touching `thresholds` (ledger.py:193-198), and sizing uses `AccountState(equity=self.ledger.equity, ...)` (engine.py:858). live_risk_inputs.py:15-19 states the same split for live: "Two equities, on purpose". Every current set has `cluster_cap = 0.005` and the configured `risk_rate` is `0.005` (config/paper/paper-runtime-v2.toml:30). Probe (probe_edge.out F, probe_sizing.out D): day start 1000, +10 booked the same UTC day, empty book: XRPUSDT candidate realised risk 5.0495 vs cap 5.000 gives `CLUSTER_CAP_REJECT`; day start 600, +6: XRP 3.0274 and SOL 3.0075 vs cap 3.000 are rejected; BTC (utilisation 0.76-0.91 because of its coarse step) passes.
- Expected: a single candidate on an empty book, sized to the per-trade budget, is not rejected by the correlation cap.
- Actual: after any realised gain in the UTC day, a candidate whose utilisation exceeds `day_start_equity / current_equity` (99.0 % after +1 %, 99.8 % after +0.2 %) is rejected until 00:00 UTC. Fine-step symbols (XRP, SOL, ETH and the alt-coins) are near 99.9 % utilised, so they are the ones hit. Also, the cluster sum is compared for a candidate that is NOT in the cluster (`candidate_in_cluster` false, sum = candidate risk, still compared, lines 309-316), so a BNB or DOGE candidate would get the reason `CLUSTER_CAP_REJECT` too (read from the code; the BNB case of the probe passed only because its step left it at 4.99).
- Reproduction: `tmp/core_strategy_risk/probe_edge.py` (section F) and `probe_sizing.py` (section D).
- Impact: no money is lost (the gate fails closed). Research and paper evidence is biased: trades that follow a same-day win are removed for most symbols and kept for BTC, and trades after a loss are kept. The trade set of a backtest then depends on booking order and on step size, not only on the strategy. Live would refuse valid approvals at CONFIRM with a misleading reason, as in the 16-43 incident.
- Why tests miss it: the fixtures test the cap with open positions or with equal equities; 16-43 fixed and tested the loss direction. I found no test that books a gain and then evaluates a candidate on an empty book.
- Remediation (options for the owner, not chosen here): compare the per-trade risk against one base (size against the smaller of current and day-start equity, or resolve the cluster cap on current equity); or set the cluster cap above the single-trade risk; and skip the cluster comparison when the candidate is outside the cluster. Any of these changes the trade set, so it needs a new parameter set / strategy version and regenerated research records.

### G-0102
- ID: G-0102 · Severity: LOW (now) / MEDIUM (mainnet) · Confidence: CONFIRMED · Classification: DESIGN
- Category: sizing / reporting · Component: adverse-edge sizing, R denominator, utilisation gate
- File: src/risk/gating.py · Lines: 122-131, 193-200 (with src/core/planner.py:150-157, 609-616; src/risk/realized_risk.py:1-10; src/execution/placement.py:118-133)
- Rule: D046 item 2 (Phase 12 D-03), RISK_MANAGEMENT lines 34-41, Phase 14 D-20 · Known-prior: KNOWN:D046 states the consequence in words ("a mid-fill loss sits below budget by about (edge minus mid) times quantity") but not its size under the Phase 15 geometry
- Evidence: gating.py:14-19 "Sizing uses the ADVERSE edge of the entry zone ... The zone mid REMAINS the quantizer's min-notional reference price, because it is the price the order is actually placed at." The entry is one LIMIT at the zone mid (`derive_limit_price`, placement.py:118-133; backtest `snapped_limit_price`, src/backtest/entry.py:44-45), and a BUY limit cannot fill above its price. Family A geometry_version 1: zone = pivot +/- 0.5 ATR, entry range 0.1 ATR wider on each side, stop = pivot - 0.8 ATR (planner.py:150-156, 609-610), so the sized distance is 1.4 ATR and the largest reachable distance is 0.8 ATR. Probe (probe_edge.out E, equity 1000, budget 5.00): Family A recorded `realized_risk` 4.9964, loss at the stop for a fill at the limit incl. modelled costs 3.0482 = 61.0 % of budget (59.1 % at ATR 2 %); Family B 93 %; Family C 89 %. D046 records the rule as "reversibility one-way, decided in the unattended run without a checkpoint".
- Expected: the risk the owner sets (0.5 % of equity) is what a stopped-out trade loses, within rounding; an R multiple of -1 means a full stop.
- Actual: a Family A trade risks about 0.30 % of equity, not 0.50 %. `realized_risk` (the R denominator: realized_risk.py:1-10, used at engine.py:573, records.py:394, analytics/live_outcomes.py:300) is the adverse-edge figure, so a full stop-out is booked as about -0.6 R for Family A and about -0.9 R for B/C. The 60 % utilisation gate and the cluster/aggregate caps use the larger figure too.
- Reproduction: `tmp/core_strategy_risk/probe_edge.py` section E.
- Impact: safe side for money. For decisions: R figures of the three families are on different scales (cross-family comparison and planning figures such as "sigma about 1.2 R" in RESEARCH_PROTOCOL are affected; the sign tests G2/G3 are not); the daily stop of 1 % equals about 3.3 Family A stop-outs instead of 2; the owner reads "risk 0.5 %" for a trade that can lose 0.3 %.
- Why tests miss it: the property tests assert loss <= budget, which holds; nothing asserts that the loss of the reachable fill is close to the budget.
- Remediation: owner choice (Owner decisions 2): keep and document the real per-family risk, or size at the limit price actually placed (the only reachable worst case for a single limit), which changes quantities and needs regenerated records.

### G-0103
- ID: G-0103 · Severity: LOW (now) / MEDIUM (mainnet) · Confidence: PROBABLE (core behaviour CONFIRMED by probe; reachability from the runtimes not traced, other lanes) · Classification: GAP
- Category: fail-closed / data freshness · Component: strategy.evaluate, MarketSnapshot
- File: src/core/strategy.py · Lines: 680-735, 776-782 (src/core/types.py:270-291)
- Rule: AGENTS "Fail closed. Uncertain data ... NO_TRADE"; "no future-candle leakage" · Known-prior: none found
- Evidence: `evaluate` checks each stream alone (interval known, internal gaps via `compute_features`) and never compares `context_candles[-1].close_time_utc` with `setup_candles[-1].close_time_utc`; `MarketSnapshot.__post_init__` checks types only. Probe (probe_core.out 1), trend-pullback baseline-v6, same 1h stream: context aligned gives regime BULLISH; context ending 10 days earlier gives BULLISH; 90 days earlier gives BULLISH; context ending 8 hours LATER than the setup bar (future bars) gives BULLISH. None returns DATA_STALE.
- Expected: a context stream whose last bar is older than one context interval, or newer than the evaluated bar, is uncertain data and gives NO_TRADE in the core, as an internal gap does.
- Actual: the regime is computed from whatever the caller passes. Correctness rests on the callers' window cut (`bisect_right` in backtest/engine.py:807-810 and paper/bars.py), which prevents future bars but not a missing newest 4h bar (the cut simply returns the older window).
- Reproduction: `tmp/core_strategy_risk/probe_core.py` section 1.
- Impact: if the newest 4h bar is late or missing while 1h bars keep arriving, the direction filter uses a stale regime and paper/live differ from the backtest for the same bar, with no reason code. Bounded by human approval and by whatever feed-liveness checks the runtimes have (not verified here).
- Why tests miss it: tests feed aligned fixtures; the gap test injects a gap inside a stream, never a trailing one.
- Remediation: in `evaluate`, return DATA_STALE unless `setup_close - context_interval < context_last_close <= setup_close`.

### G-0104
- ID: G-0104 · Severity: LOW (now) / LOW (mainnet) · Confidence: CONFIRMED · Classification: DEFECT
- Category: closed-candle rule / test validity · Component: forming-bar gate
- File: src/core/strategy.py · Lines: 81-92, 806-825 (test: tests/test_candle_close_timing.py:155-196)
- Rule: D-02 / STRAT-01 "the engine must NEVER source a SETUP from an unclosed candle" · Known-prior: none found
- Evidence: `expected_close = prev.close_time_utc + duration; return candle.close_time_utc < expected_close` (strategy.py:90-92). A Binance kline that is still forming carries its scheduled close time (open + interval - 1 ms), the same value it has when closed, so the comparison is False. Probe (probe_core.out 2): `_is_forming_bar(forming, prev) = False` for a bar with the scheduled close time and partial OHLC. The test builds its "forming" bar with `close_time_utc=last_closed_open + timedelta(hours=1, minutes=30)`, a 30-minute-long 1h bar, a shape the exchange does not send; and it only asserts something when a setup happens to fire.
- Expected: either the core can recognise an unclosed bar, or the docs say the rule is enforced upstream only.
- Actual: the core gate and its test rest on the same wrong picture of the data. The effective guards are upstream: `x=True AND close_time_utc <= now_utc` (src/paper/loop.py:223-232, 632) and the REST filters (src/paper/resync.py:298-300, restart.py:293). I did not find a bypass of those; the live process path belongs to another lane.
- Reproduction: `tmp/core_strategy_risk/probe_core.py` section 2.
- Impact: false assurance; a future caller that trusts the core gate (a script, a new runtime) would evaluate a forming bar.
- Why tests miss it: test and code were written from the same misunderstanding.
- Remediation: document the gate as a chaining check only and keep the clock-based rule at every entry point; or pass an explicit as-of close into `evaluate`.

### G-0105
- ID: G-0105 · Severity: LOW (now) / MEDIUM (mainnet) · Confidence: CONFIRMED · Classification: DESIGN
- Category: parameter provenance / gate by label · Component: rationale labels, paper-start gate
- File: params/trend-pullback/research-run-1-a01.toml · Lines: 65-140 (all 48 `research-run-1-*` sets; src/domain/rationale.py:187-201; src/paper/freeze.py:632-670)
- Rule: Phase 15 D-16/D-27 (a set with PLACEHOLDER keys is research-only and is refused for paper); AGENTS "Research before optimisation"; 16-DEC-O-02 item 2 · Known-prior: KNOWN:16-DEC-O-02 (the owner approved "EXPERIMENT means fixed and preregistered before any result, not shown to be good; no PLACEHOLDER label")
- Evidence: baseline-v6 `[rationale.minimum_rr] basis = "PLACEHOLDER"` with "no empirical basis yet"; research-run-1-a01 `[rationale.minimum_rr] basis = "EXPERIMENT" value = "2.0"` with "Phase 3 seed value ..., no empirical basis yet. Held fixed by the research-run-1 preregistration ...; a preregistered fixed setting, not evidence that the value is good." Same for `swing_lookback`, `min_stop_atr`, `cluster_cap`, `pivot_left_bars`. Probe (probe_core.out 3): PLACEHOLDER-key count baseline-v6 = 16 / 17 / 22 (A / B / C), research-run-1-a01 / b01 / c01 = 0. The gate reads only the label: `table.get("basis") == "PLACEHOLDER"` (rationale.py:199). `research-run-1-a01` ran in the paper soak (evidence 16-43).
- Expected: a gate that exists to keep values without a basis out of paper/live cannot be passed by renaming the label.
- Actual: the same unvalidated numbers pass. The text is honest; the machine-read field no longer distinguishes. A later gate (the go-live gate) keyed on PLACEHOLDER would also see zero.
- Reproduction: `tmp/core_strategy_risk/probe_core.py` section 3; compare the two files.
- Impact: none for money now (SHADOW paper). For mainnet: the provenance labels cannot serve as go-live evidence; EXPERIMENT now covers both "preregistered input" and, by its name, "supported by an experiment".
- Why tests miss it: tests check that a label exists and is well formed, not what it means.
- Remediation: Owner decisions 4: a separate label (for example PREREGISTERED) that paper may accept and live must refuse, or a go-live rule that refuses EXPERIMENT without a result reference.

### G-0106
- ID: G-0106 · Severity: LOW / LOW · Confidence: CONFIRMED · Classification: GAP
- Category: configuration validation · Component: parameter registry
- File: src/domain/registry.py · Lines: 347-434, 519-565
- Rule: registry docstring "loader is fail-closed"; AGENTS "Fail closed" · Known-prior: none found
- Evidence: `_check_value_range` ranges only the rate keys, the two cost guards, the TTL, pivot widths, geometry_version and min_stop_atr; there is no required-key list. Probe (probe_core.out 4), text-level edits of range-mr baseline-v6: LOADS with `cluster_cap = -1`, `max_aggregate_open_risk = 5`, `minimum_risk_utilization_after_rounding = 0`, `daily_loss_stop_threshold = 1`, `minimum_rr = -3`, `max_open_positions = 1000`, with the `min_stop_atr` line removed (the D-08 floor is then off: planner.py:621 uses `params.get`), and with `touch_tolerance_atr` removed (KeyError later inside `evaluate`, strategy.py:559).
- Expected: risk limits outside a sane range, or a family set without its required keys, refuse to load.
- Actual: they load; some then disable a gate silently, some raise at the first bar.
- Reproduction: `tmp/core_strategy_risk/probe_core.py` section 4.
- Impact: low: every set is hash-pinned and reviewed, so this needs a new committed file. It matters because parameter sets are written by agents in bulk (48 research sets) and the owner cannot review numbers by eye.
- Why tests miss it: tests cover the keys that have ranges.
- Remediation: per-family required keys; ranges for the five portfolio/daily keys ((0, 1]), `minimum_risk_utilization_after_rounding` in (0, 1], `minimum_rr` > 0, `max_open_positions` >= 1 with a small ceiling.

### G-0107
- ID: G-0107 · Severity: LOW / LOW · Confidence: CONFIRMED · Classification: GAP
- Category: machine-enforced invariants · Component: AST guards
- File: tests/test_domain_no_float.py · Lines: 16-101, 139 (tests/test_core_tracer.py:377-411)
- Rule: AGENTS "Invariants that are machine-enforced": Decimal-only on domain/registry/risk/backtest/core/analytics; no wall clock in pure modules; `src/core` stays pure · Known-prior: none found
- Evidence: the float guard lists src/core, src/domain and src/risk files one by one (globs exist only for `src/backtest`, `src/paper`, `src/research`, line 139). Probe (probe_guards.out) NOT_FLOAT_SCANNED: src/core/_decimal.py, src/risk/cost_rates.py, src/risk/cost_guards.py, src/risk/live_commission.py, src/domain/lot_filters.py, src/domain/transitions.py (and the three out-of-lane domain files). cost_rates.py has only a weaker local check (`float(` calls, not literals: tests/test_cost_per_unit.py:259-264); I found none for cost_guards.py and _decimal.py. By grep over tests/, no test applies `wall_clock_calls` to a src/core file or to sizing/quantization/gating/portfolio/cost_*. The import-purity test names five core files and omits pivots.py and _decimal.py.
- Expected: the guards cover every module of the packages they are said to protect, including files added later.
- Actual: today all these files are clean (my scan: 0 float shapes, 0 wall-clock calls, no third-party import), so nothing is broken; the next float or `datetime.now()` in one of them would not fail CI.
- Reproduction: `tmp/core_strategy_risk/probe_guards.py`.
- Impact: latent; the money cost producer (cost_rates.py) is among the unguarded files.
- Why tests miss it: a hand-kept list; the "registration trap" was fixed for three packages only.
- Remediation: glob `src/core/*.py`, `src/domain/*.py`, `src/risk/*.py` in the float guard and add one wall-clock + import test over the same globs.

### G-0108
- ID: G-0108 · Severity: INFO / LOW · Confidence: CONFIRMED · Classification: DESIGN
- Category: small-capital tradability · Component: quantization gates x exchange minimums
- File: src/risk/quantization.py · Lines: 94-136
- Rule: AGENTS Quantization; owner goal "small capital" · Known-prior: partly KNOWN:D046 item 6 (cost ceiling binds at about 0.79 %)
- Evidence: probe_sizing.out B, LONG, stop swept 0.30 %..6.00 % in 0.05 % steps, risk 0.5 %: BTCUSDT equity 500: 27 of 115 grid points tradable, widest tradable stop 2.35 % (10 COST_TO_RISK_EXCEEDED, 5 UTILIZATION_REJECT, 73 MIN_QTY_REJECT); BTCUSDT equity 1000: 72 of 115, widest 4.85 %, with UTILIZATION_REJECT bands between whole steps; ETH/SOL/XRP: 105 of 115 (only the cost ceiling below 0.80 %). Section A: BTC 3 % stop at equity 500 is MIN_QTY_REJECT; at 1000 it is 0.001 BTC with utilisation 0.628.
- Expected / Actual: works as designed (fail closed). The point is the consequence: with 500-600 USDT, BTC trades exist only for stops between about 0.8 % and 2.4-2.8 %, and which ones pass depends on where the stop falls relative to the 0.001 step. A backtest run at another equity has a different BTC trade set.
- Reproduction: `tmp/core_strategy_risk/probe_sizing.py` sections A and B.
- Impact: research figures for BTC are equity-dependent; live will show many MIN_QTY / UTILIZATION rejections on BTC. If the mainnet BTCUSDT minimum notional is 100 USDT (the fixture says 50; not verified, no exchange call was made), one step with BTC below 100000 fails NOTIONAL_REJECT as well.
- Why tests miss it: not a defect.
- Remediation: Owner decisions 3.

### G-0109
- ID: G-0109 · Severity: INFO / INFO · Confidence: CONFIRMED · Classification: IMPROVEMENT
- Category: hashed dead field · Component: planner invalidation rule
- File: src/core/planner.py · Lines: 689-700
- Rule: DATA_MODEL section 5 (invalidation rule JSON) · Known-prior: none found
- Evidence: `break_distance = _mul(sl_buffer_atr, atr)` is stored as `"break_distance_atr": str(break_distance)`: the key says ATR multiples, the value is a price distance. A grep for `break_distance` in src finds no reader, only writers (backtest/case.py:507 writes "0", paper/rehearsal.py:428 writes "10"). The field is inside `invalidation_rule_json`, which is part of the plan hash.
- Expected: a hashed field is read by something and its name matches its unit. Actual: neither.
- Reproduction: grep.
- Impact: none today; a future reader that trusts the name would be wrong by a factor of ATR, and the field cannot be renamed without changing plan hashes.
- Why tests miss it: golden fixtures pin the bytes, not the meaning.
- Remediation: document it as unused, or fix it together with the next planned hash change.

## Owner decisions

1. **Cluster cap after a same-day gain (G-0101).** Day starts at 600 USDT, one trade wins +6. The next XRP or SOL signal that day is sized at 3.03 / 3.01 USDT risk and refused because the cap is 3.00 (0.5 % of the morning's 600). BTC passes only because its coarse step leaves it at 2.28. Choose: (a) keep it (fewer trades after wins, in backtest too), (b) compare against one equity base, (c) raise the cluster cap above the single-trade risk. (b) and (c) change the trade set and need new sets and regenerated records.
2. **How much is really risked per trade (G-0102).** With "risk 0.5 %" and 1000 USDT, a stopped-out Family A trade loses about 3.05 USDT (0.30 %), Family B about 4.65, Family C about 4.47, because the position is sized as if the entry filled at the far edge of the zone, which a single limit at the middle cannot do. Choose: (a) keep it and show the real figures on the card and in reports, (b) size at the placed limit price so that a stop-out is about 0.5 %.
3. **BTC with 500-600 USDT (G-0108).** At 500 USDT only stops between about 0.8 % and 2.35 % can be traded on BTC (0.001 BTC is about 100 USDT). Choose: accept, drop BTC from the small-account universe, or revisit the 60 % utilisation floor. The mainnet BTCUSDT minimum notional must be re-read from exchangeInfo first (not verified here).
4. **Label EXPERIMENT on values with no basis (G-0105).** Confirm that a set whose values are "preregistered but not shown to be good" may run in SHADOW paper, and decide whether the go-live gate must refuse such values.
5. **Cluster membership (KNOWN:21-DEFERRED, F-908).** 8 of the 12 research symbols are outside the hard-coded cluster. Already an owner item; listed here because G-0101 touches the same gate.

## Open Questions

- (paper / data lanes) Does the paper or live runtime wait for the 4h bar at a shared close before evaluating the 1h bar, and is a missing newest 4h bar detected (G-0103)? `group_by_close` orders bars that are present; I did not trace what happens when the 4h bar is absent.
- (paper lane) `evaluate_closed_bar` docstring: "the paper tick passes its whole series, the runtime and the decision surface pass the engine windows" (src/paper/loop.py:372-374). EMA and the range-mr touch count depend on the window start, so a caller that passes a different window gets different decisions for the same bar. Is `run_paper_tick` still a real entry point?
- (data / research lanes) One missing bar anywhere in the 1000 x 1h or 300 x 4h window makes every feature GAP_IN_SOURCE (features.py:469-480), so no signal for that symbol for up to 41-50 days. How many such gaps exist in the research dataset and how are they recorded?
- (execution / live lanes) `evaluate_risk` hard-codes `positions_reconciled=True` (src/risk/gating.py:281) and src/live/risk_inputs.py:725 passes the constant True to the placement gate with the comment "The builder just explained every exchange exposure by a PLACED or OPEN row". The fail-closed branch of `check_portfolio` is therefore unreachable through the shared pipeline; is the builder's refusal path complete?
- (execution lane) Old F-303 (no symbol-level rule in the portfolio gate): `check_portfolio` still has none; the backtest blocks by `symbol in self.active` (engine.py:738). Where does live block a second plan on a symbol?
- (execution lane) The min-notional gate uses the unsnapped zone mid (quantization.py:105); the order goes out at the tick-snapped price (LONG lower). A notional within one tick of the minimum would pass the gate and be refused by the exchange. Negligible at the notionals of the probe (77 USDT and up against a 5-50 USDT minimum).
- `evaluate` lets ValueError (duplicate or regressing timestamps, mixed symbols in a stream) and KeyError (missing family key) escape, while `plan` maps the same stream errors to NO_TRADE (strategy.py:724-735 vs planner.py:519-531). Fail closed by exception; whether the callers survive it belongs to the runtime lanes.
- `TradeStatus` (enums.py:87-94) has no transition table; I did not check whether it is persisted anywhere.
- Not inspected: the callers of `realized_risk_for_fill`, the Phase 5/15 fixture derivations, 70 parameter files value by value, and whether `registry-gate.yml` runs the pin comparison in CI (CI lane).

## DONE
