---
phase: 16-paper-runtime-composition
plan: 55
subsystem: paper-runtime-deploy
status: partial
blocked_before: "Task 4 (plan rule: two projects' backups would collide on one remote; the remote layout is the user's)"
tags: [paper-runtime, docker, single-instance, advisory-lock, held-marker, pin-and-exit, B2-CR-05, B1-WR-07, B1-WR-11, B2-WR-07]
requires: [16-32, 16-33, 16-50]
provides:
  - runtime image carries params/ and config/paper/, with an in-image load check before the build record
  - instance lease per database (PostgreSQL session advisory lock), refusal code 8
  - held, non-operational refused start with an explicit per-container held marker
  - --pin-epoch pins and exits 0 without RUNTIME_START
  - decision records 16-DEC-RESTART-POLICY, 16-DEC-HUNG-RUNTIME, 16-DEC-PIN-COMMAND
affects: [16-43, 16-56, 16-62]
tech-stack:
  added: []
  patterns:
    - "session advisory lock on a pool-detached connection as a process lease"
    - "per-container held marker read by the container probe before the bar age"
    - "AST inventory of every return of main (exit-0 paths)"
key-files:
  created:
    - scripts/check_image_paths.py
    - src/paper/held_marker.py
    - tests/test_paper_runtime_instance_guard.py
    - tests/test_paper_runtime_held_state.py
    - .planning/phases/16-paper-runtime-composition/evidence/16-55-recheck.md
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-RESTART-POLICY.md
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-HUNG-RUNTIME.md
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-PIN-COMMAND.md
  modified:
    - Dockerfile
    - deploy/soak-image.sh
    - deploy/soak.env.example
    - docker-compose.yml (paper comment block only; restart policy unchanged, Task 4)
    - src/paper/runtime.py
    - src/paper/runtime_config.py
    - src/paper/runtime_state.py
    - src/paper/shadow_runtime.py
    - src/persistence/paper_runtime_state.py
    - src/persistence/uow.py
    - config/paper/README.md
    - docs/operations/RUNBOOK.md
    - docs/SOURCES.md
key-decisions:
  - "Lease scope is one fixed paper-runtime scope per database, not the epoch id: the epoch id hashes the opening time, so a pin cannot know it before it holds the lease"
  - "A held refusal releases the lease before it waits, so the one-shot pin can run beside a held container"
  - "A hold whose marker cannot be written is never entered: refusal code, or 7 for SKIPPED, never 0"
  - "An unreadable own marker counts as held"
duration: about 95 minutes
completed: 2026-10-16
commits: 3
plan_head_before: 1631a3d76e9e849efd1f2ab6b1d05deb215157ac
plan_head_after: 32fa56d27defeccdecb5f6e0f089cd0461cd5f9e
actuals:
  tokens: 40000
  tasks: 3
  commits: 3
---

# Phase 16 Plan 55: Image and deploy Summary

The runtime image now carries `params/` and `config/paper/`, and `deploy/soak-image.sh` loads both inside the built image (`--network none`) before it records the build. One paper runtime runs per database: an instance lease (a PostgreSQL session advisory lock) is taken before the pin and before any record. A refused start, SKIPPED included, holds without writing anything and leaves a held marker, so the healthcheck reports it unhealthy. `--pin-epoch` pins and exits 0. Task 4 (deploy side) was not executed: the plan says to stop when the two projects' backups would collide on the remote, and they would.

## Status: 3 of 4 tasks done, stopped before Task 4

| Task | Name | Commit | Result |
| --- | --- | --- | --- |
| 1 | Tracer: params/ and config/paper/ in the image, static path test, in-image load check (B2-CR-05) | 52faa0a | done |
| 2 | Re-check B1-WR-11 and B2-WR-07, the three decision records, SOURCES row | 800231a | done |
| 3 | Instance lease, held refused start with marker, pin-and-exit, exit-0 inventory (B1-WR-07) | 32fa56d | done |
| 4 | unless-stopped, one-shot pin service, trading-soak backup unit, RUNBOOK 20.x and restart drill | none | **not started (blocker below)** |

### Blocker: the soak and trading backups would collide on one remote

