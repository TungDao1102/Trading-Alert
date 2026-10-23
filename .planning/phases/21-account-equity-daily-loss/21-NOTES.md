# Phase 21 notes (carried from Phase 19)

Input for `/gsd-discuss-phase 21` and the planner. Not a decision record. Written 2026-10-20 from `.planning/phases/19-execution-plan-binding-price-check/19-16-SUMMARY.md`.

- **Equity is one of the inputs that unblocks take-profit placement.** `attach_protectives_to_fill` (`src/execution/manager.py`) places TP1 and TP2 only when `snapshot_is_valid_for_live` holds for the plan's constraint snapshot (D-20). Until margin type, leverage and equity have a live source (this phase and Phase 22), the snapshot stays INCOMPLETE and every TP placement ends as `TP_UNAVAILABLE` (stop kept, SAFE_MODE, critical alert). That is the intended fail-closed result in Phase 19, not a defect.
- When this phase delivers equity, add a test that a COMPLETE snapshot built from it passes `snapshot_is_valid_for_live` (together with Phase 22's inputs), so the Demo rehearsal can stop reporting the known gap (attestation item 1).
- A stale but complete snapshot is re-sized with live exchangeInfo filters before TP placement; an incomplete one is refused. Do not feed that path a placeholder equity.

## Demo income evidence of 2026-10-23 (demo-observed, not mainnet)

- `GET /fapi/v1/income` returned one COMMISSION row (-0.02619484 USDT) after a trade in the same probe session; on 2026-10-22 it returned 0 rows in four tries. Row fields: `asset`, `income`, `income_type`, `info`, `symbol`, `time_ms`, `trade_id`, `tran_id`. No FUNDING_FEE and no REALIZED_PNL row has been seen, so the funding source is still unverified; this does not answer owner item O-2. Evidence: `.planning/phases/19-execution-plan-binding-price-check/evidence/demo-probe-EVIDENCE-20261023T140731Z.json`, summary in `19-OWNER-GAPS.md` section 2b.
- Demo minimum notional is 50 USDT for a non-reduce-only order (-4164); account leverage x20; a reduce-only order or stop above the position is clipped to the position. Phase 21 tests use recorded payloads and fakes; none of this changes a Phase 21 plan.
