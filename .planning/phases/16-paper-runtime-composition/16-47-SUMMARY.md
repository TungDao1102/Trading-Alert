---
phase: 16-paper-runtime-composition
plan: 47
subsystem: soak evidence export / hourly freeze workflow (O-01 option a, Q-F commit-pinned-state, Q-Q cron 34)
tags: [evidence, publish, rclone, workflow, cron, pinned-epoch, runbook, paper-01]

requires:
  - phase: 16-paper-runtime-composition
    provides: "plan 16-30 (exporter, the O-01, Q-F and Q-Q user decision records); plan 16-33 (soak project operations, RUNBOOK 20.1 to 20.6); plan 16-09 (allowlist-driven workflow and its text tests); plan 16-15 (expected_slots)"
provides:
  - "scripts/export_soak_evidence.py --publish <remote:bucket/prefix> and the publish subcommand: files first, manifest last, read-back verification against the manifest, exit 4 on failure"
  - ".github/workflows/paper_freeze_check.yml: step 'Use the committed pinned epoch' (Q-F), cron 34 * * * * (Q-Q)"
  - "tests/test_paper_freeze_workflow_pin_source.py (new): Q-F text and behaviour, recorded cron, record compatibility"
  - "RUNBOOK 20.7 Exporting trial evidence"
