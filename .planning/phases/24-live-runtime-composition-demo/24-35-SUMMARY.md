---
phase: 24-live-runtime-composition-demo
plan: 35
subsystem: deploy
tags: [compose, live, healthcheck, hold-on-refusal, restart-policy, OPS-02, OPS-03, D-01, D-03, O-2]
requires: [24-27, 24-30, 24-36, 24-25, 24-24]
provides:
  - "docker-compose.yml: the real `live` service (profile live, --hold-on-refusal, --healthcheck, db-upgrade dependency, livestate volume, no port, restart no)"
  - "tests/test_live_compose_service.py: docker-marked hold test"
  - "RUNBOOK 21.1c: start, inspect, hold, and how to enable the restart policy"
affects: [24-33]
key-files:
  created:
    - tests/test_live_compose_service.py
  modified:
    - docker-compose.yml
    - tests/test_deploy_compose.py
    - tests/docker_helpers.py
    - docs/operations/RUNBOOK.md
key-decisions:
  - "State volume `livestate` is mounted at /app/logs (not /app/logs/live): the image creates /app/logs owned by uid 10001, so a fresh named volume is writable; a mount at the non-existent /app/logs/live would be a root-owned mount point the runtime user cannot write. No Dockerfile change needed."
  - "restart stays \"no\"; the switch (`restart: unless-stopped`, then `docker compose --profile live up -d live`) and its condition (first clean Demo run) are written in the compose comment and RUNBOOK 21.1c."
metrics:
  tasks: 2
  completed: 2026-11-01
status: complete
actuals:
  tokens: 14000
  tasks: 2
  commits: 2
plan_head_before: 3360e659f6e6b026fa7d3a6a68dc9d2e742ebb45
plan_head_after: e91fb6e4
commits: 2
---

# Phase 24 Plan 35: Live compose service Summary

The compose `live` placeholder (a SystemExit command, no probe) is replaced by the real service: `python -m src.live.runtime --hold-on-refusal` with the `--healthcheck` probe, started only by hand from profile `live`, reading only `.env.live`, with its own state volume and restart policy off.

## What was built

- `docker-compose.yml` `live` service: `<<: *app` (image `trading-alert:${IMAGE_TAG:-dev}`, which bakes the limits files and the revision stamp, plans 24-25), env file `${TRADING_LIVE_ENV_FILE:-.env.live}` only (plan 24-30), `depends_on: db-upgrade: service_completed_successfully`, `restart: "no"`, healthcheck copying the paper service's interval 60s / timeout 15s / start period 6m / retries 3, no `ports`. New named volume `livestate` at `/app/logs` (state dir `logs/live` holds the gate state file, spill directory, liveness stamp and held marker). A comment states the restart switch and its condition.
- `tests/test_deploy_compose.py`: `test_placeholders_fail_fast_naming_the_owning_phase` (referenced only by itself and planning docs) replaced by `test_live_service_is_the_real_runtime_with_its_probe` (profile, command, restart no, image, depends_on, no ports, probe and timing equal to paper, the one mount, volume used by live alone, env file text) and `test_live_restart_policy_is_off_in_the_file_and_the_switch_is_documented`. Volume pins now allow `livestate` (five named volumes); the healthcheck-decision test pins the live probe.
- `tests/test_live_compose_service.py` (docker-marked): isolated project, empty live env file; the container runs, a held marker appears on the volume, `--healthcheck` exits non-zero with `healthy false`, `held true`, the refusal code and mode `UNRESOLVED`, `--liveness` exits non-zero, RestartCount 0, restart policy `no`, no port bindings, the log carries "live runtime refused" and the `LIVE_RUNTIME_MODE` name, and the container is unchanged a moment later (no crash loop). Torn down with volumes in a `finally`.
- `tests/docker_helpers.py`: `ComposeProject.compose` takes an optional `env` merged over the one-file defaults (needed for `TRADING_LIVE_ENV_FILE`).
- `docs/operations/RUNBOOK.md`: new 21.1c (commands, hold behaviour, restart-policy enabling steps); the stale "still a placeholder until plan 24-35" sentence in 11.1 replaced.

## Verification

- `uv run pytest -m "not docker"` on `test_deploy_compose`, `test_live_compose_env_split`, `test_deploy_docs`, `test_deploy_guide_vi`, `test_agents_md`, `test_soak_compose`, `test_deploy_images`, `test_paper_runtime_compose`, `test_dockerfile_revision_stamp`, `test_rehearsal_compose`: all pass.
- `TRADING_CI_STRICT=1 uv run pytest -m docker tests/test_live_compose_service.py`: 1 passed (RAN against Docker 29.8.0 on this machine, after `docker compose build db-upgrade` refreshed the stale `trading-alert:dev` image, which lacked `src.live`). No leftover containers or volumes.
- `ruff check` and `ruff format --check` on the three Python files: clean. `scripts/verify_decision_alignment.py all`: ALL_PASS. `git diff --exit-code -- pyproject.toml uv.lock`: exit 0. `git grep "live runner not implemented yet" -- docker-compose.yml`: empty. `docker-compose.yml` is LF.
- No `TEST_DATABASE_URL`, no `.env` read, no secret in repo.

## Deviations from Plan

**1. [Rule 3 - Blocking] `tests/docker_helpers.py` and `docs/operations/RUNBOOK.md` edited (not in files_modified)**
- helper: the live env file must be selected per test; added an optional `env` argument (backward compatible; cutover and drill tests re-use it unchanged and were not re-run).
- RUNBOOK: the 11.1 sentence calling the live service a placeholder became false; added 21.1c for the restart switch the plan requires documenting.

**2. State volume mount point.** The plan says "a named volume"; the mount is `livestate:/app/logs` (see key decisions) instead of a volume at `/app/logs/live`, to avoid a Dockerfile change.

**3. Local image rebuild.** `trading-alert:dev` on the shared Docker daemon was stale; rebuilt with a made-up revision stamp (40 hex, not a real commit) for the test run. A real build via `deploy/update.sh` stamps the true commit. The test skips (fails under strict CI) when the image lacks `src.live.runtime`.

## Owner steps

- Create `.env.live` (mode 0600) from `.env.live.example` on the host, then `docker compose --profile live up -d live`; check `--healthcheck` (RUNBOOK 21.1c). NOT_OBSERVED: no real Demo start here.
- After the first clean Demo run: change the live `restart:` line to `unless-stopped` and re-apply (RUNBOOK 21.1c). Also the host heartbeat from plan 24-24 (`deploy/heartbeat.sh --target live`) works only once this service runs; whether `docker compose exec` resolves the service without `--profile` on the host is still unconfirmed (from 24-24).

## Known Stubs

None.

## Threat Flags

None. T-24-100 (hold test, restart no), T-24-101 (no ports, env file only, pinned by tests), T-24-102 (named state volume), T-24-SC (`pyproject.toml` and `uv.lock` unchanged) are mitigated as planned.

## Self-Check: PASSED

Files found: docker-compose.yml, tests/test_live_compose_service.py, tests/test_deploy_compose.py, tests/docker_helpers.py, docs/operations/RUNBOOK.md. Commits e8a44e14 and e91fb6e4 are ancestors of HEAD.
