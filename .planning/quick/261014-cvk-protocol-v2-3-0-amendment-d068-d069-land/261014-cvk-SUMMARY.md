---
phase: quick-261014-cvk
plan: 01
subsystem: research-protocol / acceptance-gate G3 / constraint assumption
tags: [protocol-v2.3.0, D068, D069, holm, multiplicity, constraint-assumption, decision-alignment]
requires: [16-DEC-V230 (user adopt, 2026-10-14), 16-DEC-O-03b-constraint]
provides:
  - "research protocol v2.3.0 frozen (header, D068 freeze row, DOC_STATUS, holdout marker, research-gate comment)"
  - "G3 is one Holm-Bonferroni procedure over the 48 candidate-level hypotheses (D069)"
  - "declared exchange-constraint assumption, scenarios S0 and S1, new reporting fields (D068)"
  - "src/research/multiplicity.py: Decimal Holm step-down and the 48-id set builder"
  - "research-run-1-hypothesis-ADDENDUM-v2.3.0.md (the approved hypothesis file is hash-pinned and unedited)"
affects: [plan 16-37 Task 1 and Task 3, plan 16-46]
status: complete
commits: 5
plan_head_before: 47c624de7346a243fcef6c7283ab0f4ce3936d57
plan_head_after: d44d6a15f9f5a036995023a725f193988afdc712
actuals:
  tokens: 160000
  tasks: 5
  commits: 5
key-files:
  created:
    - src/research/multiplicity.py
    - tests/test_research_multiplicity.py
    - docs/research/preregistration/research-run-1-hypothesis-ADDENDUM-v2.3.0.md
    - .planning/phases/16-paper-runtime-composition/evidence/16-V230-landing-check.txt
  modified:
    - docs/research/RESEARCH_PROTOCOL.md
    - docs/DECISIONS.md
    - docs/DOC_STATUS.md
    - docs/research/holdout_consumed.json
    - docs/backtest/BACKTEST_SPEC.md
    - docs/research/GEOMETRY_AUDIT.md
    - .github/workflows/research-gate.yml
    - scripts/decision_alignment/protocol.py
    - tests/test_kill_gate_docs.py
    - tests/test_decision_alignment_protocol.py
    - tests/test_decision_alignment_bookkeeping.py
    - tests/test_research_run1_registration.py
decisions:
  - "Hypothesis id is the string strategy_id/parameter_set_id (parameter-set ids are unique across the three grids; the prefix keeps them unambiguous)"
  - "P-values and adjusted values are Decimal; float, int, bool and str are refused (the repo Decimal-only scan covers src/research)"
  - "Lineage statement lives once in section 0: no strategy version moves; registration lineage is not the holdout lineage"
  - "Freeze row convention: D068 is the one row with 'protocol v2.3.0 frozen'; D069 says it belongs to the same release"
---

# Phase quick-261014-cvk Plan 01: Protocol v2.3.0 (D068 constraint assumption, D069 global Holm) Summary

Research protocol v2.3.0 now holds a declared exchange-constraint assumption with pre-registered scenarios S0 and S1 (D068) and a G3 that is one Holm-Bonferroni procedure over the 48 candidate-level hypotheses of the three registered grids (D069), with the correction step coded and tested on supplied p-values; the p-value producer is not built.

## Tasks

| Task | Result | Commit |
|------|--------|--------|
| 1 (user adoption, done before this run) | `16-DEC-V230.md` has `option: adopt`; committed with the plan | fab893e |
| 2 Holm module, tests first | red first (ImportError), then 23 tests green; later switched to Decimal | 85f4836, d44d6a1 |
| 3 Protocol text, D068/D069, DOC_STATUS, holdout marker, BACKTEST_SPEC, GEOMETRY_AUDIT | G1/G5 byte-identical, params/ untouched | f80e0a2 |
| 4 Witnesses, new pins, addendum | tests moved or added, DC-03 on D068, hypothesis file hash-pinned | f80e0a2, 059a42d |
| 5 Gates and evidence | all green; evidence `.planning/phases/16-paper-runtime-composition/evidence/16-V230-landing-check.txt` | docs commit after this summary |

## What changed

