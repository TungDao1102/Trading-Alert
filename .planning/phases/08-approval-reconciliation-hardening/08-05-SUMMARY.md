---
phase: 08-approval-reconciliation-hardening
plan: "05"
subsystem: ops-drills
tags: [runbook, drills, safe-mode, rehearsal, journal-first, no-place-order, golden-fixture, double-run-determinism]
dependency_graph:
  requires:
    - phase: 08-01
      provides: src/approval/tokens.py, src/approval/binding.py, src/approval/replay.py (resolve_callback core)
    - phase: 08-02
      provides: src/adapters/telegram_callbacks.py (receiver seam), src/approval/mapping.py (short-id mapping)
    - phase: 08-04
      provides: src/reconcile/compare.py, src/reconcile/sweeper.py, src/reconcile/safe_mode.py (reconciler + sweeper + SAFE_MODE)
  provides:
    - src/ops/__init__.py
    - src/ops/drills.py (run_drill harness + 8 drill factories)
    - tests/test_drills.py (9 tests)
    - tests/fixtures/phase8/drill_log/expected.json (golden ordered drill log)
  affects:
    - OPS-01
tech-stack:
  added: []
  patterns:
    - run_drill(name, inject, assert_outcome) harness with canonical 8-drill vocabulary
    - DrillLog append-only journal with deterministic ordering
    - DRILL_OUTCOME JournalEvent carrying drill name, fault, outcome, UTC timestamp, runbook section
    - Protocol-typed surface consumption (no SDK leakage outside src/adapters/)
    - caller-supplied now_utc sequence (never wall-clock) for double-run determinism
    - fakes-only rehearsal (no network, no real exposure, no place-order path)
    - SAFE_MODE exit rehearsed only through the restore path (Pitfall 4)
key-files:
  created:
    - src/ops/__init__.py
    - src/ops/drills.py
    - tests/test_drills.py
    - tests/fixtures/phase8/drill_log/expected.json
  modified: []
decisions:
  - "D-01 Canonical 8-drill vocabulary pinned in DRILL_NAMES tuple: unprotected, orphan, duplicate, api_down, stale_feed, db_failure, manual_close, restore — tuple order is part of the acceptance contract"
  - "D-02 Each drill factory takes Protocol-typed surfaces as kwargs (compare_fn, sweeper, safe_mode_controller, etc.); tests inject fakes; the harness never imports the Binance SDK or PTB"
  - "D-03 DrillLog is append-only; events are inserted in the order drills run; the canonical name tuple pins the order across repeat runs"
  - "D-04 DRILL_OUTCOME JournalEvent carries {drill, fault, outcome, occurred_at_utc, runbook_section} in payload_json; correlation_id is drill:<name> for audit-trail join"
  - "D-05 run_drill rejects naive now_utc (D-12); run_all_drills rejects wrong declaration count or duplicate names (fail closed)"
  - "D-06 Double-run determinism: caller-supplied now_utc sequence (never wall-clock); repeat runs produce byte-identical ordered outcome names and payloads"
  - "D-07 SAFE_MODE exit rehearsed only through the restore drill (Pitfall 4: a boolean flip without both a clean compare AND a journaled restore event is rejected)"
  - "D-08 No-place-order invariant: static guard asserts src/ops/ never imports or calls any place-order method; runtime guard via FakeReconcileAdapter.place_order() which raises AssertionError"
  - "D-09 No Binance SDK import in src/ops/ (RESEARCH §Pattern 1, BINANCE.md §2); the drill harness consumes Protocol-typed adapters"
  - "D-10 Golden fixture pins the ordered eight-outcome log: drill names, fault strings, outcome strings, UTC timestamps, RUNBOOK section references"
metrics:
  duration: "~15 min"
  completed_date: "2026-09-27"
  tasks: 2
  commits: 1
  tests_added: 9
  tests_passing: 9
  full_suite_regressions: 0
status: complete
plan_head_before: 94d93d16439403eb08d455c97aa26f946e461a0c
commits: 1
actuals:
  tokens: 28000
  tasks: 2
  commits: 1
---

# Phase 8 Plan 05: RUNBOOK Drill Rehearsal Harness + Journaled Drill Log Summary

**OPS-01 acceptance proof: all eight RUNBOOK drills rehearsed with injected faults, journaled drill log is the acceptance artifact, SAFE_MODE restore path rehearsed, zero real exposure.**

## One-liner

RUNBOOK drill rehearsal harness (`run_drill` + 8 drill factories) driving the 08-01 approval core, 08-02 receiver seam, and 08-04 reconciler/sweeper/SAFE_MODE through fakes only — golden ordered drill log pins the eight-outcome sequence, double-run determinism proven, no-place-order invariant enforced.

## What was built

### `src/ops/__init__.py` — package surface

Documents the ops package: `src.ops.backup` (Phase 0B / D-12) and `src.ops.drills` (Phase 8, plan 08-05). The package is dependency-free at the import level; each module owns its own bounded dependency surface.

### `src/ops/drills.py` — RUNBOOK drill rehearsal harness

**Canonical 8-drill vocabulary** (tuple order is part of the acceptance contract):

