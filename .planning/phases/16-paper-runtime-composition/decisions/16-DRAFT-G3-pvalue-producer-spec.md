# DRAFT: specification of the G3 p-value producer (protocol v2.3.0, D069)

status: DRAFT for the reviewer and the user. Nothing here is in force, no code or protocol file is changed by it, and no decision is recorded. Written 2026-10-14 by the orchestrator. Every "proposal" is a proposal; every OPEN item needs a decision before anything is built.

## 0. Why this exists and who needs it (a correction)

D069 fixed the correction rule (one Holm-Bonferroni over 48 candidate-level p-values) and `src/research/multiplicity.py` corrects supplied p-values. It does not produce them. G3 of protocol v2.3.0 says the p-value is "one-sided seeded stationary block-bootstrap" for the hypothesis that mean net R is at most 0.

Correction of an earlier note: plan 16-46 does NOT need these p-values. Its objective lists floor reachability, the plateau analysis, the mark-hole count, the `modeled_costs_per_unit` limitation and timing; it prints no G3 figure. In Phase 16 the candidate "need not pass G1 to G5, and G1 to G5 never rank candidates" (L-10, plan 16-48). The owner of the executable G1-G5 gate code is Phase 26 (inherited item G3-004 in the roadmap: the executable gate code of `src/analytics/gates.py` does not exist yet). The producer is therefore a Phase 26 dependency (or earlier by a roadmap decision), not a blocker of the O-03 authorization or of 16-46. The tracker note in `deferred-items.md` was corrected to say this.

## 1. What already exists (read from the repository, 2026-10-14)

- `src/backtest/report.py:504` `_stationary_block_bootstrap_means(r_values, *, seed, n_resamples, p)`: Decimal, one `random.Random(seed)`, block length geometric with mean 1/p (`_sample_block_length`, cap `_MAX_BLOCK_LENGTH = 10000`), circular wrap, returns the list of resampled means. Private name.
- `src/backtest/report.py:619` `build(...)`: closed trades only (`_classify`: filled entry and exit kind SL or TP2; END_OF_DATA is not closed), R multiple = realized_pnl / realized_risk (`_r_multiple`, zero-risk trades excluded and counted), ordered by realized time `(exit_time_utc, trade_id)` (`_realized_order_key`, WR-06), `resamples` default 10,000 (minimum 100), `probable` default 0.1, the expectancy interval is the 2.5 / 97.5 percentile pair of the UNcentred resampled means, the drawdown stage uses `seed + 1`.
- `src/analytics/types.py`: `BOOTSTRAP_BLOCK_P = Decimal("0.1")`, `DEFAULT_RESAMPLES = 1000`, `DEFAULT_BASE_SEED = 20260929`, `MIN_RESAMPLES = 100`; `core_metrics` uses `base_seed + ordinal`.
- `src/research/run.py` (about lines 319-340): the runner already pools the Validation trades of each grid point (four consecutive folds) and feeds them to the report `build`; this is a ready input for a p-value, reporting only.
- G2 is therefore already computable: `interval.lower > 0` and mean > 0 on the pooled Validation closed trades.

## 2. What is missing

A one-sided p-value for H0: mean net R <= 0, per candidate, from the same resampler. The existing function resamples the observed series, which gives an interval around the observed mean, not a null distribution. A p-value needs the series shifted to mean zero before resampling.

## 3. Proposed definition (OPEN items in section 4)

Input: the ordered list `r_values` of one candidate: R multiples of the closed trades pooled over the four Validation folds, ordered by realized time, exactly the population `build` uses and G1 counts. Output: one `Decimal` p in (0, 1].

