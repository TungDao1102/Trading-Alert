---
phase: 16-paper-runtime-composition
plan: 20
subsystem: ops / soak host
tags: [ec2, d042, collector-move, waiver, uat]

provides:
  - "evidence/16-20-acceptance.json: D042 acceptance, validator exit 0 (16 conditions PASS; 4 are USER WAIVERS, not verified)"
  - "evidence/16-20-migration.md: hand cutover CLEAN, OI gap window, verified pull (snapshot 20261010T031756Z), UAT 8 PASS, UAT 9/10 PARTIAL"
  - "decisions/16-DEC-O-12.md: waivers and deferrals with deadlines"
affects: [16-50 (unblocked), 16-40, 16-43]

actuals:
  tasks: 3
---

# Plan 16-20 Summary

Closed 2026-10-10 with user-decided waivers. Facts, in order of strength:

- Verified: cutover report CLEAN (0 files missing/changed, 0 watermarks lost); OI gap max 10 min on 2026-10-09 19:34-19:55Z (permanent coverage gap); RUNBOOK 19.5 pull/verify/restore all exit 0.
- Done by hand, not by `deploy/migrate.sh` (old host is Windows Docker Desktop with no SSH server).
- User statements without pasted proof: bootstrap.sh run on EC2 (UAT 8); backup timer fired at 03:15 UTC.
- WAIVED, not verified: PAID_PLAN and BUDGET_ALERT (switch to pay-as-you-go before ~2027-01-25), HEARTBEAT_MONITOR_ALERT_RECEIVED (verify after 16-50, before 16-43), BACKUP_REAL_S3_GATE (D064 still open although the timer already pushed a snapshot).
- Deferred from UAT 9/10: real two-host migrate.sh, real-bucket restore, Binance IP whitelist, off-VPS heartbeat monitor.
