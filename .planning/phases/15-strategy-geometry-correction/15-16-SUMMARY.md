---
phase: 15-strategy-geometry-correction
plan: 16
subsystem: docs
tags: [decisions, D054, baselines, doc-test, gap-closure]
status: complete

requires:
  - phase: 15-strategy-geometry-correction
    provides: D054 row, hash-locked baseline-no-trade-v4 and baseline-simple-trend-v4 sets (15-08, 15-09)
provides:
  - D054 sentence labelling the three -v4 override values as comparison reference points, not evidence-backed parameters
  - doc test tying that sentence to the two hash-locked set files
affects: [phase-16 baselines comparison, RESEARCH_PROTOCOL Baselines]

actuals:
  tokens: 900
  tasks: 1
  commits: 2
plan_head_before: 3df767a268a0339198c94a42524db23f8b0fa481
plan_head_after: 641da997b1f61cb806ba5218091e1a76539c28cd

tech-stack:
  added: []
  patterns: ["doc test cross-checks a DECISIONS row against registry values, rationale tables and pinned hashes"]

key-files:
  created: []
  modified:
    - docs/DECISIONS.md
    - tests/test_kill_gate_docs.py

key-decisions:
  - "D054 records the user's 2026-10-07 answer (15-UAT.md test 10): baseline-no-trade-v4 minimum_rr 100 and baseline-simple-trend-v4 zone_tolerance_atr 1.0 / minimum_rr 0.5 are comparison reference points, not evidence-backed parameters"

requirements-completed: [STRAT-02]

coverage:
  - id: D1
    description: "D054 states the three -v4 override values are comparison reference points, not evidence-backed parameters, quoting the user's answer verbatim"
    requirement: "STRAT-02"
    verification:
      - kind: unit
        ref: "tests/test_kill_gate_docs.py#test_d054_v4_overrides_are_comparison_reference_points"
        status: pass
    human_judgment: false
  - id: D2
    description: "No params file changed; both -v4 files keep their pinned hashes and DECISION/D054 basis"
    requirement: "STRAT-02"
    verification:
      - kind: other
        ref: "python -m scripts.decision_alignment.params (PA-01..PA-08 ok); git status --porcelain -- params empty"
        status: pass
    human_judgment: false

duration: 10 min
completed: 2026-10-07
---

# Phase 15 Plan 16: D054 comparison-reference-point label Summary

D054 now says in plain words that baseline-no-trade-v4 minimum_rr 100 and baseline-simple-trend-v4 zone_tolerance_atr 1.0 / minimum_rr 0.5 are comparison reference points for the RESEARCH_PROTOCOL Baselines comparison, not evidence-backed parameters, quoting the user's reply "Là mốc đối chứng, ghi rõ" verbatim (closes G-15-10).

## Accomplishments

- One sentence added to the single D054 row (after "the 15-08 report flagged this for the user's attention)."): date, source (15-UAT.md test 10), verbatim user reply, the three values, "comparison reference points", "not evidence-backed parameters", not tuned, and why the in-file label stays DECISION/D054 (hash-locked; a different label needs a new set file and a new parameter_set_hash, which Phase 15 does not create).
- New doc test `test_d054_v4_overrides_are_comparison_reference_points` checks the label tokens, that D054 stays one 4-cell row, the three values via `load_parameter_set` (Decimal comparison), basis DECISION and D054 in the three rationale tables, and both pinned parameter_set_hash values (in the files and in the row).

## Task Commits

1. Task 1 RED: `8f39735` test(15-16) - new test failed with `AssertionError: D054 row must mention 'comparison reference points'` before the D054 edit.
2. Task 1 GREEN: `641da99` docs(15-16) - D054 sentence added; test passes.

## Verification

- Per-file pytest (one process each): tests/test_kill_gate_docs.py (11 passed), test_decision_alignment_bookkeeping.py, test_geometry_audit_doc.py, test_rationale.py, test_decision_alignment_params.py: all passed.
- `python -m scripts.decision_alignment.params`: PA-01..PA-08 ok.
- `ruff check tests` clean; `ruff format --check tests` clean (220 files).
- Acceptance greps: `^| D054 |` count 1; "comparison reference points for the RESEARCH_PROTOCOL Baselines comparison" count 1; "not evidence-backed parameters" count 1.
- `git show --name-only` of the GREEN commit lists only docs/DECISIONS.md; `git status --porcelain -- params` prints nothing; nothing under src/ changed.
- CI-only (not run): PostgreSQL, docker, bootstrap and deploy tests.

## Deviations from Plan

None - plan executed exactly as written. (Note: the plan's `ref D054` is carried in the rationale `text` fields of the set files, not a separate `ref` key; the test checks basis DECISION and "D054" in the text.)

## Notes for the user

The in-file rationale text of the three values already calls them the no-trade and simple-trend "comparison baseline" values, with basis DECISION and ref D054. That label stays because the set files are hash-locked. Changing the basis label would need a new set file and a new parameter_set_hash, which needs your approval; this plan does not do it.

## Known Stubs

None.

## Threat Flags

None.

## Self-Check: PASSED

- docs/DECISIONS.md and tests/test_kill_gate_docs.py modified and committed (8f39735, 641da99 found in git log).
- All acceptance criteria re-run and passing.
