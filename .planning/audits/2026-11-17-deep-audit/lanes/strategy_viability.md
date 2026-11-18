# Lane X11: strategy_viability

## Verdict for the owner
**Recommendation: do not continue the plan as it stands. Pause the execution engineering, keep live trading
disabled, and spend the next four months (until the project's own stop date, 2027-03-19) on one better-designed
research run. If nothing passes by then, stop the trading goal and keep the code as a research platform.**
- The research says no: 0 of 48 tested strategy variants can pass the project's own rules; average result per trade
  -0.07 R (trend-pullback), -0.09 R (breakout-retest), -0.10 R (range); the Demo/paper candidate a01 is -0.10 R.
- Before costs the strategies are about break-even; fees and slippage (6.5-15 % of the risk per trade) make them lose.
- More capital does not help: costs are a fixed share of each trade at any size. 20,000 USDT would lose about
  1,600 USDT a year at this rate instead of 40 USDT at 500.
- The remaining roadmap (Demo soak, go-live gate) cannot lead to a real trade: it needs a passing strategy and no step
  produces one; 3-6 months of paper trading cannot prove an edge either (too few trades).
- What would change this: a new run with enough data that passes; evidence that the portfolio caps hid a real edge;
  or a goal of learning/engineering rather than income (then continuing is a fine hobby, not an investment).

## Scope
Owner's question: should the project keep going? Per LANES.md X11: (1) edge evidence of research run 1,
(2) market rationale of the three families, (3) economics with the project's own cost model and quantization at
500 / 1000 / 5000 / 20000 USDT, (4) statistical power, (5) cost of continuing, (6) options and a recommendation.
Builds on lanes backtest_research_analytics (G-0901..G-0905), backtest_gapfill, decisions_trading_soundness
(G-2101, G-2102, G-2105, G-2107), core_strategy_risk, paper_gapfill (G-1052). Their numbers were re-derived where
this lane relies on them. Probes: `tmp/strategy_viability/` (`parse_points.py` -> `points48.json`,
`economics.py` -> `economics.out`, `power.py` -> `power.out`, `identical.out`). Python = the project venv,
PYTHONPATH = snapshot, no network, no database. This lane does not forecast profit; it judges whether continuing on
the present path is a reasonable use of the owner's time, from the evidence that exists.

## Coverage
| File | Level | Note |
|---|---|---|
| `.planning/phases/16-paper-runtime-composition/evidence/16-63-run-output.txt` | DEEP_READ (machine) | 48 `plateau point` lines parsed by my own parser (96 lines, duplicates identical); feasibility lines read |
| `docs/research/preregistration/research-run-1-manifest.json` | DEEP_READ | splits (Validation 2025-07-22..2026-05-10 = 292 d), 12 symbols, equity 600, risk 0.005 |
| `docs/research/preregistration/research-run-1-hypothesis.md` | NORMAL_READ | sections 0-6: hypotheses, fixed values, grids |
| `docs/research/preregistration/research-run-1-constraints-baseline.json` | DEEP_READ | step / min qty / min notional of the 12 symbols |
| `params/trend-pullback/research-run-1-a01.toml` | DEEP_READ | costs, guards, rationale labels |
| `params/breakout-retest/research-run-1-b01.toml`, `params/range-mr/research-run-1-c01.toml` | NORMAL_READ | rationale labels only |
| other `params/**` (baselines, 45 run-1 sets) | METADATA_ONLY | listing |
| `docs/research/families/trend-pullback.md` | NORMAL_READ | sections 1-3 |
| `docs/research/families/breakout-retest.md`, `range-mr.md` | METADATA_ONLY | hypotheses taken from the hypothesis file sections 5-6, which quote them |
| `docs/research/TRADING_STRATEGY_RESEARCH.md` | NORMAL_READ | section 5 (families), section 25 (stop conditions), references, Appendix A |
| `docs/strategy/TRADING_STRATEGY_SPEC.md` | NOT_READ | slot template, no market rationale |
| `docs/research/RESEARCH_PROTOCOL.md` | NORMAL_READ | section 4 G1-G5, power note, kill gate, amendment log |
| `docs/DECISIONS.md` | NORMAL_READ | D013, D030, D043 rows (others via the earlier lanes) |
| `src/risk/cost_rates.py`, `cost_guards.py`, `quantization.py`, `sizing.py` | DEEP_READ | called by the probes |
| `src/core/planner.py` | NORMAL_READ | lines 630-700 (TP2 = 2 x TP1 leg, RR gate on TP1) |
| `src/backtest/semantics.py`, `src/backtest/exits.py` (header) | NORMAL_READ | TP1 closes half, stop never moves |
| `.planning/ROADMAP.md` | NORMAL_READ | phase list, Phases 25-26 |
| `.planning/STATE.md` (head), `.planning/REQUIREMENTS.md` (PAPER-03) | NORMAL_READ | progress, pace |
| `.planning/phases/16-*/decisions/16-DEC-candidate.md` | NORMAL_READ | a01 designation basis |
| `tests/conftest.py` | METADATA_ONLY | live-5 list |

## Edge evidence (task 1), verified independently
Source: 48 `plateau point` lines parsed by `parse_points.py` (48 unique points, duplicates byte-equal). Mean R is G2's
statistic (pooled Validation closed trades, net of all modelled costs), as lane M09 traced in code.

| Family | negative means | trade-weighted mean | best point | worst | best point's 95 % CI (iid) | can more data change the verdict? |
|---|---|---|---|---|---|---|
| A trend-pullback | 15/16 | -0.070 R | a05 +0.0027 R (n 354) | a11 -0.147 R | -0.105 .. +0.110 | for the family as registered, no: the paper candidate a01 is -0.102 R with a CI upper bound of -0.015. a05 alone cannot be excluded as a small edge, but it was not pre-selected; choosing it now is selection on the result |
| B breakout-retest | 14/16 | -0.094 R | b16 +0.014 R (fails G1); b12 +0.0007 R (n 159) | b03 -0.232 R | b12: -0.274 .. +0.275 | the data say almost nothing either way: sigma 1.9 R and 26 trades a month give a CI half-width of about 0.27 R |
| C range-mr | 16/16 | -0.102 R | c09 -0.086 R | c07 -0.136 R | c09: -0.262 .. +0.090 | no: every point is negative; the 16 points behave like about 6 distinct outcomes (G-2305) |

Distance from break-even as a win rate (two-point fit to n, wins, mean, std; `economics.out` section B): average loss
about -0.69 R (A), -1.08 R (B), -0.97 R (C); average win about +1.6 to +2.5 R (A), +2.4 to +4.3 R (B), +2.6 R (C).
The families need 2 to 4 percentage points more winning trades than they got (a01: 22.3 % winners, 26.2 % needed).
Distance from the protocol gates: G2 needs mean > 0 and a bootstrap lower bound > 0; G3 needs a raw p-value below
0.00104 (z about 3.08). The best point is 0.05 standard errors above zero. No point is anywhere near G3.

## Strategy rationale (task 2)
| Family | Behaviour relied on | Public evidence (repo citations first, then opinion) | Reasons it may fail on crypto perps at 4H/1H (opinion) | Parameters |
|---|---|---|---|---|
| A trend-pullback | trend persistence on 4H; pullbacks to a prior 1H pivot zone hold | Repo cites Moskowitz-Ooi-Pedersen 2012 and Hurst-Ooi-Pedersen (`docs/research/TRADING_STRATEGY_RESEARCH.md:1231-1235`): time-series momentum on monthly returns across diversified futures. The same file, Appendix A: this "does not automatically transfer to crypto perpetual futures". Opinion: published crypto momentum results are mostly at daily-to-weekly return horizons, not 1H pivot-zone entries | a 4H trend label is noisy; a pullback "zone" is touched by many bars; stops of 0.8-2 % sit inside the normal 1H noise of alts | seed values of plan 03-01, "no empirical basis yet" (a01 rationale of `minimum_rr`, `swing_lookback`); grid alternatives are "the drafter's design choice" (hypothesis file section 4). Picked, not derived |
| B breakout-retest | a retest after a breakout filters false breakouts | Repo cites TradingView community scripts (`:217`, `:267`, `:303`) and states that they are "an example of quantification, not evidence that the method is profitable" (`:217`, translated). No academic source | public and crowded rules; the retest window of 5-10 1H bars is short; fat-tailed alts trade through retest levels | seeds and their doubles |
| C range-mr | ranges persist when the 4H regime is neither up nor down | none cited; `:399-405` gives a design reason only (signals in sideways markets) and names the risk "range strategy is easily broken by a trend" | long trend legs in crypto; a stop outside the range turns every break into a full loss; target at mid-range caps the win | seeds; three of four grid axes nearly inert (G-2305) |

Summary: all three are standard discretionary chart-trading ideas turned into exact rules. That is a legitimate
starting point and the project labels it honestly ("a preregistered fixed setting, not evidence that the value is
good"). None has a cited source for an edge at this horizon on this instrument, and run 1 looks like what one expects
when there is none: losses about equal to costs (next section).

## Economics (task 3): the project's cost model and quantization (`economics.out`)
Rates of a01 (fee 5 bp each side, entry slippage 1 bp, stop slippage 3 bp, take-profit slippage 1 bp) through
`src/risk/cost_rates.py:per_unit_round_trip_cost`, `src/risk/cost_guards.py:check_cost_guards`,
`src/risk/quantization.py:quantize`.

| Stop distance | Round-trip cost, share of 1R | Guard | with a maker entry (2 bp, no slip) | funding per 8 h at 0.01 % | break-even win rate, single 2R target | single 3R target |
|---|---|---|---|---|---|---|
| 0.30 % | 31.8 % | COST_TO_RISK_EXCEEDED | 25.0 % | 0.023 R | 47.8 % | 36.1 % |
| 0.79 % | 15.0 % | OK (the binding limit) | 11.2 % | 0.011 R | 38.9 % | 29.2 % |
| 1.00 % | 12.2 % | OK | 9.0 % | 0.009 R | 37.7 % | 28.4 % |
| 2.00 % | 6.5 % | OK | 4.7 % | 0.005 R | 35.5 % | 26.7 % |
| 3.00 % | 4.4 % | OK | 3.2 % | 0.003 R | 34.8 % | 26.1 % |
| 5.00 % | 2.6 % | OK | 1.9 % | 0.002 R | 34.2 % | 25.7 % |

(without costs: 33.3 % at 2R, 25.0 % at 3R)

- Costs at typical stops (0.8-2 %) are 6.5-15 % of 1R per trade. Observed means are -0.07 to -0.10 R. Before costs,
  the families are therefore roughly at zero (about -0.05 to +0.05 R depending on the unmeasured stop-distance mix).
  Costs turn "no edge" into "a loss"; they do not hide a large edge.
- A maker entry would save 0.02-0.04 R per trade at 1-2 % stops: it does not close a gap of 0.07-0.10 R.
- Capital (quantize() with the committed constraints; assumed prices BTC 100,000, ETH 3,500, BNB 650, SOL 180,
  XRP 2.5; utilisation of the risk budget at stops 1 / 2 / 3 %):

| Equity (USDT) | 1R (USDT) | BTC | ETH | BNB | SOL | XRP |
|---|---|---|---|---|---|---|
| 500 | 2.50 | 91 / 86 / MIN_QTY_REJECT | 99 / 99 / 97 | 98 / 95 / 98 | 99 / 99 / 99 | 100 |
| 1,000 | 5.00 | 91 / 86 / 63 | 100 / 99 / 99 | 99 / 97 / 98 | 100 / 99 / 99 | 100 |
| 5,000 | 25.00 | 96 / 94 / 88 | 100 | 100 | 100 | 100 |
| 20,000 | 100.00 | 99 / 98 / 97 | 100 | 100 | 100 | 100 |

  More capital makes BTC tradable at wider stops and lifts BTC utilisation from 63-91 % to 97-99 %. Every cost in the
  model is a fraction of notional, so cost per trade in R is the same at every capital. Opinion (not checked on the fee page
  in this audit): Binance's first discounted futures tier needs a 30-day volume of the order of 15 million USD; 20,000
  USDT at about 200 trades a year and notionals of 2,000-10,000 USDT trades well under 1 million USD a month.
  **More capital scales the result; it does not change its sign.** At -0.08 R per trade and about 200 trades a year on
  the live-5 (family A rate scaled by 5/12), 500 USDT would lose about 40 USDT a year and 20,000 USDT about 1,600 USDT.

## Statistical power (task 4) (`power.out`)
n = ((z_alpha + z_power) x sigma / delta)^2, iid normal approximation; a block bootstrap with dependent trades needs
more, so these are lower bounds. sigma and trade rates are run-1 values (Validation 9.6 months, 12 symbols); the
live-5 rate is the 12-symbol rate x 5/12 (assumption).

| Family (sigma, trades/month on 12 symbols, median point) | edge | n at G3 (Holm 0.05/48), 80 % power | months of 12-symbol data | n for one pre-registered test (one-sided 0.05, 80 %) | months on the live-5 |
|---|---|---|---|---|---|
| A (1.13 R, 42) | +0.05 R | 7,855 | 188 | 3,161 | 181 |
| A | +0.10 R | 1,964 | 47 | 790 | 45 |
| A | +0.20 R | 491 | 12 | 198 | 11 |
| B (1.87 R, 26) | +0.10 R | 5,364 | 208 | 2,159 | 201 |
| B | +0.20 R | 1,341 | 52 | 540 | 50 |
| C (1.53 R, 33) | +0.10 R | 3,594 | 111 | 1,446 | 107 |
| C | +0.20 R | 899 | 28 | 362 | 27 |

- What run 1 could detect (80 % power at the observed n, G2 alone / G3): about +0.13 / +0.18 R for the best-populated
  A points, +0.25 / +0.35 R for C, +0.4 / +0.57 R for B. An edge of +0.05 to +0.10 R, which (opinion) is the size a real
  retail edge after costs would plausibly have, was never detectable with 9.6 months of Validation data on 12 symbols.
- The kill gate can fire on 2027-03-19 (D013/D030), four months from now. No wait for more data on the same families
  produces the 1,000-8,000 trades a small edge needs before that date.
- The paper observation (PAPER-03, 3-6 months) and the canary run on the live-5 at about 17 trades a month (family A):
  50-105 trades, standard error 0.11-0.16 R. They cannot tell +0.1 R from -0.1 R. They test the pipeline, not the edge
  (G-2302).

## Cost of continuing (task 5)
- Pace so far (`.planning/STATE.md` head): 360 plans with a SUMMARY between the protocol freeze (2026-09-19) and
  2026-11-07, about 7 weeks. Engineering by agents is fast; the owner's sessions (host, Demo, decisions) and the
  calendar items are the bottleneck.
- Left before any real-money trade (`.planning/ROADMAP.md`): Phase 25 (18 of 33 plans done; the rest includes an
  owner-run Demo soak of at least 21 days that restarts on any defect); a phase not yet named that builds a
  strategy-driven signal source (G-1052: today the live process can only carry synthetic smoke plans); Phase 26 (0 plans:
  G1-G5 gate code, kill-gate WR fixes, real backups and a restore drill, CI, a mainnet read-only check, the canary, and
  `enable()` requiring a recorded passing candidate plus the paper exit gate); Phase 27 (USDC). The paper exit gate needs
  3-6 months of observation of the candidate that will trade, so it can start only after a candidate passes.
- Rough calendar (my estimate, not from the repo): rest of Phase 25 4-8 weeks with the soak; signal source 2-4 weeks;
  Phase 26 6-12 weeks plus the 3-6 month paper window. Earliest real-money trade if a family passed today: about
  mid-2027. With no passing family: never, by the plan (Phase 26 criterion 1: "`enable()` requires a recorded passing
  candidate ... WITHIN_BUDGET is refused"). Today's code still accepts WITHIN_BUDGET
  (`src/execution/enablement.py:237-270` refuses only an unevaluated state and INSUFFICIENT_EDGE; KNOWN G-0903); what
  blocks real orders today is `LIVE_ORDERS_DISABLED`.
- Against that, the evidence so far: 0 of 48 candidates can pass; the paper/Demo candidate a01 is negative.

## Options for the owner (task 6)
| Option | What it costs | What it would prove | Decision criterion |
|---|---|---|---|
| (a) Continue as planned (Phases 25, 26, 27) | 4-8 weeks of Phase 25 incl. a 21-day soak, an unnamed signal-source phase, 6-12 weeks of Phase 26; owner sessions throughout | that the execution pipeline works on Demo and on a 50-100 USD canary. Nothing about the edge: no step in it produces a passing candidate (G-2300), and the paper/canary stages cannot measure one (G-2302) | none on the edge until `enable()`, which will refuse; the kill gate can fire on 2027-03-19 meanwhile |
| (b) Pause engineering; record run 1; run research run 2 under a fresh pre-registered protocol | 1-2 weeks to record run 1 and write run 2's rules (alpha spending across runs, G-2102; trade lists kept, G-0902; cap-free per-signal R reported, G-2107; G4 defined, G-0905); data backfill for more history (opinion: Binance public archives reach back to 2019-2020 for the majors) or wait for forward data after 2026-10-03; about 25 h of compute per run of this size | whether any candidate with a written hypothesis clears a test that has the power to see +0.1 to +0.2 R (G-2301). With the 24-month dataset it cannot | before running: the pre-registered grid, the alpha for run 2 and the data window are fixed. After: pass G1-G3 (G5 kept for the one survivor) -> resume (a) with the signal source first; fail -> (d) or (c) |
| (c) Change family, timeframe or market | a new family sheet, strategy code in `src/core` (the simulator, risk, cost and execution stack are reusable as they are), a new registration; weeks, mostly agent work plus owner review | the same as (b) for a hypothesis with external support. Opinion: lower-turnover ideas (daily/weekly time-series momentum on a basket, the horizon where the cited literature lives) cut cost to 1-3 % of R per trade but produce fewer trades, so power stays the binding problem; market-neutral ideas (funding carry) need a different execution model | same as (b); and the D013 rule that a new family "needs a new evidence-backed question approved" |
| (d) Stop | zero further cost; keep the repository as a research/journal platform (what D013 and `TRADING_STRATEGY_RESEARCH.md` section 25 already prescribe when no family passes) | nothing new; the option value of the built execution stack is kept for later | the owner's own goal: if the goal is income, the evidence so far does not support spending more on execution; if the goal is learning, (b) or (c) is cheaper than (a) |

**Recommendation: (b), time-boxed to the kill-gate date 2027-03-19, with (c) allowed inside it.** Freeze execution
engineering after the plans of Phase 25 that are already in progress (do not start the 21-day soak, the signal-source
phase or Phase 26), keep `LIVE_ORDERS_DISABLED`, record the run-1 result (O-1 of lane M09), and spend the time on one
pre-registered research run 2 that has the power to see the edge it is looking for: more history or a longer forward
window, alpha spent across runs, and at most a few hypotheses, at least one with external support at its horizon.
If nothing passes by 2027-03-19, take (d) as the project's own rule says. If a candidate passes, resume (a): the built
stack is not wasted, it is waiting.

Reasons, in numbers: 0 of 48 pass; family means -0.07 / -0.09 / -0.10 R; before costs about zero; costs 6.5-15 % of
1R per trade at the stops the guard allows, independent of capital; the remaining engineering cannot lead to a real
trade without a passing candidate, and nothing on the roadmap produces one; the forward stages (3-6 months of paper,
canary) give a standard error of 0.11-0.16 R and cannot confirm an edge.

What would change this recommendation: (1) the owner's goal is the engineering itself (a learning project): then (a)
is a reasonable hobby, as long as no one reads its Demo/paper results as proof of profit; (2) the trade lists of run 1
(re-simulated) show a clearly positive cap-free per-signal R that the PLACEHOLDER portfolio caps hid (G-2107), which
would be a reason to re-test that family with power; (3) a run 2 candidate passes G1-G3 with a pre-registered alpha;
(4) a documented, external source for one of the three setups at this horizon on crypto perpetuals, which would make
a powered re-test of that one family worth more than (c).

## Verified Safe Areas
- **Run-1 figures re-derived independently.** My parser over the committed run output (`parse_points.py`) gives 48
  unique points identical to lane M09's table (a01 n 613, mean -0.1019, sd 1.103, 137 wins; a05 +0.0027; b12 +0.0007;
  b16 +0.0137 and fold 2 = 23 trades). The duplicate block of 48 lines in the file is byte-identical.
- **The negative sign is not an artefact of an overcharged cost model.** Costs are 6.5-15 % of R at the allowed stops;
  replacing the taker entry by a maker entry saves 0.02-0.04 R; the only known cost bias (take-profit slippage 1 bp,
  G-0904) favours the candidates. No plausible cost correction lifts -0.07..-0.10 R above zero.
- **The research sizing matches what the live sizing would do at 1,000 USDT and above**, except BTC at stops of 3 %
  and wider at 500 USDT (`quantize()` probe, table above). Research used equity 600 (manifest), so a few BTC trades with
  wide stops were refused in research as they would be live at that size.
- **Cost guard arithmetic.** `max_cost_to_risk` 0.15 implies a minimum stop of 0.79 % with these rates (probe: 15.0 %
  at 0.79 %), as the hypothesis file section 2 states. Verified with `check_cost_guards`.
- **Pre-registration held.** The 48 sets were registered before any result (hypothesis file header; rationale labels
  "not evidence that the value is good"); the paper candidate a01 was designated by grid position, not by result
  (`16-DEC-candidate.md`; it is not even the best point). This is why the run-1 result can be believed.

## Decision review
| Decision / rule | Verdict | Yardstick | Reason |
|---|---|---|---|
| Pre-registration, no tuning from results (R1-R6, D059 item 5) | SOUND | research practice | it is what makes the negative result trustworthy |
| D013/D030 kill gate (3 families + 6 months, then stop adding complexity) | SOUND as a rule | owner goals | a real stop rule exists; its effect depends on a recorded status that nobody writes (KNOWN G-0903) |
| D043/D069 G2 bound and one Holm over 48 | SOUND for false positives | arithmetic | strict and correct; together with the data depth it leaves almost no power (G-2301) |
| D049 data depth 24 months (1m), Validation 9.6 months | DOUBTFUL | power arithmetic | chosen for data-handling reasons; it caps detectable edges at about 0.13-0.57 R (G-2301) |
| Choice of the three families (`TRADING_STRATEGY_RESEARCH.md` section 5) | DOUBTFUL | public evidence (opinion) | chart-practice ideas with no cited edge at 1H/4H on crypto perps; results consistent with zero pre-cost edge (G-2303) |
| Grid values (seeds and "drafter's design choice") | SOUND as declared | logic | honestly labelled as not derived; range-mr axes mostly inert (G-2305) |
| D046 `max_cost_to_risk` 0.15, `min_stop_distance_rate` 0.003 | SOUND | arithmetic | keeps costs at or below 15 % of R; tighter stops would need break-even win rates of 42-48 % |
| D036 taker fee on the entry | SOUND (conservative) | arithmetic | overstates cost by 0.02-0.04 R at most; does not change the verdict |
| D059 item 5 / Backlog 999.2: candidates come from "the Phase 16 research runner work" | DOUBTFUL | process logic | Phase 16 is finished and produced no passing candidate; no numbered phase produces the next one (G-2300) |
| PAPER-03 "forward evidence" over 3-6 months; D040 canary | DOUBTFUL as edge evidence, SOUND as pipeline checks | arithmetic | 50-105 trades give SE 0.11-0.16 R (G-2302) |
| 16-DEC-candidate: a01 as paper/Demo candidate | SOUND for a pipeline test | logic | chosen without looking at results; must not be read as a candidate with an edge (its mean is -0.10 R) |
| D040 capital 500-1,000 USDT, "capital can be raised later" | SOUND for safety, irrelevant to the edge | arithmetic | costs in R do not depend on capital (G-2304; KNOWN G-2105 for 500-1,000) |

## Findings

### G-2300 — No numbered phase produces the passing candidate that every remaining go-live step needs; after run 1 failed, the roadmap continues only on execution
- Severity: now MEDIUM / mainnet MEDIUM
- Confidence: CONFIRMED (roadmap text; run-1 figures re-derived)
- Classification: DESIGN
- Category: viability, roadmap sequencing
- Component: `.planning/ROADMAP.md` Phases 25-27, Backlog 999.2; D059 item 5
- File: `.planning/ROADMAP.md`
- Lines: 62-64 (phase list), 1384 (Phase 25 goal "Profitability is explicitly out of scope"), 1498, 1507 (Phase 26, criterion 1), 1518 ([D059-5]), 1608-1612 (Backlog 999.2)
- Rule: D013, D059 item 5, Phase 26 criterion 1
- Known-prior: the unrecorded outcome is G-0901 / G-2101; the missing signal source is G-1052; the kill gate that never fires is G-0903. New here: no step of the plan produces a candidate at all.
- Evidence: Phase 26: "`enable()` requires a recorded passing candidate ... WITHIN_BUDGET is refused". [D059-5]: "`enable()` requires a passing candidate produced by the Phase 16 research runner work (Backlog 999.2 is not a numbered phase)". Phase 16 is complete; its run produced 0 of 48 candidates that can pass (`16-63-run-output.txt`, `points48.json`). Phases 25-27 contain no research run; Phase 25's goal says "Profitability is explicitly out of scope; correctness is the only goal".
- Expected: after a failed research run, the plan names the step that produces the next candidate (or records the stop), before more effort goes into the path that only a candidate can use.
- Actual: the remaining plan (rest of Phase 25 including a 21-day soak, an unnamed signal-source phase, Phase 26 with 0 plans, Phase 27) ends in a gate that cannot open, while the project's own stop rule can fire on 2027-03-19.
- Reproduction: read the cited roadmap lines; `python -B parse_points.py <run output>`.
- Impact: months of owner time on a path that, by its own rules, cannot reach a real trade. No money at risk (placement disabled).
- Why tests miss it: planning, not code.
- Remediation: owner decision OD-1 (below): choose option (a)-(d) explicitly and write it into ROADMAP; if (b) or (c), add a numbered research phase before the Phase 25 soak.

### G-2301 — The protocol plus the 24-month dataset can only certify large edges (about 0.13-0.57 R); a realistic edge of 0.05-0.10 R needs 1,000-8,000 trades
- Severity: now MEDIUM / mainnet MEDIUM
- Confidence: CONFIRMED (arithmetic probe `power.py`, run-1 sigma and trade rates)
- Classification: DESIGN
- Category: research methodology, statistical power
- Component: RESEARCH_PROTOCOL section 4 (G2, G3, power note); D049 data depth; manifest splits
- File: `docs/research/RESEARCH_PROTOCOL.md`
- Lines: 282-283 (G2, G3), 295 (power note); `docs/research/preregistration/research-run-1-manifest.json` (Validation 2025-07-22..2026-05-10)
- Rule: D032, D043, D049, D069
- Known-prior: the power note itself says the floor "detects only a large edge" (KNOWN, stated in the protocol); not recorded: what that means for the chance of ever passing, and that no decision addressed it
- Evidence: `power.out`. Family A (sigma 1.13 R, 42 trades/month on 12 symbols): +0.10 R needs 1,964 trades at G3 (47 months of data) or 790 for a single pre-registered test (19 months); +0.05 R needs 7,855 / 3,161. B and C need 2-5 times more. Run 1 at its n could detect, with 80 % power, about +0.13 R (G2) / +0.18 R (G3) for the best-populated A points, +0.25 / +0.35 R for C, +0.4 / +0.57 R for B. The Validation block is 9.6 months.
- Expected: a research design whose power matches the edge size that is plausible (opinion: 0.05-0.2 R after costs for a retail rule-based strategy), or an explicit decision that only large edges are of interest and what follows from a fail.
- Actual: a fail cannot separate "no edge" from "a small edge"; another run of the same size and kind is likely to fail whatever the truth, and a pass at this size would need a very large edge.
- Reproduction: `python -B power.py` in `tmp/strategy_viability` (reads `points48.json`).
- Impact: wrong decision input: "fail" is read as "no edge" or, worse, "try another grid". It also bounds what run 2 can achieve unless its data are deeper.
- Why tests miss it: methodology.
- Remediation: owner decision OD-2: for any run 2, size the data to the edge sought (more history for the majors, or a forward window), cut the number of hypotheses (each extra one raises the bar via Holm), and pre-register the minimum edge of interest.

### G-2302 — The paper observation (PAPER-03) and the canary cannot measure an edge at the expected trade rate; nothing says so
- Severity: now LOW / mainnet MEDIUM (a lucky forward run could be read as confirmation)
- Confidence: CONFIRMED (arithmetic)
- Classification: DESIGN
- Category: evidence interpretation
- Component: PAPER-03, Phase 26 criteria 1 and 5, D040 canary
- File: `.planning/REQUIREMENTS.md`
- Lines: 54 ("Forward evidence accumulates over wall-clock observation (3-6 months envelope)"); `.planning/ROADMAP.md:1511` (canary "pre-registered number of trades")
- Rule: D040, D061 item J
- Known-prior: none found
- Evidence: family A on the live-5 trades about 17 times a month (42 x 5/12); 3-6 months is 50-105 trades; with sigma 1.13 R the standard error of the mean is 0.16-0.11 R. A true +0.1 R edge and a true -0.1 R edge overlap almost entirely. The canary (50-100 USD, minimum size) produces fewer trades still.
- Expected: the forward stages are defined as pipeline and consistency checks (for example "the forward mean lies inside the backtest interval"), and the documents say they are not edge evidence.
- Actual: "forward evidence" is undefined in size; a reader (the owner) can take a positive paper quarter as proof.
- Reproduction: `power.out`; SE = 1.13 / sqrt(50..105).
- Impact: a false "go" with real money after a lucky quarter; or a false "stop" after an unlucky one.
- Why tests miss it: no test covers the meaning of evidence.
- Remediation: state the purpose and the statistical limit of PAPER-03 and the canary in RUNBOOK / Phase 26 before they start.

### G-2303 — The three family hypotheses have no cited evidence of an edge at 1H/4H on crypto perpetuals, and run 1 is consistent with zero pre-cost edge
- Severity: now LOW / mainnet LOW
- Confidence: PROBABLE (repo citations checked; the market statements are opinion; the stop-distance mix of run 1 is not recorded, so "pre-cost about zero" is a range)
- Classification: DESIGN
- Category: strategy rationale
- Component: `docs/research/TRADING_STRATEGY_RESEARCH.md` section 5, family sheets, run-1 grids
- File: `docs/research/TRADING_STRATEGY_RESEARCH.md`
- Lines: 316-405 (families), 217 (TradingView scripts "not evidence that the method is profitable"), 1231-1235 (TSMOM / trend-following references), 1239-1243 (Appendix A)
- Rule: D012 (evidence before promotion), D013 ("new evidence-backed question")
- Known-prior: none as a finding; F-909 noted seed values without basis
- Evidence: the only academic references are about monthly time-series momentum across asset classes; the document itself says it "does not automatically transfer". Breakout/retest and range sources are community scripts cited as quantification examples. Parameters: "Phase 3 seed value ... no empirical basis yet" (a01 `minimum_rr`, `swing_lookback`). Run 1: means -0.07 / -0.09 / -0.10 R with costs 6.5-15 % of R at the allowed stops (`economics.out`).
- Expected: a family enters a costly research run with a stated reason to expect an edge at its horizon (a source, or a mechanism such as a risk premium or a structural flow).
- Actual: the families are reasonable first tries but carry no prior; the outcome is what a zero-edge rule with these costs produces.
- Reproduction: read the cited lines; `economics.out`.
- Impact: decision input for option (c): a new family should come with a source; re-running the same three with new grids is unlikely to change the picture (opinion).
- Why tests miss it: not testable.
- Remediation: require a written rationale with a source for any family in run 2 (owner decision OD-3).

### G-2304 — More capital does not change the per-trade economics; it only removes BTC quantization limits and scales the result
- Severity: now INFO / mainnet INFO
- Confidence: CONFIRMED (probe with `quantize()` and `per_unit_round_trip_cost`)
- Classification: IMPROVEMENT
- Category: viability, expectation management
- Component: sizing and cost model at 500 / 1,000 / 5,000 / 20,000 USDT
- File: `src/risk/quantization.py`, `src/risk/cost_rates.py`
- Lines: `quantization.py:32-155`, `cost_rates.py:122-151`
- Rule: owner premise "capital can be increased later"; D040
- Known-prior: KNOWN G-2105 for 500-1,000 USDT (BTC marginal, canary cannot trade BTC); new here: 5,000 and 20,000 and the statement that the sign does not change
- Evidence: `economics.out` section C: utilisation of the live-5 at stops 1/2/3 %; BTC MIN_QTY_REJECT at 3 % with 500 USDT, 63 % at 1,000, 88 % at 5,000, 97 % at 20,000; all others 93-100 % at every size. Cost share of R depends only on stop distance (section A).
- Expected / Actual: not a defect. The owner's premise is right for safety (small capital limits loss) and wrong as a lever for profitability.
- Reproduction: `python -B economics.py <snapshot> points48.json`.
- Impact: at -0.08 R per trade, about 200 trades a year: -40 USDT at 500, -1,600 USDT at 20,000.
- Why tests miss it: not testable.
- Remediation: none in code; state it to the owner (this lane's verdict).

### G-2305 — Range-mr grid: half of the 16 registered points give identical or near-identical results; the family tested about 6 distinct hypotheses, not 16
- Severity: now LOW / mainnet LOW
- Confidence: CONFIRMED for the figures (`identical.out`); the cause is UNVERIFIED (not traced in the engine)
- Classification: AMBIGUITY
- Category: research design
- Component: range-mr grid (`research-run-1-grid-range-mr.json`), detector parameters `regime_filter_lookback`, `range_break_buffer_atr`
- File: `.planning/phases/16-paper-runtime-composition/evidence/16-63-run-output.txt`
- Lines: feasibility lines 669-684; plateau points c01-c16
- Rule: RESEARCH_PROTOCOL variant budget N = 25; D069 (Holm over 48)
- Known-prior: none found
- Evidence: c02 = c10 (n 320, 77 wins, mean -0.0972093 both), c04 = c12, c06 = c14, c08 = c16 (identical n, wins and mean); c02 vs c04 differ by 0.00005 R. With `signal_expiry_hours` 8, `regime_filter_lookback` 50 vs 100 changes nothing, and `range_break_buffer_atr` 0.2 vs 0.5 almost nothing. With expiry 4 the points differ by a few trades.
- Expected: each registered axis changes which trades occur, or the registration states that an axis may be inert.
- Actual: three of four axes barely move the outcome; the family's 16 hypotheses count 16 times in Holm but carry little independent information.
- Reproduction: `python -B identical.py` -> `identical.out` (reads `points48.json`).
- Impact: none on the verdict (all 16 are negative). For run 2: choose axes that matter, which also lowers the Holm bar.
- Why tests miss it: no test compares outcomes across grid points.
- Remediation: for run 2, check axis sensitivity on Development only before registration (allowed by the protocol: Development is the exploration space).

## Owner decisions
- OD-1 (G-2300): choose (a) continue, (b) pause engineering and run a powered research run 2, (c) change family/timeframe/market, or (d) stop. Example in numbers: (a) costs about 3-6 months of owner sessions and ends at a gate that refuses without a candidate; (b) costs about 1-2 weeks of rules plus a data backfill and about 25 h of compute, and answers whether a +0.1-0.2 R edge exists; (d) costs nothing more.
- OD-2 (G-2301): for run 2, the minimum edge of interest and the data needed for it. Example: to see +0.1 R in family A at one pre-registered test with 80 % power needs about 790 trades, about 19 months of 12-symbol data; at +0.2 R about 200 trades.
- OD-3 (G-2303): require a written source or mechanism for any family entered in run 2, yes or no.
- OD-4 (G-2302): state, before Phase 25's soak and PAPER-03 start, that their results are pipeline evidence only (example: 100 paper trades give a standard error of 0.11 R).
- Carried from other lanes and needed for any option: record run 1 (M09 O-1), keep trade lists (M09 O-2), alpha across runs (X09 O-3).

## Open Questions
- Lane M09 / backtest: why do the range-mr axes `regime_filter_lookback` and `range_break_buffer_atr` have no effect at `signal_expiry_hours` 8 (G-2305)? Inert by data, or not reaching the detector?
- The stop-distance distribution of run 1 is not in any committed file; with it, the pre-cost mean per family could be given as a number instead of a range (needs a re-simulation, M09 O-2).
- The Development-window means of the 48 points are not printed; they would show whether the sign is stable across the 2024-10 .. 2025-07 period (exploratory only, never a gate).

## DONE
