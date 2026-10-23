---
phase: 20-reconcile-safe-mode-hardening
plan: 29
subsystem: ops
tags: [gap-closure, spill, rest-gate, user-data-supervisor, startup, cr-c1, wr-c1, wr-c2, wr-c4, wr-c9]
status: complete

requires:
  - phase: 20-reconcile-safe-mode-hardening
    provides: "20-07 REST gate state store and CLI; 20-08 local spill; 20-19 startup recovery; 20-REVIEW findings CR-C1, WR-C1, WR-C2, WR-C4, WR-C9"
provides:
  - "LocalSpill.scan() raises on an unreadable directory; only a missing directory is an empty scan"
  - "decode_record is total (OverflowError and RecursionError read as corrupt); status and clear work on such files"
  - "the supervisor stops waiting on a gate with no known end after the stream's reconnect bound and halts through on_failure"
  - "a failed gate save is retried by the next check() or record(); the state file directory is fsynced; initialize() is exclusive"
affects: [20-DEFERRED (two rows are now stale, see Notes), phase 24 composition]

requirements-addressed: []

actuals:
  tokens: 8800
  tasks: 3
  commits: 4
plan_head_before: ffe13a74af95766f1b4911bbb98cd1083058ef06
plan_head_after: c36c92fa5ff8ad62e2304583bd9c5da9d611bc69

key-files:
  modified:
    - src/ops/spill.py
    - src/reconcile/startup.py
    - src/ops/rest_gate_state.py
    - src/adapters/binance_ratelimit_gate.py
    - src/adapters/binance_userdata_supervisor.py
    - tests/test_risk_first_spill.py
    - tests/test_startup_recovery.py
    - tests/test_gate_restart.py
    - tests/test_rest_gate_cli.py
    - tests/test_userdata_supervisor.py
  created:
    - .planning/phases/20-reconcile-safe-mode-hardening/20-29-PLAN.md

key-decisions:
  - "WR-C4 bound: a restriction with until_utc None is checked at most reconnect_max_attempts times OR reconnect_max_delay_seconds of the injected clock, whichever first (the two stops _bounded_reconnect uses); no number was invented"
  - "initialize() uses os.link of the finished temp file for the exclusive create, so the content stays atomic"
---

# Phase 20 Plan 29: ops lane gap closure Summary

Five findings of `20-REVIEW.md` (owner approved 2026-10-23) are closed in the spill, the REST gate state file, the gate and the user-data supervisor. Evidence is executed tests with fakes and local files only; nothing is `[DEMO]`, no requirement is marked complete, and the 418 / 429 durations, the 259200 s fallback and the -1003 parsing (D083, Phase 24) are untouched.

## Commits

| Commit | Scope |
|--------|-------|
| be04cd09 | PLAN |
| c3bb303e | CR-C1: `LocalSpill.scan()` raises on an unreadable directory; startup does not replay an unreadable spill |
| c9810cd2 | WR-C1, WR-C2, WR-C9 |
| c36c92fa | WR-C4 |

## What changed

