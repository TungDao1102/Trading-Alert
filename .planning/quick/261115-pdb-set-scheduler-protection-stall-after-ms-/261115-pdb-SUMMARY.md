---
phase: quick-261115-pdb
plan: 01
subsystem: execution-limits / live scheduler
tags: [limits, stall-watchdog, D114, owner-answer]
requires: [D111, D112, D113]
provides: ["scheduler.protection_stall_after_ms = 60000 (DECISION) in the shipped limits file; stall watchdog and TASK_STALLED on"]
affects: [config/execution/execution-limits-v1.toml, docs/DECISIONS.md, docs/operations/RUNBOOK.md]
key-files:
  modified:
    - config/execution/execution-limits-v1.toml
    - config/execution/README.md
    - src/execution/execution_limits.py
    - tests/support/execution_limits.py
    - tests/test_execution_limits.py
    - tests/test_live_limits_relationships.py
    - tests/test_live_wiring.py
    - docs/DECISIONS.md
    - docs/DOC_STATUS.md
    - docs/GLOSSARY.md
    - docs/operations/RUNBOOK.md
    - AGENTS.md
decisions:
  - "D114: scheduler.protection_stall_after_ms = 60000 ms, provenance DECISION (owner answer 2026-11-15); an inference from 886 ms longest observed protection_step run and the bounded cancel retry plus the 1.5 s stop reread, not a measured maximum"
status: complete
commits: 2
plan_head_before: f8634c2a1f534075ddda2dd9f081ea7656616a8d
plan_head_after: 29395a2698a535c3630ce6e25707be145a18b190
actuals:
  tokens: 40000
  tasks: 3
  commits: 2
completed: 2026-11-15
---

# Phase quick-261115-pdb Plan 01: Stall bound 60000 ms (D114) Summary

The shipped limits file now sets `scheduler.protection_stall_after_ms = 60000` with provenance DECISION, so the observe-only stall watchdog of the protection task and the `TASK_STALLED` alert are on; no `src` behavior changed (docstring and comment words only), and the value lives only in the toml, the README and the docs.

## Commits

| Task | Commit | Message |
|---|---|---|
| 1 | 75104781 | feat(quick-261115-pdb): set scheduler.protection_stall_after_ms to 60000 (D114), stall watchdog on |
| 2 | 29395a26 | docs(quick-261115-pdb): D114 protection stall bound 60000 ms, RUNBOOK 22.6-22.8 and the 2026-11-15 smokes |
| 3 | none | final gates and this SUMMARY (orchestrator commits it) |

Both commits carry the trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Nothing pushed; branch `develop`.

## Test counts

Task 1 verify set (21 files, `-m "not docker" -n 4`):

| | passed | skipped | failed |
|---|---|---|---|
| Baseline at HEAD f8634c2a | 1080 | 1 | 0 |
| After (final gate run) | 1084 | 1 | 0 |

The 4 new tests: one new negative-control parametrize case (stall bound = 180000), `test_an_unset_stall_bound_is_not_a_violation_and_a_set_one_must_stay_below_the_deadline`, `test_the_shipped_stall_bound_is_d114_and_feeds_a_sixty_second_watchdog`, `test_the_shipped_stall_bound_reaches_only_the_protection_task_as_sixty_seconds`. (The renamed committed-file test replaces its predecessor, so it is not a new count.)

The one skip is pre-existing and identical before and after: `tests/test_user_data_smoke_dry_run.py:383` "symlinks are not available on this platform" (Windows).

Task 2 verify set: 526 passed. Other docs-reading test files (17 files named by grep for RUNBOOK/GLOSSARY/DOC_STATUS): 657 passed.
Live sweep `uv run pytest tests/test_live_*.py -m "not docker" -n 4`: 1232 passed, 0 skipped, 0 failed. The two `tests/test_live_*_pg.py` files ran (no skip), so `TEST_DATABASE_URL` was set in the process; its value was never read or printed.
ruff check, ruff format --check, mypy src (291 files), `verify_decision_alignment.py all` (ALL_PASS): pass.

## RED and GREEN evidence

RED (tests edited first, config untouched), 8 failed, 264 passed on the three Task 1 test files:

