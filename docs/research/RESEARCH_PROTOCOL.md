# Research Protocol (Frozen)

> **Protocol version:** v1.0.0
> **Status:** DRAFT
> **Frozen on:**
> **Supersedes:** none

## §0 Identity, status, and one-way flow

This document is the **frozen research contract** for the Binance Futures research/execution project. It restates methodology that is owned by other canonical documents (`docs/backtest/BACKTEST_SPEC.md`, `docs/configuration/CONFIGURATION.md`, `docs/data/DATA_MODEL.md`, `docs/research/TRADING_STRATEGY_RESEARCH.md`) so that an experimenter can read dataset splits, cost model, execution assumptions, and acceptance gates in one place before running any parameter work — but it does **not** duplicate the underlying methodology. Every section cites its owning doc by title.

**Status vocabulary is binary.** A section header line carries exactly one of:

- `Status: DRAFT` — the doc is editable; new content may be added or revised.
- `Status: FROZEN` — the doc is immutable for that version. The freeze is binding when **all three** witnesses agree: this header line, a `DECISIONS.md` row naming the freeze version, and the `DOC_STATUS.md` index entry. Any two without the third means `DRAFT` in effect, and the research-gate CI workflow enforces all three at `01-04`.

**Living-doc firewall (one-way flow).** `docs/research/TRADING_STRATEGY_RESEARCH.md` is the living draft for new ideas, candidate families, and open questions. The protocol doc copies methodology *out of* the living draft once. After the protocol is frozen, any new learning enters the protocol **only** via a versioned amendment:

- clarification or wording fix → bump to `v1.0.x` (semantics unchanged);
- semantic change to dataset splits, cost model, execution simulation, or acceptance gates → bump to `v1.1.0` or `v2.0.0` per Semantic Versioning; add a `Supersedes` line and a migration paragraph.

A semantic change to the protocol triggers a new strategy-version lineage downstream (see `docs/strategy/TRADING_STRATEGY_SPEC.md` §12 Strategy versioning). Living-draft edits never modify a frozen protocol section in place.

**Numeric-gate reservation (RSCH-01/unclassified).** Every numeric threshold in §1–§5 — sample sizes, split ratios, ATR multipliers, RR minima, expiry hours, cost assumptions, frequency targets — is **TBD until exercised on real data**. Where a default direction is required to make the doc readable, it is stated as a *range to explore* (e.g. "10–15 symbols research slice", "0.5% baseline risk rate"), never as a frozen fact. A numeric gate appearing in this protocol before real-data exercise is a flagged assumption, never a frozen value.

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

- **Development** — exploratory sweep space, feature engineering, structural hypothesis selection.
- **Validation** — out-of-sample check on parameter regions chosen during Development; never used to invent new regions.
- **Final holdout / forward test** — reserved; the **final holdout must not be used to choose parameters**. Its sole purpose is the one-time honest assessment of a candidate before live consideration.

### Walk-forward

Where practical — and especially when testing parameterized structure/ATR rules — use rolling windows:

```text
train → validate → roll forward
```

The rolling period must be **fixed before** any evaluation on a window; the choice of period itself counts as a methodology decision recorded in the parameter registry (see §5) and is not tuned per family. Walk-forward results are reported per window and aggregated; an aggregate "best point" without per-window evidence is not accepted.

### Universe discipline

- **Research universe:** 10–15 sufficiently liquid Binance USDⓈ-M symbols, declared per experiment record (§5).
- **Live V1 universe:** BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT (per `docs/00_PRODUCT_SCOPE.md`).
- The experiment report must show results **both** for the broader research slice and the live-5 slice. A strategy is not accepted solely because the broader universe rescues a weak live universe.

### Anti-overfitting rules R1–R6

Restated from `docs/research/TRADING_STRATEGY_RESEARCH.md` anti-overfitting rules. These are rules of the protocol; deviations require an amendment:

- **R1** — Parameter changes need a stated reason recorded against the experiment.
- **R2** — Prefer plateau behavior over point optimum; a narrow isolated optimum is a robustness warning.
- **R3** — Out-of-sample evidence is mandatory; in-sample goodness is not a substitute.
- **R4** — Costs are modeled from experiment #1, not retrofitted after a favorable result is observed.
- **R5** — No daily-PnL targeting; NO_TRADE is a valid and reportable outcome.
- **R6** — No optimization on skipped trades; skipped/expired plans remain part of the journal record.

