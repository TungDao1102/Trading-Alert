---
phase: 16-paper-runtime-composition
plan: 25
subsystem: paper-evidence / trial exit criteria / requirement closure
tags: [exit-criteria, evidence-bundle, parity, coverage, freeze-continuity, closure-rule, proof-class, decimal, determinism]

requires:
  - phase: 16-paper-runtime-composition
    provides: "16-15 coverage_report, derive_health_intervals, freeze_evidence_report, tick_timing_summary, EvidenceGap; 16-24 PAPER_BAR_PROCESSED payload (bar, surface, source, tick_time_utc), decisions/16-DEC-Q-D.md (history-only); 16-22 load_runtime_config and HealthThresholds; 16-10 decision_surface"
provides:
  - "src/paper/evidence_bundle.py: soak-evidence-bundle/1 layout, load_evidence_bundle (sha256 verified before any parse), EvidenceBundle, DiffRecord, BundleError"
  - "src/paper/exit_criteria.py: evaluate_trial, TrialEvaluation (groups, render), CriterionResult, ProofClass, BackfillRule/read_backfill_rule, ParityReplay/parity_criterion, EvidenceItem and its four source-bound factories, closure_verdict"
  - "scripts/evaluate_trial_soak.py: CLI that evaluates a bundle and writes the printed text to --out (exit 0 pass, 1 fail, 2 unusable input)"
affects: [16-30 bundle exporter, 16-43 in-trial checks, 16-44 trial evaluation and closure verdict, 16-27 and 16-34 threshold ratification]

actuals:
  tokens: 34600
  tasks: 3
  commits: 6
plan_head_before: b03a280c46a98e52ca42c3480e1f210a41d70f28
plan_head_after: 8bb6a8d45d04f7bdd99cb127a97914ebfed43809
commits: 6

tech-stack:
  added: []
  patterns:
    - "Verify-then-parse bundle: every file is hashed against the manifest before any byte is parsed; a foreign file name in the manifest is refused (no path traversal)"
    - "Two evidence sets, two input dataclasses: _FreezeInputs and _RuntimeInputs share no field, so a freeze criterion cannot read a runtime record and the reverse (REV-02, tested by field sets and by removing one side)"
    - "A missing comparison is never a PASS: parity without a replay context is 'NOT EVALUATED' and fails"
    - "Proof class is derived from where evidence came from (manifest source, the evidence file's own proof_class field, a test file), and no factory has a proof_class parameter"

key-files:
  created:
    - src/paper/evidence_bundle.py
    - src/paper/exit_criteria.py
    - scripts/evaluate_trial_soak.py
    - tests/test_paper_exit_evaluator.py
    - tests/test_paper_closure_rule.py
  modified: []

key-decisions:
  - "The ratified values are constants labelled DECISION D061 item D, 2026-10-07 (TRIAL_CALENDAR_DAYS = 14, MIN_COVERAGE_FRACTION = Decimal('0.95'), PARITY_TOLERANCE = 0); a witness test reads docs/DECISIONS.md and fails if the D061 row drops '14 calendar days', '95 percent' or 'parity tolerance zero'"
  - "The trial window criterion requires the window to start at the epoch pin and to be exactly 14 calendar days; 319.2 h is printed as DERIVED, not a threshold"
  - "Freeze lines of a trial are those after the pin up to one slot interval after the window end (the last slot's line is written just after the window end); later lines are a later epoch and stay auxiliary"
  - "Closure slots: SC1 REAL_SOAK; SC2 a CODE contract test AND a REAL_SMOKE item; SC3 and SC5 REAL_REHEARSAL or REAL_SOAK; SC7 REAL_SMOKE. PAPER-03 is always 'Pending, Phase 26'"
  - "A failed trial evaluation cannot become SC1 evidence (bundle_evidence_item refuses it)"

patterns-established:
  - "Pattern: an evaluator that REPORTS (PASS or FAIL with the evidence it read) and never edits, drops or interpolates an input; earlier-epoch items are listed under 'auxiliary evidence (not qualifying)' with counts and span"

