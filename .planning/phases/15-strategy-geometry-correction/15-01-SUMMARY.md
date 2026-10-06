---
phase: 15-strategy-geometry-correction
plan: 01
subsystem: research-governance
tags: [geometry-audit, family-sheets, F-113, leakage, parser-test, docs]

requires:
  - phase: 12-fee-cost-model-correctness
    provides: Phase 12 cost guards whose thresholds frame the B/C arithmetic rows
  - phase: 14-backtest-causality-rewrite
    provides: engine and hand-derived-fixture discipline the later geometry plans rely on
provides:
  - "docs/research/GEOMETRY_AUDIT.md: 20-row sheet-vs-code audit (A 7, B 8, C 5) with verdict and deciding decision per cell"
  - "Leakage verdicts for Families B and C (D-13): evaluated bar never feeds the reference level"
  - "Universal planner invariant list and fixed check order (D-06, D-07, D-08, F6; invariants before RR per D-26)"
  - "Research flags F1-F12 mapped to disposition and owning Phase 15 plan"
  - "tests/test_geometry_audit_doc.py: machine check of the table (REQUIRED_CELLS, verdict vocabulary, decision citations, TBD ban, flag list, headings)"
affects: [15-03, 15-04, 15-05, 15-06, 15-14, 15-15]

actuals:
  tokens: 6130
  tasks: 2
  commits: 2
plan_head_before: bbb4bca54c381909b689bf0acacc15da3c0459f8
plan_head_after: 022289e3387fdf311d239c13fc555203dd8956ef

tech-stack:
  added: []
  patterns:
    - "Audit doc is parsed by a test: a markdown table with a fixed header is a machine-checked artifact"
    - "Negative tests run the parser on mutated copies of the doc (missing row, bad verdict, uncited deviation, TBD)"

key-files:
  created:
    - docs/research/GEOMETRY_AUDIT.md
    - tests/test_geometry_audit_doc.py
  modified: []

key-decisions:
  - "Verdicts as proposed by RESEARCH section 4, rewritten with D-22..D-27 winning over D-10/D-11: B stop FIX (D-23, the D-10 'keep the code stop' bullet is superseded), B direction and anchoring FIX (D-24), C regime and stop FIX (D-22/D-23), C target FIX to T-mid (D-10), A/B regime DEVIATION (D-22)"
  - "B breakout_confirmation_bars is PARAMETER (proposed 1 = sheet B1, ratified at the 15-08 checkpoint), not a pre-decided FIX"
  - "D-23 basis is recorded as the sheet text alone; guard-survival figures are labelled arithmetic consequences, not the reason"

patterns-established:
  - "Decision cell of every non-MATCH row must match D-NN or D054; MATCH rows carry n/a"

requirements-completed: [STRAT-02]

duration: 25min
completed: 2026-10-06
status: complete
---

# Phase 15 Plan 01: Geometry Audit Summary

**Sheet-vs-code geometry audit for the three families (20 cells, each with a MATCH/FIX/DEVIATION/PARAMETER verdict and a deciding decision), with leakage verdicts, the shared invariant order and a disposition for every research flag F1-F12, all guarded by a parser test.**

## Accomplishments

- Task 1 (tracer): created `docs/research/GEOMETRY_AUDIT.md` with the verdict vocabulary, the exact table header, the seven Family A rows and the Arithmetic section (old stop 59,920 inside the entry zone; new LONG SL 59,680, RR 5.00, adverse distance 560 = 0.930 percent, cost-to-risk 0.1303, equity 500 qty 0.003 risk 1.932, equity 1000 qty 0.007 risk 4.507; acceptance reworded to "no plan with SL inside the zone"). Created the parser test, including a negative test that deletes the `level` row. Tracer gate: the test passed end to end before expansion.
- Task 2: added 8 Family B rows and 5 Family C rows, a "Leakage verdicts (D-13)" section (B: `ref_prev = i - breakout_confirmation_bars - 1`, retest search from `i + 1`; C: `ref_idx = n - 2`, touches before it; both no leak, trailing helper stays for B/C per D-04, caveat that C's level can be set by bar n-2), a "Universal planner invariants" table (SL outside the whole zone STOP_TOO_TIGHT, signal bar through stop INVALIDATED, `min_stop_atr` STOP_TOO_TIGHT, TP1 profit side RR_TOO_LOW, RR gate), the 12-row flags table with owning plans, and the B/C arithmetic rows (labelled as consequences of a reading, not the basis of D-23).
- The test now requires 20 (family, cell) pairs, exactly one row each, verdicts in the vocabulary, a D-NN/D054 citation on every non-MATCH row, no TBD token, F1..F12 exactly once each with a plan cell, and the leakage and invariants headings.

## Task Commits

1. Task 1: `2055f0c` docs(15-01): geometry audit skeleton with Family A rows and parser test
2. Task 2: `022289e` docs(15-01): audit Families B and C, leakage verdicts, invariants, flag dispositions

## Deviations from Plan

None - plan executed exactly as written.

Notes: line references in the doc were checked against the on-disk code (strategy.py 98-120, 236, 257-262, 293, 401-404, 433, 583, 592; planner.py 109-197, 382-389, 409; features.py 187). The plan's flags-table disposition list was followed verbatim, including the plan-number mapping.

## Verification

- `tests/test_geometry_audit_doc.py` 11 passed; together with `tests/test_decision_alignment_authority.py` and `tests/test_decision_alignment_exchange.py` all pass (141 tests).
- `ruff check src tests scripts` clean, `ruff format --check src tests scripts` clean (376 files), `mypy src` clean (147 files).
- `grep -c "^| F[0-9]"` prints 12; "Leakage verdicts (D-13)" and "superseded by D-23" present; the Arithmetic section contains "59,680".

## Regeneration inventory

None: both files are new. No fixture, pin, hash, signal id or parameter set moved.

## Known Stubs

None.

## Threat Flags

None. The only artifacts are a markdown doc and a test; no network, auth, file-access or schema surface. T-15-01 (repudiation of the geometry audit) is mitigated by the parser test.

## Self-Check: PASSED

- FOUND: docs/research/GEOMETRY_AUDIT.md
- FOUND: tests/test_geometry_audit_doc.py
- FOUND: commits 2055f0c, 022289e