- `test_execution_limits.py::test_the_real_file_has_every_section_and_label_unset_except_the_decided_keys` - the file still said NOT_CONFIGURED for the stall key
- `test_the_committed_file_names_only_not_configured_except_the_owner_numbers` - numeric list lacked `protection_stall_after_ms`, quoted count 6 vs 4
- `test_the_committed_file_sets_the_equity_age_and_keeps_it_required` - `unset_alert_only_keys()` still `(STALL_KEY,)`
- `test_the_committed_file_holds_the_margin_keys_set_with_the_decision_label` - same pin
- `test_the_committed_file_sets_the_stall_key_to_the_d114_value_with_the_decision_label` - value was the NOT_CONFIGURED string
- `test_live_limits_relationships.py::test_each_relationship_fails_naming_its_keys_on_a_copy[scheduler-protection_stall_after_ms-180000-...]` - an integer with a NOT_CONFIGURED label is refused at load (the control edits only the value line)
- `test_the_shipped_stall_bound_is_d114_and_feeds_a_sixty_second_watchdog` - value not set
- `test_live_wiring.py::test_the_shipped_stall_bound_reaches_only_the_protection_task_as_sixty_seconds` - shipped bound None

GREEN: after the toml, README, comment edits: 1084 passed, 1 skipped, 0 failed.

## Pins changed (old -> new)

| File | Pin | Old | New |
|---|---|---|---|
| tests/test_execution_limits.py | numeric keys of the committed file | ends with `headroom_bps` | ends with `protection_stall_after_ms` |
| same | quoted NOT_CONFIGURED count in the shipped file | 6 | 4 |
| same | decided-keys loop | stall key must be NOT_CONFIGURED | stall key == 60000 and label DECISION (new `STALL_DECIDED_MS`) |
| same | `unset_alert_only_keys()` of the shipped file (two tests) | `(STALL_KEY,)` | `()` |
| same | committed-file stall test | `..._leaves_the_stall_key_unset_and_labelled_not_configured` | renamed `..._sets_the_stall_key_to_the_d114_value_with_the_decision_label`; also asserts timedelta 60 s, still ALERT_ONLY, require_live_ready passes, below max_unprotected_ms |
| tests/test_live_limits_relationships.py | rules | five | six (rule 6: a set stall bound is strictly below `protection.max_unprotected_ms`; unset allowed) |
| config toml | line `protection_stall_after_ms` under `[scheduler]` / `[provenance.scheduler]` | NOT_CONFIGURED / NOT_CONFIGURED | 60000 / "DECISION" |

## Pins checked and NOT changed (re-confirmed by the green run)

- `len(GUARDED_NAMES) == 68` (tests/test_no_unratified_defaults.py, tests/test_phase18_gate.py): no key added.
- Phase 19 gate invariant 4 (a set value with DECISION), Phase 20 gate invariants 3 and 6, Phase 21/22 gates (still find a NOT_CONFIGURED word: ban margin and summary window keep it): green.
- `tests/test_live_scheduler.py` stall tests and `tests/support/execution_limits.py` TEST_ONLY value `None` (grep count 1): unchanged.
- `tests/test_alerts_ops05_matrix.py:205` (TASK_STALLED row keeps the word NOT_CONFIGURED): src/ops/alerts.py untouched.
- `scheduler.duration_summary_interval_ms` and `rest_gate.ban_end_clock_margin_ms`: still NOT_CONFIGURED value and label (2 matches of the summary key).
- Conditional comments left alone: src/live/scheduler.py, src/ops/alerts.py, docs/operations/SECURITY_AND_OPERATIONS.md:86, tests/fixtures/phase23/DERIVATIONS.md:83, rows D111/D112, DOC_STATUS history lines.
- grep sweep of `protection_stall_after|STALL_KEY|unset_alert_only_keys` and `execution-limits-v1` found no test file outside the verify set.

## Line endings (CRLF / LF-only counts; each file keeps its own)

| File | Before | After |
|---|---|---|
| config/execution/execution-limits-v1.toml | 0 / 123 | 0 / 125 |
| config/execution/README.md | 157 / 0 | 157 / 0 |
| src/execution/execution_limits.py | 506 / 0 | 508 / 0 |
| tests/support/execution_limits.py | 128 / 0 | 129 / 0 |
| tests/test_execution_limits.py | 0 / 1315 | 0 / 1333 |
| tests/test_live_limits_relationships.py | 234 / 0 | 288 / 0 |
| tests/test_live_wiring.py | 718 / 0 | 737 / 0 |
| docs/DECISIONS.md | 117 / 0 | 118 / 0 |
| docs/DOC_STATUS.md | 97 / 0 | 98 / 0 |
| docs/GLOSSARY.md | 652 / 0 | 652 / 0 |
| docs/operations/RUNBOOK.md | 1267 / 0 | 1271 / 0 |
| AGENTS.md | 219 / 0 | 219 / 0 |

