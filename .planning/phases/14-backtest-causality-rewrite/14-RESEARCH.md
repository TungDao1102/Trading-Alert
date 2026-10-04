# Phase 14: Backtest Simulator Causality Rewrite - Research

**Researched:** 2026-10-04
**Domain:** deterministic event-driven futures backtest (pure Python, Decimal-only), research-protocol amendment, evidence-chain (normalizer / report / experiment record) migration
**Confidence:** HIGH for everything read in-repo this session; MEDIUM for external Binance facts (one official FAQ page fetched, API pages were never readable in this project, see `docs/SOURCES.md`)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Plan and position lifecycle (F-120, F-901, G3)**
- **D-01:** The simulator becomes an event loop over time, not a per-bar function. A plan created at the close of strategy bar N is active from bar N+1. Each later bar checks the entry until `trade_plan.expiry_utc`; an entry that has not filled by expiry ends as `EXPIRED`. The signal bar's own range is never examined for the fill. — **Reversibility:** one-way — changes every trade record, every golden fixture and the meaning of all earlier experiment hashes; the DECISIONS entry (D-02) pins it.
- **D-02:** Record the lifecycle as a DECISIONS entry and amend the research protocol for it (audit F-901 names protocol v2.0.0). v1.1.0 is frozen and is not edited in place; the planner follows the D032/D043 amendment procedure, checks the freeze-step version binding, and picks the version number that procedure requires. Add `simulator_semantics_version` ("2.0.0") to the experiment identity so a record produced by the old simulator can never be compared with a new one.
- **D-03:** **All earlier backtest evidence is void.** The DECISIONS entry says so explicitly, BKTS-01 is re-verified against the new simulator, and the planner checks `docs/research/` and the experiment store for any record or kill-gate decision that cited old results and marks it void (no silent deletion).
- **D-04:** G3 fix: entry expiry is judged against the **simulated bar time** (the bar being processed), never the fixture's single `now_utc`. The `_entry_now_utc = now_utc` shortcut is removed. A multi-bar test must show one limit entry that fills before `signal_expiry_hours` and one that expires after it.
- **D-05:** Invalidation stays closed-candle only (protocol glossary). On each post-signal bar the fill is evaluated first, using that bar's 1m data; invalidation is evaluated at the bar close only if the entry did not fill during the bar. The planner reconciles the existing close-versus-open rule with `docs/backtest/BACKTEST_SPEC.md` and records any change.
- **D-06:** A position is carried until SL, TP2 or data end. There is no time stop unless the spec or live code already has one (the planner checks `docs/strategy/TRADING_STRATEGY_SPEC.md`, `docs/trading/EXECUTION_SPEC.md` and `src/execution/`; if none exists it does not invent one). A position still open when the data ends is closed at the last mark price with `exit_kind = END_OF_DATA`, flagged, counted and reported separately, never booked as SL or TP.

**Fill rule (F-902)**
- **D-07:** The simulated limit price is the live order price, the zone mid `entry_ref` (Phase 12 D-03 note keeps the mid as the price the order is placed at). A LONG fills only when a trade-priced 1m low is at or below `entry_ref - tick`; a SHORT only when a 1m high is at or above `entry_ref + tick` (trade-through of at least one tick). A bar that only touches the limit is `TOUCH_NO_FILL`. Fill price is the limit price (conservative; a gap through the limit does not get price improvement). The tick comes from the point-in-time constraint snapshot, never a constant.
- **D-08:** Entry detection uses **trade-price 1m klines**; fill time is the close of the deciding 1m bar. The same 1m bar may also touch SL or TP; that case is resolved by the tie-break in D-12, never by order of code paths.
- **D-09:** `partial_fill_fraction` stays 1.0 for canonical runs (D038); partial and missed fills are a separate sensitivity study and stay supported by the existing cost-model field.

**Exits: mark-price triggers and the TP ladder (D037, F-102)**
- **D-10:** SL and TP triggers are evaluated on **mark-price 1m klines** (D037, protocol line 169). Entry stays on trade-price klines. The rule for a trigger touch is the same as the protocol's existing intrabar rule, applied to mark series. Exit price is the trigger price with the Phase 12 slippage terms (SL exit uses `exit_slippage_rate`, TP uses `expected_slippage`); no price improvement.
- **D-11:** The simulator **mirrors the live exit policy exactly** (F-102 option A): TP1 as a reduce-only partial and TP2 as the closing order (`docs/trading/EXECUTION_SPEC.md` lines ~81-82, `src/core/planner.py` `take_profit_json`). The TP1 quantity split, and what happens to the stop after TP1, are read from the live code and spec, not invented. If live has no explicit split or post-TP1 stop rule, that is a gap the planner raises as a checkpoint decision before writing the simulator (live and backtest must agree; fixing live is not this phase). Record the chosen policy in DECISIONS.
- **D-12:** Ambiguity tie-break stays conservative and explicit: if SL and a TP are both touched inside one 1m mark bar, SL wins (stop-first). Missing 1m coverage for a bar falls back to the strategy-bar range with stop-first, sets `fallback_applied`, and is counted in the report. Fallback is for ambiguous or missing bars only, never the default path. The tie-break name goes into the experiment record (BKTS-04).
- **D-13:** The simulator reads one **continuous, sorted 1m series per symbol** (trade and mark) instead of the per-signal-bar `intrabar_1m_map`. The planner defines the new case-input shape, extends the Phase 13 `src/data/case_input.py` builder to emit it, and validates monotonic time, no overlap and no duplicates on load. The dataset identity hash (Phase 13 D-18) continues to cover every input file.

**Funding (F-905, F-021)**
- **D-14:** Sign convention, documented in RISK_MANAGEMENT or the backtest spec: `funding_pnl = -sign(position) x quantity x markPrice(fundingTime) x fundingRate`, where `sign` is +1 LONG, -1 SHORT, so a LONG with positive funding pays. It applies for every **actual** `fundingTime` in the funding history (no fixed 8 h grid, intervals can differ per symbol) at which the position is open: `entry_time <= fundingTime < exit_time`. Funding is included in net PnL and R, never in sizing. Reversibility: costly.
- **D-15:** `markPrice(fundingTime)` comes from the funding history row; when the row's mark price is empty (Phase 13 D-23 adapter fix) it falls back to the mark kline at that minute. Funding history that does not cover a holding window **fails closed** (raises a project exception) unless the caller passes an explicit allow-gaps list that is recorded on the output (same rule as Phase 13 D-19).
- **D-16:** Funding data identity and the sign-convention version join the `cost_model_hash` inputs (audit F-905), so a funding change changes the experiment identity. The planner decides the minimal hashing change under the Phase 12 D-15 canonical-numeric rule and records it with the regeneration inventory.

**Point-in-time state and the portfolio ledger (F-305)**
- **D-17:** Historical mode selects versioned symbol metadata (tick, step, min notional, filters) by `observed_at <= bar close`. The wall-clock TTL stays for live and is not applied in the backtest. No wall-clock input anywhere in the simulator.
- **D-18:** The simulator carries a **simulated ledger** through the loop: equity (starts from `account_state`, updated by realized PnL including fees, slippage and funding), open positions, resting entries and daily-loss state. Order inside one timestamp: first advance every active plan and position over the elapsed bar and book exits and fills, then update the ledger, then evaluate new signals at the bar close with the updated ledger. Resting entries count toward portfolio gates, matching D035 (available margin includes resting entries). The daily-loss day boundary follows D033; the planner locates it and does not redefine it.
- **D-19:** A case can contain several symbols. The loop is deterministic across symbols (sorted by time, then symbol). Result order, tie order and hashing are byte-stable.

**R denominator, regime, experiment record (F-204, F-123, F-118, BKTS-04)**
- **D-20:** One R denominator for backtest and live: the realized risk persisted at sizing (Phase 12 `SizedResult.realized_risk`, the worst-case adverse-edge figure), scaled by `filled_quantity / planned_quantity`. One function computes it, used by every normalizer (`normalize_backtest`, `src/analytics/live_outcomes.py`, excursion). A parity test feeds identical trades through both paths. The planner picks the single field name and removes any competing denominator.
- **D-21:** The signal's regime is carried onto `TradeRecord` and emitted as a report slice (F-123). The plateau claim is not made here: parameter-plateau and sweep runners belong to BKTS-03, which stays Pending; this phase must not state or imply plateau evidence.
- **D-22:** `ExperimentRecord` gets typed, validated fields (F-118) instead of free-form `result_summary_json` contents: NO_TRADE counts by reason, the intrabar tie-break, timeframe, full parameters and costs, `simulator_semantics_version`, a verifiable code version (git commit and dirty flag), fallback count, `END_OF_DATA` count, and split role and boundaries (F-904 identity part only; the holdout-once enforcement stays in Phase 26). Validation is in `__post_init__`; an invalid record cannot be constructed. Reversibility: costly (record hash inputs change; included in the regeneration inventory).

**Trade-record invariants and verification (F-804, F-602, F-805, F-608)**
- **D-23:** A shared trade-record validator asserts, on every trade, `entry_time > signal_close` and `exit_time >= entry_time` (plus `exit_time` inside the data window and filled quantity <= planned). It raises, never warns. It runs inside the simulator and again at every normalizer boundary. An integration test drives simulator -> `normalize_backtest` -> excursion.
- **D-24:** Every golden case has a **hand-derived expected output** in a committed sidecar (`expected.json` plus a derivation note) that is not produced by the code under test. The fixture generator never places 1m data inside the signal bar; 1m data covers bars N+1 onward. Required cases include: the signal bar's own range touches SL or TP and no fill happens on that bar; trade-through versus touch-only; fill then hold across several bars to SL, to TP1 then TP2; expiry before fill; both-touched tie-break; gap through the limit; funding paid and received, including a position opened between two funding times; ledger effects (a loss that blocks the next signal via daily loss); END_OF_DATA; missing-1m fallback; a nonzero-cost parity fixture.
- **D-25:** Existing Phase 5/6 fixtures that are not rebuilt are relabeled **regression snapshots** (F-608), unused expected files are removed or fixed, and one DECISIONS entry lists every fixture, pin and hash that moved and why, in the style of D048. Parameter sets are not edited (F-810); a new tunable would mean a new versioned set, and none is planned.
- **D-26:** Determinism stays strict: Decimal arithmetic via `src/core/_decimal.py`, no float, no wall-clock, sorted iteration, byte-identical output on rerun, prefix-invariance (appending later bars cannot change earlier trades). `src/backtest/` stays Polars-free (Phase 13 D-22).

### Claude's Discretion
- Module split of the rewritten simulator (the current `simulator.py` is ~1,070 lines; separate lifecycle, ledger, funding and validator modules are welcome) and all internal names, provided public entry points keep working or are updated everywhere.
- Exact layout of the new case-input schema and fixture folder names, subject to D-13 and D-24.
- The field name for the shared R denominator and the validator's exception type.