### Specific value reservations

- Split ratios (e.g. 60/20/20 vs 70/15/15), walk-forward window length, and number of walk-forward windows are **ranges to explore**, not frozen facts. Their selection for an experiment is recorded in the experiment record (§5) and the parameter registry (§5).

---

## §2 Cost model

> **Source:** `docs/backtest/BACKTEST_SPEC.md` — sections "Fees and funding", "Limit-order simulation"; `docs/trading/RISK_MANAGEMENT.md` — quantization and realized-risk gate; `docs/research/TRADING_STRATEGY_RESEARCH.md` — funding and slippage discussion.

Every backtest/paper run **must expose** cost configuration. The minimum declared fields are:

### Required cost fields

| Field | Definition | Reference |
|---|---|---|
| `entry_fee` | Taker/maker fee applied at entry, basis points per side | exchange schedule, re-verified at implementation |
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
- Partial fills are modeled; partial-fill fraction must be declared per experiment.
- A retest/touch that does not fill is logged with the same attribution fields as a fill.

### Funding

Funding is applied to positions held through funding events. The funding rate applied is the Binance-published USDⓈ-M perpetual funding rate; for periods outside the public API window, self-collected historical funding rates are used (Phase 0 data foundation). Funding is signed per side per the documented convention and is part of the cost snapshot — never retrofitted.

### Quantization — floor-only, identical across modes

> **Source:** `docs/trading/RISK_MANAGEMENT.md` quantization rules; restated in `docs/AGENTS.md` Constraints (canonical).

The realized quantity is computed as:

1. Floor the raw quantity to the symbol's `stepSize` (Binance `exchangeInfo` — re-verified, never hard-coded).
2. Apply a realized-risk check against the intended risk budget (baseline 60% of intended — the exact percentage is **TBD per risk register** and may be tightened in live-mode).
3. Reject the order if the floored quantity falls below `minQty` or the notional falls below `minNotional`.
4. **NO_TRADE preferred over round-up.** Round-up silently inflates risk beyond the budget and is forbidden.

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

### Timeframe hierarchy

- **Decision timeframes:** 4H (regime/context) and 1H (setup). 15M is optional, used only for entry refinement where the candidate spec calls for it.
- **Execution simulation timeframe:** 1m. When 1m data is unavailable, the conservative deterministic assumption (see "Intrabar ambiguity" below) applies and is reported.

### Intrabar ambiguity — fixed before evaluation

When a 1H OHLC bar's high and low both touch stop and target inside the same bar:

1. Resolve with 1m data when available; the canonical tie-break is **fixed before any evaluation** (i.e. before the first run on the dataset).
2. Candidates for the fixed tie-break (any one, declared in the experiment record):
   - **Conservative adverse-first** — assume the stop fills first.
   - **Next-finer-timeframe** — defer to the 1m sequence.
   - **Mark ambiguous and segregate** — count the bar in a separate "ambiguous" bucket; never blend into win/loss.
3. When finer data is unavailable, use a conservative deterministic assumption and **report it** in the experiment record.

### Limit-order simulation — mandatory checklist

The backtest engine must model, per limit order:

- **touched vs filled** — the price was touched (wick) versus the order was filled at that price.
- **partial fill** — declared partial-fill fraction, applied before any TP/SL logic.
- **time-in-force / expiry** — limit orders expire per their declared validity; a re-quote after expiry is a new order, not a fill.
- **cancel-after-invalidation** — when a setup is invalidated, its unfilled limit order is canceled, not left to fill retroactively.
- **no retroactive fill after expiry** — once an order has expired, a later price touch is not a fill.

### Baselines

Every candidate is compared against:

- **no-trade** baseline (the null distribution), and
- at least one **simple baseline** — a buy/hold reference for spot-style setups or a simple trend filter without the proposed setup for swing setups.

The purpose is not to declare a winner; the purpose is to measure whether the added complexity contributes value beyond a simple comparator.

