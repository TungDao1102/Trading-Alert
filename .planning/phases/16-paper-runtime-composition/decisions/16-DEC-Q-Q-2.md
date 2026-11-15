# 16-DEC-Q-Q-2: cron minute of the hourly freeze check, second choice (quick task 261113-x91, Part 1)

option: off-hour-minute
decided by: user
date: 2026-11-13
supersedes: 16-DEC-Q-Q.md (minute 34, kept unchanged as the record of the trial of epoch ce6c0bbf)
source: quick task 261113-x91 description (owner instruction relayed by the orchestrator; the owner's original message is not in the repository)
cron: 17 * * * *
words:
> Part 1 (small): change the cron minute in .github/workflows/paper_freeze_check.yml from `34 * * * *` to `17 * * * *`, and update every place that pins the cron string (config, evaluator input, tests, RUNBOOK, docs) so evaluator SCHEDULE_MISMATCH still matches; no other change.

context (recorded for audit): the trial of epoch ce6c0bbf (2026-10-25 to 2026-11-08) had 9 EVIDENCE_GAP slots out of 336. Seven came from GitHub at minute 34: 5 RUN_LATE_BEYOND_GRACE and 2 NO_RUN_FOUND, with 00:34 UTC late every day and p95 lateness 19.4 min (`evidence/16-43-trial-evaluation-2026-11-08.md`). The effect of minute 17 on delayed or dropped runs is unproven (G15), and a missing or late tick is still an EVIDENCE_GAP (D065 item 4). `freeze_tick_grace_seconds` (1800), the slot interval and the hourly form are unchanged. The schedule takes effect only on `master` (G15), so the next epoch pin waits until `origin/master` carries it. Part 2 (the host tick) is a separate owner decision (`16-DEC-HOST-TICK.md`).
