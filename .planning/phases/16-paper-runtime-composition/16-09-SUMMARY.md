---
phase: 16-paper-runtime-composition
plan: 09
subsystem: paper-freeze / ci-workflow / glossary
tags: [freeze-check, paper-start-allowlist, run-metadata, github-actions, glossary, evidence-gap]

requires:
  - phase: 16-paper-runtime-composition
    provides: "16-02: PaperAllowlistEntry validation and call-time registry root (resolve_registry_root)"
provides:
  - "python -m src.paper.freeze --check --from-allowlist: SKIPPED line and exit 0 on an empty allowlist; exact-hash check of the single listed entry otherwise"
  - "FreezeSkippedEntry line shape (outcome SKIPPED, reason, optional run_metadata) and optional run_metadata on DiffLogEntry"
  - "allowlist_entries() and find_allowlist_entry() accessors in src/paper/freeze.py (the only way other code reads the allowlist)"
  - "read_run_metadata(): run_id, run_attempt, event_name, schedule, commit from five named environment variables"
  - "Hourly workflow with no hard-coded set, PAPER_EVENT_SCHEDULE stamped, header stating registry immutability only"
  - "docs/GLOSSARY.md section 13: the Phase 16 vocabulary with decision citations"
affects: [16-15 reconciler, 16-22 runtime composition, 16-30 cron checkpoint Q-Q, 16-43 master precondition, 16-47 cron constant]

actuals:
  tokens: 11600
  tasks: 3
  commits: 5
plan_head_before: f6fb5b18aae8a0ea35b2ccf3ed56306d907371d1
plan_head_after: e1dc8e3f17b5f4878308f9a321e592dee16cec52
commits: 5

tech-stack:
  added: []
  patterns:
    - "Allowlist read only through accessor functions inside freeze.py; the AST guard keeps the tuple name out of every other module"
    - "Run metadata copied from a closed set of five environment variables, rendered only when present so older lines stay byte-identical"
    - "Workflow text checked by a line-anchored cron parser asserted against one constant, with a negative control"

key-files:
  created:
    - tests/test_paper_freeze_allowlist_mode.py
  modified:
    - src/paper/freeze.py
    - .github/workflows/paper_freeze_check.yml
    - docs/GLOSSARY.md

key-decisions:
  - "A single allowlist entry is checked through the unchanged run_check_cli plus one new rule: the pinned state's hash must equal the entry's hash, else exit 1 and no line"
  - "Ambiguity fails closed: two entries make the CLI exit 1 (ambiguous allowlist) with no line, and find_allowlist_entry raises ValueError when two entries list the same ids"
  - "run_metadata keeps only keys that are present in the environment; an empty github.event.schedule on workflow_dispatch is written as an empty string, not omitted"
  - "SKIPPED is a distinct line class (FreezeSkippedEntry); DiffLogEntry still accepts only clean and REGISTRY_DIFF"
  - "The glossary entry for the freeze SKIPPED line is headed 'SKIPPED (freeze-check line)' because section 10 already defines the ApprovalResult value SKIPPED"

requirements-completed: [PAPER-01]

