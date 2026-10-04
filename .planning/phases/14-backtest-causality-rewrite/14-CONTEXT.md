# Phase 14: Backtest Simulator Causality Rewrite - Context

**Gathered:** 2026-10-04
**Status:** Ready for planning
**Mode:** `--auto` (Claude chose the recommended option for every gray area; each choice is logged in 14-DISCUSSION-LOG.md and can be overridden before planning)

<domain>
## Phase Boundary

The backtest cannot see the future. A plan created at the close of bar N can fill only from bar N+1, until expiry, at a price that actually traded. Positions carry across bars, exits follow live semantics (TP1/TP2 ladder, mark-price triggers), funding is modeled, and portfolio, equity and daily-loss state evolve through the run. All earlier backtest evidence is declared void.

Delivers: a cross-bar plan and position lifecycle in `src/backtest/`, a trade-through fill rule, mark-price SL/TP triggers, funding PnL with a documented sign convention, point-in-time constraints, a simulated portfolio ledger, one R denominator shared with live, the regime slice, typed `ExperimentRecord` fields, a shared trade-record validator with temporal invariants, hand-derived golden cases with causal 1m placement, and the entry-expiry clock fix carried over from Phase 6 (G3).

Out of scope (owned elsewhere): strategy geometry and confirmed pivots (Phase 15, F-301); parameter-plateau reports and sweep runners (BKTS-03, still Pending); the holdout-once gate and its enforcement code (Phase 26, F-960); paper runtime and SHADOW approval (Phase 16); anything in the live execution path. Ingestion of mark-price klines, funding history and the Parquet case-input builder already exist (Phase 13); this phase consumes them and does not change collectors.

Requirements: BKTS-01, BKTS-02, DOMN-03, BKTS-04. Audit refs: F-120, F-901, F-902, F-102, F-804, F-905, F-021, F-305, F-204, F-123, F-118, F-602, F-805, F-608, F-904.
</domain>

<decisions>
## Implementation Decisions

### Plan and position lifecycle (F-120, F-901, G3)
- **D-01:** The simulator becomes an event loop over time, not a per-bar function. A plan created at the close of strategy bar N is active from bar N+1. Each later bar checks the entry until `trade_plan.expiry_utc`; an entry that has not filled by expiry ends as `EXPIRED`. The signal bar's own range is never examined for the fill. — **Reversibility:** one-way — changes every trade record, every golden fixture and the meaning of all earlier experiment hashes; the DECISIONS entry (D-02) pins it.
- **D-02:** Record the lifecycle as a DECISIONS entry and amend the research protocol for it (audit F-901 names protocol v2.0.0). v1.1.0 is frozen and is not edited in place; the planner follows the D032/D043 amendment procedure, checks the freeze-step version binding, and picks the version number that procedure requires. Add `simulator_semantics_version` ("2.0.0") to the experiment identity so a record produced by the old simulator can never be compared with a new one.
- **D-03:** **All earlier backtest evidence is void.** The DECISIONS entry says so explicitly, BKTS-01 is re-verified against the new simulator, and the planner checks `docs/research/` and the experiment store for any record or kill-gate decision that cited old results and marks it void (no silent deletion).
- **D-04:** G3 fix: entry expiry is judged against the **simulated bar time** (the bar being processed), never the fixture's single `now_utc`. The `_entry_now_utc = now_utc` shortcut is removed. A multi-bar test must show one limit entry that fills before `signal_expiry_hours` and one that expires after it.
- **D-05:** Invalidation stays closed-candle only (protocol glossary). On each post-signal bar the fill is evaluated first, using that bar's 1m data; invalidation is evaluated at the bar close only if the entry did not fill during the bar. The planner reconciles the existing close-versus-open rule with `docs/backtest/BACKTEST_SPEC.md` and records any change.
- **D-06:** A position is carried until SL, TP2 or data end. There is no time stop unless the spec or live code already has one (the planner checks `docs/strategy/TRADING_STRATEGY_SPEC.md`, `docs/trading/EXECUTION_SPEC.md` and `src/execution/`; if none exists it does not invent one). A position still open when the data ends is closed at the last mark price with `exit_kind = END_OF_DATA`, flagged, counted and reported separately, never booked as SL or TP.

