# 16-20 migration evidence (O-11 ii) - PARTIAL, plan 16-20 NOT closed

## Method (deviation from plan)
`deploy/migrate.sh` was NOT used. The old host is Windows Docker Desktop with no SSH server, so the script's reverse-SSH precondition (guide 5.3.3) is not met. The user moved the collector by hand on 2026-10-09:
stop local collector (freeze) -> `pg_dump --data-only` of the 2 watermark/gap tables -> tar of 7810 Parquet files (32 MB) -> scp to EC2 -> clear the 2 fresh EC2 volumes -> load SQL + untar -> verify -> `docker compose up -d`.
The verification used the project's own `python -m src.ops.cutover report` on EC2 against fingerprints/watermarks taken on both sides.

## Cutover report (pasted by the user, exit 0)
CUTOVER VERDICT: CLEAN. Files: 0 missing, 0 changed, 0 added since the switch. Watermarks: 0 lost, 0 regressed.
Threshold: --max-gap-minutes 180.

## OI gap
Window: 2026-10-09T19:34:49Z .. 2026-10-09T19:55:00Z. This is a coverage gap: open-interest snapshots cannot be fetched later, so the dataset must not be called full history.
Largest gap per symbol is 10 min for all 18 symbols as listed in the pasted report.
Main hole per symbol: about 19:49:55-19:49:58Z .. 19:55:00Z (1 slot). DOGSUSDT has one extra hole 19:34:49Z .. 19:39:52Z (1 slot).
Funding gaps are recoverable by the funding sweep.

## UAT 8
PASS (user statement 2026-10-10): `deploy/bootstrap.sh` was run on the EC2 host. Consistent with the PASS entries SSH_KEY_ONLY, SUDO_WITH_PASSWORD and ENV_FILE_MODE_0600 in 16-20-acceptance.json (command output pasted earlier). The dry-run output was not provided.

## UAT 9
PARTIAL (user decision 2026-10-10, option 1): the real cutover was done by hand (migrate.sh not usable, see Method) and reported CLEAN; the systemd backup timer fired by itself at 03:15 UTC (snapshot 20261010T031756Z; user statement, no journal excerpt yet). `migrate.sh` itself was not exercised on two real hosts: deferred, not run.

## UAT 10
PARTIAL (user decision 2026-10-10, option 1): provider disk encryption is PASS (EBS_ROOT_VOLUME_ENCRYPTED, EBS_ENCRYPTED_BY_DEFAULT). Deferred, not run: restore of a real bucket onto an empty host (before the first real restore, with D064); Binance key IP whitelist without withdrawal permission (before real keys go into .env, WR-06); off-VPS heartbeat monitor (after 16-50, before 16-43).

## D064 real-S3 gate
OPEN (user waiver in 16-DEC-O-12): formal `rclone cryptcheck` proof on the real S3 not done. The systemd timer already pushed snapshot 20261010T031756Z and the pull verified it (see pull); the formal proof is still owed.

## pull
RUNBOOK 19.5 run on the development machine, 2026-10-10 (dest pull-20261010T085546Z):
- `pull`: pull-OK snapshot=20261010T031756Z
- `verify`: verify-OK, exit 0 (verified)
- `restore --skip-db --force`: restore-OK copied=1608 skipped=7810 database_restored=False, exit 0
Snapshot id: 20261010T031756Z. The 7810 skipped files are the ones already on the development machine, matching the 7810 Parquet files moved at cutover.

RESOLVED (user, 2026-10-10): the snapshot came from the systemd backup timer on the EC2 host, which fired by itself at 03:15 UTC (the timer is daily at 03:15 UTC). It was not a manual run. This is evidence for the timer half of UAT 9 (timer fired unattended); the user's statement is not yet backed by a pasted `systemctl list-timers` / journal excerpt.
Consequence: a real backup ran while the D064 real-S3 gate (`BACKUP_REAL_S3_GATE`) was still waived-open. The pull above verified the whole bundle against its manifest SHA-256 end to end through the crypt remote, which is practical evidence the chain works, but it is not the formal D064 proof (cryptcheck on the real S3, multipart included). Gate stays open until the user records that proof.