1. Observed statistic `t = mean(r_values)`.
2. Null series `r0_i = r_i - t` (mean exactly 0, same dependence structure and spread).
3. Draw `B` stationary-block-bootstrap means of `r0` with block parameter `p_block`, circular wrap, seed `s` (the same resampler as section 1, so the dependence model is the one the interval already uses).
4. `p = (1 + #{b : mean*_b >= t}) / (B + 1)`. The +1 keeps p above zero and is conservative.
5. Undefined cases return `p = 1` and are still counted in m (reviewer item 1, record 16-DEC-V230): fewer than two R-valued closed trades; zero sample variance (all `r_i` equal, which would make every resample equal and the count degenerate); no closed Validation trade.
6. The candidate passes G3 only when its Holm-adjusted p (over all 48, `holm_adjust_confirmatory`) is below 0.05. G2 remains an uncorrected conjunct.

## 4. OPEN decisions

- D-A (reuse): the resampler is a private function in `src/backtest/report.py`. Options: (1) export a public alias there (no behaviour change, but it touches the module behind report digests; needs the reviewer's view on risk); (2) a copy in `src/research` (duplicated, can drift); (3) a thin public wrapper in a new module that imports the private name (style objection). A copy is not recommended without a decision.
- D-B (resamples `B` and runtime): the smallest Holm threshold is 0.05/48 = 0.00104. With B = 10,000 the smallest possible p is 1/10,001 and the Monte Carlo standard error at p near 0.001 is about 0.0003 (about 30 percent relative), which is noisy exactly at the decision boundary. A larger B reduces it, but the resampler is Decimal-based and slow; cost grows as B x n_trades x 48 candidates. Measure the time on a realistic n before choosing B; B must be pre-registered and never tuned from results. Decimal is required in `src/research` (`tests/test_domain_no_float.py`), so a float fast path is not available without its own decision.
- D-C (block parameter): reuse `BOOTSTRAP_BLOCK_P = 0.1` (mean block 10) as G2's interval does, or fix another value; either way pre-registered, identical for all 48, never chosen from data.
- D-D (seeds): one seed per candidate, derived from a pre-registered base seed and the candidate's ordinal in the sorted list of the 48 hypothesis ids (the ordering `confirmatory_hypothesis_ids` returns), in a namespace that cannot collide with the expectancy-interval seed or its `seed + 1` drawdown seed. Proposal: `base + 1_000_000 + ordinal`, with the base seed pre-registered in the amendment or the run authorization.
- D-E (tie convention): `>=` as above (conservative) versus `>`; and the +1 correction. Proposal as in section 3.
- D-F (where it runs and what is printed): Phase 26 evaluates gates; printing p-values per grid point during Phase 16 would sit next to the plateau and could read as ranking (L-03, L-10). Proposal: do not print them in Phase 16.
- D-G (S1): scenario S1 results never produce a p-value that enters the 48-set (D069). `holm_adjust_confirmatory` takes exactly one mapping, but the caller must be tested to pass S0 only.
- D-H (pre-registration form): protocol v2.3.0 G3 names the procedure in words; the exact B, block parameter and seed rule would be a pre-registered parameter record (hashed like the parameter sets) or an addendum, not edited into the frozen protocol after a result.

## 5. Tests to require when it is built (not yet written)

- Fixed seed, fixed small vector: byte-equal p across runs and platforms; a different seed gives a different p.
- Shift behaviour: adding a constant c to all `r_i` changes `t` by c and p decreases as the mean rises.
- Null calibration: for seeded independent zero-mean samples the p-values are close to uniform (stated tolerance), and the share below 0.05 is near 0.05.
- Undefined cases: empty, one value, constant series all return p = 1.
- Decimal only: float, int, bool and str inputs refused; no float in the module.
- Integration: 48 p-values (from synthetic trade lists with the real 48 ids) through `holm_adjust_confirmatory` and `g3_passes`; an S1 list cannot enter.
- A recorded measurement of the runtime for the chosen B.

## 6. Out of scope

Any change to G1, G2, G4, G5; any edit of the frozen protocol; building `src/analytics/gates.py`; reading the Holdout; any run.
