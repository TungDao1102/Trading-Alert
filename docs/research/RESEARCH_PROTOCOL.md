# Research Protocol (Frozen)

> **Protocol version:** v2.1.0
> **Status:** FROZEN
> **Frozen on:** 2026-09-19
> **Amended on:** 2026-10-07
> **Supersedes:** v2.0.0

## §0 Identity, status, and one-way flow

This document is the **frozen research contract** for the Binance Futures research/execution project. It restates methodology that is owned by other canonical documents (`docs/backtest/BACKTEST_SPEC.md`, `docs/configuration/CONFIGURATION.md`, `docs/data/DATA_MODEL.md`, `docs/research/TRADING_STRATEGY_RESEARCH.md`) so that an experimenter can read dataset splits, cost model, execution assumptions, and acceptance gates in one place before running any parameter work — but it does **not** duplicate the underlying methodology. Every section cites its owning doc by title.

**Status vocabulary is binary.** A section header line carries exactly one of:

- `Status: DRAFT` — the doc is editable; new content may be added or revised.
- `Status: FROZEN` — the doc is immutable for that version. The freeze is binding when **all three** witnesses agree: this header line, a `DECISIONS.md` row naming the freeze version, and the `DOC_STATUS.md` index entry. Any two without the third means `DRAFT` in effect, and the research-gate CI workflow enforces all three at `01-04`.

**Living-doc firewall (one-way flow).** `docs/research/TRADING_STRATEGY_RESEARCH.md` is the living draft for new ideas, candidate families, and open questions. The protocol doc copies methodology *out of* the living draft once. After the protocol is frozen, any new learning enters the protocol **only** via a versioned amendment:

- clarification or wording fix → bump to `v1.0.x` (semantics unchanged);
- semantic change to dataset splits, cost model, execution simulation, or acceptance gates → bump a minor or major version per Semantic Versioning (precedents: `v1.1.0` minor, `v2.0.0` major, `v2.1.0` minor); add a `Supersedes` line and a migration paragraph.

A semantic change to the protocol triggers a new strategy-version lineage downstream (see `docs/strategy/TRADING_STRATEGY_SPEC.md` §12 Strategy versioning). Living-draft edits never modify a frozen protocol section in place.

### Migration (v1.0.1 to v1.1.0)

This is a semantic amendment (dataset splits, cost and execution assumptions, acceptance gates) per D032 and D043. The v1.0.1 text is unchanged in git history at commit `a68e97736e65b563c7ddbb8bf746d4225ad31f36` and is superseded, not edited. What changes: numeric acceptance thresholds, split proportions, the variant budget and multiple-testing correction, a single-use holdout with a consumed marker, no human pass override, the entry fee at the taker rate (D036), mark-price protective triggers (D037), `partial_fill_fraction` 1.0 as the canonical value (D038), the point-in-time research universe (D039), and one canonical quantization order. What does not change: the D030 kill-gate firing rule, the `Frozen on` clock start (2026-09-19, so the D013 six-month clock is not restarted), and the identity tuple in §5. Downstream strategy-version lineages restart per `docs/strategy/TRADING_STRATEGY_SPEC.md` §12. The full pre-registration body follows in §1–§4.

### Migration (v1.1.0 to v2.0.0)

This is a semantic amendment (execution simulation) per D032, D043 and D052. The v1.1.0 text is unchanged in git history at commit `7a80af52146d7a8112cab3536143c179050a02d2` and is superseded, not edited. What changes: the backtest simulator is rebuilt as a cross-bar event loop. A plan created at the close of strategy bar N is active from bar N+1 and the signal bar is never examined for a fill; a limit fills only on a trade-price 1m trade-through of one tick; SL and TP trigger on mark-price 1m klines (D037); the exit policy is the live TP1/TP2 ladder (TP1 is a reduce-only partial of half the filled quantity, TP2 closes the remainder, the stop is unchanged after TP1); funding is modeled at every actual `fundingTime`; constraints are point-in-time; a simulated ledger carries equity, positions, resting entries and the daily loss; one R denominator is shared with live; `simulator_semantics_version` 2.0.0 joins the experiment identity. **All earlier backtest evidence is void** (D052): the v1 simulator examined the signal bar, filled at a touch, booked a single-exit TP1 and ignored funding and the ledger. What does not change: every pre-registered threshold, the split proportions, the variant budget and multiple-testing correction, the single-use holdout rule, the D030 kill-gate firing rule, the identity tuple in §5 and the `Frozen on` clock start (2026-09-19, so the D013 six-month clock is not restarted). Downstream strategy-version lineages restart per `docs/strategy/TRADING_STRATEGY_SPEC.md` §12: the evidence-bearing strategy sets are the new versioned sets created in Phase 15, not the sets that existed before this amendment.

