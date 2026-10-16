---
schema_version: 1
open_count: 11
waived_count: 0
fixed_count: 1
total_count: 12
last_updated: 2026-10-16T14:37:27.945Z
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
| 4 | 16 | unrun-verify | tests/test_paper_test_signal_rehearsal.py | 584 | 16-56: the PostgreSQL test of the test-signal rehearsal on the v2 configuration skipped (no TEST_DATABASE_URL); make_sync_engine of the state port against a real database is unproven on the dev machine | open |  | 2026-10-16T09:39:52.126Z |  |
| 5 | 16 | unrun-verify | deploy/heartbeat.sh |  | 16-56 paper heartbeat: live ping delivery, the heartbeat-paper-url systemd credential and the 60 s timer are operator verification on the soak host before plan 16-43 (owner creates the second check, period 60 s, grace 120 s, and stores its URL with --target paper --set-url) | open |  | 2026-10-16T09:39:52.894Z |  |
| 6 | 16 | unrun-verify | src/paper/runtime.py |  | 16-56 silence watchdog proven only with fakes (fake SDK client, injected feed clock and sleep); a real half-open Binance connection and the 120 s bound on live time are first exercised on the soak host (plan 16-43) | open |  | 2026-10-16T09:39:53.728Z |  |
| 7 | 16 | unrun-verify | deploy/heartbeat.sh |  | 16-56: shellcheck not installed on the dev machine (12 shellcheck tests skipped in the deploy test set) | open |  | 2026-10-16T09:39:54.524Z |  |
| 8 | 16 | unrun-verify | tests/test_paper_replay_inputs.py | 1185 | 16-57: PostgreSQL round trip of the replay-inputs and history records skipped (no TEST_DATABASE_URL); the extra PAPER_HISTORY_BARS records of B1-CR-02 (one flush before each heartbeat and gap) are proven in memory only | open |  | 2026-10-16T10:18:40.859Z |  |
| 9 | 16 | unrun-verify | tests/test_paper_runtime_restart_pg.py |  | 16-57: the three PostgreSQL restart tests skipped (no TEST_DATABASE_URL); the shared gap ledger, the post-start seam backfill and the configuration identity in EPOCH_PINNED/RUNTIME_START are proven on the in-memory port only | open |  | 2026-10-16T10:18:41.746Z |  |
| 10 | 16 | unrun-verify | tests/test_soak_evidence_export.py | 818 | 16-57: the PostgreSQL test of the soak evidence export skipped (no TEST_DATABASE_URL); EPOCH_PINNED and RUNTIME_START now carry config_identity_sha256 and config_file_provenance | open |  | 2026-10-16T10:18:42.682Z |  |
| 11 | 16 | unrun-verify | src/paper/shadow_runtime.py |  | 16-57: the SHADOW_SIGNAL_LOST journal row (no signal or plan id, foreign keys left null) is written through the in-memory SHADOW stores only; PgShadowStores/PgJournalStore were not exercised (PostgreSQL off on the dev machine) | open |  | 2026-10-16T10:18:43.567Z |  |
| 12 | 16 | unrun-verify | .github/workflows/paper_freeze_check.yml | 72 | GitHub acceptance of the concurrency key 'queue: max' is not verified live (docs read 2026-10-16, no network); plan 16-59 tests only check the text; the first live run on master is the proof | open |  | 2026-10-16T14:37:27.945Z |  |

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
  },
  {
    "id": 4,
    "kind": "unrun-verify",
    "phase": "16",
    "file": "tests/test_paper_test_signal_rehearsal.py",
    "line": 584,
    "description": "16-56: the PostgreSQL test of the test-signal rehearsal on the v2 configuration skipped (no TEST_DATABASE_URL); make_sync_engine of the state port against a real database is unproven on the dev machine",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-10-16T09:39:52.126Z",
    "resolved_at": null,
    "milestone": "v0.3"
  },
  {
    "id": 5,
    "kind": "unrun-verify",
    "phase": "16",
    "file": "deploy/heartbeat.sh",
    "line": null,
    "description": "16-56 paper heartbeat: live ping delivery, the heartbeat-paper-url systemd credential and the 60 s timer are operator verification on the soak host before plan 16-43 (owner creates the second check, period 60 s, grace 120 s, and stores its URL with --target paper --set-url)",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-10-16T09:39:52.894Z",
    "resolved_at": null,
    "milestone": "v0.3"
  },
  {
    "id": 6,
    "kind": "unrun-verify",
    "phase": "16",
    "file": "src/paper/runtime.py",
    "line": null,
    "description": "16-56 silence watchdog proven only with fakes (fake SDK client, injected feed clock and sleep); a real half-open Binance connection and the 120 s bound on live time are first exercised on the soak host (plan 16-43)",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-10-16T09:39:53.728Z",
    "resolved_at": null,
    "milestone": "v0.3"
  },
  {
    "id": 7,
    "kind": "unrun-verify",
    "phase": "16",
    "file": "deploy/heartbeat.sh",
    "line": null,
    "description": "16-56: shellcheck not installed on the dev machine (12 shellcheck tests skipped in the deploy test set)",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-10-16T09:39:54.524Z",
    "resolved_at": null,
    "milestone": "v0.3"
  },
  {
    "id": 8,
    "kind": "unrun-verify",
    "phase": "16",
    "file": "tests/test_paper_replay_inputs.py",
    "line": 1185,
    "description": "16-57: PostgreSQL round trip of the replay-inputs and history records skipped (no TEST_DATABASE_URL); the extra PAPER_HISTORY_BARS records of B1-CR-02 (one flush before each heartbeat and gap) are proven in memory only",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-10-16T10:18:40.859Z",
    "resolved_at": null,
    "milestone": "v0.3"
  },
  {
    "id": 9,
    "kind": "unrun-verify",
    "phase": "16",
    "file": "tests/test_paper_runtime_restart_pg.py",
    "line": null,
    "description": "16-57: the three PostgreSQL restart tests skipped (no TEST_DATABASE_URL); the shared gap ledger, the post-start seam backfill and the configuration identity in EPOCH_PINNED/RUNTIME_START are proven on the in-memory port only",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-10-16T10:18:41.746Z",
    "resolved_at": null,
    "milestone": "v0.3"
  },
  {
    "id": 10,
    "kind": "unrun-verify",
    "phase": "16",
    "file": "tests/test_soak_evidence_export.py",
    "line": 818,
    "description": "16-57: the PostgreSQL test of the soak evidence export skipped (no TEST_DATABASE_URL); EPOCH_PINNED and RUNTIME_START now carry config_identity_sha256 and config_file_provenance",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-10-16T10:18:42.682Z",
    "resolved_at": null,
    "milestone": "v0.3"
  },
  {
    "id": 11,
    "kind": "unrun-verify",
    "phase": "16",
    "file": "src/paper/shadow_runtime.py",
    "line": null,
    "description": "16-57: the SHADOW_SIGNAL_LOST journal row (no signal or plan id, foreign keys left null) is written through the in-memory SHADOW stores only; PgShadowStores/PgJournalStore were not exercised (PostgreSQL off on the dev machine)",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-10-16T10:18:43.567Z",
    "resolved_at": null,
    "milestone": "v0.3"
  },
  {
    "id": 12,
    "kind": "unrun-verify",
    "phase": "16",
    "file": ".github/workflows/paper_freeze_check.yml",
    "line": 72,
    "description": "GitHub acceptance of the concurrency key 'queue: max' is not verified live (docs read 2026-10-16, no network); plan 16-59 tests only check the text; the first live run on master is the proof",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-10-16T14:37:27.945Z",
    "resolved_at": null,
    "milestone": "v0.3"
  }
]
````