### Deferred Ideas (OUT OF SCOPE)
- Parameter-plateau analysis and sweep runner: BKTS-03 (still Pending).
- Holdout-once enforcement code and split-date amendment enforcement: Phase 26 (F-960); this phase only adds the typed record fields (D-22).
- Trend-pullback geometry, confirmed pivots, minimum stop: Phase 15 (F-301).
- Maker (post-only) entry study and partial-fill sensitivity runs: separate sensitivity work under D038, not canonical.
- Fixing live exit policy if live and spec disagree on the TP ladder: raised as a checkpoint in planning (D-11), changed only by an explicit decision.

None of the pending todos matched this phase.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BKTS-01 | Backtest simulator resolves intrabar SL/TP ordering with 1m data, models limit fills/partials/expiry/invalidation, and applies fees/funding/slippage before any selection decision (REQUIREMENTS.md:45) | Sections "Cross-bar lifecycle", "Fill rule", "Exit engine", "Funding"; currently marked Complete by Phase 6 but declared void by D-03, must be re-verified |
| BKTS-02 | Every experiment is reproducible from dataset + strategy + parameter set + cost + execution versions and is compared against no-trade and simple-trend baselines (REQUIREMENTS.md:46) | "Experiment identity chain" (simulator_semantics_version, funding_convention, dataset_id), reproduce/verify migration, baselines run through the new engine |
| DOMN-03 | Strategy correctness is enforced by golden fixtures plus no-lookahead, prefix-invariance, candle-close-timing, and boundary suites (REQUIREMENTS.md:27) | Existing suites test `strategy.evaluate` only (audit F-602); this phase adds simulator-level no-lookahead and prefix-invariance suites and hand-derived goldens |
| BKTS-04 | Every experiment record carries the fields the research protocol requires, incl. NO_TRADE counts with reasons, intrabar tie-break, timeframe, full parameters and costs, verifiable code version (REQUIREMENTS.md:48; Pending, owned by Phase 14) | "ExperimentRecord typed fields" with the CI tripwire naming trap |
</phase_requirements>

## Summary

The existing simulator (`src/backtest/simulator.py`, 1,070 lines) is a per-signal-bar function: it evaluates the strategy on closed bar N, then fills, invalidates and exits the plan inside that same bar using the 1m candles of bar N, with portfolio inputs frozen for the whole run. The rewrite is an event loop over time with four moving parts that must be separated so they can be tested by hand: (1) a strategy front-end that only produces plans at bar closes, (2) a lifecycle engine that walks continuous 1m series for resting entries and open positions, (3) a simulated ledger (equity, positions, resting entries, UTC-day loss), and (4) validators/normalizers that raise on temporal violations. Almost everything the decisions need already exists as pure code (risk pipeline, cost producer, tick/step quantizers in `src/execution/placement.py`, canonical hashing); what is missing is a bounded-memory data contract, a protocol amendment, and answers to a handful of gaps listed under "Open questions needing user checkpoint".

Four findings change the plan and need user attention before the simulator is written: **(a)** live has a TP1/TP2 ladder with an unchanged stop, but the TP1 quantity fraction has no producer anywhere in `src/` or `params/` (only tests set 0.5), so D-11's "read it from live" is silent and is a mandatory checkpoint; **(b)** D-20's premise that `realized_risk` is "persisted at sizing" is false: no DB column or store holds it, and live R today divides by `plan.risk_budget`; **(c)** a naive port is computationally infeasible: `strategy.evaluate` recomputes every indicator over the whole prefix each bar (measured 16 ms at 250 bars, 99 ms at 2,000 bars), and 24 months of 1m data for 12 symbols cannot live in the current dict-of-rows case-input (about 38 GB of dicts), so a windowed strategy evaluation and a lazy `MinuteSource` contract are required; **(d)** point-in-time metadata rows can only start at the first refresh date, so `observed_at <= bar close` yields no row for almost the whole 24-month history unless a documented back-fill rule is chosen.

**Primary recommendation:** Build tracer-first around a decoupled lifecycle engine fed by hand-built `TradePlan` objects and in-memory minute series (so every golden case is derivable by hand and fast), then layer the strategy front-end, ledger, funding, R-denominator, experiment-record and protocol-amendment work on top; resolve the checkpoint list in plan 14-01 before any simulator code is written.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Plan creation at bar close (strategy.evaluate, planner.plan) | Pure core (`src/core`) | — | unchanged; simulator only calls it with a bounded trailing window |
| Resting-entry / position lifecycle, fills, exits, TP ladder | Pure backtest domain (`src/backtest`) | — | importable functions so Phase 16 paper can reuse them (CONTEXT code_context) |
| Simulated ledger, daily-loss day roll, portfolio projection | Pure backtest domain | `src/risk` (unchanged gates) | ledger feeds `evaluate_risk` inputs each time (D-18) |
| Continuous 1m trade/mark series, funding rows, metadata history | Adapter/data (`src/data`, Polars allowed) | `src/backtest` defines the `MinuteSource` protocol | Polars-free domain (D-26, Phase 13 D-22); lazy reads bound memory |
| Funding PnL and sign convention | Pure backtest domain | docs (RISK_MANAGEMENT / BACKTEST_SPEC) | D-14 |
| Shared R denominator function | Pure risk/analytics (`src/risk` new helper, used by `src/analytics`) | `src/backtest` | one function, every normalizer calls it (D-20) |
| Trade-record validator | Pure backtest domain | called again at `src/analytics` boundary | D-23 |
| Experiment identity, typed ExperimentRecord, code version lookup | `src/backtest/experiment.py` (pure validation) | adapter for `git` lookup | git subprocess is I/O, keep it outside the pure package |
| Protocol amendment, DECISIONS row, DOC_STATUS, gate pins | Docs + `scripts/decision_alignment` + tests | `.github/workflows/research-gate.yml` | D032/D043 version binding |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib (`decimal`, `dataclasses`, `datetime`, `bisect`, `heapq`) | Python 3.13.15 [VERIFIED: `uv run python --version` this session] | all simulator arithmetic and ordering | `src/backtest` is stdlib + Decimal only (src/backtest/__init__.py docstring: "this package imports NOTHING from Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic") |
| `src/core/_decimal.py` helpers `_add/_sub/_mul/_div/_q` | in-repo | pinned prec-28 Decimal arithmetic | `_PREC = 28` [VERIFIED: src/core/_decimal.py:20] |
| `src/risk` (`evaluate_risk`, `size_and_quantize`, `check_portfolio`, `resolve_absolute_thresholds`) | in-repo | sizing, cost guards, portfolio gates, reused unchanged (CONTEXT) | same function in backtest/paper/live |
| `src/execution/placement.py` pure helpers (`derive_limit_price`, `quantize_price`, `entry_limit_rounding`, `size_protectives_to_filled_qty`) | in-repo | the live limit price, tick snapping and TP1 quantity split | `src/execution/__init__.py` imports only `.order_ids`; placement.py is stdlib + `src.core._decimal` + `src.risk.types` [VERIFIED: placement.py:1-40] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Polars | 1.44.2 [VERIFIED: `uv run python -c "import polars"` this session] | adapter-side lazy Parquet reads for the `MinuteSource` implementation | only in `src/data/`, never imported by `src/backtest` |
| DuckDB | 1.5.5 [VERIFIED: same command] | already used by coverage/gap code | no new use needed |
| pytest | in repo dev extra | tests | `asyncio_mode = "auto"`, `addopts = "-q"` [VERIFIED: pyproject.toml pytest section] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Lazy `MinuteSource` protocol | Keep a dict-of-rows `intrabar_1m_map`-style case input | dict rows for 24 months x 12 symbols x trade+mark is about 38 GB (estimate below); not viable |
| Windowed strategy evaluation | Full-prefix evaluate each bar (current behavior) | about 25 hours of pure evaluate per run (table in Pitfall 1); also one gap anywhere in 2 years poisons all later features (`compute_features` marks every feature at and after the first gap GAP_IN_SOURCE, src/core/features.py:391-405) |
| Incremental feature series in `src/core/features.py` | Window constant in simulator | exact-equivalence refactor, but touches the file Phase 15 rewrites (confirmed pivots); defer |

**Installation:** none. No new external packages are introduced.

**Version verification:** no new packages to verify; installed versions above were read from the local environment. 

## Package Legitimacy Audit

No external packages are installed by this phase. All recommended code is stdlib or in-repo.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| (none) | — | — | — | — | — | Not applicable |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
 case input (fixtures: JSON rows | real runs: Parquet adapter)
        |
        v
 +-----------------------+   strategy bars (1h) + context (4h) per symbol, validated sorted
 | load + validate       |   MinuteSource(trade, mark) per symbol: monotonic, no overlap/dup
 | (series.py, adapter)  |   funding rows per symbol, constraint history per symbol, cost model
 +-----------+-----------+
             |
             v
   global clock = union of 1h bar closes, sorted by (time, symbol)           <-- D-19
             |
   for each timestamp T (strategy-bar close):
     1) ADVANCE active entities over (prev_T, T] on 1m data (minute by minute only while
        something is active; jump straight to T otherwise)
          resting entry:  trade-through check (trade 1m) -> FILL (entry_time = 1m close)
                          expiry (sim time) -> EXPIRED ; D033 DAILY_STOP -> cancel resting
          open position:  mark 1m: SL / TP1 / TP2 with stop-first tie-break
                          funding events (fundingTime in window) booked at their instants
          every booked event -> LEDGER (equity, open_risk, UTC-day loss)
     2) at T: invalidation (closed candle) for still-unfilled plans
     3) at T: for each symbol: strategy.evaluate(window) -> planner.plan -> evaluate_risk(
          ledger equity, ledger positions + resting entries, ledger daily loss, PIT constraints)
          -> NO_TRADE counter | REJECT record | new resting entry (active from next bar)
   end of data: open positions -> END_OF_DATA at last mark price; resting -> PENDING_AT_DATA_END
             |
             v
   TradeRecord list (+ run summary: no_trade counts, fallback count, END_OF_DATA count, tie-break,
   allowed gaps, semantics version) -> validate_trade_record (raises) -> normalize_backtest
   -> excursion / report / ExperimentRecord (typed)