### Migration (v2.0.0 to v2.1.0)

This is a semantic amendment (acceptance gate G5) per D057 and D060. The v2.0.0 text is unchanged in git history at commit `6857c1d9f488f2fa6ec02f452697bde4c68da419` and is superseded, not edited. What changes: G5 gains a floor of at least 30 closed trades in the holdout, counted exactly as G1 counts closed trades; fewer than 30 means the candidate cannot pass G5 and the holdout counts as consumed for that lineage (never re-run on the same holdout; a re-evaluation needs a new amendment and a new lineage); 30 or more only makes the candidate eligible for evaluation and is not evidence of an edge; no softer threshold and no new status vocabulary exist. `docs/research/holdout_consumed.json` moves to schema `holdout-consumed/2`, where each entry carries its own `protocol_version` beside `lineage_id`, `candidate_sha256`, `consumed_at_utc` and `decision_ref`. What does not change: G1 to G4, the 40/40/20 split and the walk-forward folds, the cost model, the execution simulation (`simulator_semantics_version` 2.0.0), the variant budget and multiple-testing correction, the D030 kill-gate firing rule, the `Frozen on` clock start (2026-09-19, so the D013 six-month clock is not restarted) and the strategy versions. Nothing is applied backwards: no holdout entry and no kill-gate decision exists, so v2.0.0 stays historical and no result was produced under it.

**Numeric-gate status (v1.1.0).** The acceptance thresholds, split proportions, variant budget, multiple-testing correction and holdout rule are pre-registered numerically in §1 and §4 per D032 and D043, before any Validation run. Strategy parameters (ATR multipliers, RR minima, expiry hours) stay versioned parameter-set values owned by the family sheets and the registry (§5). A pre-registered value changes only by a new protocol version and a new candidate lineage, never after a result is seen.

---

## §1 Dataset splits

> **Source:** `docs/backtest/BACKTEST_SPEC.md` — sections "Dataset splits", "Walk-forward", "Statistical power and uncertainty", "Research universe vs live universe"; `docs/research/TRADING_STRATEGY_RESEARCH.md` — anti-overfitting rules and stop conditions.

### Three-way split

Every backtest/paper run partitions data into three sequential blocks:

```text
Development
    ↓
Validation
    ↓
Final holdout / forward test
```

- **Development** — the first 40% of the dataset by time (D032, D043); exploratory sweep space, feature engineering, structural hypothesis selection.
- **Validation** — the next 40% of the dataset by time, evaluated as four consecutive equal-length walk-forward test folds (anchored training window from the dataset start, parameters not re-fit inside a fold, every counted variant evaluated on all four folds); out-of-sample check on parameter regions chosen during Development; never used to invent new regions.
- **Final holdout / forward test** — the last 20% of the dataset by time, locked; the **final holdout must not be used to choose parameters**. Its sole purpose is the one-time honest assessment of a candidate before live consideration; it is single-use per candidate lineage (§4, D032, D043).

### Walk-forward

Where practical — and especially when testing parameterized structure/ATR rules — use rolling windows:

```text
train → validate → roll forward
```

The rolling period must be **fixed before** any evaluation on a window; the choice of period itself counts as a methodology decision recorded in the parameter registry (see §5) and is not tuned per family. Walk-forward results are reported per window and aggregated; an aggregate "best point" without per-window evidence is not accepted.

### Universe discipline

- **Research universe:** the point-in-time universe of D039 — the top 10–15 USDT perpetuals by trailing 30-day quote volume at the dataset start date, delisted symbols included — declared in `docs/research/universe/research-universe-v1.toml` (status DRAFT until Phase 13 freezes and hashes it, before any evaluation). Once FROZEN, the experiment record (§5) carries its content hash.
- **Live V1 universe:** BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT (per `docs/00_PRODUCT_SCOPE.md`); a separate list, unchanged by the research universe.
- The experiment report must show results **both** for the broader research slice and the live-5 slice. A strategy is not accepted solely because the broader universe rescues a weak live universe.

### Anti-overfitting rules R1–R6

Restated from `docs/research/TRADING_STRATEGY_RESEARCH.md` anti-overfitting rules. These are rules of the protocol; deviations require an amendment:

- **R1** — Parameter changes need a stated reason recorded against the experiment.
- **R2** — Prefer plateau behavior over point optimum; a narrow isolated optimum is a robustness warning.
- **R3** — Out-of-sample evidence is mandatory; in-sample goodness is not a substitute.
- **R4** — Costs are modeled from experiment #1, not retrofitted after a favorable result is observed.
- **R5** — No daily-PnL targeting; NO_TRADE is a valid and reportable outcome.
- **R6** — No optimization on skipped trades; skipped/expired plans remain part of the journal record.

