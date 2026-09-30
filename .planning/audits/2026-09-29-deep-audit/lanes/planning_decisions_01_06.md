# Lane B1: planning_decisions_01_06

Stage B review of the GSD planning decisions for phases 01–06. Most of these were auto-picked "recommended" options (`--auto`, or the user said "you choose the best for me"). Each decision is judged against trading and exchange reality and against the Stage A corrected rules (`lanes/docs_trading_soundness.md` "Corrected Rules for Code Audit", `lanes/docs_exchange_facts.md` "Exchange Facts for Code Audit"). Code is cited only to show the effect of a decision. The code itself is the job of Stage C.

## Scope

- Phases: `.planning/phases/01-research-formalization`, `02-data-foundation`, `03-domain-registry-fixtures`, `04-pure-core-feature-strategy-planner`, `05-risk-engine`, `06-backtest-simulator-experiment-registry`.
- Read per phase: CONTEXT, DISCUSSION-LOG, RESEARCH (decision-bearing sections: recommendations, assumptions, open questions, pitfalls), PLANs (skimmed), REVIEW / REVIEW-FIX (all iterations for 02), VERIFICATION. VALIDATION files were checked only at the metadata level.
- Cross-references:
  - `.planning/v0.3-MILESTONE-AUDIT.md` (M1–M4, tech_debt)
  - `.planning/ROADMAP.md` phases 11–17
  - `params/*/*.toml`
  - `docs/research/RESEARCH_PROTOCOL.md`
  - `docs/research/families/trend-pullback.md`
  - `docs/trading/RISK_MANAGEMENT.md` (cluster lines)
- Code touched only to show the effect of a decision:
  - `src/backtest/simulator.py`
  - `src/core/planner.py`, `src/core/features.py`, `src/core/strategy.py`
  - `src/risk/portfolio.py`
  - `src/data/backfill.py`, `src/data/collector.py`
  - `src/execution/placement.py`, `src/execution/manager.py`
  - `src/ops/backup.py`
- Stage A inputs: `lanes/docs_trading_soundness.md`, `lanes/docs_exchange_facts.md`, `INVARIANTS.md`.
- Probe: `tmp/planning_decisions_01_06/probe_samebar.py` runs `simulator.run` on three Phase-6 golden fixtures (the evidence for F-901).

## Coverage

| File | Level | Note |
|---|---|---|
| .planning/phases/01-research-formalization/01-CONTEXT.md | DEEP_READ | D-01..D-08 |
| .planning/phases/01-research-formalization/01-DISCUSSION-LOG.md | DEEP_READ | all --auto |
| .planning/phases/01-research-formalization/01-RESEARCH.md | DEEP_READ | §Frozen-Protocol, Don't Hand-Roll, Pitfalls, Assumptions, Open Qs |
| .planning/phases/01-research-formalization/01-0[1-4]-PLAN/SUMMARY, 01-VERIFICATION, 01-VALIDATION, 01-PATTERNS, COVERAGE, negative-test txt | METADATA_ONLY | |
| .planning/phases/02-data-foundation/02-CONTEXT.md | DEEP_READ | D-01..D-12 |
| .planning/phases/02-data-foundation/02-DISCUSSION-LOG.md | DEEP_READ | user delegated |
| .planning/phases/02-data-foundation/02-RESEARCH.md | NORMAL_READ | endpoints table, volume math, assumptions, open Qs |
| .planning/phases/02-data-foundation/02-REVIEW*.md, 02-REVIEW-FIX*.md | NORMAL_READ | all fixed; Info out of scope |
| .planning/phases/02-data-foundation/02-0[1-5]-PLAN/SUMMARY, 02-VERIFICATION | NORMAL_READ (grep) | depth/D-02 references |
| .planning/phases/02-data-foundation/02-VALIDATION, 02-PATTERNS, COVERAGE | METADATA_ONLY | |
| .planning/phases/03-domain-registry-fixtures/03-CONTEXT.md | DEEP_READ | D-01..D-12 |
| .planning/phases/03-domain-registry-fixtures/03-DISCUSSION-LOG.md | DEEP_READ | |
| .planning/phases/03-domain-registry-fixtures/03-REVIEW.md, 03-REVIEW-FIX.md | NORMAL_READ | 19/19 fixed |
| .planning/phases/03-domain-registry-fixtures/03-RESEARCH, PLANs, SUMMARYs, PATTERNS, UAT, VALIDATION, VERIFICATION | METADATA_ONLY (grep) | seed params origin |
| .planning/phases/04-pure-core-feature-strategy-planner/04-CONTEXT.md | DEEP_READ | D-01..D-10 |
| .planning/phases/04-pure-core-feature-strategy-planner/04-DISCUSSION-LOG.md | DEEP_READ | |
| .planning/phases/04-pure-core-feature-strategy-planner/04-03-PLAN.md, 04-03-SUMMARY.md | NORMAL_READ | checkpoint:decision auto-option A |
| .planning/phases/04-pure-core-feature-strategy-planner/04-RESEARCH.md | NORMAL_READ | entry_ref options, open Qs |
| .planning/phases/04-pure-core-feature-strategy-planner/04-REVIEW.md, 04-REVIEW-FIX.md | NORMAL_READ | 24/24 fixed |
| .planning/phases/04-pure-core-feature-strategy-planner/other PLAN/SUMMARY/PATTERNS/VALIDATION/VERIFICATION | METADATA_ONLY | |
| .planning/phases/05-risk-engine/05-CONTEXT.md | DEEP_READ | D-01..D-05 |
| .planning/phases/05-risk-engine/05-DISCUSSION-LOG.md | DEEP_READ | |
| .planning/phases/05-risk-engine/05-RESEARCH.md | NORMAL_READ | A3 cluster assumption, daily-loss open Q |
| .planning/phases/05-risk-engine/05-01-PLAN.md, 05-02-PLAN.md | NORMAL_READ | cap semantics |
| .planning/phases/05-risk-engine/05-REVIEW.md, 05-REVIEW-FIX.md | NORMAL_READ | 13/13 fixed |
| .planning/phases/05-risk-engine/05-VALIDATION, 05-VERIFICATION, 05-PATTERNS, SUMMARYs | METADATA_ONLY | |
| .planning/phases/06-backtest-simulator-experiment-registry/06-CONTEXT.md | DEEP_READ | D-01..D-05 |
| .planning/phases/06-backtest-simulator-experiment-registry/06-DISCUSSION-LOG.md | NORMAL_READ | |
| .planning/phases/06-backtest-simulator-experiment-registry/06-RESEARCH.md | NORMAL_READ | pitfalls (1m lookahead), splits |
| .planning/phases/06-backtest-simulator-experiment-registry/06-01-PLAN.md, 06-02-PLAN.md, 06-03-PLAN.md | NORMAL_READ | entry semantics, cost keys |
| .planning/phases/06-backtest-simulator-experiment-registry/06-REVIEW.md, 06-REVIEW-FIX.md | DEEP_READ | 3 skipped (CR-04, WR-03, WR-13) |
| .planning/phases/06-backtest-simulator-experiment-registry/06-VERIFICATION.md | NORMAL_READ | G1–G4 |
| .planning/phases/06-backtest-simulator-experiment-registry/06-VALIDATION, 06-PATTERNS, SUMMARYs, COVERAGE | METADATA_ONLY | |
| .planning/v0.3-MILESTONE-AUDIT.md | NORMAL_READ | M1–M4, tech_debt |
| .planning/ROADMAP.md | NORMAL_READ (grep) | P11–P17 goals, backup, funding |
| .planning/REQUIREMENTS.md | NORMAL_READ (grep) | REFN, universe |
| docs/research/RESEARCH_PROTOCOL.md | NORMAL_READ | header, numeric-gate reservation L24, L205–236 |
| docs/research/families/trend-pullback.md | METADATA_ONLY (grep) | expiry "value TBD" |
| docs/trading/RISK_MANAGEMENT.md | METADATA_ONLY (grep) | cluster L50–59 |
| params/trend-pullback/baseline-v1.toml, baseline-v3.toml; other params (grep) | NORMAL_READ | seed values, partial_fill_fraction |
| src/backtest/simulator.py | NORMAL_READ | L189–276, L351–540, L699–900 (effect of the Phase 6 decisions) |
| src/core/planner.py | METADATA_ONLY (grep) | entry_ref = zone mid L382–404 |
| src/core/features.py | NORMAL_READ | L410–428 (EMA200 required) |
| src/risk/portfolio.py | NORMAL_READ | L24–31, L150–175 |
| src/data/backfill.py | NORMAL_READ | L545–625 |
| src/data/collector.py | METADATA_ONLY (grep) | FUNDING_BOOTSTRAP_LOOKBACK_MS L74 |
| src/execution/placement.py, src/execution/manager.py | METADATA_ONLY (grep) | limit price = zone mid |
| src/ops/backup.py | METADATA_ONLY (grep) | OneDrive target |
| lanes/docs_trading_soundness.md, lanes/docs_exchange_facts.md | DEEP_READ | Stage A inputs |
| INVARIANTS.md | NORMAL_READ (grep) | INV / AMB IDs |