Plan Task 2 says: "If the dumps of two projects would collide on the remote, stop before Task 4 and report (the remote layout is the user's)." The re-check found that they would (evidence/16-55-recheck.md, "Would two projects' dumps collide on the backup remote?"):

- `src/ops/backup_remote.py` has no project component in the remote layout: `snapshots/<YYYYMMDDTHHMMSSZ>/pg.dump`, `manifest.json`, `parquet/<root basename>/`. Only `BACKUP_S3_BUCKET` and the crypt passwords select the remote.
- `deploy/soak.env.example` lists the same `BACKUP_*` names and says to fill them from the off-host secrets file, so a soak backup unit would normally push to the same bucket and crypt remote as `trading-backup`.
- In one remote the two projects form ONE snapshot series. Retention (`select_retained`, 7/4/6) keeps the newest snapshot per UTC day across both, so the next retention run deletes the earlier of the two daily dumps every day. A `pull` without `--snapshot` takes the newest snapshot of either project. Same-bucket with other crypt passwords fails the sentinel check.

The user decides between, for example, (a) a separate `BACKUP_S3_BUCKET` for the soak env file (its own sentinel through `deploy/backup.sh --init-remote`; Task 4 then only adds the unit pair and a RUNBOOK requirement), or (b) a project component in the remote layout (a code change of `src/ops/backup_remote.py` and of the restore and pull paths). This executor chose neither.

Everything else in Task 4 does not depend on the backup choice, but the plan puts the stop before the whole task, so none of it was done. A continuation runs Task 4 as written after the user's backup-layout decision: `restart: "unless-stopped"` for `paper`, the one-shot pin service (`restart: "no"`, `--pin-epoch` only), the `trading-soak-backup` unit pair, RUNBOOK 20.1/20.2/20.5, the "Restart drill before the pin" subsection and the DEPLOY_GUIDE.vi.md cards. Until then `paper` keeps `restart: "on-failure"`. The runtime side already supports both policies: SKIPPED holds under `--hold-on-refusal` and no service path exits 0 by itself.

## Re-check verdicts (evidence/16-55-recheck.md)

- `verdict WR-11 code: holds`. Before Task 3, a requested stop recorded RUNTIME_STOP and returned `ExitCode.OK` (`runtime.py` lines 1145 and 1155).
- `verdict WR-11 docker: verified`. Docker documentation as summarised by the planner (MEDIUM confidence, not verified live): `on-failure` does not restart after a daemon restart. The live proof is the 16-43 drill.
- `verdict WR-07 hang: holds`. The heartbeat probes only `src.data.collector --healthcheck` of project `trading`, and Docker never restarts an unhealthy container.
- `verdict WR-07 backup: holds`. `trading-backup.service` sets no project, so it dumps `trading`, while the soak evidence is in `trading-soak_pgdata`.
- B1-WR-07 re-check (Task 3 behaviour item): on the code before the guard, two `main` calls on one epoch with one shared in-memory state both reached RUNTIME_START. The output was `first exit 0 second exit [0]` and `RUNTIME_START count 3`, which counts the old pin run. After the guard the second call is refused with 8 before any record (`test_a_second_runtime_on_the_running_epoch_is_refused_before_any_record`).

## Recorded owner decisions (copied from 16-DEC-FIXPLANS.md by script)

- `decisions/16-DEC-RESTART-POLICY.md`: `option: Q1-unless-stopped-hold-skipped`, with the reviewer section "### Q1" byte-equal and correction 1.
- `decisions/16-DEC-HUNG-RUNTIME.md`: `option: Q2-second-monitor-check`, with `paper_heartbeat_interval_seconds: 60`, `paper_check_period_seconds: 60`, `paper_check_grace_seconds: 120`, the ping_url line and correction 2. Plan 16-56 Task 4 builds it.
- `decisions/16-DEC-PIN-COMMAND.md`: `option: Q3-pin-and-exit`, with the reviewer section "### Q3" byte-equal.

Each record has `decided by: user`, `date: 2026-10-16`, the source line (commit bdbdc11) and the user's line verbatim. All Task 2 verify commands passed: the verdict count is 4, all three option greps match, and the byte-equality check prints True for Q1, Q2 and Q3.

