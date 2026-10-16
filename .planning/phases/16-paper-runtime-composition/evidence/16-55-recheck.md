# 16-55 re-check of B1-WR-11 and B2-WR-07 (offline, 2026-10-16)

Re-checked by the executor of plan 16-55 Task 2 against the tree at commit 52faa0a (the Task 1 commit), offline: reading of the code and the compose file, no network, no Docker daemon. A verdict "does not hold" would be recorded with its note and would not reopen the owner's decision (16-DEC-FIXPLANS.md); none is "does not hold" here.

## B1-WR-11: a clean SIGTERM stop exits 0 while the paper service restarts only on failure

Code half. `src/paper/runtime.py` `main` (before this plan's Task 3): after `run_admitted` (or the injected `run_loop`) returns, which it does only after a requested stop (SIGTERM or SIGINT through `_wait_for_stop_signal`), `main` records RUNTIME_STOP (`port.record(_epoch_record(RuntimeEventType.RUNTIME_STOP, ...))`, line 1145) and falls through to `return int(ExitCode.OK)` (line 1155). `tests/test_paper_runtime_admission.py::test_clean_shutdown_records_runtime_stop_and_leaves_the_pinned_state_alone` exercises that path (the injected loop returns, RUNTIME_STOP is recorded, status 0). A failed loop returns 7 without RUNTIME_STOP; a refusal returns its code (3 to 6).

verdict WR-11 code: holds

Compose half. `docker-compose.yml` (before Task 4): the `paper` service has `restart: "on-failure"` (line 119); the `collector` service inherits `restart: unless-stopped` from the `x-app` anchor (line 19) and the `postgres` service sets it too (line 42). The paper comment block gives the reason (an empty allowlist exits 0, which `unless-stopped` would restart in a loop).

Docker half. Source: https://docs.docker.com/engine/containers/start-containers-automatically/ , read 2026-10-16, method: WebFetch summary by the planner of plan 16-55, not verified live. Facts quoted in the plan's objective:

- `on-failure` "doesn't restart the container if the daemon restarts";
- `always` restarts the container whenever it stops;
- `unless-stopped` is "similar to always, except that when the container is stopped (manually or otherwise), it isn't restarted even after Docker daemon restarts";
- a manual stop makes Docker ignore the restart policy until the daemon restarts or the container is restarted by hand.

So a paper container that exited 0 on the SIGTERM of a host shutdown, or that was running when the daemon restarted, is not brought back under `on-failure`. The documentation read makes this `verified` at MEDIUM confidence; the live proof is the restart drill that plan 16-43 runs on the soak host before the pin (RUNBOOK, "Restart drill before the pin", written by Task 4). The same row is in docs/SOURCES.md.

verdict WR-11 docker: verified

## B2-WR-07: nothing restarts or reports a hung paper runtime, and the backup unit covers the wrong project

Hang. `deploy/heartbeat.sh` `run_once` (lines 221-246) runs exactly one probe, `"${COMPOSE[@]}" exec -T "$SERVICE" "$PY" -m src.data.collector --healthcheck`, on the project that compose selects for the checkout: `deploy/systemd/trading-heartbeat.service` sets no `COMPOSE_PROJECT_NAME` and no `TRADING_ENV_FILE`, so the project is `trading` (`name: trading` in docker-compose.yml). No probe of the paper runtime, and no probe of project `trading-soak`, exists. Docker never restarts an unhealthy container (the Dockerfile HEALTHCHECK comment says so), and the `paper` healthcheck reports unhealthy only after the 3900 s bar age (`timing.healthcheck_max_bar_age_seconds` in config/paper/paper-runtime-v1.toml). A hung paper process (no exit) is therefore neither restarted nor reported. The owner's decision for this half is 16-DEC-HUNG-RUNTIME (Q2 = B, a separate paper heartbeat), built by plan 16-56 Task 4.

verdict WR-07 hang: holds

Backup. `deploy/systemd/trading-backup.service` runs `deploy/backup.sh` with `WorkingDirectory` the checkout and sets no `COMPOSE_PROJECT_NAME` and no `TRADING_ENV_FILE`; `deploy/backup.sh` runs `docker compose --profile ops run --rm -T backup ... -m src.ops.backup scheduled` through `compose_init`, so compose takes the project from `name: trading` and the env file from the checkout's `.env`. The dump (`pg_dump --format=custom` of the operational database, `src/ops/backup.py`) is therefore taken from the `postgres` service of project `trading` (volume `trading_pgdata`). The soak evidence lives in project `trading-soak` (volume `trading-soak_pgdata`, RUNBOOK 20.1, `deploy/compose-soak.sh`), which no unit backs up.

verdict WR-07 backup: holds

### Would two projects' dumps collide on the backup remote?

Yes, when the two projects use the same remote, which is the default way the soak env file is filled.

- The remote layout of `src/ops/backup_remote.py` has no project component: inside the crypt remote it is `_sentinel/sentinel.txt`, `snapshots/<YYYYMMDDTHHMMSSZ>/pg.dump`, `snapshots/<YYYYMMDDTHHMMSSZ>/manifest.json` and `parquet/<root basename>/...`. The remote is selected only by `BACKUP_S3_BUCKET` (`rclone_env`: `RCLONE_CONFIG_<crypt>_REMOTE = <s3 remote>:<bucket>`) and the crypt passwords; nothing names the compose project.
- `deploy/soak.env.example` lists the same `BACKUP_S3_*` and `BACKUP_CRYPT_*` names as `.env.example` and says to fill the values "from the off-host secrets file"; RUNBOOK 19.5 has the development machine hold "the same `BACKUP_*` configuration as the host". A soak backup unit that reads the soak env file filled that way pushes into the same bucket and the same crypt remote as the `trading` unit.
- In one remote, the snapshots of both projects form ONE series in `snapshots/`. Retention (`select_retained`, policy 7/4/6) keeps the newest snapshot of each UTC day, ISO week and month across that series, so on every day on which both projects back up, the next retention run deletes the earlier of the two snapshots of that day: one project's daily dump is lost every day. A `pull` without `--snapshot` takes the newest complete snapshot whatever its project, and a restore drill could restore the wrong database. Two pushes in the same second would also write the same `snapshots/<id>` directory.
- With a different bucket in the soak env file (a different `BACKUP_S3_BUCKET`, its own sentinel from `deploy/backup.sh --init-remote`), nothing collides: each remote has its own series and its own retention. Using the same bucket with different crypt passwords does not work at all: the sentinel check fails ("backup sentinel unreadable") and `--init-remote` refuses a non-empty bucket.

Consequence for the plan: the plan says "If the dumps of two projects would collide on the remote, stop before Task 4 and report (the remote layout is the user's)". Which layout the soak backup uses (a separate bucket for the soak project, or a project component in the remote layout, which is a code change of `src/ops/backup_remote.py`) is the user's decision, so the soak backup unit of Task 4 is not built until the user decides. Tasks 2 and 3 of plan 16-55 are not affected and proceed.