coverage:
  - id: D1
    description: "With an empty PAPER_START_ALLOWLIST the freeze CLI appends exactly one SKIPPED line (reason 'allowlist empty') and exits 0; it writes no clean line, pins nothing and names no set; explicit ids are forbidden with --from-allowlist and still required without it"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_freeze_allowlist_mode.py#test_empty_allowlist_appends_one_skipped_line_and_exits_zero"
        status: pass
      - kind: unit
        ref: "tests/test_paper_freeze_allowlist_mode.py#test_from_allowlist_forbids_explicit_ids"
        status: pass
      - kind: unit
        ref: "tests/test_paper_freeze_allowlist_mode.py#test_without_from_allowlist_both_ids_are_still_required"
        status: pass
    human_judgment: false
  - id: D2
    description: "With one allowlist entry the CLI checks exactly that strategy_id, parameter_set_id and approved hash with exit codes 0, 1, 2, 3; two entries exit 1"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_freeze_allowlist_mode.py#test_one_entry_clean_tick_exits_zero_and_checks_exactly_that_set"
        status: pass
      - kind: unit
        ref: "tests/test_paper_freeze_allowlist_mode.py#test_one_entry_registry_change_is_a_rollover_exit_three"
        status: pass
      - kind: unit
        ref: "tests/test_paper_freeze_allowlist_mode.py#test_pinned_hash_must_equal_the_entry_hash"
        status: pass
      - kind: unit
        ref: "tests/test_paper_freeze_allowlist_mode.py#test_two_entries_are_ambiguous_exit_one_and_nothing_is_guessed"
        status: pass
    human_judgment: false
  - id: D3
    description: "Every line can carry run_metadata from the five named variables; lines without the variables are byte-identical to the pre-plan shape"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_freeze_allowlist_mode.py#test_clean_and_rollover_lines_carry_run_metadata_when_the_variables_are_set"
        status: pass
      - kind: unit
        ref: "tests/test_paper_freeze_allowlist_mode.py#test_lines_without_run_metadata_are_byte_identical_to_the_pinned_shape"
        status: pass
      - kind: unit
        ref: "tests/test_paper_freeze_allowlist_mode.py#test_run_metadata_reads_only_the_five_named_variables"
        status: pass
    human_judgment: false
  - id: D4
    description: "The hourly workflow has no hard-coded id, passes github.event.schedule, keeps least privilege and SHA pins, and has exactly one cron line equal to EXPECTED_FREEZE_CRON (hourly form); the checker fails on a changed, doubled or missing cron"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_freeze_allowlist_mode.py#test_workflow_has_exactly_the_expected_cron_line"
        status: pass
      - kind: unit
        ref: "tests/test_paper_freeze_allowlist_mode.py#test_cron_check_fails_on_a_changed_a_second_or_a_missing_cron"
        status: pass
      - kind: unit
        ref: "tests/test_paper_freeze_allowlist_mode.py#test_workflow_reads_the_allowlist_and_hard_codes_no_set"
        status: pass
      - kind: unit
        ref: "tests/test_deploy_workflows.py (unedited, pin and runner checks)"
        status: pass
    human_judgment: false
  - id: D5
    description: "docs/GLOSSARY.md defines CONTEXT_BAR (confirmed in src/paper/loop.py), DUPLICATE_BAR, SHADOW, SKIPPED, EVIDENCE_GAP, PLANNED_RESTART, HEALTHY, DEGRADED, the three source tags and test_only, each with its decision citation"
    requirement: PAPER-01
    verification:
      - kind: other
        ref: "python -c membership check of the twelve terms in docs/GLOSSARY.md (exit 0, empty list)"
        status: pass
      - kind: unit
        ref: "tests/test_decision_alignment_authority.py, tests/test_decision_alignment_bookkeeping.py, scripts/verify_decision_alignment.py all (ALL_PASS)"
        status: pass
    human_judgment: true
    rationale: "Whether each definition says what the user means (health thresholds, the REST_BACKFILL rule) is the user's; the text deliberately points to the O-07 table and the Q-D record instead of stating a rule"

duration: 10min
completed: 2026-10-09
status: complete
---

# Phase 16 Plan 09: Freeze check reads the allowlist (G2-009) Summary

**`python -m src.paper.freeze --check --from-allowlist` now writes one SKIPPED line and exits 0 while the allowlist is empty, checks exactly the single approved set otherwise, stamps lines with the Actions run identity, and the workflow carries no hard-coded set; the Phase 16 vocabulary is in the GLOSSARY.**

## Performance

- **Duration:** about 10 min (2026-10-09T05:08:54Z to about 05:19Z)
- **Tasks:** 3 (Task 1 tracer and Task 2 TDD, Task 3 docs)
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments

