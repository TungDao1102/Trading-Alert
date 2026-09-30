---
phase: 11-decision-alignment
plan: 01
subsystem: research-protocol
tags: [research-protocol, ci-gate, pre-registration, holdout, holm-bonferroni, decisions]
status: complete

requires:
  - phase: 10-kill-gate-analytics
    provides: D030 kill-gate firing rule, Frozen-on clock parser, D029 freeze witnesses
provides:
  - Version-bound research-gate freeze step (header version = DECISIONS row = DOC_STATUS line)
  - Research protocol v1.1.0 (FROZEN, Frozen on unchanged, Amended on 2026-09-30, Supersedes v1.0.1) with numeric pre-registration G1-G5
  - DECISIONS row D043 and DOC_STATUS index/change-log entry
  - Append-only single-use holdout marker docs/research/holdout_consumed.json
  - scripts/decision_alignment/protocol.py gates PR-01..PR-10 and candidate_sha256()
affects: [11-02, 11-03, 13-data-foundation, 14-causal-simulator, 26-analytics-gates]

actuals:
  tokens: 12800
  tasks: 3
  commits: 3
plan_head_before: a153a1b37226c2e03b13fec7049a1877fc0d3fca
plan_head_after: 0c79a3a5a22d1492efaf19b9a027c9a364813321

tech-stack:
  added: []
  patterns:
    - "Version-bound freeze witnesses: the gate derives V from the header and requires the same V in DECISIONS and DOC_STATUS"
    - "Gate modules under scripts/decision_alignment/ return (name, ok, detail) tuples and expose pure text-in functions for negative tests"
    - "Workflow steps are tested by executing the real run block under bash against tmp_path witness copies"

key-files:
  created:
    - tests/test_research_gate_negative.py
    - tests/test_decision_alignment_protocol.py
    - scripts/decision_alignment/protocol.py
    - docs/research/holdout_consumed.json
  modified:
    - .github/workflows/research-gate.yml
    - docs/research/RESEARCH_PROTOCOL.md
    - docs/DECISIONS.md
    - docs/DOC_STATUS.md
    - docs/backtest/BACKTEST_SPEC.md
    - tests/test_kill_gate_docs.py

key-decisions:
  - "D043 recorded: protocol v1.1.0 frozen with the D032 pre-registration (100 pooled / 30 per fold trades, expectancy > 0 R with lower 95% bootstrap bound > 0, drawdown <= 20% of research equity, N = 25 per family, Holm-Bonferroni alpha 0.05 per family with ~14% cross-family residual, last-20% single-use holdout)"
  - "Frozen-on 2026-09-19 kept; Amended-on line added so the D013 six-month clock (earliest terminal 2027-03-19T00:00Z) is not restarted"
  - "Trade floor not lowered; defined on pooled Validation folds; feasibility left to Phase 13 dataset sizing because the trade rate is unmeasured until the Phase 14 simulator exists"
  - "Human role: may reject a passing candidate, may never pass a failing one; holdout consumption is keyed by candidate_sha256 in an append-only marker"

requirements-completed: [RSCH-01, RSCH-02]

coverage:
  - id: D1
    description: "Research-gate freeze step is version-bound and fails on any witness disagreement, including the half-frozen D029-only case"
    requirement: "RSCH-01"
    verification:
      - kind: unit
        ref: "tests/test_research_gate_negative.py (15 tests running the real step under bash)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Protocol v1.1.0 frozen in one change with header, D043 row and DOC_STATUS line agreeing; pinned kill-gate doc tests moved"
    requirement: "RSCH-01"
    verification:
      - kind: unit
        ref: "tests/test_kill_gate_docs.py, tests/test_kill_gate_clock.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "Numeric pre-registration (G1-G5), single-use holdout marker, no human pass override, intact D030 rule, machine-checked by gates PR-01..PR-10"
    requirement: "RSCH-02"
    verification:
      - kind: unit
        ref: "tests/test_decision_alignment_protocol.py (23 tests)"
        status: pass
    human_judgment: false
  - id: D4
    description: "Whether the pre-registered numbers (100/30 trades, N = 25, 40/40/20 split) are reachable at the eventual dataset depth"
    requirement: "RSCH-02"
    human_judgment: true
    rationale: "Trade frequency is unmeasured until the Phase 14 causal simulator exists; D043 records the shortfall-reporting rule"
---

# Phase 11 Plan 01: Protocol v1.1.0 Pre-registration and Version-bound Gate Summary

**Research protocol amended to v1.1.0 with numeric pre-registration (D032/D043) and a research-gate freeze step that reads the header version and requires the matching DECISIONS row and DOC_STATUS line.**

## Performance

- **Duration:** about 30 min
- **Completed:** 2026-09-30
- **Tasks:** 3 (1 tracer, 2 auto/tdd)
- **Files:** 10 (4 created, 6 modified)

