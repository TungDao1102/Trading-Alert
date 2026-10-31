---
phase: 24-live-runtime-composition-demo
plan: 05
subsystem: ops
tags: [asyncio, store-executor, threads, shadow-runtime, phase-24, p16r-03]

requires:
  - phase: 24-live-runtime-composition-demo
    provides: "24-01 owner answer Q2 (recommended StoreExecutor seam: sync stores, one writer thread, no async pool)"
provides:
  - "src/ops/store_executor.py: StoreExecutor with read, write, close, aclose (thread prefix store-writer)"
  - "the paper runtime confirm TTL sweep (ConfirmBook.expire_due) runs on the writer thread, off the event loop (P16R-03)"
affects: [24-12, 24-14, 24-16, 24-17, 24-22, 24-23, 24-29, 24-30]

tech-stack:
  added: []
  patterns:
    - "every on-loop store call goes through StoreExecutor.write (ordered, one thread) or .read (to_thread)"
    - "writes are shielded from caller cancellation and must be idempotent at the store layer"

key-files:
  created:
    - src/ops/store_executor.py
    - tests/test_store_executor.py
  modified:
    - src/paper/shadow_runtime.py
    - tests/test_paper_shadow_runtime.py
    - tests/test_paper_shadow_isolation.py

key-decisions:
  - "write() shields the executor future: a cancelled caller does not drop a write that is still queued (not only one that is running); the plan only asked to pin the running case"
  - "aclose() added next to close(): the drain wait runs in the default executor so stop() never blocks the loop"
  - "ShadowCoordinator.expire_due() became a coroutine (it runs through the writer); the two test call sites await it"
  - "stop() sets a stopped flag first; a poll step that runs after stop skips the sweep instead of raising RuntimeError, so the paper runtime shutdown path (stop() while the poller task is still alive) behaves as before"

requirements-completed: []  # OPS-03 is only advanced here (the seam exists); the live composition plans complete it

duration: 1 session
completed: 2026-10-31
status: complete
actuals:
  tokens: 14500
  tasks: 2
  commits: 3
plan_head_before: 7bd629638a5d5013148b57e65165e76e46da87df
plan_head_after: 130529bbc13d34396ffaf7518cb567a93e768862
---

# Phase 24 Plan 05: StoreExecutor seam Summary

**One stdlib-only `StoreExecutor` (ordered writes on a single `store-writer` thread, parallel reads, shielded writes, drain on close) and the paper runtime's on-loop `expire_due` moved behind it.**

## Precondition

24-01-SUMMARY.md "Owner answers" records Q2 as the recommended option (sync stores behind `src/ops/store_executor.py`, one writer thread, no async pool). The precondition holds.

## Accomplishments

- `src/ops/store_executor.py`: `write` (ThreadPoolExecutor `max_workers=1`, `contextvars.copy_context().run`, shielded), `read` (`asyncio.to_thread`), `close` (blocking, idempotent), `aclose` (non-blocking drain). Module docstring states D-25, the P-2 facts, and that callers keep writes idempotent. Imports: standard library only (checked by AST).
- `tests/test_store_executor.py` (11 tests, real threads, `threading.Event` handshakes, one bounded wait constant `TEST_ONLY_WAIT_SECONDS`): submission order on one thread, reads parallel and off the writer, running write survives caller cancellation, queued write survives caller cancellation, exception class and message reach the caller and the writer survives, no "never retrieved" warning after a cancelled failing write, contextvar visible in read and write, args/kwargs, close drains and refuses later writes, close idempotent, aclose does not block the loop.
- `src/paper/shadow_runtime.py`: the coordinator owns a `StoreExecutor`; `poll_once` and the public `expire_due()` call `self._confirm.expire_due` through `await executor.write(...)`; `stop()` drains it last. `git grep "self._confirm.expire_due(now)"` prints nothing (baseline at HEAD: 1 line at 838 on this base; the plan said at least 2, the second site used `self._clock()`).
- `tests/test_paper_shadow_runtime.py` (+6 tests): the sweep of a poll and the public `expire_due` run on a `store-writer` thread, a blocked sweep does not stop the loop from turning, an unpressed CONFIRM past its TTL is still expired and journaled once (second sweep writes nothing), `stop()` waits for an in-flight sweep, a poll after `stop()` skips the sweep.
- `tests/test_paper_shadow_isolation.py` (+1 test): `src.ops.store_executor` is in the SHADOW closure, is not banned, has no order-surface name, imports no local module, and no `src.live` module is in the closure. The banned prefixes are unchanged.

## Verification