## Verified Safe Areas

- **Phase 1 artifacts (D-01..D-06, D-08).**
  - Checked: 01-CONTEXT, 01-RESEARCH, RESEARCH_PROTOCOL header.
  - A separate frozen protocol doc, a one-way living-doc firewall, the 7-slot family template, C1–C7 resolved through DECISIONS rows, and "V1 family TBD" are all sound research-governance choices.
- **Parameter values kept out of the protocol (01-RESEARCH Pitfall 2).** Keeping ATR multipliers, RR minima and similar values in the registry rather than the frozen protocol is correct. What went wrong is the spill-over of that rule to acceptance thresholds (F-903).
- **Phase 2 storage and data discipline (D-03..D-07, D-09..D-11).**
  - Checked: 02-CONTEXT and the 02-RESEARCH endpoints table.
  - Official-SDK klines, immutable Hive Parquet, the PG/Parquet role split, UTC storage, and flag-never-fabricate gaps are all sound.
  - The 5-minute OI poll is sound. The 30-day `openInterestHist` window is correctly identified (it matches the A2 facts: latest 1 month, limit ≤ 500). All Phase-2 review iterations were fully fixed (0 skipped).
- **Phase 3 (D-01..D-08, D-10..D-12).** Pure frozen domain dataclasses, the ORM mirror, content-hash IDs, the TOML registry with a canonical SHA-256, the loader exception plus CI gate, the strategy/runtime split, explicit status columns, and Decimal/UTC are all sound. Review: 19/19 fixed.
  - Caveat for Stage C: deterministic client IDs do not prevent re-submission after a fill or cancel (Corrected Rule 28).
- **Phase 4 (D-01..D-07, D-09, D-10).** The closed-candle-only engine, per-feature validity flags with NO_TRADE on invalid, tracer-first rollout, and a pure core are all sound. The D-08 "TP1 built from minimum_rr" design was vacuous, but it was caught (04-REVIEW CR-03) and fixed: `src/core/planner.py` L9–13, L402–408 now use a structure-derived TP1, so the RR gate can fire.
- **04-03 checkpoint option A (entry_ref = zone mid) is sound for LIVE sizing.**
  - Checked: `src/execution/placement.py` L133–143 and `src/execution/manager.py` L472.
  - The live LIMIT is placed at the zone mid, and a buy or sell limit never fills worse than its price. So sizing on the mid satisfies the intent of Corrected Rule 2 ("entry_worst") for live.
  - Stage C should not raise a live-sizing defect on the zone-mid basis alone. The defect is in how the backtest maps it (F-902).
- **Phase 5 quantization order (D-02).** Floor to step, then min-qty, then notional, then the 60% realized-risk utilization check, with no round-up. This matches Corrected Rule 4. Strict fail-closed on stale or unknown state (D-04) is sound. The 05-REVIEW CR-01 (side hard-coded LONG) and CR-02 (TTL fail-open) findings were fixed.
- **Phase 6 identity and reporting (D-03, D-04).** The six-field experiment identity, the stationary block bootstrap with a recorded seed, and the resampled drawdown distribution, plateau section and baselines exist in `src/backtest/report.py` L5–7, L95–196.