## Accomplishments

- Closed the F3 gate defect: the freeze step derives V from `> **Protocol version:** vX.Y.Z`, escapes the dots and requires `protocol vV frozen` in DECISIONS plus a DOC_STATUS index line naming vV. The clock-parsed `Frozen on` grep line is kept verbatim and first.
- `tests/test_research_gate_negative.py` executes the real `Freeze check` run block under bash (Git bash, script written to a file) against synthetic triplets and the real repo files: 15 tests, none skipped.
- Froze v1.1.0 in one change (header, D043, DOC_STATUS, pinned tests); DECISIONS table split (audit F-119) repaired.
- Wrote the pre-registration body: 40/40/20 split with four walk-forward Validation folds, G1-G5, variant budget, Holm scope with the ~14% residual, consumed-marker rule, power note, D036/D037/D038/D039 alignment and one canonical quantization order.
- Added `docs/research/holdout_consumed.json` and `scripts/decision_alignment/protocol.py` (PR-01..PR-10, `candidate_sha256`).

## Task Commits

1. Task 1 (tracer): `a68e977` - version-bound freeze step plus negative test
2. Task 2: `4e31839` - v1.1.0 header, migration paragraph (cites `a68e97736e65b563c7ddbb8bf746d4225ad31f36`), D043, DOC_STATUS, pinned tests
3. Task 3: `0c79a3a` - pre-registration body, holdout marker, BACKTEST_SPEC pointers, gate module and tests

## Verification

- `pytest tests/test_decision_alignment_protocol.py tests/test_kill_gate_docs.py tests/test_kill_gate_clock.py tests/test_kill_gate_registration.py tests/test_research_gate_negative.py`: 63 passed, 0 skipped.
- `python -m scripts.decision_alignment.protocol`: 10 gates, 0 failed.
- `ruff check` on the new files: clean; `mypy scripts/decision_alignment/protocol.py`: clean.
- Task 2 command (adds `tests/test_analytics_files.py`): passes; its single skip is a pre-existing symlink test (`symlinks unavailable on this platform`), not in the gate tests.
- Wider docs/registry/report suites (`test_registry`, `test_backtest_*`, `test_analytics_*`): pass.
- Kill-gate section: only the "Because numeric acceptance thresholds remain TBD ..." sentence changed (as specified); the three condition lines, independence definition and consequence paragraph are unchanged versus `679825c`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Windows `bash -c` mangles backslash escapes**
- **Found during:** Task 1 (GREEN)
- **Issue:** Passing the freeze script through `bash -c` on Windows let command-line quoting drop the backslash in the `sed` dot-escape, so `v1.1.0` matched `v1x1x0` (the dots-escaped test failed).
- **Fix:** The test writes the extracted step to a file in `tmp_path` and runs `bash _freeze_step.sh`; the workflow text is unchanged and the file path is equivalent to what Actions runs.
- **Files modified:** tests/test_research_gate_negative.py
- **Commit:** a68e977

**2. [Ordering] Task 3 RED not committed separately**
- The docs/protocol text and `holdout_consumed.json` were written before the gate tests, so the module tests were never run against a missing module. RED was demonstrated after the fact by running `check_preregistration` / `check_no_human_pass` on the Task 2 protocol (15 and 6 problems respectively). The tracer and Task 2 followed the plan's single-commit acceptance (`git show --stat HEAD` lists only the planned files).

**Total deviations:** 1 auto-fix, 1 ordering note. **Impact:** none on scope or outputs.

## Issues Encountered

- Between Task 1 and Task 2 the real repository was intentionally inconsistent with the new gate (as the plan warned); nothing was pushed in that window.

## Known Stubs

None. The pre-registered numbers are documentation plus the PR- gates; executable analytics gate code (audit F-960, `src/analytics/gates.py`) is owned by Phase 26 and recorded in D043.

## Threat Flags

None. No new endpoints, auth paths or trust boundaries; threat register T-11-01..T-11-04 mitigated (version-bound gate with negative tests, holdout marker with duplicate detection, human-pass wording gated by PR-05, Frozen-on pinned by PR-02 and clock tests).

## Next Phase Readiness

Ready for 11-02. Open follow-ups recorded in D043: Phase 13 must size the dataset (or report the shortfall) against the 100-trade floor and freeze the research-universe manifest (11-03 creates the DRAFT manifest that protocol section 1 references); Phase 26 owns executable gate code. `docs/trading/RISK_MANAGEMENT.md` section 11 is cited as the canonical quantization statement and must carry the same order (owned by a later Phase 11 plan).

## Self-Check: PASSED

All created files exist on disk; commits a68e977, 4e31839, 0c79a3a found in git log; all task acceptance commands re-run green.