requirements-completed: []  # none by this plan: PAPER-01 and PAPER-02 close only when closure_verdict sees REAL evidence per criterion (SC9); this plan builds the judge

coverage:
  - id: D1
    description: "A 14-day fixture bundle is loaded, sha256-verified and judged criterion by criterion (window, coverage with the derived 319.2 h, continuous-uncovered ceiling, freeze continuity, single epoch, unchanged pinned hash); time of day is reported, not a pass condition; the fixture is FAKE"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_exit_evaluator.py#test_tracer_a_14_day_fixture_trial_is_judged_criterion_by_criterion"
        status: pass
      - kind: unit
        ref: "tests/test_paper_exit_evaluator.py#test_the_rendered_evaluation_prints_pass_or_fail_per_criterion"
        status: pass
    human_judgment: false
  - id: D2
    description: "A bundle file that does not match the manifest sha256 is refused by name; ratified constants are labelled and witnessed against DECISIONS.md; thresholds, cron, symbols, Q-D rule and parity have no default"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_exit_evaluator.py#test_a_file_that_does_not_match_the_manifest_sha256_is_refused_by_name"
        status: pass
      - kind: unit
        ref: "tests/test_paper_exit_evaluator.py#test_witness_decisions_md_still_carries_the_ratified_numbers"
        status: pass
      - kind: unit
        ref: "tests/test_paper_exit_evaluator.py#test_evaluate_trial_requires_thresholds_and_cron_with_no_default"
        status: pass
    human_judgment: false
  - id: D3
    description: "Parity with tolerance zero over the recorded bars (altered feature digest fails naming the bar close, DATA_STALE reproduced from the recorded tick time); gaps need a real reason; REST_WARMUP, REST_BACKFILL or pre-close bars are late or fabricated; no evaluated bar closed while the process was down; duplicate signal and missing journal row fail; test_only inside the window fails"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_exit_evaluator.py#test_one_altered_recorded_feature_digest_fails_parity_and_names_the_bar_close"
        status: pass
      - kind: unit
        ref: "tests/test_paper_exit_evaluator.py#test_an_expected_close_with_neither_a_bar_nor_a_gap_is_a_missing_journal_row"
        status: pass
      - kind: unit
        ref: "tests/test_paper_exit_evaluator.py#test_a_test_only_record_inside_the_soak_window_fails_the_trial"
        status: pass
    human_judgment: false
  - id: D4
    description: "Earlier-epoch evidence is auxiliary (listed with counts, never qualifies, inputs byte-identical after the run); evaluating the same inputs as epoch E1 reproduces E1's EVIDENCE_GAP; observations are report-only; freeze integrity and runtime health read disjoint inputs"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_exit_evaluator.py#test_earlier_epoch_evidence_is_auxiliary_and_never_qualifies_the_new_trial"
        status: pass
      - kind: unit
        ref: "tests/test_paper_exit_evaluator.py#test_evaluating_the_same_inputs_as_epoch_e1_reproduces_its_evidence_gap"
        status: pass
      - kind: unit
        ref: "tests/test_paper_exit_evaluator.py#test_observations_are_report_only_and_change_no_verdict"
        status: pass
      - kind: unit
        ref: "tests/test_paper_exit_evaluator.py#test_removing_all_runtime_records_changes_no_freeze_result_and_the_reverse"
        status: pass
    human_judgment: false
  - id: D5
    description: "Closure rule: PAPER-01 and PAPER-02 are closable only with REAL evidence per criterion; a complete FAKE and CODE set closes neither (negative control); PAPER-03 is never closable here; proof class follows the evidence source only"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_closure_rule.py#test_a_complete_set_of_fake_and_code_evidence_closes_nothing"
        status: pass
      - kind: unit
        ref: "tests/test_paper_closure_rule.py#test_paper_03_is_never_closable_here"
        status: pass
      - kind: unit
        ref: "tests/test_paper_closure_rule.py#test_a_bundle_proof_class_follows_its_manifest_source_only"
        status: pass
    human_judgment: false
  - id: D6
    description: "That the parity criterion can PASS on a real soak bundle. The command line has no replay context (constraint snapshots, account state and open positions of the live run are not in the bundle), so on a real bundle parity reads NOT EVALUATED and the overall result is FAIL until the runtime records its replay inputs or the user decides on a narrower parity definition"
    requirement: PAPER-01
    verification: []
    human_judgment: true
    rationale: "A design decision, not a code defect: what the replay may assume about the risk context is the user's (parity tolerance zero is ratified; the context source is not)."