## Claim table (new sentences of D114 and the RUNBOOK)

| Claim | Backing |
|---|---|
| Bound 60000, provenance DECISION, owner answer 2026-11-15 | owner statement (task prompt); config toml `[scheduler]` and `[provenance.scheduler]`; tests |
| Longest `protection_step` run 886 ms, about a dozen runs, no rate limit or ban | read-only `LIVE_TASK_DURATION` journal query made on 2026-11-15 in an earlier session of this task (figure supplied by the coordinator; not from the owner, D114 item 1 says so); I did not re-run the query in this continuation |
| Cancel retry 3 attempts, 30 s ceiling | src/adapters/binance_usdm.py:160-161 (`_RECONCILER_CANCEL_MAX_ATTEMPTS` 3, `_RECONCILER_CANCEL_MAX_DELAY_SECONDS` 30), checked |
| 1.5 s stop reread (3 x 0.5 s) | D113 row text (docs/DECISIONS.md D113 item 4) |
| 180000 = `protection.max_unprotected_ms`, D089 | config toml; rule 6 test |
| Watchdog is observe only, TASK_STALLED HIGH, reason STALL_BOUND_EXCEEDED, dedupe | existing RUNBOOK 22.8 text and GLOSSARY row (D111), unchanged behavior |
| 22.6: first smoke FAILED at TP_UNAVAILABLE, times, D113 fix, second COMPLETE 21 of 21 | old 22.6 paragraph, D113 row, owner statement for the second run; cause and fix "not proven" |
| After a failed run: UNSYNCED_ALGO raises SAFE_MODE | src/reconcile/classify.py module docstring ("every kind enters SAFE_MODE ... the reason is the kind name") and compare.py UNSYNCED_ALGO emission (local algo with no matching exchange algo); step name `demo_enable` is in `_SMOKE_STEPS` (scripts/demo_rehearsal.py:2285); `GATE_STATE_EXISTS` raised in src/live/startup.py:882 when `--initialize-gate-state` meets an existing gate state; `scripts/demo_clear.py` exists. That the owner's run stopped exactly at `demo_enable` is the owner's observation (task statement), not something I verified in a journal. |

## Deviations from Plan

- None in code or scope. Both commits were separate as planned (the alignment gate did not need D114 in the Task 1 commit).
- Process note, not a deviation: the earlier executor session was interrupted by a rate limit after one edit (`STALL_DECIDED_MS` in tests/test_execution_limits.py); the work was resumed from `git status` and nothing was redone.
- AGENTS.md: the open-item line naming the stall key was replaced by one naming `scheduler.duration_summary_interval_ms` (D112, RUNBOOK 22.8). Line count unchanged (219). `tests/test_agents_md.py` and the alignment gate stayed green, so the change was KEPT and committed in Task 2.
- RUNBOOK section 22 status line was not pinned by any test or script (grepped), so it was updated to say Demo was observed by the smokes of 2026-11-06 and 2026-11-15.

## Pre-existing stale text left alone (config/execution/README.md)

Line 9 "four are filled", "Of the twenty keys", and the REQUIRED user-data bullet in the "Still NOT_CONFIGURED" list. Not touched, as planned.

## Known Stubs

None.

## Threat Flags

None. No new endpoint, auth path, file access or schema change.

## Residuals for the owner

- 60000 ms is an inference, not a measured maximum; tune after more Demo runs (RUNBOOK 22.8, new DECISIONS row).
- No run with the bound set has been observed; no stall or `TASK_STALLED` has been seen.
- The value takes effect only in a process or image that carries commit 75104781 (rebuild and re-pin, D106).
- The untracked 2026-11-15 evidence files (083259Z FAILED, 104211Z COMPLETE) stay the owner's to commit; they were not opened or staged.
- `scheduler.duration_summary_interval_ms` and `rest_gate.ban_end_clock_margin_ms` stay NOT_CONFIGURED.

## Self-Check: PASSED

- Commits 75104781 and 29395a26 are ancestors of HEAD (`git rev-list --count f8634c2a..HEAD` = 2).
- `git diff --cached --name-only` empty; `.planning/STATE.md`, `config.json`, `REQUIREMENTS.md`, `state.json` still modified and unstaged; no untracked file touched; no deletions in either commit.
- `git show --stat HEAD~1 -- src/live` empty; no `60000` in the src diff (0); `float(` count in src/live/scheduler.py and wiring.py is 0 and 0.