## Findings

### F-901 — Backtest simulator (Phase 6 design) fills, invalidates and exits a plan inside the very bar that generated its signal (look-ahead); plans are never carried to later bars, and the skipped fix CR-04 was never scheduled

- **Severity:** HIGH
- **Confidence:** CONFIRMED (code trace plus probe)
- **Classification:** DEFECT
- **Category:** research methodology / backtest semantics
- **Component:** Phase 6 simulator design (06-01-PLAN entry semantics; 06-REVIEW-FIX skipped CR-04)
- **File:** src/backtest/simulator.py
- **Lines:** 753–866 (loop), 351–540 (`_resolve_entry`), 189–276 (`resolve_intrabar`)
- **Invariant:** INV-003, INV-004, INV-103, INV-104; AMB-035
- **Phase/commit:** 06 / 77a0659 (feat(06-01)); skip recorded in 06-REVIEW-FIX 2026-09-26
- **Known-prior:** partial.
  - KNOWN: 06-REVIEW CR-04 (skipped: "plans are never carried across bars … needs a planner/simulator design call"), 06-VERIFICATION G3, 06-REVIEW WR-02 (TP2 not modeled), WR-12.
  - None of these names the look-ahead. v0.3-MILESTONE-AUDIT lists only "06-VERIFICATION stale". ROADMAP P11–P17 do not schedule a fix.
- **Evidence:**
  - Loop (L753–866):
    - `evaluate(snapshot=...closed_setup = sorted_bars[: idx + 1]...)` produces a signal whose `detected_at_utc` = the close of `bar`.
    - The same `bar` is then passed to `_resolve_entry(trade_plan=trade_plan, bar=bar, ...)`, which checks `zone_touched = bar.high >= entry_min and bar.low <= entry_max` (L449) and, for LONG, `if bar.close < bar.open: INVALIDATION_CANCEL` (L394).
    - The exit is resolved from `intrabar_map.get(f"{bar.symbol}|{bar.close_time_utc.isoformat()}")` (L852), which holds the 1m candles inside that same signal bar.
  - The 06-01-PLAN L109 design says "a LIMIT-zone plan fills only when a strategy-bar range touches the zone". 06-REVIEW-FIX L285–298 says: "plans are never carried across bars. … the real fix is a cross-bar plan lifecycle … a design decision beyond review-fix scope."
  - Probe (`tmp/planning_decisions_01_06/probe_samebar.py`) on golden fixtures `intrabar_both_touched` and `limit_partial_fill`: `entry_time_utc '2026-09-11T09:59:59+00:00'`, `exit_time_utc '2026-09-11T09:00:59+00:00'`, `exit_kind 'SL'`. **The exit happens 59 minutes before the entry**, using minutes before the signal existed.
  - Related:
    - When neither SL nor TP is hit, the trade exits "EOD" at the signal bar's last 1m close (L268–275), so the holding period is at most 0 bars.
    - Missing 1m data leads to an unconditional SL exit even if the bar never reached the SL (L216–225). D-01 limits the fallback to both-touched bars.
    - The TP2 leg is never modeled (WR-02).
    - `open_positions` and `daily_loss_quote` are constants read from the case input (L716–717), so portfolio caps and DAILY_STOP are never driven by the backtest's own trades.
- **Expected** (Corrected Rules 18 and 20, BACKTEST_SPEC §3–6, 06-RESEARCH Pitfall 2 "1m resolution consumes only 1m candles strictly inside (entry_bar.open, exit_bar.close]"):
  - A plan created at the close of bar N can only fill from bar N+1 onward, through its expiry.
  - The position is carried across bars until SL, TP or expiry/invalidation.
  - The intrabar walk starts after the fill.
- **Actual:** Entry, invalidation and exit are all read from price data that precedes the decision. The exit horizon is the signal bar itself.
- **Reproduction:** Run `tmp/planning_decisions_01_06/probe_samebar.py` with the repo venv. `exit_time_utc < entry_time_utc` on the fixtures.
- **Impact:**
  - Every Phase-6 experiment result is structurally invalid: look-ahead in both directions, zero-bar holding, TP2 ignored.
  - The kill gate (Phase 10) and V1 family selection consume these results. A family could be passed or killed on meaningless evidence.
  - It is not yet producing live money decisions, because M4 means the backtest does not run on real data yet. But it is the validation authority the project rests on.
- **Why tests miss it:**
  - Golden fixtures pin the current (wrong) semantics byte for byte.
  - The determinism suites (Phase 3 D-08) cover the strategy path, not the simulator fill/exit path.
  - 06-VERIFICATION IN-02b notes that the "no-lookahead exit [is] decided on candle 0".
- **Remediation:**
  - Make an explicit design decision (DECISIONS row plus a protocol v2.0.0 semantic change): a cross-bar plan lifecycle. The plan becomes active at the next bar open. Entry is checked per subsequent bar (1m when available) until `expiry_utc`. The open position is carried until SL/TP/expiry. TP1/TP2 ladder semantics must match live. The fallback applies only to genuinely ambiguous bars.
  - Add a test asserting `entry_time_utc > signal.detected_at_utc` and `exit_time_utc >= entry_time_utc` for every record.
  - Invalidate and regenerate the fixtures and experiment hashes.

### F-902 — The backtest counts any touch of the entry zone as a fill at the zone mid, a price the bar may never have traded

- **Severity:** HIGH
- **Confidence:** CONFIRMED (code)
- **Classification:** DEFECT
- **Category:** research methodology / fill simulation
- **Component:** 04-03 checkpoint option A (entry_ref = zone mid) as mapped into the Phase 6 simulator (06-01-PLAN)
- **File:** src/backtest/simulator.py
- **Lines:** 448–483, 513–518
- **Invariant:** INV-104; AMB-004, AMB-036
- **Phase/commit:** 04 (df27af6, 04-03 checkpoint auto-selected), 06 (77a0659)
- **Known-prior:** Stage A F-004 / Corrected Rule 18 (generic touch-vs-fill). This planning choice makes it worse: a touch of the far edge counts as a fill at the mid.
- **Evidence:**
  - 04-RESEARCH L319: "entry_ref documented per plan: zone mid or worst-fill edge". 04-03-SUMMARY L76–80: "Auto-selected option A … entry_ref = zone mid".
  - Live places the LIMIT at the zone mid (`placement.py` L133–143).
  - The simulator uses `zone_touched = bar.high >= trade_plan.entry_min_price and bar.low <= trade_plan.entry_max_price` (L449), then `# Zone touched — fill at entry_ref (zone mid)` (L478–483), with `entry_price=entry_ref` (L517).