## Held-marker design

- One JSON file per container at `<pinned-state dir>/held-refusal-<container>.json`, which is `logs/paper/` on the logs volume. It holds the schema, the container name (`socket.gethostname()`, the container id under Docker), the pid, the exit code and the refusal class name (the `ExitCode` member name, or `SKIPPED`). It never holds an environment or configuration value. The write is atomic: a temporary file in the same directory, then `os.replace`.
- `_hold` writes the marker, calls `wait_for_stop`, and removes the marker in `finally`. It writes no record and builds no client, and the lease is released before the wait.
- `--healthcheck` reads its own container's marker first, before the start-gate checks and before any bar age, and exits 1 with the refusal class and code. A marker of another container is ignored. An unreadable own marker counts as held. The probe never removes a marker.
- A successful start of the same container removes a stale marker (one left by a killed hold) before RUNTIME_START. If the removal fails, the start fails closed with 7.
- If the marker cannot be written, the hold is not entered. The process exits with the refusal code, or with 7 for SKIPPED, never with 0, because a hold without the marker could look healthy.
- Exit-0 inventory (`test_every_return_of_main_is_a_known_kind`). Every `return` of `main` is one of `_healthcheck`, `_skip`, `_pinned_and_exit`, `_stopped_on_request`, `refuse` (never with `OK`), `_usage_error` or `_failed_closed`. Only the first four can yield 0. A behaviour test confirms that the service flags exit 0 only after a stop request.

## Instance lease

- `RuntimeStatePort.acquire_instance_lease(scope)` returns an `InstanceLease` (`is_held`, `release`) or None. In memory, the registry is per `InMemoryRuntimeState`, because one instance models one database. On PostgreSQL, `pg_try_advisory_lock(key)` runs on a connection detached from the pool (`OperationalDatabase.dedicated_connection`, new). `is_held` queries `pg_locks` on the holding session, and an error counts as lost. `release` unlocks and then closes. The key is the first 8 bytes of the SHA-256 of the scope, top bit cleared.
- `main` takes the lease after admission, the config and the port, before the pin branch and before any record, and releases it in `finally`. A held lease refuses with `ExitCode.INSTANCE_LEASE_HELD = 8`, which is in `REFUSAL_CODES` and is held under the flag.
- The live loop re-checks the lease at every consumer batch (before the batch writes), after every sleep of the existing constraint-refresh loop, and before every SHADOW poll step (a new `before_step` hook on `ShadowCoordinator.run_poller`). A lost or unverifiable lease fails closed with 7 and no RUNTIME_STOP. No new interval or number was added.
- **Known limit:** a lost lease is noticed only at the next consumer batch or periodic step. A verify query on a network-partitioned connection can block until TCP gives up; the separate paper heartbeat of plan 16-56 is what detects that hang.

## Deviations from Plan

### Auto-fixed / adjusted