1. **CR-C1** (`src/ops/spill.py`, `src/reconcile/startup.py`). `scan()` catches only `FileNotFoundError` (empty scan). Any other `OSError` (permission, an I/O fault, a path that is not a directory) propagates, so `_scan_spill` returns `readable=False`: `STEP_SPILL_READ` fails, SAFE_MODE `RESTORE_INCONSISTENT` is entered, `spill_rows_for` returns `None`. Step 6 no longer calls `replay_spill` on a spill that was just found unreadable: it fails `STEP_SPILL_REPLAYED` with the same reason (before, the second scan would have raised and entered `DB_FAILURE`, a misleading reason). Corrupt-entry handling is unchanged. The `LocalSpill` constructor still creates a missing directory, so an unmounted volume that is re-created empty still reads as empty (not changed; composition, Phase 24).
2. **WR-C1** (`src/ops/rest_gate_state.py`). Reproduced first with `uv run python -I`: a year-9999 timestamp with offset `-05:00` raises `OverflowError`, `b"[" * 200000` raises `RecursionError`; both escaped `decode_record`. `_parse_time` now catches `(ValueError, OverflowError)` around parse and `astimezone`; `decode_record` is a thin total wrapper (any non-`GateStateCorrupt` exception from the strict parser becomes `GateStateCorrupt`). So `load()` sets such a file aside, `inspect()` reports it corrupt, `status` exits 2 with "corrupt", and `clear` replaces it and keeps the original aside as `*.corrupt-<time>`. `rest_gate_cli.py` needed no change: with a total `decode_record` the CLI never sees the exception, which also makes the review's third suggestion (treat any exception from `inspect()` as corrupt in the CLI) unnecessary.
3. **WR-C4** (`src/adapters/binance_userdata_supervisor.py`). `_await_rest_allowed` counts the checks of a restriction with `until_utc is None` (`GATE_NOT_RESTORED`, `GATE_STATE_UNKNOWN`) and raises `_RecoveryHalted(restriction.reason)` once `reconnect_max_attempts` checks were made or `reconnect_max_delay_seconds` of the injected clock passed, whichever is first (the same two stops `_bounded_reconnect` uses). The halt goes through the existing path: `_halt` sets UNKNOWN, calls `on_failure(reason)` once, and the loop waits for `request_resync()` (a resync is bounded again and reports again). Reconcile 20-16 maps any halt reason to `STREAM_TASK_DIED`. A timed pause (`until_utc` set) waits as before; a test with the bound set to 1 proves it. No integer literal beyond 0 and 1 was added (the supervisor's own pin test passes).
4. **WR-C2** (`src/adapters/binance_ratelimit_gate.py`). `_save_failed` is the pending-save flag. `check()` and a `record()` that changed nothing call `_retry_failed_save()`, which does nothing unless the last save failed (and skips while another thread is saving), otherwise saves the current deadlines; status stays `PERSISTENCE_FAILED` until a save succeeds. The new method name contains none of the words the 20-07 guard `test_restriction_expiry_sends_and_replays_nothing` rejects, so that allow-list is unchanged.
5. **WR-C9** (`src/ops/rest_gate_state.py`). `_write_atomic` fsyncs the directory after the write through `_fsync_directory` (same best-effort behavior as `LocalSpill`: POSIX only, no-op on Windows). `initialize()` links the fsynced temp file to the final name (`os.link` fails if the name exists); `FileExistsError` becomes `GateStateExists`, the winner's file is untouched.

## TDD evidence (honest)

- Task 1: RED seen before the fix: 4 of the 5 new tests failed (`scan()` returned an empty scan for a non-directory path, `PermissionError` and a generic `OSError`; the startup test saw no SAFE_MODE reason at all). The fifth, "a missing directory is an empty scan", passed before and after (a guard of the unchanged behavior).
- Task 2: RED seen: 12 of 13 new tests failed (decode overflow and recursion at the store, the gate and the CLI; the two save-retry tests; the two fsync tests; the exclusive-create test). "A gate that never failed a save does not save on check" passed before and after (a guard). One of my own tests was wrong at first (it expected a `replace` call from `initialize()`, which now links); I corrected the test, not the code.
- Task 3: RED seen: with the old code the 4 new halting tests fail; the first run, without a real-time guard, hung forever (the supervisor spun at 1 s, which is the finding) and I killed the two pytest processes of this worktree, then added `asyncio.wait_for(starting, timeout=5)` so the old behavior fails instead of hanging. The timed-pause test passed before and after (a guard).

## Verification run

Run from this worktree with `TRADING_CI_STRICT=1` and `TEST_DATABASE_URL` set in the process environment (not echoed): `tests/test_risk_first_spill.py test_startup_recovery.py test_gate_restart.py test_rest_gate_cli.py test_binance_ratelimit_gate.py test_userdata_supervisor.py test_binance_usdm_error_routing.py test_phase18_gate.py test_phase19_gate.py test_phase20_gate.py test_persistence_exit_evidence_pg.py` plus `test_pending_actions.py test_reconcile_loop.py test_safe_mode_exit_operator.py test_alerts.py test_manual_controls.py test_agents_md.py` (other consumers of the touched modules): 858 passed, 0 failed, 0 skipped. `uv run mypy src` clean (235 files), `uv run ruff check` clean, `uv run ruff format --check` clean (728 files), `uv run python scripts/verify_decision_alignment.py all` ALL_PASS. The full suite was not run (orchestrator's job).

## Deviations from Plan

None in scope. Pins changed: none (the attribute-name guard needed no extension; the supervisor's integer-literal pin still passes). Findings rejected: none; all five were reproduced or confirmed against the source (WR-C1 by script, the others by reading and by the failing tests above). One reviewer suggestion was deliberately not followed: WR-C4 proposed halting `GATE_STATE_UNKNOWN` immediately; the owner instruction was a bound from the existing stream limits, so both reasons are bounded the same way.

## Not done and known limits

- **WR-C2 cost.** The retry happens on every `check()` while a save keeps failing, so each REST call then pays one failed save attempt (on Windows up to the `replace_with_retry` budget). No interval was added because that would need a new number; the owner asked for retry on the next `record()` / `check()`.
- **WR-C9 needs hard links** on the state file's filesystem for `initialize()` (ext4, xfs, NTFS have them; FAT-like filesystems do not, and then `initialize()` raises `OSError`, fail closed). The directory fsync is `[NOT_TESTED]` on a real POSIX host here (this machine is Windows; tested with a fake `os`).
- Not touched: WR-C3 (adopting any persisted deadline), WR-C10 (`clear --reason` not durable), and the supervisor still re-reports `on_failure` on each `request_resync()`.
- `LocalSpill.__init__` re-creating a missing directory still hides an unmounted spill volume (above).

## Notes for the orchestrator (docs outside this lane)

`20-DEFERRED.md` has two rows now out of date; I did not edit it (not my file list): "`LocalSpill.scan()` swallows an `OSError`" (fixed here, constructor caveat remains) and "User-data supervisor and probe wiring to the REST gate" (the 1-second spin of `GATE_NOT_RESTORED` / `GATE_STATE_UNKNOWN` is now bounded; the `binance_probe` and Phase 24 wiring parts remain). Plans 20-27 and 20-28 share no file with this plan.

## Self-Check: PASSED

Files exist: the five source files, the five test files, `20-29-PLAN.md`. Commits found in `git log`: be04cd09, c3bb303e, c9810cd2, c36c92fa.
