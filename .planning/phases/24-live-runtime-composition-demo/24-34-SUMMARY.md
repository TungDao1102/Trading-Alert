---
phase: 24-live-runtime-composition-demo
plan: 34
subsystem: execution
tags: [reconcile, unknown-entry, protection-coordinator, cancel-lag, g4-034, g2-019, phase-24]

requires:
  - phase: 24-live-runtime-composition-demo
    provides: "24-20 reconcile composition (src/live/reconcile.py); 24-21 algo_cancel_query_lag fake and sweeper open-list rule"
provides:
  - "UnknownEntryResolver(on_resolved=...) and ProtectionCoordinator.note_entry_resolved(plan_hash, resolution)"
  - "UNKNOWN_EXIT_EVIDENCE rows carry probe_count next to evidence_source and observed_at_utc (G4-034)"
  - "coordinator FLAT sweep reads a leg absent from the open-algo list as gone (D-34)"
  - "G2-019 proven through the composed reconcile loop (D-35)"
affects: [24-27, 25]

key-files:
  created:
    - tests/test_live_unknown_entry_notify.py
    - tests/test_protection_cancel_lag.py
    - tests/test_live_reconcile_divergences.py
  modified:
    - src/execution/intent_recovery.py
    - src/execution/protection.py

key-decisions:
  - "note_entry_resolved reuses the existing ENTRY_ENDED_NO_FILL state and reason (no new state, edge or reason), so protection_rebuild and the PROTECTION transition table are unchanged; the why is a separate PROTECTION_ENTRY_RECONCILED_ABSENT note."
  - "Only AWAITING_FILL and ENTRY_UNRESOLVED plans move; a plan with a fill or position is never changed by an absence verdict (returns False, no row)."
  - "The resolver callback is best effort: the close is already durable, a failing listener changes nothing."
  - "probe_count is a string number in the existing exit-evidence payload: for REJECTED the consecutive clean not-found probes, for ACKED the probes of the sequence including the one that found the order."
  - "The coordinator cancel fix lives in ProtectionCoordinator._sweep (protection.py), not in manager.cancel_untriggered_protectives (not in this plan's files): a STILL_OPEN leg is re-checked once against snapshot_open_algo_orders and corrected to GONE_NOT_CANCELED."

requirements-completed: [EXEC-02, EXEC-03]  # not marked in REQUIREMENTS: the orchestrator owns that file

plan_head_before: e60011eeb21a47429b0f611d0334eb2cbe2b7275
plan_head_after: bef9d8e9e0dfa2a65860e5667c362fb8de95c0d9
actuals:
  tokens: 22000
  tasks: 3
  commits: 3
status: complete
completed: 2026-11-01
---

# Phase 24 Plan 34: Reconcile follow-ups the composition makes reachable Summary

**A RECONCILED_ABSENT close now reaches the protection coordinator in the same call, every exit from UNKNOWN names its probe count, the coordinator's FLAT sweep no longer re-cancels legs that the open-algo list already omits, and G2-019 is proven through the composed loop.**

## Accomplishments

### Task 1 (tracer) - RECONCILED_ABSENT reaches the coordinator at once (D-35, G4-034)

- `UnknownEntryResolver` takes `on_resolved: Callable[[str, str], None] | None` (`EntryResolvedCallback`). After `finalize_reconciled_resolution` succeeds it calls `on_resolved(plan_hash, RESOLUTION_RECONCILED_ABSENT)`. Without the callback nothing changes (existing tests green); a raising callback is swallowed, the close stays.
- `ProtectionCoordinator.note_entry_resolved(plan_hash, resolution) -> bool`: for a plan in AWAITING_FILL or ENTRY_UNRESOLVED it takes the ordinary transition to ENTRY_ENDED_NO_FILL (reason `ENTRY_ENDED_NO_FILL`, `entry_terminal_at` set), then journals one `PROTECTION_ENTRY_RECONCILED_ABSENT` note. Unknown plan, another resolution, or a plan past a fill: False, no row. Nothing is sent, cancelled or closed; SAFE_MODE is untouched.
- G4-034: the exit-evidence row of the resolver (REJECTED and ACKED) gets `probe_count`; the REST source and the injected time (`observed_at_utc`) were already there. The D080 rule is unchanged: fewer probes than configured, or a probe error that restarts the count, closes nothing (tests assert both).
- Plan 24-27 binds `on_resolved` to `coordinator.note_entry_resolved`; the test binds it the same way.

