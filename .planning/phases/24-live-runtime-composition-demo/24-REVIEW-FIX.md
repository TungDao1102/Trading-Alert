---
phase: 24-live-runtime-composition-demo
fixed_at: 2026-11-07T00:00:00Z
review_path: .planning/phases/24-live-runtime-composition-demo/24-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 3
skipped: 3
status: partial
---

# Phase 24: Code Review Fix Report

**Fixed at:** 2026-11-07
**Source review:** .planning/phases/24-live-runtime-composition-demo/24-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 6 (CR-01, WR-01 to WR-05)
- Fixed: 3 (CR-01, WR-01, WR-02)
- Skipped: 3 (WR-03, WR-04, WR-05; each needs an owner or design decision)

Verification ran in the main checkout (`workflow.use_worktrees` is `false`): the touched tests, `tests/test_live_*.py`, `tests/test_phase24_gate.py`, `tests/test_approval_mode_scope_pg.py` and the PG-backed shadow suites (with `TEST_DATABASE_URL` set, `TRADING_CI_STRICT=1` for the PG set), then `uv run ruff check`, `uv run ruff format --check` and `uv run mypy src` over the whole tree: all clean. The full suite was not run (the orchestrator does that once).

## Fixed Issues

### CR-01: The live engine has no connect, lock, statement or UTC bounds