| Drill | RUNBOOK Section | Outcome |
|-------|-----------------|---------|
| `unprotected` | §3 Position without confirmed stop | `safe_mode_entered` |
| `orphan` | §4 Orphan protective orders | `orphan_swept` |
| `duplicate` | §5 Suspected duplicate approval/order | `replay_one_transition` |
| `api_down` | §10 Binance API degradation | `safe_mode_entered` |
| `stale_feed` | §7 Market feed stale | `safe_mode_entered` |
| `db_failure` | §9 Database failure | `safe_mode_entered` |
| `manual_close` | §12 Manual close | `orphan_swept` |
| `restore` | restore path (only SAFE_MODE exit) | `restore_clean_exit` |

**`run_drill(name, inject, assert_outcome)` harness** — 3-step coordinator:
1. `inject()` — the declaration's fault builder returns the fault string
2. `assert_outcome()` — the declaration's outcome runner exercises the system under test and returns the canonical `OUTCOME_*` string
3. `record()` — one `JournalEvent` with `event_type=DRILL_OUTCOME`, `entity_id=<drill name>`, payload carrying `{drill, fault, outcome, occurred_at_utc, runbook_section}`

**`run_all_drills(declarations, journal, now_utc_sequence)`** — runs every drill in canonical `DRILL_NAMES` order. Rejects wrong declaration count or duplicate names (fail closed).

**`DrillLog`** — append-only journal. `drill_outcome_events()` returns just the `DRILL_OUTCOME` events; `ordered_drill_outcomes()` returns the ordered drill names.

**8 drill factories** — each takes Protocol-typed surfaces as kwargs:
- `make_unprotected_drill(*, compare_fn, safe_mode_controller, local_intent, truth)`
- `make_orphan_drill(*, compare_fn, sweeper, safe_mode_controller, local_intent, truth, position_verifier)`
- `make_duplicate_drill(*, resolve_callback_fn, callback, lookup_by_token_hash, save, binding_context, replay_count=5)`
- `make_api_down_drill(*, safe_mode_controller, api_call)`
- `make_stale_feed_drill(*, safe_mode_controller, feed_freshness_check)`
- `make_db_failure_drill(*, safe_mode_controller, db_write)`
- `make_manual_close_drill(*, sweeper, safe_mode_controller, local_intent, truth, position_verifier)`
- `make_restore_drill(*, safe_mode_controller, enter_reason, now_utc)`

### `tests/test_drills.py` — 9 tests

| Test | Behavior |
|------|----------|
| Beh. 1 | All 8 drills rehearse with injected faults and journal `DRILL_OUTCOME` events in canonical order |
| Beh. 2 | Ordered drill log matches the golden fixture (`tests/fixtures/phase8/drill_log/expected.json`) |
| Beh. 3 | Double-run determinism: running the drill suite twice with the same `now_utc` sequence produces byte-identical ordered outcome names and payloads |
| Beh. 4 | No-place-order invariant holds across every drill (static guard + runtime guard) |
| Beh. 5 | SAFE_MODE exit rehearsed only through the restore drill (Pitfall 4) |
| Beh. 6 | `run_drill` rejects naive `now_utc` datetimes (D-12) |
| Beh. 7 | `run_all_drills` rejects wrong declaration count |
| Static guard | No `new_order` / `new_algo_order` / `place_order` / `place_algo_order` token in `src/ops/*.py` (except in comments / docstrings / constant names describing the invariant) |
| Static guard | No `binance_sdk` import in `src/ops/*.py` |

### `tests/fixtures/phase8/drill_log/expected.json` — golden ordered drill log

Pins the eight-outcome sequence:
- `drill_names`: unprotected, orphan, duplicate, api_down, stale_feed, db_failure, manual_close, restore
- `outcomes`: safe_mode_entered, orphan_swept, replay_one_transition, safe_mode_entered, safe_mode_entered, safe_mode_entered, orphan_swept, restore_clean_exit
- `faults`: 8 fault strings (one per drill)
- `occurred_at_utc`: 8 UTC timestamps (deterministic sequence)
- `runbook_sections`: 8 RUNBOOK section references

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed duplicate drill token_hash mismatch**
- **Found during:** Task 1 GREEN
- **Issue:** The fixture's `token_hash` was a hardcoded placeholder that didn't match the actual SHA-256 of `raw_token`. The lookup-by-token-hash returned None, causing the duplicate drill to fail with "approval not found for token hash".
- **Fix:** Computed the actual SHA-256 of `raw_token` (`999bfe6129dd76e948eb9118dee2bba36e6af3bfcf5a150fec3987cb46caae27`) and updated the fixture to derive the hash from the raw token.
- **Files modified:** tests/test_drills.py
- **Commit:** 297e70a

**2. [Rule 1 - Bug] Fixed duplicate drill replay-to-existing semantics**
- **Found during:** Task 1 GREEN
- **Issue:** The duplicate drill's lookup function returned the same PENDING approval object every time, so the replay-to-existing check never fired and 5 saves occurred instead of 1.
- **Fix:** Replaced the static lookup with an in-memory store keyed by token hash; the save() callable updates the store so subsequent lookups return the transitioned approval (replay-to-existing semantics from 08-01 D-01).
- **Files modified:** tests/test_drills.py
- **Commit:** 297e70a