1. **[Rule 4 avoided, design choice inside the plan's latitude] Lease scope.** The plan says the key is "derived from the epoch id" and that the lease is taken "before the pin branch". Both cannot hold, because `pin_stream_epoch` mints the epoch id from the opening time, so a pin knows its epoch only after pinning. The key is therefore derived from one fixed scope, `paper-runtime`, one lease per database. This is the reviewer's alternative in B1-WR-07 ("or a fixed paper-runtime key"). It is strictly stronger than per epoch: only the latest pin is runnable (REV-18), and a pin can never run beside any runtime of the database. Files: `src/paper/runtime_state.py`.
2. **[Rule 3] Files outside the plan's list.**
   - `src/persistence/uow.py` gained `dedicated_connection()`: the advisory lock needs a pool-detached connection.
   - `src/paper/shadow_runtime.py` gained the `before_step` hook on `run_poller`, so the lease check runs at the SHADOW poll step.
   - Test doubles and record counts in `tests/test_paper_runtime_loop.py`, `tests/test_paper_runtime_restart.py`, `tests/test_paper_market_inputs.py` and `tests/test_paper_shadow_runtime.py` changed. These tests assumed the old pin started and stopped a run. Two state wrappers also gained `acquire_instance_lease` delegation.
   - `tests/test_soak_compose.py` now asserts refusal codes {3,4,5,6,8}.
3. **[Rule 3] Compose comment in Task 3.** Adding code 8 to `REFUSAL_CODES` would have failed `test_compose_comment_names_every_refusal_code`, so the `paper` comment block in `docker-compose.yml` now names code 8 and the held marker. It also says that `unless-stopped` comes with Task 4. The restart policy itself is unchanged (`on-failure`).
4. **In-image check invocation.** `deploy/soak-image.sh` runs `-m scripts.check_image_paths --root /app` rather than the script path. With a script path, `sys.path[0]` would be `/app/scripts` and `import src` would fail. The in-image config path is held in one variable, `IN_IMAGE_RUNTIME_CONFIG`. The check also compares each set's hash with its allowlist entry (the runtime admission rule).
5. **Usage error as a return.** `--pin-epoch --hold-on-refusal` returns 2 through `_usage_error`, not through argparse's `SystemExit`, so it shows in the exit inventory and takes no lease.

## Verification

- Task 1 verify: test_deploy_images, test_deploy_scripts, test_soak_compose, test_soak_runbook and test_paper_start_gate gave 254 passed, 12 skipped (shellcheck not installed). Ruff passed on the script. `git diff --name-only 5f8269b HEAD -- params/` is empty.
- Task 2 verify: all five commands passed (see above).
- Task 3 verify: test_paper_runtime_instance_guard, held_state, compose, env, admission, start_gate, state_pg and state gave 213 passed, 20 skipped. The skips are PostgreSQL tests, because `TEST_DATABASE_URL` is unset and Docker is not running on this machine.
- Related targeted runs:
  - test_paper_runtime_loop, test_paper_runtime_restart and test_paper_market_inputs passed.
  - test_paper_replay_inputs, shadow_isolation, shadow_runtime, test_signal_rehearsal, soak_evidence_export, deploy_compose, deploy_guide_vi, soak_compose, soak_runbook, persistence_engine_timeouts, controller_rehydrate, runtime_pipeline and runtime_config_file passed after the count fixes.
  - The final combined run gave 344 passed, 20 skipped.
- `uv run ruff check src scripts tests`: all checks passed. `uv run ruff format --check src scripts tests`: 508 files already formatted. `uv run mypy src`: no issues in 187 source files.
- The full suite was not run (memory-limited machine; the plan names plan 16-59 Task 4 as the full-suite gate).

### Not testable here (proven on the soak host by plan 16-43)

The host-reboot and Docker-daemon-restart paths of the owner's decision cannot be exercised on this development machine: there is no Docker daemon, no host reboot and no network. Plan 16-43 must prove them in the restart drill on the soak host before the pin, together with the refused-start, process-crash and requested-stop paths. The RUNBOOK subsection "Restart drill before the pin" that lists the drill belongs to Task 4 and is not written yet.

## Known Stubs

None. No placeholder values or unwired data paths were introduced.

## Threat Flags

| Flag | File | Description |
| --- | --- | --- |
| threat_flag: file-write | src/paper/held_marker.py | New write on the logs volume (`logs/paper/held-refusal-<container>.json`). It holds only the container name, pid, code and class name, and is covered by T-16-136 and T-16-170 |
| threat_flag: db-session | src/persistence/paper_runtime_state.py | One extra long-lived PostgreSQL session per runtime, holding the advisory lock (T-16-134) |

## Broken-windows ledger

Two `unrun-verify` entries were appended to `.planning/WINDOWS.md`: (1) the PostgreSQL lease tests skipped without `TEST_DATABASE_URL`, and (2) Task 4 not executed.

## Self-Check: PASSED

- FOUND: scripts/check_image_paths.py, src/paper/held_marker.py, tests/test_paper_runtime_instance_guard.py, tests/test_paper_runtime_held_state.py, evidence/16-55-recheck.md, decisions/16-DEC-RESTART-POLICY.md, decisions/16-DEC-HUNG-RUNTIME.md, decisions/16-DEC-PIN-COMMAND.md
- FOUND commits: 52faa0a, 800231a, 32fa56d (measured: `git rev-list --count 1631a3d..HEAD` = 3)