- Tracer (D-21, L-01): `--from-allowlist` is a new CLI mode. With `PAPER_START_ALLOWLIST == ()` it appends one `FreezeSkippedEntry` line (`outcome` "SKIPPED", `reason` "allowlist empty"), writes no clean line, creates no pinned state and exits 0. `--strategy-id` and `--parameter-set-id` are forbidden with the flag (argparse exit 2) and still required without it, so no fallback set can be named. `DiffLogEntry` keeps its two outcomes.
- Non-empty path: one entry is checked through `run_check_cli` with the exit codes 0 (clean), 3 (rollover), 2 (missing pinned state) and 1 (id mismatch), plus a new rule: the pinned hash must equal the entry's approved hash or the result is 1 with no line. Two entries exit 1 with "ambiguous allowlist".
- Accessors `allowlist_entries()` and `find_allowlist_entry()` live in `src/paper/freeze.py`; the runtime (plan 16-22) must use them. The AST guard of `tests/test_paper_start_gate.py` still passes: the allowlist name appears only in `src/paper/freeze.py`, and neither the tuple name nor `PaperAllowlistEntry` was added to `__all__`.
- Tick identification (REV-02, T-16-21): `read_run_metadata()` reads only `GITHUB_RUN_ID`, `GITHUB_RUN_ATTEMPT`, `GITHUB_EVENT_NAME`, `GITHUB_SHA` and `PAPER_EVENT_SCHEDULE` and writes them as `run_id`, `run_attempt`, `event_name`, `commit`, `schedule` under `run_metadata` on SKIPPED, clean and REGISTRY_DIFF lines, in both CLI modes. With none of the variables set the key is absent and the line is byte-identical to before (pinned by a literal-string test).
- Workflow: the two id flags are gone, `--from-allowlist` is used, `PAPER_EVENT_SCHEDULE: ${{ github.event.schedule }}` is added to the step env, and the header states that the check proves registry immutability only, never that the host ran, and that the Actions cache is operational state, not evidence. Cron, permissions, `persist-credentials: false`, SHA-pinned actions, cache restore/save, artifact upload and the alert steps are unchanged.
- Cron asserted, not assumed: the workflow has exactly one `- cron:` list item and it equals `EXPECTED_FREEZE_CRON` (`0 * * * *`, the line already on master), defined once at the top of the new test file; the expected value must be of the hourly form `M * * * *`; a negative control shows the checker fails on a changed, a doubled and a missing (commented-out) cron. `git diff f6fb5b1 -- .github/workflows/paper_freeze_check.yml` contains no `cron:` line.
- GLOSSARY section 13 defines CONTEXT_BAR, DUPLICATE_BAR, SHADOW, SKIPPED (freeze-check line), EVIDENCE_GAP, PLANNED_RESTART, HEALTHY, DEGRADED, LIVE_WS, REST_WARMUP, REST_BACKFILL and test_only with D040, D061, D063 and D065 citations. CONTEXT_BAR and DUPLICATE_BAR were confirmed by reading `run_paper_tick` in `src/paper/loop.py` (4h event gives `CONTEXT_BAR`, repeated open time gives `DUPLICATE_BAR`, both with stage `feed_gate`).

## RED Evidence

- **Task 1** (`45e7d9d`, tests only) against the unchanged CLI: the six tests that need the new mode or classes failed (`SystemExit: 2` from the required id flags, missing `FreezeSkippedEntry`); the "forbids explicit ids" cases passed vacuously because argparse already rejected the unknown flag, and the "ids still required" cases characterise existing behaviour.
- **Task 2** (`e49e0b8`, tests only) against the fail-closed stub of Task 1 (non-empty allowlist returned 1): nine tests failed (clean, rollover, missing-state, run_metadata, byte-identical keyword, three workflow tests). `test_pinned_hash_must_equal_the_entry_hash`, `test_one_entry_with_other_ids_than_the_pinned_state_exits_one`, `test_two_entries_are_ambiguous_exit_one_and_nothing_is_guessed` and the cron tests passed before GREEN because the stub already returned 1 or the cron line was already on master; their meaning was exercised by the GREEN code path.

## Task Commits

1. **Task 1 (tracer): empty allowlist gives one SKIPPED line** - `45e7d9d` (test, RED), `027563d` (feat, GREEN)
2. **Task 2: non-empty path, run metadata, workflow** - `e49e0b8` (test, RED), `09ba112` (feat, GREEN)
3. **Task 3: GLOSSARY vocabulary** - `e1dc8e3` (docs)

**Plan metadata:** committed separately (docs: complete plan).

## Verification