```

### Recommended Project Structure
```
src/backtest/
├── semantics.py     # SIMULATOR_SEMANTICS_VERSION, TP1_QUANTITY_FRACTION, TIE_BREAK name, FUNDING_CONVENTION
├── series.py        # MinuteSource Protocol, ListMinuteSource, series validation (D-13)
├── entry.py         # resting-entry state machine: trade-through, tick snap, expiry, invalidation
├── exits.py         # mark-price walk, TP1/TP2 ladder, tie-break, fallback, END_OF_DATA
├── funding.py       # funding schedule, sign convention, coverage check, mark fallback
├── ledger.py        # equity, positions, resting entries, UTC-day loss, projection to OpenPosition
├── validator.py     # validate_trade_record + TradeRecordInvariantError
├── costs.py         # + funding_convention key (presence-driven), per-leg cost booking
├── simulator.py     # run(), orchestration only; keep `evaluate_risk` imported here (tests patch it)
├── experiment.py    # typed ExperimentRecord, assemble(run_summary=...), reproduce/verify
└── report.py        # closed-trade counting, regime slice, plateau suppressed
src/data/case_input.py   # + trade_bars_1m provider, multi-symbol, funding per symbol, metadata history
src/risk/realized_risk.py (name is discretion)  # the one R-denominator function
tests/fixtures/phase14/<case>/{input.json,expected.json}  + DERIVATIONS.md
```

### Pattern 1: Lifecycle engine decoupled from the strategy front-end
**What:** the engine takes `(TradePlan, sized quantity, constraint row, MinuteSource views, funding rows, cost model)` and returns state transitions. A hand-built `TradePlan` is constructible directly (frozen dataclass, validation ends at non-empty strings and Decimal types, src/domain/trade_plan.py `__post_init__`, lines 76-130).
**When to use:** all golden cases except one or two end-to-end ones. The strategy needs 200+ warm-up bars so each end-to-end run costs seconds (the existing 6 backtest-related test files take about 170 s locally, measured), and Phase 15 will change plan geometry, which would invalidate any hand-derived number that depends on planner output.
**Example (limit/trade-through, D-07, mirrors live rounding):**
```python
# Source: src/execution/placement.py:118-135,160-193 (live price derivation), D-07
limit = quantize_price(
    price=derive_limit_price(entry_min_price=plan.entry_min_price, entry_max_price=plan.entry_max_price),
    price_tick_size=tick,
    direction=entry_limit_rounding(candidate_position_side=direction),  # BUY floors, SELL ceils
)
if direction == "LONG":
    filled = minute.low <= _sub(limit, tick)      # trade-through of one tick
else:
    filled = minute.high >= _add(limit, tick)