### Fill rule (F-902)
- **D-07:** The simulated limit price is the live order price, the zone mid `entry_ref` (Phase 12 D-03 note keeps the mid as the price the order is placed at). A LONG fills only when a trade-priced 1m low is at or below `entry_ref - tick`; a SHORT only when a 1m high is at or above `entry_ref + tick` (trade-through of at least one tick). A bar that only touches the limit is `TOUCH_NO_FILL`. Fill price is the limit price (conservative; a gap through the limit does not get price improvement). The tick comes from the point-in-time constraint snapshot, never a constant.
- **D-08:** Entry detection uses **trade-price 1m klines**; fill time is the close of the deciding 1m bar. The same 1m bar may also touch SL or TP; that case is resolved by the tie-break in D-12, never by order of code paths.
- **D-09:** `partial_fill_fraction` stays 1.0 for canonical runs (D038); partial and missed fills are a separate sensitivity study and stay supported by the existing cost-model field.

### Exits: mark-price triggers and the TP ladder (D037, F-102)
- **D-10:** SL and TP triggers are evaluated on **mark-price 1m klines** (D037, protocol line 169). Entry stays on trade-price klines. The rule for a trigger touch is the same as the protocol's existing intrabar rule, applied to mark series. Exit price is the trigger price with the Phase 12 slippage terms (SL exit uses `exit_slippage_rate`, TP uses `expected_slippage`); no price improvement.
- **D-11:** The simulator **mirrors the live exit policy exactly** (F-102 option A): TP1 as a reduce-only partial and TP2 as the closing order (`docs/trading/EXECUTION_SPEC.md` lines ~81-82, `src/core/planner.py` `take_profit_json`). The TP1 quantity split, and what happens to the stop after TP1, are read from the live code and spec, not invented. If live has no explicit split or post-TP1 stop rule, that is a gap the planner raises as a checkpoint decision before writing the simulator (live and backtest must agree; fixing live is not this phase). Record the chosen policy in DECISIONS.
- **D-12:** Ambiguity tie-break stays conservative and explicit: if SL and a TP are both touched inside one 1m mark bar, SL wins (stop-first). Missing 1m coverage for a bar falls back to the strategy-bar range with stop-first, sets `fallback_applied`, and is counted in the report. Fallback is for ambiguous or missing bars only, never the default path. The tie-break name goes into the experiment record (BKTS-04).
- **D-13:** The simulator reads one **continuous, sorted 1m series per symbol** (trade and mark) instead of the per-signal-bar `intrabar_1m_map`. The planner defines the new case-input shape, extends the Phase 13 `src/data/case_input.py` builder to emit it, and validates monotonic time, no overlap and no duplicates on load. The dataset identity hash (Phase 13 D-18) continues to cover every input file.

### Funding (F-905, F-021)
- **D-14:** Sign convention, documented in RISK_MANAGEMENT or the backtest spec: `funding_pnl = -sign(position) x quantity x markPrice(fundingTime) x fundingRate`, where `sign` is +1 LONG, -1 SHORT, so a LONG with positive funding pays. It applies for every **actual** `fundingTime` in the funding history (no fixed 8 h grid, intervals can differ per symbol) at which the position is open: `entry_time <= fundingTime < exit_time`. Funding is included in net PnL and R, never in sizing. Reversibility: costly.
- **D-15:** `markPrice(fundingTime)` comes from the funding history row; when the row's mark price is empty (Phase 13 D-23 adapter fix) it falls back to the mark kline at that minute. Funding history that does not cover a holding window **fails closed** (raises a project exception) unless the caller passes an explicit allow-gaps list that is recorded on the output (same rule as Phase 13 D-19).
- **D-16:** Funding data identity and the sign-convention version join the `cost_model_hash` inputs (audit F-905), so a funding change changes the experiment identity. The planner decides the minimal hashing change under the Phase 12 D-15 canonical-numeric rule and records it with the regeneration inventory.

### Point-in-time state and the portfolio ledger (F-305)
- **D-17:** Historical mode selects versioned symbol metadata (tick, step, min notional, filters) by `observed_at <= bar close`. The wall-clock TTL stays for live and is not applied in the backtest. No wall-clock input anywhere in the simulator.
- **D-18:** The simulator carries a **simulated ledger** through the loop: equity (starts from `account_state`, updated by realized PnL including fees, slippage and funding), open positions, resting entries and daily-loss state. Order inside one timestamp: first advance every active plan and position over the elapsed bar and book exits and fills, then update the ledger, then evaluate new signals at the bar close with the updated ledger. Resting entries count toward portfolio gates, matching D035 (available margin includes resting entries). The daily-loss day boundary follows D033; the planner locates it and does not redefine it.
- **D-19:** A case can contain several symbols. The loop is deterministic across symbols (sorted by time, then symbol). Result order, tie order and hashing are byte-stable.

