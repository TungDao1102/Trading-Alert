# Backtest Specification

## 1. Purpose

Estimate how a deterministic strategy would have behaved under explicit data, execution, and cost assumptions.

A backtest is evidence about the tested assumptions, not proof of future performance.

## 2. Data hierarchy

Preferred:

- 4H + 1H for strategy.
- 1M for execution simulation: one continuous, sorted, non-overlapping series per symbol, trade-price klines for entries and mark-price klines for exits (protocol v2.0.0, D052). Missing minutes are never padded.
- Historical funding at the symbol's actual `fundingTime` instants (section 5).
- Point-in-time symbol constraints (tick, step, minimum quantity, minimum notional) selected by `observed_at` at or before the bar close; no wall-clock input anywhere in the simulator.
- Self-collected OI for periods outside Binance's historical API window.

## 3. Candle-close rule

Strategy decisions must use information available by the source candle close.

No future candle data, future swing confirmation, or future intrabar outcome may leak into historical decisions.

A plan created at the close of strategy bar N is active from bar N+1. The signal bar's own range is never examined for a fill or an exit, so `entry_time` is after the signal close and `exit_time` is not before `entry_time`; a shared trade-record validator raises on any violation.

## 4. Intrabar ambiguity

Exits are evaluated on 1m **mark-price** klines (D037); entries on 1m trade-price klines.

If one 1m mark minute touches both the stop and a target, the stop wins (`STOP_FIRST`, recorded in the experiment record). On the fill minute only the stop can trigger. A stop gap books the adverse of the trigger price and the mark-minute open and sets a counted flag. Exit prices are the trigger price with the cost-model slippage terms; there is no price improvement.

If 1m mark coverage is missing for part of a strategy bar, the remainder of that bar is resolved once at the strategy-bar close from the bar range, stop-first, with a counted `fallback_applied` flag and a coverage note. The fallback applies to exits only: a missing trade minute never produces a fill.

While a position is open the simulator walks the mark minutes in order. When two consecutive walked minutes, or the minute before the fill minute and the first walked minute, are more than one minute apart, or when a position closed `END_OF_DATA` has whole minutes missing before the data end, the missing minutes carry no mark price, so no stop or target is evaluated minute by minute for them. This applies to minutes outside any strategy-bar fallback, for example an hour in which the symbol has no strategy bar. The trade's `coverage_note` records the first and last missing minute. This is annotation only: it does not set `fallback_applied`, changes no price, time or count, and the report lists the note under its intrabar coverage notes.

Exit ladder: TP1 is a reduce-only partial of half the filled quantity (`TP1_QUANTITY_FRACTION` 0.5, a code constant covered by `simulator_semantics_version`), TP2 closes the remainder, the stop is unchanged after TP1. A position is carried until SL, TP2 or data end; there is no time stop. A position open at data end closes at the last mark close as `END_OF_DATA`.

## 5. Fees and funding

All backtests must expose cost configuration.

Minimum:

- entry fee,
- exit fee,
- funding treatment,
- slippage,
- spread/fill assumptions.

Funding (D052): `funding_pnl = -sign(position) x open_quantity x markPrice(fundingTime) x fundingRate` at every actual `fundingTime` with `entry_time <= fundingTime < exit_time`; sign is +1 LONG and -1 SHORT, so a LONG pays when the rate is positive. `open_quantity` is the quantity open at that instant (the post-TP1 remainder after a TP1). Funding is part of net PnL and R and never of sizing. Its convention (`funding_convention` `MARK_NOTIONAL_SIGNED_V1`) is part of `cost_model_hash`. A holding window needs funding coverage (consecutive rows at most 8 h or 4 h per symbol plus 60 s apart, window inside the loaded UTC days) or the run fails closed unless the caller passes an allowed gap, which is recorded on the output. The same rule and the funding FAQ fact are in `docs/trading/RISK_MANAGEMENT.md` section 3 and `docs/SOURCES.md`.

## 6. Limit-order simulation

Backtest must model:

- price touched vs actual fill: the limit is the tick-snapped live order price; a LONG fills only when a trade-price 1m low is at or below `limit - tick`, a SHORT only when a 1m high is at or above `limit + tick` (trade-through of at least one tick). The fill price is the limit, the fill time is the close of the deciding minute. A touch without trade-through is counted per plan and is never terminal (`TOUCH_NO_FILL` is not an outcome),
- partial fill assumption (`partial_fill_fraction` 1.0 in canonical runs, D038),
- time-in-force / expiry: a resting entry expires when the close of a simulated minute is after `expiry_utc`; the simulated minute, never a clock, is the reference (closes Phase 6 gap G3),
- canceled entry after invalidation: the plan's own `CANDLE_CLOSE` rule, level `stop_loss_price`, evaluated at strategy-bar closes. A close strictly beyond the level cancels an unfilled plan (`INVALIDATION_CANCEL`). The order inside one bar is fill first, invalidation second, expiry last, so invalidation wins when the bar closes exactly at expiry. **This replaces the v1 rule** that cancelled when the entry bar's close was below its open (LONG) or above it (SHORT), a bar-direction heuristic with no basis in the plan (D-05, D-35),
- no retroactive fill after expiry,
- one plan or position per symbol: a re-signal meanwhile is skipped and counted as a conflict with an open position,
- DAILY_STOP cancels resting entries (`DAILY_STOP_CANCEL`) and leaves the protective stops of open positions in place (D033); resting entries count toward the portfolio gates (D035),
- data end: an open position closes at the last mark close as `END_OF_DATA`, a resting plan is `PENDING_AT_DATA_END` (never `EXPIRED`); both are kept as records, counted and reported separately and excluded from pooled R and the closed-trade floor.

