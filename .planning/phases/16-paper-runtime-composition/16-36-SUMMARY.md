---
phase: 16-paper-runtime-composition
plan: 36
subsystem: paper evidence export / analytics reporting
tags: [shadow, analytics-evidence, approval-delay, synthetic-lag, test-only, rev-03, d-18, p15, paper-02]

requires:
  - phase: 16-paper-runtime-composition
    provides: "plan 16-35: PaperRecord SHADOW fields, assemble_paper_record(shadow_outcome=...), canonical_record_dict, evidence loader keys; plan 16-05: the kill-gate report guard (NOT CONCLUDED on real evidence)"
provides:
  - "src/paper/evidence_export.py: ShadowRow, export_shadow_evidence, evidence_file_bytes, EVIDENCE_FILE_SCHEMA"
  - "src/analytics/lifecycle.py: exclude_test_only, paper_delay_is_synthetic; synthetic_lag set from the presence of a measured approval request time"
  - "src/analytics/report.py: EvidenceInputs / EvidenceBlock counters shadow_records and test_only_excluded (digest and sidecar only when non-zero)"
  - "src/analytics/render.py: the D-18 sentence and the 'test_only records excluded: N (D063 item 3)' line under the evidence overview"
  - "tests/test_paper_shadow_evidence_export.py (14 tests), additions in test_analytics_lifecycle.py and test_analytics_approval_delay.py"
affects: [16-30 trial export (passes backtest entries and research universe to the exporter), 16-31 runtime composition (builds ShadowRow from the journal), 16-25 (fails a trial that contains test_only rows)]

requirements-completed: [PAPER-02]

actuals:
  tokens: 11500
  tasks: 3
  commits: 6
plan_head_before: 577767b5b88a19ff7d7c4de06bc3fc6020ea766a
plan_head_after: 478c87282233d35172b5fd322dac95eda852fac0
commits: 6

tech-stack:
  added: []
  patterns:
    - "Optional report counters enter the digest and the JSON sidecar only when non-zero (SIDECAR_OMIT_WHEN_ZERO), so every report without SHADOW evidence keeps its digest, sidecar and Markdown goldens byte for byte"
    - "test_only rows are dropped once at the analytics edge (exclude_test_only) and counted; every downstream normalizer sees the same rows"
    - "The synthetic-lag label is a function of the normalized records (paper_delay_is_synthetic), shared by the approval-delay and execution-quality sections"

key-files:
  created:
    - src/paper/evidence_export.py
    - tests/test_paper_shadow_evidence_export.py
  modified:
    - src/analytics/lifecycle.py
    - src/analytics/approval_delay.py
    - src/analytics/latency.py
    - src/analytics/report.py
    - src/analytics/cli.py
    - src/analytics/render.py
    - src/analytics/render_sidecar.py
    - tests/test_analytics_lifecycle.py
    - tests/test_analytics_approval_delay.py

key-decisions:
  - "The exporter takes a ShadowRow (signal, trade plan, approval, order, fill, confirm, ShadowOutcome, test_only) and has no clock or I/O; the caller writes evidence_file_bytes(document). A ShadowOutcome is required so the exporter never guesses what happened to a plan"
  - "A paper user-executed row is measured (synthetic_lag False) iff it carries approval_requested_at_utc; the request time becomes the delivery-request proxy, as for LIVE evidence, so the existing latency legs measure the real delay with no new metric"
  - "The SYNTHETIC LAG label stays for a paper section that has a synthetic user-executed record or no user-executed record at all (status quo for Phase 7-10 evidence); it is dropped only when every user-executed approval is measured. A section that mixes both keeps the label (one label per section)"
  - "The soak sentence is printed when the PAPER block holds SHADOW-mode records, not for every paper record: the committed Phase 10 render goldens contain paper data and must stay byte-exact"
  - "test_only is counted in records (rows), not signals"

patterns-established:
  - "Display counters on EvidenceBlock: add a field, omit it from digest() and the sidecar while zero"