### R denominator, regime, experiment record (F-204, F-123, F-118, BKTS-04)
- **D-20:** One R denominator for backtest and live: the realized risk persisted at sizing (Phase 12 `SizedResult.realized_risk`, the worst-case adverse-edge figure), scaled by `filled_quantity / planned_quantity`. One function computes it, used by every normalizer (`normalize_backtest`, `src/analytics/live_outcomes.py`, excursion). A parity test feeds identical trades through both paths. The planner picks the single field name and removes any competing denominator.
- **D-21:** The signal's regime is carried onto `TradeRecord` and emitted as a report slice (F-123). The plateau claim is not made here: parameter-plateau and sweep runners belong to BKTS-03, which stays Pending; this phase must not state or imply plateau evidence.
- **D-22:** `ExperimentRecord` gets typed, validated fields (F-118) instead of free-form `result_summary_json` contents: NO_TRADE counts by reason, the intrabar tie-break, timeframe, full parameters and costs, `simulator_semantics_version`, a verifiable code version (git commit and dirty flag), fallback count, `END_OF_DATA` count, and split role and boundaries (F-904 identity part only; the holdout-once enforcement stays in Phase 26). Validation is in `__post_init__`; an invalid record cannot be constructed. Reversibility: costly (record hash inputs change; included in the regeneration inventory).

### Trade-record invariants and verification (F-804, F-602, F-805, F-608)
- **D-23:** A shared trade-record validator asserts, on every trade, `entry_time > signal_close` and `exit_time >= entry_time` (plus `exit_time` inside the data window and filled quantity <= planned). It raises, never warns. It runs inside the simulator and again at every normalizer boundary. An integration test drives simulator -> `normalize_backtest` -> excursion.
- **D-24:** Every golden case has a **hand-derived expected output** in a committed sidecar (`expected.json` plus a derivation note) that is not produced by the code under test. The fixture generator never places 1m data inside the signal bar; 1m data covers bars N+1 onward. Required cases include: the signal bar's own range touches SL or TP and no fill happens on that bar; trade-through versus touch-only; fill then hold across several bars to SL, to TP1 then TP2; expiry before fill; both-touched tie-break; gap through the limit; funding paid and received, including a position opened between two funding times; ledger effects (a loss that blocks the next signal via daily loss); END_OF_DATA; missing-1m fallback; a nonzero-cost parity fixture.
- **D-25:** Existing Phase 5/6 fixtures that are not rebuilt are relabeled **regression snapshots** (F-608), unused expected files are removed or fixed, and one DECISIONS entry lists every fixture, pin and hash that moved and why, in the style of D048. Parameter sets are not edited (F-810); a new tunable would mean a new versioned set, and none is planned.
- **D-26:** Determinism stays strict: Decimal arithmetic via `src/core/_decimal.py`, no float, no wall-clock, sorted iteration, byte-identical output on rerun, prefix-invariance (appending later bars cannot change earlier trades). `src/backtest/` stays Polars-free (Phase 13 D-22).