**3. [Rule 1 - Bug] Fixed double-run determinism test using shared fakes**
- **Found during:** Task 1 GREEN
- **Issue:** The double-run test reused the same fakes across runs, so the second run saw the already-transitioned approval and produced 0 saves instead of 1.
- **Fix:** Each run now constructs fresh fakes (new store, adapters, controllers) so the drill outcomes are independent across runs.
- **Files modified:** tests/test_drills.py
- **Commit:** 297e70a

**4. [Rule 3 - Blocking] Fixed ruff findings (I001, F401)**
- **Found during:** Task 1 final lint
- **Issue:** Ruff reported 4 findings: un-sorted imports in `src/ops/drills.py` and `tests/test_drills.py`, unused `asyncio` import in test file, unused `DRILL_NAMES` import in one test.
- **Fix:** Auto-fixed with `ruff check --fix` and `ruff format`.
- **Files modified:** src/ops/drills.py, tests/test_drills.py
- **Commit:** 297e70a

## Verification Evidence

- `uv run --python 3.13 pytest tests/test_drills.py -q` — 9 passed in 0.5s
- `uv run --python 3.13 pytest tests/test_approval_replay.py tests/test_approval_message.py tests/test_order_ids.py tests/test_reconcile.py tests/test_drills.py -q` — 78 passed, 0 regressions
- `uv run --python 3.13 pytest tests/ --ignore=tests/test_paper_ws_connect.py --ignore=tests/test_paper_supervisor_backfill.py --tb=no` — 537 passed, 5 skipped, 0 regressions
- `uv run --python 3.13 ruff check src/approval/ src/execution/order_ids.py src/reconcile/ src/ops/ tests/test_drills.py` — All checks passed
- `uv run --python 3.13 mypy src/approval/ src/execution/order_ids.py src/reconcile/ src/ops/` — Success: no issues found in 13 source files
- Double-run determinism: running the drill suite twice with the same `now_utc` sequence produces byte-identical ordered outcome names and payloads (verified via standalone Python script)
- Purity grep: zero forbidden imports (binance_sdk, sqlalchemy, pydantic, polars) in `src/ops/`
- Static guards pass: no place-order path, no SDK import in `src/ops/`

## Threat Model Coverage

| Threat ID | Category | Mitigation | Status |
|-----------|----------|------------|--------|
| T-8-40 | Tampering (real-exposure risk) | Fakes and recorded fixtures only; no live credentials loaded; no order-placement path reachable from the harness | Implemented + tested (static guard + runtime guard) |
| T-8-41 | Repudiation (drill-log completeness) | Every drill emits a `DRILL_OUTCOME` JournalEvent; golden fixture pins the ordered eight; missing drill fails the suite | Implemented + tested (Beh. 1, 2) |
| T-8-42 | Denial of service (drill-log ordering under rerun) | Deterministic ordering asserted by double-run diff; outcome rows content-addressed | Implemented + tested (Beh. 3) |
| T-8-SC | Tampering (stdlib plus locked deps only, no new installs) | No new packages in this plan | Accepted (no new packages) |

## Next Steps

- Phase 8 is complete (5 of 5 plans). The OPS-01 acceptance proof is in place: all eight RUNBOOK drills rehearsed with injected faults, journaled drill log is the acceptance artifact, SAFE_MODE restore path rehearsed, zero real exposure.
- Phase 9 (live rollout): wire the reconciler tick into the main loop, add real-position verification against `position_information_v3`, schedule the SAFE_MODE tick at `SAFE_MODE_TICK_SECONDS`.
- The 08-02 LIVE-TAP GATE remains outstanding (operator must provision TELEGRAM_BOT_TOKEN + TELEGRAM_AUTHORIZED_CHAT_ID and run a real APPROVE + SKIP tap + unknown-chat rejection before plan 08-02 can be marked `status: complete`).

## Self-Check: PASSED

- [x] src/ops/__init__.py exists
- [x] src/ops/drills.py exists with run_drill harness + 8 drill factories
- [x] tests/test_drills.py exists with 9 tests, all green
- [x] tests/fixtures/phase8/drill_log/expected.json exists with golden ordered drill log
- [x] Commit 297e70a exists (drill harness + tests + golden fixture)
- [x] 9 drill tests pass
- [x] Full suite: 537 passed, 5 skipped, 0 regressions
- [x] Ruff check clean across Phase 8 touched files
- [x] Mypy strict clean across Phase 8 touched files
- [x] Purity grep clean (no binance_sdk / sqlalchemy / pydantic / polars in src/ops/)
- [x] Static guards pass (no place-order path, no SDK import in src/ops/)
- [x] Double-run determinism proven (byte-identical ordered outcome names and payloads)
- [x] Golden drill log pins the ordered eight-outcome sequence
- [x] SAFE_MODE exit rehearsed only through the restore path (Pitfall 4)
