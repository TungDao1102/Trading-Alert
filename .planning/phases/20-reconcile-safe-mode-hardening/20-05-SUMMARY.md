---
phase: 20-reconcile-safe-mode-hardening
plan: 05
subsystem: domain-vocabulary
tags: [rejection-reason, glossary, decision-alignment, EXEC-02]
requires: []
provides:
  - "RejectionReason.ENTRY_WITHOUT_PROTECTIVE (21 members)"
  - "GLOSSARY 9.1 with 21 codes; 9.3 row removed"
affects: [20-08, 20-11, 20-17, 20-22]
tech-stack:
  added: []
  patterns: ["enum promotion with unchanged string value"]
key-files:
  created: []
  modified:
    - src/domain/enums.py
    - src/execution/manager.py
    - docs/GLOSSARY.md
    - scripts/decision_alignment/bookkeeping.py
    - tests/test_domain_enums.py
    - tests/test_backtest_engine.py
    - tests/test_decision_alignment_bookkeeping.py
    - tests/test_phase19_gate.py
key-decisions:
  - "ENTRY_WITHOUT_PROTECTIVE promoted into RejectionReason with the string value unchanged (D-10, G3-005, D044 item 1)."
  - "Divergence-kind and SAFE_MODE copies in compare.py, fill_monitor.py, health.py, protection.py stay plain strings."
requirements-completed: []
duration: 25min
completed: 2026-10-21
status: complete
estimate:
  tokens: 50000
  tasks: 2
actuals:
  tokens: 3800
  tasks: 2
  commits: 3
plan_head_before: 9d8a9b0e6b4b532b525c64424dd37bebb0b679d7
plan_head_after: 08af274b79ed19727bf24ee886b000489504b60a
---

# Phase 20 Plan 05: ENTRY_WITHOUT_PROTECTIVE promotion Summary

`RejectionReason` now has 21 members: `ENTRY_WITHOUT_PROTECTIVE` is canonical, GLOSSARY 9.1 lists it, its 9.3 plain-string row is gone, and the manager constant is bound to the enum member with the emitted string unchanged.

## Tasks

| Task | Name | Commits |
|------|------|---------|
| 1 (tracer, tdd) | Enum member plus GLOSSARY 9.1 parity, proven by the GL gates | RED `ba56bd64`, GREEN `794b2693` |
| 2 (auto) | Manager uses the enum member; string copies stay plain | `08af274b` |

### Task 1
- RED: count pins moved to 21 (`tests/test_domain_enums.py`, `tests/test_backtest_engine.py`, `tests/test_decision_alignment_bookkeeping.py`, `tests/test_phase19_gate.py`), expected set and GLOSSARY-block token count updated, `PHASE_20_CODES` added to the GL-02 referenced-code assertion. Observed 5 failures before the GREEN commit.
- GREEN: member appended after `COST_TO_RISK_EXCEEDED` (docstring says 21); GLOSSARY section 9 intro and 9.2 counts changed to 21, the token added to the 9.1 block with a meaning sentence (entry fill without a confirmed protective stop; also a divergence kind and SAFE_MODE reason, 9.4; promoted in Phase 20, D044 item 1), the 9.3 row removed, 9.3 intro now says Phases 24 and 26; `ENTRY_WITHOUT_PROTECTIVE` dropped from `STRING_CODES` (GL-05). The 9.4 row is kept.
- Tracer gate: `tests/test_domain_enums.py tests/test_decision_alignment_bookkeeping.py tests/test_phase19_gate.py tests/test_backtest_engine.py` pass and `scripts/verify_decision_alignment.py all` prints `ALL_PASS all` (GL-01..GL-06 included).

### Task 2
- `src/execution/manager.py`: `_ENTRY_WITHOUT_PROTECTIVE: str = RejectionReason.ENTRY_WITHOUT_PROTECTIVE.value` (the `RejectionReason` import already existed).
- New test `test_entry_without_protective_is_one_vocabulary_in_three_roles` asserts the manager constant, `DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE` (compare.py) and `SAFE_MODE_ENTRY_WITHOUT_PROTECTIVE` (protection.py) all equal the enum value, plus a source check that the manager binds the enum member.
- Task 2 had no separate RED step (a behavior-neutral refactor; value equalities hold before and after).

## Verification (real results)

- `uv run pytest -m "not docker" tests/test_domain_enums.py tests/test_decision_alignment_bookkeeping.py tests/test_phase19_gate.py tests/test_backtest_engine.py tests/test_execution_attach.py`: 210 passed.
- `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- `uv run mypy src`: no issues in 214 files. `uv run ruff check`: all checks passed; `ruff format --check` on the three touched Python files: already formatted.
- Acceptance: `docs/DECISIONS.md`, `docs/research/`, `src/execution/fill_monitor.py`, `src/ops/health.py`, `src/reconcile/compare.py`, `pyproject.toml`, `uv.lock` unmodified; no fixture or research record regenerated.
- The full suite was not run (orchestrator owns that).

## Deviations from Plan

None to the plan's content. Two environment notes:

- The worktree base `9d8a9b0e` predates the Phase 20 plan commits, so the plan and phase documents were absent from the checkout. I read `20-05-PLAN.md` read-only from the `develop` branch of the same repository (`git show develop:<path>`). `develop` contains only `.planning`, config and unrelated `src/execution/protection*`, `execution_limits`, `transitions` changes since the base; none of this plan's files differ there, so work at the original base is valid and merges cleanly. `20-REVIEW-RESOLUTIONS.md` and `20-CONTEXT.md` were not read in full; the plan's own text was sufficient (the plan is `depends_on: []` and its D-10 content is self-contained).
- Line endings: every touched file is pure CRLF; edits were done bytes-aware and re-checked with `file`.

## Known Stubs

None.

## Threat Flags

None. T-20-11 mitigated (string value unchanged, GL-01..GL-06 gates and the three-role equality test); T-20-SC mitigated (no dependency change).

## Self-Check: PASSED

- Commits `ba56bd64`, `794b2693`, `08af274b` exist on `worktree-agent-ab7ed2b24cec8511c`.
- `RejectionReason.ENTRY_WITHOUT_PROTECTIVE` present; GLOSSARY 9.1 holds 21 tokens; 9.3 has no `ENTRY_WITHOUT_PROTECTIVE` row; 9.4 row kept.
