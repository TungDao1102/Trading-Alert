---
phase: 24-live-runtime-composition-demo
plan: 24
subsystem: ops
tags: [heartbeat, systemd, live, deploy, healthchecks]
requires: [24-01, 24-11]
provides:
  - "deploy/heartbeat.sh --target live (run, --set-url, --install-timer)"
  - "trading-live-heartbeat.service and .timer"
affects: [24-33]
tech-stack:
  added: []
  patterns: ["one external check per process (24-01 Q11)", "stub-first shell tests with a FAKE sentinel URL"]
key-files:
  created:
    - deploy/systemd/trading-live-heartbeat.service
    - deploy/systemd/trading-live-heartbeat.timer
  modified:
    - deploy/heartbeat.sh
    - tests/test_deploy_heartbeat.py
key-decisions:
  - "No target may use another target's default URL file (live refuses the collector's and the paper's, and both refuse the live file)."
  - "The probe is `docker compose exec -T live ... python -m src.live.runtime --liveness` with no --profile flag, the same shape as the paper probe."
requirements-completed: [OPS-02, OPS-03]
status: complete
commits: 1
plan_head_before: 17307cd08288d97d6bc482e258b1380955ec41f5
plan_head_after: c8d22486
actuals:
  tokens: 17000
  tasks: 2
  commits: 1
metrics:
  completed: 2026-10-31
---

# Phase 24 Plan 24: Live heartbeat target Summary

`deploy/heartbeat.sh --target live` gives the live process its own external check: it probes `python -m src.live.runtime --liveness` inside the compose `live` service and sends one success ping to its own monitor URL only while the probe passes.

## What was built

- **Script branch (`deploy/heartbeat.sh`)**: `--target live` selects service `live`, probe label "live liveness", default URL file `/etc/trading/heartbeat-live.url` (or `HEARTBEAT_LIVE_URL_FILE`), systemd credential `heartbeat-live-url`, units `trading-live-heartbeat.service` and `.timer`. The collector and paper paths are unchanged (all existing tests green).
- **Refusals (exit 2)**: `--target live --url-file` naming the collector's or the paper's default file; collector or paper naming the live file; `--soak-env-file` with live; `--install-timer` without `--interval-seconds` (no default for any target).
- **Units**: oneshot service with only `LoadCredential=heartbeat-live-url:@URL_FILE@` and `ExecStart=... heartbeat.sh --target live`, no link directives; timer with no catch-up and no random delay, interval from `--interval-seconds`.
- **Secret handling**: the URL is read by `--set-url` from standard input only, stored mode 0600, never an argument, never exported or logged; xtrace is still refused. FAKE sentinel asserted absent from stdout, stderr, stub log and unit files.
- **Tests**: 32 new live cases in `tests/test_deploy_heartbeat.py` (probe line, fail ping, only-docker-exec, own credential, no fallback to other URLs, env-var URL file, usage errors, set-url, install-timer, unit templates, LF in the index, full secret path, xtrace).

## Verification

- `uv run pytest -m "not docker" tests/test_deploy_heartbeat.py tests/test_deploy_scripts.py`: all pass (4 pre-existing skips).
- `shellcheck -x heartbeat.sh` (run from `deploy/`): exit 0. From the repo root, plain `shellcheck deploy/heartbeat.sh` only prints the info-level SC1091 (cannot follow `lib.sh`), which already existed before this plan.
- `ruff check` and `ruff format --check` on the test file: clean. `pyproject.toml` and `uv.lock` untouched. Script and new units are LF in the index (`eol=lf`).

## Deviations from Plan

None. Tasks 1 and 2 touch the same two files and were committed together in one commit (`c8d22486`).

## Notes for the owner and plan 24-33 (host steps, not claimed here)

- Create the healthchecks.io live check (period 60 s, grace 120 s recommended), then on the host: `sudo deploy/heartbeat.sh --target live --set-url` (URL on stdin) and `sudo deploy/heartbeat.sh --target live --install-timer --interval-seconds 60`.
- The `live` compose service carries `profiles: ["live"]`. The probe uses `docker compose exec -T live` without `--profile`, as the plan specifies and as the paper probe does for the paper profile. If `exec` on the host cannot resolve the service without the profile, set `COMPOSE_PROFILES=live` in the unit environment or add `--profile live` to the probe; this can only be confirmed with real Docker on the host.
- Also note `docker-compose.yml` still carries the Phase 24 placeholder command for `live`; the probe passes only once the live runtime plans have replaced it.

## Known Stubs

None.

## Threat Flags

None. Mitigations T-24-73, T-24-74, T-24-75 are covered by tests; T-24-SC: no dependency change.

## Self-Check: PASSED

Files exist (heartbeat.sh, both live units, the test file) and commit `c8d22486` is in HEAD history.
