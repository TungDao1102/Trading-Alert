# Phase 21 notes (carried from Phase 19)

Input for `/gsd-discuss-phase 21` and the planner. Not a decision record. Written 2026-10-20 from `.planning/phases/19-execution-plan-binding-price-check/19-16-SUMMARY.md`.

- **Equity is one of the inputs that unblocks take-profit placement.** `attach_protectives_to_fill` (`src/execution/manager.py`) places TP1 and TP2 only when `snapshot_is_valid_for_live` holds for the plan's constraint snapshot (D-20). Until margin type, leverage and equity have a live source (this phase and Phase 22), the snapshot stays INCOMPLETE and every TP placement ends as `TP_UNAVAILABLE` (stop kept, SAFE_MODE, critical alert). That is the intended fail-closed result in Phase 19, not a defect.
- When this phase delivers equity, add a test that a COMPLETE snapshot built from it passes `snapshot_is_valid_for_live` (together with Phase 22's inputs), so the Demo rehearsal can stop reporting the known gap (attestation item 1).
- A stale but complete snapshot is re-sized with live exchangeInfo filters before TP placement; an incomplete one is refused. Do not feed that path a placeholder equity.
