# 16-37 REEFUSDT technical diagnostic, truncated window: the 33 errors coincide with 33 open positions at the cut

date: 2026-10-14. Follow-up of `evidence/16-37-reef-diagnostic.md` (FundingCoverageError in 33 of 48 points), run under the reviewer's scope of 2026-10-14 (read-only, REEF-only, 48 registered points, S0, Development data only, no Validation or Holdout, no ExperimentRecord, no `holdout_consumed.json`, no code, gap or semantics change, no 12-symbol run, no PnL or any ranking figure reported). This is evidence for a decision; nothing is decided or fixed by it.

## Boundary rule checked before the run (reviewer item 2)
- `build_case_input_data` accepts an `end_utc` only at 00:00:00 UTC of a whole UTC day (`CaseInputRangeError: end_utc must be at 00:00:00 UTC (whole UTC days only)`). Tried: `2025-01-22T08:00Z` and `2025-01-22T09:00Z` were refused by the builder; `2025-01-22T00:00Z` was accepted with 0 gaps (data window end `2025-01-22T00:00:00Z`, last strategy and context bar close `2025-01-21T23:59:59.999Z`, last funding row `2025-01-21T20:00Z`, 626 funding rows, `allowed_gaps = 0`). `2025-01-23T00:00Z` is the whole-day end that contains the missing funding after 08:00Z (the configuration that failed).
- So the only truncated window that needs no change of builder or engine semantics ends at `2025-01-22T00:00Z`, eight hours before the last REEFUSDT funding instant. Editing `data_window.end_utc` by hand to 08:00Z or 09:00Z would bypass the builder's whole-day validation; it was NOT done (possible change of semantics; the reviewer's stop condition).

## Method (as run)
- Script: `evidence/16-37-reef-diagnostic-cut-script.txt` (sha256 `56e182d4c0d6cec0ba4c12acb2cf3d550daa514175ae7788d0a987a5c3c0b951`, throwaway). Same preconditions as before, checked at every run: S0 sha256 `4307eec74feeab04081b872866895f70568f1d289b8a249fc7de702e71e11d3f`, all 1,077 REEFUSDT files re-hashed equal to the verified inventory (listing sha256 `b9b8426a31a2821d27d07fc49457cabcdc7cd887910b8185269de3bfa5982b34`). Window `[2024-10-03T00:00Z, 2025-01-22T00:00Z)`, equity 600, risk_rate 0.005, no terminal declaration (the builder reports 0 gaps). One process per grid point, 48 points. Output is a whitelist: ids, END_OF_DATA entry/exit timestamps and direction, pending-at-data-end entries, counters.
- `END_OF_DATA` here is the end of the SIMULATION window at the cut. It is not the contract's settlement (2025-01-22 09:00 UTC) and not a Binance event.

## Result
- All 48 points completed without error (`allowed_gaps_used = 0`, `data_window.end_utc = 2025-01-22T00:00:00Z` on every point). No point has a pending entry at data end (`pending_at_data_end_count = 0`, 48 of 48).
- **33 points have exactly one trade marked END_OF_DATA, always a SHORT, still open at the cut; 15 points have none.** No point has more than one.
- **The 33 points are exactly the 33 points that raised `FundingCoverageError` in the full Development window; the 15 are exactly the 15 that completed clean there.** No point is in one set and not the other (checked by set difference both ways).

| Entry time of the open SHORT (UTC) | Points |
|---|---|
| 2024-12-10T00:34:59.999Z | b07, b08 (2) |
| 2025-01-19T19:06:59.999Z | a01-a08 (8) |
| 2025-01-20T06:55:59.999Z | a09, a10, a11, a12, a14, a16 (6) |
| 2025-01-20T07:02:59.999Z | a13, c01-c16 (17) |
| none (15 points) | a15, b01-b06, b09-b16 |

All 33 positions were opened at least about 1.7 days before the cut, so none of them is an entry after the 08:30 UTC "no new positions" time of the announcement; the eight hours from 00:00Z to 08:00Z of 2025-01-22 are not covered by this run.

## What this supports and what it does not
- Supports (inference, not proof): in each of the 33 failing points a REEFUSDT position was already open before the final day and was still open at 2025-01-22T00:00Z. The engine allows one active entity per symbol and the cut run and the full run are the same simulation up to the cut, so the position that needed funding coverage at 2025-01-22T07:59:59.999Z is, with the simplest reading, the same position. The exact one-to-one match of the two 33-point sets is consistent with this and does not contradict the 33 errors.
- Does NOT establish: that the position is still open at 08:00Z (it may have closed between 00:00Z and 08:00Z, and another may have opened), when it would have closed, or what the contract's settlement would have done to it. Those are the eight hours the builder's whole-day rule hides. By the reviewer's item 5, a result that still cannot answer the question is reported and the work stops.
- Scope: REEFUSDT alone, S0, Development data, the 48 registered points, equity 600. A 12-symbol portfolio could open fewer or different REEFUSDT positions; nothing is inferred either way.

## State after this evidence
Manifest NOT frozen; REEFUSDT NOT removed; window NOT shortened; no forced-close or funding-coverage change made; 12-symbol portfolio NOT run. The error is NOT resolved: a successful truncated run does not remove the failure of the registered window. Next step is the reviewer's/user's decision (options in `evidence/16-37-reef-diagnostic.md`, last section, and in `evidence/16-37-data-snapshot.md` section 3).
