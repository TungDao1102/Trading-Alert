# Phase 15: Strategy Geometry Correction - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-10-06
**Phase:** 15-strategy-geometry-correction
**Mode:** `--auto` (no questions asked; recommended option chosen per area)
**Areas discussed:** Confirmed pivots, Trend-pullback stop placement, Minimum stop distance, Families B/C vs sheets, Parameter rationale and versioning, Tests and readiness

---

## Confirmed pivots

[auto] Confirmed pivots — Q: "What replaces the trailing window that includes the evaluated bar?" → Selected: "Fractal pivot confirmed at t+R, most recent inside swing_lookback" (recommended default, matches sheet section 5)

| Option | Description | Selected |
|--------|-------------|----------|
| Fractal pivot (left L, right R), confirmed at t+R | Matches the sheet; new keys pivot_left_bars / pivot_right_bars | ✓ |
| Trailing window over bars i-N..i-1 | Smaller change, still not a pivot, not what the sheet says | |
| Keep trailing window | Leaves F-301 open | |

[auto] Pivot widths — Q: "Default L and R?" → Selected: "3 / 3, PROPOSED, user ratifies in checkpoint" (recommended default)

## Trend-pullback stop placement

[auto] Stop — Q: "Where does the stop go relative to the entry zone?" → Selected: "Outer zone edge minus sl_buffer_atr * ATR, with hard invariant SL outside zone else NO_TRADE for all families" (recommended default)

| Option | Description | Selected |
|--------|-------------|----------|
| Buffer from outer zone edge + invariant | Stop always outside the whole zone | ✓ |
| Buffer from the pivot (current) | 1/3 of zone beyond stop | |
| Shrink zone to fit stop | Changes entry semantics and Phase 12 entry_ref | |

[auto] Signal bar already through the stop → Selected: "NO_TRADE" (recommended default)

## Minimum stop distance

[auto] Min stop — Q: "Where is the minimum ATR distance enforced?" → Selected: "Planner check with new optional key min_stop_atr (PROPOSED 0.5); Phase 12 money guards stay the binding filter" (recommended default)

## Families B/C vs sheets

[auto] Family B stop → Selected: "Keep code stop, record deviation (sheet S3 gives RR below 1 against measured-move TP)" (recommended default)
[auto] Family B and A targets → Selected: "Keep structure-derived TP1, record deviation from T1 (CR-03)" (recommended default)
[auto] Family C target → Selected: "Align code to T-mid; T-opposite becomes a later named variant" (recommended default)
[auto] B/C rejection volume → Selected: "Measure and report to the user, never loosen to rescue volume" (recommended default)

## Parameter rationale and versioning

[auto] Versioning → Selected: "baseline-v6 + strategy_version v5.0.0 per changed family, old sets byte-identical" (recommended default)
[auto] Rationale → Selected: "Machine-checked per-value rationale; PLACEHOLDER flag blocks paper freeze; no tuning from results" (recommended default)

## Tests and readiness

[auto] Tests → Selected: "Hand-derived sidecars, p9 regression, property test of the SL-outside-zone invariant" (recommended default)
[auto] Criterion 4 → Selected: "Readiness check plus real-data smoke, not the research run; protocol bump only if the planner finds one is needed" (recommended default)

## Claude's Discretion

Pivot module placement, reason-code names, rationale record format, location of the geometry audit table.

## Deferred Ideas

Family C T-opposite and other sheet variants, regime and pullback alternatives, live TP1 split (F-103), incremental feature series, freezing sheets.