### Task 2 - cancel success under the Demo lag (D-34)

`ProtectionCoordinator._sweep` re-checks a leg verified STILL_OPEN against one fresh `snapshot_open_algo_orders` read; an id absent from a successfully read list counts as gone (GONE_NOT_CANCELED). An unreadable or non-list answer, or a leg still listed, keeps the old STILL_OPEN result and the `PROTECTION_SWEEP_UNVERIFIED` retry. With the lagging fake: FLAT, three cancels, no unverified row, no second cancel on later steps. `git diff --numstat` for protection.py across the plan: small (about 80 added lines including docstrings).

### Task 3 - G2-019 through the composed loop (D-35)

No gap found; both behaviours already worked, so no library change:

- two exchange rows with the same system entry id: the tick reports `DUPLICATE_EXCHANGE_ID`, journals it in the tick counts, enters SAFE_MODE with that reason and the alert (`DIVERGENCE` / `DUPLICATE_EXCHANGE_ID`) is delivered; nothing is cancelled or placed.
- an orphan stop whose cancel is refused by the REST gate (`RateLimitPauseActive`): one `SWEEP_SKIPPED` row with symbol, algo id and `cancel_failed: RateLimitPauseActive`, no refusal text, the leg still rests, no retry inside the tick.

## Verification

- `uv run pytest -m "not docker"` on: the three new modules, test_intent_recovery, test_intent_recovery_unknown_entry, test_protection_unknown_entry, test_protection_router_rig, test_protection_sweep_spill, all `tests/test_protection*.py`, test_reconcile_compare_v2, test_live_reconcile_wiring, test_phase19_gate, test_phase22_gate, test_agents_md, test_execution_secret_posture, test_transitions: all pass.
- `uv run ruff check src` and scoped `ruff format --check`: clean. `uv run mypy src`: no issues in 287 files.
- `git diff --exit-code -- pyproject.toml uv.lock`: clean (no package added).
- `src/execution/intent_recovery.py` and `protection.py` stay CRLF (edited in place, no whole-file rewrite).
- Not run: `tests/test_intent_recovery_pg.py` (needs TEST_DATABASE_URL, forbidden for this run).
- Phase 22 gate: no pin on the touched lines; `liquidation_watch` default None is unaffected. No pin was changed.

## Deviations from Plan

None - plan executed as written. Two notes:

- The "D-34 cancel check" is implemented in `ProtectionCoordinator._sweep` rather than in `manager.cancel_untriggered_protectives`, because manager.py is not in the plan's file list; the manager's own `cancel_unverified` journal row for such a leg still says STILL_OPEN (audit truth of that moment), the coordinator's verdict map is what changes.
- The per-plan ledger file in the git dir could not be written by the Write tool (outside the worktree path); `plan_head_before` is the known base e60011ee.

## Known Stubs

None.

## Threat Flags

None. T-24-86 (probe-count rule unchanged, tested), T-24-87 (source, probe count and time journaled), T-24-88 (no endless re-cancel, tested), T-24-SC (no dependency change) are mitigated.

## Self-Check: PASSED

- tests/test_live_unknown_entry_notify.py, tests/test_protection_cancel_lag.py, tests/test_live_reconcile_divergences.py exist; commits b37ec7c0, 8cfbec7e, bef9d8e9 are on the branch.