- `uv run pytest -m "not docker"` on `tests/test_store_executor.py tests/test_paper_shadow_runtime.py tests/test_paper_shadow_isolation.py tests/test_paper_shadow_confirm.py tests/test_paper_shadow_buttons.py` plus `test_paper_shadow_lock_order / telegram_failures / reservations / evidence_export`, `test_paper_runtime_compose / loop / restart`, `test_paper_test_signal_rehearsal`, `test_rehearsal_compose`: 411 passed.
- `uv run mypy src/paper/shadow_runtime.py src/ops/store_executor.py`: clean. `uv run ruff check` on `src` and the touched tests, `ruff format --check` on the touched files: clean. `uv lock --check`: passes; `pyproject.toml` and `uv.lock` unchanged.
- Line endings: `git ls-files --eol` shows `i/lf` for `src/paper/shadow_runtime.py` before and after (the working copy is CRLF through autocrlf; the edit was made with the Edit tool, no whole-file rewrite).
- Not run (by instruction): `tests/test_paper_shadow_runtime_pg.py` and every other PostgreSQL test (other plans share that database), `uv run mypy src` (whole tree), the full suite. **Gap:** the `TRADING_CI_STRICT=1 ... test_paper_shadow_runtime_pg.py` line of the plan's verification section is not covered here.

## Deviations from Plan

### Worktree base

**1. [Rule 3 - Blocking] The worktree was created on an old base**
- **Found during:** start. The worktree branch pointed at `d9907ffc` (old `master`), which has neither the Phase 24 plan files nor the current `shadow_runtime.py` (the plan's line numbers ~838 and ~1320 only exist on `develop`).
- **Fix:** reset the still-empty worktree branch to `develop` (`7bd62963`) with `git checkout -B worktree-agent-a8f0abdc1d4d05b56 develop` on a clean tree (no commits or files lost). All three commits sit on top of `7bd62963`. The orchestrator should merge this branch into `develop`, not `master`.

### Auto-fixed Issues

**2. [Rule 2 - Missing critical functionality] Queued writes were cancellable**
- **Found during:** Task 1 design. A bare `loop.run_in_executor` future cancelled with its caller also cancels a queued (not yet started) write, which would drop an ordered write. P-2 only measured the running case.
- **Fix:** shield the executor future and mark its outcome retrieved; test pins both the running and the queued case.
- **Files:** `src/ops/store_executor.py`, `tests/test_store_executor.py`. **Commit:** bd18de6c.

**3. [Rule 1 - Bug] A poll step after `stop()` would have raised**
- **Found during:** Task 2 design. `paper/runtime.py::_shutdown` calls `shadow.stop()` while the poller task still runs until it is cancelled; a closed executor would make `poll_once` raise `RuntimeError`, which `_run_shadow_poller` turns into `_fail` and a `RuntimeFailClosed` exit. 
- **Fix:** `_stopped` flag set first in `stop()`; `poll_once` returns before the sweep once it is set (check and submit have no await between them). **Commit:** 130529bb.

### Plan details that did not apply as written

- "split `expire_due` so loop-bound work is applied on the loop": nothing loop-bound exists. `expire_due` can adopt a stored CONFIRM and call `_on_confirmed`, which only runs `_ensure_drivers` (locks and driver build), the same code `poll_once` already runs through `asyncio.to_thread`. No split was needed and `ShadowConfirm`/`ConfirmBook` are untouched. The module docstring records this.
- The CONFIRM core now lives in `src/approval/confirm_core.py` (24-08's file); the plan's `shadow_confirm.py` read-first is stale. Not modified.

## Observation for plan 24-08 (not fixed here, file owned by 24-08)

`ConfirmBook._sweep_orphans` (`src/approval/confirm_core.py`) builds `held = {... for e in self._entries.values()}` outside `self._lock`, while `register` inserts into `_entries` under the lock. This race already existed (presses run in `to_thread` workers concurrently with the sweep on the loop thread) and this plan does not make it worse in kind: the sweep now runs on the writer thread instead of the loop thread. A three-line fix would take the snapshot under `self._lock`. 24-08 modifies that file, so it is the right place.

## Known Stubs

None.

## Threat Flags

None. No endpoint, auth path or schema was added. T-24-12 (blocking store calls on the loop, paper part): mitigated by the thread-spy tests. T-24-13: single-thread writer plus the ordering test. T-24-14: `close()` drains, caller cancellation does not stop or drop a write (pinned), writes must stay idempotent (documented in the module). T-24-SC: `pyproject.toml` and `uv.lock` unchanged.

## Task Commits

1. **Task 1 RED:** `3c765852` (test) - StoreExecutor tests
2. **Task 1 GREEN:** `bd18de6c` (feat) - the StoreExecutor module
3. **Task 2:** `130529bb` (feat) - paper confirm sweep off the loop, isolation and runtime tests

## Self-Check: PASSED

- FOUND: src/ops/store_executor.py, tests/test_store_executor.py, src/paper/shadow_runtime.py
- FOUND commits 3c765852, bd18de6c, 130529bb (ancestors of HEAD)