- **Expected:** The backtest should fill only where the live order would fill. For a LONG limit at the mid, a fill needs `low <= mid − 1 tick` (trade-through, Corrected Rule 18), and the fill price is the limit.
- **Actual:**
  - A LONG bar whose low reaches only `entry_max` (the upper zone edge, above the mid) is recorded as filled at the mid.
  - These are exactly the setups where price turned before reaching the order, which are disproportionately winners.
  - Filled trades also get a better price than the market offered.
- **Reproduction:** Take any fixture with `entry_min < entry_max` and a LONG bar with `entry_mid < low <= entry_max`. `_resolve_entry` returns ENTRY_FILLED at the mid.
- **Impact:** A systematic optimistic bias in fill rate and entry price. This is adverse selection hidden from the research evidence. It persists even after F-901 is fixed.
- **Why tests miss it:** Fixtures were generated from the implementation (`scripts/gen_phase6_fixtures.py`). No test compares the fill rule against the live order price.
- **Remediation:**
  - The simulated fill condition must be derived from the same price the live order uses (mid), with a trade-through ≥ 1 tick.
  - Record `entry_kind TOUCH_NO_FILL` for zone-edge touches.
  - Keep option A for live.

### F-903 — Phase-1 research framed pre-registered numeric acceptance thresholds as an overfitting anti-pattern; this is the planning origin of F-022

- **Severity:** HIGH
- **Confidence:** CONFIRMED (docs)
- **Classification:** DEFECT
- **Category:** research governance
- **Component:** 01-RESEARCH "Don't Hand-Roll" and Pitfall 2 → RESEARCH_PROTOCOL §0 "Numeric-gate reservation" and §4 "Thresholds remain TBD"
- **File:** .planning/phases/01-research-formalization/01-RESEARCH.md
- **Lines:** 226, 237–238 (propagated to docs/research/RESEARCH_PROTOCOL.md L24, L205–213)
- **Invariant:** INV-098, INV-100, INV-101, INV-038
- **Phase/commit:** 01 / 7a7fce9
- **Known-prior:** Stage A F-022 (doc-level, HIGH). This finding records that the plan independently chose the wrong direction and gave it a rationale. That rationale is what later phases (10) inherited.
- **Evidence:**
  - 01-RESEARCH L226: "| Acceptance numbers | Invented thresholds (e.g. 'expectancy > 0.2R') | BACKTEST_SPEC 'thresholds TBD' + interval reporting | Numeric gates before data are overfitting commitments; the spec deliberately defers them |".
  - The resulting protocol L24: "Every numeric threshold in §1–§5 — sample sizes, split ratios, … cost assumptions … — is TBD until exercised on real data". L211: "After ≥3 … families … have produced Validation evidence, then and only then are candidate numerical thresholds proposed".
- **Expected:** Pre-registration is the anti-overfitting tool. Acceptance thresholds, the trial-count penalty and the holdout protocol are frozen before any Validation run (Corrected Rule 31). Only strategy parameter values are left to research.
- **Actual:**
  - The plan inverted the logic, so thresholds are set after the results are seen. The reservation also extends to "cost assumptions" and "split ratios".
  - The auto-mode rationale reads as authoritative to a non-expert user.
- **Reproduction:** Read the cited lines.
- **Impact:** Maximal researcher degrees of freedom at the only gate that stands between research and live money (see F-022). The Phase 10 kill gate then models "passing" as a recorded human decision.
- **Why tests miss it:** Governance, not code.
- **Remediation:**
  - Before the first Validation run, issue protocol v1.1.0 with the numeric gates from Corrected Rule 31.
  - Add a DECISIONS row that records the reversal of the 01-RESEARCH rationale.
  - B2/L1: check that Phase 10 does not bake in the "human decides pass" model.

### F-904 — Phase-6 D-05 dataset splits / walk-forward / single-use holdout were decided but never planned or implemented (orphaned decision)

- **Severity:** MEDIUM
- **Confidence:** CONFIRMED (plans plus grep)
- **Classification:** GAP
- **Category:** research methodology
- **Component:** Phase 6 D-05; src/backtest/experiment.py
- **File:** .planning/phases/06-backtest-simulator-experiment-registry/06-CONTEXT.md
- **Lines:** D-05 (the "Dataset splits dev/val/holdout + walk-forward" sentence)
- **Invariant:** INV-100, INV-038
- **Phase/commit:** 06
- **Known-prior:** none. Not in 06-REVIEW, 06-VERIFICATION ("Deferred items: none"), the v0.3 audit, or P11–P17.
- **Evidence:**
  - D-05: "Dataset splits dev/val/holdout + walk-forward (train → validate → roll) per BACKTEST_SPEC §§7–8".
  - `grep -i "holdout|walk-forward|split"` over 06-0[1-3]-PLAN.md finds no task.
  - `grep -rn "holdout|walk_forward|dataset_split" src` finds nothing in `src/backtest`.
  - The ExperimentRecord carries only `time_range_start/end_utc` and `universe_hash`, with no split role.
- **Expected:** Each experiment record declares its split role (DEVELOPMENT / VALIDATION / HOLDOUT), with split boundaries frozen in the protocol and a guard that rejects a second HOLDOUT evaluation or any HOLDOUT run of a non-preselected candidate (Corrected Rule 31).
- **Actual:** Split discipline exists only as prose. Nothing stops repeated holdout peeking.
- **Reproduction:** grep as above.
- **Impact:** OOS confirmation (required by D-08 / D-04 "no winner without OOS") cannot be evidenced or audited. Combined with F-903, the holdout offers no protection.
- **Why tests miss it:** No requirement ID maps it (BKTS-01..03 do not name splits).
- **Remediation:** Add a split role and boundaries to the experiment identity, a holdout-once registry check, and a protocol amendment fixing the split dates before evaluation.

