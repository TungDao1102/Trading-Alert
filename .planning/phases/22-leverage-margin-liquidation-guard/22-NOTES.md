# Phase 22 notes (carried from Phase 19)

Input for `/gsd-discuss-phase 22` and the planner. Not a decision record. Written 2026-10-20 from `.planning/phases/19-execution-plan-binding-price-check/19-16-SUMMARY.md`.

- **Margin type and leverage are inputs that unblock take-profit placement.** `attach_protectives_to_fill` (`src/execution/manager.py`) places TP1 and TP2 only when `snapshot_is_valid_for_live` holds (D-20). Until margin type and leverage have a live source (this phase) and equity (Phase 21), the snapshot stays INCOMPLETE and every TP placement ends as `TP_UNAVAILABLE` (stop kept, SAFE_MODE, critical alert). That is the intended fail-closed result in Phase 19.
- When this phase delivers them, add a test that a COMPLETE snapshot built from live margin type and leverage (with Phase 21's equity) passes `snapshot_is_valid_for_live`, so the Demo rehearsal can stop reporting the known gap (attestation item 1 NOT_OBSERVED).
- Hedge Mode is unsupported in V1 (draft D055 point 4): position-mode detection must keep refusing it.