### Fixed proportions (v1.1.0)

- The split is fixed at 40% Development, 40% Validation (four consecutive equal-length walk-forward test folds) and 20% final holdout, by time. These proportions were chosen before any evaluation (D032, D043; planner choice under the D-03 pre-registration) and are not tuned per family. The dataset start and end, and the resulting fold boundaries, are recorded in the experiment record (§5).

---

## §2 Cost model

> **Source:** `docs/backtest/BACKTEST_SPEC.md` — sections "Fees and funding", "Limit-order simulation"; `docs/trading/RISK_MANAGEMENT.md` — quantization and realized-risk gate; `docs/research/TRADING_STRATEGY_RESEARCH.md` — funding and slippage discussion.

Every backtest/paper run **must expose** cost configuration. The minimum declared fields are:

### Required cost fields

| Field | Definition | Reference |
|---|---|---|
| `entry_fee` | Fee applied at entry, basis points per side; taker rate for canonical parameter sets (D036) | exchange schedule, re-verified at implementation |
| `exit_fee` | Taker/maker fee applied at exit | exchange schedule |
| `funding_treatment` | When funding applies and how it is signed | research §10.x (by title) |
| `slippage_model` | Effective-entry formula (see below) | this section |
| `spread_fill_assumptions` | Spread observed vs assumed fill price | this section |

### Slippage — never zero by default

Slippage is applied as an **effective-entry formula**, never as a zero default:

```text
effective_entry = intended_entry + slippage
```

`slippage` is calibrated from paper/live fill data and recorded in the cost model snapshot (hashed, see §5). For research, slippage is non-zero from experiment #1 — see anti-overfitting rule R4. Calibration is a separate protocol amendment once empirical data exists; until then, the default direction is "use the upper end of the observed maker/taker spread as a conservative floor."

### Spread and fill assumptions

- The backtest must distinguish **touched price** from **filled price** for limit orders (see §3 execution assumptions).
- Canonical parameter sets use `partial_fill_fraction = 1.0` (D038), identical for candidates and baselines; partial or missed fills are a separate sensitivity run, never a canonical parameter.
- A retest/touch that does not fill is logged with the same attribution fields as a fill. A limit fills only on a trade-price trade-through of one tick (§3); a touch without trade-through is counted per plan and is never terminal.

### Funding

Funding is charged at every **actual** `fundingTime` of the symbol's funding history at which the position is open (`entry_time <= fundingTime < exit_time`); there is no fixed 8 h grid, because the interval can differ per symbol. The rate applied is the Binance-published USDⓈ-M perpetual funding rate; for periods outside the public API window, self-collected historical funding rates are used (Phase 0 data foundation).

- **Sign convention (D052):** `funding_pnl = -sign(position) x open_quantity x markPrice(fundingTime) x fundingRate`, with sign +1 for LONG and -1 for SHORT. A LONG pays when the rate is positive and receives when it is negative; a SHORT is the mirror. `open_quantity` is the quantity open at that instant, so after a TP1 the post-TP1 remainder is charged.
- **Mark price:** the funding-history row's mark price; when it is empty, the open of the mark-price kline of that minute.
- **In and out:** funding is part of net PnL and of R and is never part of position sizing. The convention (`funding_convention`, `MARK_NOTIONAL_SIGNED_V1`) is part of the cost snapshot and of `cost_model_hash` — never retrofitted.
- **Coverage rule:** a holding window is covered only when consecutive funding rows are at most the symbol's cadence (8 h or 4 h) plus 60 s apart and the window lies inside the loaded closed UTC days. Otherwise the run fails closed, unless the caller passes an explicit allowed-gap list, which is recorded on the output.
- **Not modeled:** the exchange's short grace window around `fundingTime` (a position closed within seconds of the instant); the fact and its fetch date are in `docs/SOURCES.md`.

### Quantization — floor-only, identical across modes

> **Source:** `docs/trading/RISK_MANAGEMENT.md` §11 (the canonical statement of the check order, D031); restated in the repo-root `AGENTS.md` Constraints.

The realized quantity is computed in this canonical order (first failure wins):

1. Floor the raw quantity to the symbol's `stepSize` (Binance `exchangeInfo` — re-verified, never hard-coded).
2. Reject when the floored quantity is below the symbol's minimum quantity (`MIN_QTY_REJECT`).
3. Reject when the notional is below the symbol's minimum notional (`NOTIONAL_REJECT`).
4. Reject when realized risk over allowed risk is below `minimum_risk_utilization_after_rounding`, baseline 0.6 (`UTILIZATION_REJECT`); the exact percentage is a versioned parameter and may be tightened in live mode.
5. A rejection yields NO_TRADE. **NO_TRADE preferred over round-up.** Round-up silently inflates risk beyond the budget and is forbidden.