duration: about 40 min
completed: 2026-10-10
status: complete
---

# Phase 16 Plan 25: Trial exit-criteria evaluator and requirement closure rule Summary

**One evidence-bundle loader (sha256 verified before parse), one evaluator that prints PASS or FAIL per ratified trial criterion (14 calendar days, 95 percent coverage with the derived 319.2 h, freeze continuity per scheduled tick, single epoch and pinned hash, zero-tolerance parity, no fabricated bar, no duplicate signal, no missing journal row, no test signal in the soak) and a closure rule that makes PAPER-01 and PAPER-02 closable only on REAL evidence per criterion.**

## Performance

- **Duration:** about 40 min (commits 2026-10-10 16:48 to 17:01 +0700)
- **Tasks:** 3 (Task 1 tracer, Tasks 2 and 3 auto, all TDD)
- **Files:** 5 created (3 source and script, 2 test files)

## Accomplishments

- **Bundle (`soak-evidence-bundle/1`)**: `manifest.json` (schema, epoch_id, window_start_utc, window_end_utc, source "pg" or "fixture", files with sha256), `pinned_epoch.json`, `registry_diff.jsonl`, `github_runs.json`, `runtime_records.jsonl`, `evidence_gaps.jsonl`, optional `analytics_evidence.json`. `load_evidence_bundle` hashes every listed file before parsing, refuses a missing file, a manifest entry that is not one of the known file names, an unknown schema or source, a window that ends before it starts, and a float in a record payload. Line shapes: runtime record `{event_type, epoch_id, occurred_at_utc, symbol, interval, payload}`; evidence gap `{slot_utc, schedule, reason, detected_at_utc, run_id}`.
- **Evaluator** (`evaluate_trial(bundle, *, thresholds, cron, symbols, backfill_rule, parity)`), three groups:
  - trial definition: `trial window` (starts at the pin, exactly 14 calendar days);
  - freeze integrity (reads only the pinned epoch, freeze lines, run list, gap records): `freeze continuity` (from `freeze_evidence_report`, plus any EVIDENCE_GAP record inside the window; failure text carries "qualifying trial restarts with a new epoch pin (D065 item 4)"), `single epoch`, `pinned hash unchanged`;
  - runtime health (reads only the judged epoch's runtime records): `runtime coverage` (336 h, covered hours, 319.2 h labelled DERIVED), `continuous uncovered time` (the user's O-07 ceiling), `gaps explained, no fabricated bar`, `restart warm-up before the first evaluated bar`, `no duplicate signal`, `no missing journal row`, `no test signal inside the soak window`, `runtime records of one epoch`, `parity (tolerance zero)`.
  - report-only blocks: time of day per UTC hour (covered and uncovered hours, "reported, not a pass condition"), observations (tick timing summary, dropped events by reason such as FUTURE_CLOSE), auxiliary evidence (not qualifying).
- **Earlier epoch (REV-18)**: lines, runs, runtime records and gap records of an earlier epoch are listed with counts and span under "auxiliary evidence (not qualifying)", never satisfy a slot or colour an interval of the judged epoch, are never edited (bytes and parsed inputs are unchanged after the run), and the output states that earlier-epoch evidence cannot complete the freeze criterion of the new trial. Evaluating the same inputs as epoch E1 reproduces E1's EVIDENCE_GAP. `freeze_tick_grace_seconds` is read exactly once, as the `grace_seconds` argument of `freeze_evidence_report` (AST test).
- **Closure rule (SC9)**: `closure_verdict(items)` with `EvidenceItem(criterion, proof_class, path, sha256)` and four factories (`bundle_evidence_item`, `smoke_evidence_item`, `rehearsal_evidence_item`, `code_evidence_item`), none with a proof_class parameter. A failed trial evaluation cannot become an item.