### F-905 — Funding is never modeled: D-08's funding history backfill is an 8-hour lookback, the backtest hard-codes funding = 0, and the skipped fix (06 WR-03, "cross-phase item") has no owner

- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** GAP
- **Category:** cost realism / orphaned deferral
- **Component:** Phase 2 D-08; Phase 6 D-02; 06-REVIEW-FIX WR-03 (skipped)
- **File:** src/backtest/simulator.py
- **Lines:** 655–656 (also src/data/collector.py L74; 06-REVIEW-FIX.md L300–312)
- **Invariant:** INV-105; AMB-037
- **Phase/commit:** 02 / 06e9c3f; 06 / 77a0659
- **Known-prior:** KNOWN: 06-REVIEW WR-03 (skipped, "Opened as a cross-phase item; no code touched"). Not in P11–P17. Stage A F-021 covers the doc-level sign/interval gap.
- **Evidence:**
  - simulator L655–656: `# Funding: ADDITIVE treatment → 0 for the tracer slice (no funding events).` / `funding = Decimal("0")`.
  - collector L74: `FUNDING_BOOTSTRAP_LOOKBACK_MS = 8 * 60 * 60_000`, the fresh-symbol start (02-REVIEW-FIX: "fresh symbol's adapter start_ms is now_ms - 8h").
  - 02-CONTEXT D-08: "Funding-rate history is backfilled once plus collected ongoing".
  - Phase 6 D-02: "entry fee + exit fee + funding treatment + slippage … apply from run #1".
- **Expected:** Historical funding is backfilled over the research window, and funding_pnl follows Corrected Rule 19 at actual funding timestamps (the per-symbol interval is not assumed to be 8h).
- **Actual:** No funding history, and funding is 0 in every result. The "cross-phase item" was never scheduled.
- **Reproduction:** Read the lines. `grep -in funding .planning/ROADMAP.md` has no P11–P17 hit.
- **Impact:**
  - Net expectancy is overstated for positions held through funding.
  - Once F-901 is fixed and holding spans hours to days, that is 1–3+ funding events per trade. It is material at 0.5% risk with tight stops (F-002).
- **Why tests miss it:** The fixtures contain no funding events.
- **Remediation:**
  - Add a phase, or a P11 sub-item, that backfills `fundingRate` history over the research window (using `fundingInfo` for per-symbol intervals) and applies Corrected Rule 19 in the simulator.
  - Record the funding treatment in `costModelHash`.

### F-906 — Phase-2 D-02 history depth drifted in code (1m 7 days, 1H/4H 30 days instead of 6–12 months / 2 years); 30 days of 4H cannot warm the required EMA200-4H, and no CLI exposes a deeper window

- **Severity:** MEDIUM
- **Confidence:** CONFIRMED (code plus arithmetic)
- **Classification:** DRIFT
- **Category:** data foundation
- **Component:** Phase 2 D-02; src/data/backfill.py
- **File:** src/data/backfill.py
- **Lines:** 549–561, 563–581
- **Invariant:** INV-006, INV-103, INV-109
- **Phase/commit:** 02 / b522b8d
- **Known-prior:** partial. v0.3 tech_debt says "live-network bootstrap never executed", and M4 says there is no Parquet→backtest builder. The depth drift itself is new.
- **Evidence:**
  - D-02: "1H/4H ~2 years back, 1m ~6–12 months back".
  - Code L551–560: "1m: ~7 days back … 1H/4H: ~30 days back", `DEFAULT_BACKFILL_WINDOWS_MS = {"1m": 7*24*60*60_000, "1h": 30*…, "4h": 30*…}`.
  - `features.py` L417–428: `features_valid = all(...)` includes `ema_200[last]`.
  - The 4H context is required by the regime gate (`strategy.py` L113). EMA200 needs 200 bars; 30 days × 6 bars/day = 180 < 200.
  - `backfill_universe` has no CLI caller (only `src/data/backfill.py` references it). 02-VERIFICATION L27 expects it to be called from Python.
- **Expected:** Defaults match D-02, or the deviation is recorded as a decision. The bootstrap is runnable with an explicit depth.
- **Actual:**
  - A default bootstrap yields a 4H context that is WARMUP_INSUFFICIENT on every bar, so every evaluation is NO_TRADE.
  - 1m covers only 7 days, so almost every backtest bar takes the missing-1m SL fallback (F-901).
- **Reproduction:** 30 d × 24 h / 4 h = 180 bars < EMA period 200 → the first valid EMA-200 is at index 199.
- **Impact:** Research (and a paper warm-up drawn from the store) either cannot start, or silently produces 0 setups or all-SL fallback evidence, unless the operator knows to pass an explicit `start_ms`.
- **Why tests miss it:** The tests use recorded pages and fixtures, and the real bootstrap was never run.
- **Remediation:**
  - Align the defaults with D-02 (and ≥ max warm-up + split length).
  - Add a CLI entry with `--start`/`--days`.
  - Make the coverage check assert that warm-up is sufficient per required feature.

### F-907 — The research-universe expansion (10–15 symbols) deferred by Phase-2 D-01 has no owning phase or requirement; the research universe is effectively the live-5 with no point-in-time rule

- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** GAP
- **Category:** research validity / orphaned deferral
- **Component:** Phase 2 D-01 / Deferred Ideas
- **File:** .planning/phases/02-data-foundation/02-CONTEXT.md
- **Lines:** 14, 94
- **Invariant:** INV-100, INV-109
- **Phase/commit:** 02
- **Known-prior:** Stage A F-024 (doc: no point-in-time universe rule). The orphaning is new.
- **Evidence:**
  - L94: "Research-universe expansion (10–15 symbols) … remain scheduled in their own phases/requirements".
  - REQUIREMENTS.md has only REFN-01..05 (none is universe expansion). ROADMAP has no such phase.
  - `src/data/backfill.py` L549 `LIVE_5` is the only universe. 10-RESEARCH L181: "The research universe has no code definition".
  - Phases 6 and 10 nonetheless build dual-universe report sections.