This quantization logic is **identical** in backtest, paper, and live. Any divergence must be reported as an incident and fixed in the engine, not patched at the call site.

---

## §3 Execution assumptions

> **Source:** `docs/backtest/BACKTEST_SPEC.md` — sections "Candle-close rule", "Intrabar ambiguity", "Limit-order simulation", "Baselines"; `docs/research/TRADING_STRATEGY_RESEARCH.md` — closed-bar rules, warm-up, intrabar resolution.

### Closed-candle rule

Strategy decisions use **only** information available by the source candle close. Specifically:

- No future candle data leaks into historical decisions.
- No future swing confirmation leaks.
- No future intrabar outcome leaks.
- Core signals on closed candles only; warm-up indicators (e.g. EMA200 on the 4H) are flagged invalid until sufficient history is available.
- A plan created at the close of strategy bar N is active from bar N+1. The signal bar's own range is never examined for a fill or an exit, and an exit can never precede the entry.

### Timeframe hierarchy

- **Decision timeframes:** 4H (regime/context) and 1H (setup). 15M is optional, used only for entry refinement where the candidate spec calls for it.
- **Execution simulation timeframe:** 1m, as one continuous sorted series per symbol: trade-price klines for entries, mark-price klines for exits. A missing 1m trade minute never produces a fill. A missing 1m mark minute resolves once at the strategy-bar close (see "Intrabar ambiguity" below), is flagged and is counted in the report.

### Intrabar ambiguity — fixed before evaluation

When one 1m mark-price minute touches both the stop and a target:

1. The canonical tie-break is **conservative adverse-first (`STOP_FIRST`)**, fixed before any evaluation and written to the experiment record: the stop is booked and the target is not.
2. On the fill minute only the stop can trigger; a target touched on that minute is deferred to later minutes.
3. A stop gap is booked at the adverse of the trigger price and the mark-minute open (no price improvement) and sets a counted flag.
4. When 1m mark coverage is missing for part of a strategy bar, the rest of that bar is resolved once at the strategy-bar close from the bar range, stop-first, with a counted `fallback_applied` flag and a coverage note. The fallback is for missing or ambiguous bars only, never the default path, and never produces an entry.
5. Alternatives (next-finer-timeframe, mark ambiguous and segregate) are not used by canonical runs.

### Protective trigger price series (D037)

Protective SL/TP triggers are evaluated on mark-price klines (Binance markPriceKlines) with `workingType` `MARK_PRICE` recorded on the plan, so backtest, paper and live share one trigger price series (D037). Exit prices are the trigger price with the cost-model slippage terms, with no price improvement.

**Exit ladder (D052, mirrors live):** TP1 is a reduce-only partial of half the filled quantity (`TP1_QUANTITY_FRACTION` 0.5, a code constant covered by `simulator_semantics_version`, not a tunable), sized through the live `size_protectives_to_filled_qty` helper (a TP1 that cannot be sized rejects the plan as NO_TRADE with the live reason). TP2 closes the remainder. The stop is unchanged after TP1. A position is carried until SL, TP2 or data end; there is no time stop.

### Limit-order simulation — mandatory checklist

The backtest engine must model, per limit order:

- **touched vs filled** — the limit is the tick-snapped live order price. A LONG fills only when a trade-price 1m low is at or below `limit - tick`, a SHORT only when a 1m high is at or above `limit + tick` (trade-through of at least one tick). The fill price is the limit (a gap through it gets no price improvement) and the fill time is the close of the deciding minute. A touch without trade-through is counted and never terminal.
- **partial fill** — canonical sets use `partial_fill_fraction = 1.0` (D038); a partial-fill fraction below 1.0 is applied before any TP/SL logic only in a separate sensitivity run.
- **time-in-force / expiry** — a resting entry expires when the close of a simulated minute is after `expiry_utc` (a minute closing at or before it can still fill); expiry is judged against the simulated minute, never a wall clock. A re-quote after expiry is a new order, not a fill.
- **cancel-after-invalidation** — when a setup is invalidated (CANDLE_CLOSE rule, §6), its unfilled limit order is canceled, not left to fill retroactively. Within one strategy bar the fill is evaluated first, invalidation second, expiry last.
- **no retroactive fill after expiry** — once an order has expired, a later price touch is not a fill.
- **one plan or position per symbol** — a re-signal while a plan rests or a position is open is skipped and counted as a conflict with an open position.
- **daily stop** — a DAILY_STOP cancels resting entries; protective stops of open positions stay (D033).
- **data end** — a position open at data end closes at the last mark close as `END_OF_DATA`; a plan still resting is `PENDING_AT_DATA_END` (never `EXPIRED`). Both are kept as records, counted and reported separately, and excluded from pooled R and the closed-trade floor.

