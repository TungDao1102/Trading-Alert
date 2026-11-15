---
phase: quick-261114-ufz
plan: 01
subsystem: operations-docs, evidence-exporter
tags: [runbook, partial-restore, task-stalled, rclone-child-env, d110, d111]
requires: [quick-261114-kxu, quick-261114-mp1]
provides:
  - "RUNBOOK 21.6 (partial restore after a restart, D110) and 22.8 (TASK_STALLED and the protection stall bound, D111), pointers in 21.1a and 22.2, two open items in 22.7"
  - "scripts/export_soak_evidence.py: the rclone child gets child_env(prefixes=(RCLONE_,), extra=env), a whitelisted environment"
affects: [docs/operations/RUNBOOK.md, docs/DOC_STATUS.md, AGENTS.md, scripts/export_soak_evidence.py, tests/test_soak_evidence_export.py]
key-files:
  modified:
    - docs/operations/RUNBOOK.md
    - docs/DOC_STATUS.md
    - AGENTS.md
    - scripts/export_soak_evidence.py
    - tests/test_soak_evidence_export.py
decisions: []
metrics:
  duration: "not timed at start"
  completed: 2026-11-14
status: complete
commits: 2
plan_head_before: 212161cf221548f2b4e183cd9aae3d77abab0bb4
plan_head_after: 335d048d1005d7f74ba21c44bb3f0e0cd5fd62c1
actuals:
  tokens: 4526     # chars/4 over the +/- lines of git diff 212161cf..HEAD (18104 chars)
  tasks: 3
  commits: 2       # MEASURED: git rev-list --count 212161cf..HEAD
---

# Phase quick-261114-ufz Plan 01: RUNBOOK for the partial restore and TASK_STALLED, whitelisted rclone child env

Two owner-approved follow-ups of quick tasks 261114-kxu and 261114-mp1: the operator documentation of D110 (partial restore and its one cancel) and D111 (TASK_STALLED and the NOT_CONFIGURED stall key), and the whitelist of the rclone child environment of the evidence exporter. No decision row, parameter or src file changed.

## Commits

| Task | Commit | Message |
| ---- | ------ | ------- |
| 1 | f1596f71 | docs(quick-261114-ufz): RUNBOOK for the partial restore after a restart and TASK_STALLED |
| 2 | 335d048d | fix(quick-261114-ufz): whitelist the environment of the evidence exporter's rclone child |
| 3 | none (final gates and this SUMMARY) | |

Both carry the trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Nothing was pushed or merged. Branch `develop`, sequential execution on the main working tree.

## Task 1: RUNBOOK 21.6 and 22.8

**What changed.**
- `### 21.6 Partial restore after a restart (D110)`, inserted before `## 22.`: what the restore does (per-row isolation, the fault classes, the log line with ids and class only, `COORDINATOR_RESTORED` fails with `RESTORE_INCONSISTENT`; a store fault restores nothing, `DB_FAILURE`, no cancel), what the process does next (RECOVERY degrades, admitted in SAFE_MODE, stream/reconcile/bot/scheduler start, HEALTH and ENABLE skipped, `--hold-on-refusal` does not apply, restore counts as complete so reconcile ticks run), the one cancel per distinct plan hash through `expire_pending_entry` with trigger `protection_handoff_failed` and its `ENTRY_EXPIRY` row, the adapter's existing bounded STATUS_UNKNOWN retry stated plainly (`_cancel_retrying`, 3 attempts, an absent order is success), the rebuilt-hash guard, the five-row alert table, what stays the operator's and five numbered operator steps, and the closing sentence on a literal single wire request.
- `### 22.8 TASK_STALLED and the protection stall bound (D111)`, appended at the end: meaning (watchdog beside each protection run, `LIVE_TASK_EVENT` row, HIGH alert `TASK_STALLED`, reason `STALL_BOUND_EXCEEDED`, also when the journal write fails), observe only, the key `scheduler.protection_stall_after_ms` (NOT_CONFIGURED value and provenance, alert-only, never refuses the start, off until the owner sets it with a DECISIONS row and provenance DECISION, provenance rule, stay below `protection.max_unprotected_ms`, image rebuild), how to react (and the `alerts.dedupe_window_ms` suppression), and the measurement procedure with the two read-only SQL queries copied verbatim from the mp1 SUMMARY and five owner-run Demo steps.
- Pointers: one sentence at the end of the 21.1a paragraph and of the 22.2 paragraph; two bullets after R-26 in 22.7.
- `docs/DOC_STATUS.md`: one change-log line dated 2026-11-14 naming quick task 261114-ufz (including the AGENTS.md clause).
- `AGENTS.md`: the line `the alert-only NOT_CONFIGURED key scheduler.protection_stall_after_ms (D111, RUNBOOK 22.8);` under "Still open (owner)".

