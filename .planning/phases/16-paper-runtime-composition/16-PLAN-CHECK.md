# Phase 16 Plan Check (re-verification after revision pass of 2026-10-09)

**Verdict: ISSUES FOUND (0 blocker, 1 warning, 5 info). No revision is required to execute; the warning is recommended.**

Plans checked: 49 (16-01..16-49), after the 25-plan revision described in 16-REVISION-NOTES.md. Static plan analysis only; no plan was edited.

## Mechanical results (scripted over all 49 plans)
- Frontmatter parses in all plans. `wave`, `depends_on` and `requirements` values are unchanged by the revision (git diff shows no change to those lines).
- depends_on: every reference exists, no cycle, wave = max(dep waves)+1 for all 49 plans.
- Same-wave `files_modified` overlap: none.
- Tasks per plan: max 4 (plans 11, 15, 17, 30). `estimate.tasks` equals the counted `<task>` elements in every plan. XML tags (task, action, verify, done, automated, fails_when, acceptance_criteria, files, objective, context) balance in every plan.
- Files per plan: only plan 05 is over 10 (11 files). Unchanged known warning.
- New data dependencies are all ancestors by `depends_on`: 43 needs 47 and 30; 47 needs 09, 15, 25; 21 needs 17; 27 needs 17 and 21; 22 needs 08; 26 needs 22, 24, 16, 08; 32 and 33 need 22; 31 needs 04 and 11; 35 needs 11; 25 needs 15, 24, 08; 49 needs 47.

## Requirement closure (D061 J)
- PAPER-01 / PAPER-02 / BKTS-03 declarations unchanged. PAPER-03 appears in no `requirements:` line (stays Pending). Plan 44 (wave 18) is still the last-wave plan declaring PAPER-01 and PAPER-02; plan 46 (wave 13) is the last declaring BKTS-03 (06, 12, 13, 18 earlier). The last-declaring-plan mechanism is intact. REV-02 and REV-18 are strengthened, not weakened (see fix 7).

## The 8 fixes: present and testable
1. **Cron minute Q-Q.** 30 T4 is a blocking-human decision with a python automated check that the `cron:` line agrees with the option; 09 T2 asserts exactly one `- cron:` entry equal to `EXPECTED_FREEZE_CRON` (hourly form, negative control); 47 T2 sets the cron to the Q-Q record, updates `EXPECTED_FREEZE_CRON` and has `tests/test_paper_freeze_allowlist_mode.py` in its files; 15 T3 makes `expected_slots` follow the minute and flags `SCHEDULE_MISMATCH`; 43 T1 asserts the origin/master cron equals the record. The assertion is consistent across 09/15/43/47. PRESENT.
2. **Unsolicited close + 23 h.** 01 T3 fakes (`simulate_unsolicited_close`, `last_rebuild`, `diagnostics`); 17 T2 transport-drop, `check_forced_disconnect` with negative control, faked-clock 82800 s test, pass-count gate 13; 21 live command passes `--disconnect-method transport-drop --force-disconnect-after-seconds 900 --sdk-reconnect-interval-seconds 3600`; 43 T3 reports observed rotation. PRESENT.
3. **Telegram failures.** 04 T2 (classification, 429 inside budget), 11 T4 (own test file `tests/test_paper_shadow_telegram_failures.py` in its files, automated + fails_when with a minimum count and a PG replay test), 31 T2 handler cannot approve, 35 T1 attribution. PRESENT.
4. **O-01 / Q-F options.** 30 T2/T3 text and extended record lines; 47 stop rules and a compatibility test; 07 T3 and 49 T3 read-back test. 30 T2 context states that no runtime-side event-time writer is implemented, so the user is told which choice stops 47. PRESENT.
5. **Measurements.** 17 T4 (gate: 17 passed), 21 passes explicit settings, 27 maps the fields into the O-07 observation column, 08/16/24/26 add `PAPER_TICK_STATS` and `FUTURE_CLOSE`, 15 T4 and 25 T2 report-only `tick_timing_summary`, 43 T3 records it. Field names are identical across 17/21/27. All are observations, none a threshold. PRESENT.
6. **SHADOW label and both time zones.** 04 T1/T2 composer `render_shadow_message` with enum-enumerating test, 11 T1/T2/T4 kinds, 31 T1 session-wide and AST check. PRESENT.
7. **Grace never CLEAN; auxiliary evidence.** 15 T4 (negative case in `fails_when`), 25 T2, 22 T3 README text, 27, 34 T3 (stops if grace >= interval), 30 T1 per-epoch bundles. PRESENT.
8. **Restart loop.** `ExitCode` table in 22 (0, 2, 3, 4, 5, 6, 7), refusal set {3,4,5,6} disjoint from 1 and 7; 22 T3 and 29 T2 use 6 for mismatches; 26 uses `FAIL_CLOSED_RUNTIME` (7) for queue overflow; 32 passes `--hold-on-refusal` with a static restart-loop guard; 33 T1 lists every enum member. No stale "exit 1" for refusals found (remaining exit-1 hits are the healthcheck in 26, the plan 05 report, and a plan 20 validator, all intended). CONSISTENT.