### Baselines

Every candidate is compared against:

- **no-trade** baseline (the null distribution), and
- at least one **simple baseline** — a buy/hold reference for spot-style setups or a simple trend filter without the proposed setup for swing setups.

The purpose is not to declare a winner; the purpose is to measure whether the added complexity contributes value beyond a simple comparator.

### NO_TRADE as a valid outcome

NO_TRADE is a first-class outcome reported alongside trades. The experiment record must include the count of NO_TRADE decisions and the reason category (regime filter, RR floor, conflict with open position, data unavailability, kill-gate trip). The record also carries the counts of `END_OF_DATA`, `PENDING_AT_DATA_END`, fallback and stop-gap events.

---

## §4 Acceptance methodology

> **Source:** `docs/backtest/BACKTEST_SPEC.md` — sections "Acceptance gates" (numbered list) and "Statistical power and uncertainty"; `docs/research/TRADING_STRATEGY_RESEARCH.md` — acceptance-draft categories and stop conditions; `docs/DECISIONS.md` D013 (kill gate).

### The 10 acceptance gates — methodology

A strategy may proceed only when **all ten** methodology criteria are met. Each criterion is a deterministic rule; none depend on a single point estimate:

1. **Deterministic rules** — every signal/plan/order state is reachable from data + parameter set + strategy version alone, with no LLM or subjective classifier in the decision path.
2. **No material look-ahead** — closed-candle rule (§3) is enforced; future data does not leak.
3. **Costs modeled** — every backtest exposes entry/exit fee, funding, slippage, and spread (§2).
4. **Not single-symbol/session** — results span symbols and time slices; single-symbol dominance is a rejection signal.
5. **OOS consistent** — out-of-sample behavior is not materially inconsistent with in-sample without an understood, recorded reason.
6. **Operationally tolerable drawdown** — maximum drawdown of the pooled Validation equity curve is at most 20% of research equity (gate G4 below); loss streak is reported, not gated.
7. **Reproducible** — the experiment record (§5) carries enough identifiers that another agent can re-run the exact same experiment and obtain byte-equivalent results.
8. **Distributional/interval uncertainty** — uncertainty is reported with distributional analysis (bootstrap intervals, resampled drawdowns), not a single expectancy number.
9. **No single-point dependence** — no critical conclusion rests on a single symbol, quarter, or isolated parameter point.
10. **Baseline-compared** — the candidate is compared against declared baselines (§3), not evaluated in isolation.

### Pre-registered thresholds (v1.1.0)

Pre-registered per D032 and D043 before any Validation run. Every number below is fixed at freeze; a change forces a new protocol version and a new candidate lineage, and no value is ever changed after a result is seen.

**Variant budget:** N = 25 per family, counting every parameter combination evaluated in Development or Validation, logged in the experiment record; exceeding it needs a new protocol version.

1. **G1 (trade floor)** — at least 100 closed trades pooled across the four Validation folds and at least 30 closed trades in each Validation fold; a candidate below the floor cannot pass and the floor is never lowered after the freeze.
2. **G2 (expectancy)** — mean net R per trade after full costs (taker entry fee, exit fee, funding, slippage) over the pooled Validation trades is above 0 and the lower bound of the 95% block-bootstrap interval of that mean is above 0.
3. **G3 (multiple testing)** — one-sided seeded stationary block-bootstrap p-value for the hypothesis that mean net R is at most 0, Holm-Bonferroni adjusted at family-wise alpha = 0.05 over the family's counted variants; the candidate passes only when its adjusted p-value is below 0.05.
4. **G4 (drawdown)** — maximum drawdown of the pooled Validation equity curve is at most 20% of research equity, using the same equity base and risk_rate convention as the risk engine.
5. **G5 (single-use holdout)** — the candidate lineage evaluates the final holdout (the last 20% of the dataset by time) exactly once, after G1-G4 pass, with parameters frozen; it requires at least 30 closed trades in the holdout, counted exactly as G1 counts closed trades, and it passes only when mean net R after full costs is above 0 and maximum drawdown is at most 20% on the holdout block. A candidate with fewer than 30 closed trades in the holdout cannot pass G5, the holdout counts as consumed for that lineage, and it is never re-run on the same holdout; a re-evaluation needs a new protocol amendment and a new candidate lineage. The floor is never lowered after the freeze. Thirty is an eligibility floor for the statistical evaluation, never evidence of an edge.