affects: [16-43 (checks origin/master carries this workflow before the pin), 16-48, 16-49 (bucket, remote and policy are the user's step)]

requirements-completed: [PAPER-01]

status: complete
actuals:
  tokens: 13840
  tasks: 2
  commits: 4
plan_head_before: 3c47acfe0f686bff934dd893d34e0d609d3750ee
plan_head_after: d9fa5c0b503e7c8da123c65c51ad9fcbff0bd343
commits: 4

tech-stack:
  added: []
  patterns:
    - "Injected Uploader protocol (listing, put, get) with an rclone CLI implementation; credentials only in the operator's rclone configuration or environment, never in argv"
    - "Workflow step bodies are extracted from the YAML text and executed under bash in a temp tree by the tests"

key-files:
  created:
    - tests/test_paper_freeze_workflow_pin_source.py
  modified:
    - scripts/export_soak_evidence.py
    - tests/test_soak_evidence_export.py
    - .github/workflows/paper_freeze_check.yml
    - tests/test_paper_freeze_allowlist_mode.py
    - docs/operations/RUNBOOK.md
    - tests/test_soak_runbook.py

key-decisions:
  - "Destination is an operator-supplied rclone remote spec at run time; the repository holds no default and invents no configuration name (see Deviation 1)"
  - "The committed pin lives at evidence/paper/pinned_epoch.json; the workflow copies it over the cached copy and removes a cached copy when no file is committed"
  - "An object already present under the epoch prefix is left alone only when its bytes are identical; a manifest present means the epoch is never published over"

duration: ~40 min
completed: 2026-10-12
---

# Phase 16 Plan 47: Evidence publish and pin source Summary

**`export_soak_evidence.py --publish` copies a bundle to the user's recorded S3 evidence prefix (files first, manifest last, `rclone rcat --immutable`) and reads every object back against the manifest sha256; the hourly workflow copies the committed `evidence/paper/pinned_epoch.json` before the check and runs on the recorded `34 * * * *`; RUNBOOK 20.7 gives the exact fetch, export, publish and evaluate commands.**

## Recorded decisions applied (read, never edited)

- O-01 `option: a` (S3 evidence prefix outside the backup crypt remote; `versioning: enabled`, `object_lock_mode: none`, `retention: none`; `reader_access: project owner only`; `through_crypt_remote: no`; `write_timing: exporter-schedule, hourly`).
- Q-F `option: commit-pinned-state`. Q-Q `option: off-hour-minute`, `cron: 34 * * * *`.

## Accomplishments

- **Task 1 (tracer).** `--publish` on the export command and `publish --bundle DIR --destination REMOTE` for an existing bundle (loaded and secret-scanned first). Objects go to `<destination>/<epoch_id>/<file>`; an epoch prefix that already holds `manifest.json` is refused; an existing object is left alone only if identical (interrupted publish), otherwise the publish stops naming the file. After the upload every object is read back and its sha256 compared with the manifest, then the manifest is compared byte for byte; any failure exits 4 naming the file and keeps the local bundle. The destination is validated before anything is exported or uploaded: no credential-looking text, no local path or drive letter, no empty prefix, not the backup remotes `BACKUPS3` / `BACKUPS3CRYPT`. Error text is scrubbed with the redaction module. No Git digest file is written (options b and e are not recorded); only one destination flag exists (`allow_abbrev=False`).
- **Task 2.** Workflow step "Use the committed pinned epoch" between the cache restore and the check: copies `evidence/paper/pinned_epoch.json` to `logs/paper/pinned_epoch.json`, or removes a cached copy when nothing is committed. No `secrets.` expression, `permissions: contents: read`, `persist-credentials: false`, SHA-pinned actions, `--from-allowlist` and run-metadata env unchanged; cache restore/save logic unchanged (tests/test_deploy_workflows.py passes). The single `- cron:` entry is `"34 * * * *"`, asserted equal to the Q-Q record; `EXPECTED_FREEZE_CRON` is the same value; `expected_slots` returns a grid whose minute is 34; a workflow with another cron fails (negative control). RUNBOOK 20.7 states the recorded reader, that the evidence is outside the backup crypt remote (not ciphertext, no passphrase), the hourly write timing and its loss window, the cron and that its minute is a mitigation of unproven effect (G15, REV-18) with a missing tick still an EVIDENCE_GAP, and the L-01 rule that the Actions cache is never a source of truth. The flags of the RUNBOOK export and publish commands are parsed by the exporter's own argparse parsers in a test.
- **Record compatibility (Test 4).** Real pair (O-01 a with `through_crypt_remote: no`, Q-F commit-pinned-state) passes; a seeded incompatible pair (`read-from-durable-store` with `through_crypt_remote: yes`) fails the same check.

## Task Commits

| Task | Commit | What |
| --- | --- | --- |
| 1 RED | dc4ddcb | test(16-47): RED tracer for publishing a bundle to the O-01 destination |
| 1 GREEN | fa1b507 | feat(16-47): publish a bundle to the recorded O-01 evidence remote and verify it |
| 2 RED | 83630d3 | test(16-47): RED for the Q-F pin source, the Q-Q cron line and RUNBOOK 20.7 |
| 2 GREEN | d9fa5c0 | feat(16-47): committed pin source (Q-F), recorded cron 34 * * * * (Q-Q) and RUNBOOK 20.7 |

## Verification

- `tests/test_soak_evidence_export.py` (plan command): pass; the PostgreSQL case also ran against the local test database and passed.
- `tests/test_paper_freeze_workflow_pin_source.py tests/test_paper_freeze_allowlist_mode.py tests/test_deploy_workflows.py tests/test_soak_runbook.py`: pass (the bash-run step tests were executed, not skipped).
- Also run because they read the RUNBOOK or the workflow: `tests/test_deploy_docs.py tests/test_deploy_guide_vi.py tests/test_paper_exit_evaluator.py tests/test_paper_runtime_config_file.py`: pass.
- `ruff check`, `ruff format --check` (whole repository) and `mypy src`: pass. The whole test suite was not run (memory instruction).

## Deviations from Plan

**1. [Plan stop rule applied differently] `through_crypt_remote: no` for an S3 option**
- **Found during:** start. The plan says to stop and report when O-01 records `through_crypt_remote: no` for an S3 option, "because a remote outside the crypt layer needs configuration names and an access policy the user has not decided". The record does say `no`, and also says the evidence prefix "uses its own credential and remote".
- **Decision:** the orchestrator's instruction named these records as the user's decisions and told me to proceed; the access policy (project owner only) is recorded, and the missing piece, configuration names, can be avoided without inventing any. I implemented the destination as an operator-supplied rclone remote spec (`--publish <remote:bucket/prefix>`), whose credential lives in the operator's rclone configuration or environment; the repository adds no default and no new name, and Task 1's wording "credentials come from the existing BACKUP_ names" is not followed because the record says the evidence uses its own credential and remote. The destination validator refuses the backup remotes and any credential in argv.
- **Review needed:** if the user wants fixed configuration names for the evidence remote (for example environment names the host timer sets), that is a small follow-up in `RcloneUploader`; none was invented here.

**2. [Rule 3 - Blocking] The RUNBOOK names no committed-pin path before this plan**
- The plan says "the checkout path the RUNBOOK names"; none existed. I chose `evidence/paper/pinned_epoch.json` (same `evidence/paper/` root as the plan's option b/e digest path) and made workflow, test constant `COMMITTED_PIN_PATH` and RUNBOOK 20.7 agree (a test checks the RUNBOOK names it). The user commits the pinned file there after each pin (plan 16-43 step 5).

**3. [Rule 2 - Missing critical] Cached pin removed when no pin is committed**
- Under commit-pinned-state the cache must not silently supply the pin (L-01, P18), so the step removes `logs/paper/pinned_epoch.json` when `evidence/paper/pinned_epoch.json` is absent. An empty allowlist still gives SKIPPED (no pin read); a non-empty one then fails loudly with the CLI's exit 2.

**4. Stale comment in an existing test file**
- The plan allows only the `EXPECTED_FREEZE_CRON` value to change in `tests/test_paper_freeze_allowlist_mode.py`; the comment above it said "Today it is the line on master (minute 0)" and would have become false, so that comment was updated in the same hunk. No test logic was changed.

**5. The run-list command adds flags the plan did not list**
- `gh api repos/<owner>/<repo>/actions/workflows/paper_freeze_check.yml/runs --paginate --method GET -F per_page=100 --jq '.workflow_runs[]' | jq -s '.' > <github-runs-file>` so that the output is one JSON array (`--paginate` alone concatenates page objects, which `parse_github_runs` does not read). Not run (no network); the first real run is the operator's check of the shape, as RUNBOOK 20.7 says.

**Total deviations:** 5 (1 judgement on a plan stop rule, 4 small). No architectural change.

## Authentication Gates

None. No credential was read, written or printed; the S3 publish and the GitHub run-list download were built and tested only against fakes.

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model (T-16-105 mitigated by manifest-last, read-back verification and immutable uploads; T-16-106 by no secret in the workflow and a destination validator that refuses credentials in argv).

## NOT RUN / still the user's step

- Publishing to a real bucket, `rclone` itself (the CLI argv is tested through a fake runner), and the bucket policy, versioning setting and remote configuration (plan 16-49).
- `gh api` / `gh run download` / `jq` against the real repository.
- The workflow on GitHub: nothing was pushed and `master` was not touched. The workflow edit is on this branch only; a scheduled workflow takes effect only on `master` (G15), so setting it live there is the user's step, and plan 16-43 checks it before the pin.
- `tests/test_paper_shadow_isolation.py` was not touched (plan 16-38 owns it). STATE.md and ROADMAP.md were not edited.

## Self-Check: PASSED

- Files exist: `tests/test_paper_freeze_workflow_pin_source.py`, `scripts/export_soak_evidence.py`, `.github/workflows/paper_freeze_check.yml`, RUNBOOK section 20.7.
- Commits exist: dc4ddcb, fa1b507, 83630d3, d9fa5c0.
