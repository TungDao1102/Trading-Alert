# Lane M09: backtest_research_analytics

## Scope
`src/backtest/*`, `src/research/*`, `src/analytics/*`, `docs/research/RESEARCH_PROTOCOL.md`, `docs/backtest/*`,
plus the extra task: an independent gate evaluation of research run 1 at simulator semantics 2.3.0.
Findings G-0900..0999. Snapshot `55885b9`. (Sections below are appended as work proceeds.)

## Progress log (partial-run marker; superseded by the sections below when `## DONE` is present)
- [done] Extra task: independent gate evaluation of research run 1 (2.3.0). Probes: `tmp/backtest_research_analytics/parse_run.py`
  (output `parse_v230.out`, `points_v230.json`), `boot_sens.py` (output `boot_sens.out`). Result in G-0901 / G-0902 below.

## Extra task: what G1-G5 say for the 48 candidates of run 1 at semantics 2.3.0 (independent evaluation)

**What the committed records can and cannot support (decisive for the method).**
- The 240 files in `docs/research/experiments/research-run-1-v2-3-0/` carry identity fields and `no_trade_counts` only;
  the result field is `"result_summary_json":"{\"trades_digest\":\"...\"}"` (one sha256 per window). No trade, no R value,
  no count of closed trades, no mean is in any record (`src/research/run.py:377-383`).