Holm-Bonferroni is applied per family; selecting one of the three families is an additional uncorrected layer, so the worst-case family-wise false-pass rate across three families is about 14% (1 minus 0.95 cubed); a cross-family correction needs an amendment.

A candidate passes only when G1-G5 all pass. A human may reject a candidate that passes; a human may never pass a candidate that fails (D032, D043).

**Holdout consumed marker.** Before the holdout is evaluated the harness appends `lineage_id`, `candidate_sha256`, `consumed_at_utc`, `decision_ref` and `protocol_version` (the protocol version in force when the entry is written; schema `holdout-consumed/2`) to `docs/research/holdout_consumed.json`, `candidate_sha256` being the hash of `strategy_id`, `strategy_version` and the candidate `parameter_set_hash`. A second evaluation of an already listed `lineage_id` or `candidate_sha256` is a violation and the result is void. Lineage means a `strategy_id` plus its `strategy_version` line; successive lineages on one holdout window erode it, which the marker makes countable.

**Power note.** With sigma about 1.2 R and Holm over 25 variants the trade floor detects only a large edge, about 0.35 R. The trade rate is unmeasured until the Phase 14 causal simulator exists, so D043 records that the floor may be unreachable at the decided dataset depth; that shortfall is reported, never papered over.

### Uncertainty reporting — required fields

Every experiment record includes:

- Trade counts: overall, by symbol, by quarter, by regime tag.
- R-multiples: mean, median, standard deviation.
- **Bootstrap interval for expectancy** — block-bootstrap under plausible dependence, not naive IID resampling when trades are clustered.
- Drawdown distribution under resampling (not a single peak-to-trough line).
- Per-candidate uncertainty questions (independent-ish opportunities, bootstrap sensitivity, slice consistency, universe-broadening honesty, plateau existence).
- Diagnostic: `SE ≈ σ / sqrt(n)` printed alongside the actual SE from block-bootstrap so the dependency adjustment is visible.

### Kill gate D013

> **Source:** `docs/DECISIONS.md` D013 (≥3 independently specified families AND ≥6 months research; else stop adding complexity, keep live disabled, classify as research/journal platform; NO_TRADE valid).

The kill gate fires only when **all three** conditions hold:

- at least three **independently specified** candidate families have been tested under the frozen methodology (backtest + out-of-sample evidence), **and**
- at least six calendar months have elapsed since the protocol freeze date (the header `Frozen on` date, taken at 00:00Z), **and**
- no family holds a recorded passing decision.

"Independently specified" means a distinct `strategy_id`, a 7-slot family sheet, a distinct sheet content hash and distinct registered parameter-set hashes (baselines excluded). Until all three hold the state is WITHIN_BUDGET (keep researching) or PASSING_CANDIDATE (a family holds a recorded passing decision; this does not authorize live). A family's passing status is computed from G1-G5 (Pre-registered thresholds (v1.1.0) above) and recorded with a decision reference; a human may reject a candidate that passes but may never pass a candidate that fails (D032, D043). This wording conforms the section to D013 and is recorded as D030 (protocol v1.0.1, clarification only; see the Amendment log).

When the kill gate fires, the project stops adding complexity, keeps live execution disabled, classifies the artifact as research/journal infrastructure, and continues to log NO_TRADE outcomes. NO_TRADE is a valid outcome of the kill gate; a forced green light is not.

---

## §5 Parameter-registry linkage

> **Source:** `docs/configuration/CONFIGURATION.md` — sections "Parameter set identity", "Reproducibility contract", "Immutable frozen sets", "Storage model", "Experiment linkage", "Parameter search rules", "Python configuration conventions".

### Identity tuple — required on every run

Every backtest, paper signal, alert, approval, and live order plan carries the identity tuple:

```text
strategyVersion
parameterSetId
parameterSetHash
```

`parameterSetHash` is the deterministic hash of the canonical serialized parameter document — normalized numeric types and key ordering before hashing (per `docs/configuration/CONFIGURATION.md` §9 Python configuration conventions). A live order **must never** use an unregistered parameter set.

### Loader contract (Phase 1 deliverable; implementation deferred to Phase 3)

The Phase-1 deliverable is the **loader contract**, not the loader implementation:

```text
source-controlled JSON/YAML
        ↓
validated loader
        ↓
canonical normalized JSON
        ↓
DB parameter registry
```

- The DB record stores the exact normalized snapshot used by the run.
- The hash is computed over the canonical normalized JSON, never over the source file.
- Loader normalization rules: numeric type coercion (string-vs-int for whole numbers, exact decimal representation for fractional values), key ordering (alphabetical at each depth), whitespace stripping, no comments in the canonical form.

Phase 3 builds the actual loader; Phase 1 only specifies its contract.

### Immutability

Once a parameter set is referenced by a published backtest or a live-approved plan:

- the set is **never mutated**;
- any behavior change requires a new parameter set and a strategy-version bump;
- the old set is retained in the registry (referenced by its old `parameterSetId` and `parameterSetHash`) for audit.

### Experiment linkage tuple

Every experiment record carries:

```text
experimentId
strategyVersion
parameterSetHash
dataSnapshotId
codeVersion
costModelHash
```

A backtest report is not considered reproducible without all six. `costModelHash` is the hash of the cost snapshot from §2 (entry/exit/funding/slippage/spread fields); `dataSnapshotId` identifies the exact dataset snapshot used; `codeVersion` identifies the strategy/backtest engine code commit.

### Search discipline

- Automated sweeps are allowed **only inside ranges declared by research**.
- The agent does not invent a search space after seeing the result distribution.
- Results are grouped by parameter region, not by single best point.
- A narrow isolated optimum is a robustness warning, recorded as such in the experiment record and the journal.

### Parameter seed

Phase 1 ships **zero registered parameter sets** (correct: no parameter work exists yet). The first registered sets appear in Phase 4+, after family sheets are formally specified and a candidate family is selected for empirical exercise.

---

## §6 Regime, invalidation, expiry, and journal — by reference

> **Source:** `docs/research/TRADING_STRATEGY_RESEARCH.md` — setup lifecycle (informal definition, valid_until, price/structure invalidation, optional volatility invalidation, attribution timestamps); `docs/data/DATA_MODEL.md` §6 reporting joins.

This section is short by design. Regime classification, invalidation rules, expiry rules, and journal/attribution fields are owned by their respective canonical docs and are **referenced**, not duplicated, here.

### Setup lifecycle — required fields

Every emitted setup carries:

- **valid_until** — a timestamp or candle-close boundary beyond which the setup is no longer valid; expiry reasons are categorized (time, candle count, structure, volatility, external event).
- **invalidation** — a price or structure condition that, when met on a closed candle, cancels the setup. Invalidation is closed-candle only; an intrabar touch is not an invalidation. In the simulator this is the plan's own `CANDLE_CLOSE` rule with level `stop_loss_price`: at a strategy-bar close an unfilled plan is cancelled when the close is strictly beyond the level (LONG below, SHORT above). A fill during the bar comes first, and invalidation wins over expiry at the same close. This replaces the v1 simulator's close-versus-open bar heuristic (D052).
- **optional volatility invalidation** — when the strategy spec calls for one; never a `high ATR = news` inference without event data.
- **attribution timestamps** — the four canonical timestamps `SignalTime`, `ApproveTime`, `OrderTime`, `FillTime` from `docs/data/DATA_MODEL.md` §6 reporting joins.
- **simulated end states (v2.0.0)** — an entry ends exactly one way: filled, `EXPIRED`, `INVALIDATION_CANCEL`, `DAILY_STOP_CANCEL` or `PENDING_AT_DATA_END`; a filled position ends as SL, TP2 or `END_OF_DATA`. `END_OF_DATA` and `PENDING_AT_DATA_END` are reported separately and never booked as SL, TP or expiry.

### Regime classification — by reference

Regime classification (long / short / neutral / no-trade regimes) is owned by `docs/strategy/TRADING_STRATEGY_SPEC.md` §2 once that doc is frozen. Until then, regime tags are recorded in experiment records as `regime_tag` strings; the canonical mapping is amended in a future protocol version.

### Journal separation — by reference

The journal separates three reporting slices per `docs/data/DATA_MODEL.md` §6 reporting joins:

- **system performance** — all signals/plans emitted by the strategy engine, regardless of user action.
- **user-executed** — plans the user APPROVED and that became orders, with their fills and PnL.
- **opportunity (skipped/expired)** — plans that were SKIPPED_USER / SKIPPED_BUSY / EXPIRED / INVALIDATED, reported with MFE/MAE where measurable.

NO_TRADE outcomes (no setup emitted) are reported in a fourth slice, with reason category.

### Reference target summary

For convenience, the cross-reference targets in this section resolve to:

- `docs/research/TRADING_STRATEGY_RESEARCH.md` — sections "Setup lifecycle" and "Journal" (by title).
- `docs/data/DATA_MODEL.md` §6 — reporting joins and the four canonical attribution timestamps.
- `docs/strategy/TRADING_STRATEGY_SPEC.md` §2 — regime taxonomy (TBD until the SPEC is frozen).
- repo-root `AGENTS.md` Constraints — fail-closed semantics for invalid data/connection/account/risk.

---

## Appendix A — Status & freeze mechanics (informational)

> Not part of the frozen contract; included so the freeze and amendment procedure is discoverable from one place.

### Draft → Frozen

