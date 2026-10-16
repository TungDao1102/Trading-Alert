---
phase: 16-paper-runtime-composition
plan: 55
subsystem: paper-runtime-deploy
status: complete
tags: [paper-runtime, docker, single-instance, advisory-lock, held-marker, pin-and-exit, backup, B2-CR-05, B1-WR-07, B1-WR-11, B2-WR-07]
requires: [16-32, 16-33, 16-50]
provides:
  - runtime image carries params/ and config/paper/, with an in-image load check before the build record
  - instance lease per database (PostgreSQL session advisory lock), refusal code 8
  - held, non-operational refused start with an explicit per-container held marker
  - --pin-epoch pins and exits 0 without RUNTIME_START, from the one-shot paper-pin service
  - paper service restart unless-stopped
  - trading-soak-backup unit pair with its own bucket guard
  - RUNBOOK 20.8 restart drill for plan 16-43
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
    - deploy/systemd/trading-soak-backup.service
    - deploy/systemd/trading-soak-backup.timer
    - tests/test_paper_runtime_instance_guard.py
    - tests/test_paper_runtime_held_state.py
    - .planning/phases/16-paper-runtime-composition/evidence/16-55-recheck.md
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-RESTART-POLICY.md
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-HUNG-RUNTIME.md
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-PIN-COMMAND.md
  modified:
    - Dockerfile
    - docker-compose.yml
    - deploy/soak-image.sh
    - deploy/soak.env.example
    - deploy/backup.sh
    - src/paper/runtime.py
    - src/paper/runtime_config.py
    - src/paper/runtime_state.py
    - src/paper/shadow_runtime.py
    - src/persistence/paper_runtime_state.py
    - src/persistence/uow.py
    - config/paper/README.md
    - docs/operations/RUNBOOK.md
    - docs/operations/DEPLOY_GUIDE.vi.md
    - docs/SOURCES.md
key-decisions:
  - "Lease scope is one fixed paper-runtime scope per database, not the epoch id: the epoch id hashes the opening time, so a pin cannot know it before it holds the lease"
  - "A held refusal releases the lease before it waits, so the one-shot pin can run beside a held container"
  - "A hold whose marker cannot be written is never entered: refusal code, or 7 for SKIPPED, never 0"
  - "Soak backups go to a separate BACKUP_S3_BUCKET with its own crypt passwords and --init-remote (orchestrator choice, option a); --install-soak-timer refuses an empty or shared bucket; no change to src/ops/backup_remote.py"
duration: about 120 minutes
completed: 2026-10-16
commits: 5
plan_head_before: 1631a3d76e9e849efd1f2ab6b1d05deb215157ac
plan_head_after: ebba3cb
actuals:
  tokens: 59000
  tasks: 4
  commits: 5
---

# Phase 16 Plan 55: Image and deploy Summary

What plan 16-55 delivers:
- The soak image carries `params/` and `config/paper/`. `deploy/soak-image.sh` loads both inside the built image with `--network none` before it records the build.
- One paper runtime runs per database. An instance lease (a PostgreSQL session advisory lock) is taken before the pin and before any record.
- A refused start, SKIPPED included, holds without writing anything. It leaves a held marker, so the healthcheck reports it unhealthy.
- `--pin-epoch` pins and exits 0. It runs from the one-shot `paper-pin` service (`restart: "no"`).
- The `paper` service restarts with `unless-stopped`.
- The soak database has its own backup unit, which writes to its own bucket.
- RUNBOOK 20.8 holds the five-path restart drill that plan 16-43 runs on the soak host before the pin.

## Tasks

| Task | Name | Commit |
| --- | --- | --- |
| 1 | Tracer: params/ and config/paper/ in the image, static path test, in-image load check (B2-CR-05) | 52faa0a |
| 2 | Re-check B1-WR-11 and B2-WR-07, the three decision records, SOURCES row | 800231a |
| 3 | Instance lease, held refused start with marker, pin-and-exit, exit-0 inventory (B1-WR-07) | 32fa56d |
| 4 | unless-stopped, one-shot pin service, trading-soak backup unit, RUNBOOK 11.4/20.1/20.2/20.5/20.8, DEPLOY_GUIDE cards (B1-WR-11, B2-WR-07) | ebba3cb |

An intermediate summary commit (6ede5fa) recorded the stop before Task 4. This file replaces it.

## Backup-remote decision (recorded for the owner to confirm)

The Task 2 re-check found that the soak and trading backups would collide on one remote (evidence/16-55-recheck.md):
- The remote layout of `src/ops/backup_remote.py` has no project component.
- On a shared bucket, the two projects form one snapshot series.
- Retention keeps the newest snapshot per UTC day, so it would delete one project's daily dump every day.

The plan says to stop before Task 4 in that case, because the remote layout is the user's. The executor stopped and reported. The orchestrator then chose **option (a)** as a minor ops choice and resumed Task 4. The orchestrator verified the finding in `backup_remote.py`. This choice was made by the orchestrator, not stated by the user; the owner may still override it.