## Other checks
- Coverage SC1-9 and inherited items: unchanged mapping, no plan removed. SC5 and SC7 coverage gained rows.
- D040 isolation: not weakened. The revision adds no order-surface path; the new Telegram, smoke and measurement code uses the credential-free adapter and the SHADOW composer. Plan 38 tests are untouched.
- No float in decision paths: the new fields are millisecond integer observations or report-only; `test_domain_no_float` is in the verify of 15. No LLM in any decision path.
- No scope reduction: no "v1 / stub / for now" language against a locked decision in the revised plans (hits are "later" in ordinary prose and an existing placeholder-compose description).
- VALIDATION.md: all ten new rows (unsolicited disconnect, 23 h rotation, smoke measurements, tick statistics, Telegram failures, label and time zones, freeze cron, grace/auxiliary, exit-code table, no late signal) cite existing plan and task ids whose files and automated commands exist. Flags `draft` / `nyquist_compliant: false` unchanged (intentional).

## Issues

### WARNING
1. [scope_sanity] Plan 16-05 lists 11 files in `files_modified` (over the 10-file threshold). Unchanged from the prior check. Required property: each plan stays within the per-plan context budget. Example route: split the fixture-definition task into its own plan, or accept the size because the files are small and test-heavy.

### INFO
2. [nyquist / validation_map] The three earlier VALIDATION rows are NOT resolved: "REV-03 rehearsal" cites 16-36 T2 and 16-25 T2, whose `<files>` do not contain `tests/test_paper_test_signal_rehearsal.py` (owned by 39; the cited tasks test the `test_only` exclusion in `test_analytics_*` and `test_paper_exit_evaluator`); the "D-27/D-29/D-30 runner report" row cites 16-18 T3 whose files list only `src/research/run.py` and `tests/test_research_runner.py` while the row command names `test_research_report.py` and `test_modeled_costs_none_guard.py`. The tasks themselves have their own automated checks, so only the table's file column is imprecise. Example route: list the task's real test file in the row, or move the citation.
3. [task_completeness] 30 T2's automated check greps only `option:`; the new record lines `reader_access:`, `through_crypt_remote:`, `write_timing:` are enforced later by 47 (stop rule and compatibility test), not at the checkpoint. A missing line is therefore found at wave 8, not at the decision. Example route: extend the grep of 30 T2 to require the three lines.
4. [scope_sanity] Plans 11, 15, 17 and 30 are now at 4 tasks (threshold "warning" in the general rubric, accepted for this phase). Plan 17 interleaves a docs task (SOURCES) between code tasks; the pass-count gates (13, then 17) keep the order checkable.
5. [dependency_correctness] Plans 37, 46, 41, 48, 42, 43, 44 still form a serial chain across waves 12-18 gated on the user (carried over, advisory).
6. [verification_derivation] D057 and D061-D remain covered semantically without literal ids; VALIDATION flags unchanged (carried over, advisory).

## Limits
Action bodies of unrevised plans were not re-read; consistency of exit codes, cron assertion and new evidence fields was checked by targeted grep across 09/15/17/21/22/26/27/29/32/33/43/47 plus the cited tasks' verify blocks, not by line-by-line review of every action.