### Requirement-to-criterion map (ROADMAP SC9, D061 item J)

| Requirement | Criteria | What counts as real |
|-------------|----------|---------------------|
| PAPER-01 | SC1 | a REAL_SOAK item (pg bundle whose evaluation passed) |
| PAPER-01 | SC2 | a CODE item (the contract test) AND a REAL_SMOKE item (smoke file `proof_class` REAL_SMOKE) |
| PAPER-01 | SC7 | a REAL_SMOKE item |
| PAPER-02 | SC3 | a REAL_REHEARSAL or REAL_SOAK item |
| PAPER-02 | SC5 | a REAL_REHEARSAL or REAL_SOAK item; SKIP, CANCEL and expiry journaling printed as "CODE and PG proof only, disclosed" for the O-11 (v) declaration |
| PAPER-03 | none | always "Pending, Phase 26" |

## RED Evidence

- **Task 1** (`8968753`): collection failed with `ImportError: cannot import name 'evidence_bundle' from 'src.paper'`. GREEN `a07bdd3`: 23 tests pass.
- **Task 2** (`f71ce14`): collection failed with `ImportError: cannot import name 'BackfillRule' from 'src.paper.exit_criteria'`. GREEN `927fe37`: all tests of the file pass (one test was fixed in the same GREEN: lines are bounded to one slot interval after the window end so a later epoch's lines do not break the earlier epoch's `single epoch`).
- **Task 3** (`e8b9593`): collection failed with `ImportError: cannot import name 'PAPER_03_STATUS' from 'src.paper.exit_criteria'`. GREEN `8bb6a8d`: closure tests pass.

## Task Commits

1. **Task 1 (tracer):** `8968753` (test, RED), `a07bdd3` (feat, GREEN)
2. **Task 2:** `f71ce14` (test, RED), `927fe37` (feat, GREEN)
3. **Task 3:** `e8b9593` (test, RED), `8bb6a8d` (feat, GREEN)

Tracer gate: `<verify>` of the tracer re-run end to end after Task 1 and after each later task; green each time.

`git rev-list --count` over the plan range reports 12 because plan 16-26 committed on the same branch at the same time (6 of its commits sit in the range); the 6 commits of this plan are listed above (`git log --grep "(16-25)"`).

## TDD Gate Compliance

RED and GREEN commits exist for each of the three tasks, in order (`test(16-25)` before `feat(16-25)`). Each RED failed at collection on the missing symbol the test imports, as in earlier plans of this phase; no REFACTOR commit.

## Decisions Made

See `key-decisions`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] `evaluate_trial` takes three more required inputs**
- **Found during:** Task 1 and Task 2 design
- **Issue:** the plan names `evaluate_trial(bundle, *, thresholds, cron)`. Coverage cannot be derived without the expected (symbol, interval) pairs (a symbol that never appears in the records would otherwise be invisible), the Q-D rule must come from its decision file ("never from a default"), and parity needs a replay context.
- **Fix:** keyword-only, no defaults: `symbols`, `backfill_rule` (read with `read_backfill_rule(path)`), `parity` (`ParityReplay` or None). `parity=None` makes the criterion "NOT EVALUATED" and FAIL.
- **Files modified:** src/paper/exit_criteria.py, tests/test_paper_exit_evaluator.py
- **Committed in:** a07bdd3, 927fe37

**2. [Rule 2 - Missing critical functionality] Command line additions**
- `--q-d-decision` (required) and `--workflow` (default `.github/workflows/paper_freeze_check.yml`, the cron string is parsed from it; exactly one cron or exit 2); `main(argv, *, parity=None)` is a seam for tests and for a future replay-context source. Committed in a07bdd3 and 927fe37.

**3. [Rule 2 - Missing critical functionality] Fail-closed readings the plan did not spell out**
- `single epoch` and `pinned hash unchanged` fail when no freeze line after the pin carries the field (nothing can be shown); a runtime record of another epoch inside the window fails `runtime records of one epoch`; an unknown or UNKNOWN gap reason is an unexplained gap; a bundle manifest may list only the known file names.
- Freeze lines are bounded to one slot interval after the window end, so a later epoch's lines cannot break an earlier epoch's evaluation (found by the E1 re-evaluation test).