A version is frozen when **all three** are true:

1. The header in §0 reads `Status: FROZEN` and `Frozen on: YYYY-MM-DD`.
2. A row in `docs/DECISIONS.md` names the freeze version (e.g. `D029 — Research protocol v1.0.0 frozen on YYYY-MM-DD`) and references the commit hash.
3. The `docs/DOC_STATUS.md` index lists `docs/research/RESEARCH_PROTOCOL.md` under Stable/canonical and bumps its version line.

Until all three land, the doc is `DRAFT` in effect, regardless of what the header says. The research-gate reads the header `Protocol version` and requires a DECISIONS row containing `protocol vX.Y.Z frozen` and a DOC_STATUS index line containing that same version; an older version's row does not satisfy a newer header (D043).

### Amendment procedure

- **Clarification / wording** (no semantic change) → bump to `v1.0.x`. Header `Status: FROZEN` is preserved. A DECISIONS row records the clarification.
- **Semantic change** to dataset splits, cost model, execution simulation, or acceptance gates → bump a minor or major version per Semantic Versioning (precedents: `v1.1.0` minor, `v2.0.0` major, `v2.1.0` minor). A `Supersedes` line replaces the `none` line. A migration paragraph summarizes the change. A DECISIONS row records the amendment. A semantic change triggers a new strategy-version lineage per `docs/strategy/TRADING_STRATEGY_SPEC.md` §12.

### Living-draft firewall (operational)

`docs/research/TRADING_STRATEGY_RESEARCH.md` is the only place new candidate ideas and open questions are first recorded. The protocol doc is updated only via the amendment procedure above. When a future research-gate CI workflow is in place, the workflow reads the protocol `Status:` line, the corresponding DECISIONS row, and the DOC_STATUS entry on every PR; any disagreement (e.g. header says FROZEN but no DECISIONS row exists, or the header version differs from the DECISIONS row or DOC_STATUS line) fails the gate.

### Amendment log

- **v1.0.1 — 2026-09-29 — D030 (clarification).** Wording-only correction of the "Kill gate D013" firing rule to conform to D013 (fires only when at least three independently specified families were tested AND at least six calendar months elapsed since the freeze AND none holds a recorded passing decision); the earlier disjunctive shortfall list contradicted D013 and is removed. No dataset split, cost model, execution assumption, acceptance gate, threshold or numeric value changed. `Status`, `Frozen on` and `Supersedes` are unchanged.
- **v1.1.0 — 2026-09-30 — D043 (semantic).** Implements D032. Pre-registers numeric acceptance thresholds (G1-G5: trade floor, expectancy with bootstrap bound, Holm-Bonferroni correction over N = 25 variants per family, drawdown ceiling, single-use holdout), fixes the 40/40/20 split with four walk-forward Validation folds, adds the append-only `docs/research/holdout_consumed.json` marker, removes any human pass override, and aligns costs and execution to D036 (taker entry fee), D037 (mark-price protective triggers), D038 (`partial_fill_fraction` 1.0) and D039 (point-in-time research universe) with one canonical quantization order. The research-gate freeze step is now version-bound to the header. `Frozen on` is unchanged (the D013 clock is not restarted); `Amended on` and `Supersedes: v1.0.1` are added. The D030 kill-gate firing rule is untouched.
- **v2.0.0 - 2026-10-05 - D052 (semantic).** Execution simulation rebuilt for causality (Phase 14): a plan is active from bar N+1, fills need a one-tick trade-price trade-through at the live limit, SL and TP trigger on mark-price minutes, the TP1/TP2 ladder mirrors live, funding is charged at actual `fundingTime` instants, constraints are point-in-time, a simulated ledger and one R denominator are used, and `simulator_semantics_version` 2.0.0 joins the experiment identity. All earlier backtest evidence is void. Thresholds, splits, the D030 firing rule and the identity tuple are unchanged. `Frozen on` is unchanged (the D013 clock is not restarted); `Amended on` is 2026-10-05 and `Supersedes: v1.1.0`. The version pins in the gate code and tests are read from this header from now on.
- **v2.1.0 - 2026-10-07 - D060 (semantic).** Implements D057. G5 gains a floor of at least 30 closed trades in the holdout (counted as G1 counts them); fewer than 30 cannot pass G5 and consumes the holdout for that lineage; 30 is an eligibility floor, never an edge claim, and is never lowered after the freeze. `holdout_consumed.json` schema moves to `holdout-consumed/2` with a per-entry `protocol_version`. Nothing else changed and nothing is applied backwards (no holdout entry or kill-gate decision exists). `Frozen on` is unchanged (the D013 clock is not restarted); `Amended on` is 2026-10-07 and `Supersedes: v2.0.0`.