### Research-driven refinements (auto-resolved after 14-RESEARCH.md, 2026-10-04)
- **D-27 (Q-A, stays a CHECKPOINT, not auto-resolved):** the TP1 quantity fraction has no producer in `src/` or `params/` and TRADING_STRATEGY_SPEC section 8 is TBD. Plan 14-01 is a `checkpoint:decision` that must be answered by the user before any simulator code. Researcher's recommendation to present: constant `TP1_QUANTITY_FRACTION = Decimal("0.5")` in a `semantics.py` covered by `simulator_semantics_version` (not a tunable, no param-set edit); SL unchanged after TP1 (matches live); TP1 quantity via the live `size_protectives_to_filled_qty`; an un-sizeable TP1 rejects the plan as NO_TRADE (live would hold SL-only and enter SAFE_MODE). Live still needs a producer (F-103), a later phase.
- **D-28 (Q-B):** protocol amendment version v2.0.0, `Frozen on` unchanged; rewrite every version pin in the same commit (`scripts/decision_alignment/protocol.py`, bookkeeping DC-03, `tests/test_kill_gate_docs.py`, `tests/test_decision_alignment_protocol.py`, `holdout_consumed.json`, DOC_STATUS). Next DECISIONS id is D052; its row must contain `protocol v2.0.0 frozen`.
- **D-29 (Q-C, supersedes the D-20 premise that `realized_risk` is persisted for live):** it is not persisted. Keep the field name `realized_risk` and one pure function; the live normalizer takes the sized figure as an explicit input and stays INCOMPLETE(NO_RISK_VALUE) until persisted (no current output changes). Funding is excluded from live R, so the parity fixture uses zero funding. No database migration in this phase.
- **D-30 (Q-D):** point-in-time constraints before the first metadata row back-extrapolate the earliest row with a recorded flag and a report count (tick/step/min-notional rarely change; fail-closed would produce zero trades).
- **D-31 (Q-E):** the strategy front-end is windowed (`STRATEGY_WINDOW_BARS` about 1,000 for 1h and about 300 for 4h, recorded in the run summary); multi-hour full runs are accepted; an incremental feature series is deferred past Phase 15. The 1m inputs go through a lazy pure `MinuteSource` protocol in `src/backtest`, with the Polars implementation in `src/data` (a dict-of-rows case is about 38 GB).
- **D-32 (Q-F):** one active plan or position per symbol; a re-signal meanwhile is skipped and counted as "conflict with open position". D033 DAILY_STOP also cancels resting entries.
- **D-33 (Q-G):** on the fill minute only SL can trigger; a stop gap books the adverse of the trigger and the mark-bar open and sets a counted flag; a missing trade 1m minute never produces a fill (fallback is for exits only); a fallback hour resolves at the strategy-bar close, never mid-bar. Expiry comparison uses `<=` against the last 1m bar close.
- **D-34 (Q-H):** END_OF_DATA trades stay as records, are excluded from pooled R and the closed-trade floor, and are counted separately; plans still resting at data end are `PENDING_AT_DATA_END`, not EXPIRED. The prefix-invariance test excludes END_OF_DATA trades.
- **D-35 (Q-I, refines D-05):** replace the unsupported `close < open` invalidation heuristic with the plan's own CANDLE_CLOSE rule (level = `stop_loss_price`), evaluated at strategy-bar closes; invalidation wins when it coincides with expiry.
- **D-36 (Q-J, Q-K, refines D-14 and D-16):** funding joins identity through a presence-driven `funding_convention` cost key via `cost_slice`, with data identity carried by `data_snapshot_id` plus recorded `allowed_gaps`; funding uses the open quantity at `fundingTime` (post-TP1 remainder); a holding window is covered when consecutive funding rows are no more than the max cadence plus jitter apart (cadence is 8h or 4h per symbol, times jitter by milliseconds) and the window lies inside the loaded closed UTC days.
- **D-37 (Q-L):** the report's plateau section becomes "not computed (BKTS-03)" and non-fill records stop counting as trades.
- **D-38 (Q-M):** add an optional `regime: str | None = None` to `SetupResult` (not to the persisted `Signal`) so no hash changes.
- **D-39 (ROADMAP wording):** criterion 2 says "until SL, TP or expiry" but positions have no expiry; the planner rewords it to "until SL, TP2 or data end" in the same commit as the DECISIONS entry.

### Claude's Discretion
- Module split of the rewritten simulator (the current `simulator.py` is ~1,070 lines; separate lifecycle, ledger, funding and validator modules are welcome) and all internal names, provided public entry points keep working or are updated everywhere.
- Exact layout of the new case-input schema and fixture folder names, subject to D-13 and D-24.
- The field name for the shared R denominator and the validator's exception type.

### Folded Todos
None. No pending todo matched this phase.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Authority and decisions
- `docs/DECISIONS.md` — D031 (quantization authority), D033 (daily loss), D035 (resting entries count in margin), D036 (taker entry), D037 (mark-price triggers), D038 (partial_fill_fraction 1.0), D039, D043, D046-D048 (Phase 12 cost model, adverse-edge sizing, regeneration inventory), D049 (Phase 13 data foundation); the new entry for this phase is added here
- `AGENTS.md` — Decimal-only, determinism, no-lookahead, prefix-invariance, fail closed
- `.planning/ROADMAP.md` — "Phase 14" goal and criteria 1-6
- `.planning/REQUIREMENTS.md` — BKTS-01, BKTS-02, DOMN-03, BKTS-04
- `.planning/phases/12-fee-cost-model-correctness/12-CONTEXT.md` — D-01 to D-06 (cost units, slippage, `exit_slippage_rate`), D-14 to D-16 (versioned sets, canonical hashing, deliberate regeneration)
- `.planning/phases/13-research-data-foundation-fixes/13-CONTEXT.md` — D-11, D-12 (mark klines), D-17 to D-19, D-22, D-23 (case-input builder, dataset identity, funding backfill)
- `.planning/phases/06-backtest-simulator-experiment-registry/06-VERIFICATION.md` — gap G3 (entry-expiry clock)
- `.planning/phases/06-backtest-simulator-experiment-registry/06-CONTEXT.md` — original simulator decisions this phase supersedes

