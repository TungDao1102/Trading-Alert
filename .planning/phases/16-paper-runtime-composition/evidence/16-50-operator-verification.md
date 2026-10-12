# 16-50 operator verification of the external heartbeat

Written by the orchestrator from the user's report of 2026-10-12. The orchestrator did not observe any of it.

## User statement (verbatim)

"phần healthcheck tôi đã test full. nó chạy ok, có thể đánh done"

## What was configured (user report, values from decisions/16-DEC-O-12.md)

- Service: healthchecks.io. Ping interval 300 s, check period 5 minutes, grace 10 minutes (set by the user on 2026-10-12).
- Sender: `deploy/heartbeat.sh` (`--set-url`, `--install-timer --interval-seconds 300`) on the EC2 host in `/opt/trading`. The ping URL is not recorded here.
- The user said the full test passed (timer running, check green, and the alert test). The user gave no UTC times.

## Not recorded (the user gave none; these stay UNVERIFIED sub-points)

- UTC times of the collector stop, of the alert received, of the start and of the recovery notice (plan 16-50, step 6 of the operator verification).
- The systemd version (`systemctl --version`).
- Whether the delivered credential worked for the `trading` user.

## Status

The user marks the heartbeat monitor verification done. `HEARTBEAT_MONITOR_ALERT_RECEIVED` was waived "USER WAIVER (not verified)" in `evidence/16-20-acceptance.json`; that row is not edited here. This file is the user's statement, not an independent observation.