- `docs/research/RESEARCH_PROTOCOL.md`: header v2.3.0 (`Frozen on` 2026-09-19 unchanged, `Amended on` 2026-10-14, `Supersedes` v2.2.0); migration paragraph naming the v2.2.0 commit `03573dbc4d3e68ac33a14927d37262d2e428c4bc`; the lineage sentence in section 0 rewritten (registration lineage is not the holdout lineage; `strategy_version` stays v5.0.0); new section 2 subsection "Exchange-constraint assumption (v2.3.0)"; the G3 line (one line, em dash prefix kept); the "about 14%" sentence replaced; power note recomputed (0.05/48 = 0.00104, z about 3.078, about 0.37 R, against 0.002, 2.878 and 0.35 R); two new reporting fields in section 4; scenario text in section 5; amendment log line; v2.3.0 added to the two precedent lists.
- `docs/DECISIONS.md`: D068 (the only row with `protocol v2.3.0 frozen`) and D069 directly after D067.
- Witnesses moved to the version in force: research-gate comment, `REQUIRED_PREREGISTRATION_PHRASES` ("about 14%" replaced by four G3 phrases), header-version and DC-03 tests, `EXPECTED_SUPERSEDES`, DOC_STATUS index test. Historical v2.2.0 mentions (experiment.py, analytics_files.py, run.py and their tests, D067, CONFIGURATION line 158, DEPLOY_GUIDE.vi.md, the two hypothesis files) were not touched.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Holm module switched from float to Decimal**
- **Found during:** Task 5 (full `uv run pytest -m "not docker"`)
- **Issue:** `tests/test_domain_no_float.py` scans `src/research/*.py` and rejected the float literals of the first version of `src/research/multiplicity.py` (the plan allowed float). Editing that guard is outside `files_modified`, and its docstring forbids weakening the scan.
- **Fix:** p-values and adjusted values are `Decimal`; `FAMILY_WISE_ALPHA = Decimal("0.05")`; floats, ints, bools and strings are refused. A bootstrap p-value is the rational (k + 1) / (B + 1), so Decimal fits. Tests rewritten to Decimal (the "non-float" refusal became "non-Decimal"); the Monte Carlo draws p on a 1e-6 grid and gave 85 of 2000 repetitions with a G3 pass (bound 0.065).
- **Files modified:** `src/research/multiplicity.py`, `tests/test_research_multiplicity.py`
- **Commit:** d44d6a1

**2. [Plan note] Task 3 and Task 4 witness edits share one commit**
- The plan says the witness tests land with the Task 3 documents (the gates would be red between them), so commit f80e0a2 holds both; the addendum and the registration test are commit 059a42d.

**3. [Plan note] Hypothesis id format**
- The set builder returns strings `strategy_id/parameter_set_id` rather than tuples; "duplicate after normalization" is whitespace normalization of the string id. The 48 ids match the three grids (16 each, all distinct).

## Stop conditions

None tripped: the 48 ids match the three grids; no parameter-set hash moved (`git diff --stat 47c624d HEAD -- params tests/fixtures` is empty); Holm is stated and tested; the p = 1 convention was written under the user's adoption of item 4 in `16-DEC-V230.md`; no gate needed a different convention (DC-03 passes with D068 as the freeze row). No ExperimentRecord, no Holdout read or consumption, no O-03 run.

## Known Stubs

None. No stub, placeholder or skipped test was introduced. `gsd_run windows append` was not called.

## Threat Flags

None. No network endpoint, auth path or schema changed.

## Not done (out of scope by the plan)

The O-03b manifest and its freeze, the S1 constraint file and hash, the REEFUSDT diagnostic, the seeded block-bootstrap p-value producer, any run authorization, the six S0 and S1 bindings of plan 16-46, the G-cell derivation in `src/analytics/gates.py` (still PENDING_THRESHOLD_TBD), docker-marked tests (excluded by `-m "not docker"`).

## Tracker notes for the orchestrator (not edits)

(a) Plan 16-37 Task 1 reads `research-run-1-grid.json`, which does not exist; the grids are three files. (b) Plan 16-46 scope grows to six S0/S1 bindings and needs the p-value producer. (c) The protocol-gate cells in `src/analytics/gates.py` still say PENDING_THRESHOLD_TBD. (d) Order that follows: verify inventory and constraints, REEF diagnostic (Development, S0, no record), freeze the manifest with one REEF terminal declaration, then O-03. (e) The hypothesis files line 21 and DRAFT line 22 still say "frozen protocol v2.2.0"; they are history and pinned, the addendum states v2.3.0.

## Verification (real outputs in the evidence file)

`verify_decision_alignment.py all` ALL_PASS; `uv run pytest -m "not docker"` 6251 passed, 471 skipped, 28 deselected; `ruff check`, `ruff format --check`, `mypy src`, `uv lock --check` all exit 0; G1 and G5 sentences byte-identical to the base; every changed blob is LF.

## Self-Check: PASSED

Created files exist (multiplicity.py, its test, the addendum, the evidence file); commits fab893e, 85f4836, f80e0a2, 059a42d, d44d6a1 exist in `git log`.
