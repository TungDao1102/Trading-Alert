---
phase: 24-live-runtime-composition-demo
plan: 28
subsystem: tests
tags: [replay, restart, exactly-once, EXEC-03, OPS-03, APRV-01, D-09, D-20]
requires: [24-27]
provides:
  - "replay and restart matrix on the composed fakes (10 scenarios, every one counts place_entry as 0 or 1)"
  - "the same 10 scenarios on PostgreSQL across two process instances"
affects: [24-32, 24-33]
key-files:
  created:
    - tests/test_live_replay_restart.py
    - tests/test_live_replay_restart_pg.py
    - tests/support/live_pg_rig.py
  modified:
    - tests/support/live_rig.py
    - tests/test_live_restart_rehydrate.py
key-decisions:
  - "No production code changed (git diff -- src is empty)."
metrics:
  tasks: 3
  completed: 2026-11-07
status: complete
commits: [ff02e725, 89e3a3bc, f3a6e3b9]
---

# Plan 24-28 summary

Replayed APPROVE, CONFIRM and CANCEL, two concurrent CONFIRM presses (one process, and two processes over one store), an APPROVE redelivered after plan expiry, and restarts after APPROVE, after an ambiguous place_entry and after an acknowledged entry: none produces a second order. `place_entry` is 0 or 1 in every scenario, and the entry client id equals `derive_client_order_id` before and after a restart.

Results: fakes module 10 passed; PostgreSQL module 10 passed with TRADING_CI_STRICT=1 and 0 skipped (real stores, migration head, a throwaway `_test` database). Ruff clean; `git diff -- src pyproject.toml uv.lock` empty.

## Findings (not patched, per the plan)

1. **No fresh CONFIRM card after a restart.** Nothing in `src` re-issues a confirm card for a plan that is already APPROVED. After `expire_on_restart` (RUNTIME_RESTART) the old card answers NO_CONFIRM_CONTEXT and places nothing, and a new desk request for the same plan is refused with INVALIDATED. The owner waits for the plan to expire and for a new signal. Safe (no duplicate), but the plan text "needs a fresh CONFIRM card" is not implemented, so that scenario is tested as "the old card places nothing". Recommendation: accept for V1 (fails closed); build a re-issue path only if it hurts in use. Owner decision pending.
2. A replayed CONFIRM or APPROVE press returns ok=True with already_decided=False; the stored decision answers silently, so tests assert state and place_entry counts, not the press result.
3. The concurrent-press tests use asyncio.gather with synchronous store calls, so they interleave only at awaits. The real row-level race is covered by `tests/test_execution_exactly_once_pg.py`.

The owner-run Demo half (recorded client order ids) is plan 24-33.
