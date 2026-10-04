# Phase 14: Backtest Simulator Causality Rewrite - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-10-04
**Phase:** 14-backtest-causality-rewrite
**Mode:** `--auto` (no user prompts; the recommended option was chosen for every question)
**Areas discussed:** Plan and position lifecycle, Fill rule, Exits and TP ladder, Funding, Point-in-time state and ledger, R denominator and experiment record, Trade-record invariants and fixtures

---

[auto] Selected all gray areas: Plan and position lifecycle, Fill rule, Exits and TP ladder, Funding, Point-in-time state and ledger, R denominator and experiment record, Trade-record invariants and fixtures.

## Plan and position lifecycle

[auto] Plan and position lifecycle — Q: "How does a plan become a position across bars?" → Selected: "Event loop; plan active from bar N+1, entry checked until expiry, position carried to SL/TP2/data end" (recommended default, audit F-901)

| Option | Description | Selected |
|--------|-------------|----------|
| Cross-bar event loop | Plan active from N+1, entry per bar until expiry, position carried | ✓ |
| Keep per-bar function, shift fill by one bar | Smaller change, still cannot hold positions or expire correctly | |

[auto] Plan and position lifecycle — Q: "How is protocol v1.1.0 (frozen) handled?" → Selected: "Amend by new version per D032/D043, add `simulator_semantics_version` to identity" (recommended default)

[auto] Plan and position lifecycle — Q: "What happens to positions open at data end?" → Selected: "Close at last mark price as END_OF_DATA, flagged and reported separately; no invented time stop" (recommended default)

[auto] Plan and position lifecycle — Q: "Which clock judges entry expiry (G3)?" → Selected: "Simulated bar time" (only option that satisfies the roadmap criterion)

## Fill rule

[auto] Fill rule — Q: "What price and condition fill a limit entry?" → Selected: "Zone mid as limit; trade-through of at least one tick on trade-price 1m; fill at limit price" (recommended default, audit F-902)

| Option | Description | Selected |
|--------|-------------|----------|
| Trade-through ≥ 1 tick at zone mid | Matches live order price, conservative | ✓ |
| Touch of zone edge | Original behavior, optimistic | |
| Fill at bar open on gap | Price improvement, less conservative | |

## Exits and TP ladder

[auto] Exits — Q: "Which price series triggers SL/TP?" → Selected: "Mark-price 1m klines (D037)" (decided earlier)

[auto] Exits — Q: "How is the TP1/TP2 ladder modeled?" → Selected: "Mirror live exactly; read split and post-TP1 stop rule from live code and spec; checkpoint if absent" (recommended default, audit F-102 option A)

[auto] Exits — Q: "Tie-break inside one 1m bar?" → Selected: "Stop-first, with explicit fallback flag for missing coverage" (recommended default)

[auto] Exits — Q: "How does the simulator read 1m data?" → Selected: "One continuous sorted series per symbol for trade and mark" (recommended default)

## Funding

[auto] Funding — Q: "Sign convention and timing?" → Selected: "`-sign(position) x qty x markPrice(fundingTime) x rate` at each actual fundingTime with `entry_time <= t < exit_time`; in PnL and R, not sizing" (recommended default, audit F-021)

[auto] Funding — Q: "Missing funding coverage?" → Selected: "Fail closed unless explicit recorded allow-gaps" (recommended default, mirrors Phase 13 D-19)

[auto] Funding — Q: "Is funding part of experiment identity?" → Selected: "Yes, joins `cost_model_hash` inputs" (recommended default, audit F-905)

## Point-in-time state and ledger

[auto] Ledger — Q: "How do equity, daily loss and positions evolve?" → Selected: "Simulated ledger; book exits and fills first, then update ledger, then evaluate new signals; resting entries count toward gates" (recommended default, audit F-305, D035)

[auto] Ledger — Q: "Which constraint metadata applies?" → Selected: "Versioned metadata with `observed_at <= bar close`; no wall-clock TTL in historical mode" (recommended default)

## R denominator and experiment record

[auto] R denominator — Q: "Which denominator do backtest and live share?" → Selected: "Sizing `realized_risk` scaled by filled/planned quantity, one function for all normalizers" (recommended default, audit F-204)

[auto] Regime and plateau — Q: "Plateau claim in this phase?" → Selected: "No; emit regime slice only, plateau stays BKTS-03" (recommended default)

[auto] ExperimentRecord — Q: "Free-form summary or typed fields?" → Selected: "Typed validated fields incl. NO_TRADE counts, tie-break, timeframe, code version, split role/boundaries" (recommended default, audit F-118, F-904 identity part)

## Trade-record invariants and fixtures

[auto] Invariants — Q: "Warn or raise on temporal violations?" → Selected: "Raise; validator runs in simulator and at every normalizer boundary" (recommended default, audit F-804)

[auto] Fixtures — Q: "Where do golden expected outputs come from?" → Selected: "Hand-derived sidecar per case, 1m data only from bar N+1 onward, legacy fixtures relabeled regression snapshots, one regeneration inventory in DECISIONS" (recommended default, audit F-602, F-805, F-608)

---

## Claude's Discretion

- Module split of the rewritten simulator and all internal names.
- New case-input schema layout and fixture folder names.
- Field name for the shared R denominator and the validator's exception type.

## Deferred Ideas

- Parameter-plateau analysis and sweep runner (BKTS-03).
- Holdout-once enforcement code (Phase 26).
- Trend-pullback geometry and confirmed pivots (Phase 15).
- Maker entry study and partial-fill sensitivity (D038 follow-up).
- Live TP-ladder changes if live and spec disagree (checkpoint in planning).