- The per-trade lists existed only in the checkpoint directory `C:\rerun-v230\ck\<family>` named by
  `evidence/16-63-run-output.txt:5`. That directory is not in the repository and no longer exists on this machine
  (`C:\rerun-v230\` holds only start/end stamp files). So the **real block-bootstrap interval cannot be computed by
  anyone from committed material**; it needs a re-simulation (4.7 h + 12.5 h + 7.9 h of wall time in the recorded run)
  on raw data that is not committed either.
- The only committed per-candidate figures are the `feasibility` and `plateau point` lines of
  `.planning/phases/16-paper-runtime-composition/evidence/16-63-run-output.txt` (a text file "written afterwards from
  its logs", line 1). They are not bound to the records by any hash. I take them as the run's printed output.
- What those figures are (traced in code, not taken from the other lane): `src/research/run.py:762-786`
  `_plateau_summaries` pools the trades of the four VALIDATION windows of a grid point and calls
  `src/research/report.py:summarize_trades` -> `src/backtest/report.py:build`; `mean_r` is `_decimal_mean` of
  `realized_pnl / realized_risk` over closed trades only (filled, exit SL or TP2; `report.py:606-640`), ordered by exit time.
  So `mean_r` IS the statistic of G2's first conjunct ("mean net R per trade ... over the pooled Validation trades").
  `build` also computes the 95 % stationary-block-bootstrap interval (`report.py:757-771`, the G2 second conjunct) on every
  run, with 100 resamples, and `point_summary` (`src/research/report.py:61-73`) drops it before printing.

**Gate by gate (48 candidates = 16 x 3 registered grid points; equity 600, risk_rate 0.005 from the manifest).**

| Gate | Decidable from committed figures? | Result |
|---|---|---|
| G1 (>=100 pooled, >=30 per fold) | Yes, exactly (`feasibility` lines) | 45 pass, 3 fail: b04 folds 42,20,42,43; b08 38,19,41,42; b16 41,23,48,37 |
| G2 conjunct 1 (pooled mean R > 0) | Yes, exactly (`mean_r`) | 45 fail (mean < 0, from -0.2324 to -0.0106); 3 have a mean above 0: a05 +0.0027, b12 +0.0007, b16 +0.0137 |
| G2 conjunct 2 (95 % block-bootstrap lower bound > 0) | No (no trade list). Not needed for the 45. For a05/b12/b16 only a bound by construction | iid SE is 0.055 / 0.140 / 0.146, i.e. the means are 0.05 / 0.005 / 0.09 SE above zero. Probe `boot_sens.py`: a two-point series matched to the committed n, wins, losses, mean and std, run through the project's own `_stationary_block_bootstrap_means` (p = 0.1, 2000 resamples), gives a lower bound of -0.030 / -0.072 / -0.065 even in the most favourable order a win/loss series can have (wins evenly interleaved), -0.11 / -0.17 / -0.22 shuffled. Fails in every order tried |
| G3 (Holm over 48, adjusted p < 0.05) | No producer exists (`src/research/multiplicity.py` docstring; protocol section 4). Bound only | Holm needs the smallest raw p below 0.05/48 = 0.00104. The most favourable one-sided p found in the probe (centred null, the draft spec's definition) is 0.38. No candidate can pass; 45 candidates have a negative mean so their p is above about 0.5 |
| G4 (max drawdown <= 20 % of equity) | Not exactly: the printed figure is in R (`_max_drawdown` over R values, `report.py:545-558`), the gate is in percent of equity and its producer does not exist | With risk 0.5 % of equity per trade and realized risk between 60 % and 100 % of the budget, 20 % is roughly 40 R to 67 R. 18 candidates are below 40 R (cannot be said to fail), a01 at 78.3 R is above the range, the other 29 are undetermined |
| G5 (holdout) | Not run, correctly: `holdout_consumed.json` has no entry | not applicable (G1-G4 must pass first) |

**Per-candidate verdict under the protocol's conjunction (G1 and G2 and G3 and G4 and G5):**
- 45 of 48: FAIL, certain, on G2 conjunct 1 alone (negative pooled Validation mean; no bootstrap is needed to say so).
- b16: FAIL, certain, on G1 (fold 2 has 23 closed trades).
- a05 and b12: mean above zero by 0.003 R and 0.0007 R; FAIL on G2 conjunct 2 and on G3 with very high confidence
  (bound by construction above), but this is the one place where "certain" would need the trade lists.
- The paper/Demo candidate a01 (`16-DEC-candidate.md`): n = 613, mean -0.1019 R, std 1.103, wins 137 / losses 476,
  observed drawdown 78.3 R. FAIL on G2 conjunct 1, certain. The same point in the first run (2.1.0, cold windows) printed
  -0.1104 R on 343 trades (`evidence/16-46-run-output.txt:108`, committed 2026-10-16 08:23 +0700; the designation record
  was committed 13 minutes later).

**Verdict on the other lane's claim.**
- "No candidate can pass the protocol's gates": HOLDS. Certain for 46 of 48; for a05 and b12 it holds with very high
  confidence and is not strictly provable from committed material (their means are positive by less than 0.05 SE).
- "Most candidates have a negative pooled Validation mean R": HOLDS exactly (45 of 48).
- "The candidate used for paper/Demo is negative": HOLDS (a01, -0.1019 R).
- "a01 has a significantly negative mean (naive z = -2.29)": OVERSTATED as worded. -2.29 is an iid z with no dependence
  adjustment and no multiplicity adjustment; the protocol has no gate that tests "significantly negative", and the
  block-bootstrap interval of a01 cannot be computed from committed material. What can be said: the mean is negative, which
  is enough for G2 to fail.
- "Nothing records a kill-gate verdict": HOLDS as a fact (`docs/research/kill_gate_decisions.json` has `"families": []`),
  but it needs two qualifications: (1) under D013/D030 the kill gate cannot fire before 2027-03-19 (six months after the
  freeze of 2026-09-19), so WITHIN_BUDGET is the state the rule gives today; (2) the protocol asks that "a family's passing
  status is computed from G1-G5 and recorded with a decision reference", and no code computes G2-G4 (`src/analytics/gates.py`
  still says "Numeric acceptance thresholds remain TBD"). So what is missing is not a kill-gate firing but the recorded
  per-family G1-G5 status of a run that is finished. See G-0901.
- "Two of the three D013 conditions are met in fact": PARTLY. "No family holds a recorded passing decision" is true.
  "Three independently specified families have been tested" is true in substance, but the file that the evaluator reads
  lists no family as tested, so the evaluator would report 0 families tested.

## Coverage
| File | Level | Note |
|---|---|---|
| `docs/research/RESEARCH_PROTOCOL.md` | DEEP_READ | sections 0-6 and amendment log |
| `docs/research/experiments/research-run-1-v2-3-0/*.json` (240) | NORMAL_READ | one record read in full; structure is uniform (identity + `no_trade_counts` + `trades_digest`) |
| `docs/research/experiments/research-run-1/*.json` | METADATA_ONLY | superseded 2.1.0 run |
| `docs/research/kill_gate_decisions.json`, `holdout_consumed.json`, `kill_gate_review_registry.json` | DEEP_READ | first two empty; registry has 5 UNRESOLVED items |
| `docs/research/preregistration/*` | NORMAL_READ | manifest (head), one 2.3.0 authorization; grids not read value by value |
| `.planning/phases/16-*/evidence/16-63-run-output.txt`, `16-46-run-output.txt` | DEEP_READ (machine) | all 48 feasibility and plateau lines parsed |
| `.planning/phases/16-*/decisions/16-DEC-candidate.md`, `16-DEC-EQUITY-BASE.md`, `16-DRAFT-G3-pvalue-producer-spec.md` | NORMAL_READ | |
| `src/backtest/report.py` | DEEP_READ | statistics, bootstrap, drawdown, closed-trade rule |
| `src/backtest/entry.py`, `exits.py`, `semantics.py` | DEEP_READ | probed |
| `src/backtest/engine.py` | NORMAL_READ | window processing, signal evaluation, sizing (lines 435-540, 723-942); rest by outline |
| `src/backtest/records.py`, `costs.py` | NORMAL_READ | cost application and R denominator |
| `src/backtest/lifecycle.py`, `ledger.py`, `funding.py`, `case.py`, `series.py`, `constraints.py`, `validator.py`, `binding.py`, `experiment.py`, `simulator.py`, `__init__.py` | METADATA_ONLY | grep only; funding sign and coverage NOT verified by me |
| `src/research/run.py` | NORMAL_READ | run flow, checkpoint, report, record content |
| `src/research/report.py`, `plateau.py`, `feasibility.py`, `multiplicity.py`, `authorization.py` | DEEP_READ | |
| `src/research/manifest.py` | NORMAL_READ | splits, holdout fields |
| `src/research/manifest_build.py`, `register.py`, `settlement_evidence.py`, `__init__.py` | NOT_READ | |
| `src/analytics/stats.py`, `gates.py`, `family.py` | DEEP_READ | |
| `src/analytics/killgate.py` | NORMAL_READ | `evaluate`, `registration_allowed`; probed |
| `src/analytics/cli.py`, `killgate_guard.py`, `clock.py` | METADATA_ONLY | grep of the record path |
| `src/analytics/render_metrics.py`, `render_killgate.py`, `render_common.py`, `render_sidecar.py`, `render.py`, `report.py`, `lifecycle.py`, `approval_delay.py`, `latency.py`, `excursion.py`, `live_outcomes.py`, `slices.py`, `types.py`, `provenance.py`, `no_trade.py`, `universe.py`, `core_metrics.py`, `inputs.py`, `__init__.py` | NOT_READ | out of time; no claim is made about them |
| `docs/backtest/BACKTEST_SPEC.md`, `METRICS.md` | METADATA_ONLY | grep; METRICS first 60 lines |

## Verified Safe Areas
- **No fill on the signal bar; plan active only after the signal close.** Probe `causality_probe.py` case C: the minute closing
  exactly at the signal close trades through the limit, later minutes do not: result `PENDING_AT_DATA_END`, no entry.
  Code: `src/backtest/engine.py:939-941` (`advanced_to=close`), `entry.py:is_minute_eligible`.
- **Future data after the exit does not change a closed trade.** Case B: a +50 % rally appended after the stop-out; the
  trade record is byte-identical to case A. The strategy windows are cut with `bisect_right(closes, close)`
  (`engine.py:802-810`), so no bar closing after the signal close enters `evaluate` (read, not probed on real data).
- **Touch is not a fill.** Case D (low == limit): no entry. `entry.py:is_trade_through` needs limit minus one tick.
- **Same-minute stop and target resolves to the stop; no take-profit on the fill minute.** Cases E and F
  (`exits.py:resolve_mark_minute`): E books SL at 98.00 although the minute high is 130; F leaves the position open.
- **Stop gap gets no price improvement.** Case G: mark minute opens at 96.00 below the 98.00 stop: exit 96.00, flag set.
- **R is net of all modeled costs.** `records.py:393` `realized_pnl = gross - entry_fee - exit_fee - slippage + funding`;
  probe line H reproduces the fees by hand (1.576872). The entry is charged the taker fee and 1 bp slippage although it is
  a limit fill (conservative). The R denominator is the sized worst-case risk scaled by the fill
  (`src/risk/realized_risk.py`), so a plain stop-out is about -0.68 R, not -1 R (probe; consistent with the run's median
  near -0.6 R). Not a defect.
- **`mean_r` of the run output is G2's statistic.** Pooled over the four Validation folds, closed trades only, exit-time
  order (`run.py:762-786`, `report.py:606-640, 664-676`). Development trades do not enter it.
- **Holdout untouched.** `manifest.py:581-592` `research_splits` returns Development and the four folds only; the case is
  built with `end_utc=window.end_utc` (`run.py:343-349`); `holdout_consumed.json` has no entry.
- **Run authorization binds what ran.** `authorization.py:require_authorized` checks grid hash, manifest hash and the
  simulator semantics version; the 2.3.0 file read carries all three. A record file is created exclusively and never
  overwritten (`run.py:726-733`).
- **Holm step-down is implemented correctly** for supplied p-values (`multiplicity.py:holm_adjust`: sorted, running max of
  (m - i) x p_i, capped at 1); it refuses anything but the 48 registered ids.
- **Simulator and paper share the exit, cost and ledger code** (imports only): `src/paper/shadow_fill.py:38-61` and
  `shadow_ledger.py:72-83` import `src.backtest.exits/lifecycle/records/ledger/funding`. Behavioural parity is M10's.

## Decision review
| Decision / rule | Verdict | Yardstick | Reason |
|---|---|---|---|
| D052 causal simulator (active from bar N+1, one-tick trade-through, stop-first, mark triggers) | SOUND | probe, practice | conservative on every ambiguity; verified by probe |
| D036 taker fee on the limit entry | SOUND | practice | overstates cost, never understates |
| D032/D043 G1 floors 100 / 30 | SOUND | practice | fixed before the run; 3 candidates fail it and are reported as such |
| G2 mean > 0 and bootstrap lower bound > 0 | SOUND | practice | but its second half is computed and thrown away (G-0902) |
| D069 one Holm over 48 | SOUND | arithmetic | correct and strict; the p-value producer is missing (KNOWN) |
| G4 20 % of research equity | DOUBTFUL | logic | the conversion from four separately simulated folds is not defined (G-0905) |
| D013/D030 kill gate needs recorded human statuses | DOUBTFUL | logic, probe | never fires when nobody records a status (G-0903) |
| D046 slippage 1 bp / 3 bps, "auto-mode default" | CANNOT_JUDGE | exchange | not calibrated on any fill; take-profit legs use the smaller rate (G-0904) |
| L-03 / L-10 "reporting only, never rank" for the run output | DOUBTFUL | owner goals | it kept the run neutral, and it also kept the outcome from being stated (G-0901) |
| Records hold a trades digest only (B3-WR-02) | DOUBTFUL | protocol section 4 | a digest proves identity but nothing can be recomputed from it (G-0902) |
| D068 back-extrapolated constraints, declared assumption | SOUND as declared | logic | stated openly on every record; not judged further |

## Findings

### G-0901 — Run 1 (2.3.0) is finished and none of its 48 candidates can pass G1-G5; no file states that outcome
- Severity: now MEDIUM / mainnet MEDIUM
- Confidence: CONFIRMED for 46 candidates (exact figures); PROBABLE for a05 and b12 (bound by construction, no trade lists)
- Classification: GAP
- Category: research integrity
- Component: research run 1, acceptance gates
- File: `.planning/phases/16-paper-runtime-composition/evidence/16-63-run-output.txt`; `docs/research/kill_gate_decisions.json`; `src/research/report.py`
- Lines: the 48 feasibility and 48 plateau-point lines of the run output; `report.py:61-73`
- Rule: RESEARCH_PROTOCOL section 4 (G1-G5; "A family's passing status is computed from G1-G5 ... and recorded with a decision reference"); D059 (Phase 26 needs a passing candidate)
- Known-prior: the missing G1-G5 code is KNOWN:G3-004 (ROADMAP line 1521). The outcome itself is recorded nowhere. Raised by lane decisions_trading_soundness as G-2101; this is the independent check that was asked for.
- Evidence: the table in section "Extra task" above; `tmp/backtest_research_analytics/parse_v230.out`, `boot_sens.out`. 45 means are below zero; b16 fails G1; a05 (+0.0027 R, iid SE 0.055) and b12 (+0.0007 R, iid SE 0.140) fail the bootstrap bound in every order tried; the smallest favourable p found is 0.38 against the 0.00104 that Holm needs.
- Expected: after the registered run, each candidate's G1-G4 status is computed and written down with a decision reference.
- Actual: the figures sit in an evidence text file under "plateau section: reporting only"; `kill_gate_decisions.json` has `"families": []`; the paper/Demo candidate a01 has a mean of -0.1019 R on 613 trades.
- Reproduction: `python -B parse_run.py <snapshot> 16-63-run-output.txt points_v230.json`; `python -B boot_sens.py points_v230.json 2000` (PYTHONPATH = snapshot).
- Impact: the roadmap (Demo campaign, go-live gate) proceeds without the fact that, under the project's own pre-registered rules, run 1 produced no acceptable candidate. No money is at risk now. This is the protocol's result, not a statement about future profitability.
- Why tests miss it: no test or gate requires a status after a run; the report module is written to print no verdict.
- Remediation: record the per-family result with a decision reference; build the G2/G3 producer on kept trade lists (G-0902); put the consequence to the owner (O-1).
- Qualification of the other lane's wording: "significantly negative (z = -2.29)" for a01 is an iid figure without dependence or multiplicity adjustment and is not a protocol gate; "negative, therefore fails G2" is the supportable statement.

### G-0902 — The committed experiment records hold no result, the trade lists were not kept, and the G2 interval is computed and discarded
- Severity: now MEDIUM / mainnet MEDIUM
- Confidence: CONFIRMED
- Classification: GAP
- Category: reproducibility, evidence
- Component: research runner
- File: `src/research/run.py`; `src/research/report.py`; `docs/research/experiments/research-run-1-v2-3-0/*.json`
- Lines: `run.py:377-383` (`_result_summary_json` returns only `trades_digest`), `run.py:762-786`; `report.py:22-23` (`_SUMMARY_RESAMPLES = 100`), `report.py:61-73`
- Rule: RESEARCH_PROTOCOL section 4 "Uncertainty reporting - required fields": "Every experiment record includes: Trade counts ... R-multiples: mean, median, standard deviation. Bootstrap interval for expectancy ... Drawdown distribution under resampling ... `SE` ... printed alongside the actual SE from block-bootstrap"; methodology gate 7 "Reproducible"
- Known-prior: B3-WR-02 added the digest (plan 16-61). That the records lack the section 4 fields is not in the registers I read.
- Evidence: a full record (`0081eb04...json`, 3201 bytes) has identity fields, `no_trade_counts` and `"result_summary_json":"{\"trades_digest\":\"84f2...\"}"`, nothing else. `backtest_report.build` computes `expectancy_interval` (lower, upper, `se_diagnostic`) and the resampled drawdown quantiles for every grid point; `point_summary` returns eight figures and drops them. The per-trade lists lived in `C:\rerun-v230\ck\<family>` (run output line 5), a directory outside the repository that no longer exists on this machine. The per-candidate figures exist only in a text file "written afterwards from its logs" by the orchestrator, bound to the records by no hash.
- Expected: a record, or a hashed file beside it, from which G1-G4 can be recomputed and checked against `trades_digest`.
- Actual: recomputing any gate, including the block-bootstrap bound this task asked for, needs a new simulation (about 25 hours of wall time summed over the three families in the recorded run) on raw data that is not committed. A reviewer can check identity, never a result.
- Reproduction: `head -c 5000` of any record; list `C:\rerun-v230`.
- Impact: the central research evidence of the project cannot be audited from the repository. A later G2/G3 producer has to re-simulate first, and a transcription error in the evidence text file would be undetectable.
- Why tests miss it: tests pin the digest and the record schema, not the presence of the section 4 fields.
- Remediation: keep the per-window trade lists (compressed, hashed, digest equal to `trades_digest`) as evidence, and write the section 4 fields into a result file per candidate.

### G-0903 — The kill gate counts only statuses a human chooses to record, so it stays WITHIN_BUDGET for ever when none is recorded
- Severity: now MEDIUM / mainnet MEDIUM
- Confidence: CONFIRMED (probe)
- Classification: DESIGN
- Category: kill gate bypass by omission
- Component: kill-gate evaluator
- File: `src/analytics/killgate.py`
- Lines: 428-454 (`counts`: `family.status is not FamilyStatus.NOT_TESTED`); `src/analytics/family.py:29-33, 78-82`; `src/execution/enablement.py:262-271`
- Rule: D013/D030; RESEARCH_PROTOCOL section 4 "Kill gate D013"
- Known-prior: related KNOWN items WR-10, WR-12, WR-13 in `docs/research/kill_gate_review_registry.json` (UNRESOLVED; WR-10 blocks live enable) and G3-004. The omission path is not among them.
- Evidence: `killgate_probe.out`: with the committed file (`families: []`) the evaluator returns WITHIN_BUDGET with `families_tested=0` on 2026-11-17, 2027-03-19, 2028-09-19 and 2036-09-19. A status is "only ever a recorded human decision" (`family.py:79`); nothing derives TESTED_FAIL from a finished registered run, although 240 records of three families exist. `LiveEnablementController.enable` refuses only a non-evaluated state and INSUFFICIENT_EDGE, so WITHIN_BUDGET is accepted.
- Expected: the D013 condition "three families have been tested under the frozen methodology" follows from the records of a registered run, or a finished run forces a recorded status.
- Actual: the gate that is meant to stop endless work fires only if someone records the failures. Not recording them is the default, and it is what happened after run 1.
- Reproduction: `python -B killgate_probe.py <snapshot>` (PYTHONPATH = snapshot).
- Impact: the six-month kill gate (2027-03-19) will not fire on the present records; the state shown to the owner stays "keep researching". Live placement is separately disabled, so no order risk follows from this today.
- Why tests miss it: tests feed the evaluator hand-built family statuses; none starts from run records.
- Remediation: owner decision O-1. Then either derive "tested" from the experiment records of a completed authorized run, or make the completion of a run require a status entry.

### G-0904 — Take-profit legs are costed as a resting limit (1 bp) although live places TAKE_PROFIT_MARKET orders triggered by mark price
- Severity: now LOW / mainnet LOW
- Confidence: CONFIRMED (code on both sides); the size of the effect is an estimate
- Classification: DRIFT
- Category: cost model
- Component: simulator records vs live protective legs
- File: `src/backtest/records.py`
- Lines: 148-169, 196-201; `src/execution/placement.py:410-430`
- Rule: RESEARCH_PROTOCOL section 3 "the exit policy is the live TP1/TP2 ladder"; D046
- Known-prior: none found
- Evidence: `records.py:151` "TP2 (a resting limit) uses `expected_slippage`"; `placement.py:414,427` `"type": "TAKE_PROFIT_MARKET"`, `"working_type": "MARK_PRICE"`. The stop (also a market order after a mark trigger) is charged `exit_slippage_rate` 0.0003; the two take-profit legs 0.0001. Both rates are "Phase 12 auto-mode default of D046" (`params/trend-pullback/baseline-v6.toml:164-206`), not measured.
- Expected: one slippage assumption for all market-type exits, or a stated reason for the lower one.
- Actual: winning legs carry 2 bps less cost than the same order type on the losing side.
- Reproduction: read the two files.
- Impact: a small bias in favour of every candidate. Rough size (assumed stop distance 1.5 %): 2 bps of exit notional is about 0.013 R per take-profit trade, about 0.004 R on the mean at a 28 % win rate. That is the size of the positive means of a05 (+0.0027 R) and b12 (+0.0007 R), so the correction can only move them toward zero or below. It changes no verdict of G-0901.
- Why tests miss it: the cost tests pin the simulator's own rule.
- Remediation: owner decision O-3; a change is a simulator-semantics change (new version, D075/D076 procedure).

### G-0905 — G4 has no defined computation: the run prints an additive drawdown in R over four folds that each start at fresh equity
- Severity: now LOW / mainnet LOW
- Confidence: CONFIRMED
- Classification: AMBIGUITY
- Category: acceptance gate definition
- Component: G4
- File: `src/backtest/report.py`
- Lines: 545-558; `src/research/run.py:355-363`
- Rule: RESEARCH_PROTOCOL section 4 G4 "maximum drawdown of the pooled Validation equity curve is at most 20% of research equity, using the same equity base and risk_rate convention as the risk engine"
- Known-prior: KNOWN:G3-004 covers "no gate code"; the definition gap is not stated there.
- Evidence: `_max_drawdown` sums R values; each fold is simulated from `manifest.equity` = 600 with its own ledger, so there is no single pooled equity curve. With risk 0.5 % of equity and realized risk between 60 % and 100 % of the budget, 20 % of equity is anywhere from about 40 R to 67 R: 18 candidates are below 40 R, a01 (78.3 R) is above 67 R, 29 are in between and cannot be decided.
- Expected: one written rule for how four fold ledgers become "the pooled Validation equity curve" and how it becomes a percentage.
- Actual: none; the producer would have to choose it after the results are known.
- Reproduction: `parse_v230.out`, column ddR.
- Impact: none on run 1 (no candidate reaches G4 with G1-G3 passed). It matters for a later run.
- Why tests miss it: no G4 code exists.
- Remediation: fix the rule in a protocol amendment before any further run.

## Owner decisions
- O-1 (G-0901, G-0903): record the result of run 1 or not. In numbers: 48 candidates; 45 have a negative Validation mean (from -0.23 R to -0.011 R); one is below the trade floor; two are positive by 0.003 R and 0.0007 R with an uncertainty of 0.055 R and 0.14 R. Options: (a) record the three families as tested with no passing candidate, so the kill gate can fire on 2027-03-19 if nothing passes by then; (b) leave it unrecorded, and the state stays WITHIN_BUDGET whatever happens.
- O-2 (G-0902): keep trade lists as evidence. Cost: disk space, and one more simulation of about 25 hours if the lists of run 1 are wanted.
- O-3 (G-0904): one slippage rate for all market-type exits (3 bps) or keep 1 bp on take-profits; a change is a new simulator version.

## Open Questions
- Not computed, and not computable from committed material: the real 95 % block-bootstrap interval and the G3 p-values of any candidate.
- Not verified by me: funding sign and coverage (`src/backtest/funding.py`), the ledger and daily-stop logic, `case.py` input validation, the strategy-driven path of the engine on real data (the causality probe used a scripted plan; the window cut was read, not probed), and all of `src/analytics` beyond stats, gates, family and the kill-gate evaluator.
- For the live lanes: `LiveEnablementController.enable` (`src/execution/enablement.py:262-271`) accepts WITHIN_BUDGET, so no code requires a passing candidate before live is enabled; KNOWN WR-10 covers the caller-supplied state. Is the D059 "passing candidate" condition planned as code in Phase 26?
- For M13: `16-63-run-output.txt` is assembled by hand from logs; is there any check that its figures equal the run logs?
- For M10: behavioural parity of shadow fills with the simulator (imports are shared; behaviour not checked here).

## DONE