- **Expected:** A scheduled phase or requirement that collects data for a frozen, hashed, point-in-time research universe, including delisted symbols (Corrected Rule 33).
- **Actual:**
  - The claim that the work is "scheduled" is false.
  - Five mega-cap survivors form the whole evidence base. The "research universe" column will be empty or ad hoc.
- **Reproduction:** grep REQUIREMENTS/ROADMAP for "universe".
- **Impact:** Survivorship and small-sample bias in family selection. The BACKTEST_SPEC §10.1 dual-universe check becomes vacuous.
- **Why tests miss it:** Planning gap.
- **Remediation:** Add a requirement and phase (before any Validation run) for a point-in-time research universe with a frozen hash, or record by DECISIONS that V1 research is live-5 only and restate the statistical limits.

### F-908 — Phase-5 portfolio-cap choices: BNB excluded from the correlated cluster (hard-coded, against the research's own mitigation), and caps count filled positions only

- **Severity:** MEDIUM
- **Confidence:** CONFIRMED (cluster) / PROBABLE (open-risk ledger impact depends on the Phase 8/9 callers)
- **Classification:** DEFECT
- **Category:** portfolio risk
- **Component:** Phase 5 D-03; 05-RESEARCH A3; 05-02-PLAN
- **File:** src/risk/portfolio.py
- **Lines:** 26–31
- **Invariant:** INV-063, INV-064, INV-065; AMB-016, AMB-017
- **Phase/commit:** 05 / 4f6d968
- **Known-prior:** Stage A F-014 (doc ambiguity). This plan independently picked a membership that contradicts Corrected Rule 9.
- **Evidence:**
  - D-03: "directionally-aligned BTC/ETH/SOL/XRP counted as one cluster".
  - 05-RESEARCH L310, A3 [ASSUMED]: "mitigate: cluster membership as a registry param (symbol list string), not hard-coded".
  - Code: `CLUSTER_SYMBOLS: frozenset[str] = frozenset({"BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"})`.
  - 05-02-PLAN L69: "position count at max_open_positions yields MAX_POSITIONS_REJECT counting open positions only".
- **Expected** (Corrected Rule 9):
  - All live-5 symbols are one cluster, capped per direction.
  - Open risk = filled positions + working entries + APPROVED-but-unplaced plans, under one lock.
- **Actual:**
  - BNB is outside the cluster, so a BNB long plus a BTC long doubles the aligned correlated exposure (2 × 0.5%). That is the only way to hold two aligned positions.
  - The caps ignore resting 4h LIMIT entries and pending approvals, so two approvals inside one validity window can both pass.
- **Reproduction:** `check_portfolio` with open position BTCUSDT LONG at risk 0.5% and candidate BNBUSDT LONG at 0.5% gives no CLUSTER_CAP_REJECT.
- **Impact:** Correlated drawdown up to 2× the intended cluster budget. Caps can be exceeded when working orders fill together. The aggregate 1% cap still bounds the total.
- **Why tests miss it:** Fixtures encode the chosen membership. No test has a working entry.
- **Remediation:**
  - Move cluster membership to the registry (symbol list, hashed) including BNB.
  - Define the open-risk ledger to include working entries and approved plans.
  - Stage C/B2: check that Phase 8/9 callers pass such a ledger.

### F-909 — Phase-3 seed and Phase-4 tracer parameter values (fixture placeholders) became the baseline parameter sets used downstream, with no recorded rationale; the family sheets still say "value TBD"

- **Severity:** LOW
- **Confidence:** PROBABLE
- **Classification:** IMPROVEMENT
- **Category:** research governance
- **Component:** Phase 3 D-09; 04-01-PLAN "tracer values"; params baseline-v1→v3
- **File:** params/trend-pullback/baseline-v1.toml
- **Lines:** 19–27 (also baseline-v3.toml L23–33)
- **Invariant:** INV-038, INV-034
- **Phase/commit:** 03 / f8ff6e5 (added in feat(03-01)); 04
- **Known-prior:** Stage A F-016 (4h validity) and F-002 (tight stops versus costs). The provenance is new.
- **Evidence:**
  - baseline-v1 header: "Seed parameter set … (Phase 3, plan 03-01)" with `sl_buffer_atr = 0.2`, `minimum_rr = 2.0`, `signal_expiry_hours = 4`, `zone_tolerance_atr = 0.5`.
  - 04-01-PLAN L93: "tracer values: … signal_expiry_hours 4".
  - baseline-v3 (used for paper): "Inherited from baseline-v2 (non-cost params unchanged)".
  - `docs/research/families/trend-pullback.md` L156: "`signal_expiry_hours` … value TBD".
  - 03 D-09: "minimal placeholder expectations".
- **Expected:** Baseline values come from declared ranges-to-explore (Phase 1 Pitfall 2), with a DECISIONS or registry note explaining each choice. Placeholders are marked as placeholders.
- **Actual:** Fixture placeholders silently became the research and paper baseline. This answers the Stage A question "who chose `signal_expiry_hours = 4`": the Phase-3 registry seed.
- **Reproduction:** `git log --diff-filter=A -- params/trend-pullback/baseline-v1.toml` → f8ff6e5.
- **Impact:** Forward paper months (Phase 7) could be spent observing arbitrary parameters. This is methodology only; no profitability judgement is made.
- **Why tests miss it:** Values are hashed, not justified.
- **Remediation:** Add a registry comment field or DECISIONS row per baseline value, or flag the set `PLACEHOLDER` so it cannot be frozen for paper.

### F-910 — The Phase-2 D-12 backup accepted an unencrypted OneDrive-synced folder as "off-host", with "harden later" never scheduled

- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Classification:** GAP
- **Category:** operations / orphaned deferral
- **Component:** Phase 2 D-12; 02-RESEARCH Open Q2; src/ops/backup.py
- **File:** .planning/phases/02-data-foundation/02-RESEARCH.md
- **Lines:** 384–387 (src/ops/backup.py L32–33)
- **Invariant:** INV-115
- **Phase/commit:** 02 / f3a13f4
- **Known-prior:** none. v0.3 tech_debt lists only the Docker/live-PG human steps.
- **Evidence:**
  - "Recommendation: accept OneDrive-synced backup dir as the Phase-2 drill target (documented), harden to true second-host later".
  - "Weekly schedule deferred to later hardening" (02-RESEARCH L234).
  - `grep -i backup ROADMAP.md` hits only Phase 2.
  - INV-115 requires an encrypted off-host copy.
- **Expected:** Before live operation (Phase 9), the backup is encrypted, independent (not a sync mirror, which propagates deletion or corruption), scheduled, and drilled.
- **Actual:** No phase owns the hardening.
- **Reproduction:** grep as above.
- **Impact:**
  - The irrecoverable OI dataset and the operational journal (approvals, orders) depend on a sync folder in the same user account.
  - The data holds no credentials, so the confidentiality impact is low. The main risk is loss.
- **Why tests miss it:** The drill tests restore, not independence or encryption.
- **Remediation:** Add an OPS item before Phase 9 go-live: a scheduled, encrypted, versioned off-host backup plus a periodic drill.

## Open Questions

- **For B2 (07–17):**
  - `partial_fill_fraction = 0.5` originates in `scripts/gen_phase6_fixtures.py` (the Phase-6 fixture COST_MODEL). baseline-v3 (07.1) adopted it explicitly "to dodge the whole-number-trap" (hash normalization), not for any trading reason. Please judge the 07.1 decision (Stage A F-006).
  - Does the Phase 7 paper loop reuse `simulator` entry/exit semantics? If it does, F-901/F-902 carry into paper.
  - Does the paper warm-up read from the Parquet store with the 30-day default (F-906)?
  - Does Phase 8/9 pass an open-risk ledger that includes working entries and approved plans (F-908)?
  - Does Phase 10 hard-code "passing = human decision" (F-903)?
- **For Stage C (L3 business invariants):**
  - Verify F-901 independently with a multi-bar fixture.
  - Check whether any caller builds `open_positions` from reconciled positions only.
  - Check that the live `workingType=MARK_PRICE` choice (A2 open question 4) versus the backtest's last-price 1m candles is recorded as a parity gap. It becomes material once F-901 is fixed.
- **Stage A question "Phase 5 D-05 cluster/aggregate":** answered. The cluster is defined in Phase 5 **D-03** as {BTC, ETH, SOL, XRP}, excluding BNB (F-908).
- **Stage A question "who chose signal_expiry_hours = 4 / partial_fill_fraction = 0.5":** answered in F-909 and the first B2 bullet above.
- **Not inspected:** the Phase 1 family sheets beyond grep (Stage A already reviewed their content), 0x-PATTERNS files, and the VALIDATION files (Nyquist bookkeeping).

---

## Appendix: Decision register (phases 01–06)

Verdicts: SOUND / QUESTIONABLE / WRONG / RISKY-DEFERRAL. "auto" means an auto-picked recommended default.