- `.venv/Scripts/python -m pytest tests/test_paper_freeze_allowlist_mode.py tests/test_paper_freeze.py tests/test_paper_start_gate.py tests/test_deploy_workflows.py tests/test_paper_allowlist_entry.py -q -p no:cacheprovider`: all pass (29 tests in the new file). Also green: `test_kill_gate_docs`, `test_research_runner`, `test_domain_enums`, `test_geometry_audit_doc`, `test_decision_alignment_authority`, `test_decision_alignment_bookkeeping`, `scripts/verify_decision_alignment.py all` (ALL_PASS).
- `uv run ruff check`, `uv run ruff format --check` (451 files) and `uv run mypy src` (157 files) are clean.
- The GLOSSARY membership one-liner prints `[]` and exits 0.
- Existing pinned outputs: `tests/test_paper_freeze.py` is unedited and passes.
- No network, no package install; `uv.lock` unchanged.

## Decisions Made

- Hash-mismatch and ambiguity write no diff-log line and exit 1, matching today's id-mismatch behaviour; the workflow turns red on any exit other than 0 or 3.
- `find_allowlist_entry` raises `ValueError("ambiguous allowlist ...")` when two entries list the same ids rather than returning the first (fail closed; the plan's signature returns `PaperAllowlistEntry | None`, and the runtime plan 16-22 should treat the error as a refusal to start).
- `run_metadata` is typed `Mapping[str, str] | None` and validated against the closed key set at construction.

## Deviations from Plan

None - plan executed exactly as written. Two small points, neither a deviation from a requirement:

- During Task 2 my first test mutation (`fee_rate_entry` renamed) tripped the registry's unknown-key check; the test now changes a value (`fee_rate_entry = 0.0002` to `0.0003`) as the existing rollover test does. Test-only fix, in the GREEN commit.
- Ruff import-order fixes in the new test file were applied before each commit.

## Issues Encountered

- Inline Python in shell heredocs lost one level of backslashes in the `_cli_main` docstring (`\\` became `\`); caught by diffing against HEAD and restored before commit. The remaining edits used the Edit tool or script files.

## Observations for later plans

- In allowlist mode, after a REGISTRY_DIFF rollover (exit 3) the CLI rewrites the pinned state to the new hash; the next tick then sees pinned hash different from the entry's approved hash and exits 1 until the allowlist is changed by the user (O-13 / plan 16-42). That is the fail-closed reading of "checks exactly the approved hash"; the reconciler (16-15) and the evaluator (D-23) should expect a red run after a rollover, not a stream of clean lines.
- The workflow change only takes effect once it is on `master` (scheduled workflows run on the default branch); that check is a precondition of plan 16-43, not of this plan. The cron minute is the user's checkpoint Q-Q (plan 16-30); plan 16-47 changes only `EXPECTED_FREEZE_CRON` in `tests/test_paper_freeze_allowlist_mode.py` and the workflow line together. A missing tick is an EVIDENCE_GAP under either answer.

## Known Stubs

None.

## Threat Flags

None. T-16-21 (manual run counted as a tick) is mitigated at the line level (event_name and schedule on every line; the reconciler of 16-15 must count only `event_name` "schedule"); T-16-22 (fallback to a legacy set) is mitigated by the forbidden id flags, the SKIPPED path and the ambiguity exit; T-16-23 is transferred to plan 16-15; T-16-SC accepted, no package installed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 16-15 can rely on `run_metadata.event_name` and `run_metadata.schedule` on every line, and on the SKIPPED class being distinct from clean.
- Plan 16-22 can read the allowlist through `allowlist_entries()` and `find_allowlist_entry()` only.
- The allowlist remains empty by the user's decision (checkpoint 15-17-01, Option B).

---
*Phase: 16-paper-runtime-composition*
*Completed: 2026-10-09*

## Self-Check: PASSED

`src/paper/freeze.py`, `tests/test_paper_freeze_allowlist_mode.py`, `.github/workflows/paper_freeze_check.yml`, `docs/GLOSSARY.md` and this SUMMARY exist; commits 45e7d9d, 027563d, e49e0b8, 09ba112, e1dc8e3 are in git log (5 commits since f6fb5b1); the plan test commands, ruff check, ruff format --check and mypy src pass.