### NO_TRADE as a valid outcome

NO_TRADE is a first-class outcome reported alongside trades. The experiment record must include the count of NO_TRADE decisions and the reason category (regime filter, RR floor, conflict with open position, data unavailability, kill-gate trip).

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
6. **Operationally tolerable drawdown** — drawdown and loss streak are reported; the operational definition of "tolerable" is per-risk-register and is **TBD** until paper evidence exists.
7. **Reproducible** — the experiment record (§5) carries enough identifiers that another agent can re-run the exact same experiment and obtain byte-equivalent results.
8. **Distributional/interval uncertainty** — uncertainty is reported with distributional analysis (bootstrap intervals, resampled drawdowns), not a single expectancy number.
9. **No single-point dependence** — no critical conclusion rests on a single symbol, quarter, or isolated parameter point.
10. **Baseline-compared** — the candidate is compared against declared baselines (§3), not evaluated in isolation.

### Thresholds remain TBD

Exact numerical acceptance thresholds (expectancy magnitude, drawdown ceiling, loss-streak ceiling, minimum OOS consistency margin, minimum trade count by slice) remain `TBD` until the methodology is exercised on real data. The mechanism for setting these thresholds is:

- A `parameterSet` is run through Development.
- The family of candidate sets is run through Validation.
- After ≥3 independently specified families (see kill gate below) have produced Validation evidence, **then** and only then are candidate numerical thresholds proposed, recorded in `DECISIONS.md`, and added to a future protocol amendment (e.g. `v1.1.0`).

A numeric threshold appearing before this empirical base is a flagged assumption, never a frozen gate.

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

The kill gate fires if:

- fewer than three **independently specified** candidate families have completed backtest + out-of-sample evidence, **or**
- fewer than six months of research effort have been invested across those families, **or**
- any family fails the 10 acceptance gates materially.

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
- **invalidation** — a price or structure condition that, when met on a closed candle, cancels the setup. Invalidation is closed-candle only; an intrabar touch is not an invalidation.
- **optional volatility invalidation** — when the strategy spec calls for one; never a `high ATR = news` inference without event data.
- **attribution timestamps** — the four canonical timestamps `SignalTime`, `ApproveTime`, `OrderTime`, `FillTime` from `docs/data/DATA_MODEL.md` §6 reporting joins.

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
- `docs/AGENTS.md` Constraints — fail-closed semantics for invalid data/connection/account/risk.

---

## Appendix A — Status & freeze mechanics (informational)

> Not part of the frozen contract; included so the freeze and amendment procedure is discoverable from one place.

### Draft → Frozen

A version is frozen when **all three** are true:

1. The header in §0 reads `Status: FROZEN` and `Frozen on: YYYY-MM-DD`.
2. A row in `docs/DECISIONS.md` names the freeze version (e.g. `D029 — Research protocol v1.0.0 frozen on YYYY-MM-DD`) and references the commit hash.
3. The `docs/DOC_STATUS.md` index lists `docs/research/RESEARCH_PROTOCOL.md` under Stable/canonical and bumps its version line.

Until all three land, the doc is `DRAFT` in effect, regardless of what the header says.

### Amendment procedure

- **Clarification / wording** (no semantic change) → bump to `v1.0.x`. Header `Status: FROZEN` is preserved. A DECISIONS row records the clarification.
- **Semantic change** to dataset splits, cost model, execution simulation, or acceptance gates → bump to `v1.1.0` (minor) or `v2.0.0` (major). A `Supersedes` line replaces the `none` line. A migration paragraph summarizes the change. A DECISIONS row records the amendment. A semantic change triggers a new strategy-version lineage per `docs/strategy/TRADING_STRATEGY_SPEC.md` §12.

### Living-draft firewall (operational)

`docs/research/TRADING_STRATEGY_RESEARCH.md` is the only place new candidate ideas and open questions are first recorded. The protocol doc is updated only via the amendment procedure above. When a future research-gate CI workflow is in place, the workflow reads the protocol `Status:` line, the corresponding DECISIONS row, and the DOC_STATUS entry on every PR; any disagreement (e.g. header says FROZEN but no DECISIONS row exists) fails the gate.