| Phase / ID | What was chosen | Alternatives | Verdict | Reasoning (trading reality, corrected rules) |
|---|---|---|---|---|
| 01 D-01/D-02 | Separate frozen `RESEARCH_PROTOCOL.md`; not in the living doc, not planning-only | section in the research doc; .planning artifact | SOUND | A freezable contract with a one-way firewall is standard pre-registration practice |
| 01 D-03/D-04 | 7-slot template per concept + family sheet | freeform prose | SOUND | Makes the families comparable, and bias analysis is mandatory |
| 01 D-05/D-06 | C1–C7 fixed by canonical edits + DECISIONS rows | leave the docs | SOUND | Auditable |
| 01 D-07 | Registry loader + CI gate, fail-closed | convention only | SOUND (caveat) | The runtime loader is the real gate. The CI workflow never runs (no remote; branch protection is `human_needed` per the v0.3 tech_debt) |
| 01 D-08 | V1 family TBD | pick early | SOUND | |
| 01 RESEARCH "Don't hand-roll: acceptance numbers" + protocol "numeric-gate reservation" | Thresholds TBD until after Validation evidence | pre-registered thresholds | WRONG | The logic is inverted. Pre-registration prevents overfitting → F-903 (F-022) |
| 01 RESEARCH Pitfall 2 | Parameter values stay in the registry, not the protocol | freeze values | SOUND | Correct for parameters only |
| 01 Open Q1 (auto) | Freeze as the last plan | freeze inside the batch | SOUND | |
| 01 research-universe transcription | "10–15 liquid symbols" | point-in-time rule | QUESTIONABLE | Stage A F-024; worsened by F-907 |
| 01 kill-gate transcription | Disjunctive shortfall list (later corrected by D030, v1.0.1) | D013 wording | SOUND after D030 | The family-sheet wording is still wrong (Stage A F-025; B2 checks Phase 10) |
| 02 D-01 (user delegated) | Live-5 bootstrap first; 10–15 research slice deferred | full slice; hybrid | RISKY-DEFERRAL | Deferral is fine, but no phase owns it → F-907 |
| 02 D-02 | 1H/4H ~2y, 1m ~6–12mo | full history | SOUND (decision) / DRIFT (code) | 2 years is roughly one regime cycle, which is thin but acceptable to start. The code defaults are 7d/30d → F-906 |
| 02 D-03 | Official SDK klines behind an adapter | TradingView / vendor | SOUND | Matches the A2 exchange facts |
| 02 D-04/D-05 | Hive Parquet immutable raw; PG for operational state | PG candles | SOUND | |
| 02 D-06 | UTC storage; Asia/Ho_Chi_Minh display | — | SOUND | |
| 02 D-07 | OI poll every 5 min, from day 1 | sub-minute; hist-only | SOUND | Correctly notes the `openInterestHist` 1-month window (A2 fact) |
| 02 D-08 | Funding backfilled once + ongoing | — | SOUND (decision) / DRIFT | The code backfills 8h only; the backtest uses funding 0 → F-905. Research assumed an 8h interval (A2: intervals vary per symbol) |
| 02 D-09/D-10/D-11 | Flag-never-fabricate; fail-closed structural QA; coverage CLI + view | interpolate | SOUND | |
| 02 D-12 | Weekly backup; OneDrive as off-host; harden later | second host; encrypted | RISKY-DEFERRAL | INV-115 needs encrypted off-host; orphaned → F-910 |
| 02 discretion | Sequential bootstrap, weight-aware pacing | parallel | SOUND | |
| 03 D-01/D-02 | Frozen dataclass domain; ORM mirror + mappers | ORM/Pydantic as domain | SOUND | |
| 03 D-03 | Content-hash IDs; child IDs from the signal hash | sequences | SOUND (caveat) | Binance enforces client-ID uniqueness only among open orders; a durable dedup is still needed (Corrected Rule 28; Stage C) |
| 03 D-04/D-05/D-06 | TOML registry, SHA-256 canonical, loader raise + CI; strategy/runtime split | DB registry; warn | SOUND | |
| 03 D-07/D-08 | Golden triples + 4 determinism suites | — | SOUND (limited) | The suites cover the strategy path, not the simulator fill/exit path, so they missed F-901 |
| 03 D-09 | Placeholder expectations; seed param set | — | QUESTIONABLE | The seed values became the baseline → F-909 |
| 03 D-10/D-11/D-12 | Enums; explicit status; Decimal/UTC | strings; nullable inference | SOUND | |
| 04 D-01/D-02/D-04 | Minimal EMA/ATR/swing/zone; closed candles; gaps invalid | full library | SOUND | |
| 04 D-03 | Per-feature validity; EMA200-4H required | silent NaN | SOUND | But see F-906 (the default data depth cannot satisfy it) |
| 04 D-05/D-06/D-07/D-10 | Tracer-first; enum promotion; pure evaluate; pure core | — | SOUND | |
| 04 D-08 | TP1 at minimum_rr, TP2 extension, RR gate | minimal plan | WRONG → fixed | 04-REVIEW CR-03: the RR gate was vacuous; TP1 is now structure-derived |
| 04 D-09 | Quantization deferred to risk | planner rounds | SOUND | |
| 04-03 checkpoint (auto option A) | entry_ref = zone mid; TP2 = entry_ref + 2·minimum_rr·risk | worst-fill edge; TP2 at next structure | SOUND for live / WRONG as mapped into the backtest | The live limit is at the mid, so the worst live fill is the mid. The backtest fills a touch at the mid → F-902. The TP2 multiple is arbitrary and never simulated (F-901) |
| 04-03 fingerprint / timeframe spelling | Fixed key list; "1h" | composite string | SOUND | |
| 04 tracer values (signal_expiry_hours 4, sl_buffer 0.2 ATR, …) | Tracer numbers | researched ranges | QUESTIONABLE | → F-909; Stage A F-016, F-002 |
| 05 D-01 (auto) | risk = equity × risk_rate ÷ (|entry_ref − SL| + modeled costs); risk_rate 0.5% | fixed fraction | SOUND formula / cost units KNOWN P11 | Stage A F-001; the zone mid is correct for live (see 04-03) |
| 05 D-02 (auto) | Floor → min-qty → notional → 60% realized-risk; no round-up | planner rounds | SOUND | Matches Corrected Rule 4 |
| 05 D-03 caps (auto) | max 2 positions, 1% aggregate, cluster = {BTC, ETH, SOL, XRP} aligned at 0.5% | registry list; all live-5 | WRONG (membership) / QUESTIONABLE (ledger) | → F-908; Corrected Rule 9 |
| 05 D-03 daily loss | 0.5% warn / 1% stop; the day boundary and accumulation deferred to "Phase 7/8" | UTC-day rule | RISKY-DEFERRAL | KNOWN P12 (daily realized loss from Binance); the boundary is still undefined (Stage A F-013, Corrected Rule 10) |
| 05 D-04 (auto) | Strict fail-closed; TTL 3600 s constraint snapshot | best effort | SOUND | CR-02 (TTL fail-open when None) was fixed |
| 05 D-05 | Pure `src/risk/`, fine-grained reason codes | shared math | SOUND | |
| 06 D-01 (auto) | 1m intrabar, SL-first fallback when 1m missing | setup-candle only | SOUND policy / WRONG implementation | Resolution runs on the signal bar (look-ahead). The fallback fires for every missing-1m bar, not only both-touched bars → F-901 |
| 06-01-PLAN entry semantics | Fill when the strategy-bar range touches the zone, at the mid, on the same bar | next-bar trade-through | WRONG | → F-901, F-902 (Corrected Rule 18) |
| 06 D-02 (auto) | Costs from run 1, identical risk parity | local estimates | SOUND intent / DRIFT | Funding = 0 (F-905); slippage/fee units KNOWN P11 (06 WR-13 skipped) |
| 06 partial-fill concept | `partial_fill_fraction` applied to qty; fixture value 0.5 | 1.0 | QUESTIONABLE | Stage A F-006; the value adoption is in 07.1 (B2) |
| 06 D-03 | Six-field identity; Parquet canonical | PG only | SOUND | CR-06 (ID omits run_type) was fixed |
| 06 D-04 | Uncertainty-first report, bootstrap, plateau, baselines, dual universe | headline expectancy | SOUND | Implemented; the dual-universe view is vacuous without F-907 |
| 06 D-05 splits / walk-forward | Declared | — | RISKY-DEFERRAL (orphaned) | Never planned or implemented → F-904 |
| 06 D-05 purity / VectorBT exploratory | Pure `src/backtest/` | vectorized | SOUND | |
| 06 REVIEW-FIX skipped CR-04 | "Design call needed", no owner | fix now | RISKY-DEFERRAL | → F-901 |
| 06 REVIEW-FIX skipped WR-03 | Funding "cross-phase item", no owner | — | RISKY-DEFERRAL | → F-905 |
| 06 REVIEW-FIX skipped WR-13 | Slippage units | — | KNOWN P11 | Covered by the ROADMAP phase 11 goal |
| 06 REVIEW-FIX WR-02 | TP2 not modeled, documented as a limitation | model the ladder | QUESTIONABLE | The backtest exits 100% at TP1 while live uses a TP1/TP2 ladder, so the results are not parity-true (part of F-901) |
