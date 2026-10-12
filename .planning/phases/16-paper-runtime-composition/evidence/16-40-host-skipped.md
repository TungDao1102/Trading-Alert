# 16-40 Task 2: fail-closed start on the soak host (empty allowlist)

Observed by the user on 2026-10-12, reported to the orchestrator, written from the user's pasted output.

## Commit

4a16da8b48aa3181ccf4a2b2f5fc1ebb5a93802d (built by deploy/soak-image.sh from a clean `git worktree` checkout, as the main checkout has untracked files)

## Image id

trading-alert:4a16da8b48aa3181ccf4a2b2f5fc1ebb5a93802d
sha256:caf95ef20c2802e1eaeafd8a1df97c3a82a7a72d14e1ae9841b15ad5b70658ca (APP_IMAGE_ID of .deploy/soak-image.env, equal to `docker image inspect`)

## Log excerpt

Command: `IMAGE_TAG=<commit> TRADING_ENV_FILE=<soak env outside the checkout> deploy/compose-soak.sh --profile paper up -d --no-build`

```
paper-1  | {"event": "SKIPPED (allowlist empty)", "level": "info", "timestamp": "2026-10-12T15:16:42.613049Z"}
```

Container state afterwards: `trading-soak-paper-1` exited, restart policy on-failure, not restarted. `db-upgrade` exited 0, `postgres` healthy. The `collector` service also started (it depends only on db-upgrade) and was Up (health: starting).

## Exit code

0 (`docker inspect --format '{{.State.ExitCode}}' trading-soak-paper-1`; state exited)

## Notes

- A first `up` attempt left the containers in state Created and `db-upgrade` failed with "failed to resolve host 'postgres'" (stale project network). `deploy/compose-soak.sh down` (without volumes) followed by the same `up` fixed it. No volume was removed.
- The soak env file lives outside the checkout; no value of it is recorded here.