Several symbols run in sorted (time, symbol) order; output, tie order and hashes are byte-stable, and appending later bars cannot change earlier trades (prefix invariance, END_OF_DATA and PENDING_AT_DATA_END records excepted).

## 7. Dataset splits

Minimum:

```text
Development
    ↓
Validation
    ↓
Final holdout / forward test
```

The final holdout must not be used to choose parameters.

Fixed proportions (40% Development, 40% Validation as four consecutive walk-forward test folds, last 20% final holdout, single-use) are pre-registered in `docs/research/RESEARCH_PROTOCOL.md` v2.0.0 §1 and §4 per D032 and D043.

## 8. Walk-forward

Where practical, use rolling windows:

```text
train → validate → roll forward
```

This is especially important when testing parameterized structure/ATR rules.

## 9. Baselines

Every candidate strategy should be compared with at least one simple baseline, e.g.:

- no-trade,
- buy/hold for spot-style reference when appropriate,
- simple trend filter without the proposed setup.

The purpose is not to prove a strategy “wins”; it is to understand whether the added complexity contributes measurable value.


## 10. Statistical power and uncertainty

Backtest sample size must be treated as a limitation, not hidden behind a single expectancy number.

Required reporting:

- trade count overall and by symbol/quarter/regime;
- mean, median, standard deviation of R;
- bootstrap interval for expectancy;
- drawdown distribution under resampling;
- stability across time and symbols.

If trade returns are plausibly dependent or clustered, use a block/bootstrap method rather than assuming independent observations.

As a diagnostic, for approximately independent trade outcomes with standard deviation `σ`, the standard error of the mean is approximately:

```text
SE ≈ σ / sqrt(n)
```

For example, if `σ ≈ 1.2R`, then `n = 500` gives `SE ≈ 0.054R`, so a 95% interval is still roughly ±0.11R before accounting for dependence. This illustrates why an observed expectancy such as +0.15R may remain statistically uncertain even after hundreds of trades.

This is a methodology warning, not a claim that a fixed sample size proves or disproves a strategy.

## 10.1 Research universe vs live universe

To increase research sample size without changing the intended live product:

- research evaluates the point-in-time universe of D039 (top 10–15 USDT perpetuals by volume at the dataset start date, delisted symbols included), declared in the manifest `docs/research/universe/research-universe-v1.toml` and frozen and hashed before evaluation;
- live V1 may remain limited to the declared 5-symbol universe;
- the research report must show results both for the broader research universe and the intended live universe.

A strategy must not be accepted solely because the broader universe rescues a weak live universe.

## 11. Experiment record

Each run stores:

- experiment ID,
- strategy version,
- dataset range,
- symbol universe,
- timeframe,
- all parameters,
- cost assumptions,
- results,
- code/data version,
- notes.

The record carries typed, validated fields (D-22): `no_trade_counts` by reason, `intrabar_tie_break`, `timeframe` and `context_timeframe`, `parameter_values` and `cost_values` (canonical text, the cost values hashing to `cost_model_hash` and carrying `funding_convention`), `simulator_semantics_version`, `code_commit` and `code_dirty` (`code_version` is the commit, plus `-dirty`), `fallback_count`, `end_of_data_count`, `strategy_window_bars` and `context_window_bars`, `allowed_gaps` and the split role with its start and end. A record missing or violating any of them cannot be constructed. The simulator semantics version and the split fields are part of the experiment identity, so a record from the old simulator can never be compared with a new one.

The canonical six-field identity tuple required on every experiment record is defined in `docs/research/RESEARCH_PROTOCOL.md` §5 and `docs/configuration/CONFIGURATION.md` §7 (`experimentId`, `strategyVersion`, `parameterSetHash`, `dataSnapshotId`, `codeVersion`, `costModelHash`); the `parameterSetId` runtime identifier is required alongside `parameterSetHash` per the same source. An experiment record missing any of these six fields does not satisfy this section.

## 12. Acceptance gates

A strategy may proceed only when:

1. rules are deterministic;
2. there is no material look-ahead;
3. costs are modeled;
4. results are not confined to one symbol/session;
5. out-of-sample behavior is not materially inconsistent without an understood reason;
6. drawdown and loss streak are operationally tolerable;
7. results are reproducible;
8. uncertainty is reported with distributional/interval analysis rather than a single point estimate;
9. no critical conclusion depends on a single symbol, quarter, or isolated parameter point;
10. candidate has been compared against declared baselines.

The numerical acceptance thresholds (trade floor, expectancy bound, multiple-testing correction, drawdown ceiling, single-use holdout) are pre-registered in `docs/research/RESEARCH_PROTOCOL.md` v2.0.0 §4 per D032 and D043.


## 13. Research implementation

Exploratory backtests may use pandas/Polars/NumPy/VectorBT, but the final validation path must execute the canonical project strategy/backtest engine. A library-specific vectorized result is not sufficient evidence when execution semantics such as partial fill, expiry, quantization, or intrabar resolution differ.
