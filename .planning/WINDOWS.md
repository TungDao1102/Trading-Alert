---
schema_version: 1
open_count: 2
waived_count: 0
fixed_count: 1
total_count: 3
last_updated: 2026-10-16T08:50:33.123Z
---

# Broken Windows Ledger

> Cross-phase defect register. With `workflow.windows_enforce` enabled, `/gsd-ship` blocks while `open_count > 0`.
> Waive with `gsd-tools windows waive <id> "<reason>"` (reason required).
> Mark fixed with `gsd-tools windows fixed <id>`.

| id | phase | kind | file | line | description | status | reason | recorded_at | resolved_at |
|----|-------|------|------|------|-------------|--------|--------|-------------|-------------|
| 1 | 16 | unrun-verify | tests/test_paper_runtime_state_pg.py |  | 16-55 PG lease tests (second instance refused, lease ends with the connection, terminated backend fails the runtime closed) skipped: no TEST_DATABASE_URL on the dev machine | open |  | 2026-10-16T08:35:22.568Z |  |
| 2 | 16 | unrun-verify | docker-compose.yml |  | 16-55 Task 4 not executed (stopped per plan: soak and trading backups would collide on one remote): unless-stopped, one-shot pin service, trading-soak backup unit, RUNBOOK restart drill pending | fixed |  | 2026-10-16T08:35:23.461Z | 2026-10-16T08:50:20.986Z |
| 3 | 16 | unrun-verify | docs/operations/RUNBOOK.md |  | 16-55 restart drill (refused start, requested stop, process crash, host reboot, Docker daemon restart) not runnable on the dev machine; proven only by the plan 16-43 drill on the soak host before the pin (RUNBOOK 20.8) | open |  | 2026-10-16T08:50:33.123Z |  |

````json
[
  {
    "id": 1,
    "kind": "unrun-verify",
    "phase": "16",
    "file": "tests/test_paper_runtime_state_pg.py",
    "line": null,
    "description": "16-55 PG lease tests (second instance refused, lease ends with the connection, terminated backend fails the runtime closed) skipped: no TEST_DATABASE_URL on the dev machine",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-10-16T08:35:22.568Z",
    "resolved_at": null,
    "milestone": "v0.3"
  },
  {
    "id": 2,
    "kind": "unrun-verify",
    "phase": "16",
    "file": "docker-compose.yml",
    "line": null,
    "description": "16-55 Task 4 not executed (stopped per plan: soak and trading backups would collide on one remote): unless-stopped, one-shot pin service, trading-soak backup unit, RUNBOOK restart drill pending",
    "status": "fixed",
    "reason": "",
    "recorded_at": "2026-10-16T08:35:23.461Z",
    "resolved_at": "2026-10-16T08:50:20.986Z",
    "milestone": "v0.3"
  },
  {
    "id": 3,
    "kind": "unrun-verify",
    "phase": "16",
    "file": "docs/operations/RUNBOOK.md",
    "line": null,
    "description": "16-55 restart drill (refused start, requested stop, process crash, host reboot, Docker daemon restart) not runnable on the dev machine; proven only by the plan 16-43 drill on the soak host before the pin (RUNBOOK 20.8)",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-10-16T08:50:33.123Z",
    "resolved_at": null,
    "milestone": "v0.3"
  }
]
````