What option (a) means:
- The soak env file names a **separate `BACKUP_S3_BUCKET`** with its own crypt passwords.
- That bucket is initialised once with `COMPOSE_PROJECT_NAME=trading-soak TRADING_ENV_FILE=<soak.env> deploy/backup.sh --init-remote`.
- `src/ops/backup_remote.py` is not changed.

How it is enforced:
- `deploy/backup.sh --install-soak-timer --soak-env-file <path>` refuses an empty soak bucket. It also refuses a soak bucket equal to the bucket in the trading env file (`TRADING_BACKUP_ENV_FILE`, default the checkout's `.env`). It compares values and prints names only.
- `deploy/soak.env.example` keeps `BACKUP_S3_BUCKET=` empty. A comment there says it must be the soak project's own bucket, never the one `trading-backup` uses (covered by a static test).
- RUNBOOK 11.4 and 20.5 state the rule.

**Owner action (not a blocker):** create the second bucket for the soak project before plan 16-43 on EC2, with its own crypt passwords, then run `--init-remote` for the soak project. The other remaining owner input is the second secret heartbeat URL (16-DEC-HUNG-RUNTIME).

## Re-check verdicts (evidence/16-55-recheck.md)

- `verdict WR-11 code: holds`. Before Task 3, a requested stop recorded RUNTIME_STOP and returned 0.
- `verdict WR-11 docker: verified` (MEDIUM). Docker documentation, as summarised by the planner, says `on-failure` does not restart a container after a daemon restart. The live proof is the 16-43 drill.
- `verdict WR-07 hang: holds`. The heartbeat probes only the collector of project `trading`. The separate paper heartbeat is built by plan 16-56 Task 4.
- `verdict WR-07 backup: holds`. `trading-backup` dumps project `trading`, not `trading-soak_pgdata`. Fixed in Task 4.
- B1-WR-07 re-check, before the guard: two `main` calls on one epoch, sharing one in-memory state, both reached RUNTIME_START. The output was `first exit 0 second exit [0]`, `RUNTIME_START count 3`, where the count includes the old pin run. After the guard, the second call is refused with 8 before any record.

## Recorded owner decisions (copied by script from 16-DEC-FIXPLANS.md)

- `decisions/16-DEC-RESTART-POLICY.md`: `option: Q1-unless-stopped-hold-skipped`, with correction 1.
- `decisions/16-DEC-HUNG-RUNTIME.md`: `option: Q2-second-monitor-check`, with interval 60, period 60, grace 120, the ping_url line and correction 2. Built by plan 16-56.
- `decisions/16-DEC-PIN-COMMAND.md`: `option: Q3-pin-and-exit`.

Each record carries `decided by: user`, `date: 2026-10-16`, the source (commit bdbdc11) and the user's line verbatim. Each reviewer section is byte-equal to the source, and every Task 2 verify command passed.

## Held-marker design

- **The file.** One JSON file per container, `held-refusal-<container>.json`, in the directory of the pinned-state file (`logs/paper/`). It holds the schema, the container name (`socket.gethostname()`), the pid, the exit code and the refusal class name. It never holds an environment or configuration value. It is written atomically (a temporary file, then `os.replace`).
- **The hold.** `_hold` writes the marker, waits for the stop and removes the marker in `finally`. It writes no record and builds no client. The lease is released before the wait.
- **The probe.** `--healthcheck` checks this container's marker first, before the gate checks and before any bar age. A marker of another container is ignored, an unreadable own marker counts as held, and the probe never removes a marker.
- **A stale marker.** The next successful start of the same container removes it before RUNTIME_START. If the removal fails, the start fails closed with 7.
- **No invisible hold.** If the marker cannot be written, the process exits with the refusal code, or with 7 for SKIPPED, never with 0.
- **Exit-0 inventory.** Every `return` of `main` is one of `_healthcheck`, `_skip`, `_pinned_and_exit`, `_stopped_on_request`, `refuse` (never `OK`), `_usage_error` or `_failed_closed`. Only the first four can give 0. A behaviour test confirms that the service flags exit 0 only after a stop request. The compose test checks that the service command carries `--hold-on-refusal` and never `--pin-epoch`, and that only `paper-pin` passes `--pin-epoch`.

## Instance lease

- **Port method.** `RuntimeStatePort.acquire_instance_lease(scope)` returns an `InstanceLease` (`is_held`, `release`) or None.
- **In memory.** One registry per state instance, which models one database.
- **PostgreSQL.** `pg_try_advisory_lock` runs on a connection detached from the pool (`OperationalDatabase.dedicated_connection`). `is_held` queries `pg_locks` on the holding session, and any error counts as lost. `release` unlocks, then closes.
- **Key.** The key comes from one fixed scope, `paper-runtime`: the first 8 bytes of a SHA-256, with the top bit cleared.
- **In `main`.** The lease is taken after admission, the configuration and the port, and before the pin or any record. It is released in `finally`. A held lease is a refusal with `INSTANCE_LEASE_HELD = 8`.
- **In the loop.** The lease is re-checked at every consumer batch, at every constraint-refresh step and before every SHADOW poll step (a new `before_step` hook on `run_poller`). A lost lease gives exit 7 and no RUNTIME_STOP.
- **Known limit:** a lost lease is noticed only at the next batch or periodic step. A verify query on a network-partitioned connection can block until TCP gives up. The paper heartbeat of plan 16-56 detects such a hang.

## Deviations from Plan

1. **Lease scope:** one fixed scope per database instead of the epoch id. The pin mints the epoch id from the opening time, so a pin could not know its key before it must already hold the lease. This is the reviewer's alternative in B1-WR-07, and it is stricter than one lease per epoch.
2. **[Rule 3] Files outside the list:**
   - `src/persistence/uow.py` gained `dedicated_connection()`.
   - `src/paper/shadow_runtime.py` gained the `before_step` hook on `run_poller`.
   - Record counts or test doubles changed in `tests/test_paper_runtime_loop.py`, `tests/test_paper_runtime_restart.py`, `tests/test_paper_market_inputs.py`, `tests/test_paper_shadow_runtime.py` and `tests/test_paper_runtime_admission.py`, because the pin no longer starts a run.
   - `tests/test_soak_compose.py` now expects refusal codes {3, 4, 5, 6, 8}.
3. **In-image check:** it runs as `-m scripts.check_image_paths`; a script path cannot import `src`. The check also compares each set's hash with its allowlist entry.
4. **Usage error:** `--pin-epoch --hold-on-refusal` returns 2 through `_usage_error` (no `SystemExit`), so it shows in the exit inventory and takes no lease.
5. **Stop and resume around Task 4:** the plan's stop rule fired on the backup collision. Task 4 resumed after the orchestrator's option (a). The bucket guard in `deploy/backup.sh` (`--install-soak-timer` refuses an empty or shared bucket) is an addition the orchestrator asked for.
6. **Pin service name and profile:** `paper-pin`, in its own profile `paper-pin`. RUNBOOK 20.1 runs it with `deploy/compose-soak.sh --profile paper-pin run --rm paper-pin`, and starts the managed service as the very next command.
7. **Other doc updates:** RUNBOOK 11.4 documents the new `backup.sh` flags, because `tests/test_deploy_docs.py` requires every flag in its section. DEPLOY_GUIDE.vi.md updates the section 10 service table (`paper` row, new `paper-pin` row, heading now "Tám service") and the section 14 rows.

## Verification

- **Task 1:** 254 passed, 12 skipped (shellcheck not installed). `params/` is unchanged since 5f8269b.
- **Task 2:** all five verify commands passed.
- **Task 3:** the verify set gave 213 passed, 20 skipped. The skips are PostgreSQL tests: `TEST_DATABASE_URL` is unset and Docker is not running. The related loop, restart, market-inputs and shadow tests passed.
- **Task 4:**
  - RED first: 6 compose tests and 5 RUNBOOK tests failed before the change, and so did 4 guide tests. The backup-unit tests were written before the units but first run after them.
  - GREEN: test_soak_compose, paper_runtime_compose, deploy_backup_scripts, soak_runbook, deploy_docs, deploy_guide_vi, deploy_compose, deploy_scripts and deploy_images gave 343 passed, 12 skipped (shellcheck).
  - `git diff --quiet 5f8269b HEAD -- deploy/systemd/trading-backup.* deploy/systemd/trading-heartbeat.* deploy/heartbeat.sh params/` exits 0.
- **Checks:** `ruff check src scripts tests` passed; `ruff format --check` reports 508 files formatted; `mypy src` found no issues in 187 files.
- **No full suite** was run (memory-limited machine; plan 16-59 Task 4 is the full-suite gate).

### Proven only on the soak host (plan 16-43)

The development machine has no Docker daemon, cannot reboot the host and has no network. So the restart drill of RUNBOOK 20.8 is proven only by the 16-43 drill on the soak host before the pin. The drill covers five paths: refused start, requested stop, process crash, host reboot and Docker daemon restart. The PostgreSQL lease tests run only where `TEST_DATABASE_URL` is set. Both gaps are recorded as `unrun-verify` entries in `.planning/WINDOWS.md`. The Task 4 entry recorded at the stop is now marked fixed.

## Known Stubs

None.

## Threat Flags

| Flag | File | Description |
| --- | --- | --- |
| threat_flag: file-write | src/paper/held_marker.py | New write on the logs volume (container name, pid, code and class only; T-16-136, T-16-170) |
| threat_flag: db-session | src/persistence/paper_runtime_state.py | One long-lived PostgreSQL session per runtime, holding the advisory lock (T-16-134) |
| threat_flag: secret-read | deploy/backup.sh | `--install-soak-timer` reads `BACKUP_S3_BUCKET` from two env files to compare them; the values are never printed (T-16-137) |

## Self-Check: PASSED

- FOUND: scripts/check_image_paths.py, src/paper/held_marker.py, deploy/systemd/trading-soak-backup.service, deploy/systemd/trading-soak-backup.timer, the two new test files, evidence/16-55-recheck.md, the three decision records
- FOUND commits: 52faa0a, 800231a, 32fa56d, 6ede5fa, ebba3cb (measured: `git rev-list --count 1631a3d..HEAD` = 5 before this metadata commit)