fill_price = limit                                 # no price improvement
```

### Pattern 2: `MinuteSource` protocol (pure) with Polars adapter
**What:** `src/backtest/series.py` defines a small Protocol (`first_open`, `last_close`, `window(symbol, start, end) -> Sequence[Candle]` for trade and mark). `ListMinuteSource` serves fixtures; `src/data/` implements it lazily over the day-partitioned Parquet store (`partition_file` per symbol/day, small LRU of parsed days). Candle parsing costs 8.3 us per row [VERIFIED: timing run this session], so parse only the windows being walked.
**Validation (D-13):** on first touch of a window, assert strictly increasing `open_time_utc`, step exactly 60 s, no duplicates; a missing minute is an explicit hole, handled by the fallback rule, not padded.

### Pattern 3: Event-sourced ledger
**What:** every booking is a dated event (entry fee at entry time, TP1 leg PnL at TP1 time, funding at its `fundingTime`, exit leg at exit time). Equity = initial + sum(events); UTC-day loss = max(0, -(sum of events dated inside the UTC day)) per D033 ("daily loss = realized PnL + commissions + funding, counted as a loss", docs/trading/RISK_MANAGEMENT.md section 8); thresholds = rate x equity at the UTC day start, via `resolve_absolute_thresholds(parameter_set=..., equity=equity_at_day_start)` (src/risk/portfolio.py:79-107), recomputed at each day roll instead of once per run (current code computes it once, simulator.py:777).
**Projection to risk gates:** `OpenPosition(symbol, position_side, open_risk, daily_pnl_contribution)` is the only portfolio input type (src/risk/types.py:182-205); a resting entry has no type, so project it as `OpenPosition` with `open_risk = sized.realized_risk` and `daily_pnl_contribution = 0`. Open positions after TP1 carry `open_risk = initial_realized_risk x remaining_qty / filled_qty` (recommended, consistent with D-20).

### Anti-Patterns to Avoid
- **Splitting `run` into modules that import `evaluate_risk` elsewhere:** tests monkeypatch `src.backtest.simulator.evaluate_risk` and `src.paper.loop.evaluate_risk` (tests/test_paper_parity.py, `_spy`); the risk call must stay a module-global lookup in `simulator.py`.
- **Adding `RejectionReason` members:** the enum is pinned at 20 members with GLOSSARY gate tests (src/domain/enums.py:122-123 "(20 members)"); use `entry_kind` / summary counter vocabulary for new lifecycle outcomes instead.
- **Booking a trade per bar:** one terminal record per plan; per-bar `TOUCH_NO_FILL` becomes a counter on that record.
- **Sorting 1m input silently:** D-13 says validate and raise; the old simulator sorted strategy bars, keep that, but do not sort minutes.
- **Float anywhere, including time arithmetic on funding:** funding and fills compare Decimal prices and datetimes only (`tests/test_domain_no_float.py` has an explicit file list, see Pitfall 11).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Limit price and tick snapping | a second rounding rule | `derive_limit_price`, `quantize_price`, `entry_limit_rounding`, `sl_trigger_rounding`, `tp_trigger_rounding` (src/execution/placement.py:118-210) | live sends the snapped price; trade-through must be measured against the price the order really has |
| TP1 split and un-sizeable checks | own floor/min-notional math | `size_protectives_to_filled_qty` / `quantize_protective_qty` (placement.py:213-441) | same floor, same MIN_QTY/NOTIONAL gates as live |
| Sizing, cost guards, portfolio gates | simulator-local risk math | `evaluate_risk` unchanged | parity guarantee (src/risk/gating.py docstring) |
| Canonical hashing, decimal text | new hash helpers | `sha256_hex`, `canonical_decimal_text` (src/domain/canonical.py) | spelling-invariant hashes (D047); floats rejected |
| Per-leg cost booking | new fee/slippage formulas | extend `_apply_costs` (fee = price x qty x rate, slippage per leg, exit rate by exit kind) | Phase 12 already correct; add TP2 and END_OF_DATA kinds and funding |
| Dataset identity | new snapshot hash | `dataset_identity` (src/data/case_input.py:208-219) over all files incl. funding | already covers every file read (D-18) |
| Gap definition | simulator-side gap rules | `gap_ranges_for_files` / `GapRange` allow-list (src/data/coverage.py:340-398) | single gap definition (Phase 13 D-19) |

**Key insight:** the risky parts are semantics and data volume, not arithmetic. Reuse the live and risk helpers so the simulator cannot drift from them, and spend the effort on the event ordering, the oracle fixtures and the evidence migration.

## Research Question Answers (with evidence)

### Q1. Exact live exit policy (D-11)
- **TP1 reduce-only partial, TP2 close-all, SL close-all with unchanged level.** `size_protectives_to_filled_qty` builds `"type": "STOP_MARKET"`, `"close_position": True`, `"working_type": "MARK_PRICE"` for the SL (placement.py:298-312), TP1 as `"type": "TAKE_PROFIT_MARKET"`, `"close_position": False`, `"quantity": tp1_qty` (placement.py:410-420) and TP2 as `"close_position": True` (placement.py:423-433). EXECUTION_SPEC.md:77-85 states the same pattern but as non-binding: "A common One-way-Mode pattern may be: ... This is **mode-dependent**, not a universal template."
- **Split parameter:** `ProtectiveTemplate.tp1_quantity_fraction: Decimal` (placement.py:59), range-checked to [0, 1] (placement.py:71-74), used as `raw_tp1_qty = _mul(filled_quantity, protective_template.tp1_quantity_fraction)` (placement.py:379), floored to step and gated by min-qty/min-notional (placement.py:380-392; a reject returns all three legs None).
- **No producer anywhere in `src/` or `params/`:** repository-wide grep finds the field only in placement.py; tests construct it with `"0.5"` (tests/test_execution_adapter_contract.py:45, tests/test_execution_price_ticks.py:81, fixtures read `pt["tp1_quantity_fraction"]` in tests/test_execution_attach.py:122). The audit says the same (F-103: "grep over src/ and params/ finds no producer"). TRADING_STRATEGY_SPEC.md section 8 lists "Partial exit rules: `TBD`" (lines 73-77).
- **After TP1 the stop does not move.** Grep over `src/` for breakeven / move-stop / replace-stop finds only unrelated `break_even_price` position fields; the attach path adopts an existing ACTIVE SL by its deterministic id (manager.py:1176-1180) and the reconciler re-places a missing stop "at the original plan stop-loss, never wider" (EXECUTION_SPEC.md:196). Spec is silent on a post-TP1 stop rule; live leaves it unchanged by omission.
- **TP2 level:** `tp2 = entry_ref +/- 2 * (TP1 - entry_ref)` using the zone mid (planner.py:400-406); `take_profit_json` keys `"tp1"`, `"tp2"`, `"tp1_role": "TAKE_PROFIT_1"`, `"tp2_role": "TAKE_PROFIT_2"` (planner.py:418-427).
- **Live trigger prices are tick-snapped toward the entry** (SL up for LONG, TP down for LONG; placement.py:196-210). The simulator should snap the same way so mark-trigger touches match live.
- **Verdict (planner checkpoint, see Open Questions Q-A):** structure of live and spec agree, but the numeric TP1 fraction is defined nowhere (spec silent, live caller-supplied, tests use 0.5). D-11 requires a user decision before the simulator is written.
- **Detail that matters for fidelity:** `TAKE_PROFIT_MARKET` is a conditional market order in live, while `_apply_costs` documents TP1 as "a resting limit" and books `expected_slippage` (simulator.py:663-666; RISK_MANAGEMENT.md:58 "entry and TP1 use `expected_slippage`"). D-10 locks the booked rate; note the inconsistency, do not change it here.

### Q2. Time stop / max holding rule (D-06)
None exists. Searched `src/`, `docs/`, `params/` for `time.stop|max.hold|holding time|hold.*bars|max_bars|time-based exit|exit after|bars held`: only hits are `docs/backtest/METRICS.md:122` ("holding time is excessive", a reporting remark) and unrelated `sufficiency.py`/`paper/loop.py` text. TRADING_STRATEGY_SPEC.md sections 6-9 are all `TBD` (lines 55-80). Family sheets contain no exit-time rule. Therefore, per D-06, no time stop. Note a wording mismatch to fix: ROADMAP Phase 14 criterion 2 says positions are held "until SL, TP or expiry"; entry expiry applies to resting plans only, positions have no expiry. [VERIFIED by grep this session; absence evidence for "no rule exists", the spec text itself is TBD]

### Q3. Simulator inputs/outputs and blast radius
- **Inputs read by `run`** (simulator.py:739-751): `strategy_id, strategy_version, parameter_set_id, strategy_bars, context_bars, intrabar_1m_map, account_state, constraint_snapshot, cost_model, open_positions, daily_loss_quote, now_utc, ttl_seconds`. Output: dict with `trades` (list of `TradeRecord.to_dict()`), `strategy_version, parameter_set_hash, cost_model_hash, symbol` (simulator.py:931-937).
- **`TradeRecord`** has 26 fields (simulator.py:132-157); `entry_kind` vocabulary documented at simulator.py:124-129 ("ENTRY_FILLED", "PARTIAL_FILL", "TOUCH_NO_FILL", "EXPIRED", "INVALIDATION_CANCEL"; `exit_kind` "SL", "TP1", "EOD"). Analytics hard-codes these: `_BACKTEST_FILLED_KINDS = frozenset({"ENTRY_FILLED", "PARTIAL_FILL"})` and `_BACKTEST_UNFILLED_KINDS = frozenset({"TOUCH_NO_FILL", "EXPIRED", "INVALIDATION_CANCEL"})` (src/analytics/lifecycle.py:45-46; unknown kinds raise AnalyticsInputError at lifecycle.py:249-251); `excursion.py:319` filters `e.exit_kind == "TP1"`.
- **Callers of `run`:** `src/backtest/experiment.py:370,483,499`; tests: test_backtest_simulator.py (about 40 tests), test_backtest_experiment.py, test_backtest_binding.py, test_cost_parity.py, test_paper_parity.py, test_case_input_builder.py:232-238. Private helpers imported by tests: `_make_record`, `_apply_costs`, `resolve_intrabar`, `_parse_candle`, `_parse_account_state` (tests/test_backtest_simulator.py, tests/test_phase6_fixture_geometry.py:25).
- **`TradeRecord` consumers:** `src/analytics/inputs.py:21` (`normalize_backtest`), `src/analytics/cli.py:101`, `src/adapters/analytics_files.py:34` (evidence loader, duplicates the decimal/datetime field lists at lines 62-76 and calls `_trade_from_dict` at line 441), `src/backtest/experiment.py:34,306-318` (`_trade_from_dict` does `TradeRecord(**data)`; `_DECIMAL_TRADE_FIELDS`/`_DATETIME_TRADE_FIELDS` at lines 252-266 must list every new field), `tests/phase10_helpers.py:127-140` (`make_trade_record` with `_TRADE_DEFAULTS`; central place to add defaults).
- **`ExperimentRecord(**fields)`** is constructed in `src/adapters/analytics_files.py:506`, `src/backtest/experiment.py:231`, tests (test_analytics_files.py:93, test_analytics_report.py:112, test_backtest_report.py:51, test_backtest_experiment.py:555-578). Evidence file `tests/fixtures/phase10/loaders/evidence_sample.json` carries an `experiment` object without any new typed field, so adding required fields breaks the loader on old files, which is the desired behavior for void evidence but needs a schema bump (`EVIDENCE_SCHEMA = "analytics-evidence/1"`, analytics_files.py:61) and regenerated samples.
- **Report:** `build()` counts `n_trades = len(trade_records)` and `by_regime[_safe_str(trade.get("regime"), "UNKNOWN")]` (report.py:611-613,619) and reads `parameter_region` (report.py:728). It counts every record including non-fills, which would corrupt trade counts (G1 floor) once terminal non-fill records are emitted.
- **Case-input vs builder (Phase 13) gap (D-13):** builder emits `strategy_bars, context_bars, intrabar_1m_map, mark_price_bars, funding, open_interest, dataset_id, allowed_gaps` (src/data/case_input.py:157-179) for **one symbol per call** (`build_case_input_data`, case_input.py:444-455). Gaps against a continuous per-symbol series: (1) the raw trade 1m rows are read (`minutes`, case_input.py:525-534) but only exposed grouped into complete 60-row hours (`_group_intrabar`, case_input.py:416-436; an incomplete hour becomes `None`), so there is no continuous trade 1m series; (2) mark 1m is exposed as a flat list (`mark_bars_1m`) but fully materialized as dict rows (`frame.iter_rows(named=True)`, case_input.py:406), which cannot hold 24 months; (3) single symbol only; (4) funding gap check assumes an 8 h cadence (`("funding", ... "8h")`, case_input.py:484, `DEFAULT_FUNDING_INTERVAL_MS`, coverage.py:45), but real data has per-symbol and time-varying cadence (Q8); (5) no constraint-metadata history (it lives in PostgreSQL `symbol_metadata`, written only by `refresh_symbol_metadata`; no reader exists, grep finds only the writer in src/data/metadata.py:41,108); (6) mark rows carry `price_tick_count` and no `volume` (case_input.py:76-86) so the simulator's `_parse_candle` (requires `volume`) needs a mark-row adapter.

### Q4. The R denominator (D-20)
- **Backtest:** `realized_risk = sized.realized_risk` copied onto the record (simulator.py:890), where quantization sets `realized_risk = _mul(rounded, risk_per_unit)` (src/risk/quantization.py:117) with `risk_per_unit = sl_distance + costs` at the adverse zone edge (src/risk/gating.py:150-152). Unscaled even for `PARTIAL_FILL` today.
- **Report/normalizers:** `_r_multiple` = pnl / realized_risk (report.py:412-421); `src/analytics/stats.py:48-50` wraps it as `r_value`; `excursion._r_form` divides by the same field (excursion.py:171-177, used at 239-240,245); `TradeOutcome.realized_risk` validated non-negative (analytics/types.py:119,143-144); evidence loader refuses negatives (analytics_files.py:422-423).
- **Live (competing denominator):** `realized_risk: Decimal | None = plan.risk_budget` (src/analytics/live_outcomes.py:238) where the planner sets `risk_budget = quantize_for_storage(_mul(account_state.equity, risk_rate))` (planner.py:452), i.e. equity x rate before rounding, regardless of filled quantity (audit F-204).
- **D-20 premise is wrong:** `realized_risk` is not persisted anywhere on the live side. Grep for `realized_risk` across `src/` finds only src/risk, src/backtest, src/analytics and src/adapters/analytics_files.py; the `trade_plans` table has `risk_budget` and quantity columns but no realized risk (src/db/models.py:273-297), and `execution_intents` stores `intended_quantity`/`intended_price` only (models.py:536-537). The sizing result exists only in memory at execute time (manager.py:583-602). See Open Question Q-C for options.
- **Recommended single-field design:** keep the field name `realized_risk` (already in `TradeRecord`, `TradeOutcome`, evidence files, report, excursion); redefine it as `sized_realized_risk x filled_quantity / planned_quantity` computed by one pure function (put it beside `SizedResult`, for example `src/risk/realized_risk.py`, so both backtest and analytics import it without analytics depending on `src.backtest.report`). Remove `plan.risk_budget` as a denominator in `live_outcomes.py`; live R stays INCOMPLETE (`NO_RISK_VALUE`) until the sized figure is supplied, which costs nothing today because live R is already INCOMPLETE for every closed signal (`LIVE_NET_PNL_SEMANTICS_VERIFIED: bool = False`, live_outcomes.py:67).
- **Parity-test caveat:** live net PnL excludes funding by design (`LIVE_R_EXCLUDES: tuple[str, ...] = ("funding",)`, src/analytics/provenance.py:46) while backtest R now includes funding (D-14). The parity fixture must use a zero-funding trade, and the difference must be documented.
- **Expected consequence:** R at a stop-out is slightly above -1 in magnitude terms less than 1, because the denominator is the worst-case adverse-edge risk while the fill is at the zone mid. Not an error; mention in the report notes.

### Q5. Daily-loss day boundary and portfolio gate representation (D-18)
- **D033** (docs/DECISIONS.md D033 row): "The day is the UTC day (00:00 UTC = 07:00 Asia/Ho_Chi_Minh). The loss counted is realized PnL + commissions + funding, against a base of account equity at the UTC day start. Thresholds stay as in the params (warning 0.5%, stop 1%). On DAILY_STOP: cancel pending entries, keep the protective SL of open positions, alert." RISK_MANAGEMENT.md section 8 repeats it. Consequence the CONTEXT does not list: DAILY_STOP must **cancel resting entries** in the simulator (new terminal `entry_kind`, for example `DAILY_STOP_CANCEL`) while keeping stops on open positions.
- **Gates:** `check_portfolio` order is cluster cap, aggregate cap, position count, daily state (src/risk/portfolio.py:307-354). `CLUSTER_SYMBOLS = frozenset({"BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"})` (portfolio.py:29). Baseline set values `max_open_positions = 2`, `max_aggregate_open_risk = 0.01`, `cluster_cap = 0.005`, `daily_loss_warning_threshold = 0.005`, `daily_loss_stop_threshold = 0.01` (params/trend-pullback/baseline-v5.toml). Because `cluster_cap` equals one trade's risk rate, two same-direction cluster-symbol trades can essentially never coexist; resting entries count (D-18) so a resting BTC plan blocks a same-side ETH signal for its whole 4 h window.
- **`daily_loss_quote`** is a loss magnitude compared with `>=` thresholds (portfolio.py:62-66) and `None` fails closed (portfolio.py:260-267): use `max(0, -net_day_pnl)`.
- **Freshness gate must be neutralized for history:** `check_portfolio` rejects `age > ttl or age < 0` as STALE_CONSTRAINTS (portfolio.py:285-296). Zero-touch method (recommended): pass a point-in-time `ConstraintSnapshot` whose `metadata_observed_at_utc` is clamped to the bar close and `ttl=timedelta(0)` so age is exactly 0, and record the true `observed_at` separately; alternative is an explicit optional `ttl=None` in `src/risk` (changes a live-shared module, needs a decision).
- **Equity semantics:** ledger equity is realized only (no unrealized PnL) and `AccountState` raises for `equity <= 0` (src/core/types.py:302-307): catch it and stop opening trades (fail closed).

### Q6. Protocol amendment procedure (D-02, D032, D043)
- **Procedure** (RESEARCH_PROTOCOL.md Appendix A, lines 388-391): "Semantic change to dataset splits, cost model, execution simulation, or acceptance gates -> bump to `v1.1.0` (minor) or `v2.0.0` (major). A `Supersedes` line replaces the `none` line. A migration paragraph summarizes the change. A DECISIONS row records the amendment. A semantic change triggers a new strategy-version lineage per `docs/strategy/TRADING_STRATEGY_SPEC.md` §12." Version-binding rule (Appendix A line 386): "The research-gate reads the header `Protocol version` and requires a DECISIONS row containing `protocol vX.Y.Z frozen` and a DOC_STATUS index line containing that same version; an older version's row does not satisfy a newer header (D043)."
- **CI workflow** `.github/workflows/research-gate.yml` reads `VER` from the header and greps `protocol v${VER} frozen` in DECISIONS and `^- \`research/RESEARCH_PROTOCOL\.md\`.*v${VER}` in DOC_STATUS. Its identity-tuple step greps camelCase `strategyVersion parameterSetId parameterSetHash dataSnapshotId codeVersion costModelHash` in any file named `experiment*.json|yaml` or `backtest*.json|yaml`, and its tripwire fails any JSON/YAML containing `parameterSetId|parameter_set_id|parameterSetHash|parameter_set_hash` **and** the literal key `"parameters"` or `"parameters_json"` outside `docs/research/registry` (research-gate.yml, tripwire step). Consequences: never name a committed file `experiment*.json` / `backtest*.json`; never serialize the typed experiment parameters under the key `parameters` or `parameters_json` (use for example `parameter_values`).
- **Version number (recommended v2.0.0, user checkpoint Q-B):** semantic change to execution simulation that voids prior evidence; audit F-901 names v2.0.0; D043 reserves `v1.2.0` for changing pre-registered values, which this phase does not do. `Frozen on: 2026-09-19` must not change (D030 kill-gate clock; pinned by `PINNED_PROTOCOL_LINES` in tests/test_kill_gate_docs.py and `check_header` in scripts/decision_alignment/protocol.py:148-163); `Amended on` and `Supersedes: v1.1.0` change.
- **Files that must change in the same commit (all pin v1.1.0 literally):**
  - docs: `docs/research/RESEARCH_PROTOCOL.md` (header lines 3-7, migration paragraph, section 2 funding/cost text, section 3 execution assumptions and intrabar/limit-order text, amendment log; do NOT touch the `### Quantization` block, scripts/decision_alignment/authority.py compares it with RISK_MANAGEMENT section 11), `docs/DECISIONS.md` (new row D052: last row is D051 [VERIFIED: tail of ID list]; DC-02 requires contiguous IDs; its Decision column must contain `protocol v2.0.0 frozen` so `check_witnesses` regex `^\| D\d+ \| .*protocol v{version} frozen` matches), `docs/DOC_STATUS.md` (line 13, exactly one index line, plus a changelog line), `docs/backtest/BACKTEST_SPEC.md` (sections 4, 5, 6, 11; keep a `v1.1.0` mention or update the gate, see below), `docs/trading/RISK_MANAGEMENT.md` (funding sign convention in section 3, D033 resting-entry cancel in section 8), `docs/SOURCES.md` (funding facts), ROADMAP Phase 15 SC4 text ("research re-run under protocol v1.1.0").
  - gate code: `scripts/decision_alignment/protocol.py` (docstring, `REQUIRED_PREREGISTRATION_PHRASES` includes the heading text `"Pre-registered thresholds (v1.1.0)"` at line 56: keep that heading, since those thresholds were pre-registered in v1.1.0; `check_backtest_spec` line 310-311 requires `"v1.1.0" in norm`), `scripts/decision_alignment/bookkeeping.py:470-471` (DC-03 asserts the D043 row contains `protocol v1.1.0 frozen`: still true, history row stays).
  - tests: `tests/test_kill_gate_docs.py` (`W3_FREEZE_ROW`, `W2_INDEX_LINE`, `PINNED_PROTOCOL_LINES` incl. `> **Amended on:** 2026-09-30` and `> **Supersedes:** v1.0.1`, `> **Protocol version:** v1.1.0`, `D043_ROW_PREFIX`; rewrite to read the version from the header instead of pinning it), `tests/test_decision_alignment_protocol.py` (lines 40, 57, 59), `tests/test_research_gate_negative.py` (parametrized by version string; likely unchanged), `docs/research/holdout_consumed.json` (`"protocol_version": "v1.1.0"`, only shape-checked as vX.Y.Z; update with the amendment, entries stay empty).