coverage:
  - id: D1
    description: "SHADOW rows (APPROVE then CONFIRM, SKIP, APPROVAL_EXPIRED, untouched plan) export to a real analytics-evidence/2 file; the analytics CLI reports one user-executed-sim, two opportunity and one system-only signal, the kill-gate line reads NOT CONCLUDED with WR-01, WR-06, WR-12, WR-13, and the export is byte-identical and independent of row order"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_evidence_export.py#test_shadow_rows_export_as_real_evidence_and_report_three_way_outcomes"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_evidence_export.py#test_the_kill_gate_stays_not_concluded_on_the_real_shadow_evidence"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_evidence_export.py#test_exporting_the_same_rows_twice_is_byte_identical_and_order_independent"
        status: pass
    human_judgment: false
  - id: D2
    description: "Records with a measured delay are not labelled SYNTHETIC LAG (approval-delay and execution-quality sections); a section without a human action keeps the label exactly as before"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_analytics_approval_delay.py#test_measured_paper_delays_carry_no_synthetic_lag_label"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_approval_delay.py#test_a_paper_section_without_a_user_executed_record_keeps_the_label"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_lifecycle.py#test_a_user_executed_row_with_a_measured_approval_is_not_synthetic_lag"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_evidence_export.py#test_measured_shadow_delays_are_not_labelled_synthetic_lag_in_the_report"
        status: pass
    human_judgment: false
  - id: D3
    description: "test_only rows are excluded from signal counts, delay blocks, execution quality, NO_TRADE counts and epoch provenance; the report prints how many were excluded"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_evidence_export.py#test_test_only_rows_are_excluded_from_every_paper_count_and_the_report_says_so"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_lifecycle.py#test_the_paper_normalizer_never_sees_a_test_only_row"
        status: pass
    human_judgment: false
  - id: D4
    description: "The rendered report states that soak evidence never feeds a value into trading logic, and the SHADOW fixture adds no section, metric or column (only the two display counters)"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_evidence_export.py#test_a_report_of_shadow_evidence_states_the_soak_rule_once"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_evidence_export.py#test_shadow_evidence_adds_no_metric_or_section_to_the_report"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_evidence_export.py#test_the_new_sentence_obeys_the_byte_rules_of_the_renderer"
        status: pass
    human_judgment: false
  - id: D5
    description: "The exporter is fed real journal facts (approval row, confirm events, orders, fills) by the running SHADOW chain and the trial export passes the backtest entries"
    requirement: PAPER-02
    verification: []
    human_judgment: true
    rationale: "Building ShadowRow from the journal is plan 16-31; passing backtest entries and the research universe is plan 16-30. This plan provides the exporter, the normalizer changes and the report statement"

duration: 45min
completed: 2026-10-10
status: complete
---

# Phase 16 Plan 36: SHADOW decision history through the analytics path Summary

**SHADOW approval and confirm rows now export to a real `analytics-evidence/2` file that the unchanged Phase 10 CLI reports as system, user-executed-sim and opportunity outcomes, measured approval delays are no longer labelled SYNTHETIC LAG, `test_only` rehearsal rows are excluded and counted, and the report states that soak evidence never feeds trading logic, with no metric added and every pinned digest and golden unchanged.**

## Performance

- **Tasks:** 3 (Task 1 tracer, Tasks 2 and 3 TDD), 6 commits (3 RED, 3 GREEN)
- **Files:** 11 (2 created, 9 modified)
- **Plan base:** `577767b` (the worktree was fast-forwarded to `develop` first, see Deviations)

## Accomplishments

- `export_shadow_evidence(rows, *, research_universe, backtest_entries)` maps each `ShadowRow` to its `PaperRecord` rows through `assemble_paper_record` and returns the evidence document (no `evidence_class` key, so it is REAL and the plan 16-05 guard applies). Records are sorted by signal and attribution; `evidence_file_bytes` is canonical JSON plus one LF.
- Lifecycle normalization: a user-executed paper row with a measured `approval_requested_at_utc` has `synthetic_lag=False` and the request time as the delivery-request proxy; the approval-delay and execution-quality sections drop the SYNTHETIC LAG label and seconds only when every user-executed approval is measured.
- `exclude_test_only` drops rehearsal rows once at the edge (`cli._paper_inputs`) and the report prints `test_only records excluded: N (D063 item 3)`.
- Report: `Soak evidence never feeds a value into trading logic (D-18).` under the evidence overview whenever SHADOW paper records are present.

## RED Evidence

- **Task 1** (`9bda790`): collection failed with `ModuleNotFoundError: No module named 'src.paper.evidence_export'`.
- **Task 2** (`e7e8d3e`): `test_analytics_lifecycle.py` failed at collection (`cannot import name 'exclude_test_only'`); five new tests failed in the other two files (for example `assert 30 is None` for the execution-quality seconds of a measured record).
- **Task 3** (`29f52e2`): `test_a_report_of_shadow_evidence_states_the_soak_rule_once` and `test_the_new_sentence_obeys_the_byte_rules_of_the_renderer` failed (`assert 0 == 1`). The set-equality and sentence-absent guard tests pass before and after by design (they guard against regression).