**AGENTS.md line: KEPT.** `tests/test_agents_md.py` passed (3 dots, no failure) and `uv run python scripts/verify_decision_alignment.py all` printed ALL_PASS after the edit, so nothing was reverted.

**Citations re-checked against the code before writing** (line numbers drifted by a few lines from the plan in some files, the statements held): `src/live/scheduled_cancel.py` (`cancel_unrestored_entries` one result per distinct plan hash, rebuilt-hash guard, `ValueError` -> REFUSED, other `Exception` -> FAILED, `STILL_OPEN`/`UNKNOWN` -> UNVERIFIED, one `snapshot_positions`, the live-5 check, non-zero or non-Decimal amount); `src/live/startup.py` (`_ROW_FAULTS`, `RestoreSourceMissing`, log line fields, `PartialRestore` with flagged entries, port call wrapped so nothing stops the start, `HOLD_STEPS`, degrade branch, `_enable` skip); `src/reconcile/startup.py` (`PartialRestore` -> `RESTORE_INCONSISTENT`, other exception -> `DB_FAILURE`); `src/execution/manager.py` (`expire_pending_entry`, `ENTRY_EXPIRY`); `src/adapters/binance_usdm.py` (`_cancel_retrying`, `_RECONCILER_CANCEL_MAX_ATTEMPTS` = 3); `src/ops/alerts.py` (severities CRITICAL, HIGH, HIGH); `src/live/scheduler.py` (watchdog, observe only, log line, stall event); `src/live/wiring.py` (`_record_task` journal then alert in `finally`, bound only on the protection spec); `src/live/wiring_parts.py` (`task_event_journal` fields, `alert_task_stall`); `src/execution/execution_limits.py` (alert-only set, provenance rule, PLACEHOLDER refusal); `config/execution/execution-limits-v1.toml` (NOT_CONFIGURED value and provenance); `src/live/config.py` (`default_limits_path`, no flag); `src/ops/alert_wording.py` (operator line). The kxu and mp1 SUMMARY lines and D110/D111 items match the text.

**Left out (could not be backed, plan said write nothing else):** no statement on which reconcile divergence kind an unrestored position produces (kxu report b says it depends on the compare inputs and was not run end to end).

**Headings.** No existing heading was renumbered or renamed; the only new headings are `### 21.6` and `### 22.8`. `git diff` shows 2 changed existing RUNBOOK lines (the two pointer lines, each with one appended sentence).

**CRLF counts (CRLF = LF, before -> after):** RUNBOOK 1162 -> 1238 (+76 lines added), AGENTS.md 218 -> 219, DOC_STATUS.md 93 -> 94.

**Verify.** `tests/test_soak_runbook.py tests/test_deploy_docs.py tests/test_decision_alignment_ops_risk.py tests/test_decision_alignment_bookkeeping.py tests/test_agents_md.py tests/test_phase24_gate.py tests/test_soak_compose.py tests/test_deploy_guide_vi.py`, `-m "not docker" -n 4`: 363 passed. Decision alignment ALL_PASS. Greps: `^### 21.6 Partial restore after a restart` 1, `^### 22.8 TASK_STALLED` 1, each of the five reason codes 1, `scheduler.protection_stall_after_ms` 2, `_cancel_retrying` 1, `section 21.6` 3, `261114-ufz` in DOC_STATUS 1.

## Task 2: whitelisted environment of the rclone child

**What changed.** `scripts/export_soak_evidence.py`: `from src.ops.backup import child_env  # noqa: E402`; `_run_rclone` passes `env=child_env(prefixes=("RCLONE_",), extra=env)` (was the whole parent environment spread under `env`); docstring updated; the two local variables named `child_env` in `RcloneUploader.__init__` and `RcloneWitnessReader.__init__` renamed `remote_env`; the module docstring sentence about `RCLONE_CONFIG_EVIDENCES3_*` now says the child gets a whitelisted environment. Signature `(argv, stdin, env)` and every error message unchanged. `tests/test_soak_evidence_export.py`: `import subprocess` and `test_the_rclone_child_gets_a_whitelisted_environment_never_the_whole_parent`.