### Audit
- `.planning/audits/2026-09-29-deep-audit/DEEP_AUDIT_REPORT.md` and `findings.json` — F-120, F-901, F-902, F-102, F-804, F-905, F-021, F-305, F-204, F-123, F-118, F-602, F-805, F-608, F-904

### Specs to amend or read
- `docs/research/RESEARCH_PROTOCOL.md` (v1.1.0 FROZEN; read-only, amend by new version per D-02), especially the mark-price trigger paragraph (~line 169) and the invalidation glossary entry (~line 345)
- `docs/backtest/BACKTEST_SPEC.md` — candle-close rule, intrabar ambiguity, limit-order simulation
- `docs/trading/EXECUTION_SPEC.md` (~lines 81-82: TP1 reduce-only, TP2 closePosition) and `docs/trading/RISK_MANAGEMENT.md` (costs, section 3)
- `docs/strategy/TRADING_STRATEGY_SPEC.md` — any time-stop or holding rule (D-06)
- `docs/SOURCES.md` — funding and mark-price endpoint facts recorded in Phase 13

### Code
- `src/backtest/simulator.py` — `run`, `_resolve_entry`, `resolve_intrabar`, `_apply_costs`, `_make_record`; `_entry_now_utc` shortcut (~line 758) and per-bar fill at the zone mid (~lines 482-542)
- `src/backtest/costs.py`, `src/backtest/experiment.py`, `src/backtest/report.py`, `src/backtest/binding.py`
- `src/core/planner.py` — `take_profit_json` (tp1, tp2), `entry_ref`, plan expiry
- `src/core/_decimal.py` — pinned Decimal helpers
- `src/risk/` — `evaluate_risk`, `SizedResult`, `cost_rates`, guards
- `src/analytics/live_outcomes.py` and `normalize_backtest` — normalizers that must share the R denominator
- `src/data/case_input.py` and `src/data/` coverage and funding modules — Phase 13 inputs
- `tests/fixtures/phase5/`, `tests/fixtures/phase6/`, `tests/test_backtest_simulator.py` — fixtures and tests affected
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `resolve_intrabar` (tie-break, fallback flags, coverage notes): keep the contract, re-point it at mark series and forward walks.
- `_apply_costs` and the Phase 12 cost producer: slippage per leg and exit slippage already correct; funding is the missing term.
- `evaluate_risk` pipeline: reused unchanged; the ledger supplies its account, positions and daily-loss inputs each time.
- Phase 13 case-input builder and dataset hash: the data side of reproducibility already exists.
- `TradeRecord.to_dict` and `ExperimentRecord` hashing: the identity chain to extend, not replace.

### Established Patterns
- Frozen artifacts are versioned, never edited in place (params, protocol).
- Deliberate regeneration gets one DECISIONS entry listing every moved fixture and hash.
- Domain code stays free of Polars; adapters hold data-frame work.
- Fail closed with project exceptions; no silent padding.

### Integration Points
- `run(case_input)` is called by the experiment layer and by tests; its output feeds `report.py` slices and `ExperimentRecord`.
- Normalizers in `src/analytics/` consume trade records; the temporal validator sits at that boundary too.
- Paper loop (Phase 16) will reuse lifecycle semantics later; keep lifecycle logic in importable functions, not buried in `run`.
</code_context>

<specifics>
## Specific Ideas

- Audit worked example for the tests: a signal bar whose own range touches both the limit and the SL must produce no fill and no exit on that bar.
- Funding example for the oracle: a LONG held across two actual `fundingTime` instants, one positive and one negative rate, hand-computed to the cent.
- A multi-bar example for G3: `signal_expiry_hours = 4`; fill on bar N+2 (before expiry) versus a limit never reached until bar N+5 (expired).
</specifics>

<deferred>
## Deferred Ideas

- Parameter-plateau analysis and sweep runner: BKTS-03 (still Pending).
- Holdout-once enforcement code and split-date amendment enforcement: Phase 26 (F-960); this phase only adds the typed record fields (D-22).
- Trend-pullback geometry, confirmed pivots, minimum stop: Phase 15 (F-301).
- Maker (post-only) entry study and partial-fill sensitivity runs: separate sensitivity work under D038, not canonical.
- Fixing live exit policy if live and spec disagree on the TP ladder: raised as a checkpoint in planning (D-11), changed only by an explicit decision.

None of the pending todos matched this phase.
</deferred>

---

*Phase: 14-Backtest Simulator Causality Rewrite*
*Context gathered: 2026-10-04*
