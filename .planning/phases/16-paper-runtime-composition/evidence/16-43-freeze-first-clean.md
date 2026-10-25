# 16-43 — first clean freeze tick after the pin

Evidence that the hourly freeze check (`.github/workflows/paper_freeze_check.yml`, cron
`34 * * * *`) writes a `clean` line for the pinned epoch of the soak.

## Context

- Pinned epoch: `ce6c0bbf27f080a6843c62dcedfd336e6d90b918ca08203912035235e9f83eda`
  (opened 2026-10-25T12:37:43.833841+00:00, `trend-pullback` / `research-run-1-a01`,
  parameter_set_hash `6f42f70e7e7a107b1be02fc4079fbb70f1408b4307099aa253bd93ebdbce6d87`).
- Pin file committed on develop (`5bc93d8c`) and on master (`6c759ef6`, "commit the pinned epoch").
- Defect found: `src/paper/freeze.py` had no `__main__` guard, so `python -m src.paper.freeze`
  exited 0 without running the check. Runs `40194725860`, `40198757199` and `40203425195`
  wrote no line and uploaded no artifact, while reporting success.
- Fix: `ddcc4930` "fix(16-43): run the freeze check when the module is executed" (regression
  test `test_module_entry_point_runs_the_check`), merged to master as `d9907ffc` (PR #2).

## First clean tick

| Field | Value |
|---|---|
| GitHub run | `40208128985` (schedule, `createdAt` 2026-10-25T15:41:26Z) |
| Conclusion | success |
| Checked out commit | `d9907ffcd02e00591e91f52945a10d361e52832b` |
| Artifact | `registry-diff-40208128985`, file `registry_diff.jsonl` |

Line read from the artifact (single line):

```json
{"checked_at_utc":"2026-10-25T15:42:02.545949+00:00","current_hash":"6f42f70e7e7a107b1be02fc4079fbb70f1408b4307099aa253bd93ebdbce6d87","epoch_id":"ce6c0bbf27f080a6843c62dcedfd336e6d90b918ca08203912035235e9f83eda","outcome":"clean","pinned_hash":"6f42f70e7e7a107b1be02fc4079fbb70f1408b4307099aa253bd93ebdbce6d87","run_metadata":{"commit":"d9907ffcd02e00591e91f52945a10d361e52832b","event_name":"schedule","run_attempt":"1","run_id":"40208128985","schedule":"34 * * * *"}}
```

Checks against the expected clean line:

- `outcome` = `clean`
- `epoch_id` = pinned epoch
- `pinned_hash` = `current_hash`
- `run_metadata.event_name` = `schedule`, `schedule` = `34 * * * *`, `run_id` matches the run

## Not yet covered

- Subsequent hourly ticks: to be recorded as they arrive.
- Earlier failed ticks (`40194725860`, `40198757199`, `40203425195`) are not a clean tick; they ran the
  unfixed module and are kept as history.