## Verification

- Task 1 to 3 commands: `pytest tests/test_paper_shadow_evidence_export.py tests/test_analytics_cli.py`, the seven analytics suites of Task 2, and `tests/test_paper_shadow_evidence_export.py tests/test_analytics_render.py`: green. `tests/test_analytics_sidecar.py`, `test_analytics_report.py`, `test_killgate_guard.py`, `test_domain_no_float.py`, `test_analytics_edge_guards.py`: green with no golden or expected literal edited.
- `pytest -m "not docker" -k "analytics or killgate or paper or evidence or domain_no_float"` (deselecting the known `tests/test_cost_parity.py` failure in `deferred-items.md`): all passed.
- Whole suite `pytest -m "not docker" -x --deselect tests/test_cost_parity.py`: exit 0 (no failure).
- `ruff check`, `ruff format --check` (src and tests): clean. `mypy src` (170 files): clean. `uv lock --check`: clean.
- No network, `.env` not read, no package installed.

## Decisions Made

See `key-decisions` above.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree base was stale**
- **Found during:** startup
- **Issue:** the worktree HEAD (`9186194`) predated the Phase 16 plans and the plan 16-35 code; the plan file and `src/paper/journal.py` SHADOW fields did not exist.
- **Fix:** `git merge --ff-only develop` (the branch was a strict ancestor with no local work), then `uv sync --frozen --extra dev`.

**2. [Rule 3 - Blocking] The plan's file list was too small for "excluded from every count" and the report line**
- **Issue:** the report line needs a counter carried through the report tree, and the exclusion has to happen where the paper records enter the analytics (the CLI), not only in a normalizer.
- **Fix:** also modified `src/analytics/report.py` (two display counters on `EvidenceInputs` and `EvidenceBlock`), `src/analytics/cli.py` (`_paper_inputs` calls `exclude_test_only`), `src/analytics/render_sidecar.py` (omit the counters from the sidecar while zero) and `src/analytics/latency.py` (the execution-quality `synthetic_lag_seconds` follows the same rule as the approval-delay label, otherwise the sidecar would still claim a 30 s synthetic lag for measured records).
- **Commit:** 4d5e74f

**3. [Interpretation] The soak sentence is conditional on SHADOW records**
- The plan says "printed whenever paper records are present". The committed Phase 10 render and sidecar goldens contain paper data without a mode; printing the sentence for them would edit expected literals. It is printed whenever the PAPER block holds SHADOW-mode records, which is every soak report.

**4. [Interpretation] "One system outcome"**
- The "untouched NO_TRADE plan" of Task 1 Test 1 is a signalled plan nobody touched and that has not expired (`SYSTEM_ONLY`). The system block counts all four signals the engine emitted, which the test asserts together with the one `SYSTEM_ONLY` path.

### TDD ordering

Each task has its RED commit before the GREEN commit.

**Total deviations:** 2 auto-fixed (Rule 3) plus 2 interpretations. **Impact:** none on behaviour outside the plan's intent; Phase 7 to 10 digests, sidecars and goldens are unchanged.

## Known Stubs

None.

## Threat Flags

None beyond the plan's register. T-16-83 (rehearsal rows inflating counts) is covered by the exclusion at the edge, the printed counter and `test_test_only_rows_are_excluded_from_every_paper_count_and_the_report_says_so`; T-16-84 (soak evidence as a trading input) by the set-equality test (only the two display counters are new keys), the report sentence and the unchanged NOT CONCLUDED kill-gate line. No package installs (T-16-SC).

## Notes for later plans

- Plan 16-31 builds `ShadowRow` from the journal; plan 16-30 passes `backtest_entries` and `research_universe` (the same shape as the `backtest` and `research_universe` parts of an evidence file).
- `test_only` is counted in records. Plan 16-25 still has to refuse a trial that contains test_only rows; this plan only excludes and reports them.
- The sidecar/digest omit-when-zero pattern (`SIDECAR_OMIT_WHEN_ZERO` on `EvidenceBlock`) is available for later display counters.

## Self-Check: PASSED

- FOUND: src/paper/evidence_export.py, tests/test_paper_shadow_evidence_export.py, src/analytics/lifecycle.py, src/analytics/render.py
- FOUND commits: 9bda790, 138619e, e7e8d3e, 4d5e74f, 29f52e2, 478c872