**Files modified:** `src/live/runtime.py`, `tests/test_live_default_assemble.py` (new)
**Commit:** 8efdfc15
**Applied fix:** `default_assemble` now passes `make_sync_engine(url)` to `build_wiring` (bounded connect, lock, statement and pool waits, keepalives, verified UTC pin; the same factory as the paper runtime). The now-unused `_sqlalchemy_url` helper and the `create_engine` import were removed. An unreachable database or a session off UTC raises at build time, which `run_admitted` already turns into a refused start. New tests: a call spy that pins the engine handed to `build_wiring` to `make_sync_engine` (and the `DATABASE_URL_SYNC` over `DATABASE_URL` order, and no engine without a URL), plus an AST guard that `src/live/runtime.py` never references `create_engine`. Note: `make_sync_engine` accepts only `postgresql://` and `postgresql+psycopg://` (the old helper also accepted `postgres://`); a `postgres://` URL now refuses the start with `ValueError`, the same as the paper runtime. Note: the pool-exhaustion path (a bare `sqlalchemy.exc.TimeoutError` not wrapped as `StoreUnavailable`) is now bounded to 5 s by `pool_timeout` but its exception type was not changed (out of scope of this finding's fix).

### WR-01: An interrupted first install leaves a gate state without the spill sentinel

**Files modified:** `src/live/startup.py`, `tests/test_live_start_sequence.py`
**Commit:** cc9a9df8
**Status:** fixed: requires human verification (ordering logic)
**Applied fix:** in the GATE step the spill sentinel is now written (atomic, idempotent) immediately BEFORE `gate_store.initialize`, after the operator-id check, so the gate state file and the sentinel appear together whatever holds next in ALEMBIC, SAFE_MODE or ENABLEMENT. The review suggested writing it right after `initialize`; writing it first also covers a failure of the sentinel write itself (no gate state is then left behind). The SPILL_SENTINEL step is unchanged (it still writes on a first install, idempotently, and checks otherwise). New tests: a first start held in ALEMBIC leaves both files and a later plain start is admitted, enabled and not in SAFE_MODE (verified to fail without the fix); a bootstrap refused for a missing operator id writes neither file. Not covered: an install that is ALREADY stuck (gate state, no sentinel) on a host; recovering it still means creating `spill/.spill-initialized` by hand or deleting the gate state file, which this change does not document (RUNBOOK says not to edit the spill directory; adding a recovery note is the owner's call).

### WR-02: A SHADOW runtime restart expires the DEMO process's PENDING approvals

**Files modified:** `src/persistence/shadow_stores.py`, `src/live/approval_sender.py` (docstring only), `tests/shadow_fakes.py`, `tests/test_approval_mode_scope_pg.py`
**Commit:** 94223052
**Status:** fixed: requires human verification (scoping logic)
**Applied fix:** `list_pending_approvals` now uses the same marker join and `mode_includes` filter as `list_approved_approvals` (one shared `_list_in_mode`, PENDING keeps all actions, APPROVED keeps APPROVE only; the unused `_by_status` was removed). This follows the contract the module already documents for the approved reader (SHADOW sees unmarked and SHADOW rows, DEMO and LIVE only their own, unreadable markers never listed, `confirm_mode=None` unscoped), so no new contract was invented. The in-memory fake `InMemoryShadowStores` mirrors it. The DEMO marker check in `make_open_demo_approvals_reader` is kept as a second guard (docstring updated). New PG tests: SHADOW, DEMO, LIVE and unscoped readers over one SHADOW, one DEMO and one unmarked PENDING row; and `invalidate_pending_on_restart` on the SHADOW store leaves the DEMO PENDING approval untouched. Behaviour note: a PENDING approval whose marker payload is unreadable is now never listed by a scoped store (it stays PENDING instead of being expired by the SHADOW sweep), the same fail-closed rule as the approved reader.

## Skipped Issues

### WR-03: `mark_placed` and `mark_open` have no production caller

**File:** `src/persistence/risk_reservations.py:463-497` (and `src/live/reservation_release.py:146`)
**Reason:** skipped: needs an owner decision on the reservation lifecycle. The finding is accurate (the only `mark_placed` call is the release sweep, `mark_open` has none), but the repo records two conflicting rules for the call site: `21-DEFERRED.md` says `mark_placed` must run BEFORE the entry POST (so a RELEASED row is never placed), while the `mark_placed` docstring, 22-REVIEW WR-06 and the placement-time margin netting require the instant to be read AFTER the exchange acknowledged. `mark_open` at the first fill is also tied to the `release(POSITION_CLOSED)` source rules. A wrong stamp makes the margin guard under-refuse (unsafe direction), so this is not invented here.
**Question for the owner:** after an ACKED entry, should `mark_placed` be stamped at the acknowledgement (as the store docstring and WR-06 require, which leaves a window where a released row would raise `RowConflict`), and should `mark_open` be driven by the coordinator's first-fill transition, or is the current sweep-only behaviour (safe over-counting, one symbol) accepted until Phase 25?
**Original issue:** an executed plan's reservation stays RESERVED for the life of the position, so its margin is counted twice for any other plan.

### WR-04: Stopping the process leaves resting entries on the exchange unprotected

**File:** `src/live/runtime.py:514-551`, `src/live/execution_service.py:191-194`
**Reason:** skipped: needs an owner decision on the shutdown policy. Cancelling every AWAITING_FILL entry at SIGTERM, reordering the drain before the coordinator and stream stop, or only documenting the window and making `update.sh` refuse while `live` runs are different behaviours, and the cancel path touches the D079 fill-driven protection and the never-resend placement rules.
**Question for the owner:** on stop, should the live process cancel resting entries (journal-first, verified) and run the protection step until no plan is UNPROTECTED or a deadline passes, or is the unprotected window to be documented in RUNBOOK section 22 with `update.sh` refusing to run while `live` is up?
**Original issue:** protection is fill-driven, so an entry that fills while the process is down has no stop until the next start.

### WR-05: Operator commands and start-time rehydration do synchronous database work on the event loop

**File:** `src/live/operator.py:362-373`, `:536-569`; `src/live/wiring.py:846-859`, `:1216`; `src/live/startup.py:569-597`
**Reason:** skipped: the fix is a multi-component API change, not a local edit. `SafeModeController.exit_safe_mode` takes synchronous provider callables (`local_intent_fn`, `readiness`) that `OperatorCommands` fills from the raw stores, so routing them through `StoreExecutor` needs async variants in the controller, `build_exit_readiness`, the operator, `expire_on_restart` and the restore glue, plus their fakes and wiring-gate links. The journal write from the rejection path also needs a fire-and-forget policy (ordering and loss semantics) that is a design choice. CR-01 now bounds every one of these calls (5 s lock, 10 s statement, 3 s connect, 5 s pool), which removes the unbounded stall; what remains is a bounded loop stall.
**Question for the owner:** is a bounded loop stall in the operator and start-time paths acceptable for Phase 24 (deferred to a later plan), or should `exit_safe_mode`'s providers become async and the rejection journal fire-and-forget now?
**Original issue:** operator audit, readiness and intent reads run inline on the event loop, as do `expire_on_restart` and the restored-plans builder.

---

_Fixed: 2026-11-07_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
