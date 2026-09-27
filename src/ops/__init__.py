"""Ops package — backup + RUNBOOK drill harness (Phase 0B + Phase 8).

This package contains the operational tooling required before live
enablement:

  - `src.ops.backup` — single-command backup + scratch-restore drill
    (Phase 0B / D-12 / SECURITY_AND_OPERATIONS §9). The `run_drill`
    function in this module is a precedent the RUNBOOK drill harness
    (`src.ops.drills`) follows: inject a fault, assert the expected
    outcome, journal the result.

  - `src.ops.drills` — RUNBOOK drill rehearsal harness (Phase 8, plan
    08-05). Rehearses every RUNBOOK procedure with injected faults and
    journals the outcomes as a deterministic `DRILL_OUTCOME` event log.
    The drill harness drives the 08-01 approval core, the 08-02
    receiver seam, and the 08-04 reconciler/sweeper/SAFE_MODE through
    fakes only — it NEVER touches the network, places an order, or
    creates real unprotected exposure.

The ops package is dependency-free at the import level: each module is
free to add its own bounded dependency surface, but the package itself
has no shared state. No Binance SDK, no SQLAlchemy, no Telegram PTB
imports leak across module boundaries.
"""

from __future__ import annotations