### Plan-shape choices (not defects)

- Test helper imports: the closure and parity tests reuse `tests.test_paper_runtime_pipeline.Fixture` and `tests.test_paper_decision_surface` helpers (the Phase 7 parity fixture); no new helper file.
- `PIPELINE-only` gate records (`HISTORY_DISCONTINUITY`, `SIBLING_4H_MISSING`) depend on the pipeline's own buffers; parity counts them and does not compare them.

**Total deviations:** 3 auto-fixed (all Rule 2). **Impact:** stricter than the plan, never looser; no threshold, default or semantics of an existing module changed; no package installed; `uv.lock` unchanged.

## Known Limitations (for plans 16-26, 16-30, 16-43, 16-44 and the user)

- **Parity on a real bundle is NOT EVALUATED from the command line.** The decision surface of the risk stage depends on the constraint snapshot, account state, open positions and daily loss the live runtime used; none of them is in the bundle (the PAPER_BAR_PROCESSED payload holds the bar and the surface only). So `scripts/evaluate_trial_soak.py` run on a real bundle prints `FAIL  parity (tolerance zero)` with "NOT EVALUATED" and exits 1. Options for the user or the next plan: record the replay inputs (for example a context digest and the constraint snapshot used per bar) in the runtime records or the bundle, or ratify a narrower parity (replay up to the strategy stage). This plan does not choose.
- **Warm-up completion is not directly observable from records.** The restart check enforces the observable part: no evaluated bar closed before the start of its run, and every evaluated bar sits inside a recorded run.
- **Gap explanation** checks the reason code (present, known, not UNKNOWN); it does not cross-check each reason against a recorded stop or disconnect span. Coverage already counts every gap as uncovered.
- The bundle loader reads the shapes defined here; plan 16-30's exporter must write exactly these (its Test 1 loads its output through `load_evidence_bundle`).

## Issues Encountered

- A long bash heredoc failed to parse twice (quoting); larger additions were written through the Write tool into a scratch file and spliced with a short script.
- `ruff check --fix` on the test file removed imports that its later tests needed; restored by hand before the RED commit.

## Known Stubs

None.

## Threat Flags

None. The modules and the script read files of one directory and write one output file; no network, no clock, no secret. T-16-58 (fake evidence closing a requirement) mitigated: proof class from the source only, REAL item per criterion, negative-control test, a failed evaluation cannot become evidence. T-16-59 (bundle edited after export) mitigated: sha256 per file verified before parsing, foreign file names refused. T-16-SC accepted: no package installed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 16-30 (exporter) writes the layout above; plan 16-44 runs `scripts/evaluate_trial_soak.py --bundle <dir> --config config/paper/paper-runtime-v1.toml --q-d-decision .planning/phases/16-paper-runtime-composition/decisions/16-DEC-Q-D.md --out evidence/16-44-trial-evaluation.txt` and appends `closure_verdict` over the items. Note the added `--q-d-decision` argument and the parity limitation above.
- The user owns the parity-context decision (see Known Limitations).

## Verification

- `.venv/Scripts/python -m pytest tests/test_paper_closure_rule.py tests/test_paper_exit_evaluator.py tests/test_paper_coverage.py tests/test_paper_freeze_evidence.py tests/test_domain_no_float.py -q -p no:cacheprovider`: 165 passed.
- `ruff check` and `ruff format --check` on the five files: clean. `mypy src`: 177 files, no issues.
- No file deleted by any commit; no package installed.

## Self-Check: PASSED

- FOUND: src/paper/evidence_bundle.py, src/paper/exit_criteria.py, scripts/evaluate_trial_soak.py, tests/test_paper_exit_evaluator.py, tests/test_paper_closure_rule.py
- FOUND commits: 8968753, a07bdd3, f71ce14, 927fe37, e8b9593, 8bb6a8d