- **Strategy lineage rule:** protocol section 0 says a semantic protocol change "triggers a new strategy-version lineage downstream". The simulator change alters no strategy rule (TRADING_STRATEGY_SPEC section 12 lists detection, entry, SL, TP, invalidation, expiry, features), and D-25 forbids editing parameter sets, so record in D052 that the lineage restarts with Phase 15's new versioned sets, not here.

### Experiment identity chain (D-02, D-16)
- **Today:** `experiment_id = sha256_hex({strategy_id, strategy_version, parameter_set_hash, data_snapshot_id, code_version, cost_model_hash, run_type, time_range_start_utc, time_range_end_utc, universe_hash})` (experiment.py:217-229). `assert_cost_model_binds_registry` (binding.py:43-64) compares the passed model's hash with `build_cost_model(cost_slice(parameter_set.params))`; `assert_sizing_costs_bind_registry` (binding.py:67-90) does the same but copies `partial_fill_fraction` from the model first. `cost_model_hash` hashes the 7 `COST_KEYS` plus `exit_slippage_rate` by presence (costs.py:38-51,71-83) so legacy hashes stay byte-locked.
- **`simulator_semantics_version`:** add to the `experiment_id` payload and as a typed record field (D-02). Constant `SIMULATOR_SEMANTICS_VERSION = "2.0.0"` in `semantics.py`.
- **D-16 minimal hashing change (recommended):** add one presence-driven optional cost key `funding_convention` (a code-constant string naming the sign convention and mark-notional rule, for example `"MARK_NOTIONAL_SIGNED_V1"`) following the `exit_slippage_rate` precedent (costs.py:51); make `cost_slice` append it to every registry slice so `assert_*_binds_registry` (hash-to-hash) keeps working on both sides; refuse in `simulator.run` any cost model lacking it (fail closed, so a funding-less identity can never be produced). Funding **data** identity is already covered: `dataset_identity` hashes every file read including the funding partitions (case_input.py:208-219, `used += funding_files` at line 546), and it becomes `data_snapshot_id`; also record the acknowledged `allowed_gaps` on the run summary. Parameter sets stay byte-identical (the key comes from code, not the registry), consistent with D-25. Cost: every registry-derived `cost_model_hash` moves; pins to regenerate are listed in Q7. User confirmation needed because it interprets "funding data identity ... join cost_model_hash inputs" as "sign convention joins the hash, data identity rides in data_snapshot_id" (Q-J).

### Q7. Inventory of fixtures, goldens, hash pins and tests that move (D-25) and void markers (D-03)
- **Simulator fixtures (regression snapshots or rebuilt):** `tests/fixtures/phase6/{intrabar_both_touched, intrabar_both_touched_short, intrabar_missing_fallback, invalidation_cancels_entry, limit_expiry, limit_partial_fill, limit_touch_no_fill}/input.json` (7; today only `input.json` exists, `_load_expected` is dead, audit F-805), `tests/fixtures/phase6/baselines/{no_trade,simple_trend}/input.json`, `tests/fixtures/phase6/report_slices/{input,expected}.json` (digest includes plateau/regime sections), `tests/fixtures/phase6/registry_identity/{input,expected}.json` (grandfathered, "not a simulator input", D048), `tests/fixtures/phase7/parity_overlapping_history/{input,expected}.json` (pinned digest, `parameter_set_hash`, `cost_model_hash` per D048 item 5; expected `trade_count` 1), `scripts/gen_phase6_fixtures.py` (generator places 1m data in the signal bar; rewrite).
- **Phase 10 fixtures:** `tests/fixtures/phase10/loaders/evidence_sample.json` (experiment object lacks new typed fields), phase10 helpers `tests/phase10_helpers.py:127-140`.
- **Tests that import or exercise the changed surfaces:** test_backtest_simulator.py (rewrite), test_backtest_experiment.py, test_backtest_report.py, test_backtest_binding.py, test_cost_parity.py, test_cost_per_unit.py, test_sl_loss_property.py, test_phase6_fixture_geometry.py, test_paper_parity.py, test_case_input_builder.py, test_analytics_{cli,digest,dual_universe,excursion,files,incomplete,latency,lifecycle,no_trade,report,store}.py (via helpers), test_domain_no_float.py (add new module paths to its explicit list, lines 45-52), test_decision_alignment_{protocol,bookkeeping}.py, test_kill_gate_docs.py.
- **Hash pins to regenerate deliberately:** every registry-derived `cost_model_hash` (if D-16 option above is taken), `experiment_id` values (new payload field), report digests, phase7 parity digest, trade ids (new id payload), `parameter_set_hash` pins do **not** move (no param edits; `tests/fixtures/phase4/parameters.json` untouched).
- **Paper parity coupling:** `tests/test_paper_parity.py` compares `(signal_id, reason_code)` verdicts of `run_paper_tick` per bar against `simulator.run` trades (functions `_project_simulator_verdicts`, `_replay_paper_through_bars`). With a ledger that evolves, a later signal can be `MAX_POSITIONS_REJECT` in the simulator while the stateless paper tick says OK. Keep the parity fixture to a case where the ledger never binds, or feed the paper replay the same ledger state per bar; record the choice in D052.
- **Void markers (D-03):** searched for stored evidence: `docs/research/kill_gate_decisions.json` is `{"families": [], "resets": [], "recorded_terminal": null}`, `docs/research/holdout_consumed.json` has `"entries": []`, `data/reports/` is empty, and no `experiment*.json` / `backtest*.json` exists in the repo (`git ls-files` grep). So nothing to rewrite in data; mark void in text: `06-VERIFICATION.md` (status passed, truths 01-1..03-8), `06-01-SUMMARY.md`/`06-03-SUMMARY.md` BKTS claims, REQUIREMENTS.md rows BKTS-01 and BKTS-02 (Complete, Phase 6) and DOMN-03 (Complete, Phase 3), ROADMAP Phase 6 completion line, `docs/00_PRODUCT_SCOPE.md:139` example expectancy (illustrative only; leave), and the D052 text itself.