**RED (source at HEAD, test added first):**
```
tests\test_soak_evidence_export.py:1890: AssertionError
E           AssertionError: BINANCE_DEMO_API_SECRET of the parent reached the rclone child
1 failed, 67 deselected
```
**GREEN.** The new test passes. `tests/test_soak_evidence_export.py tests/test_evidence_remote.py tests/test_soak_runbook.py`, `-m "not docker" -n 4`: 170 passed, 0 skipped. `TEST_DATABASE_URL` is set in this process environment, so the pg-fixture tests inside `tests/test_soak_evidence_export.py` ran (no skip reported with `-rs`). Greps: non-comment `**os.environ` 1 -> 0; `child_env(prefixes=("RCLONE_",), extra=env)` 0 -> 1; `from src.ops.backup import child_env` 0 -> 1; `remote_env` 4.

**What the child needs (determined from code).** The only child process the exporter starts is rclone (`subprocess.run` in `_run_rclone`; no other subprocess, Popen or os.system use in that script, in `scripts/evaluate_trial_soak.py` or in `src/ops/evidence_remote.py`; the script never calls `gh`, so no GitHub token is needed). rclone gets its remote only from the `RCLONE_CONFIG_EVIDENCES3_*` mapping (`src/ops/evidence_remote.py`), optional `RCLONE_*` tuning, and OS basics (PATH, SYSTEMROOT/WINDIR, HOME/USERPROFILE/APPDATA, TEMP/TMP/TMPDIR, proxy and SSL_CERT_* names), all in `_CHILD_ENV_NAMES` of `src/ops/backup.py`. It reads no PostgreSQL name and no DATABASE_URL. The call has the same shape as `make_rclone_runner` (`src/ops/backup_remote.py`).

**CRLF counts (CRLF = LF):** `scripts/export_soak_evidence.py` 1265 -> 1271, `tests/test_soak_evidence_export.py` 1912 -> 1984.

## Final gates (Task 3)

Run once after both commits: `uv run ruff check`: All checks passed. `uv run ruff format --check`: 1029 files already formatted. `uv run mypy src`: Success, no issues in 291 source files. `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS. Union of the two verify sets, `-m "not docker" -n 4`: **464 passed**, 0 skipped reported.

Not run: the full suite (orchestrator), docker-marked tests, `pytest -m demo`, `--execute` scripts, any `*_pg.py` file. `tests/test_phase20_gate.py` was neither run nor edited: its invariant 6 fails before and after for the pre-existing reason recorded in the mp1 SUMMARY (Residuals).

## Deviations from Plan

None - plan executed exactly as written. (Tool outputs stayed ASCII-only; the DOC_STATUS line uses the same em dash as its neighbours.)

## Known Stubs

None.

## Threat Flags

None. T-ufz-01 is mitigated by the whitelist and its test (BINANCE_*, TELEGRAM_*, DATABASE_URL, PG*, EVIDENCE_S3_*, BACKUP_*, GITHUB_*, AWS_* never reach the child; no value is logged or printed). T-ufz-04: the two SQL blocks in 22.8 are SQL only.

## Residuals (for the owner)

- A real Binance cancel answer and the real position read for an unrestorable plan after a restart remain owner-run Demo checks (stated in RUNBOOK 21.6).
- A literal single wire request for the restart cancel needs an adapter change and its own decision (stated in RUNBOOK 21.6 and 22.7).
- The value of `scheduler.protection_stall_after_ms` is still the owner's (RUNBOOK 22.8, 22.7).

## Self-Check: PASSED

- Commits f1596f71 and 335d048d are ancestors of HEAD; `git rev-list --count 212161cf..HEAD` = 2; both commit messages carry the Sonnet 5.5 trailer.
- Created file exists: this SUMMARY. All five edited files have CRLF count equal to LF count.
- `git status` shows nothing staged; `.planning/STATE.md`, `.planning/config.json`, `.planning/REQUIREMENTS.md` and `.planning/state.json` remain unstaged owner modifications; untracked files were not touched.