### Q8. Phase 13 data shapes
- **Funding rows** (local Parquet under `data/raw/data_class=funding/symbol=*/date=*/sweep-*.parquet`): schema `{'symbol': String, 'funding_time_utc': Datetime(ms, UTC), 'funding_rate': Decimal(38,10), 'mark_price': Decimal(38,8)}` [VERIFIED: polars read this session]; builder columns `_FUNDING_COLUMNS = ("symbol","funding_time_utc","funding_rate","mark_price")` (case_input.py:87-92). Rows exist for 19 symbols from 2024-10-03; **0 null `mark_price` rows** in the local data, so the D-15 fallback path is exercised only by synthetic tests (docs/SOURCES.md:69 says empty markPrice appears before 2024, mapped to None by the adapter).
- **Per-symbol and time-varying cadence is real:** 8 h grid for BTC/ETH/BNB/SOL/XRP/DOGE/NEAR/QNT/SUI/WLD/ZEC/1000PEPE; 4 h for DOGS, ENA, MOVR, WIF, HYPE, PUMP; REEF mixes 8 h and 4 h; one 503 h hole in PUMP funding and one 8 h gap inside 4 h series (DOGS/ENA/MOVR/HYPE/WIF). Times jitter by milliseconds around the grid (consecutive differences of 7 h 59 m 59.99x s appear). [VERIFIED: local analysis this session; SOURCES.md:69 notes the jitter]
- **Gap tolerance:** builder tolerance is 8 h + 60 s (`FUNDING_JITTER_MS = 60_000`, `DEFAULT_FUNDING_INTERVAL_MS = 28_800_000`, coverage.py:45-51), so a missed tick in a 4 h series is not detected. No `fundingInfo` ingestion exists (grep: none), so the per-symbol interval can only be inferred from observed spacing.
- **Mark klines:** columns `symbol, interval, open_time_utc, close_time_utc, open, high, low, close, price_tick_count` (case_input.py:76-86), volume always `"0"` in the source (SOURCES.md:65), `closeTime = open + 59,999 ms` (sample rows: `1790770020000 ... 1790770079999`, tests/fixtures/phase13/mark_klines/mark_price_klines_sample.json). `pin_price_scale=True` floors Decimal columns at scale 8, so string spellings carry trailing zeros: compare numerically, not as strings.
- **Metadata:** table `symbol_metadata`, PK `(symbol, metadata_observed_at_utc)`, columns `status, contract_type, onboard_time_utc, price_tick_size, quantity_step_size, min_quantity, max_quantity, min_notional, ...` (src/db/models.py:80-110); written only by `refresh_symbol_metadata` which stamps `observed_at` with the caller-supplied or `datetime.now(UTC)` time (src/data/metadata.py:92). exchangeInfo has no history, so rows older than the first refresh cannot exist. [ASSUMED: the first refresh date is recent; the database was not inspected, no PostgreSQL client in this environment] This makes D-17 (`observed_at <= bar close`) return nothing for most of the 24-month window: Open Question Q-D.
- **Local data available for a real-data smoke:** 19 symbols of 1m trade, 1m mark, funding, 1h/4h under `data/raw` (1.6 GB) from 2024-10-03 to 2026-10-02 [VERIFIED: directory listing and funding analysis]. The D-21 outcome says 1m is 100% in every split block except HYPE, PUMP, REEF (13-CONTEXT D-21 outcome).
- **External funding fact (Binance official FAQ, fetched 2026-10-04):** "Funding Amount = Nominal Value of Positions * Funding Rate" where "Nominal Value of Positions = Mark Price * Size of a Contract"; when the rate is positive longs pay shorts; "You are only liable for funding payments in either direction if you have open positions at the pre-specified funding times", with a stated 15-second grace example (a position opened at 08:00:05 UTC could still be charged). [CITED: https://www.binance.com/en/support/faq/introduction-to-binance-futures-funding-rates-360033525031] This supports D-14's sign and mark-notional formula; the 15 s grace is a boundary nuance D-14 does not model (document it). Record the fetch in `docs/SOURCES.md` as the plan's doc task requires (project rule: exchange facts need a source).

### Q9. Pitfalls (see Common Pitfalls) and Q10 (see Validation Architecture)

## Common Pitfalls

### Pitfall 1: Quadratic strategy evaluation makes a 24-month run infeasible
**What goes wrong:** `strategy.evaluate` and `plan` call `compute_features` on the whole candle list each time, recomputing EMA20/50/200, ATR, swings and zones from bar 0 (src/core/features.py:376-386); the current loop passes `sorted_bars[: idx + 1]` every bar and filters the whole context list per bar (simulator.py:793-794).
**Measured** [VERIFIED: timing script this session, `evaluate` on synthetic time-shifted copies of the phase6 fixture]: 16.3 ms at 250 bars, 98.6 ms at 2,000 bars (about 0.047 ms per bar of history plus about 4.5 ms). Extrapolated (ESTIMATE, not measured): one symbol-year has about 8,766 1h bars, 24 months about 17,500.

| History passed to evaluate | ms per call | per symbol (17.5k calls) | 12 symbols |
|---|---|---|---|
| full prefix (avg 8.8k bars) | about 420 | about 2 h | about 25 h |
| trailing 700 bars | about 37 | about 11 min | about 2.2 h |
| trailing 1,200 bars | about 61 | about 18 min | about 3.6 h |

**Why it also matters semantically:** with an SMA-seeded EMA200 the seed influence after k extra bars is `(1 - 2/201)^k`: 0.61 after 50, 0.0067 after 500, 4.5e-5 after 1,000 [computed]; a 250-bar window would make decisions seed-dominated, 700+ bars is needed for the window not to matter to 1%. Also `compute_features` flags every feature at and after the first gap as GAP_IN_SOURCE, so one hole anywhere in 2 years would silence every later bar in a full-prefix run.
**How to avoid:** a fixed `STRATEGY_WINDOW_BARS` constant (1h) and `CONTEXT_WINDOW_BARS` (4h) in `semantics.py`, recorded in the run summary and covered by `simulator_semantics_version`; use bisect pointers instead of re-filtering. Even windowed, a full run is hours: plan a `slow`-marked real-data smoke and flag the follow-up (incremental feature series after Phase 15) in D052. Checkpoint Q-E.
**Warning signs:** a fixture test that takes more than about 5 s; the CI test job has `timeout-minutes: 30` (ci.yml line 30) and the six backtest-related test files already take about 170 s locally (measured: 118 tests in 2 m 49 s).

### Pitfall 2: Memory of the case input
**What goes wrong:** 1.05M 1m rows per series-year; as dict rows (about 0.8 GB per symbol-series-year, ESTIMATE) 24 months x trade+mark x 12 symbols is about 38 GB; as `Candle` objects at 8.3 us each it is also about 7 minutes of parsing.
**How to avoid:** the `MinuteSource` protocol (Pattern 2); the simulator only touches minutes while a plan or position is active and jumps over idle time.

### Pitfall 3: Fill and stop on the same 1m bar, and the fill-bar exit rule
**What goes wrong:** entry fill time is the close of the deciding trade-price minute (D-08), but the exact instant inside that minute is unknown, so a mark-price SL touch inside the same minute may have preceded the fill. D-12 says stop-first for SL vs TP in one mark bar; it does not say what happens to exits on the fill minute itself.
**How to avoid (recommended, user checkpoint Q-G):** exits become eligible on the fill minute itself, but only the SL is allowed to trigger there; a TP touch on the fill minute is deferred to the next minute. Gives `exit_time >= entry_time` with equality possible (D-23 allows it). Test: fill minute touches both SL and TP -> SL at the fill minute; fill minute touches only TP1 -> no exit until the next minute.

### Pitfall 4: Expiry boundary with real timestamps
**What goes wrong:** real bars close at `open + N - 1 ms` (`...59:59.999`), `expiry_utc = signal_close + 4 h` is therefore also `...59.999`, i.e. exactly the close of the last eligible 1m bar; a strict `<` comparison silently drops one minute, while the old code used `now_utc >= expiry_utc -> EXPIRED` (simulator.py:370). Fixtures use second resolution (`09:59:59`).
**How to avoid:** a 1m bar is eligible iff `close_time_utc <= expiry_utc`; the plan is cancelled at `expiry_utc`; add boundary tests for the last eligible and the first ineligible minute with millisecond timestamps, and with second-resolution fixtures.

### Pitfall 5: Prefix-invariance is false for open trades at data end
**What goes wrong:** END_OF_DATA closes a position at the last mark price of the data, so appending more bars changes that trade. A blanket "earlier trades never change" test would fail by construction.
**How to avoid:** state the invariant precisely: for a prefix run P and an extended run E, every record of P whose terminal state is not `END_OF_DATA` / `PENDING_AT_DATA_END` appears byte-identical in E; records that were END_OF_DATA in P may differ in E. Also assert no-lookahead at 1m level (appending later minutes changes nothing before them), analog of tests/test_backtest_simulator.py:416-444.

### Pitfall 6: Re-signaling while a plan is active
**What goes wrong:** trend-pullback signals on every bar that touches the zone, each with a new `signal_id` (fingerprint plus source close). A loop that keeps evaluating each hour will stack several plans on one symbol (the position-count gate does not look at symbols, src/risk/portfolio.py:337-345; it only counts entities). `TradePlanStatus.SUPERSEDED` exists in live vocabulary for a replaced pre-decision plan (GLOSSARY 272-282; manager.py:1398-1402 lists "superseded plan" as a cancel trigger).
**How to avoid (recommended, checkpoint Q-F):** at most one active entity (resting entry or open position) per symbol; a new signal while one exists is skipped and counted under the protocol's NO_TRADE category "conflict with open position" (RESEARCH_PROTOCOL section 3: "regime filter, RR floor, conflict with open position, data unavailability, kill-gate trip"), via a summary counter, not a new `RejectionReason`.

### Pitfall 7: Point-in-time metadata and wall-clock TTL
See Q5 and Q8: no rows before the first refresh; TTL gate must be neutralized without wall clock. If the rule is back-extrapolation of the earliest row, flag every affected trade (`constraints_extrapolated_backward`) and count it in the report.

### Pitfall 8: Decimal spelling vs hand-derived oracles
**What goes wrong:** `sha256_hex` hashes `Decimal` via `str()` preserving spelling (src/domain/canonical.py docstring: "Decimal -> str() preserving full precision (Decimal("1.50") stays "1.50", never "1.5")"), and Parquet rows carry scale-8 strings. A hand-derived `expected.json` compared as strings will fail on spelling, a comparison via `canonical_decimal_text` or `Decimal ==` will not.
**How to avoid:** goldens compare numerically (Decimal equality or `canonical_decimal_text`); the run-twice and prefix-invariance digests compare raw serialization.

### Pitfall 9: Funding boundary granularity
**What goes wrong:** positions enter and exit at 1m bar closes (`...59.999`), funding times jitter by a few ms after (or before) the grid. A position whose exit minute contains the funding instant is charged under `entry_time <= fundingTime < exit_time` even if the exit happened earlier in that minute; Binance's own FAQ describes a 15 s grace on entry. Quantity at a funding instant is the **open** quantity after TP1 (D-14 says `quantity`; clarify, Q-K).
**How to avoid:** implement exactly D-14 at bar-close granularity, document the same-minute convention in the spec, test funding exactly at, just before and just after entry and exit times, a position opened between two funding times (no charge), and across a TP1 partial.

### Pitfall 10: Same-minute ordering of TP1 and TP2 and of SL
In one mark minute: SL and any TP -> SL (whole position). TP1 and TP2 both touched, no SL -> book TP1 then TP2 in that order at the same minute close. Gap beyond a trigger: D-10 books the trigger price with no improvement; it does not penalize a gap through a **stop** (real stop-market fills worse); optimistic for stops, so count a `gap_through_stop` flag or choose exit at the adverse mark open (Q-G).

### Pitfall 11: Test and gate registration traps
- New modules must be added to the explicit file list in tests/test_domain_no_float.py:45-52 or the float guard silently skips them.
- Monkeypatch coupling to `src.backtest.simulator.evaluate_risk` (Anti-Patterns).
- CI research-gate file-name and key traps (Q6): no `experiment*.json` / `backtest*.json` committed files; never emit a `"parameters"` / `"parameters_json"` JSON key next to a `parameter_set_id`.
- 20-member `RejectionReason` and GLOSSARY pins: reuse `STALE_CONSTRAINTS`, `DAILY_STOP_BLOCK` etc., add no members.
- `tests/phase10_helpers.py::make_trade_record` raises on unknown override names; add new `TradeRecord` fields there with defaults.

### Pitfall 12: Multi-symbol tie order bias
Sorting by `(time, symbol)` (D-19) lets alphabetically earlier symbols take scarce slots (cluster cap effectively allows one same-side cluster trade). Deterministic and locked; state the bias in the run summary and the report notes so research does not read it as edge.

### Pitfall 13: Report counts and plateau wording
`report.build` counts every trade record and always emits a plateau section (report.py:728-753; every trade gets region "UNKNOWN" today). With terminal non-fill records and D-21, count only closed filled trades toward `trade_count` and G1, move non-fills to a separate plan-outcome count, and replace the plateau section with an explicit "not computed (BKTS-03 pending)" note; this changes the pinned report digest. END_OF_DATA trades: recommend excluding them from the pooled R distribution and the trade-floor count and reporting them separately (Q-H).

## Code Examples

### Hand-derivable single-plan oracle (tracer test shape)
```python
# Source: derived from D-07/D-10/D-12 and src/execution/placement.py (project decisions, not an external library)
# Plan (hand-built): LONG, zone mid 100.00, tick 0.10 -> limit 100.00 (on grid), SL 98.00, TP1 104.00, TP2 108.00, qty 0.5
# 1m trade minutes after signal close 09:59:59.999:
#   10:00 low 100.00  -> TOUCH_NO_FILL (needs low <= 99.90)
#   10:01 low 99.90   -> FILL at 100.00, entry_time 10:01:59.999
# mark minutes: 10:01 low 97.90 -> SL touched on the fill minute -> exit SL at 98.00, exit_time 10:01:59.999
# expected: entry_time > signal_close, exit_time == entry_time (allowed), loss = (98.00-100.00)*0.5 - fees/slippage
```

### Funding oracle (two funding instants, one positive one negative)
```python
# funding_pnl = -sign x qty x markPrice(fundingTime) x rate    (D-14)
# LONG qty 0.5; t1 rate +0.0001 mark 100 -> -(+1) x 0.5 x 100 x 0.0001 = -0.005   (pays)
#               t2 rate -0.0002 mark 102 -> -(+1) x 0.5 x 102 x (-0.0002) = +0.0102 (receives)
# hand sum = +0.0052 ; computed in a standalone Decimal script with no project imports
```

### Validator contract (D-23)
```python
# Source: D-23. Raises, never warns.
def validate_trade_record(rec, *, signal_close, data_start, data_end) -> None:
    if rec.entry_time_utc is not None:
        if not rec.entry_time_utc > signal_close: raise TradeRecordInvariantError("entry_time <= signal_close")
        if rec.exit_time_utc is not None and rec.exit_time_utc < rec.entry_time_utc: raise ...
        # exit inside [data_start, data_end]; filled quantity <= planned quantity
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| per-bar fill+exit inside the signal bar (look-ahead) | cross-bar lifecycle from bar N+1 on 1m trade series | this phase (D-01) | all earlier evidence void |
| zone touch = fill at mid | trade-through of one tick at the live (snapped) limit | this phase (D-07) | fewer, more realistic fills |
| single exit at TP1, `funding = 0` | TP1/TP2 ladder, mark-price triggers, funding PnL | this phase (D-10, D-11, D-14) | R distribution changes sign-relevant paths (F-102 worked example: TP1 then SL is +0.5R live vs +2.0R old) |

**Deprecated/outdated:** `intrabar_1m_map`, `IntrabarOutcome.exit_kind == "EOD"`, `_entry_now_utc = now_utc`, `Candle.close<open` invalidation heuristic (no spec basis; plan carries a CANDLE_CLOSE rule `{"basis": "CANDLE_CLOSE", "level": str(stop_loss), "break_distance_atr": ...}` that nothing consumes, planner.py:431-439; recommendation: invalidate at a strategy-bar close beyond `level`, Q-I).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `symbol_metadata` rows exist only from the first refresh date (recent), so `observed_at <= bar close` is empty for most history | Q8, Pitfall 7 | if older rows exist, no back-extrapolation rule is needed |
| A2 | `markPrice(fundingTime)` fallback = the mark kline whose minute contains `fundingTime`, using that minute's **open** (closest observed price to the instant) | Q8 / D-15 | funding amount differs slightly; unused with current local data (0 null rows) |
| A3 | Run-time figures for full runs (hours) are linear extrapolations of the measured 250/2,000-bar timings | Pitfall 1 | real runtime could differ by tens of percent |
| A4 | Mark-kline high/low are the extremes of mark-price updates in the minute and a trigger fires on touch (SOURCES.md:65 rates the endpoint page MEDIUM, unreadable) | exits | trigger timing could differ at the tick level |
| A5 | Dict-row memory about 0.8 GB per symbol-series-year | Pitfall 2 | only affects the size of the case, not the conclusion |
| A6 | TP legs booked at `expected_slippage` although live TPs are conditional market orders (Phase 12 lock) | Q1 | TP exit slippage may be understated; follow-up, not this phase |
| A7 | No unrealized PnL in ledger equity is acceptable for sizing (Phase 21 owns live equity) | Q5 | sizing equity slightly differs from live |

## Open Questions needing user checkpoint

1. **Q-A (mandatory before simulator code, D-11): TP1 split fraction and un-sizeable TP1.** Live and spec agree on the ladder and an unchanged SL, but `tp1_quantity_fraction` has no registered source (tests use 0.5). Recommendation: a code constant `TP1_QUANTITY_FRACTION = Decimal("0.5")` in `semantics.py` (covered by `simulator_semantics_version`, not a tunable, no param-set edit), SL unchanged after TP1, TP1 quantity via the live `size_protectives_to_filled_qty`; if TP1 is un-sizeable (MIN_QTY/NOTIONAL), reject the plan as NO_TRADE with that code because live would hold SL-only and enter SAFE_MODE (placement.py:385-392, manager.py:1270-1281). Record in D052; flag that live still needs a producer (F-103, later phase).
2. **Q-B: protocol version.** Recommended v2.0.0 (execution-simulation semantic change voiding evidence, matches F-901, D043 reserves v1.2.0 for pre-registered values), `Frozen on` unchanged (kill-gate clock not restarted, no evidence ever existed), plus rewriting the version pins listed in Q6.
3. **Q-C: D-20 premise.** `realized_risk` is not persisted for live. Options: (1) recommended: single field `realized_risk` and one pure function; live normalizer takes the sized figure as an explicit input and stays INCOMPLETE(NO_RISK_VALUE) until it is persisted (no current output changes); (2) add a nullable column on `execution_intents` or `trade_plans` plus migration, store method and mapper (touches Phase 17 persistence); (3) recompute from intended_quantity and plan prices (needs cost rates, not persisted).
4. **Q-D: point-in-time constraints before the first metadata row.** Fail closed (no historical trades) or back-extrapolate the earliest row with a recorded flag and report count. Recommendation: back-extrapolate with an explicit flag, because tick/step/min-notional rarely change and the alternative produces zero trades.
5. **Q-E: strategy window constants and run-time budget.** Recommend `STRATEGY_WINDOW_BARS` about 1,000 (1h) and about 300 (4h), recorded in the run summary; accept multi-hour full runs now and defer an incremental feature series to after Phase 15.
6. **Q-F: re-signal while a plan is active.** Recommend one active entity per symbol; skip and count under "conflict with open position".
7. **Q-G: exits on the fill minute, gap through stop, entry with missing trade 1m.** Recommend: on the fill minute only SL can trigger; stop gap books the adverse of trigger and mark-bar open (or a counted `gap_through_stop` flag if D-10 stays literal); a missing trade minute never produces a fill (fallback applies to exits only); a fallback hour resolves at the strategy-bar close, never mid-bar (causality).
8. **Q-H: END_OF_DATA and unresolved plans.** Recommend: END_OF_DATA trades stay as records with `exit_kind = END_OF_DATA`, excluded from pooled R and the closed-trade floor, counted separately; plans still resting at data end are `PENDING_AT_DATA_END`, not EXPIRED.
9. **Q-I: invalidation rule (D-05).** The current `close < open` heuristic has no support in BACKTEST_SPEC section 6, EXECUTION_SPEC section 4 or protocol section 6. Recommend the plan's own CANDLE_CLOSE rule (level = `stop_loss_price`) evaluated at strategy-bar closes, invalidation taking precedence when it coincides with expiry.
10. **Q-J: D-16 interpretation.** Recommend the presence-driven `funding_convention` cost key via `cost_slice`, with funding data identity carried by `data_snapshot_id` plus recorded `allowed_gaps`.
11. **Q-K: D-14 clarification.** Use the **open** quantity at `fundingTime` (post-TP1 remainder); funding coverage rule: a holding window is covered if consecutive funding rows inside it are no more than max cadence plus jitter apart and the window lies inside the range of closed UTC days loaded, with explicit allow-gaps recorded.
12. **Q-L: report.** Plateau section replaced by "not computed (BKTS-03)", non-fills out of `trade_count`.
13. **Q-M: SetupResult regime.** `Signal` has no regime; `evaluate` computes it internally (src/core/strategy.py `_resolve_regime`, used at line 576) and only hashes it into the fingerprint. Recommend adding an optional `regime: str | None = None` to `SetupResult` (not to the persisted `Signal`) so no hash changes; otherwise the simulator would re-derive it.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.13 via uv | everything | ✓ | 3.13.15 / uv 0.12.17 | — |
| git | code-version lookup, DECISIONS history | ✓ | 2.51.2 | — |
| Polars / DuckDB | adapter-side series reads, builder | ✓ | 1.44.2 / 1.5.5 | — |
| Local market data (`data/raw`, 19 symbols, 1.6 GB) | real-data smoke and perf measurement | ✓ | 2024-10-03 to 2026-10-02 | synthetic fixtures only |
| PostgreSQL client / server | metadata reader integration test | ✗ (no `pg_isready`) | — | SQLite-backed unit tests (ORM ignores column widths on SQLite per src/data/metadata.py docstring); live-PG tests run in CI |
| Docker | not needed here | ✓ | 29.8.0 | — |

**Missing dependencies with no fallback:** none. **With fallback:** PostgreSQL for the metadata reader (SQLite unit tests locally, CI runs PG).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (project dev extra), `asyncio_mode = "auto"`, `addopts = "-q"` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]`, `testpaths = ["tests"]` |
| Quick run command | `uv run pytest tests/test_backtest_entry.py tests/test_backtest_exits.py tests/test_backtest_funding.py tests/test_backtest_ledger.py tests/test_trade_record_validator.py -x` |
| Full suite command | `uv run pytest -m "not docker" -rs -p no:cacheprovider` (exact CI command, ci.yml line 73) plus `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src` |

### Phase Success Criteria -> Test Map
| Criterion | Behavior | Test Type | Automated Command | File Exists? |
|-----------|----------|-----------|-------------------|-------------|
| SC1 (F-120/F-901/F-902/F-804) | no fill on signal bar; fill only after N; trade-through >= 1 tick; touch-only is TOUCH_NO_FILL; `entry_time > signal_close`, `exit_time >= entry_time` raise | unit, hand-derived golden | `uv run pytest tests/test_backtest_entry.py tests/test_trade_record_validator.py -x` | ❌ Wave 0 |
| SC1 integration | simulator -> `normalize_backtest` -> `compute_trade_excursion` has no NEGATIVE_INTERVAL | integration | `uv run pytest tests/test_backtest_chain.py -x` | ❌ Wave 0 |
| SC2 (F-102, D037) | multi-bar hold to SL / TP1+TP2; TP1 then SL; mark-price series triggers; stop-first tie; fallback flag; END_OF_DATA | unit + golden | `uv run pytest tests/test_backtest_exits.py -x` | ❌ Wave 0 |
| SC3 (F-905/F-021/F-305) | funding paid/received, between-funding entry, fail-closed coverage, allow-gaps recorded; PIT constraint selection; ledger equity/daily-loss/resting gates | unit + golden | `uv run pytest tests/test_backtest_funding.py tests/test_backtest_ledger.py tests/test_backtest_pit_constraints.py -x` | ❌ Wave 0 |
| SC4 (F-204/F-123/F-118/BKTS-04) | R parity live vs backtest on identical trades; regime slice populated; typed ExperimentRecord rejects invalid construction | unit | `uv run pytest tests/test_r_denominator_parity.py tests/test_backtest_report.py tests/test_backtest_experiment.py -x` | ❌ Wave 0 (parity), ✅ existing report/experiment files rewritten |
| SC5 (F-602/F-805/F-608) | every golden case has `expected.json` + derivation; generator never puts 1m in the signal bar; regression snapshots relabeled | golden + meta | `uv run pytest tests/test_backtest_goldens.py tests/test_phase14_fixture_generator.py -x` | ❌ Wave 0 |
| SC6 (G3) | limit fills before `signal_expiry_hours`; another expires after; boundary on last eligible minute | unit | `uv run pytest tests/test_backtest_expiry_clock.py -x` | ❌ Wave 0 |
| Determinism / D-26 | run twice byte-identical; shuffled strategy bars identical; prefix-invariance (non-END_OF_DATA records); 1m no-lookahead; no float | property/unit | `uv run pytest tests/test_backtest_determinism.py tests/test_domain_no_float.py -x` | ❌ Wave 0 / ✅ |
| Protocol amendment (D-02) | header, DECISIONS row, DOC_STATUS line agree at the new version; gate PR-01..PR-10 pass | gate | `uv run pytest tests/test_decision_alignment_protocol.py tests/test_kill_gate_docs.py tests/test_research_gate_negative.py -q` and `uv run python scripts/verify_decision_alignment.py` | ✅ (edit pins) |
| BKTS-04 identity | typed fields incl. `simulator_semantics_version`, `funding_convention`, code commit/dirty, split role | unit | `uv run pytest tests/test_backtest_experiment.py -x` | ✅ rewritten |
| Real-data smoke (perf, memory) | one symbol, 3 months, bounded RSS, deterministic digest | manual/slow script | `uv run python scripts/smoke_backtest_realdata.py --symbol BTCUSDT --days 90` (to be created; not in CI) | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** the relevant new test module only (target under 20 s each; lifecycle-engine tests use hand-built `TradePlan` and in-memory minute series, no 250-bar warm-up).
- **Per wave merge:** the quick run command above plus `uv run pytest tests/test_backtest_*.py tests/test_paper_parity.py tests/test_cost_parity.py tests/test_case_input_builder.py`.
- **Phase gate:** full suite green (CI command), `ruff`, `mypy src`, decision-alignment gate, then `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_backtest_entry.py`, `test_backtest_exits.py`, `test_backtest_funding.py`, `test_backtest_ledger.py`, `test_backtest_pit_constraints.py`, `test_backtest_expiry_clock.py`, `test_trade_record_validator.py`, `test_backtest_chain.py`, `test_backtest_determinism.py`, `test_backtest_goldens.py`, `test_r_denominator_parity.py`, `test_phase14_fixture_generator.py`
- [ ] `tests/fixtures/phase14/<case>/{input.json,expected.json}` and `tests/fixtures/phase14/DERIVATIONS.md` following the Phase 5 precedent (tests/fixtures/phase5/DERIVATIONS.md: numbers from a standalone Decimal computation with no project imports; never regenerate an expectation by running the pipeline). Fixture file names must not begin with `experiment` or `backtest` (research-gate trap); no `"parameters"` key.
- [ ] Update `tests/test_domain_no_float.py` file list, `tests/phase10_helpers.py` defaults
- [ ] `scripts/smoke_backtest_realdata.py` (local only)
- Framework install: none needed.

## Security Domain

`security_enforcement` is enabled (ASVS level 1, block on high, `.planning/config.json`).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication / V3 Session | no | no network or user surface in this phase |
| V4 Access Control | no | — |
| V5 Input Validation | yes | fail-closed parsing of case inputs and evidence files: reject floats (`_coerce_money`), naive datetimes, unsorted/duplicate minutes, unknown `entry_kind`; project exception types, never warnings |
| V6 Cryptography | no (hashing only) | `sha256_hex` / `canonical_decimal_text`, no custom crypto |
| V12 Files and Resources | yes | Parquet reads confined under `raw_root` (`_relative_posix` raises `CaseInputError`, case_input.py:201-205); evidence loader path confinement exists (`confine_output_dir`); `git` lookup for code version uses a fixed argv, no shell |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Tampered or stale evidence passed off as new (old void results) | Tampering / Repudiation | evidence schema bump, `simulator_semantics_version` in identity, ExperimentRecord validation, reproduce/verify binds record to inputs |
| Path traversal through symbol or dataset names | Tampering | existing symbol regex `^[A-Z0-9]+USDT$` and raw-root confinement; keep in the multi-symbol builder |
| Silent data padding hiding gaps | Tampering | `allow_gaps` must be explicit and recorded on output; funding and minute holes raise or flag |
| Command injection in code-version lookup | Elevation | `subprocess` with list argv, outside the pure package |

## Recommended Plan / Wave Breakdown (small plans, tracer-first, tdd_mode on)

| Wave | Plan | Content | Depends |
|------|------|---------|---------|
| 1 | 14-01 | `checkpoint:decision` gate for Q-A..Q-M (answers recorded); draft D052 skeleton; no code | — |
| 1 | 14-02 | **Tracer:** `semantics.py`, v2 `TradeRecord` fields (defaults for old helpers), `validator.py` (`validate_trade_record`, `TradeRecordInvariantError`), one hand-built LONG plan -> fill N+1 -> SL slice end to end on in-memory series | 14-01 |
| 1 | 14-03 | `series.py` (`MinuteSource` protocol, `ListMinuteSource`, D-13 validation) with tests | — |
| 2 | 14-04 | entry lifecycle: trade-through at the snapped limit, TOUCH_NO_FILL counter, expiry vs simulated time (G3), invalidation, hand-derived goldens | 14-02, 14-03 |
| 2 | 14-05 | exit engine: mark-price walk, TP1/TP2 ladder, stop-first, fallback, END_OF_DATA, per-leg `_apply_costs` | 14-02, 14-03 |
| 2 | 14-06 | funding: schedule, sign convention, coverage fail-closed, mark fallback, `funding_convention` cost key + binding functions | 14-02 |
| 3 | 14-07 | ledger: events, UTC-day loss and threshold re-resolution, DAILY_STOP cancel, projection to `OpenPosition`, PIT constraint selection and TTL neutralization, multi-symbol ordering | 14-04, 14-05, 14-06 |
| 3 | 14-08 | data adapter: extend `src/data/case_input.py` (lazy `MinuteSource` over Parquet, multi-symbol, funding per symbol, metadata history reader, one `dataset_id`) | 14-03 |
| 4 | 14-09 | `run()` orchestrator: windowed strategy front-end, per-symbol streams, counters, run summary, one-active-per-symbol, e2e on phase6 prefix; determinism, shuffle, prefix-invariance suites | 14-07 |
| 5 | 14-10 | shared R denominator function; update `normalize_backtest`, `live_outcomes`, excursion exit kinds, lifecycle kinds, evidence loader (schema bump); regime on `SetupResult`/`TradeRecord`; report changes; parity test | 14-09 |
| 5 | 14-11 | typed `ExperimentRecord`, `assemble(run_summary)`, code-version adapter, split role and boundaries, `reproduce`/`verify` and baselines migrated | 14-09 |
| 6 | 14-12 | goldens: generator rewrite, `tests/fixtures/phase14` with DERIVATIONS.md, relabel regression snapshots, remove stale expected files, phase7 parity fixture decision | 14-09 |
| 6 | 14-13 | protocol amendment and docs: RESEARCH_PROTOCOL, DECISIONS D052 (lifecycle, void evidence, ladder policy, regeneration inventory), DOC_STATUS, BACKTEST_SPEC, RISK_MANAGEMENT, SOURCES, ROADMAP/REQUIREMENTS void markers, gate script and test pin updates, BKTS-01 re-verification | 14-10, 14-11, 14-12 |
| 7 | 14-14 | local real-data smoke and performance report (3 months, one symbol; memory and runtime recorded in the SUMMARY) | 14-08, 14-09 |

Plans 14-04/05/06 and 14-10/11 can run in parallel inside their waves.

## Risks

1. **Runtime of research runs (HIGH):** even windowed, full-universe runs take hours (Pitfall 1). Mitigation: windowed evaluate now, incremental features after Phase 15, smoke script, keep unit tests small.
2. **Evidence-chain blast radius (HIGH):** `TradeRecord`/`ExperimentRecord` field changes ripple through analytics loaders, helpers, fixtures and pinned digests; mitigate by defaulted trailing fields, central helper updates and the single D052 inventory.
3. **Protocol pin churn (MEDIUM):** six files pin v1.1.0 literally; one missed pin fails CI's research-gate.
4. **Premise errors in CONTEXT (MEDIUM):** D-20 (not persisted), D-17 (no history before first refresh), D-11 (split undefined) all need user answers; plan 14-01 exists for that.
5. **Parity with paper (MEDIUM):** ledger-evolving simulator vs stateless paper verdicts (Q7).
6. **Optimistic stop gaps / TP market slippage (LOW-MEDIUM):** known simplifications; flagged counters, not fixed here.

## Sources

### Primary (HIGH confidence, read this session)
- Source: src/backtest/{simulator,costs,binding,experiment,report,__init__}.py; src/core/{planner,_decimal,features,strategy,types}.py; src/risk/{gating,portfolio,sizing,types}.py; src/execution/placement.py, manager.py (excerpts); src/analytics/{inputs,live_outcomes,excursion,lifecycle,types}.py; src/adapters/analytics_files.py; src/data/{case_input,coverage,metadata}.py; src/db/models.py; src/domain/{enums,canonical,trade_plan}.py
- Docs: docs/trading/{EXECUTION_SPEC,RISK_MANAGEMENT}.md; docs/backtest/BACKTEST_SPEC.md; docs/research/RESEARCH_PROTOCOL.md; docs/DECISIONS.md (D030-D051 rows), docs/DOC_STATUS.md; docs/strategy/TRADING_STRATEGY_SPEC.md; docs/SOURCES.md (funding, mark klines)
- Gates and CI: .github/workflows/{research-gate,ci}.yml; scripts/decision_alignment/{protocol,bookkeeping}.py; tests/test_kill_gate_docs.py, test_decision_alignment_protocol.py, test_paper_parity.py, test_domain_no_float.py
- Audit: .planning/audits/2026-09-29-deep-audit/findings.json (F-120, F-901, F-902, F-102, F-103, F-804, F-905, F-021, F-305, F-204, F-123, F-118, F-602, F-805, F-608, F-904)
- Local measurements: evaluate timing, Candle parse timing, funding-series analysis over `data/raw` (scratchpad scripts, not committed)

### Secondary (MEDIUM confidence)
- Binance support FAQ (fetched via WebFetch 2026-10-04): https://www.binance.com/en/support/faq/introduction-to-binance-futures-funding-rates-360033525031 — funding formula, payer direction, liability at funding time, 15 s grace example

### Tertiary (LOW confidence)
- none beyond the `[ASSUMED]` items in the Assumptions Log

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all reuse verified by reading the files
- Architecture: HIGH for decomposition and data-volume conclusions (measured); MEDIUM for full-run hour estimates (extrapolated)
- Pitfalls: HIGH — each tied to a read file or measurement
- External facts (funding semantics): MEDIUM — one official FAQ page; Binance API pages are not readable in this project (SOURCES.md)

**Research date:** 2026-10-04
**Valid until:** 2026-11-03 (in-repo findings stay valid until the files change; re-check the Binance FAQ at implementation time)
